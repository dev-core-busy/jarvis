/**
 * Jarvis Google Apps – Settings-Tab UI
 *
 * Sektion 1: Jarvis Google Apps (Device Flow OAuth)
 * Sektion 2: OpenClaw Gmail / gog  (nur wenn Skill aktiviert)
 */
class JarvisGoogleManager {
    constructor() {
        this._devicePollTimer  = null;
        this._gogPollTimer     = null;
        this._gogEmail         = '';
    }

    async init() {
        await this._renderAll();
    }

    // ─── Haupt-Render ──────────────────────────────────────────────

    async _renderAll() {
        const container = document.getElementById('google-status-container');
        if (!container) return;
        container.innerHTML = '<div class="kb-loading">' + window.t('google.loading') + '</div>';

        // Beide Stati parallel laden
        const [jarvisStatus, gogStatus, gogEnabled] = await Promise.all([
            this._fetchJson('/api/google/status'),
            this._fetchJson('/api/google/gog-status'),
            this._isGogEnabled(),
        ]);

        let html = '';

        // ── Sektion 1: Jarvis Google Apps ──
        html += this._renderJarvisSection(jarvisStatus);

        // ── Sektion 2: OpenClaw Gmail (gog) – nur wenn aktiviert ──
        if (gogEnabled) {
            html += '<div class="google-section-divider"></div>';
            html += this._renderGogSection(gogStatus);
        }

        container.innerHTML = html;
        this._attachGogListeners();
    }

    // ─── Sektion 1: Jarvis Google Apps ────────────────────────────

    _renderJarvisSection(status) {
        if (!status) return this._errorCard('Jarvis Google', window.t('google.conn_error'));

        let card = '';

        if (!status.configured) {
            card = `
                <div class="google-card google-card-warn">
                    <div class="google-card-icon">⚙️</div>
                    <div class="google-card-body">
                        <div class="google-card-title">${window.t('google.jarvis_not_configured')}</div>
                        <div class="google-card-desc">${window.t('google.jarvis_env_hint')}</div>
                        <ol class="google-setup-steps">
                            <li>${window.t('google.setup_step_console')}</li>
                            <li>${window.t('google.setup_step_apis')}</li>
                            <li>${window.t('google.setup_step_oauth')}</li>
                            <li>${window.t('google.setup_step_env')}</li>
                        </ol>
                    </div>
                </div>`;
        } else if (status.authenticated) {
            card = `
                <div class="google-card google-card-ok">
                    <div class="google-card-icon">✅</div>
                    <div class="google-card-body">
                        <div class="google-card-title">Jarvis Google Apps</div>
                        <div class="google-card-email">${status.email || ''}</div>
                        <div class="google-card-services">
                            <span class="google-service-badge">Gmail</span>
                            <span class="google-service-badge">Drive</span>
                            <span class="google-service-badge">Calendar</span>
                        </div>
                    </div>
                    <button class="kb-btn-action google-btn-revoke"
                        onclick="window.googleManager.revokeJarvis()">${window.t('google.disconnect')}</button>
                </div>`;
        } else {
            card = `
                <div class="google-card google-card-idle" id="jarvis-google-card">
                    <div class="google-card-icon">🔗</div>
                    <div class="google-card-body">
                        <div class="google-card-title">Jarvis Google Apps</div>
                        <div class="google-card-desc">${window.t('google.jarvis_desc')}</div>
                    </div>
                    <button class="kb-btn-action google-btn-connect"
                        onclick="window.googleManager.connectJarvis()">${window.t('google.connect_google')}</button>
                </div>`;
        }

        return `<div class="google-section">
            <div class="google-section-label">Jarvis Google Apps</div>
            ${card}
        </div>`;
    }

    // ─── Sektion 2: OpenClaw Gmail (gog) ──────────────────────────

