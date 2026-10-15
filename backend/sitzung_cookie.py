"""Sitzung der Weboberflaeche im HttpOnly-Cookie, CSRF-Token im Kopfsatz (BSI H4).

WARUM ES DAS GIBT (Befund H4, Rest „HttpOnly-Cookie + CSRF-Token"): bis
2026-10-12 lag das volle Sitzungstoken ``user:ts:sig`` im ``localStorage``.
Jedes eingeschleuste Skript konnte es lesen und mitnehmen – aus einer
XSS-Luecke wurde eine Kontouebernahme fuer bis zu 12 Stunden, auch nachdem der
Benutzer die Seite laengst geschlossen hatte.

Das Verfahren:

  * Die Anmeldung der Weboberflaeche schickt ``X-Jarvis-Sitzung: cookie``.
    Der Server legt das echte Token dann in das Cookie ``__Host-jarvis_sitzung``
    (HttpOnly, Secure, SameSite=Strict, Path=/) und gibt im Feld ``token`` statt
    des Tokens ein **CSRF-Token** zurueck: ``JCS1.<hmac(token)>``.
  * Das Frontend legt diesen Wert dort ab, wo vorher das Token lag, und schickt
    ihn wie bisher als ``Authorization: Bearer …``. Die ueber 180 Aufrufstellen
    bleiben damit unveraendert.
  * ``SitzungCookieMiddleware`` setzt vor dem Routing beides zusammen: passt
    das CSRF-Token zum Cookie, steht im Kopfsatz wieder das echte Token und
    alle Pruefungen (``require_auth`` & Co., Widerruf, 2FA-Kontext) laufen wie
    bisher. Passt es nicht, wird der Kopfsatz ENTFERNT – die Anfrage endet im
    gewohnten 401.

Was das bringt – und was nicht:

  * Ein eingeschleustes Skript liest nur noch das CSRF-Token. Das ist ohne das
    Cookie wertlos, und das Cookie ist fuer Skripte unsichtbar. Es kann die
    Sitzung also nur benutzen, solange die Seite offen ist, nicht mitnehmen.
  * Das Cookie ALLEIN berechtigt zu nichts: ohne den Kopfsatz mit dem passenden
    CSRF-Token setzt die Middleware nichts zusammen. Eine fremde Seite kann den
    Kopfsatz nicht setzen (kein CORS fuer fremde Urspruenge) und das Token nicht
    kennen; SameSite=Strict haelt das Cookie bei fremden Anfragen zusaetzlich
    zurueck. Das ist der CSRF-Schutz – fuer JEDE Methode, nicht nur fuer POST.
  * Apps, Add-ins und Programmschluessel schicken den Anmelde-Kopf nicht und
    bekommen weiter das echte Token (Bearer). Fuer sie aendert sich nichts.

Das CSRF-Token ist an das Sitzungstoken gebunden (HMAC mit dem Server-
Schluessel), nicht gespeichert: Widerruf, Laufzeit und Leerlauf gelten damit
unveraendert ueber das Token im Cookie. Ein neues Token (Kennwortwechsel,
neue Anmeldung) ergibt ein neues CSRF-Token.

Ohne HTTPS gibt es kein ``__Host-``-Cookie (der Browser verwirft es still) –
dann bleibt es beim Bearer-Token, siehe ``moeglich``.

Das Modul importiert ``backend.config`` nicht (Tests: der echte Import schreibt
die Live-settings.json); ``main`` reicht den Schluessel ueber
``schluessel_quelle`` herein.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac

COOKIE_NAME = "__Host-jarvis_sitzung"
# Anfrage-Kopf, mit dem die Weboberflaeche bei der Anmeldung das Cookie-Verfahren
# verlangt. Nur der Wert "cookie" zaehlt.
ANMELDE_KOPF = "x-jarvis-sitzung"
PRAEFIX = "JCS1."
# Kennung des Cookie-WERTS: das Token steht base64url-kodiert darin.
#
# WARUM (gemessen DEV 2026-10-12, erste AD-Anmeldung nach dem Ausrollen): ein
# AD-Token heisst `contoso\benutzer:ts:sig`. Ein Backslash ist in einem
# Cookie-Wert nicht erlaubt – Starlette setzt den Wert deshalb in
# Anfuehrungszeichen und VERDOPPELT den Backslash, zurueck kam
# `contoso\\benutzer`. Das CSRF-Token passte nicht mehr, jede Anfrage endete
# in 401, und die Anmeldemaske kam sofort wieder. Die Tests kannten nur Namen
# ohne Domaenen-Praefix. base64url besteht nur aus Zeichen, die nie maskiert
# werden – auch Umlaute im Namen ueberleben damit.
WERT_PRAEFIX = "t1."

_schluessel = None


def schluessel_quelle(fn) -> None:
    """``fn()`` liefert den Server-Schluessel (``config.SECRET_KEY``)."""
    global _schluessel
    _schluessel = fn


def _key() -> bytes:
    if _schluessel is None:
        # fail-closed: ohne Schluessel gibt es keine Bindung, also kein Cookie-Weg
        raise RuntimeError("sitzung_cookie: kein Schluessel")
    k = _schluessel()
    if not k:
        raise RuntimeError("sitzung_cookie: leerer Schluessel")
    return k.encode() if isinstance(k, str) else bytes(k)


def csrf_fuer(token: str) -> str:
    """CSRF-Token zu einem Sitzungstoken. Eigener Zweck-Praefix im HMAC, damit
    der Wert nie mit einer anderen Signatur desselben Schluessels zusammenfaellt."""
    mac = hmac.new(_key(), b"jarvis-csrf-v1\x00" + token.encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return PRAEFIX + mac


def ist_csrf(wert: str) -> bool:
    return isinstance(wert, str) and wert.startswith(PRAEFIX)


def aufloesen(csrf: str, cookie_token: str) -> str | None:
    """Echtes Token, wenn ``csrf`` zu ``cookie_token`` gehoert – sonst None.
    Vergleich als Bytes: ``compare_digest`` wirft bei Nicht-ASCII-``str``."""
    if not ist_csrf(csrf) or not cookie_token:
        return None
    try:
        erwartet = csrf_fuer(cookie_token)
    except Exception:  # noqa: BLE001 – kein Schluessel = keine Bindung
        return None
    if hmac.compare_digest(erwartet.encode("utf-8"), csrf.encode("utf-8")):
        return cookie_token
    return None


def gewuenscht(headers) -> bool:
    """Verlangt die Anfrage das Cookie-Verfahren? ``headers``: Mapping mit
    kleingeschriebenen Namen (Starlette ``Headers`` erfuellt das)."""
    try:
        return (headers.get(ANMELDE_KOPF) or "").strip().lower() == "cookie"
    except Exception:  # noqa: BLE001
        return False


def moeglich(scheme: str) -> bool:
    """``__Host-`` verlangt Secure – ueber http verwirft der Browser das Cookie
    still, die Anmeldung waere dann ein stiller Fehlschlag. Also nur ueber https."""
    return (scheme or "").lower() in ("https", "wss")


def wert_kodieren(token: str) -> str:
    roh = base64.urlsafe_b64encode(token.encode("utf-8")).decode("ascii").rstrip("=")
    return WERT_PRAEFIX + roh


def wert_lesen(wert: str) -> str:
    """Token aus dem Cookie-Wert ('' wenn unlesbar – fail-closed)."""
    wert = (wert or "").strip().strip('"')
    if not wert.startswith(WERT_PRAEFIX):
        return ""
    roh = wert[len(WERT_PRAEFIX):]
    try:
        return base64.urlsafe_b64decode(roh + "=" * (-len(roh) % 4)).decode("utf-8")
    except (binascii.Error, ValueError):
        return ""


def setzen(response, token: str, max_age: int) -> None:
    response.set_cookie(COOKIE_NAME, wert_kodieren(token), max_age=max(int(max_age), 60), path="/",
                        secure=True, httponly=True, samesite="strict")


def loeschen(response) -> None:
    # Dieselben Attribute wie beim Setzen – sonst gilt das Loeschen als ANDERES
    # Cookie (__Host- verlangt Secure + Path=/).
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True,
                           samesite="strict")


def cookie_aus_kopf(cookie_kopf: str) -> str:
    """Sitzungstoken aus einem rohen ``Cookie``-Kopf ('' wenn keines).
    Eigene Zerlegung statt http.cookies: SimpleCookie verwirft bei EINEM
    ungueltigen fremden Cookie den ganzen Kopf."""
    for teil in (cookie_kopf or "").split(";"):
        name, _, wert = teil.strip().partition("=")
        if name == COOKIE_NAME:
            return wert_lesen(wert)
    return ""


class SitzungCookieMiddleware:
    """Reine ASGI-Middleware (nur ``http``): ersetzt ``Authorization: Bearer
    JCS1.…`` durch das echte Token aus dem Cookie, wenn beides zusammengehoert,
    und entfernt den Kopfsatz sonst. ``scope["jarvis_sitzung_cookie"]`` haelt
    fest, dass die Anfrage ueber das Cookie angemeldet ist (Antworten mit einem
    neuen Token muessen dann wieder ein Cookie setzen, siehe main)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        auth_i = None
        auth_wert = ""
        cookie_kopf = ""
        for i, (k, v) in enumerate(scope.get("headers") or []):
            if k == b"authorization":
                auth_i, auth_wert = i, v.decode("latin-1")
            elif k == b"cookie":
                cookie_kopf += ("; " if cookie_kopf else "") + v.decode("latin-1")
        if auth_i is None:
            return await self.app(scope, receive, send)
        wert = auth_wert[7:].strip() if auth_wert[:7].lower() == "bearer " else ""
        if not ist_csrf(wert):
            return await self.app(scope, receive, send)
        echt = aufloesen(wert, cookie_aus_kopf(cookie_kopf))
        kopf = list(scope["headers"])
        if echt:
            kopf[auth_i] = (b"authorization", ("Bearer " + echt).encode("latin-1"))
        else:
            del kopf[auth_i]
        scope = dict(scope)
        scope["headers"] = kopf
        scope["jarvis_sitzung_cookie"] = bool(echt)
        return await self.app(scope, receive, send)
