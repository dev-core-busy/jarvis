"""Persoenlicher VEMAS-Zugang je Benutzer (Vorrang vor dem Sammelzugang).

Bauart und Begruendung folgen ``sap_accounts.py``: der in *Einstellungen →
Vemas* hinterlegte Zugang ist der **Sammelzugang** und nur noch der RUECKFALL.
Wer eigene Zugangsdaten hinterlegt (Kachel "Mein VEMAS-Zugang" in ``/vemas``),
arbeitet damit – im Bereich ``/vemas``, bei den ``vemas_*``-Werkzeugen im Chat
und in zeitversetzten Laeufen (ueber die Actor-Bindung).

**Warum das ein Sicherheitsgewinn ist:** ohne persoenlichen Zugang erben ALLE
Freigegebenen die Berechtigungen EINES Server-Kontos ("fremde Zugangsdaten als
Vollmacht" – eines der vier Muster aus der Endpunkt-Durchsicht vom 2026-08-04).
Mit eigenem VEMAS-Benutzer sieht jeder genau die Daten, fuer die er im
Zielsystem berechtigt ist – und ein Schreibvorgang steht im VEMAS-Protokoll
unter seinem Namen statt unter einem Sammelkonto.

── ZWEI BEWUSSTE ABWEICHUNGEN VOM SAP-VORBILD ─────────────────────────────

**(1) Der Benutzer setzt NUR die Zugangsdaten, NIE die Serveradresse.**
Bei SAP darf er die Adresse setzen, weil der Fall "der Administrator hat gar
nichts konfiguriert" sonst unloesbar waere – dort gibt es je Fachbereich
verschiedene Systeme. VEMAS ist wie Jira **ein** Haus-System: die Adresse
gehoert in den Reiter, der Benutzer haengt nur seine Anmeldung daran. Damit
entfaellt die ganze SSRF-Flaeche und mit ihr die Host-Freigabeliste, die es bei
SAP nur deshalb gibt. ``base_url`` steht deshalb **nicht** in ``AENDERBAR``.

**(2) Geschrieben wird NUR mit dem persoenlichen Zugang.**
Der Administrator kann Schreibzugriffe freischalten (``read_only = false`` in
der Skill-Config). Diese Freigabe wirkt aber ausschliesslich fuer Benutzer mit
EIGENEM Zugang: ``aufloesen()`` erzwingt am Sammelzugang unabhaengig von der
Konfiguration wieder Nur-Lesen. Zwei Gruende, und beide zaehlen einzeln:
ein Schreibvorgang mit dem Sammelkonto traegt im VEMAS-Protokoll den falschen
Namen und ist nicht zuzuordnen; und er liefe mit den – in aller Regel weiteren –
Rechten dieses Kontos, also mit fremder Vollmacht. Wer schreiben soll, meldet
sich mit seinem eigenen Konto an.

**KEIN KLARTEXT-RUECKFALL.** Fehlt ``cryptography``, wird das Speichern
abgelehnt statt das Kennwort unverschluesselt abzulegen (gleiche Begruendung wie
in ``mail_accounts``/``sap_accounts``: ein stiller Rueckfall meldet Erfolg, und
niemand erfaehrt, dass die Kennwoerter offen liegen). ``data/vemas_accounts.json``
ist 0640, ``data/.vemaskey`` ist 0600, beide stehen in ``_APP_DENY_REL``,
``PRIVATE_FILES`` bzw. ``PRIVATE_FILES_STRENG`` und ``SHELL_SECRET_PATHS``.
Kein Endpunkt gibt ein Kennwort heraus, auch nicht maskiert – die Laenge allein
ist schon eine Aussage.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import time
from pathlib import Path

from backend.vemas_client import VemasClient, VemasError, get_vemas_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KONTEN_DATEI = DATA_DIR / "vemas_accounts.json"
SCHLUESSEL_DATEI = DATA_DIR / ".vemaskey"

DATEI_MODUS = 0o640
SCHLUESSEL_MODUS = 0o600


class VemasKontoFehler(Exception):
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
# Benutzer absichtlich LEER ("keine Einschraenkung"). Ein VEMAS-Zugang ist aber
# keine Rechtefrage, sondern eine Personenfrage – ein Administrator hat genauso
# einen eigenen VEMAS-Benutzer.
#
# UND NIEMALS ALS WERKZEUG-PARAMETER: sonst koennte das Modell (oder ein per
# Prompt-Injection eingeschmuggelter Satz) waehlen, mit WESSEN Zugangsdaten es
# arbeitet – und bei freigeschaltetem Schreiben auch, in wessen Namen es bucht.
current_vemas_user: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_vemas_user", default="")


def norm_user(name: str) -> str:
    """Kontoname ohne Domaenen-Praefix/UPN-Suffix, klein.

    Gleiche Semantik wie ``sap_accounts.norm_user`` und ``main._norm_login``:
    derselbe Mensch meldet sich mal als ``nexus\\a.bender``, mal als
    ``a.bender@nexus.int`` an – ohne Normalisierung haette er je Tippform einen
    eigenen Zugang und wuerde seinen eigenen nicht wiederfinden."""
    s = (name or "").strip()
    if not s or ":" in s:          # Kanal-Kennungen (wa:/tg:/api:) unangetastet
        return s.lower()
    return s.split("@")[0].split("\\")[-1].strip().lower()


# ── Verschluesselung ────────────────────────────────────────────────────────

def _fernet():
    """Fernet-Instanz mit dem lokalen Schluessel; legt ihn beim ersten Mal an.

    **Eigene Schluesseldatei, nicht die des SAP-/Mail-Moduls.** Ein gemeinsamer
    Schluessel verbaende zwei Bereiche, und ein Restore eines einzelnen machte
    den anderen unlesbar (gleiche Entscheidung wie bei ``.jirakey``)."""
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        raise VemasKontoFehler(
            "Das Paket 'cryptography' fehlt – Kennwoerter koennen nicht "
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
    except VemasKontoFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise VemasKontoFehler("Schluesseldatei nicht nutzbar: %s" % e, "fehler") from e


def verschluesseln(klartext: str) -> str:
    if not klartext:
        return ""
    return _fernet().encrypt(klartext.encode("utf-8")).decode("ascii")


def entschluesseln(gespeichert: str) -> str:
    """Gibt bei einem unlesbaren Wert einen LEEREN String zurueck.

    Fail-safe in Richtung "nicht nutzbar": ein Zugang, dessen Kennwort sich
    nicht entschluesseln laesst (Schluesseldatei getauscht), gilt als
    unvollstaendig und faellt auf den Sammelzugang zurueck – statt mit einer
    Ausnahme mitten im Werkzeug-Aufruf zu stehen."""
    if not gespeichert:
        return ""
    try:
        return _fernet().decrypt(gespeichert.encode("ascii")).decode("utf-8")
    except VemasKontoFehler:
        raise
    except Exception:  # noqa: BLE001
        return ""


# ── Ablage ──────────────────────────────────────────────────────────────────

def _laden() -> dict:
    try:
        if not KONTEN_DATEI.exists():
            return {}
        daten = json.loads(KONTEN_DATEI.read_text(encoding="utf-8"))
        return daten if isinstance(daten, dict) else {}
    except Exception as e:  # noqa: BLE001
        print("[VEMAS] Zugaenge nicht lesbar: %s" % e, flush=True)
        return {}


def _speichern(alle: dict) -> None:
    """Atomar schreiben und die Rechte SOFORT setzen (0640).

    Ohne den frueh gesetzten Modus laege die Datei zwischen Anlegen und chmod
    mit 0644 da – lesbar fuer jeden Shell-Befehl in der Sandbox."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = KONTEN_DATEI.with_suffix(".tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, DATEI_MODUS)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(alle, f, ensure_ascii=False, indent=2)
        os.chmod(tmp, DATEI_MODUS)
        os.replace(tmp, KONTEN_DATEI)
        os.chmod(KONTEN_DATEI, DATEI_MODUS)
    except Exception as e:  # noqa: BLE001
        try:
            tmp.unlink()
        except Exception:  # noqa: BLE001
            pass
        raise VemasKontoFehler("Zugang nicht speicherbar: %s" % e, "fehler") from e


