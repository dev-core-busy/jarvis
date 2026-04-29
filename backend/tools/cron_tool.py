"""Cron-Tools – zeitgesteuerte Auftraege fuer den Jarvis-Agent."""

from backend.tools.base import BaseTool


class CronCreateTool(BaseTool):
    """Erstellt einen zeitgesteuerten Cron-Job (einmalig oder wiederkehrend)."""

    @property
    def name(self) -> str:
        return "cron_create"

    @property
    def description(self) -> str:
        return (
            "Erstellt einen zeitgesteuerten Auftrag (Cron-Job). "
            "Ideal fuer Erinnerungen, geplante WhatsApp-Nachrichten oder wiederkehrende Aufgaben.\n\n"
            "Cron-Format: 'Minute Stunde Tag Monat Wochentag' (Timezone: Europe/Berlin)\n"
            "Beispiele:\n"
            "  15 6 30 4 *   → einmalig am 30.04. um 06:15\n"
            "  0 8 * * 1-5   → Mo–Fr um 08:00\n"
            "  30 7 * * *    → taeglich um 07:30\n"
            "  0 * * * *     → jede volle Stunde\n\n"
            "Fuer WhatsApp-Erinnerungen:\n"
            "  task = 'Sende WhatsApp an +49XXXXXXXXXX: Deine Erinnerungsnachricht'\n\n"
            "Mit einmalig=True wird der Job nach einmaligem Ausfuehren automatisch geloescht."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "label": {
                    "type": "STRING",
                    "description": "Kurze Beschreibung, z.B. 'WA Erinnerung Datensicherung'",
                },
                "cron": {
                    "type": "STRING",
                    "description": "Cron-Ausdruck im Format 'Min Std Tag Mon Wochentag', z.B. '15 6 30 4 *'",
                },
                "task": {
                    "type": "STRING",
                    "description": "Aufgabe die ausgefuehrt wird, z.B. 'Sende WhatsApp an +49XXX: Text'",
                },
                "einmalig": {
                    "type": "BOOLEAN",
                    "description": "True = Job loescht sich nach einmaligem Ausfuehren automatisch (fuer Erinnerungen)",
                },
            },
            "required": ["label", "cron", "task"],
        }

    async def execute(self, label: str = "", cron: str = "", task: str = "",
                      einmalig: bool = False, **kwargs) -> str:
        if not label or not cron or not task:
            return "Fehler: label, cron und task sind Pflichtfelder."
        try:
            from backend.scheduler import cron_manager
            job = cron_manager.add_job(label=label, cron=cron, task=task, once=einmalig)
            einmalig_info = " (einmalig, wird danach automatisch gelöscht)" if einmalig else " (wiederkehrend)"
            return (
                f"Cron-Job erstellt{einmalig_info}:\n"
                f"  ID:       {job['id']}\n"
                f"  Label:    {label}\n"
                f"  Zeitplan: {cron}\n"
                f"  Aufgabe:  {task[:120]}"
            )
        except ValueError as e:
            return f"Fehler – ungültiger Cron-Ausdruck: {e}"
        except Exception as e:
            return f"Fehler beim Erstellen des Jobs: {e}"


class CronListTool(BaseTool):
    """Listet alle vorhandenen Cron-Jobs auf."""

    @property
    def name(self) -> str:
        return "cron_list"

    @property
    def description(self) -> str:
        return "Zeigt alle vorhandenen zeitgesteuerten Auftraege (Cron-Jobs) mit Zeitplan und letztem Ergebnis."

    def parameters_schema(self) -> dict:
        return {"type": "OBJECT", "properties": {}, "required": []}

    async def execute(self, **kwargs) -> str:
        from backend.scheduler import cron_manager
        jobs = cron_manager.list_jobs()
        if not jobs:
            return "Keine Cron-Jobs vorhanden."
        lines = [f"{len(jobs)} Cron-Job(s):"]
        for j in jobs:
            status = "aktiv" if j.get("enabled") else "deaktiviert"
            einmalig = " [einmalig]" if j.get("once") else ""
            last = j.get("last_run")
            last_str = ""
            if last:
                import time
                import datetime
                last_str = f", zuletzt: {datetime.datetime.fromtimestamp(last).strftime('%d.%m. %H:%M')}"
            lines.append(f"  [{j['id'][:8]}] {j['label']} – {j['cron']} ({status}{einmalig}{last_str})")
            lines.append(f"    Aufgabe: {j['task'][:80]}")
        return "\n".join(lines)


class CronDeleteTool(BaseTool):
    """Loescht einen Cron-Job anhand seiner ID."""

    @property
    def name(self) -> str:
        return "cron_delete"

    @property
    def description(self) -> str:
        return "Löscht einen zeitgesteuerten Auftrag (Cron-Job) anhand seiner ID. ID mit cron_list abrufen."

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "job_id": {
                    "type": "STRING",
                    "description": "Die vollständige Job-ID (aus cron_list)",
                },
            },
            "required": ["job_id"],
        }

    async def execute(self, job_id: str = "", **kwargs) -> str:
        if not job_id:
            return "Fehler: job_id ist ein Pflichtfeld."
        try:
            from backend.scheduler import cron_manager
            # Auch Kurzform (erste 8 Zeichen) akzeptieren
            if len(job_id) < 32:
                match = next((j for j in cron_manager.list_jobs() if j["id"].startswith(job_id)), None)
                if match:
                    job_id = match["id"]
            job = cron_manager.get_job(job_id)
            if not job:
                return f"Kein Job mit ID '{job_id}' gefunden."
            label = job["label"]
            cron_manager.delete_job(job_id)
            return f"Cron-Job '{label}' ({job_id[:8]}) gelöscht."
        except Exception as e:
            return f"Fehler: {e}"
