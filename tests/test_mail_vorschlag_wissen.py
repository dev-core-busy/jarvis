#!/usr/bin/env python3
"""Waechter: Wissensdatenbank beim Antwortvorschlag (2026-11-05).

Zusage: der Antwortvorschlag des Outlook-Add-ins bekommt GENAU dann die
lesende Wissenssuche (``knowledge_search``) und SONST NICHTS, wenn der
Administrator unter Einstellungen → E-Mail den Bereich ``wissen`` freigegeben
hat. Ohne Freigabe bleibt der Lauf werkzeuglos. Mail-, Sende- und
Schreibwerkzeuge kommen nie dazu – auch nicht, wenn ``voll``, ``fach`` oder
``adressbuch`` freigegeben sind. Der Vorschlag meldet, ob die Datenbank zur
Verfuegung stand und wie oft sie WIRKLICH befragt wurde (gezaehlt ueber den
Beobachter-Haken des Agenten, nicht vermutet).

Gemessen wird WIRKUNG: ``antwort_vorschlag`` laeuft ganz durch, eine
Agent-Attrappe mit der ECHTEN Signatur haelt fest, welchen Zuschnitt und
welchen Auftrag sie bekommt, und ruft den Haken so, wie ``_execute_tool`` es
tut (``hook(name, args)``).

``backend.config`` ist eine Attrappe (der echte Import schreibt die Live-
``settings.json``). Austauschdatei fuer die Gegenprobe: WV_RUNNER.
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_mail_vorschlag_wissen.py
"""
import ast
import asyncio
import importlib.util
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


RUNNER = Path(os.environ.get("WV_RUNNER") or ROOT / "backend/mail_runner.py")
TMP = Path(tempfile.mkdtemp(prefix="mail_wissen_test_"))
_skill_states = {"email": {"enabled": True, "config": {"bereiche": "mail"}}}
_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return _skill_states

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod


class _StubAgent:
    """Attrappe mit der Signatur von ``JarvisAgent.run_task_headless``."""
    laeufe = []
    werkzeugaufrufe = []        # (name, args), die der "Lauf" macht

    def __init__(self, label=""):
        self._role_tools = None
        self._schritt_hook = None

    async def run_task_headless(self, auftrag, actor=None, reasoning_effort=None, **kw):
        _StubAgent.laeufe.append({"auftrag": auftrag,
                                  "werkzeuge": self._role_tools,
                                  "actor": actor})
        # Wie agent._execute_tool: die harte Schranke VOR dem Haken.
        for name, args in _StubAgent.werkzeugaufrufe:
            erlaubt = self._role_tools
            if erlaubt is not None and name not in erlaubt:
                continue
            hook = getattr(self, "_schritt_hook", None)
            if hook is not None:
                hook(name, args)
        return "Sehr geehrter Kunde,\nvielen Dank.\nGruss"


sys.modules["backend.agent"] = types.ModuleType("backend.agent")
sys.modules["backend.agent"].JarvisAgent = _StubAgent


def _laden(name, pfad):
    spec = importlib.util.spec_from_file_location(name, pfad)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    import backend  # noqa: F401
    from backend import mail_accounts as ma
    from backend import mail_rules as mr
    mrun = _laden("backend.mail_runner", RUNNER)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Module nicht ladbar: {e}")
    sys.exit(2)

ma.DATA_DIR = TMP
ma.KONTEN_DATEI = TMP / "email_accounts.json"
ma.SCHLUESSEL_DATEI = TMP / ".mailkey"
mr.DATA_DIR = TMP
mr.REGEL_DATEI = TMP / "email_rules.json"
mr.ZUSTAND_DATEI = TMP / "email_state.json"
mr.PROTOKOLL_DATEI = TMP / "email_log.jsonl"
for pf in (ma.KONTEN_DATEI, ma.SCHLUESSEL_DATEI, mr.REGEL_DATEI, mr.PROTOKOLL_DATEI):
    if not str(pf).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {pf}")
        sys.exit(2)
