#!/usr/bin/env python3
"""Waechter: Anfragerumpfe der Endpunkte OHNE Sitzung sind gedeckelt.

Befund 2026-11-27 (Speicher-DoS ohne Anmeldung): ``/api/login``,
``/api/verify-token``, ``/api/addin/diag`` u. a. lasen den ganzen Rumpf in den
Speicher, bevor irgendeine Pruefung griff. ``backend/rumpf_deckel.py`` deckelt
ihn jetzt als ASGI-Schicht VOR der Anwendung.

Teil A – Wirkung an der echten Middleware (ASGI-Aufrufe von Hand):
  * angekuendigte Laenge ueber der Grenze → 413, KEIN Byte gelesen, App nie gerufen
  * ohne Ankuendigung (stueckweise) → 413 nach hoechstens grenze+Stueck Byte
  * kleiner Rumpf → kommt byte-gleich bei der App an (auch in mehreren Stuecken)
  * Pfad ausserhalb der Liste → unberuehrt durchgereicht (auch gross)
Teil B – Regel am Syntaxbaum von ``backend/main.py``:
  * jede schreibende Route OHNE ``Depends(`` in der Signatur, die einen Rumpf
    liest, steht in ``GRENZEN`` (keine gepflegte Liste im Waechter)
  * jeder Pfad in ``GRENZEN`` ist eine Route in main.py (kein toter Eintrag)
  * die Middleware ist in main.py registriert

    python3 tests/test_rumpf_deckel.py      Exit 0 gruen, 1 rot, 2 konnte nicht laufen
"""
import ast
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import rumpf_deckel  # noqa: E402

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


# ── Teil A: Wirkung ─────────────────────────────────────────────────────────

def _lauf(pfad, stuecke, laenge=None, grenzen=None):
    """Eine Anfrage durch die Middleware. Rueckgabe: (status, gelesen, app_rumpf)."""
    gelesen = {"n": 0, "aufrufe": 0}
    app_sah = {"rumpf": None}
    gesendet = []

    async def app(scope, receive, send):
        teile = []
        while True:
            m = await receive()
            teile.append(m.get("body", b""))
            if not m.get("more_body"):
                break
        app_sah["rumpf"] = b"".join(teile)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    reste = list(stuecke)

    async def receive():
        gelesen["aufrufe"] += 1
        if not reste:
            return {"type": "http.disconnect"}
        s = reste.pop(0)
        gelesen["n"] += len(s)
        return {"type": "http.request", "body": s, "more_body": bool(reste)}

    async def send(m):
        gesendet.append(m)

    kopf = []
    if laenge is not None:
        kopf.append((b"content-length", str(laenge).encode()))
    scope = {"type": "http", "path": pfad, "headers": kopf, "method": "POST"}
    mw = rumpf_deckel.RumpfDeckel(app, grenzen)
    asyncio.run(mw(scope, receive, send))
    status = next((m["status"] for m in gesendet if m["type"] == "http.response.start"), None)
    return status, gelesen, app_sah["rumpf"]


print("Teil A – Wirkung der Middleware")
G = {"/api/x": 1000}

# Positivkontrolle: der Messaufbau leitet eine erlaubte Anfrage an die App
st, gel, rumpf = _lauf("/api/x", [b"a" * 10], laenge=10, grenzen=G)
if st != 200 or rumpf != b"a" * 10:
    print(f"ABBRUCH: Positivkontrolle – kleine Anfrage kam nicht durch ({st}, {rumpf!r})")
    sys.exit(2)
check(True, "Positivkontrolle: kleiner Rumpf erreicht die App (200)")

st, gel, rumpf = _lauf("/api/x", [b"a" * 5000], laenge=5000, grenzen=G)
check(st == 413, f"angekuendigt 5000 > 1000 → 413 (ist {st})")
check(gel["aufrufe"] == 0, f"dabei kein receive() (ist {gel['aufrufe']})")
check(rumpf is None, "App wurde nicht gerufen")

