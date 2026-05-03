/**
 * Jarvis Chat UI – WebSocket-basierte Chat-Oberfläche
 * Android-identisches Bubble-Design mit LDAP-Authentifizierung
 */
(() => {
    'use strict';

    // ─── State ──────────────────────────────────────────────────
    let token = localStorage.getItem('jarvis_chat_token') || '';
    let ws = null;
    let reconnectAttempts = 0;
    const MAX_RECONNECT = 20;
    let agentRunning = false;
    let currentBotBubble = null;   // Streaming-Ziel
    let lastDate = '';

    // TTS-State
    let ttsEnabled = false;
    let _ttsAudio = null;
    let _ttsBuf = '';              // sammelt Bot-Text während Streaming

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
    const logoutBtn    = $('btn-logout');
    const statusDot    = $('status-dot');
    const totpSetupBtn = $('btn-totp-setup');
    const totpModal    = $('totp-modal');
    const btnTtsChat   = $('btn-tts-chat');
    const chatTtsVoice = $('chat-tts-voice');
    const chatTtsIconOn  = $('chat-tts-icon-on');
    const chatTtsIconOff = $('chat-tts-icon-off');

    // ═════════════════════════════════════════════════════════════
    //  TTS
    // ═════════════════════════════════════════════════════════════

    function _updateTtsChatBtn() {
        if (!btnTtsChat) return;
        if (chatTtsIconOn)  chatTtsIconOn.style.display  = ttsEnabled ? '' : 'none';
        if (chatTtsIconOff) chatTtsIconOff.style.display = ttsEnabled ? 'none' : '';
        const voiceWrap = $('tts-voice-wrap');
        if (voiceWrap) voiceWrap.style.display = ttsEnabled ? '' : 'none';
        btnTtsChat.title = ttsEnabled ? 'Sprachausgabe deaktivieren' : 'Sprachausgabe aktivieren';
    }

    async function _loadChatTtsVoices(savedVoice) {
        if (!chatTtsVoice) return;
        try {
            const resp = await fetch('/api/tts/voices', { headers: { 'Authorization': `Bearer ${token}` } });
            if (!resp.ok) return;
            const voices = await resp.json();
            chatTtsVoice.innerHTML = '<option value="">Standard</option>';
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
        loginBtn.textContent = 'Anmelden…';

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

            if (data.success && data.token) {
                token = data.token;
                localStorage.setItem('jarvis_chat_token', token);
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
                loginError.textContent = data.error || 'Anmeldung fehlgeschlagen';
            }
        } catch (err) {
            loginError.textContent = 'Verbindungsfehler';
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = 'Anmelden';
        }
    });

    function showChat() {
        loginScreen.classList.add('hidden');
        chatScreen.classList.remove('hidden');
        connectWS();
        msgInput.focus();
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
    const _authHdr = () => ({ 'Authorization': 'Bearer ' + token });

    async function _updateContextIndicator() {
        const el   = document.getElementById('ctx-indicator');
        const text = document.getElementById('ctx-indicator-text');
        if (!el) return;
        try {
            const r = await fetch('/api/context/stats', { headers: _authHdr() });
            if (!r.ok) return;
            const d = await r.json();
            const n = d.history_entries || 0;
            if (n > 0) {
                el.style.display = 'flex';
                text.textContent = `Kontext Speicher: ${n} Einträge · ${d.fills_pct ?? 0} %`;
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
            const r = await fetch('/api/context/clear', { method: 'POST', headers: _authHdr() });
            const d = await r.json();
            if (d.ok) document.getElementById('ctx-indicator').style.display = 'none';
        } catch (e) { /* ignore */ }
    };

    function logout() {
        token = '';
        localStorage.removeItem('jarvis_chat_token');
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

        statusDot.className = 'topbar-dot connecting';

        ws.onopen = () => {
            statusDot.className = 'topbar-dot connected';
            reconnectAttempts = 0;
        };

        ws.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                handleMessage(msg);
            } catch { /* ignore non-JSON */ }
        };

        ws.onclose = () => {
            statusDot.className = 'topbar-dot disconnected';
            scheduleReconnect();
        };

        ws.onerror = () => {
            statusDot.className = 'topbar-dot disconnected';
        };
    }

    function scheduleReconnect() {
        if (reconnectAttempts >= MAX_RECONNECT) return;
        reconnectAttempts++;
        const delay = 2000 * Math.min(reconnectAttempts, 5);
        statusDot.className = 'topbar-dot connecting';
        setTimeout(connectWS, delay);
    }

    function wsSend(obj) {
        if (!ws || ws.readyState !== 1) return;
        ws.send(JSON.stringify({ ...obj, token }));
    }

    // ═════════════════════════════════════════════════════════════
    //  NACHRICHT SENDEN
    // ═════════════════════════════════════════════════════════════

    function sendMessage() {
        const text = msgInput.value.trim();
        if (!text) return;

        addBubble(text, 'user');
        wsSend({ type: 'task', text });

        msgInput.value = '';
        msgInput.style.height = '';
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
        sendBtn.disabled = !msgInput.value.trim();
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

            case 'llm_stats':
                appendStats(msg);
                break;

            case 'error':
                if (msg.message === 'Nicht autorisiert') {
                    logout();
                }
                break;

            case 'cpu':
            case 'pong':
                break; // ignorieren
        }
    }

    function handleStatus(msg) {
        const text = msg.message || '';
        if (!text) return;

        // Highlight-Nachrichten = LLM-Antworten → in Bot-Bubble
        // Prefix-basierte Erkennung (identisch zu Android SegmentType)
        if (text.startsWith('🚀 ') || text.startsWith('🔧 ') || text.startsWith('📋 ')
            || text.startsWith('⏳') || text.startsWith('💬') || text.startsWith('💻 ')
            || text.startsWith('✅') || text.startsWith('⚠️') || text.startsWith('❌')) {
            // Debug/Status-Zeilen ausblenden (wie Android ohne Debug-Modus)
            return;
        } else if (text.startsWith('⏸') || text.startsWith('▶') || text.startsWith('⏹')) {
            addStatusLine(text);
        } else {
            // LLM-Antwort-Text → Bot-Bubble (Streaming) + TTS-Puffer füllen
            _ttsBuf += (text + ' ');
            appendToBotBubble(text);
        }
    }

    function handleAgentEvent(msg) {
        if (msg.event === 'started') {
            agentRunning = true;
            _ttsBuf = '';  // Puffer für neue Antwort zurücksetzen
            stopBtn.classList.remove('hidden');
            // Neue Bot-Bubble vorbereiten
            currentBotBubble = null;
        } else if (msg.event === 'finished') {
            agentRunning = false;
            stopBtn.classList.add('hidden');
            // Streaming beenden
            removeStreamingDots();
            currentBotBubble = null;
            _updateContextIndicator();
            // TTS: gesammelte Antwort vorlesen
            const toSpeak = _ttsBuf.trim();
            _ttsBuf = '';
            if (toSpeak) speak(toSpeak);
        }
    }

    // ═════════════════════════════════════════════════════════════
    //  BUBBLES RENDERN
    // ═════════════════════════════════════════════════════════════

    function addBubble(text, role) {
        removeWelcome();
        maybeAddDateSep();

        const row = document.createElement('div');
        row.className = `msg-row ${role}`;

        // Timestamp
        const timeEl = document.createElement('div');
        timeEl.className = 'msg-time';
        timeEl.textContent = timeStr();

        // Bubble
        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';
        bubble.innerHTML = role === 'user' ? escapeHtml(text) : renderMarkdown(text);

        const col = document.createElement('div');
        col.appendChild(timeEl);
        col.appendChild(bubble);

        if (role === 'bot') {
            const avatar = document.createElement('div');
            avatar.className = 'msg-avatar';
            avatar.textContent = 'J';
            row.appendChild(avatar);
        }

        row.appendChild(col);
        messagesEl.appendChild(row);
        scrollToBottom();

        return bubble;
    }

    function appendToBotBubble(text) {
        if (!currentBotBubble) {
            currentBotBubble = addBubble(text, 'bot');
            addStreamingDots();
        } else {
            // Neuen Text anhängen (ersetze bisherigen Inhalt)
            currentBotBubble.innerHTML = renderMarkdown(
                (currentBotBubble._rawText || '') + '\n' + text
            );
        }
        currentBotBubble._rawText = (currentBotBubble._rawText || '') + '\n' + text;
        scrollToBottom();
    }

    function appendStats(msg) {
        if (!currentBotBubble) return;
        removeStreamingDots();

        const stats = document.createElement('div');
        stats.className = 'msg-stats';
        const dur = (msg.duration_ms / 1000).toFixed(1);
        const tokens = msg.total_tokens || 0;
        const steps = msg.steps || 0;
        stats.textContent = `${dur}s · ${tokens} Tokens · ${steps} Schritte`;
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
    function maybeAddDateSep() {
        const today = new Date().toLocaleDateString('de-DE', {
            day: '2-digit', month: '2-digit', year: 'numeric'
        });
        if (today === lastDate) return;
        lastDate = today;

        const sep = document.createElement('div');
        sep.className = 'date-sep';
        sep.innerHTML = `<span>${today}</span>`;
        messagesEl.appendChild(sep);
    }

    // ─── Helpers ────────────────────────────────────────────────
    function timeStr() {
        return new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
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

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    /** Einfaches Markdown → HTML: **bold**, *italic*, `code`, ```pre``` */
    function renderMarkdown(text) {
        let html = escapeHtml(text);

        // Code-Blöcke (```)
        html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
            return `<pre><code>${code.trim()}</code></pre>`;
        });

        // Inline-Code
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Bold
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

        // Italic
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

        // Newlines
        html = html.replace(/\n/g, '<br>');

        return html;
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
        localStorage.setItem('jarvis_chat_theme', light ? 'light' : 'dark');
    }

    // Gespeicherte Präferenz laden
    const savedTheme = localStorage.getItem('jarvis_chat_theme');
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
            totpModalError.textContent = 'Verbindungsfehler';
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
                addStatusLine('✅ 2FA wurde aktiviert');
            } else {
                totpModalError.textContent = data.error || 'Verifizierung fehlgeschlagen';
            }
        } catch {
            totpModalError.textContent = 'Verbindungsfehler';
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
                addStatusLine('🔓 2FA wurde deaktiviert');
            } else {
                totpModalError.textContent = data.error || 'Deaktivierung fehlgeschlagen';
            }
        } catch {
            totpModalError.textContent = 'Verbindungsfehler';
        }
    });

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

    // Token vorhanden? → direkt zum Chat (Token wird beim ersten WS-Send validiert)
    if (token) {
        fetch('/api/config', {
            headers: { 'Authorization': `Bearer ${token}` }
        }).then(r => {
            if (r.ok) showChat();
            else logout();
        }).catch(() => showChat());
    }

    // PWA Service Worker registrieren
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js').then((reg) => {
            console.log('[PWA] Service Worker registriert:', reg.scope);
        }).catch((err) => {
            console.warn('[PWA] Service Worker Fehler:', err);
        });
    }
})();
