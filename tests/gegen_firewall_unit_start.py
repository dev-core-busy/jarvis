#!/usr/bin/env python3
"""Gegenprobe zu tests/test_firewall_unit_start.py: beisst der Waechter?

Jede Probe baut EINE Rueckentwicklung in eine KOPIE von firewall.sh (der
Arbeitsbaum wird nicht angefasst) und laesst den Waechter ueber
JARVIS_PRUEFLING_FIREWALL gegen sie laufen; erwartet wird mindestens ein FAIL
(Exit 1). Vorher gruener Basislauf gegen das Original.

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
ORIG = ROOT / "deploy" / "security" / "firewall.sh"
WAECHTER = ROOT / "tests" / "test_firewall_unit_start.py"

PROBEN = [
    ("nft-Weg startet nicht (Stand vor dem Fix)",
     '        _unit_starten\n        echo "Regeln gespeichert (/etc/jarvis/firewall.nft) + Unit aktiviert."',
     '        echo "Regeln gespeichert (/etc/jarvis/firewall.nft) + Unit aktiviert."'),
    ("iptables-Weg startet nicht (Stand vor dem Fix)",
     '    _unit_starten\n    echo "Regeln gespeichert (/etc/jarvis/firewall-v*.rules) + Unit aktiviert."',
     '    echo "Regeln gespeichert (/etc/jarvis/firewall-v*.rules) + Unit aktiviert."'),
    ("laufende Unit wird neu gestartet",
     '    systemctl is-active --quiet jarvis-firewall.service && return 0\n',
     ''),
    ("gescheiterter Start bricht ab",
     '    systemctl start jarvis-firewall.service >/dev/null 2>&1 \\\n'
     '        || echo "WARNUNG',
     '    systemctl start jarvis-firewall.service >/dev/null 2>&1 \\\n'
     '        || return 1; echo "WARNUNG'),
    ("gescheiterter Start ohne Warnung",
     '        || echo "WARNUNG: jarvis-firewall.service liess sich nicht starten',
     '        || : "jarvis-firewall.service liess sich nicht starten'),
]


def lauf(pfad):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", JARVIS_PRUEFLING_FIREWALL=str(pfad))
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
    with tempfile.TemporaryDirectory(prefix="gegen_fw_unit_") as d:
        for name, alt, neu in PROBEN:
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            kopie = Path(d) / "firewall.sh"
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
