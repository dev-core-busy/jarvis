#!/usr/bin/env python3
"""Waechter: GZip nur fuer statische Inhalte und HTML-Seiten (backend/kompression.py).

Gemessen wird die WIRKUNG an einer echten Starlette-App mit der echten Weiche:
- statisches JS, HTML-Seite: gzip, Vary, entpackt byte-gleich
- ohne ``Accept-Encoding: gzip``: unkomprimiert
- ``/api/`` JSON: NIE komprimiert (Geheimnis + Eingabe = BREACH-Lage)
- ``/api/`` NDJSON-Strom: jede Zeile kommt EINZELN an, nicht gepuffert
- POST, kleine Antworten, Bilder: unkomprimiert
- Regel am AST: ``main.py`` registriert die Weiche als LETZTE Middleware
  (aeusserste Schicht – sonst saehe no_cache_static einen gepackten Rumpf).
  Ausgenommen ist allein die Host-Pruefung (Haertung B12): sie liegt noch
  weiter aussen, fasst aber keinen Rumpf an – sie weist nur ab oder reicht durch.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import gzip
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
    from starlette.routing import Route
    from backend import kompression as K
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH (Exit 2): starlette/backend.kompression nicht importierbar: {e}")
    print("  Hinweis: mit dem Projekt-venv starten (venv/bin/python tests/test_kompression.py)")
    sys.exit(2)

import starlette.middleware.gzip as _sgz  # noqa: E402

# Die Ausnahme fuer bereits komprimierte Formate (Bilder, Video, Archive) bringt
# ``GZipMiddleware`` erst in neueren Fassungen mit; requirements.txt verlangt
# starlette >= 1.3.1. Eine aeltere Umgebung kann die Zusage nicht messen.
if not hasattr(_sgz, "DEFAULT_EXCLUDED_CONTENT_TYPES"):
    import starlette as _st
    print(f"ABBRUCH (Exit 2): starlette {_st.__version__} zu alt (requirements: >= 1.3.1) – "
          "auf DEV/ECHT-Stand messen")
    sys.exit(2)

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  [{info}]" if info else ""))


JS = ("/* Probe */\n" + "var eintrag = {schluessel: 'wert', zahl: 12345};\n" * 2000).encode()
HTML = ("<!doctype html><html><body>" + "<p>Absatz mit Text</p>" * 1500 + "</body></html>")
GEHEIM = {"token": "abc123geheim", "echo": "x" * 4000}


async def js(_r):
    return Response(JS, media_type="application/javascript")


async def seite(_r):
    return HTMLResponse(HTML)


async def api_json(_r):
    return JSONResponse(GEHEIM)


async def bild(_r):
    return Response(b"\x89PNG" + b"\0" * 5000, media_type="image/png")


async def klein(_r):
    return Response(b"kurz", media_type="text/plain")


async def strom(_r):
    async def zeilen():
        for i in range(3):
            yield (f'{{"i": {i}, "fuell": "{"y" * 2000}"}}\n').encode()
            await asyncio.sleep(0.05)
    return StreamingResponse(zeilen(), media_type="application/x-ndjson")


async def seitenstrom(_r):
    """Strom OHNE Laengenangabe ausserhalb /api/ – darf gepackt, aber nicht
    gepuffert werden."""
    async def zeilen():
        for i in range(3):
            yield (f"<p>{i}{'z' * 3000}</p>\n").encode()
            await asyncio.sleep(0.05)
    return StreamingResponse(zeilen(), media_type="text/html")


async def post_seite(_r):
    return HTMLResponse(HTML)


inner = Starlette(routes=[
    Route("/static/js/probe.js", js), Route("/wissen", seite), Route("/api", seite),
    Route("/api/geheim", api_json), Route("/static/bild.png", bild), Route("/static/k.txt", klein),
    Route("/api/strom", strom), Route("/portal", post_seite, methods=["POST"]),
    Route("/webdav/x.txt", js), Route("/openapi.json", api_json),
    Route("/seitenstrom", seitenstrom),
])


# ⚠ WIE IM ECHTEN DIENST: innen liegen @app.middleware-Schichten
# (BaseHTTPMiddleware). Durch sie kommt JEDER Rumpf gestueckelt an
# (more_body=True) – ohne diese Schicht sah der Waechter einen Ein-Stueck-Rumpf
# und hielt die Mindestgroesse fuer wirksam, waehrend auf DEV eine 48-Byte-
# Antwort gepackt (73 Byte) und ohne Content-Length ausgeliefert wurde.
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


async def _durchreichen(request, call_next):
    return await call_next(request)


APP = K.KompressionsWeiche(BaseHTTPMiddleware(inner, dispatch=_durchreichen))


async def anfrage(pfad, methode="GET", gzip_an=True):
    """Roh ueber ASGI – nur so ist sichtbar, ob ein Strom in EINZELNEN
    Nachrichten ankommt (ein Client fuegt sie zusammen)."""
    kopf = [(b"host", b"t")]
    if gzip_an:
        kopf.append((b"accept-encoding", b"gzip, br"))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": methode,
             "scheme": "https", "path": pfad, "raw_path": pfad.encode(), "query_string": b"",
             "root_path": "", "headers": kopf, "client": ("t", 1), "server": ("t", 443)}
    gesendet = False

    async def receive():
        nonlocal gesendet
        if not gesendet:
            gesendet = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(3600)

    nachrichten = []

    async def send(m):
        nachrichten.append(m)

    await APP(scope, receive, send)
    start = next(m for m in nachrichten if m["type"] == "http.response.start")
    hdr = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    teile = [m.get("body", b"") for m in nachrichten if m["type"] == "http.response.body"]
    return start["status"], hdr, b"".join(teile), [t for t in teile if t]


def lauf(*a, **k):
    return asyncio.run(anfrage(*a, **k))


print("\n[1] Statisches und HTML wird komprimiert")
s, h, b, _ = lauf("/static/js/probe.js")
check("Positivkontrolle: Probe-JS kommt an", s == 200 and len(b) > 0, s)
check("JS: Content-Encoding gzip", h.get("content-encoding") == "gzip", h)
check("JS: entpackt byte-gleich", h.get("content-encoding") == "gzip" and gzip.decompress(b) == JS)
check("JS: deutlich kleiner (< 25 %)", len(b) < len(JS) / 4, (len(b), len(JS)))
check("JS: Content-Length passt zum gepackten Rumpf (nicht chunked)",
      h.get("content-length") == str(len(b)), h.get("content-length"))
check("JS: Vary: Accept-Encoding", "accept-encoding" in h.get("vary", "").lower(), h.get("vary"))
s, h, b, _ = lauf("/wissen")
check("HTML-Seite: gzip", h.get("content-encoding") == "gzip", h)
check("HTML-Seite: entpackt gleich", h.get("content-encoding") == "gzip"
      and gzip.decompress(b).decode() == HTML)
s, h, b, _ = lauf("/api")
check("/api (Doku-Seite OHNE Schraegstrich) darf komprimiert werden", h.get("content-encoding") == "gzip", h)
s, h, b, _ = lauf("/static/js/probe.js", gzip_an=False)
check("ohne Accept-Encoding: unkomprimiert", "content-encoding" not in h and b == JS, h)

print("\n[2] Was NICHT komprimiert werden darf")
s, h, b, _ = lauf("/api/geheim")
check("Positivkontrolle: API-Antwort ist gross genug fuer gzip", len(b) > K.MINDESTGROESSE, len(b))
check("/api/-JSON (Token + Eingabe): NIE komprimiert", "content-encoding" not in h, h)
s, h, b, teile = lauf("/api/strom")
check("/api/-Strom: unkomprimiert", "content-encoding" not in h, h)
check("/api/-Strom: drei Zeilen in drei EINZELNEN Nachrichten", len(teile) == 3, len(teile))
s, h, b, _ = lauf("/webdav/x.txt")
check("/webdav: unkomprimiert", "content-encoding" not in h, h)
s, h, b, _ = lauf("/openapi.json")
check("/openapi.json: unkomprimiert", "content-encoding" not in h, h)
s, h, b, _ = lauf("/portal", methode="POST")
check("POST: unkomprimiert", "content-encoding" not in h, h)
s, h, b, _ = lauf("/static/bild.png")
check("PNG (schon komprimiert): unkomprimiert", "content-encoding" not in h, h)
s, h, b, _ = lauf("/static/k.txt")
check("kleine Antwort (< MINDESTGROESSE): unkomprimiert", "content-encoding" not in h, h)
check("kleine Antwort behaelt Content-Length", h.get("content-length") == str(len(b)), h)
s, h, b, teile = lauf("/seitenstrom")
check("Strom ohne Laenge: gepackt", h.get("content-encoding") == "gzip", h)
check("Strom ohne Laenge: NICHT gepuffert (mehrere Stuecke)", len(teile) >= 3, len(teile))
check("Strom ohne Laenge: entpackt vollstaendig",
      h.get("content-encoding") == "gzip" and gzip.decompress(b).count(b"<p>") == 3)
check("komprimierbar(): WebSocket nie", not K.komprimierbar({"type": "websocket", "path": "/static/x"}))
check("komprimierbar(): /ws/users nie",
      not K.komprimierbar({"type": "http", "method": "GET", "path": "/ws/users"}))
check("komprimierbar(): /wissen (beginnt mit /w) schon",
      K.komprimierbar({"type": "http", "method": "GET", "path": "/wissen"}))

print("\n[3] Regel: Weiche ist die AEUSSERSTE Schicht")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
registriert = []
for k in ast.parse(MAIN).body:
    ziel = k.value if isinstance(k, ast.Expr) else None
    if isinstance(ziel, ast.Call) and isinstance(ziel.func, ast.Attribute) \
            and ziel.func.attr == "add_middleware" and ziel.args:
        registriert.append(ast.unparse(ziel.args[0]))
    if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in k.decorator_list:
            if isinstance(d, ast.Call) and ast.unparse(d.func) == "app.middleware":
                registriert.append(k.name)
check("Positivkontrolle: mehrere Middlewares gefunden", len(registriert) >= 5, registriert)
check("KompressionsWeiche ist registriert", any("KompressionsWeiche" in r for r in registriert), registriert)
# Die Host-Pruefung liegt bewusst noch aussen (tests/test_host_pruefung.py) und
# fasst keinen Rumpf an; jede ANDERE Middleware muss innen liegen.
AUSSEN_ERLAUBT = {"_host_pruefung.HostPruefung"}
innen = [r for r in registriert if r not in AUSSEN_ERLAUBT]
check("…und zwar als LETZTE (= aeusserste Schicht, ausser der Host-Pruefung)",
      bool(innen) and "KompressionsWeiche" in innen[-1], registriert[-3:])
check("main.py benutzt GZipMiddleware nicht direkt (nur ueber die Weiche)",
      "GZipMiddleware" not in MAIN.replace("# ", ""))

print(f"\nErgebnis: {OK} OK, {FAIL} FAIL")
sys.exit(0 if FAIL == 0 else 1)
