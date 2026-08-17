#!/usr/bin/env python3
"""Regressionstests: Werkzeug-Schemata im OpenAI-kompatiblen Pfad (2026-08-17).

DER VORFALL (ECHT, Profil ``qwen/qwen3.8-27b`` auf ``191.100.144.3:9081``):
Jeder Chat mit diesem Profil endete mit HTTP 400, und zwar mit EINEM Fehler je
Werkzeug (82 Stueck)::

    "code": "invalid_union_discriminator",
    "path": [0, "function", "parameters", "type"],
    "message": "Invalid discriminator value. Expected 'object'"

Ursache: Die Werkzeuge deklarieren ihr Schema im Gemini-Stil (``"type":
"OBJECT"``, ``"STRING"``) – JSON-Schema verlangt Kleinschreibung.
``_normalize_schema()`` gibt es seit Langem, angewandt wurde es aber NUR im
Anthropic-Zweig; der OpenAI-kompatible Pfad reichte das Schema roh weiter.

Warum es jahrelang niemandem auffiel: vLLM und llama.cpp validieren
Werkzeug-Schemata nicht und nehmen ``OBJECT`` klaglos an (live gegengeprueft:
derselbe Request gegen das vLLM der uebrigen Profile liefert HTTP 200). Erst ein
streng validierender Server – LM Studio prueft mit Zod – lehnt ab. Der Fehler
haengt also am SERVER, nicht am Modell, und trifft jedes kuenftige Profil auf
einem solchen Endpunkt.

Der zweite Teil der Datei haelt die Fehlermeldung fuer ein zu kleines
Kontextfenster fest: LM Studio schreibt "exceeds the available context size",
nicht "context length" – ohne dieses Muster lief der Fall in die rohe
HTTP-400-Meldung, aus der niemand den Grund ablesen kann.

Laeuft ohne fastapi. ``backend.config`` ist ein Stub – der echte Import laeuft
durch die Profil-Migration und schriebe die LIVE-settings.json zurueck.

    python3 tests/test_llm_tool_schema.py
"""
import asyncio
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fail = 0
_ok = 0


def check(cond, label):
    global _fail, _ok
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


# ── Sandkasten-Schranke ─────────────────────────────────────────────────────
# EXIT 2, nicht 1: "der Test konnte gar nicht laufen" muss von "eine Pruefung
# ist fehlgeschlagen" unterscheidbar sein – sonst sieht eine Gegenprobe gegen
# einen alten Stand wie ein normaler Fehlschlag aus.
if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist bereits geladen – der Test wuerde die "
          "echte settings.json anfassen.", file=sys.stderr)
    raise SystemExit(2)

_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = types.SimpleNamespace(
    LLM_TIMEOUT=180, LLM_MAX_TOKENS=8192, LLM_REASONING_EFFORT="",
)
sys.modules["backend.config"] = _cfg_mod

try:
    from backend import llm
except Exception as e:  # google-genai/httpx fehlen
    print(f"ABBRUCH: backend.llm nicht importierbar ({e})", file=sys.stderr)
    raise SystemExit(2)

if not hasattr(llm, "_normalize_schema"):
    print("ABBRUCH: _normalize_schema fehlt – gegen diesen Stand ist der Test "
          "nicht lauffaehig.", file=sys.stderr)
    raise SystemExit(2)

LLM_SRC = (ROOT / "backend" / "llm.py").read_text(encoding="utf-8")


# ── Attrappen ───────────────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._payload is None:
            raise ValueError("kein JSON")
        return self._payload


class FakeClient:
    def __init__(self, resp):
        self.resp = resp
        self.sent = []

    async def post(self, url, headers=None, json=None, timeout=None):
        self.sent.append(json)
        return self.resp


class Part:
    def __init__(self, text):
        self.text = text


class Content:
    def __init__(self, role, text):
        self.role = role
        self.parts = [Part(text)]


class Tool:
    def __init__(self, schema, name="probe", description="Ein Testwerkzeug"):
        self._schema = schema
        self.name = name
        self.description = description

    def parameters_schema(self):
        return self._schema


OK_ANTWORT = {"choices": [{"message": {"role": "assistant", "content": "fertig"}}]}


