#!/usr/bin/env python3
"""Waechter: SQL-Assistent (Schema-Graph) – Parser, Graph, GraphRAG, Pruefung.

Gemessen werden WIRKUNGEN, nicht Vorkommen:

  1. Parser: Struktur aus PostgreSQL-/T-SQL-/MySQL-DDL; Datenbloecke
     (INSERT, COPY FROM stdin) tragen keine Struktur, auch wenn darin
     "CREATE TABLE" steht; dieselben Anweisungen bei JEDER Blockgroesse
     1..200 (Blockgrenze zwischen "-" und "-", mitten in "$tag$", mitten im
     Kopf "ALTER " | "TABLE"); ein grosses INSERT wird NICHT gepuffert
     (Speicherspitze per tracemalloc); Oracles ``V$SESSION`` oeffnet keine
     Zeichenkette bis Dateiende.
  2. Ableitung: Fremdschluessel/Kommentar aus einer ANDEREN Datei als das
     CREATE; unqualifizierter Verweis ueber das Schema des Verweisenden;
     Mehrdeutiges wird nicht geraten; abgeleitete Kanten nur ohne deklarierten
     FK und als eigene Art; Abbruch laesst den alten Graphen byte-gleich.
  3. Indexlauf: inkrementell, verschwundene Dateien raus, Negativ-Cache nach
     MAX_VERSUCHE Abstuerzen, Sperre gegen einen zweiten Lauf.
  4. GraphRAG: Steiner-Naeherung bringt ein Join-Glied ohne Suchtreffer in den
     Kontext; ein Hub wird nicht ausgebreitet; die Kuerzung der Spaltenliste
     steht beziffert VOR der Liste.
  5. Pruefung (Riegel): Tabelle aus Faellen – nur lesend, eine Anweisung,
     Zeichenketten/Kommentare/Namen in Anfuehrungszeichen sind kein SQL,
     unbekannte Spalten mit Vorschlag, Aliase, Komma-Join, CTE.
  6. Kette mit Modell-Attrappe (Aufrufform wie ``_modell(auftrag, system)``):
     Reparaturrunde, BRAUCHE-Runde, dauerhaft schreibendes SQL bleibt
     "NICHT BESTANDEN" in der ERSTEN Ausgabezeile, Rueckfall ohne Begriffsmodell.
  7. Skill: Manifest-Werkzeuge == get_tools(); Erfassen aus dem Chat ist ohne
     Schalter abgewiesen. Regeln am Syntaxbaum: der Parser importiert nichts
     aus ``backend``, der Indexlauf benutzt kein ``multiprocessing``.

``backend.config`` nur als Attrappe. Alles in einem Wegwerf-Verzeichnis.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

    python3 tests/test_schema_graph.py
"""
from __future__ import annotations

import ast
import asyncio
import atexit
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import tracemalloc
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def wert(con, sql, args=(), vorgabe=None):
    """Erste Spalte der ersten Zeile oder ``vorgabe`` (wirft nie)."""
    try:
        r = con.execute(sql, args).fetchone()
    except Exception:  # noqa: BLE001
        return vorgabe
    return r[0] if r else vorgabe


def erstes(folge, vorgabe=None):
    """Erstes Element oder ``vorgabe`` – nie werfen (eine werfende Pruefung
    beendet den Lauf ohne Bilanz und sieht wie "nicht gelaufen" aus)."""
    for x in folge:
        return x
    return vorgabe


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
_SKILL_CFG = {"schema_graph": {"enabled": True, "config": {}}}
_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = types.SimpleNamespace(get_skill_states=lambda: _SKILL_CFG)
sys.modules["backend.config"] = _cfg_mod

try:
    from backend import schema_graph_parser as P
    from backend import schema_graph_store as S
    from backend import schema_graph_index as I
    from backend import schema_graph_rag as R
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht ladbar: {e}")

TMP = Path(tempfile.mkdtemp(prefix="test_schema_graph_"))
# Aufraeumen auch bei Abbruch/Absturz (eine Gegenprobe, die den Lauf kippen
# laesst, hinterliess sonst je Probe einen Ordner in /tmp – dort ein tmpfs).
atexit.register(shutil.rmtree, TMP, True)
S.ORDNER = TMP / "ablage"
if not str(S.ordner()).startswith(str(TMP)):
    abbruch("Ablage zeigt aus dem Sandkasten heraus")

PG = r"""-- Kopf; Semikolon im Kommentar
SET client_encoding = 'UTF8';
CREATE TABLE public.kunde (
    id integer NOT NULL,
    name character varying(200) NOT NULL, -- Name; mit Semikolon
    land_code char(2) REFERENCES stamm.land(code),
    CONSTRAINT kunde_pkey PRIMARY KEY (id)
);
COMMENT ON TABLE public.kunde IS 'Kundenstamm; alle Debitoren';
COMMENT ON COLUMN public.kunde.name IS 'Anzeigename des Kunden';
CREATE TABLE "public"."Auftrag" ("AuftragId" bigint PRIMARY KEY, kunde_id integer, betrag numeric(12,2), datum date);
COPY public.kunde (id, name) FROM stdin;
1	O'Brien; CREATE TABLE falsch_copy (x int);
2	Semikolon ; hier
\.
CREATE FUNCTION f() RETURNS int AS $body$ BEGIN RETURN 1; END; $body$ LANGUAGE plpgsql;
CREATE VIEW public.v_umsatz AS SELECT k.name, sum(a.betrag) FROM public.kunde k JOIN public."Auftrag" a ON a.kunde_id = k.id GROUP BY k.name;
INSERT INTO public.kunde VALUES (3, 'x; CREATE TABLE falsch_insert(y int)');
SELECT * FROM V$SESSION;
CREATE TABLE stamm.land (code char(2) primary key, bez varchar(80)) COMMENT='Laender';
"""
# ALTER und Kommentar in einer ANDEREN Datei als das CREATE
PG2 = """ALTER TABLE ONLY public."Auftrag" ADD CONSTRAINT fk_kunde FOREIGN KEY (kunde_id) REFERENCES kunde(id);
COMMENT ON TABLE public."Auftrag" IS 'Auftragskopf';
"""
MS = """CREATE TABLE [dbo].[Artikel](
\t[ArtikelID] [int] IDENTITY(1,1) NOT NULL,
\t[Bez] [nvarchar](100) NULL,
 CONSTRAINT [PK_Artikel] PRIMARY KEY CLUSTERED ([ArtikelID] ASC)
) ON [PRIMARY]
GO
EXEC sys.sp_addextendedproperty @name=N'MS_Description', @value=N'Artikelstamm' , @level0type=N'SCHEMA',@level0name=N'dbo', @level1type=N'TABLE',@level1name=N'Artikel'
GO
CREATE TABLE `shop`.`bestellpos` (`id` int NOT NULL AUTO_INCREMENT COMMENT 'Positions-ID', `artikel_id` int, `lager_id` int, PRIMARY KEY (`id`), KEY `ix` (`artikel_id`), CONSTRAINT `fk_art` FOREIGN KEY (`artikel_id`) REFERENCES `dbo`.`Artikel` (`ArtikelID`)) ENGINE=InnoDB COMMENT='Bestellpositionen';
CREATE TABLE shop.lager (id int PRIMARY KEY, ort varchar(50));
CREATE TABLE a.dublette (id int primary key);
CREATE TABLE b.dublette (id int primary key);
CREATE TABLE shop.verweis (id int primary key, d_id int REFERENCES dublette(id));
"""

Q = TMP / "quelle"
Q.mkdir()
(Q / "pg.sql").write_text(PG)
(Q / "pg_alter.sql").write_text(PG2)
(Q / "ms.sql").write_text(MS)
(Q / "notiz.md").write_text("CREATE TABLE ignoriert (x int);")

# ─── Positivkontrolle ───────────────────────────────────────────────────────
erg = P.datei_zerlegen(str(Q / "pg.sql"))
namen = {f.get("name") for f in erg["fakten"] if f.get("art") in ("tabelle", "sicht")}
if not erg["ok"] or "public.kunde" not in namen:
    abbruch(f"Parser liefert auf dem Probematerial nichts Erwartetes: {erg.get('fehler')} {namen}")

print("1. Parser")
check("Tabellen und Sicht erkannt", namen == {"public.kunde", "public.Auftrag", "public.v_umsatz", "stamm.land"},
      namen)
check("CREATE TABLE in COPY-Daten/INSERT-String ist keine Struktur",
      not any("falsch" in (n or "") for n in namen), namen)
check("COPY-Block erkannt", erg["stat"].get("copy_bloecke") == 1, erg["stat"])
kunde = erstes((f for f in erg["fakten"] if f.get("name") == "public.kunde"), {"spalten": [], "pk": [], "fks": []})
check("Spalten mit Typ", [(s.get("name"), s.get("typ")) for s in kunde["spalten"]] ==
      [("id", "integer"), ("name", "character varying(200)"), ("land_code", "char(2)")], kunde["spalten"])
check("PK aus Constraint", kunde["pk"] == ["id"], kunde["pk"])
check("Inline-REFERENCES", kunde["fks"] == [{"von": ["land_code"], "ziel": "stamm.land", "nach": ["code"]}],
      kunde["fks"])
kom = [f for f in erg["fakten"] if f.get("art") == "kommentar"]
check("COMMENT ON TABLE/COLUMN (Semikolon im Text)", {(k.get("ziel_art"), k.get("ziel"), k.get("text")) for k in kom} == {
    ("tabelle", "public.kunde", "Kundenstamm; alle Debitoren"),
    ("spalte", "public.kunde.name", "Anzeigename des Kunden")}, kom)
sicht = erstes((f for f in erg["fakten"] if f.get("name") == "public.v_umsatz"), {"nutzt": None})
check("Sicht kennt benutzte Tabellen", sicht["nutzt"] == ["public.Auftrag", "public.kunde"], sicht["nutzt"])
ms = P.datei_zerlegen(str(Q / "ms.sql"))
art = erstes((f for f in ms["fakten"] if f.get("name") == "dbo.Artikel"), {"pk": None, "spalten": [{}, {}]})
check("T-SQL: [ArtikelID] ASC ist Spalte ArtikelID", art["pk"] == ["ArtikelID"], art["pk"])
check("T-SQL: Typ ohne Klammern", len(art["spalten"]) > 1 and art["spalten"][1].get("typ") == "nvarchar(100)", art["spalten"])
check("T-SQL: sp_addextendedproperty", any(f.get("art") == "kommentar" and f.get("text") == "Artikelstamm"
                                           for f in ms["fakten"]), ms["fakten"])
bp = erstes((f for f in ms["fakten"] if f.get("name") == "shop.bestellpos"), {"kommentar": None, "spalten": [{}]})
check("MySQL: Spalten- und Tabellenkommentar",
      bp["kommentar"] == "Bestellpositionen" and bp["spalten"][:1] and bp["spalten"][0].get("kommentar") == "Positions-ID", bp)

ref_pg = list(P.anweisungen(str(Q / "pg.sql")))
ref_ms = list(P.anweisungen(str(Q / "ms.sql")))
abw = [b for b in range(1, 201) if list(P.anweisungen(str(Q / "pg.sql"), block=b)) != ref_pg]
abw += [-b for b in range(1, 201) if list(P.anweisungen(str(Q / "ms.sql"), block=b)) != ref_ms]
check("Gleiche Anweisungen bei jeder Blockgroesse 1..200", not abw, f"abweichend: {abw[:15]}")

# Ein Name mit ZWEI $ darf kein Dollar-Quoting oeffnen ($RATE$ waere ein Tag)
# Zweites Vorkommen desselben Namens: ohne Lookbehind waere "$RATE$ … $RATE$"
# eine VOLLSTAENDIGE Zeichenkette und verschluckte nach_ora2 (Zweig "str");
# das erste allein, ohne Gegenstueck, prueft den Zweig "offen".
(TMP / "ora.sql").write_text("SELECT * FROM PAY$RATE$HIST WHERE x = 1;\nCREATE TABLE nach_ora (id int);\n"
                             "SELECT * FROM V$SESSION;\nCREATE TABLE nach_ora2 (id int);\n"
                             "SELECT * FROM PAY$RATE$ALT;\nCREATE TABLE nach_ora3 (id int);\n")
(TMP / "ora1.sql").write_text("SELECT * FROM PAY$RATE$HIST WHERE x = 1;\nCREATE TABLE nach_ora (id int);\n")
ora1 = P.datei_zerlegen(str(TMP / "ora1.sql"))
check("Ein Name mit zwei $ ohne Gegenstueck oeffnet nichts",
      [f.get("name") for f in ora1["fakten"]] == ["nach_ora"], ora1["fakten"])
ora = P.datei_zerlegen(str(TMP / "ora.sql"))
check("PAY$RATE$HIST/V$SESSION oeffnen kein Dollar-Quoting",
      [f.get("name") for f in ora["fakten"]] == ["nach_ora", "nach_ora2", "nach_ora3"], ora["fakten"])

# Eine einzige lange Zeile ohne Umbruch: hier schneidet der Automat MITTEN in
# der Zeile – Kontextzeichen (GO-Zeile, Lookbehind) und Rueckweichen vor "/".
# (Kein "--" darin: ohne Zeilenende waere der ganze Rest Kommentar.)
EINZEILE = ("SELECT 1 AS ALGO FROM t WHERE a = 'x' ; CREATE TABLE z1 (id int, b int /* k; k */); "
            "SELECT Q$A$B FROM PAY$RATE$HIST ; CREATE TABLE z2 (id int) ; SELECT $$ a ; b $$ AS t ; "
            "CREATE TABLE z3 (id int); SELECT 1 AS ALGO ; CREATE TABLE z4 (id int)")
(TMP / "einzeile.sql").write_text(EINZEILE.replace("\n", " ") + " ")
ref_e = list(P.anweisungen(str(TMP / "einzeile.sql")))
abw_e = [b for b in range(1, 120) if list(P.anweisungen(str(TMP / "einzeile.sql"), block=b)) != ref_e]
check("Positivkontrolle einzeilige Probe: vier Tabellen",
      [P.zerlege(a).get("name") for a in ref_e if P.zerlege(a)] == ["z1", "z2", "z3", "z4"],
      [P.zerlege(a) for a in ref_e])
