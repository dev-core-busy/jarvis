"""Jarvis Audit-Log – strukturiertes JSONL-Logging aller Tasks und Tool-Ausführungen."""

import json
import threading
import time
from pathlib import Path

AUDIT_FILE = Path("data/logs/audit.jsonl")
_lock = threading.Lock()
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB Rotation


def _ensure_dir():
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)


def log_task(user: str, task: str, client_type: str = "", client_ip: str = ""):
    """Loggt den Start einer Benutzer-Anfrage (auch ohne Tool-Aufruf)."""
    entry = {
        "ts": int(time.time()),
        "user": user or "unknown",
        "tool": "[task]",
        "args": {
            "task": task[:200] + ("…" if len(task) > 200 else ""),
            **({"client_type": client_type} if client_type else {}),
            **({"client_ip": client_ip} if client_ip else {}),
        },
        "result_len": None,
        "duration_ms": None,
    }
    _write(entry)


def log_tool(user: str, tool: str, args: dict, result_len: int, duration_ms: int):
    """Loggt einen Tool-Aufruf als JSONL-Zeile."""
    entry = {
        "ts": int(time.time()),
        "user": user or "unknown",
        "tool": tool,
        "args": {k: v for k, v in args.items() if not k.startswith("_")},  # interne Args ausblenden
        "result_len": result_len,
        "duration_ms": duration_ms,
    }
    _write(entry)


def _write(entry: dict):
    """Schreibt einen Eintrag atomar in die Log-Datei."""
    line = json.dumps(entry, ensure_ascii=False)
    with _lock:
        _ensure_dir()
        # Rotation wenn Datei zu gross
        if AUDIT_FILE.exists() and AUDIT_FILE.stat().st_size > _MAX_BYTES:
            bak = AUDIT_FILE.with_suffix(".jsonl.bak")
            AUDIT_FILE.rename(bak)
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_log(limit: int = 500, user_filter: str = "", tool_filter: str = "") -> list[dict]:
    """Liest die letzten N Audit-Log-Einträge (neueste zuerst)."""
    _ensure_dir()
    if not AUDIT_FILE.exists():
        return []
    with _lock:
        lines = AUDIT_FILE.read_text(encoding="utf-8").splitlines()

    entries = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if user_filter and user_filter.lower() not in (entry.get("user") or "").lower():
                continue
            if tool_filter and tool_filter.lower() not in (entry.get("tool") or "").lower():
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break
        except Exception:
            pass
    return entries
