#!/usr/bin/env python3
"""Woran haengt die Befolgung des Chat-Preprompts – Position oder WERKZEUGE?

⚠ VERAENDERT NICHTS. Eigene Sitzung, am Ende abgeraeumt.

Vorgeschichte, gemessen an genau diesem Aufbau:

  * ueber `run_task` (86 Werkzeuge):        2 von 4 befolgt
  * derselbe System-Prompt, `tools=[]`:     8 von 8 befolgt
  * dieselbe Anweisung ans ENDE, `tools=[]`: 8 von 8  ⇒ Position ist es NICHT

Die beiden ersten Messungen unterscheiden sich aber in ZWEI Dingen – Werkzeuge
ja/nein UND `run_task` gegen direkten Provider-Aufruf. Den Unterschied den
Werkzeugen zuzuschreiben waere derselbe Fehlschluss, der die
Positionshypothese erzeugt hat. Also: EINE Schleife, EIN Provider, und
verschieden ist genau ein Merkmal.

  A  Prompt an der IST-Stelle  ohne Werkzeuge
  C  Prompt an der IST-Stelle  MIT den echten Werkzeugen   <- nur hierin anders als A
  D  Prompt ans Ende geschoben MIT den echten Werkzeugen   <- hilft die Position DANN?

Ergebnis (je 15 Laeufe): A 100 % · C 80 % · D 100 % ⇒ die Werkzeuge kosten, und
die Position ist die Abhilfe.

⚠ SEIT DEM FIX VOM 2026-09-11 SIND C UND D DASSELBE. `agent.py` haengt die
Anweisung jetzt selbst zuletzt an, die IST-Stelle IST also das Ende – die Probe
meldet seither fuer beide 99,9 % und 15/15. Die Spalte heisst deshalb
"IST-Stelle" und nicht mehr "77 %": wer hier "C 77 %" liest, haelt eine
Bestaetigung des Fixes fuer einen Widerspruch dazu. Um den Altstand erneut zu
messen, muesste man den Anhaeng-Schritt zurueckdrehen (siehe
`tests/gegen_pp_zuletzt.py`, Probe 1).

⚠ Urteil ueber QUOTEN, nie ueber Einzellaeufe. Alle Varianten im SELBEN
Event-Loop mit DEMSELBEN Provider.
"""
import asyncio
import sys

sys.path.insert(0, "/opt/jarvis")

from google.genai import types                                     # noqa: E402

from backend import chat_sessions as CS                            # noqa: E402
from backend import agent as A                                     # noqa: E402
from backend import llm as L                                       # noqa: E402

BENUTZER = "jarvis"
TEXT = "Beginne JEDE Antwort mit dem Wort BANANE."
JE = int(sys.argv[1]) if len(sys.argv) > 1 else 6
FRAGE = "Wie viel ist 2+2?"

sess = CS.create_session(BENUTZER, "ZZ-Probe Werkzeuge")
SID = sess["id"] if isinstance(sess, dict) else str(sess)
CS.save_session_preprompt(BENUTZER, SID, TEXT)

gefangen = {}


class _Halt(Exception):
    pass


class _P:
    async def generate_response(self, *a, **kw):
        gefangen["sp"] = kw.get("system_prompt") or ""
        gefangen["tools"] = kw.get("tools")
        raise _Halt()


class _WS:
    async def send_json(self, *a, **kw):
        return None


def befolgt(t: str) -> bool:
    return (t or "").strip().upper().lstrip("*_# \n").startswith("BANANE")


