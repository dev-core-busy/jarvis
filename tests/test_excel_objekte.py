#!/usr/bin/env python3
"""Waechter: Excel-OBJEKTE als Vorschlags-Eintrag (Pivot, Diagramm, Tabelle, bedingt).

Die echten Funktionen laufen WIRKLICH – eine Quelltext-Pruefung koennte die
Frage „was kommt bei dieser Eingabe heraus?" gar nicht beantworten, und genau
die entscheidet, ob eine Pivot-Tabelle entsteht oder ein Eintrag still als
Wertematrix gelesen wird.

DIE TRAGENDE ZUSAGE STEHT IN ABSCHNITT 1: ein Eintrag OHNE ``typ`` verhaelt
sich BYTE-GLEICH wie vor der Aenderung. Ein Feature, das den Bestand anfasst,
ist keines – das hat der Werkzeug-Zuschnitt am 2026-09-06 gekostet.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def check(text: str, bedingung) -> None:
    """(Beschreibung, Bedingung) – NIE andersherum.

    ``test_jira_vorlagen.py`` hatte alle 57 Aufrufe vertauscht und meldete
    „57 OK, 0 FAIL", ohne eine einzige Bedingung ausgewertet zu haben (eine
    nicht-leere Zeichenkette ist wahr). Deshalb bricht der Waechter hier ab.
    """
    global _ok, _fail
    if not isinstance(text, str) or isinstance(bedingung, str):
        print("ABBRUCH: check(Beschreibung, Bedingung) – Argumente vertauscht")
        sys.exit(2)
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print("  FAIL: " + text)


def sicher(fn, *a, **k):
    """Ruft auf und gibt bei einem Wurf den Fehler zurueck – statt den Lauf
    abzubrechen. Ein Waechter, der wirft, endet OHNE Bilanzzeile und ist von
    „nicht gelaufen" nicht zu unterscheiden."""
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return ("WURF", repr(e))


# ── Namens-Guard ──────────────────────────────────────────────────────────
# Gegen einen aelteren Stand faellt der Import, und der Lauf staerbe mit
# AttributeError irgendwo in der Mitte – ohne Bilanz, also ununterscheidbar
# von „bestanden".
try:
    from backend import excel_objekte as o
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend/excel_objekte.py nicht importierbar: %r" % (e,))
    sys.exit(2)

for name in ("API_MIN", "TYPEN", "ist_objekt", "objekt_pruefen",
             "bereich_pruefen", "kurzfassung", "HAUPT_ARTEN",
             "HAUPT_AGGREGATE", "HAUPT_OPERATOREN"):
    if not hasattr(o, name):
        print("ABBRUCH: excel_objekte.%s fehlt" % name)
        sys.exit(2)


def hole(liste, i: int, feld: str = ""):
    """Element i einer Liste – NIE ungeprueft dereferenzieren.

    ⚠ Eine Gegenprobe hat es gezeigt: ``gut3[1].get(...)`` wirft, wenn die
    Sabotage die Liste kuerzer macht – der Waechter bricht dann OHNE
    Bilanzzeile ab und ist von „nicht gelaufen" nicht zu unterscheiden.
    """
    if not isinstance(liste, list) or len(liste) <= i:
        return None
    x = liste[i]
    if not feld:
        return x
    return x.get(feld) if isinstance(x, dict) else None


def pruefe(e, blatt="Auswertung", adresse="A1"):
    return o.objekt_pruefen(e, blatt, adresse)


PIVOT_OK = {"typ": "pivot", "name": "Umsatz", "quelle": "Daten!A1:E200",
            "zeilenfelder": ["Region"], "spaltenfelder": ["Quartal"],
            "wertfelder": [{"feld": "Umsatz", "funktion": "sum"}]}

print("── 1. Der Bestand bleibt unangetastet ──────────────────────────────")
# Ohne fastapi laeuft `excel_ask` nicht ueberall – der Abschnitt ist deshalb
# bedingt, meldet das aber AUSDRUECKLICH, statt still zu bestehen.
try:
    from backend import excel_ask
    _ask = True
