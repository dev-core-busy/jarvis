"""Serverzertifikat eines LLM-Endpunkts per Fingerabdruck verankern.

**Warum es das gibt:** Ein selbst betriebener LLM-Server (vLLM, Ollama hinter
einem Reverse-Proxy, ein Haus-Gateway) hat oft ein selbst ausgestelltes oder
intern signiertes Zertifikat. Bisher gab es dafuer keinen Weg: httpx prueft
gegen certifi, der Aufruf scheiterte mit ``CERTIFICATE_VERIFY_FAILED``, und die
einzige "Loesung" waere ``verify=False`` gewesen – also jede Antwort und jeder
API-Schluessel offen fuer einen Man-in-the-Middle.

**Verankern statt abschalten** – dasselbe Verfahren wie bei SAP, LDAP und der
Kundenverwaltung (``sap_cert``): genau EIN Zertifikat wird einziger
Vertrauensanker fuer Host:Port. Die Pruefung bleibt AN; ein spaeterer
Zertifikatswechsel bricht ab und muss bewusst uebernommen werden.

**Der Fingerabdruck kommt vom Menschen, das Zertifikat vom Server.** Das PEM
wird NIE aus einem Request angenommen: ``anker_bauen`` holt das Zertifikat
selbst und vergleicht es mit dem eingegebenen bzw. angezeigten Fingerabdruck
(``sap_cert.bestaetigen``). Der Fingerabdruck darf auch von Hand kommen (vom
Betreiber des LLM-Servers durchgegeben) – das ist der staerkere Weg, weil er
nicht ueber dieselbe Leitung laeuft, die er absichern soll.

**Zuordnung nach Host UND Port, exakt.** httpx-``mounts`` taugen dafuer nicht:
``https://h:443`` wird von httpx zu ``https://h`` normiert und passt dann auf
JEDEN Port (gemessen mit httpx 0.28.1: das Muster traf ``https://h:8443``).
Ein Anker fuer 443 haette einen anderen Dienst auf demselben Rechner mit dem
falschen Zertifikat geprueft. Deshalb ein eigener Transport, der nach
``(host, port)`` waehlt.

**Ohne Anker byte-gleich:** ``client_args()`` liefert dann ``{}``, die Clients
entstehen genau wie vorher.
"""

from __future__ import annotations

import re
import ssl
from urllib.parse import urlparse

import httpx

# Feld im Profil-Datensatz (Eintrag aus sap_cert.eintrag_bauen). Steht bewusst
# NICHT in der Whitelist von config.update_profile – gesetzt wird es nur ueber
# anker_bauen, sonst liesse sich per PUT ein beliebiger Anker einschleusen.
FELD = "cert"

# Kanal fuer sap_cert.pruefen: misst "braucht es ueberhaupt einen Anker?" gegen
# den Vertrauensspeicher, den httpx wirklich benutzt (certifi), nicht gegen den
# des Systems.
KANAL = "llm"


class AnkerFehler(RuntimeError):
    """Fingerabdruck unbrauchbar oder Zertifikat passt nicht."""


# ── Fingerabdruck normieren ─────────────────────────────────────────────────

_HEX = re.compile(r"^[0-9a-f]+$")


def fingerabdruck_normieren(roh: str) -> str:
    """Gaengige Schreibweisen auf ``sha256:<64 hex>`` bringen.

    Angenommen werden ``sha256:ab12…``, ``AB:12:…`` (Browser, Windows),
    ``SHA256 Fingerprint=AB:12:…`` (``openssl x509 -fingerprint``) und
    Hex mit Leerzeichen. SHA-1 (40 Stellen) wird ausdruecklich abgelehnt statt
    still als ungueltig gemeldet – genau diese Form zeigt Windows als
    "Fingerabdruck" zuerst an, und ohne den Hinweis sucht man den Fehler beim
    Abtippen.
    """
    s = str(roh or "").strip()
    if not s:
        raise AnkerFehler("Kein Fingerabdruck angegeben.")
    if "=" in s:
        s = s.split("=", 1)[1]
    s = s.strip().lower()
    if s.startswith("sha256:"):
        s = s[len("sha256:"):]
    elif s.startswith("sha-256:"):
        s = s[len("sha-256:"):]
    s = re.sub(r"[\s:\-]", "", s)
    if not _HEX.match(s):
        raise AnkerFehler("Der Fingerabdruck enthält Zeichen, die keine "
                          "Hexadezimalziffern sind.")
    if len(s) == 40:
        raise AnkerFehler("Das ist ein SHA-1-Fingerabdruck (40 Stellen). Benötigt "
                          "wird SHA-256 (64 Stellen).")
    if len(s) != 64:
        raise AnkerFehler("Ein SHA-256-Fingerabdruck hat 64 Hexadezimalstellen, "
                          "angegeben waren %d." % len(s))
    return "sha256:" + s


