#!/usr/bin/env python3
"""Waechter: Commit-Liste im Update-Popup – nur ausstehende Commits, je ein Satz.

Gewuenscht 2026-10-30: Administratoren sehen im Popup der Versions-Pill die
Commits, die ein Update bringt, mit je einem Satz Beschreibung. Quelle ist eine
Zeile ``Kurz: <Satz>`` im Commit-Text, sonst der erste Satz des ersten Absatzes.

Vorher stand dort ``git log origin/<branch> -5``: immer die letzten fuenf, also
auch schon eingespielte, und bei mehr als fuenf fehlte der Rest ohne Hinweis.

Gemessen mit echtem git an einem Wegwerf-Origin (Commits baut git selbst, nicht
der Test von Hand):
  1. Positivkontrolle: der Pruefstand stellt "Server hinter Origin" her.
  2. Nur HEAD..origin wird gelistet, neueste zuerst, nichts Eingespieltes.
  3. Beschreibung: Kurz-Zeile (auch umbrochen), Rueckfall erster Satz,
     Abkuerzungen, Aufzaehlung, nur Trailer -> leer, Laengendeckel.
  4. Betreff mit "|" bleibt ganz (die alte Zerlegung brach daran).
  5. Ueber MAX_COMMIT_LISTE hinaus: Liste gedeckelt, Rest beziffert.

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


TMP = Path(tempfile.mkdtemp(prefix="waechter-update-commitliste-"))
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
        r = sh(GIT, "commit", "-q", "--allow-empty", "-m", msg, cwd=arbeit)
        if r.returncode:
            abbruch("Commit gescheitert: " + r.stderr)
        if sh(GIT, "push", "-q", "origin", "HEAD:master", cwd=arbeit).returncode:
            abbruch("Push ins Test-Origin gescheitert")

    commit("alt: schon eingespielt", "Dieser Commit liegt auf dem Server bereits vor.")
    server = TMP / "server"
    sh(GIT, "clone", "-q", str(origin), str(server))
    um.PROJECT_ROOT = server
    um.SIGNATUR_ANKER = TMP / "kein_anker"   # Herkunft ist hier nicht Gegenstand

    TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    commit("feat(a): erster neuer",
           "Technischer Absatz, der NICHT angezeigt werden soll, weil es eine\n"
           "Kurz-Zeile gibt.\n\n"
           "Kurz: Administratoren sehen jetzt je Commit einen Satz,\n"
           "der auch ueber zwei Zeilen umbrechen darf.\n\n" + TRAILER)
    commit("fix(b): zweiter neuer",
           "Bisher zeigte die Liste z. B. auch alte Commits bzw. zu wenige an. "
           "Der zweite Satz gehoert nicht dazu.\n\n" + TRAILER)
    commit("fix(c): nur Trailer", TRAILER)
    commit("feat(d): Betreff | mit Strich",
           "- Aufzaehlung als erster Absatz. Danach mehr.")

    # ─── 1. Positivkontrolle ────────────────────────────────────────────────
    r = um.check_update()
    if not (r.get("ok") and r.get("has_update") and r.get("commits_behind") == 4):
        abbruch("Pruefstand stellt 'vier Commits hinter Origin' nicht her: %s" % str(r)[:300])
    check("Positivkontrolle: Server ist vier Commits hinter Origin", True)

    # ─── 2. Nur ausstehende Commits ─────────────────────────────────────────
    liste = r.get("recent_commits") or []
    betreffe = [c.get("message") for c in liste]
    check("genau die vier ausstehenden Commits gelistet", len(liste) == 4, str(betreffe))
    check("der schon eingespielte Commit fehlt",
          "alt: schon eingespielt" not in betreffe, str(betreffe))
    check("neueste zuerst",
          betreffe[:1] == ["feat(d): Betreff | mit Strich"]
          and betreffe[-1:] == ["feat(a): erster neuer"], str(betreffe))
    check("nichts weiter zu beziffern", r.get("commits_weitere") == 0,
          repr(r.get("commits_weitere")))
    besch = {c.get("message"): c.get("beschreibung") for c in liste}

    # ─── 3. Beschreibung ────────────────────────────────────────────────────
    check("Kurz-Zeile hat Vorrang, samt Fortsetzungszeile",
          besch.get("feat(a): erster neuer")
          == "Administratoren sehen jetzt je Commit einen Satz, der auch ueber "
             "zwei Zeilen umbrechen darf.",
          repr(besch.get("feat(a): erster neuer")))
    check("Rueckfall: erster Satz, Abkuerzungen beenden ihn nicht",
          besch.get("fix(b): zweiter neuer")
          == "Bisher zeigte die Liste z. B. auch alte Commits bzw. zu wenige an.",
          repr(besch.get("fix(b): zweiter neuer")))
    check("nur Trailer -> keine Beschreibung", besch.get("fix(c): nur Trailer") == "",
          repr(besch.get("fix(c): nur Trailer")))

    # ─── 4. Betreff mit Strich ──────────────────────────────────────────────
    check("Betreff mit '|' bleibt ganz", "feat(d): Betreff | mit Strich" in besch, str(betreffe))
    check("... und seine Beschreibung ohne Aufzaehlungszeichen",
          besch.get("feat(d): Betreff | mit Strich") == "Aufzaehlung als erster Absatz.",
          repr(besch.get("feat(d): Betreff | mit Strich")))
    check("jeder Eintrag traegt Hash, Datum, Autor",
          all(len(c.get("hash", "")) == 7 and c.get("date") and c.get("author") == "t"
              for c in liste) and len(liste) > 0, str(liste[:1]))

    # ─── 3b. Beschreibung, Einzelfaelle ohne git ────────────────────────────
    kb = um.kurzbeschreibung
    check("leerer Text -> leer", kb("") == "" and kb(None) == "")
    check("Kurz-Zeile endet vor einem Trailer ohne Leerzeile",
          kb("Kurz: Ein Satz.\n" + TRAILER) == "Ein Satz.", repr(kb("Kurz: Ein Satz.\n" + TRAILER)))
    check("leere Kurz-Zeile faellt auf den Rueckfall",
          kb("Kurz:\n\nDer erste Satz ist lang genug zum Zeigen. Zweiter.")
          == "Der erste Satz ist lang genug zum Zeigen.")
    check("'Gemeldet:' ist Fliesstext, kein Trailer",
          kb("Gemeldet: die Liste zeigte alte Eintraege an. Mehr.")
          == "Gemeldet: die Liste zeigte alte Eintraege an.")
    lang = "Wort " * 200
    erg = kb("Kurz: " + lang)
    check("ueberlanger Satz wird gedeckelt und als gekuerzt markiert",
          len(erg) <= um.MAX_BESCHREIBUNG + 2 and erg.endswith(" …"), "%d Zeichen" % len(erg))

    # ─── 5. Deckel + Rest beziffern ─────────────────────────────────────────
    zusaetzlich = um.MAX_COMMIT_LISTE + 3
    for i in range(zusaetzlich):
        commit("chore: Nummer %d" % i)
    r = um.check_update()
    gesamt = 4 + zusaetzlich
    if r.get("commits_behind") != gesamt:
        abbruch("Pruefstand: erwartet %d ausstehend, gemeldet %r" % (gesamt, r.get("commits_behind")))
    liste = r.get("recent_commits") or []
    check("Liste auf MAX_COMMIT_LISTE gedeckelt (%d)" % um.MAX_COMMIT_LISTE,
          len(liste) == um.MAX_COMMIT_LISTE, str(len(liste)))
    check("der Rest wird beziffert (%d)" % (gesamt - um.MAX_COMMIT_LISTE),
          r.get("commits_weitere") == gesamt - um.MAX_COMMIT_LISTE,
          repr(r.get("commits_weitere")))
    check("der neueste steht oben",
          liste[:1] and liste[0].get("message") == "chore: Nummer %d" % (zusaetzlich - 1),
          str(liste[:1]))
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print("\n%d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
