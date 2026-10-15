#!/usr/bin/env python3
"""BSI H10 – die Weiche im ECHTEN Dispatch (agent.py), mit echten Laeufen.

Ergaenzt ``tests/test_bsi_h10.py`` (Grenzen, Namespace, Broker-Op, Werkzeug).
Hier laeuft ``run_task_headless``/``run_task`` mit einem Attrappen-Provider,
der ``shell_execute`` aufruft; das Shell-Werkzeug ist eine Attrappe, die
festhaelt, mit welchen Argumenten der Dispatch es WIRKLICH aufruft – oder ob
er es gar nicht aufruft.

Gemessen:
* Domain-Benutzer: immer Sandbox (auch bei LEERER Einstellung), ohne Internet
  eigener Netz-Namespace, Grenzen gesetzt, privates /tmp verlangt.
* fail-closed: ohne Sandbox-Benutzer oder ohne Lauf-Isolation wird das
  Werkzeug NICHT aufgerufen, das Modell erfaehrt warum.
* Administratoren: Schalter AUS = wie bisher (Root-Broker-Weg, H9-Klick);
  Schalter AN = Sandbox im echten /tmp, Root-Befehle weiter ueber die
  Root-Freigaben, und fehlt die Sandbox, auch fuer sie keine Shell.
* H9: ein Sandbox-Befehl eines Administrators legt KEINE Karte vor, ohne
  Schalter schon (Gegenkontrolle).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

    venv/bin/python tests/test_bsi_h10_dispatch.py
"""
import asyncio
import hashlib
import shutil
import sys
import tempfile
import types as _pytypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n── {t} " + "─" * max(0, 66 - len(t)))


_settings = [p for p in (ROOT / "settings.json", ROOT / "data" / "settings.json") if p.exists()]


def _set_md5():
    return {str(p): hashlib.md5(p.read_bytes()).hexdigest() for p in _settings}


_md5_vorher = _set_md5()
try:
    import backend.agent as A
    from backend.llm import LLMResponse
    from backend import sandbox_grenzen as SG
    from backend import wirkung as W
    from google.genai import types
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.agent nicht ladbar ({type(e).__name__}: {e}) – mit venv/bin/python starten")
    sys.exit(2)

A.JarvisAgent.LLM_PROVIDER = property(lambda self: "openai_compatible")
LT = A._lauf_tmp

SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis_h10d_"))
LT.ARBEIT_ROOT = SANDKASTEN / "arbeit"
LT.ANH_ROOT = SANDKASTEN / "anhaenge"
# Vorfallsliste in den Sandkasten: die gesperrten Werkzeugaufrufe in Abschnitt
# 5 werden als "Grenze" gezaehlt – nicht in data/security_state.json.
from backend import security_guard as _SGD  # noqa: E402
_SGD._STATE_FILE = SANDKASTEN / "security_state.json"
_SGD._STATE_FILE.write_text('{"blocked": {}, "violations": {}}', encoding="utf-8")
if not str(_SGD._STATE_FILE).startswith(str(SANDKASTEN)):
    print("ABBRUCH: Vorfallsliste liegt nicht im Sandkasten")
    sys.exit(2)
if not str(LT.ARBEIT_ROOT).startswith(str(SANDKASTEN)):
    print("ABBRUCH: ARBEIT_ROOT liegt nicht im Sandkasten")
    sys.exit(2)

# Stellschrauben der Umgebung (alles, was sonst root bzw. echte OS-Benutzer
# braucht). Die ENTSCHEIDUNG im Dispatch bleibt echt.
UMG = {"bwrap": True, "uids": {"jarvis_sandbox": 997, "jarvis_sandbox_noinet": 996},
       "admins": False, "einst": {}}
LT.bwrap_verfuegbar = lambda *a, **k: UMG["bwrap"]
SG._uid = lambda n: UMG["uids"].get(n)
SG.auch_admins = lambda: UMG["admins"] is True

_get_echt = A.config.get_setting


