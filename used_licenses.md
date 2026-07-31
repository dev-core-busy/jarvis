# Verwendete Lizenzen

Vollständiges Verzeichnis der Fremdkomponenten in Jarvis, gruppiert nach Lizenz.

**Stand:** 2026-07-31 · **Erhoben auf:** DEV (191.100.144.1), Python 3.13.5, Node 20, Go 1.24.4

---

## 1. Wie diese Liste entstanden ist – und was sie nicht leistet

Die Angaben stammen **aus den Paket-Metadaten selbst**, nicht aus einer Recherche
oder aus dem Gedächtnis:

| Ökosystem | Quelle | Verfahren |
|---|---|---|
| Python | `importlib.metadata` im venv `/opt/jarvis/venv` | `License-Expression` → Trove-`Classifier` → Freitextfeld `License`, in dieser Reihenfolge |
| Node.js | `package.json` jedes Pakets in `node_modules` | Feld `license` bzw. `licenses` |
| Go | `LICENSE`-Datei im Modul-Cache | Texterkennung am charakteristischen Wortlaut |
| Android | `gradle/libs.versions.toml` | Zuordnung über die Herausgeber (androidx/JetBrains/Square/Google) |
| System | `/usr/share/doc/<paket>/copyright` | Debian-`License:`-Feld |
| Frontend | Lizenzkopf in der ausgelieferten Datei | Sichtprüfung |

**Vier Einschränkungen, die man kennen muss:**

1. **Das ist eine Inventur, keine Rechtsberatung.** Die Liste sagt, *was* eingebunden
   ist. Ob eine Kombination zulässig ist, hängt vom Vertriebsmodell ab (SaaS auf
   eigenem Server ≠ ausgelieferte Windows-Binärdatei) und gehört vor eine juristische
   Prüfung.
2. **Erhoben wurde der Zustand auf DEV.** Dort sind Skills aktiv, die auf anderen
   Installationen fehlen – und umgekehrt. Der Python-Baum enthält deshalb mehr, als
   ein Minimal-Setup zieht (siehe die Spalte „Rolle": `transitiv` = kein direkter
   Eintrag in `requirements.txt` oder einem `skill.json`).
3. **Die Trove-Classifier sind unscharf.** „BSD License" sagt nicht, ob 2- oder
   3-Klausel; „Other/Proprietary License" ist eine Restkategorie. Wo die Metadaten
   unscharf sind, steht das hier ebenfalls unscharf – geraten wurde nicht.
4. **Optionale, nicht installierte Abhängigkeiten fehlen im Zahlenwerk.** Das betrifft
   `pyodata` und `pyrfc` aus dem SAP-Skill; sie sind unten gesondert vermerkt.

---

## 2. Die eigene Lizenz

Das Repository steht unter **Apache-2.0** (`LICENSE`, 201 Zeilen, unverändert).
Die 39 Backend-Module, 27 Skills und das gesamte Frontend fallen darunter; keiner der
Skills führt ein eigenes `license`-Feld in seinem `skill.json`.

Das ist der Bezugspunkt für alles Weitere: **Apache-2.0 ist gebefreudig, aber nicht
beliebig kombinierbar.** Zwei Richtungen sind relevant und werden unten konkret:

- Apache-2.0-Code lässt sich **nicht** in ein GPL-2.0-Projekt aufnehmen (die
  Patentklausel gilt als zusätzliche Beschränkung im Sinne von GPLv2 §6).
- Bindet man umgekehrt eine **GPL-3.0**-Bibliothek ein, ist das kombinierte Werk bei
  Weitergabe GPL-3.0 – Apache-2.0 bleibt für die eigenen Dateien bestehen, deckt die
  Weitergabe des Ganzen aber nicht mehr ab.

---

## 3. Überblick

| Lizenzfamilie | Python | Node | Go | Σ | Bewertung |
|---|---:|---:|---:|---:|---|
| MIT / BSD / ISC / 0BSD | 110 | 124 | 21 | **255** | unkritisch, Namensnennung genügt |
| Apache-2.0 | 48 | 6 | 1 | **55** | unkritisch, `NOTICE` beachten |
| PSF / MIT-CMU / BSL-1.0 / Unlicense / BlueOak | 5 | 1 | 1 | **7** | unkritisch |
| **MPL-2.0** (auch in Kombination) | 3 | – | – | **3** | dateiweises Copyleft, bei unveränderter Nutzung folgenlos |
| **LGPL-3.0** | 3 | 2 | – | **5** | Austauschbarkeit muss gewahrt bleiben |
| **GPL-2.0 / GPL-3.0** | **0** | **1** | – | **1** | nur noch die WhatsApp-Bridge – Abschnitt 4.1 |
| **proprietär** | **1** | – | – | **1** | nur noch SAP `hdbcli` – Abschnitt 4.5 |
| keine Angabe / unklar | 1 | – | **0** | **1** | nur noch `chroma-hnswlib` – in `NOTICE.md` nachgetragen |
| | **171** | **134** | **25** | **330** | |

**Zählregel:** Kombinierte Ausdrücke zählen nach ihrem **strengsten** Bestandteil –
`MPL-2.0 AND MIT` steht bei MPL, nicht bei MIT. Wahlrechte (`Apache-2.0 OR BSD-3-Clause`)
zählen dagegen bei der permissiven Variante, weil man sie wählen darf.
Das dual lizenzierte `freetype` (FTL **oder** GPL-2.0+) steht unter „Wahlrecht" und nicht
unter GPL: **die Wahl ist am 2026-07-31 getroffen** (FTL, siehe `NOTICE.md`) – siehe 4.3.

Die Go-Zahl ist bewusst *nicht* die aus `go list -m all` (193): der Modulgraph enthält
Module, die nie übersetzt werden und nicht einmal im Cache liegen. Gezählt wurde, was
`go list -deps` für `GOOS=windows` tatsächlich einbindet — 25.

