#!/usr/bin/env python3
"""Waechter: Backend <-> WhatsApp-Bridge nur mit gemeinsamem Geheimnis
(Code-Review 2026-10-18).

  [1] backend/wa_bruecke.py AUSGEFUEHRT im Wegwerf-Verzeichnis: Anlegen 0600,
      kein Ueberschreiben, Vergleich, Sprachdatei-Schranke (Symlink, ../).
  [2] REGEL ueber backend/ und skills/ (Syntaxbaum): jede Funktion, die die
      Bridge-Adresse benutzt UND eine HTTP-Anfrage stellt, ruft ``kopf()`` –
      gezaehlt, nicht gelistet (eine vergessene Stelle meldet sich nicht).
      Dazu: kein toter Pfad ``/api/send`` mehr.
  [3] Webhook /api/whatsapp/incoming AUSGEFUEHRT (per AST geschnitten):
      ohne Geheimnis 403, leere Freigabeliste = niemand, fremder
      Sprachdatei-Pfad wird weder transkribiert noch geloescht.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import os
import shutil
import stat
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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


SK = Path(tempfile.mkdtemp(prefix="wa_bruecke_"))
spec = importlib.util.spec_from_file_location("wa_bruecke_probe", ROOT / "backend" / "wa_bruecke.py")
WB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(WB)
WB.PFAD = SK / "data" / ".wa_bridge_secret"
WB.SPRACH_DIR = str(SK / "voice")
os.makedirs(WB.SPRACH_DIR)
if not str(WB.PFAD).startswith(str(SK)):
    abbruch("Sandkasten greift nicht")

try:
    print("\n[1] wa_bruecke.py")
    g = WB.geheimnis()
    check("(Positivkontrolle) Geheimnis angelegt", isinstance(g, str) and len(g) >= 32)
    if FAIL:
        abbruch("Messaufbau traegt nicht")
    check("Datei 0600", stat.S_IMODE(WB.PFAD.stat().st_mode) == 0o600, oct(stat.S_IMODE(WB.PFAD.stat().st_mode)))
    WB._cache = None
    check("zweiter Aufruf liest DASSELBE (kein Ueberschreiben)", WB.geheimnis() == g)
    check("kopf() traegt den Wert", WB.kopf() == {WB.KOPF: g})
    check("pruefe: richtig", WB.pruefe(g) is True)
    check("pruefe: falsch/leer/None", not WB.pruefe(g[:-1] + "x") and not WB.pruefe("") and not WB.pruefe(None))
    gut = Path(WB.SPRACH_DIR) / "voice_1.ogg"
    gut.write_bytes(b"OGG")
    fremd = SK / "wichtig.txt"
    fremd.write_text("x")
    (Path(WB.SPRACH_DIR) / "link.ogg").symlink_to(fremd)
    check("(Positivkontrolle) Sprachdatei im Ablageordner erlaubt", WB.sprachdatei_erlaubt(str(gut)))
    check("fremde Datei abgewiesen", not WB.sprachdatei_erlaubt(str(fremd)))
    check("Symlink im Ablageordner auf fremde Datei abgewiesen",
          not WB.sprachdatei_erlaubt(str(Path(WB.SPRACH_DIR) / "link.ogg")))
    check("../ aus dem Ablageordner abgewiesen",
          not WB.sprachdatei_erlaubt(WB.SPRACH_DIR + "/../wichtig.txt"))
    check("leer/kein Text abgewiesen", not WB.sprachdatei_erlaubt("") and not WB.sprachdatei_erlaubt(None))
finally:
    pass

print("\n[2] Regel: jeder Bridge-Aufruf traegt das Geheimnis")
BRIDGE_NAMEN = {"BRIDGE_URL", "WA_BRIDGE", "_WA_BRIDGE"}
ANFRAGE = {"urlopen", "Request", "post", "get"}
befunde, gezaehlt = [], 0
for p in list((ROOT / "backend").rglob("*.py")) + list((ROOT / "skills").rglob("*.py")):
    if "__pycache__" in p.parts:
        continue
    try:
        baum = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for fn in ast.walk(baum):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        innen = [n for n in ast.walk(fn) if n is not fn]
        # eigene Unterfunktionen zaehlen fuer sich
        nutzt = any((isinstance(n, ast.Name) and n.id in BRIDGE_NAMEN)
                    or (isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and (":3001" in n.value) and n.value.startswith("http"))
                    for n in innen)
        fragt = any(isinstance(n, ast.Call) and (getattr(n.func, "attr", None) in ANFRAGE
                                                 or getattr(n.func, "id", None) in ANFRAGE)
                    for n in innen)
        if not (nutzt and fragt):
            continue
        gezaehlt += 1
        kopf = any(isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "kopf" for n in innen)
        if not kopf:
            befunde.append("%s:%s %s" % (p.relative_to(ROOT), fn.lineno, fn.name))
        for n in innen:
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.endswith(":3001/api/send"):
                befunde.append("%s:%s toter Pfad /api/send" % (p.relative_to(ROOT), n.lineno))
check("(Positivkontrolle) Bridge-Aufrufe gefunden (%d)" % gezaehlt, gezaehlt >= 7, str(gezaehlt))
check("jeder ruft kopf()", not befunde, "; ".join(befunde))

print("\n[3] Webhook")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
hook = None
for n in BAUM.body:
    if isinstance(n, ast.AsyncFunctionDef):
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "post" and d.args
                    and isinstance(d.args[0], ast.Constant) and d.args[0].value == "/api/whatsapp/incoming"):
                hook = n
if hook is None:
    abbruch("Webhook nicht gefunden")
hook.decorator_list = []
LOG, GESTARTET, TRANSKRIBIERT = [], [], []


class JSONResponse:
    def __init__(self, content, status_code=200):
        self.content, self.status_code = content, status_code


class Anfrage:
    def __init__(self, body, kopf=None, ip="127.0.0.1"):
        self._b = body
        self.headers = {WB.KOPF: kopf} if kopf else {}
        self.client = types.SimpleNamespace(host=ip)

    async def json(self):
        return self._b


class SM:
    def __init__(self, cfg):
        self.cfg = cfg

    def get_skill_config(self, name):
        return self.cfg


_cfg = {"allowed_numbers": "4930123456"}
wb_modul = types.ModuleType("backend.wa_bruecke")
wb_modul.__dict__.update({k: getattr(WB, k) for k in ("KOPF", "SPRACH_DIR", "pruefe", "sprachdatei_erlaubt")})
paket = sys.modules.setdefault("backend", types.ModuleType("backend"))
sys.modules["backend.wa_bruecke"] = wb_modul
paket.wa_bruecke = wb_modul


async def _run_wa(*a):
    GESTARTET.append(a)


ns = {"JSONResponse": JSONResponse, "Request": Anfrage, "asyncio": asyncio, "os": os,
      "wa_log": lambda *a, **k: LOG.append(a), "_get_skill_manager": lambda: SM(_cfg),
      "_transcribe_audio": lambda pfad, *a: TRANSKRIBIERT.append(pfad) or "Hallo Welt",
      "_run_wa_task": _run_wa, "app": None}
exec(compile(ast.fix_missing_locations(ast.Module(body=[hook], type_ignores=[])), "main", "exec"), ns)
H = ns[hook.name]


def ruf(body, kopf=None, cfg=None):
    global _cfg
    _cfg = cfg if cfg is not None else {"allowed_numbers": "4930123456"}
    GESTARTET.clear()
    TRANSKRIBIERT.clear()

    async def _lauf():
        r = await H(Anfrage(body, kopf))
        await asyncio.sleep(0)
        return r
    return asyncio.run(_lauf())


TEXT = {"type": "text", "from": "4930123456", "text": "Hallo"}
r = ruf(TEXT, kopf=g)
check("(Positivkontrolle) mit Geheimnis + freigegebener Nummer: Auftrag startet",
      r.content.get("status") == "processing" and len(GESTARTET) == 1, str(r.content))
r = ruf(TEXT)
check("ohne Geheimnis: 403, kein Auftrag", r.status_code == 403 and not GESTARTET, str(r.content))
r = ruf(TEXT, kopf="falsch")
check("falsches Geheimnis: 403", r.status_code == 403 and not GESTARTET)
r = ruf(TEXT, kopf=g, cfg={"allowed_numbers": ""})
check("leere Freigabeliste = niemand", r.content.get("status") == "rejected" and not GESTARTET, str(r.content))
r = ruf(dict(TEXT, **{"from": "4930999999"}), kopf=g)
check("fremde Nummer abgewiesen", r.content.get("status") == "rejected" and not GESTARTET)
fremd.write_text("bleibt")
r = ruf({"type": "voice", "from": "4930123456", "media_path": str(fremd)}, kopf=g)
check("Sprachnachricht mit fremdem Pfad: nicht transkribiert", not TRANSKRIBIERT, str(TRANSKRIBIERT))
check("... und NICHT geloescht", fremd.exists())
r = ruf({"type": "voice", "from": "4930123456", "media_path": str(gut)}, kopf=g)
check("(Positivkontrolle) Sprachnachricht im Ablageordner: transkribiert und aufgeraeumt",
      TRANSKRIBIERT == [str(gut)] and not gut.exists(), str(TRANSKRIBIERT))

shutil.rmtree(SK, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
