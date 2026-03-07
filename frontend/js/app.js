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
    const speedSlider = document.getElementById('speed-slider');
    const speedValue = document.getElementById('speed-value');

    const cpuBarFill = document.getElementById('cpu-bar-fill');
    const cpuBarLabel = document.getElementById('cpu-bar-label');
    const connectionDot = document.getElementById('connection-dot');
    const agentStateBadge = document.getElementById('agent-state-badge');

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
            addLogEntry(data.message);
            if (data.state) {
                updateAgentState(data.state);
            }
        });

        ws.on('error', (data) => {
            addLogEntry(`❌ ${data.message || 'Fehler'}`, 'error');
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
        addLogEntry(`📝 Aufgabe: ${text.substring(0, 80)}…`, 'task');
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

        ws.send({ type: 'task', text, token });
        addLogEntry(`📝 Aufgabe: ${text}`, 'task');
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
    btnPause.addEventListener('click', () => {
        ws.send({ type: 'control', action: 'pause', token });
        btnPause.hidden = true;
        btnResume.hidden = false;
        btnResume.disabled = false;
    });

    btnResume.addEventListener('click', () => {
        ws.send({ type: 'control', action: 'resume', token });
        btnResume.hidden = true;
        btnPause.hidden = false;
        btnPause.disabled = false;
    });

    btnStop.addEventListener('click', () => {
        ws.send({ type: 'control', action: 'stop', token });
        btnPause.disabled = true;
        btnStop.disabled = true;
        btnResume.hidden = true;
        btnPause.hidden = false;
    });

    speedSlider.addEventListener('input', () => {
        const val = parseFloat(speedSlider.value);
        speedValue.textContent = val.toFixed(1) + 'x';
        ws.send({ type: 'control', action: 'speed', value: val, token });
    });

    btnClearLog.addEventListener('click', () => {
        logContainer.innerHTML = '';
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

    // ─── Log ────────────────────────────────────────────────────
    function addLogEntry(message, type = 'info') {
        if (type === 'system' || type === 'info') {
            // Bereinige Nachricht von Emojis für sauberere Aussprache
            const cleanMessage = message.replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '');
            speak(cleanMessage);
        }
        // Willkommens-Nachricht entfernen
        const welcome = logContainer.querySelector('.log-welcome');
        if (welcome) welcome.remove();

        const entry = document.createElement('div');
        entry.className = 'log-entry';

        const now = new Date();
        const time = now.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

        entry.innerHTML = `<span class="log-time">${time}</span>${escapeHtml(message)}`;

        logContainer.appendChild(entry);

        // Auto-Scroll nach unten
        logContainer.scrollTop = logContainer.scrollHeight;

        // Max 500 Einträge behalten
        while (logContainer.children.length > 500) {
            logContainer.removeChild(logContainer.firstChild);
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
        agentStateBadge.className = 'header-status';
        switch (state) {
            case 'running':
                agentStateBadge.textContent = 'Läuft';
                agentStateBadge.classList.add('running');
                btnPause.disabled = false;
                btnStop.disabled = false;
                break;
            case 'paused':
                agentStateBadge.textContent = 'Pausiert';
                agentStateBadge.classList.add('paused');
                break;
            case 'stopped':
                agentStateBadge.textContent = 'Gestoppt';
                agentStateBadge.classList.add('stopped');
                btnPause.disabled = true;
                btnStop.disabled = true;
                break;
            case 'idle':
                agentStateBadge.textContent = 'Bereit';
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

        const allSettingsTabs = [tabProfiles, tabSkills, tabWhatsApp, tabKnowledge, tabGoogle, tabVision];

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

        // ── Google-Tab-Button: nur sichtbar wenn 'google'-Skill aktiviert ──
        const googleTabBtn = document.getElementById('settings-tab-btn-google');

        window.updateGoogleTabVisibility = async function updateGoogleTabVisibility() {
            if (!googleTabBtn) return;
            try {
                const token = localStorage.getItem('jarvis_token') || '';
                const resp = await fetch('/api/skills', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const skills = data.skills || data || [];
                const googleSkill = Array.isArray(skills)
                    ? skills.find(s => s.dir_name === 'google')
                    : null;
                // Tab-Button anzeigen wenn Skill aktiviert, sonst verstecken
                const isEnabled = googleSkill && googleSkill.enabled;
                googleTabBtn.style.display = isEnabled ? '' : 'none';
                // Falls Google-Tab aktiv war und Skill nun deaktiviert → zu Profilen wechseln
                if (!isEnabled && tabGoogle && tabGoogle.classList.contains('active')) {
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

