#!/usr/bin/env python3
"""Waechter fuer backend/paket_updates.py.

Testmaterial sind Ausgaben, wie sie auf DEV am 24.11.2026 gemessen wurden
(``apt-get -s upgrade`` mit LANG=C, ``needrestart -b -r l``) – kein
erfundenes Format. Ausgefuehrt wird der echte Code; nur ``_run`` (also die
Kommandos) ist eine Attrappe mit der echten Signatur und Rueckgabeform
(``subprocess.CompletedProcess``).

Zusagen:
  1. Trockenlauf: Pakete mit alter/neuer Fassung und Quelle, Sicherheitsquelle
     erkannt, zurueckgehaltene und zu entfernende Pakete getrennt.
  2. needrestart: Kernelstand, nur echte .service-Namen, keine Doppelten.
  3. Neustart nie fuer dbus, logind, Desktop-Anmeldung, Update-Auftraege.
  4. einspielen: plant apt eine Entfernung, laeuft KEIN upgrade; das upgrade
     laeuft mit --no-remove, NEEDRESTART_MODE=l, --force-confold; ohne offene
     Pakete laeuft es gar nicht; nach dem Einspielen wird AIDE angestossen.
  5. dienst_neustart: nur, was needrestart JETZT nennt; kein Oneshot; die
     Anwendung selbst nur verzoegert (die Antwort muss zurueckgehen).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import importlib
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OK = FAIL = 0


def pruefe(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


# Gegenprobe (tests/gegen_paket_updates.py) laedt eine sabotierte KOPIE
_KOPIE = os.environ.get("JARVIS_PAKET_UPDATES_MODUL", "")
if _KOPIE:
    _spec = importlib.util.spec_from_file_location("paket_updates_probe", _KOPIE)
    P = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(P)
else:
    P = importlib.import_module("backend.paket_updates")

# Attrappen fuer die beiden Module, die einspielen/status nachladen
_aide_aufrufe = []
aide_attrappe = types.ModuleType("backend.aide_abgleich")
aide_attrappe.pruefung_starten = lambda: (_aide_aufrufe.append(1), {"ok": True, "laeuft": True})[1]
cve_attrappe = types.ModuleType("backend.cve_apt")
cve_attrappe.index_alter = lambda: 1795480000.0
import backend  # noqa: E402
sys.modules["backend.aide_abgleich"] = aide_attrappe
sys.modules["backend.cve_apt"] = cve_attrappe
backend.aide_abgleich = aide_attrappe
backend.cve_apt = cve_attrappe

SIM = """Reading package lists...
Building dependency tree...
Calculating upgrade...
The following packages have been kept back:
  linux-image-amd64 phasedpkg
The following packages will be upgraded:
  base-files libssl3t64 openssl google-chrome-stable
