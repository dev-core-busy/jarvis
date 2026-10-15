#!/usr/bin/env python3
"""Waechter BSI H4 – Sitzung im HttpOnly-Cookie, CSRF-Token im Kopfsatz.

Befund H4 (Rest): „Token in localStorage → XSS = Kontouebernahme". Seit
2026-10-12 haelt die Weboberflaeche nur noch ein an das Cookie gebundenes
CSRF-Token (backend/sitzung_cookie.py). Gemessen an der WIRKUNG:

  [A] Modul: das CSRF-Token ist an GENAU ein Sitzungstoken gebunden, faellt nie
      mit ihm zusammen und kann von ``verify_token`` schon der Form nach nicht
      angenommen werden; Cookie-Kopf-Zerlegung; Cookie-Attribute an einer
      ECHTEN Starlette-Antwort (HttpOnly, Secure, SameSite=Strict, Path=/,
      kein Domain – sonst verwirft der Browser ``__Host-``).
  [B] Middleware gegen eine Attrappen-App: passendes Paar → echtes Token im
      Kopfsatz; falsches/fehlendes Cookie → Kopfsatz WEG; Cookie ALLEIN → kein
      Kopfsatz entsteht (das ist der CSRF-Schutz); Klartext-Token unberuehrt.
  [C] die ECHTEN Ruempfe ``_sitzung_antwort`` und ``_token_aufloesen`` aus main.py.
  [D] Durchstich durch eine echte FastAPI-App mit Cookie-Jar (https):
      Anmeldung mit Kopf → Cookie gesetzt, im Koerper nur CSRF; Folgeanfrage
      mit CSRF → angemeldet; Cookie ohne CSRF → 401; CSRF ohne Cookie → 401;
      eine aeussere ``@app.middleware("http")`` stoert das nicht.
  [E] Regeln an main.py (AST): Middleware registriert; jede Antwort, die ein
      Token ausgibt, laeuft ueber ``_sitzung_antwort`` – Ausnahmen mit Grund;
      JEDE Funktion, die ein Token aus Nachricht oder Koerper liest und
      ``verify_token`` ruft, loest es ueber ``_token_aufloesen`` auf (REGEL,
      Ausnahmen mit Grund – gefunden im Browser: /api/verify-token); logout
      loescht das Cookie; Umstellungs-Endpunkt existiert.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import hashlib
import hmac
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

try:
    import fastapi  # noqa: F401
    import httpx  # noqa: F401
except ImportError:
    venv_py = ROOT / "venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), __file__] + sys.argv[1:])
    print("ABBRUCH: fastapi/httpx fehlen (venv/bin/python tests/test_bsi_h4_cookie.py)")
    sys.exit(2)

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import sitzung_cookie as sc  # noqa: E402

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


SCHLUESSEL = "s" * 64
sc.schluessel_quelle(lambda: SCHLUESSEL)


def token(user="anna", ts=1790000000):
    sig = hmac.new(SCHLUESSEL.encode(), f"{user}:{ts}".encode(), hashlib.sha256).hexdigest()
    return f"{user}:{ts}:{sig}"


T1, T2 = token("anna"), token("bert")
# AD-Anmeldung: Name MIT Domaenen-Praefix (Backslash) – genau daran ist der
# erste Ausrollstand auf DEV gescheitert (Starlette maskiert den Backslash im
# Cookie-Wert). Dazu ein Umlaut, der als Cookie-Wert ebenso unzulaessig ist.
TAD, TUML = token("contoso\\m.mustermann"), token("jürgen")
K1 = sc.wert_kodieren(T1)

# ── [A] Modul ────────────────────────────────────────────────────────────────
print("\n[A] Modul")
c1 = sc.csrf_fuer(T1)
check("Positivkontrolle: zwei verschiedene Tokens", T1 != T2)
check("CSRF-Token traegt das Praefix", c1.startswith(sc.PRAEFIX))
check("CSRF-Token ist deterministisch je Token", sc.csrf_fuer(T1) == c1)
check("CSRF-Token unterscheidet sich je Token", sc.csrf_fuer(T2) != c1)
check("CSRF-Token enthaelt das Token nicht", T1 not in c1 and T1.split(":")[2] not in c1)
check("CSRF-Token hat kein ':' (verify_token nimmt es der Form nach nicht an)", ":" not in c1)
check("aufloesen: passendes Paar -> echtes Token", sc.aufloesen(c1, T1) == T1)
check("aufloesen: fremdes Cookie -> None", sc.aufloesen(c1, T2) is None)
check("aufloesen: leeres Cookie -> None", sc.aufloesen(c1, "") is None)
check("aufloesen: Klartext-Token statt CSRF -> None", sc.aufloesen(T1, T1) is None)
check("aufloesen: Nicht-ASCII wirft nicht", sc.aufloesen(sc.PRAEFIX + "ä" * 64, T1) is None)
_alt = sc._schluessel
sc.schluessel_quelle(lambda: "anderer" * 8)
check("anderer Server-Schluessel -> anderes CSRF-Token", sc.csrf_fuer(T1) != c1)
sc.schluessel_quelle(None)
check("ohne Schluessel: aufloesen fail-closed (None, kein Wurf)", sc.aufloesen(c1, T1) is None)
sc._schluessel = _alt

check("cookie_aus_kopf: zwischen fremden Cookies",
      sc.cookie_aus_kopf("a=1; %s=%s; b=2" % (sc.COOKIE_NAME, K1)) == T1)
check("cookie_aus_kopf: in Anfuehrungszeichen",
      sc.cookie_aus_kopf('%s="%s"' % (sc.COOKIE_NAME, K1)) == T1)
check("cookie_aus_kopf: Namens-Praefix ist keine Identitaet",
      sc.cookie_aus_kopf("x%s=%s" % (sc.COOKIE_NAME, K1)) == "")
check("cookie_aus_kopf: ungueltiges fremdes Cookie stoert nicht",
      sc.cookie_aus_kopf('kaputt="; %s=%s' % (sc.COOKIE_NAME, K1)) == T1)
check("cookie_aus_kopf: Rohwert ohne Kennung -> '' (fail-closed)",
      sc.cookie_aus_kopf("%s=%s" % (sc.COOKIE_NAME, T1)) == "")
check("wert_lesen: kaputtes base64 -> ''", sc.wert_lesen(sc.WERT_PRAEFIX + "!!!") == "")
check("gewuenscht: nur der Wert 'cookie'",
      sc.gewuenscht({sc.ANMELDE_KOPF: "Cookie"}) and not sc.gewuenscht({sc.ANMELDE_KOPF: "ja"})
      and not sc.gewuenscht({}))
check("moeglich: nur https", sc.moeglich("https") and not sc.moeglich("http"))
check("Cookie-Name mit __Host-", sc.COOKIE_NAME.startswith("__Host-"))

r = JSONResponse({})
sc.setzen(r, T1, 43200)
sk = [v.decode() for k, v in r.raw_headers if k == b"set-cookie"]
s0 = sk[0] if len(sk) == 1 else ""
check("setzen: genau ein Set-Cookie", len(sk) == 1, sk)
attr = [a.strip().lower() for a in s0.split(";")]
check("setzen: Wert traegt das Token (kodiert)", s0.startswith("%s=%s;" % (sc.COOKIE_NAME, K1)), s0)
# Rundlauf durch den ECHTEN Setz- und Lese-Weg, je Namensform
from starlette.requests import cookie_parser  # noqa: E402
for _name, _t in (("ASCII", T1), ("AD mit Backslash", TAD), ("Umlaut", TUML)):
    _r = JSONResponse({})
    sc.setzen(_r, _t, 600)
    _sk = [v.decode("latin-1") for k, v in _r.raw_headers if k == b"set-cookie"][0]
    _paar = _sk.split(";", 1)[0]
    check("Rundlauf %s: Cookie-Wert unmaskiert (keine Anfuehrungszeichen)" % _name,
          '"' not in _paar and "\\" not in _paar, _paar)
    check("Rundlauf %s: Kopf -> Token" % _name, sc.cookie_aus_kopf(_paar) == _t, _paar)
    check("Rundlauf %s: Starlette-Cookies -> Token" % _name,
          sc.wert_lesen(cookie_parser(_paar).get(sc.COOKIE_NAME, "")) == _t)
check("setzen: HttpOnly", "httponly" in attr, s0)
check("setzen: Secure", "secure" in attr, s0)
check("setzen: SameSite=Strict", "samesite=strict" in attr, s0)
check("setzen: Path=/", "path=/" in attr, s0)
check("setzen: KEIN Domain (sonst verwirft der Browser __Host-)",
      not any(a.startswith("domain=") for a in attr), s0)
check("setzen: Max-Age = Laufzeit", "max-age=43200" in attr, s0)
r = JSONResponse({})
sc.loeschen(r)
sl = [v.decode().lower() for k, v in r.raw_headers if k == b"set-cookie"]
check("loeschen: Max-Age=0 mit denselben Attributen",
      len(sl) == 1 and "max-age=0" in sl[0] and "secure" in sl[0] and "path=/" in sl[0], sl)

# ── [B] Middleware ───────────────────────────────────────────────────────────
print("\n[B] Middleware")


def mw_lauf(headers, typ="http"):
    gesehen = {}

    async def innen(scope, receive, send):
        gesehen["scope"] = scope

    scope = {"type": typ, "headers": [(k.lower().encode(), v.encode()) for k, v in headers]}
    asyncio.run(sc.SitzungCookieMiddleware(innen)(scope, None, None))
    s = gesehen.get("scope") or {}
    auth = [v.decode() for k, v in s.get("headers", []) if k == b"authorization"]
    return auth, s


ck = "%s=%s" % (sc.COOKIE_NAME, K1)
auth, s = mw_lauf([("Authorization", "Bearer " + c1), ("Cookie", ck)])
check("passendes Paar -> Kopfsatz traegt das echte Token", auth == ["Bearer " + T1], auth)
check("passendes Paar -> Merker gesetzt", s.get("jarvis_sitzung_cookie") is True)
auth, s = mw_lauf([("Authorization", "bearer " + c1), ("Cookie", ck)])
check("Bearer klein geschrieben wird erkannt", auth == ["Bearer " + T1], auth)
auth, s = mw_lauf([("Authorization", "Bearer " + c1), ("Cookie", "%s=%s" % (sc.COOKIE_NAME, sc.wert_kodieren(T2)))])
check("fremdes Cookie -> Kopfsatz entfernt", auth == [], auth)
check("fremdes Cookie -> Merker False", s.get("jarvis_sitzung_cookie") is False)
auth, _ = mw_lauf([("Authorization", "Bearer " + c1)])
check("CSRF ohne Cookie -> Kopfsatz entfernt", auth == [], auth)
auth, s = mw_lauf([("Cookie", ck)])
check("Cookie ALLEIN -> kein Kopfsatz entsteht (CSRF-Schutz)", auth == [], auth)
check("Cookie ALLEIN -> kein Merker", "jarvis_sitzung_cookie" not in s)
auth, s = mw_lauf([("Authorization", "Bearer " + T2), ("Cookie", ck)])
check("Klartext-Token bleibt unberuehrt (Apps)", auth == ["Bearer " + T2], auth)
check("Klartext-Token -> kein Merker", "jarvis_sitzung_cookie" not in s)
auth, _ = mw_lauf([("Authorization", "Bearer " + c1), ("Cookie", "a=b"), ("Cookie", ck)])
check("mehrere Cookie-Kopfzeilen werden zusammen gelesen", auth == ["Bearer " + T1], auth)
_, s = mw_lauf([("Authorization", "Bearer " + c1), ("Cookie", ck)], typ="websocket")
check("WebSocket-Scope wird nicht umgeschrieben (Aufloesung ueber _token_aufloesen)",
      "jarvis_sitzung_cookie" not in s)

# ── [C] echte Ruempfe aus main.py ────────────────────────────────────────────
print("\n[C] _sitzung_antwort und _token_aufloesen (echte Ruempfe)")
MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MAIN_AST = ast.parse(MAIN_SRC)
FN = {}
for k in ast.walk(MAIN_AST):
    if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FN.setdefault(k.name, []).append(k)


def fdef(name):
    t = FN.get(name, [])
    if len(t) != 1:
        abbruch("main.py: %d Definitionen von %s (erwartet genau 1)" % (len(t), name))
    return t[0]


def rumpf(name, ns):
    k = ast.parse(ast.get_source_segment(MAIN_SRC, fdef(name)) or "").body[0]
    k.decorator_list = []
    exec(compile(ast.Module(body=[k], type_ignores=[]), "main.py:" + name, "exec"), ns)
    return ns[name]


NS = {"Request": object, "WebSocket": object, "JSONResponse": JSONResponse,
      "_sitzung_cookie": sc, "_sitzung": types.SimpleNamespace(max_alter_s=lambda: 43200)}
sitzung_antwort = rumpf("_sitzung_antwort", NS)
ws_token = rumpf("_token_aufloesen", NS)


class Req:
    def __init__(self, headers=None, scheme="https", scope=None):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.url = types.SimpleNamespace(scheme=scheme)
        self.scope = scope or {}


def koerper(resp):
    import json
    return json.loads(resp.body)


def cookies(resp):
    return [v.decode() for k, v in resp.raw_headers if k == b"set-cookie"]


d = {"success": True, "token": T1, "username": "anna"}
r = sitzung_antwort(Req({"X-Jarvis-Sitzung": "cookie"}), dict(d))
check("Anmelde-Kopf + https -> Koerper traegt nur das CSRF-Token",
      koerper(r)["token"] == sc.csrf_fuer(T1) and T1 not in r.body.decode(), koerper(r))
check("Anmelde-Kopf + https -> Cookie mit echtem Token",
      len(cookies(r)) == 1 and sc.cookie_aus_kopf(cookies(r)[0].split(";", 1)[0]) == T1, cookies(r))
check("Anmelde-Kopf + https -> uebrige Felder bleiben", koerper(r).get("username") == "anna")
r = sitzung_antwort(Req({}), dict(d))
check("ohne Kopf (Apps) -> echtes Token im Koerper, kein Cookie",
      koerper(r)["token"] == T1 and not cookies(r))
r = sitzung_antwort(Req({"X-Jarvis-Sitzung": "cookie"}, scheme="http"), dict(d))
check("ohne https -> echtes Token, kein Cookie (kein stiller Fehlschlag)",
      koerper(r)["token"] == T1 and not cookies(r))
r = sitzung_antwort(Req({}, scope={"jarvis_sitzung_cookie": True}), dict(d))
check("Cookie-angemeldete Anfrage (Kennwortwechsel) -> wieder Cookie + CSRF",
      koerper(r)["token"] == sc.csrf_fuer(T1) and len(cookies(r)) == 1)
r = sitzung_antwort(Req({"X-Jarvis-Sitzung": "cookie"}), {"success": False, "error": "x"})
check("ohne Token (Fehlschlag) -> kein Cookie", not cookies(r) and "token" not in koerper(r))

ws_mit = types.SimpleNamespace(cookies={sc.COOKIE_NAME: K1})
ws_ohne = types.SimpleNamespace(cookies={})
check("_token_aufloesen: CSRF + Cookie -> echtes Token", ws_token(ws_mit, c1) == T1)
check("_token_aufloesen: CSRF ohne Cookie -> ''", ws_token(ws_ohne, c1) == "")
check("_token_aufloesen: fremdes CSRF -> ''", ws_token(ws_mit, sc.csrf_fuer(T2)) == "")
check("_token_aufloesen: Klartext/API-Key unveraendert", ws_token(ws_ohne, "apikey123") == "apikey123")
check("_token_aufloesen: kein String -> ''", ws_token(ws_ohne, None) == "")

# ── [D] Durchstich durch eine echte FastAPI-App ──────────────────────────────
print("\n[D] Durchstich FastAPI + Cookie-Jar (https)")
app = FastAPI()
app.add_middleware(sc.SitzungCookieMiddleware)
GESEHEN = []


@app.middleware("http")
async def aussen(request, call_next):   # wie die BaseHTTPMiddleware-Schichten in main.py
    return await call_next(request)


async def pruefe(request: Request) -> str:
    t = request.headers.get("Authorization", "").replace("Bearer ", "")
    GESEHEN.append(t)
    if t not in (T1, T2):
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    return t.split(":")[0]


@app.post("/login")
async def login(request: Request):
    return sitzung_antwort(request, {"success": True, "token": T1})


@app.post("/geschuetzt")
async def geschuetzt(user: str = Depends(pruefe)):
    return {"user": user}


cl = TestClient(app, base_url="https://jarvis.beispiel.de")
r = cl.post("/login", headers={"X-Jarvis-Sitzung": "cookie"})
csrf = r.json().get("token", "")
check("Anmeldung: Koerper ohne echtes Token", T1 not in r.text and csrf == c1, r.text)
check("Anmeldung: Cookie im Jar", sc.wert_lesen(cl.cookies.get(sc.COOKIE_NAME, "")) == T1,
      dict(cl.cookies))
r = cl.post("/geschuetzt", headers={"Authorization": "Bearer " + csrf})
check("CSRF + Cookie -> angemeldet", r.status_code == 200 and r.json().get("user") == "anna",
      (r.status_code, r.text))
check("Positivkontrolle: Dependency sah das echte Token", GESEHEN[-1:] == [T1], GESEHEN[-1:])
r = cl.post("/geschuetzt")
check("Cookie ohne CSRF-Kopf -> 401 (fremde Seite kann nichts ausloesen)", r.status_code == 401)
r = cl.post("/geschuetzt", headers={"Authorization": "Bearer " + sc.csrf_fuer(T2)})
check("CSRF eines anderen Tokens -> 401", r.status_code == 401)
@app.post("/login_ad")
async def login_ad(request: Request):
    return sitzung_antwort(request, {"success": True, "token": TAD})


async def pruefe_ad(request: Request) -> str:
    t = request.headers.get("Authorization", "").replace("Bearer ", "")
    if t != TAD:
        raise HTTPException(status_code=401, detail="Nicht authentifiziert")
    return "ad"


@app.post("/geschuetzt_ad")
async def geschuetzt_ad(user: str = Depends(pruefe_ad)):
    return {"user": user}


cl3 = TestClient(app, base_url="https://jarvis.beispiel.de")
r = cl3.post("/login_ad", headers={"X-Jarvis-Sitzung": "cookie"})
r = cl3.post("/geschuetzt_ad", headers={"Authorization": "Bearer " + r.json().get("token", "")})
check("AD-Anmeldung (contoso\\name) ueber Cookie-Jar -> angemeldet (DEV-Befund 12.10.)",
      r.status_code == 200, (r.status_code, r.text))
cl2 = TestClient(app, base_url="https://jarvis.beispiel.de")
r = cl2.post("/geschuetzt", headers={"Authorization": "Bearer " + csrf})
check("CSRF ohne Cookie (gestohlen, anderer Browser) -> 401", r.status_code == 401)
r = cl2.post("/geschuetzt", headers={"Authorization": "Bearer " + T2})
check("Klartext-Bearer (Apps) -> weiter angemeldet", r.status_code == 200)

# ── [E] Regeln an main.py ────────────────────────────────────────────────────
print("\n[E] Regeln an main.py")


def ist_name(n, *namen):
    return (isinstance(n, ast.Name) and n.id in namen) or (
        isinstance(n, ast.Attribute) and n.attr in namen)


reg = [n for n in MAIN_AST.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
       and ist_name(n.value.func, "add_middleware") and n.value.args
       and ist_name(n.value.args[0], "SitzungCookieMiddleware")]
check("Middleware auf Modulebene registriert", len(reg) == 1, len(reg))

# Jede Antwort mit einem "token"-Feld. Ausnahmen MIT Grund:
#  - _addin_sso_ablauf: Outlook-Aufgabenfenster, laeuft in einem fremden Rahmen
#    bzw. einer Office-WebView – dort kommt ein SameSite=Strict-Cookie nicht an.
#  - sitzung_auf_cookie: gibt bereits das CSRF-Token aus (csrf_fuer), kein Token.
AUSNAHMEN = {"_addin_sso_ablauf", "sitzung_auf_cookie"}
treffer, falsch = [], []
for name, defs in FN.items():
    for f in defs:
        for c in ast.walk(f):
            if not isinstance(c, ast.Call):
                continue
            for a in c.args:
                if isinstance(a, ast.Dict) and any(
                        isinstance(k, ast.Constant) and k.value == "token" for k in a.keys):
                    treffer.append(name)
                    if not ist_name(c.func, "_sitzung_antwort") and name not in AUSNAHMEN:
                        falsch.append("%s:%d" % (name, c.lineno))
check("Positivkontrolle: Token-Antworten gefunden (Anmeldung, Kennwortwechsel)",
      "_login_ablauf" in treffer and "change_password" in treffer, sorted(set(treffer)))
check("jede Token-Antwort laeuft ueber _sitzung_antwort (ausser benannte Ausnahmen)",
      not falsch, falsch)
check("Ausnahmen existieren noch (sonst ist die Liste veraltet)",
      all(a in treffer for a in AUSNAHMEN), sorted(AUSNAHMEN - set(treffer)))
sac = fdef("sitzung_auf_cookie")
csrf_aufruf = [c for c in ast.walk(sac) if isinstance(c, ast.Call) and ist_name(c.func, "csrf_fuer")]
check("sitzung_auf_cookie gibt nur ein CSRF-Token aus", len(csrf_aufruf) == 1)
dek = [d for d in sac.decorator_list if isinstance(d, ast.Call) and d.args
       and isinstance(d.args[0], ast.Constant) and d.args[0].value == "/api/sitzung/cookie"
       and ist_name(d.func, "post")]
check("Route POST /api/sitzung/cookie", len(dek) == 1)
dep = [d for d in sac.args.defaults if isinstance(d, ast.Call) and d.args
       and ist_name(d.args[0], "require_auth")]
check("Umstellung nur angemeldet (require_auth)", len(dep) == 1)


# Jede Funktion, die ein "token" aus einer Nachricht, einem Koerper oder einer
# Adresse liest UND verify_token ruft, muss es ueber _token_aufloesen fuehren –
# die Middleware sieht nur den Kopfsatz. Gemessen statt gelistet: eine neue
# Funktion dieser Art faellt von selbst unter die Regel. Ausnahmen MIT Grund:
#  - Adressen (?token=): dort steht nie das CSRF-Token – Datei-Adressen tragen
#    Abruf-Schluessel (BSI M4), der Kamera-Strom einen eigenen Stream-Schluessel.
ADRESS_AUSNAHMEN = {"_query_benutzer", "require_auth_or_query", "vision_mjpeg_stream"}


def eltern_von(f):
    e = {}
    for p in ast.walk(f):
        for c in ast.iter_child_nodes(p):
            e[c] = p
    return e


def ueber_aufloesen(f, g, eltern):
    """``g`` (ein .get("token")) steht innerhalb eines _token_aufloesen-Aufrufs –
    direkt oder ueber eine Zwischenvariable, die danach hineingeht."""
    p = eltern.get(g)
    while p is not None and not isinstance(p, ast.stmt):
        if isinstance(p, ast.Call) and ist_name(p.func, "_token_aufloesen"):
            return True
        p = eltern.get(p)
    if isinstance(p, ast.Assign) and len(p.targets) == 1 and isinstance(p.targets[0], ast.Name):
        var = p.targets[0].id
        return any(isinstance(c, ast.Call) and ist_name(c.func, "_token_aufloesen") and len(c.args) > 1
                   and isinstance(c.args[1], ast.Name) and c.args[1].id == var for c in ast.walk(f))
    return False


geprueft, roh = [], []
for name, defs in FN.items():
    for f in defs:
        gets = [c for c in ast.walk(f) if isinstance(c, ast.Call) and ist_name(c.func, "get")
                and c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == "token"]
        ruft_vt = any(isinstance(c, ast.Call) and ist_name(c.func, "verify_token") for c in ast.walk(f))
        if not gets or not ruft_vt or name in ADRESS_AUSNAHMEN:
            continue
        geprueft.append(name)
        el = eltern_von(f)
        roh += ["%s:%d" % (name, g.lineno) for g in gets if not ueber_aufloesen(f, g, el)]
check("Positivkontrolle: Handler mit Token in Nachricht/Koerper gefunden",
      {"handle_ws_message", "userchat_ws", "verify_token_endpoint", "api_feedback"} <= set(geprueft),
      sorted(geprueft))
check("Token aus Nachricht/Koerper geht durch _token_aufloesen", not roh, roh)
check("Adress-Ausnahmen existieren noch (sonst ist die Liste veraltet)",
      all(a in FN for a in ADRESS_AUSNAHMEN), sorted(a for a in ADRESS_AUSNAHMEN if a not in FN))

lo = fdef("logout")
check("logout loescht das Cookie",
      any(isinstance(c, ast.Call) and ist_name(c.func, "loeschen") for c in ast.walk(lo)))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
