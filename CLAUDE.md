# Jarvis – AI Desktop Agent

## Projekt
Autonomer KI-Agent auf einem Linux-Server (Debian 13) mit Web-Frontend, Desktop-Steuerung via VNC und WhatsApp-Integration.

## Server & Deployment
- **App-Server:** root@191.100.144.1 (Debian 13), SSH: `ssh -i /c/users/bender/.ssh/id_rsa root@191.100.144.1`
- **Ein Pfad:** `/opt/jarvis/` (systemd Service, WorkingDirectory) – der frühere Zweitpfad `/home/jarvis/jarvis/` wurde 2026-07-17 abgeschafft (war totes Kopier-Ziel).
- **Deploy:** Lokal schreiben + `scp` (keine Heredocs ueber SSH – Quoting-Probleme mit f-strings)
  - HINWEIS: Auf dem Server wird NICHT committet → der Git-HEAD dort bleibt alt und ist KEIN Versionsindikator. Massgeblich ist der Datei-Inhalt (md5-Vergleich), nicht `git rev-parse`.
- **Landing-Page:** `jarvis-ai.info` ist ein SEPARATER Host (89.110.149.134, nginx) – NICHT der App-Server.
  - Quelle der Wahrheit ist die live deployte Datei; Repo-Kopie `docs/landing-page/index.html` driftet und muss manuell nachgezogen werden.
  - Deploy via `windows-app-go/build.sh` – per **keyless SSH** (`jarvis@jarvis-ai.info`, Key `~/.ssh/id_rsa`, Docroot `/var/www/vhosts/jarvis-ai.info/www`), KEIN Secret im Repo (FTP/FTPS wurde abgelöst, da FTP-ALG in manchen Netzen das AUTH-Kommando kapert).
  - Drift-sicher patchen: Live-Datei per `scp` laden, gezielt ändern, zurückspielen (statt Repo-Kopie zu überschreiben) – so wie build.sh es für den Versionsstring macht.
- **Desktop-User:** `jarvis` (autologin via lightdm), Web-Login: `jarvis/jarvis`
- **Services:** `systemctl restart jarvis.service` + `systemctl restart whatsapp-bridge.service`
- **Git-Remote:** lokaler Clone nutzt SSH (`git@github.com:dev-core-busy/jarvis.git`) – kein Token mehr in `.git/config` (Stand 2026-06-16). Repo ist public; Server ziehen token-los per HTTPS.

## Architektur
```
Frontend (Vanilla JS)  ─HTTPS─>  FastAPI (Port 443)  ──>  AgentManager
     │                                │                        │
     ├─ WebSocket (Agent-Steuerung)   ├─ LLM (Gemini/etc.)    ├─ Hauptagent (JarvisAgent)
     ├─ Agent-Sidebar (Multi-Agent)   ├─ Skills API            │   ├─ SkillManager + Tools
     ├─ noVNC (Port 6080)            ├─ WhatsApp Proxy        │   └─ spawn_agent → Sub-Agents
     └─ Settings (Profile/Skills/WA)  └─ Debug-Toggle          ├─ Sub-Agent 1 (autonom)
                                           │                    ├─ Sub-Agent 2 (autonom)
                                    WhatsApp Bridge             └─ Memory (data/memory.json)
```

## Tech Stack
- **Backend:** Python 3.13, FastAPI, uvicorn, HTTPS (self-signed)
- **Frontend:** Vanilla JS, Dark Glassmorphism Theme, WebSocket
- **LLM:** Multi-Provider (Google Gemini, OpenRouter, Anthropic, OpenAI-compatible)
- **Desktop:** Xvfb/X11, Openbox, x11vnc, websockify (noVNC)
- **WhatsApp:** Node.js + Baileys v7, faster-whisper (Voice-Transkription)
- **Vision:** face_recognition (dlib DNN), OpenCV, HOG/CNN Detection

