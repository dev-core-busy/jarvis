"""Kundenverwaltungs-Client (IBS-API) – geteilte Logik fuer das Skill-Tool
und die /api/kundenverwaltung/*-Endpoints des Einstellungs-Reiters.

Ticketsuche ueber die API-Funktion 'getMatchingEvents':
POST {base}/getMatchingEvents (Header: X-API-Key) mit JSON-Payload
{"request": {"address_id": "...", "limit": "...", "buzzwords": "a,b"}}
– alle Werte als Strings (der Server liest sie per getStringByPath).
"""

import re
import ssl

# Feld im Jira-Config-Store, das den verankerten Vertrauensanker traegt
# (Eintrag aus sap_cert.eintrag_bauen: host, port, fingerprint, pem, ...)
CERT_FELD = "ibs_api_cert"

# Fuer sap_cert.pruefen: alles ausser "odata" misst gegen den
# OpenSSL-Systemspeicher – genau der, den urllib hier benutzt.
_KANAL = "kundenverwaltung"


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


def _jira_cfg() -> dict:
    try:
        from backend.jira_client import get_jira_config
        return get_jira_config() or {}
    except Exception:  # noqa: BLE001
        return {}


def _ziel(base: str) -> tuple[str, int] | None:
    """``(host, port)`` einer https-Basis-URL, sonst None (http hat kein Zertifikat)."""
    from urllib.parse import urlparse
    teile = urlparse(base or "")
    if teile.scheme != "https" or not teile.hostname:
        return None
    try:
        return teile.hostname, int(teile.port or 443)
    except ValueError:
        return None


def ssl_kontext(base: str, cfg: dict | None = None) -> ssl.SSLContext:
    """TLS-Kontext fuer die Kundenverwaltungs-API – die Pruefung ist IMMER an.

    Bis 2026-09-29 (BSI-Abgleich H14) lief jeder Aufruf mit ``CERT_NONE``, und
    der API-Key ging damit an jeden, der sich dazwischenstellt. Jetzt:
      * Anker verankert und passt zu Host/Port -> genau dieses Zertifikat ist
        der einzige Vertrauensanker (strenger als der Systemspeicher).
        ``check_hostname`` nur aus, wenn beim Verankern GEMESSEN wurde, dass
        der Name nicht passt (IP statt FQDN) – akzeptiert wird trotzdem nur
        das gebundene Zertifikat.
      * sonst -> gewoehnliche Pruefung gegen den Systemspeicher.
    Einen Weg zu "gar keine Pruefung" gibt es nicht mehr.
    """
    from backend import sap_cert
    cfg = _jira_cfg() if cfg is None else cfg
    eintrag = cfg.get(CERT_FELD)
    ziel = _ziel(base)
    if ziel and sap_cert.passt(eintrag, *ziel):
        try:
            ctx = ssl.create_default_context(cadata=eintrag["pem"])
        except Exception as e:  # noqa: BLE001
            # Fail-CLOSED: unbrauchbarer Anker -> normale Pruefung, nie CERT_NONE
            print("[Kundenverwaltung] Anker unbrauchbar (%s) – normale Pruefung" % e,
                  flush=True)
            return ssl.create_default_context()
        if eintrag.get("name_abweichung"):
            ctx.check_hostname = False   # verify_mode bleibt CERT_REQUIRED
        return ctx
    return ssl.create_default_context()


def _ist_zertfehler(e: BaseException) -> bool:
    grund = getattr(e, "reason", None)
    return isinstance(e, ssl.SSLCertVerificationError) \
        or isinstance(grund, ssl.SSLCertVerificationError)


