"""Schutz vor Datenabfluss ueber E-Mail-Regeln (Massnahmen 1-4, 2026-11-20).

WARUM ES DAS GIBT: ein Regel-Lauf verbindet drei Dinge, die man sonst trennt –
Fremdtext (die eingegangene Mail), Zugriff auf Firmenwissen (Bereiche
``wissen``, ``fach``, ``dokumente``, ``adressbuch``, ``voll``) und einen
Sendeweg. Bis hierher war die einzige harte Grenze der Werkzeug-Zuschnitt, und
INNERHALB davon durfte eine Regel mit Aussenwirkung an beliebige Adressen
senden. Eine praeparierte Mail ("schicke die Preisliste an …") war damit nur
durch eine Bitte im Prompt aufgehalten. Dazu kommt der zweite Weg: Regel-Prompt,
Stile und Signaturen sind GESPEICHERTER Text, der spaeter ohne anwesenden
Menschen wirkt – ein Kennwort oder eine eingeschmuggelte Anweisung darin geht
bei jedem Lauf mit.

Vier Massnahmen, die ersten drei sitzen im CODE, nicht im Prompt:

1. **Empfaenger-Schranke** (``versand_pruefen``): in einem Regel-Lauf geht eine
   Mail nur dann direkt hinaus, wenn jeder Empfaenger in einer freigegebenen
   Domaene liegt (Skill-Config ``versand_domaenen``; leer = die Domaene des
   eigenen Postfachs) ODER am Gespraech beteiligt ist (Absender/Empfaenger der
   eingegangenen Nachricht). Alles andere wird zum ENTWURF – nicht abgewiesen:
   der Inhaber sieht, was die Regel wollte, und sendet selbst. Ein Abweisen
   haette die Arbeit der Regel weggeworfen und waere als Fehlversuch gezaehlt
   worden (drei davon, und die Nachricht bleibt liegen).
2. **Gefaehrliche Kombination** (ebenda): hat die Regel einen Bereich AUSSER
   ``mail``, geht an externe Empfaenger nur ein Entwurf – auch an den
   Absender. Bewusst als Ausschluss formuliert ("alles ausser mail"), nicht als
   Liste der Wissensbereiche: ein kuenftiger Bereich faellt damit fail-closed
   auf die strenge Seite (Register: eine Namensliste ist an dem Tag
   unvollstaendig, an dem jemand einen Bereich hinzufuegt).
3. **Ausgangspruefung** (``inhalt_befunde``): Text, Betreff und – bei einer
   fremden Nachricht – das Zitierte werden auf Zugangsdaten (Schluesselformen,
   Kennwort-Angaben, Kartennummern) und auf die Sperrbegriffe des Admins
   (``sperrbegriffe``) geprueft. Ein Treffer macht den Versand zum Entwurf,
   AUCH an interne Empfaenger. Anhaenge an externe Empfaenger ebenso: ihren
   Inhalt kann diese Pruefung nicht verlaesslich lesen, und "nicht geprueft"
   darf nicht "freigegeben" heissen.
4. **Pruefung beim Speichern** (``feld_pruefen``): Regel-Prompt, Stil und
   Signatur werden VOR dem Speichern auf dieselben Befunde geprueft, Stile und
   Prompts zusaetzlich auf Injektionsmuster, Stile auf Handlungsanweisungen
   (weiterleiten, Kopie an, Werkzeugnamen) und fremde Adressen, Signaturen auf
   versteckten Text und Bilder von fremden Servern (Zaehlpixel). Ein Treffer
   lehnt das SPEICHERN ab – er sperrt kein Konto: der Text stammt vom Benutzer
   selbst, oft aus einer Vorlage kopiert, und eine Kontosperre fuer einen
   eingefuegten Absatz waere die Lehre vom 2026-08-05 noch einmal.

WAS DAS NICHT LEISTET – benannt, nicht verschwiegen:
- Ob ein Text "Firmenwissen" enthaelt, ist nicht entscheidbar. Die
  Inhaltspruefung erkennt Formen (Schluessel, Kennwort-Angaben) und die
  Begriffe, die der Admin nennt – sie ist Sichtbarkeit, die harte Grenze sind
  1 und 2.
- Die Schranke gilt fuer die Mail-Werkzeuge. Ein Regel-Lauf mit Bereich
  ``voll`` hat weitere Aussenkanaele (Messenger, Ticketsysteme); dort gilt
  weiter nur die Freigabe "Darf nach außen wirken" (``wirkung.py``).
- Im CHAT gilt sie nicht: dort sieht der Mensch jede Sendung in der
  Bestaetigungskarte (BSI H9) – eine zweite Schranke wuerde dort nur seine
  Entscheidung ueberstimmen.
"""

