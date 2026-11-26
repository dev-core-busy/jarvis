#!/usr/bin/env python3
"""Waechter: ``firewall.sh --anwenden`` laesst jarvis-firewall.service LAUFEN,
nicht nur aktiviert zurueck (2026-11-26).

Befund: Nach einer Neuinstallation meldete die Serverueberwachung am Zahnrad
"jarvis-firewall.service ist aktiviert, laeuft aber nicht (inactive)". Die
Regeln standen (regeln_setzen laedt sie direkt), persistieren() hatte die Unit
aber nur per ``systemctl enable`` fuer den naechsten Boot vorgemerkt – bis zum
ersten Neustart war sie inactive.

Zusagen, gemessen am ECHTEN Skript in einem Sandkasten (``JARVIS_FW_TEST``,
Attrappen fuer iptables/ip6tables/-save/-restore, nft, systemctl, ss) – auf
dem iptables- UND dem nft-Weg:
  1. die Unit wird nach dem Aktivieren gestartet;
  2. eine schon laufende Unit wird NICHT erneut gestartet;
  3. scheitert der Start, endet --anwenden trotzdem mit Exit 0 und WARNT
     (die Regeln sind geladen – ein Abbruch meldete einen Filter als
     gescheitert, der steht).

Pruefling umlenkbar fuer die Gegenprobe: JARVIS_PRUEFLING_FIREWALL.

    python3 tests/test_firewall_unit_start.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKRIPT = Path(os.environ.get("JARVIS_PRUEFLING_FIREWALL",
                             ROOT / "deploy" / "security" / "firewall.sh"))
UNIT = "jarvis-firewall.service"
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  OK   %s" % name)
    else:
        fail += 1
        print("  FAIL %s%s" % (name, (" – %s" % (detail,)) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="fw_unit_start_"))


def sandkasten(art, unit_aktiv=False, start_scheitert=False):
    d = Path(tempfile.mkdtemp(dir=TMP))
    bin_ = d / "bin"
    bin_.mkdir()
    log = d / "log"
    for n in ("etc", "sicherung", "units"):
        (d / n).mkdir()

    def attrappe(name, rumpf):
        p = bin_ / name
        p.write_text("#!/bin/sh\nprintf '%s %%s\\n' \"$*\" >> \"%s\"\n%s\n" % (name, log, rumpf))
        p.chmod(0o755)

    if art == "iptables":
        attrappe("iptables", 'case "$1" in -C) exit 1;; esac; exit 0')
        attrappe("ip6tables", 'case "$1" in -C) exit 1;; esac; exit 0')
        attrappe("iptables-save", "echo '# V4-STAND'")
        attrappe("ip6tables-save", "echo '# V6-STAND'")
        attrappe("iptables-restore", "exit 0")
        attrappe("ip6tables-restore", "exit 0")
    attrappe("nft", "[ \"$1\" = \"-f\" ] && cat > /dev/null; exit 0")
    attrappe("ss", "exit 0")
    # is-active: nur die Firewall-Unit kann "aktiv" sein (fw-rollback.timer nie)
    attrappe("systemctl",
             'case "$1" in\n'
             '  is-active) for a in "$@"; do [ "$a" = "%s" ] && exit %d; done; exit 3;;\n'
             '  start) exit %d;;\n'
             'esac\nexit 0' % (UNIT, 0 if unit_aktiv else 3, 1 if start_scheitert else 0))
    env = {"PATH": "%s:/usr/bin:/bin" % bin_, "HOME": str(d), "JARVIS_FW_TEST": "1",
           "JARVIS_FW_SICHERUNG": str(d / "sicherung"), "JARVIS_FW_ETC": str(d / "etc"),
           "JARVIS_UNIT_DIR": str(d / "units"),
           "JARVIS_BROKER_CONF": str(d / "etc" / "broker.conf")}
    return env, log, d


def anwenden(env):
    try:
        return subprocess.run(["bash", str(SKRIPT), "--anwenden"], env=env, capture_output=True,
                              text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        abbruch("firewall.sh --anwenden haengt im Sandkasten (Attrappe?)")


def zeilen(log):
    return log.read_text().splitlines() if log.exists() else []


def pos(z, praefix):
    """Index der ersten Zeile mit diesem Anfang, sonst -1 (wirft nie)."""
    return next((i for i, s in enumerate(z) if s.startswith(praefix)), -1)


if not SKRIPT.is_file():
    abbruch("Pruefling fehlt: %s" % SKRIPT)
# Positivkontrolle der Sandkasten-Annahme: iptables liegt NICHT im echten Pfad,
# sonst waere der nft-Weg nicht erreichbar
r = subprocess.run(["bash", "-c", "command -v iptables"], env={"PATH": "/usr/bin:/bin"},
                   capture_output=True, text=True)
if r.returncode == 0:
    abbruch("iptables liegt im Systempfad (%s) – der nft-Weg waere nicht messbar" % r.stdout.strip())

try:
    for art in ("iptables", "nft"):
        print("\n%s-Weg" % art)
        env, log, d = sandkasten(art)
        r = anwenden(env)
        z = zeilen(log)
        regeln = pos(z, "iptables -A JARVIS-IN") if art == "iptables" else pos(z, "nft -f")
        enable = pos(z, "systemctl enable %s" % UNIT)
        start = pos(z, "systemctl start %s" % UNIT)
        # Positivkontrolle: der Lauf hat Regeln gesetzt und persistiert
        if r.returncode != 0 or regeln < 0 or enable < 0 or not (d / "units" / UNIT).exists():
            abbruch("%s: --anwenden lief im Sandkasten nicht durch (rc=%d, Regeln=%d, enable=%d)\n%s"
                    % (art, r.returncode, regeln, enable, (r.stdout + r.stderr)[-400:]))
        check("%s: Unit wird gestartet" % art, start >= 0, z[-6:])
        check("%s: Start NACH dem Aktivieren und nach dem Laden der Regeln" % art,
              start > enable and start > regeln, (regeln, enable, start))

        env, log, d = sandkasten(art, unit_aktiv=True)
        r = anwenden(env)
        z = zeilen(log)
        check("%s: laufende Unit wird nicht erneut gestartet" % art,
              r.returncode == 0 and pos(z, "systemctl start %s" % UNIT) < 0
              and pos(z, "systemctl is-active") >= 0, (r.returncode, z[-6:]))

        env, log, d = sandkasten(art, start_scheitert=True)
        r = anwenden(env)
        z = zeilen(log)
        check("%s: gescheiterter Start -> trotzdem Exit 0" % art,
              r.returncode == 0 and pos(z, "systemctl start %s" % UNIT) >= 0,
              (r.returncode, r.stderr[-200:]))
        check("%s: … und eine WARNUNG nennt die Unit" % art,
              "WARNUNG" in r.stderr and UNIT in r.stderr, r.stderr[-300:])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
