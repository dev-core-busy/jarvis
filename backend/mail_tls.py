"""TLS fuer den E-Mail-Bereich: Pruefung IMMER an, Anker per Fingerabdruck.

**Befund (BSI-Abgleich 29.09.2026, Abschnitt 5, Skill ``email``, Schwere hoch):**
"TLS-Pruefung je Konto abschaltbar". Der Haken "Serverzertifikat pruefen" in
der Skill-Konfiguration schaltete fuer EWS, IMAP und SMTP auf ``CERT_NONE`` –
und ueber jede dieser Verbindungen geht das DOMAENENKENNWORT des Benutzers.
Dazu hing die kennwortlose Add-in-Anmeldung (``addin_sso``) am selben Haken:
ohne Pruefung haette ein Dazwischengeschalteter einen eigenen
Signaturschluessel unterschieben und sich als beliebiger Benutzer anmelden
koennen.

**Massnahme (Betreiberentscheid 2026-10-12, "wie H14"):** einen Weg zu "gar
keine Pruefung" gibt es nicht mehr. Ein selbst ausgestelltes Exchange-
Zertifikat wird stattdessen VERANKERT – genau dieses Zertifikat ist dann der
einzige Vertrauensanker der Verbindung (strenger als der Systemspeicher).
Bausteine aus ``sap_cert`` (Holen, Beurteilen, gemessene Bindung, PEM nie aus
dem Request), Oberflaeche ``sapcert.js``.

**Drei Kanaele, drei Ziele.** Gespeichert wird je Kanal ein Eintrag unter
``zert_anker`` in der Skill-Konfiguration, mit Host UND Port – nach einem
Adresswechsel passt der Anker nicht mehr und wird nicht still weitergeschleppt.
IMAP auf 143 und SMTP auf 587 sprechen STARTTLS: dort wird das Zertifikat
erst nach dem Klartext-Vorspann geholt, ein blosser TLS-Handshake auf den Port
saehe nichts.

**Vertrauensspeicher je Kanal** (dieselbe Falle wie bei SAP, siehe
``sap_cert._system_kontext``): EWS laeuft ueber ``requests`` und damit ueber
das certifi-Buendel, IMAP/SMTP ueber OpenSSL und damit den Systemspeicher.
Eine interne CA im Systemspeicher hilft EWS also nicht – genau das war der
uebliche Grund, den Haken abzuschalten.

**Bestand mit abgeschalteter Pruefung** (Betreiberentscheid: einmalige
Uebernahme). ``bestand_festschreiben()`` laeuft beim Start EINMAL: stand der
alte Schalter auf aus, werden die zu diesem Zeitpunkt eingetragenen Ziele
(EWS-Adresse, IMAP-, SMTP-Server) als "Uebernahme offen" festgehalten. Beim
ersten Verbindungsaufbau zu GENAU einem dieser Ziele wird das vorgelegte
Zertifikat verankert (laut im Journal) – vorher lief dieselbe Verbindung ganz
ohne Pruefung, die Uebernahme ist also strikt besser. Ein spaeter eingetragener
Server bekommt diese Ausnahme NICHT; die Liste waechst nie. Ohne die
Uebernahme haette das Update auf einem solchen Server den E-Mail-Betrieb
angehalten, bis ein Administrator den Reiter findet.
"""

from __future__ import annotations

import hmac
import imaplib
import smtplib
import socket
import ssl
import threading
import time
from urllib.parse import urlparse

KANAELE = ("ews", "imap", "smtp")
CERT_FELD = "zert_anker"                    # {kanal: eintrag aus sap_cert.eintrag_bauen}
BESTAND_FELD = "tls_bestand"                # Marke: alter Schalter einmal ausgewertet
UEBERNAHME_FELD = "tls_uebernahme_offen"    # ["kanal|host|port", ...] – waechst nie

VERBINDUNGS_TIMEOUT = 8.0

_sperre = threading.Lock()


def _log(text: str) -> None:
    print("[Mail-TLS] " + text, flush=True)


# ── Konfiguration ───────────────────────────────────────────────────────────

def _cfg() -> dict:
    from backend.mail_accounts import skill_config  # noqa: PLC0415
    return skill_config() or {}


