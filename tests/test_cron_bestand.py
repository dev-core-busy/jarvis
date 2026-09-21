#!/usr/bin/env python3
"""Waechter: ein Cron-Zugriff VOR start() darf den Bestand nicht loeschen.

⚠ DAS IST EIN BEZAHLTER VORFALL, kein theoretischer Fall (2026-09-21, ECHT):
der Startup-Hook des Wissensabgleichs rief ``cron_manager.add_job()``, bevor
``start()`` gelaufen war. ``_jobs`` war dabei die LEERE Anfangsliste aus dem
Konstruktor - add_job haengte an, ``_save()`` schrieb eine Liste mit genau
einem Eintrag, und der taegliche Auftrag ``system_auto_update`` war weg.
Sichtbar war davon nichts: das Journal meldete "1 Jobs geladen", genau wie an
jedem Tag davor (dort war es der andere Job).

Auf DEV ist es nicht aufgefallen, weil dort **0 Auftraege** lagen - es gab
schlicht nichts zu verlieren. Dieselbe Klasse wie die Werkzeug-Buendel und das
Lernnotizen-Aufraeumen: eine Messung auf DEV, die auf ECHT anders ausgeht,
weil DEV den Bestand nicht hat.

Gemessen wird die EIGENSCHAFT ("ein bestehender Auftrag ueberlebt"), nicht eine
Schreibweise - die echte Klasse wird per ``ast`` geschnitten und WIRKLICH
AUSGEFUEHRT. Eine Quelltext-Suche koennte "wird der Job geloescht?" nicht
beantworten.
"""
import ast
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUELLE = ROOT / "backend" / "scheduler.py"

_ok = _fail = 0


def check(text, bedingung):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}")


