#!/usr/bin/env python3
"""Tests fuer die Word-Hausvorlage (skills/office/vorlage_word.py + main.py).

AUSGANGSPUNKT: ``office_create_word`` rief ``Document()`` ohne Argument auf –
US-Letter, Calibri, Office-Blau, keine Kopf-/Fusszeile. Jetzt entsteht jedes
Word-Dokument auf einer Hausvorlage (A4, Branding-Farbe als Theme, Logo,
Seitenzahl) oder auf einer hochgeladenen Firmenvorlage.

Gemessen wird am ERZEUGTEN Dokument (python-docx liest es zurueck), nicht am
Quelltext. Hermetisch: ``backend.config`` und ``backend.main`` sind Attrappen,
Vorlagen- und Dokumentordner liegen in einem Wegwerf-Verzeichnis.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen (python-docx fehlt,
Sandkasten nicht hergestellt).

Lauf:  python3 tests/test_office_vorlage_word.py
"""

import asyncio
import io
import re
import shutil
import sys
import tempfile
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


def abbruch(grund):
    print(f"ABBRUCH (konnte nicht laufen): {grund}")
    sys.exit(2)


try:
    import docx  # noqa: F401
    from docx import Document
    from docx.oxml.ns import qn
except Exception as e:  # noqa: BLE001
    abbruch(f"python-docx nicht installiert ({e})")

TMP = Path(tempfile.mkdtemp(prefix="jarvis_word_vorlage_"))

# ── Attrappen: echte Antwortform von config.get_skill_states() ──────────────
AKZENT = "1A7F5A"
LOGO = TMP / "logo.png"
# 4×2-PNG, von Hand gebaut (kein Pillow noetig): Seitenverhaeltnis 2:1
import struct  # noqa: E402
import zlib  # noqa: E402


