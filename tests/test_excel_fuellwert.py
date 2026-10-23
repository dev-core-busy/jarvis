#!/usr/bin/env python3
"""Waechter: ein Platzhalterwert ueber einen grossen Bereich wird ABGELEHNT.

DER BEZAHLTE VORFALL (2026-10-23, dritter Anlauf am selben Tag). Nachdem der
Spalten-Deckel gefallen war, sah das Modell alle 243 Koepfe – und fuellte die
Koepfe ohne Partner mit Nullen:

    [schreiben] [0] 2026!AU12:II12  wert  bereich=1x197
    [schreiben] [1] 2026!F12:II12   wert  bereich=1x238
    [schreiben] [3] 2026!F12:II12   wert  bereich=1x238
    [antwort]   „Fehlende Uebereinstimmungen wurden mit 0 befuellt."

``wert`` setzt EINEN Wert in JEDE Zelle des Bereichs. Das sind 238 Zellen mit
einer erfundenen Null – und eine Null ist spaeter nicht von einem Messwert zu
unterscheiden.

⚠ DAS VERBOT STAND ZU DIESEM ZEITPUNKT SCHON IM PROMPT und wurde ignoriert.
Ein Prompt ist eine Bitte, kein Riegel: die Grenze gehoert in die PRUEFUNG.
Der Ablehnungsgrund nennt den Weg (Zellen weglassen, offene Spalten nennen)
und geht an das Modell zurueck, das im selben Lauf korrigieren kann.

ZWEITE ZUSAGE: eine TRANSPONIERTE Wertematrix ist kein Fehler, solange sie
eindeutig ist (4x1 fuer einen Bereich 1x4) – aber 2x3 gegen 3x2 wird NICHT
geraten, dort waere jede Zuordnung eine Erfindung.
"""
from __future__ import annotations

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

for n in ("aenderungen_pruefen", "_ist_fuellwert", "MAX_FUELL_ZELLEN",
          "_matrix_pruefen", "_VORSPANN"):
    if not hasattr(ea, n):
        print("ABBRUCH: excel_ask.%s fehlt" % n)
        sys.exit(2)

DECKEL = ea.MAX_FUELL_ZELLEN


def pruef(eintrag):
    gut, weg = ea.aenderungen_pruefen([eintrag])
    return (gut[0] if gut else None,
            (weg[0].get("grund") or "") if weg else "")


# ── 0. Positivkontrolle: entsteht der gemeldete Fall ueberhaupt? ──────────
# Ohne diesen Beleg sind alle Pruefungen trivial wahr – ein Bereich, der den
# Deckel nicht ueberschreitet, braucht keinen Riegel.
print("── 0. Positivkontrolle des Messaufbaus ─────────────────────────────")
_gross = {"blatt": "2026", "adresse": "F12:II12", "wert": 0}
_s, _g = pruef(_gross)
_zellen = 0
m = ea._ADR_RE.match("F12:II12")
if m:
    c1 = ea._spalte_zu_index(m.group(1))
    c2 = ea._spalte_zu_index(m.group(3))
    _zellen = abs(c2 - c1) + 1
# ⚠ ZWEI URSACHEN, ZWEI ANTWORTEN – zum DRITTEN Mal an einem Tag dieselbe
# Falle: ein Guard mit `sys.exit(2)` verwandelt einen Produktbefund in
# "konnte nicht laufen", und ein abgebrochener Lauf ist von einem bestandenen
# nicht zu unterscheiden. Hier sind es:
#   (a) der Deckel ist unbrauchbar hoch -> PRODUKTBEFUND (FAIL mit Zahlen),
#   (b) der Probebereich ist zu klein   -> kaputter MESSAUFBAU (Exit 2).
# Der erste Entwurf behandelte beides als (b); die Gegenprobe
# "Deckel so hoch, dass er nie greift" meldete deshalb BRICHT AB statt zu
# beissen.
PLAUSIBEL = 200     # ein Riegel gegen Luecken-Fuellen liegt weit darunter
if DECKEL > PLAUSIBEL:
    check("MAX_FUELL_ZELLEN ist eine wirksame Grenze (ist %d, erwartet <= %d – "
          "so hoch greift der Riegel praktisch nie)" % (DECKEL, PLAUSIBEL),
          False)
