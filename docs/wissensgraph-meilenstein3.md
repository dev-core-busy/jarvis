# Wissensgraph – Bericht Meilenstein 3 (Phase 4: Admin-Kachel)

Stand: 2026-10-30 · Vorgänger: `docs/wissensgraph-meilenstein2.md` · Status:
**auf DEV gebaut und im echten Chrome abgenommen, auf ECHT nicht ausgerollt, nicht committet.**

## 1. Was gebaut ist

| Teil | Ort |
|---|---|
| Kachel „Wissensgraph" (nur Admins, eingeblendet über `/api/me`) | `frontend/portal.html`, `frontend/js/portal_seite.js` |
| Seite `/wissensgraph` (leere Hülle; Daten nur hinter `require_local_auth`) | `frontend/wissensgraph.html`, `frontend/js/wissensgraph.js`, `frontend/css/wissensgraph.css` |
| Grafik: sigma 4 (WebGL 2), graphology, ForceAtlas2 im Worker, Louvain | `frontend/js/vendor/*.min.js`, Herkunft und Lizenzen in `HERKUNFT.txt` |
| Farbvariablen `--graph-c1…c12`, `--graph-kante-stark/-schwach`, `--graph-gedimmt` (hell und dunkel) | `frontend/css/theme.css` |
| API: Graph (gefiltert, paginiert), Knoten-Detail, Prüfliste, Zusammenführen, Trennen, Entfernen | `backend/wissensgraph.py`, `backend/main.py` |
| Seitenrahmen als Ausnahme der Deny-by-default-Regel (BSI M10) | `backend/zugang_regel.py` |
| „Recherche starten" → Auftrag als Vorlage im Chat-Eingabefeld (nie abgeschickt) | `frontend/js/chat_vorlage.js`, eingebunden in `chat.html` |
| i18n DE/EN (100 Schlüssel je Sprache) | `frontend/js/i18n.js` |

**Funktionen (Parität mit llm_wiki, plus):** Färbung nach Art ↔ nach Themen-Inseln (Louvain im
Browser, 12er-Palette aus `theme.css`); Knotengröße ~ √Grad; Kantenstärke nach Zahl der belegenden
Dokumente; Hover dimmt alles außer dem Knoten und seinen Nachbarn und zeigt die Relevanz an der
Kante; Legende (Art: Anzahl je Art; Inseln: wichtigster Begriff, Mitglieder, Zusammenhalt mit
Warnung unter 0,15); Zoom +/−, Einpassen, Neu anordnen; Positions-Cache (`localStorage`);
Auffälligkeiten (überraschende Verbindungen über Inselgrenzen, Brückenbegriffe, Begriffe ohne
Verbindung, dünne Themen) mit Hervorheben, Ausblenden und „Recherche starten"; Suche mit
Hervorhebung und Kamerafahrt (lädt bei Bedarf vom Server nach); Filter nach Art, Wissensgruppe,
Ordner, Dokumente ein/aus; Detail mit Zusammenfassung, Aliassen, Quellen (öffnen per Blob, kein
Token in der Adresse), ein-/ausgehenden Kanten, „Begriff entfernen"; Pflege: Status, Neuaufbau
(eingestellt/alles/Gruppe/Ordner, voll), Abbrechen, Prüfliste (gleich/verschieden).

## 2. Abweichungen vom Plan

| Plan | Gebaut | Grund |
|---|---|---|
| `GET /api/wissensgraph/insights` | Auffälligkeiten im Browser | Sie bauen auf den Themen-Inseln auf, die die Legende zeigt. Eine zweite Community-Erkennung im Server liefe auseinander – eine Karte spräche dann von einer Insel, die es in der Grafik nicht gibt. |
| „Recherche starten" an den Agenten | Vorlage im Chat-Feld, kein Abschicken | Der Auftrag stammt aus einer Auswertung, nicht vom Benutzer; er soll ihn lesen und bewusst absenden. |

## 3. Befunde – fast alle nur im echten Browser sichtbar