except Exception as e:  # noqa: BLE001
    _ask = False
    print("  NICHT GEPRUEFT: backend.excel_ask nicht importierbar (%r)" % (e,))

if _ask:
    zell = [{"adresse": "B2", "formel": "=A2*2"},
            {"adresse": "C1:C9", "wert": 7},
            {"adresse": "D1", "format": "0.00%"},
            {"adresse": "E1:F2", "werte": [[1, 2], [3, 4]]}]
    gut, weg = excel_ask.aenderungen_pruefen(zell)
    check("vier Zell-Eintraege bleiben gueltig", len(gut) == 4)
    check("kein Zell-Eintrag wird abgelehnt", not weg)
    check("kein Zell-Eintrag bekommt ein Feld 'typ'",
          all("typ" not in g for g in gut))
    check("kein Zell-Eintrag bekommt 'api_min'",
          all("api_min" not in g for g in gut))
    # Die Felder selbst muessen unveraendert durchkommen.
    check("Formel unveraendert", hole(gut, 0, "formel") == "=A2*2")
    check("Wert unveraendert", hole(gut, 1, "wert") == 7)
    check("Werte-Matrix unveraendert", hole(gut, 3, "werte") == [[1, 2], [3, 4]])

    print("── 1b. Der Objekt-Zweig greift VOR der Zell-Pruefung ───────────────")
    # ⚠ DIE ENTSCHEIDENDE KOLLISION: `wertfelder` ist eine Liste, und die
    # Zell-Pruefung wuerde einen Pivot-Eintrag als Wertematrix lesen und mit
    # „Die Maße passen nicht zum Bereich" ablehnen.
    gut2, weg2 = excel_ask.aenderungen_pruefen([dict(PIVOT_OK, adresse="A1")])
    check("Pivot kommt durch die Sammelpruefung", len(gut2) == 1 and not weg2)
    check("Pivot behaelt seinen Typ", hole(gut2, 0, "typ") == "pivot")
    check("Pivot traegt api_min", hole(gut2, 0, "api_min") == "1.8")

    print("── 1c. Gemischter Vorschlag ────────────────────────────────────────")
    gemischt = [{"adresse": "A1:C50", "werte": [[1, 2, 3]] * 50},
                dict(PIVOT_OK, adresse="H1")]
    gut3, weg3 = excel_ask.aenderungen_pruefen(gemischt)
    check("Zelle und Objekt zusammen gueltig", len(gut3) == 2 and not weg3)
    check("Reihenfolge bleibt (Zelle zuerst)",
          bool(hole(gut3, 0, "werte")) and hole(gut3, 1, "typ") == "pivot")

    print("── 1d. Ein kaputtes Objekt wird GEMELDET, nicht verschluckt ────────")
    gut4, weg4 = excel_ask.aenderungen_pruefen(
        [{"adresse": "A1", "typ": "pivot", "name": "X", "quelle": "D!A1:B9"}])
    check("kaputtes Objekt ist nicht gueltig", not gut4)
    check("kaputtes Objekt steht in der Ablehnung", len(weg4) == 1)
    check("die Ablehnung nennt den Typ", hole(weg4, 0, "typ") == "pivot")
    check("die Ablehnung nennt einen Grund", bool(hole(weg4, 0, "grund")))

print("── 2. Typ-Erkennung ────────────────────────────────────────────────")
check("Eintrag ohne typ ist kein Objekt", not o.ist_objekt({"adresse": "A1"}))
check("leerer typ ist kein Objekt", not o.ist_objekt({"typ": "  "}))
check("typ=pivot ist ein Objekt", o.ist_objekt({"typ": "pivot"}))
check("None ist kein Objekt", not o.ist_objekt(None))
check("Liste ist kein Objekt", not o.ist_objekt([1, 2]))