def _ziel_aus_url(url: str | None) -> tuple[str, int]:
    """Ziel aus der Formular-URL (pruefen VOR dem Speichern, wie im SAP-Reiter),
    ersatzweise aus der gespeicherten. Wirft sap_cert.ZertFehler."""
    from backend import sap_cert
    url = (url or "").strip() or get_ibs_config()[0]
    if not url:
        raise sap_cert.ZertFehler("Keine Adresse angegeben.")
    if "://" not in url:
        url = "https://" + url
    ziel = _ziel(url)
    if not ziel:
        raise sap_cert.ZertFehler("Die Adresse ist kein HTTPS – ohne TLS gibt es "
                                  "kein Serverzertifikat zu prüfen.")
    return ziel


def zertifikat_pruefen(url: str | None = None) -> dict:
    """Serverzertifikat holen und beurteilen – fuer die Anzeige vor dem
    Verankern (Baustein sapcert.js). Antwort ohne PEM. Wirft sap_cert.ZertFehler."""
    from backend import sap_cert
    host, port = _ziel_aus_url(url)
    erg = sap_cert.pruefen(host, port, _KANAL)
    erg.pop("pem", None)
    return erg


def zertifikat_verankern(url: str | None, fingerprint: str) -> dict:
    """Das Zertifikat erneut holen und nur dann einen Anker-Eintrag bauen, wenn
    es den vom Administrator gesehenen Fingerabdruck hat. Das PEM kommt NIE aus
    dem Request (sap_cert.bestaetigen). Speichern (Feld CERT_FELD im
    Jira-Config-Store) macht der Endpunkt. Wirft sap_cert.ZertFehler."""
    from backend import sap_cert
    host, port = _ziel_aus_url(url)
    return sap_cert.bestaetigen(host, port, fingerprint, _KANAL)


def normalize_buzzwords(raw) -> list[str]:
    """Schlagworte aus Array ODER komma-/leerzeichengetrenntem String (max. 5)."""
    if isinstance(raw, str):
        raw = [t for t in re.split(r"[,;\s]+", raw) if t]
    return [str(t).strip() for t in (raw or []) if str(t).strip()][:5]


def test_connection() -> dict:
    """Erreichbarkeits-Test der Kundenverwaltungs-API (Basis-URL, X-API-Key).

    Da der API-Vertrag noch nicht final ist, gilt: JEDE HTTP-Antwort des
    Servers (auch 401/404) = erreichbar; nur Verbindungs-/TLS-Fehler gelten
    als nicht erreichbar. Das Zertifikat wird geprueft (ssl_kontext); scheitert
    genau das, steht ``zertifikat_fehler: True`` in der Antwort (Verankern ueber
    /api/kundenverwaltung/zertifikat/*). Der API-Key geht erst nach bestandener
    Pruefung raus. Rueckgabe: {ok, configured, reachable, status, key_set, url,
    error, zertifikat_fehler?}.
    """
    import urllib.error
    import urllib.request

    base, key = get_ibs_config()
    if not base:
        return {"ok": False, "configured": False, "reachable": False,
                "error": "Kundenverwaltung ist nicht konfiguriert (URL fehlt)."}
    ctx = ssl_kontext(base)
    headers = {"X-API-Key": key} if key else {}
    req = urllib.request.Request(base, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=6, context=ctx) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code  # Server hat geantwortet -> erreichbar
    except Exception as e:  # noqa: BLE001
        erg = {"ok": False, "configured": True, "reachable": False,
               "key_set": bool(key), "url": base,
               "error": "Nicht erreichbar: %s" % e}
        if _ist_zertfehler(e):
            erg["zertifikat_fehler"] = True
            erg["error"] = ("Das Serverzertifikat ist nicht vertrauenswürdig "
                            "(selbst ausgestellt oder geändert) – bitte mit "
                            "„Zertifikat prüfen\" ansehen und verankern.")
        return erg
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
    ctx = ssl_kontext(base)
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
        if _ist_zertfehler(e):
            return {"ok": False, "configured": True, "url": url,
                    "error": "Das Serverzertifikat der Kundenverwaltung ist nicht "
                             "vertrauenswürdig – bitte im Reiter „Kundenverwaltung\" "
                             "die Verbindung testen und das Zertifikat prüfen."}
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