# ── Felder ──────────────────────────────────────────────────────────────────
# Nur diese Felder darf ein Benutzer an seinem Zugang setzen. Ohne Whitelist
# nimmt ein POST beliebige Felder – dieselbe Luecke, die ``scheduler.update_job``
# bis 2026-07-28 hatte (dort liess sich ``owner_privileged`` setzen).
#
# NICHT enthalten und das ist Absicht:
#   base_url / login_path / token_json_path / …  – Eigenschaften des SERVERS,
#       nicht der Person; sie pflegt der Administrator (siehe Modul-Docstring).
#   verify_ssl   – die TLS-Pruefung ABzuschalten bleibt Sache des Admins.
#   read_only    – Schreiben schaltet ausschliesslich der Administrator frei.
TEXTFELDER = ("auth_kind", "username")
GEHEIMFELDER = ("password", "api_token")
AENDERBAR = ("aktiv",) + TEXTFELDER + GEHEIMFELDER

ANMELDEARTEN = ("basic", "bearer", "login")


# ── Aussetzer nach wiederholten Anmeldefehlern ──────────────────────────────
#
# WARUM ES DAS GIBT: zeitversetzte Laeufe (Cron, E-Mail-Regeln) melden sich im
# Takt an. Ist das Kennwort falsch oder abgelaufen, erzeugt JEDER Lauf einen
# weiteren abgelehnten Logon – dauerhaft, ohne dass jemand hinsieht.
#
# EHRLICH GESAGT: ob VEMAS.NET Konten nach N Fehlversuchen sperrt, ist NICHT
# belegt (die Doku ist nicht oeffentlich, siehe vemas_client). Der Aussetzer ist
# hier deshalb eine Vorsichtsmassnahme mit zwei belegbaren Wirkungen: er
# verhindert Dauerverkehr gegen einen fremden Server, und er macht den kaputten
# Zugang in der Oberflaeche SICHTBAR, statt ihn stillschweigend jedes Mal neu
# scheitern zu lassen. Sperrt VEMAS doch, hat er zusaetzlich genau die Wirkung,
# die er bei SAP hat.
#
# GEZAEHLT WIRD NUR EIN ANMELDEFEHLER (``ist_anmeldefehler``). Ein unerreichbarer
# Server, ein Zeitlimit oder ein Zertifikatsfehler sind keine Fehlversuche – wer
# die mitzaehlt, setzt den Zugang bei jeder Netzstoerung aus.
MAX_ANMELDEFEHLER = 3


