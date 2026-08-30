#!/usr/bin/env python3
"""Waechter: Prompt-Tooltip an der Rollenliste + Delegation bei Aenderungswuenschen.

ZWEI ANLIEGEN AUS EINEM AUFTRAG (2026-08-30):

1. **Der verlorene Helm.** Gemessen auf ECHT: auf „setzte der Kuh einen silbernen
   Helm auf" delegierte das Modell die Aufgabe *„Generiere ein kleines,
   fotorealistisches Bild einer gruenen Kuh"* – **ohne den Helm**. Die Rolle
   sieht das Gespraech nicht und beginnt bei null; wer ihr nur die alte
   Beschreibung schickt, bekommt zwangslaeufig das alte Bild. Die
   Schema-Beschreibung sagte zwar „vollstaendig", aber nichts ueber den Fall
   AENDERUNGSWUNSCH – und genau der ist der haeufigste Folgeauftrag.

2. **Der Prompt im Mouseover.** Die Rollenliste nannte Name, Beschreibung und
   Kennzahlen – der System-Prompt IST aber die Definition einer Rolle. Ihn nur
   im Formular zu zeigen, macht den Vergleich zweier Rollen zur Klickstrecke.

`jsdom` ist in dieser Umgebung nicht installiert (Bestandslage, siehe CLAUDE.md),
deshalb werden die UI-Eigenschaften am Quelltext geprueft – aber als
EIGENSCHAFT, nicht als Zeichenkette, wo immer es geht.

Exit 0 = bestanden · 1 = FAIL · 2 = konnte nicht laufen.
"""

import re
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
JS = WURZEL / "frontend" / "js" / "agent_roles.js"
CSS = WURZEL / "frontend" / "css" / "style.css"
I18N = WURZEL / "frontend" / "js" / "i18n.js"
SKILL = WURZEL / "skills" / "agent_orchestrator" / "main.py"

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


for _p in (JS, CSS, I18N, SKILL):
    if not _p.exists():
        abbruch(f"{_p} fehlt")

Q_JS = JS.read_text(encoding="utf-8")
Q_CSS = CSS.read_text(encoding="utf-8")
Q_I18N = I18N.read_text(encoding="utf-8")
Q_SKILL = SKILL.read_text(encoding="utf-8")


def ohne_kommentare_js(t: str) -> str:
    """Ein Waechter, der seine eigene Begruendung liest, prueft nichts."""
    ohne = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
    return "\n".join(z for z in ohne.splitlines() if not z.strip().startswith("//"))


JS_CODE = ohne_kommentare_js(Q_JS)


# ═══════════════════════════════════════════════════════════════════════════
print("1. Delegation: Aenderungswuensche muessen VOLLSTAENDIG beschrieben werden")

m = re.search(r'"task":\s*\{(.*?)\n\s{16}\},', Q_SKILL, re.S)
if not m:
    m = re.search(r'"task":\s*\{(.*?)\}', Q_SKILL, re.S)
if not m:
    abbruch("Schema-Feld 'task' nicht gefunden")
beschr = m.group(1)

pruef("AENDERUNG" in beschr.upper(),
      "die Beschreibung sagt nichts ueber Aenderungswuensche zu einem frueheren Ergebnis")
pruef("null" in beschr.lower() or "kennt das vorherige" in beschr.lower(),
      "es steht nicht da, dass die Rolle das vorherige Ergebnis NICHT kennt")
pruef("PLUS" in beschr or "plus" in beschr,
      "die Regel 'alte Beschreibung PLUS Aenderung' fehlt")
# Der konkrete Fall gehoert hinein - ein Verbot ohne Beispiel wird ueberlesen.
pruef("Helm" in beschr, "der gemeldete Fall fehlt als Beispiel")
pruef("NIEMALS" in beschr,
      "die Gegenrichtung (nur die alte Beschreibung / nur die Aenderung) wird nicht verboten")

