#!/usr/bin/env python3
"""Waechter: Haertung B12 – Anfragen mit fremdem Servernamen (Host-Kopf).

Gemessen an der WIRKUNG:
  [A] ``host_normal``: Port, eckige Klammern, Grossschreibung, Punkt am Ende.
  [B] erlaubte Namen und Modus mit ECHTEN Zertifikaten (openssl): CN und SAN
      (DNS und IP) des Zertifikats, Loopback, die Hosts aus den Einstellungen;
      ``auto`` weist nur bei CA-signiertem Zertifikat ab, bei selbst signiertem
      oder unlesbarem wird nur gemeldet; ``erzwingen``/``melden``/``aus``;
      die Liste wird nach ``TTL_S`` neu gebaut, davor nicht.
  [C] die Middleware in einer echten Starlette-App: erlaubter Name 200, fremder
      421, WebSocket mit fremdem Namen abgewiesen, ohne Host-Kopf abgewiesen,
      im Modus ``melden`` durchgelassen und protokolliert, Meldung hoechstens
      einmal je Name und Stunde.
  [D] Regel (AST) ueber backend/main.py: die Host-Pruefung ist die ZULETZT
      registrierte Middleware (also die aeusserste) und bekommt
      ``config.get_setting`` und das Server-Zertifikat.

Braucht starlette/httpx/cryptography (venv; startet sich sonst damit neu).
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import cryptography  # noqa: F401
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route, WebSocketRoute
    from starlette.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
except ImportError:
    venv_py = ROOT / "venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), __file__] + sys.argv[1:])
    print("ABBRUCH: starlette/httpx/cryptography fehlen (venv/bin/python tests/test_host_pruefung.py)")
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


from backend import host_pruefung as HP  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="waechter-host-pruefung-"))
FREMD = "boese.example"


def ossl(*args, eingabe: str | None = None):
    r = subprocess.run(["openssl", *args], capture_output=True, text=True, input=eingabe)
    if r.returncode != 0:
        abbruch("openssl %s: %s" % (args[0], r.stderr[-300:]))


# Selbst signiert (wie security.ensure_certificates) und CA-signiert mit SAN (wie ECHT)
ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=selbst.firma.local",
     "-keyout", str(TMP / "s.key"), "-out", str(TMP / "selbst.crt"))
ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=Test-CA",
     "-keyout", str(TMP / "ca.key"), "-out", str(TMP / "ca.crt"))
ossl("req", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=vm01.firma.local",
     "-keyout", str(TMP / "l.key"), "-out", str(TMP / "l.csr"))
(TMP / "san.ext").write_text("subjectAltName=DNS:jarvis.beispiel.de,DNS:ki.beispiel.de,IP:192.0.2.10\n")
ossl("x509", "-req", "-in", str(TMP / "l.csr"), "-CA", str(TMP / "ca.crt"), "-CAkey",
     str(TMP / "ca.key"), "-CAcreateserial", "-days", "1", "-extfile", str(TMP / "san.ext"),
     "-out", str(TMP / "ca_signiert.crt"))

EINST: dict = {}
ZERT = TMP / "server.crt"


def setze(quelle: str | None, **einst):
    if quelle is None:
        ZERT.unlink(missing_ok=True)
    else:
        shutil.copy(TMP / quelle, ZERT)
    EINST.clear()
    EINST.update(einst)
    HP.einstellungen_quelle(lambda k, d=None: EINST.get(k, d), ZERT)


# ── Positivkontrolle: die Zertifikate sind, was sie sein sollen ─────────────
# Das MATERIAL wird unabhaengig vom Pruefling gelesen: ob das Modul die SAN-Namen
# findet, ist eine Produkteigenschaft und gehoert als FAIL gemeldet, nicht als
# Abbruch (sonst endet die Gegenprobe "DNS-Namen fehlen" mit Exit 2).
from cryptography import x509  # noqa: E402
_z = x509.load_pem_x509_certificate((TMP / "ca_signiert.crt").read_bytes())
if "jarvis.beispiel.de" not in _z.extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName):
    abbruch("Messaufbau: das Probezertifikat traegt die SAN-Namen nicht")
setze("ca_signiert.crt")
if HP.zertifikat_lesen(ZERT)[0] is not False:
    abbruch("Positivkontrolle: CA-signiertes Zertifikat nicht als solches erkannt")
if HP.zertifikat_lesen(TMP / "selbst.crt")[0] is not True:
    abbruch("Positivkontrolle: selbst signiertes Zertifikat nicht erkannt")
if FREMD in HP.stand()[1]:
    abbruch("Messaufbau: der fremde Probename ist auf diesem Rechner ein eigener Name")

# ── [A] Normierung ──────────────────────────────────────────────────────────
print("[A] host_normal")
for roh, soll in (("Jarvis.Beispiel.DE", "jarvis.beispiel.de"),
                  ("jarvis.beispiel.de:443", "jarvis.beispiel.de"),
                  ("jarvis.beispiel.de.", "jarvis.beispiel.de"),
                  ("[::1]:443", "::1"), ("[::1]", "::1"),
                  ("192.0.2.10:8443", "192.0.2.10"),
                  ("", ""), ("a.de:abc", ""), ("[::1", ""), ("a.de/x", "")):
    check("%r -> %r" % (roh, soll), HP.host_normal(roh) == soll)

# ── [B] Namen und Modus ─────────────────────────────────────────────────────
print("[B] erlaubte Namen und Modus")
setze("ca_signiert.crt",
      cors_origins="https://extra.beispiel.de:8443, https://zweit.beispiel.de",
      addin_base_url="https://addin.beispiel.de/",
      oidc_redirect_uri="https://rueck.beispiel.de/api/login/oidc/callback",
      erlaubte_hostnamen="Alias.Beispiel.de, [2001:db8::5]")
m, namen = HP.stand()
check("auto + CA-signiert: erzwingen", m == "erzwingen")
for n in ("localhost", "127.0.0.1", "::1"):
    check("Loopback erlaubt: " + n, n in namen)
for n in ("vm01.firma.local", "jarvis.beispiel.de", "ki.beispiel.de", "192.0.2.10"):
    check("aus dem Zertifikat (CN/SAN): " + n, n in namen)
for n in ("extra.beispiel.de", "zweit.beispiel.de"):
    check("aus cors_origins: " + n, n in namen)
check("aus addin_base_url", "addin.beispiel.de" in namen)
check("aus oidc_redirect_uri", "rueck.beispiel.de" in namen)
check("aus erlaubte_hostnamen (normiert)", "alias.beispiel.de" in namen and "2001:db8::5" in namen)
check("erlaubte_hostnamen als JSON-Liste",
      (setze("ca_signiert.crt", erlaubte_hostnamen='["json.beispiel.de"]'),
       "json.beispiel.de" in HP.stand()[1])[1])
check("fremder Name nicht erlaubt", FREMD not in namen)
check("erlaubt() mit Port", HP.erlaubt("jarvis.beispiel.de:443"))
check("erlaubt() leer = nein", not HP.erlaubt(""))

setze("selbst.crt")
check("auto + selbst signiert: nur melden", HP.stand()[0] == "melden")
setze(None)
check("auto + Zertifikat unlesbar: nur melden", HP.stand()[0] == "melden")
setze("selbst.crt", host_pruefung="erzwingen")
check("erzwingen gilt auch bei selbst signiert", HP.stand()[0] == "erzwingen")
setze("ca_signiert.crt", host_pruefung="melden")
check("melden gilt auch bei CA-signiert", HP.stand()[0] == "melden")
setze("ca_signiert.crt", host_pruefung="AUS")
check("aus (Grossschreibung egal)", HP.stand()[0] == "aus")
setze("selbst.crt", host_pruefung="quatsch")
check("unbekannter Modus gilt als auto (nicht erzwingen)", HP.modus() == "auto"
      and HP.stand()[0] == "melden")

# Zwischenspeicher: vor Ablauf der Frist bleibt der Stand, danach wird neu gebaut
setze("ca_signiert.crt")
t0 = 1000.0
HP.stand(t0)
EINST["erlaubte_hostnamen"] = "neu.beispiel.de"
check("innerhalb TTL_S: Liste unveraendert", "neu.beispiel.de" not in HP.stand(t0 + HP.TTL_S - 1)[1])
check("nach TTL_S: Liste neu gebaut", "neu.beispiel.de" in HP.stand(t0 + HP.TTL_S + 1)[1])

# ── [C] Middleware ──────────────────────────────────────────────────────────
print("[C] Middleware")


async def _seite(request):
    return PlainTextResponse("inhalt")


async def _ws(websocket):
    await websocket.accept()
    await websocket.send_text("hallo")
    await websocket.close()


APP = Starlette(routes=[Route("/", _seite), WebSocketRoute("/ws", _ws)])
APP.add_middleware(HP.HostPruefung)
CLIENT = TestClient(APP)


def abruf(host: str):
    return CLIENT.get("/", headers={"host": host})


def ws_angenommen(host: str) -> bool:
    try:
        with CLIENT.websocket_connect("/ws", headers={"host": host}) as w:
            return w.receive_text() == "hallo"
    except WebSocketDisconnect:
        return False


# Positivkontrolle des Pruefstands (Modus aus = Durchreichen): App und Client
# laufen. Ob ein ERLAUBTER Name durchkommt, ist Produkt – das ist ein FAIL.
setze("ca_signiert.crt", host_pruefung="aus")
r = abruf("jarvis.beispiel.de")
if r.status_code != 200 or r.text != "inhalt" or not ws_angenommen("jarvis.beispiel.de"):
    abbruch("Positivkontrolle: Pruefstand liefert nicht aus (%s)" % r.status_code)
setze("ca_signiert.crt")
check("erlaubter Name (aus dem Zertifikat): 200", abruf("jarvis.beispiel.de").status_code == 200)
check("erlaubter Name mit Port: 200", abruf("jarvis.beispiel.de:443").status_code == 200)
check("Loopback: 200", abruf("127.0.0.1").status_code == 200)
r = abruf(FREMD)
check("fremder Name: 421", r.status_code == HP.STATUS == 421)
check("fremder Name: Inhalt der Seite nicht ausgeliefert", "inhalt" not in r.text)
check("WebSocket mit erlaubtem Namen angenommen", ws_angenommen("jarvis.beispiel.de"))
check("WebSocket mit fremdem Namen abgewiesen", not ws_angenommen(FREMD))


def roh_ohne_host() -> int:
    """ASGI-Aufruf ganz ohne Host-Kopf (TestClient setzt immer einen)."""
    gesendet = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(nachricht):
        gesendet.append(nachricht)

    scope = {"type": "http", "method": "GET", "path": "/", "raw_path": b"/",
             "query_string": b"", "headers": [], "scheme": "https",
             "client": ("192.0.2.99", 5000), "server": ("192.0.2.10", 443),
             "http_version": "1.1", "asgi": {"version": "3.0"}, "root_path": ""}
    asyncio.run(APP(scope, receive, send))
    starts = [n for n in gesendet if n.get("type") == "http.response.start"]
    return starts[0]["status"] if starts else -1


check("ohne Host-Kopf: 421", roh_ohne_host() == 421)

setze("ca_signiert.crt", host_pruefung="melden")
puffer = io.StringIO()
with contextlib.redirect_stdout(puffer):
    r1 = abruf(FREMD)
    r2 = abruf(FREMD)
    abruf("zweit.example")
check("melden: fremder Name kommt durch", r1.status_code == 200 and r2.status_code == 200)
zeilen = [z for z in puffer.getvalue().splitlines() if "[Host-Pruefung]" in z]
check("melden: Zeile im Journal mit dem Namen", any(repr(FREMD) in z for z in zeilen))
check("Meldung hoechstens einmal je Name (2 Abrufe -> 1 Zeile)",
      sum(repr(FREMD) in z for z in zeilen) == 1)
check("anderer Name wird eigens gemeldet", any("zweit.example" in z for z in zeilen))
check("melden: Zeile sagt 'nur gemeldet'", all("nur gemeldet" in z for z in zeilen))

setze("ca_signiert.crt", host_pruefung="aus")
puffer = io.StringIO()
with contextlib.redirect_stdout(puffer):
    r = abruf(FREMD)
check("aus: durch und ohne Meldung", r.status_code == 200 and "[Host-Pruefung]" not in puffer.getvalue())

setze("selbst.crt")
with contextlib.redirect_stdout(io.StringIO()):
    r = abruf(FREMD)
check("auto + selbst signiert: fremder Name kommt durch", r.status_code == 200)

# ── [D] Regel ueber main.py ─────────────────────────────────────────────────
print("[D] Einbindung in backend/main.py")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
reg = []          # (Zeile, Name) jeder Middleware-Registrierung auf Modulebene
quelle_ok = False
for knoten in baum.body:
    if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in knoten.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr == "middleware"):
                reg.append((knoten.lineno, knoten.name))
    if isinstance(knoten, ast.Expr) and isinstance(knoten.value, ast.Call):
        c = knoten.value
        if isinstance(c.func, ast.Attribute) and c.func.attr == "add_middleware" and c.args:
            reg.append((knoten.lineno, ast.unparse(c.args[0])))
        if (isinstance(c.func, ast.Attribute) and c.func.attr == "einstellungen_quelle"
                and ast.unparse(c.func.value) == "_host_pruefung"):
            quelle_ok = (len(c.args) == 2 and ast.unparse(c.args[0]) == "config.get_setting"
                         and ast.unparse(c.args[1]) == "_SERVER_ZERTIFIKAT")
if len(reg) < 5:
    abbruch("Messaufbau: nur %d Middleware-Registrierungen in main.py gefunden" % len(reg))
check("Host-Pruefung registriert", any(n == "_host_pruefung.HostPruefung" for _, n in reg))
check("Host-Pruefung ist die zuletzt registrierte (aeusserste) Middleware",
      reg[-1][1] == "_host_pruefung.HostPruefung")
check("Host-Pruefung genau einmal registriert",
      sum(n == "_host_pruefung.HostPruefung" for _, n in reg) == 1)
check("bekommt config.get_setting und das Server-Zertifikat", quelle_ok)

shutil.rmtree(TMP, ignore_errors=True)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
