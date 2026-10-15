"""TLS fuer jede LDAP-Verbindung mit Anmeldedaten – ohne Klartext-Rueckfall.

**Befund H5 (BSI-Abgleich 2026-09-29):** Login (``main.authenticate_linux_user``)
und Verzeichnis-Suche (``ldap_directory._bind``) versuchten StartTLS in einem
``try: … except: pass`` und banden danach in JEDEM Fall. Scheiterte StartTLS –
DC ohne Zertifikat, Firewall, jemand dazwischen, der das Extended-Request
verwirft –, ging das AD-Kennwort im Klartext ueber die Leitung. Geprueft wurde
das Zertifikat ausserdem nie (ldap3-Vorgabe ``CERT_NONE``): wer sich
dazwischenstellte, bekam das Kennwort auch MIT StartTLS.

**Jetzt gibt es genau einen Weg** (``verbinden``): TLS ist Pflicht (``ldaps://``
oder StartTLS), das Zertifikat wird geprueft, und scheitert eins davon, wird
``TlsFehler`` geworfen, BEVOR ein Bind stattfindet. Einen Rueckfall gibt es
nicht, auch keinen Schalter dafuer.

**Wogegen geprueft wird:**
  * Anker verankert und passt zu Host/Port -> genau dieses Zertifikat ist der
    einzige Vertrauensanker (``ad_tls_anker`` in settings.json, Eintrag wie
    ``sap_cert.eintrag_bauen``). Der Namensabgleich entfaellt nur, wenn beim
    Verankern GEMESSEN wurde, dass der Name nicht passt (IP statt FQDN) –
    akzeptiert wird dann trotzdem nur das gebundene Zertifikat.
  * sonst -> Systemspeicher mit Namensabgleich. Das ist der Weg, der eine
    Zertifikatserneuerung am DC ueberlebt: interne CA ins System
    (``/usr/local/share/ca-certificates`` + ``update-ca-certificates``) und als
    Domain-Controller den Namen eintragen, auf den das Zertifikat lautet.

**Gemessen auf DEV (2026-09-29, 10.0.0.50):** StartTLS geht, das Zertifikat
stammt von ``ROOT-CA-CONTOSO`` (nicht im Systemspeicher), lautet auf
``DS-DC01.firma.local`` – eingetragen ist die IP – und der DC schickt nur das
Blattzertifikat, keine Kette. Ohne Anker oder Systemeintrag scheitert damit
jede AD-Anmeldung; das ist gewollt (fail-closed), aber es ist die Folge.

Die Pruefung (``pruefen``) laeuft ueber DENSELBEN Verbindungsaufbau wie die
Anmeldung (``_oeffnen``) – ein Urteil "wuerde gehen", das ein anderer Weg
misst als der, der spaeter das Kennwort sendet, waere eine falsche Sonde.
"""

from __future__ import annotations

import hmac
import ssl
from urllib.parse import urlparse

from backend import sap_cert
from backend.config import config

# Feld in settings.json ("extra"), das den verankerten Vertrauensanker traegt
ANKER_FELD = "ad_tls_anker"

KANAL = "ad"
VERBINDUNGS_TIMEOUT = 6

# ── Uebergangsfrist (Entscheidung des Betreibers 2026-09-29) ────────────────
# ECHT holt master jede Nacht selbst ab. Ohne Frist haette jede AD-Anmeldung dort
# ab dem ersten Lauf versagt, bis ein Administrator mit lokalem Konto das
# DC-Zertifikat verankert. Bis zur Frist gilt deshalb: TLS bleibt PFLICHT (kein
# Klartext, DC ohne StartTLS wird abgewiesen), nur die ZERTIFIKATSPRUEFUNG wird
# ausgesetzt – und nur, solange KEIN Anker gesetzt ist. Ein gesetzter Anker, der
# nicht passt, ist genau der Angriffsfall und faellt nie in den Uebergang.
# Nach der Frist gilt automatisch die strenge Pruefung. Verschieben laesst sie
# sich nur ueber settings.json (``ad_tls_uebergang_bis``, ISO-Datum); ein
# unlesbarer Wert heisst streng (fail-closed).
UEBERGANG_FELD = "ad_tls_uebergang_bis"
UEBERGANG_BIS = "2026-10-13"


