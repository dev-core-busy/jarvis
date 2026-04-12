"""Knowledge Base Tool – Multi-Folder RAG mit Vektor-Suche (ChromaDB) und TF-IDF Fallback."""

import asyncio
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
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
EXTENSIONS_XLSX = {".xlsx", ".xls"}
EXTENSIONS_PPTX = {".pptx"}
EXTENSIONS_VIDEO = {".mp4", ".mkv", ".avi", ".webm", ".mov", ".m4v", ".flv", ".wmv"}
EXTENSIONS_AUDIO = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus"}

_cache_lock = threading.Lock()
_log = logging.getLogger("jarvis.knowledge")

# ─── Indizierungs-Fortschritt (thread-sicher) ────────────────────────────────
_index_progress: dict = {"running": False, "phase": "", "done": 0, "total": 0, "vector_done": 0, "vector_total": 0, "error": ""}
_progress_lock = threading.Lock()

def get_index_progress() -> dict:
    with _progress_lock:
        return dict(_index_progress)

def _set_progress(**kwargs):
    with _progress_lock:
        _index_progress.update(kwargs)

# ─── Vector Store (optional, Fallback auf TF-IDF) ────────────────
_vector_store = None
_vector_store_checked = False

# ─── Gecachte Stats (Format-Support ändert sich nie zur Laufzeit) ─
_stats_cache: dict | None = None
_stats_cache_lock = threading.Lock()


def _get_vector_store():
    """Gibt VectorStore-Singleton zurueck oder None wenn Dependencies fehlen."""
    global _vector_store, _vector_store_checked
    if _vector_store_checked:
        return _vector_store
    _vector_store_checked = True
    try:
        from backend.tools.vector_store import VectorStore
        vs = VectorStore(PROJECT_ROOT / "data" / "vector_store")
        _vector_store = vs
        _log.info("VectorStore verfuegbar – semantische Suche aktiv")
        return vs
    except ImportError as e:
        _log.info(f"VectorStore nicht verfuegbar (chromadb/sentence-transformers fehlt): {e}")
        return None
    except Exception as e:
        _log.warning(f"VectorStore Initialisierung fehlgeschlagen: {e}")
        return None


def _rebuild_vector_index(folders: list[Path], max_bytes: int) -> bool:
    """Inkrementeller Vektor-Index Aufbau. Gibt True zurueck wenn verfuegbar."""
    vs = _get_vector_store()
    if vs is None:
        return False

    files = _all_files(folders)
    current_paths = {str(f) for f in files}
    indexed = vs.get_indexed_files()

    # Geloeschte Dateien entfernen
    for path_str in indexed:
        if path_str not in current_paths:
            vs.remove_file(path_str)

    # Neue/geaenderte Dateien ermitteln
    to_index = []
    for filepath in files:
        path_str = str(filepath)
        try:
            mtime = filepath.stat().st_mtime
        except Exception:
            continue
        if indexed.get(path_str) != mtime:
            to_index.append(filepath)

    _set_progress(phase="Vektor", vector_done=0, vector_total=len(to_index))

    changed = 0
    for i, filepath in enumerate(to_index):
        path_str = str(filepath)
        _set_progress(vector_done=i + 1, phase=f"Vektor: {filepath.name[:40]}")
        try:
            mtime = filepath.stat().st_mtime
            text = _extract_text(filepath, max_bytes)
            if text and text.strip():
                chunks = _chunk_text(text)
                vs.add_chunks(path_str, chunks, mtime)
                changed += 1
            else:
                vs.remove_file(path_str)
        except Exception:
            pass

    _set_progress(vector_done=len(to_index), vector_total=len(to_index))
    if changed:
        _log.info(f"Vektor-Index aktualisiert: {changed} Datei(en)")
    return True


def _vector_search(query: str, max_results: int) -> list[tuple[float, str, str]] | None:
    """Semantische Suche via VectorStore. Gibt None zurueck wenn nicht verfuegbar."""
    vs = _get_vector_store()
    if vs is None:
        return None
    results = vs.search(query, max_results)
    if not results:
        return None
    # Relative Pfade berechnen
    converted = []
    for score, file_path, chunk in results:
        try:
            rel = str(Path(file_path).relative_to(PROJECT_ROOT))
        except ValueError:
            rel = file_path
        converted.append((score, rel, chunk))
    return converted


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