from __future__ import annotations

import contextvars
import html as _html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# ── Konfiguration (Skill-Config des E-Mail-Skills) ──────────────────────────

CFG_DOMAENEN = "versand_domaenen"
CFG_SPERRBEGRIFFE = "sperrbegriffe"
# Kuerzere Sperrbegriffe werden ignoriert: "AG" oder "IT" traefen jeden
# zweiten Satz und machten aus jeder Antwort einen Entwurf.
SPERRBEGRIFF_MIN = 3
# Deckel fuer die Liste – sie wird bei jedem Versand gegen den Text geprueft.
SPERRBEGRIFFE_MAX = 500


def _cfg() -> dict:
    try:
        from backend import mail_accounts
        return mail_accounts.skill_config() or {}
    except Exception:  # noqa: BLE001
        return {}


def _liste(roh) -> list[str]:
    """Komma-, Semikolon- oder zeilengetrennte Eingabe als Liste."""
    if isinstance(roh, (list, tuple)):
        teile = [str(x) for x in roh]
    else:
        teile = re.split(r"[,;\n]", str(roh or ""))
    return [t.strip() for t in teile if t and t.strip()]


def domaene(adresse: str) -> str:
    """Domaene einer Adresse, klein geschrieben – "" ohne ``@``."""
    a = str(adresse or "").strip().lower()
    if "<" in a and ">" in a:
        a = a[a.rfind("<") + 1:a.rfind(">")].strip()
    if "@" not in a:
        return ""
    return a.rsplit("@", 1)[1].strip().rstrip(".")


def versand_domaenen(eigene_adresse: str = "", cfg: dict | None = None) -> list[str]:
    """Domaenen, an die ein Regel-Lauf ohne Entwurf senden darf.

    Leer konfiguriert = die Domaene des eigenen Postfachs. Ohne beides ist die
    Liste LEER – dann ist jeder Empfaenger extern (fail-closed).
    """
    c = _cfg() if cfg is None else cfg
    doms = []
    for d in _liste(c.get(CFG_DOMAENEN)):
        d = d.lower().lstrip("@").lstrip("*").lstrip(".").strip()
        if d and "." in d and d not in doms:
            doms.append(d)
    if not doms:
        eigen = domaene(eigene_adresse)
        if eigen:
            doms.append(eigen)
    return doms


def domaene_erlaubt(adresse: str, domaenen: list[str]) -> bool:
    """Liegt die Adresse in einer der Domaenen (Subdomaenen eingeschlossen)?

    ⚠ Vergleich auf Domaenengrenze, nicht per Teilstring: ``firma.de.boese.org``
    und ``nichtfirma.de`` duerfen nicht als ``firma.de`` durchgehen.
    """
    d = domaene(adresse)
    if not d:
        return False
    return any(d == x or d.endswith("." + x) for x in domaenen)


def sperrbegriffe(cfg: dict | None = None) -> list[str]:
    c = _cfg() if cfg is None else cfg
    raus = []
    for b in _liste(c.get(CFG_SPERRBEGRIFFE)):
        if len(b) >= SPERRBEGRIFF_MIN and b.lower() not in (x.lower() for x in raus):
            raus.append(b)
    return raus[:SPERRBEGRIFFE_MAX]


# ── Inhaltspruefung (Massnahme 3, auch fuer 4) ──────────────────────────────

