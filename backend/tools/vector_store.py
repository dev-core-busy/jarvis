"""Vector Store – FAISS + sentence-transformers (multilingual-e5-small) fuer semantische Suche.

Warum FAISS statt ChromaDB:
- 10-100x schnellere Suche (reines C++, kein Python/SQLite-Overhead)
- Geringerer RAM-Verbrauch
- Einfachere Abhaengigkeit (faiss-cpu)

Warum e5-small statt e5-base:
- ~4x schnelleres Encoding (384d statt 768d)
- ~4x kleineres Modell (~120 MB statt ~500 MB)
- Qualitaetsverlust <10% fuer typische RAG-Anwendungen

Hybride Suche (seit 2026-07-23):
Rein semantische Suche ist bei exakten Bezeichnern (@STR_UCASE, Fehlercodes,
Parameternamen) strukturell schwach – das Embedding bildet "STR_UCASE" und
"STR_LCASE" fast auf denselben Punkt ab. Deshalb laeuft parallel ein
lexikalischer BM25-Kanal ueber dieselben Chunks (kein zweiter Index: die Texte
liegen ohnehin in _meta). Beide Ranglisten werden per Reciprocal Rank Fusion
zusammengefuehrt.
"""

import json
import logging
import math
import re
import threading
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

_log = logging.getLogger("jarvis.vector_store")
_model_lock = threading.Lock()
_embedding_model = None

MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384

# Mindest-Relevanz fuer Treffer (Inner Product bei normierten Vektoren).
# ACHTUNG: e5 komprimiert Cosine-Scores auf ~0.75–0.95; ein Schwellwert von 0.40
# hat daher nie etwas gefiltert. 0.72 verwirft echten Muell, ohne Treffer zu
# kosten. Die eigentliche Trennung macht der relative Cut (RELATIVE_CUT).
MIN_SCORE = 0.72

# Relativer Cut: Treffer unterhalb dieses Anteils des besten Scores fliegen raus.
# Weil die absoluten Scores dicht beieinander liegen, ist der Abstand zum
# Top-Treffer das aussagekraeftigere Signal.
RELATIVE_CUT = 0.5
# ... aber nie weniger als so viele Treffer zurueckgeben (sonst kippt der Cut
# bei einem zufaellig sehr hohen Top-Score die gesamte Trefferliste).
MIN_KEEP = 3

# BM25-Parameter (Standardwerte aus der Literatur)
BM25_K1 = 1.5
BM25_B = 0.75

# Reciprocal Rank Fusion: kleines k gewichtet die Spitzenplaetze staerker
RRF_K = 20

_TOKEN_RE = re.compile(r"[A-Za-zÄÖÜäöüß0-9_]{2,}")

# Frage-Floskeln und Funktionswoerter. Sie stehen in fast jeder Benutzerfrage,
# tragen keine Bedeutung und ziehen den Query-Vektor in Richtung eines
# "durchschnittlichen Satzes". Gemessen: "gibt es einen befehl um im nxis einen
# String in großschreibweise zu konvertieren" findet den STR_UCASE-Abschnitt
# nicht, die auf Inhaltswoerter reduzierte Fassung schon.
_STOPWORDS = {
    "aber", "alle", "als", "am", "an", "auch", "auf", "aus", "bei", "bin", "bis",
    "da", "damit", "dann", "das", "dass", "dem", "den", "der", "des", "die", "dies",
    "diese", "diesem", "diesen", "dieser", "doch", "dort", "du", "durch", "ein",
    "eine", "einem", "einen", "einer", "eines", "er", "es", "etwas", "euer", "fuer",
    "für", "gibt", "hab", "habe", "haben", "hat", "hier", "ich", "ihr", "im", "in",
    "ins", "ist", "kann", "kannst", "koennen", "können", "man", "mich", "mir", "mit",
    "muss", "nach", "nicht", "noch", "nur", "ob", "oder", "ohne", "sein", "seine",
    "sich", "sie", "sind", "so", "soll", "über", "um", "und", "uns", "unser", "vom",
    "von", "vor", "waere", "wäre", "wann", "war", "was", "wenn", "wer", "werden",
    "wie", "wieso", "wir", "wird", "wo", "wollen", "wozu", "zu", "zum", "zur",
    "welche", "welcher", "welches", "warum", "bitte", "mal", "gern", "gerne",
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for",
    "from", "how", "i", "in", "is", "it", "of", "on", "or", "please", "the",
    "there", "to", "what", "which", "with", "you",
}


