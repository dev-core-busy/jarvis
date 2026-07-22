"""Wissensgruppierung – logische Tags (Modell B) fuer die Knowledge Base.

Gruppen sind *logische Tags*, entkoppelt von der Ordnerstruktur auf der Platte.
Ein Dokument kann zu 0, 1 oder mehreren Gruppen gehoeren (Mehrfachzuordnung).
"ungruppiert" ist eine *virtuelle* Gruppe = jede indizierte Datei ohne Eintrag.

Persistenz: ``data/knowledge/.groups.json`` (Sidecar-Manifest, ueberlebt Reindex).
Pfade werden relativ zu ``PROJECT_ROOT`` und mit Forward-Slashes gespeichert,
damit das Manifest portabel bleibt.
"""

import json
import re
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "knowledge" / ".groups.json"

# Virtuelle Gruppe fuer Dateien ohne Tag – NICHT im Manifest gespeichert.
UNGROUPED_ID = "ungrouped"

# System-Gruppe fuer automatisch erlerntes Wissen. Alle systemgenerierten
# Wissensdateien (learning.py: conv_*.md, main.py-Feedback: feedback_*.md,
# knowledge_compactor.py: konsolidiert/conv_konsolidiert_*.md) liegen unter
# data/knowledge/learned/ und werden dieser Gruppe automatisch zugeordnet,
# damit sie nicht als "ungruppiert" erscheinen.
LEARNED_GROUP_NAME = "Erlernt"
LEARNED_GROUP_COLOR = "#10b981"
LEARNED_PATH_PREFIX = "data/knowledge/learned/"

# Beim ersten Anlegen vorbelegte, feste Startgruppen.
_SEED_GROUPS = [
    {"id": "ibs", "name": "IBS", "color": "#3b82f6", "order": 0},
    {"id": "dc-pathos", "name": "DC-Pathos", "color": "#a855f7", "order": 1},
]

_lock = threading.Lock()


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    """Erzeugt eine stabile, URL-taugliche ID aus einem Gruppennamen."""
    s = (name or "").strip().lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "gruppe"


def _rel(path) -> str:
    """Normalisiert einen Pfad auf einen relativen Posix-String zu PROJECT_ROOT."""
    p = Path(path)
    try:
        if p.is_absolute():
            p = p.relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    return p.as_posix().lstrip("/")


def _default_manifest() -> dict:
    return {"groups": [dict(g) for g in _SEED_GROUPS], "assignments": {}}


# ─── Laden / Speichern ───────────────────────────────────────────────────────

def _load_unlocked() -> dict:
    if not MANIFEST_PATH.exists():
        return _default_manifest()
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _default_manifest()
    if not isinstance(data, dict):
        return _default_manifest()
    data.setdefault("groups", [])
    data.setdefault("assignments", {})
    # Erst-Migration: leeres Manifest -> Startgruppen setzen.
    if not data["groups"] and not data["assignments"]:
        data["groups"] = [dict(g) for g in _SEED_GROUPS]
    return data


def _save_unlocked(data: dict):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load() -> dict:
    with _lock:
        return _load_unlocked()


# ─── Gruppen-Registry ────────────────────────────────────────────────────────

def list_groups(all_rel_paths=None) -> dict:
    """Liefert die Gruppenliste inkl. Zaehlern + die virtuelle Gruppe "ungruppiert".

    ``all_rel_paths`` (optional): Liste ALLER aktuell indizierten Dateien
    (relativ). Wird sie uebergeben, zaehlen wir nur noch existierende Dateien
    und koennen die "ungruppiert"-Zahl berechnen.
    """
    with _lock:
        data = _load_unlocked()
    assignments = data.get("assignments", {})
    known = set(_rel(p) for p in all_rel_paths) if all_rel_paths is not None else None

    def _count(gid: str) -> int:
        n = 0
        for path, gids in assignments.items():
            if gid not in gids:
                continue
            if known is not None and _rel(path) not in known:
                continue
            n += 1
        return n

    groups = sorted(data.get("groups", []), key=lambda g: g.get("order", 0))
    out_groups = [{
        "id": g["id"],
        "name": g.get("name", g["id"]),
        "color": g.get("color", "#64748b"),
        "order": g.get("order", 0),
        "count": _count(g["id"]),
        # Pro-Gruppe zusaetzliche Wissens-Editoren (analog Sicherheit -> Berechtigungen):
        # AD-Benutzer kommagetrennt, AD-Gruppen-DNs zeilengetrennt.
        "editors_users": g.get("editors_users", ""),
        "editors_group": g.get("editors_group", ""),
        # Speicherordner der Gruppe (relative Pfade, z.B. "data/ibs"): werden
        # /wissen-Nutzern dieser Gruppe als Upload-Ziel angeboten.
        "folders": list(g.get("folders", [])),
    } for g in groups]

    ungrouped_count = None
    if known is not None:
        assigned = {
            _rel(p) for p, gids in assignments.items()
            if gids and _rel(p) in known
        }
        ungrouped_count = len(known - assigned)

    return {"groups": out_groups, "ungrouped_count": ungrouped_count}