ma.KONTEN_DATEI.write_text("{}", encoding="utf-8")


async def _keine_pruefung(*a, **kw):
    return None


mrun._injektion_pruefen = _keine_pruefung
# Stelligkeit wie an den Aufrufstellen (siehe test_mail_styles): drei Werte.
mrun._rechte = lambda owner: (False, False, False)

NACHRICHT = {"von": "kunde@beispiel.de", "von_name": "Kunde", "betreff": "Frage",
             "datum": "2026-11-05", "text": "Wie richte ich die Schnittstelle ein?"}
SENTINEL = object()


def bereiche(wert):
    _skill_states["email"]["config"]["bereiche"] = wert


def vorschlag(aufrufe=()):
    mrun._agent = None
    _StubAgent.laeufe = []
    _StubAgent.werkzeugaufrufe = list(aufrufe)
    agent = _StubAgent()
    agent._schritt_hook = SENTINEL
    mrun._agent = agent
    d = asyncio.run(mrun.antwort_vorschlag("m.mustermann", stil_id=ma.STIL_KEINER,
                                           nachricht=dict(NACHRICHT),
                                           postfach="m.mustermann@beispiel.de"))
    return d, agent


def lauf_oder_fail(label, aufrufe=()):
    """Ein Lauf, dessen Absturz ein FAIL ist und kein Abbruch ohne Bilanz.

    Eine Sabotage wie "voll heisst keine Schranke" (Rueckgabe None) wirft im
    Lauf – ohne diese Klammer endete der Waechter ohne Bilanzzeile, und das ist
    von "konnte nicht laufen" nicht zu unterscheiden."""
    try:
        return vorschlag(aufrufe)
    except Exception as e:  # noqa: BLE001
        check(False, label + ": Lauf scheitert", f"{type(e).__name__}: {e}")
        return None, None


# ═══════════════════════════════════════════════════════════════════════════
section("0. Positivkontrolle: der Lauf erreicht den Agenten")
# ═══════════════════════════════════════════════════════════════════════════
bereiche("mail")
try:
    d0, a0 = vorschlag()
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: antwort_vorschlag nicht lauffaehig ({type(e).__name__}: {e})")
    sys.exit(2)
if len(_StubAgent.laeufe) != 1 or not d0.get("text"):
    print(f"ABBRUCH: kein Agentenlauf gemessen ({len(_StubAgent.laeufe)})")
    sys.exit(2)
check(True, "ein Lauf, Text kommt zurueck")

# ═══════════════════════════════════════════════════════════════════════════
section("1. Zuschnitt aus der Freigabe")
# ═══════════════════════════════════════════════════════════════════════════
FALL = [
    ("nur mail", "mail", set()),
    ("ohne Feld", None, set()),
    ("mail + wissen", "mail,wissen", {"knowledge_search"}),
    ("alles frei (voll, fach, adressbuch, dokumente, wissen)",
     "mail,voll,fach,adressbuch,dokumente,wissen", {"knowledge_search"}),
    ("alles frei AUSSER wissen", "mail,voll,fach,adressbuch,dokumente", set()),
]
for name, wert, soll in FALL:
    if wert is None:
        _skill_states["email"]["config"].pop("bereiche", None)
    else:
        bereiche(wert)
    ist = mrun.vorschlag_werkzeuge()
    check(ist is not None and set(ist) == soll, f"{name}: {sorted(soll) or 'keine Werkzeuge'}",
          repr(ist))

_echt = mr.freigegebene_bereiche


def _wirft():
    raise RuntimeError("Konfiguration nicht lesbar")


mr.freigegebene_bereiche = _wirft
try:
    ist = mrun.vorschlag_werkzeuge()
    check(ist == set(), "Konfigurationsfehler: keine Werkzeuge (fail-closed)", repr(ist))
except Exception as e:  # noqa: BLE001
    check(False, "Konfigurationsfehler: keine Werkzeuge (fail-closed)", f"wirft {e}")
