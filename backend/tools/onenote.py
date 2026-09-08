"""Text aus OneNote-Abschnittsdateien (``*.one``) – ueber Apache Tika.

WARUM TIKA UND NICHT PYTHON
---------------------------
``.one`` ist das binaere MS-ONESTORE-Format. Gemessen am 2026-09-03 an sechs
echten Notizbuchdateien (OneNote 2007 bis Office 365):

* **Apache Tika** hat einen vollstaendigen ONESTORE-Parser (eigenes Modul,
  ~60 Klassen) und gibt die Seiteninhalte aus ``RichEditTextUnicode`` heraus –
  alle sechs Dateien mit rc=0, inklusive chinesischer Notizen.
* **Der Java-freie Weg ist AUSGESCHLOSSEN, nicht nur unschoen.** ``strings -e l``
  findet den Text zwar teilweise, verliert aber Inhalt: "This is one note 2016"
  liefert Tika, ``strings`` findet es NICHT (1 gegen 0 Treffer) – und produziert
  zugleich Rauschen (in einer Datei 30 von 63 Zeilen Schriftnamen, interne
  Marker, XML-IDs). Ein Extraktor, der still Inhalt verliert, ist die
  schlechteste Variante.
* ``pyOneNote`` ist Version 0.0.2 und beschreibt seinen Zweck selbst als
  Extraktion **eingebetteter Dateien** fuer die Sicherheitsanalyse, nicht als
  Textextraktion.

WAS DABEI HERAUSKOMMT – UND WAS NICHT
-------------------------------------
Gemessen, damit niemand mehr erwartet, als da ist:

* **Keine Seitenstruktur.** Tika liefert eine flache Absatzliste, kein Element
  je Seite. Ein Abschnitt mit 30 Seiten wird EIN Textklumpen; die Chunk-Grenzen
  liegen quer ueber Seitenuebergaenge.
* **Die Reihenfolge ist nicht die Seitenreihenfolge**, sondern die des
  Revisionsbaums.
* **Dubletten aus Revisionen: 14 % bis 56 % der Zeilen** (gemessen: 261 Zeilen,
  117 eindeutig). Bekanntes Tika-Thema – dort gibt es sogar eine Testdatei
  ``test-tika-3970-dupetext.one``.
* **Binaerreste.** Der Baumlaeufer gibt auch Eigenschaftsmengen heraus, die
  keinen Text enthalten (ICC-Profile, XMP-Bloecke, komprimierte Fragmente).
* Bilder liefern **den Text, den OneNote selbst darin erkannt hat** – OneNote
  speichert seine eigene Bilderkennung in der Datei. **Tesseract ist dafuer
  NICHT beteiligt**, nachgewiesen: derselbe Aufruf mit und ohne ``tesseract``
  im PATH ergibt byte-identische Ausgabe. Die Laufzeit ist damit vorhersagbar,
  die Qualitaet dieser Textfragmente aber schwankend (Menuebaender von
  Bildschirmfotos erscheinen als Buchstabensalat).

Deshalb ist ``saeubern()`` kein Feinschliff, sondern Teil der Extraktion.

``.onetoc2`` wird BEWUSST nicht unterstuetzt: das ist der Notizbuch-Index ohne
eigenen Inhalt, und Tika hat dafuer keinen Parser (im Quelltext als "TODO - add
onetoc" vermerkt). Eine Endung anzunehmen, fuer die es keinen Parser gibt,
waere eine Zusage, die der naechste Schritt kassiert.
"""

import html
import os
import re
import selectors
import shutil
import signal
import subprocess
import threading
import time
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Die Datei ist 65 MB und gehoert damit NICHT in ein oeffentliches Repo –
# ``deploy/tika_setup.sh`` legt sie ab. Reihenfolge: ausdrueckliche Angabe des
# Betreibers zuerst, dann der Ort des Setup-Skripts, dann die ueblichen
# Systempfade.
_TIKA_KANDIDATEN = (
    "vendor/tika-app.jar",
    "/opt/jarvis/vendor/tika-app.jar",
    "/usr/share/java/tika-app.jar",
)
_TIKA_GLOBS = ("vendor/tika-app-*.jar", "/usr/share/java/tika-app-*.jar")

_JAVA_KANDIDATEN = ("java", "/usr/bin/java", "/usr/lib/jvm/default-java/bin/java")


