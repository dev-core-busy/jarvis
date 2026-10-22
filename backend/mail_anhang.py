"""Dateien aus dem Chat als E-Mail-Anhang: Aufloesen und Eigentuemer-Schranke.

WARUM ES DIESES MODUL GIBT
--------------------------
Bis 2026-10-22 konnte ``email_senden`` nur Nur-Text versenden. Gemeldet wurde
woertlich: "Das verfuegbare E-Mail-Tool (email_senden) unterstuetzt keine
Anhaenge". Gewuenscht sind zwei Dinge: ein Chat-ANHANG (PDF, Tabelle, Bild) und
ein im Chat ANGEZEIGTES Bild (erzeugt oder als Ergebnis ausgeliefert) sollen als
Anhang hinausgehen koennen.

Das Modell nennt eine Datei auf vier verschiedene Arten, und jede zeigt auf
einen anderen Ort:

* ``/tmp/jarvis-anhaenge/<kennung>/anhang_<12 Hex>_<name>`` – Arbeitskopie eines
  Chat-Anhangs (aus dem Anhang-Hinweis, ``main._anhang_ablegen``).
* ``data/documents/<name>`` oder nur ``<name>`` – die dauerhafte Ablage desselben
  Anhangs (``_anhang_erinnerung`` nennt sie so, wenn die Kopie abgelaufen ist).
* ``/api/documents/<32 Hex>__<name>`` bzw. ``/api/chat/attachment/<name>`` – eine
  im Chat ausgelieferte Datei bzw. ein hochgeladenes Bild.
* ``/api/generated/<32 Hex>.<endung>`` – ein erzeugtes oder gesuchtes Bild.
* ``/tmp/<name>`` – eine Ergebnisdatei des Laufs (Modell-Pfad, im Lauf
  uebersetzt nach ``/tmp/jarvis-arbeit/<kennung>/``).

⚠ EINE AUSGELIEFERTE ERGEBNISDATEI HAT IHREN /tmp-PFAD VERLOREN. ``_deliver_docs``
kopiert sie nach ``data/documents/<32 Hex>__<name>`` und LOESCHT die Quelle; der
Download-Chip geht nur an die Oberflaeche, nicht in den Verlauf des Modells. In
der Folgefrage ("schick mir das Diagramm per Mail") nennt das Modell also den
alten Pfad, den es nicht mehr gibt. Deshalb sucht ``_ausgeliefert`` zu einem
nicht vorhandenen Pfad die ausgelieferte Fassung ueber ihren Anzeigenamen – aber
nur unter den Dateien DIESES Benutzers.

DIE SCHRANKE: NUR EIGENE DATEIEN AUS DEM CHAT
---------------------------------------------
Ein Mailanhang ist ein Weg nach aussen. Er darf deshalb nicht weiter reichen als
der Download-Chip im Chat: Wissensordner, Freigaben, ``/mnt`` oder fremde
Arbeitsverzeichnisse sind KEINE Anhangquelle, auch wenn ``authorize_fs`` sie
zum Lesen erlaubt – sonst waere "haeng die Preisliste aus dem Wissen an" ein Weg,
Wissen per Mail aus dem Haus zu tragen, den es vorher nicht gab.

OHNE MENSCHEN NUR UNERRATBARE NAMEN
-----------------------------------
In einem Lauf ohne Oberflaeche (E-Mail-Regel, Cron, Telegram …) steht Fremdtext
im Prompt, und niemand sieht die Aktion vorher. Ein eingeschmuggelter Satz
"haeng data/documents/Angebot.pdf an" waere mit dem Klarnamen eines Uploads
erfolgreich. Dort gelten deshalb nur Verweise, deren Name nicht zu raten ist
(32-Hex-Capability, 12-Hex-Arbeitskopie, erzeugtes Bild). Der Preis: ein
Cron-Auftrag kann eine Datei, die er im selben Lauf unter ``/tmp`` erzeugt hat,
nicht anhaengen. Unterschieden wird ueber ``wirkung.kanal_cv`` – dieselbe Stelle,
an der die Bestaetigungskarte (BSI H9) entscheidet, ob ein Mensch zusieht.

Dieses Modul importiert weder ``exchangelib`` noch ``fastapi`` – pruefbar ohne
Postfach (``tests/test_mail_anhang.py``).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from backend import documents, lauf_tmp, sandbox
from backend.mail_client import MailFehler

GEN_DIR = Path(__file__).resolve().parent.parent / "data" / "generated_images"

MAX_ANZAHL = 10
_RE_CAP = re.compile(r"^[0-9a-f]{32}__(.+)$")
_RE_GEN = re.compile(r"^[0-9a-f]{32}\.(?:png|jpe?g|gif|webp)$")
_RE_ANHANG = re.compile(r"^anhang_[0-9a-f]{12}_(.+)$")
# Markdown-Verweis `![titel](adresse)` oder `[titel](adresse)`: das Modell kopiert
# die Adresse gern samt Klammer aus dem Verlauf.
_RE_MD = re.compile(r"^!?\[[^\]]*\]\(([^)\s]+)\)$")
_UML = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue",
                      "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def max_bytes() -> int:
    """Obergrenze aller Anhaenge einer Mail in Bytes (``JARVIS_MAIL_ANHANG_MAX_MB``).

    Vorgabe 20 MB: Exchange lehnt in der Werkseinstellung Nachrichten ab etwa
    25 MB ab, und base64 vergroessert um ein Drittel. Eine FUNKTION, damit eine
    geaenderte Umgebung ohne Neustart des Moduls greift. Deckel 150 MB.
    """
    try:
        mb = float(os.environ.get("JARVIS_MAIL_ANHANG_MAX_MB", "20"))
    except Exception:  # noqa: BLE001
        mb = 20.0
    mb = 20.0 if mb <= 0 else min(mb, 150.0)
    return int(mb * 1024 * 1024)


def mit_mensch() -> bool:
    """Sieht ein Mensch diesen Lauf (Chat mit Oberflaeche)?"""
    try:
        from backend import wirkung
        return wirkung.kanal_cv.get() is not None
    except Exception:  # noqa: BLE001
        return False


def liste(roh) -> list[str]:
    """Argument tolerant in eine Liste von Verweisen wandeln.

    Modelle liefern mal eine Liste, mal eine Zeichenkette mit Kommas oder
    Zeilenumbruechen. Ein String wird NIE zeichenweise durchlaufen (Register:
    "ueber einen String zu iterieren ist immer erlaubt und nie gemeint").
    """
    if roh is None or roh == "":
        return []
    if isinstance(roh, str):
        teile = re.split(r"[\n,;]", roh)
    elif isinstance(roh, (list, tuple)):
        teile = []
        for t in roh:
            if isinstance(t, dict):
                t = t.get("pfad") or t.get("path") or t.get("url") or ""
            teile.append(str(t or ""))
    else:
        teile = [str(roh)]
    return [t.strip().strip("`'\"") for t in teile if t and t.strip()]


def _anzeigename(p: Path) -> str:
    """Dateiname, unter dem der Empfaenger den Anhang sieht – ohne interne Praefixe."""
    name = p.name
    for muster in (_RE_CAP, _RE_ANHANG):
        m = muster.match(name)
        if m:
            return m.group(1)
    return name


def _namensschluessel(name: str) -> str:
    """Anzeigename so normiert, wie ``_deliver_docs`` ihn beim Ausliefern baut."""
    stamm, endung = os.path.splitext(os.path.basename(name or ""))
    stamm = re.sub(r"[^A-Za-z0-9_\- ]+", "", stamm.translate(_UML)).strip().replace(" ", "_")
    endung = re.sub(r"[^A-Za-z0-9]+", "", endung)[:8]
    return f"{stamm}.{endung}".lower() if stamm and endung else ""


def _ausgeliefert(name: str, benutzer: str) -> Path | None:
    """Juengste ausgelieferte Datei DIESES Benutzers mit diesem Anzeigenamen."""
    schluessel = _namensschluessel(name)
    if not schluessel:
        return None
    treffer = []
    try:
        for p in documents.DOCS_DIR.iterdir():
            m = _RE_CAP.match(p.name)
            if not m or m.group(1).lower() != schluessel:
                continue
            if p.is_file() and documents.may_access(p.name, benutzer, is_admin=False):
                treffer.append(p)
    except OSError:
        return None
    if not treffer:
        return None
    return max(treffer, key=lambda q: q.stat().st_mtime)


def _in(rp: Path, wurzel: Path) -> bool:
    try:
        rp.relative_to(wurzel.resolve())
        return True
    except (ValueError, OSError):
        return False


def aufloesen(verweis: str, benutzer: str, mensch: bool) -> tuple[Path, str]:
    """Einen Verweis in ``(datei, anzeigename)`` aufloesen oder ``MailFehler`` werfen.

    Die Meldung nennt den Grund UND den Weg, damit das Modell nicht Varianten
    desselben Zugriffs durchprobiert (Register: "ein richtiger Ablehnungsgrund
    kann nutzlos sein").
    """
    roh = (verweis or "").strip()
    m = _RE_MD.match(roh)
    if m:
        roh = m.group(1)
    if roh.startswith(("http://", "https://")):
        # Nur die eigene Adresse ergibt Sinn; der Pfad entscheidet, nicht der Host.
        roh = urlsplit(roh).path
    roh = unquote(roh.split("?", 1)[0].split("#", 1)[0]).strip()
    if not roh:
        raise MailFehler("Leerer Anhang-Verweis.", "eingabe")

    docs = documents.DOCS_DIR
    kandidat: Path | None = None
    art = ""
    if roh.startswith("/api/generated/"):
        name = os.path.basename(roh)
        if not _RE_GEN.match(name):
            raise MailFehler("'%s' ist keine gueltige Bildadresse." % verweis, "eingabe")
        kandidat, art = GEN_DIR / name, "erzeugt"
    elif roh.startswith(("/api/documents/", "/api/chat/attachment/")):
        kandidat, art = docs / os.path.basename(roh), "ablage"
    elif roh.startswith("data/documents/") or roh.startswith(str(docs) + "/"):
        kandidat, art = docs / os.path.basename(roh), "ablage"
    elif "/" not in roh and "\\" not in roh:
        kandidat, art = docs / roh, "ablage"
    elif roh.startswith("/tmp"):
        kandidat, art = Path(lauf_tmp.aufloesen(roh)), "tmp"
    else:
        raise MailFehler(
            "'%s' kann nicht angehaengt werden: als Anhang gehen nur Dateien aus "
            "diesem Chat (Anhaenge, angezeigte Bilder, gelieferte Ergebnisse) – "
            "keine Dateien aus Wissensordnern oder Freigaben." % verweis, "eingabe")

    # ".." und Symlinks: entschieden wird am AUFGELOESTEN Pfad.
    try:
        rp = kandidat.resolve()
    except OSError:
        rp = kandidat

    if art == "ablage" and not _in(rp, docs):
        raise MailFehler("'%s' liegt nicht in der Dokumentablage." % verweis, "eingabe")
    if art == "erzeugt" and not _in(rp, GEN_DIR):
        raise MailFehler("'%s' ist keine gueltige Bildadresse." % verweis, "eingabe")

    if not rp.is_file() and art in ("ablage", "tmp"):
        # Ausgeliefert und dabei aus /tmp weggezogen? Nur MIT Menschen: der
        # Anzeigename ist erratbar.
        if mensch:
            ersatz = _ausgeliefert(rp.name, benutzer)
            if ersatz is not None:
                rp, art = ersatz.resolve(), "ablage"
    if not rp.is_file():
        raise MailFehler(
            "Die Datei '%s' gibt es nicht (mehr). Eine Arbeitskopie verfaellt nach "
            "einigen Stunden; die Download-Adresse aus dem Chat (/api/documents/…) "
            "oder der Name in data/documents bleibt gueltig." % verweis, "eingabe")
    if sandbox.is_sensitive(rp):
        raise MailFehler("'%s' ist eine geschuetzte Datei." % verweis, "eingabe")

    if art == "erzeugt":
        return rp, rp.name

    if _in(rp, docs):
        if rp.parent != docs.resolve():
            raise MailFehler("'%s' liegt nicht in der Dokumentablage." % verweis, "eingabe")
        # Eigentuemer, auch fuer Administratoren (is_admin=False): als Anhang
        # geht nur, was der Benutzer selbst hochgeladen oder bekommen hat.
        if not documents.may_access(rp.name, benutzer, is_admin=False):
            raise MailFehler("Die Datei '%s' gehoert nicht zu deinen Dateien." % verweis,
                             "eingabe")
        if not mensch and not documents.is_capability(rp.name):
            raise MailFehler(
                "'%s' kann in einem Lauf ohne Oberflaeche nicht angehaengt werden: "
                "der Name ist erratbar. Erlaubt sind dort nur Download-Adressen "
                "(/api/documents/…) und Anhang-Arbeitskopien." % verweis, "eingabe")
        return rp, _anzeigename(rp)

    if _in(rp, lauf_tmp.ANH_ROOT):
        if lauf_tmp.gehoert_anhang(rp, benutzer) is not True:
            raise MailFehler("Dieser Anhang gehoert einem anderen Benutzer.", "eingabe")
        return rp, _anzeigename(rp)

    if _in(rp, lauf_tmp.ARBEIT_ROOT):
        if lauf_tmp.gehoert_arbeitsbereich(rp, benutzer) is not True:
            raise MailFehler("Diese Datei gehoert einem anderen Benutzer.", "eingabe")
        if not mensch:
            raise MailFehler(
                "'%s' kann in einem Lauf ohne Oberflaeche nicht angehaengt werden: "
                "der Name ist erratbar." % verweis, "eingabe")
        return rp, _anzeigename(rp)

    # Echtes /tmp: nur fuer privilegierte Laeufe, die kein eigenes
    # Arbeitsverzeichnis haben (``lauf_tmp``: Administratoren arbeiten dort).
    # Ein Domain-Benutzer kommt hier nur mit einem Pfad an, der NICHT seiner
    # ist – im echten /tmp liegen die Dateien aller.
    if (art == "tmp" and mensch and not sandbox.tool_user()
            and lauf_tmp.aktueller_lauf() is None and _in(rp, lauf_tmp.TMP_ECHT)):
        return rp, _anzeigename(rp)
    raise MailFehler(
        "'%s' kann nicht angehaengt werden: als Anhang gehen nur deine eigenen "
        "Dateien aus diesem Chat." % verweis, "eingabe")


def laden(roh, benutzer: str, mensch: bool | None = None) -> list[tuple[str, bytes]]:
    """Alle Verweise aufloesen und lesen: ``[(anzeigename, inhalt), …]``.

    Alles oder nichts: scheitert EIN Anhang, geht die Mail nicht hinaus. Eine
    Mail mit stillschweigend fehlendem Anhang waere der teurere Fehler – der
    Empfaenger merkt es, der Absender nicht.
    """
    verweise = liste(roh)
    if not verweise:
        return []
    if not (benutzer or "").strip():
        raise MailFehler("Ohne bekannten Benutzer koennen keine Anhaenge zugeordnet "
                         "werden.", "eingabe")
    if len(verweise) > MAX_ANZAHL:
        raise MailFehler("Hoechstens %d Anhaenge je Mail (genannt: %d)."
                         % (MAX_ANZAHL, len(verweise)), "eingabe")
    if mensch is None:
        mensch = mit_mensch()
    deckel = max_bytes()
    gesamt = 0
    ergebnis: list[tuple[str, bytes]] = []
    gesehen = set()
    for v in verweise:
        pfad, name = aufloesen(v, benutzer, mensch)
        if pfad in gesehen:
            continue
        gesehen.add(pfad)
        gesamt += pfad.stat().st_size
        if gesamt > deckel:
            raise MailFehler(
                "Die Anhaenge sind zusammen groesser als %d MB – so grosse Mails "
                "lehnt der Mailserver ab." % (deckel // (1024 * 1024)), "eingabe")
        ergebnis.append((name, pfad.read_bytes()))
    return ergebnis


def vermerk(anhaenge: list[tuple[str, bytes]]) -> str:
    """Kurzer Zusatz fuer die Erfolgsmeldung: welche Dateien hingen an."""
    if not anhaenge:
        return ""
    return " Anhang: %s." % ", ".join(n for n, _ in anhaenge)