check("Einzeilige Datei: gleiche Anweisungen bei jeder Blockgroesse 1..119", not abw_e, abw_e[:15])

# Grosses INSERT: Speicherspitze muss weit unter der Anweisungsgroesse bleiben
gross = TMP / "gross.sql"
with open(gross, "w") as f:
    f.write("INSERT INTO t VALUES ")
    zeile = ",".join(f"({i},'Wert ; {i} mit '' Apostroph')" for i in range(2000))
    while f.tell() < 12 * 1024 * 1024:
        f.write(zeile + ",")
    f.write("(0,'x');\nCREATE TABLE nach_insert (id int);\n")
tracemalloc.start()
gr = [P.zerlege(a) for a in P.anweisungen(str(gross), block=256 * 1024)]
_akt, spitze = tracemalloc.get_traced_memory()
tracemalloc.stop()
check("Grosses INSERT ueberlesen, Struktur danach gefunden",
      [g.get("name") for g in gr if g] == ["nach_insert"], gr)
check("INSERT nicht gepuffert (Spitze < 4 MB bei 12 MB Anweisung)", spitze < 4 * 1024 * 1024,
      f"Spitze {spitze / 1e6:.1f} MB")

# ─── 2./3. Indexlauf und Ableitung ──────────────────────────────────────────
print("2./3. Indexlauf und Ableitung")
st = I.lauf([str(Q)], prozesse=2)
check("Lauf fertig", st["ergebnis"] == "fertig" and not st["fehler"], (st["ergebnis"], st["fehler"]))
check("Nur passende Muster gelesen (notiz.md nicht)", st["dateien_neu"] == 3, st["dateien_neu"])
g = S.graph_lesen()
if g is None:
    abbruch("kein Graph nach dem Lauf")


def kanten():
    return {(a, b, art) for a, b, art in g.execute(
        "SELECT x.schluessel, y.schluessel, k.art FROM kante k JOIN objekt x ON x.id=k.von "
        "JOIN objekt y ON y.id=k.nach")}


K = kanten()
check("FK aus ALTER in anderer Datei, unqualifizierter Verweis aufgeloest",
      ("public.auftrag", "public.kunde", "fk") in K, K)
check("Kommentar aus anderer Datei", wert(g, "SELECT kommentar FROM objekt WHERE schluessel='public.auftrag'") == "Auftragskopf")
check("Spaltenkommentar uebernommen", wert(g, "SELECT s.kommentar FROM spalte s JOIN objekt o ON o.id=s.objekt_id WHERE o.schluessel='public.kunde' "
    "AND s.name_l='name'") == "Anzeigename des Kunden")
check("Sicht-Kanten", {("public.v_umsatz", "public.kunde", "sicht"),
                       ("public.v_umsatz", "public.auftrag", "sicht")} <= K, K)
check("Mehrdeutiger Verweis nicht geraten", not any(a == "shop.verweis" for a, _b, _c in K), K)
check("Abgeleitete Kante lager_id -> lager als eigene Art",
      ("shop.bestellpos", "shop.lager", "abgeleitet") in K, K)
check("Keine abgeleitete Kante, wo ein FK deklariert ist",
      ("shop.bestellpos", "dbo.artikel", "abgeleitet") not in K and ("shop.bestellpos", "dbo.artikel", "fk") in K, K)
zaehler = json.loads(wert(g, "SELECT v FROM meta WHERE k='zaehler'", vorgabe="{}"))
check("Mehrdeutigkeit gezaehlt", zaehler.get("mehrdeutig", 0) >= 1, zaehler)
g.close()

st2 = I.lauf([str(Q)], prozesse=2)
check("Zweiter Lauf unveraendert", st2["ergebnis"] == "unveraendert" and st2["dateien_neu"] == 0,
      (st2["ergebnis"], st2["dateien_neu"]))
(Q / "pg_alter.sql").unlink()
st3 = I.lauf([str(Q)], prozesse=2)
g = S.graph_lesen()
check("Geloeschte Datei ausgetragen, FK weg", st3["entfernt"] == 1 and
      ("public.auftrag", "public.kunde", "fk") not in kanten(), (st3["entfernt"], st3["ergebnis"]))
g.close()
(Q / "pg_alter.sql").write_text(PG2)
I.lauf([str(Q)], prozesse=2)

# Abbruch beim Ableiten: alter Graph bleibt byte-gleich
vorher = hashlib.md5(S.graph_pfad().read_bytes()).hexdigest()
con = S.roh_oeffnen()
r = S.ableiten(con, abbruch=lambda: True)
con.close()
check("Abbruch beim Ableiten meldet abgebrochen", r.get("abgebrochen") is True, r)
check("Abbruch laesst alten Graphen byte-gleich", S.graph_pfad().exists() and
      hashlib.md5(S.graph_pfad().read_bytes()).hexdigest() == vorher)
if not S.graph_pfad().exists():
    I.lauf([str(Q)], nur_ableiten=True)   # damit die Folgeabschnitte messen koennen

# Negativ-Cache: ein Arbeitsprozess "stirbt" an einer Datei
(Q / "kaputt.sql").write_text("CREATE TABLE kaputt (id int);")
_orig = I._Arbeiter.zerlegen


def _stirbt(self, pfad):
    if pfad.endswith("kaputt.sql"):
        return {"pfad": pfad, "ok": False, "fakten": [], "stat": {}, "abgestuerzt": True,
                "fehler": "Arbeitsprozess beendet (Probe)"}
    return _orig(self, pfad)


I._Arbeiter.zerlegen = _stirbt
try:
    sa = I.lauf([str(Q)], prozesse=1)
    sb = I.lauf([str(Q)], prozesse=1)
    sc = I.lauf([str(Q)], prozesse=1)
finally:
    I._Arbeiter.zerlegen = _orig
check("Absturz: erster und zweiter Lauf versuchen die Datei",
      sa["dateien_neu"] == 1 and sb["dateien_neu"] == 1, (sa["dateien_neu"], sb["dateien_neu"]))
check("Nach MAX_VERSUCHE ausgelassen und benannt",
      sc["dateien_neu"] == 0 and any(p.endswith("kaputt.sql") for p in sc["ausgelassen"]),
      (sc["dateien_neu"], sc["ausgelassen"]))
check("Lauf geht trotz Absturz weiter (Graph vorhanden)", sa["ergebnis"] in ("fertig", "unveraendert"),
      sa["ergebnis"])
(Q / "kaputt.sql").write_text("CREATE TABLE kaputt (id int, neu int);")  # Aenderung -> neuer Versuch
sd = I.lauf([str(Q)], prozesse=1)
check("Geaenderte Datei wird wieder versucht", sd["dateien_neu"] == 1 and not sd["ausgelassen"],
      (sd["dateien_neu"], sd["ausgelassen"]))
(Q / "kaputt.sql").unlink()
I.lauf([str(Q)], prozesse=1)

fd = I._sperre_nehmen()
try:
    try:
        I.lauf([str(Q)])
        gesperrt = False
    except I.LaeuftSchon:
        gesperrt = True
finally:
    os.close(fd)
check("Zweiter Lauf bei gehaltener Sperre abgewiesen", gesperrt)

# Bereiche: zwei Gruppen, die nur ueber einen Hub verbunden sind, bleiben zwei
import sqlite3 as _sq
_m = _sq.connect(":memory:")
_m.execute("CREATE TABLE objekt(id INTEGER PRIMARY KEY, name TEXT, bereich INTEGER)")
_m.execute("CREATE TABLE bereich(id INTEGER PRIMARY KEY, name TEXT, groesse INTEGER)")
_n_hub = S.BEREICH_HUB_GRAD + 20
_m.executemany("INSERT INTO objekt VALUES (?,?,NULL)",
               [(1, "mandant")] + [(i, ("auftrag_" if i % 2 else "lager_") + str(i)) for i in range(2, _n_hub + 2)])
_kanten = [(i, 1, "fk", "[]", "[]") for i in range(2, _n_hub + 2)]          # alle -> Hub
_kanten += [(i, i - 2, "fk", "[]", "[]") for i in range(4, _n_hub + 2)]     # zwei Ketten (gerade/ungerade)
_nb = S._bereiche(_m, _n_hub + 1, _kanten)
_b_auftrag = {r[0] for r in _m.execute("SELECT bereich FROM objekt WHERE name LIKE 'auftrag_%'")}
_b_lager = {r[0] for r in _m.execute("SELECT bereich FROM objekt WHERE name LIKE 'lager_%'")}
check("Hub zieht Bereiche nicht zusammen", _nb >= 2 and not (_b_auftrag & _b_lager), (_nb, _b_auftrag, _b_lager))

# ─── 4. GraphRAG-Bausteine ──────────────────────────────────────────────────
print("4. GraphRAG")
g = S.graph_lesen()
tr = R.suche(g, ["anzeigename"])
check("Suche ueber Spaltenkommentar", tr and wert(g, "SELECT schluessel FROM objekt WHERE id=?", (tr[0][0],)) == "public.kunde", tr)
tr = R.suche(g, ["artikel_id"])
check("Suche ueber Spaltennamen", any(wert(g, "SELECT schluessel FROM objekt WHERE id=?", (o,))
                                      == "shop.bestellpos" for o, _ in tr), tr)


def oid(n):
    return wert(g, "SELECT id FROM objekt WHERE schluessel=?", (n,), vorgabe=-1)


# Anker Auftrag und Land – Kunde ist das Join-Glied ohne eigenen Treffer
w = R.auswahl(g, [(oid("public.auftrag"), 9.0), (oid("stamm.land"), 8.0)], 5)
check("Steiner: Join-Glied kunde ergaenzt", oid("public.kunde") in w["verbinder"], w)
alt_hub = R.HUB_GRAD
R.HUB_GRAD = 1   # kunde hat 3 Kanten -> gilt als Hub
p_hub = R.pfad_zu_menge(g, oid("public.auftrag"), {oid("stamm.land")})
p_ziel = R.pfad_zu_menge(g, oid("public.auftrag"), {oid("public.kunde")})
R.HUB_GRAD = alt_hub
check("Hub wird durchquert, aber nicht ausgebreitet", p_hub is None, p_hub)
check("Hub bleibt als Ziel erreichbar", p_ziel == [oid("public.auftrag"), oid("public.kunde")], p_ziel)
kt, _tabs = R.kontext_bauen(g, [oid("public.kunde"), oid("public.auftrag")], ["name"], 2)
zeilen = kt.splitlines()
i_hin = next((i for i, z in enumerate(zeilen) if "2 von 3 gezeigt" in z), -1)
i_sp = next((i for i, z in enumerate(zeilen) if z.strip().startswith("name ")), -1)
check("Kuerzung beziffert und VOR der Liste", 0 <= i_hin < i_sp, kt)
check("Schluessel bleibt trotz Kuerzung", any(z.strip().startswith("id ") for z in zeilen), kt)
check("Join-Bedingung im Kontext", "public.Auftrag.kunde_id = public.kunde.id" in kt, kt)

# ─── 5. Pruefung ────────────────────────────────────────────────────────────
print("5. Pruefung")
FAELLE = [
    ("SELECT k.name, l.bez FROM public.kunde k JOIN stamm.land l ON l.code = k.land_code", True),
    ('SELECT a."AuftragId", k.name FROM public."Auftrag" a, kunde k WHERE a.kunde_id = k.id', True),
    ("WITH x AS (SELECT * FROM kunde) SELECT x.name FROM x", True),
    ("SELECT stamm.bez FROM stamm.land stamm", True),   # Alias heisst wie das Schema (echtes Modell)
    ("SELECT l.bez FROM stamm.land l WHERE EXTRACT(YEAR FROM l.code) = 2025", True),   # echtes Modell
    ("SELECT SUBSTRING(l.bez FROM 1 FOR 3), TRIM(BOTH ' ' FROM l.bez) FROM stamm.land l", True),
    ("SELECT x.n FROM (SELECT k.name AS n FROM kunde k) x", True),
    ("SELECT k.id, (SELECT SYSDATE FROM dual) AS jetzt FROM kunde k", True),   # Oracle-Pseudotabelle
    ("SELECT l.bez FROM stamm.land l WHERE l.code IN (SELECT k.land_code FROM gibtsnicht k)", False),
    ("SELECT 'DELETE; FROM x' AS t, k.id FROM kunde k -- DROP TABLE kunde", True),
    ('SELECT k."Copy" FROM kunde k', False),          # Spalte fehlt – aber KEIN Schluesselwort-Befund
    ("SELECT k.nam FROM kunde k", False),
    ("SELECT * FROM gibtsnicht", False),
    ("DELETE FROM kunde", False),
    ("SELECT 1 FROM kunde; DROP TABLE kunde", False),
    ("SELECT k.id FROM kunde k; SELECT l.code FROM stamm.land l", False),   # nur ';' faengt das
    ("SELECT * INTO neu FROM kunde", False),
    ("SELECT utl_http.request('x') FROM kunde", False),
    ("SELECT k.id FROM kunde k FOR UPDATE", False),
    ("SELECT d.id FROM dublette d", False),
]
for sql, soll in FAELLE:
    pr = R.pruefen(g, sql)
    check(f"{'gilt' if soll else 'abgewiesen'}: {sql[:60]}", pr["ok"] is soll, pr["fehler"])
pr = R.pruefen(g, 'SELECT k."Copy" FROM kunde k')
check("Name in Anfuehrungszeichen ist kein Schluesselwort",
      not any("Schlüsselwort" in f for f in pr["fehler"]), pr["fehler"])
pr = R.pruefen(g, "SELECT k.nam FROM kunde k")
check("Unbekannte Spalte mit Vorschlag", any("ähnlich: name" in f for f in pr["fehler"]), pr["fehler"])

# ─── 6. Kette mit Modell-Attrappe ───────────────────────────────────────────
print("6. Kette")


class Attrappe:
    """Bildet ``_modell(auftrag, system) -> str`` nach und protokolliert."""

    def __init__(self, antworten):
        self.antworten = list(antworten)
        self.auftraege = []

    async def __call__(self, auftrag, system):
        self.auftraege.append((auftrag, system))
        a = self.antworten.pop(0) if self.antworten else self.antworten_rest
        if isinstance(a, Exception):
            raise a
        return a

    antworten_rest = "```sql\nDELETE FROM kunde\n```"