class TlsFehler(RuntimeError):
    """Keine gesicherte Verbindung – es wurde NICHTS gesendet, kein Bind."""


# ── Ziel ────────────────────────────────────────────────────────────────────

def ziel(ad_server: str) -> tuple[str, int, bool]:
    """``(host, port, ldaps)`` aus der Einstellung ``ad_server``.

    Erlaubt: ``host``, ``host:port``, ``ldap://host[:port]``,
    ``ldaps://host[:port]``. Ohne Schema gilt ldap:// mit StartTLS (so steht es
    auf DEV und ECHT in der Konfiguration). Wirft ``sap_cert.ZertFehler``.
    """
    roh = (ad_server or "").strip()
    if not roh:
        raise sap_cert.ZertFehler("Kein Domain-Controller angegeben.")
    schema = "ldap"
    if "://" in roh:
        schema, _, roh = roh.partition("://")
        schema = schema.strip().lower()
        if schema not in ("ldap", "ldaps"):
            raise sap_cert.ZertFehler("Unbekanntes Schema '%s://' – erlaubt sind "
                                      "ldap:// und ldaps://." % schema)
    teile = urlparse("//" + roh.rstrip("/"))
    if not teile.hostname:
        raise sap_cert.ZertFehler("Aus der Adresse laesst sich kein Servername lesen.")
    ldaps = schema == "ldaps"
    try:
        port = int(teile.port or (636 if ldaps else 389))
    except ValueError:
        raise sap_cert.ZertFehler("Port muss eine Zahl zwischen 1 und 65535 sein.") from None
    return teile.hostname, port, ldaps


def anker() -> dict | None:
    eintrag = config.get_setting(ANKER_FELD, None)
    return eintrag if isinstance(eintrag, dict) else None


def uebergang() -> dict:
    """``{"aktiv": bool, "bis": "YYYY-MM-DD"}`` – aktiv bis einschliesslich ``bis``."""
    import datetime
    bis = str(config.get_setting(UEBERGANG_FELD, UEBERGANG_BIS) or "").strip()
    try:
        ende = datetime.date.fromisoformat(bis)
    except ValueError:
        return {"aktiv": False, "bis": bis}
    return {"aktiv": datetime.date.today() <= ende, "bis": ende.isoformat()}


# ── Verbindungsaufbau (EIN Weg fuer Anmeldung und Pruefung) ─────────────────

def _tls(host: str, port: int, eintrag: dict | None, *, pruefen: bool = True,
         name_pruefen: bool = True, nur_anker: bool = False):
    """ldap3-Tls-Objekt. ``pruefen=False`` nur fuer das ABHOLEN des Zertifikats
    in ``pruefen()`` – dort wird nie gebunden."""
    import ldap3
    if not pruefen:
        return ldap3.Tls(validate=ssl.CERT_NONE)
    kw: dict = {"validate": ssl.CERT_REQUIRED}
    if nur_anker or sap_cert.passt(eintrag, host, port):
        # ca_certs_data -> create_default_context(cadata=…) laedt NUR dieses
        # Zertifikat, den Systemspeicher nicht (Python-Semantik, ldap3 2.9.1
        # core/tls.py wrap_socket). Strenger als der Systemspeicher.
        kw["ca_certs_data"] = (eintrag or {}).get("pem", "")
        if not name_pruefen or (eintrag or {}).get("name_abweichung"):
            # ldap3.check_hostname: '*' in valid_names gilt als Treffer. Der
            # Anker ist genau EIN Blattzertifikat, per Fingerabdruck bestaetigt.
            kw["valid_names"] = ["*"]
    return ldap3.Tls(**kw)


def _ist_netzfehler(e: BaseException) -> bool:
    """Server nicht erreichbar (kein TLS-Problem) – bleibt die urspruengliche
    Ausnahme, damit die Protokollzeile "AD nicht erreichbar" stimmt."""
    t = str(e).lower()
    if any(w in t for w in ("ssl", "certificate", "tls", "handshake")):
        return False
    return "LDAPSocketOpen" in type(e).__name__ or isinstance(e, OSError)


