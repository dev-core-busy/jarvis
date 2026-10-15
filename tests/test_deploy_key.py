#!/usr/bin/env python3
"""Waechter: Update-Wege fuer das PRIVATE Repository (Deploy Keys, 2026-09-30).

Das Repository ist seit 2026-09-30 privat; anonym per https scheitern das
App-Update (update_manager.py) und die root-eigene Broker-Kopie
(broker_installieren.sh, Befund K1). Gemessen an der WIRKUNG:

  [A] broker_installieren.sh laeuft ECHT (als Schein-root per ``unshare -r``,
      alles im Wegwerf-Verzeichnis, ``git`` als Attrappe, die Aufrufe und
      GIT_SSH_COMMAND mitschreibt):
      - https ohne Konfiguration (Positivkontrolle) installiert
      - SSH-REPO + Schluessel: fester Host-Anker, keine ssh_config, BatchMode,
        nur ed25519; Bestands-Cache wird auf die neue Adresse umgestellt
      - Port 443 ueber ssh.github.com
      - Schluessel zu offen / Link / fehlt, Anker fremd beschreibbar:
        Abbruch, BESTEHENDE Installation bleibt unberuehrt
      - eingeschleuste REPO-Zeile wird ignoriert
  [B] deploy_key_einrichten.sh baut fuer root DIESELBEN ssh-Optionen und
      traegt denselben Host-Schluessel wie deploy/security/github_known_hosts;
      dessen Fingerabdruck ist der von GitHub veroeffentlichte.
  [C] update_manager: ein Zugangsfehler bekommt den Deploy-Key-Hinweis und
      loest NICHT die Rechte-Diagnose aus.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INST = ROOT / "deploy" / "security" / "broker_installieren.sh"
EINR = ROOT / "deploy" / "security" / "deploy_key_einrichten.sh"
KH = ROOT / "deploy" / "security" / "github_known_hosts"
GITHUB_FP = "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"

OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + ((" – " + detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


for datei in (INST, EINR, KH):
    if not datei.exists():
        abbruch("%s fehlt" % datei)
if subprocess.run(["unshare", "-r", "true"], capture_output=True).returncode != 0:
    abbruch("unshare -r nicht verfuegbar (Schein-root fuer den Installer)")

TMP = Path(tempfile.mkdtemp(prefix="waechter-deploykey-"))

# git-Attrappe: schreibt jeden Aufruf samt GIT_SSH_COMMAND mit; clone legt einen
# Cache aus dem ECHTEN Baum an (der Installer laedt den Broker danach wirklich).
GIT = TMP / "bin" / "git"
GIT.parent.mkdir()
GIT.write_text(r"""#!/bin/bash
printf '%s\t%s\n' "${GIT_SSH_COMMAND:-}" "$*" >> "$PROBE_LOG"
if [ "$1" = "clone" ]; then
    ziel="${@: -1}"; mkdir -p "$ziel/.git"
    tar -C "$PROBE_SRC" --exclude=__pycache__ -cf - backend deploy start_jarvis_root.sh \
        jarvis.service | tar -C "$ziel" -xf -
    exit 0