def _transcribe_media(filepath: Path) -> str | None:
    """Transkribiert Audio/Video via ffmpeg + faster-whisper."""
    if not shutil.which("ffmpeg"):
        _log.warning("ffmpeg nicht gefunden – Video/Audio-Support deaktiviert")
        return None

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        _log.warning("faster-whisper nicht installiert – Video/Audio-Support deaktiviert")
        return None

    tmpdir = None
    try:
        # Audio aus Video/Audio extrahieren → WAV (16kHz mono, optimal für Whisper)
        tmpdir = tempfile.mkdtemp(prefix="jarvis_kb_")
        wav_path = os.path.join(tmpdir, "audio.wav")

        cmd = [
            "ffmpeg", "-i", str(filepath),
            "-vn",                    # kein Video
            "-acodec", "pcm_s16le",   # PCM 16-bit
            "-ar", "16000",           # 16kHz
            "-ac", "1",               # Mono
            "-y",                     # Überschreiben
            wav_path
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0 or not os.path.exists(wav_path):
            _log.error(f"ffmpeg fehlgeschlagen für {filepath}: {result.stderr[:200]}")
            return None

        # Whisper-Modell laden (eigene Instanz, nicht die aus main.py)
        # Nutze "small" als Default – guter Kompromiss aus Geschwindigkeit und Qualität
        cfg = _get_skill_config()
        model_name = cfg.get("whisper_model", "small")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")

        segments, info = model.transcribe(wav_path, language="de")
        text = " ".join([seg.text for seg in segments]).strip()

        if text:
            # Dateiname + erkannte Sprache als Kontext
            header = f"[Transkription: {filepath.name} | Sprache: {info.language}]"
            _log.info(f"Transkription OK für {filepath.name}: {len(text)} Zeichen")
            return f"{header}\n{text}"

        _log.warning(f"Keine Sprache erkannt in {filepath.name}")
        return None

    except subprocess.TimeoutExpired:
        _log.error(f"ffmpeg Timeout für {filepath}")
        return None
    except Exception as e:
        _log.error(f"Transkription fehlgeschlagen für {filepath}: {e}")
        return None
    finally:
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_text(filepath: Path, max_bytes: int) -> str | None:
    """Extrahiert Text aus einer Datei (Text/PDF/DOCX/XLSX/PPTX/Video/Audio)."""
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

    if suffix in EXTENSIONS_XLSX:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(filepath), read_only=True, data_only=True)
            sheets_text = []
            for ws in wb.worksheets:
                rows = []
                for row in ws.iter_rows(values_only=True):
                    cells = [str(c) if c is not None else "" for c in row]
                    if any(c.strip() for c in cells):
                        rows.append("\t".join(cells))
                if rows:
                    header = f"[Sheet: {ws.title}]"
                    sheets_text.append(header + "\n" + "\n".join(rows))
            wb.close()
            return "\n\n".join(sheets_text) or None
        except ImportError:
            return None
        except Exception:
            return None

    if suffix in EXTENSIONS_PPTX:
        try:
            from pptx import Presentation
            prs = Presentation(str(filepath))
            slides_text = []
            for i, slide in enumerate(prs.slides, 1):
                texts = []
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        for para in shape.text_frame.paragraphs:
                            t = para.text.strip()
                            if t:
                                texts.append(t)
                    if shape.has_table:
                        for row in shape.table.rows:
                            cells = [cell.text.strip() for cell in row.cells]
                            if any(cells):
                                texts.append("\t".join(cells))
                if texts:
                    slides_text.append(f"[Folie {i}]\n" + "\n".join(texts))
            return "\n\n".join(slides_text) or None
        except ImportError:
            return None
        except Exception:
            return None

    if suffix in EXTENSIONS_VIDEO | EXTENSIONS_AUDIO:
        # Video/Audio: max_bytes-Check großzügiger (200MB Default für Medien)
        media_max = max(max_bytes, 200 * 1024 * 1024)
        try:
            if filepath.stat().st_size > media_max:
                _log.warning(f"Mediendatei zu groß: {filepath} ({filepath.stat().st_size / 1024 / 1024:.0f} MB)")
                return None
        except Exception:
            return None
        return _transcribe_media(filepath)

    return None


def _tokenize(text: str) -> list[str]:
    return re.findall(r'\b\w{2,}\b', text.lower())


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
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
    all_exts = EXTENSIONS_TEXT | EXTENSIONS_PDF | EXTENSIONS_DOCX | EXTENSIONS_XLSX | EXTENSIONS_PPTX | EXTENSIONS_VIDEO | EXTENSIONS_AUDIO
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

        # Neue/geänderte Dateien ermitteln
        to_index = []
        for filepath in files:
            path_str = str(filepath)
            try:
                mtime = filepath.stat().st_mtime
            except Exception:
                continue
            cached = cache["files"].get(path_str, {})
            if cached.get("mtime") != mtime:
                to_index.append(filepath)

        _set_progress(phase="TF-IDF", done=0, total=len(to_index))

        changed = False
        for i, filepath in enumerate(to_index):
            path_str = str(filepath)
            _set_progress(done=i + 1, phase=f"TF-IDF: {filepath.name[:40]}")
            try:
                mtime = filepath.stat().st_mtime
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
            except Exception:
                pass

        if changed:
            _save_cache(cache)

        _set_progress(done=len(to_index), total=len(to_index))
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


