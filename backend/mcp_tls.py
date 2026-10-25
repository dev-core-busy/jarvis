"""Eigenes CA-Zertifikat je MCP-Server – die Pruefung bleibt AN.

WARUM ES DIESES MODUL GIBT
--------------------------
Gemeldet am 2026-10-24: ein MCP-Server mit selbstsigniertem Zertifikat laesst
sich nicht einbinden, und "ich kann keine Zertifikat Pruefung oder
'akzeptieren' feststellen". Gemessen stimmte das in jeder Schicht – weder
``mcp_client`` noch die Maske kannten ein Feld dafuer, und
``_connect_streamable_http`` rief ``streamablehttp_client(url=url)`` ohne jede
TLS-Angabe. Der Haken der Bibliothek (``httpx_client_factory``) war ungenutzt.

DIE ENTSCHEIDUNG (Betreiber, 2026-10-24): **die Pruefung bleibt an.** Es wird
NICHT abschaltbar, sondern es laesst sich ein eigenes CA-Zertifikat
hinterlegen. Der Unterschied ist nicht kosmetisch: ``verify=False`` nimmt jedes
Zertifikat an, auch das eines Fremden auf dem Weg – ein hinterlegtes CA-Zert
vertraut genau EINEM Aussteller. Der Preis ist ein Feld mehr in der Maske; der
Gewinn ist, dass die Verbindung weiterhin beweist, mit wem sie spricht.

EIN FELD, ZWEI FORMEN
---------------------
``ca_cert`` nimmt beides:

* **PEM-Inhalt** (beginnt mit ``-----BEGIN``) – der Regelweg fuer die Maske:
  der Admin kopiert das Zertifikat hinein, es landet in der settings.json und
  es muss keine Datei auf dem Server liegen. Gelesen wird es ueber
  ``SSLContext.load_verify_locations(cadata=...)``, also OHNE Umweg ueber eine
  temporaere Datei – eine Datei waere eine zweite Stelle, an der etwas
  liegenbleibt, und im ``/tmp`` eines Dienstes ohnehin die schlechtere Wahl.
* **Pfad** – fuer Haeuser, die ihr CA-Bundle ohnehin ausrollen
  (``/usr/local/share/ca-certificates/...``). Dann bleibt die
  settings.json frei von Zertifikatsmaterial.

⚠ EIN PFAD IST EINE LESEANWEISUNG AN DEN DIENST, und der laeuft als
Dienstbenutzer. Deshalb wird er gegen ``sandbox.is_sensitive`` geprueft: ohne
das waere "CA-Datei" ein Feld, mit dem ein Administrator den Dienst dazu
bringt, ``.secret_key`` oder ``data/settings.json`` zu lesen – und der
Fehlertext ("kein Zertifikat in …") traegt bei einem Parse-Fehler Teile des
Inhalts nach draussen. Ein Administrator darf viel, aber ein Feld, das
beilaeufig zum Dateileser wird, ist kein gewollter Weg.

Dieses Modul importiert weder ``mcp`` noch ``httpx`` – pruefbar ohne beide
(``tests/test_mcp_tls.py``).
"""

from __future__ import annotations

import os
import ssl
from pathlib import Path


class CaFehler(Exception):
    """Das hinterlegte Zertifikat ist nicht verwendbar.

    Die Meldung nennt den Grund UND den naechsten Schritt – ein "ungueltig"
    allein laesst den Administrator raten, ob er die falsche Datei, das falsche
    Format oder einen Tippfehler im Pfad hat.
    """


# Ein PEM-Block faengt so an. Alles andere gilt als Pfad – diese Weiche ist die
# ganze Unterscheidung, deshalb steht sie an EINER Stelle und wird nicht an
# jedem Aufrufer wiederholt.
PEM_ANFANG = "-----BEGIN"


def ist_pem(wert: str) -> bool:
    """Ist ``wert`` ein PEM-Block (statt eines Pfades)?"""
    return str(wert or "").lstrip().startswith(PEM_ANFANG)


