#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_jira_nur_lesen.py?

Sabotierte KOPIEN in einem Wegwerf-Verzeichnis, uebergeben ueber JI_CLIENT /
JI_ACCOUNTS / JI_MAIN / JI_SETTINGS / JI_SKILL – die echten Dateien werden nie
angefasst. Vorher ein gruener Basislauf; eine Probe "beisst" nur mit Exit 1 UND
mindestens einem FAIL (Exit 2 zaehlt nicht).

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
# Drei Pruefstaende: Backend (Python) und die beiden Oberflaechen (jsdom).
WAECHTER = [
    [sys.executable, str(HIER / "test_jira_nur_lesen.py")],
    ["node", str(HIER / "test_jira_persoenlich_ui.js")],
    ["node", str(HIER / "test_jira_addon_ui.js")],
]
DATEIEN = {
    "client": (ROOT / "backend" / "jira_client.py", "JI_CLIENT"),
    "konten": (ROOT / "backend" / "jira_accounts.py", "JI_ACCOUNTS"),
    "main": (ROOT / "backend" / "main.py", "JI_MAIN"),
    "settings": (ROOT / "frontend" / "settings.html", "JI_SETTINGS"),
    "skill": (ROOT / "skills" / "jira" / "main.py", "JI_SKILL"),
    "jirajs": (ROOT / "frontend" / "js" / "jira.js", "JIRA_JS"),
    "addonjs": (ROOT / "frontend" / "js" / "jira_addon.js", "JIRA_ADDON_JS"),
    "assist": (ROOT / "backend" / "jira_assist.py", "JI_ASSIST"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("gemeinsamer Zugang darf POST", "client",
     'if (method or "").upper() != "GET" and not self.schreiben:',
     'if (method or "").upper() not in ("GET", "POST") and not self.schreiben:'),
    ("Vorgabe des Clients ist Schreiben", "client",
     "def __init__(self, cfg: dict | None = None, *, schreiben: bool = False):",
     "def __init__(self, cfg: dict | None = None, *, schreiben: bool = True):"),
    ("persoenlicher Zugang ohne Schreibrecht", "konten",
     '{"base_url": basis, "api_token": token}, schreiben=True)',
     '{"base_url": basis, "api_token": token})'),
    ("Schalter in der Aufloesung ignoriert", "konten",
     '    if not persoenlich_erlaubt():\n        # Ein Rest in der Datei',
     '    if False:\n        # Ein Rest in der Datei'),
    ("Schalter aus, Speichern trotzdem moeglich", "konten",
     '        raise JiraKontoFehler("Fuer diese Kennung kann kein Jira-Zugang hinterlegt werden.")\n'
     '    if not persoenlich_erlaubt():\n        raise JiraKontoFehler(ABGESCHALTET_TEXT)\n',
     '        raise JiraKontoFehler("Fuer diese Kennung kann kein Jira-Zugang hinterlegt werden.")\n'),
    ("Schalter aus, Verbindungstest trotzdem moeglich", "konten",
     '    if not persoenlich_erlaubt():\n        raise JiraKontoFehler(ABGESCHALTET_TEXT)\n    un = norm_user(user)\n',
     '    un = norm_user(user)\n'),
    ("alle_entfernen loescht nichts", "konten",
     "    if n:\n        _speichern({})\n", ""),
    ("fehlendes Feld gilt als abgeschaltet", "konten",
     "    return cfg.get(PERSOENLICH_SCHALTER) is not False",
     "    return cfg.get(PERSOENLICH_SCHALTER) is True"),
    ("Abschalten loescht keine Token", "main",
     "            _nj = _jacc.alle_entfernen()\n", "            _nj = 0\n"),
    ("Admin-Liste ohne Schalter", "main",
     '                         "persoenlich_erlaubt": jira_accounts.persoenlich_erlaubt()})',
     '                         })'),
    ("Nur-Lesen abschaltbar", "settings",
     '<input type="checkbox" id="jira-read-only" checked disabled>',
     '<input type="checkbox" id="jira-read-only" checked>'),
    ("Abschalten ohne Rueckfrage", "jirajs",
     "            if (!body.persoenliche_zugaenge && Manager._persoenlichGespeichert) {",
     "            if (false) {"),
    ("Container bleibt nach dem Abschalten sichtbar", "jirajs",
     "            if (sect) sect.style.display = erlaubt ? '' : 'none';",
     "            if (sect) sect.style.display = '';"),
    ("Schalter wird nicht mitgespeichert", "jirajs",
     "                persoenliche_zugaenge: $('jira-persoenlich') ? $('jira-persoenlich').checked : true\n",
     "                persoenliche_zugaenge: true\n"),
    ("Mein Jira-Zugang bleibt trotz Abschalten sichtbar", "addonjs",
     "        if (sect) sect.style.display = (a.persoenlich_erlaubt === false) ? 'none' : '';",
     "        if (sect) sect.style.display = '';"),
    # Punkt f: Browser-Erweiterung nur ueber den gemeinsamen Lesezugang
    ("aufloesen ignoriert nur_gemeinsam", "konten",
     "    if nur_gemeinsam.get():\n", "    if False:\n"),
    ("Erweiterung laedt Tickets mit dem eigenen Token", "assist",
     "        c = jira_accounts.sammel_client()\n", "        c = jira_accounts.aufloesen(user)[\"client\"]\n"),
    ("Assistentenlauf ohne nur_gemeinsam", "assist",
     "    _ng = _jacc.nur_gemeinsam.set(True)\n", "    _ng = _jacc.nur_gemeinsam.set(False)\n"),
    ("nur_gemeinsam bleibt nach dem Lauf stehen", "assist",
     "    finally:\n        _jacc.nur_gemeinsam.reset(_ng)\n", ""),
    ("health-Route fragt den eigenen Zugang", "main",
     "        konfiguriert = bool(jira_accounts.sammel_client().configured)",
     "        konfiguriert = bool(jira_accounts.aufloesen(user)[\"client\"].configured)"),
    ("Skill baut einen schreibenden Client", "skill",
     "        return JiraClient()\n", "        return JiraClient(schreiben=True)\n"),
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