def _get(key, default=None):
    if key in ("sandbox_shell_user", "sandbox_shell_user_noinet") or key in SG.EINSTELLUNG.values():
        return UMG["einst"].get(key, default)
    return _get_echt(key, default)


A.config.get_setting = _get


class ShellAttrappe:
    """Steht fuer shell_execute: haelt die Argumente des Dispatch fest."""
    name = "shell_execute"
    description = "Fuehrt einen Shell-Befehl aus"
    supports_streaming = False
    aufrufe = []

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {"command": {"type": "STRING"}}}

    async def execute(self, **kw):
        ShellAttrappe.aufrufe.append(dict(kw))
        return "STDOUT:\nausgefuehrt"


class Stub:
    def __init__(self, folge):
        self.folge = list(folge)
        self.antworten = []

    async def generate_response(self, model=None, system_prompt=None, contents=None,
                                tools=None, **kw):
        for c in contents or []:
            for p in (c.parts or []):
                fr = getattr(p, "function_response", None)
                if fr is not None:
                    self.antworten.append((fr.response or {}).get("result") or "")
        parts = self.folge.pop(0) if self.folge else [types.Part.from_text(text="fertig")]
        return LLMResponse(parts=parts, raw=None, usage={})


class WS:
    def __init__(self, antwort_mit=None):
        self.nachrichten = []
        self.antwort_mit = antwort_mit

    async def send_json(self, m):
        self.nachrichten.append(m)
        if m.get("type") == "bestaetigung_anfrage" and self.antwort_mit is not None:
            benutzer, erlaubt = self.antwort_mit
            asyncio.get_running_loop().call_soon(W.antwort, m["id"], benutzer, self, erlaubt)

    def typen(self):
        return [m.get("type") for m in self.nachrichten]


if "backend.main" not in sys.modules:
    fake = _pytypes.ModuleType("backend.main")
    fake.agent_manager = A.AgentManager()
    sys.modules["backend.main"] = fake
_am = sys.modules["backend.main"].agent_manager
_halter = {"s": None}
A.get_provider = lambda *a, **kw: _halter["s"]

haupt = A.JarvisAgent()
_am.main_agent = haupt
_am.agents[haupt.agent_id] = haupt
_sh = ShellAttrappe()
haupt.tools_map["shell_execute"] = _sh
haupt._tool_instances = [t for t in haupt._tool_instances
                         if getattr(t, "name", "") != "shell_execute"] + [_sh]


LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)


def fc(name, **args):
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def lauf(befehl, *, user, privileged, internet=True, chat_ws=None):
    stub = Stub([[fc("shell_execute", command=befehl)], [types.Part.from_text(text="ok")]])
    _halter["s"] = stub
    haupt.provider = stub
    haupt._user_histories.clear()
    ShellAttrappe.aufrufe = []
    # EINE Event-Loop fuer alle Laeufe: der geteilte Agent bindet seine
    # Ereignisse an die erste Loop, mehrere asyncio.run() messen sonst neben
    # dem eigentlichen Lauf eine Fehlermeldung (Register).
    if chat_ws is not None:
        LOOP.run_until_complete(haupt.run_task("Zeig mir /tmp", chat_ws, username=user,
                                               bestaetigung=True))
    else:
        # Freigabe je Auftrag (BSI H8/H9-Rest, 2026-10-11): gemessen wird hier die
        # WEICHE (Sandbox / Root-Broker), nicht die Freigabe – also ein Auftrag,
        # der nach aussen wirken darf (wie der Auto-Update-Auftrag).
        LOOP.run_until_complete(W.mit_auftrag("Test-Auftrag", True, haupt.run_task_headless(
            "Zeig mir /tmp", actor={
                "user": user, "privileged": privileged, "internet": internet})))
    return list(ShellAttrappe.aufrufe), stub.antworten


def ein(aufrufe):
    return aufrufe[0] if len(aufrufe) == 1 else {}


try:
    auf, antw = lauf("ls /tmp", user="max.muster", privileged=False)