Von den 171 Python-Distributionen sind **39 direkt angefordert** (`requirements.txt` +
`skill.json` — deklariert sind 41, `pyodata` und `pyrfc` sind nicht installiert), die
übrigen **132 kommen transitiv mit**. Genau dort — und nicht in der kurzen, gut
überblickbaren `requirements.txt` — saßen sämtliche GPL- und alle proprietären Pakete.
Die Spalte „Rolle" in Abschnitt 9 macht das je Paket sichtbar.

> **Aufgeräumt am 2026-07-31.** Die erste Fassung dieser Liste zählte 198
> Python-Distributionen mit 3 GPL- und 17 proprietären Paketen. 27 davon waren
> nachweislich ungenutzt und wurden entfernt (Abschnitte 4.2 und 4.4). Übrig bleiben
> **eine** GPL-Bindung (WhatsApp-Bridge, eigener Prozess) und **ein** proprietäres Paket
> (SAP `hdbcli`, ohne Alternative). Das venv schrumpfte dabei von 8,4 GB auf 2,4 GB.

---

## 4. Was Aufmerksamkeit braucht

Sieben Punkte. **4.2, 4.3, 4.4 und 4.7 sind am 2026-07-31 erledigt** und bleiben als
Begründung stehen, damit niemand sie versehentlich rückgängig macht. Von 4.6 ist der
Lizenzkopf erledigt, die Figur bleibt offen.

**Wirklich offen sind damit nur noch Entscheidungen, keine Codearbeit:** die
Avatar-Figur (4.6) und die Haltung zur Weitergabe mit WhatsApp-Bridge (4.1). Beides ist
in [`NOTICE.md`](NOTICE.md) so dokumentiert, dass eine Weitergabe heute möglich wäre.

### 4.1 GPL-3.0 in der WhatsApp-Bridge

`@whiskeysockets/libsignal-node` 2.0.1 steht unter **GPL-3.0** und ist eine
Laufzeit-Abhängigkeit von Baileys, also des Dienstes `whatsapp-bridge.service`.

Das ist die stärkste Copyleft-Bindung im gesamten Baum. Entschärfend wirkt die
Architektur: Die Bridge ist ein **eigener Node-Prozess**, der über HTTP auf
`localhost:3001` mit dem Python-Backend spricht – keine Verlinkung, kein gemeinsamer
Adressraum. Nach verbreiteter Auslegung liegt damit kein abgeleitetes Werk vor. Wer
Jarvis jedoch **als Ganzes weitergibt** (Appliance, VM-Image, Installer), verteilt die
GPL-3.0-Komponente mit und schuldet dafür den Quelltext samt Installationsinformationen.

