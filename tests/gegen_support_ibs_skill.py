#!/usr/bin/env python3
"""Gegenprobe zu test_support_ibs_skill: beisst jeder Waechter einzeln?

Jede Probe dreht genau eine Zusage zurueck und erwartet einen FAIL. Bleibt der
Waechter gruen, ist das ein Testmangel. Sicherung auf Platte mit Laufmarke: Wird
der Lauf abgeschossen, stellt der naechste Start den Arbeitsbaum zuerst wieder her.
"""
import atexit
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ABLAGE = pathlib.Path.home() / ".gegen-support-ibs"
MARKE = ABLAGE / ".laeuft"
SERVER = ["python3", "tests/test_support_ibs_skill.py"]
UI = ["node", "tests/test_support_ibs_skill_ui.js"]
DATEIEN = ["backend/main.py", "frontend/js/support.js", "frontend/support.html"]

PROBEN = [
    ("Status meldet den Skill nicht", "backend/main.py",
     '"ibs_active": _skill_active("kundenverwaltung"),', '"ibs_active": True,', SERVER),
    ("Suche prueft den Skill nicht", "backend/main.py",
     'if bool(body.get("ibs")) and _skill_active("kundenverwaltung"):',
     'if bool(body.get("ibs")):', SERVER),
    ("Option wird nicht ausgeblendet", "frontend/js/support.js",
     "ibsWrap.classList.toggle('hidden', !ibsAktiv);",
     "ibsWrap.classList.remove('hidden');", UI),
    ("Filtereintrag bleibt stehen", "frontend/js/support.js",
     "if (ibsFilter && !ibsAktiv) ibsFilter.remove();", "", UI),
    ("Kaestchen haengt nur am Zugang", "frontend/js/support.js",
     "ibsBereit = ibsAktiv && !!d.ibs_configured;", "ibsBereit = !!d.ibs_configured;", UI),
    ("Huelle startet sichtbar", "frontend/support.html",
     'id="sup-opt-ibs-wrap" class="hidden"', 'id="sup-opt-ibs-wrap"', UI),
]


def zuruecklegen():
    for rel in DATEIEN:
        kopie = ABLAGE / rel.replace("/", "__")
        if kopie.exists():
            shutil.copy2(kopie, ROOT / rel)
    if MARKE.exists():
        MARKE.unlink()


def lauf(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout + r.stderr)
    return r.returncode, int(m.group(2)) if m else -1


def main():
    fehlend = sorted({p[1] for p in PROBEN} - set(DATEIEN))
    if fehlend:
        print("ABBRUCH: nicht gesichert: %s" % fehlend)
        return 2
    if MARKE.exists():
        print("Abgebrochener Vorlauf gefunden, stelle zuerst wieder her.")
        zuruecklegen()
    for cmd in (SERVER, UI):
        code, fails = lauf(cmd)
        if code != 0 or fails != 0:
            print("ABBRUCH: kein gruener Basislauf (%s: Exit %s, FAIL %s)" % (cmd[1], code, fails))
            return 2
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABLAGE / rel.replace("/", "__"))
    MARKE.write_text("laeuft", encoding="utf-8")
    atexit.register(zuruecklegen)

    bissen = 0
    for name, rel, alt, neu, cmd in PROBEN:
        pfad = ROOT / rel
        vorher = pfad.read_text(encoding="utf-8")
        if vorher.count(alt) != 1:
            print("ABBRUCH: Probe '%s' passt nicht (%d Treffer)" % (name, vorher.count(alt)))
            return 2
        pfad.write_text(vorher.replace(alt, neu), encoding="utf-8")
        try:
            code, fails = lauf(cmd)
        finally:
            pfad.write_text(vorher, encoding="utf-8")
        beisst = code == 1 and fails > 0
        bissen += beisst
        print("  %s %s: Exit %s, %s FAIL" % ("✓" if beisst else "✗", name, code, fails))
    print("\n%d von %d Proben beissen" % (bissen, len(PROBEN)))
    return 0 if bissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