def _cfg_schreiben(daten: dict) -> bool:
    """Felder in die Skill-Konfiguration MERGEN (wie ``update_skill_config``).

    Ohne vorhandenen Skill-Eintrag wird nichts angelegt – ein Eintrag, der nur
    aus TLS-Feldern besteht, haette den Skill-Zustand ``enabled`` offen gelassen.
    """
    from backend.config import config  # noqa: PLC0415
    states = config.get_skill_states()
    state = states.get("email")
    if not isinstance(state, dict):
        return False
    cfg = dict(state.get("config") or {})
    cfg.update(daten)
    state["config"] = cfg
    config.save_skill_state("email", state)
    return True


def _alt_aus(wert) -> bool:
    """Stand der alte Schalter ausdruecklich auf AUS? (nur ein echtes Nein zaehlt)"""
    if wert is False:
        return True
    return str(wert).strip().lower() in ("false", "0", "nein", "no", "off")


# ── Ziele ───────────────────────────────────────────────────────────────────

def _https_ziel(url: str):
    if not url:
        return None
    from backend.mail_client import ews_url_normieren  # noqa: PLC0415
    teile = urlparse(ews_url_normieren(url))
    if teile.scheme != "https" or not teile.hostname:
        return None
    try:
        return teile.hostname, int(teile.port or 443)
    except ValueError:
        return None


def _int(wert, vorgabe: int) -> int:
    try:
        return int(str(wert).strip())
    except (TypeError, ValueError):
        return vorgabe


def _ja(wert, vorgabe: bool) -> bool:
    if wert is None or wert == "":
        return vorgabe
    if isinstance(wert, bool):
        return wert
    return str(wert).strip().lower() not in ("false", "0", "nein", "no", "off")


def ziele(cfg: dict) -> dict:
    """``{kanal: (host, port, starttls)}`` der eingetragenen TLS-Ziele.

    ``starttls`` ist ``None`` (TLS von Anfang an), ``"imap"`` oder ``"smtp"``.
    Ein Kanal ohne Eintrag oder ohne TLS fehlt – ohne TLS gibt es kein
    Zertifikat zu pruefen.
    """
    erg: dict = {}
    ews = _https_ziel(str(cfg.get("ews_url") or "").strip())
    if ews:
        erg["ews"] = (ews[0], ews[1], None)
    host = str(cfg.get("imap_host") or "").strip()
    if host:
        mit_ssl = _ja(cfg.get("imap_ssl"), True)
        port = _int(cfg.get("imap_port"), 993 if mit_ssl else 143) or (993 if mit_ssl else 143)
        erg["imap"] = (host, port, None if mit_ssl else "imap")
    host = str(cfg.get("smtp_host") or "").strip()
    if host:
        port = _int(cfg.get("smtp_port"), 587) or 587
        if port == 465:
            erg["smtp"] = (host, port, None)
        elif _ja(cfg.get("smtp_starttls"), True):
            erg["smtp"] = (host, port, "smtp")
    return erg


def ziel_aus_angabe(kanal: str, angabe: dict, cfg: dict | None = None):
    """Ziel fuer Pruefen/Verankern aus den FORMULARFELDERN (vor dem Speichern,
    wie im SAP-Reiter), ersatzweise aus der gespeicherten Konfiguration.
    Wirft ``sap_cert.ZertFehler``."""
    from backend import sap_cert  # noqa: PLC0415
    if kanal not in KANAELE:
        raise sap_cert.ZertFehler("Unbekannter Kanal.")
    basis = dict(_cfg() if cfg is None else cfg)
    a = angabe or {}
    if kanal == "ews":
        if str(a.get("url") or "").strip():
            basis["ews_url"] = str(a.get("url")).strip()
    else:
        for feld in ("host", "port", "ssl", "starttls"):
            if a.get(feld) not in (None, ""):
                ziel = {"host": kanal + "_host", "port": kanal + "_port",
                        "ssl": "imap_ssl", "starttls": "smtp_starttls"}[feld]
                basis[ziel] = a.get(feld)
    z = ziele(basis).get(kanal)
    if z:
        return z
    if kanal == "ews":
        raise sap_cert.ZertFehler(
            "Keine EWS-Adresse eingetragen. Mit Autodiscover gilt die gewöhnliche "
            "Zertifikatsprüfung – verankern lässt sich nur eine eingetragene Adresse.")
    raise sap_cert.ZertFehler("Kein Server eingetragen, oder die Verbindung ist ohne "
                              "Verschlüsselung eingestellt – dann gibt es kein "
                              "Zertifikat zu prüfen.")


