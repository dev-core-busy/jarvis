#!/usr/bin/env python3
"""Gegenprobe zu tests/test_system_haertung.py: beisst der Waechter?

Jede Probe sabotiert eine KOPIE von deploy/security/system_haertung.sh in
einem Wegwerf-Verzeichnis und laesst den Waechter gegen diese Kopie laufen
(JARVIS_SYSTEM_HAERTUNG_SKRIPT). Die Repo-Datei wird nie angefasst – ein
abgebrochener Lauf hinterlaesst also keinen Rueckstand im Arbeitsbaum.

Erwartet je Probe: Waechter Exit 1 (Befund). Exit 0 = Probe beisst NICHT,
Exit 2 = Waechter konnte nicht laufen (zaehlt ebenfalls nicht als Biss).
Vorab muss der Basislauf gegen die unveraenderte Kopie gruen sein.

BEWUSST NICHT sabotiert: "Testmodus ohne Wurzel erlaubt". Eine solche Kopie
wuerde im Testmodus auf das ECHTE / schreiben – eine Gegenprobe darf keinen
Zustand ausserhalb ihres Sandkastens herstellen.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKRIPT = REPO / "deploy" / "security" / "system_haertung.sh"
WAECHTER = REPO / "tests" / "test_system_haertung.py"

# (Name, alt, neu, erwartete Trefferzahl von 'alt')
PROBEN = [
    ("root fehlt in den Limits", "\nroot    hard    core    0'", "'", 1),
    ("ptrace_scope locker", "kernel.yama.ptrace_scope = 2", "kernel.yama.ptrace_scope = 0", 1),
    ("modules_disabled gesetzt", "dev.tty.ldisc_autoload = 0",
     "dev.tty.ldisc_autoload = 0\nkernel.modules_disabled = 1", 1),
    ("AIDE prueft die Netzfreigaben", "!/mnt\n", "", 1),
    ("AIDE nimmt den Code aus", "!/media\n", "!/media\n!/opt/jarvis\n", 1),
    ("AIDE haengt an SentinelOne-tracefs", "!/opt/sentinelone/mount\n", "", 1),
    ("root-cmd auch fuer Dienste", "-F auid>=1000 -F auid!=unset -k root-cmd",
     "-F auid>=1000 -k root-cmd", 2),
    ("needrestart startet selbst neu", "'\"'\"'l'\"'\"'", "'\"'\"'a'\"'\"'", 1),
    ("Skript schreibt in apt", "etc/aide/aide.conf.d/95_jarvis_ausnahmen|0644|AIDE",
     "etc/aide/aide.conf.d/95_jarvis_ausnahmen|0644|AIDE\netc/apt/apt.conf.d/52haertung|0644|LIMITS", 1),
    ("sudoers ohne visudo-Pruefung", 'if ! visudo -cf "$tmp" >/dev/null 2>&1; then', "if false; then", 1),
    ("schreibt immer (nicht idempotent)", 'echo "  unveraendert $ziel"\n        return 0', "true", 1),
    ("--pruefen schreibt", "        dateien pruefen\n", "        dateien anwenden\n", 1),
    ("Drop-in ohne LimitCORE=0", "LimitCORE=0'", "LimitCORE=infinity'", 1),
    ("Broker-Zaehler voll geprueft", "/var/lib/jarvis-broker/zaehler\\.json$ f VarFile\n", "", 1),
    ("Freigabeliste als wechselnd gelockert", "/var/lib/jarvis-broker$ d VarDir\n",
     "/var/lib/jarvis-broker$ d VarDir\n/etc/jarvis/broker-policy\\.json$ f VarFile\n", 1),
]


def waechter(skript):
    env = dict(os.environ, JARVIS_SYSTEM_HAERTUNG_SKRIPT=str(skript))
    p = subprocess.run([sys.executable, str(WAECHTER)], env=env,
                       capture_output=True, text=True, timeout=180)
    fails = sum(1 for z in p.stdout.splitlines() if z.startswith("  FAIL"))
    return p.returncode, fails


def main():
    if not SKRIPT.is_file() or not WAECHTER.is_file():
        print("ABBRUCH: Skript oder Waechter fehlt")
        return 2
    original = SKRIPT.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="gegen_sys_haertung_"))
    try:
        basis = tmp / "basis.sh"
        basis.write_text(original, encoding="utf-8")
        rc, f = waechter(basis)
        if rc != 0:
            print("ABBRUCH: Basislauf nicht gruen (Exit %d, %d FAIL) – keine Probe deutbar" % (rc, f))
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, alt, neu, n in PROBEN:
            treffer = original.count(alt)
            if treffer != n:
                print("  PROBE KAPUTT  %-38s Anker %d statt %d Treffer" % (name, treffer, n))
                stumm += 1
                continue
            kopie = tmp / "probe.sh"
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
