# Wissensgraph – Bericht Meilenstein 4 (Phase 3: graph-erweiterte Suche)

Stand: 2026-10-30 · Vorgänger: `docs/wissensgraph-meilenstein3.md` · Status:
**auf DEV gebaut und gemessen, Schalter AUS (Vorgabe), auf ECHT nicht ausgerollt, nicht committet.**

## 1. Was gebaut ist

| Teil | Ort |
|---|---|
| Relevanzmodell: Startbegriffe → 2-Hop-Expansion (Abklingen 1,0 / 0,5) → vier Signale (Überlappung ×4, direkte/erreichte Verbindung ×3, Adamic-Adar ×1,5, Typ-Affinität ×1), Hub-Dämpfung | `backend/wissensgraph.py` (`relevanz`) |
| Vierter RRF-Kanal: verwandte Dokumente der vorläufig besten fünf, ihre semantisch besten Chunks (max. 2 je Dokument) gehen in **dieselbe** Fusion; Score-Semantik, `MIN_SCORE`, `RELATIVE_CUT`, `MIN_KEEP` unverändert | `backend/tools/vector_store.py` (`_graph_kanal`, Parameter `graph_rangliste`) |
| Block „Zusammenhänge" in `knowledge_search` (`X ↔ Y (Art, über Dokument Z)`, gedeckelt auf ein Drittel eines Treffers) | `backend/tools/knowledge.py`, `backend/wissensgraph.py` (`zusammenhaenge`) |
| Schalter `expansion` in den Graph-Einstellungen, **Vorgabe AUS** (aus = byte-gleicher Suchdurchgang) | `backend/wissensgraph_extraktion.py` |

**Filter in der Abfrage:** Mit Wissensgruppen-Filter zählen nur erlaubte Dokumente – als
Kandidat, als Beleg eines Begriffs **und als Beleg einer Kante**. Eine Beziehung, die nur ein
fremdes Dokument kennt, trägt die Expansion nicht, auch nicht als Zwischenschritt (Wächter +
Gegenprobe „Filter entfernen → FAIL").

**Nicht gebaut:** das optionale Werkzeug `knowledge_graph(entitaet)` – ohne messbaren Nutzen der
Erweiterung wäre es ein weiterer Weg ins Modell ohne Beleg.

## 2. Messung (DEV, Confluence, 236 Dokumente)

Fragen formuliert das Haus-Modell aus einem Abschnitt, ohne Titel/Dateinamen. Die Suche ist
deterministisch (geprüft: derselbe Satz zweimal, gleiche Treffer) – die drei Wiederholungen sind
drei unabhängig gezogene Fragensätze. `tests/live_wissensgraph_recall_dev.py`.

**Ein Zieldokument je Frage** (3 × 30):

| | ohne Graph | mit Graph |
|---|---|---|
| Recall@1 | 0,778 | 0,778 |
| Recall@3 | 0,878 | 0,878 |
| Recall@5 | 0,878 | 0,889 |
| Recall@8 | 0,889 | 0,889 |
| MRR | 0,824 | 0,823 |
| Dauer je Suche (Median) | 36–38 ms | 57–59 ms |

**Zusammenhangsfragen** – zwei Dokumente teilen einen seltenen Begriff (2–4 Dokumente), die Frage
braucht beide (3 × 15):

| beide Dokumente unter den ersten k | ohne | mit |
|---|---|---|
| k = 3 | 0,444 | 0,400 |
| k = 5 | 0,533 | 0,489 |
| k = 8 | 0,600 | 0,534 |

**Ergebnis: kein Gewinn, bei Zusammenhangsfragen ein leichter Verlust, +21 ms je Suche.**

**Ursache, gemessen:** In 18 Fällen fehlte genau eines der beiden Dokumente. Der Graph
*erreicht* es in allen 18 – ordnet es aber im Median auf Rang 42 von rund 200 ein; nur 2 kommen
unter die ersten 10, die in den Kanal gehen. Eine strengere Hub-Grenze ändert daran fast nichts
(20 %: 2/18, 3 %: 3/18 unter den ersten 10). Das Modell bewertet Verwandtschaft **Dokument zu
Dokument** ausgehend von fünf gemischten Startdokumenten und kennt **die Frage nicht**; die
reine Überlappung belohnt Dokumente mit vielen allgemeinen gemeinsamen Begriffen. Für
Seitennavigation (llm_wiki) passt das, als Suchkanal nicht.

## 3. Entscheidung (Meilenstein 5 des Plans)

- **Schalter bleibt AUS.** Der Plan sagt „einschalten erst nach Messung"; die Messung zeigt
  keinen Gewinn.
- Ein fragebezogenes Modell (z. B. Startbegriffe = Begriffe, die in der Frage oder im besten
  Treffer vorkommen; Überlappung nach Seltenheit gewichtet) wäre ein Umbau über den Plan hinaus –
  **offen, zur Entscheidung des Betreibers.** Messaufbau und Fragensätze liegen bereit; eine neue
  Fassung ist in Minuten gegen dieselben Fragen gemessen.
- Die Graph-Ansicht (Meilenstein 3) ist davon unabhängig nutzbar.

## 4. Prüfung

| Wächter | Prüfungen |
|---|---|
| `tests/test_wissensgraph_relevanz.py` (neu) | 36 |
| Gegenproben `tests/gegen_wissensgraph.py` (jetzt einschließlich Relevanz und Kanal) | siehe Abschluss |
| Bestand auf DEV (faiss): `test_vector_journal`, `test_search_anchor`, `test_vector_store_atomar`, `test_similar_drafts`, `test_trennen_index`, `test_rag_autoindex`, `test_wissen_regression` | alle grün |

Eigene Prüfstand-Mängel dieser Runde, von Gegenproben gefunden: ein Sollwert, der aus dem
sabotierten Modul selbst gerechnet wurde (passte sich jeder Änderung an); ein Testfall, der die
Lage „Kante nur durch fremdes Dokument belegt" gar nicht herstellte; eine Prüfung, die bei einer
Ausnahme abstürzte statt fehlzuschlagen; und eine Determinismus-Sonde, die die Laufzeit
mitverglich.
