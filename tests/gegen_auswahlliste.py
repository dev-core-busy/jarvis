#!/usr/bin/env python3
"""Gegenprobe zu tests/test_auswahlliste_ui.js (gestaltbare Auswahl, 2026-11-21).

Jede Probe dreht EINE Zusage im PRODUKT zurueck (Modul, theme.css, style.css,
Einbindung), laesst den Waechter laufen und erwartet mindestens einen FAIL
(Exit 1). Exit 2 zaehlt NICHT als Biss – dann hat eine Positivkontrolle der
Messvorrichtung abgebrochen. Vorher gruener Basislauf, danach Byte-Gleichheit.

Bewusst NICHT als Probe (doppelte Schranke, Sabotage waere stumm):
  - die `CSS.supports`-Pruefung am Modulanfang: ohne sie fragt `betroffen()`
    trotzdem die berechnete `appearance` ab, die ohne base-select `auto` ist;
  - `s.multiple` in `betroffen()`: dieselbe berechnete `appearance` schliesst
    Mehrfachauswahl schon aus (theme.css nimmt sie per `:not([multiple])` aus).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_auswahlliste_ui.js"
SICHERUNG = Path.home() / ".gegen_auswahlliste_sicherung"

MOD = "frontend/js/auswahlliste.js"
THEME = "frontend/css/theme.css"
STYLE = "frontend/css/style.css"
SETTINGS = "frontend/settings.html"

PROBEN = [
    # ── Modul ──
    ("nie eine Mindestbreite (Breite springt wieder)", MOD,
     "        if (groesste - kleinste > 0.5) {\n", "        if (false) {\n"),
    ("erste Fassung: nur wenn aktuelle Breite schmaler", MOD,
     "        if (groesste - kleinste > 0.5) {\n",
     "        if (groesste > s.getBoundingClientRect().width + 0.5) {\n"),
    ("Auswahl nach dem Messen nicht zurueckgestellt", MOD,
     "        s.selectedIndex = vorher;\n", ""),
    ("Mindestbreite des Autors wird ueberschrieben", MOD,
     "        if (s.style.minWidth && !s.hasAttribute(MARKE)) return false;   // vom Autor gesetzt\n", ""),
    ("eigene Mindestbreite wird nie zurueckgenommen", MOD,
     "            s.style.minWidth = '';\n            s.removeAttribute(MARKE);\n", ""),
    ("kein Messen beim Fokus", MOD,
     "    document.addEventListener('focusin', vorDemOeffnen, true);\n", ""),
    ("kein Messen beim Druecken der Maustaste", MOD,
     "    document.addEventListener('pointerdown', vorDemOeffnen, true);\n", ""),
    ("geaenderte Eintraege werden nicht nachgemessen", MOD,
     "            var s = feldZu(m.target);\n", "            var s = null;\n"),
    ("Sprachwechsel misst nicht neu", MOD,
     "    window.addEventListener('jarvis-lang-changed', alle);\n", ""),
    # ── theme.css ──
    ("Grundform ohne :where() (ueberstimmt Klassenregeln)", THEME,
     "    select:where(:not([multiple]):not([size])) {\n        align-items: center;\n",
     "    select:not([multiple]):not([size]) {\n        align-items: center;\n"),
    ("Auswahlfelder nicht mehr auf base-select (der gemeldete Fehler)", THEME,
     "        appearance: base-select;\n    }\n    select:where(:not([multiple]):not([size])) {\n",
     "        appearance: auto;\n    }\n    select:where(:not([multiple]):not([size])) {\n"),
    # ── style.css: Felder mit eigenem Pfeil ──
    ("Feld mit eigenem Pfeil bleibt beim Betriebssystem-Menue", STYLE,
     "    select.input-field,\n    .wa-log-select {\n        appearance: base-select;\n",
     "    select.input-field {\n        appearance: base-select;\n"),
    ("doppelter Pfeil (Chrome-Pfeil nicht ausgeblendet)", STYLE,
     "    select.input-field::picker-icon,\n", ""),
    # ── Einbindung ──
    ("Einstellungsseite laedt das Modul nicht", SETTINGS,
     '    <script src="/static/js/auswahlliste.js?v=1"></script>\n', ""),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf() -> tuple[int, str]:
    r = subprocess.run(["node", str(WAECHTER)], cwd=ROOT, capture_output=True,
                       text=True, timeout=300)
    zeile = next((z for z in reversed(r.stdout.splitlines())
                  if "FAIL" in z or "ABBRUCH" in z), "")
    return r.returncode, zeile.strip()


def zurueck() -> None:
    if not SICHERUNG.exists():
        return
    for rel in DATEIEN:
        quelle = SICHERUNG / rel
        if quelle.exists():
            shutil.copy2(quelle, ROOT / rel)
    shutil.rmtree(SICHERUNG)


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Dateiliste unvollstaendig.")
        return 2
    zurueck()  # Rueckstand eines abgebrochenen Laufs
    for name, rel, alt, _neu in PROBEN:
        n = (ROOT / rel).read_text(encoding="utf-8").count(alt)
        if n != 1:
            print("ABBRUCH: Anker %dx gefunden – %s" % (n, name))
            return 2
    code, zeile = lauf()
    if code != 0:
        print("ABBRUCH: Basislauf nicht gruen (%s, Exit %d)" % (zeile, code))
        return 2
    print("Basislauf gruen: " + zeile)
    vorher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    SICHERUNG.mkdir(mode=0o700)
    for rel in DATEIEN:
        (SICHERUNG / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, SICHERUNG / rel)
    stumm = []
    try:
        for name, rel, alt, neu in PROBEN:
            pfad = ROOT / rel
            original = pfad.read_text(encoding="utf-8")
            pfad.write_text(original.replace(alt, neu), encoding="utf-8")
            try:
                code, zeile = lauf()
            finally:
                pfad.write_text(original, encoding="utf-8")
            biss = code == 1
            print("%s  %-58s %s (Exit %d)"
                  % ("BEISST" if biss else "STUMM ", name, zeile, code))
            if not biss:
                stumm.append(name)
    finally:
        zurueck()
    nachher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    if nachher != vorher:
        print("FEHLER: Dateien nach der Gegenprobe nicht byte-gleich!")
        return 2
    print("\nDateien byte-gleich wiederhergestellt.")
    print("Bilanz: %d von %d Proben beissen" % (len(PROBEN) - len(stumm), len(PROBEN)))
    return 0 if not stumm else 1


if __name__ == "__main__":
    sys.exit(main())
