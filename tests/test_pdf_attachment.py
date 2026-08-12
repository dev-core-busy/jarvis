#!/usr/bin/env python3
"""PDF-Anhaenge im Chat: Extraktion, OCR-Rueckfall, sichtbare Grenzen.

DER VORFALL (2026-08-12, ECHT): Ein Benutzer hat in /chat ein PDF hochgeladen
und um Auswertung gebeten. Gemeldet wurde "das Dokument wird nicht gefunden".

Ursache: der Extraktor begann mit ``import pypdf`` – und pypdf stand in KEINER
requirements.txt. Auf DEV war es zufaellig installiert, auf ECHT nicht (das venv
dort wurde mehrfach ausgeduennt). Die Funktion scheiterte deshalb an ihrer ersten
Zeile, und weil der OCR-Rueckfall IN derselben Funktion darunter stand, wurde
auch der nie erreicht – obwohl pdfplumber, pdf2image, pytesseract und tesseract
vorhanden sind. Der Benutzer bekam "Konnte nicht gelesen werden".

DIE PRUEFUNG, DIE DEN FEHLER FINDET, IST DIE BLOCKADE VON pypdf: der Test setzt
``sys.modules["pypdf"] = None`` und stellt damit genau die Produktivumgebung her.
Ohne diese Zeile laeuft der Test auf einem Rechner MIT pypdf gruen und beweist
nichts – so ist der Fehler monatelang unbemerkt geblieben.

Der Extraktor ist eine verschachtelte Funktion im WebSocket-Handler und damit
nicht importierbar; er wird per Quelltext herausgeschnitten und ausgefuehrt
(dasselbe Verfahren wie in tests/test_shell_redirects.py). Ein Import von
backend.main scheidet aus: das braucht fastapi und wuerde beim Laden von
backend.config die Live-settings.json zurueckschreiben.

Beendet sich mit **Exit 2**, wenn pdfplumber fehlt – "konnte nicht laufen" muss
von "bestanden" unterscheidbar bleiben.

Lauf:  venv/bin/python tests/test_pdf_attachment.py
"""
import glob
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "backend" / "main.py"

# Genau die Bedingung des Produktivsystems: pypdf ist nicht importierbar.
sys.modules["pypdf"] = None
sys.path.insert(0, str(ROOT))

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


def hole_funktion(name: str) -> str:
    """Schneidet eine (auch verschachtelte) Funktion per Quelltext heraus."""
    zeilen = MAIN.read_text(encoding="utf-8").split("\n")
    start = next(i for i, z in enumerate(zeilen) if z.strip().startswith(f"def {name}("))
    tiefe = len(zeilen[start]) - len(zeilen[start].lstrip())
    raus = [zeilen[start]]
    for z in zeilen[start + 1:]:
        if z.strip() and (len(z) - len(z.lstrip())) <= tiefe:
            break
        raus.append(z)
    return textwrap.dedent("\n".join(raus))


