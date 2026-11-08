"""Schema-Graph: Einstellungen des SQL-Assistenten – Normierung und Pruefung.

Die EINE Stelle, an der aus einem Rumpf (Einstellungs-Reiter) oder aus dem
gespeicherten Skill-Zustand eine gueltige Konfiguration wird. Reine Funktionen,
kein Import von ``backend.config`` – der Aufrufer reicht den Zustand herein
(testbar ohne Attrappe der Live-``settings.json``).

Aufbau::

    {"schemata": [{"id", "name"}],
     "dialekt", "dateimuster", "prozesse", "fk_ableiten",
     "max_tabellen", "max_spalten", "index_aus_chat"}

**Ein Schema ist ein fester Ordner** ``data/sql_schema_graph/<id>/`` (Vorgabe
des Betreibers 2026-11-07: keine freie Ordnerwahl, Dateien kommen per Upload
im Reiter). Der Graph selbst liegt in ``data/sql_schema_graph/_graph/`` – der
Unterstrich kann in keiner Schema-Kennung vorkommen (``[a-z0-9-]``), die beiden
koennen sich also nicht ueberschneiden.

**Keine Wissensgruppen mehr** (dieselbe Vorgabe): wer fuer den SQL-Assistenten
freigegeben ist, darf jedes Schema WAEHLEN; was eine Frage sieht, entscheidet
die Auswahl (im Chat neben den Wissensgruppen, auf /sql oben) – nicht eine
Gruppenzugehoerigkeit.
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASIS = PROJECT_ROOT / "data" / "sql_schema_graph"
GRAPH_UNTERORDNER = "_graph"

DIALEKTE = ("allgemein", "postgresql", "mysql", "mariadb", "oracle", "mssql", "sqlite",
            "db2", "hana", "snowflake", "bigquery", "teradata")

# Nur ``*.endung``: daraus entsteht zugleich die Endungsliste fuer den Upload
# (ZIP-Entpacker und Einzeldateien) – ein freies Glob-Muster liesse sich dort
# nicht abbilden, und zwei Regeln fuer "welche Datei gehoert dazu" liefen
# auseinander.
VORGABEN = {
    "schemata": [], "dialekt": "allgemein", "dateimuster": "*.sql,*.ddl,*.yaml,*.yml", "prozesse": 0,
    "fk_ableiten": True, "max_tabellen": 12, "max_spalten": 40, "index_aus_chat": False,
}
GRENZEN = {"prozesse": (0, 32), "max_tabellen": (3, 40), "max_spalten": (10, 200)}
MAX_SCHEMATA = 100
NAME_MAX = 80
_KENNUNG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_MUSTER_RE = re.compile(r"\*\.[a-z0-9]{1,10}")


def ordner_fuer(sid: str) -> Path:
    """Ablageordner eines Schemas. Wirft bei einer ungueltigen Kennung – die
    Kennung wird zu einem Pfadteil, ein ``..`` darin waere ein Weg hinaus."""
    if not isinstance(sid, str) or not _KENNUNG_RE.fullmatch(sid):
        raise ValueError(f"ungueltige Schema-Kennung: {sid!r}")
    return BASIS / sid


def graph_ordner() -> Path:
    return BASIS / GRAPH_UNTERORDNER


def endungen(cfg: dict) -> set[str]:
    """``*.sql,*.ddl`` -> ``{".sql", ".ddl"}`` (fuer Upload und ZIP)."""
    return {"." + m.split(".", 1)[1] for m in str(cfg.get("dateimuster") or "").split(",")
            if _MUSTER_RE.fullmatch(m.strip())}


# Begleitdokumente (Konventionen, SQL-Beispiele): unabhaengig vom Dateimuster
# immer angenommen und erfasst – gleiche Liste wie ``schema_graph_parser.
# DOK_ENDUNGEN`` (Gleichheit prueft der Waechter; das Modul hier importiert den
# Parser bewusst nicht).
DOK_ENDUNGEN = (".md", ".docx", ".pdf")


def upload_endungen(cfg: dict) -> set[str]:
    """Was der Upload annimmt: Dateimuster plus Begleitdokumente."""
    return endungen(cfg) | set(DOK_ENDUNGEN)


def erfassungs_muster(cfg: dict) -> str:
    """Muster fuer den Indexlauf: Dateimuster plus Begleitdokumente."""
    teile = [m for m in str(cfg.get("dateimuster") or "").split(",") if m.strip()]
    for e in DOK_ENDUNGEN:
        if "*" + e not in teile:
            teile.append("*" + e)
    return ",".join(teile)


def _zahl(wert, schluessel: str, fehler: list) -> int:
    lo, hi = GRENZEN[schluessel]
    if isinstance(wert, bool) or not isinstance(wert, (int, float, str)):
        fehler.append(f"{schluessel}: keine Zahl")
        return VORGABEN[schluessel]
    try:
        n = int(wert)
    except (TypeError, ValueError):
        fehler.append(f"{schluessel}: keine Zahl")
        return VORGABEN[schluessel]
    if not lo <= n <= hi:
        fehler.append(f"{schluessel}: erlaubt {lo} bis {hi}, angegeben {n}")
        return VORGABEN[schluessel]
    return n


def _kennung(name: str, vergeben: set) -> str:
    s = name.lower()
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "schema"
    k, i = s, 2
    while k in vergeben:
        k, i = f"{s}-{i}", i + 1
    return k


def normieren(roh: dict) -> tuple[dict, list, list]:
    """Rumpf -> (Konfiguration, Fehler, Hinweise). Bei Fehlern NICHT speichern.

    Eine vorhandene Kennung bleibt erhalten (sie ist der Ordnername – eine
    Umbenennung aendert nur den Anzeigenamen, die Dateien bleiben, wo sie
    sind). Neue Schemata bekommen eine Kennung aus dem Namen.
    """
    fehler: list[str] = []
    hinweise: list[str] = []
    if not isinstance(roh, dict):
        return dict(VORGABEN), ["Erwartet wird ein Objekt."], []
    cfg = dict(VORGABEN)
    liste = roh.get("schemata", [])
    if not isinstance(liste, list):
        fehler.append("schemata: erwartet wird eine Liste")
        liste = []
    if len(liste) > MAX_SCHEMATA:
        fehler.append(f"höchstens {MAX_SCHEMATA} Schemata")
        liste = liste[:MAX_SCHEMATA]
    vergeben: set[str] = set()
    namen: set[str] = set()
    schemata = []
    for i, s in enumerate(liste, 1):
        if not isinstance(s, dict):
            fehler.append(f"Schema {i}: kein Objekt")
            continue
        name = str(s.get("name") or "").strip()
        if not name:
            fehler.append(f"Schema {i}: Name fehlt")
            continue
        if len(name) > NAME_MAX:
            fehler.append(f"Schema „{name[:30]}…“: Name länger als {NAME_MAX} Zeichen")
            continue
        if name.lower() in namen:
            fehler.append(f"Schema „{name}“ ist doppelt")
            continue
        namen.add(name.lower())
        sid = str(s.get("id") or "").strip()
        if sid and (not _KENNUNG_RE.fullmatch(sid) or sid in vergeben):
            fehler.append(f"Schema „{name}“: ungültige oder doppelte Kennung {sid!r}")
            continue
        if not sid:
            sid = _kennung(name, vergeben)
        vergeben.add(sid)
        schemata.append({"id": sid, "name": name})
    cfg["schemata"] = schemata
    d = str(roh.get("dialekt", VORGABEN["dialekt"]) or "").strip().lower()
    if d not in DIALEKTE:
        fehler.append(f"dialekt: unbekannt ({d})")
        d = VORGABEN["dialekt"]
    cfg["dialekt"] = d
    m = roh.get("dateimuster", VORGABEN["dateimuster"])
    teile = [t.strip().lower() for t in str(m or "").split(",") if t.strip()]
    if not teile or any(not _MUSTER_RE.fullmatch(t) for t in teile):
        fehler.append("dateimuster: kommagetrennte Endungen wie *.sql,*.ddl")
        teile = VORGABEN["dateimuster"].split(",")
    cfg["dateimuster"] = ",".join(dict.fromkeys(teile))
    for k in ("prozesse", "max_tabellen", "max_spalten"):
        cfg[k] = _zahl(roh.get(k, VORGABEN[k]), k, fehler)
    for k in ("fk_ableiten", "index_aus_chat"):
        w = roh.get(k, VORGABEN[k])
        if not isinstance(w, bool):
            fehler.append(f"{k}: erwartet wird ja/nein")
            w = VORGABEN[k]
        cfg[k] = w
    return cfg, fehler, hinweise


def aus_zustand(skill_cfg: dict | None) -> dict:
    """Gespeicherten Skill-Zustand lesen – immer eine vollstaendige Konfiguration.

    Altfassung (``quellen`` mit freien Ordnern und Wissensgruppen, bis
    2026-11-07) wird zu Schemata gleicher Kennung und gleichen Namens; Ordner und
    Gruppen fallen weg – deren Dateien lagen woanders und muessen hochgeladen
    werden (der Reiter zeigt das Schema dann als leer).
    """
    roh = dict(skill_cfg or {})
    if not roh.get("schemata") and isinstance(roh.get("quellen"), list):
        roh["schemata"] = [{"id": q.get("id"), "name": q.get("name")}
                           for q in roh["quellen"] if isinstance(q, dict)]
    cfg, _fehler, _hinweise = normieren(roh)
    return cfg


def auswahl(cfg: dict, roh) -> set[str]:
    """Auswahl eines Benutzers -> Kennungen, die es WIRKLICH gibt.

    ``roh``: Liste oder kommagetrennte Zeichenkette. Unbekanntes faellt still
    weg (ein geloeschtes Schema in einer gemerkten Auswahl ist kein Fehler),
    Nicht-Zeichenketten ebenso.
    """
    if isinstance(roh, str):
        roh = roh.split(",")
    if not isinstance(roh, list):
        return set()
    bekannt = {s["id"] for s in cfg.get("schemata") or []}
    return {x.strip() for x in roh if isinstance(x, str) and x.strip() in bekannt}
