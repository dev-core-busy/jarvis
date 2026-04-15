"""Vector Store – FAISS + sentence-transformers (multilingual-e5-small) fuer semantische Suche.

Warum FAISS statt ChromaDB:
- 10-100x schnellere Suche (reines C++, kein Python/SQLite-Overhead)
- Geringerer RAM-Verbrauch
- Einfachere Abhaengigkeit (faiss-cpu)

Warum e5-small statt e5-base:
- ~4x schnelleres Encoding (384d statt 768d)
- ~4x kleineres Modell (~120 MB statt ~500 MB)
- Qualitaetsverlust <10% fuer typische RAG-Anwendungen
"""

import json
import logging
import threading
from pathlib import Path

import numpy as np

_log = logging.getLogger("jarvis.vector_store")
_model_lock = threading.Lock()
_embedding_model = None

MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384

# Mindest-Relevanz fuer Treffer (0.0–1.0, Inner Product bei normierten Vektoren)
MIN_SCORE = 0.40


def _get_embedding_model():
    """Lazy-Load des Embedding-Modells (Singleton, Thread-sicher)."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    with _model_lock:
        if _embedding_model is not None:
            return _embedding_model
        from sentence_transformers import SentenceTransformer
        _log.info(f"Lade Embedding-Modell: {MODEL_NAME}")
        _embedding_model = SentenceTransformer(MODEL_NAME)
        _log.info("Embedding-Modell geladen")
        return _embedding_model


def _encode(texts: list[str], prefix: str = "passage") -> np.ndarray:
    """Kodiert Texte mit e5-Prefix zu normierten Float32-Vektoren."""
    model = _get_embedding_model()
    prefixed = [
        t if (t.startswith("passage:") or t.startswith("query:")) else f"{prefix}: {t}"
        for t in texts
    ]
    vecs = model.encode(
        prefixed,
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=64,
    )
    return vecs.astype(np.float32)


class VectorStore:
    """FAISS-basierter Vektorspeicher mit JSON-Metadaten-Persistenz.

    Persistenz:
      <dir>/faiss_index.bin  – FAISS IndexFlatIP (normierte Vektoren → Cosine)
      <dir>/faiss_meta.json  – Liste aller Chunks mit file_path, mtime, chunk_index, text

    Deletion: rebuild-on-change (bei 10-20k Chunks <5 ms – vollkommen akzeptabel).
    """

    def __init__(self, persist_dir: Path):
        import faiss  # noqa: F401 – fruehzeitig pruefen ob installiert
        self._dir = persist_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "faiss_index.bin"
        self._meta_path = self._dir / "faiss_meta.json"
        self._lock = threading.Lock()

        # _meta: Liste von {"file_path": str, "mtime": float, "chunk_index": int, "text": str}
        # _index: FAISS IndexFlatIP mit normierten Vektoren (Inner Product = Cosine)
        self._meta: list[dict] = []
        self._index = None
        self._load()
        _log.info(f"VectorStore (FAISS) initialisiert: {persist_dir} ({len(self._meta)} Chunks)")

    # ─── Persistenz ──────────────────────────────────────────────────────────

    def _load(self):
        import faiss
        if self._index_path.exists() and self._meta_path.exists():
            try:
                self._index = faiss.read_index(str(self._index_path))
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    self._meta = json.load(f)
                return
            except Exception as e:
                _log.warning(f"FAISS-Index konnte nicht geladen werden, neu anlegen: {e}")
        self._reset_index()

    def _reset_index(self):
        import faiss
        self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
        self._meta = []

    def _save(self):
        import faiss
        try:
            faiss.write_index(self._index, str(self._index_path))
            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump(self._meta, f, ensure_ascii=False)
        except Exception as e:
            _log.error(f"FAISS-Index speichern fehlgeschlagen: {e}")

    def _rebuild(self, meta: list[dict], vectors: np.ndarray):
        """Baut den FAISS-Index aus einer neuen Meta+Vektor-Liste neu auf."""
        import faiss
        idx = faiss.IndexFlatIP(EMBEDDING_DIM)
        if len(vectors) > 0:
            idx.add(vectors)
        self._index = idx
        self._meta = meta
        self._save()

    # ─── Schreib-Operationen ─────────────────────────────────────────────────

    def add_chunks(self, file_path: str, chunks: list[str], mtime: float):
        """Fuegt Chunks fuer eine Datei hinzu (ersetzt bestehende)."""
        if not chunks:
            self.remove_file(file_path)
            return

        # Neue Vektoren berechnen (ausserhalb des Locks – dauert laenger)
        new_vecs = _encode(chunks, prefix="passage")

        with self._lock:
            # Bestehende Chunks dieser Datei entfernen
            keep = [i for i, m in enumerate(self._meta) if m["file_path"] != file_path]
            old_meta = [self._meta[i] for i in keep]
            old_vecs = self._vectors_at(keep)

            # Neue Chunks anfuegen
            new_meta = [
                {"file_path": file_path, "mtime": mtime, "chunk_index": i, "text": t}
                for i, t in enumerate(chunks)
            ]
            combined_meta = old_meta + new_meta
            combined_vecs = (
                np.vstack([old_vecs, new_vecs])
                if len(old_vecs) > 0
                else new_vecs
            )
            self._rebuild(combined_meta, combined_vecs)
        _log.debug(f"Indexiert: {file_path} ({len(chunks)} Chunks)")

    def remove_file(self, file_path: str):
        """Entfernt alle Chunks einer Datei."""
        with self._lock:
            keep = [i for i, m in enumerate(self._meta) if m["file_path"] != file_path]
            if len(keep) == len(self._meta):
                return  # nichts zu tun
            new_meta = [self._meta[i] for i in keep]
            new_vecs = self._vectors_at(keep)
            self._rebuild(new_meta, new_vecs)

    def clear(self):
        """Loescht den gesamten Index."""
        with self._lock:
            self._reset_index()
            self._save()
        _log.info("VectorStore geleert")

    # ─── Suche ───────────────────────────────────────────────────────────────

    def search(self, query: str, max_results: int) -> list[tuple[float, str, str]]:
        """Semantische Suche. Gibt (score, file_path, chunk_text) zurueck."""
        with self._lock:
            total = len(self._meta)
        if total == 0:
            return []

        query_vec = _encode([query], prefix="query")  # (1, 384)
        k = min(max_results * 2, total)

        with self._lock:
            scores, indices = self._index.search(query_vec, k)

        output = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            if float(score) < MIN_SCORE:
                continue
            m = self._meta[idx]
            output.append((float(score), m["file_path"], m["text"]))

        # Sortiert nach Score (FAISS liefert bereits absteigend, sicherheitshalber)
        output.sort(key=lambda x: x[0], reverse=True)
        return output[:max_results]

    # ─── Metadaten-Abfragen ──────────────────────────────────────────────────

    def get_indexed_files(self) -> dict[str, float]:
        """Gibt {file_path: mtime} aller indexierten Dateien zurueck."""
        with self._lock:
            files: dict[str, float] = {}
            for m in self._meta:
                fp = m["file_path"]
                if fp not in files:
                    files[fp] = m["mtime"]
            return files

    def file_count(self) -> int:
        return len(self.get_indexed_files())

    def chunk_count(self) -> int:
        with self._lock:
            return len(self._meta)

    # ─── Hilfsmethoden ───────────────────────────────────────────────────────

    def _vectors_at(self, indices: list[int]) -> np.ndarray:
        """Extrahiert Vektoren fuer gegebene Indizes aus dem FAISS-Index."""
        if not indices or self._index.ntotal == 0:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
        # IndexFlatIP speichert Vektoren dicht – direkter Zugriff via reconstruct
        vecs = np.zeros((len(indices), EMBEDDING_DIM), dtype=np.float32)
        for out_i, idx in enumerate(indices):
            self._index.reconstruct(int(idx), vecs[out_i])
        return vecs
