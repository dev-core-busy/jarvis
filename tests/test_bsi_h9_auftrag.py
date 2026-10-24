#!/usr/bin/env python3
"""Waechter BSI H8/H9-Rest: Freigabe je Auftrag fuer Laeufe ohne Oberflaeche.

Betreiberentscheid 2026-10-11 („Freigabe je Auftrag"): Laeufe ohne Oberflaeche
(Cron, Dateiwaechter, Mail-Regeln, Telegram, WhatsApp, Agent-API) fuehren
Aktionen mit Aussen-/Loeschwirkung nur noch aus, wenn der Auftrag, die Regel
bzw. der Kanal sie ausdruecklich erlaubt. Ohne jeden Auftrag: abgewiesen
(fail-closed). Bestand behaelt sein Verhalten (einmalig festgeschrieben).

Gemessen wird:
  1. der Kern (backend/wirkung.py) WIRKLICH ausgefuehrt: freigabe() mit und ohne
     Auftrag, Vererbung in Kind-Tasks, ein Chat-Kanal bleibt vorrangig;
  2. die Bestands-Festschreibung WIRKLICH ausgefuehrt – Messenger, Agent-API,
     Cron, Trigger, Mail-Regeln – in einem Sandkasten;
  3. als REGEL ueber den Syntaxbaum: JEDER run_task_headless-Aufruf in backend/
     und skills/ setzt einen Auftrag – oder steht mit Begruendung in AUSNAHMEN
     und hat dort eine Werkzeug-Positivliste. Ein neuer Einstieg faellt damit
     von selbst auf.

Lauf:  python3 tests/test_bsi_h9_auftrag.py
"""
import ast
import asyncio
import re
import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        fail += 1
        print(f"  ❌ {name}" + (f" – {detail}" if detail else ""))


# ── Attrappen: backend.config (NIE echt – schreibt sonst die Live-settings.json),
#    apscheduler und watchdog (lokal nicht installiert, fuer den Test belanglos)
EINST, SKILLS = {}, {}


class _Cfg:
    def get_setting(self, k, d=None):
        return EINST.get(k, d)

    def save_setting(self, k, v):
        EINST[k] = v

    def get_skill_states(self):
        return SKILLS

    def save_skill_state(self, name, state):
        SKILLS[name] = state


_cfgmod = types.ModuleType("backend.config")
_cfgmod.config = _Cfg()
_cfgmod.PROJECT_ROOT = ROOT
sys.modules["backend.config"] = _cfgmod


class _Leer:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return lambda *a, **k: None


