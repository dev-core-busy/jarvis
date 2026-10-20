"""Nachweis fuer Root-Freigaben: ein Einmal-Code, den nur der Broker pruefen kann.

WARUM ES DAS BRAUCHT (Befund K2, BSI-Abgleich 2026-09-29): ``broker.policy_decide``
war "immer erlaubt", und ``by`` gab der Aufrufer selbst an. Der Socket gehoert
der Gruppe ``jarvis`` – jeder Prozess des Dienstbenutzers konnte sich damit einen
``shell_root``-Befehl selbst freigeben. Dafuer genuegte EIN injizierter
Shell-Befehl eines privilegierten Benutzers, kein "vollstaendig kompromittiertes
Backend", wie das README annahm.

Ein Peer-Credential-Check allein loest das NICHT: die Admin-Oberflaeche und ein
eingeschleuster Prozess laufen unter DERSELBEN uid. Unterscheidbar ist nur etwas,
das der Dienstbenutzer nicht besitzt – hier ein TOTP-Schluessel, der root-eigen
unter ``/etc/jarvis`` liegt. Der Administrator liest den Code aus seiner
Authenticator-App ab; das Backend reicht ihn nur durch.

Was das NICHT leistet (bewusst benannt): ein Backend, das in dem Moment
kompromittiert ist, in dem ein Administrator einen Code eintippt, kann diesen
EINEN Code fuer eine andere Entscheidung verwenden. Der Wiederholschutz begrenzt
das auf genau eine Entscheidung. Ohne anwesenden Administrator – der Fall einer
Prompt-Injection – gibt es keinen Code und damit keine Freigabe.

Nur Standardbibliothek: der Broker laeuft mit dem System-Python (root-eigen),
nicht mit dem venv des Dienstbenutzers.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import threading
import time
from pathlib import Path
from urllib.parse import quote

SCHLUESSEL = Path(os.environ.get("JARVIS_BROKER_FREIGABE_KEY",
                                 "/etc/jarvis/broker-freigabe.key"))
ZUSTAND = Path(os.environ.get("JARVIS_BROKER_FREIGABE_STATE",
                              "/etc/jarvis/broker-freigabe.state"))
SCHRITT_S = 30
FENSTER = 1          # +-1 Zeitschritt: Uhrabweichung des Telefons
STELLEN = 6

# ⚠ Durchprobieren (Code-Review 2026-10-07): ohne Grenze kostete ein Versuch
# drei HMACs, und je 30 s sind drei von 10^6 Codes gueltig – ein Prozess des
# Dienstbenutzers (genau der Angreifer aus K2) haette per Schleife ueber den
# Socket geraten. Nach FEHL_MAX falschen Codes gilt eine Sperre von SPERRE_S,
# in der auch ein RICHTIGER Code nicht angenommen wird; der Zaehler liegt im
# root-eigenen Zustand und ueberlebt einen Broker-Neustart.
FEHL_MAX = 5
SPERRE_S = 15 * 60

# Zwei Zwecke, EIN Schluessel (Betreiberentscheid 2026-10-20: genau ein Eintrag in
# der Authenticator-App). Die Aufteilung ist nicht kosmetisch:
#
#   * Der WIEDERHOLSCHUTZ (``letzter_schritt``) ist GEMEINSAM. Ein Code, den die
#     Anmeldung verbraucht hat, gilt fuer eine Freigabe nicht mehr – sonst waere
#     der Umbau eine Verschlechterung: bisher ging ein gueltiger Code nur bei
#     einer Freigabe durchs Backend (selten), jetzt bei jeder Anmeldung (oft),
#     und der oben benannte Rest-Angriff ("kompromittiertes Backend verwendet
#     den gerade eingetippten Code fuer etwas anderes") haette ein vielfach
#     groesseres Zeitfenster.
#   * Die FEHLVERSUCH-SPERRE ist GETRENNT, sonst legt ein fehlschlagender
#     Anmeldeversuch die Root-Freigaben fuer SPERRE_S lahm.
#     ⚠ NICHT, weil "die Anmeldemaske von aussen erreichbar" waere – das stand
#     hier zuerst und ist FALSCH: im Login-Ablauf stehen IP-Drossel,
#     Kontosperre und die KENNWORTPRUEFUNG vor dem 2FA-Zweig (nachgemessen am
#     Quelltext, in dieser Reihenfolge). Ein Fremder erreicht diese Pruefung
#     also gar nicht. Der Weg, der sie erreicht, ist der SOCKET: jeder Prozess
#     des Dienstbenutzers kann ``broker.totp_pruefen`` direkt rufen, ohne
#     Kennwort und ohne Anmeldung. Genau dafuer ist die Sperre da – und genau
#     deshalb darf sie die Freigaben nicht mitnehmen.
ZWECK_FREIGABE = "freigabe"
ZWECK_LOGIN = "login"
ZWECKE = (ZWECK_FREIGABE, ZWECK_LOGIN)

# Steht als ``totp_secret`` eines Kontos in ``data/auth_state.json``, wenn dessen
# Geheimnis HIER liegt und die Anmeldung den Broker fragt (Op
# ``broker.totp_pruefen``). Kein Geheimnis, nur ein Verweis – und bewusst ein
# Wert, der nie ein gueltiger Base32-Schluessel sein kann (Kleinbuchstaben).
MARKE_IM_BROKER = "broker"

# Pruefen und Merken des verbrauchten Schritts sind EIN Vorgang: der Broker
# behandelt Anfragen parallel (asyncio.to_thread), ohne Sperre gingen zwei
# gleichzeitige Anfragen mit demselben Code beide durch.
_SPERRE = threading.Lock()


def _vertrauenswuerdig(p: Path) -> bool:
    """Datei gehoert root und ist fuer niemanden sonst les- oder schreibbar.

    Fail-closed: liegt der Schluessel mit falschen Rechten da, koennte ihn der
    Dienstbenutzer kennen oder ersetzen – dann ist er kein Nachweis mehr.
    Laeuft der Prozess nicht als root (Tests), wird der EIGENE Benutzer
    verlangt.
    """
    try:
        st = p.stat()
    except OSError:
        return False
    erwartet = 0 if os.geteuid() == 0 else os.geteuid()
    return st.st_uid == erwartet and (st.st_mode & 0o077) == 0


def eingerichtet() -> bool:
    return _lade() is not None


def _lade() -> bytes | None:
    if not _vertrauenswuerdig(SCHLUESSEL):
        return None
    try:
        roh = SCHLUESSEL.read_text(encoding="ascii").strip().upper()
        schluessel = base64.b32decode(roh + "=" * (-len(roh) % 8))
    except Exception:  # noqa: BLE001
        return None
    return schluessel if len(schluessel) >= 16 else None


def _code(schluessel: bytes, zaehler: int) -> str:
    """RFC 4226 (HOTP) – TOTP ist HOTP ueber den Zeitschritt (RFC 6238)."""
    mac = hmac.new(schluessel, struct.pack(">Q", zaehler), hashlib.sha1).digest()
    ofs = mac[-1] & 0x0F
    wert = struct.unpack(">I", mac[ofs:ofs + 4])[0] & 0x7FFFFFFF
    return str(wert % (10 ** STELLEN)).zfill(STELLEN)


def _leerer_zustand() -> dict:
    z = {"letzter_schritt": 0}
    for zweck in ZWECKE:
        z[f"fehl_{zweck}"] = 0
        z[f"gesperrt_bis_{zweck}"] = 0.0
    return z


def _zustand() -> dict:
    """``{letzter_schritt, fehl_<zweck>, gesperrt_bis_<zweck>}`` – fehlend/unlesbar: Nullwerte.

    ALTBESTAND: vor der Login-Pruefung hiessen die Felder ``fehl`` und
    ``gesperrt_bis`` ohne Zweck und zaehlten fuer Freigaben. Sie gelten weiter –
    eine laufende Sperre darf ein Deploy nicht aufheben.
    """
    try:
        if _vertrauenswuerdig(ZUSTAND):
            roh = json.loads(ZUSTAND.read_text())
            z = _leerer_zustand()
            z["letzter_schritt"] = int(roh.get("letzter_schritt", 0))
            for zweck in ZWECKE:
                alt_f = roh.get("fehl", 0) if zweck == ZWECK_FREIGABE else 0
                alt_g = roh.get("gesperrt_bis", 0) if zweck == ZWECK_FREIGABE else 0
                z[f"fehl_{zweck}"] = int(roh.get(f"fehl_{zweck}", alt_f))
                z[f"gesperrt_bis_{zweck}"] = float(roh.get(f"gesperrt_bis_{zweck}", alt_g))
            return z
    except Exception:  # noqa: BLE001
        pass
    return _leerer_zustand()


def _letzter_schritt() -> int:
    return _zustand()["letzter_schritt"]


def _schreibe_privat(p: Path, inhalt: str) -> None:
    """Atomar, 0600 VOR dem Umbenennen – kein Moment mit weiteren Rechten."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, inhalt.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def pruefen(code, jetzt: float | None = None,
            zweck: str = ZWECK_FREIGABE) -> tuple[bool, str]:
    """(gueltig?, Grund). Jeder Code gilt genau EINMAL – ueber BEIDE Zwecke hinweg
    (gemeinsamer ``letzter_schritt``); nach FEHL_MAX falschen Codes ist fuer
    SPERRE_S jede Pruefung DIESES Zwecks "gesperrt" (getrennte Zaehler)."""
    if zweck not in ZWECKE:
        # Kein ratbarer Zweck: ein Tippfehler darf keine Pruefung ohne Sperre erzeugen.
        return False, "nachweis_falsch"
    schluessel = _lade()
    if schluessel is None:
        return False, "nicht_eingerichtet"
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != STELLEN:
        return False, "nachweis_fehlt"
    t = time.time() if jetzt is None else jetzt
    with _SPERRE:
        z = _zustand()
        if z[f"gesperrt_bis_{zweck}"] > t:
            return False, "gesperrt"
        schritt = int(t // SCHRITT_S)
        for d in range(-FENSTER, FENSTER + 1):
            s = schritt + d
            if hmac.compare_digest(_code(schluessel, s), code):
                if s <= z["letzter_schritt"]:
                    return False, "nachweis_verbraucht"
                z["letzter_schritt"] = s
                z[f"fehl_{zweck}"] = 0
                z[f"gesperrt_bis_{zweck}"] = 0
                _schreibe_privat(ZUSTAND, json.dumps(z))
                return True, "ok"
        fehl = z[f"fehl_{zweck}"] + 1
        gesperrt_bis = t + SPERRE_S if fehl >= FEHL_MAX else 0
        z[f"fehl_{zweck}"] = 0 if gesperrt_bis else fehl
        z[f"gesperrt_bis_{zweck}"] = gesperrt_bis
        _schreibe_privat(ZUSTAND, json.dumps(z))
        if gesperrt_bis:
            print(f"[Broker] Code {FEHL_MAX}x falsch ({zweck}) – {zweck} fuer "
                  f"{SPERRE_S // 60} Minuten gesperrt", flush=True)
        return False, "nachweis_falsch"


def uebernehmen(b32: str, jetzt: float | None = None) -> str:
    """Einen BESTEHENDEN Base32-Schluessel uebernehmen (z. B. das vorhandene
    2FA-Geheimnis eines Kontos), damit genau EIN Eintrag in der
    Authenticator-App noetig ist. Rueckgabe: der normalisierte Schluessel.

    Der laufende Zeitschritt gilt danach als VERBRAUCHT: wer das Geheimnis
    gerade noch fuer eine Anmeldung benutzt hat, soll denselben Code nicht
    unmittelbar danach fuer eine Freigabe verwenden koennen – der bisherige
    Wiederholschutz der Anmeldung (``data/totp_schritte.json``) zaehlt hier
    nicht mit.
    """
    roh = "".join(str(b32 or "").split()).upper()
    try:
        schluessel = base64.b32decode(roh + "=" * (-len(roh) % 8))
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"kein gueltiger Base32-Schluessel: {e}") from e
    if len(schluessel) < 16:
        raise ValueError(f"Schluessel zu kurz ({len(schluessel)} Byte, mindestens 16)")
    t = time.time() if jetzt is None else jetzt
    _schreibe_privat(SCHLUESSEL, roh + "\n")
    z = _leerer_zustand()
    z["letzter_schritt"] = int(t // SCHRITT_S)
    _schreibe_privat(ZUSTAND, json.dumps(z))
    return roh


def einrichten(konto: str = "root-freigaben") -> tuple[str, str]:
    """Neuen Schluessel erzeugen (ersetzt den alten). Rueckgabe: (Base32, otpauth-URI)."""
    roh = secrets.token_bytes(20)
    b32 = base64.b32encode(roh).decode("ascii").rstrip("=")
    _schreibe_privat(SCHLUESSEL, b32 + "\n")
    _schreibe_privat(ZUSTAND, json.dumps(_leerer_zustand()))
    try:
        import socket
        host = socket.gethostname()
    except Exception:  # noqa: BLE001
        host = "jarvis"
    uri = (f"otpauth://totp/{quote('Jarvis-Root ' + host)}:{quote(konto)}"
           f"?secret={b32}&issuer={quote('Jarvis-Root ' + host)}&digits={STELLEN}&period={SCHRITT_S}")
    return b32, uri


# Klartext zu den Gruenden – fuer die Oberflaeche und die root-Konsole.
MELDUNG = {
    "nicht_eingerichtet": (
        "Freigaben über die Oberfläche sind erst möglich, wenn auf dem Server ein "
        "Freigabe-Code eingerichtet ist. Als root: jarvis-broker-admin "
        "totp-einrichten – oder die Freigabe direkt dort erteilen: "
        "jarvis-broker-admin erlauben <Eintrag>"),
    "nachweis_fehlt": "Bitte den 6-stelligen Freigabe-Code eingeben.",
    "nachweis_falsch": "Der Freigabe-Code ist falsch oder abgelaufen.",
    "nachweis_verbraucht": "Dieser Freigabe-Code wurde schon verwendet – bitte den nächsten abwarten.",
    "gesperrt": (
        f"Zu viele falsche Freigabe-Codes – Freigaben sind für {SPERRE_S // 60} Minuten "
        "gesperrt. Direkt auf dem Server geht es weiter: jarvis-broker-admin erlauben <Eintrag>"),
}