    _renderGogSection(gogStatus) {
        // gog-Status auswerten
        const accounts  = gogStatus?.data?.accounts || [];
        const connected = accounts.length > 0;
        const email     = connected ? (accounts[0]?.email || accounts[0] || '') : '';

        // Credentials vorhanden?
        const hasCreds = gogStatus?.ok !== false;

        let card = '';

        if (connected) {
            // ── Verbunden ──
            card = `
                <div class="google-card google-card-ok">
                    <div class="google-card-icon">✅</div>
                    <div class="google-card-body">
                        <div class="google-card-title">${window.t('google.gog_connected')}</div>
                        <div class="google-card-email" id="gog-email-display">${email}</div>
                        <div class="google-card-services">
                            <span class="google-service-badge">Gmail</span>
                            <span class="google-service-badge">Calendar</span>
                            <span class="google-service-badge">Drive</span>
                        </div>
                    </div>
                    <button class="kb-btn-action google-btn-revoke" id="gog-remove-btn">${window.t('google.disconnect')}</button>
                </div>`;
        } else {
            // ── Setup-Formular ──
            card = `
                <div class="google-card google-card-idle gog-setup-card">
                    <div class="google-card-body" style="width:100%">
                        <div class="google-card-title">${window.t('google.gog_setup_title')}</div>
                        <div class="google-card-desc">${window.t('google.gog_setup_desc')}</div>

                        <div class="gog-form">
                            <div class="gog-form-row">
                                <label class="gog-label">${window.t('google.label_client_id')}</label>
                                <input id="gog-client-id" class="gog-input" type="text"
                                    placeholder="1234….apps.googleusercontent.com" autocomplete="off">
                            </div>
                            <div class="gog-form-row">
                                <label class="gog-label">${window.t('google.label_client_secret')}</label>
                                <input id="gog-client-secret" class="gog-input" type="password"
                                    placeholder="GOCSPX-…" autocomplete="off">
                            </div>
                            <div class="gog-form-row">
                                <label class="gog-label">${window.t('google.label_gmail_account')}</label>
                                <input id="gog-email" class="gog-input" type="email"
                                    placeholder="deine@gmail.com" autocomplete="off">
                            </div>

                            <div class="gog-btn-row">
                                <button id="gog-save-btn" class="gog-btn gog-btn-primary">
                                    ${window.t('google.save_credentials')}
                                </button>
                                <button id="gog-connect-btn" class="gog-btn gog-btn-connect" disabled>
                                    ${window.t('google.connect_gmail')}
                                </button>
                            </div>

                            <div id="gog-status-msg" class="gog-status-msg" style="display:none;"></div>
                        </div>
                    </div>
                </div>`;
        }

        return `<div class="google-section">
            <div class="google-section-label">OpenClaw Gmail <span class="gog-badge">gog v0.11</span></div>
            ${card}
        </div>`;
    }

    // ─── Event-Listener nach Render ───────────────────────────────

    _attachGogListeners() {
        const saveBtn    = document.getElementById('gog-save-btn');
        const connectBtn = document.getElementById('gog-connect-btn');
        const removeBtn  = document.getElementById('gog-remove-btn');

        if (saveBtn)    saveBtn.addEventListener('click',    () => this._gogSave());
        if (connectBtn) connectBtn.addEventListener('click', () => this._gogConnect());
        if (removeBtn)  removeBtn.addEventListener('click',  () => this._gogRemove());
    }

    // ─── gog Aktionen ─────────────────────────────────────────────

