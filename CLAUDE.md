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

## Reasoning-Steuerung (Denktiefe, seit 2026-07-27)
- **Eine providerunabhaengige Stufenleiter** (`REASONING_LEVELS` in `llm.py`):
  `off | low | medium | high | max`. `normalize_effort()` nimmt tolerant Synonyme an
  (DE/EN, `xhigh`→`max`, `none`/`aus`/`0`→`off`); **unbekannte Werte werden zu None**,
  ein Tippfehler im API-Aufruf darf die Anfrage nicht mit einem Provider-400 killen.
- **Vorrang:** pro Chat-Anfrage (`reasoning_effort` im WS-`task`) > LLM-Profil
  (`reasoning_effort`) > global (`config.LLM_REASONING_EFFORT`, Einstellungen/ENV).
  `agent.py::current_reasoning_effort` loest Anfrage>Profil auf, `llm.py::_resolve_effort()`
  haengt die globale Vorgabe hinten an.
- **Sentinel `_EFFORT_UNSET`** (analog `_KB_GROUPS_UNSET`): `main.py` uebergibt den Wert
  IMMER explizit (auch `None`), Sub-Agents uebergeben ihn nicht und erben damit die Stufe
  des Eltern-Agenten. Ohne diese Unterscheidung wuerde die Stufe eines Nutzers am
  **geteilten Hauptagenten** beim naechsten Nutzer haengenbleiben.
  `run_task_headless()` setzt bewusst `None` (WhatsApp/Telegram/Cron haben keine Oberflaeche).
- **Uebersetzung je Provider** (`_apply_reasoning` / `_thinking_config`):
  | Provider | Feld | `off` |
  |---|---|---|
  | Gemini | `thinking_config.thinking_budget` (0/1024/4096/12288/24576 Token) | Budget 0 |
  | OpenAI-kompatibel | `reasoning_effort: minimal\|low\|medium\|high` | `minimal` (Annaeherung!) |
  | OpenRouter | `reasoning: {effort}` bzw. `{enabled: false}` | `enabled:false` |
  | Anthropic | `thinking:{type:adaptive}` + `output_config:{effort}` | `thinking:{type:disabled}` |
  | Anthropic-Session (claude.ai) | – (Wert wird angenommen und ignoriert) | – |
- **Anthropic-Besonderheiten:** bei gesetzter Stufe wird `temperature` **weggelassen** –
  aktuelle Modelle (Opus 5/4.8/4.7, Sonnet 5, Fable 5) lehnen Sampling-Parameter mit 400 ab.
  Bei `high`/`max` wird `max_tokens` auf mind. 16000 gehoben (deckelt Denk- UND Antworttoken
  gemeinsam). Bei `off` wird KEIN `output_config` gesendet (thinking-aus + hohe Stufe = 400).
- **Selbstheilender Fallback:** lehnt ein Modell/Server einen dieser Parameter mit 400 ab
  (`_is_unsupported_param_error()`), wird die Anfrage EINMAL ohne thinking/effort/temperature
  wiederholt – der Nutzer bekommt eine Antwort ohne Feinsteuerung statt einer Fehlermeldung.
  Echte Fehler (429/500/Kontextfenster) laufen NICHT in den Fallback.
- **Verifiziert auf DEV (Gemini 3.5 flash, harte Rechenfrage):** `off` = keine Denk-Token /
  3,4 s, `low` = 1344 / 6,6 s, `high` = 1515 / 8,2 s, `max` = 1631 / 8,6 s. Der Regler wirkt.
- **Kein UI-Element** – bislang nur API (WS-`task` + `POST /api/agent/task`) und Profil-/
  Globalfeld. Ein Frontend-Schalter muesste `data-i18n` + CSS-Variablen beachten.
- **Alte google-genai-Versionen** (< ~1.10) kennen `thinking_budget` nicht. Weil ThinkingConfig
  ein pydantic-Modell ist, kommt dann ein **ValidationError** (nicht TypeError) – daher das
  breite `except Exception` in `_thinking_config()`. DEV hat 1.72.0 (unterstuetzt es).