def max_anmeldefehler() -> int:
    """Schwelle als FUNKTION, nicht als beim Import eingefrorener Wert.

    Gleiche Begruendung wie ``documents.retention_days()``: ueber die Umgebung
    gesetzt soll der Wert ohne Dienstneustart gelten. ``0`` schaltet den
    Aussetzer ab."""
    try:
        n = int(os.environ.get("JARVIS_VEMAS_MAX_AUTHFEHLER", MAX_ANMELDEFEHLER))
    except (TypeError, ValueError):
        return MAX_ANMELDEFEHLER
    return max(0, min(n, 50))


# ⚠ BERECHTIGUNG IST NICHT ANMELDUNG (Lehre aus dem SAP-Vorfall 2026-08-25).
#
# Als Anmeldefehler galt dort jedes HTTP 403 und der Text "not authorized".
# Beides sind AUTORISIERUNGS-Fehler: der Benutzer war angemeldet, ihm fehlte nur
# die Berechtigung fuer diese Ressource. Auf der Gegenseite steht dann KEIN
# fehlgeschlagener Logon – die Meldung war von aussen nicht erklaerbar, und ein
# Auswertungslauf, der mehrere Pfade durchprobiert, setzte den Zugang nach drei
# Fehlgriffen aus.
#
# Nur HTTP 401 zaehlt (unzweideutig die Anmeldung). Die Ausschlussliste gewinnt
# gegen die Trefferliste (fail-safe in Richtung "nicht zaehlen"), aber NICHT
# gegen 401.
_AUTH_MUSTER = re.compile(
    r"authentication failed|invalid username or password|"
    r"name or password is incorrect|user is locked|account is locked|"
    r"logon failed|login failed|invalid credentials|anmeldung abgelehnt|"
    r"benutzer oder kennwort", re.I)

