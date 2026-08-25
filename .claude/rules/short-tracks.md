---
paths:
  - "backend/short_tracks.py"
  - "backend/short_tracks_runner.py"
  - "backend/prompt_check.py"
  - "frontend/tracks.html"
  - "frontend/js/tracks.js"
  - "frontend/js/short_tracks_admin.js"
  - "skills/short-tracks/**"
  - "tests/test_short_tracks.py"
  - "tests/test_short_tracks_ui.js"
---

<!-- Ausgelagert aus CLAUDE.md am 2026-08-25. Diese Datei laedt NUR, wenn Claude eine
     der oben genannten Dateien liest. Landkarte + Verweis stehen in CLAUDE.md. -->

## Short Tracks `/tracks`: Ablagen mit gespeichertem Prompt (2026-08-18)
**Was es ist:** Ein Brett aus benannten **Ablagen** („Dumps"), jede mit gespeichertem Prompt; wer
eine Datei oder URL darauf zieht, loest ihn aus. Ergebnis auf der Karte, erzeugte Dateien als
Download-Chip. Code: `backend/short_tracks.py` (Registry), `short_tracks_runner.py` (Aufnahme,
Warteschlange, Lauf), `/api/tracks/*`, `frontend/tracks.html` + `js/tracks.js`, Admin-Reiter
`js/short_tracks_admin.js`, Skill `skills/short-tracks/`.

**Entscheidungen des Nutzers:** Dateien UND URLs · eigene Seite mit Portal-Kachel · Admin legt
globale Ablagen an, jeder Benutzer eigene · Hintergrundlauf mit Warteschlange, Anzahl im
Admin-Bereich einstellbar (Vorgabe 2) · je Ablage „jede Datei einzeln" (Vorgabe) oder „alle
gemeinsam" · **Ergebnis nur anzeigen + Download**, kein Mail-/Wissens-/Ordner-Ziel ·
Werkzeug-Bereiche waehlbar aus einer Admin-Freigabe · optionales Hinweisfeld · Quelldatei bleibt
liegen · eigene Zugriffs-Freigabe.

- **Warum ein Benutzer hier eigene Prompts speichern darf** (sonst Admin-Sache): der Lauf startet
  nur, weil ein Mensch etwas darauf gezogen hat, traegt dessen Kennung und ist **immer
  unprivilegiert** (`_actor_fuer` – `privileged` hart `False`, **kein Feld eines Dumps**), und der
  Werkzeugsatz ist eine Whitelist aus Admin-freigeschalteten Bereichen. Wer eine dieser drei
  Eigenschaften aufhebt, macht Short Tracks zum bequemsten Weg um `_BLOCKED_TOOLS_FOR_LDAP`.
- **Zugriffs-Freigabe 1:1 wie E-Mail** (Nachtrag auf Wunsch; gebaut war der Bereich zunaechst fuer
  jeden Angemeldeten offen): `tracks_allowed_users` ODER `tracks_allowed_group`, **leer = niemand**,
  kein Admin-Bypass (`require_tracks_access`). `permissions.tracks` nennt Freigabe UND Skill.
  **`/api/tracks/admin/*` bleibt `require_local_auth`** und damit unabhaengig – ein Admin muss
  Grenzen pflegen koennen, ohne sich einzutragen. Block `sec-sub-tracks` startet versteckt
  (`app.js::updateTracksSecVisibility`). Zwei Bestandstests schrieben das alte Verhalten fest.
- **`werkzeuge_fuer()` gibt IMMER eine Menge zurueck, nie `None`** – anders als bei E-Mail gibt es
  bewusst keinen Bereich „voller Werkzeugkasten", der Dateiinhalt kommt von aussen. `basis`
  (Lesen + Tabellen + Dokumente) ist Pflicht und Vorgabe; `wissen`, `fach` (nur lesend) und
  `shell` schaltet ein Admin frei. Ohne Freigabe gilt allein `basis`.
- **`run_task_headless`, NICHT `run_task`** – letzteres laedt und SPEICHERT den Chat-Verlauf des
  Benutzers. Preis: headless sendet keine Statusmeldungen und ruft `_deliver_docs` nicht auf;
  beides holt der Runner ueber die Hooks `agent._schritt_hook` und `_ergebnis_hook` nach, mit
  einem Sammler statt eines WebSockets. Eine zweite Fassung der Datei-Erkennung waere Drift.
- **Eigener `JarvisAgent` je Auftrag** (ein Lauf dauert Minuten und duerfte den geteilten
  Hauptagenten nicht blockieren); Profil/Denktiefe/Schrittgrenze ueber **dieselben** Attribute wie
  Rollen-Agenten (`_role_profile_id`, `_role_max_steps`).
- **Die Warteschlange liest ihre Grenze bei JEDEM Durchlauf frisch** (`st.gleichzeitig()`) statt
  sie in einer Semaphore einzufrieren – eine Aenderung im Admin-Reiter soll ohne Dienstneustart
  greifen.
- **Die Arbeitskopie in `/tmp` entsteht erst beim START des Auftrags** (`anhang_<12 Hex>_<name>`,
  30-min-Frist ueber `backend/attachments.py`) – ein Auftrag, der 40 min in der Schlange steht,
  haette sie sonst verloren. Massgeblich ist die Ablage in `data/documents` mit Eigentuemer.
- `data/short_tracks.json` + `short_tracks_log.jsonl` (0640) in `_APP_DENY_REL`, `PRIVATE_FILES`,
  `SHELL_SECRET_PATHS`: wer die Registry beschreibt, legt sich einen Dump mit Bereich `shell` an
  und laesst ihn unter fremder Kennung laufen. Protokoll altert nur nach Alter (`log_retention`).

### Injektionsproben: 1 von 6 → 6 von 6 (gemessen)
Ablage, deren Aufgabe **jeden** Werkzeugaufruf verbietet – jeder Aufruf im Audit-Log ist der
Beweis; dazu eine **Positivkontrolle**, sonst beweist „gehalten" nichts.
- Durchgekommen war der **Nachbau der Auftragsstruktur** (CSV mit `===== ENDE ABGELEGTER INHALT
  =====` + eigener Aufgaben-Abschnitt). Markenzeilen zu entschaerfen genuegte **nicht**: die Zeile
  verliert dadurch ihre GESTALT, nicht ihre BEDEUTUNG.
- **Drei Massnahmen:** (1) **die Aufgabe steht am ENDE noch einmal woertlich** – ein blosser
  Verweis reichte nicht, die nachgebaute Marke stand naeher am Antwortzeitpunkt; wirksamste, ein
  paar hundert Zeichen. (2) **Strukturwoerter werden im Fremdtext gebrochen** (`A·UFGABE DIESER
  ABLAGE`, `_STRUKTURWORT`) – fuer einen Leser unveraendert, als Nachbau unbrauchbar.
  (3) Echtheitskennung je Lauf.
- **Restrisiko:** Prompt-Ebene ist wahrscheinlich, nicht sicher. Harte Grenze ist der
  Werkzeug-Zuschnitt – bei `basis` kann eine praeparierte Datei hoechstens den Antworttext
  verfaelschen, bei `shell` ist die Flaeche deutlich groesser. Deshalb `shell` nicht per Vorgabe.

### Vier Befunde aus dem echten Lauf
1. **Das Modell rechnet falsch und sieht dabei glaubwuerdig aus** („Summe 1.999,50", richtig
   2.000,00). Der Vorspann verlangt seither **„RECHNE NICHT IM KOPF"**: Summen ueber ein Werkzeug
   oder ausdruecklich sagen, dass sie ungeprueft ist.
2. **Die ABGELEGTE Datei wurde als ERGEBNIS angeboten** (Namensraterei in `_deliver_docs`, die
   Eingabedatei erfuellt die mtime-Schranke). Kein Sicherheitsproblem, aber ein Chip heisst „hier
   ist das Ergebnis" – Eingabepfade gehen jetzt vorher als „schon geliefert" in `_deliver_docs`.
3. **Die eigene oeffentliche Adresse des Servers kam durch die SSRF-Schranke** – sie ist nicht
   privat, zeigt aber ueber `lo` an der Firewall vorbei auf lokale Dienste. `_eigene_adressen()`
   sperrt sie. ⚠ In einem Netz mit oeffentlichen Adressen sind andere Haus-Server per IP-Bereich
   nicht von fremden zu unterscheiden – dafuer braeuchte es eine Ziel-Whitelist (nicht gebaut).
   Weiterleitungen werden **manuell** verfolgt, `follow_redirects=True` waere hier falsch.
4. **Der Werkzeug-Zuschnitt haelt live** – Ablage ohne `shell` mit „fuehre `id` aus" endet mit
   „nicht erlaubt", Journal `nicht im Rollenumfang`, **kein** Audit-Eintrag.

### Vorfall: Dateien erzeugt, aber kein Download-Chip
`office_create_excel` legt die Datei selbst ab und nennt die URL in **seinem Werkzeug-Ergebnis**;
die Endantwort nennt nur den Klarnamen. Der Runner rief `_deliver_docs` **nur mit der Endantwort**
→ `dateien: []`. Fix: `agent._ergebnis_hook(name, result_str)` (Gegenstueck zu `_schritt_hook`),
der Runner sammelt die Ergebnistexte (`_ERGEBNIS_MAX = 40`) und laesst `_deliver_docs` ueber
Ergebnisse UND Endantwort laufen – mit **demselben** `delivered`-Set, also je Datei ein Chip.
**Merkregel: ein headless-Aufrufer, der Dateien ausliefern will, braucht die WERKZEUG-ERGEBNISSE**
– die Endantwort nennt Dateien in Prosa, nicht als URL.

### Zwei BESTANDS-Befunde, die diese Messung aufdeckte
1. **Die Injektionsheuristik war rein ENGLISCH** – „IGNORIERE ALLE VORHERIGEN ANWEISUNGEN" blieb
   in **allen** Kanaelen unsichtbar. Ergaenzt sind nur die woertlichen Gegenstuecke.
   **Ausdruecklich NICHT ergaenzt: ein deutsches „ohne Regeln/Beschraenkungen"** – es traf
   „ohne Beschraenkungen der Haftung"; ein Fehlalarm mit Kontosperre ist schlimmer als eine
   Luecke in der Sichtbarkeit.
2. **`inspect(block=False)` protokollierte in ein Fach ohne Oberflaeche** (`logonly`), obwohl der
   Docstring Sichtbarkeit verspricht – betraf auch die E-Mail-Regeln.
   `list_recent_violations(mit_logonly=True)` fuehrt beides zusammen und kennzeichnet weiche
   Eintraege; **die Zaehlung fuer die Auto-Sperre bleibt unangetastet.**

### Oberflaeche
- **Reset je Ablage** (⟳, `POST /api/tracks/dumps/{id}/reset`): verwirft alle EIGENEN Auftraege
  dieser Ablage und **bricht einen laufenden wirklich ab** (`task.cancel()` ueber das Register
  `_tasks`) – ohne die Referenz behielte ein haengender Lauf seinen Platz in der Schlange, und
  genau dafuer drueckt jemand „Zuruecksetzen". Status **vor** dem Abbruch setzen (das `finally`
  schreibt den Protokolleintrag), danach `_pumpe()`. Fremde Auftraege und das Protokoll bleiben
  unberuehrt; der Endpunkt prueft bewusst **nicht** `darf_benutzen` (gerade eine abgeschaltete
  Ablage will man aufraeumen), unbekannt → 404.