# ── TLS-Gespraech ───────────────────────────────────────────────────────────

def _der_holen(host: str, port: int, starttls, ctx: ssl.SSLContext) -> bytes:
    """Handshake (ggf. nach STARTTLS) und das DER-Zertifikat des Servers."""
    if starttls == "smtp":
        s = smtplib.SMTP(host, port, timeout=VERBINDUNGS_TIMEOUT)
        try:
            s.ehlo()
            s.starttls(context=ctx)
            return s.sock.getpeercert(binary_form=True) or b""
        finally:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
    if starttls == "imap":
        c = imaplib.IMAP4(host, port, timeout=VERBINDUNGS_TIMEOUT)
        try:
            c.starttls(ssl_context=ctx)
            return c.sock.getpeercert(binary_form=True) or b""
        finally:
            try:
                c.shutdown()
            except Exception:  # noqa: BLE001
                pass
    with socket.create_connection((host, port), timeout=VERBINDUNGS_TIMEOUT) as roh:
        with ctx.wrap_socket(roh, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True) or b""


def _handshake_ok(host: str, port: int, starttls, ctx) -> tuple[bool, str]:
    from backend import sap_cert  # noqa: PLC0415
    try:
        _der_holen(host, port, starttls, ctx)
        return True, ""
    except ssl.SSLCertVerificationError as e:
        return False, sap_cert._verify_grund(e)
    except ssl.SSLError as e:
        return False, "TLS-Fehler: %s" % e
    except (OSError, smtplib.SMTPException, imaplib.IMAP4.error) as e:
        return False, "Server nicht erreichbar: %s" % e


def _system_kontext(kanal: str):
    """Der Vertrauensspeicher, den der Kanal WIRKLICH benutzt (s. Modulkopf)."""
    from backend import sap_cert  # noqa: PLC0415
    return sap_cert._system_kontext("odata" if kanal == "ews" else "hana")


def pruefen(kanal: str, host: str, port: int, starttls=None) -> dict:
    """Zertifikat holen und beurteilen – wie ``sap_cert.pruefen`` (drei
    Handshakes: ohne Pruefung, gegen den Kanal-Speicher, gegen das Zertifikat
    als einzigen Anker), aber mit STARTTLS. Wirft ``sap_cert.ZertFehler``."""
    from backend import sap_cert  # noqa: PLC0415
    roh = ssl.create_default_context()
    roh.check_hostname = False
    roh.verify_mode = ssl.CERT_NONE
    try:
        der = _der_holen(host, port, starttls, roh)
    except ssl.SSLError as e:
        raise sap_cert.ZertFehler("Kein TLS auf %s:%d (%s)" % (host, port, e)) from None
    except (OSError, smtplib.SMTPException, imaplib.IMAP4.error) as e:
        raise sap_cert.ZertFehler("Server %s:%d nicht erreichbar: %s"
                                  % (host, port, e)) from None
    if not der:
        raise sap_cert.ZertFehler("Der Server hat kein Zertifikat vorgelegt.")
    pem = ssl.DER_cert_to_PEM_cert(der)
    sys_ctx, sys_quelle = _system_kontext(kanal)
    system_ok, system_grund = _handshake_ok(host, port, starttls, sys_ctx)
    pin_ok, pin_grund = True, ""
    if not system_ok:
        try:
            anker = ssl.create_default_context(cadata=pem)
        except Exception as e:  # noqa: BLE001
            pin_ok, pin_grund = False, "Zertifikat nicht als Anker verwendbar: %s" % e
        else:
            pin_ok, pin_grund = _handshake_ok(host, port, starttls, anker)
    erg = {"host": host, "port": port, "kanal": kanal,
           "fingerprint": sap_cert.fingerabdruck(der), "pem": pem,
           "system_ok": system_ok, "system_grund": system_grund,
           "system_quelle": sys_quelle, "pin_ok": pin_ok, "pin_grund": pin_grund}
    erg.update(sap_cert._details(der))
    return erg


