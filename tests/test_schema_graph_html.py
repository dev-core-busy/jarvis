#!/usr/bin/env python3
"""Waechter: SQL-Assistent liest die HTML-Dokumentation aus DbSchema.

Anlass (ECHT 2026-11-11): ein Schema bestand aus zwei DbSchema-HTML-Seiten
(234 Tabellen, 15 Sichten). Ohne eigenen Weg gingen sie durch den SQL-Parser
und standen als "ohne Struktur" da.

Das Material bildet den GEMESSENEN Aufbau der beiden echten Seiten nach (die
Seiten selbst enthalten Kundennamen und gehoeren nicht ins Repo):
- Tabellenkarte im Layout MIT Beschreibungsspalte (Idx | Column Name |
  Definition | Description) und im Layout OHNE (Idx | Column Name | Data Type)
- Sichtkarte mit "View <name>" OHNE Schema in der Ueberschrift
- Zwischenkoepfe Indexes / Foreign Key / Referring Foreign Key / Triggers
- Entities (``&#40;``, ``&#95;``, ``&#46;``), ``<br>`` in Beschreibungen,
  ``onclick`` mit ``<`` im Anker, Diagramme (SVG) mit Tabellennamen darin
- eine Kante OHNE Zielspalte (im echten Bestand 3 von 394)

Aufruf:  python3 tests/test_schema_graph_html.py [parser.py]
         (optional ein anderer Parser – fuer Gegenproben an einer Kopie)
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


pfad = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backend" / "schema_graph_parser.py"
spec = importlib.util.spec_from_file_location("parser_unter_test", pfad)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

# ── Material (Aufbau wie die echte DbSchema-Seite) ──────────────────────────
KLICK = ("onclick=\"window.scrollTo(60, 336);var nodes = document.getElementsByClassName('palpable');"
         "for (var i = 0; i < nodes.length; i++) { nodes[i].classList.remove('palpable');}; return false;\"")
SVG_SYMBOL = "<svg width='14' height='14'><use href='#pk'/><title>Primary Key</title></svg>"
# Diagramm mit Tabellennamen und sogar einer Karten-Attrappe: darf nichts liefern
SVG_DIAGRAMM = ("<div class='svgContainer'><svg viewBox='0 0 10 10'><text>dbo.Geist</text>"
                "<a name='dbo.Geist'><h5 class='card-title'>Table dbo.Geist</h5></a></svg></div>")


def kopf(titel):
    return ("<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n<!DOCTYPE html>\n"
            "<html lang='en-us' xmlns='http://www.w3.org/1999/xhtml' >\n<head>\n<title>" + titel + "</title>\n"
            "<style>.card-title{color:#000}</style><script>var x = 1 < 2;</script></head>\n<body class=''>\n"
            + SVG_DIAGRAMM)


def karte(art, anker, titel, beschreibung=""):
    p = f'\n<p class="text-muted">{beschreibung}</p>' if beschreibung else ""
    return (f"<br><br>\n<div class='card'><div class='card-body'><a name='{anker}'  {KLICK} "
            f"style='cursor:pointer;'><h5 class='card-title'>{art} {titel}</h5></a>{p}\n"
            "<table class='table table-sm small' style='table-layout: fixed; word-wrap: break-word;'>\n")


def kante(von, ziel_anker, ziel, nach, pfeil="&#8599;"):
    klammer = f"({nach})" if nach is not None else ""
    return (f"\t<tr>\n\t\t<td></td><td>FK_{von}</td>\n\t\t<td > {von} {pfeil} <a href='#{ziel_anker}' {KLICK}>"
            f"&#10063; {ziel}</a>{klammer} </td>\n\t\t<td>  </td>\n\t</tr>\n")


SEITE_TABELLEN = (
    kopf("Contoso DB&#45;Schema")
    + "<div class='card'><div class='card-body'><h5 class='card-title'>Tables</h5><ul>"
    + "<li>Schema <a href='#Contoso.dbo'/> Contoso.dbo</a><ul><li><a href='#dbo.Auftrag'/>Auftrag</a>"
    + "</ul></ul></div></div>\n"
    + "<div class='card'><div class='card-body'><a name='Contoso.dbo' style='cursor:pointer;'>"
    + "<h5 class='card-title'>Schema Contoso.dbo</h5></div></div>\n"
    # Layout MIT Beschreibungsspalte
    + karte("Table", "dbo.Auftrag", "dbo.Auftrag", "Auftr&#228;ge des Hauses")
    + "<thead>\n<tr><th style='width:5%'>Idx</th><th style='width:20%'>Column Name</th>"
      "<th style='width:23%'>Definition</th><th style='width:52%'>Description</th></tr>\n</thead>\n<tbody>\n"
    + f"\t<tr>\n\t\t<td>*{SVG_SYMBOL}</td>\n\t\t<td><a name='dbo.Auftrag_GUID'>GUID</a></td>\n"
      "\t\t<td> char&#40;22&#41; COLLATE Latin1&#95;General&#95;CS&#95;AS COLLATE Latin1&#95;General&#95;CS&#95;AS </td>\n"
      "\t\t<td> PK </td>\n\t</tr>\n"
    + f"\t<tr>\n\t\t<td>*{SVG_SYMBOL}{SVG_SYMBOL}</td>\n\t\t<td><a name='dbo.Auftrag_Kunde'>Kunde</a></td>\n"
      "\t\t<td> char&#40;22&#41; </td>\n\t\t<td> FK auf Kunde&#46;GUID </td>\n\t</tr>\n"
    + "\t<tr>\n\t\t<td>&nbsp;</td>\n\t\t<td><a name='dbo.Auftrag_Bemerkung'>Bemerkung</a></td>\n"
      "\t\t<td> varchar&#40;4000&#41; COLLATE Latin1&#95;General&#95;CI&#95;AS </td>\n"
      "\t\t<td> Freitext<br>Zweite Zeile&#44; mit &quot;Zitat&quot; </td>\n\t</tr>\n"
    + f"\t<tr>\n\t\t<td>{SVG_SYMBOL}</td>\n\t\t<td><a name='dbo.Auftrag_Betrag'>Betrag</a></td>\n"
      "\t\t<td> int DEFAULT 0 </td>\n\t\t<td>  </td>\n\t</tr>\n"
    + "\t<tr>\n\t\t<td>&nbsp;</td>\n\t\t<td><a name='dbo.Auftrag_Bereich'>Bereich</a></td>\n"
      "\t\t<td> smallint </td>\n\t\t<td>  </td>\n\t</tr>\n"
    + "<tr><th colspan='4'>Indexes</th></tr>\n"
    # PK ZUERST wie im echten Bestand – danach Index und Unique: wer jeden Index
    # als PK nimmt, behaelt den letzten
    + "\t<tr>\t\t<td></td><td>Auftrag&#95;PK</td>\n\t\t<td>Primary Key ON GUID</td>\n\t\t<td>  </td>\n\t</tr>\n"
    + "\t<tr>\t\t<td></td><td>Auftrag&#95;I&#95;Kunde</td>\n\t\t<td>Index ON Kunde&#44; Betrag</td>\n\t\t<td>  </td>\n\t</tr>\n"
    + "\t<tr>\t\t<td></td><td>Auftrag&#95;UK</td>\n\t\t<td>Unique Key ON Bemerkung</td>\n\t\t<td>  </td>\n\t</tr>\n"
    + "<tr><th colspan='4'>Foreign Key</th></tr>\n"
    + kante("Kunde", "dbo&#46;Kunde", "dbo&#46;Kunde", "GUID")
    + kante("Bereich", "dbo&#46;Bereich", "dbo&#46;Bereich", None)
    + "<tr><th colspan='4'>Referring Foreign Key</th></tr>\n"
    + kante("GUID", "dbo&#46;Position", "dbo&#46;Position", "Auftrag", pfeil="&#8601;")
    + "<tr><th colspan='4'>Triggers</th></tr>\n</tbody>\n</table></div></div>\n"
    # Layout OHNE Beschreibungsspalte, zusammengesetzter Schluessel
    + karte("Table", "dbo.Kunde", "dbo.Kunde")
    + "<thead>\n<tr><th style='width:5%'>Idx</th><th style='width:40%'>Column Name</th><th>Data Type</th></tr>\n"
      "</thead>\n<tbody>\n"
    + f"\t<tr>\n\t\t<td>*{SVG_SYMBOL}</td>\n\t\t<td><a name='dbo.Kunde_Mandant'>Mandant</a></td>\n"
      "\t\t<td> smallint </td>\n\t</tr>\n"
    + f"\t<tr>\n\t\t<td>*{SVG_SYMBOL}</td>\n\t\t<td><a name='dbo.Kunde_Nummer'>Nummer</a></td>\n"
      "\t\t<td> varchar&#40;20&#41; COLLATE Latin1&#95;General&#95;CI&#95;AS </td>\n\t</tr>\n"
    + "\t<tr>\n\t\t<td>&nbsp;</td>\n\t\t<td><a name='dbo.Kunde_Name'>Name</a></td>\n"
      "\t\t<td> nvarchar&#40;100&#41; </td>\n\t</tr>\n"
    + "<tr><th colspan='3'>Indexes</th></tr>\n"
    + "\t<tr> <td></td><td>Kunde&#95;PK</td> <td>Primary Key ON Mandant&#44; Nummer</td> </tr>\n"
    + "<tr><th colspan='3'>Foreign Key</th></tr>\n<tr><th colspan='3'>Triggers</th></tr>\n"
    + "</tbody>\n</table></div></div>\n</body></html>\n")

SEITE_SICHTEN = (
    kopf("Views")
    + karte("View", "dbo.v_Offen", "v_Offen")
    + "<tr><th style='width:10%'>Idx</th><th style='width:30%'>Column Name</th><th>Data Type</th></tr>\n"
    + "<tr> <td>&nbsp;</td> <td><a name='dbo.v_Offen_GUID'>GUID</a></td> <td> char </td> </tr>\n"
    + "<tr> <td>&nbsp;</td> <td><a name='dbo.v_Offen_Kunde'>Kunde</a></td> <td> varchar </td> </tr>\n"
    + "</table></div></div>\n</body></html>\n")

SEITE_FREMD = ("<!DOCTYPE html><html><head><title>Notizen</title></head><body><h1>Besprechung</h1>"
               "<table><tr><th>Tabelle</th></tr><tr><td>Auftrag</td></tr></table></body></html>")

# Positivkontrolle des Materials: die Struktur, die gemessen werden soll, ist da
if (SEITE_TABELLEN.count("card-title'>Table dbo.") != 3 or SEITE_SICHTEN.count("card-title'>View ") != 1
        or SEITE_TABELLEN.count("&#8599;") != 2 or SEITE_TABELLEN.count("&#8601;") != 1):
    abbruch("Testmaterial hat nicht den erwarteten Aufbau (3 Tabellenkoepfe inkl. Diagramm-Attrappe, "
            "1 Sicht, 2 Kanten, 1 rueckwaertige Kante)")

TMP = Path(tempfile.mkdtemp(prefix="test_sg_html_"))
try:
    (TMP / "Tabellen.html").write_text(SEITE_TABELLEN, encoding="utf-8")
    (TMP / "Sichten.HTM").write_text(SEITE_SICHTEN, encoding="utf-8")
    (TMP / "Notizen.html").write_text(SEITE_FREMD, encoding="utf-8")
    # UTF-8 mit Marke: die Marke darf nichts kosten
    (TMP / "Marke.html").write_bytes(b"\xef\xbb\xbf" + SEITE_SICHTEN.encode("utf-8"))

    print("0. Weg und Fassung")
    check("Parser-Fassung >= 7 (Bestand wird nach dem Update neu gelesen)", getattr(P, "FASSUNG", 0) >= 7,
          getattr(P, "FASSUNG", None))
    eT = P.datei_zerlegen(str(TMP / "Tabellen.html"))
    eS = P.datei_zerlegen(str(TMP / "Sichten.HTM"))
    check(".html gelesen ohne Fehler", eT["ok"] and not eT["fehler"], eT["fehler"])
    check(".HTM (Grossschreibung, Kurzform) gelesen", eS["ok"] and not eS["fehler"], eS["fehler"])
    fT = {x.get("name"): x for x in eT["fakten"]}
    fS = {x.get("name"): x for x in eS["fakten"]}

    print("1. Tabellen")
    check("genau zwei Tabellen, das Diagramm liefert nichts", sorted(fT) == ["dbo.Auftrag", "dbo.Kunde"], sorted(fT))
    check("Statistik: 2 Anweisungen, 2 Strukturen",
          eT["stat"].get("anweisungen") == 2 and eT["stat"].get("struktur") == 2, eT["stat"])
    a = fT.get("dbo.Auftrag") or {}
    k = fT.get("dbo.Kunde") or {}
    sp = {s["name"]: s for s in a.get("spalten", [])}
    check("Art 'tabelle'", a.get("art") == "tabelle" and k.get("art") == "tabelle")
    check("Tabellenbeschreibung gelesen (Entity aufgeloest)", a.get("kommentar") == "Aufträge des Hauses",
          a.get("kommentar"))
    check("Tabelle ohne Beschreibung: leer", k.get("kommentar") == "", k.get("kommentar"))
    check("Spalten in Reihenfolge", list(sp) == ["GUID", "Kunde", "Bemerkung", "Betrag", "Bereich"], list(sp))
    check("Typ ohne COLLATE", sp.get("GUID", {}).get("typ") == "char(22)", sp.get("GUID"))
    check("Typ ohne DEFAULT", sp.get("Betrag", {}).get("typ") == "int", sp.get("Betrag"))
    check("Typ ohne Zusatz", sp.get("Bereich", {}).get("typ") == "smallint", sp.get("Bereich"))
    check("'*' = Pflichtfeld", sp.get("GUID", {}).get("null") is False and sp.get("Kunde", {}).get("null") is False)
    check("nur Symbol (kein '*') = darf leer sein", sp.get("Betrag", {}).get("null") is True, sp.get("Betrag"))
    check("&nbsp; = darf leer sein", sp.get("Bemerkung", {}).get("null") is True)
    check("Spaltenbeschreibung gelesen", sp.get("Kunde", {}).get("kommentar") == "FK auf Kunde.GUID",
          sp.get("Kunde"))
    check("<br> wird Zeilenumbruch, Entities aufgeloest",
          sp.get("Bemerkung", {}).get("kommentar") == 'Freitext\nZweite Zeile, mit "Zitat"', sp.get("Bemerkung"))
    check("leere Beschreibung bleibt leer", sp.get("Betrag", {}).get("kommentar") == "", sp.get("Betrag"))

    print("2. Schluessel und Kanten")
    check("PK aus 'Primary Key ON' (nicht aus Index/Unique davor)", a.get("pk") == ["GUID"], a.get("pk"))
    check("PK-Spalte markiert, andere nicht",
          sp.get("GUID", {}).get("pk") is True and not any(s["pk"] for n, s in sp.items() if n != "GUID"))
    check("zusammengesetzter PK im Layout ohne Beschreibung", k.get("pk") == ["Mandant", "Nummer"], k.get("pk"))
    fks = a.get("fks", [])
    check("Kante mit Zielspalte", {"von": ["Kunde"], "ziel": "dbo.Kunde", "nach": ["GUID"]} in fks, fks)
    check("Kante OHNE Zielspalte: nach = []", {"von": ["Bereich"], "ziel": "dbo.Bereich", "nach": []} in fks, fks)
    check("rueckwaertige Kante (Referring Foreign Key) NICHT gelesen", len(fks) == 2 and
          not any(f["ziel"] == "dbo.Position" for f in fks), fks)
    check("Tabelle ohne Kanten: fks leer", k.get("fks") == [], k.get("fks"))

    print("3. Sichten")
    v = fS.get("dbo.v_Offen") or {}
    check("Sichtname aus dem Anker (mit Schema), nicht aus der Ueberschrift", list(fS) == ["dbo.v_Offen"], list(fS))
    check("Art 'sicht'", v.get("art") == "sicht", v.get("art"))
    check("Sichtspalten mit Typ", [(s["name"], s["typ"]) for s in v.get("spalten", [])]
          == [("GUID", "char"), ("Kunde", "varchar")], v.get("spalten"))
    check("Sicht ohne SQL: keine benutzten Tabellen, keine Herkunft",
          v.get("nutzt") == [] and v.get("herkunft") == {"spalten": {}, "stern": []}, v)
    eM = P.datei_zerlegen(str(TMP / "Marke.html"))
    check("UTF-8 mit Marke liefert dieselbe Sicht", [x.get("name") for x in eM["fakten"]] == ["dbo.v_Offen"],
          eM)

    print("4. Gleiche Form wie der YAML-Weg (den der Index schon versteht)")
    yt = P.yaml_objekt({"object_type": "TABLE", "name": "T", "schema": "S", "columns": [{"name": "A"}]},
                       P.Statistik())
    yv = P.yaml_objekt({"object_type": "VIEW", "name": "V", "schema": "S", "columns": [{"name": "A"}]},
                       P.Statistik())
    check("Tabelle: dieselben Schluessel", yt and set(a) == set(yt[0]) and
          set(sp.get("GUID", {})) == set(yt[0]["spalten"][0]), (sorted(a), yt and sorted(yt[0])))
    check("Sicht: dieselben Schluessel", yv and set(v) == set(yv[0]), (sorted(v), yv and sorted(yv[0])))

    print("5. Fremde HTML-Seite")
    eF = P.datei_zerlegen(str(TMP / "Notizen.html"))
    check("liefert keine Fakten (wird nicht geraten)", eF["ok"] and eF["fakten"] == [], eF)
    check("zaehlt als Anweisung -> erscheint am Schema als 'ohne Struktur'",
          int(eF["stat"].get("anweisungen") or 0) > 0, eF["stat"])
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nBilanz: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
