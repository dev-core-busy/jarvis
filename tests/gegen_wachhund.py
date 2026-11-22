#!/usr/bin/env python3
"""Gegenproben zu tests/test_wachhund.js (Wachhund auf Stillstand statt fester Dauer, 2026-11-22).

Ein Waechter, der nicht beisst, ist ein TESTMANGEL - kein Beweis. Jede Probe
dreht GENAU EINE Zusage zurueck - im Helfer ``tests/lib/wachhund.js`` oder
in einem Waechter, der ihn benutzt - und
erwartet, dass der Waechter sie meldet (Exit 1 MIT Bilanz und mindestens
einem FAIL; ein Abbruch zaehlt nicht).

Gesichert wird auf PLATTE samt Laufmarke; ein Rueckstand eines
abgeschossenen Laufs wird beim naechsten Start zurueckgenommen.

    PYTHONDONTWRITEBYTECODE=1 python3 tests/gegen_wachhund.py
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
ABLAGE = Path.home() / ".gegen-wachhund"   # 0700, NICHT /tmp (1777)
MARKE = ABLAGE / ".laeuft"
# Ablage nach geordnetem Ende abraeumen (tests/lib/gegen_ablage.py) - VOR jedem
# atexit.register dieses Skripts, damit es als Letztes laeuft (atexit: LIFO).
import gegen_ablage  # noqa: E402
gegen_ablage.abraeumen_bei_ende(ABLAGE, marke=MARKE)

HELFER = ROOT / "tests/lib/wachhund.js"
W_EINS = ROOT / "tests/test_sql_ui.js"
WAECHTER = ROOT / "tests/test_wachhund.js"
DATEIEN = [HELFER, W_EINS]
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
    r = subprocess.run([shutil.which("node") or "node", str(WAECHTER)], capture_output=True, text=True,
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


def erstes(alt, neu):
    """Nur das ERSTE Vorkommen ersetzen (der Anker steht mehrfach)."""
    def f(text):
        if alt not in text:
            raise AssertionError("Anker nicht gefunden")
        return text.replace(alt, neu, 1)
    return f


PROBEN = [
    ("Ausgabe startet die Frist nicht neu (Fortschritt unsichtbar)", HELFER,
     ersetzen("                for (const h of aktiv) { h.letzte = t; h.timer.refresh(); }\n", "")),
    ("Last verlaengert die Frist nicht mehr", HELFER,
     ersetzen("    return Math.max(1, last / kerne);\n", "    return 1;\n")),
    ("Hund haengt an der Uhr des Waechters (Date.now)", HELFER,
     ersetzen("const _jetztMs = () => Number(process.hrtime.bigint() / 1000000n);\n",
              "const _jetztMs = () => Date.now();\n")),
    ("Hund schlaegt sofort an statt bei Stillstand", HELFER,
     ersetzen("        if (still < grundMs * faktor) {\n", "        if (false) {\n")),
    ("ein Waechter traegt wieder einen festen Wecker", W_EINS,
     ersetzen("const WACHHUND = require('./lib/wachhund')(function () {",
              "const WACHHUND = setTimeout(function () {")),
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
