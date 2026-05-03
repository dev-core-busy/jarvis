"""Jarvis Web-Extraktor – URL / Datei abrufen, per LLM strukturieren, als Pending-Dokument speichern."""

import asyncio
import json
import re
import time
import uuid
from pathlib import Path

PENDING_DIR = Path("data/knowledge/pending")

# ─── LLM-Prompt ──────────────────────────────────────────────────────────────

_EXTRACT_PROMPT = """\
Analysiere den folgenden Inhalt und erstelle eine strukturierte Wissensextraktion.

Ausgabe AUSSCHLIESSLICH als valides JSON-Objekt mit diesen Feldern:
{
  "title": "Prägnanter Titel des Inhalts",
  "summary": "Zusammenfassung in 3-5 Sätzen",
  "facts": [
    "Kernfakt 1 als vollständiger Satz",
    "Kernfakt 2 als vollständiger Satz"
  ],
  "qa_pairs": [
    {"q": "Frage 1?", "a": "Antwort 1."},
    {"q": "Frage 2?", "a": "Antwort 2."}
  ]
}

Regeln:
- Sprache: Deutsch (auch wenn der Quelltext Englisch ist)
- 3–10 Kernfakten
- 5–15 Frage-Antwort-Paare – präzise, eigenständig verständlich, direkt aus dem Inhalt
- Keine Quellenangaben, keine URLs in den Antworten
- Kein Markdown, keine Code-Blöcke um das JSON

Inhalt:
---
{content}
---
"""

# ─── Datei-Typ Erkennung ─────────────────────────────────────────────────────

# Content-Type → Dateiendung für direkte Datei-Downloads via URL
_CT_TO_SUFFIX: dict[str, str] = {
    "application/pdf":                                                          ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword":                                                       ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":       ".xlsx",
    "application/vnd.ms-excel":                                                 ".xls",
    "application/vnd.oasis.opendocument.spreadsheet":                          ".ods",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/csv":                                                                 ".csv",
    "audio/mpeg":   ".mp3",
    "audio/mp4":    ".m4a",
    "audio/wav":    ".wav",
    "audio/ogg":    ".ogg",
    "video/mp4":    ".mp4",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
}
_FILE_SUFFIXES: frozenset[str] = frozenset(
    ".pdf .docx .doc .xlsx .xls .ods .pptx .csv "
    ".mp3 .m4a .wav .ogg .mp4 .mov .mkv .avi".split()
)


# ─── URL abrufen ─────────────────────────────────────────────────────────────

async def _http_get(url: str):
    """Führt einen GET-Request aus und gibt das httpx-Response-Objekt zurück."""
    try:
        import httpx
    except ImportError:
        raise RuntimeError("httpx nicht installiert. Bitte: pip install httpx")

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; JarvisBot/1.0; +https://jarvis-ai.info)",
        "Accept": "*/*",
        "Accept-Language": "de,en;q=0.7",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp


def _html_to_text(html: str) -> tuple[str, str]:
    """Einfache HTML→Text Konvertierung ohne externe Deps."""
    # Titel extrahieren
    title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    title = _strip_tags(title_m.group(1)) if title_m else "Unbekannter Titel"
    title = title.strip()[:200]

    # Script/Style/Nav/Footer entfernen
    for tag in ('script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript'):
        html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', ' ', html, flags=re.I | re.S)

    # Blockstruktur mit Leerzeilen
    for tag in ('p', 'div', 'section', 'article', 'h1', 'h2', 'h3', 'h4', 'li', 'br', 'tr'):
        html = re.sub(rf'</?{tag}[^>]*>', '\n', html, flags=re.I)

    # Restliche Tags entfernen
    text = _strip_tags(html)

    # Whitespace normalisieren
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if len(l) > 2]
    text = '\n'.join(lines)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return title, text.strip()


def _strip_tags(html: str) -> str:
    return re.sub(r'<[^>]+>', '', html)


# ─── LLM-Extraktion ──────────────────────────────────────────────────────────