def stille_deckel() -> int:
    """Sekunden OHNE JEDE AUSGABE, nach denen ein Lauf als haengend gilt.

    ⚠ DIESER WERT HAT DEN FESTEN GESAMTDECKEL ABGELOEST, und der Grund ist
    gemessen, nicht geschaetzt: die alte Begruendung ("die Laufzeit haengt an
    der DATEIGROESSE") ist WIDERLEGT. An der 46,5-MB-Datei von ECHT nachgemessen
    (2026-09-07): 281 s Gesamtlaufzeit, davon 277 s Tesseract-OCR eingebetteter
    Bildschirmfotos – dieselbe Datei ohne OCR braucht 4 s. Die Laufzeit haengt
    an der Zahl eingebetteter BILDER, nicht an der Dateigroesse. Ein fester
    Deckel schneidet damit ausgerechnet die inhaltsreichen Dateien ab: 86 % des
    Textes jener Datei (7363 von 8508 Zeilen) stammen aus genau dieser OCR.

    DER FORTSCHRITT LIEGT DIE GANZE ZEIT MESSBAR AUF STDOUT. Ueber denselben
    Lauf gemessen: 74 Ausgaben, laengste Pause **13,9 s** (p95 9,2 s, Median
    3,9 s). Der Prozess verstummt also nie laenger als 14 s, waehrend er 280 s
    arbeitet – der alte Deckel hat einen Extraktor abgeschnitten, der im
    Sekundentakt Text lieferte.

    120 s ist bewusst DERSELBE Zahlenwert wie der fruehere Gesamtdeckel, nur mit
    der richtigen Bezugsgroesse. Das laesst der laengsten gemessenen Pause das
    8,6-fache an Luft – Reserve fuer eine langsamere Maschine, ein einzelnes
    sehr grosses eingebettetes Bild und Last durch parallele Laeufe – und
    schlaegt trotzdem zu, wenn ein Prozess wirklich haengt.
    """
    try:
        wert = int(os.environ.get("JARVIS_ONENOTE_STILLE", "120"))
    except (TypeError, ValueError):
        return 120
    return max(10, min(wert, 3600))


def zeitdeckel() -> int:
    """HARTE Obergrenze je Datei – die Notbremse HINTER dem Stille-Waechter.

    Sie faengt nur noch den pathologischen Fall: einen Prozess, der zwar stetig
    ausgibt, aber nie fertig wird (beschaedigter Revisionsbaum, Endlosschleife
    im Parser). Ueber den Normalfall entscheidet `stille_deckel()`.

    Vorgabe 3600 s statt der frueheren 120: mit dem Waechter davor darf sie
    grosszuegig sein, und ein zu knapper Wert war genau der Fehler, der eine
    46-MB-Datei mit 284 Chunks SAP-Anleitungswissen aus dem Index gehalten hat.
    FUNKTION, keine Modulkonstante – ein beim Import gelesener Wert waere bis
    zum Dienstneustart nicht aenderbar.
    """
    try:
        wert = int(os.environ.get("JARVIS_ONENOTE_TIMEOUT", "3600"))
    except (TypeError, ValueError):
        return 3600
    return max(60, min(wert, 86400))


def jvm_heap() -> str:
    """Obergrenze fuer den JVM-Heap.

    Gedeckelt, weil der Reindex auf der Produktions-VM ohnehin nah an der
    Speichergrenze laeuft (historisch dreimal OOM) – eine JVM ohne Deckel nimmt
    sich standardmaessig ein Viertel des Hauptspeichers. 512 MB haben in der
    Messung fuer alle Dateien gereicht, auch fuer die 1,2-MB-Datei.
    """
    wert = str(os.environ.get("JARVIS_ONENOTE_HEAP", "512m")).strip()
    return wert if re.fullmatch(r"\d+[kKmMgG]", wert) else "512m"


def finde_java() -> str | None:
    """Pfad zur Java-Laufzeit; None = nicht installiert."""
    for k in _JAVA_KANDIDATEN:
        if k.startswith("/"):
            if Path(k).is_file():
                return k
        else:
            gefunden = shutil.which(k)
            if gefunden:
                return gefunden
    heim = os.environ.get("JAVA_HOME", "").strip()
    if heim:
        kandidat = Path(heim) / "bin" / "java"
        if kandidat.is_file():
            return str(kandidat)
    return None


def finde_tika() -> Path | None:
    """Pfad zur tika-app.jar; None = nicht abgelegt.

    ``JARVIS_TIKA_JAR`` sticht alle Kandidaten – ein Betreiber, der die Datei
    woanders vorhaelt, muss nicht das Repo anfassen.
    """
    gesetzt = os.environ.get("JARVIS_TIKA_JAR", "").strip()
    if gesetzt:
        p = Path(gesetzt)
        return p if p.is_file() else None
    for k in _TIKA_KANDIDATEN:
        p = Path(k) if k.startswith("/") else PROJECT_ROOT / k
        if p.is_file():
            return p
    for muster in _TIKA_GLOBS:
        if muster.startswith("/"):
            treffer = sorted(Path(muster).parent.glob(Path(muster).name))
        else:
            treffer = sorted(PROJECT_ROOT.glob(muster))
        # Juengste Version zuletzt sortiert -> die nehmen.
        for p in reversed(treffer):
            if p.is_file():
                return p
    return None


