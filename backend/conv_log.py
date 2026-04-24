"""Protokolliert LLM-Konversationen fuer den Verlauf-Tab.

Speichert die letzten 200 Konversationen in data/conv_log.json.
Pro Konversation: Aufgabe, Modell, Client-IP/-Typ, Steps, Dauer, Nachrichten.
"""

import json
import threading
import time
from pathlib import Path
from typing import Any

_LOG_FILE = Path(__file__).parent.parent / "data" / "conv_log.json"
_MAX_ENTRIES = 200
_PREVIEW_LEN = 300   # Zeichen pro Nachrichten-Preview

_lock = threading.Lock()


def _load() -> list:
    try:
        if _LOG_FILE.exists():
            return json.loads(_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save(entries: list):
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LOG_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=None),
                             encoding="utf-8")
    except Exception:
        pass


def log_conversation(
    task: str,
    model: str,
    client_ip: str,
    client_type: str,
    system_prompt: str,
    messages: list[dict],   # {"role": str, "content": str|None, "tool": str|None}
    steps: int,
    duration_ms: int,
    error: str | None = None,
    username: str = "",
):
    """Speichert eine abgeschlossene Konversation."""
    entry = {
        "id": f"{int(time.time()*1000)}",
        "ts": time.time(),
        "task": task[:200],
        "model": model,
        "username": username or "",
        "client_ip": client_ip or "unknown",
        "client_type": client_type or "browser",
        "steps": steps,
        "duration_ms": duration_ms,
        "error": error,
        "system_prompt_preview": (system_prompt or "")[:500],
        "messages": [_shrink(m) for m in (messages or [])],
    }
    with _lock:
        entries = _load()
        entries.append(entry)
        if len(entries) > _MAX_ENTRIES:
            entries = entries[-_MAX_ENTRIES:]
        _save(entries)


def _shrink(m: dict) -> dict:
    """Kuerzt eine Nachricht auf Preview-Laenge."""
    role = m.get("role", "?")
    content = m.get("content") or ""
    tool = m.get("tool")
    result = {"role": role}
    if tool:
        result["tool"] = tool
    if content:
        result["preview"] = content[:_PREVIEW_LEN] + ("…" if len(content) > _PREVIEW_LEN else "")
    return result


def get_conversations(limit: int = 50, ip_filter: str | None = None,
                      user_filter: str | None = None) -> list:
    with _lock:
        entries = _load()
    entries = list(reversed(entries))          # Neueste zuerst
    if ip_filter:
        entries = [e for e in entries if e.get("client_ip") == ip_filter]
    if user_filter:
        entries = [e for e in entries if e.get("username") == user_filter]
    return entries[:limit]


def get_known_ips() -> list[str]:
    with _lock:
        entries = _load()
    seen = []
    for e in reversed(entries):
        ip = e.get("client_ip", "unknown")
        if ip not in seen:
            seen.append(ip)
    return seen


def get_known_users() -> list[str]:
    with _lock:
        entries = _load()
    seen = []
    for e in reversed(entries):
        user = e.get("username", "")
        if user and user not in seen:
            seen.append(user)
    return seen


def clear():
    with _lock:
        _save([])
