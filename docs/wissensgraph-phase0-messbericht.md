# Wissensgraph – Messbericht Phase 0

Stand: 2026-10-30 · Plan: „Wissensgraph für das Jarvis-RAG“ (Vorlage llm_wiki) · Status:
**Phase 0 abgeschlossen, nichts gebaut** – Modell, Umfang und Grafik entschieden (Abschnitt 4).

**Server-Angaben:** Korpusgröße auf **ECHT** gemessen (nur lesend; der Index auf DEV ist
leer: 0 Dateien, 0 Chunks). Extraktionsprobe und Schwellen-Sonde auf **DEV**, Modell auf
dem Haus-Server (Profil „Qwen3.6-35B-A3B-FP8“). CSP-Probe lokal mit der Richtlinie aus
`backend/csp.py`.

---

## Ergebnis in fünf Sätzen

1. Die Grafik-Bibliotheken laufen unter `erzwingen` **ohne einen CSP-Verstoß**, der
   FA2-Worker startet per Blob-URL; sigma 4 verlangt aber **WebGL 2**.
2. Mit dem heutigen Aufrufweg (`reasoning_effort="low"`) ist das Haus-Modell **unbrauchbar**:
   es denkt trotzdem voll (≈ 6.500 Ausgabe-Token je Aufruf), läuft ans Längenlimit und
   liefert in **54 %** der Blöcke kein gültiges JSON.
3. Mit abgeschaltetem Denken (`chat_template_kwargs.enable_thinking=false`) liefert es in
   **98 %** gültiges JSON bei **4,0 s** je Aufruf – ein Volllauf von ECHT wären
   ≈ 10.900 Aufrufe ≈ **12 h** seriell.
4. Die Namensstabilität über Wiederholungen ist **mäßig** (Jaccard 0,39), die
   Kantenstabilität **gering** (0,09); der Graph muss Kanten über Mehrfachbelege
   gewichten, nicht über eine Einzelextraktion.
5. Der e5-Kosinus taugt **nicht** zum automatischen Zusammenführen (Fehlpaare noch bei
   ≥ 0,95), wohl aber zur Kandidatensuche ab **0,88**.

---

## 1. Korpus und Kostenformel (ECHT, lesend)

| Größe | Wert |
|---|---|
| Dateien im Index | 1.405 (PDF 1.041 · MD 252 · CSV 55 · DOCX 38 · XLSX 14 · OneNote 3 · sonst 2) |
| Chunks | 46.212 (Median 7 je Datei, p90 43, Maximum 3.375) |
| Wörter ohne Chunk-Überlappung | 7.285.803 |
| Blöcke bei 1.000 / **1.500** / 3.000 Wörtern | 8.093 / **5.711** / 3.374 |
| Blöcke je Wurzelordner (1.500) | 4.784 · 285 · 198 · 164 · 153 · 56 · 56 · 12 · 3 |

Der größte Wurzelordner trägt allein 84 % der Blöcke. Die Confluence-Ablage, ein
naheliegender erster Umfang, hat 285 Blöcke.

**Kostenformel** (gemessen, nicht geschätzt):

```
Aufrufe  = Σ_Dateien ⌈Wörter(Datei) / Blockgröße⌉ × a        a = 1,90 Aufrufe je Block
Dauer    = Aufrufe × t                                       t = 4,0 s (Denken aus) · 22,9 s (low)
Token    = Aufrufe × (1.598 Eingabe + 1.135 Ausgabe)         (Denken aus)
```

`a < 2`, weil der erste Block eines Laufs keine bekannten Namen hat und die Normierung
entfällt. Für ECHT bei 1.500 Wörtern:

| | Denken aus | Denken low (heutiger Weg) |
|---|---|---|
| Aufrufe | ≈ 10.850 | ≈ 10.850 |
| Dauer seriell | ≈ 12 h | ≈ 69 h, davon die Hälfte verworfen |
| Token | ≈ 17 Mio. ein + 12 Mio. aus | ≈ 22 Mio. ein + 70 Mio. aus |
| nur Confluence-Ablage (285 Blöcke) | ≈ 540 Aufrufe ≈ 36 min | ≈ 3,5 h |

Auf dem Haus-Server entstehen keine Tokenkosten, aber stundenlange Last. Die geplante
Ratenbegrenzung (`graph.rate_*`) ist deshalb Pflicht, nicht Kür.

## 2. CSP-Machbarkeit