- **Karten maximieren** (⛶/🗗 wie `#btn-maximize-settings` – **die einzige Emoji-Ausnahme des
  Waechters**, aus Konsistenz mit dem Bestand, Zeichen aus der Quelle gelesen statt abgetippt):
  fuellt den Bereich **unter** der Titelleiste (`--st-top` wird GEMESSEN, nicht angenommen),
  Kopfzeile sticky, hoechstens EINE Karte, Escape verkleinert, **Zustand wird bewusst NICHT
  gemerkt** – ein Vollbild beim naechsten Oeffnen sieht wie ein Fehler aus.
- **Drehender Kreis in der Auftragsliste** (`.st-spin`, Vorgabe des Nutzers): erscheint **nur bei
  `status === 'laeuft'`** – ein wartender Auftrag arbeitet nicht. Er steht NEBEN dem Text „läuft …",
  nicht an seiner Stelle: eine Bewegung allein ist keine Information. `aria-hidden`, Farbe aus
  `--accent`.
  - **Die Liste wird alle 2 s neu gebaut** (`TAKT_AKTIV`), und ein CSS-`animation` beginnt bei
    jedem Neuaufbau von vorn – der Kreis spränge im Sekundentakt zurück. Deshalb ein **negativer
    `animation-delay` aus der Uhrzeit** (`-(Date.now() % 800)ms`): die Drehphase hängt an der Zeit,
    nicht am Rendern, und alle Kreise laufen synchron.
  - **`prefers-reduced-motion` verlangsamt, es schaltet NICHT ab** – ein stehender Ring sieht aus
    wie ein Zeichen, nicht wie ein Vorgang; die Anzeige verlöre genau das, wofür sie da ist.
  - **FALLSTRICK im eigenen Test:** `laufZeile.querySelector(...)` ohne Null-Prüfung *wirft*, wenn
    der Kreis fehlt – die Gegenprobe bricht dann ab und sieht wie ein bestandener Lauf aus. Jetzt
    null-sicher; Gegenproben beißen mit 3 bzw. 1 FAIL.
