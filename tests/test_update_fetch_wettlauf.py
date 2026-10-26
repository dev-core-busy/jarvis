#!/usr/bin/env python3
"""Waechter: Update-Pruefung und Update holen nicht gegeneinander.

Vorfall 2026-10-26 (ECHT): der Update-Knopf meldete
    "Schwerwiegend: Kann nicht zu mehreren Branches vorspulen."
der zweite Klick 11 s spaeter lief durch. Ursache: ``git fetch`` kuerzt
FETCH_HEAD zu Beginn und haengt am Ende an. Laufen zwei Fetches gleichzeitig
(Pruefung beim Oeffnen der Versions-Pill + Pull des Knopfs), stehen zwei
Merge-Zeilen darin, und ``pull --ff-only`` bricht ab.

Gemessen an der WIRKUNG mit echten Repositorys und echtem git:
  - Positivkontrolle: roher ``git fetch`` parallel zu ``git pull --ff-only``
    erzeugt den Fehler im Pruefstand (sonst Exit 2 - der Stand zeigt nichts).
  - check_update laesst FETCH_HEAD unberuehrt und erkennt trotzdem das Update.
  - check_update parallel zu einem fremden ``git pull`` (anderer Prozess,
    z.B. Auto-Update per Agent-Shell): kein Fehlschlag.
  - zwei apply_update parallel (zwei Reiter): kein Fehlschlag.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git") or "/usr/bin/git"
RUNDEN = 60
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


TMP = Path(tempfile.mkdtemp(prefix="waechter-update-wettlauf-"))
GENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@x", LC_ALL="C")


def sh(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, env=GENV, capture_output=True, text=True)


sys.path.insert(0, str(ROOT))
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)
os.environ.update({k: v for k, v in GENV.items() if k.startswith("GIT_") or k == "LC_ALL"})
from backend import update_manager as um  # noqa: E402

origin = TMP / "origin.git"
sh(GIT, "init", "-q", "--bare", "-b", "master", str(origin))
arbeit = TMP / "arbeit"
sh(GIT, "clone", "-q", str(origin), str(arbeit))
sh(GIT, "commit", "-q", "--allow-empty", "-m", "basis", cwd=arbeit)
sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=arbeit)
server = TMP / "server"
sh(GIT, "clone", "-q", str(origin), str(server))
um.PROJECT_ROOT = server
um.SIGNATUR_ANKER = TMP / "kein_anker"   # Herkunft ist hier nicht Gegenstand


def neuer_commit(msg):
    sh(GIT, "commit", "-q", "--allow-empty", "-m", msg, cwd=arbeit)
    if sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=arbeit).returncode != 0:
        abbruch("Push ins Test-Origin gescheitert")


def parallel(hintergrund, vordergrund):
    """Laesst ``hintergrund`` in Schleife laufen, solange ``vordergrund`` RUNDEN-mal
    laeuft. Liefert die Fehltexte des Vordergrunds."""
    stopp = threading.Event()

    def schleife():
        while not stopp.is_set():
            hintergrund()

    t = threading.Thread(target=schleife, daemon=True)
    t.start()
    fehler = []
    try:
        for _ in range(RUNDEN):
            f = vordergrund()
            if f:
                fehler.append(f)
    finally:
        stopp.set()
        t.join(timeout=60)
    return fehler


def roher_pull():
    r = sh(GIT, "pull", "-q", "--ff-only", "origin", "master", cwd=server)
    return (r.stderr or r.stdout or "rc %d" % r.returncode) if r.returncode else ""


# ─── Positivkontrolle: der Pruefstand zeigt den Wettlauf ────────────────────
fehler = parallel(lambda: sh(GIT, "fetch", "-q", "origin", "master", cwd=server), roher_pull)
if not any("multiple branches" in f for f in fehler):
    abbruch("Positivkontrolle: roher Parallel-Fetch erzeugt den Fehler nicht "
            "(%d/%d Fehlschlaege) - der Pruefstand kann nichts zeigen" % (len(fehler), RUNDEN))
check("Positivkontrolle: roher Parallel-Fetch bricht pull --ff-only (%d/%d)"
      % (len(fehler), RUNDEN), True)

# ─── check_update laesst FETCH_HEAD in Ruhe ─────────────────────────────────
neuer_commit("v2")
fh = server / ".git" / "FETCH_HEAD"
fh.write_text("waechter-marke\n")
r = um.check_update()
check("check_update erkennt das Update", r.get("ok") is True and r.get("has_update") is True,
      str(r)[:200])
check("check_update schreibt FETCH_HEAD nicht", fh.read_text() == "waechter-marke\n",
      fh.read_text()[:200])

# ─── Pruefung parallel zu einem fremden Pull (anderer Prozess) ──────────────
fehler = parallel(um.check_update, roher_pull)
check("check_update parallel zu fremdem git pull: kein Fehlschlag (%d/%d)"
      % (len(fehler), RUNDEN), not fehler, (fehler[:1] or [""])[0][:200])

# ─── Zwei Updates parallel (zwei Reiter) ────────────────────────────────────
neuer_commit("v3")


def update():
    r = um.apply_update()
    return "" if r.get("ok") else str(r.get("error"))[:300]


fehler = parallel(update, update)
check("zwei apply_update parallel: kein Fehlschlag (%d/%d)" % (len(fehler), RUNDEN),
      not fehler, (fehler[:1] or [""])[0])
check("... am Ende vorgespult", sh(GIT, "log", "-1", "--format=%s", cwd=server).stdout.strip()
      == "v3")

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