def sende(tools, antwort=None):
    """Fuehrt einen echten _generate_native-Lauf aus und gibt den Payload zurueck."""
    client = FakeClient(antwort or FakeResp(200, OK_ANTWORT))

    async def _fake_client():
        return client

    orig = llm._get_shared_client
    llm._get_shared_client = _fake_client
    try:
        prov = llm.OpenAICompatibleProvider(api_key="", base_url="http://testhost:9081/v1")
        coro = prov._generate_native("modell", "System", [Content("user", "hallo")], tools, None, None)
        try:
            asyncio.run(coro)
            fehler = None
        except Exception as e:
            fehler = e
    finally:
        llm._get_shared_client = orig
    return (client.sent[0] if client.sent else None), fehler


# ── 1. _normalize_schema ────────────────────────────────────────────────────
print("\n1. _normalize_schema senkt Typen, sonst nichts")
gemini = {
    "type": "OBJECT",
    "properties": {
        "pfad": {"type": "STRING", "description": "Ein Pfad"},
        "modus": {"type": "STRING", "enum": ["AN", "AUS"], "description": "Modus"},
        "liste": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Liste"},
        "tief": {"type": "OBJECT", "properties": {"n": {"type": "INTEGER"}}},
        "matrix": {"type": "ARRAY", "items": {"type": "OBJECT",
                                             "properties": {"x": {"type": "NUMBER"}}}},
    },
    "required": ["pfad"],
}
n = llm._normalize_schema(gemini)
check(n["type"] == "object", "Wurzel: OBJECT -> object")
check(n["properties"]["pfad"]["type"] == "string", "Eigenschaft: STRING -> string")
check(n["properties"]["liste"]["type"] == "array", "ARRAY -> array")
check(n["properties"]["liste"]["items"]["type"] == "string", "items rekursiv")
check(n["properties"]["tief"]["properties"]["n"]["type"] == "integer",
      "verschachtelte properties rekursiv")
check(n["properties"]["matrix"]["items"]["properties"]["x"]["type"] == "number",
      "properties INNERHALB von items rekursiv")
# Der Fallstrick eines naiven .lower() ueber alles: enum-WERTE sind Daten, keine
# Typen. Wer sie mitsenkt, veraendert die Bedeutung der Parameter.
check(n["properties"]["modus"]["enum"] == ["AN", "AUS"], "enum-Werte bleiben unveraendert")
check(n["properties"]["pfad"]["description"] == "Ein Pfad", "Beschreibungen bleiben unveraendert")
check(n["required"] == ["pfad"], "required bleibt unveraendert")
check(gemini["type"] == "OBJECT", "das Original wird NICHT veraendert")
check(llm._normalize_schema("kein dict") == "kein dict", "Nicht-dict wird durchgereicht")
check(llm._normalize_schema({}) == {}, "leeres Schema bleibt leer")
# Kleingeschriebene Schemata (manche Werkzeuge schreiben bereits JSON-Schema)
# duerfen sich nicht veraendern.
klein = {"type": "object", "properties": {"a": {"type": "string"}}}
check(llm._normalize_schema(klein) == klein, "bereits kleingeschrieben: unveraendert")

# ── 2. Der gemeldete Fall im echten Sendeweg ────────────────────────────────
print("\n2. Nativer OpenAI-Pfad sendet JSON-Schema-Typen")
payload, fehler = sende([Tool(gemini)])
check(fehler is None, "Lauf ohne Ausnahme")
check(payload is not None, "Payload wurde gesendet")
fn = payload["tools"][0]["function"]
check(payload["tools"][0]["type"] == "function", "Huelle bleibt type=function")
check(fn["name"] == "probe" and fn["description"] == "Ein Testwerkzeug",
      "Name und Beschreibung unveraendert")
# GENAU DAS hat der Server beanstandet: path [0,"function","parameters","type"]
check(fn["parameters"]["type"] == "object",
      "parameters.type ist 'object' (der beanstandete Pfad)")
check(fn["parameters"]["properties"]["liste"]["items"]["type"] == "string",
      "auch verschachtelte Typen sind gesenkt")