def _get_static_stats() -> dict:
    """Format-Support + ChromaDB-Client – wird einmalig gecacht (ändert sich nicht)."""
    global _stats_cache
    with _stats_cache_lock:
        if _stats_cache is not None:
            return _stats_cache
        has_pdf = has_docx = has_xlsx = has_pptx = has_video = False
        try:
            import pdfplumber; has_pdf = True
        except ImportError: pass
        try:
            import docx; has_docx = True
        except ImportError: pass
        try:
            import openpyxl; has_xlsx = True
        except ImportError: pass
        try:
            from pptx import Presentation; has_pptx = True
        except ImportError: pass
        try:
            from faster_whisper import WhisperModel
            if shutil.which("ffmpeg"): has_video = True
        except ImportError: pass

        _stats_cache = {
            "pdf_support": has_pdf, "docx_support": has_docx,
            "xlsx_support": has_xlsx, "pptx_support": has_pptx,
            "video_support": has_video,
        }
        return _stats_cache


def get_stats() -> dict:
    """Statistiken für die API – schnell, kein Netzwerk-/Modell-Scan."""
    folders = _get_folders()

    # Ordner-Liste ohne Netzwerk-Scan
    folder_list = []
    for f in folders:
        try:
            rel = str(f.relative_to(PROJECT_ROOT))
        except ValueError:
            rel = str(f)
        folder_list.append({"path": rel, "exists": f.exists()})

    # Nur gecachten TF-IDF-Index laden
    cache = _load_cache()
    total_chunks = sum(len(d.get("chunks", [])) for d in cache["files"].values())
    total_size   = sum(d.get("size", 0) for d in cache["files"].values())

    # Vektor-DB: gecachter Client, nur count() aufrufen
    has_vector = False
    vector_chunks = 0
    vector_files = 0
    try:
        import chromadb as _chroma
        from backend.tools.vector_store import COLLECTION_NAME
        _vs_dir = PROJECT_ROOT / "data" / "vector_store"
        _db = _vs_dir / "chroma.sqlite3"
        if _db.exists() and _db.stat().st_size > 4096:
            _c = _chroma.PersistentClient(path=str(_vs_dir))
            _col = _c.get_or_create_collection(COLLECTION_NAME)
            vector_chunks = _col.count()
            has_vector = vector_chunks > 0
            vector_files = len(cache["files"]) if has_vector else 0
    except Exception:
        pass

    return {
        "folders": folder_list,
        "total_files": len(cache["files"]),
        "indexed_files": len(cache["files"]),
        "total_chunks": total_chunks,
        "total_size_bytes": total_size,
        **_get_static_stats(),
        "vector_search": has_vector,
        "vector_files": vector_files,
        "vector_chunks": vector_chunks,
        "search_mode": _get_skill_config().get("search_mode", "auto"),
        "indexing": get_index_progress()["running"],
    }


def force_reindex() -> dict:
    """Erzwingt vollstaendigen Neuaufbau des Index (TF-IDF + Vektor)."""
    _set_progress(running=True, phase="Starte...", done=0, total=0, vector_done=0, vector_total=0, error="")
    try:
        with _cache_lock:
            try:
                INDEX_CACHE_PATH.unlink(missing_ok=True)
            except Exception:
                pass

        # Vektor-Index ebenfalls leeren
        vs = _get_vector_store()
        if vs:
            vs.clear()

        folders = _get_folders()
        max_bytes = _get_max_bytes()
        cache = _rebuild_cache(folders, max_bytes)
        _rebuild_vector_index(folders, max_bytes)

        total_chunks = sum(len(d.get("chunks", [])) for d in cache["files"].values())
        vector_info = ""
        if vs:
            vector_info = f", Vektor: {vs.chunk_count()} Chunks"
        _set_progress(running=False, phase="Fertig")
        return {"indexed_files": len(cache["files"]), "total_chunks": total_chunks, "vector_info": vector_info}
    except Exception as e:
        _set_progress(running=False, phase="Fehler", error=str(e))
        raise


