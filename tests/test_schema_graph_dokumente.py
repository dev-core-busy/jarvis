#!/usr/bin/env python3
"""Waechter: Begleitdokumente des SQL-Assistenten – DOCX und PDF WIRKLICH gelesen.

Der Graph-Waechter (``test_schema_graph.py``) prueft die Kette mit Markdown,
weil das ueberall laeuft. DOCX und PDF brauchen ``python-docx`` und
``pdfplumber`` (``requirements.txt``) – lokal fehlt python-docx, auf den
Servern ist beides da. Dieser Waechter laeuft deshalb dort, wo die
Bibliotheken sind, und endet sonst mit Exit 2 ("konnte nicht laufen"), nie
mit einem stillen Gruen.

Gemessen am ECHTEN Erzeuger: die DOCX baut python-docx selbst (Ueberschrift
in englischer UND deutscher Stilbenennung, Tabelle mit verbundenen Zellen),
die PDF ist von Hand gebaut (pdfplumber muss sie oeffnen, sonst Exit 2).

Seit Parser-Fassung 5 auch die BILDER: Diagramme in einem DOCX und PDF-Seiten
ohne Textebene gehen durch tesseract (Positivkontrolle: fehlt tesseract mit
deu/eng, Exit 2). Das Testbild ist schwarze Schrift auf DURCHSICHTIGEM Grund,
wie die Diagramme im echten Bestand.

Aufruf:  venv/bin/python tests/test_schema_graph_dokumente.py [parser.py]
         (optional ein anderer Parser – fuer Gegenproben an einer Kopie)
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + str(detail)[:400] if detail else ""))


def abbruch(grund):
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


try:
    import docx  # noqa: F401
    import pdfplumber  # noqa: F401
    from docx.enum.style import WD_STYLE_TYPE
except ImportError as e:
    abbruch(f"Lesebibliothek fehlt ({e.name}) – dieser Waechter laeuft auf den Servern (venv)")

pfad = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backend" / "schema_graph_parser.py"
spec = importlib.util.spec_from_file_location("parser_unter_test", pfad)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

TMP = Path(tempfile.mkdtemp(prefix="test_sg_dok_"))
try:
    # ── DOCX ────────────────────────────────────────────────────────────────
    print("1. DOCX")
    d = docx.Document()
    d.add_heading("Namenskonventionen", level=1)
    d.add_paragraph("Ein Mandat ist im Haus ein Kundenauftrag. Mandate stehen in CTS.V_VKAUF_AUFTRAG.")
    t = d.add_table(rows=3, cols=2)
    t.cell(0, 0).merge(t.cell(0, 1)).text = "Kürzeltabelle"
    t.cell(1, 0).text, t.cell(1, 1).text = "AKDKND", "Kundenstamm"
    t.cell(2, 0).text, t.cell(2, 1).text = "VVKAUF", "Auftrag"
    stil = d.styles.add_style("Überschrift 2", WD_STYLE_TYPE.PARAGRAPH)
    d.add_paragraph("Join-Regeln", style=stil)
    d.add_paragraph("Fremdschlüssel heißen wie der Primärschlüssel der Zieltabelle.")
    d.add_paragraph("   ")
    datei = TMP / "Konventionen.docx"
    d.save(str(datei))
    e = P.datei_zerlegen(str(datei))
    f = (e.get("fakten") or [{}])[0]
    teile = f.get("teile") or []
    alles = "\n".join(teile)
    check("Positivkontrolle: DOCX gelesen, ein Dokument-Fakt", e.get("ok") and f.get("art") == "dokument"
          and f.get("titel") == "Konventionen", e)
    check("Englische Ueberschrift ('Heading 1') wird Kopf", any(x.startswith("[Namenskonventionen]") for x in teile), teile)
    check("Deutsche Ueberschrift ('Überschrift 2') wird Kopf", any(x.startswith("[Join-Regeln]") and "Fremdschlüssel" in x
                                                                    for x in teile), teile)
    check("Absatztext vorhanden", "Mandat" in alles and "CTS.V_VKAUF_AUFTRAG" in alles, alles[:300])
    check("Tabelle zeilenweise, Zellen mit ' | '", "AKDKND | Kundenstamm" in alles and "VVKAUF | Auftrag" in alles, alles)
    check("Verbundene Zelle nur EINMAL", alles.count("Kürzeltabelle") == 1, alles)
    # find() statt index(): ein fehlender Teil soll FEHLSCHLAGEN, nicht werfen (Register)
    lage = [alles.find(x) for x in ("Mandat", "AKDKND", "Join-Regeln")]
    check("Tabelle in Lesereihenfolge (zwischen Absatz und naechster Ueberschrift)",
          -1 not in lage and lage == sorted(lage), (lage, alles[:300]))
    kaputt = TMP / "kaputt.docx"
    kaputt.write_bytes(b"PK\x03\x04 kein echtes docx")
    e = P.datei_zerlegen(str(kaputt))
    check("Kaputtes DOCX: Fehler mit Grund, kein Wurf", e.get("ok") is False and e.get("fehler"), e)

    # ── PDF ─────────────────────────────────────────────────────────────────
    print("2. PDF")

    def pdf(inhalt: bytes) -> bytes:
        """Minimal-PDF (eine Seite, Helvetica) mit korrekter xref-Tabelle."""
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
                b"/Resources << /Font << /F1 5 0 R >> >> >>",
                b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        out = b"%PDF-1.4\n"
        lage = []
        for i, o in enumerate(objs, 1):
            lage.append(len(out))
            out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for x in lage:
            out += f"{x:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return out

    text_pdf = TMP / "SQL_Beispiele.pdf"
    text_pdf.write_bytes(pdf(b"BT /F1 12 Tf 72 760 Td (Faelle je Fallart: GROUP BY CTSFAL_FALLART) Tj ET"))
    try:
        with pdfplumber.open(str(text_pdf)) as pp:
            roh = pp.pages[0].extract_text() or ""
    except Exception as ex:  # noqa: BLE001
        roh = ""
        abbruch(f"Positivkontrolle: die gebaute PDF oeffnet pdfplumber nicht ({ex})")
    if "CTSFAL_FALLART" not in roh:
        abbruch(f"Positivkontrolle: pdfplumber liest den Text der gebauten PDF nicht ({roh!r})")
    e = P.datei_zerlegen(str(text_pdf))
    f = (e.get("fakten") or [{}])[0]
    check("PDF gelesen, Text im Abschnitt", e.get("ok") and any("CTSFAL_FALLART" in x for x in f.get("teile") or [])
          and f.get("titel") == "SQL_Beispiele", e)
    bild_pdf = TMP / "Diagramm.pdf"
    bild_pdf.write_bytes(pdf(b"0 0 1 rg 100 100 200 200 re f"))
    e = P.datei_zerlegen(str(bild_pdf))
    check("PDF ohne Text (nur Grafik/gescannt): Fehler MIT Grund", e.get("ok") is False
          and "kein lesbarer Text" in (e.get("fehler") or ""), e)

    # ── Grenzen ─────────────────────────────────────────────────────────────
    print("3. Grenzen")
    alt = P.DOK_MAX
    P.DOK_MAX = 10
    e = P.datei_zerlegen(str(datei))
    P.DOK_MAX = alt
    check("Zu grosses Dokument: Fehler mit Grund statt Speicherlast", e.get("ok") is False
          and "groesser" in (e.get("fehler") or ""), e)
    gross = docx.Document()
    gross.add_heading("Lang", level=1)
    for _ in range(40):
        gross.add_paragraph("wort " * 200)
    lang = TMP / "Lang.docx"
    gross.save(str(lang))
    e = P.datei_zerlegen(str(lang))
    teile = (e.get("fakten") or [{}])[0].get("teile") or []
    check("Langes Dokument: Abschnitte gedeckelt, jeder mit seiner Ueberschrift",
          len(teile) >= 20 and all(len(x) <= P.DOK_TEIL + 20 and x.startswith("[Lang]") for x in teile),
          (len(teile), max((len(x) for x in teile), default=0)))

    # ── Bilder (Texterkennung, Parser-Fassung 5) ────────────────────────────
    print("4. Bilder")
    import io
    import struct
    import zlib
    from PIL import Image, ImageDraw, ImageFont

    if P._ocr_sprache() is None:
        abbruch("Positivkontrolle: tesseract mit deu/eng fehlt auf diesem Rechner")

    def schrift(groesse):
        for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
            if Path(f).exists():
                return ImageFont.truetype(f, groesse)
        return ImageFont.load_default(size=groesse)

    def bild(zeilen, modus="RGBA", groesse=(900, 220)):
        """Schwarze Schrift; bei RGBA auf DURCHSICHTIGEM Grund (wie die
        Diagramme im echten Bestand)."""
        im = Image.new(modus, groesse, (0, 0, 0, 0) if modus == "RGBA" else (255, 255, 255))
        z = ImageDraw.Draw(im)
        for i, t in enumerate(zeilen):
            z.text((20, 20 + i * 60), t, fill=(0, 0, 0, 255) if modus == "RGBA" else (0, 0, 0), font=schrift(40))
        puffer = io.BytesIO()
        im.save(puffer, "PNG")
        return puffer.getvalue()

    diagramm = bild(["CTS_REZEPT_POS", "Rezepte zur Abrechnung"])
    # Positivkontrolle der Probe: OHNE Weiss-Unterlage (blosses RGB) ist das
    # Bild schwarz auf schwarz – sonst misst die Pruefung unten nichts.
    roh_rgb = io.BytesIO()
    Image.open(io.BytesIO(diagramm)).convert("RGB").save(roh_rgb, "PNG")
    import subprocess
    r = subprocess.run(["tesseract", "stdin", "stdout", "-l", "deu+eng"], input=roh_rgb.getvalue(),
                       capture_output=True, timeout=60)
    check("Probe beisst: dasselbe Bild ohne Weiss-Unterlage liest tesseract NICHT",
          b"REZEPT" not in r.stdout.upper(), r.stdout[:200])

    nur_bilder = docx.Document()
    nur_bilder.add_heading("Datenbankmodell", level=0)
    nur_bilder.add_heading("Behandlungszeiträume", level=2)
    nur_bilder.add_picture(io.BytesIO(diagramm))
    nur_bilder.add_heading("Ereignisse", level=2)
    nur_bilder.add_picture(io.BytesIO(bild(["CTS_EREIGNIS_TYP", "Ereignistypen"])))
    nur_bilder.add_picture(io.BytesIO(diagramm))           # dasselbe Bild noch einmal
    nur_bilder.add_picture(io.BytesIO(bild(["x"], groesse=(20, 20))))   # Symbol
    datei_b = TMP / "Diagramme.docx"
    nur_bilder.save(str(datei_b))
    e = P.datei_zerlegen(str(datei_b))
    teile = (e.get("fakten") or [{}])[0].get("teile") or []
    st = e.get("stat") or {}
    alles = "\n".join(teile)
    check("Nur-Bilder-DOCX wird gelesen (vorher: 'kein lesbarer Text')", e.get("ok") and teile, e)
    check("Text des Diagramms erkannt (Tabellenname UND Bezeichnung)",
          "REZEPT_POS" in alles and "Rezepte" in alles, alles[:400])
    erster = next((x for x in teile if "REZEPT_POS" in x), "")
    check("Bildtext steht unter SEINER Ueberschrift und ist als Texterkennung gekennzeichnet",
          erster.startswith("[Behandlungszeiträume] " + P.OCR_KENNUNG), erster[:120])
    zweiter = next((x for x in teile if "EREIGNIS_TYP" in x), "")
    check("Zweites Bild unter der zweiten Ueberschrift", zweiter.startswith("[Ereignisse]"), zweiter[:120])
    check("Dasselbe Bild nur EINMAL gelesen", alles.count("REZEPT_POS") == 1 and st.get("bilder") == 3, (st, alles.count("REZEPT_POS")))
    check("Symbol (20x20) ausgelassen und gezaehlt", st.get("bilder_klein") == 1 and st.get("bilder_gelesen") == 2, st)

    gemischt = docx.Document()
    gemischt.add_paragraph("Vor dem Bild.")
    gemischt.add_picture(io.BytesIO(diagramm))
    gemischt.add_paragraph("Nach dem Bild.")
    # Text UND Bild im selben Absatz (Bildunterschrift davor): erst der Text
    gemischt.add_paragraph("Im Absatz davor.").add_run().add_picture(io.BytesIO(bild(["CTS_EREIGNIS_TYP"])))
    datei_g = TMP / "Gemischt.docx"
    gemischt.save(str(datei_g))
    alles = "\n".join(((P.datei_zerlegen(str(datei_g)).get("fakten") or [{}])[0]).get("teile") or [])
    lage = [alles.find(x) for x in ("Vor dem Bild", "REZEPT_POS", "Nach dem Bild")]
    check("Bildtext in Lesereihenfolge zwischen den Absaetzen", -1 not in lage and lage == sorted(lage), (lage, alles))
    lage2 = [alles.find(x) for x in ("Im Absatz davor", "EREIGNIS_TYP")]
    check("Bild im selben Absatz steht NACH dessen Text", -1 not in lage2 and lage2 == sorted(lage2), (lage2, alles))

    # Grenzen und Angriffe – direkt an der Lesefunktion
    stat = {}
    ende = __import__("time").monotonic() + 60
    check("Kein Bild (Textdatei mit Pfaden) erreicht tesseract nicht",
          P._bild_lesen(b"/etc/hostname\n/etc/passwd\n", stat, ende) == "" and stat.get("bilder_unlesbar") == 1, stat)
    eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 100\nshowpage\n"
    # Spion am EPS-Leser von PIL: ohne ihn hinge die Probe davon ab, ob
    # Ghostscript installiert ist (fehlt es, wirft PIL ohnehin – kein Biss).
    from PIL import EpsImagePlugin
    _eps_offen = []
    _eps_alt = EpsImagePlugin.EpsImageFile._open
    EpsImagePlugin.EpsImageFile._open = lambda self, *a, **k: (_eps_offen.append(1), _eps_alt(self, *a, **k))[1]
    stat = {}
    try:
        _eps_erg = P._bild_lesen(eps, stat, ende)
    finally:
        EpsImagePlugin.EpsImageFile._open = _eps_alt
    check("EPS wird nicht einmal geoeffnet (kein Ghostscript)", _eps_erg == "" and not _eps_offen
          and stat.get("bilder_unlesbar") == 1, (stat, _eps_offen))

    def png_luege(breite, hoehe):
        """Kleines PNG, dessen Kopf eine riesige Groesse BEHAUPTET (CRC stimmt)."""
        roh = bild(["x"], modus="RGB", groesse=(50, 50))
        ihdr = struct.pack(">II", breite, hoehe) + roh[24:29]
        return roh[:16] + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr)) + roh[33:]
    # 10000x10000 liegt UEBER der eigenen Grenze, aber UNTER der von PIL (die
    # wirft erst ab ~179 Mio. Pixel) – nur so misst die Probe die eigene.
    stat = {}
    check("Behauptete Groesse ueber OCR_BILD_PIXEL: ausgelassen, ohne zu entpacken",
          P._bild_lesen(png_luege(10000, 10000), stat, ende) == "" and stat.get("bilder_zu_gross") == 1, stat)
    stat = {}
    check("Behauptete Riesengroesse (PIL-Grenze): ausgelassen, kein Wurf",
          P._bild_lesen(png_luege(100000, 100000), stat, ende) == "" and sum(stat.values()) == 1, stat)
    stat = {}
    alt_b = P.OCR_BILD_BYTES
    P.OCR_BILD_BYTES = 100
    check("Zu viele Bytes: ausgelassen", P._bild_lesen(diagramm, stat, ende) == "" and stat.get("bilder_zu_gross") == 1, stat)
    P.OCR_BILD_BYTES = alt_b
    stat = {}
    check("Zeitgrenze abgelaufen: ausgelassen", P._bild_lesen(diagramm, stat, 0.0) == ""
          and stat.get("bilder_ohne_zeit") == 1, stat)
    alt_n = P.OCR_MAX_BILDER
    P.OCR_MAX_BILDER = 1
    e = P.datei_zerlegen(str(datei_b))
    P.OCR_MAX_BILDER = alt_n
    st = e.get("stat") or {}
    check("Hoechstzahl Bilder je Dokument greift", st.get("bilder_gelesen") == 1 and st.get("bilder_ueber_grenze") == 2, st)

    # Ohne tesseract: Fehler mit Grund und Abhilfe, nicht "kein lesbarer Text"
    alt_c = list(P._ocr_sprache_cache)
    P._ocr_sprache_cache[:] = [None]
    e = P.datei_zerlegen(str(datei_b))
    P._ocr_sprache_cache[:] = alt_c
    check("Ohne tesseract: Nur-Bilder-DOCX nennt die fehlende Texterkennung", e.get("ok") is False
          and "tesseract" in (e.get("fehler") or ""), e)
    e = P.datei_zerlegen(str(datei))
    check("Dokument MIT Text braucht keine Texterkennung (unveraendert gelesen)", e.get("ok"), e)

    # Gescannte PDF-Seite: ein Bild, keine Textebene
    def pdf_mit_bild(png: bytes) -> bytes:
        im = Image.open(io.BytesIO(png)).convert("RGB")
        b, h = im.size
        daten = zlib.compress(im.tobytes())
        inhalt = f"q {b} 0 0 {h} 50 400 cm /Im1 Do Q".encode()
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
                b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1000 842] /Contents 4 0 R "
                b"/Resources << /XObject << /Im1 5 0 R >> >> >>",
                b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
                f"<< /Type /XObject /Subtype /Image /Width {b} /Height {h} /ColorSpace /DeviceRGB "
                f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(daten)} >>\nstream\n".encode()
                + daten + b"\nendstream"]
        out = b"%PDF-1.4\n"
        lage = []
        for i, o in enumerate(objs, 1):
            lage.append(len(out))
            out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
        for x in lage:
            out += f"{x:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return out
    scan = TMP / "Scan.pdf"
    scan.write_bytes(pdf_mit_bild(bild(["CTS_REZEPT_POS", "Rezepte zur Abrechnung"], modus="RGB")))
    try:
        with pdfplumber.open(str(scan)) as pp:
            hat_bild = bool(pp.pages[0].images) and not (pp.pages[0].extract_text() or "").strip()
    except Exception:  # noqa: BLE001
        hat_bild = False
    if not hat_bild:
        abbruch("Positivkontrolle: die gebaute Scan-PDF hat fuer pdfplumber kein Bild bzw. doch Text")
    e = P.datei_zerlegen(str(scan))
    alles = "\n".join(((e.get("fakten") or [{}])[0]).get("teile") or [])
    # Aus der gerenderten Seite (200 dpi) liest tesseract "_" als Leerzeichen
    # (DEV, 2026-11-08) – zugesagt ist der erkannte Text, nicht der Unterstrich
    import re
    check("Gescannte PDF-Seite per Texterkennung gelesen", e.get("ok") and re.search(r"REZEPT[_ ]POS", alles)
          and P.OCR_KENNUNG in alles, e)
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nBilanz: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
