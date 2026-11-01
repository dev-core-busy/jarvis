# Wissensgraph – Bericht Meilenstein 2 (Phase 1 + 2)

Stand: 2026-10-30 · Vorgänger: `docs/wissensgraph-phase0-messbericht.md` · Status:
**auf DEV gebaut und gemessen, auf ECHT nicht ausgerollt, nicht committet.**

Entscheidungen des Betreibers: Haus-Modell **ohne Denken**, erster Umfang **Confluence**,
**sigma 4** (Phase 4), Probedaten bleiben erhalten. Auf DEV liegt die Confluence-Ablage als
Kopie von ECHT (236 Seiten, `data/rag/confluence`, Wissensgruppe „Confluence").

---

## 1. Was gebaut ist

| Teil | Ort |
|---|---|
| Ablage, Datenmodell, Ableitung, Warteschlange, Negativ-Cache | `backend/wissensgraph.py` |
| Prompt, Schema-Prüfung, Normierung, Drossel, Arbeiter, Abgleich, Einstellungen | `backend/wissensgraph_extraktion.py` |
| Denken abschalten (`chat_template_kwargs.enable_thinking=false`) | `backend/llm.py` (`OpenAICompatibleProvider.denken_aus`) |
| Pflege-Hooks Entfernen/Umbenennen | `backend/tools/vector_store.py` (`_graph_melden`), dazu `chunks_fuer` |
| Vormerken im Indexlauf | `backend/tools/knowledge.py` (`_graph_einreihen`, `_graph_einreihen_abschliessen`) |
| Admin-API + Startup-Hook | `backend/main.py`: `/api/wissensgraph/{status,einstellungen,neuaufbau,abbrechen}` |
| Ablage 0750 | `backend/sandbox.py` (`PRIVATE_DIRS`) |

**Ablage** `data/graph/`: `quellen/<sha256>.json` je Quelldatei, `graph.json` (nur Cache,
jederzeit aus den Quellen ableitbar), `aliasse.json` (Admin-Entscheidungen, überstehen jeden
Neuaufbau), `queue.json`, `status.json`, `unlesbar.json`.

**Ablauf:** Indexlauf merkt vor → reiht am Laufende ein (nach der Gruppenzuordnung) → ein
asyncio-Arbeiter im Dienst-Loop holt die Chunks aus dem Index, schneidet den Importer-Kopf ab,
bildet Blöcke zu 1.500 Wörtern, ruft je Block Analyse und (bei Kandidaten) Normierung, prüft das
Schema und legt die Quelle ab. Kein Modellaufruf im Indexlauf oder in einem Request.

## 2. Abweichungen vom Plan (jeweils begründet)

| Plan | Gebaut | Grund |
|---|---|---|
| Schlüssel Pfad + mtime + **Größe** | Pfad + **Index-mtime** (+ Prüfsumme des Eingabetexts) | Eingabe sind die Chunks des Index, deren Identität dessen mtime ist; eine Größe bräuchte ein `stat` auf der Freigabe und sähe nichts zusätzlich. |
| Plural in der Namensnorm | keine Plural-Regel | Deutsche Mehrzahl ist per Regel nicht sicher („Status", „Prozess") – ein falsches Abschneiden führte zwei Dinge automatisch zusammen. Mehrzahl fängt der Normierungsschritt. |
| fail-closed je Block | 2. Versuch je Block; verworfen wird der Block, die Datei scheitert erst bei > 50 % | Bei 1–2 % Ausfall je Block würde eine Datei mit 450 Blöcken sonst nie fertig. |
| `graph.modell` | `profil` (Profil-ID) | Modelle werden in Jarvis über Profile gewählt; so gelten Schlüssel und Adresse des Profils. |
| Kosten in `status.json` | Token und Aufrufe | Das Haus-Modell hat keinen Preis; Kosten je Profil gibt es im System nicht. |
| zwei Gegenproben-Harnesse | einer (`gegen_wissensgraph.py`) | Gemeinsame Sicherung/Laufmarke/Basislauf; die Pflege- und Warteschlangen-Wächter hätten sonst keinen. |
| Relevanzmodell, Insights (Phase 1) | **noch nicht** | Gehören zu ihren Verwendern (Meilenstein 3/4); ohne Verwender wären sie ungeprüfte Zusagen. |
| Cron-Art `wissensgraph` | **nicht gebaut** | Der Arbeiter läuft ohnehin dauernd; inkrementell kommt alles über den Indexlauf. |

## 3. Befunde aus dem Bauen und Messen

1. **Rennen Indexlauf ↔ Arbeiter (eigener Fehler, vor dem ersten Live-Lauf gefunden).** Der
   Indexlauf ordnet neue Dateien erst am Ende ihrer Wissensgruppe zu. Hätte der Arbeiter eine
   eingereihte Datei vorher gesehen, wäre sie „außerhalb des Umfangs" ausgetragen worden – bis zum
   nächsten Neuaufbau nie extrahiert. Jetzt wird lokal vorgemerkt und erst nach der Zuordnung
   eingereiht; der Wächter prüft die Reihenfolge am AST, eine Gegenprobe beißt.
2. **Scheinknoten aus dem Importer-Kopf.** Jede Confluence-Seite beginnt mit einem Kopf, den der
   Jarvis-Abgleich schreibt (`> Quelle: Confluence · <Bereich> …`, `> Stand: Version …`). Im
   ersten Aufbau wurden „Confluence" (98 von 236 Quellen) und der Bereichsname (69) die größten
   Knoten – Verbindungen, die jede Seite mit jeder verknüpfen. Der Kopf wird jetzt vor der
   Extraktion entfernt (Muster gegen die festen Marken des Erzeugers, getestet mit Material aus
   `confluence_abgleich._inhalt`).
3. **Kantenart in mehreren Schreibweisen** (`gehört_zu`, `gehoert_zu`) – wird beim Ableiten
   vereinheitlicht, gilt damit auch für schon gespeicherte Quellen.
4. **Eine Messung falsch übertragen (eigener Fehler).** Die Schwelle 0,88 aus Messbericht 3.3
   galt dem *automatischen* Zusammenführen; ich hatte sie auf das *Angebot* an den
   Normierungsschritt gelegt. Gemessen (11 Dokumente × 3, je produktive Kette):

   | Prompt | Kandidaten ab | Namen-Jaccard | unscharf ≥ 0,90 | Kanten-Jaccard | „verdächtige" Namen | s/Aufruf |
   |---|---|---|---|---|---|---|
   | Phase 0 | 0,88 | 0,30 | 0,68 | 0,085 | 10,8 % | 4,5 |
   | mit Körnungsregeln | 0,88 | 0,26 | 0,61 | 0,066 | 9,1 % | 3,3 |
   | **Phase 0** | **0,5** | **0,42** | **0,78** | **0,11** | 11,7 % | 4,1 |
   | mit Körnungsregeln | 0,5 | 0,36 | 0,76 | 0,09 | 11,3 % | 3,1 |

   Vergleichswert: die Phase-0-Probe, unverändert wiederholt, 0,39 bzw. 0,42 – die Kennzahl
   streut also wenig, die Unterschiede sind echt. Querwert (Namen zwischen verschiedenen
   Dokumenten) in allen Läufen 0,013–0,022: das breitere Angebot führt nichts fälschlich zusammen.
   **Übernommen: Phase-0-Prompt, Kandidaten ab 0,5.** Die Körnungsregeln brachten keinen
   messbaren Gewinn und kosteten Stabilität.
5. **Eine falsche Sonde (eigener Fehler):** die erste Körnungs-Sonde meldete in allen Läufen
   ~60 % „verdächtig" – mit `re.I` traf das CamelCase-Muster jedes Wort. Korrigiert, mit
   Positiv- und Negativkontrolle (Exit 2 bei falscher Sonde).
6. **Einstellungen froren Vorgaben ein.** Gespeichert wurde das ganze Einstellungsobjekt – nach
   dem ersten Speichern stand jede Vorgabe fest in der `settings.json`, und die korrigierte
   Schwelle hätte DEV nie erreicht. Jetzt werden nur Abweichungen gespeichert.

## 4. Ergebnis auf DEV (Confluence, 236 Seiten)

| | erster Aufbau | Vollaufbau mit Kopf-Entfernung, Phase-0-Prompt, Schwelle 0,5 |
|---|---|---|
| Quellen / Fehlschläge | 236 / 0 | 236 / 0 (1 Block zweimal ungültig → Wiederholung gelang) |
| Aufrufe · Dauer | 512 · 18,5 min | 516 · 22 min |
| Token ein / aus | 452 k / 266 k | 417 k / 325 k |
| ungültiges JSON · verworfene Blöcke | 6 (1,2 %) · 0 | 8 (1,6 %) · 1 |
| Entitäten · davon in ≥ 2 Quellen | 1.222 · 409 | 1.810 · 560 |
| Kanten · mehrfach belegt | 2.634 · 43 | 3.069 · 11 |
| größter Knoten (Quellen) | Importer-Kopf „Confluence" (98) | ein inhaltlicher Knoten (18); „Confluence" nur noch 10, der Bereichsname nicht mehr unter den ersten 25; größter Grad 213 → 133 |

**Mehrfach belegte Kanten 43 → 11:** die meisten „Mehrfachbelege" des ersten Aufbaus stammten
aus dem Importer-Kopf (jede Seite belegte dieselben Kopf-Kanten). Was jetzt mehrfach belegt ist,
ist Inhalt. Mehr Entitäten als im ersten Aufbau, weil der Phase-0-Prompt nicht ausdünnt und das
breitere Kandidatenangebot nur gleichartige Namen zusammenführt.

Der Indexlauf für die 236 Seiten dauerte 165 s (718 Chunks, 0 Fehler); während des Laufs blieb
die Warteschlange leer, eingereiht wurde am Ende.

## 5. Prüfung

| Wächter | Prüfungen |
|---|---|
| `tests/test_wissensgraph_isolation.py` | 46 |
| `tests/test_wissensgraph_extraktion.py` | 53 |
| `tests/test_wissensgraph_pflege.py` | 32 |
| `tests/test_wissensgraph_warteschlange.py` | 24 |
| `tests/test_endpoint_rights.py` (erweitert) | 128 |
| **Gegenproben** `tests/gegen_wissensgraph.py` | **42 / 42 beißen**, Arbeitsbaum byte-gleich wiederhergestellt |
| **Live** `tests/live_wissensgraph_dev.py` (DEV) | 17 / 17 |

Unverändert grün (lokal und/oder DEV): `test_kommentare_deutsch`, `test_keine_echtwerte`,
`test_messung_zustand`, `test_trennen_index` (Prolog um `_graph_melden` ergänzt – die Methode
wird dort geschnitten), `test_rag_autoindex`, `test_reindex_mount`, `test_wissen_regression`,
`test_vector_journal`, `test_similar_drafts`, `test_search_anchor`, `test_vector_store_atomar`
sowie die übrigen 36 Wächter, die die geänderten Dateien berühren. Vier davon brauchen faiss und
laufen nur auf DEV; sieben brechen lokal auch auf `HEAD` ab (Umgebung) – verglichen in einem
Wegwerf-Arbeitsbaum.

**Live:** Nicht-Admins bekommen auf allen fünf Routen 403; ungültige Eingaben 400 ohne Wirkung;
jede Quelle liegt unter `data/rag/confluence` und im eingestellten Umfang; Ablage 0750.

## 6. Offen für die nächsten Meilensteine

- **Hubs:** auch ohne Importer-Kopf bleiben allgemeine Knoten (Hersteller, „Datenbank", „Linux")
  mit sehr hohem Grad. Für die 2-Hop-Expansion (Phase 3) braucht es eine Dämpfung nach Grad
  bzw. Quellenhäufigkeit – sonst verbindet ein Hub alles mit allem.
- **Kantenstabilität** bleibt gering (Jaccard ~0,1): Kanten tragen über ihr Gewicht (Zahl der
  belegenden Quellen), nicht über eine Einzelextraktion.
- **Personen:** der Graph enthält Vornamen und Namen aus den Dokumenten (Typ `person`). Er ist
  admin-only und 0750; ob Personen überhaupt Knoten sein sollen, ist eine Entscheidung für
  Phase 4.
- Gruppenzuordnung, die sich NACH dem Einreihen ändert, merkt der Graph erst beim nächsten
  Neuaufbau.
