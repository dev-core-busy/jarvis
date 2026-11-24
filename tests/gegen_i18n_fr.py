"""Gegenprobe zu test_i18n_fr.js (Franzoesisch + Klappmenue der Sprachwahl, 2026-11-24).

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
FR = W / "frontend/js/i18n_fr.js"
CSS = W / "frontend/css/theme.css"
PORTAL = W / "frontend/portal.html"
TEST = "test_i18n_fr.js"
DATEIEN = [I18N, FR, CSS, PORTAL]
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
    ("FR-Schluessel fehlt", FR,
     '    "portal.welcome": "Bienvenue",\n', ''),
    ("Platzhalter {marke} verloren", FR,
     'peut confier des tâches de code à {marke}. Les tâches', 'peut confier des tâches de code. Les tâches'),
    ("schliessendes </b> verloren", FR,
     '<b>La clé reste visible ici.</b>', '<b>La clé reste visible ici.'),
    ("Seite bindet i18n_fr.js nicht ein", PORTAL,
     '<script src="/static/js/i18n_fr.js?v=1"></script>', ''),
    ("Rueckfall fr ohne Englisch", I18N,
     "fr: ['fr', 'en', 'de']", "fr: ['fr', 'de']"),
    ("Klick auf aktive Sprache setzt nur neu", I18N,
     "if (gruppe && b.classList.contains('active')) {", "if (false) {"),
    ("Esc schliesst nicht", I18N,
     "if (e.key === 'Escape') _sprachMenuesSchliessen(null);", "if (false) _sprachMenuesSchliessen(null);"),
    ("andere Gruppe schliesst nicht (Klick auf Knopf)", I18N,
     "    var gruppe = b && b.closest ? b.closest('.lang-toggle') : null;\n    _sprachMenuesSchliessen(gruppe);",
     "    var gruppe = b && b.closest ? b.closest('.lang-toggle') : null;\n    if (!b) _sprachMenuesSchliessen(gruppe);"),
    ("Klick daneben / andere Gruppe schliesst nicht", I18N,
     "    _sprachMenuesSchliessen(gruppe);\n    if (!b) return;", "    if (!b) return;"),
    ("unbekannte Sprache ohne aktiven Knopf", I18N,
     "        aktiv.classList.add('active');\n", ""),
    ("aktive Sprache nicht vorn", I18N,
     "    knoepfe.forEach(function (k) { if (k !== aktiv) gruppe.appendChild(k); });",
     "    knoepfe.forEach(function (k) { if (k !== aktiv) gruppe.insertBefore(k, gruppe.firstChild); });"),
    ("Angebote in Wechselfolge statt fest", I18N,
     "    knoepfe.sort(function (a, b) { return rang(a) - rang(b); });\n", ""),
    ("theme.css blendet nicht aktive Sprachen nicht aus", CSS,
     ".lang-toggle:not(.offen) > .lang-toggle-btn:not(.active) { display: none; }",
     ".lang-toggle:not(.offen) > .lang-toggle-btn:not(.active) { }"),
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