finally:
    mr.freigegebene_bereiche = _echt

# ═══════════════════════════════════════════════════════════════════════════
section("2. Lauf OHNE Freigabe: werkzeuglos, kein Wissensabschnitt")
# ═══════════════════════════════════════════════════════════════════════════
bereiche("mail,voll,fach")
d, a = lauf_oder_fail("ohne Freigabe", [("knowledge_search", {"query": "x"})])
if d is not None:
    lauf = _StubAgent.laeufe[0]
    check(lauf["werkzeuge"] == set() and lauf["werkzeuge"] is not None,
        "der Agent bekommt die LEERE Menge (nicht None)", repr(lauf["werkzeuge"]))
    check("knowledge_search" not in lauf["auftrag"],
        "der Auftrag nennt das Werkzeug nicht (ein Prompt ist Code)")
    check(d.get("wissen") is False and d.get("wissen_suchen") == 0,
        "Rueckmeldung: wissen=False, 0 Suchen", f"{d.get('wissen')!r}/{d.get('wissen_suchen')!r}")

# ═══════════════════════════════════════════════════════════════════════════
section("3. Lauf MIT Freigabe: nur die Wissenssuche, gezaehlt")
# ═══════════════════════════════════════════════════════════════════════════
bereiche("mail,wissen,voll,adressbuch")
d, a = lauf_oder_fail("mit Freigabe", [("knowledge_search", {"query": "Schnittstelle"}),
                  ("email_senden", {"an": "x@beispiel.de"}),
                  ("knowledge_search", {"query": "Einrichtung"})])
if d is None:
    print("\n" + "=" * 46)
    print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
    sys.exit(1)
lauf = _StubAgent.laeufe[0]
check(lauf["werkzeuge"] == {"knowledge_search"},
      "der Agent bekommt GENAU die Wissenssuche", repr(lauf["werkzeuge"]))
check("WISSENSDATENBANK" in lauf["auftrag"] and "knowledge_search" in lauf["auftrag"],
      "der Auftrag erklaert die Wissenssuche")
_vor = lauf["auftrag"].split("EINGEGANGENE NACHRICHT", 1)[0]
check("WISSENSDATENBANK" in _vor,
      "der Wissensabschnitt steht VOR dem Fremdtext (nicht darin)")
check(d.get("wissen") is True, "Rueckmeldung: wissen=True", repr(d.get("wissen")))
check(d.get("wissen_suchen") == 2,
      "gezaehlt werden genau die Wissenssuchen (2), kein fremdes Werkzeug",
      repr(d.get("wissen_suchen")))
check(lauf["actor"] and lauf["actor"].get("privileged") is False,
      "der Lauf bleibt unprivilegiert")

# ═══════════════════════════════════════════════════════════════════════════
section("4. Nach dem Lauf ist der geteilte Agent wieder sauber")
# ═══════════════════════════════════════════════════════════════════════════
check(a._role_tools is None, "Zuschnitt zurueckgesetzt", repr(a._role_tools))
check(a._schritt_hook is SENTINEL, "Beobachter-Haken auf den Vorzustand zurueckgestellt",
      repr(a._schritt_hook))

# ═══════════════════════════════════════════════════════════════════════════
section("5. Regel am Syntaxbaum: kein Regel-Zuschnitt im Vorschlag")
# ═══════════════════════════════════════════════════════════════════════════
baum = ast.parse(RUNNER.read_text(encoding="utf-8"))
fn = next((n for n in ast.walk(baum)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "antwort_vorschlag"), None)
if fn is None:
    print("ABBRUCH: antwort_vorschlag nicht gefunden")
    sys.exit(2)
namen = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | \
        {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
for verboten in ("werkzeuge_fuer", "MAIL_WERKZEUGE", "BEREICHE"):
    check(verboten not in namen,
          f"antwort_vorschlag benutzt {verboten} nicht (der Regel-Zuschnitt zieht Mail mit)")

print("\n" + "=" * 46)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
