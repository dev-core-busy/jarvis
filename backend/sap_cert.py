"""Serverzertifikat eines SAP-Systems pruefen und als Vertrauensanker verankern.

**Warum es das gibt:** Im SAP-Reiter gab es nur den Haken "SSL-Zertifikat
pruefen" – an oder aus. Bei einem SAP-System mit selbst ausgestelltem Zertifikat
blieb dem Administrator nur das Abschalten, und danach ist JEDE SAP-Verbindung
gegen einen Man-in-the-Middle offen, ohne dass es jemand sieht. Beim
persoenlichen Zugang (``sap_accounts``) war es schlimmer: ``verify_ssl`` kommt
dort ausschliesslich aus der Admin-Konfiguration, ein Benutzer mit eigenem
Server hatte also gar keinen Weg.

**Verankern statt abschalten:** genau EIN Zertifikat wird Vertrauensanker der
Verbindung. Die Pruefung bleibt AN – ein spaeterer Zertifikatswechsel bricht ab
und muss bewusst uebernommen werden. Das ist strenger als der System-
Vertrauensspeicher, nicht schwaecher. Vorbild ist die Bindung im Standort-Sync
(``knowledge_sync._ssl_kontext`` / ``zertifikat_abfragen``).

**DIE BINDUNG WIRD GEMESSEN, NICHT ABGELEITET.** ``pruefen()`` macht bis zu drei
TLS-Handshakes:

  1. ohne Pruefung  -> das Zertifikat ueberhaupt bekommen
  2. gegen den System-Vertrauensspeicher -> braucht es einen Anker?
  3. gegen das geholte Zertifikat als ``cadata`` -> **wuerde der Anker wirken?**

Erst (3) beantwortet die Frage, die zaehlt. Ohne sie muesste man ueber
Namensabweichungen raten (der haeufigste Fall: das Zertifikat lautet auf den
FQDN, in der URL steht eine IP) – und der Knopf "Diesem Zertifikat vertrauen"
verspraeche etwas, das die Verbindung spaeter nicht haelt. Genau die
Fehlerklasse "eine Zusage, die der Code nicht haelt".

**Der Browser spielt hier keine Rolle.** Alle SAP-Aufrufe macht das Backend; ein
Eintrag im Vertrauensspeicher des Browsers wuerde der Verbindung nichts nuetzen.
Wirksam ist allein der Anker hier.

**Das Buendel ist eine DATEI, weil ``requests.verify`` keinen SSLContext nimmt** –
nur ``bool`` oder einen Pfad. ``data/sap_certs/<fp16>.pem`` enthaelt deshalb
GENAU das verankerte Zertifikat und nichts sonst; ein oeffentlich signiertes
Zertifikat wuerde damit folgerichtig abgelehnt. Das Verzeichnis steht in
``sandbox._APP_DENY_REL``: ein beschreibbarer Vertrauensanker waere ein
bequemer Weg, eine SAP-Verbindung umzuleiten.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import socket
import ssl
import time
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CERT_DIR = PROJECT_ROOT / "data" / "sap_certs"
DATEI_MODUS = 0o640
DIR_MODUS = 0o750

# Kanaele mit TLS-Serverzertifikat. RFC steht bewusst NICHT dabei: dort gibt es
# kein Serverzertifikat in diesem Sinne (SNC ist ein anderes Verfahren).
KANAELE = ("odata", "hana")

VERBINDUNGS_TIMEOUT = 8.0


class ZertFehler(RuntimeError):
    """Zertifikat nicht ermittelbar oder Fingerabdruck passt nicht."""


# ── Ziel bestimmen ──────────────────────────────────────────────────────────

def ziel_bestimmen(kanal: str, angabe: dict) -> tuple[str, int]:
    """``(host, port)`` aus den Formularangaben.

    OData kommt als URL (Basis-URL des Gateways), HANA als Host + Port. Die
    Angabe stammt aus dem REQUEST und nicht aus der gespeicherten Konfiguration,
    damit man ein Zertifikat pruefen kann, BEVOR man speichert – sonst muesste
    man erst eine Verbindung ablegen, von der man noch nicht weiss, ob sie geht.
    """
    kanal = (kanal or "").strip().lower()
    if kanal not in KANAELE:
        raise ZertFehler("Unbekannter Kanal '%s' – erlaubt sind: %s"
                         % (kanal, ", ".join(KANAELE)))
    if kanal == "hana":
        host = str(angabe.get("host") or "").strip()
        # Ein Copy&Paste "host:port" soll nicht an einer Kleinigkeit scheitern.
        if host and ":" in host and not host.startswith("["):
            host, _, rest = host.partition(":")
            if not angabe.get("port") and rest.isdigit():
                angabe = dict(angabe, port=rest)
        try:
            port = int(str(angabe.get("port") or 443).strip() or 443)
        except (TypeError, ValueError):
            raise ZertFehler("Port muss eine Zahl sein.") from None
        if not host:
            raise ZertFehler("Kein HANA-Host angegeben.")
        if not 1 <= port <= 65535:
            raise ZertFehler("Port muss zwischen 1 und 65535 liegen.")
        return host.strip("[]"), port

    roh = str(angabe.get("url") or angabe.get("host") or "").strip()
    if not roh:
        raise ZertFehler("Keine Basis-URL angegeben.")
    if "://" not in roh:
        roh = "https://" + roh
    teile = urlparse(roh)
    if teile.scheme != "https":
        # http hat kein Zertifikat – das ist keine Fehlbedienung, die man
        # kommentarlos in einen TLS-Handshake laufen laesst.
        raise ZertFehler("Die Adresse ist kein HTTPS – ohne TLS gibt es kein "
                         "Serverzertifikat zu pruefen.")
    if not teile.hostname:
        raise ZertFehler("Aus der Adresse laesst sich kein Servername lesen.")
    return teile.hostname, int(teile.port or 443)


# ── Zertifikat holen und beurteilen ─────────────────────────────────────────

def _der_holen(host: str, port: int, ctx: ssl.SSLContext) -> bytes:
    with socket.create_connection((host, port), timeout=VERBINDUNGS_TIMEOUT) as roh:
        with ctx.wrap_socket(roh, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True) or b""


def _handshake_ok(host: str, port: int, ctx: ssl.SSLContext) -> tuple[bool, str]:
    """Handshake versuchen. Rueckgabe ``(ok, grund)`` – Grund nur bei Misserfolg."""
    try:
        _der_holen(host, port, ctx)
        return True, ""
    except ssl.SSLCertVerificationError as e:
        return False, _verify_grund(e)
    except ssl.SSLError as e:
        return False, "TLS-Fehler: %s" % e
    except OSError as e:
        return False, "Server nicht erreichbar: %s" % e


def _verify_grund(e: Exception) -> str:
    """Aus dem OpenSSL-Text eine Aussage machen, mit der jemand etwas anfangen kann."""
    t = str(e)
    if "self signed" in t or "self-signed" in t:
        return "selbst ausgestelltes Zertifikat"
    if "unable to get local issuer" in t:
        return "Aussteller unbekannt (keine bekannte Zertifizierungsstelle)"
    if "certificate has expired" in t or "expired" in t:
        return "Zertifikat ist abgelaufen"
    if "not yet valid" in t:
        return "Zertifikat ist noch nicht gueltig"
    if "Hostname mismatch" in t or "doesn't match" in t:
        return "der Name im Zertifikat passt nicht zur Adresse"
    return t


def _details(der: bytes) -> dict:
    """Inhaber, Aussteller, Laufzeit, Namen – ueber ``cryptography``.

    Fehlt das Paket, gibt es Fingerabdruck und PEM trotzdem: eine
    Minimalauskunft ist besser als ein Fehler, und der Fingerabdruck allein
    genuegt fuer die bewusste Uebernahme.
    """
    leer = {"inhaber": "", "aussteller": "", "gueltig_von": "", "gueltig_bis": "",
            "namen": [], "selbstsigniert": None, "details_da": False}
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID, NameOID
    except Exception:  # noqa: BLE001
        return leer
    try:
        zert = x509.load_der_x509_certificate(der)
    except Exception:  # noqa: BLE001
        return leer

    def _cn(name) -> str:
        try:
            werte = name.get_attributes_for_oid(NameOID.COMMON_NAME)
            if werte:
                return str(werte[0].value)
        except Exception:  # noqa: BLE001
            pass
        try:
            return name.rfc4514_string()
        except Exception:  # noqa: BLE001
            return ""

    namen: list[str] = []
    try:
        san = zert.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        namen = [str(w) for w in san.get_values_for_type(x509.DNSName)]
        namen += [str(w) for w in san.get_values_for_type(x509.IPAddress)]
    except Exception:  # noqa: BLE001
        pass
    inhaber = _cn(zert.subject)
    if not namen and inhaber:
        namen = [inhaber]

    def _zeit(attr_neu: str, attr_alt: str) -> str:
        # not_valid_before_utc gibt es erst ab cryptography 42; der alte Name
        # ist ab 45 entfernt. Beide Wege, damit es auf jedem Server laeuft.
        for a in (attr_neu, attr_alt):
            try:
                w = getattr(zert, a, None)
                if w is not None:
                    return w.strftime("%Y-%m-%d %H:%M UTC")
            except Exception:  # noqa: BLE001
                continue
        return ""

    return {
        "inhaber": inhaber,
        "aussteller": _cn(zert.issuer),
        "gueltig_von": _zeit("not_valid_before_utc", "not_valid_before"),
        "gueltig_bis": _zeit("not_valid_after_utc", "not_valid_after"),
        "namen": namen,
        "selbstsigniert": zert.subject == zert.issuer,
        "details_da": True,
    }


def fingerabdruck(der: bytes) -> str:
    return "sha256:" + hashlib.sha256(der).hexdigest()


def _system_kontext(kanal: str) -> tuple[ssl.SSLContext, str]:
    """Vertrauensspeicher, den der jeweilige Kanal WIRKLICH benutzt.

    ⚠ DAS IST NICHT DASSELBE, und der Unterschied hat auf DEV zugeschlagen:
    ``ssl.create_default_context()`` nimmt den OpenSSL-Systemspeicher
    (``/etc/ssl/certs``), ``requests`` dagegen das Buendel von **certifi**. Auf
    einem Server, dessen Administrator eine interne CA ins System gelegt hat,
    sagt der Systemspeicher "vertrauenswuerdig", waehrend genau dieselbe
    Verbindung ueber ``requests`` mit ``SSLError`` scheitert. Wer hier den
    Systemspeicher misst, meldet dem Administrator "nichts zu tun" – und die
    SAP-Verbindung geht trotzdem nicht.

    Deshalb je Kanal die echte Quelle:
      * odata -> was ``requests.get(..., verify=True)`` nimmt (inkl. der
        Umgebungsvariablen, die requests selbst auswertet)
      * hana  -> hdbcli laeuft ueber OpenSSL, also der Systemspeicher
    """
    if kanal == "odata":
        pfad = (os.environ.get("REQUESTS_CA_BUNDLE")
                or os.environ.get("CURL_CA_BUNDLE"))
        if not pfad:
            try:
                import requests.certs
                pfad = requests.certs.where()
            except Exception:  # noqa: BLE001
                pfad = ""
        if pfad and Path(pfad).exists():
            return ssl.create_default_context(cafile=pfad), pfad
    return ssl.create_default_context(), "Systemspeicher"


def pruefen(host: str, port: int, kanal: str = "odata") -> dict:
    """Zertifikat holen und beurteilen. Wirft ``ZertFehler``, wenn schon der
    Handshake ohne Pruefung scheitert (Server nicht erreichbar, kein TLS).

    ``system_ok``  – die gewoehnliche Pruefung DIESES KANALS besteht bereits;
                     dann ist ein Anker ueberfluessig und der Knopf bleibt weg.
                     Gemessen gegen den Vertrauensspeicher, den der Kanal
                     tatsaechlich benutzt (siehe ``_system_kontext``).
    ``pin_ok``     – mit diesem Zertifikat als einzigem Anker kommt eine
                     vollstaendige Pruefung (inkl. Namensabgleich) zustande.
                     GEMESSEN, siehe Modul-Docstring.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        der = _der_holen(host, port, ctx)
    except OSError as e:
        raise ZertFehler("Server %s:%d nicht erreichbar: %s" % (host, port, e)) from None
    except ssl.SSLError as e:
        raise ZertFehler("Kein TLS auf %s:%d (%s)" % (host, port, e)) from None
    if not der:
        raise ZertFehler("Der Server hat kein Zertifikat vorgelegt.")

    pem = ssl.DER_cert_to_PEM_cert(der)
    fp = fingerabdruck(der)

    sys_ctx, sys_quelle = _system_kontext(kanal)
    system_ok, system_grund = _handshake_ok(host, port, sys_ctx)

    pin_ok, pin_grund = True, ""
    if not system_ok:
        try:
            anker = ssl.create_default_context(cadata=pem)
        except Exception as e:  # noqa: BLE001
            pin_ok, pin_grund = False, "Zertifikat nicht als Anker verwendbar: %s" % e
        else:
            pin_ok, pin_grund = _handshake_ok(host, port, anker)

    erg = {"host": host, "port": port, "kanal": kanal, "fingerprint": fp, "pem": pem,
           "system_ok": system_ok, "system_grund": system_grund,
           "system_quelle": sys_quelle,
           "pin_ok": pin_ok, "pin_grund": pin_grund}
    erg.update(_details(der))
    return erg