def fehlender_baustein() -> str:
    """Klartext-Auskunft, WAS fehlt und was gerade dagegen laeuft – oder "".

    ⚠ DIESER TEXT FORDERT NICHT ZUR HANDARBEIT AUF. Die Einrichtung laeuft
    automatisch: beim Broker-Start (``start_jarvis_root.sh`` Schritt 6e), beim
    Backend-Start (``startup_onenote_tika``) und bei Bedarf, sobald eine
    ``.one``-Datei gelesen werden soll (``text_aus_datei`` stoesst sie an).
    Ein Hinweis, auf den ein Administrator zufaellig stossen muss, damit
    ueberhaupt etwas passiert, ist keine Loesung – er ist die Beschreibung
    eines liegengebliebenen Problems.

    Der Handweg steht deshalb nur noch dort, wo die Automatik NICHT greifen
    kann: wenn sie abgeschaltet ist (``JARVIS_TIKA_AUTO=0``) oder wenn es
    keinen Weg zu Root-Rechten gibt (kein Broker und Backend unprivilegiert).
    """
    fehlt = []
    if not finde_java():
        fehlt.append("Java")
    if not finde_tika():
        fehlt.append("Apache Tika (tika-app.jar)")
    if not fehlt:
        return ""
    kopf = ("OneNote-Datei noch nicht lesbar – auf diesem Server fehlt: "
            + " und ".join(fehlt) + ". ")

    if einrichtung_laeuft():
        return kopf + ("Die Einrichtung laeuft gerade automatisch (laedt eine "
                       "Java-Laufzeit und ~65 MB Apache Tika). Danach wird die "
                       "Datei beim naechsten Indizierungslauf gelesen – es ist "
                       "nichts zu tun.")
    if not automatik_an():
        return kopf + ("Die automatische Einrichtung ist abgeschaltet "
                       "(JARVIS_TIKA_AUTO=0). Entweder JARVIS_TIKA_JAR auf eine "
                       "vorhandene tika-app.jar setzen oder einmalig "
                       "'sudo bash deploy/tika_setup.sh' ausfuehren.")
    fehler = letzter_einrichtungsfehler()
    if fehler:
        return kopf + ("Die automatische Einrichtung ist fehlgeschlagen: "
                       + fehler + " Sie wird wiederholt; besteht das Problem "
                       "fort, fehlt in aller Regel der Netzzugang zu "
                       "repo1.maven.org (dann JARVIS_TIKA_JAR auf eine von Hand "
                       "abgelegte tika-app.jar setzen).")
    return kopf + ("Die Einrichtung wird automatisch angestossen; danach ist "
                   "die Datei beim naechsten Indizierungslauf lesbar.")


# ─── Automatische Einrichtung ────────────────────────────────────────────────
#
# WARUM DAS HIER STEHT UND NICHT NUR IM BOOTSTRAP: Schritt 6e in
# start_jarvis_root.sh laeuft beim BROKER-START. Wer heute ein Notizbuch in
# einen Wissensordner legt, wartet damit auf den naechsten Neustart – und in
# der Zwischenzeit liegt die Datei unlesbar da. Ausdrueckliche Vorgabe des
# Betreibers (2026-09-04): die Einrichtung passiert von selbst, ein
# Administrator soll nichts abtippen muessen.

_SPERRE = threading.Lock()
_zustand: dict = {"laeuft": False, "letzter_start": 0.0,
                  "letzter_fehler": "", "versuche": 0}

# Mindestabstand zwischen zwei Versuchen. Ohne ihn stiesse JEDE unlesbare
# .one-Datei eines Indizierungslaufs einen eigenen apt-Lauf an – bei 40 Dateien
# waeren das 40 Versuche gegen dieselbe (womoeglich tote) Paketquelle.
WIEDERHOLUNG_S = 1800


def automatik_an() -> bool:
    """FUNKTION, keine Modulkonstante – ein beim Import gelesener Wert waere
    bis zum Dienstneustart eingefroren (Register)."""
    return str(os.environ.get("JARVIS_TIKA_AUTO", "1")).strip() != "0"


def einrichtung_laeuft() -> bool:
    with _SPERRE:
        return bool(_zustand["laeuft"])


def letzter_einrichtungsfehler() -> str:
    with _SPERRE:
        return str(_zustand["letzter_fehler"])


def einrichtung_zustand() -> dict:
    with _SPERRE:
        return dict(_zustand)


