#!/usr/bin/env python3
"""Gegenprobe zu tests/test_zugang_klappen_ui.js: beisst der Waechter?

Jede Probe sabotiert KOPIEN der betroffenen Frontend-Dateien in einem
Wegwerf-Ordner (KLAPPEN_DIR) – der Arbeitsbaum wird nie angefasst, ein
abgebrochener Lauf hinterlaesst also keinen Rueckstand.

Vorab ein Basislauf gegen die unveraenderten Kopien: ohne gruene Basis ist
keine Probe deutbar (Exit 2). Eine Probe "beisst", wenn der Waechter mit
Exit 1 UND einer Bilanzzeile endet – ein Absturz ist kein Biss.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
    python3 tests/gegen_zugang_klappen.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WAECHTER = REPO / "tests" / "test_zugang_klappen_ui.js"
DATEIEN = ["sap.html", "vemas.html", "jira_addon.html", "confluence_addon.html",
           "js/sap_portal.js", "js/vemas_portal.js", "js/jira_addon.js",
           "js/confluence_addon.js", "js/zugang_sitzung.js"]

# (Name, Datei, alt, neu, Anzahl Ersetzungen) – je Probe EIN Eingriff.
PROBEN = [
    ("SAP: Klapp-Aufruf fehlt", "js/sap_portal.js",
     "accKlappen(!d.configured", "void (!d.configured", 1),
    ("VEMAS: Klapp-Aufruf fehlt", "js/vemas_portal.js",
     "accKlappen(!d.configured", "void (!d.configured", 1),
    ("SAP/VEMAS: Anmeldekarte zaehlt nicht", "js/vemas_portal.js",
     "accKlappen(!d.configured && !(ohneAnmeldung && d.anmeldung && d.anmeldung.feld));",
     "accKlappen(!d.configured);", 1),
    ("Jira: gemeinsamer Zugang zaehlt nicht", "js/jira_addon.js",
     "a.sammel_vorhanden === false\n", "true\n", 1),
    ("Confluence: eigener Token zaehlt nicht", "js/confluence_addon.js",
     "&& !(a.vorhanden && a.aktiv !== false)", "", 1),
    ("Jira: Klick schnappt beim Neuzeichnen zurueck", "js/jira_addon.js",
     "if (erstes || (noetig && !_accNoetig)) s.open", "if (true) s.open", 1),
    ("Sitzungsbetrieb: gemeinsamer Zugang zaehlt nicht", "js/zugang_sitzung.js",
     "&& a.sammel_vorhanden === false", "", 1),
    ("Sitzungsbetrieb: angemeldet zaehlt nicht", "js/zugang_sitzung.js",
     "klappen(!!a.server_konfiguriert && !a.angemeldet", "klappen(!!a.server_konfiguriert", 1),
]


def kopie(ziel: Path):
    for rel in DATEIEN:
        q = REPO / "frontend" / rel
        z = ziel / rel
        z.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(q, z)


def lauf(ordner: Path):
    p = subprocess.run(["node", str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, env=dict(os.environ, KLAPPEN_DIR=str(ordner)))
    m = re.search(r"ERGEBNIS: (\d+) OK, (\d+) FAIL", p.stdout)
    return p.returncode, (int(m.group(2)) if m else None), p.stdout


def main():
    if not WAECHTER.exists():
        print("ABBRUCH: Waechter fehlt"); return 2
    with tempfile.TemporaryDirectory(prefix="gegen_klappen_") as tmp:
        basis = Path(tmp) / "basis"
        kopie(basis)
        rc, fails, out = lauf(basis)
        if rc != 0 or fails != 0:
            print(out[-2000:])
            print(f"ABBRUCH: Basislauf nicht gruen (Exit {rc}, FAIL {fails})")
            return 2
        print("Basislauf gruen.\n")
        stumm = 0
        for i, (name, rel, alt, neu, n) in enumerate(PROBEN):
            ordner = Path(tmp) / f"p{i}"
            kopie(ordner)
            d = ordner / rel
            text = d.read_text(encoding="utf-8")
            if text.count(alt) != n:
                print(f"ABBRUCH: Anker der Probe '{name}' trifft {text.count(alt)}x statt {n}x")
                return 2
            d.write_text(text.replace(alt, neu), encoding="utf-8")
            rc, fails, _ = lauf(ordner)
            if rc == 1 and fails:
                print(f"  BEISST {name}: {fails} FAIL")
            else:
                stumm += 1
                print(f"  STUMM  {name}: Exit {rc}, FAIL {fails}")
        print(f"\n{len(PROBEN) - stumm} von {len(PROBEN)} Proben beissen.")
        return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
