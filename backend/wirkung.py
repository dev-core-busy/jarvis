"""Werkzeuge nach Wirkung einstufen und vor Aussen-/Loeschwirkung bestaetigen (BSI H9).

Befund H9 aus dem BSI-Abgleich vom 2026-09-29: der Haupt-Agent sendete und
loeschte E-Mails, schrieb in Confluence/Jira und fuehrte Shell-Befehle aus,
ohne dass ein Mensch die einzelne Aktion gesehen hatte. Zusammen mit H8
(Fremdtext im Werkzeugergebnis) ist das der klassische Weg einer Indirect
Prompt Injection: eine praeparierte Mail laesst den Agenten eine zweite Mail
schreiben.

Massnahme: Werkzeuge nach Wirkung klassifizieren; Aussen- und Loeschwirkung
nur nach Klick in der Oberflaeche. Das Modell kann den Klick nicht erzeugen –
die Antwort kommt als eigene WebSocket-Nachricht des angemeldeten Benutzers.

## Wo das Tor gilt (Betreiberentscheid 2026-10-04)

* **Interaktiver Chat im Browser:** Bestaetigung per Klick.
* **Client ohne Bestaetigungsdialog** (Windows-/Android-App): die Aktion
  unterbleibt, das Modell bekommt einen Hinweis fuer den Benutzer.
* **Laeufe ohne Oberflaeche** (Cron, Dateiwaechter, Telegram/WhatsApp,
  Mail-Regeln, Agent-API, …): seit 2026-10-11 FREIGABE JE AUFTRAG
  (Betreiberentscheid, BSI H8/H9-Rest). Der Einstieg setzt ``auftrag_cv`` mit
  der Freigabe des Auftrags/der Regel/des Kanals ("Darf nach außen wirken").
  Ohne Freigabe wird die Aktion abgewiesen und gemeldet; OHNE jeden Auftrag
  ebenso (fail-closed) – ein kuenftiger, vergessener Einstieg wirkt damit nicht
  still nach aussen. Bestand behaelt sein Verhalten: Auftraege, Regeln und
  Kanaele, die vor dieser Aenderung existierten, bekommen die Freigabe beim
  ersten Laden einmalig festgeschrieben; neue starten ohne.
  ``cron_create`` bleibt selbst bestaetigungspflichtig – sonst waere "lege einen
  Auftrag an, der die Mail spaeter schickt" der Umweg – und kann die Freigabe
  NICHT setzen (nur ein Admin in der Oberflaeche).
* **Shell:** nur OHNE Sandbox. Ein Befehl als Sandbox-Benutzer laeuft mit
  eingegrenzten Schreibpfaden und braucht keinen Klick.
  Netz hat er nur, wenn der Benutzer unter Berechtigungen die Internet-
  Freigabe hat (``_user_has_internet_access``); sonst ``--unshare-net``.
  Dass ein Sandbox-Befehl MIT Freigabe ohne Klick ins Netz senden kann, ist
  Betreiberentscheid vom 2026-10-11 (Code-Review): die Internet-Freigabe
  selbst ist die Zustimmung. Wer das aendert, aendert es hier UND in
  ``einstufen()``.

Unterscheidbar wird "Lauf ohne Oberflaeche" von "Client ohne Dialog" ueber den
``kanal_cv``: ``run_task`` setzt ihn (mit oder ohne Dialogfaehigkeit), ein
headless-Lauf nicht. Ein Rollen-/Unter-Agent, den ein Chat-Lauf startet, ERBT
den Kanal (ContextVar, ``await`` bzw. ``create_task`` kopiert den Kontext) –
sonst waere die Delegation an eine Rolle mit ``email_senden`` der Umweg.

## Einstufung: Regel mit einer Tabelle, kein stilles Durchlassen

``einstufen()`` fragt zuerst das Werkzeug selbst (Attribut ``wirkung``: eine
Klasse, ``None`` oder eine Funktion der Argumente), dann die Tabelle unten.
MCP-Werkzeuge ohne eigene Angabe gelten als Aussenwirkung (fremder Code,
unbekannte Wirkung – fail-closed). Damit eine neue Funktion nicht still in die
Klasse "ohne Wirkung" faellt, prueft ``tests/test_bsi_h9.py`` als REGEL ueber
alle Werkzeugnamen: wer nach Senden/Loeschen/Anlegen klingt, muss eingestuft
sein (Tabelle oder Attribut).
"""