**Bundles** (einmalig mit esbuild 0.28.2 gebaut, `--bundle --minify --format=iife
--target=es2019 --legal-comments=eof`, nicht ins Repo übernommen – das ist Phase 4):

| Datei | Paket (Lizenz) | Global | Bytes | SHA-256 |
|---|---|---|---|---|
| `sigma.min.js` | sigma 4.0.4 (MIT) | `JarvisSigma` | 437.442 | `4920b885…238f0736a` |
| `graphology.min.js` | graphology 0.26.0 (MIT) | `JarvisGraphology` | 67.965 | `f2032c6e…7608c4a3` |
| `graphology-fa2.min.js` | graphology-layout-forceatlas2 0.10.1 (MIT) | `JarvisFA2` | 19.004 | `9c3036d1…dc400dbe` |
| `graphology-louvain.min.js` | graphology-communities-louvain 2.0.2 (MIT) | `JarvisLouvain` | 24.674 | `29be7328…74970863` |

Einstiegsdateien: sigma (`Sigma`, `sigma/rendering`, `sigma/utils`), graphology (`Graph`
und Varianten), FA2 (`forceAtlas2` + `graphology-layout-forceatlas2/worker`), Louvain.
sigma ist gzip-komprimiert 115 KB groß.

**Messung** – Probeseite mit 400 Knoten / ≈ 1.190 Kanten, Louvain, FA2 synchron, FA2-Worker,
sigma-Rendering; Zähler am `securitypolicyviolation`-Ereignis und am `report-uri`:

| Lauf | Verstöße | Berichte | Ergebnis |
|---|---|---|---|
| `erzwingen` (Headless-Chrome, SwiftShader) | 0 | 0 | sigma rendert 400 Knoten (Screenshot geprüft), Louvain 12–14 Communities |
| `melden` (Report-Only) | 0 | **0** | wie oben |
| **Gegenprobe** `eval` + `new Function` unter `erzwingen` | **2** | **2** | beide blockiert – die Messung beißt |
| FA2-Worker in Echtzeit (eingebauter Browser) | 0 | – | 863 Worker-Nachrichten, Knoten bewegen sich |

Statisch enthält keines der Pakete `eval` oder `new Function`. Der Worker entsteht über
`Blob` + `URL.createObjectURL` und ist damit von `worker-src 'self' blob:` gedeckt.

**Zwei Befunde für Phase 4:**
- **sigma 4 verweigert den Start ohne WebGL 2** („WebGL 2 is not supported by your
  browser“). Im eingebauten Browser der Desktop-App fehlte WebGL ganz. Die Seite braucht
  deshalb eine klare Meldung statt einer leeren Fläche; ein Umstieg auf sigma 3 hilft
  nur gegen fehlendes WebGL 2, nicht gegen fehlendes WebGL.
- Im Headless-Modus steht der Worker unter `--virtual-time-budget` still (0 Nachrichten).
  Ein Screenshot-Test des Layouts in Phase 5 muss in Echtzeit laufen, sonst prüft er ein
  Layout, das nie gerechnet wurde.

## 3. Extraktionsprobe (DEV)

**Aufbau:** 11 Dokumente aus ECHT (5 PDF, 2 DOCX, 1 OneNote, 2 Confluence, 1 XLSX;
97 Chunks), als bereits extrahierter Chunk-Text übernommen – kein zweiter OCR-/Tika-Lauf,
wie in Phase 2 vorgesehen. Text aus Chunks ohne die 40-Wort-Überlappung rekonstruiert,
Blöcke zu 1.500 Wörtern (16 Blöcke je Durchlauf). Zwei Schritte je Block: Analyse →
Normierung gegen die Top-25 bekannten Namen (e5). `tools=[]`, Dokumenttext durch
`fremdtext.entschaerfen`, Markerblock mit Zufallsmarke je Aufruf. Ungültiges JSON wird
verworfen, nicht repariert; Schema-Prüfung je Entität/Relation. Drei Wiederholungen je
Variante, `temperature: auto`. Positivkontrolle vor dem Lauf (Abbruch mit Exit 2).

### 3.1 Denk-Anteil (Ursache des ersten Fehlschlags)

Der erste Lauf verwarf beide Blöcke des ersten Dokuments. Ursache laut Abbruchgrund:
`laengenlimit` bei 8.192 Ausgabe-Token, sichtbar waren nur ≈ 3.200 Zeichen. Direktvergleich
mit demselben Block:

