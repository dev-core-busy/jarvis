"""Gegenprobe zu test_imagemagick_auto.py: beisst der Waechter?

Jede Probe verdreht EINE Zusage des Abschnitts 6i in einer KOPIE von
start_jarvis_root.sh (das echte Skript bleibt unberuehrt) und erwartet FAILs.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
QUELLE = WURZEL / "start_jarvis_root.sh"
TEST = WURZEL / "tests" / "test_imagemagick_auto.py"
O = QUELLE.read_text(encoding="utf-8")


def lauf(text=None):
    env = dict(os.environ)
    with tempfile.TemporaryDirectory() as td:
        if text is not None:
            p = Path(td) / "start_jarvis_root.sh"
            p.write_text(text, encoding="utf-8")
            env["JARVIS_TEST_QUELLE"] = str(p)
        r = subprocess.run([sys.executable, str(TEST)], env=env,
                           capture_output=True, text=True, timeout=120)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


rc, b, f = lauf()
if rc or not b or f:
    print(f"ABBRUCH: Basis nicht gruen (rc={rc} bilanz={b} fails={f})")
    sys.exit(2)
print("Basis gruen.\n")

PROBEN = [
    ("Pruefung auf convert entfaellt",
     '        && ! command -v convert >/dev/null 2>&1 \\\n', ""),
    ("Pruefung auf magick entfaellt",
     '        && ! command -v magick >/dev/null 2>&1; then', "; then"),
    ("Schalter wirkungslos",
     '"${JARVIS_IMAGEMAGICK_AUTO:-1}" != "0"', '"1" != "0"'),
    ("falsches Paket",
     "apt-get install -y imagemagick 2>&1", "apt-get install -y imagemagick-7-common 2>&1"),
    ("interaktives apt",
     'AUSGABE="$(DEBIAN_FRONTEND=noninteractive apt-get install -y imagemagick ',
     'AUSGABE="$(apt-get install -y imagemagick '),
    ("Erfolg nur am Exit-Code von apt",
     '[ "$RC" -eq 0 ] && { command -v convert >/dev/null 2>&1 || command -v magick >/dev/null 2>&1; }',
     '[ "$RC" -eq 0 ]'),
    ("Fehlschlag still",
     'echo "[ImageMagick] WARNUNG: nicht installierbar', 'echo "[ImageMagick] nicht installierbar'),
    ("im Vordergrund (blockiert den Broker-Start)",
     "    ) &\nfi\n\n# 6h.", "    )\nfi\n\n# 6h."),
]
gut = 0
for name, a, n in PROBEN:
    if O.count(a) != 1:
        print(f"  ⚠ VERFEHLT  {name} (Anker {O.count(a)}x statt genau 1x)")
        continue
    rc, b, f = lauf(O.replace(a, n, 1))
    biss = rc == 1 and b and f > 0
    gut += biss
    print(f"  {'OK     ' if biss else 'ZAHNLOS'}  {name}: rc={rc} {f} FAIL"
          + ("" if b else " (OHNE BILANZ!)"))
print(f"\n{gut} von {len(PROBEN)} beissen einzeln.")
sys.exit(0 if gut == len(PROBEN) else 1)
