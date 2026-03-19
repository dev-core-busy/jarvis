/**
 * Jarvis VNC/noVNC Integration
 *
 * Verbindungsstrategie:
 *  - noVNC wird über Same-Origin (/novnc/) geladen → kein separates SSL-Zertifikat
 *  - WebSocket-Proxy über /ws/vnc → FastAPI proxied direkt zu x11vnc (TCP 5900)
 *  - Sofortversuch beim Laden (initVNC in app.js)
 *  - startProbing(): zyklische Verfügbarkeitsprüfung via /api/config,
 *    verbindet automatisch sobald noVNC erreichbar — kein fixer Countdown
 */
class JarvisVNC {
    constructor() {
        this.iframe       = document.getElementById('vnc-iframe');
        this.placeholder  = document.getElementById('desktop-placeholder');
        this.statusEl     = document.getElementById('vnc-status');
        this.connected    = false;
        this.websockifyPort = null;
        this._reconnectTimer  = null;
        this._countdownTimer  = null;
        this._overlay     = null;
        this._probingActive = false;
    }

    // ─── Verbinden ────────────────────────────────────────────────

    connect(websockifyPort) {
        this.websockifyPort = websockifyPort;
        this._probingActive = false;
        this._clearTimers();

        const host = window.location.hostname || 'localhost';
        const port = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');

        // noVNC über Same-Origin laden (kein separates SSL-Zertifikat nötig)
        // WebSocket-Pfad: /ws/vnc → FastAPI proxied zu x11vnc TCP 5900
        const vncUrl = `/novnc/vnc.html?autoconnect=true&resize=scale&view_only=false&host=${host}&port=${port}&path=ws/vnc&encrypt=1`;

        this.iframe.src    = vncUrl;
        this.iframe.hidden = false;
        this.placeholder.hidden = true;
        this.connected     = true;
        this._removeOverlay();

        this.statusEl.textContent = 'Verbunden';
        this.statusEl.style.color = '#10b981';

        this.iframe.onerror = () => this.showError();
    }

    // ─── Intelligentes Probing (ersetzt fixen Countdown) ─────────

    /**
     * Zyklische VNC-Verfügbarkeitsprüfung.
     * Verbindet automatisch sobald /api/config vnc_available = true meldet.
     * @param {number} intervalMs   Intervall zwischen Versuchen (Default: 3000ms)
     * @param {number} maxAttempts  Max. Versuche bevor Fehler (Default: 40 = 2 Min)
     */
    startProbing(intervalMs = 3000, maxAttempts = 40) {
        if (this._probingActive) return;   // Läuft bereits
        this._probingActive = true;
        this.connected = false;

        this._clearTimers();
        this._showWaitingOverlay();
        this.statusEl.textContent = 'Warte auf Desktop…';
        this.statusEl.style.color = '#f59e0b';

        let attempts = 0;

        const probe = async () => {
            if (!this._probingActive) return;
            attempts++;

            try {
                const res  = await fetch('/api/config', { cache: 'no-store' });
                const data = await res.json();
                if (data.vnc_available) {
                    // VNC erreichbar → sofort verbinden
                    this._probingActive = false;
                    this._clearTimers();
                    this._removeOverlay();
                    // Kurze Pause damit x11vnc vollständig gestartet ist
                    setTimeout(() => this.connect(data.websockify_port), 400);
                    return;
                }
            } catch {
                // Server noch nicht bereit — weiter probieren
            }

            if (attempts >= maxAttempts) {
                this._probingActive = false;
                this._clearTimers();
                this._removeOverlay();
                this.showError();
                return;
            }

            this._reconnectTimer = setTimeout(probe, intervalMs);
        };

        // Sofortversuch, dann im Intervall
        probe();
    }

    /**
     * Probing abbrechen (z.B. wenn Tab geschlossen wird)
     */
    stopProbing() {
        this._probingActive = false;
        this._clearTimers();
    }

    // ─── Overlay: Warten auf Desktop ─────────────────────────────

    _showWaitingOverlay() {
        this._removeOverlay();

        const container = this.iframe.parentElement;
        this._overlay = document.createElement('div');
        this._overlay.className = 'vnc-reconnect-overlay';
        this._overlay.innerHTML = `
            <div class="vnc-reconnect-content">
                <div class="vnc-reconnect-spinner"></div>
                <div class="vnc-reconnect-text">Warte auf Desktop…</div>
                <div class="vnc-reconnect-sub">Verbindung wird automatisch hergestellt</div>
                <button class="vnc-reconnect-btn"
                    onclick="window._jarvisVNC && window._jarvisVNC._retryNow()">
                    Jetzt versuchen
                </button>
            </div>
        `;
        container.style.position = 'relative';
        container.appendChild(this._overlay);
        window._jarvisVNC = this;
    }

    /** Sofortiger Retry-Versuch aus dem Overlay-Button */
    _retryNow() {
        this.stopProbing();
        this.startProbing(3000, 40);
    }

    // ─── Hilfsmethoden ───────────────────────────────────────────

    _removeOverlay() {
        if (this._overlay && this._overlay.parentElement) {
            this._overlay.parentElement.removeChild(this._overlay);
        }
        this._overlay = null;
        window._jarvisVNC = null;
    }

    _clearTimers() {
        if (this._countdownTimer) { clearInterval(this._countdownTimer); this._countdownTimer = null; }
        if (this._reconnectTimer) { clearTimeout(this._reconnectTimer);  this._reconnectTimer = null; }
    }

    // ─── Fehler / Disconnect ──────────────────────────────────────

    showError() {
        this.connected = false;
        this.iframe.hidden = true;
        this.placeholder.hidden = false;
        this.placeholder.innerHTML = `
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.3">
                <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
                <line x1="8" y1="21" x2="16" y2="21"/>
                <line x1="12" y1="17" x2="12" y2="21"/>
            </svg>
            <p style="margin-top:1rem;color:#64748b;font-size:0.85rem;">
                Desktop-Vorschau nicht verfügbar.<br>
                <small>Prüfe: <code>x11vnc</code> auf Port 5900</small>
            </p>`;
        this.statusEl.textContent = 'Nicht verfügbar';
        this.statusEl.style.color = '#f59e0b';
    }

    disconnect() {
        this.stopProbing();
        this._removeOverlay();
        this.iframe.src    = '';
        this.iframe.hidden = true;
        this.placeholder.hidden = false;
        this.connected = false;
        this.statusEl.textContent = 'Nicht verbunden';
        this.statusEl.style.color = '';
    }

    /**
     * Legacy-Methode — leitet jetzt auf startProbing() um.
     * Kein fixer Countdown mehr.
     */
    reconnect() {
        if (!this.websockifyPort) return;
        this.connected = false;
        this.startProbing(3000, 40);
    }
}
