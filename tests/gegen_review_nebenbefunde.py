#!/usr/bin/env python3
"""Gegenprobe zu test_review_nebenbefunde.py: beisst der Waechter?

Jede Probe setzt den Stand VOR dem Fix wieder ein (Texttausch, eindeutiger
Anker) und verlangt FAILs. Gesichert wird auf Platte + atexit; eine liegen
gebliebene LAUFMARKE (kill -9) nimmt der naechste Start selbst zurueck.

Exit 0 = alle beissen, 1 = mindestens eine beisst nicht, 2 = nicht deutbar.
"""
from __future__ import annotations

import atexit
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SICHER = Path.home() / ".gegen-review-nebenbefunde"
MARKE = SICHER / "LAEUFT"
WAECHTER = [sys.executable, str(ROOT / "tests" / "test_review_nebenbefunde.py")]

DATEIEN = ["backend/ai_mouse_fragen.py", "backend/license.py",
           "backend/main.py", "backend/lauf_tmp.py", "backend/attachments.py"]


def zurueck() -> None:
    for rel in DATEIEN:
        s = SICHER / rel.replace("/", "__")
        if s.is_file():
            shutil.copy2(s, ROOT / rel)


def abraeumen() -> None:
    if MARKE.is_file():
        zurueck()
        MARKE.unlink()


if MARKE.is_file():
    print("⚠ Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck.")
    zurueck()
SICHER.mkdir(exist_ok=True)
for rel in DATEIEN:
    shutil.copy2(ROOT / rel, SICHER / rel.replace("/", "__"))
MARKE.write_text("laeuft\n", encoding="utf-8")
atexit.register(abraeumen)


def lauf():
    p = subprocess.run(WAECHTER, capture_output=True, text=True, timeout=300)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", p.stdout)
    return p.returncode, (int(m.group(2)) if m else None)


# (Beschreibung, [(Datei, alt, neu), ...])
PROBEN = [
    ("[1] volle Liste setzt wieder `geaendert`", [
        ("backend/ai_mouse_fragen.py",
         "        if len(eigen) >= MAX_JE_BENUTZER:\n            continue\n"
         "        have.append(vid)\n",
         "        if len(eigen) >= MAX_JE_BENUTZER:\n            geaendert = True\n"
         "            continue\n        have.append(vid)\n")]),
    ("[2] gemeinsame Temp-Datei + replace", [
        ("backend/license.py",
         '        tmp = INSTANZ_FILE.with_name("%s.%s.tmp" % (INSTANZ_FILE.name, neu[:8]))\n'
         "        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)\n",
         '        tmp = INSTANZ_FILE.with_suffix(".tmp")\n'
         "        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)\n"),
        ("backend/license.py",
         "        try:\n            os.link(tmp, INSTANZ_FILE)\n        except FileExistsError:",
         "        try:\n            os.replace(tmp, INSTANZ_FILE); tmp = None\n"
         "        except FileExistsError:")]),
    ("[3] Nicht-Strings wieder still verworfen", [
        ("backend/main.py",
         "    if any(not isinstance(g, str) for g in groups):\n",
         "    if False and any(not isinstance(g, str) for g in groups):\n"),
        ("backend/main.py",
         "    if roh_anzahl and not groups:\n",
         "    if False and roh_anzahl and not groups:\n")]),
    ("[4a] Anlegen frischt die mtime nicht auf", [
        ("backend/lauf_tmp.py",
         "                os.chmod(ziel, 0o755)\n                os.utime(ziel)\n",
         "                os.chmod(ziel, 0o755)\n")]),
    ("[4b] Aufraeumer ohne Sperre", [
        ("backend/attachments.py",
         "            with ANH_VERZ_SPERRE:\n                st = d.lstat()\n",
         "            if True:\n                st = d.lstat()\n")]),
]

code, f0 = lauf()
if code != 0 or f0 != 0:
    print("Basis NICHT gruen (exit=%s, FAIL=%s) – ohne gruene Basis ist keine "
          "Gegenprobe deutbar." % (code, f0))
    sys.exit(2)
print("Basis gruen.\n")

beissen = 0
for name, tausche in PROBEN:
    getroffen = True
    for rel, alt, neu in tausche:
        d = ROOT / rel
        s = d.read_text(encoding="utf-8")
        if s.count(alt) != 1:
            print("  ⚠ %-44s ANKER %dx in %s – Probe verfehlt ihr Ziel"
                  % (name, s.count(alt), rel))
            getroffen = False
            break
        d.write_text(s.replace(alt, neu), encoding="utf-8")
    if getroffen:
        c, f = lauf()
        if f is None:
            # Absturz ist KEIN Beissen: der Waechter muss fehlschlagen, nicht werfen.
            print("  ⚠ %-44s KEINE BILANZ (exit %s) – nicht deutbar" % (name, c))
        else:
            ok = c != 0 and f > 0
            beissen += ok
            print("  %s %-44s %s FAIL" % ("beisst" if ok else "ZAHNLOS", name, f))
    zurueck()

print("\n%d von %d Gegenproben beissen." % (beissen, len(PROBEN)))
sys.exit(0 if beissen == len(PROBEN) else 1)
