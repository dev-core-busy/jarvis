#!/usr/bin/env python3
"""Waechter: gespeichertes XSS ueber SVG/HTML aus Datei-Endpunkten (Befund B2, 2026-11).

Gemessen wird die WIRKUNG an den ausgelieferten Kopfzeilen: die ECHTEN
Endpunkte (``get_document``, ``read_knowledge_file_raw``, ``wissen_file``,
``get_branding_logo``) und die ECHTEN Middlewares (``_csp_kopfzeilen``,
``_datei_aktiv_kopfzeilen``) werden per AST aus ``backend/main.py``
geschnitten, in eine FastAPI-Probe-App in DERSELBEN Reihenfolge eingehaengt
und ueber den TestClient abgerufen:

  * SVG/HTML aus Datei-Endpunkten: ``attachment`` + Sandbox-CSP + nosniff;
  * PNG/PDF/Text bleiben ``inline`` (Vorschau, <img>) und ohne Sandbox;
  * das Branding-Logo (SVG, oeffentlich) bekommt die Sandbox-CSP;
  * eine App-SEITE (text/html ausserhalb der Datei-Endpunkte) behaelt ihre
    App-CSP – sonst liefe dort kein Skript mehr.

Kein ``backend.config``. Exit 0 gruen, 1 FAIL, 2 konnte nicht laufen.
"""
from __future__ import annotations

import ast
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
MAIN = ROOT / "backend" / "main.py"

try:
    from fastapi import FastAPI, Depends, Request  # noqa: F401
    from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
    from fastapi.testclient import TestClient
except ImportError as e:
    print("ABBRUCH: fastapi/TestClient fehlt (%s)" % e, flush=True)
    sys.exit(2)

OK = FAIL = 0


