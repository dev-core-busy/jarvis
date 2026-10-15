#!/usr/bin/env python3
"""Waechter: BSI-Befund H1 – nur signierte Staende werden uebernommen.

Befund H1 (BSI-Abgleich 2026-09-29): das Update zog, was auf GitHub lag, ohne
die Herkunft zu pruefen; seit K1 holt ausserdem root die Broker-Kopie selbst von
master. Seit 2026-09-30 zaehlt nur eine Spitze, die mit einem Schluessel aus
/etc/jarvis/allowed_signers signiert ist. Gemessen an der WIRKUNG mit echten
Repositorys, echten SSH-Signaturen und echtem git:

  [A] broker_installieren.sh (Schein-root per ``unshare -r``; nur clone/fetch
      umgelenkt, alles andere echtes git): gut signiert -> installiert;
      unsigniert / fremder Schluessel / Anker fremd beschreibbar -> Abbruch,
      Bestand unberuehrt; ohne Anker -> installiert MIT Warnung.
  [B] update_manager gegen ein lokales Origin: apply_update lehnt unsigniert
      und fremd signiert ab (HEAD bleibt, Hinweis), nimmt gut signiert;
      check_update meldet die Signatur; ohne Anker altes Verhalten.
  [C] signatur_einrichten.sh verankert nichts ohne bzw. mit falschem
      Fingerabdruck und lehnt fremde Zeilenformen ab.
  [D] deploy/security/allowed_signers traegt genau den dokumentierten Schluessel.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INST = ROOT / "deploy" / "security" / "broker_installieren.sh"
EINR = ROOT / "deploy" / "security" / "signatur_einrichten.sh"
SIGNERS_REPO = ROOT / "deploy" / "security" / "allowed_signers"
FP_RELEASE = "SHA256:+z3tS1d4c7KKO/Fd/XcIzckaT/txQWxEwyrR0OSnv6w"
GIT = shutil.which("git") or "/usr/bin/git"

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


for datei in (INST, EINR, SIGNERS_REPO, Path("/usr/bin/ssh-keygen")):
    if not datei.exists():
        abbruch("%s fehlt" % datei)
if subprocess.run(["unshare", "-r", "true"], capture_output=True).returncode != 0:
    abbruch("unshare -r nicht verfuegbar")

TMP = Path(tempfile.mkdtemp(prefix="waechter-signatur-h1-"))


def sh(*a, cwd=None, env=None):
    return subprocess.run(list(a), cwd=cwd, env=env, capture_output=True, text=True)


for name in ("gut", "boese"):
    sh("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(TMP / name))
ANKER = TMP / "allowed_signers"
ANKER.write_text('rel namespaces="git" %s\n' % " ".join((TMP / "gut.pub").read_text().split()[:2]))
ANKER.chmod(0o644)
GENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@x")


def commit(repo, msg, schluessel=None):
    sh(GIT, "add", "-A", cwd=repo, env=GENV)
    arg = [GIT, "-c", "gpg.format=ssh"]
    if schluessel:
        arg += ["-c", "user.signingkey=%s.pub" % (TMP / schluessel)]
    arg += ["commit", "-q", "--allow-empty", "-m", msg] + (["-S"] if schluessel else ["--no-gpg-sign"])
    r = sh(*arg, cwd=repo, env=GENV)
    if r.returncode != 0:
        abbruch("commit %s: %s" % (msg, r.stderr[-300:]))


# ─── [A] Broker-Installer ────────────────────────────────────────────────────
print("[A] broker_installieren.sh")
QUELLEN = {}
for art, schl in (("gut", "gut"), ("unsigniert", None), ("fremd", "boese")):
    q = TMP / ("quelle_" + art)
    q.mkdir()
    sh(GIT, "init", "-q", "-b", "master", cwd=q, env=GENV)
    subprocess.run("tar -C %s --exclude=__pycache__ -cf - backend deploy start_jarvis_root.sh "
                   "jarvis.service | tar -C %s -xf -" % (ROOT, q), shell=True, check=True)
    commit(q, art, schl)
    QUELLEN[art] = q

WRAP = TMP / "bin" / "git"
WRAP.parent.mkdir()
WRAP.write_text("""#!/bin/bash
# clone/fetch aus dem vorbereiteten Repository, alles andere: echtes git
if [ "$1" = "clone" ]; then ziel="${@: -1}"; rm -rf "$ziel"; cp -a "$PROBE_QUELLE" "$ziel"; exit 0; fi
if [ "$1" = "-C" ] && [ "$3" = "fetch" ]; then exit 0; fi
if [ "$1" = "-C" ] && [ "$3" = "reset" ]; then exit 0; fi
exec %s "$@"
""" % GIT)
WRAP.chmod(0o755)


def installiere(name, quelle, anker=ANKER, anker_modus=None):
    d = TMP / ("inst_" + name)
    (d / "ziel").mkdir(parents=True)
    (d / "ziel" / "STAND").write_text('{"hash": "alt"}')
    a = d / "anker"
    if anker is not None:
        shutil.copy(anker, a)
        a.chmod(anker_modus or 0o644)
    env = dict(GENV, PATH="%s:%s" % (WRAP.parent, os.environ.get("PATH", "")),
               PROBE_QUELLE=str(quelle), JARVIS_BROKER_INSTALL_DIR=str(d / "ziel"),
               JARVIS_BROKER_KONF=str(d / "keine.conf"), JARVIS_BROKER_CACHE=str(d / "cache"),
               JARVIS_BROKER_KNOWN_HOSTS=str(d / "known"), JARVIS_BROKER_ADMIN_BIN=str(d / "admin"),
               JARVIS_BROKER_SIGNERS=str(a))
    r = subprocess.run(["unshare", "-r", "bash", str(INST), "--jarvis-dir", str(ROOT)],
                       env=env, capture_output=True, text=True, timeout=180)
    return r.returncode, r.stdout + r.stderr, (d / "ziel" / "STAND").read_text()


rc, aus, stand = installiere("gut", QUELLEN["gut"])
if rc != 0:
    abbruch("Positivkontrolle: gut signierter Stand installiert nicht (rc=%s)\n%s" % (rc, aus[-500:]))
check("gut signiert -> installiert (Positivkontrolle)", '"hash": "alt"' not in stand)
check("gut signiert -> 'Signatur geprueft' gemeldet", "Signatur geprueft" in aus)
for art in ("unsigniert", "fremd"):
    rc, aus, stand = installiere(art, QUELLEN[art])
    check("%s -> Abbruch, Bestand unberuehrt" % art,
          rc == 1 and '"hash": "alt"' in stand and "nicht mit einem zugelassenen" in aus, "rc=%s" % rc)
rc, aus, stand = installiere("anker0666", QUELLEN["gut"], anker_modus=0o666)
check("Anker fremd beschreibbar -> Abbruch", rc == 1 and '"hash": "alt"' in stand)
rc, aus, stand = installiere("ohneanker", QUELLEN["unsigniert"], anker=None)
check("ohne Anker -> installiert, aber mit Warnung",
      rc == 0 and '"hash": "alt"' not in stand and "Herkunft des Stands NICHT geprueft" in aus)

# ─── [B] App-Update ──────────────────────────────────────────────────────────
print("[B] update_manager")
sys.path.insert(0, str(ROOT))
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)
os.environ.update({k: v for k, v in GENV.items() if k.startswith("GIT_")})
from backend import update_manager as um  # noqa: E402

origin = TMP / "origin.git"
sh(GIT, "init", "-q", "--bare", "-b", "master", str(origin), env=GENV)
arbeit = TMP / "arbeit"
sh(GIT, "clone", "-q", str(origin), str(arbeit), env=GENV)
(arbeit / "f").write_text("1\n")
commit(arbeit, "basis", "gut")
sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=arbeit, env=GENV)
server = TMP / "server"
sh(GIT, "clone", "-q", str(origin), str(server), env=GENV)
um.PROJECT_ROOT = server
um.SIGNATUR_ANKER = ANKER


def veroeffentliche(msg, schl):
    (arbeit / "f").write_text((arbeit / "f").read_text() + msg + "\n")
    commit(arbeit, msg, schl)
    sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=arbeit, env=GENV)


def head():
    return sh(GIT, "log", "-1", "--format=%s", cwd=server, env=GENV).stdout.strip()


if head() != "basis":
    abbruch("Aufbau: Server-Klon steht nicht auf 'basis'")
veroeffentliche("unsigniert", None)
c = um.check_update()
check("check_update: unsignierte Spitze -> signatur 'fehlt'", c.get("signatur") == "fehlt", str(c.get("signatur")))
r = um.apply_update()
check("apply_update: unsigniert abgelehnt", r.get("ok") is False and r.get("signatur") == "fehlt")
check("... mit Hinweis", um.SIGNATUR_HINWEIS in (r.get("error") or ""))
check("... HEAD unveraendert", head() == "basis", head())
veroeffentliche("fremd", "boese")
r = um.apply_update()
check("apply_update: fremder Schluessel abgelehnt", r.get("ok") is False and head() == "basis", head())
veroeffentliche("gut", "gut")
c = um.check_update()
check("check_update: gut signierte Spitze -> 'ok'", c.get("signatur") == "ok", str(c.get("signatur")))
r = um.apply_update()
check("apply_update: gut signiert uebernommen (unsignierte darunter mitverbuergt)",
      r.get("ok") is True and head() == "gut", "%s %s" % (head(), r.get("error", "")[:120]))
um.SIGNATUR_ANKER = TMP / "gibt_es_nicht"
veroeffentliche("ohne-anker", None)
check("ohne Anker: signatur 'ungeprueft'", um.check_update().get("signatur") == "ungeprueft")
r = um.apply_update()
check("ohne Anker: altes Verhalten (unsigniert uebernommen)", r.get("ok") is True and head() == "ohne-anker")

# ─── [C] signatur_einrichten.sh ──────────────────────────────────────────────
print("[C] signatur_einrichten.sh")
kopie = TMP / "einr"
kopie.mkdir(mode=0o755)
shutil.copy(EINR, kopie / "signatur_einrichten.sh")
(kopie / "signatur_einrichten.sh").chmod(0o755)


def einrichten(*args, signers=None):
    ziel = TMP / ("ziel_%d" % len(list(TMP.glob("ziel_*"))))
    env = dict(os.environ, JARVIS_SIGNATUR_ANKER=str(ziel))
    a = ["unshare", "-r", "bash", str(kopie / "signatur_einrichten.sh"), "--jarvis-dir", "/nirgends"]
    if signers:
        a += ["--signers", str(signers)]
    r = subprocess.run(a + list(args), env=env, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr, ziel


rc, aus, ziel = einrichten(signers=ANKER)
check("ohne --fingerabdruck -> nichts verankert", rc == 1 and not ziel.exists())
rc, aus, ziel = einrichten("--fingerabdruck", "SHA256:falsch", signers=ANKER)
check("falscher Fingerabdruck -> nichts verankert", rc == 1 and not ziel.exists() and "nicht bestaetigt" in aus)
fp_gut = sh("ssh-keygen", "-lf", str(TMP / "gut.pub")).stdout.split()[1]
schraeg = TMP / "schraeg"
schraeg.write_text('rel namespaces="git",cert-authority %s\n' % " ".join((TMP / "gut.pub").read_text().split()[:2]))
rc, aus, ziel = einrichten("--fingerabdruck", fp_gut, signers=schraeg)
check("Zeile mit Zusatzoption -> nichts verankert", rc == 1 and not ziel.exists() and "unerwartete Zeile" in aus)
rc, aus, ziel = einrichten("--fingerabdruck", fp_gut, signers=ANKER)
check("richtiger Fingerabdruck -> Anker geschrieben (Positivkontrolle)",
      ziel.exists() and ziel.read_text().strip() == ANKER.read_text().strip(), aus[-200:])

# ─── [D] Schluesselliste im Repository ───────────────────────────────────────
print("[D] deploy/security/allowed_signers")
zeilen = [z for z in SIGNERS_REPO.read_text().splitlines() if z and not z.startswith("#")]
check("genau eine Schluesselzeile", len(zeilen) == 1)
fp = sh("bash", "-c", "ssh-keygen -lf <(cut -d' ' -f3,4 %s | grep -v '^$' | grep -v '^#')" % SIGNERS_REPO).stdout
fp2 = [z for z in fp.splitlines() if "ED25519" in z]
check("Fingerabdruck = dokumentierter Release-Schluessel", len(fp2) == 1 and FP_RELEASE in fp2[0], fp.strip())

shutil.rmtree(TMP, ignore_errors=True)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
