#!/usr/bin/env python3
"""Waechter: eine Sitzungs-Kennung kann den Benutzerordner nicht verlassen (2026-10-07).

Befund aus dem Code-Review 2026-10-07: ``_safe`` liess reine Punktnamen stehen.
``POST /api/chat/sessions/delete {"ids":[".."]}`` zeigte damit auf
``data/chats`` selbst, ``_valid`` war wahr (der Ordner existiert immer), und
``shutil.rmtree`` loeschte die Chats ALLER Benutzer – die Antwort meldete dabei
sogar "failed", weil erst das abschliessende rmdir scheiterte.

Gemessen wird WIRKUNG am echten Modul ``backend.chat_sessions`` in einem
Wegwerf-Verzeichnis (``_ROOT`` umgebogen), nicht ein Vorkommen im Text:

  * Positivkontrolle: eine echte Sitzung laesst sich loeschen, die Messung
    sieht also eine Loeschung, wenn es eine gibt.
  * ``..``, ``.``, ``...`` u. a. loeschen NICHTS – fremde Sitzungen, der eigene
    Benutzerordner und ``preprompt.txt`` bleiben stehen.
  * Kein Lese-/Schreibweg nimmt eine Punkt-Kennung an.
  * Ein Symlink als Sitzungsordner zaehlt nicht als Sitzung (rmtree/Schreiben
    wuerden sonst dem Link folgen bzw. ihn als Sitzung behandeln).

    python3 tests/test_chat_sessions_traversal.py
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % label)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s%s" % (label, (" – %s" % detail) if detail else ""))


def abbruch(grund):
    """"Konnte nicht laufen" ist nicht "bestanden" – Exit 2."""
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


try:
    cs = importlib.import_module("backend.chat_sessions")
except Exception as e:  # noqa: BLE001
    abbruch("backend.chat_sessions nicht importierbar: %s" % e)

SANDKASTEN = Path(tempfile.mkdtemp(prefix="jv_chat_trav_"))
CHATS = SANDKASTEN / "data" / "chats"
DRAUSSEN = SANDKASTEN / "draussen"
cs._ROOT = CHATS

# Sandkasten-Waechter: ein Pfad aus dem echten Bestand waere ein Messfehler.
if not str(cs._user_dir("alice")).startswith(str(SANDKASTEN)):
    abbruch("_user_dir zeigt nicht in den Sandkasten: %s" % cs._user_dir("alice"))


def aufbauen():
    """Zwei Benutzer mit je einer Sitzung + preprompt, frisch je Abschnitt."""
    if CHATS.exists():
        shutil.rmtree(CHATS)
    if DRAUSSEN.exists():
        shutil.rmtree(DRAUSSEN)
    DRAUSSEN.mkdir(parents=True)
    (DRAUSSEN / "wichtig.txt").write_text("x", encoding="utf-8")
    sessions = {}
    for u in ("alice", "bob"):
        s = cs.create_session(u, "Probe " + u)
        sessions[u] = s["id"]
        cs.save_transcript(u, s["id"], [{"role": "user", "text": "hallo " + u}])
        cs.save_preprompt(u, "Vorgabe " + u)
    return sessions


def bestand_heil(sessions, label):
    for u, sid in sessions.items():
        check((cs._user_dir(u) / sid / "meta.json").is_file(),
              "%s: Sitzung von %s steht noch" % (label, u))
        check((cs._user_dir(u) / "preprompt.txt").is_file(),
              "%s: preprompt.txt von %s steht noch" % (label, u))
    check((DRAUSSEN / "wichtig.txt").is_file(), "%s: Datei ausserhalb steht noch" % label)


BOESE = ["..", ".", "...", " .. ", "./..", "../..", "..\\..", "/..", "%2E%2E", ""]

try:
    print("\n\033[1mPositivkontrolle\033[0m")
    sess = aufbauen()
    check(cs.get_meta("alice", sess["alice"]) is not None, "eigene Sitzung ist lesbar")
    check(cs.delete_session("alice", sess["alice"]) is True, "eigene Sitzung laesst sich loeschen")
    check(not (cs._user_dir("alice") / sess["alice"]).exists(), "danach ist ihr Ordner weg")
    if _fail:
        abbruch("Positivkontrolle gescheitert – die Messung saehe keine Loeschung")

    print("\n\033[1mLoeschen mit Punkt-/Traversal-Kennungen\033[0m")
    for boese in BOESE:
        sess = aufbauen()
        erg = cs.delete_session("alice", boese)
        check(erg is False, "delete_session(%r) meldet False" % boese, repr(erg))
        bestand_heil(sess, "nach delete(%r)" % boese)

    print("\n\033[1mLese-/Schreibwege nehmen keine Punkt-Kennung an\033[0m")
    sess = aufbauen()
    for boese in ("..", "."):
        check(cs.get_meta("alice", boese) is None, "get_meta(%r) ist None" % boese)
        check(cs.load_transcript("alice", boese) == [], "load_transcript(%r) ist leer" % boese)
        check(cs.load_context("alice", boese) == [], "load_context(%r) ist leer" % boese)
        check(cs.rename_session("alice", boese, "x") is None, "rename_session(%r) ist None" % boese)
        cs.save_transcript("alice", boese, [{"role": "user", "text": "boese"}])
        cs.save_context("alice", boese, [{"x": 1}])
    check(not (CHATS / "transcript.json").exists() and not (CHATS / "context.json").exists(),
          "nichts in data/chats geschrieben")
    check(not (cs._user_dir("alice") / "transcript.json").exists()
          and not (cs._user_dir("alice") / "context.json").exists(),
          "nichts in den Benutzerordner selbst geschrieben")
    bestand_heil(sess, "nach Lese-/Schreibversuchen")

    print("\n\033[1mSymlink als Sitzungsordner\033[0m")
    sess = aufbauen()
    link = cs._user_dir("alice") / "abc123def456"
    os.symlink(DRAUSSEN, link)
    (DRAUSSEN / "meta.json").write_text(json.dumps({"id": "abc123def456"}), encoding="utf-8")
    check(cs.get_meta("alice", "abc123def456") is None, "Symlink-Sitzung ist nicht lesbar")
    check(cs.delete_session("alice", "abc123def456") is False, "Symlink-Sitzung laesst sich nicht loeschen")
    check(DRAUSSEN.is_dir() and (DRAUSSEN / "wichtig.txt").is_file(), "Ziel des Symlinks steht noch")
    link.unlink()
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("\n" + "=" * 60)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