st, gel, rumpf = _lauf("/api/x", [b"b" * 300] * 50, laenge=None, grenzen=G)
check(st == 413, f"ohne Ankuendigung 50x300 → 413 (ist {st})")
check(gel["n"] <= 1000 + 300, f"hoechstens grenze+Stueck gelesen (ist {gel['n']})")
check(rumpf is None, "App wurde nicht gerufen (stueckweise)")

st, gel, rumpf = _lauf("/api/x", [b"b" * 300] * 50, laenge=100, grenzen=G)
check(st == 413, f"falsche (zu kleine) Ankuendigung hilft nicht → 413 (ist {st})")

st, gel, rumpf = _lauf("/api/x", [b"12", b"34", b"56"], laenge=None, grenzen=G)
check(st == 200 and rumpf == b"123456", f"mehrere kleine Stuecke kommen zusammen an ({rumpf!r})")

st, gel, rumpf = _lauf("/api/x", [b"x" * 1000], laenge=1000, grenzen=G)
check(st == 200 and rumpf is not None and len(rumpf) == 1000, "genau an der Grenze → durch")

st, gel, rumpf = _lauf("/api/x", [b"x"], laenge=None, grenzen=G)
check(st == 200, "Laenge ohne Kopf, klein → durch")

st, gel, rumpf = _lauf("/api/anders", [b"z" * 5000], laenge=5000, grenzen=G)
check(st == 200 and rumpf is not None and len(rumpf) == 5000, "fremder Pfad bleibt ungedeckelt")

# Ein ungueltiger Content-Length-Kopf ist kein Freifahrtschein
async def _ungueltig():
    gesendet = []

    async def app(scope, receive, send):
        gesendet.append("app")

    async def send(m):
        gesendet.append(m)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    mw = rumpf_deckel.RumpfDeckel(app, G)
    await mw({"type": "http", "path": "/api/x", "headers": [(b"content-length", b"abc")]},
             receive, send)
    return gesendet
g = asyncio.run(_ungueltig())
check("app" not in g and any(isinstance(m, dict) and m.get("status") == 413 for m in g),
      "ungueltiger Content-Length → 413")

# Die echten Grenzen: Anmeldung klein, Inhalt groesser
check(rumpf_deckel.grenze_fuer("/api/login") == rumpf_deckel.KLEIN, "/api/login hat die kleine Grenze")
check(rumpf_deckel.grenze_fuer("/api/addin/diag") == rumpf_deckel.KLEIN, "/api/addin/diag hat die kleine Grenze")
check(rumpf_deckel.KLEIN <= 64 * 1024, f"kleine Grenze hoechstens 64 KB (ist {rumpf_deckel.KLEIN})")
check(rumpf_deckel.INHALT <= 8 * 1024 * 1024, f"Inhaltsgrenze hoechstens 8 MB (ist {rumpf_deckel.INHALT})")
st, gel, rumpf = _lauf("/api/login", [b"x" * 200_000], laenge=200_000)
check(st == 413 and gel["aufrufe"] == 0, "echte Liste: 200 KB an /api/login → 413 ungelesen")


# ── Teil B: Regel ueber main.py ─────────────────────────────────────────────
print("Teil B – Regel am Syntaxbaum von main.py")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(MAIN)

# Modul-Aliase (from backend import x as _x) fuer Pfade wie _csp.MELDE_PFAD
aliase = {}
for n in baum.body:
    if isinstance(n, ast.ImportFrom) and n.module == "backend":
        for a in n.names:
            aliase[a.asname or a.name] = a.name


def _pfad(ausdruck):
    if isinstance(ausdruck, ast.Constant) and isinstance(ausdruck.value, str):
        return ausdruck.value
    if (isinstance(ausdruck, ast.Attribute) and isinstance(ausdruck.value, ast.Name)
            and ausdruck.value.id in aliase):
        datei = ROOT / "backend" / (aliase[ausdruck.value.id] + ".py")
        if datei.exists():
            for k in ast.parse(datei.read_text(encoding="utf-8")).body:
                if (isinstance(k, ast.Assign) and len(k.targets) == 1
                        and isinstance(k.targets[0], ast.Name)
                        and k.targets[0].id == ausdruck.attr
                        and isinstance(k.value, ast.Constant)):
                    return k.value.value
    return None


