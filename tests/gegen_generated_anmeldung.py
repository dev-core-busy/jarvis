#!/usr/bin/env python3
"""Gegenprobe zu ``test_generated_anmeldung.py`` + ``test_generated_anmeldung_ui.js``.

Je Probe wird EINE Stelle zurueckgedreht, an der die Anmeldung fuer erzeugte
Bilder haengt; mindestens einer der beiden Waechter muss mit Exit 1 antworten.
Basislauf gruen, Sicherung auf Platte, Laufmarke, md5-Kontrolle danach, ohne
Bytecode (Register). NICHT in einem Sammellauf mitlaufen lassen.

Exit 0 = jede Probe beisst, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MARKE = Path.home() / ".gegen_generated_anmeldung.laeuft"
SICHER = Path.home() / ".gegen_generated_anmeldung.sicherung"
MAIN = "backend/main.py"
ZR = "backend/zugang_regel.py"
CL = "frontend/js/chatlib.js"
AN = "android/app/src/main/java/info/jarvisai/app/ui/chat/ChatImage.kt"
GO = "windows-app-go/chatimage.go"
CS = "ai-mouse/src/AiMouse/Vision/JarvisClient.cs"

PROBEN = [
    ("Endpunkt ohne Anmeldung", MAIN,
     "async def get_generated_image(name: str, user: str = Depends(require_auth_or_query)):",
     "async def get_generated_image(name: str):"),
    ("Zwischenspeicher wieder oeffentlich", MAIN,
     'headers={"Cache-Control": "private, max-age=86400"})',
     'headers={"Cache-Control": "public, max-age=86400"})'),
    ("Zugangsregel fuehrt ihn wieder als oeffentlich", ZR,
     '    ("GET", "/api/addin/version"):',
     '    ("GET", "/api/generated/{name}"): ("oeffentlich", "Probe"),\n    ("GET", "/api/addin/version"):'),
    ("Browser haengt keinen Schluessel an", CL,
     "knowledge\\/netzquelle\\?|generated\\/)", "knowledge\\/netzquelle\\?)"),
    ("Android ohne Token", AN,
     '                    if (authToken.isNotBlank()) header("Authorization", "Bearer $authToken")\n',
     '                    // header("Authorization", "Bearer $authToken")\n'),
    ("Windows-Client ohne Token", GO,
     '\tif tok := imgTokenJetzt(); tok != "" {\n\t\treq.Header.Set("Authorization", "Bearer "+tok)\n\t}\n', ''),
    ("AI-Maus ohne Token", CS,
     '                anfrage.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);\n',
     '                // anfrage.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);\n'),
]
DATEIEN = sorted({p[1] for p in PROBEN})

_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  ok   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (("  -> " + detail) if detail else ""))


def md5(p):
    return hashlib.md5((WURZEL / p).read_bytes()).hexdigest()


def lauf():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    a = subprocess.run([sys.executable, "tests/test_generated_anmeldung.py"], cwd=WURZEL,
                       capture_output=True, text=True, timeout=300, env=env)
    b = subprocess.run(["node", "tests/test_generated_anmeldung_ui.js"], cwd=WURZEL,
                       capture_output=True, text=True, timeout=300, env=env)
    aus = a.stdout + a.stderr + b.stdout + b.stderr
    fails = aus.count("  FAIL ") + aus.count("  ✗ ")
    return a.returncode, b.returncode, fails, aus


def zurueck():
    for d in DATEIEN:
        q = SICHER / d.replace("/", "__")
        if q.exists():
            shutil.copy2(q, WURZEL / d)


if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

ra, rb, f, aus = lauf()
if ra != 0 or rb != 0:
    print("ABBRUCH (Exit 2): Basislauf nicht gruen (%d/%d)" % (ra, rb))
    print(aus[-1500:])
    sys.exit(2)
print("Basislauf gruen.\n")

SICHER.mkdir(exist_ok=True)
vorher = {}
for d in DATEIEN:
    shutil.copy2(WURZEL / d, SICHER / d.replace("/", "__"))
    vorher[d] = md5(d)
MARKE.write_text("laeuft")
try:
    for name, datei, alt, neu in PROBEN:
        p = WURZEL / datei
        t = p.read_text(encoding="utf-8")
        if t.count(alt) != 1:
            pruefe(False, "%s: Anker nicht eindeutig (%d)" % (name, t.count(alt)))
            continue
        p.write_text(t.replace(alt, neu), encoding="utf-8")
        ra, rb, f, aus = lauf()
        pruefe((ra == 1 or rb == 1) and f >= 1 and 2 not in (ra, rb),
               "%s -> beisst (%d FAIL)" % (name, f), "Exit %d/%d" % (ra, rb))
        zurueck()
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for d in DATEIEN:
    pruefe(md5(d) == vorher[d], "%s byte-gleich zurueck" % d)
ra, rb, _, _ = lauf()
pruefe(ra == 0 and rb == 0, "Abschlusslauf wieder gruen")
shutil.rmtree(SICHER, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