async def extract_from_url(url: str) -> dict:
    """URL → strukturiertes Pending-Dokument.
    Erkennt automatisch ob die URL auf eine HTML-Seite oder eine Datei zeigt
    (PDF, DOCX, XLSX, PPTX, Audio/Video …) und wählt die passende Pipeline."""
    from pathlib import Path as _Path

    resp = await _http_get(url)

    # Content-Type auswerten (nur Typ, ohne Parameter wie charset)
    ct = resp.headers.get("content-type", "").lower().split(";")[0].strip()
    url_suffix = _Path(url.split("?")[0]).suffix.lower()

    # Datei-Pipeline? → Content-Type hat Vorrang, dann URL-Endung
    detected_suffix = _CT_TO_SUFFIX.get(ct) or (url_suffix if url_suffix in _FILE_SUFFIXES else None)

    if detected_suffix:
        # Dateiname aus URL ableiten
        raw_name = _Path(url.split("?")[0]).name
        filename = raw_name if raw_name.endswith(detected_suffix) else (raw_name or "dokument") + detected_suffix
        # Datei-Pipeline mit Original-URL als Quelle
        return await extract_from_file(filename, resp.content, source_url=url)

    # ── HTML-Pipeline ──────────────────────────────────────────────────────────
    from backend.config import config
    from backend.llm import get_provider
    from google.genai import types

    page_title, content = _html_to_text(resp.text)
    content = content[:8000]

    if not content.strip():
        raise ValueError("Seite enthält keinen lesbaren Text")

    # 2. LLM-Extraktion
    provider = get_provider(
        config.LLM_PROVIDER,
        config.current_api_key,
        auth_method=config.current_auth_method,
        session_key=config.current_session_key,
        prompt_tool_calling=False,
    )

    prompt = _EXTRACT_PROMPT.replace("{content}", content)
    response = await provider.generate_response(
        model=config.current_model,
        system_prompt="Du bist ein Wissensextraktor. Antworte ausschließlich mit dem angeforderten JSON.",
        contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
        tools=[],
    )

    # 3. JSON parsen
    raw_text = ""
    if response.parts:
        for p in response.parts:
            if getattr(p, "text", None):
                raw_text += p.text

    # JSON aus der Antwort extrahieren (auch wenn LLM Markdown-Blöcke liefert)
    json_match = re.search(r'\{[\s\S]*\}', raw_text)
    if not json_match:
        raise ValueError(f"LLM lieferte kein gültiges JSON: {raw_text[:300]}")

    data = json.loads(json_match.group(0))

    # 4. Pending-Dokument erstellen
    doc_id = str(uuid.uuid4())[:8]
    qa_pairs = []
    for pair in data.get("qa_pairs", []):
        qa_pairs.append({
            "id": str(uuid.uuid4())[:6],
            "q": str(pair.get("q", "")).strip(),
            "a": str(pair.get("a", "")).strip(),
            "approved": True,  # Default: alle vorausgewählt
        })

    pending = {
        "id": doc_id,
        "url": url,
        "title": str(data.get("title", page_title)).strip()[:300],
        "summary": str(data.get("summary", "")).strip(),
        "facts": [str(f).strip() for f in data.get("facts", []) if str(f).strip()],
        "qa_pairs": qa_pairs,
        "created_at": int(time.time()),
        "status": "pending",
    }

    save_pending(pending)
    return pending


# ─── Pending-Dokument-Verwaltung ─────────────────────────────────────────────

def _ensure_dir():
    PENDING_DIR.mkdir(parents=True, exist_ok=True)


def save_pending(doc: dict) -> str:
    _ensure_dir()
    path = PENDING_DIR / f"{doc['id']}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc["id"]


