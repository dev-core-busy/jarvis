/**
 * Jarvis Cron-Trigger UI
 * Verwaltet geplante Aufgaben (Cron-Jobs) und Datei-Watcher.
 */
class JarvisCronManager {
    constructor() {
        this._jobs = [];
        this._editingId = null;
        this._container = null;
    }

    init() {
        this._container = document.getElementById('cron-tab-content');
        if (!this._container) return;
        this._render();
        this._load();
        this._bindForm();
    }

    // ─── Laden ───────────────────────────────────────────────────────────

    async _load() {
        try {
            const r = await fetch('/api/cron', { headers: _authHeaders() });
            if (!r.ok) return;
            this._jobs = await r.json();
            this._renderList();
        } catch (e) {
            console.error('[Cron] Ladefehler:', e);
        }
    }

    // ─── Render ──────────────────────────────────────────────────────────

    _render() {
        this._container.innerHTML = `
        <div style="display:flex;gap:12px;align-items:center;margin-bottom:16px;">
            <h3 style="margin:0;font-size:1rem;">⏰ Geplante Aufgaben</h3>
            <button id="cron-add-btn" class="settings-btn" style="margin-left:auto;">+ Neue Aufgabe</button>
            <button id="cron-refresh-btn" class="settings-btn settings-btn-secondary" title="Aktualisieren">🔄</button>
        </div>

        <!-- Formular (collapsed by default) -->
        <div id="cron-form-wrap" style="display:none;background:var(--bg-glass);border:1px solid var(--border-color);border-radius:12px;padding:16px;margin-bottom:16px;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                <div>
                    <label style="font-size:0.78rem;color:var(--text-muted);display:block;margin-bottom:4px;">Bezeichnung</label>
                    <input id="cron-label" type="text" placeholder="z.B. Täglicher Server-Report" class="settings-input" style="width:100%;">
                </div>
                <div>
                    <label style="font-size:0.78rem;color:var(--text-muted);display:block;margin-bottom:4px;">
                        Zeitplan (Cron)
                        <a href="https://crontab.guru" target="_blank" style="color:var(--accent-color);margin-left:6px;font-size:0.75rem;">Hilfe ↗</a>
                    </label>
                    <input id="cron-schedule" type="text" placeholder="0 8 * * *  (täglich 8:00 Uhr)" class="settings-input" style="width:100%;">
                </div>
            </div>
            <div style="margin-bottom:10px;">
                <label style="font-size:0.78rem;color:var(--text-muted);display:block;margin-bottom:4px;">Aufgabe für Jarvis</label>
                <textarea id="cron-task" rows="3" placeholder="Was soll Jarvis tun? z.B.: Prüfe Server-Auslastung und sende Zusammenfassung per WhatsApp." class="settings-input" style="width:100%;resize:vertical;"></textarea>
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
                <label style="display:flex;align-items:center;gap:6px;font-size:0.85rem;cursor:pointer;">
                    <input id="cron-enabled" type="checkbox" checked style="width:16px;height:16px;"> Aktiv
                </label>
                <div style="margin-left:auto;display:flex;gap:8px;">
                    <button id="cron-cancel-btn" class="settings-btn settings-btn-secondary">Abbrechen</button>
                    <button id="cron-save-btn" class="settings-btn">Speichern</button>
                </div>
            </div>
            <div id="cron-form-error" style="color:var(--error-color,#e74c3c);font-size:0.8rem;margin-top:8px;display:none;"></div>
        </div>

        <!-- Cron-Beispiele -->
        <div id="cron-examples" style="margin-bottom:12px;display:flex;flex-wrap:wrap;gap:6px;">
            ${[
                ['Täglich 8:00', '0 8 * * *'],
                ['Stündlich', '0 * * * *'],
                ['Montags 9:00', '0 9 * * 1'],
                ['Alle 15 Min', '*/15 * * * *'],
                ['1. des Monats', '0 0 1 * *'],
            ].map(([l, c]) => `<button class="cron-example-btn settings-btn settings-btn-secondary" data-cron="${c}" style="font-size:0.75rem;padding:3px 10px;">${l}<span style="color:var(--text-muted);margin-left:4px;font-family:monospace;">${c}</span></button>`).join('')}
        </div>

        <!-- Job-Liste -->
        <div id="cron-list"></div>
        `;

        // Beispiel-Buttons
        this._container.querySelectorAll('.cron-example-btn').forEach(btn => {
            btn.onclick = () => {
                document.getElementById('cron-schedule').value = btn.dataset.cron;
            };
        });

        document.getElementById('cron-add-btn').onclick = () => this._showForm();
        document.getElementById('cron-refresh-btn').onclick = () => this._load();
        document.getElementById('cron-cancel-btn').onclick = () => this._hideForm();
    }

