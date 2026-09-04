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

import os
import re
import shutil
import signal
import subprocess
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


def zeitdeckel() -> int:
    """Sekunden je Datei. FUNKTION, keine Modulkonstante – ein beim Import
    gelesener Wert waere bis zum Dienstneustart nicht aenderbar.

    120 s statt eines knapperen Werts, weil die Laufzeit an der DATEIGROESSE
    haengt, nicht an der Seitenzahl: gemessen 1,4 s fuer 14 KB und 11,5 s fuer
    435 KB. Ein mehrere Megabyte grosser Abschnitt braucht entsprechend mehr.
    """
    try:
        wert = int(os.environ.get("JARVIS_ONENOTE_TIMEOUT", "120"))
    except (TypeError, ValueError):
        return 120
    return max(10, min(wert, 900))


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
    """Klartext-Hinweis, WAS fehlt und wie man es behebt – oder "".

    Ohne diese Meldung bekaeme der Administrator nur "Datei liess sich nicht
    auslesen" und muesste raten. Dieselbe Ueberlegung wie beim PDF-Export ohne
    LibreOffice (2026-07-28): daraus konnte weder Modell noch Nutzer ableiten,
    was zu tun ist.
    """
    fehlt = []
    if not finde_java():
        fehlt.append("Java")
    if not finde_tika():
        fehlt.append("Apache Tika (tika-app.jar)")
    if not fehlt:
        return ""
    return (
        "OneNote-Datei nicht lesbar – auf diesem Server fehlt: "
        + " und ".join(fehlt)
        + ". Ein Administrator behebt das mit 'sudo bash deploy/tika_setup.sh' "
        "(installiert die Java-Laufzeit und legt tika-app.jar unter vendor/ ab). "
        "Java allein kommt auch ueber Einstellungen -> Skills: der Wissens-Skill "
        "zeigt dann die Plakette 'Abhaengigkeit fehlt' und daneben den Knopf "
        "'Fehlende Abhaengigkeiten nachinstallieren'."
    )


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
    bilanz = {"zeilen": 0, "dubletten": 0, "rauschen": 0, "zeit": 0, "behalten": 0}
    gesehen: set[str] = set()
    aus: list[str] = []
    for rohzeile in (roh or "").splitlines():
        zeile = _entschaerfen(rohzeile)
        if not zeile:
            continue
        bilanz["zeilen"] += 1
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


def text_aus_datei(pfad: Path, zeitlimit: int | None = None) -> tuple[str | None, str]:
    """Extrahiert Text aus einer ``.one``-Datei.

    Rueckgabe ``(text, grund)``: ``text`` ist None, wenn nichts herauskam –
    ``grund`` nennt dann im Klartext, warum. Der Aufrufer im Indexer braucht
    beides getrennt, weil er den Grund in die Fehlerliste des Laufs schreibt.
    """
    java = finde_java()
    jar = finde_tika()
    if not java or not jar:
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

    try:
        roh, fehler = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:  # noqa: BLE001
            pass
        return None, (f"Zeitlimit von {limit} s ueberschritten – Datei zu gross "
                      f"oder beschaedigt (JARVIS_ONENOTE_TIMEOUT erhoeht das Limit)")
    except Exception as e:  # noqa: BLE001
        return None, f"Aufruf fehlgeschlagen: {e}"

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
