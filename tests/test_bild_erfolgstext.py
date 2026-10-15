#!/usr/bin/env python3
"""Waechter: ein erfolgreiches Bild-Ergebnis liest sich nicht wie ein Fehler.

DER VORFALL (ECHT, 2026-08-30): Auf „setze der Kuh einen Helm auf" lieferte das
Werkzeug ein fertiges Bild – der Lauf hatte GENAU ZWEI Nachrichten:

    [tool]      Ergebnis der Rolle 'image_builder':
                [BILDDATEN AUSGELAGERT: PNG, 1966 KB. Base64 gehoert NICHT in
                 deine Antwort … Gib stattdessen GENAU diese Zeile …:]
                ![Bild](/api/generated/cb20b70d….png)
    [assistant] „Die Bildgenerierung mit der Rolle `image_builder` ist
                 fehlgeschlagen. Fehlermeldung: 'Failed to parse as a valid JSON'."

BEFUND: Der Wortlaut steht NIRGENDS – nicht im Code, nicht im System-Prompt,
nicht in Instruktionen, Memory oder Wissensdateien (auf ECHT durchsucht). Es gab
keinen JSON-Fehler und keinen zweiten Werkzeug-Aufruf. **Das Modell hat den
Fehlschlag erfunden** – dieselbe Klasse wie „Die Base64-URL war vermutlich zu
lang" (2026-08-26).

Ein A/B-Lauf gegen das echte Modell (Qwen3.6-35B, je 5 Laeufe) hat den alten
Ersatztext NICHT als Ausloeser bestaetigt: beide Fassungen 0/5 Fehlbehauptungen,
5/5 Bild. **Der Fix ist damit eine HAERTUNG, kein bewiesener Ursachenfix** – und
genau das steht hier, damit es niemand fuer mehr haelt.

Geprueft werden zwei Eigenschaften, die unabhaengig vom Modell gelten:
  1. Der Ersatztext im Werkzeug-Ergebnis sagt ERFOLG, nicht Stoerung.
  2. Der System-Prompt verbietet, bei einer `/api/generated/`-Adresse einen
     Fehlschlag zu behaupten.

Exit 0 = bestanden · 1 = FAIL · 2 = konnte nicht laufen.
"""

import ast
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
AGENT_PY = WURZEL / "backend" / "agent.py"

_ok = 0
_fail = 0


def pruef(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {text}")


def abbruch(text):
    print(f"KONNTE NICHT LAUFEN: {text}")
    sys.exit(2)


if not AGENT_PY.exists():
    abbruch(f"{AGENT_PY} fehlt")

QUELLE = AGENT_PY.read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)
KLS = next((n for n in ast.walk(BAUM)
            if isinstance(n, ast.ClassDef) and n.name == "JarvisAgent"), None)
if KLS is None:
    abbruch("Klasse JarvisAgent nicht gefunden")


# ═══════════════════════════════════════════════════════════════════════════
print("1. Der Ersatztext im Werkzeug-Ergebnis meldet ERFOLG")

_bb = next((n for n in KLS.body
            if isinstance(n, ast.FunctionDef) and n.name == "_bilddaten_bergen"), None)
if _bb is None:
    abbruch("_bilddaten_bergen nicht gefunden")
_src = ast.get_source_segment(QUELLE, _bb) or ""

# Der Text fuer das MODELL (fuer_anzeige=False) – nur die Literale, nicht die
# Kommentare: ein Waechter, der seine eigene Begruendung liest, prueft nichts.
_literale = [n.value for n in ast.walk(ast.parse(_src))
             if isinstance(n, ast.Constant) and isinstance(n.value, str)]
_text = " ".join(_literale)

pruef("ERFOLGREICH" in _text.upper(),
      "der Ersatztext sagt nicht, dass das Bild ERFOLGREICH erzeugt wurde")
pruef("KEIN FEHLER" in _text.upper(),
      "der Ersatztext stellt nicht ausdruecklich klar, dass es kein Fehler ist")
pruef("AUSGELAGERT" not in _text.upper() or "ERFOLGREICH" in _text.upper(),
      "die Marke liest sich weiter wie eine Stoerungsmeldung")

# Woerter, die einen Fehlschlag suggerieren, gehoeren NICHT in eine Erfolgsmeldung.
for wort in ("gehoert NICHT", "fuellt den Kontext"):
    pruef(wort not in _text,
          f"der Erfolgstext enthaelt weiter die tadelnde Formulierung {wort!r}")

# Die Bildzeile muss weiterhin drin sein – sonst kommt gar nichts an.
# ⚠ NICHT ueber die String-Literale pruefbar: `![{bild_alt}]({url})` steht in
# einem f-String, und dort sind `{url}`/`{bild_alt}` FormattedValue-Knoten,
# keine Konstanten. Geprueft wird deshalb der Quelltext ohne Kommentare – sonst
# meldet der Waechter einen Fehler, den es nicht gibt (beim ersten Lauf genau so
# passiert).
_code = "\n".join(z for z in _src.splitlines() if not z.strip().startswith("#"))
pruef("![{bild_alt}]({url})" in _code,
      "der Ersatztext enthaelt die Bildreferenz nicht mehr")


# ═══════════════════════════════════════════════════════════════════════════
print("\n2. Der System-Prompt verbietet den erfundenen Fehlschlag")

_sp = None
for n in KLS.body:
    if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SYSTEM_PROMPT" for t in n.targets):
        _sp = n.value.value if isinstance(n.value, ast.Constant) else None
if not isinstance(_sp, str):
    abbruch("SYSTEM_PROMPT nicht als Literal gefunden")

pruef("/api/generated/" in _sp, "der Prompt nennt die Bild-Adresse nicht")
_regel = [z for z in _sp.splitlines() if "/api/generated/" in z and "ERFOLG" in z.upper()]
pruef(bool(_regel),
      "keine Regel: eine /api/generated-Adresse im Ergebnis ist ein ERFOLG")
_alles = " ".join(_regel).lower()
pruef("fehlschlag" in _alles or "fehlermeldung" in _alles,
      "die Regel verbietet den behaupteten Fehlschlag nicht ausdruecklich")
pruef("failed to parse" in _sp.lower(),
      "der gemeldete Wortlaut wird nicht als Beispiel genannt – "
      "ein Verbot ohne den konkreten Fall ist leicht zu uebersehen")

# Gegenrichtung: die bestehende Regel gegen erfundene FEHLER-Begruendungen
# muss erhalten bleiben (sie deckt den umgekehrten Fall ab).
pruef("erfinde keine" in _sp.lower(),
      "die Regel gegen erfundene 'geht nicht'-Begruendungen ist verschwunden")


# ═══════════════════════════════════════════════════════════════════════════
print("\n3. Ehrlichkeit des Waechters: der Fix ist eine HAERTUNG")
# Diese Pruefung hat keinen technischen Zweck – sie haelt fest, dass der
# A/B-Lauf die Ursache NICHT bestaetigt hat. Wer den Text spaeter aendert,
# soll wissen, dass hier nichts Bewiesenes verteidigt wird.
_doc = ast.get_docstring(ast.parse(Path(__file__).read_text(encoding="utf-8"))) or ""
pruef("HAERTUNG" in _doc.upper() and "erfunden" in _doc.lower(),
      "der Waechter verschweigt, dass die Ursache eine Halluzination ist")


# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}\n{_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
