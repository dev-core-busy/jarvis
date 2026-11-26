#!/usr/bin/env python3
"""Gegenprobe zu test_ausgang.py: beisst der Waechter?

Jede Verfaelschung wird auf eine KOPIE von deploy/security/ausgang.sh
angewendet; der Waechter laeuft gegen die Kopie (JARVIS_AUSGANG_PRUEFLING) und
muss mit Exit 1 rot werden. Die Repo-Datei wird nie angefasst.
Vorher muss der Basislauf gruen sein – sonst ist keine Gegenprobe deutbar.
Exit 0 = jede Verfaelschung erkannt, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
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

REPO = Path(__file__).resolve().parent.parent
ORIGINAL = REPO / "deploy" / "security" / "ausgang.sh"
WAECHTER = REPO / "tests" / "test_ausgang.py"

VERFAELSCHUNGEN = {
    "Log-Regel vor den Freigaben": (
        '    for r in "${REGELN[@]}"; do echo "        $r"; done\n'
        '    echo "        limit rate $LOG_RATE log prefix \\"$praefix\\" flags skuid"\n',
        '    echo "        limit rate $LOG_RATE log prefix \\"$praefix\\" flags skuid"\n'
        '    for r in "${REGELN[@]}"; do echo "        $r"; done\n'),
    "Sperre ohne drop": ('policy="drop"; praefix="$PRAEFIX_DROP"', 'policy="accept"; praefix="$PRAEFIX_DROP"'),
    "Vorgabe sperre statt protokoll": ('MODUS="protokoll"\nREGELN=()', 'MODUS="sperre"\nREGELN=()'),
    "alle mit * erlaubt": ('[[ "$benutzer" != "alle" || "$ziele" != "*" ]] ||', 'true ||'),
    "uid-Bindung fehlt": ('regel+="meta skuid $uid "', 'regel+=""'),
    "Portpruefung fehlt": ('    [[ "$p" == "-" ]] && return 0\n', '    return 0\n'),
    "Zielpruefung fehlt": ('    [[ "$z" == "*" ]] && return 0\n', '    return 0\n'),
    "Log ohne uid": (' flags skuid"', '"'),
    "Log ungedrosselt": ('echo "        limit rate $LOG_RATE log', 'echo "        log'),
    "bestehende Verbindungen fehlen": ('    echo "        ct state established,related accept"\n', ''),
    "anhaengen statt ersetzen": ('    echo "delete table inet $TABELLE"\n', ''),
    "MODUS ungeprueft": ('*) fehler "Zeile $nr: MODUS muss', '*) MODUS=protokoll; : "'),
}


def lauf(pruefling):
    env = dict(os.environ, JARVIS_AUSGANG_PRUEFLING=str(pruefling))
    p = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True, timeout=300, env=env)
    return p.returncode, p.stdout


def main():
    if not ORIGINAL.is_file() or not WAECHTER.is_file():
        print("ABBRUCH: Original oder Waechter fehlt")
        return 2
    rc, aus = lauf(ORIGINAL)
    if rc != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (rc={rc})\n{aus[-800:]}")
        return 2
    print("Basislauf gruen.")
    text = ORIGINAL.read_text()
    nicht_erkannt = 0
    with tempfile.TemporaryDirectory() as d:
        for name, (alt, neu) in VERFAELSCHUNGEN.items():
            if text.count(alt) != 1:
                print(f"  ABBRUCH: Stelle fuer '{name}' nicht eindeutig im Original")
                return 2
            kopie = Path(d) / "ausgang.sh"
            kopie.write_text(text.replace(alt, neu))
            rc, aus = lauf(kopie)
            fails = aus.count("✗")
            if rc == 1:
                print(f"  ✓ {name}: erkannt ({fails} FAIL)")
            else:
                nicht_erkannt += 1
                print(f"  ✗ {name}: NICHT erkannt (rc={rc})")
    print(f"\n{len(VERFAELSCHUNGEN) - nicht_erkannt}/{len(VERFAELSCHUNGEN)} erkannt")
    return 1 if nicht_erkannt else 0


if __name__ == "__main__":
    sys.exit(main())
