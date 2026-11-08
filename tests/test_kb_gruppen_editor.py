#!/usr/bin/env python3
"""Waechter: Gruppen-Editoren duerfen fremde Dateien und Editoren nicht uebernehmen (Befund B5).

Gemessen an den ECHTEN Endpunkten ``knowledge_assignments_set``
(POST /api/knowledge/assignments) und ``knowledge_groups_update``
(PATCH /api/knowledge/groups/{gid}) samt ihren Schranken, per AST aus
``backend/main.py`` geschnitten und mit einer In-Memory-Gruppenablage
ausgefuehrt. Szenario: Benutzer ``ed`` ist Editor der Gruppe A, NICHT von B.

  * fremde Datei (nur B) an A haengen -> 403 (vorher erlaubt: danach konnte
    ``ed`` sie ueber DELETE /api/wissen/file loeschen);
  * Datei mit A+B: A entfernen -> 403; ungruppierte Datei an A -> 403;
  * eigene Datei (nur A): A entfernen/belassen -> erlaubt (Positivkontrolle);
  * PATCH: Editoren-Felder aendern -> 403, unveraendert mitgeschickt -> ok
    (der Dialog „Berechtigungen" schickt sie immer mit), Name aendern -> ok;
  * globaler Wissens-Editor: alles erlaubt.

Kein ``backend.config``. Exit 0 gruen, 1 FAIL, 2 konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
MAIN = ROOT / "backend" / "main.py"

try:
    from fastapi import HTTPException
except ImportError:
    print("ABBRUCH: fastapi fehlt", flush=True)
    sys.exit(2)

OK = FAIL = 0


def check(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


BAUM = ast.parse(MAIN.read_text(encoding="utf-8"))
FN = {"knowledge_assignments_set", "knowledge_groups_update", "_kb_editorfelder_schranke",
      "_kb_zuordnung_schranke", "_gruppen_normieren"}
VAR = {"_KB_EDITOR_FIELDS"}
teile, gef = [], set()
for k in BAUM.body:
    if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name in FN:
        k.decorator_list = []
        teile.append(k)
        gef.add(k.name)
    elif isinstance(k, ast.Assign) and any(isinstance(t, ast.Name) and t.id in VAR for t in k.targets):
        teile.append(k)
        gef.update(t.id for t in k.targets if isinstance(t, ast.Name))
if (FN | VAR) - gef:
    print("ABBRUCH: nicht gefunden: %s" % sorted((FN | VAR) - gef), flush=True)
    sys.exit(2)

# ── In-Memory-Gruppenablage ────────────────────────────────────────────────
GRUPPEN = {}
ZUORDNUNG = {}


def _reset():
    GRUPPEN.clear()
    GRUPPEN.update({
        "A": {"id": "A", "name": "Alpha", "editors_users": "ed", "editors_group": ""},
        "B": {"id": "B", "name": "Beta", "editors_users": "andere", "editors_group": ""},
    })
    ZUORDNUNG.clear()
    ZUORDNUNG.update({"data/rag/fremd.pdf": ["B"], "data/rag/eigen.pdf": ["A"],
                      "data/rag/beide.pdf": ["A", "B"], "data/rag/eigen2.pdf": ["A"]})


def _update_group(gid, **felder):
    if gid not in GRUPPEN:
        raise KeyError(gid)
    for k, v in felder.items():
        if v is not None:
            GRUPPEN[gid][k] = v
    return dict(GRUPPEN[gid])


kg = types.ModuleType("backend.knowledge_groups")
kg.get_group = lambda gid: GRUPPEN.get(gid)
kg.get_assignment = lambda p: list(ZUORDNUNG.get(p, []))
kg._rel = lambda p: p.lstrip("/")


def _set_assignment(p, groups):
    ZUORDNUNG[p] = list(groups)
    return list(groups)


kg.set_assignment = _set_assignment
kg.update_group = _update_group
sys.modules["backend.knowledge_groups"] = kg
sys.modules["backend.config"] = types.ModuleType("backend.config")

GLOBAL = {"chef"}


class JSONResponse:
    def __init__(self, content, status_code=200):
        self.content, self.status_code = content, status_code


AKTUELLER_RUMPF = {}


async def _json_objekt(req):
    return dict(AKTUELLER_RUMPF)


NS = {
    "HTTPException": HTTPException, "JSONResponse": JSONResponse, "Request": object,
    "Depends": lambda *a, **k: None, "require_auth": None,
    "_json_objekt": _json_objekt, "_aktivitaet": lambda *a, **k: None,
    "_wissen_schluessel_erlaubt": lambda p: True,
    "_may_edit_knowledge": lambda u: u in GLOBAL,
    "_is_kb_group_editor": lambda u, g: bool(g) and u in (g.get("editors_users") or "").split(","),
    "_can_edit_kb_group": lambda u, gid: u in GLOBAL or (
        bool(GRUPPEN.get(gid)) and u in (GRUPPEN[gid].get("editors_users") or "").split(",")),
    "asyncio": asyncio,
}
exec(compile(ast.Module(body=teile, type_ignores=[]), str(MAIN), "exec"), NS)


def zuordnen(user, pfad, gruppen):
    AKTUELLER_RUMPF.clear()
    AKTUELLER_RUMPF.update({"path": pfad, "groups": gruppen})
    try:
        r = asyncio.run(NS["knowledge_assignments_set"](request=None, user=user))
        return r.status_code
    except HTTPException as e:
        return e.status_code


def patchen(user, gid, rumpf):
    AKTUELLER_RUMPF.clear()
    AKTUELLER_RUMPF.update(rumpf)
    try:
        r = asyncio.run(NS["knowledge_groups_update"](gid=gid, request=None, user=user))
        return r.status_code
    except HTTPException as e:
        return e.status_code


# ── Positivkontrolle ─────────────────────────────────────────────────────
_reset()
st = zuordnen("ed", "data/rag/eigen.pdf", [])
if st != 200 or ZUORDNUNG["data/rag/eigen.pdf"] != []:
    print("ABBRUCH: Positivkontrolle – eigene Datei laesst sich nicht aendern (%s)" % st, flush=True)
    sys.exit(2)
check(True, "Positivkontrolle: Gruppen-Editor entfernt seine Gruppe von eigener Datei")

print("\n1. Zuordnung durch Gruppen-Editor")
_reset()
check(zuordnen("ed", "data/rag/fremd.pdf", ["B", "A"]) == 403
      and ZUORDNUNG["data/rag/fremd.pdf"] == ["B"],
      "eigene Gruppe an FREMDE Datei haengen -> 403, Zuordnung unveraendert")
check(zuordnen("ed", "data/rag/fremd.pdf", ["A"]) == 403, "fremde Gruppe ersetzen -> 403")
check(zuordnen("ed", "data/rag/beide.pdf", ["B"]) == 403
      and ZUORDNUNG["data/rag/beide.pdf"] == ["A", "B"],
      "Datei mit fremder Mitgruppe: eigene Gruppe entfernen -> 403")
check(zuordnen("ed", "data/rag/eigen.pdf", ["A", "B"]) == 403, "fremde Gruppe hinzufuegen -> 403")
check(zuordnen("ed", "data/rag/neu.pdf", ["A"]) == 403 and "data/rag/neu.pdf" not in ZUORDNUNG,
      "ungruppierte Datei an eigene Gruppe -> 403")
check(zuordnen("ed", "data/rag/beide.pdf", ["A", "B"]) == 200, "unveraendert absenden -> erlaubt")
check(zuordnen("ed", "data/rag/eigen2.pdf", ["A"]) == 200, "eigene Datei unveraendert -> erlaubt")

print("\n2. Globaler Wissens-Editor unberuehrt")
_reset()
check(zuordnen("chef", "data/rag/fremd.pdf", ["A", "B"]) == 200
      and ZUORDNUNG["data/rag/fremd.pdf"] == ["A", "B"], "fremde Datei umhaengen -> erlaubt")
check(zuordnen("chef", "data/rag/neu.pdf", ["A"]) == 200, "ungruppierte Datei zuordnen -> erlaubt")

print("\n3. PATCH Editoren-Felder")
_reset()
check(patchen("ed", "A", {"editors_users": "ed,komplize"}) == 403
      and GRUPPEN["A"]["editors_users"] == "ed", "Gruppen-Editor erweitert Editoren -> 403")
check(patchen("ed", "A", {"editors_group": "CN=Alle,OU=Gruppen"}) == 403
      and GRUPPEN["A"]["editors_group"] == "", "Gruppen-Editor setzt AD-Gruppe -> 403")
check(patchen("ed", "A", {"editors_users": " ed ", "editors_group": "", "name": "Alpha2"}) == 200
      and GRUPPEN["A"]["name"] == "Alpha2" and GRUPPEN["A"]["editors_users"] == "ed",
      "Dialog schickt unveraenderte Felder mit -> erlaubt, Name geaendert, Editoren bleiben")
check(patchen("ed", "B", {"name": "x"}) == 403, "fremde Gruppe -> 403 (Bestand)")
check(patchen("chef", "A", {"editors_users": "ed,neu"}) == 200
      and GRUPPEN["A"]["editors_users"] == "ed,neu", "globaler Editor aendert Editoren -> erlaubt")

print("\n" + "=" * 60)
print("  %d OK, %d FAIL" % (OK, FAIL))
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
