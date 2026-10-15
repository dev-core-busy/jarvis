"""Deny-by-default fuer alle Routen (BSI M10, 2026-10-12).

WARUM: Bis hierher war jede Route OFFEN, an die niemand ``Depends(require_…)``
gehaengt hat – Schutz nur je Route, und die vergessene meldet sich nicht. Der
BSI-Abgleich zaehlte 61 von 545 Routen ohne Dependency; die meisten zu Recht
(Seitenrahmen, Anmeldung, Zustandsabfrage), einige mit eigener Pruefung im
Rumpf – aber keine Stelle, die das fuer die NAECHSTE Route erzwingt.

Diese Middleware bestimmt fuer jede Anfrage die Route (dieselbe Reihenfolge wie
der Router) und laesst sie nur durch, wenn

  * die Route eine Anmelde-Dependency traegt (``require_*`` im Abhaengigkeits-
    baum – die Dependency prueft dann wie bisher selbst), ODER
  * sie in ``AUSNAHMEN`` steht – je Eintrag mit Art und Grund, keine
    Sammelfreigabe.

Fuer jede ANDERE Route verlangt sie eine gueltige Anmeldung (dieselbe Pruefung
wie ``require_auth``, inkl. Sperre/Kennwortwechsel/Anmeldeberechtigung). Eine
vergessene Dependency macht eine Route damit "nur fuer Angemeldete" statt
"fuer jeden" – fail-closed, ohne dass die Route kaputtgeht. Jede solche Route
wird einmal im Journal genannt, und ``zustand()`` liefert die Liste (Sicherheit
-> Zugangsregeln, Waechter ``tests/test_bsi_m10.py``).

ARTEN der Ausnahmen:
  seite       – HTML-Rahmen ohne Daten; die Anmeldung laeuft danach im Browser
                ueber die API (die selbst geschuetzt ist).
  anmeldung   – der Weg ZUR Anmeldung (kann keine Anmeldung voraussetzen).
  oeffentlich – bewusst ohne Anmeldung, Inhalt ohne Schutzbedarf.
  selbst      – prueft im Rumpf selbst (anderer Nachweis als die Sitzung:
                Agent-Schluessel, Freigabe-Token, Einmal-Ticket, localhost).
                Der Waechter verlangt dort einen Pruefaufruf im Rumpf.

WebSocket-Routen ohne Eintrag werden geschlossen (1008): ein WebSocket traegt
seinen Nachweis im ersten Rahmen oder als Ticket, die Middleware kann ihn
nicht pruefen – also gibt es dort nur die ausdrueckliche Ausnahme.
"""
from __future__ import annotations

import json
from typing import Callable, Iterable

