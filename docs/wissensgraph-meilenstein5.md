# Wissensgraph – Bericht Meilenstein 5 (Entscheidung) und Phase 6

Stand: 2026-10-31 · Vorgänger: `docs/wissensgraph-meilenstein4.md` · Status:
**auf DEV gebaut, gemessen und eingeschaltet; auf ECHT nicht ausgerollt, nicht committet.**

Entscheidungen des Betreibers (2026-10-31): fragebezogenes Relevanzmodell bauen; Personen als
Knoten „evtl. später“; Phase 6 vollständig; überlappende Beschriftungen beheben; Echtinhalte
auf DEV behalten. Wiki-Seiten: eigene Ablage, **nicht** indexiert; erzeugt auf Abruf und im
Sammellauf.

## 1. Fragebezogenes Relevanzmodell (ersetzt das Modell aus Meilenstein 4)

Das Modell aus dem Plan (vier Signale Dokument zu Dokument, 2-Hop-Expansion) kannte die Frage
nicht und brachte bei Zusammenhangsfragen einen Verlust (Meilenstein 4). Neu:

- **Fragebegriffe:** Begriffe des Graphen, deren Name *vollständig* in der Frage steht – jedes
  Wort, Beugung toleriert („Rechnungsfreigaben“ → „Rechnungsfreigabe“, erst ab fünf
  Buchstaben), ohne Füllwörter, ohne Hubs (mehr als 20 % der Dokumente).
- **Score je Dokument:** Summe der Seltenheit `ln(1 + N/df)` der getroffenen Begriffe.
- **Ohne die vorläufig besten Dokumente:** sie erneut zu stärken, schob bei Ein-Dokument-Fragen
  den richtigen Treffer von Platz 1.
- **Kanalgewicht 0,5** in der RRF-Fusion (die drei Bestandskanäle zählen 1,0).
- **Filter in der Abfrage:** mit Wissensgruppen-Filter zählen nur erlaubte Dokumente – als
  Kandidat und in der Seltenheit.

Orte: `backend/wissensgraph.py` (`frage_begriffe`, `relevanz`), `backend/tools/vector_store.py`
(`GRAPH_GEWICHT`, Frage an `graph_rangliste`), `backend/tools/knowledge.py`.

### Messung (DEV, Confluence, 236 Dokumente, `tests/live_wissensgraph_recall_dev.py`)

Eingestellt an den Fragensätzen 11/22/33 (Gitter über Kanalgewicht 1,0/0,5/0,3, Dokumente
10/5/3, Chunks 2/1, mit/ohne Startdokumente, mit/ohne Schritt über Kanten), geprüft an den
**neuen** Sätzen 44/55/66, die das Modell vorher nicht gesehen hatte. Gesamt über sechs Sätze:

| | ohne Graph | mit Graph |
|---|---|---|
| Ein Dokument (6 × 30): Recall@1 | 0,822 | 0,817 |
| Recall@3 | 0,922 | 0,922 |
| Recall@5 | 0,928 | 0,933 |
| MRR | 0,869 | 0,867 |
| Zusammenhangsfragen (6 × 15): beide@3 | 0,411 | 0,444 |
| beide@5 | 0,533 | 0,578 |
| **beide@8** | **0,578** | **0,667** (in keinem Satz schlechter) |
| Dauer je Suche (Median) | 33 ms | 53 ms |

Einordnung, ehrlich:
- Der Gewinn kommt aus dem **Begriffsindex** des Graphen (Namen, Schreibweisen, Belege), nicht
  aus den Kanten: der Schritt zu Nachbarbegriffen (Gewicht 0,25 und 0,5) senkte das Ergebnis.
- Die Zusammenhangsfragen entstehen aus einem gemeinsamen seltenen Begriff; in 69–73 % der
  Fragen steht er wörtlich. Das begünstigt ein Modell, das Begriffe der Frage sucht – es ist
  aber auch die Lage, in der der Graph etwas beitragen *kann*.
