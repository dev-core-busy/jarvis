"""Persoenlicher Jira-Zugang je Benutzer (Vorrang vor dem Sammelzugang).

**Entscheidung 2026-08-28:** Der in *Einstellungen → Jira* hinterlegte Token ist
ab jetzt der **Sammelzugang** und nur noch der RUECKFALL. Wer unter *Mein
Jira-Zugang* (Bereich ``/jira-addon``) einen eigenen Token hinterlegt, arbeitet
damit – in der Browser-Erweiterung, bei den ``jira_*``-Werkzeugen im Chat, in
der Ticketsuche des Reiters und in zeitversetzten Laeufen (ueber die
Actor-Bindung).

**Warum das ein Sicherheitsgewinn ist:** vorher erbten ALLE Jira-freigegebenen
Benutzer die Berechtigungen EINES Server-Tokens – "fremde Zugangsdaten als
Vollmacht", eines der vier Muster aus der Endpunkt-Durchsicht vom 2026-08-04.
Ein Jira-PAT traegt die Rechte seines Besitzers; mit eigenem Token sieht jeder
genau die Vorgaenge, fuer die er in Jira berechtigt ist. Beim Sammelzugang
dagegen sieht **jeder alles, was das Servertoken sehen darf** – und im
Ticketverlauf stehen Kundendaten.

DER BENUTZER SETZT NUR DEN TOKEN, NIE DIE ADRESSE
-------------------------------------------------
Bewusster Unterschied zu ``sap_accounts`` (Vorgabe des Nutzers 2026-08-28): dort
darf der Benutzer die Serveradresse setzen, weil der Fall "der Administrator hat
gar nichts konfiguriert" sonst unloesbar waere. Bei Jira gibt es **ein**
Haus-System; ein freies Adressfeld waere eine SSRF-Flaeche ohne Gegenwert – und
es zoege die ganze Host-Freigabeliste samt Admin-Pflege nach sich. Die Adresse
kommt deshalb IMMER aus der Skill-Config. Fehlt sie dort, gibt es auch mit
eigenem Token keine Verbindung, und die Meldung sagt genau das.

**KEIN AUSSETZER nach Anmeldefehlern** – ebenfalls anders als bei SAP, und der
Grund ist, dass der SAP-Grund hier fehlt: dort schuetzt der Aussetzer vor
``login/fails_to_user_lock``, das den SAP-Benutzer sperrt. Ein abgelaufener
Jira-PAT sperrt kein Konto, er wird schlicht abgelehnt. Vermerkt werden
trotzdem letzter Erfolg und letzter Fehler – ein toter Token muss sichtbar
sein, sonst sucht der Benutzer den Fehler in der Auswertung.

**KEIN KLARTEXT-RUECKFALL.** Fehlt ``cryptography``, wird das Speichern
abgelehnt statt den Token unverschluesselt abzulegen (gleiche Begruendung wie in
``mail_accounts``/``sap_accounts``: ein stiller Rueckfall meldet Erfolg, und
niemand erfaehrt, dass die Token offen liegen). ``data/jira_accounts.json`` ist
0640, ``data/.jirakey`` ist 0600, beide stehen in ``_APP_DENY_REL``,
``PRIVATE_FILES`` bzw. ``PRIVATE_FILES_STRENG`` und ``SHELL_SECRET_PATHS``.
Kein Endpunkt gibt einen Token heraus, auch nicht maskiert – die Laenge allein
ist schon eine Aussage.
"""

from __future__ import annotations

import contextvars
import json
import os
import time
from pathlib import Path

from backend.jira_client import JiraClient, JiraError, get_jira_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KONTEN_DATEI = DATA_DIR / "jira_accounts.json"
SCHLUESSEL_DATEI = DATA_DIR / ".jirakey"

DATEI_MODUS = 0o640
SCHLUESSEL_MODUS = 0o600


