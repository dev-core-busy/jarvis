/**
 * Jarvis Kontext-Manager
 * Zeigt History-Umfang, Token-Verbrauch, Schwellwert-Einstellung und manuelle Komprimierung.
 * Design: kb-container / kb-section System
 */
window.contextManager = new (class JarvisContextManager {
    constructor() {
        this._pollTimer  = null;
        this._initialized = false;
    }

    init() {
        if (!this._initialized) {
            this._bindButtons();
            this._initialized = true;
        }
        this._load();
        // Alle 5s automatisch aktualisieren solange Tab offen
        this._startPoll();
    }

    stop() {
        if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
    }

    _startPoll() {
        this.stop();
        this._pollTimer = setInterval(() => this._load(), 5000);
    }

    _bindButtons() {
        const refreshBtn  = document.getElementById('ctx-refresh-btn');
        const saveBtn     = document.getElementById('ctx-threshold-save');
        const compressBtn = document.getElementById('ctx-compress-btn');

        if (refreshBtn)  refreshBtn.onclick  = () => this._load();
        if (saveBtn)     saveBtn.onclick      = () => this._saveThreshold();
        if (compressBtn) compressBtn.onclick  = () => this._forceCompress();
    }

    async _load() {
        try {
            const r = await fetch('/api/context/stats', { headers: _authHeaders() });
            if (!r.ok) return;
            const d = await r.json();
            this._render(d);
        } catch (e) { console.error('[CtxMgr] Ladefehler:', e); }
    }

    _render(d) {
        const $ = id => document.getElementById(id);

        // Stat-Kacheln
        const fmt = n => (n === undefined || n === null) ? '—' : n.toLocaleString('de-DE');
        $('ctx-history-entries') && ($('ctx-history-entries').textContent = fmt(d.history_entries));
        $('ctx-fills-pct')       && ($('ctx-fills-pct').textContent       = d.fills_pct !== undefined ? d.fills_pct + ' %' : '—');
        $('ctx-input-tokens')    && ($('ctx-input-tokens').textContent     = fmt(d.session_input_tokens));
        $('ctx-output-tokens')   && ($('ctx-output-tokens').textContent    = fmt(d.session_output_tokens));
        $('ctx-total-tokens')    && ($('ctx-total-tokens').textContent     = fmt(d.session_total_tokens));
        $('ctx-hist-tokens')     && ($('ctx-hist-tokens').textContent      = fmt(d.estimated_history_tokens));

        // Agent-Status mit Farbe
        const stateEl = $('ctx-agent-state');
        if (stateEl) {
            const stateMap = {
                idle:    { label: 'Bereit',    color: 'var(--text-secondary)' },
                running: { label: 'Läuft',     color: 'var(--success-color,#2ecc71)' },
                paused:  { label: 'Pausiert',  color: '#f39c12' },
                stopped: { label: 'Gestoppt',  color: '#e74c3c' },
            };
            const s = stateMap[d.agent_state] || { label: d.agent_state || '—', color: 'var(--text-secondary)' };
            stateEl.textContent = s.label;
            stateEl.style.color = s.color;
        }

        // Schwellwert-Anzeige
        $('ctx-threshold-display') && ($('ctx-threshold-display').textContent = fmt(d.compress_threshold));

        // Schwellwert-Input nur vorbelegen wenn noch nicht vom User verändert
        const inp = $('ctx-threshold-input');
        if (inp && !inp._userEdited) {
            inp.value = d.compress_threshold ?? 30;
            inp.addEventListener('input', () => { inp._userEdited = true; }, { once: true });
        }

        // Fortschrittsbalken
        const bar   = $('ctx-fills-bar');
        const label = $('ctx-fills-label');
        if (bar) {
            const pct = Math.min(100, d.fills_pct ?? 0);
            bar.style.width = pct + '%';
            // Farbverlauf: grün → orange → rot
            bar.style.background = pct < 60 ? 'var(--accent)' : pct < 85 ? '#f39c12' : '#e74c3c';
        }
        if (label) {
            label.textContent = `${d.history_entries ?? 0} / ${d.compress_threshold ?? 30} Einträge`;
        }
    }

    async _saveThreshold() {
        const inp = document.getElementById('ctx-threshold-input');
        if (!inp) return;
        const val = parseInt(inp.value, 10);
        if (isNaN(val) || val < 4 || val > 200) {
            this._notify('Ungültiger Wert (4–200)', 'error'); return;
        }
        try {
            const r = await fetch('/api/context/threshold', {
                method: 'POST',
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ threshold: val })
            });
            const d = await r.json();
            this._notify(`✅ Schwellwert auf ${d.threshold} gesetzt`);
            inp._userEdited = false;
            this._load();
        } catch (e) { this._notify('Netzwerkfehler: ' + e.message, 'error'); }
    }

    async _forceCompress() {
        const btn = document.getElementById('ctx-compress-btn');
        const res = document.getElementById('ctx-compress-result');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ Komprimiere…'; }
        try {
            const r = await fetch('/api/context/compress', {
                method: 'POST',
                headers: _authHeaders()
            });
            const d = await r.json();
            if (d.skipped) {
                this._notify(`ℹ️ Nicht komprimiert: ${d.reason}`, 'info');
                if (res) res.textContent = `Nicht nötig: ${d.reason}`;
            } else {
                this._notify(`✅ Komprimiert: ${d.before} → ${d.after} Einträge`);
                if (res) res.textContent = `Letzte Komprimierung: ${d.before} → ${d.after} Einträge`;
            }
            this._load();
        } catch (e) {
            this._notify('Fehler: ' + e.message, 'error');
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '🗜️ Jetzt komprimieren'; }
        }
    }

    _notify(msg, type = 'success') {
        const el = document.getElementById('ctx-notification');
        if (!el) return;
        el.textContent = msg;
        el.className = `kb-notification kb-notification-${type}`;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 4000);
    }
})();
