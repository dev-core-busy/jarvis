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
        container.innerHTML = '<div class="kb-loading">Lade…</div>';

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
        if (!status) return this._errorCard('Jarvis Google', 'Verbindungsfehler');

        let card = '';

        if (!status.configured) {
            card = `
                <div class="google-card google-card-warn">
                    <div class="google-card-icon">⚙️</div>
                    <div class="google-card-body">
                        <div class="google-card-title">Jarvis Google Apps – nicht konfiguriert</div>
                        <div class="google-card-desc">
                            Füge in <code>.env</code> hinzu:<br>
                            <code>GOOGLE_OAUTH_CLIENT_ID=…</code><br>
                            <code>GOOGLE_OAUTH_CLIENT_SECRET=…</code><br>
                            OAuth-App-Typ: <strong>TV und Geräte mit eingeschränkter Eingabe</strong>
                        </div>
                        <ol class="google-setup-steps">
                            <li><a href="https://console.cloud.google.com/" target="_blank">Google Cloud Console</a> öffnen</li>
                            <li>APIs aktivieren: Gmail, Drive, Calendar</li>
                            <li>OAuth-Client → Typ: <strong>TV und eingeschränkte Eingabegeräte</strong></li>
                            <li>Client-ID + Secret in <code>.env</code> eintragen → Jarvis neu starten</li>
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
                        onclick="window.googleManager.revokeJarvis()">Trennen</button>
                </div>`;
        } else {
            card = `
                <div class="google-card google-card-idle" id="jarvis-google-card">
                    <div class="google-card-icon">🔗</div>
                    <div class="google-card-body">
                        <div class="google-card-title">Jarvis Google Apps</div>
                        <div class="google-card-desc">Gmail, Drive und Calendar via Device Flow verbinden.</div>
                    </div>
                    <button class="kb-btn-action google-btn-connect"
                        onclick="window.googleManager.connectJarvis()">Mit Google verbinden</button>
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
                        <div class="google-card-title">OpenClaw Gmail verbunden</div>
                        <div class="google-card-email" id="gog-email-display">${email}</div>
                        <div class="google-card-services">
                            <span class="google-service-badge">Gmail</span>
                            <span class="google-service-badge">Calendar</span>
                            <span class="google-service-badge">Drive</span>
                        </div>
                    </div>
                    <button class="kb-btn-action google-btn-revoke" id="gog-remove-btn">Trennen</button>
                </div>`;
        } else {
            // ── Setup-Formular ──
            card = `
                <div class="google-card google-card-idle gog-setup-card">
                    <div class="google-card-body" style="width:100%">
                        <div class="google-card-title">OpenClaw Gmail einrichten</div>
                        <div class="google-card-desc">
                            Einmalig: OAuth-Client aus der
                            <a href="https://console.cloud.google.com/" target="_blank">Google Cloud Console</a>
                            eintragen (Typ: <strong>Desktop-App</strong>).
                        </div>

                        <div class="gog-form">
                            <div class="gog-form-row">
                                <label class="gog-label">Client-ID</label>
                                <input id="gog-client-id" class="gog-input" type="text"
                                    placeholder="1234….apps.googleusercontent.com" autocomplete="off">
                            </div>
                            <div class="gog-form-row">
                                <label class="gog-label">Client-Secret</label>
                                <input id="gog-client-secret" class="gog-input" type="password"
                                    placeholder="GOCSPX-…" autocomplete="off">
                            </div>
                            <div class="gog-form-row">
                                <label class="gog-label">Gmail-Konto</label>
                                <input id="gog-email" class="gog-input" type="email"
                                    placeholder="deine@gmail.com" autocomplete="off">
                            </div>

                            <div class="gog-btn-row">
                                <button id="gog-save-btn" class="gog-btn gog-btn-primary">
                                    💾 Credentials speichern
                                </button>
                                <button id="gog-connect-btn" class="gog-btn gog-btn-connect" disabled>
                                    🔗 Mit Gmail verbinden
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
            this._gogMsg('⚠️ Bitte alle Felder ausfüllen.', 'warn'); return;
        }

        this._gogMsg('💾 Speichere Credentials…', 'info');
        const saveBtn = document.getElementById('gog-save-btn');
        if (saveBtn) saveBtn.disabled = true;

        const result = await this._fetchJson('/api/google/gog-setup', {
            method: 'POST',
            body: JSON.stringify({ client_id: clientId, client_secret: clientSecret, email }),
        });

        if (saveBtn) saveBtn.disabled = false;

        if (!result || result.error || !result.ok) {
            this._gogMsg('❌ Fehler: ' + (result?.error || 'Unbekannt'), 'error'); return;
        }

        this._gogEmail = email;
        this._gogMsg('✅ Credentials gespeichert! Jetzt "Mit Gmail verbinden" klicken.', 'success');
        const connectBtn = document.getElementById('gog-connect-btn');
        if (connectBtn) connectBtn.disabled = false;
    }

    async _gogConnect() {
        const email = this._gogEmail
            || document.getElementById('gog-email')?.value.trim();

        if (!email) {
            this._gogMsg('⚠️ Bitte zuerst Credentials speichern.', 'warn'); return;
        }

        const connectBtn = document.getElementById('gog-connect-btn');
        if (connectBtn) { connectBtn.disabled = true; connectBtn.textContent = '⏳ Lade URL…'; }

        // Schritt 1: Auth-URL vom Server holen
        const result = await this._fetchJson('/api/google/gog-auth-url', {
            method: 'POST',
            body: JSON.stringify({ email }),
        });

        if (connectBtn) { connectBtn.disabled = false; connectBtn.textContent = '🔗 Mit Gmail verbinden'; }

        if (!result || !result.ok) {
            this._gogMsg('❌ ' + (result?.error || 'Fehler beim Abrufen der Auth-URL'), 'error');
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
                <div class="google-card-title">Google-Konto verbinden – 3 Schritte</div>

                <div class="google-flow-steps" style="margin-top:0.85rem">
                    <div class="google-flow-step">
                        <span class="google-flow-num">1</span>
                        <span>Öffne diesen Link in deinem Browser und melde dich an:</span>
                    </div>
                </div>
                <a href="${authUrl}" target="_blank" class="gog-auth-link">
                    🔗 Jetzt bei Google anmelden
                </a>

                <div class="google-flow-steps" style="margin-top:0.85rem">
                    <div class="google-flow-step">
                        <span class="google-flow-num">2</span>
                        <span>Nach der Anmeldung versucht der Browser auf <code>localhost</code> weiterzuleiten
                        — das schlägt fehl. Kopiere die komplette URL aus der Adressleiste (beginnt mit
                        <code>http://localhost:…?code=…</code>).</span>
                    </div>
                    <div class="google-flow-step">
                        <span class="google-flow-num">3</span>
                        <span>Füge die URL hier ein:</span>
                    </div>
                </div>

                <div class="gog-form-row" style="margin-top:0.5rem">
                    <input id="gog-redirect-url" class="gog-input" type="text"
                        placeholder="http://localhost:…?code=…&scope=…" autocomplete="off">
                </div>

                <div class="gog-btn-row" style="margin-top:0.6rem">
                    <button id="gog-exchange-btn" class="gog-btn gog-btn-connect">
                        ✅ Verbindung abschließen
                    </button>
                    <button class="gog-btn"
                        onclick="window.googleManager._renderAll()">Abbrechen</button>
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
            this._gogMsg('⚠️ Bitte die Redirect-URL einfügen.', 'warn'); return;
        }

        const btn = document.getElementById('gog-exchange-btn');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Verbinde…'; }
        this._gogMsg('🔄 Authentifizierung läuft…', 'info');

        const result = await this._fetchJson('/api/google/gog-auth-exchange', {
            method: 'POST',
            body: JSON.stringify({ email, redirect_url: redirectUrl }),
        });

        if (!result || !result.ok) {
            this._gogMsg('❌ ' + (result?.error || 'Fehler'), 'error');
            if (btn) { btn.disabled = false; btn.textContent = '✅ Verbindung abschließen'; }
            return;
        }

        this._gogMsg('✅ Erfolgreich verbunden!', 'success');
        setTimeout(() => this._renderAll(), 900);
    }

    async _gogRemove() {
        const emailEl = document.getElementById('gog-email-display');
        const email   = emailEl?.textContent.trim() || '';
        if (!email) { await this._renderAll(); return; }
        if (!confirm(`OpenClaw Gmail-Konto "${email}" trennen?`)) return;

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
            alert('Fehler: ' + (result?.error || 'Unbekannt'));
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
                    <div class="google-card-title">Google verbinden – 2 Schritte</div>
                    <div class="google-flow-steps">
                        <div class="google-flow-step">
                            <span class="google-flow-num">1</span>
                            <span>Öffne:</span>
                            <a href="${verification_url}" target="_blank" class="google-flow-url">${verification_url}</a>
                        </div>
                        <div class="google-flow-step">
                            <span class="google-flow-num">2</span>
                            <span>Gib diesen Code ein:</span>
                        </div>
                    </div>
                    <div class="google-flow-code">${user_code}</div>
                    <div class="google-flow-hint" id="jarvis-device-status">⏳ Warte… (${min} Min)</div>
                </div>
                <button class="kb-btn-action google-btn-revoke"
                    onclick="window.googleManager._stopDevicePoll();window.googleManager._renderAll()">Abbrechen</button>`;
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
            if (el) el.textContent = '✅ ' + (data.message || 'Verbunden!');
            setTimeout(() => this._renderAll(), 800);
        } else if (data.status === 'expired' || data.status === 'error') {
            this._stopDevicePoll();
            if (el) el.textContent = (data.status === 'expired' ? '⚠️ Code abgelaufen' : '❌ Fehler') + ' – bitte erneut versuchen.';
            setTimeout(() => this._renderAll(), 2500);
        } else if (el && data.expires_in_sec > 0) {
            const m = Math.floor(data.expires_in_sec / 60);
            const s = data.expires_in_sec % 60;
            el.textContent = `⏳ Warte… (noch ${m}:${String(s).padStart(2,'0')} Min)`;
        }
    }

    async revokeJarvis() {
        if (!confirm('Jarvis Google-Verbindung trennen?')) return;
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
            <div class="kb-empty" style="color:#f87171;">${title}: ${msg}</div>
        </div>`;
    }
}

window.googleManager = new JarvisGoogleManager();
