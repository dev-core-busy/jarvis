/**
 * Jarvis Chat UI – WebSocket-basierte Chat-Oberfläche
 * Android-identisches Bubble-Design mit LDAP-Authentifizierung
 */
(() => {
    'use strict';

    // ─── State ──────────────────────────────────────────────────
    // SSO: jeden gueltigen Login-Token akzeptieren (kein Re-Login bei Seitenwechsel)
    let token = localStorage.getItem('jarvis_chat_token') || localStorage.getItem('jarvis_token') || localStorage.getItem('jarvis_uc_token') || '';
    if (token) localStorage.setItem('jarvis_chat_token', token);
    // Eindeutige Fenster-ID fuer Live-Sync (eigene Echo-Events ignorieren)
    const _clientId = 'chat-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    let _currentUser = localStorage.getItem('jarvis_chat_user') || '';
    let _isAdmin = false;   // jarvis/lokaler Admin -> Update-Pill/VNC/Multi-Agent sichtbar
    let ws = null;
    // Multi-Agent (nur Admin): Agent-Infos + aktive Ansicht + Sub-Agent-Streams
    let _activeAgentId = '_main';
    const _agentInfos = {};   // agent_id -> {label, state, is_sub_agent}
    const _subBubbles = {};   // agent_id -> Streaming-Bubble eines Sub-Agenten
    let reconnectAttempts = 0;
    const MAX_RECONNECT = 20;
    let agentRunning = false;
    let currentBotBubble = null;   // Streaming-Ziel
    let lastDate = '';

    // TTS-State
    let ttsEnabled = false;
    let _ttsAudio = null;
    let _ttsBuf = '';              // sammelt Bot-Text während Streaming

    // Feedback-State
    let _lastUserMsg  = '';        // letzte gesendete Benutzerfrage
    let _lastBotResp  = '';        // letzte vollständige Bot-Antwort
    let _lastBotCol   = null;      // .msg-col des letzten Bot-Bubbles
    let _lastStats    = '';        // Statistik-Text des letzten Bot-Bubbles

    // Verlauf-Persistenz
    const _HISTORY_KEY = 'jarvis_chat_history_v1';
    const _HISTORY_MAX = 120;
    let _chatHistory   = [];
    // Benutzereigene Chat-Sitzungen (Sidebar-Historie)
    let _sessions  = [];
    let _activeSid = null;
    const _CS_DEFAULT_TITLE = 'Neuer Chat';   // Backend-Standardtitel (chat_sessions._DEFAULT_TITLE)

    // ─── DOM ────────────────────────────────────────────────────
    const $ = id => document.getElementById(id);
    const loginScreen  = $('login-screen');
    const chatScreen   = $('chat-screen');
    const loginForm    = $('login-form');
    const loginUser    = $('login-user');
    const loginPass    = $('login-pass');
    const loginBtn     = $('btn-login');
    const loginError   = $('login-error');
    const eyeBtn       = $('eye-btn');
    const totpRow      = $('totp-row');
    const loginTotp    = $('login-totp');
    const messagesEl   = $('messages');
    const msgInput     = $('msg-input');
    const sendBtn      = $('btn-send');
    const stopBtn      = $('btn-stop');
    const btnAttach    = $('btn-attach');
    const attachInput  = $('attach-input');
    const attachBar    = $('attach-preview-bar');
    const attachToast  = $('attach-toast');
    const logoutBtn    = $('btn-logout');
    const statusDot    = $('status-dot');
    const totpSetupBtn = $('btn-totp-setup');
    const totpModal    = $('totp-modal');
    const btnTtsChat   = $('btn-tts-chat');
    const chatTtsVoice = $('chat-tts-voice');
    const chatTtsIconOn  = $('chat-tts-icon-on');
    const chatTtsIconOff = $('chat-tts-icon-off');
    const btnSelectMsgs  = $('btn-select-msgs');
    const msgSelectBar   = $('msg-select-bar');
    const msgSelectCount = $('msg-select-count');
    const btnMsgDelSel   = $('btn-msg-del-sel');
    const btnMsgSelCancel = $('btn-msg-sel-cancel');

    // ═════════════════════════════════════════════════════════════
    //  TTS
    // ═════════════════════════════════════════════════════════════

    function _updateTtsChatBtn() {
        if (!btnTtsChat) return;
        if (chatTtsIconOn)  chatTtsIconOn.style.display  = ttsEnabled ? '' : 'none';
        if (chatTtsIconOff) chatTtsIconOff.style.display = ttsEnabled ? 'none' : '';
        const voiceWrap = $('tts-voice-wrap');
        if (voiceWrap) voiceWrap.style.display = ttsEnabled ? '' : 'none';
        btnTtsChat.title = window.t(ttsEnabled ? 'chat.tts_on' : 'chat.tts_off');
    }

    async function _loadChatTtsVoices(savedVoice) {
        if (!chatTtsVoice) return;
        try {
            const resp = await fetch('/api/tts/voices', { headers: { 'Authorization': `Bearer ${token}` } });
            if (!resp.ok) return;
            const voices = await resp.json();
            chatTtsVoice.innerHTML = '<option value="">' + window.t('chat.voice_default') + '</option>';
            voices.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v.name;
                opt.textContent = v.display || v.name;
                chatTtsVoice.appendChild(opt);
            });
            if (savedVoice) chatTtsVoice.value = savedVoice;
        } catch (e) { /* ignore */ }
    }

    async function _saveChatTtsSettings() {
        // LocalStorage = primaere Persistenz (funktioniert fuer alle User, auch LDAP)
        // Backend = best-effort (klappt nur fuer lokale Admin-User wegen require_local_auth)
        try {
            localStorage.setItem('jarvis_chat_tts_enabled', ttsEnabled ? '1' : '0');
            localStorage.setItem('jarvis_chat_tts_voice', chatTtsVoice?.value || '');
        } catch (e) { /* ignore */ }
        try {
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ tts_enabled: ttsEnabled, tts_voice: chatTtsVoice?.value || '' })
            });
        } catch (e) { /* ignore */ }
    }

    function stopSpeak() {
        if (_ttsAudio) { _ttsAudio.pause(); _ttsAudio.src = ''; _ttsAudio = null; }
    }

    async function speak(text) {
        if (!ttsEnabled || !text) return;
        const clean = text.replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/gu, '').trim();
        if (!clean) return;
        stopSpeak();
        const voice = chatTtsVoice?.value || '';
        try {
            const resp = await fetch('/api/tts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ text: clean, voice })
            });
            if (!resp.ok) return;
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            _ttsAudio = new Audio(url);
            _ttsAudio.onended = () => { URL.revokeObjectURL(url); _ttsAudio = null; };
            _ttsAudio.play().catch(() => {});
        } catch (e) { console.warn('[TTS] Fehler:', e); }
    }

    if (btnTtsChat) {
        btnTtsChat.addEventListener('click', () => {
            ttsEnabled = !ttsEnabled;
            _updateTtsChatBtn();
            if (!ttsEnabled) stopSpeak();
            _saveChatTtsSettings();
        });
    }
    if (chatTtsVoice) {
        chatTtsVoice.addEventListener('change', () => _saveChatTtsSettings());
    }

    const btnTtsPreviewChat = $('btn-tts-preview-chat');
    if (btnTtsPreviewChat && chatTtsVoice) {
        btnTtsPreviewChat.addEventListener('click', async () => {
            const voice = chatTtsVoice.value;
            const previewText = window._lang === 'en'
                ? 'Hello, I am Jarvis, your autonomous AI assistant.'
                : 'Hallo, ich bin Jarvis, dein autonomer KI-Assistent.';
            btnTtsPreviewChat.disabled = true;
            btnTtsPreviewChat.innerHTML = '⏳';
            try {
                const resp = await fetch('/api/tts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                    body: JSON.stringify({ text: previewText, voice: voice || '' })
                });
                if (!resp.ok) throw new Error('TTS error');
                const blob = await resp.blob();
                const url = URL.createObjectURL(blob);
                const audio = new Audio(url);
                btnTtsPreviewChat.innerHTML = '🔊';
                audio.onended = () => { URL.revokeObjectURL(url); btnTtsPreviewChat.innerHTML = '▶'; btnTtsPreviewChat.disabled = false; };
                audio.onerror  = () => { URL.revokeObjectURL(url); btnTtsPreviewChat.innerHTML = '▶'; btnTtsPreviewChat.disabled = false; };
                await audio.play();
            } catch (e) {
                btnTtsPreviewChat.innerHTML = '▶';
                btnTtsPreviewChat.disabled = false;
            }
        });
    }

    // ═════════════════════════════════════════════════════════════
    //  LOGIN
    // ═════════════════════════════════════════════════════════════

    // ─── Eye-Button (SVG Auge / durchgestrichenes Auge) ───────
    const eyeSvgOpen = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
    const eyeSvgClosed = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
        <line x1="1" y1="1" x2="23" y2="23"/></svg>`;

    eyeBtn.addEventListener('click', () => {
        const show = loginPass.type === 'password';
        loginPass.type = show ? 'text' : 'password';
        eyeBtn.innerHTML = show ? eyeSvgClosed : eyeSvgOpen;
    });

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginError.textContent = '';
        loginBtn.disabled = true;
        loginBtn.textContent = window.t('chat.connecting');

        try {
            const payload = {
                username: loginUser.value.trim(),
                password: loginPass.value,
            };
            // TOTP-Code mitschicken falls Feld sichtbar
            if (!totpRow.classList.contains('hidden') && loginTotp.value.trim()) {
                payload.totp_code = loginTotp.value.trim();
            }

            const resp = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();

            if (data.success && data.token && data.account_blocked) {
                // Sicherheitsschicht: Konto gesperrt → nur Hinweis + Protokoll
                token = data.token;
                localStorage.setItem('jarvis_chat_token', token);
                if (window.SecurityIncidents) window.SecurityIncidents.showBlockedScreen(data.block_reason, data.block_incidents);
            } else if (data.success && data.token && data.must_change_password) {
                // Lokaler Erst-Login: Kennwortaenderung ist nur im Hauptfenster moeglich.
                loginError.textContent = window.t('chat.change_pw_main_first');
            } else if (data.success && data.token) {
                token = data.token;
                localStorage.setItem('jarvis_chat_token', token);
                _currentUser = data.username || loginUser.value.trim();
                localStorage.setItem('jarvis_chat_user', _currentUser);
                _isAdmin = !!data.is_admin;
                totpRow.classList.add('hidden');
                loginTotp.value = '';
                showChat();
            } else if (data.requires_totp) {
                // Passwort korrekt, 2FA-Code nötig
                totpRow.classList.remove('hidden');
                loginTotp.focus();
                if (data.error && data.error !== '2FA-Code erforderlich') {
                    loginError.textContent = data.error;
                }
            } else {
                loginError.textContent = data.error || window.t('chat.login_failed');
            }
        } catch (err) {
            loginError.textContent = window.t('chat.connection_error');
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = window.t('chat.submit');
        }
    });

    // ── Status-Dot = Erreichbarkeit des AKTIVEN LLM-Profils (wie Hauptseite) ──
    //    erreichbar -> gruen (.connected), sonst rot (.disconnected). Kein Doppelklick.
    let _llmStatusTimer = null;
    async function _checkLlmStatus() {
        if (!statusDot) return;
        try {
            const res = await fetch('/api/llm/active-status', {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            if (!res.ok) {
                statusDot.className = 'topbar-dot disconnected';
                statusDot.title = window.t('chat.llm_status_unavailable');
                return;
            }
            const d = await res.json();
            const reachable = (d.status === 'ok' || d.status === 'degraded');
            statusDot.className = 'topbar-dot ' + (reachable ? 'connected' : 'disconnected');
            const name = d.profile_name ? ' – ' + d.profile_name : '';
            if (d.status === 'ok')            statusDot.title = window.t('chat.llm_reachable') + name;
            else if (d.status === 'degraded') statusDot.title = window.t('chat.llm_reachable_no_model') + name;
            else                              statusDot.title = window.t('chat.llm_unreachable') + name;
        } catch (e) {
            statusDot.className = 'topbar-dot disconnected';
            statusDot.title = window.t('chat.llm_unreachable');
        }
    }
    function _startLlmStatusIndicator() {
        _checkLlmStatus();
        if (!_llmStatusTimer) _llmStatusTimer = setInterval(_checkLlmStatus, 30000);
    }

    function showChat() {
        loginScreen.classList.add('hidden');
        chatScreen.classList.remove('hidden');
        ensureKbFilter();
        // Angemeldeter Benutzer: als Tooltip am Logout-Button ('<user> abmelden')
        const _logoutBtn = $('btn-logout');
        if (_logoutBtn && _currentUser) _logoutBtn.title = window.t('chat.logout_user').replace('{u}', _currentUser);
        // Setup/Einstellungen-Button nur fuer Admins (direkt vor Logout)
        const _setupBtn = $('btn-settings');
        if (_setupBtn) {
            _setupBtn.style.display = _isAdmin ? '' : 'none';
            if (_isAdmin && !_setupBtn._wired) {
                _setupBtn._wired = true;
                _setupBtn.addEventListener('click', () => { try{sessionStorage.setItem('jarvis_settings_return','/chat');}catch(e){} window.location.href = '/settings'; });
            }
        }
        // Update-Pill nur fuer Admins (jarvis/lokaler Admin) einblenden + starten
        const _updWrap = $('chat-update-wrap');
        if (_isAdmin && _updWrap) {
            _updWrap.style.display = '';
            if (window.JarvisUpdateWidget) window.JarvisUpdateWidget.init();
        }
        // Desktop/VNC-Button: nach /portal verschoben (dort fuer alle Admins)
        // CPU-Auslastung fuer alle (Werte kommen via WS-Event 'cpu')
        const _cpuBar = $('cpu-bar');
        if (_cpuBar) _cpuBar.style.display = '';
        // LLM-Status-Pill fuer Admins klickbar -> Einstellungen (LLM-Profile)
        const _dot = $('status-dot');
        if (_isAdmin && _dot && !_dot._adminWired) {
            _dot._adminWired = true;
            _dot.style.cursor = 'pointer';
            _dot.title = (window.t ? window.t('chat.llm_settings') : 'LLM-Profile öffnen');
            _dot.addEventListener('click', () => { try{sessionStorage.setItem('jarvis_settings_return','/chat');}catch(e){} window.location.href = '/settings'; });
        }
        connectWS();
        _startLlmStatusIndicator();
        _initSessions();
        const _csNewBtn = $('cs-new');
        if (_csNewBtn && !_csNewBtn._wired) { _csNewBtn._wired = true; _csNewBtn.addEventListener('click', _newSession); }
        const _csCol = $('cs-collapse'); if (_csCol && !_csCol._wired) { _csCol._wired = true; _csCol.addEventListener('click', () => _setSidebarCollapsed(true)); }
        const _csExp = $('cs-expand');   if (_csExp && !_csExp._wired) { _csExp._wired = true; _csExp.addEventListener('click', () => _setSidebarCollapsed(false)); }
        // Zuletzt gewählten Einklapp-Zustand wiederherstellen
        try { _setSidebarCollapsed(localStorage.getItem('jarvis_chat_sidebar_collapsed') === '1'); } catch (e) {}
        // Auto-Focus nur auf Geraeten mit Maus/Tastatur: auf Touch-Geraeten oeffnet
        // focus() die Bildschirmtastatur und Chrome schiebt die Titelleiste aus dem Bild.
        if (!window.matchMedia('(pointer: coarse)').matches) msgInput.focus();
        _startContextIndicator();
        // TTS-Einstellungen laden: LocalStorage hat Vorrang vor Backend
        const lsEnabled = localStorage.getItem('jarvis_chat_tts_enabled');
        const lsVoice   = localStorage.getItem('jarvis_chat_tts_voice');
        if (lsEnabled !== null) {
            ttsEnabled = lsEnabled === '1';
            _updateTtsChatBtn();
            _loadChatTtsVoices(lsVoice || '');
        } else {
            // Fallback: Backend-Settings (klappt nur fuer lokale Admins)
            fetch('/api/settings', { headers: { 'Authorization': `Bearer ${token}` } })
                .then(r => r.json())
                .then(d => {
                    ttsEnabled = d.tts_enabled || false;
                    _updateTtsChatBtn();
                    _loadChatTtsVoices(d.tts_voice || '');
                }).catch(() => { _loadChatTtsVoices(''); });
        }
    }

    // ─── Kontext-Indikator ────────────────────────────────────────────
    let _ctxTimer = null;
    const _authHdr = (extra) => Object.assign({ 'Authorization': 'Bearer ' + token }, extra || {});

    async function _updateContextIndicator() {
        const el   = document.getElementById('ctx-indicator');
        const text = document.getElementById('ctx-indicator-text');
        if (!el) return;
        try {
            const q = _activeSid ? ('?session_id=' + encodeURIComponent(_activeSid)) : '';
            const r = await fetch('/api/context/stats' + q, { headers: _authHdr() });
            if (!r.ok) return;
            const d = await r.json();
            const n = d.history_entries || 0;
            if (n > 0) {
                el.style.display = 'flex';
                text.textContent = window.t('chat.ctx_label').replace('{n}', n).replace('{pct}', d.fills_pct ?? 0);
            } else {
                el.style.display = 'none';
            }
        } catch (e) { /* offline */ }
    }

    function _startContextIndicator() {
        _updateContextIndicator();
        _ctxTimer = setInterval(_updateContextIndicator, 8000);
    }

    window._clearUserContext = async function () {
        try {
            const r = await fetch('/api/context/clear', {
                method: 'POST', headers: _authHdr({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ session_id: _activeSid || '' })
            });
            const d = await r.json();
            if (d.ok) document.getElementById('ctx-indicator').style.display = 'none';
        } catch (e) { /* ignore */ }
    };

    function logout() {
        token = '';
        // Global abmelden (SSO): alle Seiten-Token entfernen
        localStorage.removeItem('jarvis_chat_token');
        localStorage.removeItem('jarvis_token');
        localStorage.removeItem('jarvis_uc_token');
        if (ws) { ws.close(); ws = null; }
        chatScreen.classList.add('hidden');
        loginScreen.classList.remove('hidden');
        loginPass.value = '';
        loginError.textContent = '';
    }

    logoutBtn.addEventListener('click', logout);

    // ═════════════════════════════════════════════════════════════
    //  WEBSOCKET
    // ═════════════════════════════════════════════════════════════

    function connectWS() {
        if (ws && ws.readyState <= 1) return;

        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}//${location.host}/ws`);

        // #status-dot zeigt den LLM-Profil-Status (s. _checkLlmStatus), nicht den WS-Status.

        ws.onopen = () => {
            reconnectAttempts = 0;
            // Beim Server registrieren (setzt Benutzer der WS) → Live-Sync-Events empfangen
            wsSend({ type: 'hello' });
        };

        ws.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                handleMessage(msg);
            } catch { /* ignore non-JSON */ }
        };

        ws.onclose = () => {
            scheduleReconnect();
        };

        ws.onerror = () => {};
    }

    function scheduleReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT) return;
        reconnectAttempts++;
        const delay = 2000 * Math.min(reconnectAttempts, 5);
        setTimeout(connectWS, delay);
    }

    function wsSend(obj) {
        if (!ws || ws.readyState !== 1) return;
        ws.send(JSON.stringify({ ...obj, token }));
    }

    // ═════════════════════════════════════════════════════════════
    //  NACHRICHT SENDEN
    // ═════════════════════════════════════════════════════════════

    // ─── Datei-Anhänge ──────────────────────────────────────────
    let _pendingAttachments = [];

    // Wissensgruppen-Filter (aufklappbare Checkbox-Liste in der Eingabeleiste)
    let _kbFilter = null;
    function ensureKbFilter() {
        if (_kbFilter || !window.KbGroupFilter) return;
        const slot = document.getElementById('kb-filter-slot');
        if (!slot) return;
        _kbFilter = window.KbGroupFilter.mount({ anchor: slot, place: 'append', direction: 'up', key: 'chat' });
    }

    const _SUPPORTED = new Set([
        'image/jpeg','image/jpg','image/png','image/gif','image/webp','image/bmp',
        'audio/wav','audio/mp3','audio/mpeg','audio/ogg','audio/webm','audio/aac','audio/flac','audio/m4a','audio/x-m4a',
        'video/mp4','video/webm','video/ogg','video/quicktime','video/x-msvideo','video/mpeg',
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',      // xlsx
        'application/vnd.ms-excel',                                               // xls
        'application/vnd.oasis.opendocument.spreadsheet',                         // ods
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',// docx
        'application/msword',                                                     // doc
        'application/vnd.oasis.opendocument.text',                                // odt
        'application/vnd.openxmlformats-officedocument.presentationml.presentation', // pptx
        'application/vnd.ms-powerpoint',                                          // ppt
        'text/plain','text/markdown','text/csv','application/json',
        'application/xml','text/xml',                                             // xml
        'application/zip','application/x-zip-compressed',                         // zip
    ]);
    // Endungs-Fallback (Office-Dateien melden per Drag&Drop oft leeren MIME-Typ)
    const _SUPPORTED_EXT = new Set([
        'pdf','txt','md','rst','csv','json','xml','zip',
        'docx','doc','odt','rtf','xlsx','xls','ods','pptx','ppt','odp',
        'jpg','jpeg','png','gif','bmp','tif','tiff','webp',
        'mp3','m4a','wav','ogg','aac','flac',
        'mp4','mov','mkv','avi','webm','mpeg',
    ]);

    let _toastTimer = null;
    function showToast(msg) {
        if (!attachToast) return;
        attachToast.textContent = msg;
        attachToast.classList.add('show');
        clearTimeout(_toastTimer);
        _toastTimer = setTimeout(() => attachToast.classList.remove('show'), 4000);
    }

    function renderPreviews() {
        if (!attachBar) return;
        attachBar.innerHTML = '';
        if (_pendingAttachments.length === 0) {
            attachBar.style.display = 'none';
            if (btnAttach) btnAttach.classList.remove('has-files');
            sendBtn.disabled = !msgInput.value.trim();
            return;
        }
        attachBar.style.display = 'flex';
        if (btnAttach) btnAttach.classList.add('has-files');
        sendBtn.disabled = false;
        _pendingAttachments.forEach((att, idx) => {
            const chip = document.createElement('div');
            chip.className = 'attach-chip';
            if (att.type === 'image') {
                const img = document.createElement('img');
                img.src = `data:${att.mime_type};base64,${att.data}`;
                chip.appendChild(img);
            } else {
                const ico = document.createElement('span');
                ico.className = 'attach-chip-icon';
                const _ext = (att.name.split('.').pop() || '').toLowerCase();
                let icon = '📎';
                if (att.type === 'audio') icon = '🎵';
                else if (att.type === 'pdf') icon = '📄';
                else if (att.type === 'video') icon = '🎬';
                else if (['xlsx','xls','ods','csv','tsv'].includes(_ext)) icon = '📊';
                else if (['docx','doc','odt','rtf'].includes(_ext)) icon = '📝';
                else if (['pptx','ppt','odp'].includes(_ext)) icon = '📑';
                else if (['txt','md','rst','json'].includes(_ext)) icon = '📄';
                ico.textContent = icon;
                chip.appendChild(ico);
            }
            const nm = document.createElement('span');
            nm.className = 'attach-chip-name';
            nm.textContent = att.name.length > 16 ? att.name.slice(0,14)+'…' : att.name;
            nm.title = att.name;
            chip.appendChild(nm);
            const rm = document.createElement('button');
            rm.className = 'attach-chip-remove';
            rm.textContent = '×';
            rm.type = 'button';
            rm.addEventListener('click', () => { _pendingAttachments.splice(idx,1); renderPreviews(); });
            chip.appendChild(rm);
            attachBar.appendChild(chip);
        });
    }

    async function addFiles(files) {
        const unsupported = [];
        for (const file of Array.from(files)) {
            const mime = (file.type || '').toLowerCase();
            const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
            const okMime = _SUPPORTED.has(mime) || mime.startsWith('image/') || mime.startsWith('audio/') || mime.startsWith('video/');
            if (!okMime && !_SUPPORTED_EXT.has(ext)) {
                unsupported.push(ext ? '.'+ext.toUpperCase() : (mime||'?')); continue;
            }
            if (_pendingAttachments.length >= 5) { showToast(window.t('chat.max_files')); break; }
            let type = 'file';
            if (mime.startsWith('image/') || ['jpg','jpeg','png','gif','bmp','tif','tiff','webp'].includes(ext)) type = 'image';
            else if (mime.startsWith('audio/') || ['mp3','m4a','wav','ogg','aac','flac'].includes(ext)) type = 'audio';
            else if (mime.startsWith('video/') || ['mp4','mov','mkv','avi','webm','mpeg'].includes(ext)) type = 'video';
            else if (mime === 'application/pdf' || ext === 'pdf') type = 'pdf';
            else type = 'document';
            try {
                const b64 = await new Promise((res,rej) => {
                    const r = new FileReader();
                    r.onload = e => res(e.target.result.split(',')[1]);
                    r.onerror = rej;
                    r.readAsDataURL(file);
                });
                _pendingAttachments.push({ name: file.name, mime_type: mime, data: b64, type });
            } catch(e) { showToast(window.t('chat.file_read_error').replace('{f}', file.name)); }
        }
        if (unsupported.length > 0) {
            const fmts = [...new Set(unsupported)].join(', ');
            showToast(window.t('chat.format_unsupported').replace('{f}', fmts));
        }
        renderPreviews();
    }

    if (btnAttach) btnAttach.addEventListener('click', () => attachInput && attachInput.click());
    if (attachInput) {
        attachInput.addEventListener('change', async () => { await addFiles(attachInput.files); attachInput.value = ''; });
    }

    // Drag & Drop auf Nachrichten-Bereich
    if (messagesEl) {
        messagesEl.addEventListener('dragover', e => { e.preventDefault(); messagesEl.classList.add('drag-over'); });
        messagesEl.addEventListener('dragleave', e => { if (!messagesEl.contains(e.relatedTarget)) messagesEl.classList.remove('drag-over'); });
        messagesEl.addEventListener('drop', async e => {
            e.preventDefault(); messagesEl.classList.remove('drag-over');
            if (e.dataTransfer && e.dataTransfer.files.length > 0) await addFiles(e.dataTransfer.files);
        });
    }

    function sendMessage() {
        const text = msgInput.value.trim();
        if (!text && _pendingAttachments.length === 0) return;
        const finalText = text || window.t('chat.analyze_attachments');

        _lastUserMsg = finalText;
        _lastBotResp = '';
        _lastBotCol  = null;
        _lastStats   = '';

        const userBubble = addBubble(finalText, 'user', null, _activeAgentId);
        if (_pendingAttachments.length > 0) {
            // Snapshot der Anhänge für Rendering (vor dem Leeren von _pendingAttachments)
            const attSnap = _pendingAttachments.map(a => ({ name: a.name, mime_type: a.mime_type, data: a.data }));
            _renderAttachments(userBubble, { attachments: attSnap });
        }

        // Benutzernachricht im Verlauf speichern (nur Text + Hinweis, kein base64)
        const _attIcon = m => { m = (m || '').toLowerCase(); return m.startsWith('image/') ? '🖼️' : m === 'application/pdf' ? '📄' : m.startsWith('audio/') ? '🎵' : m.startsWith('video/') ? '🎬' : '📎'; };
        const attNote = _pendingAttachments.length > 0
            ? ' [' + _pendingAttachments.map(a => `${_attIcon(a.mime_type)} ${a.name || window.t('chat.file')}`).join(', ') + ']'
            : '';
        _chatHistory.push({ role: 'user', text: finalText + attNote, time: timeStr(), date: _currentDateStr(), ts: Date.now() });
        _saveHistory();
        _syncAppend(_chatHistory[_chatHistory.length - 1]);
        const msg = { type: 'task', text: finalText, lang: window._lang || 'de' };
        if (_activeSid) msg.session_id = _activeSid;
        // Multi-Agent: an aktiven Sub-Agenten richten (sonst Hauptagent)
        if (_activeAgentId && _activeAgentId !== '_main') msg.agent_id = _activeAgentId;
        if (_pendingAttachments.length > 0) {
            msg.attachments = _pendingAttachments.map(a => ({ name: a.name, mime_type: a.mime_type, data: a.data }));
        }
        // Wissensgruppen-Filter: null = alle (Feld weglassen), [] = keine, [ids] = nur diese
        if (_kbFilter) {
            const _sel = _kbFilter.getSelection();
            if (_sel !== null) msg.kb_groups = _sel;
        }
        wsSend(msg);

        msgInput.value = '';
        msgInput.style.height = '';
        _pendingAttachments = [];
        renderPreviews();
        sendBtn.disabled = true;
    }

    sendBtn.addEventListener('click', sendMessage);

    msgInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    msgInput.addEventListener('input', () => {
        sendBtn.disabled = !msgInput.value.trim() && _pendingAttachments.length === 0;
        // Auto-resize
        msgInput.style.height = '';
        msgInput.style.height = Math.min(msgInput.scrollHeight, 120) + 'px';
    });

    // Stop-Button
    stopBtn.addEventListener('click', () => {
        wsSend({ type: 'control', action: 'stop' });
    });

    // ═════════════════════════════════════════════════════════════
    //  NACHRICHTEN VERARBEITEN
    // ═════════════════════════════════════════════════════════════

    function handleMessage(msg) {
        switch (msg.type) {
            case 'status':
                handleStatus(msg);
                break;

            case 'agent_event':
                handleAgentEvent(msg);
                break;

            case 'shared_history_append':
                _applyRemoteAppend(msg.message, msg.origin);
                break;

            case 'llm_stats':
                appendStats(msg);
                break;

            case 'error':
                if (msg.message === 'Nicht autorisiert') {
                    logout();
                }
                break;

            case 'session_invalid':
                // Anmeldeberechtigung entzogen → abmelden, danach greift die
                // Login-Sperre ('Keine Anmeldeberechtigung').
                if (msg.message) alert(msg.message);
                logout();
                break;

            case 'security_blocked':
                if (window.SecurityIncidents) window.SecurityIncidents.fetchAndShowBlocked();
                break;

            case 'cpu':
                updateCPU(msg.value);
                break;

            case 'pong':
                break; // ignorieren
        }
    }

    // CPU-Bar (Admin) aus WS-Event aktualisieren
    function updateCPU(percent) {
        const fill = $('cpu-bar-fill');
        const label = $('cpu-bar-label');
        if (!fill || !label) return;
        const pct = Math.max(0, Math.min(100, Number(percent) || 0));
        fill.style.width = pct + '%';
        fill.style.backgroundPosition = pct + '% 0';
        label.textContent = 'CPU: ' + Math.round(pct) + '%';
    }

    function handleStatus(msg) {
        const text = msg.message || '';
        if (!text) return;

        // Status-Nachrichten erkennen: beginnen immer mit einem bekannten Emoji
        const STATUS_PREFIXES = ['🚀','🔧','📋','⏳','💬','💻','✅','⚠️','❌','🧠','⏸','▶','⏹','📊','🧩','🔎'];
        const isStatus = STATUS_PREFIXES.some(p => text.startsWith(p));

        // Multi-Agent: Sub-Agent-Ausgabe in eine eigene (getaggte) Bubble lenken
        const _aid = msg.agent_id || '_main';
        const _isSub = _aid !== '_main' && _agentInfos[_aid] && _agentInfos[_aid].is_sub_agent;

        if (msg.highlight && !isStatus) {
            if (_isSub) {
                _appendSubBubble(_aid, text);   // Sub-Agent: getaggt, kein TTS
            } else {
                // Echter LLM-Antwort-Text (highlight=true, kein Status-Emoji) → Bot-Bubble + TTS
                _ttsBuf += (text + ' ');
                appendToBotBubble(text);
            }
        } else if (isStatus) {
            if (text.startsWith('⏸') || text.startsWith('▶') || text.startsWith('⏹')) {
                addStatusLine(text);
            } else {
                // Laufende Aktivität (Start / LLM-Warten / Tool / Fortschritt) live anzeigen
                _setActivity(text);
            }
        }
    }

    // ── Live-Aktivitäts-/Fortschrittszeile (Spinner + aktueller Status) ──
    let _activityEl = null;
    function _setActivity(text) {
        if (!messagesEl) return;
        if (!_activityEl) {
            _activityEl = document.createElement('div');
            _activityEl.className = 'chat-activity';
            _activityEl.innerHTML = '<span class="chat-activity-spinner"></span><span class="chat-activity-text"></span>';
        }
        const t = _activityEl.querySelector('.chat-activity-text');
        if (t) t.textContent = text;
        messagesEl.appendChild(_activityEl);   // immer ans Ende
        scrollToBottom();
    }
    function _clearActivity() {
        if (_activityEl && _activityEl.parentNode) _activityEl.parentNode.removeChild(_activityEl);
        _activityEl = null;
    }

    // Streaming-Bubble eines Sub-Agenten (getaggt; nur sichtbar wenn aktiv)
    function _appendSubBubble(agentId, text) {
        let b = _subBubbles[agentId];
        if (!b) {
            b = addBubble(text, 'bot', null, agentId);
            b._rawText = text;
            _subBubbles[agentId] = b;
        } else {
            b._rawText = (b._rawText || '') + '\n' + text;
            b.innerHTML = renderMarkdown(b._rawText.trim());
            if ((b.closest('.msg-row')?.dataset.agentId || '_main') === _activeAgentId) scrollToBottom();
        }
    }

    function handleAgentEvent(msg) {
        const ev = msg.event;
        const agent = msg.agent || {};
        const isSub = !!agent.is_sub_agent;

        if (ev === 'started' && !isSub) {
            // Hauptagent: neuer Lauf -> Agent-Infos/Sub-Streams zuruecksetzen
            agentRunning = true;
            _ttsBuf = '';
            stopBtn.classList.remove('hidden');
            currentBotBubble = null;
            Object.keys(_agentInfos).forEach(k => delete _agentInfos[k]);
            Object.keys(_subBubbles).forEach(k => delete _subBubbles[k]);
            _activeAgentId = '_main';
            if (agent.agent_id) _agentInfos[agent.agent_id] = { label: agent.label || 'Jarvis', state: 'running', is_sub_agent: false };
        } else if (ev === 'finished' && !isSub) {
            agentRunning = false;
            stopBtn.classList.add('hidden');
            _clearActivity();
            removeStreamingDots();
            currentBotBubble = null;
            _updateContextIndicator();
            const toSpeak = _ttsBuf.trim();
            _ttsBuf = '';
            if (toSpeak) speak(toSpeak);
            if (_lastBotResp) {
                _chatHistory.push({ role: 'bot', text: _lastBotResp, time: timeStr(), date: _currentDateStr(), stats: _lastStats, ts: Date.now() });
                _saveHistory();
                _syncAppend(_chatHistory[_chatHistory.length - 1]);
                _maybeRefreshTitle();   // Auto-Benennung nach der ersten Antwort in die Sidebar uebernehmen
            }
            if (_lastBotCol && _lastBotResp) {
                _appendFeedbackRow(_lastBotCol, _lastUserMsg, _lastBotResp);
                _lastBotCol = null;
            }
        }

        // ── Sub-Agent-Lebenszyklus (Multi-Agent-Sidebar, nur Admin sichtbar) ──
        if ((ev === 'started' || ev === 'spawned') && isSub) {
            _agentInfos[agent.agent_id] = { label: agent.label || agent.agent_id, state: 'running', is_sub_agent: true };
        }
        if (ev === 'finished' && isSub && _agentInfos[agent.agent_id]) {
            _agentInfos[agent.agent_id].state = 'idle';
            if (_activeAgentId === agent.agent_id) _switchToAgent('_main');
            const rid = agent.agent_id;
            setTimeout(() => {
                if (_agentInfos[rid] && _agentInfos[rid].state !== 'paused') { delete _agentInfos[rid]; _renderAgentPanel(); }
            }, 8000);
        }
        if (ev === 'paused' && isSub && _agentInfos[agent.agent_id]) _agentInfos[agent.agent_id].state = 'paused';

        // Gesamtliste aus dem Event uebernehmen (falls mitgeliefert)
        (msg.agents || []).forEach(a => { _agentInfos[a.agent_id] = { label: a.label, state: a.state, is_sub_agent: a.is_sub_agent }; });

        _renderAgentPanel();
    }

    // Wechselt die angezeigte Agenten-Ansicht (filtert Nachrichten per data-agent-id)
    function _switchToAgent(agentId) {
        _activeAgentId = agentId;
        messagesEl.querySelectorAll('.msg-row').forEach(r => {
            const a = r.dataset.agentId || '_main';
            r.style.display = (a === agentId) ? '' : 'none';
        });
        _renderAgentPanel();
        scrollToBottom();
    }

    // Rendert das Multi-Agent-Panel (nur Admin, nur wenn Sub-Agenten existieren)
    function _renderAgentPanel() {
        const panel = $('agent-panel'), list = $('agent-panel-list');
        if (!panel || !list) return;
        const subs = Object.keys(_agentInfos).filter(id => _agentInfos[id].is_sub_agent);
        if (!_isAdmin || subs.length === 0) { panel.style.display = 'none'; return; }
        panel.style.display = '';
        const ids = ['_main'].concat(subs);
        const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
        list.innerHTML = ids.map(id => {
            const info = id === '_main'
                ? { label: 'Jarvis', state: agentRunning ? 'running' : 'idle', is_sub_agent: false }
                : _agentInfos[id];
            if (!info) return '';
            const dot = info.state === 'running' ? 'var(--warning)' : info.state === 'paused' ? 'var(--accent)' : 'var(--success)';
            const act = id === _activeAgentId;
            return '<div class="agent-card" data-agent-id="' + esc(id) + '" style="display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:8px;cursor:pointer;margin-bottom:4px;'
                + (act ? 'background:rgba(var(--accent-rgb,99,102,241),0.18);' : '') + '">'
                + '<span style="width:8px;height:8px;border-radius:50%;background:' + dot + ';flex-shrink:0;"></span>'
                + '<span style="font-size:0.82rem;color:var(--text-primary,#f8fafc);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + esc(info.label || id) + (info.is_sub_agent ? '' : '') + '</span>'
                + '</div>';
        }).join('');
        list.querySelectorAll('.agent-card').forEach(c => c.addEventListener('click', () => _switchToAgent(c.dataset.agentId)));
    }

    // ═════════════════════════════════════════════════════════════
    //  BUBBLES RENDERN
    // ═════════════════════════════════════════════════════════════

    function addBubble(text, role, customTime, agentId) {
        removeWelcome();
        maybeAddDateSep();

        const row = document.createElement('div');
        row.className = `msg-row ${role}`;
        // Multi-Agent: Zeile dem Agenten zuordnen; nicht aktive Agenten ausblenden
        const _aid = agentId || '_main';
        row.dataset.agentId = _aid;
        if (_aid !== _activeAgentId) row.style.display = 'none';

        // Timestamp
        const timeEl = document.createElement('div');
        timeEl.className = 'msg-time';

        // Bubble
        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';
        bubble.innerHTML = role === 'user' ? escapeHtml(text) : renderMarkdown(text);

        // Edit-Button für User-Bubbles
        if (role === 'user') {
            const editBtn = document.createElement('button');
            editBtn.type = 'button';
            editBtn.className = 'msg-edit-btn';
            editBtn.title = (window.t ? window.t('bubble.edit_msg') : 'Nachricht bearbeiten');
            editBtn.setAttribute('aria-label', editBtn.title);
            editBtn.textContent = '✏';
            editBtn.addEventListener('click', () => _editUserBubble(row, bubble));
            timeEl.appendChild(editBtn);
            const timeSpan = document.createElement('span');
            timeSpan.textContent = customTime || timeStr();
            timeEl.appendChild(timeSpan);
            row.dataset.rawText = text;
        } else {
            timeEl.textContent = customTime || timeStr();
        }

        const col = document.createElement('div');
        col.appendChild(timeEl);
        col.appendChild(bubble);

        if (role === 'bot') {
            const avatar = document.createElement('div');
            avatar.className = 'msg-avatar';
            avatar.textContent = 'J';
            if (window.brandAvatar) window.brandAvatar(avatar);
            row.appendChild(avatar);
            col.appendChild(_botActions(bubble));
        }

        row.appendChild(col);
        messagesEl.appendChild(row);
        scrollToBottom();

        // ── Kontextmenue (Rechtsklick / Long-Press) ────────────────
        if (window.JarvisChatLib && window.JarvisChatLib.setupBubbleContextMenu) {
            window.JarvisChatLib.setupBubbleContextMenu(row, () => _buildBubbleCtxItems(row, bubble, role));
        }

        // Im Auswahlmodus neue Bubble direkt mit Checkbox versehen
        if (_selCtl && _selCtl.isActive()) _selCtl.addCheckboxToRow(row);

        return bubble;
    }

    // Dezente Aktions-Buttons unter Bot-Bubbles: Kopieren + PDF-Export.
    function _botActions(bubble) {
        const bar = document.createElement('div');
        bar.className = 'bubble-actions';
        // In Zwischenablage kopieren
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'bubble-act-btn';
        copyBtn.title = (window.t ? window.t('bubble.copy_clip') : 'In Zwischenablage kopieren');
        copyBtn.setAttribute('aria-label', copyBtn.title);
        copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
        copyBtn.addEventListener('click', () => {
            const t = bubble.textContent || '';
            const done = () => { copyBtn.classList.add('ok'); setTimeout(() => copyBtn.classList.remove('ok'), 1200); };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(t).then(done).catch(() => { window.JarvisChatLib && window.JarvisChatLib.copyTextToClipboard && window.JarvisChatLib.copyTextToClipboard(t); done(); });
            } else { window.JarvisChatLib && window.JarvisChatLib.copyTextToClipboard && window.JarvisChatLib.copyTextToClipboard(t); done(); }
        });
        bar.appendChild(copyBtn);
        // Als PDF exportieren (Druckfenster -> "Als PDF speichern")
        const pdfBtn = document.createElement('button');
        pdfBtn.type = 'button';
        pdfBtn.className = 'bubble-act-btn';
        pdfBtn.title = (window.t ? window.t('bubble.export_pdf') : 'Als PDF exportieren');
        pdfBtn.setAttribute('aria-label', pdfBtn.title);
        pdfBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><polyline points="9 15 12 18 15 15"/></svg>';
        pdfBtn.addEventListener('click', () => _exportBubblePdf(bubble));
        bar.appendChild(pdfBtn);
        return bar;
    }

    // PDF-Export ohne externe Libs: Druckfenster mit gerendertem Bubble-Inhalt.
    function _exportBubblePdf(bubble) {
        const w = window.open('', '_blank');
        if (!w) { alert(window.t ? window.t('bubble.popup_blocked') : 'Bitte Pop-ups erlauben, um als PDF zu exportieren.'); return; }
        const title = (window.t ? window.t('chat.title') : 'Chat');
        w.document.write(
            '<!doctype html><html><head><meta charset="utf-8"><title>' + title + '</title>'
            + '<style>body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.55;color:#111;max-width:820px;margin:0 auto;padding:28px;}'
            + 'pre{background:#f4f4f5;border-radius:8px;padding:12px;overflow:auto;white-space:pre-wrap;word-break:break-word;}'
            + 'code{background:#f4f4f5;border-radius:4px;padding:1px 4px;} pre code{padding:0;background:none;}'
            + 'img,video{max-width:100%;} table{border-collapse:collapse;width:100%;} td,th{border:1px solid #ccc;padding:5px 9px;text-align:left;}'
            + 'a{color:#4338ca;word-break:break-all;} h1,h2,h3{line-height:1.25;}</style></head><body>'
            + (bubble.innerHTML || '') + '</body></html>'
        );
        w.document.close();
        w.focus();
        setTimeout(() => { try { w.print(); } catch (e) {} }, 350);
    }

    // Kontextmenue-Items (Bearbeiten/Kopieren/Loeschen)
    function _buildBubbleCtxItems(row, bubble, role) {
        const items = [];
        const txt = (row.dataset && row.dataset.rawText) ||
                    (bubble && (bubble.textContent || '')) || '';
        if (role === 'user') {
            items.push({
                label: (window.t ? window.t('bubble.ctx.edit') : 'Bearbeiten'), icon: '✏',
                onClick: () => _editUserBubble(row, bubble),
            });
        }
        items.push({
            label: (window.t ? window.t('bubble.ctx.copy') : 'Text kopieren'), icon: '⧉',
            onClick: () => window.JarvisChatLib?.copyTextToClipboard?.(txt),
        });
        items.push({
            label: (window.t ? window.t('bubble.ctx.delete') : 'Löschen'), icon: '🗑', danger: true,
            onClick: () => _selCtl.startSelectionDelete(row),
        });
        return items;
    }

    // Loescht NUR die angeklickte Bubble (analog Android-App-Verhalten).
    // Nachfolgende Antworten/Dialoge bleiben erhalten. Backend-Agent-History
    // wird nicht angetastet (User-Anker/Tool-Call-Verkettung bleibt intakt).
    function _deleteBubble(row, role) {
        if (!row || !row.parentNode) return;
        if (_editingRow && _editingRow !== row) {
            try { _restoreBubble(_editingRow.querySelector('.msg-bubble'), _editingRow); } catch(_) {}
        }

        const isUser = (role === 'user');
        const promptTxt = window.t
            ? (isUser ? window.t('bubble.del_user_q') : window.t('bubble.del_bot_a'))
            : (isUser ? 'Diese Frage löschen?' : 'Diese Antwort löschen?');
        if (!confirm(promptTxt)) return;

        const rowSel = isUser ? '.msg-row.user' : '.msg-row.bot';
        const sameRoleRows = messagesEl.querySelectorAll(rowSel);
        const roleIndex    = Array.from(sameRoleRows).indexOf(row);

        // Streaming-State leeren, falls die aktive Bot-Bubble entfernt wird
        if (!isUser && row.contains(currentBotBubble)) {
            currentBotBubble = null;
            _lastBotCol = null; _lastBotResp = ''; _lastStats = '';
        }
        if (_editingRow === row) _editingRow = null;

        row.parentNode.removeChild(row);

        if (Array.isArray(_chatHistory) && roleIndex >= 0) {
            const wantRoles = isUser ? ['user'] : ['bot', 'assistant'];
            let seen = 0;
            for (let i = 0; i < _chatHistory.length; i++) {
                const e = _chatHistory[i];
                if (e && wantRoles.includes(e.role)) {
                    if (seen === roleIndex) { _chatHistory.splice(i, 1); break; }
                    seen++;
                }
            }
            _saveHistory();
            _syncReplace();
        }
    }

    // ─── Mehrfachauswahl: Nachrichten per Checkbox loeschen ──────
    //  Lebenszyklus in chatlib.js (createSelectionController). Hier nur
    //  die seitenspezifische Loeschlogik (lokale History + DOM).
    const _selCtl = window.JarvisChatLib.createSelectionController({
        container: messagesEl,
        rowSelector: '.msg-row',
        checkboxClass: 'msg-check',
        bar: msgSelectBar,
        countEl: msgSelectCount,
        delBtn: btnMsgDelSel,
        toggleBtn: btnSelectMsgs,
        cancelBtn: btnMsgSelCancel,
        onEnter: () => {
            if (_editingRow) { try { _restoreBubble(_editingRow.querySelector('.msg-bubble'), _editingRow); } catch(_) {} }
        },
        onDelete: (checked) => {
            const userRows = Array.from(messagesEl.querySelectorAll('.msg-row.user'));
            const botRows  = Array.from(messagesEl.querySelectorAll('.msg-row.bot'));
            const delUser = new Set();
            const delBot  = new Set();
            for (const row of checked) {
                if (row.classList.contains('user')) {
                    const i = userRows.indexOf(row);
                    if (i >= 0) delUser.add(i);
                } else {
                    const i = botRows.indexOf(row);
                    if (i >= 0) delBot.add(i);
                    if (row.contains(currentBotBubble)) {
                        currentBotBubble = null; _lastBotCol = null; _lastBotResp = ''; _lastStats = '';
                    }
                }
                if (_editingRow === row) _editingRow = null;
            }

            if (Array.isArray(_chatHistory)) {
                let uSeen = 0, bSeen = 0;
                _chatHistory = _chatHistory.filter(e => {
                    if (!e) return false;
                    if (e.role === 'user') { const keep = !delUser.has(uSeen); uSeen++; return keep; }
                    if (e.role === 'bot' || e.role === 'assistant') { const keep = !delBot.has(bSeen); bSeen++; return keep; }
                    return true;
                });
                _saveHistory();
                _syncReplace();
            }

            checked.forEach(row => { if (row.parentNode) row.parentNode.removeChild(row); });

            // Verwaiste Datums-Separatoren entfernen
            messagesEl.querySelectorAll('.date-sep').forEach(sep => {
                let n = sep.nextElementSibling;
                while (n && !n.classList.contains('msg-row')) {
                    if (n.classList.contains('date-sep')) { n = null; break; }
                    n = n.nextElementSibling;
                }
                if (!n) sep.remove();
            });
        },
    });

    // ─── Edit-Modus für User-Bubbles (delegiert an chatlib.js) ───
    let _editingRow = null;

    function _editUserBubble(row, bubble) {
        if (_editingRow) return;
        if (!row || !bubble) return;
        if (!(window.JarvisChatLib && window.JarvisChatLib.enterEditMode)) {
            alert(window.t('chat.editlib_missing'));
            return;
        }
        const ok = window.JarvisChatLib.enterEditMode(row, bubble, {
            editBtnSelector: '.msg-edit-btn',
            areaClass:    'msg-edit-area',
            actionsClass: 'msg-edit-actions',
            saveClass:    'msg-edit-save',
            cancelClass:  'msg-edit-cancel',
            isBlocked: () => agentRunning,
            blockMessage: (window.t ? window.t('bubble.block_running') : 'Bitte stoppe zuerst die laufende Aufgabe.'),
            onCommit: (newText) => _submitEdit(row, bubble, newText),
            onCancel: () => { _editingRow = null; },
        });
        if (ok) _editingRow = row;
    }

    function _restoreBubble(bubble, row) {
        if (window.JarvisChatLib && window.JarvisChatLib.exitEditMode) {
            window.JarvisChatLib.exitEditMode(row, bubble, { editBtnSelector: '.msg-edit-btn' });
        }
        _editingRow = null;
    }

    function _submitEdit(row, bubble, newText) {
        const allUserRows = messagesEl.querySelectorAll('.msg-row.user');
        const userIndex = Array.from(allUserRows).indexOf(row);
        if (userIndex < 0) { _restoreBubble(bubble, row); return; }

        // DOM: alles nach dieser Row entfernen
        if (window.JarvisChatLib && window.JarvisChatLib.removeRowsAfter) {
            window.JarvisChatLib.removeRowsAfter(row);
        }

        // Streaming-State zurücksetzen
        currentBotBubble = null;
        _lastBotCol = null;
        _lastBotResp = '';
        _lastStats = '';

        // _chatHistory trimmen + Text aktualisieren (in place)
        if (window.JarvisChatLib && window.JarvisChatLib.truncateHistoryToUserIndex) {
            window.JarvisChatLib.truncateHistoryToUserIndex(
                _chatHistory, userIndex, newText,
                { timeStr: timeStr(), dateStr: _currentDateStr() }
            );
        }
        _saveHistory();
        _syncReplace();

        // Bubble visuell zurücksetzen mit neuem Text
        bubble.classList.remove('editing');
        bubble.innerHTML = escapeHtml(newText);
        delete bubble.dataset.origHtml;
        row.dataset.rawText = newText;
        const editBtn = row.querySelector('.msg-edit-btn');
        if (editBtn) editBtn.style.visibility = '';
        const timeSpan = row.querySelector('.msg-time span');
        if (timeSpan) timeSpan.textContent = timeStr();
        _editingRow = null;

        // WS-Task mit truncate-Hint
        _lastUserMsg = newText;
        _lastBotResp = '';
        _lastBotCol  = null;
        _lastStats   = '';
        wsSend({
            type: 'task',
            text: newText,
            lang: window._lang || 'de',
            truncate_user_msg_index: userIndex,
            session_id: _activeSid || undefined,
        });
    }

    function appendToBotBubble(text) {
        _clearActivity();   // finale Antwort kommt → Aktivitätszeile entfernen
        if (!currentBotBubble) {
            currentBotBubble = addBubble(text, 'bot');
            _lastBotCol = currentBotBubble.parentElement; // .msg-col merken
            addStreamingDots();
        } else {
            currentBotBubble.innerHTML = renderMarkdown(
                (currentBotBubble._rawText || '') + '\n' + text
            );
        }
        currentBotBubble._rawText = (currentBotBubble._rawText || '') + '\n' + text;
        _lastBotResp = currentBotBubble._rawText.trim();
        scrollToBottom();
    }

    function appendStats(msg) {
        if (!currentBotBubble) return;
        removeStreamingDots();

        const stats = document.createElement('div');
        stats.className = 'msg-stats';
        const secNum = (msg.duration_ms || 0) / 1000;
        const dur = secNum.toFixed(1);
        const tokens = msg.total_tokens || 0;
        const outTok = msg.output_tokens || 0;
        const steps = msg.steps || 0;
        let s = `${dur}s · ${tokens} Tokens`;
        if (outTok > 0 && secNum > 0) {
            const tps = outTok / secNum;
            s += ` · ${tps >= 100 ? tps.toFixed(0) : tps.toFixed(1)} tok/s`;
        }
        s += ' · ' + window.t('chat.n_steps').replace('{n}', steps);
        _lastStats = s;
        stats.textContent = _lastStats;
        currentBotBubble.parentElement.appendChild(stats);
        scrollToBottom();
    }

    function addStatusLine(text) {
        const el = document.createElement('div');
        el.className = 'msg-status';
        el.textContent = text;
        messagesEl.appendChild(el);
        scrollToBottom();
    }

    // ─── Streaming Dots ─────────────────────────────────────────
    function addStreamingDots() {
        removeStreamingDots();
        const dots = document.createElement('div');
        dots.className = 'streaming-dots';
        dots.id = 'streaming-dots';
        dots.textContent = '●●●';
        messagesEl.appendChild(dots);
        scrollToBottom();
    }

    function removeStreamingDots() {
        const el = $('streaming-dots');
        if (el) el.remove();
    }

    // ─── Date Separator ─────────────────────────────────────────
    function _dateLabel(str) {
        const fmt = d => d.toLocaleDateString('de-DE', { day:'2-digit', month:'2-digit', year:'numeric' });
        const todayStr = fmt(new Date());
        const yesterStr = fmt(new Date(Date.now() - 86400000));
        if (str === todayStr)   return window.t('chat.today');
        if (str === yesterStr)  return window.t('chat.yesterday');
        return str;
    }

    function maybeAddDateSep() {
        const today = new Date().toLocaleDateString('de-DE', {
            day: '2-digit', month: '2-digit', year: 'numeric'
        });
        if (today === lastDate) return;
        lastDate = today;

        const sep = document.createElement('div');
        sep.className = 'date-sep';
        sep.innerHTML = `<span>${_dateLabel(today)}</span>`;
        messagesEl.appendChild(sep);
    }

    // ─── Helpers (delegieren an chatlib.js) ─────────────────────
    function timeStr() {
        return (window.JarvisChatLib && window.JarvisChatLib.timeStr)
            ? window.JarvisChatLib.timeStr()
            : new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    }

    function scrollToBottom() {
        requestAnimationFrame(() => {
            messagesEl.scrollTop = messagesEl.scrollHeight;
        });
    }

    function removeWelcome() {
        const w = messagesEl.querySelector('.welcome-msg');
        if (w) w.remove();
    }

    // ─── Datei-Anhang-Rendering (Galerie, Lightbox, Kontextmenü) ─

    function _dataUrl(att) {
        return `data:${att.mime_type};base64,${att.data}`;
    }

    // Lightbox
    let _lbAtts = [], _lbIdx = 0;
    function openLightbox(atts, idx) {
        _lbAtts = atts; _lbIdx = idx;
        _lbUpdate();
        document.getElementById('uc-lightbox')?.classList.add('open');
    }
    function closeLightbox() {
        document.getElementById('uc-lightbox')?.classList.remove('open');
    }
    function _lbUpdate() {
        const img     = document.getElementById('uc-lb-img');
        const counter = document.getElementById('uc-lb-counter');
        const prev    = document.getElementById('uc-lb-prev');
        const next    = document.getElementById('uc-lb-next');
        if (!img) return;
        const att = _lbAtts[_lbIdx];
        img.src = _dataUrl(att);
        img.alt = att.name || '';
        if (counter) counter.textContent = _lbAtts.length > 1 ? `${_lbIdx + 1} / ${_lbAtts.length}` : '';
        if (prev)    prev.style.display  = _lbAtts.length > 1 ? '' : 'none';
        if (next)    next.style.display  = _lbAtts.length > 1 ? '' : 'none';
    }
    document.addEventListener('keydown', e => {
        const lb = document.getElementById('uc-lightbox');
        if (!lb || !lb.classList.contains('open')) return;
        if (e.key === 'Escape') closeLightbox();
        if (e.key === 'ArrowLeft')  { _lbIdx = (_lbIdx - 1 + _lbAtts.length) % _lbAtts.length; _lbUpdate(); }
        if (e.key === 'ArrowRight') { _lbIdx = (_lbIdx + 1) % _lbAtts.length; _lbUpdate(); }
    });
    (function initLightbox() {
        document.getElementById('uc-lb-close')?.addEventListener('click', closeLightbox);
        document.getElementById('uc-lb-prev')?.addEventListener('click', () => {
            _lbIdx = (_lbIdx - 1 + _lbAtts.length) % _lbAtts.length; _lbUpdate();
        });
        document.getElementById('uc-lb-next')?.addEventListener('click', () => {
            _lbIdx = (_lbIdx + 1) % _lbAtts.length; _lbUpdate();
        });
        document.getElementById('uc-lb-save')?.addEventListener('click', () => {
            const att = _lbAtts[_lbIdx];
            Object.assign(document.createElement('a'), { href: _dataUrl(att), download: att.name || 'bild' }).click();
        });
        document.getElementById('uc-lightbox')?.addEventListener('click', e => {
            if (e.target === document.getElementById('uc-lightbox')) closeLightbox();
        });
    })();

    // Kontextmenü
    let _ctxAtt = null;
    function showCtxMenu(e, att) {
        e.preventDefault(); e.stopPropagation();
        _ctxAtt = att;
        const menu = document.getElementById('uc-ctx-menu');
        if (!menu) return;
        const x = Math.min(e.clientX, window.innerWidth - 180);
        const y = Math.min(e.clientY, window.innerHeight - 60);
        menu.style.left = x + 'px';
        menu.style.top  = y + 'px';
        menu.classList.add('open');
    }
    function hideCtxMenu() { document.getElementById('uc-ctx-menu')?.classList.remove('open'); }
    document.addEventListener('click', hideCtxMenu);
    document.getElementById('uc-ctx-save-btn')?.addEventListener('click', () => {
        if (!_ctxAtt) return;
        Object.assign(document.createElement('a'), { href: _dataUrl(_ctxAtt), download: _ctxAtt.name || 'datei' }).click();
        hideCtxMenu();
    });

    // Long-Press (Mobile)
    function addLongPress(el, callback) {
        let timer = null;
        el.addEventListener('touchstart', e => { timer = setTimeout(() => callback(e.touches[0]), 600); }, { passive: true });
        el.addEventListener('touchend', () => clearTimeout(timer));
        el.addEventListener('touchmove', () => clearTimeout(timer));
    }

    // Anhang-Rendering
    function _renderAttachments(bubble, msg) {
        const atts = msg.attachments || [];
        if (atts.length === 0) return;
        const imgAtts   = atts.filter(a => (a.mime_type || '').startsWith('image/'));
        const otherAtts = atts.filter(a => !(a.mime_type || '').startsWith('image/'));

        if (imgAtts.length > 0) {
            const MAX = 4;
            const gallery = document.createElement('div');
            gallery.className = 'uc-img-gallery uc-ig-' + Math.min(imgAtts.length, MAX);
            gallery.style.marginTop = bubble.innerHTML.trim() ? '6px' : '0';
            imgAtts.slice(0, MAX).forEach((att, i) => {
                const cell = document.createElement('div');
                cell.className = 'uc-ig-cell';
                const img = document.createElement('img');
                img.src = _dataUrl(att);
                img.alt = att.name || window.t('chat.image');
                img.loading = 'lazy';
                cell.appendChild(img);
                if (i === MAX - 1 && imgAtts.length > MAX) {
                    const ov = document.createElement('div');
                    ov.className = 'uc-ig-more';
                    ov.textContent = '+' + (imgAtts.length - MAX + 1);
                    cell.appendChild(ov);
                }
                cell.addEventListener('click', e => { e.stopPropagation(); openLightbox(imgAtts, i); });
                cell.addEventListener('contextmenu', e => showCtxMenu(e, att));
                addLongPress(cell, e => showCtxMenu(e, att));
                gallery.appendChild(cell);
            });
            bubble.appendChild(gallery);
        }
        for (const att of otherAtts) {
            bubble.appendChild(_renderFileChip(att));
        }
    }

    function _renderFileChip(att) {
        const mime = (att.mime_type || '').toLowerCase();
        const src  = _dataUrl(att);
        const wrap = document.createElement('div');
        wrap.className = 'uc-file-chip';
        wrap.style.marginTop = '4px';

        if (mime.startsWith('audio/')) {
            wrap.classList.add('audio');
            wrap.innerHTML = `<div class="uc-fc-icon">🎵</div>
                <div class="uc-fc-info">
                    <span class="uc-fc-name" title="${escapeHtml(att.name||'')}">${escapeHtml(att.name||'Audio')}</span>
                    <span class="uc-fc-badge">Audio</span>
                </div>`;
            const player = document.createElement('audio');
            player.controls = true; player.src = src; player.className = 'uc-fc-player';
            wrap.appendChild(player);
        } else if (mime.startsWith('video/')) {
            wrap.classList.add('video');
            wrap.innerHTML = `<div class="uc-fc-icon">🎬</div>
                <div class="uc-fc-info">
                    <span class="uc-fc-name" title="${escapeHtml(att.name||'')}">${escapeHtml(att.name||'Video')}</span>
                    <span class="uc-fc-badge">Video</span>
                </div>`;
            const player = document.createElement('video');
            player.controls = true; player.src = src; player.className = 'uc-fc-player'; player.style.maxWidth = '220px';
            wrap.appendChild(player);
        } else {
            const isPdf = mime === 'application/pdf';
            wrap.classList.add(isPdf ? 'pdf' : 'other');
            const icon  = isPdf ? '📄' : '📎';
            const badge = isPdf ? 'PDF' : att.name?.split('.').pop()?.toUpperCase() || 'Datei';
            wrap.innerHTML = `<div class="uc-fc-icon">${icon}</div>
                <div class="uc-fc-info" style="flex:1;min-width:0;">
                    <span class="uc-fc-name" title="${escapeHtml(att.name||'')}">${escapeHtml(att.name||window.t('chat.file'))}</span>
                    <span class="uc-fc-badge">${escapeHtml(badge)}</span>
                </div>
                <a class="uc-fc-dl" href="${src}" download="${escapeHtml(att.name||'datei')}" title="${escapeHtml(window.t('chat.download'))}" onclick="event.stopPropagation()">⬇</a>`;
            wrap.addEventListener('contextmenu', e => showCtxMenu(e, att));
            addLongPress(wrap, e => showCtxMenu(e, att));
        }
        return wrap;
    }

    // ─── Verlauf-Persistenz (delegiert an chatlib.js) ───────────
    function _currentDateStr() {
        return (window.JarvisChatLib && window.JarvisChatLib.currentDateStr)
            ? window.JarvisChatLib.currentDateStr()
            : new Date().toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
    }

    function _saveHistory() {
        if (_chatHistory.length > _HISTORY_MAX) _chatHistory = _chatHistory.slice(-_HISTORY_MAX);
        if (window.JarvisChatLib && window.JarvisChatLib.saveHistory) {
            window.JarvisChatLib.saveHistory(_HISTORY_KEY, _chatHistory, _HISTORY_MAX);
        } else {
            try { localStorage.setItem(_HISTORY_KEY, JSON.stringify(_chatHistory)); }
            catch(e) { /* QuotaExceeded */ }
        }
    }

    function _loadHistory() {
        if (window.JarvisChatLib && window.JarvisChatLib.loadHistory) {
            return window.JarvisChatLib.loadHistory(_HISTORY_KEY);
        }
        try {
            const raw = localStorage.getItem(_HISTORY_KEY);
            return raw ? (JSON.parse(raw) || []) : [];
        } catch(e) { return []; }
    }

    function _addHistoryBubble(entry) {
        const row = document.createElement('div');
        row.className = `msg-row ${entry.role}`;

        const timeEl = document.createElement('div');
        timeEl.className = 'msg-time';

        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';
        bubble.innerHTML = entry.role === 'user'
            ? escapeHtml(entry.text)
            : renderMarkdown(entry.text);

        // Edit-Button für User-Bubbles (auch nach Reload nutzbar)
        if (entry.role === 'user') {
            const editBtn = document.createElement('button');
            editBtn.type = 'button';
            editBtn.className = 'msg-edit-btn';
            editBtn.title = (window.t ? window.t('bubble.edit_msg') : 'Nachricht bearbeiten');
            editBtn.setAttribute('aria-label', editBtn.title);
            editBtn.textContent = '✏';
            editBtn.addEventListener('click', () => _editUserBubble(row, bubble));
            timeEl.appendChild(editBtn);
            const timeSpan = document.createElement('span');
            timeSpan.textContent = entry.time || '';
            timeEl.appendChild(timeSpan);
            row.dataset.rawText = entry.text;
        } else {
            timeEl.textContent = entry.time || '';
        }

        const col = document.createElement('div');
        col.appendChild(timeEl);
        col.appendChild(bubble);

        if (entry.role === 'bot') {
            const avatar = document.createElement('div');
            avatar.className = 'msg-avatar';
            avatar.textContent = 'J';
            if (window.brandAvatar) window.brandAvatar(avatar);
            row.appendChild(avatar);

            if (entry.stats) {
                const stats = document.createElement('div');
                stats.className = 'msg-stats';
                stats.textContent = entry.stats;
                col.appendChild(stats);
            }
            col.appendChild(_botActions(bubble));
        }

        row.appendChild(col);
        messagesEl.appendChild(row);

        // Kontextmenue auch fuer restaurierte Bubbles aktivieren (vorher fehlte
        // dieser Hook, weshalb Rechtsklick im /chat-Popup nur Browser-Menue zeigte).
        if (window.JarvisChatLib && window.JarvisChatLib.setupBubbleContextMenu) {
            window.JarvisChatLib.setupBubbleContextMenu(row, () => _buildBubbleCtxItems(row, bubble, entry.role));
        }
    }

    // ── Chat-Sitzungen: Persistenz je aktiver Sitzung (statt geteilter History) ──
    function _csHeaders(extra) { return Object.assign({ 'Authorization': 'Bearer ' + token }, extra || {}); }
    function _sidKey() { return 'jarvis_chat_sid_' + (_currentUser || 'anon'); }
    // Transkript der aktiven Sitzung serverseitig speichern (nach jedem Turn/Edit)
    function _persistSession() {
        if (!_activeSid || !token) return;
        fetch('/api/chat/sessions/' + encodeURIComponent(_activeSid) + '/transcript', {
            method: 'PUT', headers: _csHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ messages: _chatHistory })
        }).catch(() => {});
    }
    // Kompatible Namen zu den bisherigen Aufrufstellen -> alle schreiben die Sitzung
    function _syncAppend(_msg) { _persistSession(); }
    function _syncReplace() { _persistSession(); }

    async function _csList() {
        try { const r = await fetch('/api/chat/sessions', { headers: _csHeaders() }); const d = await r.json(); return (d && d.sessions) || []; }
        catch (e) { return []; }
    }
    async function _csCreate(title) {
        try {
            const r = await fetch('/api/chat/sessions', { method: 'POST', headers: _csHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ title: title || '' }) });
            const d = await r.json(); return d && d.session;
        } catch (e) { return null; }
    }
    async function _csTranscript(sid) {
        try { const r = await fetch('/api/chat/sessions/' + encodeURIComponent(sid), { headers: _csHeaders() }); if (!r.ok) return []; const d = await r.json(); return (d && d.transcript) || []; }
        catch (e) { return []; }
    }

    function _renderSidebar() {
        const list = document.getElementById('cs-list');
        if (!list) return;
        if (!_sessions.length) { list.innerHTML = '<div class="cs-empty">' + escapeHtml(window.t('chat.no_sessions')) + '</div>'; return; }
        list.innerHTML = '';
        _sessions.forEach(s => {
            const item = document.createElement('div');
            item.className = 'cs-item' + (s.id === _activeSid ? ' active' : '');
            const title = document.createElement('span');
            title.className = 'cs-title'; title.textContent = s.title || window.t('chat.untitled');
            const ren = document.createElement('button'); ren.type = 'button'; ren.className = 'cs-act cs-ren'; ren.textContent = '✎'; ren.title = window.t('chat.rename');
            const del = document.createElement('button'); del.type = 'button'; del.className = 'cs-act cs-del'; del.textContent = '×'; del.title = window.t('chat.delete');
            item.appendChild(title); item.appendChild(ren); item.appendChild(del);
            item.addEventListener('click', (e) => { if (e.target === ren || e.target === del) return; _switchSession(s.id); });
            ren.addEventListener('click', (e) => { e.stopPropagation(); _renameSession(s); });
            del.addEventListener('click', (e) => { e.stopPropagation(); _deleteSession(s); });
            list.appendChild(item);
        });
    }

    async function _initSessions() {
        _sessions = await _csList();
        let want = null; try { want = localStorage.getItem(_sidKey()); } catch (e) {}
        let active = _sessions.find(s => s.id === want) || _sessions[0] || null;
        if (!active) { active = await _csCreate(''); if (active) _sessions.unshift(active); }
        _activeSid = active ? active.id : null;
        if (_activeSid) { try { localStorage.setItem(_sidKey(), _activeSid); } catch (e) {} }
        _renderSidebar();
        await _restoreHistory();        _updateContextIndicator();
    }

    async function _switchSession(sid) {
        if (sid === _activeSid) return;
        _persistSession();
        _activeSid = sid;
        try { localStorage.setItem(_sidKey(), sid); } catch (e) {}
        _renderSidebar();
        await _restoreHistory();        _updateContextIndicator();
    }

    async function _newSession() {
        _persistSession();
        const s = await _csCreate('');
        if (!s) return;
        _sessions.unshift(s);
        _activeSid = s.id;
        try { localStorage.setItem(_sidKey(), s.id); } catch (e) {}
        _renderSidebar();
        await _restoreHistory();        _updateContextIndicator();
        if (typeof msgInput !== 'undefined' && msgInput) msgInput.focus();
    }

    async function _renameSession(s) {
        const nn = window.prompt(window.t('chat.rename_prompt'), s.title || '');
        if (nn == null) return;
        const title = nn.trim(); if (!title) return;
        try {
            const r = await fetch('/api/chat/sessions/' + encodeURIComponent(s.id), { method: 'PATCH', headers: _csHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ title }) });
            const d = await r.json();
            if (d && d.ok && d.session) { s.title = d.session.title; _renderSidebar(); }
        } catch (e) {}
    }

    async function _deleteSession(s) {
        if (!window.confirm(window.t('chat.delete_confirm').replace('{name}', s.title || ''))) return;
        try { await fetch('/api/chat/sessions/' + encodeURIComponent(s.id), { method: 'DELETE', headers: _csHeaders() }); } catch (e) {}
        _sessions = _sessions.filter(x => x.id !== s.id);
        if (_activeSid === s.id) {
            _activeSid = _sessions[0] ? _sessions[0].id : null;
            if (!_activeSid) { const ns = await _csCreate(''); if (ns) { _sessions.unshift(ns); _activeSid = ns.id; } }
            try { localStorage.setItem(_sidKey(), _activeSid || ''); } catch (e) {}
            _renderSidebar();
            await _restoreHistory();            _updateContextIndicator();
        } else {
            _renderSidebar();
        }
    }
    // Nach der ersten Antwort den vom Backend automatisch gesetzten Titel
    // (erster Nachrichtentext) in die Sidebar uebernehmen.
    async function _maybeRefreshTitle() {
        const s = _sessions.find(x => x.id === _activeSid);
        if (!s || (s.title && s.title !== _CS_DEFAULT_TITLE)) return;
        const list = await _csList();
        const ns = list.find(x => x.id === _activeSid);
        if (ns && ns.title && ns.title !== s.title) { s.title = ns.title; _renderSidebar(); }
    }
    // Verlaufs-Sidebar ein-/ausklappen (nach links); Zustand pro Browser gemerkt.
    function _setSidebarCollapsed(collapsed) {
        const screen = document.getElementById('chat-screen');
        if (screen) screen.classList.toggle('sidebar-collapsed', !!collapsed);
        try { localStorage.setItem('jarvis_chat_sidebar_collapsed', collapsed ? '1' : '0'); } catch (e) {}
    }
    window._chatNewSession = _newSession;

    // Live-Sync: vom anderen Fenster (gleicher Benutzer) angehaengte Nachricht
    // sofort darstellen, ohne sie erneut ans Backend zu senden.
    function _applyRemoteAppend(entry, origin) {
        if (origin && origin === _clientId) return;       // eigenes Echo ignorieren
        if (!entry || (entry.role !== 'user' && entry.role !== 'bot')) return;
        if (entry.ts && _chatHistory.some(m => m && m.ts === entry.ts)) return;  // Dedup
        removeWelcome();
        maybeAddDateSep();
        _addHistoryBubble(entry);
        _chatHistory.push(entry);
        scrollToBottom();
    }
    async function _restoreHistory() {
        // Sichtbares Transkript der AKTIVEN Sitzung laden und die Anzeige ersetzen.
        messagesEl.innerHTML = '';
        currentBotBubble = null;
        _chatHistory = _activeSid ? await _csTranscript(_activeSid) : [];
        if (_chatHistory.length === 0) {
            // Willkommensnachricht (wie im Ausgangszustand)
            messagesEl.innerHTML = '<div class="welcome-msg">'
                + '<p data-i18n="chat.greeting">Hallo! Ich bin Jarvis.</p>'
                + '<p class="welcome-sub" data-i18n="chat.greeting_sub">Wie kann ich dir helfen?</p></div>';
            if (window.applyLang) window.applyLang();
            return;
        }

        removeWelcome();
        let restoredDate = '';

        for (const entry of _chatHistory) {
            if (entry.date && entry.date !== restoredDate) {
                restoredDate = entry.date;
                const sep = document.createElement('div');
                sep.className = 'date-sep';
                sep.innerHTML = `<span>${_dateLabel(entry.date)}</span>`;
                messagesEl.appendChild(sep);
            }

            if (entry.role === 'user' || entry.role === 'bot') {
                _addHistoryBubble(entry);
            }
        }

        // lastDate mit dem letzten wiederhergestellten Datum synchronisieren,
        // damit maybeAddDateSep() keinen doppelten Separator erzeugt
        if (restoredDate) lastDate = restoredDate;

        // Visueller Trenner zwischen alten und neuen Nachrichten
        const divider = document.createElement('div');
        divider.className = 'date-sep';
        divider.style.opacity = '0.45';
        divider.innerHTML = `<span>── ${escapeHtml(window.t('chat.new_session'))} ──</span>`;
        messagesEl.appendChild(divider);

        scrollToBottom();
    }

    function escapeHtml(str) {
        if (window.JarvisChatLib && window.JarvisChatLib.escapeHtml) {
            return window.JarvisChatLib.escapeHtml(str);
        }
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    /** Markdown → HTML, delegiert an chatlib.js (einheitlicher Renderer). */
    function renderMarkdown(text) {
        if (window.JarvisChatLib && window.JarvisChatLib.renderMarkdown) {
            return window.JarvisChatLib.renderMarkdown(text);
        }
        // Fallback (sollte nie greifen, da chat.html chatlib.js vor chat.js lädt)
        return escapeHtml(text).replace(/\n/g, '<br>');
    }

    // ═════════════════════════════════════════════════════════════
    //  THEME TOGGLE (Light/Dark)
    // ═════════════════════════════════════════════════════════════

    function applyTheme(light) {
        document.body.classList.toggle('light', light);
        // Beide Button-Icon-Paare synchron aktualisieren
        [['theme-icon-moon', 'theme-icon-sun'],
         ['login-theme-icon-moon', 'login-theme-icon-sun']].forEach(([moonId, sunId]) => {
            const moon = $(moonId), sun = $(sunId);
            if (moon) moon.classList.toggle('hidden', light);
            if (sun)  sun.classList.toggle('hidden', !light);
        });
        localStorage.setItem('jarvis_theme', light ? 'light' : 'dark');
        // Branding ueber den Theme-Wechsel informieren (Logo/Farben neu waehlen)
        try { document.dispatchEvent(new CustomEvent('jarvis:themechange', { detail: { light: light } })); } catch (e) {}
    }

    // Gespeicherte Präferenz laden (seitenuebergreifender Schluessel)
    const savedTheme = localStorage.getItem('jarvis_theme');
    if (savedTheme === 'light') applyTheme(true);

    // Beide Theme-Buttons registrieren
    ['btn-theme', 'btn-theme-login'].forEach(id => {
        const btn = $(id);
        if (btn) btn.addEventListener('click', () => {
            applyTheme(!document.body.classList.contains('light'));
        });
    });

    // ═════════════════════════════════════════════════════════════
    //  INIT
    // ═════════════════════════════════════════════════════════════

    // ═════════════════════════════════════════════════════════════
    //  2FA SETUP MODAL
    // ═════════════════════════════════════════════════════════════

    // 2FA nach /portal verschoben – Block nur aktiv, falls Elemente vorhanden.
    if (totpSetupBtn && totpModal) {
    const totpModalError = $('totp-modal-error');
    const totpActive     = $('totp-active');
    const totpSetupFlow  = $('totp-setup-flow');

    totpSetupBtn.addEventListener('click', async () => {
        totpModalError.textContent = '';
        totpActive.classList.add('hidden');
        totpSetupFlow.classList.add('hidden');

        // Status abfragen
        try {
            const resp = await fetch('/api/auth/totp/status', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            const data = await resp.json();

            if (data.enabled) {
                totpActive.classList.remove('hidden');
            } else {
                // Setup starten: QR-Code holen
                const setup = await fetch('/api/auth/totp/setup', {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const sdata = await setup.json();

                $('totp-qr').innerHTML = `<img src="${sdata.qr_code}" alt="QR-Code">`;
                $('totp-secret-code').textContent = sdata.secret;
                $('totp-verify-code').value = '';
                totpSetupFlow.classList.remove('hidden');
            }
        } catch {
            totpModalError.textContent = window.t('chat.connection_error');
        }

        totpModal.classList.remove('hidden');
    });

    // Modal schließen
    $('btn-totp-close').addEventListener('click', () => {
        totpModal.classList.add('hidden');
    });
    totpModal.addEventListener('click', (e) => {
        if (e.target === totpModal) totpModal.classList.add('hidden');
    });

    // 2FA aktivieren (Code verifizieren)
    $('btn-totp-verify').addEventListener('click', async () => {
        const code = $('totp-verify-code').value.trim();
        if (!code) return;
        totpModalError.textContent = '';

        try {
            const resp = await fetch('/api/auth/totp/verify', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ code }),
            });
            const data = await resp.json();
            if (data.success) {
                totpModal.classList.add('hidden');
                addStatusLine('✅ ' + window.t('chat.totp_enabled'));
            } else {
                totpModalError.textContent = data.error || window.t('chat.verify_failed');
            }
        } catch {
            totpModalError.textContent = window.t('chat.connection_error');
        }
    });

    // 2FA deaktivieren
    $('btn-totp-disable').addEventListener('click', async () => {
        const password = $('totp-disable-pass').value;
        if (!password) return;
        totpModalError.textContent = '';

        try {
            const resp = await fetch('/api/auth/totp/disable', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ password }),
            });
            const data = await resp.json();
            if (data.success) {
                totpModal.classList.add('hidden');
                $('totp-disable-pass').value = '';
                addStatusLine('🔓 ' + window.t('chat.totp_disabled'));
            } else {
                totpModalError.textContent = data.error || window.t('chat.disable_failed');
            }
        } catch {
            totpModalError.textContent = window.t('chat.connection_error');
        }
    });
    }  // Ende 2FA-Guard

    // ═════════════════════════════════════════════════════════════
    //  INIT
    // ═════════════════════════════════════════════════════════════

    // ═════════════════════════════════════════════════════════════
    //  SSL-ZERTIFIKAT MODAL
    // ═════════════════════════════════════════════════════════════

    const certModal = $('cert-modal');
    $('btn-cert')?.addEventListener('click', () => certModal.classList.remove('hidden'));
    $('btn-cert-close')?.addEventListener('click', () => certModal.classList.add('hidden'));
    certModal?.addEventListener('click', (e) => {
        if (e.target === certModal) certModal.classList.add('hidden');
    });

    // ── SSL-/Verbindungs-Sicherheit: Warnbanner + Badge (wie im Hauptfenster) ──
    function _openCertModal() { if (certModal) certModal.classList.remove('hidden'); }
    function checkSecurity() {
        const banner = $('security-banner');
        const bannerText = $('security-banner-text');
        const indicator = $('security-indicator');
        const isHttps = location.protocol === 'https:';
        const isLocal = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
        const certDismissed = localStorage.getItem('jarvis_cert_dismissed') === 'true';

        if (!isHttps && !isLocal) {
            if (banner) {
                banner.hidden = false;
                banner.style.display = 'block';
                if (bannerText) bannerText.textContent = (window.t ? window.t('panel.security_banner') : 'Verbindung unsicher');
            }
            if (indicator) {
                indicator.className = 'security-badge';
                indicator.title = (window.t ? window.t('panel.security_critical') : 'Kritisch: Keine Verschlüsselung');
            }
            // Beim ersten unsicheren Aufruf das Zertifikat-Modal automatisch öffnen
            if (!certDismissed) setTimeout(_openCertModal, 600);
        } else {
            if (banner) { banner.hidden = true; banner.style.display = 'none'; }
            if (indicator) {
                indicator.className = 'security-badge secure';
                indicator.title = (window.t ? window.t('panel.security_secure') : 'Gesichert');
            }
        }
    }
    $('security-indicator')?.addEventListener('click', _openCertModal);
    $('btn-banner-help')?.addEventListener('click', _openCertModal);
    $('btn-close-banner')?.addEventListener('click', () => {
        const banner = $('security-banner');
        if (banner) banner.style.display = 'none';
        try { localStorage.setItem('jarvis_cert_dismissed', 'true'); } catch (e) {}
    });
    checkSecurity();

    // Desktop/VNC-Overlay: nach /portal verschoben (portal.html + vnc.js)

    // Tab-Wechsel
    document.querySelectorAll('.cert-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.cert-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            ['win', 'linux', 'browser'].forEach(t => {
                const el = $('cert-tab-' + t);
                if (el) el.classList.toggle('hidden', btn.dataset.certTab !== t);
            });
        });
    });

    // ─── Spracheingabe (Mic-Button) ──────────────────────────────────
    const btnMic = $('btn-mic');
    let isRecording = false;
    let recognition = null;

    if (btnMic) {
        if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            recognition = new SR();
            recognition.continuous = false;
            recognition.interimResults = false;
            recognition.lang = 'de-DE';

            recognition.onstart = () => {
                isRecording = true;
                btnMic.classList.add('recording');
            };
            recognition.onresult = (e) => {
                const transcript = e.results[0][0].transcript;
                if (msgInput && transcript && transcript.trim()) {
                    msgInput.value = transcript.trim();
                    msgInput.dispatchEvent(new Event('input'));
                    stopMic();
                    sendMessage(); // erkannten Text sofort senden
                } else {
                    stopMic();
                }
            };
            recognition.onerror = () => stopMic();
            recognition.onend = () => stopMic();

            function stopMic() {
                isRecording = false;
                btnMic.classList.remove('recording');
                if (recognition) recognition.stop();
            }

            btnMic.addEventListener('click', () => {
                if (isRecording) {
                    stopMic();
                    // Wenn Text im Feld → direkt senden
                    if (msgInput && msgInput.value.trim()) sendMessage();
                } else {
                    isRecording = true;
                    btnMic.classList.add('recording');
                    recognition.start();
                }
            });
        } else {
            // Browser unterstützt keine Spracheingabe → Button ausblenden
            btnMic.style.display = 'none';
        }
    }

    // ═════════════════════════════════════════════════════════════
    //  FEEDBACK
    // ═════════════════════════════════════════════════════════════

    function _appendFeedbackRow(col, userMsg, botResp) {
        const row = document.createElement('div');
        row.className = 'msg-feedback-row';
        // SVG-Icons statt Emoji – konsistent zu Windows-App + Hauptfenster.
        const SVG_UP   = `<svg viewBox="0 0 24 24" width="14" height="14" fill="#FFCA28"><path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/></svg>`;
        const SVG_DOWN = `<svg viewBox="0 0 24 24" width="14" height="14" fill="#FFCA28"><path d="M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z"/></svg>`;
        const SVG_X    = `<svg viewBox="0 0 24 24" width="14" height="14" fill="#E74C3C"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>`;
        const _tGood  = window.t ? window.t('feedback.good')  : 'Gute Antwort';
        const _tBad   = window.t ? window.t('feedback.bad')   : 'Schlechte Antwort';
        const _tWrong = window.t ? window.t('feedback.wrong') : 'Falsche Antwort';
        row.innerHTML =
            `<button class="msg-fb-btn" data-r="positive" title="${_tGood}">${SVG_UP}</button>` +
            `<button class="msg-fb-btn" data-r="negative" title="${_tBad}">${SVG_DOWN}</button>` +
            `<button class="msg-fb-btn" data-r="wrong"    title="${_tWrong}">${SVG_X}</button>`;
        col.appendChild(row);

        row.querySelectorAll('.msg-fb-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const rating = btn.dataset.r;
                row.querySelectorAll('.msg-fb-btn').forEach(b => b.disabled = true);
                btn.classList.add('msg-fb-active');
                try {
                    const res = await fetch('/api/feedback', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ token, rating, user_message: userMsg, bot_response: botResp }),
                    });
                    const data = await res.json();
                    // Kurze Bestätigung anzeigen
                    const info = document.createElement('div');
                    info.className = 'msg-fb-info';
                    info.textContent = data.message || (window.t ? window.t('feedback.thanks') : 'Danke!');
                    row.replaceWith(info);
                    // LLM-Analyse mit Alternativen als Jarvis-Antwort einblenden
                    if (data.analysis) {
                        addBubble(data.analysis, 'bot');
                    }
                } catch {
                    btn.disabled = false;
                }
            });
        });
    }

    // Einmalig Feedback-CSS einfügen
    (function _injectFeedbackCss() {
        const id = 'jarvis-feedback-css';
        if (document.getElementById(id)) return;
        const s = document.createElement('style');
        s.id = id;
        s.textContent = `
.msg-feedback-row{display:flex;gap:4px;margin-top:4px;padding-left:2px;align-items:center;}
.msg-fb-btn{background:none;border:1px solid var(--outline);border-radius:50%;
  width:24px;height:24px;display:inline-flex;align-items:center;justify-content:center;
  padding:0;cursor:pointer;transition:all .15s;line-height:0;}
.msg-fb-btn svg{display:block;}
.msg-fb-btn:hover:not(:disabled){border-color:var(--accent);background:var(--surface-variant);transform:scale(1.12);}
.msg-fb-btn:disabled{cursor:default;opacity:.5;}
.msg-fb-btn.msg-fb-active{border-color:rgba(var(--accent-rgb),.7);background:rgba(var(--accent-rgb),.2);}
.msg-fb-info{font-size:.75rem;color:var(--muted);margin-top:4px;padding-left:2px;}
        `;
        document.head.appendChild(s);
    })();

    // Token vorhanden? → Benutzer vom Server holen (validiert Token + liefert Namen
    // fuer die Titelleiste), dann direkt zum Chat. Offline (PWA) → graceful Fallback.
    if (token) {
        fetch('/api/me', {
            headers: { 'Authorization': `Bearer ${token}` }
        }).then(r => {
            if (!r.ok) { logout(); return null; }
            return r.json();
        }).then(d => {
            if (d && d.username) {
                _currentUser = d.username;
                localStorage.setItem('jarvis_chat_user', _currentUser);
            }
            if (d) _isAdmin = !!d.is_admin;
            if (d !== null) showChat();
        }).catch(() => showChat());
    }

    // PWA Service Worker DEAKTIVIERT: der Offline-Cache hatte wiederholt veraltete
    // CSS/JS ausgeliefert (z.B. Branding am Senden-Button, CPU-Rahmen). Die App
    // braucht ohnehin durchgehend Netz (WebSocket/LLM). Daher aktiv abmelden +
    // Caches leeren, damit Updates IMMER sofort greifen.
    if ('serviceWorker' in navigator) {
        try {
            navigator.serviceWorker.getRegistrations().then((regs) => {
                regs.forEach((r) => r.unregister());
            }).catch(() => {});
            if (window.caches && caches.keys) {
                caches.keys().then((keys) => keys.forEach((k) => caches.delete(k))).catch(() => {});
            }
        } catch (e) { /* ignorieren */ }
    }
})();
