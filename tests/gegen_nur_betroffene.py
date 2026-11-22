#!/usr/bin/env python3
"""Gegenproben zu tests/test_nur_betroffene.py (ci_lauf.py --nur-betroffene, 2026-11-22).

Ein Waechter, der nicht beisst, ist ein TESTMANGEL - kein Beweis. Jede Probe
dreht GENAU EINE Zusage zurueck - im Parser ``tests/lib/lesespur.py``, in
der Regel ``tests/lib/betroffen.py`` oder in ``tests/ci_lauf.py`` - und
erwartet, dass der Waechter sie meldet (Exit 1 MIT Bilanz und mindestens
einem FAIL; ein Abbruch zaehlt nicht).

Gesichert wird auf PLATTE samt Laufmarke; ein Rueckstand eines
abgeschossenen Laufs wird beim naechsten Start zurueckgenommen.

    PYTHONDONTWRITEBYTECODE=1 python3 tests/gegen_nur_betroffene.py
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
ABLAGE = Path.home() / ".gegen-nur-betroffene"   # 0700, NICHT /tmp (1777)
MARKE = ABLAGE / ".laeuft"
# Ablage nach geordnetem Ende abraeumen (tests/lib/gegen_ablage.py) - VOR jedem
# atexit.register dieses Skripts, damit es als Letztes laeuft (atexit: LIFO).
import gegen_ablage  # noqa: E402
gegen_ablage.abraeumen_bei_ende(ABLAGE, marke=MARKE)

SPUR = ROOT / "tests/lib/lesespur.py"
REGEL = ROOT / "tests/lib/betroffen.py"
CI = ROOT / "tests/ci_lauf.py"
WAECHTER = ROOT / "tests/test_nur_betroffene.py"
DATEIEN = [SPUR, REGEL, CI]
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
                       timeout=1200, cwd=ROOT, env=UMG)
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
    # ── Parser (lesespur.py) ──
    ("chdir wird nicht verfolgt", SPUR,
     ersetzen("                cwd[pid] = aufloesen(pid, texte[0])\n", "                pass\n")),
    ("Kindprozesse erben das Arbeitsverzeichnis nicht", SPUR,
     ersetzen("                cwd[rc] = cwd.get(pid, wurzel)\n", "                pass\n")),
    ("unterbrochene Zeilen verlieren ihren Pfad", SPUR,
     ersetzen('                offen[pid] = (aufruf, rest[: -len("<unfinished ...>")])\n',
              "                pass\n")),
    ("fehlende Pfade zaehlen nicht mehr", SPUR,
     ersetzen("        gelesen.add(pfad)\n    return gelesen, verzeichnisse\n",
              "        if rc is None or rc >= 0:\n            gelesen.add(pfad)\n    return gelesen, verzeichnisse\n")),
    ("aufgelistete Verzeichnisse werden nicht erkannt", SPUR,
     ersetzen('            if "O_DIRECTORY" in flags:\n', "            if False:\n")),
    ("reines Schreiben gilt als Abhaengigkeit", SPUR,
     ersetzen('            if ("O_WRONLY" in flags) and "O_RDWR" not in flags:\n', "            if False:\n")),
    ("Deskriptor-Pfade (*at mit dirfd) werden uebergangen", SPUR,
     ersetzen("        basis = fd.group(1) if fd else None\n", "        basis = None\n")),
    ("Bytecode zaehlt als Abhaengigkeit", SPUR,
     ersetzen('            if "__pycache__/" in rel or rel.endswith("/__pycache__"):\n', "            if False:\n")),
    ("der eigene Cache gilt als Abhaengigkeit (nie mehr gleich)", SPUR,
     ersetzen('    for d in (".cache", ".harness-schreibschutz", ".npm", ".node_repl_history"):\n',
              '    for d in (".harness-schreibschutz", ".npm", ".node_repl_history"):\n')),
    ("ein Verweis auf Fluechtiges gilt als Abhaengigkeit", SPUR,
     ersetzen("        elif not fluechtig(p, home) and not fluechtig(os.path.realpath(p), home):\n",
              "        elif not fluechtig(p, home):\n")),
    ("fluechtige Ablagen zaehlen in der Verzeichnisliste mit", SPUR,
     ersetzen("        namen = sorted(n for n in os.listdir(p) if not fluechtiger_name(n))\n",
              "        namen = sorted(os.listdir(p))\n")),
    # ── Regel (betroffen.py) ──
    ("ein roter Waechter darf entfallen", REGEL,
     ersetzen('        if e["rc"] != 0:\n', "        if False:\n")),
    ("keine Altersgrenze", REGEL,
     ersetzen("        if (jetzt if jetzt is not None else time.time()) - e[\"zeit\"] > max_alter_s():\n",
              "        if False:\n")),
    ("Abhaengigkeiten werden nicht verglichen", REGEL,
     ersetzen('        if zustaende.summe(e["dateien"], e["verzeichnisse"]) != e["summe"]:\n', "        if False:\n")),
    ("eine andere Umgebung gilt weiter", REGEL,
     ersetzen('            if roh.get("kennung") != kennung:\n', "            if False:\n")),
    # summe() steht in lesespur.py: Verzeichnislisten fliessen nicht ein
    ("Verzeichnislisten fliessen nicht in den Vergleich", SPUR,
     ersetzen('            h.update(b"V\\0" + v.encode() + b"\\0" + self.verzeichnis(v).encode() + b"\\n")\n',
              "            pass\n")),
    # ── Sammellauf (ci_lauf.py) ──
    ("Waechter laufen ohne Lesespur", CI,
     ersetzen('    if _SPUR["verzeichnis"] is not None and datei.name in _SPUR["namen"]:\n', "    if False:\n")),
    ("aufgezeichnete Laeufe ohne erhoehten Zeitdeckel", CI,
     ersetzen("        zeitdeckel *= STRACE_ZEITFAKTOR\n", "        pass\n")),
    ("ein Teillauf loescht die Eintraege der anderen", CI,
     ersetzen("    karte.behalten_nur({d.name for d in kandidaten([])})\n",
              '    karte.behalten_nur(set(_SPUR["namen"]))\n')),
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
