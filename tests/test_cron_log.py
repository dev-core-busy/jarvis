#!/usr/bin/env python3
"""Waechter: Protokoll der Cron-Aufgaben (Vorgabe 2026-09-28: "bei den Tasks ->
Cron-Aufgaben fehlen logs").

GEMESSEN WIRD DIE WIRKUNG:
  1. ``backend/cron_log`` laeuft WIRKLICH in einem Sandkasten (Exit 2, wenn der
     Ablageort herauszeigt): Reihenfolge, Nachladen, Status, Kennungs-Schranke,
     Kuerzung nach Alter, "wirft nie".
  2. ``CronManager._execute``/``run_now`` werden per ``ast`` aus
     ``backend/scheduler.py`` geschnitten und AUSGEFUEHRT (apscheduler ist
     gestellt) – schreibt JEDER Lauf einen Eintrag, auch ein gescheiterter und
     der einzige eines Einmal-Jobs?
  3. Der Endpunkt ``cron_log_lesen`` wird aus ``backend/main.py`` geschnitten und
     ausgefuehrt: ein fremder Auftrag -> 404, OHNE dass gelesen wird.
  4. ``log_retention.run_all`` raeumt das Protokoll mit ab (Speicher gestellt).

``backend.config`` wird nirgends importiert (der echte Import schreibt die
Live-``settings.json``).
"""
from __future__ import annotations

import ast
import asyncio
import json
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def section(t): print(f"\n\033[1m{t}\033[0m")


def check(desc, cond, info=""):
    global OK, FAIL
    if cond:
        OK += 1; print(f"  \033[32m✓\033[0m {desc}")
    else:
        FAIL += 1; print(f"  \033[31m✗\033[0m {desc}" + (f" – {info}" if info else ""))