| Variante | Dauer | Ausgabe-Token | Denk-Zeichen | gültiges JSON |
|---|---|---|---|---|
| `reasoning_effort="low"` | 28–30 s | 7.615–8.192 | 21.000–28.000 | 1 von 4 |
| `enable_thinking=false` | 2–7 s | 396–2.177 | 0 | 4 von 4 |

Der Haus-Server **übergeht** `reasoning_effort`. Der Provider kennt
`chat_template_kwargs` heute nicht; die Probe ruft für diese Variante deshalb direkt auf.

### 3.2 Hauptmessung (3 Wiederholungen je Variante)

| Kennzahl | Denken aus | Denken low |
|---|---|---|
| Laufzeit gesamt | 384 s | 1.550 s |
| Aufrufe | 91 | 67 |
| s je Aufruf | **4,0** | 22,9 |
| Token je Aufruf (ein / aus) | 1.598 / 1.135 | 1.994 / 6.459 |
| gültiges JSON | 89 / 91 (**98 %**) | 41 / 67 (61 %) |
| verworfene Blöcke | 2 / 48 (4 %) | **26 / 48 (54 %)** |
| Entitäten je Dokument (Spanne) | 12–133 | 0–28 |
| verworfene Einzelteile (Schema) | 399 | 5 |
| Jaccard Namen (gefüllte Paare) | Mittel **0,39**, Median 0,39, n = 33 | Mittel 0,38, n = 10 (23 Paare mit leerer Seite) |
| Jaccard Kanten | Mittel **0,09** | nicht deutbar |
| Jaccard Namen **zwischen verschiedenen Dokumenten** | 0,014 | – |

Je Dokument (Denken aus) schwankt die Namensstabilität zwischen 0,15 und 0,70.
Kurze, sachlich dichte Dokumente (Confluence-Entwurf, Berechtigungskonzept) liegen bei
0,5–0,7, die Tabelle (XLSX) bei 0,14–0,18. Dort schwankt auch die Menge am stärksten:
133 / 42 / 57 Entitäten.

**Sonde der Sonde:** Der Querwert zwischen verschiedenen Dokumenten (0,014) liegt weit
unter dem Wiederholungswert (0,39), die Kennzahl misst also Stabilität und nicht
Zufall. **Korrigiert:** Die erste Auswertung zählte zwei *leere* Ergebnisse als
Jaccard 1,0 und ein einseitig leeres als 0,0. Bei „low“ mischte sie so Ausfälle in die
Stabilität (Mittel 0,27, Median 0,0), und die Zahl war nicht deutbar. Ausgewertet werden
nur noch gefüllte Paare, die Ausfälle stehen getrennt in der Zeile „verworfene Blöcke“.

**Was verworfen wurde (Denken aus):** in der Stichprobe zu ⅔ Relationen, deren `von`/`nach`
nicht in der eigenen Entitätsliste stehen, und zu ⅓ Entitäten mit einem Typ außerhalb der
Liste. Inhaltlich fällt eine zu feine Körnung auf: Schaltflächen, Kontrollkästchen,
Programmparameter und Menüpunkte werden zu Entitäten. Der Prompt muss in Phase 2 die
Körnung festlegen. Die Reparatur bleibt trotzdem verboten, verworfen wird weiterhin.

### 3.3 Schwelle für die Entitätsauflösung (e5, DEV)

Anteil der Namen einer Wiederholung mit einem Partner ≥ Schwelle, und zwar *innen* (andere
Wiederholung, gleiches Dokument) bzw. *quer* (anderes Dokument). Der Querwert ist eine
Obergrenze für Fehlzusammenführungen, denn echte gemeinsame Entitäten zählen mit.

| Schwelle | 0,80 | 0,85 | **0,88** | 0,90 | 0,92 | 0,94 | 0,96 |
|---|---|---|---|---|---|---|---|
| innen | 1,000 | 0,965 | **0,833** | 0,772 | 0,708 | 0,628 | 0,585 |
| quer | 0,999 | 0,641 | **0,170** | 0,093 | 0,070 | 0,046 | 0,033 |

Die Stichprobe der Paare je Band entscheidet die Frage, die Tabelle allein nicht:
- **≥ 0,95 enthält noch Fehlpaare:** „gültig ab“ ~ „gültig bis“ (0,956), zwei
  Programmnummern mit verschiedenen Endziffern (0,957), dieselbe Konfigurationsdatei als
  `.ini` und `.txt` (0,949), ein Parameter und sein Schalter „…Verwenden“ (0,970).