# ── Ziel aus der Profil-Adresse ─────────────────────────────────────────────

def ziel(api_url: str) -> tuple[str, int]:
    """``(host, port)`` einer https-Adresse. Wirft ``AnkerFehler`` bei http."""
    roh = str(api_url or "").strip()
    if not roh:
        raise AnkerFehler("Keine API-Adresse angegeben.")
    if "://" not in roh:
        roh = "https://" + roh
    teile = urlparse(roh)
    if teile.scheme != "https":
        raise AnkerFehler("Die Adresse ist kein HTTPS – ohne TLS gibt es kein "
                          "Serverzertifikat zu prüfen.")
    if not teile.hostname:
        raise AnkerFehler("Aus der Adresse lässt sich kein Servername lesen.")
    try:
        port = int(teile.port or 443)
    except ValueError:
        raise AnkerFehler("Der Port in der Adresse ist keine Zahl.") from None
    return teile.hostname.lower(), port


# ── Anker bauen, pruefen, anwenden ──────────────────────────────────────────

def kontext(eintrag: dict) -> ssl.SSLContext:
    """TLS-Kontext mit GENAU diesem Zertifikat als Anker.

    ``check_hostname`` nur aus, wenn beim Verankern gemessen wurde, dass der
    Name nicht passt (IP statt FQDN in der Adresse) – akzeptiert wird dann
    trotzdem nur das gebundene Zertifikat (``verify_mode`` bleibt
    ``CERT_REQUIRED``). Gleiche Regel wie ``kundenverwaltung_client``.
    """
    ctx = ssl.create_default_context(cadata=eintrag["pem"])
    if eintrag.get("name_abweichung"):
        ctx.check_hostname = False
    return ctx


def _handshake(host: str, port: int, ctx: ssl.SSLContext) -> str:
    """Leerer String bei Erfolg, sonst der Grund."""
    from backend import sap_cert
    ok, grund = sap_cert._handshake_ok(host, port, ctx)
    return "" if ok else (grund or "unbekannter Fehler")


def pruefen(api_url: str) -> dict:
    """Zertifikat des Ziels holen und beurteilen – fuer die Anzeige. Ohne PEM."""
    from backend import sap_cert
    host, port = ziel(api_url)
    try:
        erg = sap_cert.pruefen(host, port, KANAL)
    except sap_cert.ZertFehler as e:
        raise AnkerFehler(str(e)) from None
    erg.pop("pem", None)
    return erg


def anker_bauen(api_url: str, fingerabdruck: str) -> dict:
    """Zertifikat holen, mit dem Fingerabdruck vergleichen und die Bindung
    MESSEN, bevor sie gespeichert wird.

    Der letzte Schritt ist der entscheidende: ein Handshake mit genau dem
    Kontext, den der Betrieb spaeter benutzt. Ein Anker, der die Verbindung
    nicht traegt (abgelaufenes Zertifikat, falscher Schluesseltyp), wird
    abgelehnt – sonst stuende "verankert" im Profil, und der erste Chat
    scheiterte mit einem Zertifikatsfehler, den niemand mehr dem Anker zuordnet.
    """
    import hmac
    from backend import sap_cert
    fp = fingerabdruck_normieren(fingerabdruck)
    host, port = ziel(api_url)
    # Wie sap_cert.bestaetigen, aber mit eigener Meldung: dort heisst es "seit
    # der Anzeige geaendert" – hier kann der Abdruck auch von Hand kommen.
    try:
        erg = sap_cert.pruefen(host, port, KANAL)
    except sap_cert.ZertFehler as e:
        raise AnkerFehler(str(e)) from None
    if not hmac.compare_digest(erg["fingerprint"], fp):
        raise AnkerFehler("Der Server legt ein anderes Zertifikat vor, als der "
                          "Fingerabdruck beschreibt.\nerwartet: %s\ngefunden: %s"
                          % (fp, erg["fingerprint"]))
    eintrag = sap_cert.eintrag_bauen(erg)
    grund = _handshake(host, port, kontext(eintrag))
    if grund:
        raise AnkerFehler("Mit diesem Zertifikat als Anker kommt keine "
                          "Verbindung zustande (%s)." % grund)
    return eintrag


def passt(eintrag, api_url: str) -> bool:
    """Gilt der Anker fuer diese Adresse?"""
    from backend import sap_cert
    try:
        host, port = ziel(api_url)
    except AnkerFehler:
        return False
    return sap_cert.passt(eintrag, host, port)