class JiraKontoFehler(Exception):
    """Fehler bei der Pflege eines persoenlichen Zugangs.

    ``kategorie``: ``eingabe`` (=> HTTP 400) oder ``fehler`` (=> 500). Getrennt,
    damit die Oberflaeche einen Tippfehler nicht wie einen Serverausfall
    darstellt."""

    def __init__(self, message: str, kategorie: str = "eingabe"):
        self.kategorie = kategorie
        super().__init__(message)


# ── Wer laeuft gerade? ──────────────────────────────────────────────────────
# Gleiche Mechanik wie ``sap_accounts.current_sap_user``: ``agent.py::
# _execute_tool`` setzt den Wert pro Werkzeug-Aufruf und nimmt ihn im
# ``finally`` zurueck.
#
# BEWUSST NICHT ueber ``sandbox.tool_user()``: der ist fuer privilegierte
# Benutzer absichtlich LEER ("keine Einschraenkung"). Ein Jira-Zugang ist aber
# keine Rechtefrage, sondern eine Personenfrage – ein Administrator hat genauso
# einen eigenen Jira-Benutzer. Mit ``tool_user()`` haetten Administratoren gar
# keinen persoenlichen Zugang.
#
# UND NIEMALS ALS WERKZEUG-PARAMETER: sonst koennte das Modell (oder ein per
# Prompt-Injection eingeschmuggelter Satz) waehlen, mit WESSEN Token es
# arbeitet.
current_jira_user: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_jira_user", default="")


def norm_user(name: str) -> str:
    """Kontoname ohne Domaenen-Praefix/UPN-Suffix, klein.

    Gleiche Semantik wie ``sap_accounts.norm_user`` und ``main._norm_login``:
    derselbe Mensch meldet sich mal als ``nexus\\a.bender``, mal als
    ``a.bender@nexus.int`` an – ohne Normalisierung haette er je Tippform einen
    eigenen Jira-Zugang und wuerde seinen eigenen nicht wiederfinden."""
    s = (name or "").strip()
    if not s or ":" in s:          # Kanal-Kennungen (wa:/tg:/api:) unangetastet
        return s.lower()
    return s.split("@")[0].split("\\")[-1].strip().lower()


# ── Verschluesselung ────────────────────────────────────────────────────────

def _fernet():
    """Fernet-Instanz mit dem lokalen Schluessel; legt ihn beim ersten Mal an.

    EIGENE Schluesseldatei, nicht die des SAP-Moduls: ein gemeinsamer
    Schluessel verbaende zwei Bereiche, die nichts miteinander zu tun haben –
    beim Zuruecksichern eines einzelnen Bereichs waere danach der jeweils
    andere unlesbar."""
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        raise JiraKontoFehler(
            "Das Paket 'cryptography' fehlt – Token koennen nicht "
            "verschluesselt gespeichert werden. Ein Klartext-Rueckfall ist "
            "ausdruecklich nicht vorgesehen.", "fehler") from e
    try:
        if SCHLUESSEL_DATEI.exists():
            roh = SCHLUESSEL_DATEI.read_bytes().strip()
            if roh:
                return Fernet(roh)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        neu = Fernet.generate_key()
        # Erst mit 0600 anlegen, DANN schreiben: zwischen open() und chmod()
        # laege der Schluessel sonst kurz mit 0644 auf der Platte.
        fd = os.open(str(SCHLUESSEL_DATEI), os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                     SCHLUESSEL_MODUS)
        with os.fdopen(fd, "wb") as f:
            f.write(neu)
        os.chmod(SCHLUESSEL_DATEI, SCHLUESSEL_MODUS)
        return Fernet(neu)
    except JiraKontoFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise JiraKontoFehler("Schluesseldatei nicht nutzbar (%s): %s"
                              % (SCHLUESSEL_DATEI, e), "fehler") from e


def verschluesseln(klartext: str) -> str:
    if not klartext:
        return ""
    return _fernet().encrypt(klartext.encode("utf-8")).decode("ascii")