print("── 3. Pivot ────────────────────────────────────────────────────────")
s, g = pruefe(PIVOT_OK)
check("vollstaendiger Pivot wird angenommen", s is not None)
check("Aggregat wird auf Office-Schreibweise normiert",
      bool(s) and hole(s.get("wertfelder"), 0, "funktion") == "Sum")
check("Zeilenfelder bleiben erhalten", s and s["zeilenfelder"] == ["Region"])
check("Ziel bleibt Blatt+Adresse",
      s and s["blatt"] == "Auswertung" and s["adresse"] == "A1")

s, g = pruefe(dict(PIVOT_OK, wertfelder=[]))
check("Pivot ohne Wertfeld wird abgelehnt", s is None)
check("...und der Grund nennt 'wertfelder'", "wertfelder" in (g or ""))

s, g = pruefe({k: v for k, v in PIVOT_OK.items()
               if k not in ("zeilenfelder", "spaltenfelder")})
check("Pivot ohne Zeilen- UND Spaltenfeld wird abgelehnt", s is None)

s, g = pruefe(dict(PIVOT_OK, wertfelder=["Umsatz"]))
check("Wertfeld als blosser Text wird angenommen (Kurzform)", s is not None)
check("...mit Vorgabe Sum", bool(s) and hole(s.get("wertfelder"), 0, "funktion") == "Sum")

s, g = pruefe(dict(PIVOT_OK, zeilenfelder='["Region","Land"]'))
check("Feldliste als JSON-STRING wird geparst",
      s is not None and s["zeilenfelder"] == ["Region", "Land"])

s, g = pruefe(dict(PIVOT_OK, zeilenfelder="Region"))
check("einzelnes Feld als Text wird angenommen",
      s is not None and s["zeilenfelder"] == ["Region"])

s, g = pruefe(dict(PIVOT_OK, quelle=""))
check("Pivot ohne Quelle wird abgelehnt", s is None)

print("── 4. Diagramm ─────────────────────────────────────────────────────")
s, g = pruefe({"typ": "diagramm", "art": "saeule", "quelle": "Daten!A1:B10",
               "titel": "Umsatz 2026"})
check("Diagramm wird angenommen", s is not None)
check("Art wird auf den Office-ChartType normiert",
      s and s["art"] == "ColumnClustered")
check("Titel bleibt erhalten", s and s["titel"] == "Umsatz 2026")

s, g = pruefe({"typ": "diagramm", "quelle": "Daten!A1:B10"})
check("Diagramm ohne Art nimmt die Vorgabe (Saeule)",
      s is not None and s["art"] == "ColumnClustered")

s, g = pruefe({"typ": "diagramm", "art": "kreis", "quelle": "Daten!A1:B10"})
check("kreis -> Pie", s and s["art"] == "Pie")

print("── 5. Tabelle ──────────────────────────────────────────────────────")
s, g = pruefe({"typ": "tabelle", "name": "Umsaetze"}, adresse="A1:E200")
check("Tabelle wird angenommen", s is not None)
check("kopfzeile ist per Vorgabe wahr", s and s["kopfzeile"] is True)

s, g = pruefe({"typ": "tabelle", "name": "T", "kopfzeile": False})
check("kopfzeile=False wird uebernommen", s and s["kopfzeile"] is False)

# ⚠ `is False` und nicht Falsyness: ein FEHLENDES Feld darf nicht als „nein"
# gelten – sonst macht Excel aus der Ueberschriftenzeile eine Datenzeile.
s, g = pruefe({"typ": "tabelle", "name": "T", "kopfzeile": None})
check("kopfzeile=None gilt als JA (nicht als nein)", s and s["kopfzeile"] is True)

for schlecht, warum in [("Meine Tabelle", "Leerzeichen"),
                        ("A1", "sieht aus wie ein Zellbezug"),
                        ("1Tabelle", "beginnt mit Ziffer"),
                        ("", "leer")]:
    s, g = pruefe({"typ": "tabelle", "name": schlecht})
    check("Tabellenname %r wird abgelehnt (%s)" % (schlecht, warum), s is None)

