"""Adressbuch-Suche: aus einem NAMEN eine E-Mail-Adresse machen.

Zwei Quellen, in dieser Reihenfolge – dasselbe Muster wie die Kanalwahl des
Mail-Clients (EWS als Regelweg, Standardprotokoll als Rueckfall):

1. **Exchange (EWS ``ResolveNames``)** mit den Zugangsdaten des Postfach-
   Inhabers. Das ist das echte Adressbuch: globale Adressliste, Verteiler UND
   die persoenlichen Kontakte – also genau das, was dieser Mensch in Outlook
   sieht. Deshalb steht es vorn: ein Verteiler und ein eigener Kontakt stehen
   in keinem Verzeichnis-Benutzerobjekt.
2. **AD/LDAP** ueber das Dienstkonto (``ad_bind_user``). Greift, wenn fuer den
   Benutzer kein Postfach hinterlegt ist, der IMAP-Kanal laeuft oder EWS
   gerade nicht erreichbar ist. Findet nur PERSONEN
   (``objectCategory=person``) – keine Verteiler, keine Kontakte; das steht in
   der Antwort, damit niemand ein leeres Ergebnis fuer eine Aussage haelt.

WARUM DER BENUTZER KEIN PARAMETER DES WERKZEUGS IST: dieselbe Begruendung wie
im ganzen E-Mail-Skill (siehe dessen Modulkopf). Der Postfach-Inhaber kommt aus
``mail_accounts.current_mail_user``; haette ein Modell hier ein Feld, koennte
ein per Mail eingeschmuggelter Satz im Adressbuch eines anderen suchen.

ALLE AUFRUFE HIER SIND BLOCKIEREND (Netz, ldap3, exchangelib). Aufrufer
verpacken sie in ``asyncio.to_thread`` – ein blockierender Netzaufruf im
Event-Loop friert den ganzen Dienst ein.
"""

import contextvars
import re

from backend.mail_client import MailFehler

# ── Welche Adressen wurden in DIESEM Lauf wirklich aufgeloest? ───────────────
#
# ⚠ WOZU (bezahlter Vorfall DEV 2026-10-23): auf "sende an <Name>" nahm das
# Modell in etwa jedem zweiten Lauf eine Adresse aus Gedaechtnis oder
# Gespraechsverlauf, OHNE zu suchen – gemeldet als "wird an eine vorher
# verwendete adresse gesendet". Am Feld ist das nicht zu sehen: eine
# uebernommene Adresse hat genauso ein "@" wie eine aufgeloeste. Die
# Bestaetigungskarte kann den Unterschied nur zeigen, wenn ihn jemand
# festhaelt – das passiert hier.
#
# Die Marke ist ein SET, das der LAUF anlegt; das Werkzeug fuellt es. Bewusst
# den Inhalt veraendern und nicht die Variable neu setzen: eine Zuweisung in
# einer inneren Aufgabe waere fuer den Aufrufer unsichtbar (Register).
aufgeloest_cv: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_adressbuch_aufgeloest", default=None)


def lauf_oeffnen():
    """Marke fuer "in diesem Lauf aufgeloeste Adressen" anlegen."""
    return aufgeloest_cv.set(set())


def lauf_schliessen(token) -> None:
    if token is None:
        return
    try:
        aufgeloest_cv.reset(token)
    except Exception:  # noqa: BLE001
        pass


def merken(adressen) -> None:
    """Adressen vermerken, die eine Suche in diesem Lauf geliefert hat."""
    menge = aufgeloest_cv.get()
    if not isinstance(menge, set):
        return
    for a in adressen or []:
        s = str(a or "").strip().lower()
        if "@" in s:
            menge.add(s)


def ist_aufgeloest(wert: str) -> "bool | None":
    """Kam ``wert`` aus einer Suche DIESES Laufs?

    ``None`` = unbekannt (kein offener Lauf) – das ist NICHT "nein". Ein
    headless-Lauf oder ein Aufrufer ohne Klammer weiss es schlicht nicht, und
    die Karte darf dann nichts behaupten (Register: "Unbekannt" ist eine
    eigene Stufe neben ja/nein).

    Mehrere Empfaenger gelten nur zusammen als aufgeloest: steht EINE
    uebernommene Adresse in der Zeile, ist die Zeile nicht geprueft.
    """
    menge = aufgeloest_cv.get()
    if not isinstance(menge, set):
        return None
    teile = [x.strip().lower() for x in re.split(r"[,;]", str(wert or "")) if x.strip()]
    adressen = [x for x in teile if "@" in x]
    if not adressen:
        return False
    return all(a in menge for a in adressen)

# Unter zwei Zeichen wird nicht gesucht: ein einzelner Buchstabe trifft im
# Verzeichnis einer Firma fast jeden und macht aus der Suche einen Abzug des
# Adressbuchs. Dieselbe Untergrenze wie im Verzeichnis-Picker und in
# /api/userchat/search.
MIN_FRAGE = 2

