"""HTTP→HTTPS-Umleitung auf Port 80 – nur auf Namen aus dem Serverzertifikat (BSI N2).

Befund N2 aus dem BSI-Abgleich vom 2026-09-29: die Umleitung baute ihr Ziel
aus ``request.url`` und damit aus dem Host-Kopf der Anfrage. Ein Link
``http://<server>/`` mit ``Host: boese.example`` leitete auf
``https://boese.example/`` um (Open Redirect) – ein Werkzeug fuer
Phishing-Links, die mit der echten Serveradresse beginnen.

Jetzt gilt: Ziel ist IMMER ein Name, fuer den das Serverzertifikat ausgestellt
ist. Nennt der Host-Kopf einen davon (DNS-Name oder IP aus dem SAN), bleibt es
bei ihm – der Benutzer landet dort, wo er hinwollte, und das Zertifikat passt.
Sonst geht es auf den ersten Namen, der bei einem fremden Client ueberhaupt
ankommen kann – einteilige Rechnernamen und Loopback zaehlen nicht dazu
(``taugt_als_rueckfall``, Vorfall vom 2026-10-13). Kein fester Name im Code:
die Namen stehen im Zertifikat der jeweiligen Installation.

Laesst sich das Zertifikat nicht lesen, gibt es KEINE Umleitung, sondern einen
Hinweis-Text (fail-closed) – ein Rueckfall auf den Host-Kopf waere genau die
Luecke.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path


def zertifikat_namen(cert_pfad) -> list[str]:
    """DNS-Namen und IP-Adressen aus dem SAN des Zertifikats, DNS zuerst.

    Ohne SAN: der CN. Leere Liste, wenn die Datei fehlt oder unlesbar ist."""
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        daten = Path(cert_pfad).read_bytes()
        cert = x509.load_pem_x509_certificate(daten)
    except Exception:  # noqa: BLE001
        return []
    dns: list[str] = []
    ips: list[str] = []
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        dns = [n.strip().lower() for n in san.get_values_for_type(x509.DNSName)]
        ips = [str(a) for a in san.get_values_for_type(x509.IPAddress)]
    except Exception:  # noqa: BLE001 – kein SAN
        pass
    if not dns and not ips:
        try:
            cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            dns = [cn[0].value.strip().lower()] if cn else []
        except Exception:  # noqa: BLE001
            dns = []
    # Platzhalter (*.firma.de) taugen nicht als Ziel
    dns = [d for d in dns if d and "*" not in d]
    return dns + ips


def _host_ohne_port(host: str) -> str:
    host = (host or "").strip().lower()
    if host.startswith("["):                       # [IPv6]:port
        return host[1:host.find("]")] if "]" in host else ""
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    return host


def _als_netzname(name: str) -> str:
    """IPv6 in eckige Klammern, alles andere unveraendert."""
    try:
        if ipaddress.ip_address(name).version == 6:
            return "[%s]" % name
    except ValueError:
        pass
    return name


def taugt_als_rueckfall(name: str) -> bool:
    """Kann dieser Name das Ziel fuer einen FREMDEN Client sein?

    Der Rueckfall trifft jemanden, der eine ANDERE Adresse getippt hat – er
    muss den Namen also selbst aufloesen koennen. Zwei Klassen koennen das
    grundsaetzlich nicht:

    * **Einteilige Namen** (``jarvis``). Sie gelten nur innerhalb der eigenen
      Suchdomaene. Genau das war der Fehler (DEV, 2026-10-13): das
      selbstsignierte Zertifikat entsteht aus ``_collect_server_names()``, und
      dessen Liste beginnt mit ``["jarvis", "jarvis.local", "localhost"]`` –
      ``namen[0]`` war damit auf JEDER Standardinstallation der blanke
      Rechnername. Gemessen: ``http://<dev-ip>/chat`` → ``https://jarvis/chat``,
      ein Ziel, das ausserhalb des Servers niemand aufloest. Der Benutzer sieht
      einen DNS-Fehler und nichts, was ihn weiterbringt.
    * **Loopback/unspezifisch** (``localhost``, ``127.0.0.1``, ``::1``,
      ``0.0.0.0``). Dorthin umgeleitet landet ein fremder Client auf dem
      EIGENEN Rechner – schlimmer als keine Umleitung.
    * **``.local``** (``jarvis.local``). Das ist nach RFC 6762 fuer mDNS
      reserviert und loest nur auf demselben Netzabschnitt auf – in einem
      gerouteten Netz so unbrauchbar wie der blanke Rechnername. Steht
      ebenfalls im selbstsignierten Zertifikat (``_collect_server_names``),
      waere also ohne diese Zeile der naechste Griff nach dem einteiligen Namen.

    Die drei Klassen folgen je einer Festlegung (Suchdomaene, RFC 5735/4291,
    RFC 6762) – nicht dem Symptom eines einzelnen Servers.

    Ein ausdruecklich GEWUENSCHTER Name wird davon nicht beruehrt: wer
    ``http://jarvis/`` tippt, kann ihn offensichtlich aufloesen (siehe
    ``ziel_url``). Platzhalter sind schon in ``zertifikat_namen`` weg.
    """
    name = (name or "").strip().lower()
    if not name:
        return False
    try:
        adr = ipaddress.ip_address(name)
    except ValueError:
        if "." not in name:                       # einteilig
            return False
        if name == "localhost" or name.endswith(".localhost"):
            return False
        return not (name == "local" or name.endswith(".local"))
    return not (adr.is_loopback or adr.is_unspecified)


def ziel_url(host_kopf: str, pfad: str, query: str, namen: list[str], port: int = 443) -> str | None:
    """HTTPS-Adresse fuer die Umleitung oder None (kein zulaessiges Ziel).

    ``namen`` ist die Liste aus ``zertifikat_namen`` – das Ziel ist IMMER
    einer davon, nie der rohe Host-Kopf.

    Nennt der Host-Kopf einen Namen aus dem Zertifikat, bleibt es bei ihm –
    auch bei einem einteiligen (wer ``http://jarvis/`` tippt, loest ihn auf).
    Sonst wird der erste Name genommen, der beim Client ueberhaupt ankommen
    kann (``taugt_als_rueckfall``); bleibt keiner uebrig, gibt es KEINE
    Umleitung. Ein Sprung auf ein unaufloesbares Ziel ist keine Hilfe, sondern
    ein DNS-Fehler ohne Erklaerung."""
    if not namen:
        return None
    gewuenscht = _host_ohne_port(host_kopf)
    if gewuenscht and gewuenscht in namen:
        host = gewuenscht
    else:
        brauchbar = [n for n in namen if taugt_als_rueckfall(n)]
        if not brauchbar:
            return None
        host = brauchbar[0]
    netz = _als_netzname(host)
    if port and int(port) != 443:
        netz = "%s:%d" % (netz, int(port))
    # Pfad beginnt immer mit genau EINEM "/": "//x" waere sonst eine
    # schemarelative Adresse, falls ein Client das Ziel neu zusammensetzt.
    pfad = "/" + (pfad or "").lstrip("/")
    return "https://%s%s%s" % (netz, pfad, ("?" + query) if query else "")


def app_erstellen(cert_pfad, port: int = 443):
    """Starlette-App fuer Port 80. Die Zertifikatsnamen werden je Anfrage frisch
    gelesen, wenn sich die Datei geaendert hat (neues Zertifikat ohne Neustart)."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse, RedirectResponse
    from starlette.routing import Route

    stand: dict = {"mtime": None, "namen": []}

    def _namen() -> list[str]:
        try:
            mtime = os.stat(cert_pfad).st_mtime
        except OSError:
            return []
        if stand["mtime"] != mtime:
            stand["namen"] = zertifikat_namen(cert_pfad)
            stand["mtime"] = mtime
        return stand["namen"]

    async def _umleiten(request):
        ziel = ziel_url(request.headers.get("host", ""), request.url.path,
                        request.url.query, _namen(), port)
        if not ziel:
            return PlainTextResponse("Bitte die Adresse mit https:// aufrufen.", status_code=400)
        return RedirectResponse(ziel, status_code=301)

    return Starlette(routes=[Route("/{path:path}", _umleiten)])
