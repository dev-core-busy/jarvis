"""Gegenprobe zu test_sitzung_ablauf_ui.js (Hinweis "Sitzung abgelaufen", 2026-11-24).

Dreht je EINE Zusage in einer Plattenkopie zurueck und erwartet FAILs MIT
Bilanzzeile (Exit 1) – ein Exit 2 waere "konnte nicht laufen", kein Biss.
Stellt danach byte-gleich wieder her (md5).
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
AB = W / "frontend/js/sitzung_ablauf.js"
SI = W / "frontend/js/sitzung.js"
APP = W / "frontend/js/app.js"
IDP = W / "frontend/js/idp_anmeldung.js"
CSS = W / "frontend/css/theme.css"
CHAT = W / "frontend/chat.html"
TEST = "test_sitzung_ablauf_ui.js"
DATEIEN = [AB, SI, APP, IDP, CSS, CHAT]
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()
vorher = {p: md5(p) for p in DATEIEN}
sich = {p: p.read_bytes() for p in DATEIEN}


def lauf():
    r = subprocess.run(["node", str(W / "tests" / TEST)], capture_output=True, text=True, timeout=300)
    m = re.search(r"Ergebnis: (\d+)/(\d+)", r.stdout)
    return r.returncode, (int(m.group(2)) - int(m.group(1)) if m else None)


PROBEN = [
    ("401 loest keine Pruefung mehr aus", AB,
     "if (r && r.status === 401 && eigeneApi(url)) pruefen(true);",
     "if (false && r && r.status === 401 && eigeneApi(url)) pruefen(true);"),
    ("Anmeldeweg nicht mehr ausgenommen", AB,
     "&& !AUSGENOMMEN.test(u.pathname)", ""),
    ("fremder Ursprung zaehlt mit", AB,
     "if (u.origin !== location.origin) return false;", ""),
    ("'unbekannt' gilt als abgemeldet", AB,
     "if (gilt === false && aktiv() && S.token() === tk) zeigen();",
     "if (gilt !== true && aktiv() && S.token() === tk) zeigen();"),
    ("Rueckkehr ungedrosselt", AB,
     "if (!erzwingen && jetzt - _letztePruefung < PRUEF_ABSTAND_MS) return;", ""),
    ("Takt fragt den Server ohne Zeitsprung", AB,
     "if (sprung && !document.hidden) pruefen(true);", "if (!document.hidden) pruefen(true);"),
    ("Tab-Rueckkehr wird nicht beachtet", AB,
     "if (!document.hidden) pruefen(false);\n    });", "\n    });"),
    ("Hinweis trotz abgeraeumtem/ersetztem Token", AB,
     "if (gilt === false && aktiv() && S.token() === tk) zeigen();",
     "if (gilt === false) zeigen();"),
    ("Ruhezeit nach Schliessen fehlt", AB,
     "if (jetzt < _ruheBis) return;", ""),
    ("Wurzel / wird geprueft", AB,
     "if (p === '') return false;", ""),
    ("Neu anmelden merkt die Adresse nicht", AB,
     "S.merkeRueckkehr();\n        location.replace('/');", "location.replace('/');"),
    ("x ist ein Muelleimer", AB,
     "window.JarvisIcons.setClose(zu)", "window.JarvisIcons.setTrash(zu)"),
    ("Ziel //host wird angenommen", SI,
     "if (z.charAt(0) !== '/' || z.charAt(1) === '/') return '';", "if (z.charAt(0) !== '/') return '';"),
    ("Ziel wird nicht verbraucht", SI,
     "sessionStorage.removeItem(RUECKKEHR_SCHLUESSEL);\n", ""),
    ("Kennwort-Anmeldung wieder fest aufs Portal", APP,
     "// (sitzung_ablauf.js): dann zurueck auf die Seite von vorher.\n"
     "                        window.location.replace(window.JarvisSitzung.rueckkehrZiel('/portal'));",
     "// (sitzung_ablauf.js): dann zurueck auf die Seite von vorher.\n"
     "                        window.location.replace('/portal');"),
    ("Firmen-Anmeldung wieder fest aufs Portal", IDP,
     "window.location.replace(window.JarvisSitzung.rueckkehrZiel('/portal'));",
     "window.location.replace('/portal');"),
    ("Einbindung auf /chat fehlt", CHAT,
     '<script src="/static/js/sitzung_ablauf.js?v=1"></script>\n', ""),
    ("CSS-Klasse der Karte fehlt", CSS,
     ".jv-sitzung-ablauf-karte {", ".jv-sitzung-ablauf-kartx {"),
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
        txt = sich[datei].decode()
        if txt.count(a) != 1:
            print(f"  VERFEHLT {name}: Anker {txt.count(a)}x")
            continue
        datei.write_text(txt.replace(a, n, 1))
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
        if md5(p) != vorher[p]:
            p.write_bytes(sich[p])
    print("byte-gleich:", all(md5(p) == vorher[p] for p in DATEIEN))
sys.exit(rc_ende)