class KnowledgeTool(BaseTool):
    """Durchsucht die lokale Knowledge Base (RAG)."""

    @property
    def name(self) -> str:
        return "knowledge_search"

    @property
    def description(self) -> str:
        return (
            "IMMER ZUERST AUFRUFEN bei Fragen zu Produkten, Software, Technik oder Kunden! "
            "Durchsucht die lokale Knowledge Base mit Kundendokumentation, Produkthandbüchern, "
            "Installationsanleitungen, technischen Spezifikationen und internen Vorgaben. "
            "Enthält PDFs, DOCX, PPTX, Excel und Textdateien. "
            "VOR jeder Web- oder Google-Suche dieses Tool verwenden – "
            "die Wissensdatenbank hat aktuelle, kundenbezogene Informationen die im Internet nicht zu finden sind."
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
        max_results = int(kwargs.get("max_results", 8))

        if not query.strip():
            return "❌ Fehler: query-Parameter fehlt. Bitte knowledge_search erneut aufrufen und einen konkreten Suchbegriff aus der Benutzeranfrage als 'query' übergeben (z.B. knowledge_search({'query': 'LDT Import Medistar'}))."

        # Standardordner sicherstellen
        (PROJECT_ROOT / DEFAULT_FOLDER).mkdir(parents=True, exist_ok=True)

        folders = _get_folders()
        max_bytes = _get_max_bytes()

        # Suchmodus aus Config: "auto" (default), "tfidf", "vector"
        cfg = _get_skill_config()
        search_mode_cfg = cfg.get("search_mode", "auto")

        # TF-IDF Cache immer aufbauen (wird fuer Stats/Management gebraucht)
        cache = await asyncio.to_thread(_rebuild_cache, folders, max_bytes)

        if not cache["files"]:
            folder_display = ", ".join(
                str(f.relative_to(PROJECT_ROOT)) if str(f).startswith(str(PROJECT_ROOT)) else str(f)
                for f in folders
            )
            return f"📂 Knowledge Base ist leer. Lege Dateien in einen der Ordner ab: {folder_display}"

        results = None
        search_mode = "TF-IDF"

        # Vektor-Suche wenn gewuenscht
        if search_mode_cfg in ("auto", "vector"):
            has_vector = await asyncio.to_thread(_rebuild_vector_index, folders, max_bytes)
            if has_vector:
                results = await asyncio.to_thread(_vector_search, query, max_results)
                if results:
                    search_mode = "Vektor"

        # TF-IDF wenn gewuenscht oder als Fallback
        if not results and search_mode_cfg in ("auto", "tfidf"):
            results = _search(query, cache, max_results)
            search_mode = "TF-IDF"

        if not results:
            total = sum(len(d.get("chunks", [])) for d in cache["files"].values())
            return f"🔍 Keine Treffer für '{query}' ({len(cache['files'])} Dateien, {total} Chunks)."

        output = f"🔍 {len(results)} Treffer für '{query}' ({search_mode}):\n\n"
        for i, (score, filename, chunk) in enumerate(results, 1):
            output += f"--- [{i}] {filename} (Relevanz: {score:.2f}) ---\n"
            output += chunk.strip()[:1500] + "\n\n"

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
            return f"✅ Index neu aufgebaut: {result['indexed_files']} Dateien, {result['total_chunks']} Chunks{result.get('vector_info', '')}."

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
            if stats["xlsx_support"]:
                formats.append("Excel")
            else:
                formats.append("Excel ⚠️ (openpyxl fehlt)")
            if stats["pptx_support"]:
                formats.append("PowerPoint")
            else:
                formats.append("PowerPoint ⚠️ (python-pptx fehlt)")
            if stats["video_support"]:
                formats.append("Video/Audio")
            else:
                formats.append("Video/Audio ⚠️ (ffmpeg + faster-whisper nötig)")
            size_mb = stats["total_size_bytes"] / (1024 * 1024)

            # Vektor-Info
            if stats.get("vector_search"):
                vector_line = f"\n  🧠 Vektor-Suche: aktiv ({stats['vector_files']} Dateien, {stats['vector_chunks']} Chunks)"
            else:
                vector_line = "\n  🧠 Vektor-Suche: inaktiv (chromadb/sentence-transformers fehlt)"

            return (
                f"📊 Knowledge Base Statistiken:\n"
                f"  Dateien: {stats['total_files']} ({size_mb:.1f} MB)\n"
                f"  TF-IDF Index: {stats['indexed_files']} Dateien, {stats['total_chunks']} Chunks"
                f"{vector_line}\n"
                f"  Formate: {', '.join(formats)}"
            )

        return f"❌ Unbekannte Aktion: {action}"