## Sampling & Antwortlaenge (temperature, LLM_MAX_TOKENS, seit 2026-07-27)

- **`temperature` ist ein Profil-Feld, kein Anfrage-Parameter.** Der Wert liegt in
  `config.py::create_profile`/`update_profile` neben `reasoning_effort` und wird von
  `agent.py::current_temperature` gelesen. Die Begruendung fuer „Profil statt Anfrage": die
  Temperature ist faktisch eine Modell-Eigenschaft, und in Jarvis IST das Profil das Modell –
  ausserdem zerlegen Werte ab etwa 0.7 die JSON-Argumente von Tool-Aufrufen, was pro Nachricht
  umschaltbar ein reiner Fussangel-Schalter waere. Zwei Zustaende: **`"auto"` ist der STANDARD**
  (seit 2026-07-27) und laesst den Parameter komplett weg, eine Zahl `0.0`–`2.0` sendet genau
  diesen Wert. Validierung: `config._valid_temperature()` (nimmt deutsche Dezimalkommas, begrenzt
  auf 0..2, macht aus Leerem und Muell `"auto"`); Aufloesung: `llm.py::_resolve_temperature()`
  (gibt `None` zurueck = Feld weglassen, **nicht** 0).
- **Warum `"auto"` der Standard ist – und was das kostet.** Aktuelle Claude-Modelle
  (Opus 5/4.8/4.7, Sonnet 5, Fable 5) lehnen Sampling-Parameter mit HTTP 400 ab; ohne `"auto"`
  faengt das erst der 400-Fallback ab, also nach einem verschwendeten Aufruf. **Nebenwirkung, die
  man kennen muss:** ohne Feld gilt der Anbieter-Default, und der liegt bei vielen
  OpenAI-kompatiblen Servern und bei Gemini deutlich ueber den frueher fest verdrahteten 0.2.
  Fuer werkzeuglastige Profile kann das die Zuverlaessigkeit von Tool-Aufrufen senken – dort
  gehoert eine feste Zahl ins Profil (0.2 stellt das Verhalten vor Juli 2026 wieder her).
  `llm.LEGACY_TEMPERATURE = 0.2` dokumentiert diesen Altwert als benannte Konstante.
