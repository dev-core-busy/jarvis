#!/usr/bin/env python3
"""Gegenprobe zu tests/test_firewall_log.py: beisst der Waechter?

Jede Probe sabotiert eine KOPIE von deploy/security/firewall.sh bzw.
backend/egress_guard.py in einem Wegwerf-Verzeichnis und laesst den Waechter
gegen diese Kopie laufen (JARVIS_FW_PRUEFLING / JARVIS_EGRESS_PRUEFLING). Die
Repo-Dateien werden nie angefasst.

Erwartet je Probe: Waechter Exit 1 mit mindestens einem FAIL. Exit 0 = Probe
beisst NICHT, Exit 2 = Waechter konnte nicht laufen (zaehlt ebenfalls nicht).
Vorab muss der Basislauf gegen die unveraenderten Kopien gruen sein.

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
FW = REPO / "deploy" / "security" / "firewall.sh"
EG = REPO / "backend" / "egress_guard.py"
WAECHTER = REPO / "tests" / "test_firewall_log.py"

# (Name, Datei "fw"|"eg", alt, neu, erwartete Trefferzahl von 'alt')
PROBEN = [
    ("input ohne Log-Regel", "fw",
     '        meta pkttype host limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_IN"\n', "", 1),
    ("forward ohne Log-Regel", "fw",
     '        meta pkttype host limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_FWD"\n', "", 1),
    ("Log-Regel VOR den Freigaben (protokolliert Erlaubtes)", "fw",
     '        iif lo accept\n',
     '        meta pkttype host limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_IN"\n        iif lo accept\n', 1),
    ("ungedrosselt", "fw", '        meta pkttype host limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_IN"\n',
     '        meta pkttype host log prefix "$FW_LOG_PREFIX_IN"\n', 1),
    ("Drossel 50/minute", "fw", 'FW_LOG_RATE="5/minute"', 'FW_LOG_RATE="50/minute"', 1),
    ("anderes Praefix (Ueberwachung findet nichts)", "fw",
     'FW_LOG_PREFIX_IN="nft-in-drop: "', 'FW_LOG_PREFIX_IN="drop: "', 1),
    ("Log-Regel verwirft selbst", "fw",
     '        meta pkttype host limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_IN"\n',
     '        meta pkttype host limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_IN" drop\n', 1),
    ("nft-Syntaxfehler in der Log-Regel", "fw",
     '        meta pkttype host limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_FWD"\n',
     '        meta pkttype host limit rate $FW_LOG_RATE lag prefix "$FW_LOG_PREFIX_FWD"\n', 1),
    ("iptables: JARVIS-IN ohne LOG", "fw",
     '        "$ipt" -A JARVIS-IN "${log_arg[@]}" --log-prefix "$FW_LOG_PREFIX_IN"\n', "", 1),
    ("iptables: FORWARD waechst je Lauf (ohne -C)", "fw",
     '        "$ipt" -C FORWARD "${log_arg[@]}" --log-prefix "$FW_LOG_PREFIX_FWD" 2>/dev/null \\\n            || ',
     "        ", 1),
    ("Multicast zaehlt mit (nft)", "fw",
     '        meta pkttype host limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_IN"\n',
     '        limit rate $FW_LOG_RATE log prefix "$FW_LOG_PREFIX_IN"\n', 1),
    ("Multicast zaehlt mit (iptables)", "fw",
     '(-m pkttype --pkt-type unicast -m limit', '(-m limit', 1),
    ("iptables: LOG vor den SSH-Freigaben", "fw",
     "        # 4b) SSH nur aus SSH_NETZE (BSI M7), je Familie die passende Liste\n",
     '        "$ipt" -A JARVIS-IN -j LOG --log-prefix "$FW_LOG_PREFIX_IN"\n'
     "        # 4b) SSH nur aus SSH_NETZE (BSI M7), je Familie die passende Liste\n", 1),
    ("Ausgang ohne Log-Regel", "eg",
     '        f"        meta skuid {uid} limit rate 5/minute log prefix \\"nft-out-drop: \\" flags skuid\\n"\n',
     "", 1),
    ("Ausgang: Log ungebunden (Kernel-Sockets)", "eg",
     'f"        meta skuid {uid} limit rate 5/minute log prefix',
     'f"        limit rate 5/minute log prefix', 1),
    ("Ausgang: ohne flags skuid", "eg", '\\"nft-out-drop: \\" flags skuid\\n"', '\\"nft-out-drop: \\"\\n"', 1),
    ("Ausgang: Log hinter dem drop", "eg",
     '        f"        meta skuid {uid} limit rate 5/minute log prefix \\"nft-out-drop: \\" flags skuid\\n"\n',
     "", 1),
    ("Ausgang: Log-Regel zaehlt als veraltet", "eg",
     'if re.search(r"\\bdrop\\b", z) and not re.search(r"\\bskuid\\b", z):',
     'if re.search(r"\\bdrop\\b", z) and (not re.search(r"\\bskuid\\b", z) or " log " in z):', 1),
]
# "Log hinter dem drop" haengt die Zeile zusaetzlich hinter das drop an:
NACHTRAG = {"Ausgang: Log hinter dem drop": (
    '        f"        meta skuid {uid} drop\\n"\n',
    '        f"        meta skuid {uid} drop\\n"\n'
    '        f"        meta skuid {uid} limit rate 5/minute log prefix \\"nft-out-drop: \\" flags skuid\\n"\n')}


def waechter(fw, eg):
    env = dict(os.environ, JARVIS_FW_PRUEFLING=str(fw), JARVIS_EGRESS_PRUEFLING=str(eg),
               PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(WAECHTER)], env=env, capture_output=True,
                       text=True, timeout=240)
    fails = p.stdout.count("\033[31m✗\033[0m")
    return p.returncode, fails


def main():
    for f in (FW, EG, WAECHTER):
        if not f.is_file():
            print(f"ABBRUCH: {f} fehlt")
            return 2
    original = {"fw": FW.read_text(encoding="utf-8"), "eg": EG.read_text(encoding="utf-8")}
    tmp = Path(tempfile.mkdtemp(prefix="gegen_fw_log_"))
    try:
        pfad = {"fw": tmp / "firewall.sh", "eg": tmp / "egress_guard.py"}

        def schreiben(wer, text):
            for k in ("fw", "eg"):
                pfad[k].write_text(text if k == wer else original[k], encoding="utf-8")

        schreiben("fw", original["fw"])
        rc, f = waechter(pfad["fw"], pfad["eg"])
        if rc != 0:
            print("ABBRUCH: Basislauf nicht gruen (Exit %d, %d FAIL) – keine Probe deutbar" % (rc, f))
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, wer, alt, neu, n in PROBEN:
            text = original[wer]
            treffer = text.count(alt)
            if treffer != n:
                print("  PROBE KAPUTT  %-52s Anker %d statt %d Treffer" % (name, treffer, n))
                stumm += 1
                continue
            text = text.replace(alt, neu)
            if name in NACHTRAG:
                a2, n2 = NACHTRAG[name]
                if text.count(a2) != 1:
                    print("  PROBE KAPUTT  %-52s Nachtrag-Anker fehlt" % name)
                    stumm += 1
                    continue
                text = text.replace(a2, n2)
            schreiben(wer, text)
            rc, f = waechter(pfad["fw"], pfad["eg"])
            if rc == 1 and f > 0:
                print("  beisst        %-52s %d FAIL" % (name, f))
            else:
                print("  STUMM         %-52s Exit %d, %d FAIL" % (name, rc, f))
                stumm += 1
        print("ERGEBNIS: %d von %d Proben beissen" % (len(PROBEN) - stumm, len(PROBEN)))
        return 0 if stumm == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