## Verzeichnisstruktur
```
backend/
  main.py          – FastAPI Server, alle HTTP/WS Endpoints
  agent.py         – Agent-Loop (run_task, run_task_headless) + AgentManager + Multi-Agent
  llm.py           – Multi-Provider LLM Client
  config.py        – Konfiguration (env + settings.json)
  security.py      – SSL-Zertifikate
  scheduler.py     – Zeitgesteuerte Auftraege (Cron-Backend)
  update_manager.py – Auto-Update via git (stash vor Pull)
  learning.py      – Konversations-Lernsystem (Faktenextraktion in FAISS)
  issues.py        – Issue-Tracker (Bugs/Features/Verbesserungen)
  mcp_client.py    – MCP-Client (Model Context Protocol)
  google_auth.py   – Google OAuth (Calendar/Drive/Gmail)
  webdav.py, web_extractor.py, file_watcher.py
  audit_log.py, conv_log.py, telemetry.py – Logging/Telemetrie
  skills/
    manager.py     – SkillManager (enable/disable/config/reload)
    loader.py      – Dynamisches Skill-Loading
  tools/
    base.py        – BaseTool Klasse
    shell.py       – Shell-Ausfuehrung mit Live-Streaming (stdout zeilenweise via WebSocket)
    subagent.py    – spawn_agent Tool (Hauptagent startet Sub-Agents)
    vector_store.py – FAISS Vektor-DB + BM25 fuer hybride Wissenssuche
    desktop.py, filesystem.py, screenshot.py, knowledge.py, memory.py
    android_desktop.py, windows_desktop.py – Remote-Desktop-Steuerung
    google_calendar.py, google_drive.py, google_gmail.py, google_auth.py
    clipboard.py, cron_tool.py, reflection.py
    whatsapp.py    – WhatsApp Send/Status Tools
    wa_logger.py   – Strukturiertes WhatsApp-Logging (JSON-Lines)
frontend/
  index.html       – Single-Page App
  css/style.css, css/chat.css, css/chat-bubbles.css – Glassmorphism Dark Theme
  js/app.js        – Haupt-UI + WebSocket + Login
  js/chat.js, js/chatlib.js, js/userchat.js – Chat-UI (Bubbles, Multi-Select, History)
  js/i18n.js       – DE/EN-Sprachschalter (alle UI-Strings)
  js/skills.js     – Skills Settings UI
  js/whatsapp.js   – WhatsApp Settings + Log-Viewer
  js/vision.js     – Vision Settings (Dashboard/Training/Profile/Aktionen)
  js/google.js, js/mcp.js, js/cron.js, js/issues.js, js/telemetry.js, js/audit.js
  js/vnc.js        – noVNC Integration
  js/websocket.js  – WebSocket Manager
skills/             – 18 Skills, u.a.:
  browser_control/ – xdotool-basierte Browser-Automation + CDP
  whatsapp/        – WhatsApp Skill (send + status Tools)
  telegram/        – Telegram Bot (Empfang + Antwort)
  google/          – Google Calendar/Drive/Gmail
  vision/, jarvis-vision/ – Gesichtserkennung (face_recognition/dlib, USB/IP-Kamera)
  cron/            – Zeitgesteuerte Auftraege
  agent_orchestrator/ – Zerlegt Aufgaben in koordinierte Sub-Agenten (inbox/outbox)
  agent_autonomy_kit/ – Proaktives Aufgaben-Management via QUEUE.md
  cognitive_evolution/ – Selbstverbessernder Agent (schreibt/validiert eigene Skills)
  claude_bridge/   – Delegiert Aufgaben an Claude Desktop-App (xdotool)
  example_skill/   – Template fuer neue Skills
android/           – Android-App (Kotlin/Jetpack Compose, signiert via .jks)
windows-app-go/    – Nativer Windows-Client (Go, Tray, lokale STT, Avatar, WS-Client)
docs/landing-page/ – Statische Landing-Page fuer jarvis-ai.info (SSH-Deploy via build.sh, keyless)
services/
  whatsapp-bridge/index.js – Baileys Bridge mit Express API
data/
  knowledge/       – Wissensdatenbank (TF-IDF + ChromaDB Vektor-Suche)
  chroma_db/       – ChromaDB Persistenz (sentence-transformers Embeddings)
  memory.json      – Persistenter Key-Value Speicher
  logs/            – WhatsApp-Logs (JSON-Lines)
  vision/          – Gesichtserkennung (faces/, encodings.pkl, config.json, events.json)
```

