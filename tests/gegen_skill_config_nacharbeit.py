#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_skill_config_nacharbeit.py?

Legt sabotierte KOPIEN von ``backend/main.py``, ``backend/config.py`` bzw.
``backend/skills/manager.py`` in ein Wegwerf-Verzeichnis und gibt sie dem
Waechter ueber ``SKNACH_MAIN`` / ``SKNACH_CONFIG`` / ``SKNACH_MANAGER`` mit –
die echten Dateien werden nie angefasst, ein abgebrochener Lauf hinterlaesst
also keinen Rueckstand.

Vorher ein Basislauf gegen die unveraenderten Dateien: ohne gruene Basis ist
keine Probe deutbar.

ZWEI ERWARTUNGEN, getrennt gezaehlt – sonst ist "konnte nicht laufen" von
"ich beisse" nicht zu unterscheiden:
  * ``biss``    – Produkt-Sabotage: Exit 1 und mindestens ein FAIL.
  * ``abbruch`` – Mess-Sabotage (die Attrappe spiegelt das Original nicht
                  mehr): Exit 2, KEIN stilles Gruen.

Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht
laufen.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = HIER / "test_skill_config_nacharbeit.py"
DATEIEN = {
    "main": (ROOT / "backend" / "main.py", "SKNACH_MAIN"),
    "config": (ROOT / "backend" / "config.py", "SKNACH_CONFIG"),
    "sap": (ROOT / "backend" / "sap_accounts.py", "SKNACH_SAP"),
}

# Der Altstand vom 2026-11-05 – der gemeldete Fehler, Zeile fuer Zeile.
ALT_KOPIE = ("    gespeichert = dict(sm.get_skill_config(name) or {})",
             "    gespeichert = sm.get_skill_config(name) or {}")
ALT_SAP = ("    if success and sap_kachel:",
           "    if success and sap_kachel and not gespeichert.get(\"kachel_anmeldung\"):")
ALT_JIRA = ('    if success and _pers_modul and _endzustand("persoenliche_zugaenge") is False:',
            '    if (success and _pers_modul and body.get("persoenliche_zugaenge") is False\n'
            '            and gespeichert.get("persoenliche_zugaenge") is not False):')

