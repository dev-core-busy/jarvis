"""Vector Store – ChromaDB + sentence-transformers fuer semantische Suche."""

import logging
import threading
from pathlib import Path

_log = logging.getLogger("jarvis.vector_store")
_model_lock = threading.Lock()
_embedding_model = None

COLLECTION_NAME = "knowledge_chunks"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


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
    """Adapter: sentence-transformers → ChromaDB Embedding-Interface."""

    def __call__(self, input: list[str]) -> list[list[float]]:
        model = _get_embedding_model()
        embeddings = model.encode(input, show_progress_bar=False)
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
            metadata={"hnsw:space": "cosine"},
        )
        _log.info(f"VectorStore initialisiert: {persist_dir}")

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
        batch_size = 500
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

        results = self._collection.query(
            query_texts=[query],
            n_results=min(max_results, count),
            include=["documents", "metadatas", "distances"],
        )

        output = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                # Cosine-Distanz: 0 = identisch, 2 = gegenteilig
                # Umrechnung in Aehnlichkeit: 1 - (dist/2)
                score = 1.0 - (dist / 2.0)
                output.append((score, meta["file_path"], doc))

        return output

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
        """Anzahl einzigartiger Dateien im Index."""
        return len(self.get_indexed_files())

    def chunk_count(self) -> int:
        """Gesamtanzahl der Chunks im Index."""
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
            metadata={"hnsw:space": "cosine"},
        )
        _log.info("VectorStore geleert")