fi
if [ "$1" = "-C" ] && [ "$3" = "rev-parse" ]; then echo 0123456789abcdef0123456789abcdef01234567; exit 0; fi
exit 0
""")
GIT.chmod(0o755)


def lauf(name, konf_zeilen=None, schluessel_modus=0o600, link=False, anker_modus=0o644,
         cache_da=False, ohne_schluessel=False):
    d = TMP / name
    (d / "etc").mkdir(parents=True)
    ziel, cache, log = d / "ziel", d / "cache", d / "git.log"
    key, anker = d / "etc" / "deploy_key", d / "etc" / "known"
    if not ohne_schluessel:
        if link:
            (d / "etc" / "echt_key").write_text("K")
            (d / "etc" / "echt_key").chmod(0o600)
            key.symlink_to(d / "etc" / "echt_key")
        else:
            key.write_text("K")
            key.chmod(schluessel_modus)
    anker.write_text(KH.read_text())
    anker.chmod(anker_modus)
    # bestehende Installation, die ein Abbruch NICHT anfassen darf
    ziel.mkdir()
    (ziel / "STAND").write_text('{"hash": "alt"}')
    if cache_da:
        (cache / ".git").mkdir(parents=True)
        subprocess.run("tar -C %s --exclude=__pycache__ -cf - backend deploy start_jarvis_root.sh "
                       "jarvis.service | tar -C %s -xf -" % (shlex.quote(str(ROOT)),
                                                                   shlex.quote(str(cache))),
                       shell=True, check=True)
    konf = d / "etc" / "broker.conf"
    if konf_zeilen is not None:
        konf.write_text("\n".join(z.replace("@KEY@", str(key)) for z in konf_zeilen) + "\n")
        konf.chmod(0o644)
    env = dict(os.environ, PATH="%s:%s" % (GIT.parent, os.environ.get("PATH", "")),
               PROBE_LOG=str(log), PROBE_SRC=str(ROOT),
               JARVIS_BROKER_INSTALL_DIR=str(ziel), JARVIS_BROKER_KONF=str(konf),
               JARVIS_BROKER_CACHE=str(cache), JARVIS_BROKER_KNOWN_HOSTS=str(anker),
               JARVIS_BROKER_ADMIN_BIN=str(d / "admin"),
               # Signaturpruefung (H1) hier AUS: die git-Attrappe hat keine
               # echten Commits; auf einem eingerichteten Server laege sonst der
               # echte Anker unter /etc/jarvis (test_signatur_h1.py prueft sie).
               JARVIS_BROKER_SIGNERS=str(d / "kein_anker"))
    r = subprocess.run(["unshare", "-r", "bash", str(INST), "--jarvis-dir", str(ROOT)],
                       env=env, capture_output=True, text=True, timeout=180)
    aufrufe = []
    if log.exists():
        for z in log.read_text().splitlines():
            ssh, _, args = z.partition("\t")
            aufrufe.append((ssh, args))
    stand = (ziel / "STAND").read_text() if (ziel / "STAND").exists() else ""
    return {"rc": r.returncode, "aus": r.stdout + r.stderr, "aufrufe": aufrufe,
            "stand": stand, "key": str(key), "anker": str(anker)}


def ssh_von(erg):
    return next((s for s, a in erg["aufrufe"] if ("fetch" in a or "clone" in a)), None)


print("[A] broker_installieren.sh")
a = lauf("https")
if a["rc"] != 0 or '"hash": "alt"' in a["stand"]:
    abbruch("Positivkontrolle: Installation ohne Konfiguration gelingt nicht (rc=%s)\n%s"
            % (a["rc"], a["aus"][-600:]))
check("https ohne Konfiguration: installiert (Positivkontrolle)", True)
check("https: clone von der https-Adresse",
      any(x[1].startswith("clone") and "https://github.com/dev-core-busy/jarvis.git" in x[1]
          for x in a["aufrufe"]))
check("https: kein GIT_SSH_COMMAND", ssh_von(a) == "")

SSH_KONF = ["QUELLE=github", "REPO=git@github.com:dev-core-busy/jarvis.git", "SCHLUESSEL=@KEY@"]
b = lauf("ssh", SSH_KONF, cache_da=True)
s = ssh_von(b) or ""
teile = shlex.split(s)
check("SSH: installiert", b["rc"] == 0, b["aus"][-300:])
check("SSH: Bestands-Cache auf neue Adresse umgestellt",
      any("remote set-url origin git@github.com:dev-core-busy/jarvis.git" in x[1] for x in b["aufrufe"]))
check("SSH: fetch geht ueber GIT_SSH_COMMAND", bool(s))
for opt in ("-F", "/dev/null", "-i", b["key"], "IdentitiesOnly=yes", "BatchMode=yes",
            "StrictHostKeyChecking=yes", "UserKnownHostsFile=" + b["anker"],
            "GlobalKnownHostsFile=/dev/null", "HostKeyAlias=github.com",
            "HostKeyAlgorithms=ssh-ed25519"):
    check("SSH-Option %s" % opt, opt in teile)
check("SSH: ohne 443-Schalter kein Umweg", "Port=443" not in teile)

c = lauf("ssh443", SSH_KONF + ["SSH_443=1"])
t443 = shlex.split(ssh_von(c) or "")
check("Port 443: ueber ssh.github.com", "HostName=ssh.github.com" in t443 and "Port=443" in t443)

for name, kw, grund in (
        ("key0640", {"schluessel_modus": 0o640}, "Schluessel gruppenlesbar"),
        ("keylink", {"link": True}, "Schluessel ist ein Link"),
        ("keyfehlt", {"ohne_schluessel": True}, "Schluessel fehlt"),
        ("anker0666", {"anker_modus": 0o666}, "Host-Anker fremd beschreibbar")):
    e = lauf(name, SSH_KONF, **kw)
    check("%s -> Abbruch, Bestand unberuehrt" % grund,
          e["rc"] == 1 and '"hash": "alt"' in e["stand"] and ssh_von(e) is None,
          "rc=%s" % e["rc"])
e = lauf("ohneschl", ["REPO=git@github.com:dev-core-busy/jarvis.git"])
check("SSH-REPO ohne SCHLUESSEL -> Abbruch", e["rc"] == 1 and '"hash": "alt"' in e["stand"])
e = lauf("injekt", ["REPO=git@github.com:a/b.git;touch /tmp/x", "SCHLUESSEL=@KEY@"])
check("eingeschleuste REPO-Zeile ignoriert (https-Vorgabe)",
      any(x[1].startswith("clone") and "https://github.com/dev-core-busy/jarvis.git" in x[1]
          for x in e["aufrufe"]))

print("[B] deploy_key_einrichten.sh")
src = EINR.read_text()
anfang = src.find("root_ssh() {")
ende = src.find("\n}\n", anfang)
if anfang < 0 or ende < 0:
    abbruch("root_ssh() nicht in deploy_key_einrichten.sh")
fn = src[anfang:ende + 3]
for p443, ref in (("0", teile), ("1", t443)):
    r = subprocess.run(["bash", "-c", fn + '\nroot_ssh "$1"', "_", p443], capture_output=True, text=True,
                       env=dict(os.environ, ROOT_KEY=b["key"] if p443 == "0" else c["key"],
                                KNOWN=b["anker"] if p443 == "0" else c["anker"]))
    check("root_ssh(%s) == Installer-Optionen" % p443,
          r.returncode == 0 and shlex.split(r.stdout.strip()) == ref,
          "%r vs %r" % (r.stdout.strip(), ref))
lit = next((z.split("=", 1)[1].strip('"') for z in src.splitlines() if z.startswith("GITHUB_HOSTKEY=")), "")
check("Host-Schluessel im Skript == github_known_hosts", lit == KH.read_text().strip())
fp = subprocess.run(["ssh-keygen", "-lf", str(KH)], capture_output=True, text=True).stdout
check("Fingerabdruck = von GitHub veroeffentlicht (%s)" % GITHUB_FP, GITHUB_FP in fp, fp.strip())
check("nur EIN Schluessel, nur ed25519",
      len(KH.read_text().split("\n")) == 2 and KH.read_text().split()[1] == "ssh-ed25519")

# ── core.sshCommand im Baum des Dienstbenutzers ───────────────────────────
# Bis zum 2026-10-11 stand in /opt/jarvis/.git/config von HAND der Schluessel
# von ROOT (/root/.ssh/jarvis_broker_deploy) - fuer `jarvis` absichtlich
# unlesbar. Jeder "runuser -u jarvis -- git fetch" warnte deshalb und gelang
# nur, weil ~/.ssh/config einsprang; ein stiller fetch-Fehler laesst den
# folgenden "reset --hard" gegen den ALTEN origin/master laufen und sieht wie
# ein Erfolg aus. Geprueft wird die EIGENSCHAFT: das Skript setzt
# core.sshCommand, und zwar auf den Schluessel des DIENSTBENUTZERS - kein Pfad
# unter /root. Das ist auch die K1-Richtung: .git/config ist fuer `jarvis`
# schreibbar, root darf daraus nie eine Identitaet beziehen.
zeilen = src.splitlines()
idx = next((i for i, z in enumerate(zeilen) if "git -C" in z and "core.sshCommand" in z), -1)
check("das Skript setzt core.sshCommand im Baum", idx >= 0)
# Der Wert steht in der Folgezeile (Zeilenfortsetzung) - ein Fenster von drei
# Zeilen, und KEIN .index()/[1] in der Pruefung: das wuerde WERFEN statt
# fehlzuschlagen, und die Gegenprobe saehe wie ein bestandener Lauf aus.
wert = " ".join(zeilen[idx:idx + 3]) if idx >= 0 else ""
check("... mit dem Schluessel des Dienstbenutzers ($K)", "-i $K" in wert, wert.strip()[:140])
check("... und KEINEM Pfad unter /root", "/root/" not in wert, wert.strip()[:140])
check("... Hostkey festgenagelt (StrictHostKeyChecking + eigene known_hosts)",
      "StrictHostKeyChecking=yes" in wert and "UserKnownHostsFile=" in wert, wert.strip()[:140])
# Und es muss als DIENSTBENUTZER laufen: ein `git config` als root macht
# .git/config root-eigen und legt den naechsten Abruf von `jarvis` lahm.
blockanfang = src.find('runuser -u "$SERVICE_USER" -- bash -s')
check("... gesetzt INNERHALB des runuser-Blocks (sonst .git/config root-eigen)",
      blockanfang >= 0 and idx >= 0 and src.find("core.sshCommand", blockanfang) > blockanfang)

print("[C] update_manager")
sys.path.insert(0, str(ROOT))
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)
from backend import update_manager as um  # noqa: E402

gerufen = []
um.diagnose_permissions = lambda *a, **k: gerufen.append(1) or {"ok": False, "hint": "RECHTE"}
m = um._mit_diagnose("git fetch fehlgeschlagen: x", "git@github.com: Permission denied (publickey).")
check("publickey -> Deploy-Key-Hinweis", um.ZUGANG_HINWEIS in m)
check("publickey -> KEINE Rechte-Diagnose", not gerufen and "RECHTE" not in m)
m = um._mit_diagnose("x", "fatal: could not read Username for 'https://github.com': terminal prompts disabled")
check("https ohne Zugang -> Deploy-Key-Hinweis", um.ZUGANG_HINWEIS in m)
gerufen.clear()
m = um._mit_diagnose("x", "error: unable to unlink old 'a': Permission denied")
check("echter Rechtefehler -> weiter Rechte-Diagnose (Positivkontrolle)", gerufen and "RECHTE" in m)

shutil.rmtree(TMP, ignore_errors=True)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
