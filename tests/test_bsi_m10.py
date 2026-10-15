#!/usr/bin/env python3
"""Waechter BSI M10 – Deny-by-default fuer alle Routen.

  [A] REGEL (AST ueber backend/main.py + webdav.py): jede Route traegt eine
      Anmelde-Dependency (``Depends(require_*)``) ODER steht in
      ``zugang_regel.AUSNAHMEN``; jede Ausnahme hat eine Route (keine Leichen);
      Ausnahmen der Art ``selbst`` rufen im Rumpf eine Pruefung auf.
  [B] WIRKUNG der Middleware an einer echten FastAPI-App: Route ohne Regel
      verlangt eine Anmeldung (401 ohne, 200 mit, 403 bei Sperre), Ausnahme und
      Dependency-Route bleiben unberuehrt, WebSocket ohne Regel wird
      geschlossen, unbekannte Pfade bleiben 404, HEAD gilt wie GET.
  [C] Verdrahtung in main.py: Middleware INNEN (nach Cookie-Zusammensetzen,
      hinter CORS), Pruefung = require_auth.
  [D] ``zustand()``: zaehlt und nennt Routen ohne Regel und verwaiste Ausnahmen.
  [E] Vision-Stream: kein fester Vorgabeschluessel mehr (Rumpf ausgefuehrt).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

try:
    import fastapi  # noqa: F401
    from fastapi.testclient import TestClient  # noqa: F401
except ImportError:
    venv_py = ROOT / "venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), __file__] + sys.argv[1:])
    print("ABBRUCH: fastapi fehlt (venv/bin/python tests/test_bsi_m10.py)")
    sys.exit(2)

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:400] + "]") if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


from backend import zugang_regel as zr  # noqa: E402

MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[A] Regel ueber alle Routen")
VERBEN = {"get": "GET", "post": "POST", "put": "PUT", "delete": "DELETE", "patch": "PATCH"}
ANMELDE = {n.name for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and n.name.startswith("require_")}
if len(ANMELDE) < 10:
    abbruch("nur %d require_*-Funktionen gefunden" % len(ANMELDE))

# Pfad-Konstanten aus anderen Modulen, die als Dekorator-Argument stehen
KONST = {"_csp.MELDE_PFAD": None}
try:
    from backend import csp as _csp_mod  # noqa: E402
    KONST["_csp.MELDE_PFAD"] = _csp_mod.MELDE_PFAD
except Exception as e:  # noqa: BLE001
    abbruch("backend.csp nicht ladbar: %s" % e)


def _pfad(arg):
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return KONST.get(ast.unparse(arg))


routen = []          # (schluessel, funktion, hat_dependency)
unlesbar = []
for fn in ast.walk(BAUM):
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for d in fn.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"):
            continue
        art = d.func.attr
        if art not in VERBEN and art != "websocket":
            continue
        pfad = _pfad(d.args[0]) if d.args else None
        if pfad is None:
            unlesbar.append(fn.name)
            continue
        deps = [ast.unparse(x.args[0]) for x in (fn.args.defaults + fn.args.kw_defaults)
                if isinstance(x, ast.Call) and getattr(x.func, "id", "") == "Depends" and x.args]
        for kw in d.keywords:
            if kw.arg == "dependencies":
                deps += [ast.unparse(e.args[0]) for e in getattr(kw.value, "elts", [])
                         if isinstance(e, ast.Call) and e.args]
        hat = any(x in ANMELDE for x in deps)
        schl = ("WS", pfad) if art == "websocket" else (VERBEN[art], pfad)
        routen.append((schl, fn, hat))
# app.mount("…") in main.py und webdav.py
MOUNTS = set()
for q in (MAIN, (ROOT / "backend" / "webdav.py").read_text(encoding="utf-8")):
    for n in ast.walk(ast.parse(q)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "mount" \
                and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) \
                and n.args[0].value.startswith("/"):
            MOUNTS.add(("MOUNT", n.args[0].value))

check("alle Routen-Pfade lesbar", not unlesbar, unlesbar)
if len(routen) < 300:
    abbruch("nur %d Routen gefunden – Erkennung blind?" % len(routen))
print("  (%d Routen, %d Mounts, %d Anmelde-Dependencies)" % (len(routen), len(MOUNTS), len(ANMELDE)))

ohne = sorted("%s %s" % s for s, fn, hat in routen if not hat and s not in zr.AUSNAHMEN)
ohne += sorted("%s %s" % m for m in MOUNTS if m not in zr.AUSNAHMEN)
check("jede Route: Anmelde-Dependency ODER begruendete Ausnahme", not ohne, ohne)

alle = {s for s, _, _ in routen} | MOUNTS
leichen = sorted("%s %s" % k for k in zr.AUSNAHMEN if k not in alle)
check("keine Ausnahme ohne Route", not leichen, leichen)
doppelt = sorted("%s %s" % s for s, fn, hat in routen if hat and s in zr.AUSNAHMEN)
check("keine Ausnahme fuer eine Route, die schon eine Dependency hat", not doppelt, doppelt)
check("jede Ausnahme hat Art und Grund",
      all(a in zr.ARTEN and len(g) >= 8 for a, g in zr.AUSNAHMEN.values()),
      [k for k, (a, g) in zr.AUSNAHMEN.items() if a not in zr.ARTEN or len(g) < 8])

PRUEF_AUFRUFE = {"verify_token", "_verify_agent_api_key", "_is_valid_agent_key", "_pull_share",
                 "einloesen", "_token_aufloesen", "compare_digest", "_ws_auth", "_verify_ws_token"}
nach_schl = {s: fn for s, fn, _ in routen}
MODUL_FN = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _gerufen(fn):
    return {(c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", ""))
            for c in ast.walk(fn) if isinstance(c, ast.Call)}


selbst_ohne = []
for k, (art, _g) in zr.AUSNAHMEN.items():
    if art != "selbst" or k[0] == "MOUNT":
        continue
    fn = nach_schl.get(k)
    if fn is None:
        continue
    namen = _gerufen(fn)
    # eine Ebene tiefer: /ws prueft in handle_ws_message, nicht im Handler selbst
    for n in list(namen):
        if n in MODUL_FN and n != fn.name:
            namen |= _gerufen(MODUL_FN[n])
    lokal = any(isinstance(c, ast.Constant) and c.value == "127.0.0.1" for c in ast.walk(fn))
    if not (namen & PRUEF_AUFRUFE or lokal):
        selbst_ohne.append("%s %s (%s)" % (k[0], k[1], fn.name))
check("Art 'selbst': jeder Rumpf ruft eine Pruefung auf", not selbst_ohne, selbst_ohne)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[B] Wirkung der Middleware")
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.staticfiles import StaticFiles  # noqa: E402
import tempfile  # noqa: E402

GESPERRT = {"gesperrt"}


async def require_probe(request: Request) -> str:
    t = request.headers.get("Authorization", "").replace("Bearer ", "")
    if t not in ("gut", "gesperrt"):
        raise HTTPException(401, "Nicht authentifiziert")
    if t in GESPERRT:
        raise HTTPException(403, "ACCOUNT_BLOCKED")
    return t


async def require_probe_schluessel(request: Request) -> str:
    """Anderer Nachweis als die Sitzung (wie require_claudesub_key/_or_agent)."""
    if request.headers.get("X-Key") != "k":
        raise HTTPException(401, "Schluessel fehlt")
    return "api"


probe = FastAPI()
probe.add_middleware(zr.ZugangsMiddleware,
                     anmelde_funktionen=lambda: {require_probe, require_probe_schluessel},
                     pruefen=require_probe)


@probe.get("/per_schluessel")
async def _per_schluessel(u: str = Depends(require_probe_schluessel)):
    return {"ok": u}


@probe.get("/frei")
async def _frei():
    return {"ok": "frei"}


@probe.get("/geschuetzt")
async def _gesch(u: str = Depends(require_probe)):
    return {"ok": u}


@probe.get("/vergessen")
async def _verg():
    return {"ok": "vergessen"}


@probe.post("/vergessen_post")
async def _verg_post(request: Request):
    return {"ok": (await request.json()).get("x")}


@probe.websocket("/ws_frei")
async def _wsf(ws: WebSocket):
    await ws.accept()
    await ws.send_text("hallo")
    await ws.close()


@probe.websocket("/ws_vergessen")
async def _wsv(ws: WebSocket):
    await ws.accept()
    await ws.send_text("durch")
    await ws.close()


_stat = Path(tempfile.mkdtemp(prefix="m10_"))
(_stat / "a.txt").write_text("statisch")
probe.mount("/stat", StaticFiles(directory=str(_stat)))

_alt = dict(zr.AUSNAHMEN)
zr.AUSNAHMEN.clear()
zr.AUSNAHMEN.update({("GET", "/frei"): ("oeffentlich", "Probe ohne Schutz"),
                     ("WS", "/ws_frei"): ("selbst", "Probe-WebSocket"),
                     ("MOUNT", "/stat"): ("seite", "Probe-Dateien")})
try:
    c = TestClient(probe)
    r = c.get("/frei")
    check("Ausnahme: ohne Anmeldung 200 (Positivkontrolle)", r.status_code == 200, r.status_code)
    check("Dependency-Route ohne Token: 401 (von der Dependency)", c.get("/geschuetzt").status_code == 401)
    check("Dependency-Route mit Token: 200",
          c.get("/geschuetzt", headers={"Authorization": "Bearer gut"}).status_code == 200)
    r = c.get("/per_schluessel", headers={"X-Key": "k"})
    check("Dependency mit ANDEREM Nachweis (Schluessel): Middleware laesst sie selbst pruefen (200)",
          r.status_code == 200, (r.status_code, r.text))
    r = c.get("/vergessen")
    check("⚠ Route OHNE Regel ohne Anmeldung: 401", r.status_code == 401, (r.status_code, r.text))
    r = c.get("/vergessen", headers={"Authorization": "Bearer gut"})
    check("Route ohne Regel MIT Anmeldung: funktioniert (200)", r.status_code == 200
          and r.json().get("ok") == "vergessen", (r.status_code, r.text))
    r = c.get("/vergessen", headers={"Authorization": "Bearer gesperrt"})
    check("Route ohne Regel, gesperrtes Konto: 403 wie require_auth", r.status_code == 403, r.status_code)
    r = c.post("/vergessen_post", json={"x": 7}, headers={"Authorization": "Bearer gut"})
    check("Rumpf kommt nach der Pruefung unversehrt an", r.status_code == 200 and r.json().get("ok") == 7,
          (r.status_code, r.text))
    check("unbekannter Pfad bleibt 404", c.get("/gibtsnicht").status_code == 404)
    check("Mount mit Ausnahme: 200", c.get("/stat/a.txt").status_code == 200)
    with c.websocket_connect("/ws_frei") as ws:
        check("WebSocket mit Ausnahme: angenommen", ws.receive_text() == "hallo")
    try:
        with c.websocket_connect("/ws_vergessen") as ws:
            ws.receive_text()
        check("⚠ WebSocket OHNE Regel: geschlossen", False)
    except Exception:  # noqa: BLE001
        check("⚠ WebSocket OHNE Regel: geschlossen", True)
finally:
    zr.AUSNAHMEN.clear()
    zr.AUSNAHMEN.update(_alt)

# Frische App fuer die Mount-Pruefung ohne Ausnahme (Einstufung wird je Instanz gecacht)
probe2 = FastAPI()
probe2.add_middleware(zr.ZugangsMiddleware, anmelde_funktionen=lambda: {require_probe},
                      pruefen=require_probe)
probe2.mount("/stat", StaticFiles(directory=str(_stat)))
check("Mount OHNE Ausnahme: verlangt Anmeldung (401)", TestClient(probe2).get("/stat/a.txt").status_code == 401)
check("Mount OHNE Ausnahme mit Anmeldung: 200",
      TestClient(probe2).get("/stat/a.txt", headers={"Authorization": "Bearer gut"}).status_code == 200)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[C] Verdrahtung in main.py")
reihen = []
for n in BAUM.body:
    if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) \
            and ast.unparse(n.value.func) == "app.add_middleware" and n.value.args:
        reihen.append(ast.unparse(n.value.args[0]))
check("Zugangs-Middleware eingehaengt", "_zugang_regel.ZugangsMiddleware" in reihen, reihen)
if "_zugang_regel.ZugangsMiddleware" in reihen and "CORSMiddleware" in reihen \
        and "_sitzung_cookie.SitzungCookieMiddleware" in reihen:
    i_z = reihen.index("_zugang_regel.ZugangsMiddleware")
    check("innen: VOR CORS und Cookie eingehaengt (spaeter = weiter aussen)",
          i_z < reihen.index("CORSMiddleware") < reihen.index("_sitzung_cookie.SitzungCookieMiddleware"),
          reihen)
else:
    check("CORS und Cookie-Middleware gefunden", False, reihen)
pf = next((n for n in BAUM.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_zugang_pruefen"), None)
check("Pruefung ruft require_auth", pf is not None and "require_auth(request)" in ast.unparse(pf))
af = next((n for n in BAUM.body if isinstance(n, ast.FunctionDef) and n.name == "_anmelde_funktionen"), None)
check("Anmelde-Funktionen = alle require_*", af is not None and "startswith('require_')" in ast.unparse(af))
ep = [s for s, fn, hat in routen if s == ("GET", "/api/security/zugangsregeln") and hat]
check("Ueberblick-Endpunkt nur mit Anmeldung", bool(ep))

# Rundsendungen an /ws nur an angemeldete Verbindungen (Nebenbefund M10)
schleifen_ohne = []
schleifen = 0
for fn in ast.walk(BAUM):
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    for loop in ast.walk(fn):
        if not isinstance(loop, (ast.For, ast.AsyncFor)):
            continue
        it = ast.unparse(loop.iter)
        if "active_sessions" not in it and "_active_ws" not in it:
            continue
        rumpf = "\n".join(ast.unparse(x) for x in loop.body)
        if "send_json" not in rumpf and "send_text" not in rumpf:
            continue
        schleifen += 1
        if "_ws_rundsendung_erlaubt(" not in rumpf and "_ws_usernames.get(" not in rumpf:
            schleifen_ohne.append("%s:%d" % (fn.name, loop.lineno))
check("Rundsende-Schleifen gefunden (Positivkontrolle, %d)" % schleifen, schleifen >= 4)
check("jede /ws-Rundsendung nur an angemeldete Verbindungen", not schleifen_ohne, schleifen_ohne)
cpu = MODUL_FN.get("cpu_broadcast")
check("CPU-Last nur an angemeldete Verbindungen",
      cpu is not None and "_ws_rundsendung_erlaubt(ws)" in ast.unparse(cpu))
hw = MODUL_FN.get("handle_ws_message")
hws = ast.unparse(hw) if hw else ""
check("Verbindung gilt erst NACH allen Pruefungen als angemeldet",
      "_ws_angemeldet.add(id(ws))" in hws
      and hws.find("_ws_angemeldet.add(id(ws))") > hws.find("_login_still_allowed(token_username)") > 0)
we = MODUL_FN.get("websocket_endpoint")
check("beim Trennen wieder abgemeldet", we is not None and "_ws_angemeldet.discard(id(ws))" in ast.unparse(we))

# ═════════════════════════════════════════════════════════════════════════════
print("\n[D] zustand()")
z = zr.zustand(probe2, {require_probe})
check("zustand nennt den Mount ohne Regel", "MOUNT /stat" in z["ohne_regel"], z)
check("zustand zaehlt Routen", z["routen"] >= 1)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[E] Vision-Stream ohne festen Vorgabeschluessel")
vfn = next((n for n in BAUM.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "vision_mjpeg_stream"), None)
if vfn is None:
    abbruch("vision_mjpeg_stream nicht gefunden")
vfn.decorator_list = []
quelle = ast.Module(body=[vfn], type_ignores=[])
ns: dict = {}


class _Cfg:
    zustand: dict = {}

    def get_skill_states(self):
        return self.zustand


class _Abgelehnt(Exception):
    def __init__(self, status_code=0, detail=""):
        self.status_code = status_code


import hmac as _hmac  # noqa: E402
ns.update(config=_Cfg(), verify_token=lambda t: "anna" if t == "gut" else None,
          HTTPException=_Abgelehnt, hmac=_hmac, _get_vision_engine=lambda: None,
          JSONResponse=lambda d, status_code=200: ("antwort", status_code), Request=object,
          # Sperrpruefung der Sitzung (test_bsi_sitzung_sperre) – hier nicht Gegenstand
          _sitzung_gesperrt=lambda u: False)
exec(compile(quelle, "vision_mjpeg_stream", "exec"), ns)


class _Req:
    def __init__(self, **q):
        self.query_params = q


def _stream(cfg, **q):
    ns["config"].zustand = cfg
    try:
        asyncio.run(ns["vision_mjpeg_stream"](_Req(**q)))
        return "durch"
    except _Abgelehnt:
        return "401"


check("Positivkontrolle: Sitzung kommt durch", _stream({}, token="gut") == "durch")
# Rueckfall des erwarteten Schluessels: ausser "" keine Konstante (kein Vorgabeschluessel)
_erw = [n for n in ast.walk(vfn) if isinstance(n, ast.Assign)
        and any(getattr(t, "id", "") == "expected_key" for t in n.targets)]
_konst = [c.value for a in _erw for c in ast.walk(a.value)
          if isinstance(c, ast.Constant) and isinstance(c.value, str)
          and c.value not in ("", "vision", "config", "stream_key")]
check("expected_key gefunden (Positivkontrolle)", len(_erw) == 1, len(_erw))
check("⚠ kein fester Vorgabeschluessel im Rueckfall", not _konst, _konst)
check("⚠ alter Vorgabeschluessel ohne Einstellung: abgewiesen", _stream({}, key="jarvis-stream") == "401")
check("leerer Schluessel bei leerer Einstellung: abgewiesen",
      _stream({"vision": {"config": {"stream_key": ""}}}, key="") == "401")
check("zu kurzer gesetzter Schluessel gilt nicht",
      _stream({"vision": {"config": {"stream_key": "kurz"}}}, key="kurz") == "401")
lang = "s" * 24
check("gesetzter langer Schluessel: durch", _stream({"vision": {"config": {"stream_key": lang}}}, key=lang) == "durch")
check("falscher Schluessel: abgewiesen",
      _stream({"vision": {"config": {"stream_key": lang}}}, key=lang + "x") == "401")

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