import asyncio
import contextvars
import re
from contextlib import contextmanager
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable

AUSSEN = "aussen"          # erreicht andere Menschen oder fremde Systeme
LOESCHEN = "loeschen"      # entfernt Daten
SHELL = "shell"            # Befehl ohne Sandbox – Wirkung nicht eingegrenzt
ZEITPLAN = "zeitplan"      # legt einen Auftrag an, der spaeter OHNE Rueckfrage laeuft

KLASSEN = (AUSSEN, LOESCHEN, SHELL, ZEITPLAN)

# Wie lange eine Anfrage auf den Klick wartet. Danach gilt sie als abgelehnt –
# ein vergessener Tab darf den Lauf nicht unbegrenzt festhalten.
FRIST_S = 300

# Anzeige der Argumente im Dialog: lang genug, um eine Mail vor dem Senden
# wirklich lesen zu koennen; die Kuerzung wird beziffert.
_ANZEIGE_MAX = 4000


def _aktion(args: dict) -> str:
    return str((args or {}).get("action") or "").strip().strip("\"'").lower()


def _je_aktion(**zuordnung: str) -> Callable[[dict], "str | None"]:
    """Einstufung nach dem Argument ``action`` (Google-, Speicher-Werkzeuge)."""
    def _f(args: dict):
        return zuordnung.get(_aktion(args))
    return _f


# Ziel eines Verschiebens, das einem Loeschen gleichkommt. Ohne diese Zeile
# waere ``email_verschieben`` nach "Geloeschte Elemente" der Weg um die
# Bestaetigung von ``email_loeschen`` herum (dessen Vorgabe ist genau der
# Papierkorb).
_PAPIERKORB = re.compile(
    r"papierkorb|gel(ö|oe)scht|trash|deleted|junk|spam", re.IGNORECASE)


def _email_verschieben(args: dict):
    ziel = str((args or {}).get("ziel") or (args or {}).get("ordner") or "")
    return LOESCHEN if _PAPIERKORB.search(ziel) else None


TABELLE: dict[str, "str | Callable[[dict], str | None]"] = {
    # E-Mail (eigenes Postfach)
    "email_senden": AUSSEN,
    "email_antworten": AUSSEN,
    "email_weiterleiten": AUSSEN,
    "email_loeschen": LOESCHEN,
    "email_verschieben": _email_verschieben,
    # Nachrichten an Dritte
    "whatsapp_send": AUSSEN,
    "telegram_send": AUSSEN,
    # Fremdsysteme mit Schreibzugriff
    "confluence_create_page": AUSSEN,
    "confluence_update_page": AUSSEN,
    "confluence_add_comment": AUSSEN,
    "confluence_upload_attachment": AUSSEN,
    "confluence_delete_page": LOESCHEN,
    "jira_add_comment": AUSSEN,
    "jira_create_issue": AUSSEN,
    "vemas_write": AUSSEN,
    "google_gmail": _je_aktion(send_mail=AUSSEN, reply_mail=AUSSEN),
    # Ein Termin mit Teilnehmern verschickt Einladungen.
    "google_calendar": _je_aktion(create_event=AUSSEN, update_event=AUSSEN,
                                  delete_event=LOESCHEN),
    # Zeitversetzt ohne Rueckfrage
    "cron_create": ZEITPLAN,
    "cron_delete": LOESCHEN,
    # Eigene Datenbestaende
    "memory_manage": _je_aktion(delete=LOESCHEN),
    "knowledge_manage": _je_aktion(remove_folder=LOESCHEN),
}


def einstufen(name: str, args: dict, *, tool: Any = None,
              sandbox: bool = False, fremd: bool = False) -> "str | None":
    """Wirkungsklasse eines Aufrufs oder ``None`` (keine Bestaetigung noetig).

    ``sandbox``: der Shell-Befehl laeuft als Sandbox-Benutzer.
    ``fremd``: MCP-Werkzeug (fremder Code).
    """
    if name == "shell_execute":
        return None if sandbox else SHELL
    if tool is not None and hasattr(tool, "wirkung"):
        regel = getattr(tool, "wirkung")
    elif name in TABELLE:
        regel = TABELLE[name]
    elif fremd:
        return AUSSEN
    else:
        return None
    if callable(regel):
        try:
            regel = regel(dict(args or {}))
        except Exception:  # noqa: BLE001
            # Eine Einstufung, die selbst scheitert, ist "unbekannt" – und
            # unbekannt heisst hier: fragen.
            return AUSSEN
    if regel is None:
        return None
    return regel if regel in KLASSEN else AUSSEN


