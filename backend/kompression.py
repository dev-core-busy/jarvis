"""GZip-Kompression fuer statische Inhalte und HTML-Seiten – und NUR dafuer.

Anlass (gemessen auf ECHT 2026-11-16): der Dienst lieferte alles unkomprimiert,
auch wenn der Browser ``gzip`` anbot. /settings brachte 3,7 MB ueber die Leitung
(648 KB HTML, ``i18n.js`` allein 962 KB) – im LAN unauffaellig, ueber VPN und
nach jedem Update spuerbar.

Warum eine Weiche vor ``GZipMiddleware`` statt der Middleware fuer alles:

* **``/api/`` bleibt aussen vor.** Dort laufen NDJSON-Stroeme (Destillat,
  Chat), die ``GZipMiddleware`` nicht kennt (sie nimmt nur ``text/event-stream``
  aus) – ein gepufferter Strom kaeme beim Benutzer erst am Ende an. Ausserdem
  mischen API-Antworten Geheimnisse (Tokens, Schluessel) mit Eingaben des
  Benutzers: genau die Lage, in der Kompression eine BREACH-artige Seitenkanal-
  Messung erlaubt. Statische Dateien und die HTML-Huellen tragen beides nicht.
* **WebSocket, WebDAV und ``/ws`` sind kein Thema fuer HTTP-Kompression** bzw.
  haben eigene Clients (WebDAV-Mount unter Windows), deren Verhalten mit
  ``Content-Encoding`` nicht gemessen ist.
* Nur ``GET``/``HEAD`` – alles andere ist keine Auslieferung von Inhalt.

Bilder, Videos, Archive und Schriften nimmt ``GZipMiddleware`` selbst aus
(bereits komprimiert); 304-Antworten haben keinen Rumpf und bleiben unberuehrt.
"""
from __future__ import annotations

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Kleiner lohnt nicht: Kopfzeilen und CPU kosten mehr, als die Kompression spart.
MINDESTGROESSE = 1024
# Stufe 6 statt der Vorgabe 9: fuer Text fast dieselbe Groesse, deutlich weniger
# CPU – der Dienst teilt sich auf ECHT vier Kerne mit Modell- und OCR-Arbeit.
STUFE = 6

# Bis zu dieser angekuendigten Groesse wird ein Rumpf vor dem Packen zu EINEM
# Stueck zusammengefasst (siehe _Zusammenfassen). Die groesste Datei heute ist
# i18n.js mit knapp 1 MB; darueber wird gestueckelt gepackt wie bisher.
PUFFER_MAX = 8 * 1024 * 1024

# Pfad-Praefixe, die NIE komprimiert werden (Begruendung im Modulkopf).
AUSGENOMMEN = ("/api/", "/ws", "/webdav", "/openapi.json")


def komprimierbar(scope: Scope) -> bool:
    """Darf diese Anfrage komprimiert beantwortet werden? Entscheidet am
    Routing-Pfad (``scope["path"]``), nicht an ``request.url`` – der wird aus dem
    Host-Header gebaut (CVE-2026-48710, siehe ``main._routing_pfad``)."""
    if scope.get("type") != "http":
        return False
    if scope.get("method") not in ("GET", "HEAD"):
        return False
    pfad = scope.get("path") or ""
    # "/api" OHNE Schraegstrich ist die HTML-Dokumentationsseite – die darf.
    if pfad.startswith(AUSGENOMMEN):
        return False
    return True


class _Zusammenfassen:
    """Fasst einen Rumpf mit bekannter Laenge (<= PUFFER_MAX) zu EINER
    ``http.response.body``-Nachricht zusammen, bevor ``GZipMiddleware`` ihn sieht.

    ⚠ WARUM (auf DEV gemessen 2026-11-16): die inneren ``@app.middleware``-
    Schichten (BaseHTTPMiddleware) reichen JEDEN Rumpf gestueckelt weiter
    (``more_body=True``). ``GZipMiddleware`` prueft die Mindestgroesse aber nur
    bei einem Rumpf in einem Stueck – gestueckelt packt sie alles, auch eine
    48-Byte-404 (danach 73 Byte), und liefert ohne ``Content-Length`` (chunked).
    Ein Rumpf OHNE Laengenangabe ist ein echter Strom und laeuft unveraendert
    gestueckelt durch – ihn zu puffern hiesse, ihn anzuhalten."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        puffern = False
        teile: list[bytes] = []

        async def senden(m: Message) -> None:
            nonlocal puffern
            if m["type"] == "http.response.start":
                laenge = Headers(raw=m.get("headers", [])).get("content-length", "")
                puffern = laenge.isdigit() and int(laenge) <= PUFFER_MAX
                await send(m)
                return
            if m["type"] == "http.response.body" and puffern:
                teile.append(m.get("body", b""))
                if m.get("more_body", False):
                    return
                await send({"type": "http.response.body", "body": b"".join(teile), "more_body": False})
                return
            await send(m)

        await self.app(scope, receive, senden)


class KompressionsWeiche:
    """Leitet komprimierbare Anfragen durch ``GZipMiddleware``, alle anderen
    unveraendert an die App."""

    def __init__(self, app: ASGIApp, minimum_size: int = MINDESTGROESSE,
                 compresslevel: int = STUFE) -> None:
        self.app = app
        self.gzip = GZipMiddleware(_Zusammenfassen(app), minimum_size=minimum_size,
                                   compresslevel=compresslevel)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if komprimierbar(scope):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)
