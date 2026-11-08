#!/usr/bin/env python3
"""Waechter: SQL-Assistent – Freigabe, Schemata, Dateiablage, Auswahl, Oberflaeche.

Seit 2026-11-07 (Vorgabe des Betreibers): KEINE Wissensgruppen-Bindung, KEINE
freie Ordnerwahl. Ein Schema ist ein fester Ordner
``data/sql_schema_graph/<kennung>/``, gefuellt per Upload (Dateien, Ordner,
ZIP); welches Schema eine Frage sieht, ist die AUSWAHL des Benutzers (im Chat
neben den Wissensgruppen, Vorgabe "kein Schema"; auf /sql oben).

Gemessen werden WIRKUNGEN (ausgefuehrt), die Endpunkt-Zusagen als REGELN am
Syntaxbaum:

  1. Einstellungen: Kennungen (vergeben, behalten, Umlaute, doppelt), Ordner je
     Kennung (kein Weg hinaus), Endungen, Altfassung, Auswahl-Schnitt.
  2. Sichtbarkeit im Graphen – zwei Schemata A/B; eine B-Tabelle ist das
     EINZIGE Join-Glied zwischen zwei A-Tabellen (jede Pruefung mit
     Positivkontrolle ohne Filter).
  3. Indexlauf: feste Ordner (``ordner_schutz=False``) tragen Geloeschtes aus,
     die Kommandozeile mit freien Ordnern schuetzt weiter; Nachlauf.
  4. Kette: leere Auswahl endet VOR jedem Modellaufruf.
  5. Dateiablage (``schema_graph_dateien``) im Sandkasten AUSGEFUEHRT:
     Pfadschutz, Verknuepfungen, Ersetzen, Baum, Loeschen, ZIP.
  6. ``main.py`` am AST: Rechte je Endpunkt, Auswahl statt Gruppen, Upload als
     Strom, Loeschen mit Bestaetigung, Erfassung von selbst; ``schema_zugang``
     und ``_schema_quellen`` AUSGEFUEHRT.
  7. Agent und Chat: Angebot nur mit Auswahl, Auswahl hart gesetzt (nicht
     setdefault), Vererbung an Sub-Agenten, WebSocket und Sitzung.
  8. Sandbox: ``data/sql_schema_graph`` fuer Dateiwerkzeuge UND Shell gesperrt
     (AUSGEFUEHRT, mit Positivkontrolle).
  9. Oberflaeche als Regel: Einbindungen, Kachel, Matrix-Spalte, i18n DE/EN.

``backend.config`` nur als Attrappe. Alles in einem Wegwerf-Verzeichnis.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import atexit
import io
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import types
import zipfile
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


def wirft(fn, *a, art=Exception):
    """True, wenn ``fn(*a)`` mit ``art`` wirft – nie selbst werfend (Register)."""
    try:
        fn(*a)
    except art:
        return True
    except Exception:  # noqa: BLE001 – falsche Art zaehlt als "wirft nicht wie verlangt"
        return False
    return False


_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = types.SimpleNamespace(get_skill_states=lambda: {})
sys.modules["backend.config"] = _cfg_mod
try:
    from backend import schema_graph_einstellungen as E
    from backend import schema_graph_store as S
    from backend import schema_graph_index as I
    from backend import schema_graph_rag as R
    from backend import schema_graph_dienst as D
    from backend import schema_graph_dateien as F_
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht ladbar: {e}")

TMP = Path(tempfile.mkdtemp(prefix="test_schema_zugang_"))
atexit.register(shutil.rmtree, TMP, True)

# ─── 1. Einstellungen ───────────────────────────────────────────────────────
print("1. Einstellungen")
check("Graph liegt im festen Ordner unter data/sql_schema_graph/_graph",
      S.ORDNER == ROOT / "data" / "sql_schema_graph" / "_graph" == E.graph_ordner(), S.ORDNER)
check("Basis ist data/sql_schema_graph", E.BASIS == ROOT / "data" / "sql_schema_graph", E.BASIS)
# Ab hier alles im Sandkasten
E.BASIS = TMP / "basis"
S.ORDNER = TMP / "basis" / "_graph"
check("Positivkontrolle: Ordner je Kennung im Sandkasten", E.ordner_fuer("erp") == TMP / "basis" / "erp")
for boese in ("../x", "_graph", "", "ERP", "a/b", ".", "-x", "x" * 49, None, 5):
    check(f"ordner_fuer weist ab: {boese!r}", wirft(E.ordner_fuer, boese, art=ValueError))
cfg, fehler, _h = E.normieren({"schemata": [{"name": "ERP"}, {"name": "Lager & Versand"}, {"name": "Größe"}]})
check("Gueltig ohne Fehler", not fehler, fehler)
check("Kennungen aus dem Namen (Umlaute umgeschrieben)",
      [s["id"] for s in cfg["schemata"]] == ["erp", "lager-versand", "groesse"], cfg["schemata"])
cfg2, fehler, _h = E.normieren({"schemata": [{"id": "erp", "name": "ERP neu"}, {"name": "erp"}]})
check("Umbenennen behaelt die Kennung (= Ordner), neue weicht aus",
      not fehler and [s["id"] for s in cfg2["schemata"]] == ["erp", "erp-2"], (fehler, cfg2["schemata"]))
_, fehler, _ = E.normieren({"schemata": [{"name": "ERP"}, {"name": "erp"}]})
check("Doppelter Name = Fehler", any("doppelt" in f for f in fehler), fehler)
_, fehler, _ = E.normieren({"schemata": [{"id": "../etc", "name": "X"}]})
check("Kennung mit Weg hinaus = Fehler", any("Kennung" in f for f in fehler), fehler)
_, fehler, _ = E.normieren({"schemata": [{"id": "a", "name": "A"}, {"id": "a", "name": "B"}]})
check("Doppelte Kennung = Fehler", any("Kennung" in f for f in fehler), fehler)
_, fehler, _ = E.normieren({"schemata": [{"name": ""}], "max_tabellen": 999, "dialekt": "cobol",
                            "dateimuster": "*.sql;rm -rf", "fk_ableiten": "ja"})
check("Name fehlt/Grenzen/Dialekt/Muster/Typ abgewiesen", len(fehler) == 5, fehler)
for muster in ("*", "foo*.sql", "*.sql,*", "../*.sql"):
    _, fehler, _ = E.normieren({"dateimuster": muster})
    check(f"Muster nur als *.endung: {muster!r} abgewiesen", any("dateimuster" in f for f in fehler), fehler)
cfg3, _, _ = E.normieren({"dateimuster": "*.SQL, *.ddl,*.sql"})
check("Muster klein, ohne Dubletten", cfg3["dateimuster"] == "*.sql,*.ddl", cfg3["dateimuster"])
check("Endungen fuer den Upload", E.endungen(cfg3) == {".sql", ".ddl"}, E.endungen(cfg3))
alt = E.aus_zustand({"quellen": [{"id": "erp", "name": "ERP", "ordner": ["/mnt/x"], "gruppen": ["g1"]}]})
check("Altfassung -> Schema gleicher Kennung, OHNE Ordner und Gruppen",
      alt["schemata"] == [{"id": "erp", "name": "ERP"}] and "quellen" not in alt, alt)
check("Vorgabe: keine Schemata, Muster ohne *.txt", E.VORGABEN["schemata"] == []
      and "txt" not in E.VORGABEN["dateimuster"] and I.STANDARD_MUSTER == E.VORGABEN["dateimuster"])
check("Auswahl: Liste und Zeichenkette, Unbekanntes faellt weg",
      E.auswahl(cfg, ["erp", "fremd", 7, None]) == {"erp"} and E.auswahl(cfg, "erp, groesse,x") == {"erp", "groesse"},
      (E.auswahl(cfg, ["erp", "fremd", 7, None]), E.auswahl(cfg, "erp, groesse,x")))
check("Auswahl: nichts / falscher Typ = leer", E.auswahl(cfg, None) == set() and E.auswahl(cfg, {"erp": 1}) == set()
      and E.auswahl(cfg, []) == set())
gi0 = D.graph_info(None, [{"id": "a", "name": "ERP"}])
check("Ohne Graph: Schemata mit Nullen (frisch angelegt waehlbar)", gi0["vorhanden"] is False
      and gi0["schemata"] == [{"id": "a", "name": "ERP", "tabellen": 0, "sichten": 0, "spalten": 0, "dokumente": 0}], gi0)

# ─── 2. Sichtbarkeit im Graphen ─────────────────────────────────────────────
print("2. Sichtbarkeit")
QA, QB = TMP / "quelle_a", TMP / "quelle_b"
QA.mkdir()
QB.mkdir()
(QA / "a.sql").write_text("""
CREATE TABLE erp.kunde (id int PRIMARY KEY, name varchar(50));
COMMENT ON TABLE erp.kunde IS 'Kundenstamm';
CREATE TABLE erp.lager (id int PRIMARY KEY, ort varchar(50));
CREATE TABLE erp.dublette (id int PRIMARY KEY);
CREATE VIEW erp.v_kunde AS SELECT k.name FROM erp.kunde k JOIN hr.gehalt g ON g.kunde_id = k.id;
""")
(QB / "b.sql").write_text("""
CREATE TABLE hr.gehalt (id int PRIMARY KEY, kunde_id int REFERENCES erp.kunde(id),
  lager_id int REFERENCES erp.lager(id), betrag numeric);