BEGR = '{"begriffe": ["umsatz", "betrag", "land", "auftrag"]}'
FALSCH = "```sql\nSELECT l.bez, sum(a.betrag_x) FROM public.\"Auftrag\" a JOIN public.kunde k ON a.kunde_id=k.id JOIN stamm.land l ON l.code=k.land_code GROUP BY l.bez\n```\nERKLÄRUNG: Umsatz je Land.\nANNAHMEN: keine"
RICHTIG = FALSCH.replace("betrag_x", "betrag")


async def kette():
    m1 = Attrappe([BEGR, FALSCH, RICHTIG])
    e1 = await R.sql_erzeugen("Umsatz je Land", dialekt="postgresql", con=g, modell=m1)
    m2 = Attrappe([BEGR, "BRAUCHE: artikel, bestellposition", "```sql\nSELECT b.id, ar.\"Bez\" FROM shop.bestellpos b JOIN dbo.\"Artikel\" ar ON ar.\"ArtikelID\" = b.artikel_id\n```\nERKLÄRUNG: x"])
    # max_tabellen=3 und keine "Artikel" in der Frage: der Artikel steht im
    # ersten Ausschnitt nachweislich NICHT (eigene Pruefung unten).
    e2 = await R.sql_erzeugen("Umsatz je Land", con=g, modell=m2, max_tabellen=3)
    m5 = Attrappe([BEGR, "BRAUCHE: kunde", RICHTIG])
    e5 = await R.sql_erzeugen("Umsatz je Land", con=g, modell=m5)
    # Zweimal BRAUCHE (live auf DEV gesehen): eine letzte Runde, dann SQL
    m6 = Attrappe([BEGR, "BRAUCHE: kunde", "BRAUCHE: land", RICHTIG])
    e6 = await R.sql_erzeugen("Umsatz je Land", con=g, modell=m6)
    # Dreimal BRAUCHE: dann ehrlich aufgeben, nicht raten
    m7 = Attrappe([BEGR, "BRAUCHE: kunde", "BRAUCHE: land", "BRAUCHE: land"])
    e7 = await R.sql_erzeugen("Umsatz je Land", con=g, modell=m7)
    m3 = Attrappe([BEGR])
    e3 = await R.sql_erzeugen("Umsatz je Land", con=g, modell=m3)
    m4 = Attrappe([RuntimeError("Modell weg"), RICHTIG])
    e4 = await R.sql_erzeugen("Umsatz je Land", con=g, modell=m4)
    return (m1, e1), (m2, e2), (m3, e3), (m4, e4), (m5, e5), (m6, e6), (m7, e7)


(m1, e1), (m2, e2), (m3, e3), (m4, e4), (m5, e5), (m6, e6), (m7, e7) = asyncio.run(kette())
check("Reparatur: zweite Runde besteht", e1.get("pruefung", {}).get("ok") and e1.get("runden") == 2,
      (e1.get("runden"), e1.get("pruefung", {}).get("fehler")))
rep = m1.auftraege[2][0] if len(m1.auftraege) > 2 else ""
check("Reparaturauftrag nennt Befund und Vorschlag",
      "PRÜFUNG FEHLGESCHLAGEN" in rep and "betrag_x" in rep and "ähnlich: betrag" in rep, rep[-400:])
check("Dialekt im Systemprompt", "postgresql" in m1.auftraege[1][1], m1.auftraege[1][1][:120])
check("Join-Glied kunde im ersten Kontext", "TABELLE public.kunde" in m1.auftraege[1][0], m1.auftraege[1][0][:600])
check("Positivkontrolle: Artikel fehlt im ersten Ausschnitt",
      len(m2.auftraege) > 1 and "TABELLE dbo.Artikel" not in m2.auftraege[1][0], m2.auftraege[1][0][:300] if len(m2.auftraege) > 1 else "")
check("BRAUCHE ohne neue Tabelle bricht nicht ab", e5.get("pruefung", {}).get("ok") and
      "keine weiteren Tabellen" in (m5.auftraege[2][0] if len(m5.auftraege) > 2 else ""), (e5.get("fehler"), e5.get("pruefung")))
check("Zweites BRAUCHE: letzte Runde statt Abbruch", e6.get("pruefung", {}).get("ok") and len(m6.auftraege) == 4
      and "nicht mehr möglich" in (m6.auftraege[3][0] if len(m6.auftraege) > 3 else ""),
      (e6.get("fehler"), len(m6.auftraege)))
check("Drittes BRAUCHE: ehrlicher Fehler, keine weitere Runde", bool(e7.get("fehler")) and len(m7.auftraege) == 4,
      (e7.get("fehler"), len(m7.auftraege)))
check("Systemvorgabe nennt Abkuerzungen statt sofort nachzufordern", "abgekürzt" in R.SYSTEM_SQL)
check("Fuellwoerter keine Suchbegriffe", "hoch" not in R.woerter("Wie hoch war der Umsatz") and
      "umsatz" in R.woerter("Wie hoch war der Umsatz"))
check("BRAUCHE-Runde holt Artikel nach", e2.get("pruefung", {}).get("ok") and
      "TABELLE dbo.Artikel" in (m2.auftraege[2][0] if len(m2.auftraege) > 2 else ""),
      (e2.get("pruefung"), e2.get("fehler")))
check("Dauerhaft schreibend: nicht bestanden", e3.get("pruefung", {}).get("ok") is False, e3.get("pruefung"))
check("Reparaturen gedeckelt", len(m3.auftraege) == 1 + 1 + R.MAX_REPARATUR, len(m3.auftraege))
check("Rueckfall ohne Begriffsmodell", e4.get("begriffe_quelle") == "frage" and e4.get("pruefung", {}).get("ok"),
      (e4.get("begriffe_quelle"), e4.get("fehler")))
check("Rueckfall nennt den GRUND (Ausnahme), nicht still", "Modell weg" in e4.get("begriffe_grund", ""),
      e4.get("begriffe_grund"))
check("Ohne Rueckfall kein Grund", e1.get("begriffe_quelle") == "modell" and e1.get("begriffe_grund") == "",
      (e1.get("begriffe_quelle"), e1.get("begriffe_grund")))
_z = e1.get("zeiten") or {}
check("Zeiten je Phase: Begriffe, Graph, je Modellrunde, gesamt",
      set(_z) == {"begriffe", "graph", "modell", "gesamt"} and len(_z.get("modell") or []) == e1.get("runden")
      and all(isinstance(x, float) and x >= 0 for x in [_z.get("begriffe", -1), _z.get("graph", -1),
                                                         _z.get("gesamt", -1)] + list(_z.get("modell") or [])), _z)
# Antwortformen der Begriffsrunde: dieselbe Sache kommt mal so, mal so
for _roh, _soll in (
        ('{"begriffe": ["a1", "b2"]}', ["a1", "b2"]),
        ('```json\n{"begriffe": ["a1"]}\n```\nHinweis: {x} ist kein JSON', ["a1"]),   # Klammern dahinter
        ('{"begriffe": "kunde, auftrag; land"}', ["kunde", "auftrag", "land"]),          # Zeichenkette
        ('["kunde", "land"]', ["kunde", "land"]),                                         # nackte Liste
        # Zeichenkette statt Liste: sonst faende der Listen-Rueckfall ["z9"] auch
        # ohne die Objektsuche – die Probe haette zwei Wege und mass keinen (Register)
        ('Text {kaputt} und dann {"begriffe": "z9"}', ["z9"])):                          # erstes GUELTIGES Objekt
    check(f"Begriffe aus {_roh[:34]!r}", R._begriffe_aus(_roh)[0] == _soll, R._begriffe_aus(_roh))
for _roh, _grund in (("", "leer"), ('{"x": 1}', "kein Feld"), ('{"begriffe": []}', "leer")):
    check(f"Kein Begriff aus {_roh!r}: Grund '{_grund}'", R._begriffe_aus(_roh)[0] == []
          and _grund in R._begriffe_aus(_roh)[1], R._begriffe_aus(_roh))

def E_DOK():
    from backend import schema_graph_einstellungen as _E  # noqa: PLC0415
    return _E.DOK_ENDUNGEN


# ─── 6b. YAML-Objektexporte ─────────────────────────────────────────────────
# Form wie der echte Bestand (gemessen auf DEV 2026-11-07), Namen ERFUNDEN
# (Contoso) – Kundennamen gehoeren nicht ins Repo.
print("6b. YAML")
Y = TMP / "yaml"
(Y / "objekte").mkdir(parents=True)
(Y / "objekte" / "CTS_TABLE_A_KDKND_KUNDE.yaml").write_text("""name: A_KDKND_KUNDE
object_type: TABLE
schema: CTS
comment: Kundenstamm der Contoso
columns:
- name: AKDKND_ID
  type: NUMBER
  length: 22
  precision: 10
  scale: 0
  nullable: false
  comment: Kundennummer
- name: AKDKND_NAME
  type: VARCHAR2
  length: 120
  char_length: 120
  nullable: true
- name: ALLLND_LAND
  type: CHAR
  length: 2
  nullable: true
constraints:
- name: PK_AKDKND
  type: PRIMARY_KEY
  columns: [AKDKND_ID]
""", encoding="utf-8")
(Y / "objekte" / "CTS_TABLE_A_LLLND_LAND.yaml").write_text("""name: A_LLLND_LAND
object_type: TABLE
schema: CTS
columns:
- {name: ALLLND_LAND, type: CHAR, length: 2, nullable: false}
- {name: ALLLND_BEZ, type: VARCHAR2, length: 80, nullable: true, comment: "Bezeichnung: deutsch"}
constraints:
- {name: PK_ALLLND, type: PRIMARY_KEY, columns: [ALLLND_LAND]}
""", encoding="utf-8")
(Y / "objekte" / "CTS_TABLE_V_VKAUF_AUFTRAG.yaml").write_text("""name: V_VKAUF_AUFTRAG
object_type: TABLE
schema: CTS
columns:
- {name: VVKAUF_ID, type: NUMBER, nullable: false}
- {name: AKDKND_ID, type: NUMBER, nullable: true}
- {name: VVKAUF_NETTO, type: NUMBER, precision: 15, scale: 2, nullable: true}
- {name: OBJEKTID, type: NUMBER, nullable: true}
constraints:
- {name: PK_VVKAUF, type: PRIMARY_KEY, columns: [VVKAUF_ID]}
foreign_keys:
- {name: FK_X, delete_rule: CASCADE, columns: [AKDKND_ID], referenced_table: A_KDKND_KUNDE, referenced_columns: [AKDKND_ID]}
""", encoding="utf-8")
(Y / "objekte" / "CTS_TABLE_Z_ZZOBJ_OBJEKT.yaml").write_text("""name: Z_ZZOBJ_OBJEKT
object_type: TABLE
schema: CTS
columns:
- {name: OBJEKTID, type: NUMBER, nullable: false}
constraints:
- {name: PK_O, type: PRIMARY_KEY, columns: [OBJEKTID]}
""", encoding="utf-8")
(Y / "objekte" / "CTS_TABLE_L_LGLOG_PROTOKOLL.yaml").write_text("""name: L_LGLOG_PROTOKOLL
object_type: TABLE
schema: CTS
columns:
- {name: LLGLOG_ID, type: NUMBER, nullable: false}
- {name: ALLLND_LAND, type: CHAR, nullable: true}
- {name: DUPPK_ID, type: NUMBER, nullable: true}
constraints:
- {name: PK_L, type: PRIMARY_KEY, columns: [LLGLOG_ID]}
""", encoding="utf-8")
# Mehrdeutig im SELBEN Schema: zwei Tabellen mit PK DUPPK_ID -> keine Kante
for _n in ("Z_DUP1", "Z_DUP2"):
    (Y / "objekte" / f"CTS_TABLE_{_n}.yaml").write_text(
        f"name: {_n}\nobject_type: TABLE\nschema: CTS\ncolumns:\n- {{name: DUPPK_ID, type: NUMBER}}\n"
        "constraints:\n- {name: P, type: PRIMARY_KEY, columns: [DUPPK_ID]}\n", encoding="utf-8")
# Gleichnamige Tabelle in einem ZWEITEN Schema: der Verweis bleibt im eigenen,
# und die Land-Tabelle verweist nicht ueber ihren eigenen PK auf die andere.
(Y / "objekte" / "ALT_TABLE_A_LLLND_LAND.yaml").write_text(
    "name: A_LLLND_LAND\nobject_type: TABLE\nschema: ALT\ncolumns:\n- {name: ALLLND_LAND, type: CHAR}\n"
    "constraints:\n- {name: P, type: PRIMARY_KEY, columns: [ALLLND_LAND]}\n", encoding="utf-8")
(Y / "objekte" / "CTS_VIEW_V_KUNDE_UMSATZ.yaml").write_text("""name: V_KUNDE_UMSATZ
object_type: VIEW
schema: CTS
comment: Umsatz je Kunde
definition: |-
  SELECT K.AKDKND_NAME AS KUNDE, SUM(A.VVKAUF_NETTO) UMSATZ, K.ALLLND_LAND
  FROM A_KDKND_KUNDE K JOIN V_VKAUF_AUFTRAG A ON A.AKDKND_ID = K.AKDKND_ID
  GROUP BY K.AKDKND_NAME, K.ALLLND_LAND
""", encoding="utf-8")
(Y / "objekte" / "CTS_VIEW_V_ALLES.yaml").write_text("""name: V_ALLES
object_type: VIEW
schema: CTS
definition: SELECT * FROM A_KDKND_KUNDE
""", encoding="utf-8")
# Sicht auf Sicht (Herkunft ueber zwei Stufen) und Sicht mit zwei Sternen
(Y / "objekte" / "CTS_VIEW_V_KUNDE_LAND.yaml").write_text("""name: V_KUNDE_LAND
object_type: VIEW
schema: CTS
definition: SELECT u.KUNDE AS KNAME, u.ALLLND_LAND FROM V_KUNDE_UMSATZ u
""", encoding="utf-8")
(Y / "objekte" / "CTS_VIEW_V_ZWEI.yaml").write_text("""name: V_ZWEI
object_type: VIEW
schema: CTS
definition: SELECT k.*, p.* FROM A_KDKND_KUNDE k, L_LGLOG_PROTOKOLL p
""", encoding="utf-8")
(Y / "objekte" / "CTS_SEQUENCE_X_SEQ.yaml").write_text("name: X_SEQ\nobject_type: SEQUENCE\nschema: CTS\nmin_value: 1\n",
                                                     encoding="utf-8")
