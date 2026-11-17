"""Kurzlebiger Abruf-Schluessel fuer Datei-Links (statt des Sitzungstokens).

WARUM ES DAS GIBT (gemessen 2026-09-02): ein Download-Link sah so aus –

    /api/documents/<cap>.pptx?token=s.fischer:1786692855:c9630e30…

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

    JDL1.<benutzer-b64>.<ablauf>.<art>.<sitz>.<ziel>.<hmac>

``<art>`` (seit Code-Review 2026-10-07): ``v`` = volle Sitzung, ``e`` =
EINGESCHRAENKTE Sitzung (App-Anmeldung oder Admin ohne 2FA unter der Pflicht,
BSI M3). Vorher trug der Schluessel nur den Benutzer – und beim Einloesen galten
die Rechte des KONTOS: eine App-Sitzung eines Admins holte sich einen Schluessel
und bekam damit Kamerabild, Gesichtsdaten und die Dokumente aller Benutzer.
Ein Schluessel in der alten 4-teiligen Form gilt als eingeschraenkt (fail-closed).

``<sitz>`` (seit Code-Review 2026-10-07, 6-teilige Form): ``<ts>-<kennung>`` der
AUSSTELLENDEN Sitzung (Ausstellungszeit des Sitzungstokens und
``sitzung_token.schluessel``, nie das Token selbst), ``0`` ohne Sitzung
(Agent-API-Key). Vorher ueberlebte ein Schluessel Abmelden, Kennwortwechsel
und Zwangsabmeldung bis zu seinem Ablauf – ein abgegriffener Schluessel lud
nach dem Kennwortwechsel noch bis zu 15 (einstellbar 120) Minuten. Die
Pruefung gegen Widerruf und Epoche macht ``main._query_benutzer``; die alten
Formen ohne ``<sitz>`` laufen nur noch bis zu ihrem Ablauf aus.

  * **nur fuer Abruf-Endpunkte** – die Dependencies ``require_auth_or_query``
    und ``require_admin_or_query`` nehmen ihn an, ``verify_token`` NICHT. Damit
    ist er als ``Bearer`` wertlos: er oeffnet keine Einstellungen, keinen Chat,
    keine Wissensverwaltung.
  * **kurzlebig** – Vorgabe 15 Minuten (``download_key_ttl_min``, 1..120).
  * **an den Benutzer gebunden** – die Eigentuemer-Pruefung in
    ``documents.may_see`` und die Admin-Pruefung in ``require_admin_or_query``
    arbeiten unveraendert weiter.

``<ziel>`` (seit Pentest "Hardening" F-20, 2026-11-17, 7-teilige Form): der
Schluessel gilt nur noch fuer GENAU EINE Adresse. Bis dahin oeffnete ein
abgegriffener Schluessel (Verlauf, Proxy-Protokoll, weitergeleiteter Link) fuer
seine Laufzeit JEDE Datei, die der Benutzer laden darf. Das Ziel ist ein Hash
ueber Pfad und Abfrageparameter (``ziel_kanon``); ``token`` und der
Cache-Buster ``t`` zaehlen nicht mit, Reihenfolge und Kodierung der Parameter
ebenso wenig. **Die alten Formen ohne Ziel werden abgewiesen**
(Betreiberentscheid 2026-11-17: sofort, ohne Uebergang).

Die fruehere Begruendung gegen eine Bindung („die Renderer bauen Adressen
synchron") traegt nicht mehr: ``frontend/js/dlkey.js`` setzt beim Rendern einen
Platzhalter, holt die Schluessel im Sammelabruf (``POST /api/download-key``)
und schreibt sie nachtraeglich ins DOM – derselbe Weg, auf dem es seit
2026-09-04 abgelaufene Schluessel ersetzt. Der Client rechnet dabei keinen Hash
nach: er schickt die Adresse, der Server bildet das Ziel. Zwei Fassungen
derselben Kanonisierung (Python und JS) koennten nie auseinanderlaufen.

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
    """Weist ``?token=`` ein SITZUNGStoken ab? Vorgabe AN (BSI M4, 2026-10-05).

    Bis 2026-10-05 war die Vorgabe AUS: die Android-App baute ihre
    Anhang-Adresse mit dem Sitzungstoken (``IssuesRepository.kt``). Seitdem holt
    sie einen Abruf-Schluessel; Betreiberentscheid war, danach umzuschalten.
    **Preis:** eine aeltere App-Fassung oeffnet Issue-Anhaenge erst nach dem
    Update wieder (401), und ``/docs`` von Hand geht nur noch mit einem
    Abruf-Schluessel (``GET /api/download-key``) statt des Sitzungstokens.
    Jede abgewiesene Alt-Nutzung steht weiter im Journal (``[AUTH] ...
    abgewiesen (streng)``).

    Fail-closed: nur ein AUSDRUECKLICHES Nein (``false``/``0``/``nein``/``off``)
    schaltet zurueck – ein Tippfehler im Wert darf den Schutz nicht still
    abschalten.
    """
    v = config.get_setting("download_key_strict", True)
    if v is False:
        return False
    return str(v).strip().lower() not in ("false", "0", "nein", "no", "off", "aus")


def _sig(user: str, exp: int, art: str, sitz: str, ziel: str) -> str:
    inhalt = f"jdl1:{user}:{exp}:{art}:{sitz}:{ziel}"
    return hmac.new(config.SECRET_KEY.encode(), inhalt.encode(),
                    hashlib.sha256).hexdigest()


# Parameter, die NICHT zum Ziel gehoeren: der Schluessel selbst und der
# Cache-Buster der Kamerabilder (``?t=<Date.now()>``, wechselt bei jedem
# Neuladen – mit ihm braeuchte jedes Bild einen eigenen Schluessel). Kein
# Abruf-Endpunkt wertet ``t`` aus (gemessen 2026-11-17 an allen 16).
_ZIEL_OHNE = ("token", "t")


def ziel_kanon(pfad: str, params) -> str:
    """Kanonische Form eines Abruf-Ziels: dekodierter Pfad + sortierte Parameter.

    ``params``: Paare (Name, Wert), bereits DEKODIERT – so liefert sie
    Starlette (``request.query_params.multi_items()``) und ``parse_qsl``.
    Der Pfad wird ebenfalls dekodiert verglichen (``request.url.path`` ist es),
    damit ``%20`` und ein Leerzeichen dasselbe Ziel sind."""
    from urllib.parse import unquote, urlencode
    p = unquote(str(pfad or ""))
    paare = sorted((str(k), str(v)) for k, v in (params or ()) if str(k) not in _ZIEL_OHNE)
    return p + ("?" + urlencode(paare) if paare else "")


def ziel_aus_adresse(adresse: str) -> str:
    """Kanonische Form aus einer Adresse, wie der Client sie baut (relativ
    oder absolut). Nur Pfade unter ``/api/`` und die Schema-Seiten – ein
    Schluessel fuer eine beliebige Adresse waere sinnlos."""
    from urllib.parse import urlsplit, parse_qsl
    teile = urlsplit(str(adresse or "").strip())
    pfad = teile.path or ""
    if not (pfad.startswith("/api/") or pfad in ("/openapi.json", "/docs", "/redoc")):
        raise ValueError("kein Abruf-Ziel")
    return ziel_kanon(pfad, parse_qsl(teile.query, keep_blank_values=True))


def ziel_hash(kanon: str) -> str:
    """Kurzform des Ziels im Schluessel (144 Bit, base64url ohne Punkt)."""
    return base64.urlsafe_b64encode(
        hashlib.sha256(str(kanon).encode()).digest()[:18]).decode()


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _unb64(s: str) -> str:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()


def _sitz_text(sitzung) -> str:
    if not sitzung:
        return "0"
    ts, kennung = sitzung
    kennung = str(kennung)
    if not kennung.isalnum():
        raise ValueError("Sitzungskennung unzulaessig")
    return f"{int(ts)}-{kennung}"


def erzeugen(user: str, ttl_min: int | None = None,
             eingeschraenkt: bool = False,
             sitzung: "tuple[int, str] | None" = None,
             programm: bool = False, *, ziel: str) -> tuple[str, int]:
    """Schluessel + Ablaufzeitpunkt (Epoche) fuer diesen Benutzer.

    Der Benutzername wird base64url kodiert: er kann einen Domaenen-Praefix mit
    Rueckstrich tragen (``firma\\s.fischer``), und ein roher Wert in einer
    URL-getrennten Zeichenkette waere eine Einladung fuer Parser-Fehler.
    """
    if not user:
        raise ValueError("kein Benutzer")
    # ``ziel`` ist PFLICHT (keyword-only, ohne Vorgabe): ein Aufrufer, der es
    # vergisst, bekommt einen TypeError statt eines ungebundenen Schluessels.
    if not ziel:
        raise ValueError("kein Ziel")
    ttl = ttl_minuten() if ttl_min is None else max(1, min(int(ttl_min), _TTL_MAX))
    exp = int(time.time()) + ttl * 60
    # Art "p" (Pentest A7, 2026-11-08): Schluessel fuer einen PROGRAMMSCHLUESSEL
    # (Agent-API-Key) statt fuer eine Sitzung. ``sitzung`` traegt dann (0,
    # Kurzkennung des ausstellenden Programmschluessels) – beim Einloesen gilt
    # er nur, solange genau dieser Programmschluessel noch existiert. Die Art
    # steht in der Signatur; ein Sitzungs-Schluessel laesst sich nicht umetikettieren.
    art = "p" if programm else ("e" if eingeschraenkt else "v")
    sitz = _sitz_text(sitzung)
    zh = ziel_hash(ziel)
    return (f"{PRAEFIX}.{_b64(user)}.{exp}.{art}.{sitz}.{zh}."
            f"{_sig(user, exp, art, sitz, zh)}", exp)


def ist_abrufschluessel(wert: str) -> bool:
    """Sieht der Wert wie ein Abruf-Schluessel aus? (Form, nicht Gueltigkeit.)

    Braucht die Dependency, um zwischen „abgelaufener Schluessel" (401 mit
    eigener Meldung) und „Sitzungstoken" (Alt-Weg) zu unterscheiden.
    """
    return bool(wert) and wert.startswith(PRAEFIX + ".")


def grund(wert: str, ziel: str | None = None) -> str:
    """Warum wird dieses ``?token=`` nicht angenommen? – fuer die Protokollzeile.

    WARUM ES DAS GIBT (bezahlt am 2026-10-01): ein Datei-Abruf ohne gueltiges
    Merkmal endet in ``require_auth_or_query`` als ``HTTPException(401)`` – und
    die schreibt KEINE Zeile. Im Journal von ECHT war ueber drei Tage nichts zu
    finden, waehrend eine Benutzerin genau daran haengen blieb; der Browser
    macht aus dem 401 eine Frage nach Benutzername und Kennwort, also sah es
    nach einem Berechtigungsproblem aus. Ein Fehlschlag ohne Spur ist von
    „nichts passiert" nicht zu unterscheiden.

    Der Rueckgabewert nennt die URSACHE, nicht den Fehlschlag – der Unterschied
    zwischen „kein Token in der Adresse" (Frontend baut sie falsch) und
    „abgelaufen" (der bekannte 15-Minuten-Fall) entscheidet, wo man sucht.
    Der SCHLUESSEL selbst gehoert nie ins Protokoll: er ist ein Zugangsmerkmal.
    """
    if not wert:
        return "kein Token in der Adresse"
    if not ist_abrufschluessel(wert):
        return "Sitzungstoken statt Abruf-Schluessel" if streng() else "ungueltiges Sitzungstoken"
    teile = wert.split(".")
    if len(teile) != 7:
        return "Abruf-Schluessel ohne Zielbindung (alte Form, wird abgewiesen)"
    try:
        exp = int(teile[2])
    except Exception:  # noqa: BLE001
        return "Abruf-Schluessel unlesbar"
    alter = int(time.time()) - exp
    if alter > 0:
        return f"Abruf-Schluessel seit {alter} s abgelaufen (Laufzeit {ttl_minuten()} min)"
    if ziel is not None and teile[5] != ziel_hash(ziel):
        return "Abruf-Schluessel gilt fuer eine andere Adresse"
    return "Abruf-Schluessel: Signatur passt nicht"


def pruefen_voll(schluessel: str, ziel: str | None = None
                 ) -> "tuple[str | None, bool, tuple[int, str] | None]":
    """(Benutzername, eingeschraenkt?, Sitzung) oder (None, True, None).

    ``ziel`` = kanonische Form der ABGERUFENEN Adresse (``ziel_kanon``). Ohne
    Ziel gibt es keinen Zugang (fail-closed) – eine Pruefung, die das Ziel
    vergisst, darf nicht still zur ungebundenen werden. Die alten Formen
    (4/5/6 Teile, ohne Ziel) werden abgewiesen (F-20).

    Sitzung = ``(ts, kennung)`` der ausstellenden Sitzung oder None (ohne
    Sitzung)."""
    nein = (None, True, None)
    try:
        if not ziel or not ist_abrufschluessel(schluessel):
            return nein
        teile = schluessel.split(".")
        if len(teile) != 7:
            return nein
        _, b_user, s_exp, art, sitz, zh, sig = teile
        if art not in ("v", "e", "p"):
            return nein
        if not hmac.compare_digest(zh, ziel_hash(ziel)):
            return nein
        exp = int(s_exp)
        if exp < int(time.time()):
            return nein
        user = _unb64(b_user)
        if not user:
            return nein
        # compare_digest: die Laufzeit darf nicht verraten, wie weit die
        # Signatur uebereinstimmt.
        if not hmac.compare_digest(sig, _sig(user, exp, art, sitz, zh)):
            return nein
        sitzung = None
        if sitz != "0":
            s_ts, _, kennung = sitz.partition("-")
            if not kennung:
                return nein
            sitzung = (int(s_ts), kennung)
        return user, art != "v", sitzung
    except Exception:  # noqa: BLE001
        return nein


def programm_kennung(schluessel: str, ziel: str | None = None) -> str | None:
    """Kurzkennung des ausstellenden Programmschluessels – oder None.

    None heisst: KEIN gueltiger Schluessel der Art "p" (andere Art, Form,
    Ablauf oder Signatur falsch). Nur die 7-teilige (zielgebundene) Form wird angenommen.
    Der Aufrufer prueft die Kennung gegen die heute gueltigen Programmschluessel
    (ein widerrufener Schluessel nimmt seine Abruf-Schluessel mit)."""
    try:
        teile = (schluessel or "").split(".")
        if len(teile) != 7 or teile[3] != "p":
            return None
        user, _, sitzung = pruefen_voll(schluessel, ziel)
        if not user or not sitzung or sitzung[0] != 0:
            return None
        return sitzung[1]
    except Exception:  # noqa: BLE001
        return None


def pruefen_mit_art(schluessel: str, ziel: str | None = None) -> tuple[str | None, bool]:
    """(Benutzername, eingeschraenkt?) oder (None, True) – siehe pruefen_voll."""
    user, eingeschraenkt, _ = pruefen_voll(schluessel, ziel)
    return user, eingeschraenkt


def pruefen(schluessel: str, ziel: str | None = None) -> str | None:
    """Benutzername oder None. Fail-closed: jeder Fehler = kein Zugang."""
    return pruefen_mit_art(schluessel, ziel)[0]