def _stubmodul(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


for n in ("apscheduler", "apscheduler.schedulers", "apscheduler.triggers"):
    _stubmodul(n)
_stubmodul("apscheduler.schedulers.asyncio", AsyncIOScheduler=_Leer)
_stubmodul("apscheduler.triggers.cron",
           CronTrigger=type("CronTrigger", (), {"from_crontab": staticmethod(lambda *a, **k: None)}))
_stubmodul("watchdog")
_stubmodul("watchdog.events", FileSystemEventHandler=object, FileCreatedEvent=object,
           FileModifiedEvent=object, FileDeletedEvent=object, FileMovedEvent=object)
_stubmodul("watchdog.observers", Observer=_Leer)

try:
    from backend import wirkung as W
except Exception as ex:  # noqa: BLE001
    print(f"ABBRUCH: backend.wirkung nicht ladbar: {ex}")
    sys.exit(2)
for name in ("Auftrag", "auftrag", "auftrag_cv", "mit_auftrag", "kanal_freigabe",
             "agent_api_freigabe", "bestand_festschreiben", "hinweis_ohne_freigabe"):
    if not hasattr(W, name):
        print(f"ABBRUCH: wirkung.{name} fehlt – Stand vor der Freigabe je Auftrag?")
        sys.exit(2)


async def frei(name="email_senden", klasse="aussen"):
    # Vierter Parameter = der Satz, der ausgefuehrt wuerde (im Dispatch eine
    # Kopie von args, die VOR der Freigabe entsteht). Hier gibt es keine Karte
    # und damit keine Korrekturen – Pflicht ist er trotzdem, damit ein
    # Aufrufer ihn nicht vergessen kann.
    args = {"an": "x@beispiel.de"}
    return await W.freigabe(name, args, klasse, dict(args))


print("\n1. Kern: Laeufe ohne Oberflaeche")


async def teil1():
    check("Positivkontrolle: kein Kanal gesetzt", W.kanal_cv.get() is None)
    r = await frei()
    check("⚠ ohne jeden Auftrag: abgewiesen (fail-closed)",
          isinstance(r, str) and r.startswith("NICHT AUSGEFÜHRT"), str(r)[:80])
    with W.auftrag("Cron-Auftrag 'Bericht'", False):
        r = await frei()
        check("Auftrag ohne Freigabe: abgewiesen", isinstance(r, str) and "NICHT" in r)
        check("… die Meldung nennt den Auftrag", "Cron-Auftrag 'Bericht'" in (r or ""))
    with W.auftrag("Cron-Auftrag 'Bericht'", True):
        check("⚠ Auftrag MIT Freigabe: ausgefuehrt", await frei() is None)
        for k in ("loeschen", "shell", "zeitplan"):
            check(f"… auch Klasse {k}", await frei("x", k) is None)
    for wert in ("true", 1, "ja", None):
        with W.auftrag("A", wert):
            check(f"aussenwirkung={wert!r} gibt NICHT frei", await frei() is not None)
    check("nach dem with ist der Auftrag zurueckgenommen", W.auftrag_cv.get() is None)

    async def kind():
        return await frei()
    with W.auftrag("Telegram", True):
        r = await asyncio.create_task(kind())
    check("Kind-Task (Delegation) ERBT die Freigabe", r is None)
    with W.auftrag("Telegram", False):
        r = await asyncio.create_task(kind())
    check("… und auch die Verweigerung", r is not None)

    r = await W.ohne_dialog("anna", frei())
    check("⚠ ohne_dialog(): Aussenwirkung mit Hinweis auf den Browser-Chat abgewiesen",
          isinstance(r, str) and "Browser" in r, str(r)[:80])
    check("… und der Kanal ist danach zurueckgenommen", W.kanal_cv.get() is None)
    with W.auftrag("A", True):
        r = await W.ohne_dialog("anna", frei())
    check("ohne_dialog() schlaegt eine Freigabe (der Kanal geht vor)", isinstance(r, str))
    r = await W.mit_auftrag("Telegram", True, frei())
    check("mit_auftrag() setzt die Freigabe fuer den Lauf", r is None)
    check("… und nimmt sie danach zurueck", W.auftrag_cv.get() is None)

    # Ein Chat-Kanal bleibt vorrangig: eine Freigabe kann ihn NICHT umgehen.
    marke = W.kanal_cv.set(W.Kanal(ws=None, username="u", kann_bestaetigen=False))
    try:
        with W.auftrag("A", True):
            r = await frei()
        check("⚠ Client ohne Dialog bleibt abgewiesen, auch mit Freigabe",
              isinstance(r, str) and "Bestätigung" in r, str(r)[:80])
    finally:
        W.kanal_cv.reset(marke)

asyncio.run(teil1())

print("\n2. Kanal-Freigaben und Bestand (Messenger, Agent-API)")
SKILLS.clear(); EINST.clear()
check("nicht konfigurierter Kanal: keine Freigabe", W.kanal_freigabe("telegram") is False)
SKILLS["telegram"] = {"enabled": True, "config": {"bot_token": "t"}}
SKILLS["whatsapp"] = {"enabled": True, "config": {"aussenwirkung": False, "auto_reply": True}}
geaendert = W.bestand_festschreiben(bestand=True)
check("Bestand: konfigurierter Telegram-Kanal ohne Feld -> True",
      SKILLS["telegram"]["config"].get("aussenwirkung") is True, str(geaendert))
check("… andere Felder bleiben", SKILLS["telegram"]["config"].get("bot_token") == "t")
check("gesetztes False (WhatsApp) wird NICHT angefasst",
      SKILLS["whatsapp"]["config"]["aussenwirkung"] is False)
check("Bestand: Agent-API -> True", EINST.get(W.EINSTELLUNG_AGENT_API) is True)
check("kanal_freigabe liest es", W.kanal_freigabe("telegram") is True
      and W.kanal_freigabe("whatsapp") is False)
check("zweiter Lauf aendert nichts", W.bestand_festschreiben(bestand=False) == [])
SKILLS.clear(); EINST.clear()
W.bestand_festschreiben(bestand=False)
check("Erstinstallation: Agent-API -> False", EINST.get(W.EINSTELLUNG_AGENT_API) is False)
check("Erstinstallation: unkonfigurierter Messenger bekommt nichts", "telegram" not in SKILLS)
EINST[W.EINSTELLUNG_AGENT_API] = "true"
check("Agent-API: nur echtes True gibt frei", W.agent_api_freigabe() is False)

print("\n3. Bestand und Vorgabe: Cron, Trigger, Mail-Regeln (Sandkasten)")
tmp = Path(tempfile.mkdtemp(prefix="h9_auftrag_"))
try:
    from backend import scheduler as SCH
    from backend import file_watcher as FW
    from backend import mail_rules as MR

    # Cron
    SCH.JOBS_FILE = tmp / "jobs.json"
    SCH.JOBS_FILE.write_text(json.dumps([{"id": "alt", "label": "Alt", "cron": "0 3 * * *",
                                          "task": "x", "enabled": False, "owner": "a",
                                          "owner_privileged": True}]))
    cm = SCH.CronManager()
    cm._validate_cron = lambda c: None
    jobs = cm.list_jobs()
    check("Cron-Bestand: Freigabe festgeschrieben",
          jobs[0].get("aussenwirkung") is True, str(jobs[0]))
    check("… und gespeichert", json.loads(SCH.JOBS_FILE.read_text())[0].get("aussenwirkung") is True)
    neu = cm.add_job("Neu", "0 4 * * *", "y", enabled=False)
    check("⚠ neuer Cron-Auftrag: Vorgabe OHNE Freigabe", neu.get("aussenwirkung") is False)
    neu2 = cm.add_job("Neu2", "0 4 * * *", "y", enabled=False, aussenwirkung="true")
    check("nur echtes True gibt beim Anlegen frei", neu2.get("aussenwirkung") is False)
    cm.update_job(neu["id"], aussenwirkung=True)
    check("PUT setzt die Freigabe (admin-only Endpunkt)", cm.get_job(neu["id"])["aussenwirkung"] is True)
    try:
        cm.update_job(neu["id"], aussenwirkung="ja")
        check("PUT mit Nicht-bool wird abgewiesen", False)
    except ValueError:
        check("PUT mit Nicht-bool wird abgewiesen", True)

    # Trigger
    FW.WATCHERS_FILE = tmp / "watchers.json"
    FW.WATCHERS_FILE.write_text(json.dumps([{"id": "w1", "label": "W", "enabled": False}]))
    wm = FW.WatcherManager.__new__(FW.WatcherManager)
    wm._watchers = []
    wm._load()
    check("Trigger-Bestand: Freigabe festgeschrieben",
          wm._watchers[0].get("aussenwirkung") is True, str(wm._watchers[0]))
    wm._register = lambda w: None
    w = wm.add_watcher("Neu", enabled=False)
    check("⚠ neuer Trigger: Vorgabe OHNE Freigabe", w.get("aussenwirkung") is False)

    # Mail-Regeln
    MR.REGEL_DATEI = tmp / "rules.json"
    MR.REGEL_DATEI.write_text(json.dumps({"regeln": [{"id": "r1", "owner": "anna", "name": "R"}]}))
    regeln = MR._alle()
    check("Mail-Regel-Bestand: Freigabe festgeschrieben", regeln[0].get("aussenwirkung") is True)
    r = MR._pruefe({"name": "N", "prompt": "p"}, None, owner="anna")
    check("⚠ neue Mail-Regel: Vorgabe OHNE Freigabe", r.get("aussenwirkung") is False)
    r2 = MR._pruefe({"aussenwirkung": True}, {"name": "N", "prompt": "p", "aussenwirkung": False})
    check("Inhaber setzt die Freigabe an seiner Regel", r2.get("aussenwirkung") is True)
    r3 = MR._pruefe({"name": "M"}, {"name": "N", "prompt": "p", "aussenwirkung": True})
    check("Aendern ohne das Feld laesst die Freigabe stehen", r3.get("aussenwirkung") is True)
    try:
        MR._pruefe({"aussenwirkung": "ja"}, {"name": "N", "prompt": "p"})
        check("Nicht-bool wird abgewiesen", False)
    except MR.RegelFehler:
        check("Nicht-bool wird abgewiesen", True)
    check("aussenwirkung ist ueber PUT aenderbar", "aussenwirkung" in MR.AENDERBAR)
except Exception as ex:  # noqa: BLE001
    check("Abschnitt 3 lief durch", False, f"{type(ex).__name__}: {ex}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n4. Regel: jeder run_task_headless setzt einen Auftrag (oder ist begruendet ausgenommen)")
# (Datei, Funktion) -> Grund. Jede Ausnahme muss eine Werkzeug-Positivliste setzen
# (`_role_tools = …`), sonst ist sie keine – das prueft die Regel mit.
AUSNAHMEN = {
    ("backend/short_tracks_runner.py", "*"): "Positivliste ohne Aussenwerkzeuge",
    ("backend/ai_mouse.py", "*"): "Positivliste, nur lesend",
    ("backend/jira_assist.py", "*"): "Positivliste, nur lesend",
    ("backend/claude_subagent.py", "*"): "filesystem + Sandbox-Shell ohne Netz",
    ("backend/mail_runner.py", "antwort_vorschlag"): "keine Werkzeuge (set())",
    ("backend/main.py", "excel_ask_endpoint"): "nur excel_vorschlag",
    ("backend/agent.py", "_delegate_to_role"): "erbt Kanal bzw. Auftrag des Aufrufers",
}


def eltern_kette(baum):
    eltern = {}
    for n in ast.walk(baum):
        for k in ast.iter_child_nodes(n):
            eltern[k] = n
    return eltern


def setzt_auftrag(knoten, eltern):
    """Steht der Aufruf in `with ….auftrag(...)`, in `mit_auftrag(…, <hier>)`
    oder in einer Funktion, die `auftrag_cv.set(` ruft?"""
    n = knoten
    funk = None
    while n in eltern:
        p = eltern[n]
        if (isinstance(p, ast.Call) and getattr(p.func, "attr", "") in ("mit_auftrag", "ohne_dialog")
                and n in p.args):
            return True
        if isinstance(p, (ast.With, ast.AsyncWith)):
            for it in p.items:
                c = it.context_expr
                if isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "auftrag":
                    return True
        if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)) and funk is None:
            funk = p
        n = p
    if funk is not None:
        for c in ast.walk(funk):
            if (isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "set"
                    and isinstance(c.func.value, ast.Attribute) and c.func.value.attr == "auftrag_cv"):
                return True
    return False