def _ist_tabu(rp: Path) -> tuple[bool, str]:
    """``(gesperrt, grund)`` fuer einen Pfad, der als Zertifikat gelesen wird.

    ⚠ AUSDRUECKLICH NICHT ``sandbox.is_sensitive`` – und der Grund ist wichtig,
    damit niemand es "vereinfacht": jene Funktion fuehrt ``.crt``, ``.pem`` und
    ``.cer`` in ``_SECRET_SUFFIX`` und ``certs`` in ``_SECRET_DIRPARTS``. Fuer
    ihren Zweck ist das genau richtig (ein Domain-Benutzer soll ueber kein
    Werkzeug an Schluesselmaterial kommen) – hier waere es das Ende der
    Funktion: JEDE Zertifikatsdatei waere gesperrt, auch
    ``/etc/ssl/certs/ca-certificates.crt``. Beim ersten Waechterlauf genau so
    gemessen, sechs von sechs Probepfaden abgewiesen.

    Gesperrt wird deshalb, was dieses Feld NICHT werden darf: ein Leser fuer
    die Geheimnisse des Dienstes. Die Listen kommen aus ``sandbox`` und werden
    NICHT abgeschrieben – eine zweite Kopie derselben Liste ist die Zeitbombe,
    die das Register an sechs Stellen fuehrt.

    Erlaubt bleiben die Zertifikats-FORMATE (``.pem``/``.crt``/``.cer`` und
    endungslose Dateien). Schluessel-Formate sind gesperrt: ein ``.key`` oder
    ``.p12`` ist kein CA-Zertifikat, und wer eines eintraegt, hat sich
    vergriffen – ihn darauf hinzuweisen ist besser, als es zu lesen.
    """
    from backend import sandbox

    name = rp.name.lower()
    s = str(rp)
    if name in sandbox._SECRET_NAMES or name.startswith(".env"):
        return True, "das ist eine Geheimnis-Datei dieses Dienstes"
    # Schluesselmaterial: NICHT die Zertifikatsformate, nur die Schluessel.
    schluessel = {".key", ".p12", ".pfx", ".jks", ".keystore", ".keytab"}
    if rp.suffix.lower() in schluessel:
        return True, ("'%s' ist ein Schluessel-Format, kein CA-Zertifikat "
                      "(erwartet wird PEM: .pem, .crt, .cer)" % rp.suffix)
    if {p.lower() for p in rp.parts} & {".ssh", ".git"}:
        return True, "der Pfad fuehrt durch .ssh oder .git"
    if s == "/root" or s.startswith(sandbox._SYSTEM_DENY_PREFIX):
        return True, "der Ort ist fuer diesen Dienst gesperrt"
    for rel in sandbox._APP_DENY_REL:
        basis = str(sandbox.PROJECT_ROOT / rel)
        if s == basis or s.startswith(basis + os.sep):
            return True, "das ist ein interner Pfad der Anwendung"
    return False, ""


def _pfad_pruefen(roh: str) -> Path:
    p = Path(str(roh).strip()).expanduser()
    if not p.is_absolute():
        raise CaFehler(
            "Der Pfad zum CA-Zertifikat muss absolut sein (z. B. "
            "/usr/local/share/ca-certificates/firma.crt) – '%s' ist relativ "
            "und haengt damit vom Arbeitsverzeichnis des Dienstes ab." % roh)
    try:
        aufgeloest = p.resolve()
    except OSError as e:
        raise CaFehler("Der Pfad '%s' ist nicht auflösbar: %s" % (roh, e)) from e
    # ⚠ Symlinks und ".." sind VOR der Pruefung aufgeloest – sonst entscheidet
    # die Pruefung ueber einen anderen Pfad als das Lesen (Register).
    try:
        geschuetzt, grund = _ist_tabu(aufgeloest)
    except Exception:  # noqa: BLE001
        # Fail-closed: laesst sich die Schranke nicht befragen, wird nicht
        # gelesen. "Unbekannt heisst nicht erlaubt."
        raise CaFehler(
            "Die Schutzpruefung fuer '%s' konnte nicht ausgefuehrt werden – "
            "die Datei wird deshalb nicht gelesen." % roh) from None
    if geschuetzt:
        raise CaFehler(
            "'%s' wird nicht als Zertifikat gelesen: %s. Hinterlege das "
            "CA-Zertifikat als eigene Datei oder trage seinen PEM-Inhalt in "
            "das Feld ein." % (roh, grund))
    if not aufgeloest.is_file():
        raise CaFehler(
            "Die Datei '%s' gibt es nicht (oder sie ist für den Dienstbenutzer "
            "nicht lesbar). Pfad pruefen, oder den PEM-Inhalt direkt in das "
            "Feld eintragen." % roh)
    return aufgeloest