def einrichtung_anstossen(ausloeser: str = "") -> str:
    """Einrichtung im HINTERGRUND anstossen. Rueckgabe: was passiert ist.

    Idempotent und fail-safe: bereits eingerichtet, Automatik aus, ein Lauf
    laeuft schon, oder der letzte Versuch ist keine 30 Minuten her → es
    passiert nichts, und die Rueckgabe sagt warum. Es wird NIE gewartet – der
    Aufrufer (Indexer, Startup, Werkzeug) laeuft weiter.
    """
    if finde_java() and finde_tika():
        return "bereits eingerichtet"
    if not automatik_an():
        return "Automatik abgeschaltet (JARVIS_TIKA_AUTO=0)"
    jetzt = time.time()
    with _SPERRE:
        if _zustand["laeuft"]:
            return "laeuft bereits"
        if _zustand["letzter_start"] and jetzt - _zustand["letzter_start"] < WIEDERHOLUNG_S:
            rest = int(WIEDERHOLUNG_S - (jetzt - _zustand["letzter_start"]))
            return f"letzter Versuch zu jung (naechster in {rest} s)"
        _zustand["laeuft"] = True
        _zustand["letzter_start"] = jetzt
        _zustand["versuche"] += 1
    t = threading.Thread(target=_einrichten, args=(ausloeser,),
                         name="tika-setup", daemon=True)
    t.start()
    return "angestossen"


def _einrichten(ausloeser: str) -> None:
    """Laeuft im Hintergrund-Thread. Darf unter keinen Umstaenden werfen."""
    grund = f" (Ausloeser: {ausloeser})" if ausloeser else ""
    fehler = ""
    try:
        print(f"[OneNote/Tika] Richte ein{grund} – Java-Laufzeit und ~65 MB "
              f"Apache Tika werden geladen. Das kann einige Minuten dauern.",
              flush=True)
        from backend import broker_client
        modus = broker_client.mode()
        if modus == "none":
            # Kein Broker und keine Root-Rechte: hier endet die Automatik, und
            # das muss im Klartext dastehen statt still zu scheitern.
            fehler = ("kein Weg zu Root-Rechten (Broker-Socket fehlt und das "
                      "Backend laeuft unprivilegiert) – einmalig "
                      "'sudo bash deploy/tika_setup.sh' ausfuehren oder den "
                      "Root-Broker einrichten.")
        else:
            res = broker_client.call_sync("tika_setup", {}, user="system",
                                          timeout=900)
            if res.get("ok") and int(res.get("rc") or 0) == 0:
                pass
            elif res.get("decision") == "pending":
                fehler = ("die Root-Freigabe steht aus – unter Sicherheit → "
                          "Root-Freigaben freigeben.")
            else:
                roh = (str(res.get("stderr") or "").strip()
                       or str(res.get("error") or "").strip()
                       or str(res.get("stdout") or "").strip())
                fehler = (roh.splitlines()[-1][:300] if roh
                          else f"rc={res.get('rc')}")
    except Exception as e:  # noqa: BLE001
        fehler = f"{type(e).__name__}: {e}"

    # Massgeblich ist der ZUSTAND auf Platte, nicht der Rueckgabewert des
    # Skripts: es kann teilweise gelaufen sein (Java da, jar nicht), und ein
    # rc=0 ohne vorhandene Datei waere eine Zusage, die nichts haelt.
    java, jar = finde_java(), finde_tika()
    if not fehler and not (java and jar):
        offen = " und ".join([n for n, v in (("Java", java),
                                             ("tika-app.jar", jar)) if not v])
        fehler = (f"das Setup-Skript meldete Erfolg, aber {offen} fehlt "
                  f"weiterhin auf Platte.")
    with _SPERRE:
        _zustand["laeuft"] = False
        _zustand["letzter_fehler"] = "" if (java and jar) else (fehler or "unbekannt")
    if java and jar:
        print(f"[OneNote/Tika] Bereit – .one-Dateien werden beim naechsten "
              f"Indizierungslauf gelesen (jar: {jar}).", flush=True)
    else:
        print(f"[OneNote/Tika] WARNUNG: Einrichtung fehlgeschlagen: "
              f"{fehler or 'unbekannt'}", flush=True)


# ─── Saeubern ────────────────────────────────────────────────────────────────

_ZEIT_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|am|pm|Uhr)?$")
# Ein "Wort" ist eine Buchstabenfolge ab drei Zeichen. ABSICHTLICH OHNE
# Vokal-Bedingung – das war der erste Entwurf, und die Messung hat ihn
# widerlegt: ueber sechs echte Dateien hinweg brachte die Vokal-Pruefung genau
# DREI zusaetzlich verworfene Muellzeilen, kostete dafuer aber jede Zeile, die
# nur aus einer vokallosen Abkuerzung besteht ("SQL", "PDF", "GmbH", "XML",
# "CRM" – alle nachgemessen). Drei Muellzeilen gegen still verlorenes Wissen
# ist derselbe schlechte Handel, aus dem der ``strings``-Weg verworfen wurde.
_WORT_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
# CJK/Kana/Hangul. Seit die Vokal-Regel gefallen ist, deckt _WORT_RE lange
# CJK-Zeilen mit ab (die Zeichen sind Wortzeichen). NOETIG bleibt die Pruefung
# fuer KURZE Zeilen: _WORT_RE verlangt drei Zeichen, und im Chinesischen ist
# ein Wort oft zwei – "中文" waere sonst Rauschen.
_CJK_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")
_ZIFFER_RE = re.compile(r"\d")

