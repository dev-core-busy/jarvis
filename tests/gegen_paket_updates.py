#!/usr/bin/env python3
"""Gegenprobe zu tests/test_paket_updates.py: beisst der Waechter?

Jede Probe sabotiert eine KOPIE von backend/paket_updates.py; der Waechter
laedt sie ueber JARVIS_PAKET_UPDATES_MODUL. Die Repo-Datei bleibt unberuehrt.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODUL = REPO / "backend" / "paket_updates.py"
WAECHTER = REPO / "tests" / "test_paket_updates.py"

PROBEN = [
    ("Entfernung im Trockenlauf egal", '    if plan["entfernt"]:\n', "    if False:\n", 1),
    ("upgrade ohne --no-remove", '"--no-remove", "upgrade"]', '"upgrade"]', 1),
    ("needrestart startet selbst neu", 'NEEDRESTART_MODE="l"', 'NEEDRESTART_MODE="a"', 1),
    ("Konfiguration wird ueberschrieben", '"-o", "Dpkg::Options::=--force-confold",', '', 1),
    ("dbus darf neu starten", 'r"^(?:dbus|dbus-broker|', 'r"^(?:dbus-broker|', 1),
    ("lightdm darf neu starten", "|lightdm|gdm3?|", "|gdm3?|", 1),
    ("Neustart ohne needrestart-Abgleich", "    if dienst not in genannt:\n", "    if False:\n", 1),
    ("Oneshot darf neu starten", 'if (r.stdout or "").strip() == "oneshot":', "if False:", 1),
    ("Anwendung sofort neu gestartet", "    if dienst in _SELBST:\n", "    if False:\n", 1),
    ("AIDE nicht angestossen", "    if eingespielt:\n        a = aide_abgleich.pruefung_starten()",
     "    if False:\n        a = aide_abgleich.pruefung_starten()", 1),
    ("Sicherheitsquelle nicht erkannt", '"sicherheit": "-security" in quelle or "Debian-Security" in quelle,',
     '"sicherheit": False,', 1),
    ("doppelte Dienste", 'and v not in erg["dienste"]:', ":", 1),
    ("Fortschritt als Hinweis", 'i = ausgabe.find("apt-listchanges: News")', 'i = ausgabe.find("apt-listchanges")', 1),
    ("Hinweis mit dpkg-Ausgabe", 'ende = ausgabe.find("(Reading database", i)', "ende = -1", 1),
]


def waechter(modul):
    env = dict(os.environ, JARVIS_PAKET_UPDATES_MODUL=str(modul), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(WAECHTER)], env=env, capture_output=True, text=True, timeout=120)
    return p.returncode, sum(1 for z in p.stdout.splitlines() if z.startswith("  FAIL"))


def main():
    original = MODUL.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="gegen_paket_updates_"))
    try:
        basis = tmp / "basis.py"
        basis.write_text(original, encoding="utf-8")
        rc, f = waechter(basis)
        if rc != 0:
            print("ABBRUCH: Basislauf nicht gruen (Exit %d, %d FAIL) – keine Probe deutbar" % (rc, f))
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, alt, neu, n in PROBEN:
            if original.count(alt) != n:
                print("  PROBE KAPUTT  %-38s Anker %d statt %d Treffer" % (name, original.count(alt), n))
                stumm += 1
                continue
            kopie = tmp / "probe.py"
            kopie.write_text(original.replace(alt, neu), encoding="utf-8")
            rc, f = waechter(kopie)
            if rc == 1 and f > 0:
                print("  beisst        %-38s %d FAIL" % (name, f))
            else:
                print("  STUMM         %-38s Exit %d, %d FAIL" % (name, rc, f))
                stumm += 1
        print("ERGEBNIS: %d von %d Proben beissen" % (len(PROBEN) - stumm, len(PROBEN)))
        return 0 if stumm == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
