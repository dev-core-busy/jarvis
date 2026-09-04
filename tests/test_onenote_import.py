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
for _name in ("saeubern", "text_aus_datei", "finde_java", "finde_tika",
              "fehlender_baustein", "zeitdeckel", "jvm_heap"):
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
check("_extract_text_rest ruft text_aus_datei", "text_aus_datei(filepath)" in quelle_k)
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


def _attrappe(pfad, zeitlimit=None):
    spur.append(str(pfad))
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
check("Zeitdeckel wird nach unten UND oben begrenzt",
      isinstance(_deckel, int) and 10 <= _deckel <= 900, repr(_deckel))
alt = os.environ.get("JARVIS_ONENOTE_TIMEOUT")
try:
    os.environ["JARVIS_ONENOTE_TIMEOUT"] = "unfug"
    check("unbrauchbarer Zeitwert faellt auf die Vorgabe, statt zu werfen",
          sicher(lambda: ON.zeitdeckel()) == 120)
    os.environ["JARVIS_ONENOTE_TIMEOUT"] = "5"
    check("zu kleiner Zeitwert wird gehoben", sicher(lambda: ON.zeitdeckel()) == 10)
finally:
    os.environ.pop("JARVIS_ONENOTE_TIMEOUT", None)
    if alt is not None:
        os.environ["JARVIS_ONENOTE_TIMEOUT"] = alt

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

# Fehlt ein Baustein, MUSS der Hinweis den Weg nennen – nicht nur die Not.
alt_jar = os.environ.get("JARVIS_TIKA_JAR")
try:
    os.environ["JARVIS_TIKA_JAR"] = "/gibt/es/nicht/tika.jar"
    hinweis = sicher(ON.fehlender_baustein)
    check("fehlende Tika wird benannt", isinstance(hinweis, str) and "Tika" in hinweis, str(hinweis)[:90])
    check("der Hinweis nennt den WEG (tika_setup.sh)",
          isinstance(hinweis, str) and "tika_setup.sh" in hinweis)
    text, grund = paar(ON.text_aus_datei, FIXTURES / "abschnitt_2016.one")
    check("ohne Tika kommt None + Grund, nicht ein leerer Text",
          text is None and isinstance(grund, str) and "tika_setup.sh" in grund, repr(grund)[:90])
    check("_failure_reason gibt denselben Weg heraus",
          "tika_setup.sh" in str(sicher(K._unlesbar_grund, FIXTURES / "abschnitt_2016.one", 10 ** 9)))
finally:
    os.environ.pop("JARVIS_TIKA_JAR", None)
    if alt_jar is not None:
        os.environ["JARVIS_TIKA_JAR"] = alt_jar


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
check("der Fehlertext nennt den Weg", "tika_setup.sh" in i18n)
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
print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m"
      + (f"  \033[33m({UEBERSPRUNGEN} nicht geprueft – siehe oben)\033[0m" if UEBERSPRUNGEN else ""))
if FAIL:
    print(f"\033[31m{FAIL} Pruefung(en) fehlgeschlagen\033[0m")
sys.exit(1 if FAIL else 0)