_AUTHZ_MUSTER = re.compile(
    r"insufficient privilege|not authorized|no authorization|forbidden|"
    r"missing authorization|authorization (check )?fail|"
    r"keine berechtigung|nicht berechtigt", re.I)

_AUTH_STATUS = (401,)


def ist_anmeldefehler(fehler: Exception) -> bool:
    """Ist das ein ANMELDE-Fehler (zaehlt gegen den Aussetzer)?

    Abgegrenzt gegen den BERECHTIGUNGS-Fehler, der wie einer aussieht, aber
    keiner ist – siehe die Begruendung bei ``_AUTHZ_MUSTER``."""
    text = str(fehler or "")
    try:
        status = int(getattr(fehler, "status", 0) or 0)
    except Exception:  # noqa: BLE001
        status = 0
    if status in _AUTH_STATUS:
        return True
    if status == 403:
        return False
    if _AUTHZ_MUSTER.search(text):
        return False
    return bool(_AUTH_MUSTER.search(text))


def _leer(un: str) -> dict:
    return {"benutzer_norm": un, "auth_kind": "", "aktiv": True,
            "angelegt": int(time.time()), "geaendert": 0,
            "letzter_erfolg": 0, "letzter_fehler": "",
            "anmeldefehler": 0, "ausgesetzt": False, "ausgesetzt_seit": 0,
            "ausgesetzt_grund": ""}


def _vollstaendig(k: dict) -> bool:
    """Reicht der gespeicherte Zugang, um ueberhaupt zu verbinden?

    Bewusst je Anmeldeart geprueft: ein Datensatz mit Benutzernamen, aber ohne
    Kennwort ist bei ``basic`` wertlos und wuerde nur einen 401 erzeugen."""
    ak = (k.get("auth_kind") or "").strip().lower()
    if ak in ("basic", "login"):
        return bool((k.get("username") or "").strip()
                    and (k.get("password_enc") or "").strip())
    if ak == "bearer":
        return bool((k.get("api_token_enc") or "").strip())
    return False


def hat_zugang(user: str) -> bool:
    """Hat dieser Benutzer einen (vollstaendigen) eigenen Zugang hinterlegt?"""
    k = _laden().get(norm_user(user))
    return bool(k and _vollstaendig(k))


def skill_config() -> dict:
    """Konfiguration des VEMAS-Skills (Sammelzugang + Serverangaben).

    Lazy und fehlertolerant: der Skill kann fehlen oder aus sein – dann gibt es
    ein leeres dict, und die Aufloesung meldet einen Klartext-Grund."""
    try:
        return get_vemas_config() or {}
    except Exception:  # noqa: BLE001
        return {}


def server_konfiguriert() -> bool:
    """Ist ueberhaupt eine Serveradresse hinterlegt?

    Ohne sie ist ein persoenlicher Zugang sinnlos – die Oberflaeche sagt das
    dann, statt Anmeldedaten entgegenzunehmen, die nirgendwo hingehen."""
    return bool((skill_config().get("base_url") or "").strip())


def _konto_fuer_schreiben(user: str) -> tuple[str, dict, dict]:
    un = norm_user(user)
    if not un:
        raise VemasKontoFehler("Kein Benutzer – Zugang kann nicht zugeordnet werden.")
    if ":" in un:
        # wa:/tg:/api: – Kanal-Kennungen sind keine Personen mit VEMAS-Konto.
        raise VemasKontoFehler("Fuer diese Kennung kann kein VEMAS-Zugang "
                               "hinterlegt werden.")
    alle = _laden()
    return un, alle, (alle.get(un) or _leer(un))


