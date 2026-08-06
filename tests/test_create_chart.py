#!/usr/bin/env python3
"""Tests fuer backend/tools/chart.py (create_chart).

Laeuft OHNE fastapi und ohne Netz: chart.py importiert nur BaseTool. Damit ist
der Test auch auf DEV im echten venv ausfuehrbar.

Schwerpunkte – in der Reihenfolge, in der Fehler hier wirklich weh tun:
 1. parse_number: eine deutsche Tabelle mit "1.234" MUSS 1234 ergeben.
    float("1.234") liefert 1.234 – das ist ein stiller Faktor 1000 im
    Diagramm, den niemand sieht.
 2. Die Fehlermeldungen: sie sind der Repair-Loop. Eine Meldung ohne die
    Angabe, WAS zu tun ist, macht das Werkzeug wertlos.
 3. Marker: die Zahlen duerfen nicht in den Rueckgabetext geraten (sonst
    laufen sie doch durch den Modell-Kontext).
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.tools import chart as C  # noqa: E402

_ok = 0
_fail = 0


def pruefe(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}")


def lauf(**kwargs):
    """create_chart einmal ausfuehren und den Ergebnistext liefern."""
    return asyncio.run(C.CreateChartTool().execute(**kwargs))


def spec_aus(ergebnis):
    """Holt die registrierte Spezifikation zum Marker im Ergebnistext."""
    import re
    m = re.search(r"\[\[JARVIS_CHART:([0-9a-f]{16})\]\]", ergebnis)
    return C.get_spec(m.group(1)) if m else None


# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 1. Zahlen aus Tabellen (parse_number) ===")

faelle = [
    ("1234", 1234.0, "einfache Ganzzahl"),
    ("1.234", 1234.0, "deutscher Tausenderpunkt -> 1234, NICHT 1.234"),
    ("1.234.567", 1234567.0, "zwei Tausendergruppen"),
    ("1,5", 1.5, "deutsches Dezimalkomma"),
    ("1.234,56", 1234.56, "deutsch gemischt"),
    ("1,234.56", 1234.56, "englisch gemischt"),
    ("1,234", 1234.0, "englischer Tausenderkomma"),
    ("12,5%", 12.5, "Prozentzeichen"),
    ("1.234,50 €", 1234.5, "Waehrung + geschuetztes Leerzeichen"),
    ("(1.234)", -1234.0, "Buchhaltungsklammern = negativ"),
    ("-42", -42.0, "negativ"),
    ("0", 0.0, "Null (darf nicht als leer gelten)"),
    (0, 0.0, "Zahl 0 direkt"),
    (7, 7.0, "int direkt"),
    (3.5, 3.5, "float direkt"),
    ("", None, "leerer Text"),
    (None, None, "None"),
    ("k.A.", None, "Text ohne Zahl"),
    (True, None, "bool ist keine Zahl"),
    ("1 234,5", 1234.5, "Leerzeichen als Tausendertrenner"),
]
for roh, erwartet, was in faelle:
    got = C.parse_number(roh)
    pruefe(got == erwartet, f"{was}: {roh!r} -> {got!r} (erwartet {erwartet!r})")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 2. Pflichtangaben und Fehlermeldungen (Repair-Loop) ===")

r = lauf()
pruefe(r.startswith("FEHLER_KORRIGIERBAR") and "type" in r, "type fehlt -> korrigierbarer Fehler")
r = lauf(type="pyramide", labels=["a"], series=[{"data": [1]}])
pruefe("bar" in r and "line" in r, "unbekannter Typ nennt die erlaubten Werte")
r = lauf(type="bar", labels=["a", "b"])
pruefe("series" in r and "source" in r, "fehlende Daten nennen BEIDE Wege")
r = lauf(type="bar", series=[{"label": "x", "data": [1, 2]}])
pruefe("labels" in r, "fehlende Kategorien werden benannt")
r = lauf(type="bar", labels=["a", "b", "c"], series=[{"label": "Umsatz", "data": [1, 2]}])
pruefe("2 Werte" in r and "3 Kategorien" in r,
       "Laengenfehler nennt BEIDE Anzahlen (nicht nur 'ungueltig')")
pruefe("null" in r, "Laengenfehler sagt, wie fehlende Werte anzugeben sind")
r = lauf(type="bar", labels=["a"], series=[{"label": "x", "data": []}])
pruefe("nicht-leere" in r or "nicht-leer" in r, "leeres data wird abgewiesen")
r = lauf(type="bar", labels=["a", "b"], series=[{"label": "x", "data": ["k.A.", "-"]}])
pruefe("keine Zahl" in r, "Datenreihe ohne jede Zahl wird abgewiesen")
r = lauf(type="scatter", series=[{"label": "p", "data": [1, 2, 3]}])
pruefe("x" in r and "y" in r, "scatter verlangt Punktpaare und sagt das Format")
r = lauf(type="bubble", series=[{"label": "p", "data": [{"x": 1, "y": 2}]}])
pruefe(spec_aus(r) is not None, "bubble ohne r ist erlaubt (Radius wird ergaenzt)")
sp = spec_aus(r)
pruefe(sp and sp["data"]["datasets"][0]["data"][0].get("r") == 6, "fehlender Radius wird auf 6 gesetzt")
r = lauf(type="bar", labels=["a"], series=[{"label": "x", "data": [1]} for _ in range(C.MAX_SERIES + 1)])
pruefe(str(C.MAX_SERIES) in r, "zu viele Datenreihen: Grenze wird genannt")
r = lauf(type="bar", labels=[str(i) for i in range(C.MAX_POINTS + 1)],
         series=[{"label": "x", "data": list(range(C.MAX_POINTS + 1))}])
pruefe("aggregate" in r or "zusammen" in r.lower(), "zu viele Punkte: Ausweg wird genannt")
pruefe(all(t.startswith("FEHLER") for t in [lauf(), lauf(type="bar")]),
       "kein Fehlerfall liefert versehentlich einen Marker")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 3. Erfolgsfall: Spezifikation + Marker ===")

r = lauf(type="bar", title="Umsatz je Quartal", labels=["Q1", "Q2", "Q3"],
         series=[{"label": "Umsatz (k€)", "data": ["1.200", "1.450,50", 900]}],
         x_title="Quartal", y_title="Umsatz in k€")
sp = spec_aus(r)
pruefe(sp is not None, "Erfolgsfall registriert eine Spezifikation")
pruefe("[[JARVIS_CHART:" in r, "Ergebnis enthaelt die Marker-Zeile")
pruefe("1.200" not in r and "1450" not in r and "900" not in r,
       "die ZAHLEN stehen NICHT im Rueckgabetext (sonst im Modell-Kontext)")
pruefe(sp["data"]["datasets"][0]["data"] == [1200.0, 1450.5, 900.0],
       "deutsche Zahlen wurden korrekt umgesetzt")
pruefe(sp["data"]["labels"] == ["Q1", "Q2", "Q3"], "Kategorien uebernommen")
pruefe(sp["options"]["plugins"]["title"]["text"] == "Umsatz je Quartal", "Titel gesetzt")
pruefe(sp["options"]["scales"]["y"]["title"]["text"] == "Umsatz in k€", "y-Achsentitel gesetzt")
pruefe(sp["options"]["scales"]["x"]["title"]["display"] is True, "Achsentitel ist sichtbar")
txt = json.dumps(sp)
pruefe("color" not in txt.lower().replace("scales", ""),
       "KEINE Farben in der Spezifikation – die Optik macht der Theme-Layer")
pruefe("function" not in txt and "=>" not in txt, "keine JS-Funktionen in der Spezifikation")

r = lauf(type="bar", labels=["Sehr langer Name"], series=[{"label": "x", "data": [5]}],
         horizontal=True, stacked=True)
sp = spec_aus(r)
pruefe(sp["options"]["indexAxis"] == "y", "horizontal -> indexAxis y")
pruefe(sp["options"]["scales"]["x"]["stacked"] and sp["options"]["scales"]["y"]["stacked"],
       "stacked setzt beide Achsen")

r = lauf(type="line", labels=["a", "b"], series=[{"label": "x", "data": [1, 2]}],
         target_line="1.000", target_label="Ziel")
sp = spec_aus(r)
ann = sp["options"]["plugins"]["annotation"]["annotations"]["ziel"]
pruefe(ann["yMin"] == 1000.0 and ann["yMax"] == 1000.0, "Ziellinie auf der y-Achse (senkrechte Balken)")
pruefe(ann["label"]["content"] == "Ziel", "Ziellinie beschriftet")
r = lauf(type="bar", labels=["a"], series=[{"label": "x", "data": [1]}],
         horizontal=True, target_line=5)
ann = spec_aus(r)["options"]["plugins"]["annotation"]["annotations"]["ziel"]
pruefe("xMin" in ann and "yMin" not in ann,
       "bei waagerechten Balken liegt die Ziellinie auf der x-Achse")

r = lauf(type="pie", labels=["a", "b"], series=[{"label": "1", "data": [1, 2]},
                                               {"label": "2", "data": [3, 4]}])
pruefe("erste Datenreihe" in r, "Kreisdiagramm mit mehreren Reihen wird angemerkt")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 4. Marker aufloesen / entfernen ===")

r = lauf(type="bar", labels=["a"], series=[{"label": "x", "data": [42]}])
import re as _re
tok = _re.search(r"\[\[JARVIS_CHART:([0-9a-f]{16})\]\]", r).group(1)
antwort = f"Hier das Ergebnis.\n\n[[JARVIS_CHART:{tok}]]\n\nSoweit die Zahlen."
aus = C.expand_markers(antwort)
pruefe("```chartjs" in aus, "expand_markers erzeugt einen chartjs-Block")
pruefe('"data":[42' in aus.replace(" ", "") or "42" in aus, "die Werte stehen im Block")
pruefe("[[JARVIS_CHART:" not in aus, "der Marker selbst ist verschwunden")
pruefe("Hier das Ergebnis." in aus and "Soweit die Zahlen." in aus, "der Text bleibt erhalten")
aus2 = C.expand_markers(aus)
pruefe(aus2 == aus, "zweiter Durchlauf aendert nichts (idempotent)")
pruefe(C.get_spec(tok) is not None, "Spezifikation bleibt nach dem Einloesen abrufbar")
pruefe(C.expand_markers("[[JARVIS_CHART:" + "0" * 16 + "]] Text").strip() == "Text",
       "unbekanntes Token wird entfernt, nicht als Klartext gezeigt")
pruefe(C.expand_markers("ohne Marker") == "ohne Marker", "Text ohne Marker bleibt unangetastet")
strip = C.strip_markers(antwort)
pruefe("[[JARVIS_CHART:" not in strip and "```chartjs" not in strip,
       "strip_markers (WhatsApp/Telegram) laesst weder Marker noch JSON zurueck")
pruefe("Hier das Ergebnis." in strip, "strip_markers behaelt den Text")

# Deckel: aeltester Eintrag fliegt, neue bleiben abrufbar
tokens = [C.register_spec({"type": "bar", "n": i}) for i in range(C._MAX_PENDING + 5)]
pruefe(C.get_spec(tokens[0]) is None, "Deckel greift: aeltester Eintrag ist weg")
pruefe(C.get_spec(tokens[-1]) is not None, "neuester Eintrag ist da")
pruefe(len(C._pending) <= C._MAX_PENDING, "Speicher waechst nicht unbegrenzt")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 5. Datenquelle: CSV/TSV/XLSX (A4) ===")

tmp = Path(tempfile.mkdtemp(prefix="jchart_"))

csv_de = tmp / "umsatz.csv"
csv_de.write_text(
    "Region;Umsatz;Kosten\n"
    "Nord;1.200,50;800\n"
    "Süd;2.000;1.100\n"
    "Nord;300,50;100\n"
    "Ost;500;200\n"
    ";999;999\n",                      # Zeile ohne Kategorie -> wird verworfen
    encoding="utf-8")

r = lauf(type="bar", title="Umsatz", source={
    "file": str(csv_de), "label_column": "Region",
    "value_columns": ["Umsatz", "Kosten"], "aggregate": "sum"})
sp = spec_aus(r)
pruefe(sp is not None, f"CSV mit Semikolon gelesen ({r[:60]})")
pruefe(sp["data"]["labels"] == ["Nord", "Süd", "Ost"],
       f"Kategorien in Datei-Reihenfolge, dedupliziert: {sp['data']['labels']}")
pruefe(sp["data"]["datasets"][0]["data"] == [1501.0, 2000.0, 500.0],
       f"Summe je Region mit deutschen Zahlen: {sp['data']['datasets'][0]['data']}")
pruefe(len(sp["data"]["datasets"]) == 2 and sp["data"]["datasets"][1]["label"] == "Kosten",
       "zweite Wertespalte wird zweite Datenreihe")
pruefe("Kategorien aus umsatz.csv" in r, "Ergebnis nennt Herkunft und Umfang")
pruefe("1.200" not in r and "1501" not in r, "auch beim Datei-Weg keine Zahlen im Rueckgabetext")

r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Region",
                             "value_columns": ["Umsatz"], "aggregate": "mean"})
pruefe(spec_aus(r)["data"]["datasets"][0]["data"][0] == 750.5,
       "aggregate=mean rechnet Mittel ((1200,50 + 300,50) / 2)")
r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Region",
                             "value_columns": ["Umsatz"], "aggregate": "count"})
pruefe(spec_aus(r)["data"]["datasets"][0]["data"][0] == 2.0, "aggregate=count zaehlt Zeilen")
r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Region",
                             "value_columns": ["Umsatz"], "aggregate": "max"})
pruefe(spec_aus(r)["data"]["datasets"][0]["data"][0] == 1200.5, "aggregate=max")

r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Region",
                             "value_columns": ["Umsatz"], "aggregate": "sum",
                             "sort": "value_desc"})
pruefe(spec_aus(r)["data"]["labels"] == ["Süd", "Nord", "Ost"], "sort=value_desc sortiert absteigend")
r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Region",
                             "value_columns": ["Umsatz"], "aggregate": "sum", "sort": "label"})
pruefe(spec_aus(r)["data"]["labels"] == ["Nord", "Ost", "Süd"], "sort=label sortiert alphabetisch")

r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Region",
                             "value_columns": ["Umsatz"], "aggregate": "sum",
                             "sort": "value_desc", "top_n": 2})
pruefe(len(spec_aus(r)["data"]["labels"]) == 2, "top_n begrenzt")
pruefe("2 von 3" in r, "gekuerzte Auswahl wird AUSDRUECKLICH gemeldet (kein stilles Abschneiden)")

# Spaltensuche
r = lauf(type="bar", source={"file": str(csv_de), "label_column": "region",
                             "value_columns": ["umsatz"]})
pruefe(spec_aus(r) is not None, "Spaltennamen ohne Beachtung der Gross-/Kleinschreibung")
r = lauf(type="bar", source={"file": str(csv_de), "label_column": "1", "value_columns": ["2"]})
pruefe(spec_aus(r) is not None, "Spalten auch per Position ansprechbar")
r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Gebiet",
                             "value_columns": ["Umsatz"]})
pruefe("Gebiet" in r and "Region" in r and "Umsatz" in r,
       "unbekannte Spalte: Meldung listet die VORHANDENEN Spalten auf")
r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Region"})
pruefe("value_columns" in r, "fehlende Wertespalte wird benannt")
r = lauf(type="bar", source={"file": str(tmp / "gibtsnicht.csv"), "label_column": "a",
                             "value_columns": ["b"]})
pruefe("nicht gefunden" in r, "fehlende Datei -> klare Meldung")
r = lauf(type="bar", source={"file": str(tmp), "label_column": "a", "value_columns": ["b"]})
pruefe("Verzeichnis" in r, "Verzeichnis statt Datei -> klare Meldung")
r = lauf(type="bar", source={"file": str(csv_de), "label_column": "Region",
                             "value_columns": ["Umsatz"], "aggregate": "median"})
pruefe("aggregate" in r and "sum" in r, "unbekanntes Aggregat nennt die erlaubten Werte")

# Komma-CSV (englisch) – Trennzeichen-Erkennung
csv_en = tmp / "sales.csv"
csv_en.write_text("Month,Revenue\nJan,1200.5\nFeb,900\n", encoding="utf-8")
r = lauf(type="line", source={"file": str(csv_en), "label_column": "Month",
                              "value_columns": ["Revenue"]})
sp = spec_aus(r)
pruefe(sp and sp["data"]["datasets"][0]["data"] == [1200.5, 900.0],
       "Komma-getrennte Datei wird erkannt")

# TSV
tsv = tmp / "d.tsv"
tsv.write_text("A\tB\nx\t5\ny\t7\n", encoding="utf-8")
r = lauf(type="bar", source={"file": str(tsv), "label_column": "A", "value_columns": ["B"]})
pruefe(spec_aus(r)["data"]["datasets"][0]["data"] == [5.0, 7.0], "TSV wird gelesen")

# cp1252 (Excel-Export) – Umlaute duerfen nicht zerfallen
csv_win = tmp / "win.csv"
csv_win.write_bytes("Größe;Wert\nKlein;1\nGroß;2\n".encode("cp1252"))
r = lauf(type="bar", source={"file": str(csv_win), "label_column": "Größe",
                             "value_columns": ["Wert"]})
sp = spec_aus(r)
pruefe(sp and sp["data"]["labels"] == ["Klein", "Groß"], f"cp1252-Datei mit Umlauten: {sp and sp['data']['labels']}")

# Kopfzeile weiter unten
csv_hdr = tmp / "hdr.csv"
csv_hdr.write_text("Bericht Q1\n\nName;Wert\na;1\nb;2\n", encoding="utf-8")
r = lauf(type="bar", source={"file": str(csv_hdr), "label_column": "Name",
                             "value_columns": ["Wert"], "header_row": 2})
pruefe(spec_aus(r) is not None, "header_row verschiebt die Kopfzeile")
r = lauf(type="bar", source={"file": str(csv_hdr), "label_column": "Name",
                             "value_columns": ["Wert"], "header_row": 99})
pruefe("header_row" in r, "header_row hinter dem Dateiende -> Meldung")

# Spalte ohne Kopf bleibt ansprechbar
csv_nohdr = tmp / "nohdr.csv"
csv_nohdr.write_text("Name;\na;5\nb;6\n", encoding="utf-8")
r = lauf(type="bar", source={"file": str(csv_nohdr), "label_column": "Name",
                             "value_columns": ["Spalte2"]})
pruefe(spec_aus(r) is not None, "namenlose Spalte ist als 'SpalteN' ansprechbar")

# source hat Vorrang vor series
r = lauf(type="bar", labels=["z"], series=[{"label": "alt", "data": [1]}],
         source={"file": str(csv_en), "label_column": "Month", "value_columns": ["Revenue"]})
pruefe("ignoriert" in r and spec_aus(r)["data"]["labels"] == ["Jan", "Feb"],
       "bei beidem gewinnt source – und sagt es")

# XLSX (nur wenn openpyxl vorhanden – auf dem Server ist es das)
try:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Daten"
    ws.append(["Monat", "Menge"])
    ws.append(["Jan", 10])
    ws.append(["Feb", 20.5])
    ws2 = wb.create_sheet("Zweites")
    ws2.append(["Monat", "Menge"])
    ws2.append(["Mrz", 99])
    xlsx = tmp / "t.xlsx"
    wb.save(str(xlsx))
    r = lauf(type="bar", source={"file": str(xlsx), "label_column": "Monat",
                                 "value_columns": ["Menge"]})
    sp = spec_aus(r)
    pruefe(sp and sp["data"]["datasets"][0]["data"] == [10.0, 20.5], "XLSX: erstes Blatt gelesen")
    r = lauf(type="bar", source={"file": str(xlsx), "label_column": "Monat",
                                 "value_columns": ["Menge"], "sheet": "Zweites"})
    pruefe(spec_aus(r)["data"]["labels"] == ["Mrz"], "XLSX: Blatt waehlbar")
    r = lauf(type="bar", source={"file": str(xlsx), "label_column": "Monat",
                                 "value_columns": ["Menge"], "sheet": "Fehlt"})
    pruefe("Daten" in r and "Zweites" in r, "unbekanntes Blatt listet die vorhandenen auf")
except ImportError:
    print("  … XLSX-Teil uebersprungen (openpyxl fehlt lokal)")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 6. Werkzeug-Beschreibung und Schema ===")

t = C.CreateChartTool()
pruefe(t.name == "create_chart", "Werkzeugname")
schema = t.parameters_schema()
pruefe(schema["required"] == ["type"], "nur type ist Pflicht (Daten per series ODER source)")
pruefe(set(schema["properties"]["type"]["enum"]) == set(C.ALLOWED_TYPES),
       "Typ-Aufzaehlung im Schema stimmt mit der Prueflogik ueberein")
pruefe("source" in schema["properties"] and "aggregate" in schema["properties"]["source"]["properties"],
       "Datenquelle inkl. Aggregat im Schema beschrieben")
pruefe("marker" in t.description.lower() or "Marker" in t.description,
       "Beschreibung nennt die Marker-Pflicht")
pruefe("matplotlib" in t.description, "Beschreibung verweist fuer PNG auf matplotlib")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 7. Verdrahtung in agent.py (Quelltext) ===")

agent_src = (Path(__file__).resolve().parent.parent / "backend" / "agent.py").read_text()
pruefe("CreateChartTool" in agent_src, "Werkzeug wird registriert")
pruefe('name == "create_chart"' in agent_src and "authorize_fs" in agent_src,
       "Dispatch prueft die Datei-Freigabe fuer source.file")
i_chart = agent_src.find('elif name == "create_chart"')
i_auth = agent_src.find("authorize_fs", i_chart)
pruefe(0 < i_chart < i_auth < i_chart + 1200,
       "die Freigabepruefung steht im create_chart-Zweig (nicht irgendwo sonst)")
pruefe("_expand_charts" in agent_src, "Anzeigetext loest die Marker auf")
pruefe("strip_markers" in agent_src, "headless-Kanaele entfernen die Marker")
pruefe("_mit_plotstyle" in agent_src and "{MPLSTYLE}" in agent_src,
       "matplotlib-Hausstil wird in den Prompt eingesetzt")
pruefe("create_chart" not in agent_src.split("_BLOCKED_TOOLS_FOR_LDAP")[1][:400],
       "create_chart ist fuer Netzwerk-Benutzer NICHT gesperrt (nur lesend, kein Persistenz-Substrat)")

style = Path(__file__).resolve().parent.parent / "backend" / "plotstyles" / "jarvis.mplstyle"
pruefe(style.exists(), "Stildatei liegt an der Stelle, die agent.py nennt")
stxt = style.read_text()
pruefe("figure.constrained_layout.use: True" in stxt,
       "constrained_layout ist an (sonst abgeschnittene Achsenbeschriftungen)")
pruefe("savefig.dpi:         200" in stxt.replace("\t", " "), "savefig.dpi ist erhoeht")
# Nur die WIRKSAMEN Zeilen pruefen, nicht die Kommentare: dort steht 'Inter'
# ausdruecklich als Gegenbeispiel (die Web-Schrift fehlt auf dem Server).
_wirksam = [z for z in stxt.splitlines() if z.strip() and not z.strip().startswith("#")]
_fonts = next((z for z in _wirksam if z.startswith("font.sans-serif")), "")
pruefe("Inter" not in " ".join(_wirksam),
       "keine auf dem Server fehlende Schrift in den wirksamen Zeilen (Warnungsflut)")
pruefe("DejaVu Sans" in _fonts and "Liberation Sans" in _fonts,
       "Schriftliste nennt die auf dem Server vorhandenen Familien")
pruefe("9B59B6" in stxt, "Markenfarbe zuerst im Farbzyklus – wie im Web-Theme")

# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}\nErgebnis: {_ok}/{_ok + _fail} Pruefungen bestanden")
if _fail:
    print(f"FEHLGESCHLAGEN: {_fail}")
try:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
except Exception:
    pass
sys.exit(1 if _fail else 0)