def info(eintrag, api_url: str = "") -> dict:
    """Anzeige ohne PEM, dazu ``aktiv`` – passt der Anker zur Adresse?"""
    from backend import sap_cert
    aus = sap_cert.info(eintrag)
    if aus:
        aus["aktiv"] = passt(eintrag, api_url)
    return aus


# ── Transport ───────────────────────────────────────────────────────────────

def anker() -> dict[tuple[str, int], dict]:
    """Alle Anker aus den Profilen, je ``(host, port)`` der zuletzt gebundene.

    Ein Anker gilt fuer den SERVER, nicht nur fuer sein Profil: zwei Profile
    mit verschiedenen Modellen auf demselben Server sprechen dieselbe
    TLS-Gegenstelle an, und der gemeinsame Client weiss bei einem Aufruf nicht,
    zu welchem Profil er gehoert.
    """
    try:
        from backend.config import config
        profile = list(config.profiles or [])
    except Exception:  # noqa: BLE001
        return {}
    aus: dict[tuple[str, int], dict] = {}
    for p in profile:
        e = p.get(FELD) if isinstance(p, dict) else None
        if not isinstance(e, dict) or not e.get("pem"):
            continue
        try:
            schluessel = (str(e.get("host") or "").strip().lower(), int(e.get("port") or 0))
        except (TypeError, ValueError):
            continue
        alt = aus.get(schluessel)
        if alt is None or int(e.get("gebunden_am") or 0) >= int(alt.get("gebunden_am") or 0):
            aus[schluessel] = e
    return aus


def stand(zusatz: dict | None = None) -> tuple:
    """Vergleichbarer Abdruck der Anker – aendert er sich, wird der gemeinsame
    Client neu gebaut."""
    a = dict(anker())
    if zusatz:
        a.update(zusatz)
    return tuple(sorted((k, e.get("fingerprint"), bool(e.get("name_abweichung")))
                        for k, e in a.items()))


class AnkerTransport(httpx.AsyncBaseTransport):
    """Waehlt je Anfrage den Transport nach ``(host, port)``.

    Ziele ohne Anker laufen ueber einen gewoehnlichen Transport mit der
    Standardpruefung. Ein unbrauchbarer Anker faellt auf die Standardpruefung
    zurueck – NIE auf "gar keine Pruefung" (fail-closed).
    """

    def __init__(self, anker_je_ziel: dict[tuple[str, int], dict], **kw):
        self._standard = httpx.AsyncHTTPTransport(**kw)
        self._gebunden: dict[tuple[str, int], httpx.AsyncHTTPTransport] = {}
        for (host, port), e in anker_je_ziel.items():
            try:
                ctx = kontext(e)
            except Exception as ex:  # noqa: BLE001
                print(f"[LLM] Zertifikatsanker fuer {host}:{port} unbrauchbar ({ex}) – "
                      f"es gilt die normale Pruefung", flush=True)
                continue
            self._gebunden[(host, port)] = httpx.AsyncHTTPTransport(verify=ctx, **kw)

    def _waehlen(self, url: httpx.URL) -> httpx.AsyncHTTPTransport:
        if url.scheme == "https":
            t = self._gebunden.get(((url.host or "").lower(), url.port or 443))
            if t is not None:
                return t
        return self._standard

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._waehlen(request.url).handle_async_request(request)

    async def aclose(self) -> None:
        for t in [self._standard, *self._gebunden.values()]:
            try:
                await t.aclose()
            except Exception:  # noqa: BLE001
                pass


def client_args(zusatz: dict | None = None, **kw) -> dict:
    """Zusatzargumente fuer ``httpx.AsyncClient(...)``.

    ``zusatz``: Anker, die (noch) nicht gespeichert sind – fuer den
    Verbindungstest eines Formulars, dessen Fingerabdruck gerade erst
    eingegeben wurde. ``kw`` geht an jeden inneren Transport (z. B.
    ``limits``: bei gesetztem ``transport`` ignoriert httpx das ``limits`` des
    Clients). Ohne Anker ``{}`` – der Client entsteht wie bisher.
    """
    a = dict(anker())
    if zusatz:
        a.update(zusatz)
    if not a:
        return {}
    return {"transport": AnkerTransport(a, **kw)}


def zusatz_fuer(api_url: str, fingerabdruck: str) -> dict:
    """Ungespeicherten Anker fuer einen Formulartest bauen (holt das Zertifikat
    selbst, vergleicht den Fingerabdruck). Leer, wenn nichts anzuwenden ist."""
    if not str(fingerabdruck or "").strip():
        return {}
    e = anker_bauen(api_url, fingerabdruck)
    return {(e["host"].lower(), int(e["port"])): e}