def text_pdf() -> bytes:
    """Minimales PDF MIT Textebene – von Hand gebaut, ohne Fremdbibliothek.

    reportlab ist nicht installiert und soffice waere eine schwere Abhaengigkeit
    fuer 650 Byte Nutzlast."""
    inhalt = (b"BT /F1 24 Tf 72 700 Td (Quartalsbericht Q2 2026) Tj ET\n"
              b"BT /F1 14 Tf 72 660 Td (Umsatz 1.216.500 EUR) Tj ET\n")
    objekte = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"endstream",
    ]
    aus = bytearray(b"%PDF-1.4\n")
    pos = []
    for i, o in enumerate(objekte, 1):
        pos.append(len(aus))
        aus += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(aus)
    aus += f"xref\n0 {len(objekte) + 1}\n".encode() + b"0000000000 65535 f \n"
    for p in pos:
        aus += f"{p:010d} 00000 n \n".encode()
    aus += (f"trailer\n<< /Size {len(objekte) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(aus)


def scan_pdf() -> bytes | None:
    """PDF OHNE Textebene (reines Bild) – fuer den OCR-Rueckfall."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    img = Image.new("RGB", (1240, 400), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
    except Exception:
        f = ImageFont.load_default()
    d.text((60, 60), "Rechnung 2026-0815", fill="black", font=f)
    d.text((60, 150), "Betrag: 4.950,00 EUR", fill="black", font=f)
    import io
    puffer = io.BytesIO()
    img.save(puffer, "PDF", resolution=150)
    return puffer.getvalue()


def main() -> int:
    try:
        import pdfplumber  # noqa: F401
    except Exception as e:
        print(f"ABBRUCH: pdfplumber fehlt ({e}) – der Test kann nichts beweisen.")
        print("Im venv laufen lassen:  venv/bin/python tests/test_pdf_attachment.py")
        return 2

    quelle = MAIN.read_text(encoding="utf-8")

    abschnitt("1) Quelltext-Waechter")
    pruefe("backend/main.py importiert pypdf nicht mehr",
           "import pypdf" not in quelle and "from pypdf" not in quelle)
    src = hole_funktion("_extract_pdf_text")
    pruefe("der Extraktor nutzt den Leser der Wissensdatenbank",
           "_extract_text" in src and "knowledge" in src)
    pruefe("OCR-Rueckfall ist weiterhin vorgesehen", "_ocr_pdf_bytes" in src)
    pruefe("Temporaerdatei wird wieder entfernt", "unlink" in src)
    pruefe("Deckel fuer den Prompt ist gesetzt", "_PDF_PROMPT_MAX_CHARS" in quelle)
    # Der Indizierungs-Deckel der Wissensdatenbank (4 Mio Zeichen) waere als
    # Prompt-Grenze unbrauchbar - das sind ueber eine Million Token.
    import re
    m = re.search(r"_PDF_PROMPT_MAX_CHARS\s*=\s*([\d_]+)", quelle)
    pruefe("Prompt-Deckel liegt unter 500.000 Zeichen",
           bool(m) and int(m.group(1).replace("_", "")) < 500_000,
           m.group(1) if m else "nicht gefunden")

    abschnitt("2) Zu grosse und gekuerzte PDFs werden GEMELDET, nicht verschluckt")
    # Ein wortlos uebersprungener Anhang ist fuer den Benutzer nicht von
    # "Dokument nicht gefunden" zu unterscheiden - genau der gemeldete Eindruck.
    pruefe("Groessengrenze erzeugt einen Hinweistext",
           "zu gross zum Verarbeiten" in quelle
           and quelle.count("zu gross zum Verarbeiten") >= 2,
           "auch der PDF-Zweig muss es melden")
    pruefe("Kuerzung wird ausgewiesen", "gekuerzt: von" in quelle)

    abschnitt("3) Der echte Extraktor – OHNE pypdf (Zustand auf ECHT)")
    umgebung = {"Path": Path, "print": print}
    exec(src, umgebung)
    extrahiere = umgebung["_extract_pdf_text"]

    vorher = set(glob.glob(os.path.join("/tmp", "tmp*.pdf")))

    t = extrahiere(text_pdf())
    pruefe("PDF mit Textebene: Inhalt erkannt", "Quartalsbericht" in t, repr(t[:80]))
    pruefe("PDF mit Textebene: Zahl unveraendert", "1.216.500" in t, repr(t[:120]))

    nachher = set(glob.glob(os.path.join("/tmp", "tmp*.pdf")))
    pruefe("keine Temporaerdatei liegengeblieben", vorher == nachher,
           str(nachher - vorher))

    abschnitt("4) OCR-Rueckfall bei gescanntem PDF")
    roh = scan_pdf()
    if roh is None:
        print("  (uebersprungen: Pillow fehlt)")
    else:
        try:
            import pdf2image, pytesseract  # noqa: F401
            import shutil
            hat_ocr = shutil.which("tesseract") is not None
        except Exception:
            hat_ocr = False
        if not hat_ocr:
            print("  (uebersprungen: pdf2image/pytesseract/tesseract nicht vollstaendig)")
        else:
            s = extrahiere(roh)
            pruefe("Scan-PDF: OCR liefert ueberhaupt Text", len(s.strip()) > 20, repr(s[:80]))
            pruefe("Scan-PDF: Rechnungsnummer erkannt", "0815" in s.replace(" ", ""),
                   repr(s[:120]))
            pruefe("Scan-PDF: Betrag erkannt", "4.950" in s or "4950" in s.replace(" ", ""),
                   repr(s[:120]))

    abschnitt("5) Gegenprobe: die alte Fassung unter denselben Bedingungen")
    u2 = {}
    exec("def alt(b):\n    import pypdf, io\n    return pypdf.PdfReader(io.BytesIO(b))\n", u2)
    try:
        u2["alt"](text_pdf())
        pruefe("alte Fassung scheitert ohne pypdf", False, "sie lief durch")
    except Exception as e:
        pruefe(f"alte Fassung scheitert ohne pypdf ({type(e).__name__})", True)

    abschnitt("6) Sperre fuer ausfuehrbare Anhaenge")
    # Konstanten + Funktion per Quelltext holen (kein Import von backend.main:
    # das braucht fastapi und wuerde die Live-settings.json anfassen).
    teile = []
    for name in ("_ANHANG_EXEC_EXT", "_ANHANG_EXEC_MIME", "_ANHANG_EXEC_MAGIC"):
        i = quelle.index(f"{name} = ")
        j = quelle.index("\n)\n", i) + 3 if quelle[i:i + 200].count("(") else quelle.index("\n}\n", i) + 3
        teile.append(quelle[i:j])
    teile.append(hole_funktion("_anhang_ausfuehrbar"))
    u = {}
    exec("\n".join(teile), u)
    ausf = u["_anhang_ausfuehrbar"]

    for endung, mime, roh, soll, was in [
        ("exe", "application/octet-stream", b"MZ\x90\x00", True, "Windows-Programm"),
        ("sh",  "text/plain",               b"#!/bin/bash\n", True, "Shell-Skript"),
        ("py",  "text/x-python",            b"print(1)", True, "Python-Datei"),
        ("jar", "application/java-archive", b"PK\x03\x04", True, "Java-Archiv"),
        ("dat", "application/octet-stream", b"MZ\x90\x00", True, "umbenannte .exe (Magie-Bytes)"),
        ("txt", "text/plain",               b"\x7fELF\x02", True, "umbenanntes ELF"),
        ("csv", "text/csv",                 b"#!/usr/bin/env python\n", True, "Shebang trotz .csv"),
        ("pdf", "application/pdf",          b"%PDF-1.4", False, "PDF"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 b"PK\x03\x04", False, "Excel-Datei"),
        ("csv", "text/csv",                 b"a;b\n1;2\n", False, "CSV"),
        ("zip", "application/zip",          b"PK\x03\x04", False, "ZIP (Container, wird nicht ausgefuehrt)"),
        ("eml", "message/rfc822",           b"From: x\n", False, "beliebige Unterlage"),
    ]:
        grund = ausf(endung, mime, roh)
        pruefe(f"{'abgewiesen' if soll else 'angenommen'}: {was}",
               bool(grund) == soll, repr(grund))

    abschnitt("7) Ablage: dauerhaft + Arbeitskopie")
    import tempfile, re as _re, stat as _stat
    with tempfile.TemporaryDirectory() as tmpdir:
        gemerkt = []

        class _DocsStub:
            @staticmethod
            def register_upload(name, benutzer):
                gemerkt.append((name, benutzer))

        u2 = {"Path": Path, "os": os, "_documents": _DocsStub,
              "__file__": str(Path(tmpdir) / "backend" / "main.py"), "print": print}
        exec(hole_funktion("_anhang_ablegen"), u2)
        ablegen = u2["_anhang_ablegen"]

        ziel, arbeit = ablegen(b"%PDF-1.4 inhalt", "Quartals bericht.pdf", "nexus\\andrea.ladd")
        pruefe("dauerhafte Kopie liegt in data/documents",
               ziel is not None and ziel.exists() and ziel.parent.name == "documents")
        pruefe("Sonderzeichen im Namen entschaerft", ziel is not None and " " not in ziel.name,
               ziel.name if ziel else "-")
        pruefe("Inhalt unveraendert", ziel is not None and ziel.read_bytes() == b"%PDF-1.4 inhalt")
        pruefe("Eigentuemer vermerkt", gemerkt and gemerkt[0][1] == "nexus\\andrea.ladd",
               str(gemerkt))
        pruefe("Arbeitskopie in /tmp mit erwartetem Namensmuster",
               arbeit is not None and bool(_re.match(r"anhang_[0-9a-f]{12}_", arbeit.name)),
               arbeit.name if arbeit else "-")
        pruefe("Arbeitskopie ist 0644 – KEIN Ausfuehrungsrecht",
               arbeit is not None and _stat.S_IMODE(arbeit.stat().st_mode) == 0o644,
               oct(_stat.S_IMODE(arbeit.stat().st_mode)) if arbeit else "-")
        # Zweiter Upload mit gleichem Namen darf den ersten nicht ueberschreiben
        ziel2, arbeit2 = ablegen(b"zweiter", "Quartals bericht.pdf", "nexus\\andrea.ladd")
        pruefe("gleicher Name kollidiert nicht", ziel2 is not None and ziel2.name != ziel.name
               and ziel.read_bytes() == b"%PDF-1.4 inhalt")
        for a in (arbeit, arbeit2):
            if a is not None:
                try:
                    a.unlink()
                except OSError:
                    pass

    abschnitt("8) Verdrahtung und Grenzen")
    pruefe("PDF-Zweig legt die Datei ab",
           quelle.count("_anhang_ablegen(") >= 3, "Definition + PDF-Zweig + Dokument-Zweig")
    pruefe("beide Zweige pruefen auf Ausfuehrbarkeit",
           quelle.count("_anhang_ausfuehrbar(") >= 3)
    pruefe("die alte Zulassungsliste _DOC_EXT ist weg", "_DOC_EXT" not in quelle)
    m = _re.search(r"_ATTACH_MAX_BYTES = (\d+) \* 1024 \* 1024", quelle)
    pruefe("Groessengrenze 50 MB", bool(m) and m.group(1) == "50",
           m.group(1) if m else "nicht gefunden")
    pruefe("Grenze wird base64-gerecht geprueft", "_ATTACH_MAX_B64" in quelle
           and "* 4 / 3" in quelle)
    # Ohne --ws-max-size ist die 50-MB-Zusage wertlos: uvicorn bricht die
    # VERBINDUNG bei 16 MB ab, bevor der Server die Datei sieht.
    for datei, muster in (("start_jarvis.sh", "--ws-max-size"), ("run.sh", "--ws-max-size"),
                          ("backend/main.py", "ws_max_size=")):
        inhalt = (ROOT / datei).read_text(encoding="utf-8")
        pruefe(f"{datei}: WebSocket-Grenze gesetzt", muster in inhalt)
    ws = _re.search(r"--ws-max-size (\d+)", (ROOT / "start_jarvis.sh").read_text(encoding="utf-8"))
    pruefe("WebSocket-Grenze liegt ueber der Anhang-Grenze",
           bool(ws) and int(ws.group(1)) > 50 * 1024 * 1024 * 4 / 3,
           ws.group(1) if ws else "-")

    print(f"\n{ok} ok, {fehler} Fehler ({ok + fehler} Pruefungen)")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
