"""Pruefstand fuer den ECHTEN Werkzeug-Dispatch (``JarvisAgent._execute_tool``).

Fuer die Pentest-Waechter C1/C2/C5/C6 (2026-11-05). ``backend.config`` wird
NIE echt importiert (der Import migriert Profile und schreibt die Live-
settings.json zurueck): vor dem Import von ``backend.agent`` steht eine
Attrappe in ``sys.modules``. ``backend.main`` ebenso – der echte Import laedt
die ganze App; die Werkzeuge fragen dort nur ``_is_admin_user`` /
``_may_edit_knowledge`` ab, und die Attrappe beantwortet das aus zwei Mengen.

Der Agent entsteht OHNE Konstruktor (der baut einen LLM-Client und braucht
einen Schluessel); gesetzt werden genau die Attribute, die ``_execute_tool``
liest. Fehlt eines, stirbt der Lauf mit AttributeError – und der Waechter
bricht dann mit Exit 2 ab, nicht mit einem FAIL.
"""

import sys
import types
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent.parent
if str(WURZEL) not in sys.path:
    sys.path.insert(0, str(WURZEL))


class CfgAttrappe:
    """Nur was die gepruefte Strecke liest: get/save_setting, Skill-Zustaende."""

    def __init__(self):
        self.s = {}
        self.profiles = []
        self.active_profile = None
        self.skill_states = {}

    def get_setting(self, k, d=None):
        return self.s.get(k, d)

    def save_setting(self, k, v):
        self.s[k] = v

    def get_skill_states(self):
        return self.skill_states

    def save_skill_state(self, name, state):
        self.skill_states[name] = state

    def profile_for_user(self, _u):
        return None

    def __getattr__(self, n):
        if n.isupper():
            return ""
        raise AttributeError(n)


CFG = CfgAttrappe()
_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = CFG
sys.modules["backend.config"] = _cfg_mod

ADMINS: set = set()
EDITOREN: set = set()
_main = types.ModuleType("backend.main")
_main._is_admin_user = lambda u: (u or "") in ADMINS
_main._may_edit_knowledge = lambda u: (u or "") in EDITOREN
sys.modules["backend.main"] = _main

import backend.agent as A  # noqa: E402
from backend.tools.base import BaseTool  # noqa: E402


class Aufzeichner(BaseTool):
    """Werkzeug, das jeden Aufruf mit seinen Schluesselwort-Argumenten merkt."""

    def __init__(self, name, antwort="ok"):
        self._n = name
        self._antwort = antwort
        self.aufrufe = []

    @property
    def name(self):
        return self._n

    @property
    def description(self):
        return ""

    def parameters_schema(self):
        return {"type": "object", "properties": {}}

    async def execute(self, **kw):
        self.aufrufe.append(dict(kw))
        return self._antwort


def agent(werkzeuge, benutzer="anna.beispiel", privilegiert=False):
    """Agent ohne Konstruktor mit genau diesen Werkzeugen."""
    a = object.__new__(A.JarvisAgent)
    a.agent_id = "pruef"
    a.tools_map = {w.name: w for w in werkzeuge}
    a.skill_manager = types.SimpleNamespace(is_tool_readonly=lambda n: False)
    a._current_username = benutzer
    a._current_actor_privileged = privilegiert
    # Fuer _send_status (Statusmeldungen an eine WS-Attrappe).
    a.state = A.AgentState.IDLE
    a.label = "Pruefstand"
    a.is_sub_agent = False
    return a
