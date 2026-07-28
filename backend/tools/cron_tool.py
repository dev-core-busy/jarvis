"""Cron-Tools – zeitgesteuerte Auftraege fuer den Jarvis-Agent.

SICHERHEIT (seit 2026-07-28): Ein Cron-Job ist eine ZEITVERSETZTE Ausfuehrung.
Wer ihn anlegen darf, entscheidet damit ueber einen spaeteren Lauf – und bis
2026-07-28 lief dieser Lauf mit der Identitaet, die zufaellig am geteilten
Hauptagenten hing (leerer Wert = privilegiert). Ein Domain-Nutzer konnte sich so
per Chat einen Auftrag anlegen, der spaeter mit Root-Rechten feuert.

Zwei Schranken greifen hier:
1. Der ANLEGENDE Benutzer wird im Job festgeschrieben (owner/owner_privileged,
   gesetzt aus dem Dispatch in agent.py) und regiert dessen Ausfuehrung.
2. Ein unprivilegierter Benutzer darf keinen Auftrag anlegen, dessen Text auf
   System-/Root-Absicht deutet. Das ist eine ZUSATZschranke: sie faengt den
   Versuch frueh und sichtbar ab. Die harte Garantie liefert (1) – deshalb ist
   eine Umschreibung des Textes ("bitte als root", verschleiert) kein Loch,
   sondern laeuft spaeter einfach in die Rechte des Anlegenden.
"""

import re

from backend.tools.base import BaseTool

# System-/Root-Absicht im Auftragstext. Deckungsgleich gehalten mit
# agent.py::_LDAP_SHELL_FORBIDDEN – bewusst etwas breiter (natuerliche Sprache),
# weil hier ein Auftrag FUER ein Modell steht und kein Shell-Befehl.
_ROOT_INTENT = re.compile(
    r'\b(?:sudo|su\s|root(?:rechte|-rechte)?|systemctl|service\s+\S+\s+(?:start|stop|restart)|'
    r'apt(?:-get)?\b|dpkg\b|pip3?\s+install|npm\s+install|'
    r'crontab|/etc/(?:cron|shadow|passwd|sudoers)|'
    r'useradd|usermod|userdel|groupadd|passwd\b|chpasswd|'
    r'chmod|chown|chattr|mkfs|fdisk|'
    r'reboot|shutdown|poweroff|halt\b|'
    r'\.ssh/|id_rsa|id_ed25519|authorized_keys|'
    r'\.env\b|settings\.json|auth_state\.json|shadow\b)',
    re.IGNORECASE,
)


def _root_intent(text: str) -> str:
    """Gibt den erkannten Treffer zurueck ('' = unauffaellig)."""
    m = _ROOT_INTENT.search(text or "")
    return m.group(0) if m else ""


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
        username = (kwargs.get("_username") or "").strip()
        privileged = bool(kwargs.get("_privileged"))
        # Schranke 2 (siehe Modul-Docstring): kein System-Auftrag von einem
        # unprivilegierten Benutzer. Der Versuch wird protokolliert – ein
        # zeitversetzter Root-Auftrag ist kein Bedienfehler.
        if not privileged:
            hit = _root_intent(f"{label}\n{task}")
            if hit:
                print(f"[CRON] BLOCKED Auftrag mit System-Absicht ('{hit}') von "
                      f"'{username or 'unbekannt'}': {task[:120]}", flush=True)
                try:
                    from backend import security_guard as _sg
                    _sg.record_violation(
                        username or "unbekannt", "chat", "cron-root-intent", hit,
                        snippet=task[:200], tool="cron_create", task=task[:300],
                        client_type=kwargs.get("_client_type") or "")
                except Exception as e:  # noqa: BLE001
                    print(f"[CRON] record_violation fehlgeschlagen: {e}", flush=True)
                return (
                    f"Zugriff verweigert: Dieser zeitgesteuerte Auftrag enthält eine "
                    f"System-/Root-Anweisung ('{hit}'). Zeitgesteuerte Aufträge laufen mit "
                    f"deinen Rechten – System-Änderungen muss ein Administrator anlegen."
                )
        try:
            from backend.scheduler import cron_manager
            job = cron_manager.add_job(
                label=label, cron=cron, task=task, once=einmalig,
                owner=username, owner_privileged=privileged,
                created_via=f"chat:{kwargs.get('_client_type') or 'agent'}")
            einmalig_info = " (einmalig, wird danach automatisch gelöscht)" if einmalig else " (wiederkehrend)"
            rechte = "mit Systemrechten" if privileged else "mit deinen Benutzerrechten"
            return (
                f"Cron-Job erstellt{einmalig_info}:\n"
                f"  ID:       {job['id']}\n"
                f"  Label:    {label}\n"
                f"  Zeitplan: {cron}\n"
                f"  Aufgabe:  {task[:120]}\n"
                f"  Läuft:    {rechte} ({username or 'System'})"
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
        # Unprivilegierte Benutzer sehen nur ihre eigenen Auftraege: der Text
        # eines fremden Auftrags verraet Ablaeufe, Empfaenger und Pfade. Die
        # ANZAHL wird genannt, damit die Liste nicht faelschlich vollstaendig
        # wirkt (gleiche Regel wie bei data/documents).
        if not kwargs.get("_privileged"):
            _me = (kwargs.get("_username") or "").strip()
            _own = [j for j in jobs if (j.get("owner") or "") == _me and _me]
            _hidden = len(jobs) - len(_own)
            jobs = _own
        else:
            _hidden = 0
        if not jobs:
            return ("Keine Cron-Jobs vorhanden."
                    + (f" ({_hidden} Auftrag/Aufträge anderer Benutzer ausgeblendet)"
                       if _hidden else ""))
        lines = [f"{len(jobs)} Cron-Job(s):"
                 + (f" ({_hidden} von anderen Benutzern ausgeblendet)" if _hidden else "")]
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
            # Fremde Auftraege sind fuer unprivilegierte Benutzer unantastbar –
            # und die Antwort verraet nicht, dass sie existieren (wie beim
            # Dokument-Download: 404 statt 403).
            if not kwargs.get("_privileged"):
                _me = (kwargs.get("_username") or "").strip()
                if not _me or (job.get("owner") or "") != _me:
                    return f"Kein Job mit ID '{job_id}' gefunden."
            label = job["label"]
            cron_manager.delete_job(job_id)
            return f"Cron-Job '{label}' ({job_id[:8]}) gelöscht."
        except Exception as e:
            return f"Fehler: {e}"
