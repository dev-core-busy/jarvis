"""Sicherheits-Kopfzeilen jeder Antwort (BSI H7).

Befund H7 aus dem BSI-Abgleich vom 2026-09-29 (APP.3.1.A21): HSTS,
X-Frame-Options, X-Content-Type-Options und Referrer-Policy fehlten (die CSP
kam mit H4, ``backend/csp.py``).

Gesetzt werden – per ``setdefault``, eine Route mit eigener Vorgabe gewinnt:

* ``X-Content-Type-Options: nosniff`` – jede Antwort. Der Browser deutet keine
  hochgeladene Datei mehr als Skript/HTML um, nur weil der Inhalt danach aussieht.
* ``Referrer-Policy: same-origin`` – Adressen (mit Abruf-Schluesseln und
  Suchbegriffen) gehen nicht an fremde Server, auch nicht beim Laden externer
  Bilder im Chat. Innerhalb von Jarvis bleibt der Referrer erhalten.
* ``X-Frame-Options: SAMEORIGIN`` – keine fremde Seite darf Jarvis in einen
  Rahmen laden (Clickjacking). Die eigenen Rahmen (Desktop, Vorschauen) sind
  gleicher Herkunft und bleiben moeglich.
  ⚠ AUSGENOMMEN die Office-Add-ins: Outlook/Excel im Web laden das
  Aufgabenfenster in einen iframe von Microsofts Hosts. X-Frame-Options kennt
  keine Liste erlaubter Hosts – dort gilt stattdessen ``frame-ancestors`` in
  der CSP mit den Office-Hosts (``csp.FRAME_ANCESTORS_OFFICE``).
* ``Strict-Transport-Security: max-age=31536000`` (1 Jahr, BSI-Vorgabe) – nur
  ueber HTTPS und nur, wenn das Server-Zertifikat NICHT selbst signiert ist.
  ⚠ HSTS macht jeden Zertifikatsfehler fuer ein Jahr unueberwindbar: wer bei
  einem selbst signierten Zertifikat (Jarvis erzeugt bei der Installation eines,
  DEV laeuft damit) die Warnung bisher wegklickt, waere ausgesperrt – und das
  liesse sich serverseitig nicht zuruecknehmen, der Browser merkt es sich.
  Kein ``includeSubDomains``: es braucht keiner, und es traefe Hosts, die
  Jarvis nicht kennt. Kein ``preload``.

``hsts_modus`` in settings.json: ``auto`` (Vorgabe, wie oben), ``an`` (immer
ueber HTTPS – nur mit einem Zertifikat, dem alle Clients vertrauen), ``aus``.
Ein unbekannter Wert gilt als ``auto``.
"""
from __future__ import annotations

import posixpath
import threading
from pathlib import Path

HSTS_WERT = "max-age=31536000"
HSTS_MODI = ("auto", "an", "aus")
HSTS_VORGABE = "auto"
REFERRER = "same-origin"

# Pfade, die Office im Web einrahmt (wie csp._ADDIN_PRAEFIXE)
ADDIN_PRAEFIXE = ("/addin/", "/excel-addin/", "/static/addin/", "/static/excel-addin/")

_get_setting = None
_zert_pfad: Path | None = None
_sperre = threading.Lock()
_zert_cache: tuple[float, bool] | None = None    # (mtime, selbst_signiert)


def einstellungen_quelle(fn, zertifikat: Path | None = None) -> None:
    """``main`` reicht ``config.get_setting`` und den Pfad des Server-Zertifikats
    herein (das Modul importiert ``backend.config`` nie selbst)."""
    global _get_setting, _zert_pfad, _zert_cache
    _get_setting = fn
    _zert_pfad = zertifikat
    _zert_cache = None


def hsts_modus() -> str:
    wert = HSTS_VORGABE
    if _get_setting is not None:
        try:
            wert = str(_get_setting("hsts_modus", HSTS_VORGABE) or HSTS_VORGABE).strip().lower()
        except Exception:  # noqa: BLE001
            wert = HSTS_VORGABE
    return wert if wert in HSTS_MODI else HSTS_VORGABE


def zertifikat_selbst_signiert() -> bool | None:
    """True/False fuer das Server-Zertifikat; None = nicht lesbar.
    Gemerkt bis sich die Datei aendert (mtime) – laeuft bei jeder Antwort."""
    global _zert_cache
    p = _zert_pfad
    if p is None:
        return None
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    with _sperre:
        if _zert_cache and _zert_cache[0] == mtime:
            return _zert_cache[1]
    try:
        from cryptography import x509
        z = x509.load_pem_x509_certificate(p.read_bytes())
        selbst = z.issuer == z.subject
    except Exception as e:  # noqa: BLE001
        print(f"[Kopfzeilen] Server-Zertifikat nicht lesbar ({e}) – kein HSTS", flush=True)
        return None
    with _sperre:
        _zert_cache = (mtime, selbst)
    return selbst


def hsts_aktiv() -> bool:
    """Wird HSTS gesendet (bei HTTPS)? ``auto``: nur bei einem Zertifikat, das
    nachweislich NICHT selbst signiert ist – unlesbar heisst: nein (fail-safe in
    die Richtung, die niemanden aussperrt)."""
    m = hsts_modus()
    if m == "aus":
        return False
    if m == "an":
        return True
    return zertifikat_selbst_signiert() is False


def _pfad_normal(pfad: str) -> str:
    """Wie ``csp.pfad_normal`` (hier ohne Import, das Modul bleibt eigenstaendig)."""
    p = pfad or ""
    if not p:
        return p
    n = posixpath.normpath(p)
    if p.endswith("/") and not n.endswith("/"):
        n += "/"
    return n


def kopfzeilen(pfad: str, https: bool) -> dict[str, str]:
    """Die Sicherheits-Kopfzeilen fuer eine Antwort unter ``pfad``."""
    k = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": REFERRER}
    # Am AUFGELOESTEN Pfad entscheiden: ``/static/addin/..%2Fportal.html``
    # kommt dekodiert an und ist das Portal, kein Add-in (csp.pfad_normal).
    pfad = _pfad_normal(pfad)
    if not any(pfad.startswith(p) for p in ADDIN_PRAEFIXE):
        k["X-Frame-Options"] = "SAMEORIGIN"
    if https and hsts_aktiv():
        k["Strict-Transport-Security"] = HSTS_WERT
    return k
