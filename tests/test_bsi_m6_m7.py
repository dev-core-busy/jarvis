#!/usr/bin/env python3
"""Waechter: BSI M6 + M7 aus dem BSI-Abgleich vom 2026-09-29.

  M7  SSH nur per Schluessel, root nicht, Port 22 begrenzbar.
      - ``deploy/security/ssh_haertung.sh`` wird in einem Sandkasten
        AUSGEFUEHRT (eigene passwd/group/Homes/sshd_config, JARVIS_SSH_TEST=1):
        Inhalt des Drop-ins, Namensreihenfolge vor 50-*.conf, Aussperr-Schutz
        (kein Admin mit Schluessel, Aufrufer ohne Schluessel), --erzwingen,
        SSH_ROOT, fehlendes Include, --erneuern je SSH_HAERTUNG.
      - Grenzen aus Haertung B9 (MaxAuthTries, MaxSessions, Weiterleitungen,
        LogLevel, Banner …) gemessen mit dem ECHTEN ``sshd -T`` gegen die
        Sandkasten-Konfiguration (laeuft ohne root mit eigenem HostKey) – also
        die wirkliche Vorrang-Regel, keine Nachbildung. Dazu: eine frueher
        gelesene Datei, die den Drop-in ueberstimmt, fuehrt zum Abbruch (Exit 7).
      - ``haertung_installieren.sh`` (Broker-Start) erneuert den Drop-in nur
        bei SSH_HAERTUNG=an – ebenfalls ausgefuehrt.
      - ``firewall.sh --zeigen``: mit SSH_NETZE steht 22 NICHT mehr in der
        allgemeinen Freigabe, sondern je Netz; ohne SSH_NETZE bleibt 22 offen
        (sonst sperrte sich jeder Bestandsserver aus); die eigene Sitzung
        ausserhalb der Netze bricht ab.
  M6  Node-LTS, Sicherheits-CI, Dependabot, Abhaengigkeits-Untergrenzen.
      - Alle Node-Quellen (Dockerfile, Bridge-Dockerfile, install.sh) nennen
        dieselbe Linie wie ``node_aktualisieren.sh`` (ZIEL), ZIEL >= MINDEST >= 22;
        ``--pruefen`` gegen eine Node-Attrappe (20 -> Exit 1, 24 -> Exit 0).
      - ``.github/workflows/sicherheit.yml`` als YAML: Ausloeser, Schritte fuer
        Waechter, pip-audit (mit Ausnahmeliste), npm audit, SBOM, bandit,
        gitleaks ueber die ganze Historie.
      - Ausnahmelisten (pip-audit, CI-Waechter, gitleaks) brechen ohne Grund ab.

``backend.config`` wird nicht importiert. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import quell_ausschnitt  # noqa: E402  (linear statt ast.get_source_segment)

ROOT = Path(__file__).resolve().parent.parent
SEC = ROOT / "deploy" / "security"
SSH_SKRIPT = SEC / "ssh_haertung.sh"
SSHD = shutil.which("sshd") or ("/usr/sbin/sshd" if os.access("/usr/sbin/sshd", os.X_OK) else "")
FW_SKRIPT = SEC / "firewall.sh"
HAERTUNG = SEC / "haertung_installieren.sh"
NODE_SKRIPT = SEC / "node_aktualisieren.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "sicherheit.yml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
GOMOD = ROOT / "windows-app-go" / "go.mod"

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


def ohne_kommentare(sh: str) -> str:
    """Shell-Text ohne reine Kommentarzeilen – der Waechter soll keine Begruendung lesen."""
    return "\n".join(z for z in sh.splitlines() if not z.lstrip().startswith("#"))


for p in (SSH_SKRIPT, FW_SKRIPT, HAERTUNG, NODE_SKRIPT, WORKFLOW, DEPENDABOT):
    if not p.is_file():
        abbruch(f"{p.relative_to(ROOT)} fehlt")
if not shutil.which("bash"):
    abbruch("bash fehlt")

# ════════════════════════════════════════════════════════════════════════════
# M7 – Sandkasten fuer ssh_haertung.sh
# ════════════════════════════════════════════════════════════════════════════


class Kasten:
    """Ein erfundenes System: passwd/group, Homes mit authorized_keys,
    sshd_config mit Include, broker.conf. Alles unter einem tmp-Verzeichnis."""

    def __init__(self, keys: dict[str, int], sudo: list[str], conf: str = "",
                 include: bool = True, echt_sshd: bool = False):
        self.d = Path(tempfile.mkdtemp(prefix="jv_m7_"))
        self.dropin_dir = self.d / "sshd_config.d"
        self.dropin_dir.mkdir()
        self.sshd_config = self.d / "sshd_config"
        inc = f"Include {self.dropin_dir}/*.conf\n" if include else ""
        # Wie Debian: Include ganz oben, danach die Vorgaben der Hauptdatei –
        # X11Forwarding yes steht dort und muss vom Drop-in ueberstimmt werden
        haupt = "KbdInteractiveAuthentication no\nUsePAM yes\nX11Forwarding yes\n"
        self.extra: dict[str, str] = {}
        if echt_sshd:
            hk = self.d / "hostkey"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(hk)],
                           check=True, capture_output=True, timeout=30)
            haupt = f"HostKey {hk}\n" + haupt
            self.extra["JARVIS_SSHD_BIN"] = SSHD
        self.sshd_config.write_text(inc + haupt)
        self.broker_conf = self.d / "broker.conf"
        self.broker_conf.write_text("QUELLE=github\n" + conf)
        nutzer = {"root": 0, "admin": 1000, "anna": 1001, "dienst": 999}
        zeilen = []
        for n, uid in nutzer.items():
            home = self.d / "home" / n
            (home / ".ssh").mkdir(parents=True)
            shell = "/usr/sbin/nologin" if n == "dienst" else "/bin/bash"
            zeilen.append(f"{n}:x:{uid}:{uid}::{home}:{shell}")
            if keys.get(n):
                (home / ".ssh" / "authorized_keys").write_text(
                    "# Kommentar zaehlt nicht\n\n"
                    + "".join(f"ssh-ed25519 AAAA{i} {n}@x\n" for i in range(keys[n])))
        self.passwd = self.d / "passwd"
        self.passwd.write_text("\n".join(zeilen) + "\n")
        self.group = self.d / "group"
        self.group.write_text(f"root:x:0:\nsudo:x:27:{','.join(sudo)}\nadmin:x:1000:\n")

    @property
    def dropin(self) -> Path:
        return self.dropin_dir / "05-jarvis-haertung.conf"

    @property
    def banner(self) -> Path:
        return self.d / "jarvis-banner.txt"

    def sshd_t(self, binaer: str = "") -> dict[str, str]:
        """Wirksame Werte laut echtem ``sshd -T`` (Schluessel klein).

        ``binaer`` liest mit einem anderen sshd als dem des Systems - gebraucht
        fuer das nachgestellte neuere OpenSSH weiter unten."""
        p = subprocess.run([binaer or SSHD, "-T", "-f", str(self.sshd_config)],
                           capture_output=True,
                           text=True, timeout=30)
        erg: dict[str, str] = {}
        for z in p.stdout.splitlines():
            teile = z.split(None, 1)
            if len(teile) == 2:
                erg.setdefault(teile[0].lower(), teile[1].strip())
        return erg

    def env(self, **extra: str) -> dict:
        e = {k: v for k, v in os.environ.items() if k not in ("SUDO_USER",)}
        e.pop("JARVIS_SSHD_BIN", None)
        e.update(self.extra)
        e.update(JARVIS_SSH_TEST="1", JARVIS_SSHD_CONFIG=str(self.sshd_config),
                 JARVIS_SSHD_DROPIN_DIR=str(self.dropin_dir),
                 JARVIS_BROKER_CONF=str(self.broker_conf),
                 JARVIS_PASSWD=str(self.passwd), JARVIS_GROUP=str(self.group))
        e.update(extra)
        return e

    def ssh(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(SSH_SKRIPT), *args], env=self.env(**extra),
                              capture_output=True, text=True, timeout=60)

    def wirksam(self) -> dict[str, str]:
        """sshd-Semantik: bei globalen Schluesselwoertern gilt der ERSTE Wert."""
        erg: dict[str, str] = {}
        if not self.dropin.is_file():
            return erg
        for z in self.dropin.read_text().splitlines():
            z = z.strip()
            if not z or z.startswith("#"):
                continue
            teile = z.split(None, 1)
            if len(teile) == 2:
                erg.setdefault(teile[0].lower(), teile[1].strip())
        return erg

    def konf(self, schluessel: str) -> str | None:
        wert = None
        for z in self.broker_conf.read_text().splitlines():
            m = re.match(rf"\s*{schluessel}\s*=\s*(.*)$", z)
            if m:
                wert = m.group(1).strip().strip('"')
        return wert

    def weg(self) -> None:
        shutil.rmtree(self.d, ignore_errors=True)


abschnitt("M7.1 Positivkontrolle: Sandkasten + Skript laufen")
k = Kasten(keys={"admin": 1}, sudo=["admin"])
r = k.ssh("--status")
if r.returncode != 0 or "admin" not in r.stdout:
    print(r.stdout, r.stderr)
    abbruch("ssh_haertung.sh --status laeuft im Sandkasten nicht (Messaufbau)")
check("--status nennt das Konto mit Schluessel", "admin" in r.stdout)
k.weg()

abschnitt("M7.2 --anwenden: Inhalt und Wirkung des Drop-ins")
k = Kasten(keys={"admin": 2}, sudo=["admin"])
r = k.ssh("--anwenden")
check("--anwenden Exit 0", r.returncode == 0, r.stderr.strip())
w = k.wirksam()
check("Drop-in geschrieben", k.dropin.is_file())
check("PasswordAuthentication no", w.get("passwordauthentication") == "no", w)
check("KbdInteractiveAuthentication no", w.get("kbdinteractiveauthentication") == "no", w)
check("PermitEmptyPasswords no", w.get("permitemptypasswords") == "no", w)
check("PermitRootLogin no (Vorgabe, BSI)", w.get("permitrootlogin") == "no", w)
GRENZEN = {"maxauthtries": "3", "maxsessions": "2", "logingracetime": "30",
           "clientaliveinterval": "300", "clientalivecountmax": "2", "tcpkeepalive": "no",
           "x11forwarding": "no", "allowagentforwarding": "no", "allowtcpforwarding": "no",
           "loglevel": "verbose"}
for _s, _v in GRENZEN.items():
    check(f"Grenze {_s} {_v} im Drop-in (B9)", (w.get(_s) or "").lower() == _v, w.get(_s))
check("Banner zeigt auf die eigene Datei neben dem Drop-in-Verzeichnis (nicht /etc/issue.net)",
      w.get("banner") == str(k.banner), w.get("banner"))
_bt = k.banner.read_text() if k.banner.is_file() else ""
check("Banner-Datei geschrieben, nicht leer, nennt kein Betriebssystem",
      bool(_bt.strip()) and not re.search(r"(?i)debian|ubuntu|linux|\\[nlrsv]", _bt), _bt)
txt = k.dropin.read_text() if k.dropin.is_file() else ""
check("kein Match-Block im Drop-in (sonst gilt der Rest nur bedingt)",
      not re.search(r"(?im)^\s*match\b", txt))
check("Dateiname sortiert VOR 50-cloud-init.conf und 50-jarvis-nur-schluessel.conf",
      k.dropin.name < "50-cloud-init.conf" and k.dropin.name < "50-jarvis-nur-schluessel.conf",
      k.dropin.name)
check("SSH_HAERTUNG=an in broker.conf", k.konf("SSH_HAERTUNG") == "an", k.broker_conf.read_text())
check("vorhandene broker.conf-Zeilen bleiben", k.konf("QUELLE") == "github")
r = k.ssh("--anwenden")
check("zweiter Lauf idempotent (eine SSH_HAERTUNG-Zeile)",
      k.broker_conf.read_text().count("SSH_HAERTUNG=") == 1 and r.returncode == 0)
k.weg()

abschnitt("M7.3 Aussperr-Schutz")
k = Kasten(keys={"anna": 1}, sudo=["admin"])   # anna hat Schluessel, ist aber kein Admin
r = k.ssh("--anwenden")
check("kein Admin mit Schluessel -> Exit 3", r.returncode == 3, (r.returncode, r.stderr.strip()))
check("…und nichts geschrieben", not k.dropin.exists())
check("…und SSH_HAERTUNG nicht gesetzt", k.konf("SSH_HAERTUNG") is None)
r = k.ssh("--test", "60")
check("--test unterliegt demselben Schutz", r.returncode == 3 and not k.dropin.exists(),
      r.returncode)
r = k.ssh("--anwenden", "--erzwingen")
check("--erzwingen uebergeht den Schutz (laut)", r.returncode == 0 and k.dropin.exists()
      and "WARNUNG" in r.stderr, (r.returncode, r.stderr.strip()))
k.weg()

k = Kasten(keys={"admin": 1}, sudo=["admin", "anna"])
r = k.ssh("--anwenden", SUDO_USER="anna")
check("Aufrufer per sudo ohne eigenen Schluessel -> Exit 3",
      r.returncode == 3 and not k.dropin.exists(), (r.returncode, r.stderr.strip()))
r = k.ssh("--anwenden", SUDO_USER="admin")
check("Aufrufer mit Schluessel -> geschrieben", r.returncode == 0 and k.dropin.exists())
k.weg()

k = Kasten(keys={"admin": 0, "dienst": 1}, sudo=["admin", "dienst"])
r = k.ssh("--anwenden")
check("Konto mit nologin zaehlt nicht als Zugang", r.returncode == 3, r.returncode)
k.weg()

abschnitt("M7.4 SSH_ROOT")
k = Kasten(keys={"root": 1}, sudo=[])
r = k.ssh("--anwenden")
check("nur root mit Schluessel, SSH_ROOT=nein -> Exit 3 (root kaeme nicht mehr herein)",
      r.returncode == 3, r.returncode)
k.weg()
k = Kasten(keys={"root": 1}, sudo=[], conf="SSH_ROOT=schluessel\n")
r = k.ssh("--anwenden")
check("SSH_ROOT=schluessel -> root mit Schluessel genuegt", r.returncode == 0, r.stderr.strip())
check("…PermitRootLogin prohibit-password", k.wirksam().get("permitrootlogin") == "prohibit-password",
      k.wirksam())
check("…Kennwort bleibt trotzdem aus", k.wirksam().get("passwordauthentication") == "no")
k.weg()

abschnitt("M7.5 ohne Include in sshd_config")
k = Kasten(keys={"admin": 1}, sudo=["admin"], include=False)
r = k.ssh("--anwenden")
check("Abbruch statt wirkungslosem Drop-in", r.returncode != 0 and not k.dropin.exists(),
      r.returncode)
k.weg()

abschnitt("M7.6 --erneuern (Broker-Start)")
k = Kasten(keys={"admin": 1}, sudo=["admin"])
r = k.ssh("--erneuern")
check("SSH_HAERTUNG fehlt -> nichts geschrieben (erste Umstellung macht ein Mensch)",
      r.returncode == 0 and not k.dropin.exists(), r.returncode)
k.broker_conf.write_text("SSH_HAERTUNG=an\n")
r = k.ssh("--erneuern")
check("SSH_HAERTUNG=an -> Drop-in hergestellt", k.dropin.is_file()
      and k.wirksam().get("passwordauthentication") == "no", r.stderr.strip())
k.dropin.write_text("PasswordAuthentication yes\n")
k.ssh("--erneuern")
check("…und von Hand veraendert -> zurueckgeschrieben",
      k.wirksam().get("passwordauthentication") == "no", k.wirksam())
k.broker_conf.write_text("SSH_HAERTUNG=aus\n")
k.ssh("--erneuern")
check("SSH_HAERTUNG=aus -> Drop-in entfernt", not k.dropin.exists())
k.weg()
k = Kasten(keys={"admin": 1}, sudo=["admin"], conf="SSH_HAERTUNG=an\n")
k.ssh("--erneuern")
(k.d / "home" / "admin" / ".ssh" / "authorized_keys").unlink()
k.dropin.write_text("# alt\nPasswordAuthentication no\n")
r = k.ssh("--erneuern")
check("Schluessel spaeter entfernt -> vorhandener Stand bleibt, Warnung",
      k.dropin.read_text() == "# alt\nPasswordAuthentication no\n" and "WARNUNG" in r.stderr,
      r.stderr.strip())
r = k.ssh("--aus")
check("--aus entfernt und setzt SSH_HAERTUNG=aus",
      not k.dropin.exists() and k.konf("SSH_HAERTUNG") == "aus")
k.weg()

abschnitt("M7.7 haertung_installieren.sh ruft --erneuern")
for wert, soll in (("an", True), ("", False)):
    k = Kasten(keys={"admin": 1}, sudo=["admin"], conf=(f"SSH_HAERTUNG={wert}\n" if wert else ""))
    unit = k.d / "units"
    (unit).mkdir()
    (unit / "jarvis.service").write_text("[Service]\nUser=jarvis\n")
    r = subprocess.run(["bash", str(HAERTUNG), str(k.d / "opt")],
                       env=k.env(JARVIS_HAERTUNG_TEST="1", JARVIS_UNIT_DIR=str(unit),
                                 JARVIS_LOGROTATE_DIR=str(k.d / "logrotate"),
                                 JARVIS_GEHEIMNIS_DATEI=str(k.d / "geheimnis.key"),
                                 JARVIS_BROKER_AUDIT=str(k.d / "audit.jsonl")),
                       capture_output=True, text=True, timeout=60)
    if not (unit / "jarvis.service.d" / "50-haertung.conf").is_file():
        print(r.stdout, r.stderr)
        abbruch("haertung_installieren.sh lief im Sandkasten nicht durch (Messaufbau)")
    check(f"SSH_HAERTUNG={wert or '(fehlt)'} -> Drop-in {'da' if soll else 'nicht da'}",
          k.dropin.exists() == soll, r.stderr.strip()[-300:])
    k.weg()

abschnitt("M7.9 Wirkung mit echtem sshd -T (B9-Grenzen, Vorrang frueherer Dateien)")
if not SSHD or not shutil.which("ssh-keygen"):
    abbruch("sshd oder ssh-keygen fehlt – die Wirkung laesst sich nicht messen (Paket openssh-server)")
k = Kasten(keys={"admin": 1}, sudo=["admin"], echt_sshd=True)
vorher = k.sshd_t()
if vorher.get("x11forwarding") != "yes" or vorher.get("maxauthtries") != "6":
    print(vorher)
    abbruch("sshd -T liest die Sandkasten-Konfiguration nicht (Messaufbau)")
check("Positivkontrolle: ohne Drop-in gelten die Vorgaben (x11forwarding yes, maxauthtries 6)", True)
r = k.ssh("--anwenden")
check("--anwenden mit echtem sshd -t/-T: Exit 0", r.returncode == 0, (r.returncode, r.stderr.strip()))
t = k.sshd_t()
for _s, _v in GRENZEN.items():
    check(f"wirksam laut sshd -T: {_s} {_v}", (t.get(_s) or "").lower() == _v, t.get(_s))
check("wirksam: permitrootlogin no", t.get("permitrootlogin") == "no", t.get("permitrootlogin"))
check("wirksam: passwordauthentication no", t.get("passwordauthentication") == "no")
check("wirksam: banner = eigene Datei", t.get("banner") == str(k.banner), t.get("banner"))
r = k.ssh("--status")
check("--status: jede Zeile wirksam", "jede Zeile wirksam" in r.stdout, r.stdout[-400:])
# Eine SPAETER gelesene Datei verliert – darf also keinen Abbruch ausloesen
(k.dropin_dir / "60-spaeter.conf").write_text("MaxAuthTries 6\nAllowTcpForwarding yes\n")
k.dropin.unlink(missing_ok=True)
r = k.ssh("--anwenden")
check("spaetere Datei mit lockeren Werten: kein Abbruch, Drop-in gewinnt",
      r.returncode == 0 and k.sshd_t().get("maxauthtries") == "3", (r.returncode, r.stderr.strip()))
k.weg()

k = Kasten(keys={"admin": 1}, sudo=["admin"], echt_sshd=True)
(k.dropin_dir / "00-haertung.conf").write_text(
    "PasswordAuthentication no\nPermitRootLogin prohibit-password\nAllowUsers *@192.0.2.0/24\n")
r = k.ssh("--test", "60")
check("frueher gelesene Datei ueberstimmt PermitRootLogin -> --test Exit 7",
      r.returncode == 7, (r.returncode, r.stderr.strip()))
check("…Meldung nennt Schluessel und Datei",
      "permitrootlogin" in r.stderr and "00-haertung.conf" in r.stderr, r.stderr.strip())
check("…Drop-in und Banner zurueckgenommen", not k.dropin.exists() and not k.banner.exists())
r = k.ssh("--anwenden")
check("…--anwenden ebenso Exit 7 und SSH_HAERTUNG nicht gesetzt",
      r.returncode == 7 and k.konf("SSH_HAERTUNG") is None, (r.returncode, k.konf("SSH_HAERTUNG")))
k.weg()

k = Kasten(keys={"root": 1}, sudo=[], conf="SSH_ROOT=schluessel\n", echt_sshd=True)
(k.dropin_dir / "00-haertung.conf").write_text("PermitRootLogin prohibit-password\n")
r = k.ssh("--anwenden")
_wirksam = k.sshd_t().get("permitrootlogin")
check("gleicher Wert in frueherer Datei (prohibit-password = without-password) -> kein Abbruch",
      r.returncode == 0 and _wirksam in ("without-password", "prohibit-password"),
      (r.returncode, _wirksam, r.stderr.strip()))
k.weg()

# Dieselbe Lage, aber sshd -T schreibt PermitRootLogin unter der ANDEREN
# Schreibweise. Debian 13 gibt den alten Namen aus (without-password), neuere
# OpenSSH-Fassungen den heutigen (prohibit-password) - das Skript muss beide als
# gleichwertig nehmen. Am 2026-11-19 auf einem Laeufer mit neuerem OpenSSH
# gemessen: es nahm dort seinen eigenen Drop-in bei JEDEM Lauf zurueck, die
# Haertung griff nie, und auf Debian war davon nichts zu sehen.
k = Kasten(keys={"root": 1}, sudo=[], conf="SSH_ROOT=schluessel\n", echt_sshd=True)
_anders = k.d / "sshd_andere_schreibweise"
_anders.write_text(
    "#!/bin/bash\n"
    "for a in \"$@\"; do\n"
    "    [ \"$a\" = \"-T\" ] || continue\n"
    f"    \"{SSHD}\" \"$@\" | sed -e 's/^permitrootlogin without-password$/permitrootlogin prohibit-password/'"
    " -e 't' -e 's/^permitrootlogin prohibit-password$/permitrootlogin without-password/'\n"
    "    exit ${PIPESTATUS[0]}\n"
    "done\n"
    f"exec \"{SSHD}\" \"$@\"\n", encoding="utf-8")
_anders.chmod(0o755)
_echt_wert = k.sshd_t().get("permitrootlogin")
_anders_wert = k.sshd_t(str(_anders)).get("permitrootlogin")
if not _echt_wert or not _anders_wert or _echt_wert == _anders_wert:
    abbruch(f"das nachgestellte sshd schreibt PermitRootLogin nicht anders ({_echt_wert} / {_anders_wert})")
check(f"Positivkontrolle: nachgestelltes sshd -T schreibt '{_anders_wert}' statt '{_echt_wert}'", True)
k.extra["JARVIS_SSHD_BIN"] = str(_anders)
(k.dropin_dir / "00-haertung.conf").write_text("PermitRootLogin prohibit-password\n")
r = k.ssh("--anwenden")
check("andere Schreibweise in sshd -T: gleicher Wert bleibt gleichwertig, kein Abbruch",
      r.returncode == 0, (r.returncode, r.stderr.strip()))
check("…und der Drop-in bleibt liegen", k.dropin.exists())
k.weg()

k = Kasten(keys={"admin": 1}, sudo=["admin"], conf="SSH_HAERTUNG=an\n", echt_sshd=True)
k.ssh("--erneuern")
k.dropin.write_text("PasswordAuthentication no\n")
(k.dropin_dir / "01-fremd.conf").write_text("MaxSessions 10\n")
r = k.ssh("--erneuern")
check("--erneuern (Broker-Start) mit ueberstimmender Datei: alter Stand bleibt, kein Teilzustand",
      k.dropin.read_text() == "PasswordAuthentication no\n" and "ABBRUCH" in r.stderr
      and "maxsessions" in r.stderr, (r.returncode, r.stderr.strip()))
k.weg()

abschnitt("M7.8 firewall.sh: SSH_NETZE")


def fw(conf: str | None, sitzung: str | None = None) -> subprocess.CompletedProcess:
    d = Path(tempfile.mkdtemp(prefix="jv_fw_"))
    bc = d / "broker.conf"
    if conf is not None:
        bc.write_text(conf)
    e = {k: v for k, v in os.environ.items() if k != "SSH_CONNECTION"}
    e["JARVIS_BROKER_CONF"] = str(bc)
    if sitzung:
        e["SSH_CONNECTION"] = f"{sitzung} 50000 192.0.2.254 22"
    r = subprocess.run(["bash", str(FW_SKRIPT), "--zeigen"], env=e, capture_output=True,
                       text=True, timeout=60)
    shutil.rmtree(d, ignore_errors=True)
    return r


def allgemein_ports(nft: str) -> set[str]:
    m = re.search(r"^\s*tcp dport \{([^}]*)\} ct state new accept\s*$", nft, re.M)
    return {p.strip() for p in m.group(1).split(",")} if m else set()


r = fw(None)
if r.returncode != 0 or "table inet jarvis_fw" not in r.stdout:
    print(r.stdout, r.stderr)
    abbruch("firewall.sh --zeigen liefert keinen Regelsatz (Messaufbau)")
check("ohne SSH_NETZE: 22 in der allgemeinen Freigabe (kein Aussperren)",
      "22" in allgemein_ports(r.stdout), allgemein_ports(r.stdout))
check("ohne SSH_NETZE: 443 offen (Positivkontrolle der Port-Erkennung)",
      "443" in allgemein_ports(r.stdout))
r = fw('SSH_NETZE="192.0.2.0/24 2001:db8::/48 198.51.100.7"\n', sitzung="192.0.2.10")
check("mit SSH_NETZE: Exit 0, eigene Sitzung liegt drin", r.returncode == 0, r.stderr.strip())
ports = allgemein_ports(r.stdout)
check("mit SSH_NETZE: 22 NICHT mehr allgemein", "22" not in ports and "443" in ports, ports)
v4 = re.search(r"^\s*ip saddr \{([^}]*)\} tcp dport 22 ct state new accept\s*$", r.stdout, re.M)
v6 = re.search(r"^\s*ip6 saddr \{([^}]*)\} tcp dport 22 ct state new accept\s*$", r.stdout, re.M)
check("IPv4-Netze an Port 22", bool(v4) and {x.strip() for x in v4.group(1).split(",")}
      == {"192.0.2.0/24", "198.51.100.7/32"}, v4.group(1) if v4 else r.stdout)
check("IPv6-Netz an Port 22", bool(v6) and v6.group(1).strip() == "2001:db8::/48",
      v6.group(1) if v6 else "")
check("keine weitere Regel oeffnet 22", len(re.findall(r"dport 22\b", r.stdout)) == 2,
      r.stdout)
r = fw('SSH_NETZE="192.0.2.0/24"\n')
check("mit SSH_NETZE an der Konsole (keine SSH-Sitzung) -> laeuft", r.returncode == 0
      and "tcp dport 22" in r.stdout, (r.returncode, r.stderr.strip()))
r = fw('SSH_NETZE="192.0.2.0/24"\n', sitzung="203.0.113.5")
check("eigene Sitzung ausserhalb -> Exit 3", r.returncode == 3, (r.returncode, r.stderr.strip()))
r = fw('SSH_NETZE="192.0.2.0/24 kein-netz"\n')
check("ungueltiger Eintrag -> Abbruch statt still enger", r.returncode != 0, r.returncode)

# ════════════════════════════════════════════════════════════════════════════
# M6
# ════════════════════════════════════════════════════════════════════════════
abschnitt("M6.1 Node-Linie")
ns = NODE_SKRIPT.read_text(encoding="utf-8")
m_ziel = re.search(r"(?m)^ZIEL=(\d+)\s*$", ns)
m_min = re.search(r"(?m)^MINDEST=(\d+)\s*$", ns)
if not (m_ziel and m_min):
    abbruch("ZIEL/MINDEST in node_aktualisieren.sh nicht gefunden")
ziel, mindest = int(m_ziel.group(1)), int(m_min.group(1))
check("MINDEST >= 22 (Node 20 seit 30.04.2026 ohne Updates)", mindest >= 22, mindest)
check("ZIEL >= MINDEST und gerade (LTS-Linie)", ziel >= mindest and ziel % 2 == 0, ziel)
# Das Haupt-Image installiert Node seit 2026-10-21 ueber node_aktualisieren.sh
# selbst (Linie = ZIEL, Schluessel gegen Fingerabdruck) statt ueber das
# NodeSource-setup-Skript per Pipe. Geprueft wird deshalb, dass es das Skript
# KOPIERT UND AUSFUEHRT und keine eigene Node-Quelle mehr fuehrt.
df = ohne_kommentare((ROOT / "Dockerfile").read_text(encoding="utf-8"))
check("Dockerfile kopiert node_aktualisieren.sh ins Image",
      re.search(r"(?m)^COPY\s+deploy/security/node_aktualisieren\.sh\s+(\S+)", df) is not None)
_df_ziel = re.search(r"(?m)^COPY\s+deploy/security/node_aktualisieren\.sh\s+(\S+)", df)
check("Dockerfile fuehrt das kopierte Skript aus",
      bool(_df_ziel) and re.search(r"\bbash\s+%s\b" % re.escape(_df_ziel.group(1)), df) is not None)
check("Dockerfile ohne eigene NodeSource-Quelle (setup_NN.x / node_NN.x)",
      not re.search(r"(setup|node)_\d+\.x", df), re.findall(r"(?:setup|node)_\d+\.x", df))
check("Dockerfile: kein Netz-Skript per Pipe in eine Shell",
      not re.search(r"\|\s*(sudo\s+)?(ba)?sh\b", df))
check("Dockerfile auf derselben Debian-Linie wie die Server (trixie)",
      re.search(r"(?m)^FROM\s+debian:trixie(-slim)?\s*$", df) is not None,
      re.findall(r"(?m)^FROM\s+\S+", df))
quellen = {
    "services/whatsapp-bridge/Dockerfile": re.findall(
        r"(?m)^FROM node:(\d+)", (ROOT / "services/whatsapp-bridge/Dockerfile").read_text()),
    "docs/install.sh": re.findall(r"setup_(\d+)\.x", ohne_kommentare((ROOT / "docs/install.sh").read_text())),
}
for datei, funde in quellen.items():
    check(f"{datei}: Node {ziel} (gefunden {funde})", bool(funde) and all(int(f) == ziel for f in funde))
# install.sh (apt): Node ueber das gepruefte Skript nach dem Klonen, nicht mehr
# ueber deb.nodesource.com/setup per Pipe (2026-10-21). Der rpm-Zweig hat kein
# solches Skript und bleibt bei setup_NN.x – der steht oben in quellen.
inst = ohne_kommentare((ROOT / "docs/install.sh").read_text(encoding="utf-8"))
check("install.sh: kein deb.nodesource-setup-Skript mehr (apt)",
      "deb.nodesource.com/setup_" not in inst)
check("install.sh: apt-Zweig fuehrt node_aktualisieren.sh aus",
      re.search(r'bash\s+"\$INSTALL_DIR/deploy/security/node_aktualisieren\.sh"', inst) is not None
      and re.search(r"(?m)^\s*NODE_UEBER_SKRIPT=1\s*$", inst) is not None)
check("Schluessel-Fingerabdruck festgeschrieben (40 hex)",
      bool(re.search(r'(?m)^NODESOURCE_FPR="[0-9A-F]{40}"\s*$', ns)))
check("kein Netz-Skript per Pipe in eine Shell", not re.search(r"\|\s*(sudo\s+)?(ba)?sh\b",
                                                                ohne_kommentare(ns)))
check("Pin-Priority fuer nodejs aus NodeSource", "Pin-Priority: 600" in ns)

fake = Path(tempfile.mkdtemp(prefix="jv_node_"))
for ver, soll in (("20.19.2", 1), (f"{ziel}.1.0", 0), (f"{mindest}.0.0", 0)):
    (fake / "node").write_text(
        "#!/bin/sh\n"
        f'case "$1" in --version) echo v{ver};; -p) echo {ver.split(".")[0]};; esac\n')
    (fake / "node").chmod(0o755)
    r = subprocess.run(["bash", str(NODE_SKRIPT), "--pruefen"], capture_output=True, text=True,
                       env=dict(os.environ, PATH=f"{fake}:{os.environ.get('PATH', '')}"), timeout=30)
    check(f"--pruefen mit Node {ver} -> Exit {soll}", r.returncode == soll, (r.returncode, r.stdout))
shutil.rmtree(fake, ignore_errors=True)
sjr = ohne_kommentare((ROOT / "start_jarvis_root.sh").read_text())
check("Broker-Start meldet eine alte Node-Linie (--pruefen)",
      bool(re.search(r'"\$NODE_SKRIPT"\s+--pruefen', sjr)))
# Seit 2026-10-26 (CVE-2026-111497): ein TAEGLICHER Timer, der auch auf der
# Ziel-Linie laeuft – vorher startete die Unit nur unter ZIEL, und ein
# Sicherheitsstand innerhalb der Linie blieb liegen (ECHT 24.21.0).
_sjr_timer = re.search(r'systemd-run --collect --unit=jarvis-node-aktualisieren \\\n'
                       r'([^\n]*)\\\n[^\n]*\\\n\s*/bin/bash "\$NODE_SKRIPT" --automatisch', sjr)
check("Broker-Start legt einen Timer fuer --automatisch an (kurz nach dem Start + taeglich)",
      _sjr_timer is not None and "--on-calendar=daily" in _sjr_timer.group(1)
      and "--on-active=" in _sjr_timer.group(1), _sjr_timer.group(0) if _sjr_timer else None)
check("…nicht nur unter der Ziel-Linie (keine --ziel-erreicht-Schranke davor)",
      "--ziel-erreicht" not in sjr)
check("…stoppt einen vorhandenen Timer vorher (Broker-Neustart legt ihn neu an)",
      bool(re.search(r'systemctl stop jarvis-node-aktualisieren\.timer[^\n]*\n(?:[^\n]*\n)?\s*systemd-run --collect', sjr)))

# --automatisch: Entscheidung wirklich ausfuehren (Attrappe node, Trockenlauf aus Datei)
fake = Path(tempfile.mkdtemp(prefix="jv_node_auto_"))


def auto(major: int, sim: str, konf: str = "", extra: dict | None = None) -> subprocess.CompletedProcess:
    (fake / "node").write_text(
        "#!/bin/sh\n"
        f'case "$1" in --version) echo v{major}.0.0;; -p) echo {major};; esac\n')
    (fake / "node").chmod(0o755)
    (fake / "sim.txt").write_text(sim)
    (fake / "broker.conf").write_text(konf)
    env = dict(os.environ, PATH=f"{fake}:{os.environ.get('PATH', '')}",
               JARVIS_NODE_TEST="1", JARVIS_NODE_SIM=str(fake / "sim.txt"),
               JARVIS_BROKER_CONF=str(fake / "broker.conf"), JARVIS_DIR=str(fake / "kein-jv"))
    env.update(extra or {})
    return subprocess.run(["bash", str(NODE_SKRIPT), "--automatisch"], capture_output=True, text=True,
                          timeout=60, env=env)


SAUBER = "Kandidat: 24.21.0-1nodesource1\n  Inst nodejs [20.20.2] (24.21.0)\n  Remv npm [9.2.0]\n  Remv libnode115 [20.19.2]\n"
FREMD = SAUBER + "  Remv webpack [5.0]\n  Remv node-acorn [8.8]\n"
r = auto(20, SAUBER)
check("--automatisch: nur Node-eigene Pakete betroffen -> stellt um",
      r.returncode == 0 and "wuerde jetzt umstellen" in r.stdout, (r.returncode, r.stdout, r.stderr))
r = auto(20, FREMD)
check("--automatisch: fremde Pakete wuerden entfernt -> NICHT umstellen, Warnung nennt sie",
      r.returncode == 4 and "webpack" in r.stderr and "wuerde jetzt" not in r.stdout, (r.returncode, r.stderr))
_GLEICH = {"JARVIS_NODE_INST": f"{ziel}.22.1-1nodesource1", "JARVIS_NODE_KAND": f"{ziel}.22.1-1nodesource1"}
r = auto(ziel, SAUBER, extra=_GLEICH)
check("--automatisch: Ziel-Linie erreicht und neuester Stand -> nichts",
      r.returncode == 0 and "erreicht" in r.stdout and "neueste Stand" in r.stdout
      and "wuerde jetzt" not in r.stdout, (r.returncode, r.stdout, r.stderr))
r = auto(20, SAUBER, "NODE_AUTO=aus\n")
check("--automatisch: NODE_AUTO=aus -> nichts", r.returncode == 0 and "NODE_AUTO=aus" in r.stdout
      and "wuerde jetzt" not in r.stdout, r.stdout)
(fake / "node").write_text("#!/bin/sh\necho 22\n")
r = subprocess.run(["bash", str(NODE_SKRIPT), "--ziel-erreicht"], capture_output=True, text=True,
                   env=dict(os.environ, PATH=f"{fake}:{os.environ.get('PATH', '')}"))
check("--ziel-erreicht mit 22 < ZIEL -> Exit != 0", r.returncode != 0)

# Code-Review 2026-10-07 (NIEDRIG): die Schranke gilt auch UNMITTELBAR vor der
# Installation (echter Stand), nicht nur im Wegwerf-Trockenlauf
(fake / "sim_echt.txt").write_text(FREMD)


def auto_echt(major, sim, sim_echt, extra=None):
    (fake / "node").write_text(
        "#!/bin/sh\n"
        f'case "$1" in --version) echo v{major}.0.0;; -p) echo {major};; esac\n')
    (fake / "node").chmod(0o755)
    (fake / "sim.txt").write_text(sim)
    (fake / "sim_echt.txt").write_text(sim_echt)
    (fake / "broker.conf").write_text("")
    env = dict(os.environ, PATH=f"{fake}:{os.environ.get('PATH', '')}", JARVIS_NODE_TEST="1",
               JARVIS_NODE_SIM=str(fake / "sim.txt"), JARVIS_NODE_SIM_ECHT=str(fake / "sim_echt.txt"),
               JARVIS_BROKER_CONF=str(fake / "broker.conf"), JARVIS_DIR=str(fake / "jv"))
    env.update(extra or {})
    return subprocess.run(["bash", str(NODE_SKRIPT), "--automatisch"], capture_output=True,
                          text=True, timeout=60, env=env)


r = auto_echt(20, SAUBER, SAUBER)
check("Positivkontrolle: Trockenlauf UND echter Stand sauber -> wuerde installieren",
      r.returncode == 0 and "wuerde jetzt installieren" in r.stdout, (r.returncode, r.stdout, r.stderr))
r = auto_echt(20, SAUBER, FREMD)
check("⚠ Trockenlauf sauber, echter Stand entfernt fremde Pakete -> Abbruch vor apt-get install",
      r.returncode == 4 and "webpack" in r.stderr and "wuerde jetzt installieren" not in r.stdout,
      (r.returncode, r.stdout, r.stderr))
_env_hand = dict(os.environ, PATH=f"{fake}:{os.environ.get('PATH', '')}", JARVIS_NODE_TEST="1",
                 JARVIS_NODE_SIM_ECHT=str(fake / "sim_echt.txt"), JARVIS_DIR=str(fake / "jv"))
_env_hand.pop("JARVIS_NODE_AUTO", None)
r = subprocess.run(["bash", str(NODE_SKRIPT)], capture_output=True, text=True, timeout=60, env=_env_hand)
check("von Hand (ohne Automatik) bleibt die Entscheidung beim Betreiber",
      r.returncode == 0 and "wuerde jetzt installieren" in r.stdout, (r.returncode, r.stderr))

# npm rebuild nie als root (Bridge-Verzeichnis kann vor dem chown root gehoeren)
_bridge = fake / "jv" / "services" / "whatsapp-bridge"
(_bridge / "node_modules").mkdir(parents=True, exist_ok=True)
(_bridge / "package.json").write_text("{}")
_log = fake / "runuser.log"
for _n, _rumpf in (("stat", 'echo "$FAKE_EIGNER"'),
                   ("runuser", f'echo "$*" >> "{_log}"'),
                   ("systemctl", "exit 3")):
    (fake / _n).write_text("#!/bin/sh\n" + _rumpf + "\n")
    (fake / _n).chmod(0o755)
_log.write_text("")
r = auto_echt(20, SAUBER, SAUBER, {"FAKE_EIGNER": "root"})
check("⚠ Bridge gehoert root -> KEIN npm rebuild (auch nicht als root), Warnung",
      r.returncode == 0 and _log.read_text() == "" and "npm rebuild NICHT als root" in r.stderr,
      (r.returncode, _log.read_text(), r.stderr[-200:]))
_log.write_text("")
r = auto_echt(20, SAUBER, SAUBER, {"FAKE_EIGNER": "jarvis"})
check("Positivkontrolle: Bridge gehoert jarvis -> npm rebuild als jarvis",
      "-u jarvis" in _log.read_text() and "npm rebuild" in _log.read_text(),
      (_log.read_text(), r.stderr[-200:]))

# ── Nachziehen innerhalb der Ziel-Linie (2026-10-26, CVE-2026-111497) ──
# Trockenlauf eines Patch-Updates: nur nodejs selbst
NACH_SAUBER = f"  Inst nodejs [{ziel}.21.0-1nodesource1] ({ziel}.22.1-1nodesource1)\n"


def nach(inst, kand, sim_echt=NACH_SAUBER, konf=""):
    # eigene Konfigurationsdatei: auto_echt schreibt broker.conf leer
    _log.write_text("")
    (fake / "broker_nach.conf").write_text(konf)
    return auto_echt(ziel, SAUBER, sim_echt, {"FAKE_EIGNER": "jarvis", "JARVIS_NODE_INST": inst,
                                              "JARVIS_NODE_KAND": kand,
                                              "JARVIS_BROKER_CONF": str(fake / "broker_nach.conf")})


r = nach(f"{ziel}.21.0-1nodesource1", f"{ziel}.22.1-1nodesource1")
check("Positivkontrolle: neuerer Stand in der Linie -> zieht nach",
      r.returncode == 0 and "wuerde jetzt nachziehen" in r.stdout
      and f"{ziel}.21.0-1nodesource1 -> {ziel}.22.1-1nodesource1" in r.stdout, (r.returncode, r.stdout, r.stderr))
check("…und startet die Bridge-Module danach neu (als Dienstbenutzer)",
      "-u jarvis" in _log.read_text() and "npm rebuild" in _log.read_text(), _log.read_text())
r = nach(f"{ziel}.9.0-1nodesource1", f"{ziel}.10.0-1nodesource1")
check("Versionsvergleich nach dpkg, nicht als Text (.9 < .10)",
      r.returncode == 0 and "wuerde jetzt nachziehen" in r.stdout, (r.returncode, r.stdout, r.stderr))
r = nach(f"{ziel}.22.1-1nodesource1", f"{ziel}.21.0-1nodesource1")
check("aelterer Kandidat -> nichts", r.returncode == 0 and "wuerde jetzt" not in r.stdout
      and _log.read_text() == "", (r.returncode, r.stdout))
r = nach(f"{ziel}.22.1-1nodesource1", f"{ziel + 2}.1.0-1nodesource1")
check("⚠ Kandidat einer ANDEREN Linie -> kein Nachziehen (Linienwechsel nur ueber ZIEL)",
      r.returncode == 4 and "wuerde jetzt" not in r.stdout and "ausserhalb der Linie" in r.stderr,
      (r.returncode, r.stdout, r.stderr))
r = nach(f"{ziel}.21.0-1nodesource1", f"{ziel}.22.1-1nodesource1", NACH_SAUBER + "  Remv webpack [5.0]\n")
check("⚠ Nachziehen wuerde fremde Pakete entfernen -> Abbruch, Warnung nennt sie",
      r.returncode == 4 and "webpack" in r.stderr and "wuerde jetzt" not in r.stdout,
      (r.returncode, r.stdout, r.stderr))
# Leerer Kandidat (apt-cache ohne Candidate-Zeile): dpkg haelt "" fuer NICHT
# groesser – ohne eigene Schranke stuende "neuester Stand" mit Exit 0 im Journal.
# ("(none)" eignet sich als Probe nicht: dpkg haelt es fuer GROESSER, und die
# Linien-Schranke faengt es zusaetzlich – zwei Wege zum selben Ergebnis.)
r = nach(f"{ziel}.21.0-1nodesource1", "")
check("Stand nicht bestimmbar -> Exit 4 statt still 'aktuell'",
      r.returncode == 4 and "wuerde jetzt" not in r.stdout, (r.returncode, r.stdout, r.stderr))
r = nach(f"{ziel}.21.0-1nodesource1", f"{ziel}.22.1-1nodesource1", konf="NODE_AUTO=aus\n")
check("NODE_AUTO=aus gilt auch fuers Nachziehen",
      r.returncode == 0 and "wuerde jetzt" not in r.stdout, (r.returncode, r.stdout))
# Echter Weg (root, apt) als REGEL: im Rumpf von _linie_nachziehen steht die
# Fremd-Schranke VOR dem einzigen Installationsaufruf, und der ist --only-upgrade
# (ein blosses install koennte eine andere Quelle/Linie ziehen).
_rumpf_m = re.search(r"(?ms)^_linie_nachziehen\(\) \{\n(.*?)^\}\n", ohne_kommentare(ns))
_rumpf = _rumpf_m.group(1) if _rumpf_m else ""
_p_fremd = _rumpf.find('if [ -n "$f" ]; then')
_p_upg = _rumpf.find("apt-get install -y --only-upgrade")
# gezaehlt wird der AUFRUF mit -y – die Fehlermeldung nennt den Befehl ebenfalls
check("echter Weg: Fremd-Schranke vor dem einzigen apt-get install, und der ist --only-upgrade",
      bool(_rumpf) and 0 <= _p_fremd < _p_upg and _rumpf.count("apt-get install -y") == 1
      and _rumpf.find("_fremde_entfernungen", 0, _p_fremd) >= 0, (_p_fremd, _p_upg))
check("--automatisch ruft auf der Ziel-Linie _linie_nachziehen",
      bool(re.search(r'Ziel-Linie \$ZIEL erreicht\."\n\s*_linie_nachziehen\n\s*exit \$\?', ohne_kommentare(ns))))

# Der echte Installationsweg (root, apt) laeuft hier nicht – als REGEL am
# Skript: die Schranke steht VOR dem einzigen `apt-get install -y nodejs`, und
# ihr Ergebnis bricht ab (Code-Review 2026-10-07).
_ns_ohne = ohne_kommentare(ns)
_p_schr = _ns_ohne.find('_schranke_auto "$tmp/sim_echt" || exit $?')
_p_inst = _ns_ohne.find("apt-get install -y nodejs")
check("echter Weg: Schranke gegen den ECHTEN Stand vor apt-get install -y",
      0 <= _p_schr < _p_inst and _ns_ohne.count("apt-get install -y nodejs") == 1
      and _ns_ohne.find("apt-get -s install nodejs", _p_inst - 400) < _p_schr,
      (_p_schr, _p_inst))
shutil.rmtree(fake, ignore_errors=True)

abschnitt("M6.1b Pakete der Server werden beim Start/taeglich nachgezogen")
import ast as _ast  # noqa: E402
_main_src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_hook = next((f for f in _ast.parse(_main_src).body if isinstance(f, _ast.AsyncFunctionDef)
              and f.name == "startup_abhaengigkeiten"), None)
check("Start-Hook startup_abhaengigkeiten vorhanden (@app.on_event('startup'))",
      _hook is not None and any(isinstance(d, _ast.Call) and getattr(d.func, "attr", "") == "on_event"
                                for d in _hook.decorator_list))
_rufe = {getattr(n.func, "attr", getattr(n.func, "id", "")) for n in _ast.walk(_hook)
         if isinstance(n, _ast.Call)} if _hook else set()
_im_thread = _hook is not None and any(
    isinstance(n, _ast.Call) and getattr(n.func, "attr", "") == "to_thread" and n.args
    and getattr(n.args[0], "attr", "") == "abgleichen" for n in _ast.walk(_hook))
check("…ruft abgleichen (im Thread) und startet bei Aenderung neu",
      _im_thread and "restart_service_delayed" in _rufe, _rufe)
_src = (quell_ausschnitt.segment(_main_src, _hook) or "") if _hook else ""
check("…Neustart nur bei NEUER Aenderung und nicht nach Ruecknahme (keine Schleife)",
      "neu != vorher" in _src and 'not erg.get("zurueckgesetzt")' in _src)
check("…taeglich wiederholt", "86400" in _src)

abschnitt("M6.2 Sicherheits-CI")
try:
    import yaml
except ImportError:
    abbruch("PyYAML fehlt – Workflow nicht pruefbar")
wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
ausloeser = wf.get("on", wf.get(True)) or {}
check("Ausloeser: push, pull_request, schedule",
      all(k in ausloeser for k in ("push", "pull_request", "schedule")), list(ausloeser))
check("Rechte nur contents: read", wf.get("permissions") == {"contents": "read"},
      wf.get("permissions"))
jobs = wf.get("jobs") or {}


def schritte(job: dict) -> list[dict]:
    return job.get("steps") or []


def job_mit(muster: str) -> tuple[str, dict] | None:
    for name, job in jobs.items():
        if any(re.search(muster, s.get("run") or "") for s in schritte(job)):
            return name, job
    return None


for titel, muster in (("Waechter-Sammellauf", r"tests/ci_lauf\.py"),
                      ("pip-audit", r"pip-audit\b"),
                      ("npm audit", r"npm audit\b"),
                      ("SBOM Python (CycloneDX)", r"cyclonedx-py\b"),
                      ("SBOM npm (CycloneDX)", r"cyclonedx-npm\b"),
                      ("SAST bandit", r"\bbandit\b.*-r\b"),
                      ("gitleaks", r"gitleaks\S* git\b"),
                      ("govulncheck (Go-Client)", r"govulncheck\S*\"? \./\.\.\."),
                      ("SBOM Go (CycloneDX, mit Standardbibliothek)", r"cyclonedx-gomod\S*\"? app\b.*-std\b"),
                      ("SBOM Android (CycloneDX)", r"gradlew\b.*:app:cyclonedxDirectBom\b")):
    check(f"Schritt: {titel}", job_mit(muster) is not None)
gv = job_mit(r"govulncheck\S*\"? \./\.\.\.")
# Android-SBOM nur aus der ausgelieferten App, nicht aus den Test-Konfigurationen;
# und die Gradle-Distribution, die die CI laedt, wird gegen ihre Pruefsumme geprueft.
_app_gradle = (ROOT / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
check("Android-SBOM auf releaseRuntimeClasspath begrenzt",
      re.search(r'includeConfigs\.set\(listOf\("releaseRuntimeClasspath"\)\)', _app_gradle) is not None)
check("Gradle-Wrapper prueft die Distribution (distributionSha256Sum)",
      re.search(r"(?m)^distributionSha256Sum=[0-9a-f]{64}\s*$",
                (ROOT / "android/gradle/wrapper/gradle-wrapper.properties").read_text(encoding="utf-8")) is not None)

# Das JDK des Android-Jobs wird FESTGELEGT, nicht vom Runner geerbt: am
# 2026-11-17 wechselte "ubuntu-latest" von Ubuntu 24.04 auf 26.04, dessen
# Standard-JDK 25.0.5 ist. Gradle 8.11.1/AGP 8.10.1 brachen damit ab - mit
# "25.0.5" als einziger Fehlerzeile, zwei Tage lang. Die Fassung kommt aus
# build.gradle.kts und steht hier NICHT als Konstante: wandert
# sourceCompatibility, muss der Workflow mitwandern.
_sc = re.search(r"sourceCompatibility\s*=\s*JavaVersion\.VERSION_(\d+)", _app_gradle)
if not _sc:
    abbruch("android/app/build.gradle.kts ohne sourceCompatibility = JavaVersion.VERSION_<n> – "
            "die erwartete JDK-Fassung des Workflows ist nicht ableitbar")
_jdk = _sc.group(1)
_sbom_job = job_mit(r"gradlew\b.*:app:cyclonedxDirectBom\b")
# Gemessen an JEDEM Schritt, der den SBOM-Task AUSFUEHRT, und ohne Kommentarzeilen:
# eine Begruendung im Text ist keine Wirkung.
_sbom_schritte = [ohne_kommentare(s.get("run") or "") for s in schritte(_sbom_job[1])
                  if re.search(r"gradlew\b.*:app:cyclonedxDirectBom\b", s.get("run") or "")] \
    if _sbom_job else []
# "bool(...) and all(...)" statt abbruch(): ohne SBOM-Schritt waere all() trivial
# wahr, aber ein FEHLENDER Schritt ist ein Befund (die Pruefung "Schritt: SBOM
# Android" oben meldet ihn) und kein "konnte nicht laufen" – gleiche Form wie bei
# govulncheck und pip-audit.
check(f"Android-SBOM baut mit festgelegtem JDK {_jdk} (JAVA_HOME_{_jdk}_X64 exportiert), "
      "nicht mit dem Standard-JDK des Runners",
      bool(_sbom_schritte)
      and all(re.search(r'export\s+JAVA_HOME="?\$\{?JAVA_HOME_%s_X64\}?"?(\s|$)' % _jdk, r)
              for r in _sbom_schritte), _sbom_schritte)
check("…und bricht ab, wenn das Runner-Image diese Variable nicht mehr setzt",
      bool(_sbom_schritte)
      and all(re.search(r"\$\{JAVA_HOME_%s_X64:\?" % _jdk, r) for r in _sbom_schritte),
      _sbom_schritte)
# Eine Gradle-Meldung ohne Quelle ("25.0.5") kostet einen halben Tag Suche.
check("Gradle nennt im Fehlerfall die Quelle (--stacktrace)",
      bool(_sbom_schritte) and all("--stacktrace" in r for r in _sbom_schritte), _sbom_schritte)


def toolchain_aus_gomod(run: str) -> bool:
    """GOTOOLCHAIN bekommt GENAU die Variable, die aus der toolchain-Zeile von go.mod
    gelesen wurde - ein blosses Vorkommen von "GOTOOLCHAIN=" liesse auch =auto durch
    (so in der Gegenprobe gesehen)."""
    q = re.search(r"(\w+)=\$\(awk '\$1 == \"toolchain\" \{print \$2\}' go\.mod\)", run)
    return bool(q) and re.search(r'GOTOOLCHAIN="?\$\{?%s\}?"?(\s|$)' % q.group(1), run) is not None


# Gemessen am Schritt, der govulncheck AUSFUEHRT – nicht an irgendeinem Schritt
# des Jobs: der SBOM-Schritt liest die Toolchain ebenfalls und haette eine
# Sabotage am govulncheck-Schritt verdeckt (Gegenprobe 2026-10-21).
gv_schritte = [s for s in schritte(gv[1]) if re.search(r"govulncheck\S*\"? \./\.\.\.", s.get("run") or "")] \
    if gv else []
check("govulncheck laeuft mit der Toolchain aus go.mod",
      bool(gv_schritte) and all(toolchain_aus_gomod(s.get("run") or "") for s in gv_schritte))
# Ohne toolchain-Zeile baut Go mit der nackten Fassung aus "go 1.x.0" - also ohne
# Patch-Fassungen (2026-10-21: 38 erreichte Schwachstellen unter go1.25.0).
check("go.mod legt die Toolchain fest",
      re.search(r"(?m)^toolchain go\d+\.\d+\.\d+\s*$", GOMOD.read_text(encoding="utf-8")) is not None)
pa = job_mit(r"pip-audit\b")
# Gemessen an JEDEM Schritt, der pip-audit AUSFUEHRT (Aufruf ueber einen Pfad,
# nicht die Installation per pip): seit der Skill-Lock-Schritt die Liste
# ebenfalls liest, haette "irgendein Schritt" eine Sabotage am anderen verdeckt
# (Gegenprobe 2026-11-11, gleiche Falle wie bei govulncheck).
pa_schritte = [s for s in schritte(pa[1]) if re.search(r"/pip-audit\b", s.get("run") or "")] \
    if pa else []
check("pip-audit liest die Ausnahmeliste – in jedem Schritt, der es ausfuehrt",
      bool(pa_schritte) and all("pip_audit_ausnahmen.py" in (s.get("run") or "") for s in pa_schritte),
      [s.get("name") for s in pa_schritte])
na = job_mit(r"npm audit\b")
check("npm audit mit --audit-level",
      bool(na) and any(re.search(r"npm audit\b.*--audit-level=(low|moderate|high)", s.get("run") or "")
                       for s in schritte(na[1])))
gl = job_mit(r"gitleaks\S* git\b")
co = [s for s in schritte(gl[1]) if str(s.get("uses", "")).startswith("actions/checkout")] if gl else []
check("gitleaks sieht die GANZE Historie (fetch-depth: 0)",
      bool(co) and (co[0].get("with") or {}).get("fetch-depth") == 0, co)
check("gitleaks-Download gegen Pruefsumme",
      bool(gl) and any("sha256sum -c" in (s.get("run") or "") for s in schritte(gl[1])))
lauf_step = job_mit(r"tests/ci_lauf\.py")
nodes = [s for s in schritte(lauf_step[1]) if str(s.get("uses", "")).startswith("actions/setup-node")] \
    if lauf_step else []
check(f"CI-Waechter laufen unter Node {ziel}",
      bool(nodes) and str((nodes[0].get("with") or {}).get("node-version")) == str(ziel))
# Ergebnis-Cache der Baum-Waechter (2026-11-22, tests/lib/ergebnis_cache.py):
# ohne ihn lesen test_keine_echtwerte/test_kommentare_deutsch in der CI bei
# jedem Lauf alle Dateien neu. Gemessen wird die ANORDNUNG im Job, nicht das
# Vorkommen eines Namens: Wiederherstellen VOR dem Lauf, Sichern DANACH (auch
# bei Rot), derselbe Pfad wie im env des Laufs - und der liegt in runner.temp,
# denn test_keine_echtwerte liest auch unverfolgte Dateien im Workspace.
_ls = schritte(lauf_step[1]) if lauf_step else []
_li = next((i for i, s in enumerate(_ls) if re.search(r"tests/ci_lauf\.py", s.get("run") or "")), None)
_cenv = (_ls[_li].get("env") or {}).get("JARVIS_WAECHTER_CACHE") if _li is not None else None


def _cache_schritte(art):
    return [(i, s) for i, s in enumerate(_ls) if str(s.get("uses", "")).startswith(f"actions/cache/{art}@")]


def _cpfad(s):
    return str((s.get("with") or {}).get("path") or "").strip()


_wieder = [(i, s) for i, s in _cache_schritte("restore") if _cpfad(s) == _cenv]
# venv-Cache (2026-11-22): die Installation aus der Lock kostete je Lauf gut
# 4 Minuten. Gemessen wird wieder die ANORDNUNG: Wiederherstellen vor der
# Installation, die Installation selbst ohne Bedingung (sie gleicht einen
# Treffer gegen die Lock ab), Sichern direkt danach und nur ohne Treffer - also
# bevor Skill-Locks oder sonst ein pip install die venv erweitern. Und der
# Schluessel traegt Abbild, Python-Fassung und Lock-Inhalt OHNE Teiltreffer:
# eine venv einer anderen Lock liesse Pakete stehen, die pip-audit und SBOM
# dann mitzaehlen.
_vi = next((i for i, s in enumerate(_ls)
            if re.search(r"--require-hashes\b", s.get("run") or "")
            and re.search(r"-r\s+requirements\.lock\b", s.get("run") or "")), None)
_vw = [(i, s) for i, s in _cache_schritte("restore") if _cpfad(s) == "venv"]
_vs = [(i, s) for i, s in _cache_schritte("save") if _cpfad(s) == "venv"]
_vweitere = [i for i, s in enumerate(_ls)
             if _vi is not None and i > _vi and re.search(r"venv/bin/pip install\b", s.get("run") or "")]
_py_id = next((s.get("id") for s in _ls if str(s.get("uses", "")).startswith("actions/setup-python@")), None)
_vkeys = [str((s.get("with") or {}).get("key") or "") for _, s in _vw + _vs]
check("venv-Cache: Installationsschritt aus der Lock gefunden (Positivkontrolle)", _vi is not None)
check("…wiederhergestellt VOR der Installation", _vi is not None and len(_vw) == 1 and _vw[0][0] < _vi,
      [i for i, _ in _vw])
check("…Installation laeuft immer (ohne if) und gleicht einen Treffer gegen die Lock ab",
      _vi is not None and "if" not in _ls[_vi], _ls[_vi].get("if") if _vi is not None else None)
_vid = _vw[0][1].get("id") if len(_vw) == 1 else None
check("…gesichert direkt nach der Installation und nur ohne Treffer",
      _vi is not None and len(_vs) == 1 and _vs[0][0] > _vi and bool(_vid)
      and re.fullmatch(r"steps\.%s\.outputs\.cache-hit\s*!=\s*'true'" % re.escape(str(_vid)),
                       str(_vs[0][1].get("if", "")).strip()) is not None,
      [(i, s.get("if")) for i, s in _vs])
check("…und VOR jedem weiteren pip install in die venv (Skill-Locks, exchangelib)",
      len(_vs) == 1 and bool(_vweitere) and all(_vs[0][0] < i for i in _vweitere),
      ([i for i, _ in _vs], _vweitere))
check("…Schluessel gleich fuer beide und aus Lock-Inhalt, Python-Fassung und Runner-Abbild",
      len(_vkeys) == 2 and len(set(_vkeys)) == 1 and "hashFiles('requirements.lock')" in _vkeys[0]
      and bool(_py_id) and f"steps.{_py_id}.outputs.python-version" in _vkeys[0]
      and re.search(r"steps\.[\w-]+\.outputs\.kennung", _vkeys[0]) is not None, (_py_id, _vkeys))
check("…ohne restore-keys (ein Teiltreffer braechte eine venv einer anderen Lock)",
      len(_vw) == 1 and "restore-keys" not in (_vw[0][1].get("with") or {}))
check("…venv-Cache-Actions per Commit gepinnt (40 Hex), nicht per Tag",
      bool(_vw) and bool(_vs)
      and all(re.fullmatch(r"actions/cache/(restore|save)@[0-9a-f]{40}", str(s.get("uses")))
              for _, s in _vw + _vs), [s.get("uses") for _, s in _vw + _vs])

_sichern = [(i, s) for i, s in _cache_schritte("save") if _cpfad(s) == _cenv]
check("CI-Waechter mit Ergebnis-Cache ausserhalb des Workspace (runner.temp)",
      isinstance(_cenv, str) and re.fullmatch(r"\$\{\{\s*runner\.temp\s*\}\}/\S+", _cenv) is not None, _cenv)
check("…wiederhergestellt VOR dem Waechterlauf, aus demselben Pfad",
      _li is not None and any(i < _li for i, _ in _wieder), [i for i, _ in _wieder])
check("…und gesichert DANACH, auch wenn ein Waechter rot ist (if: always())",
      _li is not None and any(i > _li and "always()" in str(s.get("if", "")) for i, s in _sichern),
      [(i, s.get("if")) for i, s in _sichern])
_ws = [str((s.get("with") or {}).get("key") or "") for _, s in _wieder + _sichern]
_rk = [str((s.get("with") or {}).get("restore-keys") or "").split() for _, s in _wieder]
check("…je Lauf ein eigener Schluessel (Eintraege sind unveraenderlich), gleich fuer beide Schritte",
      len(set(_ws)) == 1 and "github.run_id" in _ws[0] and "github.run_attempt" in _ws[0], _ws)
check("…und das Wiederherstellen nimmt den juengsten ueber das Praefix des Schluessels",
      bool(_rk) and bool(_ws) and all(any(_ws[0].startswith(r) and r for r in rk) for rk in _rk), _rk)
check("…Cache-Actions per Commit gepinnt (40 Hex), nicht per Tag",
      bool(_wieder) and bool(_sichern)
      and all(re.fullmatch(r"actions/cache/(restore|save)@[0-9a-f]{40}", str(s.get("uses")))
              for _, s in _wieder + _sichern), [s.get("uses") for _, s in _wieder + _sichern])

abschnitt("M6.3 Dependabot")
db = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
upd = db.get("updates") or []
oeko = {u.get("package-ecosystem") for u in upd}
check("pip, npm, github-actions, docker", {"pip", "npm", "github-actions", "docker"} <= oeko, oeko)
pip_u = next((u for u in upd if u.get("package-ecosystem") == "pip"), {})
np_ign = [i for i in pip_u.get("ignore") or [] if i.get("dependency-name") == "numpy"]
check("numpy >= 2.1 ausgeschlossen (DEV-VM ohne SSE4.2)",
      bool(np_ign) and ">=2.1" in (np_ign[0].get("versions") or []), np_ign)
npm_u = next((u for u in upd if u.get("package-ecosystem") == "npm"), {})
check("npm zeigt auf die Bridge", npm_u.get("directory") == "/services/whatsapp-bridge")

abschnitt("M6.4 Ausnahmelisten")


def modul(pfad: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, pfad)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pa_mod = modul(SEC / "pip_audit_ausnahmen.py", "pa_ausnahmen")
g, a, f = pa_mod.laden(dt.date(2000, 1, 1))
check("pip_audit_ausnahmen.txt: Format fehlerfrei", not f, f)
check("…mindestens eine Ausnahme (Positivkontrolle der Erkennung)", len(g) + len(a) > 0)
tmpd = Path(tempfile.mkdtemp(prefix="jv_pa_"))
alt_datei = pa_mod.DATEI
try:
    pa_mod.DATEI = tmpd / "x.txt"
    pa_mod.DATEI.write_text("PYSEC-2026-1  2027-01-01\n")
    check("Ausnahme ohne Grund ist ein Fehler", bool(pa_mod.laden(dt.date(2026, 1, 1))[2]))
    pa_mod.DATEI.write_text("PYSEC-2026-1  2026-01-01  # Grund\n")
    g2, a2, f2 = pa_mod.laden(dt.date(2026, 6, 1))
    check("abgelaufene Ausnahme wird erkannt", a2 == ["PYSEC-2026-1"] and not g2, (g2, a2, f2))
    _argv = sys.argv
    sys.argv = ["x", "--argumente"]
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        rc_abg = pa_mod.main()
    sys.argv = _argv
    check("…und macht den Lauf rot (Exit 1), statt still zu verlaengern", rc_abg == 1, rc_abg)
finally:
    pa_mod.DATEI = alt_datei
    shutil.rmtree(tmpd, ignore_errors=True)

ci_mod = modul(ROOT / "tests" / "ci_lauf.py", "ci_lauf_mod")
namen = [p.name for p in ci_mod.kandidaten([])]
check("CI-Lauf: Kandidaten nicht leer", len(namen) > 50, len(namen))
check("CI-Lauf: keine gegen_/live_ (patchen bzw. brauchen Dienst)",
      all(n.startswith("test_") for n in namen))
ausn = ci_mod.ausnahmen_laden()
check("ci_ausnahmen.txt laedt, jeder Eintrag mit Grund", all(ausn.values()) and len(ausn) > 0)
check("dieser Waechter ist nicht ausgenommen", "test_bsi_m6_m7.py" not in ausn)
# Der Auszug eines roten Waechters muss die Zeile mitnehmen, die den Abbruch
# ERKLAERT - und die ist hier deutsch ("FEHLER:"), nicht englisch ("Error").
# Die Fuellzeilen schieben sie aus den letzten 15 Zeilen heraus, sonst kaeme sie
# ueber das Ende mit und die Pruefung waere trivial wahr.
_fuell = "\n".join(f"  ok Zeile {_i}" for _i in range(40))
_aus = ci_mod._auszug(_fuell + "\nFEHLER: sudoers-Pruefung (visudo -cf) fehlgeschlagen\n" + _fuell)
check("CI-Auszug nimmt eine deutsche FEHLER-Zeile mit", "visudo -cf" in _aus, _aus[-200:])
check("…und nicht jede beliebige Zeile (sonst misst die Pruefung darueber nichts)",
      "ok Zeile 5" not in _aus)
# Eine Zusage, die ein GRUENER Waechter ausdruecklich nicht gemessen hat, muss in
# der Bilanz auftauchen. Bis 2026-11-20 verwarf ci_lauf die Ausgabe gruener
# Waechter restlos: im Lauf 00a0e81f war nicht zu sagen, ob der Laeufer ein
# taugliches visudo fand oder zwei Zusagen ungemessen blieben - beides Exit 0.
# Geprueft an den ECHTEN Ausgabeformen der vier Waechter, die das melden; eine
# erfundene Form wuerde nur die Pruefung bestaetigen, nicht die Wirklichkeit.
_formen = {
    "test_system_haertung.py": "NICHT GEPRUEFT: visudo -cf (visudo fehlt)",
    "test_excel_objekte.py": "  NICHT GEPRUEFT: backend.excel_ask nicht importierbar (ImportError())",
    # test_onenote_import faerbt und setzt den Marker MITTEN in die Zeile
    "test_onenote_import.py": "  \033[33m–\033[0m Seiten werden geholt  (NICHT GEPRUEFT: kein Zugang)",
}
for _w, _zeile in _formen.items():
    _gef = ci_mod._luecken(_w, "  OK   irgendwas\n" + _zeile + "\nErgebnis: 5 OK, 0 FAIL\n")
    check("CI-Bilanz hebt die nicht gemessene Zusage aus %s" % _w,
          len(_gef) == 1 and _gef[0][0] == _w and "NICHT GEPRUEFT" in _gef[0][1], _gef)
# Gegenkontrolle: klein geschriebenes "nicht geprueft" steht in Pruefnamen und
# Begruendungen – wuerde es mitzaehlen, meldete jeder Lauf Luecken, die keine
# sind, und der Abschnitt waere binnen Tagen Tapete.
check("…und nicht jede Zeile, die 'nicht geprueft' nur erwaehnt",
      ci_mod._luecken("x.py", "  OK   Grund wird genannt, nicht geprueft ist nicht bestanden\n") == [])
# Die Funktion allein genuegt nicht: sie muss im Sammellauf AUFGERUFEN werden
# und ihr Ergebnis in die Bilanz fliessen. Am Syntaxbaum gemessen, nicht am
# Text - ein Teilstring belegt keinen Aufruf (eine Pruefung, die nur _luecken()
# befragt, haette eine entfernte Sammelstelle nicht bemerkt).
_cibaum = ast.parse((ROOT / "tests" / "ci_lauf.py").read_text(encoding="utf-8"))
_main = next((k for k in _cibaum.body
              if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == "main"), None)
if _main is None:
    abbruch("tests/ci_lauf.py ohne main() – die Pruefungen darueber messen nichts")
check("Sammellauf ruft _luecken() auf",
      any(isinstance(c, ast.Call) and ast.unparse(c.func) == "_luecken" for c in ast.walk(_main)))
# Und die Bilanzzeile nennt die Zahl - sonst steht die Luecke nur in einem
# Abschnitt, den ein langer Lauf nach oben schiebt.
_bilanz = [c for c in ast.walk(_main) if isinstance(c, ast.Call)
           and ast.unparse(c.func) == "print" and "BILANZ" in ast.unparse(c)]
check("…und die Bilanzzeile nennt die nicht gemessenen Zusagen",
      bool(_bilanz) and all("luecken" in ast.unparse(c) for c in _bilanz), len(_bilanz))
tmpd = Path(tempfile.mkdtemp(prefix="jv_ci_"))
alt_a = ci_mod.AUSNAHMEN
try:
    for inhalt, titel in (("test_bsi_m6_m7.py\n", "Eintrag ohne Grund"),
                          ("test_gibt_es_nicht.py  # Grund\n", "Eintrag fuer fehlende Datei")):
        ci_mod.AUSNAHMEN = tmpd / "a.txt"
        ci_mod.AUSNAHMEN.write_text(inhalt)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ci_mod.ausnahmen_laden()
            rc = 0
        except SystemExit as e:
            rc = e.code
        check(f"ci_ausnahmen: {titel} -> Exit 2", rc == 2, rc)
finally:
    ci_mod.AUSNAHMEN = alt_a
    shutil.rmtree(tmpd, ignore_errors=True)

gli = [z.strip() for z in (ROOT / ".gitleaksignore").read_text().splitlines()
       if z.strip() and not z.startswith("#")]
# Commit-SHA optional: seit dem Neustart der Historie (2026-10-15) stehen die
# Eintraege als globaler Fingerabdruck datei:regel:zeile – die SHA-Form hing an
# Commits, die es nicht mehr gibt. gitleaks gleicht beide Formen ab.
_GLI = r"(?:[0-9a-f]{40}:)?[^:*]+:[a-z0-9-]+:\d+"
check(".gitleaksignore: nur Fingerabdruecke ([commit:]datei:regel:zeile), keine Pfad-Wildcards",
      bool(gli) and all(re.fullmatch(_GLI, z) for z in gli),
      [z for z in gli if not re.fullmatch(_GLI, z)][:3])

abschnitt("M6.5 Untergrenzen aus pip-audit")
try:
    from packaging.requirements import Requirement
    from packaging.version import Version
except ImportError:
    try:  # jede venv hat pip, und pip bringt packaging mit
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.version import Version
    except ImportError:
        abbruch("packaging fehlt")
reqs = {}
for z in (ROOT / "requirements.txt").read_text().splitlines():
    z = z.split("#", 1)[0].strip()
    if z:
        rq = Requirement(z)
        reqs[rq.name.lower()] = rq.specifier
for paket, unter in (("python-dotenv", "1.2.2"), ("mcp", "1.28.1"), ("starlette", "1.0.1")):
    spec = reqs.get(paket)
    # Eigenschaft: keine erlaubte Version liegt unter der Grenze
    zu_alt = [v for v in ("0.1", "1.0.0", "1.0.1", "1.2.1", "1.25.0", "1.28.0")
              if Version(v) < Version(unter) and spec is not None and spec.contains(v)]
    check(f"{paket}: nichts unter {unter} erlaubt", spec is not None and not zu_alt, (spec, zu_alt))
check("mcp: keine 2.x (zog im Probelauf ein pydantic-Beta nach)",
      reqs.get("mcp") is not None and not reqs["mcp"].contains("2.0.0"))
check("numpy bleibt < 2.1", reqs.get("numpy") is not None and not reqs["numpy"].contains("2.1.0"))

print("\n" + "=" * 60)
print(f"Ergebnis: {OK} OK, {FAIL} FAIL")
print("=" * 60)
sys.exit(1 if FAIL else 0)
