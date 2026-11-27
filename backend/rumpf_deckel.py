"""Obergrenze fuer Anfragerumpfe der Endpunkte, die OHNE Sitzung erreichbar sind.

Befund 2026-11-27 (Speicher-DoS ohne Anmeldung): ``/api/login``,
``/api/verify-token``, ``/api/addin/diag`` und weitere Endpunkte ohne
Dependency lasen den GANZEN Rumpf in den Speicher, bevor irgendeine Pruefung
griff – ein Angreifer ohne Konto konnte so mit wenigen parallelen Anfragen
Gigabytes belegen. Die Grenzen IM Endpunkt (z. B. 4 KB in ``addin_diag``)
wirkten erst NACH dem Einlesen.

Diese reine ASGI-Schicht sitzt VOR der Anwendung:

* eine angekuendigte Laenge (Content-Length) ueber der Grenze → sofort 413,
  ohne ein Byte zu lesen;
* ohne (oder mit falscher) Ankuendigung wird hoechstens ``grenze + 1`` Byte
  gelesen; danach 413, der Rest bleibt ungelesen;
* sonst wird der gelesene Rumpf unveraendert an die Anwendung weitergereicht.

Gedeckelt wird nur, was in ``GRENZEN`` steht – Endpunkte mit Anmeldung
(Uploads, Vorlagen, Sprache) behalten ihre eigenen, groesseren Grenzen.
Wer einen neuen Endpunkt OHNE Dependency baut, traegt ihn hier ein
(Waechter: ``tests/test_rumpf_deckel.py`` gleicht die Liste am Syntaxbaum
von ``main.py`` ab).
"""
from __future__ import annotations

import json

KLEIN = 64 * 1024          # Anmeldung, Berichte: ein paar hundert Byte echt
INHALT = 4 * 1024 * 1024   # Endpunkte mit Freitext (Auftrag, Vorlesen, Feedback)

# Pfad → Obergrenze in Byte. Nur exakte Pfade, keine Praefixe: ein Praefix
# wuerde stillschweigend auch kuenftige Endpunkte mit Anmeldung deckeln.
GRENZEN: dict[str, int] = {
    "/api/login": KLEIN,
    "/api/verify-token": KLEIN,
    "/api/login/oidc/einloesen": KLEIN,
    "/api/login/oidc/app-einloesen": KLEIN,
    "/api/addin/diag": KLEIN,
    "/api/addin/sso": KLEIN,
    "/api/csp-report": KLEIN,
    "/api/avatar/stop": KLEIN,
    "/api/feedback": INHALT,
    "/api/avatar/ask": INHALT,
    "/api/support/query": INHALT,
    "/api/support/summarize": INHALT,
    "/api/agent/task": INHALT,
    "/api/tts": INHALT,
    "/api/whatsapp/incoming": INHALT,
}

_ANTWORT = json.dumps({"success": False, "ok": False,
                       "error": "Anfrage zu groß."}).encode()


def grenze_fuer(pfad: str) -> "int | None":
    """Obergrenze fuer diesen Pfad oder None (nicht gedeckelt)."""
    return GRENZEN.get(pfad)


async def _ablehnen(send) -> None:
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(_ANTWORT)).encode()),
                            (b"connection", b"close")]})
    await send({"type": "http.response.body", "body": _ANTWORT})


class RumpfDeckel:
    """ASGI-Middleware: Rumpf der Pfade aus ``GRENZEN`` gedeckelt einlesen."""

    def __init__(self, app, grenzen: "dict[str, int] | None" = None):
        self.app = app
        self.grenzen = GRENZEN if grenzen is None else grenzen

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        grenze = self.grenzen.get(scope.get("path", ""))
        if grenze is None:
            await self.app(scope, receive, send)
            return
        for name, wert in scope.get("headers") or ():
            if name == b"content-length":
                try:
                    if int(wert) > grenze:
                        await _ablehnen(send)
                        return
                except ValueError:
                    await _ablehnen(send)
                    return
        teile, n = [], 0
        while True:
            nachricht = await receive()
            if nachricht["type"] == "http.disconnect":
                return
            stueck = nachricht.get("body", b"")
            n += len(stueck)
            if n > grenze:
                await _ablehnen(send)
                return
            teile.append(stueck)
            if not nachricht.get("more_body", False):
                break
        rumpf = b"".join(teile)
        geliefert = False

        async def wiedergabe():
            nonlocal geliefert
            if not geliefert:
                geliefert = True
                return {"type": "http.request", "body": rumpf, "more_body": False}
            # Danach verhaelt sich receive wie bei Starlette ueblich: das
            # naechste Ereignis ist die Trennung des Clients.
            return await receive()

        await self.app(scope, wiedergabe, send)