# ── Lesen ───────────────────────────────────────────────────────────────────

def klartext(user: str, feld: str) -> tuple[str, str]:
    """Ein gespeichertes Geheimnis dieses Benutzers im Klartext. (wert, fehler)

    Anweisung und Begruendung: siehe ``sap_accounts.klartext`` – dasselbe
    Muster, hier fuer VEMAS. ``zugang_info`` gibt weiterhin nichts heraus.

    ⚠ Besonderheit dieses Moduls: ``entschluesseln`` WIRFT NICHT, es gibt bei
    einem unlesbaren Wert ``""`` zurueck. Ein leeres Ergebnis darf deshalb
    nicht als "nichts gespeichert" gemeldet werden – es kann auch ein kaputter
    Schluessel sein, und das sind zwei verschiedene Antworten.
    """
    f = (feld or "").strip() or GEHEIMFELDER[0]
    if f not in GEHEIMFELDER:
        return "", f"Das Feld '{f}' ist kein Geheimfeld dieses Zugangs."
    k = _laden().get(norm_user(user)) or {}
    roh = str(k.get(f + "_enc") or "").strip()
    if not roh:
        return "", "In diesem Feld ist nichts gespeichert."
    wert = entschluesseln(roh)
    if not wert:
        return "", ("Der gespeicherte Wert liess sich nicht entschluesseln "
                    "(Schluesseldatei getauscht?). Bitte neu eintragen.")
    return wert, ""


def zugang_info(user: str) -> dict:
    """Fuer die Oberflaeche – OHNE Kennwoerter, auch nicht maskiert.

    ``*_gesetzt`` ist die einzige Aussage darueber. Eine maskierte Form
    ("****") wuerde die Laenge verraten, und ein leeres Feld heisst in der
    Oberflaeche "unveraendert" – dafuer braucht es nur ein Ja/Nein."""
    un = norm_user(user)
    k = _laden().get(un) or _leer(un)
    c = skill_config()
    info = {
        "vorhanden": bool(_vollstaendig(k)),
        "auth_kind": (k.get("auth_kind") or "").strip().lower(),
        "aktiv": bool(k.get("aktiv", True)),
        "passwort_gesetzt": bool((k.get("password_enc") or "").strip()),
        "token_gesetzt": bool((k.get("api_token_enc") or "").strip()),
        "letzter_erfolg": int(k.get("letzter_erfolg", 0) or 0),
        "letzter_fehler": k.get("letzter_fehler", ""),
        "anmeldefehler": int(k.get("anmeldefehler", 0) or 0),
        "max_anmeldefehler": max_anmeldefehler(),
        "ausgesetzt": bool(k.get("ausgesetzt")),
        "ausgesetzt_seit": int(k.get("ausgesetzt_seit", 0) or 0),
        "ausgesetzt_grund": k.get("ausgesetzt_grund", ""),
        # Serverangaben sind ANZEIGE, nicht Eingabe: der Benutzer soll sehen,
        # WOHIN seine Zugangsdaten gehen, ohne die Adresse aendern zu koennen.
        "server": (c.get("base_url") or "").strip(),
        "server_konfiguriert": server_konfiguriert(),
        "server_auth_kind": (c.get("auth_kind") or "basic").strip().lower(),
        # Damit die Kachel sagen kann, ob Schreiben ueberhaupt in Frage kommt.
        "schreiben_frei": c.get("read_only") is False,
    }
    for f in TEXTFELDER:
        info[f] = k.get(f, "")
    return info


# ── Schreiben ───────────────────────────────────────────────────────────────

