---
paths:
  - "backend/lauf_tmp.py"
  - "backend/attachments.py"
  - "backend/sandbox.py"
  - "backend/agent.py"
  - "backend/broker/**"
  - "backend/tools/shell.py"
  - "tests/test_lauf_tmp.py"
  - "tests/test_doc_delivery.py"
---

<!-- Ausgelagert aus CLAUDE.md am 2026-08-25. Diese Datei laedt NUR, wenn Claude eine
     der oben genannten Dateien liest. Landkarte + Verweis stehen in CLAUDE.md. -->

## Privates `/tmp` je Benutzer (Mount-Namespace, 2026-08-23)
**Was es loest:** der Abschnitt darueber. Alle Domain-Benutzer fuehren Shell-Befehle als EIN
OS-Benutzer aus; in `/tmp` gab es damit keine Trennung zwischen ihnen, und Dateirechte sind fuer
dieses Problem die falsche Ebene (0600 sperrt den eigenen Lauf aus). Jetzt bekommt jeder
unprivilegierte Benutzer ein eigenes Arbeitsverzeichnis, das `bwrap` im Lauf auf `/tmp` mountet.
Code `backend/lauf_tmp.py` (eine Stelle fuer alles), Verdrahtung in `tools/shell.py`,
`broker/ops.py::sandbox_exec`, `agent.py`, `sandbox.py`, `attachments.py`.