# (Name, Erwartung, Datei, [(alt, neu), ...])
PROBEN = [
    ("Vorzustand wieder als lebendes dict gelesen", "biss", "main", [ALT_KOPIE]),
    ("SAP-Loeschung wieder am Umschalt-Moment", "biss", "main", [ALT_SAP]),
    ("Jira-Loeschung wieder am Umschalt-Moment", "biss", "main", [ALT_JIRA]),
    ("KOMPLETTER ALTSTAND (der gemeldete Fehler)", "biss", "main",
     [ALT_KOPIE, ALT_SAP, ALT_JIRA]),
    ("Endzustand ignoriert den Bestand (nur Body)", "biss", "main",
     [("        return body[feld] if feld in body else gespeichert.get(feld)",
       "        return body.get(feld)")]),
    ("kennwoerter_entfernen wird nicht gerufen", "biss", "main",
     [("            _n = _sapacc.kennwoerter_entfernen()", "            _n = 0")]),
    ("alle_entfernen wird nicht gerufen", "biss", "main",
     [('            _nj = importlib.import_module("backend." + _pers_modul).alle_entfernen()',
       "            _nj = 0")]),
    # 2026-11-15: der Schalter fuer Confluence; SAP/VEMAS bewusst NICHT
    ("Confluence fehlt in der Zuordnung", "biss", "main",
     [('    _PERSOENLICH_MODULE = {"jira": "jira_accounts", "confluence": "confluence_accounts"}',
       '    _PERSOENLICH_MODULE = {"jira": "jira_accounts"}')]),
    ("SAP/VEMAS wieder in der Zuordnung (loeschte ganze Zugaenge)", "biss", "main",
     [('    _PERSOENLICH_MODULE = {"jira": "jira_accounts", "confluence": "confluence_accounts"}',
       '    _PERSOENLICH_MODULE = {"jira": "jira_accounts", "confluence": "confluence_accounts",\n'
       '                           "sap": "sap_accounts", "vemas": "vemas_accounts"}')]),
    ("nur noch Jira wird geraeumt (alter Zweig)", "biss", "main",
     [('    if success and _pers_modul and _endzustand("persoenliche_zugaenge") is False:',
       '    if success and name == "jira" and _endzustand("persoenliche_zugaenge") is False:')]),
    ("SAP/VEMAS weisen persoenliche_zugaenge:false wieder ab", "biss", "main",
     [('    sap_kachel = name in ("sap", "vemas") and bool(_endzustand("kachel_anmeldung"))\n',
       '    if name in ("sap", "vemas") and _endzustand("persoenliche_zugaenge") is False:\n'
       '        return JSONResponse({"success": False, "code": "kachel_braucht_persoenlich"},\n'
       '                            status_code=400)\n'
       '    sap_kachel = name in ("sap", "vemas") and bool(_endzustand("kachel_anmeldung"))\n')]),
    ("Aktivitaet traegt nicht mehr den Bereich", "biss", "main",
     [('"confluence_persoenliche_zugaenge_aus"', '"jira_persoenliche_zugaenge_aus"')]),
    ("Stand wird gar nicht gespeichert", "biss", "main",
     [("    success = sm.update_skill_config(name, body)", "    success = True")]),
    # Seit 2026-11-15 BLEIBT das Sammel-Kennwort (Rueckfall wie Jira/Confluence);
    # die Probe stellt das fruehere Leeren wieder her.
    ("Sammel-Kennwort wird wieder geleert", "biss", "main",
     [("    body = _sr.leere_geheimfelder_behalten(body, gespeichert)\n"
       "    success = sm.update_skill_config(name, body)\n",
       "    body = _sr.leere_geheimfelder_behalten(body, gespeichert)\n"
       "    if sap_kachel:\n        for _f in _sapacc.GEHEIMFELDER:\n            body[_f] = \"\"\n"
       "    success = sm.update_skill_config(name, body)\n")]),
    ("Zahl der entfernten Kennwoerter nicht protokolliert", "biss", "main",
     [("                        kennwoerter_entfernt=_n)",
       "                        )")]),
    ("Fehlschlag des Loeschens wird verschluckt", "biss", "main",
     [("            print(f\"[{name}] persoenliche Kennwoerter nicht entfernt: {e}\", flush=True)\n"
       "            return JSONResponse({\"success\": False,\n"
       "                                 \"error\": \"Die Einstellung ist gespeichert, aber die \"\n"
       "                                          \"persönlichen Kennwörter ließen sich \"\n"
       "                                          f\"nicht entfernen: {e}\"}, status_code=500)",
       "            _n = 0")]),
    # 2026-11-18: SAP/VEMAS entfernen beim Umschalten NUR die Kennwoerter
    ("SAP/VEMAS: beim Umschalten wieder ALLE Zugaenge geloescht", "biss", "main",
     [("            _n = _sapacc.kennwoerter_entfernen()",
       "            _n = _sapacc.kennwoerter_entfernen()\n"
       "            if umschalten:\n                _sapacc.alle_entfernen()")]),
    ("SAP/VEMAS: Kennwoerter beim Umschalten nicht entfernt", "biss", "main",
     [("            _n = _sapacc.kennwoerter_entfernen()", "            _n = 0")]),
    # Mess-Sabotagen: die Attrappe spiegelt das Original nicht mehr → Exit 2.
    ("config.save_skill_state merged nicht mehr", "abbruch", "config",
     [("        self._skill_states[name].update(state)",
       "        self._skill_states[name] = dict(state)")]),
    ("GEHEIMFELDER in sap_accounts verschwunden", "abbruch", "sap",
     [("GEHEIMFELDER = (\"password\", \"bearer_token\", \"hana_password\", \"rfc_password\")",
       "GEHEIMFELDER_ALT = (\"password\",)")]),
]


def lauf(umgebung: dict) -> tuple:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **umgebung)
    r = subprocess.run([sys.executable, str(WAECHTER)], cwd=str(ROOT), env=env,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None), r.stdout + r.stderr


def main() -> int:
    nicht_gedeckt = {p[2] for p in PROBEN} - set(DATEIEN)
    if nicht_gedeckt:
        print(f"ABBRUCH: Proben auf unbekannte Dateien: {nicht_gedeckt}")
        return 2
    code, fails, aus = lauf({})
    if code != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, FAIL {fails})")
        print(aus[-3000:])
        return 2
    print("Basislauf gruen.\n")
    schlecht = 0
    with tempfile.TemporaryDirectory(prefix="gegen_sknach_") as tmp:
        for i, (name, erwartung, datei, ersetzungen) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            fehler = ""
            for alt, neu in ersetzungen:
                n = text.count(alt)
                if n != 1:
                    fehler = f"Anker {n}x gefunden (erwartet 1)"
                    break
                text = text.replace(alt, neu)
            if fehler:
                print(f"  ??  {i:2d} {name} – {fehler}")
                schlecht += 1
                continue
            ziel = Path(tmp) / f"probe{i}_{quelle.name}"
            ziel.write_text(text, encoding="utf-8")
            code, fails, aus = lauf({var: str(ziel)})
            if erwartung == "biss":
                gut = code == 1 and bool(fails)
            else:
                gut = code == 2
            if gut:
                print(f"  {'BEISST' if erwartung == 'biss' else 'ABBRUCH'} {i:2d} {name}"
                      f" ({fails} FAIL, Exit {code})")
            else:
                schlecht += 1
                print(f"  STUMM  {i:2d} {name} (Exit {code}, FAIL {fails}, "
                      f"erwartet {erwartung})")
    print(f"\nErgebnis: {len(PROBEN) - schlecht}/{len(PROBEN)} Proben wie erwartet")
    return 1 if schlecht else 0


if __name__ == "__main__":
    sys.exit(main())
