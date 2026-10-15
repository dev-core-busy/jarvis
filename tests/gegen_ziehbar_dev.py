"""Gegenproben zur ZiehbarRegel – dort, wo sie WIRKLICH gemessen wird."""
import re, subprocess, sys
from pathlib import Path
Q = Path("/opt/jarvis/ai-mouse/src/AiMouse/Input/ZiehbarRegel.cs")
O = Q.read_text(encoding="utf-8")

def lauf():
    r = subprocess.run([sys.executable, "/opt/jarvis/tests/live_ziehbar_dev.py"],
                       capture_output=True, text=True, timeout=600)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1

rc, b, f = lauf()
if rc or not b or f:
    print(f"ABBRUCH: Basis nicht gruen (rc={rc} bilanz={b} fails={f})"); sys.exit(2)
print("Basis gruen.\n")

PROBEN = [
    ("Custom ohne Beleg gilt als ziehbar",
     "return controlType == Custom && auswaehlbar;", "return controlType == Custom;"),
    ("Text/Dokument gelten als ziehbar",
     "        Image,        // Bild im Browser oder in einer Galerie",
     "        Image,\n        Text,\n        Document,"),
    ("die LEERE Liste gilt als ziehbar",
     "        ListItem,     // Datei/Ordner im Explorer, Mail in Outlook, Zeile in Listen",
     "        ListItem,\n        List,"),
    ("DragPattern wird ignoriert",
     "        if (dragPattern)\n        {\n            return true;\n        }", "        if (false)\n        {\n            return true;\n        }"),
    ("eine Id ist verdreht (ListItem <-> List)",
     "public const int ListItem = 50007;", "public const int ListItem = 50008;"),
]
gut = 0
try:
    for name, a, n in PROBEN:
        Q.write_text(O, encoding="utf-8")
        s = Q.read_text(encoding="utf-8")
        if a not in s:
            print(f"  ⚠ VERFEHLT  {name}"); continue
        Q.write_text(s.replace(a, n, 1), encoding="utf-8")
        rc, b, f = lauf()
        Q.write_text(O, encoding="utf-8")
        ok = rc != 0 and b and f > 0
        gut += ok
        print(f"  {'OK  ' if ok else 'ZAHNLOS'}  {name}: {f} FAIL" + ("" if b else " (OHNE BILANZ!)"))
finally:
    Q.write_text(O, encoding="utf-8")
print(f"\n{gut} von {len(PROBEN)} beissen einzeln.")
sys.exit(0 if gut == len(PROBEN) else 1)
