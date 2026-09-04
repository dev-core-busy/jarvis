"""Persoenlicher SAP-Zugang je Benutzer (Vorrang vor dem Sammelzugang).

**Entscheidung 2026-08-17:** Der in *Einstellungen → SAP* hinterlegte Zugang ist
ab jetzt ein **Read-Only-Sammelbenutzer** und nur noch der RUECKFALL. Wer einen
eigenen SAP-Zugang hinterlegt (Klappabschnitt "Mein SAP-Zugang" in ``/sap``),
arbeitet damit – in ``/sap``, bei den ``sap_*``-Werkzeugen im Chat, in der
BI-Anbindung/Abfrage-Konsole und in zeitversetzten Laeufen (Cron, E-Mail-Regeln,
ueber die Actor-Bindung).

**Warum das ein Sicherheitsgewinn ist:** vorher erbten ALLE SAP-freigegebenen
Benutzer die Berechtigungen EINES Server-Zugangs ("fremde Zugangsdaten als
Vollmacht" – eines der vier Muster aus der Endpunkt-Durchsicht vom 2026-08-04).
Mit eigenem SAP-Benutzer sieht jeder genau die Daten, fuer die er im Zielsystem
berechtigt ist.

**Anders als beim E-Mail-Skill darf der Benutzer hier die SERVERADRESSE setzen**
(Vorgabe des Nutzers). Notwendig, weil der Fall "der Administrator hat gar
nichts konfiguriert" sonst nicht loesbar waere – dann gibt es keine Adresse, an
die man Anmeldedaten haengen koennte. Der Preis ist eine SSRF-Flaeche: ohne
Schranke koennte jeder Freigegebene Jarvis an eine beliebige Adresse schicken.
Deshalb gibt es die **Host-Freigabeliste** des Administrators
(``allowed_hosts`` in der SAP-Skill-Config, siehe ``hosts_erlaubt``):
**leer = niemand**, der bereits konfigurierte Server des Administrators gilt
**implizit** als erlaubt.

**Was der Benutzer NICHT setzen darf:** das ABSCHALTEN der Zertifikatspruefung
(``verify_ssl``/``hana_ssl_validate``) und ``read_only``. Ein freier Host PLUS
abgeschaltete Zertifikatspruefung waere eine Einladung zum
Man-in-the-Middle; die TLS-Vorgabe bleibt Sache des Administrators.

**Ein Serverzertifikat VERANKERN darf er dagegen sehr wohl** (seit 2026-08-23,
``zertifikat_binden`` / ``backend/sap_cert.py``): dabei wird die Pruefung nicht
abgeschaltet, sondern auf genau ein Zertifikat festgelegt – strenger als der
System-Vertrauensspeicher. Ohne diesen Weg haette ein Benutzer mit eigenem
Server und selbst ausgestelltem Zertifikat gar keine Loesung ausser der Bitte an
den Administrator, die Pruefung fuer ALLE abzuschalten. Read-only
ist ohnehin hart im ``sap_client`` erzwungen (OData nur GET, SQL nur
SELECT/WITH, RFC nur Whitelist-Bausteine) – unabhaengig davon, woher die
Zugangsdaten kommen.

**KEIN KLARTEXT-RUECKFALL.** Fehlt ``cryptography``, wird das Speichern
abgelehnt statt das Kennwort unverschluesselt abzulegen (gleiche Begruendung wie
in ``mail_accounts``: ein stiller Rueckfall meldet Erfolg, und niemand erfaehrt,
dass die Kennwoerter offen liegen). ``data/sap_accounts.json`` ist 0640,
``data/.sapkey`` ist 0600, beide stehen in ``_APP_DENY_REL``, ``PRIVATE_FILES``
bzw. ``PRIVATE_FILES_STRENG`` und ``SHELL_SECRET_PATHS``. Kein Endpunkt gibt ein
Kennwort heraus, auch nicht maskiert – die Laenge allein ist schon eine Aussage.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from backend.sap_client import SapClient, SapError, get_sap_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KONTEN_DATEI = DATA_DIR / "sap_accounts.json"
SCHLUESSEL_DATEI = DATA_DIR / ".sapkey"

DATEI_MODUS = 0o640
SCHLUESSEL_MODUS = 0o600


class SapKontoFehler(Exception):
    """Fehler bei der Pflege eines persoenlichen Zugangs.

    ``kategorie``: ``eingabe`` (=> HTTP 400) oder ``fehler`` (=> 500). Getrennt,
    damit die Oberflaeche einen Tippfehler nicht wie einen Serverausfall
    darstellt."""

    def __init__(self, message: str, kategorie: str = "eingabe"):
        self.kategorie = kategorie
        super().__init__(message)


# ── Wer laeuft gerade? ──────────────────────────────────────────────────────
# Gleiche Mechanik wie ``mail_accounts.current_mail_user``: ``agent.py::
# _execute_tool`` setzt den Wert pro Werkzeug-Aufruf und nimmt ihn im
# ``finally`` zurueck.
#
# BEWUSST NICHT ueber ``sandbox.tool_user()``: der ist fuer privilegierte
# Benutzer absichtlich LEER ("keine Einschraenkung"). Ein SAP-Zugang ist aber
# keine Rechtefrage, sondern eine Personenfrage – ein Administrator hat genauso
# einen eigenen SAP-Benutzer. Mit ``tool_user()`` haetten Administratoren gar
# keinen persoenlichen Zugang.
#
# UND NIEMALS ALS WERKZEUG-PARAMETER: sonst koennte das Modell (oder ein per
# Prompt-Injection eingeschmuggelter Satz) waehlen, mit WESSEN Zugangsdaten es
# arbeitet.
current_sap_user: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_sap_user", default="")


def norm_user(name: str) -> str:
    """Kontoname ohne Domaenen-Praefix/UPN-Suffix, klein.

    Gleiche Semantik wie ``mail_accounts.norm_user`` und ``main._norm_login``:
    derselbe Mensch meldet sich mal als ``nexus\\a.bender``, mal als
    ``a.bender@nexus.int`` an – ohne Normalisierung haette er je Tippform einen
    eigenen SAP-Zugang und wuerde seinen eigenen nicht wiederfinden."""
    s = (name or "").strip()
    if not s or ":" in s:          # Kanal-Kennungen (wa:/tg:/api:) unangetastet
        return s.lower()
    return s.split("@")[0].split("\\")[-1].strip().lower()


# ── Verschluesselung ────────────────────────────────────────────────────────

def _fernet():
    """Fernet-Instanz mit dem lokalen Schluessel; legt ihn beim ersten Mal an."""
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        raise SapKontoFehler(
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
    except SapKontoFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise SapKontoFehler("Schluesseldatei nicht nutzbar (%s): %s"
                             % (SCHLUESSEL_DATEI, e), "fehler") from e


def verschluesseln(klartext: str) -> str:
    if not klartext:
        return ""
    return _fernet().encrypt(klartext.encode("utf-8")).decode("ascii")


def entschluesseln(gespeichert: str) -> str:
    """Kennwort zurueckholen. Bei ungueltigem Wert: sprechender Fehler.

    Haeufigster Fall ist eine verlorene/ersetzte Schluesseldatei (Restore ohne
    ``.sapkey``). "InvalidToken" sagt niemandem etwas – die Meldung nennt
    deshalb die Abhilfe."""
    if not gespeichert:
        return ""
    try:
        return _fernet().decrypt(gespeichert.encode("ascii")).decode("utf-8")
    except SapKontoFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise SapKontoFehler(
            "Das gespeicherte SAP-Kennwort laesst sich nicht entschluesseln – "
            "vermutlich wurde die Schluesseldatei data/.sapkey ersetzt oder sie "
            "fehlt. Bitte den Zugang unter 'Mein SAP-Zugang' neu hinterlegen. "
            "(%s)" % type(e).__name__, "fehler") from e


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
        print("[SAP] Kontendatei nicht lesbar: %s" % e, flush=True)
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
# nimmt ein POST beliebige Felder – dieselbe Luecke, die
# ``scheduler.update_job`` bis 2026-07-28 hatte (dort liess sich
# ``owner_privileged`` setzen).
#
# NICHT enthalten und das ist Absicht:
#   verify_ssl / hana_ssl_validate  – TLS-Pruefung bleibt Sache des Admins
#   read_only                       – hart im sap_client erzwungen
TEXTFELDER = (
    "sap_product",
    # OData
    "odata_base_url", "odata_service", "auth_kind", "username", "sap_client",
    # HANA
    "hana_host", "hana_user", "hana_schema",
    # RFC
    "rfc_ashost", "rfc_sysnr", "rfc_client", "rfc_user", "rfc_lang",
)
GEHEIMFELDER = ("password", "bearer_token", "hana_password", "rfc_password")
AENDERBAR = ("connection_type", "aktiv", "hana_port") + TEXTFELDER + GEHEIMFELDER

KANAELE = ("odata", "hana", "rfc")


# ── Aussetzer nach wiederholten Anmeldefehlern ──────────────────────────────
#
# WARUM ES DAS GIBT: derselbe Vorfall wie beim E-Mail-Postfach (2026-08-16), nur
# mit SAP als Gegenstelle. Zeitversetzte Laeufe (Cron, E-Mail-Regeln) melden sich
# im Takt an; ist das Kennwort falsch oder abgelaufen, erzeugt JEDER Lauf einen
# weiteren abgelehnten Logon. SAP zaehlt die mit (``login/fails_to_user_lock``,
# typisch 3–5) und sperrt den SAP-Benutzer. Damit haelt eine einzige vergessene
# Regel einen SAP-Zugang dauerhaft gesperrt.
#
# GEZAEHLT WIRD NUR EIN ANMELDEFEHLER (``ist_anmeldefehler``). Ein unerreichbarer
# Server, ein Zeitlimit oder ein Zertifikatsfehler sind keine Fehlversuche im
# Sinne der Sperrpolitik – wer die mitzaehlt, setzt den Zugang bei jeder
# Netzstoerung aus.
#
# Der Aussetzer ist hier ZUGLEICH die Rueckfall-Schwelle: ab ihm laufen die
# Abfragen wieder ueber den Sammelzugang (mit deutlichem Hinweis), statt
# fehlzuschlagen.
MAX_ANMELDEFEHLER = 3


def max_anmeldefehler() -> int:
    """Schwelle als FUNKTION, nicht als beim Import eingefrorener Wert.

    Gleiche Begruendung wie ``documents.retention_days()``: ueber die Umgebung
    gesetzt soll der Wert ohne Dienstneustart gelten. ``0`` schaltet den
    Aussetzer ab."""
    try:
        n = int(os.environ.get("JARVIS_SAP_MAX_AUTHFEHLER", MAX_ANMELDEFEHLER))
    except (TypeError, ValueError):
        return MAX_ANMELDEFEHLER
    return max(0, min(n, 50))


# Muster, die einen echten Anmeldefehler belegen. Bewusst KNAPP gehalten und
# fail-safe in Richtung "nicht zaehlen": ein falsch gezaehlter Netzfehler wuerde
# den Zugang aussetzen, obwohl die Zugangsdaten stimmen.
_AUTH_MUSTER = re.compile(
    r"authentication failed|invalid username or password|"
    r"name or password is incorrect|password logon no longer possible|"
    r"user is locked|account is locked|rfc_logon_failure|logon failed|"
    r"invalid credentials", re.I)

# ⚠ BERECHTIGUNG IST NICHT ANMELDUNG (Vorfall 2026-08-25, ECHT).
#
# Gemeldet: die SAP-Analyse eines Benutzers endete immer wieder mit "Ausgesetzt
# nach fehlgeschlagenen Anmeldungen", waehrend auf dem SAP-System KEIN Fehler
# feststellbar war und "Verbindung testen" anschliessend klaglos durchlief.
#
# Ursache: als Anmeldefehler galt (a) jedes HTTP 403 und (b) der Text
# "not authorized". Beides sind AUTORISIERUNGS-Fehler: der Benutzer war
# angemeldet, ihm fehlte nur die Berechtigung fuer diesen Service, diese Tabelle
# oder dieses Schema. HANA meldet das als Fehler 258 "insufficient privilege:
# Not authorized", SAP Gateway als 403 – in beiden Faellen steht auf der
# SAP-Seite kein einziger fehlgeschlagener Logon, deshalb war die Meldung von
# aussen nicht erklaerbar. Ein Analyselauf probiert mehrere Services/Tabellen
# durch; drei Fehlgriffe reichen fuer den Aussetzer. Der Verbindungstest prueft
# dagegen nur $metadata bzw. einen Trivial-SELECT – der laeuft, hebt den
# Aussetzer auf, und der naechste Lauf setzt ihn erneut. Genau der Kreislauf.
#
# WARUM DAS OHNE RISIKO IST: der Aussetzer existiert allein, damit
# ``login/fails_to_user_lock`` den SAP-Benutzer nicht sperrt. Dieser Zaehler
# steigt nur bei einem ABGELEHNTEN LOGON (HTTP 401 / "authentication failed").
# Ein 403 ist ein angenommener Logon – es zaehlt auf der SAP-Seite nichts hoch,
# also darf es hier auch nichts hochzaehlen. Wir verlieren keinen Schutz, wir
# hoeren nur auf, den falschen Fall zu zaehlen.
#
# Die Ausschlussliste GEWINNT gegen ``_AUTH_MUSTER`` (fail-safe in Richtung
# "nicht zaehlen"), aber NICHT gegen HTTP 401 – das ist unzweideutig die
# Anmeldung, egal was im Rumpf steht.
_AUTHZ_MUSTER = re.compile(
    r"insufficient privilege|not authorized|no authorization|"
    r"missing authorization|authorization (check )?fail|"
    r"keine berechtigung|nicht berechtigt|no rfc authorization", re.I)

# Nur diese Status zaehlen. 403 steht bewusst NICHT hier (siehe oben).
_AUTH_STATUS = (401,)


def ist_anmeldefehler(fehler: Exception) -> bool:
    """Ist das ein ANMELDE-Fehler (zaehlt gegen den Aussetzer)?

    Abgegrenzt gegen den BERECHTIGUNGS-Fehler, der wie einer aussieht, aber
    keiner ist – siehe die Begruendung bei ``_AUTHZ_MUSTER``.

    OData liefert 401 (HANA/RFC melden ueber ``SapError(0, text)``, dort
    entscheidet der Text: hdbcli "authentication failed", pyrfc "Name or
    password is incorrect")."""
    text = str(fehler or "")
    try:
        status = int(getattr(fehler, "status", 0) or 0)
    except Exception:  # noqa: BLE001
        status = 0
    if status in _AUTH_STATUS:
        return True
    if _AUTHZ_MUSTER.search(text):
        return False
    return bool(_AUTH_MUSTER.search(text))


def _leer(un: str) -> dict:
    return {"benutzer_norm": un, "connection_type": "", "aktiv": True,
            "angelegt": int(time.time()), "geaendert": 0,
            "letzter_erfolg": 0, "letzter_fehler": "",
            "anmeldefehler": 0, "ausgesetzt": False, "ausgesetzt_seit": 0,
            "ausgesetzt_grund": ""}


def hat_zugang(user: str) -> bool:
    """Hat dieser Benutzer einen (vollstaendigen) eigenen Zugang hinterlegt?"""
    k = _laden().get(norm_user(user))
    return bool(k and _vollstaendig(k))


def _vollstaendig(k: dict) -> bool:
    """Reicht der gespeicherte Zugang, um ueberhaupt zu verbinden?

    Dieselben Bedingungen wie ``SapClient.configured`` – nur ohne Client-Objekt,
    damit die Pruefung ohne Entschluesselung auskommt."""
    ct = (k.get("connection_type") or "").strip().lower()
    if ct == "odata":
        return bool((k.get("odata_base_url") or "").strip())
    if ct == "hana":
        return bool((k.get("hana_host") or "").strip() and (k.get("hana_user") or "").strip())
    if ct == "rfc":
        return bool((k.get("rfc_ashost") or "").strip() and (k.get("rfc_user") or "").strip())
    return False


# ── Host-Freigabeliste des Administrators ───────────────────────────────────

def skill_config() -> dict:
    """Konfiguration des SAP-Skills (Sammelzugang + Freigabeliste).

    Lazy und fehlertolerant: der Skill kann fehlen oder aus sein – dann gibt es
    ein leeres dict, und die Aufloesung meldet einen Klartext-Grund."""
    try:
        return get_sap_config() or {}
    except Exception:  # noqa: BLE001
        return {}


def _host_von(wert: str) -> str:
    """Hostname aus einer URL ODER einem blossen Host[:Port].

    Ein Administrator traegt ``exchange.firma.de`` ein, ein Benutzer klebt
    vielleicht ``https://s4.firma.de:44300/sap/opu/odata`` ins Feld – beide
    muessen auf denselben Hostnamen fuehren, sonst ist die Freigabeliste ein
    Zufallsspiel."""
    s = (wert or "").strip()
    if not s:
        return ""
    if "://" in s:
        try:
            h = urlparse(s).hostname or ""
        except Exception:  # noqa: BLE001
            h = ""
        return h.strip().lower()
    s = s.split("/")[0]
    # IPv6 in Klammern: [::1]:30015
    if s.startswith("["):
        return s.split("]")[0].lstrip("[").strip().lower()
    return s.split(":")[0].strip().lower()


def hosts_admin() -> list[str]:
    """Ausdrueckliche Freigabeliste des Administrators (``allowed_hosts``)."""
    roh = skill_config().get("allowed_hosts") or ""
    if isinstance(roh, (list, tuple)):
        teile = [str(x) for x in roh]
    else:
        teile = re.split(r"[,\n;]+", str(roh))
    out = []
    for t in teile:
        eintrag = t.strip()
        # Erst die Platzhalter-Schreibweise abstreifen, DANN den Host ermitteln:
        # sonst bliebe "*.firma.de" als Hostname stehen und wuerde nie treffen
        # (der Eintrag deckt Unterdomaenen ohnehin ab, siehe host_ok).
        if eintrag.startswith("*"):
            eintrag = eintrag[1:]
        eintrag = eintrag.lstrip(".")
        # Auch ein versehentlich eingetragener URL-Eintrag soll wirken.
        h = _host_von(eintrag)
        if h:
            out.append(h)
    return sorted(set(x for x in out if x))


def hosts_implizit() -> list[str]:
    """Hosts des Sammelzugangs – gelten IMMER als erlaubt.

    Sonst muesste der Administrator seinen eigenen Server doppelt eintragen,
    und niemand koennte auch nur seine Anmeldedaten fuer das Haussystem
    hinterlegen (das ist der haeufigste Fall ueberhaupt)."""
    c = skill_config()
    out = []
    for feld in ("odata_base_url", "hana_host", "rfc_ashost"):
        h = _host_von(str(c.get(feld) or ""))
        if h:
            out.append(h)
    return sorted(set(out))


def hosts_erlaubt() -> list[str]:
    """Alle erlaubten Hosts (Freigabeliste + Sammelzugang).

    **LEER = NIEMAND.** Konsistent zu allen uebrigen Freigabefeldern des
    Projekts (Login, SAP-Zugriff, E-Mail, Wissens-Editoren – Vorgabe seit
    2026-07-29). Ohne Eintrag und ohne konfigurierten Sammelzugang kann also
    niemand einen eigenen Zugang hinterlegen; das ist der bewusst
    abschaltende Ausgangszustand."""
    return sorted(set(hosts_admin()) | set(hosts_implizit()))


def host_ok(host: str, erlaubt: list[str] | None = None) -> bool:
    """Passt ``host`` auf die Freigabeliste?

    Ein Eintrag deckt den Host selbst UND seine Unterdomaenen ab
    (``firma.de`` erlaubt ``s4.firma.de``) – so laesst sich eine Domaene in
    einer Zeile freigeben. Bewusst keine allgemeinen Platzhalter: ``*`` waere
    ein Freibrief, der wie eine Einschraenkung aussieht."""
    h = _host_von(host)
    if not h:
        return False
    for e in (erlaubt if erlaubt is not None else hosts_erlaubt()):
        if h == e or h.endswith("." + e):
            return True
    return False


def _hosts_im_zugang(k: dict) -> list[str]:
    """Hosts, die dieser Zugang anspricht (nur der aktive Kanal zaehlt)."""
    ct = (k.get("connection_type") or "").strip().lower()
    feld = {"odata": "odata_base_url", "hana": "hana_host", "rfc": "rfc_ashost"}.get(ct)
    if not feld:
        return []
    h = _host_von(str(k.get(feld) or ""))
    return [h] if h else []


# ── Verankerte Serverzertifikate ────────────────────────────────────────────
#
# Verankern ist ausdruecklich KEINE Aufweichung: die Pruefung bleibt an, es gilt
# genau ein Zertifikat. Deshalb darf der Benutzer es selbst tun, waehrend
# `verify_ssl` (= Pruefung ABschalten) weiterhin nur der Administrator setzt.
#
# **Das PEM kommt nie aus dem Request** – `sap_cert.bestaetigen` holt das
# Zertifikat selbst und vergleicht den Fingerabdruck, den der Mensch gesehen
# hat. Genau deshalb stehen `cert_odata`/`cert_hana` NICHT in `AENDERBAR`: ueber
# `speichern()` liesse sich sonst ein beliebiger Vertrauensanker einschleusen.

def _cert_ansicht(k: dict) -> dict:
    """Was die Oberflaeche ueber die Anker erfaehrt (eigener + Administrator)."""
    from backend import sap_cert
    c = skill_config()
    out = {}
    for kanal in sap_cert.KANAELE:
        feld = "cert_" + kanal
        out[kanal] = {"eigen": sap_cert.info(k.get(feld)),
                      "admin": sap_cert.info(c.get(feld))}
    return out


def _konto_fuer_schreiben(user: str) -> tuple[str, dict, dict]:
    un = norm_user(user)
    if not un:
        raise SapKontoFehler("Kein Benutzer – Zugang kann nicht zugeordnet werden.")
    if ":" in un:
        raise SapKontoFehler("Fuer diese Kennung kann kein SAP-Zugang hinterlegt werden.")
    alle = _laden()
    return un, alle, (alle.get(un) or _leer(un))


def host_pruefen(host: str) -> None:
    """Dieselbe Schranke wie beim Speichern eines Zugangs (SSRF-Flaeche).

    Ohne sie waere die Zertifikatspruefung ein Portscanner fuer jeden
    SAP-freigegebenen Benutzer – man bekaeme fuer jede Adresse eine Aussage
    darueber, ob dort TLS lauscht."""
    erlaubt = hosts_erlaubt()
    if host_ok(host, erlaubt):
        return
    raise SapKontoFehler(
        "Der Server '%s' ist nicht freigegeben. %s" % (
            host,
            ("Freigegeben sind: " + ", ".join(erlaubt)) if erlaubt else
            "Es ist bisher KEIN Server freigegeben – ein Administrator muss die "
            "Freigabeliste unter Einstellungen → SAP fuellen (leer = niemand)."))


def zertifikat_binden(user: str, kanal: str, host: str, port: int,
                      fingerprint: str) -> dict:
    """Zertifikat des Servers als Anker im EIGENEN Zugang hinterlegen."""
    from backend import sap_cert
    if kanal not in sap_cert.KANAELE:
        raise SapKontoFehler("Unbekannter Kanal '%s'." % kanal)
    host_pruefen(host)
    un, alle, k = _konto_fuer_schreiben(user)
    try:
        eintrag = sap_cert.bestaetigen(host, int(port), fingerprint, kanal)
    except sap_cert.ZertFehler as e:
        raise SapKontoFehler(str(e)) from None
    k["benutzer_norm"] = un
    k["cert_" + kanal] = eintrag
    k["geaendert"] = int(time.time())
    alle[un] = k
    _speichern(alle)
    return zugang_info(user)


def zertifikat_loesen(user: str, kanal: str) -> dict:
    """Eigenen Anker entfernen – danach gilt wieder die normale Pruefung
    (bzw. der Anker des Administrators, falls er auf denselben Server zeigt)."""
    from backend import sap_cert
    if kanal not in sap_cert.KANAELE:
        raise SapKontoFehler("Unbekannter Kanal '%s'." % kanal)
    un, alle, k = _konto_fuer_schreiben(user)
    if k.pop("cert_" + kanal, None) is not None:
        k["geaendert"] = int(time.time())
        alle[un] = k
        _speichern(alle)
    return zugang_info(user)


# ── Lesen fuer die Oberflaeche ──────────────────────────────────────────────

def klartext(user: str, feld: str) -> tuple[str, str]:
    """Ein gespeichertes Geheimnis dieses Benutzers im Klartext. (wert, fehler)

    ⚠ AUSDRUECKLICHE ANWEISUNG DES BETREIBERS (2026-09-04): das Auge am
    Kennwortfeld soll das GESPEICHERTE Kennwort zeigen. Die Zusage im Modulkopf
    ("kein Endpunkt gibt ein Kennwort heraus") gilt fuer ``zugang_info`` und
    jede Uebersicht unveraendert weiter – herausgegeben wird nur auf diesen
    einen, benannten Abruf, und der Aufrufer (``/api/secret/reveal``)
    protokolliert ihn.

    DIE FUNKTION LIEGT HIER UND NICHT IM ABRUF-ENDPUNKT: nur dieses Modul kennt
    seine Feldnamen (``password_enc`` & Co.) und seinen Schluessel. Eine
    zentrale Fassung muesste die Interna von vier Modulen nachbauen – und liefe
    beim naechsten Feld auseinander.

    Fail-closed: nur Felder aus ``GEHEIMFELDER``, nichts anderes.
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
    """Fuer die Oberflaeche – OHNE Kennwoerter, auch nicht maskiert.

    ``*_gesetzt`` ist die einzige Aussage darueber. Eine maskierte Form
    ("****") wuerde die Laenge verraten, und ein leeres Feld heisst in der
    Oberflaeche "unveraendert" – dafuer braucht es nur ein Ja/Nein.

    (Den Klartext gibt ``klartext()`` heraus – ausdruecklich, einzeln und
    protokolliert.)"""
    un = norm_user(user)
    k = _laden().get(un) or _leer(un)
    erlaubt = hosts_erlaubt()
    hosts = _hosts_im_zugang(k)
    info = {
        "vorhanden": bool(_vollstaendig(k)),
        "connection_type": (k.get("connection_type") or "").strip().lower(),
        "aktiv": bool(k.get("aktiv", True)),
        "hana_port": int(k.get("hana_port") or 443),
        "passwort_gesetzt": bool((k.get("password_enc") or "").strip()),
        "bearer_gesetzt": bool((k.get("bearer_token_enc") or "").strip()),
        "hana_passwort_gesetzt": bool((k.get("hana_password_enc") or "").strip()),
        "rfc_passwort_gesetzt": bool((k.get("rfc_password_enc") or "").strip()),
        "letzter_erfolg": int(k.get("letzter_erfolg", 0) or 0),
        "letzter_fehler": k.get("letzter_fehler", ""),
        "anmeldefehler": int(k.get("anmeldefehler", 0) or 0),
        "max_anmeldefehler": max_anmeldefehler(),
        "ausgesetzt": bool(k.get("ausgesetzt")),
        "ausgesetzt_seit": int(k.get("ausgesetzt_seit", 0) or 0),
        "ausgesetzt_grund": k.get("ausgesetzt_grund", ""),
        # Damit die Oberflaeche sagen kann, WAS ueberhaupt eingetragen werden
        # darf, statt den Benutzer in ein 400 laufen zu lassen.
        "erlaubte_hosts": erlaubt,
        "host_ok": (not hosts) or all(host_ok(h, erlaubt) for h in hosts),
        # Verankerte Serverzertifikate – OHNE PEM (`sap_cert.info`). Getrennt
        # nach eigenem Anker und dem des Administrators: die Oberflaeche muss
        # sagen koennen, WESSEN Anker gerade gilt, sonst sucht der Benutzer den
        # Loesen-Knopf fuer etwas, das ihm gar nicht gehoert.
        "cert": _cert_ansicht(k),
    }
    for f in TEXTFELDER:
        info[f] = k.get(f, "")
    return info


# ── Schreiben ───────────────────────────────────────────────────────────────

def speichern(user: str, felder: dict) -> dict:
    """Zugang des Benutzers anlegen/aendern. Rueckgabe = ``zugang_info``.

    **Leeres Kennwortfeld heisst UNVERAENDERT**, nicht "loeschen". Sonst
    ueberschriebe jedes Speichern der uebrigen Felder (Schema, Mandant) das
    Kennwort mit einem Leerstring – derselbe Fehler, der beim Dienstkonto der
    Lizenz-Ausgabestelle und beim Postfach behoben wurde. Zum Entfernen gibt es
    ``loeschen()``.

    Die Feldliste ``AENDERBAR`` ist die EINZIGE Instanz: der Endpunkt filtert
    ausdruecklich NICHT vor. Zwei Schichten mit unterschiedlicher Meinung sind
    das Muster, das in diesem Projekt schon mehrfach Stunden gekostet hat – ein
    stillschweigend verworfenes Feld meldet "gespeichert", obwohl es das nicht
    ist."""
    un = norm_user(user)
    if not un:
        raise SapKontoFehler("Kein Benutzer – Zugang kann nicht zugeordnet werden.")
    if ":" in un:
        # wa:/tg:/api: – Kanal-Kennungen sind keine Personen mit SAP-Benutzer.
        raise SapKontoFehler("Fuer diese Kennung kann kein SAP-Zugang hinterlegt werden.")

    alle = _laden()
    k = alle.get(un) or _leer(un)
    k["benutzer_norm"] = un

    unbekannt = [f for f in (felder or {}) if f not in AENDERBAR]
    if unbekannt:
        raise SapKontoFehler(
            "Unbekannte oder nicht selbst setzbare Felder: %s. Das ABSCHALTEN "
            "der Zertifikatspruefung, Nur-Lesen und die Freigabeliste pflegt der "
            "Administrator; ein Serverzertifikat verankerst du ueber den Knopf "
            "„Zertifikat pruefen\" (das ist strenger, nicht schwaecher)."
            % ", ".join(sorted(unbekannt)))

    if "connection_type" in felder:
        ct = str(felder.get("connection_type") or "").strip().lower()
        if ct and ct not in KANAELE:
            raise SapKontoFehler("Zugangsart muss %s sein."
                                 % " / ".join(KANAELE))
        k["connection_type"] = ct
    if "auth_kind" in felder:
        ak = str(felder.get("auth_kind") or "").strip().lower()
        if ak and ak not in ("basic", "bearer"):
            raise SapKontoFehler("Anmeldeart muss 'basic' oder 'bearer' sein.")
        k["auth_kind"] = ak
    for f in TEXTFELDER:
        if f in felder and f != "auth_kind":
            k[f] = str(felder.get(f) or "").strip()
    if "hana_port" in felder:
        try:
            p = int(str(felder.get("hana_port") or 443).strip())
        except (TypeError, ValueError):
            raise SapKontoFehler("HANA-Port muss eine Zahl sein.") from None
        if not 1 <= p <= 65535:
            raise SapKontoFehler("HANA-Port muss zwischen 1 und 65535 liegen.")
        k["hana_port"] = p
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

    # ── Host-Freigabe: beim Speichern pruefen, nicht erst beim Verbinden ──
    # Ein 400 mit Klartext ist hier die richtige Antwort: der Benutzer sieht
    # sofort, welche Hosts freigegeben sind, statt spaeter eine Auswertung zu
    # starten, die stillschweigend ueber den Sammelzugang laeuft.
    erlaubt = hosts_erlaubt()
    for h in _hosts_im_zugang(k):
        if not host_ok(h, erlaubt):
            raise SapKontoFehler(
                "Der Server '%s' ist nicht freigegeben. %s" % (
                    h,
                    ("Freigegeben sind: " + ", ".join(erlaubt)) if erlaubt else
                    "Es ist bisher KEIN Server freigegeben – ein Administrator "
                    "muss die Freigabeliste unter Einstellungen → SAP fuellen "
                    "(leer = niemand)."))

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

    ``anmeldefehler=True`` zaehlt gegen den Aussetzer – siehe Begruendung bei
    ``MAX_ANMELDEFEHLER``. Wer den Parameter weglaesst, zaehlt NICHTS mit; das
    ist Absicht (fail-safe): ein neuer Aufrufer soll einen Zugang nicht
    versehentlich aussetzen, sondern den Anmeldefehler bewusst melden muessen."""
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
            print("[SAP] Aussetzer fuer '%s' aufgehoben (Anmeldung wieder erfolgreich)"
                  % un, flush=True)
    else:
        k["letzter_fehler"] = (fehler or "")[:500]
        if anmeldefehler:
            k["anmeldefehler"] = int(k.get("anmeldefehler", 0) or 0) + 1
            grenze = max_anmeldefehler()
            if grenze and k["anmeldefehler"] >= grenze and not k.get("ausgesetzt"):
                k["ausgesetzt"] = True
                k["ausgesetzt_seit"] = int(time.time())
                k["ausgesetzt_grund"] = (fehler or "")[:500]
                print("[SAP] Persoenlicher Zugang von '%s' nach %d Anmeldefehlern "
                      "ausgesetzt – Abfragen laufen wieder ueber den Sammelzugang, "
                      "damit der SAP-Benutzer nicht gesperrt wird."
                      % (un, k["anmeldefehler"]), flush=True)
    alle[un] = k
    try:
        _speichern(alle)
    except Exception as e:  # noqa: BLE001
        print("[SAP] Zugangs-Zustand nicht gespeichert: %s" % e, flush=True)


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
    """Normalisierte Namen aller Benutzer mit eigenem Zugang (fuer die Admin-Sicht)."""
    return sorted(_laden().keys())


# ── Aufloesung: welcher Zugang gilt fuer diesen Lauf? ───────────────────────

# Warum ein eigenes Ergebnis-dict und nicht nur ein Client: der Aufrufer MUSS
# sagen koennen, WELCHER Zugang benutzt wurde. Ein stiller Wechsel auf den
# Sammelzugang liesse den Benutzer Zahlen sehen, die mit FREMDEN (in der Regel
# weiteren) SAP-Berechtigungen geholt wurden – ohne dass er es merkt. Genau die
# Fehlerklasse "eine Anzeige behauptet einen Zustand, den sie nicht kennt".
QUELLE_PERSOENLICH = "persoenlich"
QUELLE_SAMMEL = "sammel"


def _cfg_aus_zugang(k: dict) -> dict:
    """Baut die ``SapClient``-Konfiguration aus dem gespeicherten Zugang.

    Reihenfolge ist Absicht: die Kennwoerter und Adressen kommen aus dem
    Benutzer-Datensatz, die TLS-Vorgaben und ``read_only`` ausschliesslich aus
    der Administrator-Konfiguration (siehe Modul-Docstring)."""
    c = skill_config()
    cfg = {
        "connection_type": (k.get("connection_type") or "").strip().lower(),
        "sap_product": (k.get("sap_product") or c.get("sap_product") or ""),
        "read_only": True,
        # TLS: Vorgabe des Administrators, Standard AN.
        "verify_ssl": c.get("verify_ssl", True),
        "hana_encrypt": c.get("hana_encrypt", True),
        "hana_ssl_validate": c.get("hana_ssl_validate", True),
        # Verankertes Serverzertifikat: EIGENER Anker vor dem des Administrators.
        # Der Rueckfall auf dessen Anker ist Absicht – wer denselben Server
        # benutzt, soll ihn nicht ein zweites Mal bestaetigen muessen. Ob ein
        # Anker ueberhaupt gilt, entscheidet der Ziel-Vergleich im sap_client
        # (Host/Port), nicht diese Zuweisung.
        "cert_odata": k.get("cert_odata") or c.get("cert_odata"),
        "cert_hana": k.get("cert_hana") or c.get("cert_hana"),
    }
    for f in TEXTFELDER:
        if f == "sap_product":
            continue
        cfg[f] = k.get(f, "")
    cfg["hana_port"] = int(k.get("hana_port") or 443)
    cfg["password"] = entschluesseln(k.get("password_enc", ""))
    cfg["bearer_token"] = entschluesseln(k.get("bearer_token_enc", ""))
    cfg["hana_password"] = entschluesseln(k.get("hana_password_enc", ""))
    cfg["rfc_password"] = entschluesseln(k.get("rfc_password_enc", ""))
    if not (cfg.get("auth_kind") or "").strip():
        cfg["auth_kind"] = "bearer" if cfg["bearer_token"] else "basic"
    return cfg


def aufloesen(user: str | None = None, trotz_aussetzer: bool = False) -> dict:
    """Welcher SAP-Zugang gilt? Rueckgabe:
    ``{client, quelle, hinweis, benutzer, ausgesetzt}``.

    ``user=None`` nimmt den ContextVar (also den Actor des laufenden Auftrags).
    Faellt IMMER auf den Sammelzugang zurueck, wenn der persoenliche nicht
    nutzbar ist – mit einem Hinweis, der den Grund nennt (Vorgabe des Nutzers
    2026-08-17: Rueckfall mit Hinweis statt Absage).

    ``trotz_aussetzer=True`` uebergeht den Aussetzer und ist den vom BENUTZER
    ausgeloesten Wegen vorbehalten (Verbindungstest). **Ohne diese Ausnahme gibt
    es keinen Rueckweg:** der Test wuerde den Sammelzugang pruefen, "ok" melden
    und den Aussetzer nie aufloesen. Ein Klick ist EIN Anmeldeversuch;
    gefaehrlich ist die Automatik, die es im Takt wiederholt. Vorgabe ist
    fail-closed – wer den Parameter nicht setzt, bekommt den Rueckfall."""
    if user is None:
        try:
            user = current_sap_user.get() or ""
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
                hinweis = ("Dein persoenlicher SAP-Zugang steht auf inaktiv – "
                           "es gilt der gemeinsame Lesezugang.")
            elif k.get("ausgesetzt") and not trotz_aussetzer:
                hinweis = (
                    "Dein persoenlicher SAP-Zugang ist nach %d fehlgeschlagenen "
                    "Anmeldungen ausgesetzt (damit der SAP-Benutzer nicht gesperrt "
                    "wird) – es gilt der gemeinsame Lesezugang. Kennwort unter "
                    "'Mein SAP-Zugang' pruefen und 'Verbindung testen' druecken."
                    % int(k.get("anmeldefehler", 0) or 0))
            elif not all(host_ok(h) for h in _hosts_im_zugang(k)):
                # Die Freigabeliste kann sich NACH dem Speichern geaendert haben.
                hinweis = ("Der Server deines persoenlichen SAP-Zugangs ist nicht "
                           "mehr freigegeben – es gilt der gemeinsame Lesezugang.")
            else:
                try:
                    cfg = _cfg_aus_zugang(k)
                except SapKontoFehler as e:
                    hinweis = "%s Es gilt vorerst der gemeinsame Lesezugang." % e
                else:
                    c = SapClient(cfg)
                    if c.configured:
                        return {"client": c, "quelle": QUELLE_PERSOENLICH,
                                "hinweis": "", "benutzer": un, "ausgesetzt": False}
                    hinweis = ("Dein persoenlicher SAP-Zugang ist unvollstaendig – "
                               "es gilt der gemeinsame Lesezugang.")
    return {"client": SapClient(), "quelle": QUELLE_SAMMEL, "hinweis": hinweis,
            "benutzer": un, "ausgesetzt": bool(hinweis)}


def client_fuer_lauf(user: str | None = None) -> SapClient:
    """Nur der Client – fuer Aufrufer, die den Hinweis nicht brauchen."""
    return aufloesen(user)["client"]


def quelle_text(quelle: str, lang: str = "de") -> str:
    """Kurzbezeichnung fuer die Oberflaeche/den Ergebniskopf."""
    if lang.startswith("en"):
        return ("your personal SAP access" if quelle == QUELLE_PERSOENLICH
                else "the shared read-only access")
    return ("dein persoenlicher SAP-Zugang" if quelle == QUELLE_PERSOENLICH
            else "der gemeinsame Lesezugang")


__all__ = [
    "SapKontoFehler", "SapError", "current_sap_user", "norm_user",
    "zugang_info", "speichern", "loeschen", "hat_zugang", "alle_benutzer",
    "merke_ergebnis", "melde_fehler", "ist_anmeldefehler", "max_anmeldefehler",
    "aufloesen", "client_fuer_lauf", "quelle_text",
    "hosts_erlaubt", "hosts_admin", "hosts_implizit", "host_ok",
    "QUELLE_PERSOENLICH", "QUELLE_SAMMEL", "AENDERBAR", "TEXTFELDER",
    "GEHEIMFELDER", "KANAELE",
]
