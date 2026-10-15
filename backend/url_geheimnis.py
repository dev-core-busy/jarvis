"""Geheimnisse in Adressen schwaerzen, bevor sie in ein Protokoll gehen (BSI M4).

WARUM: uvicorn schreibt jede Anfrage MIT Query-String ins Access-Log
(``"GET /api/x?token=... HTTP/1.1" 200``) und jeden WebSocket-Aufbau ueber
``uvicorn.error`` (``"WebSocket /ws/vnc?token=..." [accepted]``). Das Journal
liest jeder in den Gruppen ``adm``/``systemd-journal`` – ein Sitzungstoken dort
ist eine Kontouebernahme ohne Kennwort.

Gemessen auf DEV am 2026-10-05: das Access-Log von Jarvis kam zu diesem Zeitpunkt
GAR NICHT im Journal an (ein Nachbau mit derselben uvicorn-Version schrieb
``GET /x?token=SONDE`` sehr wohl). Dass dort nichts stand, war also Zufall und
kein Schutz – sobald jemand das Access-Log wieder einschaltet, ist es zurueck.
Deshalb haengt der Filter an den Loggern selbst und wirkt unabhaengig davon.

Geschwaerzt wird der WERT bekannter Geheimnis-Parameter, auch wenn er
prozentkodiert in einem anderen Parameter steckt (noVNC:
``path=ws%2Fvnc%3Fticket%3D...``), und das Kennwort in ``schema://user:pw@host``
(Kamera-Adressen). Name und Rest der Adresse bleiben lesbar – das Protokoll soll
weiter zeigen, WAS abgerufen wurde.
"""
from __future__ import annotations

import logging
import re

# Parameternamen, deren Wert nie in ein Protokoll gehoert (Gross/klein egal).
GEHEIME_PARAMETER = (
    "token", "access_token", "id_token", "refresh_token",
    "key", "api_key", "apikey", "ticket",
    "password", "passwort", "pw", "secret", "sig", "signature", "code",
)

ERSATZ = "***"

_NAMEN = "|".join(sorted((re.escape(n) for n in GEHEIME_PARAMETER), key=len, reverse=True))
# Anfang: Stringbeginn, ?, &, ;, oder die Prozentform von ? und & (verschachtelte
# Adresse). Ende des Werts: &, #, Leerraum, Anfuehrungszeichen oder ein
# prozentkodiertes & (%26) – sonst fraesse der Ausdruck die folgenden Parameter
# der aeusseren Adresse mit.
_PARAM = re.compile(
    r"(?P<vor>(?:^|[?&;]|%3[Ff]|%26))(?P<name>" + _NAMEN + r")(?P<gleich>=|%3[Dd])"
    r"(?P<wert>(?:(?!%26)[^&#\s\"'])+)",
    re.IGNORECASE,
)
# schema://benutzer:kennwort@host – nur das Kennwort wird ersetzt.
# Das Lookbehind laesst ein Schema nur an einer Wortgrenze beginnen: ohne es
# probierte der Ausdruck in einer langen Buchstabenfolge JEDE Position als
# Schema-Anfang – quadratisch (16.000 Zeichen = 0,46 s, eine 1-MB-Zeile hing
# minutenlang; gefunden beim Bau der Journal-Einsicht BSI M8, 2026-10-12).
_USERINFO = re.compile(r"(?<![a-zA-Z0-9+.-])(?P<vor>[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]*:)(?P<pw>[^/\s@]+)(?=@)")


def schwaerzen(text):
    """Gibt ``text`` mit geschwaerzten Geheimnis-Werten zurueck; Nicht-Strings unveraendert."""
    if not isinstance(text, str) or not text:
        return text
    t = _PARAM.sub(lambda m: m.group("vor") + m.group("name") + m.group("gleich") + ERSATZ, text)
    return _USERINFO.sub(lambda m: m.group("vor") + ERSATZ, t)


class ProtokollFilter(logging.Filter):
    """Schwaerzt Nachricht und String-Argumente eines Protokolleintrags.

    Laesst JEDEN Eintrag durch (Rueckgabe True) – ein Filter, der bei einem
    unerwarteten Eintrag ``False`` liefert, wuerde Meldungen verschlucken.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = schwaerzen(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(schwaerzen(a) for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: schwaerzen(v) for k, v in record.args.items()}
        except Exception:  # noqa: BLE001 – ein Protokollfilter darf nie werfen
            pass
        return True


# Die Logger, ueber die uvicorn Adressen ausgibt: Access-Log und die
# WebSocket-Zeilen ("WebSocket /pfad?query" [accepted]).
UVICORN_LOGGER = ("uvicorn.access", "uvicorn.error")


def installieren() -> None:
    """Haengt den Filter an die uvicorn-Logger (mehrfacher Aufruf harmlos)."""
    for name in UVICORN_LOGGER:
        lg = logging.getLogger(name)
        if not any(isinstance(f, ProtokollFilter) for f in lg.filters):
            lg.addFilter(ProtokollFilter())
