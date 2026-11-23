/**
 * Jarvis Google Apps – Settings-Tab UI
 *
 * Google Apps (Device Flow OAuth)
 */
class JarvisGoogleManager {
    constructor() {
        this._devicePollTimer  = null;
    }

    async init() {
        await this._renderAll();
    }

    // ─── Haupt-Render ──────────────────────────────────────────────

    async _renderAll() {
        const container = document.getElementById('google-status-container');
        if (!container) return;
        container.innerHTML = '<div class="kb-loading">' + window.t('google.loading') + '</div>';

        const jarvisStatus = await this._fetchJson('/api/google/status');
        container.innerHTML = this._renderJarvisSection(jarvisStatus);
    }

    // ─── Google Apps ──────────────────────────────────────────────

    _renderJarvisSection(status) {
        if (!status) return this._errorCard(window.t('google.jarvis_title'), window.t('google.conn_error'));

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
                        <div class="google-card-title">${window.t('google.jarvis_title')}</div>
                        <div class="google-card-email">${status.email || ''}</div>
                        <div class="google-card-services">
                            <span class="google-service-badge">Gmail</span>
                            <span class="google-service-badge">Drive</span>
                            <span class="google-service-badge">Calendar</span>
                        </div>
                    </div>
                    <button class="kb-btn-action google-btn-revoke"
                        data-gm-aktion="revokeJarvis">${window.t('google.disconnect')}</button>
                </div>`;
        } else {
            card = `
                <div class="google-card google-card-idle" id="jarvis-google-card">
                    <div class="google-card-icon">🔗</div>
                    <div class="google-card-body">
                        <div class="google-card-title">${window.t('google.jarvis_title')}</div>
                        <div class="google-card-desc">${window.t('google.jarvis_desc')}</div>
                    </div>
                    <button class="kb-btn-action google-btn-connect"
                        data-gm-aktion="connectJarvis">${window.t('google.connect_google')}</button>
                </div>`;
        }

        return `<div class="google-section">
            <div class="google-section-label">${window.t('google.jarvis_title')}</div>
            ${card}
        </div>`;
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
                    data-gm-aktion="abbrechenPoll">${window.t('google.cancel')}</button>`;
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
        // Ein confirm()-Text landet nie im DOM: branding.js kann {marke}
        // dort nicht ersetzen, das muss der Aufrufort tun.
        const marke = (window.jarvisMarke && window.jarvisMarke()) || 'Jarvis';
        if (!confirm(window.t('google.confirm_disconnect_jarvis')
                .split('{marke}').join(marke))) return;
        await this._fetchJson('/api/google/revoke', { method: 'POST' });
        await this._renderAll();
    }

    // ─── Hilfsfunktionen ──────────────────────────────────────────

    async _fetchJson(url, opts = {}) {
        const token = window.JarvisSitzung.token();
        const headers = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json', ...(opts.headers || {}) };
        try {
            const r = await fetch(url, { ...opts, headers });
            return await r.json();
        } catch { return null; }
    }

    _errorCard(title, msg) {
        return `<div class="google-section">
            <div class="kb-empty" style="color:var(--danger);">${title}: ${msg}</div>
        </div>`;
    }
}

// ─── Delegierte Knopf-Aktionen (BSI H4, 2026-10-04) ──────────────────
// Eine CSP mit script-src 'self' OHNE 'unsafe-inline' blockiert jedes
// onclick= im per innerHTML gebauten Markup. Die Knoepfe tragen nur noch
// data-gm-aktion; verteilt wird ueber eine FESTE Zuordnung (kein Aufruf
// eines beliebigen Namens aus dem Attribut). Unbekanntes tut nichts.
// Capture-Phase: die Aktion laeuft wie vorher der Inline-Handler vor allen
// Bubble-Listenern der Vorfahren.
(() => {
    if (window._gmAktionenGebunden) return;
    window._gmAktionenGebunden = true;
    const AKTIONEN = {
        revokeJarvis:  (gm) => gm.revokeJarvis(),
        connectJarvis: (gm) => gm.connectJarvis(),
        abbrechenPoll: (gm) => { gm._stopDevicePoll(); gm._renderAll(); },
    };
    document.addEventListener('click', (e) => {
        const el = e.target && e.target.closest ? e.target.closest('[data-gm-aktion]') : null;
        if (!el) return;
        const name = el.getAttribute('data-gm-aktion');
        if (!Object.prototype.hasOwnProperty.call(AKTIONEN, name)) return;
        const gm = window.googleManager;
        if (gm) AKTIONEN[name](gm);
    }, true);
})();

window.googleManager = new JarvisGoogleManager();
