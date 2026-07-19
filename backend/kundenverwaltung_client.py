"""Kundenverwaltungs-Client (IBS-API) – geteilte Logik fuer das Skill-Tool
und die /api/kundenverwaltung/*-Endpoints des Einstellungs-Reiters.

Die API-Funktion 'tickets-by-buzzwords' ist serverseitig noch nicht
verfuegbar – tickets_by_buzzwords() liefert daher eine als DUMMY
gekennzeichnete Beispielantwort (inkl. geplanter Request-URL). Bei
Umsetzung der echten API hier den HTTP-Aufruf ergaenzen (X-API-Key-Header);
Tool und Reiter uebernehmen die Aenderung dann automatisch.
"""

import re


def get_ibs_config() -> tuple[str, str]:
    """URL + API-Key der Kundenverwaltungs-API (Ablage rueckwaerts-kompatibel
    im Config-Store des Jira-Skills: ibs_api_url/ibs_api_key – dieselben
    Werte schalten auch die Checkbox 'IBS Tickets' in der Support-Suche frei)."""
    try:
        from backend.jira_client import get_jira_config
        cfg = get_jira_config()
    except Exception:  # noqa: BLE001
        cfg = {}
    return ((cfg.get("ibs_api_url") or "").strip().rstrip("/"),
            (cfg.get("ibs_api_key") or "").strip())


def normalize_buzzwords(raw) -> list[str]:
    """Schlagworte aus Array ODER komma-/leerzeichengetrenntem String (max. 5)."""
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,;\s]+", raw) if t]
    return [str(t).strip() for t in (raw or []) if str(t).strip()][:5]


def tickets_by_buzzwords(terms, limit: int = 25) -> dict:
    """Ticketsuche nach Schlagworten (API-Funktion 'tickets-by-buzzwords').

    DERZEIT DUMMY: validiert Eingaben und liefert gekennzeichnete
    Beispieldaten plus die geplante Request-URL. Rueckgabe:
    {ok, dummy, configured, planned, terms, limit, tickets[]} bzw.
    {ok: False, configured, error}.
    """
    base, key = get_ibs_config()
    if not base or not key:
        return {"ok": False, "configured": False,
                "error": "Kundenverwaltung ist nicht konfiguriert (URL und API-Key fehlen)."}
    terms = normalize_buzzwords(terms)
    if not terms:
        return {"ok": False, "configured": True,
                "error": "Mindestens ein Schlagwort angeben."}
    try:
        limit = max(1, min(int(limit or 25), 100))
    except (TypeError, ValueError):
        limit = 25

    planned = "%s/tickets-by-buzzwords?buzzwords=%s&limit=%d" % (
        base, ",".join(terms), limit)
    tickets = [
        {"key": "KV-000001", "title": "[BEISPIEL] Ticket zu '%s'" % terms[0],
         "status": "offen"},
        {"key": "KV-000002", "title": "[BEISPIEL] Ticket zu '%s'" % ", ".join(terms),
         "status": "abgeschlossen"},
    ]
    return {"ok": True, "dummy": True, "configured": True, "planned": planned,
            "terms": terms, "limit": limit, "tickets": tickets}
