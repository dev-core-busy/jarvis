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
- **Benannte Ops mit harter Validierung:** systemctl (Unit-Whitelist), unlock_screen, switch_session, vnc_restart, chpasswd, sandbox_exec (nur `jarvis_sandbox*`), sandbox/egress_setup|teardown|status, apt_upgrades_setup|teardown|status, mount_share/umount_share (nur /mnt/), certbot_obtain, shell_root (generisch)
- **FALLSTRICK Deploy:** Der Broker ist ein EIGENER Prozess mit eigener Kopie von `backend/broker/*`. Wer dort etwas aendert (neue Op!), muss **`systemctl restart jarvis-broker.service`** – ein Neustart von `jarvis.service` allein genuegt nicht, die neue Op ist dann „unbekannt" und der Endpunkt antwortet 502. Nach dem Neustart dauert es einige Sekunden bis zum Socket: `start_jarvis_root.sh` startet erst x11vnc und websockify, dann den Broker („[Broker] Bereit auf …" im Journal). Wer sofort danach testet, bekommt denselben 502 und sucht den Fehler im Code.
- **Auditierbare Freigabeliste:** Jede Op wird beim ersten Auftauchen als Policy-Eintrag registriert (`/etc/jarvis/broker-policy.json`, root-only). System-Ops: auto-allow (widerrufbar). `shell_root:<befehl>`: startet **pending** → Admin entscheidet unter *Einstellungen → Sicherheit → Root-Freigaben* (`/api/broker/*`, security_incidents.js)
- **Shell-Routing:** `shell.py::_needs_root()` erkennt Root-Befehle (sudo/systemctl/apt/mount/...); privilegierte Nutzer → Broker shell_root, Domain-Nutzer → Broker sandbox_exec (runuser). Audit: `/var/log/jarvis-broker-audit.jsonl`
- **Migration pro Server:** `bash deploy/security/setup_broker.sh` (chown, Units installieren, Dienste starten, Verifikation). Alt-Betrieb (Backend als root, repo-root `jarvis.service`) funktioniert weiter: broker_client fuehrt Ops dann lokal aus (inkl. Policy/Audit)
- **Achtung:** settings.json-Schreiben erhaelt Eigentuemer (`config._write_preserve_owner`) – der root-Broker darf die Datei dem jarvis-Backend nicht entziehen

## Automatische Sicherheitsupdates (Schalter, seit 2026-07-28)
- **Warum es das gibt:** Auf ECHT hatte ein lokaler Admin eine eigene Einheit
  `apt-daily-custom.timer` gebaut, die naechtlich `apt-get update` **und
  `apt-get autoremove -y`** ausfuehrte. Das Aufraeumen war das Problem –
  unbeaufsichtigtes Paket-Loeschen kann Abhaengigkeiten des Agenten entfernen
  (cmake/boost fuer dlib, ffmpeg fuer Whisper, X/VNC, LibreOffice-Teile), und der
  Dienst bricht Stunden spaeter ohne erkennbaren Zusammenhang. Beim Rueckbau fiel
  auf: `unattended-upgrades` war gar nicht installiert, die Maschine bekam also
  **keine** Sicherheitspatches. Der Schalter macht daraus einen bewussten,
  umschaltbaren Zustand statt undokumentierter Handarbeit.
- **Code:** `backend/apt_upgrades.py` (analog `egress_guard.py`/`sandbox_guard.py`)
  + Broker-Ops `apt_upgrades_setup|teardown|status` + `GET/POST
  /api/security/unattended[/setup|/teardown]` + Panel unter *Einstellungen →
  KI & System → System-Einstellungen* (fuenfte `.tuning-group`).
  **Die Logik liegt weiter in `security_incidents.js`** (`sec-unatt-*`), das
  Panel aber in einem ANDEREN Reiter – deshalb ruft `app.js` beim Aktivieren des
  Reiters `SecurityIncidents.onShowUnattended()` (bindet idempotent + laedt den
  Status). Ohne diesen Aufruf waeren die Knoepfe unverdrahtet und der Status
  leer, solange der Sicherheits-Reiter nicht geoeffnet wurde.
- **Die Begrenzungen SIND das Feature** (`/etc/apt/apt.conf.d/52jarvis-unattended`):
  nur `origin=Debian,label=Debian-Security`; `Automatic-Reboot "false"`;
  `Remove-Unused-Dependencies "false"` **und** `Remove-New-Unused-Dependencies
  "false"` – genau das, was gerade zurueckgebaut wurde, darf nicht durch die
  Hintertuer zurueckkommen. Eigene Datei (52 > 50), damit ein
  `dpkg-reconfigure unattended-upgrades` sie nicht ueberschreibt.
- **FALLSTRICK `#clear` – apt ERGAENZT Listen, es ersetzt sie nicht.** Die erste
  Fassung schrieb nur den eigenen `Origins-Pattern`-Block. Wirksam war danach die
  VEREINIGUNG mit der Vorgabe aus `50unattended-upgrades`, also auch
  `origin=Debian,codename=${distro_codename},label=Debian` = **alle** Updates.
  Nachgewiesen auf DEV: `apt-config dump` zeigte vier Eintraege (einer davon
  `label=Debian`) und der Trockenlauf meldete 282 Kandidaten statt der 93
  Sicherheitspakete – die zentrale Zusage des Moduls war damit gebrochen. Fix:
  `#clear Unattended-Upgrade::Origins-Pattern;` (+ `Allowed-Origins` fuer
  Alt-Setups) VOR dem eigenen Block.
- **Deshalb prueft `_limits_ok()` die WIRKSAME Liste, nicht den Dateiinhalt:**
  `effective_origins()` liest `apt-config dump` und verlangt, dass JEDER Eintrag
  `Debian-Security` enthaelt. Ein Test, der nur „`Debian-Security` kommt im Dump
  vor" prueft, ist bei einer Vereinigung gruen und beweist nichts – genau dieser
  zu schwache Test hat den Fehler zunaechst durchgelassen. Das Panel zeigt die
  Liste jetzt an („Wirksame Paketquellen").
- **Ausschalten laesst den Index-Refresh AN** (`Update-Package-Lists "1"`) und das
  Paket installiert. Grund: ein veralteter Index laesst Installationen mit
  `404 Not Found` scheitern – genau daran starb auf ECHT die LibreOffice-
  Installation (die Version im lokalen Index lag nicht mehr auf dem Spiegel).
  Deshalb fuehrt `manager.py::_apt_install` zusaetzlich immer selbst
  `apt-get update` unmittelbar vor der Installation aus.
- **Status wird aus `apt-config dump` gelesen**, nicht aus der Datei: nur so sieht
  man, was apt ueber ALLE `conf.d`-Dateien hinweg tatsaechlich anwendet (eine
  spaeter einsortierte Datei kann die eigene ueberstimmen).
- **`setup()` darf KEINEN Trockenlauf enthalten.** Erste Fassung endete mit
  `status(live=True)`; das Einschalten haing dadurch **ueber zwei Minuten**, obwohl
  die eigentliche Arbeit in 0,5 s fertig war. `unattended-upgrade --dry-run`
  simuliert JEDES Kandidatenpaket einzeln und braucht bei Rueckstand Minuten.
  Jetzt: `setup()` → `status(live=False)` (0,5 s), Trockenlauf nur auf Knopfdruck
  mit hartem Deckel `DRY_RUN_TIMEOUT = 45` s; laeuft er ab, sagt die Meldung
  ausdruecklich, dass das **nichts** ueber die Einstellungen aussagt (die stehen
  darueber, aus `apt-config` gelesen). Das Frontend sperrt den Knopf waehrenddessen
  und nennt die Wartezeit.
- **Timer nur `enable`, NICHT `enable --now`:** beide Timer haben
  `Persistent=true`, ein Start kann den Dienst SOFORT ausloesen (`apt-get update`
  bzw. `unattended-upgrade`), der haelt dann die apt-Sperre und laesst jede weitere
  Aktion warten. Sie feuern ohnehin nach Plan.

## Auftraggeber-Bindung zeitversetzter Läufe (Fix 2026-07-28)
**Der Vorfall:** Auf ECHT lief am 28.07. um 03:00 der Cron-Job `system_auto_update`
(`git pull && systemctl restart jarvis.service`) und wurde mit „der aktuell angemeldete
Benutzer hat keine Berechtigung" abgebrochen – obwohl niemand angemeldet war. Der Job hatte
die Rechte eines *fremden Chat-Nutzers* geerbt. Dieselbe Mechanik trifft in der anderen
Richtung: **ein Domain-Nutzer konnte per Chat einen Cron-Job anlegen, der später mit
Root-Rechten feuerte.**
- **Ursache – drei Zeilen, die zusammen die Lücke bilden:**
  1. `agent.py::_execute_tool` entschied über Rechte anhand von `self._current_username`.
  2. `_LOCAL_PRIVILEGED_USERS = {"jarvis", "root", ""}` – **der leere String ist privilegiert.**
  3. `run_task_headless()` setzte diesen Wert NIE, und Cron/Watcher/WhatsApp/Telegram/Notify
     laufen alle auf dem **geteilten** Hauptagenten (`get_or_create_main()`).
  Ergebnis: der zeitversetzte Lauf bekam die Identität, die zufällig zuletzt am Objekt hing –
  nach einem Dienststart `""` → `_root_broker=True`, keine Shell-Deny-Muster, kein
  Pfad-Confinement, keine Dokument-Eigentümer-Schranke. **Nichtdeterministisch:** derselbe Job
  läuft je nach Vorgeschichte als root oder scheitert an einer Domain-Sperre.
- **Die Lösung heißt Actor-Bindung** (`agent.py`): `_actor_cv` (ContextVar) hält
  `(username, privileged)` für den LAUFENDEN Auftrag, `actor_scope()` setzt und **stellt
  zurück**, `_actor_is_privileged()` ist ab jetzt die EINZIGE Quelle für die Rechtefrage.
  Alle vier Gate-Stellen im Dispatch (Tool-Sperrliste, filesystem, shell, Root-Broker) prüfen
  nur noch das – nicht mehr den Namen.
  - **ContextVar, nicht Objekt-Attribut:** ein Cron-Lauf um 03:00 und ein Chat-Auftrag können
    GLEICHZEITIG auf demselben Agenten liegen. Ein Attribut würde den Sicherheitsentscheid des
    jeweils anderen Laufs mitregieren; jeder `asyncio.Task` hat seine eigene Kopie, Sub-Agenten
    erben sie. Der Test „parallel Chat + Cron" prüft genau das.
  - `run_task_headless(actor=…)` ist **fail-closed**: nicht übergeben = unprivilegiert.
    Der Sentinel `_ACTOR_UNSET` unterscheidet das von `actor=None` (= bestehenden Kontext
    behalten, nur für Läufe, die schon in einem Scope stehen).
  - `_ANON_ACTOR = "__unprivilegiert__"`: unprivilegierte Läufe OHNE Namen bekommen einen
    Platzhalter, **nie den leeren String** – leer heißt bei `set_tool_user()` „keine Schranke",
    fremde Dokumente wären damit wieder lesbar.
- **Jeder Job trägt seinen Besitzer** (`scheduler.py`, `file_watcher.py`): `owner` +
  `owner_privileged` + `created_via` werden beim Anlegen festgeschrieben; `_actor_for()` baut
  daraus den Actor. **Privilegiert wird nur, wer beides hat** (`owner_privileged and owner`) –
  ein manipulierter Eintrag ohne Besitzer zählt nicht.
  - **`UPDATABLE_FIELDS` ist die Kernschranke:** `update_job(**fields)` nahm vorher BELIEBIGE
    Felder – ein Domain-Nutzer hätte sich per `PUT /api/cron/<id>` einfach
    `owner_privileged: true` gesetzt. Jetzt Whitelist; die Bindung ändert **nur** `claim_job()`.
  - **Altbestand ohne `owner` läuft unprivilegiert** (fail-closed) und wird beim Laden
    protokolliert. Nicht geraten: der Besitzer ist nicht rekonstruierbar. Reparatur =
    `POST /api/cron/{id}/claim` (Admin, `require_local_auth`) bzw. 🔑 in der Oberfläche.
    **Das ist die bewusste Attestierung** – der einzige Weg zu Systemrechten.
- **Kanäle ohne Konto sind IMMER unprivilegiert** – nicht konfigurierbar: WhatsApp
  (`wa:+49…`), Telegram (`tg:<chat>`), Notify-API (`api:<quelle>`). Der Absender ist eine
  Telefonnummer/ein Gerät, keine Anmeldung. Wer hier Systemrechte braucht, legt einen
  Cron-Job als Admin an.
- **Zweite Schranke beim ANLEGEN** (`cron_tool.py::_root_intent`): ein unprivilegierter
  Benutzer darf keinen Auftrag mit System-/Root-Absicht anlegen (sudo/systemctl/apt/`.ssh`/
  `/etc/shadow`/…), Verstoß geht in `security_guard`. Das ist ausdrücklich **Zusatz**: die
  harte Garantie ist die Bindung – ein umformulierter Text läuft später einfach in die Rechte
  des Anlegenden. Auch an `POST /api/cron` und `POST /api/watchers` geprüft.
- **Fremde Aufträge sind unsichtbar:** `cron_list` zeigt Nicht-Admins nur eigene Jobs (nennt
  die **Anzahl** ausgeblendeter, sonst hält das Modell die Liste für vollständig),
  `cron_delete` antwortet bei fremden Jobs „nicht gefunden" (nicht „verboten"),
  `GET/PUT/DELETE/run /api/cron` filtern über `_cron_visible()`. **`run` nutzt die Rechte des
  BESITZERS** – sonst wäre „fremden Job starten" der bequemste Eskalationsweg.
- **Werkzeuge, die die Grundlage künftiger Läufe ändern, sind für Domain-Nutzer gesperrt**
  (`_BLOCKED_TOOLS_FOR_LDAP`): `reflection` (schreibt `data/instructions/*.md` → fließt in
  JEDEN System-Prompt, auch den eines Admins; kann Code-Fixes anwenden), `evolution_propose|
  apply|cycle` (schreibt/aktiviert Skills), `queue_add` (Aufträge für spätere autonome Läufe).
  Das sind dieselben Persistenz-Substrate wie Cron, nur ohne Uhrzeit.
- **Die Auftrags-Dateien selbst sind zu** (`sandbox.py`): `data/scheduled_jobs.json`,
  `data/file_watchers.json`, `data/security_state.json` stehen in `_APP_DENY_REL` +
  `SHELL_SECRET_PATHS` und werden von `harden_data_dirs()` auf **0640** gesetzt
  (`PRIVATE_FILES`). Ohne das umgeht ein `cat` in der Sandbox den `cron_list`-Filter –
  genau die Lücke, die am selben Tag für `data/chats` geschlossen wurde.
- **Verifiziert auf DEV:** 17 Dispatch-Tests (Rechte-Matrix inkl. Nachwirkung, Parallelität,
  Sub-Agent-Vererbung) + 22 Manager-Tests (Bindung, Whitelist, Übernahme, Migration,
  Sichtbarkeit) = 39/39. Live geprüft: Shell- und filesystem-Zugriff auf die Auftragsdatei
  gesperrt, `data/knowledge` weiter lesbar, Dienst nach Neustart aktiv (HTTP 200).
- **Merkregel:** Ein Lauf ohne angemeldeten Benutzer ist NICHT dasselbe wie ein Lauf mit
  Systemrechten. Wer einen neuen entkoppelten Auslöser ergänzt (Queue, Webhook, Mail-Trigger),
  muss `actor=` mitgeben – sonst ist er still unprivilegiert (gewollt), und wer ihn
  privilegiert braucht, muss den Besitzer speichern.

## Zeitversetzte Auslöser nur für Admins (2026-07-29)
**Was der Test vom 29.07. zeigte:** Die Bindung vom 28.07. regelt, **mit welchen Rechten** ein
zeitversetzter Lauf feuert – nicht, **ob** ein Nicht-Admin sich überhaupt einen einrichten darf.
Ein Domain-Nutzer (und damit auch eine per Prompt-Injection gesteuerte WhatsApp-Nachricht) konnte
weiter einen wiederkehrenden Auftrag anlegen, der **sofort aktiv** ist und außerhalb jeder
Chat-Sitzung einen Agenten mit vollem Werkzeugkasten startet. Es gab kein `enabled`-Feld im
Werkzeug und keine Freigabe. Das war inkonsistent zur eigenen Sperrliste: `queue_add`,
`reflection`, `evolution_*` sind genau deshalb gesperrt – `cron_create` tat dasselbe, nur mit Uhr.
- **Gesperrt ist jetzt das ANLEGEN und ÄNDERN, nicht das Sehen/Löschen:**
  `cron_create` steht in `_BLOCKED_TOOLS_FOR_LDAP`; `POST/PUT /api/cron`,
  `POST /api/cron/{id}/run`, `POST/PUT /api/watchers` verlangen Admin
  (`main.py::_require_trigger_admin`). `GET` und `DELETE` bleiben mit Eigentümer-Filter offen –
  beides schafft keine Persistenz, und der **Altbestand muss aufräumbar bleiben**.
  `cron_list`/`cron_delete` bleiben aus demselben Grund erlaubte Werkzeuge.
- **`PUT` ist gleichwertig mit Anlegen.** Wer `task`/`cron` eines bestehenden Auftrags umschreiben
  darf, hat einen neuen Dauerauftrag – über jeden Altbestand-Job wäre die Sperre sonst umgehbar.
  Dasselbe gilt für `run`: ein gespeicherter Auftragstext wäre sonst der bequemste Weg, einen
  Agentenlauf ohne nachvollziehbare Chat-Sitzung auszulösen.
- **Nur der Treffer wird als Verstoß protokolliert** (`cron_tool.record_cron_denied`):
  `security_guard.record_violation()` sperrt Konten ab einer Schwelle. Zählte jeder abgelehnte
  Versuch, sperrte „erinnere mich täglich um 8" beim dritten Mal einen harmlosen Benutzer. Der
  Versuch steht im Journal; als Verstoß gilt nur, was `_root_intent` trifft (Angriffsindiz).
- **Nebenbefund, mitbehoben:** `POST /api/update/settings` legte den Job `system_auto_update`
  **ohne `owner`** an. Seit dem 28.07. lief er damit unprivilegiert und wäre an
  `git pull`/`systemctl restart` gescheitert – das Auto-Update war still tot. Jetzt
  `owner=user, owner_privileged=True` (der Endpunkt verlangt `require_local_auth`).

### Erinnerungs-Ausnahme (`backend/reminders.py`)
Messenger-Kanäle sind **immer** unprivilegiert (`wa:+49…`, `tg:<chat>`) – auch das Telefon des
Admins. Mit der Sperre allein wäre „Erinnere mich morgen um 06:15 per WhatsApp" tot. Die Ausnahme
holt genau das zurück, ohne die Lücke zu öffnen; **vier Bedingungen, alle nötig:**
1. **Whitelist** – nur freigegebene Absender (*Einstellungen → Sicherheit → Erinnerungen per
   Messenger*, `GET/POST /api/reminders/senders`, Feld `reminder_senders` im `extra`-Bereich).
   Vorgabe ist LEER: ohne bewusste Freigabe kann niemand etwas anlegen.
2. **KEIN AGENT** – der Job trägt `kind="reminder"` + `payload={channel,to,message}` und wird von
   `scheduler._execute` **direkt versendet**, ohne LLM und ohne Werkzeuge. **Das ist der Kern:**
   liefe der gespeicherte Text später durch ein Modell, wäre der Nachrichtentext wieder ein
   zeitversetzt ausgeführter Auftrag – also genau die geschlossene Lücke. Wer diesen Zweig
   anfasst, macht die Ausnahme zur Hintertür.
3. **Nur an sich selbst** – der Empfänger kommt aus der Actor-Kennung, NICHT aus dem Auftragstext.
   `_reminder_message()` holt aus „Sende WhatsApp an +49…: Text" nur den *Text*; die Nummer darin
   wird verworfen. Sonst wäre die Ausnahme ein Versandweg für fremde Nummern (Spam/Phishing).
4. **Einmalig + Deckel** – nur `once=True` (wiederkehrend = dauerhafte Präsenz = Admin-Sache),
   höchstens `MAX_OPEN=20` offene je Absender (ohne Deckel legt eine injizierte Nachricht
   tausende Jobs an – DoS ohne Rechteerhöhung), Text auf `MAX_MESSAGE_LEN=500` gekürzt.
- **Zwei Tore, beide fail-closed:** `agent.py::_reminder_exempt()` lässt `cron_create` im Dispatch
  überhaupt erst durch, `CronCreateTool` prüft danach selbst noch einmal (ein Skill könnte das
  Werkzeug außerhalb des Dispatchs benutzen). Jeder Fehler beim Prüfen = keine Ausnahme.
- **`kind`/`payload` stehen NICHT in `UPDATABLE_FIELDS`** – sonst ließe sich eine Erinnerung
  nachträglich in einen Agenten-Job umschreiben.
- **Telefonnummern werden normiert** (`_norm_phone`): JID-Suffix, LID-Anteil, `00`-Präfix,
  Leerzeichen. Ohne das wäre die Whitelist ein Zufallsspiel – dieselbe Nummer stünde drin und
  würde je nach Eingangsweg nicht erkannt. Ungültige Einträge werden **verworfen, nicht geraten**.
- **`WA_TASK_PROMPT` wurde umgeschrieben:** vorher stand dort „immer cron_create verwenden – nie
  ablehnen!". Ein Prompt, der etwas verspricht, was der Dispatch verweigert, produziert
  Endlosversuche und Fehlermeldungen beim Absender. Jetzt: nur einmalige Erinnerungen über
  `nachricht`, klarer Hinweis auf den Administrator, ausdrücklich **keine** Aktionszusagen.
  Aus demselben Grund sind die Beispiele „Starte den Webserver neu → `systemctl restart`" und
  „Liste die letzten Logs → `journalctl`" **entfernt** (2026-07-29) und durch einen Abschnitt
  „WAS ÜBER WHATSAPP NICHT GEHT" ersetzt: WhatsApp ist immer unprivilegiert, `systemctl` fällt
  in `_LDAP_SHELL_FORBIDDEN` – das Beispiel lud also zu einem Aufruf ein, der als
  **Sicherheitsverstoß protokolliert** wird (und bei Wiederholung das Konto sperren könnte).
  System-Logs sind für den Sandbox-Benutzer ohnehin nicht lesbar.
- **Oberfläche:** Klappabschnitt im Sicherheits-Reiter (`sec-sect-rem-*`, Logik in
  `security_incidents.js::loadReminders/saveReminders`, Collapse-Eintrag in `app.js`).
  **Sichtbar nur, wenn WhatsApp ODER Telegram aktiv ist** (`app.js::
  updateReminderSectionVisibility`, gleiches Muster wie der SAP-Berechtigungsblock
  `sec-sub-sap`): ohne Kanal gibt es keinen Absender `wa:`/`tg:`, die Freigabe wäre eine
  Freigabe für nichts. `sec-sect-rem-box` startet deshalb mit `display:none` im HTML –
  sonst blitzt der Abschnitt beim Öffnen auf und verschwindet wieder. Aufgerufen in
  `openModal()` **und** an den drei Stellen in `skills.js`, die nach einem Skill-Wechsel die
  Reiter-Sichtbarkeit erneuern. Zwei Feinheiten, die zusammengehören: `loadReminders()`
  bricht bei versteckter Box ab (kein Abruf für einen unsichtbaren Abschnitt), und beim
  Sichtbar**werden** ruft `updateReminderSectionVisibility()` es nach – ohne das stünde die
  Liste nach dem Einschalten eines Kanals leer da, obwohl Einträge gespeichert sind.
  Der Hinweis nennt die tatsächlich aktiven Kanäle (`sec-rem-channels`).
  Der Cron-Reiter zeigt bei `kind='reminder'` das Abzeichen „Erinnerung" und **keinen
  🔑-Übernehmen-Knopf** (Systemrechte sind dort sinnlos – es wird nichts ausgeführt).
