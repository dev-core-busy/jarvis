#!/usr/bin/env python3
"""LIVE auf DEV: was spart der Zuschnitt am ECHTEN Agenten - und bricht er etwas?

Gemessen am laufenden Werkzeugkasten, nicht an Attrappen. Der Schalter wird
nur im PROZESS gesetzt (config-Attribut), nie in der settings.json - der
Dienst bleibt unberuehrt.
"""
import json, sys, time
sys.path.insert(0, "/opt/jarvis")
from backend.config import config
from backend.agent import JarvisAgent

OK = FAIL = 0
def check(n, b):
    global OK, FAIL
    print(("  \033[32m✓\033[0m " if b else "  \033[31m✗\033[0m ") + n)
    if b: OK += 1
    else: FAIL += 1

def schema_len(tools):
    return len(json.dumps([{"type": "function", "function": {
        "name": t.name, "description": getattr(t, "description", "") or "",
        "parameters": t.parameters_schema()}} for t in tools], ensure_ascii=False))

a = JarvisAgent()
config.WERKZEUG_BUENDEL = False
a._current_task = "generiere ein kleines fotorealistisches Bild einer gruenen Kuh"
voll = a._llm_tools
n_voll, z_voll = len(voll), schema_len(voll)
print(f"\n\033[1mOhne Zuschnitt\033[0m: {n_voll} Werkzeuge, {z_voll} Zeichen Schemata")
# ⚠ AUSGESCHALTET wird werkzeuge_anfordern NICHT angeboten - ein Werkzeug ohne
# Wirkung verleitet nur zu Fehlversuchen, und das Angebot muss bei
# ausgeschaltetem Feature UNVERAENDERT bleiben (drei Bestandstests fielen sonst
# um). Im KASTEN liegt es trotzdem, damit es beim Einschalten sofort da ist.
check("⚠ ausgeschaltet wird der Rueckweg NICHT angeboten",
      not any(t.name == "werkzeuge_anfordern" for t in voll))
check("er liegt aber im Kasten (sofort da beim Einschalten)",
      any(getattr(t, "name", "") == "werkzeuge_anfordern" for t in a._tool_instances))
KASTEN = {getattr(t, "name", "") for t in a._tool_instances}

config.WERKZEUG_BUENDEL = True
faelle = {
    "generiere ein kleines fotorealistisches Bild einer gruenen Kuh": "bild",
    "erstelle eine PowerPoint mit 5 Folien zum Thema Netzwerksicherheit": "dokument",
    "lies das Jira-Ticket NXCSO-28878 und fasse es zusammen": "fach",
    "wie funktioniert der LDT-Import in Medistar?": "(kein Thema)",
}
print(f"\n\033[1mMit Zuschnitt\033[0m")
for auftrag, erwartet in faelle.items():
    a._buendel_voll = False
    a._current_task = auftrag
    g = a._llm_tools
    z = schema_len(g)
    spar = (1 - z / z_voll) * 100
    print(f"  {erwartet:12s} {len(g):3d} Werkzeuge, {z:6d} Zeichen  ({spar:+5.1f} %)  "
          f"{auftrag[:44]}")

# ── Die Zusagen ──────────────────────────────────────────────────────────
a._buendel_voll = False
a._current_task = "generiere ein kleines fotorealistisches Bild einer gruenen Kuh"
bild = a._llm_tools
namen = {t.name for t in bild}
check("beim Bild-Auftrag ist generate_image dabei", "generate_image" in namen)
check("⚠ und windows_desktop NICHT (genau die Frage des Betreibers)",
      "windows_desktop" not in namen)
check("⚠ und office_create_powerpoint NICHT", "office_create_powerpoint" not in namen)
check("der Kern ist da (knowledge_search, memory_manage, shell_execute)",
      {"knowledge_search", "memory_manage", "shell_execute"} <= namen)
check("der Rueckweg ist da", "werkzeuge_anfordern" in namen)
check("es wurde wirklich gekuerzt", len(bild) < n_voll)

# Nur wegnehmen, nie hinzufuegen - Referenz ist der KASTEN, nicht die
# ausgeschaltete Liste (die traegt den Rueckweg bewusst nicht).
check("⚠ kein Werkzeug kam hinzu", namen <= KASTEN)

# Rueckweg wirkt: voller Satz PLUS der Rueckweg selbst
a._buendel_voll = True
nach = {t.name for t in a._llm_tools}
check("⚠ nach werkzeuge_anfordern steht wieder der volle Satz",
      {t.name for t in voll} <= nach)
a._buendel_voll = False

# Schalter aus = exakt wie vorher
config.WERKZEUG_BUENDEL = False
check("⚠ ausgeschaltet ist die Liste BYTE-GLEICH zu vorher",
      [t.name for t in a._llm_tools] == [t.name for t in voll])
config.WERKZEUG_BUENDEL = True

print(f"\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)
