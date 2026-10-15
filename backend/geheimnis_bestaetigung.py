"""Erneute Anmeldung vor dem Anzeigen eines Geheimnisses (BSI M5).

BEFUND M5 (BSI-Abgleich 2026-09-29): "Geheimnis-Anzeige ohne erneute
Anmeldung". Bis dahin genuegte eine gueltige Sitzung, um ueber
``POST /api/secret/reveal`` (und die Formulare, die ihren Klartext gleich
mitluden) jedes hinterlegte Kennwort zu lesen. Wer eine Sitzung uebernimmt –
offener Rechner, geleaktes Token – konnte die Zugangsdaten damit AUSLESEN,
nicht nur benutzen (der Preis steht seit 2026-09-04 im Kopf von
``backend/secret_reveal.py``).

JETZT: vor dem ersten Abruf bestaetigt der Benutzer mit seinem Kennwort (bei
aktiver Zwei-Faktor-Anmeldung wahlweise mit dem Code). Danach ist DIESE
Sitzung fuer ``FENSTER_S`` Sekunden frei – wie sudo. Entscheidung des
Betreibers 2026-10-05: "Kennwort, 5 min".

GEBUNDEN AN DAS TOKEN, nicht an den Benutzer: eine zweite Sitzung desselben
Benutzers (anderes Geraet) ist nicht mitbestaetigt – genau die Sitzung, die
jemand uebernommen hat, soll ohne Kennwort nichts zeigen. Gespeichert wird
nur ein Hash des Tokens, im Speicher; ein Neustart verlangt eine neue
Bestaetigung (bewusst: kein Zustand auf Platte, der selbst ein Geheimnis
waere).

Die Pruefung des Kennworts selbst liegt im Endpunkt (main.py) – sie braucht
``authenticate_linux_user`` und den Anmeldeschutz (Fehlversuche zaehlen
dort mit, sonst waere dieser Endpunkt ein Weg, am Konto-Zaehler vorbei
Kennwoerter durchzuprobieren).
"""

from __future__ import annotations

import hashlib
import threading
import time

FENSTER_S = 300

_lock = threading.Lock()
_frisch: dict[str, tuple[str, float]] = {}


def _schluessel(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _aufraeumen_unlocked(jetzt: float) -> None:
    for k in [k for k, (_u, bis) in _frisch.items() if bis <= jetzt]:
        _frisch.pop(k, None)


def vermerken(token: str, user: str, jetzt: float | None = None) -> float:
    """Sitzung als frisch bestaetigt vermerken. Gibt den Ablauf zurueck."""
    if not token or not user:
        raise ValueError("token und user noetig")
    jetzt = time.time() if jetzt is None else jetzt
    bis = jetzt + FENSTER_S
    with _lock:
        _aufraeumen_unlocked(jetzt)
        _frisch[_schluessel(token)] = (str(user), bis)
    return bis


def restzeit(token: str, user: str, jetzt: float | None = None) -> int:
    """Sekunden, die diese Sitzung noch bestaetigt ist (0 = nicht/abgelaufen).

    Der Benutzer muss PASSEN: ein Token, das inzwischen fuer einen anderen
    Benutzer steht, kann es nicht geben – aber eine Verwechslung im Aufrufer
    soll nicht zu einer Freigabe werden (fail-closed).
    """
    if not token or not user:
        return 0
    jetzt = time.time() if jetzt is None else jetzt
    with _lock:
        eintrag = _frisch.get(_schluessel(token))
    if not eintrag:
        return 0
    wer, bis = eintrag
    if wer != str(user) or bis <= jetzt:
        return 0
    return max(1, int(bis - jetzt))


def ist_frisch(token: str, user: str, jetzt: float | None = None) -> bool:
    return restzeit(token, user, jetzt) > 0


def verwerfen(token: str) -> None:
    with _lock:
        _frisch.pop(_schluessel(token), None)


def _reset_fuer_tests() -> None:
    with _lock:
        _frisch.clear()


__all__ = ["FENSTER_S", "vermerken", "restzeit", "ist_frisch", "verwerfen"]
