#!/usr/bin/env python3
"""Waechter: die OCR im Wissens-Suchpfad ist BEGRENZT.

⚠ AUF ECHT BEZAHLT (2026-09-24, ~15:00): 116 neue PDFs standen zur Indizierung
an, der Suchpfad arbeitete sie in 10er-Haeppchen ab (INLINE_LIMIT). Gemessen am
Journal: 14:32:44 "116 neue/geaenderte Dateien", 14:35:45 "109" - also 7 Dateien
in 3 Minuten, rund 26 s je Datei auf einem 4-Kern-Server, waehrend mehrere
Benutzer gleichzeitig suchten. Die CPU lag bei 100 %.

URSACHE: ``pytesseract.image_to_string`` startet tesseract mit der GEERBTEN
Umgebung. Tesseract parallelisiert sich intern ueber OpenMP und belegt ALLE
Kerne; mehrere gleichzeitige Erkennungen kaempfen um dieselben und werden
langsamer statt schneller. Zwei andere Module dieses Projekts hatten die
Begrenzung laengst samt Messung (pdf_formular.py: 69,1 s ohne gegen 4,5 s mit,
Faktor 15) - ausgerechnet im heissen Pfad jeder ``knowledge_search`` fehlte sie.

GEPRUEFT WIRD DIE EIGENSCHAFT, NICHT EIN VORKOMMEN:
  * Abschnitt 2 ist eine REGEL ueber den AST: JEDER tesseract-Aufruf in
    knowledge.py traegt ``env`` MIT OMP_THREAD_LIMIT UND ein ``timeout``.
    Damit faellt auch eine KUENFTIGE Aufrufstelle auf, ohne dass jemand eine
    Liste pflegt.
  * Abschnitt 4 FUEHRT die echten Funktionen aus (tesseract ist auf DEV und
    ECHT vorhanden) - ob am Ende wirklich eine begrenzte Umgebung ankommt,
    kann eine Quelltext-Suche nicht beantworten.

⚠ DER KOMMENTARFILTER IST HIER PFLICHT: der Begruendungsblock in knowledge.py
nennt "image_to_string", "pytesseract" und "OMP_THREAD_LIMIT" woertlich. Ohne
das Entfernen von Kommentaren UND Docstrings liest der Waechter seine eigene
Erklaerung (im Projekt achtzehnmal bezahlt).
"""
import ast
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
KNOW = WURZEL / "backend" / "tools" / "knowledge.py"
BILD = WURZEL / "backend" / "tools" / "bild_text.py"
FORM = WURZEL / "skills" / "office" / "pdf_formular.py"

_ok = 0
_fail = 0


def check(text, bedingung, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{detail}]" if detail else ""))