COMMENT ON TABLE hr.gehalt IS 'Geheime Gehaelter';
CREATE TABLE hr.dublette (id int PRIMARY KEY);
""")
QUELLEN = [{"id": "a", "ordner": [str(QA)]}, {"id": "b", "ordner": [str(QB)]}]
st = I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
if st.get("ergebnis") != "fertig":
    abbruch(f"Indexlauf {st.get('ergebnis')}: {st.get('fehler')}")
g = S.graph_lesen()
if g is None:
    abbruch("kein Graph")


def oid(n):
    r = g.execute("SELECT id FROM objekt WHERE schluessel=?", (n,)).fetchone()
    return r[0] if r else -1


A, AB = {"a"}, {"a", "b"}
check("Positivkontrolle: Schemata zugeordnet", g.execute(
    "SELECT quelle FROM objekt WHERE schluessel='hr.gehalt'").fetchone()[0] == "b"
    and g.execute("SELECT quelle FROM objekt WHERE schluessel='erp.kunde'").fetchone()[0] == "a")
geheim = oid("hr.gehalt")
check("Positivkontrolle: Suche ohne Filter findet B", geheim in [o for o, _ in R.suche(g, ["gehalt"])])
check("Suche mit A findet B nicht", geheim not in [o for o, _ in R.suche(g, ["gehalt", "geheime"], erlaubt=A)])
check("Leere Auswahl -> keine Treffer", R.suche(g, ["kunde"], erlaubt=set()) == [])
p_ohne = R.pfad_zu_menge(g, oid("erp.kunde"), {oid("erp.lager")})
p_a = R.pfad_zu_menge(g, oid("erp.kunde"), {oid("erp.lager")}, erlaubt=A)
check("Positivkontrolle: Pfad ueber B-Tabelle existiert", p_ohne == [oid("erp.kunde"), geheim, oid("erp.lager")],
      p_ohne)
check("Nicht gewaehlte Tabelle ist kein Durchgang", p_a is None, p_a)
w = R.auswahl(g, [(oid("erp.kunde"), 9.0), (oid("erp.lager"), 8.0)], 6, erlaubt=A)
check("Steiner-Auswahl ergaenzt kein fremdes Glied", geheim not in w["ids"] and geheim not in w["verbinder"], w)
check("tabelle_laden: fremde Kennung -> None", R.tabelle_laden(g, geheim, A) is None
      and R.tabelle_laden(g, geheim, AB) is not None)
info = D.tabelle_info(g, "hr.gehalt", A)
check("Detail einer B-Tabelle mit A: nicht gefunden, ohne Vorschlag aus B",
      info.get("fehler") == "nicht_gefunden" and "hr.gehalt" not in (info.get("vorschlaege") or []), info)
info = D.tabelle_info(g, "erp.kunde", A)
rein = [k["quelle"] for k in (info.get("tabelle") or {}).get("rein", [])]
check("'Wird referenziert von' ohne B", "tabelle" in info and "hr.gehalt" not in rein, rein)
check("Mehrdeutig nur unter Gewaehltem", R.finde_objekt(g, "dublette", A)[0] != "mehrdeutig"
      and R.finde_objekt(g, "dublette", AB)[0] == "mehrdeutig")
pr = R.pruefen(g, "SELECT k.name, x.betrag FROM erp.kunde k JOIN hr.gehalt x ON x.kunde_id = k.id", A)
check("Pruefung: B-Tabelle ist 'unbekannt'", any("Unbekannte Tabellen: hr.gehalt" in f for f in pr["fehler"]),
      pr["fehler"])
check("Positivkontrolle: mit A+B gilt die Abfrage", R.pruefen(
    g, "SELECT k.name, x.betrag FROM erp.kunde k JOIN hr.gehalt x ON x.kunde_id = k.id", AB)["ok"])
kt, _tabs = R.kontext_bauen(g, [oid("erp.v_kunde")], ["kunde"], 40, A)
check("Sicht-Grundlage ohne B", "hr.gehalt" not in kt and "erp.kunde" in kt, kt)
gi = D.graph_info(A, [{"id": "a", "name": "ERP"}, {"id": "b", "name": "Personal"}])
check("Status nur gewaehlte Schemata", [q["name"] for q in gi["schemata"]] == ["ERP"]
      and gi["schemata"][0]["tabellen"] == 3, gi)
gi = D.graph_info(None, [{"id": "a", "name": "ERP"}, {"id": "b", "name": "Personal"}])
check("Status ohne Filter: alle Schemata (zum Auswaehlen)", [q["name"] for q in gi["schemata"]] == ["ERP", "Personal"], gi)
g.close()

# ─── 3. Indexlauf ───────────────────────────────────────────────────────────
print("3. Indexlauf")
st = I.lauf([], quellen=[{"id": "a", "ordner": [str(QA), str(QB)]}], prozesse=1, ordner_schutz=False)
g = S.graph_lesen()
check("Umzuordnung ohne Dateiaenderung leitet neu ab", st["ergebnis"] == "fertig" and st["dateien_neu"] == 0
      and g.execute("SELECT quelle FROM objekt WHERE schluessel='hr.gehalt'").fetchone()[0] == "a",
      (st["ergebnis"], st["dateien_neu"]))
g.close()
I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)


def bestand(ordner):
    con = S.roh_oeffnen()
    try:
        return con.execute("SELECT count(*) FROM dateien WHERE pfad LIKE ?", (str(ordner) + "/%",)).fetchone()[0]
    finally:
        con.close()


# Freie Ordner (Kommandozeile, Freigaben): ein fehlender Ordner traegt NICHT aus
weg = TMP / "quelle_b_weg"
QB.rename(weg)
st = I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=True)
check("ordner_schutz=True: fehlender Ordner, Bestand bleibt", bestand(QB) == 1 and st["entfernt"] == 0,
      (bestand(QB), st["entfernt"]))
# Feste Ordner: fehlend heisst "noch nichts hochgeladen / geloescht" -> austragen
st = I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
check("ordner_schutz=False: fehlender Ordner wird ausgetragen, ohne Fehler",
      bestand(QB) == 0 and st["entfernt"] == 1 and st["ergebnis"] == "fertig" and not st["fehler"],
      (bestand(QB), st["entfernt"], st["ergebnis"], st["fehler"]))
weg.rename(QB)
I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
(QB / "b.sql").rename(TMP / "b.sql.weg")
st = I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
check("ordner_schutz=False: leerer Ordner (alles geloescht) wird ausgetragen", bestand(QB) == 0 and st["entfernt"] == 1,
      (bestand(QB), st["entfernt"], st["fehler"]))
(TMP / "b.sql.weg").rename(QB / "b.sql")
st = I.lauf([], quellen=[], prozesse=1, ordner_schutz=False)
g = S.graph_lesen()
n_obj = g.execute("SELECT count(*) FROM objekt").fetchone()[0] if g else -1
if g:
    g.close()
check("Alle Schemata entfernt -> Graph leer (nicht stehengeblieben)", st["ergebnis"] in ("fertig", "unveraendert")
      and n_obj == 0, (st["ergebnis"], n_obj))
# Parser-Fassung: ein mit einer ALTEN Fassung erfasster Bestand wird neu gelesen
I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
st = I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
check("Positivkontrolle: unveraenderter Bestand liest nichts neu", st["dateien_neu"] == 0 and st["dateien_gesamt"] >= 2,
      (st["dateien_neu"], st["dateien_gesamt"]))
con = S.roh_oeffnen()
check("Fassung nach dem Lauf vermerkt", S.roh_fassung(con) == I.parser.FASSUNG, S.roh_fassung(con))
S.roh_fassung_setzen(con, I.parser.FASSUNG - 1)
con.commit()
con.close()
st = I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
check("Alte Fassung: ALLE bekannten Dateien neu gelesen, mit Hinweis", st["dateien_neu"] == st["dateien_gesamt"]
      and "Parser-Fassung" in (st.get("hinweis") or ""), (st["dateien_neu"], st["dateien_gesamt"], st.get("hinweis")))
st = I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
check("... und danach wieder inkrementell", st["dateien_neu"] == 0 and not st.get("hinweis"), (st["dateien_neu"], st.get("hinweis")))
con = S.roh_oeffnen()
con.execute("DELETE FROM roh_meta")
con.commit()
con.close()
st = I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
check("Bestand OHNE Fassungsmarke (vor ihrer Einfuehrung erfasst) wird neu gelesen",
      st["dateien_neu"] == st["dateien_gesamt"], (st["dateien_neu"], st["dateien_gesamt"]))

# Nachlauf: ein Anstoss waehrend eines Laufs wird nachgeholt, nicht verworfen
_laeufe = []
_echt = I.lauf


def _langsam(ordner, **kw):
    _laeufe.append(kw.get("quellen"))
    time.sleep(0.3)
    return {"ergebnis": "fertig"}


I.lauf = _langsam
try:
    r1 = I.anstossen([], quellen=[{"id": "x", "ordner": []}], ordner_schutz=False)
    time.sleep(0.05)
    r2 = I.anstossen([], quellen=[{"id": "y", "ordner": []}], ordner_schutz=False)
    r3 = I.anstossen([], quellen=[{"id": "z", "ordner": []}], ordner_schutz=False)
    for _ in range(50):
        if not I._auto_aktiv:
            break
        time.sleep(0.05)
finally:
    I.lauf = _echt
check("anstossen: erst gestartet, dann vorgemerkt", (r1, r2, r3) == ("gestartet", "vorgemerkt", "vorgemerkt"),
      (r1, r2, r3))
check("Nachlauf mit dem LETZTEN Stand, genau einmal", [q[0]["id"] for q in _laeufe] == ["x", "z"],
      [q[0]["id"] for q in _laeufe])
check("Nach dem Nachlauf ist nichts mehr aktiv", I._auto_aktiv is False and I._nachlauf is None)


def _wirft(ordner, **kw):
    _laeufe.append(kw.get("quellen"))
    if len(_laeufe) == 1:
        time.sleep(0.3)
        raise FileNotFoundError("Probe")
    return {"ergebnis": "fertig"}


_laeufe.clear()
I.lauf = _wirft
try:
    I.anstossen([], quellen=[{"id": "x", "ordner": []}])
    time.sleep(0.05)
    I.anstossen([], quellen=[{"id": "y", "ordner": []}])
    for _ in range(50):
        if not I._auto_aktiv:
            break
        time.sleep(0.05)
finally:
    I.lauf = _echt
check("Scheitert ein Lauf, wird der vorgemerkte Nachlauf trotzdem gefahren",
      [q[0]["id"] for q in _laeufe] == ["x", "y"], [q[0]["id"] for q in _laeufe])

# ─── 4. Kette ───────────────────────────────────────────────────────────────
print("4. Kette")
I.lauf([], quellen=QUELLEN, prozesse=1, ordner_schutz=False)
aufrufe = []


async def _modell(auftrag, system):
    aufrufe.append(auftrag)
    return '{"begriffe": ["kunde"]}'

g = S.graph_lesen()
erg = asyncio.run(R.sql_erzeugen("Kunden", con=g, modell=_modell, erlaubt=set()))
check("Leere Auswahl: Fehler vor jedem Modellaufruf, Grund nennt die Auswahl",
      erg.get("fehler") and "Schema" in erg["fehler"] and "Wissensgruppe" not in erg["fehler"] and not aufrufe,
      (erg, aufrufe))
g.close()

# ─── 5. Dateiablage ─────────────────────────────────────────────────────────
print("5. Dateiablage")
END = {".sql", ".ddl"}
SID = "probe"
basis = F_.ordner_anlegen(SID)
check("Positivkontrolle: Ablage im Sandkasten", basis == TMP / "basis" / SID and basis.is_dir(), basis)
check("Ablage 0750", stat.S_IMODE(basis.stat().st_mode) == 0o750, oct(stat.S_IMODE(basis.stat().st_mode)))
for boese in ("../x.sql", "/abs.sql", "a/../b.sql", ".git/x.sql", "a//b.sql", "a\\..\\b.sql", "", "a/.x.sql",
              "/".join(["d"] * 17) + "/x.sql", "a\nb.sql", "x" * 201 + ".sql"):
    check(f"Pfad abgewiesen: {boese[:40]!r}", wirft(F_.zielpfad, SID, boese, art=F_.DateiFehler))
check("Unbekanntes Schema (Kennung) abgewiesen", wirft(F_.zielpfad, "../etc", "x.sql", art=F_.DateiFehler))
draussen = TMP / "draussen"
draussen.mkdir()
(draussen / "wichtig.sql").write_text("bleibt")
os.symlink(draussen, basis / "link")
check("Verknuepfung im Pfad abgewiesen (schreiben)", wirft(F_.zielpfad, SID, "link/neu.sql", art=F_.DateiFehler))
check("Verknuepfung abgewiesen (loeschen)", wirft(F_.loeschen, SID, "link", art=F_.DateiFehler)
      and (draussen / "wichtig.sql").exists())
# Zwei Schranken, mit BENANNTEM Grund (Register): der Aufloese-Riegel faengt
# jeden Weg HINAUS; die Verknuepfungs-Pruefung nennt die richtige Ursache und
# faengt eine Verknuepfung INNERHALB des Schemas – dort liefe das Loeschen
# sonst in rmtree auf einen Link (OSError, im Endpunkt ein 500).
try:
    F_.zielpfad(SID, "link/neu.sql")
    grund = ""
except F_.DateiFehler as e:
    grund = str(e)
check("Grund nennt die Verknuepfung (nicht nur 'ausserhalb')", "Verknüpfung" in grund, grund)
(basis / "link").unlink()
(basis / "echt").mkdir()
(basis / "echt" / "a.sql").write_text("x")
os.symlink(basis / "echt", basis / "innen")
check("Verknuepfung INNERHALB des Schemas: Loeschen sauber abgewiesen (kein OSError)",
      wirft(F_.loeschen, SID, "innen", art=F_.DateiFehler) and (basis / "echt" / "a.sql").exists())
(basis / "innen").unlink()
shutil.rmtree(basis / "echt")
erg = F_.datei_speichern(SID, "erp/stamm/kunde.sql", io.BytesIO(b"CREATE TABLE a (id int);"), END)
ziel = basis / "erp/stamm/kunde.sql"
check("Gespeichert samt Unterordnern", ziel.read_bytes() == b"CREATE TABLE a (id int);"
      and erg == {"pfad": "erp/stamm/kunde.sql", "groesse": 24, "ersetzt": False}, erg)
check("Datei 0640", stat.S_IMODE(ziel.stat().st_mode) == 0o640, oct(stat.S_IMODE(ziel.stat().st_mode)))
erg = F_.datei_speichern(SID, "erp/stamm/kunde.sql", io.BytesIO(b"CREATE TABLE b (id int);"), END)
check("Gleichnamiges ERSETZT (kein _1 daneben)", erg["ersetzt"] is True
      and ziel.read_bytes().startswith(b"CREATE TABLE b") and not list(ziel.parent.glob("kunde_*")),
      (erg, sorted(p.name for p in ziel.parent.iterdir())))
check("Keine Nebendatei liegen geblieben", not [p for p in basis.rglob(".*")], [p.name for p in basis.rglob(".*")])
check("Falsche Endung abgewiesen", wirft(F_.datei_speichern, SID, "x.exe", io.BytesIO(b"x"), END, art=F_.DateiFehler))
check("Datei als Ordnerteil abgewiesen", wirft(F_.datei_speichern, SID, "erp/stamm/kunde.sql/x.sql",
                                               io.BytesIO(b"x"), END, art=F_.DateiFehler))


class _Bricht(io.RawIOBase):
    def readinto(self, b):
        raise OSError("Verbindung weg")


try:
    F_.datei_speichern(SID, "halb.sql", _Bricht(), END)
except OSError:
    pass
check("Abgebrochener Upload hinterlaesst weder Datei noch Nebendatei",
      not (basis / "halb.sql").exists() and not [p for p in basis.rglob(".*")])
F_.datei_speichern(SID, "Alpha.sql", io.BytesIO(b"x"), END)
F_.datei_speichern(SID, "erp/b.ddl", io.BytesIO(b"yy"), END)
(basis / ".versteckt.sql").write_text("z")
b = F_.baum(SID)
pf = [e["pfad"] for e in b["eintraege"]]
check("Baum: Ordner vor Inhalt, alphabetisch, versteckte ausgelassen",
      pf == ["Alpha.sql", "erp", "erp/b.ddl", "erp/stamm", "erp/stamm/kunde.sql"], pf)
check("Baum: Zahlen", b["dateien"] == 3 and b["ordner"] == 2 and b["bytes"] == 1 + 2 + 24 and not b["gekappt"], b)
b2 = F_.baum(SID, limit=2)
check("Baum gekappt: beziffert", b2["gekappt"] and b2["gesamt"] == 5 and len(b2["eintraege"]) == 2, b2)
check("Loeschen ohne Pfad abgewiesen (nie das ganze Schema)", wirft(F_.loeschen, SID, "", art=F_.DateiFehler)
      and basis.is_dir())
check("Loeschen: nicht vorhanden benannt", wirft(F_.loeschen, SID, "gibtsnicht.sql", art=F_.DateiFehler))
# Ordnername mit Leerzeichen am Ende (echter Export auf DEV): Name, kein Rand
erg = F_.datei_speichern(SID, "Export /KB/a.yaml", io.BytesIO(b"x"), END | {".yaml"})
check("Ordner mit Leerzeichen am Ende: angelegt wie benannt", (basis / "Export " / "KB" / "a.yaml").is_file()
      and erg["pfad"] == "Export /KB/a.yaml", erg)
try:
    erg = F_.loeschen(SID, "Export ")
except F_.DateiFehler as _e:   # ein Wurf ist hier der Befund, kein Abbruch (Register)
    erg = {"fehler": str(_e)}
check("... und loeschbar (frueher 'nicht vorhanden')", erg.get("dateien") == 1 and not (basis / "Export ").exists(), erg)
if (basis / "Export ").exists():
    shutil.rmtree(basis / "Export ")
for boese in ("   ", " ..", ".. ", "a/ /b.sql"):
    check(f"Leerraum-Pfad abgewiesen: {boese!r}", wirft(F_.zielpfad, SID, boese, art=F_.DateiFehler))
erg = F_.loeschen(SID, "erp")
check("Ordner samt Inhalt geloescht, Zahl genannt", erg == {"art": "ordner", "dateien": 2}
      and not (basis / "erp").exists() and (basis / "Alpha.sql").exists(), erg)
erg = F_.loeschen(SID, "Alpha.sql")
check("Datei geloescht", erg == {"art": "datei", "dateien": 1} and not (basis / "Alpha.sql").exists(), erg)
# ZIP
F_.datei_speichern(SID, "dumps/kunde.sql", io.BytesIO(b"alt"), END)
puf = io.BytesIO()
with zipfile.ZipFile(puf, "w") as zf:
    zf.writestr("kunde.sql", "neu")
    zf.writestr("sub/auftrag.ddl", "CREATE TABLE auftrag (id int);")
    zf.writestr("../boese.sql", "x")
    zf.writestr("/abs.sql", "x")
    zf.writestr("__MACOSX/._kunde.sql", "x")
    zf.writestr("sub/.hidden.sql", "x")
    zf.writestr("liesmich.txt", "x")
    zi = zipfile.ZipInfo("link.sql")
    zi.external_attr = (stat.S_IFLNK | 0o777) << 16
    zf.writestr(zi, "/etc/passwd")
puf.seek(0)
gesp, abgl = F_.zip_entpacken(SID, "dumps", puf, END)
check("ZIP: entpackt in den Ordner des Archivs", sorted(x["pfad"] for x in gesp) == ["dumps/kunde.sql",
                                                                                     "dumps/sub/auftrag.ddl"], gesp)
check("ZIP: gleichnamiger Eintrag ERSETZT", (basis / "dumps/kunde.sql").read_text() == "neu"
      and not list((basis / "dumps").glob("kunde_*")))
namen = {a["name"] for a in abgl}
check("ZIP: Zip-Slip, Verknuepfung, falsches Format abgewiesen und BENANNT",
      {"../boese.sql", "/abs.sql", "link.sql", "liesmich.txt"} <= namen, abgl)
check("ZIP: Metadaten und Versteckte still uebergangen", not any("MACOSX" in n or "hidden" in n for n in namen), namen)
check("ZIP: nichts ausserhalb der Ablage", not (TMP / "basis" / "boese.sql").exists() and not (TMP / "boese.sql").exists()
      and not Path("/abs.sql").exists())
puf.seek(0)
gesp, abgl = F_.zip_entpacken(SID, "", puf, END, min_frei=1 << 62)
check("ZIP: Platzreserve greift je Eintrag", not gesp and any("Speicher" in a["grund"] for a in abgl), abgl)
puf.seek(0)
gesp, abgl = F_.zip_entpacken(SID, "", puf, END, max_eintraege=2)
check("ZIP: zu viele Eintraege -> ganzes Archiv abgewiesen", not gesp and "Zu viele" in abgl[0]["grund"], abgl)
gesp, abgl = F_.zip_entpacken(SID, "", io.BytesIO(b"kein zip"), END)
check("ZIP: kaputtes Archiv benannt", not gesp and "ZIP" in abgl[0]["grund"], abgl)
fn = next((n for n in ast.walk(ast.parse((ROOT / "backend/schema_graph_dateien.py").read_text()))
           if isinstance(n, ast.FunctionDef) and n.name == "zip_entpacken"), None)
liest = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr in ("read", "extract", "extractall")] if fn else ["fehlt"]
check("Regel: ZIP-Eintraege als Strom (kein read/extract ins RAM bzw. am Pfadschutz vorbei)",
      fn is not None and not liest and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "datei_speichern"
                                            for n in ast.walk(fn)), liest)
# Basis gehoert einem anderen (von Hand per sudo angelegt): BENANNT, kein 500
if os.geteuid() != 0:
    # Fremder Eigentuemer laesst sich ohne root nicht herstellen: 0555 PLUS ein
    # chmod, das fuer die Basis scheitert (wie bei fremdem Eigentuemer) – sonst
    # setzte ordner_anlegen die Rechte als Eigentuemer einfach zurueck.
    _chmod = os.chmod
    _chmod(E.BASIS, 0o555)

    def _fremd(pfad, modus, *a, **k):
        if Path(pfad) == E.BASIS:
            raise PermissionError(1, "Operation not permitted", str(pfad))
        return _chmod(pfad, modus, *a, **k)
    os.chmod = _fremd
    try:
        try:
            F_.ordner_anlegen("neu-q9")
            grund = ""
        except F_.DateiFehler as e:
            grund = str(e)
        except Exception as e:  # noqa: BLE001
            grund = "WURF " + type(e).__name__
    finally:
        os.chmod = _chmod
        _chmod(E.BASIS, 0o750)
    check("Basis ohne Schreibrecht: DateiFehler mit Eigentuemer und Abhilfe",
          "nicht schreiben" in grund and "Eigentümer" in grund and "chown" in grund, grund)
else:
    check("Basis ohne Schreibrecht (als root nicht messbar – uebersprungen)", True)
soll = sum(len(f) for _d, _u, f in os.walk(basis))
n = F_.schema_loeschen(SID)
check("Schema loeschen: Ordner weg, Zahl genannt", soll >= 3 and n == soll and not basis.exists(), (n, soll))
check("Schema loeschen ohne Ordner: 0", F_.schema_loeschen(SID) == 0)

# ─── 6. main.py als Regel / ausgefuehrt ─────────────────────────────────────
print("6. main.py")
QUELLTEXT = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELLTEXT)
FUNK = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def route(fn):
    for d in fn.decorator_list:
        if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args \
                and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
            return d.func.attr, d.args[0].value
    return None, None


def deps(fn):
    out = set()
    for dflt in list(fn.args.defaults) + [d for d in fn.args.kw_defaults if d is not None]:
        if isinstance(dflt, ast.Call) and getattr(dflt.func, "id", "") == "Depends" and dflt.args:
            out.add(getattr(dflt.args[0], "id", ""))
    return out


def ruft(fn, name):
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == name
               for n in ast.walk(fn))


def nennt(fn, name):
    return any((isinstance(n, ast.Name) and n.id == name) or (isinstance(n, ast.Attribute) and n.attr == name)
               for n in ast.walk(fn))


sql_routen = {(m, p): fn for fn in FUNK.values() for m, p in [route(fn)] if p and p.startswith("/api/sql")}
check("Positivkontrolle: /api/sql-Endpunkte gefunden", len(sql_routen) >= 12, sorted(sql_routen))
for (m, pfad), fn in sorted(sql_routen.items()):
    d = deps(fn)
    if pfad.startswith("/api/sql/admin"):
        check(f"{m.upper()} {pfad}: require_local_auth", d == {"require_local_auth"}, d)
        continue
    check(f"{m.upper()} {pfad}: require_schema_access", d == {"require_schema_access"}, d)
    # /api/sql/status listet die Schemata ZUM AUSWAEHLEN – alles andere sieht nur
    # die Auswahl (frage, suche, tabelle, verbindung).
    if pfad != "/api/sql/status":
        check(f"{m.upper()} {pfad}: sieht nur die Auswahl (_sql_auswahl)", nennt(fn, "_sql_auswahl"), pfad)
check("Keine Wissensgruppen-Bindung mehr in main.py",
      not any(k in FUNK for k in ("_schema_erlaubt", "_sql_wissensgruppen"))
      and "sichtbare_quellen" not in QUELLTEXT, [k for k in ("_schema_erlaubt", "_sql_wissensgruppen") if k in FUNK])
fn = FUNK.get("sql_admin_upload")
f_reads = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "read" and isinstance(n.func.value, ast.Name)] if fn else ["fehlt"]
check("Upload: kein await f.read() (Strom), ZIP ueber zip_entpacken, NICHT _kb_unpack_zip",
      fn is not None and not f_reads and nennt(fn, "zip_entpacken") and not nennt(fn, "_kb_unpack_zip")
      and nennt(fn, "datei_speichern"), f_reads)
check("Upload: Platzreserve vor jeder Datei", fn is not None and nennt(fn, "SQL_UPLOAD_MIN_FREI")
      and ruft(fn, "disk_usage"))
check("Upload/Loeschen stossen die Erfassung an", all(ruft(FUNK.get(k), "_sql_erfassen_anstossen")
                                                      for k in ("sql_admin_upload", "sql_admin_datei_loeschen")))
fn = FUNK.get("sql_admin_speichern")
check("Speichern: normiert, loescht entfernte Schemata NUR mit Bestaetigung",
      fn is not None and ruft(fn, "normieren") and nennt(fn, "schema_loeschen")
      and any(isinstance(n, ast.Constant) and n.value == "loeschen_bestaetigt" for n in ast.walk(fn)))
check("Upload nimmt Begleitdokumente an (upload_endungen, nicht nur das Dateimuster)",
      nennt(FUNK.get("sql_admin_upload"), "upload_endungen"))
check("Erfassung schliesst Begleitdokumente ein (erfassungs_muster)",
      nennt(FUNK.get("_sql_erfassen_anstossen"), "erfassungs_muster"))
check("Verwaltung meldet die Upload-Endungen an den Reiter", nennt(FUNK.get("sql_admin_lesen"), "upload_endungen"))
cfgx, _f, _h = E.normieren({"dateimuster": "*.yaml"})
check("Begleitdokumente: Upload und Erfassung ausgefuehrt", E.upload_endungen(cfgx) == {".yaml", ".md", ".docx", ".pdf"}
      and E.erfassungs_muster(cfgx) == "*.yaml,*.md,*.docx,*.pdf", (E.upload_endungen(cfgx), E.erfassungs_muster(cfgx)))
fn = FUNK.get("_sql_erfassen_anstossen")
kws = {k.arg: getattr(k.value, "value", None) for n in ast.walk(fn) if isinstance(n, ast.Call)
       and getattr(n.func, "attr", "") == "anstossen" for k in n.keywords} if fn else {}
check("Erfassung der festen Ordner mit ordner_schutz=False", kws.get("ordner_schutz") is False, kws)
fn = FUNK.get("sql_page")
check("/sql antwortet ohne Skill 404", fn is not None and ruft(fn, "_skill_active"))
ZR = (ROOT / "backend" / "zugang_regel.py").read_text(encoding="utf-8")
check("Seitenrahmen /sql als Ausnahme 'seite' eingetragen",
      re.search(r'\("GET", "/sql"\): \("seite",', ZR) is not None)
fn = FUNK.get("require_schema_access")
check("require_schema_access prueft Skill UND Freigabe", fn is not None and ruft(fn, "_skill_active")
      and ruft(fn, "_user_may_use_schema"))

# Praedikat AUSFUEHREN (Attrappen mit echter Semantik)
fn = FUNK.get("_user_may_use_schema")
if fn is None:
    abbruch("_user_may_use_schema fehlt")
EINST = {}
ns = {"config": types.SimpleNamespace(get_setting=lambda k, d="": EINST.get(k, d)),
      "_norm_login": lambda u: (u or "").strip().lower().split("\\")[-1],
      "_member_of_any_group": lambda dns, grp: any(x.strip() in dns for x in grp.split("\n") if x.strip()),
      "_user_group_dns_cache": {"anna": ["CN=SQL,OU=Gruppen,DC=firma,DC=local"]}}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "main.py", "exec"), ns)
pr = ns["_user_may_use_schema"]
check("Leer = niemand (auch kein Admin)", pr("jarvis") is False and pr("anna") is False)
EINST["schema_allowed_users"] = "Bert, carla"
check("Liste: bert ja, anna nein", pr("bert") is True and pr("BERT") is True and pr("anna") is False)
EINST["schema_allowed_group"] = "CN=SQL,OU=Gruppen,DC=firma,DC=local"
check("Gruppe: anna ja", pr("anna") is True)
check("Leerer Benutzer nein", pr("") is False)
check("Speichern kennt beide Felder", '"schema_allowed_users" in body' in QUELLTEXT
      and '"schema_allowed_group" in body' in QUELLTEXT)
check('/api/me meldet "schema"', re.search(r'"schema":\s*_user_may_use_schema\(user\) and _skill_active\(_SCHEMA_SKILL\)',
                                           QUELLTEXT) is not None)
# schema_zugang und _schema_quellen AUSFUEHREN
ns2 = {"_SCHEMA_SKILL": "schema_graph", "_FREI": {"bert"}, "_AKTIV": [True]}
ns2.update({"_user_may_use_schema": lambda u: u in ns2["_FREI"], "_skill_active": lambda s: ns2["_AKTIV"][0],
            "_user_is_admin": lambda u: u == "bert",
            "_schema_cfg": lambda: {"schemata": [{"id": "erp", "name": "ERP"}, {"id": "hr", "name": "HR"}]}})
for name in ("schema_zugang", "_schema_quellen"):
    if name not in FUNK:
        abbruch(f"{name} fehlt in main.py")
    exec(compile(ast.Module(body=[FUNK[name]], type_ignores=[]), "main.py", "exec"), ns2)
z = ns2["schema_zugang"]("bert")
check("schema_zugang: freigegeben -> ALLE Schemata waehlbar", z == {"darf": True, "erlaubt": {"erp", "hr"}, "admin": True}, z)
z = ns2["schema_zugang"]("anna")
check("schema_zugang: nicht freigegeben -> nichts", z["darf"] is False and z["erlaubt"] == set(), z)
ns2["_AKTIV"][0] = False
z = ns2["schema_zugang"]("bert")
check("schema_zugang: Skill aus -> nichts", z["darf"] is False and z["erlaubt"] == set(), z)
q = ns2["_schema_quellen"]({"schemata": [{"id": "erp", "name": "ERP"}]})
check("_schema_quellen: je Schema GENAU der feste Ordner", q == [{"id": "erp", "ordner": [str(E.ordner_fuer("erp"))]}], q)

# ─── 7. Agent und Chat ──────────────────────────────────────────────────────
print("7. Agent und Chat")
AGENT = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
AB_ = ast.parse(AGENT)
check("Angebot: ohne Auswahl KEINE schema_-Werkzeuge (vor der Freigabe-Frage)",
      'schema_ok = bool(getattr(self, "_current_sql_schemata", None))' in AGENT
      and "_m._user_may_use_schema(uname) and _m._skill_active(_m._SCHEMA_SKILL)" in AGENT
      and 'if name.startswith("schema_") and not schema_ok:' in AGENT)
setzt = [n for n in ast.walk(AB_) if isinstance(n, ast.Assign) and any(
    isinstance(t, ast.Subscript) and getattr(t.value, "id", "") == "exec_args"
    and isinstance(t.slice, ast.Constant) and t.slice.value == "_sql_schemata" for t in n.targets)]
weich = [n for n in ast.walk(AB_) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "setdefault"
         and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "_sql_schemata"]
check("Dispatch SETZT _sql_schemata hart (das Modell kann die Auswahl nicht erweitern)",
      len(setzt) == 1 and not weich, (len(setzt), len(weich)))
rt = next((n for n in ast.walk(AB_) if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_task"), None)
argn = [a.arg for a in rt.args.args] if rt else []
check("run_task nimmt sql_schemata (Vorgabe: erben)", "sql_schemata" in argn
      and "_SQL_SCHEMATA_UNSET" in AGENT, argn)
check("Sub- und Rollen-Agenten erben die Auswahl",
      AGENT.count('agent._current_sql_schemata = getattr(parent, "_current_sql_schemata", None)') == 2
      and "agent._current_sql_schemata = sql_schemata" in AGENT
      and "sql_schemata=getattr(self, '_current_sql_schemata', None)" in AGENT)
run_calls = [n for n in ast.walk(BAUM) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "run_task"
             and any(k.arg == "kb_groups" for k in n.keywords)]
check("WebSocket reicht die Auswahl an JEDEN run_task mit kb_groups weiter",
      run_calls and all(any(k.arg == "sql_schemata" for k in c.keywords) for c in run_calls), len(run_calls))
check("WebSocket: nur Zeichenketten, fehlt = kein Schema", 'sql_schemata = msg.get("sql_schemata")' in QUELLTEXT
      and "if isinstance(x, str)][:100]" in QUELLTEXT)
check("Sitzung speichert und liefert die Auswahl", ruft(FUNK.get("chat_sessions_save_transcript"), "save_sql_schemata")
      and '"sql_schemata": meta.get("sql_schemata") or []' in QUELLTEXT)
SKILL = (ROOT / "skills/schema_graph/main.py").read_text(encoding="utf-8")
SB_ = ast.parse(SKILL)
ex = [n for n in ast.walk(SB_) if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute"]
check("Jedes Werkzeug nimmt _sql_schemata und reicht es an _zugang",
      len(ex) == 5 and all("_sql_schemata" in [a.arg for a in f.args.args] and any(
          isinstance(c, ast.Call) and any(getattr(a, "id", "") == "_sql_schemata" for a in c.args)
          for c in ast.walk(f)) for f in ex), len(ex))

# ─── 8. Sandbox ─────────────────────────────────────────────────────────────
print("8. Sandbox")
try:
    from backend import sandbox as SBX
except Exception as e:  # noqa: BLE001
    abbruch(f"sandbox nicht ladbar: {e}")
_p = lambda rel: (SBX.PROJECT_ROOT / rel).resolve()
if SBX.is_sensitive(_p("data/rag/beispiel.txt")):
    abbruch("is_sensitive haelt schon einen Wissenspfad fuer sensibel – Abschnitt trivial")
erl, _, _ = SBX.authorize_shell("grep -r suchbegriff data/rag")
if not erl:
    abbruch("authorize_shell verweigert schon eine harmlose Suche – Abschnitt trivial")
check("Positivkontrolle: harmlose Pfade/Befehle frei", True)
for rel in ("data/sql_schema_graph", "data/sql_schema_graph/erp/kunde.sql", "data/sql_schema_graph/_graph/graph.db",
            "data/sql_schema_graph/kuenftig/neu.ddl"):
    check(f"Dateiwerkzeuge: gesperrt {rel}", SBX.is_sensitive(_p(rel)))
for cmd in (f"cat {SBX.PROJECT_ROOT}/data/sql_schema_graph/erp/kunde.sql",
            "cd data && ls sql_schema_graph", "sqlite3 data/sql_schema_graph/_graph/graph.db .dump"):
    erl, _g, marke = SBX.authorize_shell(cmd)
    check(f"Shell: gesperrt {cmd[:60]}", not erl and bool(marke), (erl, marke))

# ─── 9. Oberflaeche ─────────────────────────────────────────────────────────
print("9. Oberflaeche")
F = ROOT / "frontend"
settings = (F / "settings.html").read_text(encoding="utf-8")
sqlhtml = (F / "sql.html").read_text(encoding="utf-8")
chathtml = (F / "chat.html").read_text(encoding="utf-8")
portal = (F / "portal.html").read_text(encoding="utf-8")
check("settings.html bindet sql_admin.js ein", re.search(r'<script src="/static/js/sql_admin\.js\?v=\d+"', settings))
check("sql.html bindet sql.js ein", re.search(r'<script src="/static/js/sql\.js\?v=\d+"', sqlhtml))
check("chat.html bindet sqlschemafilter.js VOR chat.js ein",
      0 <= chathtml.find("/static/js/sqlschemafilter.js?v=") < chathtml.find("/static/js/chat.js?v="))
check("Kachel im Portal", 'id="pt-card-sql" href="/sql"' in portal)
check("Kachel an permissions.schema", "d.permissions.schema" in (F / "js/portal_seite.js").read_text())
check("Reiter-Knopf an Skill (TAB_BUTTONS)", "schema_graph:       'settings-tab-btn-sql'" in (F / "js/skillcfg.js").read_text())
appjs = (F / "js/app.js").read_text()
check("Reiter in allSettingsTabs und Klick-Zweig", "tabSql, tabKundenverwaltung" in appjs and "target === 'sql' && tabSql" in appjs)
check("Matrix-Spalte nur bei aktivem Skill", "_rechteBereich('schema'" in appjs
      and "await updateSchemaSecVisibility();" in appjs)
check("Matrix kennt die Spalte", "sub: 'schema',     users: 'schema-allowed-users'" in (F / "js/rechte_matrix.js").read_text())
sad = (F / "js/settings_ad.js").read_text()
check("Freigabe-Felder lesen/schreiben", "lesen: 'schema_users',            schreiben: 'schema_allowed_users'" in sad
      and "lesen: 'schema_group',            schreiben: 'schema_allowed_group'" in sad)
check("skills.js zieht die Spalte dreimal nach",
      (F / "js/skills.js").read_text().count("window.updateSchemaSecVisibility()") == 3)
chatjs = (F / "js/chat.js").read_text()
check("chat.js schickt sql_schemata nur bei Auswahl und speichert sie je Sitzung",
      "if (_sq.length) msg.sql_schemata = _sq;" in chatjs and "body.sql_schemata = _sqlFilter.getSelection();" in chatjs
      and "_sqlFilter.setSelection((_sdata && _sdata.sql_schemata) || []);" in chatjs)
panel = settings[settings.find('id="settings-tab-sql"'):settings.find('id="settings-tab-tracks"')]
check("Reiter: keine Ordner- und Gruppenfelder mehr", "sqadm-ordner" not in panel and "sqadm-grp" not in panel
      and "sqladm.groups" not in panel and 'id="sqadm-schemata"' in panel)

I18N = (F / "js/i18n.js").read_text(encoding="utf-8")
grenze = I18N.find("\n    en: {")
if grenze < 0:
    abbruch("EN-Block in i18n.js nicht gefunden")
de_keys = set(re.findall(r"^\s+'([\w.]+)':", I18N[:grenze], re.M))
en_keys = set(re.findall(r"^\s+'([\w.]+)':", I18N[grenze:], re.M))
check("Positivkontrolle: i18n gelesen", "sql.title" in de_keys and "sql.title" in en_keys and len(de_keys) > 1000,
      (len(de_keys), len(en_keys)))
benutzt = set()
for quelle in ((F / "js/sql.js").read_text(), (F / "js/sql_admin.js").read_text(),
               (F / "js/sqlschemafilter.js").read_text()):
    benutzt |= set(re.findall(r"\b[Tt]\('((?:sql|sqladm|sqlfilter|common|portal|settings|rmx)\.[\w.]+)'", quelle))
for quelle in (sqlhtml, panel):
    benutzt |= set(re.findall(r'data-i18n(?:-html|-title|-placeholder|-aria)?="([\w.]+)"', quelle))
benutzt |= {"portal.card_sql", "portal.card_sql_desc", "settings.tab.sql", "rmx.col_schema"}
check("Positivkontrolle: Schluessel gesammelt", len(benutzt) > 100
      and {"sqladm.drop", "sqlfilter.btn", "sql.choose_schema"} <= benutzt, len(benutzt))
fehlt_de = sorted(benutzt - de_keys)
fehlt_en = sorted(benutzt - en_keys)
check("Jeder benutzte Schluessel in DE", not fehlt_de, fehlt_de)
check("Jeder benutzte Schluessel in EN", not fehlt_en, fehlt_en)
alt_texte = [k for k in de_keys | en_keys if k in ("sql.no_source", "sql.sources", "sqladm.groups", "sqladm.folders")]
check("Alte Gruppen-/Ordner-Texte entfernt", not alt_texte, alt_texte)

print(f"\nBilanz: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
