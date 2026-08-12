"""Exchange-Anbindung fuer den E-Mail-Skill: EWS als Regelweg, IMAP/SMTP als Rueckfall.

Warum ZWEI Kanaele (Vorgabe 2026-08-12): EWS (Exchange Web Services) ist der
einzige Weg, der alles kann, was die Regeln brauchen – Ordnerbaum lesen,
verschieben, echte Weiterleitung MIT Originalanhaengen, Entwurf im Postfach
ablegen, Kategorie setzen. IMAP/SMTP koennen davon nur einen Teil, sind aber
oft noch offen, wenn EWS gesperrt ist. Deshalb: EWS zuerst, IMAP als
Ausweichkanal.

DER RUECKFALL GREIFT NIE BEI EINEM ANMELDEFEHLER. Zwei Gruende, beide wichtig:
  1. Ein zweiter Anmeldeversuch mit demselben falschen Kennwort zaehlt in der
     AD-Sperrpolitik ein zweites Mal – zwei Kanaele wuerden ein Konto doppelt
     so schnell aussperren.
  2. Der Grund wuerde verschleiert: der Benutzer sieht dann einen IMAP-Fehler,
     obwohl sein Kennwort das Problem ist.
Der Rueckfall gilt ausschliesslich fuer KANAL-Fehler (exchangelib fehlt, EWS-URL
nicht auffindbar, Endpunkt antwortet 404/501, Verbindung abgelehnt).

Alle Aufrufe hier sind BLOCKIEREND (Netzwerk, imaplib, exchangelib). Aufrufer
muessen sie in ``asyncio.to_thread`` legen – ein synchroner Netzaufruf im
Event-Loop friert den ganzen Dienst ein (dieselbe Falle wie bei der
WhatsApp-Bridge und ``/api/knowledge/mounts``).

Fehler kommen als ``MailFehler`` mit einer ``kategorie`` heraus, damit der
Aufrufer entscheiden kann (Rueckfall ja/nein) und die Oberflaeche einen
verstaendlichen Satz zeigen kann, statt eines rohen Protokolltextes.
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

# ── Fehlerkategorien ────────────────────────────────────────────────────────
# "auth"      – Anmeldung abgelehnt. KEIN Rueckfall (siehe Modulkopf).
# "kanal"     – dieser Kanal steht nicht zur Verfuegung → Rueckfall erlaubt.
# "netz"      – Server nicht erreichbar/Zeitueberschreitung.
# "nicht_da"  – Nachricht/Ordner gibt es nicht.
# "grenze"    – der Kanal kann das nicht (z.B. IMAP kann keine echte Weiterleitung).
# "eingabe"   – Aufruf war falsch (fehlender Empfaenger o.ae.).
# "fehler"    – alles andere.
KATEGORIEN = ("auth", "kanal", "netz", "nicht_da", "grenze", "eingabe", "fehler")

# Kanaele, bei denen ein Rueckfall auf IMAP/SMTP sinnvoll ist.
_RUECKFALL_KATEGORIEN = {"kanal"}


class MailFehler(Exception):
    """Fehler eines Mail-Vorgangs mit Einordnung fuer Aufrufer und Oberflaeche."""

    def __init__(self, nachricht: str, kategorie: str = "fehler", kanal: str = ""):
        super().__init__(nachricht)
        self.kategorie = kategorie if kategorie in KATEGORIEN else "fehler"
        self.kanal = kanal

    def __str__(self) -> str:  # pragma: no cover - triviale Darstellung
        return super().__str__()


# ── Datenhaltung ────────────────────────────────────────────────────────────

@dataclass
class MailKonto:
    """Alles, was zum Anmelden an EINEM Postfach gebraucht wird.

    ``adresse`` ist die primaere SMTP-Adresse des Postfachs, ``benutzer`` der
    Anmeldename (bei Exchange oft ``DOMAENE\\benutzer`` oder der UPN). Beides
    getrennt, weil es sich in AD-Umgebungen regelmaessig unterscheidet.
    """
    adresse: str = ""
    benutzer: str = ""
    passwort: str = ""
    kanal: str = "auto"              # auto | ews | imap
    # EWS
    ews_url: str = ""                # z.B. https://mail.firma.de/EWS/Exchange.asmx
    autodiscover: bool = True
    auth_typ: str = "auto"           # auto | basic | ntlm
    verify_ssl: bool = True
    # IMAP/SMTP (Rueckfall)
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_starttls: bool = True
    # Ordnernamen (koennen je Sprache/Server abweichen)
    ordner_eingang: str = "INBOX"
    ordner_entwuerfe: str = ""       # leer = Standardordner des Kanals
    ordner_gesendet: str = ""
    zeitlimit: int = 30              # Sekunden je Netzaufruf

    def gueltig(self) -> tuple[bool, str]:
        """Reicht das zum Anmelden? Rueckgabe (ok, Grund)."""
        if not (self.adresse or "").strip():
            return False, "Es fehlt die E-Mail-Adresse des Postfachs."
        if not (self.passwort or "").strip():
            return False, "Es fehlt das Kennwort."
        if self.kanal == "imap" and not (self.imap_host or "").strip():
            return False, "Kanal IMAP gewaehlt, aber kein IMAP-Server hinterlegt."
        if self.kanal == "ews" and not self.autodiscover and not (self.ews_url or "").strip():
            return False, "Kanal EWS ohne Autodiscover gewaehlt, aber keine EWS-URL hinterlegt."
        return True, ""

    def anmeldename(self) -> str:
        return (self.benutzer or "").strip() or (self.adresse or "").strip()


@dataclass
class MailNachricht:
    """Eine E-Mail in der Form, die Werkzeuge und Regel-Laeufe sehen.

    ``id`` ist die kanal-eigene Kennung (EWS: ItemId, IMAP: UID im Ordner) und
    nur zusammen mit ``ordner`` eindeutig. ``schluessel`` ist die STABILE
    Kennung fuer die Verarbeitungs-Buchhaltung: die Message-ID des Kopfes, die
    ein Verschieben zwischen Ordnern ueberlebt.
    """
    id: str = ""
    schluessel: str = ""
    ordner: str = "INBOX"
    von: str = ""
    von_name: str = ""
    an: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    betreff: str = ""
    datum: str = ""                  # ISO-8601
    zeitstempel: float = 0.0
    text: str = ""
    ungelesen: bool = True
    kategorien: list[str] = field(default_factory=list)
    anhaenge: list[str] = field(default_factory=list)
    hat_anhaenge: bool = False

    def kurz(self, text_max: int = 4000) -> dict:
        """Fuer die Uebergabe an das Modell bzw. die Oberflaeche."""
        t = self.text or ""
        gekuerzt = len(t) > text_max
        return {
            "id": self.id,
            "ordner": self.ordner,
            "von": self.von,
            "von_name": self.von_name,
            "an": self.an,
            "cc": self.cc,
            "betreff": self.betreff,
            "datum": self.datum,
            "ungelesen": self.ungelesen,
            "kategorien": self.kategorien,
            "anhaenge": self.anhaenge,
            "text": (t[:text_max] + "\n… [Text gekuerzt, %d Zeichen insgesamt]" % len(t)) if gekuerzt else t,
            "text_gekuerzt": gekuerzt,
        }


# ── gemeinsame Helfer ───────────────────────────────────────────────────────

_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_BR = re.compile(r"(?i)<\s*(br|/p|/div|/tr)\s*/?>")
_LEERZEILEN = re.compile(r"\n{3,}")


def html_zu_text(html: str) -> str:
    """Grobe HTML-Entschaerfung fuer den Modell-Kontext.

    Bewusst KEIN HTML an das Modell: eine HTML-Mail besteht zu neun Zehnteln aus
    Stil-Attributen und Layout-Tabellen. Das ist Kontext-Verbrauch ohne Aussage –
    und es versteckt Anweisungen in Attributen, die im Klartext auffallen wuerden.
    """
    if not html:
        return ""
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html)
    t = _HTML_BR.sub("\n", t)
    t = _HTML_TAG.sub(" ", t)
    for roh, klar in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                      ("&quot;", '"'), ("&#39;", "'"), ("&auml;", "ä"), ("&ouml;", "ö"),
                      ("&uuml;", "ü"), ("&Auml;", "Ä"), ("&Ouml;", "Ö"), ("&Uuml;", "Ü"),
                      ("&szlig;", "ß"), ("&euro;", "€")):
        t = t.replace(roh, klar)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = _LEERZEILEN.sub("\n\n", t)
    return t.strip()


def _tls_adapter_setzen(verify: bool) -> None:
    """Zertifikatspruefung fuer EWS ein- oder ausschalten.

    **IN BEIDE RICHTUNGEN, und das ist der Punkt.** exchangelib waehlt den
    HTTP-Adapter ueber eine **prozessweite Klassenvariable**
    (``BaseProtocol.HTTP_ADAPTER_CLS``). Die erste Fassung setzte sie nur auf
    ``NoVerifyHTTPAdapter``, wenn die Pruefung abgeschaltet war – und nie
    zurueck. Damit blieb die Pruefung nach EINEM Lauf ohne Verifikation fuer den
    ganzen Prozess aus, auch wenn der Administrator sie danach wieder
    einschaltete: ein Schutz, der still ausfaellt, ist kein Schutz.

    Selbstsignierte interne Zertifikate sind bei On-Prem-Exchange der Normalfall;
    abgeschaltet wird nur auf ausdrueckliche Einstellung des Administrators (die
    Einstellung ist ohnehin serverweit, nicht pro Benutzer).

    ⚠ GRENZE: exchangelib haelt Verbindungspools je Endpunkt. Ein Umschalten
    wirkt auf NEU aufgebaute Sitzungen; fuer die bestehenden kann ein
    Dienstneustart noetig sein. Deshalb wird jeder Wechsel protokolliert – sonst
    sucht man den Unterschied zwischen Einstellung und Verhalten im Code.
    """
    try:
        import requests.adapters  # noqa: PLC0415
        from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return
    ziel = requests.adapters.HTTPAdapter if verify else NoVerifyHTTPAdapter
    if BaseProtocol.HTTP_ADAPTER_CLS is not ziel:
        BaseProtocol.HTTP_ADAPTER_CLS = ziel
        print("[Mail] TLS-Zertifikatspruefung fuer EWS: %s"
              % ("aktiv" if verify else "ABGESCHALTET (Einstellung des Administrators)"),
              flush=True)
    if not verify:
        # urllib3 warnt pro ANFRAGE – ein einziger Lesevorgang erzeugte 22 Zeilen
        # im Journal und begraebt die Meldungen, auf die es ankommt. "once" statt
        # "ignore": die Information bleibt (einmal je Prozess), das Rauschen geht.
        try:
            import warnings  # noqa: PLC0415
            from urllib3.exceptions import InsecureRequestWarning  # noqa: PLC0415
            warnings.filterwarnings("once", category=InsecureRequestWarning)
        except Exception:  # noqa: BLE001
            pass


def ews_url_normieren(wert: str) -> str:
    """Macht aus einer Servereingabe eine vollstaendige EWS-Adresse.

    Ein Administrator traegt erfahrungsgemaess den HOSTNAMEN ein
    (``exchange.firma.de``) – exchangelib braucht aber die volle Adresse des
    Endpunkts. Ohne diese Normierung scheitert die Verbindung mit einer Meldung
    ueber ein ungueltiges Schema, und niemand verbindet das mit dem Eingabefeld.

    Ergaenzt wird nur, was fehlt: Schema (https) und der Standardpfad
    ``/EWS/Exchange.asmx``. Ein bereits vollstaendiger Pfad bleibt unangetastet –
    manche Haeuser veroeffentlichen EWS hinter einem eigenen Pfad, und den darf
    eine Bequemlichkeitsfunktion nicht ueberschreiben.
    """
    u = (wert or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "https://" + u
    ohne_schema = u.split("://", 1)[1]
    if "/" not in ohne_schema.rstrip("/") or not ohne_schema.split("/", 1)[1].strip("/"):
        u = u.rstrip("/") + "/EWS/Exchange.asmx"
    return u


def _adressliste(wert) -> list[str]:
    """Nimmt Liste, Komma-/Semikolontext oder None und liefert saubere Adressen."""
    if not wert:
        return []
    if isinstance(wert, str):
        teile = re.split(r"[,;]", wert)
    else:
        teile = list(wert)
    raus = []
    for t in teile:
        t = str(t or "").strip()
        if not t:
            continue
        # "Name <adresse@x>" → adresse@x
        name, adr = email.utils.parseaddr(t)
        raus.append((adr or t).strip())
    return [a for a in raus if a]


def _pruefe_empfaenger(adressen: list[str]) -> None:
    if not adressen:
        raise MailFehler("Es ist kein Empfaenger angegeben.", "eingabe")
    for a in adressen:
        if "@" not in a or a.startswith("@") or a.endswith("@"):
            raise MailFehler("Keine gueltige E-Mail-Adresse: %s" % a, "eingabe")


def _iso(dt) -> str:
    try:
        if isinstance(dt, (int, float)):
            dt = datetime.fromtimestamp(dt, timezone.utc)
        if dt is None:
            return ""
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return ""


def _stempel(dt) -> float:
    try:
        if isinstance(dt, (int, float)):
            return float(dt)
        if dt is None:
            return 0.0
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:  # noqa: BLE001
        return 0.0


def _einordnen(e: Exception, kanal: str) -> MailFehler:
    """Ordnet eine fremde Ausnahme in unsere Kategorien ein.

    Bewusst ueber Klassen-NAMEN und Text statt ueber Import der Fehlerklassen:
    exchangelib hat seine Fehlerklassen zwischen Versionen umbenannt und
    verschoben. Ein Modul, das die Klassen importiert, bricht dann beim Import –
    also genau dort, wo es nichts mehr melden kann.
    """
    if isinstance(e, MailFehler):
        return e
    name = type(e).__name__
    txt = str(e) or name
    tief = txt.lower()

    if isinstance(e, ModuleNotFoundError) or "no module named" in tief:
        return MailFehler(txt, "kanal", kanal)
    if name in ("UnauthorizedError", "CredentialsExpiredError", "AccountIsLocked",
                "InvalidPassword") or "unauthorized" in tief or "401" in tief \
            or "authentication failed" in tief or "logon" in tief and "fail" in tief \
            or "invalid credentials" in tief or "authenticationfailed" in tief:
        return MailFehler(txt, "auth", kanal)
    if name in ("AutoDiscoverFailed", "AutoDiscoverCircularRedirect",
                "RedirectError", "EWSWarning") or "autodiscover" in tief:
        return MailFehler(txt, "kanal", kanal)
    if "404" in tief or "501" in tief or "not implemented" in tief \
            or "connection refused" in tief or "name or service not known" in tief \
            or "no address associated" in tief:
        return MailFehler(txt, "kanal", kanal)
    if name in ("ErrorItemNotFound", "ErrorFolderNotFound", "ErrorNonExistentMailbox") \
            or "not found" in tief or "nicht gefunden" in tief:
        return MailFehler(txt, "nicht_da", kanal)
    if isinstance(e, (TimeoutError, ssl.SSLError)) or "timed out" in tief \
            or "timeout" in tief or name in ("TransportError", "RateLimitError",
                                             "ServerBusy", "SSLError"):
        return MailFehler(txt, "netz", kanal)
    if isinstance(e, OSError):
        return MailFehler(txt, "netz", kanal)
    return MailFehler(txt, "fehler", kanal)


def klartext(f: MailFehler) -> str:
    """Ein Satz, aus dem hervorgeht, was zu tun ist.

    Der rohe Protokolltext ("ErrorNonExistentMailbox", "b'LOGIN failed'") sagt
    weder Benutzer noch Modell, was zu aendern ist – und ein Modell, das den
    Grund nicht versteht, wiederholt den Versuch.
    """
    k = f.kategorie
    if k == "auth":
        return ("Anmeldung am Postfach abgelehnt. Benutzername und Kennwort im "
                "E-Mail-Bereich pruefen (bei Exchange ggf. DOMAENE\\Benutzer oder "
                "die UPN-Form benutzer@firma.de). Achtung: weitere Fehlversuche "
                "koennen das Konto in der Domaene sperren. Meldung des Servers: %s" % f)
    if k == "kanal":
        return ("Dieser Zugangsweg steht nicht zur Verfuegung (%s). Ist EWS am "
                "Exchange freigegeben, bzw. sind IMAP/SMTP-Server hinterlegt? "
                "Meldung: %s" % (f.kanal or "?", f))
    if k == "netz":
        return ("Der Mailserver war nicht erreichbar (Zeitueberschreitung oder "
                "Netzfehler). Meldung: %s" % f)
    if k == "nicht_da":
        return "Nachricht oder Ordner gibt es nicht (mehr): %s" % f
    if k == "grenze":
        return str(f)
    if k == "eingabe":
        return str(f)
    return "Mail-Fehler: %s" % f


# ═══════════════════════════════════════════════════════════════════════════
# EWS-Kanal (exchangelib)
# ═══════════════════════════════════════════════════════════════════════════

class _Ews:
    """EWS-Zugriff. exchangelib wird LAZY importiert.

    Der Import darf nicht auf Modulebene stehen: exchangelib ist eine
    Abhaengigkeit des E-Mail-Skills und beim Backend-Start nicht zwangslaeufig
    vorhanden. Ein Import-Fehler hier ist ein KANAL-Fehler (Rueckfall auf IMAP),
    kein Programmfehler.
    """

    kanal = "ews"

    def __init__(self, konto: MailKonto):
        self.konto = konto
        self._acc = None
        self._mod = None

    # ── Verbindung ──────────────────────────────────────────────────────────
    def _lib(self):
        if self._mod is not None:
            return self._mod
        try:
            import exchangelib  # noqa: PLC0415
        except Exception as e:  # noqa: BLE001
            raise MailFehler(
                "exchangelib ist nicht installiert – der EWS-Kanal steht nicht zur "
                "Verfuegung (Skill 'E-Mail' aktivieren installiert es nach). %s" % e,
                "kanal", "ews") from e
        self._mod = exchangelib
        return exchangelib

    def _konto(self):
        if self._acc is not None:
            return self._acc
        xl = self._lib()
        k = self.konto
        try:
            _tls_adapter_setzen(bool(k.verify_ssl))

            creds = xl.Credentials(username=k.anmeldename(), password=k.passwort)
            zugriff = getattr(xl, "DELEGATE", "delegate")

            # EINE EINGETRAGENE URL GEWINNT – auch wenn der Autodiscover-Haken
            # gesetzt ist. Vorher galt `ews_url and not autodiscover`: wer den
            # Server eintrug und den Haken stehen liess, dessen Eingabe wurde
            # stillschweigend ignoriert (auf DEV genau so passiert, Eintrag
            # "exchange.nexus-ag.de" bei autodiscover=true). Wer eine Adresse
            # hinschreibt, meint sie; der Haken entscheidet nur noch, was ohne
            # Eintrag geschieht.
            if k.ews_url:
                kwargs = {"service_endpoint": ews_url_normieren(k.ews_url),
                          "credentials": creds}
                auth = self._auth_typ(xl)
                if auth is not None:
                    kwargs["auth_type"] = auth
                cfg = xl.Configuration(**kwargs)
                self._acc = xl.Account(primary_smtp_address=k.adresse, config=cfg,
                                       autodiscover=False, access_type=zugriff)
            else:
                self._acc = xl.Account(primary_smtp_address=k.adresse, credentials=creds,
                                       autodiscover=True, access_type=zugriff)
            return self._acc
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def _auth_typ(self, xl):
        t = (self.konto.auth_typ or "auto").lower()
        if t == "ntlm":
            return getattr(xl, "NTLM", None)
        if t == "basic":
            return getattr(xl, "BASIC", None)
        return None  # auto: exchangelib probiert selbst

    # ── Ordner ──────────────────────────────────────────────────────────────
    def _ordner(self, name: str):
        """Ordner nach Name finden – Standardnamen zuerst, dann Suche im Baum."""
        acc = self._konto()
        n = (name or "").strip()
        standard = {
            "": acc.inbox, "inbox": acc.inbox, "eingang": acc.inbox,
            "posteingang": acc.inbox,
            "drafts": acc.drafts, "entwuerfe": acc.drafts, "entwürfe": acc.drafts,
            "sent": acc.sent, "gesendet": acc.sent,
            "trash": acc.trash, "papierkorb": acc.trash, "geloescht": acc.trash,
            "junk": getattr(acc, "junk", None), "spam": getattr(acc, "junk", None),
        }
        treffer = standard.get(n.lower())
        if treffer is not None:
            return treffer
        # Pfad "Eingang/Rechnungen" oder blosser Name irgendwo im Baum
        teile = [p for p in re.split(r"[/\\]", n) if p]
        aktuell = acc.msg_folder_root
        try:
            if len(teile) > 1:
                for t in teile:
                    aktuell = aktuell / t
                return aktuell
            for f in acc.msg_folder_root.walk():
                if (f.name or "").lower() == n.lower():
                    return f
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e
        raise MailFehler("Ordner '%s' gibt es im Postfach nicht." % name, "nicht_da", "ews")

    def ordner_liste(self) -> list[dict]:
        acc = self._konto()
        raus = []
        try:
            for f in acc.msg_folder_root.walk():
                # Nur Nachrichten-Ordner: Kalender/Kontakte haben hier nichts zu suchen
                if getattr(f, "CONTAINER_CLASS", None) not in (None, "IPF.Note"):
                    continue
                raus.append({
                    "name": f.name or "",
                    "pfad": self._pfad(f, acc),
                    "anzahl": int(getattr(f, "total_count", 0) or 0),
                    "ungelesen": int(getattr(f, "unread_count", 0) or 0),
                })
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e
        raus.sort(key=lambda x: x["pfad"].lower())
        return raus

    @staticmethod
    def _pfad(f, acc) -> str:
        teile, cur = [], f
        try:
            while cur is not None and cur != acc.msg_folder_root:
                teile.append(cur.name or "")
                cur = cur.parent
        except Exception:  # noqa: BLE001
            pass
        return "/".join(reversed([t for t in teile if t])) or (f.name or "")

    # ── Lesen ───────────────────────────────────────────────────────────────
    def liste(self, ordner: str = "", seit: float = 0.0, limit: int = 25,
              nur_ungelesen: bool = False, suche: str = "") -> list[MailNachricht]:
        f = self._ordner(ordner)
        try:
            q = f.all()
            if seit:
                q = q.filter(datetime_received__gt=self._dt(seit))
            if nur_ungelesen:
                q = q.filter(is_read=False)
            if suche:
                q = q.filter(subject__contains=suche)
            q = q.order_by("-datetime_received")
            felder = ("id", "subject", "sender", "to_recipients", "cc_recipients",
                      "datetime_received", "is_read", "categories", "has_attachments",
                      "message_id")
            try:
                q = q.only(*felder)
            except Exception:  # noqa: BLE001
                pass  # aeltere Version kennt ein Feld nicht: dann alles holen
            pfad = self._pfad(f, self._konto())
            return [self._kopf(m, pfad) for m in q[:max(1, int(limit or 25))]]
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def _dt(self, stempel: float):
        xl = self._lib()
        dt = datetime.fromtimestamp(float(stempel), timezone.utc)
        try:
            return xl.EWSDateTime.from_datetime(dt)
        except Exception:  # noqa: BLE001
            return dt

    def _kopf(self, m, ordner: str) -> MailNachricht:
        absender = getattr(m, "sender", None)
        return MailNachricht(
            id=str(getattr(m, "id", "") or ""),
            schluessel=str(getattr(m, "message_id", "") or "") or str(getattr(m, "id", "") or ""),
            ordner=ordner,
            von=(getattr(absender, "email_address", "") or "") if absender else "",
            von_name=(getattr(absender, "name", "") or "") if absender else "",
            an=[x.email_address for x in (getattr(m, "to_recipients", None) or []) if getattr(x, "email_address", None)],
            cc=[x.email_address for x in (getattr(m, "cc_recipients", None) or []) if getattr(x, "email_address", None)],
            betreff=getattr(m, "subject", "") or "",
            datum=_iso(getattr(m, "datetime_received", None)),
            zeitstempel=_stempel(getattr(m, "datetime_received", None)),
            ungelesen=not bool(getattr(m, "is_read", True)),
            kategorien=list(getattr(m, "categories", None) or []),
            hat_anhaenge=bool(getattr(m, "has_attachments", False)),
        )

    def _suche_item(self, msg_id: str):
        """Nachricht anhand der ItemId holen (ordnerunabhaengig).

        ``account.fetch(ids=[...])`` ist der direkte Weg und braucht keinen
        Ordner – wichtig, weil eine Regel eine Nachricht verschiebt und die
        Folge-Aktion sie danach im alten Ordner nicht mehr faende.
        """
        acc = self._konto()
        gruende: list[str] = []

        # WEG 1: GetItem ueber die Kennung. `fetch()` erwartet
        # **(id, changekey)-TUPEL** oder Item-Objekte – KEINE nackten
        # Zeichenketten (so steht es im Docstring von Account.fetch, exchangelib
        # 5.6). Mit `ids=[msg_id]` schlug der Aufruf fehl, und weil der Fehler
        # hier mit `except Exception: pass` verschluckt wurde, war der Grund
        # unsichtbar. Der Changekey darf None sein.
        try:
            for m in acc.fetch(ids=[(msg_id, None)]):
                # fetch() liefert Ausnahmen IN der Ergebnisfolge, nicht als
                # Wurf – ein `isinstance`-Test allein und dann stilles
                # Weiterlaufen verliert die Begruendung.
                if isinstance(m, Exception):
                    gruende.append("fetch: %s" % m)
                    continue
                return m
        except Exception as e:  # noqa: BLE001
            gruende.append("fetch: %s" % e)

        # WEG 2: `get(id=…)` je Standardordner. exchangelib erlaubt GENAU diese
        # Form (QuerySet.get ist auf {id} bzw. {id, changekey} gesondert
        # behandelt) und macht daraus ebenfalls ein GetItem.
        #
        # NIEMALS `filter(id=…)`: daraus wird eine Restriction, und EWS lehnt sie
        # ab – "EWS does not support filtering on field 'id'". Genau das hat am
        # 2026-08-12 im Betrieb JEDE Aktion einer Regel blockiert (Antworten,
        # Lesen, Verschieben), und die Meldung nannte den Ordner-Rueckfall,
        # nicht den eigentlich gescheiterten ersten Weg.
        for f in (acc.inbox, acc.drafts, acc.sent, acc.trash,
                  getattr(acc, "junk", None), getattr(acc, "archive_msg_folder_root", None)):
            if f is None:
                continue
            try:
                return f.get(id=msg_id)
            except Exception as e:  # noqa: BLE001
                name = getattr(f, "name", "?")
                if type(e).__name__ != "DoesNotExist":
                    gruende.append("%s: %s" % (name, e))

        if gruende:
            raise MailFehler(
                "Nachricht %s konnte nicht geoeffnet werden. Versuche: %s"
                % (msg_id[:40] + ("…" if len(msg_id) > 40 else ""), " | ".join(gruende[:3])),
                "fehler", "ews")
        raise MailFehler("Nachricht %s nicht gefunden." % msg_id, "nicht_da", "ews")

    def lesen(self, msg_id: str, ordner: str = "") -> MailNachricht:
        m = self._suche_item(msg_id)
        n = self._kopf(m, ordner or "")
        try:
            koerper = getattr(m, "text_body", None)
            if not koerper:
                roh = getattr(m, "body", "") or ""
                koerper = html_zu_text(str(roh))
            n.text = koerper or ""
            n.anhaenge = [getattr(a, "name", "") or "" for a in (getattr(m, "attachments", None) or [])]
            n.hat_anhaenge = bool(n.anhaenge) or n.hat_anhaenge
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e
        return n

    # ── Schreiben ───────────────────────────────────────────────────────────
    def senden(self, an, betreff: str, text: str, cc=None, entwurf: bool = False) -> str:
        acc, xl = self._konto(), self._lib()
        an, cc = _adressliste(an), _adressliste(cc)
        if not entwurf:
            _pruefe_empfaenger(an)
        try:
            m = xl.Message(
                account=acc,
                folder=acc.drafts if entwurf else acc.sent,
                subject=betreff or "",
                body=text or "",
                to_recipients=[xl.Mailbox(email_address=a) for a in an],
                cc_recipients=[xl.Mailbox(email_address=a) for a in cc] or None,
            )
            if entwurf:
                m.save()
                return "Entwurf im Ordner Entwuerfe gespeichert."
            m.send_and_save()
            return "E-Mail an %s gesendet." % ", ".join(an)
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def antworten(self, msg_id: str, text: str, allen: bool = False,
                  entwurf: bool = False) -> str:
        m = self._suche_item(msg_id)
        acc = self._konto()
        try:
            betreff = m.subject or ""
            if not betreff.lower().startswith("re:"):
                betreff = "Re: " + betreff
            if entwurf:
                # create_reply(...).save(ordner) ist der dokumentierte Weg zum
                # Entwurf – der Entwurf behaelt dabei den Gesprächsfaden.
                erz = m.create_reply_all(betreff, text or "") if allen \
                    else m.create_reply(betreff, text or "")
                erz.save(acc.drafts)
                return "Antwort als Entwurf gespeichert."
            if allen:
                m.reply_all(subject=betreff, body=text or "")
            else:
                m.reply(subject=betreff, body=text or "")
            return "Antwort gesendet."
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def weiterleiten(self, msg_id: str, an, text: str = "", entwurf: bool = False) -> str:
        m = self._suche_item(msg_id)
        acc, xl = self._konto(), self._lib()
        an = _adressliste(an)
        _pruefe_empfaenger(an)
        try:
            betreff = m.subject or ""
            if not betreff.lower().startswith("wg:") and not betreff.lower().startswith("fw"):
                betreff = "WG: " + betreff
            empf = [xl.Mailbox(email_address=a) for a in an]
            if entwurf:
                m.create_forward(betreff, text or "", empf).save(acc.drafts)
                return "Weiterleitung als Entwurf gespeichert."
            m.forward(subject=betreff, body=text or "", to_recipients=empf)
            return "Weitergeleitet an %s." % ", ".join(an)
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def verschieben(self, msg_id: str, ziel: str) -> str:
        m = self._suche_item(msg_id)
        f = self._ordner(ziel)
        try:
            m.move(f)
            return "Nachricht nach '%s' verschoben." % ziel
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def loeschen(self, msg_id: str, endgueltig: bool = False) -> str:
        m = self._suche_item(msg_id)
        try:
            if endgueltig:
                m.delete()
                return "Nachricht endgueltig geloescht."
            m.move_to_trash()
            return "Nachricht in den Papierkorb verschoben."
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def kategorie(self, msg_id: str, name: str) -> str:
        m = self._suche_item(msg_id)
        try:
            vorhanden = list(getattr(m, "categories", None) or [])
            if name in vorhanden:
                return "Kategorie war bereits gesetzt."
            vorhanden.append(name)
            m.categories = vorhanden
            m.save(update_fields=["categories"])
            return "Kategorie '%s' gesetzt." % name
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def gelesen(self, msg_id: str, gelesen: bool = True) -> str:
        m = self._suche_item(msg_id)
        try:
            m.is_read = bool(gelesen)
            m.save(update_fields=["is_read"])
            return "Als %s markiert." % ("gelesen" if gelesen else "ungelesen")
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e

    def test(self) -> dict:
        acc = self._konto()
        try:
            posteingang = acc.inbox
            return {
                "ok": True, "kanal": "ews",
                "postfach": getattr(acc, "primary_smtp_address", self.konto.adresse),
                "ews_url": str(getattr(getattr(acc, "protocol", None), "service_endpoint", "") or ""),
                "server_version": str(getattr(getattr(acc, "version", None), "fullname", "") or ""),
                "eingang_gesamt": int(getattr(posteingang, "total_count", 0) or 0),
                "eingang_ungelesen": int(getattr(posteingang, "unread_count", 0) or 0),
            }
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "ews") from e


# ═══════════════════════════════════════════════════════════════════════════
# IMAP/SMTP-Kanal (Rueckfall)
# ═══════════════════════════════════════════════════════════════════════════

class _Imap:
    """Rueckfall ueber Standardprotokolle.

    Was hier NICHT geht und deshalb ausdruecklich als Grenze gemeldet wird:
    - **echte Weiterleitung**: IMAP/SMTP koennen die Originalnachricht samt
      Anhaengen nicht als Anhang weitergeben, ohne sie vollstaendig zu laden und
      neu zu bauen. Umgesetzt ist eine Weiterleitung des TEXTES mit Vermerk;
      Anhaenge bleiben zurueck. Ein stilles Weglassen waere schlimmer als eine
      klare Absage, deshalb steht es im Ergebnis.
    - **Kategorien**: gesetzt wird ein IMAP-Schluesselwort. Ob Outlook das als
      Kategorie anzeigt, entscheidet der Server – die Buchhaltung von Jarvis
      haengt deshalb NICHT daran (siehe mail_rules: Zustandsdatei ist die
      Wahrheit).
    """

    kanal = "imap"

    def __init__(self, konto: MailKonto):
        self.konto = konto
        self._c = None

    # ── Verbindung ──────────────────────────────────────────────────────────
    def _verbinden(self):
        if self._c is not None:
            return self._c
        k = self.konto
        host = (k.imap_host or "").strip()
        if not host:
            raise MailFehler("Kein IMAP-Server hinterlegt.", "kanal", "imap")
        try:
            if k.imap_ssl:
                ctx = ssl.create_default_context()
                if not k.verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                c = imaplib.IMAP4_SSL(host, int(k.imap_port or 993),
                                      ssl_context=ctx, timeout=k.zeitlimit)
            else:
                c = imaplib.IMAP4(host, int(k.imap_port or 143), timeout=k.zeitlimit)
                try:
                    c.starttls()
                except Exception:  # noqa: BLE001
                    pass
            c.login(k.anmeldename(), k.passwort)
            self._c = c
            return c
        except imaplib.IMAP4.error as e:  # Anmeldefehler kommen hier heraus
            raise MailFehler(str(e), "auth", "imap") from e
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e

    def schliessen(self) -> None:
        c, self._c = self._c, None
        if c is None:
            return
        for fn in ("close", "logout"):
            try:
                getattr(c, fn)()
            except Exception:  # noqa: BLE001
                pass

    def _waehlen(self, ordner: str, schreibbar: bool = True):
        c = self._verbinden()
        name = (ordner or self.konto.ordner_eingang or "INBOX").strip() or "INBOX"
        try:
            typ, _ = c.select(self._quote(name), readonly=not schreibbar)
            if typ != "OK":
                raise MailFehler("Ordner '%s' gibt es nicht." % name, "nicht_da", "imap")
        except MailFehler:
            raise
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e
        return c, name

    @staticmethod
    def _quote(name: str) -> str:
        return '"%s"' % name.replace('"', '\\"') if " " in name or "/" in name else name

    # ── Ordner ──────────────────────────────────────────────────────────────
    def ordner_liste(self) -> list[dict]:
        c = self._verbinden()
        try:
            typ, daten = c.list()
            if typ != "OK":
                return []
            raus = []
            for z in daten or []:
                if isinstance(z, bytes):
                    z = z.decode("utf-8", "replace")
                m = re.match(r'\([^)]*\)\s+"?([^"\s]+)"?\s+"?(.+?)"?$', str(z))
                if not m:
                    continue
                trenner, pfad = m.group(1), m.group(2)
                if pfad in (".", ""):
                    continue
                raus.append({"name": pfad.split(trenner)[-1], "pfad": pfad,
                             "anzahl": -1, "ungelesen": -1})
            raus.sort(key=lambda x: x["pfad"].lower())
            return raus
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e

    # ── Lesen ───────────────────────────────────────────────────────────────
    def liste(self, ordner: str = "", seit: float = 0.0, limit: int = 25,
              nur_ungelesen: bool = False, suche: str = "") -> list[MailNachricht]:
        c, name = self._waehlen(ordner, schreibbar=False)
        kriterien = []
        if seit:
            # IMAP SINCE hat Tages-Auflösung; deshalb einen Tag zurueck und
            # danach exakt nach Zeitstempel nachfiltern. Ohne den Nachfilter
            # wuerde jeder Lauf die Mails des ganzen Vortags erneut liefern.
            tag = datetime.fromtimestamp(seit, timezone.utc) - timedelta(days=1)
            kriterien += ["SINCE", tag.strftime("%d-%b-%Y")]
        if nur_ungelesen:
            kriterien.append("UNSEEN")
        if suche:
            kriterien += ["SUBJECT", '"%s"' % suche.replace('"', "")]
        if not kriterien:
            kriterien = ["ALL"]
        try:
            typ, daten = c.uid("SEARCH", None, *kriterien)
            if typ != "OK":
                return []
            uids = (daten[0] or b"").split()
            uids = uids[-max(1, int(limit or 25)) * 2:]  # Reserve fuer den Nachfilter
            raus = []
            for uid in reversed(uids):
                n = self._kopf(c, uid, name)
                if n is None:
                    continue
                if seit and n.zeitstempel and n.zeitstempel <= seit:
                    continue
                raus.append(n)
                if len(raus) >= int(limit or 25):
                    break
            return raus
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e

    def _kopf(self, c, uid: bytes, ordner: str) -> MailNachricht | None:
        try:
            typ, daten = c.uid("FETCH", uid,
                               "(FLAGS BODY.PEEK[HEADER.FIELDS "
                               "(FROM TO CC SUBJECT DATE MESSAGE-ID)])")
            if typ != "OK" or not daten:
                return None
            roh, flags = b"", ""
            for teil in daten:
                if isinstance(teil, tuple):
                    roh += teil[1] or b""
                    flags += (teil[0] or b"").decode("utf-8", "replace")
                elif isinstance(teil, bytes):
                    flags += teil.decode("utf-8", "replace")
            kopf = email.message_from_bytes(roh)
            von_name, von = email.utils.parseaddr(self._dec(kopf.get("From", "")))
            dt = email.utils.parsedate_to_datetime(kopf.get("Date", "")) if kopf.get("Date") else None
            mid = (kopf.get("Message-ID") or "").strip()
            return MailNachricht(
                id=uid.decode() if isinstance(uid, bytes) else str(uid),
                schluessel=mid or ("%s:%s" % (ordner, uid.decode() if isinstance(uid, bytes) else uid)),
                ordner=ordner,
                von=von, von_name=von_name,
                an=_adressliste(self._dec(kopf.get("To", ""))),
                cc=_adressliste(self._dec(kopf.get("Cc", ""))),
                betreff=self._dec(kopf.get("Subject", "")),
                datum=_iso(dt), zeitstempel=_stempel(dt),
                ungelesen="\\Seen" not in flags,
                kategorien=re.findall(r"\$([A-Za-z0-9_-]+)", flags),
            )
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _dec(wert: str) -> str:
        try:
            teile = email.header.decode_header(wert or "")
            raus = []
            for t, kod in teile:
                if isinstance(t, bytes):
                    raus.append(t.decode(kod or "utf-8", "replace"))
                else:
                    raus.append(t)
            return "".join(raus).strip()
        except Exception:  # noqa: BLE001
            return wert or ""

    def lesen(self, msg_id: str, ordner: str = "") -> MailNachricht:
        c, name = self._waehlen(ordner, schreibbar=False)
        try:
            typ, daten = c.uid("FETCH", str(msg_id), "(BODY.PEEK[])")
            if typ != "OK" or not daten or not isinstance(daten[0], tuple):
                raise MailFehler("Nachricht %s nicht gefunden." % msg_id, "nicht_da", "imap")
            msg = email.message_from_bytes(daten[0][1] or b"")
            n = MailNachricht(
                id=str(msg_id), ordner=name,
                schluessel=(msg.get("Message-ID") or "").strip() or "%s:%s" % (name, msg_id),
                betreff=self._dec(msg.get("Subject", "")),
                an=_adressliste(self._dec(msg.get("To", ""))),
                cc=_adressliste(self._dec(msg.get("Cc", ""))),
            )
            n.von_name, n.von = email.utils.parseaddr(self._dec(msg.get("From", "")))
            if msg.get("Date"):
                dt = email.utils.parsedate_to_datetime(msg.get("Date"))
                n.datum, n.zeitstempel = _iso(dt), _stempel(dt)
            n.text, n.anhaenge = self._koerper(msg)
            n.hat_anhaenge = bool(n.anhaenge)
            return n
        except MailFehler:
            raise
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e

    @staticmethod
    def _koerper(msg) -> tuple[str, list[str]]:
        """Nur-Text bevorzugen, HTML entschaerfen, Anhangsnamen sammeln."""
        text, html, anhaenge = "", "", []
        if msg.is_multipart():
            for teil in msg.walk():
                if teil.get_content_maintype() == "multipart":
                    continue
                name = teil.get_filename()
                if name:
                    anhaenge.append(_Imap._dec(name))
                    continue
                typ = teil.get_content_type()
                try:
                    roh = teil.get_payload(decode=True) or b""
                    inhalt = roh.decode(teil.get_content_charset() or "utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
                if typ == "text/plain" and not text:
                    text = inhalt
                elif typ == "text/html" and not html:
                    html = inhalt
        else:
            try:
                roh = msg.get_payload(decode=True) or b""
                inhalt = roh.decode(msg.get_content_charset() or "utf-8", "replace")
            except Exception:  # noqa: BLE001
                inhalt = ""
            if msg.get_content_type() == "text/html":
                html = inhalt
            else:
                text = inhalt
        return (text or html_zu_text(html) or ""), anhaenge

    # ── Schreiben ───────────────────────────────────────────────────────────
    def _smtp(self):
        k = self.konto
        host = (k.smtp_host or "").strip()
        if not host:
            raise MailFehler("Kein SMTP-Server hinterlegt – Senden ist ueber diesen "
                             "Kanal nicht moeglich.", "kanal", "smtp")
        try:
            if int(k.smtp_port or 587) == 465:
                ctx = ssl.create_default_context()
                if not k.verify_ssl:
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                s = smtplib.SMTP_SSL(host, 465, timeout=k.zeitlimit, context=ctx)
            else:
                s = smtplib.SMTP(host, int(k.smtp_port or 587), timeout=k.zeitlimit)
                if k.smtp_starttls:
                    ctx = ssl.create_default_context()
                    if not k.verify_ssl:
                        ctx.check_hostname = False
                        ctx.verify_mode = ssl.CERT_NONE
                    s.starttls(context=ctx)
            s.login(k.anmeldename(), k.passwort)
            return s
        except smtplib.SMTPAuthenticationError as e:
            raise MailFehler(str(e), "auth", "smtp") from e
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "smtp") from e

    def _bauen(self, an: list[str], betreff: str, text: str, cc: list[str],
               bezug: str = "") -> EmailMessage:
        m = EmailMessage()
        m["From"] = self.konto.adresse
        m["To"] = ", ".join(an)
        if cc:
            m["Cc"] = ", ".join(cc)
        m["Subject"] = betreff or ""
        m["Date"] = email.utils.formatdate(localtime=True)
        m["Message-ID"] = email.utils.make_msgid()
        if bezug:
            m["In-Reply-To"] = bezug
            m["References"] = bezug
        m.set_content(text or "")
        return m

    def senden(self, an, betreff: str, text: str, cc=None, entwurf: bool = False) -> str:
        an, cc = _adressliste(an), _adressliste(cc)
        if entwurf:
            return self._entwurf_ablegen(self._bauen(an, betreff, text, cc))
        _pruefe_empfaenger(an)
        m = self._bauen(an, betreff, text, cc)
        s = None
        try:
            s = self._smtp()
            s.send_message(m)
        finally:
            if s is not None:
                try:
                    s.quit()
                except Exception:  # noqa: BLE001
                    pass
        self._kopie_ablegen(m)
        return "E-Mail an %s gesendet." % ", ".join(an)

    def _entwurf_ablegen(self, m: EmailMessage) -> str:
        ordner = (self.konto.ordner_entwuerfe or "").strip() or "Drafts"
        c = self._verbinden()
        try:
            c.append(self._quote(ordner), "(\\Draft)",
                     imaplib.Time2Internaldate(time.time()), m.as_bytes())
            return "Entwurf im Ordner '%s' gespeichert." % ordner
        except Exception as e:  # noqa: BLE001
            raise MailFehler(
                "Entwurf konnte nicht abgelegt werden (Ordner '%s'). Ordnername im "
                "E-Mail-Bereich pruefen. Meldung: %s" % (ordner, e), "fehler", "imap") from e

    def _kopie_ablegen(self, m: EmailMessage) -> None:
        """Gesendete Nachricht in den Ordner legen – best effort.

        Erfolg wird am SENDEN gemessen, nicht am Ablegen: SMTP hat die Mail
        schon zugestellt, wenn das hier scheitert. Ein Fehler waere hier eine
        Falschmeldung ("nicht gesendet"), obwohl sie beim Empfaenger liegt –
        dieselbe Abwaegung wie bei ``_ingest`` in agent.py.
        """
        ordner = (self.konto.ordner_gesendet or "").strip()
        if not ordner:
            return
        try:
            self._verbinden().append(self._quote(ordner), "(\\Seen)",
                                     imaplib.Time2Internaldate(time.time()), m.as_bytes())
        except Exception as e:  # noqa: BLE001
            print("[Mail] Kopie im Ordner '%s' nicht abgelegt: %s" % (ordner, e), flush=True)

    def antworten(self, msg_id: str, text: str, allen: bool = False,
                  entwurf: bool = False) -> str:
        alt = self.lesen(msg_id)
        an = [alt.von] if alt.von else []
        cc = []
        if allen:
            eigen = (self.konto.adresse or "").lower()
            cc = [a for a in (alt.an + alt.cc) if a.lower() != eigen and a.lower() != (alt.von or "").lower()]
        betreff = alt.betreff or ""
        if not betreff.lower().startswith("re:"):
            betreff = "Re: " + betreff
        zitat = "\n\n----- Urspruengliche Nachricht -----\nVon: %s\nDatum: %s\nBetreff: %s\n\n%s" % (
            alt.von, alt.datum, alt.betreff, (alt.text or "")[:5000])
        m = self._bauen(an, betreff, (text or "") + zitat, cc, bezug=alt.schluessel)
        if entwurf:
            return self._entwurf_ablegen(m)
        _pruefe_empfaenger(an)
        s = None
        try:
            s = self._smtp()
            s.send_message(m)
        finally:
            if s is not None:
                try:
                    s.quit()
                except Exception:  # noqa: BLE001
                    pass
        self._kopie_ablegen(m)
        return "Antwort an %s gesendet." % ", ".join(an)

    def weiterleiten(self, msg_id: str, an, text: str = "", entwurf: bool = False) -> str:
        alt = self.lesen(msg_id)
        an = _adressliste(an)
        _pruefe_empfaenger(an)
        betreff = alt.betreff or ""
        if not betreff.lower().startswith("wg:"):
            betreff = "WG: " + betreff
        hinweis = ""
        if alt.anhaenge:
            hinweis = ("\n\n[Hinweis: Diese Weiterleitung lief ueber IMAP/SMTP. Die "
                       "Anhaenge der Originalnachricht (%s) sind NICHT enthalten.]"
                       % ", ".join(alt.anhaenge))
        rumpf = "%s\n\n----- Weitergeleitete Nachricht -----\nVon: %s\nDatum: %s\nBetreff: %s\n\n%s%s" % (
            text or "", alt.von, alt.datum, alt.betreff, (alt.text or "")[:8000], hinweis)
        m = self._bauen(an, betreff, rumpf, [])
        if entwurf:
            return self._entwurf_ablegen(m)
        s = None
        try:
            s = self._smtp()
            s.send_message(m)
        finally:
            if s is not None:
                try:
                    s.quit()
                except Exception:  # noqa: BLE001
                    pass
        self._kopie_ablegen(m)
        ergebnis = "Weitergeleitet an %s." % ", ".join(an)
        if alt.anhaenge:
            ergebnis += (" ACHTUNG: ueber IMAP ohne die Anhaenge (%s) – der Empfaenger "
                         "wurde im Text darauf hingewiesen." % ", ".join(alt.anhaenge))
        return ergebnis

    def verschieben(self, msg_id: str, ziel: str) -> str:
        c, _ = self._waehlen("", schreibbar=True)
        try:
            if hasattr(c, "uid") and "MOVE" in (getattr(c, "capabilities", ()) or ()):
                typ, _d = c.uid("MOVE", str(msg_id), self._quote(ziel))
                if typ == "OK":
                    return "Nachricht nach '%s' verschoben." % ziel
            typ, _d = c.uid("COPY", str(msg_id), self._quote(ziel))
            if typ != "OK":
                raise MailFehler("Kopieren nach '%s' fehlgeschlagen." % ziel, "nicht_da", "imap")
            c.uid("STORE", str(msg_id), "+FLAGS", "(\\Deleted)")
            c.expunge()
            return "Nachricht nach '%s' verschoben." % ziel
        except MailFehler:
            raise
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e

    def loeschen(self, msg_id: str, endgueltig: bool = False) -> str:
        if not endgueltig:
            papierkorb = "Trash"
            try:
                return self.verschieben(msg_id, papierkorb)
            except MailFehler:
                pass  # kein Papierkorb: dann Loesch-Merker setzen
        c, _ = self._waehlen("", schreibbar=True)
        try:
            c.uid("STORE", str(msg_id), "+FLAGS", "(\\Deleted)")
            c.expunge()
            return "Nachricht geloescht."
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e

    def kategorie(self, msg_id: str, name: str) -> str:
        c, _ = self._waehlen("", schreibbar=True)
        marke = "$" + re.sub(r"[^A-Za-z0-9_-]", "", name or "Jarvis")
        try:
            typ, _d = c.uid("STORE", str(msg_id), "+FLAGS", "(%s)" % marke)
            if typ != "OK":
                return ("Der Server nimmt keine Schluesselwoerter an – die Verarbeitung "
                        "ist trotzdem vermerkt (Zustandsdatei).")
            return "Schluesselwort %s gesetzt." % marke
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e

    def gelesen(self, msg_id: str, gelesen: bool = True) -> str:
        c, _ = self._waehlen("", schreibbar=True)
        try:
            c.uid("STORE", str(msg_id), "+FLAGS" if gelesen else "-FLAGS", "(\\Seen)")
            return "Als %s markiert." % ("gelesen" if gelesen else "ungelesen")
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e

    def test(self) -> dict:
        c, name = self._waehlen(self.konto.ordner_eingang, schreibbar=False)
        try:
            typ, daten = c.uid("SEARCH", None, "ALL")
            gesamt = len((daten[0] or b"").split()) if typ == "OK" else -1
            typ, daten = c.uid("SEARCH", None, "UNSEEN")
            unge = len((daten[0] or b"").split()) if typ == "OK" else -1
            return {"ok": True, "kanal": "imap", "postfach": self.konto.adresse,
                    "imap_host": self.konto.imap_host, "smtp_host": self.konto.smtp_host,
                    "ordner": name, "eingang_gesamt": gesamt, "eingang_ungelesen": unge}
        except Exception as e:  # noqa: BLE001
            raise _einordnen(e, "imap") from e


# ═══════════════════════════════════════════════════════════════════════════
# Fassade mit Kanalwahl
# ═══════════════════════════════════════════════════════════════════════════

_OPERATIONEN = ("test", "ordner_liste", "liste", "lesen", "senden", "antworten",
                "weiterleiten", "verschieben", "loeschen", "kategorie", "gelesen")


class MailClient:
    """Ein Postfach, zwei moegliche Wege dorthin.

    Der gewaehlte Kanal wird nach dem ersten Erfolg FESTGEHALTEN
    (``self.aktiver_kanal``): sonst wuerde jeder Aufruf erneut den EWS-Weg
    versuchen und in dieselbe Zeitueberschreitung laufen – bei einem Regel-Lauf
    mit zehn Nachrichten zehnmal.
    """

    def __init__(self, konto: MailKonto):
        ok, grund = konto.gueltig()
        if not ok:
            raise MailFehler(grund, "eingabe")
        self.konto = konto
        self.aktiver_kanal = ""
        self._ews = _Ews(konto)
        self._imap = _Imap(konto)

    # ── Kanalwahl ───────────────────────────────────────────────────────────
    def _kandidaten(self) -> list:
        gewuenscht = (self.konto.kanal or "auto").lower()
        if self.aktiver_kanal == "ews":
            return [self._ews]
        if self.aktiver_kanal == "imap":
            return [self._imap]
        if gewuenscht == "ews":
            return [self._ews]
        if gewuenscht == "imap":
            return [self._imap]
        return [self._ews, self._imap]

    def _ruf(self, op: str, *a, **kw):
        """Vorgang ueber den ersten nutzbaren Kanal ausfuehren.

        SCHEITERN BEIDE KANAELE, MUSS DIE MELDUNG BEIDE NENNEN. Der erste
        Anlauf ist fast immer der interessante: auf DEV meldete der Fehler nur
        "Kein IMAP-Server hinterlegt", obwohl vorher EWS an einem
        Autodiscover-Problem gescheitert war – ein Administrator sucht dann am
        falschen Ende (und traegt einen IMAP-Server ein, den er nicht braucht).
        """
        if op not in _OPERATIONEN:
            raise MailFehler("Unbekannte Mail-Operation '%s'." % op, "eingabe")
        vorherige: list[str] = []
        kandidaten = self._kandidaten()
        for i, backend in enumerate(kandidaten):
            try:
                ergebnis = getattr(backend, op)(*a, **kw)
                self.aktiver_kanal = backend.kanal
                return ergebnis
            except Exception as e:  # noqa: BLE001
                f = e if isinstance(e, MailFehler) else _einordnen(e, backend.kanal)
                letzter = i + 1 >= len(kandidaten)
                if f.kategorie not in _RUECKFALL_KATEGORIEN or letzter:
                    if vorherige:
                        # Vorgeschichte anhaengen, Kategorie und Kanal des
                        # letzten Versuchs behalten (der Aufrufer entscheidet
                        # daran ueber den Rueckfall).
                        f = MailFehler("%s | Zuvor versucht: %s"
                                       % (f, "; ".join(vorherige)),
                                       f.kategorie, f.kanal)
                    raise f from e
                vorherige.append("%s → %s" % (backend.kanal, f))
                print("[Mail] Kanal %s nicht nutzbar (%s) – versuche %s"
                      % (backend.kanal, f, kandidaten[i + 1].kanal), flush=True)
        raise MailFehler("Kein Zugangsweg zum Postfach.", "kanal")

    def schliessen(self) -> None:
        try:
            self._imap.schliessen()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.schliessen()
        return False

    # ── Vorgaenge ───────────────────────────────────────────────────────────
    def test(self) -> dict:
        return self._ruf("test")

    def ordner(self) -> list[dict]:
        return self._ruf("ordner_liste")

    def liste(self, ordner: str = "", seit: float = 0.0, limit: int = 25,
              nur_ungelesen: bool = False, suche: str = "") -> list[MailNachricht]:
        return self._ruf("liste", ordner=ordner, seit=seit, limit=limit,
                         nur_ungelesen=nur_ungelesen, suche=suche)

    def lesen(self, msg_id: str, ordner: str = "") -> MailNachricht:
        return self._ruf("lesen", msg_id, ordner=ordner)

    def senden(self, an, betreff: str, text: str, cc=None, entwurf: bool = False) -> str:
        return self._ruf("senden", an, betreff, text, cc=cc, entwurf=entwurf)

    def antworten(self, msg_id: str, text: str, allen: bool = False,
                  entwurf: bool = False) -> str:
        return self._ruf("antworten", msg_id, text, allen=allen, entwurf=entwurf)

    def weiterleiten(self, msg_id: str, an, text: str = "", entwurf: bool = False) -> str:
        return self._ruf("weiterleiten", msg_id, an, text=text, entwurf=entwurf)

    def verschieben(self, msg_id: str, ziel: str) -> str:
        return self._ruf("verschieben", msg_id, ziel)

    def loeschen(self, msg_id: str, endgueltig: bool = False) -> str:
        return self._ruf("loeschen", msg_id, endgueltig=endgueltig)

    def kategorie(self, msg_id: str, name: str) -> str:
        return self._ruf("kategorie", msg_id, name)

    def gelesen(self, msg_id: str, gelesen: bool = True) -> str:
        return self._ruf("gelesen", msg_id, gelesen=gelesen)