def funktion_von(knoten, eltern):
    n = knoten
    while n in eltern:
        n = eltern[n]
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return n
    return None


gesamt = 0
for pfad in sorted(list((ROOT / "backend").rglob("*.py")) + list((ROOT / "skills").rglob("*.py"))):
    rel = str(pfad.relative_to(ROOT))
    try:
        src = pfad.read_text(encoding="utf-8")
        baum = ast.parse(src)
    except Exception:  # noqa: BLE001
        continue
    eltern = None
    for n in ast.walk(baum):
        if not (isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "run_task_headless"):
            continue
        eltern = eltern or eltern_kette(baum)
        gesamt += 1
        f = funktion_von(n, eltern)
        fname = f.name if f else "<modul>"
        if setzt_auftrag(n, eltern):
            continue
        grund = AUSNAHMEN.get((rel, fname)) or AUSNAHMEN.get((rel, "*"))
        if not grund:
            check(f"{rel}:{n.lineno} ({fname}) setzt einen Auftrag", False,
                  "neuer Einstieg ohne Freigabe-Entscheid")
            continue
        if fname == "_delegate_to_role":
            continue
        positiv = any(isinstance(z, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == "_role_tools" for t in z.targets)
            for z in ast.walk(f if fname != "<modul>" else baum))
        if not positiv:
            positiv = "_role_tools" in src
        check(f"Ausnahme {rel}:{fname} hat eine Werkzeug-Positivliste ({grund})", positiv)
