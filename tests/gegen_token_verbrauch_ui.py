#!/usr/bin/env python3
"""Gegenprobe zu tests/test_token_verbrauch_ui.js: beisst der Waechter?

Jede Probe dreht EINE Zusage der Oberflaeche zurueck, laesst den Waechter
laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach
Byte-Gleichheit aller Dateien per md5.

NIE in einem Sammellauf mitlaufen lassen – sie patcht Produktdateien.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_token_verbrauch_ui.js"
JS = "frontend/js/token_verbrauch.js"
BED = "frontend/js/settings_bedienung.js"
I18N = "frontend/js/i18n.js"
TV = "backend/token_verbrauch.py"

PROBEN = [
    ("leerer Filterwert wird nicht geschickt", JS,
     "            if (sel && sel.value !== '*') p.set(dim, sel.value);\n",
     "            if (sel && sel.value && sel.value !== '*') p.set(dim, sel.value);\n"),
    ("ohne Zaehlung erscheint als 0", JS,
     "                c.textContent = (i >= 1 && i <= 3 && gemessen <= 0) ? '—' : w;\n",
     "                c.textContent = w;\n"),
    ("Legende per innerHTML", JS,
     "            t.textContent = r.schluessel === UEBRIGE\n",
     "            t.innerHTML = r.schluessel === UEBRIGE\n"),
    ("Klappkopf nicht verdrahtet", BED,
     "        'tv-klappen': function () {\n",
     "        'tv-klappen-weg': function () {\n"),
    ("Messgroesse laedt neu", JS,
     "        if (m) m.addEventListener('change', zeichnen);",
     "        if (m) m.addEventListener('change', laden);"),
    ("leerer Zeitraum = nie erfasst", JS,
     "            p.textContent = d.erfasst_seit\n",
     "            p.textContent = false\n"),
    ("Segment auch fuer 0", JS,
     "                if (!v) return;\n                var h = innenH * v / oben;\n",
     "                var h = innenH * v / oben;\n"),
    ("Dienstname fehlt in DE", I18N,
     "        'tv.d.wissensgraph_extraktion': 'Wissensgraph',\n", ""),
    ("neue Funktion in main.py ohne Dienst", TV,
     '    ("backend.main", "_support_ai_summary"): "support",\n', ""),
    ("Auswahl geht beim Neuladen verloren", JS,
     "            sel.value = gewaehlt;\n", ""),
    ("Achse wieder in Vierteln (krumme Marken)", JS,
     "        var stufen = [1, 2, 2.5, 5, 10];\n",
     "        var stufen = [1.25, 2.5, 3.75, 5, 10];\n"),
    ("Sprachwechsel zeichnet nicht neu", JS,
     "            if (daten) { optionenFuellen(daten); zeichnen(); }\n", ""),
]

DATEIEN = [JS, BED, I18N, TV, "tests/test_token_verbrauch_ui.js"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(["node", str(WAECHTER)],
                       capture_output=True, text=True, timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
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
