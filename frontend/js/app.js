/**
 * Jarvis Haupt-App
 * Verbindet Login, WebSocket, VNC und UI-Steuerung.
 */
(function () {
    'use strict';

    // ─── State ──────────────────────────────────────────────────
    // Single-Sign-On ueber alle Seiten: jeder gueltige Login-Token (egal von
    // welcher Seite gesetzt) wird akzeptiert und unter dem eigenen Key gespiegelt,
    // damit kein erneuter Login bei Seitenwechsel noetig ist.
    let token = localStorage.getItem('jarvis_token') || localStorage.getItem('jarvis_chat_token') || localStorage.getItem('jarvis_uc_token') || '';
    if (token) localStorage.setItem('jarvis_token', token);
    // Eindeutige Fenster-ID fuer Live-Sync (eigene Echo-Events ignorieren)
    const _clientId = 'main-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    let currentUser = localStorage.getItem('jarvis_user') || '';

    // Diese App-Shell wird unter / UND unter /settings ausgeliefert. Unter
    // /settings oeffnet sich direkt das Einstellungen-Modal (eigene Admin-Seite);
    // unter / werden alle Rollen aufs Portal geleitet (Konsolidierung).
    const _isSettingsPage = location.pathname.replace(/\/+$/, '') === '/settings';

    // Rücksprung-Ziel beim Schliessen der Einstellungen: der auslösende Bereich
    // (von chat/userchat/support/portal via sessionStorage gesetzt), sonst /portal.
    function _settingsReturn() {
        var allowed = ['/chat', '/userchat', '/support', '/portal'];
        var r = '';
        try { r = sessionStorage.getItem('jarvis_settings_return') || ''; } catch (e) {}
        return allowed.indexOf(r) !== -1 ? r : '/portal';
    }
    // Oeffnet NUR das Einstellungen-Modal (nicht den toten Haupt-Chat/-Desktop).
    // Stufe 1 der Altlast-Bereinigung: der chat-/desktopspezifische Init-Chain aus
    // showMainScreen() (WebSocket, VNC, Verlauf, Kontext-/LLM-Status, Header-TTS)
    // laeuft auf /settings nicht mehr. Das Modal laedt seine Daten selbst (openModal).
    function _enterSettingsPage() {
        if (loginScreen) loginScreen.classList.remove('active');
        setTimeout(function () {
            // Modal direkt oeffnen (ohne den entfernten Header-Zahnrad-Button)
            if (window._openSettingsModal) window._openSettingsModal();
            const c = document.getElementById('btn-close-settings');
            if (c) c.addEventListener('click', function () { window.location.replace(_settingsReturn()); }, { once: true });
            if (window.applyLang) window.applyLang();
        }, 60);
    }

    // ─── DOM Elemente ───────────────────────────────────────────
    const loginScreen = document.getElementById('login-screen');
    const mainScreen = document.getElementById('main-screen');
    const loginForm = document.getElementById('login-form');
    const loginUsername = document.getElementById('login-username');
    const loginPassword = document.getElementById('login-password');
    const loginError = document.getElementById('login-error');
    const loginBtn = document.getElementById('login-btn');


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
                background: rgba(var(--accent-rgb), ${0.1 + Math.random() * 0.3});
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

        loginBtn.querySelector('.btn-text').textContent = window.t ? window.t('common.connecting') : 'Verbinde...';
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
                if (data.account_blocked) {
                    // Sicherheitsschicht: Konto gesperrt → nur Hinweis + Protokoll
                    if (window.SecurityIncidents) {
                        window.SecurityIncidents.showBlockedScreen(data.block_reason, data.block_incidents);
                    }
                } else if (data.must_change_password) {
                    showChangePwModal(true);
                } else if (_isSettingsPage) {
                    // Eigene /settings-Seite: nur Admins; sonst aufs Portal.
                    if (data.is_admin === false) window.location.replace('/portal');
                    else _enterSettingsPage();
                } else {
                    // Konsolidierung: alle Rollen landen auf dem Portal (kein Haupt-Chat mehr).
                    window.location.replace('/portal');
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
                loginError.textContent = data.error || window.t('login.failed');
                loginError.hidden = false;
            }
        } catch (err) {
            loginError.textContent = window.t('login.server_error');
            loginError.hidden = false;
        } finally {
            loginBtn.querySelector('.btn-text').textContent = window.t('login.submit');
            loginBtn.disabled = false;
        }
    });

    // ─── TOTP Auto-Submit: Formular schicken sobald 6 Ziffern eingegeben ──────
    const _totpAutoInput = document.getElementById('login-totp');
    if (_totpAutoInput) {
        _totpAutoInput.addEventListener('input', () => {
            const digits = _totpAutoInput.value.replace(/\D/g, '');
            if (digits.length === 6 && !loginBtn.disabled) {
                _totpAutoInput.value = digits;
                loginForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
            }
        });
    }

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
        // Abbrechen immer sichtbar – bei Pflicht-Änderung als Abmelden-Button
        if (cpwCancel) {
            cpwCancel.style.display = '';
            if (mandatory) {
                cpwCancel.textContent = 'Abmelden';
                cpwCancel.removeAttribute('data-i18n');
            } else {
                cpwCancel.setAttribute('data-i18n', 'common.cancel');
                cpwCancel.textContent = window.t ? window.t('common.cancel') : 'Abbrechen';
            }
        }
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
        const labels = [0,1,2,3,4].map(i => window.t('security.strength.' + i));
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
            if (_cpwMandatory) {
                // Pflicht-Kennwortänderung abgebrochen → Token löschen + Login-Screen
                showLoginScreen();
            }
        });
    }

    if (cpwSubmit) {
        cpwSubmit.addEventListener('click', async () => {
            if (cpwError) cpwError.style.display = 'none';
            const old_pw = cpwOld ? cpwOld.value : '';
            const new_pw = cpwNew ? cpwNew.value : '';
            const conf_pw = cpwConfirm ? cpwConfirm.value : '';
            if (!old_pw || !new_pw || !conf_pw) {
                if (cpwError) { cpwError.textContent = window.t('security.fill_fields'); cpwError.style.display = ''; }
                return;
            }
            cpwSubmit.disabled = true;
            cpwSubmit.textContent = window.t('common.saving');
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
                        // Erst-Login abgeschlossen -> Portal (Konsolidierung, kein Haupt-Chat)
                        window.location.replace('/portal');
                    }
                } else {
                    if (cpwError) { cpwError.textContent = data.error || window.t('security.change_error'); cpwError.style.display = ''; }
                }
            } catch (e) {
                if (cpwError) { cpwError.textContent = window.t('login.server_error'); cpwError.style.display = ''; }
            } finally {
                cpwSubmit.disabled = false;
                cpwSubmit.textContent = window.t('security.save_pw');
            }
        });
    }

    // ─── Version laden und anzeigen ─────────────────────────────
    async function _loadInstructions() {
        const list = document.getElementById('instr-list');
        if (!list) return;
        const authHeader = { 'Authorization': `Bearer ${token}` };
        try {
            const res = await fetch('/api/instructions', { headers: authHeader });
            const data = await res.json();
            list.innerHTML = '';
            if (!data.files || data.files.length === 0) {
                list.innerHTML = `<p style="color:var(--text-muted); font-size:0.85rem;">${window.t('instructions.empty')}</p>`;
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
                            <button class="btn-instr-save" data-name="${f.name}" style="padding:4px 12px;font-size:0.75rem;background:var(--accent);color:#fff;border:none;border-radius:var(--radius-sm);cursor:pointer;">${window.t('instructions.save')}</button>
                            <button class="btn-instr-del" data-name="${f.name}" title="${window.t('instructions.delete')}" aria-label="${window.t('instructions.delete')}" style="width:28px;height:28px;font-size:1rem;line-height:1;background:rgba(var(--danger-rgb),0.15);color:var(--danger);border:1px solid rgba(var(--danger-rgb),0.3);border-radius:var(--radius-sm);cursor:pointer;flex-shrink:0;">×</button>
                        </div>
                    </div>
                    <div class="instr-card-body" style="display:none;padding:0 14px 14px;">
                        <textarea class="instr-editor" data-name="${f.name}" style="width:100%;min-height:360px;padding:10px;background:var(--bg-secondary);border:1px solid var(--border);border-radius:var(--radius-sm);color:var(--text-primary);font-family:var(--font-mono);font-size:0.8rem;resize:vertical;line-height:1.5;box-sizing:border-box;">${f.content}</textarea>
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
                    if (res.ok) { btn.textContent = '✓'; btn.style.background = 'var(--success)'; setTimeout(() => { btn.textContent = window.t('instructions.save'); btn.style.background = ''; }, 1500); }
                });
            });
            // Event-Handler Löschen
            list.querySelectorAll('.btn-instr-del').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm(window.t('instructions.confirm_delete').replace('{name}', btn.dataset.name))) return;
                    await fetch(`/api/instructions/${btn.dataset.name}`, {method: 'DELETE', headers: authHeader});
                    _loadInstructions();
                });
            });
        } catch (e) { list.innerHTML = `<p style="color:var(--danger);">${window.t('instructions.error')}</p>`; }
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
        // Global abmelden (SSO): alle Seiten-Token entfernen
        localStorage.removeItem('jarvis_token');
        localStorage.removeItem('jarvis_chat_token');
        localStorage.removeItem('jarvis_uc_token');
        localStorage.removeItem('jarvis_user');
    }

    // (Alter Haupt-Chat-Code entfernt – der Chat lebt in /chat;
    //  diese Seite ist nur noch Login-Einstieg + Settings-Modal.)

    function escapeHtml(text) {
        if (window.JarvisChatLib && window.JarvisChatLib.escapeHtml) {
            return window.JarvisChatLib.escapeHtml(text);
        }
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ─── CPU Bar ────────────────────────────────────────────────
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
        const selectTtsVoice = document.getElementById('setting-tts-voice');
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

        // btnOpen (Header-Zahnrad) ist optional – /settings oeffnet das Modal ueber
        // window._openSettingsModal. Nur das Modal selbst ist Pflicht.
        if (!modal) return;

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

        // ── Wissen-Tab: Abschnitte einklappbar ──
        // ── Generischer Collapse-Init ──────────────────────────────────────
        function _collapseInit(sections) {
            sections.forEach(({ hdr, body, tog }) => {
                const hdrEl = document.getElementById(hdr);
                if (!hdrEl || hdrEl._kbBound) return;
                hdrEl._kbBound = true;
                // Initiale is-collapsed Klasse setzen
                const bodyEl0 = document.getElementById(body);
                if (bodyEl0 && bodyEl0.style.display === 'none') {
                    hdrEl.classList.add('is-collapsed');
                }
                hdrEl.addEventListener('click', (e) => {
                    if (e.target.closest('button, input, label, .toggle-switch, a')) return;
                    const bodyEl = document.getElementById(body);
                    const togEl  = document.getElementById(tog);
                    const collapsed = bodyEl.style.display !== 'none';
                    bodyEl.style.display = collapsed ? 'none' : '';
                    if (togEl) togEl.textContent = collapsed ? '▶' : '▼';
                    hdrEl.classList.toggle('is-collapsed', collapsed);
                });
            });
        }

        // ── Wissen-Tab Collapse ────────────────────────────────────────────
        function _initKbCollapse() {
            _collapseInit([
                { hdr: 'kb-sect-stats-hdr',  body: 'kb-sect-stats-body',  tog: 'kb-sect-stats-tog'  },
                { hdr: 'kb-sect-groups-hdr', body: 'kb-sect-groups-body', tog: 'kb-sect-groups-tog' },
                { hdr: 'kb-sect-upload-hdr', body: 'kb-sect-upload-body', tog: 'kb-sect-upload-tog' },
                { hdr: 'kb-sect-folder-hdr', body: 'kb-sect-folder-body', tog: 'kb-sect-folder-tog' },
                { hdr: 'kb-sect-webdav-hdr', body: 'kb-sect-webdav-body', tog: 'kb-sect-webdav-tog' },
                { hdr: 'kb-sect-net-hdr',    body: 'kb-sect-net-body',    tog: 'kb-sect-net-tog'    },
                { hdr: 'kb-sect-ext-hdr',    body: 'kb-sect-ext-body',    tog: 'kb-sect-ext-tog'    },
            ]);
        }

        // ── Sicherheit-Tab Collapse ────────────────────────────────────────
        function _initSecCollapse() {
            _collapseInit([
                { hdr: 'sec-sect-pw-hdr',  body: 'sec-sect-pw-body',  tog: 'sec-sect-pw-tog'  },
                { hdr: 'sec-sect-ad-hdr',  body: 'sec-sect-ad-body',  tog: 'sec-sect-ad-tog'  },
                { hdr: 'sec-sect-2fa-hdr', body: 'sec-sect-2fa-body', tog: 'sec-sect-2fa-tog' },
                { hdr: 'sec-sect-incidents-hdr', body: 'sec-sect-incidents-body', tog: 'sec-sect-incidents-tog' },
                { hdr: 'sec-sect-broker-hdr', body: 'sec-sect-broker-body', tog: 'sec-sect-broker-tog' },
            ]);
        }

        // ── KI-Profile Collapse ────────────────────────────────────────────
        function _initProfilesCollapse() {
            _collapseInit([
                { hdr: 'prof-sect-list-hdr', body: 'prof-sect-list-body', tog: 'prof-sect-list-tog' },
                { hdr: 'prof-sect-tts-hdr',  body: 'prof-sect-tts-body',  tog: 'prof-sect-tts-tog'  },
                { hdr: 'prof-sect-timeout-hdr', body: 'prof-sect-timeout-body', tog: 'prof-sect-timeout-tog' },
                { hdr: 'prof-sect-api-hdr',  body: 'prof-sect-api-body',  tog: 'prof-sect-api-tog'  },
                { hdr: 'prof-sect-ssl-hdr',  body: 'prof-sect-ssl-body',  tog: 'prof-sect-ssl-tog'  },
            ]);
        }

        // ── WhatsApp-Tab Collapse ──────────────────────────────────────────
        function _initWaCollapse() {
            _collapseInit([
                { hdr: 'wa-sect-status-hdr', body: 'wa-sect-status-body', tog: 'wa-sect-status-tog' },
                { hdr: 'wa-sect-logs-hdr',   body: 'wa-sect-logs-body',   tog: 'wa-sect-logs-tog'   },
            ]);
        }

        // ── Vision-Tab Collapse ────────────────────────────────────────────
        function _initVisionCollapse() {
            _collapseInit([
                { hdr: 'vis-sect-feed-hdr',  body: 'vis-sect-feed-body',  tog: 'vis-sect-feed-tog'  },
                { hdr: 'vis-sect-train-hdr', body: 'vis-sect-train-body', tog: 'vis-sect-train-tog' },
                { hdr: 'vis-sect-faces-hdr', body: 'vis-sect-faces-body', tog: 'vis-sect-faces-tog' },
                { hdr: 'vis-sect-cfg-hdr',   body: 'vis-sect-cfg-body',   tog: 'vis-sect-cfg-tog'   },
            ]);
        }

        // ── Settings Tabs ──
        const settingsTabs = document.querySelectorAll('.settings-tab-btn');
        const tabProfiles = document.getElementById('settings-tab-profiles');
        const tabSkills = document.getElementById('settings-tab-skills');
        const tabWhatsApp = document.getElementById('settings-tab-whatsapp');
        const tabKnowledge = document.getElementById('settings-tab-knowledge');
        const tabGoogle = document.getElementById('settings-tab-google');
        const tabVision = document.getElementById('settings-tab-vision');
        const tabBranding = document.getElementById('settings-tab-branding');
        const tabMcp = document.getElementById('settings-tab-mcp');
        const tabTelemetry = document.getElementById('settings-tab-telemetry');
        const tabInstructions = document.getElementById('settings-tab-instructions');
        const tabSecurity = document.getElementById('settings-tab-security');
        const tabCron    = document.getElementById('settings-tab-cron');
        const tabConfluence = document.getElementById('settings-tab-confluence');
        const tabJira    = document.getElementById('settings-tab-jira');
        const tabSupport = document.getElementById('settings-tab-support');
        const allSettingsTabs = [tabProfiles, tabInstructions, tabSkills, tabWhatsApp, tabKnowledge, tabGoogle, tabVision, tabBranding, tabConfluence, tabJira, tabSupport, tabMcp, tabTelemetry, tabSecurity, tabCron];

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
                    _initProfilesCollapse();
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
                    _initWaCollapse();
                    if (window.waManager) window.waManager.refresh();
                } else if (target === 'knowledge' && tabKnowledge) {
                    tabKnowledge.style.display = '';
                    tabKnowledge.classList.add('active');
                    _initKbCollapse();
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
                    _initVisionCollapse();
                    if (window.visionManager) window.visionManager.refresh();
                } else if (target === 'branding' && tabBranding) {
                    tabBranding.style.display = '';
                    tabBranding.classList.add('active');
                    if (window.brandingAdmin) window.brandingAdmin.init();
                } else if (target === 'confluence' && tabConfluence) {
                    tabConfluence.style.display = '';
                    tabConfluence.classList.add('active');
                    if (window.ConfluenceManager) window.ConfluenceManager.onShow();
                } else if (target === 'jira' && tabJira) {
                    tabJira.style.display = '';
                    tabJira.classList.add('active');
                    if (window.JiraManager) window.JiraManager.onShow();
                } else if (target === 'support' && tabSupport) {
                    tabSupport.style.display = '';
                    tabSupport.classList.add('active');
                    if (window.SupportAdminManager) window.SupportAdminManager.onShow();
                } else if (target === 'telemetry' && tabTelemetry) {
                    tabTelemetry.style.display = '';
                    tabTelemetry.classList.add('active');
                    if (window.telemetryManager) window.telemetryManager.init();
                } else if (target === 'security' && tabSecurity) {
                    tabSecurity.style.display = '';
                    tabSecurity.classList.add('active');
                    _initSecCollapse();
                    _initSecurityTab();
                    if (window.SecurityIncidents) window.SecurityIncidents.onShow();
                } else if (target === 'cron' && tabCron) {
                    tabCron.style.display = '';
                    tabCron.classList.add('active');
                    if (window.cronManager) window.cronManager.init();
                }

                // Polling stoppen wenn weg-navigiert
                if (target !== 'vision'    && window.visionManager)   window.visionManager.stop();
                if (target !== 'telemetry' && window.contextManager)  window.contextManager.stop();
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

        // ── Branding-Tab-Button: nur sichtbar wenn 'branding'-Skill aktiviert ──
        const brandingTabBtn = document.getElementById('settings-tab-btn-branding');

        window.updateBrandingTabVisibility = async function updateBrandingTabVisibility() {
            if (!brandingTabBtn) return;
            try {
                const resp = await fetch('/api/skills', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const skills = data.skills || data || [];
                const brSkill = Array.isArray(skills)
                    ? skills.find(s => s.dir_name === 'branding')
                    : null;
                const isEnabled = brSkill && brSkill.enabled;
                brandingTabBtn.style.display = isEnabled ? '' : 'none';
                // Falls Branding-Tab aktiv war und Skill nun deaktiviert → zu Profilen wechseln
                if (!isEnabled && tabBranding && tabBranding.classList.contains('active')) {
                    settingsTabs.forEach(t => t.classList.remove('active'));
                    if (settingsTabs[0]) settingsTabs[0].classList.add('active');
                    allSettingsTabs.forEach(t => { if (t) { t.style.display = 'none'; t.classList.remove('active'); } });
                    if (tabProfiles) { tabProfiles.style.display = ''; tabProfiles.classList.add('active'); }
                }
            } catch (e) {
                // Fehler ignorieren – Tab bleibt versteckt
            }
        }

        const confluenceTabBtn = document.getElementById('settings-tab-btn-confluence');
        window.updateConfluenceTabVisibility = async function updateConfluenceTabVisibility() {
            if (!confluenceTabBtn) return;
            try {
                const resp = await fetch('/api/skills', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const skills = data.skills || data || [];
                const cf = Array.isArray(skills)
                    ? skills.find(s => s.dir_name === 'confluence')
                    : null;
                const isEnabled = cf && cf.enabled;
                confluenceTabBtn.style.display = isEnabled ? '' : 'none';
                // Confluence-Importquelle im Extraktor nur bei aktivem Skill zeigen
                if (window.extractorManager && window.extractorManager.setConfluenceEnabled) {
                    window.extractorManager.setConfluenceEnabled(!!isEnabled);
                }
                if (!isEnabled && tabConfluence && tabConfluence.classList.contains('active')) {
                    settingsTabs.forEach(t => t.classList.remove('active'));
                    if (settingsTabs[0]) settingsTabs[0].classList.add('active');
                    allSettingsTabs.forEach(t => { if (t) { t.style.display = 'none'; t.classList.remove('active'); } });
                    if (tabProfiles) { tabProfiles.style.display = ''; tabProfiles.classList.add('active'); }
                }
            } catch (e) {
                // Fehler ignorieren – Tab bleibt versteckt
            }
        }

        const jiraTabBtn = document.getElementById('settings-tab-btn-jira');
        window.updateJiraTabVisibility = async function updateJiraTabVisibility() {
            if (!jiraTabBtn) return;
            try {
                const resp = await fetch('/api/skills', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const skills = data.skills || data || [];
                const jr = Array.isArray(skills)
                    ? skills.find(s => s.dir_name === 'jira')
                    : null;
                const isEnabled = jr && jr.enabled;
                jiraTabBtn.style.display = isEnabled ? '' : 'none';
                if (!isEnabled && tabJira && tabJira.classList.contains('active')) {
                    settingsTabs.forEach(t => t.classList.remove('active'));
                    if (settingsTabs[0]) settingsTabs[0].classList.add('active');
                    allSettingsTabs.forEach(t => { if (t) { t.style.display = 'none'; t.classList.remove('active'); } });
                    if (tabProfiles) { tabProfiles.style.display = ''; tabProfiles.classList.add('active'); }
                }
            } catch (e) {
                // Fehler ignorieren – Tab bleibt versteckt
            }
        }

        const supportTabBtn = document.getElementById('settings-tab-btn-support');
        window.updateSupportTabVisibility = async function updateSupportTabVisibility() {
            if (!supportTabBtn) return;
            try {
                const resp = await fetch('/api/skills', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await resp.json();
                const skills = data.skills || data || [];
                const sp = Array.isArray(skills)
                    ? skills.find(s => s.dir_name === 'support_assistant')
                    : null;
                const isEnabled = sp && sp.enabled;
                supportTabBtn.style.display = isEnabled ? '' : 'none';
                if (!isEnabled && tabSupport && tabSupport.classList.contains('active')) {
                    settingsTabs.forEach(t => t.classList.remove('active'));
                    if (settingsTabs[0]) settingsTabs[0].classList.add('active');
                    allSettingsTabs.forEach(t => { if (t) { t.style.display = 'none'; t.classList.remove('active'); } });
                    if (tabProfiles) { tabProfiles.style.display = ''; tabProfiles.classList.add('active'); }
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
                    el.innerHTML = window.t('profile.cert_self_signed') + ` ${d.expiry})`;
                } else {
                    el.innerHTML = window.t('profile.cert_self_signed_nodate');
                }
            } catch (e) { /* ignorieren */ }
        }

        // ── Let's Encrypt Zertifikat beantragen ──
        async function requestLetsEncrypt() {
            const domain = (document.getElementById('le-domain') || {}).value?.trim();
            const email = (document.getElementById('le-email') || {}).value?.trim();
            if (!domain || !email) { alert(window.t('app.domain_email_required')); return; }

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
            await updateBrandingTabVisibility();
            await updateConfluenceTabVisibility();
            await updateJiraTabVisibility();
            await updateSupportTabVisibility();
            loadSslStatus();
            showListView();
            // Ersten Tab aktivieren
            settingsTabs.forEach(t => t.classList.remove('active'));
            if (settingsTabs[0]) settingsTabs[0].classList.add('active');
            if (tabProfiles) { tabProfiles.style.display = ''; tabProfiles.classList.add('active'); }
            _initProfilesCollapse();
            // LLM-Timeout speichern (einmalig verdrahten)
            const _btnTm = document.getElementById('btn-save-llm-timeout');
            if (_btnTm && !_btnTm._wired) {
                _btnTm._wired = true;
                _btnTm.addEventListener('click', async () => {
                    const el = document.getElementById('setting-llm-timeout');
                    const st = document.getElementById('llm-timeout-status');
                    let v = parseInt(el && el.value, 10);
                    if (isNaN(v) || v < 10) v = 10;
                    if (v > 1800) v = 1800;
                    if (el) el.value = v;
                    try {
                        await fetch('/api/settings', {
                            method: 'POST',
                            headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                            body: JSON.stringify({ llm_timeout: v })
                        });
                        if (st) { st.textContent = '✓ ' + (window.t ? window.t('profile.save_btn') : 'Gespeichert'); setTimeout(() => { st.textContent = ''; }, 2000); }
                    } catch (e) {
                        if (st) st.textContent = '✗';
                    }
                });
            }
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

        // Von _enterSettingsPage genutzt, damit /settings das Modal ohne den
        // (entfernten) Header-Zahnrad-Button oeffnen kann.
        window._openSettingsModal = openModal;
        if (btnOpen) btnOpen.addEventListener('click', openModal);
        btnClose.addEventListener('click', closeModal);
        // Kein Schließen bei Klick außerhalb oder versehentlichem Drag – nur explizit via X-Button

        // ── Vollbild-Umschalter (gilt für alle Einstellungs-Tabs) ──
        const btnMax = document.getElementById('btn-maximize-settings');
        if (btnMax && !btnMax._bound) {
            btnMax._bound = true;
            const applyMax = (on) => {
                modal.classList.toggle('settings-maximized', on);
                btnMax.textContent = on ? '🗗' : '⛶';
                btnMax.classList.toggle('active', on);
            };
            // Zustand aus localStorage wiederherstellen
            applyMax(localStorage.getItem('jarvis_settings_maximized') === '1');
            btnMax.addEventListener('click', () => {
                const on = !modal.classList.contains('settings-maximized');
                localStorage.setItem('jarvis_settings_maximized', on ? '1' : '0');
                applyMax(on);
            });
        }

        // ── Ansicht wechseln ──
        function showListView() {
            listView.style.display = '';
            editView.style.display = 'none';
            settingsTitle.textContent = window.t('settings.title');
        }

        function showEditView(isNew) {
            listView.style.display = 'none';
            editView.style.display = '';
            settingsTitle.textContent = isNew ? window.t('profile.new') : window.t('profile.edit');
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
                // LLM-Timeout (global) ins Eingabefeld
                const _tmEl = document.getElementById('setting-llm-timeout');
                if (_tmEl) _tmEl.value = data.llm_timeout || 180;
                // Stimmen laden und gespeicherte Auswahl setzen
                _loadTtsVoices(data.tts_voice || '');
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

        // Dezente Zusammenfassung der Profil-Einschraenkung (erlaubte Benutzer/Gruppen)
        // fuer die Listenanzeige – leer, wenn das Profil fuer alle offen ist.
        function _profRestrictionSummary(p) {
            const cn = (dn) => { const m = /^CN=([^,]+)/i.exec((dn || '').trim()); return m ? m[1] : (dn || '').trim(); };
            const users = (p.allowed_users || '').split(',').map(s => s.trim()).filter(Boolean);
            const groups = (p.allowed_group || '').split('\n').map(cn).filter(Boolean);
            const all = users.concat(groups);
            const lbl = escapeHtml(window.t('profile.perm_label'));
            if (!all.length) {
                const ev = escapeHtml(window.t('profile.perm_everyone'));
                return ` <span class="profile-restriction" title="${lbl}: ${ev}">(${ev})</span>`;
            }
            const txt = all.join(', ');
            return ` <span class="profile-restriction" title="${lbl}: ${escapeHtml(txt)}">(${escapeHtml(txt)})</span>`;
        }

        // ── Profilliste rendern ──
        function renderProfileList() {
            profilesContainer.innerHTML = '';
            profiles.forEach(p => {
                const card = document.createElement('div');
                card.className = 'profile-card' + (p.id === activeProfileId ? ' active' : '');
                card.innerHTML = `
                    <div class="profile-info" data-id="${p.id}">
                        <span class="profile-name-row">
                            <span class="llm-status-pill checking" data-id="${p.id}" title="${window.t('profile.status_checking')}"></span>
                            <span class="profile-name">${escapeHtml(p.name)}</span>
                        </span>
                        <span class="profile-detail">${PROVIDER_LABELS[p.provider] || p.provider} · ${escapeHtml(p.model)}${_profRestrictionSummary(p)}</span>
                    </div>
                    <div class="profile-actions">
                        <button class="btn-icon btn-small btn-perms-profile" data-id="${p.id}" title="${window.t('profile.perm_label')}">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                        </button>
                        <button class="btn-icon btn-small btn-edit-profile" data-id="${p.id}" title="Bearbeiten">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
                        </button>
                        <button class="btn-icon btn-small btn-delete-profile" data-id="${p.id}" title="${window.t('common.delete')}">
                            <span style="font-size:1.15rem;line-height:1;">×</span>
                        </button>
                    </div>
                `;
                // Klick auf Info-Bereich = Profil aktivieren
                card.querySelector('.profile-info').addEventListener('click', () => activateProfile(p.id));
                card.querySelector('.btn-perms-profile').addEventListener('click', (e) => {
                    e.stopPropagation();
                    editProfilePermissions(p.id);
                });
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
            // Erreichbarkeit aller Profile asynchron prüfen (Ampel-Pills aktualisieren)
            _refreshProfileStatuses();
        }

        // ── LLM-Erreichbarkeit pro Profil prüfen (grün/gelb/rot Pill) ──
        async function _refreshProfileStatuses() {
            await Promise.all(profiles.map(async (p) => {
                const pill = profilesContainer.querySelector(`.llm-status-pill[data-id="${p.id}"]`);
                if (!pill) return;
                try {
                    const res = await fetch(`/api/profiles/${p.id}/test`, {
                        headers: { 'Authorization': `Bearer ${token}` }
                    });
                    const d = await res.json();
                    // status: ok (grün) | degraded (gelb) | down (rot)
                    const status = d.status || (d.success ? 'ok' : 'down');
                    pill.classList.remove('checking', 'ok', 'degraded', 'down');
                    pill.classList.add(status);
                    const latency = d.latency_ms != null ? ` (${d.latency_ms} ms)` : '';
                    if (status === 'ok') {
                        pill.title = window.t('profile.status_online') + latency;
                    } else if (status === 'degraded') {
                        pill.title = (d.message || window.t('profile.status_model_missing')) + latency;
                    } else {
                        pill.title = (d.error || window.t('profile.status_offline')) + latency;
                    }
                } catch (err) {
                    pill.classList.remove('checking', 'ok', 'degraded', 'down');
                    pill.classList.add('down');
                    pill.title = window.t('profile.status_offline');
                }
            }));
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
            } catch (err) {
                console.error('Fehler beim Aktivieren:', err);
            }
        }

        // ── Pro-Profil Berechtigungen (eigenes Fenster, analog Wissensgruppen) ──
        function editProfilePermissions(id) {
            const p = profiles.find(x => x.id === id);
            if (!p) return;
            const T = (k, d) => (window.t && window.t(k) !== k ? window.t(k) : d);

            const old = document.getElementById('llm-perm-modal');
            if (old) old.remove();

            const m = document.createElement('div');
            m.id = 'llm-perm-modal';
            m.className = 'modal';
            m.style.zIndex = '10001';
            m.innerHTML = `
                <div class="modal-content glass" style="max-width:620px;">
                    <div class="modal-header">
                        <h2>${T('profile.perm_label', 'Nutzung erlauben für')} – ${escapeHtml(p.name)}</h2>
                        <button class="btn-icon" id="llm-perm-close" aria-label="${T('common.close', 'Schließen')}">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                        </button>
                    </div>
                    <div class="modal-body" style="overflow-y:auto;">
                        <p class="kb-hint" style="margin-top:0;" data-i18n="profile.perm_hint">${T('profile.perm_hint', 'Leer lassen = alle dürfen dieses Profil nutzen und darauf wechseln. Sonst nur die genannten Benutzer/Gruppen (plus Administratoren).')}</p>
                        <label class="kb-form-label" style="display:block;margin:12px 0 4px;" data-i18n="profile.perm_users">${T('profile.perm_users', 'Erlaubte AD-Benutzer')}</label>
                        <input type="text" id="llm-perm-users" class="kb-input" style="width:100%;box-sizing:border-box;" data-i18n-placeholder="profile.perm_users_ph" placeholder="${T('profile.perm_users_ph', 'Benutzer (kommagetrennt)')}">
                        <label class="kb-form-label" style="display:block;margin:16px 0 4px;" data-i18n="profile.perm_groups">${T('profile.perm_groups', 'Erlaubte AD-Gruppen')}</label>
                        <textarea id="llm-perm-groups" class="kb-input" rows="2" style="width:100%;box-sizing:border-box;" data-i18n-placeholder="profile.perm_groups_ph" placeholder="${T('profile.perm_groups_ph', 'AD-Gruppen (eine pro Zeile)')}"></textarea>
                        <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px;">
                            <button type="button" id="llm-perm-cancel" class="btn-secondary" data-i18n="profile.cancel">${T('profile.cancel', 'Abbrechen')}</button>
                            <button type="button" id="llm-perm-save" class="btn-primary" data-i18n="profile.save">${T('profile.save', 'Speichern')}</button>
                        </div>
                    </div>
                </div>`;
            document.body.appendChild(m);

            const usersInp = m.querySelector('#llm-perm-users');
            const groupsInp = m.querySelector('#llm-perm-groups');
            // Werte VOR dem Attach setzen, damit die Chip-Liste sie sofort rendert
            // (behebt: hinterlegter Benutzer wurde nicht angezeigt).
            usersInp.value = p.allowed_users || '';
            groupsInp.value = p.allowed_group || '';
            if (window.LdapPicker) {
                window.LdapPicker.attachField(usersInp, { kind: 'users', sep: ',' });
                window.LdapPicker.attachField(groupsInp, { kind: 'groups', sep: '\n' });
            }
            if (window.applyLang) window.applyLang();

            const close = () => m.remove();
            m.querySelector('#llm-perm-close').onclick = close;
            m.querySelector('#llm-perm-cancel').onclick = close;
            m.addEventListener('click', (e) => { if (e.target === m) close(); });
            m.querySelector('#llm-perm-save').onclick = async () => {
                try {
                    const res = await fetch(`/api/profiles/${id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                        body: JSON.stringify({
                            allowed_users: (usersInp.value || '').trim(),
                            allowed_group: (groupsInp.value || '').trim(),
                        }),
                    });
                    const data = await res.json();
                    if (data && (data.success || data.id)) {
                        await loadProfiles();
                        close();
                    } else {
                        alert(window.t('common.error_unknown').replace('{msg}', (data && data.error) || '?'));
                    }
                } catch (e) {
                    alert(window.t('common.connection_failed'));
                }
            };
            requestAnimationFrame(() => m.classList.add('open'));
        }

        // ── Profil löschen ──
        async function deleteProfile(id) {
            if (profiles.length <= 1) {
                alert(window.t('profile.cannot_delete_last'));
                return;
            }
            const profile = profiles.find(p => p.id === id);
            if (!confirm(window.t('profile.confirm_delete').replace('{name}', profile?.name || ''))) return;

            try {
                const res = await fetch(`/api/profiles/${id}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                const data = await res.json();
                if (data.success) {
                    await loadProfiles();
                } else {
                    alert(window.t('common.error_unknown').replace('{msg}', data.error || '?'));
                }
            } catch (err) {
                alert(window.t('common.connection_failed'));
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
                apikeyHint.textContent = isOpenAICompat ? window.t('app.apikey_optional_ollama') : '';
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
                alert(window.t('profile.name_required'));
                return;
            }
            if (!model.trim()) {
                alert(window.t('profile.model_required'));
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

            btnSaveProfile.textContent = window.t('common.saving');
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
                    await loadProfiles();
                    showListView();
                } else {
                    alert(window.t('common.error_unknown').replace('{msg}', data.error || '?'));
                }
            } catch (err) {
                alert(window.t('common.connection_failed'));
            } finally {
                btnSaveProfile.textContent = window.t('profile.save');
                btnSaveProfile.disabled = false;
            }
        });

        // ── Abbrechen (zurück zur Liste) ──
        btnCancelProfile.addEventListener('click', showListView);

        // ── Verbindung testen ──
        if (btnTestProfile) {
            btnTestProfile.addEventListener('click', async () => {
                btnTestProfile.disabled = true;
                btnTestProfile.textContent = window.t('common.testing');
                profileTestResult.style.display = '';
                profileTestResult.style.background = 'rgba(var(--fg-rgb),0.05)';
                profileTestResult.style.border = '1px solid rgba(var(--fg-rgb),0.1)';
                profileTestResult.style.color = 'var(--text-muted)';
                profileTestResult.textContent = window.t('profile.testing');
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
                        profileTestResult.style.background = ok ? 'rgba(var(--success-rgb),0.15)' : 'rgba(var(--warning-rgb),0.15)';
                        profileTestResult.style.border = ok ? '1px solid rgba(var(--success-rgb),0.4)' : '1px solid rgba(var(--warning-rgb),0.4)';
                        profileTestResult.style.color = ok ? 'var(--success)' : 'var(--warning)';
                        profileTestResult.textContent = `${ok ? '✓' : '⚠'} ${data.message}${data.latency_ms ? ` (${data.latency_ms} ms)` : ''}`;
                        if (availModels.length > 0 && !ok) {
                            profileTestResult.textContent += ' → ' + window.t('app.pick_model_from_list');
                        }
                    } else {
                        profileTestResult.style.background = 'rgba(var(--danger-rgb),0.15)';
                        profileTestResult.style.border = '1px solid rgba(var(--danger-rgb),0.4)';
                        profileTestResult.style.color = 'var(--danger)';
                        profileTestResult.textContent = `✗ ${data.error}${data.latency_ms ? ` (${data.latency_ms} ms)` : ''}`;
                    }
                } catch (e) {
                    profileTestResult.style.background = 'rgba(var(--danger-rgb),0.15)';
                    profileTestResult.style.border = '1px solid rgba(var(--danger-rgb),0.4)';
                    profileTestResult.style.color = 'var(--danger)';
                    profileTestResult.textContent = `✗ ${window.t('update.error').replace('{msg}', e.message)}`;
                } finally {
                    btnTestProfile.disabled = false;
                    btnTestProfile.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>' + window.t('app.test_connection');
                }
            });
        }

        // ── Discover-Button: verfuegbare Modelle abrufen + per Klick uebernehmen ──
        const btnDiscoverModels = document.getElementById('btn-discover-models');
        const modelDiscoverList = document.getElementById('model-discover-list');
        const _hideModelDiscover = () => { if (modelDiscoverList) modelDiscoverList.style.display = 'none'; };
        if (btnDiscoverModels && modelDiscoverList) {
            // Farben/Deckung direkt inline per !important setzen – unabhaengig von
            // CSS-Datei/Service-Worker-Cache. Theme-bewusst (dark/light).
            const _mdColors = () => {
                const light = document.body.classList.contains('light');
                return {
                    bg:  light ? '#ffffff' : '#141a28',
                    bgh: light ? '#eef0f4' : '#20283c',
                    fg:  light ? '#1f2937' : '#e5e7eb',
                    fgm: light ? '#475569' : '#cbd5e1',
                    acc: light ? '#4f46e5' : '#a5b4fc',
                    brd: light ? 'rgba(0,0,0,0.15)' : 'rgba(255,255,255,0.18)',
                };
            };
            const _mdSolid = (el, c, textColor) => {
                el.style.setProperty('background-color', c.bg, 'important');
                if (textColor) el.style.setProperty('color', textColor, 'important');
            };
            const _mdMsg = (txt, isErr) => {
                const c = _mdColors();
                modelDiscoverList.innerHTML = '';
                const d = document.createElement('div');
                d.textContent = txt;
                d.style.cssText = 'padding:9px 12px;font-size:0.8rem;';
                _mdSolid(d, c, isErr ? 'var(--danger)' : c.fgm);
                modelDiscoverList.appendChild(d);
            };
            // Popup an document.body haengen + per position:fixed unter dem Eingabefeld
            // platzieren. So entkommt es dem Stacking-Context von .input-group
            // (backdrop-filter), der sonst nachfolgende Formularelemente DARUEBER malt.
            const _mdPlace = () => {
                const c = _mdColors();
                if (modelDiscoverList.parentElement !== document.body) {
                    document.body.appendChild(modelDiscoverList);
                }
                const r = inputModel.getBoundingClientRect();
                const s = modelDiscoverList.style;
                s.setProperty('position', 'fixed', 'important');
                s.setProperty('top', (r.bottom + 4) + 'px', 'important');
                s.setProperty('left', r.left + 'px', 'important');
                s.setProperty('width', r.width + 'px', 'important');
                s.setProperty('right', 'auto', 'important');
                s.setProperty('max-height', '260px', 'important');
                s.setProperty('overflow-y', 'auto', 'important');
                s.setProperty('z-index', '2147483600', 'important');
                s.setProperty('background-color', c.bg, 'important');
                s.setProperty('border', '1px solid ' + c.brd, 'important');
                s.setProperty('border-radius', '10px', 'important');
                s.setProperty('box-shadow', '0 12px 34px rgba(0,0,0,0.7)', 'important');
                s.setProperty('display', 'block', 'important');
            };
            btnDiscoverModels.addEventListener('click', async () => {
                const c = _mdColors();
                const origHtml = btnDiscoverModels.innerHTML;
                btnDiscoverModels.disabled = true;
                btnDiscoverModels.innerHTML = '⏳';
                _mdPlace();
                _mdMsg(window.t('app.loading_models'), false);
                try {
                    const payload = {
                        provider: selectProvider.value,
                        api_url: inputUrl.value.trim(),
                        api_key: inputKey.value.trim(),
                        auth_method: (radioSession && radioSession.checked) ? 'session' : 'api_key',
                        session_key: inputSessionKey ? inputSessionKey.value.trim() : '',
                    };
                    const res = await fetch('/api/profiles/models', {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    const data = await res.json();
                    const models = (data.success && Array.isArray(data.models)) ? data.models : [];
                    if (models.length) {
                        modelSuggestions.innerHTML = '';
                        models.forEach(m => { const o = document.createElement('option'); o.value = m; modelSuggestions.appendChild(o); });
                        modelDiscoverList.innerHTML = '';
                        const head = document.createElement('div');
                        head.textContent = models.length + ' ' + window.t('app.models_click_to_apply');
                        head.style.cssText = 'position:sticky;top:0;padding:7px 12px;font-size:0.72rem;border-bottom:1px solid ' + c.brd + ';';
                        _mdSolid(head, c, c.fgm);
                        modelDiscoverList.appendChild(head);
                        const cur = (inputModel.value || '').trim();
                        models.forEach(m => {
                            const item = document.createElement('div');
                            item.textContent = m;
                            item.style.cssText = 'padding:7px 12px;font-size:0.85rem;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
                            _mdSolid(item, c, m === cur ? c.acc : c.fg);
                            if (m === cur) item.style.fontWeight = '600';
                            item.addEventListener('mouseenter', () => item.style.setProperty('background-color', c.bgh, 'important'));
                            item.addEventListener('mouseleave', () => item.style.setProperty('background-color', c.bg, 'important'));
                            item.addEventListener('click', () => { inputModel.value = m; _hideModelDiscover(); });
                            modelDiscoverList.appendChild(item);
                        });
                    } else {
                        _mdMsg('✗ ' + (data.error || window.t('app.no_models_found')), true);
                    }
                } catch (e) {
                    _mdMsg('✗ ' + e.message, true);
                } finally {
                    btnDiscoverModels.disabled = false;
                    btnDiscoverModels.innerHTML = origHtml;
                }
            });
            // Klick ausserhalb schliesst die Liste
            document.addEventListener('click', (e) => {
                if (modelDiscoverList.style.display !== 'none'
                    && !modelDiscoverList.contains(e.target)
                    && !btnDiscoverModels.contains(e.target)) {
                    _hideModelDiscover();
                }
            });
        }

        // ── TTS-Stimmen laden ──
        async function _loadTtsVoices(savedVoice) {
            if (!selectTtsVoice) return;
            try {
                const resp = await fetch('/api/tts/voices', {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (!resp.ok) { selectTtsVoice.innerHTML = '<option value="">Standard</option>'; return; }
                const voices = await resp.json();
                selectTtsVoice.innerHTML = '<option value="">Standard (de-DE-ConradNeural)</option>';
                voices.forEach(v => {
                    const opt = document.createElement('option');
                    opt.value = v.name;
                    opt.textContent = v.display || v.name;
                    selectTtsVoice.appendChild(opt);
                });
                if (savedVoice) selectTtsVoice.value = savedVoice;
            } catch (e) {
                if (selectTtsVoice) selectTtsVoice.innerHTML = '<option value="">Standard</option>';
            }
        }

        // TTS-Enabled wird jetzt direkt vom btn-tts-Click-Handler persistiert (kein Checkbox mehr)

        // ── TTS-Stimme speichern ──
        if (selectTtsVoice) {
            selectTtsVoice.addEventListener('change', async () => {
                // Header-Stimme synchron halten
                const hv = document.getElementById('hdr-tts-voice');
                if (hv) hv.value = selectTtsVoice.value;
                try {
                    await fetch('/api/settings', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({ tts_voice: selectTtsVoice.value })
                    });
                } catch (err) {
                    console.error('Fehler beim Speichern der TTS-Stimme:', err);
                }
            });
        }

        // ── TTS-Stimme Vorschau ──
        const btnTtsPreview = document.getElementById('btn-tts-preview');
        if (btnTtsPreview && selectTtsVoice) {
            btnTtsPreview.addEventListener('click', async () => {
                const voice = selectTtsVoice.value;
                const previewText = window._lang === 'en'
                    ? 'Hello, I am Jarvis, your autonomous AI assistant.'
                    : 'Hallo, ich bin Jarvis, dein autonomer KI-Assistent.';
                const origHtml = btnTtsPreview.innerHTML;
                btnTtsPreview.disabled = true;
                btnTtsPreview.innerHTML = '⏳';
                try {
                    const resp = await fetch('/api/tts', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${token}`
                        },
                        body: JSON.stringify({ text: previewText, voice: voice || '' })
                    });
                    if (!resp.ok) throw new Error('TTS-Fehler');
                    const blob = await resp.blob();
                    const url = URL.createObjectURL(blob);
                    const audio = new Audio(url);
                    btnTtsPreview.innerHTML = '🔊';
                    audio.onended = () => {
                        URL.revokeObjectURL(url);
                        btnTtsPreview.innerHTML = origHtml;
                        btnTtsPreview.disabled = false;
                    };
                    audio.onerror = () => {
                        URL.revokeObjectURL(url);
                        btnTtsPreview.innerHTML = origHtml;
                        btnTtsPreview.disabled = false;
                    };
                    await audio.play();
                } catch (e) {
                    btnTtsPreview.innerHTML = '❌';
                    setTimeout(() => { btnTtsPreview.innerHTML = origHtml; btnTtsPreview.disabled = false; }, 1500);
                }
            });
        }

        // ── Agent API Keys (mehrere, benannt) ──
        (function initAgentKeys() {
            const listEl = document.getElementById('agent-keys-list');
            const addBtn = document.getElementById('btn-agent-key-add');
            const nameInput = document.getElementById('agent-key-newname');
            const hdr = document.getElementById('prof-sect-api-hdr');
            if (!listEl) return;
            const EYE = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
            const COPY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
            const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
            const api = (path, opts) => fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token } }, opts || {}));

            function render(keys) {
                if (!keys.length) { listEl.innerHTML = `<div style="opacity:.6;font-size:.8rem;">${window.t('app.no_keys')}</div>`; return; }
                listEl.innerHTML = '';
                keys.forEach(k => {
                    const row = document.createElement('div');
                    row.style.cssText = 'display:flex;gap:6px;align-items:center;margin-bottom:6px;';
                    row.dataset.id = k.id;
                    row.innerHTML =
                        '<input class="ak-name" value="' + esc(k.name) + '" title="Name" style="width:130px;">' +
                        '<input class="ak-key" type="password" value="' + esc(k.key) + '" readonly style="flex:1;font-family:monospace;font-size:.78rem;">' +
                        '<button class="btn-icon btn-small ak-show" title="Anzeigen/Verbergen">' + EYE + '</button>' +
                        '<button class="btn-icon btn-small ak-copy" title="Kopieren">' + COPY + '</button>' +
                        '<button class="btn-icon btn-small ak-regen" title="Neu generieren">🔄</button>' +
                        '<button class="btn-icon btn-small ak-del" title="Löschen">×</button>';
                    listEl.appendChild(row);
                });
            }
            function load() {
                api('/api/agent/keys').then(r => r.json()).then(d => render((d && d.keys) || []))
                    .catch(() => { listEl.innerHTML = `<div style="opacity:.6;font-size:.8rem;color:var(--danger);">${window.t('app.load_error')}</div>`; });
            }
            let _loaded = false;
            function loadOnce() { if (_loaded) return; _loaded = true; load(); }
            if (hdr) hdr.addEventListener('click', () => setTimeout(loadOnce, 50));

            listEl.addEventListener('click', e => {
                const row = e.target.closest('[data-id]'); if (!row) return;
                const id = row.dataset.id, keyInput = row.querySelector('.ak-key');
                if (e.target.closest('.ak-show')) {
                    keyInput.type = keyInput.type === 'password' ? 'text' : 'password';
                } else if (e.target.closest('.ak-copy')) {
                    navigator.clipboard.writeText(keyInput.value);
                    const b = e.target.closest('.ak-copy'), o = b.title; b.title = 'Kopiert'; setTimeout(() => b.title = o, 1500);
                } else if (e.target.closest('.ak-regen')) {
                    if (!confirm('Diesen Key neu generieren? Der alte Key wird ungültig.')) return;
                    api('/api/agent/keys/' + id, { method: 'PUT', body: JSON.stringify({ regenerate: true }) }).then(() => load());
                } else if (e.target.closest('.ak-del')) {
                    if (!confirm('Diesen Key löschen?')) return;
                    api('/api/agent/keys/' + id, { method: 'DELETE' }).then(() => load());
                }
            });
            listEl.addEventListener('change', e => {
                if (e.target.classList.contains('ak-name')) {
                    const row = e.target.closest('[data-id]');
                    api('/api/agent/keys/' + row.dataset.id, { method: 'PUT', body: JSON.stringify({ name: e.target.value }) });
                }
            });
            if (addBtn) addBtn.addEventListener('click', () => {
                const name = (nameInput && nameInput.value.trim()) || '';
                api('/api/agent/keys', { method: 'POST', body: JSON.stringify({ name: name }) })
                    .then(r => r.json()).then(() => { if (nameInput) nameInput.value = ''; _loaded = true; load(); });
            });
        })();

        // ── Agent API Key: Generieren (Legacy – Element entfernt, no-op) ──
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
                        btnCopyKey.title = window.t('common.copied');
                        setTimeout(() => { btnCopyKey.title = window.t('common.copy'); }, 2000);
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
                    if (errEl) { errEl.textContent = window.t('security.fill_fields'); errEl.style.display = ''; }
                    return;
                }
                submitEl.disabled = true;
                submitEl.textContent = window.t('common.saving');
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
                        if (okEl) { okEl.textContent = window.t('security.password_changed'); okEl.style.display = ''; }
                    } else {
                        if (errEl) { errEl.textContent = data.error || window.t('common.error'); errEl.style.display = ''; }
                    }
                } catch (e) {
                    if (errEl) { errEl.textContent = window.t('common.connection_failed'); errEl.style.display = ''; }
                } finally {
                    submitEl.disabled = false;
                    submitEl.textContent = window.t('security.save_pw');
                }
            };
        }

        function _secStrengthCheck(inputEl, outputEl) {
            if (!outputEl) return;
            const pw = inputEl.value;
            const score = [pw.length >= 8, /[A-Z]/.test(pw), /[a-z]/.test(pw), /[0-9]/.test(pw)].filter(Boolean).length;
            const labels = [window.t('security.strength.0'), window.t('security.strength.1'), window.t('security.strength.2'), window.t('security.strength.3'), window.t('security.strength.4')];
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
                if (data.must_change_password) {
                    // Erst-Kennwort noch nicht geaendert -> Maske erzwingen.
                    // Auch nach F5/Reload (serverseitig zusaetzlich gesperrt).
                    showChangePwModal(true);
                } else if (_isSettingsPage) {
                    // Eigene /settings-Seite: nur Admins; sonst aufs Portal.
                    if (data.is_admin === false) window.location.replace('/portal');
                    else _enterSettingsPage();
                } else {
                    // Konsolidierung: Wurzel-Seite leitet alle Rollen aufs Portal
                    // (kein Haupt-Chat mehr). Chat/Userchat/Support/Settings dort verlinkt.
                    window.location.replace('/portal');
                }
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
            bannerText.textContent = window.t('panel.security_banner');
            if (indicator) {
                indicator.className = 'security-badge';
                indicator.title = window.t('panel.security_critical');
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
                indicator.title = window.t('panel.security_secure');
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


    // ─── Init ───────────────────────────────────────────────────
    initParticles();
    setupModal();
    setupSettings();
    checkSecurity();

})();

