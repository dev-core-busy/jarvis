#!/usr/bin/env python3
"""Waechter: eine gekuerzte Spaltenliste im Excel-Ueberblick wird BENANNT.

DER BEZAHLTE VORFALL (2026-10-23). Ein Blatt mit 242 Spalten (bis IH) ging in
den Ueberblick; die Spaltenliste endete stumm bei der 40. Spalte, waehrend der
Blattkopf „242 Spalten, benutzt A20:IH500" nannte. Das Modell loeste den
Widerspruch so auf, wie es ihm offenstand:

    „In der bereitgestellten Tabellenuebersicht waren die Spaltenkoepfe nur bis
     Spalte AN gelistet. […] konnte ich ab Spalte AO keine passenden Header
     erkennen und habe daher die Uebertragung dort beendet."

202 von 242 Spalten blieben unbearbeitet, und die Begruendung las sich wie eine
Eigenschaft der Tabelle. Das Modell hat dabei NICHTS erfunden – es hat
wahrheitsgemaess ueber seinen Eingang berichtet.

⚠ DIE ZUSAGE IST NICHT „es steht ein Hinweis da", SONDERN DREI EIGENSCHAFTEN:
der Hinweis nennt die ZAHL, er nennt die NACHFORDERUNG mit fertiger Adresse,
und er steht VOR der Liste (am Ende schneidet ihn die naechste Kappung selbst
weg). Jede davon wird einzeln geprueft – sonst waere eine Gegenprobe, die nur
die Zahl entfernt, nicht als Mangel sichtbar.

Die ECHTE Funktion laeuft; eine Quelltext-Pruefung koennte „was liest das
Modell bei 242 Spalten?" gar nicht beantworten.
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
    """(Beschreibung, Bedingung) – NIE andersherum.

    ``test_jira_vorlagen.py`` hatte alle 57 Aufrufe vertauscht und meldete
    „57 OK, 0 FAIL", ohne eine Bedingung ausgewertet zu haben.
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


try:
    from backend import excel_ask as ea
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend/excel_ask.py nicht importierbar: %r" % (e,))
    sys.exit(2)

for name in ("_blatt_block", "_spalten_hinweis", "spaltenbuchstabe",
             "MAX_SPALTEN_ANZEIGE", "MAX_BLOCK_LEN", "_VORSPANN"):
    if not hasattr(ea, name):
        print("ABBRUCH: excel_ask.%s fehlt" % name)
        sys.exit(2)

DECKEL = ea.MAX_SPALTEN_ANZEIGE


def blatt(spalten: int, spalte_ab: int = 1, zeile_ab: int = 20,
          name: str = "2026", probe_breite: int | None = None) -> dict:
    """Ein Blatt-Eintrag, wie das Fenster ihn schickt.

    ``probe_breite`` ist bewusst getrennt von ``spalten``: das Fenster LAEDT
    nur ``PROBE_SPALTEN`` Spalten, die echte Breite steht im Kopf. Genau diese
    Trennung war die Luecke.
    """
    if probe_breite is None:
        probe_breite = min(spalten, DECKEL)
    kopf = ["Kopf%d" % k for k in range(1, probe_breite + 1)]
    return {"name": name, "bereich": "A%d:IH500" % zeile_ab,
            "zeilen": 481, "spalten": spalten,
            "zeile_ab": zeile_ab, "spalte_ab": spalte_ab,
            "kopfRel": 1, "datenRel": 2,
            "probe": [kopf, [1234.5] * probe_breite]}


# ── 0. Positivkontrolle: stellt der Aufbau die Lage ueberhaupt her? ───────
# Ohne diesen Beleg sind alle folgenden Pruefungen trivial wahr – eine
# Spaltenliste, die gar nicht gekuerzt ist, braucht keinen Hinweis.
print("── 0. Positivkontrolle des Messaufbaus ─────────────────────────────")
_breit = ea._blatt_block(blatt(242), True)
_gelistet = re.findall(r"([A-Z]{1,3})=Kopf\d+", _breit)
if len(_gelistet) != DECKEL:
    print("ABBRUCH: der Aufbau listet %d statt %d Spalten – die zu pruefende "
          "Kuerzung findet gar nicht statt" % (len(_gelistet), DECKEL))
    sys.exit(2)
if _gelistet[-1] != "AN":
    print("ABBRUCH: letzte gelistete Spalte ist %r, erwartet AN (der gemeldete "
          "Fall)" % _gelistet[-1])
    sys.exit(2)
check("der Aufbau stellt den gemeldeten Fall her (A–AN von 242)", True)

