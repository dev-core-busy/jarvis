#!/usr/bin/env python3
"""Gegenproben zu `TastenAus` – dort, wo es WIRKLICH ausgefuehrt wird.

Die Aufloesung der zwei entgegengesetzten Tastenfelder laesst sich im
Quelltext nur als Schreibweise pruefen; ihre EIGENSCHAFT misst
`live_tastenaus_dev.py`. Also gehoert die Gegenprobe hierher.

Aufruf auf DEV: python3 tests/gegen_tastenaus_dev.py
"""
import re
import subprocess
import sys
from pathlib import Path

Q = Path("/opt/jarvis/ai-mouse/src/AiMouse/TrayApplicationContext.cs")
O = Q.read_text(encoding="utf-8")


def lauf():
    r = subprocess.run([sys.executable, "/opt/jarvis/tests/live_tastenaus_dev.py"],
                       capture_output=True, text=True, timeout=600)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


rc, b, f = lauf()
if rc or not b or f:
    print(f"ABBRUCH: Basis nicht gruen (rc={rc} bilanz={b} fails={f})")
    sys.exit(2)
print("Basis gruen.\n")

PROBEN = [
    # ⚠ DIE TRAGENDE ZUSAGE: mit Gestentaste ist Durchreichen abgeschaltet.
    ("Aufloesung laesst Durchreichen stehen",
     "            : (geste, GestenTaste.Keine);",
     "            : (geste, GestenTasteAus(s.RightDragKey));"),
    ("die Gestentaste gewinnt NICHT mehr",
     "        return geste == GestenTaste.Keine",
     "        return true"),
    ("Gestentaste faellt auf Strg statt Keine",
     "GestenTasteAus(s.GestureKey, GestenTaste.Keine)", "GestenTasteAus(s.GestureKey)"),
    ("die je Feld verschiedene Vorgabe faellt weg",
     "GestenTaste vorgabe = GestenTaste.Strg", "GestenTaste vorgabe = GestenTaste.Keine"),
    ("Gross/Kleinschreibung wird nicht mehr normiert",
     ".Trim().ToLowerInvariant() switch", ".Trim() switch"),
]

gut = 0
try:
    for name, a, n in PROBEN:
        Q.write_text(O, encoding="utf-8")
        s = Q.read_text(encoding="utf-8")
        if a not in s:
            print(f"  ⚠ VERFEHLT  {name}")
            continue
        Q.write_text(s.replace(a, n, 1), encoding="utf-8")
        rc, b, f = lauf()
        Q.write_text(O, encoding="utf-8")
        ok = rc != 0 and b and f > 0
        gut += ok
        print(f"  {'OK  ' if ok else 'ZAHNLOS'}  {name}: {f} FAIL"
              + ("" if b else " (OHNE BILANZ!)"))
finally:
    Q.write_text(O, encoding="utf-8")

print(f"\n{gut} von {len(PROBEN)} beissen einzeln.")
sys.exit(0 if gut == len(PROBEN) else 1)
