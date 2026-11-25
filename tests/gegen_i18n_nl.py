"""Gegenprobe zu test_i18n_nl.js (Niederlaendisch als vierte Oberflaechensprache, 2026-11-25).

Dreht je EINE Zusage in den echten Dateien zurueck und erwartet FAILs MIT
Bilanzzeile (Exit 1); stellt danach byte-gleich wieder her (md5).
Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import hashlib, os, re, subprocess, sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
I18N = W / "frontend/js/i18n.js"
NL = W / "frontend/js/i18n_nl.js"
CSS = W / "frontend/css/theme.css"
PORTAL = W / "frontend/portal.html"
KOPF = W / "frontend/js/kopfzeile.js"
TEST = "test_i18n_nl.js"
DATEIEN = [I18N, NL, CSS, PORTAL, KOPF]
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
vorher = {p: md5(p) for p in DATEIEN}
sich = {p: p.read_bytes() for p in DATEIEN}
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def lauf():
    r = subprocess.run(["node", str(W / "tests" / TEST)], capture_output=True, text=True,
                       env=env, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


PROBEN = [
    ("NL-Schluessel fehlt", NL,
     '    "portal.welcome": "Welkom",\n', ''),
    ("Platzhalter {marke} verloren", NL,
     '"input.placeholder": "Voer een taak in voor {marke}..."', '"input.placeholder": "Voer een taak in..."'),
    ("schliessendes </b> verloren", NL,
     '<b>De sleutel blijft hier zichtbaar.</b>', '<b>De sleutel blijft hier zichtbaar.'),
    ("Seite bindet i18n_nl.js nicht ein", PORTAL,
     '<script src="/static/js/i18n_nl.js?v=', '<script src="/static/js/i18n_nl_weg.js?v='),
    ("Seite ohne NL-Knopf", PORTAL,
     '<button class="lang-toggle-btn" data-lang="nl" data-setlang="nl" title="Nederlands">NL</button>', ''),
    ("Kopfzeile ohne NL-Knopf", KOPF, 'data-lang="nl" data-setlang="nl"', 'data-lang="nl"'),
    ("Rueckfall nl ohne Englisch", I18N, "nl: ['nl', 'en', 'de']", "nl: ['nl', 'de']"),
    ("theme.css zeigt bei NL die deutschen Bloecke", CSS,
     'html[data-lang="nl"] .i18n-de { display: none !important; }', '.nie-da { display: none !important; }'),
    ("theme.css blendet bei NL die englischen Bloecke aus", CSS,
     ':not([data-lang="nl"]) .i18n-en', ' .i18n-en'),
]

rc_ende = 1
try:
    rc, f = lauf()
    if rc != 0 or f != 0:
        print(f"ABBRUCH: Basis {TEST} nicht gruen (rc={rc}, fail={f})")
        sys.exit(2)
    print("Basis gruen.")
    gut = 0
    for name, datei, a, n in PROBEN:
        txt = sich[datei].decode("utf-8")
        if txt.count(a) != 1:
            print(f"  VERFEHLT {name}: Anker {txt.count(a)}x")
            continue
        datei.write_text(txt.replace(a, n, 1), encoding="utf-8")
        try:
            rc, f = lauf()
        finally:
            datei.write_bytes(sich[datei])
        biss = rc == 1 and (f or 0) > 0
        gut += biss
        print(f"  {'OK     ' if biss else 'ZAHNLOS'} {name}: rc={rc} FAIL={f}")
    print(f"{gut} von {len(PROBEN)} beissen.")
    rc_ende = 0 if gut == len(PROBEN) else 1
finally:
    for p in DATEIEN:
        p.write_bytes(sich[p])
    print("byte-gleich:", all(md5(p) == vorher[p] for p in DATEIEN))
sys.exit(rc_ende)
