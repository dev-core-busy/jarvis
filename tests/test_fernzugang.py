#!/usr/bin/env python3
"""Waechter: Fernzugang (SSH) aus der Oberflaeche – BSI M7 per Klick.

Ausgefuehrt wird der ECHTE Weg: ``backend/broker/meta.py`` -> ``fernzugang.py``
-> ``ssh_haertung.sh`` / ``firewall.sh``, alles in einem Sandkasten:

  * erfundenes System (passwd/group/Homes mit ECHTEN ed25519-Schluesseln, damit
    ``ssh-keygen -lf`` echte Fingerabdruecke liefert), broker.conf, sshd_config;
  * Attrappen NUR fuer das, was root bzw. das echte System braucht: ``nft``,
    ``systemctl``, ``systemd-run``, ``sshd`` (protokollieren ihre Aufrufe);
  * ein eigener Freigabe-Schluessel (``freigabe.einrichten`` im Sandkasten),
    damit Codes WIRKLICH vom Broker-Code geprueft werden.

Geprueft: Status (Konten, Fingerabdruecke, wer nach der Umstellung herein
kaeme), Test -> Bestaetigen/Verwerfen/Aus fuer die Haertung, Netze mit Test,
Rueckfall auf den URSPRUENGLICHEN Wert, Bestaetigen (persistiert), Abweisung
boeser Eingaben, Aussperr-Schutz, eigene Sitzung ausserhalb der Netze,
Freigabe-Code (fehlt/falsch/gueltig, verwerfen ohne Code), Audit, die drei
API-Endpunkte samt Admin-Pflicht (AST) und dass der Broker die Meta-Ops nicht
im Event-Loop ausfuehrt.

``backend.config`` wird nicht importiert. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def check(name: str, bed: bool, detail: str = "") -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail) if detail else ""))


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


def abschnitt(t: str) -> None:
    print("\n── " + t)


for werkzeug in ("bash", "ssh-keygen", "python3"):
    if not shutil.which(werkzeug):
        abbruch(f"{werkzeug} fehlt")

# ════════════════════════════════════════════════════════════════════════════
# Sandkasten
# ════════════════════════════════════════════════════════════════════════════
SK = Path(tempfile.mkdtemp(prefix="jv_fernzugang_"))
BIN = SK / "bin"
LOG = SK / "aufrufe.log"
TIMER = SK / "timer"
for d in (BIN, TIMER, SK / "etc", SK / "units", SK / "dropin", SK / "sicherung"):
    d.mkdir(parents=True)

# Attrappen – jede schreibt ihren Aufruf ins Protokoll
(BIN / "nft").write_text(f"""#!/bin/sh
eingabe=""
[ "$1" = "-f" ] && eingabe="$(cat)"
printf 'nft %s\\n%s\\n--ende--\\n' "$*" "$eingabe" >> "{LOG}"
if [ "$1" = "list" ]; then
    [ -f "{SK}/fw_eingerichtet" ] || exit 1
    echo "table inet jarvis_fw {{ }}"
fi
exit 0
""")
(BIN / "systemctl").write_text(f"""#!/bin/sh
printf 'systemctl %s\\n' "$*" >> "{LOG}"
case "$1" in
  is-active) for a in "$@"; do case "$a" in *.timer) [ -f "{TIMER}/$a" ] && exit 0 || exit 3;; esac; done; exit 3;;
  stop) for a in "$@"; do case "$a" in *.timer) rm -f "{TIMER}/$a";; esac; done;;
