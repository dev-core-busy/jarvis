#!/usr/bin/env python3
"""PDF-Textqualitaet: erkennt eine beschaedigte Textebene und laesst OCR entscheiden.

DER VORFALL (2026-08-12, ECHT): ein 54-seitiges PDF lieferte ueber pdfplumber
80.586 Zeichen – die alte Schwelle "unter 80 Zeichen -> OCR" greift damit nie.
Der Text war aber teils unbrauchbar ("Datum: OL.O7.2026" statt "01.07.2026",
"ftir" statt "fuer", "Lauerstr.'14"), weil die Zeichentabelle der eingebetteten
Schriften beschaedigt ist. Das Modell hat daraufhin 17 Extraktionsskripte gebaut
und die Adressen trotzdem nicht saubergekriegt.

WAS DIESER TEST VOR ALLEM ABSICHERT, IST DIE ANDERE RICHTUNG: die Erkennung darf
NICHT bei gesundem Fachtext anschlagen. An 753 echten Dokumenten auf ECHT
gemessen schlug eine erste, breitere Fassung bei ICD-10-Codes ("O61.0"),
PPR-Pflegekategorien ("A4S1") und GUIDs ("43B3B851") an – alles korrekter Text.
In einer Klinikumgebung waere das ein Dauerfehlalarm gewesen, und OCR kostet
rund zwei Sekunden je Seite. Diese drei Faelle stehen deshalb woertlich drin.

``backend.config`` wird als Attrappe gelegt: der echte Import migriert beim
Laden die LIVE-``settings.json`` und schreibt sie zurueck.

Exit 2 = konnte nicht laufen (Import/Sandkasten), 1 = Pruefung fehlgeschlagen,
0 = bestanden.

    python3 tests/test_pdf_qualitaet.py
"""
import io
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n\033[1m{t}\033[0m")


# ── Attrappe fuer backend.config VOR dem Import ────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="pdfqs_test_"))
(TMP / "data").mkdir(parents=True)

_cfg = types.SimpleNamespace(
    KNOWLEDGE_DIR=str(TMP / "data" / "knowledge"),
    DATA_DIR=str(TMP / "data"),
    get_skill_config=lambda name: {},
    save_settings=lambda *a, **k: None,
)
_mod = types.ModuleType("backend.config")
_mod.config = _cfg
sys.modules["backend.config"] = _mod

try:
    from backend.tools import knowledge as kb
except Exception as e:                                    # pragma: no cover
    print(f"ABBRUCH: backend.tools.knowledge nicht importierbar ({e})")
    sys.exit(2)

# Sandkasten-Waechter: nichts darf auf das echte data/ des Repos zeigen.
for name in ("KNOWLEDGE_DIR",):
    wert = str(getattr(kb.config, name, ""))
    if wert and str(ROOT / "data") in wert:
        print(f"ABBRUCH: {name} zeigt auf das echte data/ ({wert})")
        sys.exit(2)


# ═══════════════════════════════════════════════════════════════════════════
section("1) Vorfilter: der gemeldete Schaden wird erkannt")

KAPUTT = """ngirrrsf#s$
NEXUS / DIGITAL PATHOLOGY GmbH
Zweigstelle
Lauerstr.'14
67697 Otterberg
Telefon: +49 2056.261 551
Dr. Datum: OL.O7.2026
Androshchuk, Miroslav
Praxis ftir Pathologie
Nemerowerstraße 4-6
D-17033 Neubrandenburg
Sehr geehrte Damen und Herren,
wir moechten Sie ueber die Anbindung informieren. Der Termin am O1.O7.2026
ist verbindlich. Bitte pruefen Sie die Angaben und senden Sie das Formular
ausgefuellt zurueck an die oben genannte Adresse.
"""
g = kb.pdf_text_verdacht(KAPUTT)
check(bool(g), "gemeldeter Text: Verdacht ausgeloest", str(g))
check("datum_verstuemmelt" in g, "verstuemmeltes Datum erkannt (OL.O7.2026)", str(g))
check("apostroph_vor_zahl_je_1k" in g, "Apostroph vor Hausnummer erkannt (Lauerstr.'14)", str(g))
# ZWEI unabhaengige Gruende – das ist die wichtigere Eigenschaft. Faellt ein
# Muster durch eine spaetere Verschaerfung gegen Fehlalarme weg, wird der Fall
# trotzdem noch erkannt.
check(len(g) >= 2, "mehr als ein Grund – die Erkennung haengt an keinem einzelnen", str(g))
# Die Logo-Zeile "ngirrrsf#s$" faengt die Muellzeilen-Regel NICHT: sie enthaelt
# ein 'i'. Bewusst nicht nachgeschaerft – die Regel loeste auf ECHT bereits bei
# 20 gesunden Dokumenten aus, und jeder Fehlalarm kostet die OCR-Stichprobe.
check(not kb.pdf_text_verdacht("x" * 300 + "\nngirrrsf#s$\n").get("muellzeilen"),
      "Logo-Zeile mit Vokal gilt NICHT als Muellzeile (bekannte Grenze)")
check(kb.pdf_text_verdacht("Sehr geehrte Damen und Herren, " * 12
                           + "\n###§$%rtzfgh\n").get("muellzeilen") == 1,
      "eine Zeile ganz ohne Vokal wird dagegen erkannt")

# ═══════════════════════════════════════════════════════════════════════════
section("2) KEIN Fehlalarm bei echtem Fachtext (an 753 Dokumenten gemessen)")

GESUND = {
    "ICD-10-Codes": """Die Diagnose O61.0 Geburtseinleitung wird erfasst.
Weitere Schluessel: I10 Hypertonie, L40.0 Psoriasis, O80 Spontangeburt.
Geschlecht: weiblich, Alter: 12-55 Jahre. Erfassung erfolgt im Modul.
Die Kodierung richtet sich nach den Vorgaben des DIMDI fuer das Jahr 2025.""",
    "PPR-Pflegekategorien": """Die Pflegekategorien A4S1, A4S2 und A4S3 bilden das
kalkulatorische Aequivalent zu den ueber die Pflegepersonalregelung
ermittelten Werten. Behandlungsfaelle werden entsprechend eingestuft.
Die Einstufung erfolgt automatisch anhand der dokumentierten Leistungen.""",
    "GUID / Kennungen": """Der Aufruf erfolgt mit der Kennung "{43B3B851…}", mit
entsprechender URL und Uebergabeparametern. Die Konfiguration wird in der
Datei hinterlegt. Weitere Kennungen: 7F2A9C41, B3D8E017, 2C4F6A88.
Bitte pruefen Sie die Eintraege vor der Uebernahme in das Produktivsystem.""",
    "Paragraphen und Zahlen": """Nach § 301 SGB V erfolgt die Datenuebermittlung.
Die Abrechnung nach § 21 KHEntgG 2024 umfasst 1.216.500 EUR bei 12.480
Behandlungsfaellen. Der Stichtag ist der 31.12.2025, Version 2.4 ab 01.01.2026.
Die Werte wurden am 15.03.2025 durch das Institut bestaetigt.""",
    "Normaler Brieftext": """Sehr geehrte Damen und Herren,
hiermit bestaetigen wir den Eingang Ihrer Unterlagen vom 12.08.2026.
Die Bearbeitung erfolgt innerhalb von 14 Tagen. Bei Rueckfragen erreichen
Sie uns unter der Telefonnummer 06301 123456 oder per E-Mail.
Mit freundlichen Gruessen""",
}
for name, txt in GESUND.items():
    g = kb.pdf_text_verdacht(txt)
    check(not g, f"kein Verdacht: {name}", str(g))

check(not kb.pdf_text_verdacht("kurz"), "zu kurzer Text loest nichts aus")
check(not kb.pdf_text_verdacht(""), "leerer Text loest nichts aus")

# Die Regex selbst: die drei Muster duerfen NICHT treffen
check(not kb._TQ_INNEN.search("O61.0"),
      "ICD-10 O61.0 trifft die Ziffer-Buchstabe-Regel nicht")
check(not kb._TQ_INNEN.search("A4S1"),
      "PPR-Kategorie A4S1 trifft die Regel nicht (S ist ausgenommen)")
check(not kb._TQ_INNEN.search("43B3B851"),
      "GUID 43B3B851 trifft die Regel nicht (B ist ausgenommen)")
check(bool(kb._TQ_INNEN.search("2O26")),
      "aber 2O26 (O zwischen Ziffern) trifft sehr wohl")

# ═══════════════════════════════════════════════════════════════════════════
section("3) Guetemass: zaehlt, was man am Ende braucht")

g_kaputt = kb.text_guete(KAPUTT)
SAUBER = KAPUTT.replace("OL.O7.2026", "01.07.2026").replace("O1.O7.2026", "01.07.2026") \
               .replace("Lauerstr.'14", "Lauerstr. 14").replace("ftir", "fuer") \
               .replace("ngirrrsf#s$", "nexus lab")
g_sauber = kb.text_guete(SAUBER)
check(g_sauber["struktur"] > g_kaputt["struktur"],
      "saubere Fassung findet mehr Strukturdaten",
      f"{g_kaputt['struktur']} -> {g_sauber['struktur']}")
check(kb.text_guete("")["struktur"] == 0, "leerer Text: keine Strukturtreffer")

hat_liste = bool(kb._wortliste())
print(f"     (Wortliste vorhanden: {hat_liste})")

# ═══════════════════════════════════════════════════════════════════════════
section("4) Entscheidungsregel _ocr_gewinnt – fail-closed")

check(not kb._ocr_gewinnt({"struktur": 10, "wortquote": 70.0},
                          {"struktur": 10, "wortquote": 70.0}, True),
      "Gleichstand: OCR gewinnt NICHT")
check(not kb._ocr_gewinnt({"struktur": 10, "wortquote": 76.5},
                          {"struktur": 12, "wortquote": 59.2}, True),
      "mehr Struktur, aber viel schlechtere Woerter: OCR gewinnt NICHT "
      "(der gemessene gesunde Fall)")
check(kb._ocr_gewinnt({"struktur": 21, "wortquote": 58.6},
                      {"struktur": 37, "wortquote": 61.4}, True),
      "der gemessene Schadensfall: OCR gewinnt")
check(not kb._ocr_gewinnt({"struktur": 21, "wortquote": 58.6},
                          {"struktur": 22, "wortquote": 58.6}, True),
      "ein einzelner Strukturtreffer mehr genuegt nicht")
check(not kb._ocr_gewinnt({"struktur": 0, "wortquote": 50.0},
                          {"struktur": 0, "wortquote": 55.0}, False),
      "ohne Wortliste zaehlt allein die Struktur")
check(kb._ocr_gewinnt({"struktur": 4, "wortquote": 0.0},
                      {"struktur": 12, "wortquote": 0.0}, False),
      "ohne Wortliste: deutlich mehr Struktur genuegt")

# ═══════════════════════════════════════════════════════════════════════════
section("5) Ablauf: kein Inhaltsverlust, Abschaltbarkeit")

seiten = ["Seite eins mit Text", "", "Seite drei mit Text"]
erg, ber = kb.pdf_qualitaet_sichern(b"%PDF-1.4", seiten)
check(erg == seiten, "unauffaellige Seiten bleiben unveraendert")
check(ber["seiten_gesamt"] == 3, "Seitenzahl im Bericht", str(ber))
check(not ber["ocr"], "kein OCR ohne Verdacht", str(ber))

erg, ber = kb.pdf_qualitaet_sichern(b"", [])
check(erg == [] and not ber["ocr"], "leeres Dokument: kein Absturz")

# Verdacht, aber OCR liefert nichts (kein poppler/tesseract im Test) ->
# die Textebene MUSS erhalten bleiben.
alt = kb._ocr_pdf_seiten
kb._ocr_pdf_seiten = lambda *a, **k: {}
try:
    erg, ber = kb.pdf_qualitaet_sichern(b"%PDF", [KAPUTT])
    check(erg == [KAPUTT], "OCR nicht verfuegbar: Textebene bleibt unveraendert")
    check("nicht verfuegbar" in ber["grund"], "Grund wird benannt", ber["grund"])
    check(not ber["ocr"], "und es gilt NICHT als OCR-Lauf")
finally:
    kb._ocr_pdf_seiten = alt

# Abschaltbar
alt_aktiv = kb._PDF_QS_AKTIV
kb._PDF_QS_AKTIV = False
try:
    erg, ber = kb.pdf_qualitaet_sichern(b"%PDF", [KAPUTT])
    check(erg == [KAPUTT] and ber["grund"] == "abgeschaltet",
          "JARVIS_PDF_QS=0 schaltet die Pruefung ab", str(ber))
finally:
    kb._PDF_QS_AKTIV = alt_aktiv

# ═══════════════════════════════════════════════════════════════════════════
section("6) Seitenweise Mischung – der OCR-Text landet auf der RICHTIGEN Seite")

# Genau der Fehler, den die lueckenlose Seitenliste verhindert: haette man
# leere Seiten uebersprungen, laege der OCR-Text von Seite 3 auf Seite 2.
gefaelscht = {1: "Seite eins per OCR sauber 01.07.2026 info@example.de 67697",
              3: "Seite drei per OCR sauber 02.07.2026 post@example.de 42579"}
kb._ocr_pdf_seiten = lambda b, e=1, l=20: (
    {k: v for k, v in gefaelscht.items() if e <= k <= l} if l > 1
    else {e: gefaelscht.get(e, "")} if gefaelscht.get(e) else {})
try:
    quelle = [KAPUTT, "", "Dr. Datum: OL.O7.2026 Praxis ftir Pathologie 42579 Ort"]
    erg, ber = kb.pdf_qualitaet_sichern(b"%PDF", quelle)
    check(ber["ocr"], "OCR wurde angewandt", str(ber.get("grund")))
    check(erg[0].startswith("Seite eins per OCR"),
          "Seite 1 ersetzt", erg[0][:40])
    check(erg[2].startswith("Seite drei per OCR"),
          "Seite 3 ersetzt – NICHT auf Index 1 verrutscht", erg[2][:40])
    check(erg[1] == "", "die leere Seite 2 bleibt leer", repr(erg[1]))
    check(len(erg) == 3, "Seitenzahl unveraendert")
finally:
    kb._ocr_pdf_seiten = alt

# ═══════════════════════════════════════════════════════════════════════════
section("7) Deckel: was NICHT geprueft wurde, wird AUSGEWIESEN")

alt_max = kb._PDF_QS_MAX_SEITEN
kb._PDF_QS_MAX_SEITEN = 2
# Der gefaelschte OCR-Text muss ECHTER Text sein: eine wortarme Attrappe laesst
# die Wortquote einbrechen, und dann lehnt die Schutzregel korrekt ab – der Test
# haette dann den Deckel geprueft und in Wahrheit die Ablehnung gemessen.
_OCR_SEITE = (SAUBER + "\nDie Unterlagen wurden vollstaendig geprueft und "
              "koennen zur weiteren Bearbeitung freigegeben werden. Bitte "
              "beachten Sie die beigefuegten Hinweise zur Anbindung.\n"
              "Rueckfragen richten Sie an unsere Zweigstelle.")
kb._ocr_pdf_seiten = lambda b, e=1, l=20: {
    n: f"Seite {n} per OCR.\n{_OCR_SEITE}" for n in range(e, min(l, 2) + 1)}
try:
    quelle = [KAPUTT] * 5
    erg, ber = kb.pdf_qualitaet_sichern(b"%PDF", quelle)
    check(ber.get("nicht_geprueft_ab") == 3,
          "ab Seite 3 wurde nicht geprueft – steht im Bericht", str(ber))
    check(erg[4] == KAPUTT, "Seite 5 traegt weiter die Textebene (kein Verlust)")
    h = kb.qualitaets_hinweis(ber)
    check("Ab Seite 3" in h, "der Hinweis sagt es dem Modell", h)
    check("Texterkennung" in h, "und nennt den Grund", h)
    # Am echten PDF gemessen: OCR liefert deutlich mehr, aber eigene Lesefehler
    # ("auftrag@ibsvS.de" statt "ibsv3"). Ein Hinweis, der nur "per OCR gelesen"
    # sagt, suggeriert einen sauberen Text.
    check("Lesefehler" in h, "der Hinweis warnt vor OCR-eigenen Lesefehlern", h)
    check("pruefen" in h.lower(), "und fordert zur Pruefung am Original auf", h)
finally:
    kb._PDF_QS_MAX_SEITEN = alt_max
    kb._ocr_pdf_seiten = alt

check(kb.qualitaets_hinweis({"ocr": False}) == "",
      "ohne OCR gibt es keinen Hinweis (kein Rauschen im Prompt)")

# ═══════════════════════════════════════════════════════════════════════════
section("8) Verdrahtung im Quelltext")

kq = (ROOT / "backend" / "tools" / "knowledge.py").read_text(encoding="utf-8")
mq = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")

check("def pdf_text_mit_bericht" in kq, "knowledge.py: Funktion mit Bericht vorhanden")
check("pdf_qualitaet_sichern(filepath.read_bytes(), seiten)" in kq,
      "die Pruefung bekommt die LUECKENLOSE Seitenliste, nicht texts",
      "sonst verrutschen die Seiten")
check("seiten.append(t or \"\")" in kq, "leere Seiten werden mitgefuehrt")
check("_kb.pdf_text_mit_bericht(_tmp)" in mq, "main.py nutzt den Weg mit Bericht")
check("_pdf_text, _pdf_hinweis = await asyncio.to_thread" in mq,
      "main.py nimmt Text UND Hinweis entgegen")
check("_vorspann}{_pdf_text}" in mq, "der Hinweis steht VOR dem Inhalt")
# Die alte Schwelle bleibt als Rueckfall fuer echte Scans erhalten.
check("len(combined.strip()) < 80" in kq,
      "der Rueckfall fuer PDFs ohne Text-Layer bleibt bestehen")

print(f"\n{_ok} ok, {_fail} Fehler ({_ok + _fail} Pruefungen)")
sys.exit(1 if _fail else 0)