def ssl_kontext(ca_cert: str | None) -> "ssl.SSLContext | None":
    """SSL-Kontext, der ZUSAETZLICH ``ca_cert`` vertraut – oder ``None``.

    ``None`` heisst "nichts hinterlegt, nimm die Vorgabe des Systems" und ist
    der Normalfall. Der zurueckgegebene Kontext hat ``check_hostname`` an und
    ``verify_mode = CERT_REQUIRED`` – ausdruecklich gesetzt und nicht geerbt,
    damit ein kuenftiger Umbau an ``create_default_context`` die Zusage dieses
    Moduls nicht still aushebelt.

    Die System-CAs bleiben geladen (``load_default_certs``): ein hinterlegtes
    Firmen-Zert soll den oeffentlichen Satz ERGAENZEN, nicht ersetzen – sonst
    bricht derselbe Server, sobald er auf ein regulaeres Zertifikat wechselt.
    """
    roh = str(ca_cert or "").strip()
    if not roh:
        return None

    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED

    if ist_pem(roh):
        try:
            ctx.load_verify_locations(cadata=roh)
        except ssl.SSLError as e:
            raise CaFehler(
                "Der eingetragene PEM-Block ist kein lesbares Zertifikat (%s). "
                "Erwartet wird der Text zwischen BEGIN/END CERTIFICATE, "
                "einschliesslich dieser Zeilen." % e) from e
        except Exception as e:  # noqa: BLE001
            raise CaFehler("Der PEM-Block konnte nicht geladen werden: %s" % e) from e
        return ctx

    datei = _pfad_pruefen(roh)
    try:
        ctx.load_verify_locations(cafile=str(datei))
    except ssl.SSLError as e:
        raise CaFehler(
            "'%s' enthaelt kein lesbares CA-Zertifikat (%s). Erwartet wird eine "
            "PEM-Datei (BEGIN CERTIFICATE); eine DER-Datei muss erst "
            "umgewandelt werden." % (roh, e)) from e
    except OSError as e:
        raise CaFehler("'%s' ist nicht lesbar: %s" % (roh, e)) from e
    return ctx


# ── Ansehen, pruefen, erlauben ──────────────────────────────────────────────
#
# ⚠ DER FINGERABDRUCK IST DER GANZE SINN DIESES WEGES. Das Zertifikat wird
# OHNE Pruefung abgeholt – anders kommt man an das eines unbekannten Ausstellers
# nicht heran – und genau deshalb ist das Abholen allein KEIN Vertrauensbeweis:
# wer auf dem Weg sitzt, zeigt sein eigenes. Was den Weg sicher macht, ist der
# Mensch dazwischen: er vergleicht den angezeigten SHA-256-Abdruck mit dem, den
# der Server-Betreiber nennt, und erst sein Klick schreibt das Zertifikat in die
# Konfiguration. Danach laeuft jede Verbindung MIT Pruefung gegen genau dieses
# Zertifikat.
#
# Deshalb liefert `zertifikat_abholen` nie ein "ist in Ordnung", sondern immer
# die Befunde dazu – und die Oberflaeche zeigt den Abdruck prominent. Ein
# Dialog, der nur "Zertifikat akzeptieren?" fragt, ist ein Klick ohne
# Information und waere `verify=False` mit mehr Schritten.

ABHOL_FRIST_S = 8.0