def sicher(fn, *a, **kw):
    """Nie ungeprueft dereferenzieren - ein Wurf beendet den Lauf sonst OHNE
    Bilanzzeile, und das ist von 'nicht gelaufen' nicht zu unterscheiden."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return f"<WURF {type(e).__name__}: {e}>"


def ohne_worte(quelle: str) -> str:
    """Kommentare UND Docstrings entfernen.

    ``tokenize`` kennt nur ``#``-Kommentare - die Begruendungen dieses Projekts
    stehen ueberwiegend in Docstrings. Beide muessen weg, sonst prueft der
    Waechter seinen eigenen Erklaerungstext.
    """
    baum = ast.parse(quelle)
    weg = []
    for k in ast.walk(baum):
        if isinstance(k, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            leib = getattr(k, "body", None)
            if leib and isinstance(leib[0], ast.Expr) and isinstance(leib[0].value, ast.Constant) \
                    and isinstance(leib[0].value.value, str):
                weg.append((leib[0].lineno, leib[0].end_lineno))
    zeilen = quelle.splitlines(keepends=True)
    for a, b in weg:
        for i in range(a - 1, b):
            zeilen[i] = "\n"
    text = "".join(zeilen)
    aus = list(text)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                (z1, s1), (z2, s2) = tok.start, tok.end
                if z1 == z2:
                    versatz = sum(len(l) for l in text.splitlines(keepends=True)[:z1 - 1])
                    for i in range(versatz + s1, versatz + s2):
                        aus[i] = " "
    except tokenize.TokenError:
        pass
    return "".join(aus)


print("\n=== 1. Namens-Guard (gegen den Altstand bricht der Lauf sonst ohne Bilanz ab) ===")
QUELL = KNOW.read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)
NAMEN = {n.name for n in BAUM.body if isinstance(n, ast.FunctionDef)}
for noetig in ("_ocr_datei", "_ocr_zeitdeckel", "_ocr_image", "_ocr_sprachen"):
    check(f"{noetig} existiert", noetig in NAMEN,
          "Altstand? Dann sind die uebrigen Pruefungen gegenstandslos")
if "_ocr_datei" not in NAMEN:
    print(f"\nERGEBNIS: {_ok} OK, {_fail} FAIL  (ABBRUCH: Altstand)")
    sys.exit(1)

OHNE = ohne_worte(QUELL)
check("Positivkontrolle: der Filter hat wirklich etwas entfernt",
      len(OHNE) < len(QUELL) - 2000, f"{len(QUELL)} -> {len(OHNE)}")
check("Positivkontrolle: Code bleibt stehen", "def _ocr_datei" in OHNE)
check("Positivkontrolle: die Begruendung ist weg",
      "belegt damit ALLE" not in OHNE and "Faktor 15" not in OHNE)

print("\n=== 2. REGEL: jeder tesseract-Aufruf ist begrenzt ===")
# Gemessen wird am AST, nicht am Text: gesucht sind subprocess.run-Aufrufe,
# deren erstes Argument eine Liste ist, die mit "tesseract" beginnt.
BAUM_OHNE = ast.parse(OHNE)


def _liste_mit_tesseract(k):
    """Ist dieser Knoten eine Liste, die mit 'tesseract' beginnt?"""
    return (isinstance(k, ast.List) and k.elts
            and isinstance(k.elts[0], ast.Constant) and k.elts[0].value == "tesseract")


def _tesseract_laeufe(fn):
    """Alle subprocess.run-Aufrufe in DIESER Funktion, die tesseract starten.

    ⚠ DIE HERKUNFT DER VARIABLEN GEHOERT MITVERFOLGT. Der eigentliche
    OCR-Aufruf baut seinen Befehl erst in einer Variablen zusammen
    (``befehl = ["tesseract", ...]``) und uebergibt dann diesen Namen - eine
    Regel, die nur auf ein Listen-Literal AM AUFRUF sieht, findet ausgerechnet
    die teure Stelle NICHT und prueft nur die harmlose --list-langs-Abfrage.
    Genau so war die erste Fassung dieses Waechters zahnlos.
    """
    # 1. Namen sammeln, denen in dieser Funktion eine tesseract-Liste zugewiesen wird
    namen = set()
    for k in ast.walk(fn):
        if isinstance(k, ast.Assign) and _liste_mit_tesseract(k.value):
            for z in k.targets:
                if isinstance(z, ast.Name):
                    namen.add(z.id)
        if isinstance(k, ast.AugAssign) and isinstance(k.target, ast.Name):
            pass                      # befehl += [...] erweitert nur, Ursprung zaehlt
    # 2. Aufrufe finden
    aus = []
    for k in ast.walk(fn):
        if not (isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
                and k.func.attr == "run" and k.args):
            continue
        erst = k.args[0]
        if _liste_mit_tesseract(erst) or (isinstance(erst, ast.Name) and erst.id in namen):
            aus.append((k, erst))
    return aus


laeufe = []
for fn in ast.walk(BAUM_OHNE):
    if isinstance(fn, ast.FunctionDef):
        laeufe += [(fn.name, k, erst) for k, erst in _tesseract_laeufe(fn)]

# ⚠ MINDESTENS ZWEI: die Spracherkennung (--list-langs) UND der eigentliche
# OCR-Lauf. Findet der Waechter nur einen, hat er den teuren uebersehen.
check("beide tesseract-Aufrufe gefunden (Abfrage UND Erkennung)", len(laeufe) >= 2,
      f"{len(laeufe)} gefunden: {[n for n, _, _ in laeufe]}")

for fname, k, erst in laeufe:
    args = {kw.arg for kw in k.keywords}
    # --list-langs ist eine Abfrage ohne Rechenarbeit - sie braucht kein
    # OMP-Limit, aber sehr wohl einen Deckel (ein haengender Aufruf im
    # Suchpfad ist auch dort teuer).
    ist_abfrage = _liste_mit_tesseract(erst) and any(
        isinstance(e, ast.Constant) and e.value == "--list-langs" for e in erst.elts)
    art = "Abfrage" if ist_abfrage else "ERKENNUNG"
    check(f"{fname} ({art}): timeout gesetzt", "timeout" in args)
    if not ist_abfrage:
        check(f"{fname} ({art}): eigene env uebergeben", "env" in args)

check("mindestens eine ERKENNUNG (nicht nur Abfragen) geprueft",
      any(not (_liste_mit_tesseract(e) and any(
          isinstance(x, ast.Constant) and x.value == "--list-langs" for x in e.elts))
          for _, _, e in laeufe),
      "sonst misst Abschnitt 2 nur die harmlose Sprachabfrage")

# Die env muss OMP_THREAD_LIMIT tragen - und zwar aus _OCR_UMGEBUNG.
check("_OCR_UMGEBUNG traegt OMP_THREAD_LIMIT", "OMP_THREAD_LIMIT" in OHNE)
check("die Erkennung nutzt _OCR_UMGEBUNG", "_OCR_UMGEBUNG" in OHNE)

print("\n=== 3. Keine globale Umgebung, kein pytesseract im OCR-Weg ===")
# os.environ["OMP..."] = ... waere prozessweit und traefe Embeddings und
# Bildmodelle im selben Dienst mit.
setzt_global = False
for k in ast.walk(BAUM_OHNE):
    if isinstance(k, ast.Assign):
        for z in k.targets:
            if isinstance(z, ast.Subscript) and isinstance(z.value, ast.Attribute) \
                    and z.value.attr == "environ":
                setzt_global = True
check("os.environ wird NICHT global gesetzt", not setzt_global,
      "eine globale Variable traefe auch Embeddings/Bildmodelle")
check("kein image_to_string mehr (pytesseract startet mit geerbter Umgebung)",
      "image_to_string" not in OHNE)
check("dict(os.environ) wird kopiert (TESSDATA_PREFIX bleibt erhalten)",
      "dict(os.environ)" in OHNE)

print("\n=== 4. Zeitdeckel ist eine FUNKTION, keine Konstante ===")
check("_ocr_zeitdeckel ist eine Funktion", "_ocr_zeitdeckel" in NAMEN,
      "eine Modul-Konstante waere bis zum Dienstneustart eingefroren")

print("\n=== 5. Die Plakette haengt am PROGRAMM, nicht am Python-Paket ===")
# Wer weiter pytesseract verlangt, meldet 'OCR nicht verfuegbar' fuer eine OCR,
# die laeuft - eine Anzeige, die einen Zustand behauptet, den sie nicht hat.
# ⚠ GEZIELT DIE FUNKTION SCHNEIDEN: 'which("tesseract")' steht auch in der
# Formatliste weiter unten. Ueber die ganze Datei gesucht bleibt die Pruefung
# gruen, waehrend die Verfuegbarkeits-Weiche sabotiert ist (Gegenprobe war stumm).
_stat = next((ast.get_source_segment(OHNE, n) for n in ast.walk(BAUM_OHNE)
              if isinstance(n, ast.FunctionDef) and n.name == "_get_static_stats"), None)
check("Positivkontrolle: _get_static_stats geschnitten", bool(_stat))
if _stat:
    check("has_image haengt an shutil.which('tesseract')", 'which("tesseract")' in _stat)
    check("has_image haengt NICHT mehr an import pytesseract",
          "pytesseract" not in _stat)
check("Plakettentext verlangt kein pytesseract mehr",
      "pytesseract nötig" not in QUELL and "pytesseract noetig" not in QUELL)

print("\n=== 6. DRIFT: alle drei OCR-Module begrenzen gleich ===")
for datei in (BILD, FORM):
    q = sicher(lambda d=datei: ohne_worte(d.read_text(encoding="utf-8")))
    check(f"{datei.name}: OMP_THREAD_LIMIT vorhanden",
          isinstance(q, str) and "OMP_THREAD_LIMIT" in q, str(q)[:80])

print("\n=== 7. AUSGEFUEHRT: die Begrenzung kommt wirklich an ===")
if not shutil.which("tesseract"):
    check("tesseract vorhanden (sonst NICHT PRUEFBAR)", False,
          "auf DEV und ECHT installiert - hier nicht, Abschnitt uebersprungen")
else:
    schnitt = {}
    noetig = {"_ocr_zeitdeckel", "_ocr_datei", "_ocr_image", "_ocr_sprachen"}
    for n in BAUM.body:
        if isinstance(n, ast.FunctionDef) and n.name in noetig:
            schnitt[n.name] = ast.get_source_segment(QUELL, n)

    def _ziel(n):
        if isinstance(n, ast.Assign):
            return [getattr(t, "id", "") for t in n.targets]
        if isinstance(n, ast.AnnAssign):
            return [getattr(n.target, "id", "")]
        return []

    konst = [ast.get_source_segment(QUELL, n) for n in BAUM.body
             if set(_ziel(n)) & {"_OCR_UMGEBUNG", "_ocr_sprachen_cache"}]
    check("Schnitt vollstaendig (4 Funktionen + 2 Konstanten)",
          len(schnitt) == 4 and len(konst) == 2,
          f"{len(schnitt)}/{len(konst)}")

    import logging
    ns = {"os": os, "subprocess": subprocess, "shutil": shutil,
          "tempfile": tempfile, "Path": Path, "_log": logging.getLogger("waechter")}
    # ⚠ DER exec DARF DEN LAUF NICHT BEENDEN. Faellt der Schnitt gegen einen
    # sabotierten Stand aus (fehlende Funktion, Import im Rumpf), waere ein
    # Abbruch OHNE Bilanzzeile von 'nicht gelaufen' nicht zu unterscheiden -
    # und die Gegenprobe koennte nicht beurteilen, ob sie gebissen hat.
    _exec_ok = True
    try:
        exec("\n".join(konst + list(schnitt.values())), ns)  # noqa: S102
    except Exception as e:  # noqa: BLE001
        _exec_ok = False
        check("der geschnittene OCR-Weg laesst sich ueberhaupt laden", False,
              f"{type(e).__name__}: {e}")

    sand = tempfile.mkdtemp(prefix="ocrtest_")
    try:
        if not _exec_ok:
            raise RuntimeError("Schnitt nicht ladbar - Ausfuehrungsteil uebersprungen")
        from PIL import Image, ImageDraw
        bild = os.path.join(sand, "probe.png")
        img = Image.new("RGB", (900, 200), "white")
        ImageDraw.Draw(img).text((30, 70), "Rechnung 12345 Muster GmbH", fill="black")
        img.save(bild)

        # Positivkontrolle: die OCR muss ueberhaupt etwas liefern, sonst sind
        # alle Aussagen darunter trivial wahr.
        # ⚠ ns[...] NIE ungeprueft: fehlt der Name (umbenannt) oder wirft der
        # Aufruf (ein Import im Rumpf, den es hier nicht gibt), endet der Lauf
        # OHNE Bilanzzeile - von "nicht gelaufen" ununterscheidbar.
        _bild_ocr = ns.get("_ocr_image")
        check("_ocr_image ist im Schnitt aufrufbar", callable(_bild_ocr))
        if not callable(_bild_ocr):
            _bild_ocr = lambda *_a, **_k: None          # noqa: E731
        text = sicher(_bild_ocr, Path(bild))
        check("Positivkontrolle: OCR erkennt den Text",
              isinstance(text, str) and "Rechnung" in text, str(text)[:60])

        # Der Kern: was kommt wirklich bei subprocess an?
        echt = subprocess.run
        gesehen = {}

        def spion(cmd, **kw):
            if cmd and cmd[0] == "tesseract" and "stdout" in cmd:
                gesehen["omp"] = (kw.get("env") or {}).get("OMP_THREAD_LIMIT")
                gesehen["timeout"] = kw.get("timeout")
                gesehen["envn"] = len(kw.get("env") or {})
            return echt(cmd, **kw)

        ns["subprocess"].run = spion
        sicher(_bild_ocr, Path(bild))
        ns["subprocess"].run = echt

        check("OMP_THREAD_LIMIT=1 kommt am Prozess an", gesehen.get("omp") == "1",
              repr(gesehen.get("omp")))
        check("ein timeout kommt am Prozess an", isinstance(gesehen.get("timeout"), int)
              and gesehen["timeout"] > 0, repr(gesehen.get("timeout")))
        check("die Umgebung ist NICHT minimal (TESSDATA_PREFIX & Co. bleiben)",
              (gesehen.get("envn") or 0) > 5, f"{gesehen.get('envn')} Variablen")
        check("os.environ des Dienstes bleibt unberuehrt",
              "OMP_THREAD_LIMIT" not in os.environ)

        # Gegenrichtungen: kein Wurf, und leer heisst None (der Negativ-Cache
        # im Aufrufer haengt an None, nicht an "").
        leer = os.path.join(sand, "leer.png")
        Image.new("RGB", (300, 120), "white").save(leer)
        check("leeres Bild -> None (nicht '')", sicher(_bild_ocr, Path(leer)) is None)
        kaputt = os.path.join(sand, "kaputt.png")
        Path(kaputt).write_bytes(b"kein bild")
        check("kaputte Datei -> None statt Wurf",
              sicher(_bild_ocr, Path(kaputt)) is None)

        # Der Deckel selbst
        # ⚠ NIE ungeprueft aus dem Namensraum greifen: fehlt die Funktion (weil
        # sie jemand umbenannt oder zur Konstante gemacht hat), wirft ns[...] und
        # der Lauf endet OHNE Bilanzzeile - von "nicht gelaufen" ununterscheidbar.
        _deckel = ns.get("_ocr_zeitdeckel")
        check("_ocr_zeitdeckel ist im Schnitt aufrufbar", callable(_deckel))
        vorher = os.environ.pop("JARVIS_OCR_TIMEOUT", None)
        try:
            for wert, erwartet, was in ((None, 120, "Vorgabe-Zeitdeckel 120 s"),
                                        ("45", 45, "ENV setzt den Deckel"),
                                        ("abc", 120, "unbrauchbarer ENV-Wert -> Vorgabe (nicht 0)"),
                                        ("999999", 120, "ausserhalb der Grenzen -> Vorgabe")):
                if wert is None:
                    os.environ.pop("JARVIS_OCR_TIMEOUT", None)
                else:
                    os.environ["JARVIS_OCR_TIMEOUT"] = wert
                got = sicher(_deckel) if callable(_deckel) else "<keine Funktion>"
                check(was, got == erwartet, repr(got))
        finally:
            os.environ.pop("JARVIS_OCR_TIMEOUT", None)
            if vorher is not None:
                os.environ["JARVIS_OCR_TIMEOUT"] = vorher
    except RuntimeError as e:
        print(f"  ..   Ausfuehrungsteil uebersprungen: {e}")
    finally:
        shutil.rmtree(sand, ignore_errors=True)

print(f"\nERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