# ── Welche Felder der Mensch in der Karte korrigieren darf ──────────────────
#
# ⚠ DIESE LISTE IST DIE GANZE SCHRANKE. Was hier nicht steht, laesst sich aus
# der Karte nicht aendern – ein Feldname, den die Oberflaeche schickt und der
# hier fehlt, wird VERWORFEN und im Journal benannt (nicht stillschweigend
# uebernommen).
#
# WARUM SO ENG: die Karte zeigt, was das MODELL vorgeschlagen hat, und die
# Zusage von BSI H9 ist "was du siehst, laeuft". Ein frei beschreibbarer
# Argumentsatz wuerde daraus "was du siehst, ist ein Vorschlag, und was
# laeuft, hat die Oberflaeche zuletzt geschickt". Zugelassen sind deshalb nur
# die EMPFAENGER-Felder der Mail-Werkzeuge: dort ist der Fall belegt, dass das
# Modell einen Namen statt einer Adresse einsetzt, und der Mensch ist genau
# die Instanz, die weiss, wer gemeint ist.
#
# NICHT zugelassen und mit Grund:
#   - `betreff`/`text`: der Mensch soll den Inhalt nicht in der Karte
#     umschreiben. Wer das will, laesst die Nachricht neu formulieren – sonst
#     steht im Verlauf ein Text, den niemand erzeugt hat.
#   - `email_antworten`: dort gibt es kein Empfaengerfeld, der Empfaenger ist
#     der Absender des Originals. Ein Feld anzubieten, das der Aufruf nicht
#     hat, waere eine Zusage ohne Wirkung.
#   - `email_loeschen`/`email_verschieben`: eine Kennung oder ein Ordner ist
#     keine Angabe, die ein Mensch sinnvoll frei tippt.
AENDERBAR: dict[str, tuple] = {
    "email_senden": ("an", "cc"),
    "email_entwurf": ("an", "cc"),
    "email_weiterleiten": ("an",),
}

# Obergrenze fuer einen uebernommenen Wert. Eine Empfaengerliste wird lang
# (mehrere Adressen mit Komma), ein Fliesstext hat hier nichts zu suchen.
AENDERBAR_MAX = 2000


def aenderbare_felder(name: str, args: dict) -> list:
    """Welche Felder DIESES Aufrufs die Karte zum Aendern anbieten darf.

    Nur Felder, die der Aufruf auch HAT – ein angebotenes Feld, das das Modell
    nicht gesetzt hat, waere ein leeres Eingabefeld ohne Bezug zum Aufruf
    (``cc`` ist bei den meisten Aufrufen nicht dabei).
    """
    erlaubt = AENDERBAR.get(str(name or ""), ())
    return [f for f in erlaubt if f in (args or {})]


def herkunft_felder(name: str, args: dict) -> dict:
    """Woher kommt der Wert der aenderbaren Felder? ``{feld: "aufgeloest" |
    "uebernommen" | "unbekannt"}``.

    Fuer die Karte: eine ueber das Adressbuch aufgeloeste Adresse und eine aus
    dem Gespraech uebernommene sehen am Feld GLEICH aus (beide mit "@"). Der
    Benutzer soll den Unterschied sehen, bevor er klickt – eine uebernommene
    Adresse ist der Fall, der am 2026-10-23 an den falschen Empfaenger ging.

    ``unbekannt`` ist eine eigene Stufe und NICHT "uebernommen": ohne offene
    Lauf-Klammer weiss hier niemand etwas, und eine Anzeige darf keinen
    Zustand behaupten, den sie nicht kennt (Register).
    """
    raus = {}
    try:
        from backend import adressbuch
    except Exception:  # noqa: BLE001
        return raus
    for feld in aenderbare_felder(name, args):
        wert = (args or {}).get(feld)
        if not str(wert or "").strip():
            continue
        try:
            ist = adressbuch.ist_aufgeloest(str(wert))
        except Exception:  # noqa: BLE001
            ist = None
        raus[feld] = ("unbekannt" if ist is None
                      else ("aufgeloest" if ist else "uebernommen"))
    return raus


