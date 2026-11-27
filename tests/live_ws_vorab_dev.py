#!/usr/bin/env python3
"""Live auf DEV: Rumpf- und WebSocket-Grenzen vor der Anmeldung (Befund 2026-11-27).

Misst am LAUFENDEN Dienst (echter Middleware-Stapel, Server-Fassungen von
Starlette/uvicorn/websockets) – ``test_ws_vorab.py`` misst nur eine kleine
Nachbau-App, und ob ``ws._receive.__self__`` hinter allen Schichten noch das
Protokollobjekt ist, sieht nur der echte Dienst.

  1. /ws ohne Anmeldung: kleine Nachricht → Antwort (Positivkontrolle)
  2. /ws ohne Anmeldung: 2 MB → Verbindung zu mit 1009
  3. /ws mit Anmeldung (hello + Token), DIREKT danach 3 MB → Antwort (pong)
  4. /ws ohne Anmeldung: nach der Frist zu mit 1008
  5. /api/login mit 200 KB → 413; mit kleinem Rumpf → KEIN 413
  6. Journal seit Probenbeginn: keine Zeile "[ws_vorab] Protokollobjekt nicht erreichbar"

Laeuft im Dienstkontext (Hauptschluessel, BSI M5 – das Token muss im Dienst gelten):
    bash /opt/jarvis/deploy/als_dienst.sh env PYTHONDONTWRITEBYTECODE=1 \\
        venv/bin/python tests/live_ws_vorab_dev.py
"""
import asyncio
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")

try:
    import websockets  # noqa: E402
except ImportError:
    print("ABBRUCH: websockets fehlt")
    sys.exit(2)

from backend import main as M  # noqa: E402
from backend import ws_vorab  # noqa: E402

URL = "wss://127.0.0.1/ws"
HTTP = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
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


async def _antwort(v, typ, frist=10):
    """Naechste Nachricht vom Typ typ (cpu-Rundsendungen ueberspringen)."""
    ende = time.monotonic() + frist
    while time.monotonic() < ende:
        m = json.loads(await asyncio.wait_for(v.recv(), ende - time.monotonic()))
        if m.get("type") == typ:
            return m
    return None


async def _zu_code(v, frist):
    try:
        ende = time.monotonic() + frist
        while time.monotonic() < ende:
            await asyncio.wait_for(v.recv(), ende - time.monotonic())
    except websockets.ConnectionClosed as e:
        return e.rcvd.code if e.rcvd else None
    except asyncio.TimeoutError:
        return None
    return None


async def ws_proben(token):
    async with websockets.connect(URL, ssl=_KTX, max_size=None) as v:
        await v.send(json.dumps({"type": "ping"}))
        a = await _antwort(v, "pong", 10)
    if not a:
        print("ABBRUCH: Positivkontrolle – /ws antwortet nicht auf ping")
        sys.exit(2)
    check(True, "Positivkontrolle: /ws antwortet ohne Anmeldung auf ping")

    async with websockets.connect(URL, ssl=_KTX, max_size=None) as v:
        await v.send(json.dumps({"type": "ping", "pad": "x" * (2 * 1024 * 1024)}))
        code = await _zu_code(v, 10)
    check(code == 1009, f"ohne Anmeldung: 2 MB → 1009 (ist {code})")

    try:
        async with websockets.connect(URL, ssl=_KTX, max_size=None) as v:
            await v.send(json.dumps({"type": "hello", "token": token}))
            await v.send(json.dumps({"type": "ping", "token": token,
                                     "pad": "y" * (3 * 1024 * 1024)}))
            a = await _antwort(v, "pong", 20)
    except websockets.ConnectionClosed as e:
        a = None
        print(f"       (Verbindung zu: {e})")
    check(bool(a), "mit Anmeldung: 3 MB direkt nach hello → pong")

    t0 = time.monotonic()
    async with websockets.connect(URL, ssl=_KTX, max_size=None) as v:
        code = await _zu_code(v, ws_vorab.ANMELDE_FRIST_S + 15)
    d = time.monotonic() - t0
    check(code == 1008 and d < ws_vorab.ANMELDE_FRIST_S + 10,
          f"ohne Anmeldung nach der Frist zu (Code {code}, {d:.0f} s)")


def http_post(pfad, rumpf):
    req = urllib.request.Request(HTTP + pfad, data=rumpf, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_KTX, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, ConnectionError) as e:
        return f"{type(e).__name__}"


def main():
    seit = time.strftime("%Y-%m-%d %H:%M:%S")
    token = M.generate_token("jarvis")
    print("WebSocket /ws")
    asyncio.run(ws_proben(token))

    print("HTTP-Rumpf")
    st = http_post("/api/login", b'{"username":"' + b"a" * 200_000 + b'"}')
    check(st == 413, f"/api/login mit 200 KB → 413 (ist {st})")
    st = http_post("/api/login", b'{"username":"","password":""}')
    check(st != 413 and isinstance(st, int), f"/api/login klein → kein 413 (ist {st})")
    st = http_post("/api/addin/diag", b"x" * 100_000)
    check(st == 413, f"/api/addin/diag mit 100 KB → 413 (ist {st})")

    j = subprocess.run(["journalctl", "-u", "jarvis.service", "--since", seit, "--no-pager"],
                       capture_output=True, text=True).stdout
    check("Protokollobjekt nicht erreichbar" not in j,
          "Journal: Grenze auf Protokollebene war in jedem Fall aktiv")

    print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
    sys.exit(1 if _fail else 0)


if __name__ == "__main__":
    main()
