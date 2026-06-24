/**
 * Jarvis Chat UI – WebSocket-basierte Chat-Oberfläche
 * Android-identisches Bubble-Design mit LDAP-Authentifizierung
 */
(() => {
    'use strict';

    // ─── State ──────────────────────────────────────────────────
    let token = localStorage.getItem('jarvis_chat_token') || '';
    // Eindeutige Fenster-ID fuer Live-Sync (eigene Echo-Events ignorieren)
    const _clientId = 'chat-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    let _currentUser = localStorage.getItem('jarvis_chat_user') || '';
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

    // Feedback-State
    let _lastUserMsg  = '';        // letzte gesendete Benutzerfrage
    let _lastBotResp  = '';        // letzte vollständige Bot-Antwort
    let _lastBotCol   = null;      // .msg-col des letzten Bot-Bubbles
    let _lastStats    = '';        // Statistik-Text des letzten Bot-Bubbles

    // Verlauf-Persistenz
    const _HISTORY_KEY = 'jarvis_chat_history_v1';
    const _HISTORY_MAX = 120;
    let _chatHistory   = [];

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

            if (data.success && data.token && data.must_change_password) {
                // Lokaler Erst-Login: Kennwortaenderung ist nur im Hauptfenster moeglich.
                loginError.textContent = 'Bitte zuerst im Hauptfenster (Startseite) das Kennwort aendern, dann hier anmelden.';
            } else if (data.success && data.token) {
                token = data.token;
                localStorage.setItem('jarvis_chat_token', token);
                _currentUser = data.username || loginUser.value.trim();
                localStorage.setItem('jarvis_chat_user', _currentUser);
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
                statusDot.title = 'LLM-Status nicht abrufbar';
                return;
            }
            const d = await res.json();
            const reachable = (d.status === 'ok' || d.status === 'degraded');
            statusDot.className = 'topbar-dot ' + (reachable ? 'connected' : 'disconnected');
            const name = d.profile_name ? ' – ' + d.profile_name : '';
            if (d.status === 'ok')            statusDot.title = 'LLM erreichbar' + name;
            else if (d.status === 'degraded') statusDot.title = 'LLM erreichbar (Modell fehlt)' + name;
            else                              statusDot.title = 'LLM nicht erreichbar' + name;
        } catch (e) {
            statusDot.className = 'topbar-dot disconnected';
            statusDot.title = 'LLM nicht erreichbar';
        }
    }
    function _startLlmStatusIndicator() {
        _checkLlmStatus();
        if (!_llmStatusTimer) _llmStatusTimer = setInterval(_checkLlmStatus, 30000);
    }

    function showChat() {
        loginScreen.classList.add('hidden');
        chatScreen.classList.remove('hidden');
        const _ownBadge = $('chat-own-badge');
        if (_ownBadge) _ownBadge.textContent = _currentUser || '';
        connectWS();
        _startLlmStatusIndicator();
        _restoreHistory();
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
    ]);
    // Endungs-Fallback (Office-Dateien melden per Drag&Drop oft leeren MIME-Typ)
    const _SUPPORTED_EXT = new Set([
        'pdf','txt','md','rst','csv','json',
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
            if (_pendingAttachments.length >= 5) { showToast('Max. 5 Dateien erlaubt.'); break; }
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
            } catch(e) { showToast(`"${file.name}" konnte nicht gelesen werden.`); }
        }
        if (unsupported.length > 0) {
            const fmts = [...new Set(unsupported)].join(', ');
            showToast(`Format nicht unterstützt: ${fmts} – Erlaubt: Bilder, Audio, Video, PDF, Office (xlsx/docx/pptx), Text`);
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
        const finalText = text || 'Bitte analysiere/beschreibe die angehängten Dateien.';

        _lastUserMsg = finalText;
        _lastBotResp = '';
        _lastBotCol  = null;
        _lastStats   = '';

        const userBubble = addBubble(finalText, 'user');
        if (_pendingAttachments.length > 0) {
            // Snapshot der Anhänge für Rendering (vor dem Leeren von _pendingAttachments)
            const attSnap = _pendingAttachments.map(a => ({ name: a.name, mime_type: a.mime_type, data: a.data }));
            _renderAttachments(userBubble, { attachments: attSnap });
        }

        // Benutzernachricht im Verlauf speichern (nur Text + Hinweis, kein base64)
        const _attIcon = m => { m = (m || '').toLowerCase(); return m.startsWith('image/') ? '🖼️' : m === 'application/pdf' ? '📄' : m.startsWith('audio/') ? '🎵' : m.startsWith('video/') ? '🎬' : '📎'; };
        const attNote = _pendingAttachments.length > 0
            ? ' [' + _pendingAttachments.map(a => `${_attIcon(a.mime_type)} ${a.name || 'Datei'}`).join(', ') + ']'
            : '';
        _chatHistory.push({ role: 'user', text: finalText + attNote, time: timeStr(), date: _currentDateStr(), ts: Date.now() });
        _saveHistory();
        _syncAppend(_chatHistory[_chatHistory.length - 1]);
        const msg = { type: 'task', text: finalText, lang: window._lang || 'de' };
        if (_pendingAttachments.length > 0) {
            msg.attachments = _pendingAttachments.map(a => ({ name: a.name, mime_type: a.mime_type, data: a.data }));
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

            case 'cpu':
            case 'pong':
                break; // ignorieren
        }
    }

    function handleStatus(msg) {
        const text = msg.message || '';
        if (!text) return;

        // Status-Nachrichten erkennen: beginnen immer mit einem bekannten Emoji
        const STATUS_PREFIXES = ['🚀','🔧','📋','⏳','💬','💻','✅','⚠️','❌','🧠','⏸','▶','⏹'];
        const isStatus = STATUS_PREFIXES.some(p => text.startsWith(p));

        if (msg.highlight && !isStatus) {
            // Echter LLM-Antwort-Text (highlight=true, kein Status-Emoji) → Bot-Bubble + TTS
            _ttsBuf += (text + ' ');
            appendToBotBubble(text);
        } else if (isStatus && (text.startsWith('⏸') || text.startsWith('▶') || text.startsWith('⏹'))) {
            addStatusLine(text);
        }
        // Alle anderen Status-Nachrichten still ignorieren
    }

    function handleAgentEvent(msg) {
        if (msg.event === 'started') {
            agentRunning = true;
            _ttsBuf = '';
            stopBtn.classList.remove('hidden');
            currentBotBubble = null;
        } else if (msg.event === 'finished') {
            agentRunning = false;
            stopBtn.classList.add('hidden');
            removeStreamingDots();
            currentBotBubble = null;
            _updateContextIndicator();
            const toSpeak = _ttsBuf.trim();
            _ttsBuf = '';
            if (toSpeak) speak(toSpeak);
            // Bot-Antwort im Verlauf speichern
            if (_lastBotResp) {
                _chatHistory.push({ role: 'bot', text: _lastBotResp, time: timeStr(), date: _currentDateStr(), stats: _lastStats, ts: Date.now() });
                _saveHistory();
                _syncAppend(_chatHistory[_chatHistory.length - 1]);
            }
            // Feedback-Buttons anfügen
            if (_lastBotCol && _lastBotResp) {
                _appendFeedbackRow(_lastBotCol, _lastUserMsg, _lastBotResp);
                _lastBotCol = null;
            }
        }
    }

    // ═════════════════════════════════════════════════════════════
    //  BUBBLES RENDERN
    // ═════════════════════════════════════════════════════════════

    function addBubble(text, role, customTime) {
        removeWelcome();
        maybeAddDateSep();

        const row = document.createElement('div');
        row.className = `msg-row ${role}`;

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
            alert('Edit-Bibliothek (chatlib.js) nicht geladen.');
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
        });
    }

    function appendToBotBubble(text) {
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
        s += ` · ${steps} Schritte`;
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
        if (str === todayStr)   return 'Heute';
        if (str === yesterStr)  return 'Gestern';
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
                img.alt = att.name || 'Bild';
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
                    <span class="uc-fc-name" title="${escapeHtml(att.name||'')}">${escapeHtml(att.name||'Datei')}</span>
                    <span class="uc-fc-badge">${escapeHtml(badge)}</span>
                </div>
                <a class="uc-fc-dl" href="${src}" download="${escapeHtml(att.name||'datei')}" title="Herunterladen" onclick="event.stopPropagation()">⬇</a>`;
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
        }

        row.appendChild(col);
        messagesEl.appendChild(row);

        // Kontextmenue auch fuer restaurierte Bubbles aktivieren (vorher fehlte
        // dieser Hook, weshalb Rechtsklick im /chat-Popup nur Browser-Menue zeigte).
        if (window.JarvisChatLib && window.JarvisChatLib.setupBubbleContextMenu) {
            window.JarvisChatLib.setupBubbleContextMenu(row, () => _buildBubbleCtxItems(row, bubble, entry.role));
        }
    }

    // Neue Nachricht in die geteilte Backend-History anhaengen (additiv, fensteruebergreifend)
    function _syncAppend(msg) {
        if (window.JarvisChatLib && window.JarvisChatLib.sharedAppend && token) {
            window.JarvisChatLib.sharedAppend(token, msg, _clientId);
        }
    }
    // Komplette Liste ins Backend schreiben (fuer Editieren/Loeschen)
    function _syncReplace() {
        if (window.JarvisChatLib && window.JarvisChatLib.sharedReplace && token) {
            window.JarvisChatLib.sharedReplace(token, _chatHistory, _clientId);
        }
    }

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
        // Geteilte Anzeige-History pro Benutzer (Hauptfenster + jarvis/chat identisch).
        const _CL = window.JarvisChatLib;
        if (_CL && _CL.sharedMigrate && token) {
            try {
                await _CL.sharedMigrate(token, ['jarvis_main_history_v1', 'jarvis_chat_history_v1']);
                const shared = await _CL.sharedLoad(token);
                _chatHistory = (shared !== null) ? shared : _loadHistory();
            } catch (_e) { _chatHistory = _loadHistory(); }
        } else {
            _chatHistory = _loadHistory();
        }
        if (_chatHistory.length === 0) return;

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
        divider.innerHTML = `<span>── Neue Sitzung ──</span>`;
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
            if (d !== null) showChat();
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