def uebernehmen(name: str, ziel: dict, aenderungen) -> list:
    """Korrekturen aus der Karte in den Argumentsatz schreiben, der AUSGEFUEHRT
    wird. Rueckgabe: ``[(feld, alt, neu)]`` – die wirklich uebernommenen.

    ⚠ ``ziel`` MUSS der Satz sein, mit dem das Werkzeug gerufen wird, nicht
    der, der in der Karte stand. Im Dispatch sind das ZWEI Objekte
    (``exec_args = dict(args)`` entsteht VOR der Freigabe); wer hier ``args``
    beschreibt, korrigiert die Anzeige und sendet an die alte Adresse – eine
    Luege, die niemand sieht. Deshalb hat ``freigabe`` dafuer einen eigenen,
    PFLICHT-Parameter: ein vergessenes Argument ist ein TypeError und kein
    stiller Ausfall.
    """
    if not isinstance(aenderungen, dict) or not aenderungen:
        return []
    erlaubt = set(AENDERBAR.get(str(name or ""), ()))
    getan = []
    for feld, wert in aenderungen.items():
        f = str(feld or "")
        if f not in erlaubt:
            print(f"[H9] Korrektur an '{name}' fuer Feld '{f}' VERWORFEN: "
                  "nicht aenderbar", flush=True)
            continue
        if f not in (ziel or {}):
            print(f"[H9] Korrektur an '{name}' fuer Feld '{f}' VERWORFEN: "
                  "im Aufruf nicht vorhanden", flush=True)
            continue
        # Zeilenumbrueche heraus: ein Empfaenger ist eine Zeile. Das ist
        # Hygiene an der Kopfzeile, keine Rechtegrenze – wer hier tippt, darf
        # ohnehin an beliebige Adressen senden.
        neu = " ".join(str("" if wert is None else wert).split())[:AENDERBAR_MAX]
        alt = str(ziel.get(f) or "")
        if neu == alt:
            continue
        ziel[f] = neu
        getan.append((f, alt, neu))
    return getan


def anzeige_argumente(args: dict) -> list:
    """Argumente fuer den Dialog: ``[[name, wert], …]`` in Aufrufreihenfolge.

    Interne Argumente (``_status_callback``, ``_sandbox_user`` …) beginnen mit
    ``_`` und stammen nicht vom Modell – sie gehoeren nicht in den Dialog.
    """
    zeilen = []
    for k, v in (args or {}).items():
        if str(k).startswith("_"):
            continue
        if isinstance(v, str):
            wert = v
        else:
            try:
                import json
                wert = json.dumps(v, ensure_ascii=False)
            except Exception:  # noqa: BLE001
                wert = str(v)
        if len(wert) > _ANZEIGE_MAX:
            wert = (f"[gekürzt: {_ANZEIGE_MAX} von {len(wert)} Zeichen]\n"
                    + wert[:_ANZEIGE_MAX])
        zeilen.append([str(k), wert])
    return zeilen


# ── Kanal zur Oberflaeche ───────────────────────────────────────────────────

@dataclass
class Kanal:
    """Der Weg zum Menschen, der eine Aktion dieses Laufs bestaetigen kann."""
    ws: Any
    username: str
    kann_bestaetigen: bool
    agent_id: str = ""


kanal_cv: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_bestaetigung_kanal", default=None)


# ── Eine abgelehnte Aktion kommt nicht wieder ───────────────────────────────
#
# ⚠ BEZAHLTER VORFALL (DEV, 2026-10-23): nach "Ablehnen" rief das Modell
# `email_senden` im SELBEN Lauf ein zweites Mal – eine zweite Karte fuer
# genau die Aktion, die der Mensch gerade verweigert hatte. Der Hinweistext
# sagt ausdruecklich "Versuche sie NICHT auf anderem Weg"; ein Prompt ist
# aber eine Bitte, und hier war der Schaden sichtbar (Karten-Spam, und im
# zweiten Anlauf haette ein unachtsamer Klick die Aktion doch freigegeben).
# Deshalb ein RIEGEL statt einer Bitte.
#
# Geblockt wird JE WERKZEUG, nicht je Argumentsatz: wer "sende diese Mail"
# ablehnt, hat "sende Mail" abgelehnt – ein Modell, das Betreff oder Text
# minimal aendert, bekaeme sonst eine neue Karte und haette den Riegel
# umgangen. Der naechste Auftrag des Benutzers ist ein NEUER Lauf und damit
# wieder frei.
#
# Die Marke ist ein SET, das der Lauf anlegt; `freigabe` fuellt es. Bewusst
# den Inhalt veraendern und nicht die Variable neu setzen – eine Zuweisung in
# einer inneren Aufgabe waere fuer den Aufrufer unsichtbar (Register).
verweigert_cv: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_bestaetigung_verweigert", default=None)