def entschluesseln(gespeichert: str) -> str:
    """Token zurueckholen. Bei ungueltigem Wert: sprechender Fehler.

    Haeufigster Fall ist eine verlorene/ersetzte Schluesseldatei (Restore ohne
    ``.jirakey``). "InvalidToken" sagt niemandem etwas – die Meldung nennt
    deshalb die Abhilfe."""
    if not gespeichert:
        return ""
    try:
        return _fernet().decrypt(gespeichert.encode("ascii")).decode("utf-8")
    except JiraKontoFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise JiraKontoFehler(
            "Der gespeicherte Jira-Token laesst sich nicht entschluesseln – "
            "vermutlich wurde die Schluesseldatei data/.jirakey ersetzt oder "
            "sie fehlt. Bitte den Token unter 'Mein Jira-Zugang' neu "
            "hinterlegen. (%s)" % type(e).__name__, "fehler") from e


# ── Ablage ──────────────────────────────────────────────────────────────────

def _laden() -> dict:
    try:
        if not KONTEN_DATEI.exists():
            return {}
        d = json.loads(KONTEN_DATEI.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception as e:  # noqa: BLE001
        # Eine beschaedigte Datei darf den Dienst nicht kippen; sie wird aber
        # AUCH NICHT ueberschrieben (Datenverlust ohne Not) – der Aufrufer sieht
        # "kein Zugang" und faellt auf den Sammelzugang zurueck.
        print("[Jira] Kontendatei nicht lesbar: %s" % e, flush=True)
        return {}


def _speichern(alle: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = KONTEN_DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(alle, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, DATEI_MODUS)
    except Exception:  # noqa: BLE001
        pass
    os.replace(tmp, KONTEN_DATEI)   # atomar: kein halber Zustand bei Absturz
    try:
        os.chmod(KONTEN_DATEI, DATEI_MODUS)
    except Exception:  # noqa: BLE001
        pass


# ── Felder ──────────────────────────────────────────────────────────────────
# Nur diese Felder darf ein Benutzer an seinem Zugang setzen. Ohne Whitelist
# nimmt ein POST beliebige Felder – dieselbe Luecke, die ``scheduler.update_job``
# bis 2026-07-28 hatte (dort liess sich ``owner_privileged`` setzen).
#
# NICHT enthalten und das ist Absicht:
#   base_url  – die Adresse kommt IMMER aus der Skill-Config (Modul-Docstring)
GEHEIMFELDER = ("api_token",)
AENDERBAR = ("aktiv",) + GEHEIMFELDER


def _leer(un: str) -> dict:
    return {"benutzer_norm": un, "aktiv": True,
            "angelegt": int(time.time()), "geaendert": 0,
            "letzter_erfolg": 0, "letzter_fehler": "",
            "anzeigename": "", "konto": ""}


def _vollstaendig(k: dict) -> bool:
    """Reicht der gespeicherte Zugang, um ueberhaupt zu verbinden?

    Nur der Token – die Adresse steuert der Administrator bei. Bewusst OHNE
    Entschluesselung: die Frage "gibt es einen Zugang" wird auf jeder Seite
    gestellt und darf keinen Schluesselzugriff kosten."""
    return bool((k.get("api_token_enc") or "").strip())


def hat_zugang(user: str) -> bool:
    """Hat dieser Benutzer einen (vollstaendigen) eigenen Zugang hinterlegt?"""
    k = _laden().get(norm_user(user))
    return bool(k and _vollstaendig(k))


def basis_url() -> str:
    """Adresse des Jira-Servers – IMMER aus der Skill-Config."""
    try:
        return (get_jira_config().get("base_url") or "").strip().rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


# ── Lesen fuer die Oberflaeche ──────────────────────────────────────────────

def klartext(user: str, feld: str) -> tuple[str, str]:
    """Den gespeicherten Token dieses Benutzers im Klartext. (wert, fehler)

    Anweisung und Begruendung: siehe ``sap_accounts.klartext``. ``zugang_info``
    gibt weiterhin nichts heraus.
    """
    f = (feld or "").strip() or GEHEIMFELDER[0]
    if f not in GEHEIMFELDER:
        return "", f"Das Feld '{f}' ist kein Geheimfeld dieses Zugangs."
    k = _laden().get(norm_user(user)) or {}
    roh = str(k.get(f + "_enc") or "").strip()
    if not roh:
        return "", "In diesem Feld ist nichts gespeichert."
    try:
        return entschluesseln(roh), ""
    except Exception as e:  # noqa: BLE001
        return "", f"Entschluesselung fehlgeschlagen: {e}"


def zugang_info(user: str) -> dict:
    """Fuer die Oberflaeche – OHNE Token, auch nicht maskiert.

    ``token_gesetzt`` ist die einzige Aussage darueber. Eine maskierte Form
    ("****") wuerde die Laenge verraten, und ein leeres Feld heisst in der
    Oberflaeche "unveraendert" – dafuer braucht es nur ein Ja/Nein."""
    un = norm_user(user)
    k = _laden().get(un) or _leer(un)
    basis = basis_url()
    return {
        "vorhanden": bool(_vollstaendig(k)),
        "aktiv": bool(k.get("aktiv", True)),
        "token_gesetzt": bool((k.get("api_token_enc") or "").strip()),
        "letzter_erfolg": int(k.get("letzter_erfolg", 0) or 0),
        "letzter_fehler": k.get("letzter_fehler", ""),
        # Wer der Token in Jira IST – aus /myself beim Verbindungstest. Ohne
        # das ist ein Token eine Zeichenkette ohne Aussage, und ein
        # versehentlich fremder Token faellt nie auf.
        "anzeigename": k.get("anzeigename", ""),
        "konto": k.get("konto", ""),
        # Die Adresse gehoert dem Administrator und wird nur ANGEZEIGT: der
        # Benutzer muss wissen, gegen welchen Server sein Token gilt.
        "basis_url": basis,
        "server_konfiguriert": bool(basis),
        # Hat der Administrator ueberhaupt einen Sammelzugang? Wenn nicht, ist
        # ein eigener Token der EINZIGE Weg – dann darf die Oberflaeche ihn
        # nicht als "optional" beschreiben.
        "sammel_vorhanden": bool(sammel_client().configured),
    }


def sammel_client() -> JiraClient:
    """Der Zugang des Administrators (Skill-Config) – der Rueckfall."""
    return JiraClient()


# ── Schreiben ───────────────────────────────────────────────────────────────

def speichern(user: str, felder: dict) -> dict:
    """Zugang des Benutzers anlegen/aendern. Rueckgabe = ``zugang_info``.

    **Leeres Token-Feld heisst UNVERAENDERT**, nicht "loeschen". Sonst
    ueberschriebe jedes Speichern der uebrigen Felder (der Haken "verwenden")
    den Token mit einem Leerstring – derselbe Fehler, der beim Dienstkonto der
    Lizenz-Ausgabestelle und beim Postfach behoben wurde. Zum Entfernen gibt es
    ``loeschen()``.

    Die Feldliste ``AENDERBAR`` ist die EINZIGE Instanz: der Endpunkt filtert
    ausdruecklich NICHT vor. Zwei Schichten mit unterschiedlicher Meinung sind
    das Muster, das in diesem Projekt schon mehrfach Stunden gekostet hat – ein
    stillschweigend verworfenes Feld meldet "gespeichert", obwohl es das nicht
    ist."""
    un = norm_user(user)
    if not un:
        raise JiraKontoFehler("Kein Benutzer – Zugang kann nicht zugeordnet werden.")
    if ":" in un:
        # wa:/tg:/api: – Kanal-Kennungen sind keine Personen mit Jira-Benutzer.
        raise JiraKontoFehler("Fuer diese Kennung kann kein Jira-Zugang hinterlegt werden.")

    alle = _laden()
    k = alle.get(un) or _leer(un)
    k["benutzer_norm"] = un

    unbekannt = [f for f in (felder or {}) if f not in AENDERBAR]
    if unbekannt:
        raise JiraKontoFehler(
            "Unbekannte oder nicht selbst setzbare Felder: %s. Die Serveradresse "
            "pflegt der Administrator unter Einstellungen → Jira – dein Token "
            "gilt immer fuer genau diesen Server." % ", ".join(sorted(unbekannt)))

    if "aktiv" in felder:
        k["aktiv"] = bool(felder.get("aktiv"))

    for f in GEHEIMFELDER:
        if f in felder:
            wert = str(felder.get(f) or "")
            if wert.strip():
                k[f + "_enc"] = verschluesseln(wert)
                # NEUER Token = neuer Anlauf: der alte Fehler gehoert nicht
                # mehr dazu und stuende sonst weiter in der Oberflaeche.
                k["letzter_fehler"] = ""
                k["anzeigename"] = ""
                k["konto"] = ""

    k["geaendert"] = int(time.time())
    alle[un] = k
    _speichern(alle)
    return zugang_info(user)


def loeschen(user: str) -> bool:
    un = norm_user(user)
    alle = _laden()
    if un not in alle:
        return False
    del alle[un]
    _speichern(alle)
    return True


def merke_ergebnis(user: str, ok: bool, fehler: str = "",
                   anzeigename: str = "", konto: str = "") -> None:
    """Letzten Zustand am Zugang vermerken (fuer die Oberflaeche)."""
    un = norm_user(user)
    alle = _laden()
    k = alle.get(un)
    if not k:
        return
    if ok:
        k["letzter_erfolg"] = int(time.time())
        k["letzter_fehler"] = ""
        if anzeigename:
            k["anzeigename"] = anzeigename[:120]
        if konto:
            k["konto"] = konto[:120]
    else:
        k["letzter_fehler"] = (fehler or "")[:500]
    alle[un] = k
    try:
        _speichern(alle)
    except Exception as e:  # noqa: BLE001
        print("[Jira] Zugangs-Zustand nicht gespeichert: %s" % e, flush=True)


def melde_fehler(user: str, fehler: Exception) -> None:
    """Bequemer Weg fuer Aufrufer: vermerkt einen Fehlschlag am eigenen Zugang.

    Nur wirksam, wenn der Lauf ueberhaupt den persoenlichen Zugang benutzt hat –
    sonst wuerde ein Fehler des Sammelzugangs dem Benutzer angerechnet."""
    try:
        if not hat_zugang(user):
            return
        merke_ergebnis(user, False, str(fehler or ""))
    except Exception:  # noqa: BLE001
        pass


def alle_benutzer() -> list[str]:
    """Normalisierte Namen aller Benutzer mit eigenem Zugang (Admin-Sicht)."""
    return sorted(_laden().keys())


# ── Aufloesung: welcher Zugang gilt fuer diesen Lauf? ───────────────────────

# Warum ein eigenes Ergebnis-dict und nicht nur ein Client: der Aufrufer MUSS
# sagen koennen, WELCHER Zugang benutzt wurde. Ein stiller Wechsel auf den
# Sammelzugang liesse den Benutzer Tickets sehen, die mit FREMDEN (in der Regel
# weiteren) Jira-Berechtigungen geholt wurden – ohne dass er es merkt. Genau die
# Fehlerklasse "eine Anzeige behauptet einen Zustand, den sie nicht kennt".
QUELLE_PERSOENLICH = "persoenlich"
QUELLE_SAMMEL = "sammel"


def aufloesen(user: str | None = None) -> dict:
    """Welcher Jira-Zugang gilt? Rueckgabe:
    ``{client, quelle, hinweis, benutzer}``.

    ``user=None`` nimmt den ContextVar (also den Actor des laufenden Auftrags).
    Faellt IMMER auf den Sammelzugang zurueck, wenn der persoenliche nicht
    nutzbar ist – mit einem Hinweis, der den Grund nennt (gleiche Vorgabe wie
    bei SAP: Rueckfall mit Hinweis statt Absage)."""
    if user is None:
        try:
            user = current_jira_user.get() or ""
        except Exception:  # noqa: BLE001
            user = ""
    un = norm_user(user or "")
    basis = basis_url()
    hinweis = ""
    if un and ":" not in un:
        try:
            k = _laden().get(un)
        except Exception:  # noqa: BLE001
            k = None
        if k and _vollstaendig(k):
            if not bool(k.get("aktiv", True)):
                hinweis = ("Dein persoenlicher Jira-Zugang steht auf inaktiv – "
                           "es gilt der gemeinsame Zugang.")
            elif not basis:
                # Ohne Adresse nuetzt der beste Token nichts. Der Hinweis nennt
                # den Ort, an dem sie fehlt – sonst sucht der Benutzer den
                # Fehler bei seinem Token.
                hinweis = ("Es ist keine Jira-Adresse hinterlegt – ein "
                           "Administrator muss sie unter Einstellungen → Jira "
                           "eintragen. Dein eigener Token kann ohne sie nicht "
                           "verwendet werden.")
            else:
                try:
                    token = entschluesseln(k.get("api_token_enc", ""))
                except JiraKontoFehler as e:
                    hinweis = "%s Es gilt vorerst der gemeinsame Zugang." % e
                else:
                    c = JiraClient({"base_url": basis, "api_token": token})
                    if c.configured:
                        return {"client": c, "quelle": QUELLE_PERSOENLICH,
                                "hinweis": "", "benutzer": un}
                    hinweis = ("Dein persoenlicher Jira-Zugang ist "
                               "unvollstaendig – es gilt der gemeinsame Zugang.")
    return {"client": sammel_client(), "quelle": QUELLE_SAMMEL,
            "hinweis": hinweis, "benutzer": un}


def client_fuer_lauf(user: str | None = None) -> JiraClient:
    """Nur der Client – fuer Aufrufer, die den Hinweis nicht brauchen."""
    return aufloesen(user)["client"]


def quelle_text(quelle: str, lang: str = "de") -> str:
    """Kurzbezeichnung fuer die Oberflaeche/den Ergebniskopf."""
    if lang.startswith("en"):
        return ("your personal Jira access" if quelle == QUELLE_PERSOENLICH
                else "the shared access")
    return ("dein persoenlicher Jira-Zugang" if quelle == QUELLE_PERSOENLICH
            else "der gemeinsame Zugang")


def testen(user: str) -> dict:
    """Verbindungstest MIT dem eigenen Token – ``/myself``.

    Er prueft ausdruecklich den PERSOENLICHEN Zugang, nicht den, der gerade
    gelten wuerde: sonst meldete der Knopf bei einem kaputten eigenen Token
    "ok" (weil der Sammelzugang antwortet) und der Benutzer haette keinen Weg,
    seinen Fehler zu finden – dieselbe Falle wie beim SAP-Verbindungstest.
    """
    un = norm_user(user)
    k = _laden().get(un)
    if not (k and _vollstaendig(k)):
        raise JiraKontoFehler("Es ist kein eigener Token hinterlegt.")
    basis = basis_url()
    if not basis:
        raise JiraKontoFehler(
            "Es ist keine Jira-Adresse hinterlegt – ein Administrator muss sie "
            "unter Einstellungen → Jira eintragen.")
    c = JiraClient({"base_url": basis, "api_token": entschluesseln(k.get("api_token_enc", ""))})
    try:
        ich = c.myself() or {}
    except JiraError as e:
        merke_ergebnis(user, False, str(e))
        raise JiraKontoFehler("Jira lehnt den Token ab: %s" % e) from None
    except Exception as e:  # noqa: BLE001
        merke_ergebnis(user, False, str(e))
        raise JiraKontoFehler("Jira ist nicht erreichbar: %s" % e) from None
    name = str(ich.get("displayName") or "").strip()
    konto = str(ich.get("name") or ich.get("key") or "").strip()
    merke_ergebnis(user, True, anzeigename=name, konto=konto)
    return {"anzeigename": name, "konto": konto, "info": zugang_info(user)}


__all__ = [
    "JiraKontoFehler", "JiraError", "current_jira_user", "norm_user",
    "zugang_info", "speichern", "loeschen", "hat_zugang", "alle_benutzer",
    "merke_ergebnis", "melde_fehler", "testen", "basis_url", "sammel_client",
    "aufloesen", "client_fuer_lauf", "quelle_text",
    "QUELLE_PERSOENLICH", "QUELLE_SAMMEL", "AENDERBAR", "GEHEIMFELDER",
]
