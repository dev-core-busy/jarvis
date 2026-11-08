"""Schema-Graph: Ablage (SQLite) und Ableitung des Graphen aus den Rohfakten.

⚠ SQLITE UND NICHT JSON wie ``backend/wissensgraph.py``: dort liegen einige
tausend Entitaeten, hier – bei einem Schema-Bestand von zweistelligen GB –
Hunderttausende Tabellen mit Millionen Spalten. Ein ``graph.json`` dieser
Groesse liesse sich weder im Dienst halten noch je Werkzeugaufruf laden.
SQLite ist Teil der Standardbibliothek (kein neues Paket) und bringt mit FTS5
eine BM25-Volltextsuche mit.

Zwei Dateien unter ``data/sql_schema_graph/_graph/``::

    roh.sqlite    – je Quelldatei ihre Rohfakten (inkrementell gepflegt;
                    eine geaenderte Datei ersetzt nur ihre eigenen Zeilen)
    graph.sqlite  – der abgeleitete Graph (Objekte, Spalten, Kanten, Bereiche,
                    Volltextindex). Wird VOLLSTAENDIG in ``graph.neu.sqlite``
                    gebaut und per ``os.replace`` getauscht: ein Leser sieht
                    nie einen halben Graphen, und ein Abbruch beim Ableiten
                    laesst den alten stehen.

Warum zwei Stufen: eine Tabelle wird oft in einer Datei angelegt, in einer
zweiten per ALTER TABLE verknuepft und in einer dritten kommentiert. Erst
die Gesamtheit ergibt den Graphen – die Ableitung laeuft deshalb ueber ALLE
Rohfakten, das Zerlegen (teuer) nur ueber geaenderte Dateien.

Kantenarten: ``fk`` (deklarierter Fremdschluessel, Kind -> Eltern),
``sicht`` (Sicht -> benutzte Tabelle), ``abgeleitet`` (aus Spaltennamen
erschlossen, z. B. ``kunde_id`` -> ``kunde.id``; nur wo KEIN deklarierter
Fremdschluessel auf der Spalte liegt, und als schwaecher gekennzeichnet).

Bereiche sind Gemeinschaften im Graphen (Label Propagation) – die
"Communities" des GraphRAG-Ansatzes. Sie werden NICHT per Modell
zusammengefasst (bei dieser Groesse waeren das zehntausende Aufrufe), sondern
nach den haeufigsten Namensbestandteilen ihrer Mitglieder benannt.
"""
from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Seit 2026-11-07 unter dem festen Ablageordner des SQL-Assistenten (die Schema-
# Dateien liegen daneben in data/sql_schema_graph/<schema>/). Bis dahin
# data/schema_graph – ein dort liegender Altbestand wird nicht mehr gelesen.
ORDNER = PROJECT_ROOT / "data" / "sql_schema_graph" / "_graph"

# Obergrenze der Spalten, die in das Volltext-Dokument EINER Tabelle gehen.
# SAP-artige Tabellen haben mehrere hundert; alle aufzunehmen, liesse breite
# Tabellen jede Suche gewinnen (BM25 normiert die Laenge nur teilweise).
FTS_MAX_SPALTEN = 300


def ordner() -> Path:
    """Ablageordner – als Funktion, damit ein Test ``ORDNER`` umlenken kann."""
    return ORDNER


def roh_pfad() -> Path:
    return ordner() / "roh.sqlite"


def graph_pfad() -> Path:
    return ordner() / "graph.sqlite"


# ─── Namen ──────────────────────────────────────────────────────────────────

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_TRENN = re.compile(r"[^0-9A-Za-zÀ-￿]+")


def schluessel(name: str) -> str:
    return (name or "").strip().lower()


def letzter_teil(name: str) -> str:
    return schluessel(name).rsplit(".", 1)[-1]


def namens_woerter(name: str) -> list[str]:
    """``KundeAuftrag_pos`` -> [kundeauftrag_pos, kunde, auftrag, pos].

    Die Gesamtform bleibt mit drin, damit eine exakte Suche nach dem Bezeichner
    trifft; die Teile, damit "auftrag" ihn ebenfalls findet. Ein Stueck ohne
    Gross-/Kleinwechsel kann keine CamelCase-Grenze haben – dann entfaellt der
    teure Split (Vorfilter, siehe Register).
    """
    out = []
    for stueck in _TRENN.split(name or ""):
        if not stueck:
            continue
        out.append(stueck.lower())
        teile = _CAMEL.split(stueck) if (not stueck.islower() and not stueck.isupper()) else [stueck]
        for t in teile:
            for u in re.split(r"(?<=\D)(?=\d)|(?<=\d)(?=\D)", t):
                if len(u) >= 2 and u.lower() != stueck.lower():
                    out.append(u.lower())
    return out


# ─── Rohfakten ──────────────────────────────────────────────────────────────

def ordner_anlegen(p: Path) -> None:
    """Ablage 0750: die Struktur einer Unternehmensdatenbank (Tabellen,
    Kommentare, Beziehungen) ist selbst schuetzenswert – nicht weltlesbar."""
    p.mkdir(mode=0o750, parents=True, exist_ok=True)
    try:
        os.chmod(p, 0o750)
    except PermissionError:
        pass   # fremder Eigentuemer: nicht unsere Entscheidung, kein Abbruch


def _datei_schuetzen(p: Path) -> None:
    for q in (p, Path(str(p) + "-wal"), Path(str(p) + "-shm")):
        try:
            if q.exists():
                os.chmod(q, 0o640)
        except PermissionError:
            pass


def roh_oeffnen(pfad: Path | None = None) -> sqlite3.Connection:
    p = pfad or roh_pfad()
    ordner_anlegen(p.parent)
    con = sqlite3.connect(str(p), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS dateien(
            pfad TEXT PRIMARY KEY, groesse INTEGER, mtime_ns INTEGER,
            stand TEXT, fehler TEXT, fakten INTEGER, stat TEXT,
            versuche INTEGER DEFAULT 0, zeit REAL);
        CREATE TABLE IF NOT EXISTS roh(
            datei TEXT, nr INTEGER, fakt TEXT);
        CREATE INDEX IF NOT EXISTS roh_datei ON roh(datei);
        CREATE TABLE IF NOT EXISTS roh_meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    _datei_schuetzen(p)
    return con


def roh_fassung(con: sqlite3.Connection) -> int | None:
    """Parser-Fassung, mit der die Rohfakten entstanden sind (None = unbekannt,
    also vor Einfuehrung der Marke)."""
    r = con.execute("SELECT v FROM roh_meta WHERE k='parser_fassung'").fetchone()
    try:
        return int(r[0]) if r else None
    except (TypeError, ValueError):
        return None


def roh_fassung_setzen(con: sqlite3.Connection, fassung: int) -> None:
    con.execute("INSERT INTO roh_meta(k, v) VALUES ('parser_fassung', ?) "
                "ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(int(fassung)),))


def roh_ersetzen(con: sqlite3.Connection, ergebnis: dict, groesse: int, mtime_ns: int) -> None:
    """Rohfakten EINER Datei ersetzen (im Rahmen der laufenden Transaktion)."""
    pfad = ergebnis["pfad"]
    con.execute("DELETE FROM roh WHERE datei=?", (pfad,))
    con.executemany("INSERT INTO roh(datei, nr, fakt) VALUES (?,?,?)",
                    ((pfad, i, json.dumps(f, ensure_ascii=False))
                     for i, f in enumerate(ergebnis.get("fakten") or [])))
    con.execute(
        "INSERT INTO dateien(pfad, groesse, mtime_ns, stand, fehler, fakten, stat, versuche, zeit) "
        "VALUES (?,?,?,?,?,?,?,0,?) ON CONFLICT(pfad) DO UPDATE SET groesse=excluded.groesse, "
        "mtime_ns=excluded.mtime_ns, stand=excluded.stand, fehler=excluded.fehler, "
        "fakten=excluded.fakten, stat=excluded.stat, versuche=0, zeit=excluded.zeit",
        (pfad, groesse, mtime_ns, "ok" if ergebnis.get("ok") else "fehler",
         ergebnis.get("fehler") or "", len(ergebnis.get("fakten") or []),
         json.dumps(ergebnis.get("stat") or {}), time.time()))


def roh_entfernen(con: sqlite3.Connection, pfad: str) -> None:
    con.execute("DELETE FROM roh WHERE datei=?", (pfad,))
    con.execute("DELETE FROM dateien WHERE pfad=?", (pfad,))


# ─── Ableitung ──────────────────────────────────────────────────────────────

_GRAPH_SCHEMA = """
    CREATE TABLE objekt(
        id INTEGER PRIMARY KEY, schluessel TEXT UNIQUE, schema TEXT, name TEXT,
        name_l TEXT, art TEXT, kommentar TEXT, datei TEXT, spalten_n INTEGER,
        pk TEXT, bereich INTEGER, quelle TEXT);
    CREATE TABLE spalte(
        objekt_id INTEGER, pos INTEGER, name TEXT, name_l TEXT, typ TEXT,
        pk INTEGER, nullable INTEGER, kommentar TEXT);
    CREATE TABLE kante(
        von INTEGER, nach INTEGER, art TEXT, von_spalten TEXT, nach_spalten TEXT);
    CREATE TABLE herkunft(
        sicht_id INTEGER, spalte_l TEXT, basis_id INTEGER, basis_spalte_l TEXT);
    CREATE TABLE dokument(
        id INTEGER PRIMARY KEY, quelle TEXT, datei TEXT, titel TEXT, nr INTEGER, text TEXT);
    CREATE TABLE bereich(id INTEGER PRIMARY KEY, name TEXT, groesse INTEGER);
    CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
"""
_GRAPH_INDEX = """
    CREATE INDEX objekt_name ON objekt(name_l);
    CREATE INDEX spalte_obj ON spalte(objekt_id);
    CREATE INDEX spalte_name ON spalte(name_l);
    CREATE INDEX kante_von ON kante(von);
    CREATE INDEX herkunft_sicht ON herkunft(sicht_id, spalte_l);
    CREATE INDEX kante_nach ON kante(nach);
    CREATE INDEX objekt_bereich ON objekt(bereich);
    CREATE INDEX objekt_quelle ON objekt(quelle);
"""


class _Aufloeser:
    """Bezeichner aus Fremdschluesseln/Kommentaren -> Objekt-ID.

    Reihenfolge: exakter Schluessel; dann gleicher Name im Schema des
    VERWEISENDEN Objekts; dann ein im ganzen Bestand EINDEUTIGER Name.
    Mehrdeutiges wird nicht geraten, sondern gezaehlt.
    """

    def __init__(self):
        self.genau: dict[str, int] = {}
        self.nach_name: dict[str, list[int]] = defaultdict(list)
        self.schema_von: dict[int, str] = {}
        self.mehrdeutig = 0
        self.unbekannt = 0

    def dazu(self, oid: int, schl: str, schema: str) -> None:
        self.genau[schl] = oid
        self.nach_name[letzter_teil(schl)].append(oid)
        self.schema_von[oid] = schema

    def finde(self, ziel: str, schema_hinweis: str = "") -> int | None:
        s = schluessel(ziel)
        if s in self.genau:
            return self.genau[s]
        name = letzter_teil(s)
        kand = self.nach_name.get(name) or []
        if not kand:
            # db.schema.tabelle gegen schema.tabelle (oder umgekehrt)
            for k in (s.split(".", 1)[-1],):
                if k in self.genau:
                    return self.genau[k]
            self.unbekannt += 1
            return None
        if len(kand) == 1:
            return kand[0]
        if schema_hinweis:
            gleich = [o for o in kand if self.schema_von.get(o) == schema_hinweis]
            if len(gleich) == 1:
                return gleich[0]
        self.mehrdeutig += 1
        return None


def _herkunft_aufloesen(oid: int, hk: dict, aufgeloest: dict, z: Counter) -> list[tuple]:
    """Herkunft der Sichtspalten (Parser: Tabellenname wie geschrieben) ->
    Zeilen ``(sicht_id, spalte_l, basis_id, basis_spalte_l)``; ``*`` = jede
    Spalte gleichen Namens.

    Jede Herkunftstabelle steht in ``nutzt`` (der Parser nimmt die FROM-Liste
    dorthin mit) und ist damit schon aufgeloest – ein zweites Nachschlagen
    zaehlte denselben Verweis doppelt als "mehrdeutig"/"unbekannt".
    """
    def ziel(t: str) -> int | None:
        return aufgeloest.get(schluessel(t))

    zeilen = []
    if not isinstance(hk, dict):
        return zeilen
    for name, paar in (hk.get("spalten") or {}).items():
        if not (isinstance(paar, list) and len(paar) == 2 and all(isinstance(x, str) for x in paar)):
            continue
        zid = ziel(paar[0])
        if zid is not None and zid != oid:
            zeilen.append((oid, str(name).lower(), zid, paar[1].lower()))
            z["herkunft_spalten"] += 1
    for t in hk.get("stern") or []:
        zid = ziel(t) if isinstance(t, str) else None
        if zid is not None and zid != oid:
            zeilen.append((oid, "*", zid, "*"))
            z["herkunft_stern"] += 1
    return zeilen


def _schema_und_name(schl_original: str) -> tuple[str, str]:
    teile = schl_original.split(".")
    if len(teile) == 1:
        return "", teile[0]
    return ".".join(teile[:-1]), teile[-1]


def ableiten(roh_con: sqlite3.Connection, ziel: Path | None = None,
             fk_ableiten: bool = True, melde=None, abbruch=None,
             quelle_von=None) -> dict:
    """Baut ``graph.sqlite`` aus allen Rohfakten neu (in eine Nebendatei, dann
    atomarer Tausch). Rueckgabe: Zaehler des Laufs.

    ``melde(text)`` bekommt Fortschrittszeilen, ``abbruch()`` -> True bricht ab
    (der alte Graph bleibt dann unveraendert stehen).

    ``quelle_von(datei) -> str`` ordnet jede Datei einer SCHEMA-QUELLE zu; an
    der Quelle (= dem Schema) haengt die Sichtbarkeit (Auswahl, ``schema_graph_rag``).
    Eine Datei ohne Quelle bekommt ``""`` – und ist damit fuer niemanden
    sichtbar (fail-closed), nur fuer Aufrufer ohne Filter (Tests, Kommandozeile).
    """
    quelle_von = quelle_von or (lambda _d: "")
    melde = melde or (lambda _t: None)
    abbruch = abbruch or (lambda: False)
    ziel = ziel or graph_pfad()
    neu = ziel.with_name(ziel.stem + ".neu.sqlite")
    for p in (neu, Path(str(neu) + "-journal")):
        if p.exists():
            p.unlink()
    ordner_anlegen(neu.parent)
    g = sqlite3.connect(str(neu))
    _datei_schuetzen(neu)
    g.execute("PRAGMA journal_mode=OFF")
    g.execute("PRAGMA synchronous=OFF")
    g.executescript(_GRAPH_SCHEMA)
    z = Counter()
    je_quelle: dict[str, Counter] = defaultdict(Counter)
    auf = _Aufloeser()
    # Spalten je Objekt, um Kommentare/PKs aus anderen Dateien nachzutragen.
    fks_roh: list[tuple[int, list, str, list]] = []
    sicht_roh: list[tuple[int, list, dict]] = []
    nach_alter: list[tuple[str, dict]] = []
    kommentare: list[dict] = []

    melde("Objekte uebernehmen")
    naechste_id = 1
    for i, (datei, roh) in enumerate(roh_con.execute("SELECT datei, fakt FROM roh ORDER BY datei, nr")):
        if i % 50000 == 0 and abbruch():
            g.close()
            neu.unlink(missing_ok=True)
            return {"abgebrochen": True}
        f = json.loads(roh)
        art = f.get("art")
        if art in ("tabelle", "sicht"):
            name = f.get("name") or ""
            schl = schluessel(name)
            if not schl:
                continue
            if schl in auf.genau:
                # Dieselbe Tabelle in zwei Dateien: die erste gilt, Spalten aus
                # der zweiten nur, wenn die erste keine hatte (CREATE … AS).
                z["doppelt"] += 1
                oid = auf.genau[schl]
                hat = g.execute("SELECT spalten_n FROM objekt WHERE id=?", (oid,)).fetchone()[0]
                if hat or not f.get("spalten"):
                    continue
                _spalten_schreiben(g, oid, f)
                continue
            oid = naechste_id
            naechste_id += 1
            schema, kurz = _schema_und_name(name)
            q = quelle_von(datei) or ""
            g.execute("INSERT INTO objekt(id, schluessel, schema, name, name_l, art, kommentar, datei, "
                      "spalten_n, pk, bereich, quelle) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)",
                      (oid, schl, schema, kurz, kurz.lower(), art, f.get("kommentar") or "", datei,
                       len(f.get("spalten") or []), json.dumps(f.get("pk") or []), q))
            je_quelle[q][art] += 1
            je_quelle[q]["spalten"] += len(f.get("spalten") or [])
            _spalten_schreiben(g, oid, f)
            auf.dazu(oid, schl, schluessel(schema))
            z[art] += 1
            z["spalten"] += len(f.get("spalten") or [])
            for fk in f.get("fks") or []:
                fks_roh.append((oid, fk.get("von") or [], fk.get("ziel") or "", fk.get("nach") or []))
            if f.get("nutzt") or f.get("herkunft"):
                sicht_roh.append((oid, f.get("nutzt") or [], f.get("herkunft") or {}))
        elif art == "dokument":
            # Begleitdokument: je Abschnitt eine Zeile, Sichtbarkeit am Schema
            q = quelle_von(datei) or ""
            teile = [t for t in (f.get("teile") or []) if isinstance(t, str) and t.strip()]
            g.executemany("INSERT INTO dokument(quelle, datei, titel, nr, text) VALUES (?,?,?,?,?)",
                          ((q, datei, str(f.get("titel") or "")[:200], n, t) for n, t in enumerate(teile, 1)))
            z["dokumente"] += 1
            z["dokument_teile"] += len(teile)
            je_quelle[q]["dokumente"] += 1
        elif art == "alter":
            nach_alter.append((f.get("name") or "", f))
        elif art == "kommentar":
            kommentare.append(f)

    melde("ALTER TABLE und Kommentare zuordnen")
    for name, f in nach_alter:
        oid = auf.finde(name)
        if oid is None:
            z["alter_ohne_tabelle"] += 1
            continue
        for fk in f.get("fks") or []:
            fks_roh.append((oid, fk.get("von") or [], fk.get("ziel") or "", fk.get("nach") or []))
        if f.get("pk"):
            g.execute("UPDATE objekt SET pk=? WHERE id=?", (json.dumps(f["pk"]), oid))
            g.executemany("UPDATE spalte SET pk=1 WHERE objekt_id=? AND name_l=?",
                          ((oid, s.lower()) for s in f["pk"]))
    for k in kommentare:
        ziel_t = k.get("ziel") or ""
        if k.get("ziel_art") == "spalte":
            tab, _, sp = ziel_t.rpartition(".")
            oid = auf.finde(tab) if tab else None
            if oid is None:
                z["kommentar_ohne_ziel"] += 1
                continue
            cur = g.execute("UPDATE spalte SET kommentar=? WHERE objekt_id=? AND name_l=?",
                            (k.get("text") or "", oid, sp.lower()))
            z["kommentar_spalte"] += cur.rowcount
        else:
            oid = auf.finde(ziel_t)
            if oid is None:
                z["kommentar_ohne_ziel"] += 1
                continue
            g.execute("UPDATE objekt SET kommentar=? WHERE id=?", (k.get("text") or "", oid))
            z["kommentar_tabelle"] += 1

    melde("Fremdschluessel aufloesen")
    fk_spalten: set[tuple[int, str]] = set()
    kanten = []
    for oid, von, ziel_t, nach in fks_roh:
        zid = auf.finde(ziel_t, auf.schema_von.get(oid, ""))
        if zid is None:
            z["fk_unaufgeloest"] += 1
            continue
        if not nach:
            # REFERENCES t ohne Spalten = Primaerschluessel von t
            pk = g.execute("SELECT pk FROM objekt WHERE id=?", (zid,)).fetchone()
            nach = json.loads(pk[0]) if pk and pk[0] else []
        kanten.append((oid, zid, "fk", json.dumps(von), json.dumps(nach)))
        for s in von:
            fk_spalten.add((oid, s.lower()))
        z["fk"] += 1
    herkunft_zeilen = []
    for oid, nutzt, hk in sicht_roh:
        aufgeloest: dict[str, int | None] = {}
        for t in nutzt:
            zid = auf.finde(t, auf.schema_von.get(oid, ""))
            aufgeloest[schluessel(t)] = zid
            if zid is not None and zid != oid:
                kanten.append((oid, zid, "sicht", "[]", "[]"))
                z["sicht_kanten"] += 1
        herkunft_zeilen.extend(_herkunft_aufloesen(oid, hk, aufgeloest, z))
    g.executemany("INSERT INTO herkunft VALUES (?,?,?,?)", herkunft_zeilen)

    if fk_ableiten:
        melde("Beziehungen aus Spaltennamen ableiten")
        z["abgeleitet"] = _ableiten_aus_namen(g, auf, fk_spalten, kanten)

    g.executemany("INSERT INTO kante VALUES (?,?,?,?,?)", kanten)
    z["mehrdeutig"] = auf.mehrdeutig
    z["unbekannt"] = auf.unbekannt

    melde("Bereiche bilden")
    if abbruch():
        g.close()
        neu.unlink(missing_ok=True)
        return {"abgebrochen": True}
    z["bereiche"] = _bereiche(g, naechste_id - 1, kanten)

    melde("Indizes und Volltext aufbauen")
    g.executescript(_GRAPH_INDEX)
    _volltext(g)
    g.execute("INSERT INTO meta VALUES ('stand', ?)", (time.strftime("%Y-%m-%d %H:%M:%S"),))
    g.execute("INSERT INTO meta VALUES ('zaehler', ?)", (json.dumps(dict(z)),))
    g.execute("INSERT INTO meta VALUES ('je_quelle', ?)",
              (json.dumps({q: dict(c) for q, c in je_quelle.items()}),))
    g.commit()
    g.execute("ANALYZE")
    g.close()
    os.replace(neu, ziel)
    return dict(z)


def _spalten_schreiben(g: sqlite3.Connection, oid: int, f: dict) -> None:
    sp = f.get("spalten") or []
    pk = {s.lower() for s in (f.get("pk") or [])}
    g.executemany(
        "INSERT INTO spalte VALUES (?,?,?,?,?,?,?,?)",
        ((oid, i, s.get("name") or "", (s.get("name") or "").lower(), s.get("typ") or "",
          1 if (s.get("pk") or (s.get("name") or "").lower() in pk) else 0,
          1 if s.get("null", True) else 0, s.get("kommentar") or "")
         for i, s in enumerate(sp)))
    g.execute("UPDATE objekt SET spalten_n=? WHERE id=?", (len(sp), oid))


_ID_ENDUNG = re.compile(r"^(?P<stamm>.+?)_?(?:id|nr|no|key|code|schluessel)$", re.I)


def _ableiten_aus_namen(g, auf: _Aufloeser, fk_spalten: set, kanten: list) -> int:
    """``kunde_id`` -> Tabelle ``kunde`` (auch ``kunden``/``kundes``/``tbl_kunde``)
    mit EINSPALTIGEM Primaerschluessel. Nur Spalten ohne deklarierten FK.

    Bewusst eng: ein falsch erschlossener Join ist im SQL nicht von einem
    richtigen zu unterscheiden. Deshalb eigene Kantenart, die der Kontext fuer
    das Modell ausdruecklich als "vermutet" ausweist.
    """
    pk_ein: dict[int, str] = {}
    for oid, pk in g.execute("SELECT id, pk FROM objekt WHERE art='tabelle'"):
        try:
            liste = json.loads(pk or "[]")
        except ValueError:
            liste = []
        if len(liste) == 1:
            pk_ein[oid] = liste[0]
    n = 0
    for oid, name, name_l in g.execute(
            "SELECT objekt_id, name, name_l FROM spalte WHERE pk=0 AND "
            "(name_l LIKE '%id' OR name_l LIKE '%nr' OR name_l LIKE '%no' OR name_l LIKE '%key' "
            "OR name_l LIKE '%code' OR name_l LIKE '%schluessel')").fetchall():
        if (oid, name_l) in fk_spalten:
            continue
        m = _ID_ENDUNG.match(name_l)
        if not m:
            continue
        stamm = m.group("stamm").rstrip("_")
        if len(stamm) < 3:
            continue
        schema = auf.schema_von.get(oid, "")
        treffer = None
        for kand in (stamm, stamm + "s", stamm + "n", stamm + "en", stamm + "e",
                     "tbl_" + stamm, "t_" + stamm):
            for zid in auf.nach_name.get(kand, []):
                if zid == oid or zid not in pk_ein:
                    continue
                if treffer is None or (auf.schema_von.get(zid) == schema
                                       and auf.schema_von.get(treffer) != schema):
                    treffer = zid
        if treffer is None:
            continue
        kanten.append((oid, treffer, "abgeleitet", json.dumps([name]),
                       json.dumps([pk_ein[treffer]])))
        fk_spalten.add((oid, name_l))
        n += 1
    return n + _ableiten_gleicher_pk(g, auf, fk_spalten, kanten, pk_ein)


# Primaerschluessel-Namen, die die zweite Regel benutzt: zusammengesetzt
# (PRAEFIX_REST, Praefix mindestens drei Zeichen) – ``ALLLND_LAND``,
# ``AKDKND_ID``, ``kunde_nr``, nicht ``OBJEKTID``/``LASTUPDATE``/``id``.
_PK_ZUSAMMENGESETZT = re.compile(r"[a-z0-9]{3,}_[a-z0-9_]+")


def _ableiten_gleicher_pk(g, auf: _Aufloeser, fk_spalten: set, kanten: list, pk_ein: dict) -> int:
    """Zweite Regel: eine Spalte, die GENAU SO heisst wie der einspaltige
    Primaerschluessel GENAU EINER anderen Tabelle (bei mehreren: genau einer im
    eigenen Schema), verweist auf diese.

    Gemessen am echten YAML-Bestand auf DEV (2026-11-07, 4033 Tabellen, nur 169
    davon mit deklarierten Fremdschluesseln): die erste Regel (``kunde_id`` ->
    ``kunde``) fand dort 24 Beziehungen, 2610 Tabellen blieben ohne jede Kante.
    Diese Regel findet 2104; von den 104 deklarierten einspaltigen
    Fremdschluesseln reproduziert sie 44 und widerspricht KEINEM, und 85 % ihrer
    Treffer passen zusaetzlich zur Kuerzel-Konvention des Bestands.

    Bewusst nur ZUSAMMENGESETZTE Schluesselnamen (``_PK_ZUSAMMENGESETZT``): ohne
    diese Schranke kamen allgemeine Namen hinzu, die zufaellig nur einmal
    Primaerschluessel sind – gemessen ``LASTUPDATE`` -> eine Nachrichtentabelle,
    ``OBJEKTID`` -> eine Prioritaetentabelle. Ein falscher Join ist im SQL nicht
    von einem richtigen zu unterscheiden; also lieber 222 echte verpassen.
    Kantenart ``abgeleitet`` – das Modell sieht sie als "vermutet".
    """
    nach_pk: dict[str, list[int]] = defaultdict(list)
    for oid, pk in pk_ein.items():
        if _PK_ZUSAMMENGESETZT.fullmatch(pk.lower()):
            nach_pk[pk.lower()].append(oid)
    if not nach_pk:
        return 0
    n = 0
    # Nur Tabellen: Sichten haengen ueber ihre Kanten "sicht" schon an den
    # Tabellen, auf denen sie beruhen (und so ist die Regel gemessen).
    for oid, name, name_l, ist_pk in g.execute(
            "SELECT s.objekt_id, s.name, s.name_l, s.pk FROM spalte s JOIN objekt o ON o.id = s.objekt_id "
            "WHERE o.art = 'tabelle'").fetchall():
        ziele = nach_pk.get(name_l)
        if not ziele or (oid, name_l) in fk_spalten:
            continue
        # Der eigene einspaltige Primaerschluessel verweist nicht auf sich selbst
        if ist_pk and pk_ein.get(oid, "").lower() == name_l:
            continue
        andere = [z for z in ziele if z != oid]
        if len(andere) != 1:
            schema = auf.schema_von.get(oid, "")
            andere = [z for z in andere if auf.schema_von.get(z) == schema]
        if len(andere) != 1:
            continue
        kanten.append((oid, andere[0], "abgeleitet", json.dumps([name]), json.dumps([pk_ein[andere[0]]])))
        fk_spalten.add((oid, name_l))
        n += 1
    return n


_ALLGEMEIN = {"id", "nr", "no", "tbl", "tab", "t", "v", "vw", "view", "hist", "log", "tmp",
              "temp", "data", "daten", "info", "dbo", "public", "x", "old", "new", "bak"}


# Knoten mit mehr Kanten gelten fuer die Bereichsbildung als Hub (Mandant,
# Waehrung, Benutzer …) – dieselbe Schwelle wie die Breitensuche der Suche.
BEREICH_HUB_GRAD = 300


def _bereiche(g: sqlite3.Connection, max_id: int, kanten: list) -> int:
    """Label Propagation ueber den ungerichteten Graphen (fk/sicht = 1.0,
    abgeleitet = 0.5). Deterministisch (fester Zufallsstart, feste Runden).

    ⚠ Kanten an einem HUB zaehlen nicht mit: verweist jede Tabelle auf
    ``mandant``, zog der Hub sonst den ganzen Bestand in EINEN Bereich
    (Massstabsprobe DEV, 100.000 Tabellen: 1 Bereich). Der Hub selbst bleibt
    ohne Bereich, wenn er sonst keine Kanten hat.
    """
    if max_id <= 0:
        return 0
    grad: Counter = Counter()
    for von, nach, _art, _a, _b in kanten:
        grad[von] += 1
        grad[nach] += 1
    nachbarn: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for von, nach, art, _a, _b in kanten:
        if grad[von] > BEREICH_HUB_GRAD or grad[nach] > BEREICH_HUB_GRAD:
            continue
        w = 0.5 if art == "abgeleitet" else 1.0
        nachbarn[von].append((nach, w))
        nachbarn[nach].append((von, w))
    label = {i: i for i in nachbarn}
    knoten = sorted(nachbarn)
    rnd = random.Random(42)
    for _runde in range(15):
        rnd.shuffle(knoten)
        geaendert = 0
        for k in knoten:
            gew: dict[int, float] = defaultdict(float)
            for n, w in nachbarn[k]:
                gew[label[n]] += w
            best = max(gew.items(), key=lambda kv: (kv[1], -kv[0]))[0]
            if best != label[k]:
                label[k] = best
                geaendert += 1
        if geaendert < max(1, len(knoten) // 1000):
            break
    # Neu nummerieren, benennen, schreiben. Einzelgaenger ohne Kanten bilden
    # keinen Bereich (bereich bleibt NULL) – das sind keine Gemeinschaften.
    gruppen: dict[int, list[int]] = defaultdict(list)
    for k, l in label.items():
        gruppen[l].append(k)
    namen = {oid: n for oid, n in g.execute("SELECT id, name FROM objekt")}
    bid = 0
    for _l, mitglieder in sorted(gruppen.items(), key=lambda kv: -len(kv[1])):
        if len(mitglieder) < 2:
            continue
        bid += 1
        woerter = Counter()
        for oid in mitglieder:
            woerter.update({w for w in namens_woerter(namen.get(oid, ""))
                            if w not in _ALLGEMEIN and not w.isdigit() and len(w) >= 3})
        name = ", ".join(w for w, _ in woerter.most_common(3)) or f"Bereich {bid}"
        g.execute("INSERT INTO bereich VALUES (?,?,?)", (bid, name, len(mitglieder)))
        g.executemany("UPDATE objekt SET bereich=? WHERE id=?", ((bid, o) for o in mitglieder))
    return bid


def _volltext(g: sqlite3.Connection) -> None:
    """FTS5 je Objekt: Name (ganz + zerlegt, doppelt gewichtet ueber eigene
    Spalte), Kommentar, Spaltennamen und -kommentare. Dazu je Abschnitt eines
    Begleitdokuments (Titel + Text, Bezeichner zusaetzlich zerlegt)."""
    g.execute("CREATE VIRTUAL TABLE dokument_fts USING fts5(titel, text, "
              "tokenize='unicode61 remove_diacritics 2')")
    for did, titel, text in g.execute("SELECT id, titel, text FROM dokument").fetchall():
        zerlegt = " ".join(namens_woerter(" ".join(re.findall(r"[A-Za-z][A-Za-z0-9_$#]*_[A-Za-z0-9_$#]+", text))))
        g.execute("INSERT INTO dokument_fts(rowid, titel, text) VALUES (?,?,?)", (did, titel, text + " " + zerlegt))
    g.execute("CREATE VIRTUAL TABLE objekt_fts USING fts5(name, kommentar, spalten, "
              "tokenize='unicode61 remove_diacritics 2')")
    cur = g.execute("SELECT id, schluessel, kommentar FROM objekt")
    while True:
        zeilen = cur.fetchmany(5000)
        if not zeilen:
            break
        daten = []
        for oid, schl, kom in zeilen:
            sp = g.execute("SELECT name, kommentar FROM spalte WHERE objekt_id=? ORDER BY pos LIMIT ?",
                           (oid, FTS_MAX_SPALTEN)).fetchall()
            sp_text = " ".join(" ".join(namens_woerter(n)) + (" " + k if k else "") for n, k in sp)
            daten.append((oid, " ".join(namens_woerter(schl)), kom or "", sp_text))
        g.executemany("INSERT INTO objekt_fts(rowid, name, kommentar, spalten) VALUES (?,?,?,?)", daten)


# ─── Lesen ──────────────────────────────────────────────────────────────────

def graph_lesen(pfad: Path | None = None) -> sqlite3.Connection | None:
    """Nur-Lese-Verbindung auf den Graphen (None, wenn es keinen gibt)."""
    p = pfad or graph_pfad()
    if not p.exists():
        return None
    # check_same_thread=False: die Werkzeuge reichen die Verbindung an
    # ``asyncio.to_thread`` weiter (nacheinander, nie gleichzeitig) – die
    # Suche darf den Event-Loop nicht blockieren.
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con