# Technische Marken aus den Metadaten EINGEBETTETER BILDER. Sie stammen nie aus
# dem Notizbuchtext, sondern aus den Rohbytes, die der Baumlaeufer mit
# herausgibt (gemessen: ICC-Profil und ein kompletter XMP-Block in
# testOneNoteEmbeddedImage.one). Die Liste ist ABSICHTLICH auf die beobachteten
# Namensraeume begrenzt und nicht "jede Zeile, die mit < beginnt": in einem
# IT-Haus steht in einer Notiz durchaus einmal ein <soap:Envelope>, und das ist
# dann Inhalt. Preis dieser Regel: eine Seite, die ausgerechnet
# Bild-Metadaten-XML zitiert, verliert diese Zeilen.
_META_MARKER = re.compile(
    r"(ICC\s*Profile|<\s*/?\s*(?:x:xmpmeta|xmpmeta|rdf:|exif:|tiff:|photoshop:|xmp[A-Za-z]*:|dc:))",
    re.IGNORECASE)

# Bis zu dieser Laenge gilt die strenge Pruefung. Alles Laengere bleibt stehen:
# die gemessenen Binaerreste waren durchweg kurz (7–11 Zeichen), und eine lange
# Zeile faellt im Index kaum auf, waehrend ein Fehlurteil dort echten Inhalt
# kostet.
_STRENG_BIS = 40


def _ist_nutztext(zeile: str) -> bool:
    """Traegt die Zeile ueberhaupt Inhalt?

    Die Bewertung ist ABSICHTLICH schwach: sie soll Binaerreste wegnehmen, aber
    im Zweifel behalten. Fehlurteile in dieser Richtung kosten ein paar
    Muell-Token im Index; in der anderen Richtung kosten sie Wissen – und
    genau das ist der Grund, aus dem der ``strings``-Weg verworfen wurde.

    Was damit NICHT weggeht: kurze Binaerfragmente, die zufaellig drei
    Buchstaben am Stueck enthalten (gemessen drei Zeilen in einer von sechs
    Dateien). Das ist der bewusst gezahlte Preis.
    """
    if _META_MARKER.search(zeile):
        return False
    if len(zeile) > _STRENG_BIS:
        return True
    if _CJK_RE.search(zeile):
        return True
    if len(_ZIFFER_RE.findall(zeile)) >= 4:
        # Preise, Datumsangaben, Belegnummern.
        return True
    # Uebrig bleibt: eine Zeile ohne jede Buchstabenfolge ab drei Zeichen. Das
    # trifft die Binaerreste ("i\\ hE@RZ", "pM:3t Em") und die
    # Ein-/Zwei-Zeichen-Bruchstuecke aus der Bilderkennung ("o", "|", "<2",
    # "e ="), aber KEIN Wort irgendeiner Sprache.
    return bool(_WORT_RE.findall(zeile))


def _entschaerfen(zeile: str) -> str:
    """Nicht darstellbare Zeichen entfernen und Leerraum normieren.

    ``U+FFFD`` ist der haeufigste Fall: Tika haengt es an die Namen
    eingebetteter Objekte ("Untitled picture.png�"). Es ist KEIN
    Steuerzeichen – eine Pruefung ueber die Unicode-Kategorie C allein sieht es
    nicht (gemessen: ctrl=0 in jeder Zeile).
    """
    sauber = []
    for c in zeile:
        if c == "�":
            continue
        if c in ("\t", " "):
            sauber.append(" ")
            continue
        if unicodedata.category(c)[0] == "C":
            continue
        sauber.append(c)
    return re.sub(r"\s{2,}", " ", "".join(sauber)).strip()