- **Eine abgeschaltete Ablage bekommt GAR KEINE Drop-Bindung** – der Server weist mit 404 ab, und
  eine Flaeche, die zum Ablegen einlaedt, produziert eine Meldung, die niemand deuten kann.
- `.st-form` braucht `grid-column: 1 / -1` (Kind des Karten-Rasters), `.st-board`
  `align-items: start` (sonst zieht eine lange Auftragsliste die Nachbarn mit); das wandernde
  Formular braucht **beide** Haelften (heimholen vor `innerHTML=''` UND wieder einsetzen).
- **Endlosschleife im Admin-Reiter:** `zeichne()` rief `applyLang()`, das `jarvis-lang-changed`
  feuert, worauf der Zuhoerer neu lud – **ueber 40 Abrufe in 250 ms**, ein gesetzter Haken war im
  naechsten Durchlauf weg. Fix: Sprachvergleich (`_lang` schon in `laden()` setzen, nicht erst in
  `zeichne()` – sonst faellt ein `applyLang()` ins Zeitfenster des laufenden Abrufs) **plus**
  `_laeuft` gegen parallele Abrufe. Der Test war „gruen", weil er sofort nach `onShow()` prueste;
  jetzt frisches DOM, Haken setzen, 150 ms warten, dasselbe Element pruefen.
