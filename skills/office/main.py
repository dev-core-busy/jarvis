"""Office-Skill – erzeugt und liest Office-Dokumente (Word/Excel/PowerPoint)
und exportiert sie nach PDF.

Ansatz: programmatisch via python-docx / openpyxl / python-pptx (deterministisch,
headless). PDF-Export via LibreOffice (soffice --headless --convert-to pdf).

Dateien landen im Server-Dateisystem unter data/documents/ mit Capability-Name
(<32-Hex>__<Name>.<ext>) und werden via /api/documents/{name} zum Download
ausgeliefert (siehe backend/main.py).
"""

import os
import re
import json
import uuid
import asyncio
import subprocess
from pathlib import Path

from backend.tools.base import BaseTool

# data/documents/ relativ zum Projekt-Root (skills/office/ -> ../../)
DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "documents"

_UML = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
})


def _safe_base(name: str, default: str = "dokument") -> str:
    """Macht aus einem (ggf. unsicheren) Namen einen ASCII-sicheren Basisnamen."""
    base = os.path.splitext(os.path.basename(name or ""))[0].translate(_UML)
    base = re.sub(r"[^A-Za-z0-9_\- ]+", "", base).strip().replace(" ", "_")
    return base or default


def _new_path(friendly: str, ext: str):
    """Erzeugt einen neuen Capability-Pfad. Gibt (disk_path, fname, download_name) zurueck."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex  # 32 Hex-Zeichen
    base = _safe_base(friendly)
    fname = f"{token}__{base}.{ext}"
    return DOCS_DIR / fname, fname, f"{base}.{ext}"


def _ok(download_name: str, fname: str, disk_path: Path, extra: str = "") -> str:
    # Markdown-Download-Link, den die Frontends als Download-Chip rendern.
    return (
        f"✅ '{download_name}' wurde erstellt.\n\n"
        f"[📥 {download_name} herunterladen](/api/documents/{fname})"
        + (f"\n\n{extra}" if extra else "")
    )


def _resolve_existing(path: str) -> Path | None:
    """Loest einen Eingabepfad zu einer existierenden Datei auf.

    Akzeptiert: reinen Dateinamen in data/documents/, '/api/documents/<name>'
    oder einen beliebigen (absoluten/relativen) Dateisystempfad.
    """
    if not path:
        return None
    path = path.strip()
    if path.startswith("/api/documents/"):
        path = path[len("/api/documents/"):]
    cand = DOCS_DIR / path
    if cand.exists():
        return cand
    p = Path(path)
    if p.exists():
        return p
    return None


# ─────────────────────────────────────────────────────────────────────────
# Word
# ─────────────────────────────────────────────────────────────────────────
class CreateWordTool(BaseTool):
    @property
    def name(self) -> str:
        return "office_create_word"

    @property
    def description(self) -> str:
        return (
            "Erstellt ein Word-Dokument (.docx). 'content' wird zeilenweise interpretiert: "
            "'# ' = Ueberschrift 1, '## ' = Ueberschrift 2, '### ' = Ueberschrift 3, "
            "'- ' oder '* ' = Aufzaehlung, '1. ' = nummerierte Liste, Leerzeile = neuer Absatz, "
            "sonst normaler Absatz. Gibt eine Download-URL zurueck."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "filename": {"type": "STRING", "description": "Dateiname/Titel des Dokuments (ohne Pfad), z.B. 'Quartalsbericht'."},
                "title": {"type": "STRING", "description": "Optionaler Titel, der als grosse Ueberschrift oben eingefuegt wird."},
                "content": {"type": "STRING", "description": "Inhalt des Dokuments (mit einfacher Markdown-Syntax, siehe Beschreibung)."},
            },
            "required": ["filename", "content"],
        }

    async def execute(self, filename: str = "", title: str = "", content: str = "", **kwargs) -> str:
        if not filename:
            return "Fehler: 'filename' ist Pflicht."
        try:
            from docx import Document
        except Exception as e:
            return f"Fehler: python-docx nicht verfuegbar ({e})."

        doc = Document()
        if title:
            doc.add_heading(title, level=0)

        for raw in (content or "").split("\n"):
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("### "):
                doc.add_heading(stripped[4:].strip(), level=3)
            elif stripped.startswith("## "):
                doc.add_heading(stripped[3:].strip(), level=2)
            elif stripped.startswith("# "):
                doc.add_heading(stripped[2:].strip(), level=1)
            elif stripped.startswith("- ") or stripped.startswith("* "):
                doc.add_paragraph(stripped[2:].strip(), style="List Bullet")
            elif re.match(r"^\d+\.\s", stripped):
                doc.add_paragraph(re.sub(r"^\d+\.\s", "", stripped), style="List Number")
            else:
                doc.add_paragraph(stripped)

        disk, fname, dl = _new_path(filename, "docx")
        try:
            doc.save(str(disk))
        except Exception as e:
            return f"Fehler beim Speichern: {e}"
        return _ok(dl, fname, disk)


# ─────────────────────────────────────────────────────────────────────────
# Excel
# ─────────────────────────────────────────────────────────────────────────
class CreateExcelTool(BaseTool):
    @property
    def name(self) -> str:
        return "office_create_excel"

    @property
    def description(self) -> str:
        return (
            "Erstellt eine Excel-Tabelle (.xlsx). Entweder 'rows' (2D-Liste von Zellen) "
            "mit optionalen 'headers' und 'sheet_name' fuer EIN Blatt, ODER 'sheets' "
            "(Objekt: Blattname -> {headers:[...], rows:[[...]]}) fuer mehrere Blaetter. "
            "Gibt eine Download-URL zurueck."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "filename": {"type": "STRING", "description": "Dateiname (ohne Pfad), z.B. 'Umsatz'."},
                "sheet_name": {"type": "STRING", "description": "Blattname fuer den Einzelblatt-Modus (Standard 'Tabelle1')."},
                "headers": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Optionale Kopfzeile (Einzelblatt-Modus)."},
                "rows": {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}, "description": "Datenzeilen als 2D-Liste (Einzelblatt-Modus)."},
                "sheets": {"type": "OBJECT", "description": "Mehrblatt-Modus: { 'Blattname': { 'headers': [...], 'rows': [[...]] } }."},
            },
            "required": ["filename"],
        }

    def _write_sheet(self, ws, headers, rows):
        if headers:
            ws.append(list(headers))
            # Kopfzeile fett
            from openpyxl.styles import Font
            for cell in ws[1]:
                cell.font = Font(bold=True)
        for row in (rows or []):
            ws.append(list(row) if isinstance(row, (list, tuple)) else [row])

    async def execute(self, filename: str = "", sheet_name: str = "", headers=None,
                       rows=None, sheets=None, **kwargs) -> str:
        if not filename:
            return "Fehler: 'filename' ist Pflicht."
        try:
            from openpyxl import Workbook
        except Exception as e:
            return f"Fehler: openpyxl nicht verfuegbar ({e})."

        wb = Workbook()
        if sheets and isinstance(sheets, dict):
            first = True
            for sname, sdef in sheets.items():
                sdef = sdef or {}
                ws = wb.active if first else wb.create_sheet()
                ws.title = str(sname)[:31] or "Tabelle"
                self._write_sheet(ws, sdef.get("headers"), sdef.get("rows"))
                first = False
        else:
            ws = wb.active
            ws.title = (sheet_name or "Tabelle1")[:31]
            self._write_sheet(ws, headers, rows)

        disk, fname, dl = _new_path(filename, "xlsx")
        try:
            wb.save(str(disk))
        except Exception as e:
            return f"Fehler beim Speichern: {e}"
        return _ok(dl, fname, disk)


# ─────────────────────────────────────────────────────────────────────────
# PowerPoint
# ─────────────────────────────────────────────────────────────────────────
class CreatePowerPointTool(BaseTool):
    @property
    def name(self) -> str:
        return "office_create_powerpoint"

    @property
    def description(self) -> str:
        return (
            "Erstellt eine PowerPoint-Praesentation (.pptx). 'slides' ist eine Liste von "
            "Folien-Objekten: { 'title': 'Folientitel', 'bullets': ['Punkt 1','Punkt 2'] } "
            "oder { 'title': ..., 'content': 'Freitext' }. Optional 'title' fuer eine "
            "Titelfolie am Anfang. Gibt eine Download-URL zurueck."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "filename": {"type": "STRING", "description": "Dateiname (ohne Pfad)."},
                "title": {"type": "STRING", "description": "Optionaler Titel fuer eine Titelfolie am Anfang."},
                "subtitle": {"type": "STRING", "description": "Optionaler Untertitel der Titelfolie."},
                "slides": {"type": "ARRAY", "items": {"type": "OBJECT"}, "description": "Liste der Inhaltsfolien (siehe Beschreibung)."},
            },
            "required": ["filename", "slides"],
        }

    async def execute(self, filename: str = "", title: str = "", subtitle: str = "",
                       slides=None, **kwargs) -> str:
        if not filename:
            return "Fehler: 'filename' ist Pflicht."
        try:
            from pptx import Presentation
        except Exception as e:
            return f"Fehler: python-pptx nicht verfuegbar ({e})."

        prs = Presentation()
        # Titelfolie
        if title:
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = title
            if subtitle and len(slide.placeholders) > 1:
                slide.placeholders[1].text = subtitle

        for sl in (slides or []):
            if isinstance(sl, str):
                sl = {"title": sl}
            layout = prs.slide_layouts[1]  # Titel + Inhalt
            slide = prs.slides.add_slide(layout)
            slide.shapes.title.text = str(sl.get("title", ""))
            body = slide.placeholders[1].text_frame if len(slide.placeholders) > 1 else None
            if body is not None:
                bullets = sl.get("bullets")
                if bullets and isinstance(bullets, (list, tuple)):
                    body.text = str(bullets[0])
                    for b in bullets[1:]:
                        p = body.add_paragraph()
                        p.text = str(b)
                elif sl.get("content"):
                    body.text = str(sl.get("content"))

        disk, fname, dl = _new_path(filename, "pptx")
        try:
            prs.save(str(disk))
        except Exception as e:
            return f"Fehler beim Speichern: {e}"
        return _ok(dl, fname, disk)


# ─────────────────────────────────────────────────────────────────────────
# Lesen
# ─────────────────────────────────────────────────────────────────────────
class ReadDocumentTool(BaseTool):
    @property
    def name(self) -> str:
        return "office_read"

    @property
    def description(self) -> str:
        return (
            "Liest den Textinhalt eines Office-Dokuments (.docx, .xlsx, .pptx) und gibt ihn "
            "als Text zurueck. 'path' kann ein Dateiname aus data/documents/, eine "
            "/api/documents/-URL oder ein beliebiger Server-Pfad sein."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Pfad/Name des zu lesenden Dokuments."},
            },
            "required": ["path"],
        }

    async def execute(self, path: str = "", **kwargs) -> str:
        p = _resolve_existing(path)
        if not p:
            return f"Fehler: Datei nicht gefunden: {path}"
        ext = p.suffix.lower()
        try:
            if ext == ".docx":
                from docx import Document
                doc = Document(str(p))
                parts = [par.text for par in doc.paragraphs if par.text.strip()]
                for tbl in doc.tables:
                    for row in tbl.rows:
                        parts.append(" | ".join(c.text for c in row.cells))
                text = "\n".join(parts)
            elif ext == ".xlsx":
                from openpyxl import load_workbook
                wb = load_workbook(str(p), read_only=True, data_only=True)
                blocks = []
                for ws in wb.worksheets:
                    blocks.append(f"# Blatt: {ws.title}")
                    for row in ws.iter_rows(values_only=True):
                        blocks.append(" | ".join("" if c is None else str(c) for c in row))
                text = "\n".join(blocks)
            elif ext == ".pptx":
                from pptx import Presentation
                prs = Presentation(str(p))
                blocks = []
                for i, slide in enumerate(prs.slides, 1):
                    blocks.append(f"# Folie {i}")
                    for shape in slide.shapes:
                        if shape.has_text_frame and shape.text_frame.text.strip():
                            blocks.append(shape.text_frame.text)
                text = "\n".join(blocks)
            else:
                return f"Fehler: Nicht unterstuetzte Endung '{ext}' (docx/xlsx/pptx)."
        except Exception as e:
            return f"Fehler beim Lesen: {e}"

        if len(text) > 20000:
            text = text[:20000] + "\n… [gekuerzt]"
        return text or "(leeres Dokument)"


# ─────────────────────────────────────────────────────────────────────────
# PDF-Export via LibreOffice
# ─────────────────────────────────────────────────────────────────────────
class ExportPdfTool(BaseTool):
    @property
    def name(self) -> str:
        return "office_to_pdf"

    @property
    def description(self) -> str:
        return (
            "Exportiert ein Office-Dokument (.docx/.xlsx/.pptx) nach PDF (via LibreOffice). "
            "'path' kann ein Dateiname aus data/documents/, eine /api/documents/-URL oder ein "
            "Server-Pfad sein. Gibt eine Download-URL fuer das PDF zurueck."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Pfad/Name des zu konvertierenden Dokuments."},
            },
            "required": ["path"],
        }

    async def execute(self, path: str = "", **kwargs) -> str:
        src = _resolve_existing(path)
        if not src:
            return f"Fehler: Datei nicht gefunden: {path}"
        if src.suffix.lower() not in (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"):
            return f"Fehler: Format '{src.suffix}' wird fuer PDF-Export nicht unterstuetzt."

        DOCS_DIR.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        # Eigenes UserInstallation-Profil, um Konflikte mit dem Desktop-LibreOffice zu vermeiden
        profile = f"/tmp/lo_jarvis_{token}"
        cmd = [
            "soffice", "--headless", "--norestore", "--convert-to", "pdf",
            "--outdir", str(DOCS_DIR),
            f"-env:UserInstallation=file://{profile}",
            str(src),
        ]
        try:
            proc = await asyncio.to_thread(
                subprocess.run, cmd,
                capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return "Fehler: PDF-Export hat das Zeitlimit (120s) ueberschritten."
        except Exception as e:
            return f"Fehler beim PDF-Export: {e}"

        # soffice legt <stem>.pdf in outdir ab
        produced = DOCS_DIR / (src.stem + ".pdf")
        if not produced.exists():
            return f"Fehler: PDF wurde nicht erzeugt. soffice: {proc.stderr or proc.stdout}".strip()

        # In Capability-Schema umbenennen (Download-Name aus Original-Basis ableiten)
        base = src.stem.split("__", 1)[-1] if "__" in src.stem else src.stem
        disk, fname, dl = _new_path(base, "pdf")
        try:
            produced.rename(disk)
        except Exception:
            # Fallback: Inhalt kopieren
            disk.write_bytes(produced.read_bytes())
            produced.unlink(missing_ok=True)
        return _ok(dl, fname, disk)


def get_tools():
    return [
        CreateWordTool(),
        CreateExcelTool(),
        CreatePowerPointTool(),
        ReadDocumentTool(),
        ExportPdfTool(),
    ]