# (Methode, Pfad) -> (Art, Grund). Methode "WS" fuer WebSockets, "MOUNT" fuer
# eingehaengte Unteranwendungen (Pfad = Praefix).
AUSNAHMEN: dict[tuple[str, str], tuple[str, str]] = {
    # ── Seitenrahmen ──
    ("GET", "/"): ("seite", "Startseite/Anmeldemaske"),
    ("GET", "/manifest.json"): ("seite", "PWA-Manifest"),
    ("GET", "/chat"): ("seite", "Seitenrahmen"),
    ("GET", "/userchat"): ("seite", "Seitenrahmen"),
    ("GET", "/portal"): ("seite", "Seitenrahmen"),
    ("GET", "/wissen"): ("seite", "Seitenrahmen"),
    ("GET", "/supportagent"): ("seite", "Seitenrahmen"),
    ("GET", "/settings"): ("seite", "Seitenrahmen"),
    ("GET", "/api"): ("seite", "API-Dokumentationsseite (Rahmen)"),
    ("GET", "/support-api"): ("seite", "Support-API-Dokumentation (Rahmen)"),
    ("GET", "/sap"): ("seite", "Seitenrahmen"),
    ("GET", "/vemas"): ("seite", "Seitenrahmen"),
    ("GET", "/excel"): ("seite", "Seitenrahmen"),
    ("GET", "/email"): ("seite", "Seitenrahmen"),
    ("GET", "/tracks"): ("seite", "Seitenrahmen"),
    ("GET", "/claude"): ("seite", "Seitenrahmen"),
    ("GET", "/jira-addon"): ("seite", "Seitenrahmen"),
    ("GET", "/confluence-addon"): ("seite", "Seitenrahmen"),
    ("GET", "/ai-mouse"): ("seite", "Seitenrahmen"),
    ("GET", "/feedback"): ("seite", "Seitenrahmen"),
    ("GET", "/support"): ("seite", "Seitenrahmen"),
    ("GET", "/claude/skill.md"): ("seite", "Anleitung zum Herunterladen (statischer Text)"),
    ("GET", "/claude/claude-md-diaet.md"): ("seite", "Anleitung zum Herunterladen (statischer Text)"),
    ("GET", "/addin/manifest.xml"): ("seite", "Outlook-Add-in-Manifest (wird von Office ohne Sitzung geladen)"),
    ("GET", "/addin/taskpane.html"): ("seite", "Outlook-Aufgabenbereich (Rahmen)"),
    ("GET", "/addin/icon-{groesse}.png"): ("seite", "Add-in-Symbol"),
    ("GET", "/excel-addin/manifest.xml"): ("seite", "Excel-Add-in-Manifest"),
    ("GET", "/excel-addin/taskpane.html"): ("seite", "Excel-Aufgabenbereich (Rahmen)"),
    ("GET", "/excel-addin/icon-{groesse}.png"): ("seite", "Add-in-Symbol"),
    ("MOUNT", "/static"): ("seite", "Oberflaechen-Dateien (JS/CSS/Bilder)"),
    ("MOUNT", "/novnc"): ("seite", "noVNC-Dateien; die Verbindung selbst braucht ein Ticket"),
    # ── Anmeldung ──
    ("POST", "/api/login"): ("anmeldung", "Anmeldung"),
    ("POST", "/api/verify-token"): ("anmeldung", "Sitzung pruefen (liefert ohne Sitzung nur 'ungueltig')"),
    ("POST", "/api/addin/sso"): ("anmeldung", "Anmeldung des Outlook-Add-ins per Office-SSO"),
    ("GET", "/api/security/my-block"): ("selbst", "eigene Sperr-Info – auch fuer gesperrte Konten, prueft das Token selbst"),
    # ── oeffentlich ──
    ("GET", "/api/health"): ("oeffentlich", "Zustandsabfrage, liefert nur ok"),
    ("GET", "/api/version"): ("oeffentlich", "Versionsnummer fuer die Anmeldemaske"),
    ("GET", "/api/config"): ("oeffentlich", "VNC-Port/-Verfuegbarkeit fuer die Oberflaeche"),
    ("GET", "/api/branding"): ("oeffentlich", "Marke/Farben – gebraucht auf der Anmeldemaske"),
    ("GET", "/api/branding/logo"): ("oeffentlich", "Logo – gebraucht auf der Anmeldemaske"),
    ("GET", "/api/branding/portal-video"): ("oeffentlich", "Portal-Video der Marke"),
    ("GET", "/api/cert"): ("oeffentlich", "Server-Zertifikat zum Importieren (oeffentlicher Schluessel)"),
    ("POST", "/api/csp-report"): ("oeffentlich", "CSP-Verstossmeldungen des Browsers (BSI H4), ohne Sitzung gesendet"),
    ("GET", "/api/generated/{name}"): ("oeffentlich", "Bild per nicht erratbarer 128-Bit-Kennung (Capability-Adresse)"),
    ("GET", "/api/addin/version"): ("oeffentlich", "Versionsabgleich des Add-ins"),
    ("GET", "/api/excel-addin/version"): ("oeffentlich", "Versionsabgleich des Add-ins"),
    ("GET", "/api/avatar/config"): ("selbst", "Avatar-Darstellung; prueft Sitzung/Schluessel im Rumpf"),
    ("GET", "/api/vision/download/stream-tools"): ("oeffentlich", "Weiterleitung auf den oeffentlichen Download"),
    # ── prueft selbst ──
    ("POST", "/api/feedback"): ("selbst", "Sitzung oder Agent-Schluessel, auch im Rumpf (App-Clients)"),
    ("GET", "/api/avatar/graphics"): ("selbst", "Sitzung oder Agent-Schluessel"),
    ("POST", "/api/avatar/ask"): ("selbst", "Sitzung oder Agent-Schluessel"),
    ("POST", "/api/avatar/stop"): ("selbst", "Sitzung oder Agent-Schluessel"),
    ("POST", "/api/support/query"): ("selbst", "Sitzung oder Agent-Schluessel"),
    ("POST", "/api/support/summarize"): ("selbst", "Sitzung oder Agent-Schluessel"),
    ("POST", "/api/agent/task"): ("selbst", "nur Agent-Schluessel"),
    ("GET", "/api/knowledge/pull/manifest"): ("selbst", "Freigabe-Token des Standorts"),
    ("GET", "/api/knowledge/pull/file"): ("selbst", "Freigabe-Token des Standorts"),
    ("GET", "/api/vision/stream"): ("selbst", "Sitzung oder ausdruecklich gesetzter Stream-Schluessel"),
    ("POST", "/api/tts"): ("selbst", "Sitzung oder Agent-Schluessel"),
    ("GET", "/api/tts/voices"): ("selbst", "Sitzung oder Agent-Schluessel"),
    ("POST", "/api/whatsapp/incoming"): ("selbst", "nur von localhost (WhatsApp-Bridge)"),
    ("WS", "/ws"): ("selbst", "Token im ersten Rahmen"),
    ("WS", "/ws/users"): ("selbst", "Token im ersten Rahmen"),
    ("WS", "/ws/vnc"): ("selbst", "Einmal-Ticket (BSI M4)"),
    ("MOUNT", "/webdav"): ("selbst", "WebDAV mit eigener Anmeldung (Basic, eigenes Kennwort)"),
}
ARTEN = ("seite", "anmeldung", "oeffentlich", "selbst")


