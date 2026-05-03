/**
 * Jarvis Benutzer-Chat – User-zu-User Echtzeit-Messaging
 */
(() => {
    'use strict';

    // ─── State ──────────────────────────────────────────────────
    let token     = localStorage.getItem('jarvis_uc_token') || '';
    let myUser    = localStorage.getItem('jarvis_uc_user')  || '';
    let ws        = null;
    let wsReady   = false;
    let activePartner = null;       // Username des aktiven Gesprächspartners
    let reconnectTimer = null;
    let typingTimer    = null;
    let typingCooldown = false;

    // Lokaler Nachrichten-Cache: username → [{from,to,text,ts,mine}]
    const _msgs = {};
    // Ungelesene Zähler: username → count
    const _unread = {};
    // Online-Status: username → bool
    const _online = {};

    // ─── DOM ────────────────────────────────────────────────────
    const $ = id => document.getElementById(id);
    const loginScreen   = $('login-screen');
    const chatScreen    = $('chat-screen');
    const loginForm     = $('login-form');
    const loginUser     = $('login-user');
    const loginPass     = $('login-pass');
    const loginBtn      = $('btn-login');
    const loginError    = $('login-error');
    const eyeBtn        = $('eye-btn');
    const totpRow       = $('totp-row');
    const loginTotp     = $('login-totp');
    const ownBadge      = $('uc-own-badge');
    const userList      = $('uc-user-list');
    const emptyState    = $('uc-empty-state');
    const chatArea      = $('uc-chat-area');
    const partnerAvatar = $('uc-partner-avatar');
    const partnerName   = $('uc-partner-name');
    const partnerStatus = $('uc-partner-status');
    const messages      = $('uc-messages');
    const typingEl      = $('uc-typing');
    const inputEl       = $('uc-input');
    const sendBtn       = $('uc-send-btn');

    // ─── Hilfsfunktionen ────────────────────────────────────────
    function initial(name) {
        return (name || '?').charAt(0).toUpperCase();
    }

    function formatTime(ts) {
        const d = new Date(ts);
        return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    }

    function formatDate(ts) {
        const d = new Date(ts);
        const today = new Date();
        if (d.toDateString() === today.toDateString()) return 'Heute';
        const yest = new Date(today);
        yest.setDate(yest.getDate() - 1);
        if (d.toDateString() === yest.toDateString()) return 'Gestern';
        return d.toLocaleDateString('de-DE');
    }

    // ─── Eye-Button ─────────────────────────────────────────────
    const eyeSvgOpen = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
    const eyeSvgClosed = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;
    eyeBtn.addEventListener('click', () => {
        const show = loginPass.type === 'password';
        loginPass.type = show ? 'text' : 'password';
        eyeBtn.innerHTML = show ? eyeSvgClosed : eyeSvgOpen;
    });

    // ─── Login ──────────────────────────────────────────────────
    // Auto-Login wenn Token vorhanden
    if (token && myUser) {
        showChat();
    }

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
                token  = data.token;
                myUser = data.username || loginUser.value.trim();
                localStorage.setItem('jarvis_uc_token', token);
                localStorage.setItem('jarvis_uc_user',  myUser);
                totpRow.classList.add('hidden');
                showChat();
            } else if (data.requires_totp) {
                totpRow.classList.remove('hidden');
                loginTotp.focus();
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
        loginScreen.style.display = 'none';
        chatScreen.style.display  = 'block';
        chatScreen.classList.remove('hidden');
        if (ownBadge) ownBadge.textContent = myUser;
        connectWS();
    }

    // ─── WebSocket ──────────────────────────────────────────────
    function connectWS() {
        if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}//${location.host}/ws/users`);

        ws.addEventListener('open', () => {
            wsReady = true;
            // Erste Nachricht: Auth
            ws.send(JSON.stringify({ type: 'auth', token }));
        });

        ws.addEventListener('message', (ev) => {
            try {
                handleMessage(JSON.parse(ev.data));
            } catch (e) { /* ignore */ }
        });

        ws.addEventListener('close', () => {
            wsReady = false;
            // Reconnect nach 3s
            clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connectWS, 3000);
        });

        ws.addEventListener('error', () => {
            wsReady = false;
        });
    }

    function wsSend(obj) {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ ...obj, token }));
        }
    }

    // ─── Nachrichten-Handler ─────────────────────────────────────
    function handleMessage(msg) {
        switch (msg.type) {
            case 'connected':
                myUser = msg.username || myUser;
                if (ownBadge) ownBadge.textContent = myUser;
                updatePresence(msg.users || []);
                break;

            case 'presence':
                updatePresence(msg.users || []);
                break;

            case 'dm': {
                const partner = msg.from === myUser ? msg.to : msg.from;
                if (!_msgs[partner]) _msgs[partner] = [];
                _msgs[partner].push(msg);
                if (partner === activePartner) {
                    appendMessage(msg);
                    scrollToBottom();
                } else {
                    // Ungelesen hochzählen
                    _unread[partner] = (_unread[partner] || 0) + 1;
                    renderUserList();
                }
                break;
            }

            case 'typing':
                if (msg.from === activePartner) {
                    showTyping(msg.from);
                }
                break;

            case 'error':
                if (msg.message === 'Nicht autorisiert') {
                    // Token ungültig – ausloggen
                    localStorage.removeItem('jarvis_uc_token');
                    localStorage.removeItem('jarvis_uc_user');
                    location.reload();
                }
                break;
        }
    }

    // ─── Presence / Userliste ────────────────────────────────────
    function updatePresence(users) {
        // Alle als offline markieren, dann online setzen
        for (const k in _online) _online[k] = false;
        for (const u of users) {
            _online[u.username] = u.online;
        }
        // Sicherstellen, dass eigener User drin ist
        if (myUser && !_online.hasOwnProperty(myUser)) {
            _online[myUser] = true;
        }
        renderUserList();
        // Partner-Status aktualisieren
        if (activePartner) updatePartnerStatus();
    }

    function renderUserList() {
        if (!userList) return;
        const allUsers = Object.keys(_online).sort((a, b) => {
            // Online zuerst, dann alphabetisch
            const ao = _online[a] ? 1 : 0;
            const bo = _online[b] ? 1 : 0;
            if (ao !== bo) return bo - ao;
            return a.localeCompare(b);
        });

        userList.innerHTML = '';
        for (const username of allUsers) {
            const online  = _online[username];
            const unread  = _unread[username] || 0;
            const isMe    = username === myUser;
            const isActive = username === activePartner;

            const item = document.createElement('div');
            item.className = 'uc-user-item' + (isActive ? ' active' : '');
            item.dataset.username = username;

            item.innerHTML = `
                <div class="uc-avatar">
                    ${initial(username)}
                    <span class="uc-online-dot ${online ? 'online' : 'offline'}"></span>
                </div>
                <span class="uc-user-name ${online ? '' : 'offline'}">${escHtml(username)}${isMe ? ' (ich)' : ''}</span>
                ${unread > 0 ? `<span class="uc-unread">${unread}</span>` : ''}
            `;

            if (!isMe) {
                item.addEventListener('click', () => openChat(username));
            }
            userList.appendChild(item);
        }
    }

    function escHtml(s) {
        return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ─── Chat öffnen ─────────────────────────────────────────────
    function openChat(username) {
        activePartner = username;
        _unread[username] = 0;

        // Header
        partnerAvatar.textContent = initial(username);
        partnerName.textContent   = username;
        updatePartnerStatus();

        // UI umschalten
        emptyState.style.display = 'none';
        chatArea.style.display   = 'flex';

        // Nachrichten anzeigen
        messages.innerHTML = '';
        const history = _msgs[username] || [];
        let lastDate = '';
        for (const m of history) {
            const d = formatDate(m.ts);
            if (d !== lastDate) {
                appendDateSep(d);
                lastDate = d;
            }
            appendMessage(m);
        }
        scrollToBottom();
        renderUserList();
        inputEl.focus();
    }

    function updatePartnerStatus() {
        if (!activePartner) return;
        const online = _online[activePartner] || false;
        partnerStatus.textContent = online ? 'online' : 'offline';
        partnerStatus.className = 'uc-chat-status ' + (online ? 'online' : '');
    }

    // ─── Nachrichten rendern ─────────────────────────────────────
    function appendDateSep(label) {
        const div = document.createElement('div');
        div.className = 'uc-date-sep';
        div.textContent = label;
        messages.appendChild(div);
    }

    function appendMessage(msg) {
        const mine = msg.from === myUser;
        const row  = document.createElement('div');
        row.className = 'uc-msg-row ' + (mine ? 'mine' : 'theirs');

        const bubble = document.createElement('div');
        bubble.className = 'uc-bubble ' + (mine ? 'mine' : 'theirs');
        bubble.textContent = msg.text;

        const ts = document.createElement('div');
        ts.className = 'uc-ts';
        ts.textContent = formatTime(msg.ts);

        row.appendChild(bubble);
        row.appendChild(ts);
        messages.appendChild(row);
    }

    function scrollToBottom() {
        messages.scrollTop = messages.scrollHeight;
    }

    // ─── Typing-Indikator ────────────────────────────────────────
    let _typingClearTimer = null;
    function showTyping(username) {
        typingEl.textContent = `${username} schreibt…`;
        clearTimeout(_typingClearTimer);
        _typingClearTimer = setTimeout(() => { typingEl.textContent = ''; }, 3000);
    }

    // ─── Eingabe ─────────────────────────────────────────────────
    inputEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    inputEl.addEventListener('input', () => {
        // Auto-Resize
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
        // Typing-Event (max 1x pro 2s)
        if (activePartner && !typingCooldown) {
            typingCooldown = true;
            wsSend({ type: 'typing', to: activePartner });
            setTimeout(() => { typingCooldown = false; }, 2000);
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    function sendMessage() {
        const text = inputEl.value.trim();
        if (!text || !activePartner) return;
        wsSend({ type: 'dm', to: activePartner, text });
        inputEl.value = '';
        inputEl.style.height = 'auto';
        inputEl.focus();
    }

})();
