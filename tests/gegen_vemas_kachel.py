#!/usr/bin/env python3
"""Gegenprobe: beissen tests/test_vemas_kachel_anmeldung.py und
tests/test_vemas_kachel_ui.js?

Sabotierte KOPIEN in einem Wegwerf-Verzeichnis, uebergeben ueber
VEMAS_KACHEL_MODUL / VEMAS_KACHEL_MAIN / VEMAS_PORTAL_JS / VEMAS_JS – die echten
Dateien werden nie angefasst. Vorher ein gruener Basislauf; eine Probe "beisst"
nur mit Exit 1 UND mindestens einem FAIL (Exit 2 und Abstuerze zaehlen nicht).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = [
    [sys.executable, str(HIER / "test_vemas_kachel_anmeldung.py")],
    ["node", str(HIER / "test_vemas_kachel_ui.js")],
]
DATEIEN = {
    "modul": (ROOT / "backend" / "vemas_accounts.py", "VEMAS_KACHEL_MODUL"),
    "main": (ROOT / "backend" / "main.py", "VEMAS_KACHEL_MAIN"),
    "portal": (ROOT / "frontend" / "js" / "vemas_portal.js", "VEMAS_PORTAL_JS"),
    "vemasjs": (ROOT / "frontend" / "js" / "vemas.js", "VEMAS_JS"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("Kennwort trotz Schalter verschluesselt gespeichert", "modul",
     "                if pflicht:\n                    sitzung_neu[f] = wert\n",
     "                if False:\n                    sitzung_neu[f] = wert\n"),
    ("Aufloesung ignoriert den Schalter", "modul",
     "    if kachel_pflicht():\n        return _aufloesen_kachel(un, trotz_aussetzer)\n", ""),
    ("ohne Anmeldung wird verbunden", "modul",
     '    if not _sitzung_holen(un):\n        return _kein_zugang(un, "Fuer VEMAS ist eine Anmeldung noetig. " + ANMELDEN_TEXT)\n', ""),
    ("Zugang ohne Kennwort gilt als nicht eingerichtet", "modul",
     "    if kachel_pflicht():\n        return _eingerichtet(k)\n", ""),
    ("Einschalten entfernt keine Kennwoerter", "modul",
     "        for f in weg:\n            del k[f]\n", "        for f in weg:\n            pass\n"),
    ("Anmeldung laeuft nie ab", "modul",
     '    if float(s.get("bis") or 0) < time.time():\n', "    if False:\n"),
    ("Anmeldefehler beendet die Anmeldung nicht", "modul",
     "        if anmeldefehler and kachel_pflicht() and sitzung_beenden(un):\n", "        if False:\n"),
    ("Anmeldekarte auch ohne erfolgreichen Vorlauf", "modul",
     '    if not int(k.get("letzter_erfolg", 0) or 0) or not server_konfiguriert():\n',
     "    if not server_konfiguriert():\n"),
    ("Client liest das Kennwort von der Platte", "modul",
     "    if kachel_pflicht(c):\n        s = _sitzung_holen(", "    if False:\n        s = _sitzung_holen("),
    ("Einstellungs-Speichern behandelt nur SAP", "main",
     'sap_kachel = name in ("sap", "vemas") and', 'sap_kachel = name == "sap" and'),
    ("Jarvis-Abmeldung laesst die VEMAS-Anmeldung stehen", "main",
     "        _vmacc.sitzung_beenden(user)\n", "        pass\n"),
    ("Status ohne Anmeldekarte", "main",
     "        anmeldung = vemas_accounts.anmeldung_anbieten(user) if kachel else {}\n",
     "        anmeldung = {}\n"),
    ("Anmeldekarte wird nie gezeigt", "portal",
     "                    loginZeigen(d.anmeldung);\n                    return;\n", "                    return;\n"),
    ("Merken auch bei falschem Kennwort", "portal",
     "                if (p) p.value = '';\n                if (t && t.ok) {\n"
     "                    if (feld !== 'api_token') kennwortMerken(name, pw);\n",
     "                if (p) p.value = '';\n                kennwortMerken(name, pw);\n"
     "                if (t && t.ok) {\n"),
    ("Kachel-Modus meldet doppelt an", "portal",
     "if (accS) accS.addEventListener('click', function () { if (!_kachel) saveAccount(); });",
     "if (accS) accS.addEventListener('click', saveAccount);"),
    ("Einschalten ohne Warnhinweis", "vemasjs",
     "            if (checked('vemas-kachel-pflicht') && !(this._cfg && this._cfg.kachel_anmeldung)) {",
     "            if (false) {"),
    ("Liste ohne Kennwort-Zustand", "vemasjs",
     "                            + Manager._kennwortZustand(a, kachel) + '</li>';", "                            + '</li>';"),
]


def lauf(umgebung: dict) -> tuple:
    """Alle Pruefstaende; Rueckgabe (Exit, FAIL-Summe, Ausgabe).

    Exit 2 bei irgendeinem Pruefstand geht vor (konnte nicht messen); eine
    fehlende Bilanzzeile heisst FAIL None – das zaehlt nicht als Biss."""
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
    print(f"Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_sapkachel_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??  {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
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
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