def _schluessel(route) -> list[tuple[str, str]]:
    """(Methode, Pfad)-Schluessel einer Route fuer den Abgleich mit AUSNAHMEN."""
    pfad = getattr(route, "path_format", None) or getattr(route, "path", "")
    cls = type(route).__name__
    if cls == "Mount":
        return [("MOUNT", getattr(route, "path", pfad))]
    if "WebSocket" in cls:
        return [("WS", pfad)]
    methoden = getattr(route, "methods", None) or set()
    return [(m, pfad) for m in sorted(methoden) if m != "HEAD"] or [("GET", pfad)]


def _aufrufe(dependant) -> Iterable:
    """Alle ``call`` im Abhaengigkeitsbaum einer Route (rekursiv)."""
    stapel = [dependant]
    while stapel:
        d = stapel.pop()
        if d is None:
            continue
        c = getattr(d, "call", None)
        if c is not None:
            yield c
        stapel.extend(getattr(d, "dependencies", None) or [])


def einstufen(route, anmelde_funktionen: set) -> tuple[str, str]:
    """('dependency'|'ausnahme'|'ohne_regel', Grund)."""
    dep = getattr(route, "dependant", None)
    if dep is not None and any(c in anmelde_funktionen for c in _aufrufe(dep)):
        return "dependency", ""
    for k in _schluessel(route):
        if k in AUSNAHMEN:
            art, grund = AUSNAHMEN[k]
            return "ausnahme", "%s: %s" % (art, grund)
    return "ohne_regel", ""


class ZugangsMiddleware:
    """Reine ASGI-Middleware (wirkt auch fuer WebSockets).

    ``anmelde_funktionen``: liefert die Menge der Anmelde-Dependencies (spaet
    ausgewertet – sie sind beim Einhaengen der Middleware noch nicht definiert).
    ``pruefen``: ``async (Request) -> None``, wirft HTTPException wie
    ``require_auth``.
    """

    def __init__(self, app, anmelde_funktionen: Callable[[], set] = lambda: set(),
                 pruefen=None):
        self.app = app
        self._funktionen_quelle = anmelde_funktionen
        self._pruefen = pruefen
        self._stufe: dict = {}          # id(route) -> Einstufung (Routen aendern sich kaum)
        self._gemeldet: set = set()

    def _einstufung(self, route) -> str:
        k = id(route)
        if k not in self._stufe:
            stufe, _ = einstufen(route, self._funktionen_quelle())
            self._stufe[k] = stufe
            if stufe == "ohne_regel" and k not in self._gemeldet:
                self._gemeldet.add(k)
                print("[Zugang] Route ohne Zugangsregel – verlangt Anmeldung (BSI M10): %s"
                      % ", ".join("%s %s" % s for s in _schluessel(route)), flush=True)
        return self._stufe[k]

    @staticmethod
    def _route(scope):
        from starlette.routing import Match
        app = scope.get("app")
        router = getattr(app, "router", None)
        for r in getattr(router, "routes", None) or []:
            try:
                m, _ = r.matches(scope)
            except Exception:  # noqa: BLE001
                continue
            if m == Match.FULL:
                return r
        return None                      # 404/405 entscheidet der Router

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        route = self._route(scope)
        if route is None or self._einstufung(route) != "ohne_regel":
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        from starlette.requests import Request
        status, detail = 401, "Nicht authentifiziert"
        if self._pruefen is not None:
            try:
                await self._pruefen(Request(scope, receive))
                return await self.app(scope, receive, send)
            except Exception as e:  # noqa: BLE001
                status = int(getattr(e, "status_code", 401) or 401)
                detail = str(getattr(e, "detail", "") or detail)
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def zustand(app, anmelde_funktionen: set) -> dict:
    """Ueberblick fuer Sicherheit -> Zugangsregeln und die Live-Probe."""
    out = {"routen": 0, "dependency": 0, "ausnahmen": [], "ohne_regel": [],
           "verwaiste_ausnahmen": []}
    gesehen = set()
    for r in getattr(app.router, "routes", []):
        out["routen"] += 1
        stufe, grund = einstufen(r, anmelde_funktionen)
        schl = _schluessel(r)
        gesehen.update(schl)
        if stufe == "dependency":
            out["dependency"] += 1
        elif stufe == "ausnahme":
            out["ausnahmen"].append({"route": " ".join(schl[0]), "grund": grund})
        else:
            out["ohne_regel"].append(" ".join(schl[0]))
    # Ausnahmen ohne Route (umbenannt/entfernt) – MOUNTs, die je System fehlen
    # duerfen (noVNC, WebDAV), sind dabei kein Befund.
    out["verwaiste_ausnahmen"] = sorted(
        " ".join(k) for k in AUSNAHMEN if k not in gesehen and k[0] != "MOUNT")
    return out