def lauf_oeffnen():
    """Marke fuer "in diesem Lauf verweigerte Werkzeuge" anlegen.

    Rueckgabe ist das Token fuer ``lauf_schliessen``. Ohne offenen Lauf
    greift der Riegel NICHT – das ist Absicht: ein Aufrufer, der keine
    Klammer setzt (headless, Agent-API), hat auch keine Karte, und dort
    entscheidet die Freigabe des Auftrags.
    """
    return verweigert_cv.set(set())


def lauf_schliessen(token) -> None:
    if token is None:
        return
    try:
        verweigert_cv.reset(token)
    except Exception:  # noqa: BLE001
        pass


def _verweigert_merken(name: str, grund: str) -> None:
    menge = verweigert_cv.get()
    if isinstance(menge, set):
        menge.add((str(name or ""), str(grund or "")))


def verweigert_grund(name: str) -> str:
    """Wurde ``name`` in diesem Lauf schon verweigert? Gibt den Grund oder ""."""
    menge = verweigert_cv.get()
    if not isinstance(menge, set):
        return ""
    for wz, grund in menge:
        if wz == str(name or ""):
            return grund
    return ""


def hinweis_schon_verweigert(name: str, grund: str) -> str:
    """Antwort auf einen zweiten Anlauf – sie muss den NAECHSTEN SCHRITT nennen.

    Ein blosses "abgelehnt" wuerde das Modell wieder probieren lassen; deshalb
    steht hier ausdruecklich, dass in diesem Lauf nichts mehr geht und der
    Benutzer das Wort hat.
    """
    was = ("soeben selbst abgelehnt" if grund == "abgelehnt"
           else "nicht freigegeben (keine Antwort in der Frist)")
    return (f"NICHT AUSGEFÜHRT: '{name}' wurde in diesem Auftrag schon vorgelegt und "
            f"vom Benutzer {was}. Es wird KEINE zweite Bestätigung mehr angezeigt – "
            "ein weiterer Versuch ist in diesem Auftrag ausgeschlossen, auch mit "
            "anderem Betreff, anderem Text oder anderem Empfänger. Sage dem Benutzer "
            "kurz, dass nichts geschehen ist, und warte auf seine nächste Anweisung; "
            "weiche NICHT auf ein anderes Werkzeug, die Shell oder eine Delegation aus.")


@dataclass
class _Offen:
    zukunft: "asyncio.Future"
    kanal: Kanal
    werkzeug: str
    klasse: str
    angelegt: float = field(default=0.0)


_offen: dict[str, _Offen] = {}


@dataclass(frozen=True)
class Auftrag:
    """Freigabe eines Laufs ohne Oberflaeche (BSI H8/H9-Rest, 2026-10-11).

    ``quelle`` nennt den Auftrag fuer Meldung und Journal ("cron:<id>",
    "regel:<id>", "telegram", …); ``aussenwirkung`` ist die Freigabe – nur ein
    echtes ``True`` gibt frei.
    """
    quelle: str
    aussenwirkung: bool = False


auftrag_cv: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_wirkung_auftrag", default=None)


@contextmanager
def auftrag(quelle: str, aussenwirkung):
    """Freigabe fuer die Dauer eines headless-Laufs setzen (und sicher zuruecknehmen).

    Rollen, an die dieser Lauf delegiert, ERBEN sie (ContextVar) – die
    Delegation ist kein Umweg und keine Erweiterung.
    """
    marke = auftrag_cv.set(Auftrag(str(quelle or "unbenannt"), aussenwirkung is True))
    try:
        yield
    finally:
        auftrag_cv.reset(marke)


# Kanaele ohne Oberflaeche, deren Freigabe in der Skill-Konfiguration steht
# (Feld "aussenwirkung"), und die Einstellung fuer die Agent-API.
KANAL_SKILLS = ("telegram", "whatsapp")
EINSTELLUNG_AGENT_API = "agent_api_aussenwirkung"


def kanal_freigabe(skill: str) -> bool:
    """Freigabe eines Messenger-Kanals – nur ein echtes True, Fehler = nein."""
    try:
        from backend.config import config
        cfg = (config.get_skill_states().get(skill) or {}).get("config") or {}
        return cfg.get("aussenwirkung") is True
    except Exception:  # noqa: BLE001
        return False


