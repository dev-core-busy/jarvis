#!/usr/bin/env python3
"""Waechter: ``firewall.sh --test`` setzt Regeln nur MIT vollstaendigem Rueckfall
(Code-Review 2026-10-07).

Befunde:
  * iptables-Weg: der Rueckfall-Timer stellte nur IPv4 wieder her
    (``iptables-restore``); ``ip6tables -P INPUT DROP`` aus regeln_setzen blieb
    stehen – eine Aussperrung ueber IPv6 heilte nicht.
  * Lief schon ein ``fw-rollback``-Timer, scheiterte systemd-run (Unit
    existiert). Es kam nur eine WARNUNG, und die Regeln wurden trotzdem gesetzt
    – ohne Rueckfall.

Gemessen am ECHTEN Skript in einem Sandkasten (``JARVIS_FW_TEST``, Attrappen
fuer iptables/ip6tables/-save/-restore, nft, systemctl, systemd-run, ss). Der
Rueckfall wird ausgefuehrt, wie systemd ihn ausfuehren wuerde: GENAU der
Befehl, den systemd-run bekommen hat.

    python3 tests/test_firewall_rueckfall.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKRIPT = ROOT / "deploy" / "security" / "firewall.sh"
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % (detail,)) if detail else ""))


def abbruch(grund):
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


if os.geteuid() == 0:
    abbruch("als root ausgefuehrt – die Attrappen koennten echte Befehle verdecken")
if not SKRIPT.is_file():
    abbruch("firewall.sh fehlt")

SK = Path(tempfile.mkdtemp(prefix="fw_rueckfall_"))


def sandkasten(art: str, timer_aktiv=False, run_scheitert=False):
    """Frischer Sandkasten; ``art`` = iptables | nft. Rueckgabe (env, LOG, RUN)."""
    d = SK / ("%s_%d_%d" % (art, timer_aktiv, run_scheitert))
    bin_ = d / "bin"
    bin_.mkdir(parents=True)
    log, run = d / "log", d / "systemd-run.args"
    for n in ("etc", "sicherung", "units"):
        (d / n).mkdir()

    def attrappe(name, rumpf):
        p = bin_ / name
        p.write_text("#!/bin/sh\nprintf '%s %%s\\n' \"$*\" >> \"%s\"\n%s\n" % (name, log, rumpf))
        p.chmod(0o755)

    if art == "iptables":
        # -C (Regel vorhanden?) = nein: das Skript raeumt Altregeln mit
        # `while iptables -C …; do iptables -D …` – ein immer-0 drehte endlos
        attrappe("iptables", 'case "$1" in -C) exit 1;; esac; exit 0')
        attrappe("ip6tables", 'case "$1" in -C) exit 1;; esac; exit 0')
        attrappe("iptables-save", "echo '# V4-STAND'")
        attrappe("ip6tables-save", "echo '# V6-STAND'")
        attrappe("iptables-restore", "echo \"iptables-restore-datei $(cat \"$1\")\" >> \"%s\"" % log)
        attrappe("ip6tables-restore", "echo \"ip6tables-restore-datei $(cat \"$1\")\" >> \"%s\"" % log)
    attrappe("nft", "[ \"$1\" = \"-f\" ] && cat > /dev/null; exit 0")
    attrappe("ss", "exit 0")
    attrappe("systemctl",
             'case "$1" in is-active) %s;; esac; exit 0' % ("exit 0" if timer_aktiv else "exit 3"))
    # systemd-run: die Argumente NUL-getrennt festhalten (Quoting bleibt erhalten)
    attrappe("systemd-run",
             'for a in "$@"; do printf "%%s\\0" "$a"; done > "%s"; exit %d'
             % (run, 1 if run_scheitert else 0))
    env = {"PATH": "%s:/usr/bin:/bin" % bin_, "HOME": str(d), "JARVIS_FW_TEST": "1",
           "JARVIS_FW_SICHERUNG": str(d / "sicherung"), "JARVIS_FW_ETC": str(d / "etc"),
           "JARVIS_UNIT_DIR": str(d / "units"),
           "JARVIS_BROKER_CONF": str(d / "etc" / "broker.conf")}
    return env, log, run


def lauf(env):
    try:
        return subprocess.run(["bash", str(SKRIPT), "--test", "60"], env=env, capture_output=True,
                              text=True, timeout=60, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        abbruch("firewall.sh --test haengt im Sandkasten (Attrappe?)")


def gesetzt(log: Path) -> bool:
    t = log.read_text() if log.exists() else ""
    return "-A JARVIS-IN" in t or "nft -f" in t


# Positivkontrolle der Sandkasten-Annahme: iptables liegt NICHT im echten Pfad
r = subprocess.run(["bash", "-c", "command -v iptables"], env={"PATH": "/usr/bin:/bin"},
                   capture_output=True, text=True)
if r.returncode == 0:
    abbruch("iptables liegt im Systempfad (%s) – der nft-Weg waere nicht messbar" % r.stdout.strip())

print("\n\033[1m1 – iptables-Weg: Rueckfall stellt IPv4 UND IPv6 her\033[0m")
env, log, run = sandkasten("iptables")
r = lauf(env)
check("Positivkontrolle: --test laeuft durch und setzt Regeln", r.returncode == 0 and gesetzt(log),
      (r.returncode, r.stderr[-300:]))
check("… auch fuer IPv6 (ip6tables -P INPUT DROP o. ae.)", "ip6tables -" in log.read_text())
args = run.read_bytes().split(b"\0")[:-1] if run.exists() else []
args = [a.decode() for a in args]
check("Positivkontrolle: systemd-run bekam einen Befehl", bool(args), args)
idx = next((i for i, a in enumerate(args) if not a.startswith("--")), None)
befehl = args[idx:] if idx is not None else []
log.write_text("")
if befehl:
    subprocess.run(befehl, env=env, capture_output=True, text=True, timeout=30)
t = log.read_text()
check("Rueckfall: IPv4-Sicherung zurueck", "iptables-restore-datei # V4-STAND" in t, t[-300:])
check("⚠ Rueckfall: IPv6-Sicherung zurueck", "ip6tables-restore-datei # V6-STAND" in t, t[-300:])

for art in ("iptables", "nft"):
    print("\n\033[1m2 – %s: laufender Test wird nicht ueberschrieben\033[0m" % art)
    env, log, run = sandkasten(art, timer_aktiv=True)
    r = lauf(env)
    check("⚠ %s: Timer laeuft schon -> Abbruch, KEINE Regeln" % art,
          r.returncode != 0 and not gesetzt(log) and not run.exists(),
          (r.returncode, r.stdout[-200:], r.stderr[-200:]))
    print("\n\033[1m3 – %s: ohne Rueckfall-Timer keine Regeln\033[0m" % art)
    env, log, run = sandkasten(art, run_scheitert=True)
    r = lauf(env)
    check("⚠ %s: systemd-run scheitert -> Abbruch, KEINE Regeln" % art,
          r.returncode != 0 and not gesetzt(log), (r.returncode, r.stdout[-200:], r.stderr[-200:]))
    check("… mit Meldung", "ABBRUCH" in r.stderr, r.stderr[-200:])

env, log, run = sandkasten("nft")
r = lauf(env)
check("Positivkontrolle nft: --test laeuft durch und setzt Regeln", r.returncode == 0 and gesetzt(log),
      (r.returncode, r.stderr[-300:]))

shutil.rmtree(SK, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
