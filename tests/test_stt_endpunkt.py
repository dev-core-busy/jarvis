#!/usr/bin/env python3
"""Waechter: ``POST /api/stt`` – Spracheingabe aus dem Browser, nur lokal erkannt.

Hintergrund (todo.txt, Datenschutz STT, 2026-09-29): Mic-Knopf im Chat und der
Avatar nutzten ``window.SpeechRecognition``; Chrome/Edge schicken das Audio
dabei an die Cloud von Google bzw. Microsoft. Seit 2026-10-02 nimmt der Browser
nur auf (``frontend/js/stt.js``) und dieser Endpunkt erkennt mit dem lokalen
Whisper.

Gemessen wird die WIRKUNG, nicht das Vorkommen: die Funktion wird per AST aus
``backend/main.py`` geschnitten und mit Attrappen AUSGEFUEHRT (``main.py`` selbst
zu importieren wuerde den ganzen Dienst starten). Geprueft wird u.a.:

  * nur angemeldete Benutzer (``Depends(require_auth)``),
  * die Aufnahme liegt waehrend der Erkennung als 0600-Datei vor und ist danach
    WEG – auch wenn die Erkennung wirft,
  * die Klammertexte von ``_transcribe_audio`` landen nie als "erkannter Text"
    beim Browser (sonst stuende "[Keine Sprache erkannt]" als Nachricht im Chat),
  * leere/zu grosse Aufnahme und fehlendes Modell erreichen Whisper gar nicht,
  * ``lang`` ist auf de/en begrenzt, die Dateiendung folgt dem Content-Type.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import os
import stat
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MAIN = WURZEL / "backend" / "main.py"
ROUTE = "/api/stt"

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def abbruch(grund):
    print(f"ABBRUCH (Exit 2): {grund}")
    sys.exit(2)


# ── Funktion und Konstanten aus main.py schneiden ───────────────────────────
try:
    baum = ast.parse(MAIN.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    abbruch(f"main.py nicht lesbar: {e}")


def _route_von(fn):
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                and d.args and isinstance(d.args[0], ast.Constant)):
            return d.func.attr, d.args[0].value
    return None


treffer = [n for n in baum.body if isinstance(n, ast.AsyncFunctionDef)
           and _route_von(n) == ("post", ROUTE)]
konstanten = [n for n in baum.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id.upper().startswith("_STT_") for t in n.targets)]
# Seit Code-Review 2026-10-07 liest der Endpunkt den Rumpf ueber den Helfer
helfer = [n for n in baum.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_rumpf_mit_deckel"]

print("Positivkontrolle")
check(f"genau EIN Endpunkt POST {ROUTE}", len(treffer) == 1, f"gefunden: {len(treffer)}")
check("Konstanten _STT_* gefunden", len(konstanten) >= 2, f"gefunden: {len(konstanten)}")
if len(treffer) != 1 or len(konstanten) < 2:
    abbruch("Endpunkt nicht eindeutig gefunden – keine Aussage moeglich")
fn = treffer[0]

# ── Berechtigung: Depends(require_auth) als Parameter-Vorgabe ───────────────
print("\nBerechtigung")
vorgaben = fn.args.defaults + [d for d in fn.args.kw_defaults if d is not None]
auth = [d for d in vorgaben if isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
        and d.func.id == "Depends" and d.args and isinstance(d.args[0], ast.Name)
        and d.args[0].id == "require_auth"]
check("Endpunkt haengt an Depends(require_auth)", len(auth) == 1)

# ── Ausfuehrbar machen ──────────────────────────────────────────────────────
fn.decorator_list = []
modul = ast.Module(body=konstanten + helfer + [fn], type_ignores=[])
ast.fix_missing_locations(modul)


class JSONResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


class Anfrage:
    def __init__(self, daten=b"", lang=None, typ="audio/webm;codecs=opus"):
        self._daten = daten
        self.query_params = {} if lang is None else {"lang": lang}
        self.headers = {"content-type": typ} if typ else {}

    async def body(self):
        return self._daten

    async def stream(self):
        # wie Starlette: der Rumpf in Stuecken
        for i in range(0, len(self._daten), 65536):
            yield self._daten[i:i + 65536]


class Whisper:
    """Attrappe fuer _get_whisper_model + _transcribe_audio (echte Signatur:
    filepath, language, initial_prompt, source) – merkt sich, was sie sah."""
    def __init__(self):
        self.modell = object()
        self.antwort = "hallo welt"
        self.fern = False
        self.wirft = None
        self.aufrufe = []

    def get_model(self, source="chat"):
        return self.modell

    def transcribe(self, filepath, language="de", initial_prompt=None, source="chat"):
        p = Path(filepath)
        info = {"pfad": filepath, "language": language, "source": source,
                "existiert": p.is_file()}
        if p.is_file():
            info["inhalt"] = p.read_bytes()
            info["modus"] = stat.S_IMODE(p.stat().st_mode)
        self.aufrufe.append(info)
        if self.wirft:
            raise self.wirft
        return self.antwort


W = Whisper()
# Jede require_*-Abhaengigkeit als Attrappe: eine FALSCHE im Kopf soll die
# Berechtigungspruefung melden (Exit 1), nicht ein NameError die Messung abbrechen.
import re as _re
_abh = {n: object() for n in set(_re.findall(r"\bDepends\((require_[a-z_]+)\)", MAIN.read_text(encoding="utf-8")))}
ns = {**_abh, "JSONResponse": JSONResponse, "Request": Anfrage, "Depends": lambda f: None,
      "require_auth": object(), "asyncio": asyncio, "os": os,
      "_get_whisper_model": lambda source="chat": W.get_model(source),
      # Quelle der Spracherkennung (Einstellung): Vorgabe lokal, im Abschnitt
      # "Fern-Dienst" umgestellt.
      "_stt_quelle_fern": lambda: W.fern,
      "_transcribe_audio": lambda *a, **k: W.transcribe(*a, **k)}
try:
    exec(compile(modul, str(MAIN), "exec"), ns)
except Exception as e:  # noqa: BLE001
    abbruch(f"Endpunkt nicht ausfuehrbar: {e}")
endpunkt = ns[fn.name]


def rufe(anfrage):
    return asyncio.run(endpunkt(anfrage, user="tester"))


AUDIO = b"\x1aE\xdf\xa3" + b"opus-daten" * 50

# ── Regelfall ───────────────────────────────────────────────────────────────
print("\nRegelfall")
W.aufrufe.clear()
r = rufe(Anfrage(AUDIO, lang="de"))
check("Antwort 200 mit erkanntem Text", r.status_code == 200 and r.content == {"text": "hallo welt"},
      f"{r.status_code} {r.content}")
check("Whisper genau einmal gerufen", len(W.aufrufe) == 1, f"{len(W.aufrufe)}")
a = W.aufrufe[0] if W.aufrufe else {}
check("Aufnahme lag waehrend der Erkennung als Datei vor", a.get("existiert") is True)
check("Inhalt byte-gleich mit dem Upload", a.get("inhalt") == AUDIO)
check("Datei nur fuer den Dienst lesbar (0600)", a.get("modus") == 0o600, oct(a.get("modus") or 0))
check("Datei ist danach WEG", bool(a.get("pfad")) and not Path(a["pfad"]).exists(), a.get("pfad", ""))
check("Sprache de durchgereicht", a.get("language") == "de", repr(a.get("language")))
check("Endung .webm fuer audio/webm", str(a.get("pfad", "")).endswith(".webm"))
check("eigene Quelle fuers Journal (nicht whatsapp)", a.get("source") not in (None, "", "whatsapp"),
      repr(a.get("source")))

# ── Aufraeumen auch bei Ausnahme ────────────────────────────────────────────
print("\nErkennung wirft")
W.aufrufe.clear()
W.wirft = RuntimeError("kaputt")
geworfen = False
try:
    rufe(Anfrage(AUDIO))
except RuntimeError:
    geworfen = True
W.wirft = None
check("Ausnahme wurde durchgereicht (Attrappe wirklich gerufen)", geworfen and len(W.aufrufe) == 1)
check("Aufnahme trotzdem geloescht", bool(W.aufrufe) and not Path(W.aufrufe[0]["pfad"]).exists())

# ── Klammertexte nie als erkannter Text ─────────────────────────────────────
print("\nSonderfaelle von _transcribe_audio")
W.antwort = "[Keine Sprache erkannt]"
r = rufe(Anfrage(AUDIO))
check("'Keine Sprache' -> 200 mit leerem Text", r.status_code == 200 and r.content == {"text": ""},
      f"{r.status_code} {r.content}")
W.antwort = "[Transkription fehlgeschlagen: Modell weg]"
r = rufe(Anfrage(AUDIO))
check("'fehlgeschlagen' -> 500", r.status_code == 500, f"{r.status_code}")
check("... und kein Klammertext als 'text'", "text" not in r.content, f"{r.content}")
W.antwort = "hallo welt"

# ── Was Whisper gar nicht erreichen darf ────────────────────────────────────
print("\nVorpruefungen")
W.aufrufe.clear()
r = rufe(Anfrage(b""))
check("leere Aufnahme -> 400", r.status_code == 400, f"{r.status_code}")
gross = ns["_STT_MAX_BYTES"] + 1
r = rufe(Anfrage(b"\0" * gross))
check("zu grosse Aufnahme -> 413", r.status_code == 413, f"{r.status_code}")
W.modell = None
r = rufe(Anfrage(AUDIO))
W.modell = object()
check("ohne Whisper-Modell -> 503", r.status_code == 503, f"{r.status_code}")
check("in keinem dieser Faelle wurde Whisper gerufen", len(W.aufrufe) == 0, f"{len(W.aufrufe)}")
# Fern-Dienst eingestellt: das lokale Modell ist nur der Ersatz, sein Fehlen
# darf die Aufnahme nicht abweisen (2026-10-22).
W.modell, W.fern = None, True
r = rufe(Anfrage(AUDIO))
W.modell, W.fern = object(), False
check("Fern-Dienst eingestellt, ohne lokales Modell -> trotzdem erkannt (200)",
      r.status_code == 200 and len(W.aufrufe) == 1, f"{r.status_code}, {len(W.aufrufe)} Aufrufe")
W.aufrufe.clear()

# ── Sprache und Endung ──────────────────────────────────────────────────────
print("\nSprache und Endung")
W.aufrufe.clear()
rufe(Anfrage(AUDIO, lang="en", typ="audio/ogg;codecs=opus"))
rufe(Anfrage(AUDIO, lang="xx' ; rm", typ="application/x-irgendwas"))
rufe(Anfrage(AUDIO, typ=None))
check("drei Aufrufe gemessen", len(W.aufrufe) == 3, f"{len(W.aufrufe)}")
if len(W.aufrufe) == 3:
    check("lang=en durchgereicht", W.aufrufe[0]["language"] == "en")
    check("Endung .ogg fuer audio/ogg", W.aufrufe[0]["pfad"].endswith(".ogg"))
    check("unbekannte Sprache -> automatische Erkennung (None)", W.aufrufe[1]["language"] is None,
          repr(W.aufrufe[1]["language"]))
    check("unbekannter Typ -> .webm", W.aufrufe[1]["pfad"].endswith(".webm"))
    check("ohne Content-Type -> .webm", W.aufrufe[2]["pfad"].endswith(".webm"))
    check("keine der Dateien blieb liegen",
          not any(Path(x["pfad"]).exists() for x in W.aufrufe))

ok = sum(res)
print(f"\n\033[1mErgebnis: {ok}/{len(res)}\033[0m")
sys.exit(0 if ok == len(res) else 1)
