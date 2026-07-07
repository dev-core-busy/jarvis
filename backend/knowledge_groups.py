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
    } for g in groups]

    ungrouped_count = None
    if known is not None:
        assigned = {
            _rel(p) for p, gids in assignments.items()
            if gids and _rel(p) in known
        }
        ungrouped_count = len(known - assigned)

    return {"groups": out_groups, "ungrouped_count": ungrouped_count}


def _valid_ids(data: dict) -> set:
    return {g["id"] for g in data.get("groups", [])}


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


def update_group(gid: str, name=None, color=None, order=None) -> dict:
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