def _content_terms(text: str) -> list[str]:
    """Reduziert eine Query auf ihre Inhaltswoerter (ohne Floskeln)."""
    out = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok not in _STOPWORDS and len(tok) >= 3:
            out.append(tok)
    return out


def _lex_tokens(text: str) -> list[str]:
    """Tokenisierung fuer den lexikalischen Kanal.

    Bezeichner werden zusaetzlich in ihre Bestandteile zerlegt, damit sowohl
    "@STR_UCASE" als auch die Suche nach "ucase" trifft.
    """
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        out.append(raw)
        if "_" in raw:
            out.extend(p for p in raw.split("_") if len(p) >= 2)
    return out


def _get_embedding_model():
    """Lazy-Load des Embedding-Modells (Singleton, Thread-sicher)."""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model
    with _model_lock:
        if _embedding_model is not None:
            return _embedding_model
        from sentence_transformers import SentenceTransformer
        # PyTorch auf 2 Kerne begrenzen (verhindert CPU-Sättigung bei Indexierung)
        try:
            import torch
            torch.set_num_threads(2)
        except Exception:
            pass
        _log.info(f"Lade Embedding-Modell: {MODEL_NAME}")
        _embedding_model = SentenceTransformer(MODEL_NAME)
        _log.info("Embedding-Modell geladen")
        return _embedding_model