def _oeffnen(host: str, port: int, ldaps: bool, tls, user=None, password=None,
             timeout: int = VERBINDUNGS_TIMEOUT):
    """Verbindung oeffnen und TLS herstellen – noch KEIN Bind.

    Rueckgabe: offene ldap3-Connection mit aktivem TLS. Wirft ``TlsFehler``
    (TLS nicht zustande gekommen / Zertifikat abgelehnt) oder die
    Netzwerk-Ausnahme von ldap3 (nicht erreichbar).
    """
    import ldap3
    server = ldap3.Server(host, port=port, use_ssl=ldaps, tls=tls,
                          get_info=ldap3.NONE, connect_timeout=timeout)
    conn = ldap3.Connection(server, user=user, password=password, auto_bind=False,
                            receive_timeout=timeout)
    try:
        conn.open()                     # ldaps: Handshake + Pruefung hier
        if not ldaps and not conn.start_tls():
            raise TlsFehler("der Domain-Controller hat StartTLS abgelehnt")
    except TlsFehler:
        _schliessen(conn)
        raise
    except Exception as e:  # noqa: BLE001
        _schliessen(conn)
        if not ldaps and "startTLS failed" in str(e):
            raise TlsFehler("der Domain-Controller bietet kein StartTLS an (%s) – "
                            "als Adresse ldaps://… eintragen oder StartTLS am DC "
                            "einrichten" % str(e)[:80]) from None
        if _ist_netzfehler(e):
            raise
        raise TlsFehler(sap_cert._verify_grund(e)) from None
    return conn


def _schliessen(conn) -> None:
    try:
        conn.unbind()
    except Exception:  # noqa: BLE001
        pass


def verbinden(ad_server: str, user=None, password=None,
              timeout: int = VERBINDUNGS_TIMEOUT, info: dict | None = None):
    """Offene, TLS-gesicherte, GEPRUEFTE Verbindung – der Aufrufer bindet.

    Einziger Weg fuer Verbindungen mit Anmeldedaten (Login, Verzeichnis-Suche,
    Revalidierung). Wirft ``TlsFehler`` oder die Netzwerk-Ausnahme; in beiden
    Faellen hat der DC kein Kennwort gesehen.

    In der Uebergangsfrist (``uebergang()``) und OHNE Anker wird ein Zertifikat,
    das die Pruefung nicht besteht, noch angenommen – verschluesselt, aber
    ungeprueft; ``info["ungeprueft"]`` sagt es dem Aufrufer.
    """
    try:
        host, port, ldaps = ziel(ad_server)
    except sap_cert.ZertFehler as e:
        raise TlsFehler(str(e)) from None
    eintrag = anker()
    try:
        return _oeffnen(host, port, ldaps, _tls(host, port, eintrag), user, password, timeout)
    except TlsFehler:
        ue = uebergang()
        if not ue["aktiv"] or sap_cert.passt(eintrag, host, port):
            raise
    # Zweiter Aufbau ohne Pruefung – TLS bleibt Pflicht: ein DC ohne StartTLS
    # scheitert hier genauso und wirft weiter TlsFehler.
    conn = _oeffnen(host, port, ldaps, _tls(host, port, None, pruefen=False),
                    user, password, timeout)
    try:
        fp = sap_cert.fingerabdruck(conn.socket.getpeercert(binary_form=True) or b"")
    except Exception:  # noqa: BLE001
        fp = "?"
    print("[AUTH] WARNUNG: AD-Zertifikat von %s:%d UNGEPRUEFT angenommen (Uebergangsfrist "
          "bis %s, %s) – Einstellungen → Sicherheit → Verbindung: Zertifikat pruefen und "
          "verankern." % (host, port, ue["bis"], fp), flush=True)
    if info is not None:
        info["ungeprueft"] = True
    return conn


# ── Zertifikat pruefen und verankern (Baustein sapcert.js) ──────────────────

def _versuch(host, port, ldaps, tls) -> tuple[bool, str]:
    try:
        _schliessen(_oeffnen(host, port, ldaps, tls))
        return True, ""
    except TlsFehler as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, "Server nicht erreichbar: %s" % str(e)[:120]


