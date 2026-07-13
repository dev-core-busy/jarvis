"""Root-Broker-Daemon: Unix-Socket-Server fuer privilegierte Operationen.

Laeuft als root (jarvis-broker.service). Das unprivilegierte Backend verbindet
sich ueber /run/jarvis-broker.sock (root:<gruppe> 0660) und sendet EINE
JSON-Zeile pro Verbindung:

    {"op": "...", "args": {...}, "user": "...", "timeout": 120}

Antwort als NDJSON: beliebig viele {"type":"stream","line": "..."}-Zeilen
(Live-Ausgabe fuer shell-artige Ops), abgeschlossen mit
{"type":"result", "ok": ..., "decision": ..., ...}.

Meta-Operationen (nicht policy-gesteuert, fuer die Admin-UI):
- broker.ping           – Erreichbarkeits-/Versionscheck
- broker.policy_list    – alle Policy-Eintraege
- broker.policy_decide  – {key, decision, by} setzen
- broker.policy_remove  – {key} loeschen
- broker.audit_tail     – {n} letzte Audit-Eintraege

Start: /opt/jarvis/venv/bin/python -m backend.broker.daemon
"""

import asyncio
import grp
import json
import os
import signal
import sys

# Projekt-Root in sys.path (Start via `python -m backend.broker.daemon` aus
# dem Projektverzeichnis funktioniert auch ohne diesen Eintrag; absolute
# Aufrufe aus systemd nicht unbedingt).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.broker import SOCKET_PATH, ops, policy  # noqa: E402

SOCKET_GROUP = os.environ.get("JARVIS_BROKER_GROUP", "jarvis")
MAX_REQUEST_BYTES = 512 * 1024
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 900


def _meta(op: str, args: dict) -> dict | None:
    """Meta-Operationen (Policy-Verwaltung/Audit) – immer erlaubt, kein Root-Effekt."""
    if op == "broker.ping":
        return {"ok": True, "pid": os.getpid(), "euid": os.geteuid()}
    if op == "broker.policy_list":
        return {"ok": True, "ops": policy.list_ops()}
    if op == "broker.policy_decide":
        entry = policy.decide(str(args.get("key", "")), str(args.get("decision", "")),
                              str(args.get("by", "")))
        if entry is None:
            return {"ok": False, "error": "Unbekannter Key oder ungueltige Entscheidung"}
        policy.audit(str(args.get("by", "")), "broker.policy_decide",
                     str(args.get("key", "")), str(args.get("decision", "")))
        return {"ok": True, "entry": entry}
    if op == "broker.policy_remove":
        ok = policy.remove(str(args.get("key", "")))
        if ok:
            policy.audit(str(args.get("by", "")), "broker.policy_remove",
                         str(args.get("key", "")), "removed")
        return {"ok": ok}
    if op == "broker.audit_tail":
        return {"ok": True, "entries": policy.audit_tail(int(args.get("n") or 100))}
    return None


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    loop = asyncio.get_running_loop()

    async def send(obj: dict):
        writer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
        await writer.drain()

    try:
        raw = await asyncio.wait_for(reader.readline(), timeout=30)
        if not raw or len(raw) > MAX_REQUEST_BYTES:
            await send({"type": "result", "ok": False, "error": "Leere/zu grosse Anfrage"})
            return
        try:
            req = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            await send({"type": "result", "ok": False, "error": "Ungueltiges JSON"})
            return

        op = str(req.get("op", ""))
        args = req.get("args") or {}
        user = str(req.get("user", ""))
        timeout = min(int(req.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT)

        # Meta-Operationen direkt beantworten
        meta = _meta(op, args)
        if meta is not None:
            await send({"type": "result", **meta})
            return

        # Streaming-Callback: aus dem Worker-Thread thread-sicher in den Loop
        def stream_cb(line: str):
            asyncio.run_coroutine_threadsafe(
                send({"type": "stream", "line": str(line)[:4000]}), loop)

        print(f"[Broker] op={op} user={user} args={ops.redact_args(op, args)}", flush=True)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(ops.dispatch, op, args, user, stream_cb),
                timeout=timeout + 30,   # Puffer: Op-interne Timeouts greifen zuerst
            )
        except asyncio.TimeoutError:
            result = {"ok": False, "error": f"Broker-Timeout nach {timeout}s"}
        await send({"type": "result", **result})

    except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await send({"type": "result", "ok": False, "error": f"Broker-Fehler: {e}"})
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


async def main():
    if os.geteuid() != 0:
        print("[Broker] WARNUNG: laeuft nicht als root – Root-Ops werden scheitern.", flush=True)

    # Alten Socket entfernen (Neustart)
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    server = await asyncio.start_unix_server(_handle, path=SOCKET_PATH)

    # Socket: root:<gruppe> 0660 – nur der Dienst-Benutzer darf verbinden
    try:
        gid = grp.getgrnam(SOCKET_GROUP).gr_gid
        os.chown(SOCKET_PATH, 0, gid)
    except KeyError:
        print(f"[Broker] WARNUNG: Gruppe '{SOCKET_GROUP}' fehlt – Socket bleibt root-only.", flush=True)
    os.chmod(SOCKET_PATH, 0o660)

    print(f"[Broker] Bereit auf {SOCKET_PATH} (Gruppe: {SOCKET_GROUP})", flush=True)

    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    async with server:
        await stop.wait()
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass
    print("[Broker] Beendet.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
