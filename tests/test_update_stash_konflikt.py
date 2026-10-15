#!/usr/bin/env python3
"""Waechter: ein Konflikt beim Zurueckspielen lokaler Aenderungen blockiert kein Update.

Vorfall 2026-10-02 (ECHT): auf dem Server lagen von Hand eingespielte Dateien
(Vorab-Stand eines spaeteren Commits). Das App-Update stashte sie, spulte vor
und scheiterte beim `stash pop` an EINER Kommentarzeile. Zurueck blieb ein
ungeloester Eintrag im Index (`UU frontend/userchat.html`), das Update meldete
trotzdem Erfolg – und jedes weitere Update scheiterte mit "Pullen ist nicht
moeglich, weil Sie nicht zusammengefuehrte Dateien haben".

Gemessen an der WIRKUNG mit echten Repositorys und echtem git:
  1. Positivkontrolle: lokale Aenderung ohne Ueberschneidung -> vorgespult,
     zurueckgespielt, kein Stash, keine Nacharbeit.
  2. Konflikt beim Pop: ok True (der neue Stand IST eingespielt), nacharbeit
     nennt genau die Datei, Index ohne Konflikt, Datei = neuer Stand, lokale
     Fassung im Stash gesichert, die konfliktfreie Aenderung liegt weiter
     (ungestaged) im Arbeitsbaum – und das NAECHSTE Update laeuft durch.
  3. Altlast (Konflikt aus einem frueheren Lauf): ok False, konflikt nennt die
     Datei, KONFLIKT_HINWEIS, HEAD unveraendert, Stash nicht angefasst.

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


if not Path(GIT).exists():
    abbruch("git fehlt")

TMP = Path(tempfile.mkdtemp(prefix="waechter-update-stash-"))
GENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@x", LC_ALL="C")


def sh(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, env=GENV, capture_output=True, text=True)


def commit_push(repo, msg):
    sh(GIT, "add", "-A", cwd=repo)
    r = sh(GIT, "commit", "-q", "-m", msg, cwd=repo)
    if r.returncode != 0:
        abbruch("commit %s: %s" % (msg, r.stderr[-300:]))
    if sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=repo).returncode != 0:
        abbruch("push %s gescheitert" % msg)


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
(arbeit / "seite.html").write_text("kopf\n<!-- 3,6-MB-Bibliothek -->\n<script v=1>\nfuss\n")
(arbeit / "lokal.txt").write_text("a\n")
commit_push(arbeit, "basis")
server = TMP / "server"
sh(GIT, "clone", "-q", str(origin), str(server))
um.PROJECT_ROOT = server
um.SIGNATUR_ANKER = TMP / "kein-anker"          # ohne Anker: keine Signaturpruefung
if um._signatur_optionen():
    abbruch("Signaturpruefung trotz fehlendem Anker aktiv")


def head():
    return sh(GIT, "log", "-1", "--format=%s", cwd=server).stdout.strip()


def stashes():
    return [z for z in sh(GIT, "stash", "list", cwd=server).stdout.splitlines() if z.strip()]


def status():
    return sh(GIT, "status", "--porcelain", cwd=server).stdout.splitlines()


KONFLIKT = ("UU", "AA", "DU", "UD", "AU", "UA", "DD")

# ─── 1. Positivkontrolle: Stash/Pop ohne Ueberschneidung ────────────────────
(server / "lokal.txt").write_text("a\nlokal\n")
(arbeit / "seite.html").write_text("kopf\n<!-- 3,6-MB-Bibliothek -->\n<script v=1>\nfuss v2\n")
commit_push(arbeit, "v2")
r = um.apply_update()
if not (r.get("ok") is True and head() == "v2"):
    abbruch("Positivkontrolle: Vorspulen klappt nicht (%s, %s)" % (head(), str(r)[:300]))
check("Positivkontrolle: vorgespult", True)
check("... lokale Aenderung zurueckgespielt", (server / "lokal.txt").read_text() == "a\nlokal\n")
check("... kein Stash uebrig", not stashes(), str(stashes()))
check("... keine Nacharbeit gemeldet", "nacharbeit" not in r, str(r.get("nacharbeit")))

# ─── 2. Konflikt beim Pop (der Vorfall) ─────────────────────────────────────
# Server: Vorab-Stand von Hand eingespielt (Kommentar "2,7", Skript v=2).
(server / "seite.html").write_text("kopf\n<!-- 2,7-MB-Bibliothek -->\n<script v=2>\nfuss v2\n")
# Upstream: endgueltiger Commit (Kommentar "3,6" geaendert, Skript v=2).
(arbeit / "seite.html").write_text("kopf\n<!-- 3,6-MB-Bibliothek neu -->\n<script v=2>\nfuss v2\n")
commit_push(arbeit, "v3")
r = um.apply_update()
na = r.get("nacharbeit") or {}
check("Konflikt: ok True (neuer Stand ist eingespielt)", r.get("ok") is True, str(r)[:300])
check("... HEAD vorgespult", head() == "v3", head())
check("... Nacharbeit nennt genau die Datei", na.get("dateien") == ["seite.html"], str(na))
check("... Nacharbeit: lokale Fassung gesichert", na.get("gesichert") is True, str(na))
check("... Nacharbeit: nichts ungeloest", na.get("ungeloest") == [], str(na))
check("... Hinweis in der Ausgabe", um.NACHARBEIT_HINWEIS in (r.get("output") or ""))
konfl = [z for z in status() if z[:2] in KONFLIKT]
check("... KEIN Konflikteintrag im Index", not konfl, str(konfl))
check("... Datei = neuer Stand, ohne Konfliktmarker",
      (server / "seite.html").read_text() == (arbeit / "seite.html").read_text(),
      (server / "seite.html").read_text()[:120])
check("... genau ein Stash mit der lokalen Fassung", len(stashes()) == 1, str(stashes()))
gesichert = sh(GIT, "show", "stash@{0}:seite.html", cwd=server).stdout
check("... Stash enthaelt die lokale Fassung", "2,7-MB" in gesichert, gesichert[:120])
check("... konfliktfreie Aenderung liegt weiter im Arbeitsbaum",
      (server / "lokal.txt").read_text() == "a\nlokal\n")
check("... und ist NICHT gestaged (wie im Regelfall)",
      " M lokal.txt" in status(), str(status()))

# Das naechste Update laeuft durch (vorher scheiterte JEDES weitere).
(arbeit / "seite.html").write_text("kopf\n<!-- 3,6-MB-Bibliothek neu -->\n<script v=2>\nfuss v4\n")
commit_push(arbeit, "v4")
r = um.apply_update()
check("Folge-Update: ok True und vorgespult", r.get("ok") is True and head() == "v4",
      "%s %s" % (head(), str(r)[:200]))

# ─── 3. Altlast: ungeloester Konflikt aus einem frueheren Lauf ──────────────
# Genau der Zustand vom 2026-10-02 (altes Verhalten): stash, ff, pop mit Konflikt.
sh(GIT, "checkout", "-q", "--", ".", cwd=server)
sh(GIT, "stash", "clear", cwd=server)
(server / "seite.html").write_text("kopf\n<!-- lokal -->\n<script v=2>\nfuss v4\n")
sh(GIT, "stash", "push", "-q", "-m", "jarvis-auto-pre-update", cwd=server)
(arbeit / "seite.html").write_text("kopf\n<!-- upstream -->\n<script v=2>\nfuss v4\n")
commit_push(arbeit, "v5")
sh(GIT, "pull", "-q", "--ff-only", "origin", "master", cwd=server)
sh(GIT, "stash", "pop", cwd=server)
if not [z for z in status() if z[:2] in KONFLIKT]:
    abbruch("Altlast liess sich nicht herstellen: %s" % status())
(arbeit / "seite.html").write_text("kopf\n<!-- upstream -->\n<script v=2>\nfuss v6\n")
commit_push(arbeit, "v6")
vorher = head()
stash_vorher = stashes()
r = um.apply_update()
check("Altlast: ok False", r.get("ok") is False, str(r)[:200])
check("... konflikt nennt die Datei", r.get("konflikt") == ["seite.html"], str(r.get("konflikt")))
check("... mit Hinweis, was zu tun ist", um.KONFLIKT_HINWEIS in (r.get("error") or ""))
check("... HEAD unveraendert", head() == vorher, head())
check("... Stash nicht angefasst", stashes() == stash_vorher, str(stashes()))

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
