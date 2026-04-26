/**
 * Jarvis Trigger-UI
 * Verwaltet geplante Aufgaben (Cron-Jobs) und Datei-Watcher.
 * Design: kb-container / kb-section System (wie Wissen- und Skills-Tab)
 */
window.cronManager = new (class JarvisCronManager {
    constructor() {
        this._jobs = [];
        this._watchers = [];
        this._editingJobId = null;
        this._editingWatcherId = null;
        this._container = null;
        this._activeSubTab = 'cron';
        this._initialized = false;
    }

    init() {
        this._container = document.getElementById('cron-tab-content');
        if (!this._container) return;
        if (!this._initialized) {
            this._render();
            this._bindForms();
            this._initialized = true;
        }
        this._loadJobs();
        this._loadWatchers();
    }

    // ─── Sub-Tab ─────────────────────────────────────────────────────────

    _switchSubTab(tab) {
        this._activeSubTab = tab;
        ['cron', 'watcher'].forEach(t => {
            const btn = document.getElementById(`trigger-subtab-${t}`);
            const panel = document.getElementById(`trigger-panel-${t}`);
            if (btn) btn.classList.toggle('active', t === tab);
            if (panel) panel.style.display = t === tab ? '' : 'none';
        });
    }

    // ─── Render ──────────────────────────────────────────────────────────

    _render() {
        this._container.innerHTML = `
        <div class="kb-container">

            <!-- Sub-Tab-Leiste -->
            <div style="display:flex;gap:6px;margin-bottom:16px;">
                <button id="trigger-subtab-cron" class="kb-btn-action active">⏰ Cron-Aufgaben</button>
                <button id="trigger-subtab-watcher" class="kb-btn-action" style="background:transparent;border:1px solid var(--border);color:var(--text-secondary);">📁 Datei-Watcher</button>
            </div>

            <!-- Benachrichtigung -->
            <div id="cron-notification" class="kb-notification" style="display:none;"></div>

            <!-- ═══ Panel: Cron ═══ -->
            <div id="trigger-panel-cron">

                <!-- Toolbar -->
                <div class="kb-section">
                    <div class="kb-section-header">
                        <h3>Geplante Aufgaben</h3>
                        <div style="display:flex;gap:6px;">
                            <button id="cron-add-btn" class="kb-btn-action">+ Neue Aufgabe</button>
                            <button id="cron-refresh-btn" class="kb-btn-action" style="background:transparent;border:1px solid var(--border);color:var(--text-secondary);" title="Aktualisieren">🔄</button>
                        </div>
                    </div>
                    <p class="kb-hint">Jarvis führt die angegebene Aufgabe automatisch zum geplanten Zeitpunkt aus.</p>
                </div>

                <!-- Formular -->
                <div id="cron-form-wrap" class="kb-section" style="display:none;">
                    <h3 id="cron-form-title">Neue Aufgabe</h3>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                        <div>
                            <label class="kb-hint" style="display:block;margin-bottom:4px;">Bezeichnung</label>
                            <input id="cron-label" type="text" placeholder="z.B. Täglicher Server-Report" class="kb-input" style="width:100%;box-sizing:border-box;">
                        </div>
                        <div>
                            <label class="kb-hint" style="display:block;margin-bottom:4px;">
                                Zeitplan (Cron)&ensp;<a href="https://crontab.guru" target="_blank" style="color:var(--accent-color);">Hilfe ↗</a>
                            </label>
                            <input id="cron-schedule" type="text" placeholder="0 8 * * *" class="kb-input" style="width:100%;box-sizing:border-box;">
                        </div>
                    </div>
                    <!-- Beispiel-Chips -->
                    <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:10px;">
                        ${[['Täglich 8:00','0 8 * * *'],['Stündlich','0 * * * *'],['Montags 9:00','0 9 * * 1'],['Alle 15 Min','*/15 * * * *'],['1. des Monats','0 0 1 * *']]
                          .map(([l,c]) => `<button class="cron-example-btn" data-cron="${c}" style="font-size:0.73rem;padding:2px 9px;background:var(--bg-glass);border:1px solid var(--border);border-radius:20px;cursor:pointer;color:var(--text-secondary);">${l} <code style="opacity:.7;">${c}</code></button>`).join('')}
                    </div>
                    <div style="margin-bottom:10px;">
                        <label class="kb-hint" style="display:block;margin-bottom:4px;">Aufgabe für Jarvis</label>
                        <textarea id="cron-task" rows="3" placeholder="Was soll Jarvis tun? z.B.: Prüfe Server-Auslastung und sende Zusammenfassung per WhatsApp." class="kb-input" style="width:100%;box-sizing:border-box;resize:vertical;"></textarea>
                    </div>
                    <div style="display:flex;gap:8px;align-items:center;">
                        <label style="display:flex;align-items:center;gap:6px;font-size:0.85rem;cursor:pointer;color:var(--text-secondary);">
                            <input id="cron-enabled" type="checkbox" checked> Aktiv
                        </label>
                        <div style="margin-left:auto;display:flex;gap:6px;">
                            <button id="cron-cancel-btn" class="kb-btn-action" style="background:transparent;border:1px solid var(--border);color:var(--text-secondary);">Abbrechen</button>
                            <button id="cron-save-btn" class="kb-btn-action">Speichern</button>
                        </div>
                    </div>
                    <div id="cron-form-error" style="color:var(--error-color,#e74c3c);font-size:0.8rem;margin-top:8px;display:none;"></div>
                </div>

                <!-- Job-Liste -->
                <div id="cron-list" class="kb-section">
                    <div class="kb-loading">Lade…</div>
                </div>

            </div>

            <!-- ═══ Panel: Datei-Watcher ═══ -->
            <div id="trigger-panel-watcher" style="display:none;">

                <!-- Toolbar -->
                <div class="kb-section">
                    <div class="kb-section-header">
                        <h3>Datei-Watcher</h3>
                        <div style="display:flex;gap:6px;">
                            <button id="watcher-add-btn" class="kb-btn-action">+ Neuer Watcher</button>
                            <button id="watcher-refresh-btn" class="kb-btn-action" style="background:transparent;border:1px solid var(--border);color:var(--text-secondary);" title="Aktualisieren">🔄</button>
                        </div>
                    </div>
                    <p class="kb-hint">Jarvis reagiert automatisch wenn Dateien in einem Ordner erstellt, geändert oder gelöscht werden.</p>
                </div>

                <!-- Watcher-Formular -->
                <div id="watcher-form-wrap" class="kb-section" style="display:none;">
                    <h3 id="watcher-form-title">Neuer Watcher</h3>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                        <div>
                            <label class="kb-hint" style="display:block;margin-bottom:4px;">Bezeichnung</label>
                            <input id="watcher-label" type="text" placeholder="z.B. PDF Inbox" class="kb-input" style="width:100%;box-sizing:border-box;">
                        </div>
                        <div>
                            <label class="kb-hint" style="display:block;margin-bottom:4px;">Ordnerpfad</label>
                            <input id="watcher-path" type="text" placeholder="/home/jarvis/inbox" class="kb-input" style="width:100%;box-sizing:border-box;">
                        </div>
                    </div>
                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                        <div>
                            <label class="kb-hint" style="display:block;margin-bottom:4px;">Datei-Muster</label>
                            <input id="watcher-pattern" type="text" placeholder="*.pdf" class="kb-input" style="width:100%;box-sizing:border-box;">
                        </div>
                        <div>
                            <label class="kb-hint" style="display:block;margin-bottom:4px;">Ereignisse</label>
                            <div style="display:flex;gap:12px;margin-top:6px;">
                                ${['created','modified','deleted','moved'].map(ev =>
                                    `<label style="display:flex;align-items:center;gap:4px;font-size:0.82rem;cursor:pointer;color:var(--text-secondary);">
                                        <input type="checkbox" class="watcher-event-cb" value="${ev}" ${ev==='created'?'checked':''}> ${ev}
                                    </label>`
                                ).join('')}
                            </div>
                        </div>
                    </div>
                    <div style="margin-bottom:10px;">
                        <label class="kb-hint" style="display:block;margin-bottom:4px;">
                            Aufgabe für Jarvis &ensp;<span style="opacity:.6;">Platzhalter: <code>{filename}</code> <code>{filepath}</code></span>
                        </label>
                        <textarea id="watcher-task" rows="3" placeholder="Fasse die neu eingetroffene Datei {filename} zusammen." class="kb-input" style="width:100%;box-sizing:border-box;resize:vertical;"></textarea>
                    </div>
                    <div style="display:flex;gap:8px;align-items:center;">
                        <label style="display:flex;align-items:center;gap:6px;font-size:0.85rem;cursor:pointer;color:var(--text-secondary);">
                            <input id="watcher-enabled" type="checkbox" checked> Aktiv
                        </label>
                        <div style="margin-left:auto;display:flex;gap:6px;">
                            <button id="watcher-cancel-btn" class="kb-btn-action" style="background:transparent;border:1px solid var(--border);color:var(--text-secondary);">Abbrechen</button>
                            <button id="watcher-save-btn" class="kb-btn-action">Speichern</button>
                        </div>
                    </div>
                    <div id="watcher-form-error" style="color:var(--error-color,#e74c3c);font-size:0.8rem;margin-top:8px;display:none;"></div>
                </div>

                <!-- Watcher-Liste -->
                <div id="watcher-list" class="kb-section">
                    <div class="kb-loading">Lade…</div>
                </div>

            </div>
        </div>
        `;

        // Sub-Tab Buttons
        document.getElementById('trigger-subtab-cron').onclick = () => this._switchSubTab('cron');
        document.getElementById('trigger-subtab-watcher').onclick = () => this._switchSubTab('watcher');

        // Cron Beispiel-Chips
        this._container.querySelectorAll('.cron-example-btn').forEach(btn => {
            btn.onclick = () => { document.getElementById('cron-schedule').value = btn.dataset.cron; };
        });

        // Cron Toolbar
        document.getElementById('cron-add-btn').onclick = () => this._showJobForm();
        document.getElementById('cron-refresh-btn').onclick = () => this._loadJobs();
        document.getElementById('cron-cancel-btn').onclick = () => this._hideJobForm();

        // Watcher Toolbar
        document.getElementById('watcher-add-btn').onclick = () => this._showWatcherForm();
        document.getElementById('watcher-refresh-btn').onclick = () => this._loadWatchers();
        document.getElementById('watcher-cancel-btn').onclick = () => this._hideWatcherForm();
    }

    _bindForms() {
        document.getElementById('cron-save-btn').onclick = () => this._saveJob();
        document.getElementById('watcher-save-btn').onclick = () => this._saveWatcher();
    }

    _notify(msg, isError = false) {
        const el = document.getElementById('cron-notification');
        if (!el) return;
        el.textContent = msg;
        el.className = 'kb-notification' + (isError ? ' kb-notification-error' : '');
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 4000);
    }

    // ═══ CRON JOBS ═══════════════════════════════════════════════════════

    async _loadJobs() {
        try {
            const r = await fetch('/api/cron', { headers: _authHeaders() });
            if (!r.ok) return;
            this._jobs = await r.json();
            this._renderJobList();
        } catch (e) { console.error('[Cron] Ladefehler:', e); }
    }

    _renderJobList() {
        const el = document.getElementById('cron-list');
        if (!el) return;
        if (!this._jobs.length) {
            el.innerHTML = `<p class="kb-hint" style="text-align:center;padding:24px 0;">Noch keine geplanten Aufgaben. Klicke <strong>+ Neue Aufgabe</strong> um loszulegen.</p>`;
            return;
        }
        el.innerHTML = this._jobs.map(job => {
            const lastRun = job.last_run ? new Date(job.last_run * 1000).toLocaleString('de-DE') : '—';
            const dot = job.enabled ? 'var(--success-color,#2ecc71)' : 'var(--text-muted)';
            return `
            <div class="kb-folder-item" style="margin-bottom:8px;" data-id="${job.id}">
                <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0;">
                    <div style="width:9px;height:9px;border-radius:50%;background:${dot};flex-shrink:0;"></div>
                    <span style="font-weight:600;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this._esc(job.label)}</span>
                    <code style="font-size:0.78rem;background:var(--bg-glass);padding:2px 7px;border-radius:5px;flex-shrink:0;">${this._esc(job.cron)}</code>
                </div>
                <div style="display:flex;gap:5px;align-items:center;flex-shrink:0;margin-left:8px;">
                    <button class="kb-btn-action cron-run-btn" data-id="${job.id}" style="padding:3px 9px;font-size:0.75rem;" title="Jetzt ausführen">▶</button>
                    <button class="kb-btn-action cron-edit-btn" data-id="${job.id}" style="padding:3px 9px;font-size:0.75rem;background:transparent;border:1px solid var(--border);color:var(--text-secondary);">✏️</button>
                    <button class="kb-btn-action cron-del-btn" data-id="${job.id}" style="padding:3px 9px;font-size:0.75rem;background:rgba(231,76,60,.15);color:#e74c3c;border:none;">🗑️</button>
                    <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:0.8rem;color:var(--text-muted);margin-left:2px;">
                        <input type="checkbox" class="cron-toggle" data-id="${job.id}" ${job.enabled ? 'checked' : ''}>
                    </label>
                </div>
                <div style="width:100%;margin-top:5px;padding-left:19px;font-size:0.8rem;color:var(--text-muted);">
                    ${this._esc(job.task)}
                </div>
                <div style="width:100%;margin-top:3px;padding-left:19px;font-size:0.74rem;color:var(--text-muted);opacity:.7;">
                    Letzter Lauf: ${lastRun}${job.last_result ? ` · ${this._esc(job.last_result.substring(0,70))}${job.last_result.length>70?'…':''}` : ''}
                </div>
            </div>`;
        }).join('');

        el.querySelectorAll('.cron-del-btn').forEach(btn => { btn.onclick = () => this._deleteJob(btn.dataset.id); });
        el.querySelectorAll('.cron-edit-btn').forEach(btn => { btn.onclick = () => this._editJob(btn.dataset.id); });
        el.querySelectorAll('.cron-run-btn').forEach(btn => { btn.onclick = () => this._runJobNow(btn.dataset.id, btn); });
        el.querySelectorAll('.cron-toggle').forEach(cb => { cb.onchange = () => this._toggleJob(cb.dataset.id, cb.checked); });
    }

    _showJobForm(job = null) {
        this._editingJobId = job ? job.id : null;
        document.getElementById('cron-form-title').textContent = job ? 'Aufgabe bearbeiten' : 'Neue Aufgabe';
        document.getElementById('cron-label').value = job ? job.label : '';
        document.getElementById('cron-schedule').value = job ? job.cron : '';
        document.getElementById('cron-task').value = job ? job.task : '';
        document.getElementById('cron-enabled').checked = job ? job.enabled : true;
        document.getElementById('cron-form-error').style.display = 'none';
        document.getElementById('cron-form-wrap').style.display = '';
        document.getElementById('cron-label').focus();
    }

    _hideJobForm() {
        this._editingJobId = null;
        document.getElementById('cron-form-wrap').style.display = 'none';
    }

    _editJob(id) {
        const job = this._jobs.find(j => j.id === id);
        if (job) this._showJobForm(job);
    }

    async _saveJob() {
        const label = document.getElementById('cron-label').value.trim();
        const cron  = document.getElementById('cron-schedule').value.trim();
        const task  = document.getElementById('cron-task').value.trim();
        const enabled = document.getElementById('cron-enabled').checked;
        const errEl = document.getElementById('cron-form-error');
        if (!label || !cron || !task) { errEl.textContent = 'Bitte alle Felder ausfüllen.'; errEl.style.display = 'block'; return; }
        errEl.style.display = 'none';
        try {
            const method = this._editingJobId ? 'PUT' : 'POST';
            const url = this._editingJobId ? `/api/cron/${this._editingJobId}` : '/api/cron';
            const r = await fetch(url, { method, headers: { ..._authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ label, cron, task, enabled }) });
            if (!r.ok) { const e = await r.json().catch(() => ({})); errEl.textContent = e.detail || 'Fehler'; errEl.style.display = 'block'; return; }
            this._hideJobForm();
            this._loadJobs();
            this._notify('✅ Aufgabe gespeichert');
        } catch (e) { errEl.textContent = 'Netzwerkfehler: ' + e.message; errEl.style.display = 'block'; }
    }

    async _deleteJob(id) {
        if (!confirm('Aufgabe wirklich löschen?')) return;
        await fetch(`/api/cron/${id}`, { method: 'DELETE', headers: _authHeaders() });
        this._loadJobs();
    }

    async _toggleJob(id, enabled) {
        await fetch(`/api/cron/${id}`, { method: 'PUT', headers: { ..._authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
        this._loadJobs();
    }

    async _runJobNow(id, btn) {
        const orig = btn.textContent;
        btn.textContent = '⏳'; btn.disabled = true;
        try {
            await fetch(`/api/cron/${id}/run`, { method: 'POST', headers: _authHeaders() });
            btn.textContent = '✅';
            setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
            this._loadJobs();
        } catch { btn.textContent = '❌'; setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000); }
    }

    // ═══ DATEI-WATCHER ═══════════════════════════════════════════════════

    async _loadWatchers() {
        try {
            const r = await fetch('/api/watchers', { headers: _authHeaders() });
            if (!r.ok) return;
            this._watchers = await r.json();
            this._renderWatcherList();
        } catch (e) { console.error('[Watcher] Ladefehler:', e); }
    }

    _renderWatcherList() {
        const el = document.getElementById('watcher-list');
        if (!el) return;
        if (!this._watchers.length) {
            el.innerHTML = `<p class="kb-hint" style="text-align:center;padding:24px 0;">Noch keine Datei-Watcher. Klicke <strong>+ Neuer Watcher</strong> um loszulegen.</p>`;
            return;
        }
        el.innerHTML = this._watchers.map(w => {
            const lastTrig = w.last_triggered ? new Date(w.last_triggered * 1000).toLocaleString('de-DE') : '—';
            const dot = w.enabled ? 'var(--success-color,#2ecc71)' : 'var(--text-muted)';
            const evBadges = (w.events || []).map(ev => `<span style="font-size:0.7rem;background:var(--bg-glass);padding:1px 5px;border-radius:4px;margin-right:3px;">${ev}</span>`).join('');
            return `
            <div class="kb-folder-item" style="margin-bottom:8px;" data-id="${w.id}">
                <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0;">
                    <div style="width:9px;height:9px;border-radius:50%;background:${dot};flex-shrink:0;"></div>
                    <span style="font-weight:600;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${this._esc(w.label)}</span>
                    <code style="font-size:0.78rem;background:var(--bg-glass);padding:2px 7px;border-radius:5px;flex-shrink:0;">${this._esc(w.pattern||'*')}</code>
                    <span>${evBadges}</span>
                </div>
                <div style="display:flex;gap:5px;align-items:center;flex-shrink:0;margin-left:8px;">
                    <button class="kb-btn-action watcher-edit-btn" data-id="${w.id}" style="padding:3px 9px;font-size:0.75rem;background:transparent;border:1px solid var(--border);color:var(--text-secondary);">✏️</button>
                    <button class="kb-btn-action watcher-del-btn" data-id="${w.id}" style="padding:3px 9px;font-size:0.75rem;background:rgba(231,76,60,.15);color:#e74c3c;border:none;">🗑️</button>
                    <label style="display:flex;align-items:center;gap:4px;cursor:pointer;font-size:0.8rem;color:var(--text-muted);margin-left:2px;">
                        <input type="checkbox" class="watcher-toggle" data-id="${w.id}" ${w.enabled ? 'checked' : ''}>
                    </label>
                </div>
                <div style="width:100%;margin-top:5px;padding-left:19px;font-size:0.78rem;color:var(--text-muted);">
                    📂 ${this._esc(w.path)}
                </div>
                <div style="width:100%;margin-top:3px;padding-left:19px;font-size:0.8rem;color:var(--text-muted);">${this._esc(w.task)}</div>
                <div style="width:100%;margin-top:3px;padding-left:19px;font-size:0.74rem;color:var(--text-muted);opacity:.7;">
                    Letzter Trigger: ${lastTrig}${w.last_result ? ` · ${this._esc(w.last_result.substring(0,70))}${w.last_result.length>70?'…':''}` : ''}
                </div>
            </div>`;
        }).join('');

        el.querySelectorAll('.watcher-del-btn').forEach(btn => { btn.onclick = () => this._deleteWatcher(btn.dataset.id); });
        el.querySelectorAll('.watcher-edit-btn').forEach(btn => { btn.onclick = () => this._editWatcher(btn.dataset.id); });
        el.querySelectorAll('.watcher-toggle').forEach(cb => { cb.onchange = () => this._toggleWatcher(cb.dataset.id, cb.checked); });
    }

    _showWatcherForm(w = null) {
        this._editingWatcherId = w ? w.id : null;
        document.getElementById('watcher-form-title').textContent = w ? 'Watcher bearbeiten' : 'Neuer Watcher';
        document.getElementById('watcher-label').value = w ? w.label : '';
        document.getElementById('watcher-path').value = w ? w.path : '';
        document.getElementById('watcher-pattern').value = w ? (w.pattern || '*') : '*.pdf';
        document.getElementById('watcher-task').value = w ? w.task : '';
        document.getElementById('watcher-enabled').checked = w ? w.enabled : true;
        document.querySelectorAll('.watcher-event-cb').forEach(cb => {
            cb.checked = w ? (w.events || ['created']).includes(cb.value) : cb.value === 'created';
        });
        document.getElementById('watcher-form-error').style.display = 'none';
        document.getElementById('watcher-form-wrap').style.display = '';
        document.getElementById('watcher-label').focus();
    }

    _hideWatcherForm() {
        this._editingWatcherId = null;
        document.getElementById('watcher-form-wrap').style.display = 'none';
    }

    _editWatcher(id) {
        const w = this._watchers.find(x => x.id === id);
        if (w) this._showWatcherForm(w);
    }

    async _saveWatcher() {
        const label   = document.getElementById('watcher-label').value.trim();
        const path    = document.getElementById('watcher-path').value.trim();
        const pattern = document.getElementById('watcher-pattern').value.trim() || '*';
        const task    = document.getElementById('watcher-task').value.trim();
        const enabled = document.getElementById('watcher-enabled').checked;
        const events  = [...document.querySelectorAll('.watcher-event-cb:checked')].map(cb => cb.value);
        const errEl   = document.getElementById('watcher-form-error');
        if (!label || !path || !task) { errEl.textContent = 'Bitte Bezeichnung, Pfad und Aufgabe ausfüllen.'; errEl.style.display = 'block'; return; }
        if (!events.length) { errEl.textContent = 'Mindestens ein Ereignis auswählen.'; errEl.style.display = 'block'; return; }
        errEl.style.display = 'none';
        try {
            const method = this._editingWatcherId ? 'PUT' : 'POST';
            const url = this._editingWatcherId ? `/api/watchers/${this._editingWatcherId}` : '/api/watchers';
            const r = await fetch(url, { method, headers: { ..._authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ label, path, pattern, events, task, enabled }) });
            if (!r.ok) { const e = await r.json().catch(() => ({})); errEl.textContent = e.detail || 'Fehler'; errEl.style.display = 'block'; return; }
            this._hideWatcherForm();
            this._loadWatchers();
            this._notify('✅ Watcher gespeichert');
        } catch (e) { errEl.textContent = 'Netzwerkfehler: ' + e.message; errEl.style.display = 'block'; }
    }

    async _deleteWatcher(id) {
        if (!confirm('Watcher wirklich löschen?')) return;
        await fetch(`/api/watchers/${id}`, { method: 'DELETE', headers: _authHeaders() });
        this._loadWatchers();
    }

    async _toggleWatcher(id, enabled) {
        await fetch(`/api/watchers/${id}`, { method: 'PUT', headers: { ..._authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) });
        this._loadWatchers();
    }

    // ─── WebSocket-Events ─────────────────────────────────────────────────

    handleWsEvent(msg) {
        if (msg.type === 'cron_event' && msg.event === 'finished') this._loadJobs();
        else if (msg.type === 'watcher_event' && msg.event === 'finished') this._loadWatchers();
    }

    _esc(str) {
        return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
})();
