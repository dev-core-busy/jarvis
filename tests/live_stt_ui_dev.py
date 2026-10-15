#!/usr/bin/env python3
"""Live auf DEV, ECHTER Browser: Mic-Knopf im Chat -> stt.js -> /api/stt -> Nachricht.

jsdom kennt weder MediaRecorder noch Pegelmessung – test_stt_lokal.js prueft
stt.js dort nur gegen Attrappen. Hier laeuft die ganze Kette in Chrome:
die AUSGELIEFERTE /chat-Seite, der echte Klick auf #btn-mic, ein Mikrofon aus
einer WAV-Datei (``--use-file-for-fake-audio-capture``), die Pegelmessung, die
das Ende selbst erkennen muss, und der echte Endpunkt mit dem lokalen Whisper.

Veraendert NICHTS: die Chat-Nachricht, die am Ende entsteht, wird an
``WebSocket.send`` abgefangen (type ``task``) und NICHT verschickt – sonst
startete ein Agentenlauf auf dem Testkonto.

Gemessen wird auch, wohin der Browser Netzverkehr schickt: nur an den eigenen
Server (Network.requestWillBeSent).

Aufruf: cd /opt/jarvis && runuser -u jarvis -- env PYTHONDONTWRITEBYTECODE=1 \
            HOME=/home/jarvis venv/bin/python tests/live_stt_ui_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

BASIS = "https://127.0.0.1"
SATZ = "Wie wird das Wetter morgen in Berlin?"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


from backend import main as M  # noqa: E402

BENUTZER = ziele.wert("JARVIS_DEV_TESTUSER")
TOKEN = M.generate_token(BENUTZER)

# ── Testmaterial vom Erzeuger: TTS -> WAV mit Pausen davor und danach ────────
ARBEIT = Path(tempfile.mkdtemp(prefix="stt-ui-", dir=str(Path.home())))
os.chmod(ARBEIT, 0o700)
r = urllib.request.Request(BASIS + "/api/tts", data=json.dumps({"text": SATZ}).encode(), method="POST")
r.add_header("Authorization", "Bearer " + TOKEN)
r.add_header("Content-Type", "application/json")
try:
    with urllib.request.urlopen(r, context=CTX, timeout=120) as a:
        (ARBEIT / "satz.mp3").write_bytes(a.read())
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH (Exit 2): /api/tts lieferte kein Audio: {e}")
    shutil.rmtree(ARBEIT, ignore_errors=True)
    sys.exit(2)
WAV = ARBEIT / "mikrofon.wav"
# 1 s Stille, Satz, 5 s Stille – die Pegelmessung muss das Ende SELBST finden.
subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-t", "1", "-i", "anullsrc=r=48000:cl=mono",
                "-i", str(ARBEIT / "satz.mp3"),
                "-f", "lavfi", "-t", "5", "-i", "anullsrc=r=48000:cl=mono",
                "-filter_complex", "[1:a]aresample=48000,aformat=channel_layouts=mono[s];"
                                   "[0:a][s][2:a]concat=n=3:v=0:a=1",
                "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(WAV)],
               check=True, timeout=60)

s = socket.socket()
s.bind(("127.0.0.1", 0))
PORT = s.getsockname()[1]
s.close()
PROFIL = ARBEIT / "profil"
chrome = subprocess.Popen(
    ["/usr/bin/google-chrome", "--headless=new", "--no-sandbox", "--disable-gpu",
     f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
     f"--user-data-dir={PROFIL}", "--window-size=1100,900",
     "--ignore-certificate-errors",
     "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
     f"--use-file-for-fake-audio-capture={WAV}%noloop",
     "--autoplay-policy=no-user-gesture-required", "about:blank"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def ende(code):
    chrome.kill()
    shutil.rmtree(ARBEIT, ignore_errors=True)
    print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
    sys.exit(code)


def ziel_ws():
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as a:
                for t in json.loads(a.read()):
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


print("Live DEV (Chrome): Mic-Knopf im Chat")
ws = ziel_ws()
if not ws:
    print("ABBRUCH (Exit 2): kein CDP-Ziel")
    ende(2)
try:
    from websockets.sync.client import connect
except Exception:  # noqa: BLE001
    print("ABBRUCH (Exit 2): python-websockets fehlt im venv.")
    ende(2)

_id = [0]
NETZ = []


def cdp(sock, m, **p):
    _id[0] += 1
    sock.send(json.dumps({"id": _id[0], "method": m, "params": p}))
    while True:
        d = json.loads(sock.recv(timeout=60))
        if d.get("method") == "Network.requestWillBeSent":
            NETZ.append(d["params"]["request"]["url"])
        if d.get("id") == _id[0]:
            return d.get("result", {})


def js(sock, a):
    r = cdp(sock, "Runtime.evaluate", expression=a, returnByValue=True, awaitPromise=True)
    if "exceptionDetails" in r:
        e = ((r["exceptionDetails"].get("exception") or {}).get("description")
             or r["exceptionDetails"].get("text") or "?")
        return "JS-WURF: " + str(e)[:200]
    return (r.get("result") or {}).get("value")


VORLAUF = """
localStorage.setItem('jarvis_chat_token', %s);
localStorage.setItem('jarvis_token', %s);
window.__fehler = '';
window.addEventListener('error', function (e) { window.__fehler += e.message + ' | '; });
window.__tasks = [];
window.__sttAufrufe = 0;
(function () {
  var orig = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) {
    try { var m = JSON.parse(d); if (m && m.type === 'task') { window.__tasks.push(m.text); return; } } catch (e) {}
    return orig.apply(this, arguments);
  };
  var f = window.fetch;
  window.fetch = function (u) { if (String(u).indexOf('/api/stt') === 0) window.__sttAufrufe++; return f.apply(this, arguments); };
})();
""" % (json.dumps(TOKEN), json.dumps(TOKEN))

try:
    with connect(ws, max_size=80 * 1024 * 1024) as sock:
        cdp(sock, "Page.enable")
        cdp(sock, "Network.enable")
        cdp(sock, "Page.addScriptToEvaluateOnNewDocument", source=VORLAUF)
        cdp(sock, "Page.navigate", url=BASIS + "/chat")
        time.sleep(4.0)

        lage = js(sock, "({pfad: location.pathname, stt: !!window.JarvisSTT,"
                        " knopf: !!document.getElementById('btn-mic'),"
                        " sichtbar: (function(){var b=document.getElementById('btn-mic');"
                        " return !!b && getComputedStyle(b).display !== 'none';})()})")
        if not isinstance(lage, dict) or lage.get("pfad") != "/chat":
            print(f"ABBRUCH (Exit 2): /chat nicht geladen: {lage}")
            ende(2)
        check("(Positivkontrolle) /chat geladen, angemeldet", True)
        check("stt.js ist auf der Seite geladen", lage.get("stt") is True)
        check("Mic-Knopf ist sichtbar (stt.js stand VOR chat.js)", lage.get("sichtbar") is True, str(lage))

        t0 = time.time()
        js(sock, "document.getElementById('btn-mic').click()")
        time.sleep(0.5)
        check("Knopf zeigt die Aufnahme an", js(sock, "document.getElementById('btn-mic').classList.contains('recording')") is True)

        # Kein zweiter Klick: das Ende muss die Pegelmessung selbst finden.
        # Ende = weder Aufnahme noch Erkennung aktiv. Der Zwischenzustand
        # 'transcribing' (Aufnahme vorbei, Server erkennt) wird dabei mitgemessen.
        ergebnis = None
        erkennung_gesehen = None
        while time.time() - t0 < 40:
            z = js(sock, "(function(){var b=document.getElementById('btn-mic');"
                         " return {n: window.__tasks.length, rec: b.classList.contains('recording'),"
                         " erk: b.classList.contains('transcribing'), titel: b.title};})()")
            if not isinstance(z, dict):
                break
            if z.get("erk") and erkennung_gesehen is None:
                erkennung_gesehen = z
            if z.get("n") or (not z.get("rec") and not z.get("erk")):
                ergebnis = js(sock, "({tasks: window.__tasks, stt: window.__sttAufrufe,"
                                    " fehler: window.__fehler,"
                                    " toast: (document.querySelector('.attach-toast.show')||{}).textContent||''})")
                break
            time.sleep(0.5)
        dauer = time.time() - t0
        if not isinstance(ergebnis, dict):
            check("Aufnahme endet von selbst (ohne zweiten Klick)", False, f"nach {dauer:.0f} s noch aktiv")
            ende(1)
        # Ein abgefangenes task kommt kurz nach dem Ende – einmal nachlesen
        time.sleep(1.0)
        ergebnis["tasks"] = js(sock, "window.__tasks")
        print(f"  ... Ende nach {dauer:.1f} s, Nachricht: {ergebnis.get('tasks')}, Hinweis: {ergebnis.get('toast')!r}")
        check("Aufnahme endet von selbst (ohne zweiten Klick)", dauer < 30, f"{dauer:.1f} s")
        check("waehrend der Erkennung: eigener Zustand, nicht mehr 'Aufnahme'",
              bool(erkennung_gesehen) and not erkennung_gesehen.get("rec"), str(erkennung_gesehen))
        check("... mit Text im Tooltip (nicht nur Farbe)",
              bool(erkennung_gesehen) and "erkannt" in (erkennung_gesehen.get("titel") or ""),
              str(erkennung_gesehen))
        check("genau ein Upload an /api/stt", ergebnis.get("stt") == 1, str(ergebnis.get("stt")))
        tasks = ergebnis.get("tasks") or []
        text = (tasks[0] if tasks else "").lower()
        check("erkannter Satz wird als Chat-Nachricht gesendet", "wetter" in text and "berlin" in text, repr(tasks))
        check("keine JS-Fehler auf der Seite", not ergebnis.get("fehler"), ergebnis.get("fehler", ""))
        check("Knopf ist wieder im Ruhezustand",
              js(sock, "(function(){var c=document.getElementById('btn-mic').classList;"
                       " return !c.contains('recording') && !c.contains('transcribing');})()") is True)

        fremd = sorted({u for u in NETZ if not u.startswith(BASIS) and not u.startswith("data:")
                        and not u.startswith("blob:") and not u.startswith("about:")})
        check("kein Netzverkehr an fremde Adressen", not fremd, ", ".join(fremd[:5]))
except Exception as e:  # noqa: BLE001
    check("Messlauf ohne Ausnahme", False, repr(e)[:200])
    ende(1)

ende(1 if _fail else 0)
