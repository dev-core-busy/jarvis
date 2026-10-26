"""2FA-Code fuer Live-Proben – auch wenn das Geheimnis im ROOT-BROKER liegt.

WARUM (BSI-Abgleich 2026-10-26): seit eea020d3 (2026-10-20) kann ein Konto
EINEN Authenticator-Eintrag fuer Anmeldung und Root-Freigaben haben; dann
steht in ``auth_state`` nur die Marke ``"broker"``, das Geheimnis liegt
root-eigen in ``/etc/jarvis/broker-freigabe.key`` (Befund K2: das Backend darf
es nie kennen). Die Proben ``live_bsi_m5_dev`` und ``live_bsi_n_dev`` gaben die
Marke an ``pyotp`` und starben mit ``binascii.Error: Incorrect padding`` –
ohne Bilanzzeile, also von "nicht gelaufen" nicht zu unterscheiden.

Liegt das Geheimnis im Broker, fragt der Pruefling sein Relais
(``tests/live_mit_brokercode.py``, laeuft als root) ueber stdout und liest den
Code von stdin. Das Geheimnis verlaesst den root-Prozess nie; heraus kommen nur
Einmal-Codes – dasselbe, was ein Administrator in die Maske tippt.

Ohne Relais (stdin geschlossen oder keine Antwort) endet die Probe mit Exit 2
und nennt den Aufruf – ein geratener Code waere eine Messung ohne Gegenstand.
"""
import select
import sys

MARKE_IM_BROKER = "broker"
ANFRAGE = "@@BROKERCODE?@@"
WARTE_S = 120   # das Relais wartet bis zu einem Zeitschritt auf einen frischen Code


def _abbruch(grund: str) -> None:
    print("ABBRUCH (konnte nicht laufen): " + grund, flush=True)
    sys.exit(2)


def _vom_relais() -> str:
    print(ANFRAGE, flush=True)
    try:
        bereit, _, _ = select.select([sys.stdin], [], [], WARTE_S)
    except (OSError, ValueError):
        bereit = []
    zeile = sys.stdin.readline().strip() if bereit else ""
    if len(zeile) != 6 or not zeile.isdigit():
        _abbruch("das 2FA-Geheimnis liegt im Root-Broker, und es antwortet kein Relais – "
                 "Probe starten mit: python3 tests/live_mit_brokercode.py <probe>")
    return zeile


def code_quelle(geheimnis):
    """Funktion, die bei jedem Aufruf einen gueltigen, FRISCHEN Code liefert."""
    if geheimnis == MARKE_IM_BROKER:
        return _vom_relais
    import pyotp
    return lambda: pyotp.TOTP(geheimnis).now()
