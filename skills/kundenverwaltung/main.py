"""Kundenverwaltungs-Skill (IBS-Kundenverwaltungs-API).

Anbindung an die Kundenverwaltungs-API (IBS) – unabhaengig von Jira.
Erste Funktion: Ticketsuche nach Schlagworten ueber die API-Funktion
'tickets-by-buzzwords'. Diese ist serverseitig noch nicht verfuegbar und
daher hier als DUMMY umgesetzt: das Tool validiert die Eingaben, zeigt den
geplanten API-Aufruf und liefert gekennzeichnete Beispieldaten.

Zugangsdaten (URL + API-Key) werden im Einstellungs-Reiter 'Kundenverwaltung'
gepflegt. Ablage rueckwaerts-kompatibel im Config-Store des Jira-Skills
(Schluessel ibs_api_url/ibs_api_key – dieselben Werte schalten auch die
Checkbox 'IBS Tickets' in der Support-Suche frei).
"""

import re

from backend.tools.base import BaseTool


def _ibs_config() -> tuple[str, str]:
    """Liest URL + API-Key der Kundenverwaltungs-API (Reiter 'Kundenverwaltung')."""
    try:
        from backend.jira_client import get_jira_config
        cfg = get_jira_config()
    except Exception:  # noqa: BLE001
        cfg = {}
    return ((cfg.get("ibs_api_url") or "").strip().rstrip("/"),
            (cfg.get("ibs_api_key") or "").strip())


def _normalize_buzzwords(raw) -> list[str]:
    """Schlagworte aus Array ODER komma-/leerzeichengetrenntem String."""
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,;\s]+", raw) if t]
    return [str(t).strip() for t in (raw or []) if str(t).strip()][:5]


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
        base, key = _ibs_config()
        if not base or not key:
            return ("Kundenverwaltung ist nicht konfiguriert. Bitte URL und API-Key im "
                    "Einstellungs-Reiter 'Kundenverwaltung' eintragen.")
        terms = _normalize_buzzwords(kwargs.get("buzzwords") or kwargs.get("keywords"))
        if not terms:
            return "Bitte mindestens ein Schlagwort angeben (z.B. buzzwords=['LDT','Anbindung'])."
        try:
            limit = max(1, min(int(kwargs.get("limit") or 25), 100))
        except (TypeError, ValueError):
            limit = 25

        # ── DUMMY-Implementierung ─────────────────────────────────────────
        # Die API-Funktion 'tickets-by-buzzwords' existiert serverseitig noch
        # nicht. Geplanter Aufruf (bei Umsetzung durch echten HTTP-Request via
        # asyncio.to_thread ersetzen, X-API-Key als Header senden):
        planned = "%s/tickets-by-buzzwords?buzzwords=%s&limit=%d" % (
            base, ",".join(terms), limit)

        beispiel = [
            "- KV-000001 — [BEISPIEL] Ticket zu '%s' | Status: offen" % terms[0],
            "- KV-000002 — [BEISPIEL] Ticket zu '%s' | Status: abgeschlossen" % ", ".join(terms),
        ]
        return (
            "⚠️ DUMMY-ANTWORT der Kundenverwaltung – die API-Funktion "
            "'tickets-by-buzzwords' ist noch nicht verfuegbar.\n"
            "Geplanter Aufruf: GET %s (Header: X-API-Key)\n"
            "Parameter validiert: Schlagworte=%s, limit=%d\n\n"
            "Beispieldaten (KEINE echten Tickets):\n%s"
            % (planned, terms, limit, "\n".join(beispiel))
        )


def get_tools():
    return [KvTicketsByBuzzwordsTool()]
