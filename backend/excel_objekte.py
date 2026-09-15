"""Excel-OBJEKTE als Vorschlags-Eintrag: Pivot, Diagramm, Tabelle, bedingte Formatierung.

WARUM ES DIESES MODUL GIBT
--------------------------
Bis 2026-09-15 kannte ``excel_vorschlag`` genau vier Felder (``formel``,
``werte``, ``wert``, ``format``) – alles davon setzt ZELLINHALTE. Auf die Bitte
um eine Pivot-Tabelle antwortete das Modell:

    „Die direkte Erstellung einer interaktiven Excel-Pivot-Table ist über diese
     Schnittstelle nicht möglich, da Excel-Objekte wie Pivots nicht über
     API-Vorschläge angelegt werden können."

**Der erste Halbsatz stimmte, der zweite ist frei erfunden.** Office.js kann
das seit Langem; gefehlt hat unser Werkzeug. Der Prompt sagte nirgends, was
``excel_vorschlag`` NICHT kann – also riet das Modell und formulierte eine
plausible technische Begründung. Dieselbe Fehlerklasse wie „Die Base64-URL war
zu lang" und „Bildgenerierung ist nicht verfügbar" (CLAUDE.md, Register).

DIE VERSIONEN SIND BELEGT, NICHT GESCHAETZT
-------------------------------------------
Gemessen an der Herstellerdoku (learn.microsoft.com, 2026-09-15):

    pivotTables.add        ExcelApi 1.8   ⚠ ueber unserem Manifest
    charts.add             ExcelApi 1.1
    tables.add             ExcelApi 1.1
    conditionalFormats.add ExcelApi 1.6

Unser Manifest verlangt **1.7** (``excel_addin.EXCEL_API_MIN``). Drei der vier
Typen sind damit auf jedem Client garantiert – nur Pivot nicht.

⚠ **DAS MANIFEST WIRD DAFUER NICHT HOCHGEZOGEN.** Erfuellt ein Client die
``MinVersion`` nicht, laedt das Add-in **gar nicht** und erscheint nicht einmal
unter „Meine Add-Ins". Ein Sprung auf 1.8 waere eine abschaltende Aenderung fuer
jeden mit aelterem Office – fuer ein Feature, das die meisten nie benutzen. Die
Doku empfiehlt ausdruecklich den anderen Weg: *„we recommend that you check for
requirement support at runtime […] instead of defining requirement set support
in the manifest."* Das Fenster prueft deshalb je Eintrag mit
``isSetSupported`` und lehnt EINEN Eintrag mit Grund ab, statt dass das ganze
Add-in verschwindet.

WAS HIER NICHT ENTSCHIEDEN WIRD
-------------------------------
Dieses Modul prueft die FORM eines Eintrags. Ob der Client die noetige
ExcelApi-Fassung hat, weiss nur der Client – ``API_MIN`` ist die Angabe, gegen
die er prueft, und wird mitgeschickt. Eine zweite Fassung dieser Tabelle im
Client waere Drift: das Backend liesse einen Eintrag zu, den das Fenster
danach anders beurteilt.
"""

from __future__ import annotations

import json as _json
import re

# ── Typen und ihre Mindestfassung ─────────────────────────────────────────
# Der Wert ist die BELEGTE ExcelApi-Version (siehe Modulkopf). Er geht mit dem
# Eintrag an das Fenster; dort entscheidet `isSetSupported` darueber.
API_MIN = {
    "pivot": "1.8",
    "diagramm": "1.1",
    "tabelle": "1.1",
    "bedingt": "1.6",
}
TYPEN = tuple(API_MIN)

MAX_NAME_LEN = 80
MAX_TITEL_LEN = 120
MAX_FELDER = 8          # Zeilen-/Spalten-/Wertfelder je Pivot
MAX_BEREICH_LEN = 200

# Ein Quellbereich DARF einen Blattnamen tragen (`Daten!A1:E200`) – anders als
# `adresse`, wo der Blattname ins Feld `blatt` gehoert. Grund: eine Pivot- oder
# Diagrammquelle liegt fast immer auf einem ANDEREN Blatt als das Ergebnis.
_BEREICH_RE = re.compile(
    r"^(?:'([^']{1,120})'|([A-Za-z0-9_äöüÄÖÜß .\-]{1,120}))?!?"
    r"\$?([A-Z]{1,3})\$?([0-9]{1,7})"
    r"(?::\$?([A-Z]{1,3})\$?([0-9]{1,7}))?$"
)