def list_pending() -> list[dict]:
    _ensure_dir()
    result = []
    for f in sorted(PENDING_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            result.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return result


def get_pending(doc_id: str) -> dict | None:
    path = PENDING_DIR / f"{doc_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def update_pending(doc_id: str, data: dict) -> bool:
    doc = get_pending(doc_id)
    if not doc:
        return False
    # Erlaubte Felder aktualisieren
    for field in ("title", "summary", "facts", "qa_pairs"):
        if field in data:
            doc[field] = data[field]
    save_pending(doc)
    return True


def approve_pending(doc_id: str) -> dict:
    """Genehmigte Items als .md in die Wissens-DB schreiben.
    Das Pending-Dokument bleibt erhalten (status='approved') fuer die Verlaufsansicht."""
    doc = get_pending(doc_id)
    if not doc:
        raise FileNotFoundError(f"Pending-Dokument {doc_id} nicht gefunden")

    from backend.tools.knowledge import PROJECT_ROOT, _get_folders, force_reindex

    target_dir = _get_folders()[0]
    target_dir.mkdir(parents=True, exist_ok=True)

    # Sicherer Dateiname
    safe_title = re.sub(r'[^\w\s\-äöüÄÖÜß]', '', doc["title"])
    safe_title = re.sub(r'\s+', '_', safe_title.strip())[:60]
    filename = f"extract_{doc_id}_{safe_title}.md"
    target_path = target_dir / filename

    # Markdown-Dokument aufbauen
    source_label = doc.get("source_name") or doc.get("url", "")
    lines = [f"# {doc['title']}", "", f"> Quelle: {source_label}", ""]

    if doc.get("summary"):
        lines += ["## Zusammenfassung", "", doc["summary"], ""]

    approved_facts = doc.get("facts", [])
    if approved_facts:
        lines += ["## Kernfakten", ""]
        for fact in approved_facts:
            lines.append(f"- {fact}")
        lines.append("")

    approved_qa = [p for p in doc.get("qa_pairs", []) if p.get("approved", True)]
    if approved_qa:
        lines += ["## Fragen & Antworten", ""]
        for pair in approved_qa:
            if pair.get("q") and pair.get("a"):
                lines += [f"**F: {pair['q']}**", f"A: {pair['a']}", ""]

    md_content = "\n".join(lines)
    target_path.write_text(md_content, encoding="utf-8")

    # Pending-Dokument als "approved" markieren (nicht loeschen – Verlauf erhalten)
    doc["status"] = "approved"
    doc["approved_at"] = int(time.time())
    doc["file"] = str(target_path.relative_to(PROJECT_ROOT))
    doc["qa_count"] = len(approved_qa)
    doc["fact_count"] = len(approved_facts)
    save_pending(doc)

    # Wissens-Index neu aufbauen (im Hintergrund-Thread)
    def _reindex_and_trim():
        force_reindex()
        try:
            from backend.tools.vector_store import release_memory_to_os
            release_memory_to_os()
        except Exception:
            pass

    import threading
    threading.Thread(target=_reindex_and_trim, daemon=True).start()

    return {
        "file": doc["file"],
        "qa_count": len(approved_qa),
        "fact_count": len(approved_facts),
    }


def delete_pending(doc_id: str) -> bool:
    path = PENDING_DIR / f"{doc_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ─── Datei-Extraktion ────────────────────────────────────────────────────────

async def extract_from_file(filename: str, content: bytes, source_url: str | None = None) -> dict:
    """Datei → Text-Extraktion → LLM → Pending-Dokument.
    Unterstützt: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV und Audio/Video via Whisper.
    source_url: wird gesetzt wenn die Datei über eine URL heruntergeladen wurde."""
    import asyncio as _asyncio
    import os as _os
    import tempfile as _tempfile
    from pathlib import Path as _Path

    suffix = _Path(filename).suffix.lower() or ".bin"

    # Temp-Datei mit korrektem Suffix anlegen (damit _extract_text das Format erkennt)
    fd, tmp_path = _tempfile.mkstemp(suffix=suffix, prefix="jarvis_ext_")
    try:
        _os.close(fd)
        _Path(tmp_path).write_bytes(content)

        # Blockierende Text-Extraktion (PDF-Parsing, Whisper, …) im Thread ausführen
        from backend.tools.knowledge import _extract_text
        text = await _asyncio.to_thread(
            _extract_text, _Path(tmp_path), 50 * 1024 * 1024
        )
    finally:
        try:
            _os.unlink(tmp_path)
        except Exception:
            pass

    if not text or not text.strip():
        raise ValueError(
            f"Datei enthält keinen extrahierbaren Text (Format: {suffix}). "
            "Unterstützt: PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, "
            "MP3/M4A/WAV (Transkription via Whisper), MP4/MOV/MKV."
        )

    # Auf 8 000 Zeichen kürzen (LLM-Kontext)
    text = text[:8000]

    # LLM-Extraktion – gleiche Pipeline wie URL-Extraktion
    from backend.config import config
    from backend.llm import get_provider
    from google.genai import types

    provider = get_provider(
        config.LLM_PROVIDER,
        config.current_api_key,
        auth_method=config.current_auth_method,
        session_key=config.current_session_key,
        prompt_tool_calling=False,
    )

    prompt = _EXTRACT_PROMPT.replace("{content}", f"[Datei: {filename}]\n\n{text}")
    response = await provider.generate_response(
        model=config.current_model,
        system_prompt="Du bist ein Wissensextraktor. Antworte ausschließlich mit dem angeforderten JSON.",
        contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
        tools=[],
    )

    raw_text = ""
    if response.parts:
        for p in response.parts:
            if getattr(p, "text", None):
                raw_text += p.text

    json_match = re.search(r'\{[\s\S]*\}', raw_text)
    if not json_match:
        raise ValueError(f"LLM lieferte kein gültiges JSON: {raw_text[:300]}")

    data = json.loads(json_match.group(0))

    doc_id = str(uuid.uuid4())[:8]
    qa_pairs = [
        {
            "id": str(uuid.uuid4())[:6],
            "q": str(pair.get("q", "")).strip(),
            "a": str(pair.get("a", "")).strip(),
            "approved": True,
        }
        for pair in data.get("qa_pairs", [])
    ]

    pending = {
        "id":          doc_id,
        "url":         source_url or f"file://{filename}",
        "source_type": "url" if source_url else "file",
        "source_name": filename,
        "title":   str(data.get("title", filename)).strip()[:300],
        "summary": str(data.get("summary", "")).strip(),
        "facts":   [str(f).strip() for f in data.get("facts", []) if str(f).strip()],
        "qa_pairs":    qa_pairs,
        "created_at":  int(time.time()),
        "status":      "pending",
    }

    save_pending(pending)
    return pending