- **Migration bestehender Profile** (`_load_v2`): Profile ohne `temperature`-Key oder mit leerem
  Wert werden beim Laden auf `"auto"` gesetzt und **einmalig** zurueckgeschrieben – nur wenn
  wirklich etwas geaendert wurde, sonst schriebe jeder Start die settings.json neu. Ein bereits
  gesetzter Zahlenwert bleibt unangetastet, **auch `0.0`** (die Pruefung ist
  `in ("", None)`, NICHT auf Falsyness – sonst wuerde 0.0 als „leer" gelten). Schlaegt das
  Schreiben fehl (Rechte), gelten die Werte nur fuer diesen Lauf und der Start laeuft weiter.
  Auf DEV verifiziert: 4 Profile migriert, API-Keys unveraendert, zweiter Start schreibt nicht.
- **`temperature` war an vier Stellen hart codiert** (Gemini-Config, OpenAI-nativ,
  OpenAI-Prompt-Modus, Anthropic-kwargs) und ist jetzt an allen vier durch den aufgeloesten Wert
  ersetzt. Jeder Provider sendet das Feld nur, wenn der aufgeloeste Wert nicht `None` ist –
  das Muster ist immer `if temperature is not None: payload["temperature"] = temperature`.
  Bei Anthropic gilt zusaetzlich die aeltere Regel weiter, dass bei **gesetzter Reasoning-Stufe**
  gar keine Temperature mitgeht. `AnthropicSessionProvider` (claude.ai) nimmt den Wert an und
  ignoriert ihn, weil die Session-Schnittstelle keine Sampling-Parameter kennt. Verifiziert auf
  DEV mit Gemini: `0.0` und `0.2` liefern dreimal dasselbe Wort, `1.8` variiert, `"auto"` laeuft
  fehlerfrei ohne das Feld.
- **`config.LLM_MAX_TOKENS` existierte vorher NICHT.** `llm.py::_llm_max_tokens()` las es per
  `getattr(config, "LLM_MAX_TOKENS", 8192)`, sodass immer 8192 galt – obwohl der Docstring
  Einstellbarkeit ueber *Einstellungen → LLM* versprach. Das Feld ist jetzt eine echte globale
  Einstellung mit Laden (`_load_v2`), Speichern (`_save_to_file`), Schreib-Endpunkt
  (`save_global_settings`) und Anzeige in `GET /api/settings`. Der Wert wird an drei Stellen auf
  256..131072 begrenzt (Laden, Speichern, Auslesen), damit auch eine handgeschriebene
  settings.json nichts kaputt machen kann. Praktische Relevanz: bei Reasoning-Stufe `high`/`max`
  zaehlen Denk- UND Antworttoken gegen dieses Limit, ein zu kleiner Wert schneidet die Antwort
  mitten im Satz ab.
- **`prompt_tool_calling` wurde nie persistiert** (behoben 2026-07-27). Das Frontend sendet das
  Feld seit Langem im Profil-Payload und `agent.py::current_prompt_tool_calling` liest es, aber
  es stand weder in `create_profile` noch in der Whitelist von `update_profile` – der Schalter im
  Profilformular hatte also **keine Wirkung**. Wer Prompt-basiertes Tool-Calling brauchte, musste
  den Wert direkt in settings.json eintragen. Jetzt ist das Feld in beiden Funktionen vorhanden
  und wird als `bool()` normalisiert. Beim Erweitern von Profil-Feldern immer BEIDE Stellen
  anfassen, sonst entsteht genau dieser stille Fehler wieder.
- **Oberflaeche – Klappabschnitt „Tuning"** (*Einstellungen → KI & System*): fasst seit
  2026-07-27 „Sprachausgabe (TTS)", „Antwort-Timeout" und „Maximale Antwortlaenge" in EINEM
  Abschnitt zusammen (vorher drei einzelne). Die drei Untergruppen nutzen `.tuning-group` +
  `.tuning-group-title` (style.css), getrennt durch eine Linie ab der zweiten Gruppe. **Alle
  Element-IDs sind unveraendert geblieben** (`setting-tts-voice`, `setting-llm-timeout`,
  `setting-llm-max-tokens`, die zugehoerigen Buttons und Status-Spans) – app.js verdrahtet sie
  darueber, ein Umbenennen haette die Speichern-Knoepfe still gebrochen. In
  `_initProfilesCollapse()` ersetzt ein Eintrag `prof-sect-tuning-*` die drei alten.
  Die Untergruppen-Titel recyceln die vorhandenen i18n-Keys `profile.section_tts|timeout|maxtok`.
- **Oberflaeche – Temperature-Feld:** Freitextfeld im Profil-Formular mit `datalist`
  (auto/0.0/0.2/0.7/1.0), Platzhalter „leer = auto (Anbieter entscheidet)". Absichtlich ein
  Textfeld und kein `number`-Input, weil `"auto"` ein gueltiger Wert ist. Beim Laden eines
  Profils wird auf `null`/`undefined`/`""` geprueft und **nicht** auf Falsyness – sonst wuerde
  ein gespeicherter Wert `0` als leeres Feld erscheinen. Die Validierung passiert bewusst nur
  im Backend; das Frontend schickt den Rohtext. Infotexte mit je fuenf Saetzen in DE und EN
  (`profile.maxtok_hint`, `profile.temp_hint`).
- **API-Nutzung:** Profil-Feld ueber `POST`/`PUT /api/profiles` als `temperature`
  (`""`|`"auto"`|Zahl), globaler Wert ueber `POST /api/settings` als `llm_max_tokens`.
  Achtung Asymmetrie: das Profil-Feld `reasoning_effort` akzeptiert nur die fuenf kanonischen
  Stufen, waehrend das Anfrage-Feld `reasoning_effort` im WS-Task tolerant Synonyme annimmt
  (`xhigh`, `aus`, …). Grund ist die Import-Richtung: `llm.py` importiert `config.py`, nicht
  umgekehrt, deshalb liegt die Alias-Tabelle nur in `llm.py`.

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
- **Stirbt der PROZESS mitten im Lauf** (Absturz/Neustart/**OOM-Killer**), bleibt
  `status: running` in last_index.json stehen; `resume_interrupted_reindex()` (Start-Hook in
  main.py, +30 s) setzt den Neuaufbau **inkrementell** fort (`force_reindex(incremental=True)`
  → KEIN `vs.clear()`, die schon indizierten Dateien bleiben). Fortgesetzt wird nur, solange
  messbarer Fortschritt entsteht: `resume_baseline` merkt den Dateistand zu Beginn jedes
  Anlaufs; bringt ein Anlauf keine neue Datei, wird mit `status: interrupted` +
  `interrupt_reason` gestoppt (sonst liefe eine Datei, die den Prozess zuverlaessig killt,
  endlos). Sicherheitsnetz `MAX_RESUMES=20`. Ein Checkpoint (`_write_run_checkpoint`, alle
  `CHECKPOINT_EVERY=25` Dateien) haelt `current_file`/`done`/`total` auf Platte fest – die
  UI zeigt nach einem Absturz, WIE WEIT und bei WELCHER Datei es endete.
- **OOM-URSACHE (behoben 2026-07-24):** `VectorStore.add_chunks` hat frueher bei JEDER Datei
  den kompletten FAISS-Index rekonstruiert (`_vectors_at`→`np.vstack`→neuer Index) UND die
  vollen ~55 MB auf Platte geschrieben → O(N²) Heap-Wachstum, das den Prozess bei ~600 von
  893 Dateien per OOM-Killer beendete (Echt-System, 3× in Folge). Jetzt Schnellpfad: neue
  Datei = nur `index.add()` + `_meta.extend()` (kein Rebuild); der Reindex-Loop speichert
  gedrosselt (`add_chunks(save=False)` + `vs.save()` alle 25 Dateien) und ruft periodisch
  `release_memory_to_os()` (malloc_trim). Verifiziert DEV: 300 Dateien = +65 MB RSS statt
  linear; realer Lauf bleibt bei ~1,6 GB flach. Der langsame Pfad (Rebuild) greift nur noch
  bei GEAENDERTEN Dateien (alte Chunks entfernen).
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

## Kontext-API (/api/context/*) – Rechte und Wirkungsbereich (geklaert 2026-07-27)
| Endpunkt | Auth | Wirkungsbereich |
|---|---|---|
| `GET /stats` | jeder Benutzer | eigener Kontext: mit `session_id` diese /chat-Sitzung, ohne den sitzungslosen Bucket `_hist_key(user)` |
| `POST /clear` | jeder Benutzer | eigener Kontext (gleicher Schluessel) |
| `POST /truncate` | jeder Benutzer | eigener Kontext |
| `POST /compress` | **Admin** (`require_local_auth`) | `_current_chat_history` – der ZULETZT GELADENE Kontext, ggf. fremd |
| `POST /threshold` | **Admin** (`require_local_auth`) | **global**: gemeinsamer Hauptagent + `settings.json` |
- **Der Schwellwert ist bewusst GLOBAL** (Vorgabe 2026-07-27): `_compress_threshold` liegt am
  gemeinsamen Hauptagenten, nicht pro History-Schluessel. Die Oberflaeche sagt es jetzt auch
  (`telemetry.ctx_threshold_hint`). Nur Admins duerfen ihn setzen – vorher hing `/threshold` an
  `require_auth`, sodass JEDER angemeldete Benutzer per API die Einstellung aller aendern konnte,
  obwohl das Feld nur unter *Einstellungen → Logs & Debug → Kontext* (Admin) erreichbar ist.
  Die Admin-Schranke auf `/settings` ist rein clientseitig (`app.js`: `is_admin === false` →
  Weiterleitung aufs Portal) – die Route selbst ist ungeschuetzt. Serverseitige Rechte gehoeren
  deshalb IMMER an den jeweiligen API-Endpunkt, nie an die Seite.
- **FALLSTRICK – `main_agent` ist lazy:** `agent_manager.main_agent` bleibt nach jedem Neustart
  `None`, bis der erste Chat-Auftrag laeuft (`get_or_create_main()`). `GET /stats` gab in diesem
  Zustand eine fest verdrahtete `compress_threshold: 30` zurueck; nach dem Speichern von 50 sprang
  das Feld also wieder auf 30 und die Einstellung sah wirkungslos aus – obwohl sie griff, sobald
  der Agent entstand (`JarvisAgent.__init__` liest `compress_threshold`). Jetzt liefert der
  No-Agent-Zweig den gespeicherten Wert. Beim Ergaenzen solcher Zweige NIEMALS Standardwerte
  hart hinschreiben, sondern aus der Konfiguration lesen.
- **Token-Zaehler sind Agent-weit, nicht pro Benutzer:** `_session_input_tokens`/`_output` werden
  bei JEDEM Auftrag zurueckgesetzt und gehoeren zum zuletzt gelaufenen. `get_context_stats(...,
  include_session_tokens=False)` nullt sie, wenn der abgefragte Kontext nicht der laufende ist.
- **`context.js`-Falle:** Der 5-Sekunden-Poll (`_render`) belegt das Schwellwert-Feld neu. Der
  `_userEdited`-Merker wird beim Speichern zurueckgesetzt, deckte also eine danach begonnene
  Eingabe nicht ab – deshalb zusaetzlich `document.activeElement !== inp`.

## Willkommens-Chat „Beispiel Prompts" (/chat, seit 2026-07-27)
- **Jeder Benutzer** erhaelt beim ERSTEN Aufruf von `GET /api/chat/sessions` eine vorbereitete
  Sitzung mit dem Titel `Beispiel Prompts` (`chat_sessions.ensure_welcome_session`). Sie enthaelt
  genau einen Transkript-Eintrag `{role:"bot", kind:"welcome", …}` – **kein LLM-Kontext**, die
  Begruessung landet also nicht im Gedaechtnis des Agenten.
- **Marker `data/chats/<user>/.welcome_v1`** verhindert das Wiederauftauchen, nachdem der Benutzer
  die Sitzung geloescht hat. Eine Willkommensmeldung, die sich nicht wegraeumen laesst, waere eine
  Zumutung. Fuer eine neue Beispiel-Generation den Markernamen hochzaehlen (`_WELCOME_MARK`) –
  dann bekommen ALLE Benutzer den Chat erneut.
- **Inhalt liegt in der Oberflaeche, nicht im Backend:** `chat.js::_renderWelcomeCard` baut die
  Karte aus i18n-Keys (`chat.welcome_head|_intro|_hint`, je Beispiel `chat.wex_<key>_label|_desc|
  _prompt`), das Backend liefert nur `text` als Notfall-Text. So bleibt DE/EN umschaltbar und der
  Text steht nicht doppelt. Katalog + Reihenfolge: `_WELCOME_EXAMPLES` in chat.js (10 Beispiele:
  Excel+Chart, Word→PDF, PPTX-Schaubild, Anhang-Analyse, Wissensdatenbank, Web, Bild, Cron,
  Multi-Agent, Skript). Der Prompt wird ERST BEIM KLICK uebersetzt – sonst wuerde nach einem
  Sprachwechsel der alte Text gesendet.
- **Klick = sofort senden** (`_useExamplePrompt` → `sendMessage()`). Die Karte bleibt danach
  stehen, damit weitere Beispiele erreichbar sind.
- **FALLSTRICK – Index-Zuordnung DOM↔Verlauf:** Der Eintrag hat `role:"bot"`, erzeugt aber KEINE
  `.msg-row`. Alle Stellen, die eine DOM-Zeile per Rollen-Index auf `_chatHistory` abbilden
  (`_deleteBubble`, Mehrfach-Loeschen `onDelete`), muessen ihn ueberspringen – dafuer gibt es
  `_isRowEntry()`. Ohne das loescht ein Klick auf die erste Bot-Antwort den falschen Eintrag.
  `_submitEdit`/`truncateHistoryToUserIndex` zaehlen nur `user`-Eintraege und sind nicht betroffen.

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
- **Jeder Skill mit `config_schema` hat einen eigenen Settings-Reiter** (seit 2026-07-26):
  Das Zahnrad unter *Einstellungen → Skills → Installierte Skills* springt in diesen Reiter
  (Zuordnung `SKILL_TABS` in `frontend/js/skills.js`). Reiter ohne handgebaute Oberflaeche
  (google, telegram, browser_control, claude_bridge, agent_orchestrator, agent_autonomy_kit)
  werden von `frontend/js/skillcfg.js` **generisch aus dem Manifest** gerendert – ein neues
  `config_schema`-Feld erscheint dort ohne Frontend-Aenderung (`string`/`number`/`boolean`/
  `enum`/`secret` + `label`/`description`). Zwei Reiter mischen: WhatsApp (`skcfg-whatsapp`,
  ohne `debug_mode` – das hat seinen Toggle unter „Logs & Debug") und Wissen
  (`skcfg-knowledge`, nur `max_file_size_mb`).
  - Diese Reiter sind nur bei AKTIVEM Skill sichtbar (`SkillCfg.updateTabs()`, aufgerufen
    ueber `window.updateSkillCfgTabVisibility`). Ist der Reiter ausgeblendet, fallen die
    Zahnraeder auf den generischen Dialog zurueck (`_showConfigDialog`) – der bleibt auch
    fuer importierte Fremd-/OpenClaw-Skills ohne Reiter der Weg.
  - `POST /api/skills/{name}/config` **merged** serverseitig (`update_skill_config`), ein
    Reiter darf also eine Teilmenge der Felder schicken, ohne die anderen zu verlieren.
  - Neues Reiter-Skill anlegen: Knopf + Panel mit `<div id="skcfg-<skill>">` in
    `settings.html`, Eintrag in `TARGETS`/`TAB_BUTTONS` (skillcfg.js), `SKILL_TABS`
    (skills.js) und `SKILLCFG_TABS` (app.js).

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
- **`llm.py` hat KEINEN Modul-Import von `config`:** jede Funktion, die `config` nutzt, braucht
  ein lokales `from backend.config import config`. Fehlte in `GeminiProvider.generate_response`
  → **jeder** Gemini-Chat scheiterte still mit `NameError: name 'config' is not defined`
  (behoben 2026-07-27). Beim Erweitern von llm.py darauf achten.
- **Icon-Knoepfe in Klapp-Kopfzeilen brauchen `.kb-hdr-btn`**, nicht `.kb-btn-action`:
  Letztere ist ein grosser CTA (Akzent-Hintergrund, weisse Schrift, 0.45rem Padding) und fuellte
  im Telemetry-Reiter die Zeile mit Akzentfarbe. `.kb-btn-danger` war bei 0.72rem umgekehrt zu
  blass. `.kb-hdr-btn` (+ Modifier `.is-danger`) vereinheitlicht Groesse, Rahmen und Hover fuer
  LLM-Verlauf, Kontext/History und Tool-Audit-Log; Farben kommen aus `var(--danger)` per
  `color-mix`. Icon ist `⟳`/`×` als Textglyph statt Emoji – 🔄 wird je nach System farbig
  gerendert und passt sich keinem Theme an.
- **Neues Profil-Feld = ZWEI Stellen in config.py:** `create_profile()` (Anlegen) UND die
  Whitelist in `update_profile()`. Fehlt eine, wird das Feld still verworfen – genau so war
  `prompt_tool_calling` jahrelang wirkungslos, obwohl Frontend und agent.py es kannten.
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
