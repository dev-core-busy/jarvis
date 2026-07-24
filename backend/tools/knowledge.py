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
import time
from collections import Counter
from pathlib import Path

from backend.tools.base import BaseTool
from backend.config import config

PROJECT_ROOT = Path(__file__).parent.parent.parent
INDEX_CACHE_PATH = PROJECT_ROOT / "data" / "knowledge_index.json"
DEFAULT_FOLDER = "data/knowledge"
DEFAULT_MAX_SIZE_MB = 50

# Maximale Zeichen pro Treffer-Chunk in der Tool-Ausgabe.
# MUSS groesser sein als ein vollstaendiger Chunk (_chunk_text: 200 Woerter,
# ~1600 Zeichen) – sonst wird der gefundene Treffer mitten im Text abgeschnitten
# und das LLM antwortet auf einem Ausschnitt, der die Antwort gar nicht enthaelt.
CHUNK_OUTPUT_LIMIT = 3000

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
EXTENSIONS_IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}

_cache_lock = threading.Lock()
_log = logging.getLogger("jarvis.knowledge")

# ─── Indizierungs-Fortschritt (thread-sicher) ────────────────────────────────
# started_at/finished_at sind Unix-Zeitstempel (float) – die Oberflaeche zeigt
# damit Startzeit und Laufdauer an.
_index_progress: dict = {"running": False, "phase": "", "done": 0, "total": 0,
                         "vector_done": 0, "vector_total": 0, "vector_base": 0,
                         "chunks": 0, "error": "", "current_file": "",
                         "started_at": 0.0, "finished_at": 0.0, "cancelled": False}
_progress_lock = threading.Lock()
# Alle wieviel Dateien der Bulk-Reindex auf Platte sichert + Speicher ans OS
# zurueckgibt. Kompromiss: haeufiger = weniger Verlust bei Absturz, aber mehr
# I/O; 25 verliert im schlimmsten Fall 25 Dateien, die die Wiederaufnahme ohnehin
# nachholt.
CHECKPOINT_EVERY = 25
# Metadaten des gerade laufenden Laufs (fuer die Platten-Checkpoints).
_current_run: dict = {}
# Verhindert PARALLELE Reindex-Laeufe – sonst teilen sie sich _index_progress und
# die Zaehler ueberschreiben sich (z.B. vector_done=48 / vector_total=10 -> 480%).
_reindex_lock = threading.Lock()
# Kam waehrend eines laufenden Reindex eine weitere Anfrage, wird GENAU EINMAL
# nachgeholt (coalesced) – so gehen frisch hinzugefuegte Dateien nicht verloren.
_reindex_rerun = threading.Event()
# Abbruchwunsch des Benutzers. Wird nur zwischen zwei Dateien geprueft – eine
# laufende Einbettung wird nicht mitten drin abgeschossen.
_reindex_cancel = threading.Event()

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
        _log.info(f"VectorStore nicht verfuegbar (faiss-cpu/sentence-transformers fehlt): {e}")
        return None
    except Exception as e:
        _log.warning(f"VectorStore Initialisierung fehlgeschlagen: {e}")
        return None


def preload_embedding_model():
    """Lädt das Embedding-Modell im Hintergrund vor (vermeidet Kaltstart bei erster Suche)."""
    vs = _get_vector_store()
    if vs is None:
        print("[knowledge] Embedding-Preload übersprungen (kein VectorStore)", flush=True)
        return
    try:
        from backend.tools.vector_store import _get_embedding_model
        print("[knowledge] Lade Embedding-Modell vor...", flush=True)
        _get_embedding_model()
        print("[knowledge] Embedding-Modell vorgeladen ✓", flush=True)
    except Exception as e:
        print(f"[knowledge] Embedding-Modell Preload fehlgeschlagen: {e}", flush=True)


def _rebuild_vector_index(folders: list[Path], max_bytes: int, force: bool = False) -> bool:
    """Inkrementeller Vektor-Index Aufbau. Gibt True zurueck wenn Index Inhalt hat.

    force=False (Suchpfad): Kein Bulk-Aufbau bei leerem Index, max. INLINE_LIMIT Dateien.
    force=True  (Neu-Indizieren): Alle Dateien werden verarbeitet, kein Limit.
    """
    vs = _get_vector_store()
    if vs is None:
        return False

    indexed = vs.get_indexed_files()

    if not force:
        # Leerer Index: kein Inline-Bulk-Indexing
        if not indexed:
            _log.debug("Vektor-Index leer – bitte Neu-Indizieren ausfuehren")
            return False

    files = _all_files(folders)
    current_paths = {str(f) for f in files}

    # Geloeschte Dateien entfernen
    for path_str in list(indexed.keys()):
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

    if not force and len(to_index) > INLINE_LIMIT:
        _log.info(f"{len(to_index)} neue/geaenderte Dateien – nur {INLINE_LIMIT} inline, Rest via Neu-Indizieren")
        to_index = to_index[:INLINE_LIMIT]

    # Bereits indizierte Dateien zaehlen mit (der Voll-Reindex ueberspringt
    # unveraenderte Dateien) – so zeigt der Balken bei einer WIEDERAUFNAHME nach
    # Absturz den echten Gesamtstand, nicht nur die Rest-Dateien.
    already = max(0, len(indexed) - len([f for f in to_index if str(f) in indexed]))
    total = len(to_index)
    _set_progress(phase="Vektor", vector_done=0, vector_total=total, vector_base=already)

    changed = 0
    cancelled = False
    for i, filepath in enumerate(to_index):
        # Abbruch nur ZWISCHEN zwei Dateien – die bereits geschriebenen Chunks
        # bleiben gueltig, der Index ist danach lediglich unvollstaendig.
        if _reindex_cancel.is_set():
            cancelled = True
            _log.info(f"Vektor-Index: Abbruch nach {i}/{total} Dateien")
            break
        path_str = str(filepath)
        _set_progress(vector_done=i + 1, phase=f"Vektor: {filepath.name[:40]}",
                      current_file=filepath.name)
        try:
            mtime = filepath.stat().st_mtime
            text = _extract_text(filepath, max_bytes)
            if text and text.strip():
                chunks = _chunk_text(text)
                # save=False: nicht bei jeder Datei den ganzen Index schreiben.
                vs.add_chunks(path_str, chunks, mtime, save=False)
                changed += 1
            else:
                vs.remove_file(path_str)
        except Exception:
            pass

        # Laufende Chunk-Zahl mitfuehren, damit ALLE offenen Clients dieselbe
        # Live-Zahl sehen (sonst zeigt ein Browser, der die Kachel vor dem Lauf
        # geladen hat, dauerhaft den alten Stand – z.B. 16453 statt 9715).
        try:
            _set_progress(chunks=vs.chunk_count())
        except Exception:
            pass

        # Checkpoint: alle CHECKPOINT_EVERY Dateien auf Platte sichern, Speicher
        # ans OS zurueckgeben (verhindert Heap-Wachstum → OOM) und den
        # Fortschritt persistent festhalten (welche Datei, wie weit) – so ist
        # nach einem Absturz sichtbar, wo es endete, und die Wiederaufnahme
        # setzt genau dort fort.
        if (i + 1) % CHECKPOINT_EVERY == 0:
            try:
                vs.save()
                from backend.tools.vector_store import release_memory_to_os
                release_memory_to_os()
            except Exception as e:
                _log.warning(f"Checkpoint fehlgeschlagen: {e}")
            _write_run_checkpoint(done=i + 1, total=total,
                                  current_file=filepath.name,
                                  indexed_files=already + changed)

    # Rest sichern (der letzte, unvollstaendige Checkpoint-Block).
    try:
        vs.save()
    except Exception as e:
        _log.warning(f"Abschluss-Speichern fehlgeschlagen: {e}")

    if not cancelled:
        _set_progress(vector_done=total, vector_total=total)
    if changed:
        _log.info(f"Vektor-Index aktualisiert: {changed} Datei(en)")
    return vs.chunk_count() > 0


