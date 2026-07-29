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
