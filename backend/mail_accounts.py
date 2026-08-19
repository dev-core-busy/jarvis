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
import secrets
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
        if not isinstance(d, dict):
            return {}
        if _migrieren(d):
            try:
                _speichern(d)
            except Exception as e:  # noqa: BLE001
                # Nur fuer diesen Lauf migriert – der naechste versucht es
                # erneut. Ein Schreibfehler (Rechte) darf das Lesen nicht kippen.
                print("[Mail] Stil-Migration nicht gespeichert: %s" % e, flush=True)
        return d
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
             "ordner_eingang", "ordner_entwuerfe", "ordner_gesendet",
             "antwort_vorgabe")

# Deckel fuer den Text EINES Stils. Er geht in JEDEN Auftrag ein, der ihn
# benutzt (Vorschlag und Regel-Lauf), und kostet dort Kontext – ein Roman waere
# kein Gewinn, sondern verdraengte die eigentliche Nachricht.
#
# 2026-08-18 von 2000 auf 6000 angehoben (Rueckmeldung des Nutzers: "kann zu
# wenig Text aufnehmen"). Eine echte Signatur mit Rechtsform, Registergericht
# und Pflichtangaben plus Ton- und Tabu-Regeln sprengt 2000 Zeichen schnell.
# 6000 sind grob 1500 Token – spuerbar, aber neben TEXT_MAX (Fremdtext) und
# PROMPT_MAX (8000) vertretbar; nur EIN Stil geht je Lauf hinein.
VORGABE_MAX = 6000

# Mehrere benannte Stile je Postfach (2026-08-18). Bis dahin gab es genau EINEN
# Text ("Stil und Signatur fuer Antworten"); wer je nach Empfaenger foermlich
# oder locker schreibt, musste ihn vor jeder Antwort umschreiben.
#
# Ein Stil bestimmt weiterhin AUSSCHLIESSLICH die FORM eines Textes. Er loest
# nichts aus – die Lehre aus dem Vorfall 2026-08-17 gilt unveraendert und wird
# durch die Auswahl nicht aufgeweicht: gewaehlt wird nur, WELCHE Form gilt.
MAX_STILE = 12
STIL_NAME_MAX = 60
# Ausdrueckliche Wahl "kein Stil" – unterscheidbar von "nichts gewaehlt"
# (leer = Standardstil bzw. Erkennung aus dem Regel-Prompt).
STIL_KEINER = "-"

# „Das Modell soll den Stil selbst waehlen." NUR in der Antwort-Vorschau des
# Add-ins – dort liest ein Mensch den Vorschlag, bevor er ihn absendet, und der
# Lauf hat keine Werkzeuge. In einer REGEL waere derselbe Wert gefaehrlich:
# sie feuert ohne Anwesenden, und die Stilwahl haenge dann am Fremdtext.
# Deshalb loest `stil_fuer` ihn ausdruecklich zu „kein Stil" auf (fail-closed);
# den Auto-Modus baut allein `mail_runner.antwort_vorschlag`.
STIL_AUTO = "auto"
# Kuerzere Namen werden im Regel-Prompt NICHT gesucht: "AG" oder "Du" treffen
# in jedem zweiten Satz und wuerden einen Stil erzwingen, den niemand meinte.
STIL_PROMPT_MIN = 3
# Anfuehrungszeichen, die um einen Stilnamen stehen duerfen (deutsche und
# englische Formen, gerade und typografische).
_ANFUEHRUNG = "\"'\u201e\u201c\u201d\u00ab\u00bb\u2018\u2019"