def ungrouped_files(all_rel_paths) -> list:
    """Relative Pfade aller indizierten Dateien OHNE Gruppen-Zuordnung
    (Gegenstueck zur ungrouped_count-Zahl aus list_groups)."""
    with _lock:
        data = _load_unlocked()
    assignments = data.get("assignments", {})
    known = {_rel(p) for p in (all_rel_paths or [])}
    assigned = {_rel(p) for p, gids in assignments.items() if gids}
    return sorted(known - assigned)


def _valid_ids(data: dict) -> set:
    return {g["id"] for g in data.get("groups", [])}


def get_group(gid: str) -> dict:
    """Liefert die rohe Gruppen-Definition (inkl. Editoren) oder None.

    Wird backend-seitig fuer die Berechtigungspruefung benoetigt (welche
    AD-Benutzer/-Gruppen duerfen genau diese Gruppe bearbeiten)."""
    with _lock:
        data = _load_unlocked()
    for g in data.get("groups", []):
        if g["id"] == gid:
            return dict(g)
    return None


def create_group(name: str, color: str = "#64748b") -> dict:
    """Legt eine neue Gruppe an. Kollidierende IDs werden durchnummeriert."""
    with _lock:
        data = _load_unlocked()
        existing = _valid_ids(data)
        base = _slugify(name)
        gid = base
        i = 2
        while gid in existing:
            gid = f"{base}-{i}"
            i += 1
        order = max((g.get("order", 0) for g in data["groups"]), default=-1) + 1
        group = {"id": gid, "name": (name or gid).strip(), "color": color, "order": order}
        data["groups"].append(group)
        _save_unlocked(data)
        return group


def update_group(gid: str, name=None, color=None, order=None,
                 editors_users=None, editors_group=None, folders=None) -> dict:
    """Aktualisiert eine Gruppe. ``None`` = Feld unveraendert lassen,
    Leerstring bei den Editoren-Feldern loescht die jeweilige Zuordnung.
    ``folders``: Liste relativer Speicherordner-Pfade (leere Liste = keine)."""
    with _lock:
        data = _load_unlocked()
        for g in data["groups"]:
            if g["id"] == gid:
                if name is not None:
                    g["name"] = name.strip()
                if color is not None:
                    g["color"] = color
                if order is not None:
                    g["order"] = int(order)
                if editors_users is not None:
                    g["editors_users"] = (editors_users or "").strip()
                if editors_group is not None:
                    g["editors_group"] = (editors_group or "").strip()
                if folders is not None:
                    g["folders"] = [_rel(f) for f in folders if str(f).strip()]
                _save_unlocked(data)
                return g
        raise KeyError(gid)


def delete_group(gid: str) -> bool:
    """Entfernt eine Gruppe aus der Registry UND aus allen Zuordnungen."""
    with _lock:
        data = _load_unlocked()
        before = len(data["groups"])
        data["groups"] = [g for g in data["groups"] if g["id"] != gid]
        if len(data["groups"]) == before:
            return False
        # Tag aus allen Zuordnungen entfernen, leere Eintraege loeschen.
        new_assign = {}
        for path, gids in data["assignments"].items():
            rest = [x for x in gids if x != gid]
            if rest:
                new_assign[path] = rest
        data["assignments"] = new_assign
        _save_unlocked(data)
        return True


# ─── Zuordnungen (Datei -> Gruppen) ──────────────────────────────────────────

def get_assignment(rel_path) -> list:
    key = _rel(rel_path)
    with _lock:
        data = _load_unlocked()
    return list(data.get("assignments", {}).get(key, []))


