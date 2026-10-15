#!/usr/bin/env python3
"""Gegenproben zum Abschnitt "Persistenz-Substrat" in test_jira_assist.py.

Geprueft werden die drei Schranken, die `data/jira_vorlagen.json` vor einem
`cat` in der Sandbox schuetzen (`_APP_DENY_REL`, `PRIVATE_FILES`,
`SHELL_SECRET_PATHS`). Jede Probe nimmt GENAU EINE davon weg und misst, ob
der Waechter das meldet.

Anlass (2026-10-03): der Waechter meldete an dieser Stelle einen DAUERHAFTEN
FAIL, den es im Code nicht gab – `SANDBOX.find("PRIVATE_FILES")` traf
`PRIVATE_FILES_STRENG`, und von dort lief ein festes Fenster von 2600
Zeichen, waehrend der echte Eintrag 5228 Zeichen dahinter steht. Zugleich
fehlte dem Waechter das abschliessende `sys.exit`: er endete mit Exit 0 und
war damit in jedem Sammellauf stumm. Beides ist behoben; diese Datei haelt
die Zusage fest.

ZWEI EIGENSCHAFTEN DIESER PROBE, beide aus dem Register:

* **Sie patcht KEINE Datei.** Sabotiert wird im Speicher: `backend.sandbox`
  wird vorab importiert, die Schranke entfernt und das Modul ueber
  `sys.modules` an den Waechter gegeben. Damit gibt es keinen Rueckstand im
  Arbeitsbaum, auch nicht nach einem `kill -9` – die ganze Mechanik aus
  Sicherung, Laufmarke und md5-Vergleich entfaellt, weil es nichts
  wiederherzustellen gibt.
* **Gemessen wird EXIT-CODE und Bilanzzeile.** Ein Lauf ohne Bilanz ist von
  "bestanden" nicht zu unterscheiden; und ein Exit 1 allein koennte auch ein
  Absturz sein, deshalb muss die erwartete FAIL-Zeile dabei sein.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_jira_assist.py"
PFAD = "data/jira_vorlagen.json"

# (Name, Sabotage-Code, erwartete FAIL-Zeile)
PROBEN = [
    ("_APP_DENY_REL",
     "sb._APP_DENY_REL = tuple(x for x in sb._APP_DENY_REL if x != P)",
     "steht in _APP_DENY_REL"),
    ("PRIVATE_FILES",
     "sb.PRIVATE_FILES = tuple(x for x in sb.PRIVATE_FILES if x != P)",
     "steht in PRIVATE_FILES"),
    ("SHELL_SECRET_PATHS",
     "sb.SHELL_SECRET_PATHS = __import__('re').compile("
     "sb.SHELL_SECRET_PATHS.pattern.replace(r'jira_vorlagen\\.json\\b|', ''))",
     "wird von SHELL_SECRET_PATHS getroffen"),
]

VORLADER = '''
import runpy, sys
sys.path.insert(0, {root!r})
P = {pfad!r}
import backend.sandbox as sb
# Positivkontrolle: der Schutz ist VOR der Sabotage vollstaendig da. Greift
# eine Sabotage ins Leere, kaeme der FAIL aus einem anderen Grund.
vorher = (P in sb._APP_DENY_REL, P in sb.PRIVATE_FILES,
          bool(sb.SHELL_SECRET_PATHS.search(P)))
if not all(vorher):
    print("PROBE-ABBRUCH: Schutz schon vorher unvollstaendig %r" % (vorher,))
    sys.exit(2)
{sabotage}
nachher = (P in sb._APP_DENY_REL, P in sb.PRIVATE_FILES,
           bool(sb.SHELL_SECRET_PATHS.search(P)))
if nachher == vorher:
    print("PROBE-ABBRUCH: Sabotage hat nichts veraendert")
    sys.exit(2)
sys.argv = [{waechter!r}]
runpy.run_path({waechter!r}, run_name="__main__")
'''


def lauf(sabotage: str) -> tuple[int, str]:
    code = VORLADER.format(root=str(ROOT), pfad=PFAD, sabotage=sabotage,
                           waechter=str(WAECHTER))
    # Kein `python3 -c` mit verschachtelten Anfuehrungszeichen (Register):
    # der Code geht ueber stdin.
    p = subprocess.run([sys.executable, "-"], input=code, text=True,
                       capture_output=True, cwd=str(ROOT), timeout=600)
    return p.returncode, p.stdout + p.stderr


def bilanz(text: str):
    m = re.search(r"(\d+) OK, (\d+) FAIL", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


print("\033[1mBasislauf: der Waechter ist ohne Sabotage gruen\033[0m")
rc0 = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                     text=True, cwd=str(ROOT), timeout=600)
b0 = bilanz(rc0.stdout + rc0.stderr)
if b0 is None:
    print("ABBRUCH: keine Bilanzzeile im Basislauf – 'nicht gelaufen' waere "
          "von 'bestanden' nicht zu unterscheiden")
    sys.exit(2)
if b0[1] or rc0.returncode != 0:
    print(f"ABBRUCH: Basis ist NICHT gruen ({b0[0]} OK, {b0[1]} FAIL, "
          f"exit {rc0.returncode}) – ohne gruene Basis ist keine Gegenprobe "
          f"deutbar")
    sys.exit(2)
print(f"  \033[32m✓\033[0m {b0[0]} OK, {b0[1]} FAIL, exit 0")

print("\n\033[1mProben\033[0m")
beissen, stumm = 0, []
for name, sabotage, erwartet in PROBEN:
    rc, text = lauf(sabotage)
    b = bilanz(text)
    if "PROBE-ABBRUCH" in text or b is None:
        grund = next((z for z in text.splitlines() if "PROBE-ABBRUCH" in z),
                     "keine Bilanzzeile")
        print(f"  \033[33m⚠\033[0m {name}: Probe unbrauchbar – {grund}")
        stumm.append(name + " (unbrauchbar)")
        continue
    # Drei Bedingungen: Exit 1, genau eine FAIL mehr als die Basis, und die
    # FAIL-Zeile ist die GEMEINTE. Ohne die dritte wuerde eine Probe, die
    # irgendwo anders etwas kaputt macht, als Erfolg zaehlen.
    getroffen = any(erwartet in z and "FAIL" in z for z in text.splitlines())
    if rc == 1 and b[1] == 1 and getroffen:
        beissen += 1
        print(f"  \033[32m✓\033[0m {name} → exit 1, {b[0]} OK, {b[1]} FAIL "
              f"({erwartet})")
    else:
        stumm.append(name)
        print(f"  \033[31m✗\033[0m {name} → BEISST NICHT (exit {rc}, "
              f"{b[0]} OK, {b[1]} FAIL, gemeinte Zeile: {getroffen})")

print(f"\n\033[1mErgebnis: {beissen}/{len(PROBEN)} Proben beissen\033[0m")
if stumm:
    print("Stumm: " + "; ".join(stumm))
print("Arbeitsbaum: unberuehrt (Sabotage nur im Speicher)")
sys.exit(1 if stumm else 0)
