#!/usr/bin/env python3
"""Gegenprobe zu tests/test_schema_graph_dokumente.py: beisst der Waechter?

Jede Probe dreht EINE Zusage der Texterkennung im Parser zurueck und erwartet
mindestens einen FAIL. Anders als die uebrigen Gegenproben wird hier NICHTS
im Baum gepatcht: der Waechter nimmt den Pfad eines Parsers entgegen, die
sabotierte Fassung liegt in einem eigenen Temp-Verzeichnis.

Laeuft dort, wo python-docx, pdfplumber und tesseract sind (Server, venv):
  venv/bin/python tests/gegen_schema_graph_dokumente.py
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_schema_graph_dokumente.py"
PARSER = ROOT / "backend" / "schema_graph_parser.py"

# (Name, [(alt, neu), ...]) – mehrere Paare, wo eine Zusage zweifach gehalten wird
PROBEN = [
    ("Transparenz nicht auf Weiss gelegt",
     [('        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):', "        if False:")]),
    ("Alle Bildformate (auch EPS -> Ghostscript)",
     [("        im = Image.open(io.BytesIO(blob), formats=OCR_FORMATE)", "        im = Image.open(io.BytesIO(blob))")]),
    ("Pixelgrenze fehlt", [("        if b * h > OCR_BILD_PIXEL:", "        if False:")]),
    ("Bytegrenze fehlt", [("    if len(blob) > OCR_BILD_BYTES:", "    if False:")]),
    ("Symbole werden gelesen", [("        if min(b, h) < OCR_MIN_SEITE:", "        if False:")]),
    ("Gleiches Bild mehrfach gelesen", [('        if kennung in self.gesehen:\n            return ""\n', "")]),
    ("Keine Hoechstzahl Bilder", [("        if self.anzahl >= OCR_MAX_BILDER:", "        if False:")]),
    ("Keine Zeitgrenze",
     [("    if rest <= 1:\n", "    if False:\n"), ("timeout=min(OCR_ZEIT_BILD, rest)", "timeout=OCR_ZEIT_BILD")]),
    ("DOCX-Bilder nicht gelesen", [("            for blob in _docx_bilder(el, d.part):", "            for blob in []:")]),
    ("Gescannte PDF-Seite nicht gelesen", [("                if not t.strip() and seite.images:", "                if False:")]),
    ("Bildtext nicht gekennzeichnet", [('        return f"{OCR_KENNUNG} {t}" if t else ""', "        return t")]),
    ("Ohne tesseract nur 'kein lesbarer Text'", [('        if stat.get("bilder_ohne_ocr"):', "        if False:")]),
    # Bild zuerst gelesen; der zweite Durchgang am Ende findet es dann schon
    # gesehen und haengt nichts mehr an – also echte Umstellung, kein Verlust
    ("Bilder VOR dem Text ihres Absatzes",
     [('            if tag == "p":\n                par = Paragraph(el, d)',
       '            if tag == "p":\n                for blob in _docx_bilder(el, d.part):\n'
       '                    bt = bilder.lesen(blob)\n                    if bt:\n'
       '                        out.append(("text", bt))\n                par = Paragraph(el, d)')]),
]


def lauf(parser: Path) -> tuple[int, int]:
    r = subprocess.run([sys.executable, "-W", "ignore", str(WAECHTER), str(parser)], capture_output=True,
                       text=True, timeout=900, cwd=str(ROOT))
    m = re.search(r"Bilanz: (\d+) OK, (\d+) FAIL", r.stdout)
    return (int(m.group(2)) if m and r.returncode != 2 else -1), r.returncode


def main() -> int:
    quelle = PARSER.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="gegen_sg_dok_"))
    try:
        basis = tmp / "schema_graph_parser.py"
        basis.write_text(quelle, encoding="utf-8")
        f, rc = lauf(basis)
        if f != 0:
            print(f"ABBRUCH: Basislauf nicht gruen (FAIL={f}, rc={rc})")
            return 2
        print("Basislauf gruen.\n")
        beissen = 0
        for name, paare in PROBEN:
            t = quelle
            ok = True
            for alt, neu in paare:
                if t.count(alt) != 1:
                    print(f"  ???  {name:50} Anker {t.count(alt)}x gefunden")
                    ok = False
                    break
                t = t.replace(alt, neu)
            if not ok:
                continue
            ziel = tmp / f"p{beissen}_{abs(hash(name)) % 10**6}" / "schema_graph_parser.py"
            ziel.parent.mkdir()
            ziel.write_text(t, encoding="utf-8")
            f, rc = lauf(ziel)
            if f > 0:
                beissen += 1
                print(f"  BISS {name:50} {f} FAIL")
            elif f < 0:
                print(f"  ABBR {name:50} rc={rc} (kein Biss: Lauf ohne Bilanz)")
            else:
                print(f"  ZAHN {name:50} 0 FAIL – beisst NICHT")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if PARSER.read_text(encoding="utf-8") != quelle:
        print("ABBRUCH: der Parser im Baum hat sich waehrend des Laufs geaendert")
        return 2
    print(f"\n{beissen}/{len(PROBEN)} Proben beissen (im Baum nichts veraendert)")
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