(Y / "CTS_SCHEMA_INDEX.yaml").write_text("schema: CTS\nindex_version: '1.0'\ntables:\n- {name: A_KDKND_KUNDE, file: x.yaml}\n",
                                         encoding="utf-8")
(Y / "kaputt.yaml").write_text("name: [unvollstaendig\n", encoding="utf-8")
(Y / "bombe.yaml").write_text("a: &a [x, x, x]\nb: &b [*a, *a, *a]\nc: [*b, *b, *b]\n", encoding="utf-8")
(Y / "anker_im_text.yaml").write_text("name: V_UND\nobject_type: VIEW\nschema: CTS\n"
                                      "definition: \"SELECT 'R &D' AS ABT FROM A_KDKND_KUNDE\"\n", encoding="utf-8")

e = P.datei_zerlegen(str(Y / "objekte" / "CTS_TABLE_A_KDKND_KUNDE.yaml"))
t = erstes(f for f in e["fakten"] if f["art"] == "tabelle") or {}
check("YAML-Tabelle: Name mit Schema, Kommentar", t.get("name") == "CTS.A_KDKND_KUNDE" and t.get("kommentar") ==
      "Kundenstamm der Contoso", t)
sp = {x["name"]: x for x in t.get("spalten") or []}
check("YAML-Spalten: Typ mit Laenge/Stellen, PK, NOT NULL, Kommentar",
      sp.get("AKDKND_ID", {}).get("typ") == "NUMBER(10)" and sp["AKDKND_ID"]["pk"] and not sp["AKDKND_ID"]["null"]
      and sp["AKDKND_ID"]["kommentar"] == "Kundennummer" and sp.get("AKDKND_NAME", {}).get("typ") == "VARCHAR2(120)",
      sp)
e = P.datei_zerlegen(str(Y / "objekte" / "CTS_TABLE_V_VKAUF_AUFTRAG.yaml"))
t = erstes(f for f in e["fakten"] if f["art"] == "tabelle") or {}
check("YAML-Fremdschluessel: Ziel im SELBEN Schema", t.get("fks") == [
    {"von": ["AKDKND_ID"], "ziel": "CTS.A_KDKND_KUNDE", "nach": ["AKDKND_ID"]}], t.get("fks"))
check("NUMBER mit precision+scale", erstes(x["typ"] for x in t.get("spalten") or [] if x["name"] == "VVKAUF_NETTO") == "NUMBER(15,2)")
e = P.datei_zerlegen(str(Y / "objekte" / "CTS_VIEW_V_KUNDE_UMSATZ.yaml"))
v = erstes(f for f in e["fakten"] if f["art"] == "sicht") or {}
check("YAML-Sicht: benutzte Tabellen aus der Definition", v.get("nutzt") == ["A_KDKND_KUNDE", "V_VKAUF_AUFTRAG"], v)
check("YAML-Sicht: Spalten aus Alias, AS-Alias und Spaltenname",
      [x["name"] for x in v.get("spalten") or []] == ["KUNDE", "UMSATZ", "ALLLND_LAND"], v.get("spalten"))
e = P.datei_zerlegen(str(Y / "objekte" / "CTS_VIEW_V_ALLES.yaml"))
check("SELECT * -> KEINE Spaltenliste (eine halbe waere schlimmer als keine)",
      bool(e["fakten"]) and (erstes(f for f in e["fakten"]) or {}).get("spalten") == [], e["fakten"])
for definition, soll in (
        ("SELECT a.x, t.* FROM t a", []),                                         # t.* nicht bestimmbar
        ("SELECT a.x, COUNT(*) FROM t a GROUP BY a.x", []),                       # Ausdruck ohne Alias
        ("SELECT CASE WHEN a=1 THEN 2 END FROM t", []),                           # END ist kein Alias
        ("WITH c AS (SELECT y FROM t) SELECT c.y AS Y1, 1 eins FROM c", ["Y1", "eins"]),
        ("(SELECT a AS p FROM t) UNION ALL (SELECT b FROM u)", ["p"]),
        ("SELECT DISTINCT t.\"Name x\" FROM t", ["Name x"]),
        ("SELECT a, a FROM t", []),                                               # doppelt
        ("SELECT f(x, ' FROM ') AS g FROM t", ["g"])):
    check(f"sicht_spalten: {definition[:42]!r}", P.sicht_spalten(definition) == soll, P.sicht_spalten(definition))
# Herkunft der Sichtspalten: NUR eindeutige Verweise, sonst nichts
for definition, soll in (
        ("SELECT a.X, a.Y AS Z, b.W FROM t1 a, s.t2 b WHERE a.k = b.k",
         {"spalten": {"x": ["t1", "X"], "z": ["t1", "Y"], "w": ["s.t2", "W"]}, "stern": []}),
        ("SELECT X, Y Z FROM s.t1", {"spalten": {"x": ["s.t1", "X"], "z": ["s.t1", "Y"]}, "stern": []}),
        ("SELECT t1.X FROM s.t1", {"spalten": {"x": ["s.t1", "X"]}, "stern": []}),
        ("SELECT * FROM s.t1", {"spalten": {}, "stern": ["s.t1"]}),
        ("SELECT a.*, b.ID AS BID FROM t1 a JOIN t2 b ON a.k = b.k",
         {"spalten": {"bid": ["t2", "ID"]}, "stern": ["t1"]}),
        ("SELECT X FROM t1 a LEFT OUTER JOIN t2 b ON a.k = b.k", {"spalten": {}, "stern": []}),   # zwei Tabellen
        ("SELECT NVL(a.X, 0) X FROM t1 a", {"spalten": {}, "stern": []}),                        # Ausdruck
        ("SELECT q.X FROM (SELECT X FROM t1) q", {"spalten": {}, "stern": []}),                  # Unterabfrage
        ("SELECT a.X FROM t1 a WHERE a.k = 1 UNION SELECT b.X FROM t2 b", {"spalten": {}, "stern": []}),  # Mengenop.
        ("SELECT X FROM (SELECT X FROM t1) q, t2", {"spalten": {}, "stern": []}),               # Unterabfrage + Tabelle
        ("WITH c AS (SELECT X FROM t1) SELECT c.X FROM c", {"spalten": {}, "stern": []}),        # CTE
        ("SELECT T.ID FROM T_X T WHERE (T.M = SYS_CONTEXT('c', 'm')) WITH CHECK OPTION",
         {"spalten": {"id": ["T_X", "ID"]}, "stern": []}),
        ("SELECT a.X FROM t1 a WHERE a.Y IN (SELECT b.Y FROM t2 b)", {"spalten": {"x": ["t1", "X"]}, "stern": []})):
    _hk = {k: v for k, v in P.sicht_herkunft(definition).items() if k != "tabellen"}
    check(f"sicht_herkunft: {definition[:46]!r}", _hk == soll, _hk)
check("FROM-Liste mit Komma: alle Tabellen (fuer die Sicht-Kanten)",
      P.sicht_herkunft("SELECT r.A FROM s.t1 r,\n t2 a, (SELECT 1 FROM t3) q WHERE a.k = r.k")["tabellen"] == ["s.t1", "t2"],
      P.sicht_herkunft("SELECT r.A FROM s.t1 r,\n t2 a, (SELECT 1 FROM t3) q WHERE a.k = r.k"))
f_ddl = P.zerlege("CREATE VIEW v AS SELECT r.A FROM t1 r, t2 a WHERE a.k = r.k")
check("DDL-Sicht: Komma-Tabelle in 'nutzt'", f_ddl and f_ddl.get("nutzt") == ["t1", "t2"], f_ddl)
f_ddl = P.zerlege("CREATE VIEW v (A, B) AS SELECT * FROM kunde")
check("DDL-Sicht mit eigener Spaltenliste: KEINE Herkunft (Namen gelten positionsweise)",
      f_ddl and f_ddl.get("herkunft") == {"spalten": {}, "stern": []}, f_ddl)
f_ddl = P.zerlege("CREATE VIEW v AS SELECT k.ID, k.NAME AS KNAME FROM kunde k")
check("DDL-Sicht ohne Liste: Spalten und Herkunft aus der Auswahl",
      f_ddl and [x["name"] for x in f_ddl.get("spalten") or []] == ["ID", "KNAME"]
      and f_ddl.get("herkunft", {}).get("spalten") == {"id": ["kunde", "ID"], "kname": ["kunde", "NAME"]}, f_ddl)
e = P.datei_zerlegen(str(Y / "objekte" / "CTS_SEQUENCE_X_SEQ.yaml"))
check("Sequenz: uebersprungen und GEZAEHLT, kein Fehler", e["ok"] and not e["fakten"]
      and e["stat"].get("objekt_uebersprungen") == 1, e)
e = P.datei_zerlegen(str(Y / "CTS_SCHEMA_INDEX.yaml"))
check("Verzeichnisdatei erkannt und uebersprungen", e["ok"] and not e["fakten"] and e["stat"].get("verzeichnis") == 1, e)
e = P.datei_zerlegen(str(Y / "kaputt.yaml"))
check("Kaputtes YAML: Fehler mit Grund, kein Wurf", not e["ok"] and e["fehler"], e)
e = P.datei_zerlegen(str(Y / "bombe.yaml"))
check("Alias-Baum abgewiesen (Speicherschutz)", not e["ok"] and "Alias" in e["fehler"], e)
e = P.datei_zerlegen(str(Y / "anker_im_text.yaml"))
check("'&' im Text: kein Fehlalarm (langsamer Lader, aber gelesen)", e["ok"] and e["fakten"]
      and [x["name"] for x in e["fakten"][0]["spalten"]] == ["ABT"], e)
_alt_max = P.YAML_MAX
P.YAML_MAX = 10
e = P.datei_zerlegen(str(Y / "objekte" / "CTS_TABLE_A_LLLND_LAND.yaml"))
P.YAML_MAX = _alt_max
check("Zu grosse YAML-Datei: Fehler mit Grund statt Speicherlast", not e["ok"] and "groesser" in e["fehler"], e)

# Begleitdokument (erfunden): ein Fachbegriff, den KEIN Bezeichner traegt
(Y / "Konventionen.md").write_text("""# Konventionen der Contoso

## Fachbegriffe
Ein Mandat ist im Haus ein Kundenauftrag. Mandate stehen in CTS.V_VKAUF_AUFTRAG,
der Nettowert in VVKAUF_NETTO.

## Beispiel
```sql
# Zaehlung
SELECT COUNT(*) FROM CTS.V_VKAUF_AUFTRAG
```
""", encoding="utf-8")
e = P.datei_zerlegen(str(Y / "Konventionen.md"))
d0 = erstes(e["fakten"]) or {}
check("Begleitdokument: ein Fakt mit Titel und Abschnitten, Ueberschrift als Kopf",
      e["ok"] and d0.get("art") == "dokument" and d0.get("titel") == "Konventionen"
      and any(t.startswith("[Fachbegriffe]") and "Mandat" in t for t in d0.get("teile") or []), e)
check("'# ...' in einem Codeblock ist keine Ueberschrift", not any(t.startswith("[Zaehlung]") for t in d0.get("teile") or [])
      and any("# Zaehlung" in t for t in d0.get("teile") or []), d0.get("teile"))
(Y / "leer.md").write_text("\n\n", encoding="utf-8")
e = P.datei_zerlegen(str(Y / "leer.md"))
check("Dokument ohne Text: Fehler mit Grund (gescannt?)", not e["ok"] and "kein lesbarer Text" in e["fehler"], e)
(Y / "leer.md").unlink()
lang = P.dokument_teile([("kopf", "K"), ("text", "wort " * 700), ("text", "rest")])
check("Abschnitte gedeckelt (DOK_TEIL), Kopf an jedem Teil", all(len(t) <= P.DOK_TEIL + 20 for t in lang)
      and all(t.startswith("[K]") for t in lang) and len(lang) >= 3, [len(t) for t in lang])
check("Begleitdokument-Endungen: Einstellungen == Parser", tuple(sorted(E_DOK())) == tuple(sorted(P.DOK_ENDUNGEN)),
      (E_DOK(), P.DOK_ENDUNGEN))
check("Parser-Fassung >= 5 (Herkunft der Sichtspalten, Texterkennung)", P.FASSUNG >= 5, P.FASSUNG)

# Durch den ganzen Lauf, mit der Regel "gleichnamiger Primaerschluessel"
S.ORDNER = TMP / "ablage_yaml"
st = I.lauf([], quellen=[{"id": "y", "ordner": [str(Y)]}], muster="*.yaml,*.md", prozesse=1, ordner_schutz=False)
gy = S.graph_lesen()
if gy is None:
    abbruch("YAML-Lauf ohne Graph: " + str(st.get("fehler")))
def _kante(von, nach):
    # tuple(): die Verbindung liefert sqlite3.Row, und Row == Tupel ist IMMER
    # falsch – die Pruefung waere sonst bei jeder Kante rot gewesen.
    return [tuple(r) for r in gy.execute(
        "SELECT k.art, k.von_spalten FROM kante k JOIN objekt a ON a.id=k.von JOIN objekt b ON b.id=k.nach "
        "WHERE a.schluessel=? AND b.schluessel=?", (von, nach)).fetchall()]
check("YAML-Lauf: Tabellen und Sichten im Graphen", wert(gy, "SELECT count(*) FROM objekt WHERE art='tabelle'") == 8
      and wert(gy, "SELECT count(*) FROM objekt WHERE art='sicht'") == 5, st.get("fehler"))
check("Kaputte/Bomben-Datei steht als Fehler im Status, der Rest ist da", any("kaputt.yaml" in f for f in st["fehler"])
      or st.get("dateien_neu", 0) >= 1, st.get("fehler"))