# Excel-Tabellennamen sind ENG geregelt – das ist keine Schikane von uns:
# Leerzeichen sind verboten, das erste Zeichen muss Buchstabe/Unterstrich sein,
# und ein Name in Zellbezugs-Form (`A1`, `XFD1048576`) wird abgelehnt. Wer das
# nicht vorher prueft, bekommt einen Office.js-Wurf zur Laufzeit, dessen
# Meldung („InvalidArgument") niemandem sagt, was zu tun ist.
_TABNAME_RE = re.compile(r"^[A-Za-z_\\][A-Za-z0-9_.äöüÄÖÜß]*$")
_WIE_ZELLE_RE = re.compile(r"^[A-Za-z]{1,3}[0-9]{1,7}$")

# Aggregatfunktionen: Whitelist auf `Excel.AggregationFunction`. Bewusst NICHT
# die ganze Liste des Herstellers – `unknown` und `automatic` sind keine
# Auswahl des Benutzers, sondern Zustaende.
AGGREGATE = {
    "sum": "Sum", "summe": "Sum",
    "count": "Count", "anzahl": "Count",
    "average": "Average", "mittelwert": "Average", "durchschnitt": "Average",
    "max": "Max", "maximum": "Max",
    "min": "Min", "minimum": "Min",
    "product": "Product", "produkt": "Product",
    "countnumbers": "CountNumbers", "anzahlzahlen": "CountNumbers",
}

# Diagrammarten: die Zuordnung deutsch/einfach -> `Excel.ChartType` liegt HIER
# und nicht im Fenster. Eine zweite Tabelle dort waere die Stelle, an der beim
# naechsten Diagrammtyp genau eine Seite nachgezogen wird.
# ⚠ DIE MELDUNGEN NENNEN DIE EINGABE-NAMEN, NICHT DIE OFFICE-WERTE.
# Erste Fassung gab bei einem unbekannten Operator „erlaubt sind: Between,
# EqualTo, GreaterThan …" aus – also die WERTE der Tabelle. Als Eingabe waeren
# die abgelehnt worden (die Schluessel heissen `groesser`, `zwischen`, …): eine
# Fehlermeldung, die einen Weg nennt, der selbst in dieselbe Fehlermeldung
# fuehrt. Und bei den Diagrammarten standen alle 23 Synonyme in einer Zeile.
# Deshalb je Tabelle eine kurze, kuratierte Liste fuer den Menschen.
HAUPT_ARTEN = ("saeule", "saeule_gestapelt", "balken", "balken_gestapelt",
               "linie", "linie_punkte", "kreis", "ring", "punkt", "flaeche")
HAUPT_AGGREGATE = ("sum", "count", "average", "max", "min", "product",
                   "countNumbers")
HAUPT_OPERATOREN = ("groesser", "kleiner", "gleich", "ungleich",
                    "groesser_gleich", "kleiner_gleich", "zwischen",
                    "nicht_zwischen")

DIAGRAMM_ARTEN = {
    "saeule": "ColumnClustered", "säule": "ColumnClustered",
    "spalte": "ColumnClustered", "column": "ColumnClustered",
    "saeule_gestapelt": "ColumnStacked", "säule_gestapelt": "ColumnStacked",
    "balken": "BarClustered", "bar": "BarClustered",
    "balken_gestapelt": "BarStacked",
    "linie": "Line", "line": "Line",
    "linie_punkte": "LineMarkers",
    "kreis": "Pie", "torte": "Pie", "pie": "Pie",
    "ring": "Doughnut", "doughnut": "Doughnut",
    "punkt": "XYScatter", "streu": "XYScatter", "scatter": "XYScatter",
    "flaeche": "Area", "fläche": "Area", "area": "Area",
}

# Regeln der bedingten Formatierung. Bewusst DREI statt der acht Office-Typen:
# jede weitere ist eine weitere Gelegenheit, eine Vorgabe falsch zu setzen, und
# diese drei decken ab, was in einer Tabelle wirklich gefragt wird.
BEDINGT_REGELN = ("zellwert", "farbskala", "datenbalken")

