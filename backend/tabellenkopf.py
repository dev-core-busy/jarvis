"""Kopfzeile und Datenanfang einer Tabelle bestimmen – EINE Regel, zwei Aufrufer.

WARUM DIESES MODUL EXISTIERT
-----------------------------
Die Regel stand bis 2026-09-08 nur in ``skills/office/tabellen.py`` und arbeitete
dort auf einem **openpyxl-Worksheet**. Das Excel-Add-in braucht sie genauso – dort
liegen die Werte aber als Listen aus dem Client (Office.js), nicht als Worksheet.
Eine zweite Fassung waere beim naechsten Feinschliff auseinandergelaufen: dann
liest der Datei-Weg die Kopfzeile anders als das Add-in, und niemand kann
erklaeren, warum dieselbe Mappe zwei verschiedene Spaltennamen ergibt.

Der Kern steht deshalb HIER, ohne jede Abhaengigkeit (auch nicht auf openpyxl):
``skills/office/tabellen.py`` sammelt die Zeilen und ruft ihn, ``backend/excel_ask.py``
baut sie aus den Client-Werten und ruft denselben Kern.

**Bewusst in ``backend/``, nicht im Office-Skill:** ein Skill ist abschaltbar und
deinstallierbar (Skill-Audit 2026-08-10). Ein Import aus ``skills.office`` in
``backend/`` waere eine Kopplung an einen Schalter – nach einem Purge ist der
Ordner weg und der Import ein 500er.

DIE REGEL – und warum sie so und nicht einfacher ist
-----------------------------------------------------
An der echten Datei von ECHT gemessen (13 Blaetter, alle UNTERSCHIEDLICH gebaut):

    Blatt 2004  Z1 = Kopfzeile,                        Daten ab Z2
    Blatt 2015  Z1 = Nummerncodes, Z2 leer, Z3 = Kopf, Daten ab Z4
    Blatt 2019  Z1 = Kopf, Z2 leer, Z3 = Kopf als FORMEL (=B1), Daten ab Z4

Mit der festen Vorgabe "Zeile 1" liest man in Blatt 2015 eine Liste von Nummern
als Spaltennamen – und findet anschliessend keinen einzigen Schluessel. Mit
"Zeile 2" (die Vorgabe des Add-ins bis heute) traf es 9 von 13 Blaettern nicht.

**Beschriftungszeile und Datenanfang sind ZWEI verschiedene Dinge.** Der ANKER
ist der Datenanfang (erste ueberwiegend numerische Zeile); die Beschriftung ist
die unterste brauchbare Zeile darueber. Bei zwei Kopfzeilen gewinnt die UNTERE –
sie steht unmittelbar ueber den Daten, und die Zeilen dazwischen wuerden sonst
als Datenzeilen mitgelesen.

**ENTSCHEIDEND IST DER TYP, NICHT DER AUGENSCHEIN:** gezaehlt wird nur
``int``/``float``. In Blatt 2015 stehen in Zeile 1 Werte wie ``"00000000083"`` –
als TEXT gespeichert. Wer sie als Zahl zaehlt, haelt Zeile 1 fuer den
Datenanfang und landet wieder bei der falschen Kopfzeile. Aus demselben Grund
darf der Aufrufer Zahlen NICHT als Zeichenkette uebergeben.
"""

from __future__ import annotations

# Wie viele Zeilen am Blattanfang angesehen werden. Tiefer zu suchen kostet
# nichts und bringt nichts: eine Kopfzeile unterhalb von Zeile 12 ist in echten
# Mappen keine Kopfzeile mehr, sondern ein Abschnittstitel.
KOPF_SUCHTIEFE = 12


def hat_beschriftungen(row) -> bool:
    """Enthaelt die Zeile echte Spaltennamen?

    Echt heisst: Text, der WEDER eine Formel (``=B1``) NOCH eine reine Zahl ist.
    Die Formel-Bedingung stammt aus der echten Datei von ECHT: in den Blaettern
    2019-2026 ist die wiederholte Kopfzeile in Zeile 3 keine Beschriftung,
    sondern ein VERWEIS auf Zeile 1 (``=B1``, ``=C1``, …) – als Spaltenname
    unbrauchbar.
    """
    gefuellt = [c for c in row if c is not None and str(c).strip() != ""]
    if len(gefuellt) < 2:
        return False
    echte = [c for c in gefuellt
             if isinstance(c, str)
             and not c.lstrip().startswith("=")
             and not c.strip().replace(".", "").replace(",", "").isdigit()]
    return len(echte) / len(gefuellt) >= 0.5


def kopf_und_daten(zeilen: list) -> tuple[int, int]:
    """Liefert ``(Beschriftungszeile, erste Datenzeile)``, 1-basiert.

    ``zeilen`` ist eine Liste von Zeilen (Listen oder Tupel) in Blattreihenfolge,
    beginnend bei Zeile 1. Zahlen MUESSEN als ``int``/``float`` vorliegen – siehe
    die Typ-Begruendung im Modulkopf.

    **Fail-safe auf ``(1, 2)``**: findet sich kein Datenanfang (reine
    Texttabelle) oder beginnen die Daten schon in Zeile 1, ist Zeile 1 die beste
    verfuegbare Annahme. Das ist genau das Verhalten von vorher – eine
    Erkennung, die im Zweifel etwas anderes behauptet, waere schlechter als die
    alte feste Vorgabe.
    """
    if not zeilen:
        return 1, 2

    nummeriert = [(i, r) for i, r in enumerate(zeilen[:KOPF_SUCHTIEFE], start=1)
                  if isinstance(r, (list, tuple))]
    if not nummeriert:
        return 1, 2

    erste_daten = 0
    for i, row in nummeriert:
        gefuellt = [c for c in row if c is not None and str(c).strip() != ""]
        if len(gefuellt) < 3:          # zu duenn, um den Datenanfang zu belegen
            continue
        zahlen = [c for c in gefuellt
                  if isinstance(c, (int, float)) and not isinstance(c, bool)]
        if len(zahlen) / len(gefuellt) >= 0.5:
            erste_daten = i
            break

    if erste_daten <= 1:
        return 1, 2

    ueber = list(reversed(nummeriert[: erste_daten - 1]))
    for i, row in ueber:
        if hat_beschriftungen(row):
            return i, erste_daten
    # Keine brauchbare Beschriftung gefunden: die letzte nicht-leere Zeile ist
    # immer noch die beste Annahme (besser als blind Zeile 1).
    for i, row in ueber:
        if any(c is not None and str(c).strip() != "" for c in row):
            return i, erste_daten
    return 1, erste_daten