# ══ Eingebettete XPS-Ausdrucke ("nach OneNote drucken") ═══════════════════
# ⚠ HIER LIEGT DER BESTE TEXT DER GANZEN DATEI – und er war bisher unbrauchbar.
# Gemessen am 2026-09-07 an der 46,5-MB-SAP-Anleitung von ECHT: 325 Zeilen der
# Form
#     <Glyphs RenderTransform="0.166693,0,0,0.167,0,0" Fill="#ff000000"
#             FontUri="/Documents/1/Resources/Fonts/C0E9….odttf"
#             UnicodeString="Die Angebotserstellung bei Maris beginnt mit …" />
# Das ist SAUBER GETIPPTER Fliesstext (kein OCR-Salat), verpackt in bis zu
# 837 Zeichen Glyphen-Geometrie. Ungeoeffnet trug ein Chunk rund 5 % Nutztext
# und 95 % GUIDs – das Embedding davon ist praktisch wertlos, und die Zeilen
# machten 40 % der gesamten Textmasse aus.
#
# ``UnicodeString`` IST laut XPS-Spezifikation der Textinhalt eines
# Glyphs-Elements. Das hier ist also keine Heuristik, sondern das Auspacken
# eines Formats – anders als eine geratene Rauschregel (siehe die verworfene
# Vokal-Regel im Kopf dieser Datei).
_XPS_TEXT_RE = re.compile(r'UnicodeString="([^"]*)"')
# Paketstruktur OHNE jeden Textgehalt: Beziehungen, Inhaltstypen, Paketstuecke.
# ⚠ ZWEI Bedingungen, nicht eine: das Element ALLEIN reicht nicht als Grund.
# Tika haengt Zeilen zusammen ("><Relationship …"), ein Anker am Zeilenanfang
# geht deshalb ins Leere - gemessen blieben so 139 Zeilen stehen. Umgekehrt
# waere "enthaelt <Relationship" zu breit fuer eine Notiz, die ueber OOXML
# schreibt. Verworfen wird nur, was BEIDES traegt: das Struktur-Element UND
# einen eindeutigen Paketmarker (XPS-Schema, obfuskierte Schrift, Inhaltstyp).
_XPS_ELEMENT_RE = re.compile(r'<(Relationship|Override|Default|Types|\?xml)\b')
_XPS_PAKET_RE = re.compile(
    r'schemas\.microsoft\.com/xps|schemas\.openxmlformats\.org/package'
    r'|\.odttf|\[Content_Types\]\.xml'
)
# Ein Paketstueck-Pfad ist fuer sich schon eindeutig: Tika nummeriert die
# Stuecke eines Pakets als "…/[0].piece".
_XPS_STUECK_RE = re.compile(r'\[\d+\]\.piece\s*$')


def _xps_auspacken(zeile: str) -> str | None:
    """Holt aus einer XPS-Glyphenzeile den Text – oder verwirft reine Struktur.

    Rueckgabe: der Text, "" fuer "verwerfen", oder None fuer "nicht zustaendig".
    Die Unterscheidung ist noetig, weil der Aufrufer nur im ersten Fall etwas
    ersetzt und sonst seinen bisherigen Weg geht.
    """
    if "<Glyphs" in zeile:
        stuecke = [html.unescape(t).strip() for t in _XPS_TEXT_RE.findall(zeile)]
        return " ".join(t for t in stuecke if t)
    if _XPS_STUECK_RE.search(zeile):
        return ""
    if _XPS_ELEMENT_RE.search(zeile) and _XPS_PAKET_RE.search(zeile):
        return ""
    return None


def saeubern(roh: str) -> tuple[str, dict]:
    """Rohtext von Tika in indizierbaren Text ueberfuehren.

    Reihenfolge ist Semantik: entschaerfen -> Zeitstempel -> Rauschen ->
    Dubletten. Zuerst zu deduplizieren waere falsch, weil zwei Zeilen erst nach
    dem Entschaerfen gleich AUSSEHEN.

    Die Dublettenpruefung ist GLOBAL, nicht nur auf Nachbarzeilen: gemessen
    stand "So good" auf Zeile 1 und Zeile 5. Preis dieser Entscheidung: eine
    absichtlich wiederholte kurze Zeile (etwa "OK" in einer Tabelle) erscheint
    nur einmal. Vertretbar – die Reihenfolge ist ohnehin nicht die der Seiten,
    eine Tabelle ist hier also nicht rekonstruierbar.
    """
    bilanz = {"zeilen": 0, "dubletten": 0, "rauschen": 0, "zeit": 0,
              "behalten": 0, "xps": 0}
    gesehen: set[str] = set()
    aus: list[str] = []
    for rohzeile in (roh or "").splitlines():
        zeile = _entschaerfen(rohzeile)
        if not zeile:
            continue
        bilanz["zeilen"] += 1
        # Eingebettete XPS-Ausdrucke auspacken, BEVOR Rauschfilter und
        # Dublettenpruefung greifen: eine 800-Zeichen-Glyphenzeile gilt sonst
        # als einzigartiger Nutztext und schleppt ihre GUIDs in den Index.
        _xps = _xps_auspacken(zeile)
        if _xps is not None:
            bilanz["xps"] = bilanz.get("xps", 0) + 1
            if not _xps:
                bilanz["rauschen"] += 1
                continue
            zeile = _xps
        if _ZEIT_RE.match(zeile):
            # Die reine Uhrzeit aus dem Seitenkopf sagt ohne ihre Seite nichts.
            bilanz["zeit"] += 1
            continue
        if not _ist_nutztext(zeile):
            bilanz["rauschen"] += 1
            continue
        if zeile in gesehen:
            bilanz["dubletten"] += 1
            continue
        gesehen.add(zeile)
        aus.append(zeile)
    bilanz["behalten"] = len(aus)
    return "\n".join(aus), bilanz


