"""Schema-Graph: Einstellungen des SQL-Assistenten – Normierung und Pruefung.

Die EINE Stelle, an der aus einem Rumpf (Einstellungs-Reiter) oder aus dem
gespeicherten Skill-Zustand eine gueltige Konfiguration wird. Reine Funktionen,
kein Import von ``backend.config`` – der Aufrufer reicht den Zustand herein
(testbar ohne Attrappe der Live-``settings.json``).

Aufbau::

    {"schemata": [{"id", "name", "dialekt", "dateimuster", "fk_ableiten",
                   "max_tabellen", "max_spalten"}],
     "prozesse", "index_aus_chat"}

**Was eine Datenbank beschreibt, steht AM SCHEMA** (Vorgabe des Betreibers
2026-11-10): Dialekt, Dateimuster, Ableiten von Beziehungen und die
Hoechstzahlen je Frage – zwei Schemata sind zwei Datenbanken und koennen sich
in jedem dieser Punkte unterscheiden. Fuer alle gemeinsam bleiben nur
``prozesse`` (eine Eigenschaft des Servers) und ``index_aus_chat`` (eine
Erlaubnis). Auch die Erfassung laeuft je Schema (``schema_graph_index``,
``nur``).

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
SCHEMA_VORGABEN = {
    "dialekt": "allgemein", "dateimuster": "*.sql,*.ddl,*.yaml,*.yml", "fk_ableiten": True,
    "max_tabellen": 12, "max_spalten": 40,
}
VORGABEN = {"schemata": [], "prozesse": 0, "index_aus_chat": False}
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


def endungen(schema: dict) -> set[str]:
    """``*.sql,*.ddl`` -> ``{".sql", ".ddl"}`` (fuer Upload und ZIP) – aus dem
    Dateimuster EINES Schemas."""
    return {"." + m.split(".", 1)[1] for m in str(schema.get("dateimuster") or "").split(",")
            if _MUSTER_RE.fullmatch(m.strip())}


# Begleitdokumente (Konventionen, SQL-Beispiele): unabhaengig vom Dateimuster
# immer angenommen und erfasst – gleiche Liste wie ``schema_graph_parser.
# DOK_ENDUNGEN`` (Gleichheit prueft der Waechter; das Modul hier importiert den
# Parser bewusst nicht).
DOK_ENDUNGEN = (".md", ".docx", ".pdf")


def upload_endungen(schema: dict) -> set[str]:
    """Was der Upload in dieses Schema annimmt: Dateimuster plus Begleitdokumente."""
    return endungen(schema) | set(DOK_ENDUNGEN)


def erfassungs_muster(schema: dict) -> str:
    """Muster fuer den Indexlauf dieses Schemas: Dateimuster plus Begleitdokumente."""
    teile = [m for m in str(schema.get("dateimuster") or "").split(",") if m.strip()]
    for e in DOK_ENDUNGEN:
        if "*" + e not in teile:
            teile.append("*" + e)
    return ",".join(teile)


def schema_von(cfg: dict, sid: str) -> dict | None:
    """Das Schema mit dieser Kennung – oder None."""
    for s in cfg.get("schemata") or []:
        if s.get("id") == sid:
            return s
    return None


def quellen(cfg: dict) -> list[dict]:
    """Schemata als Quellen des Indexlaufs: je Schema der FESTE Ordner, SEIN
    Muster und SEINE Entscheidung ueber das Ableiten aus Spaltennamen. Die eine
    Stelle dafuer – Dienst und Kommandozeile bauen sie nicht je selbst."""
    return [{"id": s["id"], "ordner": [str(ordner_fuer(s["id"]))],
             "muster": erfassungs_muster(s), "fk_ableiten": s["fk_ableiten"]}
            for s in cfg.get("schemata") or []]


def fuer_frage(cfg: dict, ids) -> dict:
    """Vorgaben einer Frage ueber die GEWAEHLTEN Schemata.

    ``dialekt``: der des ersten gewaehlten Schemas (Reihenfolge der
    Einstellungen) – eine Abfrage hat genau einen Dialekt, und der Benutzer kann
    ihn je Frage aendern. ``max_tabellen``/``max_spalten``: der GROESSTE Wert
    der gewaehlten Schemata – wer zwei Schemata zusammen fragt, bekommt nicht
    weniger Ausschnitt als fuer das groessere allein. Ohne (bekannte) Auswahl
    die Vorgaben.
    """
    ids = set(ids or ())
    gewaehlt = [s for s in cfg.get("schemata") or [] if s.get("id") in ids]
    if not gewaehlt:
        return {k: SCHEMA_VORGABEN[k] for k in ("dialekt", "max_tabellen", "max_spalten")}
    return {"dialekt": gewaehlt[0]["dialekt"],
            "max_tabellen": max(s["max_tabellen"] for s in gewaehlt),
            "max_spalten": max(s["max_spalten"] for s in gewaehlt)}


def _zahl(wert, schluessel: str, fehler: list, vor: str = "") -> int:
    """``vor``: Vorsatz fuer die Fehlermeldung (bei Schema-Feldern der Name des
    Schemas – sonst weiss niemand, WELCHES Schema gemeint ist)."""
    lo, hi = GRENZEN[schluessel]
    vorgabe = SCHEMA_VORGABEN[schluessel] if schluessel in SCHEMA_VORGABEN else VORGABEN[schluessel]
    if isinstance(wert, bool) or not isinstance(wert, (int, float, str)):
        fehler.append(f"{vor}{schluessel}: keine Zahl")
        return vorgabe
    try:
        n = int(wert)
    except (TypeError, ValueError):
        fehler.append(f"{vor}{schluessel}: keine Zahl")
        return vorgabe
    if not lo <= n <= hi:
        fehler.append(f"{vor}{schluessel}: erlaubt {lo} bis {hi}, angegeben {n}")
        return vorgabe
    return n


def _schema_felder(s: dict, name: str, fehler: list) -> dict:
    """Die Einstellungen EINES Schemas pruefen; fehlende Felder bekommen die
    Vorgabe (ein neu angelegtes Schema traegt noch keine)."""
    vor = f"Schema „{name}“ – "
    out = {}
    d = str(s.get("dialekt", SCHEMA_VORGABEN["dialekt"]) or "").strip().lower()
    if d not in DIALEKTE:
        fehler.append(f"{vor}dialekt: unbekannt ({d})")
        d = SCHEMA_VORGABEN["dialekt"]
    out["dialekt"] = d
    m = s.get("dateimuster", SCHEMA_VORGABEN["dateimuster"])
    teile = [t.strip().lower() for t in str(m or "").split(",") if t.strip()]
    if not teile or any(not _MUSTER_RE.fullmatch(t) for t in teile):
        fehler.append(f"{vor}dateimuster: kommagetrennte Endungen wie *.sql,*.ddl")
        teile = SCHEMA_VORGABEN["dateimuster"].split(",")
    out["dateimuster"] = ",".join(dict.fromkeys(teile))
    w = s.get("fk_ableiten", SCHEMA_VORGABEN["fk_ableiten"])
    if not isinstance(w, bool):
        fehler.append(f"{vor}fk_ableiten: erwartet wird ja/nein")
        w = SCHEMA_VORGABEN["fk_ableiten"]
    out["fk_ableiten"] = w
    for k in ("max_tabellen", "max_spalten"):
        out[k] = _zahl(s.get(k, SCHEMA_VORGABEN[k]), k, fehler, vor)
    return out


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

    ⚠ Ein Schema-Feld auf OBERSTER Ebene (Aufbau bis 2026-11-10) ist ein
    FEHLER, kein stiller Rest: ein noch offener Reiter mit dem alten Skript
    schickt genau das, und stilles Uebergehen setzte jedes Schema auf die
    Vorgaben zurueck. Die Altfassung im GESPEICHERTEN Zustand uebersetzt
    ``aus_zustand``.
    """
    fehler: list[str] = []
    hinweise: list[str] = []
    if not isinstance(roh, dict):
        return dict(VORGABEN), ["Erwartet wird ein Objekt."], []
    cfg = dict(VORGABEN)
    veraltet = [k for k in SCHEMA_VORGABEN if k in roh]
    if veraltet:
        fehler.append(f"{', '.join(veraltet)}: wird jetzt je Schema eingestellt – bitte die Seite "
                      "neu laden und erneut speichern")
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
        schemata.append({"id": sid, "name": name, **_schema_felder(s, name, fehler)})
    cfg["schemata"] = schemata
    cfg["prozesse"] = _zahl(roh.get("prozesse", VORGABEN["prozesse"]), "prozesse", fehler)
    w = roh.get("index_aus_chat", VORGABEN["index_aus_chat"])
    if not isinstance(w, bool):
        fehler.append("index_aus_chat: erwartet wird ja/nein")
        w = VORGABEN["index_aus_chat"]
    cfg["index_aus_chat"] = w
    return cfg, fehler, hinweise