## Rechte-Trennung (Root-Broker)
- **Getrennter Betrieb (empfohlen):** Backend laeuft unprivilegiert (`jarvis.service`, User=jarvis, Port 443 via `CAP_NET_BIND_SERVICE`); Root-Operationen laufen ueber den **Root-Broker** (`jarvis-broker.service`, root, Unix-Socket `/run/jarvis-broker.sock`, Gruppe jarvis 0660)
- **Code:** `backend/broker/` (policy.py, ops.py, daemon.py) + `backend/broker_client.py` (Client mit root-Fallback fuer Alt-Installationen) + `backend/desktop_control.py` (aus main.py herausgeloeste Desktop-/Session-Root-Logik)
- **Benannte Ops mit harter Validierung:** systemctl (Unit-Whitelist), unlock_screen, switch_session, vnc_restart, chpasswd, sandbox_exec (nur `jarvis_sandbox*`), sandbox/egress_setup|teardown|status, mount_share/umount_share (nur /mnt/), certbot_obtain, shell_root (generisch)
- **Auditierbare Freigabeliste:** Jede Op wird beim ersten Auftauchen als Policy-Eintrag registriert (`/etc/jarvis/broker-policy.json`, root-only). System-Ops: auto-allow (widerrufbar). `shell_root:<befehl>`: startet **pending** → Admin entscheidet unter *Einstellungen → Sicherheit → Root-Freigaben* (`/api/broker/*`, security_incidents.js)
- **Shell-Routing:** `shell.py::_needs_root()` erkennt Root-Befehle (sudo/systemctl/apt/mount/...); privilegierte Nutzer → Broker shell_root, Domain-Nutzer → Broker sandbox_exec (runuser). Audit: `/var/log/jarvis-broker-audit.jsonl`
- **Migration pro Server:** `bash deploy/security/setup_broker.sh` (chown, Units installieren, Dienste starten, Verifikation). Alt-Betrieb (Backend als root, repo-root `jarvis.service`) funktioniert weiter: broker_client fuehrt Ops dann lokal aus (inkl. Policy/Audit)
- **Achtung:** settings.json-Schreiben erhaelt Eigentuemer (`config._write_preserve_owner`) – der root-Broker darf die Datei dem jarvis-Backend nicht entziehen

## Multi-Agent System
- **AgentManager** in `agent.py`: Verwaltet Haupt- und Sub-Agents
  - `get_or_create_main()`: Erstellt/gibt Hauptagent zurueck
  - `spawn_sub_agent(label, task)`: Erstellt autonomen Sub-Agent
  - `run_sub_agent(agent, task, ws)`: Startet Sub-Agent als async Task
- **spawn_agent Tool** (`tools/subagent.py`): Hauptagent kann Sub-Agents starten
  - `label` optional (wird auto-generiert), `task` Pflicht
  - Tolerant: akzeptiert `code`, `name` als alternative Parameter
  - Sub-Agents arbeiten VOLLSTAENDIG AUTONOM (kein Rueckfragen)
- **Shell-Streaming** (`tools/shell.py`): stdout wird zeilenweise live via WebSocket gesendet
  - `PYTHONUNBUFFERED=1` in env fuer sofortige Ausgabe
  - Python-Code wird in Temp-Datei geschrieben (vermeidet Quoting-Probleme)
- **Frontend-Sidebar** (`app.js`): Agent-Karten rechts im LLM-Fenster
  - Hauptagent (gruen), Sub-Agents (lila), Klick wechselt Ansicht
  - X-Button zum manuellen Entfernen, Auto-Cleanup nach 8s bei Fertigstellung
  - Drag-Resize der Sidebar-Breite
- **Debug-Toggle**: Pill-Button blendet nicht-highlight Zeilen aus (nur LLM-Dialog sichtbar)
- **WebSocket-Protokoll**: `agent_event` (started/spawned/finished/paused), `agent_list`, `status` mit `agent_id`