def release_memory_to_os() -> None:
    """Gibt vom Python-Allocator gecachten Speicher an das OS zurueck.
    Aufrufen nach Bulk-Indexierung um RAM freizugeben."""
    try:
        import gc
        gc.collect()
        # malloc_trim() gibt leere Speicherseiten direkt an den Kernel zurueck
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
        _log.info("malloc_trim() ausgefuehrt – Speicher an OS zurueckgegeben")
    except Exception as e:
        _log.debug(f"malloc_trim fehlgeschlagen: {e}")


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
        batch_size=16,   # 16 statt 64: reduziert Peak-RAM um ~75% bei Indexierung
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

        # Lexikalischer BM25-Index (lazy). _gen zaehlt Index-Aenderungen hoch;
        # weicht _lex_gen davon ab, wird der invertierte Index neu gebaut.
        self._gen = 0
        self._lex_gen = -1
        self._lex_postings: dict[str, list[tuple[int, int]]] | None = None
        self._lex_doc_lens: list[int] = []
        self._lex_avg_len = 1.0

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
                self._gen += 1
                return
            except Exception as e:
                _log.warning(f"FAISS-Index konnte nicht geladen werden, neu anlegen: {e}")
        self._reset_index()

    def _reset_index(self):
        import faiss
        self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
        self._meta = []
        self._gen += 1

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
        self._gen += 1
        self._save()

    # ─── Schreib-Operationen ─────────────────────────────────────────────────

    def add_chunks(self, file_path: str, chunks: list[str], mtime: float, save: bool = True):
        """Fuegt Chunks fuer eine Datei hinzu (ersetzt bestehende).

        ``save=False`` unterdrueckt das Schreiben auf Platte – fuer den
        Bulk-Reindex, der gedrosselt selbst per ``save()`` persistiert (sonst
        wuerde bei jeder Datei der komplette Index neu serialisiert).
        """
        if not chunks:
            self.remove_file(file_path)
            return

        # Neue Vektoren berechnen (ausserhalb des Locks – dauert laenger)
        new_vecs = _encode(chunks, prefix="passage")

        new_meta = [
            {"file_path": file_path, "mtime": mtime, "chunk_index": i, "text": t}
            for i, t in enumerate(chunks)
        ]

        with self._lock:
            has_existing = any(m["file_path"] == file_path for m in self._meta)
            if has_existing:
                # Datei war schon im Index (geaenderte Datei) → alte Chunks
                # entfernen. Das erfordert einen Neuaufbau; _rebuild speichert.
                keep = [i for i, m in enumerate(self._meta) if m["file_path"] != file_path]
                old_meta = [self._meta[i] for i in keep]
                old_vecs = self._vectors_at(keep)
                combined_vecs = (
                    np.vstack([old_vecs, new_vecs]) if len(old_vecs) > 0 else new_vecs
                )
                self._rebuild(old_meta + new_meta, combined_vecs)
            else:
                # Schnellpfad (Normalfall beim Voll-Reindex): NUR anhaengen –
                # kein Reconstruct/vstack/Neuaufbau des Gesamtindex. Das war die
                # Ursache fuer O(N²)-Speicherwachstum und OOM-Kills bei ~600
                # Dateien; jetzt konstanter Aufwand pro Datei.
                base = len(self._meta)
                self._index.add(new_vecs)
                self._meta.extend(new_meta)
                self._gen += 1
                # BM25 inkrementell nachtragen: beim ANHAENGEN verschieben sich
                # keine bestehenden Positionen, ein Vollaufbau waere Verschwendung
                # (gemessen 2,85 s bei 16k Chunks – und das unter dem Lock).
                # Nur wenn der lexikalische Index vorher aktuell war.
                if self._lex_postings is not None and self._lex_gen == self._gen - 1:
                    self._append_lexical(base, chunks)
                if save:
                    self._save()
        _log.debug(f"Indexiert: {file_path} ({len(chunks)} Chunks)")

    def save(self):
        """Persistiert Index + Metadaten auf Platte (fuer gedrosseltes
        Speichern beim Bulk-Reindex – siehe ``add_chunks(save=False)``)."""
        with self._lock:
            self._save()

    def remove_file(self, file_path: str) -> int:
        """Entfernt alle Chunks einer Datei. Gibt die Anzahl zurueck.

        Der Rueckgabewert erspart Aufrufern den Griff auf ``_meta`` (private
        Struktur, ohne Lock) nur um eine Differenz zu zaehlen.
        """
        return self.remove_files([file_path])

    def remove_files(self, file_paths) -> int:
        """Entfernt mehrere Dateien mit EINEM Index-Neuaufbau.

        Wichtig fuer den Aufraeum-Schritt des Reindex: ``remove_file`` je Datei
        bedeutete N vollstaendige Neuaufbauten samt N Plattenschreibvorgaengen
        (bei 10k Chunks ~30 MB pro Runde). Hier faellt genau einer an.
        """
        drop = {str(p) for p in (file_paths or [])}
        if not drop:
            return 0
        with self._lock:
            keep = [i for i, m in enumerate(self._meta) if m["file_path"] not in drop]
            removed = len(self._meta) - len(keep)
            if not removed:
                return 0  # nichts zu tun
            new_meta = [self._meta[i] for i in keep]
            new_vecs = self._vectors_at(keep)
            self._rebuild(new_meta, new_vecs)
            return removed

    def rename_file_path(self, old_path: str, new_path: str) -> int:
        """Schreibt die Metadaten EINER Datei auf einen neuen Pfad um – ohne
        Neu-Embedding. Einzeldatei-Pendant zu ``rename_path_prefix``.

        Die Vektoren bleiben unberuehrt: der Inhalt aendert sich beim
        Verschieben nicht, nur seine Adresse. ``mtime`` wird bewusst NICHT
        angefasst – ``Path.rename()`` laesst sie ebenfalls unveraendert, und der
        inkrementelle Reindex vergleicht genau diesen Wert. Bliebe sie hier
        stehen bzw. wuerde sie hier geaendert, wuerde die Datei beim naechsten
        Lauf unnoetig neu eingebettet.

        Gibt die Anzahl umgeschriebener Chunks zurueck.
        """
        if old_path == new_path:
            return 0
        with self._lock:
            changed = 0
            for m in self._meta:
                if m["file_path"] == old_path:
                    m["file_path"] = new_path
                    changed += 1
            if changed:
                self._save()
            return changed

    def rename_path_prefix(self, old_prefix: str, new_prefix: str) -> int:
        """Schreibt file_path-Metadaten aller Chunks unterhalb eines Ordners auf
        einen neuen Pfad um (Ordner-Umbenennung) – ohne Neu-Embedding.
        Gibt die Anzahl umgeschriebener Chunks zurueck."""
        old_dir = old_prefix.rstrip("/") + "/"
        new_dir = new_prefix.rstrip("/") + "/"
        with self._lock:
            changed = 0
            for m in self._meta:
                fp = m["file_path"]
                if fp.startswith(old_dir):
                    m["file_path"] = new_dir + fp[len(old_dir):]
                    changed += 1
            if changed:
                self._save()
            return changed

    def remove_path_prefix(self, prefix: str) -> int:
        """Entfernt alle Chunks von Dateien unterhalb eines Ordner-Pfads
        (Ordner-Loeschung). Gibt die Anzahl entfernter Chunks zurueck."""
        pref = prefix.rstrip("/") + "/"
        with self._lock:
            keep = [i for i, m in enumerate(self._meta)
                    if not m["file_path"].startswith(pref)]
            removed = len(self._meta) - len(keep)
            if removed:
                new_meta = [self._meta[i] for i in keep]
                new_vecs = self._vectors_at(keep)
                self._rebuild(new_meta, new_vecs)
            return removed

    def clear(self):
        """Loescht den gesamten Index."""
        with self._lock:
            self._reset_index()
            self._save()
        _log.info("VectorStore geleert")

    # ─── Suche ───────────────────────────────────────────────────────────────

    def _search_vector_idx(self, query: str, k: int) -> list[tuple[int, float]]:
        """Semantischer Kanal. Gibt (meta_index, cosine_score) absteigend zurueck."""
        with self._lock:
            total = len(self._meta)
        if total == 0:
            return []

        query_vec = _encode([query], prefix="query")  # (1, 384)
        with self._lock:
            scores, indices = self._index.search(query_vec, min(k, total))

        out = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or float(score) < MIN_SCORE:
                continue
            out.append((int(idx), float(score)))
        return out

    @staticmethod
    def _build_postings(meta_snapshot: list[dict]):
        """Baut den invertierten Index aus einer Meta-Kopie. Haelt KEIN Lock."""
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        doc_lens: list[int] = []
        for i, m in enumerate(meta_snapshot):
            toks = _lex_tokens(m.get("text", ""))
            doc_lens.append(len(toks) or 1)
            for tok, tf in Counter(toks).items():
                postings[tok].append((i, tf))
        return dict(postings), doc_lens

    def _append_lexical(self, base: int, chunks: list[str]) -> None:
        """Traegt angehaengte Chunks in den bestehenden BM25-Index nach.
        Aufrufer muss self._lock halten und darf NUR angehaengt haben."""
        for off, txt in enumerate(chunks):
            toks = _lex_tokens(txt)
            self._lex_doc_lens.append(len(toks) or 1)
            for tok, tf in Counter(toks).items():
                self._lex_postings.setdefault(tok, []).append((base + off, tf))
        if self._lex_doc_lens:
            self._lex_avg_len = sum(self._lex_doc_lens) / len(self._lex_doc_lens)
        self._lex_gen = self._gen

    def _ensure_lexical_index(self):
        """Baut den invertierten BM25-Index, falls er zur aktuellen Generation fehlt.

        Der Aufbau laeuft AUSSERHALB des Locks: er kostet bei 16k Chunks knapp
        drei Sekunden, und unter dem Lock wartet in dieser Zeit JEDE andere Suche.
        Gebaut wird auf einer Kopie der Meta-Liste; eingehaengt wird nur, wenn sich
        die Generation zwischenzeitlich nicht geaendert hat (sonst passten die
        Positionen nicht mehr).

        Aufrufer darf self._lock NICHT halten.
        """
        for _ in range(2):
            with self._lock:
                if self._lex_postings is not None and self._lex_gen == self._gen:
                    return
                gen = self._gen
                snapshot = list(self._meta)
            postings, doc_lens = self._build_postings(snapshot)
            with self._lock:
                if gen != self._gen:
                    continue    # Index hat sich geaendert -> genau ein Neuversuch
                self._lex_postings = postings
                self._lex_doc_lens = doc_lens
                self._lex_avg_len = (sum(doc_lens) / len(doc_lens)) if doc_lens else 1.0
                self._lex_gen = gen
                _log.debug(f"BM25-Index gebaut: {len(doc_lens)} Chunks, {len(postings)} Terme")
                return

    def _search_lexical_idx(self, query: str, k: int) -> list[tuple[int, float]]:
        """Lexikalischer BM25-Kanal. Gibt (meta_index, bm25_score) absteigend zurueck."""
        self._ensure_lexical_index()        # ohne Lock (baut ggf. neu)
        with self._lock:
            # Passt der Index nicht zur aktuellen Generation, liefert der
            # lexikalische Kanal diese Runde nichts – lieber ein Kanal weniger
            # als Treffer auf verschobenen Positionen.
            if not self._lex_postings or self._lex_gen != self._gen:
                return []
            n_docs = len(self._meta)
            if n_docs == 0:
                return []
            scores: dict[int, float] = defaultdict(float)
            for tok in set(_lex_tokens(query)):
                post = self._lex_postings.get(tok)
                if not post:
                    continue
                df = len(post)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                for doc_i, tf in post:
                    dl = self._lex_doc_lens[doc_i]
                    denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * dl / self._lex_avg_len)
                    scores[doc_i] += idf * (tf * (BM25_K1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return ranked[:k]

    def search(self, query: str, max_results: int) -> list[tuple[float, str, str]]:
        """Rein semantische Suche. Gibt (score, file_path, chunk_text) zurueck.

        Fuer die Wissenssuche wird search_hybrid() verwendet; diese Methode
        bleibt fuer Aufrufer erhalten, die ausschliesslich Cosine-Scores wollen.
        """
        hits = self._search_vector_idx(query, max_results * 2)
        with self._lock:
            out = [(s, self._meta[i]["file_path"], self._meta[i]["text"]) for i, s in hits]
        return out[:max_results]

    def search_hybrid(self, query: str, max_results: int,
                      weight_fn=None) -> list[tuple[float, str, str]]:
        """Hybride Suche: semantisch + BM25, fusioniert per Reciprocal Rank Fusion.

        Drei Kanaele gehen in die Fusion:
          1. semantisch mit der Original-Query
          2. semantisch mit der auf Inhaltswoerter reduzierten Query
             (Frage-Floskeln verwaessern den Query-Vektor spuerbar)
          3. lexikalisch (BM25)

        ``weight_fn(file_path) -> float`` gewichtet Treffer nach ihrer HERKUNFT
        (z.B. Abwertung gelernter Notizen). Die Gewichtung passiert VOR dem
        relativen Cut – wird sie erst danach angewendet, misst der Cut noch am
        unabgewerteten Spitzenreiter und verwirft Primaerdokumente, die nach der
        Abwertung vorn laegen.

        Der zurueckgegebene Score ist der auf 1.0 normierte RRF-Wert (Top-Treffer
        = 1.00) – ein Rang-Mass, kein Cosine-Wert. Das ist fuer die Anzeige
        aussagekraeftiger als die stark komprimierten e5-Rohscores.

        Aendert sich der Index waehrend der Suche, verschieben sich die
        Meta-Positionen und die Kanal-Treffer zeigen auf fremde Chunks. Deshalb
        wird die Generation geprueft und die Suche EINMAL wiederholt.
        """
        out = self._search_hybrid_once(query, max_results, weight_fn, strict=True)
        if out is None:
            _log.debug("Index waehrend der Suche geaendert – ein Neuversuch")
            out = self._search_hybrid_once(query, max_results, weight_fn, strict=False)
        return out or []

    def _search_hybrid_once(self, query: str, max_results: int, weight_fn,
                            strict: bool) -> list[tuple[float, str, str]] | None:
        """Ein Durchgang der Hybridsuche.

        ``strict=True``: Hat sich der Index zwischendurch geaendert, wird ``None``
        zurueckgegeben (der Aufrufer wiederholt). ``strict=False``: bestmoegliches
        Ergebnis mit Bereichspruefung.
        """
        with self._lock:
            total = len(self._meta)
            gen_at_start = self._gen
        if total == 0:
            return []

        # Grosszuegiger Pool je Kanal: die Fusion soll aus allen Listen schoepfen
        pool = min(max(max_results * 4, 40), total)

        channels = [self._search_vector_idx(query, pool)]

        # Zweiter semantischer Kanal nur, wenn die Reduktion die Query wirklich
        # veraendert (sonst doppeltes Encoding fuer dasselbe Ergebnis).
        terms = _content_terms(query)
        reduced = " ".join(terms)
        if terms and reduced != query.strip().lower():
            channels.append(self._search_vector_idx(reduced, pool))

        channels.append(self._search_lexical_idx(query, pool))

        if not any(channels):
            return []

        rrf: dict[int, float] = defaultdict(float)
        for hits in channels:
            for rank, (idx, _score) in enumerate(hits):
                rrf[idx] += 1.0 / (RRF_K + rank + 1)

        output: list[tuple[float, str, str]] = []
        with self._lock:
            if gen_at_start != self._gen:
                if strict:
                    return None
                # Bestmoeglich weiter: die Bereichspruefung unten faengt
                # zumindest Ueberlaeufe ab.
            meta = self._meta

            # Herkunfts-Gewichtung VOR dem Cut anwenden (siehe Docstring).
            if weight_fn is not None:
                weighted = []
                for idx, score in rrf.items():
                    if idx >= len(meta):
                        continue
                    try:
                        w = float(weight_fn(meta[idx]["file_path"]))
                    except Exception:
                        w = 1.0
                    weighted.append((idx, score * w))
                ranked = sorted(weighted, key=lambda x: x[1], reverse=True)
            else:
                ranked = sorted(rrf.items(), key=lambda x: x[1], reverse=True)

            if not ranked:
                return []
            top = ranked[0][1] or 1.0

            for pos, (idx, score) in enumerate(ranked):
                if pos >= MIN_KEEP and score < top * RELATIVE_CUT:
                    break
                if idx >= len(meta):
                    continue
                m = meta[idx]
                output.append((score / top, m["file_path"], m["text"]))
                if len(output) >= max_results:
                    break
        return output

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
        """Extrahiert Vektoren fuer gegebene Indizes aus dem FAISS-Index.

        ``reconstruct_n`` holt ALLE Vektoren in EINEM Aufruf; die Auswahl macht
        danach numpy. Die fruehere Variante rief ``reconstruct`` je Vektor auf –
        bei 16k Chunks 16k einzelne Uebergaenge nach C++ fuer jede Entfernung.
        """
        if not indices or self._index.ntotal == 0:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
        all_vecs = self._index.reconstruct_n(0, self._index.ntotal)
        return np.asarray(all_vecs, dtype=np.float32)[np.asarray(indices, dtype=np.int64)]
