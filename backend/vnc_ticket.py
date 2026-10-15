"""Einmal-Ticket fuer den VNC-WebSocket (BSI M4).

WARUM: noVNC baut die WebSocket-Verbindung selbst auf und spricht danach sofort
RFB – es gibt keinen ersten Rahmen, in dem der Client sich ausweisen koennte,
und einen Kopfsatz kann ein Browser-WebSocket nicht setzen. Bis 2026-10-05 stand
deshalb das SITZUNGStoken in der Adresse (``/ws/vnc?token=...``), und zwar
doppelt: in der Adresse der noVNC-Seite und im WebSocket-Aufbau. Beides
schreibt uvicorn ins Protokoll; das Token galt dort weiter 12 Stunden.

Jetzt holt die Oberflaeche mit dem Kopfsatz ein Ticket, das
  - nur EINMAL eingeloest werden kann (der erste Verbindungsaufbau verbraucht es),
  - nach ``TTL_SEK`` verfaellt, auch ungenutzt,
  - den Sitzungskontext der ausstellenden Anfrage mitnimmt (2FA-Status, BSI M3):
    eine Sitzung ohne Admin-Rechte bekommt am WebSocket auch keine.
Ein Ticket, das in einem Protokoll steht, ist damit wertlos.

Bewusst im Speicher: es lebt Sekunden, ein Neustart verwirft es zu Recht.
"""
from __future__ import annotations

import secrets
import threading
import time

TTL_SEK = 60

_lock = threading.Lock()
# ticket -> (benutzer, sitzungskontext, ablauf)
_tickets: dict[str, tuple[str, object, float]] = {}


def _aufraeumen(jetzt: float) -> None:
    for t in [t for t, (_, _, ab) in _tickets.items() if ab <= jetzt]:
        _tickets.pop(t, None)


def ausstellen(benutzer: str, kontext: object = None) -> str:
    """Neues Ticket fuer ``benutzer``; ``kontext`` = Sitzungskontext der Anfrage."""
    if not benutzer:
        raise ValueError("ohne Benutzer kein Ticket")
    t = secrets.token_urlsafe(32)
    jetzt = time.monotonic()
    with _lock:
        _aufraeumen(jetzt)
        _tickets[t] = (benutzer, kontext, jetzt + TTL_SEK)
    return t


def einloesen(ticket: str) -> tuple[str, object] | None:
    """``(benutzer, kontext)`` oder None. Verbraucht das Ticket in JEDEM Fall."""
    if not ticket or not isinstance(ticket, str):
        return None
    jetzt = time.monotonic()
    with _lock:
        eintrag = _tickets.pop(ticket, None)
        _aufraeumen(jetzt)
    if eintrag is None or eintrag[2] <= jetzt:
        return None
    return eintrag[0], eintrag[1]