## Vektor-Datenbank (Wissenssuche)
- **FAISS** (`IndexFlatIP`, normierte Vektoren = Cosine) + **sentence-transformers**
  (`intfloat/multilingual-e5-small`, 384d) – Persistenz: `data/vector_store/faiss_index.bin`
  + `faiss_meta.json` (enthaelt auch die Chunk-Texte)
- **Hybride Suche** (seit 2026-07-23): `search_hybrid()` fusioniert drei Kanaele per
  Reciprocal Rank Fusion (RRF_K=20):
  1. semantisch mit der Original-Query (FAISS/e5, e5-Prefixe `query:` / `passage:`)
  2. semantisch mit der auf Inhaltswoerter reduzierten Query (`_content_terms()`,
     Stoppwortliste DE/EN) – Frage-Floskeln ziehen den Query-Vektor messbar weg;
     der Kanal entfaellt, wenn die Reduktion nichts aendert (spart ein Encoding)
  3. lexikalisch (BM25 ueber dieselben Chunks aus `_meta` – kein zweiter Index;
     invertierter Index lazy gebaut, invalidiert ueber Generations-Zaehler `_gen`)
  Grund fuer BM25: reine Embeddings sind bei exakten Bezeichnern (`@STR_UCASE`,
  Fehlercodes, Parameternamen) strukturell schwach – `STR_UCASE` und `STR_LCASE`
  landen fast auf demselben Punkt. Latenz gemessen: 19–58 ms bei 1155 Chunks.
- **Der zurueckgegebene Score ist ein normierter RRF-Rang** (Top = 1.00), KEIN Cosine-Wert.
- **Chunking:** 200 Woerter / 40 Overlap. MUSS unter dem 512-Token-Limit von e5 bleiben –
  laengere Chunks werden vom Modell still abgeschnitten und der Inhalt dahinter ist
  im Vektor unauffindbar.
- **Score-Filter:** `MIN_SCORE=0.72` absolut + `RELATIVE_CUT=0.5` relativ zum Top-Treffer
  (mind. `MIN_KEEP=3`). e5 komprimiert Cosine auf ~0.75–0.95, absolute Schwellen allein
  filtern daher praktisch nichts.
- **Lern-Notizen** (`knowledge/learned|pending/`) werden im Ranking mit `LEARNED_PENALTY=0.6`
  abgewertet: sie tragen die Benutzerfrage als Ueberschrift und waeren sonst fuer genau
  diese Frage der Top-Treffer – unabhaengig vom Inhalt (selbstverstaerkende Schleife).
- TF-IDF (`_search()` + `knowledge_index.json`) existiert noch als Fallback, wenn FAISS
  fehlt; der frueher waehlbare Suchmodus (Auto/TF-IDF/Vektor) wurde entfernt.
- **Verschieben ohne Neu-Embedding:** Beim Verschieben aendert sich nur die Adresse eines
  Dokuments, nicht sein Inhalt – es werden ausschliesslich Metadaten umgeschrieben.
  Ordner: `relocate_folder_index()` / `rename_path_prefix()`. Einzeldateien:
  `relocate_file_index()` / `rename_file_path()`, API `POST /api/knowledge/files/move`
  (`{paths[], target}`), Zielordner-Liste ueber `GET /api/knowledge/folder_tree`.
  UI: 📂-Knopf je Datei + "Auswahl verschieben" in der Bulk-Leiste (Einstellungen → Wissen).
  WICHTIG: Die Datei per `Path.rename()` verschieben – das laesst die mtime unveraendert,
  und genau die vergleicht der inkrementelle Reindex. Wird sie angefasst, bettet der
  naechste Lauf die Datei unnoetig neu ein. Verifiziert: 3 Chunks in 37 ms umgezogen,
  Folge-Reindex 0.00 s ohne Neu-Embedding.
