#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_office_idp_ui.js? (IdP-Anmeldung der Office-Add-ins)

Sabotierte KOPIEN in einem Wegwerf-Verzeichnis (OFFICE_IDP_JS, ADDIN_JS,
EXCEL_JS, ADDIN_HTML, EXCEL_HTML) – die echten Dateien werden nie angefasst.
Vorher ein gruener Basislauf; eine Probe "beisst" nur mit Exit 1 UND
mindestens einem FAIL (Exit 2 und Abstuerze zaehlen nicht).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = [["node", str(HIER / "test_office_idp_ui.js")]]
DATEIEN = {
    "idp": (ROOT / "frontend" / "js" / "office_idp.js", "OFFICE_IDP_JS"),
    "addin": (ROOT / "frontend" / "addin" / "addin.js", "ADDIN_JS"),
    "excel": (ROOT / "frontend" / "excel-addin" / "excel.js", "EXCEL_JS"),
    "ahtml": (ROOT / "frontend" / "addin" / "taskpane.html", "ADDIN_HTML"),
    "xhtml": (ROOT / "frontend" / "excel-addin" / "taskpane.html", "EXCEL_HTML"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("Knopf auch ohne Dialog-API", "idp",
     "return !!(_lage && _lage.aktiv && dialogDa() && kryptoDa());",
     "return !!(_lage && _lage.aktiv && kryptoDa());"),
    ("Knopf auch ohne aktiven IdP", "idp",
     "return !!(_lage && _lage.aktiv && dialogDa() && kryptoDa());",
     "return !!(_lage && dialogDa() && kryptoDa());"),
    ("fallback klappt nicht ein", "idp",
     "var zu = an && _lage.ad_modus !== 'zusaetzlich' && !_offen;",
     "var zu = false;"),
    ("zusaetzlich klappt trotzdem ein", "idp",
     "var zu = an && _lage.ad_modus !== 'zusaetzlich' && !_offen;",
     "var zu = an && !_offen;"),
    ("Link klappt nicht auf", "idp",
     "            kennwortAufklappen();\n        });",
     "        });"),
    ("zustand wird nicht verglichen", "idp",
     "if (!m || typeof m !== 'object' || m.zustand !== zustand) {",
     "if (!m || typeof m !== 'object') {"),
    ("challenge ist nicht der Hash", "idp",
     "challengeAus(verifier).then(function (challenge) {",
     "challengeAus(verifier + 'x').then(function (challenge) {"),
    ("verifier geht nicht mit", "idp",
     "body: JSON.stringify({ code: code, verifier: verifier })",
     "body: JSON.stringify({ code: code })"),
    ("falsche App-Kennung", "idp",
     "encodeURIComponent(opts.app) + '&challenge='",
     "'portal' + '&challenge='"),
    ("Fehler klappt die Maske nicht auf", "idp",
     "        function scheitern(text) {\n            fertig();\n            melde(text, 'fehler');\n            kennwortAufklappen();",
     "        function scheitern(text) {\n            fertig();\n            melde(text, 'fehler');"),
    ("Fehler gibt den Knopf nicht frei", "idp",
     "        function scheitern(text) {\n            fertig();",
     "        function scheitern(text) {"),
    ("Kennung wird nicht uebersetzt", "idp",
     "return T('login.idp_err.' + kennung, allg);", "return allg;"),
    ("Erfolg ohne Folgeweg", "idp",
     "                melde('');\n                opts.weiter();",
     "                melde('');"),
    ("12006 gilt als Fehler", "idp",
     "if (arg && arg.error === DIALOG_GESCHLOSSEN) {", "if (false) {"),
    ("spaete Nachricht nach dem Schliessen verarbeitet", "idp",
     "                            if (erledigt) return;\n                            var m = null;",
     "                            var m = null;"),
    ("kein drehender Kreis", "idp",
     "                k.className = 'jv-pkg-spin';", "                k.className = 'x';"),
    ("Dialog-Fehlschlag ohne Meldung", "idp",
     "if (!res || String(res.status).toLowerCase() !== 'succeeded' || !res.value) {\n"
     "                            scheitern(",
     "if (!res || String(res.status).toLowerCase() !== 'succeeded' || !res.value) {\n"
     "                            fertig(); return; scheitern("),
    ("Outlook: zeigeLogin zeigt den Knopf nie", "addin",
     "        if (_idp) { try { _idp.anzeigen(); } catch (e) { } }", ""),
    ("Outlook: Folgeweg ohne start()", "addin",
     "weiter: function () { melde('ad-login-status', speicherHinweis()); start(); }",
     "weiter: function () { melde('ad-login-status', speicherHinweis()); }"),
    ("Outlook: Token nicht gesetzt", "addin",
     "                    app: 'outlook', praefix: 'ad', T: T,\n                    tokenSetzen: tokenSetzen,",
     "                    app: 'outlook', praefix: 'ad', T: T,\n                    tokenSetzen: function () { },"),
    ("Excel: zeigeLogin zeigt den Knopf nie", "excel",
     "        if (_idp) { try { _idp.anzeigen(); } catch (e) { } }", ""),
    ("Excel: Folgeweg ohne pruefeFreigabe", "excel",
     "                        pruefeFreigabe(_speicherGeht ? '' :",
     "                        void (_speicherGeht ? '' :"),
    ("Outlook: Kennwortmaske ohne Klapp-Container", "ahtml",
     '        <!-- Kennwortanmeldung: bei IdP-Modus "fallback" eingeklappt (Notweg). -->\n        <div id="ad-kennwort">',
     '        <div id="ad-kennwort-x">'),
    ("Excel: Modul nicht eingebunden", "xhtml",
     '<script src="/static/js/office_idp.js?v=1"></script>\n', ""),
]


def lauf(umgebung: dict) -> tuple:
    """Alle Pruefstaende; Rueckgabe (Exit, FAIL-Summe, Ausgabe)."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **umgebung)
    codes, summe, aus = [], 0, ""
    for befehl in WAECHTER:
        r = subprocess.run(befehl, cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=300)
        m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
        codes.append(r.returncode)
        aus += r.stdout + r.stderr
        if m is None:
            summe = None
        elif summe is not None:
            summe += int(m.group(2))
    code = 2 if 2 in codes else max(codes)
    return code, summe, aus


def main() -> int:
    nicht_gedeckt = {p[1] for p in PROBEN} - set(DATEIEN)
    if nicht_gedeckt:
        print(f"ABBRUCH: Proben auf unbekannte Dateien: {nicht_gedeckt}")
        return 2
    code, fails, aus = lauf({})
    if code != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, FAIL {fails})")
        print(aus[-2000:])
        return 2
    print("Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_office_idp_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??     {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
                stumm += 1
                continue
            ziel = Path(tmp) / f"probe{i}_{quelle.name}"
            ziel.write_text(text.replace(alt, neu), encoding="utf-8")
            code, fails, aus = lauf({var: str(ziel)})
            if code == 1 and fails:
                print(f"  BEISST {i:2d} {name} ({fails} FAIL)")
            else:
                stumm += 1
                print(f"  STUMM  {i:2d} {name} (Exit {code}, FAIL {fails})")
                print("         " + aus.strip().splitlines()[-1][:200] if aus.strip() else "")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
