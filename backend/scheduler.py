"""Jarvis Cron-Scheduler – proaktiver Agent via APScheduler."""

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

JOBS_FILE = Path("data/scheduled_jobs.json")

# Auftraggeber-Name für Jobs ohne gespeicherten Besitzer (Altbestand). Bewusst
# ein Name, der keinem echten Benutzer entspricht: er ist damit unprivilegiert
# UND besitzt keine Dokumente (Eigentümer-Schranke greift fail-closed).
_LEGACY_ACTOR = "__cron_ohne_besitzer__"

# Wird von main.py gesetzt
_agent_manager = None
_broadcast_fn = None  # async fn(msg: dict) → sendet an alle WS-Clients


def init(agent_manager, broadcast_fn):
    global _agent_manager, _broadcast_fn
    _agent_manager = agent_manager
    _broadcast_fn = broadcast_fn


class CronManager:
    def __init__(self):
        self._scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
        self._jobs: list[dict] = []

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    def start(self):
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load()
        for job in self._jobs:
            if job.get("enabled"):
                self._register(job)
        self._scheduler.start()
        print(f"[Scheduler] gestartet – {len(self._jobs)} Jobs geladen", flush=True)

    def stop(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    # ─── CRUD ────────────────────────────────────────────────────────────────

    def list_jobs(self) -> list[dict]:
        return self._jobs

    def get_job(self, job_id: str) -> Optional[dict]:
        return next((j for j in self._jobs if j["id"] == job_id), None)

    def add_job(self, label: str, cron: str, task: str, enabled: bool = True,
                job_id: str | None = None, once: bool = False,
                owner: str = "", owner_privileged: bool = False,
                created_via: str = "") -> dict:
        """Legt einen Job an.

        owner/owner_privileged sind die AUFTRAGGEBER-BINDUNG: sie entscheiden,
        mit welchen Rechten der Job spaeter laeuft (siehe _execute). Ohne diese
        Bindung lief ein Job mit der Identitaet, die zufaellig am geteilten
        Hauptagenten hing – ein leerer Wert galt als privilegiert, ein Job eines
        Domain-Nutzers konnte also mit Root-Rechten feuern.
        Default ist bewusst unprivilegiert: privilegiert wird nur, wer es
        ausdruecklich anfordert und es auch selbst sein darf (siehe Aufrufer).
        """
        job = {
            "id": job_id or str(uuid.uuid4()),
            "label": label,
            "cron": cron,
            "task": task,
            "enabled": enabled,
            "once": once,   # True → Job löscht sich nach einmaligem Ausführen
            "owner": owner or "",
            "owner_privileged": bool(owner_privileged),
            "created_via": created_via or "",
            "created_at": int(time.time()),
            "last_run": None,
            "last_result": None,
        }
        self._validate_cron(cron)
        # Vorhandenen Job mit gleicher ID ersetzen
        self._jobs = [j for j in self._jobs if j["id"] != job["id"]]
        self._jobs.append(job)
        self._unregister(job["id"])
        if enabled:
            self._register(job)
        self._save()
        return job

    # Nur diese Felder dürfen von aussen geändert werden. Die Auftraggeber-Bindung
    # (owner/owner_privileged) ist NICHT dabei: sonst könnte sich ein Domain-Nutzer
    # per PUT selbst `owner_privileged: true` setzen und hätte damit genau die
    # Rechteerhöhung, die diese Bindung verhindern soll. Übernahme nur über
    # claim_job() (Admin).
    UPDATABLE_FIELDS = {"label", "cron", "task", "enabled", "once"}

    def update_job(self, job_id: str, **fields) -> dict:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} nicht gefunden")
        fields = {k: v for k, v in fields.items() if k in self.UPDATABLE_FIELDS}
        # Cron prüfen wenn geändert
        if "cron" in fields:
            self._validate_cron(fields["cron"])
        job.update(fields)
        # APScheduler-Job neu registrieren
        self._unregister(job_id)
        if job.get("enabled"):
            self._register(job)
        self._save()
        return job

    def delete_job(self, job_id: str):
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} nicht gefunden")
        self._unregister(job_id)
        self._jobs = [j for j in self._jobs if j["id"] != job_id]
        self._save()

    async def run_now(self, job_id: str) -> str:
        """Job sofort ausführen (unabhängig vom Zeitplan)."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} nicht gefunden")
        return await self._execute(job_id)

    def claim_job(self, job_id: str, user: str, privileged: bool) -> dict:
        """Auftraggeber-Bindung eines Jobs neu setzen (Admin-Übernahme).

        Der einzige Weg, einem Job Systemrechte zu geben – bewusst eine
        ausdrückliche Handlung eines Admins und kein Nebeneffekt eines Updates
        (vgl. UPDATABLE_FIELDS). Damit ist auch ein Altbestand-Job ohne Besitzer
        reparierbar, statt dauerhaft unprivilegiert zu scheitern.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} nicht gefunden")
        job["owner"] = user or ""
        job["owner_privileged"] = bool(privileged)
        job["claimed_at"] = int(time.time())
        self._save()
        return job

    # ─── Interna ─────────────────────────────────────────────────────────────

    def _register(self, job: dict):
        """Job im APScheduler registrieren."""
        try:
            trigger = CronTrigger.from_crontab(job["cron"], timezone="Europe/Berlin")
            # AsyncIOScheduler führt async-Funktionen direkt im Event-Loop aus –
            # kein synchroner Wrapper nötig (der hatte RuntimeError in Thread-Pool)
            self._scheduler.add_job(
                self._execute,
                trigger=trigger,
                id=job["id"],
                args=[job["id"]],
                replace_existing=True,
                misfire_grace_time=300,
            )
        except Exception as e:
            print(f"[Scheduler] Fehler beim Registrieren von '{job['label']}': {e}", flush=True)

    def _unregister(self, job_id: str):
        try:
            if self._scheduler.get_job(job_id):
                self._scheduler.remove_job(job_id)
        except Exception:
            pass

    async def _execute(self, job_id: str) -> str:
        """Job ausführen: Agent-Task headless starten."""
        job = self.get_job(job_id)
        if not job:
            return "Job nicht gefunden"

        task_text = job["task"]
        label = job["label"]
        print(f"[Scheduler] Starte Job '{label}': {task_text[:60]}...", flush=True)

        # Broadcast: Job gestartet
        if _broadcast_fn:
            await _broadcast_fn({
                "type": "cron_event",
                "event": "started",
                "job_id": job_id,
                "label": label,
            })

        result = "Fehler: AgentManager nicht verfügbar"
        t0 = time.time()
        try:
            if _agent_manager:
                agent = _agent_manager.get_or_create_main()
                result = await agent.run_task_headless(
                    task_text, actor=self._actor_for(job))
            duration = round(time.time() - t0, 1)
            result_short = (result[:200] + "…") if len(result) > 200 else result
            print(f"[Scheduler] Job '{label}' abgeschlossen in {duration}s", flush=True)
        except Exception as e:
            result = f"Fehler: {e}"
            duration = round(time.time() - t0, 1)
            print(f"[Scheduler] Job '{label}' Fehler: {e}", flush=True)

        # Ergebnis speichern
        job["last_run"] = int(time.time())
        job["last_result"] = result[:500] if result else ""
        self._save()

        # Einmalige Jobs nach Ausführung automatisch löschen
        if job.get("once"):
            try:
                self.delete_job(job_id)
                print(f"[Scheduler] Einmaliger Job '{label}' gelöscht.", flush=True)
            except Exception as _de:
                print(f"[Scheduler] Fehler beim Löschen von Einmal-Job: {_de}", flush=True)

        # Broadcast: Job fertig
        if _broadcast_fn:
            await _broadcast_fn({
                "type": "cron_event",
                "event": "finished",
                "job_id": job_id,
                "label": label,
                "result": job["last_result"],
            })

        return result

    def _actor_for(self, job: dict) -> dict:
        """Auftraggeber-Bindung eines Jobs in die Form für run_task_headless.

        Ein Job ohne Besitzer (Altbestand vor 2026-07-28) läuft UNPRIVILEGIERT –
        fail-closed. Sein Besitzer ist nicht rekonstruierbar, und die Alternative
        wäre genau die Lücke: bis 2026-07-28 erbte so ein Job die Rechte des
        zuletzt aktiven Chat-Nutzers, bei leerem Wert also Root über den Broker.
        Ein Admin kann ihn über claim_job() übernehmen.
        """
        owner = (job.get("owner") or "").strip()
        return {
            "user": owner or _LEGACY_ACTOR,
            "privileged": bool(job.get("owner_privileged")) and bool(owner),
            "internet": True,
            "sap": False,
        }

    def _validate_cron(self, cron_expr: str):
        """Wirft ValueError wenn Cron-Ausdruck ungültig."""
        try:
            CronTrigger.from_crontab(cron_expr)
        except Exception as e:
            raise ValueError(f"Ungültiger Cron-Ausdruck '{cron_expr}': {e}")

    def _load(self):
        if JOBS_FILE.exists():
            try:
                self._jobs = json.loads(JOBS_FILE.read_text())
            except Exception as e:
                print(f"[Scheduler] Fehler beim Laden der Jobs: {e}", flush=True)
                self._jobs = []
        else:
            self._jobs = []
        # Altbestand ohne Auftraggeber-Bindung sichtbar machen. Nicht geraten:
        # ohne Besitzer laeuft der Job unprivilegiert (siehe _actor_for), und die
        # Oberflaeche zeigt es an, damit ein Admin ihn bewusst uebernehmen kann.
        _legacy = 0
        for job in self._jobs:
            if "owner" not in job:
                job["owner"] = ""
                job["owner_privileged"] = False
                job["created_via"] = job.get("created_via") or "legacy"
                _legacy += 1
        if _legacy:
            print(f"[Scheduler] {_legacy} Job(s) ohne Auftraggeber – laufen "
                  f"unprivilegiert bis ein Admin sie uebernimmt "
                  f"(Einstellungen -> Cron -> Übernehmen)", flush=True)

    def _save(self):
        JOBS_FILE.write_text(json.dumps(self._jobs, indent=2, ensure_ascii=False))


# Singleton
cron_manager = CronManager()