# ─── Extraktion ──────────────────────────────────────────────────────────────

def _fehlergrund(stderr: bytes, rc: int) -> str:
    """Aus Javas stderr die eine Zeile ziehen, die einem Menschen etwas sagt.

    Die LETZTE Zeile zu nehmen ist bei einem Java-Stacktrace die schlechteste
    Wahl – dort steht "at org.apache.tika.cli.TikaCLI.main(TikaCLI.java:249)".
    Gemessen an einer absichtlich beschaedigten Datei lautet die brauchbare
    Zeile: "org.apache.tika.exception.TikaException: Invalid OneStore document
    - could not parse headers". Genau die geht in die Fehlerliste des
    Indizierungslaufs, die ein Administrator liest.
    """
    zeilen = [z.strip() for z in (stderr or b"").decode("utf-8", "replace").splitlines()
              if z.strip()]
    for z in zeilen:
        if "Exception" in z or "Error" in z:
            # Javas Rahmen ("Exception in thread \"main\" ") und den Paketpfad
            # abstreifen – der Satz dahinter ist die Aussage.
            kern = re.sub(r'^Exception in thread\s+"[^"]*"\s*', "", z)
            kern = re.sub(r"^(?:[\w$]+\.)+([A-Za-z_$]*(?:Exception|Error))", r"\1", kern)
            return kern[:200]
    for z in zeilen:
        if not z.startswith(("INFO", "WARN", "DEBUG")):
            return z[:200]
    return f"Rueckgabewert {rc}"


