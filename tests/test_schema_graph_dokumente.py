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
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\nBilanz: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