# Operatoren fuer `zellwert` -> `Excel.ConditionalCellValueOperator`.
OPERATOREN = {
    "groesser": "GreaterThan", "größer": "GreaterThan", ">": "GreaterThan",
    "kleiner": "LessThan", "<": "LessThan",
    "gleich": "EqualTo", "=": "EqualTo", "==": "EqualTo",
    "ungleich": "NotEqualTo", "!=": "NotEqualTo", "<>": "NotEqualTo",
    "groesser_gleich": "GreaterThanOrEqual", ">=": "GreaterThanOrEqual",
    "kleiner_gleich": "LessThanOrEqual", "<=": "LessThanOrEqual",
    "zwischen": "Between",
    "nicht_zwischen": "NotBetween",
}
# Die Office-Schreibweise wird ZUSAETZLICH angenommen (kleingeschrieben, weil
# die Eingabe vorher `lower()` durchlaeuft). Ein Modell, das `GreaterThan` aus
# der Office-Doku kennt, soll nicht an einer Vokabelfrage scheitern.
OPERATOREN.update({v.lower(): v for v in list(OPERATOREN.values())})
_ZWEI_WERTE = ("Between", "NotBetween")

_FARBE_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def ist_objekt(eintrag) -> bool:
    """Traegt der Eintrag ein Feld ``typ``?

    ⚠ **DIE VORGABE IST DER ZELL-EINTRAG.** Ein Eintrag OHNE ``typ`` laeuft
    unveraendert durch die bestehende Zell-Pruefung – byte-gleich zu vorher.
    Das ist die fail-safe Richtung: wer das Feld nicht kennt, bekommt das
    Verhalten von gestern.
    """
    if not isinstance(eintrag, dict):
        return False
    return bool(str(eintrag.get("typ") or "").strip())


def _text(wert, grenze: int) -> str:
    return str(wert or "").strip()[:grenze]


def _liste(roh, grenze: int) -> list:
    """Nimmt eine Liste – und einen JSON-STRING, der eine ist.

    Modelle liefern verschachtelte Argumente gelegentlich als Zeichenkette.
    Das hart abzulehnen meldet „keine Felder angegeben", obwohl alles richtig
    gemeint war (dieselbe Toleranz wie bei ``werte`` und ``xlsx_merge``).
    """
    if isinstance(roh, str) and roh.strip()[:1] in ("[", "{"):
        try:
            roh = _json.loads(roh)
        except Exception:  # noqa: BLE001
            return []
    if isinstance(roh, str):
        # Ein einzelnes Feld als blosser Text ist die haeufigste Kurzform.
        return [roh.strip()] if roh.strip() else []
    if not isinstance(roh, list):
        return []
    raus = []
    for x in roh[:grenze]:
        if isinstance(x, (str, int, float)):
            s = str(x).strip()
            if s:
                raus.append(s)
        elif isinstance(x, dict):
            raus.append(x)
    return raus


def bereich_pruefen(text: str) -> str:
    """Prueft einen Quellbereich (mit optionalem Blattnamen).

    Rueckgabe: Fehlergrund oder ``""``.
    """
    t = (text or "").strip()
    if not t:
        return "Kein Quellbereich angegeben."
    if len(t) > MAX_BEREICH_LEN:
        return "Der Quellbereich ist zu lang."
    if not _BEREICH_RE.match(t):
        return ("%r ist kein gültiger Bereich (erwartet z. B. 'Daten!A1:E200' "
                "oder 'A1:E200')." % t[:60])
    return ""


def _name_pruefen(name: str, typ: str) -> str:
    if not name:
        return "Kein Name angegeben."
    if len(name) > MAX_NAME_LEN:
        return "Der Name ist zu lang (höchstens %d Zeichen)." % MAX_NAME_LEN
    if typ == "tabelle":
        if _WIE_ZELLE_RE.match(name):
            return ("%r sieht aus wie ein Zellbezug – Excel lässt das als "
                    "Tabellenname nicht zu." % name)
        if not _TABNAME_RE.match(name):
            return ("%r ist kein gültiger Tabellenname – erlaubt sind "
                    "Buchstaben, Ziffern, Punkt und Unterstrich, und das erste "
                    "Zeichen darf keine Ziffer sein (kein Leerzeichen)." % name)
    return ""