1. **sigma 4 hat eine andere API als 2/3** (eigener Fehler: Schnittstelle angenommen statt
   nachgelesen). Der Reduzierer bekommt die eigenen Attribute erst als **drittes** Argument
   (mit dem zweiten: alle Knoten grau, Inselfärbung warf); `labelColor` ist keine Einstellung
   mehr, sondern steht je Element (Beschriftung dunkel auf dunkel); `hidden` heißt
   `visibility`, `forceLabel` heißt `labelVisibility`; die Kamera kennt kein `animatedZoom`/
   `animatedReset` mehr (`zoomIn`/`zoomOut`/`reset`). Die erste Chrome-Messung war trotzdem
   fast grün – „Hover dimmt" und „Suche hebt hervor" sind bei einheitlich grauen Knoten
   trivial wahr. Erst der **Screenshot** zeigte es. Jetzt misst die Abnahme die Vielfalt der
   Farben und die Beschriftungsfarbe in den Anzeigedaten; der jsdom-Wächter prüft als Regel,
   dass jede benutzte Kamera-Methode im ausgelieferten Bundle steht und kein sigma-2/3-Feld
   mehr vorkommt.
2. **sigma wirft schon beim LADEN**, wenn ein Browser `WebGL2RenderingContext` nicht kennt. Die
   erste Fassung behandelte das als „Bibliotheken fehlen" und brach ab – Auffälligkeiten,
   Prüfliste und Pflege wären mit weg gewesen. Jetzt gilt es wie „kein WebGL 2": Meldung über
   der Fläche, alles andere läuft (im jsdom-Wächter natürlich hergestellt: dort scheitert nur
   sigma).
3. **Keine `.hidden`-Regel auf der Seite** – sie steht nur in `chat.css`/`feedback.css`.
   Hinweisbalken und Detailfeld standen leer, aber sichtbar da (dieselbe Falle wie /feedback
   2026-09-15).
4. **Sprachwechsel lauschte auf `document`**, `i18n.js` feuert auf `window` – vom jsdom-Wächter
   gefunden, bevor er überhaupt stand.
5. **Insel-Kennung als Zeichenkette** (`Object.keys`) gegen die Zahl am Knoten – Hervorheben
   einer Insel aus der Legende und die Mitgliederliste dünner Themen wären leer geblieben.
6. **Themenwechsel-Listener zu spät angemeldet** (erst nach `/api/me`) – das frühe Umstellen
   durch `theme.js` ging verloren.
7. **BSI M10 (deny-by-default):** ohne Eintrag als Seitenrahmen lieferte schon die leere Hülle
   401. Jetzt in `zugang_regel.AUSNAHMEN`, mit Wächter und Gegenprobe.

Dazu vier eigene Prüfstand-Mängel, alle von Gegenproben aufgedeckt: eine Prüfung der Kanten nur
an der Vollansicht (dort hat jede Kante beide Enden), ein Testbestand ohne Nachbarordner
(Präfix-Falle unstellbar), eine Positivkontrolle, die einen Produktfehler zu „konnte nicht
laufen" machte (Register), und eine `.hidden`-Prüfung, die `.am-q-edit.hidden` als globale
Regel las.

## 4. Prüfung

| Wächter | Prüfungen |
|---|---|
| `tests/test_wissensgraph_api.py` (neu) | 36 |
| `tests/test_wissensgraph_ui.js` (neu, jsdom, echte Seite und Module) | 84 |
| `tests/live_wissensgraph_ui_dev.py` (neu, echtes Chrome, hell+dunkel, 1400/520 px) | 37 |
| `tests/test_endpoint_rights.py` (6 Routen ergänzt) | 134 |
| Gegenproben `tests/gegen_wissensgraph.py` (jetzt einschließlich API und UI) | **68 / 68** (die letzte nach der Schärfung von Hand nachgestellt) |

Unverändert grün: Cache-Buster, CSP H4 (Frontend und Backend), JS-Einbindung, keine externen
Einbindungen, Kommentare deutsch, Echtwerte, BSI M10, i18n-Schlüssel, Symbol-Semantik,
JS-Reichweite, Marke, Portal-Kacheln, Portal-Tiles, Zahnrad, Theme-Vorgabe, Topbar-Symbole,
jsdom-Einbindung. **Bestand, nicht angefasst:** `test_seite_breit_ui.js` bricht auch auf `HEAD`
ab (jsdom kennt den `:has()`-Selektor in `style.css` nicht).

**Optisch abgenommen** (Screenshots gesehen, hell und dunkel): Färbung nach Art und nach
Inseln, Hover mit Nachbarn und Beschriftung, 520 px ohne Überlauf, Legende 16,96:1 / 15,90:1.

## 5. Offen

- Hover auf einen Knoten mit über 100 Nachbarn: die Beschriftungen überlappen. Eine Begrenzung
  der erzwungenen Beschriftungen (z. B. nur die Nachbarn mit dem höchsten Grad) wäre die nächste
  Verfeinerung.
- Cache-Buster: `i18n.js?v=402` und `theme.css?v=44` in allen Seiten, `portal_seite.js?v=9`.
