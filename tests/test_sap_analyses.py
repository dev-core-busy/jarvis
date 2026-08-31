#!/usr/bin/env python3
"""Tests fuer den SAP-Analysekatalog (``backend/sap_analyses.py``).

Bewusst OHNE fastapi-Import: das Modul ist reine Datenhaltung und muss sich
auch dort pruefen lassen, wo die Web-Abhaengigkeiten fehlen.

    python3 tests/test_sap_analyses.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import sap_analyses as sa  # noqa: E402

_ok = _fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))


print("── Struktur des Katalogs ──")
cat_ids = {c["id"] for c in sa.CATEGORIES}
check("mindestens 20 Analysen", len(sa.ANALYSES) >= 20, str(len(sa.ANALYSES)))
check("Ids eindeutig",
      len({a["id"] for a in sa.ANALYSES}) == len(sa.ANALYSES))
check("jede Analyse in einer bekannten Kategorie",
      all(a["cat"] in cat_ids for a in sa.ANALYSES),
      str([a["id"] for a in sa.ANALYSES if a["cat"] not in cat_ids]))
check("jede Kategorie hat mindestens eine Analyse",
      all(any(a["cat"] == c for a in sa.ANALYSES) for c in cat_ids),
      str([c for c in cat_ids if not any(a["cat"] == c for a in sa.ANALYSES)]))

# Vollstaendigkeit je Eintrag – ein fehlendes Feld faellt sonst erst in der
# Oberflaeche auf, und dort als leerer Kasten ohne Fehlermeldung.
missing = []
for a in sa.ANALYSES:
    for lg in ("de", "en"):
        t = a.get(lg) or {}
        for f in ("title", "desc", "kpis", "task"):
            if not t.get(f):
                missing.append(f"{a['id']}.{lg}.{f}")
    if not a.get("sources"):
        missing.append(f"{a['id']}.sources")
check("alle Pflichtfelder in DE und EN belegt", not missing, str(missing[:6]))

short = [a["id"] for a in sa.ANALYSES
         if len(a["de"]["task"]) < 80 or len(a["en"]["task"]) < 80]
check("jeder Arbeitsauftrag ist ausformuliert (>= 80 Zeichen)", not short, str(short))

nokpi = [a["id"] for a in sa.ANALYSES
         if len(a["de"]["kpis"]) < 3 or len(a["en"]["kpis"]) < 3]
check("mindestens drei Kennzahlen je Analyse", not nokpi, str(nokpi))

# Read-Only ist die zentrale Zusage des Bereichs. Ein Auftrag, der ein
# schreibendes Schluesselwort enthaelt, wuerde das Modell dazu einladen, es zu
# versuchen – der sap_client lehnt zwar ab, aber der Lauf endet dann in einer
# Fehlermeldung statt in einer Auswertung.
WRITE_WORDS = (" INSERT ", " UPDATE ", " DELETE ", " DROP ", " TRUNCATE ",
               " buche ", " schreibe in ", " anlegen in SAP")
bad = [a["id"] for a in sa.ANALYSES
       if any(w.lower() in (a["de"]["task"] + " " + a["en"]["task"]).lower()
              for w in WRITE_WORDS)]
check("kein Auftrag fordert einen Schreibvorgang", not bad, str(bad))

print("\n── BI-Werkzeuge ──")
check("mindestens fuenf Werkzeuge", len(sa.BI_TOOLS) >= 5, str(len(sa.BI_TOOLS)))
check("Werkzeug-Ids eindeutig",
      len({b["id"] for b in sa.BI_TOOLS}) == len(sa.BI_TOOLS))
check("jedes Werkzeug hat eine Aufbereitungsvorgabe in DE und EN",
      all(b.get("export") and b.get("export_en") for b in sa.BI_TOOLS))
# Die Schnittstellennamen muessen exakt denen aus sap_client.reporting_endpoints()
# entsprechen – die Oberflaeche hebt den passenden Eintrag ueber Namensgleichheit
# hervor. Ein Tippfehler faellt sonst nur dadurch auf, dass NICHTS hervorgehoben
# wird, was wie "nicht konfiguriert" aussieht.
KNOWN_IFACES = {"OData Feed", "SAP HANA (SQL/ODBC/JDBC)", "SAP BW / RFC / BEx"}
badif = [b["id"] for b in sa.BI_TOOLS
         if b["iface"] is not None and b["iface"] not in KNOWN_IFACES]
check("Schnittstellennamen decken sich mit reporting_endpoints()", not badif, str(badif))

print("\n── catalog() ──")
for lg, other in (("de", "en"), ("en", "de")):
    c = sa.catalog(lg)
    check(f"catalog('{lg}') meldet die Sprache", c["lang"] == lg)
    check(f"catalog('{lg}') liefert alle Analysen",
          len(c["analyses"]) == len(sa.ANALYSES))
    check(f"catalog('{lg}') liefert Titel in der richtigen Sprache",
          c["analyses"][0]["title"] == sa.ANALYSES[0][lg]["title"])
    check(f"catalog('{lg}') gibt den Arbeitsauftrag NICHT heraus",
          all("task" not in a for a in c["analyses"]))
check("unbekannte Sprache faellt auf Deutsch zurueck", sa.catalog("fr")["lang"] == "de")
check("leere Sprache faellt auf Deutsch zurueck", sa.catalog("")["lang"] == "de")
check("catalog() ohne Argument ist Deutsch", sa.catalog()["lang"] == "de")

print("\n── find() / find_tool() ──")
check("find() findet eine bekannte Analyse", sa.find("ar_aging") is not None)
check("find() liefert None bei Unbekanntem", sa.find("gibtsnicht") is None)
check("find_tool() findet ein bekanntes Werkzeug", sa.find_tool("powerbi") is not None)
check("find_tool() liefert None bei Unbekanntem", sa.find_tool("gibtsnicht") is None)

print("\n── build_task() ──")
check("ohne Vorlage und ohne Frage: leer", sa.build_task() == "")
check("nur Frage genuegt", len(sa.build_task(question="Wie hoch ist der Umsatz?")) > 100)
check("nur Vorlage genuegt", len(sa.build_task(analysis_id="ar_aging")) > 100)
check("unbekannte Vorlage ohne Frage: leer",
      sa.build_task(analysis_id="gibtsnicht") == "")

t = sa.build_task(analysis_id="working_capital", question="Nur Buchungskreis 1000",
                  tool_id="powerbi", instructions="Beträge in TEUR.", lang="de")
check("Auftrag enthaelt den Vorlagentext",
      "Cash Conversion Cycle" in t)
check("Auftrag enthaelt die Frage", "Nur Buchungskreis 1000" in t)
check("Auftrag enthaelt das Zielwerkzeug", "Power BI" in t)
check("Auftrag enthaelt die persoenlichen Anweisungen", "Beträge in TEUR." in t)
check("Auftrag enthaelt die SAP-Quellen", "BSID" in t)
check("Auftrag nennt die Read-Only-Vorgabe", "LESEND" in t)
# Reihenfolge ist Absicht: Spaeteres praezisiert Frueheres. Kippt sie, gewinnt
# im Zweifel die Vorlage gegen die ausdrueckliche Anweisung des Benutzers.
check("Reihenfolge Vorspann < Vorlage < Frage < Werkzeug < Anweisungen",
      t.index("LESEND") < t.index("Cash Conversion Cycle")
      < t.index("Nur Buchungskreis 1000") < t.index("Power BI")
      < t.index("Beträge in TEUR."))

te = sa.build_task(analysis_id="working_capital", tool_id="excel", lang="en")
check("englischer Auftrag ist englisch", "READ-ONLY" in te and "cash conversion cycle" in te.lower())
check("englischer Auftrag nutzt die englische Werkzeugvorgabe",
      "decimal separator" in te)

check("ueberlange Anweisungen werden gekuerzt",
      len(sa.build_task(question="x", instructions="A" * 9000)) < 6000)

print("\n── Sichtbarkeit: normalize_hidden() ──")
check("None → leer", sa.normalize_hidden(None) == [])
check("leere Liste → leer", sa.normalize_hidden([]) == [])
check("Liste bleibt erhalten",
      sa.normalize_hidden(["ar_aging", "hr_kpis"]) == ["ar_aging", "hr_kpis"])
check("kommagetrennter Text wird angenommen",
      sa.normalize_hidden("ar_aging, hr_kpis") == ["ar_aging", "hr_kpis"])
check("unbekannte Ids werden VERWORFEN, nicht geraten",
      sa.normalize_hidden(["ar_aging", "gibtsnicht"]) == ["ar_aging"])
check("Duplikate fallen weg",
      sa.normalize_hidden(["ar_aging", "ar_aging"]) == ["ar_aging"])
check("Unsinn (Zahl) → leer statt Absturz", sa.normalize_hidden(42) == [])
check("Unsinn (dict) → leer statt Absturz", sa.normalize_hidden({"a": 1}) == [])

print("\n── Sichtbarkeit: catalog(hidden=…) ──")
full = sa.catalog("de")
check("ohne hidden ist alles sichtbar (leer = ALLES, nicht NICHTS)",
      len(full["analyses"]) == len(sa.ANALYSES))
c1 = sa.catalog("de", hidden=["ar_aging"])
check("ausgeblendete Analyse fehlt",
      len(c1["analyses"]) == len(sa.ANALYSES) - 1
      and all(a["id"] != "ar_aging" for a in c1["analyses"]))
# Eine Kategorie mit genau einer Analyse: 'production' hat nur production_costs.
c2 = sa.catalog("de", hidden=["production_costs"])
check("leer gewordene Kategorie verschwindet mit",
      all(c["id"] != "production" for c in c2["categories"]),
      str([c["id"] for c in c2["categories"]]))
check("andere Kategorien bleiben",
      any(c["id"] == "finance" for c in c2["categories"]))
c3 = sa.catalog("de", hidden=[a["id"] for a in sa.ANALYSES])
check("alles ausgeblendet: keine Analyse, keine Kategorie",
      c3["analyses"] == [] and c3["categories"] == [])
check("alles ausgeblendet: BI-Werkzeuge bleiben (die Konsole braucht sie)",
      len(c3["bi_tools"]) == len(sa.BI_TOOLS))
check("unbekannte Id in hidden blendet nichts aus",
      len(sa.catalog("de", hidden=["gibtsnicht"])["analyses"]) == len(sa.ANALYSES))

print("\n── Sichtbarkeit: admin_catalog() ──")
ac = sa.admin_catalog("de", hidden=["ar_aging", "hr_kpis"])
check("admin_catalog zeigt ALLE Analysen (sonst nichts einblendbar)",
      len(ac["analyses"]) == len(sa.ANALYSES))
check("admin_catalog behaelt alle Kategorien",
      len(ac["categories"]) == len(sa.CATEGORIES))
check("Merker 'visible' korrekt gesetzt",
      {a["id"] for a in ac["analyses"] if not a["visible"]} == {"ar_aging", "hr_kpis"})
check("admin_catalog meldet die hidden-Liste", ac["hidden"] == ["ar_aging", "hr_kpis"])
check("admin_catalog meldet die Gesamtzahl", ac["total"] == len(sa.ANALYSES))
check("admin_catalog gibt den Arbeitsauftrag NICHT heraus",
      all("task" not in a for a in ac["analyses"]))
check("admin_catalog uebersetzt",
      sa.admin_catalog("en")["analyses"][0]["title"] == sa.ANALYSES[0]["en"]["title"])

print("\n── Sichtbarkeit: is_hidden() ──")
check("is_hidden erkennt eine ausgeblendete Analyse",
      sa.is_hidden("ar_aging", ["ar_aging"]))
check("is_hidden ist False fuer sichtbare", not sa.is_hidden("hr_kpis", ["ar_aging"]))
check("is_hidden ohne Liste ist immer False", not sa.is_hidden("ar_aging", None))


# ══════════════════════════════════════════════════════════════════════════
# Der VORGABE-Produktname darf nicht im Pulldown stehen (2026-08-31)
# ══════════════════════════════════════════════════════════════════════════
# Im Eintrag ``inline`` stand "Jarvis (direkt hier)" – auf einer weiss
# gelabelten Installation also ein Name, den das Branding nicht erreicht.
# Gemessen auf ECHT: der Assistent heisst dort `Nexerius`, im Pulldown stand
# `Jarvis`. Geprueft wird die REGEL ueber ALLE Werkzeuge und beide Sprachen –
# ein kuenftiger Eintrag mit Produktnamen faellt damit von selbst auf.
print("\n── Kein Vorgabe-Produktname in den Zielwerkzeugen ──")
for _lg in ("de", "en"):
    _namen = [b["name"] for b in sa.catalog(_lg)["bi_tools"]]
    check(f"catalog({_lg}) nennt nirgends den Vorgabenamen",
          not any("jarvis" in n.lower() for n in _namen), str(_namen))
    check(f"catalog({_lg}) liefert fuer jedes Werkzeug einen Namen",
          all(n.strip() for n in _namen), str(_namen))
check("und der Auftragstext ebenfalls nicht (de)",
      "Jarvis" not in sa.build_task(analysis_id=None, question="x", tool_id="inline"))
check("und der Auftragstext ebenfalls nicht (en)",
      "Jarvis" not in sa.build_task(analysis_id=None, question="x", tool_id="inline",
                                    lang="en"))
# Positivkontrolle: die Namen unterscheiden sich je Sprache, der Helfer wirkt
# also wirklich (sonst waere die Null oben aus dem falschen Grund gruen).
check("der Name des Inline-Eintrags ist uebersetzt",
      sa.catalog("de")["bi_tools"][0]["name"] != sa.catalog("en")["bi_tools"][0]["name"],
      sa.catalog("en")["bi_tools"][0]["name"])
# Eigennamen bleiben in beiden Sprachen gleich – sonst waere aus dem Helfer
# eine Uebersetzungspflicht fuer Power BI und Excel geworden.
check("Eigennamen bleiben unveraendert",
      sa.catalog("de")["bi_tools"][1]["name"] == sa.catalog("en")["bi_tools"][1]["name"])

print(f"\n{'═' * 46}\nErgebnis: {_ok}/{_ok + _fail} bestanden")
sys.exit(0 if _fail == 0 else 1)
