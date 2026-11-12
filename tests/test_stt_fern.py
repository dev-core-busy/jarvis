#!/usr/bin/env python3
"""Waechter: Spracherkennung ueber den Fern-Dienst (backend/stt_fern.py).

Hintergrund (2026-10-22): die lokale Erkennung (faster-whisper ``small``) war
auf Windows-Laptops "inakzeptabel" – gemessen 14,5 % Wortfehler gegen 9,0 % beim
GPU-Dienst. Der Dienst spricht JSON ueber WebSocket (start/ready, audio-Stuecke
mit endOfUtterance, final, stop/stopped).

 A  Adresse: nur ws/wss mit Host, keine Zugangsdaten, kein Leerraum; die
    /health-Adresse wird richtig abgeleitet.
 B  Protokoll gegen einen Attrappen-Dienst auf 127.0.0.1, der die echten
    Antworten gibt: start mit 16 kHz/mono/pcm_s16le, fortlaufende Sequenz,
    endOfUtterance NUR am letzten und nie leeren Stueck, das gesamte Audio kommt
    an, der final-Text kommt zurueck, stop wird gesendet. Ein error des Dienstes
    und ein ausbleibendes final werfen (kein stiller Leertext).
 C  Einbindung, gemessen an der WIRKUNG: ``_transcribe_audio`` wird per AST aus
    main.py geschnitten und mit Attrappen ausgefuehrt – bei "fern" antwortet der
    Dienst und das lokale Modell wird NICHT geladen; scheitert der Dienst, rechnet
    das lokale Modell; bei "lokal" wird der Dienst nicht gefragt.
 D  Zugangstoken (2026-11-12, der wss-Dienst verlangt eines): es geht als
    ``Authorization: Bearer`` an WebSocket UND /health, aber NUR ueber wss;
    ``_transcribe_audio`` reicht das gespeicherte Token durch; die Endpunkte
    (per AST geschnitten) geben den Wert nie heraus, lehnen ein Token mit ws://
    ab, behalten es bei leerem Feld nur fuer DASSELBE Ziel (sonst liesse es
    sich per Adressaenderung an einen fremden Host schicken), entfernen es auf
    Wunsch und schreiben es nicht ins Sicherheitsprotokoll. Der Tresor
    verpackt ``stt_fern_token``.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import base64
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import threading
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

try:
    import websockets
except ImportError:
    print("ABBRUCH (Exit 2): websockets nicht installiert")
    sys.exit(2)
if not shutil.which("ffmpeg"):
    print("ABBRUCH (Exit 2): ffmpeg fehlt")
    sys.exit(2)

from backend import stt_fern  # noqa: E402

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   " + label)
    else:
        _fail += 1
        print("  FAIL " + label + (" – " + str(detail) if detail else ""))


# ── A: Adresse ──────────────────────────────────────────────────────────────
print("A  Adresse")


def wirft(url):
    try:
        stt_fern.url_pruefen(url)
        return False
    except ValueError:
        return True


check(stt_fern.url_pruefen(" ws://stt.beispiel.de:8090/ws/stt ") == "ws://stt.beispiel.de:8090/ws/stt",
      "ws-Adresse wird angenommen und getrimmt")
check(not wirft("wss://stt.beispiel.de/ws/stt"), "wss wird angenommen")
for schlecht, grund in (("", "leer"), ("http://stt.beispiel.de/ws/stt", "falsches Schema"),
                        ("ws:///ws/stt", "ohne Host"), ("ws://a b.de/ws", "Leerraum"),
                        ("ws://nutzer:geheim@stt.beispiel.de/ws/stt", "Zugangsdaten"),
                        ("ws://x.de/" + "a" * 600, "ueberlang")):
    check(wirft(schlecht), f"abgewiesen: {grund}")
check(stt_fern.health_url("ws://stt.beispiel.de:8090/ws/stt") == "http://stt.beispiel.de:8090/health",
      "health-Adresse aus ws", stt_fern.health_url("ws://stt.beispiel.de:8090/ws/stt"))
check(stt_fern.health_url("wss://stt.beispiel.de/basis/ws/stt") == "https://stt.beispiel.de/basis/health",
      "health-Adresse aus wss mit Basispfad", stt_fern.health_url("wss://stt.beispiel.de/basis/ws/stt"))


# ── Attrappen-Dienst ────────────────────────────────────────────────────────
class Dienst:
    """Spricht das Protokoll wie der echte Dienst. ``art`` steuert das Verhalten."""

    def __init__(self):
        self.art = "gut"
        self.nachrichten = []
        self.koepfe = []
        self.loop = asyncio.new_event_loop()
        self.port = None
        bereit = threading.Event()

        async def behandeln(ws):
            req = getattr(ws, "request", None)
            self.koepfe.append(dict(req.headers) if req is not None else {})
            puffer = b""
            async for roh in ws:
                m = json.loads(roh)
                self.nachrichten.append(m)
                t = m.get("type")
                if t == "start":
                    await ws.send(json.dumps({"type": "ready", "sessionId": m["sessionId"]}))
                elif t == "audio":
                    if "pcmBase64" not in m:
                        continue          # wie der echte Dienst: ohne Audio verworfen
                    puffer += base64.b64decode(m["pcmBase64"])
                    if m.get("endOfUtterance"):
                        if self.art == "fehler":
                            await ws.send(json.dumps({"type": "error", "sessionId": m["sessionId"],
                                                      "message": "Modell nicht geladen"}))
                        elif self.art == "stumm":
                            pass
                        else:
                            await ws.send(json.dumps({"type": "final", "sessionId": m["sessionId"],
                                                      "sequence": m["sequence"],
                                                      "text": f"erkannt {len(puffer)} bytes",
                                                      "fullText": ""}))
                elif t == "stop":
                    await ws.send(json.dumps({"type": "stopped", "sessionId": m["sessionId"]}))

        async def starten():
            srv = await websockets.serve(behandeln, "127.0.0.1", 0)
            self.port = srv.sockets[0].getsockname()[1]
            bereit.set()

        threading.Thread(target=lambda: (self.loop.run_until_complete(starten()), self.loop.run_forever()),
                         daemon=True).start()
        if not bereit.wait(10):
            print("ABBRUCH (Exit 2): Attrappen-Dienst startet nicht")
            sys.exit(2)

    @property
    def url(self):
        return f"ws://127.0.0.1:{self.port}/ws/stt"


def tonaufnahme(pfad, sekunden=1.3):
    """WAV 48 kHz mono – wird vom Code selbst per ffmpeg auf 16 kHz gebracht."""
    with wave.open(pfad, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        n = int(48000 * sekunden)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 48000)))
                               for i in range(n)))


dienst = Dienst()
tmp = tempfile.mkdtemp(prefix="stt_fern_")
aufnahme = os.path.join(tmp, "a.wav")
tonaufnahme(aufnahme)
erwartet_bytes = len(stt_fern.pcm_aus_datei(aufnahme))

# ── B: Protokoll ────────────────────────────────────────────────────────────
print("\nB  Protokoll")
check(abs(erwartet_bytes - int(1.3 * 32000)) < 3200,
      "(Positivkontrolle) ffmpeg liefert 16-kHz-PCM in erwarteter Laenge", erwartet_bytes)
text = stt_fern.transkribieren(aufnahme, dienst.url, "de")
ms = list(dienst.nachrichten)
start = next((m for m in ms if m.get("type") == "start"), {})
audio = [m for m in ms if m.get("type") == "audio"]
check(start.get("sampleRate") == 16000 and start.get("channels") == 1 and start.get("format") == "pcm_s16le"
      and start.get("language") == "de", "start traegt 16 kHz, mono, pcm_s16le, Sprache", start)
check(len(audio) >= 2, "Audio in mehreren Stuecken", len(audio))
check([m.get("sequence") for m in audio] == list(range(1, len(audio) + 1)), "Sequenz fortlaufend ab 1")
check([bool(m.get("endOfUtterance")) for m in audio] == [False] * (len(audio) - 1) + [True],
      "endOfUtterance genau am letzten Stueck")
check(all(m.get("pcmBase64") for m in audio), "kein Stueck ohne Audio (sonst verwirft der Dienst es)")
gesendet = sum(len(base64.b64decode(m.get("pcmBase64") or "")) for m in audio)
check(gesendet == erwartet_bytes, "das gesamte Audio kommt an", f"{gesendet} statt {erwartet_bytes}")
check(text == f"erkannt {erwartet_bytes} bytes", "final-Text wird zurueckgegeben", text)
check(any(m.get("type") == "stop" for m in ms), "Sitzung wird mit stop beendet")
check(len({m.get("sessionId") for m in ms}) == 1, "eine Sitzungskennung je Aufnahme")

dienst.nachrichten.clear()
stt_fern.transkribieren(aufnahme, dienst.url, None)
start2 = next((m for m in dienst.nachrichten if m.get("type") == "start"), {})
check(start2.get("language") == "de", "ohne Sprachangabe wird de gesendet", start2.get("language"))
check(start2.get("sessionId") != start.get("sessionId"), "jede Aufnahme bekommt eine neue Sitzung")


def wurf(art, frist=None):
    dienst.art = art
    alt = stt_fern.FRIST_GRUND_S
    if frist is not None:
        stt_fern.FRIST_GRUND_S = frist
    try:
        stt_fern.transkribieren(aufnahme, dienst.url, "de")
        return None
    except Exception as e:  # noqa: BLE001
        return e
    finally:
        stt_fern.FRIST_GRUND_S = alt
        dienst.art = "gut"


e = wurf("fehler")
check(e is not None and "Modell nicht geladen" in str(e), "error des Dienstes wirft mit dessen Meldung", repr(e))
e = wurf("stumm", frist=1)
check(isinstance(e, (asyncio.TimeoutError, TimeoutError)), "ausbleibendes final wirft (kein Leertext)", repr(e))
e = None
try:
    stt_fern.transkribieren(aufnahme, "ws://127.0.0.1:1/ws/stt", "de")
except Exception as x:  # noqa: BLE001
    e = x
check(e is not None, "unerreichbarer Dienst wirft")

# ── C: Einbindung in _transcribe_audio ──────────────────────────────────────
print("\nC  Einbindung in main._transcribe_audio")
quelle = open(os.path.join(REPO, "backend", "main.py"), encoding="utf-8").read()
baum = ast.parse(quelle)
fn = [n for n in baum.body if isinstance(n, ast.FunctionDef) and n.name == "_transcribe_audio"]
if len(fn) != 1:
    print("ABBRUCH (Exit 2): _transcribe_audio nicht genau einmal gefunden")
    sys.exit(2)
code = compile(ast.Module(body=fn, type_ignores=[]), "main._transcribe_audio", "exec")


class Cfg:
    def __init__(self, werte):
        self.werte = werte

    def get_setting(self, k, d=None):
        return self.werte.get(k, d)


class Segment:
    def __init__(self, t):
        self.text = t


class Modell:
    def __init__(self):
        self.aufrufe = 0

    def transcribe(self, pfad, **kw):
        self.aufrufe += 1
        return [Segment("lokal erkannt")], type("I", (), {"language": "de", "language_probability": 1.0})()


def lauf(werte):
    modell = Modell()
    geladen = []
    ns = {"config": Cfg(werte), "_tr_log": lambda *a, **k: None, "_stt_fern": stt_fern,
          "_get_whisper_model": lambda source="chat": geladen.append(source) or modell,
          "wa_log": lambda *a, **k: None}
    exec(code, ns)
    # Ein Wurf ist hier ein BEFUND (z. B. fehlender Rueckfall), kein Absturz –
    # sonst endete der Waechter ohne Bilanzzeile.
    try:
        text = ns["_transcribe_audio"](aufnahme, "de", "Jarvis Sprachsteuerung:", "voice_browser")
    except Exception as e:  # noqa: BLE001
        text = f"<wirft {type(e).__name__}>"
    return text, modell, geladen


t, m, g = lauf({"stt_quelle": "lokal"})
check(t == "lokal erkannt" and m.aufrufe == 1, "(Positivkontrolle) lokal: das lokale Modell rechnet", t)
dienst.nachrichten.clear()
t, m, g = lauf({"stt_quelle": "lokal", "stt_fern_url": dienst.url})
check(not dienst.nachrichten, "lokal: der Dienst wird nicht gefragt, auch wenn eine Adresse steht")
dienst.nachrichten.clear()
t, m, g = lauf({"stt_quelle": "fern", "stt_fern_url": dienst.url})
check(t == f"erkannt {erwartet_bytes} bytes", "fern: der Text kommt vom Dienst", t)
check(m.aufrufe == 0 and not g, "fern: das lokale Modell wird weder geladen noch benutzt", (m.aufrufe, g))
t, m, g = lauf({"stt_quelle": "fern", "stt_fern_url": "ws://127.0.0.1:1/ws/stt"})
check(t == "lokal erkannt" and m.aufrufe == 1, "fern unerreichbar: das lokale Modell springt ein", t)
dienst.art = "fehler"
t, m, g = lauf({"stt_quelle": "fern", "stt_fern_url": dienst.url})
dienst.art = "gut"
check(t == "lokal erkannt", "fern meldet Fehler: das lokale Modell springt ein", t)
t, m, g = lauf({"stt_quelle": "unsinn", "stt_fern_url": dienst.url})
check(t == "lokal erkannt", "unbekannte Quelle gilt als lokal", t)

# ── D: Zugangstoken ─────────────────────────────────────────────────────────
print("\nD  Zugangstoken")
TOK = "probe" + "ab12" * 8
WSS = f"wss://127.0.0.1:{dienst.port}/ws/stt"


def _auth_zuletzt():
    """Authorization-Kopfsatz der letzten Verbindung zur Attrappe (None = keiner)."""
    k = dienst.koepfe[-1] if dienst.koepfe else {}
    return {a.lower(): b for a, b in k.items()}.get("authorization")


# Der echte Aufrufweg: websockets.connect bekommt die wss-Adresse und die
# Kopfsaetze; die Attrappe spricht nur ws, also wird NUR das Schema getauscht.
_echt_connect = websockets.connect
connect_aufrufe = []


def _connect_mitschnitt(url, *a, **kw):
    connect_aufrufe.append((url, dict(kw.get("additional_headers") or {})))
    return _echt_connect(url.replace("wss://", "ws://", 1), *a, **kw)


websockets.connect = _connect_mitschnitt
try:
    dienst.koepfe.clear()
    t = stt_fern.transkribieren(aufnahme, WSS, "de", TOK)
    check(t == f"erkannt {erwartet_bytes} bytes" and dienst.koepfe,
          "(Positivkontrolle) wss-Lauf ueber den Mitschnitt gelingt", t)
    check(_auth_zuletzt() == "Bearer " + TOK, "wss: Token kommt als Bearer-Kopfsatz beim Dienst an", _auth_zuletzt())
    check(bool(connect_aufrufe) and TOK not in connect_aufrufe[-1][0], "Token steht nicht in der Adresse")
    dienst.koepfe.clear()
    stt_fern.transkribieren(aufnahme, dienst.url, "de", TOK)
    check(bool(dienst.koepfe) and _auth_zuletzt() is None, "ws: das Token geht NICHT im Klartext hinaus",
          _auth_zuletzt())
    dienst.koepfe.clear()
    stt_fern.transkribieren(aufnahme, WSS, "de", "")
    check(bool(dienst.koepfe) and _auth_zuletzt() is None, "ohne Token kein Authorization-Kopfsatz",
          _auth_zuletzt())

    # _transcribe_audio reicht das gespeicherte Token durch
    dienst.koepfe.clear()
    t, m, g = lauf({"stt_quelle": "fern", "stt_fern_url": WSS, "stt_fern_token": TOK})
    check(t == f"erkannt {erwartet_bytes} bytes" and _auth_zuletzt() == "Bearer " + TOK,
          "_transcribe_audio: gespeichertes Token erreicht den Dienst", (t, _auth_zuletzt()))
finally:
    websockets.connect = _echt_connect

# /health: Kopfsatz ueber den echten gesundheit()-Weg (Opener abgefangen)
_echt_opener = stt_fern.urllib.request.build_opener
anfragen = []


class _Antwort:
    def read(self, n=-1):
        return json.dumps({"status": "ok", "modelPath": "/m/large-v3", "device": "cuda"}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Opener:
    def open(self, anfrage, timeout=None):
        anfragen.append(anfrage)
        return _Antwort()


def _kopf_zuletzt():
    h = anfragen[-1] if anfragen else None
    if h is None or not hasattr(h, "get_header"):
        return "<keine Request-Instanz>"
    return h.get_header("Authorization")


stt_fern.urllib.request.build_opener = lambda *a, **k: _Opener()
try:
    g1 = stt_fern.gesundheit("wss://stt.beispiel.de/ws/stt", 1.0, TOK)
    check(g1.get("ok") and _kopf_zuletzt() == "Bearer " + TOK, "/health ueber wss traegt den Bearer-Kopfsatz",
          (g1, _kopf_zuletzt()))
    g2 = stt_fern.gesundheit("ws://stt.beispiel.de/ws/stt", 1.0, TOK)
    check(g2.get("ok") and _kopf_zuletzt() is None, "/health ueber ws: kein Token", _kopf_zuletzt())
finally:
    stt_fern.urllib.request.build_opener = _echt_opener

# Token-Pruefung und Zielvergleich
for schlecht, grund in (("a b", "Leerzeichen"), ("a\r\nX-Evil: 1", "Zeilenumbruch"), ("a\tb", "Tab"),
                        ("x" * (stt_fern.TOKEN_MAX + 1), "ueberlang")):
    try:
        stt_fern.token_pruefen(schlecht)
        check(False, f"Token abgewiesen: {grund}")
    except ValueError:
        check(True, f"Token abgewiesen: {grund}")
check(stt_fern.token_pruefen("  " + TOK + " ") == TOK, "Token wird getrimmt angenommen")
check(stt_fern.gleiches_ziel("wss://a.beispiel.de/ws/stt", "wss://A.beispiel.de:443/anders"),
      "gleiches Ziel: Host gross/klein und Standardport")
check(not stt_fern.gleiches_ziel("wss://a.beispiel.de/ws/stt", "wss://b.beispiel.de/ws/stt"),
      "anderer Host ist anderes Ziel")
check(not stt_fern.gleiches_ziel("wss://a.beispiel.de/ws/stt", "wss://a.beispiel.de:8443/ws/stt"),
      "anderer Port ist anderes Ziel")
check(not stt_fern.gleiches_ziel("", ""), "leere Adressen sind kein gleiches Ziel")

# Tresor verpackt das Feld
try:
    from backend import geheimnis_tresor as _tresor
    check(_tresor.ist_geheimer_name("stt_fern_token"), "Tresor verpackt stt_fern_token (BSI M5)")
except Exception as e:  # noqa: BLE001
    check(False, "Tresor importierbar", repr(e))

# Endpunkte: per AST geschnitten, Dekoratoren entfernt, mit Attrappen ausgefuehrt
ep = {n.name: n for n in baum.body if isinstance(n, ast.AsyncFunctionDef)
      and n.name in ("stt_einstellung_lesen", "stt_einstellung_setzen")}
if len(ep) != 2:
    print("ABBRUCH (Exit 2): STT-Endpunkte nicht gefunden")
    sys.exit(2)
for n in ep.values():
    n.decorator_list = []
ep_code = compile(ast.fix_missing_locations(ast.Module(body=list(ep.values()), type_ignores=[])),
                  "main.stt_endpunkte", "exec")


class SpeicherCfg(Cfg):
    def save_setting(self, k, v):
        self.werte[k] = v


class JR:
    def __init__(self, inhalt, status_code=200):
        self.inhalt, self.status_code = inhalt, status_code


class Anfrage:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


protokoll = []
gesund_token = []


class _Log:
    @staticmethod
    def ereignis(art, **kw):
        protokoll.append((art, kw))


def _ns(werte):
    ns = {"config": SpeicherCfg(werte), "_stt_fern": stt_fern, "JSONResponse": JR, "Request": object,
          "Depends": lambda f: None, "require_local_auth": None, "asyncio": asyncio, "_sicherheits_log": _Log}
    exec(ep_code, ns)
    return ns


def _gesundheit_attrappe(url, frist_s=3.0, token=""):
    gesund_token.append(token)
    return {"ok": True, "detail": "ok", "modell": "", "geraet": ""}


def setzen(werte, body):
    ns = _ns(werte)
    r = asyncio.run(ns["stt_einstellung_setzen"](Anfrage(body), user="admin"))
    return r, ns["config"].werte


_echt_gesundheit = stt_fern.gesundheit
stt_fern.gesundheit = _gesundheit_attrappe
try:
    A = "wss://stt.beispiel.de/ws/stt"
    r, w = setzen({}, {"quelle": "fern", "url": A, "token": TOK})
    check(r.status_code == 200 and w.get("stt_fern_token") == TOK, "(Positivkontrolle) Token wird gespeichert",
          (r.status_code, r.inhalt))
    check(bool(gesund_token) and gesund_token[-1] == TOK, "Erreichbarkeitspruefung benutzt das neue Token")
    check(TOK not in json.dumps(r.inhalt) and r.inhalt.get("token_gesetzt") is True,
          "Antwort meldet 'gesetzt', nicht den Wert", r.inhalt)
    check(bool(protokoll) and not any(TOK in json.dumps(kw, default=str) for _a, kw in protokoll),
          "Sicherheitsprotokoll enthaelt das Token nicht")
    ns = _ns({"stt_quelle": "fern", "stt_fern_url": A, "stt_fern_token": TOK})
    g = asyncio.run(ns["stt_einstellung_lesen"](user="admin")).inhalt
    check(g.get("token_gesetzt") is True and TOK not in json.dumps(g), "GET liefert nur 'gesetzt', nie den Wert", g)
    ns = _ns({"stt_quelle": "fern", "stt_fern_url": A})
    g = asyncio.run(ns["stt_einstellung_lesen"](user="admin")).inhalt
    check(g.get("token_gesetzt") is False, "GET ohne Token: 'nicht gesetzt'", g)

    r, w = setzen({"stt_quelle": "fern", "stt_fern_url": A, "stt_fern_token": TOK},
                  {"quelle": "fern", "url": A + "?x=1", "token": ""})
    check(w.get("stt_fern_token") == TOK and not r.inhalt.get("token_verworfen"),
          "leeres Feld, gleiches Ziel: Token bleibt", (w.get("stt_fern_token"), r.inhalt))
    r, w = setzen({"stt_quelle": "fern", "stt_fern_url": A, "stt_fern_token": TOK},
                  {"quelle": "fern", "url": "wss://fremd.beispiel.de/ws/stt", "token": ""})
    check(w.get("stt_fern_token") == "" and r.inhalt.get("token_verworfen") is True,
          "leeres Feld, anderer Host: Token wird verworfen (geht nicht mit)", (w.get("stt_fern_token"), r.inhalt))
    check(gesund_token[-1] == "", "fremder Host bekommt bei der Pruefung kein Token", gesund_token[-1])
    r, w = setzen({"stt_quelle": "fern", "stt_fern_url": A, "stt_fern_token": TOK},
                  {"quelle": "fern", "url": A, "token_entfernen": True})
    check(w.get("stt_fern_token") == "" and not r.inhalt.get("token_verworfen"),
          "token_entfernen loescht das Token", (w.get("stt_fern_token"), r.inhalt))
    r, w = setzen({}, {"quelle": "fern", "url": "ws://stt.beispiel.de:8090/ws/stt", "token": TOK})
    check(r.status_code == 400 and "stt_fern_token" not in w, "Token mit ws:// wird abgelehnt", (r.status_code, w))
    r, w = setzen({"stt_quelle": "fern", "stt_fern_url": A, "stt_fern_token": TOK},
                  {"quelle": "fern", "url": "ws://stt.beispiel.de/ws/stt", "token": ""})
    check(r.status_code == 200 and w.get("stt_fern_token") == "",
          "Wechsel auf ws:// (gleicher Host, anderer Port): Token geht nicht mit", (r.status_code, w))
    r, w = setzen({}, {"quelle": "fern", "url": A, "token": "a\nb"})
    check(r.status_code == 400 and "stt_fern_token" not in w, "Token mit Zeilenumbruch wird abgelehnt")
    r, w = setzen({}, {"quelle": "fern", "url": "ws://stt.beispiel.de:8090/ws/stt"})
    check(r.status_code == 200 and r.inhalt.get("verschluesselt") is False,
          "ws ohne Token: erlaubt, als unverschluesselt gemeldet", r.inhalt)
finally:
    stt_fern.gesundheit = _echt_gesundheit

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
