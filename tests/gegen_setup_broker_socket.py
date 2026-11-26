#!/usr/bin/env python3
"""Gegenprobe zu tests/test_setup_broker_socket.py: beisst der Waechter?

Jede Probe baut EINE Rueckentwicklung in eine KOPIE von setup_broker.sh (der
Arbeitsbaum wird nicht angefasst) und laesst den Waechter ueber
JARVIS_PRUEFLING_SETUP_BROKER gegen sie laufen; erwartet wird mindestens ein
FAIL (Exit 1). Vorher gruener Basislauf gegen das Original.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
# Schreibschutz: kein Zurueckschreiben ueber fremde Aenderungen (Pflicht fuer
# jeden Harness). Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIG = ROOT / "deploy" / "security" / "setup_broker.sh"
WAECHTER = ROOT / "tests" / "test_setup_broker_socket.py"

PROBEN = [
    ("alter Socket zaehlt (keine Zeitpruefung)",
     '        if [ -S "$pfad" ] && [ "$(stat -c %Z "$pfad" 2>/dev/null || echo 0)" -ge "$seit" ]; then\n',
     '        if [ -S "$pfad" ]; then\n'),
    ("wartet nicht (Einmal-Pruefung in der Funktion)",
     '        [ "$t" -ge "$max" ] && return 1\n        sleep 1; t=$((t+1))\n',
     '        return 1\n'),
    ("Frist zu kurz (4 s wie vor dem Fix)",
     'if _auf_socket_warten "$BROKER_SOCK" "$NEUSTART_SEIT" 60; then\n',
     'if _auf_socket_warten "$BROKER_SOCK" "$NEUSTART_SEIT" 4; then\n'),
    ("Zeitpunkt erst NACH dem Neustart",
     'NEUSTART_SEIT="$(date +%s)"\nsystemctl restart jarvis-broker.service\n',
     'systemctl restart jarvis-broker.service\nNEUSTART_SEIT="$(date +%s)"\n'),
    ("alte Einmal-Pruefung statt Funktion",
     'if _auf_socket_warten "$BROKER_SOCK" "$NEUSTART_SEIT" 60; then\n',
     'sleep 4\nif [ -S /run/jarvis-broker.sock ]; then\n'),
]


def lauf(pfad):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", JARVIS_PRUEFLING_SETUP_BROKER=str(pfad))
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, env=env)
    return r.returncode, r.stdout


def main():
    rc, aus = lauf(ORIG)
    if rc != 0:
        print("ABBRUCH: Basislauf nicht gruen (rc=%d)\n%s" % (rc, aus[-600:]))
        return 2
    print("Basislauf gruen.\n")
    text = ORIG.read_text(encoding="utf-8")
    beissen = 0
    with tempfile.TemporaryDirectory(prefix="gegen_sb_") as d:
        for name, alt, neu in PROBEN:
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            kopie = Path(d) / "setup_broker.sh"
            kopie.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            rc, aus = lauf(kopie)
            fails = aus.count("  FAIL ")
            if rc == 1 and fails:
                beissen += 1
                print("  BISS %-50s %d FAIL" % (name, fails))
            else:
                print("  ---- %-50s beisst NICHT (rc=%d)" % (name, rc))
    print("\n%d/%d Proben beissen" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