print("── 6. Bedingte Formatierung ────────────────────────────────────────")
s, g = pruefe({"typ": "bedingt", "regel": "zellwert", "operator": "groesser",
               "wert": 100}, adresse="B2:B99")
check("zellwert wird angenommen", s is not None)
check("Operator wird normiert", s and s["operator"] == "GreaterThan")
check("ohne Farbangabe entsteht ein sichtbares Format",
      bool(s and s.get("farbe") and s.get("textfarbe")))

s, g = pruefe({"typ": "bedingt", "regel": "zellwert", "operator": "zwischen",
               "wert": 1})
check("zwischen ohne wert2 wird abgelehnt", s is None)
check("...und der Grund nennt wert2", "wert2" in (g or ""))

s, g = pruefe({"typ": "bedingt", "regel": "zellwert", "operator": "zwischen",
               "wert": 1, "wert2": 9})
check("zwischen mit wert2 wird angenommen", s is not None)

s, g = pruefe({"typ": "bedingt", "regel": "farbskala"})
check("farbskala braucht keinen Vergleichswert", s is not None)

s, g = pruefe({"typ": "bedingt", "regel": "zellwert", "operator": "gleich",
               "wert": 1, "farbe": "rot"})
check("Farbe ohne #RRGGBB wird abgelehnt", s is None)

s, g = pruefe({"typ": "bedingt", "regel": "zellwert", "operator": "groesser",
               "wert": 5, "farbe": "#ffc7ce"})
check("Farbe wird auf Grossbuchstaben normiert", s and s["farbe"] == "#FFC7CE")

print("── 7. Quellbereich ─────────────────────────────────────────────────")
for gut_b in ["Daten!A1:E200", "A1:E200", "'Q1 2026'!A1:C9", "Tabelle1!B7"]:
    check("Bereich %r ist gueltig" % gut_b, o.bereich_pruefen(gut_b) == "")
for schlecht_b in ["", "Daten!", "A", "1:9", "x" * 300]:
    check("Bereich %r wird abgelehnt" % schlecht_b[:20],
          o.bereich_pruefen(schlecht_b) != "")

print("── 8. REGEL: jede Meldung nennt einen Weg, der WIRKLICH geht ───────")
# ⚠ Eine Fehlermeldung, die Werte auflistet, die selbst abgelehnt wuerden, ist
# schlimmer als keine – sie schickt den Leser im Kreis. Die erste Fassung tat
# genau das (sie nannte `GreaterThan`, waehrend nur `groesser` ein Schluessel
# war). Geprueft wird die EIGENSCHAFT, nicht der Wortlaut.
def genannte_werte(grund: str) -> list[str]:
    """Zieht die aufgezaehlten Werte aus einer Meldung „… erlaubt sind: a, b, c."

    ⚠ DIE MELDUNG WIRD GELESEN, NICHT DIE KONSTANTE. Die erste Fassung lief
    ueber ``o.HAUPT_ARTEN`` – damit prueft der Waechter, dass die KONSTANTE
    gueltige Werte enthaelt, und merkt nicht, wenn die Meldung etwas ganz
    anderes ausgibt. Eine Gegenprobe, die genau das tat, blieb stumm.
    """
    if "erlaubt sind:" not in (grund or ""):
        return []
    teil = grund.split("erlaubt sind:", 1)[1].strip().rstrip(".")
    return [w.strip() for w in teil.split(",") if w.strip()]


# Diagrammart
_, g_art = pruefe({"typ": "diagramm", "art": "@@gibtesnicht@@",
                   "quelle": "D!A1:B9"})
arten = genannte_werte(g_art)
check("die Diagramm-Meldung zaehlt Werte auf", len(arten) >= 3)
for art in arten:
    s, _ = pruefe({"typ": "diagramm", "art": art, "quelle": "D!A1:B9"})
    check("in der MELDUNG genannte Art %r wird angenommen" % art, s is not None)

