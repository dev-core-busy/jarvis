"""Vector Store – ChromaDB + sentence-transformers fuer semantische Suche."""

import logging
import os
import threading
from pathlib import Path

# ChromaDB-Telemetry deaktivieren (verhindert Fehler-Spam im Log)
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY", "False")

_log = logging.getLogger("jarvis.vector_store")
_model_lock = threading.Lock()
_embedding_model = None

COLLECTION_NAME = "knowledge_chunks"

# multilingual-e5-base: deutlich besser als MiniLM fuer deutschen Text
# Erfordert Prefix "query:" bei Suchanfragen, "passage:" bei Dokumenten
MODEL_NAME = "intfloat/multilingual-e5-base"

# HNSW-Parameter: M=32 (Verbindungen), ef_construction=200 (Index-Qualitaet),
# ef=100 (Query-Genauigkeit) – ChromaDB-Defaults sind sehr konservativ
HNSW_PARAMS = {
    "hnsw:space": "cosine",
    "hnsw:M": 32,
    "hnsw:construction_ef": 200,
    "hnsw:search_ef": 100,
    "hnsw:num_threads": 4,
}

# Mindest-Relevanz fuer Treffer (0.0–1.0)
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


class ChromaEmbeddingFunction:
    """Adapter: sentence-transformers → ChromaDB Embedding-Interface.
    e5-Modelle benoetigen Prefix 'passage:' fuer Dokumente beim Indexieren.
    Implementiert ChromaDB 1.5+ EmbeddingFunction Protocol."""

    def name(self) -> str:
        return "jarvis-e5-multilingual"

    def build_from_config(self, config: dict) -> "ChromaEmbeddingFunction":
        return ChromaEmbeddingFunction()

    def get_config(self) -> dict:
        return {"model": MODEL_NAME}

    def __call__(self, input: list[str]) -> list[list[float]]:
        model = _get_embedding_model()
        # Prefix hinzufuegen falls noch nicht vorhanden
        prefixed = [
            t if t.startswith("passage:") or t.startswith("query:") else f"passage: {t}"
            for t in input
        ]
        embeddings = model.encode(
            prefixed,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )
        return embeddings.tolist()


class VectorStore:
    """Wrapper um ChromaDB mit sentence-transformers Embeddings."""

    def __init__(self, persist_dir: Path):
        import chromadb
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._ef = ChromaEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self._ef,
            metadata=HNSW_PARAMS,
        )
        _log.info(f"VectorStore initialisiert: {persist_dir} ({self._collection.count()} Chunks)")

    def add_chunks(self, file_path: str, chunks: list[str], mtime: float):
        """Fuegt Chunks fuer eine Datei hinzu (ersetzt bestehende)."""
        self.remove_file(file_path)
        if not chunks:
            return

        ids = [f"{file_path}::chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {"file_path": file_path, "mtime": mtime, "chunk_index": i}
            for i in range(len(chunks))
        ]

        # ChromaDB Batch-Limit beachten
        batch_size = 200
        for start in range(0, len(chunks), batch_size):
            end = start + batch_size
            self._collection.add(
                ids=ids[start:end],
                documents=chunks[start:end],
                metadatas=metadatas[start:end],
            )
        _log.debug(f"Indexiert: {file_path} ({len(chunks)} Chunks)")

    def remove_file(self, file_path: str):
        """Entfernt alle Chunks einer Datei."""
        try:
            self._collection.delete(where={"file_path": file_path})
        except Exception:
            pass

    def search(self, query: str, max_results: int) -> list[tuple[float, str, str]]:
        """Semantische Suche. Gibt (score, rel_path, chunk_text) zurueck."""
        try:
            count = self._collection.count()
            if count == 0:
                return []
        except Exception:
            return []

        # e5-Modell benoetigt "query:" Prefix bei Suchanfragen
        query_text = f"query: {query}" if not query.startswith("query:") else query

        model = _get_embedding_model()
        query_embedding = model.encode(
            [query_text],
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

        results = self._collection.query(
            query_embeddings=query_embedding,
            n_results=min(max_results * 2, count),  # mehr holen, dann filtern
            include=["documents", "metadatas", "distances"],
        )

        output = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                # Cosine-Distanz → Aehnlichkeit (0=gleich, 1=perfekt)
                score = 1.0 - (dist / 2.0)
                if score >= MIN_SCORE:
                    output.append((score, meta["file_path"], doc))

        # Auf max_results begrenzen nach Score-Filterung
        return output[:max_results]

    def get_indexed_files(self) -> dict[str, float]:
        """Gibt {file_path: mtime} aller indexierten Dateien zurueck."""
        try:
            all_meta = self._collection.get(include=["metadatas"])
            files = {}
            for meta in all_meta["metadatas"]:
                fp = meta["file_path"]
                if fp not in files:
                    files[fp] = meta["mtime"]
            return files
        except Exception:
            return {}

    def file_count(self) -> int:
        return len(self.get_indexed_files())

    def chunk_count(self) -> int:
        try:
            return self._collection.count()
        except Exception:
            return 0

    def clear(self):
        """Loescht den gesamten Index und erstellt ihn neu."""
        try:
            self._client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self._ef,
            metadata=HNSW_PARAMS,
        )
        _log.info("VectorStore geleert")