# ── Aussetzer nach wiederholten Anmeldefehlern ──────────────────────────────
#
# WARUM ES DAS GIBT (Vorfall 2026-08-16): eine Regel meldet sich im eingestellten
# Takt am Postfach an – Vorgabe alle 5 Minuten. Ist das Kennwort falsch oder das
# Domaenenkonto gesperrt, erzeugt JEDER Lauf einen weiteren abgelehnten Logon.
# Die Domaene zaehlt die mit: gemessen sperrt nexus.int nach DREI Fehlversuchen
# fuer 30 Minuten. Damit haelt eine einzige vergessene Regel das Konto dauerhaft
# gesperrt – auch fuer Windows, und niemand sieht den Zusammenhang zwischen
# "ich komme nicht mehr an meinen Rechner" und einer Postfachregel.
#
# Deshalb: nach MAX_ANMELDEFEHLER aufeinanderfolgenden Anmeldefehlern wird die
# AUTOMATIK des Postfachs ausgesetzt. Bewusst NICHT ueber das Feld ``aktiv`` –
# das ist die Absicht des Benutzers und darf nicht stillschweigend umgeschrieben
# werden; ein eigener Zustand laesst sich zurueckziehen, ohne die Einstellung zu
# verlieren, und die Oberflaeche kann den Grund nennen.
#
# GEZAEHLT WIRD NUR KATEGORIE "auth". Ein unerreichbarer Server, ein Zeitlimit
# oder ein Zertifikatsfehler sind keine Fehlversuche im Sinne der Sperrpolitik –
# wer die mitzaehlt, setzt das Postfach bei jeder Netzstoerung aus.
MAX_ANMELDEFEHLER = 3


def max_anmeldefehler() -> int:
    """Schwelle als FUNKTION, nicht als beim Import eingefrorener Wert.

    Gleiche Begruendung wie ``documents.retention_days()``: ueber die Umgebung
    gesetzt soll der Wert ohne Dienstneustart gelten. ``0`` schaltet den
    Aussetzer ab (dann gilt wieder das Verhalten vor 2026-08-16)."""
    try:
        n = int(os.environ.get("JARVIS_MAIL_MAX_AUTHFEHLER", MAX_ANMELDEFEHLER))
    except (TypeError, ValueError):
        return MAX_ANMELDEFEHLER
    return max(0, min(n, 50))


def _leer(benutzer_norm: str) -> dict:
    return {"benutzer_norm": benutzer_norm, "adresse": "", "benutzer": "",
            "pw_enc": "", "kanal": "", "aktiv": True,
            "ordner_eingang": "", "ordner_entwuerfe": "", "ordner_gesendet": "",
            "stile": [], "antwort_vorgabe": "",
            "angelegt": int(time.time()), "geaendert": 0,
            "letzter_erfolg": 0, "letzter_fehler": "",
            "anmeldefehler": 0, "ausgesetzt": False, "ausgesetzt_seit": 0,
            "ausgesetzt_grund": ""}


def hat_konto(user: str) -> bool:
    k = _laden().get(norm_user(user))
    return bool(k and (k.get("adresse") or "").strip() and (k.get("pw_enc") or "").strip())


# ── Antwort-Stile ("Stil und Signatur") ─────────────────────────────────────
#
# **Bewusst NICHT Teil von ``MailKonto``**: dort stehen ausschliesslich
# Verbindungs- und Postfachdaten, die an ``MailClient`` gehen. Eine
# Prompt-Vorgabe hat in einem Verbindungsobjekt nichts verloren – sie wird dort
# gelesen, wo der Auftrag gebaut wird (``mail_runner``).
#
# Ein Stil: ``{"id", "name", "text", "standard"}``. Genau EINER kann
# ``standard`` sein; er gilt, wenn nichts gewaehlt wurde. Keiner ist auch
# erlaubt – dann laeuft eine Regel ohne Stil, und das ist eine gueltige Wahl.


def _stil_id() -> str:
    return secrets.token_hex(4)


