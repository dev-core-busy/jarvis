#!/usr/bin/env python3
"""Waechter: Agenten-Kern ohne geteilte Lauf-Reste (Code-Review 2026-10-18).

ECHTE ``run_task``-Laeufe mit Attrappen-Provider (echte Signatur, zaehlt
Aufrufe) und Attrappen-Werkzeugen am Hauptagenten:
  [1] Auto-Learning zaehlt nur DIESEN Lauf: ein Fehlschlag in einem frueheren
      Lauf loest im naechsten keinen zusaetzlichen LLM-Aufruf aus.
  [2] Der Lern-Hinweis landet NICHT im persistenten Verlauf, und die Aufgabe
      steht im Lern-Aufruf nicht doppelt.
  [3] Kein Werkzeug-Cache: ein zweiter "screenshot" liefert frische Daten.
Importiert backend.agent (und backend.config) – Live-settings.json wird per
md5 verglichen. Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import asyncio
import hashlib
import sys
import types as _pytypes
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


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


_settings = [p for p in (ROOT / "settings.json", ROOT / "data" / "settings.json") if p.exists()]
_md5 = lambda: {str(p): hashlib.md5(p.read_bytes()).hexdigest() for p in _settings}  # noqa: E731
_vorher = _md5()
try:
    import backend.agent as A
    from backend.llm import LLMResponse
    from backend.tools.base import BaseTool
    from google.genai import types
except Exception as e:  # noqa: BLE001
    abbruch("backend.agent nicht importierbar (venv?): %s" % e)

if "backend.main" not in sys.modules:
    fake = _pytypes.ModuleType("backend.main")
    fake.agent_manager = A.AgentManager()
    sys.modules["backend.main"] = fake
haupt = A.JarvisAgent()
A.JarvisAgent.LLM_PROVIDER = property(lambda self: "openai_compatible")


class Werkzeug(BaseTool):
    parameters_schema = {"type": "object", "properties": {}}
    description = "Probe"

    def __init__(self, name, antworten):
        self._name = name
        self.antworten = list(antworten)
        self.aufrufe = 0

    @property
    def name(self):
        return self._name

    async def execute(self, **kw):
        self.aufrufe += 1
        return self.antworten.pop(0) if self.antworten else "ok"


class Stub:
    def __init__(self, folge):
        self.folge = list(folge)
        self.aufrufe = []
        self.hintergrund = 0

    async def generate_response(self, model=None, system_prompt=None, contents=None, tools=None, **kw):
        texte = [" ".join(p.text for p in (c.parts or []) if getattr(p, "text", None))
                 for c in (contents or [])]
        # Das Hintergrund-Lernen (backend/learning.py) laeuft unabhaengig vom
        # Auto-Learning und wird getrennt gezaehlt.
        if texte and texte[0].startswith("Analysiere die folgenden"):
            self.hintergrund += 1
        else:
            self.aufrufe.append(texte)
        parts = self.folge.pop(0) if self.folge else [types.Part.from_text(text="Fertig.")]
        return LLMResponse(parts=parts, raw=None, usage={})


class WS:
    async def send_json(self, m):
        pass


def fc(name):
    return types.Part(function_call=types.FunctionCall(name=name, args={}))


def lauf(stub, text="Aufgabe XYZ123"):
    A.get_provider = lambda *a, **kw: stub
    haupt.provider = stub
    asyncio.run(haupt.run_task(text, WS(), username="jarvis"))


mem = Werkzeug("memory_manage", [])
haupt.tools_map["memory_manage"] = mem
haupt._werkzeug_nutzbar = lambda name: name in haupt.tools_map
probe = Werkzeug("probe_werkzeug", ["❌ Fehler: geht nicht", "ok", "ok", "ok", "ok", "ok"])
haupt.tools_map["probe_werkzeug"] = probe

try:
    print("\n[1] Auto-Learning je Lauf")
    s1 = Stub([[fc("probe_werkzeug")], [fc("probe_werkzeug")], [types.Part.from_text(text="Erledigt.")]])
    haupt._user_histories.clear()
    lauf(s1)
    check("(Positivkontrolle) Lauf mit Fehlschlag + Erfolg: Lern-Aufruf findet statt (4 Aufrufe)",
          len(s1.aufrufe) == 4, str(len(s1.aufrufe)))
    if FAIL:
        abbruch("Messaufbau traegt nicht")
    s2 = Stub([[fc("probe_werkzeug")], [fc("probe_werkzeug")], [types.Part.from_text(text="Erledigt.")]])
    lauf(s2, "Andere Aufgabe ABC")
    check("naechster Lauf OHNE eigenen Fehlschlag: KEIN Lern-Aufruf (3 Aufrufe)", len(s2.aufrufe) == 3,
          str(len(s2.aufrufe)))

    print("\n[2] Lern-Hinweis nicht im Verlauf")
    lern = s1.aufrufe[-1]
    check("Lern-Aufruf traegt den Hinweis", any("AUTO-LEARNING" in t for t in lern))
    check("Aufgabe im Lern-Aufruf nicht doppelt", sum(t.count("Aufgabe XYZ123") for t in lern) <= 1,
          str(sum(t.count("Aufgabe XYZ123") for t in lern)))
    verlauf = " ".join(t for a in s2.aufrufe for t in a)
    check("der Hinweis steht im Folgelauf NICHT im Verlauf", "AUTO-LEARNING" not in verlauf)

    print("\n[3] kein Werkzeug-Cache")
    shot = Werkzeug("screenshot", ["BILD-1", "BILD-2"])
    haupt.tools_map["screenshot"] = shot
    s3 = Stub([[fc("screenshot")], [fc("screenshot")], [types.Part.from_text(text="Fertig.")]])
    haupt._user_histories.clear()
    lauf(s3, "Zwei Bilder")
    check("zweiter screenshot laeuft wirklich (2 Aufrufe)", shot.aufrufe == 2, str(shot.aufrufe))
    print("\n[4] Stop-Scopes")
    s_a1, s_a2, s_b = A._StopScope(), A._StopScope(), A._StopScope()
    haupt._stop_scopes.clear()
    haupt._stop_scopes.setdefault("alice", set()).update({s_a1, s_a2})
    haupt._stop_scopes.setdefault("bob", set()).add(s_b)
    haupt.stop(username="FIRMA\\Alice")
    check("Stopp eines Benutzers trifft ALLE seine Laeufe (zwei Tabs)",
          s_a1.event.is_set() and s_a2.event.is_set())
    check("... und nicht den Lauf eines anderen", not s_b.event.is_set())

    class Blockiert:
        def __init__(self):
            self.gestartet = asyncio.Event()

        async def generate_response(self, **kw):
            self.gestartet.set()
            await asyncio.sleep(30)

    async def headless_mit_stopp():
        sb = Blockiert()
        A.get_provider = lambda *a, **kw: sb
        haupt.provider = sb
        anderer = A._StopScope()
        anderer.event.set()                      # ein laufendes stop_all fuer jemand anderen
        haupt._stop_scopes.setdefault("carol", set()).add(anderer)
        t = asyncio.ensure_future(haupt._run_headless("Warte"))
        await asyncio.wait_for(sb.gestartet.wait(), 10)
        check("headless-Start hebt einen fremden Stopp NICHT auf", anderer.event.is_set())
        t0 = asyncio.get_running_loop().time()
        haupt.stop()
        await asyncio.wait_for(t, 10)
        return asyncio.get_running_loop().time() - t0
    dauer = asyncio.run(headless_mit_stopp())
    check("Voll-Stopp beendet einen headless-Lauf (%.2f s)" % dauer, dauer < 5)
    check("der headless-Scope ist danach abgeraeumt",
          not any(k.startswith("_headless:") for k in haupt._stop_scopes), str(list(haupt._stop_scopes)))
    print("\n[5] Lauf-Kontext: zwei gleichzeitige Laeufe am geteilten Agenten")
    gesehen = {}

    class Rechte(Werkzeug):
        async def execute(self, **kw):
            await asyncio.sleep(0.2)          # der andere Lauf schreibt dazwischen
            gesehen[haupt._current_username] = (haupt._current_user_sap, haupt._current_user_internet)
            return "ok"

    haupt.tools_map["rechte_probe"] = Rechte("rechte_probe", [])

    class Langsam(Stub):
        async def generate_response(self, **kw):
            await asyncio.sleep(0.05)
            return await super().generate_response(**kw)

    async def zwei():
        sa = Langsam([[fc("rechte_probe")], [types.Part.from_text(text="A fertig")]])
        sb = Langsam([[fc("rechte_probe")], [types.Part.from_text(text="B fertig")]])
        anbieter = {"alice": sa, "bob": sb}
        A.get_provider = lambda *a, **kw: anbieter.get(haupt._current_username, sa)
        haupt._current_user_sap = "INSTANZ"          # Wert ausserhalb jedes Laufs
        ta = asyncio.ensure_future(haupt.run_task(
            "A", WS(), username="alice", rechte={"_current_user_sap": False, "_current_user_internet": False}))
        await asyncio.sleep(0.01)
        tb = asyncio.ensure_future(haupt.run_task(
            "B", WS(), username="bob", rechte={"_current_user_sap": True, "_current_user_internet": True}))
        await asyncio.gather(ta, tb)

    asyncio.run(zwei())
    check("(Positivkontrolle) beide Laeufe erreichten das Werkzeug", set(gesehen) == {"alice", "bob"}, str(gesehen))
    check("alice sieht IHRE Rechte (kein SAP), obwohl bob danach startete",
          gesehen.get("alice") == (False, False), str(gesehen.get("alice")))
    check("bob sieht seine Rechte", gesehen.get("bob") == (True, True), str(gesehen.get("bob")))
    check("der Wert an der Instanz bleibt vom Lauf unberuehrt", haupt._current_user_sap == "INSTANZ")
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    check("Laeufe ausfuehrbar", False, "%s: %s" % (type(e).__name__, e))

check("Live-settings.json unveraendert", _md5() == _vorher)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