def bestaetigen(kanal: str, host: str, port: int, starttls, fingerprint: str) -> dict:
    """Erneut holen, nur bei GLEICHEM Fingerabdruck einen Eintrag bauen. Das PEM
    kommt nie aus dem Request (Begruendung: ``sap_cert.bestaetigen``)."""
    from backend import sap_cert  # noqa: PLC0415
    if not sap_cert.fingerabdruck_gueltig(fingerprint):
        raise sap_cert.ZertFehler("Kein gueltiger Fingerabdruck uebergeben.")
    erg = pruefen(kanal, host, port, starttls)
    if not hmac.compare_digest(erg["fingerprint"], fingerprint.strip().lower()):
        raise sap_cert.ZertFehler(
            "Das Zertifikat hat sich seit der Anzeige geaendert.\n"
            "bestaetigt: %s\ngefunden:   %s\n"
            "Bitte erneut pruefen und den neuen Fingerabdruck ansehen."
            % (fingerprint.strip().lower(), erg["fingerprint"]))
    eintrag = sap_cert.eintrag_bauen(erg)
    eintrag["kanal"] = kanal
    return eintrag


# ── Bestand: einmalige Uebernahme ───────────────────────────────────────────

def _schluessel(kanal: str, host: str, port: int) -> str:
    return "%s|%s|%d" % (kanal, (host or "").strip().lower(), int(port))


def bestand_festschreiben() -> "list | None":
    """EINMAL je Installation: den alten Schalter auswerten und abloesen.

    Stand er auf AUS, werden die JETZT eingetragenen Ziele zur einmaligen
    Uebernahme vorgemerkt. In jedem Fall wird ``verify_ssl`` auf ``True``
    gesetzt und die Marke geschrieben – ein spaeter (etwa ueber die API)
    wieder auf aus gesetzter Schalter hat danach keine Wirkung mehr, auch
    keine als "Bestand". Rueckgabe: die vorgemerkten Ziele, ``None`` wenn
    nichts zu tun war.
    """
    try:
        with _sperre:
            cfg = _cfg()
            if not cfg or cfg.get(BESTAND_FELD):
                return None
            aus = _alt_aus(cfg.get("verify_ssl"))
            offen = ([_schluessel(k, h, p) for k, (h, p, _s) in sorted(ziele(cfg).items())]
                     if aus else [])
            if not _cfg_schreiben({
                    BESTAND_FELD: {"am": int(time.time()), "pruefung_war_aus": aus},
                    UEBERNAHME_FELD: offen,
                    "verify_ssl": True}):
                return None
        if aus:
            _log("Die Zertifikatspruefung war abgeschaltet und ist jetzt immer an. "
                 "Einmalig uebernommen wird beim naechsten Verbindungsaufbau das "
                 "Zertifikat von: %s" % (", ".join(offen) or "(kein Ziel eingetragen)"))
        return offen
    except Exception as e:  # noqa: BLE001
        _log("Bestand nicht festgeschrieben: %s" % e)
        return None


def _uebernehmen(kanal: str, host: str, port: int, starttls, cfg: dict):
    """Vorgemerktes Ziel: Zertifikat einmalig verankern (oder streichen, wenn
    die gewoehnliche Pruefung ohnehin besteht). Rueckgabe: Eintrag oder None."""
    from backend import sap_cert  # noqa: PLC0415
    key = _schluessel(kanal, host, port)
    if key not in list(cfg.get(UEBERNAHME_FELD) or []):
        return None
    with _sperre:
        cfg = _cfg()
        offen = list(cfg.get(UEBERNAHME_FELD) or [])
        if key not in offen:
            return anker(kanal, host, port, cfg)
        try:
            erg = pruefen(kanal, host, port, starttls)
        except sap_cert.ZertFehler as e:
            _log("Uebernahme %s verschoben – %s" % (key, e))
            return None
        offen.remove(key)
        if erg["system_ok"]:
            _cfg_schreiben({UEBERNAHME_FELD: offen})
            _log("Uebernahme %s entfaellt: die gewoehnliche Pruefung besteht." % key)
            return None
        eintrag = sap_cert.eintrag_bauen(erg)
        eintrag["kanal"] = kanal
        eintrag["uebernommen"] = True
        alle = dict(cfg.get(CERT_FELD) or {})
        alle[kanal] = eintrag
        _cfg_schreiben({CERT_FELD: alle, UEBERNAHME_FELD: offen})
        _log("BESTAND: Zertifikat fuer %s:%d (%s) einmalig verankert – %s, "
             "Inhaber %r. Pruefen unter Einstellungen → E-Mail."
             % (host, port, kanal, eintrag["fingerprint"], eintrag.get("inhaber", "")))
        if eintrag.get("name_abweichung") and kanal == "ews":
            _log("ACHTUNG: der Name im Zertifikat passt nicht zur EWS-Adresse – "
                 "fuer EWS laesst sich das nicht ueberbruecken; die Adresse eintragen, "
                 "auf die das Zertifikat lautet.")
        return eintrag