def speichern(user: str, felder: dict) -> dict:
    """Zugang des Benutzers anlegen/aendern. Rueckgabe = ``zugang_info``.

    **Leeres Kennwortfeld heisst UNVERAENDERT**, nicht "loeschen". Sonst
    ueberschriebe jedes Speichern der uebrigen Felder den Zugangsschluessel mit
    einem Leerstring – derselbe Fehler, der beim Dienstkonto der
    Lizenz-Ausgabestelle und beim Postfach behoben wurde. Zum Entfernen gibt es
    ``loeschen()``.

    Die Feldliste ``AENDERBAR`` ist die EINZIGE Instanz: der Endpunkt filtert
    ausdruecklich NICHT vor. Zwei Schichten mit unterschiedlicher Meinung sind
    das Muster, das in diesem Projekt schon mehrfach Stunden gekostet hat – ein
    stillschweigend verworfenes Feld meldet "gespeichert", obwohl es das nicht
    ist."""
    un, alle, k = _konto_fuer_schreiben(user)
    k["benutzer_norm"] = un

    unbekannt = [f for f in (felder or {}) if f not in AENDERBAR]
    if unbekannt:
        raise VemasKontoFehler(
            "Unbekannte oder nicht selbst setzbare Felder: %s. Serveradresse, "
            "Anmelde-Endpunkt, die TLS-Pruefung und die Freigabe von "
            "Schreibzugriffen pflegt der Administrator unter Einstellungen → "
            "Vemas." % ", ".join(sorted(unbekannt)))

    if "auth_kind" in felder:
        ak = str(felder.get("auth_kind") or "").strip().lower()
        if ak and ak not in ANMELDEARTEN:
            raise VemasKontoFehler("Anmeldeart muss %s sein."
                                   % " / ".join(ANMELDEARTEN))
        k["auth_kind"] = ak
    if "username" in felder:
        k["username"] = str(felder.get("username") or "").strip()
    if "aktiv" in felder:
        k["aktiv"] = bool(felder.get("aktiv"))

    for f in GEHEIMFELDER:
        if f in felder:
            wert = str(felder.get(f) or "")
            if wert.strip():
                k[f + "_enc"] = verschluesseln(wert)
                # NEUES Kennwort = neuer Anlauf. Ohne dieses Zuruecksetzen bliebe
                # der Zugang nach dem Beheben der Ursache ausgesetzt, und der
                # Benutzer haette keinen erkennbaren Weg zurueck. Nur bei einem
                # WIRKLICH gesetzten Wert – ein leeres Feld heisst
                # "unveraendert" und darf den Aussetzer nicht aufheben.
                k["anmeldefehler"] = 0
                k["ausgesetzt"] = False
                k["ausgesetzt_seit"] = 0
                k["ausgesetzt_grund"] = ""

    # Ein Zugang ohne Serveradresse geht ins Leere. 400 mit Klartext statt einer
    # spaeteren Auswertung, die stillschweigend ueber den Sammelzugang laeuft.
    if not server_konfiguriert():
        raise VemasKontoFehler(
            "Es ist keine VEMAS-Serveradresse hinterlegt – ein eigener Zugang "
            "waere wirkungslos. Ein Administrator traegt den Server unter "
            "Einstellungen → Vemas ein.")

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
                   anmeldefehler: bool = False) -> None:
    """Letzten Zustand am Zugang vermerken (fuer die Oberflaeche).

    ``anmeldefehler=True`` zaehlt gegen den Aussetzer. Wer den Parameter
    weglaesst, zaehlt NICHTS mit; das ist Absicht (fail-safe): ein neuer
    Aufrufer soll einen Zugang nicht versehentlich aussetzen, sondern den
    Anmeldefehler bewusst melden muessen."""
    un = norm_user(user)
    alle = _laden()
    k = alle.get(un)
    if not k:
        return
    if ok:
        k["letzter_erfolg"] = int(time.time())
        k["letzter_fehler"] = ""
        # Ein Erfolg loest den Aussetzer auf – das ist der eigentliche Rueckweg:
        # Kennwort neu eintragen, "Verbindung testen" druecken, fertig.
        k["anmeldefehler"] = 0
        if k.get("ausgesetzt"):
            k["ausgesetzt"] = False
            k["ausgesetzt_seit"] = 0
            k["ausgesetzt_grund"] = ""
            print("[VEMAS] Aussetzer fuer '%s' aufgehoben (Anmeldung wieder "
                  "erfolgreich)" % un, flush=True)
    else:
        k["letzter_fehler"] = (fehler or "")[:500]
        if anmeldefehler:
            k["anmeldefehler"] = int(k.get("anmeldefehler", 0) or 0) + 1
            grenze = max_anmeldefehler()
            if grenze and k["anmeldefehler"] >= grenze and not k.get("ausgesetzt"):
                k["ausgesetzt"] = True
                k["ausgesetzt_seit"] = int(time.time())
                k["ausgesetzt_grund"] = (fehler or "")[:500]
                print("[VEMAS] Persoenlicher Zugang von '%s' nach %d Anmeldefehlern "
                      "ausgesetzt – Abfragen laufen wieder ueber den Sammelzugang."
                      % (un, k["anmeldefehler"]), flush=True)
    alle[un] = k
    try:
        _speichern(alle)
    except Exception as e:  # noqa: BLE001
        print("[VEMAS] Zugangs-Zustand nicht gespeichert: %s" % e, flush=True)