esac
exit 0
""")
(BIN / "systemd-run").write_text(f"""#!/bin/sh
printf 'systemd-run %s\\n' "$*" >> "{LOG}"
for a in "$@"; do case "$a" in --unit=*) n="${{a#--unit=}}"; printf '%s\\n' "$*" > "{TIMER}/$n.timer";; esac; done
exit 0
""")
(BIN / "sshd").write_text(f"""#!/bin/sh
cat "{SK}/sshd_T" 2>/dev/null
""")
# ip -o addr show / journalctl: Form wie auf DEV gemessen (Debian 13, 2026-10-06)
(BIN / "ip").write_text(f"""#!/bin/sh
cat "{SK}/ip_addr" 2>/dev/null
""")
(BIN / "journalctl").write_text(f"""#!/bin/sh
printf 'journalctl %s\\n' "$*" >> "{LOG}"
cat "{SK}/journal" 2>/dev/null
""")
for f in BIN.iterdir():
    f.chmod(0o755)
(SK / "sshd_T").write_text("port 22\npasswordauthentication yes\nkbdinteractiveauthentication no\n"
                           "permitrootlogin without-password\npubkeyauthentication yes\n")

PFAD = f"{BIN}:/usr/bin:/bin"
r = subprocess.run(["bash", "-c", "command -v iptables"], env={"PATH": PFAD},
                   capture_output=True, text=True)
if r.returncode == 0:
    abbruch(f"iptables liegt im Suchpfad ({r.stdout.strip()}) – der nft-Weg waere nicht messbar")

# Konten: root (Schluessel), admin (sudo, Schluessel), anna (sudo, ohne), dienst (nologin)
nutzer = {"root": 0, "admin": 1000, "anna": 1001, "dienst": 999}
passwd = []
FPS: dict[str, str] = {}
for n, uid in nutzer.items():
    home = SK / "home" / n
    (home / ".ssh").mkdir(parents=True)
    shell = "/usr/sbin/nologin" if n == "dienst" else "/bin/bash"
    passwd.append(f"{n}:x:{uid}:{uid}::{home}:{shell}")
    if n in ("root", "admin", "dienst"):
        schl = SK / f"key_{n}"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"{n}@test",
                        "-f", str(schl)], check=True)
        shutil.copy(f"{schl}.pub", home / ".ssh" / "authorized_keys")
        FPS[n] = subprocess.run(["ssh-keygen", "-lf", f"{schl}.pub"], capture_output=True,
                                text=True).stdout.split()[1]
(SK / "passwd").write_text("\n".join(passwd) + "\n")
(SK / "group").write_text("root:x:0:\nsudo:x:27:admin,anna,dienst\n")
(SK / "sshd_config").write_text(f"Include {SK / 'dropin'}/*.conf\nUsePAM yes\n")
KONF = SK / "etc" / "broker.conf"
KONF.write_text("QUELLE=github\n")

os.environ.update({
    "PATH": PFAD,
    "JARVIS_BROKER_CONF": str(KONF),
    "JARVIS_FW_RUECKFALL": str(SK / "etc" / "ssh-netze.rueckfall"),
    "JARVIS_SSH_FRIST": str(SK / "frist.json"),
    "JARVIS_SSH_TEST": "1",
    "JARVIS_SSHD_CONFIG": str(SK / "sshd_config"),
    "JARVIS_SSHD_DROPIN_DIR": str(SK / "dropin"),
    "JARVIS_PASSWD": str(SK / "passwd"),
    "JARVIS_GROUP": str(SK / "group"),
    "JARVIS_FW_TEST": "1",
    "JARVIS_FW_ETC": str(SK / "etc"),
    "JARVIS_UNIT_DIR": str(SK / "units"),
    "JARVIS_FW_SICHERUNG": str(SK / "sicherung"),
    "JARVIS_BROKER_FREIGABE_KEY": str(SK / "etc" / "freigabe.key"),
    "JARVIS_BROKER_FREIGABE_STATE": str(SK / "etc" / "freigabe.state"),
    "JARVIS_BROKER_POLICY": str(SK / "etc" / "policy.json"),
    "JARVIS_BROKER_AUDIT": str(SK / "audit.jsonl"),
})
os.environ.pop("SSH_CONNECTION", None)
os.environ.pop("SUDO_USER", None)

fz = importlib.import_module("backend.broker.fernzugang")
meta = importlib.import_module("backend.broker.meta")
freigabe = importlib.import_module("backend.broker.freigabe")
DROPIN = SK / "dropin" / "05-jarvis-haertung.conf"
RUECK = SK / "etc" / "ssh-netze.rueckfall"

# Sandkasten-Waechter: kein Pfad darf ins echte System zeigen
for name, p in (("BROKER_CONF", fz.BROKER_CONF), ("RUECKFALL", fz.RUECKFALL_NETZE),
                ("FRIST", fz.FRIST_DATEI), ("FREIGABE", freigabe.SCHLUESSEL)):
    if not str(p).startswith(str(SK)):
        abbruch(f"{name} zeigt aus dem Sandkasten: {p}")


def konf(schluessel: str) -> str | None:
    return fz._konf().get(schluessel)


def log() -> str:
    return LOG.read_text() if LOG.exists() else ""


def log_leeren() -> None:
    LOG.write_text("")


def nft_regeln() -> str:
    """Der LETZTE per nft -f gesetzte Regelsatz."""
    teile = re.findall(r"nft -f -\n(.*?)\n--ende--", log(), re.S)
    return teile[-1] if teile else ""


def allgemein(regeln: str) -> set[str]:
    m = re.search(r"^\s*tcp dport \{([^}]*)\} ct state new accept\s*$", regeln, re.M)
    return {p.strip() for p in m.group(1).split(",")} if m else set()


# ════════════════════════════════════════════════════════════════════════════
abschnitt("1. Status")
st = fz.status()
if not st.get("ok") or not st.get("konten"):
    print(json.dumps(st, indent=1)[:2000])
    abbruch("status() liefert keine Konten (Messaufbau)")
kn = {k["name"]: k for k in st["konten"]}
check("Konten: root, admin, anna – nicht das nologin-Konto",
      set(kn) == {"root", "admin", "anna"}, set(kn))
check("Fingerabdruck admin = ssh-keygen -lf des hinterlegten Schluessels",
      [s["fingerabdruck"] for s in kn.get("admin", {}).get("schluessel", [])] == [FPS["admin"]],
      kn.get("admin"))
check("Typ/Kommentar mitgeliefert",
      (kn.get("admin", {}).get("schluessel") or [{}])[0].get("typ") == "ED25519"
      and (kn["admin"]["schluessel"][0].get("kommentar") == "admin@test"), kn.get("admin"))
check("anna ohne Schluessel zaehlt nicht", kn.get("anna", {}).get("zaehlt") is False)
check("admin mit Schluessel zaehlt", kn.get("admin", {}).get("zaehlt") is True)
check("root zaehlt bei SSH_ROOT=nein NICHT", kn.get("root", {}).get("zaehlt") is False)
check("zugang_moeglich je Modus", st.get("zugang_moeglich") == {"nein": True, "schluessel": True},
      st.get("zugang_moeglich"))
check("sshd -T ausgewertet", st.get("sshd", {}).get("passwordauthentication") == "yes", st.get("sshd"))
check("Paketfilter nicht eingerichtet erkannt", st.get("firewall_eingerichtet") is False)
check("kein Test laeuft", not st["test"]["haertung"]["laeuft"] and not st["test"]["netze"]["laeuft"])
KONF.write_text("SSH_ROOT=schluessel\n")
st2 = fz.status()
check("root zaehlt bei SSH_ROOT=schluessel",
      next(k for k in st2["konten"] if k["name"] == "root")["zaehlt"] is True)
KONF.write_text("QUELLE=github\n")

# ════════════════════════════════════════════════════════════════════════════
abschnitt("2. Haertung: test -> bestaetigen / verwerfen / aus")
r = fz.haertung("test", "falsch")
check("ungueltiger root_modus abgewiesen, nichts geschrieben",
      not r["ok"] and not DROPIN.exists() and konf("SSH_ROOT") is None, r)
r = fz.haertung("test", "nein")
check("test: ok", r["ok"], r)
check("test: Drop-in mit PasswordAuthentication no",
      DROPIN.is_file() and "PasswordAuthentication no" in DROPIN.read_text())
check("test: SSH_ROOT=nein in broker.conf", konf("SSH_ROOT") == "nein")
def frist(art: str) -> float:
    """Gemerktes Fristende oder 0 – wirft nie (eine fehlende Datei ist ein FAIL, kein Absturz)."""
    try:
        return float(json.loads((SK / "frist.json").read_text()).get(art) or 0)
    except Exception:  # noqa: BLE001
        return 0.0


check("test: Frist gemerkt (~300 s)", abs(frist("haertung") - (time.time() + 300)) < 30,
      frist("haertung"))
check("test: SSH_HAERTUNG noch NICHT an (erst nach Bestaetigung)", konf("SSH_HAERTUNG") is None)
r = fz.haertung("bestaetigen")
check("bestaetigen ohne laufenden Timer abgewiesen", not r["ok"] and konf("SSH_HAERTUNG") is None, r)
(TIMER / "ssh-rollback.timer").write_text("x")
st = fz.status()
check("Status meldet laufenden Test mit Restfrist",
      st["test"]["haertung"]["laeuft"] and 250 < (st["test"]["haertung"]["rest_s"] or 0) <= 300,
      st["test"]["haertung"])
r = fz.haertung("bestaetigen")
check("bestaetigen im Test: ok, SSH_HAERTUNG=an", r["ok"] and konf("SSH_HAERTUNG") == "an", r)
check("…Timer gestoppt", not (TIMER / "ssh-rollback.timer").exists())
(TIMER / "ssh-rollback.timer").write_text("x")   # ein verirrter Timer nach der Bestaetigung
r = fz.haertung("verwerfen")
check("verwerfen (ohne Code) nimmt eine BESTAETIGTE Haertung nicht zurueck",
      not r["ok"] and DROPIN.is_file(), r)
(TIMER / "ssh-rollback.timer").unlink()
r = fz.haertung("test", "schluessel")
check("erneuter Test bei aktiver Haertung abgewiesen (Rueckfall wuerde sie entfernen)",
      not r["ok"] and r.get("rc") == 6 and DROPIN.is_file(), r)
# Code-Review 2026-10-07: der abgewiesene Test liess SSH_ROOT=schluessel stehen,
# und der naechste Broker-Start schrieb es per --erneuern in die sshd-Konfiguration.
check("⚠ …und SSH_ROOT bleibt beim bestaetigten Wert (nein), nicht 'schluessel'",
      konf("SSH_ROOT") == "nein", konf("SSH_ROOT"))
r = fz.haertung("verwerfen")
check("verwerfen ohne Test abgewiesen, Drop-in bleibt", not r["ok"] and DROPIN.is_file(), r)
r = fz.haertung("aus")
check("aus: Drop-in weg, SSH_HAERTUNG=aus", r["ok"] and not DROPIN.exists()
      and konf("SSH_HAERTUNG") == "aus", r)
KONF.write_text("QUELLE=github\n")
fz.haertung("test", "nein")
(TIMER / "ssh-rollback.timer").write_text("x")
r = fz.haertung("verwerfen")
check("verwerfen im Test: Drop-in weg", r["ok"] and not DROPIN.exists(), r)

abschnitt("3. Aussperr-Schutz kommt aus dem Skript")
KONF.write_text("QUELLE=github\n")
gespart = (SK / "home" / "admin" / ".ssh" / "authorized_keys").read_text()
(SK / "home" / "admin" / ".ssh" / "authorized_keys").unlink()
r = fz.haertung("test", "nein")
check("niemand kaeme herein -> abgewiesen (rc 3), Meldung nennt den Grund",
      not r["ok"] and r.get("rc") == 3 and "ABBRUCH" in r.get("meldung", "")
      and not DROPIN.exists(), r)
check("⚠ …und SSH_ROOT steht danach NICHT in broker.conf (war vorher nicht da)",
      konf("SSH_ROOT") is None and "QUELLE=github" in KONF.read_text(), KONF.read_text())
r = fz.haertung("test", "schluessel")
check("…mit root per Schluessel geht es (root hat einen)", r["ok"], r)
fz.haertung("aus")
(SK / "home" / "admin" / ".ssh" / "authorized_keys").write_text(gespart)
KONF.write_text("QUELLE=github\n")

# ════════════════════════════════════════════════════════════════════════════
abschnitt("4. Netze")
log_leeren()
r = fz.netze("test", "192.0.2.0/24; touch /tmp/x")
check("Steuerzeichen abgewiesen, Skript nicht aufgerufen",
      not r["ok"] and log() == "" and konf("SSH_NETZE") is None, r)
r = fz.netze("test", "192.0.2.0/24")
check("Paketfilter nicht eingerichtet -> abgewiesen (rc 7)",
      not r["ok"] and r.get("rc") == 7 and konf("SSH_NETZE") is None and not RUECK.exists(), r)
(SK / "fw_eingerichtet").write_text("1")
check("…danach als eingerichtet erkannt", fz.status()["firewall_eingerichtet"] is True)
r = fz.netze("test", "999.1.1.1/8")
check("ungueltiges Netz abgewiesen, nichts geaendert",
      not r["ok"] and konf("SSH_NETZE") is None and not RUECK.exists(), r)

KONF.write_text('QUELLE=github\nSSH_NETZE="198.51.100.0/24"\n')
log_leeren()
r = fz.netze("test", "192.0.2.0/24 203.0.113.7")
check("test: ok", r["ok"], r)
check("test: Wert normiert in broker.conf", konf("SSH_NETZE") == "192.0.2.0/24 203.0.113.7/32",
      konf("SSH_NETZE"))
check("test: Rueckfall-Datei haelt den ALTEN Wert",
      RUECK.is_file() and RUECK.read_text().strip() == "198.51.100.0/24")
tm = (TIMER / "fw-ssh-rueckfall.timer")
check("test: Rueckfall-Timer mit --rueckfall gesetzt",
      tm.is_file() and "--rueckfall" in tm.read_text() and "--on-active=300" in tm.read_text(),
      tm.read_text() if tm.exists() else "")
regeln = nft_regeln()
check("test: Regeln gesetzt – 22 nicht mehr allgemein",
      "22" not in allgemein(regeln) and "443" in allgemein(regeln), allgemein(regeln))
check("test: 22 nur aus den neuen Netzen",
      re.search(r"ip saddr \{ 192\.0\.2\.0/24, 203\.0\.113\.7/32 \} tcp dport 22", regeln) is not None,
      regeln)
check("test: NICHT persistiert", not (SK / "etc" / "firewall.nft").exists())
st = fz.status()
check("Status: Netze-Test laeuft, Restfrist", st["test"]["netze"]["laeuft"]
      and (st["test"]["netze"]["rest_s"] or 0) > 250, st["test"]["netze"])
r = fz.netze("test", "192.0.2.128/25")
check("zweiter Test: Rueckfall bleibt der URSPRUENGLICHE Wert",
      r["ok"] and RUECK.read_text().strip() == "198.51.100.0/24", RUECK.read_text())
# Der Timer laeuft ab: GENAU den Befehl ausfuehren, den systemd-run bekommen hat
befehl = tm.read_text().split()
idx = befehl.index("--rueckfall") if "--rueckfall" in befehl else -1
log_leeren()
if idx > 0:
    subprocess.run(befehl[idx - 2:idx + 1], capture_output=True, text=True, timeout=60)
check("Ablauf der Frist: alter Wert zurueck", konf("SSH_NETZE") == "198.51.100.0/24",
      konf("SSH_NETZE"))
check("…Rueckfall-Datei weg", not RUECK.exists())
check("…Regeln wieder mit dem alten Netz",
      "198.51.100.0/24" in nft_regeln() and "192.0.2.128/25" not in nft_regeln(), nft_regeln())

r = fz.netze("test", "192.0.2.0/24")
(TIMER / "fw-ssh-rueckfall.timer").write_text("x")
r = fz.netze("verwerfen")
check("verwerfen: alter Wert zurueck, Datei weg",
      r["ok"] and konf("SSH_NETZE") == "198.51.100.0/24" and not RUECK.exists(), r)
r = fz.netze("verwerfen")
check("verwerfen ohne Test abgewiesen", not r["ok"], r)
r = fz.netze("bestaetigen")
check("bestaetigen ohne Test abgewiesen", not r["ok"], r)

fz.netze("test", "192.0.2.0/24")
r = fz.netze("bestaetigen")
check("bestaetigen: ok, neuer Wert bleibt", r["ok"] and konf("SSH_NETZE") == "192.0.2.0/24", r)
check("…Rueckfall-Datei weg, Timer gestoppt",
      not RUECK.exists() and not (TIMER / "fw-ssh-rueckfall.timer").exists())
check("…persistiert (Regeldatei + Boot-Unit)",
      (SK / "etc" / "firewall.nft").is_file() and (SK / "units" / "jarvis-firewall.service").is_file())

r = fz.netze("test", "")
check("leer = aus allen Netzen: 22 wieder allgemein",
      r["ok"] and konf("SSH_NETZE") == "" and "22" in allgemein(nft_regeln()), (r, allgemein(nft_regeln())))
fz.netze("verwerfen")

os.environ["SSH_CONNECTION"] = "203.0.113.50 50000 192.0.2.254 22"
r = fz.netze("test", "192.0.2.0/24")
check("eigene SSH-Sitzung ausserhalb -> rc 3, alter Wert zurueck, keine Rueckfall-Datei",
      not r["ok"] and r.get("rc") == 3 and konf("SSH_NETZE") == "192.0.2.0/24"
      and not RUECK.exists(), (r, konf("SSH_NETZE")))
os.environ.pop("SSH_CONNECTION")

# ════════════════════════════════════════════════════════════════════════════
abschnitt("5. Freigabe-Code + Audit (meta.py)")
KONF.write_text("QUELLE=github\n")
r = meta.behandeln("broker.ssh_haertung", {"aktion": "test", "root_modus": "nein", "by": "admin"})
check("ohne eingerichteten Code: abgewiesen, nichts geschrieben",
      r.get("ok") is False and r.get("grund") == "nicht_eingerichtet" and not DROPIN.exists(), r)
freigabe.einrichten()
schluessel = freigabe._lade()
if schluessel is None:
    abbruch("Freigabe-Schluessel im Sandkasten nicht ladbar (Messaufbau)")
r = meta.behandeln("broker.ssh_haertung", {"aktion": "test", "root_modus": "nein", "by": "admin",
                                            "nachweis": "000000"})
check("falscher Code: abgewiesen", r.get("ok") is False and r.get("grund") in
      ("nachweis_falsch", "nachweis_verbraucht") and not DROPIN.exists(), r)
r = meta.behandeln("broker.ssh_haertung", {"aktion": "test", "root_modus": "nein", "by": "admin"})
check("fehlender Code: abgewiesen", r.get("grund") == "nachweis_fehlt" and not DROPIN.exists(), r)
code = freigabe._code(schluessel, int(time.time() // freigabe.SCHRITT_S))
r = meta.behandeln("broker.ssh_haertung", {"aktion": "test", "root_modus": "nein", "by": "admin",
                                            "nachweis": code})
check("gueltiger Code: Test laeuft", r.get("ok") is True and DROPIN.is_file(), r)
r = meta.behandeln("broker.ssh_haertung", {"aktion": "aus", "by": "admin", "nachweis": code})
check("derselbe Code ein zweites Mal: abgewiesen",
      r.get("grund") == "nachweis_verbraucht" and DROPIN.is_file(), r)
(TIMER / "ssh-rollback.timer").write_text("x")
r = meta.behandeln("broker.ssh_haertung", {"aktion": "verwerfen", "by": "admin"})
check("verwerfen ohne Code geht durch (stellt nur den alten Stand her)",
      r.get("ok") is True and not DROPIN.exists(), r)
r = meta.behandeln("broker.ssh_netze", {"aktion": "test", "netze": "192.0.2.0/24", "by": "admin"})
check("Netze ohne Code: abgewiesen", r.get("grund") == "nachweis_fehlt" and not RUECK.exists(), r)
audit = [json.loads(z) for z in (SK / "audit.jsonl").read_text().splitlines() if z.strip()]
check("Audit: abgewiesene Versuche stehen drin",
      any(a.get("op") == "broker.ssh_haertung" and a.get("decision") == "abgewiesen" for a in audit))
check("Audit: ausgefuehrter Test mit root_modus",
      any(a.get("op") == "broker.ssh_haertung" and a.get("decision") == "executed"
          and "root_modus=nein" in (a.get("info") or "") for a in audit))
st = meta.behandeln("broker.ssh_status", {})
check("broker.ssh_status ohne Code", st.get("ok") is True and "konten" in st)

# ════════════════════════════════════════════════════════════════════════════
abschnitt("6. Vorschlaege fuer den Netze-Helfer")
(SK / "ip_addr").write_text(
    "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever\n"
    "1: lo    inet6 ::1/128 scope host noprefixroute \\       valid_lft forever\n"
    "2: ens192    inet 198.51.100.30/22 brd 198.51.103.255 scope global ens192\\       valid_lft forever\n"
    "2: ens192    inet6 2001:db8:5::30/64 scope global \\       valid_lft forever\n"
    "2: ens192    inet6 fe80::250:56ff:fe94:e3a5/64 scope link \\       valid_lft forever\n"
    "3: tailscale0    inet 100.64.12.34/32 scope global tailscale0\\       valid_lft forever\n"
    "4: wg0    inet 10.9.0.5/32 scope global wg0\\       valid_lft forever\n")
zeilen = []
for i in range(20):
    zeilen.append(f"2026-09-{10 + i:02d}T10:00:00+02:00 host sshd-session[1]: Accepted publickey for root "
                  f"from 192.0.2.{i + 1} port 5000{i} ssh2: RSA SHA256:x")
zeilen += [
    "2026-10-06T09:00:00+02:00 host sshd-session[2]: Accepted publickey for root from 203.0.113.7 port 1 ssh2: ED25519 SHA256:y",
    "2026-10-05T09:00:00+02:00 host sshd-session[3]: Accepted password for kollege from 203.0.113.7 port 2 ssh2",
    "2026-10-06T08:00:00+02:00 host sshd-session[4]: Failed password for root from 198.51.100.99 port 3 ssh2",
    "2026-10-06T07:00:00+02:00 host sshd-session[5]: Accepted publickey for root from 2001:db8:5::99 port 4 ssh2: RSA SHA256:z",
    "2026-10-06T06:00:00+02:00 host sshd-session[6]: Accepted publickey for root from kein-ip port 5 ssh2: RSA SHA256:z",
]
(SK / "journal").write_text("\n".join(zeilen) + "\n")
vs = fz._vorschlaege()
check("lokale Netze: IPv4 + IPv6 der Schnittstelle, Host-Bits genullt",
      vs["lokal"] == [{"netz": "198.51.100.0/22", "schnittstelle": "ens192"},
                      {"netz": "2001:db8:5::/64", "schnittstelle": "ens192"}], vs["lokal"])
check("Einzeladressen (/32, z. B. VPN-Tunnel) sind kein Netz-Vorschlag",
      not any(l["schnittstelle"] == "wg0" for l in vs["lokal"]), vs["lokal"])
check("Tailscale erkannt", vs["tailscale"] is True)
an = {a["ip"]: a for a in vs["anmeldungen"]}
check("hoechstens 15 Adressen", len(vs["anmeldungen"]) == 15, len(vs["anmeldungen"]))
check("juengste zuerst", vs["anmeldungen"][0]["ip"] == "203.0.113.7", vs["anmeldungen"][0])
check("je Adresse gezaehlt, Konten gesammelt, juengster Zeitpunkt",
      an.get("203.0.113.7", {}).get("anzahl") == 2
      and an["203.0.113.7"]["konten"] == ["root", "kollege"]
      and an["203.0.113.7"]["zuletzt"].startswith("2026-10-06T09"), an.get("203.0.113.7"))
check("IPv6-Quelle mitgenommen", "2001:db8:5::99" in an)
check("Fehlversuche zaehlen NICHT", "198.51.100.99" not in an)
check("keine Nicht-Adresse", "kein-ip" not in an)
check("die aeltesten fallen bei mehr als 15 heraus",
      "192.0.2.1" not in an and "192.0.2.20" in an)
check("Journal: nur die SSH-Units, 30 Tage", re.search(r"journalctl .*-u ssh -u sshd --since -30d", log()) is not None)
check("Vorschlaege stehen im Status", fz.status().get("vorschlaege", {}).get("tailscale") is True)
(SK / "journal").write_text("")
(SK / "ip_addr").write_text("")
leer = fz._vorschlaege()
check("ohne Daten: leere Listen, kein Fehler",
      leer == {"lokal": [], "tailscale": False, "anmeldungen": []}, leer)

# ════════════════════════════════════════════════════════════════════════════
abschnitt("6b. Schluessel hinterlegen / entfernen (seit 2026-10-20)")
KONF.write_text("QUELLE=github\n")
for t in TIMER.iterdir():
    t.unlink()


def neuer_schluessel(name: str, art: str = "ed25519", bits: str = "") -> tuple[str, str, str]:
    """(oeffentliche Zeile, Fingerabdruck laut ssh-keygen, privater Text)."""
    f = SK / f"neu_{name}"
    befehl = ["ssh-keygen", "-q", "-t", art, "-N", "", "-C", f"{name}@rechner", "-f", str(f)]
    if bits:
        befehl[4:4] = ["-b", bits]
    subprocess.run(befehl, check=True)
    fp = subprocess.run(["ssh-keygen", "-lf", f"{f}.pub"], capture_output=True, text=True).stdout.split()[1]
    return Path(f"{f}.pub").read_text().strip(), fp, Path(f).read_text()


def ak(n: str, datei: str = "authorized_keys") -> Path:
    return SK / "home" / n / ".ssh" / datei


def lies(pf: Path) -> str:
    return pf.read_text() if pf.exists() and not pf.is_symlink() else ""


PUB, FP_NEU, PRIV = neuer_schluessel("anna")
shutil.rmtree(SK / "home" / "anna" / ".ssh")
r = fz.schluessel("hinzufuegen", "anna", PUB)
check("hinzufuegen: ok, als neu gemeldet, Fingerabdruck = ssh-keygen",
      r.get("ok") is True and r.get("neu") is True and r.get("fingerabdruck") == FP_NEU, r)
check(".ssh fehlte: vom Broker mit 0700 angelegt",
      (SK / "home" / "anna" / ".ssh").is_dir()
      and ((SK / "home" / "anna" / ".ssh").stat().st_mode & 0o777) == 0o700,
      oct((SK / "home" / "anna" / ".ssh").stat().st_mode) if (SK / "home" / "anna" / ".ssh").exists() else "fehlt")
check("authorized_keys mit 0600", ak("anna").is_file() and (ak("anna").stat().st_mode & 0o777) == 0o600)
check("Inhalt: genau die eine Zeile, Typ + Daten + Kommentar", lies(ak("anna")) == PUB + "\n", lies(ak("anna")))
kn = {k["name"]: k for k in fz.status()["konten"]}
check("Status: anna mit dem neuen Fingerabdruck, zaehlt jetzt",
      [x["fingerabdruck"] for x in kn["anna"]["schluessel"]] == [FP_NEU] and kn["anna"]["zaehlt"] is True, kn["anna"])
r = fz.schluessel("hinzufuegen", "anna", PUB)
check("derselbe Schluessel nochmal: ok, nicht neu, keine zweite Zeile",
      r.get("ok") is True and r.get("neu") is False and lies(ak("anna")).count("\n") == 1, r)

# Abweisungen – jede ohne Aenderung an der Datei
vorher_anna = lies(ak("anna"))
typ, daten = PUB.split()[:2]
PUB_RSA_KLEIN, _, _ = neuer_schluessel("klein", "rsa", "2048")
PUB_RSA_OK, FP_RSA, _ = neuer_schluessel("gross", "rsa", "3072")
boese = {
    "privater Schluessel": (PRIV, "PRIVATER"),
    "Option command= davor": (f'command="/bin/sh" {PUB}', "unterstützter"),
    "Option from= davor": (f'from="0.0.0.0/0" {PUB}', "unterstützter"),
    "zwei Zeilen": (PUB + "\n" + PUB_RSA_OK, "genau einen"),
    "unbekannter Typ (ssh-dss)": (f"ssh-dss {daten}", "unterstützter"),
    "Typ passt nicht zu den Daten": (f"ssh-rsa {daten} x", "Typangabe"),
    "kaputtes base64": (f"{typ} {daten[:-5]}!!!!!", "unterstützter"),
    "abgeschnittene Daten": (f"{typ} {daten[:20]}", "ssh-keygen lehnt"),
    "RSA 2048": (PUB_RSA_KLEIN, "zu schwach"),
    "leer": ("   ", "Kein Schlüssel"),
}
for name, (text, erwartet) in boese.items():
    r = fz.schluessel("hinzufuegen", "anna", text)
    check(f"abgewiesen: {name}", r.get("ok") is False and erwartet in r.get("meldung", "")
          and lies(ak("anna")) == vorher_anna, r)
r = fz.schluessel("hinzufuegen", "anna", PUB_RSA_OK)
check("RSA 3072: angenommen", r.get("ok") is True and r.get("fingerabdruck") == FP_RSA, r)
vorher_anna = lies(ak("anna"))
pub_k, fp_k, _ = neuer_schluessel("kommentar")
r = fz.schluessel("hinzufuegen", "anna", f"{pub_k.rsplit(' ', 1)[0]} a\x07b\x1b[31mc")
zeile = lies(ak("anna")).splitlines()[-1] if r.get("ok") else ""
check("Steuerzeichen im Kommentar werden entfernt",
      r.get("ok") is True and zeile.endswith(" ab[31mc") and all(c.isprintable() for c in zeile), repr(zeile))

for konto in ("dienst", "kollege", "../root", ""):
    vorher_d = lies(ak("dienst"))
    r = fz.schluessel("hinzufuegen", konto, PUB)
    check(f"Konto {konto!r}: abgewiesen (nur die angezeigten Administrator-Konten)",
          r.get("ok") is False and "Unbekanntes Konto" in r.get("meldung", "") and lies(ak("dienst")) == vorher_d, r)

# Symlinks: root schreibt nie ueber einen Link hinaus
ZIEL = SK / "fremd.txt"
ZIEL.write_text("unberuehrt\n")
admin_ak = ak("admin")
admin_alt = admin_ak.read_text()
admin_ak.rename(SK / "admin_ak.bak")
admin_ak.symlink_to(ZIEL)
r = fz.schluessel("hinzufuegen", "admin", PUB)
check("authorized_keys ist ein Symlink: abgewiesen, Ziel unberuehrt",
      r.get("ok") is False and ZIEL.read_text() == "unberuehrt\n" and admin_ak.is_symlink(), r)
admin_ak.unlink()
ssh_admin = SK / "home" / "admin" / ".ssh"
ssh_admin.rename(SK / "admin_ssh.bak")
(SK / "fremd_dir").mkdir()
ssh_admin.symlink_to(SK / "fremd_dir")
r = fz.schluessel("hinzufuegen", "admin", PUB)
check(".ssh ist ein Symlink: abgewiesen, nichts im Ziel angelegt",
      r.get("ok") is False and not any((SK / "fremd_dir").iterdir()), r)
ssh_admin.unlink()
(SK / "admin_ssh.bak").rename(ssh_admin)
(SK / "admin_ak.bak").rename(admin_ak)
check("Positivkontrolle: admin wiederhergestellt", admin_ak.read_text() == admin_alt)

# Entfernen
ak("anna").write_text("# Kommentarzeile bleibt\n" + lies(ak("anna")))
r = fz.schluessel("entfernen", "anna", fingerabdruck=FP_NEU)
rest = lies(ak("anna"))
check("entfernen: ok, Zeile weg, Kommentar und andere Schluessel bleiben",
      r.get("ok") is True and PUB.split()[1] not in rest and "# Kommentarzeile bleibt" in rest
      and PUB_RSA_OK.split()[1] in rest, rest)
check("entfernen: Rechte bleiben 0600", (ak("anna").stat().st_mode & 0o777) == 0o600)
for fp_falsch, grund in (("SHA256:quatsch", "Ungültiger"), (FP_NEU, "nicht hinterlegt"),
                         ("SHA256:" + "A" * 43, "nicht hinterlegt")):
    r = fz.schluessel("entfernen", "anna", fingerabdruck=fp_falsch)
    check(f"entfernen {fp_falsch[:16]}…: abgewiesen ({grund})",
          r.get("ok") is False and grund in r.get("meldung", "") and lies(ak("anna")) == rest, r)
r = fz.schluessel("entfernen", "dienst", fingerabdruck=FPS["dienst"])
check("entfernen beim nologin-Konto: abgewiesen", r.get("ok") is False and lies(ak("dienst")), r)
# authorized_keys2 zaehlt mit
root2 = ak("root", "authorized_keys2")
shutil.copy(SK / "key_root.pub", root2)
r = fz.schluessel("entfernen", "root", fingerabdruck=FPS["root"])
check("entfernen raeumt authorized_keys UND authorized_keys2",
      r.get("ok") is True and FPS["root"] not in json.dumps(fz.status()["konten"]), r)

# Aussperr-Schutz: Haertung an, root zaehlt nicht (SSH_ROOT=nein); anna vorher leeren,
# damit admin das einzige zaehlende Konto ist
fz.schluessel("entfernen", "anna", fingerabdruck=FP_RSA)
fz.schluessel("entfernen", "anna", fingerabdruck=fp_k)
KONF.write_text("SSH_HAERTUNG=an\n")
r = fz.schluessel("entfernen", "admin", fingerabdruck=FPS["admin"])
check("Aussperr-Schutz: letzter zaehlender Schluessel bleibt (Haertung an)",
      r.get("ok") is False and "ABBRUCH" in r.get("meldung", "") and admin_ak.read_text() == admin_alt, r)
KONF.write_text("QUELLE=github\n")
(TIMER / "ssh-rollback.timer").write_text("x")
r = fz.schluessel("entfernen", "admin", fingerabdruck=FPS["admin"])
check("Aussperr-Schutz greift auch waehrend eines Tests",
      r.get("ok") is False and "ABBRUCH" in r.get("meldung", ""), r)
(TIMER / "ssh-rollback.timer").unlink()
fz.schluessel("hinzufuegen", "anna", PUB)
KONF.write_text("SSH_HAERTUNG=an\n")
r = fz.schluessel("entfernen", "admin", fingerabdruck=FPS["admin"])
check("…mit einem anderen zaehlenden Konto (anna) geht es",
      r.get("ok") is True and FPS["admin"] not in lies(admin_ak), r)
KONF.write_text("QUELLE=github\n")
admin_ak.write_text(admin_alt)

# Ueber meta.py: immer Code, Audit mit Fingerabdruck
freigabe.ZUSTAND.unlink(missing_ok=True)   # Wiederholschutz/Sperre aus Abschnitt 5 (Sandkasten)
vorher_anna = lies(ak("anna"))
r = meta.behandeln("broker.ssh_schluessel", {"aktion": "entfernen", "konto": "anna",
                                              "fingerabdruck": FP_NEU, "by": "admin"})
check("meta: entfernen ohne Code abgewiesen", r.get("grund") == "nachweis_fehlt"
      and lies(ak("anna")) == vorher_anna, r)
pub_m, fp_m, _ = neuer_schluessel("meta")
r = meta.behandeln("broker.ssh_schluessel", {"aktion": "hinzufuegen", "konto": "anna",
                                              "schluessel": pub_m, "by": "admin", "nachweis": "000000"})
check("meta: hinzufuegen mit falschem Code abgewiesen", r.get("ok") is False and r.get("grund")
      and fp_m not in json.dumps(fz.status()["konten"]), r)
freigabe.ZUSTAND.unlink(missing_ok=True)
code = freigabe._code(schluessel, int(time.time() // freigabe.SCHRITT_S))
r = meta.behandeln("broker.ssh_schluessel", {"aktion": "hinzufuegen", "konto": "anna",
                                              "schluessel": pub_m, "by": "admin", "nachweis": code})
check("meta: mit gueltigem Code hinterlegt", r.get("ok") is True and r.get("fingerabdruck") == fp_m, r)
audit = [json.loads(z) for z in (SK / "audit.jsonl").read_text().splitlines() if z.strip()]
check("Audit: Vorgang mit Konto und Fingerabdruck",
      any(a.get("op") == "broker.ssh_schluessel" and a.get("decision") == "executed"
          and a.get("key") == "broker.ssh_schluessel:hinzufuegen:anna"
          and fp_m in (a.get("info") or "") for a in audit), audit[-1:])
check("Audit: abgewiesener Versuch steht drin",
      any(a.get("op") == "broker.ssh_schluessel" and a.get("decision") == "abgewiesen" for a in audit))

# ════════════════════════════════════════════════════════════════════════════
abschnitt("7. API und Broker-Prozess (AST)")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
routen = {}
for f in baum.body:
    if isinstance(f, ast.AsyncFunctionDef):
        for d in f.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.args and isinstance(d.args[0], ast.Constant)):
                routen[(d.func.attr, d.args[0].value)] = f


def admin_pflicht(f: ast.AsyncFunctionDef) -> bool:
    for v in f.args.defaults + f.args.kw_defaults:
        if (isinstance(v, ast.Call) and getattr(v.func, "id", "") == "Depends"
                and v.args and getattr(v.args[0], "id", "") == "require_local_auth"):
            return True
    return False


for meth, pfad in (("get", "/api/broker/ssh/status"), ("post", "/api/broker/ssh/haertung"),
                   ("post", "/api/broker/ssh/netze"), ("post", "/api/broker/ssh/schluessel")):
    f = routen.get((meth, pfad))
    check(f"{meth.upper()} {pfad} vorhanden und nur fuer Admins", f is not None and admin_pflicht(f))
f = routen.get(("get", "/api/broker/ssh/status"))
gesetzt = f is not None and any(
    isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Subscript)
    and getattr(n.targets[0].slice, "value", None) == "deine_adresse" for n in ast.walk(f))
check("Status-Endpunkt liefert die Adresse der Web-Sitzung (deine_adresse)", gesetzt)
dm = ast.parse((ROOT / "backend" / "broker" / "daemon.py").read_text(encoding="utf-8"))
im_thread = any(
    (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "to_thread"
     and n.args and isinstance(n.args[0], ast.Attribute) and n.args[0].attr == "behandeln")
    # seit 2026-10-18 im eigenen Pool: run_in_executor(_KURZ, functools.partial(meta.behandeln, …))
    or (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "run_in_executor"
        and len(n.args) >= 2 and isinstance(n.args[1], ast.Call)
        and getattr(n.args[1].func, "attr", "") == "partial" and n.args[1].args
        and getattr(n.args[1].args[0], "attr", "") == "behandeln")
    for n in ast.walk(dm))
direkt = any(
    isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "behandeln"
    for n in ast.walk(dm))
check("Broker: Meta-Ops im Thread, nicht im Event-Loop", im_thread and not direkt)

shutil.rmtree(SK, ignore_errors=True)
print("\n" + "=" * 60)
print(f"Ergebnis: {OK} OK, {FAIL} FAIL")
print("=" * 60)
sys.exit(1 if FAIL else 0)
