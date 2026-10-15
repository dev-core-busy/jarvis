#!/usr/bin/env python3
"""Gegenprobe zu ``test_stt_lokal.js`` und ``test_stt_endpunkt.py``: beissen sie?

Je Probe wird EINE Zusage der lokalen Spracheingabe zurueckgedreht (Browser-
Spracherkenner wieder benutzt, Stille hochgeladen, Aufnahme bleibt liegen, …),
der zustaendige Waechter laufen gelassen und Exit 1 verlangt.

Vorgehen:
  1. Basislauf beider Waechter muss GRUEN sein – ohne gruene Basis ist keine
     Probe deutbar.
  2. Betroffene Datei sichern (im HOME, 0700), Sabotage einbauen, Waechter laufen.
  3. Zuruecknehmen und Byte-Gleichheit per md5 NACHSEHEN.
Eine Laufmarke faengt den Abbruch mitten in einer Probe ab: beim naechsten Start
wird der Rueckstand zuerst zurueckgenommen. Ohne Bytecode (Register: .pyc aus
einer Probe).

NICHT in einem Sammellauf ueber ``tests/*`` mitlaufen lassen – diese Datei
patcht den Arbeitsbaum.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
JS_W = ["node", str(WURZEL / "tests" / "test_stt_lokal.js")]
PY_W = [sys.executable, str(WURZEL / "tests" / "test_stt_endpunkt.py")]
SICHERUNG = Path.home() / ".gegen_stt_lokal"
MARKE = SICHERUNG / "laeuft"

STT = "frontend/js/stt.js"
CHAT = "frontend/js/chat.js"
CHAT_HTML = "frontend/chat.html"
MAIN = "backend/main.py"

# Die Einbindung samt Cache-Buster aus der Seite lesen – eine feste Versionsnummer
# waere beim naechsten Hochzaehlen ein Anker ohne Treffer.
_m = re.search(r'<script src="/static/js/stt\.js\?v=\d+"></script>\n',
               (WURZEL / CHAT_HTML).read_text(encoding="utf-8"))
_STT_TAG = _m.group(0) if _m else "<stt.js-Einbindung nicht gefunden>"

# (Name, Datei, alt, neu, Waechter)
PROBEN = [
    ("chat.js benutzt wieder den Browser-Spracherkenner", CHAT,
     "    let micLauf = null;\n",
     "    let micLauf = null;\n    const _SR = window.webkitSpeechRecognition;\n", JS_W),
    ("stt.js laedt auch reine Stille hoch", STT,
     "if (!sprache || !teile.length) { beenden('keine_sprache'); return; }",
     "if (!teile.length) { beenden('keine_sprache'); return; }", JS_W),
    ("stt.js gibt das Mikrofon nicht frei", STT,
     "stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) {} });",
     "stream.getTracks();", JS_W),
    ("stt.js schickt an einen fremden Dienst", STT,
     "fetch('/api/stt' + (lang ? '?lang=' + lang : ''), {",
     "fetch('https://speech.example/api/stt' + (lang ? '?lang=' + lang : ''), {", JS_W),
    ("stt.js steht in chat.html HINTER chat.js", CHAT_HTML,
     _STT_TAG + '<script src="/static/js/chat.js?v=',
     '<script src="/static/js/chat.js?v=', JS_W),
    ("Endpunkt ohne Anmeldung", MAIN,
     "async def stt_transcribe(request: Request, user: str = Depends(require_auth)):",
     "async def stt_transcribe(request: Request, user: str = None):", PY_W),
    ("Aufnahme bleibt nach der Erkennung liegen", MAIN,
     "                os.unlink(pfad)\n            except OSError:\n                pass\n    # _transcribe_audio",
     "                pass\n            except OSError:\n                pass\n    # _transcribe_audio", PY_W),
    ("Aufnahme fuer alle lesbar", MAIN,
     "            pfad = f.name\n        text = await asyncio.to_thread(",
     "            pfad = f.name\n        os.chmod(pfad, 0o644)\n        text = await asyncio.to_thread(", PY_W),
    ("'[Keine Sprache erkannt]' geht als Text an den Browser", MAIN,
     '    if text == "[Keine Sprache erkannt]":\n        return JSONResponse({"text": ""})\n',
     "", PY_W),
    ("Sprache ungeprueft an Whisper", MAIN,
     '    sprache = sprache if sprache in ("de", "en") else None\n',
     "    sprache = sprache or None\n", PY_W),
]
DATEIEN = sorted({p[1] for p in PROBEN})

_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(cmd):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    e = subprocess.run(cmd, cwd=WURZEL, capture_output=True, text=True, timeout=300, env=env)
    return e.returncode, e.stdout + e.stderr


def zurueck():
    for rel in DATEIEN:
        s = SICHERUNG / rel.replace("/", "__")
        if s.is_file():
            shutil.copyfile(s, WURZEL / rel)


# ── Rueckstand eines abgebrochenen Laufs ────────────────────────────────────
if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

# ── Basislauf ───────────────────────────────────────────────────────────────
for cmd in (JS_W, PY_W):
    rc, aus = lauf(cmd)
    if rc != 0:
        print("ABBRUCH (Exit 2): Basislauf %s nicht gruen (Exit %d)." % (Path(cmd[-1]).name, rc))
        print(aus[-1500:])
        sys.exit(2)
print("Basislauf beider Waechter gruen.\n")

SICHERUNG.mkdir(mode=0o700, exist_ok=True)
for rel in DATEIEN:
    shutil.copyfile(WURZEL / rel, SICHERUNG / rel.replace("/", "__"))
soll = {rel: md5(WURZEL / rel) for rel in DATEIEN}
MARKE.write_text("laeuft", encoding="utf-8")
try:
    for name, rel, alt, neu, waechter in PROBEN:
        pfad = WURZEL / rel
        quelle = pfad.read_text(encoding="utf-8")
        n = quelle.count(alt)
        if n != 1:
            pruefe(False, "%s -> Anker eindeutig" % name, "%d Treffer" % n)
            continue
        pfad.write_text(quelle.replace(alt, neu), encoding="utf-8")
        rc, _aus = lauf(waechter)
        pruefe(rc == 1, "%s -> %s meldet (Exit 1)" % (name, Path(waechter[-1]).name), "Exit %d" % rc)
        zurueck()
        pruefe(md5(pfad) == soll[rel], "%s -> Datei byte-gleich zurueck" % name)
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for rel in DATEIEN:
    pruefe(md5(WURZEL / rel) == soll[rel], "%s unveraendert" % rel)
for cmd in (JS_W, PY_W):
    rc, _ = lauf(cmd)
    pruefe(rc == 0, "Abschlusslauf %s gruen" % Path(cmd[-1]).name, "Exit %d" % rc)
shutil.rmtree(SICHERUNG, ignore_errors=True)

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
