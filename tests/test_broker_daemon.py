#!/usr/bin/env python3
"""Waechter: der Broker bleibt unter Last bedienbar (Code-Review 2026-10-18).

Gemessen am ECHTEN ``daemon._handle`` hinter einem echten Unix-Socket in einem
Wegwerf-Verzeichnis (Policy/Audit dorthin umgebogen, ``ops.dispatch`` als
Attrappe in echter Signatur):
  [1] Anfrage ueber 64 KiB (alter Standardpuffer) wird verarbeitet, ueber
      MAX_REQUEST_BYTES verstaendlich abgewiesen; ``timeout`` als Text wirft nicht.
  [2] Pool-Trennung: sind ALLE Plaetze fuer lange Ops belegt, antwortet ein
      Meta-Aufruf trotzdem sofort, und eine weitere lange Op wird abgewiesen
      statt endlos eingereiht.
  [3] ``ops.timeout_arg`` klemmt.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import asyncio
import getpass
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


SK = Path(tempfile.mkdtemp(prefix="broker_daemon_"))
os.environ["JARVIS_BROKER_POLICY"] = str(SK / "policy.json")
os.environ["JARVIS_BROKER_AUDIT"] = str(SK / "audit.jsonl")
os.environ["JARVIS_BROKER_FREIGABE_KEY"] = str(SK / "freigabe.key")
os.environ["JARVIS_BROKER_FREIGABE_STATE"] = str(SK / "freigabe.state")
os.environ["JARVIS_PROJECT_ROOT"] = str(SK)
os.environ["JARVIS_BROKER_LANG_MAX"] = "3"
try:
    from backend.broker import daemon as D, ops as O
except Exception as e:  # noqa: BLE001
    abbruch("Broker nicht importierbar: %s" % e)

D.SERVICE_USER = getpass.getuser()
SOCK = str(SK / "b.sock")
gesehen = []
freigabe = threading.Event()


def _dispatch(op, args, user="", stream=None, peer=""):   # echte Signatur
    gesehen.append((op, threading.current_thread().name))
    if op == "sandbox_lauf":
        freigabe.wait(20)
    return {"ok": True, "decision": "allowed", "op": op}


O.dispatch = _dispatch
_meta_echt = D.meta.behandeln
D.meta.behandeln = lambda op, args, peer="": ({"ok": True, "pong": True} if op == "broker.ping" else None)


async def anfrage(obj_oder_bytes, frist=10):
    r, w = await asyncio.open_unix_connection(SOCK, limit=2 ** 22)
    roh = obj_oder_bytes if isinstance(obj_oder_bytes, bytes) else json.dumps(obj_oder_bytes).encode()
    w.write(roh + b"\n")
    await w.drain()
    erg = None
    t0 = time.monotonic()
    while True:
        zeile = await asyncio.wait_for(r.readline(), frist)
        if not zeile:
            break
        d = json.loads(zeile)
        if d.get("type") == "result":
            erg = d
            break
    w.close()
    return erg, time.monotonic() - t0


async def haupt():
    server = await asyncio.start_unix_server(D._handle, path=SOCK, limit=D.MAX_REQUEST_BYTES + 1)
    try:
        print("\n[1] Anfragegroesse und Timeout-Feld")
        erg, _ = await anfrage({"op": "systemctl", "args": {}, "timeout": 5})
        check("(Positivkontrolle) einfache Anfrage erreicht dispatch", erg and erg.get("op") == "systemctl", str(erg))
        if not erg:
            return
        erg, _ = await anfrage({"op": "systemctl", "args": {"pad": "A" * 100_000}})
        check("100 KB-Anfrage (ueber dem alten 64-KiB-Puffer) wird verarbeitet",
              erg and erg.get("op") == "systemctl", str(erg)[:200])
        erg, _ = await anfrage({"op": "systemctl", "args": {"pad": "A" * (D.MAX_REQUEST_BYTES + 10)}})
        check("ueber MAX_REQUEST_BYTES: verstaendlich abgewiesen",
              erg and erg.get("ok") is False and "zu gross" in (erg.get("error") or ""), str(erg)[:200])
        erg, _ = await anfrage({"op": "systemctl", "args": {}, "timeout": "abc"})
        check("timeout als Text: kein Absturz", erg and erg.get("op") == "systemctl", str(erg))
        erg, _ = await anfrage({"op": "systemctl", "args": ["x"]})
        check("args als Liste: abgewiesen", erg and erg.get("ok") is False, str(erg))

        print("\n[2] Pool-Trennung")
        lang = [asyncio.create_task(anfrage({"op": "sandbox_lauf", "args": {}, "timeout": 30}, frist=30))
                for _ in range(D.LANG_MAX)]
        for _ in range(50):
            if sum(1 for o, _t in gesehen if o == "sandbox_lauf") >= D.LANG_MAX:
                break
            await asyncio.sleep(0.1)
        belegt = sum(1 for o, _t in gesehen if o == "sandbox_lauf")
        check("(Positivkontrolle) alle %d Plaetze fuer lange Ops belegt" % D.LANG_MAX, belegt == D.LANG_MAX, str(belegt))
        erg, dauer = await anfrage({"op": "broker.ping", "args": {}}, frist=5)
        check("Meta-Aufruf antwortet trotzdem sofort (%.2f s)" % dauer, erg and erg.get("pong") and dauer < 2, str(erg))
        erg, dauer = await anfrage({"op": "systemctl", "args": {}}, frist=5)
        check("kurze Op laeuft trotzdem (%.2f s)" % dauer, erg and erg.get("op") == "systemctl" and dauer < 2)
        erg, dauer = await anfrage({"op": "sandbox_lauf", "args": {}}, frist=5)
        check("weitere lange Op: sofort 'ausgelastet' statt Warteschlange",
              erg and erg.get("ok") is False and "ausgelastet" in (erg.get("error") or ""), str(erg))
        namen = {t for o, t in gesehen if o == "sandbox_lauf"}
        check("lange Ops laufen im eigenen Pool", namen and all(n.startswith("broker-lang") for n in namen), str(namen))
        freigabe.set()
        await asyncio.gather(*lang)
        check("nach dem Ende ist der Zaehler wieder 0", D._lang_aktiv == 0, str(D._lang_aktiv))
    finally:
        freigabe.set()
        server.close()


import ast as _ast  # noqa: E402
_dq = (ROOT / "backend" / "broker" / "daemon.py").read_text(encoding="utf-8")
_main = next((n for n in _ast.parse(_dq).body if isinstance(n, _ast.AsyncFunctionDef) and n.name == "main"), None)
_srv = [c for c in _ast.walk(_main) if isinstance(c, _ast.Call)
        and getattr(c.func, "attr", "") == "start_unix_server"] if _main else []
check("daemon.main() startet den Server MIT limit (sonst 64-KiB-Standard)",
      len(_srv) == 1 and any(k.arg == "limit" for k in _srv[0].keywords))

try:
    asyncio.run(haupt())
    print("\n[3] timeout_arg")
    check("Text -> Vorgabe", O.timeout_arg({"timeout": "x"}) == 120)
    check("negativ -> 1", O.timeout_arg({"timeout": -5}) == 1)
    check("riesig -> OP_TIMEOUT_MAX", O.timeout_arg({"timeout": 10 ** 9}) == O.OP_TIMEOUT_MAX)
    check("normal bleibt", O.timeout_arg({"timeout": 300}) == 300)
finally:
    D.meta.behandeln = _meta_echt
    shutil.rmtree(SK, ignore_errors=True)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