print("── 1. Die Kuerzung wird BENANNT ────────────────────────────────────")
# ⚠ GEMESSEN WIRD DER HINWEIS, NICHT DER BLOCK. Hier stand `"242" in _breit` –
# und das ist TRIVIAL WAHR: der Blattkopf nennt die Zahl ohnehin
# ("242 Spalten"). Eine Gegenprobe, die die Zahl aus dem Hinweis entfernte,
# blieb deshalb stumm, und das sah nach einer schwachen Sabotage aus. Es war
# die Pruefung, die ihre Stelle nicht traf (Register).
_hinweis = ea._spalten_hinweis(blatt(242), 1)
check("ein Hinweis steht im Block", "⚠" in _breit)
check("der Hinweis ist auch einzeln abrufbar", "⚠" in _hinweis)
check("die GESAMTZAHL steht IM HINWEIS", "242" in _hinweis)
check("die letzte gelistete Spalte wird genannt", "AN" in _hinweis)
check("das Blattende wird genannt", "IH" in _hinweis)
# Die wichtigste Zeile: das Modell darf die Luecke nicht fuer ein Ende halten.
check("der Hinweis sagt ausdruecklich, dass die Tabelle NICHT endet",
      "endet NICHT" in _hinweis)

print("── 2. Der Hinweis nennt die NACHFORDERUNG mit fertiger Adresse ─────")
m = re.search(r"\[\[EXCEL_BRAUCHE:\s*([^\]]+)\]\]", _hinweis)
check("eine EXCEL_BRAUCHE-Adresse steht im Hinweis", bool(m))
adr = (m.group(1).strip() if m else "")
check("sie nennt das Blatt", adr.startswith("2026!"))
check("sie beginnt bei der ERSTEN nicht gelisteten Spalte (AO)",
      "!AO" in adr)
check("sie reicht bis zum Blattende (IH)", "IH" in adr)
# Die Adresse muss die KOPFZEILE treffen – fuer ein Mapping fehlen die Koepfe,
# nicht die Daten. Kopfzeile ist hier Zeile 20.
check("sie beginnt in der Kopfzeile (20)", "AO20" in adr)
# ⚠ UND SIE MUSS DURCH DIE EIGENE PRUEFUNG DES LESEWEGS GEHEN. Eine Adresse,
# die `bereichLesen` verwirft, ist eine Sackgasse mit Anschein (Register: ein
# Prompt, der einen Weg verspricht, bindet sich an dessen Existenz).
_RE_CLIENT = re.compile(r"^\$?[A-Z]{1,3}\$?\d{1,7}(:\$?[A-Z]{1,3}\$?\d{1,7})?$",
                        re.IGNORECASE)
teil = adr.split("!", 1)[1] if "!" in adr else adr
check("die Adresse besteht die Pruefung von bereichLesen (excel.js)",
      bool(_RE_CLIENT.match(teil)))

print("── 3. Der Hinweis steht VOR der Liste ──────────────────────────────")
i_hinweis = _breit.find("⚠")
i_liste = _breit.find("    Spalten:")
check("beide Zeilen sind vorhanden", i_hinweis >= 0 and i_liste >= 0)
check("der Hinweis steht VOR der Spaltenliste",
      0 <= i_hinweis < i_liste)

print("── 4. Schmale Tabellen bleiben UNVERAENDERT ────────────────────────")
# Ein Hinweis, der immer kommt, ist Rauschen – und er wuerde bei jeder
# normalen Tabelle eine Nachforderung ausloesen, die nichts bringt.
for n in (1, 5, DECKEL - 1, DECKEL):
    blk = ea._blatt_block(blatt(n), True)
    check("bei %d Spalten kein Hinweis" % n, "⚠" not in blk)
    check("bei %d Spalten keine Nachforderung" % n,
          "EXCEL_BRAUCHE" not in blk)
check("bei %d+1 Spalten kommt er" % DECKEL,
      "⚠" in ea._blatt_block(blatt(DECKEL + 1), True))

print("── 5. Der Bezugsrahmen wird mitgerechnet ───────────────────────────")
# ⚠ DER BENUTZTE BEREICH BEGINNT NICHT IMMER BEI A1. Beginnt er bei B, ist die
# 40. gelistete Spalte AO und die erste fehlende AP – wer ab A rechnet, nennt
# eine Adresse, die eine Spalte daneben liegt, und das faellt NIEMANDEM auf.
blk_b = ea._blatt_block(blatt(242, spalte_ab=2), True)
gel_b = re.findall(r"([A-Z]{1,3})=Kopf\d+", blk_b)
check("bei Start in B endet die Liste bei AO", gel_b and gel_b[-1] == "AO")
m_b = re.search(r"\[\[EXCEL_BRAUCHE:\s*([^\]]+)\]\]", blk_b)
check("...und die Nachforderung beginnt bei AP",
      bool(m_b) and "!AP" in m_b.group(1))
