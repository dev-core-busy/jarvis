#!/usr/bin/env python3
"""Waechter: das App-Update spult nur vor – eine abweichende Historie wird abgelehnt.

Vorfall 2026-09-30 (ECHT): die Historie auf GitHub wurde neu geschrieben
(Echtwerte -> Platzhalter). ECHT stand 511 voraus / 513 hinterher; der
Merge-Pull haette in ueber 30 Dateien Konflikte hinterlassen – danach scheitert
jeder weitere Pull, und der Betreiber sieht es nicht.

Gemessen an der WIRKUNG mit echten Repositorys, echten SSH-Signaturen, echtem git:
  - Positivkontrolle: gut signierter Nachfolger -> vorgespult.
  - Umgeschriebene Historie (gut signiert, mit Konflikt): ok False,
    historie 'abweichend', HISTORIE_HINWEIS, HEAD unveraendert, KEIN MERGE_HEAD,
    kein Konflikteintrag, lokale Aenderung zurueckgespielt.

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


if not Path("/usr/bin/ssh-keygen").exists():
    abbruch("/usr/bin/ssh-keygen fehlt")

TMP = Path(tempfile.mkdtemp(prefix="waechter-update-ff-"))
GENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@x")


def sh(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, env=GENV, capture_output=True, text=True)


sh("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "gut", "-f", str(TMP / "gut"))
ANKER = TMP / "allowed_signers"
ANKER.write_text('rel namespaces="git" %s\n' % " ".join((TMP / "gut.pub").read_text().split()[:2]))


def commit(repo, msg):
    sh(GIT, "add", "-A", cwd=repo)
    r = sh(GIT, "-c", "gpg.format=ssh", "-c", "user.signingkey=%s.pub" % (TMP / "gut"),
           "commit", "-q", "--allow-empty", "-S", "-m", msg, cwd=repo)
    if r.returncode != 0:
        abbruch("commit %s: %s" % (msg, r.stderr[-300:]))


sys.path.insert(0, str(ROOT))
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)
os.environ.update({k: v for k, v in GENV.items() if k.startswith("GIT_")})
from backend import update_manager as um  # noqa: E402

origin = TMP / "origin.git"
sh(GIT, "init", "-q", "--bare", "-b", "master", str(origin))
arbeit = TMP / "arbeit"
sh(GIT, "clone", "-q", str(origin), str(arbeit))
(arbeit / "f").write_text("basis\n")
(arbeit / "lokal.txt").write_text("a\n")
commit(arbeit, "basis")
sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=arbeit)
server = TMP / "server"
sh(GIT, "clone", "-q", str(origin), str(server))
# Wie auf ECHT gemessen (2026-09-30): pull.rebase=false – ohne diese Zeile
# verweigert git (>= 2.33) den Merge von selbst, und der Waechter waere zahnlos.
sh(GIT, "config", "pull.rebase", "false", cwd=server)
um.PROJECT_ROOT = server
um.SIGNATUR_ANKER = ANKER


def head():
    return sh(GIT, "log", "-1", "--format=%s", cwd=server).stdout.strip()


# ─── Positivkontrolle: Vorspulen funktioniert ───────────────────────────────
(arbeit / "f").write_text("basis\nv2 echtwert\n")
commit(arbeit, "v2")
sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=arbeit)
r = um.apply_update()
if not (r.get("ok") is True and head() == "v2"):
    abbruch("Positivkontrolle: Vorspulen klappt nicht (%s, %s)" % (head(), str(r.get("error"))[:200]))
check("Positivkontrolle: gut signierter Nachfolger vorgespult", True)

# ─── Umgeschriebene Historie ────────────────────────────────────────────────
# Neu geschrieben ab "basis": v2 mit Platzhalter statt Echtwert, gut signiert.
sh(GIT, "reset", "-q", "--hard", "HEAD~1", cwd=arbeit)
(arbeit / "f").write_text("basis\nv2 platzhalter\n")
commit(arbeit, "v2-neu")
(arbeit / "f").write_text("basis\nv2 platzhalter\nv3\n")
commit(arbeit, "v3")
if sh(GIT, "push", "-q", "-f", "origin", "HEAD:master", cwd=arbeit).returncode != 0:
    abbruch("Force-Push ins Test-Origin gescheitert")
# Server hat daneben eine lokale (nicht committete) Aenderung.
(server / "lokal.txt").write_text("a\nlokal\n")

vorher = sh(GIT, "rev-parse", "HEAD", cwd=server).stdout.strip()
r = um.apply_update()
check("abweichende Historie: ok False", r.get("ok") is False, str(r)[:200])
check("... historie 'abweichend'", r.get("historie") == "abweichend", str(r.get("historie")))
check("... mit Hinweis", um.HISTORIE_HINWEIS in (r.get("error") or ""))
check("... HEAD unveraendert", sh(GIT, "rev-parse", "HEAD", cwd=server).stdout.strip() == vorher)
check("... kein halber Merge (MERGE_HEAD)", not (server / ".git" / "MERGE_HEAD").exists())
konflikte = [z for z in sh(GIT, "status", "--porcelain", cwd=server).stdout.splitlines()
             if z[:2] in ("UU", "AA", "DU", "UD", "AU", "UA", "DD")]
check("... kein Konflikteintrag im Index", not konflikte, str(konflikte))
check("... lokale Aenderung zurueckgespielt", (server / "lokal.txt").read_text() == "a\nlokal\n")

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
