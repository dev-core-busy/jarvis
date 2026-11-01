#!/usr/bin/env python3
"""Waechter: die CVE-Endpunkte weisen einen falschen JSON-Rumpf mit 400 ab.

Code-Review 2026-11-01: ``/api/system/cve/quittieren`` und ``/einzeln``
endeten bei einem Skalar oder kaputtem JSON mit 500, und ``[]`` an
``/einstellungen`` wurde STILL als "nichts geaendert" gespeichert (Erfolg fuer
eine Eingabe, die nichts bewirkt).

Was festgehalten wird:

1. ``_json_objekt`` (aus main.py geschnitten und AUSGEFUEHRT): Objekt kommt
   durch; Array, Skalar, ``null`` und kaputtes JSON -> 400.
2. Die drei Endpunkte lesen ihren Rumpf NUR ueber ``_json_objekt`` (AST).
3. ``cve_pruefung.einstellungen_setzen`` weist ein Nicht-Objekt selbst ab.

    python3 tests/test_json_objekt.py
"""
import ast
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist bereits geladen.", file=sys.stderr)
    raise SystemExit(2)

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


BAUM = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
FN = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
if "_json_objekt" not in FN:
    print("ABBRUCH: _json_objekt nicht in main.py.", file=sys.stderr)
    raise SystemExit(2)


class _HTTPException(Exception):
    def __init__(self, status_code, detail=None):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class _Req:
    """Wie starlette: ``json()`` parst den Rohtext und wirft bei Unsinn
    ``json.JSONDecodeError`` (eine Unterklasse von ValueError)."""

    def __init__(self, roh):
        self.roh = roh

    async def json(self):
        return json.loads(self.roh)


ns = {"HTTPException": _HTTPException, "Request": object}
exec(compile(ast.Module(body=[FN["_json_objekt"]], type_ignores=[]), "main.py", "exec"), ns)


def _status(roh):
    try:
        return asyncio.run(ns["_json_objekt"](_Req(roh)))
    except _HTTPException as e:
        return e.status_code
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}"


# ─── 1. Wirkung ──────────────────────────────────────────────────────────────
print("\n1. _json_objekt")
erg = _status('{"ids": ["a"], "alle": false}')
if erg != {"ids": ["a"], "alle": False}:
    print(f"ABBRUCH: Positivkontrolle – ein Objekt kommt nicht durch ({erg!r}).", file=sys.stderr)
    raise SystemExit(2)
check(True, "Positivkontrolle: ein Objekt kommt unveraendert durch")
for roh, besch in (("[]", "Array"), ('"x"', "Skalar (String)"), ("42", "Zahl"),
                   ("null", "null"), ("{kaputt", "kein JSON"), ("", "leerer Rumpf")):
    check(_status(roh) == 400, f"{besch} -> 400 (bekommen: {_status(roh)!r})")

# ─── 2. Verdrahtung ──────────────────────────────────────────────────────────
print("\n2. die Endpunkte lesen nur ueber _json_objekt")
for name in ("system_cve_einzeln", "system_cve_quittieren", "system_cve_einstellungen"):
    fn = FN.get(name)
    if fn is None:
        check(False, f"{name} gefunden")
        continue
    aufrufe = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
    ueber = any(isinstance(c.func, ast.Name) and c.func.id == "_json_objekt" for c in aufrufe)
    roh = [ast.unparse(c) for c in aufrufe
           if isinstance(c.func, ast.Attribute) and c.func.attr == "json"]
    check(ueber and not roh, f"{name}: _json_objekt ja, req.json() direkt nein ({roh})")

# ─── 3. einstellungen_setzen ─────────────────────────────────────────────────
print("\n3. einstellungen_setzen weist ein Nicht-Objekt selbst ab")
try:
    from backend import cve_pruefung  # noqa: E402
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: cve_pruefung nicht ladbar: {e!r}", file=sys.stderr)
    raise SystemExit(2)
geschrieben = []
_echt = cve_pruefung._schreiben
cve_pruefung._schreiben = lambda *a, **k: geschrieben.append(a)
try:
    for wert in ([], "x", None):
        try:
            cve_pruefung.einstellungen_setzen(wert)
            check(False, f"{wert!r} -> ValueError")
        except ValueError:
            check(True, f"{wert!r} -> ValueError")
        except Exception as e:  # noqa: BLE001 – ein Absturz ist ein FAIL, kein Abbruch
            check(False, f"{wert!r} -> ValueError (bekommen: {type(e).__name__})")
    check(not geschrieben, "dabei wurde nichts geschrieben")
finally:
    cve_pruefung._schreiben = _echt

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