# ── Eintrag: was gespeichert wird ───────────────────────────────────────────

def eintrag_bauen(erg: dict) -> dict:
    """Der zu speichernde Anker. Enthaelt Host UND Port – ohne die liesse sich
    nach einem Adresswechsel nicht erkennen, dass der Anker zu einem anderen
    Server gehoert, und er wuerde still weitergeschleppt."""
    return {
        "host": erg["host"], "port": int(erg["port"]),
        "fingerprint": erg["fingerprint"], "pem": erg["pem"],
        "inhaber": erg.get("inhaber", ""), "aussteller": erg.get("aussteller", ""),
        "gueltig_bis": erg.get("gueltig_bis", ""),
        # Nur HANA kann einen abweichenden Namen ueberbruecken
        # (sslHostNameInCertificate); fuer OData ist das eine Information fuer
        # die Anzeige, kein Schalter.
        "name_abweichung": (not erg.get("pin_ok", True)),
        "gebunden_am": int(time.time()),
    }


def passt(eintrag: dict | None, host: str, port: int) -> bool:
    """Gilt dieser Anker fuer dieses Ziel? Vergleich ohne Gross/Klein."""
    if not isinstance(eintrag, dict) or not eintrag.get("pem"):
        return False
    try:
        return (str(eintrag.get("host") or "").strip().lower() == (host or "").strip().lower()
                and int(eintrag.get("port") or 0) == int(port))
    except (TypeError, ValueError):
        return False