def _stil_norm(roh) -> dict | None:
    """Ein Eintrag aus der Datei – oder ``None``, wenn er unbrauchbar ist.

    Wird beim LESEN angewandt: eine von Hand verbogene Datei soll die
    Oberflaeche nicht kippen, sondern nur den kaputten Eintrag verlieren.
    """
    if not isinstance(roh, dict):
        return None
    sid = str(roh.get("id") or "").strip()[:32]
    name = str(roh.get("name") or "").strip()[:STIL_NAME_MAX]
    if not sid or not name:
        return None
    return {"id": sid, "name": name,
            "text": str(roh.get("text") or "").strip()[:VORGABE_MAX],
            "standard": bool(roh.get("standard"))}


def _stile_von(k: dict) -> list[dict]:
    out, gesehen = [], set()
    for roh in (k.get("stile") or []):
        e = _stil_norm(roh)
        if not e or e["id"] in gesehen:
            continue
        gesehen.add(e["id"])
        out.append(e)
        if len(out) >= MAX_STILE:
            break
    # Genau EIN Standard. Zwei waeren nicht aufloesbar; der erste gewinnt.
    schon = False
    for e in out:
        if e["standard"] and not schon:
            schon = True
        else:
            e["standard"] = False
    return out


def _migrieren(alle: dict) -> bool:
    """Einzel-Vorgabe → Stilliste. Rueckgabe: wurde etwas geaendert?

    Laeuft beim Lesen und schreibt EINMALIG zurueck (Muster ``config._load_v2``).
    Beruehrt nur Konten, die noch keine Stile haben – ein zweiter Lauf aendert
    nichts, sonst schriebe jeder Start die Datei neu.

    Das alte Feld ``antwort_vorgabe`` bleibt als **Spiegel** des Standardstils
    stehen (siehe ``_spiegel_setzen``). Es wird nirgends mehr gelesen ausser
    hier; es steht nur da, damit ein Rueckfall auf eine aeltere Programmfassung
    die Vorgabe nicht verliert.
    """
    geaendert = False
    for k in alle.values():
        if not isinstance(k, dict):
            continue
        if k.get("stile"):
            continue
        alt = str(k.get("antwort_vorgabe") or "").strip()
        if not alt:
            continue
        k["stile"] = [{"id": _stil_id(), "name": "Standard",
                       "text": alt[:VORGABE_MAX], "standard": True}]
        geaendert = True
    return geaendert


def _spiegel_setzen(k: dict) -> None:
    """Haelt ``antwort_vorgabe`` auf dem Text des Standardstils.

    Redundanz mit Ansage: MASSGEBLICH ist ``stile``. Der Spiegel wird nur von
    ``_migrieren`` gelesen (also wenn gar keine Stile da sind) und existiert
    ausschliesslich fuer den Fall, dass jemand eine aeltere Programmfassung
    zurueckspielt.
    """
    std = [e for e in _stile_von(k) if e["standard"]]
    k["antwort_vorgabe"] = std[0]["text"] if std else ""


def stile(user: str) -> list[dict]:
    """Alle Stile des Benutzers. Fail-safe leer."""
    try:
        return _stile_von(_laden().get(norm_user(user)) or {})
    except Exception:  # noqa: BLE001
        return []


def _stile_schreiben(un: str, liste: list[dict]) -> list[dict]:
    alle = _laden()
    k = alle.get(un) or _leer(un)
    k["benutzer_norm"] = un
    k["stile"] = liste
    _spiegel_setzen(k)
    k["geaendert"] = int(time.time())
    alle[un] = k
    _speichern(alle)
    return _stile_von(k)


