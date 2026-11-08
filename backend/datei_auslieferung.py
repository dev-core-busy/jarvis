"""Eine Regel fuer die Auslieferung hochgeladener/erzeugter Dateien (Befund B2, 2026-11).

Gespeichertes XSS: ein SVG oder HTML, das Jarvis aus der EIGENEN Herkunft
``inline`` ausliefert, laeuft beim Oeffnen im Tab mit Zugriff auf die
Sitzung. Bis 2026-11 taten das ``/api/documents/<cap>.svg`` (ein Chat-Anhang
``<32hex>__x.svg`` genuegte), ``/api/knowledge/file_raw`` (inline mit
geratenem MIME, ohne Endungspruefung), ``/api/wissen/file`` (html/htm/svg
inline) und ``/api/branding/logo`` (oeffentlich, SVG). Die CSP-Middleware
setzt ihre Richtlinie nur bei text/html und ist fuer App-SEITEN gebaut.

Zwei Schranken, bewusst unabhaengig:

1. ``disposition(media)``: ``inline`` NUR fuer Rasterbilder, PDF und
   text/plain – alles andere (svg, html, xml, js …) als ``attachment``.
   Ein ``<img src>`` zeigt ein SVG trotz ``attachment`` weiter an (dort laeuft
   kein Skript); nur das Oeffnen als Dokument wird zum Download.
2. Middleware ``kopfzeilen()``: jede Antwort eines Datei-Endpunkts (Pfad-
   Praefix ODER ``Content-Disposition`` gesetzt) mit AKTIVEM Inhaltstyp
   bekommt ``Content-Security-Policy: sandbox; default-src 'none'`` und
   ``nosniff``. Damit ist auch ein kuenftiger Endpunkt, der die erste Regel
   vergisst, entschaerft. App-Seiten (/chat, /settings …) sind weder
   Datei-Endpunkt noch tragen sie Content-Disposition – ihre CSP bleibt.

Importiert ``backend.config`` nicht (Tests laden das Modul direkt).
"""
from __future__ import annotations

import mimetypes
from pathlib import PurePath

SANDBOX_CSP = "sandbox; default-src 'none'"

# Was der Browser im Tab ohne Skriptausfuehrung darstellt.
INLINE_TYPEN = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
    "application/pdf", "text/plain",
})

# Textformate, die zur ANZEIGE als text/plain ausgeliefert werden (statt
# text/markdown/text/csv, die der Browser nur herunterlaedt).
_ALS_TEXT = frozenset({".txt", ".md", ".log", ".csv", ".json"})

# Datei-Endpunkte: hier kommt Inhalt aus Uploads, Wissensordnern oder
# Werkzeugen – nie eine App-Seite.
DATEI_PFADE = (
    "/api/documents/", "/api/chat/attachment/", "/api/generated/",
    "/api/knowledge/file_raw", "/api/wissen/file", "/api/branding/logo",
    "/api/knowledge/pull/file", "/api/info_files/", "/api/issues/",
)


def basis_typ(content_type: str) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def ist_aktiv(content_type: str) -> bool:
    """True fuer Inhaltstypen, die der Browser als DOKUMENT mit Skript deuten
    kann: HTML, SVG, jedes XML (``+xml``), XSLT, JavaScript."""
    t = basis_typ(content_type)
    if not t:
        return False
    return (t in ("text/html", "application/xhtml+xml", "image/svg+xml",
                  "text/xml", "application/xml", "text/xsl",
                  "application/javascript", "text/javascript",
                  "application/x-javascript", "application/ecmascript",
                  "text/ecmascript")
            or t.endswith("+xml") or t.endswith("/xml"))


def disposition(media: str) -> str:
    """'inline' nur fuer harmlos anzeigbare Typen, sonst 'attachment'."""
    return "inline" if basis_typ(media) in INLINE_TYPEN else "attachment"


def anzeige_typ(name: str) -> str:
    """MIME-Typ fuer die Auslieferung einer Datei nach ihrem Namen.

    Lesbare Textformate werden als ``text/plain; charset=utf-8`` geliefert
    (damit sie im Tab erscheinen statt als Download); alles andere geraten,
    Rueckfall ``application/octet-stream``."""
    endung = PurePath(name or "").suffix.lower()
    if endung in _ALS_TEXT:
        return "text/plain; charset=utf-8"
    return mimetypes.guess_type(name or "")[0] or "application/octet-stream"


def ist_datei_pfad(pfad: str) -> bool:
    return any((pfad or "").startswith(p) for p in DATEI_PFADE)


def kopfzeilen(pfad: str, content_type: str, hat_disposition: bool) -> dict:
    """Kopfzeilen, die eine Datei-Antwort mit aktivem Inhalt zusaetzlich traegt
    (leer = nichts zu tun). Ueberschreibt eine App-CSP an dieser Antwort."""
    if not ist_aktiv(content_type):
        return {}
    if not (ist_datei_pfad(pfad) or hat_disposition):
        return {}
    return {"Content-Security-Policy": SANDBOX_CSP,
            "X-Content-Type-Options": "nosniff"}
