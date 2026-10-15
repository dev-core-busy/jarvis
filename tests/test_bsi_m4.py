#!/usr/bin/env python3
"""Waechter BSI M4 – keine Geheimnisse aus Adressen im Protokoll.

Gemessen an der WIRKUNG:
  [A] ``backend/url_geheimnis.schwaerzen``: Token/Ticket/Schluessel-Werte,
      auch prozentkodiert in einer verschachtelten Adresse (noVNC ``path=``),
      und das Kennwort in ``schema://user:pw@host``; harmlose Parameter bleiben.
  [B] ein ECHTER uvicorn-Prozess (Access-Log + WebSocket-Zeile): ohne Filter
      steht die Sonde im Protokoll (Positivkontrolle – die Probe SIEHT ein
      Leck), mit ``installieren()`` nicht mehr, der Pfad aber schon.
      Dazu die Regel: main.py installiert den Filter auf Modulebene.
  [C] ``backend/vnc_ticket``: einmal einloesbar, verfaellt, traegt den Kontext.
  [D] der echte Rumpf von ``vnc_websocket_proxy`` (per AST, unveraendert)
      gegen Attrappen: ein Sitzungstoken in der Adresse wird ABGEWIESEN, ein
      Ticket einer 2FA-Admin-Sitzung kommt durch, ein zweites Mal nicht, eines
      aus einer Sitzung ohne 2FA bekommt keine Admin-Rechte (BSI M3 bleibt).
  [E] der echte Rumpf von ``vnc_ticket_holen``: Kontext kommt aus DIESER
      Anfrage, gesperrtes Konto 403, ``no-store``; Route + Admin-Dependency.
  [F] /docs und /redoc reichen einen Abruf-Schluessel weiter, kein Sitzungstoken.
  [G] ``frontend/js/vnc.js`` in Node ausgefuehrt: die noVNC-Adresse traegt das
      Ticket und NICHT das Sitzungstoken.
  [H] Android ``IssuesRepository.attachmentUrl``: Abruf-Schluessel per Kopfsatz,
      ein Sitzungstoken kommt nie in die Adresse (REGEL am Quelltext – die
      Kompilierbarkeit prueft ``./gradlew :app:compileDebugKotlin``).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import contextvars
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

try:
    import uvicorn  # noqa: F401
    import websockets.sync.client  # noqa: F401
except ImportError:
    venv_py = ROOT / "venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), __file__] + sys.argv[1:])
    print("ABBRUCH: uvicorn/websockets fehlen (venv/bin/python tests/test_bsi_m4.py)")
    sys.exit(2)

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:300] + "]") if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="bsi_m4_"))

# ── Sandkasten: backend.config NICHT echt importieren ─────────────────────────
# Der echte Import migriert Profile und schreibt die LIVE-settings.json zurueck.
_cfg = types.ModuleType("backend.config")


class _C:
    SECRET_KEY = "testgeheimnis-bsi-m4"

    def get_setting(self, k, d=None):
        # download_key_strict bewusst NICHT gesetzt: [F] misst die Vorgabe
        return {"download_key_ttl_min": 15}.get(k, d)


_cfg.config = _C()
sys.modules["backend.config"] = _cfg

from backend import url_geheimnis as UG   # noqa: E402
from backend import vnc_ticket as VT      # noqa: E402
from backend import download_key as DK    # noqa: E402

MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MAIN_AST = ast.parse(MAIN_SRC)


def fdef(name):
    treffer = [k for k in ast.walk(MAIN_AST)
               if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name]
    if len(treffer) != 1:
        abbruch("main.py: %d Definitionen von %s (erwartet genau 1)" % (len(treffer), name))
    return treffer[0]


def rumpf_ausfuehren(name, ns):
    """Den ECHTEN Funktionsrumpf aus main.py (ohne Dekoratoren) in ``ns`` definieren."""
    k = fdef(name)
    k2 = ast.parse(ast.get_source_segment(MAIN_SRC, k) or "").body[0]
    k2.decorator_list = []
    try:
        exec(compile(ast.Module(body=[k2], type_ignores=[]), "main.py:" + name, "exec"), ns)
    except NameError as e:
        # Ein Absturz waere Exit 1 OHNE Bilanz – „konnte nicht laufen" ist Exit 2
        abbruch("%s: Attrappe fehlt fuer %s" % (name, e))
    return ns[name]


# ═══════════════════════════════════════════════════════════════════════════
print("[A] Schwaerzen")
S = UG.schwaerzen
faelle = [
    ("/api/x?token=GEHEIM1&t=5", "/api/x?token=***&t=5"),
    ("/api/x?t=5&token=GEHEIM1", "/api/x?t=5&token=***"),
    ("/ws/vnc?ticket=GEHEIM2", "/ws/vnc?ticket=***"),
    ("/x?TOKEN=GEHEIM3", "/x?TOKEN=***"),
    ("/x?api_key=GEHEIM4&key=GEHEIM5", "/x?api_key=***&key=***"),
    # noVNC: die WS-Adresse steckt prozentkodiert im path-Parameter
    ("/novnc/vnc.html?autoconnect=true&path=ws%2Fvnc%3Fticket%3DGEHEIM6&encrypt=1",
     "/novnc/vnc.html?autoconnect=true&path=ws%2Fvnc%3Fticket%3D***&encrypt=1"),
    ("/a?path=ws%2Fvnc%3Ftoken%3DGEHEIM7%26x%3D1", "/a?path=ws%2Fvnc%3Ftoken%3D***%26x%3D1"),
    ("rtsp://admin:GEHEIM8@kamera.firma.local/stream", "rtsp://admin:***@kamera.firma.local/stream"),
    ("http://192.0.2.5/feed?token=GEHEIM9", "http://192.0.2.5/feed?token=***"),
    ('"GET /api/x?token=GEHEIM1 HTTP/1.1" 200', '"GET /api/x?token=*** HTTP/1.1" 200'),
]
for roh, soll in faelle:
    check("schwaerzt: " + roh[:60], S(roh) == soll, S(roh))
# harmlose Namen, die nur AEHNLICH heissen, bleiben stehen
for roh in ("/x?keyword=abc", "/x?monkey=1", "/x?tokens_used=12", "/api/download-key",
            "/ws/vnc", "http://host/pfad", "kein url text"):
    check("unveraendert: " + roh, S(roh) == roh, S(roh))
check("Nicht-String bleibt unveraendert", S(42) == 42 and S(None) is None)

# Filter am Protokolleintrag: msg UND args
import logging  # noqa: E402
rec = logging.LogRecord("uvicorn.access", logging.INFO, "f", 1,
                        '%s - "%s %s HTTP/%s" %d', ("1.2.3.4:5", "GET", "/x?token=GEHEIM1", "1.1", 200), None)
check("Filter laesst den Eintrag durch", UG.ProtokollFilter().filter(rec) is True)
check("Filter schwaerzt die Argumente", "GEHEIM1" not in rec.getMessage() and "/x?token=***" in rec.getMessage(),
      rec.getMessage())

# ═══════════════════════════════════════════════════════════════════════════
print("[B] Echter uvicorn: Access-Log und WebSocket-Zeile")


def freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


APP = TMP / "m4app.py"
APP.write_text(
    "import os, sys\n"
    "sys.path.insert(0, %r)\n"
    "if os.environ.get('M4_FILTER') == '1':\n"
    "    from backend import url_geheimnis\n"
    "    url_geheimnis.installieren()\n"
    "async def app(scope, receive, send):\n"
    "    if scope['type'] == 'http':\n"
    "        await send({'type': 'http.response.start', 'status': 200, 'headers': []})\n"
    "        await send({'type': 'http.response.body', 'body': b'ok'})\n"
    "    elif scope['type'] == 'websocket':\n"
    "        await receive()\n"
    "        await send({'type': 'websocket.accept'})\n"
    "        await send({'type': 'websocket.close', 'code': 1000})\n"
    "    elif scope['type'] == 'lifespan':\n"
    "        while True:\n"
    "            m = await receive()\n"
    "            if m['type'] == 'lifespan.startup':\n"
    "                await send({'type': 'lifespan.startup.complete'})\n"
    "            else:\n"
    "                await send({'type': 'lifespan.shutdown.complete'}); return\n" % str(ROOT),
    encoding="utf-8")


def uvicorn_lauf(mit_filter):
    port = freier_port()
    env = dict(os.environ, M4_FILTER="1" if mit_filter else "0", PYTHONPATH=str(TMP))
    log = TMP / ("log_%d.txt" % mit_filter)
    with open(log, "w") as fh:
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", "m4app:app", "--host", "127.0.0.1",
                              "--port", str(port)], cwd=str(TMP), env=env, stdout=fh, stderr=fh)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            abbruch("uvicorn startet nicht: " + log.read_text()[-400:])
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:%d/m4pfad?token=SONDE_HTTP&t=1" % port, timeout=5).read()
        urllib.request.urlopen("http://127.0.0.1:%d/novnc/vnc.html?path=ws%%2Fvnc%%3Fticket%%3DSONDE_NOVNC"
                               % port, timeout=5).read()
        from websockets.sync.client import connect
        try:
            with connect("ws://127.0.0.1:%d/ws/vnc?ticket=SONDE_WS" % port, open_timeout=5) as ws:
                try:
                    ws.recv(timeout=2)
                except Exception:  # noqa: BLE001 – Schliessen ist hier der Normalfall
                    pass
        except Exception as e:  # noqa: BLE001
            abbruch("WebSocket-Probe scheitert: %s" % e)
        time.sleep(0.5)
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    return log.read_text()


ohne = uvicorn_lauf(False)
# Positivkontrolle: die Probe sieht ein Leck, wenn es eines gibt
if not ("SONDE_HTTP" in ohne and "SONDE_WS" in ohne and "SONDE_NOVNC" in ohne):
    abbruch("Positivkontrolle: ohne Filter steht die Sonde NICHT im uvicorn-Protokoll – "
            "die Messung waere blind:\n" + ohne[-800:])
mit = uvicorn_lauf(True)
check("Access-Log laeuft weiter (Pfad steht drin)", "/m4pfad" in mit, mit[-400:])
check("Access-Log: Token-Wert geschwaerzt", "SONDE_HTTP" not in mit and "token=***" in mit, mit[-600:])
check("Access-Log: Ticket in der noVNC-Adresse geschwaerzt", "SONDE_NOVNC" not in mit, mit[-600:])
check("WebSocket-Zeile: Ticket geschwaerzt", "SONDE_WS" not in mit and "/ws/vnc?ticket=***" in mit, mit[-600:])

# Regel: main.py installiert den Filter auf MODULEBENE (laeuft beim Import, vor jeder Anfrage)
_inst = [n for n in MAIN_AST.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
         and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "installieren"
         and isinstance(n.value.func.value, ast.Name) and n.value.func.value.id == "_url_geheimnis"]
_imp = [n for n in MAIN_AST.body if isinstance(n, ast.ImportFrom) and n.module == "backend"
        and any(a.name == "url_geheimnis" and a.asname == "_url_geheimnis" for a in n.names)]
check("main.py ruft _url_geheimnis.installieren() auf Modulebene", len(_inst) == 1 and len(_imp) == 1)

# Kamera-Startzeile im Journal: geht durch schwaerzen()
_vis = [k for k in ast.walk(MAIN_AST) if isinstance(k, ast.JoinedStr)
        and any(isinstance(v, ast.Constant) and "Vision auto-start:" in str(v.value) for v in k.values)]
_vis_ok = bool(_vis) and all(
    all(not isinstance(v, ast.FormattedValue)
        or (isinstance(v.value, ast.Call) and isinstance(v.value.func, ast.Attribute)
            and v.value.func.attr == "schwaerzen")
        for v in k.values) for k in _vis)
check("Kamera-Startzeile schwaerzt die Adresse", _vis_ok)

# ═══════════════════════════════════════════════════════════════════════════
print("[C] Einmal-Ticket")
t1 = VT.ausstellen("anna", ("anna", True, False))
check("Ticket ist lang und zufaellig", len(t1) >= 40 and t1 != VT.ausstellen("anna"))
check("einloesen liefert Benutzer + Kontext", VT.einloesen(t1) == ("anna", ("anna", True, False)))
check("zweites Einloesen scheitert", VT.einloesen(t1) is None)
check("unbekanntes/leeres Ticket scheitert", VT.einloesen("x" * 43) is None and VT.einloesen("") is None
      and VT.einloesen(None) is None)
_echt_mono = VT.time.monotonic
t2 = VT.ausstellen("anna")
VT.time = types.SimpleNamespace(monotonic=lambda: _echt_mono() + VT.TTL_SEK + 1)
try:
    check("abgelaufenes Ticket scheitert", VT.einloesen(t2) is None)
finally:
    VT.time = time
try:
    VT.ausstellen("")
    check("ohne Benutzer kein Ticket (wirft)", False)
except ValueError:
    check("ohne Benutzer kein Ticket (wirft)", True)

# ═══════════════════════════════════════════════════════════════════════════
print("[D] /ws/vnc – echter Rumpf")
KX = contextvars.ContextVar("_sitzung_kontext", default=None)


def _admin(u):
    """Attrappe mit der ECHTEN Semantik von _user_is_admin/_sitzung_ohne_admin:
    OHNE Sitzungskontext (oder fuer ein fremdes Konto) entscheidet allein die
    Konfiguration – hier: anna ist Admin. Nur eine Sitzung OHNE 2FA nimmt die
    Rechte. Genau deshalb muss der WebSocket den Kontext des Tickets einsetzen:
    ohne ihn waere es fail-open."""
    kx = KX.get()
    if kx is None or kx[0] != u:
        return u == "anna"
    return bool(kx[1])


class _WS:
    def __init__(self, query):
        self.query_params = query
        self.headers = {}
        self.akzeptiert = False
        self.geschlossen = []

    async def accept(self, subprotocol=None):
        self.akzeptiert = True

    async def close(self, code=1000, reason=""):
        self.geschlossen.append(code)


async def _kein_vnc(*a, **k):
    raise ConnectionRefusedError()


ns_ws = {
    "WebSocket": object, "_vnc_ticket": VT, "_sitzung_kontext": KX,
    "_login_still_allowed": lambda u: True, "_user_must_change": lambda u: False,
    "_is_admin_user": _admin, "verify_token": lambda t: "anna" if t == "SITZUNG" else None,
    "asyncio": types.SimpleNamespace(open_connection=_kein_vnc, create_task=lambda c: c.close(),
                                     to_thread=lambda *a: None),
    "_unlock_desktop_screen": lambda: None,
}
proxy = rumpf_ausfuehren("vnc_websocket_proxy", ns_ws)


def ws_lauf(query):
    ws = _WS(query)
    contextvars.Context().run(asyncio.run, proxy(ws))
    return ws


w = ws_lauf({"token": "SITZUNG"})
check("Sitzungstoken in der Adresse wird abgewiesen (4001)", w.geschlossen == [4001] and not w.akzeptiert,
      w.geschlossen)
t_adm = VT.ausstellen("anna", ("anna", True, False))
w = ws_lauf({"ticket": t_adm})
# Positivkontrolle: der gemeinte Weg lief bis zum VNC-Aufbau (1011 = x11vnc nicht erreichbar)
if not (w.akzeptiert and w.geschlossen == [1011]):
    abbruch("Positivkontrolle: Ticket einer 2FA-Admin-Sitzung kommt nicht durch (%s, akzeptiert=%s)"
            % (w.geschlossen, w.akzeptiert))
check("Ticket einer 2FA-Admin-Sitzung wird angenommen", True)
w = ws_lauf({"ticket": t_adm})
check("dasselbe Ticket ein zweites Mal: 4001", w.geschlossen == [4001] and not w.akzeptiert, w.geschlossen)
w = ws_lauf({"ticket": VT.ausstellen("anna", ("anna", False, False))})
check("Ticket aus Sitzung OHNE 2FA: keine Admin-Rechte (4004)", w.geschlossen == [4004] and not w.akzeptiert,
      w.geschlossen)
ns_ws["_login_still_allowed"] = lambda u: False
w = ws_lauf({"ticket": VT.ausstellen("anna", ("anna", True, False))})
check("entzogene Anmeldeberechtigung: abgewiesen", not w.akzeptiert and w.geschlossen[:1] == [4001], w.geschlossen)
ns_ws["_login_still_allowed"] = lambda u: True

# ═══════════════════════════════════════════════════════════════════════════
print("[E] POST /api/vnc/ticket – echter Rumpf")


class _HTTPExc(Exception):
    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code = status_code


class _JR:
    def __init__(self, content, status_code=200, headers=None):
        self.content, self.status_code, self.headers = content, status_code, headers or {}


SITZ = {"TOK_2FA": ("anna", True), "TOK_OHNE": ("anna", False), "TOK_BERT": ("bert", True)}


def _verify(tok):
    s = SITZ.get(tok)
    if not s:
        return None
    KX.set((s[0], s[1], False))
    return s[0]


gesperrt = set()
# require_auth mitgestellt: die Regel unten soll eine schwaechere Dependency
# MELDEN, nicht am fehlenden Namen abstuerzen
ns_t = {"Request": object, "Depends": lambda f: None, "require_local_auth": None, "require_auth": None,
        "security_guard": types.SimpleNamespace(is_blocked=lambda u: u in gesperrt),
        "HTTPException": _HTTPExc, "verify_token": _verify, "_vnc_ticket": VT,
        "_sitzung_kontext": KX, "JSONResponse": _JR}
holen = rumpf_ausfuehren("vnc_ticket_holen", ns_t)


def ticket_lauf(tok, user):
    req = types.SimpleNamespace(headers={"Authorization": "Bearer " + tok})

    async def lauf():
        # Altlast im Kontext, wie sie die Dependency hinterlassen koennte: darf
        # NICHT ins Ticket wandern
        KX.set((user, True, False))
        return await holen(req, user)
    try:
        return contextvars.Context().run(asyncio.run, lauf())
    except _HTTPExc as e:
        return e


r = ticket_lauf("TOK_2FA", "anna")
check("Ticket ausgestellt, no-store", isinstance(r, _JR) and r.content.get("ticket")
      and r.headers.get("Cache-Control") == "no-store", getattr(r, "content", r))
check("Ticket traegt den 2FA-Kontext der Anfrage",
      isinstance(r, _JR) and VT.einloesen(r.content["ticket"]) == ("anna", ("anna", True, False)))
r = ticket_lauf("TOK_OHNE", "anna")
_t_ohne = r.content["ticket"] if isinstance(r, _JR) else ""
w = ws_lauf({"ticket": _t_ohne})
check("Kette: Sitzung ohne 2FA -> Ticket -> WebSocket 4004 (Kontext aus DIESER Anfrage)",
      w.geschlossen == [4004] and not w.akzeptiert, w.geschlossen)
r = ticket_lauf("TOK_BERT", "anna")
check("Kopfsatz eines anderen Benutzers: 401", isinstance(r, _HTTPExc) and r.status_code == 401, r)
gesperrt.add("anna")
r = ticket_lauf("TOK_2FA", "anna")
check("gesperrtes Konto: 403", isinstance(r, _HTTPExc) and r.status_code == 403, r)
gesperrt.clear()

_k = fdef("vnc_ticket_holen")
_deko = [ast.unparse(d) for d in _k.decorator_list]
check("Route POST /api/vnc/ticket", _deko == ["app.post('/api/vnc/ticket')"], _deko)
_dep = [ast.unparse(d) for d in _k.args.defaults]
check("nur fuer Administratoren (require_local_auth)", "Depends(require_local_auth)" in _dep, _dep)

# ═══════════════════════════════════════════════════════════════════════════
print("[F] /docs und /redoc")
_eingeschraenkt = {"an": False}
ns_d = {"_dlkey": DK, "_sitzung_ohne_admin": lambda u: _eingeschraenkt["an"],
        "_abruf_sitzung": lambda u: None}
oa = rumpf_ausfuehren("_openapi_url", ns_d)
u = oa("anna")
_wert = u.split("token=", 1)[-1] if "token=" in u else ""
check("openapi-Adresse traegt einen Abruf-Schluessel fuer den Benutzer",
      u.startswith("/openapi.json?token=") and DK.ist_abrufschluessel(_wert) and DK.pruefen(_wert) == "anna", u)
check("… aus voller Sitzung: Schluessel NICHT eingeschraenkt",
      DK.pruefen_mit_art(_wert) == ("anna", False), DK.pruefen_mit_art(_wert))
_eingeschraenkt["an"] = True
_wert2 = oa("anna").split("token=", 1)[-1]
check("… aus eingeschraenkter Sitzung: Schluessel traegt die Einschraenkung (Review 2026-10-07)",
      DK.pruefen_mit_art(_wert2) == ("anna", True), DK.pruefen_mit_art(_wert2))
_eingeschraenkt["an"] = False
check("Sitzungstoken in ?token= per Vorgabe abgewiesen (download_key_strict an)", DK.streng() is True)
for name in ("gated_docs", "gated_redoc"):
    k = fdef(name)
    aufrufe = [ast.unparse(c.func) for c in ast.walk(k) if isinstance(c, ast.Call)]
    roh = ast.unparse(k)
    check(name + ": Schema-Adresse aus _openapi_url(user)", "_openapi_url" in aufrufe, aufrufe)
    check(name + ": liest weder Authorization noch ?token=",
          "query_params" not in roh and "Authorization" not in roh)

# ═══════════════════════════════════════════════════════════════════════════
print("[G] vnc.js in Node")
NODE = shutil.which("node")
if not NODE:
    abbruch("node fehlt")
probe = TMP / "vnc_probe.js"
probe.write_text(r"""
const fs = require('fs'); const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
const anfragen = [];
const el = () => ({ hidden: true, src: '', textContent: '', style: {} });
const elemente = { 'vnc-iframe': el(), 'desktop-placeholder': el(), 'vnc-status': el() };
const window = {
  location: { hostname: 'h', port: '', protocol: 'https:' },
  authToken: 'SITZUNGSTOKEN_XYZ',
  JarvisSitzung: { token: () => 'SITZUNGSTOKEN_XYZ' },
  t: k => k,
};
const ctx = {
  window, console, setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  document: { getElementById: id => elemente[id] || el(), body: { appendChild() {} }, createElement: el },
  encodeURIComponent,
  fetch: (url, opt) => {
    anfragen.push({ url, method: (opt && opt.method) || 'GET', auth: opt && opt.headers && opt.headers.Authorization });
    const body = url === '/api/vnc/ticket' ? { ok: true, ticket: 'TICKET_ABC' } : { ok: true };
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  },
};
ctx.window.document = ctx.document;
vm.createContext(ctx);
vm.runInContext(src, ctx);
const v = new ctx.window.JarvisVNC();
v.connect(6080);
setImmediate(() => setImmediate(() => setImmediate(() => {
  console.log(JSON.stringify({ src: elemente['vnc-iframe'].src, anfragen }));
})));
""", encoding="utf-8")
r = subprocess.run([NODE, str(probe), str(ROOT / "frontend" / "js" / "vnc.js")],
                   capture_output=True, text=True, timeout=60)
try:
    erg = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
except ValueError:
    erg = {}
if not erg:
    abbruch("vnc.js-Probe ohne Ergebnis: " + (r.stderr or r.stdout)[-600:])
src = erg.get("src", "")
ticket_anfr = [a for a in erg.get("anfragen", []) if a.get("url") == "/api/vnc/ticket"]
# Positivkontrolle: die Probe hat connect() wirklich bis zum Setzen der Adresse gefahren
if "/novnc/vnc.html" not in src:
    abbruch("Positivkontrolle: connect() hat keine noVNC-Adresse gesetzt: %r" % src)
check("Ticket per POST mit Kopfsatz geholt",
      len(ticket_anfr) == 1 and ticket_anfr[0]["method"] == "POST"
      and ticket_anfr[0]["auth"] == "Bearer SITZUNGSTOKEN_XYZ", ticket_anfr)
check("noVNC-Adresse traegt das Ticket", "ticket%3DTICKET_ABC" in src, src)
check("noVNC-Adresse traegt KEIN Sitzungstoken", "SITZUNGSTOKEN_XYZ" not in src and "token%3D" not in src, src)

# ═══════════════════════════════════════════════════════════════════════════
print("[H] Android: Anhang-Adresse")
import re  # noqa: E402
KT = (ROOT / "android/app/src/main/java/info/jarvisai/app/data/repository/IssuesRepository.kt").read_text(
    encoding="utf-8")


def kt_rumpf(quelle, kopf):
    """Rumpf einer Kotlin-Funktion ab ``kopf`` bis zur passenden schliessenden Klammer
    (ohne //- und /* */-Kommentare, damit die Begruendung nicht mitgelesen wird)."""
    i = quelle.find(kopf)
    if i < 0:
        return None
    j = quelle.find("{", i)
    tiefe, k = 0, j
    while k < len(quelle):
        tiefe += {"{": 1, "}": -1}.get(quelle[k], 0)
        if tiefe == 0:
            break
        k += 1
    r = quelle[j:k + 1]
    r = re.sub(r"/\*.*?\*/", "", r, flags=re.S)
    return re.sub(r"//[^\n]*", "", r)


au = kt_rumpf(KT, "suspend fun attachmentUrl(")
ab = kt_rumpf(KT, "private suspend fun abrufSchluessel(")
if not au or not ab or "?token=" not in au:
    abbruch("Positivkontrolle: attachmentUrl/abrufSchluessel nicht gefunden oder ohne ?token=")
check("Abruf-Schluessel wird per Kopfsatz geholt",
      'authBuilder("/api/download-key")' in ab)
check("attachmentUrl holt einen Abruf-Schluessel", "abrufSchluessel()" in au)
_vorlagen = re.findall(r'\?token=\$\{([^}]*)\}', au)
check("in die Adresse kommt nur der gepruefte Wert (wert), nie token()/tok",
      bool(_vorlagen) and all("wert" in v and "token()" not in v and not re.search(r"\btok\b", v)
                              for v in _vorlagen), _vorlagen)
check("Rueckfall nur fuer einen Programmschluessel, nie fuers Sitzungstoken",
      re.search(r"val\s+istSitzung\s*=\s*tok\.count\s*\{\s*it\s*==\s*':'\s*\}\s*>=\s*2", au) is not None
      and re.search(r"abrufSchluessel\(\)\s*\?:\s*tok\.takeUnless\s*\{\s*istSitzung\s*\}", au) is not None)

shutil.rmtree(TMP, ignore_errors=True)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