    _renderList() {
        const el = document.getElementById('cron-list');
        if (!el) return;
        if (!this._jobs.length) {
            el.innerHTML = `<div style="text-align:center;padding:32px;color:var(--text-muted);font-size:0.9rem;">
                Noch keine geplanten Aufgaben.<br>Klicke <strong>+ Neue Aufgabe</strong> um loszulegen.
            </div>`;
            return;
        }
        el.innerHTML = this._jobs.map(job => {
            const lastRun = job.last_run
                ? new Date(job.last_run * 1000).toLocaleString('de-DE')
                : '—';
            const statusColor = job.enabled ? 'var(--success-color,#2ecc71)' : 'var(--text-muted)';
            return `
            <div class="cron-job-card" data-id="${job.id}" style="background:var(--bg-glass);border:1px solid var(--border-color);border-radius:10px;padding:14px 16px;margin-bottom:8px;">
                <div style="display:flex;align-items:center;gap:10px;">
                    <div style="width:10px;height:10px;border-radius:50%;background:${statusColor};flex-shrink:0;"></div>
                    <span style="font-weight:600;font-size:0.95rem;flex:1;">${this._esc(job.label)}</span>
                    <code style="font-size:0.8rem;background:rgba(255,255,255,0.08);padding:2px 8px;border-radius:6px;">${this._esc(job.cron)}</code>
                    <button class="settings-btn settings-btn-secondary cron-run-btn" data-id="${job.id}" title="Jetzt ausführen" style="padding:3px 10px;font-size:0.78rem;">▶ Jetzt</button>
                    <button class="settings-btn settings-btn-secondary cron-edit-btn" data-id="${job.id}" style="padding:3px 10px;font-size:0.78rem;">✏️</button>
                    <button class="settings-btn settings-btn-danger cron-del-btn" data-id="${job.id}" style="padding:3px 10px;font-size:0.78rem;">🗑️</button>
                    <label style="display:flex;align-items:center;gap:5px;cursor:pointer;font-size:0.8rem;margin-left:4px;">
                        <input type="checkbox" class="cron-toggle" data-id="${job.id}" ${job.enabled ? 'checked' : ''}>
                    </label>
                </div>
                <div style="margin-top:8px;font-size:0.82rem;color:var(--text-muted);padding-left:20px;">${this._esc(job.task)}</div>
                <div style="margin-top:6px;font-size:0.75rem;color:var(--text-muted);padding-left:20px;">
                    Letzter Lauf: ${lastRun}
                    ${job.last_result ? `<span style="margin-left:8px;color:var(--text-secondary);">→ ${this._esc(job.last_result.substring(0, 80))}${job.last_result.length > 80 ? '…' : ''}</span>` : ''}
                </div>
            </div>`;
        }).join('');

        // Events
        el.querySelectorAll('.cron-del-btn').forEach(btn => {
            btn.onclick = () => this._delete(btn.dataset.id);
        });
        el.querySelectorAll('.cron-edit-btn').forEach(btn => {
            btn.onclick = () => this._editJob(btn.dataset.id);
        });
        el.querySelectorAll('.cron-run-btn').forEach(btn => {
            btn.onclick = () => this._runNow(btn.dataset.id, btn);
        });
        el.querySelectorAll('.cron-toggle').forEach(cb => {
            cb.onchange = () => this._toggle(cb.dataset.id, cb.checked);
        });
    }

