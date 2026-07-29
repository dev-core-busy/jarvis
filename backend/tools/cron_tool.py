"""Cron-Tools – zeitgesteuerte Auftraege fuer den Jarvis-Agent.

SICHERHEIT (seit 2026-07-28): Ein Cron-Job ist eine ZEITVERSETZTE Ausfuehrung.
Wer ihn anlegen darf, entscheidet damit ueber einen spaeteren Lauf – und bis
2026-07-28 lief dieser Lauf mit der Identitaet, die zufaellig am geteilten
Hauptagenten hing (leerer Wert = privilegiert). Ein Domain-Nutzer konnte sich so
per Chat einen Auftrag anlegen, der spaeter mit Root-Rechten feuert.

Drei Schranken greifen hier:
1. Der ANLEGENDE Benutzer wird im Job festgeschrieben (owner/owner_privileged,
   gesetzt aus dem Dispatch in agent.py) und regiert dessen Ausfuehrung.
2. ANLEGEN IST UNPRIVILEGIERTEN GANZ VERWEHRT (seit 2026-07-29). Schranke (1)
   regelt nur, MIT WELCHEN RECHTEN ein Auftrag laeuft – nicht, OB jemand sich
   einen dauerhaften, wiederkehrenden Agenten-Auslöser ausserhalb jeder
   Chat-Sitzung einrichten darf. Genau das blieb als Prompt-Injection-Weg offen
   (Telefon → Zusammenfassung → Agent legt Auftrag an; sofort aktiv, ohne
   Freigabe). Zeitgesteuerte Auftraege legt jetzt ausschliesslich ein
   Administrator an – gleiche Familie wie 'queue_add'/'reflection'/'evolution_*'
   in agent.py::_BLOCKED_TOOLS_FOR_LDAP.
3. Die System-/Root-Absicht im Auftragstext (_root_intent) dient jetzt nur noch
   der EINSTUFUNG des abgelehnten Versuchs im Sicherheitsprotokoll: "erinnere
   mich morgen" ist ein Bedienversuch, "systemctl restart" ein Angriffsindiz.

Das Anzeigen (cron_list) und Loeschen EIGENER Auftraege (cron_delete) bleibt
erlaubt: beides schafft keine Persistenz, und Altbestand aus der Zeit vor der
Sperre muss aufraeumbar bleiben.
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


# Einheitlicher Ablehnungstext fuer alle Wege (Tool, HTTP-API). Nennt den Grund
# und den gangbaren Weg – sonst probiert das Modell dieselbe Anfrage umformuliert
# erneut, und der Benutzer haelt es fuer einen Fehler.
CRON_DENIED_MSG = (
    "Zugriff verweigert: Zeitgesteuerte Aufträge (Cron) darf nur ein Administrator "
    "anlegen. Ein solcher Auftrag würde später außerhalb dieser Sitzung selbständig "
    "einen Agenten mit vollem Werkzeugkasten starten – das ist bewusst Admins "
    "vorbehalten. Bitte einen Administrator um Einrichtung."
)


def record_cron_denied(username: str, source: str, text: str, *,
                       tool: str = "cron_create", client_type: str = "") -> str:
    """Abgelehnten Anlege-Versuch protokollieren; gibt den Root-Treffer zurueck.

    Die Einstufung (Schranke 3 im Modul-Docstring) trennt Bedienversuche von
    Angriffsindizien: derselbe Endpunkt lehnt beides ab, aber nur eines davon
    gehoert einem Administrator gemeldet.

    WICHTIG – nur der Treffer geht als Verstoss ins Sicherheitsprotokoll:
    record_violation() sperrt Konten ab einer Schwelle. Wer dreimal "erinnere
    mich taeglich um 8" bittet, hat nichts angegriffen; wuerde jeder abgelehnte
    Versuch zaehlen, sperrte die neue Regel harmlose Benutzer aus. Der Versuch
    selbst steht im Journal (und ueber den Tool-Aufruf im Audit-Log).
    """
    hit = _root_intent(text)
    print(f"[CRON] DENIED Anlegen durch unprivilegierten Benutzer "
          f"'{username or 'unbekannt'}'{f' (System-Absicht: {hit})' if hit else ''}: "
          f"{text[:120]}", flush=True)
    if hit:
        try:
            from backend import security_guard as _sg
            _sg.record_violation(
                username or "unbekannt", source, "cron-root-intent", hit,
                snippet=text[:200], tool=tool, task=text[:300],
                client_type=client_type)
        except Exception as e:  # noqa: BLE001
            print(f"[CRON] record_violation fehlgeschlagen: {e}", flush=True)
    return hit


# "Sende WhatsApp an +49…: Text" → "Text". Der EMPFAENGER wird absichtlich
# verworfen (er kommt aus der Absender-Kennung) – hier interessiert nur der Text.
_REMINDER_TASK_RE = re.compile(
    r'^\s*(?:sende|schicke|send)\s+(?:eine\s+)?(?:whatsapp|telegram|nachricht|message)'
    r'[^:]{0,80}:\s*(?P<msg>.+)$',
    re.IGNORECASE | re.DOTALL,
)


def _reminder_message(task: str) -> str:
    """Holt den reinen Nachrichtentext aus einem Auftragstext ('' = kein Muster).

    Das Modell formuliert Erinnerungen bisher als Auftrag ("Sende WhatsApp an
    +49…: Datensicherung"). Fuer einen Sendeauftrag brauchen wir daraus nur den
    Text; findet das Muster nichts, nimmt der Aufrufer den ganzen Auftragstext –
    er wird ohnehin nur VERSCHICKT und nicht ausgefuehrt.
    """
    m = _REMINDER_TASK_RE.match(task or "")
    return (m.group("msg").strip() if m else "")


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
            "Mit einmalig=True wird der Job nach einmaligem Ausfuehren automatisch geloescht.\n\n"
            "NUR FUER ADMINISTRATOREN: Bei Netzwerk-/Domain-Benutzern wird der Aufruf "
            "abgelehnt. In diesem Fall NICHT umformulieren und erneut versuchen, sondern "
            "dem Benutzer sagen, dass ein Administrator den Auftrag einrichten muss.\n\n"
            "AUSNAHME Erinnerungen per WhatsApp/Telegram: Ein freigegebener Absender darf "
            "sich EINMALIGE Erinnerungen an sich selbst setzen. Dann 'nachricht' mit dem "
            "reinen Erinnerungstext fuellen und einmalig=True setzen. Es wird nur diese "
            "Nachricht verschickt, kein Auftrag ausgefuehrt – versprich also keine "
            "Aktionen ('ich pruefe dann die Logs'), sondern nur die Nachricht."
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
                "nachricht": {
                    "type": "STRING",
                    "description": (
                        "Nur fuer Erinnerungen per WhatsApp/Telegram: der reine "
                        "Erinnerungstext (ohne 'Sende ... an ...'). Der Empfaenger "
                        "ist immer der Absender selbst und wird nicht angegeben."
                    ),
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
        # Schranke 2 (siehe Modul-Docstring): Anlegen ist Admins vorbehalten.
        # Diese Pruefung ist bewusst DOPPELT – der Dispatch in agent.py sperrt
        # 'cron_create' bereits fuer unprivilegierte Laeufe. Hier steht sie, weil
        # ein Skill oder ein kuenftiger Aufrufer das Tool auch ausserhalb dieses
        # Dispatchs benutzen kann; fail-closed heisst dann: ohne ausdrueckliches
        # _privileged wird nichts angelegt.
        if not privileged:
            # Einzige Ausnahme: freigegebener Messenger-Absender legt eine
            # Erinnerung an SICH SELBST an – reiner Sendeauftrag ohne Agent
            # (backend/reminders.py erklaert die vier Bedingungen).
            from backend import reminders
            if reminders.is_allowed(username):
                return await self._create_reminder(
                    username, label, cron, task,
                    kwargs.get("nachricht") or kwargs.get("message") or "",
                    einmalig, kwargs.get("_client_type") or "")
            record_cron_denied(username, "chat", f"{label}\n{task}",
                               client_type=kwargs.get("_client_type") or "")
            return CRON_DENIED_MSG
        try:
            from backend.scheduler import cron_manager
            job = cron_manager.add_job(
                label=label, cron=cron, task=task, once=einmalig,
                owner=username, owner_privileged=privileged,
                created_via=f"chat:{kwargs.get('_client_type') or 'agent'}")
            einmalig_info = " (einmalig, wird danach automatisch gelöscht)" if einmalig else " (wiederkehrend)"
            # Ab hier ist der Anleger immer privilegiert (siehe Schranke oben) –
            # der Job laeuft also mit Systemrechten.
            return (
                f"Cron-Job erstellt{einmalig_info}:\n"
                f"  ID:       {job['id']}\n"
                f"  Label:    {label}\n"
                f"  Zeitplan: {cron}\n"
                f"  Aufgabe:  {task[:120]}\n"
                f"  Läuft:    mit Systemrechten ({username or 'System'})"
            )
        except ValueError as e:
            return f"Fehler – ungültiger Cron-Ausdruck: {e}"
        except Exception as e:
            return f"Fehler beim Erstellen des Jobs: {e}"

    async def _create_reminder(self, username: str, label: str, cron: str,
                               task: str, nachricht: str, einmalig: bool,
                               client_type: str) -> str:
        """Erinnerung eines freigegebenen Messenger-Absenders anlegen.

        Der Job ist ein SENDEAUFTRAG (kind='reminder'): der Scheduler schickt die
        Nachricht direkt, ohne Agent. Der Empfaenger wird aus der Absender-Kennung
        abgeleitet und NICHT aus dem Auftragstext gelesen – sonst waere das hier
        ein Versandweg an fremde Nummern.
        """
        from backend import reminders
        parsed = reminders.parse_actor(username)
        if not parsed:
            return CRON_DENIED_MSG
        channel, addr = parsed
        if not einmalig:
            return ("Wiederkehrende Erinnerungen kann ich hier nicht einrichten – "
                    "das muss ein Administrator im Portal anlegen. Eine einmalige "
                    "Erinnerung (z.B. 'morgen um 06:15') geht dagegen sofort.")
        message = (nachricht or _reminder_message(task) or task).strip()
        if not message:
            return "Fehler: Es fehlt der Text der Erinnerung."
        if len(message) > reminders.MAX_MESSAGE_LEN:
            message = message[:reminders.MAX_MESSAGE_LEN].rstrip() + "…"
        offen = reminders.open_count(username)
        if offen >= reminders.MAX_OPEN:
            return (f"Du hast bereits {offen} offene Erinnerungen – das ist die "
                    f"Höchstzahl. Bitte zuerst eine davon löschen "
                    f"(Erinnerungen anzeigen / löschen).")
        try:
            from backend.scheduler import cron_manager
            job = cron_manager.add_job(
                label=label or "Erinnerung", cron=cron,
                # Der Auftragstext ist hier nur Anzeigetext: bei kind='reminder'
                # fuehrt ihn niemand aus (scheduler._execute).
                task=f"[Erinnerung] {message}",
                once=True,
                owner=username, owner_privileged=False,
                created_via=f"reminder:{client_type or channel}",
                kind="reminder",
                payload={"channel": channel, "to": addr, "message": message},
            )
        except ValueError as e:
            return f"Fehler – ungültiger Zeitpunkt: {e}"
        except Exception as e:  # noqa: BLE001
            return f"Fehler beim Anlegen der Erinnerung: {e}"
        print(f"[CRON] Erinnerung fuer '{username}' angelegt ({cron}): "
              f"{message[:60]}", flush=True)
        return (f"Erinnerung gesetzt ({cron}, einmalig):\n"
                f"  ID:        {job['id'][:8]}\n"
                f"  Nachricht: {message[:120]}\n"
                f"  Empfänger: {addr} (nur an dich)\n"
                f"Es wird ausschließlich diese Nachricht verschickt – kein Auftrag "
                f"ausgeführt.")


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
