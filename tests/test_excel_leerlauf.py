#!/usr/bin/env python3
"""Waechter: ein Excel-Lauf ohne Ergebnis beschuldigt nicht den Benutzer.

DER BEZAHLTE VORFALL (2026-10-23). Der Benutzer bekam im Aufgabenfenster:

    „Der Assistent hat keine Antwort formuliert. Formuliere die Frage bitte
     anders."

und im Protokoll GENAU EINE Zeile – „Excel bereit, ExcelApi 1.8=true …". Also
eine Schuldzuweisung plus ein Protokoll, mit dem sich nichts nachvollziehen
liess. Die Ursache war unser eigener Rundendeckel: das Modell hatte eine
Nachforderung (``[[EXCEL_BRAUCHE: …]]``) geschrieben, der Endpunkt verwirft sie
in der letzten Runde, und weil sonst nichts in der Antwort stand, blieb nach
dem Entfernen des Markers eine LEERE Zeichenkette.

⚠ DIE KETTE WAR SELBSTVERSCHULDET UND FRISCH: der Hinweis auf gekuerzte
Spaltenlisten (Commit 08686781, derselbe Tag) sagt dem Modell ausdruecklich,
dass Nachfordern bei breiten Tabellen „Pflicht, keine Option" ist – er hat die
Nachforderung also erst wahrscheinlich gemacht. Ein Fix, der einen neuen Pfad
oeffnet, muss dessen Enden mitpruefen.

GEPRUEFT WERDEN DREI ZUSAGEN, JEDE EINZELN:
  1. In der LETZTEN Runde sagt der Auftrag dem Modell, dass eine Nachforderung
     wirkungslos verfaellt (Fix an der Wurzel).
  2. Verwirft der Endpunkt trotzdem eine Nachforderung, entsteht ein LESBARER
     Satz statt einer leeren Antwort (Guertel).
  3. Der Grund geht als eigenes Feld hinaus, damit das Fenster nicht raet.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def check(text: str, bedingung) -> None:
    """(Beschreibung, Bedingung) – NIE andersherum."""
    global _ok, _fail
    if not isinstance(text, str) or isinstance(bedingung, str):
        print("ABBRUCH: check(Beschreibung, Bedingung) – Argumente vertauscht")
        sys.exit(2)
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print("  FAIL: " + text)


try:
    from backend import excel_ask as ea
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend/excel_ask.py nicht importierbar: %r" % (e,))
    sys.exit(2)

for n in ("auftrag", "nachforderung_lesen", "max_runden"):
    if not hasattr(ea, n):
        print("ABBRUCH: excel_ask.%s fehlt" % n)
        sys.exit(2)

UEB = {"name": "Mappe.xlsx", "blaetter": [
    {"name": "2026", "bereich": "A20:IH500", "zeilen": 481, "spalten": 242,
     "zeile_ab": 20, "spalte_ab": 1, "kopfRel": 1, "datenRel": 2,
     "probe": [["K%d" % k for k in range(1, 41)], [1] * 40]}]}

# ── 0. Positivkontrolle: tritt der Fehlerfall ohne den Fix WIRKLICH ein? ──
# ⚠ OHNE DIESEN BELEG IST ALLES DARUNTER EINE BEHAUPTUNG. Nachgebaut wird die
# Kette des Endpunkts: Modellantwort = NUR der Marker -> nachforderung_lesen
# -> Text leer. Genau das machte das Fenster zu "formuliere die Frage anders".
print("── 0. Positivkontrolle: der gemeldete Fall ist echt ────────────────")
_nur_marker = "[[EXCEL_BRAUCHE: 2026!AO20:IH21]]"
_text, _brauche = ea.nachforderung_lesen(_nur_marker)
if _text.strip():
    print("ABBRUCH: nachforderung_lesen laesst Text uebrig (%r) – die zu "
          "pruefende Lage (leere Antwort) entsteht gar nicht" % _text[:60])
    sys.exit(2)
if not _brauche:
    print("ABBRUCH: der Marker wurde nicht als Nachforderung erkannt – der "
          "Messaufbau trifft den gemeldeten Fall nicht")
    sys.exit(2)
check("eine Antwort aus NUR einem Marker ergibt leeren Text", True)
check("...und die Nachforderung wird erkannt", _brauche == ["2026!AO20:IH21"])

print("── 1. Der Auftrag warnt VOR der letzten Runde ──────────────────────")
a_normal, _ = ea.auftrag("Übertrage alle Spalten", UEB)
a_letzte, _ = ea.auftrag("Übertrage alle Spalten", UEB, letzte_runde=True)
check("ohne letzte_runde steht kein Hinweis darin",
      "LETZTE RUNDE" not in a_normal)
check("mit letzte_runde steht er darin", "LETZTE RUNDE" in a_letzte)
check("er sagt, dass die Nachforderung NICHT ausgefuehrt wird",
      "NICHT mehr ausgeführt" in a_letzte)
check("er nennt den Marker, um den es geht", "EXCEL_BRAUCHE" in a_letzte)
check("er verlangt eine Antwort mit dem Vorhandenen",
      "mit dem, was du hast" in a_letzte)
# Das Entscheidende: das Modell soll SAGEN, was fehlte – sonst ist die Antwort
# zwar nicht leer, aber genauso wenig brauchbar.
check("er verlangt, die Luecke zu benennen",
      "welche Daten dir fehlten" in a_letzte)
check("er benennt die Folge einer leeren Antwort",
      "leere Antwort" in a_letzte)
# Code-Review 2026-10-25: bei max_runden=1 stand "Nachfordern ist Pflicht"
# neben "Nachforderung verfaellt" – ohne Vorrangregel ein Widerspruch.
check("die letzte Runde hat ausdruecklich VORRANG vor der Nachforder-Pflicht",
      "VORRANG" in a_letzte and "als offen" in a_letzte)
# ⚠ DIE STELLUNG IST SEMANTIK: der Hinweis muss VOR der Frage stehen, wie alle
# Regeln dieses Auftrags (das Register haelt den umgekehrten Fall – eine
# Stilvorgabe VOR der Regel hob die Ausloesebedingung auf).
i_hinweis = a_letzte.find("LETZTE RUNDE")
i_frage = a_letzte.find("FRAGE DES BENUTZERS")
check("der Hinweis steht VOR der Frage", 0 <= i_hinweis < i_frage)
# Und der Rest des Auftrags bleibt unberuehrt: ein Zusatz, der den Bestand
# verschiebt, ist ein neuer Fehler.
check("der Ueberblick bleibt im Auftrag", "ÜBERBLICK ÜBER DIE MAPPE" in a_letzte)
check("die Echtheitskennung bleibt", "ECHTHEITSKENNUNG" in a_letzte)
check("der Auftrag ohne letzte Runde ist sonst gleich lang",
      abs(len(a_letzte) - len(a_normal)) < 1200)

print("── 2. REGEL: der Endpunkt laesst die Leere nicht durch ─────────────")
# Gemessen wird am Quelltext des Endpunkts – ein Lauf braeuchte ein Modell.
# Geprueft wird die EIGENSCHAFT (es gibt einen Zweig, der bei leerem Text UND
# verworfener Nachforderung einen Text setzt), nicht eine Formulierung.
MAIN = (ROOT / "backend" / "main.py").read_text()
i = MAIN.find('@app.post("/api/excel/ask")')
if i < 0:
    print("ABBRUCH: Endpunkt /api/excel/ask nicht gefunden")
    sys.exit(2)
# Funktionsschnitt bis zum naechsten Dekorator – ein festes Zeichenfenster
# waere die Zeitbombe, die das Register beschreibt.
j = MAIN.find("\n@app.", i + 10)
BLOCK = MAIN[i:j if j > 0 else len(MAIN)]
check("der Endpunkt merkt sich die verworfene Nachforderung",
      "verworfen = list(brauche)" in BLOCK)
check("er prueft auf leeren Text UND fehlende Eintraege",
      re.search(r"if not text and not aenderungen", BLOCK) is not None)
check("er setzt bei verworfener Nachforderung einen Text",
      re.search(r"if verworfen:\s*\n\s*grund = \"runden_erschoepft\"\s*\n\s*text = ",
                BLOCK) is not None)
check("der Text nennt die Grenze als UNSERE, nicht die des Benutzers",
      "nicht ein Fehler deiner Frage" in BLOCK)
check("er nennt den Deckel mit Zahl", "grenze_runden)" in BLOCK)
check("er nennt dem Benutzer einen naechsten Schritt",
      "kleineren Bereich" in BLOCK)
check("ein stummes Modell wird unterschieden", '"modell_stumm"' in BLOCK)
# Code-Review 2026-10-25: alles abgelehnt ist KEIN stummes Modell – sonst
# stuende "hat nichts geantwortet" direkt unter der Ablehnungsliste.
_m_ab = re.search(r"if abgelehnt:\s*\n(?:\s*#[^\n]*\n)*\s*grund = \"alles_abgelehnt\"\s*\n\s*text = ",
                  BLOCK)
check("alles abgelehnt: eigener Grund MIT Text", _m_ab is not None)
check("...und dieser Zweig kommt VOR 'modell_stumm'",
      _m_ab is not None and _m_ab.start() < BLOCK.find('grund = "modell_stumm"'))
check("eine Antwort aus nur Markern wird unterschieden", '"nur_marker"' in BLOCK)

print("── 3. Der Grund geht hinaus, das Fenster raet nicht ────────────────")
check("das Feld 'grund' steht in der Antwort", '"grund": grund' in BLOCK)
check("die verworfenen Bereiche gehen mit", '"verworfen": verworfen' in BLOCK)
check("die Rohlaenge geht mit (Diagnose)", '"rohlaenge"' in BLOCK)
check("der Fall wird ins Journal geschrieben",
      "[excel] Lauf ohne Ergebnis" in BLOCK)
check("die Journal-Zeile nennt Grund, Runde und Rohlaenge",
      "grund=%s runde=%d/%d" in BLOCK and "rohlaenge=%d" in BLOCK)

print("── 4. letzte_runde wird WIRKLICH uebergeben ────────────────────────")
# ⚠ EIN PARAMETER, DEN NIEMAND SETZT, IST TOTER CODE MIT ANSCHEIN. Hier wird
# die Verbindung gemessen, nicht die Existenz.
check("der Endpunkt uebergibt letzte_runde",
      "letzte_runde=runde >= grenze_runden" in BLOCK)
check("...und liest den Deckel VOR dem Lauf",
      BLOCK.find("grenze_runden = excel_ask.max_runden()") <
      BLOCK.find("letzte_runde=runde >= grenze_runden"))

print("── 5. Das Fenster protokolliert JEDEN Lauf ─────────────────────────")
JS = (ROOT / "frontend" / "excel-addin" / "excel.js").read_text()
check("es gibt eine Protokollzeile je Runde", "protokoll('lauf'," in JS)
for feld in ("runde ", "text=", "eintraege=", "grund="):
    check("die Zeile nennt %r" % feld, feld in JS)
check("sie nennt eine verworfene Nachforderung",
      "VERWORFEN=" in JS)
check("ein unlesbarer Bereich wird protokolliert",
      "nachgeforderter Bereich nicht lesbar" in JS)

def ohne_kommentare(js: str) -> str:
    """Ersetzt Kommentar-BEREICHE durch Leerzeichen, Zeichen fuer Zeichen.

    ⚠ ERST AUSGELASSEN, DANN BEZAHLT: ohne diesen Schritt meldete Abschnitt 6
    einen Befund, der aus MEINEM EIGENEN Kommentar stammte – der zitiert die
    alte Schuldzuweisung, um zu erklaeren, warum sie weg ist (Register: ein
    Waechter, der seine eigene Begruendung liest, prueft nichts).

    Es wird nicht zusammengefuegt, sondern ersetzt: ein Entferner, der Tokens
    neu verbindet, zerlegt jeden mehrzeiligen Ausdruck und erzeugt Fehler, die
    es im Code nicht gibt (derselbe Vorfall, andere Haelfte). Zeichenketten
    bleiben unangetastet, sonst verschwaende die Pruefung genau die Texte, um
    die es geht.
    """
    raus = []
    i, n_ = 0, len(js)
    quote = None
    while i < n_:
        c = js[i]
        if quote:
            raus.append(c)
            if c == "\\" and i + 1 < n_:
                raus.append(js[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            quote = c
            raus.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n_ and js[i + 1] == "/":
            while i < n_ and js[i] != "\n":
                raus.append(" ")
                i += 1
            continue
        if c == "/" and i + 1 < n_ and js[i + 1] == "*":
            while i < n_ and not (js[i] == "*" and i + 1 < n_ and js[i + 1] == "/"):
                raus.append("\n" if js[i] == "\n" else " ")
                i += 1
            raus.append("  ")
            i += 2
            continue
        raus.append(c)
        i += 1
    return "".join(raus)


print("── 6. Die Meldung beschuldigt den Benutzer nicht mehr ──────────────")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text()
JS_CODE = ohne_kommentare(JS)
# Positivkontrolle des Werkzeugs: es muss den Kommentar WIRKLICH entfernen und
# die Zeichenketten WIRKLICH behalten. Ohne diesen Beleg ist die Pruefung
# darunter von einem Werkzeugfehler nicht zu unterscheiden.
if "Formuliere die Frage bitte anders" in JS_CODE:
    print("ABBRUCH: ohne_kommentare() entfernt den Kommentar nicht – die "
          "Pruefung wuerde die eigene Begruendung lesen")
    sys.exit(2)
if "protokoll('lauf'," not in JS_CODE or "xl.empty_model" not in JS_CODE:
    print("ABBRUCH: ohne_kommentare() hat Code oder Zeichenketten zerstoert")
    sys.exit(2)
check("das Kommentar-Werkzeug ist belegt (entfernt Kommentar, behaelt Code)", True)
# Die alte Formulierung war die Schuldzuweisung – sie darf nirgends mehr stehen.
check("'Formuliere die Frage bitte anders' ist weg (i18n)",
      "Formuliere die Frage bitte anders" not in I18N)
check("...und auch im Fenster-Fallback (ohne Kommentare gemessen)",
      "Formuliere die Frage bitte anders" not in JS_CODE)
check("die neue Meldung relativiert ausdruecklich",
      "muss nicht an deiner Frage liegen" in I18N)
check("ein stummes Modell hat eine eigene Meldung", "'xl.empty_model'" in I18N)
check("...die die Schuld ausdruecklich abweist",
      "liegt nicht an deiner Frage" in I18N)
check("eine unlesbare Nachforderung hat eine eigene Meldung",
      "'xl.range_unreadable'" in I18N)
check("sie nennt den Bereich", "{b}" in I18N)
# Beide Sprachen – ein fehlender EN-Wert zeigt dem Benutzer den Schluessel.
for key in ("xl.empty_model", "xl.empty_marker", "xl.range_unreadable"):
    check("%s ist in BEIDEN Sprachen gesetzt" % key,
          I18N.count("'%s':" % key) >= 2)
# Und das Fenster unterscheidet die Faelle wirklich, statt einen Text zu zeigen.
check("das Fenster verzweigt ueber d.grund", "d.grund === 'modell_stumm'" in JS)
check("...und kennt den Marker-Fall", "d.grund === 'nur_marker'" in JS)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
