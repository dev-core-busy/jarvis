#!/usr/bin/env python3
"""Waechter: BSI H7 – Sicherheits-Kopfzeilen (HSTS, X-Frame-Options, nosniff,
Referrer-Policy, frame-ancestors).

Gemessen an der WIRKUNG:
  [A] ``backend/sicherheits_kopf.py`` mit ECHTEN Zertifikaten (openssl): HSTS im
      Modus ``auto`` nur bei einem CA-signierten Zertifikat, nie bei einem
      selbst signierten oder unlesbaren, nie ueber HTTP; ``an``/``aus``/unbekannt;
      Zertifikatstausch wird bemerkt; Add-in-Seiten ohne X-Frame-Options.
  [B] ``backend/csp.py``: ``frame-ancestors`` 'self' – Office-Hosts NUR auf den
      Add-in-Seiten, in beiden Kopfzeilen-Modi.
  [C] die Middleware aus main.py (per AST, unveraendert) in einer echten
      Starlette-App mit TestClient: Kopfzeilen an HTML, JSON, statischer Datei,
      404 und am Add-in-Fenster; eine Route mit eigener Vorgabe gewinnt.
  [D] Regeln: Middleware ist registriert, Admin-Endpunkte verlangen Admin.

Braucht starlette/httpx/cryptography (venv; startet sich sonst damit neu).
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import cryptography  # noqa: F401
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient
except ImportError:
    venv_py = ROOT / "venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), __file__] + sys.argv[1:])
    print("ABBRUCH: starlette/httpx/cryptography fehlen (venv/bin/python tests/test_bsi_h7.py)")
    sys.exit(2)

OK = 0
FAIL = 0


def check(name: str, bed: bool) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


from backend import csp as CSP              # noqa: E402
from backend import sicherheits_kopf as SK  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="waechter-bsi-h7-"))


def ossl(*args):
    r = subprocess.run(["openssl", *args], capture_output=True, text=True)
    if r.returncode != 0:
        abbruch("openssl %s: %s" % (args[0], r.stderr[-300:]))


# Selbst signiert (wie security.ensure_certificates) und CA-signiert (wie ECHT)
ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=selbst",
     "-keyout", str(TMP / "s.key"), "-out", str(TMP / "selbst.crt"))
ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=Test-CA",
     "-keyout", str(TMP / "ca.key"), "-out", str(TMP / "ca.crt"))
ossl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=jarvis.firma.local",
     "-keyout", str(TMP / "l.key"), "-out", str(TMP / "l.csr"))
ossl("x509", "-req", "-in", str(TMP / "l.csr"), "-CA", str(TMP / "ca.crt"), "-CAkey",
     str(TMP / "ca.key"), "-CAcreateserial", "-days", "1", "-out", str(TMP / "ca_signiert.crt"))

EINST: dict = {}
ZERT = TMP / "server.crt"


def setze(quelle: str | None, modus=None):
    if quelle is None:
        ZERT.unlink(missing_ok=True)
    else:
        shutil.copy(TMP / quelle, ZERT)
        # mtime sicher verschieden (Cache haengt an der mtime)
        t = time.time() + len(quelle)
        os.utime(ZERT, (t, t))
    if modus is None:
        EINST.pop("hsts_modus", None)
    else:
        EINST["hsts_modus"] = modus
    SK.einstellungen_quelle(lambda k, d=None: EINST.get(k, d), ZERT)


# ── [A] Modul ────────────────────────────────────────────────────────────────
print("[A] sicherheits_kopf")
setze("ca_signiert.crt")
if SK.zertifikat_selbst_signiert() is not False:
    abbruch("Positivkontrolle: CA-signiertes Zertifikat wird nicht als solches erkannt")
check("selbst signiert wird erkannt", (setze("selbst.crt"), SK.zertifikat_selbst_signiert())[1] is True)
k = SK.kopfzeilen("/portal", True)
check("auto + selbst signiert: KEIN HSTS", "Strict-Transport-Security" not in k)
setze("ca_signiert.crt")
k = SK.kopfzeilen("/portal", True)
check("auto + CA-signiert: HSTS", k.get("Strict-Transport-Security") == SK.HSTS_WERT)
check("HSTS mindestens 1 Jahr",
      int(SK.HSTS_WERT.split("max-age=")[1].split(";")[0]) >= 365 * 24 * 3600)
check("kein includeSubDomains/preload", "includesubdomains" not in SK.HSTS_WERT.lower()
      and "preload" not in SK.HSTS_WERT.lower())
check("ueber HTTP nie HSTS", "Strict-Transport-Security" not in SK.kopfzeilen("/portal", False))
setze(None)
check("Zertifikat fehlt/unlesbar: KEIN HSTS", "Strict-Transport-Security" not in SK.kopfzeilen("/portal", True))
setze("selbst.crt", "an")
check("Modus an: HSTS auch bei selbst signiert", "Strict-Transport-Security" in SK.kopfzeilen("/", True))
setze("ca_signiert.crt", "aus")
check("Modus aus: kein HSTS auch bei CA-signiert", "Strict-Transport-Security" not in SK.kopfzeilen("/", True))
setze("selbst.crt", "quatsch")
check("unbekannter Modus gilt als auto (nicht 'an')", SK.hsts_modus() == "auto"
      and "Strict-Transport-Security" not in SK.kopfzeilen("/", True))
setze("selbst.crt")
check("(Cache gefuellt: selbst signiert)", SK.zertifikat_selbst_signiert() is True)
# Tausch OHNE einstellungen_quelle – die leert den Cache und machte die Probe
# trivial wahr (Gegenprobe "Cache ohne mtime" biss sonst nicht).
shutil.copy(TMP / "ca_signiert.crt", ZERT)
_t = time.time() + 100
os.utime(ZERT, (_t, _t))
check("Zertifikatstausch im laufenden Dienst wird bemerkt (Cache an der mtime)",
      SK.zertifikat_selbst_signiert() is False)
k = SK.kopfzeilen("/portal", True)
check("nosniff", k.get("X-Content-Type-Options") == "nosniff")
check("Referrer-Policy same-origin", k.get("Referrer-Policy") == "same-origin")
check("X-Frame-Options SAMEORIGIN", k.get("X-Frame-Options") == "SAMEORIGIN")
for p in ("/addin/taskpane.html", "/excel-addin/taskpane.html", "/static/addin/addin.js"):
    k = SK.kopfzeilen(p, True)
    check("Add-in %s: KEIN X-Frame-Options, aber nosniff" % p,
          "X-Frame-Options" not in k and k.get("X-Content-Type-Options") == "nosniff")
check("Add-in-Praefixe gleich wie in csp.py", set(SK.ADDIN_PRAEFIXE) == set(CSP._ADDIN_PRAEFIXE))

# ── [B] CSP frame-ancestors ─────────────────────────────────────────────────
print("\n[B] CSP frame-ancestors")


def direktiven(r):
    d = {}
    for teil in r.split(";"):
        w = teil.strip().split()
        if w:
            d[w[0]] = w[1:]
    return d


d = direktiven(CSP.richtlinie("/portal", ""))
check("normale Seite: frame-ancestors 'self'", d.get("frame-ancestors") == ["'self'"])
for p in ("/addin/taskpane.html", "/excel-addin/taskpane.html"):
    fa = direktiven(CSP.richtlinie(p, "")).get("frame-ancestors") or []
    check("%s: 'self' + Office-Hosts" % p, "'self'" in fa and "https://*.office.com" in fa
          and "https://*.officeapps.live.com" in fa and "https://outlook.live.com" in fa)
    check("%s: kein Platzhalter fuer beliebige Hosts" % p, not any(x in ("*", "https:", "https://*") for x in fa))
for m in ("melden", "erzwingen"):
    CSP.einstellungen_quelle(lambda k, d=None, m=m: m if k == "csp_modus" else d)
    kz = CSP.kopfzeilen("/portal")
    check("CSP-Modus %s: frame-ancestors in der Kopfzeile" % m,
          any("frame-ancestors 'self'" in v for v in kz.values()))

# ── [C] Middleware aus main.py in einer echten App ──────────────────────────
print("\n[C] Middleware an echten Antworten")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
mw = next((n for n in BAUM.body if isinstance(n, ast.AsyncFunctionDef)
           and n.name == "_sicherheits_kopfzeilen"), None)
if mw is None:
    abbruch("_sicherheits_kopfzeilen nicht in main.py")
check("Middleware ist als @app.middleware(\"http\") registriert",
      any(isinstance(dk, ast.Call) and isinstance(dk.func, ast.Attribute)
          and dk.func.attr == "middleware" and dk.args and isinstance(dk.args[0], ast.Constant)
          and dk.args[0].value == "http" for dk in mw.decorator_list))
mw.decorator_list = []
for a in mw.args.args:
    a.annotation = None
# Der ECHTE Helfer aus main.py, keine Attrappe: die Middleware entscheidet ueber
# _routing_pfad (scope["path"]), siehe tests/test_routing_pfad.py.
rp = next((n for n in BAUM.body if isinstance(n, ast.FunctionDef) and n.name == "_routing_pfad"), None)
if rp is None:
    abbruch("_routing_pfad nicht in main.py")
rp.returns = None
for a in rp.args.args:
    a.annotation = None
NS = {"_sicherheits_kopf": SK}
exec(compile(ast.fix_missing_locations(ast.Module(body=[rp, mw], type_ignores=[])), "main.py", "exec"), NS)

setze("ca_signiert.crt")


async def seite(req):
    return HTMLResponse("<p>x</p>")


async def daten(req):
    return JSONResponse({"a": 1})


async def eigen(req):
    return PlainTextResponse("x", headers={"X-Frame-Options": "DENY"})


app = Starlette(routes=[Route("/portal", seite), Route("/api/x", daten),
                        Route("/addin/taskpane.html", seite), Route("/eigen", eigen)])
# add_middleware statt app.middleware("http"): den Dekorator hat Starlette 1.x
# an der nackten Starlette-App nicht mehr (die Server laufen mit 1.7.0; lokal
# stand eine 0.41er venv, dort war der Waechter gruen – gefunden von der
# frischen venv der Sicherheits-CI, 2026-10-06). FastAPI behaelt ihn.
from starlette.middleware.base import BaseHTTPMiddleware
app.add_middleware(BaseHTTPMiddleware, dispatch=NS["_sicherheits_kopfzeilen"])
cli = TestClient(app, base_url="https://testserver")
r = cli.get("/portal")
if r.status_code != 200:
    abbruch("Positivkontrolle: Testseite nicht erreichbar (%s)" % r.status_code)
check("HTML: alle vier Kopfzeilen",
      r.headers.get("x-frame-options") == "SAMEORIGIN" and r.headers.get("x-content-type-options") == "nosniff"
      and r.headers.get("referrer-policy") == "same-origin"
      and r.headers.get("strict-transport-security") == SK.HSTS_WERT)
r = cli.get("/api/x")
check("JSON: nosniff + HSTS", r.headers.get("x-content-type-options") == "nosniff"
      and "strict-transport-security" in r.headers)
r = cli.get("/gibtsnicht")
check("404: ebenfalls mit Kopfzeilen", r.status_code == 404 and r.headers.get("x-content-type-options") == "nosniff")
r = cli.get("/addin/taskpane.html")
check("Add-in-Fenster: ohne X-Frame-Options", "x-frame-options" not in r.headers
      and r.headers.get("x-content-type-options") == "nosniff")
r = cli.get("/eigen")
check("eigene Vorgabe einer Route gewinnt (DENY bleibt)", r.headers.get("x-frame-options") == "DENY")
r = TestClient(app, base_url="http://testserver").get("/portal")
check("ueber HTTP kein HSTS", "strict-transport-security" not in r.headers)

# ── [C2] Punkt-Teile im Pfad (Code-Review 2026-10-07) ───────────────────────
# Starlette dekodiert %2F vor dem Routing: /static/addin/..%2Fportal.html kam
# als /static/addin/../portal.html an, traf das Add-in-Praefix, und StaticFiles
# lieferte das PORTAL ohne X-Frame-Options aus – einrahmbar von jeder Seite.
print("\n[C2] Punkt-Teile im Pfad")
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
STAT = TMP / "statisch"
(STAT / "addin").mkdir(parents=True)
(STAT / "portal.html").write_text("<p>PORTAL</p>", encoding="utf-8")
(STAT / "addin" / "taskpane.html").write_text("<p>ADDIN</p>", encoding="utf-8")
app2 = Starlette(routes=[Mount("/static", StaticFiles(directory=str(STAT)))])
app2.add_middleware(BaseHTTPMiddleware, dispatch=NS["_sicherheits_kopfzeilen"])
cli2 = TestClient(app2, base_url="https://testserver")
r = cli2.get("/static/addin/..%2Fportal.html")
# Positivkontrolle: der Umweg erreicht das Portal wirklich – sonst waere die
# Pruefung darunter ueber eine 404 trivial wahr.
if r.status_code != 200 or "PORTAL" not in r.text:
    abbruch("Positivkontrolle: /static/addin/..%%2Fportal.html liefert nicht das Portal (%s)"
            % r.status_code)
check("/static/addin/..%2Fportal.html: X-Frame-Options SAMEORIGIN",
      r.headers.get("x-frame-options") == "SAMEORIGIN")
r = cli2.get("/static/addin/taskpane.html")
check("Positivkontrolle: echtes Add-in-Fenster bleibt ohne X-Frame-Options",
      r.status_code == 200 and "ADDIN" in r.text and "x-frame-options" not in r.headers)
check("Modul: /static/addin/../portal.html -> SAMEORIGIN",
      SK.kopfzeilen("/static/addin/../portal.html", True).get("X-Frame-Options") == "SAMEORIGIN")
check("Modul: /addin/ (Schraegstrich am Ende) bleibt Add-in",
      "X-Frame-Options" not in SK.kopfzeilen("/addin/", True))
fa = direktiven(CSP.richtlinie("/static/addin/../portal.html", "")).get("frame-ancestors")
check("CSP: /static/addin/../portal.html nur frame-ancestors 'self'", fa == ["'self'"])
check("CSP: /novnc/../portal.html ist NICHT von der Richtlinie ausgenommen",
      bool(CSP.kopfzeilen("/novnc/../portal.html")))
check("Positivkontrolle CSP: /novnc/vnc.html bleibt ausgenommen", CSP.kopfzeilen("/novnc/vnc.html") == {})

# ── [D] Regeln ───────────────────────────────────────────────────────────────
print("\n[D] Regeln")
for name in ("security_kopfzeilen_status", "security_kopfzeilen_setzen"):
    fn = next((n for n in BAUM.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name), None)
    deps = [ast.unparse(d) for d in (fn.args.defaults if fn else [])]
    check("%s verlangt Admin (require_local_auth)" % name, any("require_local_auth" in d for d in deps))
zert = next((n for n in BAUM.body if isinstance(n, ast.ImportFrom) and n.module == "backend.security"
             and any(a.name == "CERT_FILE" for a in n.names)), None)
check("HSTS prueft das Zertifikat, mit dem der Dienst startet (security.CERT_FILE)", zert is not None)
start = (ROOT / "start_jarvis.sh").read_text(encoding="utf-8")
check("start_jarvis.sh startet mit certs/server.crt (= security.CERT_FILE)",
      "--ssl-certfile ./certs/server.crt" in start)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