- 15 Fragen je Satz: ein Unterschied von 0,067 sind eine Frage pro Satz. Die Richtung ist über
  sechs Sätze stabil, die Größe nicht genau.

**Entscheidung: Schalter `expansion` auf DEV eingeschaltet** (Vorgabe im Code bleibt AUS; auf
ECHT nicht angefasst).

## 2. Beschriftungen bei großen Knoten

Beim Überfahren eines Knotens mit vielen Nachbarn lagen alle Beschriftungen und alle Kantentexte
übereinander. Jetzt:
- Erzwungen beschriftet werden der Knoten selbst und **höchstens zwölf** Nachbarn – die am
  stärksten belegten, **deren Namen auf dem Bildschirm frei liegen** (`freiAuswaehlen`). Eine
  reine Höchstzahl reichte nicht: die Nachbarn eines großen Knotens liegen dicht beieinander, zwölf
  Namen überdeckten sich weiter (Chrome-Screenshot). Die übrigen Nachbarn bleiben hell, ihre
  Beschriftung setzt das Raster von sigma.
- Kantentexte nur an den **sechs** stärksten Kanten.
- Dasselbe beim Hervorheben vieler Knoten (Insel, Suche): die größten, frei liegenden.
- **Nebenbefund, seit Meilenstein 3 vorhanden:** im dunklen Thema war der Name des überfahrenen
  Knotens unsichtbar – sigma 4 legt einen fest weißen Kasten (`backdropColor`) darunter, die
  Schrift war hell. Der Kasten nimmt jetzt `--bg-secondary`.

## 3. Phase 6

### Widersprüche zwischen Quellen (`backend/wissensgraph_widerspruch.py`)
- Je Begriff mit zwei bis Hub-Grenze Quellen **ein** Aufruf: die Abschnitte (bis vier Quellen,
  je 900 Zeichen), die den Begriff nennen, nebeneinander; gemeldet werden nur Widersprüche in
  einer **Tatsache** (Wert, Zuständigkeit, Termin, Version, Vorgehen für denselben Fall).
- Jedes gemeldete Paar geht in **zwei weitere, unabhängige Aufrufe** (nur dieses Paar). Jeder
  muss die **gemeinsame Frage** nennen, die beide Abschnitte verschieden beantworten, und beide
  Antworten **wörtlich zitieren**; ein Zitat, das nicht im Abschnitt steht, verwirft den Befund.
  Gezeigt werden die Zitate (nachweislich im Dokument), nicht die Umschreibung des Modells.
- Jeder Abschnitt trägt seinen **Dokumentnamen** – ein Datum darin macht einen älteren Stand
  erkennbar (datierte Protokolle sind kein Widerspruch).
- Wie es dazu kam (DEV, echte Confluence-Daten):
  - Fassung 1 (eine Bestätigung, nur ja/nein): 239 Begriffe, 4 Befunde – einer echt (zwei
    Anleitungen nennen für denselben Port verschiedene Werte), mindestens zwei Fehlalarme
    (Abschnitte ohne gemeinsamen Gegenstand).
  - Fassung 2 (gemeinsame Frage, Zitate, zwei Bestätigungen): 121 Begriffe, 1 Befund – ein
    Fehlalarm aus zwei datierten Protokollen (geplante Änderung).
  - Fassung 3 (mit Dokumentnamen): **alle 560 Begriffe**, 7 Befunde. Drei brauchbar (derselbe
    Konfigurationswert mit zwei Ports; zwei Hostnamen für dasselbe System; Tabelle gegen
    empfohlene View), vier Fehlalarme – drei davon Paare aus **zwei datierten Protokollen**,
    trotz Dokumentnamen und Hinweis im Auftrag (einmal mit der eigenen Begründung „kein logischer
    Widerspruch“).
  - Fassung 4 (jetzt): eine **Regel** statt des Modells – zwei datierte Dokumente (Datum im
    Dateinamen) sind zwei Stände, kein Widerspruch; das Paar kostet keine Bestätigung. Auf den
    Bestand angewandt: 4 Befunde, davon 3 brauchbar, 1 Fehlalarm (zwei Gliederungen derselben
    Organisation).
  - Einordnung: die Prüfung findet wenig, und auch nach drei Schärfungen ist etwa jeder vierte
    Befund ein Fehlalarm. Sie ist ein **Hinweisgeber für einen Menschen**, keine Wahrheit – so
    steht sie auch auf der Seite (Karte mit „Recherche starten“, Ausblenden lernt mit).
  - Kosten auf DEV: ein Aufruf je Begriff, zwei mehr je gemeldetem Paar; 560 Begriffe in
    weniger als 45 Minuten neben dem Wiki-Sammellauf.