# Auch die Zeilennummer folgt dem Rahmen.
blk_z = ea._blatt_block(blatt(242, zeile_ab=7), True)
m_z = re.search(r"\[\[EXCEL_BRAUCHE:\s*([^\]]+)\]\]", blk_z)
check("die Kopfzeile des Rahmens steht in der Adresse (7)",
      bool(m_z) and "AO7" in m_z.group(1))

print("── 6. Blattnamen mit Leerzeichen werden zitiert ────────────────────")
# Ohne Anfuehrungszeichen liest das Fenster den Namen nur bis zum Leerzeichen
# und holt den falschen (oder keinen) Bereich.
blk_s = ea._blatt_block(blatt(242, name="Plan 2026"), True)
m_s = re.search(r"\[\[EXCEL_BRAUCHE:\s*([^\]]+)\]\]", blk_s)
check("der Name steht in Anfuehrungszeichen",
      bool(m_s) and m_s.group(1).startswith("'Plan 2026'!"))

print("── 7. Auch der ALT-Zweig (aelteres excel.js) bekommt ihn ───────────")
# ⚠ EINE LEHRE IN ZWEI VON DREI ZWEIGEN IST NICHT ANGEWANDT. Der Zweig fuer
# das alte Feldformat (`kopf`/`typen`) ist der, den jeder offene Tab benutzt,
# bis der Benutzer neu laedt – also genau im Ausrollfenster.
alt = {"name": "2026", "bereich": "A20:IH500", "zeilen": 481, "spalten": 242,
       "zeile_ab": 20, "spalte_ab": 1,
       "kopf": ["Kopf%d" % k for k in range(1, 41)],
       "typen": ["Zahl"] * 40,
       "beispiele": [[1234.5] * 40]}
blk_alt = ea._blatt_block(alt, True)
check("der Alt-Zweig listet Spalten", "    Spalten:" in blk_alt)
check("...und benennt die Kuerzung", "⚠" in blk_alt and "242" in blk_alt)
check("...mit Nachforderung", "EXCEL_BRAUCHE" in blk_alt)
check("...und der Hinweis steht auch dort VOR der Liste",
      0 <= blk_alt.find("⚠") < blk_alt.find("    Spalten:"))

print("── 8. REGEL: der Prompt deutet den Hinweis ─────────────────────────")
# Ein Hinweis, den der Prompt nicht erklaert, ist eine Zeichenkette. Das
# Modell muss WISSEN, dass eine nicht gelistete Spalte nicht leer ist.
# ⚠ GELESEN WIRD DIE PROMPT-KONSTANTE, NICHT DER QUELLTEXT. Ein Rueckfall auf
# die ganze Datei haette die DOCSTRINGS mitgelesen – dann bescheinigte der
# Waechter dem Prompt eine Zusage, die nur in meiner eigenen Begruendung steht
# (Register: ein Waechter, der seine eigene Begruendung liest, prueft nichts).
# Fehlt die Konstante, ist das Exit 2 und kein "bestanden".
prompt = getattr(ea, "_VORSPANN", None)
if not isinstance(prompt, str) or len(prompt) < 500:
    print("ABBRUCH: excel_ask._VORSPANN (der Prompt) nicht lesbar – die "
          "Prompt-Zusagen sind damit ungeprueft")
    sys.exit(2)
check("der Prompt erwaehnt die gekuerzte Spaltenliste",
      "Spaltenliste ist gekürzt" in prompt)
check("...und verbietet den Abbruch ausdruecklich",
      "NIEMALS ab" in prompt or "niemals ab" in prompt.lower())
check("...und nennt das Nachfordern als Pflicht, nicht als Option",
      "Pflicht, keine Option" in prompt)

print("── 9. Der Hinweis sprengt das Blatt-Budget nicht ───────────────────")
check("ein Hinweis ist kuerzer als ein Zehntel des Blatt-Budgets",
      len(ea._spalten_hinweis(blatt(242), 1)) < ea.MAX_BLOCK_LEN // 10)
check("der Block bleibt im Budget", len(_breit) <= ea.MAX_BLOCK_LEN)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