check("Deklarierter Fremdschluessel als fk", ("fk", '["AKDKND_ID"]') in _kante("cts.v_vkauf_auftrag", "cts.a_kdknd_kunde"),
      _kante("cts.v_vkauf_auftrag", "cts.a_kdknd_kunde"))
check("Gleichnamiger zusammengesetzter PK -> abgeleitete Kante",
      ("abgeleitet", '["ALLLND_LAND"]') in _kante("cts.a_kdknd_kunde", "cts.a_lllnd_land")
      and ("abgeleitet", '["ALLLND_LAND"]') in _kante("cts.l_lglog_protokoll", "cts.a_lllnd_land"),
      (_kante("cts.a_kdknd_kunde", "cts.a_lllnd_land"), _kante("cts.l_lglog_protokoll", "cts.a_lllnd_land")))
check("Allgemeiner PK-Name (OBJEKTID) -> KEINE Kante", not _kante("cts.v_vkauf_auftrag", "cts.z_zzobj_objekt"),
      _kante("cts.v_vkauf_auftrag", "cts.z_zzobj_objekt"))
check("Deklarierter FK wird nicht doppelt abgeleitet", len(_kante("cts.v_vkauf_auftrag", "cts.a_kdknd_kunde")) == 1,
      _kante("cts.v_vkauf_auftrag", "cts.a_kdknd_kunde"))
check("Eigener PK verweist weder auf sich noch auf die gleichnamige Tabelle eines anderen Schemas",
      not _kante("cts.a_lllnd_land", "cts.a_lllnd_land") and not _kante("cts.a_lllnd_land", "alt.a_lllnd_land")
      and not _kante("alt.a_lllnd_land", "cts.a_lllnd_land"))
check("Zweites Schema mit gleichem PK: der Verweis bleibt im EIGENEN Schema",
      not _kante("cts.a_kdknd_kunde", "alt.a_lllnd_land") and _kante("cts.a_kdknd_kunde", "cts.a_lllnd_land"))
check("Mehrdeutiger PK im selben Schema -> KEINE Kante",
      not _kante("cts.l_lglog_protokoll", "cts.z_dup1") and not _kante("cts.l_lglog_protokoll", "cts.z_dup2"))
check("Sichten nehmen an der Regel nicht teil (sie haengen ueber 'sicht')",
      ("abgeleitet", '["ALLLND_LAND"]') not in _kante("cts.v_kunde_umsatz", "cts.a_lllnd_land"),
      _kante("cts.v_kunde_umsatz", "cts.a_lllnd_land"))
check("Sicht haengt an ihren Tabellen", _kante("cts.v_kunde_umsatz", "cts.a_kdknd_kunde")
      and _kante("cts.v_kunde_umsatz", "cts.v_vkauf_auftrag"))
check("Sicht mit Komma-FROM haengt an BEIDEN Tabellen", _kante("cts.v_zwei", "cts.a_kdknd_kunde")
      and _kante("cts.v_zwei", "cts.l_lglog_protokoll"), (_kante("cts.v_zwei", "cts.a_kdknd_kunde"),
                                                          _kante("cts.v_zwei", "cts.l_lglog_protokoll")))
pr = R.pruefen(gy, "SELECT u.KUNDE, u.UMSATZ FROM CTS.V_KUNDE_UMSATZ u")
check("Pruefung kennt die Sicht-Spalten aus der Definition", pr["ok"], pr["fehler"])
pr = R.pruefen(gy, "SELECT u.GIBTSNICHT FROM CTS.V_KUNDE_UMSATZ u")
check("... und weist eine falsche Sicht-Spalte ab", not pr["ok"], pr["fehler"])
pr = R.pruefen(gy, "SELECT x.IRGENDWAS FROM CTS.V_ALLES x")
check("Sicht ohne bestimmbare Spalten: nicht geprueft statt falsch abgewiesen", pr["ok"], pr["fehler"])
pfad = R.pfad_zu_menge(gy, wert(gy, "SELECT id FROM objekt WHERE schluessel='cts.v_vkauf_auftrag'"),
                       {wert(gy, "SELECT id FROM objekt WHERE schluessel='cts.a_lllnd_land'")})
check("Join-Pfad Auftrag -> Land ueber den Kunden (fk + abgeleitet)", pfad is not None and len(pfad) == 3, pfad)
# Join-Pruefung: jede Gleichsetzung zwischen zwei Tabellen gegen die BELEGTEN
# Beziehungen (Anlass: erfundener Join im Durchstich am echten Bestand)
pr = R.pruefen(gy, "SELECT k.AKDKND_NAME FROM CTS.V_VKAUF_AUFTRAG a JOIN CTS.A_KDKND_KUNDE k ON k.AKDKND_ID = a.AKDKND_ID "
                   "JOIN CTS.A_LLLND_LAND l ON l.ALLLND_LAND = k.ALLLND_LAND")
check("Join ueber fk (umgekehrte Richtung) und abgeleitete Beziehung: belegt",
      pr["ok"] and pr["joins_belegt"] == 2 and not pr["unbelegte_joins"], pr)
ERF_SQL = ("SELECT p.LLGLOG_ID FROM CTS.V_VKAUF_AUFTRAG a JOIN CTS.L_LGLOG_PROTOKOLL p ON p.LLGLOG_ID = a.VVKAUF_ID "
           "WHERE a.VVKAUF_ID <= p.LLGLOG_ID")
pr = R.pruefen(gy, ERF_SQL)
check("Erfundener Join: BENANNT, die Abfrage bleibt gueltig",
      pr["ok"] and [u["bedingung"] for u in pr["unbelegte_joins"]] == ["p.LLGLOG_ID = a.VVKAUF_ID"], pr)
check("'<=' ist kein Join", pr["joins_belegt"] == 0 and len(pr["unbelegte_joins"]) == 1, pr)
# Joins ueber Sichten: die Sichtspalte wird auf ihre Basisspalte zurueckgefuehrt
def _herkunft(sicht, spalte):
    return [tuple(r) for r in gy.execute(
        "SELECT b.schluessel, h.basis_spalte_l FROM herkunft h JOIN objekt s ON s.id=h.sicht_id "
        "JOIN objekt b ON b.id=h.basis_id WHERE s.schluessel=? AND h.spalte_l=?", (sicht, spalte)).fetchall()]
check("Positivkontrolle: Herkunft im Graphen (Alias, Spaltenname, Stern, Sicht auf Sicht)",
      _herkunft("cts.v_kunde_umsatz", "kunde") == [("cts.a_kdknd_kunde", "akdknd_name")]
      and _herkunft("cts.v_kunde_umsatz", "alllnd_land") == [("cts.a_kdknd_kunde", "alllnd_land")]
      and _herkunft("cts.v_alles", "*") == [("cts.a_kdknd_kunde", "*")]
      and _herkunft("cts.v_kunde_land", "kname") == [("cts.v_kunde_umsatz", "kunde")],
      (_herkunft("cts.v_kunde_umsatz", "kunde"), _herkunft("cts.v_alles", "*"), _herkunft("cts.v_kunde_land", "kname")))
check("Ausdruck (SUM) hat keine Herkunft", _herkunft("cts.v_kunde_umsatz", "umsatz") == [])
pr = R.pruefen(gy, "SELECT v.KUNDE FROM CTS.V_KUNDE_UMSATZ v JOIN CTS.A_KDKND_KUNDE k ON v.KUNDE = k.AKDKND_NAME")
check("Sicht gegen ihre eigene Basisspalte: belegt", pr["ok"] and pr["joins_belegt"] == 1
      and not pr["unbelegte_joins"] and pr["joins_ungeprueft"] == 0, pr)
pr = R.pruefen(gy, "SELECT l.ALLLND_BEZ FROM CTS.V_KUNDE_UMSATZ u JOIN CTS.A_LLLND_LAND l ON l.ALLLND_LAND = u.ALLLND_LAND")
check("Sichtspalte -> Basis mit abgeleiteter Beziehung: belegt", pr["joins_belegt"] == 1 and not pr["unbelegte_joins"], pr)
pr = R.pruefen(gy, "SELECT a.VVKAUF_ID FROM CTS.V_ALLES x JOIN CTS.V_VKAUF_AUFTRAG a ON a.AKDKND_ID = x.AKDKND_ID")
check("SELECT * -Sicht: Spalte gleichen Namens, Fremdschluessel: belegt", pr["joins_belegt"] == 1
      and not pr["unbelegte_joins"], pr)
pr = R.pruefen(gy, "SELECT l.ALLLND_BEZ FROM CTS.V_KUNDE_LAND v JOIN CTS.A_LLLND_LAND l ON l.ALLLND_LAND = v.ALLLND_LAND")
check("Sicht auf Sicht (zwei Stufen): belegt", pr["joins_belegt"] == 1 and not pr["unbelegte_joins"], pr)
pr = R.pruefen(gy, "SELECT p.LLGLOG_ID FROM CTS.V_ALLES x JOIN CTS.L_LGLOG_PROTOKOLL p ON p.LLGLOG_ID = x.AKDKND_ID")
u0 = erstes(pr["unbelegte_joins"]) or {}
check("Erfundener Join UEBER eine Sicht: benannt, mit der Basistabelle",
      len(pr["unbelegte_joins"]) == 1 and "Sicht auf CTS.A_KDKND_KUNDE.akdknd_id" in u0.get("nach", "")
      and u0.get("nach_id") == wert(gy, "SELECT id FROM objekt WHERE schluessel='cts.a_kdknd_kunde'")
      and "Sicht" not in u0.get("von", "x"), pr)
check("... und die Korrekturrunde bekommt den belegten Weg an der Basis",
      "belegter Weg:" in R.joins_hinweis(gy, pr["unbelegte_joins"]), R.joins_hinweis(gy, pr["unbelegte_joins"]))
pr = R.pruefen(gy, "SELECT a.VVKAUF_ID FROM CTS.V_KUNDE_UMSATZ u JOIN CTS.V_VKAUF_AUFTRAG a ON a.VVKAUF_NETTO = u.UMSATZ")
check("Sichtspalte ohne Herkunft (Ausdruck): ungeprueft, nicht 'unbelegt'", pr["joins_ungeprueft"] == 1
      and not pr["unbelegte_joins"] and pr["joins_belegt"] == 0, pr)
pr = R.pruefen(gy, "SELECT p.LLGLOG_ID FROM CTS.V_ZWEI z JOIN CTS.L_LGLOG_PROTOKOLL p ON p.LLGLOG_ID = z.LLGLOG_ID")
check("Zwei Sterne: die Spalte gibt es nur in EINER Tabelle -> aufgeloest", pr["joins_belegt"] == 1
      and pr["joins_ungeprueft"] == 0, pr)
pr = R.pruefen(gy, "SELECT l.ALLLND_BEZ FROM CTS.V_ZWEI z JOIN CTS.A_LLLND_LAND l ON l.ALLLND_LAND = z.ALLLND_LAND")
check("Zwei Sterne: die Spalte gibt es in BEIDEN -> ungeprueft statt geraten", pr["joins_ungeprueft"] == 1
      and pr["joins_belegt"] == 0 and not pr["unbelegte_joins"], pr)
pr = R.pruefen(gy, "SELECT p.LLGLOG_ID FROM CTS.V_ALLES x JOIN CTS.L_LGLOG_PROTOKOLL p ON p.LLGLOG_ID = x.GIBTSNICHT")
check("Stern-Sicht, Spalte fehlt in der Basis: ungeprueft", pr["joins_ungeprueft"] == 1 and not pr["unbelegte_joins"], pr)
import sqlite3 as _sq0
_gk = _sq0.connect(":memory:")
gy.backup(_gk)
# .get statt [..]: fehlt eine Sicht, soll das FEHLSCHLAGEN, nicht werfen (Register)
_ids = {r[0]: r[1] for r in _gk.execute("SELECT schluessel, id FROM objekt WHERE art='sicht'")}
_va, _vb = _ids.get("cts.v_kunde_land"), _ids.get("cts.v_kunde_umsatz")
if _va is None or _vb is None:
    check("Kreis zwischen zwei Sichten: endet, ungeprueft", False, "Sichten fehlen im Graphen")
else:
    try:
        _gk.execute("DELETE FROM herkunft WHERE sicht_id IN (?, ?)", (_va, _vb))
        _gk.executemany("INSERT INTO herkunft VALUES (?,?,?,?)", [(_va, "alllnd_land", _vb, "alllnd_land"),
                                                                  (_vb, "alllnd_land", _va, "alllnd_land")])
        pr = R.pruefen(_gk, "SELECT l.ALLLND_BEZ FROM CTS.V_KUNDE_LAND v JOIN CTS.A_LLLND_LAND l ON l.ALLLND_LAND = v.ALLLND_LAND")
        check("Kreis zwischen zwei Sichten: endet, ungeprueft", pr["joins_ungeprueft"] == 1, pr)
    except (RecursionError, Exception) as ex:  # noqa: BLE001
        check("Kreis zwischen zwei Sichten: endet, ungeprueft", False, repr(ex)[:200])
try:
    _gk.execute("DROP TABLE herkunft")
except Exception:  # noqa: BLE001 – ohne Tabelle (Graph vor Fassung 4) ist das der gemeinte Zustand
    pass
try:
    pr = R.pruefen(_gk, "SELECT a.VVKAUF_ID FROM CTS.V_ALLES x JOIN CTS.V_VKAUF_AUFTRAG a ON a.AKDKND_ID = x.AKDKND_ID")
    check("Graph vor Fassung 4 (ohne Herkunft): ungeprueft, kein Absturz", pr["ok"] and pr["joins_ungeprueft"] == 1, pr)
except Exception as ex:  # noqa: BLE001 – ein Absturz soll FEHLSCHLAGEN, nicht den Lauf beenden
    check("Graph vor Fassung 4 (ohne Herkunft): ungeprueft, kein Absturz", False, repr(ex))
_gk.close()
pr = R.pruefen(gy, "SELECT o.OBJEKTID FROM CTS.Z_ZZOBJ_OBJEKT o JOIN CTS.V_VKAUF_AUFTRAG a ON a.OBJEKTID = o.OBJEKTID")
check("Gleichnamige Spalte, auf einer Seite Primaerschluessel: belegt", pr["joins_belegt"] == 1
      and not pr["unbelegte_joins"], pr)
