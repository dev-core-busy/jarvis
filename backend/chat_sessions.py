"""Benutzereigene Chat-Sitzungen fuer /chat.

Jeder Benutzer hat einen Hauptordner; jede Chat-Sitzung liegt in einem eigenen
Unterordner darin:

    data/chats/<benutzer>/<sitzungs-id>/
        meta.json        – {id, title, created, updated}
        transcript.json  – sichtbarer Chatverlauf (Bubbles, Anzeige)
        context.json      – LLM-Kontextspeicher dieser Sitzung (serialisierte
                            google-genai types.Content, volle Treue inkl. Anhaenge)

So laesst sich pro Eintrag der Verlauf UND der zugehoerige Kontext laden und
fortsetzen. Der Kontext-(De)Serializer liegt in agent.py; hier nur Datei-I/O.
"""

import json
import threading
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).parent.parent / "data" / "chats"
_LOCK = threading.RLock()
_MAX_TRANSCRIPT = 800   # max. Anzeige-Nachrichten pro Sitzung
_DEFAULT_TITLE = "Neuer Chat"


def _safe(s: str, fallback: str) -> str:
    """Datei-/pfadsicherer Name (verhindert Traversal)."""
    s = (s or "").strip()
    out = "".join(c for c in s if c.isalnum() or c in "._-@")
    return out or fallback


def _user_dir(user: str) -> Path:
    return _ROOT / _safe(user, "anonymous")


def _sess_dir(user: str, sid: str) -> Path:
    return _user_dir(user) / _safe(sid, "")


def _valid(user: str, sid: str) -> bool:
    sd = _sess_dir(user, sid)
    return bool(_safe(sid, "")) and sd.is_dir()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ─── Benutzer-Preprompt (persoenliche Vorab-Anweisung fuer /chat) ─────────────
# Gilt pro Benutzer (nicht pro Sitzung) und wird dem System-Prompt des
# Hauptagenten vorangestellt. Liegt in data/chats/<user>/preprompt.txt.

_PREPROMPT_MAX = 8000


def get_preprompt(user: str) -> str:
    """Liefert den persoenlichen Preprompt des Benutzers (leerer String, wenn keiner)."""
    p = _user_dir(user) / "preprompt.txt"
    try:
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def save_preprompt(user: str, text: str) -> str:
    """Speichert den persoenlichen Preprompt des Benutzers (auf _PREPROMPT_MAX
    Zeichen begrenzt). Leerer Text loescht die Datei. Rueckgabe: gespeicherter Text."""
    text = (text or "")[:_PREPROMPT_MAX]
    ud = _user_dir(user)
    p = ud / "preprompt.txt"
    with _LOCK:
        try:
            if text.strip():
                ud.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
            elif p.exists():
                p.unlink()
        except Exception:
            pass
    return text if text.strip() else ""


# ─── Metadaten / Sitzungsverwaltung ──────────────────────────────────────────

def _read_meta(sd: Path) -> dict | None:
    p = sd / "meta.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _write_meta(sd: Path, meta: dict) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def list_sessions(user: str) -> list:
    """Alle Sitzungen des Benutzers, neueste zuerst."""
    ud = _user_dir(user)
    out = []
    with _LOCK:
        if ud.is_dir():
            for sd in ud.iterdir():
                if not sd.is_dir():
                    continue
                m = _read_meta(sd)
                if m and m.get("id"):
                    out.append({"id": m["id"], "title": m.get("title", _DEFAULT_TITLE),
                                "created": m.get("created", 0), "updated": m.get("updated", 0)})
    out.sort(key=lambda x: x.get("updated", 0), reverse=True)
    return out


def create_session(user: str, title: str = "") -> dict:
    sid = new_id()
    now = int(time.time())
    meta = {"id": sid, "title": (title or _DEFAULT_TITLE).strip()[:120] or _DEFAULT_TITLE,
            "created": now, "updated": now}
    with _LOCK:
        _write_meta(_sess_dir(user, sid), meta)
    return meta


def rename_session(user: str, sid: str, title: str) -> dict | None:
    with _LOCK:
        if not _valid(user, sid):
            return None
        sd = _sess_dir(user, sid)
        meta = _read_meta(sd) or {"id": sid, "created": int(time.time())}
        meta["title"] = (title or _DEFAULT_TITLE).strip()[:120] or _DEFAULT_TITLE
        meta["updated"] = int(time.time())
        _write_meta(sd, meta)
        return {"id": sid, "title": meta["title"], "updated": meta["updated"]}


def delete_session(user: str, sid: str) -> bool:
    import shutil
    with _LOCK:
        if not _valid(user, sid):
            return False
        try:
            shutil.rmtree(_sess_dir(user, sid))
            return True
        except Exception:
            return False


def get_meta(user: str, sid: str) -> dict | None:
    """Rohe Metadaten einer Sitzung (inkl. gespeicherter kb_groups) oder None."""
    with _LOCK:
        if not _valid(user, sid):
            return None
        return _read_meta(_sess_dir(user, sid))


def save_kb_groups(user: str, sid: str, groups) -> None:
    """Wissensgruppen-Auswahl der Sitzung merken (None=alle, []=keine, [ids]=nur diese)."""
    with _LOCK:
        sd = _sess_dir(user, sid)
        meta = _read_meta(sd)
        if not meta:
            return
        meta["kb_groups"] = groups
        _write_meta(sd, meta)


def save_profile(user: str, sid: str, profile_id) -> None:
    """Gewaehltes KI-Profil der Sitzung merken (fuer den Profil-Pulldown in /chat)."""
    with _LOCK:
        sd = _sess_dir(user, sid)
        meta = _read_meta(sd)
        if not meta:
            return
        meta["profile_id"] = (profile_id or "")
        _write_meta(sd, meta)


def touch(user: str, sid: str, auto_title: str = "") -> None:
    """Aktualisiert den updated-Zeitstempel; setzt bei noch unbenanntem Chat
    optional einen Titel aus dem ersten Nutzertext."""
    with _LOCK:
        sd = _sess_dir(user, sid)
        meta = _read_meta(sd)
        if not meta:
            return
        meta["updated"] = int(time.time())
        if auto_title and meta.get("title", _DEFAULT_TITLE) == _DEFAULT_TITLE:
            meta["title"] = " ".join(auto_title.split())[:60] or _DEFAULT_TITLE
        _write_meta(sd, meta)


# ─── Transkript (Anzeige) ────────────────────────────────────────────────────

def load_transcript(user: str, sid: str) -> list:
    with _LOCK:
        if not _valid(user, sid):
            return []
        p = _sess_dir(user, sid) / "transcript.json"
        if not p.exists():
            return []
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except Exception:
            return []


def save_transcript(user: str, sid: str, messages: list) -> list:
    if not isinstance(messages, list):
        messages = []
    messages = messages[-_MAX_TRANSCRIPT:]
    with _LOCK:
        if not _valid(user, sid):
            return []
        (_sess_dir(user, sid) / "transcript.json").write_text(
            json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    return messages


# ─── LLM-Kontext (serialisierte types.Content-Dicts) ─────────────────────────

def load_context(user: str, sid: str) -> list:
    with _LOCK:
        if not _valid(user, sid):
            return []
        p = _sess_dir(user, sid) / "context.json"
        if not p.exists():
            return []
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except Exception:
            return []


def save_context(user: str, sid: str, content_dicts: list) -> None:
    if not isinstance(content_dicts, list):
        return
    with _LOCK:
        if not _valid(user, sid):
            return
        (_sess_dir(user, sid) / "context.json").write_text(
            json.dumps(content_dicts, ensure_ascii=False), encoding="utf-8")