- **JE BENUTZER, NICHT JE LAUF** (Vorgabe des Nutzers, nach einer ersten Fassung mit einem
  Verzeichnis je Lauf): die Trennung, die FEHLTE, war Benutzer gegen Benutzer. Zwei Laeufe
  derselben Person voreinander zu verbergen loest kein Sicherheitsproblem, kostet aber etwas, das
  vorher ging – ein Zwischenprodukt, das der Agent nicht als Ergebnis nennt, waere nach dem Lauf
  weg und „und jetzt filtere Spalte C" liefe in `No such file or directory`. **Der Preis:** das
  Aufraeumen ist nicht mehr deterministisch („Lauf zu Ende, Verzeichnis weg"), sondern haengt an
  einer Frist, und ein Lauf sieht Dateien frueherer Laeufe derselben Person – wie vorher auch.

- **DER KERN IST DIE UEBERGABE, NICHT DIE GRENZE.** Der Agent arbeitet strukturell in `/tmp`, und
  der System-Prompt sagt ihm das an sieben Stellen. Ein `--tmpfs /tmp` haette jede Ergebnisdatei
  beim Prozessende vernichtet und den Download-Chip ausfallen lassen. Deshalb
  **`--bind <arbeitsverzeichnis> /tmp`**: der MODELL-Pfad `/tmp/ergebnis.xlsx` bleibt gueltig, auf
  dem Host liegt die Datei in `/tmp/jarvis-arbeit/<kennung>/` und ist fuer `_deliver_docs`
  erreichbar. **Kein Prompt musste sich aendern.**
- **Fremde Dateien sind nicht „unlesbar", sie sind NICHT VORHANDEN** – das ist der Unterschied zu
  jeder Rechte-Loesung. Dazu `--unshare-pid`: kein Blick auf fremde Prozesse (gemessen 5 statt 288).
- **Anhaenge gehen den ANDEREN Weg: Host-Pfad = Modell-Pfad.** Eine Arbeitskopie muss zwei Welten
  bedienen – die Shell im Namespace UND die Backend-Werkzeuge (`xlsx_inspect`, `office_read`,
  `create_chart`, `filesystem`), die im Dienstprozess laufen und den Pfad so oeffnen, wie das
  Modell ihn nennt. Ein uebersetzter Pfad waere dort tot. Also: `/tmp/jarvis-anhaenge/<kennung>/`
  je Benutzer, per **`--ro-bind` auf denselben Pfad** in dessen eigene Laeufe – EINE Bindung
  unabhaengig von der Anzahl (je Datei waere es eine 0-Byte-Attrappe im Lauf-Verzeichnis, die als
  „Ergebnis" ausgeliefert werden koennte), und neue Anhaenge werden waehrend des Laufs sichtbar.
- **Damit faellt eine zweite Luecke: der BACKEND-Weg.** `authorize_fs` prueft jetzt die
  Zugehoerigkeit am Verzeichnis (`gehoert_anhang`, `gehoert_lauf`). Vorher konnte ein
  Domain-Benutzer die Arbeitskopie oder Ergebnisdatei eines anderen ueber jedes Werkzeug oeffnen,
  sobald er den Namen kannte – und `filesystem list /tmp` nannte ihm alle Namen. Der Namespace
  allein haette das NICHT geschlossen, er wirkt nur auf die Shell.
- **Der Dispatch uebersetzt Modell-Pfade** (`_lauf_pfade_umleiten`) fuer `filesystem`,
  `create_chart(source.file)` und jedes Werkzeug mit `pfad_parameter`; `skills/office`
  zusaetzlich in `_resolve_existing`. Ohne das schreibt die Shell `/tmp/x.xlsx` und das naechste
  Werkzeug findet dort nichts – ein Widerspruch, den niemand erklaeren kann.
- **Privilegierte Laeufe bekommen KEIN eigenes Verzeichnis.** Sie laufen als Dienstbenutzer,
  brauchen das echte `/tmp` (Screenshot-Werkzeug, Chrome-Profil) und haben ohnehin Root-Wege;
  Isolation zwischen Administratoren ist kein Ziel. **Verschachtelte Klammern ERBEN** – ein
  Sub-Agent muss die Dateien seines Eltern-Laufs sehen, auch wenn er einen anderen Actor hat.
- **`--dev-bind / /`, nicht `--bind / /`.** Eine gewoehnliche Bindung mountet `nodev`, damit
  scheitert `2>/dev/null` mit „Keine Berechtigung" – genau die Umleitung, die 2026-08-05 vier
  Konten gesperrt hat. Der Test hat dafuer eine Gegenprobe. Das Dateisystem bleibt sonst wie es
  ist: die harte Grenze sind weiter die OS-Rechte, eine Whitelist wuerde legitime Zugriffe
  (Wissens-Share, `/mnt`, `skills/`) abschneiden.
- **`setpriv --inh-caps=-all --ambient-caps=-all` davor** – `jarvis.service` vererbt
  `CAP_NET_BIND_SERVICE` an jedes Kind, `bwrap` bricht damit ab. Faellt bei einer Handprobe per
  `runuser` NICHT auf, nur im Dienst (Register: Dienstumgebung ≠ Handprobe).
- **Verzeichnisse legt ROOT an** (Broker-Op `sandbox_exec`, Argument ist die 8-Hex-**Kennung**,
  nie ein Pfad): Eigentuemer Sandbox-Benutzer, Gruppe des Dienstes, 0770 – beide Seiten brauchen
  Schreibrecht. Ein vom Backend zuerst angelegtes Verzeichnis wird per `chown` uebernommen, die
  Reihenfolge ist also gleichgueltig. **Die Einhaengepunkte muss root VORHER anlegen:**
  ueberlaesst man das `bwrap`, entstehen sie als `drwx------ jarvis_sandbox:jarvis_sandbox` und
  das Backend kann darin nichts mehr aufraeumen – `rmtree(ignore_errors=True)` scheitert STILL.
- **Aufgeraeumt wird NACH FRIST, und nur root kann es** (Op `lauf_aufraeumen`, Kennung hart
  geprueft): der Agent legt im Verzeichnis eigene Unterverzeichnisse an (`mkdir /tmp/zwischen`,
  matplotlib-Cache), die gehoeren dem Sandbox-Benutzer mit dessen eigener Gruppe. Vorgabe 240
  Minuten ohne Zugriff, **Untergrenze 4 Stunden**: die Frist ist die einzige Schranke gegen ein
  Verzeichnis, in dem gerade gearbeitet wird (ein aktiver Lauf haelt die mtime frisch).
- **Zusatz-Bindungen fuer Ablaeufe, deren Arbeitsverzeichnis den Lauf ueberlebt:**
  `lauf_tmp.zusatz_bind(pfad)` um den Aufruf von `run_task_headless` legen (beschreibbar, nur
  `/tmp`, Verwaltungswurzeln ausgeschlossen, Deckel 8). Der **Claude-Subagent** braucht das – sein
  Wegwerf-Klon liegt in `/tmp/claude_subagent/<job>` und waere im Lauf sonst NICHT VORHANDEN, der
  Skill still kaputt. Angemeldete Pfade sind von der Uebersetzung ausgenommen (Host = Modell).
  **Wer einen neuen Ablauf mit eigenem Arbeitsverzeichnis baut, muss ihn anmelden.**
- **FAIL-OPEN, aber nicht still.** Ohne `bwrap` laeuft alles wie vorher (gemeinsames `/tmp`), mit
  Klartext im Journal beim Start. Fail-closed waere hier falsch – es wuerde auf einem Server ohne
  `bubblewrap` jeden Shell-Befehl jedes Netzwerk-Benutzers abschalten. `start_jarvis_root.sh`
  Schritt 6d installiert das Paket selbst nach (wie 6c fuer die Python-Module). Abschaltbar mit
  `JARVIS_LAUF_ISOLATION=0`.
- **Erleichterungen, die erst dadurch moeglich sind:** die Frist der Arbeitskopien steigt von 30
  auf **240 Minuten** (`DEFAULT_TTL_MIN_ISOLIERT`) – sie ist kein Sicherheitsmittel mehr, sondern
  Datenminimierung, und „und jetzt Spalte C" nach der Mittagspause funktioniert wieder; ohne
  Isolation bleibt es bei 30. Der matplotlib-Cache liegt je Benutzer (`/tmp/.mplcache` im Lauf),
  nicht je Lauf – sonst waere der Schriftarten-Index bei jedem Shell-Befehl neu gebaut worden.
  Und der matplotlib-Cache braucht keine eigene Bindung mehr – er liegt einfach im
  Arbeitsverzeichnis (`/tmp/.mplcache`), das den Lauf ueberlebt.
- **Was die Trennung NICHT ersetzt:** die mtime-Schranke in `_deliver_docs`. Eine Zwischenfassung
  hat sie fuer Dateien im Lauf-Verzeichnis uebersprungen („was drin liegt, ist aus diesem Lauf") –
  mit einem Verzeichnis je BENUTZER ist die Annahme falsch, dort liegen auch die Zwischenprodukte
  von vorhin. Genau die duerfen nicht als Ergebnis dieses Laufs herausgehen.

### Drei ALTFEHLER, die erst die Abnahme dieses Umbaus sichtbar gemacht hat
1. **`shell_execute(code=…)` war fuer Netzwerk-Benutzer nie benutzbar.**
   `tempfile.NamedTemporaryFile` legt mit **0600** an, der Befehl laeuft aber als
   `jarvis_sandbox` – `python3 /tmp/jarvis_x.py` scheiterte reproduzierbar mit `Errno 13`. Das
   Skript liegt jetzt direkt im Lauf-Verzeichnis (keine Bindung noetig) und wird auf 0644 gesetzt.
   Ebenfalls weg: das `; rm -f` im Befehl, das als Sandbox-Benutzer ohnehin still scheiterte
   (fremder Eigentuemer im sticky `/tmp`) – aufgeraeumt wird jetzt vom Aufrufer.
2. **Der Timeout des Brokers griff bei einem STILLEN Befehl nicht.** `for line in proc.stdout`
   blockiert, die Deadline wird nur beim Eintreffen einer Zeile geprueft: `sleep 300` mit
   `timeout=3` lief bis zum Client-Timeout (33 s) und der **Prozessbaum lebte danach weiter**.
   Jetzt ein Wachhund-Timer plus Kill der ganzen PROZESSGRUPPE (`start_new_session=True` +
   `killpg`) – `proc.kill()` erwischte nur die aeussere Shell, nicht `runuser → setpriv → bwrap →
   bash → python`. Gemessen: 0 Waisen statt 3. Gleiche Korrektur im lokalen Zweig von `shell.py`.
3. **Eine Meldung im Normalbetrieb entwertet das Journal:** die erste Fassung rief `chmod` auf ein
   Verzeichnis, das der Broker schon uebernommen hatte → EPERM-Zeile bei JEDEM weiteren
   Shell-Befehl, obwohl alles funktionierte. Jetzt nur als Eigentuemer.

**Und ein eigener beim Umbau auf „je Benutzer":** beim Entfernen des mpl-Arguments rutschte in
`bwrap_verfuegbar()` ein Positionsargument auf `_pruefen`; die Pruefung warf TypeError, und die
Isolation war damit **still aus** (fail-open griff korrekt – nur eben immer). Kein Unit-Test sah
es, weil alle Abschnitte diese Funktion durch einen festen Wert ersetzen. Lehre und Gegenmittel:
**Positivkontrolle der Pruefung selbst** (Abschnitt 6b im Waechter: „bei installiertem bwrap muss
sie JA sagen") und alle Argumente dort namentlich. Register: wer eine Pruefung mockt, braucht
einen Test, der sie WIRKLICH laufen laesst.

**Verifiziert:** `tests/test_lauf_tmp.py` (147; der bwrap-Aufruf wird WIRKLICH ausgefuehrt, mit
Gegenprobe fuer `--dev-bind`, und der Sandkasten bricht mit Exit 2 ab, wenn eine Wurzel nicht
umgebogen ist). Gegenproben beissen einzeln (2/3/1/1/2 FAIL). **Live auf DEV ueber den echten
Broker-Weg:** zwei parallele Benutzer schreiben denselben Modell-Pfad `/tmp/gemeinsam.txt` und
lesen je nur ihre eigene Datei; `cat` auf die fremde Arbeitskopie und `filesystem` auf den fremden
Arbeitsbereich werden abgewiesen; Ergebnis und PNG kommen auf dem Host an; `code=` mit pandas und
matplotlib laeuft; ein zweiter Lauf desselben Benutzers findet das Zwischenprodukt des ersten;
Timeout beendet den Baum ohne Waise. **Auf ECHT noch NICHT ausgerollt.**

### Halb aktive Isolation: das Backend uebersetzte, der Broker isolierte nicht (Vorfall 2026-08-24)
**Gemeldet als „einmal mehr ein nicht existierender Link zu einer Behauptung":** eine Benutzerin
liess zwei Kontrakt-Tabellen zusammenfuehren (9.693 Zeilen, Ergebnis fertig erzeugt) und fragte
„wo lade ich die neue liste". Die Antwort lautete woertlich „…nutze diesen Link:" – und dahinter
stand **nichts**. Kein Download-Chip, keine Fehlermeldung, keine Journal-Zeile.
- **Ursache – eine PROZESSGRENZE ist eine VERSIONSGRENZE:** das Backend hatte den `/tmp`-Umbau,
  der **Broker-Prozess** lief noch mit seiner sechs Tage alten Kopie von `backend/broker/*`. Er
  nahm `arbeit`/`ro_binds` klaglos an, **ignorierte sie** und fuehrte den Befehl ohne `bwrap` aus:
  die Datei landete im gemeinsamen `/tmp`. Das Backend hielt die Isolation fuer aktiv, uebersetzte
  den Modell-Pfad nach `/tmp/jarvis-arbeit/<kennung>/…` – dort war nie etwas angekommen.
  Messbar am Zustand: Datei im echten `/tmp` mit Eigentuemer `jarvis_sandbox_noinet`,
  `/tmp/jarvis-arbeit` **leer**.
- **DIE LEHRE IST DIE ASYMMETRIE, NICHT DER ALTE PROZESS.** Fail-open ist hier richtig – aber
  **beide Seiten muessen denselben Rueckfall nehmen.** Faellt nur die AUSFUEHRUNG zurueck und die
  PFAD-UEBERSETZUNG nicht, ist die Isolation halb aktiv, und das ist schlimmer als gar keine: die
  beiden Welten sehen unter demselben Namen verschiedene Orte. **Wer eine Grenze einbaut, deren
  Wirkung ein anderer Prozess herstellt, muss sich von diesem bestaetigen lassen, dass sie
  wirklich gewirkt hat.**
- **Der Handshake laeuft ueber die Broker-ANTWORT:** `_op_sandbox_exec` liefert `isolation: bool`,
  `shell.py` gibt das an `lauf_tmp.melde_ausfuehrung()`. **Ein FEHLENDES Feld ist die Aussage
  „nein"** – genau so verhaelt sich jede Fassung, die den Umbau nicht kennt; auf ein neues Feld zu
  *warten* waere die Pruefung, die den Vorfall nicht gefunden haette. Danach uebersetzt
  `aufloesen()` nicht mehr und `lauf_scope()` oeffnet gar keinen Lauf.
  - Ausgewertet wird **nur** bei angeforderter Isolation und wirklich gelaufenem Befehl
    (`"rc" in res`) – `pending`/`denied`/`unreachable` sagen darueber nichts.
  - **`None` (nichts gemessen) gilt NICHT als unwirksam**, sonst waere die Isolation nach jedem
    Dienststart einmal aus. Der Preis ist genau EIN Befehl im gemeinsamen `/tmp` – und weil die
    Meldung vor der Auslieferung eintrifft, findet der Chip die Datei trotzdem.
- **AUSDRUECKLICH NICHT gebaut: ein Rueckfall „nicht im Lauf-Verzeichnis? dann im echten /tmp
  suchen".** Er haette den Vorfall auch behoben und ist die naheliegende Idee (`such_wurzeln()`
  nennt beide Wurzeln) – aber bei AKTIVER Isolation waere er die Wiedereinfuehrung genau der
  Luecke, die der Umbau geschlossen hat: Dateinamen sind ratbar (`ergebnis.xlsx`), und der Marker
  liefert die Datei ohne weitere Eigentuemerpruefung aus.
- **Der zweite, unabhaengige Fehler – und der ist der aeltere:** der Marker-Zweig in
  `_deliver_docs` brach bei fehlender Datei mit einem **nackten `continue`** ab. Kein Log, kein
  Hinweis. Und weil `_clean_doc_refs` den Marker aus dem Anzeigetext entfernt, blieb genau der Satz
  stehen, der auf ihn verwies. **Der Chip IST der einzige Weg zur Datei – faellt er aus, muss der
  Benutzer das ERFAHREN.** Jetzt: Journal-Zeile mit rohem UND aufgeloestem Pfad plus Grund, dazu
  eine sichtbare Zeile im Chat („Konnte nicht zum Download bereitgestellt werden: …").
  - Gemeldet wird **nur beim letzten Text des Laufs** (`melden=True`, gesetzt allein an der
    Endantwort). Bei einem Werkzeug-Ergebnis waere die Warnung verfrueht – die Datei kann einen
    Schritt spaeter entstehen, und dann stuenden Warnung und Chip nebeneinander.
  - Das gilt fuer **jede** Ursache eines verfehlten Markers (Tippfehler des Modells, geloeschte
    Datei, Ort gesperrt, Secret, Ingest-Fehler), nicht nur fuer diesen Vorfall.
- **Nebenbefund: `tests/test_doc_delivery.py` war seit dem Umbau vom 23.08. ROT** –
  `_hostpfad` ruft `_lauf_tmp.aufloesen`, und die Attrappen-Umgebung kannte das Modul nicht
  (NameError mitten im Lauf). Zusaetzlich hing eine Pruefung an der Zeichenkette
  `"_search_dirs = [docs_dir, _tmp_root]"`, die nach dem Umbau `[docs_dir] + _arb_roots` heisst –
  **eine Zeichenkette als Testkriterium ist eine Zeitbombe**, jetzt wird die Eigenschaft geprueft
  (`docs_dir` drin, `proj` nicht).
- **Verifiziert:** `tests/test_lauf_tmp.py` (160, Abschnitt 10 fuehrt `aufloesen`/`lauf_scope`
  WIRKLICH aus) + `tests/test_doc_delivery.py` (53, Abschnitt 7 stellt den Vorfall funktional
  nach). Gegenproben beissen einzeln (1/2/1 FAIL). **Live auf DEV ueber den echten Broker-Weg:**
  mit neuem Broker `isolation=True`, Datei nur im Lauf-Verzeichnis, `ls /tmp` zeigt nichts Fremdes;
  mit einem nachgebauten ALTEN Broker kommt kein Feld, der Merker faellt auf `False`, das Journal
  nennt Grund und Abhilfe, `aufloesen()` laesst den Pfad stehen und die Datei wird gefunden – ohne
  den Fix zeigt derselbe Aufbau auf `/tmp/jarvis-arbeit/<kennung>/…` und findet nichts.

### Wer NACH dem Lauf ausliefert, steht ausserhalb der Klammer (Vorfall 2026-08-24, zweiter Teil)
**Gemeldet am selben Tag, wenige Stunden nach dem Fix oben:** eine Ablage „Tabellen
zusammenfuehren" endete auf ECHT mit dem Satz „Die bearbeitete Master-Datei wurde als `` gespeichert."
– **kein Dateiname, kein Download-Chip, keine Fehlermeldung.** Der Lauf stand im Protokoll als
`ok: True` mit `dateien: []`.
- **Die Datei war fertig.** Gemessen: `/tmp/jarvis-arbeit/9e78f36a/IBSv3_Monatsstatistik.xlsx`,
  37 KB, Zeitstempel **zwei Sekunden vor Laufende**; im echten `/tmp` lag nichts. Der LLM-Verlauf
  (seit dem Vortag auch fuer headless-Laeufe) nennt den Antworttext woertlich: das Modell hatte
  korrekt `/tmp/IBSv3_Monatsstatistik.xlsx` geschrieben – den MODELL-Pfad.
- **URSACHE: `short_tracks_runner` liefert NACH `run_task_headless` aus.** Die Klammer
  `lauf_scope` wird in `_run_headless` geoeffnet und beim Verlassen zurueckgesetzt. Wer danach
  ausliefert, ist **doppelt blind**: `aufloesen()` gibt ohne ContextVar den Pfad unveraendert
  zurueck (Zweig b findet nichts), und `such_wurzeln()` liefert das Lauf-Verzeichnis nicht mit
  (Zweig c sucht am falschen Ort). Der Chat-Weg war nie betroffen – dort steht `_deliver_docs`
  INNERHALB von `run_task`. **Short Tracks ist der einzige Aufrufer ausserhalb** (drei Aufrufer
  insgesamt, per grep belegt).
- **Der Fix ist die Klammer um den Auslieferungsblock.** Sie ist gefahrlos wiederholbar: das
  Verzeichnis haengt am BENUTZER (`benutzer_kennung` ist deterministisch), und beim Verlassen wird
  nichts geloescht – es ist dasselbe Verzeichnis, in dem der Lauf gerade gearbeitet hat.
- **DER ZWEITE FEHLER IST DERSELBE WIE AM VORMITTAG, nur in Zweig (b):** die Pfad-Erkennung brach
  bei fehlender Datei mit einem nackten `continue` ab. Und weil `_clean_doc_refs` den Pfad aus dem
  Anzeigetext entfernt, blieb genau der Satz stehen, der auf ihn verwies. Jetzt meldet auch (b)
  einen verfehlten Pfad – **eng gehalten**: nur an einem ERGEBNISORT (`/tmp/…`, `data/documents/…`;
  ein genannter Quellpfad wie `/mnt/share/…` bleibt still), nur beim LETZTEN Text des Laufs
  (`melden=True`; ein Werkzeug-Ergebnis darf nichts behaupten, die Datei kann einen Schritt spaeter
  entstehen) und nur, wenn der Pfad **nicht schon ausgeliefert** wurde.
  - **Die `_schon()`-Pruefung ist nicht optional, der Bestandstest hat sie erzwungen:** `_ingest`
    VERSCHIEBT die Quelle nach `data/documents` – danach ist der Pfad zwangslaeufig weg. Zwei
    Normalfaelle liefen sonst in eine Falschmeldung **neben dem fertigen Chip** (derselbe Pfad im
    Liefer-Marker UND als nackter Pfad im selben Text; oder ein Werkzeug-Ergebnis liefert, die
    Endantwort nennt ihn erneut).
  - **Die Sendung der Meldung stand ZWISCHEN (m) und (b)** – ein in (b)/(c) vermerkter Fehlschlag
    waere also nie ausgegeben worden. Sie steht jetzt am ENDE. *Eine Meldung, deren Wirkung von
    ihrer Position abhaengt, ist dieselbe Falle wie ein Hinweis hinter dem Kuerzungsschnitt.*
- **Die Warnung waere im Runner verpufft.** Der `_Sammler` legt Chip und Warnung in dieselbe Liste,
  und `_chips_lesen` laesst alles fallen, was den Chip-Regex nicht trifft. `_warnungen_lesen()`
  holt sie heraus und haengt sie **nach** `_clean_doc_refs` an die Antwort (davor schnitte die
  Bereinigung den Dateinamen aus der Warnung wieder heraus). **Eine Warnung, die nur der Chat-Weg
  ausgibt, ist fuer /tracks keine.**
- **Kosmetik mit Schutz:** `_clean_doc_refs` entfernt jetzt auch das leere Backtick-Paar, das der
  entfernte Pfad hinterlaesst. Das Lookaround um das Backtick-Paar ist Pflicht – ohne es
  matcht „``" in „```python" und macht daraus einen kaputten Codeblock.
- **Verifiziert:** `tests/test_lauf_tmp.py` (168; Abschnitt 11 fuehrt `lauf_scope`/`aufloesen`
  WIRKLICH aus und prueft per `ast`, dass der Runner **innerhalb** der Klammer ausliefert – keine
  Zeichenkette) · `tests/test_short_tracks.py` (380) · `tests/test_doc_delivery.py` (53).
  Gegenproben beissen einzeln (1/2/1/2 FAIL). **Live auf DEV mit echtem `lauf_tmp` und echtem
  `agent.py`:** ohne Scope 0 Chips + 1 Warnung (vorher: 0 Chips, **0 Warnungen**), im Scope 1 Chip
  + 0 Warnungen, Anzeigetext ohne leere Backticks.
  **Auf ECHT noch NICHT ausgerollt.**

