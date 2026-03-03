/**
 * Jarvis WhatsApp Manager – Frontend-Steuerung fuer WhatsApp-Tab
 */

class JarvisWhatsAppManager {
    constructor() {
        this._pollInterval = null;
        this._logPollInterval = null;
        this._qrLibLoaded = false;

        // Buttons verbinden
        const btnReconnect = document.getElementById('btn-wa-reconnect');
        const btnLogout = document.getElementById('btn-wa-logout');
        if (btnReconnect) btnReconnect.addEventListener('click', () => this.reconnect());
        if (btnLogout) btnLogout.addEventListener('click', () => this.logout());

        // Log-Controls
        const btnLogsRefresh = document.getElementById('btn-wa-logs-refresh');
        const btnLogsClear = document.getElementById('btn-wa-logs-clear');
        const debugToggle = document.getElementById('wa-debug-toggle');
        const logFilter = document.getElementById('wa-log-filter');
        const logSource = document.getElementById('wa-log-source');

        if (btnLogsRefresh) btnLogsRefresh.addEventListener('click', () => this.fetchLogs());
        if (btnLogsClear) btnLogsClear.addEventListener('click', () => this.clearLogs());
        if (debugToggle) debugToggle.addEventListener('change', (e) => this.toggleDebug(e.target.checked));
        if (logFilter) logFilter.addEventListener('change', () => this.fetchLogs());
        if (logSource) logSource.addEventListener('change', () => this.fetchLogs());

        // Debug-Toggle Initialzustand laden
        this._loadDebugState();
    }

    async refresh() {
        this._startPolling();
        await this._fetchStatus();
        await this.fetchLogs();
        this._startLogPolling();
    }

    stop() {
        this._stopPolling();
        this._stopLogPolling();
    }

    _startPolling() {
        this._stopPolling();
        this._pollInterval = setInterval(() => this._fetchStatus(), 3000);
    }