# ── Die vier Typen ────────────────────────────────────────────────────────
def _pivot(e: dict, ziel: dict) -> str:
    quelle = _text(e.get("quelle"), MAX_BEREICH_LEN)
    grund = bereich_pruefen(quelle)
    if grund:
        return grund
    name = _text(e.get("name"), MAX_NAME_LEN + 10)
    grund = _name_pruefen(name, "pivot")
    if grund:
        return grund

    zeilen = _liste(e.get("zeilenfelder"), MAX_FELDER)
    spalten = _liste(e.get("spaltenfelder"), MAX_FELDER)
    werte_roh = _liste(e.get("wertfelder"), MAX_FELDER)

    # ⚠ OHNE WERTFELD IST EINE PIVOT-TABELLE LEER. Das waere kein Fehler von
    # Office.js, sondern ein Ergebnis, das aussieht wie ein Fehler – und der
    # Benutzer haette es bestaetigt.
    if not werte_roh:
        return ("Eine Pivot-Tabelle braucht mindestens ein Wertfeld "
                "('wertfelder', z. B. [{\"feld\":\"Umsatz\",\"funktion\":\"sum\"}]).")
    if not zeilen and not spalten:
        return ("Eine Pivot-Tabelle braucht mindestens ein Zeilen- oder "
                "Spaltenfeld ('zeilenfelder' / 'spaltenfelder').")

    wertfelder = []
    for w in werte_roh:
        if isinstance(w, dict):
            feld = _text(w.get("feld") or w.get("name"), MAX_NAME_LEN)
            funk = str(w.get("funktion") or w.get("aggregat") or "sum").strip().lower()
        else:
            feld, funk = _text(w, MAX_NAME_LEN), "sum"
        if not feld:
            return "Ein Eintrag in 'wertfelder' hat keinen Feldnamen."
        if funk not in AGGREGATE:
            return ("%r ist keine bekannte Funktion – erlaubt sind: %s."
                    % (funk[:30], ", ".join(HAUPT_AGGREGATE)))
        wertfelder.append({"feld": feld, "funktion": AGGREGATE[funk]})

    ziel["name"] = name
    ziel["quelle"] = quelle
    ziel["zeilenfelder"] = [x for x in zeilen if isinstance(x, str)]
    ziel["spaltenfelder"] = [x for x in spalten if isinstance(x, str)]
    ziel["wertfelder"] = wertfelder
    return ""


def _diagramm(e: dict, ziel: dict) -> str:
    quelle = _text(e.get("quelle"), MAX_BEREICH_LEN)
    grund = bereich_pruefen(quelle)
    if grund:
        return grund
    art = str(e.get("art") or e.get("diagrammart") or "saeule").strip().lower()
    if art not in DIAGRAMM_ARTEN:
        return ("%r ist keine bekannte Diagrammart – erlaubt sind: %s."
                % (art[:30], ", ".join(HAUPT_ARTEN)))
    ziel["art"] = DIAGRAMM_ARTEN[art]
    ziel["quelle"] = quelle
    titel = _text(e.get("titel"), MAX_TITEL_LEN)
    if titel:
        ziel["titel"] = titel
    name = _text(e.get("name"), MAX_NAME_LEN)
    if name:
        ziel["name"] = name
    return ""


def _tabelle(e: dict, ziel: dict) -> str:
    name = _text(e.get("name"), MAX_NAME_LEN + 10)
    grund = _name_pruefen(name, "tabelle")
    if grund:
        return grund
    ziel["name"] = name
    # `kopfzeile` ist eine Zusage ueber die DATEN, nicht ueber die Optik: sagt
    # sie faelschlich `false`, macht Excel aus der Ueberschriftenzeile eine
    # Datenzeile. Vorgabe `true`, weil eine Tabelle mit Ueberschriften der
    # Normalfall ist – und `is False` statt Falsyness, damit ein fehlendes
    # Feld nicht als „nein" gilt.
    ziel["kopfzeile"] = e.get("kopfzeile") is not False
    stil = _text(e.get("stil"), 60)
    if stil:
        ziel["stil"] = stil
    return ""


