"""Wer darf die Werkzeuge eines MCP-Servers benutzen – und mit welchem Schluessel.

Zwei Fragen, die in ``mcp_client`` (Verbindung) und ``agent`` (Dispatch)
gebraucht werden und deshalb EINE Quelle haben:

1. **Freigabe je Server** – dieselbe Regel wie SAP, VEMAS, E-Mail und die
   anderen Bereiche unter Einstellungen -> Berechtigungen (Festlegung des
   Betreibers 2026-10-25):

   * ``allowed_users`` – Logins, kommagetrennt (wie ``sap_allowed_users``),
   * ``allowed_group`` – Gruppen-DNs, zeilengetrennt (DNs enthalten Kommas),
   * ODER-verknuepft; **leer = niemand, ausdruecklich auch kein
     Administrator** (kein Admin-Bypass).

   Das fruehere Feld ``allow_network_users`` ("alle Netzwerk-Benutzer") hat
   KEINE Wirkung mehr – eine Stufe "alle" gibt es bei keiner anderen Freigabe,
   und "nur Administratoren" widersprach "leer = niemand".

2. **API-Schluessel** fuer HTTP-Transporte: ``api_key`` (geheimer Name, also
   von ``geheimnis_tresor`` auf der Platte verpackt) und ``api_key_header``.
   Leer oder ``Authorization`` -> ``Authorization: Bearer <key>``; jeder andere
   Name traegt den Schluessel unveraendert (z.B. ``X-API-Key``).

Die Freigabe wird bei JEDEM Aufruf aus der aktuellen Konfiguration gelesen,
nicht beim Bau des Werkzeugs: sonst wirkte eine geaenderte Liste erst nach dem
naechsten Neuverbinden.
"""
from __future__ import annotations

import re

# Ein Header-Name nach RFC 7230 ("token"). Alles andere wuerde httpx ablehnen –
# oder schlimmer: ein Zeilenumbruch im Namen waere eine Header-Injektion.
_HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")


def norm_login(name: str) -> str:
    """Gleiche Regel wie ``main._norm_login`` (Domain-Praefix, UPN-Suffix, klein).

    Hier als Kopie, weil dieses Modul ohne ``backend.main`` laufen muss (Tests,
    Import-Reihenfolge). Die Gegenprobe vergleicht beide Fassungen.
    """
    return (name or "").split("@")[0].split("\\")[-1].strip().lower()


def benutzer_liste(raw) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def gruppen_liste(raw) -> list[str]:
    return [x.strip() for x in str(raw or "").splitlines() if x.strip()]


def freigabe_art(srv: dict | None) -> str:
    """``"auswahl"`` | ``"keine"`` – fuer Anzeige und Pruefung."""
    if not srv:
        return "keine"
    if benutzer_liste(srv.get("allowed_users")) or gruppen_liste(srv.get("allowed_group")):
        return "auswahl"
    return "keine"


def altschalter_ohne_freigabe(servers) -> list:
    """Namen der Server, die NUR noch den alten Schalter "alle Netzwerk-Benutzer"
    tragen und keine Benutzer/Gruppen – fuer sie gilt jetzt "niemand".

    Fuer eine Journalzeile beim Start (Code-Review 2026-10-25): die Regel
    "leer = niemand" ist gewollt, aber ein Server, der gestern fuer alle offen
    war und heute fuer keinen, darf nicht STILL verstummen.
    """
    return [str(s.get("name") or s.get("id") or "?") for s in (servers or [])
            if isinstance(s, dict) and s.get("allow_network_users") is True
            and freigabe_art(s) == "keine"]


def darf_benutzen(srv: dict | None, benutzer: str, gruppen_dns=None,
                  gruppe_passt=None) -> bool:
    """Darf dieser Benutzer die Werkzeuge des Servers aufrufen? (auch Admins!)

    ``gruppen_dns``/``gruppe_passt`` sind fuer Tests einsetzbar; ohne sie wird
    der Gruppen-Cache aus ``backend.main`` benutzt – derselbe, mit dem SAP,
    E-Mail & Co. ihre Gruppen pruefen. Fail-closed: jeder Fehler heisst nein.
    """
    try:
        if freigabe_art(srv) == "keine":
            return False
        plain = norm_login(benutzer)
        if not plain:
            return False
        if plain in {norm_login(x) for x in benutzer_liste(srv.get("allowed_users"))}:
            return True
        gruppen = "\n".join(gruppen_liste(srv.get("allowed_group")))
        if not gruppen:
            return False
        if gruppe_passt is not None:
            return bool(gruppe_passt(gruppen_dns or [], gruppen))
        from backend.main import _member_of_any_group, _user_group_dns_cache
        dns = gruppen_dns if gruppen_dns is not None else _user_group_dns_cache.get(plain, [])
        return bool(_member_of_any_group(dns, gruppen))
    except Exception as e:  # noqa: BLE001
        print(f"[MCP] Freigabepruefung fehlgeschlagen – verweigert: {e}", flush=True)
        return False