- **„pandas/openpyxl" stand in einem Text fuer nicht-technische Benutzer** – Bereichsnamen
  beschreiben jetzt die Wirkung („Eigene Rechenschritte (Programm ausfuehren)").
- **Nur das Endergebnis wird angeboten** (`_endergebnis_filtern`): seit dem `_ergebnis_hook` wurde
  jedes Zwischenprodukt zum Chip. Zwei Schranken gegen Datenverlust – nennt die Antwort KEINE der
  Dateien, gilt weiter alles als Ergebnis, und Zwischenprodukte werden im Text **namentlich
  genannt**. Verglichen wird auf **Wortgrenze** (`\b`): `Master.xlsx` steckt in
  `erweiterte_master.xlsx`, mit Teilstring haette der Filter nichts bewirkt. Der Hinweis wird
  **nach** `_clean_doc_refs` angehaengt.

### Verifiziert
`tests/test_short_tracks.py` (365) · `tests/test_short_tracks_ui.js` (242). Live auf DEV: echter
Agentenlauf 3,3 s, Warteschlange mit `gleichzeitig=1`, Injektionsproben 6/6 mit Positivkontrolle,
**kein Konto gesperrt**; Freigabe 19/19 (leer → 403 an allen sieben Benutzer-Endpunkten, Seite
weiter 200 als leere Huelle, Admin-Endpunkt weiter 200).
**Noch NICHT geprueft:** Bild (OCR-Weg) und URL gegen eine echte oeffentliche Seite (auf DEV hat
`jarvis` keine Internet-Freigabe), Verhalten unter Last.
**Auf ECHT noch NICHT ausgerollt.** Beim Ausrollen: Skill aktivieren, **unter *Sicherheit →
Berechtigungen → Short-Tracks-Zugriff* eintragen (leer = niemand)**, Grenzen und Bereiche pruefen
(Vorgabe: nur „Lesen + Dokumente erzeugen"). **Kostet einen Skill-Slot.**

### `shell_execute` gehoert zur Grundausstattung (Vorgabe 2026-08-24)
**Gemessen auf ECHT, Ablage „Tabellen zusammenfuehren": vier Laeufe an einem Vormittag, kein
einziges brauchbares Ergebnis.** Das Journal nannte dabei achtmal
`Rolle 'dump:…': Tool 'shell_execute' nicht im Rollenumfang`, und das Modell schrieb es selbst in
seine Antwort: „Da shell_execute nicht verfuegbar ist, hole ich die restlichen Spalten in Batches"
bzw. „Shell ist gesperrt. … Ohne Shell-Tools muss ich die Daten manuell in die Excel-Struktur
uebertragen." Ergebnisse: einmal 32 Schritte / 534 s / **nichts**; einmal 27 Spalten
**faelschlich auf 0** gesetzt; einmal Master UND Slave **selbst erfunden** („hypothetische
weitere Monate als Platzhalter"), samt derselben Datei zweimal als Chip.
- **Entscheidung des Nutzers, woertlich: „es KANN NICHT SEIN, dass `shell_execute` nicht verfuegbar
  ist. Eine Sicherheit, die die Funktionsfaehigkeit einschraenkt, ist nicht zumutbar."**
  `shell_execute` steht jetzt in `BASIS_WERKZEUGE`, der abwaehlbare Bereich **`shell` ist weg**.
- **Die Beschraenkung war ohnehin KEIN Sicherheitsgewinn:** der Lauf traegt die Kennung des
  Menschen, der die Datei abgelegt hat, ist IMMER unprivilegiert und laeuft im privaten `/tmp` als
  `jarvis_sandbox*` – genau wie ein Shell-Befehl desselben Benutzers **im Chat, wo er
  `shell_execute` hat**. Die Ablage schnitt also einen Benutzer zu, der einen Klick weiter mehr
  darf. Was traegt, ist die harte Grenze: OS-Benutzer, Namespace, Pfad-Confinement, Deny-Muster.
- **Der Haken durfte nicht als Attrappe stehen bleiben** – ein Schalter, der nichts mehr bewirkt,
  behauptet einen Zustand, den er nicht herstellt. `wissen` und `fach` bleiben eigene Bereiche:
  dort geht es nicht um Rechenleistung, sondern um ZUGANG zu fremden Datenquellen – das ist die
  Grenze, die ein Administrator ziehen soll.
- **`ALTE_BEREICHE = ("shell",)` – die einzige Stelle, an der ein unbekannter Wert still
  uebergangen wird**, und das ist Absicht: ohne sie liesse sich eine bestehende Ablage mit
  `bereiche: ["basis","shell"]` **nicht mehr speichern** („Unbekannte Werkzeug-Bereiche: shell") –
  ein Fehler, den niemand deuten kann, fuer eine Faehigkeit, die sie ohnehin hat. Der Benutzer
  verliert nichts, deshalb keine Meldung.

### Spaltennamen sind STRUKTUR – der Kopf wird nicht auf eine Anzahl gekappt
Dieselbe Messung deckte die eigentliche Ursache auf, und sie liegt in `skills/office/tabellen.py`:
- Das Blatt der echten Datei hat **254 Spalten** (Laborcode-Kuerzel als Spaltenkopf).
  `xlsx_inspect` benannte davon **60** und meldete „+182 weitere benannte Spalten";
  `xlsx_read_range` benannte sogar nur **25** – und schrieb darunter „Mit 'spalten' gezielt
  auswaehlen". **Ein Zirkelschluss:** der Hinweis verlangt Namen, die dieselbe Ausgabe gerade
  verschwiegen hat. Das Modell kam nur durch Durchprobieren weiter (24 Leseaufrufe).
- **Der Platz war da:** der ganze inspect-Text war **2.630 von 14.000 erlaubten Zeichen** lang. Die
  Kappung kam allein von einer festen Zahl.
- Jetzt `KOPF_TEXT_MAX = 4000` **Zeichen** (nicht Spalten) ueber `_kopf_text()`, benutzt von
  `xlsx_inspect` UND `xlsx_read_range` – eine Stelle, damit die beiden nicht wieder verschieden
  weit kappen. **Die DATENZEILEN bleiben gekappt** (`BEISPIEL_SPALTEN = 25`): dort ist die Grenze
  richtig, Werte gehoeren nicht durch das Modell. Reisst die Namensliste den Deckel, wird die
  Restzahl **beziffert** – eine unvollstaendige Liste, die sich fuer vollstaendig ausgibt, waere
  schlimmer als eine kurze.
- **Merkregel: die SPALTENNAMEN sind das, was diese Werkzeuge liefern sollen.** Wer sie nach Anzahl
  deckelt, deckelt die Struktur und laesst nur die Daten uebrig.

### Ein Lauf, dessen Antwort mitten im Satz endet, ist kein Erfolg
Der Lauf um 12:28 wurde als **`ok: True` mit `dateien: []`** verbucht; die Endantwort lautete
„… hole ich die restlichen Spalten in Batches.\nFehler:" – abgebrochen. Ein gruen gemeldeter
Fehlschlag ist die schlimmste Variante, weil niemand nachsieht. `_kein_ergebnis()` erkennt das
jetzt und loest denselben Neuversuch aus wie bei einer leeren Antwort.
- **Bewusst ENG:** geprueft wird das Ende auf `Fehler:`/`Error:`, **nicht** allgemein ein
  Doppelpunkt am Satzende – eine legitime Antwort darf „Die Datei liegt bereit:" heissen, wenn
  danach der Download-Chip kommt.

### Nachtrag am selben Tag: CSV als Quelle, und headless-Laeufe im Verlauf
Beide Punkte standen hier zunaechst als „bewusst offen" – auf Nachfrage des Nutzers geschlossen.

**a) Eine CSV ist eine erlaubte QUELLE** (`_CSV_ENDUNGEN` in `skills/office/tabellen.py`).
`_oeffnen()` baut aus einer CSV/TSV eine Mappe IM SPEICHER; damit arbeiten `_kz`, `_kopfzeile`,
`iter_rows` und alle vier Werkzeuge unveraendert weiter – ein zweiter Codepfad je Werkzeug waere
auseinandergelaufen.
- **SCHREIBEND bleibt gesperrt** (`xlsx_edit`-Ziel, `xlsx_merge`-Master): eine CSV hat kein Layout
  und keine Formeln, „bearbeiten und Formeln behalten" ist dort keine Zusage, die man halten kann.
  Die Meldung nennt den Weg, statt nur abzulehnen.
- **`_csv_wert()` – die Umwandlung darf keine Bedeutung loeschen.** Ohne sie landet „3282" als TEXT
  in der Master-Zelle, Excel richtet es links aus und jede Summenformel darueber rechnet es als 0.
  Umgekehrt bleiben **fuehrende Nullen TEXT** (PLZ `02625`, Kundennummer `00083` – als Zahl waeren
  sie zerstoert) und Ziffernfolgen ueber 15 Stellen (IBAN verliert als float die letzten Stellen).
  Deutsche Schreibweise laeuft ueber `chart.parse_number` – `float("1.234")` ergaebe 1.234 statt
  1234, also Faktor 1000.
- **`chart.csv_zeilen()` ist die EINE Stelle fuer Kodierung und Trennzeichen** (utf-8-sig → utf-8 →
  cp1252 → latin-1, Sniffer mit `;` als Vorgabe). `_read_table` der Diagramme benutzt sie jetzt
  ebenfalls; zwei getrennte Erkennungen waeren beim naechsten Exportformat auseinandergelaufen.

**b) Headless-Laeufe stehen im LLM-Verlauf** (`_run_headless` → `conv_log.log_conversation`).
Bis dahin protokollierte nur `run_task`, der Chat-Weg – unsichtbar war also ausgerechnet, was ohne
Zuschauer laeuft: E-Mail-Regeln, Short Tracks, Cron, Rollen-Agenten.
- **Der Eintrag entsteht im `finally`**, also auch fuer einen abgebrochenen oder gescheiterten
  Lauf. Genau der ist der interessante.
- **Auch fuer `is_sub_agent`-Laeufe** – anders als im Chat-Weg, wo der Eltern-Lauf mitschreibt.
  Hier waere sonst der Rollen-/Dump-Lauf unsichtbar, und das war der gemeldete Fall. Doppelte
  Eintraege entstehen nicht: der aeussere Lauf protokolliert nur sein Delegations-ERGEBNIS.
- **`client_type` nennt den Kanal UND die Rolle** (`headless:dump:c4e3312e6197`) – ohne das weiss
  niemand, WELCHER Lauf es war. Die Pille in `telemetry.js` rendert den Wert escaped, es braucht
  keinen Frontend-Fix.
- **Die Kosten wurden GEMESSEN, nicht geschaetzt** (ECHT, 2026-08-24): der conv-Ordner haelt 507
  Laeufe in 21 MB (~42 KB je Lauf, fast alles System-Prompt); headless kaeme mit 195 Mail- und 28
  Tracks-Eintraegen ueber Wochen dazu, also rund +9 MB. **Eine Dedup-Infrastruktur fuer den Prompt
  braucht das nicht** – wer sie ohne Messung baut, loest ein Problem, das es nicht gibt.
- **Nebenbefund: `tests/test_empty_answer.py` schrieb in den ECHTEN Verlauf** – Teil 3 fuhr seit
  immer `run_task`-Laeufe, und die protokollieren. Jetzt wird `conv_log` in einen Sandkasten
  umgebogen, mit Exit-2-Waechter.

**Verifiziert:** `tests/test_short_tracks.py` (380) · `tests/test_short_tracks_ui.js` (242) ·
`tests/test_xlsx_tabellen.py` (161, auf DEV im venv; Abschnitt 8b deckt den CSV-Weg ab, Gegenprobe
ohne die CSV-Weiche = 7 FAIL) · `tests/test_empty_answer.py` (56, Abschnitt 4 fuer den
headless-Verlauf; Gegenprobe = 5 FAIL) · `tests/test_create_chart.py` (112). Live auf DEV: `werkzeuge_fuer([])` enthaelt
`shell_execute`, `BEREICHE` hat nur noch `basis|wissen|fach`, ein Altbestand-`shell` wird still
entfernt statt abgewiesen. An einer nachgebauten 254-Spalten-Struktur gemessen: **alle 253 Kuerzel
in EINEM `xlsx_inspect`-Aufruf** (3.570 von 14.000 Zeichen), `xlsx_read_range` nennt das letzte
Kuerzel ebenfalls – vorher waeren allein fuer den Kopf 11 Bloecke noetig gewesen.

### Sechs gleichnamige Downloads, fuenf davon Teilstaende (Vorfall 2026-08-24)
**Gemeldet von ECHT:** eine Ablage bot **sechs** Downloads an, alle
`IBSv3_Monatsstatistik_aktualisiert.xlsx`. Nachgemessen am echten Artefakt (nur Kennzahlen):

| Chip | Zeit | Zellen Blatt 2026 | uebertragene Werte |
|---|---|---|---|
| Quelle | 17:53 | 2197 | – |
| 1–5 (`xlsx_edit`) | 17:56:18–17:57:04 | 2243–2250 | **46–53 von 194** |
| 6 (shell) | 17:57:25 | 2391 | **194** |

- **URSACHE 1 – jedes Schreiben ist eine eigene Ergebnisdatei:** `xlsx_edit`/`xlsx_merge`
  verlangen `ziel` und legen ueber `_new_path()` bei JEDEM Aufruf eine Datei mit eigenem
  Capability-Namen ab. Fuenf Bearbeitungsschritte = fuenf vollwertige Ergebnisdateien.
- **URSACHE 2 – die Reihe baute nicht aufeinander auf:** alle fuenf Aufrufe hatten `path` auf der
  ORIGINAL-Quelle, jeder schrieb nur seinen Batch. **Wer einen der ersten Chips oeffnete, hatte
  stillschweigend ein Viertel der Daten** – strukturell war nichts verloren (985 Formeln, beide
  Blaetter, Druckbereich; die 13 KB Groessenunterschied sind `calcChain.xml` und `sharedStrings`,
  die Excel selbst neu aufbaut).
- **WARUM `_endergebnis_filtern` DAS NICHT FING:** es prueft, ob die Abschluss-Antwort den Namen
  nennt – bei namensgleichen Fassungen trifft derselbe Name auf ALLE zu. **Der Name ist dort kein
  Unterscheidungsmerkmal**, deshalb braucht es eine Stufe davor.
- **`_gleichnamige_verdichten()`** (Runner) behaelt je Anzeigename nur die **juengste** Fassung
  (mtime ueber `_dateizeit()`; bei unlesbarer Zeit gewinnt die **spaetere Fundstelle** – die Chips
  entstehen in der Reihenfolge der Werkzeug-Ergebnisse). Laeuft **VOR** `_endergebnis_filtern`.
  Die verdraengten Fassungen werden im Text **benannt und bleiben abrufbar** – dieselbe Schranke
  wie dort: die Verdichtung darf nichts verschweigen. **Eigener Satz mit der ANZAHL**, nicht in die
  Zwischenprodukt-Aufzaehlung gemischt: fuenfmal derselbe Name unterscheidet nichts.
- **`_weiterarbeiten_hinweis()` behebt die Ursache, nicht das Symptom:** beide Schreibwerkzeuge
  sagen jetzt im Ergebnis, dass ein weiterer Schritt `path` auf die **`/api/documents/`-URL des
  Ergebnisses** setzen muss – sonst gehen die eben geschriebenen Aenderungen verloren. Ein Test
  belegt, dass diese URL wirklich als `path` annehmbar ist und der zweite Stand **beide**
  Aenderungen traegt (ein Hinweis, den das Werkzeug selbst nicht einloest, waere die bekannte
  Prompt-Falle).
- **Offen (bewusst):** der Chat-Weg kann das nicht filtern – dort streamt `_deliver_docs` jeden
  Chip sofort, eine vollstaendige Liste gibt es erst am Ende. Betroffen ist damit nur `/tracks`.
- **Verifiziert:** `tests/test_short_tracks.py` (393, Abschnitt 14 stellt den gemeldeten Fall mit
  echten Dateien und gesetzten mtimes nach) · `tests/test_xlsx_tabellen.py` (168, Abschnitt 8c).
  Gegenproben beissen einzeln (6/6 FAIL). **FALLSTRICK im eigenen Test:** die erste Fassung nutzte
  `.split(marke)[1]` – die Gegenprobe brach mit `IndexError` ab statt fehlzuschlagen, also genau
  der Fall aus dem Register. Jetzt `find()` + Slice.