def melde_fehler(user: str, fehler: Exception) -> None:
    """Bequemer Weg fuer Aufrufer: klassifiziert selbst und vermerkt.

    Nur wirksam, wenn der Lauf ueberhaupt den persoenlichen Zugang benutzt hat –
    sonst wuerde ein Fehler des Sammelzugangs dem Benutzer angerechnet."""
    try:
        if not hat_zugang(user):
            return
        merke_ergebnis(user, False, str(fehler or ""),
                       anmeldefehler=ist_anmeldefehler(fehler))
    except Exception:  # noqa: BLE001
        pass


def alle_benutzer() -> list[str]:
    """Normalisierte Namen aller Benutzer mit eigenem Zugang (Admin-Sicht)."""
    return sorted(_laden().keys())


# ── Aufloesung: welcher Zugang gilt fuer diesen Lauf? ───────────────────────
#
# Warum ein eigenes Ergebnis-dict und nicht nur ein Client: der Aufrufer MUSS
# sagen koennen, WELCHER Zugang benutzt wurde. Ein stiller Wechsel auf den
# Sammelzugang liesse den Benutzer Daten sehen, die mit FREMDEN (in der Regel
# weiteren) Berechtigungen geholt wurden – genau die Fehlerklasse "eine Anzeige
# behauptet einen Zustand, den sie nicht kennt".
QUELLE_PERSOENLICH = "persoenlich"
QUELLE_SAMMEL = "sammel"


def _cfg_aus_zugang(k: dict) -> dict:
    """Baut die ``VemasClient``-Konfiguration aus dem gespeicherten Zugang.

    Reihenfolge ist Absicht: Anmeldedaten aus dem Benutzer-Datensatz, ALLES
    UEBRIGE (Adresse, Anmelde-Endpunkt, TLS, Nur-Lesen) aus der
    Administrator-Konfiguration. Ein Benutzer kann damit weder das Ziel noch die
    Schranken verschieben – er haengt nur seine Anmeldung an einen fertig
    konfigurierten Server."""
    c = dict(skill_config())
    ak = (k.get("auth_kind") or "").strip().lower()
    c["auth_kind"] = ak or (c.get("auth_kind") or "basic")
    c["username"] = k.get("username", "")
    c["password"] = entschluesseln(k.get("password_enc", ""))
    c["api_token"] = entschluesseln(k.get("api_token_enc", ""))
    return c


def _sammel_cfg() -> dict:
    """Sammelzugang – mit ERZWUNGENEM Nur-Lesen.

    Siehe Modul-Docstring, Abweichung (2): eine Schreibfreigabe des
    Administrators gilt nur fuer Benutzer mit eigenem Konto. Ueber den
    Sammelzugang wird nie geschrieben, egal was in der Konfiguration steht."""
    c = dict(skill_config())
    c["read_only"] = True
    return c


def sammel_client() -> VemasClient:
    return VemasClient(_sammel_cfg())


