#!/usr/bin/env python3
"""Waechter fuer den OneNote-Import (*.one).

TEIL 1 laeuft ueberall: Verdrahtung, Regeln, Saeuberung (ausgefuehrt, nicht
gelesen). TEIL 2 braucht Java + tika-app.jar und laeuft gegen ECHTE
Notizbuchdateien; fehlt eine Voraussetzung, werden die Pruefungen als
UEBERSPRUNGEN gezaehlt und namentlich genannt – niemals als bestanden.

WARUM DER TEIL 1 UEBERHAUPT NOETIG IST: der teuerste Fehler dieser Aenderung
waere nicht ein falscher Parser, sondern eine VERGESSENE Stelle. Die Liste der
indizierbaren Endungen stand an sechs Orten als Handarbeit; die vergessene
Stelle meldet sich nicht, sie laesst die Datei nur still liegen.
"""

import os
import re
import subprocess
import sys
import types
from pathlib import Path

WURZEL = Path(__file__).parent.parent
sys.path.insert(0, str(WURZEL))

OK = FAIL = UEBERSPRUNGEN = 0


def check(beschreibung, bedingung, detail=""):
    """ACHTUNG Reihenfolge: (Text, Bedingung). Vertauscht bricht der Lauf ab –
    eine nicht-leere Zeichenkette ist wahr, und der Waechter meldete dann
    lauter OK, ohne eine Bedingung ausgewertet zu haben (2026-08-28 bezahlt)."""
    global OK, FAIL
    if not isinstance(beschreibung, str) or isinstance(bedingung, str):
        print(f"\033[31mABBRUCH: check(...) vertauscht: {beschreibung!r}, {bedingung!r}\033[0m")
        sys.exit(2)
    if bedingung:
        OK += 1
        print(f"  \033[32m✓\033[0m {beschreibung}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {beschreibung}" + (f"  → {detail}" if detail else ""))


def paar(fn, *a, **k):
    """Immer ein 2-Tupel – auch wenn der Aufruf wirft.

    ``t, g = sicher(...) or (None, None)`` sieht sicher aus und ist es nicht:
    sicher() gibt im Fehlerfall eine ZEICHENKETTE zurueck, und das Auspacken
    einer Zeichenkette in zwei Namen wirft ValueError. Der Lauf bricht dann
    ohne Bilanz ab – in der Gegenprobe (12) genau so passiert, zweimal in
    derselben Sitzung.
    """
    try:
        e = fn(*a, **k)
    except Exception as ex:  # noqa: BLE001
        return None, f"__FEHLER__ {type(ex).__name__}: {ex}"
    if isinstance(e, tuple) and len(e) == 2:
        return e
    return None, f"__UNERWARTET__ {e!r}"


def uebersprungen(beschreibung, grund):
    global UEBERSPRUNGEN
    UEBERSPRUNGEN += 1
    print(f"  \033[33m–\033[0m {beschreibung}  (NICHT GEPRUEFT: {grund})")


def sicher(fn, *a, **k):
    """Nie ungeprueft dereferenzieren: eine Pruefung, die WIRFT, bricht den
    Lauf ab – und ein abgebrochener Waechter ist von einem bestandenen nicht zu
    unterscheiden (Register)."""
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return f"__FEHLER__ {type(e).__name__}: {e}"


def ohne_kommentare_py(text):
    """Python-Kommentare und Docstrings durch Leerzeichen ersetzen.

    Ohne diesen Schritt liest der Waechter seine EIGENE Begruendung mit – im
    Projekt zwoelfmal passiert. Positivkontrolle weiter unten.

    ERSETZT, NICHT ENTFERNT – und das ist der Punkt: die erste Fassung sammelte
    die Tokens ein und fuegte sie mit Zeilenumbruechen zusammen. Damit zerfiel
    JEDER mehrteilige Ausdruck (aus "start_new_session=True" wurden drei
    Zeilen), und drei voellig richtige Pruefungen schlugen fehl. Ein Waechter,
    der den Quelltext umbaut, prueft nicht mehr den Quelltext.
    """
    import io
    import tokenize
    zeilen = text.splitlines(keepends=True)
    try:
        spannen = []
        zeilenanfang = True
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                spannen.append((tok.start, tok.end))
            elif tok.type == tokenize.STRING and zeilenanfang:
                # Ein String am Anfang einer logischen Zeile ist Docstring oder
                # ein Ausdruck ohne Wirkung – in beiden Faellen Text.
                spannen.append((tok.start, tok.end))
            if tok.type in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.COMMENT):
                zeilenanfang = True
            else:
                zeilenanfang = False
        for (z1, s1), (z2, s2) in spannen:
            for z in range(z1, z2 + 1):
                if z - 1 >= len(zeilen):
                    continue
                zeile = zeilen[z - 1]
                a = s1 if z == z1 else 0
                b = s2 if z == z2 else len(zeile.rstrip("\n"))
                if b > a:
                    zeilen[z - 1] = zeile[:a] + " " * (b - a) + zeile[b:]
    except Exception:  # noqa: BLE001
        return text
    return "".join(zeilen)


