#!/usr/bin/env python3
"""Waechter: /ws vor der Anmeldung – Grenze, Takt, Frist, Anzahl (ws_vorab).

Befund 2026-11-27 (Speicher-DoS ohne Anmeldung): ``/ws`` nahm Nachrichten bis
100 MB an, ohne Zeitlimit, und die websockets-Bibliothek las davon bis zu 32
im Hintergrund vor. ``backend/ws_vorab.py`` begrenzt das bis zur Anmeldung.

Teil A – Wirkung mit ECHTEM uvicorn + websockets (die installierten Fassungen,
also genau die Verkabelung ueber ``ws._receive.__self__``) an einer kleinen
Starlette-App, deren Schleife die von ``websocket_endpoint`` nachbildet:
  * Positivkontrolle: Schranken auf Protokollebene sind aktiv (vorbereiten → True)
  * vor der Anmeldung: Nachricht ueber VOR_ANMELDUNG_MAX → Verbindung zu (1009)
  * Anmeldung, DIREKT danach eine grosse Nachricht → kommt an (der Takt wirkt:
    die zweite Nachricht wird erst nach der Anmeldung gelesen)
  * ohne Anmeldung: nach der Frist zu (1008)
  * mehr als JE_QUELLE_MAX wartende Verbindungen derselben Quelle → abgewiesen
  * vor der Anmeldung liest die Bibliothek NICHT voraus (Warteschlange <= 1)
Teil B – Regel am Syntaxbaum von ``backend/main.py``:
  * websocket_endpoint: zulassen + vorbereiten VOR accept, Frist, verarbeitet im
    finally, entfernen im finally
  * freischalten steht direkt bei ``_ws_angemeldet.add`` in handle_ws_message

    python3 tests/test_ws_vorab.py      Exit 0 gruen, 1 rot, 2 konnte nicht laufen
"""
import ast
import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import uvicorn
    import websockets
    from starlette.applications import Starlette
    from starlette.routing import WebSocketRoute
    from starlette.websockets import WebSocketDisconnect
except ImportError as e:  # pragma: no cover
    print(f"ABBRUCH: Abhaengigkeit fehlt ({e})")
    sys.exit(2)

from backend import ws_vorab  # noqa: E402

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


# ── Teil A: echter Server ───────────────────────────────────────────────────
ws_vorab.ANMELDE_FRIST_S = 2.0
ws_vorab.JE_QUELLE_MAX = 3
VOLL = 20 * 1024 * 1024
ERGEBNIS = {"vorbereitet": [], "empfangen": [], "warteschlange_max": 0}


async def endpunkt(ws):
    if not ws_vorab.zulassen(ws):
        await ws.close(code=1013)
        return
    ERGEBNIS["vorbereitet"].append(ws_vorab.vorbereiten(ws))
    await ws.accept()
    beginn = time.monotonic()
    proto = getattr(ws._receive, "__self__", None)
    try:
        while True:
            rest = ws_vorab.frist(ws, beginn, time.monotonic())
            if rest is None:
                data = await ws.receive_text()
            else:
                try:
                    data = await asyncio.wait_for(ws.receive_text(), timeout=rest)
                except asyncio.TimeoutError:
                    await ws.close(code=1008)
                    break
            try:
                # Kurz warten: liest die Bibliothek waehrenddessen voraus?
                await asyncio.sleep(0.2)
                if proto is not None and not ws_vorab.ist_angemeldet(ws):
                    ERGEBNIS["warteschlange_max"] = max(
                        ERGEBNIS["warteschlange_max"], len(getattr(proto, "messages", [])))
                msg = json.loads(data)
                ERGEBNIS["empfangen"].append((msg.get("type"), len(data)))
                if msg.get("type") == "hello" and msg.get("token") == "gut":
                    ws_vorab.freischalten(ws)
                await ws.send_text(json.dumps({"ok": msg.get("type"), "n": len(data)}))
            finally:
                ws_vorab.verarbeitet(ws)
    except WebSocketDisconnect:
        pass
    finally:
        ws_vorab.entfernen(ws)


def _freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _freier_port()
app = Starlette(routes=[WebSocketRoute("/ws", endpunkt)])
cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, ws="websockets",
                     ws_max_size=VOLL, log_level="error", lifespan="off")
server = uvicorn.Server(cfg)
t = threading.Thread(target=server.run, daemon=True)
t.start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.05)
if not server.started:
    print("ABBRUCH: Testserver startet nicht")
    sys.exit(2)
