#!/usr/bin/env python3
"""Gegenprobe zu test_autonomie_aussage.py: beisst der Waechter?

Sabotiert wird eine KOPIE der betroffenen Dateien (JARVIS_TEST_WURZEL) – der
Arbeitsbaum bleibt unberuehrt, ein abgebrochener Lauf hinterlaesst also nichts.
Zaehlt nur Exit 1 mit Bilanzzeile als Biss; Exit 2 ist "nicht gemessen".

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

R = Path(__file__).resolve().parent.parent
WAECHTER = R / "tests" / "test_autonomie_aussage.py"
DATEIEN = ["backend/agent.py", "backend/tools/subagent.py", "frontend/js/app.js", "frontend/js/chat.js",
           "frontend/manifest.json", "data/instructions_default/identity.md",
           "data/instructions_default/agents.md", "data/instructions_default/tools.md",
           "data/instructions_default/projektinfo.md"]
# (Name, Datei, alt, neu)
PROBEN = [
    ("Basis-Prompt nennt sich wieder autonom", "backend/agent.py",
     "Du bist Jarvis, ein KI-Chatbot mit enormem Funktionsumfang", "Du bist Jarvis, ein autonomer KI-Agent"),
    ("Anweisung gegen Erlaubnis-Fragen entfaellt", "backend/agent.py",
     "SOFORT aus, OHNE den Benutzer um Erlaubnis zu fragen.", "SOFORT aus."),
    ("eigene Aufgaben nicht mehr ausgeschlossen", "backend/agent.py",
     "beginnst du NICHT:", "beginnst du gern:"),
    ("Sub-Agent wieder autonom", "backend/agent.py",
     "VOLLSTAENDIG und OHNE RUECKFRAGEN aus.", "VOLLSTAENDIG AUTONOM aus."),
    ("Autonomie-Absatz unbedingt", "backend/agent.py",
     'if self._werkzeug_nutzbar("queue_next"):', "if True:"),
    ("Autonomie-Absatz an falschem Werkzeug", "backend/agent.py",
     'if self._werkzeug_nutzbar("queue_next"):', 'if self._werkzeug_nutzbar("memory_manage"):'),
    ("Vorgabe identity.md wieder autonom", "data/instructions_default/identity.md",
     "ein KI-Chatbot mit enormem Funktionsumfang", "ein autonomer KI-Agent"),
    ("Vorgabe agents.md wieder Autonomieprinzip", "data/instructions_default/agents.md",
     "## Ausführungsprinzip", "## Autonomieprinzip"),
    ("Werkzeugbeschreibung wieder autonom", "backend/tools/subagent.py",
     "OHNE RUECKFRAGEN ab und", "VOLLSTAENDIG AUTONOM und"),
    ("Sprachprobe im Chat wieder autonom", "frontend/js/chat.js",
     "dein KI-Assistent.", "dein autonomer KI-Assistent."),
]

fehlend = {p[1] for p in PROBEN} - set(DATEIEN)
if fehlend:
    print("ABBRUCH: Probe faesst nicht kopierte Datei an:", fehlend)
    sys.exit(2)


def lauf(wurzel):
    env = dict(os.environ, JARVIS_TEST_WURZEL=str(wurzel), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(WAECHTER)], env=env, capture_output=True, text=True, timeout=120)


with tempfile.TemporaryDirectory() as tmp:
    w = Path(tmp)
    for rel in DATEIEN:
        (w / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(R / rel, w / rel)
    basis = lauf(w)
    if basis.returncode != 0 or "Ergebnis:" not in basis.stdout:
        print("ABBRUCH: Basislauf nicht gruen, keine Gegenprobe deutbar\n" + basis.stdout + basis.stderr)
        sys.exit(2)
    print("Basislauf:", basis.stdout.strip().splitlines()[-1])
    stumm = 0
    for name, rel, alt, neu in PROBEN:
        orig = (R / rel).read_text(encoding="utf-8")
        if orig.count(alt) != 1:
            print("ABBRUCH: Anker nicht eindeutig:", name)
            sys.exit(2)
        (w / rel).write_text(orig.replace(alt, neu), encoding="utf-8")
        r = lauf(w)
        (w / rel).write_text(orig, encoding="utf-8")
        fails = r.stdout.count("FAIL:")
        biss = r.returncode == 1 and "Ergebnis:" in r.stdout and fails > 0
        print("%s  %-46s %d FAIL (Exit %d)" % ("beisst" if biss else "STUMM ", name, fails, r.returncode))
        stumm += 0 if biss else 1
print("Gegenprobe: %d/%d beissen" % (len(PROBEN) - stumm, len(PROBEN)))
sys.exit(1 if stumm else 0)
