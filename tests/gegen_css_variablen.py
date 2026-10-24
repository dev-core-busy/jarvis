#!/usr/bin/env python3
"""Gegenprobe zu tests/test_css_variablen.py: beisst der Waechter?

ANLASS (Code-Review 2026-10-24): zwei frische Regeln in `chat.css` hingen an
`body.dark`. Diese Klasse setzt das Projekt nirgends – hell setzt `light`
(theme.js), DUNKEL IST DIE VORGABE UND TRAEGT KEINE KLASSE. Die Korrektur war
damit still wirkungslos, und im Regelfall galt die abgedunkelte Warnschrift,
die auf dunklem Grund nur 3,08:1 haelt. Der Waechter hat dafuer eine dritte
Regel bekommen; diese Datei zeigt, dass sie beisst.

Jede Probe dreht EINEN Teil zurueck (Ersetzung ganzer Zeilen), laesst den
Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf,
danach Byte-Gleichheit aller angefassten Dateien per md5, ohne Bytecode
(PYTHONDONTWRITEBYTECODE=1).

ZWEI ARTEN VON PROBEN, getrennt ausgewiesen:
  * PRODUKT – eine echte Luecke im CSS (der Vorfall selbst, ein Tippfehler in
    einer Klasse). Das ist der Fall, fuer den die Regel gebaut ist.
  * SONDE – eine Schwaechung am MESSWERKZEUG (Sammler blind, Kommentare nicht
    entfernt). Sie belegt, dass die Positivkontrollen des Waechters das merken;
    ohne sie waere die Regel trivial gruen, sobald der Sammler ins Leere
    greift. Die Regel selbst wird NICHT sabotiert – ein Waechter kann das
    Entfernen seiner eigenen Regel nicht melden, und eine Probe darauf waere
    eine falsch platzierte Probe (Register).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

    python3 tests/gegen_css_variablen.py
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_css_variablen.py"
CHAT = "frontend/css/chat.css"
STYLE = "frontend/css/style.css"
THEME = "frontend/css/theme.css"
WI = "tests/test_css_variablen.py"

PROBEN = [
    # ── PRODUKT: der Vorfall selbst ─────────────────────────────────────────
    ("PRODUKT der Vorfall: Pflichthinweis wieder an body.dark", CHAT,
     "body.light .jv-best-pflicht {",
     "body.dark .jv-best-pflicht {"),
    ("PRODUKT Herkunfts-Warnung wieder an body.dark", CHAT,
     "body.light .jv-best-herkunft.is-uebernommen {",
     "body.dark .jv-best-herkunft.is-uebernommen {"),
    # ── PRODUKT: dieselbe Fehlerklasse, anderer Name ────────────────────────
    # Die Regel darf nicht auf das Wort "dark" hoeren, sondern muss JEDE
    # body-Klasse pruefen, die es nicht gibt (Register: wer einen Waechter fuer
    # EINEN Namen baut, hat die Fehlerklasse nicht erledigt).
    ("PRODUKT Tippfehler in einer Bestandsklasse (style.css)", STYLE,
     "body.kbm-resizing", "body.kbm-reszing"),
    ("PRODUKT Tippfehler in einer Bestandsklasse (theme.css)", THEME,
     "body.jv-breit", "body.jv-briet"),
    # ── SONDE: merken die Positivkontrollen eine blinde Sammelstelle? ───────
    ("SONDE Markup-Sammler greift ins Leere", WI,
     '    for m in re.finditer(r"""class\\s*=\\s*["\']([^"\']*)["\']""",\n',
     '    for m in re.finditer(r"""klasse\\s*=\\s*["\']([^"\']*)["\']""",\n'),
    ("SONDE classList-Sammler greift ins Leere", WI,
     '    for m in re.finditer(r"""classList\\.(?:add|remove|toggle|replace)'
     '\\(\\s*[\'"]([\\w-]+)[\'"]""", t):\n',
     '    for m in re.finditer(r"""klassenListe\\.(?:add)\\(\\s*[\'"]([\\w-]+)[\'"]""", t):\n'),
    # ⚠ Diese Probe trifft genau die Falle, in der dieser Waechter sonst seine
    # EIGENE Begruendung lesen wuerde: der Kommentar an der korrigierten Regel
    # in chat.css NENNT `body.dark`. Ohne `entkommentieren` meldet der Waechter
    # ihn als Selektor – ein Fehlalarm, der wie ein Befund aussieht.
    ("SONDE Kommentare werden nicht mehr entfernt", WI,
     '    for m in re.finditer(r"\\bbody\\.([\\w-]+)",\n'
     '                         entkommentieren(p.read_text(encoding="utf-8"))):\n',
     '    for m in re.finditer(r"\\bbody\\.([\\w-]+)",\n'
     '                         p.read_text(encoding="utf-8")):\n'),
]

DATEIEN = [CHAT, STYLE, THEME, WI]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, object]:
    """FAIL-Zahl des Waechters. -1 = konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                           text=True, timeout=300, cwd=str(ROOT), env=env)
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), 0


def main() -> int:
    # Die Dateiliste als REGEL, nicht gepflegt: eine Probe an einer nicht
    # gesicherten Datei laesst ihre Sabotage im Arbeitsbaum stehen, und der
    # naechste Lauf meldet Fehler, die es im Code nicht gibt (Register).
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an: %s"
              % sorted({p[1] for p in PROBEN} - set(DATEIEN)))
        return 2
    for d in DATEIEN:
        if not (ROOT / d).is_file():
            print("ABBRUCH: %s fehlt" % d)
            return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s) – ohne gruene "
              "Basis ist keine Gegenprobe deutbar" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-56s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-56s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-56s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
