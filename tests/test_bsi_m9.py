#!/usr/bin/env python3
"""Waechter BSI M9 – Loeschkonzept.

  [A] ``loeschfristen.tage``: Einstellung > Umgebung > Vorgabe, 0 = dauerhaft,
      Deckel, Unsinn = Vorgabe; ``setzen`` prueft Grenzen und speichert.
  [B] Chats (Sandkasten): alte Sitzungen (meta.updated) und alte Nachrichten
      (ts in ms) fallen, frische und solche OHNE Zeitstempel bleiben;
      Direktnachrichten ebenso.
  [C] Konversationsprotokoll (Sandkasten): volle Inhalte aelter als die
      Prompt-Frist fallen, die Kopfzeile bleibt mit gekuerztem Aufgabentext;
      der Altbestand ``conv_log.json.migrated`` faellt.
  [D] Verdrahtung: run_all ruft Chats, Prompts und Direktnachrichten, auch wenn
      die Protokolle dauerhaft aufbewahrt werden; Protokoll- und
      Sicherheitsfrist kommen aus ``loeschfristen``.
  [E] Endpunkte (Rumpf per AST ausgefuehrt): Lernnotiz loeschen nur in
      LEARNED_DIR und nur Notiz-Dateien; Gedaechtnis-Eintrag loeschen nimmt ihn
      auch aus der Sicherungskopie; Rechte der neuen Routen.
  [F] Lernnotizen tragen Herkunft; die Liste zeigt sie und auch Feedback-Notizen.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:300] + "]") if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="bsi_m9_"))

# backend.config nur als Stub
_cfg = types.ModuleType("backend.config")


class _C:
    werte: dict = {}

    def get_setting(self, k, d=None):
        return self.werte.get(k, d)

    def save_setting(self, k, v):
        self.werte[k] = v


_cfg.config = _C()
sys.modules["backend.config"] = _cfg
for e in [k for k in os.environ if k in ("JARVIS_CHAT_TAGE", "JARVIS_PROMPT_TAGE",
                                         "JARVIS_LOG_RETENTION_DAYS", "JARVIS_SICHERHEITS_LOG_TAGE")]:
    os.environ.pop(e)

from backend import loeschfristen as lf  # noqa: E402

# ═════════════════════════════════════════════════════════════════════════════
print("\n[A] Fristen")
soll = {"chats": 180, "prompts": 30, "protokoll": 90, "sicherheit": 365}
check("Vorgaben laut Betreiberentscheid", {a: lf.tage(a) for a in soll} == soll,
      {a: lf.tage(a) for a in soll})
os.environ["JARVIS_CHAT_TAGE"] = "60"
check("Umgebung schlaegt Vorgabe", lf.tage("chats") == 60 and lf.quelle("chats") == "umgebung")
_cfg.config.werte["loeschfrist_chats"] = 45
check("Einstellung schlaegt Umgebung", lf.tage("chats") == 45 and lf.quelle("chats") == "einstellung")
_cfg.config.werte["loeschfrist_chats"] = 0
check("0 = dauerhaft (auch aus der Einstellung, Falsyness-Falle)", lf.tage("chats") == 0
      and lf.schnitt("chats") is None)
_cfg.config.werte["loeschfrist_chats"] = None
check("Einstellung None -> Umgebung", lf.tage("chats") == 60)
os.environ["JARVIS_CHAT_TAGE"] = "9000"
check("Deckel 3650", lf.tage("chats") == 3650)
os.environ["JARVIS_CHAT_TAGE"] = "abc"
check("Unsinn -> Vorgabe", lf.tage("chats") == 180)
os.environ.pop("JARVIS_CHAT_TAGE")
_cfg.config.werte["loeschfrist_chats"] = True
check("bool ist keine Zahl -> Vorgabe", lf.tage("chats") == 180)
_cfg.config.werte.clear()
jetzt = 2_000_000_000.0
check("Schnitt = jetzt - Tage", lf.schnitt("prompts", jetzt) == jetzt - 30 * 86400)
for falsch in ({"chats": -1}, {"chats": "x"}, {"chats": 4000}, {"unbekannt": 5}):
    try:
        lf.setzen(falsch)
        check("setzen weist %r ab" % falsch, False)
    except ValueError:
        check("setzen weist %r ab" % falsch, True)
erg = lf.setzen({"chats": 120, "prompts": 0, "protokoll": ""})
check("setzen speichert (Zahl, 0, leer = entfernen)",
      _cfg.config.werte == {"loeschfrist_chats": 120, "loeschfrist_prompts": 0,
                            "loeschfrist_protokoll": None}
      and erg["chats"]["tage"] == 120 and erg["prompts"]["tage"] == 0 and erg["protokoll"]["tage"] == 90,
      (_cfg.config.werte, erg))
_cfg.config.werte.clear()

# ═════════════════════════════════════════════════════════════════════════════
print("\n[B] Chats")
D = TMP / "data"
alt, neu = jetzt - 200 * 86400, jetzt - 10 * 86400


def sitzung(user, sid, updated):
    sd = D / "chats" / user / sid
    sd.mkdir(parents=True)
    if updated is not None:
        (sd / "meta.json").write_text(json.dumps({"id": sid, "updated": updated}))
    (sd / "transcript.json").write_text("[]")
    return sd


s_alt, s_neu = sitzung("anna", "a1", alt), sitzung("anna", "a2", neu)
s_kaputt = sitzung("bert", "b1", None)
s_unlesbar = sitzung("bert", "b2", None)
(s_unlesbar / "meta.json").write_text("{kaputt")
(D / "chat_history").mkdir(parents=True)
(D / "chat_history" / "anna.json").write_text(json.dumps(
    [{"text": "alt", "ts": int(alt * 1000)}, {"text": "neu", "ts": int(neu * 1000)}, {"text": "ohne ts"}]))
(D / "chat_history" / "bert.json").write_text(json.dumps([{"text": "alt", "ts": int(alt * 1000)}]))
e = lf.chats_bereinigen(jetzt=jetzt, daten=D)
check("Positivkontrolle: Lauf zaehlt", e.get("sitzungen") == 1 and e.get("verlauf_nachrichten") == 2, e)
check("alte Sitzung entfernt", not s_alt.exists())
check("frische Sitzung bleibt", s_neu.exists())
check("Sitzung ohne meta (kein Altersbeweis) bleibt", s_kaputt.exists())
check("Sitzung mit unlesbarer meta (kein Altersbeweis) bleibt", s_unlesbar.exists())
rest = json.loads((D / "chat_history" / "anna.json").read_text())
check("Verlauf: alt weg, neu und ohne Zeitstempel bleiben",
      [m["text"] for m in rest] == ["neu", "ohne ts"], rest)
check("leer gewordener Verlauf: Datei entfernt", not (D / "chat_history" / "bert.json").exists())
_cfg.config.werte["loeschfrist_chats"] = 0
check("dauerhaft: nichts angefasst", lf.chats_bereinigen(jetzt=jetzt, daten=D) == {"dauerhaft": True})
_cfg.config.werte.clear()
dm = {"a__b": [{"ts": int(alt * 1000)}, {"ts": int(neu * 1000)}], "a__c": [{"ts": int(alt * 1000)}],
      "a__d": [{"text": "ohne"}]}
n = lf.direktnachrichten_bereinigen(dm, jetzt - 180 * 86400)
check("Direktnachrichten: alt weg, leere Unterhaltung weg, ohne ts bleibt",
      n == 2 and list(dm) == ["a__b", "a__d"] and len(dm["a__b"]) == 1, (n, dm))

# ═════════════════════════════════════════════════════════════════════════════
print("\n[C] Konversationsprotokoll")
from backend import conv_log as cl  # noqa: E402
CD = TMP / "conv"
cl._DATA_DIR, cl._CONV_DIR, cl._INDEX, cl._OLD_FILE = TMP, CD, CD / "index.jsonl", TMP / "conv_log.json"
cl._migrated = True
CD.mkdir()
lang = "Bitte fasse den Vertrag mit Kunde X zusammen und nenne alle Fristen " * 3
eintraege = [{"id": "alt1", "ts": alt, "task": lang}, {"id": "neu1", "ts": neu, "task": lang}]
(CD / "index.jsonl").write_text("".join(json.dumps(x) + "\n" for x in eintraege))
for x in eintraege:
    (CD / (x["id"] + ".json")).write_text(json.dumps({"id": x["id"], "messages": [{"content": "geheim"}]}))
mig = TMP / "conv_log.json.migrated"
mig.write_text("{}")
os.utime(mig, (alt, alt))
n = cl.prompts_entfernen(jetzt - 30 * 86400)
idx = [json.loads(z) for z in (CD / "index.jsonl").read_text().splitlines() if z.strip()]
a = next((x for x in idx if x["id"] == "alt1"), {})
b = next((x for x in idx if x["id"] == "neu1"), {})
check("Positivkontrolle: eine Konversation bearbeitet", n == 1, n)
check("alter Rumpf entfernt, frischer bleibt", not (CD / "alt1.json").exists() and (CD / "neu1.json").exists())
check("Kopfzeile bleibt, Aufgabentext gekuerzt + markiert",
      a.get("inhalt_entfernt") is True and len(a.get("task", "")) <= cl.GEKUERZT_LAENGE + 1, a)
check("frische Kopfzeile unveraendert", b.get("task") == lang and "inhalt_entfernt" not in b)
check("Altbestand .migrated entfernt", not mig.exists())
check("zweiter Lauf: nichts mehr zu tun", cl.prompts_entfernen(jetzt - 30 * 86400) == 0)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[D] Verdrahtung")
LR = ast.parse((ROOT / "backend" / "log_retention.py").read_text(encoding="utf-8"))
run_all = next((n for n in LR.body if isinstance(n, ast.FunctionDef) and n.name == "run_all"), None)
rd = next((n for n in LR.body if isinstance(n, ast.FunctionDef) and n.name == "retention_days"), None)
if run_all is None or rd is None:
    abbruch("run_all/retention_days nicht gefunden")
src = ast.unparse(run_all)
check("run_all: Chats bereinigen", "loeschfristen.chats_bereinigen()" in src)
check("run_all: volle Prompts entfernen", "conv_log.prompts_entfernen(" in src)
check("run_all: Direktnachrichten (ZUSATZ_CHATS)", "for fn in list(ZUSATZ_CHATS)" in src)
i_lf = src.find("loeschfristen.chats_bereinigen()")
i_skip = src.find("if cut is None:")
check("Loeschfristen laufen VOR dem Abbruch bei 'Protokolle dauerhaft'", 0 < i_lf < i_skip, (i_lf, i_skip))
check("Protokollfrist aus loeschfristen", "loeschfristen.tage('protokoll')" in ast.unparse(rd))
SL = ast.parse((ROOT / "backend" / "sicherheits_log.py").read_text(encoding="utf-8"))
at = next((n for n in SL.body if isinstance(n, ast.FunctionDef) and n.name == "aufbewahrung_tage"), None)
check("Sicherheitsfrist aus loeschfristen", at is not None and "loeschfristen.tage('sicherheit')" in ast.unparse(at))
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MB = ast.parse(MAIN)
check("main.py meldet die Direktnachrichten an",
      "_log_retention_m9.ZUSATZ_CHATS.append(_uc_frist_anwenden)" in MAIN)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[E] Endpunkte")


def route(fn_name):
    return next((n for n in MB.body if isinstance(n, ast.AsyncFunctionDef) and n.name == fn_name), None)


def dep(fn):
    return [ast.unparse(d.args[0]) for d in fn.args.defaults if isinstance(d, ast.Call)
            and getattr(d.func, "id", "") == "Depends"] if fn else []


for name, soll_dep in [("delete_learned_file", "require_admin_or_knowledge_editor"),
                       ("loeschfristen_lesen", "require_local_auth"),
                       ("loeschfristen_setzen", "require_local_auth"),
                       ("gedaechtnis_lesen", "require_auth"),
                       ("gedaechtnis_eintrag_loeschen", "require_auth")]:
    check("%s haengt an %s" % (name, soll_dep), dep(route(name)) == [soll_dep], dep(route(name)))


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


class _JR:
    def __init__(self, inhalt, status_code=200):
        self.inhalt, self.status_code = inhalt, status_code


def ausfuehren(fn_name, ns, *args, **kw):
    fn = route(fn_name)
    fn.decorator_list = []
    exec(compile(ast.Module(body=[fn], type_ignores=[]), fn_name, "exec"), ns)
    return asyncio.run(ns[fn_name](*args, **kw))


# Lernnotiz loeschen
LD = TMP / "proj" / "data" / "erfahrung"
(LD / "2026-10").mkdir(parents=True)
notiz = LD / "2026-10" / "auto_lerned_1_ab.md"
notiz.write_text("x")
fb = LD / "feedback_1.md"
fb.write_text("x")
fremd = TMP / "proj" / "data" / "settings.json"
fremd.write_text("{}")
anders = LD / "liesmich.txt"
anders.write_text("x")
draussen = TMP / "proj" / "data" / "auto_lerned_9_zz.md"   # Notiz-Name, aber AUSSERHALB
draussen.write_text("x")
_lern = types.ModuleType("backend.learning")
_lern.LEARNED_DIR, _lern.NOTIZ_PRAEFIX, _lern.PROJECT_ROOT = LD, "auto_lerned_", TMP / "proj"
sys.modules["backend.learning"] = _lern
EREIG = []
ns = {"JSONResponse": _JR, "Request": object, "Depends": lambda f: None,
      "require_admin_or_knowledge_editor": None,
      "_sicherheits_log": types.SimpleNamespace(ereignis=lambda *a, **k: EREIG.append((a, k)))}
r = ausfuehren("delete_learned_file", ns, _Req({"path": "data/erfahrung/2026-10/auto_lerned_1_ab.md"}), user="admin")
check("Lernnotiz geloescht (Positivkontrolle)", r.status_code == 200 and not notiz.exists(), r.inhalt)
check("Loeschen protokolliert", bool(EREIG) and EREIG[-1][0][0] == "lernnotiz_geloescht")
r = ausfuehren("delete_learned_file", ns, _Req({"path": "data/erfahrung/feedback_1.md"}), user="admin")
check("Feedback-Notiz loeschbar", r.status_code == 200 and not fb.exists())
r = ausfuehren("delete_learned_file", ns, _Req({"path": "data/erfahrung/../settings.json"}), user="admin")
check("⚠ Pfad aus LEARNED_DIR heraus: 403, Datei bleibt", r.status_code == 403 and fremd.exists(), r.status_code)
r = ausfuehren("delete_learned_file", ns, _Req({"path": "data/erfahrung/../auto_lerned_9_zz.md"}), user="admin")
check("⚠ Notiz-Name ausserhalb von LEARNED_DIR: 403, Datei bleibt", r.status_code == 403 and draussen.exists(),
      r.status_code)
r = ausfuehren("delete_learned_file", ns, _Req({"path": "data/erfahrung/liesmich.txt"}), user="admin")
check("keine Notiz-Datei: 403", r.status_code == 403 and anders.exists())

# Gedaechtnis-Eintrag loeschen
MD = TMP / "mem"
MD.mkdir()
_memmod = types.ModuleType("backend.tools.memory")
import threading  # noqa: E402
_memmod._lock = threading.Lock()
_mempfad = MD / "memory_anna.json"
_daten = {"farbe": {"value": "blau", "updated": "2026-10-01T10:00:00"},
          "geheim": {"value": "PIN 1234", "updated": "2026-10-02T10:00:00"}}
_mempfad.write_text(json.dumps(_daten))
_mempfad.with_suffix(".json.bak").write_text(json.dumps(_daten))
_memmod._load_memory_dict = lambda u: json.loads(_mempfad.read_text())
_memmod._save_memory_dict = lambda d, u: _mempfad.write_text(json.dumps(d))
_memmod._get_memory_path = lambda u: _mempfad
import backend.tools  # noqa: E402
sys.modules["backend.tools.memory"] = _memmod
backend.tools.memory = _memmod
ns2 = {"JSONResponse": _JR, "Request": object, "Depends": lambda f: None, "require_auth": None}
r = ausfuehren("gedaechtnis_eintrag_loeschen", ns2, _Req({"key": "geheim"}), user="anna")
check("Gedaechtnis-Eintrag geloescht", r.status_code == 200 and "geheim" not in json.loads(_mempfad.read_text()))
check("⚠ auch aus der Sicherungskopie", "geheim" not in _mempfad.with_suffix(".json.bak").read_text())
r = ausfuehren("gedaechtnis_eintrag_loeschen", ns2, _Req({"key": "gibtsnicht"}), user="anna")
check("unbekannter Eintrag: 404", r.status_code == 404)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[F] Herkunft der Lernnotizen")
sys.modules.pop("backend.learning", None)
try:
    import importlib
    learning = importlib.import_module("backend.learning")
except Exception as e:  # noqa: BLE001
    abbruch("backend.learning nicht ladbar: %s" % e)
learning.LEARNED_DIR = TMP / "erf"
learning._save_and_index("Vertrag pruefen", "- Fakt A", "anna.beispiel")
dateien = list((TMP / "erf").rglob("*.md"))
inhalt = dateien[0].read_text() if dateien else ""
check("Notiz geschrieben (Positivkontrolle)", len(dateien) == 1)
check("Notiz nennt die Herkunft", learning.herkunft(inhalt) == "anna.beispiel", inhalt[:200])
check("Altbestand ohne Zeile: leer", learning.herkunft("# Gelernt: x\nDatum: 2026\n\nFakt") == "")
AG = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
lern_aufruf = [ast.unparse(n) for n in ast.walk(ast.parse(AG)) if isinstance(n, ast.Call)
               and ast.unparse(n.func).endswith("learn_from_conversation")]
check("Agent reicht den Benutzer durch", lern_aufruf and all("benutzer=" in x for x in lern_aufruf), lern_aufruf)
fsi = route("_feedback_self_improve")
check("Feedback-Notiz traegt Herkunft", fsi is not None and "_lern_herkunft_zeile" in ast.unparse(fsi))
api_fb = route("api_feedback")
check("Feedback-Endpunkt reicht den Benutzer durch",
      api_fb is not None and "_feedback_self_improve(user_msg, bot_resp, rating, benutzer=user)" in ast.unparse(api_fb))
ll = route("list_learned_files")
check("Liste zeigt Herkunft und Feedback-Notizen",
      ll is not None and "'herkunft': herkunft(content)" in ast.unparse(ll) and "'feedback_*.md'" in ast.unparse(ll))
kjs = (ROOT / "frontend" / "js" / "knowledge.js").read_text(encoding="utf-8")
i = kjs.find("async deleteLearnedFile(")
teil = kjs[i:i + 1200] if i >= 0 else ""
check("Loesch-Knopf ruft den eigenen Endpunkt", "'/api/knowledge/learned'" in teil
      and "'/api/knowledge/files'" not in teil, teil[:200])

shutil.rmtree(TMP, ignore_errors=True)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
