#!/usr/bin/env python3
"""Gegenproben zum Waechter tests/test_sysload_sort.js (sortierbare Spalten
der Systemauslastung, 2026-09-28).

Ein Waechter, der nicht beisst, ist ein TESTMANGEL - kein Beweis. Jede Probe
dreht GENAU EINEN Teil des Fixes zurueck und erwartet, dass der zugehoerige
Waechter das meldet.

⚠ DER HARNESS SICHERT AUF PLATTE und nimmt einen Rueckstand beim naechsten
Start selbst zurueck: ein abgeschossener Lauf (Timeout, kill) liesse den
Arbeitsbaum sonst SABOTIERT liegen, und die naechste Messung meldete Fehler,
die es nicht gibt (Register, mehrfach bezahlt).

    python3 tests/gegen_sysload_sort.py
"""
import atexit
import hashlib
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-sysload-sort"   # 0700, NICHT /tmp (1777)
MARKE = ABLAGE / "laeuft"

JS = ROOT / "frontend/js/sysload.js"
W = ROOT / "tests/test_sysload_sort.js"

DATEIEN = [JS]


def _ziel(p: Path) -> Path:
    # Schluessel ist der RELATIVE PFAD, nicht der Basisname: zwei gleichnamige
    # Dateien wuerden einander sonst still ueberschreiben (Register).
    return ABLAGE / p.relative_to(ROOT).as_posix().replace("/", "__")


def sichern() -> None:
    ABLAGE.mkdir(mode=0o700, parents=True, exist_ok=True)
    for p in DATEIEN:
        shutil.copy2(p, _ziel(p))
    MARKE.write_text("1")


def zurueck() -> None:
    for p in DATEIEN:
        q = _ziel(p)
        if q.exists():
            shutil.copy2(q, p)
    if MARKE.exists():
        MARKE.unlink()


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(waechter: Path):
    if waechter.suffix == ".js":
        r = subprocess.run(["node", str(waechter)], capture_output=True, text=True,
                           timeout=180, cwd=ROOT)
    else:
        r = subprocess.run([sys.executable, str(waechter)], capture_output=True,
                           text=True, timeout=180, cwd=ROOT)
    aus = r.stdout + r.stderr
    n = aus.count("✗")
    # Eine fehlende Bilanzzeile heisst ABGEBROCHEN - das ist kein Beissen.
    bilanz = "Ergebnis:" in aus
    return n, bilanz, aus


def probe(titel: str, datei: Path, alt: str, neu: str, waechter: Path) -> bool:
    zurueck()
    s = datei.read_text(encoding="utf-8")
    # Trefferkontrolle: eine Ersetzung ohne assert ist kein Messwert - die
    # Probe "beisst" sonst scheinbar nicht, weil sie gar nicht gegriffen hat.
    if s.count(alt) < 1:
        print(f"  ⚠ {titel}: ANKER NICHT GEFUNDEN – Probe verfehlt ihr Ziel")
        return False
    datei.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    n, bilanz, aus = lauf(waechter)
    zurueck()
    if not bilanz:
        print(f"  ⚠ {titel}: der Waechter BRACH AB (keine Bilanz) – das zaehlt nicht als Treffer")
        return False
    if n > 0:
        print(f"  ✓ {titel}: beisst ({n} FAIL)")
        return True
    print(f"  ✗ {titel}: BEISST NICHT – der Waechter ist an dieser Stelle blind")
    return False


PROBEN = [
    ("Sortierung ausgebaut (Serverfolge fest)", JS,
     "var zeilen = sortiert(d.prozesse || []).map(", "var zeilen = (d.prozesse || []).map(", W),
    ("Sortierung lebt nicht ueber das Neuzeichnen (Vorgabe bei jedem Takt)", JS,
     "    function sortiert(liste) {\n        var s = _sortSpalte, ab = _sortAb;",
     "    function sortiert(liste) {\n        var s = _sortSpalte, ab = _sortAb; _sortSpalte = 'cpu'; _sortAb = true;", W),
    ("Zuhoerer je Kopfzelle statt Delegation (Klick verpufft)", JS,
     "            if (h) umsortieren(h.getAttribute('data-sort'));\n", "", W),
    ("Tastatur sortiert nicht", JS,
     "            e.preventDefault();\n            umsortieren(h.getAttribute('data-sort'));\n", "            e.preventDefault();\n", W),
    ("zweiter Klick kehrt nicht um", JS,
     "if (_sortSpalte === sp) _sortAb = !_sortAb;", "if (_sortSpalte === sp) _sortAb = _sortAb;", W),
    ("Zahlen als Text verglichen", JS,
     "else if (ZAHL_SPALTEN[s]) r = (Number(a[s]) || 0) - (Number(b[s]) || 0);", "", W),
    ("# zeigt die Zeilennummer statt des CPU-Rangs", JS,
     "'<td class=\"jv-pkg-r jv-load-rang\">' + p._rang + '</td>'",
     "'<td class=\"jv-pkg-r jv-load-rang\">' + 0 + '</td>'", W),
    ("Fokus geht beim Neuzeichnen verloren", JS,
     "            if (h) h.focus();\n", "", W),
    ("aria-sort fehlt", JS,
     "+ '\" aria-sort=\"' + (aktiv ? (_sortAb ? 'descending' : 'ascending') : 'none') + '\">'", "+ '\">'", W),
]


def main() -> int:
    if MARKE.exists():
        print("⚠ Rueckstand eines abgeschossenen Laufs gefunden – wird zurueckgenommen.")
        zurueck()
    # Ohne gruene Basis ist KEINE Gegenprobe deutbar.
    print("=== Basislauf (muss gruen sein) ===")
    for w in (W,):
        n, bilanz, aus = lauf(w)
        if n or not bilanz:
            print(f"  ✗ {w.name} ist NICHT gruen – Abbruch, Gegenproben waeren wertlos")
            print(aus[-1500:])
            return 2
        print(f"  ✓ {w.name}: gruen")

    vorher = {p: md5(p) for p in DATEIEN}
    sichern()
    atexit.register(zurueck)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *a: (zurueck(), sys.exit(130)))

    print("\n=== Gegenproben ===")
    treffer = sum(1 for t, d, a, n, w in PROBEN if probe(t, d, a, n, w))
    zurueck()

    print("\n=== Ausgangszustand ===")
    heil = all(md5(p) == vorher[p] for p in DATEIEN)
    print(("  ✓ alle Dateien byte-gleich wiederhergestellt" if heil
           else "  ✗ RUECKSTAND im Arbeitsbaum – von Hand pruefen!"))
    print(f"\nErgebnis: {treffer} von {len(PROBEN)} Proben beissen")
    return 0 if (treffer == len(PROBEN) and heil) else 1


if __name__ == "__main__":
    sys.exit(main())
