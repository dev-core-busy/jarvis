"""
Google Calendar Tool für Jarvis.

Tool-Name: google_calendar
Aktionen:
  list_events    – Bevorstehende Termine (optional: Kalender-ID, max. Anzahl)
  get_event      – Einzelnen Termin lesen
  create_event   – Neuen Termin anlegen
  update_event   – Termin bearbeiten
  delete_event   – Termin löschen
  find_free_time – Freie Zeitfenster finden (Freebusy-Abfrage)
  list_calendars – Alle Kalender anzeigen
"""

from datetime import datetime, timezone, timedelta

from backend.tools.base import BaseTool


def _get_service():
    from backend.tools.google_auth import get_service
    return get_service("calendar", "v3")


def _fmt(dt_str: str) -> str:
    """ISO-Zeitstring lesbar formatieren."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        return dt_str


class GoogleCalendarTool(BaseTool):
    name = "google_calendar"
    description = (
        "Liest und verwaltet Google Calendar Termine. "
        "Aktionen: list_events, get_event, create_event, update_event, delete_event, "
        "find_free_time, list_calendars."
    )

    def execute(self, action: str, **kwargs) -> str:
        try:
            svc = _get_service()
        except RuntimeError as e:
            return f"❌ Nicht authentifiziert: {e}"
        except Exception as e:
            return f"❌ Verbindungsfehler: {e}"

        try:
            cal_id = kwargs.get("calendar_id", "primary")
            if action == "list_events":
                return self._list_events(svc, cal_id, kwargs.get("max_results", 10),
                                         kwargs.get("days_ahead", 14))
            elif action == "get_event":
                return self._get_event(svc, cal_id, kwargs.get("event_id", ""))
            elif action == "create_event":
                return self._create_event(svc, cal_id,
                    kwargs.get("title", "Neuer Termin"),
                    kwargs.get("start"),   # ISO-String, z.B. "2025-03-15T10:00:00"
                    kwargs.get("end"),
                    kwargs.get("description", ""),
                    kwargs.get("location", ""),
                    kwargs.get("attendees", []),  # Liste von E-Mail-Strings
                )
            elif action == "update_event":
                return self._update_event(svc, cal_id, kwargs.get("event_id", ""), kwargs)
            elif action == "delete_event":
                return self._delete_event(svc, cal_id, kwargs.get("event_id", ""))
            elif action == "find_free_time":
                return self._find_free_time(svc,
                    kwargs.get("start"),
                    kwargs.get("end"),
                    kwargs.get("duration_minutes", 60),
                )
            elif action == "list_calendars":
                return self._list_calendars(svc)
            else:
                return (f"❌ Unbekannte Aktion: {action}. "
                        "Verfügbar: list_events, get_event, create_event, update_event, "
                        "delete_event, find_free_time, list_calendars")
        except Exception as e:
            return f"❌ Calendar-Fehler: {e}"

    def _list_events(self, svc, cal_id: str, max_results: int, days_ahead: int) -> str:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days_ahead)
        result = svc.events().list(
            calendarId=cal_id,
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = result.get("items", [])
        if not events:
            return f"📅 Keine Termine in den nächsten {days_ahead} Tagen."
        lines = [f"📅 {len(events)} Termin(e) (nächste {days_ahead} Tage):"]
        for ev in events:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
            end_t = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", "")
            lines.append(
                f"  📌 {ev.get('summary','(kein Titel)')}\n"
                f"     Start: {_fmt(start)} | Ende: {_fmt(end_t)}\n"
                f"     ID: {ev['id']}"
            )
        return "\n".join(lines)

    def _get_event(self, svc, cal_id: str, event_id: str) -> str:
        if not event_id:
            return "❌ Bitte event_id angeben."
        ev = svc.events().get(calendarId=cal_id, eventId=event_id).execute()
        start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
        end   = ev.get("end", {}).get("dateTime")   or ev.get("end", {}).get("date", "")
        attendees = ", ".join(a.get("email","") for a in ev.get("attendees", []))
        return (
            f"📌 {ev.get('summary','(kein Titel)')}\n"
            f"Start:       {_fmt(start)}\n"
            f"Ende:        {_fmt(end)}\n"
            f"Ort:         {ev.get('location','–')}\n"
            f"Beschreibung:{ev.get('description','–')}\n"
            f"Teilnehmer:  {attendees or '–'}\n"
            f"Link:        {ev.get('htmlLink','–')}"
        )

    def _create_event(self, svc, cal_id: str, title: str,
                      start: str, end: str, description: str,
                      location: str, attendees: list) -> str:
        if not start or not end:
            return "❌ Bitte start und end als ISO-String angeben (z.B. '2025-03-15T10:00:00')."
        body: dict = {
            "summary":     title,
            "start":       {"dateTime": start, "timeZone": "Europe/Berlin"},
            "end":         {"dateTime": end,   "timeZone": "Europe/Berlin"},
            "description": description,
            "location":    location,
        }
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        ev = svc.events().insert(calendarId=cal_id, body=body,
                                  sendUpdates="all" if attendees else "none").execute()
        return f"✅ Termin '{title}' erstellt ({_fmt(start)})\nLink: {ev.get('htmlLink','–')}"

    def _update_event(self, svc, cal_id: str, event_id: str, kwargs: dict) -> str:
        if not event_id:
            return "❌ Bitte event_id angeben."
        ev = svc.events().get(calendarId=cal_id, eventId=event_id).execute()
        if "title" in kwargs:       ev["summary"]     = kwargs["title"]
        if "description" in kwargs: ev["description"] = kwargs["description"]
        if "location" in kwargs:    ev["location"]    = kwargs["location"]
        if "start" in kwargs:
            ev["start"] = {"dateTime": kwargs["start"], "timeZone": "Europe/Berlin"}
        if "end" in kwargs:
            ev["end"]   = {"dateTime": kwargs["end"],   "timeZone": "Europe/Berlin"}
        updated = svc.events().update(calendarId=cal_id, eventId=event_id, body=ev).execute()
        return f"✅ Termin aktualisiert: {updated.get('summary','–')}"

    def _delete_event(self, svc, cal_id: str, event_id: str) -> str:
        if not event_id:
            return "❌ Bitte event_id angeben."
        ev = svc.events().get(calendarId=cal_id, eventId=event_id).execute()
        svc.events().delete(calendarId=cal_id, eventId=event_id).execute()
        return f"🗑️ Termin '{ev.get('summary','–')}' gelöscht."

    def _find_free_time(self, svc, start: str, end: str, duration_minutes: int) -> str:
        if not start or not end:
            now = datetime.now(timezone.utc)
            start = now.isoformat()
            end   = (now + timedelta(days=7)).isoformat()
        body = {
            "timeMin": start if start.endswith("Z") else start + "Z",
            "timeMax": end   if end.endswith("Z")   else end   + "Z",
            "items":   [{"id": "primary"}],
        }
        result = svc.freebusy().query(body=body).execute()
        busy = result.get("calendars", {}).get("primary", {}).get("busy", [])
        if not busy:
            return f"✅ Keine Termine im Zeitraum — komplett frei."
        lines = [f"⏰ Belegt ({len(busy)} Block/Blocks):"]
        for b in busy:
            lines.append(f"  {_fmt(b['start'])} → {_fmt(b['end'])}")
        return "\n".join(lines)

    def _list_calendars(self, svc) -> str:
        result = svc.calendarList().list().execute()
        cals = result.get("items", [])
        lines = [f"📅 {len(cals)} Kalender:"]
        for c in cals:
            lines.append(f"  {c.get('summary','–')} (ID: {c['id']})")
        return "\n".join(lines)