def _png(b, h):
    roh = b"".join(b"\x00" + b"\xb8\x0f\x2e" * b for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", b, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(roh)) + chunk(b"IEND", b""))


LOGO.write_bytes(_png(40, 20))
_logo_an = {"wert": True}

cfg = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return {"branding": {"enabled": True, "config": {
            "colors_light": {"accent": "#" + AKZENT},
            "company_name": "Contoso AG"}}}


cfg.config = _Cfg()
bmain = types.ModuleType("backend.main")
bmain._branding_logo_path = lambda variante, art: (LOGO if _logo_an["wert"] else None)
import backend  # noqa: E402
sys.modules["backend.config"] = cfg
sys.modules["backend.main"] = bmain

from skills.office import vorlage_word as VW  # noqa: E402
from skills.office import main as OM  # noqa: E402

VW.VORLAGEN_DIR = TMP / "vorlagen"
OM.DOCS_DIR = TMP / "documents"
if not str(VW.VORLAGEN_DIR).startswith(str(TMP)) or not str(OM.DOCS_DIR).startswith(str(TMP)):
    abbruch("Sandkasten nicht hergestellt")


def xml(pfad, teil):
    with zipfile.ZipFile(pfad) as z:
        return z.read(teil).decode("utf-8")


def kinder_tags(el):
    return [k.tag.split("}")[1] for k in el]


try:
    # ═════════════════════════════════════════════════════════════════════
    print("\n=== 1. Erzeugte Hausvorlage ===")
    ziel = VW.erzeuge()
    pruefe(ziel == VW.VORLAGEN_DIR / "standard.docx" and ziel.exists(),
           "Hausvorlage liegt als standard.docx im Vorlagenordner")
    pruefe(not list(VW.VORLAGEN_DIR.glob("*.tmp.docx")) and not list(VW.VORLAGEN_DIR.glob("*.neu.docx")),
           "keine Zwischenstaende liegen geblieben")
    d = Document(str(ziel))
    sec = d.sections[0]
    pruefe(abs(sec.page_width.cm - 21.0) < 0.05 and abs(sec.page_height.cm - 29.7) < 0.05,
           f"A4 statt US-Letter ({sec.page_width.cm:.2f}×{sec.page_height.cm:.2f})")
    pruefe(abs(sec.left_margin.cm - VW.RAND_LINKS_CM) < 0.05, "linker Rand nach DIN 5008")
    pruefe(len(d.element.body) == 1 and d.element.body[0].tag == qn("w:sectPr"),
           "Vorlage hat keinen Textkoerper (nur das Seitenformat)")

    stile = d.styles
    h1 = stile["Heading 1"]
    pruefe(h1.font.name == VW._pptx.SCHRIFT_TITEL, f"Ueberschrift 1 in der Titelschrift ({h1.font.name})")
    pruefe(stile["Normal"].font.name == VW._pptx.SCHRIFT_TEXT, "Grundtext in der Textschrift")
    farbe = h1.element.rPr.find(qn("w:color"))
    pruefe(farbe is not None and farbe.get(qn("w:val")) == AKZENT
           and farbe.get(qn("w:themeColor")) == "accent1",
           "Ueberschrift 1: Branding-Akzent UND Theme-Verweis",
           str(farbe.attrib if farbe is not None else None))
    # rFonts auf allen vier Bereichen, sonst mischt Word Calibri hinein
    rf = stile["Normal"].element.rPr.find(qn("w:rFonts"))
    pruefe(rf is not None and all(rf.get(qn("w:" + a)) == VW._pptx.SCHRIFT_TEXT
                                  for a in ("ascii", "hAnsi", "eastAsia", "cs")),
           "Schrift fuer alle Schriftbereiche gesetzt")
    pruefe(stile["Title"].element.pPr is None
           or stile["Title"].element.pPr.find(qn("w:pBdr")) is None,
           "die blaue Linie unter dem Titel ist entfernt")

    # Schemareihenfolge: Word lehnt falsch geordnete Kinder ab, LibreOffice
    # nicht – das Server-PDF zeigt den Fehler also nie.
    fehler = []
    for st in stile:
        rpr = st.element.rPr
        if rpr is None:
            continue
        t = kinder_tags(rpr)
        if "color" in t and "sz" in t and t.index("color") > t.index("sz"):
            fehler.append(st.name)
    pruefe(not fehler, "w:color steht in jedem Stil VOR w:sz", ", ".join(fehler))

    theme = xml(ziel, "word/theme/theme1.xml")
    pruefe(AKZENT in theme and VW._pptx.SCHRIFT_TITEL in theme,
           "Theme traegt Akzentfarbe und CI-Schrift")

    kopf = sec.header.paragraphs[0]
    ppr_tags = kinder_tags(kopf._p.pPr)
    pruefe("pBdr" in ppr_tags and "jc" in ppr_tags and ppr_tags.index("pBdr") < ppr_tags.index("jc"),
           f"Kopfzeilen-Linie in Schemareihenfolge ({ppr_tags})")
    pruefe(bool(kopf._p.xpath(".//w:drawing")), "Logo steht in der Kopfzeile")
    fuss = xml(ziel, "word/footer1.xml")
    pruefe('w:instr=" PAGE "' in fuss and 'w:instr=" NUMPAGES "' in fuss,
           "Fusszeile mit Seitenzahl und Seitenanzahl")
    pruefe("Contoso AG" in fuss, "Fusszeile nennt die Firma")
    pruefe(d.core_properties.author == "Contoso AG", "Autor ist nicht mehr 'python-docx'")

    # Ohne Logo: Firmenname in der Kopfzeile statt leerer Zeile
    _logo_an["wert"] = False
    ohne = VW.erzeuge(TMP / "ohne_logo.docx")
    _logo_an["wert"] = True
    k2 = Document(str(ohne)).sections[0].header.paragraphs[0]
    pruefe("Contoso AG" in k2.text and not k2._p.xpath(".//w:drawing"),
           "ohne Logo steht der Firmenname in der Kopfzeile")

    # ═════════════════════════════════════════════════════════════════════
    print("\n=== 2. Aufloesen ===")
    vor = ziel.stat().st_mtime_ns
    pruefe(VW.sicherstellen() == ziel and ziel.stat().st_mtime_ns == vor,
           "sicherstellen() ueberschreibt eine vorhandene Vorlage nicht")

    # ── Gleichzeitige Erzeugung (Code-Review 2026-10-25) ────────────────────
    # Gezaehlt wird, wie oft ERZEUGT wird – "kein Absturz" allein waere
    # Glueckssache (das Rennen tritt nicht in jedem Lauf auf).
    import threading as _th
    import zipfile as _zf
    _ziel_par = TMP / "parallel.docx"
    _echt_erz = VW.erzeuge
    _zaehl = []
    def _gezaehlt(z=None):
        _zaehl.append(1)
        return _echt_erz(z)
    VW.erzeuge = _gezaehlt
    _erg, _feh = [], []
    def _los():
        try:
            _erg.append(VW.sicherstellen(_ziel_par))
        except Exception as e:  # noqa: BLE001
            _feh.append(repr(e))
    try:
        _faeden = [_th.Thread(target=_los) for _ in range(4)]
        for _f in _faeden:
            _f.start()
        for _f in _faeden:
            _f.join(180)
    finally:
        VW.erzeuge = _echt_erz
    pruefe(not _feh and len(_erg) == 4 and all(e == _ziel_par for e in _erg),
           "4 gleichzeitige sicherstellen(): alle bekommen die Vorlage, keiner scheitert",
           str(_feh[:1]))
    pruefe(len(_zaehl) == 1, "...und sie wird genau EINMAL erzeugt (Sperre)", str(len(_zaehl)))
    _zip_ok = False
    try:
        with _zf.ZipFile(_ziel_par) as _z:
            _zip_ok = _z.testzip() is None
    except Exception:  # noqa: BLE001
        pass
    pruefe(_zip_ok, "...und ist ein unbeschaedigtes ZIP")
    pruefe(not [p for p in TMP.iterdir() if p.name.startswith(".")],
           "keine Zwischenstaende bleiben liegen")
    pruefe(VW.loese_vorlage("../../data/settings.json") == ziel,
           "Pfadanteile werden verworfen, Unbekanntes faellt auf die Hausvorlage")
    (VW.VORLAGEN_DIR / "x.tmp.docx").write_bytes(b"halb")
    pruefe("x.tmp.docx" not in VW.verfuegbare() and VW.loese_vorlage("x.tmp.docx") == ziel,
           "Zwischenstaende sind keine waehlbare Vorlage")
    (VW.VORLAGEN_DIR / "x.tmp.docx").unlink()

    # ═════════════════════════════════════════════════════════════════════
    print("\n=== 3. office_create_word benutzt die Vorlage ===")
    werkzeug = OM.CreateWordTool()
    pruefe("template" in werkzeug.parameters_schema()["properties"],
           "Werkzeug bietet die Wahl einer Vorlage an")
    antwort = asyncio.run(werkzeug.execute(
        filename="Bericht", title="Quartalsbericht",
        content="# Kapitel\nText\n- Punkt\n1. Eins\n### Klein"))
    m = re.search(r"/api/documents/([^)\s]+)", antwort)
    pruefe(m is not None and "Hinweis" not in antwort, "Dokument erzeugt, ohne Rueckfall-Hinweis",
           antwort[:200])
    if m is None:
        abbruch("kein Dokument erzeugt – Folgepruefungen waeren trivial")
    erg = Document(str(OM.DOCS_DIR / m.group(1)))
    s2 = erg.sections[0]
    pruefe(abs(s2.page_width.cm - 21.0) < 0.05, "erzeugtes Dokument ist A4")
    pruefe(bool(s2.header.paragraphs[0]._p.xpath(".//w:drawing")), "…mit Logo in der Kopfzeile")
    stilnamen = [p.style.name for p in erg.paragraphs]
    pruefe(stilnamen == ["Title", "Heading 1", "Normal", "List Bullet", "List Number", "Heading 3"],
           f"Formatvorlagen je Zeile ({stilnamen})")
    pruefe(erg.styles["Heading 1"].font.name == VW._pptx.SCHRIFT_TITEL,
           "Formatvorlagen stammen aus der Hausvorlage")

    # ═════════════════════════════════════════════════════════════════════
    print("\n=== 4. Hochgeladene Firmenvorlage (.dotx, Mustertext, fehlende Stile) ===")
    fremd = Document()
    fremd.add_paragraph("MUSTERTEXT – bitte ersetzen")
    fremd.add_table(rows=1, cols=1)
    # Aufzaehlungsstil entfernen: viele Firmenvorlagen haben keinen
    for name in ("List Bullet", "List Number"):
        el = fremd.styles[name].element
        el.getparent().remove(el)
    fremd.sections[0].header.paragraphs[0].text = "BRIEFKOPF"
    puffer = io.BytesIO()
    fremd.save(puffer)
    # Als .dotx kennzeichnen – so kommt eine echte Word-Vorlage an
    roh = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(puffer.getvalue())) as q, \
            zipfile.ZipFile(roh, "w", zipfile.ZIP_DEFLATED) as z:
        for e in q.infolist():
            daten = q.read(e.filename)
            if e.filename == "[Content_Types].xml":
                daten = daten.replace(VW.CT_DOKUMENT.encode(), VW.CT_VORLAGE.encode())
            z.writestr(e, daten)
    dotx = roh.getvalue()
    try:
        Document(io.BytesIO(dotx))
        pruefe(False, "Positivkontrolle: python-docx lehnt die .dotx ab")
        abbruch("die Probe-.dotx ist keine – Abschnitt 4 waere trivial")
    except ValueError:
        pruefe(True, "Positivkontrolle: python-docx lehnt die .dotx ab")
    umgebaut = VW.als_dokument(dotx)
    # Eigene Bedingung statt nacktem Document(...): ein Wurf waere ein Absturz
    # ohne Bilanzzeile, also von „nicht gelaufen" nicht zu unterscheiden.
    try:
        Document(io.BytesIO(umgebaut))
        oeffenbar = True
    except ValueError:
        oeffenbar = False
    pruefe(oeffenbar, "als_dokument() macht sie oeffenbar")
    pruefe(VW.als_dokument(puffer.getvalue()) == puffer.getvalue(),
           "eine .docx bleibt byte-gleich")
    (VW.VORLAGEN_DIR / "firma.docx").write_bytes(umgebaut)

    antwort = asyncio.run(werkzeug.execute(filename="Brief", template="firma",
                                           content="Hallo\n- Punkt\n2. Zwei"))
    m = re.search(r"/api/documents/([^)\s]+)", antwort)
    pruefe(m is not None and "Hinweis" not in antwort, "Dokument auf der Firmenvorlage erzeugt",
           antwort[:200])
    if m:
        erg = Document(str(OM.DOCS_DIR / m.group(1)))
        texte = [p.text for p in erg.paragraphs]
        pruefe("MUSTERTEXT – bitte ersetzen" not in texte and not erg.tables,
               "Mustertext und Mustertabelle sind entfernt", str(texte))
        pruefe(texte == ["Hallo", "• Punkt", "2. Zwei"],
               f"fehlende Aufzaehlungsstile → Text mit Ersatzzeichen ({texte})")
        pruefe(erg.sections[0].header.paragraphs[0].text == "BRIEFKOPF",
               "Kopfzeile der Firmenvorlage bleibt erhalten")

    # ═════════════════════════════════════════════════════════════════════
    print("\n=== 5. office_template_info fuer Word ===")
    info = asyncio.run(OM.TemplateInfoTool().execute(art="word"))
    pruefe(f"Pfad (fuer python-docx): {ziel}" in info, "nennt den PFAD der Word-Hausvorlage",
           info[:200])
    pruefe("Heading 1" in info and "firma.docx" in info, "nennt Formatvorlagen und Vorlagen")
    pruefe("Layouts" not in info, "liefert nicht die PowerPoint-Auskunft")

    # ═════════════════════════════════════════════════════════════════════
    print("\n=== 6. Endpunkte und Oberflaeche (Regeln) ===")
    import ast
    baum = ast.parse((ROOT / "backend" / "main.py").read_text())
    routen = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.AsyncFunctionDef):
            for dek in knoten.decorator_list:
                if (isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute)
                        and dek.args and isinstance(dek.args[0], ast.Constant)):
                    routen.add((dek.func.attr, dek.args[0].value))
    for r in (("get", "/api/branding/docx-templates"), ("post", "/api/branding/docx-template"),
              ("delete", "/api/branding/docx-template"),
              ("post", "/api/branding/docx-template/regenerate")):
        pruefe(r in routen, f"Route {r[0].upper()} {r[1]}")
    html = (ROOT / "frontend" / "settings.html").read_text()
    pruefe('id="br-docx-file"' in html and 'id="br-docx-list"' in html
           and 'data-i18n="branding.docx_heading"' in html, "Markup im Branding-Reiter")
    i18n = (ROOT / "frontend" / "js" / "i18n.js").read_text()
    pruefe(i18n.count("'branding.docx_heading'") == 2, "i18n-Ueberschrift in DE und EN")
finally:
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n{'=' * 60}\nErgebnis: {_ok}/{_ok + _fail} Pruefungen bestanden")
sys.exit(1 if _fail else 0)