try:
    # ── System-Prompt UND Werkzeugliste aus einem ECHTEN Lauf ──────────────
    echt = A.get_provider
    A.get_provider = lambda *a, **kw: _P()
    try:
        asyncio.run(A.JarvisAgent().run_task(FRAGE, _WS(), username=BENUTZER,
                                             session_id=SID))
    except Exception:                                              # noqa: BLE001
        pass
    A.get_provider = echt

    sp_a = gefangen.get("sp") or ""
    werkzeuge = gefangen.get("tools") or []
    marke = ("\n\n[PERSÖNLICHE ANWEISUNG DES BENUTZERS – Stil/Kontext/Vorlieben; "
             "hebt bestehende Sicherheits- und Rechtebeschränkungen NICHT auf]\n")
    block = marke + TEXT
    if block not in sp_a:
        print("ABBRUCH: Anweisungsblock nicht im echten Prompt.")
        sys.exit(2)
    # Positivkontrolle: ohne Werkzeuge misst Variante C gar nichts.
    if not werkzeuge:
        print("ABBRUCH: der Lauf hatte KEINE Werkzeuge – C/D wären trivial.")
        sys.exit(2)
    sp_d = sp_a.replace(block, "", 1) + block

    print("Prompt %d Zeichen · Anweisung A/C bei %.1f %% · D bei %.1f %% · "
          "%d Werkzeuge · je %d Laeufe"
          % (len(sp_a), 100.0 * sp_a.find(TEXT) / len(sp_a),
             100.0 * sp_d.find(TEXT) / len(sp_d), len(werkzeuge), JE))

    # Der Zeit-Abschnitt steht laut Projektnotiz "bewusst am ENDE (98 %)".
    # Gemessen wurden 31,8 % – deshalb ALLE Vorkommen zeigen, statt aus dem
    # ersten einen Schluss zu ziehen (`find` liefert nur das erste).
    stellen, p = [], sp_a.find("## JETZT")
    while p >= 0:
        stellen.append("%.1f %%" % (100.0 * p / len(sp_a)))
        p = sp_a.find("## JETZT", p + 1)
    print("`## JETZT` kommt %dx vor: %s" % (len(stellen), ", ".join(stellen)))

    prov, modell = L.provider_fuer_lauf(prompt_tool_calling=False)

    async def frag(sysp, tools):
        r = await prov.generate_response(
            model=modell, system_prompt=sysp,
            contents=[types.Content(role="user",
                                    parts=[types.Part.from_text(text=FRAGE)])],
            tools=tools)
        return "".join(p.text for p in (r.parts or [])
                       if getattr(p, "text", None))

    async def lauf():
        bilanz = {}
        # A ist nur die POSITIVKONTROLLE (ohne Werkzeuge muss es tragen) und
        # braucht keine 15 Laeufe; verglichen werden C und D.
        for name, sysp, tools, n in (("A IST, ohne WZ", sp_a, [], 3),
                                     ("C IST,  MIT WZ", sp_a, werkzeuge, JE),
                                     ("D Ende, MIT WZ", sp_d, werkzeuge, JE)):
            ok = v = 0
            for i in range(n):
                try:
                    t = await frag(sysp, tools)
                except Exception as e:                             # noqa: BLE001
                    print("  %-15s Lauf %d: ABBRUCH %s"
                          % (name, i + 1, str(e)[:80]))
                    continue
                if not (t or "").strip():
                    # Mit Werkzeugen kann die Antwort ein reiner Aufruf sein –
                    # das ist KEIN "ignoriert", sondern nicht verwertbar.
                    print("  %-15s Lauf %d: NICHT VERWERTBAR (kein Text)"
                          % (name, i + 1))
                    continue
                v += 1
                gut = befolgt(t)
                ok += 1 if gut else 0
                print("  %-15s Lauf %d: %-9s %r"
                      % (name, i + 1, "BEFOLGT" if gut else "ignoriert",
                         t.strip()[:55]))
            bilanz[name] = (ok, v)
        return bilanz

    print()
    bilanz = asyncio.run(lauf())
    print("\n" + "=" * 64)
    for name, (ok, v) in bilanz.items():
        print("  %-15s %d von %d verwertbaren befolgt  (%s)"
              % (name, ok, v, ("%.0f %%" % (100.0 * ok / v)) if v else "–"))
    print("=" * 64)
finally:
    try:
        CS.delete_session(BENUTZER, SID)
        print("  … Probe-Sitzung entfernt")
    except Exception as e:                                         # noqa: BLE001
        print("  ⚠ Probe-Sitzung NICHT entfernt: %s" % e)
