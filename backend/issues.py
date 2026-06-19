"""Issue-Tracker: persistente Issue-Datenbank fuer User-Feedback (Bugs, Features, Improvements).

Berechtigungsmodell:
- Sehen: jeder authentifizierte Benutzer (alle Issues)
- Erstellen: jeder authentifizierte Benutzer
- Eigene Issues editieren: nur solange status != "closed"
- Alle Issues editieren, Status/Comment setzen, schliessen, loeschen: nur Benutzer "jarvis"

Speicherung:
- data/issues.json (Atomic-Write via .tmp + replace)
- data/issue_attachments/<issue_id>/<filename>
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from backend.config import config, PROJECT_ROOT

# ─── Pfade ──────────────────────────────────────────────────────────────
# config._data_dir respektiert DATA_DIR-Env (Docker), Fallback PROJECT_ROOT/data
_DATA_DIR = getattr(config, "_data_dir", None) or (PROJECT_ROOT / "data")
ISSUES_FILE = _DATA_DIR / "issues.json"
ATTACH_DIR = _DATA_DIR / "issue_attachments"
ATTACH_DIR.mkdir(parents=True, exist_ok=True)

# ─── Konstanten ─────────────────────────────────────────────────────────
JARVIS_USER = "jarvis"
VALID_TYPES = {"bug", "feature", "improvement"}
VALID_STATUS = {"open", "in_progress", "closed"}
VALID_PRIORITY = {"low", "medium", "high"}

MAX_TITLE_LEN = 200
MAX_BODY_LEN = 20000
MAX_COMMENT_LEN = 20000
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MiB pro Datei
MAX_ATTACHMENTS_PER_ISSUE = 10

# ─── Thread-Safety ─────────────────────────────────────────────────────
_lock = threading.RLock()


# ═══ Storage ════════════════════════════════════════════════════════════

def _load_all() -> list[dict]:
    """Alle Issues aus Datei laden. Gibt leere Liste zurueck wenn Datei fehlt."""
    if not ISSUES_FILE.exists():
        return []
    try:
        with ISSUES_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"[issues] Fehler beim Laden: {e}", flush=True)
        return []


def _save_all(issues: list[dict]) -> None:
    """Issues atomar speichern (tmp + replace)."""
    ISSUES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ISSUES_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)
    tmp.replace(ISSUES_FILE)


# ═══ Permissions ════════════════════════════════════════════════════════

def is_jarvis(user: str) -> bool:
    """Ist der Benutzer der Admin-User 'jarvis'?"""
    return (user or "").strip().lower() == JARVIS_USER


def can_edit(issue: dict, user: str) -> bool:
    """Darf der Benutzer das Issue bearbeiten?

    - jarvis: immer
    - Autor: nur solange status != 'closed'
    """
    if is_jarvis(user):
        return True
    if issue.get("author", "").strip().lower() != (user or "").strip().lower():
        return False
    return issue.get("status") != "closed"


def can_delete(issue: dict, user: str) -> bool:
    """Nur jarvis darf loeschen."""
    return is_jarvis(user)


# ═══ Validation ═════════════════════════════════════════════════════════

def _validate_create(data: dict) -> tuple[bool, str]:
    """Pflichtfelder + Typen pruefen. (ok, error_msg)."""
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    itype = (data.get("type") or "bug").strip().lower()
    priority = (data.get("priority") or "medium").strip().lower()

    if not title:
        return False, "Titel ist erforderlich."
    if len(title) > MAX_TITLE_LEN:
        return False, f"Titel zu lang (max {MAX_TITLE_LEN} Zeichen)."
    if len(body) > MAX_BODY_LEN:
        return False, f"Beschreibung zu lang (max {MAX_BODY_LEN} Zeichen)."
    if itype not in VALID_TYPES:
        return False, f"Ungueltiger Typ. Erlaubt: {sorted(VALID_TYPES)}"
    if priority not in VALID_PRIORITY:
        return False, f"Ungueltige Prioritaet. Erlaubt: {sorted(VALID_PRIORITY)}"
    return True, ""


def _safe_filename(name: str) -> str:
    """Filename saeubern – keine Slashes, kein .., max 100 chars.

    Wichtig: verhindert Path-Traversal (../) und absolute Pfade.
    """
    name = (name or "").strip()
    # Pfad-Komponenten entfernen
    name = Path(name).name
    # Gefaehrliche Zeichen filtern
    safe = "".join(c for c in name if c.isalnum() or c in "._- ()[]")
    safe = safe.strip(". ")
    if not safe:
        safe = f"file_{int(time.time())}"
    return safe[:100]


# ═══ CRUD ═══════════════════════════════════════════════════════════════

def list_issues(user: str, *, mine_only: bool = False,
                status: str | None = None, type_: str | None = None) -> list[dict]:
    """Liste aller Issues, optional gefiltert. Jeder authentifizierte User darf alle sehen."""
    with _lock:
        issues = _load_all()

    if mine_only:
        u = (user or "").strip().lower()
        issues = [i for i in issues if i.get("author", "").strip().lower() == u]
    if status and status in VALID_STATUS:
        issues = [i for i in issues if i.get("status") == status]
    if type_ and type_ in VALID_TYPES:
        issues = [i for i in issues if i.get("type") == type_]

    # Neueste zuerst
    issues.sort(key=lambda i: i.get("created", ""), reverse=True)
    return issues


def get_issue(issue_id: str) -> dict | None:
    """Einzelnes Issue per ID. None wenn nicht gefunden."""
    with _lock:
        for i in _load_all():
            if i.get("id") == issue_id:
                return i
    return None


def create_issue(user: str, data: dict) -> tuple[dict | None, str]:
    """Neues Issue anlegen. Gibt (issue, "") oder (None, err)."""
    ok, err = _validate_create(data)
    if not ok:
        return None, err

    now = _now_iso()
    issue = {
        "id": uuid.uuid4().hex,
        "author": user,
        "created": now,
        "updated": now,
        "title": data["title"].strip(),
        "body": (data.get("body") or "").strip(),
        "type": data.get("type", "bug").strip().lower(),
        "status": "open",
        "status_seen": "open",   # vom Autor zuletzt gesehener Status (fuer Badge-Benachrichtigung)
        "priority": data.get("priority", "medium").strip().lower(),
        "jarvis_comment": "",
        "attachments": [],
    }

    with _lock:
        issues = _load_all()
        issues.append(issue)
        _save_all(issues)
    return issue, ""


def update_issue(user: str, issue_id: str, patch: dict) -> tuple[dict | None, str]:
    """Issue bearbeiten. Gibt (issue, "") oder (None, err).

    Nicht-Jarvis-Benutzer duerfen nur title/body/type/priority aendern und nur
    bei eigenen Issues mit status != closed.
    Jarvis darf zusaetzlich status und jarvis_comment setzen.
    """
    with _lock:
        issues = _load_all()
        idx = None
        for i, it in enumerate(issues):
            if it.get("id") == issue_id:
                idx = i
                break
        if idx is None:
            return None, "Issue nicht gefunden."

        current = issues[idx]
        if not can_edit(current, user):
            if current.get("status") == "closed" and not is_jarvis(user):
                return None, "Issue ist geschlossen – nur Jarvis darf bearbeiten."
            return None, "Keine Berechtigung."

        # Erlaubte Felder fuer alle: title, body, type, priority
        for fld in ("title", "body", "type", "priority"):
            if fld in patch:
                val = (patch[fld] or "").strip() if isinstance(patch[fld], str) else patch[fld]
                if fld == "title":
                    if not val:
                        return None, "Titel darf nicht leer sein."
                    if len(val) > MAX_TITLE_LEN:
                        return None, f"Titel zu lang (max {MAX_TITLE_LEN})."
                elif fld == "body":
                    if len(val) > MAX_BODY_LEN:
                        return None, f"Beschreibung zu lang (max {MAX_BODY_LEN})."
                elif fld == "type":
                    val = val.lower()
                    if val not in VALID_TYPES:
                        return None, f"Ungueltiger Typ."
                elif fld == "priority":
                    val = val.lower()
                    if val not in VALID_PRIORITY:
                        return None, f"Ungueltige Prioritaet."
                current[fld] = val

        # Nur Jarvis: status + jarvis_comment
        if is_jarvis(user):
            if "status" in patch:
                s = (patch["status"] or "").strip().lower()
                if s not in VALID_STATUS:
                    return None, f"Ungueltiger Status."
                current["status"] = s
            if "jarvis_comment" in patch:
                c = (patch["jarvis_comment"] or "").strip()
                if len(c) > MAX_COMMENT_LEN:
                    return None, f"Kommentar zu lang (max {MAX_COMMENT_LEN})."
                current["jarvis_comment"] = c

        current["updated"] = _now_iso()
        issues[idx] = current
        _save_all(issues)
        return current, ""


def unseen_count(user: str) -> int:
    """Anzahl eigener Issues, deren Status sich seit dem letzten Ansehen geaendert hat.

    Grundlage fuer die Badge-Benachrichtigung beim meldenden Benutzer.
    """
    u = (user or "").strip().lower()
    if not u:
        return 0
    with _lock:
        issues = _load_all()
    n = 0
    for i in issues:
        if i.get("author", "").strip().lower() != u:
            continue
        seen = i.get("status_seen")
        # Alt-Issues ohne status_seen (vor dem Feature angelegt) NICHT als
        # Benachrichtigung zaehlen – sonst Pseudo-Badge fuer laengst bekannte Status.
        # Neue Issues erhalten status_seen="open" und werden korrekt verfolgt.
        if not seen:
            continue
        if i.get("status") != seen:
            n += 1
    return n


def mark_seen(user: str) -> int:
    """Markiert alle eigenen Issues als 'Status gesehen' (loescht die Badge-Benachrichtigung).
    Gibt die Anzahl aktualisierter Issues zurueck."""
    u = (user or "").strip().lower()
    if not u:
        return 0
    with _lock:
        issues = _load_all()
        changed = 0
        for i in issues:
            if i.get("author", "").strip().lower() != u:
                continue
            if i.get("status_seen", "open") != i.get("status"):
                i["status_seen"] = i.get("status")
                changed += 1
        if changed:
            _save_all(issues)
    return changed


def delete_issue(user: str, issue_id: str) -> tuple[bool, str]:
    """Issue loeschen (nur jarvis). Loescht auch Attachment-Ordner."""
    with _lock:
        issues = _load_all()
        target = None
        for i in issues:
            if i.get("id") == issue_id:
                target = i
                break
        if not target:
            return False, "Issue nicht gefunden."
        if not can_delete(target, user):
            return False, "Nur Jarvis darf Issues loeschen."

        issues = [i for i in issues if i.get("id") != issue_id]
        _save_all(issues)

    # Attachment-Ordner aufraeumen (ausserhalb des Locks)
    att_dir = _attach_dir(issue_id)
    if att_dir.exists():
        try:
            shutil.rmtree(att_dir)
        except Exception as e:
            print(f"[issues] Attachment-Ordner Loesch-Fehler: {e}", flush=True)
    return True, ""


# ═══ Attachments ═════════════════════════════════════════════════════════

def _attach_dir(issue_id: str) -> Path:
    """Pfad zu Attachment-Ordner. ID muss alphanumerisch sein (hex)."""
    safe_id = "".join(c for c in issue_id if c.isalnum())[:64]
    return ATTACH_DIR / safe_id


def add_attachment(user: str, issue_id: str, filename: str,
                   content: bytes) -> tuple[str | None, str]:
    """Anhang zu Issue speichern. Gibt (saved_filename, "") oder (None, err)."""
    if len(content) > MAX_ATTACHMENT_SIZE:
        return None, f"Datei zu gross (max {MAX_ATTACHMENT_SIZE // (1024*1024)} MiB)."

    with _lock:
        issues = _load_all()
        idx = None
        for i, it in enumerate(issues):
            if it.get("id") == issue_id:
                idx = i
                break
        if idx is None:
            return None, "Issue nicht gefunden."
        current = issues[idx]
        if not can_edit(current, user):
            return None, "Keine Berechtigung."
        if len(current.get("attachments", [])) >= MAX_ATTACHMENTS_PER_ISSUE:
            return None, f"Maximal {MAX_ATTACHMENTS_PER_ISSUE} Anhaenge pro Issue."

        safe = _safe_filename(filename)
        att_dir = _attach_dir(issue_id)
        att_dir.mkdir(parents=True, exist_ok=True)

        # Bei Namens-Kollision: Suffix anhaengen
        target = att_dir / safe
        n = 1
        while target.exists():
            stem = Path(safe).stem
            suf = Path(safe).suffix
            target = att_dir / f"{stem}_{n}{suf}"
            n += 1
            if n > 100:
                return None, "Zu viele Namens-Kollisionen."

        # Sicherheits-Check: aufgeloester Pfad MUSS unterhalb ATTACH_DIR sein
        try:
            target_resolved = target.resolve()
            att_root_resolved = ATTACH_DIR.resolve()
            if att_root_resolved not in target_resolved.parents:
                return None, "Ungueltiger Pfad."
        except Exception:
            return None, "Pfad-Aufloesung fehlgeschlagen."

        target.write_bytes(content)

        atts = current.get("attachments", [])
        atts.append(target.name)
        current["attachments"] = atts
        current["updated"] = _now_iso()
        issues[idx] = current
        _save_all(issues)
        return target.name, ""


def get_attachment_path(issue_id: str, filename: str) -> Path | None:
    """Pfad zu einem Anhang. Liefert None bei Path-Traversal-Versuch oder fehlender Datei."""
    safe = _safe_filename(filename)
    att_dir = _attach_dir(issue_id)
    p = att_dir / safe
    try:
        p_resolved = p.resolve()
        if ATTACH_DIR.resolve() not in p_resolved.parents:
            return None
        if not p_resolved.is_file():
            return None
        return p_resolved
    except Exception:
        return None


def delete_attachment(user: str, issue_id: str, filename: str) -> tuple[bool, str]:
    """Anhang entfernen. Berechtigung wie update_issue."""
    safe = _safe_filename(filename)
    with _lock:
        issues = _load_all()
        idx = None
        for i, it in enumerate(issues):
            if it.get("id") == issue_id:
                idx = i
                break
        if idx is None:
            return False, "Issue nicht gefunden."
        current = issues[idx]
        if not can_edit(current, user):
            return False, "Keine Berechtigung."

        att_dir = _attach_dir(issue_id)
        target = att_dir / safe
        try:
            target_resolved = target.resolve()
            if ATTACH_DIR.resolve() not in target_resolved.parents:
                return False, "Ungueltiger Pfad."
            if target_resolved.is_file():
                target_resolved.unlink()
        except Exception:
            pass

        atts = [a for a in current.get("attachments", []) if a != safe]
        current["attachments"] = atts
        current["updated"] = _now_iso()
        issues[idx] = current
        _save_all(issues)
    return True, ""


# ═══ Helpers ═════════════════════════════════════════════════════════════

def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
