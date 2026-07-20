/**
 * Jarvis Benutzer-Chat – User-zu-User Echtzeit-Messaging
 * v4: Emoji-Picker (WhatsApp-Style, Kategorien + Suche)
 */
(() => {
    'use strict';

    // ─── State ──────────────────────────────────────────────────
    // SSO: jeden gueltigen Login-Token akzeptieren (kein Re-Login bei Seitenwechsel)
    let token     = localStorage.getItem('jarvis_uc_token') || localStorage.getItem('jarvis_token') || localStorage.getItem('jarvis_chat_token') || '';
    if (token) localStorage.setItem('jarvis_uc_token', token);
    // Benutzername seitenuebergreifend (SSO): andere Seiten speichern unter eigenen Keys
    let myUser    = localStorage.getItem('jarvis_uc_user') || localStorage.getItem('jarvis_chat_user') || localStorage.getItem('jarvis_user') || '';
    let ws        = null;
    let wsReady   = false;
    let activePartner = null;       // Username des aktiven Gesprächspartners
    let reconnectTimer = null;
    let _sessionInvalid = false;   // Berechtigung entzogen -> kein Auto-Reconnect mehr
    let typingCooldown = false;

    // Lokaler Nachrichten-Cache: username → [{from,to,text,ts,mine,msg_id,status}]
    const _msgs = {};
    // Ungelesene Zähler: username → count
    const _unread = {};
    // Online-Status: username → bool
    const _online = {};
    // DOM-Elemente für Tick-Anzeige: msg_id → <span class="uc-ticks">
    const _tickEls = {};

    // ─── Benachrichtigungen ──────────────────────────────────────
    function _requestNotifyPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
    }

    function _showNotification(from, text) {
        const tabFocused  = document.hasFocus();
        const chatVisible = from === activePartner && tabFocused;
        if (chatVisible) return;

        _playPing();
        _updateTabTitle();

        if (!('Notification' in window) || Notification.permission !== 'granted') return;
        const body = text.length > 100 ? text.slice(0, 97) + '…' : text;
        const n = new Notification(`💬 ${from}`, {
            body,
            icon: '/static/favicon.png?v=6',
            tag:  `jarvis-uc-${from}`,
            renotify: true,
        });
        n.onclick = () => {
            window.focus();
            openChat(from);
            n.close();
        };
    }

    function _playPing() {
        try {
            const ctx  = new (window.AudioContext || window.webkitAudioContext)();
            const osc  = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = 'sine';
            osc.frequency.setValueAtTime(1047, ctx.currentTime);
            osc.frequency.setValueAtTime(1319, ctx.currentTime + 0.08);
            gain.gain.setValueAtTime(0.25, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + 0.35);
        } catch (e) { /* AudioContext evtl. nicht verfügbar */ }
    }

    function _updateTabTitle() {
        const total = Object.values(_unread).reduce((a, b) => a + b, 0);
        document.title = total > 0 ? window.t('userchat.tab_title_unread').replace('{n}', total) : window.t('userchat.tab_title');
    }

    // Tab erhält Fokus → aktiven Chat als gelesen markieren
    window.addEventListener('focus', () => {
        if (activePartner && _unread[activePartner]) {
            _markRead(activePartner);
        }
    });

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
    const msgSelectBar   = $('msg-select-bar');
    const msgSelectCount = $('msg-select-count');
    const btnMsgDelSel   = $('btn-msg-del-sel');
    const btnMsgSelCancel = $('btn-msg-sel-cancel');

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
        if (d.toDateString() === today.toDateString()) return window.t('userchat.today');
        const yest = new Date(today);
        yest.setDate(yest.getDate() - 1);
        if (d.toDateString() === yest.toDateString()) return window.t('userchat.yesterday');
        return d.toLocaleDateString('de-DE');
    }

    function escHtml(s) {
        return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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
    if (token && myUser) {
        localStorage.setItem('jarvis_uc_user', myUser);
        showChat();
    } else if (token) {
        // SSO: Token von anderer Seite vorhanden, Benutzername lokal noch unbekannt
        // -> per /api/me holen (validiert zugleich den Token). Ungueltig -> Login bleibt.
        fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + token } })
            .then(r => r.ok ? r.json() : null)
            .then(d => {
                if (d && d.username) {
                    myUser = d.username;
                    localStorage.setItem('jarvis_uc_user', myUser);
                    showChat();
                }
            })
            .catch(() => {});
    }

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginError.textContent = '';
        loginBtn.disabled = true;
        loginBtn.textContent = window.t('userchat.logging_in');

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
                loginError.textContent = data.error || window.t('userchat.login_failed');
            }
        } catch (err) {
            loginError.textContent = window.t('userchat.connection_error');
        } finally {
            loginBtn.disabled = false;
            loginBtn.textContent = window.t('userchat.login');
        }
    });

    function showChat() {
        loginScreen.style.display = 'none';
        // display:flex damit flex-direction:column + flex:1 korrekt funktionieren
        chatScreen.style.display  = 'flex';
        chatScreen.classList.remove('hidden');
        var _ucLogout = $('btn-uc-logout');
        if (_ucLogout && myUser) _ucLogout.title = window.t('userchat.logout_title').replace('{user}', myUser);
        _requestNotifyPermission();
        _startLlmStatus();
        _startCpu();
        initUserSearch();
        connectWS();
    }

    // ── CPU-Auslastung (fuer alle): /api/cpu pollen ──
    let _cpuTimer = null;
    function _updateCpu(pct) {
        const fill = $('cpu-bar-fill'), label = $('cpu-bar-label');
        if (!fill || !label) return;
        const p = Math.max(0, Math.min(100, Number(pct) || 0));
        fill.style.width = p + '%';
        fill.style.backgroundPosition = p + '% 0';
        label.textContent = 'CPU: ' + Math.round(p) + '%';
    }
    function _startCpu() {
        if (_cpuTimer) return;
        const poll = () => fetch('/api/cpu', { headers: { 'Authorization': 'Bearer ' + token } })
            .then(r => r.ok ? r.json() : null).then(d => { if (d) _updateCpu(d.cpu); }).catch(() => {});
        poll();
        _cpuTimer = setInterval(poll, 3000);
    }

    // ── LLM-Status-Pill (analog /chat): erreichbar -> gruen, sonst rot ──
    let _llmStatusTimer = null;
    function _checkLlmStatus() {
        var dot = $('status-dot');
        if (!dot) return;
        fetch('/api/llm/active-status', { headers: { 'Authorization': 'Bearer ' + token } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) { dot.className = 'topbar-dot disconnected'; dot.title = window.t('userchat.llm_status_unavailable'); return; }
                var reachable = (d.status === 'ok' || d.status === 'degraded');
                dot.className = 'topbar-dot ' + (reachable ? 'connected' : 'disconnected');
                var name = d.profile_name ? ' – ' + d.profile_name : '';
                dot.title = (d.status === 'ok' ? window.t('app.llm_reachable') : d.status === 'degraded' ? window.t('app.llm_reachable_no_model') : window.t('app.llm_unreachable')) + name;
            })
            .catch(function () { dot.className = 'topbar-dot disconnected'; dot.title = window.t('app.llm_unreachable'); });
        // Admin: Setup-Button (direkt vor Logout) einblenden -> Einstellungen.
        if (!dot._adminChecked) {
            dot._adminChecked = true;
            fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + token } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (d && d.is_admin) {
                        var sb = $('btn-uc-settings');
                        if (sb) {
                            sb.style.display = '';
                            sb.addEventListener('click', function () { try{sessionStorage.setItem('jarvis_settings_return','/userchat');}catch(e){} window.location.href = '/settings'; });
                        }
                    }
                }).catch(function () {});
        }
    }
    function _startLlmStatus() {
        _checkLlmStatus();
        if (!_llmStatusTimer) _llmStatusTimer = setInterval(_checkLlmStatus, 30000);
    }

    // ─── WebSocket ──────────────────────────────────────────────
    function connectWS() {
        if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}//${location.host}/ws/users`);

        ws.addEventListener('open', () => {
            wsReady = true;
            ws.send(JSON.stringify({ type: 'auth', token }));
        });

        ws.addEventListener('message', (ev) => {
            try {
                handleMessage(JSON.parse(ev.data));
            } catch (e) { /* ignore */ }
        });

        ws.addEventListener('close', () => {
            wsReady = false;
            clearTimeout(reconnectTimer);
            if (_sessionInvalid) return;   // Berechtigung entzogen -> nicht wieder verbinden
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
                var _ucLogout = $('btn-uc-logout');
        if (_ucLogout && myUser) _ucLogout.title = window.t('userchat.logout_title').replace('{user}', myUser);
                updatePresence(msg.users || []);
                loadKnownUsers();   // bekannte Kollegen (auch offline) nachladen
                break;

            case 'history': {
                // Empfangene Chat-Histoire vom Server (alle Konversationen dieses Users)
                const convs = msg.conversations || {};
                for (const [partner, msgs] of Object.entries(convs)) {
                    _msgs[partner] = msgs;
                    // Ungelesene Nachrichten zählen
                    const unread = msgs.filter(m => m.from === partner && m.status !== 'read').length;
                    if (unread > 0) {
                        _unread[partner] = (_unread[partner] || 0) + unread;
                    }
                    // Partner in Userliste eintragen (offline) falls noch nicht bekannt
                    if (!_online.hasOwnProperty(partner)) {
                        _online[partner] = false;
                    }
                }
                renderUserList();
                _updateTabTitle();
                break;
            }

            case 'presence':
                updatePresence(msg.users || []);
                break;

            case 'dm': {
                const partner = msg.from === myUser ? msg.to : msg.from;
                if (!_msgs[partner]) _msgs[partner] = [];
                // Neuen Partner in Userliste aufnehmen falls noch nicht bekannt
                if (!_online.hasOwnProperty(partner)) _online[partner] = false;
                // Duplikat vermeiden (Echo der eigenen Nachricht + evtl. Reconnect)
                if (!_msgs[partner].some(m => m.msg_id && m.msg_id === msg.msg_id)) {
                    _msgs[partner].push(msg);
                }
                if (partner === activePartner) {
                    appendMessage(msg);
                    scrollToBottom();
                    // Sofort als gelesen markieren, wenn Chat offen ist
                    if (msg.from !== myUser) {
                        _markRead(partner);
                    }
                } else if (msg.from !== myUser) {
                    _unread[partner] = (_unread[partner] || 0) + 1;
                    renderUserList();
                }
                if (msg.from !== myUser) {
                    _showNotification(msg.from, msg.text);
                    _updateTabTitle();
                }
                break;
            }

            case 'msg_status': {
                // Gelesene Bestätigung für eigene Nachrichten
                const ids = msg.msg_ids || [];
                const partner = msg.conv_with;
                for (const id of ids) {
                    // Cache aktualisieren
                    if (partner && _msgs[partner]) {
                        for (const m of _msgs[partner]) {
                            if (m.msg_id === id) m.status = 'read';
                        }
                    }
                    // DOM-Tick aktualisieren
                    const el = _tickEls[id];
                    if (el) {
                        el.className = 'uc-ticks read';
                        el.textContent = '✓✓';
                    }
                }
                break;
            }

            case 'reaction': {
                const { msg_id, emoji, from, removed } = msg;
                // Partner ableiten (eigene Echo oder fremde Reaktion)
                const partner = from === myUser ? activePartner : from;
                if (partner && _msgs[partner]) {
                    for (const m of _msgs[partner]) {
                        if (m.msg_id === msg_id) {
                            if (!m.reactions) m.reactions = {};
                            if (removed) {
                                if (m.reactions[emoji]) {
                                    m.reactions[emoji] = m.reactions[emoji].filter(u => u !== from);
                                    if (m.reactions[emoji].length === 0) delete m.reactions[emoji];
                                }
                            } else {
                                if (!m.reactions[emoji]) m.reactions[emoji] = [];
                                if (!m.reactions[emoji].includes(from)) m.reactions[emoji].push(from);
                            }
                            break;
                        }
                    }
                }
                // DOM aktualisieren
                const rxnRow = messages.querySelector(`[data-msgid="${msg_id}"]`);
                if (rxnRow) {
                    const rxnEl = rxnRow.querySelector('.uc-reactions');
                    const cached = partner && _msgs[partner]
                        ? _msgs[partner].find(m => m.msg_id === msg_id) : null;
                    if (rxnEl && cached) renderReactions(rxnEl, cached.reactions || {}, msg_id);
                }
                break;
            }

            case 'typing':
                if (msg.from === activePartner) {
                    showTyping(msg.from);
                }
                break;

            case 'dm_edit': {
                const partner = msg.from === myUser ? msg.to : msg.from;
                if (_msgs[partner]) {
                    for (const m of _msgs[partner]) {
                        if (m.msg_id === msg.msg_id) {
                            m.text = msg.text;
                            m.edited_at = msg.edited_at;
                            break;
                        }
                    }
                }
                if (partner === activePartner) {
                    const row = messages.querySelector(`[data-msgid="${msg.msg_id}"]`);
                    if (row) {
                        const bub = row.querySelector('.uc-bubble');
                        if (bub) {
                            // Anhaenge bleiben - nur Text-Teil austauschen.
                            // Wir entfernen die fuehrenden Text-Nodes vor evt. Galerie/File-Chip.
                            const atts = bub.querySelectorAll('.uc-img-gallery, .uc-file-chip');
                            bub.innerHTML = linkify((msg.text || '').trim() || '');
                            atts.forEach(a => bub.appendChild(a));
                        }
                        // "(bearbeitet)" Marker im Footer ergaenzen
                        const footer = row.querySelector('.uc-msg-footer');
                        if (footer && !footer.querySelector('.uc-edited')) {
                            const mark = document.createElement('span');
                            mark.className = 'uc-edited';
                            mark.textContent = window.t('userchat.edited');
                            mark.title = window.t('userchat.edited_title');
                            footer.insertBefore(mark, footer.firstChild);
                        }
                    }
                }
                break;
            }

            case 'dm_delete': {
                const partner = msg.from === myUser ? msg.to : msg.from;
                if (_msgs[partner]) {
                    _msgs[partner] = _msgs[partner].filter(m => m.msg_id !== msg.msg_id);
                }
                if (partner === activePartner) {
                    const row = messages.querySelector(`[data-msgid="${msg.msg_id}"]`);
                    if (row && row.parentNode) row.parentNode.removeChild(row);
                }
                break;
            }

            case 'error':
                if (msg.message === 'Nicht autorisiert') {
                    // Token wirklich ungueltig -> ALLE Keys leeren (sonst Reload-Schleife durch SSO-Spiegelung)
                    localStorage.removeItem('jarvis_uc_token');
                    localStorage.removeItem('jarvis_token');
                    localStorage.removeItem('jarvis_chat_token');
                    localStorage.removeItem('jarvis_uc_user');
                    location.reload();
                }
                break;

            case 'security_blocked':
                if (window.SecurityIncidents) window.SecurityIncidents.fetchAndShowBlocked();
                break;

            case 'session_invalid':
                // Anmeldeberechtigung entzogen -> Hinweis, Keys leeren, KEIN Reconnect
                // (sonst stille 3s-Reconnect-Schleife gegen den 403).
                _sessionInvalid = true;
                clearTimeout(reconnectTimer);
                if (msg.message) alert(msg.message);
                localStorage.removeItem('jarvis_uc_token');
                localStorage.removeItem('jarvis_token');
                localStorage.removeItem('jarvis_chat_token');
                localStorage.removeItem('jarvis_uc_user');
                location.reload();
                break;
        }
    }

    // ─── Lesestatus melden ───────────────────────────────────────
    function _markRead(partner) {
        _unread[partner] = 0;
        renderUserList();
        _updateTabTitle();
        wsSend({ type: 'read', from: partner });
    }

    // ─── Presence / Userliste ────────────────────────────────────
    function updatePresence(users) {
        for (const k in _online) _online[k] = false;
        for (const u of users) {
            _online[u.username] = u.online;
        }
        if (myUser && !_online.hasOwnProperty(myUser)) {
            _online[myUser] = true;
        }
        renderUserList();
        if (activePartner) updatePartnerStatus();
    }

    // Bekannte Chat-Partner (auch offline) laden, damit man Kollegen anschreiben
    // kann, ohne dass sie gerade im Benutzerchat verbunden sind. Online-Status
    // aus /ws/users hat Vorrang (nicht ueberschreiben, wenn schon online bekannt).
    function loadKnownUsers() {
        fetch('/api/userchat/users', { headers: { 'Authorization': 'Bearer ' + token } })
            .then(r => r.ok ? r.json() : null)
            .then(d => {
                if (!d || !Array.isArray(d.users)) return;
                for (const u of d.users) {
                    if (!u || !u.username) continue;
                    if (!_online.hasOwnProperty(u.username)) _online[u.username] = !!u.online;
                    else if (u.online) _online[u.username] = true;
                }
                renderUserList();
            })
            .catch(() => {});
    }

    function renderUserList() {
        if (!userList) return;
        const allUsers = Object.keys(_online).sort((a, b) => {
            const ao = _online[a] ? 1 : 0;
            const bo = _online[b] ? 1 : 0;
            if (ao !== bo) return bo - ao;
            return a.localeCompare(b);
        });

        userList.innerHTML = '';
        for (const username of allUsers) {
            if (username === myUser) continue;   // eigener User wird nicht angezeigt

            const online   = _online[username];
            const unread   = _unread[username] || 0;
            const isActive = username === activePartner;

            const item = document.createElement('div');
            item.className = 'uc-user-item' + (isActive ? ' active' : '');
            item.dataset.username = username;

            item.innerHTML = `
                <div class="uc-avatar">
                    ${initial(username)}
                    <span class="uc-online-dot ${online ? 'online' : 'offline'}"></span>
                </div>
                <span class="uc-user-name ${online ? '' : 'offline'}">${escHtml(username)}</span>
                ${unread > 0 ? `<span class="uc-unread">${unread}</span>` : ''}
            `;

            item.addEventListener('click', () => openChat(username));
            userList.appendChild(item);
        }
    }

    // ─── Benutzer-Suche (AD-Verzeichnis) ─────────────────────────
    let _searchTimer = null, _searchInit = false;
    function initUserSearch() {
        if (_searchInit) return;
        const inp = $('uc-search'), box = $('uc-search-results');
        if (!inp || !box) return;
        _searchInit = true;
        function close() { box.innerHTML = ''; }
        inp.addEventListener('input', () => {
            const q = inp.value.trim();
            clearTimeout(_searchTimer);
            if (q.length < 2) { close(); return; }
            _searchTimer = setTimeout(() => {
                fetch('/api/userchat/search', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ q })
                }).then(r => r.ok ? r.json() : null)
                  .then(d => {
                      box.innerHTML = '';
                      if (!d) return;
                      if (d.error === 'NO_SERVICE_ACCOUNT') {
                          box.innerHTML = `<div class="uc-sr-hint">${escHtml(window.t('uc.search_no_ad'))}</div>`;
                          return;
                      }
                      const users = d.users || [];
                      if (!users.length) {
                          box.innerHTML = `<div class="uc-sr-hint">${escHtml(window.t('uc.search_none'))}</div>`;
                          return;
                      }
                      for (const u of users) {
                          const it = document.createElement('div');
                          it.className = 'uc-sr-item';
                          it.innerHTML = `
                              <div class="uc-avatar" style="width:30px;height:30px;">${initial(u.display || u.username)}</div>
                              <div style="min-width:0;">
                                  <div class="uc-sr-name">${escHtml(u.display || u.username)}</div>
                                  ${u.mail ? `<div class="uc-sr-sub">${escHtml(u.mail)}</div>` : ''}
                              </div>`;
                          it.addEventListener('click', () => {
                              if (!_online.hasOwnProperty(u.username)) _online[u.username] = false;
                              renderUserList();
                              openChat(u.username);
                              inp.value = ''; close();
                          });
                          box.appendChild(it);
                      }
                  }).catch(() => { close(); });
            }, 300);
        });
        // Klick ausserhalb schliesst die Trefferliste
        document.addEventListener('click', (e) => {
            if (!box.contains(e.target) && e.target !== inp) close();
        });
    }

    // ─── Chat öffnen ─────────────────────────────────────────────
    function openChat(username) {
        activePartner = username;

        // Header
        partnerAvatar.textContent = initial(username);
        partnerName.textContent   = username;
        updatePartnerStatus();

        // UI umschalten
        emptyState.style.display = 'none';
        chatArea.style.display   = 'flex';

        // Nachrichten anzeigen
        messages.innerHTML = '';
        // _tickEls für diesen Chat zurücksetzen
        for (const id of Object.keys(_tickEls)) delete _tickEls[id];

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

        // Ungelesene Nachrichten als gelesen markieren
        _markRead(username);

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

    // URLs in klickbare Links umwandeln (HTML-safe)
    function linkify(text) {
        const esc = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
        return esc.replace(
            /(https?:\/\/[^\s<>"{}|\\^`[\]]+|www\.[a-zA-Z0-9][^\s<>"{}|\\^`[\]]*)/gi,
            (url) => {
                const href = url.startsWith('www.') ? 'https://' + url : url;
                return `<a href="${href}" target="_blank" rel="noopener noreferrer">${url}</a>`;
            }
        );
    }

    const QUICK_REACTIONS = ['👍', '👎', '❤️', '😂', '😮'];

    function appendMessage(msg) {
        const mine = msg.from === myUser;
        const row  = document.createElement('div');
        row.className = 'uc-msg-row ' + (mine ? 'mine' : 'theirs');
        if (msg.msg_id) row.dataset.msgid = msg.msg_id;

        // Bubble-Wrapper (Position-Anchor für Reaction-Bar)
        const wrap = document.createElement('div');
        wrap.className = 'uc-bubble-wrap';

        // Reaction-Bar: 5 Quick-Emojis + "+" für mehr
        if (msg.msg_id) {
            const rbar = document.createElement('div');
            rbar.className = 'uc-reaction-bar ' + (mine ? 'mine' : 'theirs');
            for (const em of QUICK_REACTIONS) {
                const btn = document.createElement('span');
                btn.className = 'uc-reaction-quick';
                btn.textContent = em;
                btn.addEventListener('click', (e) => { e.stopPropagation(); sendReaction(msg.msg_id, em); });
                rbar.appendChild(btn);
            }
            const moreBtn = document.createElement('span');
            moreBtn.className = 'uc-reaction-more';
            moreBtn.textContent = '+';
            moreBtn.title = window.t('userchat.more_emojis');
            moreBtn.addEventListener('click', (e) => { e.stopPropagation(); openRxnPicker(msg.msg_id, moreBtn); });
            rbar.appendChild(moreBtn);
            wrap.appendChild(rbar);
        }

        const bubble = document.createElement('div');
        bubble.className = 'uc-bubble ' + (mine ? 'mine' : 'theirs');
        const displayText = (msg.text || '').trim();
        if (displayText && displayText !== ' ') bubble.innerHTML = linkify(displayText);
        _renderAttachments(bubble, msg);
        // Leere Bubble (weder Text noch Anhang) nicht als leere Pille rendern
        if (bubble.childNodes.length > 0) wrap.appendChild(bubble);

        // Reaktions-Pills (leer wenn keine vorhanden)
        const reactEl = document.createElement('div');
        reactEl.className = 'uc-reactions' + (mine ? ' mine' : '');
        if (msg.reactions && Object.keys(msg.reactions).length > 0) {
            renderReactions(reactEl, msg.reactions, msg.msg_id);
        }
        wrap.appendChild(reactEl);

        // Footer: Zeitstempel + ggf. Ticks
        const footer = document.createElement('div');
        footer.className = 'uc-msg-footer' + (mine ? ' mine' : '');
        if (msg.edited_at) {
            const mark = document.createElement('span');
            mark.className = 'uc-edited';
            mark.textContent = window.t('userchat.edited');
            mark.title = window.t('userchat.edited_title');
            footer.appendChild(mark);
        }
        const ts = document.createElement('span');
        ts.className = 'uc-ts';
        ts.textContent = formatTime(msg.ts);
        footer.appendChild(ts);
        if (mine && msg.msg_id) {
            const ticks = document.createElement('span');
            const isRead = msg.status === 'read';
            ticks.className = 'uc-ticks' + (isRead ? ' read' : '');
            ticks.textContent = isRead ? '✓✓' : '✓';
            footer.appendChild(ticks);
            _tickEls[msg.msg_id] = ticks;
        }

        row.appendChild(wrap);
        row.appendChild(footer);
        messages.appendChild(row);

        // ── Kontextmenue (Rechtsklick / Long-Press) ────────────────
        if (window.JarvisChatLib && window.JarvisChatLib.setupBubbleContextMenu) {
            window.JarvisChatLib.setupBubbleContextMenu(row, () => _buildDmCtxItems(row, bubble, msg));
        }

        // Im Auswahlmodus neue eigene Bubble direkt mit Checkbox versehen
        // (canSelectRow filtert auf .mine mit msgid)
        if (_selCtl && _selCtl.isActive()) _selCtl.addCheckboxToRow(row);
    }

    // ─── Kontextmenue: Bearbeiten/Loeschen/Kopieren/Antworten ─────
    function _buildDmCtxItems(row, bubble, msg) {
        const items = [];
        const mine = msg.from === myUser;
        const txt  = (msg.text || '').trim();
        if (mine) {
            // Edit nur fuer reine Text-Nachrichten (Anhaenge bleiben unangetastet)
            if (txt) {
                items.push({
                    label: (window.t ? window.t('bubble.ctx.edit') : 'Bearbeiten'), icon: '✏',
                    onClick: () => _editDmBubble(row, bubble, msg),
                });
            }
        }
        if (txt) {
            items.push({
                label: (window.t ? window.t('bubble.ctx.copy') : 'Text kopieren'), icon: '⧉',
                onClick: () => window.JarvisChatLib?.copyTextToClipboard?.(txt),
            });
        }
        if (mine && msg.msg_id) {
            items.push({
                label: (window.t ? window.t('bubble.ctx.delete') : 'Löschen'), icon: '×', danger: true,
                onClick: () => _selCtl.startSelectionDelete(row),
            });
        }
        return items;
    }

    // ─── Mehrfachauswahl: eigene Nachrichten per Checkbox loeschen ─
    //  Lebenszyklus in chatlib.js (createSelectionController). Nur eigene
    //  Nachrichten (.mine mit msgid) sind waehlbar. Geloescht wird ueber
    //  WebSocket (dm_delete) – das Server-Echo entfernt die Rows fuer
    //  beide Seiten, daher KEINE lokale DOM-Entfernung hier.
    const _selCtl = window.JarvisChatLib.createSelectionController({
        container: messages,
        rowSelector: '.uc-msg-row',
        checkboxClass: 'uc-msg-check',
        bar: msgSelectBar,
        countEl: msgSelectCount,
        delBtn: btnMsgDelSel,
        cancelBtn: btnMsgSelCancel,
        // Nur eigene Nachrichten mit Server-Message-ID sind loeschbar
        canSelectRow: (row) => row.classList.contains('mine') && !!row.dataset.msgid,
        onDelete: (checked) => {
            if (!activePartner) return;
            const ids = checked.map(r => r.dataset.msgid).filter(Boolean);
            for (const id of ids) {
                wsSend({ type: 'dm_delete', to: activePartner, msg_id: id });
            }
        },
    });

    let _dmEditingMsgId = null;
    function _editDmBubble(row, bubble, msg) {
        if (_dmEditingMsgId) return;
        if (!window.JarvisChatLib || !window.JarvisChatLib.enterEditMode) {
            alert(window.t('userchat.edit_lib_missing'));
            return;
        }
        row.dataset.rawText = msg.text || '';
        const ok = window.JarvisChatLib.enterEditMode(row, bubble, {
            editBtnSelector: '.__noop__',  // kein Edit-Button vorhanden
            areaClass:    'uc-edit-area',
            actionsClass: 'uc-edit-actions',
            saveClass:    'uc-edit-save',
            cancelClass:  'uc-edit-cancel',
            saveLabel:    window.t('common.save'),
            cancelLabel:  window.t('common.cancel'),
            onCommit: (newText) => {
                wsSend({ type: 'dm_edit', to: activePartner, msg_id: msg.msg_id, text: newText });
                // Bubble visuell zuruecksetzen (Echo vom Server aktualisiert dann den Text)
                bubble.classList.remove('editing');
                bubble.innerHTML = linkify(newText);
                _renderAttachments(bubble, Object.assign({}, msg, { text: newText }));
                delete bubble.dataset.origHtml;
                _dmEditingMsgId = null;
            },
            onCancel: () => { _dmEditingMsgId = null; },
        });
        if (ok) _dmEditingMsgId = msg.msg_id;
    }

    function _deleteDmBubble(row, msg) {
        if (!msg.msg_id || !activePartner) return;
        if (!confirm(window.t('userchat.confirm_delete_both'))) return;
        wsSend({ type: 'dm_delete', to: activePartner, msg_id: msg.msg_id });
        // DOM nicht sofort entfernen – warten auf Server-Echo, damit Fehlerfälle
        // (z.B. fremde Nachricht / nicht gefunden) sichtbar bleiben.
    }

    // ─── Reaktionen rendern ───────────────────────────────────────
    function renderReactions(el, reactions, msgId) {
        el.innerHTML = '';
        for (const [emoji, users] of Object.entries(reactions)) {
            if (!users || users.length === 0) continue;
            const pill = document.createElement('span');
            const isMine = users.includes(myUser);
            pill.className = 'uc-reaction-pill' + (isMine ? ' mine' : '');
            pill.innerHTML = `<span>${emoji}</span><span class="uc-rp-count">${users.length}</span>`;
            pill.title = users.join(', ');
            pill.addEventListener('click', () => sendReaction(msgId, emoji));
            el.appendChild(pill);
        }
    }

    function sendReaction(msgId, emoji) {
        if (!activePartner || !msgId) return;
        wsSend({ type: 'reaction', to: activePartner, msg_id: msgId, emoji });
    }

    // ─── Mini-Picker für Reaktionen ───────────────────────────────
    function openRxnPicker(msgId, anchorEl) {
        const picker = document.getElementById('uc-rxn-picker');
        if (!picker) return;
        // Toggle: bereits für diese Nachricht offen → schließen
        if (picker.classList.contains('open') && picker.dataset.msgid === msgId) {
            picker.classList.remove('open');
            return;
        }
        picker.dataset.msgid = msgId;
        // Position: über dem Anchor, innerhalb des Viewports bleiben
        const rect = anchorEl.getBoundingClientRect();
        const pw = 276, ph = 220;
        let left = Math.min(rect.right - pw, window.innerWidth - pw - 10);
        left = Math.max(left, 10);
        let top = rect.top - ph - 6;
        if (top < 10) top = rect.bottom + 6;
        picker.style.left = left + 'px';
        picker.style.top  = top  + 'px';
        picker.classList.add('open');
    }

    function initRxnPicker() {
        const picker = document.getElementById('uc-rxn-picker');
        if (!picker) return;
        const catsEl = document.createElement('div');
        catsEl.className = 'uc-rxn-cats';
        const gridEl = document.createElement('div');
        gridEl.className = 'uc-rxn-grid';
        picker.appendChild(catsEl);
        picker.appendChild(gridEl);

        let activeCat = EMOJI_CATS[0].id;
        function renderRxnGrid(emojis) {
            gridEl.innerHTML = '';
            for (const em of emojis) {
                const span = document.createElement('span');
                span.className = 'uc-rxn-emoji';
                span.textContent = em;
                span.addEventListener('click', () => {
                    const mid = picker.dataset.msgid;
                    if (mid) sendReaction(mid, em);
                    picker.classList.remove('open');
                });
                gridEl.appendChild(span);
            }
        }
        EMOJI_CATS.forEach(cat => {
            const tab = document.createElement('button');
            tab.type = 'button';
            tab.className = 'uc-rxn-cat' + (cat.id === activeCat ? ' active' : '');
            tab.title = cat.label;
            tab.textContent = cat.icon;
            tab.addEventListener('click', (e) => {
                e.stopPropagation();
                activeCat = cat.id;
                catsEl.querySelectorAll('.uc-rxn-cat').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                renderRxnGrid(cat.emojis);
            });
            catsEl.appendChild(tab);
        });
        renderRxnGrid(EMOJI_CATS[0].emojis);

        document.addEventListener('click', (e) => {
            if (picker.classList.contains('open') && !picker.contains(e.target)) {
                picker.classList.remove('open');
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') picker.classList.remove('open');
        });
        picker.addEventListener('click', (e) => e.stopPropagation());
    }

    function scrollToBottom() {
        messages.scrollTop = messages.scrollHeight;
    }

    // ─── Typing-Indikator ────────────────────────────────────────
    let _typingClearTimer = null;
    function showTyping(username) {
        typingEl.textContent = window.t('userchat.typing').replace('{user}', username);
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
        inputEl.style.height = 'auto';
        inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
        if (activePartner && !typingCooldown) {
            typingCooldown = true;
            wsSend({ type: 'typing', to: activePartner });
            setTimeout(() => { typingCooldown = false; }, 2000);
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    // ─── Logout ──────────────────────────────────────────────────
    const logoutBtn = $('btn-uc-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            // Global abmelden (SSO): alle Seiten-Token entfernen
            localStorage.removeItem('jarvis_uc_token');
            localStorage.removeItem('jarvis_token');
            localStorage.removeItem('jarvis_chat_token');
            localStorage.removeItem('jarvis_uc_user');
            if (ws) ws.close();
            location.reload();
        });
    }

    // ─── Datei-Anhänge ──────────────────────────────────────────
    const ucAttachBtn     = document.getElementById('uc-attach-btn');
    const ucAttachInput   = document.getElementById('uc-attach-input');
    const ucAttachPreview = document.getElementById('uc-attach-preview');
    const ucAttachToast   = document.getElementById('uc-attach-toast');
    let _ucPending = [];   // [{name, mime_type, data (base64), type}]

    const _UC_SUPPORTED_MIME = new Set([
        'image/jpeg','image/jpg','image/png','image/gif','image/webp','image/bmp',
        'audio/wav','audio/mp3','audio/mpeg','audio/ogg','audio/webm','audio/aac','audio/flac','audio/m4a','audio/x-m4a',
        'video/mp4','video/webm','video/ogg','video/quicktime','video/x-msvideo','video/mpeg',
        'application/pdf',
    ]);

    let _ucToastTimer = null;
    function showUcToast(msg) {
        if (!ucAttachToast) return;
        ucAttachToast.textContent = msg;
        ucAttachToast.classList.add('show');
        clearTimeout(_ucToastTimer);
        _ucToastTimer = setTimeout(() => ucAttachToast.classList.remove('show'), 4000);
    }

    function renderUcAttachPreview() {
        if (!ucAttachPreview) return;
        ucAttachPreview.innerHTML = '';
        if (_ucPending.length === 0) {
            ucAttachPreview.style.display = 'none';
            if (ucAttachBtn) ucAttachBtn.classList.remove('has-files');
            return;
        }
        ucAttachPreview.style.display = 'flex';
        if (ucAttachBtn) ucAttachBtn.classList.add('has-files');
        _ucPending.forEach((att, idx) => {
            const chip = document.createElement('div');
            chip.className = 'uc-attach-chip';
            if (att.type === 'image') {
                const img = document.createElement('img');
                img.src = `data:${att.mime_type};base64,${att.data}`;
                chip.appendChild(img);
            } else {
                const ico = document.createElement('span');
                ico.className = 'uc-attach-chip-icon';
                ico.textContent = att.type === 'audio' ? '🎵' : att.type === 'pdf' ? '📄' : '🎬';
                chip.appendChild(ico);
            }
            const nm = document.createElement('span');
            nm.className = 'uc-attach-chip-name';
            nm.textContent = att.name.length > 16 ? att.name.slice(0,14)+'…' : att.name;
            nm.title = att.name;
            chip.appendChild(nm);
            const rm = document.createElement('button');
            rm.className = 'uc-attach-chip-rm';
            rm.textContent = '×';
            rm.type = 'button';
            rm.addEventListener('click', () => { _ucPending.splice(idx, 1); renderUcAttachPreview(); });
            chip.appendChild(rm);
            ucAttachPreview.appendChild(chip);
        });
    }

    async function addUcFiles(files) {
        const MAX = 5;
        const unsupported = [];
        for (const file of Array.from(files)) {
            const mime = (file.type || '').toLowerCase();
            if (!_UC_SUPPORTED_MIME.has(mime) && !mime.startsWith('image/') && !mime.startsWith('audio/') && !mime.startsWith('video/')) {
                const ext = file.name.includes('.') ? '.'+file.name.split('.').pop().toUpperCase() : mime||'?';
                unsupported.push(ext);
                continue;
            }
            if (_ucPending.length >= MAX) { showUcToast(window.t('userchat.max_files').replace('{n}', MAX)); break; }
            let type = 'video';
            if (mime.startsWith('image/')) type = 'image';
            else if (mime.startsWith('audio/')) type = 'audio';
            else if (mime === 'application/pdf') type = 'pdf';
            // Größenlimit: 5 MB
            if (file.size > 5 * 1024 * 1024) { showUcToast(window.t('userchat.file_too_large').replace('{name}', file.name)); continue; }
            try {
                const b64 = await new Promise((res, rej) => {
                    const r = new FileReader();
                    r.onload = e => res(e.target.result.split(',')[1]);
                    r.onerror = rej;
                    r.readAsDataURL(file);
                });
                _ucPending.push({ name: file.name, mime_type: mime, data: b64, type });
            } catch (e) { showUcToast(window.t('userchat.file_read_error').replace('{name}', file.name)); }
        }
        if (unsupported.length > 0) {
            const fmts = [...new Set(unsupported)].join(', ');
            showUcToast(window.t('userchat.format_unsupported').replace('{fmts}', fmts));
        }
        renderUcAttachPreview();
    }

    if (ucAttachBtn) ucAttachBtn.addEventListener('click', () => ucAttachInput && ucAttachInput.click());
    if (ucAttachInput) {
        ucAttachInput.addEventListener('change', async () => {
            await addUcFiles(ucAttachInput.files);
            ucAttachInput.value = '';
        });
    }

    // Drag & Drop auf Nachrichten-Bereich
    const _ucMsgArea = document.getElementById('uc-messages');
    if (_ucMsgArea) {
        _ucMsgArea.addEventListener('dragover', e => { e.preventDefault(); _ucMsgArea.classList.add('uc-drag-over'); });
        _ucMsgArea.addEventListener('dragleave', e => { if (!_ucMsgArea.contains(e.relatedTarget)) _ucMsgArea.classList.remove('uc-drag-over'); });
        _ucMsgArea.addEventListener('drop', async e => {
            e.preventDefault(); _ucMsgArea.classList.remove('uc-drag-over');
            if (e.dataTransfer && e.dataTransfer.files.length > 0) await addUcFiles(e.dataTransfer.files);
        });
    }

    function sendMessage() {
        const text = inputEl.value.trim();
        if (!text && _ucPending.length === 0) return;
        if (!activePartner) return;
        const msg = { type: 'dm', to: activePartner, text: text || ' ' };
        if (_ucPending.length > 0) {
            msg.attachments = _ucPending.map(a => ({ name: a.name, mime_type: a.mime_type, data: a.data }));
        }
        wsSend(msg);
        inputEl.value = '';
        inputEl.style.height = 'auto';
        _ucPending = [];
        renderUcAttachPreview();
        inputEl.focus();
    }

    // ─── Emoji-Picker ────────────────────────────────────────────
    const EMOJI_CATS = [
        { id: 'smileys', icon: '😀', label: window.t('userchat.cat_smileys'), emojis: [
            '😀','😃','😄','😁','😆','😅','🤣','😂','🙂','🙃','🫠','😉','😊','😇',
            '🥰','😍','🤩','😘','😗','😚','😙','🥲','😋','😛','😜','🤪','😝','🤑',
            '🤗','🫡','🤭','🫢','🫣','🤫','🤔','😐','😑','😶','😏','😒','🙄','😬',
            '🤥','😌','😔','😪','🤤','😴','😷','🤒','🤕','🤢','🤮','🤧','🥵','🥶',
            '🥴','😵','💫','🤯','🤠','🥸','😎','🤓','🧐','😕','😟','🙁','☹️','😮',
            '😯','😲','😳','🥺','🥹','😦','😧','😨','😰','😥','😢','😭','😱','😖',
            '😣','😞','😓','😩','😫','🥱','😤','😡','😠','🤬','😈','👿','💀','☠️',
            '💩','🤡','👹','👺','👻','👽','👾','🤖',
        ]},
        { id: 'people', icon: '👋', label: window.t('userchat.cat_people'), emojis: [
            '👋','🤚','🖐️','✋','🖖','🫱','🫲','👌','🤌','🤏','✌️','🤞','🫰','🤟',
            '🤘','🤙','👈','👉','👆','🖕','👇','☝️','🫵','👍','👎','✊','👊','🤛',
            '🤜','👏','🙌','🫶','🤲','🤝','🙏','💪','🦾','🫀','🦷','👀','👁️','👅',
            '👃','💋','💅','🤳','🧠','🦴','👶','🧒','👦','👧','🧑','👱','👨','🧔',
            '👩','🧓','👴','👵','🙍','🙎','🙅','🙆','💁','🙋','🧏','🙇','🤦','🤷',
        ]},
        { id: 'hearts', icon: '❤️', label: window.t('userchat.cat_hearts'), emojis: [
            '❤️','🧡','💛','💚','💙','💜','🖤','🤍','🤎','💔','❤️‍🔥','❤️‍🩹',
            '💕','💞','💓','💗','💖','💘','💝','💟','💌','💍','💎','🌹','🫦',
            '😻','💑','👫','👬','👭','💏','🥂','🍾','🎉','🎊','🎁','🎀','🎈',
        ]},
        { id: 'nature', icon: '🌿', label: window.t('userchat.cat_nature'), emojis: [
            '🐶','🐱','🐭','🐹','🐰','🦊','🐻','🐼','🐨','🐯','🦁','🐮','🐷',
            '🐸','🐵','🙈','🙉','🙊','🐔','🐧','🐦','🦆','🦅','🦉','🦇','🐝',
            '🦋','🐛','🐌','🐠','🐟','🐡','🐬','🐳','🦈','🐊','🦎','🐍','🦕',
            '🌸','🌺','🌻','🌹','🌷','🌼','💐','🍄','🌲','🌳','🌴','🌵','🎋',
            '🌾','🌿','☘️','🍀','🍁','🍂','🍃','🌍','🌙','⭐','☀️','🌈','❄️',
            '🌊','🔥','💧','🌬️','⚡','🌀','🌪️','🌫️','🌦️','⛅','☁️','🌤️',
        ]},
        { id: 'food', icon: '🍕', label: window.t('userchat.cat_food'), emojis: [
            '🍎','🍊','🍋','🍇','🍓','🫐','🍒','🍑','🥭','🍍','🥥','🥝','🍅',
            '🥑','🍆','🥦','🥕','🌽','🌶️','🧄','🧅','🍞','🥐','🥨','🧀','🥚',
            '🍳','🥓','🥩','🍗','🍖','🌭','🍔','🍟','🍕','🌮','🌯','🥗','🥙',
            '🍜','🍝','🍛','🍣','🍱','🍤','🍦','🍧','🍨','🍩','🍪','🎂','🍰',
            '🧁','🍫','🍬','🍭','☕','🍵','🧃','🥤','🧋','🍺','🍻','🥂','🍷',
            '🥃','🍸','🍹','🧉','🥛','🍼',
        ]},
        { id: 'travel', icon: '✈️', label: window.t('userchat.cat_travel'), emojis: [
            '🚀','🛸','✈️','🚁','🛩️','🪂','🚂','🚄','🚇','🚌','🚎','🏎️','🚑',
            '🚒','🚓','🚕','🛻','🚗','🚙','🛵','🏍️','🚲','🛴','🛹','⛵','🚤',
            '🛥️','🚢','🏔️','⛰️','🌋','🏕️','🏖️','🏜️','🏝️','🏛️','🏗️','🏙️',
            '🗼','🗽','🏰','🏯','🎡','🎢','🎪','🎭','🎨','🗺️','🧭','🏠','🏡',
            '🏢','🏣','🏤','🏥','🏦','🏧','🏨','🏩','🏪','🏫','🏬','🏭','🗾',
        ]},
        { id: 'objects', icon: '💡', label: window.t('userchat.cat_objects'), emojis: [
            '⌚','📱','💻','⌨️','🖥️','🖨️','🖱️','📷','📸','📹','🎥','📽️','📞',
            '☎️','📡','💡','🔦','🕯️','🔭','🔬','🧪','💊','💉','🩺','🩹','🩻',
            '🔑','🗝️','🔒','🔓','🔐','📚','📖','📝','✏️','🖊️','📌','📍','📎',
            '✂️','🗑️','🔧','🔨','⚙️','🔩','🪛','💰','💵','💳','💎','🎁','🎀',
            '🎊','🎉','🎈','🎆','🎇','🧨','🪔','🪄','🎭','🎨','🖼️','🎪','🎠',
        ]},
        { id: 'symbols', icon: '💯', label: window.t('userchat.cat_symbols'), emojis: [
            '💯','✅','❌','❓','❗','⬆️','⬇️','➡️','⬅️','↩️','↪️','🔄','🔃',
            '🔴','🟠','🟡','🟢','🔵','🟣','⚫','⚪','🟤','🔶','🔷','🔸','🔹',
            '🔺','🔻','💠','🔘','🔲','🔳','▪️','▫️','◾','◽','◼️','◻️','⭕','🅰️',
            '⚽','🏀','🏈','⚾','🥎','🎾','🏐','🏉','🥏','🏓','🏸','🥊','🥋',
            '⛷️','🏂','🏄','🤽','🚴','🏆','🥇','🥈','🥉','🏅','🎗️','🎵','🎶',
            '🎤','🎧','🎷','🎸','🥁','🎹','🎺','🎻','🎮','🕹️','🎲','♟️','🎯',
        ]},
    ];

    function initEmojiPicker() {
        const btn    = document.getElementById('uc-emoji-btn');
        const picker = document.getElementById('uc-emoji-picker');
        const search = document.getElementById('uc-emoji-search');
        const cats   = document.getElementById('uc-emoji-cats');
        const grid   = document.getElementById('uc-emoji-grid');
        if (!btn || !picker) return;

        let activeCat = EMOJI_CATS[0].id;
        let pickerOpen = false;

        // Kategorie-Tabs rendern
        EMOJI_CATS.forEach(cat => {
            const tab = document.createElement('button');
            tab.className = 'uc-emoji-cat' + (cat.id === activeCat ? ' active' : '');
            tab.title = cat.label;
            tab.textContent = cat.icon;
            tab.type = 'button';
            tab.addEventListener('click', () => {
                activeCat = cat.id;
                search.value = '';
                cats.querySelectorAll('.uc-emoji-cat').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                renderGrid(cat.emojis);
            });
            cats.appendChild(tab);
        });

        function renderGrid(list) {
            grid.innerHTML = '';
            if (list.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'uc-ep-empty';
                empty.textContent = window.t('userchat.no_emojis');
                grid.appendChild(empty);
                return;
            }
            list.forEach(em => {
                const span = document.createElement('span');
                span.className = 'uc-ep-emoji';
                span.textContent = em;
                span.title = em;
                span.addEventListener('click', () => insertEmoji(em));
                grid.appendChild(span);
            });
        }

        function insertEmoji(em) {
            const start = inputEl.selectionStart ?? inputEl.value.length;
            const end   = inputEl.selectionEnd   ?? inputEl.value.length;
            inputEl.value = inputEl.value.slice(0, start) + em + inputEl.value.slice(end);
            const pos = start + em.length;
            inputEl.selectionStart = inputEl.selectionEnd = pos;
            inputEl.focus();
            inputEl.dispatchEvent(new Event('input'));
        }

        function openPicker() {
            pickerOpen = true;
            picker.style.display = 'flex';
            picker.style.flexDirection = 'column';
            btn.classList.add('open');
            search.value = '';
            renderGrid(EMOJI_CATS.find(c => c.id === activeCat).emojis);
            search.focus();
        }

        function closePicker() {
            pickerOpen = false;
            picker.style.display = 'none';
            btn.classList.remove('open');
        }

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            pickerOpen ? closePicker() : openPicker();
        });

        // Suche
        search.addEventListener('input', () => {
            const q = search.value.trim().toLowerCase();
            if (!q) {
                cats.querySelectorAll('.uc-emoji-cat').forEach(t =>
                    t.classList.toggle('active', t.title === EMOJI_CATS.find(c => c.id === activeCat).label));
                renderGrid(EMOJI_CATS.find(c => c.id === activeCat).emojis);
                return;
            }
            // Alle Emojis durchsuchen (Text-basiert: kein Name-Dict → Emoji selbst matchen)
            const all = EMOJI_CATS.flatMap(c => c.emojis);
            // Einfacher Ansatz: Kategorielabel-Suche + Unicode-Range-Heuristik
            // Zumindest: alle Emojis zeigen, wenn Suchbegriff eine Kategorie trifft
            const matchCats = EMOJI_CATS.filter(c => c.label.toLowerCase().includes(q));
            const result = matchCats.length
                ? matchCats.flatMap(c => c.emojis)
                : all; // Fallback: alle anzeigen
            cats.querySelectorAll('.uc-emoji-cat').forEach(t => t.classList.remove('active'));
            renderGrid(result);
        });

        // Schließen bei Klick außerhalb
        document.addEventListener('click', (e) => {
            if (pickerOpen && !picker.contains(e.target) && e.target !== btn) {
                closePicker();
            }
        });

        // Escape schließt Picker
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && pickerOpen) closePicker();
        });

        // Picker nicht schließen wenn darin geklickt wird
        picker.addEventListener('click', (e) => e.stopPropagation());
    }

    // ═══════════════════════════════════════════════════════════════
    // ANHANG-RENDERING – Bilder, Audio, Video, PDF
    // ═══════════════════════════════════════════════════════════════

    // Alle Bilder der aktuell geöffneten Lightbox
    let _lbAtts = [], _lbIdx = 0, _lbMsg = null;

    function _dataUrl(att) {
        return `data:${att.mime_type};base64,${att.data}`;
    }

    // ── Lightbox ─────────────────────────────────────────────────
    function openLightbox(atts, idx, msg) {
        _lbAtts = atts; _lbIdx = idx; _lbMsg = msg;
        _lbUpdate();
        const lb = document.getElementById('uc-lightbox');
        if (lb) lb.classList.add('open');
    }
    function closeLightbox() {
        const lb = document.getElementById('uc-lightbox');
        if (lb) lb.classList.remove('open');
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
        const lb   = document.getElementById('uc-lightbox');
        if (!lb) return;
        document.getElementById('uc-lb-close')?.addEventListener('click', closeLightbox);
        document.getElementById('uc-lb-prev')?.addEventListener('click', () => {
            _lbIdx = (_lbIdx - 1 + _lbAtts.length) % _lbAtts.length; _lbUpdate();
        });
        document.getElementById('uc-lb-next')?.addEventListener('click', () => {
            _lbIdx = (_lbIdx + 1) % _lbAtts.length; _lbUpdate();
        });
        document.getElementById('uc-lb-save')?.addEventListener('click', () => {
            const att = _lbAtts[_lbIdx];
            const a = Object.assign(document.createElement('a'), {href: _dataUrl(att), download: att.name || 'bild'});
            a.click();
        });
        document.getElementById('uc-lb-fwd')?.addEventListener('click', () => {
            openFwdModal(_lbAtts[_lbIdx]);
            closeLightbox();
        });
        lb.addEventListener('click', e => { if (e.target === lb) closeLightbox(); });
    })();

    // ── Kontextmenü ───────────────────────────────────────────────
    let _ctxAtt = null;
    function showCtxMenu(e, att, msg) {
        e.preventDefault();
        e.stopPropagation();
        _ctxAtt = att;
        const menu = document.getElementById('uc-ctx-menu');
        if (!menu) return;
        const x = Math.min(e.clientX, window.innerWidth - 180);
        const y = Math.min(e.clientY, window.innerHeight - 90);
        menu.style.left = x + 'px';
        menu.style.top  = y + 'px';
        menu.classList.add('open');
    }
    function hideCtxMenu() {
        document.getElementById('uc-ctx-menu')?.classList.remove('open');
    }
    document.addEventListener('click', hideCtxMenu);
    document.addEventListener('contextmenu', e => {
        // Schließen wenn außerhalb des Menüs
        if (!document.getElementById('uc-ctx-menu')?.contains(e.target)) hideCtxMenu();
    });

    (function initCtxMenu() {
        document.getElementById('uc-ctx-save-btn')?.addEventListener('click', () => {
            if (!_ctxAtt) return;
            const a = Object.assign(document.createElement('a'), {href: _dataUrl(_ctxAtt), download: _ctxAtt.name || 'datei'});
            a.click();
            hideCtxMenu();
        });
        document.getElementById('uc-ctx-fwd-btn')?.addEventListener('click', () => {
            if (_ctxAtt) openFwdModal(_ctxAtt);
            hideCtxMenu();
        });
    })();

    // ── Weiterleiten ──────────────────────────────────────────────
    let _fwdAtt = null;
    function openFwdModal(att) {
        _fwdAtt = att;
        const list = document.getElementById('uc-fwd-list');
        const overlay = document.getElementById('uc-fwd-overlay');
        if (!list || !overlay) return;
        list.innerHTML = '';
        const users = Object.keys(_online).filter(u => u !== myUser);
        if (users.length === 0) {
            list.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem;text-align:center;padding:8px 0;">' + window.t('userchat.no_other_users') + '</p>';
        } else {
            users.sort((a,b) => (_online[b]?1:0) - (_online[a]?1:0) || a.localeCompare(b));
            for (const u of users) {
                const row = document.createElement('div');
                row.className = 'uc-fwd-user';
                row.innerHTML = `
                    <div class="uc-fwd-avatar">${initial(u)}</div>
                    <span style="flex:1;font-size:0.9rem;">${escHtml(u)}</span>
                    <span class="uc-online-dot ${_online[u]?'online':'offline'}" style="width:8px;height:8px;border-radius:50%;flex-shrink:0;"></span>`;
                row.addEventListener('click', () => { forwardTo(u, att); closeFwdModal(); });
                list.appendChild(row);
            }
        }
        overlay.style.display = 'flex';
    }
    function closeFwdModal() {
        const overlay = document.getElementById('uc-fwd-overlay');
        if (overlay) overlay.style.display = 'none';
        _fwdAtt = null;
    }
    function forwardTo(toUser, att) {
        wsSend({ type: 'dm', to: toUser, text: '', attachments: [{ name: att.name, mime_type: att.mime_type, data: att.data }] });
    }

    document.getElementById('uc-fwd-cancel')?.addEventListener('click', closeFwdModal);
    document.getElementById('uc-fwd-overlay')?.addEventListener('click', e => {
        if (e.target === document.getElementById('uc-fwd-overlay')) closeFwdModal();
    });

    // ── Long-Press für Mobile ────────────────────────────────────
    function addLongPress(el, callback) {
        let timer = null;
        el.addEventListener('touchstart', e => { timer = setTimeout(() => callback(e.touches[0]), 600); }, {passive: true});
        el.addEventListener('touchend', () => clearTimeout(timer));
        el.addEventListener('touchmove', () => clearTimeout(timer));
    }

    // ── Anhang-Rendering ──────────────────────────────────────────
    function _renderAttachments(bubble, msg) {
        const atts = msg.attachments || [];
        if (atts.length === 0) return;

        const imgAtts   = atts.filter(a => (a.mime_type||'').startsWith('image/'));
        const otherAtts = atts.filter(a => !(a.mime_type||'').startsWith('image/'));

        // ── Bildergalerie ────────────────────────────────────────
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
                img.alt = att.name || window.t('userchat.image');
                img.loading = 'lazy';
                cell.appendChild(img);

                // "+N mehr" Overlay auf letzter sichtbarer Zelle
                if (i === MAX - 1 && imgAtts.length > MAX) {
                    const ov = document.createElement('div');
                    ov.className = 'uc-ig-more';
                    ov.textContent = '+' + (imgAtts.length - MAX + 1);
                    cell.appendChild(ov);
                }

                // Klick → Lightbox
                cell.addEventListener('click', e => { e.stopPropagation(); openLightbox(imgAtts, i, msg); });
                // Rechtsklick → Kontextmenü
                cell.addEventListener('contextmenu', e => showCtxMenu(e, att, msg));
                addLongPress(cell, e => showCtxMenu(e, att, msg));

                gallery.appendChild(cell);
            });
            bubble.appendChild(gallery);
        }

        // ── Andere Dateien ────────────────────────────────────────
        for (const att of otherAtts) {
            bubble.appendChild(_renderFileChip(att, msg));
        }
    }

    function _renderFileChip(att, msg) {
        const mime = (att.mime_type || '').toLowerCase();
        const src  = _dataUrl(att);
        const wrap = document.createElement('div');
        wrap.className = 'uc-file-chip';
        wrap.style.marginTop = '4px';

        if (mime.startsWith('audio/')) {
            wrap.classList.add('audio');
            wrap.innerHTML = `<div class="uc-fc-icon">🎵</div>
                <div class="uc-fc-info">
                    <span class="uc-fc-name" title="${escHtml(att.name||'')}">${escHtml(att.name||'Audio')}</span>
                    <span class="uc-fc-badge">Audio</span>
                </div>`;
            const player = document.createElement('audio');
            player.controls = true; player.src = src; player.className = 'uc-fc-player';
            wrap.appendChild(player);
        } else if (mime.startsWith('video/')) {
            wrap.classList.add('video');
            wrap.innerHTML = `<div class="uc-fc-icon">🎬</div>
                <div class="uc-fc-info">
                    <span class="uc-fc-name" title="${escHtml(att.name||'')}">${escHtml(att.name||'Video')}</span>
                    <span class="uc-fc-badge">Video</span>
                </div>`;
            const player = document.createElement('video');
            player.controls = true; player.src = src; player.className = 'uc-fc-player'; player.style.maxWidth='220px';
            wrap.appendChild(player);
        } else {
            // PDF + alle anderen
            const isPdf = mime === 'application/pdf';
            wrap.classList.add(isPdf ? 'pdf' : 'other');
            const icon = isPdf ? '📄' : '📎';
            const badge = isPdf ? 'PDF' : att.name?.split('.').pop()?.toUpperCase() || window.t('userchat.file');
            wrap.innerHTML = `<div class="uc-fc-icon">${icon}</div>
                <div class="uc-fc-info" style="flex:1;min-width:0;">
                    <span class="uc-fc-name" title="${escHtml(att.name||'')}">${escHtml(att.name||window.t('userchat.file'))}</span>
                    <span class="uc-fc-badge">${escHtml(badge)}</span>
                </div>
                <a class="uc-fc-dl" href="${src}" download="${escHtml(att.name||'datei')}" title="${escHtml(window.t('userchat.download'))}" onclick="event.stopPropagation()">⬇</a>`;
            wrap.addEventListener('contextmenu', e => showCtxMenu(e, att, msg));
            addLongPress(wrap, e => showCtxMenu(e, att, msg));
        }
        return wrap;
    }

    initRxnPicker();
    initEmojiPicker();

})();
