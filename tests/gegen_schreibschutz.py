#!/usr/bin/env python3
"""Gegenproben zu ``test_schreibschutz.py``: beisst jede Zusage EINZELN?

⚠ DIESER HARNESS SCHREIBT KEINE DATEI IM ARBEITSBAUM. Er kopiert
``tests/lib/schreibschutz.py`` bzw. die ``gegen_*.py`` in ein
Wegwerfverzeichnis, sabotiert die KOPIE und laesst den Waechter ueber
``SCHREIBSCHUTZ_PFAD`` / ``SCHREIBSCHUTZ_HARNESSE`` darauf zeigen.

Exit 0 = alle beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIB = ROOT / "tests" / "lib" / "schreibschutz.py"
WAECHTER = ROOT / "tests" / "test_schreibschutz.py"

# (Name, alt, neu) – Sabotagen am MODUL
MODUL = [
    ("Regel 2 fehlt (veraltete Sicherung wird geschrieben) – der Vorfall",
     "                and neu_md5 in self.frueher.get(p, set())):",
     "                and neu_md5 in self.frueher.get(p, set()) and False):"),
    ("Regel 1 fehlt (fremde Aenderung wird ueberschrieben)",
     "        if jetzt is not None and jetzt not in bekannt:",
     "        if False:"),
    ("Verweigerung endet NICHT mit Exit 2",
     "            os._exit(2)\n", "            pass\n"),
    # ⚠ DAS JOURNAL WIRD AN ZWEI STELLEN GEFUEHRT (vor und nach dem Schreiben,
    # das „vor" deckt den Abschuss ZWISCHEN Journal und Datei). Eine Sabotage
    # an nur einer Stelle blieb stumm – gemessen wird deshalb die Wirkung
    # „kein Journal".
    ("Journal wird nicht geschrieben (kill -9 ohne Rueckhalt)",
     "    def _journal_schreiben(self):\n",
     "    def _journal_schreiben(self):\n        return\n"),
    ("open() ist nicht gehakt", "    builtins.open = _open\n", ""),
    ("os.replace ist nicht gehakt", '    os.replace = _os_replace_haken("os_replace")\n', ""),
    ("shutil.copyfile (und damit copy2) ist nicht gehakt", '    shutil.copyfile = _kopie("copyfile")\n', ""),
]


def md5(p):
    return hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()


def lauf(env):
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT),
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **env})
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else -1)


def bewerte(name, rc, f, zaehler):
    if rc == 1 and f > 0:
        print("  ✓  %-66s beisst (%d FAIL)" % (name, f))
        zaehler[0] += 1
    elif f < 0:
        print("  !  %-66s BRICHT AB ohne Bilanz (exit=%s)" % (name, rc))
    else:
        print("  ✗  %-66s BEISST NICHT" % name)


def main():
    vorher = {p: md5(p) for p in (LIB, WAECHTER)}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="gegen-schreibschutz-"))
    zaehler = [0]
    gesamt = 0
    try:
        rc, f = lauf({})
        if rc != 0 or f != 0:
            print("ABBRUCH: Basislauf nicht gruen (exit=%s, fail=%s)" % (rc, f))
            return 2
        print("Basis: gruen")
        text = LIB.read_text(encoding="utf-8")
        for i, (name, alt, neu) in enumerate(MODUL):
            gesamt += 1
            if text.count(alt) != 1:
                print("  ?  %-66s SABOTAGE TRIFFT NICHT (%dx)" % (name, text.count(alt)))
                continue
            d = tmp / ("m%d" % i)
            d.mkdir()
            (d / "schreibschutz.py").write_text(text.replace(alt, neu, 1), encoding="utf-8")
            bewerte(name, *lauf({"SCHREIBSCHUTZ_PFAD": str(d)}), zaehler)

        # Sabotagen an der REGEL: eine Harness-Kopie ohne bzw. mit zu spaeter Aktivierung.
        akt = "schreibschutz.aktivieren(__file__)\n"
        for name, wie in (("ein Harness ohne Aktivierung", "ohne"),
                          ("ein Harness aktiviert erst nach eigener Anweisung", "spaet")):
            gesamt += 1
            d = tmp / ("h-" + wie)
            d.mkdir()
            for h in sorted((ROOT / "tests").glob("gegen_*.py")):
                shutil.copyfile(h, d / h.name)
            ziel = d / "gegen_abmelden_ziel.py"
            t = ziel.read_text(encoding="utf-8")
            if t.count(akt) != 1:
                print("  ?  %-66s SABOTAGE TRIFFT NICHT" % name)
                continue
            if wie == "ohne":
                t = t.replace(akt, "", 1)
            else:
                t = t.replace(akt, "VORHER = 1\n" + akt, 1)
            ziel.write_text(t, encoding="utf-8")
            bewerte(name, *lauf({"SCHREIBSCHUTZ_HARNESSE": str(d)}), zaehler)

        print("\nbeissen: %d von %d" % (zaehler[0], gesamt))
        return 0 if zaehler[0] == gesamt else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if {p: md5(p) for p in vorher} != vorher:
            print("⚠ ARBEITSBAUM VERAENDERT – darf nicht sein")
            sys.exit(2)


if __name__ == "__main__":
    sys.exit(main())