def _san_liste(cert) -> list:
    """DNS-Namen aus der SubjectAlternativeName-Erweiterung (oder leer)."""
    try:
        from cryptography import x509
        erw = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value
        return [str(n) for n in erw.get_values_for_type(x509.DNSName)]
    except Exception:  # noqa: BLE001
        # Ein Zertifikat OHNE SAN ist heute ungueltig, aber das ist ein BEFUND
        # (unten) und kein Grund, die Anzeige scheitern zu lassen.
        return []


def _namen(feld) -> str:
    """``CN=…, O=…`` lesbar machen – ohne Abhaengigkeit von der Feldreihenfolge."""
    try:
        return ", ".join("%s=%s" % (a.rfc4514_attribute_name, a.value)
                         for a in feld)
    except Exception:  # noqa: BLE001
        return str(feld)


def host_und_port(url: str) -> tuple[str, int]:
    """``(host, port)`` aus einer https-Adresse. Wirft ``CaFehler``.

    Nur ``https`` – bei ``http`` gibt es kein Zertifikat, und eine Anzeige
    "kein Zertifikat gefunden" waere dort eine Falschaussage ueber den Server.
    """
    from urllib.parse import urlsplit
    teile = urlsplit(str(url or "").strip())
    if teile.scheme != "https":
        raise CaFehler(
            "Zertifikate gibt es nur bei https – diese Adresse benutzt '%s'. "
            "Ohne TLS ist nichts zu pruefen und nichts zu erlauben."
            % (teile.scheme or "(kein Schema)"))
    if not teile.hostname:
        raise CaFehler("In der Adresse '%s' steht kein Hostname." % url)
    return teile.hostname, int(teile.port or 443)


def zertifikat_abholen(url: str, frist: float = ABHOL_FRIST_S) -> dict:
    """Das Zertifikat des Servers holen und BEWERTEN – ohne ihm zu vertrauen.

    Rueckgabe::

        {"host", "port", "pem", "fingerprint_sha256", "subject", "issuer",
         "gueltig_von", "gueltig_bis", "dns_namen", "selbstsigniert": bool,
         "befunde": [str, …], "vertraut_system": bool}

    ``befunde`` ist die Liste der Gruende, aus denen die Regelpruefung
    fehlschlaegt (selbstsigniert, abgelaufen, Hostname passt nicht, kein SAN).
    Eine LEERE Liste heisst: das Zertifikat haette auch ohne Hinterlegen
    gereicht – dann ist das Erlauben unnoetig, und die Oberflaeche sagt das.

    ``vertraut_system`` ist das Ergebnis eines ZWEITEN Verbindungsversuchs, der
    regulaer prueft. Beides getrennt zu messen ist der Punkt: "ich konnte es
    abholen" und "es ist vertrauenswuerdig" sind verschiedene Aussagen, und sie
    zusammenzuwerfen war der Fehler, aus dem dieser ganze Weg entstanden ist.

    BLOCKIEREND (Netz) – im Thread rufen.
    """
    import socket

    host, port = host_und_port(url)

    # (1) Abholen OHNE Pruefung. Das ist kein Vertrauensvorschuss, sondern die
    # einzige Art, an ein unbekanntes Zertifikat zu kommen; benutzt wird es
    # ausschliesslich zur ANZEIGE.
    roh = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    roh.check_hostname = False
    roh.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=frist) as s:
            with roh.wrap_socket(s, server_hostname=host) as ts:
                der = ts.getpeercert(binary_form=True)
    except OSError as e:
        raise CaFehler(
            "Der Server %s:%d ist nicht erreichbar (%s). Ohne Verbindung laesst "
            "sich kein Zertifikat ansehen." % (host, port, e)) from e
    if not der:
        raise CaFehler("%s:%d hat kein Zertifikat vorgezeigt." % (host, port))

    pem = ssl.DER_cert_to_PEM_cert(der)
    aus = {"host": host, "port": port, "pem": pem}

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    cert = x509.load_der_x509_certificate(der)
    aus["fingerprint_sha256"] = ":".join(
        "%02X" % b for b in cert.fingerprint(hashes.SHA256()))
    aus["subject"] = _namen(cert.subject)
    aus["issuer"] = _namen(cert.issuer)
    # UTC-Varianten: die alten Eigenschaften sind in cryptography 42+ verwarnt,
    # und eine Verwarnung je Aufruf entwertet das Journal.
    von = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before
    bis = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
    aus["gueltig_von"] = von.isoformat()
    aus["gueltig_bis"] = bis.isoformat()
    aus["dns_namen"] = _san_liste(cert)
    aus["selbstsigniert"] = cert.subject == cert.issuer

    befunde = []
    if aus["selbstsigniert"]:
        befunde.append("selbstsigniert (kein Aussteller, dem das System traut)")
    import datetime as _dt
    jetzt = _dt.datetime.now(_dt.timezone.utc)
    if von.tzinfo is None:
        von = von.replace(tzinfo=_dt.timezone.utc)
    if bis.tzinfo is None:
        bis = bis.replace(tzinfo=_dt.timezone.utc)
    if jetzt < von:
        befunde.append("noch nicht gueltig (ab %s)" % von.isoformat())
    if jetzt > bis:
        befunde.append("abgelaufen (seit %s)" % bis.isoformat())
    if not aus["dns_namen"]:
        befunde.append("ohne SubjectAlternativeName – heutige Clients lehnen "
                       "das ab, auch mit hinterlegtem Zertifikat")
    elif not _host_passt(host, aus["dns_namen"]):
        befunde.append("gilt nicht fuer '%s', sondern fuer %s"
                       % (host, ", ".join(aus["dns_namen"])))
    aus["befunde"] = befunde

    # (2) Der zweite, REGULAERE Versuch: traut das System dem Zertifikat schon?
    # Wenn ja, ist Hinterlegen unnoetig – und das zu sagen verhindert, dass
    # jemand aus Gewohnheit ein Zertifikat festschreibt, das naechsten Monat
    # regulaer erneuert wird und dann nicht mehr passt.
    pruef = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=frist) as s:
            with pruef.wrap_socket(s, server_hostname=host):
                aus["vertraut_system"] = True
    except Exception:  # noqa: BLE001
        aus["vertraut_system"] = False
    return aus