def set_assignment(rel_path, group_ids) -> list:
    """Setzt die Gruppenzugehoerigkeit einer Datei (ersetzt bestehende).

    Nur bekannte Gruppen-IDs werden uebernommen; eine leere Liste entfernt den
    Eintrag (= "ungruppiert").
    """
    key = _rel(rel_path)
    with _lock:
        data = _load_unlocked()
        valid = _valid_ids(data)
        clean = [g for g in (group_ids or []) if g in valid]
        # Reihenfolge stabil + dedupliziert
        seen = set()
        clean = [g for g in clean if not (g in seen or seen.add(g))]
        if clean:
            data["assignments"][key] = clean
        else:
            data["assignments"].pop(key, None)
        _save_unlocked(data)
        return clean


def get_assignments_map() -> dict:
    with _lock:
        data = _load_unlocked()
    return dict(data.get("assignments", {}))


def add_folder_to_groups(rel_folder, group_ids) -> int:
    """Traegt einen Speicherordner bei den angegebenen Gruppen ein (dedupliziert).
    Gibt die Anzahl der Gruppen zurueck, bei denen der Ordner NEU eingetragen wurde."""
    rel = _rel(rel_folder)
    wanted = set(group_ids or [])
    if not wanted:
        return 0
    with _lock:
        data = _load_unlocked()
        added = 0
        for g in data.get("groups", []):
            if g["id"] not in wanted:
                continue
            fl = list(g.get("folders", []))
            if rel not in fl:
                fl.append(rel)
                g["folders"] = fl
                added += 1
        if added:
            _save_unlocked(data)
        return added


def set_folder_groups(rel_folder, group_ids) -> dict:
    """Setzt, welche Gruppen einen Ordner als Speicherordner fuehren: bei den
    angegebenen Gruppen wird er eingetragen, bei allen anderen entfernt.
    Rueckgabe: {"added": n, "removed": m}."""
    rel = _rel(rel_folder)
    wanted = set(group_ids or [])
    with _lock:
        data = _load_unlocked()
        added = removed = 0
        for g in data.get("groups", []):
            fl = list(g.get("folders", []))
            has = rel in fl
            if g["id"] in wanted and not has:
                fl.append(rel)
                added += 1
            elif g["id"] not in wanted and has:
                fl = [f for f in fl if f != rel]
                removed += 1
            g["folders"] = fl
        if added or removed:
            _save_unlocked(data)
        return {"added": added, "removed": removed}


def relocate_prefix(old_rel_prefix, new_rel_prefix) -> int:
    """Verschiebt bei einer Ordner-Umbenennung alle Datei-Zuordnungen unterhalb
    des Ordners auf den neuen Pfad UND zieht die Speicherordner-Eintraege der
    Gruppen (``folders``) mit. Gibt die Anzahl verschobener Zuordnungen zurueck."""
    old_dir = _rel(old_rel_prefix).rstrip("/")
    new_dir = _rel(new_rel_prefix).rstrip("/")
    old = old_dir + "/"
    new = new_dir + "/"
    with _lock:
        data = _load_unlocked()
        moved = 0
        new_assign = {}
        for path, gids in data["assignments"].items():
            key = _rel(path)
            if key.startswith(old):
                new_assign[new + key[len(old):]] = gids
                moved += 1
            else:
                new_assign[path] = gids
        # Speicherordner der Gruppen mit umbenennen (exakter Ordner oder Unterpfad)
        folders_changed = 0
        for g in data.get("groups", []):
            fl = g.get("folders")
            if not fl:
                continue
            updated = []
            for f in fl:
                key = _rel(f)
                if key == old_dir or key.startswith(old):
                    updated.append(new_dir + key[len(old_dir):])
                    folders_changed += 1
                else:
                    updated.append(f)
            g["folders"] = updated
        if moved or folders_changed:
            data["assignments"] = new_assign
            _save_unlocked(data)
        return moved