except Exception as e:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    print(f"ABBRUCH: Lauf nicht moeglich: {type(e).__name__}: {e}")
    sys.exit(2)

abschnitt("1. Domain-Benutzer")
pruefe(len(auf) == 1, "Positivkontrolle: der Befehl erreicht das Werkzeug", str(antw)[:120])
k = ein(auf)
pruefe(k.get("_sandbox_user") == "jarvis_sandbox", "laeuft als jarvis_sandbox", str(k)[:160])
pruefe(k.get("_ohne_netz") is False and k.get("_ohne_lauf") is False,
       "mit Internet: Netz bleibt, privates /tmp verlangt")
pruefe(isinstance(k.get("_grenzen"), dict) and set(k["_grenzen"]) == set(SG.STANDARD),
       "Grenzen gehen mit", str(k.get("_grenzen")))
pruefe(not k.get("_root_broker"), "kein Root-Broker-Weg fuer Domain-Benutzer")

UMG["einst"] = {"sandbox_shell_user": "", "sandbox_shell_user_noinet": ""}
auf, _ = lauf("ls /tmp", user="max.muster", privileged=False)
pruefe(ein(auf).get("_sandbox_user") == "jarvis_sandbox",
       "LEERE Einstellung schaltet die Sandbox NICHT ab (Befund H10: 'optional')", str(auf)[:120])
auf, _ = lauf("ls /tmp", user="max.muster", privileged=False, internet=False)
k = ein(auf)
pruefe(k.get("_sandbox_user") == "jarvis_sandbox_noinet" and k.get("_ohne_netz") is True,
       "ohne Internet: netzgesperrter Benutzer UND eigener Netz-Namespace", str(k)[:160])
UMG["einst"] = {}

abschnitt("2. fail-closed")
UMG["uids"] = {}
auf, antw = lauf("ls /tmp", user="max.muster", privileged=False)
pruefe(auf == [], "kein Sandbox-Benutzer -> Werkzeug wird NICHT aufgerufen", str(auf)[:120])
pruefe(any("NICHT ausgeführt" in a for a in antw), "das Modell erfaehrt warum", str(antw)[:160])
UMG["uids"] = {"jarvis_sandbox": 997, "jarvis_sandbox_noinet": 996}

UMG["bwrap"] = False
auf, antw = lauf("ls /tmp", user="max.muster", privileged=False)
pruefe(auf == [], "keine Lauf-Isolation (bwrap fehlt) -> Werkzeug wird NICHT aufgerufen "
                  "(frueher: gemeinsames /tmp)", str(auf)[:120])
pruefe(any("privates /tmp" in a for a in antw), "Grund nennt die fehlende Isolation", str(antw)[:160])
UMG["bwrap"] = True
auf, _ = lauf("ls /tmp", user="max.muster", privileged=False)
pruefe(len(auf) == 1, "Gegenkontrolle: mit Isolation laeuft derselbe Befehl wieder")

abschnitt("3. Administratoren")
UMG["admins"] = False
auf, _ = lauf("ls /tmp", user="jarvis", privileged=True)
k = ein(auf)
pruefe(len(auf) == 1 and not k.get("_sandbox_user") and k.get("_root_broker") is True,
       "Schalter AUS: wie bisher (Dienstbenutzer, Root-Broker-Weg)", str(k)[:160])

UMG["admins"] = True
auf, _ = lauf("ls /tmp", user="jarvis", privileged=True)
k = ein(auf)
pruefe(k.get("_sandbox_user") == "jarvis_sandbox" and k.get("_ohne_lauf") is True,
       "Schalter AN: Sandbox im echten /tmp (ausdruecklich angefordert)", str(k)[:160])
pruefe(not k.get("_root_broker"), "Schalter AN: kein paralleler Root-Broker-Weg")
auf, _ = lauf("systemctl restart cups", user="jarvis", privileged=True)
k = ein(auf)
pruefe(len(auf) == 1 and not k.get("_sandbox_user") and k.get("_root_broker") is True,
       "Schalter AN, Root-Befehl: weiter ueber die Root-Freigaben", str(k)[:160])
