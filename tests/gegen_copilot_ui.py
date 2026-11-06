#!/usr/bin/env python3
"""Gegenproben zu ``tests/test_copilot_ui.js``.

Jede Probe dreht GENAU EINE Zusage der Verbindungsflaeche zurueck und misst, ob
der Waechter das meldet. Dieselbe Bauart wie
``tests/gegen_copilot_recherche.py`` – siehe dort fuer die Begruendung von
Plattensicherung, Laufmarke, md5-Nachsehen und der REGEL, dass jede Probe eine
gesicherte Datei anfassen muss.

Gemessen wird Exit-Code UND die gemeinte FAIL-Zeile. Ein Abbruch mit Exit 2
("konnte nicht laufen") zaehlt ausdruecklich NICHT als Biss – und ein Exit 0
ohne Bilanzzeile wird vom Waechter selbst auf 1 gehoben.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_copilot_ui.js"
SICHERUNG = Path.home() / ".jarvis-gegen-copilot-ui"
MARKE = SICHERUNG / "LAUF_AKTIV"

JS = "frontend/js/copilot.js"
CSS = "frontend/css/style.css"
HTML = "frontend/settings.html"
I18N = "frontend/js/i18n.js"

DATEIEN = (JS, CSS, HTML, I18N)

# (Name, Datei, alt, neu, erwartete FAIL-Zeile)
PROBEN: list[tuple[str, str, str, str, str]] = [
    ("der Kontoname wird nicht mehr escaped",
     JS,
     "                    + '<div class=\"cp-konto\" id=\"copilot-konto\">'\n"
     "                    + esc(d.konto || t('copilot.konto_unbekannt', 'Konto nicht übermittelt'))",
     "                    + '<div class=\"cp-konto\" id=\"copilot-konto\">'\n"
     "                    + (d.konto || t('copilot.konto_unbekannt', 'Konto nicht übermittelt'))",
     "ein Tag im Kontonamen landet nicht im Markup"),

    ("jede Adresse wird verlinkt, auch javascript:",
     JS,
     "        return typeof url === 'string' && /^https:\\/\\/[^\\s\"']+$/.test(url);",
     "        return typeof url === 'string' && url.length > 0;",
     "kein <a> fuer eine javascript:-Adresse"),

    ("rel=noopener faellt weg",
     JS,
     "'\" target=\"_blank\" rel=\"noopener noreferrer\"'",
     "'\" target=\"_blank\"'",
     "der Verweis nach aussen traegt target=_blank und rel=noopener"),

    ("ein Ausfall der Auskunft zeichnet trotzdem den Zustand",
     JS,
     "            const { status, daten } = await this._holen('/api/copilot/status');\n"
     "            if (status !== 200) {",
     "            const { status, daten } = await this._holen('/api/copilot/status');\n"
     "            if (false) {",
     "kein Verbinden-Knopf bei unbekanntem Zustand"),

    ("der Abhol-Takt laeuft nach 'authorized' weiter",
     JS,
     "            if (zustand === 'authorized') {\n"
     "                this._laeuft = false;\n"
     "                this._stoppen();",
     "            if (zustand === 'authorized') {\n"
     "                this._laeuft = false;",
     "authorized: der Takt ist gestoppt"),

    ("der Takt laeuft auch nach 'idle' weiter",
     JS,
     "            } else if (zustand === 'idle') {\n"
     "                // Der Dienst kennt den Vorgang nicht mehr (Neustart) – nicht\n"
     "                // weiter fragen und den Grund nennen.\n"
     "                this._laeuft = false;\n"
     "                this._stoppen();",
     "            } else if (zustand === 'idle') {\n"
     "                this._laeuft = false;",
     "idle (Dienst neu gestartet): der Takt ist gestoppt"),

    ("der Verbinden-Knopf ist immer bedienbar",
     JS,
     "                    + (kannVerbinden ? '' : ' disabled')",
     "                    + ''",
     "ohne Entra-Anwendung ist der Verbinden-Knopf disabled"),

    ("der Hinweis zur Internet-Freigabe faellt weg",
     JS,
     "            if (!d.internet_frei) {",
     "            if (false) {",
     "internet_frei: ein Hinweis erscheint"),

    ("der Hinweis zur fehlenden Anwendung faellt weg",
     JS,
     "            if (!d.eingerichtet) {",
     "            if (false) {",
     "eingerichtet: ein Hinweis erscheint"),

    ("ein Emoji kommt ins Bedienelement",
     JS,
     "                    + esc(t('copilot.verbinden', 'Microsoft-Konto verbinden'))",
     "                    + '🔗 ' + esc(t('copilot.verbinden', 'Microsoft-Konto verbinden'))",
     "copilot.js enthaelt kein Emoji"),

    ("die Code-Klasse verliert ihre CSS-Regel",
     CSS,
     ".cp-code {",
     ".cp-code-ungenutzt {",
     "in style.css definiert: .cp-code"),

    ("eine feste Farbe schleicht sich ein",
     CSS,
     ".cp-titel { font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }",
     ".cp-titel { font-weight: 600; color: #e5e7eb; margin-bottom: 6px; }",
     "keine festen Farben im Block"),

    ("--danger bleibt im hellen Thema unabgedunkelt",
     CSS,
     "body.light .cp-fehler { color: color-mix(in srgb, var(--danger) 78%, #000); }",
     "",
     "--danger als Schrift ist im hellen Thema abgedunkelt"),

    ("der Knopf nimmt width:100% nicht zurueck",
     CSS,
     ".cp-knopf { width: auto; flex: 0 0 auto; margin-top: 10px; }",
     ".cp-knopf { flex: 0 0 auto; margin-top: 10px; }",
     ".btn-primary traegt width:100%"),

    # Die beiden Zusagen aus der optischen Abnahme (2026-11-06).
    ("der Trennen-Knopf verliert seine Abdunklung im hellen Thema",
     CSS,
     "body.light .cp-karte .kb-btn-danger { color: color-mix(in srgb, var(--danger) 78%, #000); }",
     "",
     "der Trennen-Knopf ist im hellen Thema abgedunkelt"),

    ("ein gesperrter Knopf sieht wieder aus wie ein bedienbarer",
     CSS,
     ".cp-knopf:disabled { opacity: 0.5; cursor: not-allowed; }",
     "",
     "ein gesperrter Knopf ist SICHTBAR gesperrt"),

    ("das Skript ist nicht mehr eingebunden",
     HTML,
     '    <script src="/static/js/copilot.js?v=1"></script>\n',
     "",
     "copilot.js ist in settings.html eingebunden"),

    ("ein i18n-Schluessel fehlt im EN-Block",
     I18N,
     "        'copilot.verbinden': 'Connect Microsoft account',\n",
     "",
     "in DE und EN belegt: copilot.verbinden"),
]


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern() -> dict[str, str]:
    SICHERUNG.mkdir(parents=True, exist_ok=True)
    SICHERUNG.chmod(0o700)
    summen = {}
    for rel in DATEIEN:
        quelle = ROOT / rel
        shutil.copy2(quelle, SICHERUNG / rel.replace("/", "__"))
        summen[rel] = _md5(quelle)
    return summen


def zurueck(summen: dict[str, str]) -> list[str]:
    schlecht = []
    for rel in DATEIEN:
        quelle = SICHERUNG / rel.replace("/", "__")
        ziel = ROOT / rel
        if not quelle.exists():
            schlecht.append(f"{rel}: keine Sicherung")
            continue
        shutil.copy2(quelle, ziel)
        if summen and _md5(ziel) != summen.get(rel):
            schlecht.append(f"{rel}: md5 weicht nach dem Zuruecklegen ab")
    return schlecht


def lauf() -> tuple[int, str]:
    umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run(["node", str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=umgebung)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fehlend = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlend:
        print(f"ABBRUCH (Exit 2): Proben fassen ungesicherte Dateien an: "
              f"{sorted(fehlend)}")
        return 2

    if MARKE.exists():
        print("! Laufmarke gefunden – nehme den Rueckstand zurueck")
        schlecht = zurueck({})
        if schlecht:
            print(f"ABBRUCH (Exit 2): Rueckstand nicht ruecknehmbar: {schlecht}")
            return 2
        MARKE.unlink()

    print("0. Basislauf muss GRUEN sein")
    code, ausgabe = lauf()
    bilanz = re.search(r"(\d+) OK, (\d+) FAIL", ausgabe)
    if code != 0 or not bilanz or bilanz.group(2) != "0":
        print(f"ABBRUCH (Exit 2): Basislauf nicht gruen (Exit {code}, "
              f"Bilanz {bilanz.group(0) if bilanz else 'FEHLT'})")
        print(ausgabe[-1500:])
        return 2
    print(f"   Basis: {bilanz.group(1)} OK, 0 FAIL, Exit 0")

    summen = sichern()
    MARKE.write_text("laeuft\n", encoding="utf-8")
    beissen = stumm = kaputt = 0
    try:
        for nr, (name, rel, alt, neu, erwartet) in enumerate(PROBEN, 1):
            ziel = ROOT / rel
            text = ziel.read_text("utf-8")
            if text.count(alt) != 1:
                print(f"{nr}. {name}\n   ABBRUCH-PROBE: der Anker kommt "
                      f"{text.count(alt)}x in {rel} vor (erwartet genau 1)")
                kaputt += 1
                continue
            ziel.write_text(text.replace(alt, neu), "utf-8")
            try:
                code, ausgabe = lauf()
            finally:
                schlecht = zurueck(summen)
                if schlecht:
                    print(f"ABBRUCH (Exit 2): Wiederherstellung misslungen: "
                          f"{schlecht}")
                    return 2
            bilanz = re.search(r"(\d+) OK, (\d+) FAIL", ausgabe)
            getroffen = erwartet in ausgabe
            if code == 2:
                print(f"{nr}. {name}\n   ABBRUCH im Waechter (Exit 2) – kein "
                      f"Biss, sondern ein zu scharfer Guard")
                kaputt += 1
            elif code == 1 and bilanz and getroffen:
                print(f"{nr}. {name}\n   BEISST: Exit 1, {bilanz.group(2)} "
                      f"FAIL, gemeinte Zeile dabei")
                beissen += 1
            elif code == 1 and bilanz:
                print(f"{nr}. {name}\n   FAIL, aber die GEMEINTE Zeile fehlt "
                      f"({erwartet!r})")
                stumm += 1
            elif not bilanz:
                print(f"{nr}. {name}\n   KEINE BILANZ (Exit {code}) – "
                      f"abgebrochen, nicht fehlgeschlagen")
                kaputt += 1
            else:
                print(f"{nr}. {name}\n   STUMM: Exit {code}")
                stumm += 1
    finally:
        schlecht = zurueck(summen)
        if MARKE.exists():
            MARKE.unlink()
        if schlecht:
            print(f"ABBRUCH (Exit 2): Rueckstand im Arbeitsbaum: {schlecht}")
            return 2

    print(f"\n{beissen} von {len(PROBEN)} Proben beissen, {stumm} stumm, "
          f"{kaputt} nicht deutbar")
    return 0 if (beissen == len(PROBEN)) else 1


if __name__ == "__main__":
    sys.exit(main())