# ── Anker anwenden ──────────────────────────────────────────────────────────

def anker(kanal: str, host: str, port: int, cfg: dict | None = None):
    """Verankerter Eintrag fuer genau dieses Ziel, sonst None."""
    from backend import sap_cert  # noqa: PLC0415
    cfg = _cfg() if cfg is None else cfg
    eintrag = (cfg.get(CERT_FELD) or {}).get(kanal)
    return eintrag if sap_cert.passt(eintrag, host, port) else None


def _eintrag_fuer(kanal: str, host: str, port: int, starttls=None):
    cfg = _cfg()
    return anker(kanal, host, port, cfg) or _uebernehmen(kanal, host, port, starttls, cfg)


def ssl_kontext(kanal: str, host: str, port: int, starttls=None) -> ssl.SSLContext:
    """TLS-Kontext fuer IMAP/SMTP (und httpx) – die Pruefung ist IMMER an.

    Anker passt -> genau dieses Zertifikat ist der einzige Vertrauensanker;
    ``check_hostname`` nur aus, wenn beim Verankern GEMESSEN wurde, dass der
    Name nicht passt (``verify_mode`` bleibt ``CERT_REQUIRED``). Sonst der
    Vertrauensspeicher des Kanals. Ein unbrauchbarer Anker fuehrt zur
    gewoehnlichen Pruefung, nie zu ``CERT_NONE`` (fail-closed).
    """
    eintrag = _eintrag_fuer(kanal, host, port, starttls)
    if eintrag:
        try:
            ctx = ssl.create_default_context(cadata=eintrag["pem"])
        except Exception as e:  # noqa: BLE001
            _log("Anker fuer %s:%s unbrauchbar (%s) – gewoehnliche Pruefung" % (host, port, e))
            return _system_kontext(kanal)[0]
        if eintrag.get("name_abweichung"):
            ctx.check_hostname = False
        return ctx
    return _system_kontext(kanal)[0]


def requests_verify(url: str):
    """``verify`` fuer requests (EWS ueber exchangelib): Pfad zum Anker-Buendel
    oder ``True``. ``requests`` nimmt keinen SSLContext, deshalb die Datei aus
    ``sap_cert.bundle_pfad``. Nie ``False``."""
    from backend import sap_cert  # noqa: PLC0415
    try:
        teile = urlparse(url or "")
        host, port = teile.hostname, int(teile.port or 443)
    except (TypeError, ValueError):
        return True
    if teile.scheme != "https" or not host:
        return True
    try:
        eintrag = _eintrag_fuer("ews", host, port)
        if eintrag:
            return sap_cert.bundle_pfad(eintrag.get("pem", ""))
    except Exception as e:  # noqa: BLE001
        _log("Anker fuer %s:%s unbrauchbar (%s) – gewoehnliche Pruefung" % (host, port, e))
    return True


def anker_info(cfg: dict | None = None) -> dict:
    """``{kanal: sap_cert.info(...)}`` fuer die Oberflaeche – ohne PEM."""
    from backend import sap_cert  # noqa: PLC0415
    cfg = _cfg() if cfg is None else cfg
    alle = cfg.get(CERT_FELD) or {}
    return {k: sap_cert.info(alle.get(k)) for k in KANAELE}