- **Indizierungs-Lauf (Einstellungen → Wissen):** `POST /api/knowledge/reindex` startet,
  `POST /api/knowledge/reindex/cancel` bricht ab (Flag `_reindex_cancel`, geprueft ZWISCHEN
  zwei Dateien – bereits geschriebene Chunks bleiben, der Index ist danach unvollstaendig,
  weil ein Neuaufbau mit `vs.clear()` beginnt). Der Knopf "Index neu aufbauen" wird waehrend
  des Laufs zu "Indizierung abbrechen". `get_index_progress()` liefert zusaetzlich
  `started_at`/`finished_at`/`cancelled`; der letzte Lauf steht in
  `data/vector_store/last_index.json` (`get_last_run()`, ueberlebt Neustart).
- **Automatischer Neuversuch nach FEHLERN** (nicht nach manuellem Abbruch): scheitert ein
  Lauf mit einer Ausnahme, wiederholt `_run_with_retries()` ihn bis `MAX_INDEX_ATTEMPTS=3`
  (Pause `RETRY_DELAY_SEC`, unterbrechbar). `running` bleibt dabei True, `attempt` zaehlt
  hoch – der Fehler-Endzustand wird erst nach dem letzten Versuch geschrieben.
  Stirbt der PROZESS mitten im Lauf, bleibt `status: running` in last_index.json stehen;
  `resume_interrupted_reindex()` (Start-Hook in main.py, +30 s) setzt den Neuaufbau dann
  automatisch fort – max. `MAX_RESUMES=2`, danach `status: interrupted` (Schleifenschutz).
- **"Dateien" vs. "Indiziert":** `total_files` ist die Anzahl indizierbarer Dateien in den
  Wissensordnern (`get_disk_file_count()`, 60 s gecacht, Hintergrund-Refresh),
  `indexed_files` die Anzahl im FAISS-Index. Frueher stand in beiden die Index-Zahl –
  ein unvollstaendiger Index sah dann wie "nur 10 Dokumente vorhanden" aus.
- **numpy**: Muss < 2.1 bleiben (VM hat kein SSE4.2)

## Wissens-Upload (/wissen → Informationsextraktor → Datei)
- Einziger UI-Weg, um Dateien in einen Wissensordner zu legen: `POST /api/wissen/upload`.
  Der frühere Upload in *Einstellungen → Wissen* wurde entfernt (die UI war schon weg,
  der tote JS-/CSS-Code am 2026-07-23 aufgeräumt). `POST /api/knowledge/upload` existiert
  weiter für API-Nutzung, hat aber KEINE Oberfläche mehr.
- **ZIP-Archive** werden serverseitig entpackt (`_kb_unpack_zip` in main.py); die
  Ordnerstruktur wird unter dem Zielordner nachgebildet, fehlende Unterordner angelegt,
  jede Datei erbt die gewählte Wissensgruppe. Nicht unterstützte Formate im Archiv
  werden einzeln abgelehnt, nicht das ganze Archiv.
- Schutz: Zip-Slip (`..`, absolute Pfade), Symlinks, `__MACOSX`/versteckte Dateien,
  Tiefenlimit 8. Umlaut-Fix für Windows-ZIPs, die UTF-8 OHNE Flag 0x800 schreiben
  (`_zip_entry_name` – sonst wird "Handbücher" zu "Handb├╝cher").
- **Grenzen:** 500 MB entpackt / 2000 Dateien / 2 GB freie Plattenreserve –
  **globale Wissens-Editoren (`_may_edit_knowledge`) sind von ALLEN dreien
  ausgenommen** (`max_total_bytes`/`max_entries`/`min_free_bytes` = `None`),
  laden also voellig unbegrenzt hoch (bewusste Vorgabe 2026-07-23).
- Das Archiv wird über `UploadFile.file` gelesen, NICHT über `await file.read()` –
  sonst läge ein mehrere GB großes Archiv komplett im RAM.
- **Unterordner anlegen/umbenennen** darf im Portal jeder Editor einer Gruppe, der der
  Wurzelordner zugeordnet ist: `POST`/`PUT /api/wissen/subfolders`, Prüfung über
  `_wissen_may_write_path()`. Wurzelordner bleiben der Admin-Fläche vorbehalten.

