#!/usr/bin/env python3
"""Waechter: Skill-Module werden einmal ausgefuehrt, nicht je Agent (Code-Review 2026-10-18).

AUSGEFUEHRT an ``backend.skills.loader.SkillLoader`` gegen einen Wegwerf-Skill
in einem eigenen Verzeichnis (``SKILLS_DIR`` umgebogen). Das Modul zaehlt
jede Ausfuehrung in einer Datei:
  [1] zweimal laden (zwei Agenten) -> EINE Ausfuehrung, aber zwei getrennte
      Werkzeug-Instanzen, gemeinsamer Modulzustand
  [2] ``frisch=True`` fuehrt neu aus; eine geaenderte Datei ebenso
  [3] die Aufrufer: Aktivieren, Nach-Installation und reload_all laden frisch,
      der Agentenstart nicht (Syntaxbaum von manager.py)
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


try:
    from backend.skills import loader as L
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: loader nicht importierbar: %s" % e)
    sys.exit(2)

SK = Path(tempfile.mkdtemp(prefix="skill_cache_"))
ZAEHLER = SK / "zaehler.txt"
MODUL = '''from backend.tools.base import BaseTool
with open(%r, "a") as _f:
    _f.write("x")
GEMEINSAM = []


class ProbeTool(BaseTool):
    name = "cache_probe"
    description = "Probe %s"
    parameters_schema = {"type": "object", "properties": {}}

    async def execute(self, **kw):
        return "ok"
'''
try:
    d = SK / "cache_probe"
    d.mkdir()
    (d / "skill.json").write_text(json.dumps({"name": "cache_probe", "module": "main"}))
    (d / "main.py").write_text(MODUL % (str(ZAEHLER), "v1"))
    L.SKILLS_DIR = SK
    L._MODULE.clear()

    def laeufe():
        return len(ZAEHLER.read_text()) if ZAEHLER.exists() else 0

    print("\n[1] zwei Agenten")
    a = L.SkillLoader().load_skill("cache_probe")
    check("(Positivkontrolle) Skill geladen und einmal ausgefuehrt", len(a) == 1 and laeufe() == 1, str(laeufe()))
    if FAIL:
        print("ABBRUCH: Messaufbau traegt nicht")
        sys.exit(2)
    b = L.SkillLoader().load_skill("cache_probe")
    check("zweiter Agent: KEINE weitere Ausfuehrung", laeufe() == 1, str(laeufe()))
    check("... aber eine eigene Werkzeug-Instanz", a[0] is not b[0])
    check("... und gemeinsamer Modulzustand", sys.modules.get("x") is None
          and type(a[0]).__module__ == type(b[0]).__module__ and type(a[0]) is type(b[0]))

    print("\n[2] frisch und geaenderte Datei")
    L.SkillLoader().load_skill("cache_probe", frisch=True)
    check("frisch=True fuehrt neu aus", laeufe() == 2, str(laeufe()))
    time.sleep(0.01)
    (d / "main.py").write_text(MODUL % (str(ZAEHLER), "v2-laenger"))
    c = L.SkillLoader().load_skill("cache_probe")
    check("geaenderte Datei wird neu ausgefuehrt", laeufe() == 3 and "v2" in c[0].description,
          "%s %s" % (laeufe(), c[0].description))
finally:
    shutil.rmtree(SK, ignore_errors=True)

print("\n[3] Aufrufer in manager.py")
baum = ast.parse((ROOT / "backend" / "skills" / "manager.py").read_text(encoding="utf-8"))


def aufrufe_in(fn_name):
    fn = next((n for n in ast.walk(baum) if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
    if fn is None:
        return None
    return [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "load_skill"]


def frisch(c):
    return any(k.arg == "frisch" and isinstance(k.value, ast.Constant) and k.value.value is True for k in c.keywords)


en = aufrufe_in("enable_skill")
check("enable_skill laedt frisch", en and all(frisch(c) for c in en), str(len(en or [])))
inst = [c for c in ast.walk(baum) if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "load_skill"]
check("jede load_skill-Stelle ausser dem Agentenstart laedt frisch",
      sum(1 for c in inst if not frisch(c)) == 1, str([ast.unparse(c) for c in inst if not frisch(c)]))
ra = next((n for n in ast.walk(baum) if isinstance(n, ast.FunctionDef) and n.name == "reload_all"), None)
check("reload_all ruft _load_enabled_skills(frisch=True)",
      ra is not None and "_load_enabled_skills(frisch=True)" in ast.unparse(ra))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
