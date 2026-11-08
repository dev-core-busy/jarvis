"""SSRF-Schranke fuer Abrufe, die der SERVER im Auftrag eines Benutzers macht.

Eine Stelle fuer alle Wege, auf denen eine von aussen kommende Adresse auf dem
Server geholt wird (Web-Extraktor im Wissensbereich, Short Tracks, Bildsuche).
Bis 2026-11 hatte nur Short Tracks eine Pruefung; der Web-Extraktor folgte
Weiterleitungen blind (``follow_redirects=True``) und haette damit jede interne
Adresse geholt – ``http://127.0.0.1:<port>/`` oder die Cloud-Metadaten unter
``169.254.169.254``.

Was ``sicher_holen`` leistet:

* ALLE aufgeloesten Adressen eines Namens werden geprueft (ein Name kann auf
  mehrere zeigen; eine einzige interne genuegt zum Abweisen).
* Gesperrt: privat, loopback, link-local, multicast, reserviert, unspezifiziert,
  sowie die EIGENEN Adressen des Servers (sie sind oft nicht privat, zeigen
  aber ueber ``lo`` an der Firewall vorbei auf lokal lauschende Dienste).
* Weiterleitungen werden MANUELL verfolgt, jeder Sprung neu geprueft.
* Die Verbindung wird auf die GEPRUEFTE Adresse festgenagelt (gegen
  DNS-Rebinding: ein Name, der bei der Pruefung oeffentlich und beim Verbinden
  intern aufloest). Host-Kopfzeile und TLS-SNI/Zertifikatspruefung laufen
  weiter auf den Servernamen (``sni_hostname``).

⚠ GRENZE: ist fuer das Schema ein Proxy in der Umgebung gesetzt
(``HTTPS_PROXY`` …), loest der PROXY den Namen auf – festnageln geht dann
nicht (der Tunnel prueft das Zertifikat gegen den Verbindungsnamen). Die
Adresspruefung laeuft trotzdem; das Rebinding-Fenster bleibt in diesem Fall
offen. Ein Proxy ist auf den Jarvis-Servern nicht eingerichtet.

⚠ WAS DAS NICHT LEISTET: in einem Netz mit OEFFENTLICHEN Adressen sind andere
Server des Hauses per IP-Bereich nicht von fremden zu unterscheiden. Dafuer
braeuchte es eine Ziel-Whitelist (bewusst nicht gebaut).

Das Modul importiert ``backend.config`` nicht (Tests laden es direkt).
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.parse import urljoin, urlsplit

WEITERLEITUNGEN = (301, 302, 303, 307, 308)


class ZielFehler(ValueError):
    """Die Adresse darf (oder kann) nicht geholt werden. Text ist fuer Menschen."""


_eigene_cache: set[str] | None = None


def eigene_adressen() -> set[str]:
    """Adressen DIESES Servers – gecacht, fail-safe leer."""
    global _eigene_cache
    if _eigene_cache is not None:
        return _eigene_cache
    raus: set[str] = set()
    try:
        for inf in socket.getaddrinfo(socket.gethostname(), None):
            raus.add(inf[4][0].split("%")[0])
    except Exception:  # noqa: BLE001
        pass
    for fam, ziel in ((socket.AF_INET, ("192.0.2.1", 1)),
                      (socket.AF_INET6, ("2001:db8::1", 1))):
        # Kein Paket: connect auf UDP waehlt nur die Route und verraet damit
        # die primaere Adresse je Familie.
        try:
            s = socket.socket(fam, socket.SOCK_DGRAM)
            try:
                s.connect(ziel)
                raus.add(s.getsockname()[0].split("%")[0])
            finally:
                s.close()
        except Exception:  # noqa: BLE001
            pass
    _eigene_cache = raus
    return raus


def adresse_sperrgrund(adr: str, eigene: set[str] | None = None) -> str:
    """'' wenn die Adresse erlaubt ist, sonst 'eigen' oder 'intern'.

    Eine IPv4-gemappte IPv6-Adresse (``::ffff:127.0.0.1``) wird als IPv4
    beurteilt – sonst waere sie ein Umweg an der Pruefung vorbei."""
    rein = (adr or "").split("%")[0]
    if eigene is None:
        eigene = eigene_adressen()
    if rein in eigene:
        return "eigen"
    try:
        ip = ipaddress.ip_address(rein)
    except ValueError:
        return "intern"          # unlesbar = nicht erlaubt (fail-closed)
    gemappt = getattr(ip, "ipv4_mapped", None)
    if gemappt is not None:
        if str(gemappt) in eigene:
            return "eigen"
        ip = gemappt
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
            or ip.is_multicast or ip.is_unspecified or not ip.is_global):
        return "intern"
    return ""


def ziel_pruefen(host: str, eigene: set[str] | None = None) -> list[str]:
    """Loest ``host`` auf und gibt die (alle erlaubten) Adressen zurueck.

    Wirft ``ZielFehler``, sobald EINE Adresse gesperrt ist."""
    if not host:
        raise ZielFehler("Die Adresse enthaelt keinen Servernamen.")
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except Exception as e:  # noqa: BLE001
        raise ZielFehler("Der Servername '%s' ist nicht aufloesbar (%s)." % (host, e))
    if eigene is None:
        eigene = eigene_adressen()
    adressen: list[str] = []
    for inf in infos:
        adr = inf[4][0].split("%")[0]
        grund = adresse_sperrgrund(adr, eigene)
        if grund == "eigen":
            raise ZielFehler("Diese Adresse ist der Jarvis-Server selbst (%s). Es lassen "
                             "sich nur fremde, oeffentliche Seiten holen." % adr)
        if grund:
            raise ZielFehler("Diese Adresse zeigt in das interne Netz (%s). Es lassen "
                             "sich nur oeffentliche Seiten holen." % adr)
        if adr not in adressen:
            adressen.append(adr)
    if not adressen:
        raise ZielFehler("Der Servername '%s' ist nicht aufloesbar." % host)
    return adressen


def _proxy_fuer(schema: str, host: str) -> bool:
    """True, wenn fuer dieses Ziel ein Umgebungs-Proxy greift (dann kein Festnageln)."""
    try:
        proxies = urllib.request.getproxies_environment()
        if not proxies.get(schema) and not proxies.get("all"):
            return False
        return not urllib.request.proxy_bypass_environment(host, proxies)
    except Exception:  # noqa: BLE001
        return False


def festnageln(url: str, adresse: str):
    """(url_mit_ip, host_kopf, sni) fuer eine Verbindung auf ``adresse``.

    Der Pfad, die Abfrage und der Port bleiben; nur der Host wird ersetzt."""
    import httpx  # noqa: PLC0415
    teile = urlsplit(url)
    host = teile.hostname or ""
    u = httpx.URL(url)
    gepinnt = u.copy_with(host=adresse)
    kopf = host if ":" not in host else "[%s]" % host
    if teile.port is not None:
        kopf = "%s:%d" % (kopf, teile.port)
    return gepinnt, kopf, host


async def sicher_holen(url: str, *, kopf: dict | None = None, timeout: float = 30.0,
                       max_spruenge: int = 5, pruefer=None, params: dict | None = None):
    """Holt ``url`` mit der Schranke oben und gibt das ``httpx.Response`` zurueck
    (Inhalt vollstaendig gelesen). Weiterleitungen manuell, je Sprung geprueft.

    ``pruefer(host) -> list[str]`` ersetzt ``ziel_pruefen`` (Short Tracks bringt
    eigene Meldungstexte mit). ``resp.url`` traegt die ECHTE (nicht gepinnte)
    Adresse des letzten Sprungs. Wirft ``ZielFehler`` bei gesperrtem Ziel,
    ``httpx.HTTPStatusError`` bei Status >= 400 (wie ``raise_for_status``)."""
    import httpx  # noqa: PLC0415
    pruefer = pruefer or ziel_pruefen
    ziel = (url or "").strip()
    erste = True
    for _ in range(max_spruenge + 1):
        teile = urlsplit(ziel)
        if teile.scheme not in ("http", "https"):
            raise ZielFehler("Nur http- und https-Adressen werden geholt (erhalten: '%s')."
                             % (teile.scheme or "ohne Schema"))
        host = teile.hostname or ""
        adressen = pruefer(host)
        kopfzeilen = dict(kopf or {})
        ext = {}
        if _proxy_fuer(teile.scheme, host) or not adressen:
            anfrage_url = httpx.URL(ziel)
            trust_env = True
        else:
            anfrage_url, host_kopf, sni = festnageln(ziel, adressen[0])
            kopfzeilen["Host"] = host_kopf
            if teile.scheme == "https":
                ext["sni_hostname"] = sni
            trust_env = False
        # Je Sprung ein eigener Client: der Verbindungs-Pool ist nach IP:Port
        # geschluesselt, eine geteilte Verbindung truege die SNI des Vorgaengers.
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout,
                                     trust_env=trust_env) as client:
            anfrage = client.build_request("GET", anfrage_url, headers=kopfzeilen,
                                           params=params if erste else None,
                                           extensions=ext)
            antwort = await client.send(anfrage)
            await antwort.aread()
        if erste and params:
            # Die echte Adresse inkl. Abfrage fuer relative Weiterleitungen
            ziel = str(httpx.URL(ziel).copy_merge_params(params))
        erste = False
        if antwort.status_code in WEITERLEITUNGEN:
            weiter = antwort.headers.get("location") or ""
            if not weiter:
                raise ZielFehler("Weiterleitung ohne Ziel (HTTP %d)." % antwort.status_code)
            ziel = urljoin(ziel, weiter)
            continue
        antwort.request = httpx.Request("GET", ziel)
        antwort.raise_for_status()
        return antwort
    raise ZielFehler("Zu viele Weiterleitungen (mehr als %d)." % max_spruenge)