## Skill-System
- Skills liegen unter `skills/<name>/` mit `skill.json` (Manifest) + `main.py` (get_tools())
- Tools erben von `backend/tools/base.py:BaseTool`
- States persistiert in `settings.json` unter `skills`-Key
- API: `/api/skills`, `/api/skills/{name}/enable|disable|config|install-status|purge`
- **Lifecycle (seit 2026-07-19):** Aktivieren installiert fehlende Abhaengigkeiten im
  Hintergrund-Thread (pip + apt via Root-Broker + `install_commands` wie npm install);
  Fortschritt via `GET install-status`, Frontend pollt und zeigt Log.
  `POST purge` deinstalliert vollstaendig: Dienst stoppen, pip-Pakete entfernen
  (Geteilt-Pruefung: requirements.txt + dependencies/optional_dependencies anderer
  installierter Skills + pip-Reverse-Deps), optional `remove_data` fuer data_dirs/caches.
  Skill-Code (git-getrackt) bleibt immer liegen.
- Manifest-Lifecycle-Felder: `dependencies` (pip), `optional_dependencies` (schuetzt
  fremde Pakete vor Purge, z.B. knowledge→faster-whisper), `system_packages` (apt),
  `purge_packages` (explizite Entfern-Liste inkl. transitiver Pakete), `data_dirs`,
  `caches` (Globs, z.B. Whisper-Modell), `install_commands` ({cmd,cwd,creates}),
  `systemd_service`

## WhatsApp-Integration
- **Bridge:** Node.js + Baileys v7, systemd `whatsapp-bridge.service`, Port 3001 (localhost)
  - Self-Chat: Erkennung via LID (Linked ID) + connectedNumber
  - Feedback-Loop Schutz: `sentByBridge` Set trackt eigene Message-IDs
- **Backend-Proxy:** `_wa_bridge_async()` – async via `asyncio.to_thread()`, 3s Timeout
  - WICHTIG: Nie synchrone Bridge-Requests im Event-Loop (Deadlock/Freeze-Gefahr)
- **wa_logger.py:** Thread-Lock, NIEMALS `log()` innerhalb von `_lock` aufrufen (Deadlock!)
- **WhatsApp-Task-Prompt:** `WA_TASK_PROMPT` in main.py – Few-Shot Beispiele fuer Agent
- **Voice-Pipeline:** OGG/Opus → faster-whisper (small, CPU, int8) → Agent-Task

## Vision-Integration (Gesichtserkennung)
- **Engine:** `VisionEngine` Singleton in `skills/vision/vision_engine.py`, Background-Thread
  - DNN-basiert via `face_recognition` (dlib), HOG (schnell/CPU) oder CNN (genau/GPU)
  - Encoding-DB: `data/vision/encodings.pkl` (128-dim Vektoren pro Person)
  - Trainingsbilder: `data/vision/faces/<name>/` (JPEG Crops)
- **Aktionssystem:** Pro erkanntem Gesicht: Webhook (HTTP POST), LLM-Prompt (Agent-Task), Log-Only
  - 10s Cooldown pro Person, konfigurierbare Toleranz (0.0–1.0)
- **API:** 14 Endpunkte unter `/api/vision/*` (status, control, snapshot, cameras, profiles, training, events, cleanup)
- **Frontend:** `JarvisVisionManager` in `vision.js`, Vision-Tab im Settings-Modal
  - Tab nur sichtbar wenn Vision-Skill aktiviert (analog Google-Tab)
  - Polling: Status 2s, Feed 1s, Training 0.5s – wird bei Tab-Wechsel gestoppt
- **Abhaengigkeiten:** `face-recognition>=1.3.0`, `opencv-python-headless>=4.8.0`, `setuptools<75` (fuer pkg_resources)
  - System-Pakete: `cmake`, `libboost-all-dev`
  - SSE41-Warnung von dlib auf der VM ist harmlos (funktioniert trotzdem)

