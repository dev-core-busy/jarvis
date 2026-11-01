#!/usr/bin/env python3
"""Waechter: Aenderungsverlauf im Update-Popup (update_manager.commit_verlauf).

Gemeldet 2026-10-31: die Commit-Liste im Popup zeigt nur, was ein Update
BRINGT – auf einem aktuellen Server ist sie leer, die bisherigen Aenderungen
waren nirgends einsehbar. Der Verlauf listet die letzten Commits von
origin/<branch>, eingespielte UND ausstehende, mit Kennzeichen.

Gemessen mit echtem git an einem Wegwerf-Origin:
  1. Positivkontrolle: Server ist zwei Commits hinter Origin.
  2. Alle Commits gelistet (eingespielt + ausstehend), neueste zuerst.
  3. Kennzeichen "eingespielt" stimmt je Commit.
  4. Limit greift, Rest wird beziffert, Limit geklemmt.
  5. GitHub-Adresse nur fuer github.com, sonst leer.

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


TMP = Path(tempfile.mkdtemp(prefix="waechter-update-verlauf-"))
GENV = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@beispiel.de", GIT_COMMITTER_NAME="t",
            GIT_COMMITTER_EMAIL="t@beispiel.de", LC_ALL="C")


def sh(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, env=GENV, capture_output=True, text=True)


sys.path.insert(0, str(ROOT))
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules.setdefault("backend.config", _cfg)
os.environ.update({k: v for k, v in GENV.items() if k.startswith("GIT_") or k == "LC_ALL"})
from backend import update_manager as um  # noqa: E402

try:
    origin = TMP / "origin.git"
    sh(GIT, "init", "-q", "--bare", "-b", "master", str(origin))
    arbeit = TMP / "arbeit"
    sh(GIT, "clone", "-q", str(origin), str(arbeit))

    def commit(betreff, text=""):
        msg = betreff + ("\n\n" + text if text else "")
        if sh(GIT, "commit", "-q", "--allow-empty", "-m", msg, cwd=arbeit).returncode:
            abbruch("Commit gescheitert")
        if sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=arbeit).returncode:
            abbruch("Push ins Test-Origin gescheitert")

    commit("alt-1", "Kurz: Erster eingespielter Commit.")
    commit("alt-2", "Kurz: Zweiter eingespielter Commit.")
    server = TMP / "server"
    sh(GIT, "clone", "-q", str(origin), str(server))
    um.PROJECT_ROOT = server
    um.SIGNATUR_ANKER = TMP / "kein_anker"
    commit("neu-1", "Kurz: Erster ausstehender Commit.")
    commit("neu-2")

    # ─── 1. Positivkontrolle ────────────────────────────────────────────────
    st = um.check_update()       # holt origin (wie das Popup beim Oeffnen)
    if not (st.get("ok") and st.get("commits_behind") == 2):
        abbruch("Pruefstand stellt 'zwei hinter Origin' nicht her: %s" % str(st)[:300])
    check("Positivkontrolle: Server ist zwei Commits hinter Origin", True)

    # ─── 2. Alle Commits, neueste zuerst ────────────────────────────────────
    v = um.commit_verlauf(50)
    betr = [c.get("message") for c in v.get("commits") or []]
    check("ok", v.get("ok") is True, str(v)[:200])
    check("eingespielte UND ausstehende Commits gelistet",
          betr == ["neu-2", "neu-1", "alt-2", "alt-1"], str(betr))
    check("Quelle ist origin/master", v.get("ref") == "origin/master", repr(v.get("ref")))

    # ─── 3. Kennzeichen ─────────────────────────────────────────────────────
    ein = {c.get("message"): c.get("eingespielt") for c in v.get("commits") or []}
    check("ausstehende als nicht eingespielt markiert",
          ein.get("neu-2") is False and ein.get("neu-1") is False, str(ein))
    check("eingespielte als eingespielt markiert",
          ein.get("alt-2") is True and ein.get("alt-1") is True, str(ein))
    besch = {c.get("message"): c.get("beschreibung") for c in v.get("commits") or []}
    check("Kurzbeschreibung je Commit", besch.get("alt-1") == "Erster eingespielter Commit.",
          repr(besch.get("alt-1")))
    check("voller Hash fuer den Link",
          all(len(c.get("hash_voll", "")) == 40 for c in v.get("commits") or []))

    # ─── 4. Limit und Rest ──────────────────────────────────────────────────
    v2 = um.commit_verlauf(3)
    check("Limit greift", len(v2.get("commits") or []) == 3, str(len(v2.get("commits") or [])))
    check("Rest beziffert", v2.get("weitere") == 1, repr(v2.get("weitere")))
    check("Limit nach unten geklemmt (0 -> 1)",
          len(um.commit_verlauf(0).get("commits") or []) == 1)
    check("unsinniges Limit faellt auf die Vorgabe zurueck",
          um.commit_verlauf("x").get("ok") is True)

    # ─── 5. GitHub-Adresse ──────────────────────────────────────────────────
    check("lokale Ablage -> keine Web-Adresse", v.get("web") == "", repr(v.get("web")))
    for url, erwartet in [
        ("git@github.com:beispiel/projekt.git", "https://github.com/beispiel/projekt"),
        ("https://github.com/beispiel/projekt.git", "https://github.com/beispiel/projekt"),
        ("https://github.com/beispiel/projekt", "https://github.com/beispiel/projekt"),
        ("git@gitlab.beispiel.de:beispiel/projekt.git", ""),
    ]:
        sh(GIT, "remote", "set-url", "origin", url, cwd=server)
        check("Web-Adresse aus %s" % url, um._web_basis() == erwartet, repr(um._web_basis()))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