pr = R.pruefen(gy, "SELECT p.LLGLOG_ID FROM CTS.L_LGLOG_PROTOKOLL p JOIN CTS.L_LGLOG_PROTOKOLL q ON q.LLGLOG_ID = p.DUPPK_ID")
check("Selbst-Join ohne Beziehung: unbelegt", len(pr["unbelegte_joins"]) == 1, pr)
ERF_TXT = "```sql\n" + ERF_SQL + "\n```\nERKLÄRUNG: x\nANNAHMEN: keine"
BELEGT_TXT = ("```sql\nSELECT p.LLGLOG_ID FROM CTS.L_LGLOG_PROTOKOLL p JOIN CTS.A_LLLND_LAND l ON l.ALLLND_LAND = "
              "p.ALLLND_LAND\n```\nERKLÄRUNG: x\nANNAHMEN: keine")
BEGR_Y = '{"begriffe": ["auftrag", "protokoll", "kunde", "land"]}'


async def _join_kette():
    ma = Attrappe([BEGR_Y, ERF_TXT, BELEGT_TXT])
    ea = await R.sql_erzeugen("Protokoll je Auftrag", con=gy, modell=ma)
    mb = Attrappe([BEGR_Y, ERF_TXT, ERF_TXT])
    eb = await R.sql_erzeugen("Protokoll je Auftrag", con=gy, modell=mb)
    mc = Attrappe([BEGR_Y, ERF_TXT, "```sql\nDELETE FROM x\n```"])
    ec = await R.sql_erzeugen("Protokoll je Auftrag", con=gy, modell=mc)
    return (ma, ea), (mb, eb), (mc, ec)


(ma, ea), (mb, eb), (mc, ec) = asyncio.run(_join_kette())
ja = ma.auftraege[2][0] if len(ma.auftraege) > 2 else ""
check("Kette: eigene Runde fuer den unbelegten Join, mit belegtem Weg",
      "JOIN OHNE BELEG" in ja and "p.LLGLOG_ID = a.VVKAUF_ID" in ja and "belegter Weg:" in ja
      and "ALLLND_LAND" in ja, ja[-700:])
check("Kette: die belegte Fassung gilt", ea.get("pruefung", {}).get("ok") and not ea["pruefung"]["unbelegte_joins"]
      and "A_LLLND_LAND" in ea.get("sql", ""), (ea.get("sql"), ea.get("pruefung")))
check("Kette: bleibt der Join, geht er MIT Vorbehalt hinaus (genau eine Join-Runde)",
      eb.get("pruefung", {}).get("ok") and len(eb["pruefung"]["unbelegte_joins"]) == 1 and len(mb.auftraege) == 3,
      (len(mb.auftraege), eb.get("pruefung")))
check("Kette: verschlechtert die Join-Runde, gilt die gueltige Fassung davor",
      ec.get("pruefung", {}).get("ok") and ec.get("sql", "").startswith("SELECT p.LLGLOG_ID FROM CTS.V_VKAUF_AUFTRAG"),
      (ec.get("sql"), ec.get("pruefung", {}).get("fehler")))
# Begriffsrunde ohne Denken, SQL-Runde mit (Attrappe des Anbieters, echte Signatur)
import types as _ty  # noqa: E402
from backend import llm as _llm  # noqa: E402


class _AnbieterAttrappe(_llm.OpenAICompatibleProvider):
    def __init__(self):
        self.denken_aus = False
        self.gesehen = []

    async def generate_response(self, model, system_prompt, contents, tools=None, reasoning_effort=None,
                                temperature=None):
        self.gesehen.append((self.denken_aus, reasoning_effort))
        return _ty.SimpleNamespace(parts=[_ty.SimpleNamespace(text="ok")])


_anb = []


def _anbieter_fuer_lauf(prompt_tool_calling=None):
    _anb.append(_AnbieterAttrappe())
    return _anb[-1], "m"


_alt_pfl = _llm.provider_fuer_lauf
_llm.provider_fuer_lauf = _anbieter_fuer_lauf
try:
    asyncio.run(R._modell_ohne_denken("a", "s"))
    asyncio.run(R._modell("a", "s"))
finally:
    _llm.provider_fuer_lauf = _alt_pfl
check("Begriffsrunde ohne Denken, SQL-Runde mit, je eigener Anbieter",
      [a.gesehen for a in _anb] == [[(True, "low")], [(False, "low")]], [a.gesehen for a in _anb])
# Standardweg der Kette (ohne uebergebenes Modell): WIRKUNG gemessen, nicht der Text
_a_sql, _a_begr = Attrappe([BELEGT_TXT]), Attrappe([BEGR_Y])
_alt_m, _alt_mo = R._modell, R._modell_ohne_denken
R._modell, R._modell_ohne_denken = _a_sql, _a_begr
try:
    asyncio.run(R.sql_erzeugen("Protokoll je Land", con=gy))
finally:
    R._modell, R._modell_ohne_denken = _alt_m, _alt_mo
check("Kette (Standardweg): Begriffsrunde ohne Denken, SQL-Runde mit",
      [x[1] for x in _a_begr.auftraege] == [R.SYSTEM_BEGRIFFE] and len(_a_sql.auftraege) >= 1
      and all(x[1] != R.SYSTEM_BEGRIFFE for x in _a_sql.auftraege),
      ([x[1][:30] for x in _a_begr.auftraege], [x[1][:30] for x in _a_sql.auftraege]))
check("Systemvorgabe verbietet erfundene Joins", "ERFINDE KEINE" in R.SYSTEM_SQL and "unbelegter Join" in R.SYSTEM_SQL)

# Hauswissen: Suche, Sichtbarkeit, Anker, Kette
check("Dokument im Graphen, dem Schema zugeordnet", wert(gy, "SELECT count(*) FROM dokument WHERE quelle='y'") >= 2,
      wert(gy, "SELECT count(*) FROM dokument"))
hw = R.dokument_suche(gy, ["mandat"])
check("Hauswissen findet den Fachbegriff", hw and "Mandat" in hw[0]["text"] and hw[0]["titel"] == "Konventionen", hw)
check("Hauswissen nur aus GEWAEHLTEN Schemata", R.dokument_suche(gy, ["mandat"], erlaubt={"fremd"}) == []
      and R.dokument_suche(gy, ["mandat"], erlaubt={"y"}) != [])
import sqlite3 as _sq
_alt = _sq.connect(":memory:")
try:
    _leer = R.dokument_suche(_alt, ["mandat"])
except Exception as _e:  # noqa: BLE001 – ein Wurf ist hier der Befund, kein Abbruch des Laufs
    _leer = f"WURF {type(_e).__name__}"
check("Graph ohne Dokument-Tabelle (vor dem Einbau erfasst): kein Hauswissen, kein Fehler", _leer == [], _leer)
_alt.close()
genannt = R.dokument_objekte(gy, hw)
check("Vom Hauswissen beim Namen genannte Tabelle wird Anker",
      wert(gy, "SELECT id FROM objekt WHERE schluessel='cts.v_vkauf_auftrag'") in genannt, genannt)
ht = R.hauswissen_text(R.dokument_suche(gy, ["beispiel", "count"]))
check("Hauswissen als DATEN gekennzeichnet, Codezaun entschaerft", "KEIN Auftrag" in ht and "`" * 3 not in ht
      and "COUNT(*)" in ht, ht[:400])


async def _hw_kette():
    mh = Attrappe(['{"begriffe": ["mandat", "mandate"]}',
                   "```sql\nSELECT COUNT(a.VVKAUF_ID) FROM CTS.V_VKAUF_AUFTRAG a\n```\nERKLÄRUNG: x\nANNAHMEN: keine"])
    eh = await R.sql_erzeugen("Wie viele Mandate gibt es?", con=gy, modell=mh)
    return mh, eh


mh, eh = asyncio.run(_hw_kette())
check("Kette: Begriffsrunde bekommt das Hauswissen zur Frage", "HAUSWISSEN" in (mh.auftraege[0][0] if mh.auftraege else "")
      and "Mandat" in mh.auftraege[0][0], (mh.auftraege[0][0][:300] if mh.auftraege else ""))
sq = mh.auftraege[1][0] if len(mh.auftraege) > 1 else ""
check("Kette: Fachbegriff ohne Bezeichner -> Tabelle ueber das Hauswissen im Ausschnitt",
      "TABELLE CTS.V_VKAUF_AUFTRAG" in sq and "HAUSWISSEN" in sq, sq[:500])
check("Kette: Ergebnis nennt das benutzte Hauswissen", eh.get("pruefung", {}).get("ok")
      and any(h["titel"] == "Konventionen" for h in eh.get("hauswissen") or []), (eh.get("fehler"), eh.get("hauswissen")))
gy.close()

# ─── 6c. Gleichwertige Objekte, Schema-Praefix, Namensnaehe ─────────────────
# Zwei Datenbankschemata in EINER Ablage (wie im echten Bestand ein altes und ein
# neues Datenmodell; Namen erfunden). Gleichwertig = Sicht ueber GENAU einer Tabelle desselben
# Schemas, alle Spalten aus ihr, alle ihre Spalten gezeigt.
print("6c. Gleichwertig / Praefix / Namensnaehe")
Z = TMP / "zwei"
(Z / "o").mkdir(parents=True)


def _tab(schema, name, spalten, kommentar=""):
    sp = "".join(f"- {{name: {c}, type: NUMBER}}\n" for c in spalten)
    (Z / "o" / f"{schema}_TABLE_{name}.yaml").write_text(
        f"name: {name}\nobject_type: TABLE\nschema: {schema}\ncomment: {kommentar or name}\ncolumns:\n{sp}"
        f"constraints:\n- {{name: PK_{name}, type: PRIMARY_KEY, columns: [{spalten[0]}]}}\n", encoding="utf-8")


def _sicht(schema, name, definition, kommentar=""):
    (Z / "o" / f"{schema}_VIEW_{name}.yaml").write_text(
        f"name: {name}\nobject_type: VIEW\nschema: {schema}\ncomment: {kommentar or name}\n"
        f"definition: \"{definition}\"\n", encoding="utf-8")


_tab("NEU", "ABCFAL_T_FAELLE", ["ABCFAL_ID", "ABCFAL_FALLART", "ABCFAL_MANDANT"], "Patientenfaelle")
_sicht("NEU", "ABCFAL_FAELLE", "SELECT t.ABCFAL_ID, t.ABCFAL_FALLART, t.ABCFAL_MANDANT FROM ABCFAL_T_FAELLE t",
       "Patientenfaelle des Mandanten")
_sicht("NEU", "ABCFAL_TEIL", "SELECT t.ABCFAL_ID FROM ABCFAL_T_FAELLE t", "Patientenfaelle kurz")
_sicht("NEU", "ABCFAL_X", "SELECT t.ABCFAL_ID, t.ABCFAL_FALLART, t.ABCFAL_MANDANT, UPPER(t.ABCFAL_FALLART) AS GROSS "
       "FROM ABCFAL_T_FAELLE t", "Patientenfaelle gross")
_tab("NEU", "ABCART_T_FALLART", ["ABCART_ID", "ABCART_BEZ"], "Fallart")
_sicht("NEU", "ABCART_FALLART", "SELECT * FROM ABCART_T_FALLART", "Fallart des Mandanten")
_tab("NEU", "XYZLOG_T_LOG", ["XYZLOG_ID"], "Protokoll")
_sicht("NEU", "XYZLOG_LOG1", "SELECT * FROM XYZLOG_T_LOG", "Protokoll eins")
_sicht("NEU", "XYZLOG_LOG2", "SELECT * FROM XYZLOG_T_LOG", "Protokoll zwei")
_tab("ALT", "P_FALL", ["PFALL_NR", "PFALL_FALLART"], "Patientenfaelle alt")
_sicht("ALT", "V_FAELLE_NEU", "SELECT * FROM NEU.ABCFAL_T_FAELLE", "Patientenfaelle ueber das neue Schema")
for _i in range(1, 8):
    _tab("ALT", f"S_STAMM{_i}", [f"SSTAMM{_i}_ID"], f"Stammdaten {_i}")
_tab("ALT", "P_REZEPT", ["PREZEPT_ID"], "Rezepte")
# Ein Paar ohne Nachbarsichten (sonst kommt die Tabelle als Join-Glied zwischen
# zwei Sichten wieder herein – das ist richtig, misst aber das Zusammenlegen nicht)
_tab("NEU", "QRSPOS_T_POSITION", ["QRSPOS_ID", "QRSPOS_MENGE"], "Rechnungsposition")
_sicht("NEU", "QRSPOS_POSITION", "SELECT p.QRSPOS_ID, p.QRSPOS_MENGE FROM QRSPOS_T_POSITION p",
       "Rechnungsposition des Mandanten")
S.ORDNER = TMP / "ablage_zwei"
st_z = I.lauf([], quellen=[{"id": "z", "ordner": [str(Z)]}], muster="*.yaml", prozesse=1, ordner_schutz=False)
gz = S.graph_lesen()
_zid = {r[0]: r[1] for r in gz.execute("SELECT schluessel, id FROM objekt")} if gz is not None else {}


def zid(n):
    return _zid.get(n.lower(), -1)


# Fehlen die Objekte (z. B. ohne YAML-Weg), ist das ein FAIL dieses Abschnitts –
# kein Abbruch des ganzen Laufs: ein Abbruch ohne Bilanz zaehlt in der
# Gegenprobe nicht als Biss (gemessen 2026-11-08: "YAML-Weg fehlt" -> rc=2).
_z_da = gz is not None and min(zid("neu.abcfal_t_faelle"), zid("neu.abcfal_faelle"), zid("alt.p_fall")) > 0
check("Positivkontrolle: Graph mit zwei Datenbankschemata erfasst", _z_da, (st_z.get("fehler"), sorted(_zid)[:10]))