def _abraeumen(proc) -> None:
    """Beendet die ganze PROZESSGRUPPE und schliesst die Pipes.

    ``proc.kill()`` allein laesst Kindprozesse als Waisen weiterlaufen
    (Register) – Tika startet fuer die OCR echte ``tesseract``-Prozesse.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass
    for pipe in (proc.stdout, proc.stderr):
        try:
            if pipe is not None:
                pipe.close()
        except OSError:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        pass


def _lies_stroemend(proc, stille_s: int, gesamt_s: int, melde=None):
    """Liest stdout/stderr STROEMEND und schlaegt zu, wenn der Prozess VERSTUMMT.

    Rueckgabe ``(stdout, stderr, abbruch, gelesen, dauer)``; ``abbruch`` ist
    None oder ``("stille"|"gesamt", gelaufene_sekunden)``.

    ⚠ WARUM NICHT ``communicate(timeout=...)``: das liest erst am Ende und kennt
    deshalb nur EINE Frage – "ist die Gesamtzeit um?". Ob der Prozess dabei
    arbeitet oder haengt, faellt unter den Tisch, obwohl der Unterschied die
    ganze Zeit auf stdout steht.

    ⚠ UND WARUM NICHT ``for line in proc.stdout``: das prueft keine Deadline und
    laeuft bei einem stillen Prozess ewig weiter (Register). ``select`` mit
    Zeitlimit kehrt auch dann zurueck, wenn NICHTS kommt – genau der Fall, um
    den es hier geht.

    Nebengewinn: beide Pipes werden fortlaufend geleert, ein voller Pipe-Puffer
    kann den Extraktor also gar nicht erst blockieren.
    """
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, "out")
    sel.register(proc.stderr, selectors.EVENT_READ, "err")
    teile: dict = {"out": [], "err": []}
    start = time.monotonic()
    letzte = start
    zuletzt_gemeldet = start
    gelesen = 0
    abbruch = None
    try:
        while sel.get_map():
            for key, _ in sel.select(timeout=1.0):
                try:
                    stueck = os.read(key.fileobj.fileno(), 65536)
                except OSError:
                    stueck = b""
                if not stueck:          # EOF auf dieser Pipe
                    sel.unregister(key.fileobj)
                    continue
                teile[key.data].append(stueck)
                if key.data == "out":
                    gelesen += len(stueck)
                # JEDE Ausgabe zaehlt als Lebenszeichen, auch die auf stderr:
                # gefragt ist "arbeitet er noch", nicht "liefert er Nutztext".
                letzte = time.monotonic()
            jetzt = time.monotonic()
            if jetzt - letzte > stille_s:
                abbruch = ("stille", jetzt - start)
                break
            if jetzt - start > gesamt_s:
                abbruch = ("gesamt", jetzt - start)
                break
            # Ohne Lebenszeichen nach aussen sieht ein Admin minutenlang eine
            # Anzeige, die sich nicht ruehrt, und haelt den Lauf fuer tot.
            if melde is not None and jetzt - zuletzt_gemeldet >= 5:
                zuletzt_gemeldet = jetzt
                try:
                    melde(gelesen, jetzt - start)
                except Exception:  # noqa: BLE001
                    pass
    finally:
        sel.close()
    return (b"".join(teile["out"]), b"".join(teile["err"]),
            abbruch, gelesen, time.monotonic() - start)


def text_aus_datei(pfad: Path, zeitlimit: int | None = None,
                   melde=None) -> tuple[str | None, str]:
    """Extrahiert Text aus einer ``.one``-Datei.

    Rueckgabe ``(text, grund)``: ``text`` ist None, wenn nichts herauskam –
    ``grund`` nennt dann im Klartext, warum. Der Aufrufer im Indexer braucht
    beides getrennt, weil er den Grund in die Fehlerliste des Laufs schreibt.
    """
    java = finde_java()
    jar = finde_tika()
    if not java or not jar:
        # BEDARFSGETRIEBEN EINRICHTEN, statt es nur zu melden: hier steht fest,
        # dass jemand wirklich ein Notizbuch indizieren will. Der Aufruf kehrt
        # SOFORT zurueck (Arbeit im Hintergrund-Thread, hoechstens ein Lauf,
        # Mindestabstand zwischen Versuchen) – dieser Indizierungslauf laeuft
        # also unveraendert weiter, der naechste findet die Datei lesbar vor.
        einrichtung_anstossen(f"Indizierung von {pfad.name}")
        return None, fehlender_baustein()

    limit = zeitlimit if zeitlimit is not None else zeitdeckel()
    cmd = [java, f"-Xmx{jvm_heap()}", "-Djava.awt.headless=true",
           "-jar", str(jar), "--text", "--encoding=UTF-8", str(pfad)]
    # HOME muss gesetzt sein: ohne das sucht die JVM ihre Ablage in /root und
    # scheitert als Dienstbenutzer. Dieselbe Falle wie bei den
    # sentence-transformers-Skripten.
    umgebung = dict(os.environ)
    umgebung.setdefault("HOME", "/tmp")
    umgebung["LC_ALL"] = umgebung.get("LC_ALL", "C.UTF-8")

    # start_new_session + killpg: bei einem Zeitueberschreiten muss die ganze
    # PROZESSGRUPPE fallen. ``proc.kill()`` allein laesst Kindprozesse als
    # Waisen zuruecklaufen (Register).
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=umgebung, start_new_session=True,
        )
    except OSError as e:
        return None, f"Java liess sich nicht starten: {e.strerror or e}"

    stille = stille_deckel()
    try:
        roh, fehler, abbruch, gelesen, gelaufen = _lies_stroemend(
            proc, stille, limit, melde)
    except Exception as e:  # noqa: BLE001
        _abraeumen(proc)
        return None, f"Aufruf fehlgeschlagen: {e}"

    if abbruch is not None:
        _abraeumen(proc)
        art, sek = abbruch
        kb = gelesen // 1024
        if art == "stille":
            # Der Grund nennt BEIDE Zahlen: wer 500 KB gelesen hat und dann
            # verstummt, hat ein anderes Problem als einer, der nie anfing.
            return None, (f"Der Extraktor hat {stille} s lang nichts mehr "
                          f"ausgegeben (nach {sek:.0f} s, {kb} KB gelesen) – "
                          f"Datei vermutlich beschaedigt "
                          f"(JARVIS_ONENOTE_STILLE aendert die Geduld)")
        return None, (f"Harte Obergrenze von {limit} s erreicht "
                      f"({kb} KB in {sek:.0f} s gelesen) – der Extraktor lieferte "
                      f"bis zuletzt Text, JARVIS_ONENOTE_TIMEOUT hebt die Grenze")

    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        # Beide Pipes stehen auf EOF, der Prozess endet aber nicht – ein Rest,
        # den nur die Prozessgruppe faengt.
        _abraeumen(proc)
        return None, (f"Der Extraktor lieferte seine Ausgabe, endete danach aber "
                      f"nicht ({gelesen // 1024} KB in {gelaufen:.0f} s)")

    if proc.returncode != 0:
        # Tika schreibt auch im Erfolgsfall Warnungen nach stderr – der
        # Rueckgabewert entscheidet, nicht ein nicht-leeres stderr.
        return None, f"Tika ist gescheitert: {_fehlergrund(fehler, proc.returncode)}"

    text, bilanz = saeubern((roh or b"").decode("utf-8", "replace"))
    if not text.strip():
        return None, ("Datei enthaelt keinen auslesbaren Text (leerer Abschnitt, "
                      "nur Handschrift oder nur Bilder ohne erkannten Text)")
    return text, (f"{bilanz['behalten']} von {bilanz['zeilen']} Zeilen behalten "
                  f"({bilanz['dubletten']} Dubletten, {bilanz['rauschen']} Rauschen, "
                  f"{bilanz['zeit']} Zeitstempel entfernt)")