# Gelernte Konversationen (learned/conv_*.md) tragen die urspruengliche
# Benutzerfrage als Ueberschrift. Dadurch sind sie fuer genau diese Frage der
# perfekte semantische Treffer – unabhaengig davon, ob ihr Inhalt zur Frage
# passt – und verdraengen die Primaerdokumentation vom ersten Platz. Das ist
# eine selbstverstaerkende Schleife: eine falsche Antwort wird gelernt und beim
# naechsten Mal bevorzugt wieder ausgeliefert. Deshalb im Ranking abwerten.
LEARNED_PENALTY = 0.6


def _is_learned_note(path_str: str) -> bool:
    p = path_str.replace("\\", "/")
    return "/knowledge/learned/" in p or "/knowledge/pending/" in p


def _vector_search(query: str, max_results: int) -> list[tuple[float, str, str]] | None:
    """Hybride Suche (semantisch + BM25) via VectorStore.

    Gibt None zurueck wenn kein VectorStore verfuegbar ist.
    """
    vs = _get_vector_store()
    if vs is None:
        return None
    # Ueber-abfragen: die Abwertung gelernter Notizen sortiert danach um.
    results = vs.search_hybrid(query, max(max_results * 2, 20))
    if not results:
        return None

    converted = []
    for score, file_path, chunk in results:
        try:
            rel = str(Path(file_path).relative_to(PROJECT_ROOT))
        except ValueError:
            rel = file_path
        if _is_learned_note(file_path):
            score *= LEARNED_PENALTY
        converted.append((score, rel, chunk))

    converted.sort(key=lambda x: x[0], reverse=True)
    return converted[:max_results]


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


# ─── Nicht-blockierende Verfügbarkeitspruefung fuer (Netz-)Ordner ─────────────
# Ein totes CIFS/NFS-Mount laesst exists()/os.walk() bis zum Kernel-Timeout
# blockieren ("Lädt…" haengt ewig). Wir pruefen exists() daher in einem
# Daemon-Thread mit kurzem Timeout und cachen ein negatives Ergebnis kurz.
_avail_down_until: dict[str, float] = {}
_AVAIL_DOWN_TTL = 30.0   # Sekunden, wie lange ein totes Mount als "weg" gilt