### Qualität der Wiki-Seiten (DEV, 560 Seiten, Stichprobe von drei)
Median 763 Zeichen und 4 Querverweise, 55 Seiten ohne Verweis, keine Fehlversuche. Die Seiten
fassen die Quellen sachlich zusammen; vereinzelt ergänzt das Modell **Allgemeinwissen**, das
nicht in den Quellen steht („ein proprietäres Betriebssystem“), oder formuliert eine knappe
Quelle schief um. Deshalb liegen die Seiten bewusst **außerhalb** der Wissenssuche.
- Ergebnis: Insight-Karte „Widerspruch“ mit beiden Aussagen und „Recherche starten“, Kante
  `widerspricht` zwischen den Dokumentknoten (eigene Farbe). Ein Befund gilt nur, solange beide
  Quellen unverändert sind; Umbenennen erhält ihn ohne Neuprüfung.

### Wiki-Seiten (`backend/wissensgraph_wiki.py`)
- Ablage `data/graph/wiki/*.md` + `index.json`, **nicht** im Wissensindex (kein Kreislauf, keine
  Konkurrenz zu den Originalquellen).
- Eingabe nur aus dem Graphen und den Quellen (Beschreibungen, Beziehungen, Abschnitte);
  Querverweise `[[Name]]` bleiben nur für verwandte Begriffe stehen.
- Auf Abruf im Detailbereich („Wiki-Seite erzeugen“ / „Neu erzeugen“, Kennzeichnung „veraltet“)
  und im Sammellauf für Begriffe mit mindestens zwei Quellen.

### Obsidian-Export
ZIP mit `Wissensgraph/Begriffe/*.md`, `Wissensgraph/Quellen/*.md`, `Übersicht.md`; Verweise
`[[Datei|Anzeige]]`, jede Zieldatei existiert (Wächter), Dateinamen ohne Zeichen, die Obsidian
oder Dateisysteme nicht vertragen, Namensgleichheit aufgelöst.

### Rückkopplung
Ausblenden einer Auffälligkeit wird beim Server gespeichert (für alle Admins, statt je Browser).
Ähnliche Vorschläge rücken nach hinten: Faktor `1 − 0,6 × Ähnlichkeit` (1 = teilt einen Begriff
mit einem verworfenen, 0,5 = gleiche Arten).

### Nachlauf und Schalter
Widerspruchsprüfung und Wiki-Sammellauf laufen im selben Arbeiter, nur bei **leerer**
Warteschlange, gedrosselt wie die Extraktion. „Abbrechen“ hält sie an, der nächste Aufbau setzt
fort. Neu auf der Seite: Schalter für Graph, Suche mit Graph, Widersprüche, Wiki-Sammellauf.

## 4. Prüfung

| Wächter | Prüfungen |
|---|---|
| `tests/test_wissensgraph_relevanz.py` (neu gefasst) | 43 |
| `tests/test_wissensgraph_phase6.py` (neu) | 88 |
| `tests/test_wissensgraph_ui.js` (+ Beschriftung, Phase 6) | 128 |
| `tests/test_endpoint_rights.py` (+ 7 Routen) | 141 |
| Gegenproben `tests/gegen_wissensgraph.py` | **117/117 beißen** |
| Live `tests/live_wissensgraph_dev.py` (+ Phase 6, Export) | 32 |
| Chrome-Abnahme `tests/live_wissensgraph_ui_dev.py` (+ Beschriftungsgrenze, Hover-Kasten, Wiki-Abschnitt) | 47 |

