#!/usr/bin/env python3
"""Gegenproben zu ``tests/test_google_geheimnisse.py``.

Jede Probe nimmt GENAU EINE der vier Schranken weg, die
``data/google_auth`` schuetzen, und misst, ob der Waechter das meldet. Ein
Waechter, dessen Zusagen auch ohne den Fix gruen bleiben, ist kein Beweis,
sondern ein Testmangel (Register).

ZWEI EIGENSCHAFTEN, uebernommen von ``gegen_jira_sandbox.py``:

* **Es wird KEINE Datei gepatcht.** Sabotiert wird im Speicher:
  ``backend.sandbox`` wird vorab importiert, die Schranke entfernt und das
  Modul ueber ``sys.modules`` an den Waechter gegeben, der per ``runpy`` im
  SELBEN Prozess laeuft. Damit bleibt nach einem ``kill -9`` kein Rueckstand
  im Arbeitsbaum.
* **Gemessen wird EXIT-CODE und Bilanzzeile.** Ein Lauf ohne Bilanz ist von
  "bestanden" nicht zu unterscheiden, und ein Exit 1 allein koennte auch ein
  Absturz sein - deshalb muss die GEMEINTE FAIL-Zeile dabei sein.

UNTERSCHIED zum jira-Vorbild, bewusst: dort wird "genau eine FAIL mehr als die
Basis" verlangt. Hier waere das falsch. Gesperrt ist ein VERZEICHNIS, und die
Sperre wirkt an mehreren Stellen zugleich (Dateiwerkzeug, Angriffsindiz,
Begruendung) - eine Sabotage an ``_APP_DENY_REL`` muss also mehrere Zusagen
reissen. Verlangt wird daher: Exit 1, mindestens eine FAIL, und die GEMEINTE
Zeile ist darunter.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_google_geheimnisse.py"
VERZ = "data/google_auth"
DATEI = VERZ + "/gog_client_secret.json"

# (Name, Sabotage-Code, erwartete FAIL-Zeile)
PROBEN = [
    ("_APP_DENY_REL (Dateiwerkzeuge + Angriffsindiz)",
     "sb._APP_DENY_REL = tuple(x for x in sb._APP_DENY_REL if x != V)",
     "gesperrt: das Verzeichnis data/google_auth selbst"),
    ("PRIVATE_DIRS (Verzeichnis-Rechte 0750)",
     "sb.PRIVATE_DIRS = tuple(x for x in sb.PRIVATE_DIRS if x != V)",
     "Verzeichnis data/google_auth auf 0750"),
    ("PRIVATE_FILES_STRENG (Datei-Rechte 0600)",
     "sb.PRIVATE_FILES_STRENG = tuple(x for x in sb.PRIVATE_FILES_STRENG "
     "if not x.startswith(V))",
     "gog_client_secret.json auf 0600"),
    ("SHELL_SECRET_PATHS (Shell-Sperre)",
     "sb.SHELL_SECRET_PATHS = __import__('re').compile("
     "sb.SHELL_SECRET_PATHS.pattern.replace("
     "r'gog_client_secret\\.json\\b|/google_auth\\b|', ''))",
     "gesperrt: cd data/google_auth && cat gog_client_secret.json"),
]

VORLADER = '''
import runpy, sys
sys.path.insert(0, {root!r})
V, D = {verz!r}, {datei!r}
import backend.sandbox as sb
# Positivkontrolle: VOR der Sabotage sind alle vier Schranken da. Greift eine
# Sabotage ins Leere, kaeme der FAIL aus einem anderen Grund.
vorher = (V in sb._APP_DENY_REL,
          V in sb.PRIVATE_DIRS,
          any(x.startswith(V) for x in sb.PRIVATE_FILES_STRENG),
          bool(sb.SHELL_SECRET_PATHS.search("/" + V.split("/")[-1])))
if not all(vorher):
    print("PROBE-ABBRUCH: Schutz schon vorher unvollstaendig %r" % (vorher,))
    sys.exit(2)
{sabotage}
nachher = (V in sb._APP_DENY_REL,
           V in sb.PRIVATE_DIRS,
           any(x.startswith(V) for x in sb.PRIVATE_FILES_STRENG),
           bool(sb.SHELL_SECRET_PATHS.search("/" + V.split("/")[-1])))
if nachher == vorher:
    print("PROBE-ABBRUCH: Sabotage hat nichts veraendert")
    sys.exit(2)
sys.argv = [{waechter!r}]
runpy.run_path({waechter!r}, run_name="__main__")
'''


def lauf(sabotage: str) -> tuple[int, str]:
    code = VORLADER.format(root=str(ROOT), verz=VERZ, datei=DATEI,
                           sabotage=sabotage, waechter=str(WAECHTER))
    # Kein `python3 -c` mit verschachtelten Anfuehrungszeichen (Register):
    # der Code geht ueber stdin.
    p = subprocess.run([sys.executable, "-"], input=code, text=True,
                       capture_output=True, cwd=str(ROOT), timeout=600)
    return p.returncode, p.stdout + p.stderr


def bilanz(text: str):
    m = re.search(r"(\d+) OK, (\d+) FAIL", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


print("\033[1mBasislauf: der Waechter ist ohne Sabotage gruen\033[0m")
r0 = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                    text=True, cwd=str(ROOT), timeout=600)
b0 = bilanz(r0.stdout + r0.stderr)
if b0 is None:
    print("ABBRUCH: keine Bilanzzeile im Basislauf - 'nicht gelaufen' waere "
          "von 'bestanden' nicht zu unterscheiden")
    sys.exit(2)
if b0[1] or r0.returncode != 0:
    print(f"ABBRUCH: Basis ist NICHT gruen ({b0[0]} OK, {b0[1]} FAIL, "
          f"exit {r0.returncode}) - ohne gruene Basis ist keine Gegenprobe deutbar")
    sys.exit(2)
print(f"  \033[32m+\033[0m {b0[0]} OK, {b0[1]} FAIL, exit 0")

print("\n\033[1mProben\033[0m")
beissen, stumm = 0, []
for name, sabotage, erwartet in PROBEN:
    rc, text = lauf(sabotage)
    b = bilanz(text)
    if "PROBE-ABBRUCH" in text or b is None:
        grund = next((z for z in text.splitlines() if "PROBE-ABBRUCH" in z),
                     "keine Bilanzzeile")
        print(f"  \033[33m!\033[0m {name}: Probe unbrauchbar - {grund}")
        stumm.append(name + " (unbrauchbar)")
        continue
    gemeint = any(z.strip().startswith("FAIL") and erwartet in z
                  for z in text.splitlines())
    if rc == 1 and b[1] > 0 and gemeint:
        beissen += 1
        print(f"  \033[32m+\033[0m {name}: {b[1]} FAIL, exit 1, gemeinte Zeile dabei")
    else:
        stumm.append(name)
        print(f"  \033[31m-\033[0m {name}: exit {rc}, {b[1]} FAIL, "
              f"gemeinte Zeile dabei: {gemeint}")

print(f"\n{beissen} von {len(PROBEN)} Proben beissen")
if stumm:
    print("STUMM: " + ", ".join(stumm))
sys.exit(1 if stumm else 0)