> Praktische Folge: Die Bridge ist auf dem Echt-System ohnehin deaktiviert (siehe
> Dauer-Randbedingung „WhatsApp am Echt-System"). Wer sie dort aktiviert, aktiviert
> damit auch diese Pflicht.

### 4.2 GPL im Backend-Prozess – über `pyautogui` ✅

Drei GPL-Pakete lagen **im selben Python-Prozess** wie das Backend:

| Paket | Lizenz | Gezogen von |
|---|---|---|
| `MouseInfo` 0.1.3 | GPL-3.0-or-later | `pyautogui` |
| `PyMsgBox` 2.0.1 | GPL-3.0-or-later | `pyautogui` |
| `python3-xlib` 0.15 | GPL-2.0 | `pyautogui`, `MouseInfo` |

`pyautogui` selbst ist BSD-3-Clause und steht als **Kern-Abhängigkeit** in
`requirements.txt`. Seine Abhängigkeiten sind es nicht. Anders als bei der Bridge gibt es
hier **keine Prozessgrenze** – es wäre ein `import` im selben Interpreter.
`python3-xlib` unter GPL-2.0 ist der heiklere Fall, weil GPL-2.0 und Apache-2.0 als
unvereinbar gelten.

**Der Punkt ist aber ein anderer: `pyautogui` wird nirgends benutzt.** Eine Suche über
das gesamte Repository findet genau einen Treffer – die Zeile `pyautogui==0.9.54` in
`requirements.txt` selbst. Kein `import`, in keinem Backend-Modul und in keinem Skill.
Die Desktop-Steuerung läuft vollständig über **`xdotool`** als Unterprozess
(`backend/tools/desktop.py`, `skills/browser_control`, `skills/claude_bridge`) – also
über eine Prozessgrenze, mit der GPL-Frage gar nicht erst.

Damit ist die gesamte GPL-Berührung auf der Python-Seite ein **Altbestand aus der
Anfangszeit**, den `pyautogui` ohne Gegenwert mitbringt. Sein Rattenschwanz umfasst neun
Pakete:

| Paket | Lizenz | Bemerkung |
|---|---|---|
| `PyAutoGUI` 0.9.54 | BSD | die einzige *deklarierte* Zeile |
| `MouseInfo` 0.1.3 | **GPL-3.0+** | Koordinatenanzeige, ungenutzt |
| `PyMsgBox` 2.0.1 | **GPL-3.0+** | Dialogboxen, ungenutzt |
| `python3-xlib` 0.15 | **GPL-2.0** | X11-Anbindung, ungenutzt |
| `PyGetWindow`, `PyRect`, `PyScreeze`, `pytweening`, `pyperclip` | BSD/MIT | unkritisch |

`pyperclip` ist ebenfalls ungenutzt – die Zwischenablage läuft über `xclip`
(`backend/tools/clipboard.py`), nicht über Python. Die einzige Erwähnung steht in
`skills/claude_bridge/skill.md`, einer veralteten Beschreibung; der tatsächliche Code in
`claude_bridge/main.py` ruft `xclip` auf.

> ### ✅ Erledigt am 2026-07-31 (DEV **und** ECHT)
> `pyautogui` ist aus `requirements.txt` entfernt, die neun Pakete sind auf DEV **und auf
> ECHT** deinstalliert. **Damit ist die GPL-Berührung auf der Python-Seite bei null** –
> auf ECHT nachgezählt: 154 Distributionen, davon **0 GPL und 0 proprietäre**.
> Nachgeprüft: `import backend.main` läuft, Dienst nach Neustart aktiv, Portal und
> Einstellungen HTTP 200. Die Zeile in `requirements.txt` ist durch einen Kommentar
> ersetzt, der erklärt, warum sie nicht zurückkommen darf.

Ein Streichen der Zeile aus `requirements.txt` samt
`pip uninstall pyautogui mouseinfo pymsgbox python3-xlib pygetwindow pyrect pyscreeze pytweening pyperclip`
entfernt die GPL-Bindung auf der Python-Seite **vollständig**. `Pillow` bleibt dabei
unangetastet, es steht eigenständig in `requirements.txt`.

### 4.3 FreeType im Windows-Client: Lizenzwahl erforderlich ✅

`github.com/golang/freetype` (über Fyne gebunden) ist **dual lizenziert** und verlangt
eine ausdrückliche Wahl:

> „Use of the Freetype-Go software is subject to your choice of exactly one of the
> following two licenses: The FreeType License … or the GNU General Public License
> (GPL), version 2 or later."

Wer nicht wählt, wählt nicht implizit die harmlosere Variante. Für eine ausgelieferte
`.exe` ist die **FreeType License (FTL)** die passende Wahl – sie ist BSD-artig, verlangt
aber einen Hinweis in der Dokumentation („credit").

> ### ✅ Erledigt am 2026-07-31
> Die Wahl ist in [`NOTICE.md`](NOTICE.md) Abschnitt 1 **ausdrücklich getroffen** (FTL,
> nicht GPL-2.0+) und der geforderte Credit dort formuliert. `lizenzen_erheben.py` erkennt
> dual lizenzierte Module jetzt am Wortlaut („your choice of exactly one") und schreibt
> **„Wahlrecht – getroffen in NOTICE.md"** statt „unbekannt" – sonst taucht das Modul in
> jeder Inventur wieder als ungeklärt auf und wird zum dritten Mal recherchiert.

### 4.4 17 proprietäre NVIDIA-Pakete auf einer Maschine ohne GPU ✅

Über `sentence-transformers` → `transformers` → `torch` zog der Wissens-Index den
kompletten CUDA-Stack: 16 `nvidia-*`-Pakete plus `cuda-bindings`, sämtlich unter
NVIDIA-eigenen Lizenzen (`Other/Proprietary License`, `LicenseRef-NVIDIA-*`).

Auf dieser VM ist das **doppelt sinnlos**: Es gibt keine GPU, und laut `CLAUDE.md` fehlt
der CPU sogar SSE4.2 (deshalb `numpy<2.1`). Die Pakete werden nie geladen. Sie belegen
aber mehrere Gigabyte und bringen proprietäre Lizenztexte in die Inventur, die man bei
einer Weitergabe des Images mitverteilen würde.

> ### ✅ Erledigt am 2026-07-31
> `torch` läuft jetzt als CPU-Variante, alle 18 CUDA-Pakete (17 proprietäre plus
> `triton`) sind entfernt. **Das venv schrumpfte von 8,4 GB auf 2,4 GB.**
>
> ```bash
> pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.10.0+cpu"
> pip uninstall -y cuda-bindings cuda-pathfinder triton nvidia-*-cu12
> ```
>
> **Das Suffix `+cpu` ist Pflicht.** Mit `torch==2.10.0` meldet pip
> „Requirement already satisfied" und tut nichts – das installierte `2.10.0+cu128`
> erfüllt die Bedingung ja. Genau darauf bin ich beim ersten Versuch hereingefallen.
>
> **Ein Reindex war NICHT nötig, entgegen der ursprünglichen Annahme hier.** Der
> Gegenbeweis ist einfach: Die Einbettung desselben Satzes hat vor und nach dem Wechsel
> denselben SHA (`ad10992e7ec1e81f`, 384 Dimensionen, identische Gleitkommawerte). Das
> ist auch der Grund – `torch.cuda.is_available()` war schon vorher `False`, gerechnet
> wurde also die ganze Zeit auf denselben CPU-Kernen. Das CUDA-Rad brachte nur
> Bibliotheken mit, die nie geladen wurden.
>
> Gegengeprüft mit einem echten Suchlauf über das Wissens-Werkzeug: 4 Treffer aus dem
> bestehenden Index, warme Suche 17–20 ms, Dienst nach Neustart aktiv.
>
> **Für eine Neuinstallation** steht der Befehl jetzt als Kommentar in
> `requirements.txt` – ohne ihn zieht `sentence-transformers` das CUDA-Rad wieder herein.
>
> **Auf ECHT** war der große CUDA-Stack schon seit dem 2026-07-19 draußen (torch
> 2.12.0+cpu). Übrig geblieben waren drei Waisen aus jener Aktion – `cuda-bindings`,
> `cuda-pathfinder`, `cuda-toolkit` –, die niemand mehr anforderte; am 2026-07-31 mit
> entfernt. Merke: Ein `pip uninstall torch` räumt seine Abhängigkeiten **nicht** mit ab,
> die bleiben als Waisen liegen und tauchen in jeder Lizenzinventur wieder auf.

### 4.5 SAP: proprietär und teils gar nicht installiert

- `hdbcli` 2.29.25 – **proprietär**, SAP-eigene Lizenzbedingungen, direkte Abhängigkeit
  des `sap`-Skills. Nutzung setzt eine gültige SAP-Lizenz voraus.
- `pyodata`, `pyrfc` – als `optional_dependencies` deklariert, auf DEV **nicht
  installiert** und deshalb in den Tabellen unten nicht enthalten. `pyrfc` ist selbst
  Apache-2.0, benötigt zur Übersetzung aber das **NetWeaver RFC SDK**, das nur über ein
  SAP-Kundenkonto zu beziehen ist.

### 4.6 Clippy: die Figur ist nicht mitlizenziert ⚠

`frontend/vendor/clippy/` enthält zwei getrennte Dinge, und nur eines davon ist frei:

| Bestandteil | Lage |
|---|---|
| `clippy.min.js`, `clippy.css` | clippy.js von Smore Inc., **MIT** – die Datei enthält allerdings **keinen Lizenzkopf** |
| `jquery-3.7.1.min.js` | **MIT**, Kopf vorhanden |
| `agents/Clippy/map.png`, `sounds-*.js` | **Sprite-Grafik und Klänge des Office-Assistenten** |

Die MIT-Lizenz der Bibliothek deckt deren Quelltext ab, **nicht die Figur**. Das
Erscheinungsbild von „Clippit" ist Microsoft-Werk. Für den internen Einsatz ist das
regelmäßig unproblematisch, für ein vermarktetes Produkt mit Außenwirkung
(jarvis-ai.info zeigt den Avatar) ist es eine offene Frage. Der Avatar-Skill unterstützt
eigene Sprites – `skills/avatar/AVATAR-DESIGN.md` beschreibt den Weg dahin, und das ist
der saubere Ausweg.

> ### ✅ Teilweise erledigt am 2026-07-31
> `clippy.min.js` und `clippy.css` haben jetzt einen Lizenzkopf – Inhalt unverändert
> (md5 der ursprünglichen Bytes geprüft), nur vorangestellt. Der Kopf nennt die
> MIT-Lizenz **und** sagt ausdrücklich, dass sie die Figur NICHT abdeckt.
>
> **Offen bleibt die Figur selbst** – das ist eine Entscheidung, keine Codearbeit.

### 4.7 Zwei Pakete ohne Lizenzangabe ✅

- `chroma-hnswlib` 0.7.6 (Python, über `chromadb`) – **keine Lizenz in den Metadaten**.
  Das Projekt selbst ist Apache-2.0, das Rad deklariert es nur nicht.
- `github.com/jsummers/gobmp` – die **angeheftete Fassung** (`v0.0.0-20151104…`) lieferte
  keine `LICENSE`-Datei aus; erst spätere Fassungen enthalten `COPYING.txt` mit MIT.

> ### ✅ Erledigt am 2026-07-31
> `gobmp` ist auf `v0.0.0-20230614200233` angehoben; der Windows-Client baut damit
> unverändert – echter mingw-Cross-Build gegen den Ausgangsstand verglichen: gleiche
> Größe (25.687.040 Byte), 230 abweichende Byte aus dem Modulpfad im Binärabbild.
> `chroma-hnswlib` ist als Apache-2.0 in `NOTICE.md` Abschnitt 4 nachgetragen – das
> Projekt deklariert es nur im Rad nicht.
>
> **Dabei fiel ein Fehler im eigenen Erkenner auf:** `gobmp` galt auch nach dem Anheben
> noch als „keine LICENSE-Datei“, weil die Namensliste in `lizenzen_erheben.py`
> `COPYING.txt` nicht enthielt – die Datei lag die ganze Zeit daneben. Wer künftig einen
> solchen Befund sieht, prüft **zuerst die Namensliste** gegen den Modulordner, bevor er
> das Projekt verdächtigt.

---

## 5. Systempakete (Debian 13, außerhalb der Anwendung)

Eigenständige Prozesse bzw. Werkzeuge – kein Linken, keine Einbindung in den
Jarvis-Adressraum. Copyleft wirkt hier nicht auf den eigenen Code.

| Lizenz | Pakete |
|---|---|
| **MPL-2.0** | `novnc` 1.6.0, `libreoffice-writer` 25.2.3 (+ `-calc`, `-impress`) |
| **LGPL-2.1+ / LGPL-3** | `ffmpeg` 7.1.5, `websockify` |
| **GPL-2.0 / GPL-2+** | `x11vnc`, `openbox` 3.6.1, `lightdm`, `poppler-utils` (GPL-2 oder GPL-3) |
| Apache-2.0 | `tesseract-ocr` 5.5.0 |
| BSD-3-Clause | `cmake` |
| MIT | `libboost-all-dev` |

`x11vnc`, `openbox` und `lightdm` laufen als getrennte Prozesse; `poppler-utils` und
`tesseract` werden über die Kommandozeile aufgerufen. LibreOffice wird vom Office-Skill
per `soffice --convert-to pdf` gestartet – ebenfalls Prozessgrenze.

---

## 6. Frontend – ausgelieferte Fremddateien

| Datei | Komponente | Lizenz | Lizenzkopf vorhanden |
|---|---|---|---|
| `frontend/js/vendor/chart.umd.min.js` | Chart.js 4.4.9 | MIT | ja |
| `frontend/vendor/clippy/jquery-3.7.1.min.js` | jQuery 3.7.1 | MIT | ja |
| `frontend/vendor/clippy/clippy.min.js` | clippy.js (Smore Inc.) | MIT | **nein** |
| `frontend/vendor/clippy/clippy.css` | clippy.js | MIT | **nein** |
| `frontend/vendor/clippy/agents/Clippy/*` | Sprite + Klänge | **ungeklärt**, siehe 4.6 | – |
| (Server) `/usr/share/novnc` | noVNC 1.6.0 | MPL-2.0 | ja |

Das Frontend bindet **keine externen Quellen zur Laufzeit** ein. Die einzige Ausnahme
– ein `<link>` auf `fonts.googleapis.com` in `settings.html` – wurde am 2026-07-28
entfernt; laut `CLAUDE.md` soll das nicht zurückkommen.

---

## 7. Android-App (`android/`)

Alle Abhängigkeiten stammen aus dem AndroidX-/Jetpack-Ökosystem, von JetBrains oder von
Square und stehen einheitlich unter **Apache-2.0**:

`androidx.appcompat`, `androidx.core:core-ktx`, `androidx.activity:activity-compose`,
`androidx.compose:compose-bom` (ui, ui-graphics, ui-tooling, ui-tooling-preview,
material3, material-icons-extended), `androidx.navigation:navigation-compose`,
`androidx.lifecycle` (viewmodel-compose, runtime-ktx), `androidx.datastore:datastore-preferences`,
`androidx.security:security-crypto`, `androidx.hilt:hilt-navigation-compose`,
`com.google.dagger:hilt-android` (+ compiler), `com.squareup.okhttp3:okhttp` (+ logging-interceptor),
`org.jetbrains.kotlinx:kotlinx-coroutines-android`, `org.jetbrains.kotlinx:kotlinx-serialization-json`,
Kotlin-Compiler und -Plugins.

Anders als bei Python und Node wurde hier **nicht gegen installierte Artefakte geprüft**,
sondern gegen die Deklaration in `libs.versions.toml` – ein Gradle-Auflauf war nicht Teil
dieser Erhebung. Die Einheitlichkeit der Herausgeber macht das Ergebnis dennoch belastbar.

---

## 8. Eigene Skills

Alle 27 Skills unter `skills/` sind Jarvis-eigener Quelltext und fallen unter die
**Apache-2.0** des Repositorys. Keiner führt ein eigenes `license`-Feld:

`agent_autonomy_kit`, `agent_orchestrator`, `avatar`, `branding`, `browser_control`,
`claude_bridge`, `coding_agent`, `cognitive_evolution`, `confluence`, `cron`, `desktop`,
`example_skill`, `filesystem`, `google`, `jarvis-vision`, `jira`, `knowledge`,
`kundenverwaltung`, `memory`, `office`, `sap`, `screenshot`, `shell`, `support_assistant`,
`telegram`, `vision`, `whatsapp`

Sieben davon ziehen zusätzliche Fremdpakete; deren Lizenzen stehen in den Tabellen unten
in der Spalte „Rolle":

| Skill | Zusätzliche Pakete |
|---|---|
| `google` | `google-api-python-client`, `google-auth-httplib2`, `google-auth-oauthlib` |
| `knowledge` | `pdfplumber`, `python-docx`, optional `faster-whisper` |
| `office` | `python-docx`, `openpyxl`, `python-pptx` + LibreOffice (apt) |
| `sap` | `hdbcli` (proprietär), optional `pyodata`, `pyrfc` |
| `telegram` | `python-telegram-bot` (LGPL-3.0) |
| `vision` | `face-recognition`, `opencv-python-headless`, `setuptools` + `cmake`, `libboost-all-dev` (apt) |
| `whatsapp` | `faster-whisper`, `httpx` |

---

## 9. Python – Backend, Skills, Wissenssuche (171 Distributionen)

### MIT (62)

| Paket | Version | Rolle |
|---|---|---|
| `annotated-doc` | 0.0.4 | transitiv |
| `annotated-types` | 0.7.0 | transitiv |
| `anthropic` | 0.83.0 | Kern |
| `anyio` | 4.12.1 | transitiv |
| `APScheduler` | 3.11.2 | Kern |
| `attrs` | 25.4.0 | transitiv |
| `backoff` | 2.2.1 | transitiv |
| `build` | 1.4.0 | transitiv |
| `cffi` | 2.0.0 | transitiv |
| `charset-normalizer` | 3.4.4 | transitiv |
| `ctranslate2` | 4.7.1 | transitiv |
| `docstring_parser` | 0.17.0 | transitiv |
| `durationpy` | 0.10 | transitiv |
| `et_xmlfile` | 2.0.0 | transitiv |
| `face-recognition` | 1.3.0 | Skill `vision` |
| `face_recognition_models` | 0.3.0 | transitiv |
| `fastapi` | 0.115.6 | Kern |
| `faster-whisper` | 1.2.1 | Skill `knowledge` (optional), Skill `whatsapp` |
| `filelock` | 3.24.3 | transitiv |
| `h11` | 0.16.0 | transitiv |
| `httplib2` | 0.31.2 | transitiv |
| `httptools` | 0.7.1 | transitiv |
| `httpx-sse` | 0.4.3 | transitiv |
| `jiter` | 0.13.0 | transitiv |
| `jsonschema` | 4.26.0 | transitiv |
| `jsonschema-specifications` | 2025.9.1 | transitiv |
| `markdown-it-py` | 4.0.0 | transitiv |
| `mcp` | 1.25.0 | Kern |
| `mdurl` | 0.1.2 | transitiv |
| `mmh3` | 5.2.1 | transitiv |
| `onnxruntime` | 1.24.2 | transitiv |
| `openpyxl` | 3.1.5 | Kern, Skill `office` |
| `pdf2image` | 1.17.0 | Kern |
| `pdfminer.six` | 20251230 | transitiv |
| `pdfplumber` | 0.11.9 | Kern, Skill `knowledge` |
| `pip` | 25.1.1 | transitiv |
| `posthog` | 7.9.12 | transitiv |
| `pydantic` | 2.12.5 | transitiv |
| `pydantic-settings` | 2.13.1 | transitiv |
| `pydantic_core` | 2.41.5 | transitiv |
| `PyJWT` | 2.12.1 | transitiv |
| `pyotp` | 2.9.0 | Kern |
| `pyparsing` | 3.3.2 | transitiv |
| `pyproject_hooks` | 1.2.0 | transitiv |
| `python-docx` | 1.2.0 | Kern, Skill `knowledge`, Skill `office` |
| `python-pam` | 2.0.2 | Kern |
| `python-pptx` | 1.0.2 | Kern, Skill `office` |
| `PyYAML` | 6.0.3 | transitiv |
| `referencing` | 0.37.0 | transitiv |
| `rich` | 14.3.3 | transitiv |
| `rpds-py` | 0.30.0 | transitiv |
| `setuptools` | 74.1.3 | Skill `vision` |
| `six` | 1.17.0 | Kern |
| `tabulate` | 0.10.0 | transitiv |
| `typer` | 0.24.1 | transitiv |
| `typer-slim` | 0.24.0 | transitiv |
| `typing-inspection` | 0.4.2 | transitiv |
| `tzlocal` | 5.3.1 | transitiv |
| `urllib3` | 2.6.3 | transitiv |
| `watchfiles` | 1.1.1 | transitiv |
| `WsgiDAV` | 4.3.3 | Kern |
| `zipp` | 3.23.0 | transitiv |

### Apache-2.0 (47)

| Paket | Version | Rolle |
|---|---|---|
| `aiosignal` | 1.4.0 | transitiv |
| `bcrypt` | 5.0.0 | transitiv |
| `chromadb` | 1.5.7 | transitiv |
| `distro` | 1.9.0 | transitiv |
| `flatbuffers` | 25.12.19 | transitiv |
| `frozenlist` | 1.8.0 | transitiv |
| `google-api-core` | 2.30.0 | transitiv |
| `google-api-python-client` | 2.190.0 | Skill `google` |
| `google-auth` | 2.49.0.dev0 | transitiv |
| `google-auth-httplib2` | 0.3.0 | Skill `google` |
| `google-auth-oauthlib` | 1.3.0 | Skill `google` |
| `google-genai` | 1.72.0 | Kern |
| `googleapis-common-protos` | 1.72.0 | transitiv |
| `grpcio` | 1.78.0 | transitiv |
| `hf-xet` | 1.2.0 | transitiv |
| `huggingface_hub` | 0.36.2 | transitiv |
| `importlib_metadata` | 8.7.1 | transitiv |
| `importlib_resources` | 6.5.2 | transitiv |
| `json5` | 0.13.0 | transitiv |
| `kubernetes` | 35.0.0 | transitiv |
| `multidict` | 6.7.1 | transitiv |
| `opencv-python-headless` | 4.13.0.92 | Skill `vision` |
| `opentelemetry-api` | 1.40.0 | transitiv |
| `opentelemetry-exporter-otlp-proto-common` | 1.40.0 | transitiv |
| `opentelemetry-exporter-otlp-proto-grpc` | 1.40.0 | transitiv |
| `opentelemetry-instrumentation` | 0.61b0 | transitiv |
| `opentelemetry-instrumentation-asgi` | 0.61b0 | transitiv |
| `opentelemetry-instrumentation-fastapi` | 0.61b0 | transitiv |
| `opentelemetry-proto` | 1.40.0 | transitiv |
| `opentelemetry-sdk` | 1.40.0 | transitiv |
| `opentelemetry-semantic-conventions` | 0.61b0 | transitiv |
| `opentelemetry-util-http` | 0.61b0 | transitiv |
| `overrides` | 7.7.0 | transitiv |
| `propcache` | 0.4.1 | transitiv |
| `proto-plus` | 1.27.1 | transitiv |
| `PyPika` | 0.51.1 | transitiv |
| `pytesseract` | 0.3.13 | Kern |
| `python-multipart` | 0.0.20 | Kern |
| `requests` | 2.32.5 | transitiv |
| `safetensors` | 0.7.0 | transitiv |
| `sentence-transformers` | 3.4.1 | Kern |
| `tenacity` | 9.1.4 | transitiv |
| `tokenizers` | 0.22.2 | transitiv |
| `transformers` | 4.57.6 | transitiv |
| `watchdog` | 6.0.0 | Kern |
| `websocket-client` | 1.9.0 | transitiv |
| `yarl` | 1.23.0 | transitiv |

### BSD (19)

| Paket | Version | Rolle |
|---|---|---|
| `asgiref` | 3.11.1 | transitiv |
| `httpx` | 0.28.1 | Skill `whatsapp` |
| `Jinja2` | 3.1.6 | transitiv |
| `mpmath` | 1.3.0 | transitiv |
| `numpy` | 2.0.2 | Kern |
| `psutil` | 6.1.1 | Kern |
| `pyasn1_modules` | 0.4.2 | transitiv |
| `pybase64` | 1.4.3 | transitiv |
| `Pygments` | 2.19.2 | transitiv |
| `python-dotenv` | 1.0.1 | Kern |
| `requests-oauthlib` | 2.0.0 | transitiv |
| `scipy` | 1.17.1 | transitiv |
| `starlette` | 0.41.3 | transitiv |
| `sympy` | 1.14.0 | transitiv |
| `threadpoolctl` | 3.6.0 | transitiv |
| `uvicorn` | 0.34.0 | Kern |
| `websockets` | 14.2 | Kern |
| `wrapt` | 1.17.3 | transitiv |
| `xlsxwriter` | 3.2.9 | transitiv |

### BSD-3-Clause (17)

| Paket | Version | Rolle |
|---|---|---|
| `av` | 16.1.0 | transitiv |
| `click` | 8.3.1 | transitiv |
| `fsspec` | 2026.2.0 | transitiv |
| `httpcore` | 1.0.9 | transitiv |
| `idna` | 3.11 | transitiv |
| `joblib` | 1.5.3 | transitiv |
| `lxml` | 6.0.2 | transitiv |
| `MarkupSafe` | 3.0.3 | transitiv |
| `networkx` | 3.6.1 | transitiv |
| `oauthlib` | 3.3.1 | transitiv |
| `protobuf` | 6.33.5 | transitiv |
| `pybind11` | 3.0.2 | transitiv |
| `pycparser` | 3.0 | transitiv |
| `pypdf` | 6.11.0 | transitiv |
| `scikit-learn` | 1.8.0 | transitiv |
| `sse-starlette` | 3.0.3 | Kern |
| `torch` | 2.10.0+cpu | transitiv |

### LGPL-3.0 (3)

| Paket | Version | Rolle |
|---|---|---|
| `edge-tts` | 7.2.7 | Kern |
| `ldap3` | 2.9.1 | Kern |
| `python-telegram-bot` | 22.8 | Skill `telegram` |

### PSF-2.0 (3)

| Paket | Version | Rolle |
|---|---|---|
| `aiohappyeyeballs` | 2.6.1 | transitiv |
| `defusedxml` | 0.7.1 | transitiv |
| `typing_extensions` | 4.15.0 | transitiv |

### Apache-2.0 OR BSD-3-Clause (2)

| Paket | Version | Rolle |
|---|---|---|
| `cryptography` | 46.0.5 | transitiv |
| `uritemplate` | 4.2.0 | transitiv |

### MIT OR Apache-2.0 (2)

| Paket | Version | Rolle |
|---|---|---|
| `sniffio` | 1.3.1 | transitiv |
| `uvloop` | 0.22.1 | transitiv |

### Apache-2.0 AND CNRI-Python (1)

| Paket | Version | Rolle |
|---|---|---|
| `regex` | 2026.2.28 | transitiv |

### Apache-2.0 AND MIT (1)

| Paket | Version | Rolle |
|---|---|---|
| `aiohttp` | 3.13.3 | transitiv |

### Apache-2.0 OR BSD-2-Clause (1)

| Paket | Version | Rolle |
|---|---|---|
| `packaging` | 26.0 | transitiv |

### BSD (+ Zusatzbedingung) (1)

| Paket | Version | Rolle |
|---|---|---|
| `qrcode` | 8.2 | Kern |

### BSD OR Apache-2.0 (1)

| Paket | Version | Rolle |
|---|---|---|
| `python-dateutil` | 2.9.0.post0 | transitiv |

### BSD-2-Clause (1)

| Paket | Version | Rolle |
|---|---|---|
| `pyasn1` | 0.6.2 | transitiv |

### BSD-3-Clause AND Apache-2.0 (1)

| Paket | Version | Rolle |
|---|---|---|
| `pypdfium2` | 5.5.0 | transitiv |

### BSL-1.0 (1)

| Paket | Version | Rolle |
|---|---|---|
| `dlib` | 20.0.0 | transitiv |

### ISC (1)

| Paket | Version | Rolle |
|---|---|---|
| `shellingham` | 1.5.4 | transitiv |

### KEINE ANGABE (1)

| Paket | Version | Rolle |
|---|---|---|
| `chroma-hnswlib` | 0.7.6 | transitiv |

### MIT AND BSD-3-Clause (1)

| Paket | Version | Rolle |
|---|---|---|
| `faiss-cpu` | 1.13.2 | Kern |

### MIT-CMU (1)

| Paket | Version | Rolle |
|---|---|---|
| `pillow` | 11.1.0 | Kern |

### MPL-2.0 (1)

| Paket | Version | Rolle |
|---|---|---|
| `certifi` | 2026.1.4 | transitiv |

### MPL-2.0 AND (Apache-2.0 OR MIT) (1)

| Paket | Version | Rolle |
|---|---|---|
| `orjson` | 3.11.7 | transitiv |

### MPL-2.0 AND MIT (1)

| Paket | Version | Rolle |
|---|---|---|
| `tqdm` | 4.67.3 | transitiv |

### proprietär (1)

| Paket | Version | Rolle |
|---|---|---|
| `hdbcli` | 2.29.25 | Skill `sap` |


## 10. Node.js – WhatsApp-Bridge (134 Pakete)

### MIT (102)

- `@borewit/text-codec` 0.2.1
- `@cacheable/memory` 2.0.7
- `@cacheable/node-cache` 1.7.6
- `@cacheable/utils` 2.3.4
- `@img/colour` 1.0.0
- `@keyv/bigmap` 1.3.1
- `@keyv/serialize` 1.1.1
- `@pinojs/redact` 0.4.0
- `@tokenizer/inflate` 0.4.1
- `@tokenizer/token` 0.3.0
- `@types/long` 4.0.2
- `@types/node` 25.3.0
- `@whiskeysockets/baileys` 7.0.0-rc.9
- `accepts` 2.0.0
- `async-mutex` 0.5.0
- `atomic-sleep` 1.0.0
- `body-parser` 2.2.2
- `bytes` 3.1.2
- `cacheable` 2.3.2
- `call-bind-apply-helpers` 1.0.2
- `call-bound` 1.0.4
- `content-disposition` 1.0.1
- `content-type` 1.0.5
- `cookie` 0.7.2
- `cookie-signature` 1.2.2
- `curve25519-js` 0.0.4
- `debug` 4.4.3
- `depd` 2.0.0
- `dunder-proto` 1.0.1
- `ee-first` 1.1.1
- `encodeurl` 2.0.0
- `es-define-property` 1.0.1
- `es-errors` 1.3.0
- `es-object-atoms` 1.1.1
- `escape-html` 1.0.3
- `etag` 1.8.1
- `eventemitter3` 5.0.4
- `express` 5.2.1
- `file-type` 21.3.0
- `finalhandler` 2.1.1
- `forwarded` 0.2.0
- `fresh` 2.0.0
- `function-bind` 1.1.2
- `get-intrinsic` 1.3.0
- `get-proto` 1.0.1
- `gopd` 1.2.0
- `has-symbols` 1.1.0
- `hashery` 1.5.0
- `hasown` 2.0.2
- `hookified` 1.15.1
- `http-errors` 2.0.1
- `iconv-lite` 0.7.2
- `ipaddr.js` 1.9.1
- `is-promise` 4.0.0
- `keyv` 5.6.0
- `math-intrinsics` 1.1.0
- `media-typer` 1.1.0
- `merge-descriptors` 2.0.0
- `mime-db` 1.54.0
- `mime-types` 3.0.2
- `ms` 2.1.3
- `music-metadata` 11.12.1
- `negotiator` 1.0.0
- `object-inspect` 1.13.4
- `on-exit-leak-free` 2.1.2
- `on-finished` 2.4.1
- `p-queue` 9.1.0
- `p-timeout` 7.0.1
- `parseurl` 1.3.3
- `path-to-regexp` 8.3.0
- `pino` 10.3.1
- `pino-abstract-transport` 3.0.0
- `pino-std-serializers` 7.1.0
- `process-warning` 5.0.0
- `proxy-addr` 2.0.7
- `qified` 0.6.0
- `quick-format-unescaped` 4.0.4
- `range-parser` 1.2.1
- `raw-body` 3.0.2
- `real-require` 0.2.0
- `router` 2.2.0
- `safe-stable-stringify` 2.5.0
- `safer-buffer` 2.1.2
- `send` 1.2.1
- `serve-static` 2.2.1
- `side-channel` 1.1.0
- `side-channel-list` 1.0.0
- `side-channel-map` 1.0.1
- `side-channel-weakmap` 1.0.2
- `sonic-boom` 4.2.1
- `statuses` 2.0.2
- `strtok3` 10.3.4
- `thread-stream` 4.0.0
- `toidentifier` 1.0.1
- `token-types` 6.1.2
- `type-is` 2.0.1
- `uint8array-extras` 1.5.0
- `undici-types` 7.18.2
- `unpipe` 1.0.0
- `vary` 1.1.2
- `win-guid` 0.2.1
- `ws` 8.19.0

### BSD-3-Clause (15)

- `@hapi/boom` 9.1.4
- `@hapi/hoek` 9.3.0
- `@protobufjs/aspromise` 1.1.2
- `@protobufjs/base64` 1.1.2
- `@protobufjs/codegen` 2.0.4
- `@protobufjs/eventemitter` 1.1.0
- `@protobufjs/fetch` 1.1.0
- `@protobufjs/float` 1.0.2
- `@protobufjs/inquire` 1.1.0
- `@protobufjs/path` 1.1.2
- `@protobufjs/pool` 1.1.0
- `@protobufjs/utf8` 1.1.0
- `ieee754` 1.2.1
- `protobufjs` 7.5.4
- `qs` 6.15.0

### Apache-2.0 (6)

- `@img/sharp-linux-x64` 0.34.5
- `@img/sharp-linuxmusl-x64` 0.34.5
- `detect-libc` 2.1.2
- `long` 5.3.2
- `qrcode-terminal` 0.12.0
- `sharp` 0.34.5

### ISC (6)

- `inherits` 2.0.4
- `once` 1.4.0
- `semver` 7.7.4
- `setprototypeof` 1.2.0
- `split2` 4.2.0
- `wrappy` 1.0.2

### LGPL-3.0-or-later (2)

- `@img/sharp-libvips-linux-x64` 1.2.4
- `@img/sharp-libvips-linuxmusl-x64` 1.2.4

### 0BSD (1)

- `tslib` 2.8.1

### BlueOak-1.0.0 (1)

- `lru-cache` 11.2.6

### GPL-3.0 (1)

- `@whiskeysockets/libsignal-node` 2.0.1


## 11. Go – Windows-Client (25 gebundene Module)

### BSD-3-Clause (12)

- `fyne.io/fyne/v2` v2.5.4
- `github.com/fsnotify/fsnotify` v1.7.0
- `github.com/fyne-io/image` v0.0.0-20220602074514-4956b0afb3d2
- `github.com/go-gl/glfw/v3.3/glfw` v0.0.0-20240506104042-037f3cc74f2a
- `github.com/go-text/render` v0.2.0
- `github.com/go-text/typesetting` v0.2.0
- `github.com/srwiley/oksvg` v0.0.0-20221011165216-be6e8873101c
- `github.com/srwiley/rasterx` v0.0.0-20220730225603-2ab79fcdd4ef
- `golang.org/x/image` v0.18.0
- `golang.org/x/net` v0.25.0
- `golang.org/x/sys` v0.20.0
- `golang.org/x/text` v0.16.0

### MIT (8)

- `github.com/BurntSushi/toml` v1.4.0
- `github.com/fogleman/gg` v1.3.0
- `github.com/fredbi/uri` v1.1.0
- `github.com/go-gl/gl` v0.0.0-20211210172815-726fda9656d6
- `github.com/jeandeaual/go-locale` v0.0.0-20240223122105-ce5225dcaa49
- `github.com/jsummers/gobmp` v0.0.0-20230614200233-a9de23ed2e25
- `github.com/nicksnyder/go-i18n/v2` v2.4.0
- `github.com/yuin/goldmark` v1.7.1

### Apache-2.0 (1)

- `fyne.io/systray` v1.11.0

### BSD-2-Clause (1)

- `github.com/gorilla/websocket` v1.5.3

### ISC (1)

- `github.com/nfnt/resize` v0.0.0-20180221191011-83c6a9932646

### Unlicense (1)

- `github.com/gen2brain/malgo` v0.11.24

### Wahlrecht – getroffen in NOTICE.md (1)

- `github.com/golang/freetype` v0.0.0-20170609003504-e2365dfdc4a0

---

## 12. Liste erneuern

Die Abschnitte 9–11 sind **erzeugt**, nicht gepflegt:

```bash
python3 tests/tools/lizenzen_erheben.py            # DEV ist die Vorgabe
python3 tests/tools/lizenzen_erheben.py --host root@191.100.130.62   # gegen ECHT
```

Das Skript schreibt die drei Abschnitte nach `/tmp/tabellen.md`; von dort ersetzen sie
alles ab `## 9.` in dieser Datei. Die Abschnitte 1–8 sind Handarbeit und müssen
mitgelesen werden, wenn sich etwas Grundsätzliches ändert.

**Warum das Skript über SSH arbeitet:** `venv` und `node_modules` liegen auf dem Server,
nicht im Repo. Eine Erhebung allein aus `requirements.txt` würde 42 direkte
Abhängigkeiten zeigen statt der 198 tatsächlich installierten Distributionen – und genau
die transitiven sind es, in denen die GPL- und die proprietären Pakete stecken.

**Die Zahlen unterscheiden sich je Server.** Auf einem System mit weniger aktiven Skills
fehlen die entsprechenden Blöcke. Wer die Liste für eine Weitergabe braucht, erhebt sie
auf **genau der Installation**, die weitergegeben wird.