# Aggregatfunktion
_, g_fn = pruefe(dict(PIVOT_OK,
                      wertfelder=[{"feld": "U", "funktion": "@@gibtesnicht@@"}]))
fns = genannte_werte(g_fn)
check("die Funktions-Meldung zaehlt Werte auf", len(fns) >= 3)
for fn in fns:
    s, _ = pruefe(dict(PIVOT_OK, wertfelder=[{"feld": "U", "funktion": fn}]))
    check("in der MELDUNG genannte Funktion %r wird angenommen" % fn,
          s is not None)

# Operator
_, g_op = pruefe({"typ": "bedingt", "regel": "zellwert",
                  "operator": "@@gibtesnicht@@", "wert": 1})
ops = genannte_werte(g_op)
check("die Operator-Meldung zaehlt Werte auf", len(ops) >= 3)
for op in ops:
    s, _ = pruefe({"typ": "bedingt", "regel": "zellwert", "operator": op,
                   "wert": 1, "wert2": 9})
    check("in der MELDUNG genannter Operator %r wird angenommen" % op,
          s is not None)
for regel in o.BEDINGT_REGELN:
    e = {"typ": "bedingt", "regel": regel, "operator": "groesser", "wert": 1}
    s, g = pruefe(e)
    check("genannte Regel %r wird angenommen" % regel, s is not None)
for typ in o.TYPEN:
    check("genannter Typ %r hat eine api_min" % typ, bool(o.API_MIN.get(typ)))

print("── 9. Die Versionen sind die BELEGTEN ──────────────────────────────")
# Gemessen an der Herstellerdoku am 2026-09-15. Wer hier etwas aendert, aendert
# eine Zusage ueber fremde Software – und muss sie neu belegen.
check("pivot = 1.8", o.API_MIN["pivot"] == "1.8")
check("diagramm = 1.1", o.API_MIN["diagramm"] == "1.1")
check("tabelle = 1.1", o.API_MIN["tabelle"] == "1.1")
check("bedingt = 1.6", o.API_MIN["bedingt"] == "1.6")

# ⚠ DAS MANIFEST DARF NICHT MITWANDERN. Eine hoehere MinVersion laesst das
# Add-in auf aelteren Clients gar nicht laden.
try:
    from backend import excel_addin
    check("das Manifest verlangt weiterhin 1.7",
          excel_addin.EXCEL_API_MIN == "1.7")
    check("genau die Typen ueber 1.7 brauchen eine Laufzeitpruefung",
          [t for t, v in o.API_MIN.items() if v > excel_addin.EXCEL_API_MIN]
          == ["pivot"])
except Exception as e:  # noqa: BLE001
    print("  NICHT GEPRUEFT: backend.excel_addin (%r)" % (e,))

print("── 10. Unbekanntes wird abgelehnt, nicht geraten ───────────────────")
for typ in ["sparkline", "makro", "slicer", "", "PIVOT TABLE"]:
    s, g = pruefe({"typ": typ})
    check("typ %r wird abgelehnt" % typ, s is None)
s, g = pruefe({"typ": "PIVOT", "name": "X", "quelle": "D!A1:B9",
               "zeilenfelder": ["R"], "wertfelder": ["U"]})
check("Grossschreibung des Typs wird toleriert", s is not None)

print("── 11. Kurzfassung ─────────────────────────────────────────────────")
for e in [PIVOT_OK,
          {"typ": "diagramm", "art": "linie", "quelle": "D!A1:B9"},
          {"typ": "tabelle", "name": "T"},
          {"typ": "bedingt", "regel": "farbskala"}]:
    s, _ = pruefe(e)
    k = sicher(o.kurzfassung, s) if s else ""
    check("Kurzfassung fuer %r ist nicht leer" % e["typ"],
          isinstance(k, str) and len(k) > 3)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
