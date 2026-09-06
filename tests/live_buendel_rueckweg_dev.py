#!/usr/bin/env python3
"""ECHTER Haertefall: das noetige Werkzeug ist NACHWEISLICH nicht im Angebot.

Der erste Versuch war keiner - der Auftragstext traf beide Buendel, das
Werkzeug war also da. Hier wird der Zuschnitt DETERMINISTISCH falsch gesetzt
(Buendel 'bild' fuer eine Excel-Aufgabe), damit die Lage wirklich eintritt.
Gemessen wird am Audit-Log UND am Antworttext.
"""
import asyncio, sys, time
sys.path.insert(0, "/opt/jarvis")
from backend.config import config
from backend import agent as _ag, audit_log, werkzeug_buendel as wb

OK = FAIL = 0
def check(n, b):
    global OK, FAIL
    print(("  \033[32m✓\033[0m " if b else "  \033[31m✗\033[0m ") + n)
    if b: OK += 1
    else: FAIL += 1
def tools_seit(t0):
    try:
        return [e.get("tool") for e in audit_log.read_log(limit=300)
                if float(e.get("ts") or 0) >= t0]
    except Exception: return []

AUFTRAG = ("Lege eine Excel-Arbeitsmappe an mit einer Spalte 'Test' und "
           "den Werten 1, 2 und 3.")

async def lauf(auftrag, themen_fest=None):
    a = _ag.JarvisAgent()
    if themen_fest is not None:
        # Zuschnitt hart auf ein FALSCHES Buendel zwingen.
        orig = wb.themen
        wb.themen = lambda t, _f=themen_fest: set(_f)
    t0 = time.time()
    try:
        with a.actor_scope("jarvis", True):
            txt = await a.run_task_headless(
                auftrag, actor={"user": "jarvis", "privileged": True})
    finally:
        if themen_fest is not None:
            wb.themen = orig
    return txt or "", tools_seit(t0), time.time() - t0

config.WERKZEUG_BUENDEL = True
print("\n\033[1mHaertefall: Excel-Aufgabe, aber nur das Buendel 'bild'\033[0m")
txt, tools, dt = asyncio.run(lauf(AUFTRAG, themen_fest={"bild"}))
print(f"  ({dt:.1f}s) Werkzeuge: {tools}")
print(f"  Antwort ({len(txt)} Z.): {txt[:300]!r}")
check("⚠ der Lauf endet nicht wortlos", len(txt.strip()) > 10)
rueck = "werkzeuge_anfordern" in tools
geloest = any("office" in (t or "") or "xlsx" in (t or "") or "shell" in (t or "")
              for t in tools)
check("⚠ die Aufgabe wurde geloest ODER der Rueckweg wurde genommen",
      geloest or rueck)
if rueck:
    check("der Rueckweg fuehrte danach zum Ziel", geloest)
else:
    print("    (kein Rueckweg genommen - dann muss der KERN gereicht haben)")
# Das Modell darf NICHT ausweichen und dabei etwas Falsches behaupten.
schlecht = any(w in txt.lower() for w in
               ("nicht installiert", "steht nicht zur verfügung", "kann ich nicht"))
check("⚠ keine erfundene Absage im Antworttext", not schlecht or geloest or rueck)

config.WERKZEUG_BUENDEL = False
print(f"\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
sys.exit(1 if FAIL else 0)