def stil_anlegen(user: str, name: str, text: str = "",
                 standard: bool | None = None) -> list[dict]:
    """Neuen Stil anlegen. Rueckgabe = die vollstaendige Liste.

    Der ERSTE Stil wird automatisch Standard: ohne ihn haette eine Regel ohne
    Auswahl gar keinen Stil, und der Benutzer haette gerade einen angelegt.
    """
    un = norm_user(user)
    if not un:
        raise MailFehler("Kein Benutzer – der Stil kann nicht zugeordnet werden.", "eingabe")
    nm = str(name or "").strip()
    if not nm:
        raise MailFehler("Der Stil braucht einen Namen.", "eingabe")
    if len(nm) > STIL_NAME_MAX:
        raise MailFehler("Der Name ist zu lang (max. %d Zeichen)." % STIL_NAME_MAX, "eingabe")
    liste = stile(user)
    if len(liste) >= MAX_STILE:
        raise MailFehler("Es sind hoechstens %d Stile moeglich (vorhanden: %d)."
                         % (MAX_STILE, len(liste)), "eingabe")
    if any(e["name"].lower() == nm.lower() for e in liste):
        # Der Name ist die sprachliche Kennung im Regel-Prompt – zwei gleiche
        # waeren dort nicht aufloesbar.
        raise MailFehler("Es gibt bereits einen Stil mit dem Namen '%s'." % nm, "eingabe")
    eintrag = {"id": _stil_id(), "name": nm,
               "text": str(text or "").strip()[:VORGABE_MAX],
               "standard": bool(standard) if standard is not None else (not liste)}
    liste.append(eintrag)
    if eintrag["standard"]:
        for e in liste:
            e["standard"] = (e["id"] == eintrag["id"])
    return _stile_schreiben(un, liste)


def stil_aendern(user: str, stil_id: str, felder: dict) -> list[dict]:
    """Name/Text/Standard eines Stils aendern. Unbekannte Kennung → Fehler."""
    un = norm_user(user)
    liste = stile(user)
    treffer = [e for e in liste if e["id"] == str(stil_id or "").strip()]
    if not treffer:
        raise MailFehler("Stil nicht gefunden.", "eingabe")
    e = treffer[0]
    if "name" in (felder or {}):
        nm = str(felder.get("name") or "").strip()
        if not nm:
            raise MailFehler("Der Stil braucht einen Namen.", "eingabe")
        if len(nm) > STIL_NAME_MAX:
            raise MailFehler("Der Name ist zu lang (max. %d Zeichen)." % STIL_NAME_MAX, "eingabe")
        if any(a["name"].lower() == nm.lower() and a["id"] != e["id"] for a in liste):
            raise MailFehler("Es gibt bereits einen Stil mit dem Namen '%s'." % nm, "eingabe")
        e["name"] = nm
    if "text" in (felder or {}):
        # LEER heisst hier wirklich "kein Text" – anders als beim Kennwort, das
        # nie angezeigt wird. Der Benutzer sieht seinen Text und kann ihn
        # bewusst loeschen.
        e["text"] = str(felder.get("text") or "").strip()[:VORGABE_MAX]
    if "standard" in (felder or {}):
        if felder.get("standard"):
            for a in liste:
                a["standard"] = (a["id"] == e["id"])
        else:
            e["standard"] = False
    return _stile_schreiben(un, liste)


def stil_loeschen(user: str, stil_id: str) -> list[dict]:
    """Stil entfernen. **Es rueckt KEINER nach.**

    Ein automatisch nachrueckender Standard wuerde bedeuten, dass Regeln ohne
    eigene Wahl ploetzlich in einem Ton antworten, den niemand dafuer bestimmt
    hat. Regeln, die genau diesen Stil gewaehlt hatten, fallen auf den Standard
    zurueck – ``stil_fuer`` vermerkt das im Klartext.
    """
    un = norm_user(user)
    liste = stile(user)
    rest = [e for e in liste if e["id"] != str(stil_id or "").strip()]
    if len(rest) == len(liste):
        raise MailFehler("Stil nicht gefunden.", "eingabe")
    return _stile_schreiben(un, rest)


