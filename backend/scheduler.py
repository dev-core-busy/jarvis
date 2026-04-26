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
                job_id: str | None = None) -> dict:
        job = {
            "id": job_id or str(uuid.uuid4()),
            "label": label,
            "cron": cron,
            "task": task,
            "enabled": enabled,
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

    def update_job(self, job_id: str, **fields) -> dict:
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} nicht gefunden")
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

    # ─── Interna ─────────────────────────────────────────────────────────────

    def _register(self, job: dict):
        """Job im APScheduler registrieren."""
        try:
            trigger = CronTrigger.from_crontab(job["cron"], timezone="Europe/Berlin")
            self._scheduler.add_job(
                self._execute_sync,
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

    def _execute_sync(self, job_id: str):
        """Synchroner Wrapper – erstellt asyncio-Task."""
        loop = asyncio.get_event_loop()
        loop.create_task(self._execute(job_id))

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
                result = await agent.run_task_headless(task_text)
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

    def _save(self):
        JOBS_FILE.write_text(json.dumps(self._jobs, indent=2, ensure_ascii=False))


# Singleton
cron_manager = CronManager()