- **Verifiziert auf DEV:** 61 Einheitentests (Normierung, Whitelist, Dispatch-Ausnahme,
  Tool-Matrix, Deckel, Scheduler ohne Agent, Update-Whitelist) + 21 Endpunkt-Tests
  (403/404/200-Matrix für Cron/Watcher/Freigaben) = 82/82. Live: Routen registriert und
  401-geschützt, Dienst nach Neustart aktiv (HTTP 200), `data/scheduled_jobs.json` und
  `data/file_watchers.json` unverändert.

## Login-Freigabe: Benutzerliste ODER Gruppe (Fix 2026-07-29)
**Der Vorfall:** Ein Domain-Benutzer konnte sich anmelden, solange er unter *Einstellungen →
Sicherheit → Berechtigungen → Anmeldung* als **Benutzer** eingetragen war. Wurde er dort entfernt
und stattdessen eine **AD-Gruppe** eingetragen, in der er Mitglied ist, war die Anmeldung tot –
obwohl `memberOf` die Gruppe nachweislich enthielt (am DC geprüft: direkte Mitgliedschaft).
- **Ursache:** `_ad_user_allowed()` behandelte eine nicht-leere `ad_allowed_users`-Liste als
  ALLEINENTSCHEIDEND: `if plain not in allowed: return False` – der Gruppen-Zweig darunter wurde
  **nie erreicht**. Wer neben der Liste eine Gruppe eintrug, sperrte damit jedes Gruppenmitglied
  aus, das nicht zusätzlich in der Liste stand. Die Symptombeschreibung „Benutzer raus, Gruppe
  rein" trifft das genau dann, wenn **noch andere Benutzer in der Liste stehen** – die Liste war
  nicht leer, also entschied sie weiter.
- **Die Oberfläche versprach das GEGENTEIL** – an fünf Stellen „– hat Vorrang gegenüber
  Benutzerliste wenn beide gesetzt" und zusätzlich „⚠ Wenn eine Gruppe eingetragen ist, wird die
  Benutzerliste ignoriert." Dazu meldete `GET /api/settings/ldap` bei gesetzter Gruppe
  `access_mode: "group"`, obwohl die Liste entschied. Der Fehler war von außen deshalb nicht
  erklärbar: die Anzeige behauptete „Gruppen-Filter aktiv", während die Liste sperrte.
- **Jetzt ODER-verknüpft** – Liste und Gruppe sind zwei Freigabewege, jeder genügt allein. Das ist
  dieselbe Semantik, die **alle anderen** Berechtigungsfelder schon immer hatten (Wissens-Editoren,
  Internet, Admins, SAP: `if plain in allowed: return True` … dann Gruppen-Check). Der Login war
  der einzige Ausreißer.
- **Vier Stellen gehören zusammen – eine allein reicht NICHT:**
  1. `_ad_user_allowed()` – die Login-Entscheidung.
  2. `_login_still_allowed()` – läuft bei **jedem Request**. Gab vorher bei nicht-leerer Liste
     hart `_norm_login(username) in allowed` zurück: ein über die Gruppe angemeldeter Benutzer
     wäre beim ersten Request wieder hinausgeflogen (403 NOT_AUTHORIZED direkt nach erfolgreichem
     Login). Jetzt: in der Liste → True, sonst → `bool(allowed_group)`, weil die Mitgliedschaft
     ohne Benutzer-Bind (= ohne Passwort) live nicht prüfbar ist.
  3. `_revalidate_ad_groups_once()` – `enforce_login` war `bool(group) and not users_raw`, die
     Nachprüfung war bei gesetzter Liste also komplett aus. Jetzt greift sie, sobald eine Gruppe
     konfiguriert ist, **überspringt aber jeden Benutzer aus der Liste** (`allowed_set`) – sonst
     würde die 10-Minuten-Revalidierung genau die Benutzer abmelden, die per Liste freigegeben sind.
  4. `access_mode` – neuer Wert **`users_group`**, wenn beides gesetzt ist (Frontend zeigt Liste
     UND Gruppe an). Ein Modus, der einen der beiden Werte verschweigt, ist die Anzeige, die den
     Fehler überhaupt erst unerklärbar gemacht hat.
- **Diagnose-Log nachgezogen:** Der Gruppen-Zweig sucht mit dem Bind des ANMELDENDEN Benutzers.
  Scheiterte diese Suche, flog die Ausnahme bis in `authenticate_linux_user` und erschien nur als
  generisches „[AUTH] AD Fehler" – das sieht wie ein Netzproblem aus. Jetzt eigenes `try/except`
  mit Klartext, und „nicht im Directory gefunden" nennt die **Suchbasis** (`DC=…` aus `ad_domain`
  abgeleitet): liegt das Konto in einer anderen Domäne als der konfigurierten, findet die Suche
  nichts, obwohl der Bind per UPN geklappt hat. Der Bind allein beweist die Suchbasis NICHT –
  im Benutzerlisten-Modus wird gar nicht gesucht, deshalb fällt eine falsche Domäne dort nie auf.
- **Merkregel:** Zwei Freigabefelder nebeneinander sind für den Benutzer additiv. Wenn eines das
  andere aushebelt, ist das ein Fehler – und wenn Oberfläche und Status-Endpunkt dazu noch das
  Gegenteil behaupten, kostet es Stunden.

### „Leer = niemand" statt „leer = alle" (Vorgabe 2026-07-29)
Beim Aufräumen fiel auf, dass **leer** in diesem einen Panel je Feld das Gegenteil bedeutete:
Anmeldung leer = **jeder** Domänen-Benutzer, Wissens-Editoren/Internet/Administratoren leer =
**niemand** (explizites Opt-in). Auf DEV konnte sich damit jeder Domänen-Benutzer mit gültigem
Passwort anmelden, obwohl kein einziger Eintrag gesetzt war. Auf Anweisung des Nutzers gilt jetzt
überall dieselbe Regel: **wer nicht eingetragen ist, darf nicht.**
- `_ad_user_allowed()`: beide Felder leer → `False` (mit Klartext-Log, das den Weg zur Einstellung
  nennt). Der frühere `return True` ist weg.
- **`_login_still_allowed()` braucht die Prüfung EBENFALLS** – sonst behielte jede bestehende
  Sitzung ihren Zugriff, bis sich der Benutzer abmeldet, und das Leeren der Felder wäre eine
  Maßnahme ohne Wirkung.
- `access_mode` heißt in diesem Fall **`none`** (vorher `open`); Oberfläche zeigt „⛔ Niemand
  freigegeben" plus Warnkasten `security.ad_warn_none`. Feldhinweis und Platzhalter sagen jetzt
  „leer = niemand" statt „Leer lassen für alle Domänen-Benutzer".
- **Der lokale Benutzer `jarvis` ist der Rückweg** und bewusst NICHT betroffen: er authentifiziert
  per PAM in `authenticate_linux_user`, **bevor** AD überhaupt befragt wird (`ALLOWED_USERS`), und
  `_login_still_allowed` gibt für ihn früh `True` zurück. Ohne diese Ausnahme wäre eine leere
  Freigabe ein Totalausschluss ohne Weg zurück in die Einstellungen.
- **Beim Ausrollen ist das eine abschaltende Änderung:** Wo bisher „leer" stand, meldet sich nach
  dem Neustart NIEMAND mehr per AD an. Vor dem Deploy auf einem System mit leeren Feldern also
  zuerst den eigenen Benutzer (oder die Gruppe) eintragen – oder danach als lokaler `jarvis`
  anmelden und nachtragen.
- **Verifiziert:** die Rechte-Matrix wuchs auf 34/34 (leer→niemand am Login UND pro Request,
  Modus `none`, kein `open` mehr im Endpunkt, lokaler `jarvis` bleibt trotz leerer Freigabe drin).
- **Verifiziert auf DEV:** 29 Prüfungen (Rechte-Matrix aus Liste/Gruppe/Mitgliedschaft, CN statt
  DN, mehrere Gruppen, Benutzer nicht im Verzeichnis, scheiternde LDAP-Suche, kein zusätzlicher
  LDAP-Roundtrip bei Listen-Treffer, `_login_still_allowed`, Revalidierungs-Entzug, `access_mode`)
  = 29/29; der alte Stand fällt in genau 5 davon durch, inklusive des gemeldeten Falls. Gegen den
  echten DC geprüft, dass `andrea.ladd` direktes Mitglied von `DP-BEFUNDKOMMUNIKATION` ist.
  Dienst nach Neustart aktiv, `/settings` HTTP 200.

## AD-Picker: Mitgliederliste + Klick auf den ganzen Eintrag (2026-07-29)
- **Der Klick auf den Eintragstext hat NICHTS getan** (`ldap_picker.js`). Der Treffer ist ein
  `<label>` um die Checkbox, ein Klick darin schaltet sie also **schon vom Browser aus** um.
  Der Handler schaltete zusätzlich selbst (`if (e.target !== cb) cb.checked = !cb.checked`), und
  weil das `<label>` den Klick danach an die Checkbox weiterreicht, kippte sie **zweimal** –
  unterm Strich gar nicht. Nur ein Treffer genau auf das 13-Pixel-Kästchen wirkte. Jetzt hört der
  Picker ausschliesslich auf `change` der Checkbox und schaltet **nie selbst**. Gilt für Benutzer-
  und Gruppen-Picker (`ad-allowed-users`, `ad-allowed-group`, Internet/Admins/Editoren/SAP).
  **Merkregel:** In einem `<label>` ist die Aktivierung Browser-Sache – wer dort zusätzlich per JS
  schaltet, hebt sich selbst auf.
- **Gruppen-Mitglieder auf Klick:** Der Gruppen**name** ist jetzt ein Knopf (`.ldap-members-btn`,
  gepunktet unterstrichen, 👥) und öffnet ein Unter-Popup mit den Mitgliedern. Der restliche
  Eintrag schaltet weiter die Auswahl um – der Knopf muss deshalb `preventDefault()` **und**
  `stopPropagation()` rufen, sonst aktiviert er über das `<label>` doch die Checkbox.
  Escape schliesst **zuerst** das Unter-Popup (`membersOpen()`), sonst bliebe eine Mitgliederliste
  ohne Bezug über einem geschlossenen Picker stehen; `close()` räumt es ebenfalls mit ab.
- **`ldap_directory.group_members(group)`** + `POST /api/ldap/group_members` (Admin,
  `require_local_auth`; Body `{group|dn,[password],[bind_user]}` → `{cn,dn,members:[{sam,display,
  mail,kind}],count}`). `group` darf **DN oder blosser CN** sein – die Token-Liste erlaubt beides
  (Auswahl liefert den DN, manuelle Eingabe oft nur den Namen).
- **Gelesen wird über `(memberOf=<dn>)`, NICHT über das `member`-Attribut der Gruppe:** dessen
  Werte liefert AD ab ~1500 Einträgen nur in Häppchen (Range-Retrieval), die Liste wäre dann
  stillschweigend unvollständig.
