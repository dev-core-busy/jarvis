"""Kurzlebiger Abruf-Schluessel fuer Datei-Links (statt des Sitzungstokens).

WARUM ES DAS GIBT (gemessen 2026-09-02): ein Download-Link sah so aus –

    /api/documents/<cap>.pptx?token=sven.sander:1786692855:c9630e30…

Darin steht **die volle Sitzung**, nicht ein Datei-Schluessel. Nachgemessen:
dasselbe Token, als ``Authorization: Bearer`` gesendet, liefert ``/api/me``,
``/api/chat/sessions``, ``/api/knowledge/groups`` und ``/api/sessions`` je 200.
Es lebt ausserdem **30 Tage ab Ausstellung** (``verify_token``), nicht ab
letzter Benutzung – der gemeldete Link war am Meldetag noch 10,5 Tage gueltig.
Wer so einen Link weitergibt (Mail, Ticket, Screenshot der Adresszeile,
Proxy-Protokoll), gibt seine Sitzung weiter.

Ein Token in der Adresse ist unvermeidlich: ``<a download>`` und ``<img src>``
koennen keinen ``Authorization``-Header setzen. **Dass es das SITZUNGStoken
ist, ist es nicht.** Dieses Modul stellt ein zweites, schwaecheres Merkmal aus:

    JDL1.<benutzer-b64>.<ablauf>.<hmac>

  * **nur fuer Abruf-Endpunkte** – die Dependencies ``require_auth_or_query``
    und ``require_admin_or_query`` nehmen ihn an, ``verify_token`` NICHT. Damit
    ist er als ``Bearer`` wertlos: er oeffnet keine Einstellungen, keinen Chat,
    keine Wissensverwaltung.
  * **kurzlebig** – Vorgabe 15 Minuten (``download_key_ttl_min``, 1..120).
  * **an den Benutzer gebunden** – die Eigentuemer-Pruefung in
    ``documents.may_see`` und die Admin-Pruefung in ``require_admin_or_query``
    arbeiten unveraendert weiter.

**Was er NICHT ist: an EINE Datei gebunden.** Das waere strenger, verlangt aber
einen Server-Aufruf je Link – und alle vierzehn Stellen, die im Frontend eine
solche Adresse bauen, tun das **synchron beim Rendern** (``chatlib::_withToken``
und Geschwister). Eine Bindung je Datei haette entweder den Renderer async
gemacht oder den Schluessel in den gespeicherten Chatverlauf geschrieben, wo er
nichts zu suchen hat. Der Gewinn ist trotzdem der entscheidende: aus „30 Tage
volle Sitzung" wird „15 Minuten Lesezugriff auf das, was dieser Benutzer
ohnehin herunterladen darf".

``verify_token`` kann diesen Schluessel schon von der Form her nicht annehmen
(kein ``:``) – die Trennung haengt also nicht an einer Reihenfolge von
Pruefungen, sondern am Format. Ein Test haelt das fest.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from backend.config import config

PRAEFIX = "JDL1"
_TTL_VORGABE = 15          # Minuten
_TTL_MAX = 120


def ttl_minuten() -> int:
    """Lebensdauer in Minuten. FUNKTION, keine Konstante – ein beim Import
    gelesener Wert waere bis zum Dienst-Neustart wirkungslos."""
    try:
        n = int(config.get_setting("download_key_ttl_min", _TTL_VORGABE))
    except Exception:  # noqa: BLE001
        return _TTL_VORGABE
    if n < 1:
        return 1
    return min(n, _TTL_MAX)


def streng() -> bool:
    """Weist ``?token=`` ein SITZUNGStoken ab? Vorgabe AUS.

    Der Uebergang ist bewusst nicht hart: die Android-App baut ihre
    Anhang-Adresse mit dem Sitzungstoken (``IssuesRepository.kt``), und
    ``/docs``/``/redoc`` werden von einem Menschen mit ``?token=`` aufgerufen –
    beides laesst sich nicht im selben Zug mitliefern. Ein harter Schnitt haette
    einen ausgelieferten Client gebrochen.
    Der Weg zum Endzustand ist trotzdem da: einschalten, sobald das Journal
    keine Alt-Nutzung mehr meldet.
    """
    v = config.get_setting("download_key_strict", False)
    return v is True or str(v).lower() in ("1", "true", "ja", "yes")


def _sig(user: str, exp: int) -> str:
    return hmac.new(config.SECRET_KEY.encode(),
                    f"jdl1:{user}:{exp}".encode(),
                    hashlib.sha256).hexdigest()


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _unb64(s: str) -> str:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()


def erzeugen(user: str, ttl_min: int | None = None) -> tuple[str, int]:
    """Schluessel + Ablaufzeitpunkt (Epoche) fuer diesen Benutzer.

    Der Benutzername wird base64url kodiert: er kann einen Domaenen-Praefix mit
    Rueckstrich tragen (``nexus\\sven.sander``), und ein roher Wert in einer
    URL-getrennten Zeichenkette waere eine Einladung fuer Parser-Fehler.
    """
    if not user:
        raise ValueError("kein Benutzer")
    ttl = ttl_minuten() if ttl_min is None else max(1, min(int(ttl_min), _TTL_MAX))
    exp = int(time.time()) + ttl * 60
    return f"{PRAEFIX}.{_b64(user)}.{exp}.{_sig(user, exp)}", exp


def ist_abrufschluessel(wert: str) -> bool:
    """Sieht der Wert wie ein Abruf-Schluessel aus? (Form, nicht Gueltigkeit.)

    Braucht die Dependency, um zwischen „abgelaufener Schluessel" (401 mit
    eigener Meldung) und „Sitzungstoken" (Alt-Weg) zu unterscheiden.
    """
    return bool(wert) and wert.startswith(PRAEFIX + ".")


def pruefen(schluessel: str) -> str | None:
    """Benutzername oder None. Fail-closed: jeder Fehler = kein Zugang."""
    try:
        if not ist_abrufschluessel(schluessel):
            return None
        _, b_user, s_exp, sig = schluessel.split(".", 3)
        exp = int(s_exp)
        if exp < int(time.time()):
            return None
        user = _unb64(b_user)
        if not user:
            return None
        # compare_digest: die Laufzeit darf nicht verraten, wie weit die
        # Signatur uebereinstimmt.
        if not hmac.compare_digest(sig, _sig(user, exp)):
            return None
        return user
    except Exception:  # noqa: BLE001
        return None