def _safe_exists(path, timeout: float = 2.0) -> bool:
    """exists()-Check, der bei toten Netzlaufwerken NICHT blockiert.

    Laeuft in einem Daemon-Thread; Timeout oder OSError => False. Ein als
    "blockierend/tot" erkanntes Verzeichnis wird kurz gecacht, damit nicht
    jeder Aufruf (z.B. Stats-Polling) erneut ins Timeout laeuft."""
    key = str(path)
    now = time.time()
    until = _avail_down_until.get(key)
    if until and now < until:
        return False

    result = {"ok": False}

    def _check():
        try:
            result["ok"] = os.path.exists(key)
        except OSError:
            result["ok"] = False

    th = threading.Thread(target=_check, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        # Haengt am toten Mount -> kurz als "weg" merken und den Thread
        # (Daemon) sich selbst beenden lassen, sobald der Kernel zurueckkehrt.
        _avail_down_until[key] = now + _AVAIL_DOWN_TTL
        _log.warning("Ordner reagiert nicht (Netzlaufwerk tot?), wird übersprungen: %s", key)
        return False
    _avail_down_until.pop(key, None)
    return bool(result["ok"])


def _bounded_call(fn, timeout: float, default):
    """Führt ``fn`` in einem Daemon-Thread aus und bricht nach ``timeout`` ab.

    Gibt bei Timeout ``default`` zurück (der haengende Thread laeuft als Daemon
    im Hintergrund aus). Schützt Hot-Paths (z.B. Stats) vor toten Netzlaufwerken."""
    box = {"val": default}

    def _run():
        try:
            box["val"] = fn()
        except Exception:
            box["val"] = default

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    return box["val"]


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


def _ocr_image(filepath: Path) -> str | None:
    """OCR auf einem Bild via Tesseract (Deutsch+Englisch). Gibt erkannten Text zurueck.

    Lokal, kein LLM. Voraussetzung: System-Paket 'tesseract-ocr' (+ Sprachpakete)
    und Python-Pakete 'pytesseract' + 'Pillow'. Fehlt etwas, wird None zurueckgegeben
    (das LLM kann dann ggf. noch das Bild selbst auswerten – siehe extract_from_file).
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        _log.warning("pytesseract/Pillow nicht installiert – Bild-OCR deaktiviert")
        return None
    try:
        # Sprachen auf verfuegbare beschraenken (deu/eng), sonst Tesseract-Default
        lang = None
        try:
            avail = set(pytesseract.get_languages(config=""))
            sel = [l for l in ("deu", "eng") if l in avail]
            lang = "+".join(sel) if sel else None
        except Exception:
            lang = "deu+eng"
        with Image.open(str(filepath)) as img:
            img.load()
            text = pytesseract.image_to_string(img, lang=lang) if lang else pytesseract.image_to_string(img)
        text = (text or "").strip()
        return text or None
    except Exception as e:
        _log.warning(f"Bild-OCR fehlgeschlagen ({filepath.name}): {e}")
        return None


def _ocr_pdf_bytes(pdf_bytes: bytes, max_pages: int = 20) -> str:
    """OCR-Fallback fuer gescannte/bildbasierte PDFs (ohne Text-Layer).

    Rendert die Seiten via pdf2image/poppler zu Bildern und liest sie per
    Tesseract (deu+eng). Gibt erkannten Text zurueck oder '' wenn nicht moeglich.
    """
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        _log.warning("pdf2image/pytesseract fehlt – PDF-OCR-Fallback deaktiviert")
        return ""
    try:
        images = convert_from_bytes(pdf_bytes, dpi=200, first_page=1, last_page=max_pages)
    except Exception as e:
        _log.warning("PDF->Bild fehlgeschlagen: %s", e)
        return ""
    try:
        avail = set(pytesseract.get_languages(config=""))
        lang = "+".join([l for l in ("deu", "eng") if l in avail]) or None
    except Exception:
        lang = "deu+eng"
    out = []
    for idx, img in enumerate(images, 1):
        try:
            t = pytesseract.image_to_string(img, lang=lang) if lang else pytesseract.image_to_string(img)
            t = (t or "").strip()
            if t:
                out.append(f"[Seite {idx} (OCR)]\n{t}")
        except Exception:
            continue
    return "\n\n".join(out)


# Obergrenze fuer extrahierten Text pro Datei. Ein einzelnes grosses
# Datenmodell-PDF (z.B. "NEXUS KIS Datenmodell – Tabellen", 9 MB) erzeugt sonst
# zig MB Text → hunderttausende Woerter → tausende Chunks → mehrere GB RAM und
# OOM. Darueber hinaus bringt Volltext kaum zusaetzlichen Trefferwert.
MAX_EXTRACT_CHARS = 4_000_000   # ~4 MB Text ≈ max. ~3000 Chunks


def _extract_text(filepath: Path, max_bytes: int) -> str | None:
    """Extrahiert Text (Text/PDF/DOCX/XLSX/PPTX/Bild-OCR/Video/Audio) und deckelt
    die Laenge, damit ein einzelnes Riesendokument nicht den Speicher sprengt."""
    text = _extract_text_raw(filepath, max_bytes)
    if text and len(text) > MAX_EXTRACT_CHARS:
        _log.warning(f"Extrahierter Text gekappt ({len(text)} → {MAX_EXTRACT_CHARS} Zeichen): {filepath.name}")
        text = text[:MAX_EXTRACT_CHARS]
    return text


def _extract_text_raw(filepath: Path, max_bytes: int) -> str | None:
    """Rohe Extraktion (ohne Laengen-Deckelung – die macht ``_extract_text``)."""
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
            texts = []
            total = 0
            with pdfplumber.open(str(filepath)) as pdf:
                for p in pdf.pages:
                    t = p.extract_text()
                    # WICHTIG: pdfplumber cached pro Seite alle Layout-Objekte und
                    # gibt sie nie von selbst frei. Ueber hunderte/tausende Seiten
                    # (grosse Datenmodell-PDFs) waechst der RAM so auf viele GB →
                    # OOM-Kill. flush_cache() gibt den Seiten-Cache sofort frei.
                    try:
                        p.flush_cache()
                    except Exception:
                        pass
                    if t:
                        texts.append(t)
                        total += len(t) + 2
                        if total >= MAX_EXTRACT_CHARS:
                            _log.warning(f"PDF-Extraktion bei {MAX_EXTRACT_CHARS} Zeichen "
                                         f"gestoppt (grosses Dokument): {filepath.name}")
                            break
            combined = "\n\n".join(texts)
            # OCR-Fallback bei gescannten/bildbasierten PDFs (kein/zu wenig Text-Layer)
            if len(combined.strip()) < 80:
                ocr = _ocr_pdf_bytes(filepath.read_bytes())
                if len(ocr.strip()) > len(combined.strip()):
                    return ocr or None
            return combined or None
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

    if suffix in EXTENSIONS_IMAGE:
        return _ocr_image(filepath)

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


def _chunk_text(text: str, chunk_size: int = 200, overlap: int = 40) -> list[str]:
    """Zerlegt Text in ueberlappende Wort-Chunks.

    chunk_size MUSS zum Embedding-Modell passen: multilingual-e5-small hat ein
    Limit von 512 Tokens und schneidet laengere Chunks stillschweigend ab. Ein
    800-Wort-Chunk deutscher Fachtexte sind ~2000 Tokens – davon waren 75%
    unsichtbar (gemessen: die Beschreibung von @STR_UCASE lag hinter dem
    Cut-off und war ueber die Vektorsuche nicht auffindbar). 200 Woerter bleiben
    mit Reserve unter dem Limit und schaerfen zugleich das Ranking, weil ein
    Chunk dann ein Thema behandelt statt eines halben Kapitels.
    """
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


def _is_pending_path(p) -> bool:
    """True fuer den internen Entwurfs-Speicher (data/knowledge/pending/*.json).
    Diese Extraktor-Entwuerfe sind KEIN Wissen und duerfen weder indiziert noch
    in der Dokument-/Gruppenliste auftauchen."""
    return "data/knowledge/pending/" in str(p or "").replace("\\", "/")


def _indexed_rel_paths() -> list:
    """Alle Datei-Pfade, die im INDEX (lokale Wissensdatenbank) stehen.

    Quelle: TF-IDF-Cache (``knowledge_index.json``) + FAISS-Meta
    (``faiss_meta.json``) – BEIDES lokale Dateien. Es wird KEIN Datei-Share
    durchlaufen; die Funktion ist damit immer schnell und unabhaengig davon,
    ob ein Netzlaufwerk erreichbar ist. Genau das ist die richtige Quelle fuer
    die Gruppen-Zaehler (die Gruppen sind logische Tags auf DB-Eintraegen)."""
    paths = set()
    try:
        for p in _load_cache().get("files", {}).keys():
            if p and not _is_pending_path(p):
                paths.add(p)
    except Exception:
        pass
    try:
        _meta = PROJECT_ROOT / "data" / "vector_store" / "faiss_meta.json"
        if _meta.exists() and _meta.stat().st_size > 10:
            for m in json.loads(_meta.read_text(encoding="utf-8")):
                fp = m.get("file_path")
                if fp and not _is_pending_path(fp):
                    paths.add(fp)
    except Exception:
        pass
    return list(paths)


def known_paths_with_disk() -> list:
    """Index-Pfade PLUS aktuell auf der Platte liegende Wissensdateien.

    Gemeinsame Zaehl-/Listen-Basis fuer die Wissensgruppen: Der Index allein
    hinkt der Platte hinterher (z.B. Pending-Extraktor-JSONs), wodurch
    Gruppen-Zaehler kleiner ausfielen als die tatsaechliche Dokumentliste.
    Der Disk-Teil laeuft best-effort – tote Netz-Shares faengt
    _all_files/_safe_exists ab, bei Fehlern bleibt es beim Index."""
    paths = set(_indexed_rel_paths())
    try:
        for f in _all_files(_get_folders()):
            paths.add(str(f))
    except Exception:
        pass
    # Versteckte/interne Dateien ausschliessen – faengt auch evtl. frueher
    # indizierte Alt-Eintraege ab (z.B. das Manifest .groups.json oder die
    # Entwurfs-JSONs unter data/knowledge/pending/).
    return [p for p in paths
            if not os.path.basename(p).startswith(".") and not _is_pending_path(p)]


# Kleiner mtime-Cache fuer den Disk-Scan der Inhalts-Suche
_scan_cache: dict = {}          # path_str -> (mtime, text_lower)
_SCAN_MAX_BYTES = 2_000_000     # groessere Dateien werden beim Disk-Scan uebersprungen
_SCAN_CACHE_BYTES = 262_144     # nur Dateien bis 256 KB im RAM cachen


def content_search_paths(needle: str) -> list:
    """Substring-Suche (case-insensitive) ueber den INHALT der Wissensdateien.

    Quellen (in dieser Reihenfolge):
    1. TF-IDF-Cache-Chunks und FAISS-Meta (bereits extrahierte Texte – deckt
       auch PDF/DOCX/OCR-Inhalte ab, sofern indexiert)
    2. Textformate (.json/.md/.txt/...) zusaetzlich direkt von der Platte –
       deckt neue/noch nicht indexierte Dateien ab, z.B. Pending-Extraktor-
       JSONs. Tote Netz-Shares faengt _all_files/_safe_exists ab.

    Gibt relative Pfade zurueck."""
    needle = (needle or "").strip().lower()
    if len(needle) < 2:
        return []
    hits = set()
    try:
        for path_str, entry in _load_cache().get("files", {}).items():
            for ch in entry.get("chunks") or []:
                if needle in ch.lower():
                    hits.add(path_str)
                    break
    except Exception:
        pass
    try:
        _meta = PROJECT_ROOT / "data" / "vector_store" / "faiss_meta.json"
        if _meta.exists() and _meta.stat().st_size > 10:
            for m in json.loads(_meta.read_text(encoding="utf-8")):
                fp = m.get("file_path")
                if fp and fp not in hits and needle in (m.get("text") or "").lower():
                    hits.add(fp)
    except Exception:
        pass
    # Disk-Scan fuer Textformate (Index kann hinter der Platte herhinken)
    try:
        for f in _all_files(_get_folders()):
            path_str = str(f)
            if path_str in hits or f.suffix.lower() not in EXTENSIONS_TEXT:
                continue
            try:
                st = f.stat()
                if st.st_size > _SCAN_MAX_BYTES:
                    continue
                cached = _scan_cache.get(path_str)
                if cached and cached[0] == st.st_mtime:
                    text = cached[1]
                else:
                    text = f.read_text(encoding="utf-8", errors="ignore").lower()
                    if st.st_size <= _SCAN_CACHE_BYTES:
                        if len(_scan_cache) > 2000:
                            _scan_cache.clear()
                        _scan_cache[path_str] = (st.st_mtime, text)
            except Exception:
                continue
            if needle in text:
                hits.add(path_str)
    except Exception:
        pass
    out = set()
    for p in hits:
        try:
            out.add(str(Path(p).resolve().relative_to(PROJECT_ROOT)))
        except Exception:
            out.add(str(p))
    return sorted(out)


def _save_cache(cache: dict):
    try:
        INDEX_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


# ─── Ordner-Verwaltung: Index-Relokation / -Bereinigung ──────────────────────
# Indizierte Dokumente sind nur ueber ihren absoluten Dateipfad mit dem
# Quellordner verknuepft (TF-IDF-Cache-Schluessel + FAISS file_path). Beim
# Umbenennen/Loeschen eines Wissens-Ordners muessen daher beide Indizes und
# die Gruppen-Zuordnungen (relative Pfade in .groups.json) mitgezogen werden.

def _folder_rel(folder: Path) -> str:
    try:
        return str(folder.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(folder)


def relocate_folder_index(old_folder: Path, new_folder: Path) -> dict:
    """Schreibt nach einer Ordner-Umbenennung alle Index-Eintraege um:
    TF-IDF-Cache, FAISS-Metadaten (ohne Neu-Embedding) und Gruppen-Zuordnungen.
    Gibt Zaehler der verschobenen Eintraege zurueck."""
    old_s, new_s = str(old_folder), str(new_folder)

    moved_tfidf = 0
    with _cache_lock:
        cache = _load_cache()
        files = cache.get("files", {})
        renamed = {}
        for p, entry in files.items():
            if p.startswith(old_s + os.sep):
                renamed[new_s + p[len(old_s):]] = entry
                moved_tfidf += 1
            else:
                renamed[p] = entry
        if moved_tfidf:
            cache["files"] = renamed
            _save_cache(cache)

    moved_vec = 0
    vs = _get_vector_store()
    if vs is not None:
        try:
            moved_vec = vs.rename_path_prefix(old_s, new_s)
        except Exception as e:
            _log.warning(f"FAISS-Relokation fehlgeschlagen: {e}")

    moved_groups = 0
    try:
        from backend import knowledge_groups as kg
        moved_groups = kg.relocate_prefix(_folder_rel(old_folder), _folder_rel(new_folder))
    except Exception as e:
        _log.warning(f"Gruppen-Relokation fehlgeschlagen: {e}")

    _log.info(f"Ordner-Index relokalisiert {old_s} -> {new_s}: "
              f"{moved_tfidf} TF-IDF-Dateien, {moved_vec} Vektor-Chunks, {moved_groups} Gruppen-Zuordnungen")
    return {"tfidf_files": moved_tfidf, "vector_chunks": moved_vec,
            "group_assignments": moved_groups}


def purge_folder_index(folder: Path) -> dict:
    """Entfernt alle Index-Eintraege (TF-IDF + FAISS) und Gruppen-Zuordnungen
    unterhalb eines Ordners. Gibt Zaehler der entfernten Eintraege zurueck."""
    folder_s = str(folder)

    removed_tfidf = 0
    with _cache_lock:
        cache = _load_cache()
        files = cache.get("files", {})
        keep = {p: e for p, e in files.items() if not p.startswith(folder_s + os.sep)}
        removed_tfidf = len(files) - len(keep)
        if removed_tfidf:
            cache["files"] = keep
            _save_cache(cache)

    removed_vec = 0
    vs = _get_vector_store()
    if vs is not None:
        try:
            removed_vec = vs.remove_path_prefix(folder_s)
        except Exception as e:
            _log.warning(f"FAISS-Bereinigung fehlgeschlagen: {e}")

    removed_groups = 0
    try:
        from backend import knowledge_groups as kg
        removed_groups = kg.remove_prefix(_folder_rel(folder))
    except Exception as e:
        _log.warning(f"Gruppen-Bereinigung fehlgeschlagen: {e}")

    _log.info(f"Ordner-Index bereinigt {folder_s}: "
              f"{removed_tfidf} TF-IDF-Dateien, {removed_vec} Vektor-Chunks, {removed_groups} Gruppen-Zuordnungen")
    return {"tfidf_files": removed_tfidf, "vector_chunks": removed_vec,
            "group_assignments": removed_groups}


def purge_file_index(file: Path) -> dict:
    """Entfernt eine EINZELNE Datei restlos aus dem Index: TF-IDF-Cache, FAISS
    und ihre Gruppen-Zuordnung. Einzeldatei-Pendant zu ``purge_folder_index`` –
    wird beim Loeschen einer Wissensdatei aufgerufen, damit die Datei nicht als
    Karteileiche in der Zaehl-Basis (``known_paths_with_disk``) bzw. den
    Wissensgruppen zurueckbleibt. Gibt Zaehler der entfernten Eintraege zurueck."""
    file_s = str(file)

    removed_tfidf = 0
    with _cache_lock:
        cache = _load_cache()
        files = cache.get("files", {})
        if file_s in files:
            del files[file_s]
            removed_tfidf = 1
            _save_cache(cache)

    removed_vec = 0
    vs = _get_vector_store()
    if vs is not None:
        try:
            before = len(vs._meta)
            vs.remove_file(file_s)
            removed_vec = before - len(vs._meta)
        except Exception as e:
            _log.warning(f"FAISS-Bereinigung fehlgeschlagen: {e}")

    removed_group = False
    try:
        from backend import knowledge_groups as kg
        if kg.get_assignment(file_s):
            kg.set_assignment(file_s, [])  # leere Liste = Zuordnung entfernen
            removed_group = True
    except Exception as e:
        _log.warning(f"Gruppen-Bereinigung fehlgeschlagen: {e}")

    _log.info(f"Datei-Index bereinigt {file_s}: "
              f"{removed_tfidf} TF-IDF, {removed_vec} Vektor-Chunks, "
              f"Gruppen-Zuordnung={'ja' if removed_group else 'nein'}")
    return {"tfidf_files": removed_tfidf, "vector_chunks": removed_vec,
            "group_assignment": removed_group}


def relocate_file_index(old_file: Path, new_file: Path) -> dict:
    """Zieht die Index-Eintraege EINER verschobenen Datei auf den neuen Pfad um –
    ohne Neu-Embedding. Einzeldatei-Pendant zu ``relocate_folder_index``.

    Betrifft TF-IDF-Cache-Schluessel, FAISS-Metadaten und die Wissensgruppen-
    Zuordnung. Die Datei selbst muss vom Aufrufer bereits verschoben worden sein
    (``Path.rename()``), damit mtime und Inhalt unveraendert bleiben und der
    naechste inkrementelle Reindex sie nicht erneut einbettet.

    Gibt Zaehler der umgezogenen Eintraege zurueck.
    """
    old_s, new_s = str(old_file), str(new_file)
    if old_s == new_s:
        return {"tfidf_files": 0, "vector_chunks": 0, "group_assignment": False}

    moved_tfidf = 0
    with _cache_lock:
        cache = _load_cache()
        files = cache.get("files", {})
        if old_s in files:
            files[new_s] = files.pop(old_s)
            moved_tfidf = 1
            _save_cache(cache)

    moved_vec = 0
    vs = _get_vector_store()
    if vs is not None:
        try:
            moved_vec = vs.rename_file_path(old_s, new_s)
        except Exception as e:
            _log.warning(f"FAISS-Relokation fehlgeschlagen: {e}")

    # Gruppen-Zuordnung mitnehmen. Modell A: Dateien in einem Ordner erben
    # dessen Gruppen; eine EXPLIZITE Zuordnung (Modell B) haengt dagegen am
    # relativen Dateipfad und muss aktiv umgehaengt werden.
    moved_group = False
    try:
        from backend import knowledge_groups as kg
        old_rel, new_rel = _folder_rel(old_file), _folder_rel(new_file)
        groups = kg.get_assignment(old_rel)
        if groups:
            kg.set_assignment(new_rel, groups)
            kg.set_assignment(old_rel, [])
            moved_group = True
    except Exception as e:
        _log.warning(f"Gruppen-Relokation fehlgeschlagen: {e}")

    _log.info(f"Datei-Index verschoben {old_s} -> {new_s}: "
              f"{moved_tfidf} TF-IDF, {moved_vec} Vektor-Chunks, "
              f"Gruppen-Zuordnung={'ja' if moved_group else 'nein'}")
    return {"tfidf_files": moved_tfidf, "vector_chunks": moved_vec,
            "group_assignment": moved_group}


def _all_files(folders: list[Path]) -> list[Path]:
    """Gibt alle unterstützten Dateien in den konfigurierten Ordnern zurück."""
    all_exts = EXTENSIONS_TEXT | EXTENSIONS_PDF | EXTENSIONS_DOCX | EXTENSIONS_XLSX | EXTENSIONS_PPTX | EXTENSIONS_VIDEO | EXTENSIONS_AUDIO
    files = []
    for folder in folders:
        # Totes Netzlaufwerk nicht anfassen -> sonst blockiert os.walk minutenlang.
        if not _safe_exists(folder):
            continue
        try:
            for root, dirs, fs in os.walk(folder, onerror=lambda e: None):
                # Versteckte Verzeichnisse nicht betreten (z.B. .git, .cache) und
                # den internen Entwurfs-Speicher (data/knowledge/pending) auslassen –
                # Extraktor-Entwuerfe sind KEIN Wissensdokument.
                dirs[:] = [d for d in dirs if not d.startswith(".")
                           and not _is_pending_path(os.path.join(root, d) + "/")]
                for f in fs:
                    # Versteckte/interne Dateien ueberspringen – z.B. das
                    # Gruppen-Manifest data/knowledge/.groups.json ist KEIN
                    # Wissensdokument und darf weder indiziert noch gelistet werden.
                    if f.startswith("."):
                        continue
                    if Path(f).suffix.lower() in all_exts:
                        files.append(Path(root) / f)
        except OSError as e:
            _log.warning("Ordner konnte nicht durchsucht werden (übersprungen): %s (%s)", folder, e)
            continue
    _disk_count_cache.update(value=len(files), ts=time.time())
    return files


# ─── Anzahl indizierbarer Dateien auf der Platte ─────────────────────────────
# Die Statistik-Kachel "Dateien" zeigt, was VORHANDEN ist – nicht, was im Index
# steht (das ist die Kachel "Indiziert"). Der Walk ueber mehrere hundert Dateien
# inkl. Netzlaufwerk darf den Stats-Aufruf aber nicht blockieren, deshalb:
# gecacht, Aktualisierung im Hintergrund, erster Aufruf mit hartem Timeout.
_disk_count_cache: dict = {"value": None, "ts": 0.0}
_DISK_COUNT_TTL = 60.0
_disk_count_refreshing = threading.Event()


def _refresh_disk_count() -> None:
    try:
        _all_files(_get_folders())   # aktualisiert _disk_count_cache selbst
    except Exception as e:
        _log.debug(f"Datei-Zaehlung fehlgeschlagen: {e}")
    finally:
        _disk_count_refreshing.clear()


def get_disk_file_count() -> int | None:
    """Anzahl indizierbarer Dateien in den Wissensordnern (None = noch unbekannt)."""
    cached = _disk_count_cache["value"]
    fresh = cached is not None and (time.time() - _disk_count_cache["ts"]) < _DISK_COUNT_TTL
    if fresh:
        return cached
    if cached is not None:
        # Alten Wert sofort ausliefern, im Hintergrund neu zaehlen.
        if not _disk_count_refreshing.is_set():
            _disk_count_refreshing.set()
            threading.Thread(target=_refresh_disk_count, daemon=True).start()
        return cached
    # Erster Aufruf: kurz warten, danach greift der Cache. Laeuft der Walk in den
    # Timeout, fuellt der (weiterlaufende) Daemon-Thread den Cache trotzdem –
    # der naechste Aufruf hat den Wert dann sofort.
    return _bounded_call(lambda: len(_all_files(_get_folders())), timeout=5.0, default=None)


INLINE_LIMIT = 10  # Maximale Dateien die inline (im Suchpfad) indiziert werden

def _rebuild_cache(folders: list[Path], max_bytes: int, force: bool = False) -> dict:
    """Inkrementeller TF-IDF Index-Aufbau (Thread-sicher).

    force=False (Suchpfad): Kein Bulk-Aufbau bei leerem Index, max. INLINE_LIMIT Dateien.
    force=True  (Neu-Indizieren): Alle Dateien werden verarbeitet, kein Limit.
    """
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

        if not force:
            # Leerer Index mit vielen Dateien: kein Inline-Bulk-Indexing
            if not cache["files"] and len(to_index) > INLINE_LIMIT:
                _log.debug(f"TF-IDF Index leer ({len(to_index)} Dateien) – bitte Neu-Indizieren ausfuehren")
                return cache
            # Bestehendes Inkrementell: max. INLINE_LIMIT Dateien inline
            if len(to_index) > INLINE_LIMIT:
                _log.info(f"{len(to_index)} geaenderte Dateien – nur {INLINE_LIMIT} inline, Rest via Neu-Indizieren")
                to_index = to_index[:INLINE_LIMIT]

        _set_progress(phase="TF-IDF", done=0, total=len(to_index))

        changed = False
        for i, filepath in enumerate(to_index):
            if _reindex_cancel.is_set():
                _log.info(f"TF-IDF Index: Abbruch nach {i}/{len(to_index)} Dateien")
                break
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

        if not _reindex_cancel.is_set():
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


async def rag_search(query: str, max_results: int = 8, groups=None) -> list[tuple[float, str, str]]:
    """Strukturierte RAG-Suche fuer externe Aufrufer (z.B. Support-Assistent).

    Liefert eine Liste von (score, relativer_pfad, chunk). Nutzt denselben
    Vektor-/TF-IDF-Dispatch wie das knowledge_search-Tool, gibt aber Rohdaten
    statt formatiertem Text zurueck.

    ``groups`` (optional): Liste von Gruppen-IDs (Modell B). Ist sie gesetzt,
    werden nur Treffer aus Dateien dieser Gruppen zurueckgegeben (ODER-Filter;
    "ungrouped" moeglich). Es wird ueber-abgefragt und danach gefiltert.
    """
    query = (query or "").strip()
    if not query:
        return []
    folders = _get_folders()
    max_bytes = _get_max_bytes()
    cfg = _get_skill_config()
    # Wissenssuche laeuft ausschliesslich ueber die Vektor-/Datenbank-Suche.
    # Der frueher waehlbare Suchmodus (Auto/TF-IDF/Vektor) wurde entfernt.
    search_mode_cfg = "vector"

    # Bei aktivem Gruppenfilter ueber-abfragen, damit nach dem Filtern noch
    # genug Treffer uebrig bleiben.
    fetch_n = max(max_results * 5, 40) if groups else max_results

    vs = _get_vector_store()
    vector_index_ready = vs is not None and vs.chunk_count() > 0
    need_tfidf_cache = search_mode_cfg == "tfidf" or (
        search_mode_cfg == "auto" and not vector_index_ready)

    cache = await asyncio.to_thread(_rebuild_cache, folders, max_bytes, False) \
        if need_tfidf_cache else _load_cache()

    results = None
    if search_mode_cfg in ("auto", "vector"):
        has_vector = await asyncio.to_thread(_rebuild_vector_index, folders, max_bytes)
        if has_vector:
            results = await asyncio.to_thread(_vector_search, query, fetch_n)
        elif search_mode_cfg == "auto":
            results = _search(query, cache, fetch_n)
    elif search_mode_cfg == "tfidf":
        results = _search(query, cache, fetch_n)
    results = results or []

    if groups:
        try:
            from backend import knowledge_groups as kg
            kept = set(kg.filter_paths_by_groups([r[1] for r in results], groups))
            results = [r for r in results if r[1] in kept][:max_results]
        except Exception:
            results = results[:max_results]
    return results


def _get_static_stats() -> dict:
    """Format-Support + ChromaDB-Client – wird einmalig gecacht (ändert sich nicht)."""
    global _stats_cache
    with _stats_cache_lock:
        if _stats_cache is not None:
            return _stats_cache
        has_pdf = has_docx = has_xlsx = has_pptx = has_video = has_image = False
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
        try:
            import pytesseract  # noqa: F401
            if shutil.which("tesseract"): has_image = True
        except ImportError: pass

        _stats_cache = {
            "pdf_support": has_pdf, "docx_support": has_docx,
            "xlsx_support": has_xlsx, "pptx_support": has_pptx,
            "video_support": has_video, "image_support": has_image,
        }
        return _stats_cache


def get_stats() -> dict:
    """Statistiken für die API – schnell, kein Netzwerk-/Modell-Scan."""
    folders = _get_folders()

    folder_list = []
    for f in folders:
        try:
            rel = str(f.relative_to(PROJECT_ROOT))
        except ValueError:
            rel = str(f)
        folder_list.append({"path": rel, "exists": _safe_exists(f)})

    # Vektor-DB: FAISS verfuegbar? + Index-Inhalt lesen (meta.json)
    vector_db_available = False
    has_vector = False
    vector_chunks = 0
    vector_files = 0
    vector_db_name = ""
    vector_db_version = ""
    vector_model = ""
    faiss_file_paths: set = set()
    faiss_meta_list: list = []
    try:
        import faiss as _faiss
        vector_db_available = True
        vector_db_name = "FAISS"
        vector_db_version = getattr(_faiss, "__version__", "")
        from backend.tools.vector_store import MODEL_NAME as _VS_MODEL
        vector_model = _VS_MODEL
        _meta_path = PROJECT_ROOT / "data" / "vector_store" / "faiss_meta.json"
        if _meta_path.exists() and _meta_path.stat().st_size > 10:
            import json as _json
            with open(_meta_path, "r", encoding="utf-8") as _f:
                faiss_meta_list = _json.load(_f)
            vector_chunks = len(faiss_meta_list)
            has_vector = vector_chunks > 0
            faiss_file_paths = {m["file_path"] for m in faiss_meta_list}
            vector_files = len(faiss_file_paths)
    except Exception:
        pass

    # Datei-/Chunk-Zähler: FAISS-Meta bevorzugen wenn vorhanden, sonst TF-IDF-Cache
    if has_vector:
        total_files = vector_files
        indexed_files = vector_files
        total_chunks = vector_chunks
        # Dateigröße aus Filesystem (FAISS speichert keine Größe). Zeitlich
        # begrenzt, damit ein totes Netzlaufwerk die Stats nicht einfriert.
        def _sum_sizes():
            total = 0
            for p in faiss_file_paths:
                try:
                    total += Path(p).stat().st_size
                except OSError:
                    continue
            return total
        total_size = _bounded_call(_sum_sizes, timeout=3.0, default=0)
    else:
        cache = _load_cache()
        total_files = len(cache["files"])
        indexed_files = len(cache["files"])
        total_chunks = sum(len(d.get("chunks", [])) for d in cache["files"].values())
        total_size = sum(d.get("size", 0) for d in cache["files"].values())

    # "Dateien" = was in den Wissensordnern LIEGT. Frueher stand hier die Anzahl
    # der Dateien im Index – bei einem unvollstaendigen Index sah es dann so aus,
    # als gaebe es nur 10 statt 700+ Dokumente.
    disk_files = get_disk_file_count()
    if disk_files is not None:
        total_files = disk_files

    return {
        "folders": folder_list,
        "total_files": total_files,
        "disk_files": disk_files,
        "indexed_files": indexed_files,
        "total_chunks": total_chunks,
        "total_size_bytes": total_size,
        **_get_static_stats(),
        "vector_db_available": vector_db_available,
        "vector_search": has_vector,
        "vector_files": vector_files,
        "vector_chunks": vector_chunks,
        "vector_db_name": vector_db_name,
        "vector_db_version": vector_db_version,
        "vector_model": vector_model,
        "search_mode": "vector",
        "indexing": get_index_progress()["running"],
        "index_phase": get_index_progress()["phase"],
        "last_index_run": get_last_run(),
    }


# Ein Lauf, der an einem Fehler scheitert (Embedding-Modell nicht ladbar,
# Netzlaufwerk weg, Speicher voll), hinterlaesst einen LEEREN Index – der
# Neuaufbau beginnt mit vs.clear(). Deshalb automatisch neu ansetzen. Der
# manuelle Abbruch ist davon ausgenommen (siehe _reindex_cancel).
MAX_INDEX_ATTEMPTS = 3      # 1 regulaerer Lauf + 2 automatische Neuversuche
RETRY_DELAY_SEC = 15        # Pause dazwischen (z.B. bis ein Mount zurueck ist)


def force_reindex(resume_count: int = 0, incremental: bool = False,
                  resume_baseline: int = -1) -> dict:
    """Neuaufbau des Wissens-Index:
    - FAISS verfuegbar → nur Vektor-Index (schneller, besser bei 600+ Dateien)
    - FAISS nicht verfuegbar → TF-IDF-Index

    ``incremental=True`` behaelt den bestehenden Index (kein ``vs.clear()``) und
    ergaenzt nur fehlende/geaenderte Dateien – so setzt eine Wiederaufnahme nach
    Absturz dort fort, wo sie war, statt bei 0 zu beginnen.

    Scheitert ein Lauf mit einer Ausnahme, wird er bis zu ``MAX_INDEX_ATTEMPTS``
    mal automatisch wiederholt. ``resume_count`` zaehlt Wiederaufnahmen nach
    einem Prozess-Neustart, ``resume_baseline`` den Dateistand zu deren Beginn
    (fuer die Fortschritts-Pruefung in ``resume_interrupted_reindex``).
    """
    # Re-Entrancy-Schutz: laeuft bereits ein Reindex, NICHT parallel starten
    # (sonst ueberschreiben sich die Fortschritts-Zaehler -> >100%). Stattdessen
    # einen Rerun vormerken, damit neu hinzugefuegte Dateien danach indexiert werden.
    if not _reindex_lock.acquire(blocking=False):
        _reindex_rerun.set()
        _log.info("force_reindex: laeuft bereits – Rerun vorgemerkt")
        return {"skipped": True, "reason": "reindex already running, rerun scheduled"}
    try:
        _reindex_cancel.clear()
        result = _run_with_retries(resume_count, incremental, resume_baseline)
        # Waehrenddessen weitere Anfragen? -> genau einmal nachholen (coalesced).
        # Nach einem Abbruch NICHT nachholen – sonst startet der Lauf, den der
        # Benutzer gerade gestoppt hat, sofort wieder von vorn.
        while _reindex_rerun.is_set() and not _reindex_cancel.is_set():
            _reindex_rerun.clear()
            result = _run_with_retries(resume_count, incremental, resume_baseline)
        return result
    finally:
        _reindex_rerun.clear()
        # Flag zuruecksetzen, sonst wuerde die naechste inline-Indizierung
        # (Suchpfad) den alten Abbruchwunsch erben und sofort abbrechen.
        _reindex_cancel.clear()
        _reindex_lock.release()


def _run_with_retries(resume_count: int = 0, incremental: bool = False,
                      resume_baseline: int = -1) -> dict:
    """Fuehrt den Neuaufbau aus und wiederholt ihn nach einem Fehler automatisch."""
    last_exc: Exception | None = None
    first_started = time.time()
    for attempt in range(1, MAX_INDEX_ATTEMPTS + 1):
        try:
            return _do_force_reindex(attempt=attempt, resume_count=resume_count,
                                     incremental=incremental,
                                     resume_baseline=resume_baseline)
        except Exception as e:
            last_exc = e
            _log.warning(f"Indizierung Versuch {attempt}/{MAX_INDEX_ATTEMPTS} fehlgeschlagen: {e}")
            if _reindex_cancel.is_set() or attempt >= MAX_INDEX_ATTEMPTS:
                break
            # "laeuft" bleibt gesetzt – die Oberflaeche zeigt den Neuversuch an
            # statt den Knopf freizugeben und den Fehler zu verschweigen.
            _set_progress(running=True, phase="Neuversuch", error=str(e),
                          attempt=attempt + 1, max_attempts=MAX_INDEX_ATTEMPTS)
            # Unterbrechbare Pause: ein Abbruch waehrend der Wartezeit greift sofort.
            if _reindex_cancel.wait(RETRY_DELAY_SEC):
                break

    finished = time.time()
    cancelled = _reindex_cancel.is_set()
    # Teilstand erhalten: bei incremental bleibt der Index bestehen, die schon
    # indizierten Dateien sind kein Verlust.
    try:
        vs = _get_vector_store()
        partial_files = vs.file_count() if vs is not None else 0
        partial_chunks = vs.chunk_count() if vs is not None else 0
    except Exception:
        partial_files = partial_chunks = 0
    _set_progress(running=False, phase="Abgebrochen" if cancelled else "Fehler",
                  error=str(last_exc or ""), finished_at=finished, cancelled=cancelled)
    _save_last_run({"started_at": first_started, "finished_at": finished,
                    "status": "cancelled" if cancelled else "error",
                    "error": str(last_exc or "")[:300], "attempts": MAX_INDEX_ATTEMPTS,
                    "resumed": resume_count, "indexed_files": partial_files,
                    "total_chunks": partial_chunks})
    raise last_exc if last_exc else RuntimeError("Indizierung fehlgeschlagen")


def cancel_reindex() -> dict:
    """Bricht einen laufenden Neuaufbau ab (nach der aktuellen Datei).

    Der Index bleibt danach unvollstaendig – ein Neuaufbau leert ihn zuerst.
    """
    if not get_index_progress().get("running"):
        return {"cancelled": False, "reason": "keine Indizierung aktiv"}
    _reindex_cancel.set()
    _reindex_rerun.clear()
    _set_progress(phase="Wird abgebrochen…")
    _log.info("Indizierung: Abbruch angefordert")
    return {"cancelled": True}


# Kurzprotokoll des letzten Laufs – ueberlebt einen Neustart, damit die
# Oberflaeche "Letzter Indexlauf: <Datum/Uhrzeit>" auch nach einem Restart zeigt.
LAST_INDEX_RUN_PATH = PROJECT_ROOT / "data" / "vector_store" / "last_index.json"


def _save_last_run(run: dict) -> None:
    try:
        LAST_INDEX_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_INDEX_RUN_PATH.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        _log.warning(f"Lauf-Protokoll konnte nicht geschrieben werden: {e}")


def get_last_run() -> dict:
    """Metadaten des letzten Indexlaufs ({} wenn noch nie gelaufen)."""
    try:
        if LAST_INDEX_RUN_PATH.exists():
            return json.loads(LAST_INDEX_RUN_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_run_checkpoint(done: int, total: int, current_file: str, indexed_files: int) -> None:
    """Schreibt den Zwischenstand des laufenden Reindex auf Platte.

    Stirbt der Prozess danach, weiss die Wiederaufnahme (und die Oberflaeche),
    WIE WEIT es kam und bei WELCHER Datei es zuletzt war."""
    _save_last_run({**_current_run, "finished_at": 0, "status": "running",
                    "done": done, "total": total, "current_file": current_file,
                    "indexed_files": indexed_files})


# Sicherheitsnetz gegen eine echte Endlosschleife: selbst wenn jeder Lauf
# Fortschritt meldet, hoert die automatische Wiederaufnahme nach so vielen
# Anlaeufen auf. Im Normalfall greift vorher die Fortschritts-Pruefung.
MAX_RESUMES = 20


def resume_interrupted_reindex() -> bool:
    """Setzt einen Lauf fort, der durch einen Prozess-Abbruch geendet hat.

    Beim Start aufrufen: steht im Lauf-Protokoll noch ``status: running``, ist
    der Prozess mittendrin gestorben (Neustart, Absturz, OOM – z.B. der
    OOM-Killer). Der Index ist dann unvollstaendig, ohne dass es irgendwo als
    Fehler auftaucht.

    Die Wiederaufnahme laeuft INKREMENTELL (kein ``vs.clear()``): die bereits
    indizierten Dateien bleiben erhalten, es werden nur die fehlenden ergaenzt.
    Fortgesetzt wird nur, solange messbarer Fortschritt entsteht – bringt ein
    Anlauf keine neue Datei in den Index, wird abgebrochen (sonst liefe eine
    Datei, die den Prozess zuverlaessig killt, endlos in dieselbe Wand).

    Gibt True zurueck, wenn eine Wiederaufnahme gestartet wurde.
    """
    run = get_last_run()
    if run.get("status") != "running":
        return False
    if get_index_progress().get("running"):
        return False   # laeuft bereits (z.B. durch Auto-Mount angestossen)

    # Aktuellen Stand aus dem Index lesen (ueberlebt den Absturz auf Platte).
    try:
        vs = _get_vector_store()
        current_files = vs.file_count() if vs is not None else 0
    except Exception:
        current_files = 0

    resumed = int(run.get("resumed") or 0) + 1
    baseline = int(run.get("resume_baseline", -1))   # Stand zu Beginn des letzten Anlaufs
    stalled = baseline >= 0 and current_files <= baseline

    if stalled or resumed > MAX_RESUMES:
        reason = ("kein Fortschritt seit letztem Anlauf – vermutlich scheitert eine "
                  "bestimmte Datei" if stalled else f"{MAX_RESUMES} Anlaeufe erschoepft")
        run.update(status="interrupted", finished_at=run.get("finished_at") or time.time(),
                   indexed_files=current_files, interrupt_reason=reason)
        _save_last_run(run)
        _log.warning(f"Wiederaufnahme der Indizierung gestoppt: {reason} "
                     f"(bei {current_files} Dateien)")
        return False

    _log.warning(
        f"Unterbrochene Indizierung gefunden (Start "
        f"{time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(run.get('started_at') or 0))}, "
        f"zuletzt {current_files} Dateien im Index) – wird inkrementell fortgesetzt "
        f"(Anlauf {resumed})")

    def _run():
        try:
            force_reindex(resume_count=resumed, incremental=True,
                          resume_baseline=current_files)
        except Exception as e:
            _log.error(f"Automatisch fortgesetzte Indizierung fehlgeschlagen: {e}")

    threading.Thread(target=_run, daemon=True, name="reindex-resume").start()
    return True


def _do_force_reindex(attempt: int = 1, resume_count: int = 0,
                      incremental: bool = False, resume_baseline: int = -1) -> dict:
    global _current_run
    started = time.time()
    # Bei einer Wiederaufnahme den urspruenglichen Start beibehalten, damit die
    # "Letzter Indexlauf"-Zeit nicht bei jedem Anlauf springt.
    if incremental:
        prev = get_last_run()
        started = prev.get("started_at") or started
    _current_run = {"started_at": started, "attempt": attempt,
                    "resumed": resume_count, "resume_baseline": resume_baseline,
                    "incremental": incremental}
    _set_progress(running=True, phase="Starte...", done=0, total=0, vector_done=0,
                  vector_total=0, vector_base=0, chunks=0, error="", current_file="",
                  started_at=started, finished_at=0.0, resumed=resume_count,
                  cancelled=False, attempt=attempt, max_attempts=MAX_INDEX_ATTEMPTS)
    # Marker "laeuft" auf die Platte: stirbt der Prozess mittendrin (Neustart,
    # OOM-Killer), erkennt resume_interrupted_reindex() das beim naechsten Start
    # und setzt den Lauf fort. Ein sauberes Ende ueberschreibt den Marker.
    _save_last_run({**_current_run, "finished_at": 0, "status": "running",
                    "indexed_files": resume_baseline if resume_baseline > 0 else 0,
                    "total_chunks": 0})
    # Ausnahmen werden bewusst NICHT hier abgefangen: Endzustand und Protokoll
    # schreibt _run_with_retries – erst wenn alle Versuche verbraucht sind.
    # Sonst zeigte die Oberflaeche zwischen zwei Neuversuchen "Fehler/fertig".
    folders = _get_folders()
    max_bytes = _get_max_bytes()
    vs = _get_vector_store()

    # Verwaiste Gruppen-Zuordnungen (Modell B) entfernen: Dateien, die es
    # nicht mehr gibt, verlieren ihre logischen Tags.
    try:
        from backend import knowledge_groups as _kg
        _kg.prune(_all_files(folders))
    except Exception:
        pass

    if vs is not None:
        # ── Nur FAISS aufbauen ──────────────────────────────────────────────
        # incremental: bestehenden Index behalten (Wiederaufnahme nach Absturz);
        # der Reindex ueberspringt unveraenderte Dateien automatisch.
        if not incremental:
            vs.clear()
        _rebuild_vector_index(folders, max_bytes, force=True)
        chunk_count = vs.chunk_count()
        file_count  = vs.file_count()
        result = {"indexed_files": file_count, "total_chunks": chunk_count,
                  "vector_info": f"Vektor: {chunk_count} Chunks"}
    else:
        # ── Nur TF-IDF aufbauen (FAISS nicht installiert) ───────────────────
        with _cache_lock:
            INDEX_CACHE_PATH.unlink(missing_ok=True)
        cache = _rebuild_cache(folders, max_bytes, force=True)
        total_chunks = sum(len(d.get("chunks", [])) for d in cache["files"].values())
        result = {"indexed_files": len(cache["files"]), "total_chunks": total_chunks,
                  "vector_info": ""}

    cancelled = _reindex_cancel.is_set()
    finished = time.time()
    _set_progress(running=False, phase="Abgebrochen" if cancelled else "Fertig",
                  finished_at=finished, cancelled=cancelled)
    _save_last_run({"started_at": started, "finished_at": finished,
                    "status": "cancelled" if cancelled else "ok",
                    "attempt": attempt, "resumed": resume_count,
                    "indexed_files": result["indexed_files"],
                    "total_chunks": result["total_chunks"]})
    result["cancelled"] = cancelled
    return result


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

        # Vom Benutzer gewaehlter Wissensgruppen-Filter (Modell B):
        #   None       -> kein Filter (alle Gruppen)
        #   []          -> Benutzer hat ALLE Gruppen abgewaehlt -> kein Wissen
        #   [ids...]    -> nur Treffer aus diesen Gruppen (ODER; "ungrouped" moeglich)
        kb_groups = kwargs.get("_kb_groups")
        if isinstance(kb_groups, list) and len(kb_groups) == 0:
            return ("🔒 Keine Wissensgruppen ausgewählt – es wird kein Wissen aus der "
                    "Knowledge Base verwendet. (Auswahl über den Wissensgruppen-Filter änderbar.)")
        # Bei aktivem Filter ueber-abfragen, damit nach dem Filtern genug uebrig bleibt.
        fetch_n = max(max_results * 5, 40) if kb_groups else max_results

        if not query.strip():
            return "❌ Fehler: query-Parameter fehlt. Bitte knowledge_search erneut aufrufen und einen konkreten Suchbegriff aus der Benutzeranfrage als 'query' übergeben (z.B. knowledge_search({'query': 'LDT Import Medistar'}))."

        # Standardordner sicherstellen
        (PROJECT_ROOT / DEFAULT_FOLDER).mkdir(parents=True, exist_ok=True)

        folders = _get_folders()
        max_bytes = _get_max_bytes()

        # Wissenssuche laeuft ausschliesslich ueber die Vektor-/Datenbank-Suche.
        # Der frueher waehlbare Suchmodus (Auto/TF-IDF/Vektor) wurde entfernt.
        cfg = _get_skill_config()
        search_mode_cfg = "vector"

        # TF-IDF Cache nur laden wenn benoetigt (nicht bei reinem Vektor-Modus)
        # Spart bei 600+ Dateien das Laden aller Chunks in den RAM
        vs = _get_vector_store()
        vector_index_ready = vs is not None and vs.chunk_count() > 0
        need_tfidf_cache = search_mode_cfg == "tfidf" or (
            search_mode_cfg == "auto" and not vector_index_ready
        )

        if need_tfidf_cache:
            cache = await asyncio.to_thread(_rebuild_cache, folders, max_bytes, False)
        else:
            cache = _load_cache()  # nur fuer die Leer-Pruefung, kein Rebuild

        # Dateien vorhanden aber noch kein Index?
        files_on_disk = _all_files(folders)
        if not cache["files"] and not vector_index_ready:
            if files_on_disk:
                return f"⚠️ Knowledge Base hat {len(files_on_disk)} Dateien, aber noch keinen Index. Bitte einmal 'Neu Indizieren' in den Einstellungen ausführen."
            folder_display = ", ".join(
                str(f.relative_to(PROJECT_ROOT)) if str(f).startswith(str(PROJECT_ROOT)) else str(f)
                for f in folders
            )
            return f"📂 Knowledge Base ist leer. Lege Dateien in einen der Ordner ab: {folder_display}"

        results = None
        search_mode = "TF-IDF"

        if search_mode_cfg in ("auto", "vector"):
            has_vector = await asyncio.to_thread(_rebuild_vector_index, folders, max_bytes)
            if has_vector:
                # Vektor-Index vorhanden → ausschliesslich Vektor verwenden (kein TF-IDF-Fallback)
                # Begruendung: TF-IDF skaliert O(n) mit Dateizahl, Vektor konstant ~35ms
                results = await asyncio.to_thread(_vector_search, query, fetch_n)
                search_mode = "Hybrid: Vektor+BM25"
            elif search_mode_cfg == "auto":
                # Kein Vektor-Index → TF-IDF als Fallback
                results = _search(query, cache, fetch_n)
                search_mode = "TF-IDF"
            # search_mode_cfg == "vector" ohne Index → keine Ergebnisse (hat_vector=False)

        elif search_mode_cfg == "tfidf":
            results = _search(query, cache, fetch_n)
            search_mode = "TF-IDF"

        # Auf die gewaehlten Wissensgruppen einschraenken (ODER-Filter ueber Pfade)
        if kb_groups and results:
            try:
                from backend import knowledge_groups as kg
                kept = set(kg.filter_paths_by_groups([r[1] for r in results], kb_groups))
                results = [r for r in results if r[1] in kept]
            except Exception:
                pass
        if results:
            results = results[:max_results]

        if not results:
            total = sum(len(d.get("chunks", [])) for d in cache["files"].values())
            _grp = " in den gewählten Wissensgruppen" if kb_groups else ""
            return f"🔍 Keine Treffer für '{query}'{_grp} ({len(cache['files'])} Dateien, {total} Chunks)."

        output = f"🔍 {len(results)} Treffer für '{query}' ({search_mode}):\n\n"
        for i, (score, filename, chunk) in enumerate(results, 1):
            output += f"--- [{i}] {filename} (Relevanz: {score:.2f}) ---\n"
            output += chunk.strip()[:CHUNK_OUTPUT_LIMIT] + "\n\n"

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
                lines.append(f"  {'✅' if _safe_exists(f) else '❌'} {rel}")
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
            # Bild-OCR (Tesseract)
            try:
                import pytesseract as _pt  # noqa: F401
                import shutil as _sh
                _ocr_ok = bool(_sh.which("tesseract"))
            except Exception:
                _ocr_ok = False
            formats.append("Bilder/OCR" if _ocr_ok
                           else "Bilder/OCR ⚠️ (tesseract-ocr + pytesseract nötig)")
            size_mb = stats["total_size_bytes"] / (1024 * 1024)

            # Vektor-Info
            if stats.get("vector_search"):
                vector_line = f"\n  🧠 Vektor-Suche: aktiv ({stats['vector_files']} Dateien, {stats['vector_chunks']} Chunks)"
            else:
                vector_line = "\n  🧠 Vektor-Suche: inaktiv (faiss-cpu/sentence-transformers fehlt)"

            return (
                f"📊 Knowledge Base Statistiken:\n"
                f"  Dateien: {stats['total_files']} ({size_mb:.1f} MB)\n"
                f"  TF-IDF Index: {stats['indexed_files']} Dateien, {stats['total_chunks']} Chunks"
                f"{vector_line}\n"
                f"  Formate: {', '.join(formats)}"
            )

        return f"❌ Unbekannte Aktion: {action}"
