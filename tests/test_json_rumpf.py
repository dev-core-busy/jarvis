#!/usr/bin/env python3
"""Waechter: kein Endpunkt greift ungeprueft auf einen JSON-Rumpf zu.

Code-Review 2026-11-01: rund 150 Endpunkte in ``backend/main.py`` lasen
``x = await request.json()`` und griffen danach mit ``x.get``/``x[...]``/``**x``
zu. Ein Array, ein Skalar oder kaputtes JSON endete als 500 – oder, schlimmer,
wurde still als "nichts geaendert" gespeichert. Seitdem laeuft jeder Rumpf
durch ``_json_objekt`` (400 bei allem, was kein Objekt ist) oder wird an Ort
und Stelle mit ``isinstance(x, dict)`` geprueft.

REGEL am Syntaxbaum ueber ALLE Fundstellen (keine Liste):
jedes ``await request.json()``/``await req.json()`` in main.py steht
  (a) in ``_json_objekt`` selbst, oder
  (b) als Zuweisung an einen Namen, den DIESELBE Funktion mit
      ``isinstance(<name>, dict)`` prueft.
Alles andere ist ein Befund – auch ein ``.json()`` ohne Zuweisung
(``(await request.json()).get(...)``).

Positivkontrollen: die Sonde findet eine ungepruefte Stelle in einem
Probetext UND laesst die beiden erlaubten Formen durch – sonst waere "0
Befunde" trivial.

    python3 tests/test_json_rumpf.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


def _ist_json_await(n):
    return (isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "json"
            and not n.value.args
            and isinstance(n.value.func.value, ast.Name)
            and n.value.func.value.id in ("request", "req"))


def befunde(quelle: str):
    """(Fundstellen gesamt, [ungepruefte Fundstellen])."""
    baum = ast.parse(quelle)
    eltern = {}
    for p in ast.walk(baum):
        for k in ast.iter_child_nodes(p):
            eltern[k] = p
    gesamt, schlecht = 0, []
    for fn in ast.walk(baum):
        if not isinstance(fn, ast.AsyncFunctionDef):
            continue
        # Fundstellen GENAU dieser Funktion (verschachtelte gehoeren ihrer eigenen)
        def _eigene(knoten):
            for k in ast.iter_child_nodes(knoten):
                if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue
                yield k
                yield from _eigene(k)
        geprueft = {c.args[0].id for c in ast.walk(fn)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                    and c.func.id == "isinstance" and len(c.args) == 2
                    and isinstance(c.args[0], ast.Name)
                    and isinstance(c.args[1], ast.Name) and c.args[1].id == "dict"}
        for n in _eigene(fn):
            if not _ist_json_await(n):
                continue
            gesamt += 1
            if fn.name == "_json_objekt":
                continue
            zuw = eltern.get(n)
            if isinstance(zuw, ast.Assign) and len(zuw.targets) == 1 \
                    and isinstance(zuw.targets[0], ast.Name) and zuw.targets[0].id in geprueft:
                continue
            schlecht.append(f"{fn.name} (Zeile {n.lineno})")
    return gesamt, schlecht


# ─── 0. Positivkontrollen der Sonde ─────────────────────────────────────────
print("\n0. die Sonde selbst")
PROBE = '''
async def _json_objekt(req):
    body = await req.json()
    return body

async def gut_helfer(request):
    body = await _json_objekt(request)
    return body.get("x")

async def gut_vorort(request):
    body = await request.json()
    if not isinstance(body, dict):
        return 400
    return body.get("x")

async def schlecht_get(request):
    body = await request.json()
    return body.get("x")

async def schlecht_inline(req):
    return (await req.json()).get("x")

async def schlecht_fremde_pruefung(request):
    body = await request.json()
    other = {}
    if isinstance(other, dict):
        pass
    return body["x"]
'''
g, s = befunde(PROBE)
erwartet = {"schlecht_get", "schlecht_inline", "schlecht_fremde_pruefung"}
gefunden = {x.split(" ")[0] for x in s}
if gefunden != erwartet or g != 5:
    print(f"ABBRUCH: Sonde misst falsch (gesamt {g}, gefunden {sorted(gefunden)}).",
          file=sys.stderr)
    raise SystemExit(2)
check(True, "Sonde findet die drei ungeprueften Formen und laesst die zwei erlaubten durch")

# ─── 1. main.py ─────────────────────────────────────────────────────────────
print("\n1. backend/main.py")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
g, s = befunde(MAIN)
if g == 0:
    print("ABBRUCH: keine einzige Fundstelle in main.py – Sonde blind?", file=sys.stderr)
    raise SystemExit(2)
check("async def _json_objekt(" in MAIN and g >= 1, f"{g} Rumpf-Lesungen gefunden")
check(not s, f"keine ungepruefte Lesung ({len(s)}: {s[:6]})")
aufrufe = MAIN.count("await _json_objekt(")
check(aufrufe > 0, f"_json_objekt wird benutzt ({aufrufe} Aufrufe)")

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
