"""/ws vor der Anmeldung: kleine Nachrichten, eine nach der anderen, mit Frist.

Befund 2026-11-27 (Speicher-DoS ohne Anmeldung): ``/ws`` nimmt jede Verbindung
an und prueft erst die Nachrichten (BSI M10). uvicorn laesst je Nachricht bis
``--ws-max-size`` (100 MB, wegen Chat-Anhaengen) zu, und die websockets-
Bibliothek liest im Hintergrund bis zu ``max_queue`` (32) solcher Nachrichten
vor, egal ob die Anwendung sie abholt. Eine einzige Verbindung OHNE Konto
konnte damit Gigabytes belegen – ohne Zeitlimit.

Vier Schranken, solange die Verbindung NICHT angemeldet ist:

1. **Kleine Nachrichten:** hoechstens ``VOR_ANMELDUNG_MAX`` Byte. Was darueber
   liegt, bricht die Bibliothek beim Lesen des Rahmenkopfs ab (Code 1009) –
   die Nutzlast wird gar nicht erst gelesen.
2. **Eine nach der anderen:** die naechste Nachricht wird erst gelesen, wenn
   die Anwendung die vorige verarbeitet hat. Ohne das hat die Bibliothek die
   zweite Nachricht schon mit der kleinen Grenze angefangen, bevor die erste
   (die Anmeldung) geprueft wurde – ein Anhang direkt nach dem ``hello``
   wuerde abgewiesen. Und ohne das liefe die Vorauslese-Warteschlange voll.
3. **Frist:** ohne gueltige Anmeldung binnen ``ANMELDE_FRIST_S`` wird die
   Verbindung geschlossen (Code 1008). Alle Clients (Browser, Windows, Android)
   melden sich direkt beim Oeffnen an.
4. **Anzahl:** hoechstens ``JE_QUELLE_MAX`` nicht angemeldete Verbindungen je
   Quelle und ``GESAMT_MAX`` insgesamt (``zulassen``, sonst Code 1013).

Nach der Anmeldung gilt wieder die volle Grenze des Servers, ohne Takt.

**Technik:** Starlette reicht das Protokollobjekt nicht heraus; erreichbar ist
es ueber die gebundene Empfangsmethode (``ws._receive.__self__``, uvicorn 0.34 /
websockets 14 Legacy-Protokoll). Die Bibliothek liest ``max_size`` zu Beginn
JEDER Nachricht neu, und ``transfer_data`` ruft ``self.read_message()`` – eine
Instanzmethode ersetzt sie fuer genau diese Verbindung. Passt das Objekt nicht
(andere Bibliothek), meldet ``vorbereiten`` das laut und es bleibt bei Frist
und Takt auf Anwendungsebene; die Waechter pruefen die Verkabelung gegen die
installierten Fassungen (``tests/test_ws_vorab.py``).
"""
from __future__ import annotations

import asyncio

# 1 MB statt weniger KB: der Windows-Client schickt seine Anmeldung aus einer
# Goroutine, eine wartende Nachricht (Sprachaufnahme fuer das Weckwort) kann
# also vor ihr ankommen – sie traegt selbst das Token und ist legitim.
VOR_ANMELDUNG_MAX = 1024 * 1024
ANMELDE_FRIST_S = 30.0
# Gleichzeitig nicht angemeldete Verbindungen: je Quelle und insgesamt. Mit
# Takt und Grenze belegt eine solche Verbindung hoechstens ~VOR_ANMELDUNG_MAX,
# zusammen also hoechstens GESAMT_MAX * VOR_ANMELDUNG_MAX.
JE_QUELLE_MAX = 16
GESAMT_MAX = 256

# id(ws) -> _Vorab
_offen: dict[int, "_Vorab"] = {}


class _Vorab:
    """Zustand einer Verbindung bis zur Anmeldung."""

    def __init__(self, proto, voll_max, quelle=""):
        self.proto = proto
        self.quelle = quelle
        self.voll_max = voll_max
        self.angemeldet = False
        self.frei = asyncio.Event()
        self.frei.set()          # die ERSTE Nachricht darf sofort gelesen werden

    def lesen_vorbereiten(self) -> None:
        if self.proto is not None:
            self.proto.max_size = self.voll_max if self.angemeldet else VOR_ANMELDUNG_MAX


def _protokoll(ws):
    """Das websockets-Protokollobjekt hinter einer Starlette-Verbindung oder None."""
    proto = getattr(getattr(ws, "_receive", None), "__self__", None)
    if proto is None:
        return None
    if not (hasattr(proto, "max_size") and hasattr(proto, "read_message")
            and asyncio.iscoroutinefunction(getattr(proto, "read_message"))):
        return None
    return proto


def _quelle(ws) -> str:
    client = getattr(ws, "client", None)
    return (getattr(client, "host", "") or "") if client else ""


def zulassen(ws) -> bool:
    """Darf diese Verbindung (noch nicht angemeldet) ueberhaupt angenommen werden?"""
    wartend = [v for v in _offen.values() if not v.angemeldet]
    if len(wartend) >= GESAMT_MAX:
        return False
    quelle = _quelle(ws)
    return sum(1 for v in wartend if v.quelle == quelle) < JE_QUELLE_MAX


def vorbereiten(ws) -> bool:
    """VOR ``ws.accept()`` aufrufen. True = Schranken auf Protokollebene aktiv."""
    proto = _protokoll(ws)
    vorab = _Vorab(proto, getattr(proto, "max_size", None), _quelle(ws))
    _offen[id(ws)] = vorab
    if proto is None:
        print("[ws_vorab] Protokollobjekt nicht erreichbar – Groessengrenze vor "
              "der Anmeldung NICHT aktiv (nur Frist).", flush=True)
        return False
    original = proto.read_message

    async def read_message():
        if not vorab.angemeldet:
            await vorab.frei.wait()
            vorab.frei.clear()
        vorab.lesen_vorbereiten()
        return await original()

    proto.read_message = read_message
    vorab.lesen_vorbereiten()
    return True


def verarbeitet(ws) -> None:
    """Die Anwendung ist mit der vorigen Nachricht fertig – naechste lesen."""
    vorab = _offen.get(id(ws))
    if vorab is not None:
        vorab.frei.set()


def freischalten(ws) -> None:
    """Verbindung hat sich angemeldet: volle Grenze, kein Takt mehr."""
    vorab = _offen.get(id(ws))
    if vorab is not None:
        vorab.angemeldet = True
        vorab.lesen_vorbereiten()
        vorab.frei.set()


def ist_angemeldet(ws) -> bool:
    vorab = _offen.get(id(ws))
    return vorab is None or vorab.angemeldet


def frist(ws, beginn: float, jetzt: float) -> "float | None":
    """Restzeit bis zur Anmeldefrist (None = angemeldet, keine Frist)."""
    if ist_angemeldet(ws):
        return None
    return max(0.0, ANMELDE_FRIST_S - (jetzt - beginn))


def entfernen(ws) -> None:
    vorab = _offen.pop(id(ws), None)
    if vorab is not None:
        vorab.frei.set()   # ein wartender Leser haengt nicht am Schliessen