# Je Muster GENAU EINE Form. Die Namen sind Oberflaechentexte (sie stehen in
# der Ablehnung und im Ergebnis des Laufs) – deshalb mit Umlauten.
_GEHEIM_DEFS = [
    ("privater Schlüssel",
     r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"),
    ("AWS-Zugangsschlüssel", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("GitHub-Token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    ("Slack-Token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    ("API-Schlüssel", r"\bsk-(?:ant-|proj-|live-)?[A-Za-z0-9_-]{24,}"),
    ("Google-API-Schlüssel", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("Anmelde-Token (JWT)",
     r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("Adresse mit Kennwort", r"\b[a-z][a-z0-9+.-]{1,15}://[^\s/:@]{1,64}:[^\s/@]{3,}@[^\s]+"),
    # Eine Kennwort-ANGABE, nicht das Wort: "Passwort: wird separat
    # zugeschickt" ist harmlos. Gezaehlt wird nur ein Wert, der wie ein
    # Kennwort aussieht – mindestens 6 Zeichen und eine Ziffer oder ein
    # Sonderzeichen.
    ("Kennwort-Angabe",
     r"(?i)\b(?:passwor[dt]|kennwort|passwd|pwd|pin|secret|geheimnis|api[_ -]?key|"
     r"zugangscode|access[_ -]?token)\b\s*[:=]\s*"
     r"(?=\S{6,})(?=\S*[0-9!#$%&*+/=?^_~@-])\S+"),
]
_GEHEIM = [(name, re.compile(rx)) for name, rx in _GEHEIM_DEFS]

# Kartennummern: nur die Praefixe der grossen Anbieter und nur mit Luhn-Pruefung.
# Ohne beides traefe jede lange Telefonnummer in einer Signatur.
_KARTE = re.compile(r"\b(?:4\d{3}|5[1-5]\d{2}|3[47]\d{2})(?:[ -]?\d){11,15}\b")
# Form einer IBAN (Laendercode, Pruefziffern, 11-30 weitere Zeichen, in
# Vierergruppen oder am Stueck). Die Pruefsumme wird bewusst NICHT verlangt:
# auch eine vertippte IBAN ist keine Kartennummer.
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{1,4}){3,8}\b")


def _luhn(ziffern: str) -> bool:
    summe, doppelt = 0, False
    for z in reversed(ziffern):
        n = int(z)
        if doppelt:
            n *= 2
            if n > 9:
                n -= 9
        summe += n
        doppelt = not doppelt
    return summe % 10 == 0


def geheimnis_befunde(text: str) -> list[str]:
    """Namen der gefundenen Zugangsdaten-Formen (ohne den Wert selbst)."""
    t = str(text or "")
    if not t.strip():
        return []
    raus = [name for name, rx in _GEHEIM if rx.search(t)]
    # IBANs VOR der Kartensuche herausnehmen: ihre Vierergruppen sehen wie eine
    # Kartennummer aus ("DE89 3704 0044 …" beginnt mit dem Amex-Praefix 37),
    # und die Luhn-Pruefung besteht ein solcher Abschnitt in jedem zehnten
    # Fall. Eine Bankverbindung gehoert zu den Pflichtangaben einer Signatur –
    # sie zu blockieren waere ein Fehlalarm im Regelfall (gefunden von der
    # Gegenprobe "ohne Luhn").
    t = _IBAN.sub(" ", t)
    for m in _KARTE.finditer(t):
        ziffern = re.sub(r"\D", "", m.group(0))
        if 13 <= len(ziffern) <= 19 and _luhn(ziffern):
            raus.append("Kartennummer")
            break
    return raus


def sperrbegriff_befunde(text: str, begriffe: list[str] | None = None) -> list[str]:
    """Sperrbegriffe, die im Text vorkommen (Gross/klein egal, an Wortgrenzen)."""
    t = str(text or "")
    if not t.strip():
        return []
    raus = []
    for b in (sperrbegriffe() if begriffe is None else begriffe):
        # Wortgrenze nur dort, wo der Begriff selbst mit einem Wortzeichen
        # beginnt/endet – sonst trafe "C#" nie.
        vor = r"(?<!\w)" if re.match(r"\w", b) else ""
        nach = r"(?!\w)" if re.search(r"\w$", b) else ""
        if re.search(vor + re.escape(b) + nach, t, re.IGNORECASE):
            raus.append(b)
    return raus


def inhalt_befunde(text: str, begriffe: list[str] | None = None) -> list[str]:
    """Alle Inhaltsbefunde als lesbare Gruende."""
    raus = ["Zugangsdaten (%s)" % n for n in geheimnis_befunde(text)]
    raus += ["Sperrbegriff „%s“" % b for b in sperrbegriff_befunde(text, begriffe)]
    return raus


# ── Pruefung beim Speichern (Massnahme 4) ───────────────────────────────────

_ADRESSE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Handlungsanweisungen, die in einem STIL nichts verloren haben. Ein Stil
# bestimmt die Form eines Textes, den die Regel ohnehin verlangt
# (mail_runner._VORSPANN) – "leite weiter", "Kopie an", "BCC" oder ein
# Werkzeugname sind dort ein Versuch, ueber das Formfeld eine Aktion
# auszuloesen. Bewusst KEIN allgemeines "sende … an": "Wir senden Ihnen die
# Unterlagen an Ihre Adresse" ist ein gewoehnlicher Satz in einer Stilvorgabe.
_STIL_AKTION_DEFS = [
    ("Weiterleiten", r"(?i)\bweiterleit\w*|\bleite\w*\b[^.\n]{0,80}\bweiter\b|\bforward\w*\b"),
    ("Kopie an weitere Empfänger",
     r"(?i)\bbcc\b|\bblindkopie\b|\b(?:in\s+)?kopie\s+an\b|\bcc\s*(?:an|:)|\bcarbon\s+copy\b"),
    ("Werkzeugname", r"\b(?:email|knowledge|jira|confluence|sap|office|shell)_[a-z_]{3,}\b"),
    ("Löschanweisung", r"(?i)\b(?:lösche|loesche|delete)\b"),
]
_STIL_AKTION = [(n, re.compile(rx)) for n, rx in _STIL_AKTION_DEFS]


def _injektion(text: str) -> str:
    """Name eines Injektionsmusters aus der zentralen Heuristik – oder "".

    Die Muster stehen in ``security_guard`` (eine Quelle fuer alle Kanaele).
    Fehlt das Modul (Testumgebung ohne Konfiguration), entfaellt NUR dieser
    Teil – die uebrigen Pruefungen laufen weiter.
    """
    try:
        from backend import security_guard
    except Exception:  # noqa: BLE001
        return ""
    try:
        return (security_guard.heuristic_match(text)
                or security_guard.weich_match(text) or "")
    except Exception:  # noqa: BLE001
        return ""


# Versteckter Text in einer Signatur: geht an jeden Empfaenger mit, ohne dass
# der Absender ihn sieht – der Weg, ueber den eine Signatur zur Anweisung an
# das KI-Postfach des Empfaengers wird, oder Daten unsichtbar mitnimmt.
_VERSTECKT_STYLE = re.compile(
    r"(?i)(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)|"
    r"font-size\s*:\s*(?:0|0?\.\d+|1)(?:px|pt|em|rem)?\s*(?:;|$)|"
    r"max-height\s*:\s*0|(?:^|;)\s*height\s*:\s*0(?:px)?\s*(?:;|$)|"
    r"(?:^|;)\s*color\s*:\s*(?:#fff(?:fff)?|white|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\))\s*(?:;|$))")
_WEISS = re.compile(r"(?i)^\s*(?:#fff(?:fff)?|white)\s*$")


class _SigSonde(HTMLParser):
    """Sammelt versteckte Stellen und fremde Bildquellen einer Signatur."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.versteckt: list[str] = []
        self.bilder: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {(k or "").lower(): (v or "") for k, v in attrs}
        stil = a.get("style", "")
        if stil and _VERSTECKT_STYLE.search(stil):
            self.versteckt.append("<%s style=\"%s\">" % (tag, stil.strip()[:60]))
        if tag == "font" and _WEISS.match(a.get("color", "")):
            self.versteckt.append("<font color=\"%s\">" % a.get("color"))
        if a.get("hidden") is not None and "hidden" in a:
            self.versteckt.append("<%s hidden>" % tag)
        if tag == "img":
            src = a.get("src", "").strip()
            if re.match(r"(?i)^https?://", src):
                self.bilder.append(src)

    handle_startendtag = handle_starttag


def _html_zu_text(h: str) -> str:
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", str(h or ""))
    t = re.sub(r"<[^>]+>", " ", t)
    return _html.unescape(t)


def feld_pruefen(art: str, text: str = "", html: str = "",
                 eigene_adresse: str = "", cfg: dict | None = None) -> list[str]:
    """Gruende, warum ``text``/``html`` so nicht gespeichert werden darf.

    ``art``: ``"regel"`` (Regel-Prompt), ``"stil"`` oder ``"signatur"``.
    Leere Liste = in Ordnung. Wirft nie – die Aufrufer machen aus den Gruenden
    ihren eigenen Fehler (``RegelFehler`` bzw. ``MailFehler``).
    """
    c = _cfg() if cfg is None else cfg
    begriffe = sperrbegriffe(c)
    voll = "\n".join(x for x in (str(text or ""), _html_zu_text(html)) if x)
    gruende = inhalt_befunde(voll, begriffe)

    if art in ("regel", "stil"):
        muster = _injektion(voll)
        if muster:
            gruende.append("Muster einer eingeschleusten Anweisung (%s)" % muster)

    if art == "stil":
        for name, rx in _STIL_AKTION:
            if rx.search(voll):
                gruende.append("Handlungsanweisung im Stil (%s) – ein Stil bestimmt "
                               "nur die Form, Aktionen gehören in die Regel" % name)
        doms = versand_domaenen(eigene_adresse, c)
        fremd = sorted({a for a in _ADRESSE.findall(voll)
                        if not domaene_erlaubt(a, doms)})
        if fremd:
            gruende.append("externe E-Mail-Adresse(n) im Stil: %s" % ", ".join(fremd[:5]))

    if art == "signatur" and (html or "").strip():
        sonde = _SigSonde()
        try:
            sonde.feed(str(html))
            sonde.close()
        except Exception:  # noqa: BLE001
            # Unlesbares HTML wird beim Versand ohnehin verworfen
            # (mail_body.html_entschaerfen, fail-closed) – hier nicht doppelt.
            pass
        if sonde.versteckt:
            gruende.append("versteckter Text in der Signatur (%s)"
                           % ", ".join(sonde.versteckt[:3]))
        doms = versand_domaenen(eigene_adresse, c)
        fremd = []
        for src in sonde.bilder:
            host = re.sub(r"(?i)^https?://", "", src).split("/", 1)[0].split(":", 1)[0]
            if not domaene_erlaubt("x@" + host, doms) and host not in fremd:
                fremd.append(host)
        if fremd:
            gruende.append("Bild von einem fremden Server (%s) – solche Bilder "
                           "melden dem Absender jedes Öffnen; ein Logo gehört "
                           "eingebettet oder auf einen eigenen Server"
                           % ", ".join(fremd[:3]))
    return gruende


def ablehnung(art: str, gruende: list[str]) -> str:
    """Ablehnungstext fuer die Oberflaeche – nennt den Weg, nicht nur den Grund."""
    was = {"regel": "Die Regel", "stil": "Der Stil",
           "signatur": "Die Signatur"}.get(art, "Der Text")
    return ("%s wurde nicht gespeichert (Schutz vor Datenabfluss): %s. "
            "Zugangsdaten und vertrauliche Angaben gehören nicht in gespeicherte "
            "Texte – sie gingen bei jedem Lauf bzw. mit jeder Mail mit."
            % (was, "; ".join(gruende)))


# ── Laufschranke (Massnahmen 1-3) ───────────────────────────────────────────

@dataclass(frozen=True)
class Lauf:
    """Was die Schranke ueber den laufenden Regel-Lauf wissen muss."""
    regel: str
    mail_id: str
    eigene_adresse: str
    beteiligte: frozenset = field(default_factory=frozenset)
    # Bereiche ausser "mail" – nicht leer heisst: der Lauf kann Firmenwissen
    # lesen (Massnahme 2).
    weitere_bereiche: tuple = ()


# Gesetzt NUR im Regel-Lauf (mail_runner._lauf_fuer_nachricht). Ohne Wert gilt
# die Schranke nicht – im Chat entscheidet der Mensch in der Karte.
lauf_cv: contextvars.ContextVar = contextvars.ContextVar("jarvis_mail_schutz_lauf",
                                                         default=None)


def adresse_norm(a: str) -> str:
    """Adresse klein und ohne Anzeigenamen ("Name <a@b>" → "a@b")."""
    a = str(a or "").strip().lower()
    if "<" in a and ">" in a:
        a = a[a.rfind("<") + 1:a.rfind(">")].strip()
    return a


def lauf_fuer(regel: dict, n, eigene_adresse: str) -> Lauf:
    """Den ``Lauf`` fuer eine Regel und eine eingegangene Nachricht bauen.

    Die Beteiligten sind die Adressen der eingegangenen Nachricht; die
    weiteren Bereiche ALLES ausser "mail" (siehe Modulkopf, Massnahme 2).
    """
    beteiligte = [getattr(n, "von", "")] + list(getattr(n, "an", None) or []) \
        + list(getattr(n, "cc", None) or [])
    return Lauf(
        regel=str(regel.get("name") or ""), mail_id=str(getattr(n, "id", "") or ""),
        eigene_adresse=str(eigene_adresse or ""),
        beteiligte=frozenset(adresse_norm(a) for a in beteiligte if adresse_norm(a)),
        weitere_bereiche=tuple(b for b in (regel.get("bereiche") or ["mail"])
                               if b != "mail"))


def aktiv() -> bool:
    return lauf_cv.get() is not None


def versand_pruefen(empfaenger, texte=(), anhaenge: int = 0,
                    cfg: dict | None = None) -> list[str]:
    """Gruende, warum dieser Versand nur als ENTWURF abgelegt werden darf.

    Leere Liste = darf gesendet werden. Ausserhalb eines Regel-Laufs immer leer.
    ``texte``: alles, was in die Mail geht (Betreff, Text, Zitat einer
    FREMDEN Nachricht). ``anhaenge``: Zahl der Anhaenge, die nicht von der
    eingegangenen Nachricht selbst stammen.
    """
    l = lauf_cv.get()
    if l is None:
        return []
    c = _cfg() if cfg is None else cfg
    doms = versand_domaenen(l.eigene_adresse, c)
    empf = [adresse_norm(a) for a in (empfaenger or []) if adresse_norm(a)]
    extern = [a for a in empf if not domaene_erlaubt(a, doms)]

    gruende = inhalt_befunde("\n".join(str(t or "") for t in texte), sperrbegriffe(c))
    if extern:
        if l.weitere_bereiche:
            gruende.append("die Regel kann Firmenwissen lesen (%s) – an externe "
                           "Empfänger geht deshalb nur ein Entwurf"
                           % ", ".join(l.weitere_bereiche))
        unbeteiligt = [a for a in extern if a not in l.beteiligte]
        if unbeteiligt:
            gruende.append("externe Empfänger, die am Gespräch nicht beteiligt sind: %s"
                           % ", ".join(unbeteiligt[:5]))
        if anhaenge:
            gruende.append("%d Anhang/Anhänge an externe Empfänger" % anhaenge)
    if gruende:
        print("[Mail-Schutz] Regel '%s': Versand an %s nur als Entwurf – %s"
              % (l.regel, ", ".join(empf) or "-", "; ".join(gruende)), flush=True)
    return gruende


def entwurf_vermerk(gruende: list[str]) -> str:
    """Zusatz zum Werkzeugergebnis: was geschah und warum (fuer Modell und Protokoll)."""
    return (" ⚠ NICHT GESENDET – als Entwurf abgelegt (Schutz vor Datenabfluss): %s. "
            "Der Postfach-Inhaber prüft den Entwurf und sendet selbst; versuche "
            "nicht, den Versand auf anderem Weg zu wiederholen." % "; ".join(gruende))
