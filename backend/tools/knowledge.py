"""Knowledge Base Tool – Multi-Folder RAG mit PDF/DOCX Support und Index-Cache."""

import asyncio
import json
import math
import os
import re
import threading
from collections import Counter
from pathlib import Path

from backend.tools.base import BaseTool
from backend.config import config

PROJECT_ROOT = Path(__file__).parent.parent.parent
INDEX_CACHE_PATH = PROJECT_ROOT / "data" / "knowledge_index.json"
DEFAULT_FOLDER = "data/knowledge"
DEFAULT_MAX_SIZE_MB = 50

EXTENSIONS_TEXT = {
    ".txt", ".md", ".json", ".csv", ".log", ".py", ".sh",
    ".yaml", ".yml", ".cfg", ".conf", ".ini",
}
EXTENSIONS_PDF = {".pdf"}
EXTENSIONS_DOCX = {".docx", ".doc"}

_cache_lock = threading.Lock()


def _get_skill_config() -> dict:
    try:
        return config.get_skill_states().get("knowledge", {}).get("config", {})
    except Exception:
        return {}


def _get_folders() -> list[Path]:
    cfg = _get_skill_config()
    folders_str = cfg.get("folders", DEFAULT_FOLDER)
    paths = []
    for f in folders_str.split(","):
        f = f.strip()
        if not f:
            continue
        p = Path(f)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        paths.append(p)
    return paths or [PROJECT_ROOT / DEFAULT_FOLDER]


def _get_max_bytes() -> int:
    try:
        mb = float(_get_skill_config().get("max_file_size_mb", DEFAULT_MAX_SIZE_MB))
    except Exception:
        mb = DEFAULT_MAX_SIZE_MB
    return int(mb * 1024 * 1024)


def _extract_text(filepath: Path, max_bytes: int) -> str | None:
    """Extrahiert Text aus einer Datei (Text/PDF/DOCX)."""
    try:
        if filepath.stat().st_size > max_bytes:
            return None
    except Exception:
        return None

    suffix = filepath.suffix.lower()

    if suffix in EXTENSIONS_TEXT:
        try:
            return filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

    if suffix in EXTENSIONS_PDF:
        try:
            import pdfplumber
            with pdfplumber.open(str(filepath)) as pdf:
                texts = [p.extract_text() for p in pdf.pages if p.extract_text()]
            return "\n\n".join(texts) or None
        except ImportError:
            return None
        except Exception:
            return None

    if suffix in EXTENSIONS_DOCX:
        try:
            import docx
            doc = docx.Document(str(filepath))
            paras = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paras) or None
        except ImportError:
            return None
        except Exception:
            return None

    return None


def _tokenize(text: str) -> list[str]:
    return re.findall(r'\b\w{2,}\b', text.lower())


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


def _load_cache() -> dict:
    try:
        if INDEX_CACHE_PATH.exists():
            data = json.loads(INDEX_CACHE_PATH.read_text(encoding="utf-8"))
            if data.get("version") == 1:
                return data
    except Exception:
        pass
    return {"version": 1, "files": {}}


def _save_cache(cache: dict):
    try:
        INDEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _all_files(folders: list[Path]) -> list[Path]:
    """Gibt alle unterstützten Dateien in den konfigurierten Ordnern zurück."""
    all_exts = EXTENSIONS_TEXT | EXTENSIONS_PDF | EXTENSIONS_DOCX
    files = []
    for folder in folders:
        if not folder.exists():
            continue
        for root, dirs, fs in os.walk(folder):
            for f in fs:
                if Path(f).suffix.lower() in all_exts:
                    files.append(Path(root) / f)
    return files


def _rebuild_cache(folders: list[Path], max_bytes: int) -> dict:
    """Inkrementeller Index-Aufbau (Thread-sicher)."""
    with _cache_lock:
        cache = _load_cache()
        files = _all_files(folders)
        current_paths = {str(f) for f in files}

        # Gelöschte Dateien entfernen
        for p in list(cache["files"].keys()):
            if p not in current_paths:
                del cache["files"][p]

        # Neue/geänderte Dateien indexieren
        changed = False
        for filepath in files:
            path_str = str(filepath)
            try:
                mtime = filepath.stat().st_mtime
            except Exception:
                continue
            cached = cache["files"].get(path_str, {})
            if cached.get("mtime") == mtime:
                continue  # Unverändert

            text = _extract_text(filepath, max_bytes)
            if text and text.strip():
                cache["files"][path_str] = {
                    "mtime": mtime,
                    "chunks": _chunk_text(text),
                    "size": filepath.stat().st_size,
                }
            else:
                cache["files"].pop(path_str, None)
            changed = True

        if changed:
            _save_cache(cache)

        return cache


