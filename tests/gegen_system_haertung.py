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
    # Anker 2026-11-20 nachgezogen: die Schranke nimmt seit d246ae87 die
    # Begruendung von visudo mit und benutzt seit aec7baaf+1 $VISUDO. Die alte
    # Zeile gab es nicht mehr - die Probe war stumm und haette es erst beim
    # naechsten Lauf dieses Harness gemeldet ("PROBE KAPUTT").
    ("sudoers ohne visudo-Pruefung",
     'if ! visudo_sagt="$(LC_ALL=C "$VISUDO" -cf "$tmp" 2>&1)"; then', "if false; then", 1),
    # Der Schalter fuer das Pruefwerkzeug darf nur im Testmodus wirken.
    ("JARVIS_VISUDO wirkt auch im Produktivlauf",
     'if [ -n "$TEST" ] && [ -n "${JARVIS_VISUDO:-}" ]; then',
     'if [ -n "${JARVIS_VISUDO:-}" ]; then', 1),
    ("schreibt immer (nicht idempotent)", 'echo "  unveraendert $ziel"\n        return 0', "true", 1),
    ("--pruefen schreibt", "        dateien pruefen\n", "        dateien anwenden\n", 1),
    ("Drop-in ohne LimitCORE=0", "LimitCORE=0'", "LimitCORE=infinity'", 1),
    ("Broker-Zaehler voll geprueft", "/var/lib/jarvis-broker/zaehler\\.json$ f VarFile\n", "", 1),
    ("sudo.log ohne Rotation", "etc/logrotate.d/sudo-haertung|0644|LOGROTATE\n", "", 1),
    ("sudo.log voll geprueft", "/var/log/sudo\\.log$ f Log\n", "", 1),
    ("auditd behaelt 5 x 8 MB", 'AUDITD_WERTE="max_log_file=50 num_logs=20"', 'AUDITD_WERTE=""', 1),
    ("AIDE nimmt ganz /var/log aus", "!/media\n", "!/media\n!/var/log\n", 1),
    ("Sandbox-Arbeitsverzeichnisse voll geprueft", "!/tmp/jarvis-arbeit\n", "", 1),
    ("Freigabeliste als wechselnd gelockert", "/var/lib/jarvis-broker$ d VarDir\n",
     "/var/lib/jarvis-broker$ d VarDir\n/etc/jarvis/broker-policy\\.json$ f VarFile\n", 1),
    # B14
    ("jarvis-web mit faillock", "auth     required   pam_unix.so\n",
     "auth     requisite  pam_faillock.so preauth\nauth     required   pam_unix.so\n", 1),
    ("faillock nach 3 statt 5 Versuchen", 'FAILLOCK_ARGS="deny=5 ', 'FAILLOCK_ARGS="deny=3 ', 1),
    ("faillock sperrt auch root", 'fail_interval=900"', 'fail_interval=900 even_deny_root"', 1),
    ("Profile mit verschiedenen Werten", "pam_faillock.so authfail $FAILLOCK_ARGS",
     "pam_faillock.so authfail deny=10 unlock_time=900 fail_interval=900", 1),
    ("Profil ohne Zuruecksetzen (account)", "Account:\n\trequired\tpam_faillock.so", "Account:\n\trequired\tpam_permit.so", 1),
    ("pwquality minlen 8", "minlen = 14'", "minlen = 8'", 1),
    ("Paket libpam-pwquality fehlt", " lynis libpam-pwquality\"", " lynis\"", 1),
    ("Schranke alter Code fehlt", 'if [ -f "$code" ] && ! grep -q', 'if false && ! grep -q', 1),
    ("--pruefen blind fuer preauth",
     "pam_faillock\\.so[[:space:]]+preauth' \"$d/common-auth\" 2>/dev/null \\\n        ||",
     "pam_faillock\\.so[[:space:]]+preauth' \"$d/common-auth\" 2>/dev/null \\\n        || true ||", 1),
    ("pam-auth-update bei jedem Lauf", '    if [ "$fehlt" -eq 0 ]; then', '    if false; then', 1),
    ("Testmodus ruft echtes pam-auth-update",
     '    if [ -n "$TEST" ] && [ -z "${JARVIS_PAM_AUTH_UPDATE:-}" ]; then', '    if false; then', 1),
    ("JARVIS_PAM_AUTH_UPDATE auch im Produktivlauf",
     'if [ -n "$TEST" ] && [ -n "${JARVIS_PAM_AUTH_UPDATE:-}" ]; then',
     'if [ -n "${JARVIS_PAM_AUTH_UPDATE:-}" ]; then', 1),
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
