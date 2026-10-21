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

from backend import atomar as _atomar

PROJECT_ROOT = Path(__file__).parent.parent
MANIFEST_PATH = PROJECT_ROOT / "data" / "knowledge" / ".groups.json"

# Virtuelle Gruppe fuer Dateien ohne Tag – NICHT im Manifest gespeichert.
UNGROUPED_ID = "ungrouped"

# ⚠ HIER STAND BIS 2026-09-13 die System-Gruppe "Erlernt" samt automatischer
# Zuordnung aller Dateien unter data/knowledge/learned/. Sie ist ersatzlos
# entfallen, weil das Erfahrungswissen seither gar nicht mehr in der
# Wissensdatenbank liegt (data/erfahrung/, ausserhalb jedes Wissensordners):
# es gibt dort nichts mehr zuzuordnen. Die Zuordnung stehen zu lassen haette
# eine Funktion ergeben, die auf einen Pfad prueft, den es nicht mehr gibt –
# richtig aussehend, wirkungslos, und bei jeder kuenftigen Durchsicht
# mitzupruefen. Vorhandene Zuordnungen raeumt `prune()` beim naechsten
# Reindex ab; eine angelegte Gruppe "Erlernt" bleibt leer stehen und kann
# von Hand geloescht werden.

# Manifest-Feld: Pfade, die die automatische Zuordnung schon einmal gesehen
# hat (siehe `automatisch_zuordnen`). Liste, kein Dict – es traegt nur die
# Aussage "erledigt", keinen Wert.
AUTO_GESEHEN = "auto_gesehen"

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
    """Manifest lesen – FAIL-CLOSED (Code-Review 2026-10-18).

    Bis dahin lieferte jeder Lesefehler (halb geschriebene Datei nach einem
    Absturz, ``write_text`` war nicht atomar) die VORGABE – und der naechste
    Schreibvorgang machte sie dauerhaft: alle Gruppenzuordnungen weg. Jetzt
    liest ``atomar.lesen`` die Sicherung oder wirft ``atomar.Unlesbar``;
    dann schreibt niemand."""
    data = _atomar.lesen(MANIFEST_PATH, vorgabe=_default_manifest,
                         pruefen=lambda d: isinstance(d, dict))
    data.setdefault("groups", [])
    data.setdefault("assignments", {})
    # Erst-Migration: leeres Manifest -> Startgruppen setzen.
    if not data["groups"] and not data["assignments"]:
        data["groups"] = [dict(g) for g in _SEED_GROUPS]
    return data


def _save_unlocked(data: dict):
    _atomar.schreiben(MANIFEST_PATH, data)


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