def check(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


sys.modules["backend.config"] = types.ModuleType("backend.config")   # nie echt laden
from backend import datei_auslieferung as datei  # noqa: E402

BAUM = ast.parse(MAIN.read_text(encoding="utf-8"))
ENDPUNKTE = {"get_document": ("/api/documents/{name}",),
             "read_knowledge_file_raw": ("/api/knowledge/file_raw",),
             "wissen_file": ("/api/wissen/file",),
             "get_branding_logo": ("/api/branding/logo",)}
MIDDLEWARES = ["_csp_kopfzeilen", "_datei_aktiv_kopfzeilen"]
HELFER = {"_liegt_unter"}
gesucht = set(ENDPUNKTE) | set(MIDDLEWARES) | HELFER
teile, gefunden = [], set()
for k in BAUM.body:
    if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name in gesucht:
        k.decorator_list = []
        teile.append(k)
        gefunden.add(k.name)
if gesucht - gefunden:
    print("ABBRUCH: in main.py nicht gefunden: %s" % sorted(gesucht - gefunden), flush=True)
    sys.exit(2)
# Reihenfolge der Middlewares wie in main.py (spaeter registriert = aussen)
reihe = [k.name for k in BAUM.body
         if isinstance(k, ast.AsyncFunctionDef) and k.name in MIDDLEWARES]

SAND = Path(tempfile.mkdtemp(prefix="datei_ausl_"))
DOCS = SAND / "data" / "documents"
DOCS.mkdir(parents=True)
RAG = SAND / "data" / "rag"
RAG.mkdir(parents=True)
CAP = "0123456789abcdef0123456789abcdef"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
HTML = b"<html><script>alert(1)</script></html>"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
for name, inhalt in ((f"{CAP}__bild.svg", SVG), (f"{CAP}__bild.png", PNG),
                     (f"{CAP}__seite.html", HTML), (f"{CAP}__doku.pdf", b"%PDF-1.4\n")):
    (DOCS / name).write_bytes(inhalt)
for name, inhalt in (("x.svg", SVG), ("x.html", HTML), ("x.htm", HTML), ("x.png", PNG),
                     ("x.pdf", b"%PDF-1.4\n"), ("x.md", b"# Titel"), ("x.js", b"alert(1)"),
                     ("x.xml", b"<a/>"), ("x.txt", b"hallo")):
    (RAG / name).write_bytes(inhalt)
LOGO = SAND / "logo.svg"
LOGO.write_bytes(SVG)

_stub_k = types.ModuleType("backend.tools.knowledge")
_stub_k._get_folders = lambda: [RAG]
_stub_k.PROJECT_ROOT = SAND
_stub_k._bounded_call = lambda fn, deckel, rueck: fn()
sys.modules["backend.tools.knowledge"] = _stub_k
_stub_l = types.ModuleType("backend.learning")
_stub_l.LEARNED_DIR = SAND / "learned"
sys.modules["backend.learning"] = _stub_l
_stub_g = types.ModuleType("backend.knowledge_groups")
_stub_g.get_assignment = lambda rel: ["g1"]
sys.modules["backend.knowledge_groups"] = _stub_g


class _Csp:
    @staticmethod
    def kopfzeilen(pfad, host):
        return {"Content-Security-Policy": "default-src 'self'; script-src 'self'"}


def _auth():
    return "u"


NS = {
    "Path": Path, "FileResponse": FileResponse, "JSONResponse": JSONResponse,
    "Request": Request, "Depends": Depends, "require_auth_or_query": _auth,
    "__file__": str(SAND / "backend" / "main.py"), "_datei": datei, "_csp": _Csp,
    "_routing_pfad": lambda r: r.scope["path"],
    "_documents": types.SimpleNamespace(may_access=lambda n, u, a: True),
    "_is_admin_user": lambda u: False,
    "_editable_groups_for": lambda u: [{"id": "g1"}],
    "_wissen_datei_ziel": lambda rel: ((RAG / rel), None),
    "_WISSEN_DATEI_DECKEL": 5.0,
    "_branding_logo_path": lambda v, k: LOGO,
}
import asyncio  # noqa: E402
NS["asyncio"] = asyncio
exec(compile(ast.Module(body=teile, type_ignores=[]), str(MAIN), "exec"), NS)

app = FastAPI()
for fn, (pfad,) in ENDPUNKTE.items():
    app.add_api_route(pfad, NS[fn], methods=["GET"])


@app.get("/chat")
async def _seite():
    return HTMLResponse("<html><script src='/static/js/app.js'></script></html>")


for mw in reihe:
    app.middleware("http")(NS[mw])
c = TestClient(app)


def holen(url):
    r = c.get(url)
    return (r.status_code, r.headers.get("content-disposition", ""),
            r.headers.get("content-security-policy", ""),
            r.headers.get("x-content-type-options", ""), r.headers.get("content-type", ""))


# ── Positivkontrolle: Messaufbau liefert Dateien aus ─────────────────────
st, *_ = holen(f"/api/documents/{CAP}__bild.png")
st2, _d, csp_app, *_ = holen("/chat")
if st != 200 or st2 != 200 or "script-src 'self'" not in csp_app:
    print("ABBRUCH: Positivkontrolle – Probe-App liefert nicht (%s/%s/%r)"
          % (st, st2, csp_app), flush=True)
    sys.exit(2)
if reihe != MIDDLEWARES:
    print("ABBRUCH: Middleware-Reihenfolge in main.py unerwartet: %s" % reihe, flush=True)
    sys.exit(2)

SANDBOX = "sandbox"


def aktiv_geschuetzt(url, text):
    st, disp, csp, nos, ct = holen(url)
    check(st == 200, "%s: ausgeliefert (200)" % text)
    check(disp.startswith("attachment"), "%s: als Download (%s)" % (text, disp or "-"))
    check(SANDBOX in csp and "default-src 'none'" in csp,
          "%s: Sandbox-CSP (%s)" % (text, csp or "-"))
    check(nos == "nosniff", "%s: nosniff" % text)


def harmlos_inline(url, text):
    st, disp, csp, _nos, ct = holen(url)
    check(st == 200 and disp.startswith("inline"), "%s: inline (%s)" % (text, disp or "-"))
    check(SANDBOX not in csp, "%s: keine Sandbox-CSP (Vorschau bleibt)" % text)


print("\n/api/documents/{name} (Chat-Anhang, Werkzeug-Ergebnis)")
aktiv_geschuetzt(f"/api/documents/{CAP}__bild.svg", "SVG")
aktiv_geschuetzt(f"/api/documents/{CAP}__seite.html", "HTML")
harmlos_inline(f"/api/documents/{CAP}__bild.png", "PNG")
harmlos_inline(f"/api/documents/{CAP}__doku.pdf", "PDF")

print("\n/api/knowledge/file_raw")
for n in ("x.svg", "x.html", "x.htm", "x.js", "x.xml"):
    st, disp, csp, nos, ct = holen("/api/knowledge/file_raw?path=data/rag/" + n)
    check(st == 200 and disp.startswith("attachment"), "%s: als Download (%s)" % (n, disp))
    if datei.ist_aktiv(ct):
        check(SANDBOX in csp, "%s: Sandbox-CSP bei aktivem Typ %s" % (n, ct))
for n in ("x.png", "x.pdf", "x.md", "x.txt"):
    harmlos_inline("/api/knowledge/file_raw?path=data/rag/" + n, n)
st, disp, csp, nos, ct = holen("/api/knowledge/file_raw?path=data/rag/x.md")
check(ct.startswith("text/plain"), "x.md als text/plain (im Tab lesbar): %s" % ct)

print("\n/api/wissen/file")
for n in ("x.svg", "x.html", "x.htm"):
    aktiv_geschuetzt("/api/wissen/file?path=" + n, n)
for n in ("x.png", "x.pdf", "x.txt", "x.md"):
    harmlos_inline("/api/wissen/file?path=" + n, n)

print("\n/api/branding/logo (oeffentlich, SVG erlaubt)")
st, disp, csp, nos, ct = holen("/api/branding/logo")
check(st == 200 and ct.startswith("image/svg+xml"), "SVG-Logo wird weiter ausgeliefert")
check(SANDBOX in csp and "default-src 'none'" in csp, "SVG-Logo mit Sandbox-CSP")
check(nos == "nosniff", "SVG-Logo mit nosniff")

print("\nApp-Seite bleibt unberuehrt")
st, disp, csp, nos, ct = holen("/chat")
check(SANDBOX not in csp and "script-src 'self'" in csp, "/chat behaelt die App-CSP")

print("\nRegel (datei_auslieferung)")
for t in ("image/svg+xml", "text/html; charset=utf-8", "application/xhtml+xml",
          "text/xml", "application/rss+xml", "application/javascript"):
    check(datei.disposition(t) == "attachment" and datei.ist_aktiv(t), "aktiv/Download: %s" % t)
for t in ("image/png", "image/jpeg", "application/pdf", "text/plain; charset=utf-8"):
    check(datei.disposition(t) == "inline" and not datei.ist_aktiv(t), "harmlos/inline: %s" % t)
check(datei.kopfzeilen("/api/irgendwas", "image/svg+xml", True) != {},
      "neuer Endpunkt mit Content-Disposition ist mitgeschuetzt")
check(datei.kopfzeilen("/settings", "text/html", False) == {},
      "App-Seite ohne Content-Disposition bekommt keine Sandbox")

# Bestandsregel: Chat-Anhang-Endpunkt bleibt Raster-only, Bildsuche nur Raster
QUELLE = MAIN.read_text(encoding="utf-8")
for fn in ("get_chat_attachment", "get_generated_image"):
    k = next((x for x in BAUM.body if isinstance(x, ast.AsyncFunctionDef) and x.name == fn), None)
    seg = ast.get_source_segment(QUELLE, k) if k else ""
    check(k is not None and "svg" not in seg.split('"""', 2)[-1].lower(),
          "%s liefert kein SVG aus" % fn)

print("\n" + "=" * 60)
print("  %d OK, %d FAIL" % (OK, FAIL))
print("=" * 60)
import shutil  # noqa: E402
shutil.rmtree(SAND, ignore_errors=True)
sys.exit(0 if FAIL == 0 else 1)