def aufloesen(user: str | None = None, trotz_aussetzer: bool = False) -> dict:
    """Welcher VEMAS-Zugang gilt? Rueckgabe:
    ``{client, quelle, hinweis, benutzer, ausgesetzt}``.

    ``user=None`` nimmt den ContextVar (also den Actor des laufenden Auftrags).
    Faellt IMMER auf den Sammelzugang zurueck, wenn der persoenliche nicht
    nutzbar ist – mit einem Hinweis, der den Grund nennt (gleiche Vorgabe wie
    bei SAP: Rueckfall mit Hinweis statt Absage).

    ``trotz_aussetzer=True`` uebergeht den Aussetzer und ist den vom BENUTZER
    ausgeloesten Wegen vorbehalten (Verbindungstest). **Ohne diese Ausnahme gibt
    es keinen Rueckweg:** der Test wuerde den Sammelzugang pruefen, "ok" melden
    und den Aussetzer nie aufloesen. Ein Klick ist EIN Anmeldeversuch;
    gefaehrlich ist die Automatik, die es im Takt wiederholt. Vorgabe ist
    fail-closed – wer den Parameter nicht setzt, bekommt den Rueckfall."""
    if user is None:
        try:
            user = current_vemas_user.get() or ""
        except Exception:  # noqa: BLE001
            user = ""
    un = norm_user(user or "")
    hinweis = ""
    if un and ":" not in un:
        try:
            k = _laden().get(un)
        except Exception:  # noqa: BLE001
            k = None
        if k and _vollstaendig(k):
            if not bool(k.get("aktiv", True)):
                hinweis = ("Dein persoenlicher VEMAS-Zugang steht auf inaktiv – "
                           "es gilt der gemeinsame Zugang.")
            elif k.get("ausgesetzt") and not trotz_aussetzer:
                hinweis = (
                    "Dein persoenlicher VEMAS-Zugang ist nach %d fehlgeschlagenen "
                    "Anmeldungen ausgesetzt – es gilt der gemeinsame Zugang. "
                    "Zugangsdaten unter 'Mein VEMAS-Zugang' pruefen und "
                    "'Verbindung testen' druecken."
                    % int(k.get("anmeldefehler", 0) or 0))
            else:
                try:
                    cfg = _cfg_aus_zugang(k)
                except VemasKontoFehler as e:
                    hinweis = "%s Es gilt vorerst der gemeinsame Zugang." % e
                else:
                    c = VemasClient(cfg)
                    if c.configured:
                        return {"client": c, "quelle": QUELLE_PERSOENLICH,
                                "hinweis": "", "benutzer": un, "ausgesetzt": False}
                    hinweis = ("Es ist keine VEMAS-Serveradresse hinterlegt – "
                               "wende dich an einen Administrator.")
    return {"client": sammel_client(), "quelle": QUELLE_SAMMEL, "hinweis": hinweis,
            "benutzer": un, "ausgesetzt": bool(hinweis)}


def client_fuer_lauf(user: str | None = None) -> VemasClient:
    """Nur der Client – fuer Aufrufer, die den Hinweis nicht brauchen."""
    return aufloesen(user)["client"]


def quelle_text(quelle: str, lang: str = "de") -> str:
    """Kurzbezeichnung fuer die Oberflaeche/den Ergebniskopf."""
    if lang.startswith("en"):
        return ("your personal VEMAS access" if quelle == QUELLE_PERSOENLICH
                else "the shared access")
    return ("dein persoenlicher VEMAS-Zugang" if quelle == QUELLE_PERSOENLICH
            else "der gemeinsame Zugang")


__all__ = [
    "VemasKontoFehler", "VemasError", "current_vemas_user", "norm_user",
    "zugang_info", "speichern", "loeschen", "hat_zugang", "alle_benutzer",
    "merke_ergebnis", "melde_fehler", "ist_anmeldefehler", "max_anmeldefehler",
    "aufloesen", "client_fuer_lauf", "quelle_text", "sammel_client",
    "server_konfiguriert", "QUELLE_PERSOENLICH", "QUELLE_SAMMEL",
    "AENDERBAR", "TEXTFELDER", "GEHEIMFELDER", "ANMELDEARTEN",
]
