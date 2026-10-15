#!/usr/bin/env python3
"""Wo bricht der Prompt-Cache – und was braechte ein Verschieben von `## JETZT`?

⚠ VERAENDERT NICHTS. Eigene Sitzung, am Ende abgeraeumt.

Befund, der die Frage ausgeloest hat: `## JETZT` steht bei 31,8 % des
System-Prompts, waehrend sein Docstring behauptet "am ENDE … der lange, stabile
Teil davor bleibt als Cache-Praefix unangetastet". Es steht am Ende des
BASIS-Prompts; danach haengt `run_task` noch Anweisungsdateien, Gedaechtnis und
die persoenliche Anweisung an.

⚠ BEVOR IRGENDETWAS VERSCHOBEN WIRD, muessen DREI Dinge gemessen sein – sonst
optimiert man eine Vermutung:

  1. Welche Abschnitte sind ueberhaupt VARIABEL? Ein Verschieben von `## JETZT`
     bringt nichts, wenn gleich danach der naechste variable Teil kommt. Der
     Gedaechtnis-Block ist `load_selective_memory(task_text)` – also
     AUFGABENabhaengig; steht er hinter der Zeit, ist der Gewinn bei jeder
     NEUEN Frage ohnehin weg.
  2. Wie GROSS ist der Anteil vor und nach der Verschiebung?
  3. Kostet ein Cache-Miss an dieser Stelle ueberhaupt messbar Zeit? Im Projekt
     gemessen sind es +81 % – aber an einem anderen Prompt und einem anderen
     Tag. Hier wird es am ECHTEN Prompt nachgemessen, mit Positivkontrolle.
"""
import asyncio
import statistics
import sys
import time

sys.path.insert(0, "/opt/jarvis")

from google.genai import types                                     # noqa: E402

from backend import chat_sessions as CS                            # noqa: E402
from backend import agent as A                                     # noqa: E402
from backend import llm as L                                       # noqa: E402

BENUTZER = "jarvis"
JE = int(sys.argv[1]) if len(sys.argv) > 1 else 6
FRAGE = "Sag nur OK."

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


sess = CS.create_session(BENUTZER, "ZZ-Probe Cache")
SID = sess["id"] if isinstance(sess, dict) else str(sess)
CS.save_session_preprompt(BENUTZER, SID, "Antworte knapp.")