    async _gogSave() {
        const clientId     = document.getElementById('gog-client-id')?.value.trim();
        const clientSecret = document.getElementById('gog-client-secret')?.value.trim();
        const email        = document.getElementById('gog-email')?.value.trim();

        if (!clientId || !clientSecret || !email) {
            this._gogMsg(window.t('google.fill_all_fields'), 'warn'); return;
        }

        this._gogMsg(window.t('google.saving_credentials'), 'info');
        const saveBtn = document.getElementById('gog-save-btn');
        if (saveBtn) saveBtn.disabled = true;

        const result = await this._fetchJson('/api/google/gog-setup', {
            method: 'POST',
            body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, email }),
        });

        if (saveBtn) saveBtn.disabled = false;

        if (!result || result.error || !result.ok) {
            this._gogMsg('❌ ' + window.t('google.error_label') + ': ' + (result?.error || window.t('google.unknown')), 'error'); return;
        }

        this._gogEmail = email;
        this._gogMsg(window.t('google.credentials_saved'), 'success');
        const connectBtn = document.getElementById('gog-connect-btn');
        if (connectBtn) connectBtn.disabled = false;
    }

    async _gogConnect() {
        const email = this._gogEmail
            || document.getElementById('gog-email')?.value.trim();

        if (!email) {
            this._gogMsg(window.t('google.save_first'), 'warn'); return;
        }

        const connectBtn = document.getElementById('gog-connect-btn');
        if (connectBtn) { connectBtn.disabled = true; connectBtn.textContent = window.t('google.loading_url'); }

        // Schritt 1: Auth-URL vom Server holen
        const result = await this._fetchJson('/api/google/gog-auth-url', {
            method: 'POST',
            body: JSON.stringify({ email }),
        });

        if (connectBtn) { connectBtn.disabled = false; connectBtn.textContent = window.t('google.connect_gmail'); }

        if (!result || !result.ok) {
            this._gogMsg('❌ ' + (result?.error || window.t('google.auth_url_error')), 'error');
            return;
        }

        // Remote-Flow UI anzeigen
        this._renderRemoteFlow(result.auth_url, email);
    }

    _renderRemoteFlow(authUrl, email) {
        // Setup-Card durch Remote-Flow-Card ersetzen
        const card = document.querySelector('.gog-setup-card');
        if (!card) return;

        card.innerHTML = `
            <div class="google-card-body" style="width:100%">
                <div class="google-card-title">${window.t('google.connect_account_3steps')}</div>

                <div class="google-flow-steps" style="margin-top:0.85rem">
                    <div class="google-flow-step">
                        <span class="google-flow-num">1</span>
                        <span>${window.t('google.flow_step_open_link')}</span>
                    </div>
                </div>
                <a href="${authUrl}" target="_blank" class="gog-auth-link">
                    ${window.t('google.sign_in_google')}
                </a>

                <div class="google-flow-steps" style="margin-top:0.85rem">
                    <div class="google-flow-step">
                        <span class="google-flow-num">2</span>
                        <span>${window.t('google.flow_step_localhost')}</span>
                    </div>
                    <div class="google-flow-step">
                        <span class="google-flow-num">3</span>
                        <span>${window.t('google.flow_step_paste')}</span>
                    </div>
                </div>

                <div class="gog-form-row" style="margin-top:0.5rem">
                    <input id="gog-redirect-url" class="gog-input" type="text"
                        placeholder="http://localhost:…?code=…&scope=…" autocomplete="off">
                </div>

                <div class="gog-btn-row" style="margin-top:0.6rem">
                    <button id="gog-exchange-btn" class="gog-btn gog-btn-connect">
                        ${window.t('google.finish_connection')}
                    </button>
                    <button class="gog-btn"
                        onclick="window.googleManager._renderAll()">${window.t('google.cancel')}</button>
                </div>
                <div id="gog-status-msg" class="gog-status-msg" style="display:none;"></div>
            </div>`;

        // Exchange-Button Listener
        const exchangeBtn = document.getElementById('gog-exchange-btn');
        if (exchangeBtn) {
            exchangeBtn.addEventListener('click', () => this._gogExchange(email));
        }
    }

    async _gogExchange(email) {
        const redirectUrl = document.getElementById('gog-redirect-url')?.value.trim();
        if (!redirectUrl) {
            this._gogMsg(window.t('google.paste_redirect_url'), 'warn'); return;
        }

        const btn = document.getElementById('gog-exchange-btn');
        if (btn) { btn.disabled = true; btn.textContent = window.t('google.connecting'); }
        this._gogMsg(window.t('google.authenticating'), 'info');

        const result = await this._fetchJson('/api/google/gog-auth-exchange', {
            method: 'POST',
            body: JSON.stringify({ email, redirect_url: redirectUrl }),
        });

        if (!result || !result.ok) {
            this._gogMsg('❌ ' + (result?.error || window.t('google.error_label')), 'error');
            if (btn) { btn.disabled = false; btn.textContent = window.t('google.finish_connection'); }
            return;
        }

        this._gogMsg(window.t('google.connected_success'), 'success');
        setTimeout(() => this._renderAll(), 900);
    }

    async _gogRemove() {
        const emailEl = document.getElementById('gog-email-display');
        const email   = emailEl?.textContent.trim() || '';
        if (!email) { await this._renderAll(); return; }
        if (!confirm(window.t('google.confirm_disconnect_gog').replace('{email}', email))) return;

        await this._fetchJson('/api/google/gog-account', {
            method: 'DELETE',
            body: JSON.stringify({ email }),
        });
        await this._renderAll();
    }

    // ─── Jarvis Google Apps (Device Flow) ─────────────────────────

    async connectJarvis() {
        const btn = document.querySelector('#jarvis-google-card .google-btn-connect');
        if (btn) { btn.disabled = true; btn.textContent = '…'; }

        const result = await this._fetchJson('/api/google/device-start', { method: 'POST' });
        if (!result || result.error) {
            alert(window.t('google.error_label') + ': ' + (result?.error || window.t('google.unknown')));
            await this._renderAll(); return;
        }

        // Device-Flow-UI inline rendern
        const card = document.getElementById('jarvis-google-card');
        if (card) {
            const { user_code, verification_url, expires_in } = result;
            const min = Math.ceil(expires_in / 60);
            card.innerHTML = `
                <div class="google-card-icon">📱</div>
                <div class="google-card-body">
                    <div class="google-card-title">${window.t('google.connect_google_2steps')}</div>
                    <div class="google-flow-steps">
                        <div class="google-flow-step">
                            <span class="google-flow-num">1</span>
                            <span>${window.t('google.flow_step_open')}</span>
                            <a href="${verification_url}" target="_blank" class="google-flow-url">${verification_url}</a>
                        </div>
                        <div class="google-flow-step">
                            <span class="google-flow-num">2</span>
                            <span>${window.t('google.flow_step_enter_code')}</span>
                        </div>
                    </div>
                    <div class="google-flow-code">${user_code}</div>
                    <div class="google-flow-hint" id="jarvis-device-status">${window.t('google.waiting_min').replace('{min}', min)}</div>
                </div>
                <button class="kb-btn-action google-btn-revoke"
                    onclick="window.googleManager._stopDevicePoll();window.googleManager._renderAll()">${window.t('google.cancel')}</button>`;
        }
        this._startDevicePoll();
    }

    _startDevicePoll() {
        this._stopDevicePoll();
        this._devicePollTimer = setInterval(() => this._pollDeviceFlow(), 2000);
    }

    _stopDevicePoll() {
        if (this._devicePollTimer) { clearInterval(this._devicePollTimer); this._devicePollTimer = null; }
    }

    async _pollDeviceFlow() {
        const data = await this._fetchJson('/api/google/device-status');
        const el   = document.getElementById('jarvis-device-status');
        if (!data) return;

        if (data.status === 'authorized') {
            this._stopDevicePoll();
            if (el) el.textContent = '✅ ' + (data.message || window.t('google.device_connected'));
            setTimeout(() => this._renderAll(), 800);
        } else if (data.status === 'expired' || data.status === 'error') {
            this._stopDevicePoll();
            if (el) el.textContent = (data.status === 'expired' ? window.t('google.code_expired') : '❌ ' + window.t('google.error_label')) + window.t('google.try_again_suffix');
            setTimeout(() => this._renderAll(), 2500);
        } else if (el && data.expires_in_sec > 0) {
            const m = Math.floor(data.expires_in_sec / 60);
            const s = data.expires_in_sec % 60;
            el.textContent = window.t('google.waiting_countdown').replace('{t}', `${m}:${String(s).padStart(2,'0')}`);
        }
    }

    async revokeJarvis() {
        if (!confirm(window.t('google.confirm_disconnect_jarvis'))) return;
        await this._fetchJson('/api/google/revoke', { method: 'POST' });
        await this._renderAll();
    }

    // ─── Hilfsfunktionen ──────────────────────────────────────────

    async _isGogEnabled() {
        const data = await this._fetchJson('/api/skills');
        const skills = data?.skills || data || [];
        const s = Array.isArray(skills) ? skills.find(x => x.dir_name === 'openclaw_gmail') : null;
        return s?.enabled === true;
    }

    async _fetchJson(url, opts = {}) {
        const token = localStorage.getItem('jarvis_token') || '';
        const headers = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json', ...(opts.headers || {}) };
        try {
            const r = await fetch(url, { ...opts, headers });
            return await r.json();
        } catch { return null; }
    }

    _gogMsg(text, type = 'info') {
        const el = document.getElementById('gog-status-msg');
        if (!el) return;
        el.style.display = text ? '' : 'none';
        el.textContent   = text;
        el.className     = `gog-status-msg gog-msg-${type}`;
    }

    _errorCard(title, msg) {
        return `<div class="google-section">
            <div class="kb-empty" style="color:var(--danger);">${title}: ${msg}</div>
        </div>`;
    }
}

window.googleManager = new JarvisGoogleManager();