# Deckel der Trefferliste. ResolveNames liefert serverseitig hoechstens 100 und
# kann nicht blaettern; mehr als eine Handvoll ist fuer "welche Adresse ist
# gemeint?" ohnehin keine Hilfe, und fuer ein Modell ist jede Zeile Token.
VORGABE_LIMIT = 10
MAX_LIMIT = 25

# Bremse je Benutzer und Minute (siehe `drossel_ok`). Grosszuegig gegenueber
# einem tippenden Menschen, eng gegenueber einer Schleife.
MAX_JE_MINUTE = 30

# Zeitstempel der letzten Abfragen je Benutzer. Liegt im Speicher des
# Prozesses, ist also je Dienst-Instanz eigen – als Bremse gegen Dauerabfragen
# genuegt das, als Sicherheitsgrenze waere es keine.
_verlauf: dict[str, list] = {}


class AdressbuchFehler(Exception):
    """Keine Quelle konnte antworten. Die Meldung nennt BEIDE Versuche.

    Gleiche Begruendung wie bei ``MailClient._ruf``: steht dort nur der letzte
    Fehlschlag, sucht ein Administrator am falschen Ende.
    """


def _limit(wert) -> int:
    try:
        n = int(wert)
    except (TypeError, ValueError):
        return VORGABE_LIMIT
    return max(1, min(n, MAX_LIMIT))


def _aus_ews(benutzer: str, frage: str, limit: int) -> list[dict]:
    """Treffer aus dem Exchange-Adressbuch des Benutzers.

    ⚠ OHNE ``trotz_aussetzer`` – und das ist eine bewusste Abweichung von
    Verbindungstest, Ordnerliste und Vorschau, die es setzen. Jene Ausnahme
    ruht auf "die Handlung eines Menschen ist EIN Versuch". Ein Tippvorschlag
    ist das NICHT: er feuert bei jedem Zeichen und steht damit der
    Fuenf-Minuten-Automatik naeher als einem Klick. Mit ``trotz_aussetzer``
    waere er der Weg, ein Domaenenkonto dauerhaft gesperrt zu halten – genau
    der Vorfall, aus dem die Aussetzer-Buchhaltung entstanden ist.

    Das kostet nichts: ist das Postfach ausgesetzt, wirft ``konto_fuer`` mit
    Klartext-Grund, ``suchen`` faengt das und weicht auf das VERZEICHNIS aus.
    Der Benutzer bekommt also weiter Adressen, nur aus der zweiten Quelle.
    """
    from backend import mail_accounts
    from backend.mail_client import MailClient

    konto = mail_accounts.konto_fuer(benutzer)
    c = MailClient(konto)
    try:
        treffer = c.adressen_suchen(frage, limit=limit)
    except MailFehler as f:
        # Ein Anmeldefehler MUSS gezaehlt werden, sonst waere diese Suche der
        # Weg, die Aussetzer-Buchhaltung zu umgehen: drei Fehlversuche sperren
        # das Domaenenkonto, und ein Tippvorschlag feuert bei jedem Zeichen.
        # Netz-, Kanal- und Zeitfehler zaehlen ausdruecklich NICHT mit.
        try:
            mail_accounts.merke_ergebnis(benutzer, False, str(f), art=f.kategorie)
        except Exception:  # noqa: BLE001
            pass
        raise
    else:
        try:
            mail_accounts.merke_ergebnis(benutzer, True)
        except Exception:  # noqa: BLE001
            pass
        return treffer
    finally:
        try:
            c.schliessen()
        except Exception:  # noqa: BLE001
            pass


def _aus_ad(frage: str, limit: int) -> list[dict]:
    """Treffer aus dem Verzeichnis (Dienstkonto, nur Personen mit Adresse)."""
    from backend import ldap_directory

    # Bewusst MEHR holen als gebraucht: `search_users` schneidet auf `limit` ab,
    # BEVOR hier die Eintraege ohne Postfach wegfallen. Mit `limit=n` kaemen
    # sonst bei zehn Treffern ohne Adresse null Ergebnisse heraus, obwohl das
    # Verzeichnis passende Personen kennt.
    rohe = ldap_directory.search_users(frage, None, None, limit=limit * 5)
    raus: list[dict] = []
    gesehen: set[str] = set()
    for r in rohe or []:
        adr = str((r or {}).get("mail") or "").strip()
        # Ein Verzeichnis-Benutzer OHNE Postfach hat kein `mail` – als
        # Empfaenger ist er unbrauchbar, und ein Treffer ohne Adresse waere
        # fuer den Aufrufer eine Sackgasse mit dem Anschein eines Ergebnisses.
        if "@" not in adr:
            continue
        schluessel = adr.lower()
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        raus.append({"name": str(r.get("display") or r.get("sam") or adr).strip(),
                     "adresse": adr, "art": "person"})
        if len(raus) >= limit:
            break
    return raus