def stil_aus_prompt(prompt: str, liste: list[dict] | None = None,
                    user: str = "") -> str:
    """Kennung des Stils, den ein Regel-PROMPT sprachlich nennt (oder "").

    **Aufgeloest wird deterministisch, BEVOR ein Modell laeuft** – und
    ausschliesslich aus dem Regel-Prompt, nie aus der eingegangenen Nachricht.
    Duerfte das Modell den Stil selbst waehlen, waere ein "[[Stil: X]]" im
    Fremdtext ein Hebel; ein Angreifer koennte sich die Form der Antwort
    aussuchen. Die Form ist zwar harmloser als eine Aktion, aber es gibt keinen
    Grund, diese Tuer aufzumachen.

    Erkannt wird ein Hinweiswort (Stil/Ton/Signatur/Vorlage/style/tone) gefolgt
    vom NAMEN eines vorhandenen Stils, in Anfuehrungszeichen oder ohne. Bei
    mehreren Treffern gewinnt der frueheste, bei gleicher Stelle der laengste
    Name (er ist der spezifischere).
    """
    text = str(prompt or "")
    if not text.strip():
        return ""
    eintraege = liste if liste is not None else stile(user)
    treffer = []
    for e in eintraege:
        nm = e.get("name") or ""
        if len(nm) < STIL_PROMPT_MIN:
            continue
        anf = "[" + re.escape(_ANFUEHRUNG) + "]?"
        muster = re.compile(
            r"(?:stilvorgabe|stil|tonfall|ton|signatur|vorlage|style|tone)\b"
            r"[^\w\n]{0,12}(?:vorgabe|von|des|der|:|=)?[^\w\n]{0,12}"
            + anf + re.escape(nm) + anf,
            re.IGNORECASE)
        m = muster.search(text)
        if m:
            treffer.append((m.start(), -len(nm), e["id"]))
    if not treffer:
        return ""
    treffer.sort()
    return treffer[0][2]


def stil_fuer(user: str, stil_id: str = "", prompt: str = "") -> dict:
    """Der Stil, der fuer DIESEN Lauf gilt.

    Reihenfolge – die Bedeutung steckt in ihr:
      1. ``stil_id`` ausdruecklich gewaehlt (Pulldown / Regelfeld) → dieser.
         ``STIL_KEINER`` heisst "ausdruecklich ohne Stil", ``STIL_AUTO``
         "das Modell waehlt" – letzteres liefert HIER keinen Stil (siehe dort).
      2. gewaehlte Kennung gibt es nicht mehr (Stil geloescht) → Standardstil,
         mit ``hinweis``. Der Lauf laeuft weiter: eine Regel, die wegen einer
         verwaisten Referenz gar nichts tut, ist der schlechtere Ausgang
         (gleiche Abwaegung wie beim geloeschten Rollen-Profil, 2026-08-10).
      3. nichts gewaehlt → im Regel-Prompt sprachlich genannter Stil.
      4. sonst → Standardstil (kann fehlen; dann gilt kein Stil).

    Rueckgabe ist IMMER ein dict: ``{"id","name","text","quelle","hinweis"}``.
    """
    leer = {"id": "", "name": "", "text": "", "quelle": "", "hinweis": ""}
    try:
        liste = stile(user)
    except Exception:  # noqa: BLE001
        return leer
    if not liste:
        return leer
    std = ([e for e in liste if e["standard"]] or [None])[0]
    wahl = str(stil_id or "").strip()

    if wahl == STIL_KEINER:
        return dict(leer, quelle="keiner")
    if wahl == STIL_AUTO:
        # Hier gibt es KEINEN Stil. Wer den Auto-Modus umsetzt, muss ihn an
        # `quelle` erkennen und den Katalog selbst bauen – so kann der Wert
        # nicht versehentlich in einen Regel-Lauf durchschlagen.
        return dict(leer, quelle="auto",
                    hinweis="" if not liste else
                    "Die automatische Stilwahl gilt nur in der Antwort-Vorschau "
                    "des Add-ins. Hier wirkt kein Stil.")
    if wahl:
        for e in liste:
            if e["id"] == wahl:
                return dict(e, quelle="feld", hinweis="")
        if std:
            return dict(std, quelle="standard",
                        hinweis="Der gewaehlte Stil gibt es nicht mehr – es gilt "
                                "der Standardstil '%s'." % std["name"])
        return dict(leer, hinweis="Der gewaehlte Stil gibt es nicht mehr, und es "
                                  "ist kein Standardstil gesetzt.")

    aus_prompt = stil_aus_prompt(prompt, liste)
    if aus_prompt:
        for e in liste:
            if e["id"] == aus_prompt:
                return dict(e, quelle="prompt", hinweis="")
    return dict(std, quelle="standard", hinweis="") if std else leer