def _abschnitt_zwei_schemata():
    check("Positivkontrolle: Herkunft der 1:1-Sicht erfasst",
          wert(gz, "SELECT count(*) FROM herkunft WHERE sicht_id=?", (zid("neu.abcfal_faelle"),)) == 3,
          gz.execute("SELECT * FROM herkunft WHERE sicht_id=?", (zid("neu.abcfal_faelle"),)).fetchall())
    alle = list(_zid.values())
    gw = R.gleichwertige(gz, alle)
    check("Gleichwertig: Sicht mit allen Spalten aus EINER Tabelle (Liste und t.*)",
          gw.get(zid("neu.abcfal_t_faelle")) == zid("neu.abcfal_faelle")
          and gw.get(zid("neu.abcart_t_fallart")) == zid("neu.abcart_fallart"), gw)
    check("Nicht gleichwertig: Teilsicht, Ausdrucksspalte, zwei Sichten auf eine Tabelle, anderes Schema",
          set(gw) == {zid("neu.abcfal_t_faelle"), zid("neu.abcart_t_fallart"), zid("neu.qrspos_t_position")},
          {k: v for k, v in gw.items()})
    check("Gleichwertig nur, wenn BEIDE gefunden wurden",
          R.gleichwertige(gz, [zid("neu.abcfal_t_faelle"), zid("alt.p_fall")]) == {})
    zt, zg = R.zusammenlegen(gz, [(zid("neu.abcfal_t_faelle"), 10.0), (zid("alt.p_fall"), 7.0),
                                  (zid("neu.abcfal_faelle"), 5.0)])
    check("Zusammenlegen: Sicht erbt Platz und Punkte der Tabelle, Tabelle faellt weg",
          zt == [(zid("neu.abcfal_faelle"), 10.0), (zid("alt.p_fall"), 7.0)]
          and zg == {zid("neu.abcfal_faelle"): zid("neu.abcfal_t_faelle")}, (zt, zg))
    zt2, zg2 = R.zusammenlegen(gz, [(zid("neu.abcfal_t_faelle"), 10.0), (zid("alt.p_fall"), 7.0)])
    check("Zusammenlegen: allein gefundene Tabelle bleibt (kein Tausch gegen eine ungesuchte Sicht)",
          zt2 == [(zid("neu.abcfal_t_faelle"), 10.0), (zid("alt.p_fall"), 7.0)] and zg2 == {}, (zt2, zg2))
    kz, _tz = R.kontext_bauen(gz, [zid("neu.abcfal_faelle")], ["fallart"], 40, None, zg)
    check("Ausschnitt nennt die zusammengelegte Tabelle an der Sicht",
          "zeigt ALLE Spalten von NEU.ABCFAL_T_FAELLE" in kz and "TABELLE NEU.ABCFAL_T_FAELLE" not in kz, kz)
    _gz_alt = _sq.connect(":memory:")
    _gz_alt.execute("CREATE TABLE kante(von, nach, art, von_spalten, nach_spalten)")
    _gz_alt.execute("CREATE TABLE objekt(id, schema, art)")
    try:
        _r = R.gleichwertige(_gz_alt, [1, 2])
    except Exception as _e:  # noqa: BLE001 – ein Wurf ist hier der Befund
        _r = f"WURF {type(_e).__name__}"
    check("Graph ohne Herkunft: nichts zusammengelegt, kein Fehler", _r == {}, _r)
    _gz_alt.close()

    # Schema-Praefix
    check("Praefix: leer heisst alle", R.praefixe_normal(None) is None and R.praefixe_normal("") is None
          and R.praefixe_normal([]) is None)
    check("Praefix: Gross, ohne Punkt, Liste oder Komma", R.praefixe_normal("alt") == {"ALT"}
          and R.praefixe_normal(["ALT.", " neu "]) == {"ALT", "NEU"} and R.praefixe_normal("ALT,NEU") == {"ALT", "NEU"})
    for _roh in ("ALT;DROP", ["ALT", 3], [f"S{_i}" for _i in range(R.MAX_PRAEFIXE + 1)], {"a": 1}, "a b"):
        try:
            R.praefixe_normal(_roh)
            check(f"Praefix ungueltig wird abgewiesen: {str(_roh)[:30]}", False)
        except ValueError:
            check(f"Praefix ungueltig wird abgewiesen: {str(_roh)[:30]}", True)
    _sch = lambda tr: {gz.execute("SELECT schema FROM objekt WHERE id=?", (o,)).fetchone()[0] for o, _p in tr}  # noqa: E731
    check("Positivkontrolle: Suche ohne Praefix trifft BEIDE Schemata", _sch(R.suche(gz, ["patientenfaelle"])) == {"ALT", "NEU"},
          _sch(R.suche(gz, ["patientenfaelle"])))
    check("Suche mit Praefix: nur dieses Schema", _sch(R.suche(gz, ["patientenfaelle"], praefixe={"ALT"})) == {"ALT"}
          and _sch(R.suche(gz, ["patientenfaelle"], praefixe={"NEU"})) == {"NEU"})
    # Exakter Name aus dem ANDEREN Schema: der Zusatzweg "exakte Namen" in suche()
    # hat einen eigenen Filter. ("p_fall" trifft ueber das Wortteil "fall" auch
    # NEU-Spalten wie FALLART – deshalb wird die ID geprueft, nicht die leere Liste.)
    check("Suche mit Praefix: auch exakte Namenstreffer gefiltert",
          zid("alt.p_fall") not in dict(R.suche(gz, ["p_fall"], praefixe={"NEU"}))
          and zid("alt.p_fall") in dict(R.suche(gz, ["p_fall"], praefixe={"ALT"}))
          and _sch(R.suche(gz, ["p_fall"], praefixe={"NEU"})) <= {"NEU"})

    # Namensnaehe: ein Auszug mit mehr Namen als ``limit``
    _fern = " ." * 60
    _diagramm = {"text": "".join(f"ALT.S_STAMM{_i} Stammdaten{_fern}\n" for _i in range(1, 8))
                 + f"ALT.P_REZEPT Rezepte zur Abrechnung{_fern}"}
    check("Viele Namen, kein Begriff in der Naehe: KEINER zaehlt (nicht die ersten sechs)",
          R.dokument_objekte(gz, [_diagramm]) == [], R.dokument_objekte(gz, [_diagramm]))
    check("Positivkontrolle: alle acht Namen des Auszugs sind im Graphen eindeutig",
          all(zid(f"alt.s_stamm{_i}") > 0 for _i in range(1, 8)) and zid("alt.p_rezept") > 0)
    check("Viele Namen im Auszug: der zur Frage passende zaehlt, nicht der erste",
          R.dokument_objekte(gz, [_diagramm], begriffe=["Rezepte"]) == [zid("alt.p_rezept")],
          R.dokument_objekte(gz, [_diagramm], begriffe=["Rezepte"]))
    _kurz = {"text": "Faelle stehen in NEU.ABCFAL_FAELLE, die Arten in NEU.ABCART_FALLART."}
    check("Wenige Namen im Auszug: alle zaehlen (auch ohne passenden Begriff)",
          R.dokument_objekte(gz, [_kurz], begriffe=["xyz"]) == [zid("neu.abcfal_faelle"), zid("neu.abcart_fallart")])
    check("Genannte Tabelle ausserhalb des Praefixes zaehlt nicht",
          R.dokument_objekte(gz, [_kurz], praefixe={"ALT"}) == [])

    # Kette: Praefix, Mischung, Zusammenlegen
    BEGR_Z = '{"begriffe": ["patientenfaelle", "fallart", "abcfal", "faelle"]}'
    BEGR_P = '{"begriffe": ["rechnungsposition", "position", "menge"]}'
    SQL_P = ("```sql\nSELECT SUM(p.QRSPOS_MENGE) FROM NEU.QRSPOS_POSITION p\n```\nERKLÄRUNG: x\nANNAHMEN: keine")
    SQL_ZWEI = ("```sql\nSELECT f.ABCFAL_FALLART, COUNT(*) FROM NEU.ABCFAL_FAELLE f JOIN ALT.P_FALL p "
                "ON p.PFALL_NR = f.ABCFAL_ID GROUP BY f.ABCFAL_FALLART\n```\nERKLÄRUNG: x\nANNAHMEN: keine")
    SQL_Z = ("```sql\nSELECT f.ABCFAL_FALLART, COUNT(*) FROM NEU.ABCFAL_FAELLE f GROUP BY f.ABCFAL_FALLART\n```\n"
             "ERKLÄRUNG: x\nANNAHMEN: keine")


    async def _z_kette():
        m1 = Attrappe([BEGR_Z, SQL_Z])
        e1 = await R.sql_erzeugen("Patientenfälle je Fallart", con=gz, modell=m1)
        m2 = Attrappe([BEGR_Z, SQL_Z])
        e2 = await R.sql_erzeugen("Patientenfälle je Fallart", con=gz, modell=m2, praefixe={"NEU"})
        m3 = Attrappe([BEGR_Z, SQL_Z])
        e3 = await R.sql_erzeugen("Patientenfälle je Fallart", con=gz, modell=m3, praefixe={"XX"})
        m4 = Attrappe([BEGR_P, SQL_P])
        e4 = await R.sql_erzeugen("Menge der Rechnungspositionen", con=gz, modell=m4)
        # Nachforderung bringt Tabelle UND Sicht: auch dort zusammengelegt
        m5 = Attrappe(['{"begriffe": ["stammdaten"]}', "BRAUCHE: rechnungsposition, position", SQL_P])
        e5 = await R.sql_erzeugen("Stammdaten", con=gz, modell=m5)
        # SQL, das BEIDE Datenbankschemata verbindet
        m6 = Attrappe([BEGR_Z, SQL_ZWEI, SQL_ZWEI])
        e6 = await R.sql_erzeugen("Patientenfälle je Fallart", con=gz, modell=m6)
        return (m1, e1), (m2, e2), (m3, e3), (m4, e4), (m5, e5), (m6, e6)


    (m1z, e1z), (m2z, e2z), (m3z, e3z), (m4z, e4z), (m5z, e5z), (m6z, e6z) = asyncio.run(_z_kette())
    check("Mischung am SQL gemessen: Ausschnitt aus beiden, SQL aus EINEM -> nur NEU",
          len(e1z.get("praefixe_kontext") or {}) == 2 and e1z.get("praefixe_sql") == {"NEU": 1},
          (e1z.get("praefixe_kontext"), e1z.get("praefixe_sql")))
    check("SQL verbindet beide Datenbankschemata -> beide gezaehlt",
          e6z.get("praefixe_sql") == {"ALT": 1, "NEU": 1}, (e6z.get("praefixe_sql"), e6z.get("fehler"),
                                                             (e6z.get("pruefung") or {}).get("fehler")))
    _a5 = m5z.auftraege[2][0] if len(m5z.auftraege) > 2 else ""
    check("Positivkontrolle: Nachforderung brachte die Position in den Ausschnitt", "NEU.QRSPOS_POSITION" in _a5, _a5[-500:])
    check("Nachforderung: Tabelle und Sicht zusammengelegt, Paar gemeldet",
          "TABELLE NEU.QRSPOS_T_POSITION" not in _a5 and "zeigt ALLE Spalten von NEU.QRSPOS_T_POSITION" in _a5
          and {"sicht": "NEU.QRSPOS_POSITION", "tabelle": "NEU.QRSPOS_T_POSITION"} in (e5z.get("gleichwertig") or []),
          (_a5[-500:], e5z.get("gleichwertig")))
    check("Positivkontrolle: Suche trifft Tabelle UND Sicht der Position",
          {zid("neu.qrspos_t_position"), zid("neu.qrspos_position")} <= set(dict(R.suche(gz, ["rechnungsposition", "position"]))))
    check("Kette ohne Praefix: Ausschnitt aus beiden Schemata, gezaehlt", set(e1z.get("praefixe_kontext") or {}) == {"ALT", "NEU"}
          and e1z.get("praefixe") == [], (e1z.get("praefixe_kontext"), e1z.get("fehler")))
    check("Kette: Tabelle UND ihre Sicht gefunden -> nur die Sicht im Ausschnitt, Paar gemeldet",
          "NEU.QRSPOS_POSITION" in (e4z.get("tabellen_kontext") or [])
          and "NEU.QRSPOS_T_POSITION" not in (e4z.get("tabellen_kontext") or [])
          and {"sicht": "NEU.QRSPOS_POSITION", "tabelle": "NEU.QRSPOS_T_POSITION"} in (e4z.get("gleichwertig") or []),
          (e4z.get("tabellen_kontext"), e4z.get("gleichwertig")))
    _az = m4z.auftraege[1][0] if len(m4z.auftraege) > 1 else ""
    check("Kette: das Modell erfaehrt die Gleichwertigkeit im Ausschnitt", "zeigt ALLE Spalten von NEU.QRSPOS_T_POSITION" in _az,
          _az[-600:])
    check("Kette: kam die Tabelle als Join-Glied doch herein, meldet die Antwort KEIN Paar fuer sie",
          not any(g["tabelle"] in (e1z.get("tabellen_kontext") or []) for g in e1z.get("gleichwertig") or []),
          (e1z.get("tabellen_kontext"), e1z.get("gleichwertig")))
    check("Kette mit Praefix NEU: Anker nur aus NEU, Wahl gemeldet",
          e2z.get("praefixe") == ["NEU"] and "ALT.P_FALL" not in (e2z.get("tabellen_kontext") or [])
          and (e2z.get("tabellen_kontext") or []), (e2z.get("tabellen_kontext"), e2z.get("fehler")))
    check("Kette mit unbekanntem Praefix: Fehler mit Grund, keine SQL-Runde",
          "eingegrenzt auf XX" in (e3z.get("fehler") or "") and len(m3z.auftraege) == 1, (e3z, len(m3z.auftraege)))


if _z_da:
    _abschnitt_zwei_schemata()
if gz is not None:
    gz.close()
S.ORDNER = TMP / "ablage"