LESER_ATTR = {"json", "body", "form", "stream"}
LESER_NAMEN = {"_json_objekt", "_rumpf_mit_deckel"}


def _liest_rumpf(fn):
    for k in ast.walk(fn):
        if isinstance(k, ast.Call):
            f = k.func
            if isinstance(f, ast.Name) and f.id in LESER_NAMEN:
                return True
            if (isinstance(f, ast.Attribute) and f.attr in LESER_ATTR
                    and isinstance(f.value, ast.Name) and f.value.id in ("request", "req")):
                return True
    return False


def _hat_depends(fn):
    for d in list(fn.args.defaults) + list(fn.args.kw_defaults):
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "Depends":
            return True
    return False


funktionen = {n.name: n for n in baum.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}


def _ruft_leser(fn, gesehen=None):
    """Liest die Route (oder eine direkt gerufene _ablauf-Hilfe in main.py) den Rumpf?"""
    gesehen = gesehen or set()
    if fn.name in gesehen:
        return False
    gesehen.add(fn.name)
    if _liest_rumpf(fn):
        return True
    for k in ast.walk(fn):
        if (isinstance(k, ast.Call) and isinstance(k.func, ast.Name)
                and k.func.id in funktionen and k.func.id.startswith("_")
                and k.func.id not in LESER_NAMEN):
            if _ruft_leser(funktionen[k.func.id], gesehen):
                return True
    return False


routen, offen, unaufgeloest = set(), [], []
for n in baum.body:
    if not isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)):
        continue
    for d in n.decorator_list:
        if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                and d.args):
            continue
        p = _pfad(d.args[0])
        if p is None:
            unaufgeloest.append(n.name)
            continue
        routen.add(p)
        schreibend = d.func.attr in ("post", "put", "patch", "delete")
        if d.func.attr == "api_route":
            meth = next((kw.value for kw in d.keywords if kw.arg == "methods"), None)
            schreibend = meth is None or any(
                isinstance(e, ast.Constant) and str(e.value).upper() in ("POST", "PUT", "PATCH", "DELETE")
                for e in getattr(meth, "elts", []))
        if not schreibend:
            continue
        if _hat_depends(n):
            continue
        if _ruft_leser(n) and rumpf_deckel.grenze_fuer(p) is None:
            offen.append(f"{p} ({n.name}, Zeile {n.lineno})")

# Positivkontrolle der Sonde: die bekannten Faelle muessen als "ohne Depends,
# liest Rumpf" erkannt werden – sonst ist "nichts offen" trivial.
_bekannt = {"login", "verify_token_endpoint", "addin_diag_melden"}
_erkannt = {n for n in _bekannt if n in funktionen and not _hat_depends(funktionen[n])
            and _ruft_leser(funktionen[n])}
if _erkannt != _bekannt:
    print(f"ABBRUCH: Positivkontrolle – Sonde erkennt {_bekannt - _erkannt} nicht als Rumpf-Leser")
    sys.exit(2)
check(True, "Positivkontrolle: login/verify-token/addin-diag werden als Rumpf-Leser erkannt")
check(not unaufgeloest, f"jeder Routenpfad ist aufloesbar ({unaufgeloest})")
check(not offen, "jede Route ohne Depends, die einen Rumpf liest, ist gedeckelt"
      + (": " + "; ".join(offen) if offen else ""))
tot = sorted(set(rumpf_deckel.GRENZEN) - routen)
check(not tot, f"jeder gedeckelte Pfad ist eine Route in main.py ({tot})")

registriert = any(
    isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute) and k.func.attr == "add_middleware"
    and k.args and isinstance(k.args[0], ast.Attribute) and k.args[0].attr == "RumpfDeckel"
    for k in ast.walk(baum))
check(registriert, "RumpfDeckel ist per app.add_middleware registriert")

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