# Gegenprobe-Schutz: die urspruengliche Zusage darf nicht verlorengehen.
pruef("ohne" in beschr.lower() and "kontext" in beschr.lower(),
      "die Grundregel 'ohne Gespraechskontext verstaendlich' ist verschwunden")


# ═══════════════════════════════════════════════════════════════════════════
print("\n2. Tooltip: Aufbau und Sicherheit")

pruef("_promptTip" in JS_CODE, "die Tooltip-Funktion fehlt")
pruef("r.prompt" in JS_CODE, "der Prompt wird gar nicht ausgelesen")
pruef("mouseenter" in JS_CODE and "mouseleave" in JS_CODE,
      "kein Mouseover/Mouseout verdrahtet")

# Fremdtext NUR maskiert: der Prompt ist Freitext des Administrators.
tip = JS_CODE[JS_CODE.find("_promptTip"):JS_CODE.find("_tipStellen")]
pruef("textContent" in tip, "der Prompt wird nicht per textContent gesetzt")
pruef("innerHTML" not in tip,
      "im Tooltip wird innerHTML benutzt – Fremdtext darf kein Markup einbringen")

# Direktes Kind von body (sonst fremder Stapelkontext).
pruef("document.body.appendChild" in tip,
      "der Tooltip haengt nicht direkt an body – er wird von der naechsten Zeile ueberdeckt")

# Kein leerer Kasten ohne Prompt.
pruef("if (!text) return" in tip.replace("  ", " ") or "if (!text)" in tip,
      "eine Rolle ohne Prompt erzeugt einen leeren Tooltip")

# Kuerzung wird BEZIFFERT (Register: jede Kuerzung ausweisen).
pruef("PROMPT_TIP_MAX" in JS_CODE, "keine Laengenbegrenzung")
pruef("prompt_cut" in JS_CODE, "eine Kuerzung wird nicht ausgewiesen")
pruef("text.length" in tip, "die Gesamtlaenge wird nicht genannt")

# Beim Neuaufbau der Liste muss ein offener Tooltip verschwinden.
pruef("_tipWeg" in JS_CODE.split("_promptTip")[0],
      "beim Neuzeichnen der Liste wird ein offener Tooltip nicht abgeraeumt")


# ═══════════════════════════════════════════════════════════════════════════
print("\n3. CSS: deckend, ueber allem, ohne Flackern")

block = Q_CSS[Q_CSS.find(".role-prompt-tip {"):]
block = block[:block.find("\n.role-prompt-tip-foot") + 400] if ".role-prompt-tip-foot" in block else block[:1200]
if ".role-prompt-tip" not in Q_CSS:
    abbruch("CSS-Block .role-prompt-tip fehlt")

pruef("position: fixed" in block, "der Tooltip ist nicht fixed positioniert")
pruef("z-index" in block, "kein z-index – der Kasten kann verdeckt werden")
pruef("var(--bg-secondary)" in block,
      "keine DECKENDE Flaeche – darunter liegen Listeneintraege mit Text")
pruef("pointer-events: none" in block,
      "ohne pointer-events:none flackert der Tooltip (Kasten unter dem Zeiger "
      "loest mouseleave aus, verschwindet, mouseenter feuert erneut)")
pruef("white-space: pre-wrap" in Q_CSS[Q_CSS.find(".role-prompt-tip-body"):][:400],
      "ohne pre-wrap wird der Prompt zu einem Textklumpen")
# Keine harten Farben (Register: nur Theme-Variablen).
farben = re.findall(r"(#[0-9a-fA-F]{3,6})\b", block)
pruef(not farben, f"harte Farben im Tooltip-CSS: {farben}")


# ═══════════════════════════════════════════════════════════════════════════
print("\n4. i18n: DE und EN vorhanden")

for key in ("roles.prompt_label", "roles.prompt_cut", "roles.chars"):
    pruef(Q_I18N.count(f"'{key}'") >= 2,
          f"{key} fehlt in DE oder EN ({Q_I18N.count(chr(39) + key + chr(39))}x gefunden)")


# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}\n{_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