## Konventionen
- **Sprache:** Code-Kommentare und Commit-Messages auf Deutsch
- **CSS:** Verwende `var(--text-primary)`, `var(--bg-glass)` etc. aus `:root` – keine hardcoded Farben
- **Frontend:** Kein Build-System, keine Frameworks – reines Vanilla JS
- **Secrets:** `.env` Datei, NICHT in Code committen
- **numpy:** Muss < 2.1 bleiben (VM hat kein SSE4.2 / X86_V2)

## Bekannte Fallstricke
- **NIEMALS Write-Tool auf bestehende Dateien:** Das Write-Tool ueberschreibt Dateien vollstaendig – bei Fehlern entstehen 0-Byte-Dateien. Fuer bestehende Dateien (z.B. index.html, main.py, etc.) IMMER nur das Edit-Tool verwenden. Write nur fuer NEUE Dateien!
- **Deadlock in wa_logger.py:** `clear_logs()` darf `log()` nur NACH Lock-Release aufrufen
- **Synchrone Bridge-Requests:** Blockieren den asyncio Event-Loop → Server friert ein. Immer `_wa_bridge_async()` verwenden
- **Self-Chat Feedback-Loop:** Bridge trackt gesendete Message-IDs in `sentByBridge` Set
- **Browser-Cache:** Bei Frontend-Aenderungen Cache-Buster in index.html hochzaehlen (`?v=N`)
- **SSH Heredocs:** Quoting-Probleme mit Python f-strings. Besser: lokal schreiben + `scp`
- **Python-Code via Shell:** NIEMALS `python3 -c "..."` mit verschachtelten Quotes. Code in Temp-Datei schreiben (`_code_to_command()` in shell.py)
- **Shell-Streaming:** `PYTHONUNBUFFERED=1` muss gesetzt sein, sonst kein Live-Output
- **Sub-Agent 0 Parts:** Wenn LLM leere Antwort liefert, pruefen ob Task-Text korrekt uebergeben wird
- **Doppelter Hauptagent:** Frontend resettet `_agentInfos` bei `started`-Event des Hauptagents
- **Embedding-Modell-Cache liegt beim jarvis-User:** Skripte, die `sentence-transformers`
  nutzen (z.B. manueller Reindex), brauchen `HOME=/home/jarvis`. Sonst sucht HF in
  `/root/.cache` → `OSError: PermissionError ... when downloading` → jedes Encoding
  scheitert und ein Reindex baut still einen LEEREN Index auf:
  `env HOME=/home/jarvis setpriv --reuid=jarvis --regid=jarvis --init-groups venv/bin/python ...`
- **`_rebuild_vector_index()` verschluckt Fehler** (`except Exception: pass` pro Datei) –
  ein fehlgeschlagener Reindex meldet keinen Fehler, sondern `0 Chunks`. Ergebniszahl
  immer pruefen; vor einem Reindex `data/vector_store/` sichern (`vs.clear()` laeuft zuerst).
- **Chunk-Ausgabe im Tool ist gedeckelt** (`CHUNK_OUTPUT_LIMIT`): Ist das Limit kleiner als
  ein Chunk, sieht das LLM nur den Anfang des Treffers und antwortet auf einem Ausschnitt,
  der die Antwort nicht enthaelt. Limit und `_chunk_text`-Groesse zusammen aendern.

## Ports
| Port | Service | Zugriff |
|------|---------|---------|
| 443 | FastAPI (HTTPS) | Extern |
| 80 | HTTP → HTTPS Redirect | Extern |
| 6080 | noVNC (WSS) | Extern |
| 5900 | x11vnc | Nur lokal |
| 3001 | WhatsApp Bridge | Nur lokal |

## Haeufige Befehle
```bash
# Services neustarten
systemctl restart jarvis.service
systemctl restart whatsapp-bridge.service
systemctl restart jarvis-broker.service   # Root-Broker (getrennter Betrieb)

# Logs pruefen
journalctl -u jarvis.service -f
journalctl -u whatsapp-bridge.service -f

# Deployen
scp -i ~/.ssh/id_rsa <datei> root@191.100.144.1:/opt/jarvis/<pfad>
```