- **Bewusst nur DIREKTE Mitgliedschaften** – genau die prüft auch die Anmeldung
  (`_ad_user_allowed` vergleicht `memberOf`). Eine Liste, die zusätzlich verschachtelte Mitglieder
  zeigt, würde Zugriff versprechen, den der Login verweigert. Verschachtelte Gruppen erscheinen als
  Eintrag mit `kind="group"` (🗂️ + Beschriftung „verschachtelte Gruppe"), Mitglieder über die
  **Primärgruppe** (`primaryGroupID`, typisch „Domänen-Benutzer") fehlen hier wie dort – der
  Hinweistext unter der Liste sagt beides ausdrücklich.
- **Das On-Demand-Passwort wird wiederverwendet** (`_cred`): ohne Service-Konto müsste der Admin es
  sonst für die Mitgliederliste ein zweites Mal eingeben.
- **Verifiziert:** 12 Backend-Prüfungen gegen den echten DC (per DN und per CN, Benutzer vor
  Gruppen sortiert, verschachtelte Gruppe erkannt, unbekannte Gruppe → RuntimeError, unbekannter
  DN → leere Liste, Filter-Escaping von `(`/`*`) + 32 UI-Prüfungen in jsdom gegen die echten
  Dateien (Textklick setzt/löscht die Checkbox, Vorbelegung, Popup-Inhalt, keine Auswahl-Änderung
  beim Namensklick, Escape-Reihenfolge, Aufräumen, DE/EN-Keys). **jsdom ist hier Pflicht, nicht
  Bequemlichkeit:** es setzt die `<label>`-Aktivierungsweitergabe um – ein Test ohne echte
  Label-Semantik sieht den Doppel-Toggle NICHT. Der alte Stand fällt in genau diesen Punkten durch.

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
- **Oberflaeche – Klappabschnitt „System-Einstellungen"** (*Einstellungen → KI & System*;
  hiess bis 2026-07-28 „Tuning"): fasst seit
  2026-07-27 „Sprachausgabe (TTS)", „Antwort-Timeout" und „Maximale Antwortlaenge" in EINEM
  Abschnitt zusammen (vorher drei einzelne), seit 2026-07-28 zusaetzlich „Vorhaltezeit
  erzeugter Dokumente" und „Automatische Sicherheitsupdates". **Umbenannt wurde nur die
  Beschriftung** (`profile.section_tuning`) – die Container-IDs heissen weiter
  `prof-sect-tuning-*`, weil app.js sie darueber verdrahtet. Die drei Untergruppen nutzen `.tuning-group` +
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

## „Illegal header value" im LLM-Profil (Fix 2026-07-30)
**Der Fehler:** Das Profil `google/gemma-4-12B-it (HH-AI01)` meldete im Formular
`Illegal header value` – klingt wie ein Serverfehler, war aber **ein einziges mitkopiertes
Leerzeichen am Ende des API-Keys**. Ein Header-Wert darf laut RFC 9110 kein führendes oder
abschliessendes Leerzeichen tragen; httpx/h11 prüfen das und werfen
`LocalProtocolError: Illegal header value b'Bearer sk-… '`, bevor überhaupt gesendet wird.
- **`llm.clean_api_key()`** ist die eine Stelle, die Keys für Header normalisiert: `strip()`,
  danach **Steuerzeichen und Nicht-ASCII verwerfen** (ein Zeilenumbruch MITTEN im Wert wäre eine
  Header-Injection, Trimmen allein reicht dafür nicht). Benutzt in
  `OpenAICompatibleProvider._build_headers`, `AnthropicSessionProvider._headers` (Cookie!),
  `_probe_llm_connection` und `_list_llm_models`.
- **Die Normalisierung muss BEIM VERWENDEN passieren, nicht nur beim Speichern** – sonst bleiben
  bereits gespeicherte Keys kaputt. `config._clean_profile_str()` räumt zusätzlich an der Wurzel
  auf (`api_key`, `session_key`, `api_url`, `model` in `create_profile` UND der Whitelist von
  `update_profile` – siehe die Regel „neues Profil-Feld = ZWEI Stellen"). **`name` bleibt
  ausgenommen**, ein Anzeigename ist Freitext.
- **Der Provider-Pfad war schon sauber, die Test-Pfade nicht.** `_build_headers` strippte seit
  Langem; `_probe_llm_connection` (Verbindungstest) und `_list_llm_models` (Discover-Knopf) bauten
  `f"Bearer {api_key}"` roh. Deshalb schlug ausgerechnet der Knopf fehl, mit dem man den Fehler
  suchen wollte – während ein Chat über dasselbe Profil funktionierte.
- **`llm.scrub_secrets()`: die Fehlermeldung enthielt den API-Key im Klartext.** Die HTTP-Schicht
  zitiert den beanstandeten Header-Wert wörtlich, und `except Exception: return str(e)` schob das
  unverändert in die Oberfläche (und ins Journal). Nachgewiesen im Test: der alte Stand liefert
  `{'success': False, 'error': "Illegal header value b'Bearer sk-abcdef… '"}`. Jetzt ersetzt
  `scrub_secrets` Rohwert und bereinigte Fassung durch `***` (erst ab 8 Zeichen, damit kurze
  Zufallstreffer keinen Text zerlegen).
- **FALLSTRICK beim Nachstellen:** Ein Test gegen einen geschlossenen Port beweist NICHTS – h11
  serialisiert die Header erst nach dem Verbinden, man bekommt `ConnectError` und hält den Fehler
  für nicht reproduzierbar (genau daran lief die erste Testfassung vorbei). Es braucht einen echten
  Zuhörer (`asyncio.start_server`), dann schlägt die Header-Prüfung zu.
- **Verifiziert auf DEV:** 28 Prüfungen (echter httpx/h11-Stack mit und ohne Leerzeichen,
  Zeilenumbruch mitten im Wert, Emoji, Provider-Header, `scrub_secrets`, Speicher-Normalisierung,
  Ende-zu-Ende über `_probe_llm_connection`). Gegenprobe: der alte Stand liefert genau die
  gemeldete Meldung samt Key.

## Profil-Formular: Abbrechen-× oben rechts (2026-07-30)
`#profile-edit-view` hatte nur den `Abbrechen`-Knopf **am Ende** des Formulars – bei elf Feldern
liegt der ausserhalb des Sichtfensters, Abbrechen ging also nur nach Scrollen. Jetzt sitzt oben
rechts ein `×` (`#btn-close-profile-edit`, `.prof-edit-top`, `.btn-icon`) mit **derselben**
Funktion (`showListView`); der untere Knopf bleibt. Der negative Rand in `.prof-edit-top` setzt
das × auf die Höhe des ersten Feld-Labels, sonst entsteht eine leere Zeile. Beschriftung über
`data-i18n-title` + `data-i18n-aria` auf dem vorhandenen Key `profile.cancel` – kein neuer Text.
**Verifiziert:** 19 UI-Prüfungen in jsdom gegen die echte `settings.html` **mit app.js** (Markup
und Position, × schliesst und stellt die Liste wieder her, identischer Zustand wie „Abbrechen",
**kein** Speichern-Aufruf, Titel/aria folgen dem Sprachwechsel).

## „Letzte Zugriffs-Verstöße": Unter-Container + 10 sichtbare Zeilen (2026-07-30)
Die Liste (bis 150 Einträge aus `/api/security/violations`) füllte den Abschnitt
*Sicherheit → Angriffsprävention* und drückte „Gesperrte Konten" weit nach unten. Jetzt:
**einklappbarer Unter-Container** (`details.sec-sub[data-sub=violations]`, `#sec-sub-viol`) mit
den ersten **50 Einträgen** sichtbar (`VIOL_VISIBLE`), Rest scrollbar (`.sec-scrollbox`). Alle Einträge bleiben im
DOM – es wird nichts abgeschnitten. Die Anzahl steht in der Kopfzeile (`#sec-viol-count`, „(37)"):
der Container startet zu, ohne die Zahl wäre nicht erkennbar, ob sich das Aufklappen lohnt.
- **Die Höhe wird GEMESSEN, nicht per fester CSS-Höhe gesetzt** (`applyViolLimit`, Summe der
  `offsetHeight` der ersten `VIOL_VISIBLE` `.sec-viol-row`): ein Eintrag ist je nach Detail- und
  Anfrage-Zeile ein bis drei Zeilen hoch, eine feste Höhe würde mitten in einen Eintrag schneiden.
- **FALLSTRICK – im eingeklappten Zustand ist NICHTS messbar** (`offsetHeight` = 0). Wer das naiv
  übernimmt, setzt `max-height: 0` und die Liste ist nach dem Aufklappen unsichtbar. Deshalb: bei
  Höhe 0 gar nichts setzen und nachmessen, sobald sie sichtbar wird. **Zwei Ebenen verbergen sie,
  beide müssen gebunden sein** (`bindViolRemeasure`): der Abschnitt (Klick auf die Kopfzeile –
  `app.js::_collapseInit` hat dort einen eigenen Handler, das `setTimeout 0` wartet auf dessen
  `display`-Umschaltung) UND der Unter-Container (`toggle`-Ereignis des `<details>`).
- **Der Rahmen unten (`.sec-scrollbox`) ist Absicht:** ohne ihn sieht die angeschnittene Zeile wie
  das Ende der Liste aus. Dazu `padding-right`, damit der Scrollbalken nicht im Text liegt.
- **Nebenbefund, mitbehoben – das Inline-Skript für die Klapp-Zustände lief zu früh.** Die
  Speicherung (`jarvis_sec_sub_open`, localStorage) steht als `<script>` MITTEN in `settings.html`
  und sah per `querySelectorAll` nur die Unter-Container **oberhalb** von sich. Jeder weiter unten
  stehende ging leer aus – ohne Fehlermeldung, er merkte sich einfach nichts. Jetzt läuft die
  Initialisierung nach `DOMContentLoaded` (mit `_subBound`-Merker gegen Doppelbindung), damit sie
  **alle** sieben erfasst. Nachgewiesen: mit dem alten Skript bleibt genau `violations` ungebunden.
  **Merkregel:** Ein Inline-Skript, das per Selektor über die ganze Seite greift, gehört ans
  Dokument-Ende oder hinter `DOMContentLoaded` – sonst wächst die Seite an ihm vorbei.
- **Verifiziert:** 35 UI-Prüfungen zur Liste (4 / genau `VIOL_VISIBLE` / `+1` / 150 Einträge, Rückweg auf wenige,
  leere Liste, zugeklappt → aufklappen, Zähler, Mehrfachbindung) + 8 zur Zustands-Speicherung
  (alle Container gebunden, Speichern, Wiederherstellen), jsdom gegen die echten Dateien; die
  Persistenz-Tests laufen mit `runScripts:'dangerously'`, weil das Inline-Skript sonst nicht
  ausgeführt wird und der Test grün wäre, ohne etwas zu prüfen.

## Confluence-Anhänge + Shell-Redirect-Fehlalarm (Fix 2026-07-30)
**Der gemeldete Ablauf:** `confluence_list_attachments` gab Download-Links aus → der Agent setzte
`curl` darauf an → **sechs 0-Byte-CSV-Dateien** in /tmp → der nächste Versuch
(`curl -sv … -o test.csv 2>&1 | tail`) wurde mit „Datei-Schreiben via Shell ist nur im
temporären Arbeitsbereich /tmp erlaubt" **abgewiesen, obwohl er nach /tmp schrieb**. Zwei
unabhängige Fehler.

### 1. `2>&1` galt als Datei-Schreibzugriff
Zwei Regexes widersprachen sich: `_LDAP_SHELL_WRITE_REDIRECT` (`(?<![<|&])>\s*\S`) entschied
**dass** geschrieben wird, `_REDIRECT_TARGETS` (`(?<![<|&\d])>>?\s*(…)`) **wohin** – letzterer
schloss fd-Präfixe aus. Ergebnis: `2>&1` traf den Detektor, lieferte aber kein Ziel, und „keine
Ziele" wurde als unsicher gewertet. Betroffen waren u.a. `ls -l 2>&1` und
`python3 x.py 2>/tmp/err.txt` (Schreiben **nach /tmp** – genau das, was erlaubt sein soll).
- Ersetzt durch **einen Parser** (`_shell_redirect_writes`), der `(Datei-Ziele, unlesbare)`
  liefert und dabei unterscheidet: `2>&1`/`>&2` = Deskriptor-Duplikat (keine Datei), `2>datei` =
  Datei (fd-Präfix unerheblich), `&>datei` = beide Ströme, `> "mit leerzeichen"` = Ziel in
  Anführungszeichen. **`>` INNERHALB von Anführungszeichen ist kein Redirect** (`grep "a > b"`,
  `awk '$1 > 5'`) – wurde vorher zum Ziel `b"` und abgewiesen.
- **Der Detektor-Regex ist ganz weg**, nicht nur ergänzt: er übersah `&>datei` (das `&` fiel in
  seine Lookbehind-Ausnahme), womit ein Ziel außerhalb /tmp **ungeprüft** durchkam.
- Fail-closed bleibt: ein Ziel, das sich nicht lesen lässt (`>` ohne Ziel, offenes
  Anführungszeichen), gilt als unsicher. **Kein Ziel = in Ordnung** (das war die Fehlerquelle).
- Diese Schicht ist Tiefenverteidigung, die harte Grenze ist der OS-Benutzer `jarvis_sandbox`.
- **Verifiziert:** 37 Prüfungen (14 „muss erlaubt sein", 14 „muss gesperrt bleiben",
  Parser-Details) – der alte Stand weist 3 davon falsch ab und lässt `&>` durch.

### 2. Anhänge waren gar nicht abrufbar – und das fiel niemandem auf
Es gab **kein** Download-Tool, nur `confluence_upload_attachment`. Die Liste gab aber
Download-Links aus, also griff das Modell zwangsläufig zu `curl`. Der Link
`/download/attachments/…` ist eine **Web-UI-Route**, keine REST-Route:
- ohne Anmeldung → `302 → /login.action`; `curl` ohne `-f` wertet das nicht als Fehler und legt
  eine **0-Byte-Datei** an (der gemeldete Zustand),
- **mit** PAT → `302 → /plugins/servlet/twofactor/validate_otp`: der Token wird akzeptiert, aber
  der **Zwei-Faktor-Filter** lässt ihn nicht an die Web-Route. Folgt man der Umleitung, kommt eine
  HTML-Seite mit **HTTP 200** – eine erste Fassung dieses Fixes hat die gespeichert und damit
  6× dieselbe 53 KB große HTML-Datei mit Endung `.csv` erzeugt. Am Größenvergleich aufgefallen
  (alle gleich groß, obwohl die Liste 25133/19402/12190/… meldet).
- **Eine REST-Route für die Bytes gibt es auf Server/DC nicht** – geprüft:
  `/rest/api/content/<id>/download`, `/rest/api/attachment/<id>/download`,
  `/rest/api/content/<id>/data` → alle 404; Basic-Auth mit PAT → 401; `os_authType=basic` und
  `X-Atlassian-Token: no-check` ändern nichts.
- **Konsequenz:** `client.download_attachment()` + `confluence_download_attachment` existieren
  jetzt, können aber **auf diesem Server nicht liefern**. Sie scheitern dafür mit Klartext:
  „durch die Zwei-Faktor-Prüfung blockiert … Abhilfe nur serverseitig: Pfad
  `/download/attachments/*` im 2FA-Plugin ausnehmen ODER Dienstkonto ohne 2FA" – und mit dem
  ausdrücklichen Hinweis, dass `curl` genauso scheitert (sonst probiert das Modell es wieder).
- **Vier Schranken, damit NIE eine falsche Datei entsteht:** kein `allow_redirects` (Umleitung =
  Fehler), HTML-Erkennung über Content-Type **und** Inhalt (`<!doctype`/`<html`), 0-Byte-Prüfung,
  Größenvergleich gegen `fileSize` aus den Metadaten (Toleranz 5 %, mind. 4 Byte – **prozentual**,
  eine feste 64-Byte-Grenze ließ bei einer 12-Byte-Datei jede Abweichung durch). Geschrieben wird
  **erst nach** allen Prüfungen.
- `confluence_list_attachments` gibt den **Link nicht mehr aus** (er ist ohne PAT nutzlos und war
  die Einladung zu curl), sondern Dateigröße + den Verweis auf das Download-Tool.
- „Anhang nicht gefunden" wirft `status=0`, damit die Meldung samt Liste der vorhandenen Namen
  erhalten bleibt – `_fmt_err` ersetzt 404 durch einen generischen Text.
- **Verifiziert:** 27 Prüfungen mit gefälschten Antworten (Erfolgspfad schreibt korrekt, HTML mit
  und ohne verräterischen Content-Type, 302 auf 2FA bzw. Login, 0 Byte, falsche Größe, Toleranz,
  fehlende Metadaten, Pfad-Entschärfung) + live gegen das echte Confluence.

## `2>/dev/null` sperrte Konten (Vorfall + Fix 2026-08-05)
**Der Vorfall:** Auf ECHT wurde `nexus\rene.pfeiffer` um 17:03 mit `policy:shell-write`
**gesperrt** – ausgelöst von drei `grep`-Befehlen innerhalb von drei Sekunden, die je eine
YAML-Datei in `/tmp` durchsuchten und mit `2>/dev/null` das Rauschen unterdrückten. Kein
Schreibzugriff, keine Umgehung, keine Systemänderung.
- **Ursache:** `_shell_redirect_writes()` liefert `/dev/null` korrekt als Redirect-Ziel, und
  `_ldap_redirects_safe()` verlangt, dass **jedes** Ziel unter `/tmp` liegt. `/dev/null` liegt
  dort nicht → „Schreibziel außerhalb /tmp" → `shell-write` → drei Treffer in
  `security_autoblock_window` (600 s) bei `security_autoblock_count` (3) → **Konto zu**.
  `ls -l 2>/dev/null` und `find … 2>/dev/null | head` waren damit ebenfalls gesperrt.
- **Nachgemessen im Produktiv-Zustand:** von 28 protokollierten `shell-write`-Verstößen waren
  **15 genau dieses Muster**, verteilt auf **vier** Konten seit dem 24.07. Der Fehler lief also
  zwölf Tage unbemerkt – die Meldung „Datei-Schreiben nur in /tmp erlaubt" war für einen
  Benutzer, der nichts geschrieben hat, nicht deutbar.
- **`_SHELL_DEV_SINKS`** (`/dev/null|stdout|stderr|tty|zero|full`) wird in
  `_shell_write_targets()` herausgefiltert; der Roh-Parser bleibt wahrheitsgetreu (ein Test hält
  fest, dass er `/dev/null` weiter meldet) – **die Bewertung eines Ziels gehört in die Policy,
  nicht in die Zerlegung.** Bewusst eine **Aufzählung und kein `/dev/`-Präfix**: `> /dev/sda`
  wäre ein Plattenschreibzugriff, `> /dev/mem` ein Speicherzugriff.
- **Zweiter, unabhängiger Fehler: eine Sandbox-Grenze wurde als Angriff gezählt.** Dieselbe
  Lehre stand seit dem 2026-07-29 bei `cron_create` („zählte jeder abgelehnte Versuch, sperrte
  *erinnere mich täglich um 8* beim dritten Mal einen harmlosen Benutzer") – bei `shell-write`
  war sie nicht angewandt. Jetzt entscheidet `_shell_write_is_attack()`: nur ein Ziel in einem
  System-/Secret-Bereich (`/etc`, `/root`, `/var`, `/opt`, `.ssh`, `.env`, `settings.json`,
  `data/chats|documents|logs|instructions`, `scheduled_jobs.json`, …) ist ein Angriffsindiz.
  Ein relativer Pfad, `~/notiz.txt` oder `/mnt/…` wird **abgewiesen und protokolliert, zählt
  aber nicht**.
- **`record_violation(..., escalate=False)`** ist der Weg dafür: der Eintrag bleibt in der
  Oberfläche sichtbar, trägt aber `soft: True`. **Die Zählung filtert das FELD, nicht den
  Parameter** (`not e.get("soft")`) – sonst wäre ein bereits gespeicherter weicher Eintrag
  weiter Futter für eine spätere Sperre. Journal-Marke `GRENZE` statt `VERSTOSS`.
  Der Dispatch-Standard ist `_viol_soft = False`: ein neuer Deny-Zweig eskaliert wie bisher,
  fail-closed.
- **Die Fehlermeldung nennt jetzt das beanstandete Ziel** und sagt ausdrücklich, dass
  `/dev/null` und `2>&1` erlaubt sind. Vorher stand dort nur „Datei-Schreiben … nur in /tmp",
  obwohl der Befehl mehrere Ziele haben kann – Modell und Benutzer konnten nicht ableiten, was
  zu ändern ist, und **wiederholten den Versuch. Drei Wiederholungen sind die Sperre.**
- **Warum es zwölf Tage niemandem auffiel: die 37 Prüfungen des 2026-07-30-Fixes lagen in einem
  Wegwerf-Skript, nicht im Repo** (`grep -rn _ldap_redirects_safe tests/` fand nichts). Jetzt
  **`tests/test_shell_redirects.py`** (68 Prüfungen, ohne fastapi lauffähig: die Funktionen
  werden per Quelltext aus `agent.py` extrahiert, `backend.config` ist ein Stub – der echte
  Import würde bei einer Migration die **Live-`settings.json` zurückschreiben**).
  Enthält den gemeldeten Befehl wörtlich. Gegenprobe: der alte Stand sperrt alle fünf
  `/dev/null`-Fälle.
- **Verifiziert:** 68/68 lokal und auf DEV im echten venv, Dienst aktiv, `/settings` HTTP 200,
  echtes Modul geprüft (`grep … 2>/dev/null` erlaubt & nicht eskalierend, `> /etc/passwd`
  gesperrt & eskalierend). Konto auf ECHT freigeschaltet (Sicherung
  `data/security_state.json.bak-20260805-193614`) – **der Code-Fix ist auf ECHT noch nicht
  ausgerollt.**

### Die Durchsicht der ganzen Verstoßliste (gleicher Tag)
Auf Anweisung des Nutzers wurden danach **alle 79 Vorfälle** auf ECHT einzeln bewertet (Regel →
protokollierter Befehl → Anfrage) und die Erkennungsregeln selbst geprüft. Ergebnis: **57 der 79
Einträge waren keine Angriffsindizien**, und im Journal stehen seit dem 09.07. **zehn**
Auto-Sperren (nicht eine – die übrigen waren zwischendurch manuell entsperrt worden, deshalb
stand nur eine in `blocked`). Vier davon sind zweifelsfreie Fehlalarme.
- **`||` wurde als Pipe gelesen** (`shell-illegal`, die schwerste Einstufung
  „verschleierte Ausführung"): `\|\s*(?:bash|sh|python3?|…)` traf das zweite `|` eines
  logischen ODER. Damit galt `python3 -c "import pdfplumber" || python3 -c "import PyPDF2"` –
  das Standardmuster für Fähigkeitsprüfungen – als Verschleierung, ebenso
  `test -f x || sh x` und `which node || node -v`. Fix: `(?<!\|)\|(?!\|)`.
- **`source`/`eval`/`bash -c` trafen SUCHBEGRIFFE:** `grep -r "source" /tmp/doku.txt` war
  „verschleierte Ausführung". Deshalb sind die Regeln jetzt **getrennt**: `SHELL_OBFUSCATION`
  (Dekodierer + Pipe-in-Shell) prüft den **ganzen** Befehl – eine base64-Nutzlast steckt fast
  immer in einem Argument –, `SHELL_EXEC_WORDS` nur `strip_quoted(cmd)`. **`strip_quoted()` ist
  fail-closed:** bei offenem Anführungszeichen gibt es den Originaltext zurück, dann prüft die
  Regel wieder alles. Die Umgehung `ev"a"l` bleibt möglich, war es vorher aber genauso.
- **`blocked-tool` ist jetzt IMMER weich.** Alle fünf Einträge auf ECHT (fünf verschiedene
  Konten) waren `spawn_agent` – **kein Benutzer hat das verlangt**, das Modell greift von sich
  aus danach. Wer für die Werkzeugwahl eines LLM gesperrt wird, versteht die Sperre nicht und
  kann sie auch nicht vermeiden.
- **`fs-deny` ist weich, außer bei Secret-/System-Zielen** (`sandbox.fs_target_sensitive()`,
  fail-closed). 20 der 39 Einträge waren vom Modell **geratene Pfade**: bei „suche in allen
  CSV-Dateien, die mit nxis_Connectors…" probierte es `/opt`, `/var/nxis`, `/home`, `.` durch –
  vier Fehlversuche in einer Minute, Konto gesperrt (29.07.).
- **Nebenbefund, mitbehoben: `data/chats` stand nicht in `_APP_DENY_REL`.** Es war nur über
  `PRIVATE_DIRS` (OS-Rechte 0750) geschützt, `authorize_fs` verweigerte den Zugriff mit der
  Begründung „nicht im Arbeitsbereich" statt „sensibel". Ab jetzt macht das einen Unterschied –
  ein Zugriff auf **fremde Chat-Verläufe** wäre sonst als „geratener Pfad" weich eingestuft
  worden. Zusätzlich in `SHELL_SECRET_PATHS`. Gegengeprüft: `data/knowledge` und
  `data/documents` bleiben lesbar.
- **Die Protokollgrenzen waren zu klein, um eine Sperre zu BEURTEILEN** (`_VIOL_DETAIL_MAX`
  2000 statt 120/200, `_VIOL_TASK_MAX` 1000 statt 300). Bei sieben der 28 `shell-write`-Einträge
  endete der gespeicherte Befehl mitten im Redirect-Ziel (`2>/dev` statt `2>/dev/null`) oder in
  einem offenen Anführungszeichen – **ich konnte sie bei der Durchsicht nicht bewerten, ein
  Administrator kann es auch nicht.** Dieselbe Lehre wie am 2026-08-04 beim LLM-Verlauf, hier
  aber mit einer Kontosperre am Ende. Kosten: 79 Vorfälle in vier Wochen, je Konto nur die
  letzten 100 – die Datei wuchs von 48 auf 55 KB.
- **`deploy/security/reclassify_violations.py`** bewertet den Altbestand nach denselben Regeln
  neu und setzt `soft` + `soft_reason`. **Es löscht nichts und ändert keinen Text** – das
  Protokoll bleibt vollständig und in der Oberfläche sichtbar, die Einträge zählen nur nicht
  mehr zur Auto-Sperre. Nötig, weil die Sperrprüfung über ein Zeitfenster **zurückblickt**:
  ohne Reklassifizierung hätten alte Fehlalarme weiter zu neuen Sperren beigetragen.
  - **Die Regeln werden per Quelltext aus `agent.py`/`sandbox.py` GELADEN, nicht nachgebaut** –
    ein Nachbau würde beim nächsten Regel-Fix auseinanderlaufen und genau die Einträge
    verschonen, die dann neu als Fehlalarm gelten.
  - **Trockenlauf ist die Vorgabe**, `--apply` schreibt (mit Sicherung, Eigentümer/Modus der
    Zieldatei werden übernommen), zweiter Lauf ist idempotent (`0 neu markiert`).
  - **War der protokollierte Text schon am alten Deckel, steht das in der Begründung**
    („[Text war gekuerzt – Bewertung anhand des Ausschnitts]"). Ohne diesen Zusatz liest sich
    „Fehlalarm" wie eine gesicherte Aussage, obwohl der entscheidende Teil fehlt.
  - **`--soft-entry <ts>` für Fälle, die keine Regel erkennen kann.** Genau einer: 28.07.,
    **03:00**, `nexus\peter.sachs`, `git pull && systemctl restart jarvis.service`,
    protokollierte Anfrage „leider gar nicht" – das ist der Cron-Vorfall vom 28.07.
    (`system_auto_update` lief unter der Identität des letzten Chat-Nutzers). Die Ursache ist
    mit der Actor-Bindung behoben, der falsch zugeschriebene Verstoß zählte aber weiter in
    seinem Konto. **Automatisch erkennen wäre Raten**, deshalb eine ausdrückliche
    Administrator-Entscheidung mit Begründung im Eintrag.
- **Gesperrte Konten werden NICHT automatisch entsperrt** – das bleibt `/api/security/unblock`
  bzw. die Oberfläche. Ein Skript, das im Vorbeigehen Konten freischaltet, ist eine
  Sicherheitsentscheidung ohne Entscheider.
- **Zur Einordnung:** `security_autoblock_*` ist auf ECHT nicht gesetzt (Standard 3 Verstöße /
  600 s) und **`ad_admin_users` ist leer** – niemand ist `exempt`, jedes Konto kann sich
  aussperren.
- **Verifiziert:** 118/118 (`tests/test_shell_redirects.py` – erweitert um `||`/Suchbegriff,
  `strip_quoted` fail-closed, `fs_target_sensitive`, und das Reklassifizierungs-Skript
  end-to-end inkl. Idempotenz, Sicherung, `--soft-entry` und Kürzungs-Hinweis) lokal und auf
  DEV im echten venv, Dienst aktiv, `/settings` HTTP 200. Auf ECHT angewandt: **57 von 79
  Einträgen** markiert (56 regelbasiert + der Cron-Einzelfall), Kontrolllauf `0 neu markiert`,
  Datei valides JSON mit `jarvis:jarvis 0640`, Originaltexte unangetastet, Dienst aktiv,
  `/portal` HTTP 200. Weiter hart: 19 `fs-deny` auf Secret-Ziele + 3 `shell-illegal` auf
  `/root`/`settings.json`. Sicherung `data/security_state.json.bak-20260805-195956`.

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
- **Wissensgruppen-Filter gehoert IN die Suche, nicht dahinter (Fix 2026-08-02).** Bis dahin
  holte `knowledge.py` bei gesetztem Gruppenfilter das **Fuenffache** (`max(k*5, 40)`) und
  filterte danach in Python. Das verliert still Treffer – und zwar nicht nur ueber die Anzahl:
  der **relative Cut misst am globalen Spitzenreiter**, der in einer fremden Gruppe liegen kann.
  Der beste erlaubte Treffer faellt dann schon vor dem Nachfilter heraus, und der Benutzer liest
  „keine Treffer", obwohl passendes Wissen in seiner Gruppe liegt.
  **Nachgemessen** (60 laute Chunks in Gruppe A, 1 leiser in Gruppe B): bei drei von vier
  Anfragen stand der B-Treffer **gar nicht** in den ueber-abgefragten 40.
  - `search_hybrid(..., allow_paths=…)` reicht die Erlaubnis an BEIDE Kanaele durch: semantisch
    ueber `faiss.IDSelectorBatch` + `SearchParameters`, lexikalisch ueber ein `continue` in der
    BM25-Schleife. Damit sind die k Treffer die besten der **erlaubten** Chunks, und Cut,
    `MIN_KEEP` und Normierung rechnen auf derselben Grundlage.
  - **`sel` und `params` muessen bis nach `search()` am Leben bleiben** – SWIG-Objekte mit
    C++-Speicher. Inline als Ausdruck geschrieben kann der Selector vorher eingesammelt werden.
  - **`df`/`n_docs` in BM25 bleiben die Werte des GESAMTBESTANDS.** Sonst haenge die Seltenheit
    eines Wortes davon ab, wer fragt – derselbe Begriff waere in einer kleinen Gruppe ploetzlich
    „haeufig" und wuerde abgewertet.
  - **Die erlaubten Pfade werden ERST NACH `_rebuild_vector_index()` bestimmt** (aus
    `get_indexed_files()`, nicht aus den Treffern): der Reindex kann gerade geaenderte Dateien
    nachgetragen haben, die sonst fuer diesen Lauf unsichtbar waeren. Kosten: **0,61 ms** bei
    12.387 Chunks.
  - **Die Ueber-Abfrage bleibt fuer den TF-IDF-Rueckfall** – der kann nicht filtern. Schlaegt das
    Ermitteln der Pfade fehl, faellt der Code bewusst auf den alten Weg zurueck (`gruppen_in_suche
    = False`), statt den Filter stillschweigend aufzuheben.
  - Betroffen waren ZWEI Stellen: `KnowledgeTool.execute` und `rag_search()` (Support-Assistent).
  - **Verifiziert:** 20 Tests (`tests/test_kb_group_filter.py`, u.a. der reproduzierte Verlust)
    + Gegenprobe, dass der **ungefilterte** Weg gegenueber dem alten Code Treffer, Reihenfolge
    und Scores **bitgleich** liefert (6 Anfragen inkl. Zeichensalat).
- **`search_hybrid_ex()` statt `search_hybrid()` + `has_lexical_anchor()`** (seit 2026-08-02):
  letzteres rechnete denselben BM25-Durchlauf ein ZWEITES Mal, obwohl die Hybridsuche das
  Ergebnis Millisekunden vorher schon hatte und wegwarf. `search_hybrid()` bleibt unveraendert
  (gibt nur die Liste), `search_hybrid_ex()` gibt `(treffer, ohne_anker)`.
  **Feiner Unterschied:** bei gesetztem `allow_paths` bezieht sich die Anker-Aussage auf die
  ERLAUBTEN Chunks – fuer den Zweck richtiger, denn die Warnung soll sagen, worauf die
  gelieferten Treffer beruhen. `has_lexical_anchor()` bleibt fuer Aufrufer erhalten, die nur
  diese eine Frage haben.
- **BM25-Index wird beim Start vorgebaut** (`startup_warm_lexical_index`, +45 s, im Thread):
  kalt kostet der Aufbau 593 ms, und die traf bisher immer den ERSTEN Benutzer nach jedem
  Deploy. Faellt der Vorbau aus, ist nichts kaputt – die erste Suche baut ihn dann selbst.
- **`add_chunks(save=False)` wirkte nur auf dem Anhaeng-Pfad** (behoben 2026-08-02): der Zweig
  fuer GEAENDERTE Dateien ruft `_rebuild()`, und das speicherte bedingungslos. Ein Bulk-Lauf
  ueber geaenderte Dateien schrieb also je Datei den vollstaendigen Index (~700 ms bei 12.387
  Chunks), obwohl der Aufrufer das ausdruecklich unterdruecken wollte. `_rebuild(..., save=…)`
  reicht das Flag jetzt durch; die uebrigen Aufrufer (remove_files, rename_*, clear) speichern
  ueber den Vorgabewert `True` weiter wie bisher.
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
- **MASSSTABSPROBE 2026-07-31** (`tests/scale_rehearsal.py`, DEV, 900 Dateien / 12.387 Chunks,
  3 h Laufzeit, 366 Messpunkte): Speicher ueber ZWEI vollstaendige Durchgaenge flach bei
  1269–1518 MB (Spitze 1538 MB) – der historische Abbruchpunkt bei ~600 Dateien wurde zweimal
  ohne Regung passiert. 12/12 Pruefungen. Suche warm 47 ms (Median), kalt 593 ms inkl.
  BM25-Aufbau; Lern-Notiz anhaengen 191 ms mit inkrementellem BM25-Nachtrag.
- **⚠ DIE ~2-STUNDEN-ZAHL GALT NUR FUER DEV – auf ECHT sind es ~13 Minuten** (korrigiert
  2026-08-02). Die Maßstabsprobe lief auf der DEV-VM, und der Satz „ECHT liegt gleichauf" war
  eine **Annahme, keine Messung**. Nachgemessen auf ECHT (Xeon Gold 6526Y, AVX-512, 4 Kerne,
  gleiche Thread-Zahl wie die Produktion): **57,8 Chunks/s** gegen **11,3 auf DEV** – Faktor 5,3.
  Auf 200-Wort-Chunks hochgerechnet rund 15 Chunks/s, also **~13 min fuer 12.387 Chunks**.
  Seit der Thread-Aenderung (siehe unten) schafft DEV 21,1 Chunks/s, der Voll-Reindex dort
  also ~1 h statt 2 h.
  **Merkregel:** DEV ist eine VM OHNE AVX/SSE4.2 mit 8 Kernen, ECHT hat AVX-512 mit 4 Kernen.
  Leistungszahlen von DEV tragen keine Entscheidung – auf ECHT messen (kurz und lesend,
  es ist Produktion).
- **PyTorch-Threads: zwei Kerne bleiben frei** (`_get_embedding_model`). Vorher stand dort fest
  `set_num_threads(2)`; auf einer 8-Kern-Maschine verschenkte das drei Viertel. Gemessen auf
  ECHT (32 Chunks je Lauf): 1 Thread 29,1 · 2 Threads 57,8 · 3 Threads 80,3 · 4 Threads
  91,5 Chunks/s – nahezu linear. Jetzt `max(1, min(cpu_count - 2, 8))`: auf ECHT weiterhin 2
  (**Produktionsverhalten unveraendert**), auf DEV 6 (+87 %). Zwei Kerne bleiben bewusst frei,
  damit eine laufende Indexierung den Webdienst nicht aushungert. Fuer die SUCHE ist die Zahl
  fast gleichgueltig (10,6 ms bei 2 Threads gegen 8,5 ms bei 4) – sie wirkt auf die Indexierung.
- **Die Batchgroesse ist NICHT der Hebel** (gemessen, damit es niemand erneut versucht): auf DEV
  ist der Durchsatz ueber 1/3/8/32/64 Texte konstant (~11/s), die CPU ist schon mit einem Text
  ausgelastet. Auf ECHT bringt Batching etwas (58 → 100/s von 1 auf 32 Texte), aber `add_chunks`
  encodiert ohnehin alle Chunks EINER Datei zusammen, und das sind im Schnitt 14
  (12.387/893) – damit liegt es bereits nahe am Optimum. Dateiuebergreifendes Buendeln braechte
  ~12 % und lohnt die Komplexitaet nicht. `batch_size=16` bleibt (RAM-Schonung ist gratis).
- Die folgenden Punkte gelten unveraendert – nur mit den korrigierten Zeiten im Kopf:
  - `resume_interrupted_reindex()` bleibt sinnvoll, ist aber kein Notnagel mehr: ein
    Neustart bei 80 % kostet auf ECHT wenige Minuten, nicht anderthalb Stunden.
  - Der Unterschied „inkrementell vs. voll" ist kein Feinschliff (0,2 s Leerlauf gegen
    Minuten bis Stunden). Wer im Zweifel ist, nimmt `incremental=True`.
  - Ein Modellwechsel (anderes Embedding-Modell) kostet auf ECHT rund eine Viertelstunde
    Stillstand der Wissenssuche – nicht zwei Stunden. Das aendert die Kosten-Nutzen-Rechnung
    fuer Quantisierung/Modellwechsel erheblich.
  - **FALLSTRICK bei eigenen Messungen:** `force_reindex()` ohne Schalter ist ein
    VOLLSTAENDIGER Neuaufbau. In der Massstabsprobe hat genau das den Abschnitt
    „50 Dateien loeschen" mit 6568 s vergiftet – die Zahl sah wie eine katastrophale
    Loeschdauer aus und war in Wahrheit ein zweiter Voll-Reindex. Das Loeschen selbst ist
    eine Aufraeumaktion (ein `remove_files()`-Sammelaufruf) und kostet Sekunden.
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

## Erzeugte Dokumente (`/api/documents`) – drei Schranken (seit 2026-07-28)
- **Lieferweg:** Erzeugt der Agent eine Datei (Office-Skill ODER Shell/python-pptx in `/tmp`),
  zieht `agent.py::_deliver_docs` sie nach `data/documents/` und sendet EINEN Markdown-Link
  `[📥 … herunterladen](/api/documents/<32-Hex>__<Basis>.<ext>)`, den die Frontends als Chip
  rendern. `_clean_doc_refs` entfernt vorher alle Pfade aus dem Anzeigetext – der Chip ist der
  EINZIGE Weg zur Datei. Fällt er aus, sieht der Nutzer eine Antwort ohne jeden Hinweis.
- **Nur was in DIESEM Lauf entstand (mtime-Schranke, seit 2026-07-28).** `_deliver_docs` hat vier
  Erkennungspfade: (a) fertige `/api/documents/`-URLs, (m) explizite `[[JARVIS_DELIVER:…]]`-Marker,
  (b) Dateipfade, (c) **bloße Dateinamen**. (b) und (c) raten über Namen – und ein Werkzeug-Ergebnis
  wie `filesystem list data/documents` ist voll von Namen. Auf ECHT kam so am 2026-07-28 mitten in
  einer Word/PDF-Aufgabe ein `b45.xlsx` **aus einem Chat vom Juni** als Ergebnis-Chip heraus (es war
  die einzige Roh-Datei ohne Capability-Präfix im Ordner; die drei `…__b45.xlsx` daneben zeigen, dass
  das schon öfter passiert war). Deshalb bekommt `_deliver_docs` jetzt `since=_task_start_time` und
  (b)+(c) liefern nur Dateien mit `mtime >= since - _DELIVER_TOLERANCE_SEC` (120 s Toleranz für
  Anhänge, die der Nutzer unmittelbar vor dem Absenden hochlädt).
  - `since=0` schaltet die Prüfung ab (Aufrufer ohne Laufzeitbezug) – beim Ergänzen neuer Aufrufer
    den Startzeitpunkt **mitgeben**, sonst ist die Schranke dort still wirkungslos.
  - Die mtime-Prüfung ist **fail-open**: ist `stat()` nicht lesbar, wird ausgeliefert. Ein fehlender
    Chip ist der schlimmere Fehler (der Nutzer hat dann gar nichts), ein Chip zu viel nur Rauschen.
  - (m) ist absichtlich ausgenommen: dort benennt der Agent die Datei ausdrücklich, das ist Absicht
    und keine Namensraterei. Schutz dort: Ortsprüfung (/tmp, data/documents) + Secret-Sperrliste.
- **Bis 2026-07-28 war der Capability-Name der einzige Schutz:** keine Anmeldung, kein Bezug zum
  Ersteller, kein Verfall, kein Aufräumen. 122 Bit Entropie sind zwar nicht erratbar, aber ein
  geleakter Link (Browser-Verlauf, Proxy-Log, weitergeleiteter Screenshot) gab dauerhaft Zugriff –
  auf ECHT liegen dort Jira-Exporte mit Kundendaten. Jetzt gilt zusätzlich:
  1. **Anmeldung** – `require_auth_or_query`: Bearer-Header ODER `?token=`. Die Query-Variante ist
     nötig, weil `<a download>` und `<img src>` keine Header setzen können.
  2. **Eigentümer** – `backend/documents.py`: `data/documents/.owners.json` bildet
     Capability → Benutzer ab; nur der Ersteller und Admins dürfen laden.
  3. **Vorhaltezeit** – `cleanup_old()` beim Start und danach täglich
     (`startup_documents_retention`). Capability-URLs verfallen nicht von selbst,
     **das Löschen der Datei IST der Widerruf.**
- **Vorhaltezeit einstellbar** unter *Einstellungen → KI & System → Tuning* (vierte
  `.tuning-group`, seit 2026-07-28): Zahlenfeld **15–90 Tage** + Kontrollkästchen „dauerhaft" (= 0,
  nie löschen). Feld `docs_retention_days` in `POST /api/settings`, Anzeige in `GET /api/settings`,
  Validierung `config._valid_retention()`, ENV-Startwert `JARVIS_DOCS_RETENTION_DAYS`.
  - **`_valid_retention` darf NICHT über Falsyness prüfen** (`int(v or 30)`) – 0 ist ein gültiger
    Wert und würde still zum Standard. Werte 1–14 werden auf 15 **gehoben**, nicht auf 0
    abgerundet: aus einer zu knappen Eingabe darf nicht versehentlich „dauerhaft" werden.
    Dasselbe im Frontend beim Laden (`data.docs_retention_days == null`, nicht `|| 30`).
  - **`documents.retention_days()` ist eine Funktion, keine Modulkonstante.** Ein beim Import
    gelesener Wert hätte die Einstellung bis zum nächsten Dienststart wirkungslos gemacht.
    Aus demselben Grund läuft die Tagesschleife auch bei „dauerhaft" weiter und prüft die
    Frist bei jedem Durchlauf neu.
  - **Speichern räumt sofort auf** und meldet `docs_removed` zurück – wer die Frist verkürzt,
    erwartet, dass die Altdateien jetzt weg sind, nicht erst morgen.
- **Vierte Schranke: der WERKZEUG-Weg (seit 2026-07-28).** Die drei Schranken oben hängen am
  HTTP-Endpunkt. Der Agent kommt aber ganz anders an den Ordner: `filesystem list data/documents`
  zeigte JEDEM Domain-Benutzer die Dateinamen aller anderen (auf ECHT Jira-Exporte mit Kundendaten,
  fremde Angebote, `Manager_IDs.xml`), `filesystem read` und `office_read` konnten sie öffnen.
  Jetzt gilt dieselbe Eigentümer-Regel auch dort:
  - **`backend/sandbox.py`** hält die Policy: `may_see_document(name)` (delegiert an
    `documents.may_access`, fail-closed) und `may_list_entry(dir, name)` (greift **nur** in
    `data/documents`). `authorize_fs` verweigert `read`/`exists` auf fremde Dateien; das
    **Verzeichnis bleibt auflistbar**, gefiltert wird der Inhalt.
  - **Der Benutzer kommt über einen ContextVar** (`set_tool_user`/`tool_user`), den
    `agent.py::_execute_tool` für die Dauer EINES Aufrufs setzt (`try/finally`, sonst regiert ein
    stehengebliebener Wert den nächsten Lauf). Grund für den ContextVar statt eines Parameters:
    `filesystem` und der Office-Skill lösen Pfade selbst auf – jede Signatur anzufassen hätte
    fremde Skills gebrochen. **LEER = keine Einschränkung** (privilegierte Benutzer, Systemläufe);
    genau wie die übrigen Sandbox-Prüfungen gilt die Schranke nur für Domain-Benutzer.
  - **Kein Admin-Bypass im Werkzeug-Weg** (anders als am HTTP-Endpunkt): ein Admin, der einen Link
    anklickt, ist eine bewusste Handlung – ein Agent, der im Auftrag eines Admins den Ordner
    durchwühlt, ist es nicht. Admins arbeiten über Einstellungen/Shell.
  - **Wer schreibt, besitzt.** Damit die Schranke nicht die eigenen Dateien verschluckt, wird der
    Eigentümer beim ENTSTEHEN vermerkt: `documents.register_upload()` für Chat-Anhänge
    (`main.py`, Anhang-Block) und für `filesystem write/append` in den Ordner
    (`FileSystemTool._claim`), `register()` schon im Office-Skill (`_ok`) statt erst in
    `_deliver_docs` – letzteres läuft bei **Sub-Agenten gar nicht**, deren eigene Datei wäre
    sonst sofort unsichtbar.
  - `register_upload()` ist absichtlich von `register()` getrennt: `register()` bekommt Namen aus
    LLM-Text und darf deshalb nur unerratbare Capability-Namen annehmen.
  - **`.owners.json` steht in `_SECRET_NAMES`** – die Datei bildet Dokument→Benutzer ab und wird
    weder gelistet noch gelesen.
  - Die Auflistung nennt die **Anzahl** ausgeblendeter Dateien, keine Namen: sonst wüsste das
    Modell wieder, dass fremde Dateien existieren – ohne den Hinweis hielte es die gefilterte
    Liste aber für vollständig.
  - **Dateirechte-Lücke geschlossen (2026-07-28):** Shell-Befehle von Domain-Benutzern laufen
    als `jarvis_sandbox`; mit den Vorgabe-Rechten (0755/0644) kam ein `cat` an JEDE Datei –
    nicht nur an Dokumente, sondern auch an `data/chats` (fremde Chat-Verläufe!) und
    `data/logs`. `sandbox.harden_data_dirs()` setzt diese drei Verzeichnisse auf **0750**
    (`PRIVATE_DIRS`), aufgerufen beim Start (`startup_harden_data_dirs`), damit es nach
    Neuinstall/Restore nicht driftet. Das Verzeichnis-x-Bit ist die ganze Sperre – die
    Dateimodi darin sind dann gleichgültig. `data/knowledge` bleibt ABSICHTLICH lesbar
    (`READ_ROOTS` erlaubt es, die Shell soll Wissensdateien verarbeiten).
    - **Was OS-Rechte hier NICHT leisten:** alle Domain-Benutzer teilen EINEN
      Sandbox-Benutzer. Sie sind damit vom Dienst-Verzeichnis getrennt, aber nicht
      voneinander – eine Datei, die `jarvis_sandbox` lesen darf, darf jeder Domain-Benutzer
      lesen. Echte Trennung bräuchte einen Sandbox-Benutzer pro Person.
    - **Deshalb bekommt der Agent Anhänge als Arbeitskopie in `/tmp`** (`anhang_<12 Hex>_<name>`,
      main.py): `data/documents` ist für die Shell zu, aber „analysiere die angehängte Tabelle"
      muss mit pandas/openpyxl weiter funktionieren. Der Hinweistext an das Modell nennt den
      /tmp-Pfad ausdrücklich für Shell-Skripte. Wer den Anhang-Block anfasst: **diese Kopie
      nicht entfernen**, sonst ist die Anhang-Verarbeitung für Netzwerk-Benutzer tot.
  - **Altbestand ohne Registry-Eintrag ist für Werkzeuge unsichtbar** (fail-closed). Wer eine alte
    Anhangsdatei wieder braucht, lädt sie erneut hoch – dann ist sie registriert.
- **Der Agent-API-Key (Benutzer `api`) ist von der Eigentümerprüfung ausgenommen** – er darf
  ohnehin beliebige Aufgaben starten, eine Leseschranke gewinnt dort nichts.
- **Fail-closed:** Ohne Registry-Eintrag ist eine Datei nur für Admins erreichbar. Betrifft den
  Altbestand aus der Zeit vor der Registry – dessen Eigentümer ist nicht rekonstruierbar, und
  Raten wäre schlechter als Verweigern. Die Frist räumt ihn ohnehin ab. Verweigert wird mit
  **404, nicht 403** – ob eine Datei existiert, ist selbst eine Information.
- **Erster Schreiber gewinnt:** `register()` überschreibt einen bestehenden Eintrag NICHT. Sonst
  könnte ein Nutzer (oder ein Prompt-Injection-Text) eine fremde Capability-URL in seine Antwort
  schreiben und die Datei so auf sich umschreiben – Pfad (a) in `_deliver_docs` registriert jede
  URL, die im Text auftaucht.
- **Nur Capability-Dateien werden abgeräumt.** Roh-Dateien im selben Ordner (Skill-Exporte,
  hochgeladene Anhänge wie `Manager_IDs.xml`) sind über den Endpunkt gar nicht erreichbar
  (`fullmatch` → 400) und werden von Tools über ihren Namen weiterbenutzt – Löschen würde
  laufende Abläufe brechen.
- **FALLSTRICK – das Token gehört NUR ins DOM, nie in den Markdown:** `chatlib.js::_withToken()`
  hängt `?token=` erst beim Rendern an (`_inline()` läuft bei jeder Anzeige neu). Der Chat-Verlauf
  liegt auf Platte, geht teils in den LLM-Kontext und wird exportiert – ein Sitzungstoken hat dort
  nichts zu suchen. Ergänzt wird ausschliesslich `/api/documents/…`; sonst flösse das Token beim
  Rendern eines fremden Links an einen fremden Host ab. Token-Schlüssel in dieser Reihenfolge:
  `jarvis_token`, `jarvis_chat_token`, `jarvis_uc_token` (gleiche Kette wie `support.js::TOKEN_KEYS`).
- **`run_task_headless` (WhatsApp/Telegram/Cron) liefert keine Dokumente aus** – `_deliver_docs`
  wird dort nicht aufgerufen. Wer das ergänzt, braucht einen anderen Auslieferungsweg als einen
  Link, der eine Portal-Anmeldung verlangt.

## Anwesenheit: „Angemeldete Benutzer" (seit 2026-07-30)
- **Was es ist:** Ein Personen-Symbol oben rechts im Portal – **zwischen** Desktop (VNC)
  und Dokumente –, das zeigt, wer am System angemeldet war und ist: grüne Pille = online,
  graue = offline, dazu letzte Anmeldung, letzte Abmeldung und (bei Online) die Zeit seit
  der letzten Aktivität. **Nur für Administratoren.**
  Code: `backend/user_sessions.py`, `GET /api/sessions` + `POST /api/logout`,
  `frontend/js/sessions.js`, Markup/CSS in `portal.html` (`pt-usr-*`).
- **Warum es ein eigenes Modul braucht:** Jarvis hat **keine Sitzungstabelle**. Tokens
  sind zustandslose HMAC-Zeichenketten (`generate_token`); der Server weiß von sich aus
  weder, wer da ist, noch wer sich abgemeldet hat. Das Modul führt genau diese
  Buchhaltung, **ohne am Token-Verfahren etwas zu ändern**.
- **Drei Ereignisse:** `record_login` (aus `/api/login`), `record_logout` (aus dem neuen
  `/api/logout`), `touch` (aus `require_auth`, also bei JEDER authentifizierten Anfrage).
- **FALLSTRICK Leistung – `touch()` darf NICHT bei jedem Aufruf schreiben.** Es läuft
  mehrmals pro Sekunde (Portal- und Chat-Polls). Alles liegt im Speicher, auf Platte geht
  es gedrosselt (`FLUSH_INTERVAL = 20 s`) sowie sofort bei An-/Abmeldung; `shutdown`
  ruft `flush()`, sonst fehlen die letzten 20 Sekunden. Geschrieben wird atomar
  (`os.replace`) – ein Absturz mitten im Schreiben darf keine halbe Datei hinterlassen.
- **„Online" ist ABGELEITET, nicht gemeldet:** letzte Anfrage jünger als
  `ONLINE_WINDOW = 120 s` UND keine Abmeldung danach. Wer den Tab schließt, meldet sich
  nicht ab, sondern verstummt – er erscheint deshalb noch bis zu zwei Minuten als online.
  Der Hinweistext im Panel sagt das ausdrücklich.
- **`record_logout` setzt `last_seen` NICHT hoch** – sonst gälte der Benutzer nach dem
  Abmelden noch zwei Minuten als online. Genau dafür gibt es einen Test.
- **Das Abmelde-Signal muss VOR dem Verwerfen des Tokens raus** und braucht
  `keepalive: true` (`sessions.js::logout`): die Seite navigiert unmittelbar danach weg,
  ohne keepalive bricht der Browser die Anfrage ab. `sendBeacon` scheidet aus – es kann
  keinen `Authorization`-Header setzen. Verdrahtet in **allen** Abmeldewegen: portal.html,
  chat.js, support.js, wissen.js, userchat.js, app.js (`showLoginScreen`) und
  security_incidents.js (Sperr-Abmeldung).
- **Schlüssel wird normalisiert** (`_key`): klein, ohne UPN-Suffix und ohne
  Domänen-Präfix. Sonst stünde dieselbe Person mehrfach in der Liste, je nachdem wie sie
  sich angemeldet hat.
- **Der Domänen-Präfix hing an der TIPPFORM des Anmeldefelds (Fix 2026-08-02).** Gemeldet als
  „im Popup fehlt oft der Präfix `nexus`". Ursache: der Anzeigename war schlicht der Text aus dem
  Login-Feld. Wer `nexus\andrea.ladd` eingab, stand mit Präfix in der Liste; wer `andrea.ladd`
  oder `andrea.ladd@nexus.int` eingab, ohne – bei derselben Person am selben Verzeichnis.
  - `main.py::_display_name()` leitet ihn jetzt aus dem ab, was das System **weiß**: lokale
    Konten (`ALLOWED_USERS`, also `jarvis`) bekommen **keinen** Präfix (sie stammen nicht aus dem
    Verzeichnis, `nexus\jarvis` wäre schlicht falsch), ein vorhandener `domäne\`-Anteil bleibt,
    sonst Kurzname aus `ad_domain` (erste Beschriftung: `nexus.int` → `nexus`). **Ohne
    konfigurierte Domäne wird nichts geraten.** Der Kurzname stammt aus dem DNS-Namen und muss
    nicht dem NetBIOS-Namen entsprechen – vertretbar, weil er reine Anzeige ist; angemeldet,
    gesucht und berechtigt wird über den normalisierten Namen.
  - **`_richer()` verhindert das Zurückfallen:** `touch()`/`note_action()` laufen bei jeder
    Anfrage, die Zwangsabmeldung kennt nur den normalisierten Namen. Ohne diese Regel hätte der
    nächstbeste Aufruf den guten Namen wieder durch den dürftigen ersetzt – der Präfix wäre
    scheinbar zufällig verschwunden. Regel: ein Name MIT Domänenanteil wird nie durch einen OHNE
    ersetzt. **Nur `record_login()` setzt unbedingt** (`force=True`) – nur sie ermittelt den Wert
    frisch aus der Konfiguration.
  - **Der Präfix muss BEIM AUSLESEN entstehen, nicht nur beim Schreiben** (Nachbesserung am
    selben Tag). Die erste Fassung reicherte den Namen nur bei Aktivität an – „Altbestand heilt
    sich beim nächsten Request". Auf ECHT blieben damit **drei Einträge ohne Präfix**:
    `sven.sander`, `jonas.reichelt`, `kai-olaf.pieth` waren seit dem Update nicht mehr da.
    Daneben standen zwei MIT Präfix (`rene.pfeiffer`, `dieter.jeske`) – die hatten ihn damals
    schlicht selbst eingetippt. Das sah nach Zufall aus und war es auch.
    **Genau die längst offlinen Einträge sind in einer „wer war da"-Liste die interessanten** –
    auf Aktivität zu warten hilft dort nie. `GET /api/sessions` schickt den Namen jetzt durch
    `_display_name()`, bevor er hinausgeht (fail-safe: ein Fehler dabei kippt die Liste nicht).
    Die Anreicherung beim Schreiben bleibt, sie hält die Datei konsistent.
  - **`_NON_DOMAIN_USERS = {"api", "root", "system"}`** neben `ALLOWED_USERS`: `api` ist der
    Agent-API-Benutzer. Er kommt heute nicht in die Liste (`_note_activity` hängt an
    `require_auth`, das nie `api` liefert), aber die Leseaufbereitung greift auf JEDEN Eintrag –
    ein `nexus\api` wäre schlicht falsch.
  - **Merkregel:** Wenn eine Anzeige aus gespeicherten Altdaten kommt, reicht es nicht, das
    Schreiben zu reparieren. Entweder man migriert den Bestand oder man bereitet beim Lesen auf.
    „Heilt sich beim nächsten Request" ist keine Lösung für Daten, deren Wert gerade darin
    besteht, dass kein Request mehr kommt.
  - **Verifiziert auf DEV mit nachgestelltem Alt-Eintrag** (offline seit 2,2 Tagen, `display`
    ohne Präfix): erscheint sofort als `nexus\sven.sander`, ganz ohne Aktivität; `jarvis` bleibt
    ohne Präfix. Testdaten danach entfernt, Datei feldgleich zur Sicherung.
- **Altbestand:** Wer sich vor Einführung angemeldet hat, zeigt „Anmeldung: –" – ein
  Zeitpunkt, den niemand aufgezeichnet hat, wird nicht geraten. Heilt sich beim nächsten
  Login. `MAX_USERS = 500` deckelt die Datei (ältester Eintrag nach `last_seen` fliegt).
- **FALLSTRICK Platzhalter (Fix 2026-08-04):** `sessions.hint` nennt `{n}` **zweimal**
  („in den letzten {n} Sekunden" und „bis zu {n} Sekunden weiter als online"), die
  Auflösung lief aber über `.replace('{n}', …)`. `String.replace` mit einem **String**
  tauscht nur das ERSTE Vorkommen – der zweite Platzhalter stand wörtlich in der
  Oberfläche. Jetzt `.replace(/\{n\}/g, …)`. Beim Ergänzen von Texten mit mehr als
  einem gleichen Platzhalter immer global ersetzen. Ein Sweep über alle i18n-Werte zeigte:
  `sessions.hint` ist der **einzige** Schlüssel mit doppeltem Platzhalter, die übrigen 23
  `.replace('{n}', …)`-Stellen sind korrekt.
- **Die Pille hat DREI Stufen** (seit 2026-08-04): `online` (grün) · `inaktiv` (orange,
  `is-idle`) · `offline` (grau). Schwelle für „inaktiv" ist `IDLE_WARN` (30 Min), **nicht**
  `IDLE_AB` (5 Min) – bei fünf Minuten wäre in einer Liste mit zwanzig Anmeldungen fast
  jeder „inaktiv", dieselbe Begründung wie bei der Färbung der Untätigkeits-Angabe.
  - **Ist `idle_seconds` null, bleibt es bei „online".** Das ist der Fall „frisch
    angemeldet, noch keine Handlung" – Untätigkeit, die nicht gemessen werden kann, wird
    nicht behauptet (Test `dora`).
  - **Der Zähler musste mit:** „2/11" neben einer Zeile, die „inaktiv" sagt, liest sich wie
    ein Fehler. Er zeigt jetzt `2/11 · 1 inaktiv` (nur ungefiltert; beim Filtern zählt
    weiterhin die Trefferzahl). Zustand und Zähler kommen aus **einer** Funktion
    (`zustand(u)`), damit sie nicht auseinanderlaufen können.
  - **Zwei bestehende Tests schrieben das alte Verhalten fest** und mussten nachgezogen
    werden: „trotzdem online" für den 40-Minuten-Fall und „Zähler wieder online/gesamt"
    (`=== '3/4'`). Wer die Pille anfasst, muss dort nachsehen.
  - **FALLSTRICK beim Erweitern des UI-Tests:** die späteren Abschnitte rendern eigene
    Datensätze. Ein neuer Block am Ende muss den Ausgangsdatensatz erst wieder laden,
    sonst prüft er ein fremdes DOM und meldet überall `null`.
  - Auf ECHT nachgerechnet: `silke.nitschkowski` (idle 21.482 s) → **inaktiv**,
    `andreas.bender` (idle 310 s) → online, Zähler `2/11 · 1 inaktiv`.
- **„online" heißt „es kommen Anfragen", nicht „arbeitet gerade".** Ein offener Tab
  pollt im Hintergrund und hält damit `last_seen` frisch – der Benutzer bleibt online,
  während `last_action` (echte Handlung: Nachricht, Suche, Speichern; `_ACTION_IGNORE`
  filtert technisches Rauschen) beliebig alt wird. Auf ECHT gemessen: letzte Anfrage vor
  35 s, letzte Handlung vor 20.916 s (5,8 h) → online **und** 5,8 h untätig. Das ist
  gewollt und steht so im Hinweistext; genau dieser Hinweis war durch den
  Platzhalter-Fehler oben halb unlesbar.
- **Die Pille trägt die Aussage doppelt** (Farbe UND Text „online"/„offline") – Farbe
  allein ist für Farbfehlsichtige keine Information. Panel **deckend**
  (`var(--bg-secondary)`), gleiche Begründung wie beim Dokumente-Panel.
- **Verifiziert auf DEV:** 53 Einheitentests (`tests/test_user_sessions.py`: Normierung,
  Lebenszyklus, Online-Fenster, Persistenz über Neustart, beschädigte Datei, Drosselung,
  Sortierung, Verdrahtung) + Live gegen den laufenden Dienst (Übersicht, Abmeldung wirkt
  sofort, ohne Token 401) + Browser-Sichtprüfung (Knopf zwischen Desktop und Dokumente
  bei x=814/860/906, grüne Pille `--success`, Escape schließt, Hell-Modus deckend,
  keine Konsolenfehler).
  **FALLSTRICK im Test:** Zwei Schreibvorgänge im Abstand von 0,3 ms bekommen unter Linux
  **denselben** mtime-Tick (grobe Uhr). Ein mtime-Vergleich meldet dann „nicht
  geschrieben", obwohl geschrieben wurde – die Drosselung wird deshalb über den
  DATEIINHALT geprüft.

## Skill-Zugangsdaten waren für jeden lesbar (Fix 2026-08-02)
`GET /api/skills/{name}/config` hing an **`require_auth`** – jeder angemeldete Benutzer konnte
damit die Zugangsdaten SÄMTLICHER Skills im Klartext abrufen: HANA-/RFC-Kennwort und
Bearer-Token (SAP), Jira-/Confluence-Token, IBS-API-Key, Google-Client-Secret. Die Antwort ist
die **rohe** Skill-Config, es gibt keine Feld-Filterung. Der Schreib-Endpunkt daneben war seit
jeher `require_local_auth` – **Lesen war also freier als Schreiben**, was den Fehler beim
Überfliegen unsichtbar machte.
- Jetzt `require_local_auth`. Der Zuschnitt ist unkritisch: **alle** Aufrufer sitzen auf
  `settings.html` (sap.js, jira.js, confluence.js, whatsapp.js, knowledge.js, vision.js,
  kundenverwaltung.js, support_admin.js, skillcfg.js, brandingAdmin), die ohnehin Admins
  vorbehalten ist.
- **`branding.js` ist die Ausnahme, die man prüfen MUSS:** die Datei liegt auf JEDER Seite. Der
  Config-Aufruf steckt aber im Admin-Teil (`window.brandingAdmin`), der nur aus `app.js`
  gestartet wird – und `app.js` lädt allein `settings.html`. Das öffentliche Branding läuft über
  den eigenen Endpunkt **`GET /api/branding` (ohne Anmeldung)** und ist NICHT betroffen; er wird
  schon auf der Loginseite gebraucht. Wer hier aufräumt, darf die beiden nicht verwechseln.
- **Regressionstest `tests/test_skill_config_rights.py`** (11 Prüfungen, ohne fastapi lauffähig)
  hält beides fest: die Dependency am Endpunkt UND dass kein Aufrufer hinzukommt, der außerhalb
  der Einstellungsseite sitzt – genau das wäre der Grund, aus dem jemand die Schranke wieder
  löst. Der alte Stand fällt in den ersten beiden Prüfungen durch (verifiziert).
- Live auf DEV: Admin 200, angemeldeter Nicht-Admin **403 mit der Admin-Meldung** (nicht der
  Login-Schranke), ohne Token 401, `/api/branding` weiterhin 200 ohne Anmeldung.

## SAP-Analysebereich `/sap` (seit 2026-08-02)
- **Was es ist:** Eine eigene Seite für die Geschäftsleitung – Kachel im Portal, nur für
  SAP-berechtigte Benutzer. Drei Dinge auf einer Fläche: **Management-Analysen** (Vorlage wählen →
  Agent wertet lesend aus), **BI-Anbindung** (fertige Verbindungsangaben je Werkzeug) und eine
  **Abfrage-Konsole** (OData/SQL ohne KI). Code: `backend/sap_analyses.py`, Endpunkte
  `GET /sap`, `/api/sap/status|analyses|instructions|ask|stop`, `frontend/sap.html`,
  `frontend/js/sap_portal.js`.
- **Nicht zu verwechseln mit dem SAP-Reiter** (*Einstellungen → SAP*, `frontend/js/sap.js`): dort
  pflegt ein Admin die **Zugangsdaten**, hier wird nur **ausgewertet**. Die Seite zeigt keine
  Zugangsdaten und kann keine speichern. Deshalb auch das Präfix **`sp-`** für alles Neue –
  `sap-` gehört den Reiter-IDs, eine Kollision wäre beim Debuggen kaum zu sehen.
- **Der Analysekatalog liegt im BACKEND, nicht in `i18n.js`** (`sap_analyses.py`, 24 Analysen in
  6 Kategorien, DE+EN). Grund: zu jedem Titel gehört ein **Arbeitsauftrag für den Agenten**, und
  Titel und Auftrag dürfen nicht auseinanderlaufen. Läge der Titel in `i18n.js` und der Auftrag
  hier, wäre das genau das Drift-Muster, das im Projekt schon mehrfach Stunden gekostet hat.
  `catalog(lang)` liefert nur EINE Sprache und **gibt das `task`-Feld nicht heraus** – der
  Arbeitsauftrag ist nichts, was der Browser braucht (Test prüft das).
- **Zuschnitt Aktiengesellschaft:** neben der klassischen Betriebsauswertung (GuV/Bilanz, Working
  Capital, Debitoren-Aging, Auftragsbestand, Spend, Bestände, Personal) ausdrücklich die
  kapitalmarktrechtlichen Pflichten – Segmentberichterstattung (IFRS 8), erwartete Kreditverluste
  (IFRS 9), Konzernkonsolidierung/Intercompany, IKS und Funktionstrennung (§ 91 Abs. 3 AktG),
  Umsatzsteuer/Intrastat, ESG/CSRD und die **Prognoseabweichung als Ad-hoc-Frühwarnung**
  (Art. 17 MAR). Letztere sagt im Auftragstext selbst, dass sie die rechtliche Bewertung NICHT
  ersetzt – eine Auswertung, die eine Ad-hoc-Pflicht behauptet, wäre gefährlicher als keine.
- **`build_task()` – die Reihenfolge ist die Semantik:** Vorspann (Read-Only + Vorgehen) →
  Vorlage → Freitext-Frage → Zielwerkzeug → persönliche Anweisungen. Späteres präzisiert
  Früheres; kippt die Reihenfolge, gewinnt im Zweifel die Vorlage gegen die ausdrückliche
  Anweisung des Benutzers. Genau dafür gibt es einen Test.
- **Read-Only ist die Zusage des Bereichs** und wird zweifach gehalten: hart im `sap_client`
  (OData nur GET, SQL nur SELECT/WITH, RFC nur Whitelist) und im Katalog – ein Test lehnt jeden
  Auftragstext ab, der ein schreibendes Schlüsselwort enthält. Grund für den zweiten: der Client
  würde zwar ablehnen, der Lauf endete dann aber in einer Fehlermeldung statt in einer Auswertung.
- **Der Lauf ist unprivilegiert mit `sap: True`** (`actor={"privileged": False, "sap": True}`).
  Das schaltet `agent.py` die `sap_*`-Werkzeuge frei, **ohne** Systemrechte zu geben. Eigener
  Agent + eigene Sperre (`_sap_agent`, `_sap_agent_lock`) wie beim Avatar: eine Analyse läuft
  Minuten und dürfte den geteilten Hauptagenten nicht für alle anderen blockieren.
- **`permissions.sap` in `/api/me` heißt „darf diesen Bereich BETRETEN"** – Freigabe UND aktiver
  Skill. Eine Kachel, die auf eine 404-Seite führt, ist schlimmer als keine Kachel. Die
  Datenendpunkte prüfen weiterhin nur die Freigabe (`require_sap_access`), damit der
  Einstellungs-Reiter unabhängig vom Skill-Zustand bedienbar bleibt. Das Feld ist bewusst ein
  **Unterobjekt**: jede Kachel mit eigenem Abruf kostet einen Roundtrip – der Grund, aus dem
  /settings einmal neun Sekunden brauchte.
- **Die Seitenroute prüft die Berechtigung NICHT** (eine normale Navigation trägt keinen
  Authorization-Header, der Token liegt im localStorage). `/sap` prüft nur, ob der Skill aktiv
  ist; die Seite holt als Erstes `/api/me` und schickt Unberechtigte aufs Portal. Sicherheits-
  relevant ist das nicht – die Seite ist eine leere Hülle. **Fail-closed:** fehlt
  `permissions` ganz (älteres Backend), gilt „nicht freigegeben".
- **Der Verlauf speichert die FRAGE, nie das Ergebnis** (`localStorage`, 25 Einträge): sonst
  lägen Geschäftszahlen im Browser-Speicher. Ein Klick im Verlauf **übernimmt nur, er startet
  nicht** – eine Analyse kostet Minuten und Last, ein versehentlicher Klick darf sie nicht
  auslösen. Beides ist getestet.
- **Sprachwechsel:** der Katalog kommt übersetzt vom Server, `applyLang()` erreicht ihn also
  nicht. Dafür feuert `i18n.js` jetzt das Ereignis **`jarvis-lang-changed`** (additiv, Zuhörer
  freiwillig). Der Zuhörer vergleicht mit `_catalog.lang` – ohne diesen Vergleich holte die Seite
  den Katalog beim Aufbau zweimal, weil `applyLang()` auch bei DOMContentLoaded läuft.
- **Avatar:** `/sap` bindet dieselben Bausteine ein wie `/support` und `/portal` (clippy.css,
  avatar.css, jQuery, clippy.min.js, avatar.js – Skripte NACH `sap_portal.js`). Der Ein/Aus-
  Schalter baut sich selbst und hängt sich **vor `#btn-theme-toggle`** – fehlt diese Id auf einer
  Seite, landet er als frei schwebender Knopf irgendwo. Der Zustand wird pro Pfad gemerkt
  (`jarvis_avatar_off:/sap`).
- **Sichtbarkeit je Analyse (seit 2026-08-02):** *Einstellungen → SAP → „Sichtbare Analysen im
  Bereich /sap"* – ein Kästchen je Vorlage, nach Kategorien gruppiert, plus „Alle auswählen/
  abwählen" und Zähler.
  - Gespeichert wird die Liste der **AUSGEBLENDETEN** Ids (`hidden_analyses` in der
    SAP-Skill-Config), nicht der sichtbaren. **Leer heißt „alles sichtbar"** – anders als bei den
    Berechtigungsfeldern, und das ist Absicht: dies ist eine Aufräum-Einstellung, keine Freigabe
    (wer den Bereich betreten darf, hat die Freigabe schon). Bei „leer = nichts" stünde nach dem
    Einschalten des Skills ein leeres Pulldown da, und eine später ergänzte Analyse wäre still
    unsichtbar.
  - **Eine leer gewordene Kategorie verschwindet mit** – eine Gruppenüberschrift ohne Einträge
    sieht im Pulldown wie ein Fehler aus. `admin_catalog()` behält dagegen ALLE Kategorien und
    ALLE Analysen: sonst ließe sich nichts wieder einblenden.
  - **`/api/sap/ask` lehnt ausgeblendete Analysen ab.** Der Verlauf liegt im localStorage des
    Browsers und überlebt das Ausblenden, ein offener Reiter ebenso – ohne diese Prüfung wäre
    „ausgeblendet" nur eine Empfehlung. Das Frontend fängt den Fall zusätzlich ab und sagt es,
    statt das Feld wortlos auf „freie Frage" springen zu lassen.
  - **`GET /api/sap/analyses/catalog` hängt an `require_local_auth`, NICHT an
    `require_sap_access`:** `_user_may_use_sap` kennt bewusst keinen Admin-Bypass – ein
    Administrator ohne SAP-Freigabe könnte die Sichtbarkeit sonst nicht pflegen (auf DEV genau
    dieser Fall). Der Katalog enthält keine Daten aus dem SAP-System.
  - **Gespeichert wird über den vorhandenen `POST /api/skills/sap/config`** (Admin,
    `update_skill_config` merged per `current_config.update(data)`). Der Sichtbarkeits-Knopf
    sendet **nur** `hidden_analyses`, der Verbindungs-Knopf **nie** dieses Feld – sonst
    überschriebe ein Klick den jeweils anderen Teil mit dem Formularstand. Beides ist getestet.
  - `normalize_hidden()` nimmt Liste ODER kommagetrennten Text und **verwirft unbekannte Ids,
    statt sie zu raten**: sonst bliebe die Id einer entfernten Analyse dauerhaft in der
    Konfiguration stehen und würde bei jedem Speichern mitgeschrieben.
- **FALLSTRICK im UI-Test:** `window.location` lässt sich in jsdom **weder ersetzen noch
  überschreiben** (`Cannot redefine property`) – weder am Fenster, noch an `Location.prototype`,
  noch an der Instanz. Eine Weiterleitung erkennt man über den jsdomError
  „Not implemented: navigation" (VirtualConsole); das ZIEL gibt jsdom nicht heraus und wird
  deshalb per Quelltext-Prüfung abgedeckt. Für den Einstellungen-Reiter wird `settings.html` mit
  `runScripts: 'outside-only'` geladen und nur `i18n.js` + `sap.js` eingespielt – `app.js` würde
  sonst fremde Poll-Timer starten.
- **Verifiziert:** 41 Katalog-Tests (`tests/test_sap_analyses.py`, ohne fastapi lauffähig) +
  59 UI-Tests in jsdom gegen die echten Dateien (`tests/test_sap_portal_ui.js`) = 100/100.
  Live auf DEV: Gate greift (Nicht-Freigegebener → `permissions.sap: false` + HTTP 403 auf allen
  `/api/sap/*`), Katalog liefert 24 Analysen in DE und EN, Anweisungen speichern/lesen,
  `ask` meldet bei unkonfiguriertem SAP Klartext statt eines Agentenlaufs.
  **Ein echter Agentenlauf gegen ein SAP-System ist NICHT geprüft** – auf DEV sind keine
  SAP-Zugangsdaten hinterlegt.

## Info-Dokumente im Portal (`frontend_info_files/`, seit 2026-07-29)
- **Was es ist:** Ein Ablage-Ordner neben dem Backend (`/opt/jarvis/frontend_info_files`,
  umstellbar über `JARVIS_INFO_DIR`). Ein Administrator kopiert Dateien hinein (Handbuch,
  Merkblatt, Formular), das Portal zeigt sie oben rechts hinter einem **Ordnersymbol**.
  Code: `backend/info_files.py`, `GET /api/info_files` (+ `/{name}`), `frontend/js/info_files.js`,
  Markup/CSS in `portal.html` (`pt-info-*`).
- **Das Symbol erscheint NUR, wenn Dateien vorhanden sind** (`#pt-info-wrap` startet auf
  `display:none`, `info_files.js::load()` blendet es ein). Ein Knopf, der ein leeres Fach
  öffnet, ist eine Enttäuschung – und der leere Ordner ist der Normalzustand nach dem Deploy.
- **Bewusst NICHT `data/documents`** (siehe dort): jenes hält vom Agenten ERZEUGTE Dateien mit
  Capability-Namen, Eigentümer-Bindung und Verfallsfrist. Hier liegen bewusst abgelegte Dateien
  mit sprechenden Namen, die **jeder angemeldete Benutzer** lesen darf – deshalb keine
  Eigentümer-Prüfung. Vertrauliches gehört in die Wissensdatenbank mit Gruppenrechten.
- **Pfad-Sicherheit in `resolve()`:** Der Name aus der URL wird nicht bloß angehängt und
  gehofft – nach `resolve(strict=True)` wird geprüft, dass `parent` **wirklich** der Info-Ordner
  ist. Ein Prefix-Vergleich allein wäre durch einen Symlink zu umgehen; der Test legt genau so
  einen an. Abgewiesen werden zusätzlich Pfadanteile (`/`, `\`), `..`, versteckte Dateien und
  NUL-Bytes – Antwort immer **404**, nie 400/403 (der Grund verrät sonst, was im Ordner liegt).
- **`inline` nur für PDF/Bild/Text**, alles andere ist ein Download (ein „inline" geliefertes
  `.docx` erscheint als Zeichenmüll). **Ausnahme `_NEVER_INLINE_EXT`: SVG/HTML/XML sind trotz
  passender Kategorie immer Download** – SVG darf Skripte enthalten, die im Tab im **Origin des
  Portals** liefen und dort an `localStorage` samt Sitzungstoken kämen. Dazu
  `X-Content-Type-Options: nosniff`, damit der Browser den Typ nicht selbst „errät".
- **Verknüpfungen (`.url`, seit 2026-07-29):** Eine Datei mit der Endung `.url`/`.link`/
  `.weblink` wird nicht zum Download angeboten, sondern **öffnet ihr Ziel** (Kategorie `link`,
  Weltkugel-Symbol, in der Meta-Spalte steht der Host statt der Größe, Anzeigename ist der
  Dateiname **ohne** Endung). `read_link()` versteht das Windows-Format
  (`[InternetShortcut]` + `URL=…`, so entsteht die Datei beim Ziehen aus der Adresszeile) und
  – tolerant – eine Datei, die nur die Adresse enthält.
  - **Nur `http`/`https`, an ZWEI Stellen geprüft** (`_LINK_SCHEMES` im Backend,
    `isWebUrl()` im Frontend): ein `javascript:`-Ziel liefe beim Klick im **Origin des Portals**
    und käme an das Sitzungstoken im `localStorage`; `file:`/`data:` führen am Server vorbei.
    Wer eine Verknüpfung ablegen darf, soll damit **kein Skript ausführen** können.
  - **Unbrauchbare Verknüpfung wird zur normalen Datei** (kein `url`-Feld → Download, und dann
    auch das Datei-Symbol statt der Weltkugel; ein Globus, der eine Datei herunterlädt, wäre
    eine falsche Ansage). Deckel `_LINK_MAX_BYTES = 8192` – eine Verknüpfung ist winzig.
  - Links tragen `rel="noopener noreferrer"`: das Ziel soll nicht erfahren, aus welcher
    internen Seite der Klick kam.
- **Die Kategorie (`kind`) kommt vom Backend**, nicht aus einer zweiten Endungs-Tabelle im
  Frontend: sonst müsste ein neuer Dateityp an zwei Stellen nachgetragen werden und Symbol und
  Auslieferungsart würden auseinanderlaufen. Symbole/Farben in `info_files.js` je `kind`
  (CSS-Klassen `.pt-ico-*`, Farben aus Theme-Variablen).
- **Panel ist DECKEND** (`var(--bg-secondary)`), nicht Glas: darunter liegen die Portal-Karten
  mit Text, der bei halbtransparentem Hintergrund durch die Dateinamen scheint (im UI-Test
  sichtbar geworden). `backdrop-filter` ist kein Ersatz – er wird nicht überall gerendert.
- **Token gehört nur ins DOM:** die Links tragen `?token=` (ein `<a>`/Tab kann keinen
  Authorization-Header setzen, gleiche Begründung wie bei `/api/documents`); die Liste wird bei
  jedem Öffnen neu gebaut, nichts davon wird gespeichert. Der Ordner wird beim Öffnen des Panels
  neu geladen, damit eine gerade abgelegte Datei ohne Neuladen der Seite auftaucht.
- **Der Ordner wird beim Start angelegt** (`startup_info_files_dir`, gehört dann `jarvis`), damit
  ein Admin nur noch hineinkopieren muss. Fehlende Rechte sind KEIN Startfehler – dann bleibt die
  Liste leer und das Symbol aus.
- **Verifiziert auf DEV:** 52 Backend-Tests (Kategorien, inline/attachment, Traversal inkl.
  Symlink, leerer/fehlender Ordner) + 17 UI-Tests gegen die echte Portalseite mit gemockter API
  (Symbol aus/ein, Panel, typgerechte Symbole, `target=_blank` vs. `download`, Escape,
  Hell-Modus). Live gegen echte Dateien geprüft: Umlaut- und Leerzeichen-Namen laufen
  (`filename*=utf-8''…`), ohne Token 401.
  **FALLSTRICK im UI-Test:** Playwright prüft Routen in **umgekehrter** Registrierungsreihenfolge
  – ein zuletzt registrierter `**/api/**`-Catch-all verschluckt die spezifische Mock-Route, der
  Test läuft dann grün ohne etwas zu prüfen.

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
- **Beispiele müssen mit den AKTIVEN Fähigkeiten übereinstimmen** (Korrektur 2026-08-04).
  `web` („Web-Recherche") und `image` („Bild generieren") sind **entfernt**: für
  Web-Recherche existiert **gar kein Werkzeug** (`backend/tools/` hat kein
  `web_search.py`), und `generate_image` läuft über das **aktive Profil** – ist das ein
  Textmodell (auf ECHT `Qwen/Qwen3.6-35B-A3B-FP8`, `openai_compatible`), gibt das
  Beispiel nur die Fehlermeldung des Tools aus. Ersetzt durch `jira` und `conf`: beide
  Skills sind aktiv UND konfiguriert (live geprüft: Jira liefert offene Tickets,
  Confluence 21 Spaces und 10 Treffer je Suchbegriff), beide sind **intern** und stehen
  daher nicht in `_INTERNET_TOOLS` – funktionieren also auch für Benutzer ohne
  Internet-Freigabe. Beide Beispiele sind bewusst **nur lesend**: ein Beispiel-Prompt
  darf kein echtes Ticket anlegen.
  - **SAP wäre der naheliegende Kandidat gewesen und ist es NICHT:** der Skill ist auf
    ECHT aktiv, aber die Verbindung ist nicht konfiguriert (`sap`-Config leer) – das
    Beispiel hätte genauso versagt. Vor dem Setzen eines Beispiels immer prüfen, ob der
    Skill aktiv **und** konfiguriert ist.
  - **`cron` und `multi` ebenfalls ersetzt** (gleicher Tag): `cron_create` und
    `spawn_agent` stehen beide in `_BLOCKED_TOOLS_FOR_LDAP`, für Domänen-Benutzer also
    gesperrt; der Cron-Prompt nannte zusätzlich Kalendertermine, obwohl der
    `google`-Skill auf ECHT nicht aktiv ist. Neu: `ibs` (Kundenvorgänge nach
    Schlagworten – live geprüft, liefert echte Vorgänge mit Nummer und Datum; die
    IBS-Zugangsdaten liegen unter der **jira**-Skill-Config, `ibs_api_url`/`ibs_api_key`)
    und `multi2` („Alle Quellen auf einmal": Wissensdatenbank + Confluence + Tickets in
    EINEM Auftrag zusammenführen, Widersprüche benennen). Letzteres behält die Absicht
    des alten Multi-Agenten-Beispiels – eine große Aufgabe – ohne Sub-Agenten.
  - **Der Wächter-Test verbietet die Rückkehr:** `web`, `image`, `cron`, `multi` dürfen
    als Key nicht wieder auftauchen, und kein Prompt darf Bildgenerierung, Web-Recherche,
    Sub-Agenten oder einen zeitgesteuerten Auftrag verlangen. Er belegt zusätzlich am
    Quelltext von `agent.py`, dass `cron_create`/`spawn_agent` wirklich gesperrt sind.
    **FALLSTRICK im Test selbst:** ein Muster `/wiederkehrend/` trifft „wiederkehrende
    **Themen**" im IBS-Prompt – der Test schlug an der eigenen Unschärfe fehl, nicht am
    Inhalt. Jetzt auf die Auftrags-Anlage präzisiert.
- **Eine Änderung an `_WELCOME_EXAMPLES`/i18n wirkt SOFORT auch in bereits
  ausgelieferten Sitzungen** – `_WELCOME_MARK` muss dafür NICHT hochgezählt werden. Das
  Backend speichert nur `{role:"bot", kind:"welcome", text}` als Notfalltext; die Karte
  baut `_renderWelcomeCard()` bei JEDER Anzeige neu aus der Liste und den i18n-Keys.
  Der Marker ist nur nötig, wenn Benutzer die gelöschte Sitzung erneut bekommen sollen.
  Ein jsdom-Test (`tests/test_welcome_examples.js`, 44 Prüfungen) hält das fest: er
  rendert mit einem Backend-Eintrag samt ALTEM Notfalltext und erwartet die neuen
  Beispiele.
- **Klick = sofort senden** (`_useExamplePrompt` → `sendMessage()`). Die Karte bleibt danach
  stehen, damit weitere Beispiele erreichbar sind.
- **FALLSTRICK – Index-Zuordnung DOM↔Verlauf:** Der Eintrag hat `role:"bot"`, erzeugt aber KEINE
  `.msg-row`. Alle Stellen, die eine DOM-Zeile per Rollen-Index auf `_chatHistory` abbilden
  (`_deleteBubble`, Mehrfach-Loeschen `onDelete`), muessen ihn ueberspringen – dafuer gibt es
  `_isRowEntry()`. Ohne das loescht ein Klick auf die erste Bot-Antwort den falschen Eintrag.
  `_submitEdit`/`truncateHistoryToUserIndex` zaehlen nur `user`-Eintraege und sind nicht betroffen.

## Chat-Sitzungen: „Neue Sitzung" war nur ein Trenner (geklaert 2026-07-28)
**Der vermutete Fehler existierte nicht.** Verdacht war: „Neue Sitzung" im Chat erzeugt keine
neue Backend-Sitzung, weil auf ECHT zwei Auftraege (07:00 PPTX, 07:25 Bild) trotz sichtbarem
Trenner „── Neue Sitzung ──" denselben Kontext teilten. Nachgemessen mit 13 Pruefungen
(zwei echte Sitzungen ueber die API, Laeufe mit LLM-Stub): die Trennung ist auf JEDER Ebene
intakt – `_hist_key(user, sid)`-Buckets, der an das Modell gereichte Kontext, die
`context.json` je Sitzung, und der sitzungslose Bucket bleibt separat.
- **Die Ursache war die Beschriftung.** Der Trenner wird von `_restoreHistory()` an das ENDE
  des wiederhergestellten Verlaufs gesetzt – er erscheint also, wenn eine BESTEHENDE Sitzung
  geoeffnet wird, und trennt nur alte von neuen Nachrichten. Er hiess trotzdem „Neue Sitzung".
  Jetzt: **„Sitzung fortgesetzt"** (`chat.session_continued`). Eine neue Sitzung entsteht
  ausschliesslich ueber „+ Neuer Chat" (`_newSession` → `POST /api/chat/sessions`).
- **Sichtbar gemacht:** die Kontext-Pille traegt jetzt einen Titel-Tooltip mit Name UND Id der
  Sitzung, zu der der Kontext gehoert (`chat.ctx_session_hint`). Die Verwechslung war nur
  moeglich, weil man das nirgends ablesen konnte.
- **Echte Luecke, die dabei auffiel:** zwischen Seitenaufbau und dem Ende von
  `_initSessions()` ist `_activeSid` noch `null`. Wer in dieser Zehntelsekunde abschickt,
  sendet den Auftrag OHNE `session_id` – der Kontext landet im sitzungslosen Bucket und
  gehoert zu keiner Sitzung der Seitenleiste. `sendMessage()` beschafft jetzt zuerst eine
  Sitzung (`_ensureSession()`) und sendet dann; **genau ein** Nachversuch, danach wird auch
  ohne Sitzung gesendet – eine Endlosschleife waere schlimmer als ein Auftrag ohne
  Sitzungsbezug.
- Merkregel: eine Beschriftung, die einen Zustand behauptet, den sie nicht kennt, kostet
  Stunden Fehlersuche. `/userchat` und `/support` sind nicht betroffen, die kennen keine
  Sitzungen.

## Verlaufs-Buchhaltung im Agent-Loop (Fix 2026-07-28)
**Vorfall:** Auf ECHT kam die Antwort auf eine PowerPoint-Anfrage (07:01) erst beim
*nächsten* Auftrag (07:25) heraus – vermischt mit dessen Antwort. Der gespeicherte
Kontext (`data/chats/<user>/<sid>/context.json`) sah so aus:
`[user PPTX] [model fc:shell_execute] [user Bild] [model fc:generate_image] [user fresp]
[user Bild] [model Antwort auf BEIDES]` – ein `function_call` ohne `function_response`,
die PPTX-Frage ohne Antwort, und die Bild-Frage doppelt.
- **Regel:** Ein Lauf hinterlässt den Kontext ENTWEDER vollständig (Frage genau einmal +
  Antwort als letzter Eintrag, jeder `function_call` mit seiner `function_response`) ODER
  unverändert. Ein Zwischenzustand lässt das Modell die offene Frage beim nächsten Lauf
  mitbeantworten – das ist der ganze Fehler.
- **Behoben:** (a) Der Leere-Antwort-Zweig endete mit einem nackten `break`, nachdem der
  Kurz-Prompt-Neuversuch seinen Text an den Nutzer gesendet hatte – der Nutzer sah eine
  Antwort, der Kontext kannte sie nicht. Jetzt wird sie eingetragen. (b) Endet ein Lauf
  ohne jede Antwort, setzt `_rollback_history()` auf den Schnappschuss `_hist_before_run`
  zurück (Inhalt per `[:] =` ersetzen, NICHT die Liste – darauf zeigen noch
  `_user_histories` und `_current_chat_history`).
- **`_ensure_user_msg()` statt Verlaufs-Vergleich:** Die Frage darf pro Lauf genau einmal
  in den Verlauf; gemerkt wird das über den lauf-lokalen Merker `_user_msg_added`.
  Die alten Prüfungen (`chat_history[-1] != _user_msg`, an drei Stellen) übersahen sie
  nach einem Werkzeugschritt, weil dort die `function_response` steht → Frage doppelt.
  **Ein Wächter, der den ganzen Verlauf durchsucht, ist ebenfalls falsch** – er
  unterschlägt eine wiederholte, wortgleiche Frage. Deshalb der Merker.
- **`serialize_history`/`deserialize_history` protokollieren Verluste.** Beide hatten
  `except Exception: pass` pro Eintrag – ein nicht konvertierbarer Eintrag verschwand
  lautlos und konnte so aus einem gültigen Gespräch ein ungültiges machen.
- **Regressionstest:** fünf Abläufe (direkte Antwort / Werkzeug+Antwort / Werkzeug+leer+
  Neuversuch / gar keine Antwort / **dieselbe Frage zweimal**). Der alte Stand fiel in
  3 von 4 durch, der neue besteht 5/5 – zusätzlich live gegen ein echtes Modell geprüft.
- **Nicht behoben (offen):** Die „Neue Sitzung" im Chat-Fenster hat auf ECHT KEINE neue
  Backend-Sitzung erzeugt – beide Aufträge liefen in `f8fb6ee0b419`. Der geteilte Kontext
  war damit erwartungswidrig, unabhängig von der Buchhaltung oben.

## Wissens-Extraktor: „Fragen & Antworten generieren (KI)" (Fix 2026-07-28)
Der Haken steht in `/wissen` bewusst **unter allen drei Eingabearten** (Datei, URL,
Confluence) – gewirkt hat er nur bei der Datei. Ursache war eine verschluckte Null:
- **`_clamp_qa_count()` gab für 0 UND für „keine Angabe" beides `None` zurück**, und `None`
  bedeutete Standardregel (`5–15 Frage-Antwort-Paare`). Ein ausdrückliches „keine Fragen"
  war damit gar nicht ausdrückbar. Jetzt drei Zustände: `None` = keine Angabe → Standard,
  `0` = ausdrücklich keine, `1..50` = genau so viele. **Aufrufer dürfen nicht per Falsyness
  prüfen** (`if n:`), sondern müssen `n == 0` abfragen – genau daran lag der Fehler.
- **`extract_to_pending()` kannte `qa_count` überhaupt nicht** – der Weg, den BEIDE
  Confluence-Importe nutzen (`/api/wissen/extract/confluence` und
  `/api/knowledge/extract/confluence`). Parameter ergänzt und in allen vier Aufrufstellen
  durchgereicht (Einzelseite + Bulk je Endpunkt).
- **`_drop_qa_if_unwanted()` als zweite Schranke:** Der Prompt sagt bei 0 „qa_pairs MUSS
  ein leeres Array sein", aber ein Prompt ist eine Bitte, keine Garantie – Modelle liefern
  trotzdem Fragen. Verifiziert mit einem absichtlich widersprechenden Stub-Modell.
- **Frontend:** `qaWish()` in `wissen.js` liefert die Anzahl **einschließlich** des
  Haken-Zustands (0 wenn aus) und wird von allen drei Eingabearten benutzt. Vorher sandte
  der Confluence-Import gar kein Feld und der URL-Import `qa_count` bedingungslos.
- **FALLSTRICK Datei-Upload:** Dort gatet `if qa_n > 0` die GESAMTE Extraktion – bei
  ausgeschaltetem Haken wird die Datei nur abgelegt, es entsteht kein Entwurf. Das ist
  gewollt; `qa_n` darf in `/api/wissen/upload` deshalb **nicht** auf `None` umgestellt
  werden (der Vergleich `> 0` würde mit `None` werfen).
- **Verifiziert auf DEV** gegen echtes Confluence: `qa_count=0` → keine Fragen, aber
  Zusammenfassung und Fakten weiterhin extrahiert; `qa_count=3` → genau 3; ohne Feld →
  Standardregel. Dazu 19 Einheitentests der Zustandslogik.

## /wissen → „Deine Entwürfe": Vorschau-Platz + Sammel-Übernahme (2026-07-28)
- **Kein Scroll-Sprung bei „Prüfen":** `window.scrollTo(0, document.body.scrollHeight)` sprang ans
  **Seitenende** – und damit von der Vorschau WEG, denn `#wi-ext-review` steht im HTML **oberhalb**
  der Liste (`#wi-pending-list`). Zweiter, subtilerer Sprung: das Einblenden verlängert den Bereich
  über der Liste und zieht den angeklickten Eintrag unter dem Zeiger weg. Gelöst, indem die
  Verschiebung der eigenen Zeile gemessen und per `window.scrollBy(0, delta)` ausgeglichen wird.
- **„Prüfen" ist ein Umschalter:** ein zweiter Klick auf denselben Knopf schließt die Vorschau
  wieder (`_revId === it.id` + gefüllter Container → `clearReview()`). Vorher war „Prüfen" eine
  Einbahnstraße – die Vorschau ließ sich nur über Freigeben oder Verwerfen loswerden.
- **Die Vorschau wandert, es gibt aber nur EINEN Container.** `showReview(d, anchor)` verschiebt
  `#wi-ext-review` per `insertBefore` **direkt unter die angeklickte Zeile**; ohne `anchor` (nach
  einer Extraktion) zurück an seinen Heimatplatz unter dem Extraktor. Zwei Container hätten zwei
  Wege zum Freigeben/Verwerfen bedeutet.
  - **FALLSTRICK:** Liegt die Vorschau in der Liste, würde `box.innerHTML = ''` in `loadPending()`
    sie **mitlöschen** (danach liefert `$('wi-ext-review')` null). Deshalb holt `loadPending()` sie
    per `_revPlace(null)` VOR dem Leeren heim und setzt sie danach über `_revId` wieder unter ihre
    Zeile. Aus demselben Grund gibt es `clearReview()` statt `innerHTML = ''` an den Aufrufstellen.
  - `_revHome` wird **nur beim ersten Verschieben** gesetzt – ein erneutes Auslesen würde die
    verschobene Position als „Heimat" merken.
- **Sammel-Übernahme** (Knopf `#wi-drafts-appsel`, seit 2026-07-28): markierte Entwürfe lassen sich
  jetzt nicht nur löschen, sondern auch übernehmen. Sind ALLE markiert, heißt der Knopf „Alle
  übernehmen (n)". Übernommen wird **wie vorliegend** – Titel/Q&A korrigiert man einzeln unter
  „Prüfen". Die Zielgruppen fehlen aber zwingend, deshalb der Klappkasten `#wi-drafts-approve` mit
  eigenem Gruppen-Präfix **`bulk`** (`checkedGroups()` sucht global im Dokument, `rev` würde
  kollidieren). Er ist gleichzeitig die Bestätigung – kein zusätzliches `confirm()`.
  Die Aufrufe laufen **sequenziell** (jede Übernahme schreibt Dateien und indiziert).

## Office-Skill: PDF-Export (Fix 2026-07-28)
- **LibreOffice steht jetzt im Manifest** (`system_packages: libreoffice-writer|-calc|-impress`).
  Vorher war es eine undokumentierte Handinstallation: auf DEV vorhanden, auf ECHT **nie** – daher
  „bei dir geht PDF, bei mir nicht". Aktivieren des Skills installiert die Pakete jetzt per apt
  (Root-Broker). **Purge entfernt sie absichtlich NICHT** – LibreOffice ist auch die Office-Suite
  des Desktops.
- **`_find_soffice()`** sucht `soffice`/`libreoffice` in PATH und an den üblichen festen Orten
  (`/usr/lib/libreoffice/program/soffice`, `/opt/libreoffice/program/soffice`, snap). Fehlt es,
  kommt ein **Klartext-Hinweis mit apt-Befehl** statt des rohen
  `[Errno 2] No such file or directory: 'soffice'` – aus dem konnten weder Modell noch Nutzer
  ableiten, was zu tun ist. Der Hinweis sagt ausdrücklich, dass das Office-Dokument selbst erzeugt
  wurde und abrufbar bleibt.
- **`system_packages` wirken NUR beim Einschalten** – deshalb blieb der PDF-Export auf ECHT auch
  nach dem Update tot: der Office-Skill war dort längst aktiv, `enable_skill()` lief also nie
  wieder und die Pakete wurden nie installiert. Der Skill sah dabei völlig gesund aus.
  Gegenmittel (2026-07-28):
  - `SkillManager.missing_for(name)` liefert `{pip, apt, commands}`, `install_missing(name)`
    installiert nach, **ohne den Ein/Aus-Zustand anzufassen**. `GET /api/skills` liefert für
    installierte Skills ein `missing`-Feld (nur wenn wirklich etwas fehlt).
  - `POST /api/skills/{name}/install` ist auf `install_missing()` umgestellt. Der alte Rumpf rief
    `install_dependencies()` – **nur pip, blockierend, ohne apt** – und hätte genau diesen Fall
    nicht gelöst. (`install_dependencies()` existiert noch, ist aber ohne Aufrufer.)
  - Oberfläche: *Einstellungen → Skills* zeigt am Skill die Plakette „Abhängigkeit fehlt"
    (`.sk-badge-missing`) und den Knopf ⤓ (`.sk-btn-fix`) → gleiche Fortschrittsanzeige wie beim
    Einschalten.
  - **`dpkg -s` wird prozessweit gecacht** (`_apt_cache`), weil die Skill-Liste den Zustand jetzt
    bei jedem Aufruf abfragt. `_install_worker` leert den Cache im `finally` – sonst gälten die
    gerade installierten Pakete bis zum Dienst-Neustart weiter als fehlend.
  - **Im getrennten Betrieb sind es ZWEI Schritte:** `_apt_install` geht über den Broker als
    `shell_root`, und das ist per `default_allow=False` **immer erst `pending`**. Also: ⤓ drücken →
    unter *Sicherheit → Root-Freigaben* freigeben → ⤓ **erneut** drücken. Die Log-Zeile sagt das
    jetzt ausdrücklich, sonst wartet der Admin auf etwas, das nie kommt.
- **`_resolve_existing()` löst jetzt auch den ANZEIGENAMEN auf.** Auf Platte heißt die Datei
  `<32-Hex>__<Anzeigename>`, der Erfolgstext von `office_create_word` nennt aber nur
  `IT-Projektangebot.docx`. Genau den gibt das Modell an `office_to_pdf` weiter → bis 2026-07-28
  „Fehler: Datei nicht gefunden". Die Kette Erstellen→PDF war damit über den natürlichen Weg
  unbenutzbar. Nachschlag über `DOCS_DIR.glob("*__<name>")`, bei mehreren Treffern der **jüngste**.

## Telemetrie belastbar gemacht (2026-08-04)
Drei Zusagen, die der Reiter *Einstellungen → Logs & Debug* vorher nicht hielt.

### a) Selbstbereinigung nach 90 Tagen – **Alter ist die EINZIGE Schranke**
Erste Fassung hatte zusätzlich Stückzahl-Schranken (5000 Konversationen, 200 Fehler,
10-MB-Rotation im Audit-Log). Die sind auf Anweisung des Nutzers **wieder entfernt** – und das
war richtig: eine Stückzahl hebelt die Zusage aus. „Diagnosedaten werden 90 Tage vorgehalten"
ist falsch, wenn ein Tag mit viel Verkehr die Einträge von vorgestern verdrängt, und zwar
unsichtbar, genau dann, wenn man sie braucht.
- **Die 10-MB-Rotation im Audit-Log war eine Stückzahl-Schranke in Verkleidung:** bei 10 MB
  wurde nach `.jsonl.bak` umbenannt, und `read_log()` las nur die aktive Datei. Die Einträge
  waren aus der Oberfläche verschwunden, ohne gelöscht zu sein – Sichtbarkeit nach Datenmenge
  statt nach Alter. `read_log()` liest die alte `.bak` jetzt mit, damit vorhandener Bestand
  wieder auftaucht; `prune_older_than()` räumt beide.
- **Ohne Deckel kann jede Datei lang werden – deshalb liest nichts mehr alles ein:**
  `conv_log._iter_index_reversed()` und `audit_log._iter_reversed()` lesen **blockweise von
  hinten** und brechen ab, sobald `limit` Treffer da sind. Die Antwortzeit hängt am Limit, nicht
  an der Historie. Messbar besser als vorher: `/api/logs/retention` 12,6 → **5,9 ms**,
  `/api/conv_log?limit=100` 9,8 → **5,3 ms**.
  - **FALLSTRICK beim Rückwärtslesen:** der erste Teil eines rückwärts gelesenen Blocks ist in
    der Regel eine **angeschnittene Zeile**. Sie muss zurückgehalten und mit dem nächsten – weiter
    vorne liegenden – Block zusammengesetzt werden. Wer das vergisst, verliert je Block eine Zeile
    oder bekommt Bruchstücke. Der Test prüft dasselbe Ergebnis mit `chunk=64` wie mit 256 KB.
  - **Der Filter wirkt WÄHREND des Lesens, nicht danach.** Ein Nachfilter auf den letzten n
    Zeilen meldet „keine Treffer", obwohl weiter hinten welche liegen – derselbe Fehler wie beim
    Wissensgruppen-Filter am 2026-08-02. Test: ein seltener Benutzer wird hinter 120 neueren
    Einträgen gefunden.
  - `get_stats()` (beide Module) zählt nur Zeilenumbrüche und wertet **erste und letzte** Zeile
    aus – O(1) statt O(n) JSON-Arbeit, weil der Wert am Telemetrie-Reiter hängt.
- **Was NICHT als Aufbewahrungs-Schranke zählt und deshalb bleibt:** der Span-Ringpuffer
  (`MAX_SPANS = 1000`) liegt nur im Speicher, trägt keinen Zeitstempel auf Platte und ist nach
  einem Neustart weg – das ist eine Live-Anzeige mit Speicher-Grenze, kein aufbewahrtes Log.
  Ebenso die 100 Dauer-Werte je Tool: eine Stichprobe für Ø/Min/Max. Und die Größen-Notbremsen
  **je Eintrag** in `conv_log` (1 MB/Nachricht, 8 MB/Konversation) begrenzen eine einzelne
  Antwort, nicht die Anzahl der Einträge.
- **Test hält die Abwesenheit fest:** `not hasattr(conv_log, "_MAX_ENTRIES")`,
  `not hasattr(telemetry, "_MAX_ERRORS")`, `not hasattr(audit_log, "_MAX_BYTES")` – plus
  250 Konversationen ohne Verdrängung, 300 Fehler (früher bei 200 gedeckelt), 400 Audit-Zeilen
  in einer Datei ohne `.bak`.
- **`audit_log._bak()` ist eine FUNKTION, keine Konstante.** Als Modulkonstante wäre der Wert
  beim Import an den damaligen `AUDIT_FILE` gebunden; Tests biegen den auf ein Wegwerf-
  Verzeichnis um und hätten weiter auf die echte Datei unter `data/logs/` gezeigt.

### a2) Der Zeitplan (`backend/log_retention.py`)
Vorher wuchsen alle Diagnose-Speicher **nur gegen Stückzahlen, nie gegen Alter**: 200
Konversationen, 200 Fehler, Audit-Rotation erst bei 10 MB. Wie weit der Verlauf zurückreichte,
war damit reine Zufallsgröße – auf DEV waren 200 Konversationen **37,9 Tage**, auf einem stillen
System Jahre, auf einem lauten drei Tage. Eine Frist in TAGEN ist die einzige Größe, die man
einem Betreiber zusagen kann.
- **Ein Zeitplan, drei Speicher:** `run_all()` ruft `conv_log.prune_older_than()`,
  `tracer.prune_errors_older_than()`, `audit_log.prune_older_than()`. Startup-Hook
  `startup_log_retention` (main.py): +60 s nach dem Start, danach täglich. Sofortlauf über
  `POST /api/logs/retention/run`, Status über `GET /api/logs/retention`.
- **Frist über `JARVIS_LOG_RETENTION_DAYS`** (Vorgabe 90, `0` = dauerhaft, Deckel 3650).
  Bewusst **keine** Oberflächen-Einstellung: wie lange Diagnosedaten vorliegen, ist eine
  Betriebsvorgabe – und in manchen Häusern muss ein Audit-Log länger vorgehalten werden.
  `retention_days()` ist eine **Funktion**, keine Modulkonstante (ein beim Import gelesener
  Wert wäre bis zum Neustart eingefroren – dieselbe Begründung wie bei
  `documents.retention_days()`).
- **`run_all()` ist je Speicher fehlerrobust:** ein Aufräumlauf, der beim ersten Problem
  abbricht, lässt genau die Datei stehen, die am dringendsten aufgeräumt werden muss.
- **Eintrag OHNE Zeitstempel bleibt stehen** (Altbestand): ein fehlendes Datum ist kein
  Altersbeweis. Er fällt über die Stückzahl-Schranke heraus, nicht durch Raten.
- **`audit.jsonl.bak` wird mitbereinigt UND mitgelesen** – siehe a) oben.
- **Live auf DEV:** erster Lauf entfernte 11 Telemetrie-Fehler + 61 Audit-Zeilen.

### b) LLM-Verlauf ohne Kürzung – zwei Dateien je Konversation (`backend/conv_log.py`)
Vorher war **jedes** Feld beschnitten: Aufgabe `[:200]`, System-Prompt `[:500]` (und im
Frontend gar nicht angezeigt), jede Nachricht `[:300]`. Auf DEV waren **19 von 200** Aufgaben
abgeschnitten. Für eine Fehlersuche ist ein halber Prompt schlimmer als kein Prompt: man sucht
den Fehler in der Antwort, obwohl er in der abgeschnittenen Frage stand.
- **Das Kürzen hatte einen Grund, und der gilt weiter:** die Datei wurde bei JEDER
  Konversation komplett gelesen und komplett neu geschrieben. Ein einzelnes Tool-Ergebnis
  erreichte auf DEV **1,28 MB** (p50 750 B, p90 11 KB, p99 25 KB) – unbeschnitten *und*
  monolithisch geht nicht. Deshalb getrennt:
  - `data/logs/conv/index.jsonl` – eine Zeile je Konversation, nur Kopfdaten + die
    **vollständige Aufgabe**. Wird nur ANGEHÄNGT, das Schreiben kostet unabhängig von der
    Historie immer gleich viel. Die Liste in der Oberfläche kommt allein hieraus.
  - `data/logs/conv/<id>.json` – der vollständige Rumpf (System-Prompt + alle Nachrichten).
    Einmal geschrieben, gelesen nur beim Aufklappen (`GET /api/conv_log/{id}`).
- **Erst der Rumpf, dann die Index-Zeile.** Umgekehrt bliebe bei einem Absturz ein Eintrag
  zurück, der beim Aufklappen leer ist. Verwaiste Rümpfe (Absturz *zwischen* beiden) räumt
  `prune_older_than()` mit auf – sonst würde die niemand je entfernen.
- **Die Zusage lautet: PROMPTS werden nie gekürzt.** Aufgabe, System-Prompt und Nachrichten
  der Rollen `user`/`system` (`_NEVER_TRUNCATE`) haben **keine** Grenze. Andere Rollen
  (Tool-Ergebnisse, Modell-Antworten) haben mit `_MAX_MSG_CHARS` (1 MB) und `_MAX_BODY_CHARS`
  (8 MB) Notbremsen, die um Größenordnungen über dem p99 liegen und praktisch nie greifen.
  - **`_prepare_messages()` zieht die Prompts ZUERST vom Rumpf-Budget ab.** Sonst könnte ein
    großes Tool-Ergebnis *vor* dem Prompt das Budget aufbrauchen und die unkürzbare Frage
    hätte keinen Platz mehr. Test „Prompt nach großem Tool-Ergebnis vollständig".
  - **Greift eine Bremse, steht es AUSDRÜCKLICH im Eintrag** (`truncated` + `full_len`, in der
    Oberfläche „[gekürzt: 1234.6k Zeichen]"). Der alten Fassung fehlte genau das: ein „…" am
    Ende war der einzige Hinweis, und der sah nach Satzende aus.
- **`_new_id()` = Millisekunden + Zähler.** Zwei Konversationen können in derselben
  Millisekunde enden (Parallelbetrieb); eine doppelte Id würde den Rumpf der einen mit dem der
  anderen überschreiben.
- **Migration ist automatisch und einmalig** (`_migrate_once()`, lazy beim ersten Zugriff):
  `data/conv_log.json` → neue Ablage, Quelldatei wird zu `conv_log.json.migrated`
  **umbenannt, nicht gelöscht**. Alt-Einträge tragen `legacy: true` und ein Abzeichen
  „gekürzt (Altbestand)" – ihre Texte SIND gekürzt und lassen sich nicht vervollständigen; ohne
  den Hinweis hielte man sie für vollständig.
  - **FALLSTRICK:** der Alt-Rumpf hat **kein `task`-Feld** (die Aufgabe stand nur im Index).
    `_renderConvBody(d, idx)` fällt deshalb auf den Index zurück – sonst fehlte die Aufgabe in
    der aufgeklappten Ansicht genau bei den Einträgen, bei denen sie ohnehin gekürzt ist.
- **Oberfläche:** die Kopfzeile zeigt die Aufgabe per CSS-Ellipse, der aufgeklappte Bereich den
  **vollen** Text plus Zeichenzahl; der System-Prompt steht darunter **eingeklappt** (er hat
  gut 33.000 Zeichen und machte jeden Eintrag sonst unlesbar). Rümpfe werden je Id
  zwischengespeichert (`_convBodies`), Zu- und Aufklappen ruft nicht erneut ab.
- **Es gibt keine Stückzahl-Schranke** (siehe a) – der Index wird nur nach Alter gekürzt.
- **Beschädigte Index-Zeile wird übersprungen**, nicht als Fehler behandelt: eine halb
  geschriebene Zeile darf nicht den ganzen Verlauf unlesbar machen. `_write_index()` schreibt
  atomar über `os.replace`.

### c) Alle fünf Statistiken/Logs einzeln leerbar
Vorher gab es genau EINEN Knopf „Zurücksetzen" für alles. Wer die Tool-Zeiten nach einer
Optimierung frisch messen wollte, verlor dabei das Fehler-Log – also genau die Daten, die man
nach einer Änderung braucht.
| Abschnitt | Endpunkt |
|---|---|
| Tool-Statistiken | `DELETE /api/telemetry/tool_stats` |
| LLM-Statistiken | `DELETE /api/telemetry/llm_stats` |
| Fehler-Log | `DELETE /api/telemetry/errors` |
| Letzte Spans | `DELETE /api/telemetry/spans` |
| LLM-Verlauf | `DELETE /api/conv_log` (bestand schon) |
- **Was NICHT mitgelöscht wird:** `agent_runs`, `total_duration_ms`. Die gehören zu keinem der
  Abschnitte und verschwinden nur beim vollständigen Zurücksetzen – sonst würde das Leeren der
  Tool-Tabelle stillschweigend auch die Stat-Karten oben verändern. Umgekehrt nullt
  `clear_errors()` den `errors`-**Zähler** mit: eine Karte „7 Fehler" über einem leeren
  Fehler-Log sieht wie ein Fehler der Oberfläche aus.
- **Nachweis je Bereich** (`_area_resets`, überlebt Neustart): unter dem Abschnitt steht
  „↺ Zuletzt geleert: … von …" – **auch im Leerzustand**. Ohne den Hinweis ist „0" nicht von
  „noch nichts passiert" zu unterscheiden; genau dafür gab es den globalen Nachweis schon.
  Ein vollständiges Zurücksetzen **verwirft** die Bereichs-Nachweise (ein älterer Hinweis
  daneben wäre irreführend).
- **FALLSTRICK – das × sitzt IN der klickbaren Kopfzeile.** Ohne
  `onclick="event.stopPropagation()"` am umgebenden `<span>` klappt derselbe Klick den
  Abschnitt auf/zu. Gleiches Muster wie bei LLM-Verlauf/Audit-Log. Der UI-Test prüft für jeden
  der fünf Knöpfe: genau ein DELETE auf den **eigenen** Endpunkt UND `display` unverändert.
- **Spans liegen nur im Speicher** – nach einem Neustart sind sie ohnehin weg. Der Knopf ist
  trotzdem sinnvoll: er schafft einen definierten Nullpunkt für eine Messung, ohne den Dienst
  anzufassen.
- Nebenbefund, mitbehoben: die Kopfzeilen von Tool- und LLM-Statistiken riefen beim Aufklappen
  `_loadSpans()` statt `_loadStats()` (Kopierfehler, folgenlos weil beide Abschnitte offen
  starten) – jetzt richtig.

## Vollständige Endpunkt-Rechte-Durchsicht (2026-08-04)
Auslöser war der Telemetrie-Befund unten. Auf Anweisung des Nutzers wurden danach **alle 342
Routen** in `main.py` systematisch geprüft (Route → Dependency → tatsächliche Rückgabe →
Frontend-Aufrufer). Ergebnis: **63 Endpunkte** hingen an `require_auth`, obwohl sie
Administratoren-Material liefern oder Administratoren-Aktionen ausführen. Alle korrigiert.
Wächter: `tests/test_endpoint_rights.py` (105 Prüfungen).

**Die vier Muster – wichtiger als die Einzelfälle:**
1. **Lesen war freier als Schreiben.** Das macht den Fehler beim Überfliegen unsichtbar, weil
   der schreibende Endpunkt daneben korrekt aussieht. Drei Vorkommen: Skill-Config (2026-08-02),
   `/api/knowledge/pending` (PATCH/approve = Editor, GET = jeder), Telemetrie.
2. **Die Oberfläche war die einzige Schranke.** Desktop-Knopf und Update-Pille im Portal
   erscheinen nur unter `if (d.is_admin)` – die Endpunkte dahinter standen jedem offen. Eine
   clientseitige Sichtbarkeit ist keine Berechtigung (steht so schon bei der Kontext-API).
3. **Fremde Zugangsdaten als Vollmacht.** `/api/jira/*`, `/api/confluence/*`,
   `/api/kundenverwaltung/*` fragen mit den **Server**-Zugangsdaten ab und umgehen damit die
   Rechte des Benutzers im Zielsystem vollständig.
4. **Verbindungstests sind SSRF-Werkzeuge.** `/api/profiles/test`, `/api/profiles/models`,
   `/api/auth/ad_test` nehmen das **Ziel aus dem Request** und melden, ob es erreichbar war –
   ein Portscanner aus dem Inneren des Netzes, für jeden angemeldeten Benutzer.

**Der schwerste Einzelfall: `POST /api/instructions/{name}`.** `data/instructions/*.md` wird von
`agent.py::load_instructions()` an den System-Prompt **jedes** Laufs angehängt – auch an den
eines Admins. Genau deshalb steht `reflection` in `_BLOCKED_TOOLS_FOR_LDAP` („schreibt
data/instructions/*.md → fließt in JEDEN System-Prompt"). Der Werkzeug-Weg war gesperrt, der
HTTP-Weg daneben stand jedem Domänen-Benutzer offen – GET, POST **und** DELETE. Das ist genau
die dauerhafte Rechteerhöhung, gegen die die Sperrliste gebaut wurde.

**Weitere Befunde, gruppiert:**
| Gruppe | Was möglich war |
|---|---|
| WhatsApp | `GET /qr` = fremdes Telefon an die Bridge koppeln; `logout`/`reconnect` = Integration abschalten; `logs`/`bridge-logs` (GET+DELETE) = Nachrichtentexte lesen und löschen |
| Vision | `events` = wer wann erkannt wurde (biometrisch); `cleanup` = **gesamte Gesichts-DB löschen**; `control`/`training`/`profiles`/`profile DELETE`; dazu die Medien `snapshot`/`face-crop`/`preview`/`thumbnail`/`greet-audio` (Gesichtsbilder) |
| Google | `revoke` = dem ganzen System den Zugriff entziehen; `gog-setup` = OAuth-Zugangsdaten schreiben |
| Wissen | `GET /api/knowledge/pending[/{id}]` = **alle** unfreigegebenen Extraktions-Entwürfe im Volltext (die /wissen-Variante filtert korrekt auf die eigenen); `GET /api/knowledge/learned` = Titel + Vorschau der Lern-Notizen, abgeleitet aus fremden Gesprächen |
| System | `POST /api/vnc/unlock` = Desktop-Sperre aufheben; `ad_status` = DC-Name, Freigabe- und Admin-Listen; `settings/ssl`; `update/status|settings`; `mcp/servers`; `openclaw/*` |

**Zwei Fallen, in die ich beim Korrigieren selbst gelaufen bin** – beide vom Wächter gefangen:
- **`require_knowledge_editor` hätte Admins ausgesperrt.** `_may_edit_knowledge()` gibt bei
  LEERER Editoren-Konfiguration für **jeden** `False` zurück, ausdrücklich auch für lokale
  Admins (bewusst so). Der Wissens-Reiter unter /settings wäre auf einem frisch installierten
  System für niemanden lesbar gewesen. Deshalb neu: **`require_admin_or_knowledge_editor`**.
  Merkregel: eine Sperre, die den Administrator aus seiner eigenen Oberfläche aussperrt, ist
  schlimmer als die Lücke, die sie schließt.
- **Die Vision-Medien brauchen `?token=`** (`<img src>` kann keinen Header setzen) – sie standen
  daher auf `require_auth_or_query`. Richtig ist das **schon vorhandene**
  `require_admin_or_query` (Admin **und** Query-Token). Genau diese fünf hat der
  Namensraum-Wächter beim ersten Lauf gefunden, nachdem ich sie beim ersten Durchgang übersehen
  hatte.

**Bewusst NICHT geändert** (mit Begründung, damit es niemand „nachbessert"):
- `/api/settings` und `/api/profiles` (GET) geben Schlüssel **maskiert** heraus (`_mask_key`) –
  ein eigener Test hält das fest. Die Asymmetrie zu POST (Admin) ist damit in Ordnung.
- `/api/branding/logo|portal-video` (GET, ohne Anmeldung) müssen **vor** dem Login sichtbar sein.
- `/api/knowledge/groups|assignments|files|stats|content_search` – von `chat.html`,
  `support.html` und `wissen.html` für Gruppenfilter und die Editor-Matrix gebraucht; Schreiben
  ist längst über `_can_edit_kb_group`/`_may_edit_knowledge` gesichert. **Offener Restpunkt:**
  `content_search` und `files` liefern Datei**pfade** ohne Gruppenfilter – kein Inhalt, aber ein
  Namens-/Existenz-Orakel. Eine Korrektur bräuchte ein Gruppenfilter-Konzept für diese Reads,
  keine Admin-Sperre (die bräche das Wissensportal für Gruppen-Editoren).
- `/api/skills` – `branding.js` braucht es auf **jeder** Seite. Enthält keine Zugangsdaten (die
  liegen hinter `/api/skills/{n}/config`, seit 2026-08-02 Admin).
- `/api/cron`, `/api/watchers` – prüfen intern `_require_trigger_admin` (2026-07-29).
- Endpunkte ganz ohne Dependency (40) haben durchweg eine eigene Prüfung im Rumpf:
  Capability-URL (`/api/generated/{name}`), Stream-Key (`/api/vision/stream`), localhost-Zwang
  (`/api/whatsapp/incoming`), Agent-API-Key (`/api/agent/task`), Token im WS-`auth`-Rahmen.
  Die Seiten-Routen (`/chat`, `/settings`, …) sind leere Hüllen.

**Der Wächter prüft drei Dinge – die Liste ist nur eines davon:**
1. Namentliche Muss-Liste (63 Endpunkte + Telemetrie).
2. **Namensraum-Wächter:** jede Route unter `/api/telemetry|conv_log|audit_log|logs/|
   instructions|whatsapp/|vision/|google/|confluence/|jira/|kundenverwaltung/|mcp/|openclaw/|
   broker/` muss auf Admin-Ebene liegen. Damit fällt auch eine **künftige** Route auf, ohne dass
   jemand die Liste pflegt. Ausnahmen sind einzeln aufgeführt und begründet, keine Sammelfreigabe.
3. **Regel „Lesen nicht freier als Schreiben":** für jeden Pfad mit Schreibmethode wird geprüft,
   ob ein GET darauf schwächer geschützt ist. Das ist Muster 1 als Test.
4. **Gegenprobe in die andere Richtung:** 19 Endpunkte, die für normale Benutzer erreichbar
   **bleiben müssen** (`/api/me`, `/api/chat/sessions`, `/api/wissen/*`, …). Ohne diese Hälfte
   wäre der Test durch „alles auf Admin" trivial erfüllbar – und die Anwendung kaputt.

**Verifiziert auf DEV, und dabei ein untauglicher Testaufbau korrigiert:** Der erste Live-Test
nutzte `nexus\andrea.ladd` – der Benutzer steht auf DEV nicht in `ad_allowed_users`, bekommt
also bei **jedem** Endpunkt 403 (`NOT_AUTHORIZED`). Damit beweist ein 403 nichts über die
Admin-Schranke. Wiederholt mit `jonas.reichelt` (login-freigegeben, **kein** Admin): 23 gesperrte
Endpunkte je 200 (Admin) / **403 mit der Admin-Meldung** (Nicht-Admin) / 401 (ohne Token), der
Eskalationsversuch `POST /api/instructions/boeswillig` → 403 und **keine Datei angelegt**; dazu
22 normale Endpunkte für den Nicht-Admin weiterhin 200 und 10 Admin-Reiter-Datenquellen 200.
**Merkregel: ein Rechte-Test mit einem Benutzer, der gar nicht anmeldeberechtigt ist, ist grün
aus dem falschen Grund.**

### Rechte: die Telemetrie war für JEDEN angemeldeten Benutzer lesbar
Alle Endpunkte hingen an `require_auth`. Ein Domänen-Benutzer konnte damit den **LLM-Verlauf
sämtlicher Benutzer** abrufen (Aufgaben, Modell, IP, Nachrichten), das **Tool-Audit-Log** aller
Benutzer lesen und beides löschen. Mit vollständigen Prompts (b) wäre daraus eine echte
Datenpreisgabe geworden – ein Prompt enthält regelmäßig genau die Inhalte, um die es geht.
Jetzt `require_local_auth` für **alle** `/api/telemetry/*`, `/api/conv_log/*`,
`/api/audit_log`, `/api/logs/retention*`. Der Zuschnitt ist unkritisch: der Reiter liegt
ausschließlich auf `settings.html`, und die ist Administratoren vorbehalten (gleiche Lage wie
bei den Skill-Zugangsdaten am 2026-08-02). Live auf DEV: Admin 200, Domänen-Benutzer **403 mit
der Admin-Meldung**, ohne Token 401.
- **FALLSTRICK Routen-Reihenfolge:** `GET /api/conv_log/{conv_id}` muss **nach**
  `/api/conv_log/ips` und `/api/conv_log/users` registriert sein – FastAPI prüft in
  Registrierungsreihenfolge, sonst fängt die Sammelroute deren Pfade ab und die Filter im
  Verlauf bleiben leer, ohne dass ein Fehler sichtbar wird. Ein Test hält die Reihenfolge fest.
- Unbekannte Id → **404**, nicht 403.

### Verifiziert
- **177 Backend-Prüfungen** (`tests/test_log_retention.py`, ohne fastapi lauffähig): Alterung
  je Speicher, verwaiste Rümpfe, beschädigte Zeilen, Frist-Auflösung inkl. Tippfehlern,
  fehlerrobustes `run_all()`, Vollständigkeit der Prompts, Notbremsen + Ausweisung,
  Budget-Reihenfolge, Id-Eindeutigkeit, Pfad-Entschärfung, Selektivität aller fünf Clears,
  Migration, Stückzahl-Schranke, Endpunkt-/Rechte-/Reihenfolge-Prüfung am Quelltext.
  - **Der Test hat eine Sandkasten-Schranke, und die war nötig:** bei der Gegenprobe gegen den
    alten Modulstand (`git stash`) heißen die Pfadvariablen anders (`_LOG_FILE` statt
    `_INDEX`/`_OLD_FILE`), die Umbiegung greift dann nicht und der Test schrieb Testinhalte in
    das **echte** `data/conv_log.json`. Jetzt prüft der Test jedes `Path`-Attribut der drei
    Module und bricht mit Exit 2 ab, wenn eines aus dem Wegwerf-Verzeichnis herauszeigt.
    `data/conv_log.json*` + die beiden `telemetry_*.json` stehen zusätzlich in `.gitignore`.
- **Laufzeiten auf DEV** (200 Konversationen, 1516 Audit-Zeilen): `GET /api/logs/retention`
  5,9 ms · `GET /api/conv_log?limit=100` 5,3 ms / 30 KB · `GET /api/audit_log?limit=200` 5,8 ms
  · Rumpf-Abruf 4,4 ms. Die Liste ist
  klein geblieben, obwohl die Inhalte jetzt vollständig sind – genau das war der Zweck der
  getrennten Ablage. `GET /api/logs/retention` liest den Audit-Bestand und stat()et alle
  Rumpfdateien; das ist vertretbar, weil der Reiter **nicht pollt** (nur Öffnen + Knopf).
- **40 UI-Prüfungen** (`tests/test_telemetry_ui.js`, jsdom gegen die echten Dateien):
  Rumpf erst beim Aufklappen und nur einmal, vollständiger Prompt im DOM, System-Prompt
  eingeklappt + Umschalter, Kürzungs-Hinweis, Alt-Eintrag mit Index-Rückfall, alle fünf
  Leeren-Knöpfe (eigener Endpunkt, kein Umklappen), Bereichs-Nachweis, `init()` idempotent.
  **jsdom läuft nur lokal** – auf DEV ist es nicht installiert.
- **Gegenproben:** der alte Stand kürzt einen 5012-Zeichen-Prompt nachweislich auf 200
  (Aufgabe) / 301 (Nachricht) / 500 (System-Prompt); der UI-Test scheitert am alten Stand
  sofort (die Knöpfe existieren nicht).
- **Live auf DEV:** Migration der 200 echten Einträge, erster Retention-Lauf (72 Einträge),
  Probe-Konversation mit 8232-Zeichen-Aufgabe + 33.337-Zeichen-System-Prompt über den echten
  Schreibpfad **unverkürzt** wieder ausgelesen, alle vier granularen Clears mit belegter
  Selektivität, Verlauf leeren (201 → 0 inkl. Rumpfdateien) und aus der Sicherung
  wiederhergestellt. Dienst aktiv, `/settings` HTTP 200.

## Instruktionen sind nicht mehr git-verfolgt (2026-08-04)
`data/instructions/` steht in `.gitignore`; die Vorgabe-Fassungen liegen versioniert unter
**`data/instructions_default/`** und werden von `agent.py::_seed_instructions()` beim ERSTEN
Start kopiert.
- **Warum:** Diese Dateien werden pro Server gepflegt (Oberfläche bzw. `reflection`-Werkzeug)
  und weichen absichtlich voneinander ab – auf ECHT sind sie auf „Nexerius" umbenannt und um
  SAP erweitert. Solange sie verfolgt waren, machte der Update-Pill (stash → pull → pop) aus
  ihnen bei jedem Pull einen Merge-Konflikt; am 2026-07-13 blockierte genau das auf ECHT jedes
  weitere Update (Konfliktmarker in den Dateien).
- **Der bisherige Gegenzug ist WIRKUNGSLOS und war es unbemerkt:** `git update-index
  --skip-worktree` (eingerichtet 2026-07-13) greift auf ECHT nicht mehr – `git ls-files -v`
  zeigt `H` statt `S`, erneutes Setzen bleibt ohne Effekt (Exit 0, Bit ungesetzt, auch bei
  unveränderten Dateien). Ursache: **`core.sparseCheckout = true`** seit 2026-07-31
  (`deploy/sparse_checkout.sh`) – sparse-checkout verwaltet das skip-worktree-Bit selbst.
  **Zwei dokumentierte Schutzmaßnahmen schlossen sich gegenseitig aus.** Merkregel: ein Schutz,
  der still ausfällt, ist kein Schutz – deshalb jetzt der Weg über `.gitignore`.
- **`_seed_instructions()` säet NUR, wenn keine einzige `.md` vorhanden ist** – nicht pro
  fehlender Datei. Auf gepflegten Systemen sind einzelne Vorgaben absichtlich gelöscht (ECHT:
  `browser_automation.md`, `user.md`); ein Auffüllen einzelner Dateien holte sie bei jedem Start
  zurück und machte aus einer Entscheidung einen wiederkehrenden Fehler. `beispiel.md.disabled`
  zählt dabei NICHT als vorhandene Instruktion (Endung ist nicht `.md`).
- Fehlschlag beim Säen ist **kein Startfehler** – der Agent läuft dann ohne Zusatz-Anweisungen.
- **Beim Ausrollen auf einen Server, der die Dateien noch verfolgt:** vorher dort
  `git rm --cached data/instructions` + lokaler Commit, sonst bricht der Pull mit „local changes
  would be overwritten" ab (die Server-Fassungen sind modifiziert).

## Wissensgruppen: Editoren-Felder nicht mehr für jeden lesbar (2026-08-04)
`GET /api/knowledge/groups` muss für **jeden** angemeldeten Benutzer erreichbar bleiben – /chat
und /support brauchen es für das Gruppen-Filter-Pulldown. Es lieferte aber auch
`editors_users`/`editors_group` mit, also **AD-Kontonamen und Gruppen-DNs aus der
Rechtekonfiguration** (auf DEV z.B. `'nxIS' editors_users='Peter.Sachs, marita.muscholl'`).
Das Pulldown braucht davon nichts (nur `id`/`name`/`color`/`count`).
- `main.py::_kb_strip_editor_fields()` entfernt die beiden Felder – **pro Gruppe**, nicht
  pauschal: ein gruppenspezifischer Editor pflegt die Editoren SEINER Gruppe im Wissensportal;
  global entfernt wäre das Formular dort leer und ein Speichern löschte die Einträge.
  Admins und globale Wissens-Editoren sehen alles. Fail-closed bei Fehlern.
- **Nicht geändert wurde der Rest der Wissens-Reads** (`content_search`, `files`, `assignments`,
  `groups/ungrouped`): Wissensgruppen sind in diesem System **keine Leseschranke**. `_kb_groups`
  ist ausdrücklich ein *vom Benutzer gewählter* Filter (`None`/fehlt = alle Gruppen), nirgends
  gegen Rechte validiert – jeder angemeldete Benutzer kann den Volltext aller Gruppen per Chat
  abrufen. Eine Pfadliste verrät also nichts, was nicht schon offen liegt; ein Filter nur auf
  den Listen wäre eine Fassade. Bewusste Entscheidung des Nutzers am 2026-08-04.
  (Inkonsistenz zum Kenntnisnehmen: `/api/wissen/file` beschränkt den Datei-**Download** sehr
  wohl auf den Bereich des Nutzers.)

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

## Transkription protokolliert nicht mehr ins WhatsApp-Log (Fix 2026-07-30)
**Der Befund:** Auf einem System **ohne installierten WhatsApp-Skill** entstand
`data/logs/whatsapp.log`, gefüllt mit `{"cat": "transcription", "msg": "Lade Whisper-Modell
'small'..."}`. Kein Fehlverhalten der Transkription – ein falsch benanntes Log.
- **Ursache:** `_get_whisper_model` und `_transcribe_audio` stehen im WhatsApp-Abschnitt von
  `main.py` und protokollierten über `wa_log`. Sie sind aber **geteilte Infrastruktur** mit
  VIER Aufrufern, von denen nur EINER WhatsApp ist:
  | Quelle | Auslöser |
  |---|---|
  | `whatsapp` | Sprachnachricht über die Bridge (der einzige echte WhatsApp-Fall) |
  | `voice` | `[Voice]`-Aufgabe des Windows-/Desktop-Clients im WS-`task` |
  | `attachment` | Audio-/Video-Anhang im Chat |
  | `transcribe_only` | Windows-App mit abgeschaltetem AutoSend |
  | `wakeword` | Wake-Word-Prüfung (nutzt nur `_get_whisper_model`) |
- **Fix:** `_tr_log(level, msg, meta, source)` als einzige Log-Stelle der Transkription. Ins
  **Journal** geht es immer (`[Transkription/<quelle>]`), ins **WhatsApp-Log nur bei
  `source="whatsapp"`**. `_transcribe_audio(..., source=...)` reicht die Quelle an
  `_get_whisper_model` weiter. **Vorgabe ist `chat`, also NICHT das WhatsApp-Log** – wer einen
  neuen Aufrufer ergänzt und die Quelle vergisst, verschmutzt kein fremdes Log (fail-safe).
- **Der volle Transkript-Text bleibt an `wa_log`+`debug_only` gebunden** und wird für fremde
  Quellen NICHT ins Journal geschrieben: dort stünden sonst komplette Diktate im Klartext.
- **Die Transkription hängt NICHT am WhatsApp-Skill** – nur ihre Feineinstellung liegt dort
  (`whisper_model` aus der Skill-Config). Ohne Skill liefert `get_skill_config` ein leeres dict
  (kein Fehler), es gilt `small`. Wer das entkoppeln will, braucht eine globale Einstellung.
- **Das bestehende `whatsapp.log` verschwindet nicht von selbst** – der Fix verhindert nur neue
  Einträge. Aufräumen über *Einstellungen → WhatsApp → Logs löschen* bzw. Datei entfernen.
- **Verifiziert auf DEV:** 34 Prüfungen (Weiche je Quelle, ganzer Lauf mit Stub-Modell für Erfolg/
  keine-Sprache/kein-Modell, Modellname ohne Skill, Quelltext-Prüfung aller Aufrufstellen).
  **FALLSTRICK im Test:** Aufrufe gehen über zwei Zeilen – eine zeilenweise Suche findet das
  Argument auf der Fortsetzungszeile nicht und meldet fälschlich „keine Quelle übergeben".

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

## Ladezeit /settings: 9× dieselbe Abfrage (Fix 2026-07-28)
Die Einstellungsseite brauchte **~10 Sekunden** bis zur Anzeige. Der Weg zur Ursache ist
lehrreich, weil zwei naheliegende Verdaechtige falsch waren:
- **NICHT der LLM-Erreichbarkeitstest** (die erste Vermutung): `/api/llm/active-status`
  wird von `/settings` gar nicht aufgerufen – nur von /chat, /portal, /support,
  /userchat, /wissen – und kostet auf ECHT 12 ms.
- **NICHT die externe Schriftquelle:** `settings.html` hatte als EINZIGE Seite ein
  render-blockierendes `<link>` auf `fonts.googleapis.com`. Das war eine plausible
  Erklaerung (nur diese Seite betroffen, ~10 s ist ein typischer Verbindungs-Timeout),
  aber nach dem Entfernen blieb die Seite genauso langsam. Die Einbindung ist trotzdem
  raus – in einer internen Admin-Oberflaeche hat ein Abruf zu Google nichts zu suchen,
  und `--font-body` faellt ohnehin auf Systemschriften zurueck. **Nie wieder extern
  einbinden**; wer Inter zwingend will, liefert WOFF2 selbst aus.
- **Die Ursache:** `openModal()` ruft NEUN Sichtbarkeits-Funktionen **hintereinander**
  (`await … await …`), und jede holte sich `/api/skills` selbst – bei 0,77 s je Abruf
  rund 7 Sekunden. Zwei Fixes:
  1. **`list_skills()` 788 ms → 71 ms:** `_missing_dependencies()` rief
     `_installed_packages()` (45 ms, laeuft alle Distributionen durch) einmal PRO SKILL
     → bei 25 Skills 1,05 s. Jetzt wird die Menge einmal pro Aufruf berechnet und
     durchgereicht (`installed`-Parameter, lazy). Das war eine Regression vom selben
     Tag: vorher gab es den `missing`-Block in `list_skills()` gar nicht.
  2. **9 Abrufe → 1:** `_skillsOnce()` in app.js (TTL 5 s + Bündelung paralleler
     Aufrufer). `skills.js::loadSkills()` ruft `window.invalidateSkillsCache()`, damit
     nach einem Skill-Toggle die Reiter-Sichtbarkeit sofort stimmt und nicht bis zu
     5 s alt ist.
- **Merkregel:** erst messen, wo die Zeit liegt – Endpunkte EINZELN, statische Dateien,
  HTML von aussen, und dann zaehlen, **wie oft** die Seite denselben Endpunkt aufruft.
  Ein einzelner Endpunkt mit 0,77 s sieht harmlos aus; neunmal in Serie sind es 7 s.

## Konventionen
- **Git:** `git commit` und `git push` NUR auf ausdrückliches Kommando des Nutzers (`c+p`) –
  niemals aus eigenem Antrieb, auch nicht wenn eine Aufgabe fertig und getestet ist. Fertige
  Änderungen bleiben im Arbeitsbaum liegen. Der DEV-Deploy zum Testen (`scp` nach
  `/opt/jarvis` + `systemctl restart`) ist davon unberührt und läuft ohne Rückfrage.
- **Sprache:** Code-Kommentare und Commit-Messages auf Deutsch
- **CSS:** Verwende `var(--text-primary)`, `var(--bg-glass)` etc. aus `:root` – keine hardcoded Farben
- **Frontend:** Kein Build-System, keine Frameworks – reines Vanilla JS
- **Secrets:** `.env` Datei, NICHT in Code committen
- **numpy:** Muss < 2.1 bleiben (VM hat kein SSE4.2 / X86_V2)

## Update scheitert an Eigentuemerschaft (Vorfall + Fix 2026-07-31)
**Der Vorfall:** Auf ECHT brach der Update ab mit
`unable to unlink old 'tests/test_portal_sessions_ui.js': Keine Berechtigung` und
`cannot create directory at 'tests/tools': Keine Berechtigung`.
- **Ursache:** `/opt/jarvis/tests` gehoerte **root**, alles andere `jarvis`. Zum ERSETZEN
  einer Datei oder ANLEGEN eines Verzeichnisses braucht git Schreibrecht auf dem
  **uebergeordneten Verzeichnis**, nicht auf der Datei. Ein einziges fremdes Verzeichnis
  legt damit jeden Update lahm, der darin etwas aendert – und zwar erst dann, oft Monate
  nachdem es entstanden ist (hier durch einen frueheren `git pull`/`scp` als root).
  Dazu 34 weitere root-eigene Dateien und 36 in `.git`.
- **Der abgebrochene Pull hinterlaesst einen Teilstand:** fuenf Dateien waren schon
  geschrieben. **Vor dem Aufraeumen jede gegen `HEAD` UND `origin/master` pruefen**
  (`git show origin/master:<datei> | md5sum`): war sie identisch mit origin/master, ist es
  Pull-Rueckstand und darf zurueckgesetzt werden; weicht sie von beidem ab, ist es
  Server-Handarbeit und muss bleiben. Blind `git checkout --` waere Datenverlust.
- **Reparatur:** `chown -R jarvis:jarvis /opt/jarvis`, dann Pull **als Dienstbenutzer**
  (`runuser -u jarvis -- git pull origin master`). Die Modi auf `data/chats|documents|logs`
  setzt `harden_data_dirs()` beim Start selbst wieder auf 0750 – nicht von Hand nachziehen.
- **Vorbeugung 1 – `start_jarvis_root.sh` Schritt 6b:** zieht bei jedem Boot die
  Eigentuemerschaft gerade (nur wenn wirklich etwas abweicht, sonst kostet ein `chown -R`
  ueber zehntausende Dateien Startzeit). Steht dort, weil der Root-Bootstrap ohnehin als
  root laeuft – **eine neue Broker-Op waere der falsche Weg**, die verlangt zusaetzlich
  einen Broker-Neustart auf jedem Server (sonst 502 „unbekannte Op").
- **Vorbeugung 2 – `update_manager.diagnose_permissions()`:** haengt bei Rechtefehlern eine
  Klartext-Erklaerung samt fertigem `chown`-Befehl an die Git-Meldung.
  - **Die Marker sind die ENGLISCHEN Git-Fragmente** (`unable to unlink`,
    `cannot create directory`): Git uebersetzt diese Meldungen nicht, wohl aber die
    errno-Beschreibung dahinter (auf ECHT „Keine Berechtigung"). Wer nur auf den
    uebersetzten Teil prueft, findet den Fall genau auf dem System nicht, auf dem er auftritt.
  - Geprueft wird ueber `git ls-files` + `os.lstat`, **nicht** per Verzeichnis-Durchlauf:
    `PROJECT_ROOT` enthaelt `venv/` mit ~100.000 Dateien, die git nie anfasst.
  - **ALS ROOT MELDET SIE NICHTS** – root umgeht die Rechtepruefung, dort gibt es das
    Problem nicht. Ohne diese Schranke schlug die Funktion aus einer Root-Shell heraus
    `chown -R root:root /opt/jarvis` vor und haette dem Dienstbenutzer das Verzeichnis
    entzogen. Beim Ausrollen auf DEV genau so passiert und dort behoben.
  - Fail-safe: schlaegt die Diagnose selbst fehl, bleibt die Original-Meldung stehen.
- **Vorbeugung 3 – `deploy/sparse_checkout.sh` (nur PRODUKTION):** blendet `tests/`,
  `android/` und `windows-app-go/` aus dem Checkout aus. Auf ECHT aktiv.
  - **`--no-cone` ist Absicht:** der Cone-Modus kennt nur EINSCHLIESSEN, man muesste alle
    uebrigen Verzeichnisse aufzaehlen – ein spaeter hinzukommendes fehlte dann **still**.
    Mit `/*` + Negationen ist die Vorgabe „alles". Nachgewiesen: ein Pull mit neuem
    Top-Level-Verzeichnis bringt es mit, waehrend `tests/` draussen bleibt.
  - **NICHT auf DEV** – dort laufen die Tests. Das Skript fragt nach, wenn es eine
    git-Identitaet findet (Indiz fuer eine Entwicklungsmaschine).
  - Als **Dienstbenutzer** ausfuehren, nicht als root: sonst entstehen in `.git` wieder
    root-eigene Dateien und man baut genau den Fehler nach, den man behebt.
- **Merkregel:** Wer auf einem Server mit unprivilegiertem Backend `sudo`/`scp als root`
  benutzt, erzeugt eine Zeitbombe, die erst beim naechsten Commit auf dasselbe Verzeichnis
  hochgeht. Deploys gehoeren dem Dienstbenutzer (`install -o jarvis -g jarvis …`).

## Bekannte Fallstricke
- **NIEMALS Write-Tool auf bestehende Dateien:** Das Write-Tool ueberschreibt Dateien vollstaendig – bei Fehlern entstehen 0-Byte-Dateien. Fuer bestehende Dateien (z.B. index.html, main.py, etc.) IMMER nur das Edit-Tool verwenden. Write nur fuer NEUE Dateien!
- **Deadlock in wa_logger.py:** `clear_logs()` darf `log()` nur NACH Lock-Release aufrufen
- **Synchrone Bridge-Requests:** Blockieren den asyncio Event-Loop → Server friert ein. Immer `_wa_bridge_async()` verwenden
- **Self-Chat Feedback-Loop:** Bridge trackt gesendete Message-IDs in `sentByBridge` Set
- **jsdom-Tests beenden sich NICHT von selbst:** Laedt der Test eine echte Seite, laufen
  deren Dauer-Abfragen weiter (`setInterval` fuer LLM-Status/CPU in wissen.js, Poll-Timer
  in anderen Modulen) und halten den Node-Event-Loop offen. `pretendToBeVisual: true`
  kommt mit einem eigenen requestAnimationFrame-Dauerlauf dazu. Der Test laeuft dann
  inhaltlich sauber durch – der PROZESS bleibt fuer immer stehen. Am 2026-07-30 hingen so
  sechs node-Prozesse mit vollstaendiger gruener Ausgabe. Jeder jsdom-Test braucht am Ende
  `window.close()` **und** ein ausdrueckliches `process.exit(ok ? 0 : 1)`; im Zweifel mit
  `timeout 60 node …` laufen lassen und den Exit-Code pruefen (124 = haengt).
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
- **Globale UI-Regeln gehoeren in `theme.css`, NICHT in `style.css`:** `style.css` wird nur von
  `settings.html` und `wissen.html` geladen – `portal/chat/userchat/support/api/supportagent`
  laden ausschliesslich `theme.css` (+ chat.css). Die Regel `select option {background-color:
  var(--bg-secondary); color: var(--text-primary)}` stand in style.css und griff deshalb auf
  genau jenen Seiten nicht: der Browser fuellte das Auswahlmenue mit Weiss, erbte aber die helle
  Schriftfarbe des Feldes → **weisse Schrift auf weissem Grund** (gemeldet 2026-07-29 fuer
  *Issue bearbeiten → Status*; betroffen waren alle Dropdowns dort, auch die von Widgets, die
  ihr CSS selbst mitbringen: `issues.js`, `extractor.js`, `profile_switcher.js`).
  Seit 2026-07-29 steht sie in `theme.css` und in style.css nur noch ein Verweis – **nicht
  duplizieren**, sonst driftet es. Merkregel: Betrifft eine Regel Widgets, die auf mehreren
  Seiten auftauchen, muss sie dort stehen, wo ALLE Seiten hinschauen. `color-scheme: dark|light`
  allein genuegt nicht: ein halbtransparenter Feld-Hintergrund (`rgba(var(--fg-rgb),.06)`)
  wird im Popup zu fast Weiss, deshalb braucht `option` eine DECKENDE Flaeche.
  Verifiziert (Playwright, berechnete Farben): normale Eintraege 16.96:1 (dunkel) / 15.90:1
  (hell), ausgewaehlter Eintrag 4.67:1 – jeweils ueber WCAG AA.
- **Icon-Knoepfe in Klapp-Kopfzeilen brauchen `.kb-hdr-btn`**, nicht `.kb-btn-action`:
  Letztere ist ein grosser CTA (Akzent-Hintergrund, weisse Schrift, 0.45rem Padding) und fuellte
  im Telemetry-Reiter die Zeile mit Akzentfarbe. `.kb-btn-danger` war bei 0.72rem umgekehrt zu
  blass. `.kb-hdr-btn` (+ Modifier `.is-danger`) vereinheitlicht Groesse, Rahmen und Hover fuer
  LLM-Verlauf, Kontext/History und Tool-Audit-Log; Farben kommen aus `var(--danger)` per
  `color-mix`. Icon ist `⟳`/`×` als Textglyph statt Emoji – 🔄 wird je nach System farbig
  gerendert und passt sich keinem Theme an.
- **`shutil.move()` auf Agent-Dateien in `/tmp` schlaegt im getrennten Betrieb fehl:** Shell-Befehle
  von Domain-Nutzern laufen ueber den Broker als `jarvis_sandbox` (runuser), die erzeugte Datei
  gehoert also NICHT dem Backend (`jarvis`) – und `/tmp` ist sticky (`drwxrwxrwt`), also darf nur
  der Eigentuemer loeschen. `shutil.move` ist bei Geraetewechsel (tmpfs → Platte) `copy2 + unlink`
  und wirft, wenn NUR das unlink scheitert. In `agent.py::_deliver_docs` sprang die Ausnahme
  dadurch vor `_emit()` heraus: die Kopie lag fertig in `data/documents`, aber der Download-Chip
  wurde nie gesendet – der Nutzer sah eine Antwort **ohne Ergebnisdatei** (`_clean_doc_refs`
  entfernt den Pfad aus dem Anzeigetext, es blieb also gar kein Hinweis). Behoben ueber den
  Helfer `_ingest()`: kopieren muss klappen, Quelle loeschen ist best-effort (Restdatei in tmpfs
  ist harmlos, wird protokolliert). Bei allen Datei-Uebernahmen aus Agent-Arbeitsverzeichnissen
  gilt: **Erfolg am Kopieren messen, nicht am Aufraeumen.**
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
