#!/usr/bin/env python3
"""NUR LESEN/MESSEN: WO steht der Chat-Preprompt im System-Prompt – und wirkt er?

⚠ VERAENDERT NICHTS AM BESTAND: die Probe legt eine eigene Sitzung an und
raeumt sie am Ende ab. Keine Einstellung wird umgestellt, kein Dienst neu
gestartet.

Die vorhandene Probe (`live_chat_prompt_weg_dev.py`) belegt, dass der Prompt im
System-Prompt ANKOMMT. Das ist die Mechanik, nicht die Wirkung. Gemeldet ist
aber "greift nicht" – und dafuer gibt es eine zweite, voellig andere Ursache:

  Der Abschnitt wird direkt nach `load_instructions()` angehaengt. Danach kommen
  Gedaechtnis, Werkzeug-Abschnitte, Zeit-Hinweis. Steht die Anweisung des
  Benutzers damit MITTEN in einem sechsstelligen Prompt, uebertoent sie das
  Regelwerk dahinter – genau deshalb steht `## JETZT` bewusst am ENDE (98 %).

Gemessen wird deshalb die POSITION, nicht nur die Anwesenheit.

⚠ NACHTRAG 2026-09-11 – DIE HYPOTHESE OBEN IST NUR ZUR HAELFTE RICHTIG. Ohne
Werkzeuge ist die Stelle gleichgueltig (17 von 17 Laeufen befolgen die
Anweisung, egal wo sie steht). Erst MIT den 85 Werkzeug-Schemata trennt sich
das Bild: an der alten Stelle 18 von 25, am Ende 21 von 21. Die vollstaendige
Messung steht in `lies_pp_werkzeuge_dev.py`; dieses Skript beantwortet nur
"wo steht sie und sieht der Benutzer eine Statuszeile".
"""
import asyncio
import sys

sys.path.insert(0, "/opt/jarvis")

from backend import chat_sessions as CS                            # noqa: E402
from backend import agent as A                                     # noqa: E402

BENUTZER = "jarvis"
TEXT = "Antworte ausschliesslich in Grossbuchstaben."

sess = CS.create_session(BENUTZER, "ZZ-Probe Position")
SID = sess["id"] if isinstance(sess, dict) else str(sess)
CS.save_session_preprompt(BENUTZER, SID, TEXT)
print("Probe-Sitzung: %s" % SID)

gesehen = {}


class _Halt(Exception):
    pass


class _P:
    async def generate_response(self, *a, **kw):
        gesehen["sp"] = kw.get("system_prompt") or (a[1] if len(a) > 1 else "")
        raise _Halt()


class _WS:
    def __init__(self):
        self.zeilen = []

    async def send_json(self, d, *a, **kw):
        # Die Statuszeile ist der Teil, den der BENUTZER sieht – und damit die
        # billigste Auskunft darueber, ob der Prompt greift.
        t = (d or {}).get("message") or (d or {}).get("text") or ""
        if t:
            self.zeilen.append(str(t))
        return None


try:
    A.get_provider = lambda *a, **kw: _P()
    ag = A.JarvisAgent()
    ws = _WS()
    try:
        asyncio.run(ag.run_task("Sag Hallo.", ws, username=BENUTZER, session_id=SID))
    except Exception:                                              # noqa: BLE001
        pass

    sp = gesehen.get("sp") or ""
    if not sp:
        print("ABBRUCH: kein System-Prompt eingefangen.")
        sys.exit(2)

    pos = sp.find(TEXT)
    laenge = len(sp)
    print("\n=== POSITION ===")
    print("System-Prompt gesamt: %d Zeichen (~%d Token geschaetzt)"
          % (laenge, int(laenge / 3.6)))
    if pos < 0:
        print("⚠ DIE ANWEISUNG STEHT GAR NICHT DRIN.")
    else:
        print("Anweisung beginnt bei Zeichen %d = %.1f %% des Prompts"
              % (pos, 100.0 * pos / max(laenge, 1)))
        print("Dahinter folgen noch %d Zeichen." % (laenge - pos - len(TEXT)))

    # Zum Vergleich: der Zeit-Abschnitt steht bewusst am Ende.
    pz = sp.find("## JETZT")
    if pz >= 0:
        print("Vergleich `## JETZT`: %.1f %% (bewusst am Ende)"
              % (100.0 * pz / max(laenge, 1)))

    print("\n=== WAS DER BENUTZER SIEHT ===")
    marken = [z for z in ws.zeilen if "Prompt" in z or "Preprompt" in z]
    print("Statuszeilen zum Prompt: %r" % marken)
    if not marken:
        print("⚠ KEINE Statuszeile – der Benutzer kann nicht erkennen, ob er greift.")

    print("\n=== UMFELD (was NACH der Anweisung kommt) ===")
    if pos >= 0:
        rest = sp[pos + len(TEXT):]
        for m in ("UNTRUSTED_CONTEXT", "## JETZT", "WERKZEUG", "Office",
                  "ERGEBNIS-DATEIEN", "SICHERHEIT"):
            p = rest.find(m)
            if p >= 0:
                print("  + %-20s nach %6d Zeichen" % (m, p))
finally:
    try:
        CS.delete_session(BENUTZER, SID)
        print("\n  … Probe-Sitzung entfernt")
    except Exception as e:                                         # noqa: BLE001
        print("\n  ⚠ Probe-Sitzung NICHT entfernt: %s" % e)