elif _zellen <= DECKEL:
    print("ABBRUCH: der Probebereich hat nur %d Zellen, der Deckel liegt bei "
          "%d (und ist plausibel) – die zu pruefende Lage entsteht gar nicht"
          % (_zellen, DECKEL))
    sys.exit(2)
else:
    check("der Probebereich ist gross genug (%d Zellen, Deckel %d)"
          % (_zellen, DECKEL), True)

print("── 1. DER GEMELDETE FALL wird abgelehnt ────────────────────────────")
check("0 über 238 Zellen wird NICHT übernommen", _s is None)
check("...und es gibt einen Grund", bool(_g))
check("der Grund nennt die Zahl der Zellen", str(_zellen) in _g)
# Die Schuld gehoert nicht zum Benutzer und nicht zur Tabelle.
check("der Grund erklaert die GEFAHR (erfundene 0 wie ein Messwert)",
      "Messwert" in _g)
check("der Grund nennt den WEG (Zellen weglassen)", "WEG" in _g)
check("...und verlangt, die offenen Spalten zu nennen", "Antwort" in _g)
check("...und nennt die Ausnahme (werte-Matrix)", "'werte'" in _g)
s2, g2 = pruef({"blatt": "2026", "adresse": "AU12:II12", "wert": 0})
check("der zweite gemeldete Eintrag (197 Zellen) ebenso", s2 is None)

print("── 2. Welche Werte als Platzhalter gelten ──────────────────────────")
for w in (0, 0.0, "", "0", " ", "-", "n/a", "N/A", False, "null"):
    s, g = pruef({"blatt": "2026", "adresse": "F12:II12", "wert": w})
    check("Platzhalter %r wird abgelehnt" % (w,), s is None)
# ⚠ DIE GEGENRICHTUNG IST DIE WICHTIGERE: ein ECHTER Wert muss durchgehen,
# sonst ist der Riegel eine Funktionssperre. "0,00 €" ist ein Text, keine Null.
for w in (42, 1.5, "Text", "0,00 €", True, "0x", "00"):
    s, g = pruef({"blatt": "2026", "adresse": "F12:II12", "wert": w})
    check("echter Wert %r geht durch" % (w,), s is not None)

print("── 3. Der Deckel ist eine GRENZE, keine Sperre ─────────────────────")
# Bewusstes Nullsetzen weniger Zellen bleibt moeglich – sonst waere eine
# voellig normale Aufgabe ("setze D5:D9 auf 0") nicht mehr erfuellbar.
s, g = pruef({"blatt": "2026", "adresse": "D5:D9", "wert": 0})
check("0 in 5 Zellen bleibt erlaubt", s is not None)
s, g = pruef({"blatt": "2026", "adresse": "A1", "wert": 0})
check("0 in EINER Zelle bleibt erlaubt", s is not None)
# Genau an der Grenze: der Deckel selbst ist noch erlaubt.
letzte = ea.spaltenbuchstabe(DECKEL)
s, g = pruef({"blatt": "2026", "adresse": "A1:%s1" % letzte, "wert": 0})
check("genau %d Zellen sind noch erlaubt" % DECKEL, s is not None)
s, g = pruef({"blatt": "2026", "adresse": "A1:%s1" % ea.spaltenbuchstabe(DECKEL + 1),
              "wert": 0})
check("%d Zellen nicht mehr" % (DECKEL + 1), s is None)

print("── 4. Eine WERTE-MATRIX mit Nullen bleibt moeglich ─────────────────")
# Der ausdrueckliche Weg: jede Null steht einzeln da und ist kein
# Nebenprodukt. Das ist die Ausnahme, die der Ablehnungsgrund NENNT – ein
# Grund, der einen Weg verspricht, muss ihn halten (Register).
s, g = pruef({"blatt": "2026", "adresse": "A1:AZ1",
              "werte": [[0] * 52]})