def info(eintrag: dict | None) -> dict:
    """Was die Oberflaeche ueber einen gespeicherten Anker erfaehrt – **ohne PEM**.
    Das Zertifikat selbst ist zwar oeffentlich, gehoert aber nicht in jede
    Antwort; die Anzeige braucht den Fingerabdruck."""
    if not isinstance(eintrag, dict) or not eintrag.get("pem"):
        return {}
    return {k: eintrag.get(k, "") for k in
            ("host", "port", "fingerprint", "inhaber", "aussteller",
             "gueltig_bis", "name_abweichung", "gebunden_am")}


# ── Buendel-Datei fuer requests ─────────────────────────────────────────────

_FP_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PEM_RE = re.compile(
    r"^-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----\s*$")


def bundle_pfad(pem: str, fp: str = "") -> str:
    """Schreibt das Zertifikat als CA-Buendel und gibt den Pfad zurueck.

    Idempotent: gleicher Inhalt -> gleiche Datei. Der Name kommt aus dem Hash
    des Inhalts, nicht aus Host oder Fingerabdruck-Feld: so kann ein
    manipulierter Datensatz nicht auf eine fremde Datei zeigen.
    """
    pem = (pem or "").strip()
    if not _PEM_RE.match(pem + "\n"):
        raise ZertFehler("Kein gueltiges Zertifikat (PEM) im Anker.")
    name = hashlib.sha256(pem.encode("ascii", "ignore")).hexdigest()[:16] + ".pem"
    ziel = CERT_DIR / name
    if ziel.exists():
        return str(ziel)
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CERT_DIR, DIR_MODUS)
    except OSError:
        pass
    tmp = ziel.with_suffix(".tmp")
    tmp.write_text(pem + "\n", encoding="ascii")
    try:
        os.chmod(tmp, DATEI_MODUS)
    except OSError:
        pass
    os.replace(tmp, ziel)     # atomar: nie eine halbe Vertrauenskette
    return str(ziel)