    // ─── Formular ────────────────────────────────────────────────────────

    _bindForm() {
        document.getElementById('cron-save-btn').onclick = () => this._save();
    }

    _showForm(job = null) {
        this._editingId = job ? job.id : null;
        document.getElementById('cron-label').value = job ? job.label : '';
        document.getElementById('cron-schedule').value = job ? job.cron : '';
        document.getElementById('cron-task').value = job ? job.task : '';
        document.getElementById('cron-enabled').checked = job ? job.enabled : true;
        document.getElementById('cron-form-error').style.display = 'none';
        document.getElementById('cron-form-wrap').style.display = 'block';
        document.getElementById('cron-examples').style.display = job ? 'none' : '';
        document.getElementById('cron-label').focus();
    }

    _hideForm() {
        this._editingId = null;
        document.getElementById('cron-form-wrap').style.display = 'none';
        document.getElementById('cron-examples').style.display = '';
    }

    _editJob(id) {
        const job = this._jobs.find(j => j.id === id);
        if (job) this._showForm(job);
    }

    async _save() {
        const label = document.getElementById('cron-label').value.trim();
        const cron = document.getElementById('cron-schedule').value.trim();
        const task = document.getElementById('cron-task').value.trim();
        const enabled = document.getElementById('cron-enabled').checked;
        const errEl = document.getElementById('cron-form-error');

        if (!label || !cron || !task) {
            errEl.textContent = 'Bitte alle Felder ausfüllen.';
            errEl.style.display = 'block';
            return;
        }
        errEl.style.display = 'none';

        try {
            const method = this._editingId ? 'PUT' : 'POST';
            const url = this._editingId ? `/api/cron/${this._editingId}` : '/api/cron';
            const r = await fetch(url, {
                method,
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ label, cron, task, enabled }),
            });
            if (!r.ok) {
                const err = await r.json().catch(() => ({}));
                errEl.textContent = err.detail || 'Fehler beim Speichern.';
                errEl.style.display = 'block';
                return;
            }
            this._hideForm();
            this._load();
        } catch (e) {
            errEl.textContent = 'Netzwerkfehler: ' + e.message;
            errEl.style.display = 'block';
        }
    }

    // ─── Aktionen ────────────────────────────────────────────────────────

    async _delete(id) {
        if (!confirm('Aufgabe wirklich löschen?')) return;
        await fetch(`/api/cron/${id}`, { method: 'DELETE', headers: _authHeaders() });
        this._load();
    }

    async _toggle(id, enabled) {
        await fetch(`/api/cron/${id}`, {
            method: 'PUT',
            headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        });
        this._load();
    }

    async _runNow(id, btn) {
        const orig = btn.textContent;
        btn.textContent = '⏳';
        btn.disabled = true;
        try {
            const r = await fetch(`/api/cron/${id}/run`, { method: 'POST', headers: _authHeaders() });
            const data = await r.json();
            btn.textContent = '✅';
            setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
            this._load();
        } catch (e) {
            btn.textContent = '❌';
            setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
        }
    }

    // ─── WebSocket-Events ─────────────────────────────────────────────────

    handleWsEvent(msg) {
        if (msg.type !== 'cron_event') return;
        // Job-Liste aktualisieren nach jedem Lauf
        if (msg.event === 'finished') {
            this._load();
        }
    }

    // ─── Hilfsfunktionen ─────────────────────────────────────────────────

    _esc(str) {
        return String(str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
}

// Singleton
const cronManager = new JarvisCronManager();
