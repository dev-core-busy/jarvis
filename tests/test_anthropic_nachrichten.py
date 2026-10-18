#!/usr/bin/env python3
"""Waechter: was der Anthropic-Provider an die API schickt (Code-Review 2026-10-18).

AUSGEFUEHRT an ``AnthropicProvider.generate_response`` mit einem Attrappen-
Client (echte Aufrufform ``client.messages.create(**kw)``, Antwort mit
``content``/``stop_reason``/``usage``); ``backend.config`` nur als Stub:
  [1] zwei parallele Aufrufe DESSELBEN Werkzeugs: eindeutige tool_use-IDs,
      die tool_result-Bloecke verweisen je auf die richtige
  [2] ein Bild an der Werkzeug-Antwort kommt im tool_result an; ein PDF-Anhang
      als document-Block
  [3] Prompt-Caching: cache_control am letzten Werkzeug, am System-Prompt und
      am juengsten Block
  [4] max_tokens aus der Einstellung, gedeckelt; Kappung (stop_reason
      max_tokens) wird als HINWEIS_UNVOLLSTAENDIG gemeldet
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import asyncio
import sys
import types as _pt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


stub = _pt.ModuleType("backend.config")
stub.config = _pt.SimpleNamespace(LLM_MAX_TOKENS=100000)
sys.modules["backend.config"] = stub
try:
    import backend.llm as L
    from google.genai import types
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend.llm nicht importierbar: %s" % e)
    sys.exit(2)


class Antwort:
    def __init__(self, stop="end_turn"):
        self.content = [_pt.SimpleNamespace(type="text", text="ok")]
        self.stop_reason = stop
        self.usage = _pt.SimpleNamespace(input_tokens=10, output_tokens=2,
                                         cache_read_input_tokens=7, cache_creation_input_tokens=3)


class Client:
    def __init__(self, stop="end_turn"):
        self.kw = None
        self.stop = stop
        self.messages = self

    async def create(self, **kw):
        self.kw = kw
        return Antwort(self.stop)


class Werkzeug:
    def __init__(self, name):
        self.name = name
        self.description = "d"

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {}}


P = object.__new__(L.AnthropicProvider)
P.client = Client()
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
PDF = b"%PDF-1.4 probe"
inhalte = [
    types.Content(role="user", parts=[types.Part.from_text(text="Mach zwei Screenshots"),
                                      types.Part.from_bytes(data=PDF, mime_type="application/pdf")]),
    types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name="screenshot", args={"n": 1})),
        types.Part(function_call=types.FunctionCall(name="screenshot", args={"n": 2}))]),
    types.Content(role="user", parts=[
        types.Part.from_function_response(name="screenshot", response={"result": "erstes"}),
        types.Part.from_function_response(name="screenshot", response={"result": "zweites"}),
        types.Part.from_bytes(data=PNG, mime_type="image/png")]),
]
erg = asyncio.run(P.generate_response("claude-x", "SYSTEM", inhalte,
                                      tools=[Werkzeug("a"), Werkzeug("screenshot")]))
kw = P.client.kw
check("(Positivkontrolle) Anfrage gebaut", isinstance(kw, dict) and len(kw.get("messages", [])) == 3,
      str(kw)[:200] if kw else "keine")
if FAIL:
    print("ABBRUCH: Messaufbau traegt nicht")
    sys.exit(2)
msgs = kw["messages"]

print("\n[1] eindeutige IDs")
uses = [b for b in msgs[1]["content"] if b.get("type") == "tool_use"]
ids = [b["id"] for b in uses]
check("zwei tool_use mit VERSCHIEDENEN IDs", len(ids) == 2 and len(set(ids)) == 2, str(ids))
res = [b for b in msgs[2]["content"] if b.get("type") == "tool_result"]
check("tool_result verweisen der Reihe nach auf die IDs", [r["tool_use_id"] for r in res] == ids,
      str([r["tool_use_id"] for r in res]))

print("\n[2] Bilder und PDF")
letzter = res[-1]["content"] if res else None
check("Bild der Werkzeug-Antwort steht im tool_result",
      isinstance(letzter, list) and any(b.get("type") == "image" for b in letzter), str(letzter)[:200])
check("... samt dem Text des Ergebnisses",
      isinstance(letzter, list) and any(b.get("type") == "text" and b.get("text") == "zweites" for b in letzter))
erste = msgs[0]["content"]
check("PDF-Anhang als document-Block",
      isinstance(erste, list) and any(b.get("type") == "document"
                                      and b["source"]["media_type"] == "application/pdf" for b in erste),
      str(erste)[:200])

print("\n[3] Prompt-Caching")
check("letztes Werkzeug traegt cache_control", kw["tools"][-1].get("cache_control") == {"type": "ephemeral"}
      and "cache_control" not in kw["tools"][0])
check("System-Prompt als Block mit cache_control",
      isinstance(kw["system"], list) and kw["system"][0].get("text") == "SYSTEM"
      and kw["system"][0].get("cache_control") == {"type": "ephemeral"})
check("juengster Block traegt cache_control",
      isinstance(msgs[-1]["content"], list) and msgs[-1]["content"][-1].get("cache_control") == {"type": "ephemeral"})
check("usage meldet Cache-Werte", erg.usage.get("cache_read_input_tokens") == 7)

print("\n[4] max_tokens")
check("aus der Einstellung, gedeckelt (100000 -> %d)" % L._ANTHROPIC_MAX_TOKENS_OHNE_STREAM,
      kw["max_tokens"] == L._ANTHROPIC_MAX_TOKENS_OHNE_STREAM, str(kw["max_tokens"]))
stub.config.LLM_MAX_TOKENS = 4000
P.client = Client(stop="max_tokens")
erg = asyncio.run(P.generate_response("claude-x", "S", [types.Content(role="user", parts=[types.Part.from_text(text="x")])]))
check("kleiner Wert wird uebernommen", P.client.kw["max_tokens"] == 4000, str(P.client.kw["max_tokens"]))
check("Kappung bei max_tokens wird gemeldet",
      any(L.HINWEIS_UNVOLLSTAENDIG in (p.text or "") for p in erg.parts))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