def verify_fuer(cfg: dict, feld: str, host: str, port: int):
    """Was ``requests`` als ``verify`` bekommt.

    Reihenfolge ist Absicht: **ein passender Anker gewinnt gegen einen
    abgeschalteten Haken.** Verankern ist strenger als der System-Speicher, und
    ein Anker, der nur bei eingeschalteter Pruefung wirkt, waere ein stiller
    No-op – genau das Muster, das dieses Projekt mehrfach teuer bezahlt hat.
    Passt der Anker nicht zum Ziel, gilt unveraendert ``verify_ssl``.
    """
    eintrag = cfg.get(feld)
    if passt(eintrag, host, port):
        try:
            return bundle_pfad(eintrag.get("pem", ""))
        except Exception as e:  # noqa: BLE001
            # Fail-CLOSED: ein unlesbarer Anker darf nicht stillschweigend zu
            # "gar keine Pruefung" werden.
            print(f"[SAP] Anker fuer {host}:{port} unbrauchbar ({e}) – "
                  f"es gilt die normale Pruefung", flush=True)
            return True
    return bool(cfg.get("verify_ssl", True))


def fingerabdruck_gueltig(fp: str) -> bool:
    return bool(_FP_RE.match((fp or "").strip().lower()))


def bestaetigen(host: str, port: int, fingerprint: str, kanal: str = "odata") -> dict:
    """Zertifikat erneut holen und gegen den vom Menschen gesehenen Fingerabdruck
    pruefen; Rueckgabe ist der fertige Eintrag.

    **Das PEM kommt NIE aus dem Request.** Sonst waere der Endpunkt ein Weg,
    einen beliebigen Vertrauensanker einzuschleusen – der Benutzer bestaetigt
    nur, was er gesehen hat. Vergleich mit ``compare_digest``.
    """
    if not fingerabdruck_gueltig(fingerprint):
        raise ZertFehler("Kein gueltiger Fingerabdruck uebergeben.")
    erg = pruefen(host, port, kanal)
    if not hmac.compare_digest(erg["fingerprint"], fingerprint.strip().lower()):
        raise ZertFehler(
            "Das Zertifikat hat sich seit der Anzeige geaendert.\n"
            "bestaetigt: %s\ngefunden:   %s\n"
            "Bitte erneut pruefen und den neuen Fingerabdruck ansehen."
            % (fingerprint.strip().lower(), erg["fingerprint"]))
    return eintrag_bauen(erg)