def antwort_vorgabe(user: str) -> str:
    """Text des STANDARD-Stils.

    Bleibt als Name erhalten, weil er das ist, was ein Aufrufer ohne eigene
    Stilwahl meint. Wer die Wahl treffen kann, benutzt ``stil_fuer``.
    """
    e = stil_fuer(user)
    return e.get("text") or ""


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
        # Die Stile SIND die Vorgabe (seit 2026-08-18). ``antwort_vorgabe``
        # bleibt als abgeleiteter Wert (Text des Standardstils) in der Antwort:
        # ein Client, der noch das alte Einzelfeld kennt, zeigt damit weiter
        # etwas Sinnvolles an, statt ein leeres Feld.
        "stile": _stile_von(k),
        "max_stile": MAX_STILE,
        "antwort_vorgabe": ([e["text"] for e in _stile_von(k) if e["standard"]]
                            or [""])[0],
        "letzter_erfolg": int(k.get("letzter_erfolg", 0) or 0),
        "letzter_fehler": k.get("letzter_fehler", ""),
        "anmeldefehler": int(k.get("anmeldefehler", 0) or 0),
        "max_anmeldefehler": max_anmeldefehler(),
        "ausgesetzt": bool(k.get("ausgesetzt")),
        "ausgesetzt_seit": int(k.get("ausgesetzt_seit", 0) or 0),
        "ausgesetzt_grund": k.get("ausgesetzt_grund", ""),
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
    if "antwort_vorgabe" in felder:
        # ALTER WEG, seit 2026-08-18 nur noch fuer Clients, die die Stilliste
        # nicht kennen (ein im Browser zwischengespeichertes Add-in sendet das
        # Feld weiter). Er schreibt den Text des STANDARDSTILS.
        #
        # **Ein LEERER Wert wird hier ignoriert** – anders als frueher. Grund:
        # ein alter Client sendet das Feld bei JEDEM Speichern mit, und wenn er
        # es nicht anzeigen kann, sendet er es leer. Wuerde das loeschen, waere
        # ein Klick auf "Ordner speichern" der Verlust aller Stiltexte. Zum
        # Entfernen gibt es den Stil-Endpunkt.
        _alt = str(felder.get("antwort_vorgabe") or "").strip()[:VORGABE_MAX]
        if _alt:
            _liste = _stile_von(k)
            _std = [e for e in _liste if e["standard"]]
            if _std:
                _std[0]["text"] = _alt
            elif len(_liste) < MAX_STILE:
                _liste.append({"id": _stil_id(), "name": "Standard",
                               "text": _alt, "standard": True})
            k["stile"] = _liste
            _spiegel_setzen(k)
    if "passwort" in felder:
        pw = str(felder.get("passwort") or "")
        if pw.strip():
            k["pw_enc"] = verschluesseln(pw)
            # NEUES Kennwort = neuer Anlauf. Ohne dieses Zuruecksetzen bliebe das
            # Postfach nach dem Beheben der Ursache ausgesetzt, und der Benutzer
            # haette keinen erkennbaren Weg zurueck. Nur bei einem WIRKLICH
            # gesetzten Kennwort – ein leeres Feld heisst "unveraendert" und darf
            # den Aussetzer nicht aufheben.
            k["anmeldefehler"] = 0
            k["ausgesetzt"] = False
            k["ausgesetzt_seit"] = 0
            k["ausgesetzt_grund"] = ""

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