def agent_api_freigabe() -> bool:
    try:
        from backend.config import config
        return config.get_setting(EINSTELLUNG_AGENT_API, False) is True
    except Exception:  # noqa: BLE001
        return False


def bestand_festschreiben(bestand: bool) -> list:
    """Einmalig beim Start: Kanaele/Agent-API ohne Angabe behalten ihr Verhalten.

    Messenger: ein Skill mit vorhandener Konfiguration ohne das Feld stammt aus
    der Zeit, in der der Kanal als Zustimmung galt -> True festschreiben. Ein
    noch nie konfigurierter Skill bekommt nichts (Vorgabe nein).
    Agent-API: bei bestehender Installation True, bei Erstinstallation False.
    Ein gesetzter Wert wird nie angefasst. Rueckgabe: Liste der Aenderungen.
    """
    geaendert = []
    try:
        from backend.config import config
        states = config.get_skill_states()
        for skill in KANAL_SKILLS:
            st = states.get(skill) or {}
            cfg = st.get("config")
            if isinstance(cfg, dict) and cfg and "aussenwirkung" not in cfg:
                neu = dict(st)
                neu["config"] = {**cfg, "aussenwirkung": True}
                config.save_skill_state(skill, neu)
                geaendert.append(f"{skill}=True")
        if config.get_setting(EINSTELLUNG_AGENT_API, None) is None:
            config.save_setting(EINSTELLUNG_AGENT_API, bool(bestand))
            geaendert.append(f"agent_api={bool(bestand)}")
    except Exception as e:  # noqa: BLE001
        print(f"[H9] Freigaben des Bestands nicht festgeschrieben: {e}", flush=True)
    if geaendert:
        print(f"[H9] Freigabe 'Darf nach außen wirken' festgeschrieben (Bestand): "
              f"{', '.join(geaendert)}", flush=True)
    return geaendert


async def mit_auftrag(quelle: str, aussenwirkung, lauf):
    """``await``-bare Form von ``auftrag()`` fuer einen einzelnen Lauf."""
    with auftrag(quelle, aussenwirkung):
        return await lauf


async def ohne_dialog(username: str, lauf):
    """Lauf aus einer Oberflaeche OHNE Bestaetigungsdialog (Avatar, SAP-/VEMAS-
    Abfrage, Support-Assistent).

    Betreiberentscheid 2026-10-11 (BSI H9): diese Oberflaechen starten Laeufe
    mit vollem Werkzeugkasten, koennen aber keine Bestaetigungskarte zeigen –
    sie gelten wie die Windows-/Android-App als "Client ohne Dialog": Aussen-
    und Loeschwirkung wird mit Hinweis auf den Browser-Chat abgewiesen. Das
    gilt ausdruecklich auch fuer vemas_write aus der VEMAS-Abfrage.
    """
    marke = kanal_cv.set(Kanal(ws=None, username=str(username or ""),
                               kann_bestaetigen=False))
    try:
        return await lauf
    finally:
        kanal_cv.reset(marke)


def hinweis_ohne_dialog(name: str) -> str:
    return (f"NICHT AUSGEFÜHRT: '{name}' wirkt nach außen bzw. löscht Daten und braucht "
            "deshalb eine Bestätigung per Klick. Diese Anwendung kann keine "
            "Bestätigung anzeigen. Sage dem Benutzer, dass er die Aktion im Chat "
            "im Browser auslösen kann. Versuche sie NICHT auf anderem Weg.")


def hinweis_abgelehnt(name: str) -> str:
    # Die erste Fassung ("hat nicht freigegeben") las das Modell auf DEV als
    # RECHTEFRAGE und riet dem Benutzer, sich an einen Admin zu wenden
    # (2026-10-04). Deshalb ausdruecklich: Klick in der Karte, eigene Entscheidung.
    return (f"ABGELEHNT: Der Benutzer hat '{name}' soeben selbst in der "
            "Bestätigungskarte mit „Ablehnen“ abgelehnt – das ist seine Entscheidung, "
            "kein Rechte- oder Systemfehler. Die Aktion wurde nicht ausgeführt. Bestätige "
            "ihm kurz, dass nichts geschehen ist. Versuche sie NICHT auf anderem Weg "
            "(andere Werkzeuge, Shell, Delegation).")


