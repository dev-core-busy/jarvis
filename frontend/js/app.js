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
    const thinkingBar = document.getElementById('llm-thinking-bar');
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
            const payload = { username, password };
            // TOTP-Code mitschicken falls Feld sichtbar
            const totpRow = document.getElementById('totp-row');
            const totpInput = document.getElementById('login-totp');
            if (totpRow && totpRow.style.display !== 'none' && totpInput && totpInput.value.trim()) {
                payload.totp_code = totpInput.value.trim();
            }

            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await res.json();

            if (data.success) {
                token = data.token;
                currentUser = data.username || username;
                localStorage.setItem('jarvis_token', token);
                localStorage.setItem('jarvis_user', currentUser);
                if (totpRow) totpRow.style.display = 'none';
                if (totpInput) totpInput.value = '';
                if (data.must_change_password) {
                    showChangePwModal(true);
                } else {
                    showMainScreen();
                }
            } else if (data.requires_totp) {
                // Passwort korrekt, 2FA-Code nötig → TOTP-Feld einblenden
                if (totpRow) totpRow.style.display = '';
                if (totpInput) totpInput.focus();
                if (data.error && data.error !== '2FA-Code erforderlich') {
                    loginError.textContent = data.error;
                    loginError.hidden = false;
                }
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

    // ─── Eye-Toggle Hilfsfunktion (global im IIFE) ──────────────
    const _SVG_EYE_OPEN   = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
    const _SVG_EYE_CLOSED = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;

    function _wireEyeBtn(btnId, inputEl) {
        const btn = document.getElementById(btnId);
        if (!btn || !inputEl) return;
        btn.addEventListener('click', () => {
            const isHidden = inputEl.type === 'password';
            inputEl.type = isHidden ? 'text' : 'password';
            btn.innerHTML = isHidden ? _SVG_EYE_CLOSED : _SVG_EYE_OPEN;
        });
    }

    // Login-Kennwort Eye-Toggle
    _wireEyeBtn('btn-toggle-login-pw', document.getElementById('login-password'));

    // ─── Screen-Wechsel ─────────────────────────────────────────
    function showMainScreen() {
        loginScreen.classList.remove('active');
        mainScreen.classList.add('active');
        connectWebSocket();
        initVNC();
        loadVersion();
        updateWidget.init();
    }

    // ─── Kennwort-Änderungs-Modal ────────────────────────────────
    const changePwModal = document.getElementById('change-password-modal');
    const cpwOld     = document.getElementById('cpw-old');
    const cpwNew     = document.getElementById('cpw-new');
    const cpwConfirm = document.getElementById('cpw-confirm');
    const cpwError   = document.getElementById('cpw-error');
    const cpwStrength = document.getElementById('cpw-strength');
    const cpwSubmit  = document.getElementById('cpw-submit');
    const cpwCancel  = document.getElementById('cpw-cancel');
    let _cpwMandatory = false; // true = Pflicht (erstes Login)

    // Eye-Buttons im Change-Password-Modal verdrahten
    _wireEyeBtn('btn-eye-cpw-old',     document.getElementById('cpw-old'));
    _wireEyeBtn('btn-eye-cpw-new',     document.getElementById('cpw-new'));
    _wireEyeBtn('btn-eye-cpw-confirm', document.getElementById('cpw-confirm'));

    function showChangePwModal(mandatory) {
        _cpwMandatory = mandatory;
        if (changePwModal) changePwModal.classList.add('open');
        if (cpwCancel) cpwCancel.style.display = mandatory ? 'none' : '';
        if (cpwOld) cpwOld.value = '';
        if (cpwNew) { cpwNew.type = 'password'; cpwNew.value = ''; cpwNew.removeEventListener('input', _cpwStrengthCheck); cpwNew.addEventListener('input', _cpwStrengthCheck); }
        if (cpwConfirm) { cpwConfirm.type = 'password'; cpwConfirm.value = ''; }
        if (cpwOld) cpwOld.type = 'password';
        // Eye-Icons zurücksetzen
        ['btn-eye-cpw-old','btn-eye-cpw-new','btn-eye-cpw-confirm'].forEach(id => {
            const b = document.getElementById(id); if (b) b.innerHTML = _SVG_EYE_OPEN;
        });
        if (cpwError) cpwError.style.display = 'none';
        if (cpwStrength) cpwStrength.textContent = '';
    }

    function hideChangePwModal() {
        if (changePwModal) changePwModal.classList.remove('open');
    }

    function _cpwStrengthCheck() {
        if (!cpwStrength || !cpwNew) return;
        const pw = cpwNew.value;
        const checks = [
            pw.length >= 8,
            /[A-Z]/.test(pw),
            /[a-z]/.test(pw),
            /[0-9]/.test(pw),
        ];
        const score = checks.filter(Boolean).length;
        const labels = ['Sehr schwach', 'Schwach', 'Mittel', 'Stark', 'Sehr stark'];
        const colors = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#16a34a'];
        if (pw.length === 0) { cpwStrength.textContent = ''; return; }
        cpwStrength.innerHTML = `<span style="color:${colors[score]}">● ${labels[score]}</span>`;
    }

    // Sicheres zufälliges Kennwort generieren (mittlere+ Stärke)
    function _generateStrongPassword() {
        const upper  = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
        const lower  = 'abcdefghjkmnpqrstuvwxyz';
        const digits = '23456789';
        const special = '!@#$%&*+-?';
        const all = upper + lower + digits + special;
        const arr = new Uint8Array(14);
        crypto.getRandomValues(arr);
        let pw = '';
        // Mindestens je 1 aus jeder Gruppe sicherstellen
        pw += upper[arr[0] % upper.length];
        pw += lower[arr[1] % lower.length];
        pw += digits[arr[2] % digits.length];
        pw += special[arr[3] % special.length];
        for (let i = 4; i < 14; i++) pw += all[arr[i] % all.length];
        // Mischen
        pw = pw.split('').sort(() => (crypto.getRandomValues(new Uint8Array(1))[0] % 3) - 1).join('');
        return pw;
    }

    const cpwSuggest = document.getElementById('cpw-suggest');
    if (cpwSuggest && cpwNew && cpwConfirm) {
        cpwSuggest.addEventListener('click', () => {
            const pw = _generateStrongPassword();
            cpwNew.type = 'text';
            cpwNew.value = pw;
            cpwConfirm.value = pw;
            _cpwStrengthCheck();
        });
    }

    if (cpwCancel) {
        cpwCancel.addEventListener('click', () => {
            hideChangePwModal();
        });
    }

    if (cpwSubmit) {
        cpwSubmit.addEventListener('click', async () => {
            if (cpwError) cpwError.style.display = 'none';
            const old_pw = cpwOld ? cpwOld.value : '';
            const new_pw = cpwNew ? cpwNew.value : '';
            const conf_pw = cpwConfirm ? cpwConfirm.value : '';
            if (!old_pw || !new_pw || !conf_pw) {
                if (cpwError) { cpwError.textContent = 'Alle Felder ausfüllen.'; cpwError.style.display = ''; }
                return;
            }
            cpwSubmit.disabled = true;
            cpwSubmit.textContent = 'Speichere...';
            try {
                const res = await fetch('/api/change-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                    body: JSON.stringify({ old_password: old_pw, new_password: new_pw, confirm_password: conf_pw }),
                });
                const data = await res.json();
                if (data.success) {
                    hideChangePwModal();
                    if (_cpwMandatory) {
                        showMainScreen();
                    } else {
                        addLogEntry('✅ Kennwort erfolgreich geändert.', 'system');
                    }
                } else {
                    if (cpwError) { cpwError.textContent = data.error || 'Fehler beim Ändern.'; cpwError.style.display = ''; }
                }
            } catch (e) {
                if (cpwError) { cpwError.textContent = 'Server nicht erreichbar.'; cpwError.style.display = ''; }
            } finally {
                cpwSubmit.disabled = false;
                cpwSubmit.textContent = 'Kennwort speichern';
            }
        });
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

    // ─── Update-Widget ────────────────────────────────────────────
    const updateWidget = (() => {
        const widget   = document.getElementById('update-widget');
        const dropdown = document.getElementById('update-dropdown');
        const badge    = document.getElementById('update-badge');
        const verEl    = document.getElementById('update-version');
        const body     = document.getElementById('upd-body');
        let _open = false;
        let _checkTimer = null;

        function init() {
            if (!widget) return;
            widget.addEventListener('click', toggle);
            document.getElementById('upd-close')?.addEventListener('click', close);
            // Klick außerhalb schließt Dropdown
            document.addEventListener('click', e => {
                if (_open && !widget.contains(e.target) && !dropdown?.contains(e.target)) close();
            });
            // Sofort prüfen, danach alle 30 Min
            _check();
            _checkTimer = setInterval(_check, 30 * 60 * 1000);
        }

        function toggle() { _open ? close() : open(); }

        function open() {
            _open = true;
            dropdown?.classList.remove('hidden');
            _check();
        }

        function close() {
            _open = false;
            dropdown?.classList.add('hidden');
        }

        async function _check() {
            try {
                const r = await fetch('/api/update/status', { headers: _authHeaders() });
                if (!r.ok) return;
                const d = await r.json();
                _render(d);
            } catch (e) { /* offline */ }
        }

        function _render(d) {
            // Version im Widget
            if (verEl) verEl.textContent = 'v' + (d.jarvis_version || '?');

            // Badge
            if (badge) {
                badge.style.display = d.has_update ? 'inline' : 'none';
                badge.className = 'update-badge' + (d.has_update ? ' has-update' : '');
                badge.title = d.has_update ? `${d.commits_behind} Commit(s) verfügbar` : '';
            }

            if (!body) return;

            // Auto-Update-Einstellung laden
            fetch('/api/update/settings', { headers: _authHeaders() })
                .then(r => r.json())
                .then(s => _buildBody(d, s.auto_update_schedule || 'never'))
                .catch(() => _buildBody(d, 'never'));
        }

        function _buildBody(d, schedule) {
            if (!body) return;
            const statusDot  = d.has_update ? 'pending' : (d.ok ? 'ok' : 'error');
            const statusText = d.has_update
                ? `${d.commits_behind} neue${d.commits_behind === 1 ? 'r Commit' : ' Commits'} verfügbar`
                : (d.ok ? 'Aktuell' : ('Fehler: ' + (d.error || '?')));

            let commitsHtml = '';
            if (d.recent_commits?.length) {
                commitsHtml = `
                <div class="upd-commit-list">
                    ${d.recent_commits.map(c => `
                    <div class="upd-commit">
                        <span class="upd-commit-hash">${c.hash}</span>
                        <span class="upd-commit-msg">${_esc(c.message)}</span>
                        <span class="upd-commit-date">${c.date}</span>
                    </div>`).join('')}
                </div>`;
            }

            let updateBtn = '';
            if (d.has_update) {
                updateBtn = `<button id="upd-apply-btn" class="kb-btn-action" style="width:100%;">⬇ Jetzt aktualisieren</button>`;
            } else {
                updateBtn = `<button id="upd-check-btn" class="kb-btn-secondary" style="width:100%;font-size:.78rem;">🔄 Erneut prüfen</button>`;
            }

            body.innerHTML = `
                <div class="upd-status-row">
                    <span class="upd-dot ${statusDot}"></span>
                    <span style="font-size:.82rem;color:var(--text-primary);">${statusText}</span>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:.75rem;color:var(--text-secondary);">
                    <span>Aktuell: <code style="color:var(--accent);">${d.current_hash || '?'}</code></span>
                    <span>Branch: <code style="color:var(--text-secondary);">${d.branch || 'master'}</code></span>
                </div>
                ${commitsHtml}
                ${updateBtn}
                <div class="upd-auto-row">
                    <span class="upd-auto-label">Auto-Update</span>
                    <select id="upd-schedule" class="upd-schedule-select">
                        <option value="never"  ${schedule==='never'  ?'selected':''}>Aus</option>
                        <option value="daily"  ${schedule==='daily'  ?'selected':''}>Täglich (03:00)</option>
                        <option value="weekly" ${schedule==='weekly' ?'selected':''}>Wöchentlich (Mo 03:00)</option>
                    </select>
                </div>`;

            document.getElementById('upd-apply-btn')?.addEventListener('click', _applyUpdate);
            document.getElementById('upd-check-btn')?.addEventListener('click', _check);
            document.getElementById('upd-schedule')?.addEventListener('change', e => _saveSchedule(e.target.value));
        }

        async function _applyUpdate() {
            const btn = document.getElementById('upd-apply-btn');
            if (btn) { btn.disabled = true; btn.textContent = '⏳ Aktualisiere…'; }
            if (body) body.insertAdjacentHTML('afterbegin',
                '<p class="kb-hint" style="margin:0;color:#f39c12;">Update wird durchgeführt – Jarvis startet danach neu…</p>');
            try {
                const r = await fetch('/api/update/apply', { method: 'POST', headers: _authHeaders() });
                const d = await r.json();
                if (d.ok) {
                    if (body) body.innerHTML = `<p style="color:#2ecc71;font-size:.85rem;">✅ Update erfolgreich. Verbindung wird in 5 s wiederhergestellt…</p>`;
                    setTimeout(() => window.location.reload(), 5000);
                } else {
                    if (body) body.insertAdjacentHTML('afterbegin',
                        `<p class="kb-hint" style="color:#e74c3c;">Fehler: ${_esc(d.error || '')}</p>`);
                    if (btn) { btn.disabled = false; btn.textContent = '⬇ Jetzt aktualisieren'; }
                }
            } catch (e) {
                if (btn) { btn.disabled = false; btn.textContent = '⬇ Jetzt aktualisieren'; }
            }
        }

        async function _saveSchedule(val) {
            await fetch('/api/update/settings', {
                method: 'POST',
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ auto_update_schedule: val })
            });
        }

        function _esc(s) {
            return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        }

        return { init };
    })();

    // ─── Instructions Editor ─────────────────────────────────────
    async function _loadInstructions() {
        const list = document.getElementById('instr-list');
        if (!list) return;
        const authHeader = { 'Authorization': `Bearer ${token}` };
        try {
            const res = await fetch('/api/instructions', { headers: authHeader });
            const data = await res.json();
            list.innerHTML = '';
            if (!data.files || data.files.length === 0) {
                list.innerHTML = '<p style="color:var(--text-muted); font-size:0.85rem;">Noch keine Instruktionen vorhanden. Erstelle eine neue über das Feld oben.</p>';
                return;
            }
            data.files.forEach(f => {
                const card = document.createElement('div');
                card.style.cssText = 'background:var(--bg-glass);border:1px solid var(--border);border-radius:var(--radius-md);overflow:hidden;';
                card.innerHTML = `
                    <div class="instr-card-header" data-name="${f.name}" style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;cursor:pointer;user-select:none;">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <span class="instr-arrow" style="font-size:0.7rem;color:var(--text-muted);transition:transform 0.2s;">▶</span>
                            <strong style="color:var(--accent-hover);font-size:0.9rem;">${f.name}.md</strong>
                        </div>
                        <div style="display:flex;gap:6px;">
                            <button class="btn-instr-save" data-name="${f.name}" style="padding:4px 12px;font-size:0.75rem;background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);cursor:pointer;">Speichern</button>
                            <button class="btn-instr-del" data-name="${f.name}" style="padding:4px 12px;font-size:0.75rem;background:rgba(239,68,68,0.15);color:#ef4444;border:1px solid rgba(239,68,68,0.3);border-radius:var(--radius-sm);cursor:pointer;">Löschen</button>
                        </div>
                    </div>
                    <div class="instr-card-body" style="display:none;padding:0 14px 14px;">
                        <textarea class="instr-editor" data-name="${f.name}" style="width:100%;min-height:120px;padding:10px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text-primary);font-family:var(--font-mono);font-size:0.8rem;resize:vertical;line-height:1.5;box-sizing:border-box;">${f.content}</textarea>
                    </div>
                `;
                list.appendChild(card);
            });
            // Auf-/Zuklappen per Klick auf Header
            list.querySelectorAll('.instr-card-header').forEach(header => {
                header.addEventListener('click', e => {
                    if (e.target.closest('button')) return; // Buttons nicht triggern
                    const body = header.nextElementSibling;
                    const arrow = header.querySelector('.instr-arrow');
                    const open = body.style.display !== 'none';
                    body.style.display = open ? 'none' : 'block';
                    arrow.style.transform = open ? '' : 'rotate(90deg)';
                });
            });
            // Event-Handler Speichern
            list.querySelectorAll('.btn-instr-save').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const name = btn.dataset.name;
                    const textarea = list.querySelector(`.instr-editor[data-name="${name}"]`);
                    const res = await fetch(`/api/instructions/${name}`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json', ...authHeader},
                        body: JSON.stringify({content: textarea.value})
                    });
                    if (res.ok) { btn.textContent = '✓'; btn.style.background = '#10b981'; setTimeout(() => { btn.textContent = 'Speichern'; btn.style.background = ''; }, 1500); }
                });
            });
            // Event-Handler Löschen
            list.querySelectorAll('.btn-instr-del').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm(`Instruktion "${btn.dataset.name}" wirklich löschen?`)) return;
                    await fetch(`/api/instructions/${btn.dataset.name}`, {method: 'DELETE', headers: authHeader});
                    _loadInstructions();
                });
            });
        } catch (e) { list.innerHTML = '<p style="color:var(--danger);">Fehler beim Laden der Instruktionen.</p>'; }
    }

    // Neue Instruktion erstellen
    document.getElementById('btn-instr-new')?.addEventListener('click', async () => {
        const nameInput = document.getElementById('instr-new-name');
        const name = nameInput.value.trim();
        if (!name) { nameInput.style.borderColor = 'var(--danger)'; setTimeout(() => nameInput.style.borderColor = '', 2000); return; }
        await fetch(`/api/instructions/${name}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${token}`},
            body: JSON.stringify({content: `# ${name}\n\nDeine Anweisungen hier eingeben...\n`})
        });
        nameInput.value = '';
        _loadInstructions();
    });

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
            // Fehlermeldungen (❌/🔴/⚠️) immer als highlight anzeigen, unabhängig vom Debug-Modus
            const isError = data.message && (data.message.startsWith('❌') || data.message.startsWith('🔴') || data.message.startsWith('⚠️'));
            addLogEntry(data.message, 'info', data.highlight || isError, agentId);
            // Agent-State in Sidebar aktualisieren
            if (data.agent_id) {
                _updateAgentCard(data.agent_id, data.agent_label, data.state, data.is_sub_agent);
            }
            // Hauptagent-State im Header nur wenn aktiver Agent
            if (agentId === _activeAgentId && data.state) {
                updateAgentState(data.state);
            }
        });

        ws.on('llm_stats', (data) => {
            const agentId = data.agent_id || '_main';
            const sec = (data.duration_ms / 1000).toFixed(1);
            const inTok = data.input_tokens || 0;
            const outTok = data.output_tokens || 0;
            const total = data.total_tokens || (inTok + outTok);
            let info = `⏱ ${sec}s`;
            if (total > 0) info += ` · ${inTok.toLocaleString('de-DE')} → ${outTok.toLocaleString('de-DE')} Tokens`;
            if (data.steps > 0) info += ` · ${data.steps} Schritt${data.steps !== 1 ? 'e' : ''}`;
            addStatsEntry(info, agentId);
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
            const msg = data.message || data.error || data.detail || JSON.stringify(data);
            addLogEntry(`❌ Fehler: ${msg}`, 'error');
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

        // Cron- und Watcher-Events an cronManager weiterleiten
        ws.on('cron_event', (data) => {
            if (window.cronManager) window.cronManager.handleWsEvent(data);
        });
        ws.on('watcher_event', (data) => {
            if (window.cronManager) window.cronManager.handleWsEvent(data);
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
    const _updateDebugBtn = () => {
        btnDebug.textContent = _debugMode ? 'debug aktiv' : 'debug aktivieren';
        btnDebug.classList.toggle('active', _debugMode);
        logContainer.classList.toggle('hide-debug', !_debugMode);
    };
    _updateDebugBtn();

    btnDebug.addEventListener('click', () => {
        _debugMode = !_debugMode;
        localStorage.setItem('jarvis_debug', _debugMode);
        _updateDebugBtn();
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
        // Eintraege des aktiven Agents + pre-agent Eintraege ('_main') entfernen
        const entries = logContainer.querySelectorAll(`.log-entry[data-agent-id="${_activeAgentId}"], .log-entry[data-agent-id="_main"]`);
        entries.forEach(e => e.remove());
        if (_agentLogs[_activeAgentId]) _agentLogs[_activeAgentId] = [];
        if (_agentLogs['_main']) _agentLogs['_main'] = [];
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

        // Thinking Bar: ausblenden wenn Hauptagent fertig oder idle
        if ((event === 'finished' || event === 'paused') && !agent.is_sub_agent) {
            updateAgentState('idle');
        }
        if (event === 'started' && !agent.is_sub_agent) {
            updateAgentState('running');
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

    function addStatsEntry(info, agentId) {
        const effectiveAgentId = agentId || '_main';
        const entry = document.createElement('div');
        entry.className = 'log-entry log-stats';
        entry.dataset.agentId = effectiveAgentId;
        if (effectiveAgentId !== _activeAgentId) entry.style.display = 'none';
        entry.innerHTML = `<span class="log-stats-text">${escapeHtml(info)}</span>`;
        _ensureAgentLog(effectiveAgentId);
        _agentLogs[effectiveAgentId].push(entry);
        logContainer.appendChild(entry);
        if (effectiveAgentId === _activeAgentId) logContainer.scrollTop = logContainer.scrollHeight;
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
        const isRunning = state === 'running';
        thinkingBar.hidden = !isRunning;
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
        const SVG_EYE_OPEN   = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
        const SVG_EYE_CLOSED = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;

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
        const inputModel = document.getElementById('profile-model-input');
        const modelSuggestions = document.getElementById('model-suggestions');
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
        const btnToggleProfileApiKey = document.getElementById('btn-toggle-profile-apikey');
        const btnToggleProfileSessionKey = document.getElementById('btn-toggle-profile-sessionkey');
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
        const btnTestProfile = document.getElementById('btn-test-profile');
        const profileTestResult = document.getElementById('profile-test-result');

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
        const tabTelemetry = document.getElementById('settings-tab-telemetry');
        const tabInstructions = document.getElementById('settings-tab-instructions');
        const tabSecurity = document.getElementById('settings-tab-security');
        const tabCron    = document.getElementById('settings-tab-cron');
        const tabContext = document.getElementById('settings-tab-context');
        const tabAudit   = document.getElementById('settings-tab-audit');

        const allSettingsTabs = [tabProfiles, tabInstructions, tabSkills, tabWhatsApp, tabKnowledge, tabGoogle, tabVision, tabMcp, tabTelemetry, tabSecurity, tabCron, tabContext, tabAudit];

        settingsTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                settingsTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                const target = tab.dataset.settingsTab;
                allSettingsTabs.forEach(t => {
                    if (t) { t.style.display = 'none'; t.classList.remove('active'); }
                });

                if (target === 'profiles' && tabProfiles) {
                    tabProfiles.style.display = '';
                    tabProfiles.classList.add('active');
                } else if (target === 'instructions' && tabInstructions) {
                    tabInstructions.style.display = '';
                    tabInstructions.classList.add('active');
                    _loadInstructions();
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
                    if (window.extractorManager) window.extractorManager.init();
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
                } else if (target === 'telemetry' && tabTelemetry) {
                    tabTelemetry.style.display = '';
                    tabTelemetry.classList.add('active');
                    if (window.telemetryManager) window.telemetryManager.init();
                } else if (target === 'security' && tabSecurity) {
                    tabSecurity.style.display = '';
                    tabSecurity.classList.add('active');
                    _initSecurityTab();
                } else if (target === 'cron' && tabCron) {
                    tabCron.style.display = '';
                    tabCron.classList.add('active');
                    if (window.cronManager) window.cronManager.init();
                } else if (target === 'context' && tabContext) {
                    tabContext.style.display = '';
                    tabContext.classList.add('active');
                    if (window.contextManager) window.contextManager.init();
                } else if (target === 'audit' && tabAudit) {
                    tabAudit.style.display = '';
                    tabAudit.classList.add('active');
                    if (window.auditManager) window.auditManager.init();
                }

                // Polling stoppen wenn weg-navigiert
                if (target !== 'vision'   && window.visionManager)   window.visionManager.stop();
                if (target !== 'context'  && window.contextManager)  window.contextManager.stop();
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

        // ── SSL-Status laden ──
        async function loadSslStatus() {
            try {
                const r = await fetch('/api/settings/ssl', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const d = await r.json();
                const el = document.getElementById('ssl-status-text');
                if (!el) return;
                if (d.is_letsencrypt) {
                    el.innerHTML = `\u2705 Let's Encrypt: <strong>${d.domain}</strong> \u2013 g\u00fcltig bis ${d.expiry}`;
                } else if (d.expiry) {
                    el.innerHTML = `\u26a0\ufe0f Self-signed Zertifikat aktiv (g\u00fcltig bis ${d.expiry})`;
                } else {
                    el.innerHTML = '\u26a0\ufe0f Self-signed Zertifikat aktiv';
                }
            } catch (e) { /* ignorieren */ }
        }

        // ── Let's Encrypt Zertifikat beantragen ──
        async function requestLetsEncrypt() {
            const domain = (document.getElementById('le-domain') || {}).value?.trim();
            const email = (document.getElementById('le-email') || {}).value?.trim();
            if (!domain || !email) { alert('Domain und E-Mail erforderlich'); return; }

            const btn = document.getElementById('btn-request-letsencrypt');
            const progress = document.getElementById('le-progress');
            if (btn) { btn.disabled = true; btn.textContent = 'L\u00e4uft...'; }
            if (progress) { progress.style.display = 'block'; progress.textContent = ''; }

            try {
                const resp = await fetch('/api/settings/letsencrypt', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({ domain, email })
                });

                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    if (progress) {
                        progress.textContent += decoder.decode(value);
                        progress.scrollTop = progress.scrollHeight;
                    }
                }
            } catch (e) {
                if (progress) progress.textContent += `\nFehler: ${e.message}\n`;
            }

            if (btn) { btn.disabled = false; btn.textContent = 'Zertifikat beantragen'; }
            loadSslStatus();
        }

        // Button-Handler registrieren
        const btnLE = document.getElementById('btn-request-letsencrypt');
        if (btnLE) btnLE.addEventListener('click', requestLetsEncrypt);

        // ── Modal öffnen/schließen ──
        const openModal = async () => {
            await loadProfiles();
            await updateGoogleTabVisibility();
            await updateWhatsAppTabVisibility();
            await updateVisionTabVisibility();
            loadSslStatus();
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
            if (tabTelemetry) { tabTelemetry.style.display = 'none'; tabTelemetry.classList.remove('active'); }
            modal.classList.add('open');
        };
        const closeModal = () => {
            modal.classList.remove('open');
            if (window.visionManager) window.visionManager.stop();
        };

        btnOpen.addEventListener('click', openModal);
        btnClose.addEventListener('click', closeModal);
        // Kein Schließen bei Klick außerhalb oder versehentlichem Drag – nur explizit via X-Button

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
                // Agent API Key: vollen Key vom Server holen → type=password zeigt korrekte Sternanzahl
                if (inputAgentKey) {
                    fetch('/api/settings/agentkey', { headers: { 'Authorization': `Bearer ${token}` } })
                        .then(r => r.json()).then(d => {
                            _agentKeyValue = d.agent_api_key || '';
                            inputAgentKey.value = _agentKeyValue;
                            inputAgentKey.type = 'password';
                            inputAgentKey.readOnly = true;
                            _agentKeyVisible = false;
                            if (btnToggleKey) btnToggleKey.innerHTML = SVG_EYE_OPEN;
                        }).catch(() => {});
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

            // Felder befüllen (zunächst mit maskierten Werten)
            inputName.value = profile ? profile.name : '';
            selectProvider.value = profile ? profile.provider : 'google';
            inputUrl.value = profile ? profile.api_url : '';
            inputKey.value = '';
            if (inputSessionKey) inputSessionKey.value = '';

            // Eye-Icons zurücksetzen (Auge-auf = verborgen)
            inputKey.type = 'password';
            if (btnToggleProfileApiKey) btnToggleProfileApiKey.innerHTML = SVG_EYE_OPEN;
            if (inputSessionKey) inputSessionKey.type = 'password';
            if (btnToggleProfileSessionKey) btnToggleProfileSessionKey.innerHTML = SVG_EYE_OPEN;

            // Test-Ergebnis zurücksetzen
            if (profileTestResult) { profileTestResult.style.display = 'none'; profileTestResult.textContent = ''; }

            // Vollen Key vom Server laden und als Sternchen anzeigen (korrekte Anzahl)
            if (id) {
                fetch(`/api/profiles/${id}/key`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                }).then(r => r.json()).then(data => {
                    inputKey.value = data.api_key || '';
                    if (inputSessionKey) inputSessionKey.value = data.session_key || '';
                }).catch(() => {});
            }

            // Auth-Methode
            if (profile && profile.auth_method === 'session') {
                radioSession.checked = true;
            } else {
                radioApiKey.checked = true;
            }

            // Provider-abhängige Felder initialisieren
            updateProviderUI();

            // Modell setzen (nach updateProviderUI)
            if (profile) {
                inputModel.value = profile.model || '';
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

            // Datalist mit Vorschlägen für aktuellen Provider befüllen
            const models = (defaults[provider] && defaults[provider].models) || [];
            modelSuggestions.innerHTML = '';
            models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m;
                modelSuggestions.appendChild(opt);
            });

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
            const model = inputModel.value;

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
                    addLogEntry('Profil gespeichert: ' + profileData.name + (profileData.model ? ' (' + profileData.model + ')' : ''), 'system');
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

        // ── Verbindung testen ──
        if (btnTestProfile) {
            btnTestProfile.addEventListener('click', async () => {
                btnTestProfile.disabled = true;
                btnTestProfile.textContent = 'Teste…';
                profileTestResult.style.display = '';
                profileTestResult.style.background = 'rgba(255,255,255,0.05)';
                profileTestResult.style.border = '1px solid rgba(255,255,255,0.1)';
                profileTestResult.style.color = 'var(--text-muted)';
                profileTestResult.textContent = '⏳ Verbindung wird geprüft…';
                try {
                    // Aktuelle Formularwerte verwenden (nicht die gespeicherten)
                    const testPayload = {
                        provider: selectProvider.value,
                        api_url: inputUrl.value.trim(),
                        api_key: inputKey.value.trim(),
                        model: inputModel.value.trim() || '',
                        auth_method: (radioSession && radioSession.checked) ? 'session' : 'api_key',
                        session_key: inputSessionKey ? inputSessionKey.value.trim() : '',
                    };
                    const res = await fetch(`/api/profiles/test`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                        body: JSON.stringify(testPayload),
                    });
                    const data = await res.json();
                    // Datalist mit echten API-Modellen befüllen
                    const availModels = data.available_models || data.models || [];
                    if (availModels.length > 0) {
                        modelSuggestions.innerHTML = '';
                        availModels.forEach(m => {
                            const opt = document.createElement('option');
                            opt.value = m;
                            modelSuggestions.appendChild(opt);
                        });
                    }
                    if (data.success) {
                        const ok = data.model_found !== false;
                        profileTestResult.style.background = ok ? 'rgba(46,204,113,0.15)' : 'rgba(230,126,34,0.15)';
                        profileTestResult.style.border = ok ? '1px solid rgba(46,204,113,0.4)' : '1px solid rgba(230,126,34,0.4)';
                        profileTestResult.style.color = ok ? '#2ecc71' : '#e67e22';
                        profileTestResult.textContent = `${ok ? '✓' : '⚠'} ${data.message}${data.latency_ms ? ` (${data.latency_ms} ms)` : ''}`;
                        if (availModels.length > 0 && !ok) {
                            profileTestResult.textContent += ' → Modellname aus Vorschlagsliste wählen!';
                        }
                    } else {
                        profileTestResult.style.background = 'rgba(231,76,60,0.15)';
                        profileTestResult.style.border = '1px solid rgba(231,76,60,0.4)';
                        profileTestResult.style.color = '#e74c3c';
                        profileTestResult.textContent = `✗ ${data.error}${data.latency_ms ? ` (${data.latency_ms} ms)` : ''}`;
                    }
                } catch (e) {
                    profileTestResult.style.background = 'rgba(231,76,60,0.15)';
                    profileTestResult.style.border = '1px solid rgba(231,76,60,0.4)';
                    profileTestResult.style.color = '#e74c3c';
                    profileTestResult.textContent = `✗ Fehler: ${e.message}`;
                } finally {
                    btnTestProfile.disabled = false;
                    btnTestProfile.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>Verbindung testen';
                }
            });
        }

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

        // ── Einheitliche Eye-Toggle-Logik für alle Key-Felder ──
        function toggleKeyField(inputEl, btnEl) {
            const isHidden = inputEl.type === 'password';
            inputEl.type = isHidden ? 'text' : 'password';
            btnEl.innerHTML = isHidden ? SVG_EYE_CLOSED : SVG_EYE_OPEN;
        }

        if (btnToggleKey && inputAgentKey) {
            btnToggleKey.addEventListener('click', () => toggleKeyField(inputAgentKey, btnToggleKey));
        }
        if (btnToggleProfileApiKey && inputKey) {
            btnToggleProfileApiKey.addEventListener('click', () => toggleKeyField(inputKey, btnToggleProfileApiKey));
        }
        if (btnToggleProfileSessionKey && inputSessionKey) {
            btnToggleProfileSessionKey.addEventListener('click', () => toggleKeyField(inputSessionKey, btnToggleProfileSessionKey));
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

        // ── Sicherheits-Tab: Kennwort-Änderung ──
        function _initSecurityTab() {
            const oldEl    = document.getElementById('sec-cpw-old');
            const newEl    = document.getElementById('sec-cpw-new');
            const confEl   = document.getElementById('sec-cpw-confirm');
            const errEl    = document.getElementById('sec-cpw-error');
            const okEl     = document.getElementById('sec-cpw-success');
            const strengthEl = document.getElementById('sec-cpw-strength');
            const submitEl = document.getElementById('sec-cpw-submit');
            if (!submitEl) return;

            // Eye-Buttons einmalig verdrahten (idempotent via flag)
            if (!tabSecurity._eyesWired) {
                tabSecurity._eyesWired = true;
                _wireEyeBtn('btn-eye-sec-old',     document.getElementById('sec-cpw-old'));
                _wireEyeBtn('btn-eye-sec-new',     document.getElementById('sec-cpw-new'));
                _wireEyeBtn('btn-eye-sec-confirm', document.getElementById('sec-cpw-confirm'));
            }

            // Felder leeren beim Öffnen
            if (oldEl) { oldEl.type = 'password'; oldEl.value = ''; }
            if (newEl) { newEl.type = 'password'; newEl.value = ''; newEl.oninput = () => _secStrengthCheck(newEl, strengthEl); }
            if (confEl) { confEl.type = 'password'; confEl.value = ''; }
            // Eye-Icons zurücksetzen
            ['btn-eye-sec-old','btn-eye-sec-new','btn-eye-sec-confirm'].forEach(id => {
                const b = document.getElementById(id); if (b) b.innerHTML = _SVG_EYE_OPEN;
            });
            if (errEl) errEl.style.display = 'none';
            if (okEl) okEl.style.display = 'none';

            // Vorschlagen-Button verdrahten
            const suggestEl = document.getElementById('sec-cpw-suggest');
            if (suggestEl && newEl && confEl) {
                suggestEl.onclick = () => {
                    const pw = _generateStrongPassword();
                    newEl.type = 'text';
                    newEl.value = pw;
                    confEl.value = pw;
                    _secStrengthCheck(newEl, strengthEl);
                };
            }

            submitEl.onclick = async () => {
                if (errEl) errEl.style.display = 'none';
                if (okEl) okEl.style.display = 'none';
                const old_pw  = oldEl ? oldEl.value : '';
                const new_pw  = newEl ? newEl.value : '';
                const conf_pw = confEl ? confEl.value : '';
                if (!old_pw || !new_pw || !conf_pw) {
                    if (errEl) { errEl.textContent = 'Alle Felder ausfüllen.'; errEl.style.display = ''; }
                    return;
                }
                submitEl.disabled = true;
                submitEl.textContent = 'Speichere...';
                try {
                    const res = await fetch('/api/change-password', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                        body: JSON.stringify({ old_password: old_pw, new_password: new_pw, confirm_password: conf_pw }),
                    });
                    const data = await res.json();
                    if (data.success) {
                        if (oldEl) oldEl.value = '';
                        if (newEl) newEl.value = '';
                        if (confEl) confEl.value = '';
                        if (strengthEl) strengthEl.textContent = '';
                        if (okEl) { okEl.textContent = '✅ Kennwort erfolgreich geändert.'; okEl.style.display = ''; }
                    } else {
                        if (errEl) { errEl.textContent = data.error || 'Fehler.'; errEl.style.display = ''; }
                    }
                } catch (e) {
                    if (errEl) { errEl.textContent = 'Server nicht erreichbar.'; errEl.style.display = ''; }
                } finally {
                    submitEl.disabled = false;
                    submitEl.textContent = 'Kennwort speichern';
                }
            };
        }

        function _secStrengthCheck(inputEl, outputEl) {
            if (!outputEl) return;
            const pw = inputEl.value;
            const score = [pw.length >= 8, /[A-Z]/.test(pw), /[a-z]/.test(pw), /[0-9]/.test(pw)].filter(Boolean).length;
            const labels = ['Sehr schwach', 'Schwach', 'Mittel', 'Stark', 'Sehr stark'];
            const colors = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#16a34a'];
            outputEl.innerHTML = pw.length ? `<span style="color:${colors[score]}">● ${labels[score]}</span>` : '';
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
                // Token-Expiry Warnung einrichten
                if (data.remaining_seconds && data.remaining_seconds < 3600) {
                    _showTokenExpiryWarning(data.remaining_seconds);
                } else if (data.remaining_seconds) {
                    // Timer fuer Warnung 1h vor Ablauf
                    const warnIn = (data.remaining_seconds - 3600) * 1000;
                    if (warnIn > 0) setTimeout(() => _showTokenExpiryWarning(3600), warnIn);
                }
            } else {
                showLoginScreen();
            }
        }).catch(() => {
            showLoginScreen();
        });
    }
    function _showTokenExpiryWarning(remainingSec) {
        const mins = Math.round(remainingSec / 60);
        const bar = document.createElement('div');
        bar.className = 'token-expiry-bar';
        bar.innerHTML = `⏱ Sitzung laeuft in ${mins} Min. ab. <button onclick="this.parentElement.remove();showLoginScreen()">Neu anmelden</button>`;
        bar.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:10000;background:var(--accent-warning,#f0ad4e);color:#000;text-align:center;padding:8px;font-size:14px;';
        document.body.appendChild(bar);
        // Auto-Logout bei Ablauf
        setTimeout(() => { showLoginScreen(); }, remainingSec * 1000);
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