def ohne_kommentare_js(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


# ─── Stubs, damit knowledge.py ohne fastapi/dotenv importierbar bleibt ───────
_d = types.ModuleType("dotenv"); _d.load_dotenv = lambda *a, **k: None
sys.modules.setdefault("dotenv", _d)
_cfg = types.ModuleType("backend.config")


class _Config:
    def get_skill_states(self):
        return {}

    def save_skill_state(self, *a, **k):
        pass

    def __getattr__(self, n):
        return None


_cfg.config = _Config()
sys.modules.setdefault("backend.config", _cfg)

import backend.tools.knowledge as K          # noqa: E402
from backend.tools import onenote as ON      # noqa: E402

FIXTURES = WURZEL / "tests" / "fixtures" / "onenote"

# Namen der geprueften Funktionen NICHT ungeprueft dereferenzieren: ein
# umbenannter Helfer laesst den Waechter sonst mit AttributeError abbrechen –
# und ein abgebrochener Lauf sieht wie ein bestandener aus (Register).
for _name in ("alle_endungen", "_unlesbar_grund", "_extract_text_raw", "get_stats"):
    if not hasattr(K, _name):
        print(f"\033[31mABBRUCH: knowledge.{_name} gibt es nicht (umbenannt?)\033[0m")
        sys.exit(2)
# Die Symbole der Automatik gehoeren HIERHER, nicht erst vor Abschnitt 10:
# Abschnitt 5 greift bereits auf _zustand zu, und gegen einen Altstand ohne
# diese Namen brach der Lauf mit AttributeError ab – OHNE Bilanzzeile und
# damit nicht von "bestanden" zu unterscheiden (Register). Fehlt eines,
# endet der Waechter mit Exit 2: "konnte nicht laufen".
for _name in ("saeubern", "text_aus_datei", "finde_java", "finde_tika",
              "fehlender_baustein", "zeitdeckel", "stille_deckel", "jvm_heap",
              "_lies_stroemend", "_abraeumen", "_xps_auspacken",
              "einrichtung_anstossen", "einrichtung_laeuft", "automatik_an",
              "letzter_einrichtungsfehler", "WIEDERHOLUNG_S", "_zustand"):
    if not hasattr(ON, _name):
        print(f"\033[31mABBRUCH: onenote.{_name} gibt es nicht (umbenannt?)\033[0m")
        sys.exit(2)


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m1. Endung registriert – und .onetoc2 bewusst NICHT\033[0m")

endungen = sicher(K.alle_endungen)
check(".one ist indizierbar", isinstance(endungen, set) and ".one" in endungen, str(endungen)[:80])
check(".onetoc2 ist NICHT dabei (Notizbuch-Index ohne Inhalt, kein Parser)",
      isinstance(endungen, set) and ".onetoc2" not in endungen)
check("EXTENSIONS_ONENOTE enthaelt genau .one", getattr(K, "EXTENSIONS_ONENOTE", None) == {".one"},
      repr(getattr(K, "EXTENSIONS_ONENOTE", None)))
# Gegenrichtung: die uebrigen Formate duerfen nicht verloren gegangen sein.
for e in (".pdf", ".docx", ".xlsx", ".pptx", ".md", ".png", ".mp3"):
    check(f"{e} weiterhin indizierbar", e in endungen)

# Mit einer ECHTEN Datei: _unlesbar_grund macht zuerst stat() und meldete
# sonst "nicht lesbar" statt der Formataussage – der Waechter haette einen
# Fehler gemeldet, den es nicht gibt.
import tempfile as _tf
with _tf.NamedTemporaryFile(suffix=".onetoc2", delete=False) as _f:
    _f.write(b"x" * 64)
    _toc = Path(_f.name)
grund_toc = sicher(K._unlesbar_grund, _toc, 10 ** 9)
_toc.unlink(missing_ok=True)
check(".onetoc2 bekommt einen ERKLAERENDEN Grund, nicht 'nicht unterstuetzt'",
      isinstance(grund_toc, str) and "Notizbuch-Index" in grund_toc, str(grund_toc)[:120])


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m2. REGEL: die Endungs-Liste wird nirgends von Hand zusammengesetzt\033[0m")

# Diese Regel ist der eigentliche Grund fuer den Umbau. Sie prueft nicht eine
# gepflegte Liste von Orten, sondern die EIGENSCHAFT – damit faellt auch eine
# kuenftige Stelle auf.
import ast as _ast


def _oder_ketten(quelle):
    """Alle |-Ausdruecke ueber EXTENSIONS_*-Namen, mit ihrer Umgebung.

    AST statt Zeilensuche, aus zwei Gruenden: die Vereinigung stand ueber
    MEHRERE Zeilen verteilt, und das legitime dispatch-Muster
    ``if suffix in (EXTENSIONS_VIDEO | EXTENSIONS_AUDIO)`` darf nicht als
    Verstoss gelten. Gezaehlt werden die NAMEN in einem Ausdruck: die
    Gesamtliste hat neun, ein Dispatch-Vergleich zwei.
    """
    aus = []
    baum = _ast.parse(quelle)
    eltern = {}
    for k in _ast.walk(baum):
        for kind in _ast.iter_child_nodes(k):
            eltern[kind] = k
    for k in _ast.walk(baum):
        if not (isinstance(k, _ast.BinOp) and isinstance(k.op, _ast.BitOr)):
            continue
        # nur die WURZEL einer Kette bewerten, nicht jedes Teilstueck
        if isinstance(eltern.get(k), _ast.BinOp) and isinstance(eltern[k].op, _ast.BitOr):
            continue
        namen = {n.id for n in _ast.walk(k)
                 if isinstance(n, _ast.Name) and n.id.startswith("EXTENSIONS_")}
        if not namen:
            continue
        # umgebende Funktion bestimmen
        fn = ""
        p2 = eltern.get(k)
        while p2 is not None:
            if isinstance(p2, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                fn = p2.name
                break
            p2 = eltern.get(p2)
        aus.append((fn, sorted(namen)))
    return aus


verstoss = []
for pfad in sorted(WURZEL.glob("backend/**/*.py")):
    quelle = pfad.read_text(encoding="utf-8", errors="replace")
    for fn, namen in sicher(_oder_ketten, quelle) or []:
        if fn == "alle_endungen":
            continue            # die EINE Quelle
        if len(namen) >= 4:     # vier oder mehr = jemand baut die Liste nach
            verstoss.append(f"{pfad.relative_to(WURZEL)}::{fn or '<modul>'}: {namen}")
check("keine handgebaute Vereinigung mehr (ausser in alle_endungen())",
      not verstoss, " | ".join(verstoss[:3]))
check("das legitime Dispatch-Muster (2 Namen) gilt NICHT als Verstoss",
      any(len(n) == 2 for _, n in (sicher(_oder_ketten,
          (WURZEL / "backend" / "tools" / "knowledge.py").read_text()) or [])))

# Positivkontrolle: die Regel MUSS anschlagen, wenn man ihr eine solche Zeile
# vorlegt – sonst waere die Null oben eine leere Abfrage.
probe = ("def irgendwas():\n    return (EXTENSIONS_TEXT | EXTENSIONS_PDF | EXTENSIONS_DOCX\n"
         "            | EXTENSIONS_XLSX | EXTENSIONS_ONENOTE)\n")
gefunden = sicher(_oder_ketten, probe) or []
check("Positivkontrolle: die Regel erkennt eine handgebaute Vereinigung (auch mehrzeilig)",
      any(len(n) >= 4 for _, n in gefunden), str(gefunden))

# Und die Kommentar-Entfernung muss wirklich entfernen, sonst prueft Teil 2
# oben womoeglich Begruendungstexte.
roh = (WURZEL / "backend" / "tools" / "onenote.py").read_text()
ohne = ohne_kommentare_py(roh)
check("Positivkontrolle: ohne_kommentare_py entfernt Kommentare",
      "WARUM TIKA UND NICHT PYTHON" in roh and "WARUM TIKA UND NICHT PYTHON" not in ohne)
check("Positivkontrolle: ohne_kommentare_py behaelt Code",
      "def text_aus_datei" in ohne)

alle_nutzer = []
for pfad in sorted(WURZEL.glob("backend/**/*.py")):
    if "alle_endungen" in pfad.read_text(encoding="utf-8", errors="replace"):
        alle_nutzer.append(pfad.name)
check("alle vier Module lesen aus der einen Quelle",
      {"knowledge.py", "main.py", "knowledge_sync.py"} <= set(alle_nutzer), str(alle_nutzer))


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m3. Dispatch: der .one-Zweig ruft wirklich den Extraktor\033[0m")

quelle_k = ohne_kommentare_py((WURZEL / "backend" / "tools" / "knowledge.py").read_text())
check("_extract_text_rest ruft text_aus_datei",
      "text_aus_datei(filepath" in quelle_k)
# Der Fortschritt muss dabei durchgereicht werden - sonst steht in der
# Oberflaeche minutenlang derselbe Dateiname und der Lauf sieht tot aus.
check("und reicht einen Fortschritts-Callback durch",
      "melde=" in quelle_k.split("text_aus_datei(filepath")[1][:40], quelle_k[:0])
check("_failure_reason fragt den fehlenden Baustein ab", "fehlender_baustein" in quelle_k)
check("get_stats liefert onenote_support", '"onenote_support"' in quelle_k)
def rumpf(quelle, name):
    """Rumpf einer Funktion per AST - NICHT "bis zur naechsten Textmarke".

    Ein Schnitt an einer Textmarke hat in diesem Projekt schon 446 Zeilen
    fremden Code mitgenommen und die Pruefung damit trivial wahr gemacht.
    """
    import ast
    baum = ast.parse(quelle)
    for k in ast.walk(baum):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return ast.get_source_segment(quelle, k) or ""
    return ""


quelle_k_roh = (WURZEL / "backend" / "tools" / "knowledge.py").read_text()
r_static = rumpf(quelle_k_roh, "_get_static_stats")
r_stats = rumpf(quelle_k_roh, "get_stats")
check("Positivkontrolle: beide Funktionsruempfe gefunden",
      len(r_static) > 100 and len(r_stats) > 100, f"{len(r_static)}/{len(r_stats)}")
check("onenote_support liegt NICHT im prozessweiten Cache, sondern in get_stats",
      "onenote_support" not in r_static and "onenote_support" in r_stats,
      "sonst bleibt die Plakette bis zum Dienstneustart rot")

# Der Zweig wird AUSGEFUEHRT gemessen, nicht gelesen: mit einer Attrappe fuer
# den Extraktor. Eine Quelltext-Pruefung bliebe gruen, wenn jemand ein return
# davor setzt.
spur = []


def _attrappe(pfad, zeitlimit=None, melde=None):
    # Signatur GENAU wie das Original: eine Attrappe, die mehr annimmt (etwa
    # **kwargs), wuerde einen Aufruf durchwinken, den der echte Extraktor
    # ablehnt (Register).
    spur.append(str(pfad))
    if melde is not None:
        melde(0, 0.0)          # der Aufrufer muss einen Callback vertragen
    return "AUS DER ATTRAPPE", "ok"


echt = ON.text_aus_datei
try:
    ON.text_aus_datei = _attrappe
    tmp = FIXTURES / "abschnitt_2016.one"
    ergebnis = sicher(K._extract_text_raw, tmp, 10 ** 9)
finally:
    ON.text_aus_datei = echt
check("_extract_text_raw leitet .one an den Extraktor weiter",
      ergebnis == "AUS DER ATTRAPPE" and len(spur) == 1, f"{ergebnis!r} / {spur}")


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m4. saeubern() – gegen die GEMESSENEN Rohausgaben\033[0m")

# Genau die Zeilen, die Tika am 2026-09-03 aus den echten Dateien geliefert hat.
# "14:08" ist die Zeile, an der die Zeitstempel-Regel HAENGT: sie hat vier
# Ziffern und gilt damit als Nutztext, der Rauschfilter nimmt sie also NICHT
# weg. "5:37 PM" faellt schon am Rauschfilter (kein Wort ab drei Buchstaben) –
# ein Test nur damit ist gruen, auch wenn die Zeitstempel-Regel fehlt. Genau so
# hat die Gegenprobe (8) zuerst NICHT gebissen.
roh_2016 = ("So good\nWednesday, December 11, 2019\n5:37 PM\n14:08\n"
            "Wednesday, December 11, 2019\nSo good\nThis is one note 2016\n5:37 PM\n")
text, bilanz = paar(ON.saeubern, roh_2016)
check("Dubletten fallen weg (global, nicht nur benachbart)",
      isinstance(text, str) and text.count("So good") == 1, repr(text))
check("der einzigartige Inhalt bleibt", isinstance(text, str) and "This is one note 2016" in text)
check("die nackte Uhrzeit fliegt raus (auch die 24-h-Form mit vier Ziffern)",
      isinstance(text, str) and "5:37 PM" not in text and "14:08" not in text, repr(text))
check("das Datum bleibt (Seitenkopf, traegt Information)",
      isinstance(text, str) and "December 11, 2019" in text)
check("Bilanz zaehlt die Dubletten", isinstance(bilanz, dict) and bilanz.get("dubletten") == 2,
      str(bilanz))

# Binaerreste, wie sie in testOneNote2007OrEarlier.one wirklich vorkamen.
binaer = "i\\ hE@RZ\npM:3t Em\nEine echte Notiz mit Inhalt.\n"
text2, b2 = paar(ON.saeubern, binaer)
check("Binaerreste ohne Wort werden verworfen",
      isinstance(text2, str) and "hE@RZ" not in text2 and "pM:3t" not in text2, repr(text2))
check("die echte Notiz daneben bleibt",
      isinstance(text2, str) and "Eine echte Notiz mit Inhalt." in text2)

# Bild-Metadaten aus den Rohbytes.
meta = ('iCCPICC Profile\n<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        '<exif:PixelXDimension>373</exif:PixelXDimension>\n<rdf:Description rdf:about="">\n'
        'Besprechungsnotiz vom Montag\n')
text3, _ = paar(ON.saeubern, meta)
for marke in ("ICC Profile", "xmpmeta", "exif:", "rdf:"):
    check(f"Bild-Metadaten weg: {marke}", isinstance(text3, str) and marke not in text3, repr(text3))
check("der Notiztext daneben bleibt",
      isinstance(text3, str) and "Besprechungsnotiz vom Montag" in text3)

# U+FFFD an Namen eingebetteter Objekte – KEIN Steuerzeichen, eine Pruefung
# ueber die Unicode-Kategorie C allein sieht es nicht.
text4, _ = paar(ON.saeubern, "Untitled picture.png�\n")
check("U+FFFD wird entfernt, der Name bleibt", text4 == "Untitled picture.png", repr(text4))

# Gegenrichtungen: was NICHT verloren gehen darf.
behalten = [
    ("Chinesisch ohne lateinische Woerter", "中文标题"),
    # KURZ und chinesisch: _WORT_RE verlangt drei Zeichen, ein chinesisches
    # Wort ist oft zwei - ohne die CJK-Pruefung waere das Rauschen.
    ("zweizeichiges chinesisches Wort", "中文"),
    ("Preis-/Zahlzeile ohne Buchstaben", "§249.99-599.99 |"),
    ("Datum ohne Buchstaben", "7/25/2012"),
    ("vokallose Abkuerzung (SQL)", "SQL"),
    ("vokallose Abkuerzung (PDF)", "PDF"),
    ("gemischtschreibende Abkuerzung (GmbH)", "GmbH"),
    ("deutsches Wort mit y statt Vokal", "Typ"),
    ("langer Satz mit Sonderzeichen", "+ Arrive at airport at 6am [Ben + Hotel ist fuer den 6.]"),
]
for name, zeile in behalten:
    t, _ = paar(ON.saeubern, zeile + "\n")
    check(f"bleibt erhalten: {name}", t == zeile, repr(t))

leer, bleer = paar(ON.saeubern, "")
check("leere Eingabe ergibt leeren Text ohne Wurf", leer == "" and isinstance(bleer, dict))


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m5. Voraussetzungen finden und melden\033[0m")

quelle_o = ohne_kommentare_py((WURZEL / "backend" / "tools" / "onenote.py").read_text())
check("Zeitdeckel ist eine FUNKTION (env zur Laufzeit lesbar)", callable(getattr(ON, "zeitdeckel", None)))
check("Heap-Grenze ist eine FUNKTION", callable(getattr(ON, "jvm_heap", None)))
# Nicht ungeprueft vergleichen: ist zeitdeckel keine Funktion mehr, gibt
# sicher() eine Zeichenkette zurueck - ein ">=" darauf WIRFT, der Lauf bricht
# OHNE BILANZ ab, und ein abgebrochener Waechter ist von einem bestandenen
# nicht zu unterscheiden. In der Gegenprobe (12) genau so passiert.
_deckel = sicher(lambda: ON.zeitdeckel())
check("harte Obergrenze wird nach unten UND oben begrenzt",
      isinstance(_deckel, int) and 60 <= _deckel <= 86400, repr(_deckel))
_stille = sicher(lambda: ON.stille_deckel())
check("Stille-Deckel ist eine FUNKTION und begrenzt",
      isinstance(_stille, int) and 10 <= _stille <= 3600, repr(_stille))
# ⚠ DIE EIGENTLICHE ZUSAGE: die Notbremse muss WEIT ueber der Geduld liegen.
# Steht sie darunter, greift sie zuerst - und der Stille-Waechter, der den
# Unterschied zwischen "arbeitet" und "haengt" kennt, kommt nie zum Zug.
check("die Notbremse liegt deutlich ueber dem Stille-Deckel",
      isinstance(_deckel, int) and isinstance(_stille, int) and _deckel >= 5 * _stille,
      f"gesamt={_deckel} stille={_stille}")
alt = os.environ.get("JARVIS_ONENOTE_TIMEOUT")
try:
    os.environ["JARVIS_ONENOTE_TIMEOUT"] = "unfug"
    check("unbrauchbarer Zeitwert faellt auf die Vorgabe, statt zu werfen",
          sicher(lambda: ON.zeitdeckel()) == 3600)
    os.environ["JARVIS_ONENOTE_TIMEOUT"] = "5"
    check("zu kleiner Zeitwert wird gehoben", sicher(lambda: ON.zeitdeckel()) == 60)
finally:
    os.environ.pop("JARVIS_ONENOTE_TIMEOUT", None)
    if alt is not None:
        os.environ["JARVIS_ONENOTE_TIMEOUT"] = alt

alt = os.environ.get("JARVIS_ONENOTE_STILLE")
try:
    os.environ["JARVIS_ONENOTE_STILLE"] = "unfug"
    check("unbrauchbarer Stille-Wert faellt auf die Vorgabe",
          sicher(lambda: ON.stille_deckel()) == 120)
    os.environ["JARVIS_ONENOTE_STILLE"] = "3"
    check("zu kleiner Stille-Wert wird gehoben", sicher(lambda: ON.stille_deckel()) == 10)
finally:
    os.environ.pop("JARVIS_ONENOTE_STILLE", None)
    if alt is not None:
        os.environ["JARVIS_ONENOTE_STILLE"] = alt

alt = os.environ.get("JARVIS_ONENOTE_HEAP")
try:
    os.environ["JARVIS_ONENOTE_HEAP"] = "rm -rf /"
    check("unbrauchbare Heap-Angabe wird verworfen (kein Argument-Schmuggel)",
          sicher(lambda: ON.jvm_heap()) == "512m", repr(sicher(lambda: ON.jvm_heap())))
finally:
    os.environ.pop("JARVIS_ONENOTE_HEAP", None)
    if alt is not None:
        os.environ["JARVIS_ONENOTE_HEAP"] = alt

check("JARVIS_TIKA_JAR sticht die Kandidaten", "JARVIS_TIKA_JAR" in quelle_o)
check("Timeout toetet die PROZESSGRUPPE, nicht nur das Kind",
      "start_new_session=True" in quelle_o and "killpg" in quelle_o)
check("kein shell=True", "shell=True" not in quelle_o)
check("HOME wird gesetzt (sonst sucht die JVM in /root)", 'setdefault("HOME"' in quelle_o)
check("der Rueckgabewert entscheidet, nicht ein nicht-leeres stderr",
      "proc.returncode != 0" in quelle_o)

# Fehlt ein Baustein, sagt der Hinweis, WAS PASSIERT – und fordert NICHT zur
# Handarbeit auf. Vorgabe des Betreibers (2026-09-04): auf einen Hinweis zu
# hoffen, auf den ein Administrator zufaellig stoesst, ist keine Loesung.
# Der Anstoss wird hier ueber den Mindestabstand stillgelegt, damit die
# Textpruefung keinen echten Einrichtungslauf startet (Abschnitt 10 misst ihn).
import time as _t
alt_jar = os.environ.get("JARVIS_TIKA_JAR")
ON._zustand["letzter_start"] = _t.time()
try:
    os.environ["JARVIS_TIKA_JAR"] = "/gibt/es/nicht/tika.jar"
    hinweis = sicher(ON.fehlender_baustein)
    check("fehlende Tika wird benannt", isinstance(hinweis, str) and "Tika" in hinweis, str(hinweis)[:90])
    check("der Hinweis sagt, dass es AUTOMATISCH passiert",
          isinstance(hinweis, str) and "automatisch" in hinweis.lower(), str(hinweis)[:140])
    check("und fordert KEINE Handarbeit, solange die Automatik greifen kann",
          isinstance(hinweis, str) and "sudo bash" not in hinweis, str(hinweis)[:140])
    text, grund = paar(ON.text_aus_datei, FIXTURES / "abschnitt_2016.one")
    check("ohne Tika kommt None + Grund, nicht ein leerer Text",
          text is None and isinstance(grund, str) and "automatisch" in grund.lower(),
          repr(grund)[:90])
    check("_failure_reason gibt dieselbe Aussage heraus",
          "automatisch" in str(sicher(K._unlesbar_grund,
                                      FIXTURES / "abschnitt_2016.one", 10 ** 9)).lower())
    # Die Ausnahme, in der der Handweg richtig ist: die Automatik ist AUS.
    os.environ["JARVIS_TIKA_AUTO"] = "0"
    aus = sicher(ON.fehlender_baustein)
    check("bei abgeschalteter Automatik steht der Handweg drin",
          isinstance(aus, str) and "tika_setup.sh" in aus and "JARVIS_TIKA_AUTO" in aus,
          str(aus)[:140])
finally:
    os.environ.pop("JARVIS_TIKA_AUTO", None)
    os.environ.pop("JARVIS_TIKA_JAR", None)
    if alt_jar is not None:
        os.environ["JARVIS_TIKA_JAR"] = alt_jar
    ON._zustand["letzter_start"] = 0.0


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m6. Manifest, Setup-Skript, .gitignore\033[0m")

import json  # noqa: E402
manifest = json.loads((WURZEL / "skills" / "knowledge" / "skill.json").read_text())
check("Java steht als system_package im Manifest",
      "default-jre-headless" in manifest.get("system_packages", []),
      str(manifest.get("system_packages")))
check("Java steht NICHT unter dependencies (es ist kein pip-Paket)",
      "default-jre-headless" not in manifest.get("dependencies", []))
check("die Formatliste im Manifest nennt OneNote",
      "OneNote" in manifest["help"]["notes"])
check("das Manifest benennt die Grenze (keine Seitengrenzen)",
      "Seitengrenzen" in manifest["help"]["notes"])

skript = (WURZEL / "deploy" / "tika_setup.sh").read_text()
check("Setup-Skript existiert und pinnt die SHA-256",
      re.search(r'TIKA_SHA256="[0-9a-f]{64}"', skript) is not None)
check("Setup-Skript prueft zusaetzlich die veroeffentlichte SHA-1",
      re.search(r'TIKA_SHA1="[0-9a-f]{40}"', skript) is not None)
check("Setup-Skript hat einen --pruefen-Modus", "--pruefen" in skript)
check("Setup-Skript laedt erst in eine Nebendatei und verschiebt nach der Pruefung",
      ".tika-app.jar.download" in skript and "mv -f" in skript)
check("Setup-Skript setzt den Eigentuemer auf den Dienstbenutzer",
      "chown" in skript and "DIENST_USER" in skript)
check("Setup-Skript ueberschreibt eine fremde Datei NICHT selbsttaetig",
      "PRÜFSUMME WEICHT AB" in skript)
# Der Pipeline-Fallstrick aus dem Register: RC=$? nach einer Pipe misst das
# LETZTE Glied. Hier als Regel geprueft.
schlecht = re.search(r'AUSGABE="\$\([^)]*\|[^)]*\)"\s*\n\s*RC=\$\?', skript)
check("kein 'RC=$?' unmittelbar nach einer Pipeline", schlecht is None)

gi = subprocess.run(["git", "check-ignore", "-v", "vendor/tika-app.jar"],
                    cwd=WURZEL, capture_output=True, text=True)
check("vendor/ ist wirklich ignoriert (gemessen, nicht am Dateiinhalt geraten)",
      gi.returncode == 0, gi.stdout.strip() or gi.stderr.strip())


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m7. Oberflaeche: die Plakette sagt den Zustand\033[0m")

kjs = ohne_kommentare_js((WURZEL / "frontend" / "js" / "knowledge.js").read_text())
check("knowledge.js liest onenote_support", "stats.onenote_support" in kjs)
check("die Plakette steht in der Formatzeile", "OneNote</span>" in kjs)
i18n = (WURZEL / "frontend" / "js" / "i18n.js").read_text()
for schluessel in ("knowledge.support_onenote_ok", "knowledge.support_onenote_missing"):
    check(f"i18n-Schluessel zweimal vorhanden (DE+EN): {schluessel}",
          i18n.count(f"'{schluessel}'") == 2, str(i18n.count(f"'{schluessel}'")))
# Die Plakette ist der einzige Ort, an dem ein Administrator den Zustand sieht –
# und sie darf ihn NICHT zu einem Befehl auffordern, den die Automatik ohnehin
# selbst ausfuehrt. Geprueft wird der Meldungstext beider Sprachen.
for _spr, _abschnitt in (("DE", i18n[:i18n.find("knowledge.support_onenote_missing") + 400]),
                         ("EN", i18n[i18n.rfind("knowledge.support_onenote_missing"):][:400])):
    check(f"die Plakette fordert keine Handarbeit ({_spr})",
          "tika_setup.sh" not in _abschnitt, _abschnitt[:160])
check("die Plakette sagt, dass die Einrichtung automatisch laeuft",
      i18n.count("automatisch (lädt") >= 1 and "automatically" in i18n)
check("der Hinweis der Netzwerk-Freigaben erklaert den OneNote-Fall",
      i18n.count("*.one") >= 2)


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m8. ECHTE Dateien durch den echten Tika-Lauf\033[0m")

java = ON.finde_java()
jar = ON.finde_tika()
if not java or not jar:
    fehlt = " und ".join([n for n, v in (("Java", java), ("tika-app.jar", jar)) if not v])
    for name in ("2016er Abschnitt", "Office-365-Abschnitt", "Abschnitt mit Bild",
                 "Dublettenabbau am echten Lauf", "unlesbare Datei"):
        uebersprungen(name, f"{fehlt} nicht vorhanden – 'sudo bash deploy/tika_setup.sh'")
else:
    print(f"  (Java: {java} · Tika: {jar})")
    t, g = paar(ON.text_aus_datei, FIXTURES / "abschnitt_2016.one")
    check("2016er Abschnitt: Text kommt heraus",
          isinstance(t, str) and "This is one note 2016" in t, repr(g)[:100])
    check("2016er Abschnitt: keine Dublette im Ergebnis",
          isinstance(t, str) and t.count("So good") == 1, repr(t)[:120])

    t, g = paar(ON.text_aus_datei, FIXTURES / "abschnitt_o365.one")
    check("Office-365-Abschnitt: beide Seiteninhalte da",
          isinstance(t, str) and "Section1Page1Content" in t and "Section1Page2Content" in t,
          repr(t)[:120])

    t, g = paar(ON.text_aus_datei, FIXTURES / "abschnitt_bild.one")
    check("Abschnitt mit Bild: der von OneNote erkannte Bildtext kommt mit",
          isinstance(t, str) and "Test section" in t, repr(t)[:150])
    check("Abschnitt mit Bild: keine ICC-/XMP-Reste im Ergebnis",
          isinstance(t, str) and "ICC Profile" not in t and "xmpmeta" not in t, repr(t)[:150])

    # Der Dublettenabbau ist der groesste Gewinn – am echten Lauf gemessen,
    # nicht an einer nachgebauten Zeichenkette.
    roh = subprocess.run([java, f"-Xmx{ON.jvm_heap()}", "-jar", str(jar), "--text",
                          str(FIXTURES / "abschnitt_bild.one")],
                         capture_output=True, text=True, timeout=180)
    vorher = len([z for z in roh.stdout.splitlines() if z.strip()])
    nachher = len([z for z in (t or "").splitlines() if z.strip()])
    check(f"Dubletten/Rauschen messbar entfernt ({vorher} → {nachher} Zeilen)",
          vorher > 0 and nachher < vorher, f"{vorher} / {nachher}")

    # Eine Datei, die WIRKLICH kein lesbares OneNote ist: None MIT Grund.
    # Der Grund muss die Aussage tragen, nicht die letzte Stacktrace-Zeile.
    import os as _os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".one", delete=False) as f:
        f.write(_os.urandom(4096))
        kaputt = Path(f.name)
    try:
        t, g = paar(ON.text_aus_datei, kaputt)
        check("beschaedigte .one-Datei: None + Grund im Klartext",
              t is None and isinstance(g, str) and "OneStore" in g, repr(g)[:140])
        check("der Grund ist KEINE Stacktrace-Zeile",
              isinstance(g, str) and not g.strip().startswith("at "), repr(g)[:80])
    finally:
        kaputt.unlink(missing_ok=True)

    # GEMESSENE Eigenschaft, damit sie niemand fuer einen Fehler haelt: Tika
    # erkennt am INHALT, nicht an der Endung. Eine Textdatei mit der Endung
    # .one liefert deshalb ihren Text – das ist robuster als eine Absage und
    # hier ausdruecklich erwuenscht (ein falsch benanntes Notizbuch waere
    # sonst unlesbar).
    with tempfile.NamedTemporaryFile(suffix=".one", delete=False, mode="w",
                                     encoding="utf-8") as f:
        f.write("Protokoll der Besprechung vom Montag\n")
        falsch = Path(f.name)
    try:
        t, g = paar(ON.text_aus_datei, falsch)
        check("Tika erkennt am Inhalt: Textdatei mit .one-Endung liefert Text",
              isinstance(t, str) and "Besprechung" in t, repr(t))
    finally:
        falsch.unlink(missing_ok=True)

# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m9. Automatik: die Einrichtung darf keine Handarbeit sein\033[0m")

boot = (WURZEL / "start_jarvis_root.sh").read_text()
# Kommentare weg – sonst liest der Waechter die Begruendungen mit, in denen
# JARVIS_TIKA_AUTO und tika_setup.sh natuerlich vorkommen (Register).
boot_code = "\n".join(z for z in boot.splitlines() if not z.lstrip().startswith("#"))
check("Positivkontrolle: Kommentare sind entfernt",
      "WARUM HIER" in boot and "WARUM HIER" not in boot_code)

check("der Broker-Bootstrap ruft tika_setup.sh", "tika_setup.sh" in boot_code)
check("Schritt 6e steht VOR dem Broker-Start (danach ist exec, es laeuft nichts mehr)",
      boot_code.find("tika_setup.sh") < boot_code.find("backend.broker.daemon"),
      f"{boot_code.find('tika_setup.sh')} / {boot_code.find('backend.broker.daemon')}")
check("abschaltbar ueber JARVIS_TIKA_AUTO", "JARVIS_TIKA_AUTO" in boot_code)
check("Vorgabe ist AN (nur ein ausdrueckliches 0 schaltet ab)",
      'JARVIS_TIKA_AUTO:-1' in boot_code and '!= "0"' in boot_code)

# ⚠ IM HINTERGRUND ist Pflicht, nicht Geschmack: der erste Lauf installiert
# eine Java-Laufzeit und laedt 65 MB. Synchron wartet der Broker-SOCKET darauf
# – und ohne Socket gibt es keine Root-Operationen, kein x11vnc, kein
# websockify.
#
# ⚠ DAS FENSTER MUSS GENAU DIESEN BLOCK TREFFEN. Erste Fassung nahm 400 Zeichen
# VOR dem Fund mit – und griff damit in Schritt 6d (bubblewrap), der ebenfalls
# mit ") &" endet: die Gegenprobe "synchron statt im Hintergrund" blieb gruen,
# weil der Waechter das Hintergrund-& des NACHBARN sah. Dieselbe Klasse wie der
# 446-Zeilen-Schnitt von 2026-08-18.
def bootblock():
    """Der 6e-Block, von der Zuweisung bis zum schliessenden fi."""
    a = boot_code.find('TIKA_SETUP="')
    if a < 0:
        return ""
    e = boot_code.find("\nfi\n", a)
    return boot_code[a:e + 4] if e > a else boot_code[a:]


block = bootblock()
check("Positivkontrolle: der 6e-Block wurde geschnitten und enthaelt nur ihn",
      len(block) > 200 and block.count("TIKA_SETUP=") == 1
      and "bubblewrap" not in block and "SANDBOX_PY" not in block,
      f"{len(block)} Zeichen")
check("der Aufruf laeuft im HINTERGRUND (Subshell mit &)",
      ") &" in block, repr(block[-160:]))
check("erst pruefen, dann einrichten (idempotent, kein Rauschen bei jedem Start)",
      "--pruefen" in block and block.find("--pruefen") < block.find("AUSGABE="))

# Der Pipeline-Fallstrick aus dem Register, hier als Regel ueber die GANZE Datei:
# RC=$? unmittelbar nach einer Pipe misst das letzte Glied.
schlecht = re.search(r'AUSGABE="\$\([^)]*\|[^)]*\)"\s*\n\s*RC=\$\?', boot)
check("kein 'RC=$?' unmittelbar nach einer Pipeline im Bootstrap", schlecht is None)

# Fehlschlag MUSS gemeldet werden - eine Automatik, die still scheitert, ist
# keine (dieselbe Lehre wie bei skip-worktree gegen sparseCheckout).
check("ein Fehlschlag wird nach stderr gemeldet",
      "WARNUNG" in block and ">&2" in block)
check("und er sagt, dass es SELBSTTAETIG wiederholt wird (keine Handarbeit)",
      "wiederholt" in block and "von Hand ausfuehren" not in block, block[-260:])

migr_roh = (WURZEL / "deploy" / "security" / "setup_broker.sh").read_text()
# Kommentarfrei pruefen: der Skriptname steht auch in der Begruendung und im
# Hinweistext – die Gegenprobe "Block entfernt" blieb dadurch gruen, obwohl die
# ZUWEISUNG ins Leere zeigte.
migr = "\n".join(z for z in migr_roh.splitlines() if not z.lstrip().startswith("#"))
check("Positivkontrolle: Kommentare der Migration sind entfernt",
      "SICHTBAR und synchron" in migr_roh and "SICHTBAR und synchron" not in migr)
check("die Erstinstallation zeigt auf das echte Skript",
      re.search(r'TIKA_SETUP="\$\(dirname "\$0"\)/\.\./tika_setup\.sh"', migr) is not None,
      "Zuweisung fehlt oder zeigt woanders hin")
check("sie prueft erst und richtet nur bei Bedarf ein",
      '"$TIKA_SETUP" --pruefen' in migr)
check("die Migration bricht deswegen NICHT ab", "nachholen" in migr)

# Und das Backend muss den Ausfall SAGEN.
haupt_roh = (WURZEL / "backend" / "main.py").read_text()
haupt = ohne_kommentare_py(haupt_roh)


def startup_haken(name):
    """Gibt es eine Startup-Funktion GENAU dieses Namens, und ist sie als
    Startup-Ereignis registriert?

    ⚠ Ein ``"name" in quelltext`` genuegt NICHT: die Gegenprobe benannte die
    Funktion in ``_aus_startup_onenote_tika`` um – der Teilstring blieb, der
    Waechter blieb gruen, und der Haken war weg. Geprueft wird der Name
    EXAKT und der Dekorator dazu.
    """
    import ast
    try:
        baum = ast.parse(haupt_roh)
    except SyntaxError:
        return False
    for k in baum.body:
        if isinstance(k, ast.AsyncFunctionDef) and k.name == name:
            for d in k.decorator_list:
                if (isinstance(d, ast.Call)
                        and getattr(d.func, "attr", "") == "on_event"
                        and any(isinstance(x, ast.Constant) and x.value == "startup"
                                for x in d.args)):
                    return True
    return False


check("Positivkontrolle: ein vorhandener Startup-Haken wird erkannt",
      startup_haken("startup_sandbox_python"))
check("das Backend prueft beim Start und meldet den Ausfall",
      startup_haken("startup_onenote_tika") and "fehlender_baustein" in haupt)
check("⚠ es prueft ZWEIMAL – sonst warnt es, waehrend die Automatik noch laedt",
      haupt.count("fehlender_baustein") >= 2 and "asyncio.sleep(180)" in haupt,
      "sonst fordert ein frischer Server zu einer Handarbeit auf, die laeuft")


def startup_rumpf(name):
    """Der Quelltext GENAU dieser Startup-Funktion, per AST geschnitten.

    ⚠ Eine Fenster-Pruefung (``haupt.split(name)[1][:2000]``) misst je nach
    Laenge der Funktion den NACHBARN mit oder die eigene Funktion nur halb –
    dieselbe Klasse wie der 446-Zeilen-Schnitt von 2026-08-18. Und ein
    ``"x" in haupt`` ueber die ganze Datei trifft jede andere Startup-Routine.
    """
    import ast
    try:
        baum = ast.parse(haupt_roh)
    except SyntaxError:
        return ""
    for k in baum.body:
        if isinstance(k, ast.AsyncFunctionDef) and k.name == name:
            return ast.get_source_segment(haupt_roh, k) or ""
    return ""


_tika_rumpf = ohne_kommentare_py(startup_rumpf("startup_onenote_tika"))
check("Positivkontrolle: der Rumpf wurde geschnitten und ist nur diese Funktion",
      len(_tika_rumpf) > 400 and _tika_rumpf.count("async def startup_") == 1
      and "sandbox_python" not in _tika_rumpf, f"{len(_tika_rumpf)} Zeichen")
check("die Pruefung blockiert den Event-Loop nicht",
      "asyncio.to_thread(" in _tika_rumpf and "fehlender_baustein" in _tika_rumpf)
check("und sie laeuft als Task, nicht im Startup-Pfad (180 s Wartezeit!)",
      "asyncio.create_task(" in _tika_rumpf)
# DER KERN DER VORGABE: das Backend RICHTET EIN, es meldet nicht nur.
check("⚠ das Backend stoesst die Einrichtung selbst an (nicht nur melden)",
      "einrichtung_anstossen" in _tika_rumpf, _tika_rumpf[:200])
check("und es wiederholt den Versuch, statt es bei einem Anlauf zu belassen",
      "for versuch in range(" in _tika_rumpf and "WIEDERHOLUNG_S" in _tika_rumpf)

# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m10. Die Einrichtung passiert von SELBST – ausgefuehrt gemessen\033[0m")
#
# VORGABE DES BETREIBERS (2026-09-04): "Es ist absolut inakzeptabel zu hoffen,
# dass ein Admin zufaellig auf einen versteckten Hinweis stolpert, dass etwas
# nachinstalliert werden muss." Genau das prueft dieser Abschnitt – und zwar
# AUSGEFUEHRT: eine Quelltext-Suche nach "einrichtung_anstossen" bliebe gruen,
# sobald jemand den Zweig spaeter ueberspringt oder der Broker-Aufruf ins Leere
# laeuft.

import backend                                  # noqa: E402
_echt_java, _echt_tika = ON.finde_java, ON.finde_tika
_echt_broker = sys.modules.get("backend.broker_client")


class _FakeBroker:
    """Attrappe des Root-Brokers. Zaehlt die Aufrufe – nur so ist messbar, dass
    ueberhaupt eingerichtet WIRD und dass der Mindestabstand greift."""

    def __init__(self, res=None, modus="broker", nebenwirkung=None, wirft=False):
        self.aufrufe = []
        self._res = res if res is not None else {"ok": True, "rc": 0}
        self._modus = modus
        self._neben = nebenwirkung
        self._wirft = wirft

    def mode(self):
        return self._modus

    def call_sync(self, op, args=None, *, user="", timeout=120, stream_cb=None):
        self.aufrufe.append({"op": op, "args": dict(args or {}), "timeout": timeout,
                             "user": user})
        if self._wirft:
            raise RuntimeError("Broker-Socket weg")
        if self._neben:
            self._neben()
        return self._res


def _broker(fake):
    sys.modules["backend.broker_client"] = fake
    backend.broker_client = fake            # from backend import broker_client
    return fake


def _reset(java=None, tika=None):
    """Frischer Zustand vor jedem Fall – sonst misst der naechste Fall den
    Mindestabstand des vorigen und der Waechter ist gruen aus dem falschen
    Grund."""
    ON.finde_java = (lambda: java)
    ON.finde_tika = (lambda: tika)
    ON._zustand.update({"laeuft": False, "letzter_start": 0.0,
                        "letzter_fehler": "", "versuche": 0})
    os.environ.pop("JARVIS_TIKA_AUTO", None)


def _warte_ende(sek=15.0):
    """Auf das Ende des Hintergrund-Laufs warten. Gibt False zurueck, wenn er
    haengt – das ist ein FAIL und kein Grund, ewig zu blockieren."""
    ziel = _t.time() + sek
    while _t.time() < ziel:
        if not ON.einrichtung_laeuft():
            return True
        _t.sleep(0.05)
    return False


try:
    # (1) Bereits eingerichtet -> es passiert NICHTS.
    _reset(java="/usr/bin/java", tika=Path("/tmp/tika-app.jar"))
    f = _broker(_FakeBroker())
    check("bereits eingerichtet: kein Einrichtungslauf",
          ON.einrichtung_anstossen("test") == "bereits eingerichtet" and not f.aufrufe,
          str(f.aufrufe))

    # (2) Automatik abgeschaltet -> ebenfalls nichts, aber mit Begruendung.
    _reset()
    os.environ["JARVIS_TIKA_AUTO"] = "0"
    f = _broker(_FakeBroker())
    erg = ON.einrichtung_anstossen("test")
    check("JARVIS_TIKA_AUTO=0 schaltet die Automatik wirklich ab",
          "abgeschaltet" in erg and not f.aufrufe, f"{erg} / {f.aufrufe}")
    os.environ.pop("JARVIS_TIKA_AUTO", None)

    # (3) DER KERNFALL: nichts da -> die Broker-Op laeuft wirklich.
    _reset()
    f = _broker(_FakeBroker(nebenwirkung=lambda: (
        setattr(ON, "finde_java", lambda: "/usr/bin/java"),
        setattr(ON, "finde_tika", lambda: Path("/tmp/tika-app.jar")))))
    check("Anstoss meldet 'angestossen'", ON.einrichtung_anstossen("test") == "angestossen")
    check("der Hintergrund-Lauf endet (haengt nicht)", _warte_ende())
    check("⚠ es wird WIRKLICH eingerichtet: die Broker-Op tika_setup laeuft",
          [a["op"] for a in f.aufrufe] == ["tika_setup"], str(f.aufrufe))
    check("mit einem Zeitdeckel, der apt + 65 MB Download zulaesst",
          bool(f.aufrufe) and f.aufrufe[0]["timeout"] >= 600, str(f.aufrufe[:1]))
    check("die Op bekommt KEINEN Pfad als Argument (sonst waere sie shell_root)",
          bool(f.aufrufe) and not f.aufrufe[0]["args"], str(f.aufrufe[:1]))
    check("nach Erfolg ist kein Fehler vermerkt", ON.letzter_einrichtungsfehler() == "")

    # (4) Mindestabstand: ein zweiter Anstoss haemmert nicht gegen apt.
    _reset()
    f = _broker(_FakeBroker())
    ON.einrichtung_anstossen("erst")
    _warte_ende()
    zweit = ON.einrichtung_anstossen("gleich nochmal")
    _warte_ende()
    check("ein zweiter Anstoss laeuft in den Mindestabstand",
          "zu jung" in zweit and len(f.aufrufe) == 1, f"{zweit} / {len(f.aufrufe)}")
    check("WIEDERHOLUNG_S ist gesetzt und nicht null", ON.WIEDERHOLUNG_S >= 300)

    # (5) rc=0, aber auf Platte fehlt weiterhin etwas -> das ist ein FEHLER.
    #     Massgeblich ist der Zustand, nicht der Rueckgabewert des Skripts.
    _reset()
    f = _broker(_FakeBroker({"ok": True, "rc": 0}))
    ON.einrichtung_anstossen("test")
    _warte_ende()
    check("⚠ rc=0 ohne vorhandene Datei gilt NICHT als Erfolg",
          ON.letzter_einrichtungsfehler() != "", ON.letzter_einrichtungsfehler())

    # (6) Die Op steht aus (pending) -> der Grund nennt die Freigabe.
    _reset()
    _broker(_FakeBroker({"ok": False, "decision": "pending", "rc": None}))
    ON.einrichtung_anstossen("test")
    _warte_ende()
    check("eine ausstehende Root-Freigabe wird benannt",
          "Freigabe" in ON.letzter_einrichtungsfehler(), ON.letzter_einrichtungsfehler())

    # (7) Kein Broker und keine Root-Rechte -> HIER ist der Handweg richtig.
    _reset()
    f = _broker(_FakeBroker(modus="none"))
    ON.einrichtung_anstossen("test")
    _warte_ende()
    check("ohne Root-Weg wird der Handweg genannt (die einzige Ausnahme)",
          "tika_setup.sh" in ON.letzter_einrichtungsfehler() and not f.aufrufe,
          ON.letzter_einrichtungsfehler())

    # (8) Der Hintergrund-Lauf darf NIE werfen – sonst bleibt 'laeuft' stehen
    #     und es wird nie wieder eingerichtet.
    _reset()
    _broker(_FakeBroker(wirft=True))
    ON.einrichtung_anstossen("test")
    check("ein krachender Broker haengt die Automatik nicht auf", _warte_ende())
    check("und der Fehler ist vermerkt", ON.letzter_einrichtungsfehler() != "")

    # (9) DER WICHTIGSTE WEG: eine .one soll gelesen werden, Tika fehlt ->
    #     die Einrichtung laeuft an, OHNE dass jemand etwas anklickt.
    _reset()
    f = _broker(_FakeBroker())
    text, grund = paar(ON.text_aus_datei, FIXTURES / "abschnitt_2016.one")
    _warte_ende()
    check("⚠ eine unlesbare .one stoesst die Einrichtung selbst an",
          [a["op"] for a in f.aufrufe] == ["tika_setup"], str(f.aufrufe))
    check("und der Indexer bekommt trotzdem sofort seinen Grund (kein Warten)",
          text is None and isinstance(grund, str) and "automatisch" in grund.lower(),
          repr(grund)[:120])

    # (10) Bei 40 unlesbaren Dateien in einem Lauf trotzdem nur EIN apt-Lauf.
    _reset()
    f = _broker(_FakeBroker())
    for _ in range(5):
        paar(ON.text_aus_datei, FIXTURES / "abschnitt_2016.one")
    _warte_ende()
    check("fuenf unlesbare Dateien erzeugen EINEN Einrichtungslauf, nicht fuenf",
          len(f.aufrufe) == 1, str(len(f.aufrufe)))
finally:
    ON.finde_java, ON.finde_tika = _echt_java, _echt_tika
    ON._zustand.update({"laeuft": False, "letzter_start": 0.0,
                        "letzter_fehler": "", "versuche": 0})
    os.environ.pop("JARVIS_TIKA_AUTO", None)
    if _echt_broker is not None:
        sys.modules["backend.broker_client"] = _echt_broker
        backend.broker_client = _echt_broker
    else:
        sys.modules.pop("backend.broker_client", None)
        if hasattr(backend, "broker_client"):
            del backend.broker_client


# ─── Die Op selbst: auto-allow, kein Pfad aus Argumenten ─────────────────────
os.environ.setdefault("JARVIS_BROKER_POLICY", "/tmp/jarvis-test-policy.json")
os.environ.setdefault("JARVIS_BROKER_AUDIT", "/tmp/jarvis-test-audit.jsonl")
try:
    from backend.broker import ops as _ops
    _reg = getattr(_ops, "_REGISTRY", {})
    check("die Broker-Op 'tika_setup' ist registriert", "tika_setup" in _reg)
    check("sie ist auto-allow (System-Op, widerrufbar) – sonst haengt die "
          "Automatik an einer Admin-Freigabe",
          bool(_reg.get("tika_setup")) and _reg["tika_setup"][3] is True)
    check("der Status-Abruf ist ein reiner Lesevorgang (kein Audit-Rauschen)",
          "tika_status" in getattr(_ops, "READONLY_OPS", set()))
    import inspect as _insp
    _rumpf = ohne_kommentare_py(_insp.getsource(_ops._op_tika_setup))
    check("⚠ der Skriptpfad kommt NICHT aus den Argumenten",
          "args.get" not in _rumpf and "deploy" in _rumpf, _rumpf[:200])
except Exception as _e:  # noqa: BLE001
    check(f"Broker-Ops pruefbar ({type(_e).__name__})", False, str(_e)[:160])


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m11. Stille-Waechter statt festem Zeitdeckel\033[0m")
import inspect
import subprocess as _sp
import time
# ⚠ HIER WIRD DER ECHTE LESER AUSGEFUEHRT, mit echten Unterprozessen. Eine
# Quelltext-Pruefung koennte die Frage gar nicht beantworten, um die es geht:
# laeuft ein LANGSAMER, aber arbeitender Prozess durch - und ein HAENGENDER
# nicht? Das entscheidet sich im Ablauf, nicht im Wortlaut.


def _starte(shell_code):
    return _sp.Popen(["sh", "-c", shell_code], stdout=_sp.PIPE, stderr=_sp.PIPE,
                     start_new_session=True)


# (a) DER GEMELDETE FALL: laeuft weit laenger als der alte Deckel, gibt aber
#     regelmaessig aus. Gemessen an der echten 46-MB-Datei: 280 s Laufzeit,
#     laengste Pause 13,9 s - genau dieses Verhaeltnis, nur in klein.
_p = _starte('for i in 1 2 3 4 5 6; do echo "zeile $i"; sleep 1; done')
_aus, _err, _abbruch, _gelesen, _dauer = ON._lies_stroemend(_p, stille_s=3, gesamt_s=60)
check("ein langsamer, aber ARBEITENDER Lauf wird nicht abgebrochen",
      _abbruch is None, f"abbruch={_abbruch}")
check("er laeuft dabei laenger als seine Geduld je Pause (3 s)",
      _dauer > 4, f"dauer={_dauer:.1f}s")
check("und seine Ausgabe kommt VOLLSTAENDIG an",
      _aus.count(b"zeile") == 6, _aus[:80])
check("der Prozess ist danach beendet", _p.poll() is not None or _p.wait(5) is not None)

# (b) HAENGT: gibt einmal aus und verstummt dann.
_p = _starte('echo start; sleep 30')
_t0 = time.monotonic()
_aus, _err, _abbruch, _gelesen, _dauer = ON._lies_stroemend(_p, stille_s=2, gesamt_s=60)
_gebraucht = time.monotonic() - _t0
check("ein VERSTUMMTER Lauf wird abgebrochen", bool(_abbruch) and _abbruch[0] == "stille",
      f"abbruch={_abbruch}")
check("und zwar zuegig, nicht erst am Gesamtdeckel", _gebraucht < 10,
      f"{_gebraucht:.1f}s")
ON._abraeumen(_p)
check("der haengende Prozess ist danach tot", _p.poll() is not None)

# (c) STETIG, ABER ENDLOS: nur dafuer gibt es die harte Notbremse.
_p = _starte('while true; do echo tick; sleep 0.2; done')
_aus, _err, _abbruch, _gelesen, _dauer = ON._lies_stroemend(_p, stille_s=30, gesamt_s=3)
check("ein endloser Lauf faellt in die harte Obergrenze",
      bool(_abbruch) and _abbruch[0] == "gesamt", f"abbruch={_abbruch}")
ON._abraeumen(_p)

# (d) ⚠ KILLPG: Tika startet fuer die OCR echte tesseract-Prozesse. ``kill()``
#     allein laesst sie als Waisen weiterlaufen (Register).
_p = _starte('sleep 300 & echo $!; sleep 300')
_zeile = _p.stdout.readline().strip()
_enkel = int(_zeile) if _zeile.isdigit() else 0
ON._abraeumen(_p)
time.sleep(0.5)


def _lebt(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


check("das Abraeumen faellt die ganze PROZESSGRUPPE (Enkel inbegriffen)",
      _enkel > 0 and not _lebt(_enkel), f"enkel={_enkel} lebt={_lebt(_enkel) if _enkel else '?'}")

# (e) Lebenszeichen nach aussen - ohne das sieht ein Admin minutenlang nichts.
_meldungen = []
_p = _starte('for i in 1 2 3 4 5 6 7 8 9 10 11 12; do echo x; sleep 1; done')
ON._lies_stroemend(_p, stille_s=5, gesamt_s=60,
                   melde=lambda b, sek: _meldungen.append((b, sek)))
check("der Fortschritt wird nach aussen gemeldet", len(_meldungen) >= 2,
      f"{len(_meldungen)} Meldungen")
check("und er waechst mit (gelesene Bytes, Laufzeit)",
      bool(_meldungen) and _meldungen[-1][0] >= _meldungen[0][0] and _meldungen[-1][1] > 0,
      str(_meldungen[:3]))
# Ein Fehler im Callback des Aufrufers darf die Extraktion nicht killen.
# ⚠ Der Lauf MUSS laenger dauern als die Melde-Schwelle (5 s), sonst wird der
# Callback nie gerufen und die Pruefung ist trivial wahr - in der Gegenprobe
# genau so aufgefallen (+0 FAIL).
_rufe = []
_p = _starte('echo eins; sleep 7; echo zwei')


def _kaputt(_b, _s):
    _rufe.append(1)
    raise RuntimeError("Callback des Aufrufers kracht")


_aus, _, _abbruch, _, _ = ON._lies_stroemend(_p, stille_s=30, gesamt_s=60, melde=_kaputt)
check("Positivkontrolle: der krachende Callback wurde ueberhaupt gerufen",
      len(_rufe) >= 1, f"{len(_rufe)} Rufe")
check("ein krachender Fortschritts-Callback bricht die Extraktion NICHT ab",
      _abbruch is None and b"zwei" in _aus, f"abbruch={_abbruch} aus={_aus[:40]}")

# (f) stderr zaehlt als Lebenszeichen: waehrend der OCR schreibt Tika INFO-Zeilen.
#     Gefragt ist "arbeitet er noch", nicht "liefert er Nutztext".
_p = _starte('for i in 1 2 3 4 5 6; do echo warnung >&2; sleep 1; done; echo fertig')
_aus, _err, _abbruch, _, _ = ON._lies_stroemend(_p, stille_s=3, gesamt_s=60)
check("Ausgabe auf stderr haelt den Lauf am Leben",
      _abbruch is None and b"fertig" in _aus, f"abbruch={_abbruch}")

# (g) Die Zusage nach einem Abbruch: KEIN halber Text, der als vollstaendig gilt.
#     Ein Teiltext waere still verlorener Inhalt bei einer Datei, die danach als
#     erfolgreich indiziert gilt - der mtime-Cache verhindert jeden zweiten
#     Versuch (Register: ein Extraktor, der still Inhalt verliert, ist die
#     schlechteste Variante).
_quelle_te = ohne_kommentare_py(inspect.getsource(ON.text_aus_datei))
import ast as _ast


def _abbruchzweig_gibt_nur_none():
    """Jedes ``return`` im Abbruch-Zweig muss None als ersten Wert liefern."""
    # ⚠ NICHT die kommentarfreie Fassung: der Kommentar-Entferner zerlegt
    #   mehrzeilige Ausdruecke, und der AST braucht gueltige Syntax. Kommentare
    #   stoeren einen Syntaxbaum ohnehin nicht (Register).
    baum = _ast.parse(inspect.getsource(ON.text_aus_datei))
    fn = next(n for n in _ast.walk(baum) if isinstance(n, _ast.FunctionDef))
    for knoten in _ast.walk(fn):
        # Der Zweig, der auf ``abbruch`` prueft - egal wie er formuliert ist.
        if not isinstance(knoten, _ast.If):
            continue
        if "abbruch" not in _ast.dump(knoten.test):
            continue
        for r in (x for x in _ast.walk(knoten) if isinstance(x, _ast.Return)):
            wert = r.value
            erst = wert.elts[0] if isinstance(wert, _ast.Tuple) and wert.elts else wert
            if not (isinstance(erst, _ast.Constant) and erst.value is None):
                return False, _ast.dump(erst)[:120]
        return True, ""
    return False, "kein Zweig auf 'abbruch' gefunden"


_ok_zweig, _detail = paar(_abbruchzweig_gibt_nur_none) if False else _abbruchzweig_gibt_nur_none()
check("nach einem Abbruch gibt text_aus_datei None zurueck, nie einen Teiltext "
      "(ein halber Text gaelte als vollstaendig – der mtime-Cache verhindert "
      "jeden zweiten Versuch)", _ok_zweig, _detail)
check("der Grund nennt die gelesene Menge (500 KB und dann still ist ein "
      "anderes Problem als nie angefangen)",
      "KB gelesen" in _quelle_te)
check("und er nennt den Stellhebel", "JARVIS_ONENOTE_STILLE" in _quelle_te)

# (h) REGEL: kein communicate(timeout=) mehr im Extraktionspfad - es liest erst
#     am Ende und kann den Unterschied "arbeitet/haengt" gar nicht sehen.
check("⚠ der Extraktionspfad benutzt kein communicate(timeout=) mehr",
      "communicate(timeout" not in _quelle_te, _quelle_te[:0])


# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m12. Eingebettete XPS-Ausdrucke auspacken\033[0m")
# Die Zeilenform stammt 1:1 aus der Messung an der echten SAP-Anleitung von
# ECHT (2026-09-07) – der TEXT darin ist ersetzt: Kundennamen und Adressen
# gehoeren nicht in ein oeffentliches Repo.
_GLYPH = ('<Glyphs RenderTransform="0.166693,0,0,0.167,0,0" Fill="#ff000000" '
          'FontUri="/Documents/1/Resources/Fonts/C0E91E0F-DCB7-4047-919D-57162B6807CF.odttf" '
          'FontRenderingEmSize="96" OriginX="139.2" OriginY="187.68" '
          'UnicodeString="Die Angebotserstellung beginnt im Vorsystem " />')
_REL = ('><Relationship Target="/Documents/1/Resources/Fonts/'
        'C0E91E0F-DCB7-4047-919D-57162B6807CF.odttf" Id="R0" '
        'Type="http://schemas.microsoft.com/xps/2005/06/required-resource" />')
_STUECK = "Documents/1/Resources/Fonts/8656C6C5-278D-4CA4-9ABD-3D2CA2BBC848.odttf/[0].piece"

_t = sicher(ON._xps_auspacken, _GLYPH)
check("aus einer Glyphenzeile kommt der NUTZTEXT heraus",
      _t == "Die Angebotserstellung beginnt im Vorsystem", repr(_t)[:120])
check("und die Geometrie/GUIDs sind weg",
      isinstance(_t, str) and "odttf" not in _t and "RenderTransform" not in _t)
check("der Gewinn ist die Groessenordnung (5 % Nutztext in 95 % Struktur)",
      isinstance(_t, str) and len(_t) < len(_GLYPH) / 5, f"{len(_t)} von {len(_GLYPH)}")

check("XML-Entities werden aufgeloest",
      sicher(ON._xps_auspacken,
             '<Glyphs UnicodeString="Order &amp; Billing" />') == "Order & Billing")
check("mehrere Textstuecke einer Zeile werden verbunden",
      sicher(ON._xps_auspacken,
             '<Glyphs UnicodeString="Auftrag " /><Glyphs UnicodeString="anlegen" />')
      == "Auftrag anlegen")

check("reine Paketstruktur wird verworfen (leerer String, nicht None)",
      sicher(ON._xps_auspacken, _REL) == "")
check("ein Paketstueck-Pfad ebenfalls", sicher(ON._xps_auspacken, _STUECK) == "")

# ⚠ DIE GEGENRICHTUNG – dafuer sind es ZWEI Bedingungen. Eine Notiz, die ueber
# XML schreibt, darf nicht verstuemmelt werden; genau daran ist im Projekt
# schon einmal eine "kluge" Filterregel gescheitert (die Vokal-Regel).
check("eine Notiz UEBER XML bleibt unangetastet",
      sicher(ON._xps_auspacken,
             '<Relationship Id="rId1"> ist das Grundelement einer .rels-Datei') is None)
check("gewoehnlicher Text ist nicht betroffen (None = nicht zustaendig)",
      sicher(ON._xps_auspacken, "Vertragsbeginn 01.05.2025, Fakturasperre pruefen") is None)
check("ein Glyphs-Element OHNE Text ergibt kein Rauschen, sondern nichts",
      sicher(ON._xps_auspacken, '<Glyphs Indices="3,1" />') == "")

# Ende zu Ende durch saeubern(): der Nutztext bleibt, die Struktur faellt.
_roh = "\n".join([_GLYPH, _REL, _STUECK, "Handnotiz: Kontrakt pruefen"])
_sauber, _bilanz = paar(ON.saeubern, _roh)
check("saeubern() liefert den ausgepackten Text",
      isinstance(_sauber, str) and "Die Angebotserstellung beginnt im Vorsystem" in _sauber,
      repr(_sauber)[:140])
check("und die handgeschriebene Zeile daneben",
      isinstance(_sauber, str) and "Handnotiz: Kontrakt pruefen" in _sauber)
check("die Paketstruktur steht NICHT mehr im Ergebnis",
      isinstance(_sauber, str) and "odttf" not in _sauber and ".piece" not in _sauber,
      repr(_sauber)[:140])
check("die Bilanz weist die XPS-Zeilen aus (sonst sieht niemand, dass es wirkt)",
      isinstance(_bilanz, dict) and _bilanz.get("xps", 0) >= 3, str(_bilanz))

# ⚠ REIHENFOLGE: erst auspacken, dann Rauschfilter/Dubletten. Andersherum gilt
# eine 800-Zeichen-Glyphenzeile als einzigartiger Nutztext und schleppt ihre
# GUIDs in den Index - gemessen waren das 40 % der gesamten Textmasse.
_q_saeubern = ohne_kommentare_py(inspect.getsource(ON.saeubern))
_i_xps = _q_saeubern.find("_xps_auspacken")
_i_rausch = _q_saeubern.find("_ist_nutztext")
_i_dub = _q_saeubern.find("in gesehen")
check("das Auspacken steht VOR Rauschfilter und Dublettenpruefung",
      0 < _i_xps < _i_rausch and _i_xps < _i_dub,
      f"xps={_i_xps} rausch={_i_rausch} dub={_i_dub}")


# ═════════════════════════════════════════════════════════════════════════════
print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m"
      + (f"  \033[33m({UEBERSPRUNGEN} nicht geprueft – siehe oben)\033[0m" if UEBERSPRUNGEN else ""))
if FAIL:
    print(f"\033[31m{FAIL} Pruefung(en) fehlgeschlagen\033[0m")
sys.exit(1 if FAIL else 0)