URL = f"ws://127.0.0.1:{PORT}/ws"


async def _zu_code(verb, timeout=5):
    """Wartet, bis der Server schliesst; Rueckgabe Close-Code oder None."""
    try:
        await asyncio.wait_for(verb.recv(), timeout)
        await asyncio.wait_for(verb.recv(), timeout)
    except websockets.ConnectionClosed as e:
        return e.rcvd.code if e.rcvd else None
    except asyncio.TimeoutError:
        return None
    return None


async def teil_a():
    print("Teil A – Wirkung mit echtem uvicorn/websockets "
          f"(uvicorn {uvicorn.__version__}, websockets {websockets.__version__})")
    gross = "x" * (ws_vorab.VOR_ANMELDUNG_MAX + 10)

    # Positivkontrolle + kleine Nachricht ohne Anmeldung geht
    async with websockets.connect(URL, max_size=None) as v:
        await v.send(json.dumps({"type": "ping"}))
        a = json.loads(await asyncio.wait_for(v.recv(), 5))
    if ERGEBNIS["vorbereitet"] != [True]:
        print(f"ABBRUCH: Positivkontrolle – Protokollebene nicht erreichbar ({ERGEBNIS['vorbereitet']})")
        sys.exit(2)
    check(True, "Positivkontrolle: Schranken auf Protokollebene aktiv")
    check(a.get("ok") == "ping", "kleine Nachricht vor der Anmeldung kommt an")

    # Grosse Nachricht vor der Anmeldung → 1009, App sieht sie nie
    vorher = len(ERGEBNIS["empfangen"])
    async with websockets.connect(URL, max_size=None) as v:
        await v.send(json.dumps({"type": "task", "text": gross}))
        code = await _zu_code(v)
    check(code == 1009, f"grosse Nachricht vor der Anmeldung → 1009 (ist {code})")
    check(len(ERGEBNIS["empfangen"]) == vorher, "die App hat sie nicht bekommen")

    # Anmeldung und SOFORT danach eine grosse Nachricht
    a1, a2 = {}, {}
    try:
        async with websockets.connect(URL, max_size=None) as v:
            await v.send(json.dumps({"type": "hello", "token": "gut"}))
            await v.send(json.dumps({"type": "task", "text": "y" * (3 * 1024 * 1024)}))
            a1 = json.loads(await asyncio.wait_for(v.recv(), 5))
            a2 = json.loads(await asyncio.wait_for(v.recv(), 10))
    except (websockets.ConnectionClosed, asyncio.TimeoutError) as e:
        a2 = {"fehler": f"{type(e).__name__}: {e}"}
    check(a1.get("ok") == "hello" and a2.get("ok") == "task" and a2.get("n", 0) > 3_000_000,
          f"nach Anmeldung kommt eine 3-MB-Nachricht an, auch direkt hinterher ({a1}, {a2.get('ok') or a2})")

    # Zwei grosse Nachrichten nach Anmeldung: weiterhin volle Grenze
    a = {}
    try:
        async with websockets.connect(URL, max_size=None) as v:
            await v.send(json.dumps({"type": "hello", "token": "gut"}))
            await asyncio.wait_for(v.recv(), 5)
            await v.send(json.dumps({"type": "task", "text": "z" * (2 * 1024 * 1024)}))
            a = json.loads(await asyncio.wait_for(v.recv(), 10))
    except (websockets.ConnectionClosed, asyncio.TimeoutError):
        pass
    check(a.get("ok") == "task", "angemeldet: grosse Nachricht spaeter ebenfalls")

    # Falsche Anmeldung, dann gross → 1009
    async with websockets.connect(URL, max_size=None) as v:
        await v.send(json.dumps({"type": "hello", "token": "falsch"}))
        await asyncio.wait_for(v.recv(), 5)
        await v.send(json.dumps({"type": "task", "text": gross}))
        code = await _zu_code(v)
    check(code == 1009, f"gescheiterte Anmeldung hebt die Grenze nicht (ist {code})")

    # Vorauslesen: fuenf kleine Nachrichten auf einmal, keine Anmeldung
    ERGEBNIS["warteschlange_max"] = 0
    async with websockets.connect(URL, max_size=None) as v:
        for _ in range(5):
            await v.send(json.dumps({"type": "ping", "p": "q" * 1000}))
        for _ in range(5):
            await asyncio.wait_for(v.recv(), 5)
    check(ERGEBNIS["warteschlange_max"] == 0,
          f"vor der Anmeldung keine Vorauslese (Warteschlange max {ERGEBNIS['warteschlange_max']})")

    # Frist
    t0 = time.monotonic()
    async with websockets.connect(URL, max_size=None) as v:
        code = await _zu_code(v, timeout=ws_vorab.ANMELDE_FRIST_S + 5)
    dauer = time.monotonic() - t0
    check(code == 1008 and dauer < ws_vorab.ANMELDE_FRIST_S + 3,
          f"ohne Anmeldung nach der Frist zu (Code {code}, {dauer:.1f} s)")

    # Anzahl je Quelle
    offen = [await websockets.connect(URL, max_size=None) for _ in range(ws_vorab.JE_QUELLE_MAX)]
    await asyncio.sleep(0.3)
    abgewiesen = False
    extra = None
    try:
        extra = await websockets.connect(URL, max_size=None)
        # Angenommen? Dann muss der Server SOFORT schliessen – die Frist (2 s)
        # darf nicht als Abweisung durchgehen, also kuerzer warten.
        code = await _zu_code(extra, timeout=ws_vorab.ANMELDE_FRIST_S / 2)
        abgewiesen = code is not None
    except (websockets.InvalidStatus, websockets.InvalidHandshake, OSError):
        abgewiesen = True
    finally:
        if extra is not None:
            await extra.close()
    check(abgewiesen, f"Verbindung Nr. {ws_vorab.JE_QUELLE_MAX + 1} derselben Quelle wird abgewiesen")
    # Nach Anmeldung einer davon ist wieder Platz
    await offen[0].send(json.dumps({"type": "hello", "token": "gut"}))
    await asyncio.wait_for(offen[0].recv(), 5)
    neu = await websockets.connect(URL, max_size=None)
    await neu.send(json.dumps({"type": "ping"}))
    a = json.loads(await asyncio.wait_for(neu.recv(), 5))
    check(a.get("ok") == "ping", "angemeldete Verbindungen zaehlen nicht gegen die Grenze")
    for v in offen + [neu]:
        await v.close()


