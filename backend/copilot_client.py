"""Microsoft 365 Copilot als Recherche-Dienst (Graph Chat API, Preview).

WAS DAS IST
-----------
Ein Zugang zur **Microsoft 365 Copilot Chat API**, damit ein Jarvis-Lauf eine
Frage an Copilot stellen kann und eine Antwort MIT QUELLEN zurueckbekommt.
Copilot groundet dabei standardmaessig im Web (Bing) und im Mandanten-Bestand.

    POST /beta/copilot/conversations            -> Unterhaltung anlegen
    POST /beta/copilot/conversations/{id}/chat  -> Frage stellen

WARUM DELEGIERT UND NICHT MIT EINEM DIENSTKONTO
-----------------------------------------------
Microsoft unterstuetzt fuer diese API **ausschliesslich delegierte Rechte mit
einem Arbeits-/Schulkonto** ("Application: Not supported", Learn-Doku, Stand
2026-11). Es gibt also kein Dienstkonto, keinen Cron-Lauf und keinen
WhatsApp-Weg – jede Recherche laeuft unter dem Microsoft-Konto eines
ANWESENDEN, lizenzierten Benutzers. Das ist keine Entscheidung dieses Moduls,
sondern die Grenze der Schnittstelle; sie ist gleichzeitig die wirksamste
Schranke gegen eine unbeobachtete Recherche.

Dazu verlangt die API **alle sieben** Graph-Berechtigungen aus ``SCOPES`` –
darunter ``Mail.Read`` und ``Sites.Read.All``. Das ist der Preis, und er ist
hoch: die Consent-Flaeche dieser App reicht weiter als die Recherche. Deshalb
gehoert sie in eine EIGENE Anwendungsregistrierung, nicht an den SSO-Pfad des
Outlook-Add-ins (``backend/addin_sso.py``).

WARUM DEVICE CODE FLOW
----------------------
Jarvis-Benutzer melden sich an einem Verzeichnis im Haus an (AD/LDAP), nicht an
Entra – es gibt im Lauf also kein Microsoft-Token. Der Device Code Flow ist der
Weg, der dafuer ohne Rueckleit-Adresse und ohne Client-Geheimnis auskommt:
derselbe Mechanismus, den ``backend/google_auth.py`` seit Langem benutzt. Die
App ist ein **oeffentlicher Client** ("Allow public client flows"), es gibt
also kein ``client_secret``, das gestohlen werden koennte.

Gespeichert wird je Benutzer nur das **Refresh-Token** (``data/copilot_auth``,
0600, in allen vier Sperrlisten der Sandbox – siehe ``backend/sandbox.py``).
Wer es liest, handelt als dieser Benutzer gegen dessen Postfach und SharePoint;
es ist damit dieselbe Klasse wie ``data/google_auth``.

WAS DIESES MODUL NICHT TUT
--------------------------
* **Es entschaerft den Antworttext NICHT.** Das macht ``backend/werkzeug_rahmen``
  zentral fuer JEDES Werkzeugergebnis (BSI H8). Eine zweite Entschaerfung hier
  waere die Dopplung, an der jede Gegenprobe stumm wird (Register).
* **Es prueft keine Freigabe.** Die Internet-Freigabe gehoert an die Stelle, die
  den Auftraggeber kennt – das Werkzeug in ``skills/copilot/main.py``.
* Es kennt die Rechtelage nicht und stellt keine Jarvis-Sitzung aus.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from backend import atomar as _atomar

# ── Wer recherchiert? ───────────────────────────────────────────────────────
# Gleiche Mechanik wie ``mail_accounts.current_mail_user``: ``agent.py::
# _execute_tool`` setzt den Actor-Namen je Aufruf.
#
# BEWUSST NICHT ``sandbox.tool_user()`` – der ist fuer privilegierte Benutzer
# absichtlich LEER ("keine Einschraenkung"). Ein Microsoft-Konto ist aber keine
# Rechtefrage, sondern eine Personenfrage: mit ``tool_user()`` haetten
# Administratoren gar keine Copilot-Verbindung (dieselbe Lehre wie beim
# Postfach). Und der Benutzer darf NIEMALS ein Werkzeug-Argument sein – sonst
# koennte das Modell waehlen, mit wessen Microsoft-Konto und damit mit wessen
# Postfach-Zugriff es recherchiert.
current_copilot_user: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_copilot_user", default="")

_DATA = Path(__file__).resolve().parent.parent / "data" / "copilot_auth"
# EINE Datei mit FESTEM Namen, Benutzer als Schluessel – nicht eine Datei je
# Benutzer. Zwei Gruende, beide aus dem Register:
#   * Nur ein fester Name laesst sich in ``PRIVATE_FILES_STRENG`` eintragen
#     (0600). Diese Liste kennt keine Globs, und ein Hash-Dateiname waere
#     damit von ``harden_data_dirs`` nicht erfasst – die Datei haette nur den
#     Modus, den der schreibende Prozess ihr gerade gegeben hat.
#   * Ein Verzeichnis, dessen Dateinamen die Benutzer nennen, verraet die
#     Benutzerliste an jeden, der es auflisten darf (``support_instructions``,
#     ECHT 2026-10-22). Hier nennt es nur eine Datei.
# Das VERZEICHNIS ist trotzdem gesperrt, nicht nur die Datei: eine kuenftige
# zweite Datei ist damit von sich aus erfasst (Lehre aus ``data/google_auth``,
# wo die Sperrliste die zweite Datei desselben Zwecks nicht kannte).
_DATEI = _DATA / "tokens.json"

# Verzeichnis 0750 wie die uebrigen PRIVATE_DIRS (die Sandbox-Konten sind
# NICHT in der Dienstgruppe – das ist die Schranke), Datei 0600.
_DIR_MODUS = 0o750
_DATEI_MODUS = 0o600

ANMELDUNG = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/beta"

# Alle sieben sind PFLICHT – die Doku sagt woertlich "You need all of these
# Microsoft Graph permissions to successfully call the Microsoft 365 Copilot
# Chat API". Ein fehlender Eintrag ergibt kein eingeschraenktes Ergebnis,
# sondern einen Fehlschlag; deshalb steht die Liste hier vollstaendig und wird
# vom Waechter gegen die Doku-Liste gehalten.
SCOPES = (
    "Sites.Read.All",
    "Mail.Read",
    "People.Read.All",
    "OnlineMeetingTranscript.Read.All",
    "Chat.Read",
    "ChannelMessage.Read.All",
    "ExternalItem.Read.All",
)
# offline_access liefert das Refresh-Token, ohne das jede Recherche eine neue
# Geraete-Anmeldung braeuchte.
_ZUSATZ_SCOPES = ("offline_access",)

NETZ_ZEITDECKEL_S = 30
# Die Chat API vertraegt keine langlaufenden Aufgaben ("prone to gateway
# timeouts", Learn). Ein eigener Deckel darunter macht aus dem Gateway-Fehler
# eine Meldung mit Grund.
CHAT_ZEITDECKEL_S = 110

# Ein Token gilt rund eine Stunde; 120 s Vorlauf gegen Uhrenversatz.
_VORLAUF_S = 120

_schreibsperre = threading.RLock()


class CopilotFehler(Exception):
    """Etwas an der Einrichtung oder am Zugang stimmt nicht – mit Klartext.

    ``grund`` ist eine maschinell auswertbare Kennung, damit ein Aufrufer die
    Faelle unterscheiden kann, ohne Meldungstexte zu vergleichen (ein Waechter,
    der Texte vergleicht, bricht beim ersten Umformulieren – Register).
    """

    def __init__(self, text: str, grund: str = "fehler"):
        super().__init__(text)
        self.grund = grund


# ── Einrichtung aus der Skill-Konfiguration ─────────────────────────────────
def einrichtung() -> dict:
    """``{"tenant_id": …, "client_id": …}`` aus der Skill-Konfiguration.

    FUNKTION, kein Modulwert: die Werte sind im Einstellungen-Reiter aenderbar
    und muessen ohne Dienstneustart greifen (Register, ``addin.ordner_pfad``).
    Beide Werte sind KEINE Geheimnisse (eine Client-ID eines oeffentlichen
    Clients ist oeffentlich), aber Echtwerte – sie gehoeren deshalb in die
    Konfiguration und nicht ins Repo.
    """
    try:
        from backend.config import config  # noqa: PLC0415
        st = config.get_skill_states().get("copilot", {}) or {}
        cfg = st.get("config", {}) or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    return {
        "tenant_id": str(cfg.get("copilot_tenant_id") or "").strip(),
        "client_id": str(cfg.get("copilot_client_id") or "").strip(),
    }


def eingerichtet() -> bool:
    e = einrichtung()
    return bool(e["tenant_id"] and e["client_id"])


def _scope_string() -> str:
    return " ".join([f"https://graph.microsoft.com/{s}" for s in SCOPES]
                    + list(_ZUSATZ_SCOPES))


# ── Token-Ablage je Benutzer ────────────────────────────────────────────────
def _kennung(benutzer: str) -> str:
    """Stabile Dateikennung aus dem Benutzernamen.

    NICHT der Benutzername als Dateiname: ein Verzeichnis, dessen Dateinamen
    die Benutzer nennen, verraet die Benutzerliste an jeden, der es auflisten
    darf – derselbe Befund wie bei ``data/support_instructions`` (ECHT
    2026-10-22). Der Hash ist hier ausreichend, weil niemand von der Kennung
    auf den Namen zurueckrechnen MUSS.
    """
    norm = (benutzer or "").strip().lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _alle() -> dict:
    try:
        if not _DATEI.exists():
            return {}
        d = json.loads(_DATEI.read_text("utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception as e:  # noqa: BLE001
        print(f"[Copilot] Token-Ablage nicht lesbar: {e}", flush=True)
        return {}


def _lade(benutzer: str) -> dict:
    e = _alle().get(_kennung(benutzer))
    return e if isinstance(e, dict) else {}


def _sichere(benutzer: str, daten: dict | None) -> None:
    """Eintrag schreiben (``None`` entfernt ihn) – unter einer Sperre.

    Die Sperre ordnet die Schreibzugriffe EINES Prozesses: zwei Benutzer
    koennen sich gleichzeitig verbinden, und ein Lesen-Aendern-Schreiben ohne
    Sperre verliert dann den jeweils anderen Eintrag.
    """
    with _schreibsperre:
        _DATA.mkdir(parents=True, exist_ok=True)
        try:
            if (_DATA.stat().st_mode & 0o777) != _DIR_MODUS:
                _DATA.chmod(_DIR_MODUS)
        except OSError:
            pass
        alle = _alle()
        k = _kennung(benutzer)
        if daten is None:
            alle.pop(k, None)
        else:
            alle[k] = daten
        # Der Modus wird MITGEGEBEN, nicht danach gesetzt: ``atomar.schreiben``
        # legt die Zieldatei neu an, und zwischen Anlegen und einem
        # nachtraeglichen chmod laege das Refresh-Token offen da.
        _atomar.schreiben(_DATEI, alle, modus=_DATEI_MODUS)


def verbunden(benutzer: str) -> bool:
    return bool(_lade(benutzer).get("refresh_token"))


def konto(benutzer: str) -> str:
    """Das verbundene Microsoft-Konto (fuer die Anzeige) oder ``""``."""
    return str(_lade(benutzer).get("upn") or "")


def trennen(benutzer: str) -> bool:
    """Verbindung loesen – der Eintrag wird ENTFERNT, nicht geleert.

    Ein leerer Eintrag waere von "nie verbunden" nicht zu unterscheiden und
    liesse die Oberflaeche einen Zustand behaupten, den sie nicht kennt.
    """
    if not _lade(benutzer):
        return False
    try:
        _sichere(benutzer, None)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[Copilot] Trennen fehlgeschlagen: {e}", flush=True)
        return False


# ── Geraete-Anmeldung (Device Code Flow) ────────────────────────────────────
# Der laufende Vorgang je Benutzer, nur im Speicher: ein Geraete-Code ist
# Sekunden bis Minuten gueltig und hat auf der Platte nichts zu suchen.
_laeuft: dict[str, dict] = {}


async def geraet_start(benutzer: str) -> dict:
    """Startet die Geraete-Anmeldung; Rueckgabe fuer die Anzeige."""
    e = einrichtung()
    if not (e["tenant_id"] and e["client_id"]):
        raise CopilotFehler(
            "Microsoft 365 Copilot ist nicht eingerichtet: Mandanten-Kennung "
            "und Anwendungs-Kennung fehlen (Einstellungen -> Copilot).",
            "nicht_eingerichtet")
    url = f"{ANMELDUNG}/{e['tenant_id']}/oauth2/v2.0/devicecode"
    async with httpx.AsyncClient(timeout=NETZ_ZEITDECKEL_S) as c:
        r = await c.post(url, data={"client_id": e["client_id"],
                                    "scope": _scope_string()})
    if not r.is_success:
        raise CopilotFehler(_fehlertext(r, "Geraete-Anmeldung"), "anmeldung")
    d = r.json()
    _laeuft[_kennung(benutzer)] = {
        "device_code": d.get("device_code", ""),
        "interval": int(d.get("interval") or 5),
        "ablauf": time.time() + int(d.get("expires_in") or 900),
        "naechster": 0.0,
    }
    return {
        "user_code": d.get("user_code", ""),
        "verification_url": d.get("verification_uri")
                            or d.get("verification_url", ""),
        "expires_in": int(d.get("expires_in") or 900),
    }


async def geraet_status(benutzer: str) -> dict:
    """Fragt EINMAL nach, ob die Anmeldung bestaetigt wurde.

    Bewusst ohne Hintergrund-Aufgabe: ein Poller, der 15 Minuten laeuft,
    uebersteht keinen Dienstneustart und muss seinen Zustand doch wieder
    herstellen. Hier fragt der Aufrufer im Takt ``interval`` – das ist
    derselbe Takt, den Microsoft vorgibt, und der Zustand liegt nur im
    Speicher des Vorgangs.
    """
    k = _kennung(benutzer)
    vorgang = _laeuft.get(k)
    if not vorgang:
        return {"status": "idle"}
    if time.time() > vorgang["ablauf"]:
        _laeuft.pop(k, None)
        return {"status": "expired",
                "message": "Die Geraete-Anmeldung ist abgelaufen. Bitte neu starten."}
    # Microsoft weist zu haeufiges Fragen mit slow_down ab; den Takt einhalten.
    if time.time() < vorgang["naechster"]:
        return {"status": "pending"}
    vorgang["naechster"] = time.time() + vorgang["interval"]

    e = einrichtung()
    url = f"{ANMELDUNG}/{e['tenant_id']}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=NETZ_ZEITDECKEL_S) as c:
        r = await c.post(url, data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": e["client_id"],
            "device_code": vorgang["device_code"],
        })
    d: dict[str, Any] = {}
    try:
        d = r.json() or {}
    except Exception:  # noqa: BLE001
        pass
    if r.is_success and d.get("refresh_token"):
        _speichere_token(benutzer, d)
        _laeuft.pop(k, None)
        return {"status": "authorized", "konto": konto(benutzer)}
    fehler = str(d.get("error") or "")
    if fehler in ("authorization_pending", "slow_down"):
        if fehler == "slow_down":
            vorgang["interval"] += 5
        return {"status": "pending"}
    _laeuft.pop(k, None)
    if fehler in ("expired_token", "code_expired"):
        return {"status": "expired",
                "message": "Die Geraete-Anmeldung ist abgelaufen. Bitte neu starten."}
    return {"status": "error",
            "message": str(d.get("error_description") or fehler
                           or f"HTTP {r.status_code}")}


def _speichere_token(benutzer: str, d: dict) -> None:
    alt = _lade(benutzer)
    _sichere(benutzer, {
        "refresh_token": d.get("refresh_token") or alt.get("refresh_token", ""),
        "access_token": d.get("access_token", ""),
        # Ablauf absolut, nicht relativ: ein relativer Wert ist nach einem
        # Dienstneustart nicht mehr deutbar.
        "gueltig_bis": time.time() + int(d.get("expires_in") or 3600),
        "upn": _upn_aus_token(d.get("id_token") or d.get("access_token") or "")
               or alt.get("upn", ""),
    })


def _upn_aus_token(jwt: str) -> str:
    """Der Kontoname aus dem Token – NUR fuer die Anzeige.

    Die Nutzlast wird NICHT geprueft und traegt hier keine Entscheidung: das
    Token kommt aus der direkten Antwort des Anmeldedienstes, und ob es gilt,
    beantwortet Graph beim ersten Aufruf. Ein halb nachgebauter JWT-Pruefer
    waere die Art Abkuerzung, die spaeter als Luecke auffaellt
    (``addin_sso.py`` prueft, weil dort das Token vom CLIENT kommt).
    """
    import base64  # noqa: PLC0415
    try:
        teil = jwt.split(".")[1]
        teil += "=" * (-len(teil) % 4)
        nutz = json.loads(base64.urlsafe_b64decode(teil).decode("utf-8"))
        return str(nutz.get("upn") or nutz.get("preferred_username") or "")
    except Exception:  # noqa: BLE001
        return ""


# ── Zugriffstoken ───────────────────────────────────────────────────────────
async def _zugriffstoken(benutzer: str) -> str:
    daten = _lade(benutzer)
    refresh = daten.get("refresh_token")
    if not refresh:
        raise CopilotFehler(
            "Dieses Konto ist nicht mit Microsoft 365 Copilot verbunden. "
            "Einmalig verbinden: Einstellungen -> Copilot -> Verbinden.",
            "nicht_verbunden")
    zugriff = daten.get("access_token")
    if zugriff and float(daten.get("gueltig_bis") or 0) - _VORLAUF_S > time.time():
        return str(zugriff)

    e = einrichtung()
    if not (e["tenant_id"] and e["client_id"]):
        raise CopilotFehler(
            "Microsoft 365 Copilot ist nicht mehr eingerichtet "
            "(Mandanten-/Anwendungs-Kennung fehlt).", "nicht_eingerichtet")
    url = f"{ANMELDUNG}/{e['tenant_id']}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=NETZ_ZEITDECKEL_S) as c:
        r = await c.post(url, data={
            "grant_type": "refresh_token",
            "client_id": e["client_id"],
            "refresh_token": refresh,
            "scope": _scope_string(),
        })
    if not r.is_success:
        # Ein abgelaufenes oder zurueckgezogenes Refresh-Token ist der
        # Regelfall nach 90 Tagen – es wird ENTFERNT, damit die Oberflaeche
        # "nicht verbunden" zeigt statt bei jeder Frage denselben Fehler.
        trennen(benutzer)
        raise CopilotFehler(
            "Die Verbindung zu Microsoft 365 Copilot ist nicht mehr gueltig "
            "(" + _fehlertext(r, "Token-Auffrischung") + "). Bitte neu verbinden.",
            "nicht_verbunden")
    _speichere_token(benutzer, r.json() or {})
    return str(_lade(benutzer).get("access_token") or "")


def _fehlertext(r: httpx.Response, was: str) -> str:
    try:
        d = r.json() or {}
        f = d.get("error")
        if isinstance(f, dict):          # Graph-Stil
            f = f.get("message") or f.get("code")
        detail = d.get("error_description") or f or ""
    except Exception:  # noqa: BLE001
        detail = ""
    detail = str(detail)[:300] or (r.text or "")[:300]
    return f"{was}: HTTP {r.status_code} {detail}".strip()


# ── Recherche ───────────────────────────────────────────────────────────────
async def recherche(benutzer: str, frage: str, web: bool = True) -> dict:
    """Eine Frage an Copilot; Rueckgabe ``{"text": …, "quellen": [...]}``.

    ``web=False`` schaltet das Web-Grounding fuer DIESE Nachricht ab. Der
    Schalter gilt laut Microsoft nur fuer eine einzelne Nachricht
    ("single-turn action") – weil hier je Frage eine eigene Unterhaltung
    entsteht, deckt sich das: der Wert gilt genau fuer diese eine Frage.

    Das Mandanten-Grounding (Postfach, SharePoint, Teams) laesst die API NICHT
    abschalten; auch bei ``web=True`` kann die Antwort also Hausinternes
    enthalten. Das ist eine Eigenschaft der Schnittstelle und steht so in der
    Werkzeug-Beschreibung.
    """
    frage = (frage or "").strip()
    if not frage:
        raise CopilotFehler("Keine Frage angegeben.", "eingabe")
    token = await _zugriffstoken(benutzer)
    kopf = {"Authorization": f"Bearer {token}",
            "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=CHAT_ZEITDECKEL_S) as c:
        r = await c.post(f"{GRAPH}/copilot/conversations", headers=kopf, json={})
        if not r.is_success:
            raise CopilotFehler(_hinweis_zu(r, _fehlertext(r, "Unterhaltung anlegen")),
                                _grund_zu(r))
        conv = (r.json() or {}).get("id") or ""
        if not conv:
            raise CopilotFehler(
                "Microsoft hat keine Unterhaltungs-Kennung geliefert "
                "(die Chat API steht unter /beta, ihre Antwortform kann sich "
                "aendern).", "antwortform")

        r = await c.post(
            f"{GRAPH}/copilot/conversations/{conv}/chat",
            headers=kopf,
            json={
                "message": {"text": frage},
                # isWebEnabled ist standardmaessig AN; der Wert wird trotzdem
                # ausdruecklich gesetzt – eine Vorgabe, die man nicht schreibt,
                # ist eine Annahme ueber eine Preview-API.
                "contextualResources": {"webContext": {"isWebEnabled": bool(web)}},
            },
        )
    if not r.is_success:
        raise CopilotFehler(_hinweis_zu(r, _fehlertext(r, "Copilot-Anfrage")),
                            _grund_zu(r))
    return _antwort_lesen(r.json() or {}, frage)


def _grund_zu(r: httpx.Response) -> str:
    if r.status_code in (401, 403):
        return "rechte"
    if r.status_code == 429:
        return "drosselung"
    return "fehler"


def _hinweis_zu(r: httpx.Response, text: str) -> str:
    """Der Fehlergrund nennt den naechsten Schritt, nicht nur den Fehlschlag.

    Die drei Faelle, die bei dieser API wirklich vorkommen, zeigen alle in
    verschiedene Richtungen – und ein 403 ohne Hinweis schickt die Suche in
    die Rechteverwaltung, obwohl eine fehlende Lizenz die haeufigere Ursache
    ist (Register: ein Fehlergrund, der die falsche Ursache benennt, ist
    teurer als einer, der schweigt).
    """
    if r.status_code == 403:
        return (text + " – haeufigste Ursache: dieses Konto hat keine "
                "Microsoft-365-Copilot-Lizenz (die Chat API ist nur mit "
                "Add-on-Lizenz nutzbar). Zweite Moeglichkeit: die sieben "
                "Graph-Berechtigungen der Anwendung sind nicht freigegeben.")
    if r.status_code == 401:
        return text + " – die Verbindung neu herstellen (Einstellungen -> Copilot)."
    if r.status_code == 429:
        return text + " – Microsoft drosselt gerade; spaeter erneut versuchen."
    if r.status_code == 404:
        return (text + " – die Chat API steht unter /beta und ist nicht in "
                "jedem Mandanten freigeschaltet.")
    return text


def _antwort_lesen(d: dict, frage: str = "") -> dict:
    """Text und Quellen aus der ``copilotConversation``-Antwort.

    Gelesen wird die LETZTE Nachricht, die Text traegt – die Antwort enthaelt
    auch die eigene Frage. Die wird ausdruecklich uebersprungen: traegt die
    Antwort keinen Text, bekaeme das Modell sonst seine eigene Frage als
    Rechercheergebnis statt des Fehlers (Review 2026-11-10). Kein ``[-1]``
    und kein ``.index()``: beides wirft, statt einen Grund zu nennen, und
    ein Wurf in einem Werkzeug ist von "nicht gelaufen" nicht zu
    unterscheiden (Register).
    """
    text = ""
    quellen: list[dict] = []
    eigene = (frage or "").strip()
    nachrichten = d.get("messages")
    if not isinstance(nachrichten, list):
        nachrichten = []
    for m in nachrichten:
        if not isinstance(m, dict):
            continue
        t = m.get("text")
        if not isinstance(t, str) or not t.strip():
            continue
        if eigene and t.strip() == eigene:
            continue
        text = t
        quellen = []
        attr = m.get("attributions")
        if isinstance(attr, list):
            for a in attr:
                if not isinstance(a, dict):
                    continue
                url = str(a.get("seeMoreWebUrl") or "").strip()
                name = str(a.get("providerDisplayName") or "").strip()
                if url or name:
                    quellen.append({"name": name, "url": url,
                                    "art": str(a.get("attributionType") or "")})
    if not text:
        raise CopilotFehler(
            "Copilot hat keinen Text geliefert (Antwort ohne Nachricht). "
            "Die Chat API steht unter /beta, ihre Antwortform kann sich "
            "aendern.", "antwortform")
    return {"text": text, "quellen": quellen}
