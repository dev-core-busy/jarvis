#!/usr/bin/env python3
"""Waechter: jedes Schema ist im Graphen ein eigener Bestand.

Anlass (ECHT 2026-11-11): zwei Schemata beschrieben dieselbe Datenbank
(SQL-Export und HTML-Dokumentation, beide mit ``dbo.<Tabelle>``). Der
Objektschluessel war global; alle 249 Objekte des zweiten Schemas galten als
"doppelt" und fielen weg – eine Frage an dieses Schema endete mit "Zu den
Begriffen der Frage wurde keine Tabelle gefunden". Dieselbe globale Aufloesung
haette Fremdschluessel, ALTER, Kommentare, Sicht-Kanten und abgeleitete
Beziehungen ueber Schemagrenzen gefuehrt.

Gemessen wird ueber den ECHTEN Lauf (``schema_graph_index.lauf`` mit zwei
Quellen, SQL-Dateien) und den fertigen Graphen – nicht am Aufloeser allein.

Dazu ``ohne_struktur``: bewusst uebersprungene Objekte (SEQUENCE, PACKAGE …
im YAML-Export, Verzeichnisdateien) sind kein Hinweis wert (ECHT: 2183
Fehlalarme nach dem Neulesen).

Aufruf:  python3 tests/test_schema_graph_quellen.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import atexit
import json
import shutil
import sqlite3
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail)[:400] if detail else ""))


def abbruch(grund):
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


# backend.config-Attrappe VOR jedem Import (der echte schreibt settings.json).
_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = types.SimpleNamespace(get_skill_states=lambda: {"schema_graph": {"enabled": True, "config": {}}})
sys.modules["backend.config"] = _cfg_mod
try:
    from backend import schema_graph_index as I
    from backend import schema_graph_store as S
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht ladbar: {e}")

TMP = Path(tempfile.mkdtemp(prefix="test_sg_quellen_"))
atexit.register(shutil.rmtree, TMP, True)
S.ORDNER = TMP / "ablage"
if not str(S.ordner()).startswith(str(TMP)):
    abbruch("Ablage zeigt aus dem Sandkasten heraus")

A, B = TMP / "a", TMP / "b"
A.mkdir()
B.mkdir()
# Schema a: Kunde (2 Spalten), Auftrag mit DEKLARIERTEM FK, LandID ohne
# Land-Tabelle, Ort mit ABCLND_LAND ohne die Tabelle dazu.
(A / "schema.sql").write_text("""
CREATE TABLE dbo.Kunde (KundeID int PRIMARY KEY, Name varchar(10));
CREATE TABLE dbo.Auftrag (AuftragID int PRIMARY KEY, KundeID int REFERENCES dbo.Kunde(KundeID), LandID int);
CREATE TABLE dbo.Ort (OrtID int PRIMARY KEY, ABCLND_LAND varchar(3));
EXEC sp_addextendedproperty 'MS_Description', 'Kunde A', 'SCHEMA', 'dbo', 'TABLE', 'Kunde';
EXEC sp_addextendedproperty 'MS_Description', 'Name A', 'SCHEMA', 'dbo', 'TABLE', 'Kunde', 'COLUMN', 'Name';
""", encoding="utf-8")
# Dieselbe Tabelle zweimal im SELBEN Schema: das bleibt eine Dublette
(A / "zwei.sql").write_text("CREATE TABLE dbo.Kunde (KundeID int PRIMARY KEY, Name varchar(10));\n",
                            encoding="utf-8")
# Schema b: gleiche Namen, andere Spalten; FK erst per ALTER; Land und ABCLND
# vorhanden (die Ableitungen greifen HIER, und nur hier); eine Sicht.
(B / "schema.sql").write_text("""
CREATE TABLE dbo.Kunde (KundeID int PRIMARY KEY, Name varchar(10), Extra int);
CREATE TABLE dbo.Auftrag (AuftragID int PRIMARY KEY, KundeID int, LandID int);
CREATE TABLE dbo.Land (LandID int PRIMARY KEY, Bez varchar(20));
CREATE TABLE dbo.ABCLND (ABCLND_LAND varchar(3) PRIMARY KEY, Bez varchar(20));
CREATE TABLE dbo.Ort (OrtID int PRIMARY KEY, ABCLND_LAND varchar(3));
ALTER TABLE dbo.Auftrag ADD CONSTRAINT fk_kunde FOREIGN KEY (KundeID) REFERENCES dbo.Kunde(KundeID);
CREATE VIEW dbo.vKunde AS SELECT k.KundeID, k.Name FROM dbo.Kunde k;
EXEC sp_addextendedproperty 'MS_Description', 'Kunde B', 'SCHEMA', 'dbo', 'TABLE', 'Kunde';
""", encoding="utf-8")

st = I.lauf([], quellen=[{"id": "a", "ordner": [str(A)]}, {"id": "b", "ordner": [str(B)]}],
            muster="*.sql", prozesse=1, ordner_schutz=False)
g = S.graph_lesen()
if g is None:
    # Ein Produktbefund (z. B. Eindeutigkeit verletzt), kein "konnte nicht laufen"
    check("Graph entstanden", False, (st.get("ergebnis"), st.get("fehler")))
    print(f"\nBilanz: {OK} OK, {FAIL} FAIL")
    sys.exit(1)
g.row_factory = None    # Tupel statt sqlite3.Row – die Pruefungen vergleichen Tupel


def oid(quelle, schl):
    r = g.execute("SELECT id FROM objekt WHERE quelle=? AND schluessel=?", (quelle, schl)).fetchall()
    return r[0][0] if len(r) == 1 else -1


def wert(sql, args=()):
    """Erste Spalte der ersten Zeile oder None – wirft nicht, wenn nichts da ist
    (ein Wurf waere in der Gegenprobe ein Lauf ohne Bilanz statt eines FAIL)."""
    r = g.execute(sql, args).fetchone()
    return r[0] if r else None


def kanten(von, art=None):
    sql = "SELECT nach, art FROM kante WHERE von=?" + (" AND art=?" if art else "")
    return g.execute(sql, (von, art) if art else (von,)).fetchall()


print("0. Positivkontrolle")
ka, kb = oid("a", "dbo.kunde"), oid("b", "dbo.kunde")
check("Graph mit Objekten aus BEIDEN Quellen",
      {r[0] for r in g.execute("SELECT DISTINCT quelle FROM objekt")} == {"a", "b"},
      g.execute("SELECT quelle, schluessel FROM objekt").fetchall())

print("1. Gleichnamige Objekte je Schema")
check("dbo.Kunde steht in a UND in b", ka > 0 and kb > 0 and ka != kb, (ka, kb))
check("je Schema die eigenen Spalten (2 gegen 3)",
      [r[0] for r in g.execute("SELECT spalten_n FROM objekt WHERE id IN (?,?) ORDER BY id", (ka, kb))] == [2, 3],
      g.execute("SELECT quelle, spalten_n FROM objekt WHERE schluessel='dbo.kunde'").fetchall())
check("je Schema die eigene Sicht der Objekte: a 3 Tabellen, b 5 Tabellen + 1 Sicht",
      g.execute("SELECT quelle, art, count(*) FROM objekt GROUP BY quelle, art ORDER BY 1, 2").fetchall()
      == [("a", "tabelle", 3), ("b", "sicht", 1), ("b", "tabelle", 5)],
      g.execute("SELECT quelle, art, count(*) FROM objekt GROUP BY quelle, art").fetchall())
check("Dublette nur INNERHALB eines Schemas gezaehlt (genau 1)", st.get("graph", {}).get("doppelt") == 1,
      st.get("graph"))

print("2. Aufloesung bleibt im eigenen Schema")
check("Kommentar a an Kunde a", wert("SELECT kommentar FROM objekt WHERE id=?", (ka,)) == "Kunde A")
check("Kommentar b an Kunde b", wert("SELECT kommentar FROM objekt WHERE id=?", (kb,)) == "Kunde B")
def spkom(o, sp):
    return wert("SELECT kommentar FROM spalte WHERE objekt_id=? AND name_l=?", (o, sp))


check("Spaltenkommentar a an Kunde a.Name", spkom(ka, "name") == "Name A", spkom(ka, "name"))
check("Kunde b.Name bleibt ohne Kommentar", spkom(kb, "name") == "", spkom(kb, "name"))
aa, ab = oid("a", "dbo.auftrag"), oid("b", "dbo.auftrag")
check("deklarierter FK in a zeigt auf Kunde a", kanten(aa, "fk") == [(ka, "fk")], kanten(aa))
check("ALTER aus b haengt an Auftrag b und zeigt auf Kunde b", kanten(ab, "fk") == [(kb, "fk")], kanten(ab))
vk = oid("b", "dbo.vkunde")
check("Sicht b benutzt Kunde b", kanten(vk, "sicht") == [(kb, "sicht")], kanten(vk))
quer = wert("SELECT count(*) FROM kante k JOIN objekt v ON v.id=k.von JOIN objekt n ON n.id=k.nach "
            "WHERE v.quelle <> n.quelle")
check("keine einzige Kante ueber eine Schemagrenze", quer == 0, quer)

print("3. Abgeleitete Beziehungen nur im eigenen Schema")
lb = oid("b", "dbo.land")
check("Positivkontrolle: Auftrag b.LandID -> Land b (Regel 'xxx_id')",
      (lb, "abgeleitet") in kanten(ab, "abgeleitet"), kanten(ab))
check("Auftrag a.LandID bekommt KEINE Kante nach b", kanten(aa, "abgeleitet") == [], kanten(aa))
ob, oa, nb = oid("b", "dbo.ort"), oid("a", "dbo.ort"), oid("b", "dbo.abclnd")
check("Positivkontrolle: Ort b.ABCLND_LAND -> ABCLND b (Regel 'gleicher PK')",
      (nb, "abgeleitet") in kanten(ob, "abgeleitet"), kanten(ob))
check("Ort a.ABCLND_LAND bekommt KEINE Kante nach b", kanten(oa, "abgeleitet") == [], kanten(oa))

print("4. 'ohne Struktur' nur fuer echte Luecken")
con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE dateien(pfad TEXT, stand TEXT, fakten INTEGER, stat TEXT)")
faelle = {
    "/x/seq.yaml": {"anweisungen": 1, "objekt_uebersprungen": 1},
    "/x/index.yaml": {"anweisungen": 1, "verzeichnis": 1},
    "/x/leer.sql": {"anweisungen": 5},
    "/x/halb.yaml": {"anweisungen": 2, "objekt_uebersprungen": 1},
}
con.executemany("INSERT INTO dateien VALUES (?, 'ok', 0, ?)", ((p, json.dumps(s)) for p, s in faelle.items()))
leer = I.ohne_struktur(con, lambda _p: "q").get("q", [])
check("Positivkontrolle: eine Datei ohne jede Struktur steht da", "/x/leer.sql" in leer, leer)
check("nur uebersprungene Objekte (SEQUENCE …): kein Hinweis", "/x/seq.yaml" not in leer, leer)
check("Verzeichnisdatei: kein Hinweis", "/x/index.yaml" not in leer, leer)
check("teils uebersprungen, teils unverstanden: Hinweis bleibt", "/x/halb.yaml" in leer, leer)

print(f"\nBilanz: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
