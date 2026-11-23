#!/usr/bin/env python3
"""Gegenprobe zu tests/test_kopfzeile_ui.js: beisst der Waechter?

Jede Probe dreht EINE Zusage der gemeinsamen Titelleiste zurueck und erwartet
mindestens einen FAIL (Exit 1). Exit 0 = die Probe blieb stumm, Exit 2 = der
Waechter konnte nicht messen – beides zaehlt NICHT als Biss.

Vor jeder Probe wird die Datei auf Platte gesichert, danach zurueckgelegt und
per md5 verglichen; ein Rueckstand aus einem abgeschossenen Lauf (Laufmarke)
wird beim naechsten Start zuerst zurueckgenommen. Ohne gruenen Basislauf
bricht die Gegenprobe ab – ohne gruene Basis ist keine Probe deutbar.

    python3 tests/gegen_kopfzeile.py
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ["node", "tests/test_kopfzeile_ui.js"]
SICHERUNG = Path.home() / ".jarvis-gegen-kopfzeile"
MARKE = SICHERUNG / "laeuft.json"
# Ablage nach geordnetem Ende abraeumen (tests/lib/gegen_ablage.py) - VOR jedem
# atexit.register dieses Skripts, damit es als Letztes laeuft (atexit: LIFO).
import gegen_ablage  # noqa: E402
gegen_ablage.abraeumen_bei_ende(SICHERUNG, marke=MARKE)

PROBEN = [
    ("Rolle wird nicht sofort aus dem Merker gesetzt",
     "frontend/js/kopfzeile.js", "    laden();\n    adminKlasse(istAdmin());", "    laden();"),
    ("Merker gilt fuer jede Anmeldung",
     "frontend/js/kopfzeile.js", "if (s && s.k === _schluessel) _stand = s;", "if (s) _stand = s;"),
    ("CPU wird nicht vorgebaut",
     "frontend/js/kopfzeile.js", "        anker = cpuBalken(wirt, anker);\n", ""),
    ("Abmelden fehlt, wo die Seite keins hat",
     "frontend/js/kopfzeile.js", "        abmelden(wirt);\n", ""),
    ("Update-Pille fragt trotz Merker nach (git fetch je Seite)",
     "frontend/js/update_widget.js", "if (g) pille(g); else check();", "check();"),
    ("CPU wieder nur fuer Admins (Nachtrag 2026-11-16: fuer alle)",
     "frontend/js/kopfzeile.js",
     "        return nachDem(anker, b);\n    }\n\n    function paketKnopf",
     "        b.classList.add('jv-kopf-nuradmin');\n        return nachDem(anker, b);\n    }\n\n    function paketKnopf"),
    ("ⓘ erst nach /api/me klickbar",
     "frontend/js/syspackages.js", "        if (b) verdrahten(b);\n        pruefe();", "        pruefe();"),
    ("Admin-Sperre ohne !important",
     "frontend/css/theme.css",
     "html:not(.jv-kopf-admin) .jv-kopf-nuradmin { display: none !important; }",
     "html:not(.jv-kopf-admin) .jv-kopf-nuradmin { display: none; }"),
    ("Name in der Box wird nicht gesetzt",
     "frontend/js/kopfzeile.js", "        document.addEventListener('DOMContentLoaded', benutzerZeigen);\n", ""),
    ("Protokolle: Zusatzrand der Container wieder da",
     "frontend/css/theme.css",
     "#settings-modal .kb-container > .sk-sektion { margin-top: 0; }",
     "#settings-modal .kb-container > .sk-sektion { margin-top: 12px; }"),
    ("/settings: 32 px unter der Reiterleiste wieder da",
     "frontend/css/theme.css", "#settings-modal .settings-tabs { margin-bottom: 0; }",
     "#settings-modal .settings-tabs { margin-bottom: 2rem; }"),
    ("SAP: Analyse-Container ohne Ueberschrift",
     "frontend/sap.html",
     '            <summary><span data-i18n="sap.karte_h">Analyse</span></summary>\n',
     '            <summary></summary>\n'),
    ("SAP: Analyse wieder als Karte statt Klapp-Container",
     "frontend/sap.html",
     '        <details class="sp-sect" id="sp-sect-analyse" open>\n',
     '        <details class="sp-card" id="sp-sect-analyse" open>\n'),
    ("rechte Gruppe wird nicht ergaenzt",
     "frontend/js/kopfzeile.js", "        rechteGruppe(wirt);\n", ""),
    ("Desktop auch fuer Nicht-Admins",
     "frontend/js/kopfzeile.js", "vnc = knopf(kl + ' jv-kopf-nuradmin', {", "vnc = knopf(kl, {"),
    ("Dokumente-Modul auf /tracks nicht eingebunden",
     "frontend/tracks.html", '<script src="/static/js/info_files.js?v=9"></script>\n', ""),
    ("VEMAS: Abfrage wieder als Karte statt Klapp-Container",
     "frontend/vemas.html",
     '        <details class="vm-sect" id="vm-sect-abfrage" open>\n',
     '        <details class="vm-card" id="vm-sect-abfrage" open>\n'),
    ("Chat bindet kopfzeile.js nicht ein",
     "frontend/chat.html", '    <script src="/static/js/kopfzeile.js?v=3"></script>\n', ""),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def zurueck(melden: bool = True) -> None:
    """Gesicherte Dateien zuruecklegen (beim Start: Rueckstand eines
    abgebrochenen Laufs; am Ende: der regulaere Abschluss, still)."""
    if not MARKE.exists():
        return
    stand = json.loads(MARKE.read_text())
    for rel, summe in stand.items():
        quelle = SICHERUNG / rel.replace("/", "__")
        shutil.copy2(quelle, ROOT / rel)
        if md5(ROOT / rel) != summe:
            print(f"ABBRUCH: {rel} liess sich nicht byte-gleich zuruecklegen")
            sys.exit(2)
        if melden:
            print(f"  Rueckstand zurueckgenommen: {rel}")
    MARKE.unlink()


def lauf() -> int:
    r = subprocess.run(WAECHTER, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return r.returncode


def main() -> int:
    SICHERUNG.mkdir(mode=0o700, exist_ok=True)
    zurueck()
    if lauf() != 0:
        print("ABBRUCH: Basislauf nicht gruen – keine Probe deutbar")
        return 2
    stand = {}
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, SICHERUNG / rel.replace("/", "__"))
        stand[rel] = md5(ROOT / rel)
    MARKE.write_text(json.dumps(stand))

    biss = 0
    try:
        for name, rel, alt, neu in PROBEN:
            ziel = ROOT / rel
            text = ziel.read_text()
            if text.count(alt) != 1:
                print(f"  ✗ {name}: Anker {text.count(alt)}x gefunden – Probe kaputt")
                continue
            ziel.write_text(text.replace(alt, neu))
            try:
                code = lauf()
            finally:
                shutil.copy2(SICHERUNG / rel.replace("/", "__"), ziel)
            if code == 1:
                biss += 1
                print(f"  ✓ beisst: {name}")
            else:
                print(f"  ✗ STUMM (Exit {code}): {name}")
    finally:
        zurueck(melden=False)

    for rel, summe in stand.items():
        if md5(ROOT / rel) != summe:
            print(f"ABBRUCH: {rel} weicht nach dem Lauf ab")
            return 2
    print(f"\nErgebnis: {biss}/{len(PROBEN)} Proben beissen")
    return 0 if biss == len(PROBEN) else 1


if __name__ == "__main__":
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.exit(main())