def sicher(fn, *a, **kw):
    """Nie ungeprueft dereferenzieren - ein Wurf darf keine Bilanz verschlucken."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


# ─── Die echte Klasse schneiden ──────────────────────────────────────────────
src = QUELLE.read_text()
baum = ast.parse(src)
cls = next((n for n in baum.body
            if isinstance(n, ast.ClassDef) and n.name == "CronManager"), None)
if cls is None:
    print("KEIN CronManager im Quelltext gefunden - nicht pruefbar")
    sys.exit(2)
KLASSE = ast.get_source_segment(src, cls)


class _SchedStub:
    running = False

    def add_job(self, *a, **kw):
        return None

    def remove_job(self, *a, **kw):
        return None

    def get_job(self, *a, **kw):
        return None

    def start(self):
        self.running = True

    def shutdown(self, *a, **kw):
        self.running = False


class _TriggerStub:
    @staticmethod
    def from_crontab(expr):
        if len(str(expr).split()) != 5:
            raise ValueError("kaputt")
        return object()


def baue(jobs_datei: Path):
    """Eine frische CronManager-Instanz mit gestellter Ablage."""
    ns = {
        "AsyncIOScheduler": lambda **kw: _SchedStub(),
        "CronTrigger": _TriggerStub,
        "JOBS_FILE": jobs_datei,
        "json": json, "uuid": __import__("uuid"), "time": __import__("time"),
        "asyncio": __import__("asyncio"),
        "Optional": __import__("typing").Optional,
        "_agent_manager": None, "_broadcast_fn": None,
        "print": print,
    }
    exec(KLASSE, ns)          # noqa: S102 - genau das ist der Zweck
    return ns["CronManager"]()


# ─── Sandkasten ──────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="cronbestand-"))
try:
    JD = SAND / "scheduled_jobs.json"
    if not str(JD).startswith(str(SAND)):
        print("SANDKASTEN GREIFT NICHT - Abbruch")
        sys.exit(2)

    ALT = [{
        "id": "system_auto_update", "label": "Auto-Update", "cron": "0 3 * * *",
        "task": "git pull && systemctl restart jarvis.service", "enabled": True,
        "once": False, "kind": "agent", "owner": "jarvis",
        "owner_privileged": True, "created_via": "update_settings",
    }]

    print("\n1) DER VORFALL: add_job VOR start()")
    JD.write_text(json.dumps(ALT))
    cm = baue(JD)
    neu = sicher(cm.add_job, "Wissensabgleich", "*/5 * * * *", "prueft nach",
                 job_id="wissensabgleich", kind="wissensabgleich")
    check("add_job wirft nicht", not isinstance(neu, Exception))
    auf_platte = sicher(lambda: json.loads(JD.read_text()))
    ids = [j.get("id") for j in auf_platte] if isinstance(auf_platte, list) else []
    check("der BESTEHENDE Auftrag liegt noch auf der Platte "
          f"(gefunden: {ids})", "system_auto_update" in ids)
    check("der neue Auftrag ist dazugekommen", "wissensabgleich" in ids)
    check("es sind GENAU zwei", len(ids) == 2)

    print("\n2) Lesen vor start() sieht den Bestand")
    JD.write_text(json.dumps(ALT))
    cm = baue(JD)
    check("get_job findet den bestehenden Auftrag",
          not isinstance(sicher(cm.get_job, "system_auto_update"), Exception)
          and cm.get_job("system_auto_update") is not None)
    cm = baue(JD)
    check("list_jobs liefert ihn", len(cm.list_jobs()) == 1)

    print("\n3) Loeschen vor start() trifft nur den gemeinten")
    JD.write_text(json.dumps(ALT + [{"id": "x", "label": "X", "cron": "* * * * *",
                                     "task": "t", "enabled": False, "once": False}]))
    cm = baue(JD)
    sicher(cm.delete_job, "x")
    rest = sicher(lambda: json.loads(JD.read_text()))
    ids = [j.get("id") for j in rest] if isinstance(rest, list) else []
    check("der fremde Auftrag ueberlebt das Loeschen "
          f"(gefunden: {ids})", ids == ["system_auto_update"])

    print("\n4) _save ist fail-closed (zweite Schranke)")
    JD.write_text(json.dumps(ALT))
    cm = baue(JD)
    cm._jobs.append({"id": "direkt", "label": "d"})   # am CRUD-Weg vorbei
    sicher(cm._save)
    auf_platte = sicher(lambda: json.loads(JD.read_text()))
    ids = [j.get("id") for j in auf_platte] if isinstance(auf_platte, list) else []
    check("ein nie geladener Bestand wird NICHT geschrieben "
          f"(gefunden: {ids})", ids == ["system_auto_update"])
    # Positivkontrolle: nach dem Laden speichert _save sehr wohl - ohne sie
    # waere die Schranke auch von einem kaputten _save nicht zu unterscheiden.
    cm = baue(JD)
    cm._ensure_loaded()
    cm._jobs.append({"id": "direkt", "label": "d"})
    sicher(cm._save)
    ids = [j.get("id") for j in json.loads(JD.read_text())]
    check("POSITIVKONTROLLE: nach dem Laden speichert _save", "direkt" in ids)

    print("\n5) Geladen wird genau EINMAL")
    JD.write_text(json.dumps(ALT))
    cm = baue(JD)
    cm._ensure_loaded()
    cm._jobs.append({"id": "im_speicher", "label": "s"})
    JD.write_text(json.dumps([]))        # jemand aendert die Platte daneben
    cm._ensure_loaded()                  # darf NICHT neu laden
    check("ein zweites _ensure_loaded verwirft die Speicher-Aenderung nicht",
          any(j.get("id") == "im_speicher" for j in cm._jobs))

    print("\n6) REGEL: jeder CRUD-Weg laedt selbst")
    kl = next(n for n in ast.parse(src).body
              if isinstance(n, ast.ClassDef) and n.name == "CronManager")
    ZIEL = {"list_jobs", "get_job", "add_job", "update_job", "delete_job",
            "claim_job"}
    gefunden = set()
    for m in kl.body:
        if isinstance(m, ast.FunctionDef) and m.name in ZIEL:
            ruft = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_ensure_loaded"
                for n in ast.walk(m))
            if ruft:
                gefunden.add(m.name)
    check(f"alle {len(ZIEL)} CRUD-Methoden rufen _ensure_loaded "
          f"(fehlen: {sorted(ZIEL - gefunden) or 'keine'})", gefunden == ZIEL)
    check("POSITIVKONTROLLE: es wurden ueberhaupt Methoden geprueft",
          len(ZIEL & {m.name for m in kl.body
                      if isinstance(m, ast.FunctionDef)}) == len(ZIEL))
finally:
    shutil.rmtree(SAND, ignore_errors=True)

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
