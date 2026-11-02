#!/usr/bin/env python3
"""Waechter: Autonomie gibt es nur per Skill – Prompt und Texte duerfen nichts anderes sagen.

FESTLEGUNG DES BETREIBERS (2026-11-02): ohne den Skill `agent_autonomy_kit` ist
Jarvis ein Chatbot mit enormem Funktionsumfang. Der Basis-Prompt nannte ihn bis
dahin "autonomer KI-Agent" und wies ihn an, IMMER eigenstaendig zu handeln –
ganz gleich, ob der Skill an war.

ZWEI ZUSAGEN, DIE ZUSAMMENGEHOEREN:
- Ein Prompt, der nur das Wort streicht, verliert leicht die eigentliche Wirkung
  der alten Regel: dass das Modell nicht bei jedem Schritt um Erlaubnis fragt.
  Geprueft wird deshalb auch, dass genau diese Anweisung stehen bleibt.
- Der Autonomie-Absatz darf nur unter der Bedingung "queue_next ist nutzbar" in
  den Prompt kommen. `in self.tools_map` genuegt nicht (Rollenlaeufe), und ein
  Vorkommen im Quelltext sagt nichts ueber die Verzweigung – gemessen am AST.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
JARVIS_TEST_WURZEL lenkt auf eine Kopie um (Gegenprobe, patcht den Baum nicht).
"""
import ast
import os
import re
import sys
from pathlib import Path

W = Path(os.environ.get("JARVIS_TEST_WURZEL") or Path(__file__).resolve().parent.parent)
ok = fail = 0


def pruefe(text, bed):
    global ok, fail
    if bed:
        ok += 1
    else:
        fail += 1
        print("FAIL:", text)


def lies(rel):
    p = W / rel
    if not p.is_file():
        print("ABBRUCH: Datei fehlt:", rel)
        sys.exit(2)
    return p.read_text(encoding="utf-8")


baum = ast.parse(lies("backend/agent.py"))
prompts = {}
autonomie_ifs = []
autonomie_literale = 0
for k in ast.walk(baum):
    if isinstance(k, ast.Assign) and len(k.targets) == 1 and isinstance(k.targets[0], ast.Name) \
            and k.targets[0].id in ("SYSTEM_PROMPT", "SUB_AGENT_PROMPT") and isinstance(k.value, ast.Constant):
        prompts[k.targets[0].id] = k.value.value
    if isinstance(k, ast.Constant) and isinstance(k.value, str) and "Agent Autonomy Kit" in k.value:
        autonomie_literale += 1
    if isinstance(k, ast.If):
        t = k.test
        if isinstance(t, ast.Call) and isinstance(t.func, ast.Attribute) and t.func.attr == "_werkzeug_nutzbar" \
                and t.args and isinstance(t.args[0], ast.Constant) and t.args[0].value == "queue_next":
            autonomie_ifs.append(k)

# Positivkontrolle: ohne die beiden Prompts waere alles Folgende trivial wahr.
if len(prompts.get("SYSTEM_PROMPT", "")) < 5000 or len(prompts.get("SUB_AGENT_PROMPT", "")) < 200:
    print("ABBRUCH: SYSTEM_PROMPT/SUB_AGENT_PROMPT nicht gefunden")
    sys.exit(2)

RE_AUTONOM = re.compile(r"autonom", re.I)
SP, SUB = prompts["SYSTEM_PROMPT"], prompts["SUB_AGENT_PROMPT"]

pruefe("der Basis-Prompt nennt keine Autonomie", not RE_AUTONOM.search(SP))
pruefe("der Sub-Agent-Prompt nennt keine Autonomie", not RE_AUTONOM.search(SUB))
pruefe("die Auftragsregel steht im Basis-Prompt", "AUFTRAEGE AUSFUEHREN" in SP)
pruefe("kein Fragen um Erlaubnis bleibt angewiesen", "OHNE den Benutzer um Erlaubnis zu fragen" in SP)
pruefe("eigene Aufgaben ohne Auftrag sind ausgeschlossen", "beginnst du NICHT" in SP)
pruefe("der Sub-Agent arbeitet weiter ohne Rueckfragen", "OHNE RUECKFRAGEN" in SUB)

pruefe("genau eine Verzweigung auf queue_next", len(autonomie_ifs) == 1)
im_zweig = 0
for z in autonomie_ifs:
    for k in ast.walk(z):
        if isinstance(k, ast.Constant) and isinstance(k.value, str) and "Agent Autonomy Kit" in k.value:
            im_zweig += 1
pruefe("der Autonomie-Absatz steht in dieser Verzweigung", im_zweig >= 1)
pruefe("der Autonomie-Absatz steht NUR in dieser Verzweigung", im_zweig == autonomie_literale)

# Der Skill-Name selbst ist die erlaubte Nennung.
for rel in ("data/instructions_default/identity.md", "data/instructions_default/agents.md",
            "data/instructions_default/tools.md", "data/instructions_default/projektinfo.md"):
    rest = re.sub(r"Agent Autonomy Kit", "", lies(rel))
    pruefe(rel + " behauptet keine Autonomie ohne den Skill",
           not re.search(r"(?m)^.*autonom.*$", rest, re.I)
           or all("Skill" in z for z in re.findall(r"(?m)^.*autonom.*$", rest, re.I)))

pruefe("die Werkzeugbeschreibung des Sub-Agenten nennt keine Autonomie",
       not RE_AUTONOM.search(lies("backend/tools/subagent.py")))
# In der Oberflaeche ist der Reiter "Autonomie" des Skills richtig – gemeint ist nur
# die Selbstbeschreibung als autonomer Assistent, nicht jedes Vorkommen des Worts.
RE_SELBSTBILD = re.compile(r"autonom(er|ous)\s+(KI|AI)", re.I)
for rel in ("frontend/js/app.js", "frontend/js/chat.js", "frontend/manifest.json"):
    pruefe(rel + " beschreibt Jarvis nicht als autonom", not RE_SELBSTBILD.search(lies(rel)))

print("Ergebnis: %d ok, %d fehlgeschlagen" % (ok, fail))
sys.exit(1 if fail else 0)
