#!/usr/bin/env python3
"""Gegenproben zu tests/test_gegen_ablage.py (Abraeumen der Harness-Ablagen, 2026-11-22).

Ein Waechter, der nicht beisst, ist ein TESTMANGEL - kein Beweis. Jede Probe
dreht GENAU EINE Zusage zurueck - im Helfer ``tests/lib/gegen_ablage.py`` oder
im Aufruf eines Harness - und erwartet, dass der Waechter sie meldet
(Exit 1 MIT Bilanz und mindestens einem FAIL; ein Abbruch zaehlt nicht).

Gesichert wird auf PLATTE samt Laufmarke; ein Rueckstand eines
abgeschossenen Laufs wird beim naechsten Start zurueckgenommen.

    PYTHONDONTWRITEBYTECODE=1 python3 tests/gegen_gegen_ablage.py
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import atexit
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-gegen-ablage"   # 0700, NICHT /tmp (1777)
MARKE = ABLAGE / ".laeuft"
# Ablage nach geordnetem Ende abraeumen (tests/lib/gegen_ablage.py) - VOR jedem
# atexit.register dieses Skripts, damit es als Letztes laeuft (atexit: LIFO).
import gegen_ablage  # noqa: E402
gegen_ablage.abraeumen_bei_ende(ABLAGE, marke=MARKE)

HELFER = ROOT / "tests/lib/gegen_ablage.py"
H_EINS = ROOT / "tests/gegen_bild_einfuegen.py"
H_ATEXIT = ROOT / "tests/gegen_am_reihenfolge.py"
WAECHTER = ROOT / "tests/test_gegen_ablage.py"
DATEIEN = [HELFER, H_EINS, H_ATEXIT]
UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def _ziel(p: Path) -> Path:
    return ABLAGE / p.relative_to(ROOT).as_posix().replace("/", "__")


def sichern() -> None:
    ABLAGE.mkdir(mode=0o700, parents=True, exist_ok=True)
    for p in DATEIEN:
        shutil.copy2(p, _ziel(p))
    MARKE.write_text("1")


def zuruecklegen() -> None:
    for p in DATEIEN:
        q = _ziel(p)
        if q.exists() and q.read_bytes() != p.read_bytes():
            shutil.copy2(q, p)


def ende() -> None:
    zuruecklegen()
    if MARKE.exists():
        MARKE.unlink()


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf():
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=ROOT, env=UMG)
    aus = r.stdout + r.stderr
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", aus)
    return r.returncode, (int(m.group(2)) if m else None), aus


def ersetzen(alt, neu):
    def f(text):
        if text.count(alt) != 1:
            raise AssertionError("Anker %dx gefunden" % text.count(alt))
        return text.replace(alt, neu)
    return f


def hinter_atexit(text):
    """Aufruf aus seiner Stelle nehmen und hinter das Modul-atexit stellen."""
    aufruf = "gegen_ablage.abraeumen_bei_ende(ABLAGE)\n"
    anker = "\natexit.register(zurueck)\n"
    if text.count(aufruf) != 1 or text.count(anker) != 1:
        raise AssertionError("Anker %dx/%dx gefunden" % (text.count(aufruf), text.count(anker)))
    return text.replace(aufruf, "").replace(anker, anker + aufruf)


PROBEN = [
    ("Helfer loescht nie (rmtree entfernt)", HELFER,
     ersetzen("    shutil.rmtree(ablage)\n    return None\n", "    return None\n")),
    ("Laufmarke wird nicht beachtet", HELFER,
     ersetzen("    if marke is not None and marke.exists():", "    if False:")),
    ("Inhaltsvergleich ist immer wahr", HELFER,
     ersetzen("        return a.read_bytes() == b.read_bytes()", "        return True")),
    ("Weg ueber den Dateinamen ausgebaut", HELFER,
     ersetzen("        if any(_gleich(f, p) for v in _varianten(name) for p in index.get(v, [])):",
              "        if False:")),
    ("Abraeumen sofort statt am Prozessende (atexit weg)", HELFER,
     ersetzen("    atexit.register(_beim_ende, Path(ablage), Path(marke) if marke else None, Path(wurzel))",
              "    _beim_ende(Path(ablage), Path(marke) if marke else None, Path(wurzel))")),
    ("harte Grenzen ausgebaut (Repo/ausserhalb des Home)", HELFER,
     ersetzen("    a, h, w = ablage.resolve(), Path.home().resolve(), wurzel.resolve()\n",
              "    return None\n    a, h, w = ablage.resolve(), Path.home().resolve(), wurzel.resolve()\n")),
    ("ein Harness ruft den Helfer nicht mehr auf", H_EINS,
     ersetzen("gegen_ablage.abraeumen_bei_ende(ABLAGE, marke=MARKE)\n", "")),
    ("ein Harness uebergibt seine Laufmarke nicht", H_EINS,
     ersetzen("gegen_ablage.abraeumen_bei_ende(ABLAGE, marke=MARKE)\n",
              "gegen_ablage.abraeumen_bei_ende(ABLAGE)\n")),
    ("Aufruf hinter das Modul-atexit verschoben", H_ATEXIT, hinter_atexit),
]


def probe(titel, datei, umbau) -> bool:
    zuruecklegen()
    try:
        neu = umbau(datei.read_text(encoding="utf-8"))
    except AssertionError as exc:
        print(f"  ⚠ {titel}: {exc} – Probe verfehlt ihr Ziel")
        return False
    datei.write_text(neu, encoding="utf-8")
    rc, n, aus = lauf()
    zuruecklegen()
    if n is None or rc == 2:
        print(f"  ⚠ {titel}: der Waechter BRACH AB (rc={rc}, keine deutbare Bilanz) – kein Treffer")
        print("    " + aus.strip().splitlines()[-1][:200] if aus.strip() else "")
        return False
    if rc == 1 and n > 0:
        print(f"  ✓ {titel}: beisst ({n} FAIL)")
        return True
    print(f"  ✗ {titel}: BEISST NICHT (rc={rc}, {n} FAIL) – der Waechter ist hier blind")
    return False


def main() -> int:
    if not {p[1] for p in PROBEN} <= set(DATEIEN):
        print("✗ eine Probe fasst eine Datei an, die nicht gesichert wird – Abbruch")
        return 2
    if MARKE.exists():
        print("⚠ Rueckstand eines abgeschossenen Laufs gefunden – wird zurueckgenommen.")
        ende()
    print("=== Basislauf (muss gruen sein) ===")
    rc, n, aus = lauf()
    if rc != 0 or n != 0:
        print(f"  ✗ {WAECHTER.name} ist NICHT gruen (rc={rc}) – Abbruch, Gegenproben waeren wertlos")
        print(aus[-1500:])
        return 2
    print(f"  ✓ {WAECHTER.name}: gruen")

    vorher = {p: md5(p) for p in DATEIEN}
    sichern()
    atexit.register(ende)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *a: (ende(), sys.exit(130)))

    print("\n=== Gegenproben ===")
    treffer = sum(1 for t, d, u in PROBEN if probe(t, d, u))
    ende()

    print("\n=== Ausgangszustand ===")
    heil = all(md5(p) == vorher[p] for p in DATEIEN)
    print("  ✓ alle Dateien byte-gleich wiederhergestellt" if heil
          else "  ✗ RUECKSTAND im Arbeitsbaum – von Hand pruefen!")
    print(f"\nErgebnis: {treffer} von {len(PROBEN)} Proben beissen")
    return 0 if heil and treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