def freigabe_normalisieren(data: dict) -> dict:
    """Nur die gesendeten Freigabefelder, normalisiert (fuer add/update)."""
    aus: dict = {}
    if "allowed_users" in data:
        aus["allowed_users"] = ", ".join(benutzer_liste(data["allowed_users"]))
    if "allowed_group" in data:
        aus["allowed_group"] = "\n".join(gruppen_liste(data["allowed_group"]))
    return aus


def header_name_gueltig(name) -> bool:
    n = str(name or "").strip()
    return n == "" or bool(_HEADER_NAME.match(n))


def auth_header(srv: dict | None) -> dict:
    """``{Name: Wert}`` fuer den API-Schluessel – oder ``{}`` ohne Schluessel."""
    if not srv:
        return {}
    key = str(srv.get("api_key") or "").strip()
    if not key:
        return {}
    name = str(srv.get("api_key_header") or "").strip() or "Authorization"
    if not _HEADER_NAME.match(name):
        # Ein unbrauchbarer Name kommt nur aus einer handbearbeiteten
        # settings.json – lieber laut scheitern als den Schluessel unter einem
        # Namen schicken, den niemand eingetragen hat.
        raise ValueError(f"Ungueltiger Header-Name fuer den API-Schluessel: {name!r}")
    if "\r" in key or "\n" in key:
        raise ValueError("Der API-Schluessel enthaelt einen Zeilenumbruch.")
    if name.lower() == "authorization" and " " not in key:
        key = "Bearer " + key
    return {name: key}


def _ziel(srv: dict) -> tuple:
    """Wohin die Geheimnisse eines Servers gehen: Transport, Adresse (der
    API-Schluessel), Befehl und Argumente (die Umgebung des stdio-Prozesses).
    Normiert wie das Formular speichert – Rand-Leerzeichen und ein
    abschliessender Schraegstrich sind keine Zielaenderung."""
    args = srv.get("args")
    if not isinstance(args, (list, tuple)):
        args = [args] if args else []
    return (str(srv.get("transport") or "stdio").strip().lower(),
            str(srv.get("url") or "").strip().rstrip("/"),
            str(srv.get("command") or "").strip(),
            tuple(str(a).strip() for a in args))


def geheimnis_umleitung(srv: dict | None, data: dict) -> list[str]:
    """Wuerde dieses Speichern ein GESPEICHERTES Geheimnis an ein neues Ziel
    schicken? Rueckgabe: die Namen der Felder, die neu einzugeben sind
    (leer = nichts zu beanstanden).

    Code-Review 2026-11-01: ``config.update_mcp_server`` behaelt einen nicht
    gesendeten ``api_key`` und eine nicht gesendete ``env`` ("leer lassen =
    unveraendert") – auch wenn im selben Speichern ``url`` oder ``command``
    wechseln. Der naechste Verbindungsaufbau schickte den Schluessel dann an
    eine frei gewaehlte Adresse bzw. gab GITHUB_TOKEN & Co. einem frei
    gewaehlten Programm, ohne dass ihn je jemand eingegeben oder per Auge
    aufgedeckt hat (BSI M5). Dieselbe Regel wie ``main._profil_umleitung``
    fuer LLM-Profile und das Register ("ein Ersatzwert ist ein
    Exfiltrationsweg, sobald die Zieladresse frei waehlbar bleibt").

    Bewusst ueber ALLE Zielfelder statt je Transport: ein Wechsel des
    Transports macht ein bisher ungenutztes Geheimnis wirksam (Umgebung eines
    HTTP-Servers -> stdio), und eine Rueckfrage zu viel kostet nur eine
    Eingabe.
    """
    if not srv or not isinstance(data, dict):
        return []
    neu = dict(srv)
    for k in ("transport", "url", "command", "args"):
        if k in data:
            neu[k] = data[k]
    if _ziel(neu) == _ziel(srv):
        return []
    behalten = []
    if "api_key" not in data and str(srv.get("api_key") or "").strip():
        behalten.append("api_key")
    if "env" not in data and srv.get("env"):
        behalten.append("env")
    return behalten


def ohne_geheimnisse(srv: dict) -> dict:
    """Server-Eintrag fuer eine API-Antwort – der Schluessel verlaesst das
    Backend nie, nur ob einer hinterlegt ist."""
    aus = {k: v for k, v in (srv or {}).items() if k != "api_key"}
    aus["api_key_gesetzt"] = bool(str((srv or {}).get("api_key") or "").strip())
    return aus