try:
    asyncio.run(teil_a())
finally:
    server.should_exit = True
    t.join(5)


# ── Teil B: Regel am Syntaxbaum von main.py ─────────────────────────────────
print("Teil B – Verkabelung in main.py")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(MAIN)
fn = {n.name: n for n in baum.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}
if "websocket_endpoint" not in fn or "handle_ws_message" not in fn:
    print("ABBRUCH: websocket_endpoint/handle_ws_message nicht gefunden")
    sys.exit(2)
ep = fn["websocket_endpoint"]


def _aufrufe(knoten, name):
    """Zeilen aller Aufrufe _ws_vorab.<name>(...) bzw. ws.<name>() unter knoten."""
    return sorted(k.lineno for k in ast.walk(knoten)
                  if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
                  and k.func.attr == name)


accept = _aufrufe(ep, "accept")
check(len(accept) == 1, f"genau ein accept() ({accept})")
acc = accept[0] if accept else 0
for name in ("zulassen", "vorbereiten"):
    z = _aufrufe(ep, name)
    check(bool(z) and max(z) < acc, f"{name}() steht vor accept()")
check(bool(_aufrufe(ep, "frist")), "Frist wird in der Schleife abgefragt")
check(bool(_aufrufe(ep, "wait_for")), "Empfang vor der Anmeldung mit Zeitdeckel (wait_for)")

im_finally = {"verarbeitet": False, "entfernen": False}
for k in ast.walk(ep):
    if isinstance(k, ast.Try):
        for f in k.finalbody:
            for name in im_finally:
                if _aufrufe(f, name):
                    im_finally[name] = True
for name, ja in im_finally.items():
    check(ja, f"{name}() steht in einem finally")

hw = fn["handle_ws_message"]
add_zeilen = [k.lineno for k in ast.walk(hw)
              if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute) and k.func.attr == "add"
              and isinstance(k.func.value, ast.Name) and k.func.value.id == "_ws_angemeldet"]
frei = _aufrufe(hw, "freischalten")
check(len(add_zeilen) == 1 and len(frei) == 1 and 0 < frei[0] - add_zeilen[0] <= 3,
      f"freischalten() direkt nach _ws_angemeldet.add ({add_zeilen}, {frei})")

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
