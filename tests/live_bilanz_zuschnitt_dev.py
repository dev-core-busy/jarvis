#!/usr/bin/env python3
"""Zeigt die Prompt-Bilanz nach dem Buendel-Zuschnitt noch die WAHRHEIT?

⚠ Die Gefahr: `prompt_bilanz` mass `_base_system_prompt()` und `_llm_tools` -
beide haengen seit dem Zuschnitt am LAUFENDEN Auftrag. Nach einem Bild-Auftrag
saehe der Administrator die Zahlen dieses Laufs statt der Obergrenze, ohne dass
die Anzeige es sagt.
"""
import sys
sys.path.insert(0, "/opt/jarvis")
from backend.config import config
from backend import agent as _ag, wissen_aufraeumen as _wa

OK = FAIL = 0
def check(n, b):
    global OK, FAIL
    print(("  \033[32m✓\033[0m " if b else "  \033[31m✗\033[0m ") + n); 
    globals().__setitem__("OK", OK + (1 if b else 0))
    globals().__setitem__("FAIL", FAIL + (0 if b else 1))

# Hauptagenten erzeugen und einen Bild-Auftrag "hinterlassen" - genau die Lage,
# in der die alte Fassung falsch gemessen haette.
# ⚠ prompt_bilanz sucht den Hauptagenten ueber backend.main.agent_manager -
# genau diesen Weg muss der Test herstellen, sonst misst er einen anderen Agenten
# als die Funktion (Register: den Weg nehmen, den der Produktivcode nimmt).
import backend.main as _hm
# Im Testprozess laeuft der Startup-Hook nicht, also ist agent_manager None.
# Der Manager wird hier erzeugt und DORT hinterlegt, wo prompt_bilanz ihn sucht -
# sonst misst der Test einen anderen Agenten als die Funktion.
mgr = _hm.agent_manager or _ag.AgentManager()
_hm.agent_manager = mgr
a = mgr.get_or_create_main()
config.WERKZEUG_BUENDEL = True
a._buendel_voll = False
a._current_task = "generiere ein kleines Bild einer gruenen Kuh"

zug_prompt = len(a._base_system_prompt())
zug_tools = len(a._llm_tools)
voll_prompt = len(a._base_system_prompt(voll=True))
voll_tools = len(a.werkzeuge_fuer_anzeige())
print(f"\n  Lauf-Zuschnitt : {zug_prompt:6d} Z. Prompt, {zug_tools:3d} Werkzeuge")
print(f"  Volle Messung  : {voll_prompt:6d} Z. Prompt, {voll_tools:3d} Werkzeuge")
check("der Zuschnitt wirkt ueberhaupt (sonst misst der Test nichts)",
      zug_prompt < voll_prompt and zug_tools < voll_tools)

b = _wa.prompt_bilanz()
print(f"\n  Bilanz: basis={b.get('basis')} werkzeuge={b.get('werkzeuge')} "
      f"anzahl={b.get('werkzeuge_anzahl')} zuschnitt_aktiv={b.get('zuschnitt_aktiv')}")
check("⚠ die Bilanz zeigt den VOLLEN Prompt, nicht den des letzten Laufs",
      b.get("basis") == voll_prompt)
check("⚠ und den VOLLEN Werkzeugsatz",
      (b.get("werkzeuge_anzahl") or 0) == voll_tools)
check("sie weist aus, dass ein Zuschnitt aktiv ist",
      b.get("zuschnitt_aktiv") is True)
check("die uebrigen Werte sind da (Anweisungen, Summe)",
      isinstance(b.get("anweisungen"), int) and isinstance(b.get("summe"), int))
check("⚠ die Messung hat den Agenten NICHT veraendert",
      a._current_task == "generiere ein kleines Bild einer gruenen Kuh"
      and getattr(a, "_buendel_voll", False) is False)
check("⚠ und der Zuschnitt wirkt danach unveraendert weiter",
      len(a._llm_tools) == zug_tools)

config.WERKZEUG_BUENDEL = False
b2 = _wa.prompt_bilanz()
check("ohne Zuschnitt wird kein Zuschnitt behauptet", not b2.get("zuschnitt_aktiv"))
check("und die Zahl bleibt dieselbe (es ist ja dieselbe Obergrenze)",
      b2.get("basis") == b.get("basis"))
print(f"\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)
