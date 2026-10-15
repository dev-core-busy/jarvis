"""Geteilte Anzeige-History der Agent-Chats (Hauptfenster + jarvis/chat).

Pro Benutzer wird der angezeigte Chatverlauf serverseitig gespeichert, damit
beide Fenster (und andere Geraete) denselben Inhalt sehen. Dies ist die
ANZEIGE-History (Bubbles); der KI-Kontext liegt separat in agent._user_histories.
"""

import json
import threading
from pathlib import Path

from backend.benutzer import pfad_teil

_DIR = Path(__file__).parent.parent / "data" / "chat_history"
_LOCK = threading.Lock()
_MAX = 400  # max. Nachrichten pro Benutzer


def _safe_user(user: str) -> str:
    """Dateiname-sicherer Benutzername (verhindert Pfad-Traversal).

    ⚠ Seit 2026-09-07 ueber ``benutzer.pfad_teil`` – vorher wurde nur
    kleingeschrieben und entschaerft, der Domaenenanteil blieb stehen:
    ``firma\\m.mustermann`` schrieb nach ``firmam.mustermann.json``,
    waehrend derselbe Mensch als ``m.mustermann`` eine zweite Datei bekam.
    """
    return pfad_teil(user, "anonymous")


def _path(user: str) -> Path:
    return _DIR / f"{_safe_user(user)}.json"


def load(user: str) -> list:
    """Gibt die gespeicherte Anzeige-History eines Benutzers zurueck."""
    p = _path(user)
    with _LOCK:
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []


def replace(user: str, messages: list) -> list:
    """Ersetzt die komplette History (fuer Migration/Edit/Loeschen/Leeren)."""
    if not isinstance(messages, list):
        messages = []
    messages = messages[-_MAX:]
    with _LOCK:
        _DIR.mkdir(mode=0o750, parents=True, exist_ok=True)  # Chats: sandbox.PRIVATE_DIRS
        _path(user).write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    return messages


def append(user: str, message: dict) -> list:
    """Haengt eine Nachricht an (additiv, vermeidet Ueberschreiben zwischen Fenstern)."""
    if not isinstance(message, dict):
        return load(user)
    p = _path(user)
    with _LOCK:
        _DIR.mkdir(mode=0o750, parents=True, exist_ok=True)  # Chats: sandbox.PRIVATE_DIRS
        try:
            cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
            if not isinstance(cur, list):
                cur = []
        except Exception:
            cur = []
        cur.append(message)
        cur = cur[-_MAX:]
        p.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    return cur


def clear(user: str) -> None:
    with _LOCK:
        p = _path(user)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