def drossel_ok(benutzer: str) -> tuple[bool, str]:
    """(erlaubt, grund) – Bremse je Benutzer im gleitenden Minutenfenster.

    Nicht gegen den tippenden Menschen gerichtet: mit Entprellung im Frontend
    entsteht etwa eine Anfrage je Tipp-Pause, das liegt weit darunter. Sie
    fasst den Fall, in dem eine Oberflaeche oder ein Modell in eine Schleife
    laeuft – jede Anfrage ist eine Anmeldung am Exchange bzw. eine
    Verzeichnis-Abfrage, und die trifft fremde Infrastruktur.
    """
    import time
    jetzt = time.time()
    liste = [t for t in _verlauf.get(str(benutzer), []) if jetzt - t < 60]
    if len(liste) >= MAX_JE_MINUTE:
        return False, ("Zu viele Adressbuch-Abfragen (%d je Minute). Das ist eine "
                       "Bremse gegen Dauerabfragen, keine Aussage ueber deine "
                       "Berechtigung." % MAX_JE_MINUTE)
    liste.append(jetzt)
    _verlauf[str(benutzer)] = liste
    return True, ""


def _reset_fuer_tests() -> None:
    """⚠ Setzt NUR den Zaehler DIESES Prozesses zurueck. Gegen einen laufenden
    Dienst gemessen ist das wirkungslos (die Drossel liegt in dessen Speicher)
    – siehe Register."""
    _verlauf.clear()


def suchen(benutzer: str, frage: str, limit=None) -> dict:
    """Nach einem Namen suchen und Adressen dazu liefern.

    Rueckgabe::

        {"treffer": [{"name", "adresse", "art"}, …],
         "quelle":  "ews" | "ad",
         "hinweis": str}      # leer, wenn es nichts einzuschraenken gibt

    ``art`` ist ``person``, ``verteiler``, ``kontakt`` oder ``unbekannt``.
    Wirft ``AdressbuchFehler``, wenn KEINE Quelle antworten konnte – eine leere
    Trefferliste heisst dagegen "gesucht, nichts gefunden" und ist ein
    Ergebnis. Die beiden auseinanderzuhalten ist der Punkt: "niemand dieses
    Namens" und "ich konnte nicht nachsehen" fuehren zu verschiedenen naechsten
    Schritten.
    """
    # ⚠ OHNE BENUTZER WIRD NICHT GESUCHT, auch nicht ueber das Verzeichnis.
    # Der AD-Rueckfall benutzt das DIENSTkonto – er wuerde also auch ohne jede
    # Identitaet antworten, und damit waere diese Funktion ein Weg, das
    # Firmen-Adressbuch ohne angemeldeten Benutzer zu lesen. Die Frage "hat der
    # Benutzer ein Postfach?" ist eine ANDERE: wer eines hat, geht ueber
    # Exchange, wer keines hat, ueber das Verzeichnis – aber ein Name muss in
    # beiden Faellen bekannt sein (fail-closed, wie im ganzen E-Mail-Skill).
    wer = str(benutzer or "").strip()
    if not wer:
        raise AdressbuchFehler(
            "Es ist kein Benutzer bekannt, fuer den im Adressbuch gesucht werden "
            "koennte. Die Adressbuch-Suche steht nur in einem Auftrag mit "
            "angemeldetem Benutzer zur Verfuegung.")

    f = str(frage or "").strip()
    if len(f) < MIN_FRAGE:
        return {"treffer": [], "quelle": "", "hinweis":
                "Der Suchbegriff ist zu kurz – mindestens %d Zeichen." % MIN_FRAGE}
    ok, grund = drossel_ok(wer)
    if not ok:
        raise AdressbuchFehler(grund)

    n = _limit(limit)
    gruende: list[str] = []

    try:
        treffer = _aus_ews(wer, f, n)
    except MailFehler as fehler:
        gruende.append("Exchange → %s" % fehler)
    except Exception as e:  # noqa: BLE001
        gruende.append("Exchange → %s" % e)
    else:
        return {"treffer": treffer, "quelle": "ews", "hinweis": ""}

    try:
        treffer = _aus_ad(f, n)
    except Exception as e:  # noqa: BLE001
        gruende.append("Verzeichnis → %s" % e)
        raise AdressbuchFehler(
            "Das Adressbuch konnte nicht durchsucht werden. Versucht: %s"
            % "; ".join(gruende)) from e
    return {"treffer": treffer, "quelle": "ad", "hinweis":
            "Aus dem Verzeichnis (nur Personen, keine Verteiler und keine "
            "persoenlichen Kontakte), weil das Exchange-Adressbuch nicht "
            "erreichbar war: %s" % "; ".join(gruende)}