def _search(query: str, cache: dict, max_results: int) -> list[tuple[float, str, str]]:
    """TF-IDF Suche über alle gecachten Chunks."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    all_chunks: list[tuple[str, str]] = []
    for path_str, fdata in cache["files"].items():
        for chunk in fdata.get("chunks", []):
            all_chunks.append((path_str, chunk))

    if not all_chunks:
        return []

    doc_count = len(all_chunks)
    doc_freq: Counter = Counter()
    for _, chunk in all_chunks:
        tokens = set(_tokenize(chunk))
        for t in query_tokens:
            if t in tokens:
                doc_freq[t] += 1

    scored: list[tuple[float, str, str]] = []
    for path_str, chunk in all_chunks:
        tokens = _tokenize(chunk)
        if not tokens:
            continue
        tf = Counter(tokens)
        score = sum(
            (tf[qt] / len(tokens)) * (math.log((doc_count + 1) / (doc_freq.get(qt, 0) + 1)) + 1)
            for qt in query_tokens if qt in tf
        )
        if score > 0:
            try:
                rel = str(Path(path_str).relative_to(PROJECT_ROOT))
            except ValueError:
                rel = path_str
            scored.append((score, rel, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:max_results]


def get_stats() -> dict:
    """Statistiken für die API."""
    folders = _get_folders()
    files = _all_files(folders)
    cache = _load_cache()
    total_chunks = sum(len(d.get("chunks", [])) for d in cache["files"].values())
    total_size = sum(f.stat().st_size for f in files if f.exists())

    folder_list = []
    for f in folders:
        try:
            rel = str(f.relative_to(PROJECT_ROOT))
        except ValueError:
            rel = str(f)
        folder_list.append({"path": rel, "exists": f.exists()})

    has_pdf = False
    has_docx = False
    try:
        import pdfplumber
        has_pdf = True
    except ImportError:
        pass
    try:
        import docx
        has_docx = True
    except ImportError:
        pass

    return {
        "folders": folder_list,
        "total_files": len(files),
        "indexed_files": len(cache["files"]),
        "total_chunks": total_chunks,
        "total_size_bytes": total_size,
        "pdf_support": has_pdf,
        "docx_support": has_docx,
    }


def force_reindex() -> dict:
    """Erzwingt vollständigen Neuaufbau des Index."""
    with _cache_lock:
        try:
            INDEX_CACHE_PATH.unlink(missing_ok=True)
        except Exception:
            pass
    folders = _get_folders()
    cache = _rebuild_cache(folders, _get_max_bytes())
    total_chunks = sum(len(d.get("chunks", [])) for d in cache["files"].values())
    return {"indexed_files": len(cache["files"]), "total_chunks": total_chunks}


class KnowledgeTool(BaseTool):
    """Durchsucht die lokale Knowledge Base (RAG)."""

    @property
    def name(self) -> str:
        return "knowledge_search"

    @property
    def description(self) -> str:
        return (
            "Durchsucht die lokale Knowledge Base nach relevanten Dokumenten. "
            "Unterstützt Text-, Markdown-, PDF- und DOCX-Dateien aus konfigurierten Ordnern. "
            "Nutze dieses Tool wenn du Informationen zu einem Thema brauchst, "
            "die der Benutzer hinterlegt hat."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Suchbegriff(e) zum Durchsuchen der Knowledge Base."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximale Anzahl der Ergebnisse (Standard: 5)."
                }
            },
            "required": ["query"]
        }

    async def execute(self, **kwargs) -> str:
        query = kwargs.get("query", "")
        max_results = int(kwargs.get("max_results", 5))

        if not query.strip():
            return "❌ Leere Suchanfrage."

        # Standardordner sicherstellen
        (PROJECT_ROOT / DEFAULT_FOLDER).mkdir(parents=True, exist_ok=True)

        folders = _get_folders()
        cache = await asyncio.to_thread(_rebuild_cache, folders, _get_max_bytes())

        if not cache["files"]:
            folder_display = ", ".join(
                str(f.relative_to(PROJECT_ROOT)) if str(f).startswith(str(PROJECT_ROOT)) else str(f)
                for f in folders
            )
            return f"📂 Knowledge Base ist leer. Lege Dateien in einen der Ordner ab: {folder_display}"

        results = _search(query, cache, max_results)

        if not results:
            total = sum(len(d.get("chunks", [])) for d in cache["files"].values())
            return f"🔍 Keine Treffer für '{query}' ({len(cache['files'])} Dateien, {total} Chunks)."

        output = f"🔍 {len(results)} Treffer für '{query}':\n\n"
        for i, (score, filename, chunk) in enumerate(results, 1):
            output += f"--- [{i}] {filename} (Relevanz: {score:.2f}) ---\n"
            output += chunk.strip()[:1000] + "\n\n"

        return output


class KnowledgeManageTool(BaseTool):
    """Verwaltet Knowledge-Base-Ordner und den Suchindex."""

    @property
    def name(self) -> str:
        return "knowledge_manage"

    @property
    def description(self) -> str:
        return (
            "Verwaltet die Knowledge Base. "
            "Aktionen: list_folders (Ordner anzeigen), add_folder (Ordner hinzufügen), "
            "remove_folder (Ordner entfernen), reindex (Index neu aufbauen), "
            "list_docs (alle Dokumente auflisten), stats (Statistiken anzeigen)."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_folders", "add_folder", "remove_folder",
                             "reindex", "list_docs", "stats"],
                    "description": "Auszuführende Aktion."
                },
                "folder": {
                    "type": "string",
                    "description": "Ordnerpfad für add_folder/remove_folder."
                }
            },
            "required": ["action"]
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        folder_arg = kwargs.get("folder", "").strip()

        if action == "list_folders":
            folders = _get_folders()
            lines = []
            for f in folders:
                try:
                    rel = str(f.relative_to(PROJECT_ROOT))
                except ValueError:
                    rel = str(f)
                lines.append(f"  {'✅' if f.exists() else '❌'} {rel}")
            return "📁 Knowledge-Ordner:\n" + "\n".join(lines)

        elif action == "add_folder":
            if not folder_arg:
                return "❌ Kein Ordner angegeben."
            states = config.get_skill_states()
            state = states.get("knowledge", {})
            cfg = state.get("config", {})
            folders = [f.strip() for f in cfg.get("folders", DEFAULT_FOLDER).split(",") if f.strip()]
            if folder_arg in folders:
                return f"ℹ️ '{folder_arg}' ist bereits konfiguriert."
            folders.append(folder_arg)
            cfg["folders"] = ",".join(folders)
            state["config"] = cfg
            config.save_skill_state("knowledge", state)
            return f"✅ Ordner '{folder_arg}' hinzugefügt."

        elif action == "remove_folder":
            if not folder_arg:
                return "❌ Kein Ordner angegeben."
            states = config.get_skill_states()
            state = states.get("knowledge", {})
            cfg = state.get("config", {})
            folders = [f.strip() for f in cfg.get("folders", DEFAULT_FOLDER).split(",") if f.strip()]
            if folder_arg not in folders:
                return f"ℹ️ '{folder_arg}' nicht in der Liste."
            folders.remove(folder_arg)
            cfg["folders"] = ",".join(folders) if folders else DEFAULT_FOLDER
            state["config"] = cfg
            config.save_skill_state("knowledge", state)
            return f"✅ Ordner '{folder_arg}' entfernt."

        elif action == "reindex":
            result = await asyncio.to_thread(force_reindex)
            return f"✅ Index neu aufgebaut: {result['indexed_files']} Dateien, {result['total_chunks']} Chunks."

        elif action == "list_docs":
            folders = _get_folders()
            files = _all_files(folders)
            if not files:
                return "📂 Keine Dokumente gefunden."
            lines = []
            for f in sorted(files):
                size = f.stat().st_size
                size_str = f"{size/1024:.1f} KB" if size >= 1024 else f"{size} B"
                try:
                    rel = str(f.relative_to(PROJECT_ROOT))
                except ValueError:
                    rel = str(f)
                lines.append(f"  📄 {rel} ({size_str})")
            return f"📚 {len(files)} Dokument(e):\n" + "\n".join(lines)

        elif action == "stats":
            stats = get_stats()
            formats = ["Text/Markdown"]
            if stats["pdf_support"]:
                formats.append("PDF")
            else:
                formats.append("PDF ⚠️ (pdfplumber fehlt)")
            if stats["docx_support"]:
                formats.append("DOCX")
            else:
                formats.append("DOCX ⚠️ (python-docx fehlt)")
            size_mb = stats["total_size_bytes"] / (1024 * 1024)
            return (
                f"📊 Knowledge Base Statistiken:\n"
                f"  Dateien: {stats['total_files']} ({size_mb:.1f} MB)\n"
                f"  Im Index: {stats['indexed_files']} Dateien, {stats['total_chunks']} Chunks\n"
                f"  Formate: {', '.join(formats)}"
            )

        return f"❌ Unbekannte Aktion: {action}"
