"""Kundenverwaltungs-Client (IBS-API) – geteilte Logik fuer das Skill-Tool
und die /api/kundenverwaltung/*-Endpoints des Einstellungs-Reiters.

Ticketsuche ueber die API-Funktion 'getMatchingEvents':
POST {base}/getMatchingEvents (Header: X-API-Key) mit JSON-Payload
{"request": {"address_id": "...", "limit": "...", "buzzwords": "a,b"}}
– alle Werte als Strings (der Server liest sie per getStringByPath).
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


def test_connection() -> dict:
    """Erreichbarkeits-Test der Kundenverwaltungs-API (Basis-URL, X-API-Key).

    Da der API-Vertrag noch nicht final ist, gilt: JEDE HTTP-Antwort des
    Servers (auch 401/404) = erreichbar; nur Verbindungs-/TLS-Fehler gelten
    als nicht erreichbar. Interne Server nutzen oft self-signed Zertifikate,
    daher ohne Zertifikatspruefung. Rueckgabe: {ok, configured, reachable,
    status, key_set, url, error}.
    """
    import ssl
    import urllib.error
    import urllib.request

    base, key = get_ibs_config()
    if not base:
        return {"ok": False, "configured": False, "reachable": False,
                "error": "Kundenverwaltung ist nicht konfiguriert (URL fehlt)."}
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    headers = {"X-API-Key": key} if key else {}
    req = urllib.request.Request(base, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=6, context=ctx) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code  # Server hat geantwortet -> erreichbar
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "configured": True, "reachable": False,
                "key_set": bool(key), "url": base,
                "error": "Nicht erreichbar: %s" % e}
    return {"ok": True, "configured": True, "reachable": True,
            "status": status, "key_set": bool(key), "url": base}


def _extract_events(data) -> list:
    """Ereignisliste aus der getMatchingEvents-Antwort ziehen.
    Vertrag: {endpoint, timestamp, buzzwords, event: [...]}. Tolerant
    gegenueber alternativen Listen-Schluesseln."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for k in ("event", "events", "matching_events", "matchingEvents",
              "tickets", "items", "result", "results", "rows"):
        v = data.get(k)
        if isinstance(v, list):
            return v
    return []


def _fmt_time(v) -> str:
    """Zeitstempel 'YYYYMMDDhhmmss' -> 'TT.MM.JJJJ HH:MM' (sonst unveraendert)."""
    s = str(v or "").strip()
    if len(s) >= 12 and s[:12].isdigit():
        return "%s.%s.%s %s:%s" % (s[6:8], s[4:6], s[0:4], s[8:10], s[10:12])
    return s


def _fmt_row(ev) -> dict:
    """Ereignis auf die Anzeige-Felder {key, title, status, text, updated,
    dispatch_user} abbilden (Struktur der getMatchingEvents-Antwort)."""
    import json
    if not isinstance(ev, dict):
        return {"key": "", "title": str(ev), "status": "", "text": str(ev)}

    def first(*names):
        for n in names:
            v = ev.get(n)
            if v not in (None, ""):
                return str(v)
        return ""

    text = first("text", "description", "beschreibung", "summary", "betreff")
    key = first("id", "key", "event_id", "eventId", "ticket_id", "number", "nummer")
    # Erste nicht-leere Textzeile als Titel (das Textfeld enthaelt oft eine
    # mehrzeilige Verlaufshistorie mit Zeitstempeln je Zeile).
    title = ""
    for line in text.splitlines():
        if line.strip():
            title = line.strip()
            break
    if not title:
        title = text or (json.dumps(ev, ensure_ascii=False)[:300])
    return {
        "key": key,
        "title": title,
        "status": first("state", "status", "zustand"),
        "text": text,
        "updated": _fmt_time(first("modification_time", "creation_time")),
        "dispatch_user": first("dispatch user", "dispatch_user", "user"),
    }


def tickets_by_buzzwords(terms, limit: int = 25, address_id: str = "") -> dict:
    """Ticketsuche nach Schlagworten (API-Funktion 'getMatchingEvents').

    POST {base}/getMatchingEvents, Header X-API-Key, JSON-Payload
    {"request": {"address_id", "limit", "buzzwords"}} (Werte als Strings).
    Rueckgabe: {ok, configured, url, terms, limit, address_id, count,
    tickets[] (Anzeige-Zeilen), events[] (Rohdaten)} bzw.
    {ok: False, configured, error}.
    """
    import json
    import ssl
    import urllib.error
    import urllib.request

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
    address_id = str(address_id or "").strip()

    url = base + "/getMatchingEvents"
    payload = json.dumps({"request": {
        "address_id": address_id,
        "limit": str(limit),
        "buzzwords": ",".join(terms),
    }}).encode("utf-8")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # interne Server: oft self-signed
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"X-API-Key": key,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            body = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False, "configured": True, "url": url,
                "error": "API-Fehler HTTP %s: %s" % (e.code, detail or e.reason)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "configured": True, "url": url,
                "error": "Kundenverwaltung nicht erreichbar: %s" % e}

    try:
        data = json.loads(body)
    except ValueError:
        return {"ok": False, "configured": True, "url": url,
                "error": "Antwort ist kein JSON: %s" % body[:300]}

    events = _extract_events(data)
    return {"ok": True, "configured": True, "url": url,
            "terms": terms, "limit": limit, "address_id": address_id,
            "count": len(events),
            "tickets": [_fmt_row(ev) for ev in events],
            "events": events}
