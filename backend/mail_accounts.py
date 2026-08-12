"""Postfach-Zugangsdaten je Benutzer (E-Mail-Skill).

**Entscheidung 2026-08-12:** Jeder Benutzer hinterlegt seine EIGENEN
Exchange-Zugangsdaten – kein Dienstkonto mit Impersonation. Das hat einen
klaren Vorteil und einen klaren Preis, beide gehoeren hierher:
  + Jarvis kann NUR auf Postfaecher zugreifen, deren Kennwort ein Mensch
    bewusst hinterlegt hat. Ein Dienstkonto mit ``ApplicationImpersonation``
    koennte technisch jedes Postfach der Firma lesen.
  − Jarvis haelt damit Benutzerkennwoerter. Deshalb liegen sie verschluesselt
    (Fernet/AES-128-CBC + HMAC aus ``cryptography``), die Datei ist 0640 und
    steht in ``_APP_DENY_REL``/``PRIVATE_FILES``/``SHELL_SECRET_PATHS``; ein
    Kennwort verlaesst den Server NIE (kein Endpunkt gibt es heraus, auch nicht
    maskiert – die Laenge allein ist schon eine Aussage).

**KEIN KLARTEXT-RUECKFALL.** Fehlt ``cryptography``, wird das Speichern mit
Klartext abgelehnt, statt das Kennwort unverschluesselt abzulegen. Ein stiller
Rueckfall waere die schlimmste Variante: die Oberflaeche meldet Erfolg, und
niemand erfaehrt, dass die Kennwoerter offen liegen. (``cryptography`` ist
ohnehin in ``requirements.txt`` – es traegt die Lizenzpruefung.)

**Der Serverteil gehoert dem Administrator, der Kontoteil dem Benutzer.**
Adresse/Anmeldename/Kennwort stehen hier; EWS-URL, IMAP-/SMTP-Server und
Kanalwahl kommen aus der Skill-Konfiguration (Reiter "E-Mail"). Der interne
Exchange ist fuer alle derselbe – ihn 200-mal eintragen zu lassen waere eine
Fehlerquelle ohne Nutzen. Nur wo es abweichen darf (Anmeldename), gibt es ein
Feld je Benutzer.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import time
from pathlib import Path

from backend.mail_client import MailFehler, MailKonto

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KONTEN_DATEI = DATA_DIR / "email_accounts.json"
SCHLUESSEL_DATEI = DATA_DIR / ".mailkey"

DATEI_MODUS = 0o640
SCHLUESSEL_MODUS = 0o600

# ── Wer laeuft gerade? ──────────────────────────────────────────────────────
# Dieselbe Mechanik wie ``sandbox.set_tool_user`` und
# ``llm.current_agent_profile``: ``agent.py::_execute_tool`` setzt den Wert pro
# Werkzeug-Aufruf und nimmt ihn im ``finally`` zurueck.
#
# WARUM NICHT ``sandbox.tool_user()``: der ist fuer PRIVILEGIERTE Benutzer
# absichtlich LEER ("keine Einschraenkung"). Ein Postfach ist aber keine
# Rechtefrage, sondern eine Personenfrage – ein Administrator hat genauso genau
# ein eigenes Postfach. Mit ``tool_user()`` haetten Administratoren gar keins.
current_mail_user: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_mail_user", default="")


def norm_user(name: str) -> str:
    """Kontoname ohne Domaenen-Praefix/UPN-Suffix, klein.

    Gleiche Semantik wie ``conv_log.norm_user`` und ``main._norm_login``: derselbe
    Mensch tippt sich mal als ``nexus\\a.bender``, mal als ``a.bender``, mal als
    ``a.bender@nexus.int`` an. Ohne Normalisierung haette er je Tippform ein
    eigenes Postfach-Konto und wuerde seine Regeln nicht wiederfinden.
    """
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
        raise MailFehler(
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
    except MailFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise MailFehler("Schluesseldatei nicht nutzbar (%s): %s"
                         % (SCHLUESSEL_DATEI, e), "fehler") from e


def verschluesseln(klartext: str) -> str:
    if not klartext:
        return ""
    return _fernet().encrypt(klartext.encode("utf-8")).decode("ascii")


def entschluesseln(gespeichert: str) -> str:
    """Kennwort zurueckholen. Bei ungueltigem Wert: sprechender Fehler.

    Der haeufigste Fall ist eine verlorene/ersetzte Schluesseldatei (Restore aus
    einer Sicherung ohne ``.mailkey``). "InvalidToken" sagt niemandem etwas –
    die Meldung nennt deshalb die Abhilfe: Kennwort neu hinterlegen.
    """
    if not gespeichert:
        return ""
    try:
        return _fernet().decrypt(gespeichert.encode("ascii")).decode("utf-8")
    except MailFehler:
        raise
    except Exception as e:  # noqa: BLE001
        raise MailFehler(
            "Das gespeicherte Kennwort laesst sich nicht entschluesseln – "
            "vermutlich wurde die Schluesseldatei data/.mailkey ersetzt oder "
            "fehlt. Bitte das Kennwort im E-Mail-Bereich neu hinterlegen. (%s)"
            % type(e).__name__, "auth") from e


# ── Ablage ──────────────────────────────────────────────────────────────────

def _laden() -> dict:
    try:
        if not KONTEN_DATEI.exists():
            return {}
        d = json.loads(KONTEN_DATEI.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception as e:  # noqa: BLE001
        # Eine beschaedigte Datei darf den Dienst nicht kippen; sie wird aber
        # AUCH NICHT ueberschrieben (das waere Datenverlust ohne Not) – der
        # Aufrufer sieht "kein Konto" und kann es neu hinterlegen.
        print("[Mail] Kontendatei nicht lesbar: %s" % e, flush=True)
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


# Nur diese Felder darf ein Benutzer an seinem Konto setzen. Ohne Whitelist
# nimmt ein PUT beliebige Felder – dieselbe Luecke, die ``scheduler.update_job``
# bis 2026-07-28 hatte (dort liess sich ``owner_privileged`` setzen).
AENDERBAR = ("adresse", "benutzer", "passwort", "kanal", "aktiv",
             "ordner_eingang", "ordner_entwuerfe", "ordner_gesendet")


def _leer(benutzer_norm: str) -> dict:
    return {"benutzer_norm": benutzer_norm, "adresse": "", "benutzer": "",
            "pw_enc": "", "kanal": "", "aktiv": True,
            "ordner_eingang": "", "ordner_entwuerfe": "", "ordner_gesendet": "",
            "angelegt": int(time.time()), "geaendert": 0,
            "letzter_erfolg": 0, "letzter_fehler": ""}


def hat_konto(user: str) -> bool:
    k = _laden().get(norm_user(user))
    return bool(k and (k.get("adresse") or "").strip() and (k.get("pw_enc") or "").strip())


def konto_info(user: str) -> dict:
    """Fuer die Oberflaeche – OHNE Kennwort, auch nicht maskiert.

    ``passwort_gesetzt`` ist die einzige Aussage darueber. Eine maskierte Form
    ("****") wuerde die Laenge verraten, und ein leeres Feld heisst in der
    Oberflaeche "unveraendert" – dafuer braucht es nur ein Ja/Nein.
    """
    k = _laden().get(norm_user(user)) or _leer(norm_user(user))
    return {
        "vorhanden": bool((k.get("adresse") or "").strip()),
        "adresse": k.get("adresse", ""),
        "benutzer": k.get("benutzer", ""),
        "kanal": k.get("kanal", "") or "",
        "aktiv": bool(k.get("aktiv", True)),
        "passwort_gesetzt": bool((k.get("pw_enc") or "").strip()),
        "ordner_eingang": k.get("ordner_eingang", ""),
        "ordner_entwuerfe": k.get("ordner_entwuerfe", ""),
        "ordner_gesendet": k.get("ordner_gesendet", ""),
        "letzter_erfolg": int(k.get("letzter_erfolg", 0) or 0),
        "letzter_fehler": k.get("letzter_fehler", ""),
    }


def speichern(user: str, felder: dict) -> dict:
    """Konto des Benutzers anlegen/aendern. Rueckgabe = ``konto_info``.

    **Leeres Kennwortfeld heisst UNVERAENDERT**, nicht "loeschen". Sonst
    ueberschriebe jedes Speichern der uebrigen Felder (Ordnername, Kanal) das
    Kennwort mit einem Leerstring – genau der Fehler, der in der
    Lizenz-Ausgabestelle beim Dienstkonto-Kennwort behoben wurde. Zum Entfernen
    gibt es ``loeschen()``.
    """
    un = norm_user(user)
    if not un:
        raise MailFehler("Kein Benutzer – Konto kann nicht zugeordnet werden.", "eingabe")

    alle = _laden()
    k = alle.get(un) or _leer(un)
    k["benutzer_norm"] = un

    unbekannt = [f for f in (felder or {}) if f not in AENDERBAR]
    if unbekannt:
        raise MailFehler("Unbekannte Felder: %s" % ", ".join(sorted(unbekannt)), "eingabe")

    if "adresse" in felder:
        adr = str(felder.get("adresse") or "").strip()
        if adr and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", adr):
            raise MailFehler("'%s' ist keine gueltige E-Mail-Adresse." % adr, "eingabe")
        k["adresse"] = adr
    for f in ("benutzer", "ordner_eingang", "ordner_entwuerfe", "ordner_gesendet"):
        if f in felder:
            k[f] = str(felder.get(f) or "").strip()
    if "kanal" in felder:
        kan = str(felder.get("kanal") or "").strip().lower()
        if kan not in ("", "auto", "ews", "imap"):
            raise MailFehler("Kanal muss leer, 'auto', 'ews' oder 'imap' sein.", "eingabe")
        k["kanal"] = kan
    if "aktiv" in felder:
        k["aktiv"] = bool(felder.get("aktiv"))
    if "passwort" in felder:
        pw = str(felder.get("passwort") or "")
        if pw.strip():
            k["pw_enc"] = verschluesseln(pw)

    k["geaendert"] = int(time.time())
    alle[un] = k
    _speichern(alle)
    return konto_info(user)


def loeschen(user: str) -> bool:
    un = norm_user(user)
    alle = _laden()
    if un not in alle:
        return False
    del alle[un]
    _speichern(alle)
    return True


def merke_ergebnis(user: str, ok: bool, fehler: str = "") -> None:
    """Letzten Zustand am Konto vermerken (fuer die Oberflaeche).

    Bewusst nur Zeitpunkt + Fehlertext: WER wann was gemacht hat, steht im
    Regel-Protokoll (mail_rules), nicht hier.
    """
    un = norm_user(user)
    alle = _laden()
    k = alle.get(un)
    if not k:
        return
    if ok:
        k["letzter_erfolg"] = int(time.time())
        k["letzter_fehler"] = ""
    else:
        k["letzter_fehler"] = (fehler or "")[:500]
    alle[un] = k
    try:
        _speichern(alle)
    except Exception as e:  # noqa: BLE001
        print("[Mail] Konto-Zustand nicht gespeichert: %s" % e, flush=True)


def alle_benutzer() -> list[str]:
    """Normalisierte Namen aller Benutzer mit Konto (fuer den Takt)."""
    return sorted(_laden().keys())


# ── Zusammenbau mit der Skill-Konfiguration ─────────────────────────────────

def skill_config() -> dict:
    """Konfiguration des E-Mail-Skills (Server-Teil, Administrator).

    Lazy und fehlertolerant: der Skill kann fehlen oder aus sein – dann gibt es
    ein leeres dict, und ``konto_fuer`` scheitert mit einem Klartext-Grund
    statt mit einem Attributfehler.
    """
    try:
        from backend.config import config  # noqa: PLC0415
        st = config.get_skill_states().get("email", {}) or {}
        return st.get("config", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def skill_aktiv() -> bool:
    try:
        from backend.config import config  # noqa: PLC0415
        return bool((config.get_skill_states().get("email", {}) or {}).get("enabled"))
    except Exception:  # noqa: BLE001
        return False


def _int(wert, vorgabe: int) -> int:
    try:
        return int(str(wert).strip())
    except Exception:  # noqa: BLE001
        return vorgabe


def _bool(wert, vorgabe: bool) -> bool:
    if wert in (None, ""):
        return vorgabe
    if isinstance(wert, bool):
        return wert
    return str(wert).strip().lower() in ("1", "true", "ja", "yes", "on")


def konto_fuer(user: str) -> MailKonto:
    """Baut das vollstaendige ``MailKonto``: Serverteil (Skill) + Benutzerteil.

    Reihenfolge ist Absicht: der Benutzer kann NUR seinen Anmeldenamen, seine
    Adresse, seine Ordnernamen und die Kanalwahl beeinflussen. Serveradressen
    kommen ausschliesslich aus der Administrator-Konfiguration – sonst waere das
    Feld "IMAP-Server" ein Weg, Jarvis mit hinterlegten Firmen-Zugangsdaten an
    einen fremden Server zu schicken (Abfluss der Zugangsdaten).
    """
    un = norm_user(user)
    k = _laden().get(un)
    if not k or not (k.get("adresse") or "").strip():
        raise MailFehler(
            "Fuer diesen Benutzer ist kein Postfach hinterlegt. Im E-Mail-Bereich "
            "Adresse und Kennwort eintragen.", "eingabe")
    if not (k.get("pw_enc") or "").strip():
        raise MailFehler("Fuer dieses Postfach ist kein Kennwort hinterlegt.", "eingabe")
    if not bool(k.get("aktiv", True)):
        raise MailFehler("Das Postfach ist im E-Mail-Bereich auf inaktiv gestellt.", "eingabe")

    c = skill_config()
    return MailKonto(
        adresse=k.get("adresse", ""),
        benutzer=(k.get("benutzer") or "").strip(),
        passwort=entschluesseln(k.get("pw_enc", "")),
        kanal=(k.get("kanal") or c.get("kanal") or "auto"),
        ews_url=(c.get("ews_url") or "").strip(),
        autodiscover=_bool(c.get("autodiscover"), True),
        auth_typ=(c.get("auth_typ") or "auto"),
        verify_ssl=_bool(c.get("verify_ssl"), True),
        imap_host=(c.get("imap_host") or "").strip(),
        imap_port=_int(c.get("imap_port"), 993),
        imap_ssl=_bool(c.get("imap_ssl"), True),
        smtp_host=(c.get("smtp_host") or "").strip(),
        smtp_port=_int(c.get("smtp_port"), 587),
        smtp_starttls=_bool(c.get("smtp_starttls"), True),
        ordner_eingang=(k.get("ordner_eingang") or c.get("ordner_eingang") or "INBOX"),
        ordner_entwuerfe=(k.get("ordner_entwuerfe") or c.get("ordner_entwuerfe") or ""),
        ordner_gesendet=(k.get("ordner_gesendet") or c.get("ordner_gesendet") or ""),
        zeitlimit=_int(c.get("zeitlimit"), 30),
    )


# ── Kategorie-Name aus dem Branding ─────────────────────────────────────────

def kategorie_name() -> str:
    """Name der Kategorie, mit der verarbeitete Mails markiert werden.

    **Vorgabe des Nutzers 2026-08-12: ergibt sich aus dem Branding.** Ein
    White-Label-System, das fremde Mails mit "Jarvis" markiert, verraet das
    Produkt dahinter – die Markierung ist im Postfach des Benutzers sichtbar
    und geht bei einer Weiterleitung mit nach draussen.

    Reihenfolge: Assistenten-Name → Firmenname → "Jarvis". Der Assistenten-Name
    steht vorn, weil er genau dafuer gedacht ist (er traegt auch die
    Begruessungen); der Firmenname ist der naechstbeste Bezug.
    """
    try:
        from backend.config import config  # noqa: PLC0415
        st = config.get_skill_states().get("branding", {}) or {}
        if st.get("enabled"):
            c = st.get("config", {}) or {}
            for feld in ("assistant_name", "company_name"):
                wert = (c.get(feld) or "").strip()
                if wert:
                    # Exchange-Kategorien duerfen kein Komma enthalten – die
                    # Kategorieliste ist selbst komma-getrennt, ein Komma im
                    # Namen zerlegt die Kategorie in zwei.
                    return wert.replace(",", " ")[:64]
    except Exception:  # noqa: BLE001
        pass
    return "Jarvis"
