#!/usr/bin/env python3
"""Wissensgruppen-Filter: Einschraenkung IN der Suche statt Nachfilter.

Der behobene Fehler: die Suche holte das Fuenffache und filterte danach nach
Gruppen. Liegt der beste Treffer einer kleinen Gruppe jenseits der global besten
5·k, fiel er still heraus – der Benutzer bekam "keine Treffer", obwohl passendes
Wissen in seiner Gruppe lag.

Der Test baut genau diese Lage nach: viele Chunks zu einem Thema in Gruppe A,
EIN passender Chunk in Gruppe B, und sucht als B-Benutzer.

    python3 tests/test_kb_group_filter.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ok = _fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))


def section(t: str) -> None:
    print("\n" + t)


try:
    from backend.tools import vector_store as vs_mod
except Exception as e:  # noqa: BLE001
    print(f"ÜBERSPRUNGEN – vector_store nicht importierbar: {e}")
    sys.exit(0)

try:
    vs_mod._get_embedding_model()
except Exception as e:  # noqa: BLE001
    print(f"ÜBERSPRUNGEN – Embedding-Modell nicht ladbar: {e}")
    sys.exit(0)


# ── Bestand aufbauen ────────────────────────────────────────────────────────
# 60 Chunks "Drucker" in Gruppe A, 1 Chunk "Drucker" in Gruppe B.
# max_results = 8 -> die alte Ueber-Abfrage holte max(8*5, 40) = 40 Treffer.
# Der B-Chunft muss dahinter landen koennen; deshalb sind die A-Chunks
# thematisch naeher an der Anfrage formuliert.
LAUT = ("Drucker einrichten: Treiber installieren, Warteschlange leeren, "
        "Netzwerkdrucker verbinden, Papierstau beheben, Toner wechseln.")
LEISE = ("Etikettendrucker Zebra ZD421 im Labor: Kalibrierung der Etiketten "
         "und Anschluss ueber USB.")

with tempfile.TemporaryDirectory() as tmp:
    store = vs_mod.VectorStore(Path(tmp))
    for i in range(60):
        store.add_chunks(f"/kb/a/drucker_{i:02d}.md", [f"{LAUT} Variante {i}."],
                         mtime=1.0, save=False)
    store.add_chunks("/kb/b/etikettendrucker.md", [LEISE], mtime=1.0, save=False)
    store.save()

    ERLAUBT = {"/kb/b/etikettendrucker.md"}
    K = 8

    section("Bestand")
    check("61 Chunks indiziert", store.chunk_count() == 61, str(store.chunk_count()))

    # Anfragen, bei denen die 60 lauten Chunks das Feld beherrschen. Der leise
    # Chunk ist thematisch verwandt, aber schwaecher – genau die Lage, in der
    # der alte Weg ihn verliert. Nicht geraten: auf DEV nachgemessen, er steht
    # bei diesen drei Anfragen NICHT unter den ueber-abgefragten 40.
    section("Der behobene Fehler: Treffer jenseits der Ueber-Abfrage")
    verloren = 0
    for frage in ("Drucker einrichten",
                  "Wie richte ich einen Drucker ein?",
                  "Drucker Problem beheben"):
        alt_roh = store.search_hybrid(frage, max(K * 5, 40))
        alt = [r for r in alt_roh if r[1] in ERLAUBT]          # = Nachfilter
        neu = store.search_hybrid(frage, K, allow_paths=ERLAUBT)
        if not alt:
            verloren += 1
        check(f"{frage!r}: neuer Weg findet den Gruppentreffer",
              len(neu) == 1 and neu[0][1] == "/kb/b/etikettendrucker.md",
              f"alt={len(alt)} von {len(alt_roh)} · neu={[r[1] for r in neu]}")
    check("alter Weg verliert den Treffer bei mindestens zwei Anfragen",
          verloren >= 2, f"nur {verloren} von 3 – Bestand zu klein fuer den Nachweis")

    section("Eigenschaften der gefilterten Suche")
    FRAGE = "Wie kalibriere ich den Zebra ZD421 Etikettendrucker?"
    neu = store.search_hybrid(FRAGE, K, allow_paths=ERLAUBT)
    check("liefert AUSSCHLIESSLICH erlaubte Pfade",
          bool(neu) and all(r[1] in ERLAUBT for r in neu),
          str(sorted({r[1] for r in neu} - ERLAUBT)))
    check("Top-Score ist auf 1.0 normiert (wie ohne Filter)",
          bool(neu) and abs(neu[0][0] - 1.0) < 1e-6, str(neu[0][0] if neu else None))
    check("ohne Filter steht derselbe Chunk auch drin",
          any(r[1] in ERLAUBT for r in store.search_hybrid(FRAGE, K)))

    section("Randfaelle")
    check("leere Erlaubnis liefert nichts",
          store.search_hybrid(FRAGE, K, allow_paths=set()) == [])
    check("allow_paths=None sucht wie bisher ueber alles",
          len(store.search_hybrid(FRAGE, K)) > 0)
    check("unbekannter Pfad in der Erlaubnis liefert nichts",
          store.search_hybrid(FRAGE, K, allow_paths={"/kb/gibtsnicht.md"}) == [])
    gemischt = store.search_hybrid(FRAGE, K,
                                   allow_paths=ERLAUBT | {"/kb/a/drucker_00.md"})
    check("zwei erlaubte Pfade: beide moeglich, nichts Fremdes",
          all(r[1] in (ERLAUBT | {"/kb/a/drucker_00.md"}) for r in gemischt)
          and len(gemischt) >= 1,
          str([r[1] for r in gemischt]))

    section("Beide Kanaele filtern (nicht nur der semantische)")
    nur_lex = store._search_lexical_idx("Zebra ZD421 Kalibrierung", 50)
    with_lex = store._search_lexical_idx(
        "Zebra ZD421 Kalibrierung", 50,
        allowed={i for i, m in enumerate(store._meta) if m["file_path"] in ERLAUBT})
    check("BM25 ungefiltert findet etwas", len(nur_lex) >= 1, str(len(nur_lex)))
    check("BM25 gefiltert bleibt in der Erlaubnis",
          all(store._meta[i]["file_path"] in ERLAUBT for i, _ in with_lex),
          str([store._meta[i]["file_path"] for i, _ in with_lex]))

    erl_idx = {i for i, m in enumerate(store._meta) if m["file_path"] in ERLAUBT}
    vek = store._search_vector_idx("Drucker", 50, allowed=erl_idx)
    check("FAISS-IDSelector begrenzt den semantischen Kanal",
          all(i in erl_idx for i, _ in vek) and len(vek) <= len(erl_idx),
          str([store._meta[i]["file_path"] for i, _ in vek]))
    check("... und liefert ohne Filter mehr", len(store._search_vector_idx("Drucker", 50)) > len(vek))

section("search_hybrid_ex: Anker ohne zweiten BM25-Durchlauf")
with tempfile.TemporaryDirectory() as tmp:
    st = vs_mod.VectorStore(Path(tmp))
    st.add_chunks("/kb/a.md", ["Zwei-Faktor-Authentifizierung mit Authenticator einrichten"],
                  mtime=1.0, save=False)
    st.add_chunks("/kb/b.md", ["Urlaubsantrag beim Vorgesetzten stellen"], mtime=1.0)
    tr, anker = st.search_hybrid_ex("Zwei-Faktor einrichten", 5)
    check("Treffer wie gehabt", len(tr) >= 1)
    check("mit Anker: ohne_anker=False", anker is False, str(anker))
    tr2, anker2 = st.search_hybrid_ex("qqqq wwww eeee", 5)
    check("ohne Anker: ohne_anker=True", anker2 is True, str(anker2))
    check("deckt sich mit has_lexical_anchor()",
          (st.has_lexical_anchor("Zwei-Faktor einrichten") is False) is (anker is True)
          and (st.has_lexical_anchor("qqqq wwww eeee") is False) is (anker2 is True))
    check("search_hybrid liefert weiterhin nur die Liste",
          isinstance(st.search_hybrid("Zwei-Faktor einrichten", 5), list))

section("save=False wird auch auf dem Aenderungs-Pfad beachtet")
with tempfile.TemporaryDirectory() as tmp:
    st = vs_mod.VectorStore(Path(tmp))
    st.add_chunks("/kb/x.md", ["Erster Inhalt zum Thema Drucker"], mtime=1.0, save=True)
    idx = Path(tmp) / "faiss_index.bin"
    vorher = idx.stat().st_mtime_ns
    # Dieselbe Datei erneut -> Aenderungs-Pfad (has_existing) mit save=False
    st.add_chunks("/kb/x.md", ["Geaenderter Inhalt zum Thema Drucker"], mtime=2.0, save=False)
    check("save=False schreibt NICHT (der eigentliche Fehler)",
          idx.stat().st_mtime_ns == vorher, "Index wurde trotzdem geschrieben")
    check("der Index im Speicher ist trotzdem aktuell",
          any("Geaenderter" in m["text"] for m in st._meta))
    st.save()
    check("save() schreibt dann doch", idx.stat().st_mtime_ns != vorher)
    # Und save=True verhaelt sich unveraendert
    vorher2 = idx.stat().st_mtime_ns
    st.add_chunks("/kb/x.md", ["Nochmals geaendert"], mtime=3.0, save=True)
    check("save=True schreibt weiterhin sofort", idx.stat().st_mtime_ns != vorher2)

section("Thread-Zahl: zwei Kerne bleiben frei")
import os as _os
try:
    import torch as _torch
    vs_mod._get_embedding_model()
    erwartet = max(1, min((_os.cpu_count() or 4) - 2, 8))
    check(f"torch nutzt {erwartet} Threads bei {_os.cpu_count()} Kernen",
          _torch.get_num_threads() == erwartet, str(_torch.get_num_threads()))
except Exception as e:  # noqa: BLE001
    check("Thread-Zahl pruefbar", False, str(e))

section("Quelltext: keine Ueber-Abfrage mehr auf dem Vektor-Weg")
kb = (Path(__file__).resolve().parent.parent / "backend" / "tools" / "knowledge.py").read_text(encoding="utf-8")
check("KnowledgeTool reicht allow_paths in die Suche",
      "_vector_search, query, n, allow_paths" in kb)
check("rag_search reicht allow_paths in die Suche",
      kb.count("allow_paths=allow_paths") >= 1
      and "gruppen_in_suche = allow_paths is not None" in kb)
check("Nachfilter nur noch als Rueckfall",
      kb.count("not gruppen_in_suche") == 2, str(kb.count("not gruppen_in_suche")))
# Die Ueber-Abfrage darf es noch geben – aber nur fuer TF-IDF.
check("Ueber-Abfrage steht nur noch im TF-IDF-Zweig",
      "n = max_results if allow_paths is not None else fetch_n" in kb)

print(f"\n{'═' * 46}\nErgebnis: {_ok}/{_ok + _fail} bestanden")
sys.exit(0 if _fail == 0 else 1)