def pruefen(ad_server: str) -> dict:
    """Zertifikat des DCs holen und beurteilen (wie ``sap_cert.pruefen``, aber
    ueber LDAP/StartTLS). Wirft ``sap_cert.ZertFehler``.

    ``system_ok``      – Anmeldung ginge schon jetzt (Systemspeicher + Name)
    ``pin_ok``         – mit genau diesem Zertifikat als Anker ginge sie
    ``name_abweichung`` – dabei passte der Name nicht (IP statt FQDN)
    """
    host, port, ldaps = ziel(ad_server)
    try:
        conn = _oeffnen(host, port, ldaps, _tls(host, port, None, pruefen=False))
    except TlsFehler as e:
        raise sap_cert.ZertFehler("Keine verschluesselte Verbindung zu %s:%d: %s"
                                  % (host, port, e)) from None
    except Exception as e:  # noqa: BLE001
        raise sap_cert.ZertFehler("Server %s:%d nicht erreichbar: %s"
                                  % (host, port, str(e)[:120])) from None
    try:
        der = conn.socket.getpeercert(binary_form=True) or b""
    except Exception:  # noqa: BLE001
        der = b""
    _schliessen(conn)
    if not der:
        raise sap_cert.ZertFehler("Der Domain-Controller hat kein Zertifikat vorgelegt.")

    pem = ssl.DER_cert_to_PEM_cert(der)
    probe = {"pem": pem}
    system_ok, system_grund = _versuch(host, port, ldaps, _tls(host, port, None))
    pin_ok, pin_grund, name_abweichung = True, "", False
    if not system_ok:
        pin_ok, pin_grund = _versuch(host, port, ldaps,
                                     _tls(host, port, probe, nur_anker=True))
        if not pin_ok:
            # Scheitert es NUR am Namen? Dann traegt der Anker trotzdem – der
            # Fingerabdruck bindet genau dieses eine Zertifikat.
            ok2, grund2 = _versuch(host, port, ldaps,
                                   _tls(host, port, probe, nur_anker=True,
                                        name_pruefen=False))
            if ok2:
                pin_ok, name_abweichung = True, True
            else:
                pin_grund = grund2 or pin_grund

    erg = {"host": host, "port": port, "kanal": KANAL,
           "fingerprint": sap_cert.fingerabdruck(der), "pem": pem,
           "system_ok": system_ok, "system_grund": system_grund,
           "system_quelle": "Systemspeicher",
           "pin_ok": pin_ok, "pin_grund": pin_grund,
           "name_abweichung": name_abweichung}
    erg.update(sap_cert._details(der))
    return erg


def bestaetigen(ad_server: str, fingerprint: str) -> dict:
    """Zertifikat erneut holen, mit dem gesehenen Fingerabdruck vergleichen und
    den Anker-Eintrag bauen. Das PEM kommt NIE aus dem Request. Wirft
    ``sap_cert.ZertFehler``. Speichern macht der Endpunkt."""
    if not sap_cert.fingerabdruck_gueltig(fingerprint):
        raise sap_cert.ZertFehler("Kein gueltiger Fingerabdruck uebergeben.")
    erg = pruefen(ad_server)
    if not hmac.compare_digest(erg["fingerprint"], fingerprint.strip().lower()):
        raise sap_cert.ZertFehler(
            "Das Zertifikat hat sich seit der Anzeige geaendert.\n"
            "bestaetigt: %s\ngefunden:   %s\n"
            "Bitte erneut pruefen und den neuen Fingerabdruck ansehen."
            % (fingerprint.strip().lower(), erg["fingerprint"]))
    if not (erg["system_ok"] or erg["pin_ok"]):
        # Gemessen: der Anker wuerde die Verbindung nicht tragen. Ein Eintrag,
        # der etwas verspricht, was die Anmeldung nicht haelt, wird nicht gebaut.
        raise sap_cert.ZertFehler("Verankern wuerde hier nicht helfen: %s"
                                  % (erg["pin_grund"] or erg["system_grund"]))
    eintrag = sap_cert.eintrag_bauen(erg)
    eintrag["name_abweichung"] = bool(erg["name_abweichung"])
    return eintrag