check("0 als ausdrueckliche Matrix ueber 52 Zellen geht durch",
      s is not None)
check("...und die Nullen kommen an", bool(s) and s.get("werte") == [[0] * 52])

print("── 5. Transponierte Matrix: der gemeldete zweite Fall ──────────────")
s, g = pruef({"blatt": "2026", "adresse": "B12:E12",
              "werte": [[1], [2], [3], [4]]})
check("4×1 fuer einen Bereich 1×4 wird angenommen", s is not None)
check("...und richtig gedreht", bool(s) and s.get("werte") == [[1, 2, 3, 4]])
s, g = pruef({"blatt": "2026", "adresse": "B12:B15",
              "werte": [[1, 2, 3, 4]]})
check("1×4 fuer einen Bereich 4×1 ebenso", s is not None)
check("...und richtig gedreht", bool(s) and s.get("werte") == [[1], [2], [3], [4]])
# Der Bestand bleibt unberuehrt.
s, g = pruef({"blatt": "2026", "adresse": "B12:E12", "werte": [[1, 2, 3, 4]]})
check("eine passende Matrix bleibt unveraendert",
      bool(s) and s.get("werte") == [[1, 2, 3, 4]])
s, g = pruef({"blatt": "2026", "adresse": "B12:E12", "werte": [1, 2, 3, 4]})
check("eine flache Liste wird weiter umgeformt (Bestand)",
      bool(s) and s.get("werte") == [[1, 2, 3, 4]])

print("── 6. Mehrdeutiges wird NICHT geraten ──────────────────────────────")
# ⚠ BEI 2×3 GEGEN 3×2 IST NICHT ENTSCHEIDBAR, welche Zahl wohin gehoert.
# Dort zu drehen hiesse, Werte an falsche Stellen zu schreiben – schlimmer
# als eine Ablehnung mit Grund.
s, g = pruef({"blatt": "2026", "adresse": "B12:C14",
              "werte": [[1, 2, 3], [4, 5, 6]]})
check("2×3 fuer einen Bereich 3×2 wird abgelehnt", s is None)
check("...mit Maß-Grund", "Maße" in g)
s, g = pruef({"blatt": "2026", "adresse": "B12:AT12",
              "werte": [list(range(46))]})
check("46 Werte fuer 45 Spalten bleiben abgelehnt", s is None)

print("── 7. Der Maß-Grund nennt die SPALTENBUCHSTABEN ────────────────────")
# „45 Spalten" laesst das Modell nachzaehlen, „B bis AT" nicht – und es
# bekommt den Grund zurueck, um im selben Lauf zu korrigieren.
check("der Grund nennt die erste Spalte", "B bis" in g)
check("...und die letzte", "AT" in g)
check("...und die Anzahl", "45 Spalten" in g)
# Bei einem mehrzeiligen Bereich waere die Spaltenangabe irrefuehrend.
s, g2 = pruef({"blatt": "2026", "adresse": "B12:C14",
               "werte": [[1, 2, 3], [4, 5, 6]]})
check("bei einem mehrzeiligen Bereich steht die Spaltenangabe NICHT da",
      "bis" not in g2)

print("── 8. REGEL: der Prompt und der Riegel sagen DASSELBE ──────────────")
# Ein Prompt, der etwas erlaubt, was die Pruefung ablehnt, erzeugt
# Endlosversuche; einer, der schweigt, laesst das Modell raten.
check("der Prompt verbietet das Erfinden weiterhin",
      "ERFINDE NIEMALS EINEN WERT" in ea._VORSPANN)
check("...und nennt die 0 als den Fall", "Eine 0" in ea._VORSPANN)
check("...und den Weg (Zelle weglassen)", "aus dem Vorschlag WEG" in ea._VORSPANN)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
