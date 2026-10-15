#!/usr/bin/env python3
"""Waechter: WebDAV nie mit dem Standardkennwort (Code-Review 2026-10-07).

Befund: ohne gesetztes Kennwort galt still ``jarvis``/``jarvis`` – ein
oeffentlich bekanntes Paar vor der ganzen Wissensdatenbank –, und
``GET /api/knowledge/webdav/status`` meldete fest ``password_gesetzt: True``.

Gemessen an der WIRKUNG:
  1. ``backend/webdav.get_webdav_app`` (echtes Modul, ``backend.config`` als
     Stub): eingeschaltet ohne Kennwort -> keine App; mit Kennwort -> App, und
     die Anmeldung ``jarvis``/``jarvis`` gelingt dann NICHT (echtes wsgidav).
  2. ``webdav_status`` / ``webdav_config`` aus main.py (AST, ausgefuehrt).
  3. ``secret_reveal.webdav``: kein erfundenes ``jarvis``.

    python3 tests/test_webdav_kennwort.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import base64
import io
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
# Echtes wsgidav, wenn vorhanden (Server, CI) – sonst eine Attrappe in echter
# Signatur, die die uebergebene Konfiguration festhaelt. Die Anmeldung selbst
# misst nur der Lauf mit echtem wsgidav; die Sperre ohne Kennwort beide.
try:
    import wsgidav.wsgidav_app  # noqa: F401
    ECHT_DAV = True
except ImportError:
    ECHT_DAV = False
    _dav = types.ModuleType("wsgidav")
    _davapp = types.ModuleType("wsgidav.wsgidav_app")

    class WsgiDAVApp:                       # Signatur wie wsgidav: WsgiDAVApp(config)
        letzte = None

        def __init__(self, config):
            WsgiDAVApp.letzte = config

        def __call__(self, environ, start_response):
            start_response("501 Not Implemented", [])
            return [b""]
    _davapp.WsgiDAVApp = WsgiDAVApp
    _dav.wsgidav_app = _davapp
    sys.modules["wsgidav"] = _dav
    sys.modules["wsgidav.wsgidav_app"] = _davapp

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % (detail,)) if detail else ""))


def abbruch(grund):
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


# backend.config NUR als Stub – der echte Import schreibt die Live-settings.json
ZUSTAND = {"knowledge": {"config": {"webdav": {}}}}
cfg_mod = types.ModuleType("backend.config")
cfg_mod.config = types.SimpleNamespace(get_skill_states=lambda: ZUSTAND,
                                       save_skill_state=lambda n, s: ZUSTAND.__setitem__(n, s))
sys.modules["backend.config"] = cfg_mod
import backend  # noqa: E402
backend.config = cfg_mod
try:
    from backend import webdav as WD  # noqa: E402
except Exception as e:  # noqa: BLE001
    abbruch("backend.webdav nicht importierbar: %s" % e)
WD.PROJECT_ROOT = Path(os.environ.get("TMPDIR", "/tmp")) / ("webdav_kw_%d" % os.getpid())


def setze(**w):
    ZUSTAND["knowledge"]["config"]["webdav"] = dict(w)


def anmelden(app, user, pw):
    """PROPFIND / mit Basic-Auth an der echten WSGI-App; Rueckgabe Statuscode."""
    status = {}

    def start(s, h, exc=None):
        status["s"] = int(s.split()[0])
    env = {"REQUEST_METHOD": "PROPFIND", "PATH_INFO": "/", "SCRIPT_NAME": "", "QUERY_STRING": "",
           "SERVER_NAME": "x", "SERVER_PORT": "443", "SERVER_PROTOCOL": "HTTP/1.1",
           "wsgi.url_scheme": "https", "wsgi.input": io.BytesIO(b""), "wsgi.errors": sys.stderr,
           "wsgi.version": (1, 0), "wsgi.multithread": False, "wsgi.multiprocess": False,
           "wsgi.run_once": False, "HTTP_DEPTH": "0", "CONTENT_LENGTH": "0",
           "HTTP_AUTHORIZATION": "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()}
    for _ in app(env, start):
        pass
    return status.get("s")


print("\n\033[1m1 – get_webdav_app\033[0m")
setze(enabled=True, username="dav", password="Geheim!9")
app = WD.get_webdav_app()
if app is None:
    abbruch("Positivkontrolle: mit Kennwort entsteht keine App")
if ECHT_DAV:
    check("Positivkontrolle: richtiges Kennwort -> angemeldet (echtes wsgidav)",
          anmelden(app, "dav", "Geheim!9") in (200, 207), anmelden(app, "dav", "Geheim!9"))
    check("Positivkontrolle: falsches Kennwort -> 401", anmelden(app, "dav", "falsch") == 401)
    check("⚠ jarvis/jarvis -> 401", anmelden(app, "jarvis", "jarvis") == 401)
else:
    print("  (wsgidav fehlt hier – Anmeldung nur am Server/CI gemessen)")
    um = ((WsgiDAVApp.letzte or {}).get("simple_dc") or {}).get("user_mapping") or {}
    check("Positivkontrolle: wsgidav bekommt genau den gesetzten Zugang",
          um == {"*": {"dav": {"password": "Geheim!9"}}}, um)
setze(enabled=True, username="jarvis")
check("⚠ eingeschaltet OHNE Kennwort -> keine App (gesperrt)", WD.get_webdav_app() is None)
setze(enabled=True)
check("⚠ … auch ohne Benutzer (frueher jarvis/jarvis)", WD.get_webdav_app() is None)
setze(enabled=True, username="jarvis", password="")
check("⚠ … und mit leerem Kennwort", WD.get_webdav_app() is None)

print("\n\033[1m2 – Status und Konfiguration (main.py)\033[0m")
MB = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
FN = {n.name: n for n in MB.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


class Antwort:
    def __init__(self, content, status_code=200, headers=None):
        self.content, self.status_code = content, status_code


class Anfrage:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


def schneide(name, ns):
    if name not in FN:
        abbruch("main.py: %s fehlt" % name)
    k = ast.parse(ast.unparse(FN[name])).body[0]
    k.decorator_list = []
    for a in k.args.args:
        a.annotation = None
    k.args.defaults = [ast.Constant(None) for _ in k.args.defaults]
    exec(compile(ast.fix_missing_locations(ast.Module(body=[k], type_ignores=[])),
                 "<main:%s>" % name, "exec"), ns)
    return ns[name]


kn = types.ModuleType("backend.tools.knowledge")
kn.PROJECT_ROOT = WD.PROJECT_ROOT
sys.modules["backend.tools.knowledge"] = kn
ns = {"JSONResponse": Antwort, "Depends": lambda x: None, "require_knowledge_editor": None,
      "os": os, "config": cfg_mod.config, "Request": Anfrage,
      "app": types.SimpleNamespace(state=types.SimpleNamespace())}
st = schneide("webdav_status", ns)
setze(enabled=False, username="jarvis")
r = asyncio.run(st(user="chef"))
check("⚠ Status ohne Kennwort: password_gesetzt False", r.content.get("password_gesetzt") is False,
      r.content.get("password_gesetzt"))
setze(enabled=False, username="dav", password="Geheim!9")
r = asyncio.run(st(user="chef"))
check("Positivkontrolle: mit Kennwort password_gesetzt True", r.content.get("password_gesetzt") is True)
check("… und das Kennwort selbst geht nicht mit (BSI M5)", "Geheim!9" not in repr(r.content))

kfg = schneide("webdav_config", ns)
setze(enabled=False, username="jarvis")
r = asyncio.run(kfg(Anfrage({"enabled": True}), user="chef"))
check("⚠ Einschalten ohne Kennwort: 400 kennwort_fehlt, nichts gespeichert",
      r.status_code == 400 and r.content.get("code") == "kennwort_fehlt"
      and ZUSTAND["knowledge"]["config"]["webdav"].get("enabled") is False,
      (r.status_code, ZUSTAND["knowledge"]))
r = asyncio.run(kfg(Anfrage({"enabled": True, "password": "Neu!Pw1"}), user="chef"))
check("Positivkontrolle: Einschalten MIT Kennwort -> gespeichert",
      r.status_code == 200 and ZUSTAND["knowledge"]["config"]["webdav"].get("enabled") is True
      and ZUSTAND["knowledge"]["config"]["webdav"].get("password") == "Neu!Pw1", r.content)
r = asyncio.run(kfg(Anfrage({"enabled": False}), user="chef"))
check("Ausschalten geht immer", r.status_code == 200)

print("\n\033[1m3 – Auge (secret_reveal.webdav)\033[0m")
from backend import secret_reveal as SR  # noqa: E402
setze(enabled=True, username="jarvis")
wert, grund = SR.webdav("")
check("⚠ ohne Kennwort: kein erfundenes 'jarvis', sondern ein Grund", wert == "" and grund, (wert, grund))
setze(enabled=True, username="dav", password="Geheim!9")
check("Positivkontrolle: gesetztes Kennwort kommt", SR.webdav("")[0] == "Geheim!9")

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
