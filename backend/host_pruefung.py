"""Pruefung des Servernamens jeder Anfrage (Haertung B12, Checkliste 109).

WARUM (gemessen auf ECHT, 2026-11-21): eine Anfrage mit fremdem Host-Kopf
(``Host: boese.example``) bekam HTTP 200. Das oeffnet zwei Wege:

* DNS-Rebinding: eine fremde Seite laesst ihren eigenen Namen auf die Adresse
  des Servers zeigen und spricht ihn dann als "gleiche Herkunft" an.
* Adressen, die aus der Anfrage abgeleitet werden (Rueckkehradresse der
  IdP-Anmeldung ohne feste Einstellung, ``request.base_url``, die CSP mit
  ``wss://<host>``), uebernehmen sonst einen Namen, den der Absender waehlt.

Erlaubt sind die Namen, unter denen der Server tatsaechlich erreichbar ist:

* ``localhost``, ``127.0.0.1``, ``::1`` (Proben, Dienste auf dem Server selbst)
* CN und alle DNS-/IP-Namen (SAN) des Server-Zertifikats – unter einem anderen
  Namen meldet der Browser ohnehin einen Zertifikatsfehler
* der eigene Rechnername (kurz und voll), ``SERVER_IP`` und die Adresse, ueber
  die der Server nach aussen spricht
* die Hosts aus ``cors_origins``, ``addin_base_url``, ``oidc_redirect_uri`` (feste
  Rueckkehradresse des IdP) und der Liste ``erlaubte_hostnamen`` (Komma-Liste oder
  JSON-Liste) in settings.json

``host_pruefung`` in settings.json:

* ``auto`` (Vorgabe): abweisen, wenn das Server-Zertifikat von einer CA stammt
  (dann sind die Namen festgelegt, wie auf ECHT); bei einem selbst signierten
  oder unlesbaren Zertifikat (DEV, Docker, Erstinstallation) nur melden – dort
  greift man oft ueber eine Adresse zu, die der Server nicht von sich kennt,
  und ein Abweisen sperrte die Installation aus.
* ``erzwingen``: immer abweisen. ``melden``: nie abweisen, nur protokollieren.
  ``aus``: weder noch. Ein unbekannter Wert gilt als ``auto``.

Abgewiesen wird mit HTTP 421 (Misdirected Request), bei einer WebSocket-
Anfrage mit dem Schliesscode 1008 vor dem Annehmen. Jeder fremde Name wird
hoechstens einmal je Stunde ins Journal geschrieben (der Wert kommt vom
Absender – gekuerzt und mit repr).

Die Liste wird hoechstens alle ``TTL_S`` Sekunden neu gebaut:
``config.get_setting`` liest und entschluesselt settings.json bei jedem Aufruf,
und die Middleware laeuft vor JEDER Anfrage.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
import time
from pathlib import Path

MODI = ("auto", "erzwingen", "melden", "aus")
VORGABE = "auto"
STATUS = 421
WS_CODE = 1008
TTL_S = 60.0
MELDE_ABSTAND_S = 3600.0
MELDE_MAX = 200
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
# settings.json: Adressen, deren Host erlaubt ist
URL_SCHLUESSEL = ("cors_origins", "addin_base_url", "oidc_redirect_uri")
LISTEN_SCHLUESSEL = "erlaubte_hostnamen"

_get_setting = None
_zert_pfad: Path | None = None
_sperre = threading.Lock()
_stand: tuple[float, str, frozenset] | None = None    # (zeit, modus_wirksam, namen)
_gemeldet: dict[str, float] = {}


def einstellungen_quelle(fn, zertifikat: Path | None = None) -> None:
    """``main`` reicht ``config.get_setting`` und das Server-Zertifikat herein
    (das Modul importiert ``backend.config`` nie selbst)."""
    global _get_setting, _zert_pfad, _stand
    _get_setting = fn
    _zert_pfad = zertifikat
    with _sperre:
        _stand = None
        _gemeldet.clear()


def _einst(name: str, vorgabe=None):
    if _get_setting is None:
        return vorgabe
    try:
        return _get_setting(name, vorgabe)
    except Exception:  # noqa: BLE001
        return vorgabe


def host_normal(roh) -> str:
    """Host-Kopf oder Name auf den reinen Namen bringen: klein, ohne Port, ohne
    eckige Klammern, ohne abschliessenden Punkt. Unbrauchbares -> ``""``."""
    h = str(roh or "").strip().lower()
    if not h or len(h) > 255 or any(c in h for c in " /\\@?#\t\r\n"):
        return ""
    if h.startswith("["):
        ende = h.find("]")
        if ende < 0:
            return ""
        rest = h[ende + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return ""
        h = h[1:ende]
        try:
            return str(ipaddress.IPv6Address(h))
        except ValueError:
            return ""
    if h.count(":") == 1:
        h, port = h.split(":", 1)
        if not port.isdigit():
            return ""
    elif ":" in h:
        # IPv6 ohne Klammern (nur als Name aus Einstellungen/Zertifikat)
        try:
            return str(ipaddress.IPv6Address(h))
        except ValueError:
            return ""
    return h.rstrip(".")


def _host_aus_url(url) -> str:
    u = str(url or "").strip()
    if "://" not in u:
        return host_normal(u)
    rest = u.split("://", 1)[1]
    for trenner in "/?#":
        rest = rest.split(trenner, 1)[0]
    if "@" in rest:
        return ""
    return host_normal(rest)


def _liste(wert) -> list:
    if isinstance(wert, (list, tuple, set)):
        return list(wert)
    s = str(wert or "").strip()
    if s.startswith("["):
        try:
            w = json.loads(s)
            return list(w) if isinstance(w, list) else []
        except ValueError:
            return []
    return [t for t in s.split(",")]


def zertifikat_lesen(pfad: Path | None) -> tuple[bool | None, set]:
    """(selbst_signiert, Namen) des Server-Zertifikats; (None, leer) = unlesbar."""
    if pfad is None:
        return None, set()
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        z = x509.load_pem_x509_certificate(Path(pfad).read_bytes())
    except Exception:  # noqa: BLE001
        return None, set()
    namen = set()
    try:
        for a in z.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
            namen.add(host_normal(a.value))
    except Exception:  # noqa: BLE001
        pass
    try:
        san = z.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for n in san.get_values_for_type(x509.DNSName):
            namen.add(host_normal(n))
        for ip in san.get_values_for_type(x509.IPAddress):
            namen.add(host_normal(str(ip)))
    except Exception:  # noqa: BLE001
        pass
    namen.discard("")
    return z.issuer == z.subject, namen


def _eigene_namen() -> set:
    namen = set()
    for f in (socket.gethostname, socket.getfqdn):
        try:
            namen.add(host_normal(f()))
        except Exception:  # noqa: BLE001
            pass
    namen.add(host_normal(os.getenv("SERVER_IP", "")))
    # Adresse, ueber die der Server nach aussen spricht – connect() auf UDP
    # sendet nichts, es waehlt nur die Route (TEST-NET-Adresse als Ziel).
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            namen.add(host_normal(s.getsockname()[0]))
    except OSError:
        pass
    namen.discard("")
    return namen


def modus() -> str:
    """Eingestellter Modus; Unbekanntes gilt als ``auto``."""
    w = str(_einst("host_pruefung", VORGABE) or VORGABE).strip().lower()
    return w if w in MODI else VORGABE


def _bauen() -> tuple[str, frozenset]:
    m = modus()
    selbst, zert_namen = zertifikat_lesen(_zert_pfad)
    if m == "auto":
        # Nur ein nachweislich CA-signiertes Zertifikat legt die Namen fest –
        # unlesbar heisst: melden (niemand wird ausgesperrt).
        m = "erzwingen" if selbst is False else "melden"
    namen = set(LOOPBACK) | zert_namen | _eigene_namen()
    for schluessel in URL_SCHLUESSEL:
        for u in _liste(_einst(schluessel, "")):
            namen.add(_host_aus_url(u))
    for n in _liste(_einst(LISTEN_SCHLUESSEL, "")):
        namen.add(host_normal(n))
    namen.discard("")
    return m, frozenset(namen)


def stand(jetzt: float | None = None) -> tuple[str, frozenset]:
    """(wirksamer Modus, erlaubte Namen) – gemerkt fuer ``TTL_S`` Sekunden."""
    global _stand
    t = time.monotonic() if jetzt is None else jetzt
    with _sperre:
        if _stand and t - _stand[0] < TTL_S:
            return _stand[1], _stand[2]
    m, namen = _bauen()
    with _sperre:
        _stand = (t, m, namen)
    return m, namen


def erlaubt(host_kopf) -> bool:
    _, namen = stand()
    h = host_normal(host_kopf)
    return bool(h) and h in namen


def _melden(host_kopf, client: str, modus_wirksam: str) -> None:
    roh = str(host_kopf or "")[:80]
    t = time.monotonic()
    with _sperre:
        zuletzt = _gemeldet.get(roh)
        if zuletzt is not None and t - zuletzt < MELDE_ABSTAND_S:
            return
        if zuletzt is None and len(_gemeldet) >= MELDE_MAX:
            return
        _gemeldet[roh] = t
    print("[Host-Pruefung] fremder Servername %r von %s – %s" % (
        roh, client or "?", "abgewiesen" if modus_wirksam == "erzwingen" else "nur gemeldet"),
        flush=True)


def _host_aus_scope(scope) -> str | None:
    for k, v in scope.get("headers") or ():
        if k == b"host":
            return v.decode("latin-1")
    return None


class HostPruefung:
    """ASGI-Middleware: weist Anfragen mit fremdem Servernamen ab (HTTP und
    WebSocket). Aeusserste Schicht – sie laeuft vor allen anderen."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        m, namen = stand()
        if m == "aus":
            return await self.app(scope, receive, send)
        host = _host_aus_scope(scope)
        h = host_normal(host)
        if h and h in namen:
            return await self.app(scope, receive, send)
        client = (scope.get("client") or ("",))[0]
        _melden(host, client, m)
        if m != "erzwingen":
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": WS_CODE})
            return
        rumpf = "Unbekannter Servername.\n".encode("utf-8")
        await send({"type": "http.response.start", "status": STATUS,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(rumpf)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": rumpf})