    _stopPolling() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    }

    async _fetchStatus() {
        try {
            const resp = await fetch('/api/whatsapp/status');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            this._updateUI(data);

            // QR-Code laden wenn noetig
            if (data.state === 'qr_pending' && data.has_qr) {
                await this._fetchQR();
            }
        } catch (e) {
            this._updateUI({
                state: 'error',
                connected_number: null,
                has_qr: false,
                message_count: 0,
                last_error: 'Bridge nicht erreichbar'
            });
        }
    }

    _updateUI(data) {
        const state = data.state || 'disconnected';
        const number = data.connected_number;
        const msgCount = data.message_count || 0;
        const lastError = data.last_error;

        // Status-Badge
        const badge = document.getElementById('wa-status-badge');
        if (badge) {
            badge.className = 'wa-status-badge ' + state;
            const labels = {
                'connected': 'Verbunden',
                'qr_pending': 'QR-Scan',
                'connecting': 'Verbindet...',
                'disconnected': 'Getrennt',
                'error': 'Fehler'
            };
            badge.textContent = labels[state] || state;
        }

        // Status-Icon
        const icon = document.getElementById('wa-status-icon');
        if (icon) {
            icon.className = 'wa-status-icon';
            if (state === 'disconnected' || state === 'error') icon.classList.add('disconnected');
            if (state === 'connecting') icon.classList.add('connecting');
        }

        // Status-Text
        const statusText = document.getElementById('wa-status-text');
        if (statusText) {
            const texts = {
                'connected': 'WhatsApp verbunden',
                'qr_pending': 'Warte auf QR-Scan',
                'connecting': 'Verbinde...',
                'disconnected': 'Nicht verbunden',
                'error': 'Fehler'
            };
            statusText.textContent = texts[state] || 'Unbekannt';
        }

        // Detail-Text
        const detail = document.getElementById('wa-status-detail');
        if (detail) {
            if (lastError) {
                detail.textContent = lastError;
            } else if (state === 'connected') {
                detail.textContent = 'Bereit fuer Nachrichten';
            } else if (state === 'qr_pending') {
                detail.textContent = 'Scanne den QR-Code mit deinem Handy';
            } else {
                detail.textContent = '';
            }
        }

        // Stats
        const numEl = document.getElementById('wa-connected-number');
        if (numEl) numEl.textContent = number ? `+${number}` : '--';

        const msgEl = document.getElementById('wa-msg-count');
        if (msgEl) msgEl.textContent = msgCount;

        // QR-Section Sichtbarkeit
        const qrSection = document.getElementById('wa-qr-section');
        if (qrSection) {
            if (state === 'connected') {
                qrSection.style.display = 'none';
            } else {
                qrSection.style.display = '';
            }
        }

        // Bei Verbindung: "Connected" im QR-Bereich zeigen
        if (state === 'connected') {
            const qrBox = document.getElementById('wa-qr-box');
            if (qrBox) {
                qrBox.innerHTML = `
                    <div class="wa-qr-connected">
                        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                            <polyline points="22 4 12 14.01 9 11.01"/>
                        </svg>
                        Verbunden
                    </div>`;
            }
        }
    }

    async _fetchQR() {
        try {
            const resp = await fetch('/api/whatsapp/qr');
            if (!resp.ok) return;
            const data = await resp.json();

            if (data.qr) {
                await this._renderQR(data.qr);
            }
        } catch (e) {
            console.error('[WA] QR-Fetch Fehler:', e);
        }
    }

    async _renderQR(qrData) {
        const qrBox = document.getElementById('wa-qr-box');
        if (!qrBox) return;

        // QRCode-Library laden falls noetig
        if (!this._qrLibLoaded) {
            await this._loadQRLib();
        }

        if (typeof QRCode === 'undefined') {
            qrBox.innerHTML = '<div class="wa-qr-loading">QR-Library fehlt</div>';
            return;
        }

        // QR-Code rendern
        qrBox.innerHTML = '';
        try {
            new QRCode(qrBox, {
                text: qrData,
                width: 200,
                height: 200,
                colorDark: '#000000',
                colorLight: '#ffffff',
                correctLevel: QRCode.CorrectLevel.M,
            });
        } catch (e) {
            // Fallback: Einfaches Canvas
            qrBox.innerHTML = '<div class="wa-qr-loading">QR-Code wird generiert...</div>';
            console.error('[WA] QR-Render Fehler:', e);
        }
    }

    async _loadQRLib() {
        if (typeof QRCode !== 'undefined') {
            this._qrLibLoaded = true;
            return;
        }

        return new Promise((resolve) => {
            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js';
            script.onload = () => {
                this._qrLibLoaded = true;
                resolve();
            };
            script.onerror = () => {
                console.error('[WA] QRCode-Library konnte nicht geladen werden');
                // Fallback: eigene minimale QR-Darstellung
                this._qrLibLoaded = false;
                resolve();
            };
            document.head.appendChild(script);
        });
    }

    // ─── Log-Polling ──────────────────────────────────────────────

    _startLogPolling() {
        this._stopLogPolling();
        this._logPollInterval = setInterval(() => this.fetchLogs(), 5000);
    }

    _stopLogPolling() {
        if (this._logPollInterval) {
            clearInterval(this._logPollInterval);
            this._logPollInterval = null;
        }
    }

    async _loadDebugState() {
        try {
            const token = localStorage.getItem('jarvis_token');
            const resp = await fetch('/api/skills/whatsapp', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (resp.ok) {
                const data = await resp.json();
                const dbg = data.config?.debug_mode || false;
                const toggle = document.getElementById('wa-debug-toggle');
                if (toggle) toggle.checked = dbg;
            }
        } catch (e) { /* ignore */ }
    }

    async toggleDebug(enabled) {
        try {
            const token = localStorage.getItem('jarvis_token');
            await fetch('/api/skills/whatsapp/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({ debug_mode: enabled })
            });
        } catch (e) {
            console.error('[WA] Debug-Toggle Fehler:', e);
        }
    }

    async fetchLogs() {
        const token = localStorage.getItem('jarvis_token');
        const levelFilter = document.getElementById('wa-log-filter')?.value || '';
        const source = document.getElementById('wa-log-source')?.value || '';
        const container = document.getElementById('wa-logs-container');
        if (!container) return;

        let allLogs = [];

        try {
            // Backend-Logs
            if (source !== 'bridge') {
                const params = new URLSearchParams({ lines: '150' });
                if (levelFilter) params.set('level', levelFilter);
                const resp = await fetch(`/api/whatsapp/logs?${params}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (resp.ok) {
                    const data = await resp.json();
                    allLogs.push(...(data.logs || []).map(l => ({ ...l, src: 'B' })));
                }
            }

            // Bridge-Logs (via Proxy)
            if (source !== 'backend') {
                const params = new URLSearchParams({ lines: '150' });
                if (levelFilter) params.set('level', levelFilter);
                const resp = await fetch(`/api/whatsapp/bridge-logs?${params}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (resp.ok) {
                    const data = await resp.json();
                    allLogs.push(...(data.logs || []).map(l => ({ ...l, src: 'W' })));
                }
            }
        } catch (e) {
            container.innerHTML = '<div class="wa-logs-empty">Logs konnten nicht geladen werden</div>';
            return;
        }

        if (allLogs.length === 0) {
            container.innerHTML = '<div class="wa-logs-empty">Keine Logs vorhanden</div>';
            return;
        }

        // Nach Zeitstempel sortieren
        allLogs.sort((a, b) => (a.ts || '').localeCompare(b.ts || ''));
        const last200 = allLogs.slice(-200);

        const wasScrolledToBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 20;

        container.innerHTML = last200.map(e => {
            const ts = (e.ts || '').substring(11, 19);
            const meta = e.meta ? `<div class="wa-log-meta">${this._escHtml(JSON.stringify(e.meta))}</div>` : '';
            return `<div class="wa-log-entry">` +
                `<span class="wa-log-ts">${ts}</span>` +
                `<span class="wa-log-level ${e.level}">${e.level}</span>` +
                `<span class="wa-log-cat">[${e.src}/${e.cat || '?'}]</span>` +
                `<span class="wa-log-msg">${this._escHtml(e.msg || '')}${meta}</span>` +
                `</div>`;
        }).join('');

        if (wasScrolledToBottom) {
            container.scrollTop = container.scrollHeight;
        }
    }

    async clearLogs() {
        const token = localStorage.getItem('jarvis_token');
        try {
            await Promise.all([
                fetch('/api/whatsapp/logs', {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                }),
                fetch('/api/whatsapp/bridge-logs', {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                })
            ]);
            await this.fetchLogs();
        } catch (e) {
            console.error('[WA] Logs-Clear Fehler:', e);
        }
    }

    _escHtml(s) {
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ─── Verbindungs-Aktionen ───────────────────────────────────────

    async reconnect() {
        try {
            const resp = await fetch('/api/whatsapp/reconnect', { method: 'POST' });
            const data = await resp.json();
            if (data.success) {
                // Warte kurz, dann Status neu laden
                setTimeout(() => this._fetchStatus(), 2000);
            }
        } catch (e) {
            console.error('[WA] Reconnect Fehler:', e);
        }
    }

    async logout() {
        if (!confirm('WhatsApp wirklich abmelden? Du musst den QR-Code erneut scannen.')) return;

        try {
            const resp = await fetch('/api/whatsapp/logout', { method: 'POST' });
            const data = await resp.json();
            if (data.success) {
                setTimeout(() => this._fetchStatus(), 3000);
            }
        } catch (e) {
            console.error('[WA] Logout Fehler:', e);
        }
    }
}

// Global initialisieren
document.addEventListener('DOMContentLoaded', () => {
    window.waManager = new JarvisWhatsAppManager();
});
