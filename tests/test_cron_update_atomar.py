#!/usr/bin/env python3
"""Waechter: ein abgelehnter Cron-PUT aendert NICHTS – auch nicht die CVE-Optionen.

Code-Review 2026-11-01: ``PUT /api/cron/{id}`` speicherte die CVE-Optionen
(``set_cve_payload``) VOR ``update_job``. Scheiterte danach der Cron-Ausdruck,
kam 400 "nicht gespeichert" – und ``beheben: true`` stand trotzdem auf der
Platte. Der Auftrag behob ab da automatisch, waehrend die Oberflaeche einen
Fehlschlag gemeldet hatte.

Was festgehalten wird (``update_job`` laeuft WIRKLICH, gegen eine
Wegwerf-``jobs.json``; apscheduler ist eine Attrappe, deren ``from_crontab``
wie das Original bei einem kaputten Ausdruck wirft):

0. Positivkontrolle: ein gueltiger PUT mit ``cve`` aendert Payload UND Datei.
1. Ungueltiger Cron + ``cve`` -> ValueError, Payload im Speicher UND auf der
   Platte unveraendert.
2. Ungueltige CVE-Optionen + gueltiger Cron -> ValueError, Cron unveraendert.
3. ``cve`` an einem Nicht-CVE-Auftrag -> ValueError, nichts geaendert.
4. Der Endpunkt speichert nur noch ueber ``update_job`` (kein Vorab-Speichern).

    python3 tests/test_cron_update_atomar.py
"""
import ast
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if "backend.config" in sys.modules:
    print("ABBRUCH: backend.config ist bereits geladen.", file=sys.stderr)
    raise SystemExit(2)

_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


class _Leer:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return lambda *a, **k: None


def _crontab(ausdruck, *a, **k):
    # Wie das Original: fuenf Felder, sonst ValueError.
    if not isinstance(ausdruck, str) or len(ausdruck.split()) != 5:
        raise ValueError(f"Wrong number of fields; got {ausdruck!r}")
    return object()


def _stub(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m


for n in ("apscheduler", "apscheduler.schedulers", "apscheduler.triggers"):
    _stub(n)
_stub("apscheduler.schedulers.asyncio", AsyncIOScheduler=_Leer)
_stub("apscheduler.triggers.cron",
      CronTrigger=type("CronTrigger", (), {"from_crontab": staticmethod(_crontab)}))

try:
    from backend import scheduler as SCH
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.scheduler nicht ladbar: {e!r}", file=sys.stderr)
    raise SystemExit(2)
if "backend.config" in sys.modules:
    print("ABBRUCH: scheduler hat backend.config nachgeladen.", file=sys.stderr)
    raise SystemExit(2)

tmp = Path(tempfile.mkdtemp(prefix="cron_atomar_"))
try:
    SCH.JOBS_FILE = tmp / "jobs.json"
    BESTAND = [
        {"id": "cve", "label": "CVE", "cron": "0 3 * * *", "task": "", "enabled": False,
         "kind": "cve_pruefung", "payload": {"beheben": False, "schwelle": ""},
         "owner": "a", "owner_privileged": True, "aussenwirkung": True},
        {"id": "agent", "label": "Agent", "cron": "0 4 * * *", "task": "x", "enabled": False,
         "kind": "agent", "owner": "a", "owner_privileged": True, "aussenwirkung": True},
    ]

    def frisch():
        SCH.JOBS_FILE.write_text(json.dumps(BESTAND))
        return SCH.CronManager()

    def platte(job_id):
        return next(j for j in json.loads(SCH.JOBS_FILE.read_text()) if j["id"] == job_id)

    # ─── 0. Positivkontrolle ─────────────────────────────────────────────────
    print("\n0. Positivkontrolle: gueltiger PUT mit cve")
    cm = frisch()
    if cm.get_job("cve") is None:
        print("ABBRUCH: Bestand nicht geladen.", file=sys.stderr)
        raise SystemExit(2)
    try:
        cm.update_job("cve", cron="0 5 * * *", cve={"beheben": True, "schwelle": "alle"})
    except Exception as e:  # noqa: BLE001
        print(f"ABBRUCH: gueltiger PUT scheitert: {e!r}", file=sys.stderr)
        raise SystemExit(2)
    if not (platte("cve")["payload"].get("beheben") is True and platte("cve")["cron"] == "0 5 * * *"):
        print(f"ABBRUCH: gueltiger PUT kommt nicht auf der Platte an: {platte('cve')}",
              file=sys.stderr)
        raise SystemExit(2)
    check(True, "gueltiger PUT setzt Cron UND Optionen (Speicher und Platte)")

    # ─── 1. ungueltiger Cron + cve ───────────────────────────────────────────
    print("\n1. ungueltiger Cron-Ausdruck mit cve")
    cm = frisch()
    try:
        cm.update_job("cve", cron="ungueltig", cve={"beheben": True, "schwelle": ""})
        geworfen = False
    except ValueError:
        geworfen = True
    check(geworfen, "ValueError (-> 400)")
    check(cm.get_job("cve")["payload"].get("beheben") is False,
          "beheben bleibt im Speicher AUS")
    check(platte("cve")["payload"].get("beheben") is False,
          "beheben bleibt auf der Platte AUS")
    check(platte("cve")["cron"] == "0 3 * * *", "Cron unveraendert")

    # ─── 2. ungueltige Optionen + gueltiger Cron ─────────────────────────────
    print("\n2. ungueltige CVE-Optionen mit gueltigem Cron")
    cm = frisch()
    try:
        cm.update_job("cve", cron="0 6 * * *", cve={"schwelle": "kritisch"})
        geworfen = False
    except ValueError:
        geworfen = True
    check(geworfen, "ValueError (-> 400)")
    check(cm.get_job("cve")["cron"] == "0 3 * * *" and platte("cve")["cron"] == "0 3 * * *",
          "Cron im Speicher und auf der Platte unveraendert")

    # ─── 3. cve an einem Nicht-CVE-Auftrag ───────────────────────────────────
    print("\n3. cve an einem anderen Auftrag")
    cm = frisch()
    try:
        cm.update_job("agent", label="Neu", cve={"beheben": True})
        geworfen = False
    except ValueError:
        geworfen = True
    check(geworfen, "ValueError (-> 400)")
    check("payload" not in cm.get_job("agent") and platte("agent")["label"] == "Agent",
          "kein Payload, Bezeichnung unveraendert")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ─── 4. Endpunkt: kein Vorab-Speichern mehr ──────────────────────────────────
print("\n4. PUT /api/cron/{id} speichert nur ueber update_job")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
ep = next((n for n in ast.walk(baum)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "cron_update"), None)
check(ep is not None, "Endpunkt cron_update gefunden")
if ep is not None:
    aufrufe = [c.func.attr for c in ast.walk(ep)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
               and isinstance(c.func.value, ast.Name) and c.func.value.id == "cron_manager"]
    check(aufrufe == ["update_job"],
          f"genau EIN schreibender Aufruf am cron_manager: update_job ({aufrufe})")

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
