#!/usr/bin/env python3
"""Gegenproben zu tests/test_browser_addon_idp.js (Firmenkonto-Anmeldung der
Browser-Erweiterung).

Jede Probe nimmt GENAU EINE Zusage weg und misst, ob der Waechter mit Exit 1
UND einer FAIL-Zeile antwortet. Exit 2 oder ein Absturz zaehlen NICHT als Biss
(Register: eine Sabotage, die den Waechter abstuerzen laesst, hat nicht
gebissen).

Sabotiert wird eine KOPIE von browser-addon/ (der Waechter liest sie ueber
ADDON_DIR); der Arbeitsbaum wird nie beschrieben. Ohne gruenen Basislauf auf
der Kopie ist keine Probe deutbar (Exit 2).
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_browser_addon_idp.js"

# (Name, Datei in browser-addon/, alt, neu)
PROBEN = [
    ("zustand wird nicht geprueft", "background.js",
     '  if (q.get("zustand") !== zustand) {', "  if (false) {"),
    ("Rueckkehr an fremde Adresse angenommen", "background.js",
     '    if (u.origin !== new URL(rueck).origin) throw new Error("fremde Adresse");\n', ""),
    ("challenge ist der verifier selbst (kein S256)", "background.js",
     "  return { verifier, challenge: _b64url(hash),", "  return { verifier, challenge: verifier,"),
    ("Einloesen ohne verifier", "background.js",
     "rumpf: { code, verifier } });", "rumpf: { code } });"),
    ("Abbruch gilt als Fehler (Maske springt auf)", "background.js",
     'return ende("Anmeldung über das Firmenkonto abgebrochen.", true);',
     'return ende("Anmeldung über das Firmenkonto abgebrochen.", false);'),
    ("Sitzung wird nicht geschrieben", "background.js",
     "  await sitzungSchreiben({ token: d.token, benutzer });\n", ""),
    ("einstSchreiben verwirft idp_kennwort", "background.js",
     "  if (teil.idp_kennwort !== undefined) neu.idp_kennwort = !!teil.idp_kennwort;\n", ""),
    ("Nachrichtenfall idp_status fehlt", "background.js",
     '        case "idp_status":\n          antworten(Object.assign({ ok: true }, await idpStatus(nachricht.basis)));\n          break;\n', ""),
    ("Status ohne identity-Pruefung", "background.js",
     "  if (!idpApi()) return { aktiv: false };\n  basis =", "  basis ="),
    ("identity nur an der chrome-Wurzel gesucht", "background.js",
     "  const id = api.identity;",
     '  const id = (typeof chrome !== "undefined" && chrome.identity) || null;'),
    ("Freigabe nach IdP-Anmeldung nicht geprueft", "background.js",
     "  return Object.assign(await freigabePruefen(benutzer), { angemeldet: true });",
     '  return { ok: true, benutzer, erlaubt: true, hinweis: "", angemeldet: true };'),
    ("ad_modus zusaetzlich ignoriert", "popup.js",
     '_idpStatus.ad_modus !== "zusaetzlich" && ', ""),
    ("Fehlschlag klappt die Kennwortmaske nicht auf", "popup.js",
     "    if (!a.abgebrochen) {\n      _kennwortOffen = true;",
     "    if (false) {\n      _kennwortOffen = true;"),
    ("IdP-Anmeldung ohne Zugriffsrecht", "popup.js",
     '    melde("Prüfe das Zugriffsrecht …", true);\n    await zugriffSichern(basis);\n    melde("Anmeldung über',
     '    melde("Anmeldung über'),
    ("start ignoriert idp_kennwort", "popup.js",
     "      if (z.idp_kennwort === true) _kennwortOffen = true;\n", ""),
    ("start zeigt die verpasste Meldung nicht", "popup.js",
     '    if (_idpMeldung) { melde(_idpMeldung); _idpMeldung = ""; }', ""),
    ("Erfolg ohne Aufbau des Arbeitsbereichs", "popup.js",
     '      nachAnmeldung(a, basis, a.benutzer || "");\n      return;', "      return;"),
    ("STAND laeuft auseinander", "popup.js",
     "const STAND = 10;", "const STAND = 9;"),
    ("identity fehlt im Firefox-Manifest", "manifest.firefox.json",
     '    "scripting",\n    "identity"\n', '    "scripting"\n'),
    ("IdP-Block im Markup sichtbar vorbelegt", "popup.html",
     '<div id="idp-block" class="idp-block" hidden>', '<div id="idp-block" class="idp-block">'),
]


def bilanz(text: str):
    m = re.search(r"(\d+) OK, (\d+) FAIL", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def lauf(kopie: Path) -> tuple[int, str]:
    env = dict(os.environ, ADDON_DIR=str(kopie))
    r = subprocess.run(["node", str(WAECHTER)], capture_output=True, text=True,
                       cwd=str(ROOT), timeout=300, env=env)
    return r.returncode, r.stdout + r.stderr


def main() -> int:
    kopie = Path(tempfile.mkdtemp(prefix="gegen_browser_addon_idp_"))
    try:
        shutil.copytree(ROOT / "browser-addon", kopie, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("dist"))
        rc, aus = lauf(kopie)
        b = bilanz(aus)
        if rc != 0 or not b or b[1] != 0:
            print("ABBRUCH: Basislauf auf der Kopie nicht gruen (rc=%s, %s)\n%s" % (rc, b, aus[-800:]))
            return 2
        print("Basislauf gruen (%d OK).\n" % b[0])
        beissen = 0
        for name, datei, alt, neu in PROBEN:
            ziel = kopie / datei
            original = ziel.read_text(encoding="utf-8")
            if original.count(alt) != 1:
                print("  ???  %-52s Anker %dx gefunden" % (name, original.count(alt)))
                continue
            ziel.write_text(original.replace(alt, neu), encoding="utf-8")
            try:
                rc, aus = lauf(kopie)
            finally:
                ziel.write_text(original, encoding="utf-8")
            b = bilanz(aus)
            if rc == 1 and b and b[1] > 0:
                beissen += 1
                faelle = [z.strip()[5:70] for z in aus.splitlines() if z.strip().startswith("FAIL")]
                print("  BISS %-52s %d FAIL  %s" % (name, b[1], faelle[:2]))
            elif rc == 0:
                print("  ZAHN %-52s 0 FAIL – beisst NICHT" % name)
            else:
                print("  ABBR %-52s rc=%s ohne gueltige Bilanz – kein Biss\n%s" % (name, rc, aus[-400:]))
        print("\n%d/%d Proben beissen (sabotiert wurde nur die Kopie in %s)"
              % (beissen, len(PROBEN), kopie))
        return 0 if beissen == len(PROBEN) else 1
    finally:
        shutil.rmtree(kopie, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
