"""Kundenverwaltungs-Skill (IBS-Kundenverwaltungs-API).

Anbindung an die Kundenverwaltungs-API (IBS) – unabhaengig von Jira.
Erste Funktion: Ticketsuche nach Schlagworten ueber die API-Funktion
'tickets-by-buzzwords'. Diese ist serverseitig noch nicht verfuegbar und
daher hier als DUMMY umgesetzt: das Tool validiert die Eingaben, zeigt den
geplanten API-Aufruf und liefert gekennzeichnete Beispieldaten.

Zugangsdaten (URL + API-Key) werden im Einstellungs-Reiter 'Kundenverwaltung'
gepflegt. Die Such-Logik liegt im geteilten ``backend.kundenverwaltung_client``
(auch vom /api/kundenverwaltung/*-Endpoint des Reiters genutzt).
"""

from backend.tools.base import BaseTool
from backend.kundenverwaltung_client import tickets_by_buzzwords


class KvTicketsByBuzzwordsTool(BaseTool):
    @property
    def name(self): return "kv_tickets_by_buzzwords"

    @property
    def description(self):
        return ("Sucht Tickets ueber die Kundenverwaltungs-API (IBS, Funktion "
                "'tickets-by-buzzwords') anhand von 1-5 Schlagworten. "
                "ACHTUNG: derzeit DUMMY – die API-Funktion "
                "ist noch nicht angebunden, es kommen gekennzeichnete Beispieldaten zurueck. "
                "Das dem Nutzer klar mitteilen und die Beispieldaten NICHT als echte "
                "Tickets ausgeben.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "buzzwords": {"type": "ARRAY", "items": {"type": "STRING"},
                          "description": "1 bis 5 Schlagworte (z.B. ['LDT','Anbindung']). Auch als komma-/leerzeichengetrennter String moeglich."},
            "limit": {"type": "INTEGER", "description": "Max. Trefferzahl (Standard 25, Maximum 100)."},
        }, "required": ["buzzwords"]}

    async def execute(self, **kwargs):
        res = tickets_by_buzzwords(
            kwargs.get("buzzwords") or kwargs.get("keywords"),
            kwargs.get("limit") or 25)
        if not res.get("ok"):
            if not res.get("configured"):
                return ("Kundenverwaltung ist nicht konfiguriert. Bitte URL und API-Key "
                        "im Einstellungs-Reiter 'Kundenverwaltung' eintragen.")
            return res.get("error") or "Suche fehlgeschlagen."
        lines = ["- %s — %s | Status: %s" % (t.get("key"), t.get("title"), t.get("status"))
                 for t in res.get("tickets", [])]
        return (
            "⚠️ DUMMY-ANTWORT der Kundenverwaltung – die API-Funktion "
            "'tickets-by-buzzwords' ist noch nicht verfuegbar.\n"
            "Geplanter Aufruf: GET %s (Header: X-API-Key)\n"
            "Parameter validiert: Schlagworte=%s, limit=%d\n\n"
            "Beispieldaten (KEINE echten Tickets):\n%s"
            % (res.get("planned"), res.get("terms"), res.get("limit"), "\n".join(lines))
        )


def get_tools():
    return [KvTicketsByBuzzwordsTool()]
