#!/usr/bin/env python3
"""Fehlende Pflichtangabe ist KEINE Zugriffssperre (Vorfall DEV 2026-10-26).

Das Modell wollte eine ganze CSV als `content` an `filesystem write` geben, die
Antwort lief ins max_tokens-Limit, und beim Aufruf kam nur `{"action": "write"}`
an. Die Pfadpruefung beurteilte den LEEREN Pfad, meldete "Schreiben ist nur im
Arbeitsbereich erlaubt" und protokollierte einen Sicherheitsverstoss.

Geprueft:
  1. `_pflicht_fehlt_grund` WIRKLICH ausgefuehrt, mit dem echten Schema von
     `FileSystemTool` – Grund nennt das Feld, sagt "keine Zugriffssperre" und
     den Weg; vollstaendige Aufrufe laufen durch.
  2. Am Syntaxbaum: in `_execute_tool` steht die Pruefung VOR jeder
     Zugriffspruefung (`authorize_fs`) und kehrt mit dem Grund zurueck.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
AGENT = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
BAUM = ast.parse(AGENT)
ok = fail = 0


def check(label, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {label}")
    else:
        fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH (Exit 2): {grund}")
    sys.exit(2)


fn = next((n for n in BAUM.body if isinstance(n, ast.FunctionDef)
           and n.name == "_pflicht_fehlt_grund"), None)
if fn is None:
    abbruch("_pflicht_fehlt_grund nicht in agent.py")
ns: dict = {}
exec(compile(ast.Module([fn], []), "agent_schnitt", "exec"), ns)
grund_fn = ns["_pflicht_fehlt_grund"]

try:
    from backend.tools.filesystem import FileSystemTool
except Exception as e:  # noqa: BLE001
    abbruch(f"FileSystemTool nicht importierbar: {e}")
fs = FileSystemTool()

print("\n0. Positivkontrolle: das echte Schema verlangt 'path'")
_req = fs.parameters_schema().get("required") or []
if "path" not in _req:
    abbruch(f"Schema von filesystem verlangt 'path' nicht mehr ({_req}) – Messung sinnlos")
check("filesystem: 'path' ist Pflicht", True)

print("\n1. Der Vorfall: nur {'action': 'write'} kommt an")
werkzeuge = {"filesystem": fs, "shell_execute": object()}
g = grund_fn(fs, "filesystem", {"action": "write"}, werkzeuge)
check("⚠ der Aufruf wird abgelehnt", isinstance(g, str) and bool(g), repr(g))
g = g or ""
check("der Grund nennt das fehlende Feld", "'path'" in g, g[:120])
check("⚠ der Grund sagt ausdruecklich: keine Zugriffssperre", "KEINE Zugriffssperre" in g)
check("⚠ die falsche Diagnose von vorher steht NICHT darin", "Arbeitsbereich" not in g)
check("der Grund nennt die Ursache (Laengenlimit)", "Laengenlimit" in g)
check("der Weg nennt shell_execute, wenn es verfuegbar ist", "shell_execute" in g)
g2 = grund_fn(fs, "filesystem", {"action": "write"}, {"filesystem": fs}) or ""
check("ohne shell_execute nennt der Weg es NICHT (Prompt ist Code)",
      "shell_execute" not in g2 and bool(g2), g2[-80:])
check("leerer String gilt als fehlend",
      bool(grund_fn(fs, "filesystem", {"action": "write", "path": ""}, werkzeuge)))

print("\n2. Vollstaendige Aufrufe laufen durch")
check("write mit Pfad", grund_fn(fs, "filesystem",
                                 {"action": "write", "path": "/tmp/x.csv", "content": "a"},
                                 werkzeuge) is None)
check("read mit Pfad (content ist optional)",
      grund_fn(fs, "filesystem", {"action": "read", "path": "/tmp/x"}, werkzeuge) is None)


class _OhneSchema:
    pass


class _KaputtesSchema:
    def parameters_schema(self):
        raise RuntimeError("x")


check("Werkzeug ohne Schema: keine Ablehnung", grund_fn(_OhneSchema(), "x", {}, {}) is None)
check("Schema wirft: keine Ablehnung (fail-open, die Werkzeugpruefung bleibt)",
      grund_fn(_KaputtesSchema(), "x", {}, {}) is None)

print("\n3. Reihenfolge im Dispatch (Syntaxbaum)")
ex = next((n for n in ast.walk(BAUM) if isinstance(n, ast.AsyncFunctionDef)
           and n.name == "_execute_tool"), None)
if ex is None:
    abbruch("_execute_tool nicht gefunden")


def _aufrufe(name):
    return [c for c in ast.walk(ex) if isinstance(c, ast.Call)
            and (getattr(c.func, "id", "") == name or getattr(c.func, "attr", "") == name)]


pf = _aufrufe("_pflicht_fehlt_grund")
az = _aufrufe("authorize_fs")
check("Positivkontrolle: authorize_fs wird in _execute_tool gerufen", bool(az))
check("⚠ _pflicht_fehlt_grund wird in _execute_tool gerufen", len(pf) == 1, str(len(pf)))
if pf and az:
    check("⚠ und zwar VOR jeder Zugriffspruefung",
          pf[0].lineno < min(c.lineno for c in az),
          f"Zeile {pf[0].lineno} gegen {min(c.lineno for c in az)}")
# Die Rueckgabe des Grundes: ein `return <name>` im If, dessen Test der Name ist,
# dem das Ergebnis zugewiesen wurde.
ziel = None
for a in ast.walk(ex):
    if (isinstance(a, ast.Assign) and isinstance(a.value, ast.Call)
            and getattr(a.value.func, "id", "") == "_pflicht_fehlt_grund"
            and isinstance(a.targets[0], ast.Name)):
        ziel = a.targets[0].id
kehrt = any(isinstance(i, ast.If) and isinstance(i.test, ast.Name) and i.test.id == ziel
            and any(isinstance(r, ast.Return) and isinstance(r.value, ast.Name)
                    and r.value.id == ziel for r in i.body)
            for i in ast.walk(ex)) if ziel else False
check("⚠ der Grund wird zurueckgegeben (nichts wird ausgefuehrt)", kehrt, str(ziel))

print("\n4. Geltungsbereich: filesystem ja, shell_execute NICHT")
# shell_execute deklariert `command` als Pflicht, nimmt aber auch nur `code` an –
# eine pauschale Pruefung haette diesen gueltigen Aufruf blockiert.
menge = None
for n in BAUM.body:
    if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == "_PFLICHT_VOR_FREIGABE"):
        menge = eval(compile(ast.Expression(n.value), "m", "eval"))  # noqa: S307
if menge is None:
    abbruch("_PFLICHT_VOR_FREIGABE nicht gefunden")
check("filesystem ist erfasst", "filesystem" in menge, str(sorted(menge)))
check("⚠ shell_execute ist NICHT erfasst (Aufruf nur mit code= ist gueltig)",
      "shell_execute" not in menge)
gate = [i for i in ast.walk(ex) if isinstance(i, ast.If)
        and any(c in pf for c in ast.walk(i))]
check("⚠ der Aufruf haengt an der Menge (nicht pauschal fuer alle Werkzeuge)",
      any("_PFLICHT_VOR_FREIGABE" in ast.unparse(i.test) for i in gate),
      [ast.unparse(i.test) for i in gate])

print(f"\nERGEBNIS: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
