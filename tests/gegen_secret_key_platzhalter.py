"""Gegenproben zu test_secret_key_platzhalter: beisst der Waechter, wenn der Fix fehlt?"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
TEST = W / "tests" / "test_secret_key_platzhalter.py"
ALT = "change-me-to-a-secure-random-string-min-32-chars"

PROBEN = [
    ("Platzhalter gilt wieder als gueltiger Wert (alter Stand)", "backend/secret_key.py",
     "    return w in BEKANNTE_PLATZHALTER or w.lower().startswith(\"change-me\")\n",
     "    return False\n"),
    ("nur die feste Liste, keine change-me-Abwandlungen", "backend/secret_key.py",
     " or w.lower().startswith(\"change-me\")\n", "\n"),
    ("Datei ohne 0600", "backend/secret_key.py",
     "    _t._schreibe_atomar(datei, inhalt.encode(\"utf-8\"), 0o600)\n",
     "    _t._schreibe_atomar(datei, inhalt.encode(\"utf-8\"), 0o644)\n"),
    ("Platzhalter in data/.secret_key wird uebernommen", "backend/secret_key.py",
     "    if ist_platzhalter(wert):\n", "    if not wert:\n"),
    ("config liest SECRET_KEY wieder direkt aus der Umgebung", "backend/config.py",
     "    SECRET_KEY: str = _secret_aufloesen(\n        os.getenv(\"SECRET_KEY\", \"\"),\n"
     "        PROJECT_ROOT / \"data\" / \".secret_key\")\n",
     "    SECRET_KEY: str = os.getenv(\"SECRET_KEY\", \"\")\n"),
    ("install.sh leert den Beispielwert nicht mehr", "docs/install.sh",
     "    sed -i -E 's/^SECRET_KEY=.*/SECRET_KEY=/' \"$INSTALL_DIR/.env\"\n", "    :\n"),
    ("install.sh leert AUCH echte Werte", "docs/install.sh",
     "^SECRET_KEY=[[:space:]]*change-me", "^SECRET_KEY="),
    ("README nennt einen neuen Beispielwert", "README.md",
     "SECRET_KEY=                     # leave empty",
     "SECRET_KEY=bitte-aendern-1234567890abcdef1234567890  # leave empty"),
]
DATEIEN = sorted({p[1] for p in PROBEN})
ORIG = {f: (W / f).read_bytes() for f in DATEIEN}


def zurueck():
    for f, b in ORIG.items():
        (W / f).write_bytes(b)


def lauf():
    r = subprocess.run([sys.executable, str(TEST)], capture_output=True, text=True, timeout=120)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


rc, b, f = lauf()
if rc or not b or f:
    print(f"ABBRUCH: Basis nicht gruen (rc={rc} bilanz={b} fails={f})")
    sys.exit(2)
print("Basis gruen.\n")

gut = 0
try:
    for name, rel, a, n in PROBEN:
        zurueck()
        s = (W / rel).read_text(encoding="utf-8")
        if s.count(a) != 1:
            print(f"  ⚠ VERFEHLT  {name} (Anker {s.count(a)}x)")
            continue
        (W / rel).write_text(s.replace(a, n, 1), encoding="utf-8")
        rc, b, f = lauf()
        zurueck()
        ok = rc != 0 and b and f > 0
        gut += ok
        print(f"  {'OK     ' if ok else 'ZAHNLOS'}  {name}: {f} FAIL" + ("" if b else " (OHNE BILANZ!)"))
finally:
    zurueck()
    for fn, bts in ORIG.items():
        if hashlib.md5((W / fn).read_bytes()).digest() != hashlib.md5(bts).digest():
            print(f"  ⚠ RUECKSTAND in {fn}")
print(f"\n{gut} von {len(PROBEN)} beissen einzeln.")
sys.exit(0 if gut == len(PROBEN) else 1)