check("Positivkontrolle: Aufrufe gefunden (>= 15)", gesamt >= 15, str(gesamt))

# Die Freigabe stammt aus dem Datensatz, nicht aus einer Konstanten True –
# ausser bei der ausdruecklich benannten Oberflaechen-Konstante.
for rel, muster in (("backend/scheduler.py", 'job.get("aussenwirkung") is True'),
                    ("backend/file_watcher.py", 'watcher.get("aussenwirkung") is True'),
                    ("backend/mail_runner.py", 'regel.get("aussenwirkung") is True'),
                    ("skills/telegram/main.py", 'kanal_freigabe("telegram")'),
                    ("backend/main.py", 'kanal_freigabe("whatsapp")'),
                    ("backend/main.py", "agent_api_freigabe()")):
    check(f"{rel}: Freigabe aus {muster}", muster in (ROOT / rel).read_text(encoding="utf-8"))
# Betreiberentscheid 2026-10-11: Oberflaechen ohne Dialog = "Client ohne Dialog"
_mn = (ROOT / "backend/main.py").read_text(encoding="utf-8")
for agent in ("_avatar_agent", "_sap_agent", "_vemas_agent", "ag"):
    check(f"{agent}: Lauf ueber ohne_dialog (Aussenwirkung mit Hinweis abgewiesen)",
          f"_wirkung_h9.ohne_dialog(" in _mn and re.search(
              r"_wirkung_h9\.ohne_dialog\(\w+, " + re.escape(agent) + r"\.run_task_headless\(", _mn) is not None)
check("keine Pauschal-Freigabe fuer Oberflaechen mehr", "OBERFLAECHE_OHNE_DIALOG_FREIGABE" not in _mn)
ct = (ROOT / "backend/tools/cron_tool.py").read_text(encoding="utf-8")
check("cron_create (Werkzeug) setzt die Freigabe NIE", "aussenwirkung=" not in ct)
mn = (ROOT / "backend/main.py").read_text(encoding="utf-8")
check("Startup-Hook startup_wirkung_bestand ist da",
      "async def startup_wirkung_bestand" in mn and "bestand_festschreiben(" in mn)
for skill in ("telegram", "whatsapp"):
    sch = json.loads((ROOT / "skills" / skill / "skill.json").read_text(encoding="utf-8"))
    f = sch.get("config_schema", {}).get("aussenwirkung") or {}
    check(f"{skill}: Schalter im Konfigurationsschema, Vorgabe aus",
          f.get("type") == "boolean" and f.get("default") is False)

print(f"\nERGEBNIS: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
