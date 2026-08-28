"""Issue-Tracker: persistente Issue-Datenbank fuer User-Feedback (Bugs, Features, Improvements).

Berechtigungsmodell:
- Sehen: jeder authentifizierte Benutzer (alle Issues)
- Erstellen: jeder authentifizierte Benutzer
- Eigene Issues editieren ('editieren'): der Ersteller, solange status != "closed"
- Loesungsbereich ('bearbeiten', status + jarvis_comment): alle Administratoren
  (is_admin wird vom Aufrufer in main.py via _is_admin_user bestimmt) sowie "jarvis"
- ALLE Felder einer FREMDEN Meldung (Titel, Text, Typ, Prioritaet, Anhaenge):
  alle Administratoren sowie "jarvis" (``can_edit``) – auch bei status "closed"
- Loeschen: alle Administratoren sowie "jarvis" (``can_delete``)

⚠ VORGABE 2026-08-28: Ein Administrator muss bei einer Meldung ALLE Felder
bearbeiten koennen. Bis dahin trennte dieses Modul „editieren" (Meldungstext,
nur der Ersteller) von „bearbeiten" (Loesungsbereich, Administratoren) und liess
den fremden Text ausdruecklich nur ``jarvis`` aendern. Diese Trennung ist
aufgehoben; sie bleibt nur noch als Aufteilung der OBERFLAECHE in zwei
Formulare bestehen, nicht als Rechteschranke.

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
# Pro Admin: zuletzt gesehener Issue-Erstellzeitpunkt (fuer die Badge bei NEUEN
# Issues anderer). {norm_login: created_iso}
ADMIN_SEEN_FILE = _DATA_DIR / "issues_admin_seen.json"
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


def _load_admin_seen() -> dict:
    if not ADMIN_SEEN_FILE.exists():
        return {}
    try:
        with ADMIN_SEEN_FILE.open("r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_admin_seen(d: dict) -> None:
    ADMIN_SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ADMIN_SEEN_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    tmp.replace(ADMIN_SEEN_FILE)


# ═══ Permissions ════════════════════════════════════════════════════════

def is_jarvis(user: str) -> bool:
    """Ist der Benutzer der Admin-User 'jarvis'?"""
    return (user or "").strip().lower() == JARVIS_USER


def can_edit(issue: dict, user: str, is_admin: bool = False) -> bool:
    """Darf der Benutzer die INHALTSFELDER des Issues aendern?

    - ``jarvis``: immer
    - Administratoren: immer, auch bei fremden und geschlossenen Meldungen
      (Vorgabe 2026-08-28: ein Administrator muss ALLE Felder bearbeiten
      koennen – Titel, Text, Typ, Prioritaet und Anhaenge, nicht nur den
      Loesungsbereich)
    - Autor: nur solange status != 'closed'

    ⚠ ``is_admin`` MUSS uebergeben werden; die Vorgabe ``False`` ist
    fail-closed. Das Modul kennt die Rechtelage nicht selbst: wer Administrator
    ist, entscheidet ``main.py::_is_admin_user`` (Benutzerliste ODER
    AD-Gruppe) – dieselbe Aufteilung wie bei ``can_delete``, ``update_issue``
    und ``unseen_count``. Ein Aufrufer, der das Argument vergisst, bekommt das
    alte, engere Verhalten und keine stille Rechteerweiterung.

    Der Autor bleibt an ``status != 'closed'`` gebunden: eine abgeschlossene
    Meldung ist die Grundlage der Antwort, die er bekommen hat – wer sie
    nachtraeglich umschreibt, entwertet den Vorgang. Ein Administrator darf
    genau das, weil er den Vorgang verantwortet.
    """
    if is_jarvis(user) or bool(is_admin):
        return True
    if issue.get("author", "").strip().lower() != (user or "").strip().lower():
        return False
    return issue.get("status") != "closed"


def can_delete(issue: dict, user: str, is_admin: bool = False) -> bool:
    """Loeschen duerfen Administratoren – und der lokale Benutzer ``jarvis``.

    ⚠ ``is_admin`` MUSS uebergeben werden; die Vorgabe ``False`` ist
    fail-closed. Das Modul kennt die Rechtelage nicht selbst: wer Administrator
    ist, entscheidet ``main.py::_is_admin_user`` (Benutzerliste ODER
    AD-Gruppe) – dieselbe Aufteilung wie bei ``update_issue`` und
    ``unseen_count``. Ein Aufrufer, der das Argument vergisst, bekommt das alte,
    engere Verhalten und keine stille Rechteerweiterung.

    Der lokale ``jarvis`` bleibt ausdruecklich drin: er ist der Rueckweg, wenn
    die AD-Freigaben leer oder falsch gesetzt sind (gleiche Begruendung wie bei
    „leer = niemand" in der Anmeldung).

    ``can_edit`` traegt seit dem 2026-08-28 dieselbe Regel (Vorgabe des
    Nutzers) – vorher war das Loeschen ausdruecklich weiter gefasst als das
    Bearbeiten.
    """
    return is_jarvis(user) or bool(is_admin)


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


def update_issue(user: str, issue_id: str, patch: dict,
                 *, is_admin: bool = False) -> tuple[dict | None, str]:
    """Issue bearbeiten. Gibt (issue, "") oder (None, err).

    - Inhaltsfelder (title/body/type/priority): der Ersteller ('editieren',
      solange status != closed) sowie Administratoren und jarvis – IMMER.
    - Loesungsbereich (status/jarvis_comment): Administratoren ('bearbeiten',
      is_admin=True vom Aufrufer bestimmt) sowie jarvis.

    Beide Bereiche stehen einem Administrator damit vollstaendig offen; die
    Aufteilung in zwei Formulare ist nur noch eine Frage der Oberflaeche.
    """
    allowed_admin = is_admin or is_jarvis(user)
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
        allowed_content = can_edit(current, user, is_admin)
        if not (allowed_content or allowed_admin):
            if current.get("status") == "closed":
                return None, ("Issue ist geschlossen – nur ein Administrator "
                              "darf es noch bearbeiten.")
            return None, "Keine Berechtigung."

        # Inhaltsfelder: Ersteller, Administratoren und jarvis
        for fld in ("title", "body", "type", "priority"):
            if fld in patch:
                if not allowed_content:
                    return None, ("Keine Berechtigung – den Inhalt duerfen nur "
                                  "der Ersteller und Administratoren aendern.")
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

        # Loesungsbereich (Admins + jarvis): status + jarvis_comment
        if allowed_admin:
            admin_changed = False
            if "status" in patch:
                s = (patch["status"] or "").strip().lower()
                if s not in VALID_STATUS:
                    return None, f"Ungueltiger Status."
                if s != current.get("status"):
                    admin_changed = True
                current["status"] = s
            if "jarvis_comment" in patch:
                c = (patch["jarvis_comment"] or "").strip()
                if len(c) > MAX_COMMENT_LEN:
                    return None, f"Kommentar zu lang (max {MAX_COMMENT_LEN})."
                if c != (current.get("jarvis_comment") or ""):
                    admin_changed = True
                current["jarvis_comment"] = c
            # Badge-Benachrichtigung fuer den Ersteller: JEDE Admin-Bearbeitung
            # (auch reiner Kommentar ohne Statuswechsel) zaehlt – ausser der
            # Ersteller bearbeitet sein eigenes Issue selbst.
            if admin_changed and current.get("author", "").strip().lower() != (user or "").strip().lower():
                current["admin_change_pending"] = True

        current["updated"] = _now_iso()
        issues[idx] = current
        _save_all(issues)
        return current, ""


# Auszug des Admin-Kommentars in der Badge-Liste. Er beantwortet die einzige
# Frage, die ein Melder beim Hovern hat („was ist daraus geworden?"), darf die
# Liste aber nicht sprengen.
NOTIF_COMMENT_LEN = 140


def unseen_details(user: str, is_admin: bool = False) -> list[dict]:
    """Die Badge-Benachrichtigungen dieses Benutzers – EINZELN aufgefuehrt.

    - EIGENE Issues mit ungesehener Bearbeitung (Statuswechsel/Admin-Kommentar)
      → ``kind="edited"``
    - Fuer ADMINS zusaetzlich: NEUE Issues ANDERER seit dem letzten "gesehen"
      → ``kind="new"``

    So erhalten alle Admins eine Badge, sobald ein neues Issue erzeugt wird.

    ⚠ DIES IST DIE EINZIGE STELLE, DIE DIE REGEL KENNT. ``unseen_count`` zaehlt
    nur noch, was hier herauskommt – eine zweite, „schnellere" Zaehlschleife
    daneben waere eine zweite Fassung derselben Regel und liefe beim naechsten
    Feld auseinander: der Badge stuende dann auf 3 und die Liste zeigte 2, ohne
    dass jemand sagen koennte, welche der beiden Zahlen stimmt.

    Neueste zuerst. Der Rueckgabewert ist frei von Geheimnissen: er enthaelt
    nur, was ``list_issues`` ohnehin jedem angemeldeten Benutzer zeigt.
    """
    u = (user or "").strip().lower()
    if not u:
        return []
    with _lock:
        issues = _load_all()

    treffer: list[dict] = []

    def _eintrag(i: dict, kind: str, ts: str) -> dict:
        e = {
            "id": i.get("id", ""),
            "title": i.get("title", ""),
            "kind": kind,
            "status": i.get("status", ""),
            "type": i.get("type", ""),
            "ts": ts,
        }
        if kind == "new":
            e["author"] = i.get("author", "")
        else:
            # Der Kommentar IST die Nachricht an den Melder – ohne ihn sagt die
            # Zeile nur, DASS etwas passiert ist.
            k = (i.get("jarvis_comment") or "").strip()
            if k:
                e["comment"] = (k[:NOTIF_COMMENT_LEN] + "…"
                                if len(k) > NOTIF_COMMENT_LEN else k)
        return e

    for i in issues:
        if i.get("author", "").strip().lower() != u:
            continue
        if i.get("admin_change_pending"):
            treffer.append(_eintrag(i, "edited", i.get("updated", "")))
            continue
        seen = i.get("status_seen")
        # Alt-Issues ohne status_seen (vor dem Feature angelegt) NICHT als
        # Benachrichtigung zaehlen – sonst Pseudo-Badge fuer laengst bekannte Status.
        if not seen:
            continue
        if i.get("status") != seen:
            treffer.append(_eintrag(i, "edited", i.get("updated", "")))

    if is_admin:
        with _lock:
            seen_map = _load_admin_seen()
            marker = seen_map.get(u)
            latest = max((i.get("created", "") for i in issues), default="")
            if marker is None:
                # Lazy-Init: bestehende Issues nicht nachtraeglich als "neu" melden.
                seen_map[u] = latest
                _save_admin_seen(seen_map)
            else:
                for i in issues:
                    if (i.get("author", "").strip().lower() != u
                            and i.get("created", "") > marker):
                        treffer.append(_eintrag(i, "new", i.get("created", "")))

    # Neueste zuerst. Ein fehlender Zeitstempel sortiert nach hinten statt zu
    # werfen – ein Altbestand-Eintrag darf die Liste nicht unbrauchbar machen.
    treffer.sort(key=lambda e: e.get("ts") or "", reverse=True)
    return treffer


def unseen_count(user: str, is_admin: bool = False) -> int:
    """Anzahl der Badge-Benachrichtigungen – siehe ``unseen_details``.

    Bewusst nur ein ``len()``: Zaehler und Liste koennen so nicht auseinander
    laufen. Die Nebenwirkung von ``unseen_details`` (Lazy-Init des
    Admin-Markers) bleibt damit unveraendert erhalten.
    """
    return len(unseen_details(user, is_admin))


def mark_seen(user: str, is_admin: bool = False) -> int:
    """Markiert alle eigenen Issues als 'Status gesehen' (loescht die Badge-
    Benachrichtigung). Fuer Admins zusaetzlich: NEUE Issues anderer als gesehen
    markieren (Admin-Badge zuruecksetzen). Gibt die Anzahl aktualisierter
    eigener Issues zurueck."""
    u = (user or "").strip().lower()
    if not u:
        return 0
    with _lock:
        issues = _load_all()
        changed = 0
        for i in issues:
            if i.get("author", "").strip().lower() != u:
                continue
            touched = False
            if i.get("status_seen", "open") != i.get("status"):
                i["status_seen"] = i.get("status")
                touched = True
            if i.get("admin_change_pending"):
                i["admin_change_pending"] = False
                touched = True
            if touched:
                changed += 1
        if changed:
            _save_all(issues)
        if is_admin:
            seen_map = _load_admin_seen()
            latest = max((i.get("created", "") for i in issues), default="")
            if seen_map.get(u) != latest:
                seen_map[u] = latest
                _save_admin_seen(seen_map)
    return changed


def delete_issue(user: str, issue_id: str, is_admin: bool = False) -> tuple[bool, str]:
    """Issue loeschen (Administratoren). Loescht auch den Attachment-Ordner."""
    with _lock:
        issues = _load_all()
        target = None
        for i in issues:
            if i.get("id") == issue_id:
                target = i
                break
        if not target:
            return False, "Issue nicht gefunden."
        if not can_delete(target, user, is_admin):
            # Das Wort "Berechtigung" traegt die Antwort: der Endpunkt macht
            # daraus 403, alles andere waere ein 404 ("nicht gefunden").
            return False, "Keine Berechtigung – Meldungen darf nur ein Administrator loeschen."

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
                   content: bytes, *, is_admin: bool = False) -> tuple[str | None, str]:
    """Anhang zu Issue speichern. Gibt (saved_filename, "") oder (None, err).

    Berechtigung wie ``can_edit`` – ein Anhang IST ein Feld der Meldung. Waere
    ``is_admin`` hier nicht durchgereicht, duerfte ein Administrator jedes Feld
    aendern ausser diesem, ohne dass die Oberflaeche den Unterschied erklaeren
    koennte.
    """
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
        if not can_edit(current, user, is_admin):
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


def delete_attachment(user: str, issue_id: str, filename: str,
                      *, is_admin: bool = False) -> tuple[bool, str]:
    """Anhang entfernen. Berechtigung wie ``can_edit`` (siehe add_attachment)."""
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
        if not can_edit(current, user, is_admin):
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
