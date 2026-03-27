/**
 * Jarvis Haupt-App
 * Verbindet Login, WebSocket, VNC und UI-Steuerung.
 */
(function () {
    'use strict';

    // ─── State ──────────────────────────────────────────────────
    let token = localStorage.getItem('jarvis_token') || '';
    let currentUser = localStorage.getItem('jarvis_user') || '';
    let ws = null;
    let vnc = null;

    // ─── DOM Elemente ───────────────────────────────────────────
    const loginScreen = document.getElementById('login-screen');
    const mainScreen = document.getElementById('main-screen');
    const loginForm = document.getElementById('login-form');
    const loginUsername = document.getElementById('login-username');
    const loginPassword = document.getElementById('login-password');
    const loginError = document.getElementById('login-error');
    const loginBtn = document.getElementById('login-btn');

    const logContainer = document.getElementById('log-container');
    const taskInput = document.getElementById('task-input');
    const btnSend = document.getElementById('btn-send');
    const btnPause = document.getElementById('btn-pause');
    const btnResume = document.getElementById('btn-resume');
    const btnStop = document.getElementById('btn-stop');
    const btnClearLog = document.getElementById('btn-clear-log');
    const btnLogout = document.getElementById('btn-logout');
    const btnMic = document.getElementById('btn-mic');
    const btnZoomIn = document.getElementById('btn-zoom-in');
    const btnZoomOut = document.getElementById('btn-zoom-out');
    const btnZoomReset = document.getElementById('btn-zoom-reset');
    let logZoom = 100; // Zoom-Stufe in Prozent

    const cpuBarFill = document.getElementById('cpu-bar-fill');
    const cpuBarLabel = document.getElementById('cpu-bar-label');
    const connectionDot = document.getElementById('connection-dot');

    // ─── Partikel-Hintergrund (Login) ───────────────────────────
    function initParticles() {
        const container = document.getElementById('particles');
        if (!container) return;

        for (let i = 0; i < 30; i++) {
            const particle = document.createElement('div');
            particle.style.cssText = `
                position: absolute;
                width: ${2 + Math.random() * 4}px;
                height: ${2 + Math.random() * 4}px;
                background: rgba(99, 102, 241, ${0.1 + Math.random() * 0.3});
                border-radius: 50%;
                left: ${Math.random() * 100}%;
                top: ${Math.random() * 100}%;
                animation: float ${5 + Math.random() * 10}s ease-in-out infinite;
                animation-delay: ${Math.random() * 5}s;
            `;
            container.appendChild(particle);
        }

        // Float Animation hinzufügen
        const style = document.createElement('style');
        style.textContent = `
            @keyframes float {
                0%, 100% { transform: translate(0, 0) scale(1); opacity: 0.3; }
                25% { transform: translate(${20 + Math.random() * 30}px, -${20 + Math.random() * 40}px) scale(1.2); opacity: 0.6; }
                50% { transform: translate(-${10 + Math.random() * 20}px, -${40 + Math.random() * 60}px) scale(0.8); opacity: 0.4; }
                75% { transform: translate(${10 + Math.random() * 20}px, -${20 + Math.random() * 30}px) scale(1.1); opacity: 0.5; }
            }
        `;
        document.head.appendChild(style);
    }

    // ─── Login ──────────────────────────────────────────────────
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = loginUsername.value.trim();
        const password = loginPassword.value.trim();
        if (!username || !password) return;

        loginBtn.querySelector('.btn-text').textContent = 'Verbinde...';
        loginBtn.disabled = true;
        loginError.hidden = true;

        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const data = await res.json();

            if (data.success) {
                token = data.token;
                currentUser = data.username || username;
                localStorage.setItem('jarvis_token', token);
                localStorage.setItem('jarvis_user', currentUser);
                showMainScreen(); // initVNC() übernimmt sofortigen VNC-Verbindungsaufbau
            } else {
                loginError.textContent = data.error || 'Anmeldung fehlgeschlagen';
                loginError.hidden = false;
            }
        } catch (err) {
            loginError.textContent = 'Server nicht erreichbar';
            loginError.hidden = false;
        } finally {
            loginBtn.querySelector('.btn-text').textContent = 'ANMELDEN';
            loginBtn.disabled = false;
        }
    });

    // ─── Screen-Wechsel ─────────────────────────────────────────
    function showMainScreen() {
        loginScreen.classList.remove('active');
        mainScreen.classList.add('active');
        connectWebSocket();
        initVNC();
        loadVersion();
    }

    // ─── Version laden und anzeigen ─────────────────────────────
    async function loadVersion() {
        try {
            const res = await fetch('/api/version');
            const data = await res.json();
            const v = data.version || '?';
            // Pill im Header
            const pill = document.getElementById('version-pill');
            if (pill) pill.textContent = 'v' + v;
            // Footer im Settings-Modal
            const footer = document.getElementById('version-modal-footer');
            if (footer) footer.innerHTML = 'Jarvis v' + v + ' · Developed by Andreas Bender with <a href="https://claude.ai" target="_blank" style="color:var(--accent-hover);text-decoration:none;">Claude</a> (Anthropic)';
        } catch (e) { /* Version nicht verfuegbar */ }
    }

    function showLoginScreen() {
        mainScreen.classList.remove('active');
        loginScreen.classList.add('active');
        token = '';
        currentUser = '';
        localStorage.removeItem('jarvis_token');
        localStorage.removeItem('jarvis_user');
        if (ws) ws.disconnect();
        if (vnc) vnc.disconnect();
    }

    // ─── WebSocket ──────────────────────────────────────────────
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        ws = new JarvisWebSocket(wsUrl);

        ws.on('connected', () => {
            connectionDot.classList.add('connected');
            addLogEntry('🔗 Verbindung hergestellt', 'system');
            // Nach Reconnect VNC neu verbinden, falls nicht schon verbunden/probiert
            if (vnc && !vnc.connected && !vnc._probingActive) {
                vnc.startProbing(2000, 30);
            }
        });

        ws.on('disconnected', () => {
            connectionDot.classList.remove('connected');
            // VNC-Probing starten — verbindet automatisch sobald Server zurück
            if (vnc && !vnc._probingActive) {
                vnc.startProbing(3000, 40);
            }
        });

        ws.on('reconnecting', (attempt) => {
            addLogEntry(`🔄 Verbindung wird wiederhergestellt... (Versuch ${attempt})`, 'system');
        });

        ws.on('cpu', (data) => {
            updateCPU(data.value);
        });

        ws.on('status', (data) => {
            const agentId = data.agent_id || '_main';
            addLogEntry(data.message, 'info', data.highlight, agentId);
            // Agent-State in Sidebar aktualisieren
            if (data.agent_id) {
                _updateAgentCard(data.agent_id, data.agent_label, data.state, data.is_sub_agent);
            }
            // Hauptagent-State im Header nur wenn aktiver Agent
            if (agentId === _activeAgentId && data.state) {
                updateAgentState(data.state);
            }
        });

        ws.on('agent_event', (data) => {
            _handleAgentEvent(data);
        });

        ws.on('agent_list', (data) => {
            for (const a of (data.agents || [])) {
                _agentInfos[a.agent_id] = {
                    label: a.label,
                    state: a.state,
                    is_sub_agent: a.is_sub_agent,
                };
                _ensureAgentLog(a.agent_id);
            }
            _renderAgentCards();
            _updateSidebarVisibility();
        });

        ws.on('error', (data) => {
            addLogEntry(`❌ ${data.message || 'Fehler'}`, 'error');
        });

        // TTS-Event: Browser Speech Synthesis fuer Vision-Begruessungen
        ws.on('tts', (data) => {
            const text = data.text || '';
            const name = data.name || '';
            if (text && window.speechSynthesis) {
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.lang = 'de-DE';
                utterance.rate = 1.0;
                utterance.pitch = 1.0;
                window.speechSynthesis.speak(utterance);
                addLogEntry(`🔊 TTS: "${text}"`);
            } else {
                addLogEntry(`🔊 Begrüßung (kein TTS verfügbar): ${text}`);
            }
        });

        // Vorgerenderte Audio-Begruessungen abspielen
        ws.on('greet_audio', (data) => {
            const url = data.url || '';
            const name = data.name || '';
            if (url) {
                const t = localStorage.getItem('jarvis_token') || '';
                const audio = new Audio(`${url}?token=${t}`);
                audio.play().catch(e => console.warn('Audio playback failed:', e));
                addLogEntry(`🔊 Begrüßung: ${name}`);
            }
        });

        // Alle Nachrichten als DOM-Event weitersenden (für OpenClaw Import-Modal etc.)
        ws.on('message', (data) => {
            window.dispatchEvent(new CustomEvent('jarvis-ws-message', { detail: data }));
        });

        ws.connect();
    }

    // ─── Globale Helfer für Skills / OpenClaw Import ─────────────
    /** Sendet einen Task an den Jarvis-Agenten via WebSocket. */
    window.sendJarvisTask = function (text) {
        if (!ws) return false;
        ws.send({ type: 'task', text, token });
        addLogEntry(`📝 Aufgabe: ${text.substring(0, 80)}…`, 'task', true);
        return true;
    };

    // ─── VNC ────────────────────────────────────────────────────
    async function initVNC() {
        vnc = new JarvisVNC();
        try {
            const res = await fetch('/api/config');
            const data = await res.json();
            if (data.vnc_available) {
                vnc.connect(data.websockify_port);
            }
        } catch {
            vnc.showError();
        }
    }

    // ─── Aufgabe senden ─────────────────────────────────────────
    function sendTask() {
        const text = taskInput.value.trim();
        if (!text || !ws) return;

        // Aufgabe an den aktiven Agent senden
        const msg = { type: 'task', text, token };
        if (_activeAgentId && _activeAgentId !== '_main') {
            msg.agent_id = _activeAgentId;
        }
        ws.send(msg);
        addLogEntry(`📝 Aufgabe: ${text}`, 'task', true, _activeAgentId);
        taskInput.value = '';
        taskInput.style.height = 'auto';

        // Steuerung aktivieren
        btnPause.disabled = false;
        btnStop.disabled = false;
    }

    // ─── Sprachsteuerung (STT) ──────────────────────────────────
    let isRecording = false;
    let recognition = null;

    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'de-DE';

        recognition.onstart = () => {
            isRecording = true;
            btnMic.classList.add('recording');
            addLogEntry('🎤 Höre zu...', 'system');
        };

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            taskInput.value = transcript;
            taskInput.dispatchEvent(new Event('input')); // Trigger auto-resize
            addLogEntry(`🎙️ Erkannt: "${transcript}"`, 'system');
        };

        recognition.onerror = (event) => {
            console.error('Speech recognition error', event.error);
            stopRecording();
        };

        recognition.onend = () => {
            stopRecording();
        };
    }

    function stopRecording() {
        isRecording = false;
        btnMic.classList.remove('recording');
        if (recognition) recognition.stop();
    }

    if (btnMic) {
        btnMic.addEventListener('click', () => {
            if (!recognition) {
                alert('Spracherkennung wird von deinem Browser leider nicht unterstützt (nutze Chrome oder Edge).');
                return;
            }
            if (isRecording) {
                stopRecording();
            } else {
                recognition.start();
            }
        });
    }

    btnSend.addEventListener('click', sendTask);
    taskInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendTask();
        }
    });

    // Auto-Resize Textarea
    taskInput.addEventListener('input', () => {
        taskInput.style.height = 'auto';
        taskInput.style.height = Math.min(taskInput.scrollHeight, 120) + 'px';
    });

    // ─── Steuerung ──────────────────────────────────────────────
    // Steuerungs-Befehle an den aktiven Agent senden
    function _controlMsg(action) {
        const msg = { type: 'control', action, token };
        // Wenn ein bestimmter Agent aktiv ist, gezielt steuern
        if (_activeAgentId && _activeAgentId !== '_main') {
            msg.agent_id = _activeAgentId;
        }
        return msg;
    }

    btnPause.addEventListener('click', () => {
        ws.send(_controlMsg('pause'));
        btnPause.hidden = true;
        btnResume.hidden = false;
        btnResume.disabled = false;
    });

    btnResume.addEventListener('click', () => {
        ws.send(_controlMsg('resume'));
        btnResume.hidden = true;
        btnPause.hidden = false;
        btnPause.disabled = false;
    });

    btnStop.addEventListener('click', () => {
        ws.send(_controlMsg('stop'));
        btnPause.disabled = true;
        btnStop.disabled = true;
        btnResume.hidden = true;
        btnPause.hidden = false;

        // Bei Stop: zurueck zum Hauptagent wechseln
        const mainId = Object.keys(_agentInfos).find(id => !_agentInfos[id].is_sub_agent);
        if (mainId && _activeAgentId !== mainId) {
            _switchToAgent(mainId);
        } else if (!mainId) {
            _switchToAgent('_main');
        }
    });

    // ─── Debug-Toggle ──────────────────────────────────────────
    const btnDebug = document.getElementById('btn-debug');
    let _debugMode = localStorage.getItem('jarvis_debug') !== 'false'; // Default: an
    // Initialzustand setzen
    if (_debugMode) {
        btnDebug.classList.add('active');
    } else {
        btnDebug.classList.remove('active');
        logContainer.classList.add('hide-debug');
    }

    btnDebug.addEventListener('click', () => {
        _debugMode = !_debugMode;
        localStorage.setItem('jarvis_debug', _debugMode);
        btnDebug.classList.toggle('active', _debugMode);
        logContainer.classList.toggle('hide-debug', !_debugMode);
        // Zum Ende scrollen
        logContainer.scrollTop = logContainer.scrollHeight;
    });

    function applyLogZoom() {
        logContainer.style.fontSize = (logZoom / 100 * 0.84).toFixed(3) + 'rem';
        btnZoomReset.textContent = logZoom + '%';
    }

    btnZoomIn.addEventListener('click', () => {
        if (logZoom < 200) { logZoom += 10; applyLogZoom(); }
    });

    btnZoomOut.addEventListener('click', () => {
        if (logZoom > 50) { logZoom -= 10; applyLogZoom(); }
    });

    btnZoomReset.addEventListener('click', () => {
        logZoom = 100; applyLogZoom();
    });

    btnClearLog.addEventListener('click', () => {
        // Nur Eintraege des aktiven Agents entfernen
        const entries = logContainer.querySelectorAll(`.log-entry[data-agent-id="${_activeAgentId}"]`);
        entries.forEach(e => e.remove());
        if (_agentLogs[_activeAgentId]) {
            _agentLogs[_activeAgentId] = [];
        }
    });

    btnLogout.addEventListener('click', () => {
        showLoginScreen();
    });

    // ─── Sprachausgabe (TTS) ────────────────────────────────────
    function speak(text) {
        if (!window.speechSynthesis) return;
        // Falls TTS deaktiviert ist, abbrechen
        const ttsEnabled = document.getElementById('setting-tts')?.checked;
        if (!ttsEnabled) return;

        // Laufende Sprachausgaben abbrechen um Überlappung zu vermeiden
        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'de-DE';
        utterance.rate = 1.0;
        utterance.pitch = 1.0;

        // Versuche eine deutsche Stimme zu finden
        const voices = window.speechSynthesis.getVoices();
        const deVoice = voices.find(v => v.lang.startsWith('de'));
        if (deVoice) utterance.voice = deVoice;

        window.speechSynthesis.speak(utterance);
    }

    // ─── Multi-Agent State ──────────────────────────────────────
    const _agentLogs = {};        // agent_id → [DOM-Elemente]
    let _activeAgentId = '_main'; // Aktuell angezeigter Agent
    const _agentInfos = {};       // agent_id → {label, state, is_sub_agent}

    function _ensureAgentLog(agentId) {
        if (!_agentLogs[agentId]) {
            _agentLogs[agentId] = [];
        }
    }

    function _switchToAgent(agentId) {
        if (_activeAgentId === agentId) return;
        _activeAgentId = agentId;

        // Alle Log-Eintraege im Container ausblenden
        const entries = logContainer.querySelectorAll('.log-entry');
        entries.forEach(e => {
            e.style.display = (e.dataset.agentId === agentId || !e.dataset.agentId) ? '' : 'none';
        });

        // Active-Klasse in Sidebar setzen
        document.querySelectorAll('.agent-card').forEach(c => {
            c.classList.toggle('active', c.dataset.agentId === agentId);
        });

        // Placeholder im Eingabefeld aktualisieren
        const info = _agentInfos[agentId];
        if (info && info.is_sub_agent) {
            taskInput.placeholder = `Nachricht an ${info.label}...`;
        } else {
            taskInput.placeholder = 'Aufgabe eingeben...';
        }

        // Zum Ende scrollen
        logContainer.scrollTop = logContainer.scrollHeight;
    }

    function _updateAgentCard(agentId, label, state, isSubAgent) {
        _agentInfos[agentId] = { label: label || agentId, state: state || 'idle', is_sub_agent: isSubAgent };
        _renderAgentCards();
    }

    function _handleAgentEvent(data) {
        const event = data.event;
        const agent = data.agent || {};
        const agents = data.agents || [];

        if (event === 'started' && !agent.is_sub_agent) {
            // Neuer Hauptagent gestartet – alte Agent-Infos zuruecksetzen
            // (z.B. nach Service-Restart oder neuem Task)
            const oldIds = Object.keys(_agentInfos);
            for (const oldId of oldIds) {
                delete _agentInfos[oldId];
            }
            _activeAgentId = agent.agent_id;
        }

        if (event === 'started' || event === 'spawned') {
            _agentInfos[agent.agent_id] = {
                label: agent.label,
                state: agent.state,
                is_sub_agent: agent.is_sub_agent,
            };
            _ensureAgentLog(agent.agent_id);
        }

        if (event === 'finished' && agent.is_sub_agent) {
            // Sub-Agent fertig – State aktualisieren
            if (_agentInfos[agent.agent_id]) {
                _agentInfos[agent.agent_id].state = 'idle';
            }
            // Wenn der beendete Sub-Agent aktiv war: zurueck zum Hauptagent
            if (_activeAgentId === agent.agent_id) {
                const mainId = Object.keys(_agentInfos).find(id => !_agentInfos[id].is_sub_agent);
                if (mainId) _switchToAgent(mainId);
            }
            // Auto-Cleanup: Sub-Agent nach 8 Sekunden entfernen (nur wenn nicht pausiert)
            const removeId = agent.agent_id;
            setTimeout(() => {
                const info = _agentInfos[removeId];
                if (info && info.state !== 'paused') {
                    window._removeAgent(removeId);
                }
            }, 8000);
        }

        if (event === 'paused' && agent.is_sub_agent) {
            // Sub-Agent pausiert – State aktualisieren, NICHT entfernen
            if (_agentInfos[agent.agent_id]) {
                _agentInfos[agent.agent_id].state = 'paused';
            }
        }

        // Alle Agent-Infos aktualisieren
        for (const a of agents) {
            _agentInfos[a.agent_id] = {
                label: a.label,
                state: a.state,
                is_sub_agent: a.is_sub_agent,
            };
        }

        _renderAgentCards();
        _updateSidebarVisibility();
    }

    function _renderAgentCards() {
        const list = document.getElementById('agent-sidebar-list');
        if (!list) return;

        const ids = Object.keys(_agentInfos);
        // Hauptagent zuerst, dann Sub-Agents
        ids.sort((a, b) => {
            const aMain = !_agentInfos[a].is_sub_agent;
            const bMain = !_agentInfos[b].is_sub_agent;
            if (aMain !== bMain) return aMain ? -1 : 1;
            return 0;
        });

        list.innerHTML = ids.map(id => {
            const info = _agentInfos[id];
            const isActive = id === _activeAgentId;
            const typeClass = info.is_sub_agent ? 'sub-agent' : 'main-agent';
            const stateLabel = { running: 'Läuft', idle: 'Bereit', paused: 'Pause', stopped: 'Stopp' };
            const closeBtn = info.is_sub_agent
                ? `<span class="agent-card-close" onclick="event.stopPropagation(); window._removeAgent('${id}')" title="Entfernen">×</span>`
                : '';
            return `<div class="agent-card ${typeClass} ${isActive ? 'active' : ''}"
                         data-agent-id="${id}"
                         onclick="window._switchAgent('${id}')">
                <div class="agent-card-header">
                    <div class="agent-card-label" title="${escapeHtml(info.label)}">${escapeHtml(info.label)}</div>
                    ${closeBtn}
                </div>
                <div class="agent-card-state">
                    <span class="state-dot ${info.state}"></span>
                    ${stateLabel[info.state] || info.state}
                </div>
            </div>`;
        }).join('');

        _updateSidebarVisibility();
    }

    function _updateSidebarVisibility() {
        const sidebar = document.getElementById('agent-sidebar');
        const resizeHandle = document.getElementById('agent-sidebar-resize');
        if (!sidebar) return;

        // Sidebar nur zeigen wenn Sub-Agents existieren
        const hasSubAgents = Object.values(_agentInfos).some(a => a.is_sub_agent);
        sidebar.style.display = hasSubAgents ? '' : 'none';
        if (resizeHandle) resizeHandle.style.display = hasSubAgents ? '' : 'none';
    }

    // ─── Sidebar Drag-Resize ─────────────────────────────────────
    (function initSidebarResize() {
        const handle = document.getElementById('agent-sidebar-resize');
        const sidebar = document.getElementById('agent-sidebar');
        if (!handle || !sidebar) return;

        let dragging = false;
        let startX = 0;
        let startW = 0;

        handle.addEventListener('mousedown', (e) => {
            e.preventDefault();
            dragging = true;
            startX = e.clientX;
            startW = sidebar.offsetWidth;
            handle.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        });

        document.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            // Sidebar ist rechts, also: Maus nach links = breiter
            const diff = startX - e.clientX;
            const newW = Math.max(100, Math.min(350, startW + diff));
            sidebar.style.width = newW + 'px';
        });

        document.addEventListener('mouseup', () => {
            if (!dragging) return;
            dragging = false;
            handle.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        });
    })();

    // Global erreichbar fuer onclick
    window._switchAgent = function(agentId) {
        _switchToAgent(agentId);
    };

    // Sub-Agent entfernen (X-Button oder Auto-Cleanup)
    window._removeAgent = function(agentId) {
        const info = _agentInfos[agentId];
        if (!info) return;

        // Falls dieser Agent gerade aktiv: zurueck zum Hauptagent
        if (_activeAgentId === agentId) {
            const mainId = Object.keys(_agentInfos).find(id => !_agentInfos[id].is_sub_agent);
            if (mainId) _switchToAgent(mainId);
        }

        // Agent-Eintraege aus DOM entfernen
        if (_agentLogs[agentId]) {
            _agentLogs[agentId].forEach(el => { if (el.parentNode) el.parentNode.removeChild(el); });
            delete _agentLogs[agentId];
        }

        // Agent-Info entfernen
        delete _agentInfos[agentId];

        // Sidebar aktualisieren
        _renderAgentCards();
        _updateSidebarVisibility();

        // Backend informieren (Agent stoppen falls noch laufend)
        if (info.state === 'running') {
            ws.send(JSON.stringify({ type: 'control', action: 'stop', agent_id: agentId, token }));
        }
    };

    // ─── Log ────────────────────────────────────────────────────
    function addLogEntry(message, type = 'info', highlight = false, agentId = null) {
        if (type === 'system' || type === 'info') {
            const cleanMessage = message.replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '');
            speak(cleanMessage);
        }
        // Willkommens-Nachricht entfernen
        const welcome = logContainer.querySelector('.log-welcome');
        if (welcome) welcome.remove();

        const entry = document.createElement('div');
        entry.className = 'log-entry' + (highlight ? ' log-highlight' : '');

        // Agent-ID zuordnen
        const effectiveAgentId = agentId || '_main';
        entry.dataset.agentId = effectiveAgentId;

        // Nur anzeigen wenn dieser Agent aktiv ist
        if (effectiveAgentId !== _activeAgentId) {
            entry.style.display = 'none';
        }

        // In per-Agent Log-Buffer speichern
        _ensureAgentLog(effectiveAgentId);
        _agentLogs[effectiveAgentId].push(entry);

        const now = new Date();
        const time = now.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

        entry.innerHTML = `<span class="log-time">${time}</span>${escapeHtml(message)}`;

        logContainer.appendChild(entry);

        // Auto-Scroll nur wenn aktiver Agent
        if (effectiveAgentId === _activeAgentId) {
            logContainer.scrollTop = logContainer.scrollHeight;
        }

        // Max 500 Eintraege pro Agent behalten
        const agentEntries = _agentLogs[effectiveAgentId];
        while (agentEntries.length > 500) {
            const old = agentEntries.shift();
            if (old.parentNode) old.parentNode.removeChild(old);
        }
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ─── CPU Bar ────────────────────────────────────────────────
    function updateCPU(percent) {
        const pct = Math.max(0, Math.min(100, percent));
        cpuBarFill.style.width = pct + '%';
        cpuBarLabel.textContent = `CPU: ${Math.round(pct)}%`;

        // Gradient-Position basierend auf Last
        const gradientPos = pct + '%';
        cpuBarFill.style.backgroundPosition = `${pct}% 0`;
    }

    // ─── Agent State ────────────────────────────────────────────
    function updateAgentState(state) {
        switch (state) {
            case 'running':
                btnPause.disabled = false;
                btnStop.disabled = false;
                break;
            case 'paused':
                break;
            case 'stopped':
                btnPause.disabled = true;
                btnStop.disabled = true;
                break;
            case 'idle':
                btnPause.disabled = true;
                btnStop.disabled = true;
                btnResume.hidden = true;
                btnPause.hidden = false;
                break;
        }
    }

    function setupSettings() {
        const modal = document.getElementById('settings-modal');
        const btnOpen = document.getElementById('btn-settings');
        const btnClose = document.getElementById('btn-close-settings');
        const settingsTitle = document.getElementById('settings-title');

        // Ansichten
        const listView = document.getElementById('profiles-list-view');
        const editView = document.getElementById('profile-edit-view');
        const profilesContainer = document.getElementById('profiles-container');

        // Profil-Editor Felder
        const inputName = document.getElementById('profile-name');
        const selectProvider = document.getElementById('profile-provider');
        const inputUrl = document.getElementById('profile-api-url');
        const selectModel = document.getElementById('profile-model-select');
        const inputModel = document.getElementById('profile-model-input');
        const modelSelectGroup = document.getElementById('model-select-group');
        const modelInputGroup = document.getElementById('model-input-group');
        const promptToolGroup = document.getElementById('prompt-tool-group');
        const checkPromptTool = document.getElementById('profile-prompt-tool-calling');
        const inputKey = document.getElementById('profile-api-key');
        const inputSessionKey = document.getElementById('profile-session-key');
        const apikeyHint = document.querySelector('.apikey-hint');
        const checkTts = document.getElementById('setting-tts');
        const inputAgentKey = document.getElementById('setting-agent-api-key');
        const btnGenKey = document.getElementById('btn-generate-apikey');
        const btnCopyKey = document.getElementById('btn-copy-apikey');
        const btnToggleKey = document.getElementById('btn-toggle-apikey');
        let _agentKeyVisible = false;
        let _agentKeyValue = '';
        const authMethodGroup = document.getElementById('auth-method-group');
        const apikeyGroup = document.getElementById('apikey-group');
        const sessionGroup = document.getElementById('session-group');
        const radioApiKey = document.getElementById('auth-apikey');
        const radioSession = document.getElementById('auth-session');

        const btnAddProfile = document.getElementById('btn-add-profile');
        const btnSaveProfile = document.getElementById('btn-save-profile');
        const btnCancelProfile = document.getElementById('btn-cancel-profile');

        let profiles = [];
        let activeProfileId = '';
        let defaults = {};
        let editingProfileId = null; // null = neues Profil

        if (!modal || !btnOpen) return;

        const PROVIDER_LABELS = {
            'google': 'Google Gemini',
            'openrouter': 'OpenRouter',
            'anthropic': 'Anthropic Claude',
            'openai_compatible': 'OpenAI-Kompatibel',
        };

        // ── Skill Manager ──
        let skillManager = null;
        if (window.JarvisSkillManager) {
            skillManager = new window.JarvisSkillManager();
        }

        // ── Settings Tabs ──
        const settingsTabs = document.querySelectorAll('.settings-tab-btn');
        const tabProfiles = document.getElementById('settings-tab-profiles');
        const tabSkills = document.getElementById('settings-tab-skills');
        const tabWhatsApp = document.getElementById('settings-tab-whatsapp');
        const tabKnowledge = document.getElementById('settings-tab-knowledge');
        const tabGoogle = document.getElementById('settings-tab-google');
        const tabVision = document.getElementById('settings-tab-vision');
        const tabMcp = document.getElementById('settings-tab-mcp');

        const allSettingsTabs = [tabProfiles, tabSkills, tabWhatsApp, tabKnowledge, tabGoogle, tabVision, tabMcp];

        settingsTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                settingsTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                const target = tab.dataset.settingsTab;
                // Alle Tabs ausblenden
                allSettingsTabs.forEach(t => {
                    if (t) { t.style.display = 'none'; t.classList.remove('active'); }
                });

                if (target === 'profiles' && tabProfiles) {
                    tabProfiles.style.display = '';
                    tabProfiles.classList.add('active');
                } else if (target === 'skills' && tabSkills) {
                    tabSkills.style.display = '';
                    tabSkills.classList.add('active');
                    if (skillManager) skillManager.loadSkills();
                } else if (target === 'whatsapp' && tabWhatsApp) {
                    tabWhatsApp.style.display = '';
                    tabWhatsApp.classList.add('active');
                    if (window.waManager) window.waManager.refresh();
                } else if (target === 'knowledge' && tabKnowledge) {
                    tabKnowledge.style.display = '';
                    tabKnowledge.classList.add('active');
                    if (window.knowledgeManager) window.knowledgeManager.init();
                } else if (target === 'google' && tabGoogle) {
                    tabGoogle.style.display = '';
                    tabGoogle.classList.add('active');
                    if (window.googleManager) window.googleManager.init();
                } else if (target === 'mcp' && tabMcp) {
                    tabMcp.style.display = '';
                    tabMcp.classList.add('active');
                    if (window.mcpManager) window.mcpManager.refresh();
                } else if (target === 'vision' && tabVision) {
                    tabVision.style.display = '';
                    tabVision.classList.add('active');
                    if (window.visionManager) window.visionManager.refresh();
                }

                // Vision-Polling stoppen wenn weg-navigiert
                if (target !== 'vision' && window.visionManager) {
                    window.visionManager.stop();
                }
            });
        });

        // ── Google-Tab entfernt – Config erfolgt über Skill-Einstellungen ──
        window.updateGoogleTabVisibility = function() {}; // No-Op (Rückwärtskompatibilität)

        // ── WhatsApp-Tab-Button: nur sichtbar wenn 'whatsapp'-Skill aktiviert ──
        const waTabBtn = document.getElementById('settings-tab-btn-whatsapp');

        window.updateWhatsAppTabVisibility = async function updateWhatsAppTabVisibility() {
            if (!waTabBtn) return;
            try {
                const token = localStorage.getItem('jarvis_token') || '';
                const resp = await fetch('/api/skills', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const skills = data.skills || data || [];
                const waSkill = Array.isArray(skills)
                    ? skills.find(s => s.dir_name === 'whatsapp')
                    : null;
                const isEnabled = waSkill && waSkill.enabled;
                waTabBtn.style.display = isEnabled ? '' : 'none';
                // Falls WhatsApp-Tab aktiv war und Skill deaktiviert → zu Profilen wechseln
                if (!isEnabled && tabWhatsApp && tabWhatsApp.classList.contains('active')) {
                    settingsTabs.forEach(t => t.classList.remove('active'));
                    if (settingsTabs[0]) settingsTabs[0].classList.add('active');
                    allSettingsTabs.forEach(t => { if (t) { t.style.display = 'none'; t.classList.remove('active'); } });
                    if (tabProfiles) { tabProfiles.style.display = ''; tabProfiles.classList.add('active'); }
                }
            } catch (e) {
                // Fehler ignorieren – Tab bleibt versteckt
            }
        }

        // ── Vision-Tab-Button: nur sichtbar wenn 'vision'-Skill aktiviert ──
        const visionTabBtn = document.getElementById('settings-tab-btn-vision');

        window.updateVisionTabVisibility = async function updateVisionTabVisibility() {
            if (!visionTabBtn) return;
            try {
                const token = localStorage.getItem('jarvis_token') || '';
                const resp = await fetch('/api/skills', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const skills = data.skills || data || [];
                const visionSkill = Array.isArray(skills)
                    ? skills.find(s => s.dir_name === 'vision')
                    : null;
                const isEnabled = visionSkill && visionSkill.enabled;
                visionTabBtn.style.display = isEnabled ? '' : 'none';
                // Falls Vision-Tab aktiv war und Skill nun deaktiviert → zu Profilen wechseln
                if (!isEnabled && tabVision && tabVision.classList.contains('active')) {
                    settingsTabs.forEach(t => t.classList.remove('active'));
                    if (settingsTabs[0]) settingsTabs[0].classList.add('active');
                    allSettingsTabs.forEach(t => { if (t) { t.style.display = 'none'; t.classList.remove('active'); } });
                    if (tabProfiles) { tabProfiles.style.display = ''; tabProfiles.classList.add('active'); }
                    if (window.visionManager) window.visionManager.stop();
                }
            } catch (e) {
                // Fehler ignorieren – Tab bleibt versteckt
            }
        }

        // ── Modal öffnen/schließen ──
        const openModal = async () => {
            await loadProfiles();
            await updateGoogleTabVisibility();
            await updateWhatsAppTabVisibility();
            await updateVisionTabVisibility();
            showListView();
            // Ersten Tab aktivieren
            settingsTabs.forEach(t => t.classList.remove('active'));
            if (settingsTabs[0]) settingsTabs[0].classList.add('active');
            if (tabProfiles) { tabProfiles.style.display = ''; tabProfiles.classList.add('active'); }
            if (tabSkills) { tabSkills.style.display = 'none'; tabSkills.classList.remove('active'); }
            if (tabWhatsApp) { tabWhatsApp.style.display = 'none'; tabWhatsApp.classList.remove('active'); }
            if (tabKnowledge) { tabKnowledge.style.display = 'none'; tabKnowledge.classList.remove('active'); }
            if (tabGoogle) { tabGoogle.style.display = 'none'; tabGoogle.classList.remove('active'); }
            if (tabVision) { tabVision.style.display = 'none'; tabVision.classList.remove('active'); }
            modal.classList.add('open');
        };
        const closeModal = () => {
            modal.classList.remove('open');
            if (window.visionManager) window.visionManager.stop();
        };

        btnOpen.addEventListener('click', openModal);
        btnClose.addEventListener('click', closeModal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });

        // ── Ansicht wechseln ──
        function showListView() {
            listView.style.display = '';
            editView.style.display = 'none';
            settingsTitle.textContent = 'KI-Einstellungen';
        }

        function showEditView(isNew) {
            listView.style.display = 'none';
            editView.style.display = '';
            settingsTitle.textContent = isNew ? 'Neues Profil' : 'Profil bearbeiten';
        }

        // ── Profile laden ──
        async function loadProfiles() {
            try {
                const res = await fetch('/api/settings', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await res.json();
                profiles = data.profiles || [];
                activeProfileId = data.active_profile_id || '';
                defaults = data.defaults || {};
                if (checkTts) checkTts.checked = data.tts_enabled || false;
                // Agent API Key laden
                _agentKeyValue = data.agent_api_key || '';
                if (inputAgentKey) {
                    inputAgentKey.value = _agentKeyValue ? '••••••••••••••••••••••' : '';
                    inputAgentKey.readOnly = true;
                    _agentKeyVisible = false;
                }
                renderProfileList();
            } catch (err) {
                console.error('Fehler beim Laden der Profile:', err);
            }
        }

        // ── Profilliste rendern ──
        function renderProfileList() {
            profilesContainer.innerHTML = '';
            profiles.forEach(p => {
                const card = document.createElement('div');
                card.className = 'profile-card' + (p.id === activeProfileId ? ' active' : '');
                card.innerHTML = `
                    <div class="profile-info" data-id="${p.id}">
                        <span class="profile-name">${escapeHtml(p.name)}</span>
                        <span class="profile-detail">${PROVIDER_LABELS[p.provider] || p.provider} · ${escapeHtml(p.model)}</span>
                    </div>
                    <div class="profile-actions">
                        <button class="btn-icon btn-small btn-edit-profile" data-id="${p.id}" title="Bearbeiten">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                        </button>
                        <button class="btn-icon btn-small btn-delete-profile" data-id="${p.id}" title="Löschen">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                    </div>
                `;
                // Klick auf Info-Bereich = Profil aktivieren
                card.querySelector('.profile-info').addEventListener('click', () => activateProfile(p.id));
                card.querySelector('.btn-edit-profile').addEventListener('click', (e) => {
                    e.stopPropagation();
                    openEditView(p.id);
                });
                card.querySelector('.btn-delete-profile').addEventListener('click', (e) => {
                    e.stopPropagation();
                    deleteProfile(p.id);
                });
                profilesContainer.appendChild(card);
            });
        }

        // ── Profil aktivieren ──
        async function activateProfile(id) {
            try {
                await fetch(`/api/profiles/${id}/activate`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                activeProfileId = id;
                renderProfileList();
                const profile = profiles.find(p => p.id === id);
                if (profile) {
                    addLogEntry('Profil gewechselt: ' + profile.name, 'system');
                }
            } catch (err) {
                console.error('Fehler beim Aktivieren:', err);
            }
        }

        // ── Profil löschen ──
        async function deleteProfile(id) {
            if (profiles.length <= 1) {
                alert('Das letzte Profil kann nicht gelöscht werden.');
                return;
            }
            const profile = profiles.find(p => p.id === id);
            if (!confirm(`Profil "${profile?.name}" wirklich löschen?`)) return;

            try {
                const res = await fetch(`/api/profiles/${id}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await res.json();
                if (data.success) {
                    await loadProfiles();
                    addLogEntry('Profil gelöscht: ' + (profile?.name || ''), 'system');
                } else {
                    alert('Fehler: ' + (data.error || 'Unbekannt'));
                }
            } catch (err) {
                alert('Server-Verbindung fehlgeschlagen');
            }
        }

        // ── Editor öffnen ──
        function openEditView(id) {
            editingProfileId = id || null;
            const profile = id ? profiles.find(p => p.id === id) : null;

            // Felder befüllen
            inputName.value = profile ? profile.name : '';
            selectProvider.value = profile ? profile.provider : 'google';
            inputUrl.value = profile ? profile.api_url : '';
            inputKey.value = profile ? profile.api_key : '';

            // Auth-Methode
            if (profile && profile.auth_method === 'session') {
                radioSession.checked = true;
            } else {
                radioApiKey.checked = true;
            }
            if (inputSessionKey) {
                inputSessionKey.value = profile ? (profile.session_key || '') : '';
            }

            // Provider-abhängige Felder initialisieren
            updateProviderUI();

            // Modell setzen (nach updateProviderUI)
            if (profile) {
                if (profile.provider === 'openai_compatible') {
                    inputModel.value = profile.model;
                } else {
                    selectModel.value = profile.model;
                }
                if (checkPromptTool) {
                    checkPromptTool.checked = !!profile.prompt_tool_calling;
                }
            } else if (checkPromptTool) {
                checkPromptTool.checked = false;
            }

            showEditView(!id);
        }

        // ── Provider-abhängige UI aktualisieren ──
        function updateProviderUI() {
            const provider = selectProvider.value;
            const isAnthropic = provider === 'anthropic';
            const isOpenAICompat = provider === 'openai_compatible';
            const isSession = radioSession && radioSession.checked;

            // Modell: Dropdown vs. Freitext
            if (isOpenAICompat) {
                modelSelectGroup.style.display = 'none';
                modelInputGroup.style.display = '';
            } else {
                modelSelectGroup.style.display = '';
                modelInputGroup.style.display = 'none';
                // Modell-Liste befüllen
                const models = (defaults[provider] && defaults[provider].models) || [];
                selectModel.innerHTML = '';
                models.forEach(m => {
                    const opt = document.createElement('option');
                    opt.value = opt.textContent = m;
                    selectModel.appendChild(opt);
                });
            }

            // URL vorbefüllen wenn leer
            if (!inputUrl.value && defaults[provider]) {
                inputUrl.value = defaults[provider].url || '';
            }

            // Auth-Methode nur bei Anthropic
            authMethodGroup.style.display = isAnthropic ? '' : 'none';

            // API Key / Session Key
            if (isAnthropic && isSession) {
                apikeyGroup.style.display = 'none';
                sessionGroup.style.display = '';
            } else {
                apikeyGroup.style.display = '';
                sessionGroup.style.display = 'none';
            }

            // API Key Hinweis
            if (apikeyHint) {
                apikeyHint.textContent = isOpenAICompat ? 'Optional – für Ollama nicht erforderlich' : '';
            }

            // Prompt-Tool-Calling nur bei openai_compatible anzeigen
            if (promptToolGroup) {
                promptToolGroup.style.display = isOpenAICompat ? '' : 'none';
            }
        }

        // Event-Listener für Provider/Auth-Wechsel
        selectProvider.addEventListener('change', () => {
            // URL zurücksetzen bei Provider-Wechsel
            const provider = selectProvider.value;
            if (defaults[provider]) {
                inputUrl.value = defaults[provider].url || '';
            }
            updateProviderUI();
        });
        if (radioApiKey) radioApiKey.addEventListener('change', updateProviderUI);
        if (radioSession) radioSession.addEventListener('change', updateProviderUI);

        // ── Neues Profil ──
        btnAddProfile.addEventListener('click', () => openEditView(null));

        // ── Profil speichern ──
        btnSaveProfile.addEventListener('click', async () => {
            const provider = selectProvider.value;
            const isSession = provider === 'anthropic' && radioSession && radioSession.checked;
            const model = provider === 'openai_compatible' ? inputModel.value : selectModel.value;

            if (!inputName.value.trim()) {
                alert('Bitte einen Profilnamen eingeben.');
                return;
            }
            if (!model.trim()) {
                alert('Bitte ein Modell angeben.');
                return;
            }

            const profileData = {
                name: inputName.value.trim(),
                provider: provider,
                model: model,
                api_url: inputUrl.value,
                api_key: isSession ? '' : inputKey.value,
                auth_method: isSession ? 'session' : 'api_key',
                session_key: isSession && inputSessionKey ? inputSessionKey.value : '',
                prompt_tool_calling: provider === 'openai_compatible' && checkPromptTool ? checkPromptTool.checked : false,
            };

            btnSaveProfile.textContent = 'Speichere...';
            btnSaveProfile.disabled = true;

            try {
                let res;
                if (editingProfileId) {
                    // Aktualisieren
                    res = await fetch(`/api/profiles/${editingProfileId}`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify(profileData)
                    });
                } else {
                    // Neu erstellen
                    res = await fetch('/api/profiles', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify(profileData)
                    });
                }
                const data = await res.json();
                if (data.success) {
                    addLogEntry('Profil gespeichert: ' + profileData.name, 'system');
                    await loadProfiles();
                    showListView();
                } else {
                    alert('Fehler: ' + (data.error || 'Unbekannt'));
                }
            } catch (err) {
                alert('Server-Verbindung fehlgeschlagen');
            } finally {
                btnSaveProfile.textContent = 'Speichern';
                btnSaveProfile.disabled = false;
            }
        });

        // ── Abbrechen (zurück zur Liste) ──
        btnCancelProfile.addEventListener('click', showListView);

        // ── TTS-Checkbox speichern ──
        if (checkTts) {
            checkTts.addEventListener('change', async () => {
                try {
                    await fetch('/api/settings', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({ tts_enabled: checkTts.checked })
                    });
                } catch (err) {
                    console.error('Fehler beim Speichern der TTS-Einstellung:', err);
                }
            });
        }

        // ── Agent API Key: Generieren ──
        if (btnGenKey) {
            btnGenKey.addEventListener('click', async () => {
                // Kryptographisch sicheren Key generieren (Browser Crypto API)
                const buf = new Uint8Array(32);
                crypto.getRandomValues(buf);
                const newKey = btoa(String.fromCharCode(...buf))
                    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
                _agentKeyValue = newKey;
                _agentKeyVisible = true;
                if (inputAgentKey) {
                    inputAgentKey.value = newKey;
                    inputAgentKey.readOnly = false;
                }
                // Sofort speichern
                try {
                    await fetch('/api/settings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                        body: JSON.stringify({ agent_api_key: newKey })
                    });
                } catch (err) {
                    console.error('Fehler beim Speichern des Agent API Keys:', err);
                }
            });
        }

        // ── Agent API Key: Kopieren ──
        if (btnCopyKey) {
            btnCopyKey.addEventListener('click', () => {
                if (_agentKeyValue) {
                    navigator.clipboard.writeText(_agentKeyValue).then(() => {
                        btnCopyKey.title = 'Kopiert!';
                        setTimeout(() => { btnCopyKey.title = 'Kopieren'; }, 2000);
                    });
                }
            });
        }

        // ── Agent API Key: Anzeigen/Verbergen ──
        if (btnToggleKey) {
            btnToggleKey.addEventListener('click', () => {
                _agentKeyVisible = !_agentKeyVisible;
                if (inputAgentKey) {
                    inputAgentKey.value = _agentKeyVisible ? _agentKeyValue : (_agentKeyValue ? '••••••••••••••••••••••' : '');
                    inputAgentKey.readOnly = !_agentKeyVisible;
                }
            });
        }

        // ── Agent API Key: Manuelle Eingabe speichern (bei blur) ──
        if (inputAgentKey) {
            inputAgentKey.addEventListener('blur', async () => {
                if (!_agentKeyVisible) return; // Nur speichern wenn sichtbar (editierbar)
                const val = inputAgentKey.value.trim();
                if (val && val !== _agentKeyValue) {
                    _agentKeyValue = val;
                    try {
                        await fetch('/api/settings', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                            body: JSON.stringify({ agent_api_key: val })
                        });
                    } catch (err) {
                        console.error('Fehler beim Speichern des Agent API Keys:', err);
                    }
                }
            });
        }
    }

    // Auto-Login wenn Token vorhanden – serverseitig validieren
    if (token) {
        fetch('/api/verify-token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token }),
        }).then(r => r.json()).then(data => {
            if (data.valid) {
                currentUser = data.username || currentUser;
                showMainScreen();
            } else {
                showLoginScreen();
            }
        }).catch(() => {
            showLoginScreen();
        });
    }
    function setupModal() {
        const modal = document.getElementById('cert-modal');
        const btnOpen = document.getElementById('btn-cert-help');
        const btnClose = document.getElementById('btn-close-modal');
        const btnBannerHelp = document.getElementById('btn-banner-help');
        const securityIndicator = document.getElementById('security-indicator');

        if (!modal || !btnOpen) return;

        const openModal = () => modal.classList.add('open');
        const closeModal = () => modal.classList.remove('open');

        // Öffnen
        btnOpen.addEventListener('click', openModal);
        if (btnBannerHelp) btnBannerHelp.addEventListener('click', openModal);
        if (securityIndicator) securityIndicator.addEventListener('click', openModal);

        // Schließen
        btnClose.addEventListener('click', closeModal);

        // Schließen bei Klick außerhalb
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });

        // Tabs
        const tabs = document.querySelectorAll('.tab-btn');
        const contents = document.querySelectorAll('.tab-content');

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                // Aktiv-Status entfernen
                tabs.forEach(t => t.classList.remove('active'));
                contents.forEach(c => c.classList.remove('active'));

                // Neuen Tab aktivieren
                tab.classList.add('active');
                const targetId = `tab-${tab.dataset.tab}`;
                document.getElementById(targetId).classList.add('active');
            });
        });
    }

    function checkSecurity() {
        const banner = document.getElementById('security-banner');
        const bannerText = document.getElementById('security-banner-text');
        const indicator = document.getElementById('security-indicator');
        const btnClose = document.getElementById('btn-close-banner');

        const isHttps = window.location.protocol === 'https:';
        const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
        const certDismissed = localStorage.getItem('jarvis_cert_dismissed') === 'true';

        if (!isHttps && !isLocal) {
            // Unsichere Verbindung – Banner anzeigen
            banner.hidden = false;
            banner.style.display = 'block';
            bannerText.textContent = '⚠️ UNSICHERE VERBINDUNG! Bitte verwenden Sie HTTPS.';
            if (indicator) {
                indicator.className = 'security-badge';
                indicator.title = 'Kritisch: Keine Verschlüsselung';
            }

            // Cert-Modal beim ersten Seitenaufruf automatisch öffnen (wie Klick auf den Button)
            if (!certDismissed) {
                setTimeout(() => {
                    const certModal = document.getElementById('cert-modal');
                    if (certModal && !certModal.classList.contains('open')) {
                        certModal.classList.add('open');
                    }
                }, 600);
            }
        } else {
            banner.hidden = true;
            banner.style.display = 'none';
            if (indicator) {
                indicator.className = 'security-badge secure';
                indicator.title = 'Gesichert';
            }
        }

        if (btnClose) {
            btnClose.addEventListener('click', () => {
                banner.style.display = 'none';
                // Merken, dass der Nutzer den Hinweis gesehen und geschlossen hat
                localStorage.setItem('jarvis_cert_dismissed', 'true');
            });
        }
    }
    function setupSplitView() {
        const handle = document.getElementById('resize-handle');
        const leftPanel = document.getElementById('panel-left');
        const mainContent = document.querySelector('.main-content');

        if (!handle || !leftPanel || !mainContent) return;

        let isResizing = false;

        handle.addEventListener('mousedown', (e) => {
            isResizing = true;
            handle.classList.add('active');
            document.body.style.cursor = 'col-resize';

            // Iframe Pointer Events deaktivieren für flüssiges Dragging
            const iframe = document.getElementById('vnc-iframe');
            if (iframe) iframe.style.pointerEvents = 'none';

            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;

            const containerRect = mainContent.getBoundingClientRect();
            const newWidth = e.clientX - containerRect.left;

            // Min/Max Beschränkungen
            if (newWidth >= 300 && newWidth <= containerRect.width - 300) {
                const percentage = (newWidth / containerRect.width) * 100;
                leftPanel.style.width = `${percentage}%`;
                leftPanel.style.flex = 'none';
            }
        });

        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false;
                handle.classList.remove('active');
                document.body.style.cursor = '';

                // Iframe Pointer Events wieder aktivieren
                const iframe = document.getElementById('vnc-iframe');
                if (iframe) iframe.style.pointerEvents = '';
            }
        });
    }

    function setupDesktopToggle() {
        // Panels
        const rightPanel = document.getElementById('panel-right');
        const leftPanel = document.getElementById('panel-left');
        const handle = document.getElementById('resize-handle');

        if (!rightPanel || !leftPanel || !handle) return;

        // Weiche Transition für Breitenänderungen
        leftPanel.style.transition = 'width 0.3s ease, max-width 0.3s ease';
        rightPanel.style.transition = 'width 0.3s ease, max-width 0.3s ease';

        // Hilfsfunktion: Panel ausblenden, anderes auf 100%
        function hidePanel(panelToHide, panelToExpand) {
            panelToHide.style.display = 'none';
            handle.style.display = 'none';
            panelToExpand.style.display = 'flex';
            panelToExpand.style.flex = '1';
            panelToExpand.style.maxWidth = '100%';
            panelToExpand.style.width = '100%';
        }

        // Linkes Panel: Minimieren = linkes Panel verstecken, rechtes expandieren
        leftPanel.querySelector('.btn-win-minimize').addEventListener('click', () => {
            hidePanel(leftPanel, rightPanel);
        });

        // Linkes Panel: Maximieren = linkes Panel auf 100%, rechtes verstecken
        leftPanel.querySelector('.btn-win-maximize').addEventListener('click', () => {
            hidePanel(rightPanel, leftPanel);
        });

        // Rechtes Panel: Minimieren = rechtes Panel verstecken, linkes expandieren
        rightPanel.querySelector('.btn-win-minimize').addEventListener('click', () => {
            hidePanel(rightPanel, leftPanel);
        });

        // Rechtes Panel: Maximieren = rechtes Panel auf 100%, linkes verstecken
        rightPanel.querySelector('.btn-win-maximize').addEventListener('click', () => {
            hidePanel(leftPanel, rightPanel);
        });

        // Wiederherstellen (Split Screen): Beide Panels sichtbar, 50/50
        document.querySelectorAll('.btn-win-restore').forEach(btn => {
            btn.addEventListener('click', () => {
                leftPanel.style.display = 'flex';
                rightPanel.style.display = 'flex';
                handle.style.display = '';

                // Zurücksetzen auf Standardwerte
                leftPanel.style.maxWidth = '';
                leftPanel.style.width = '50%';
                rightPanel.style.flex = '1';
                rightPanel.style.maxWidth = '';
            });
        });
    }


    // ─── Init ───────────────────────────────────────────────────
    initParticles();
    setupSplitView();
    setupDesktopToggle();
    setupModal();
    setupSettings();
    checkSecurity();
})();

