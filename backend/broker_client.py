"""Client fuer den Root-Broker (backend/broker/daemon.py).

Nutzung im Backend:
    from backend import broker_client
    res = await broker_client.call("systemctl", {"action": "restart", "unit": "jarvis.service"}, user=...)
    res = broker_client.call_sync(...)   # aus Threads / Sync-Kontexten

Rueckgabe-Dict: {ok, decision(allowed|pending|denied|...), key, rc, stdout, stderr, error, result}

Fallback-Modi (fuer nicht migrierte Alt-Installationen, Backend laeuft als root):
- Socket vorhanden  -> Broker (normaler, getrennter Betrieb)
- Socket fehlt, euid==0 -> lokale Ausfuehrung ueber dieselbe ops-Registry
  (inkl. Policy + Audit – Verhalten identisch, nur ohne Prozess-Trennung)
- Socket fehlt, unprivilegiert -> Fehler "Broker nicht erreichbar"
"""

import asyncio
import json
import os
import socket

from backend.broker import SOCKET_PATH

DEFAULT_TIMEOUT = 120


def mode() -> str:
    """'broker' | 'local-root' | 'none' – fuer Status-Anzeigen."""
    if os.path.exists(SOCKET_PATH):
        return "broker"
    if os.geteuid() == 0:
        return "local-root"
    return "none"


def _local_dispatch(op: str, args: dict, user: str, stream_cb) -> dict:
    """Fallback: direkte Ausfuehrung im eigenen (root-)Prozess."""
    from backend.broker import ops, policy

    # Meta-Ops auch lokal bedienen (Admin-UI auf Alt-Installationen)
    if op == "broker.ping":
        return {"ok": True, "pid": os.getpid(), "euid": os.geteuid(), "local": True}
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
        return {"ok": policy.remove(str(args.get("key", "")))}
    if op == "broker.audit_tail":
        return {"ok": True, "entries": policy.audit_tail(int(args.get("n") or 100))}
    return ops.dispatch(op, args or {}, user, stream_cb)


def call_sync(op: str, args: dict | None = None, *, user: str = "",
              timeout: int = DEFAULT_TIMEOUT, stream_cb=None) -> dict:
    """Synchroner Broker-Aufruf (fuer Threads/Sync-Code). stream_cb(line) wird
    fuer Live-Ausgabezeilen aufgerufen (sofern die Op streamt)."""
    if not os.path.exists(SOCKET_PATH):
        if os.geteuid() == 0:
            return _local_dispatch(op, args or {}, user, stream_cb)
        return {"ok": False, "decision": "unreachable",
                "error": "Root-Broker nicht erreichbar (jarvis-broker.service laeuft nicht?)"}

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout + 60)   # Netz-Timeout > Op-Timeout (Broker meldet selbst)
        s.connect(SOCKET_PATH)
        req = json.dumps({"op": op, "args": args or {}, "user": user,
                          "timeout": timeout}, ensure_ascii=False) + "\n"
        s.sendall(req.encode())

        buf = b""
        f = s.makefile("rb")
        for raw in f:
            try:
                msg = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                continue
            if msg.get("type") == "stream":
                if stream_cb:
                    try:
                        stream_cb(msg.get("line", ""))
                    except Exception:  # noqa: BLE001
                        pass
                continue
            if msg.get("type") == "result":
                msg.pop("type", None)
                return msg
        return {"ok": False, "decision": "error",
                "error": "Broker-Verbindung ohne Ergebnis beendet"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "decision": "error", "error": f"Broker-Fehler: {e}"}
    finally:
        try:
            s.close()
        except Exception:  # noqa: BLE001
            pass


async def call(op: str, args: dict | None = None, *, user: str = "",
               timeout: int = DEFAULT_TIMEOUT, stream_cb=None) -> dict:
    """Asynchroner Broker-Aufruf. stream_cb darf eine Coroutine-Funktion sein –
    Zeilen werden dann in den Event-Loop uebergeben (Live-Streaming ins WS)."""
    loop = asyncio.get_running_loop()

    if stream_cb is not None and asyncio.iscoroutinefunction(stream_cb):
        _async_cb = stream_cb

        def _cb(line):
            asyncio.run_coroutine_threadsafe(_async_cb(line), loop)
    else:
        _cb = stream_cb

    return await asyncio.to_thread(call_sync, op, args, user=user,
                                   timeout=timeout, stream_cb=_cb)


async def systemctl(action: str, unit: str, *, user: str = "") -> dict:
    """Komfort-Wrapper fuer die haeufigste Operation."""
    return await call("systemctl", {"action": action, "unit": unit}, user=user, timeout=90)


def systemctl_sync(action: str, unit: str, *, user: str = "") -> dict:
    return call_sync("systemctl", {"action": action, "unit": unit}, user=user, timeout=90)
