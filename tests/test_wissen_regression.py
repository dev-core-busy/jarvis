#!/usr/bin/env python3
"""Regressionstests zum Wissens-Code-Review vom 2026-07-30.

Jeder Test haelt GENAU EINEN Befund fest. Die Kommentare nennen die Befund-ID
und was der alte Stand getan haette – ein Test, dessen Sinn man nicht mehr
versteht, wird beim naechsten Umbau geloescht.

Laeuft ohne pytest:      python3 tests/test_wissen_regression.py
Ohne faiss/torch werden die davon abhaengigen Tests uebersprungen (der Rest
laeuft ueber Attrappen und deckt die Logik vollstaendig ab).
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.tools.knowledge as K            # noqa: E402
import backend.tools.vector_store as VS        # noqa: E402
import backend.web_extractor as WX             # noqa: E402

_results = []



def _inval():
    """Dateilisten-Cache leeren, falls vorhanden.

    Als getattr, damit die Verhaltens-Tests (A-2/A-3) auch gegen den ALTEN Stand
    laufen und dort INHALTLICH scheitern statt an einem AttributeError – nur so
    beweist die Gegenprobe etwas.
    """
    fn = getattr(K, "invalidate_files_cache", None)
    if fn:
        fn()

def check(name, cond, detail=""):
    _results.append((name, bool(cond), detail))
    print(("  ✅ " if cond else "  ❌ ") + name + ((" – " + detail) if detail and not cond else ""))
    return bool(cond)


def section(title):
    print("\n" + title)


try:
    import faiss  # noqa: F401
    HAS_FAISS = True
except Exception:
    HAS_FAISS = False


# ─── Attrappen ───────────────────────────────────────────────────────────────

class FakeVS:
    """Vektorspeicher-Attrappe: zeichnet auf, WAS mit dem Index geschah."""

    def __init__(self, indexed=None):
        self._files = dict(indexed or {})          # path -> mtime
        self.added = []                            # (path, n_chunks)
        self.removed = []                          # einzelne Entfernungen
        self.removed_batches = []                  # Sammel-Entfernungen
        self.cleared = 0

    def get_indexed_files(self):
        return dict(self._files)

    def add_chunks(self, path, chunks, mtime, save=True):
        self._files[path] = mtime
        self.added.append((path, len(chunks)))

    def remove_file(self, path):
        self.removed.append(path)
        return 1 if self._files.pop(path, None) is not None else 0

    def remove_files(self, paths):
        paths = list(paths)
        self.removed_batches.append(paths)
        n = 0
        for p in paths:
            if self._files.pop(p, None) is not None:
                n += 1
        return n

    def clear(self):
        self.cleared += 1
        self._files.clear()

    def chunk_count(self):
        return len(self._files)

    def file_count(self):
        return len(self._files)

    def save(self):
        pass


def make_store(meta):
    """VectorStore-Instanz OHNE __init__ (und damit ohne faiss) fuer Rang-Tests."""
    vs = VS.VectorStore.__new__(VS.VectorStore)
    vs._meta = meta
    vs._lock = threading.RLock()
    vs._gen = 1
    vs._lex_gen = -1
    vs._lex_postings = None
    vs._lex_doc_lens = []
    vs._lex_avg_len = 1.0
    return vs


# ─── A-3: Bilder gehoeren in den Ordner-Scan ─────────────────────────────────

def test_a3_bilder_werden_erfasst():
    section("A-3  Bilder im Wissensordner")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "handbuch.pdf").write_bytes(b"%PDF-1.4 x")
        (root / "schema.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (root / "foto.JPG").write_bytes(b"\xff\xd8\xff")
        (root / ".versteckt.md").write_text("x")
        found = {p.name for p in K._all_files([root])}
    # Alter Stand: EXTENSIONS_IMAGE fehlte in all_exts -> Bilder unsichtbar, und
    # kg.prune() entfernte danach ihre Gruppen-Zuordnung.
    check("PNG wird erfasst", "schema.png" in found, str(found))
    check("JPG erfasst (Endung Gross geschrieben)", "foto.JPG" in found, str(found))
    check("PDF weiterhin erfasst", "handbuch.pdf" in found, str(found))
    check("versteckte Datei weiterhin ignoriert", ".versteckt.md" not in found, str(found))


# ─── A-2: totes Netzlaufwerk darf nichts loeschen ────────────────────────────

def test_a2_totes_laufwerk():
    section("A-2  Nicht erreichbarer Ordner")
    with tempfile.TemporaryDirectory() as td:
        lokal = Path(td) / "lokal"
        lokal.mkdir()
        (lokal / "da.md").write_text("Inhalt " * 50)
        share = Path(td) / "share"          # existiert, wird aber als "tot" gemeldet
        share.mkdir()
        (share / "vom_share.md").write_text("Inhalt " * 50)

        indexed = {str(lokal / "da.md"): (lokal / "da.md").stat().st_mtime,
                   str(share / "vom_share.md"): 1.0}
        fake = FakeVS(indexed)

        orig_get, orig_exists, orig_extract = K._get_vector_store, K._safe_exists, K._extract_text
        K._get_vector_store = lambda: fake
        K._safe_exists = lambda p, timeout=2.0: "share" not in str(p)   # Share ist tot
        K._extract_text = lambda p, mb: "Inhalt " * 50
        _inval()
        try:
            K._rebuild_vector_index([lokal, share], 10 * 1024 * 1024, force=True)
        finally:
            K._get_vector_store, K._safe_exists, K._extract_text = orig_get, orig_exists, orig_extract
            _inval()

        # Alter Stand: der Share fehlte in current_paths -> jede seiner Dateien
        # galt als geloescht und wurde einzeln aus dem Index geworfen.
        check("Chunks des toten Shares bleiben im Index",
              str(share / "vom_share.md") in fake.get_indexed_files(),
              f"entfernt: {fake.removed} / {fake.removed_batches}")
        check("keine Einzel-Entfernung ausgeloest", not fake.removed, str(fake.removed))


def test_a2_suchpfad_entfernt_nie():
    section("A-2  Suchpfad raeumt grundsaetzlich nicht auf")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "neu.md").write_text("Inhalt " * 50)
        fake = FakeVS({str(root / "laengst_geloescht.md"): 1.0})

        orig_get, orig_extract = K._get_vector_store, K._extract_text
        K._get_vector_store = lambda: fake
        K._extract_text = lambda p, mb: "Inhalt " * 50
        _inval()
        try:
            K._rebuild_vector_index([root], 10 * 1024 * 1024, force=False)
        finally:
            K._get_vector_store, K._extract_text = orig_get, orig_extract
            _inval()

        check("verwaister Eintrag bleibt (Aufraeumen ist Sache des Reindex)",
              str(root / "laengst_geloescht.md") in fake.get_indexed_files())
        check("neue Datei wurde trotzdem indiziert", any("neu.md" in a[0] for a in fake.added),
              str(fake.added))


def test_a2_gegenprobe_echte_karteileiche():
    section("A-2  Gegenprobe: echte Karteileiche wird beim Reindex entfernt")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "da.md").write_text("Inhalt " * 50)
        fake = FakeVS({str(root / "da.md"): (root / "da.md").stat().st_mtime,
                       str(root / "weg.md"): 1.0})

        orig_get, orig_extract = K._get_vector_store, K._extract_text
        K._get_vector_store = lambda: fake
        K._extract_text = lambda p, mb: "Inhalt " * 50
        _inval()
        try:
            K._rebuild_vector_index([root], 10 * 1024 * 1024, force=True)
        finally:
            K._get_vector_store, K._extract_text = orig_get, orig_extract
            _inval()

        check("geloeschte Datei fliegt raus", str(root / "weg.md") not in fake.get_indexed_files())
        check("Entfernung als EINE Sammel-Operation", len(fake.removed_batches) == 1,
              f"{fake.removed_batches}")


# ─── A-6: unlesbare Datei behaelt ihren Indexstand ───────────────────────────

def test_a6_unlesbar_behaelt_index():
    section("A-6  Zu grosse / unlesbare Datei")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "waechst.md"
        f.write_text("Inhalt " * 50)
        fake = FakeVS({str(f): 1.0})           # alter mtime -> gilt als geaendert

        orig_get, orig_extract = K._get_vector_store, K._extract_text
        K._get_vector_store = lambda: fake
        K._extract_text = lambda p, mb: None    # zu gross / Parser fehlt
        _inval()
        try:
            K._rebuild_vector_index([root], 10 * 1024 * 1024, force=True)
        finally:
            K._get_vector_store, K._extract_text = orig_get, orig_extract
            _inval()

        # Alter Stand: else-Zweig -> vs.remove_file() -> stiller Index-Verlust.
        check("bisheriger Indexstand bleibt erhalten", str(f) in fake.get_indexed_files(),
              f"entfernt: {fake.removed}")
        check("Fehler wird gezaehlt", K.get_index_progress().get("failed", 0) >= 1,
              str(K.get_index_progress().get("failed")))


def test_a6_leere_datei_wird_entfernt():
    section("A-6  Gegenprobe: lesbar aber leer")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "leer.md"
        f.write_text("x")
        fake = FakeVS({str(f): 1.0})

        orig_get, orig_extract = K._get_vector_store, K._extract_text
        K._get_vector_store = lambda: fake
        K._extract_text = lambda p, mb: "   "   # lesbar, aber ohne Inhalt
        _inval()
        try:
            K._rebuild_vector_index([root], 10 * 1024 * 1024, force=True)
        finally:
            K._get_vector_store, K._extract_text = orig_get, orig_extract
            _inval()

        check("leerer Eintrag wird entfernt", str(f) not in fake.get_indexed_files())


# ─── A-1: Freigabe haengt an, statt alles neu zu bauen ───────────────────────

def test_a1_freigabe_ohne_vollreindex():
    section("A-1  Entwurfs-Freigabe")
    with tempfile.TemporaryDirectory() as td:
        ziel = Path(td) / "wissen"
        ziel.mkdir()
        fake = FakeVS()
        reindex_calls = []

        orig_pending = WX.PENDING_DIR
        WX.PENDING_DIR = Path(td) / "pending"
        WX.PENDING_DIR.mkdir()
        WX.save_pending({
            "id": "abc12345", "title": "Testdokument", "url": "file://t.pdf",
            "summary": "Zusammenfassung.", "facts": ["Fakt eins.", "Fakt zwei."],
            "qa_pairs": [{"id": "q1", "q": "Frage?", "a": "Antwort.", "approved": True},
                         {"id": "q2", "q": "Weg?", "a": "Nein.", "approved": False}],
            "created_at": int(time.time()), "status": "pending",
        })

        orig_get, orig_folders = K._get_vector_store, K._get_folders
        K._get_vector_store = lambda: fake
        K._get_folders = lambda: [ziel]
        orig_force = K.force_reindex
        K.force_reindex = lambda *a, **kw: reindex_calls.append(1)
        try:
            res = WX.approve_pending("abc12345")
            time.sleep(0.3)     # ein etwaiger Hintergrund-Thread haette Zeit
        finally:
            K._get_vector_store, K._get_folders = orig_get, orig_folders
            K.force_reindex = orig_force
            WX.PENDING_DIR = orig_pending

        # Alter Stand: force_reindex() -> vs.clear() -> gesamte Wissensdatenbank
        # neu einbetten, Suche waehrenddessen tot.
        check("kein vs.clear()", fake.cleared == 0, f"cleared={fake.cleared}")
        check("kein Voll-Reindex angestossen", not reindex_calls, str(reindex_calls))
        check("genau EINE Datei angehaengt", len(fake.added) == 1, str(fake.added))
        check("angehaengt wurde die neue Wissensdatei",
              fake.added and fake.added[0][0].endswith(".md"), str(fake.added))
        check("nur freigegebene Q&A im Dokument", res["qa_count"] == 1, str(res))
        # Wissensordner ausserhalb des Projektverzeichnisses (wie ein Netzlaufwerk):
        # der Pfad muss absolut zurueckkommen statt eine ValueError zu werfen.
        check("Ordner ausserhalb PROJECT_ROOT wird verkraftet",
              Path(res["file"]).name.startswith("extract_"), str(res.get("file")))
        md = (ziel / Path(res["file"]).name).read_text(encoding="utf-8")
        check("Antwort steht in der Datei", "Antwort." in md)
        check("abgewaehltes Paar fehlt", "Nein." not in md)


# ─── A-5: Herkunfts-Gewicht wirkt VOR dem Cut ────────────────────────────────

def _stub_channels(vs, ranking):
    """Laesst alle drei Kanaele dieselbe Reihenfolge liefern."""
    vs._search_vector_idx = lambda q, k: [(i, 1.0) for i in ranking]
    vs._search_lexical_idx = lambda q, k: [(i, 1.0) for i in ranking]


def test_a5_gewicht_vor_dem_cut():
    section("A-5  Abwertung gelernter Notizen")
    meta = [
        {"file_path": "/opt/jarvis/data/knowledge/learned/2026-07/conv_1.md", "text": "gelernt"},
        {"file_path": "/opt/jarvis/data/knowledge/handbuch.md", "text": "primaer"},
        {"file_path": "/opt/jarvis/data/knowledge/rest.md", "text": "rest"},
        {"file_path": "/opt/jarvis/data/knowledge/rest2.md", "text": "rest2"},
        {"file_path": "/opt/jarvis/data/knowledge/rest3.md", "text": "rest3"},
    ]
    vs = make_store(meta)
    _stub_channels(vs, [0, 1, 2, 3, 4])         # Lernnotiz steht auf Platz 1

    ohne = vs.search_hybrid("frage", 5)
    mit = vs.search_hybrid("frage", 5, weight_fn=K._learned_weight)

    check("ohne Gewichtung fuehrt die Lernnotiz", "conv_1.md" in ohne[0][1], str(ohne[0][1]))
    check("mit Gewichtung fuehrt das Primaerdokument", "handbuch.md" in mit[0][1],
          " / ".join(x[1].rsplit("/", 1)[-1] for x in mit))
    # Der Cut misst jetzt am GEWICHTETEN Spitzenreiter – die Lernnotiz bleibt
    # in der Liste, verdraengt aber nichts mehr.
    check("Lernnotiz weiterhin enthalten (nur abgewertet)",
          any("conv_1.md" in r[1] for r in mit))
    check("Spitzenwert ist auf 1.00 normiert", abs(mit[0][0] - 1.0) < 1e-9, str(mit[0][0]))


def test_a5_ohne_lernnotiz_unveraendert():
    section("A-5  Gegenprobe: ohne Lernnotizen aendert die Gewichtung nichts")
    meta = [{"file_path": f"/opt/jarvis/data/knowledge/d{i}.md", "text": f"t{i}"} for i in range(5)]
    vs = make_store(meta)
    _stub_channels(vs, [0, 1, 2, 3, 4])
    ohne = [r[1] for r in vs.search_hybrid("frage", 5)]
    mit = [r[1] for r in vs.search_hybrid("frage", 5, weight_fn=K._learned_weight)]
    check("identische Reihenfolge", ohne == mit, f"{ohne} vs {mit}")


# ─── A-4: Index-Aenderung waehrend der Suche ─────────────────────────────────

def test_a4_generationswechsel():
    section("A-4  Index aendert sich waehrend der Suche")
    meta = [{"file_path": f"/kb/datei_{i}.md", "text": f"inhalt {i}"} for i in range(6)]
    vs = make_store(meta)

    zustand = {"n": 0}

    def kippen(q, k):
        # Beim ERSTEN Durchgang aendert sich der Index zwischen den Kanaelen:
        # genau das Fenster, in dem sich die Positionen verschieben.
        zustand["n"] += 1
        if zustand["n"] == 2:
            with vs._lock:
                vs._meta = [{"file_path": "/kb/ganz_andere.md", "text": "fremd"}] + vs._meta
                vs._gen += 1
        return [(0, 1.0), (1, 0.9)]

    vs._search_vector_idx = kippen
    vs._search_lexical_idx = lambda q, k: [(0, 1.0)]

    out = vs.search_hybrid("frage", 3)
    # Alter Stand: Positionen aus dem ALTEN Zustand wurden gegen die NEUE Liste
    # aufgeloest -> Text von Datei X unter dem Namen von Datei Y.
    ok = all(m["file_path"] == out_i[1] and m["text"] == out_i[2]
             for out_i in out
             for m in [next(x for x in vs._meta if x["file_path"] == out_i[1])])
    check("Pfad und Text gehoeren zusammen", ok, str(out))
    check("Ergebnis nicht leer", len(out) > 0, str(out))


# ─── B-2: inkrementeller BM25-Index ──────────────────────────────────────────

def test_b2_bm25_inkrementell():
    section("B-2  BM25 inkrementell vs. Vollaufbau")
    meta = [{"file_path": "/kb/a.md", "text": "alpha beta gamma"},
            {"file_path": "/kb/b.md", "text": "beta delta"}]
    vs = make_store(meta)
    vs._ensure_lexical_index()
    voll_postings = dict(vs._lex_postings)
    voll_lens = list(vs._lex_doc_lens)

    # Zwei Chunks anhaengen und inkrementell nachtragen
    neue = ["gamma epsilon", "zeta"]
    with vs._lock:
        base = len(vs._meta)
        vs._meta.extend([{"file_path": "/kb/c.md", "text": t} for t in neue])
        vs._gen += 1
        vs._append_lexical(base, neue)

    inkrementell = {k: sorted(v) for k, v in vs._lex_postings.items()}
    inkrementell_lens = list(vs._lex_doc_lens)
    inkrementell_gen = vs._lex_gen

    # Gegenprobe: Vollaufbau derselben Liste
    vs2 = make_store(list(vs._meta))
    vs2._ensure_lexical_index()
    referenz = {k: sorted(v) for k, v in vs2._lex_postings.items()}

    check("Postings identisch zum Vollaufbau", inkrementell == referenz,
          f"{sorted(inkrementell.items())[:2]} vs {sorted(referenz.items())[:2]}")
    check("Dokumentlaengen identisch", inkrementell_lens == vs2._lex_doc_lens)
    check("Generation als aktuell markiert (kein Vollaufbau noetig)",
          inkrementell_gen == vs._gen, f"{inkrementell_gen} != {vs._gen}")
    check("Vollaufbau vorher war korrekt", len(voll_postings) > 0 and len(voll_lens) == 2)


def test_b2_bm25_ohne_lock_aufgebaut():
    section("B-2  BM25-Aufbau blockiert keine andere Suche")
    meta = [{"file_path": f"/kb/{i}.md", "text": f"wort{i} gemeinsam"} for i in range(200)]
    vs = make_store(meta)
    gehalten = {"während_aufbau": False}

    orig_build = VS.VectorStore._build_postings

    def langsam(snapshot):
        # Waehrend des Aufbaus muss das Lock FREI sein – sonst haengt hier jede
        # parallele Suche (gemessen: 2,85 s bei 16k Chunks).
        gehalten["während_aufbau"] = vs._lock.acquire(blocking=False)
        if gehalten["während_aufbau"]:
            vs._lock.release()
        return orig_build(snapshot)

    VS.VectorStore._build_postings = staticmethod(langsam)
    try:
        vs._ensure_lexical_index()
    finally:
        VS.VectorStore._build_postings = staticmethod(orig_build)

    check("Lock ist waehrend des Aufbaus frei", gehalten["während_aufbau"])
    check("Index danach nutzbar", vs._lex_postings is not None and vs._lex_gen == vs._gen)


# ─── D-4 / D-6 / D-2: Kleinbefunde ───────────────────────────────────────────

def test_d4_zielordner_der_gruppe():
    section("D-4  Zielordner folgt der Wissensgruppe")
    with tempfile.TemporaryDirectory() as td:
        default = Path(td) / "knowledge"
        gruppe = Path(td) / "ibs"
        default.mkdir(); gruppe.mkdir()

        orig_folders = K._get_folders
        K._get_folders = lambda: [default, gruppe]
        import backend.knowledge_groups as KG
        orig_get_group = KG.get_group
        KG.get_group = lambda gid: ({"id": "ibs", "folders": [str(gruppe)]}
                                    if gid == "ibs" else None)
        try:
            mit = WX._target_dir_for_groups(["ibs"])
            ohne = WX._target_dir_for_groups([])
            unbekannt = WX._target_dir_for_groups(["gibtsnicht"])
        finally:
            K._get_folders = orig_folders
            KG.get_group = orig_get_group

    check("Gruppenordner wird bevorzugt", mit == gruppe, f"{mit}")
    check("ohne Gruppe der erste konfigurierte Ordner", ohne == default, f"{ohne}")
    check("unbekannte Gruppe faellt sauber zurueck", unbekannt == default, f"{unbekannt}")


def test_d6_aufraeumen_nur_uebernommene():
    section("D-6  Vorhaltezeit fuer Entwuerfe")
    with tempfile.TemporaryDirectory() as td:
        orig = WX.PENDING_DIR
        WX.PENDING_DIR = Path(td)
        alt = time.time() - 200 * 86400
        try:
            WX.save_pending({"id": "alt_appr", "status": "approved", "approved_at": alt,
                             "title": "x", "qa_pairs": [], "facts": []})
            WX.save_pending({"id": "neu_appr", "status": "approved",
                             "approved_at": time.time(), "title": "x",
                             "qa_pairs": [], "facts": []})
            WX.save_pending({"id": "alt_offen", "status": "pending", "created_at": alt,
                             "title": "x", "qa_pairs": [], "facts": []})
            n = WX.cleanup_approved(90)
            uebrig = {d["id"] for d in WX.list_pending()}
        finally:
            WX.PENDING_DIR = orig

    check("genau ein Entwurf abgeraeumt", n == 1, f"n={n}")
    check("alter uebernommener Entwurf ist weg", "alt_appr" not in uebrig, str(uebrig))
    check("frisch uebernommener bleibt", "neu_appr" in uebrig, str(uebrig))
    check("OFFENER Entwurf bleibt IMMER", "alt_offen" in uebrig, str(uebrig))
    check("Vorhaltezeit 0 raeumt nichts ab", WX.cleanup_approved(0) == 0)


def test_d2_schema_default():
    section("D-2  Schema-Angabe stimmt mit dem Code ueberein")
    schema = K.KnowledgeTool().parameters_schema()
    beschr = schema["properties"]["max_results"]["description"]
    check("Beschreibung nennt Standard 8", "8" in beschr and "5" not in beschr, beschr)


def test_a8_vector_store_neuversuch():
    section("A-8  Vektorspeicher-Initialisierung")
    orig_checked = K._vector_store_checked
    orig_retry = K._vector_store_retry_after
    orig_store = K._vector_store
    try:
        K._vector_store = None
        K._vector_store_checked = True
        K._vector_store_retry_after = time.time() - 1     # Wartezeit abgelaufen
        st = K.vector_store_status()
        check("Zustand ist abfragbar", isinstance(st, dict) and "available" in st, str(st))
        check("gescheiterter Aufbau meldet 'fehler'", st["state"] == "fehler", str(st))
        check("nicht als dauerhaft aus markiert", st["permanently_off"] is False, str(st))
        K._vector_store_retry_after = float("inf")
        st2 = K.vector_store_status()
        check("fehlende Abhaengigkeit = dauerhaft aus", st2["permanently_off"] is True, str(st2))
        check("und traegt den Zustand 'nicht_installiert'",
              st2["state"] == "nicht_installiert", str(st2))
        # Der haeufigste Fall: noch nie gebraucht. Darf NICHT wie eine Stoerung
        # aussehen – genau das meldete die erste Fassung nach jedem Neustart.
        K._vector_store_checked = False
        st3 = K.vector_store_status()
        check("nicht initialisiert wird als 'unbenutzt' gemeldet",
              st3["state"] == "unbenutzt" and st3["permanently_off"] is False, str(st3))
    finally:
        K._vector_store_checked = orig_checked
        K._vector_store_retry_after = orig_retry
        K._vector_store = orig_store


# ─── B-3 / B-4: nur mit faiss ────────────────────────────────────────────────

def test_b4_sammel_entfernung():
    section("B-3/B-4  Sammel-Entfernung und reconstruct_n (echter FAISS-Index)")
    if not HAS_FAISS:
        print("  ⏭  uebersprungen (faiss nicht installiert)")
        return
    import numpy as np
    with tempfile.TemporaryDirectory() as td:
        vs = VS.VectorStore(Path(td))
        rng = np.random.default_rng(7)
        for name in ("a", "b", "c"):
            vecs = rng.standard_normal((3, VS.EMBEDDING_DIM)).astype("float32")
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
            with vs._lock:
                vs._index.add(vecs)
                vs._meta.extend([{"file_path": f"/kb/{name}.md", "mtime": 1.0,
                                  "chunk_index": i, "text": f"{name}{i}"} for i in range(3)])
                vs._gen += 1

        vorher = vs.chunk_count()
        entfernt = vs.remove_files(["/kb/a.md", "/kb/c.md"])
        check("Chunkzahl stimmt", vs.chunk_count() == vorher - 6, f"{vs.chunk_count()}")
        check("Rueckgabewert stimmt", entfernt == 6, str(entfernt))
        check("nur b bleibt", {m["file_path"] for m in vs._meta} == {"/kb/b.md"})
        check("Index und Meta gleich lang", vs._index.ntotal == len(vs._meta),
              f"{vs._index.ntotal} != {len(vs._meta)}")
        check("remove_file liefert Anzahl", vs.remove_file("/kb/b.md") == 3)
        check("Index danach leer", vs.chunk_count() == 0 and vs._index.ntotal == 0)


# ─── Quelltext-Pruefungen (kein Import von main.py noetig) ───────────────────

def test_quelltext():
    section("Quelltext-Pruefungen")
    main_src = (Path(__file__).resolve().parent.parent / "backend" / "main.py").read_text(encoding="utf-8")
    check("D-3: .ods nicht mehr in _QA_EXTS",
          '".ods"' not in main_src.split("_QA_EXTS = {")[1].split("}")[0])
    check("D-3: .rst nicht mehr in _QA_EXTS",
          '".rst"' not in main_src.split("_QA_EXTS = {")[1].split("}")[0])
    check("A-1: Lösch-Endpunkt nutzt purge_file_index statt force_reindex",
          "purge_file_index, invalidate_files_cache" in main_src)
    check("D-6: Aufraeum-Schleife ist verdrahtet", "startup_pending_retention" in main_src)

    kn_src = (Path(__file__).resolve().parent.parent / "backend" / "tools" / "knowledge.py").read_text(encoding="utf-8")
    check("D-1: Suchmodus faellt auf TF-IDF zurueck",
          kn_src.count('search_mode_cfg = "auto"') == 2 and 'search_mode_cfg = "vector"' not in kn_src)
    check("B-1: kein bedingungsloser Ordner-Scan mehr im Suchpfad",
          "files_on_disk = _all_files(folders)" not in kn_src)

    agent_src = (Path(__file__).resolve().parent.parent / "backend" / "agent.py").read_text(encoding="utf-8")
    check("Prompt-Regel zu Widerspruechen vorhanden",
          "WIDERSPRUECHLICHE FUNDSTELLEN" in agent_src)

    skill = json.loads((Path(__file__).resolve().parent.parent / "skills" / "knowledge" / "skill.json").read_text(encoding="utf-8"))
    check("D-1: totes Feld search_mode entfernt",
          "search_mode" not in skill["config_schema"])

    wissen_js = (Path(__file__).resolve().parent.parent / "frontend" / "js" / "wissen.js").read_text(encoding="utf-8")
    check("D-5: Zusammenfassung im Audit bearbeitbar", "wi-rev-summary" in wissen_js)
    check("D-5: Kernfakten im Audit bearbeitbar", "wi-rev-facts" in wissen_js)
    check("D-5: beide Felder werden mitgesendet",
          "patch.summary" in wissen_js and "patch.facts" in wissen_js)


# ─── Lauf ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Regressionstests Wissenssystem – Code-Review 2026-07-30")
    print("=" * 70)
    for fn in (test_a3_bilder_werden_erfasst,
               test_a2_totes_laufwerk,
               test_a2_suchpfad_entfernt_nie,
               test_a2_gegenprobe_echte_karteileiche,
               test_a6_unlesbar_behaelt_index,
               test_a6_leere_datei_wird_entfernt,
               test_a1_freigabe_ohne_vollreindex,
               test_a5_gewicht_vor_dem_cut,
               test_a5_ohne_lernnotiz_unveraendert,
               test_a4_generationswechsel,
               test_b2_bm25_inkrementell,
               test_b2_bm25_ohne_lock_aufgebaut,
               test_d4_zielordner_der_gruppe,
               test_d6_aufraeumen_nur_uebernommene,
               test_d2_schema_default,
               test_a8_vector_store_neuversuch,
               test_b4_sammel_entfernung,
               test_quelltext):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(fn.__name__ + " (Ausnahme)", False, str(e))

    ok = sum(1 for _, c, _ in _results if c)
    print("\n" + "=" * 70)
    print(f"ERGEBNIS: {ok}/{len(_results)} Pruefungen bestanden")
    print("=" * 70)
    if ok != len(_results):
        for name, c, detail in _results:
            if not c:
                print(f"  FEHLGESCHLAGEN: {name} – {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