try:
    echt = A.get_provider
    A.get_provider = lambda *a, **kw: _P()
    try:
        asyncio.run(A.JarvisAgent().run_task(FRAGE, _WS(), username=BENUTZER,
                                             session_id=SID))
    except Exception:                                              # noqa: BLE001
        pass
    A.get_provider = echt

    sp = gefangen.get("sp") or ""
    werkzeuge = gefangen.get("tools") or []
    if not sp:
        print("ABBRUCH: kein System-Prompt eingefangen.")
        sys.exit(2)

    n = len(sp)
    print("=" * 72)
    print("[1] AUFBAU des echten System-Prompts (%d Zeichen, %d Werkzeuge)"
          % (n, len(werkzeuge)))
    print("=" * 72)
    marken = [
        ("## JETZT", "Zeit – wechselt je MINUTE"),
        ("[UNTRUSTED_CONTEXT", "Gedaechtnis – AUFGABENabhaengig"),
        ("[PERSÖNLICHE ANWEISUNG", "Preprompt – SITZUNGSabhaengig"),
    ]
    # ⚠ ALLE VORKOMMEN, UND DAS LETZTE ZAEHLT. `find` liefert das erste – und
    # der Basis-Prompt ERKLAERT die UNTRUSTED_CONTEXT-Konvention, bevor
    # `run_task` den echten Gedaechtnis-Block anhaengt. Die erste Fassung
    # dieser Probe meldete deshalb "Cache-Praefix endet bei 2,2 %" und traf
    # damit einen Erklaerungstext statt eines variablen Abschnitts. Dieselbe
    # Falle habe ich fuer `## JETZT` vermieden und hier trotzdem gebaut.
    stellen = []
    for m, was in marken:
        alle = []
        q = sp.find(m)
        while q >= 0:
            alle.append(q)
            q = sp.find(m, q + 1)
        if not alle:
            print("  KEINS       %-26s (nicht im Prompt)" % m)
            continue
        # Der zuletzt angehaengte Block ist der wirksame.
        stellen.append((alle[-1], m, was))
        print("  %6.1f %%  %-26s %s%s"
              % (100.0 * alle[-1] / n, m, was,
                 ("   (%d Vorkommen: %s)"
                  % (len(alle), ", ".join("%.0f%%" % (100.0 * x / n)
                                          for x in alle)))
                 if len(alle) > 1 else ""))
    stellen.sort()

    # ⚠ DER ERSTE VARIABLE ABSCHNITT BESTIMMT DEN CACHE-PRAEFIX. Alles dahinter
    # ist wertlos fuer den Cache, egal wie stabil es ist.
    if stellen:
        erste = stellen[0]
        print("\n  => Cache-Praefix endet bei %.1f %% (%s)"
              % (100.0 * erste[0] / n, erste[1]))
        # Was braechte das Verschieben von `## JETZT` hinter die
        # Anweisungsdateien? Dann ist der naechste variable Teil der Erste der
        # uebrigen.
        ohne_zeit = [s for s in stellen if s[1] != "## JETZT"]
        if ohne_zeit:
            print("  => nach dem Verschieben: %.1f %% (%s)"
                  % (100.0 * ohne_zeit[0][0] / n, ohne_zeit[0][1]))
            print("     Gewinn: %+.1f Prozentpunkte = %d Zeichen"
                  % (100.0 * (ohne_zeit[0][0] - erste[0]) / n,
                     ohne_zeit[0][0] - erste[0]))
        else:
            print("  => nach dem Verschieben: 100 %% (nichts Variables mehr)")

    # ── 2) Kostet der Miss an DIESER Stelle Zeit? ──────────────────────────
    print("\n" + "=" * 72)
    print("[2] Kostet ein Cache-Miss an dieser Stelle Zeit? (je %d Messungen)" % JE)
    print("=" * 72)
    prov, modell = L.provider_fuer_lauf(prompt_tool_calling=False)

    # ⚠ OHNE `max_tokens=1` IST DIE MESSUNG UNBRAUCHBAR. Die erste Fassung mass
    # die Gesamtlatenz – und die Generierungszeit ueberdeckte den Cache-Effekt
    # vollstaendig: der Treffer lag bei 835 ms (314–984), der MISS bei 789 ms,
    # also SCHNELLER. Ein Ergebnis, das der Erwartung widerspricht, ist zuerst
    # ein Verdacht gegen das Messwerkzeug. Gemessen werden soll die
    # PROMPT-Verarbeitung, nicht das Schreiben der Antwort.
    L._llm_max_tokens = lambda: 1

    async def messe(prompts):
        """Latenzen fuer eine Folge von Prompts – ein Aufruf je Eintrag."""
        raus = []
        for p in prompts:
            t0 = time.perf_counter()
            try:
                await prov.generate_response(
                    model=modell, system_prompt=p,
                    contents=[types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=FRAGE)])],
                    tools=[], reasoning_effort="off")
            except Exception as e:                                 # noqa: BLE001
                print("     ABBRUCH: %s" % str(e)[:90])
                return []
            raus.append((time.perf_counter() - t0) * 1000.0)
        return raus

    # ⚠ AUFWAERMEN, UND ZWAR JEDE VARIANTE. Eine erste Fassung dieser Art von
    # Messung waermte nur EINE auf – die andere trug dann den Kaltstart und das
    # Ergebnis war frei erfunden (Register 2026-09-06).
    p_gleich = sp
    # Miss an der Stelle von `## JETZT`: nur dort ein Zeichen aendern.
    pz = sp.find("## JETZT")
    p_frueh = (sp[:pz] + "## JETZT  " + sp[pz + 8:]) if pz >= 0 else sp
    # Miss ganz hinten: an der Stelle, an der `## JETZT` NACH dem Verschieben
    # stuende (hinter den Anweisungsdateien, vor Gedaechtnis/Preprompt).
    pu = sp.rfind("[UNTRUSTED_CONTEXT")
    if pu < 0:
        pu = sp.rfind("[PERSÖNLICHE ANWEISUNG")
    p_spaet = (sp[:pu] + "X" + sp[pu:]) if pu > 0 else sp + "X"
    # ⚠ DIE ENTSCHEIDENDE KONTROLLE: ein KURZER Prompt. Ohne sie laesst
    # sich "kein Cache-Effekt" nicht von "mein Messaufbau sieht nichts"
    # unterscheiden – und genau dieser Unterschied ist der ganze Wert der
    # Messung. Sieht der Aufbau nicht einmal 19.000 Token gegen 40, ist
    # jede Zahl darueber wertlos.
    p_kurz = "Du bist ein Assistent. Antworte knapp."

    async def alles():
        await messe([p_gleich, p_frueh, p_spaet])          # jede Variante aufwaermen
        # ⚠ VERSCHRAENKT, NICHT IN BLOECKEN: ein Lastanstieg auf dem Server
        # trifft sonst systematisch die zuletzt gemessene Variante und sieht wie
        # ein Befund aus.
        a, b, c, k = [], [], [], []
        for i in range(JE):
            z = chr(65 + i)
            a += await messe([p_gleich])
            b += await messe([p_frueh[:-1] + z])
            c += await messe([p_spaet[:-1] + z])
            k += await messe([p_kurz + " " + z])
        return a, b, c, k

    a, b, c, k = asyncio.run(alles())
    if not (a and b and c and k):
        print("  ⚠ nicht alle Varianten messbar – kein Urteil.")
    else:
        for name, werte in (("gleicher Prompt (Treffer)", a),
                            ("Unterschied bei %.0f %% (heute)"
                             % (100.0 * pz / n if pz >= 0 else 0), b),
                            ("Unterschied bei %.0f %% (nach Verschieben)"
                             % (100.0 * pu / n if pu > 0 else 100), c)):
            print("  %-42s median %6.0f ms  (min %.0f, max %.0f)"
                  % (name, statistics.median(werte), min(werte), max(werte)))
        # ⚠ POSITIVKONTROLLE: unterscheiden sich Treffer und frueher Miss
        # ueberhaupt? Wenn nicht, macht Praefix-Caching hier gar nichts – und
        # dann ist die ganze Verschiebung eine Optimierung fuer nichts.
        mk = statistics.median(k)
        print("  %-42s median %6.0f ms  (min %.0f, max %.0f)"
              % ("KONTROLLE: kurzer Prompt (~40 Token)", mk, min(k), max(k)))
        mt, mf = statistics.median(a), statistics.median(b)
        # ⚠ TAUGLICHKEIT ZUERST: sieht der Aufbau 19.000 Token gegen 40?
        if mt - mk < 0.05 * max(mt, 1):
            print("\n  ⚠ DER AUFBAU IST BLIND: langer und kurzer Prompt sind\n"
                  "     gleich schnell (%.0f gegen %.0f ms). Damit ist KEINE\n"
                  "     Aussage ueber den Cache moeglich." % (mt, mk))
            sys.exit(2)
        print("  => Aufbau tauglich: lang gegen kurz = %+.0f ms (%+.0f %%)"
              % (mt - mk, 100.0 * (mt - mk) / mk if mk else 0))
        print("\n  Positivkontrolle: Treffer gegen fruehen Miss = %+.0f ms (%+.0f %%)"
              % (mf - mt, 100.0 * (mf - mt) / mt if mt else 0))
        if abs(mf - mt) < 0.05 * max(mt, 1):
            print("  => KEIN messbarer Cache-Effekt. Verschieben braechte nichts.")
        else:
            ms = statistics.median(c)
            print("  => Cache wirkt. Spaeter Miss gegen fruehen: %+.0f ms" % (ms - mf))
finally:
    try:
        CS.delete_session(BENUTZER, SID)
        print("\n  … Probe-Sitzung entfernt")
    except Exception as e:                                         # noqa: BLE001
        print("\n  ⚠ Probe-Sitzung NICHT entfernt: %s" % e)
