#!/usr/bin/env python3
"""Waechter: fehlt kb_groups im Auftrag, gilt die Auswahl der SITZUNG.

Vorfall ECHT 2026-11-06 (gemeldet 2026-11-15): "Wiederholen"/"Bearbeiten" im
Chat schickten den Auftrag ohne ``kb_groups``; ein fehlendes Feld hiess "alle
Gruppen", und die Wissenssuche lieferte ein Dokument aus einer Gruppe, die in
der Sitzung abgewaehlt war. Das Frontend ist repariert
(``test_chat_wiederholen_auswahl_ui.js``); dieser Waechter haelt den
Rueckfall im Backend fest, der JEDEN Client schuetzt.

  1. ``chat_sessions.kb_groups_fuer_auftrag`` WIRKLICH ausgefuehrt, im
     Sandkasten (``_ROOT`` umgebogen, Exit 2 wenn nicht):
       - Feld da (Liste / null) -> die Nachricht entscheidet,
       - Feld fehlt -> gespeicherte Auswahl (der Vorfall), gesaeubert,
       - ohne Sitzung / ohne Eintrag / fremde Sitzung -> None (bisher),
       - Domaenenform des Namens findet dieselbe Sitzung.
  2. Regel am AST von ``main.py``: der WS-Handler holt ``kb_groups`` ueber
     diese Funktion (mit ``msg`` und ``chat_sid``), ``chat_sid`` ist davor
     zugewiesen, und es gibt kein ``msg.get("kb_groups")`` mehr.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""

import ast
import importlib
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
        print("  ✓ %s" % label)
    else:
        _fail += 1
        print("  ✗ %s%s" % (label, (" – %s" % detail) if detail else ""))


def abbruch(grund):
    print("\nABBRUCH: %s" % grund)
    sys.exit(2)


try:
    cs = importlib.import_module("backend.chat_sessions")
except Exception as e:  # noqa: BLE001
    abbruch("backend.chat_sessions nicht importierbar: %s" % e)
if not hasattr(cs, "kb_groups_fuer_auftrag"):
    abbruch("chat_sessions.kb_groups_fuer_auftrag fehlt")

SANDKASTEN = Path(tempfile.mkdtemp(prefix="jv_kb_rueckfall_"))
cs._ROOT = SANDKASTEN / "data" / "chats"
if not str(cs._user_dir("alice")).startswith(str(SANDKASTEN)):
    abbruch("_user_dir zeigt nicht in den Sandkasten: %s" % cs._user_dir("alice"))

f = cs.kb_groups_fuer_auftrag

try:
    print("\n1) Regel ausgefuehrt (Sandkasten)")
    sid = cs.create_session("alice", "Probe")["id"]
    leer_sid = cs.create_session("alice", "ohne Auswahl")["id"]
    cs.save_kb_groups("alice", sid, ["ibs", "nxis"])
    # Positivkontrolle: die Auswahl steht wirklich in den Metadaten.
    meta = cs.get_meta("alice", sid) or {}
    check(meta.get("kb_groups") == ["ibs", "nxis"], "Positivkontrolle: Auswahl ist gespeichert",
          repr(meta.get("kb_groups")))
    if _fail:
        abbruch("Messaufbau steht nicht")

    check(f("alice", sid, {"type": "task"}) == ["ibs", "nxis"],
          "Feld FEHLT -> gespeicherte Auswahl der Sitzung (der Vorfall)", repr(f("alice", sid, {"type": "task"})))
    check(f("alice", sid, {"kb_groups": None}) is None,
          "Feld = null -> alle (die Nachricht entscheidet, kein Rueckfall)", repr(f("alice", sid, {"kb_groups": None})))
    check(f("alice", sid, {"kb_groups": ["x"]}) == ["x"],
          "Feld = Liste -> genau diese Liste", repr(f("alice", sid, {"kb_groups": ["x"]})))
    check(f("alice", sid, {"kb_groups": []}) == [],
          "Feld = [] -> keine Gruppe")
    check(f("alice", sid, {"kb_groups": "ibs"}) is None,
          "Feld = Zeichenkette -> None (bisheriges Verhalten)")
    check(f("alice", "", {}) is None, "ohne Sitzung -> None")
    check(f("alice", leer_sid, {}) is None, "Sitzung ohne gespeicherte Auswahl -> None")
    check(f("alice", "gibtsnicht01", {}) is None, "unbekannte Sitzung -> None")
    check(f("bob", sid, {}) is None, "FREMDE Sitzung (anderer Benutzer) -> None, nicht deren Auswahl")
    check(f("firma\\alice", sid, {}) == ["ibs", "nxis"],
          "Domaenenform des Namens findet dieselbe Sitzung", repr(f("firma\\alice", sid, {})))

    cs.save_kb_groups("alice", sid, None)
    check(f("alice", sid, {}) is None, "gespeichert 'alle' (null) -> None")
    cs.save_kb_groups("alice", sid, [])
    check(f("alice", sid, {}) == [], "gespeichert 'keine' ([]) -> [] (kein Wissen)")
    cs.save_kb_groups("alice", sid, ["ibs", 7, " ", "ibs", None, " nxis "])
    check(f("alice", sid, {}) == ["ibs", "nxis"], "gespeicherte Liste wird gesaeubert",
          repr(f("alice", sid, {})))
    cs.save_kb_groups("alice", sid, "ibs")
    check(f("alice", sid, {}) is None, "gespeicherte Zeichenkette -> None (kein Raten)")
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("\n2) Regel am AST von main.py")
quelle = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(quelle)


def ist_msg_get_kb(n):
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "msg"
            and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "kb_groups")


def ist_rueckfall(n):
    return (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "kb_groups_fuer_auftrag")


aufrufe = []      # (funktion, aufruf)
for fn in ast.walk(baum):
    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for n in ast.walk(fn):
            if ist_rueckfall(n):
                aufrufe.append((fn, n))
# Geschachtelte Funktionen werden mehrfach durchlaufen – die innerste zaehlt.
innerst = {}
for fn, n in aufrufe:
    alt = innerst.get(id(n))
    if alt is None or (fn.lineno >= alt[0].lineno and fn.end_lineno <= alt[0].end_lineno):
        innerst[id(n)] = (fn, n)
aufrufe = list(innerst.values())

check(len(aufrufe) >= 1, "Positivkontrolle: der Rueckfall wird in main.py aufgerufen", str(len(aufrufe)))
check(not any(ist_msg_get_kb(n) for n in ast.walk(baum)),
      "kein msg.get(\"kb_groups\") mehr in main.py (sonst gibt es einen Weg ohne Rueckfall)")
for fn, n in aufrufe:
    args = [a.id if isinstance(a, ast.Name) else None for a in n.args]
    check(len(args) == 3 and args[1] == "chat_sid" and args[2] == "msg",
          "Aufruf in %s mit (…, chat_sid, msg)" % fn.name, repr(args))
    ziel_ok = False
    for st in ast.walk(fn):
        if isinstance(st, ast.Assign) and st.value is n:
            ziel_ok = any(isinstance(t, ast.Name) and t.id == "kb_groups" for t in st.targets)
    check(ziel_ok, "das Ergebnis wird kb_groups zugewiesen (%s)" % fn.name)
    davor = [st for st in ast.walk(fn) if isinstance(st, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == "chat_sid" for t in st.targets)
             and st.lineno < n.lineno]
    check(bool(davor), "chat_sid ist in %s VOR dem Aufruf zugewiesen" % fn.name)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