# Kein Typ-Wert darf mehr in Grossschreibung im Payload stehen. Das faengt auch
# Schema-Formen ab, an die _normalize_schema heute nicht denkt.
roh = json.dumps(payload["tools"])
gross = re.findall(r'"type":\s*"([A-Z][A-Za-z_]*)"', roh)
check(not gross, f"kein grossgeschriebener Typ im Payload (gefunden: {gross})")

print("\n2b. Mehrere Werkzeuge, gemischte Schreibweisen")
payload, _ = sende([
    Tool(gemini, name="a"),
    Tool({"type": "object", "properties": {"x": {"type": "string"}}}, name="b"),
    Tool({"type": "OBJECT", "properties": {}}, name="c"),
])
typen = [t["function"]["parameters"]["type"] for t in payload["tools"]]
check(typen == ["object", "object", "object"], f"alle drei -> object ({typen})")

print("\n2c. Werkzeug ohne parameters_schema (Fremd-Tool)")


class FremdTool:
    name = "fremd"
    description = "d"
    parameters = {"type": "OBJECT", "properties": {}}


payload, _ = sende([FremdTool()])
check(payload["tools"][0]["function"]["parameters"]["type"] == "object",
      "auch das Attribut .parameters wird normalisiert")

print("\n2d. Ohne Werkzeuge bleibt der Payload unveraendert")
payload, _ = sende(None)
check("tools" not in payload, "kein tools-Feld ohne Werkzeuge")

# ── 3. Quelltext-Ebene ──────────────────────────────────────────────────────
# Zweite Ebene neben dem Payload-Nachweis: falls jemand den Aufruf entfernt,
# steht hier, WO er hingehoert.
print("\n3. Quelltext")
block = re.search(r'if tools:\s*\n\s*openai_tools = \[\].*?payload\["tools"\] = openai_tools',
                  LLM_SRC, re.S)
check(block is not None, "nativer Werkzeug-Block gefunden")
if block:
    check("_normalize_schema(" in block.group(0),
          "der native Block ruft _normalize_schema")
check(LLM_SRC.count("_normalize_schema(raw_schema)") >= 2,
      "Anthropic- UND OpenAI-Pfad normalisieren (>= 2 Aufrufstellen)")

# ── 4. Kontextfenster: Klartext statt roher HTTP-400-Meldung ────────────────
print("\n4. Zu kleines Kontextfenster wird als solches gemeldet")
LM_STUDIO = ("Engine protocol predict request returned 400: "
             '{"error":{"code":400,"message":"request (23708 tokens) exceeds the '
             'available context size (8192 tokens), try increasing it",'
             '"type":"exceed_context_size_error","n_prompt_tokens":23708,"n_ctx":8192}}')
meldungen = {
    "LM Studio (context size)": {"error": LM_STUDIO},
    "LM Studio (Fehlertyp)": {"error": {"message": "exceed_context_size_error"}},
    "vLLM (max_model_len)": {"error": {"message":
                                       "This model's maximum context length is 8192 tokens"}},
    "OpenAI-Stil (context length)": {"error": {"message": "context length exceeded"}},
}
for label, body in meldungen.items():
    _, fehler = sende([Tool(gemini)], FakeResp(400, body, text=json.dumps(body)))
    txt = str(fehler)
    check(isinstance(fehler, ValueError) and "Kontextfenster" in txt,
          f"{label}: Klartext statt roher Meldung")
    check("HTTP 400 von" not in txt, f"{label}: nicht die generische 400-Meldung")

# Die Server-Meldung muss erhalten bleiben – ohne sie fehlen die Zahlen
# (23708 vs. 8192), und genau die entscheiden, wie gross der Kontext sein muss.
_, fehler = sende([Tool(gemini)], FakeResp(400, {"error": LM_STUDIO}, text=LM_STUDIO))
check("23708" in str(fehler) and "8192" in str(fehler),
      "die Zahlen des Servers stehen in der Meldung")
check("LM Studio" in str(fehler), "die Abhilfe nennt auch LM Studio")

print("\n4b. Ein unbeteiligter 400er bleibt der generische Fehler")
_, fehler = sende([Tool(gemini)], FakeResp(400, {"error": {"message": "model not found"}},
                                           text="model not found"))
check(isinstance(fehler, ValueError) and "HTTP 400 von" in str(fehler),
      "fremder 400er wird nicht als Kontextproblem ausgegeben")

# ── Ergebnis ────────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