# ─── 7. Skill ───────────────────────────────────────────────────────────────
print("7. Skill")
# Attrappen mit der ECHTEN Form: backend.agent._actor_cv (ContextVar mit
# (username, privileged)) und backend.main.schema_zugang/_schema_cfg. Der
# echte backend.main-Import schriebe die Live-settings.json zurueck.
import contextvars
_ag = types.ModuleType("backend.agent")
_ag._actor_cv = contextvars.ContextVar("jarvis_actor", default=None)
sys.modules["backend.agent"] = _ag
_ZUGANG = {"darf": True, "erlaubt": {""}, "admin": True}
# Form wie schema_graph_einstellungen.normieren: Dialekt, Muster, Ableiten und
# Hoechstzahlen stehen JE SCHEMA (seit 2026-11-10), gemeinsam nur prozesse und
# index_aus_chat. Zwei Schemata, die sich in jedem Punkt unterscheiden.
_CFG = {"schemata": [{"id": "", "name": "Probe", "dialekt": "postgresql", "dateimuster": "*.sql,*.ddl",
                      "fk_ableiten": True, "max_tabellen": 12, "max_spalten": 40},
                     {"id": "fremd", "name": "Fremd", "dialekt": "oracle", "dateimuster": "*.yaml",
                      "fk_ableiten": False, "max_tabellen": 30, "max_spalten": 25}],
        "prozesse": 1, "index_aus_chat": False}
_mm = types.ModuleType("backend.main")
_mm.schema_zugang = lambda user: dict(_ZUGANG)
_mm._schema_cfg = lambda: dict(_CFG)
_ANGESTOSSEN = []
# ECHTE Signatur: _sql_erfassen_anstossen(cfg=None, nur=None)
_mm._sql_erfassen_anstossen = lambda cfg=None, nur=None: (_ANGESTOSSEN.append(nur), "gestartet")[1]
sys.modules["backend.main"] = _mm

spec = importlib.util.spec_from_file_location("skills.schema_graph.main", ROOT / "skills/schema_graph/main.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
manifest = json.loads((ROOT / "skills/schema_graph/skill.json").read_text())
check("Manifest-Werkzeuge == get_tools()", manifest["tools"] == [t.name for t in M.get_tools()],
      (manifest["tools"], [t.name for t in M.get_tools()]))
check("Vorgabe aus", manifest.get("enabled") is False)
check("Konfiguration NUR im Reiter (kein generisches config_schema)", manifest.get("config_schema") == {},
      manifest.get("config_schema"))
import re as _re
for _datei in ("frontend/js/sql.js", "frontend/js/sql_admin.js"):
    _m = _re.search(r"var DIALEKTE = \[([^\]]*)\]", (ROOT / _datei).read_text())
    _liste = _re.findall(r"'([a-z0-9]+)'", _m.group(1)) if _m else None
    check(f"Dialektliste in {_datei} == Backend", _liste == list(R.DIALEKTE), _liste)
aus = M.ausgabe(e3, "postgresql").splitlines()
check("NICHT BESTANDEN steht in der ersten Zeile", aus and "PRÜFUNG NICHT BESTANDEN" in aus[0], aus[:2])
aus = M.ausgabe(e1, "postgresql").splitlines()
check("GEPRÜFT steht in der ersten Zeile", aus and "GEPRÜFT" in aus[0], aus[:2])
aus = M.ausgabe({**e1, "pruefung": {**e1["pruefung"], "unbelegte_joins": [{"bedingung": "p.x = a.y"}]}},
                "postgresql").splitlines()
check("Join ohne Beleg: VORBEHALT samt Bedingung in der ersten Zeile",
      aus and "MIT VORBEHALT" in aus[0] and "p.x = a.y" in aus[0] and "ANNAHME" in aus[0], aus[:1])
aus = M.ausgabe({**e1, "praefixe": [], "praefixe_sql": {"ALT": 1, "NEU": 2}}, "postgresql")
check("Werkzeug: SQL aus mehreren Datenbankschemata wird benannt, mit Weg (praefix)",
      "mehreren Datenbankschemata" in aus and "ALT 1" in aus and "praefix" in aus, aus[-400:])
aus = M.ausgabe({**e1, "praefixe": [], "praefixe_kontext": {"ALT": 3, "NEU": 4}, "praefixe_sql": {"NEU": 2}},
                "postgresql")
check("Werkzeug: nur der AUSSCHNITT gemischt, das SQL nicht -> kein Hinweis", "mehreren Datenbankschemata" not in aus,
      aus[-300:])
aus = M.ausgabe({**e1, "praefixe": ["NEU"], "praefixe_sql": {"ALT": 1, "NEU": 4}}, "postgresql")
check("Werkzeug: mit gewaehltem Praefix kein Mischhinweis", "mehreren Datenbankschemata" not in aus, aus[-300:])
aus = M.ausgabe({**e1, "gleichwertig": [{"sicht": "NEU.S", "tabelle": "NEU.S_T"}]}, "postgresql")
check("Werkzeug: Zusammengelegtes wird genannt", "NEU.S statt NEU.S_T" in aus, aus[-300:])
_tsql = erstes(t for t in M.get_tools() if t.name == "schema_sql")
check("Werkzeug: Parameter praefix angeboten", "praefix" in (_tsql.parameters_schema().get("properties") or {}))
antwort = asyncio.run(_tsql.execute(frage="x", praefix="A;B", _sql_schemata=[""]))
check("Werkzeug: ungueltiger Praefix abgewiesen, vor jedem Zugriff", "Ungültige Auswahl" in antwort, antwort)
t_idx = erstes(t for t in M.get_tools() if t.name == "schema_index")
t_tab = erstes(t for t in M.get_tools() if t.name == "schema_tabelle")
t_v = erstes(t for t in M.get_tools() if t.name == "schema_verbindung")
t_sql = erstes(t for t in M.get_tools() if t.name == "schema_sql")


async def _als(user, coro_fn):
    """Werkzeug im Lauf-Kontext eines Auftraggebers ausfuehren (wie actor_scope)."""
    marke = _ag._actor_cv.set((user, False)) if user else None
    try:
        return await coro_fn()
    finally:
        if marke is not None:
            _ag._actor_cv.reset(marke)

antwort = asyncio.run(_als(None, lambda: t_tab.execute(name="kunde", _sql_schemata=[""])))
check("Ohne Auftraggeber-Bindung abgewiesen", antwort.startswith("Zugriff verweigert"), antwort)
antwort = asyncio.run(_als("probe", lambda: t_idx.execute(aktion="starten", _sql_schemata=[""])))
check("Erfassen aus dem Chat ohne Schalter abgewiesen", "ausgeschaltet" in antwort and I._thread is None, antwort)
_ZUGANG["admin"] = False
_CFG["index_aus_chat"] = True
antwort = asyncio.run(_als("probe", lambda: t_idx.execute(aktion="starten", _sql_schemata=[""])))
check("Erfassen aus dem Chat nur fuer Administratoren", "nur Administratoren" in antwort and I._thread is None, antwort)
_ZUGANG["admin"] = True
antwort = asyncio.run(_als("probe", lambda: t_idx.execute(aktion="starten", _sql_schemata=[""])))
check("Erfassen aus dem Chat: Admin + Schalter stoesst die EINE Erfassung an",
      "gestartet" in antwort and len(_ANGESTOSSEN) == 1, (antwort, _ANGESTOSSEN))
check("... und zwar NUR fuer das im Chat gewaehlte Schema, das die Antwort beim Namen nennt",
      _ANGESTOSSEN == [{""}] and "Probe" in antwort and "Fremd" not in antwort, (antwort, _ANGESTOSSEN))
_ZUGANG["erlaubt"] = {"", "fremd"}
antwort = asyncio.run(_als("probe", lambda: t_idx.execute(aktion="starten", _sql_schemata=["fremd"])))
check("... ein anderes gewaehltes Schema -> dieses", _ANGESTOSSEN[1:] == [{"fremd"}] and "Fremd" in antwort
      and "Probe" not in antwort, (antwort, _ANGESTOSSEN))
antwort = asyncio.run(_als("probe", lambda: t_idx.execute(aktion="starten", _sql_schemata=[])))
check("... OHNE Auswahl wird nichts erfasst (kein stiller Lauf ueber alle), mit Grund und Weg",
      len(_ANGESTOSSEN) == 2 and "Kein SQL-Schema gewählt" in antwort and "SQL-Schema" in antwort, (antwort, _ANGESTOSSEN))
# Frage aus dem Chat: Dialekt und Hoechstzahlen kommen aus den GEWAEHLTEN Schemata
_gefragt = []
_echt_erzeugen = R.sql_erzeugen


async def _erzeugen_attrappe(frage, dialekt="allgemein", max_tabellen=12, max_spalten=40, con=None, modell=None,
                             erlaubt=None, praefixe=None):
    _gefragt.append((dialekt, max_tabellen, max_spalten, sorted(erlaubt or [])))
    return {"fehler": "Probe"}

R.sql_erzeugen = _erzeugen_attrappe
try:
    for _ausw in ([""], ["fremd"], ["fremd", ""]):
        asyncio.run(_als("probe", lambda: t_sql.execute(frage="x", _sql_schemata=_ausw)))
    asyncio.run(_als("probe", lambda: t_sql.execute(frage="x", dialekt="mysql", _sql_schemata=["fremd"])))
finally:
    R.sql_erzeugen = _echt_erzeugen
if len(_gefragt) != 4:
    abbruch(f"Positivkontrolle: die Frage erreichte die Erzeugung nicht ({_gefragt})")
check("Frage ueber ein Schema: SEIN Dialekt und SEINE Hoechstzahlen",
      _gefragt[0] == ("postgresql", 12, 40, [""]) and _gefragt[1] == ("oracle", 30, 25, ["fremd"]), _gefragt[:2])
check("Frage ueber beide: Dialekt des ersten der Einstellungen, je die groessere Hoechstzahl",
      _gefragt[2] == ("postgresql", 30, 40, ["", "fremd"]), _gefragt[2])
check("Ein ausdruecklich genannter Dialekt gewinnt", _gefragt[3][0] == "mysql", _gefragt[3])
_ZUGANG["erlaubt"] = {""}
_CFG["index_aus_chat"] = False
antwort = asyncio.run(_als("probe", lambda: t_idx.execute(aktion="status", _sql_schemata=[""])))
check("Status nennt die sichtbare Quelle mit Zahlen", "Probe:" in antwort and "Tabellen" in antwort, antwort)
antwort = asyncio.run(_als("probe", lambda: t_tab.execute(name="kunde", _sql_schemata=[""])))
check("schema_tabelle zeigt Spalten und Beziehungen", "land_code" in antwort and "stamm.land" in antwort
      and "public.auftrag" in antwort, antwort)
antwort = asyncio.run(_als("probe", lambda: t_v.execute(von="public.Auftrag", nach="stamm.land", _sql_schemata=[""])))
check("schema_verbindung nennt beide Join-Bedingungen", "kunde_id = public.kunde.id" in antwort
      and "land_code = stamm.land.code" in antwort, antwort)
antwort = asyncio.run(_als("probe", lambda: t_tab.execute(name="kunde", unsinn=1, _sql_schemata=[""])))
check("Unbekannter Parameter benannt", "unsinn" in antwort, antwort)
# Freigabe weg -> jedes Werkzeug weist ab, auch der Status
_ZUGANG.update({"darf": False, "erlaubt": set()})
for _t, _kw in ((t_tab, {"name": "kunde"}), (t_v, {"von": "kunde", "nach": "land"}),
                (t_sql, {"frage": "x"}), (t_idx, {"aktion": "status"})):
    antwort = asyncio.run(_als("probe", lambda: _t.execute(_sql_schemata=[""], **_kw)))
    check(f"Ohne Freigabe abgewiesen: {_t.name}", antwort.startswith("Zugriff verweigert"), antwort)
# Freigabe ja, aber KEINE AUSWAHL -> abgewiesen (nicht leer beantwortet).
# Die Auswahl kommt vom Dispatch (_sql_schemata); fehlt sie, gilt "kein Schema".
_ZUGANG.update({"darf": True, "erlaubt": {""}})
for _ausw in (None, [], ["gibt-es-nicht"], [7]):
    antwort = asyncio.run(_als("probe", lambda: t_tab.execute(name="kunde", _sql_schemata=_ausw)))
    check(f"Ohne gueltige Auswahl abgewiesen ({_ausw!r})",
          antwort.startswith("Zugriff verweigert") and "Kein SQL-Schema" in antwort, antwort)
# Die Auswahl ERWEITERT nichts: gewaehlt ist "", vorhanden nur "fremd"
_ZUGANG.update({"darf": True, "erlaubt": {"fremd"}})
antwort = asyncio.run(_als("probe", lambda: t_tab.execute(name="kunde", _sql_schemata=[""])))
check("Auswahl eines nicht vorhandenen Schemas wird abgewiesen", "Kein SQL-Schema" in antwort, antwort)
# Gewaehlt ist ein anderes vorhandenes Schema -> Tabelle aus "" gibt es "nicht"
_ZUGANG.update({"darf": True, "erlaubt": {"", "fremd"}})
antwort = asyncio.run(_als("probe", lambda: t_tab.execute(name="kunde", _sql_schemata=["fremd"])))
check("Tabelle aus einem NICHT gewaehlten Schema gilt als nicht gefunden", "nicht gefunden" in antwort, antwort)
_ZUGANG.update({"darf": True, "erlaubt": {""}})
g.close()

baum = ast.parse((ROOT / "backend/schema_graph_parser.py").read_text())
fremd = [n for n in ast.walk(baum) if isinstance(n, (ast.Import, ast.ImportFrom)) and (
    (isinstance(n, ast.ImportFrom) and (n.module or "").startswith("backend")) or
    (isinstance(n, ast.Import) and any(a.name.startswith("backend") for a in n.names)))]
check("Regel: Parser importiert nichts aus backend", not fremd, [ast.dump(n) for n in fremd])
baum = ast.parse((ROOT / "backend/schema_graph_index.py").read_text())
mp = [n for n in ast.walk(baum) if isinstance(n, (ast.Import, ast.ImportFrom)) and (
    "multiprocessing" in (getattr(n, "module", "") or "") or "concurrent" in (getattr(n, "module", "") or "")
    or any("multiprocessing" in a.name or "concurrent" in a.name for a in n.names))]
check("Regel: Indexlauf ohne multiprocessing (spawn laedt run_jarvis.py)", not mp,
      [ast.dump(n) for n in mp])

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nBilanz: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
