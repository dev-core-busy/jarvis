"""Content-Security-Policy (BSI H4) – Richtlinie, Modus und Verstossmeldungen.

BEFUND H4 (BSI-Abgleich 29.09.2026, auf ECHT gemessen): keine CSP, das
Sitzungstoken liegt in localStorage. Ein einziges eingeschleustes Skript
(XSS) liest das Token und uebernimmt das Konto. Die CSP ist die zweite Linie
hinter dem Maskieren: selbst wenn Markup durchrutscht, fuehrt der Browser
kein Skript aus, das nicht als DATEI vom eigenen Server kommt.

DIE ENTSCHEIDENDE ZEILE ist ``script-src 'self'`` OHNE ``'unsafe-inline'``:
damit sind Inline-Handler (onclick=...), Inline-<script> und javascript:-Ziele
wirkungslos – genau die Formen, in denen eingeschleuste Skripte ankommen.
Das Frontend wurde dafuer frei von Inline-Skript gemacht (Waechter
tests/test_csp_h4_frontend.py). ``style-src`` erlaubt Inline-Stile
weiter – ANGENOMMENES RESTRISIKO (Betreiberentscheid 2026-10-13): ein Stil
fuehrt keinen Code aus; das Frontend setzt sie an rund 3000 Stellen, und
Mermaid schreibt eigene <style>-Elemente in jedes Diagramm.

MODUS (``csp_modus`` in settings.json; lesen/setzen ueber ``/api/security/csp``):
  * ``erzwingen`` – Vorgabe (seit 2026-10-13). Kopfzeile
                    ``Content-Security-Policy``: Verstoesse werden blockiert
                    UND gemeldet.
  * ``melden``    – Kopfzeile ``Content-Security-Policy-Report-Only``: der
                    Browser blockiert NICHTS, meldet aber jeden Verstoss an
                    ``/api/csp-report``. Bis 2026-10-13 die Vorgabe; jetzt der
                    Rueckweg, falls eine Seite nach dem Scharfschalten bricht.
                    Wer ``melden`` ausdruecklich gesetzt hat, behaelt es.
  * ``aus``       – keine Kopfzeile (Notschalter).
Ein unbekannter Wert gilt als Vorgabe (``erzwingen``) – NICHT als ``aus``: ein Tippfehler
darf den Schutz nicht still abschalten (gleiche Haltung wie H3: 0 ist kein "aus").

MELDUNGEN: ``data/logs/csp_berichte.jsonl`` (``data/logs`` ist privat, 0750;
die Datei 0640). Der Melde-Endpunkt ist zwangslaeufig OHNE Anmeldung – der
Browser schickt Berichte ohne Token. Deshalb:
  * je IP hoechstens ``RATE_JE_MINUTE`` Berichte pro Minute (Lastbremse, keine
    Aufbewahrungsregel),
  * je Bericht harte Feldlaengen (Notbremse pro Eintrag),
  * gleiche Verstoesse (Seite, Direktive, blockiertes Ziel, Quelle) werden je
    Tag nur EINMAL geschrieben und im Speicher gezaehlt – eine Seite mit
    einem Verstoss erzeugt sonst bei jedem Aufruf eine Zeile.
  * keine IP und kein vollstaendiger User-Agent in der Datei (Personenbezug).
Aufbewahrung nur nach ALTER ueber ``log_retention`` – keine Stueckzahlgrenze.

AUSGENOMMEN: ``/novnc/`` – das ist das Systempaket noVNC (``/usr/share/novnc``),
das selbst ein Inline-Modul-Skript traegt; es laeuft nur im Desktop-Rahmen fuer
Admins. Eine Richtlinie dort wuerde den Desktop nach dem Scharfschalten
brechen, ohne dass wir den Inhalt aendern koennten.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import threading
import time
from pathlib import Path

MODI = ("melden", "erzwingen", "aus")
MODUS_VORGABE = "erzwingen"
MELDE_PFAD = "/api/csp-report"
DATEI_MODUS = 0o640
RATE_JE_MINUTE = 60
FELD_MAX = 300
# Obergrenzen gegen Fluten (Code-Review 2026-10-07): der Meldepfad ist OHNE
# Anmeldung erreichbar (der Browser schickt kein Token mit). Die Lastbremse je
# IP allein liess ~1,5 MB je Minute und Adresse auf die Platte – mit vielen
# Adressen beliebig viel. Ein echter Verstoss steht je Tag EINMAL in der Datei;
# mehr als ein paar hundert verschiedene am Tag hat keine echte Seite.
TAG_MAX_ZEILEN = 1000
DATEI_MAX = 5 * 1024 * 1024
GESEHEN_MAX = 20000

# Office-Add-ins laden office.js von Microsoft (Pflicht fuer Add-ins).
_ADDIN_PRAEFIXE = ("/addin/", "/excel-addin/", "/static/addin/", "/static/excel-addin/")
_OFFICE_JS = "https://appsforoffice.microsoft.com"
# office.js oeffnet selbst einen Telemetrie-Rahmen (auf DEV gemessen 2026-10-04,
# live_csp_h4_dev.py) – nur auf den Add-in-Seiten zugelassen.
_OFFICE_RAHMEN = "https://telemetryservice.firstpartyapps.oaspapps.com"
_AUSGENOMMEN = ("/novnc/",)
# Wer die Add-in-Seiten einrahmen darf (BSI H7): Outlook/Excel im Web laden das
# Aufgabenfenster in einen iframe von Microsofts Hosts. Alle anderen Seiten nur
# 'self'. ⚠ Im Modus "melden" (Report-Only) wertet der Browser frame-ancestors
# NICHT aus – bis zum Scharfschalten schuetzt X-Frame-Options
# (backend/sicherheits_kopf.py), das die Add-in-Seiten ausnimmt.
FRAME_ANCESTORS_OFFICE = ("https://*.office.com https://*.office365.com "
                          "https://*.microsoft.com https://*.cloud.microsoft "
                          "https://*.officeapps.live.com https://*.sharepoint.com "
                          "https://outlook.live.com https://*.outlook.com")

_get_setting = None
_SPERRE = threading.Lock()
_rate: dict[str, list[float]] = {}
_gesehen: dict[str, int] = {}          # Schluessel -> Anzahl (seit Dienststart)
_gesehen_tag: dict[str, str] = {}      # Schluessel -> Tag des letzten Schreibens
_tag_zeilen: dict[str, int] = {}       # Tag -> geschriebene Zeilen (nur der heutige)


def einstellungen_quelle(fn) -> None:
    """``main`` reicht ``config.get_setting`` herein – das Modul importiert
    ``backend.config`` nie selbst (Tests: der echte Import schreibt die
    Live-settings.json)."""
    global _get_setting
    _get_setting = fn


def _ordner() -> Path:
    """Ablageort. Funktion statt Konstante – ein Test biegt ihn um."""
    return Path(__file__).resolve().parent.parent / "data" / "logs"


def _datei() -> Path:
    return _ordner() / "csp_berichte.jsonl"


def modus() -> str:
    """Wirksamer Modus. Unbekannt/fehlend -> Vorgabe ``erzwingen`` (nie still ``aus``)."""
    wert = MODUS_VORGABE
    if _get_setting is not None:
        try:
            wert = str(_get_setting("csp_modus", MODUS_VORGABE) or MODUS_VORGABE).strip().lower()
        except Exception:  # noqa: BLE001
            wert = MODUS_VORGABE
    return wert if wert in MODI else MODUS_VORGABE


def pfad_normal(pfad: str) -> str:
    """Pfad ohne ``.``/``..``-Teile fuer die Praefix-Entscheidungen.

    Code-Review 2026-10-07: Starlette dekodiert ``%2F`` VOR dem Routing –
    ``/static/addin/..%2Fportal.html`` kommt als ``/static/addin/../portal.html``
    an, traf damit das Add-in-Praefix und lieferte das PORTAL ohne
    X-Frame-Options aus (StaticFiles loest den Pfad selbst auf). Entschieden
    wird deshalb am aufgeloesten Pfad; ein Schraegstrich am Ende bleibt."""
    p = pfad or ""
    if not p:
        return p
    n = posixpath.normpath(p)
    if p.endswith("/") and not n.endswith("/"):
        n += "/"
    return n


_HOST_OK = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](:\d{1,5})?$")


def richtlinie(pfad: str, host: str = "") -> str:
    """Die Richtlinie fuer eine HTML-Antwort unter ``pfad``.

    ``host`` (Host-Kopfzeile) nur fuer das WebSocket-Ziel: aeltere Browser
    zaehlen wss:// nicht zu 'self'. Ein Host, der nicht wie ein Hostname
    aussieht, wird weggelassen statt eingesetzt – er landet sonst wortwoertlich
    in einer Sicherheits-Kopfzeile.
    """
    pfad = pfad_normal(pfad)
    addin = any(pfad.startswith(p) for p in _ADDIN_PRAEFIXE)
    skript = "'self'" + (" " + _OFFICE_JS if addin else "")
    verbinden = "'self'"
    if host and _HOST_OK.match(host):
        verbinden += " wss://" + host
    teile = [
        "default-src 'self'",
        "script-src " + skript,
        # Inline-Stile erlaubt: angenommenes Restrisiko (siehe Modulkopf).
        "style-src 'self' 'unsafe-inline'",
        # Chat rendert Markdown-Bilder auch von https-Zielen; data:/blob: fuer
        # Vorschauen, Diagramme und hochgeladene Bilder.
        "img-src 'self' data: blob: https:",
        "font-src 'self' data:",
        "connect-src " + verbinden,
        "media-src 'self' data: blob:",
        # PDF-/Dokumentvorschau im Rahmen (blob:), Desktop-Rahmen (/novnc).
        "frame-src 'self' blob: data:" + (" " + _OFFICE_RAHMEN if addin else ""),
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'" + (" " + FRAME_ANCESTORS_OFFICE if addin else ""),
        "report-uri " + MELDE_PFAD,
    ]
    return "; ".join(teile)


def kopfzeilen(pfad: str, host: str = "") -> dict[str, str]:
    """Die zu setzenden Kopfzeilen fuer eine HTML-Antwort – leer, wenn keine."""
    if any(pfad_normal(pfad).startswith(p) for p in _AUSGENOMMEN):
        return {}
    m = modus()
    if m == "aus":
        return {}
    name = "Content-Security-Policy" if m == "erzwingen" else "Content-Security-Policy-Report-Only"
    return {name: richtlinie(pfad, host)}


# ─── Meldungen ───────────────────────────────────────────────────────────────

def _kurz(v, n: int = FELD_MAX) -> str:
    s = str(v if v is not None else "")
    s = "".join(ch if ch.isprintable() else " " for ch in s)
    return s[:n]


def _ohne_query(url: str) -> str:
    """Seiten-/Ziel-URL ohne Query und Fragment – dort stehen Tokens
    (``?token=``) und Suchbegriffe, die nicht ins Protokoll gehoeren."""
    u = str(url or "")
    for z in ("?", "#"):
        i = u.find(z)
        if i >= 0:
            u = u[:i]
    return u


def _normalisieren(roh: dict) -> dict | None:
    """Beide Formate auf eine Form bringen: ``report-uri`` liefert
    ``{"csp-report": {...}}`` mit Bindestrich-Schluesseln, die Reporting-API
    ``{"type": "csp-violation", "body": {...}}`` mit camelCase."""
    if not isinstance(roh, dict):
        return None
    if isinstance(roh.get("csp-report"), dict):
        b = roh["csp-report"]
        g = lambda *k: next((b[x] for x in k if x in b), "")  # noqa: E731
        return {
            "seite": _kurz(_ohne_query(g("document-uri"))),
            "direktive": _kurz(g("effective-directive", "violated-directive"), 80),
            "blockiert": _kurz(_ohne_query(g("blocked-uri"))),
            "quelle": _kurz(_ohne_query(g("source-file"))),
            "zeile": _kurz(g("line-number"), 12),
            "auszug": _kurz(g("script-sample"), 120),
            "modus": _kurz(g("disposition"), 12),
        }
    if roh.get("type") == "csp-violation" and isinstance(roh.get("body"), dict):
        b = roh["body"]
        return {
            "seite": _kurz(_ohne_query(b.get("documentURL", ""))),
            "direktive": _kurz(b.get("effectiveDirective", ""), 80),
            "blockiert": _kurz(_ohne_query(b.get("blockedURL", ""))),
            "quelle": _kurz(_ohne_query(b.get("sourceFile", ""))),
            "zeile": _kurz(b.get("lineNumber", ""), 12),
            "auszug": _kurz(b.get("sample", ""), 120),
            "modus": _kurz(b.get("disposition", ""), 12),
        }
    return None


def _rate_ok(ip: str, jetzt: float) -> bool:
    liste = [t for t in _rate.get(ip, []) if jetzt - t < 60]
    if len(liste) >= RATE_JE_MINUTE:
        _rate[ip] = liste
        return False
    liste.append(jetzt)
    _rate[ip] = liste
    if len(_rate) > 5000:              # Speicher der Lastbremse selbst begrenzen
        for k in [k for k, v in _rate.items() if not v or jetzt - v[-1] >= 60]:
            _rate.pop(k, None)
    return True


def melden(koerper: bytes, ip: str = "", ua: str = "") -> int:
    """Einen Melde-Aufruf verarbeiten. Rueckgabe = Zahl NEU geschriebener Zeilen.

    Wirft NIE: ein kaputter Bericht ist kein Serverfehler, und der Browser
    wertet die Antwort ohnehin nicht aus."""
    try:
        jetzt = time.time()
        with _SPERRE:
            if not _rate_ok(ip or "?", jetzt):
                return 0
        if not koerper or len(koerper) > 64 * 1024:
            return 0
        daten = json.loads(koerper.decode("utf-8", "replace"))
        roh = daten if isinstance(daten, list) else [daten]
        tag = time.strftime("%Y-%m-%d", time.localtime(jetzt))
        neu = []
        for r in roh[:20]:
            e = _normalisieren(r)
            if not e:
                continue
            schluessel = "|".join((e["seite"], e["direktive"], e["blockiert"],
                                   e["quelle"], e["zeile"]))
            with _SPERRE:
                if schluessel not in _gesehen and len(_gesehen) >= GESEHEN_MAX:
                    # Speicher der Zaehler begrenzen: Eintraege von gestern weg,
                    # reicht das nicht, wird der neue Schluessel nicht gemerkt.
                    for k in [k for k, t in _gesehen_tag.items() if t != tag]:
                        _gesehen_tag.pop(k, None)
                        _gesehen.pop(k, None)
                    if len(_gesehen) >= GESEHEN_MAX:
                        continue
                _gesehen[schluessel] = _gesehen.get(schluessel, 0) + 1
                if _gesehen_tag.get(schluessel) == tag:
                    continue
                if _tag_zeilen.get(tag, 0) >= TAG_MAX_ZEILEN:
                    continue
                if tag not in _tag_zeilen:
                    _tag_zeilen.clear()
                _tag_zeilen[tag] = _tag_zeilen.get(tag, 0) + 1
                _gesehen_tag[schluessel] = tag
            e["ts"] = int(jetzt)
            e["browser"] = _browser(ua)
            neu.append(e)
        if neu:
            _schreiben(neu)
        return len(neu)
    except Exception as ex:  # noqa: BLE001
        print(f"[CSP] Bericht verworfen: {type(ex).__name__}: {ex}", flush=True)
        return 0


def _browser(ua: str) -> str:
    """Nur die Browser-Familie – fuer die Diagnose genug, kein Fingerabdruck."""
    u = str(ua or "")
    for name in ("Edg", "OPR", "Firefox", "Chrome", "Safari"):
        if name in u:
            return {"Edg": "Edge", "OPR": "Opera"}.get(name, name)
    return "?"


def _schreiben(eintraege: list[dict]) -> None:
    p = _datei()
    with _SPERRE:
        p.parent.mkdir(parents=True, exist_ok=True)
        neu = not p.exists()
        try:
            if not neu and p.stat().st_size >= DATEI_MAX:
                return                  # voll: kuerzen() (log_retention) macht Platz
        except OSError:
            return
        with p.open("a", encoding="utf-8") as f:
            for e in eintraege:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        if neu:
            try:
                os.chmod(p, DATEI_MODUS)
            except Exception:  # noqa: BLE001
                pass


def lesen(limit: int = 200) -> list[dict]:
    """Die juengsten Meldungen, NEUESTE zuerst, mit Zaehler seit Dienststart.

    Gelesen werden nur die letzten 512 kB – die Anzeige braucht die juengsten
    Verstoesse, nicht die ganze Historie (die Datei selbst wird NICHT gekuerzt)."""
    p = _datei()
    if not p.is_file():
        return []
    limit = max(1, min(int(limit or 200), 1000))
    with p.open("rb") as f:
        f.seek(0, os.SEEK_END)
        groesse = f.tell()
        f.seek(max(0, groesse - 512 * 1024))
        rest = f.read()
    zeilen = rest.split(b"\n")
    if groesse > 512 * 1024:
        zeilen = zeilen[1:]            # erste Zeile angeschnitten
    raus = []
    for z in reversed(zeilen):
        if not z.strip():
            continue
        try:
            e = json.loads(z.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(e, dict):
            continue
        k = "|".join(str(e.get(x, "")) for x in ("seite", "direktive", "blockiert", "quelle", "zeile"))
        e["anzahl_seit_start"] = _gesehen.get(k, 0)
        raus.append(e)
        if len(raus) >= limit:
            break
    return raus


def kuerzen(grenze_ts: float) -> int:
    """Eintraege aelter als ``grenze_ts`` entfernen (``log_retention``).

    Ein Eintrag ohne Zeitstempel bleibt (kein Altersbeweis)."""
    p = _datei()
    if not p.is_file():
        return 0
    with _SPERRE:
        behalten, weg = [], 0
        for z in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not z.strip():
                continue
            try:
                ts = float((json.loads(z) or {}).get("ts") or 0)
            except Exception:  # noqa: BLE001
                behalten.append(z)
                continue
            if ts and ts < grenze_ts:
                weg += 1
            else:
                behalten.append(z)
        if not weg:
            return 0
        if not behalten:
            p.unlink()
        else:
            tmp = p.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(behalten) + "\n", encoding="utf-8")
            try:
                os.chmod(tmp, DATEI_MODUS)
            except Exception:  # noqa: BLE001
                pass
            os.replace(tmp, p)
    return weg