Eigene Prüfstand-Mängel dieser Runde (stumme Gegenproben):
- Eine Längenschranke in der Wortprüfung war doppelt; die tragende Bedingung lag eine Zeile
  tiefer. Die Schranke ist jetzt entfernt, die Probe richtet sich auf die tragende Bedingung.
- Der Export-Testbestand enthielt keinen Namen mit verbotenen Zeichen, die Prüfung war trivial
  wahr. Ein solcher Begriff ist ergänzt.
- Das Zurücksetzen eines abgelehnten Schalters geschah doppelt (direkt und über den Status). Die
  direkte Zeile ist entfernt, die Probe richtet sich auf den Status.

## 6. Rechte nach Wissensrollen (Festlegung des Betreibers 2026-10-31)

„Jeder Wissenseditor darf seins sehen, globale Wissenseditoren alles, normale Benutzer sehen die
Kachel gar nicht“ – mit der Einschränkung **„Admin allein darf kein Wissen editieren“**.

| | normaler Benutzer | Editor einer Wissensgruppe | globaler Wissenseditor | Admin ohne Editorrolle |
|---|---|---|---|---|
| Kachel | – | ja | ja | ja (nur Steuerung) |
| Grafik, Detail, Auffälligkeiten, Widersprüche | – | nur aus Dokumenten seiner Gruppen | alles | – |
| Wiki-Seite lesen/erzeugen | – | nur wenn **alle** Quellen des Begriffs in seinen Gruppen liegen | alles | – |
| Prüfliste, Zusammenführen, Trennen, Löschen, Export | – | – | ja | – |
| Schalter, Aufbau, Status | – | – | – | ja |

- **Dasselbe Prädikat wie die Wissen-Kachel** (`_editable_groups_for`), damit beide Kacheln nicht
  auseinanderlaufen; Fehler beim Ermitteln → kein Zugang.
- **Teilgraph statt Filter:** für einen Gruppen-Editor wird der Graph **aus seinen Dokumenten
  allein** abgeleitet (`wissensgraph.teilgraph`). Name, Art, Beschreibung, Kanten und
  Widerspruchskanten stammen damit nur aus erlaubten Quellen – ein Filter am fertigen Graphen hätte
  die Beschreibung aus einem fremden Dokument stehen lassen (sie ist die längste aller Quellen).
- **Pflege nur global:** ein Begriff gilt für den ganzen Graphen; ein Gruppen-Editor veränderte
  mit „Zusammenführen“ sonst fremde Gruppen mit.
- **Rückmeldungen je Benutzer** (vorher gemeinsam): das Ausblenden eines Editors stufte sonst
  Hinweise in fremden Gruppen zurück.
- Neue Routen-Schranken: `require_wissensgraph_leser` (Inhalte, im Endpunkt gefiltert),
  `require_knowledge_editor` (Pflege, Export), `require_local_auth` (Steuerung);
  `GET /api/wissensgraph/zugang` liefert der Seite nur die eigenen Rechte.

**Prüfung:** `tests/test_wissensgraph_rechte.py` (41 – Rechte-Matrix mit Attrappen der Prädikate
ausgeführt; Teilgraph am serialisierten Ergebnis: kein fremder Pfad, Begriff oder Text),
`test_wissensgraph_ui.js` (143 – Portal-Kachel am Recht, nicht an „ist Admin“; vier Sichten),
`test_endpoint_rights.py` (141), **live auf DEV** `tests/live_wissensgraph_rechte_dev.py` (28/28 –
echter Gruppen-Editor, echter Bestand: jede Quelle in Graph, Kanten, Detail und Widersprüchen
liegt in seiner Gruppe; fremde Gruppe im Filter 403; Pflege, Export, Steuerung 403; ohne Rolle
überall 403).

**Nicht live prüfbar auf DEV:** „Admin ohne Editorrolle“ – dort ist jeder Admin zugleich als
Wissenseditor eingetragen. Gemessen an der Rechte-Matrix und im jsdom-Prüfstand.
