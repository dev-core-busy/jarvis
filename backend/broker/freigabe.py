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


def _zustand() -> dict:
    """``{letzter_schritt, fehl, gesperrt_bis}`` – fehlend/unlesbar: Nullwerte."""
    try:
        if _vertrauenswuerdig(ZUSTAND):
            roh = json.loads(ZUSTAND.read_text())
            return {"letzter_schritt": int(roh.get("letzter_schritt", 0)),
                    "fehl": int(roh.get("fehl", 0)),
                    "gesperrt_bis": float(roh.get("gesperrt_bis", 0))}
    except Exception:  # noqa: BLE001
        pass
    return {"letzter_schritt": 0, "fehl": 0, "gesperrt_bis": 0.0}


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


def pruefen(code, jetzt: float | None = None) -> tuple[bool, str]:
    """(gueltig?, Grund). Jeder Code gilt genau EINMAL (Wiederholschutz);
    nach FEHL_MAX falschen Codes ist fuer SPERRE_S jede Pruefung "gesperrt"."""
    schluessel = _lade()
    if schluessel is None:
        return False, "nicht_eingerichtet"
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != STELLEN:
        return False, "nachweis_fehlt"
    t = time.time() if jetzt is None else jetzt
    with _SPERRE:
        z = _zustand()
        if z["gesperrt_bis"] > t:
            return False, "gesperrt"
        schritt = int(t // SCHRITT_S)
        for d in range(-FENSTER, FENSTER + 1):
            s = schritt + d
            if hmac.compare_digest(_code(schluessel, s), code):
                if s <= z["letzter_schritt"]:
                    return False, "nachweis_verbraucht"
                _schreibe_privat(ZUSTAND, json.dumps(
                    {"letzter_schritt": s, "fehl": 0, "gesperrt_bis": 0}))
                return True, "ok"
        fehl = z["fehl"] + 1
        gesperrt_bis = t + SPERRE_S if fehl >= FEHL_MAX else 0
        _schreibe_privat(ZUSTAND, json.dumps(
            {"letzter_schritt": z["letzter_schritt"],
             "fehl": 0 if gesperrt_bis else fehl, "gesperrt_bis": gesperrt_bis}))
        if gesperrt_bis:
            print(f"[Broker] Freigabe-Code {FEHL_MAX}x falsch – Freigaben fuer "
                  f"{SPERRE_S // 60} Minuten gesperrt", flush=True)
        return False, "nachweis_falsch"


def einrichten(konto: str = "root-freigaben") -> tuple[str, str]:
    """Neuen Schluessel erzeugen (ersetzt den alten). Rueckgabe: (Base32, otpauth-URI)."""
    roh = secrets.token_bytes(20)
    b32 = base64.b32encode(roh).decode("ascii").rstrip("=")
    _schreibe_privat(SCHLUESSEL, b32 + "\n")
    _schreibe_privat(ZUSTAND, json.dumps({"letzter_schritt": 0}))
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