def hinweis_ohne_freigabe(name: str, quelle: "str | None") -> str:
    wo = f"Dieser Auftrag ({quelle})" if quelle else "Dieser Lauf"
    return (f"NICHT AUSGEFÜHRT: '{name}' wirkt nach außen bzw. löscht Daten. {wo} läuft "
            "ohne Oberfläche und hat dafür keine Freigabe. Die Freigabe wird am "
            "Auftrag, an der Regel bzw. am Kanal gesetzt („Darf nach außen wirken“). "
            "Nenne das im Ergebnis. Versuche die Aktion NICHT auf anderem Weg.")


def hinweis_frist(name: str) -> str:
    return (f"NICHT AUSGEFÜHRT: Für '{name}' kam innerhalb von {FRIST_S // 60} "
            "Minuten keine Bestätigung. Die Aktion wurde nicht ausgeführt.")


def hinweis_nicht_zustellbar(name: str) -> str:
    return (f"NICHT AUSGEFÜHRT: Die Bestätigung für '{name}' konnte nicht "
            "angezeigt werden (Verbindung unterbrochen).")


async def _senden(ws, nachricht: dict) -> bool:
    try:
        await ws.send_json(nachricht)
        return True
    except Exception:  # noqa: BLE001
        return False


async def freigabe(name: str, args: dict, klasse: str, exec_args: dict) -> "str | None":
    """Holt die Bestaetigung ein. ``None`` = ausfuehren, sonst das Ergebnis
    fuer das Modell (warum die Aktion unterblieb).

    Ohne Kanal (Lauf ohne Oberflaeche) entscheidet die Freigabe des Auftrags
    (``auftrag_cv``) – siehe Modulkopf.

    ``args`` ist, was ANGEZEIGT wird (der Vorschlag des Modells); ``exec_args``
    ist der Satz, mit dem das Werkzeug wirklich gerufen wird. Dass das zwei
    Objekte sind, ist der Grund fuer den vierten Parameter: Korrekturen aus der
    Karte (``AENDERBAR``) gehen in ``exec_args``. Wer ihn weglaesst, bekommt
    einen TypeError – ein stiller Ausfall waere hier das teuerste Ergebnis
    (Anzeige korrigiert, Mail an die alte Adresse).
    """
    kanal = kanal_cv.get()
    if kanal is None:
        a = auftrag_cv.get()
        if a is not None and a.aussenwirkung is True:
            return None
        quelle = a.quelle if a is not None else None
        print(f"[H9] {name} ({klasse}) abgewiesen: Lauf ohne Oberflaeche "
              f"{'(' + quelle + ') ' if quelle else '(ohne Auftrag) '}ohne Freigabe",
              flush=True)
        return hinweis_ohne_freigabe(name, quelle)
    if not kanal.kann_bestaetigen or kanal.ws is None:
        print(f"[H9] {name} ({klasse}) fuer '{kanal.username}' abgewiesen: "
              "Client ohne Bestaetigungsdialog", flush=True)
        return hinweis_ohne_dialog(name)

    # ⚠ RIEGEL: in diesem Lauf schon verweigert → gar keine zweite Karte.
    # Steht VOR dem Anlegen der Anfrage: eine Karte, die niemand sehen soll,
    # darf auch nicht entstehen (sonst wartet der Lauf bis zur Frist auf einen
    # Klick, den es nicht geben darf).
    _schon = verweigert_grund(name)
    if _schon:
        print(f"[H9] {name} ({klasse}) fuer '{kanal.username}': ZWEITER ANLAUF "
              f"abgewiesen (zuvor {_schon}) – keine neue Karte", flush=True)
        return hinweis_schon_verweigert(name, _schon)

    loop = asyncio.get_running_loop()
    kennung = secrets.token_urlsafe(12)
    eintrag = _Offen(zukunft=loop.create_future(), kanal=kanal,
                     werkzeug=name, klasse=klasse, angelegt=loop.time())
    _offen[kennung] = eintrag
    erledigt_grund = "abgebrochen"
    try:
        if not await _senden(kanal.ws, {
            "type": "bestaetigung_anfrage",
            "id": kennung,
            "werkzeug": name,
            "klasse": klasse,
            "argumente": anzeige_argumente(args),
            "aenderbar": aenderbare_felder(name, args),
            "herkunft": herkunft_felder(name, args),
            "frist_s": FRIST_S,
            "agent_id": kanal.agent_id,
        }):
            erledigt_grund = "nicht_zustellbar"
            return hinweis_nicht_zustellbar(name)
        print(f"[H9] Bestaetigung angefragt: {name} ({klasse}) fuer "
              f"'{kanal.username}'", flush=True)
        try:
            erlaubt, korrekturen = await asyncio.wait_for(eintrag.zukunft, FRIST_S)
        except asyncio.TimeoutError:
            erledigt_grund = "frist"
            print(f"[H9] {name} fuer '{kanal.username}': keine Antwort in "
                  f"{FRIST_S} s – nicht ausgefuehrt", flush=True)
            # Auch die Frist ist "keine Freigabe": eine zweite Karte wuerde
            # derselbe Mensch genauso nicht beantworten.
            _verweigert_merken(name, "frist")
            return hinweis_frist(name)
        erledigt_grund = "erlaubt" if erlaubt else "abgelehnt"
        # ⚠ Korrekturen NUR bei Freigabe. Bei "Ablehnen" waere das Schreiben in
        # exec_args wirkungslos (es wird nicht ausgefuehrt) – aber es stuende
        # eine Aenderung im Journal, die nie gewirkt hat.
        geaendert = uebernehmen(name, exec_args, korrekturen) if erlaubt else []
        # Das Journal nennt den WIRKLICH benutzten Wert. Vorher stand hier nur
        # "FREIGEGEBEN" – nach einer Korrektur in der Karte haette niemand
        # nachlesen koennen, an welche Adresse die Mail ging.
        # Den WIRKLICH benutzten Wert nennen. Vorher stand hier nur
        # "FREIGEGEBEN" – nach einer Korrektur in der Karte haette niemand
        # nachlesen koennen, an welche Adresse die Mail ging. Ins Audit kommt
        # er ebenfalls: der Dispatch protokolliert seit derselben Aenderung
        # `exec_args` statt `args` (siehe agent.py).
        nachtrag = "".join(" | %s: '%s' → '%s'" % (f, a, n) for f, a, n in geaendert)
        print(f"[H9] {name} ({klasse}) fuer '{kanal.username}': "
              f"{'FREIGEGEBEN' if erlaubt else 'ABGELEHNT'}{nachtrag}", flush=True)
        if not erlaubt:
            _verweigert_merken(name, "abgelehnt")
        return None if erlaubt else hinweis_abgelehnt(name)
    finally:
        _offen.pop(kennung, None)
        # Die Oberflaeche erfaehrt, dass die Karte nicht mehr wartet – auch bei
        # Stop (CancelledError) und Frist. Bei Klick ist es die Quittung.
        # Nicht abwarten: im Abbruchfall darf finally nicht erneut blockieren.
        if erledigt_grund != "nicht_zustellbar":
            try:
                asyncio.ensure_future(_senden(kanal.ws, {
                    "type": "bestaetigung_erledigt", "id": kennung,
                    "grund": erledigt_grund}))
            except Exception:  # noqa: BLE001
                pass


