#!/usr/bin/env python3
"""Waechter: kommt der Anfrage-Pfad aus ``_AnfragePfadMiddleware`` beim Endpunkt an?

Die AI-Maus-Sitzung (ohne 2FA, Betreiberentscheid 2026-10-27) gilt nur auf
ihren Pfaden; ``verify_token`` liest dafuer ``sitzung_token.ANFRAGE_PFAD``.
test_bsi_m3 setzt den Wert von Hand – ob er unter Starlette wirklich bis in
einen Endpunkt hinter ``@app.middleware("http")`` (BaseHTTPMiddleware) und bis
in einen SYNCHRONEN Endpunkt (Threadpool, Kontext-KOPIE) gelangt, misst nur
eine echte App. Ein leerer Wert hiesse: jede AI-Maus-Anfrage 401.

Die Middleware-Klasse kommt per AST aus main.py (kein Import: der echte
``backend.config`` schreibt die Live-settings.json).

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen (fastapi/httpx fehlen).
"""
from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(name: str, bed: bool, info="") -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL %s  [%s]" % (name, info))


try:
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: fastapi/httpx nicht verfuegbar (%s)" % e)
    sys.exit(2)

from backend import sitzung_token as ST  # noqa: E402

BAUM = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
klasse = next((n for n in BAUM.body if isinstance(n, ast.ClassDef)
               and n.name == "_AnfragePfadMiddleware"), None)
if klasse is None:
    print("ABBRUCH: _AnfragePfadMiddleware nicht in main.py")
    sys.exit(2)
NS = {"_sitzung": ST}
exec(compile(ast.fix_missing_locations(ast.Module(body=[klasse], type_ignores=[])),  # noqa: S102
             "main.py<auszug>", "exec"), NS)

app = FastAPI()


def _pfad_dep(request: Request) -> str:
    """Wie require_auth: eine Dependency, die den Wert liest."""
    return str(ST.ANFRAGE_PFAD.get())


@app.get("/api/ai-mouse/async")
async def ep_async(dep: str = Depends(_pfad_dep)):
    return {"ep": str(ST.ANFRAGE_PFAD.get()), "dep": dep}


@app.get("/api/ai-mouse/sync")
def ep_sync(dep: str = Depends(_pfad_dep)):
    return {"ep": str(ST.ANFRAGE_PFAD.get()), "dep": dep}


@app.middleware("http")
async def _innere_schicht(request: Request, call_next):
    """Steht fuer die @app.middleware-Schichten in main.py."""
    return await call_next(request)


# wie main.py: zuletzt registriert = aeusserste Schicht
app.add_middleware(NS["_AnfragePfadMiddleware"])

with TestClient(app) as c:
    for pfad in ("/api/ai-mouse/async", "/api/ai-mouse/sync"):
        r = c.get(pfad)
        d = r.json() if r.status_code == 200 else {}
        if r.status_code != 200:
            print("ABBRUCH: Positivkontrolle – %s antwortet %s" % (pfad, r.status_code))
            sys.exit(2)
        check("%s: Endpunkt sieht den Pfad" % pfad, d.get("ep") == pfad, d)
        check("%s: Dependency sieht den Pfad" % pfad, d.get("dep") == pfad, d)
check("ausserhalb einer Anfrage: kein Pfad (None)", ST.ANFRAGE_PFAD.get() is None)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
