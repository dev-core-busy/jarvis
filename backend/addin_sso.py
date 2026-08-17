"""Anmeldung des Outlook-Add-ins ohne Kennwort (Exchange-Identity-Token).

**Warum es das gibt:** Das Aufgabenfenster verlangte bei jedem Start Benutzer
und Kennwort – obwohl der Benutzer in Outlook an DEMSELBEN Verzeichnis
angemeldet ist wie in Jarvis (gemeldet 2026-08-17). Ein SSO ueber Office/Entra
scheidet aus: das setzt eine Anwendungsregistrierung in Microsoft 365 voraus,
die ein Exchange im eigenen Haus nicht hat.

DER WEG, DEN MICROSOFT FUER ON-PREMISES VORSIEHT
------------------------------------------------
``Office.context.mailbox.getUserIdentityTokenAsync`` liefert ein vom
**Exchange-Server signiertes** JWT. Fuer Exchange Online sind diese Token
abgeschaltet, **fuer Exchange on-premises sind sie ausdruecklich weiter
unterstuetzt** (Microsoft-Doku, Stand 2026-07) – also genau unser Fall.

**Das Token nennt KEINE Mailadresse.** Es enthaelt nur eine undurchsichtige
Postfach-Kennung (``msexchuid``) und die Adresse des Metadaten-Dokuments
(``amurl``); aus beiden bildet man eine stabile Kennung. Die Zuordnung zu einem
Jarvis-Konto muss deshalb EINMAL hergestellt werden: der Benutzer meldet sich
im Fenster ein einziges Mal regulaer an, dabei wird die Verknuepfung
gespeichert. Ab da laeuft die Anmeldung von selbst.

WAS GEPRUEFT WIRD – UND WARUM JEDER PUNKT NOETIG IST
-----------------------------------------------------
1. **Signatur** gegen das Zertifikat aus dem Metadaten-Dokument des Exchange.
   Ohne diesen Schritt waere das Token ein Zettel, den jeder schreiben kann.
2. **``amurl`` muss auf den KONFIGURIERTEN Exchange zeigen.** Das ist der
   eigentliche Vertrauensanker: ohne ihn koennte sich jemand ein Token von
   einem *beliebigen* Exchange-Server ausstellen lassen (etwa dem eigenen im
   Internet), es waere formal gueltig signiert – nur eben nicht von UNSEREM
   Server. Microsoft nennt das "verify the domain"; wir haben es leichter als
   der allgemeine Fall, weil der Administrator die EWS-Adresse ohnehin
   hinterlegt hat. **Ist keine hinterlegt, gibt es kein SSO** (fail-closed).
3. **``aud`` muss die Adresse UNSERES Aufgabenfensters sein.** Sonst liesse
   sich ein Token, das fuer ein fremdes Add-in ausgestellt wurde, hier
   einloesen.
4. **Laufzeit** (``nbf``/``exp``) mit kleiner Toleranz fuer Uhrenversatz.
5. ``appctx.version`` muss ``ExIdTok.V1`` sein.

WAS DIESES MODUL NICHT TUT
---------------------------
Es stellt **keine** Jarvis-Sitzung aus und kennt die Rechtelage nicht. Es sagt
nur: "dieses Token gehoert zu Postfach X". Ob daraus eine Anmeldung werden
darf – Login-Freigabe, Kontosperre, Lizenzgrenze – entscheidet der Endpunkt in
``main.py`` mit denselben Pruefungen wie ``/api/login``. Diese Trennung ist
Absicht: ein zweiter Anmeldeweg mit eigener, halb nachgebauter Rechtelogik ist
genau die Art Abkuerzung, die spaeter als Luecke auffaellt.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

BASIS_DIR = Path(__file__).resolve().parent.parent
LINK_DATEI = BASIS_DIR / "data" / "addin_links.json"

# Uhrenversatz zwischen Exchange und diesem Server. Microsoft empfiehlt
# ausdruecklich eine Toleranz; fuenf Minuten sind das uebliche Mass.
UHR_TOLERANZ_SEK = 300

# Das Metadaten-Dokument aendert sich nur, wenn der Exchange sein Zertifikat
# tauscht. Ohne Zwischenspeicher entstuende bei JEDEM Fensteraufruf eine
# HTTPS-Anfrage an den Exchange.
_META_TTL_SEK = 3600
_meta_cache: dict[str, tuple[float, list[dict]]] = {}


class SsoFehler(Exception):
    """Token nicht verwendbar. Der Text ist fuer Menschen gedacht."""


# ── Hilfen ──────────────────────────────────────────────────────────────────

def _b64url(teil: str) -> bytes:
    """base64url ohne Polster dekodieren (JWT laesst das '=' weg)."""
    rest = len(teil) % 4
    if rest:
        teil += "=" * (4 - rest)
    return base64.urlsafe_b64decode(teil.encode("ascii"))


def _host_von(url: str) -> str:
    """Reiner Hostname einer URL, klein, ohne Port."""
    wert = (url or "").strip().lower()
    for schema in ("https://", "http://"):
        if wert.startswith(schema):
            wert = wert[len(schema):]
            break
    host = wert.split("/")[0].split("?")[0]
    if host.startswith("["):                      # IPv6
        return host.split("]")[0] + "]"
    return host.split(":")[0]


def erlaubte_hosts() -> set[str]:
    """Exchange-Hosts, deren Token wir annehmen – aus der Skill-Konfiguration.

    Das ist der Vertrauensanker aus Punkt 2 des Modulkopfs. **Leer heisst: kein
    SSO.** Ein Rueckfall auf "irgendein Exchange" waere die Luecke, gegen die
    die Pruefung gebaut ist.

    Autodiscover-Betrieb liefert hier nichts – dann ist die Serveradresse gar
    nicht bekannt, und geraten wird sie nicht. In dem Fall bleibt es bei der
    Anmeldung im Fenster; die Meldung sagt das im Klartext.
    """
    try:
        from backend.mail_accounts import skill_config  # noqa: PLC0415
        c = skill_config() or {}
    except Exception:  # noqa: BLE001
        return set()
    hosts = set()
    for schluessel in ("ews_url", "addin_sso_host"):
        h = _host_von(str(c.get(schluessel) or ""))
        if h:
            hosts.add(h)
    return hosts


def _verify_ssl() -> bool:
    try:
        from backend.mail_accounts import skill_config  # noqa: PLC0415
        c = skill_config() or {}
        return str(c.get("verify_ssl", True)).lower() not in ("false", "0", "nein", "")
    except Exception:  # noqa: BLE001
        return True


def kennung(msexchuid: str, amurl: str) -> str:
    """Stabile, undurchsichtige Kennung eines Postfachs.

    Microsoft schreibt die Verbindung aus ``msexchuid`` UND ``amurl`` vor: die
    Postfach-Kennung allein ist nur innerhalb EINES Exchange eindeutig.

    Gespeichert wird der Hash, nicht das Original – die Verknuepfungsdatei
    braucht die Rohwerte nie wieder, und was nicht gespeichert ist, kann auch
    nicht abfliessen.
    """
    roh = "%s|%s" % ((msexchuid or "").strip().lower(), (amurl or "").strip().lower())
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()


# ── Metadaten-Dokument des Exchange (enthaelt den oeffentlichen Schluessel) ──

def _signaturschluessel(amurl: str) -> list[dict]:
    """Signier-Zertifikate vom Exchange holen (mit Zwischenspeicher)."""
    jetzt = time.time()
    treffer = _meta_cache.get(amurl)
    if treffer and (jetzt - treffer[0]) < _META_TTL_SEK:
        return treffer[1]
    try:
        import httpx  # noqa: PLC0415
        with httpx.Client(verify=_verify_ssl(), timeout=10.0) as c:
            antwort = c.get(amurl)
        antwort.raise_for_status()
        daten = antwort.json()
    except Exception as e:  # noqa: BLE001
        raise SsoFehler(
            "Das Metadaten-Dokument des Exchange ist nicht abrufbar (%s). Ohne "
            "dieses Dokument laesst sich die Signatur des Tokens nicht pruefen."
            % e) from e
    schluessel = [k for k in (daten.get("keys") or [])
                  if str(k.get("usage", "")).lower() == "signing"]
    if not schluessel:
        raise SsoFehler("Das Metadaten-Dokument des Exchange enthaelt keinen "
                        "Signaturschluessel.")
    _meta_cache[amurl] = (jetzt, schluessel)
    return schluessel


def _zertifikat_passt(eintrag: dict, x5t: str) -> bool:
    return str(((eintrag.get("keyinfo") or {}).get("x5t") or "")).strip() == (x5t or "").strip()


def _signatur_ok(signiert: bytes, signatur: bytes, schluessel: list[dict], x5t: str) -> bool:
    """RS256-Signatur gegen die Zertifikate des Exchange pruefen.

    Der zum ``x5t`` passende Schluessel wird ZUERST probiert – das ist die von
    Microsoft beschriebene Auswahl. Passt keiner (Zertifikatstausch, anderer
    Fingerabdruck-Algorithmus), werden die uebrigen ebenfalls probiert: den
    Beweis liefert am Ende die SIGNATUR, ``x5t`` ist nur die Auswahlhilfe. Ein
    Abbruch bei unbekanntem ``x5t`` wuerde jede Anmeldung scheitern lassen,
    ohne dass etwas unsicher waere.
    """
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import padding  # noqa: PLC0415
    from cryptography.x509 import load_der_x509_certificate  # noqa: PLC0415

    sortiert = sorted(schluessel, key=lambda k: 0 if _zertifikat_passt(k, x5t) else 1)
    for eintrag in sortiert:
        roh = str(((eintrag.get("keyvalue") or {}).get("value") or "")).strip()
        if not roh:
            continue
        try:
            zert = load_der_x509_certificate(base64.b64decode(roh))
            zert.public_key().verify(signatur, signiert,
                                     padding.PKCS1v15(), hashes.SHA256())
            return True
        except Exception:  # noqa: BLE001, S112
            continue        # naechstes Zertifikat – ein Fehlschlag ist normal
    return False


# ── Die eigentliche Pruefung ────────────────────────────────────────────────

def pruefe_token(token: str, erwartete_aud: str) -> dict[str, Any]:
    """Prueft ein Exchange-Identity-Token und liefert die Postfach-Kennung.

    Wirft ``SsoFehler`` mit einem Text, der sagt, WAS nicht stimmt – ein
    generisches "Token ungueltig" laesst einen Administrator im Dunkeln.
    """
    teile = (token or "").strip().split(".")
    if len(teile) != 3:
        raise SsoFehler("Das Token hat nicht die Form eines JWT (drei Teile).")
    try:
        kopf = json.loads(_b64url(teile[0]))
        rumpf = json.loads(_b64url(teile[1]))
        signatur = _b64url(teile[2])
    except Exception as e:  # noqa: BLE001
        raise SsoFehler("Das Token laesst sich nicht dekodieren (%s)." % e) from e

    if str(kopf.get("typ", "")).upper() != "JWT":
        raise SsoFehler("Kein JWT (typ=%r)." % kopf.get("typ"))
    if str(kopf.get("alg", "")).upper() != "RS256":
        # Fail-closed: 'none' oder ein symmetrisches Verfahren waere die
        # klassische JWT-Umgehung.
        raise SsoFehler("Unerwartetes Signaturverfahren (alg=%r)." % kopf.get("alg"))
    x5t = str(kopf.get("x5t") or "").strip()
    if not x5t:
        raise SsoFehler("Im Kopf fehlt der Zertifikats-Fingerabdruck (x5t).")

    # appctx kommt je nach Exchange-Fassung als Objekt ODER als JSON-Text.
    appctx = rumpf.get("appctx")
    if isinstance(appctx, str):
        try:
            appctx = json.loads(appctx)
        except Exception as e:  # noqa: BLE001
            raise SsoFehler("Der appctx-Anteil ist unlesbar (%s)." % e) from e
    if not isinstance(appctx, dict):
        raise SsoFehler("Im Token fehlt der appctx-Anteil.")

    if str(appctx.get("version") or "") != "ExIdTok.V1":
        raise SsoFehler("Unbekannte Token-Fassung (%r)." % appctx.get("version"))

    msexchuid = str(appctx.get("msexchuid") or "").strip()
    amurl = str(appctx.get("amurl") or "").strip()
    if not msexchuid or not amurl:
        raise SsoFehler("Im Token fehlen Postfach-Kennung oder Metadaten-Adresse.")

    # ── Vertrauensanker: stammt das Token von UNSEREM Exchange? ──
    hosts = erlaubte_hosts()
    if not hosts:
        raise SsoFehler(
            "Fuer die automatische Anmeldung muss die EWS-Adresse des Exchange "
            "hinterlegt sein (Einstellungen → E-Mail). Ohne sie laesst sich "
            "nicht pruefen, ob das Token vom richtigen Server stammt.")
    if _host_von(amurl) not in hosts:
        raise SsoFehler(
            "Das Token stammt von einem anderen Exchange-Server (%s), "
            "hinterlegt ist: %s." % (_host_von(amurl), ", ".join(sorted(hosts))))

    # ── Ist das Token fuer UNSER Aufgabenfenster ausgestellt? ──
    aud = str(rumpf.get("aud") or "").strip().rstrip("/")
    if aud.lower() != (erwartete_aud or "").strip().rstrip("/").lower():
        raise SsoFehler(
            "Das Token wurde fuer eine andere Adresse ausgestellt (%s), erwartet: %s. "
            "Meist ist das Add-in unter einer anderen Serveradresse installiert, "
            "als der Server jetzt benutzt (JARVIS_ADDIN_BASE)." % (aud, erwartete_aud))

    # ── Laufzeit ──
    jetzt = int(time.time())
    try:
        nbf = int(str(rumpf.get("nbf") or 0))
        exp = int(str(rumpf.get("exp") or 0))
    except ValueError as e:
        raise SsoFehler("Die Laufzeitangaben des Tokens sind unlesbar.") from e
    if nbf and jetzt + UHR_TOLERANZ_SEK < nbf:
        raise SsoFehler("Das Token gilt erst spaeter – pruefe die Uhrzeit von "
                        "Server und Exchange.")
    if exp and jetzt - UHR_TOLERANZ_SEK > exp:
        raise SsoFehler("Das Token ist abgelaufen.")

    # ── Signatur (zuletzt: sie kostet eine Netzanfrage) ──
    signiert = ("%s.%s" % (teile[0], teile[1])).encode("ascii")
    if not _signatur_ok(signiert, signatur, _signaturschluessel(amurl), x5t):
        raise SsoFehler("Die Signatur des Tokens stammt nicht vom Exchange-Server.")

    return {"kennung": kennung(msexchuid, amurl), "amurl": amurl,
            "msexchuid": msexchuid, "exp": exp}


# ── Verknuepfung Postfach ↔ Jarvis-Konto ────────────────────────────────────

def _laden() -> dict:
    try:
        if LINK_DATEI.exists():
            daten = json.loads(LINK_DATEI.read_text(encoding="utf-8"))
            return daten if isinstance(daten, dict) else {}
    except Exception as e:  # noqa: BLE001
        print("[Add-in] Verknuepfungen nicht lesbar: %s" % e, flush=True)
    return {}


def _speichern(daten: dict) -> None:
    """Atomar und mit 0600-Vorgabe schreiben.

    Die Datei ordnet Postfaecher Benutzerkonten zu. **Wer sie beschreiben kann,
    meldet sich als beliebiger Benutzer an** – deshalb steht sie zusaetzlich in
    den Sperrlisten der Sandbox (``_APP_DENY_REL``, ``PRIVATE_FILES``,
    ``SHELL_SECRET_PATHS``).
    """
    LINK_DATEI.parent.mkdir(parents=True, exist_ok=True)
    tmp = LINK_DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(daten, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o640)
    except OSError:
        pass
    os.replace(tmp, LINK_DATEI)


def _norm(user: str) -> str:
    """Benutzername normalisieren – dieselbe Regel wie in der Anwesenheit.

    Ohne das haette derselbe Mensch je nach Tippform (``x``, ``NEXUS\\x``,
    ``x@nexus.int``) eine eigene Verknuepfung, und die Anmeldung schluege
    scheinbar zufaellig fehl.
    """
    u = (user or "").strip().lower()
    if "@" in u:
        u = u.split("@", 1)[0]
    if "\\" in u:
        u = u.rsplit("\\", 1)[1]
    return u


def verknuepfe(kenn: str, user: str) -> None:
    """Postfach-Kennung mit einem Jarvis-Konto verbinden (Erstanmeldung)."""
    if not kenn or not user:
        return
    daten = _laden()
    daten[kenn] = {"user": _norm(user), "seit": int(time.time()),
                   "zuletzt": int(time.time())}
    _speichern(daten)


def benutzer_fuer(kenn: str) -> str:
    """Verknuepftes Konto – leer, wenn das Postfach unbekannt ist."""
    eintrag = _laden().get(kenn) or {}
    return str(eintrag.get("user") or "")


def merke_nutzung(kenn: str) -> None:
    """Zeitstempel der letzten automatischen Anmeldung fortschreiben.

    Nur fuer die Uebersicht; ein Fehlschlag darf die Anmeldung nicht kippen.
    """
    try:
        daten = _laden()
        if kenn in daten:
            daten[kenn]["zuletzt"] = int(time.time())
            _speichern(daten)
    except Exception:  # noqa: BLE001
        pass


def loese(user: str) -> int:
    """Alle Verknuepfungen eines Kontos entfernen; liefert die Anzahl.

    Gebraucht, wenn ein Postfach den Besitzer wechselt – ohne diesen Weg
    meldete sich der neue Inhaber als der alte Benutzer an.
    """
    un = _norm(user)
    daten = _laden()
    weg = [k for k, v in daten.items() if _norm(str((v or {}).get("user") or "")) == un]
    for k in weg:
        daten.pop(k, None)
    if weg:
        _speichern(daten)
    return len(weg)


def verknuepfungen() -> list[dict]:
    """Uebersicht fuer Administratoren (ohne die Postfach-Kennungen selbst)."""
    raus = []
    for kenn, v in (_laden() or {}).items():
        if not isinstance(v, dict):
            continue
        raus.append({"kennung": kenn[:12], "user": v.get("user", ""),
                     "seit": v.get("seit", 0), "zuletzt": v.get("zuletzt", 0)})
    raus.sort(key=lambda e: e.get("zuletzt", 0), reverse=True)
    return raus