def automatisch_zuordnen(pfade) -> int:
    """Neue Dateien in einem Speicherordner bekommen dessen Wissensgruppen.

    ⚠ WARUM ES DAS GIBT (gemeldet 2026-10-21): Dateien, die direkt auf einer
    Freigabe landen (Kundenlisten auf dem SMB-Server), wurden zwar indiziert,
    aber keiner Gruppe zugeordnet – zugeordnet haben bis dahin nur Upload,
    Standort-Sync, Confluence-Abgleich und Informationsextraktor. Der
    Speicherordner einer Gruppe war ein reines Upload-Ziel; dass sein INHALT
    der Gruppe gehoert, stand nirgends. Jede neue Datei musste von Hand
    nachgezogen werden.

    Die Regel, Datei fuer Datei:
      * liegt sie unter keinem Speicherordner -> nichts, auch KEINE Markierung
        (wird der Ordner spaeter verknuepft, ist sie dann noch "neu");
      * steht sie in ``auto_gesehen`` -> nichts. **Das ist der Punkt:** wer eine
        Datei von Hand aus der Gruppe nimmt, bekommt sie beim naechsten Lauf
        NICHT zurueck. Ohne die Markierung waere "ungruppiert" in einem
        Speicherordner kein haltbarer Zustand;
      * hat sie schon eine Zuordnung -> nur markieren. Eine ausdrueckliche
        Wahl (Upload, Confluence, Hand) gewinnt immer;
      * sonst -> alle Gruppen, die einen passenden Speicherordner fuehren
        (Vereinigung, in Gruppen-Reihenfolge), und markieren.

    ⚠ DIE MARKIERUNG LIEGT IM MANIFEST, NICHT IM INDEX. Der naheliegende
    Massstab "nicht im Index = neu" haelt nicht: ein Neuaufbau beginnt mit
    ``vs.clear()``, danach ist JEDE Datei neu – und jede von Hand
    ausgetragene kaeme zurueck.

    ``pfade``: die indizierten Dateien (absolut oder relativ). Rueckgabe: Zahl
    der NEU zugeordneten Dateien.
    """
    with _lock:
        data = _load_unlocked()
        ordner = []                       # (relativer Ordner, Gruppen-ID)
        for g in sorted(data.get("groups", []), key=lambda g: g.get("order", 0)):
            for f in g.get("folders", []):
                rel = _rel(f).rstrip("/")
                if rel:
                    ordner.append((rel, g["id"]))
        if not ordner:
            return 0
        gesehen = set(data.get(AUTO_GESEHEN, []))
        assignments = data["assignments"]
        neu = 0
        markiert = False
        for p in pfade:
            key = _rel(p)
            if key in gesehen:
                continue
            # Mit Schraegstrich: "share_1" ist sonst Praefix von "share_10".
            gids = [gid for rel, gid in ordner if key.startswith(rel + "/")]
            if not gids:
                continue
            gesehen.add(key)
            markiert = True
            if not assignments.get(key):
                assignments[key] = list(dict.fromkeys(gids))
                neu += 1
        if markiert:
            data[AUTO_GESEHEN] = sorted(gesehen)
            _save_unlocked(data)
        return neu


def gesehen_verschieben(alt, neu=None) -> None:
    """Markierung einer umbenannten/verschobenen Datei mitziehen – sonst gilt
    sie am neuen Ort als neu und bekaeme eine ausgetragene Gruppe zurueck.
    ``neu=None``: die Datei ist geloescht, die Markierung faellt weg (eine
    spaeter gleichnamig abgelegte Datei ist eine NEUE Datei)."""
    a = _rel(alt)
    with _lock:
        data = _load_unlocked()
        gesehen = data.get(AUTO_GESEHEN, [])
        if a not in gesehen:
            return
        rest = {x for x in gesehen if x != a}
        if neu is not None:
            rest.add(_rel(neu))
        data[AUTO_GESEHEN] = sorted(rest)
        _save_unlocked(data)


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
        # Markierung der automatischen Zuordnung mitziehen – sonst gilt jede
        # verschobene Datei am neuen Ort als neu.
        gesehen = data.get(AUTO_GESEHEN, [])
        neu_gesehen = sorted({new + _rel(x)[len(old):] if _rel(x).startswith(old) else x
                              for x in gesehen})
        gesehen_changed = neu_gesehen != sorted(gesehen)
        if moved or folders_changed or gesehen_changed:
            data["assignments"] = new_assign
            if gesehen_changed:
                data[AUTO_GESEHEN] = neu_gesehen
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
        gesehen = data.get(AUTO_GESEHEN, [])
        kept_gesehen = [x for x in gesehen if not _rel(x).startswith(pref)]
        if len(kept_gesehen) != len(gesehen):
            data[AUTO_GESEHEN] = kept_gesehen
            folders_changed += 1
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
        # Markierungen verschwundener Dateien ebenfalls abraeumen: kommt eine
        # gleichnamige Datei spaeter wieder, ist sie eine NEUE Datei.
        gesehen = data.get(AUTO_GESEHEN, [])
        kept_gesehen = [x for x in gesehen if _rel(x) in known]
        gesehen_weg = len(gesehen) - len(kept_gesehen)
        if gesehen_weg:
            data[AUTO_GESEHEN] = kept_gesehen
        if removed or gesehen_weg:
            _save_unlocked(data)
    return removed
