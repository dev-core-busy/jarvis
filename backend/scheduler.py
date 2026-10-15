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


class JobsUnlesbar(ValueError):
    """Die Auftragsliste existiert, laesst sich aber nicht lesen oder deuten.

    ValueError, damit die vorhandenen Endpunkte (``except ValueError`` -> 400)
    den Grund an die Oberflaeche reichen, statt mit 500 zu enden."""


def init(agent_manager, broadcast_fn):
    global _agent_manager, _broadcast_fn
    _agent_manager = agent_manager
    _broadcast_fn = broadcast_fn


class CronManager:
    def __init__(self):
        self._scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
        self._jobs: list[dict] = []
        # ⚠ DER BESTAND IST ERST NACH _load() GUELTIG - und das ist keine
        # Feinheit, sondern ein bezahlter Datenverlust (2026-09-21, ECHT):
        # ein Startup-Hook rief add_job(), BEVOR start() gelaufen war. _jobs war
        # dabei die leere Liste aus diesem Konstruktor, add_job haengte an, und
        # _save() schrieb eine Liste mit GENAU EINEM Eintrag auf die Platte -
        # der taegliche Auto-Update-Auftrag war damit weg. Kein Fehler, keine
        # Meldung: das Journal sagte nur "1 Jobs geladen", wie an jedem Tag
        # davor auch (dort war es der andere Job).
        # Deshalb entscheidet ab jetzt NICHT mehr die Aufrufreihenfolge:
        # jeder Zugriff laedt bei Bedarf selbst (_ensure_loaded), und _save()
        # verweigert den Dienst, solange nie geladen wurde.
        self._geladen = False
        # Zuletzt gemeldeter Ladefehler - damit ein dauerhaft unlesbarer
        # Bestand das Journal nicht bei JEDEM Zugriff erneut fuellt.
        self._ladefehler = ""

    # ─── Lifecycle ───────────────────────────────────────────────────────────

    def start(self):
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_loaded()
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
        self._ensure_loaded()
        return self._jobs

    def get_job(self, job_id: str) -> Optional[dict]:
        self._ensure_loaded()
        return next((j for j in self._jobs if j["id"] == job_id), None)

    def add_job(self, label: str, cron: str, task: str, enabled: bool = True,
                job_id: str | None = None, once: bool = False,
                owner: str = "", owner_privileged: bool = False,
                created_via: str = "", kind: str = "agent",
                payload: dict | None = None, aussenwirkung: bool = False) -> dict:
        """Legt einen Job an.

        owner/owner_privileged sind die AUFTRAGGEBER-BINDUNG: sie entscheiden,
        mit welchen Rechten der Job spaeter laeuft (siehe _execute). Ohne diese
        Bindung lief ein Job mit der Identitaet, die zufaellig am geteilten
        Hauptagenten hing – ein leerer Wert galt als privilegiert, ein Job eines
        Domain-Nutzers konnte also mit Root-Rechten feuern.
        Default ist bewusst unprivilegiert: privilegiert wird nur, wer es
        ausdruecklich anfordert und es auch selbst sein darf (siehe Aufrufer).

        kind unterscheidet ZWEI Job-Arten (seit 2026-07-29):
          'agent'    – der Auftragstext geht an den Agenten (Werkzeugkasten).
                       Nur Administratoren duerfen solche Jobs anlegen.
          'reminder' – reiner Sendeauftrag, `payload` = {channel,to,message}.
                       Wird DIREKT versendet, ohne LLM und ohne Werkzeuge
                       (siehe backend/reminders.py). Nur so kann ein
                       unprivilegierter Messenger-Absender eine Erinnerung
                       setzen, ohne sich damit einen zeitversetzten
                       Agentenlauf einzurichten.
          'wissensabgleich' – Wartungsauftrag (seit 2026-09-21): sieht nach, ob
                       sich in den Wissensordnern etwas geaendert hat, und
                       indiziert nur dann nach. Ebenfalls OHNE LLM und OHNE
                       Werkzeuge - ein Modell zu bitten, einen Reindex
                       anzustossen, waere teuer, unzuverlaessig und voellig
                       unnoetig fuer eine deterministische Wartungsaufgabe.

        ⚠ EINE NEUE ART GEHOERT IN DIE WHITELIST WEITER UNTEN. Steht sie nicht
        darin, wird der Job STILL zu einem Agentenlauf - er laeuft dann, tut
        etwas voellig anderes als bestellt, und niemand sieht warum.
        """
        self._schreibbar()
        job = {
            "id": job_id or str(uuid.uuid4()),
            "label": label,
            "cron": cron,
            "task": task,
            "enabled": enabled,
            "once": once,   # True → Job löscht sich nach einmaligem Ausführen
            "kind": kind if kind in ("agent", "reminder", "wissensabgleich") else "agent",
            "payload": dict(payload or {}),
            "owner": owner or "",
            "owner_privileged": bool(owner_privileged),
            "created_via": created_via or "",
            # BSI H8/H9-Rest (2026-10-11): darf der Agentenlauf dieses Auftrags
            # nach aussen wirken/loeschen? Vorgabe NEIN – nur ein echtes True.
            "aussenwirkung": aussenwirkung is True,
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
    # Ebenfalls NICHT dabei: `kind`/`payload` (seit 2026-07-29) – ein
    # Erinnerungs-Job (reiner Versand) dürfte sonst nachträglich in einen
    # Agenten-Job umgeschrieben werden und wäre damit wieder ein zeitversetzter
    # Auftrag mit Werkzeugkasten.
    # `aussenwirkung` (BSI H8/H9-Rest) IST dabei: der PUT ist admin-only
    # (_require_trigger_admin), und genau dort setzt ein Admin die Freigabe.
    UPDATABLE_FIELDS = {"label", "cron", "task", "enabled", "once", "aussenwirkung"}

    def update_job(self, job_id: str, **fields) -> dict:
        self._schreibbar()
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} nicht gefunden")
        fields = {k: v for k, v in fields.items() if k in self.UPDATABLE_FIELDS}
        if "aussenwirkung" in fields and not isinstance(fields["aussenwirkung"], bool):
            raise ValueError("aussenwirkung muss true/false sein")
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
        self._schreibbar()
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} nicht gefunden")
        self._unregister(job_id)
        self._jobs = [j for j in self._jobs if j["id"] != job_id]
        self._save()

    async def run_now(self, job_id: str, von: str = "") -> str:
        """Job sofort ausführen (unabhängig vom Zeitplan).

        ``von`` = wer ausgeloest hat – steht im Protokoll (backend/cron_log.py).
        Die RECHTE des Laufs haengen weiter am Besitzer (_actor_for), nicht hieran.
        """
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} nicht gefunden")
        return await self._execute(job_id, ausloeser="manuell", von=von)

    def claim_job(self, job_id: str, user: str, privileged: bool) -> dict:
        """Auftraggeber-Bindung eines Jobs neu setzen (Admin-Übernahme).

        Der einzige Weg, einem Job Systemrechte zu geben – bewusst eine
        ausdrückliche Handlung eines Admins und kein Nebeneffekt eines Updates
        (vgl. UPDATABLE_FIELDS). Damit ist auch ein Altbestand-Job ohne Besitzer
        reparierbar, statt dauerhaft unprivilegiert zu scheitern.
        """
        self._schreibbar()
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

    async def _execute(self, job_id: str, ausloeser: str = "zeitplan",
                       von: str = "") -> str:
        """Job ausführen: Agent-Task headless starten.

        ``ausloeser``/``von`` gehen nur ins Protokoll. Der APScheduler ruft mit
        ``args=[job_id]`` – also immer "zeitplan"."""
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
            if job.get("kind") == "reminder":
                # Reiner Sendeauftrag: KEIN Agent, kein LLM, kein Werkzeug.
                # Das ist die ganze Sicherheitsaussage der Erinnerungs-Ausnahme
                # (backend/reminders.py) – wer das hier durch einen Agentenlauf
                # ersetzt, macht aus jeder Erinnerung wieder einen zeitversetzten
                # Auftrag, den ein injizierter Nachrichtentext steuern kann.
                from backend import reminders
                result = await reminders.deliver(job.get("payload") or {})
            elif job.get("kind") == "wissensabgleich":
                # Wartungsauftrag: KEIN Agent, kein LLM, kein Werkzeug - aus
                # demselben Grund wie oben, nur andersherum begruendet: hier
                # gibt es schlicht nichts zu entscheiden. Der Lauf sieht nach,
                # ob sich etwas geaendert hat, und indiziert nur dann nach.
                #
                # ⚠ ERST Confluence, DANN der Index (Vorgabe 2026-09-27): der
                # Confluence-Abgleich schreibt geaenderte Seiten als Dateien in
                # die Wissensordner, und der Index-Abgleich danach nimmt sie im
                # SELBEN Takt auf - ueber den einen vorhandenen Indizierweg.
                # Andersherum laege jede Aenderung einen Takt laenger brach.
                from backend import rag_autoindex, confluence_abgleich
                cf = await asyncio.to_thread(confluence_abgleich.lauf)
                erg = await asyncio.to_thread(rag_autoindex.lauf)
                result = str(erg.get("grund") or "")
                if cf.get("aktiv"):
                    result += " · Confluence: " + str(cf.get("grund") or "")
            elif _agent_manager:
                agent = _agent_manager.get_or_create_main()
                from backend import wirkung as _wirkung
                with _wirkung.auftrag(f"Cron-Auftrag '{label}'",
                                      job.get("aussenwirkung") is True):
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

        # Protokoll: EIN Eintrag je Lauf (Vorgabe 2026-09-28). last_result
        # oben kennt nur den LETZTEN Lauf – der naechste ueberschreibt ihn.
        # ⚠ Wirft nie (cron_log.eintragen) – und steht VOR dem Loeschen eines
        # Einmal-Jobs, damit auch dessen einziger Lauf nachweisbar bleibt.
        try:
            from backend import cron_log
            cron_log.eintragen(job, t0, time.time(), result or "",
                               ausloeser=ausloeser, von=von)
        except Exception as _le:  # noqa: BLE001
            print(f"[Scheduler] Protokoll nicht geschrieben: {_le}", flush=True)

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

    def _schreibbar(self):
        """Vor jeder AENDERUNG: nur auf einem wirklich geladenen Bestand.

        ⚠ Code-Review 2026-09-28: bei einer unlesbaren ``jobs.json`` galt der
        Bestand trotzdem als geladen (``_jobs = []``) - der naechste
        ``add_job`` (etwa der Wissensabgleich beim Start) schrieb dann eine
        Liste mit genau EINEM Eintrag ueber die echten Auftraege. Dieselbe
        Folge wie am 2026-09-21, nur ueber den Ladefehler statt ueber die
        Reihenfolge. Hier wird LAUT abgewiesen, BEVOR ``_jobs`` oder der
        APScheduler angefasst werden - ein stiller Speicher-Verzicht liesse
        einen Auftrag im Speicher zurueck, den es auf der Platte nie gab."""
        self._ensure_loaded()
        if not self._geladen:
            raise JobsUnlesbar(
                "Die Liste der zeitgesteuerten Aufträge kann gerade nicht gelesen "
                "werden – es wird nichts verändert. Bitte den Administrator informieren.")

    def _ensure_loaded(self):
        """Den Bestand von der Platte holen, falls das noch nicht geschehen ist.

        ⚠ JEDER Zugriff auf _jobs laeuft hierueber - auch die lesenden. Der
        Grund ist der Vorfall vom 2026-09-21: ein Aufrufer VOR start() sah die
        leere Anfangsliste und hat damit den Bestand ueberschrieben. Wer das
        ueber die Reihenfolge der Startup-Hooks loesen will, loest es nur fuer
        die Hooks, die es heute gibt.
        """
        if not self._geladen:
            self._load()

    def _load(self):
        if JOBS_FILE.exists():
            try:
                jobs = json.loads(JOBS_FILE.read_text())
                if not isinstance(jobs, list) or not all(isinstance(j, dict) for j in jobs):
                    raise ValueError("unerwartete Form (keine Liste von Auftraegen)")
            except Exception as e:
                # ⚠ NICHT als geladen markieren: eine leere Liste aus einem
                # FEHLER ist kein Bestand und darf nie gespeichert werden
                # (_save verweigert, _schreibbar weist ab). Der naechste Zugriff
                # versucht es erneut - ein behobenes Rechteproblem heilt damit
                # ohne Neustart.
                grund = f"{type(e).__name__}: {e}"
                if grund != self._ladefehler:
                    print(f"[Scheduler] ⚠ {JOBS_FILE} nicht lesbar ({grund}) – "
                          f"Auftraege ruhen, Aendern ist gesperrt.", flush=True)
                    self._ladefehler = grund
                self._jobs = []
                return
            self._jobs = jobs
        else:
            self._jobs = []
        self._ladefehler = ""
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
        # BSI H8/H9-Rest (2026-10-11): Bestand behaelt sein Verhalten. Ein
        # Auftrag ohne das Feld stammt aus der Zeit, in der das Anlegen selbst
        # als Zustimmung galt (Betreiberentscheid 04.10.) – er bekommt die
        # Freigabe EINMALIG ausdruecklich festgeschrieben; neue starten ohne.
        _alt = [j for j in self._jobs if "aussenwirkung" not in j]
        for job in _alt:
            job["aussenwirkung"] = True
        # Erst ab hier ist _jobs der Bestand der Platte - vorher ist es die
        # leere Anfangsliste, und die darf nie gespeichert werden.
        self._geladen = True
        if _alt:
            print(f"[Scheduler] {len(_alt)} bestehende(r) Auftrag/Auftraege: Freigabe "
                  f"'Darf nach außen wirken' festgeschrieben (Bestand, BSI H9)", flush=True)
            self._save()

    def _save(self):
        """Den Bestand schreiben - aber NIE einen, der nie gelesen wurde.

        ⚠ FAIL-CLOSED, und die Richtung ist eine Abwaegung: eine nicht
        gespeicherte Aenderung ist nach dem naechsten Neustart weg (aergerlich),
        eine gespeicherte LEERE Liste loescht fremde Auftraege (teuer, und am
        2026-09-21 auf ECHT wirklich passiert). Im Normalbetrieb ist dieser
        Zweig unerreichbar, weil jeder CRUD-Weg vorher _ensure_loaded() ruft -
        er faengt den NAECHSTEN Pfad ab, der _jobs direkt anfasst.
        Still ist er nicht: ein uebergangener Schreibvorgang gehoert ins
        Journal, sonst sucht niemand nach der fehlenden Aenderung.
        """
        if not self._geladen:
            print("[Scheduler] ⚠ Speichern uebersprungen: der Bestand wurde nie "
                  "geladen. Das haette bestehende Auftraege geloescht.",
                  flush=True)
            return
        JOBS_FILE.write_text(json.dumps(self._jobs, indent=2, ensure_ascii=False))


# Singleton
cron_manager = CronManager()