4 upgraded, 0 newly installed, 0 to remove and 2 not upgraded.
Inst base-files [13.8+deb13u7] (13.8+deb13u8 Debian:13.8/stable [amd64])
Inst libssl3t64 [3.5.7-1~deb13u3] (3.5.9-1~deb13u1 Debian:13.8/stable, Debian-Security:13/stable-security [amd64])
Inst libext2fs2t64 [1.47.2-3+b7] (1.47.2-3+b12 Debian:13.8/stable [amd64]) [e2fsprogs:amd64 on libext2fs2t64:amd64] [e2fsprogs:amd64 ]
Inst google-chrome-stable [149.0.7827.53-1] (158.0.8127.88-1 Google:1.0/stable [amd64])
Conf base-files (13.8+deb13u8 Debian:13.8/stable [amd64])
Conf libssl3t64 (3.5.9-1~deb13u1 Debian:13.8/stable [amd64])
"""
SIM_REMV = SIM + "Remv libfoo1 [1.0-1]\n"
NR = """NEEDRESTART-VER: 3.11
NEEDRESTART-KCUR: 6.12.117+deb13-amd64
NEEDRESTART-KEXP: 6.12.118+deb13-amd64
NEEDRESTART-KSTA: 3
NEEDRESTART-SVC: accounts-daemon.service
NEEDRESTART-SVC: apt-daily-upgrade.service
NEEDRESTART-SVC: dbus.service
NEEDRESTART-SVC: getty@tty1.service
NEEDRESTART-SVC: lightdm.service
NEEDRESTART-SVC: open-vm-tools
NEEDRESTART-SVC: open-vm-tools.service
NEEDRESTART-SVC: open-vm-tools.service
NEEDRESTART-SVC: jarvis.service
NEEDRESTART-SVC: cron.service
"""

# ── 1. Trockenlauf ───────────────────────────────────────────────────────────
print("[1] Trockenlauf lesen")
plan = P.plan_lesen(SIM)
namen = [p["name"] for p in plan["pakete"]]
pruefe(namen == ["base-files", "libssl3t64", "libext2fs2t64", "google-chrome-stable"],
       "alle Inst-Zeilen gelesen, auch die mit Trigger-Zusatz (%s)" % namen)
ssl = next((p for p in plan["pakete"] if p["name"] == "libssl3t64"), {})
pruefe(ssl.get("von") == "3.5.7-1~deb13u3" and ssl.get("nach") == "3.5.9-1~deb13u1",
       "alte und neue Fassung gelesen")
pruefe(ssl.get("sicherheit") is True, "Sicherheitsquelle erkannt")
pruefe(next((p for p in plan["pakete"] if p["name"] == "base-files"), {}).get("sicherheit") is False,
       "Punktausgabe ist KEINE Sicherheitsquelle")
pruefe(next((p for p in plan["pakete"] if p["name"] == "google-chrome-stable"), {}).get("quelle") == "Google:1.0/stable",
       "Fremdquelle wird benannt")
pruefe(plan["zurueckgehalten"] == ["linux-image-amd64", "phasedpkg"], "zurueckgehaltene Pakete getrennt")
pruefe(plan["entfernt"] == [] and P.plan_lesen(SIM_REMV)["entfernt"] == ["libfoo1"], "Entfernungen erkannt")

# ── 2. needrestart ───────────────────────────────────────────────────────────
print("[2] needrestart lesen")
nr = P.needrestart_lesen(NR)
pruefe(nr["kernel_neustart"] is True and nr["kernel_neu"] == "6.12.118+deb13-amd64", "neuer Kernel erkannt")
pruefe("open-vm-tools" not in nr["dienste"] and nr["dienste"].count("open-vm-tools.service") == 1,
       "nur echte .service-Namen, keine Doppelten")
pruefe(not P.needrestart_lesen("NEEDRESTART-KSTA: 1\n")["kernel_neustart"], "aktueller Kernel: kein Neustart")

# ── 3. Sperrliste ────────────────────────────────────────────────────────────
print("[3] Neustart-Sperrliste")
for d in ("dbus.service", "systemd-logind.service", "lightdm.service", "getty@tty1.service",
          "user@1000.service", "apt-daily-upgrade.service", "unattended-upgrades.service",
          "dailyaidecheck.service"):
    pruefe(not P.neustartbar(d)[0], "nie neu starten: %s" % d)
for d in ("cron.service", "open-vm-tools.service", "jarvis.service", "accounts-daemon.service"):
    pruefe(P.neustartbar(d)[0], "darf neu starten: %s" % d)
pruefe(not P.neustartbar("cron.service; reboot")[0], "kein Dienstname mit Shell-Zeichen")
pruefe(not P.neustartbar("../x.service")[0], "kein Dienstname mit Pfadzeichen")

# ── 4. einspielen ────────────────────────────────────────────────────────────
print("[4] einspielen")
aufrufe = []
LAGE = {"sim": SIM, "versionen_nach": True}


def run_attrappe(cmd, timeout=120, env=None):
    aufrufe.append((list(cmd), dict(env or {})))
    if cmd[:2] == [P.APT_GET, "-s"]:
        return subprocess.CompletedProcess(cmd, 0, LAGE["sim"], "")
    if cmd[0] == "dpkg-query":
        neu = LAGE["versionen_nach"] and any(c[0] == P.APT_GET and "upgrade" in c and "-s" not in c for c, _ in aufrufe)
        z = "".join("%s\t%s\n" % (p["name"], p["nach"] if neu else p["von"]) for p in P.plan_lesen(LAGE["sim"])["pakete"])
        return subprocess.CompletedProcess(cmd, 0, z, "")
    if cmd[0] == P.NEEDRESTART:
        return subprocess.CompletedProcess(cmd, 0, NR, "")
    if cmd[:2] == ["systemctl", "show"]:
        return subprocess.CompletedProcess(cmd, 0, LAGE.get("typ", "simple") + "\n", "")
    return subprocess.CompletedProcess(cmd, 0, "", "")


P._run = run_attrappe
P.Path = lambda p: types.SimpleNamespace(exists=lambda: p == P.NEEDRESTART)


def upgrade_aufrufe():
    return [(c, e) for c, e in aufrufe if c[0] == P.APT_GET and "upgrade" in c and "-s" not in c]


aufrufe.clear()
LAGE["sim"] = SIM_REMV
r = P.einspielen()
pruefe(not r["ok"] and not upgrade_aufrufe(), "Entfernung geplant: KEIN upgrade, Ergebnis nicht ok")
aufrufe.clear()
LAGE["sim"] = "0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.\n"
r = P.einspielen()
pruefe(r["ok"] and not upgrade_aufrufe() and not _aide_aufrufe, "nichts offen: kein upgrade, keine AIDE-Pruefung")
aufrufe.clear()
LAGE["sim"] = SIM
r = P.einspielen()
up = upgrade_aufrufe()
pruefe(len(up) == 1, "offene Pakete: genau EIN upgrade")
if up:
    cmd, env = up[0]
    pruefe("--no-remove" in cmd, "upgrade mit --no-remove")
    pruefe("Dpkg::Options::=--force-confold" in cmd, "lokale Konfiguration bleibt (--force-confold)")
    pruefe(env.get("NEEDRESTART_MODE") == "l", "needrestart startet nichts selbst neu (NEEDRESTART_MODE=l)")
    pruefe(env.get("DEBIAN_FRONTEND") == "noninteractive", "keine Rueckfragen (noninteractive)")
    pruefe("autoremove" not in cmd and "dist-upgrade" not in cmd and "full-upgrade" not in cmd,
           "kein autoremove und kein full-upgrade")
pruefe(len(r.get("eingespielt") or []) == 4, "eingespielte Pakete aus dem Versionsvergleich (%d)" % len(r.get("eingespielt") or []))
pruefe(len(_aide_aufrufe) == 1, "danach AIDE-Pruefung angestossen")
_aide_aufrufe.clear()
aufrufe.clear()
LAGE["versionen_nach"] = False
r = P.einspielen()
pruefe(not r.get("eingespielt") and not _aide_aufrufe, "nichts wirklich eingespielt: keine AIDE-Pruefung")
LAGE["versionen_nach"] = True

# ── 4b. Hinweise der Pakete ──────────────────────────────────────────────────
print("[4b] Hinweise (apt-listchanges)")
OHNE = ("Reading package lists...\napt-listchanges: Reading changelogs...\nPreconfiguring packages ...\n"
        "(Reading database ... 5%\nUnpacking base-files ...\n")
MIT = ("apt-listchanges: Reading changelogs...\napt-listchanges: News\n---------------------\n\n"
       "openssl (3.5.9-1~deb13u1) trixie; urgency=medium\n\n  * Wichtiger Hinweis.\n\n"
       "(Reading database ... 5%\nUnpacking openssl ...\n")
pruefe(P._news(OHNE) == "", "nur die Statuszeile: KEINE Hinweise (kein dpkg-Fortschritt als Hinweis)")
h = P._news(MIT)
pruefe("Wichtiger Hinweis" in h and "Reading database" not in h and "Unpacking" not in h,
       "echte NEWS: genau dieser Abschnitt, ohne die dpkg-Ausgabe danach")

# ── 5. dienst_neustart ───────────────────────────────────────────────────────
print("[5] dienst_neustart")


def neustarts():
    return [c for c, _ in aufrufe if c[:2] == ["systemctl", "restart"] or c[0] == "systemd-run"]


aufrufe.clear()
r = P.dienst_neustart("dbus.service")
pruefe(not r["ok"] and not neustarts(), "dbus: abgelehnt, nichts gestartet")
aufrufe.clear()
r = P.dienst_neustart("ssh.service")
pruefe(not r["ok"] and not neustarts(), "nicht von needrestart genannt: abgelehnt")
aufrufe.clear()
r = P.dienst_neustart("cron.service")
pruefe(r["ok"] and neustarts() == [["systemctl", "restart", "cron.service"]], "genannter Dienst: neu gestartet")
aufrufe.clear()
LAGE["typ"] = "oneshot"
r = P.dienst_neustart("cron.service")
pruefe(not r["ok"] and not neustarts(), "Oneshot: abgelehnt (ein Neustart wuerde ihn ausloesen)")
LAGE["typ"] = "simple"
aufrufe.clear()
r = P.dienst_neustart("jarvis.service")
ns = neustarts()
pruefe(r.get("verzoegert") and ns and ns[0][0] == "systemd-run" and any(a.startswith("--on-active=") for a in ns[0]),
       "die Anwendung selbst: verzoegert ueber systemd-run (%s)" % ns)

print("ERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
