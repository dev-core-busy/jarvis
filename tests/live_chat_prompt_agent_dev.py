#!/usr/bin/env python3
"""Live auf DEV: greift der Chat-Prompt im ECHTEN Agenten?

Gemessen wird am ECHTEN `JarvisAgent` mit der ECHTEN `run_task`-Kette, was der
Wächter nur an einem Schnitt zeigen kann: welcher Prompt im System-Prompt
landet, wenn eine Sitzung einen eigenen traegt – und dass der persoenliche
dabei WEG ist, nicht daneben steht.

Kein Modellaufruf: abgegriffen wird der System-Prompt, bevor er hinausgeht
(die Provider-Attrappe bricht den Lauf danach ab). So kostet die Messung nichts
und haengt nicht an der Erreichbarkeit eines LLM-Profils.

⚠ Der vorgefundene Zustand wird wiederhergestellt: die Testsitzung wird
   geloescht, der persoenliche Preprompt des Benutzers auf seinen ALTEN Wert
   zurueckgesetzt (nicht auf einen geratenen Leerwert).

Aufruf: cd /opt/jarvis && ./venv/bin/python tests/live_chat_prompt_agent_dev.py
"""
import asyncio
import sys

sys.path.insert(0, "/opt/jarvis")

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


print("=" * 74)
print("LIVE auf DEV: Chat-Prompt im ECHTEN Agentenlauf")
print("=" * 74)

from backend import agent as ag           # noqa: E402
from backend import chat_sessions as cs   # noqa: E402

U = "jarvis"
PERS = "PERSOENLICH-MARKE: antworte immer ausfuehrlich auf Deutsch."
CHAT = "CHAT-MARKE: antworte in diesem Chat nur auf Englisch, maximal ein Satz."

pp_vorher = cs.get_preprompt(U)           # VORGEFUNDENEN Wert merken
sess = cs.create_session(U, "LIVE Agent-Probe")
SID = sess["id"]
gesehen = {}


class _Halt(Exception):
    """Bricht den Lauf ab, sobald der System-Prompt steht."""


class _Provider:
    """Attrappe: faengt den System-Prompt ab und beendet den Lauf sofort."""

    def __init__(self, marke):
        self.marke = marke

    async def generate_response(self, *a, **kw):
        sp = kw.get("system_instruction") or kw.get("system_prompt") or ""
        if not sp:
            for x in a:
                if isinstance(x, str) and len(x) > 200:
                    sp = x
                    break
        gesehen[self.marke] = sp
        raise _Halt()


class _WS:
    """WebSocket-Attrappe: sammelt die Statusmeldungen."""

    def __init__(self):
        self.texte = []

    async def send_json(self, d):
        t = (d or {}).get("message") or (d or {}).get("text") or ""
        if t:
            self.texte.append(t)

    async def send_text(self, t):
        self.texte.append(t)


async def lauf(marke, session_id):
    """Einen echten run_task starten und den System-Prompt abgreifen."""
    a = ag.AgentManager().get_or_create_main() if hasattr(ag, "AgentManager") else None
    if a is None:
        a = ag.JarvisAgent()
    ws = _WS()
    alt = ag.get_provider
    ag.get_provider = lambda *x, **y: _Provider(marke)
    try:
        await a.run_task("Sag Hallo.", ws, username=U, session_id=session_id)
    except _Halt:
        pass
    except Exception as e:  # noqa: BLE001
        # Der Lauf darf an der Attrappe scheitern – nur der System-Prompt zaehlt.
        if marke not in gesehen:
            print(f"       (Lauf {marke} endete mit {type(e).__name__}: {str(e)[:90]})")
    finally:
        ag.get_provider = alt
    return ws.texte


try:
    # ── (1) nur persoenlicher Preprompt ─────────────────────────────────────
    cs.save_preprompt(U, PERS)
    cs.save_session_preprompt(U, SID, "")
    t1 = asyncio.run(lauf("nur_pers", SID))
    sp1 = gesehen.get("nur_pers", "")
    check("System-Prompt abgegriffen (Positivkontrolle der Messung)", len(sp1) > 500,
          f"{len(sp1)} Zeichen")
    check("ohne Chat-Prompt steht der PERSOENLICHE im System-Prompt", PERS in sp1)
    check("und der Status meldet den persoenlichen",
          any("Persönlicher Preprompt" in x for x in t1), str(t1[-3:]))

    # ── (2) Chat-Prompt gesetzt -> ERSETZT ──────────────────────────────────
    cs.save_session_preprompt(U, SID, CHAT)
    t2 = asyncio.run(lauf("mit_chat", SID))
    sp2 = gesehen.get("mit_chat", "")
    check("mit Chat-Prompt steht DIESER im System-Prompt", CHAT in sp2)
    check("⚠ und der persoenliche steht NICHT mehr daneben (ERSETZT)", PERS not in sp2,
          "beide Marken im Prompt" if PERS in sp2 else "")
    check("der Status nennt den Chat-Prompt",
          any("diesen Chat" in x for x in t2), str(t2[-3:]))

    # ── (3) andere Sitzung desselben Benutzers: wieder der persoenliche ─────
    s2 = cs.create_session(U, "LIVE Agent-Probe 2")
    t3 = asyncio.run(lauf("andere_sitzung", s2["id"]))
    sp3 = gesehen.get("andere_sitzung", "")
    check("eine ANDERE Sitzung bekommt weiterhin den persoenlichen",
          PERS in sp3 and CHAT not in sp3)
    cs.delete_session(U, s2["id"])

finally:
    # VORGEFUNDENEN Zustand wiederherstellen – nicht einen geratenen.
    cs.delete_session(U, SID)
    cs.save_preprompt(U, pp_vorher)
    check("Testsitzung entfernt", not cs._valid(U, SID))
    check("⚠ der persoenliche Preprompt ist auf seinem ALTEN Stand",
          cs.get_preprompt(U) == pp_vorher,
          f"vorher={pp_vorher[:40]!r} jetzt={cs.get_preprompt(U)[:40]!r}")

print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(1 if _fail else 0)
