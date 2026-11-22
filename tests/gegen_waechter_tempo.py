#!/usr/bin/env python3
"""Gegenproben zu tests/test_waechter_tempo.py (linearer Quelltext-Zugriff, Startreihenfolge).

Ein Waechter, der nicht beisst, ist ein TESTMANGEL - kein Beweis. Jede Probe
dreht GENAU EINE Zusage zurueck - im Helfer ``tests/lib/quell_ausschnitt.py``,
in ``tests/ci_lauf.py`` oder in einem Waechter, der den Helfer benutzt - und
erwartet, dass der Waechter sie meldet (Exit 1 MIT Bilanz und mindestens
einem FAIL; ein Abbruch zaehlt nicht).

Gesichert wird auf PLATTE samt Laufmarke; ein Rueckstand eines
abgeschossenen Laufs wird beim naechsten Start zurueckgenommen.

    PYTHONDONTWRITEBYTECODE=1 python3 tests/gegen_waechter_tempo.py
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
ABLAGE = Path.home() / ".gegen-waechter-tempo"   # 0700, NICHT /tmp (1777)
MARKE = ABLAGE / ".laeuft"
# Ablage nach geordnetem Ende abraeumen (tests/lib/gegen_ablage.py) - VOR jedem
# atexit.register dieses Skripts, damit es als Letztes laeuft (atexit: LIFO).
import gegen_ablage  # noqa: E402
gegen_ablage.abraeumen_bei_ende(ABLAGE, marke=MARKE)

HELFER = ROOT / "tests/lib/quell_ausschnitt.py"
CI = ROOT / "tests/ci_lauf.py"
W_SEGMENT = ROOT / "tests/test_anhang_bild_mime.py"
W_VERSATZ = ROOT / "tests/test_dienst_neustart.py"
W_IMPORT = ROOT / "tests/test_unlesbar_cache.py"
WAECHTER = ROOT / "tests/test_waechter_tempo.py"
DATEIEN = [HELFER, CI, W_SEGMENT, W_VERSATZ, W_IMPORT]
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


def erstes(alt, neu):
    """Nur das ERSTE Vorkommen ersetzen (der Anker steht mehrfach)."""
    def f(text):
        if alt not in text:
            raise AssertionError("Anker nicht gefunden")
        return text.replace(alt, neu, 1)
    return f


PROBEN = [
    # ── Helfer: segment ──
    ("segment schneidet Zeichen statt UTF-8-Bytes", HELFER,
     ersetzen("        return alle[anfang].encode()[spalte:end_spalte].decode()\n",
              "        return alle[anfang][spalte:end_spalte]\n")),
    ("Zeilen wie str.splitlines (trennt auch \\f, \\x1c, \\u2028)", HELFER,
     ersetzen('    zerleger = getattr(ast, "_splitlines_no_ff", None)\n',
              "    zerleger = lambda q: q.splitlines(keepends=True)  # noqa: E731\n")),
    ("Zeilen werden bei jedem Aufruf neu zerlegt (Ablage weg)", HELFER,
     ersetzen("    gefunden = _ablage.get(quelle)\n", "    gefunden = None\n")),
    ("padded wird uebergangen", HELFER,
     ersetzen("    if padded:\n", "    if False:\n")),
    # ── Helfer: ZeilenVersatz ──
    ("ZeilenVersatz vergisst den Zusatz je Zeile", HELFER,
     ersetzen("            tabelle.append(tabelle[-1] + len(z) + zusatz)\n",
              "            tabelle.append(tabelle[-1] + len(z))\n")),
    ("ZeilenVersatz ohne Slice-Bedeutung (negative k)", HELFER,
     ersetzen("        return self._tabelle[len(range(self._anzahl)[:k])]\n",
              "        return self._tabelle[max(0, min(k, self._anzahl))]\n")),
    # ── Regel in den Waechtern ──
    ("ein Waechter ruft wieder ast.get_source_segment", W_SEGMENT,
     erstes("quell_ausschnitt.segment(", "ast.get_source_segment(")),
    ("ein Waechter summiert wieder je Kommentar alle Zeilen davor", W_VERSATZ,
     ersetzen("            start = vor(tok.start[0] - 1) + tok.start[1]\n",
              "            start = sum(len(z) for z in quelle.splitlines(keepends=True)"
              "[:tok.start[0] - 1]) + tok.start[1]\n")),
    ("ein Waechter benutzt den Helfer ohne Import", W_IMPORT,
     ersetzen("import quell_ausschnitt  # noqa: E402  (linear statt ast.get_source_segment)\n", "")),
    # ── Sammellauf ──
    ("Sammellauf startet wieder alphabetisch", CI,
     ersetzen('    return sorted(dateien, key=lambda d: (-dauern.get(d.name, float("inf")), d.name))\n',
              "    return sorted(dateien, key=lambda d: d.name)\n")),
    ("unbekannte Waechter starten zuletzt statt zuerst", CI,
     ersetzen('dauern.get(d.name, float("inf"))', "dauern.get(d.name, 0.0)")),
    ("Speichern ueberschreibt statt zu mischen", CI,
     ersetzen("    alle = dauern_laden()\n", "    alle = {}\n")),
    ("gemessene Zeiten werden nicht gespeichert", CI,
     ersetzen("        dauern_speichern(gemessen)\n", "")),
    ("Ausgabe in Abschlussreihenfolge statt nach Namen", CI,
     ersetzen("        ergebnisse.sort(key=lambda e: e[0])\n", "")),
    ("kaputte Zeitdatei laesst den Lauf abstuerzen", CI,
     ersetzen("    except (OSError, ValueError):\n        return {}\n",
              "    except OSError:\n        return {}\n")),
    ("Zeitdatei in falscher Form laesst den Lauf abstuerzen", CI,
     ersetzen("    if not isinstance(roh, dict):\n        return {}\n", "")),
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
