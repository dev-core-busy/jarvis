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
    ("CPU fragt auch fuer Nicht-Admins",
     "frontend/js/cpubar.js",
     "if (window.JarvisKopf && window.JarvisKopf.adminBelegt() === false) return;", ""),
    ("ⓘ erst nach /api/me klickbar",
     "frontend/js/syspackages.js", "        if (b) verdrahten(b);\n        pruefe();", "        pruefe();"),
    ("Admin-Sperre ohne !important",
     "frontend/css/theme.css",
     "html:not(.jv-kopf-admin) .jv-kopf-nuradmin { display: none !important; }",
     "html:not(.jv-kopf-admin) .jv-kopf-nuradmin { display: none; }"),
    ("Chat bindet kopfzeile.js nicht ein",
     "frontend/chat.html", '    <script src="/static/js/kopfzeile.js?v=1"></script>\n', ""),
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