def _bedingt(e: dict, ziel: dict) -> str:
    regel = str(e.get("regel") or "zellwert").strip().lower()
    if regel not in BEDINGT_REGELN:
        return ("%r ist keine bekannte Regel – erlaubt sind: %s."
                % (regel[:30], ", ".join(BEDINGT_REGELN)))
    ziel["regel"] = regel

    if regel == "zellwert":
        op = str(e.get("operator") or "groesser").strip().lower()
        if op not in OPERATOREN:
            return ("%r ist kein bekannter Operator – erlaubt sind: %s."
                    % (op[:30], ", ".join(HAUPT_OPERATOREN)))
        ziel["operator"] = OPERATOREN[op]
        wert = e.get("wert")
        if wert in (None, ""):
            return "Für die Regel 'zellwert' fehlt der Vergleichswert ('wert')."
        ziel["wert"] = _text(wert, 120)
        if ziel["operator"] in _ZWEI_WERTE:
            wert2 = e.get("wert2")
            if wert2 in (None, ""):
                return ("Der Operator %r braucht einen zweiten Wert ('wert2')."
                        % ziel["operator"])
            ziel["wert2"] = _text(wert2, 120)
        for feld in ("farbe", "textfarbe"):
            f = _text(e.get(feld), 20)
            if f:
                if not _FARBE_RE.match(f):
                    return ("%r ist keine Farbe – erwartet wird #RRGGBB." % f[:20])
                ziel[feld] = f.upper()
        # Ohne jede Farbe waere die Regel unsichtbar: sie greift, und man sieht
        # nichts. Vorgabe ist das rote Standardpaar, das Excel selbst anbietet.
        if "farbe" not in ziel and "textfarbe" not in ziel:
            ziel["farbe"] = "#FFC7CE"
            ziel["textfarbe"] = "#9C0006"
    else:
        # Farbskala und Datenbalken brauchen keinen Vergleichswert – Excel
        # leitet die Grenzen aus den Daten ab.
        f = _text(e.get("farbe"), 20)
        if f:
            if not _FARBE_RE.match(f):
                return "%r ist keine Farbe – erwartet wird #RRGGBB." % f[:20]
            ziel["farbe"] = f.upper()
    return ""


_PRUEFER = {
    "pivot": _pivot,
    "diagramm": _diagramm,
    "tabelle": _tabelle,
    "bedingt": _bedingt,
}


def objekt_pruefen(eintrag: dict, blatt: str, adresse: str) -> tuple[dict | None, str]:
    """Prueft EINEN Objekt-Eintrag.

    ``blatt``/``adresse`` sind bereits von ``excel_ask`` geprueft – die Adresse
    ist bei Pivot und Diagramm die ZIELZELLE (obere linke Ecke), bei Tabelle
    und bedingter Formatierung der BEREICH.

    Rueckgabe ``(sauber, "")`` oder ``(None, grund)``.
    """
    typ = str(eintrag.get("typ") or "").strip().lower()
    if typ not in _PRUEFER:
        return (None, "%r ist kein bekannter Eintragstyp – erlaubt sind: %s."
                % (typ[:30], ", ".join(TYPEN)))

    sauber: dict = {"typ": typ, "blatt": blatt, "adresse": adresse,
                    "api_min": API_MIN[typ]}
    grund = _PRUEFER[typ](eintrag, sauber)
    if grund:
        return (None, grund)
    if eintrag.get("begruendung"):
        sauber["begruendung"] = str(eintrag["begruendung"])[:300]
    return (sauber, "")


def kurzfassung(e: dict) -> str:
    """Eine Zeile fuer Protokoll und Anzeige – ohne die Nutzdaten zu wiederholen."""
    typ = e.get("typ", "?")
    if typ == "pivot":
        return "Pivot %r aus %s" % (e.get("name", ""), e.get("quelle", ""))
    if typ == "diagramm":
        return "Diagramm %s aus %s" % (e.get("art", ""), e.get("quelle", ""))
    if typ == "tabelle":
        return "Tabelle %r" % e.get("name", "")
    if typ == "bedingt":
        return "Bedingte Formatierung (%s)" % e.get("regel", "")
    return typ
