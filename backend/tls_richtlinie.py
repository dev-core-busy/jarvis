"""TLS-Richtlinie des HTTPS-Servers (Port 443) nach BSI TR-02102-2.

**Befund H6 (BSI-Abgleich 2026-09-29):** uvicorn setzt ohne ``--ssl-ciphers``
den OpenSSL-Ausdruck ``TLSv1`` – das ist KEINE Protokollversion, sondern die
Menge der Suites, die es schon in SSLv3/TLS 1.0 gab. Unter TLS 1.2 blieben
damit genau ``ECDHE-RSA-AES128-SHA`` und ``ECDHE-RSA-AES256-SHA`` uebrig
(CBC mit SHA-1-MAC; auf DEV gemessen 2026-10-04). TLS 1.3 war nicht betroffen.

Erlaubt sind jetzt nur ECDHE-Suites (Forward Secrecy) mit AES-GCM bzw. AES-CBC
mit SHA-2-MAC – alle aus TR-02102-2, Tabelle fuer TLS 1.2. GCM steht vorn; die
CBC-SHA2-Suites sind der Rueckweg fuer aeltere Windows-Clients. Die ECDSA-Suites
greifen erst mit einem EC-Zertifikat und schaden mit RSA nicht.

Nebenwirkung, gewollt: jede dieser Suites setzt TLS 1.2 voraus. Ein TLS-1.0/1.1-
Handshake findet damit keine gemeinsame Suite – unabhaengig davon, welche
Mindestversion die OpenSSL-Konfiguration des Systems vorgibt.

EINE Quelle: ``start_jarvis.sh`` und ``docker/entrypoint.sh`` tragen denselben
Ausdruck als Text (eine Shell kann ihn nicht importieren);
``tests/test_bsi_tls.py`` prueft die Gleichheit an allen Startstellen.

**TLS 1.3 (Rest aus H6, gemessen 2026-10-13 auf DEV und ECHT):** angeboten
wurde auch ``TLS_CHACHA20_POLY1305_SHA256`` – nicht in der TR-02102-2-Liste.
``--ssl-ciphers`` wirkt nur bis TLS 1.2, und Pythons ``ssl`` hat fuer die
TLS-1.3-Suiten KEINE Schnittstelle. Der einzige Weg ist die OpenSSL-
Konfiguration: ``backend/openssl_tls.cnf`` bindet die Systemdatei ein und
setzt nur ``Ciphersuites``. Jede Startstelle setzt ``OPENSSL_CONF`` darauf
(Shell: ``export``; Python: ``konfig_fuer_start``).

Die Variable gilt prozessweit, also auch fuer AUSGEHENDE Verbindungen – dort
harmlos, jeder TLS-1.3-Server muss TLS_AES_128_GCM_SHA256 koennen (RFC 8446
9.1). Damit sie NICHT in Kindprozesse wandert (Shell-Werkzeug, Sandbox: ein
anderer Benutzer kann die Datei evtl. nicht lesen), entfernt
``konfig_uebernehmen`` sie beim Import von ``backend.main`` wieder – OpenSSL
hat die Konfiguration zu diesem Zeitpunkt schon geladen (uvicorn baut den
TLS-Kontext vor dem Import der App), und sie bleibt fuer den Prozess wirksam.
"""
import os
import ssl
from pathlib import Path


TLS12_SUITES = (
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA384:"
    "ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA256"
)

TLS13_SUITES = "TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256"

OPENSSL_KONFIG = Path(__file__).resolve().with_name("openssl_tls.cnf")
SYSTEM_KONFIG = Path("/etc/ssl/openssl.cnf")


def konfig_fuer_start(env=None) -> bool:
    """Python-Startstellen: ``OPENSSL_CONF`` setzen, BEVOR uvicorn den
    TLS-Kontext baut (bei ``reload=True`` erben die Worker die Umgebung).
    Fehlt die Systemdatei, die ``openssl_tls.cnf`` einbindet, bleibt alles
    beim Alten – eine kaputte OpenSSL-Konfiguration waere schlimmer."""
    env = os.environ if env is None else env
    if not (OPENSSL_KONFIG.is_file() and SYSTEM_KONFIG.is_file()):
        return False
    env["OPENSSL_CONF"] = str(OPENSSL_KONFIG)
    return True


def konfig_uebernehmen() -> bool:
    """Beim Import von ``backend.main``: die Konfiguration ist geladen –
    ``OPENSSL_CONF`` aus der Umgebung nehmen, damit Kindprozesse sie nicht
    erben. Rueckgabe: TLS 1.3 ist auf die TR-Suiten beschraenkt."""
    if os.environ.get("OPENSSL_CONF") == str(OPENSSL_KONFIG):
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)    # Laden erzwingen, falls noch nicht
        os.environ.pop("OPENSSL_CONF", None)
    erlaubt = set(TLS13_SUITES.split(":"))
    t13 = {c["name"] for c in ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).get_ciphers()
           if c.get("protocol") == "TLSv1.3"}
    return bool(t13) and t13 <= erlaubt