def antwort(kennung: str, username: str, ws: Any, erlaubt: bool,
            aenderungen=None) -> bool:
    """Klick aus der Oberflaeche zustellen. ``True`` = zugestellt.

    Antworten darf nur der Benutzer, dem die Anfrage gilt – ein zweiter
    angemeldeter Benutzer koennte sonst fremde Aktionen freigeben. Ohne
    Benutzernamen (API-Schluessel) nur dieselbe Verbindung.

    ``aenderungen`` sind Korrekturen aus der Karte (``{feld: wert}``). Sie
    werden hier NICHT angewandt, sondern nur weitergereicht: angewandt wird in
    ``freigabe``, das den auszufuehrenden Argumentsatz kennt. Geprueft wird
    gegen ``AENDERBAR`` – ein fremdes Feld wird verworfen und benannt.
    """
    eintrag = _offen.get(str(kennung or ""))
    if eintrag is None or eintrag.zukunft.done():
        return False
    soll = eintrag.kanal.username
    if soll:
        if username != soll:
            print(f"[H9] Antwort auf Anfrage von '{soll}' durch '{username}' "
                  "verworfen", flush=True)
            return False
    elif ws is not eintrag.kanal.ws:
        return False
    eintrag.zukunft.set_result(
        (erlaubt is True, aenderungen if isinstance(aenderungen, dict) else {}))
    return True


def offene_anzahl() -> int:
    """Fuer Tests und Diagnose."""
    return len(_offen)