def sicher(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


SAND = Path(tempfile.mkdtemp(prefix="cronlog-test-"))
try:
    # ════════════════════════════════════════════════════════════════════════
    section("0. Sandkasten")
    import backend.cron_log as cl  # noqa: E402
    ECHT = cl._ordner()
    ECHT_VOR = sorted(p.name for p in ECHT.glob("*")) if ECHT.is_dir() else None
    cl._ordner = lambda: SAND / "logs" / "cron"          # type: ignore[assignment]
    if SAND not in cl._ordner().parents:
        print("  Sandkasten greift NICHT – Abbruch"); sys.exit(2)
    check("Ablage zeigt in den Sandkasten", True)

    # ════════════════════════════════════════════════════════════════════════
    section("1. Eintragen und Lesen")
    J = {"id": "job-1", "label": "Bericht", "kind": "agent"}
    t = 1_790_000_000
    for i in range(7):
        cl.eintragen(J, t + i * 60, t + i * 60 + 2.5, f"Lauf {i}\nZeile 2",
                     ausloeser="manuell" if i == 3 else "zeitplan",
                     von="m.mustermann" if i == 3 else "")
    cl.eintragen(J, t + 500, t + 501, "Fehler: kaputt")
    alle = cl.lesen("job-1", 50)
    check("(Positivkontrolle) acht Laeufe gelesen", len(alle) == 8, str(len(alle)))
    check("⚠ neueste zuerst", [e["ts"] for e in alle] == sorted((e["ts"] for e in alle), reverse=True),
          str([e["ts"] for e in alle]))
    check("Ergebnis steht VOLLSTAENDIG da (mit Zeilenumbruch)",
          any(e["ergebnis"] == "Lauf 6\nZeile 2" for e in alle), str(alle[1]))
    check("Dauer in Sekunden", all(e["dauer_s"] in (2.5, 1.0) for e in alle), str([e["dauer_s"] for e in alle]))
    m = [e for e in alle if e["ausloeser"] == "manuell"]
    check("manueller Lauf mit Ausloeser und Person", len(m) == 1 and m[0]["von"] == "m.mustermann", str(m))
    check("⚠ 'Fehler: …' ist ein gescheiterter Lauf", alle[0]["ok"] is False and alle[1]["ok"] is True,
          str(alle[:2]))
    check("Datei ist 0640", oct((SAND / "logs/cron/job-1.jsonl").stat().st_mode & 0o777) == "0o640")

    teil = cl.lesen("job-1", 3)
    check("limit wird eingehalten", len(teil) == 3)
    weiter = cl.lesen("job-1", 3, vor=teil[-1]["ts"])
    check("⚠ Nachladen mit 'vor' liefert die NAECHST aelteren, ohne Ueberschneidung",
          [e["ts"] for e in weiter] == [e["ts"] for e in alle[3:6]], str([e["ts"] for e in weiter]))
    check("unbekannter Auftrag: leere Liste", cl.lesen("gibt-es-nicht") == [])

    # Rueckwaerts-Lesen ueber Blockgrenzen (64 KiB): lange Ergebnisse
    J2 = {"id": "gross", "label": "g"}
    for i in range(40):
        cl.eintragen(J2, t + i, t + i, f"{i:03d}" + "x" * 5000)
    g = cl.lesen("gross", 500)
    check("⚠ Blockgrenzen: alle 40 langen Eintraege, keiner zerschnitten",
          len(g) == 40 and [int(e["ergebnis"][:3]) for e in g] == list(range(39, -1, -1)),
          f"{len(g)} Eintraege")

    riesig = "y" * (cl.ERGEBNIS_MAX + 10)
    cl.eintragen({"id": "lang"}, t, t, riesig)
    e = (cl.lesen("lang") or [{}])[0]
    check("uebergrosses Ergebnis gekuerzt UND als gekuerzt markiert",
          len(e.get("ergebnis", "")) == cl.ERGEBNIS_MAX and e.get("gekuerzt") is True)

    # ════════════════════════════════════════════════════════════════════════
    section("2. Kennungs-Schranke und 'wirft nie'")
    vorher = sorted(str(p.relative_to(SAND)) for p in SAND.rglob("*"))
    r = sicher(cl.eintragen, {"id": "../boese"}, t, t, "x")
    nachher = sorted(str(p.relative_to(SAND)) for p in SAND.rglob("*"))
    check("⚠ Kennung mit '../' wird NICHT geschrieben (auch nicht bereinigt)",
          r is None and vorher == nachher and not (SAND / "logs" / "boese.jsonl").exists(), str(nachher))
    check("…und nicht gelesen", cl.lesen("../job-1") == [])
    check("leere Kennung: nichts", sicher(cl.eintragen, {}, t, t, "x") is None and cl.lesen("") == [])
    blockiert = SAND / "blockiert"
    blockiert.write_text("ich bin eine Datei")
    cl._ordner = lambda: blockiert / "cron"                # type: ignore[assignment]
    check("⚠ nicht schreibbarer Ablageort: eintragen WIRFT NICHT",
          sicher(cl.eintragen, J, t, t, "x") is None)
    cl._ordner = lambda: SAND / "logs" / "cron"            # type: ignore[assignment]
    kaputt = SAND / "logs/cron/kaputt.jsonl"
    kaputt.write_text('{"ts": 5, "ergebnis": "gut"}\n{kaputt\n[1,2]\n', encoding="utf-8")
    check("beschaedigte Zeilen werden uebersprungen", [x.get("ergebnis") for x in cl.lesen("kaputt")] == ["gut"])

    # ════════════════════════════════════════════════════════════════════════
    section("3. Kuerzen nach Alter")
    grenze = t + 200
    vorab = {jid: cl.lesen(jid, 500) for jid in ("job-1", "gross", "lang", "kaputt")}
    erwartet_weg = sum(1 for es in vorab.values() for x in es if x.get("ts") and x["ts"] < grenze)
    erwartet_rest = [x["ts"] for x in vorab["job-1"] if x["ts"] >= grenze]
    weg = cl.kuerzen(grenze)
    rest = cl.lesen("job-1", 500)
    check("(Positivkontrolle) es gab aeltere UND neuere Eintraege",
          erwartet_weg > 0 and len(erwartet_rest) > 0, f"{erwartet_weg}/{erwartet_rest}")
    check("⚠ Eintraege vor der Grenze entfernt, neuere bleiben",
          [x["ts"] for x in rest] == erwartet_rest, str([x["ts"] for x in rest]))
    check("Anzahl stimmt (alle Dateien zusammen)", weg == erwartet_weg, f"{weg} statt {erwartet_weg}")
    check("leer gewordene Datei ist weg", not (SAND / "logs/cron/gross.jsonl").exists())
    ohne = SAND / "logs/cron/ohnezeit.jsonl"
    ohne.write_text('{"ergebnis": "ohne ts"}\n', encoding="utf-8")
    cl.kuerzen(time.time() + 10)
    check("⚠ Eintrag OHNE Zeitstempel bleibt stehen (kein Altersbeweis)",
          ohne.exists() and "ohne ts" in ohne.read_text())
    check("0640 bleibt nach dem Kuerzen", oct((SAND / "logs/cron/kaputt.jsonl").stat().st_mode & 0o777) == "0o640"
          if (SAND / "logs/cron/kaputt.jsonl").exists() else True)

    # ════════════════════════════════════════════════════════════════════════
    section("4. Scheduler: jeder Lauf schreibt einen Eintrag (echter Code)")
    src = (ROOT / "backend" / "scheduler.py").read_text(encoding="utf-8")
    baum = ast.parse(src)
    teile = {n.name: ast.get_source_segment(src, n) for n in baum.body
             if isinstance(n, ast.ClassDef) and n.name in ("CronManager", "JobsUnlesbar")}
    if "CronManager" not in teile:
        print("  CronManager nicht gefunden – NICHT PRUEFBAR"); sys.exit(2)

    class _Sched:
        running = False
        def add_job(self, *a, **k): pass
        def remove_job(self, *a, **k): pass
        def get_job(self, *a, **k): return None
        def start(self): pass

    class _Trig:
        @staticmethod
        def from_crontab(e, **k): return object()

    class _Agent:
        def __init__(self): self.antwort = "fertig"
        async def run_task_headless(self, text, actor=None):
            if self.antwort == "WURF":
                raise RuntimeError("Agent tot")
            return self.antwort

    class _AM:
        def __init__(self): self.a = _Agent()
        def get_or_create_main(self): return self.a

    am = _AM()
    ns = {"AsyncIOScheduler": lambda **k: _Sched(), "CronTrigger": _Trig,
          "JOBS_FILE": SAND / "jobs.json", "json": json, "uuid": __import__("uuid"),
          "time": time, "asyncio": asyncio, "Optional": __import__("typing").Optional,
          "_agent_manager": am, "_broadcast_fn": None, "_LEGACY_ACTOR": "__x__", "print": print,
          "_atomar": __import__("backend.atomar", fromlist=["schreiben"])}   # seit 2026-10-18
    for k in ("JobsUnlesbar", "CronManager"):
        if k in teile:
            exec(teile[k], ns)  # noqa: S102
    cm = ns["CronManager"]()
    job = cm.add_job(label="Nachtbericht", cron="0 3 * * *", task="Bericht", owner="admin",
                     owner_privileged=True, job_id="nacht")
    asyncio.run(cm._execute("nacht"))
    e = (cl.lesen("nacht") or [{}])[0]
    check("⚠ Lauf nach Zeitplan protokolliert", e.get("ausloeser") == "zeitplan" and e.get("ergebnis") == "fertig"
          and e.get("ok") is True and e.get("label") == "Nachtbericht", str(e))
    asyncio.run(cm.run_now("nacht", von="m.mustermann"))
    e = (cl.lesen("nacht") or [{}])[0]
    check("⚠ 'Jetzt ausfuehren' protokolliert als manuell, mit Person",
          e.get("ausloeser") == "manuell" and e.get("von") == "m.mustermann", str(e))
    am.a.antwort = "WURF"
    asyncio.run(cm._execute("nacht"))
    e = (cl.lesen("nacht") or [{}])[0]
    check("⚠ ein geworfener Lauf ist protokolliert – als Fehler, mit Grund",
          e.get("ok") is False and "Agent tot" in (e.get("ergebnis") or ""), str(e))
    check("drei Laeufe, drei Eintraege", len(cl.lesen("nacht")) == 3)
    am.a.antwort = "einmal erledigt"
    cm.add_job(label="Einmal", cron="0 4 * * *", task="x", job_id="einmal", once=True)
    asyncio.run(cm._execute("einmal"))
    check("⚠ Einmal-Job: gelöscht, aber sein einziger Lauf steht im Protokoll",
          cm.get_job("einmal") is None and (cl.lesen("einmal") or [{}])[0].get("ergebnis") == "einmal erledigt")
    # Scheitert das Protokoll, laeuft der Auftrag trotzdem
    cl._ordner = lambda: blockiert / "cron"                # type: ignore[assignment]
    r = asyncio.run(cm._execute("nacht"))
    cl._ordner = lambda: SAND / "logs" / "cron"            # type: ignore[assignment]
    check("⚠ Protokoll nicht schreibbar: der Lauf geht trotzdem durch",
          r == "einmal erledigt" and (cm.get_job("nacht") or {}).get("last_result") == "einmal erledigt", str(r))

    # ════════════════════════════════════════════════════════════════════════
    section("5. Endpunkt: dieselbe Sichtbarkeit wie die Liste")
    msrc = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    mb = ast.parse(msrc)
    fn = next((n for n in mb.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "cron_log_lesen"), None)
    if fn is None:
        print("  cron_log_lesen nicht gefunden – NICHT PRUEFBAR"); sys.exit(2)
    fn.decorator_list = []

    class HTTPException(Exception):
        def __init__(self, status_code, detail=""):
            super().__init__(detail); self.status_code = status_code

    class JSONResponse:
        def __init__(self, content, status_code=200):
            self.content, self.status_code = content, status_code

    GELESEN = []
    echt_lesen = cl.lesen
    def _mitschnitt(*a, **k):
        GELESEN.append(a); return echt_lesen(*a, **k)
    cl.lesen = _mitschnitt                                  # type: ignore[assignment]
    def _owned(jid, user):
        if user != "admin":
            raise HTTPException(404, "Job nicht gefunden")
        return {"id": jid}
    mns = {"JSONResponse": JSONResponse, "HTTPException": HTTPException, "Depends": lambda f: None,
           "require_auth": None, "_cron_owned_or_404": _owned, "asyncio": asyncio}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "main.py", "exec"), mns)  # noqa: S102
    backend_pkg = sys.modules.get("backend")
    r = asyncio.run(mns["cron_log_lesen"]("nacht", 2, None, user="admin"))
    check("(Positivkontrolle) Admin bekommt die Eintraege", r.content.get("ok") is True
          and len(r.content.get("eintraege") or []) == 2, str(r.content)[:200])
    check("'mehr' zeigt an, dass es aeltere gibt", r.content.get("mehr") is True)
    GELESEN.clear()
    r = sicher(lambda: asyncio.run(mns["cron_log_lesen"]("nacht", 50, None, user="fremd")))
    check("⚠ fremder Auftrag: 404 …", isinstance(r, HTTPException) and r.status_code == 404, repr(r))
    check("⚠ …und es wird GAR NICHT gelesen", GELESEN == [], str(GELESEN))
    cl.lesen = echt_lesen                                   # type: ignore[assignment]

    # ════════════════════════════════════════════════════════════════════════
    section("6. Aufbewahrung: log_retention raeumt das Protokoll mit ab")
    for name, attr in (("conv_log", "prune_older_than"), ("audit_log", "prune_older_than"),
                       ("mail_rules", "protokoll_kuerzen"), ("short_tracks", "protokoll_kuerzen")):
        m_ = types.ModuleType(f"backend.{name}"); setattr(m_, attr, lambda c: 0)
        sys.modules[f"backend.{name}"] = m_
    sys.modules["backend.conv_log"].prompts_entfernen = lambda c: 0   # BSI M9
    # Loeschfristen (BSI M9) als Attrappe: run_all bereinigt sonst echte Chats
    lfa = types.ModuleType("backend.loeschfristen")
    lfa.tage = lambda art: {"protokoll": 90, "sicherheit": 365}.get(art, 0)
    lfa.schnitt = lambda art, jetzt=None: None
    lfa.chats_bereinigen = lambda jetzt=None, daten=None: {"dauerhaft": True}
    sys.modules["backend.loeschfristen"] = lfa
    tel = types.ModuleType("backend.telemetry")
    tel.tracer = types.SimpleNamespace(prune_errors_older_than=lambda c: 0)
    sys.modules["backend.telemetry"] = tel
    import backend.log_retention as lr  # noqa: E402
    cl.eintragen({"id": "alt"}, time.time() - 400 * 86400, time.time() - 400 * 86400, "uralt")
    cl.eintragen({"id": "alt"}, time.time(), time.time(), "frisch")
    res = lr.run_all()
    check("(Positivkontrolle) Bereinigung lief ohne Fehler", res.get("ok") is True, str(res))
    check("⚠ run_all nennt das Cron-Protokoll und hat den alten Lauf entfernt",
          (res.get("removed") or {}).get("cron_log", 0) >= 1
          and [x["ergebnis"] for x in cl.lesen("alt")] == ["frisch"], str(res))
finally:
    shutil.rmtree(SAND, ignore_errors=True)

check("⚠ die echte Ablage ist unveraendert",
      (sorted(p.name for p in ECHT.glob("*")) if ECHT.is_dir() else None) == ECHT_VOR)
print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
sys.exit(1 if FAIL else 0)
