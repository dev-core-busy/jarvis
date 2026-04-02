# Jarvis – AI Desktop Agent

## Projekt
Autonomer KI-Agent auf einem Linux-Server (Debian 13) mit Web-Frontend, Desktop-Steuerung via VNC und WhatsApp-Integration.

## Server & Deployment
- **Server:** root@191.100.144.1, SSH: `ssh -i /c/users/bender/.ssh/id_rsa root@191.100.144.1`
- **Zwei Pfade:** `/opt/jarvis/` (systemd Service) + `/home/jarvis/jarvis/` (Entwicklung) – Dateien an BEIDE deployen!
- **Desktop-User:** `jarvis` (autologin via lightdm), Web-Login: `jarvis/jarvis`
- **Deploy:** Lokal schreiben + `scp` (keine Heredocs ueber SSH – Quoting-Probleme mit f-strings)
- **Services:** `systemctl restart jarvis.service` + `systemctl restart whatsapp-bridge.service`

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
  skills/
    manager.py     – SkillManager (enable/disable/config/reload)
    loader.py      – Dynamisches Skill-Loading
  tools/
    base.py        – BaseTool Klasse
    shell.py       – Shell-Ausfuehrung mit Live-Streaming (stdout zeilenweise via WebSocket)
    subagent.py    – spawn_agent Tool (Hauptagent startet Sub-Agents)
    vector_store.py – ChromaDB Vektor-Datenbank fuer Wissenssuche
    desktop.py, filesystem.py, screenshot.py, knowledge.py, memory.py
    whatsapp.py    – WhatsApp Send/Status Tools
    wa_logger.py   – Strukturiertes WhatsApp-Logging (JSON-Lines)
frontend/
  index.html       – Single-Page App
  css/style.css    – Glassmorphism Dark Theme (CSS Custom Properties)
  js/app.js        – Haupt-UI + WebSocket + Login
  js/skills.js     – Skills Settings UI
  js/whatsapp.js   – WhatsApp Settings + Log-Viewer
  js/vision.js     – Vision Settings (Dashboard/Training/Profile/Aktionen)
  js/vnc.js        – noVNC Integration
  js/websocket.js  – WebSocket Manager
skills/
  browser_control/ – xdotool-basierte Browser-Automation + CDP
  whatsapp/        – WhatsApp Skill (send + status Tools)
  vision/          – Gesichtserkennung (face_recognition/dlib, USB/IP-Kamera)
  example_skill/   – Template fuer neue Skills
services/
  whatsapp-bridge/index.js – Baileys Bridge mit Express API
data/
  knowledge/       – Wissensdatenbank (TF-IDF + ChromaDB Vektor-Suche)
  chroma_db/       – ChromaDB Persistenz (sentence-transformers Embeddings)
  memory.json      – Persistenter Key-Value Speicher
  logs/            – WhatsApp-Logs (JSON-Lines)
  vision/          – Gesichtserkennung (faces/, encodings.pkl, config.json, events.json)
```

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
- **ChromaDB** + **sentence-transformers** (`paraphrase-multilingual-MiniLM-L12-v2`)
- **vector_store.py**: PersistentClient, lazy-loaded Embedding-Singleton
- **Suchmodi** (konfigurierbar in Knowledge-Skill): Auto, TF-IDF, Vektor
  - Auto: versucht Vektor zuerst, Fallback auf TF-IDF
- **Frontend**: Toggle-Buttons (Auto/TF-IDF/Vektor) im Knowledge-Settings-Tab
- **numpy**: Muss < 2.1 bleiben (VM hat kein SSE4.2)

## Skill-System
- Skills liegen unter `skills/<name>/` mit `skill.json` (Manifest) + `main.py` (get_tools())
- Tools erben von `backend/tools/base.py:BaseTool`
- States persistiert in `settings.json` unter `skills`-Key
- API: `/api/skills`, `/api/skills/{name}/enable|disable|config`

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

# Logs pruefen
journalctl -u jarvis.service -f
journalctl -u whatsapp-bridge.service -f

# Deployen (von Windows aus)
scp -i /c/users/bender/.ssh/id_rsa <datei> root@191.100.144.1:/opt/jarvis/<pfad>
scp -i /c/users/bender/.ssh/id_rsa <datei> root@191.100.144.1:/home/jarvis/jarvis/<pfad>
```