def _host_passt(host: str, namen: list) -> bool:
    """Wildcard-Vergleich wie TLS ihn macht (eine Ebene, nur ganz links)."""
    h = str(host or "").lower().rstrip(".")
    for n in namen:
        m = str(n or "").lower().rstrip(".")
        if m == h:
            return True
        if m.startswith("*."):
            # `*.a.de` deckt `b.a.de`, aber NICHT `a.de` und nicht `c.b.a.de`.
            rest = m[2:]
            if h.endswith("." + rest) and h.count(".") == m.count("."):
                return True
    return False


def passt_zum_gespeicherten(ca_cert: str | None, pem: str) -> bool:
    """Ist ``pem`` genau das, was unter ``ca_cert`` hinterlegt ist?

    Fuer die Oberflaeche: sie soll "dieses Zertifikat ist schon erlaubt" sagen
    koennen, ohne den PEM-Block anzuzeigen. Verglichen wird normiert
    (Leerraum/Zeilenenden), denn ein eingefuegter Block traegt oft andere
    Umbrueche als der abgeholte – ein Byte-Vergleich meldete sonst einen
    Unterschied, den es inhaltlich nicht gibt.
    """
    a, b = str(ca_cert or ""), str(pem or "")
    if not a or not b or not ist_pem(a):
        return False
    norm = lambda s: "".join(s.split())          # noqa: E731
    return norm(a) == norm(b)


def beschreibung(ca_cert: str | None) -> str:
    """Kurzform fuer Journal und Oberflaeche – NIE das Zertifikat selbst.

    Ein PEM-Block gehoert nicht in eine Logzeile: er ist lang, und im Journal
    sucht niemand danach. Der Pfad dagegen ist die Information, die ein
    Administrator braucht.
    """
    roh = str(ca_cert or "").strip()
    if not roh:
        return ""
    return "eigenes CA-Zertifikat (PEM-Block)" if ist_pem(roh) \
        else "eigenes CA-Zertifikat aus %s" % roh
