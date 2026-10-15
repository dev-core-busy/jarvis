#!/usr/bin/env python3
"""NUR LESEN/MESSEN: der Wortlaut um den Chat-Preprompt – und ob er WIRKT.

⚠ VERAENDERT NICHTS: eigene Sitzung, am Ende abgeraeumt. Keine Einstellung
wird umgestellt.

Zwei Fragen, die die Positionsmessung offengelassen hat:

  1. WIE ist die Anweisung gerahmt, und was steht unmittelbar davor/danach?
     Gemessen wurde: direkt dahinter beginnt ein `UNTRUSTED_CONTEXT`-Block.
     Wenn die Grenze zwischen "Anweisung des Benutzers" und "Daten, denen du
     nicht trauen sollst" nicht deutlich ist, entwertet der zweite Block den
     ersten – und das Modell behandelt die Anweisung als Datum.

  2. WIRKT sie?  ⚠ NACHTRAG: die Antwort haengt an den WERKZEUGEN, nicht am
     Umfeld – siehe `lies_pp_werkzeuge_dev.py`. Der Verdacht gegen den
     `UNTRUSTED_CONTEXT`-Block daneben ist NICHT belegt; behoben wurde die
     Stelle (ans Ende), und die Grenze zum Block ist dadurch nebenbei klar.
     WIRKT sie? Mehrfach gemessen, weil eine Modellantwort erst nach
     Wiederholung eine Messung ist (`temperature` steht auf "auto").
"""
import asyncio
import sys

sys.path.insert(0, "/opt/jarvis")

from backend import chat_sessions as CS                            # noqa: E402
from backend import agent as A                                     # noqa: E402

BENUTZER = "jarvis"
# Eine Anweisung, deren Befolgung sich MASCHINELL pruefen laesst - "antworte
# knapper" waere nicht messbar.
TEXT = "Beginne JEDE Antwort mit dem Wort BANANE."
LAEUFE = int(sys.argv[1]) if len(sys.argv) > 1 else 3

sess = CS.create_session(BENUTZER, "ZZ-Probe Umfeld")
SID = sess["id"] if isinstance(sess, dict) else str(sess)
CS.save_session_preprompt(BENUTZER, SID, TEXT)

gesehen = {}


class _Halt(Exception):
    pass


class _P:
    async def generate_response(self, *a, **kw):
        gesehen["sp"] = kw.get("system_prompt") or (a[1] if len(a) > 1 else "")
        raise _Halt()


class _WS:
    async def send_json(self, *a, **kw):
        return None


try:
    # ── 1) Umfeld ──────────────────────────────────────────────────────────
    echt = A.get_provider
    A.get_provider = lambda *a, **kw: _P()
    try:
        asyncio.run(A.JarvisAgent().run_task("Sag Hallo.", _WS(),
                                             username=BENUTZER, session_id=SID))
    except Exception:                                              # noqa: BLE001
        pass
    A.get_provider = echt

    sp = gesehen.get("sp") or ""
    pos = sp.find(TEXT)
    if pos < 0:
        print("ABBRUCH: Anweisung nicht im System-Prompt.")
        sys.exit(2)
    print("=" * 70)
    print("UMFELD (1200 Zeichen davor / 900 danach)")
    print("=" * 70)
    print("--- DAVOR ---")
    print(sp[max(0, pos - 1200):pos])
    print("--- >>> DIE ANWEISUNG <<< ---")
    print(TEXT)
    print("--- DANACH ---")
    print(sp[pos + len(TEXT):pos + len(TEXT) + 900])

    # ── 2) Wirkung, mit echtem Modell ──────────────────────────────────────
    #
    # ⚠ ALLE LAEUFE IN EINEM EVENT-LOOP. Ein `asyncio.run()` je Lauf toetet den
    # httpx-Client des Providers (er haengt am ERSTEN Loop) – der zweite Lauf
    # stirbt dann mit "Event loop is closed" und wird als "ignoriert" gezaehlt,
    # obwohl das Modell nie gefragt wurde. Steht im Register, in der ersten
    # Fassung dieser Probe trotzdem passiert.
    #
    # ⚠ GEMESSEN WIRD DIE LETZTE HIGHLIGHT-ZEILE, nicht ihre Summe: die
    # Statusmeldungen ("⏳ Warte auf LLM-Antwort…") sind ebenfalls `highlight`.
    # Aneinandergehaengt beginnt der Text mit dem Status, und ein
    # `startswith("BANANE")` meldet dann IGNORIERT fuer eine Antwort, die
    # woertlich mit BANANE anfaengt – die erste Fassung meldete so 0 von 3,
    # waehrend 2 von 2 verwertbaren Laeufen die Anweisung befolgt hatten.
    print("\n" + "=" * 70)
    print("WIRKUNG: %d Laeufe mit dem ECHTEN Modell" % LAEUFE)
    print("=" * 70)

    def _befolgt(text: str) -> bool:
        return (text or "").strip().upper().lstrip("*_# ").startswith("BANANE")

    async def _alle():
        treffer = verwertbar = 0
        for i in range(LAEUFE):
            ag = A.JarvisAgent()
            zeilen: list[str] = []

            class _WS2:
                async def send_json(self, d, *a, **kw):
                    t = (d or {}).get("message") or ""
                    if (d or {}).get("highlight") and str(t).strip():
                        zeilen.append(str(t).strip())
                    return None

            try:
                await ag.run_task("Wie viel ist 2+2?", _WS2(),
                                  username=BENUTZER, session_id=SID)
            except Exception as e:                                 # noqa: BLE001
                print("  Lauf %d: ABBRUCH %s" % (i + 1, str(e)[:120]))
                continue
            # Statuszeilen mit fuehrendem Symbol fallen heraus; uebrig bleibt
            # die Antwort. Bleibt nichts uebrig, ist der Lauf NICHT verwertbar –
            # er darf nicht als "ignoriert" zaehlen.
            echt = [z for z in zeilen if not z[:1] in "⏳✅❌📝📋⚠🔧🤖"]
            if not echt:
                print("  Lauf %d: NICHT VERWERTBAR (keine Antwort) %r"
                      % (i + 1, zeilen[-1][:70] if zeilen else ""))
                continue
            verwertbar += 1
            antwort = echt[-1]
            ok = _befolgt(antwort)
            treffer += 1 if ok else 0
            print("  Lauf %d: %s  %r" % (i + 1, "BEFOLGT" if ok else "IGNORIERT",
                                         antwort[:90]))
        return treffer, verwertbar

    treffer, verwertbar = asyncio.run(_alle())
    print("\n  Ergebnis: %d von %d VERWERTBAREN Laeufen befolgen die Anweisung"
          % (treffer, verwertbar))
    if not verwertbar:
        print("  ⚠ KEIN verwertbarer Lauf – die Zahl sagt nichts ueber die Wirkung.")
finally:
    try:
        CS.delete_session(BENUTZER, SID)
        print("  … Probe-Sitzung entfernt")
    except Exception as e:                                         # noqa: BLE001
        print("  ⚠ Probe-Sitzung NICHT entfernt: %s" % e)