def merke_ergebnis(user: str, ok: bool, fehler: str = "", art: str = "") -> None:
    """Letzten Zustand am Konto vermerken (fuer die Oberflaeche).

    Bewusst nur Zeitpunkt + Fehlertext: WER wann was gemacht hat, steht im
    Regel-Protokoll (mail_rules), nicht hier.

    ``art`` ist die Kategorie des Fehlers (``MailFehler.kategorie``). Nur
    ``"auth"`` zaehlt gegen den Aussetzer – siehe Begruendung bei
    ``MAX_ANMELDEFEHLER``. Wer den Parameter weglaesst, zaehlt NICHTS mit; das
    ist Absicht: ein neuer Aufrufer soll das Postfach nicht versehentlich
    aussetzen, sondern es bewusst melden muessen.
    """
    un = norm_user(user)
    alle = _laden()
    k = alle.get(un)
    if not k:
        return
    if ok:
        k["letzter_erfolg"] = int(time.time())
        k["letzter_fehler"] = ""
        # Ein Erfolg loest den Aussetzer auf. Das ist der eigentliche Rueckweg:
        # der Benutzer traegt sein Kennwort neu ein und drueckt "Verbindung
        # testen" – klappt es, laeuft die Automatik ohne weiteren Handgriff.
        k["anmeldefehler"] = 0
        if k.get("ausgesetzt"):
            k["ausgesetzt"] = False
            k["ausgesetzt_seit"] = 0
            k["ausgesetzt_grund"] = ""
            print("[Mail] Aussetzer fuer '%s' aufgehoben (Anmeldung wieder erfolgreich)"
                  % un, flush=True)
    else:
        k["letzter_fehler"] = (fehler or "")[:500]
        if art == "auth":
            k["anmeldefehler"] = int(k.get("anmeldefehler", 0) or 0) + 1
            grenze = max_anmeldefehler()
            if grenze and k["anmeldefehler"] >= grenze and not k.get("ausgesetzt"):
                k["ausgesetzt"] = True
                k["ausgesetzt_seit"] = int(time.time())
                k["ausgesetzt_grund"] = (fehler or "")[:500]
                print("[Mail] Postfach '%s' nach %d Anmeldefehlern ausgesetzt – "
                      "die Automatik meldet sich nicht mehr an, damit das "
                      "Domaenenkonto nicht gesperrt wird." % (un, k["anmeldefehler"]),
                      flush=True)
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


def konto_fuer(user: str, trotz_aussetzer: bool = False) -> MailKonto:
    """Baut das vollstaendige ``MailKonto``: Serverteil (Skill) + Benutzerteil.

    ``trotz_aussetzer=True`` uebergeht den Aussetzer und ist den vom BENUTZER
    ausgeloesten Wegen vorbehalten (Verbindungstest, Ordnerliste, Testlauf).
    Begruendung: der Aussetzer soll die WIEDERHOLUNG im Takt stoppen, nicht den
    Menschen aussperren, der den Fehler gerade behebt – ohne diese Ausnahme
    waere der Verbindungstest nach dem Aussetzen tot und es gaebe keinen
    Rueckweg ausser dem Speichern des Kennworts. Ein Klick ist EIN Versuch;
    gefaehrlich ist nur die Regel, die es alle fuenf Minuten wieder tut.
    Die Vorgabe ist fail-closed: wer den Parameter nicht setzt, wird gesperrt.

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
    if k.get("ausgesetzt") and not trotz_aussetzer:
        raise MailFehler(
            "Die Automatik fuer dieses Postfach ist nach %d fehlgeschlagenen "
            "Anmeldungen ausgesetzt, damit das Domaenenkonto nicht gesperrt wird. "
            "Kennwort im E-Mail-Bereich pruefen und 'Verbindung testen' druecken – "
            "gelingt die Anmeldung, laeuft die Automatik von selbst weiter."
            % int(k.get("anmeldefehler", 0) or 0), "eingabe")

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