UMG["uids"] = {}
auf, antw = lauf("ls /tmp", user="jarvis", privileged=True)
pruefe(auf == [] and any("NICHT ausgeführt" in a for a in antw),
       "Schalter AN, aber keine Sandbox: auch fuer Administratoren keine Shell", str(antw)[:120])
UMG["uids"] = {"jarvis_sandbox": 997, "jarvis_sandbox_noinet": 996}

abschnitt("4. Zusammenspiel mit H9 (Klick)")
_frist = W.FRIST_S
W.FRIST_S = 5
try:
    UMG["admins"] = False
    ws = WS(("jarvis", False))
    auf, _ = lauf("ls /tmp", user="jarvis", privileged=True, chat_ws=ws)
    pruefe("bestaetigung_anfrage" in ws.typen() and auf == [],
           "Gegenkontrolle: Schalter AUS -> Admin-Shell legt eine Karte vor (abgelehnt, nicht ausgefuehrt)",
           str(ws.typen()))
    UMG["admins"] = True
    ws = WS(("jarvis", False))
    auf, _ = lauf("ls /tmp", user="jarvis", privileged=True, chat_ws=ws)
    pruefe("bestaetigung_anfrage" not in ws.typen() and len(auf) == 1,
           "Schalter AN -> Sandbox-Befehl ohne Karte (Wirkung eingeschlossen)", str(ws.typen()))
finally:
    W.FRIST_S = _frist
    UMG["admins"] = False

abschnitt("5. Desktop/Browser: kein Weg am Sandbox-Benutzer vorbei")


class WerkzeugAttrappe:
    aufrufe = []

    def __init__(self, name):
        self.name = name
        self.description = name

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {"action": {"type": "STRING"}}}

    async def execute(self, **kw):
        WerkzeugAttrappe.aufrufe.append(self.name)
        return "ausgefuehrt"


for _n in ("desktop_control", "browser_control", "browser_cdp"):
    _w = WerkzeugAttrappe(_n)
    haupt.tools_map[_n] = _w
    haupt._tool_instances = [t for t in haupt._tool_instances if getattr(t, "name", "") != _n] + [_w]


def werkzeug_lauf(name, *, user, privileged):
    stub = Stub([[fc(name, action="type_text")], [types.Part.from_text(text="ok")]])
    _halter["s"] = stub
    haupt.provider = stub
    haupt._user_histories.clear()
    WerkzeugAttrappe.aufrufe = []
    LOOP.run_until_complete(haupt.run_task_headless("Tippe etwas", actor={
        "user": user, "privileged": privileged, "internet": True}))
    return list(WerkzeugAttrappe.aufrufe), stub.antworten


for _n in ("desktop_control", "browser_control", "browser_cdp"):
    auf, antw = werkzeug_lauf(_n, user="jarvis", privileged=True)
    pruefe(auf == [_n], f"Gegenkontrolle: Administrator darf {_n}", str(auf))
    auf, antw = werkzeug_lauf(_n, user="max.muster", privileged=False)
    pruefe(auf == [], f"Domain-Benutzer: {_n} wird NICHT ausgefuehrt", str(auf))
with haupt.actor_scope("max.muster", privileged=False):
    angebot = {t.name for t in haupt._llm_tools}
pruefe(not angebot & {"desktop_control", "browser_control", "browser_cdp"},
       "Domain-Benutzer bekommen die drei Werkzeuge gar nicht erst angeboten",
       str(angebot & {"desktop_control", "browser_control", "browser_cdp"}))

A.config.get_setting = _get_echt
shutil.rmtree(SANDKASTEN, ignore_errors=True)
pruefe(_set_md5() == _md5_vorher, "settings.json unveraendert (keine Live-Konfiguration angefasst)")
print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 and _ok > 0 else 1)