def remove_prefix(rel_prefix) -> int:
    """Entfernt bei einer Ordner-Loeschung alle Datei-Zuordnungen unterhalb des
    Ordners UND die Speicherordner-Eintraege der Gruppen (``folders``).
    Gibt die Anzahl entfernter Zuordnungen zurueck."""
    pref_dir = _rel(rel_prefix).rstrip("/")
    pref = pref_dir + "/"
    with _lock:
        data = _load_unlocked()
        before = len(data["assignments"])
        data["assignments"] = {
            p: g for p, g in data["assignments"].items()
            if not _rel(p).startswith(pref)
        }
        removed = before - len(data["assignments"])
        folders_changed = 0
        for g in data.get("groups", []):
            fl = g.get("folders")
            if not fl:
                continue
            kept = [f for f in fl
                    if not (_rel(f) == pref_dir or _rel(f).startswith(pref))]
            folders_changed += len(fl) - len(kept)
            g["folders"] = kept
        if removed or folders_changed:
            _save_unlocked(data)
        return removed


# ─── Retrieval-Filter ────────────────────────────────────────────────────────

def filter_paths_by_groups(rel_paths, group_ids) -> list:
    """Filtert Pfade nach Gruppenzugehoerigkeit.

    ``group_ids`` kann die virtuelle ID "ungrouped" enthalten (= Dateien ohne
    Tag). Ein Pfad wird behalten, wenn er zu MINDESTENS einer der gewuenschten
    Gruppen gehoert (ODER-Verknuepfung). Leeres/None group_ids -> keine Filterung.
    """
    wanted = set(group_ids or [])
    if not wanted:
        return list(rel_paths)
    with _lock:
        data = _load_unlocked()
    assignments = data.get("assignments", {})
    want_ungrouped = UNGROUPED_ID in wanted
    kept = []
    for p in rel_paths:
        gids = assignments.get(_rel(p), [])
        if gids and wanted.intersection(gids):
            kept.append(p)
        elif not gids and want_ungrouped:
            kept.append(p)
    return kept


# ─── System-Wissen automatisch gruppieren ────────────────────────────────────

def _ensure_group_unlocked(data: dict, name: str, color: str) -> str:
    """Liefert die gid einer Gruppe mit diesem Namen (Slug-Vergleich); legt sie
    an, falls keine existiert. Erwartet, dass ``_lock`` bereits gehalten wird
    und dass der Aufrufer danach ``_save_unlocked`` ausfuehrt."""
    target = _slugify(name)
    for g in data.get("groups", []):
        if g["id"] == target or _slugify(g.get("name", "")) == target:
            return g["id"]
    existing = _valid_ids(data)
    gid = target
    i = 2
    while gid in existing:
        gid = f"{target}-{i}"
        i += 1
    order = max((g.get("order", 0) for g in data.get("groups", [])), default=-1) + 1
    data["groups"].append({"id": gid, "name": (name or gid).strip(),
                           "color": color, "order": order})
    return gid


def auto_assign_system_files(all_rel_paths) -> int:
    """Ordnet alle indizierten, noch NICHT zugeordneten systemgenerierten
    Wissensdateien (unter data/knowledge/learned/) der Gruppe "Erlernt" zu und
    legt diese Gruppe bei Bedarf an. Idempotent – schreibt nur, wenn es etwas
    Neues zuzuordnen gibt. Deckt Bestand (Backfill) und neue Dateien ab.
    Gibt die Anzahl neu zugeordneter Dateien zurueck."""
    learned = [_rel(p) for p in (all_rel_paths or [])
               if _rel(p).startswith(LEARNED_PATH_PREFIX)]
    if not learned:
        return 0
    with _lock:
        data = _load_unlocked()
        assignments = data.setdefault("assignments", {})
        todo = [p for p in learned if not assignments.get(p)]
        if not todo:
            return 0
        gid = _ensure_group_unlocked(data, LEARNED_GROUP_NAME, LEARNED_GROUP_COLOR)
        for p in todo:
            assignments[p] = [gid]
        _save_unlocked(data)
        return len(todo)


# ─── Wartung ─────────────────────────────────────────────────────────────────

def prune(existing_rel_paths) -> int:
    """Entfernt Zuordnungen fuer Dateien, die es nicht mehr gibt.

    Wird nach einem Reindex aufgerufen. Gibt die Anzahl entfernter Eintraege
    zurueck. Die Gruppen-Registry selbst bleibt unberuehrt.
    """
    known = {_rel(p) for p in existing_rel_paths}
    with _lock:
        data = _load_unlocked()
        before = len(data["assignments"])
        data["assignments"] = {
            p: gids for p, gids in data["assignments"].items() if _rel(p) in known
        }
        removed = before - len(data["assignments"])
        if removed:
            _save_unlocked(data)
    return removed
