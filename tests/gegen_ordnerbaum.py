#!/usr/bin/env python3
"""Gegenproben zum Ordnerbaum-Fix: jede Sabotage muss EINZELN beissen.

Eine Gegenprobe, die nicht beisst, ist ein Testmangel – kein Beweis. Der
Harness sichert jede angefasste Datei auf Platte, nimmt einen Rueckstand beim
naechsten Start selbst zurueck und verlangt vorab einen GRUENEN Basislauf:
ohne gruene Basis ist keine Gegenprobe deutbar.
"""
import atexit
import hashlib
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-ordnerbaum"
MARKE = ABLAGE / ".laeuft"

MAIN = WURZEL / "backend" / "main.py"
WJS = WURZEL / "frontend" / "js" / "wissen.js"
DATEIEN = [MAIN, WJS]

WAECHTER = ["tests/test_ordnerbaum.py"]


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for d in DATEIEN:
        ziel = ABLAGE / d.relative_to(WURZEL).as_posix().replace("/", "__")
        shutil.copy2(d, ziel)          # bei JEDEM Lauf erneuern
    MARKE.write_text("1")


def zurueck(still=False):
    for d in DATEIEN:
        q = ABLAGE / d.relative_to(WURZEL).as_posix().replace("/", "__")
        if q.exists():
            shutil.copy2(q, d)
            if not still and md5(q) != md5(d):
                print(f"  ⚠ WIEDERHERSTELLUNG WEICHT AB: {d}")
    MARKE.unlink(missing_ok=True)


# Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen
if MARKE.exists():
    print("⚠ Rueckstand eines frueheren Laufs gefunden – stelle wieder her")
    zurueck(still=True)

atexit.register(lambda: zurueck(still=True))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))


def lauf(datei):
    r = subprocess.run([sys.executable, datei], cwd=WURZEL,
                       capture_output=True, text=True, timeout=120)
    aus = r.stdout + r.stderr
    bilanz = [z for z in aus.splitlines() if z.startswith("ERGEBNIS:")]
    if not bilanz:
        return None, aus          # ohne Bilanz = abgebrochen
    # ⚠ "ERGEBNIS: 16 OK, 2 FAIL" -> Index 1 ist die OK-, Index 3 die FAIL-Zahl.
    #   Der erste Anlauf las Index 1 und meldete damit JEDE Probe als beissend,
    #   solange ueberhaupt etwas OK war – eine stumme Gegenprobe waere
    #   unbemerkt als Beleg durchgegangen.
    teile = bilanz[0].split()
    return int(teile[3]), aus


# ── Basislauf ───────────────────────────────────────────────────────────────
print("=" * 72)
print("BASISLAUF (muss gruen sein – sonst ist keine Gegenprobe deutbar)")
print("=" * 72)
basis_ok = True
for w in WAECHTER:
    _, aus = lauf(w)
    letzte = [z for z in aus.splitlines() if z.startswith("ERGEBNIS:")]
    print(f"  {w}: {letzte[0] if letzte else '(KEINE BILANZ)'}")
    if not letzte or "0 FAIL" not in letzte[0]:
        basis_ok = False
if not basis_ok:
    print("BASIS NICHT GRUEN – Abbruch")
    sys.exit(2)

sichern()

# ── Proben: (Name, Datei, alt, neu, Waechter) ───────────────────────────────
PROBEN = [
    ("ALTSTAND: Ausgabe wird nicht sortiert (os.walk-Reihenfolge)",
     MAIN,
     '    out.sort(key=lambda e: _kb_baum_key(e["path"]))\n    return out',
     '    return out',
     "tests/test_ordnerbaum.py"),

    ("_kb_baum_key case-sensitiv (kein .lower())",
     MAIN,
     "return tuple(teil.lower() for teil in Path(rel).parts)",
     "return tuple(teil for teil in Path(rel).parts)",
     "tests/test_ordnerbaum.py"),

    ("_kb_baum_key sortiert die ZEICHENKETTE statt der Pfadteile",
     MAIN,
     "return tuple(teil.lower() for teil in Path(rel).parts)",
     "return rel.lower()",
     "tests/test_ordnerbaum.py"),

    ("folder_tree sortiert case-sensitiv (Drift zur anderen Auswahl)",
     MAIN,
     "            entries = sorted(base.iterdir(), key=lambda e: e.name.lower())\n"
     "        except OSError:\n            return\n        for entry in entries:\n"
     "            if not entry.is_dir() or entry.name.startswith(\".\"):",
     "            entries = sorted(base.iterdir(), key=lambda e: e.name)\n"
     "        except OSError:\n            return\n        for entry in entries:\n"
     "            if not entry.is_dir() or entry.name.startswith(\".\"):",
     "tests/test_ordnerbaum.py"),

    ("Client sortiert selbst nach (zweite Fassung derselben Regel)",
     WJS,
     "        var cur = sel.value;\n        sel.innerHTML = offer.map(function (f) {",
     "        var cur = sel.value;\n        offer = offer.slice().sort(function (a, b) "
     "{ return a.name < b.name ? -1 : 1; });\n        sel.innerHTML = offer.map(function (f) {",
     "tests/test_ordnerbaum.py"),

    ("Client rueckt nicht mehr nach depth ein",
     WJS,
     "            var d = f.depth || 0;",
     "            var d = 0;",
     "tests/test_ordnerbaum.py"),
]

print()
print("=" * 72)
print("GEGENPROBEN")
print("=" * 72)
beissen = 0
for name, datei, alt, neu, w in PROBEN:
    quelle = datei.read_text(encoding="utf-8")
    treffer = quelle.count(alt)
    if treffer != 1:
        print(f"  ⚠ SABOTAGE TRIFFT NICHT ({treffer}x): {name}")
        continue
    datei.write_text(quelle.replace(alt, neu), encoding="utf-8")
    fails, aus = lauf(w)
    zurueck()
    sichern()
    if fails is None:
        print(f"  ⚠ {name}: Lauf OHNE BILANZ (abgebrochen) – Testmangel")
    elif fails > 0:
        beissen += 1
        print(f"  ✓ beisst ({fails} FAIL): {name}")
    else:
        print(f"  ✗ STUMM: {name}")

zurueck()
print()
print(f"ERGEBNIS: {beissen} von {len(PROBEN)} Gegenproben beissen")
sys.exit(0 if beissen == len(PROBEN) else 1)
