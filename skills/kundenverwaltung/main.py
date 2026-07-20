"""Kundenverwaltungs-Skill (IBS-Kundenverwaltungs-API).

Anbindung an die Kundenverwaltungs-API (IBS) – unabhaengig von Jira.
Erste Funktion: Ticket-/Ereignissuche nach Schlagworten ueber die
API-Funktion 'getMatchingEvents' (POST, X-API-Key, JSON-Payload
{"request": {address_id, limit, buzzwords}}).

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
        return ("Sucht Tickets/Ereignisse ueber die Kundenverwaltungs-API (IBS, "
                "Funktion 'getMatchingEvents') anhand von 1-5 Schlagworten; "
                "optional auf eine Kunden-Adress-ID eingeschraenkt.")

    def parameters_schema(self):
        return {"type": "OBJECT", "properties": {
            "buzzwords": {"type": "ARRAY", "items": {"type": "STRING"},
                          "description": "1 bis 5 Schlagworte (z.B. ['LDT','Anbindung']). Auch als komma-/leerzeichengetrennter String moeglich."},
            "limit": {"type": "INTEGER", "description": "Max. Trefferzahl (Standard 25, Maximum 100)."},
            "address_id": {"type": "STRING", "description": "Optionale Kunden-Adress-ID zum Einschraenken der Suche."},
        }, "required": ["buzzwords"]}

    async def execute(self, **kwargs):
        import asyncio
        res = await asyncio.to_thread(
            tickets_by_buzzwords,
            kwargs.get("buzzwords") or kwargs.get("keywords"),
            kwargs.get("limit") or 25,
            kwargs.get("address_id") or "")
        if not res.get("ok"):
            if not res.get("configured"):
                return ("Kundenverwaltung ist nicht konfiguriert. Bitte URL und API-Key "
                        "im Einstellungs-Reiter 'Kundenverwaltung' eintragen.")
            return res.get("error") or "Suche fehlgeschlagen."
        rows = res.get("tickets", [])
        if not rows:
            return ("Keine Treffer in der Kundenverwaltung fuer Schlagworte %s."
                    % res.get("terms"))
        lines = ["- %s — %s%s" % (t.get("key") or "(ohne Nr.)", t.get("title"),
                                  (" | Status: %s" % t["status"]) if t.get("status") else "")
                 for t in rows]
        return ("%d Treffer der Kundenverwaltung (Schlagworte: %s%s):\n%s"
                % (res.get("count", len(rows)), ", ".join(res.get("terms", [])),
                   (", Adress-ID: %s" % res["address_id"]) if res.get("address_id") else "",
                   "\n".join(lines)))


def get_tools():
    return [KvTicketsByBuzzwordsTool()]