- **0,88–0,94** mischt echte Varianten (Abkürzung, Klammerzusatz, Präfix „Modul“) mit
  bloßen Wortfeld-Nachbarn („Schaltfläche Löschen“ ~ „Schaltfläche Speichern“, 0,931).
- **< 0,88** ist überwiegend Rauschen.

**Empfehlung:** Automatisch zusammengeführt wird nur bei **gleicher Normform** des Namens
(und nach Admin-Entscheidungen in `aliasse.json`). Der e5-Kosinus dient nur der
**Kandidatensuche ab 0,88**, für den Normierungsschritt des Modells und für die Prüfliste.
Die Schwelle bleibt wie geplant einstellbar.

> **Korrektur in Meilenstein 2:** Die 0,88 gilt nur dort, wo ohne Modell entschieden würde. Für das
> *Angebot* an den Normierungsschritt (dort entscheidet das Modell, und es darf nur auf angebotene
> Namen abbilden) ist sie zu streng: mit 0,88 fiel die Namensstabilität der produktiven Kette auf
> 0,30, mit 0,5 lag sie bei 0,42 – bei unverändertem Querwert. Vorgabe ist jetzt 0,5
> (`docs/wissensgraph-meilenstein2.md`, Abschnitt 3).

## 4. Entscheidungen

**Entschieden vom Betreiber (2026-10-30):**
- **Modell:** Haus-Modell **ohne Denken** (`enable_thinking=false`).
- **Erster Umfang:** die **Confluence-Ablage**.
- **Grafik:** **sigma 4**, ohne WebGL 2 erscheint eine klare Meldung.
- **Probedaten:** Die Kopien bleiben erhalten, auf DEV unter `data/graph_probe/` und lokal,
  für die Wiederholungsmessung nach der Prompt-Überarbeitung.

Die Empfehlungen, auf denen die Entscheidungen beruhen:

| # | Frage | Empfehlung aus der Messung |
|---|---|---|
| 1 | Extraktionsmodell | Haus-Modell **mit abgeschaltetem Denken**. Dafür muss der OpenAI-kompatible Provider `chat_template_kwargs` je Aufruf durchreichen (Phase 2, `backend/llm.py`). Mit dem heutigen Weg ist das Modell für diese Aufgabe nicht geeignet. Ein Vergleich mit Gemini Flash steht aus (nicht gemessen, nach Tokenpreis ≈ 17 Mio. ein + 12 Mio. aus für einen Volllauf). |
| 2 | Umfang | Mit **einer Gruppe** beginnen. Die Confluence-Ablage (285 Blöcke ≈ 36 min) ist groß genug für Zusammenhänge und klein genug für schnelle Wiederholungen. Den größten Wurzelordner (84 % der Last) erst nach der Recall-Messung angehen. |
| 3 | Prompt | Körnung festlegen (keine Oberflächenelemente oder Einzelparameter als Entität). Typ-Liste im Prompt erzwingen. Relationen nur zwischen gelisteten Namen. Messung danach wiederholen (gleiche Probe, `PROBE_DENKEN=aus`). |
| 4 | Kanten | Wegen der Kantenstabilität von 0,09 trägt eine Einzelextraktion keine Kante. Gewicht über die Zahl der Belege und Quellen. Das Relevanzmodell (Quellen-Überlappung ×4,0) ist dafür ohnehin robuster als die Kantenart. |
| 5 | Grafik | sigma 4 behalten, ohne WebGL 2 eine klare Meldung zeigen. Screenshot-Test in Echtzeit. |

Die offenen Punkte 3–5 des Plans (Sichtbarkeit für Admins, Wiki-Seiten, Standard für die
Graph-Expansion) berührt Phase 0 nicht.

## 5. Nachvollziehen

Probe-Skripte (nicht im Repo, auf DEV unter `data/graph_probe/`): `probe.py` (Varianten über
`PROBE_DENKEN=aus|low`, `PROBE_WDH`, `PROBE_BLOCK_WOERTER`), `denk_vergleich.py`,
`schwelle.py`. Aufruf als root auf DEV:

```
bash /opt/jarvis/deploy/als_dienst.sh -E PROBE_DENKEN=aus /opt/jarvis/venv/bin/python /opt/jarvis/data/graph_probe/probe.py
```

Der Probekorpus besteht aus Echtdaten von ECHT. Er liegt deshalb nur auf DEV, in
`data/graph_probe/`, Modus 0700, außerhalb von `data/rag`. Der DEV-Index bleibt dadurch
unberührt.