def aus_zustand(skill_cfg: dict | None) -> dict:
    """Gespeicherten Skill-Zustand lesen – immer eine vollstaendige Konfiguration.

    Altfassung (``quellen`` mit freien Ordnern und Wissensgruppen, bis
    2026-11-07) wird zu Schemata gleicher Kennung und gleichen Namens; Ordner und
    Gruppen fallen weg – deren Dateien lagen woanders und muessen hochgeladen
    werden (der Reiter zeigt das Schema dann als leer).

    Altfassung bis 2026-11-10 (Dialekt, Dateimuster, Ableiten und Hoechstzahlen
    EINMAL fuer alle): der bisherige Wert geht in JEDES Schema, das das Feld
    noch nicht selbst traegt – nach dem Update verhaelt sich damit jedes Schema
    wie vorher, bis jemand es einzeln aendert. Festgeschrieben wird das beim
    naechsten Speichern.
    """
    roh = dict(skill_cfg or {})
    if not roh.get("schemata") and isinstance(roh.get("quellen"), list):
        roh["schemata"] = [{"id": q.get("id"), "name": q.get("name")}
                           for q in roh["quellen"] if isinstance(q, dict)]
    alt = {k: roh.pop(k) for k in SCHEMA_VORGABEN if k in roh}
    if alt and isinstance(roh.get("schemata"), list):
        roh["schemata"] = [{**alt, **s} if isinstance(s, dict) else s for s in roh["schemata"]]
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
