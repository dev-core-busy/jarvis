/**
 * Jarvis Trigger-UI  (Cron-Jobs + Datei-Watcher)
 * Design: kb-container / kb-section System  (wie Wissen- und Skills-Tab)
 */
window.cronManager = new (class JarvisCronManager {
    constructor() {
        this._jobs     = [];
        this._watchers = [];
        this._editingJobId     = null;
        this._editingWatcherId = null;
        this._container   = null;
        this._activeSubTab = 'cron';
        this._initialized  = false;
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
            const btn   = document.getElementById(`trigger-subtab-${t}`);
            const panel = document.getElementById(`trigger-panel-${t}`);
            if (btn)   btn.classList.toggle('active', t === tab);
            if (panel) panel.style.display = t === tab ? '' : 'none';
        });
    }

    // ─── Render ──────────────────────────────────────────────────────────

    _render() {
        this._container.innerHTML = `
        <div class="kb-container">

            <!-- Sub-Tab-Leiste -->
            <div class="kb-toggle-group" style="align-self:flex-start;">
                <button id="trigger-subtab-cron"    class="kb-toggle-btn active">⏰ Cron-Aufgaben</button>
                <button id="trigger-subtab-watcher" class="kb-toggle-btn">📁 Datei-Watcher</button>
            </div>

            <!-- Benachrichtigung -->
            <div id="cron-notification" class="kb-notification" style="display:none;"></div>

            <!-- ═══ Panel: Cron ═══ -->
            <div id="trigger-panel-cron">

                <!-- Header-Sektion -->
                <div class="kb-section">
                    <div class="kb-section-header">
                        <h3>Geplante Aufgaben</h3>
                        <div style="display:flex;gap:6px;">
                            <button id="cron-add-btn"     class="kb-btn-action">+ Neue Aufgabe</button>
                            <button id="cron-refresh-btn" class="kb-btn-secondary" title="Aktualisieren">🔄</button>
                        </div>
                    </div>
                    <p class="kb-hint">Jarvis führt die angegebene Aufgabe automatisch zum geplanten Zeitpunkt aus.</p>
                </div>

                <!-- Formular -->
                <div id="cron-form-wrap" class="kb-section" style="display:none;">
                    <h3 id="cron-form-title">Neue Aufgabe</h3>

                    <div class="kb-form-grid-2">
                        <div class="kb-form-field">
                            <label class="kb-label" for="cron-label">Bezeichnung</label>
                            <input id="cron-label" type="text" placeholder="z.B. Täglicher Server-Report" class="kb-input">
                        </div>
                        <div class="kb-form-field">
                            <label class="kb-label" for="cron-schedule">
                                Zeitplan (Cron) &ensp;<a href="https://crontab.guru" target="_blank" style="color:var(--accent);">Hilfe ↗</a>
                            </label>
                            <input id="cron-schedule" type="text" placeholder="0 8 * * *" class="kb-input">
                        </div>
                    </div>

                    <!-- Beispiel-Chips -->
                    <div class="kb-chip-row">
                        ${[['Täglich 8:00','0 8 * * *'],['Stündlich','0 * * * *'],['Montags 9:00','0 9 * * 1'],['Alle 15 Min','*/15 * * * *'],['1. des Monats','0 0 1 * *']]
                          .map(([l,c]) => `<button class="kb-chip cron-example-btn" data-cron="${c}">${l} <code>${c}</code></button>`).join('')}
                    </div>

                    <div class="kb-form-row">
                        <label class="kb-label" for="cron-task">Aufgabe für Jarvis</label>
                        <textarea id="cron-task" rows="3" class="kb-input"
                            placeholder="Was soll Jarvis tun? z.B.: Prüfe Server-Auslastung und sende Zusammenfassung per WhatsApp."></textarea>
                    </div>

                    <div class="kb-form-footer">
                        <div class="kb-form-footer-left">
                            <label class="kb-form-checkbox-label">
                                <input id="cron-enabled" type="checkbox" checked> Aktiv
                            </label>
                        </div>
                        <div class="kb-form-footer-right">
                            <button id="cron-cancel-btn" class="kb-btn-secondary">Abbrechen</button>
                            <button id="cron-save-btn"   class="kb-btn-action">Speichern</button>
                        </div>
                    </div>
                    <p id="cron-form-error" class="kb-form-error" style="display:none;"></p>
                </div>

                <!-- Job-Liste -->
                <div id="cron-list" class="kb-section">
                    <p class="kb-loading">Lade…</p>
                </div>

            </div><!-- /panel-cron -->

            <!-- ═══ Panel: Datei-Watcher ═══ -->
            <div id="trigger-panel-watcher" style="display:none;">

                <!-- Header-Sektion -->
                <div class="kb-section">
                    <div class="kb-section-header">
                        <h3>Datei-Watcher</h3>
                        <div style="display:flex;gap:6px;">
                            <button id="watcher-add-btn"     class="kb-btn-action">+ Neuer Watcher</button>
                            <button id="watcher-refresh-btn" class="kb-btn-secondary" title="Aktualisieren">🔄</button>
                        </div>
                    </div>
                    <p class="kb-hint">Jarvis reagiert automatisch, wenn Dateien in einem Ordner erstellt, geändert oder gelöscht werden.</p>
                </div>

                <!-- Watcher-Formular -->
                <div id="watcher-form-wrap" class="kb-section" style="display:none;">
                    <h3 id="watcher-form-title">Neuer Watcher</h3>

                    <div class="kb-form-grid-2">
                        <div class="kb-form-field">
                            <label class="kb-label" for="watcher-label">Bezeichnung</label>
                            <input id="watcher-label" type="text" placeholder="z.B. PDF Inbox" class="kb-input">
                        </div>
                        <div class="kb-form-field">
                            <label class="kb-label" for="watcher-path">Ordnerpfad</label>
                            <input id="watcher-path" type="text" placeholder="/home/jarvis/inbox" class="kb-input">
                        </div>
                    </div>

                    <div class="kb-form-grid-2">
                        <div class="kb-form-field">
                            <label class="kb-label" for="watcher-pattern">Datei-Muster</label>
                            <input id="watcher-pattern" type="text" placeholder="*.pdf" class="kb-input">
                        </div>
                        <div class="kb-form-field">
                            <label class="kb-label">Ereignisse</label>
                            <div style="display:flex;gap:12px;padding-top:4px;">
                                ${['created','modified','deleted','moved'].map(ev =>
                                    `<label class="kb-form-checkbox-label">
                                        <input type="checkbox" class="watcher-event-cb" value="${ev}" ${ev==='created'?'checked':''}> ${ev}
                                    </label>`
                                ).join('')}
                            </div>
                        </div>
                    </div>

                    <div class="kb-form-row">
                        <label class="kb-label" for="watcher-task">
                            Aufgabe für Jarvis &ensp;<span style="opacity:.6;font-size:.75rem;">Platzhalter: <code class="kb-hint" style="margin:0;">&#123;filename&#125;</code> <code class="kb-hint" style="margin:0;">&#123;filepath&#125;</code></span>
                        </label>
                        <textarea id="watcher-task" rows="3" class="kb-input"
                            placeholder="Fasse die neu eingetroffene Datei {filename} zusammen."></textarea>
                    </div>

                    <div class="kb-form-footer">
                        <div class="kb-form-footer-left">
                            <label class="kb-form-checkbox-label">
                                <input id="watcher-enabled" type="checkbox" checked> Aktiv
                            </label>
                        </div>
                        <div class="kb-form-footer-right">
                            <button id="watcher-cancel-btn" class="kb-btn-secondary">Abbrechen</button>
                            <button id="watcher-save-btn"   class="kb-btn-action">Speichern</button>
                        </div>
                    </div>
                    <p id="watcher-form-error" class="kb-form-error" style="display:none;"></p>
                </div>

                <!-- Watcher-Liste -->
                <div id="watcher-list" class="kb-section">
                    <p class="kb-loading">Lade…</p>
                </div>

            </div><!-- /panel-watcher -->

        </div><!-- /kb-container -->
        `;

        // Sub-Tab Buttons
        document.getElementById('trigger-subtab-cron').onclick    = () => this._switchSubTab('cron');
        document.getElementById('trigger-subtab-watcher').onclick = () => this._switchSubTab('watcher');

        // Cron Beispiel-Chips
        this._container.querySelectorAll('.cron-example-btn').forEach(btn => {
            btn.onclick = () => { document.getElementById('cron-schedule').value = btn.dataset.cron; };
        });

        // Cron Toolbar
        document.getElementById('cron-add-btn').onclick     = () => this._showJobForm();
        document.getElementById('cron-refresh-btn').onclick = () => this._loadJobs();
        document.getElementById('cron-cancel-btn').onclick  = () => this._hideJobForm();

        // Watcher Toolbar
        document.getElementById('watcher-add-btn').onclick     = () => this._showWatcherForm();
        document.getElementById('watcher-refresh-btn').onclick = () => this._loadWatchers();
        document.getElementById('watcher-cancel-btn').onclick  = () => this._hideWatcherForm();
    }

    _bindForms() {
        document.getElementById('cron-save-btn').onclick    = () => this._saveJob();
        document.getElementById('watcher-save-btn').onclick = () => this._saveWatcher();
    }

    _notify(msg, type = 'success') {
        const el = document.getElementById('cron-notification');
        if (!el) return;
        el.textContent = msg;
        el.className = `kb-notification kb-notification-${type}`;
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
            el.innerHTML = `<p class="kb-empty" style="text-align:center;padding:16px 0;">Noch keine geplanten Aufgaben. Klicke <strong>+ Neue Aufgabe</strong> um loszulegen.</p>`;
            return;
        }
        el.innerHTML = `<div class="kb-folder-list">${this._jobs.map(job => {
            const lastRun = job.last_run ? new Date(job.last_run * 1000).toLocaleString('de-DE') : '—';
            const dotCls  = job.enabled ? 'active' : 'inactive';
            return `
            <div class="cron-item" data-id="${job.id}">
                <div class="cron-item-row">
                    <span class="cron-item-dot ${dotCls}"></span>
                    <span class="cron-item-label">${this._esc(job.label)}</span>
                    <code  class="cron-item-code">${this._esc(job.cron)}</code>
                    <div   class="cron-item-actions">
                        <button class="kb-btn-run  cron-run-btn"  data-id="${job.id}" title="Jetzt ausführen">▶</button>
                        <button class="kb-btn-icon cron-edit-btn" data-id="${job.id}" title="Bearbeiten">✏️</button>
                        <button class="kb-btn-danger cron-del-btn" data-id="${job.id}" title="Löschen">🗑️</button>
                        <label class="kb-form-checkbox-label" style="margin-left:4px;" title="${job.enabled ? 'Aktiv' : 'Inaktiv'}">
                            <input type="checkbox" class="cron-toggle" data-id="${job.id}" ${job.enabled ? 'checked' : ''}>
                        </label>
                    </div>
                </div>
                <div class="cron-item-task">${this._esc(job.task)}</div>
                <div class="cron-item-meta">Letzter Lauf: ${lastRun}${job.last_result ? ` · ${this._esc(job.last_result.substring(0,80))}${job.last_result.length>80?'…':''}` : ''}</div>
            </div>`;
        }).join('')}</div>`;

        el.querySelectorAll('.cron-del-btn').forEach(btn => { btn.onclick = () => this._deleteJob(btn.dataset.id); });
        el.querySelectorAll('.cron-edit-btn').forEach(btn => { btn.onclick = () => this._editJob(btn.dataset.id); });
        el.querySelectorAll('.cron-run-btn').forEach(btn  => { btn.onclick = () => this._runJobNow(btn.dataset.id, btn); });
        el.querySelectorAll('.cron-toggle').forEach(cb    => { cb.onchange  = () => this._toggleJob(cb.dataset.id, cb.checked); });
    }

    _showJobForm(job = null) {
        this._editingJobId = job ? job.id : null;
        document.getElementById('cron-form-title').textContent  = job ? 'Aufgabe bearbeiten' : 'Neue Aufgabe';
        document.getElementById('cron-label').value    = job ? job.label : '';
        document.getElementById('cron-schedule').value = job ? job.cron  : '';
        document.getElementById('cron-task').value     = job ? job.task  : '';
        document.getElementById('cron-enabled').checked = job ? job.enabled : true;
        document.getElementById('cron-form-error').style.display = 'none';
        document.getElementById('cron-form-wrap').style.display  = '';
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
        const label   = document.getElementById('cron-label').value.trim();
        const cron    = document.getElementById('cron-schedule').value.trim();
        const task    = document.getElementById('cron-task').value.trim();
        const enabled = document.getElementById('cron-enabled').checked;
        const errEl   = document.getElementById('cron-form-error');
        if (!label || !cron || !task) {
            errEl.textContent  = 'Bitte alle Felder ausfüllen.';
            errEl.style.display = 'block';
            return;
        }
        errEl.style.display = 'none';
        try {
            const method = this._editingJobId ? 'PUT' : 'POST';
            const url    = this._editingJobId ? `/api/cron/${this._editingJobId}` : '/api/cron';
            const r = await fetch(url, {
                method,
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ label, cron, task, enabled })
            });
            if (!r.ok) {
                const e = await r.json().catch(() => ({}));
                errEl.textContent = e.detail || 'Fehler';
                errEl.style.display = 'block';
                return;
            }
            this._hideJobForm();
            this._loadJobs();
            this._notify('✅ Aufgabe gespeichert');
        } catch (e) {
            errEl.textContent = 'Netzwerkfehler: ' + e.message;
            errEl.style.display = 'block';
        }
    }

    async _deleteJob(id) {
        if (!confirm('Aufgabe wirklich löschen?')) return;
        await fetch(`/api/cron/${id}`, { method: 'DELETE', headers: _authHeaders() });
        this._loadJobs();
        this._notify('🗑️ Aufgabe gelöscht', 'info');
    }

    async _toggleJob(id, enabled) {
        await fetch(`/api/cron/${id}`, {
            method: 'PUT',
            headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });
        this._loadJobs();
    }

    async _runJobNow(id, btn) {
        const orig = btn.textContent;
        btn.textContent = '⏳';
        btn.disabled = true;
        try {
            await fetch(`/api/cron/${id}/run`, { method: 'POST', headers: _authHeaders() });
            btn.textContent = '✅';
            setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
            this._loadJobs();
        } catch {
            btn.textContent = '❌';
            setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000);
        }
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
            el.innerHTML = `<p class="kb-empty" style="text-align:center;padding:16px 0;">Noch keine Datei-Watcher. Klicke <strong>+ Neuer Watcher</strong> um loszulegen.</p>`;
            return;
        }
        el.innerHTML = `<div class="kb-folder-list">${this._watchers.map(w => {
            const lastTrig  = w.last_triggered ? new Date(w.last_triggered * 1000).toLocaleString('de-DE') : '—';
            const dotCls    = w.enabled ? 'active' : 'inactive';
            const evBadges  = (w.events || []).map(ev => `<span class="cron-event-badge">${ev}</span>`).join('');
            return `
            <div class="cron-item" data-id="${w.id}">
                <div class="cron-item-row">
                    <span class="cron-item-dot ${dotCls}"></span>
                    <span class="cron-item-label">${this._esc(w.label)}</span>
                    <code  class="cron-item-code">${this._esc(w.pattern || '*')}</code>
                    <span style="display:flex;gap:3px;">${evBadges}</span>
                    <div   class="cron-item-actions">
                        <button class="kb-btn-icon   watcher-edit-btn" data-id="${w.id}" title="Bearbeiten">✏️</button>
                        <button class="kb-btn-danger watcher-del-btn"  data-id="${w.id}" title="Löschen">🗑️</button>
                        <label class="kb-form-checkbox-label" style="margin-left:4px;" title="${w.enabled ? 'Aktiv' : 'Inaktiv'}">
                            <input type="checkbox" class="watcher-toggle" data-id="${w.id}" ${w.enabled ? 'checked' : ''}>
                        </label>
                    </div>
                </div>
                <div class="cron-item-path">📂 ${this._esc(w.path)}</div>
                <div class="cron-item-task">${this._esc(w.task)}</div>
                <div class="cron-item-meta">Letzter Trigger: ${lastTrig}${w.last_result ? ` · ${this._esc(w.last_result.substring(0,80))}${w.last_result.length>80?'…':''}` : ''}</div>
            </div>`;
        }).join('')}</div>`;

        el.querySelectorAll('.watcher-del-btn').forEach(btn  => { btn.onclick  = () => this._deleteWatcher(btn.dataset.id); });
        el.querySelectorAll('.watcher-edit-btn').forEach(btn => { btn.onclick  = () => this._editWatcher(btn.dataset.id); });
        el.querySelectorAll('.watcher-toggle').forEach(cb    => { cb.onchange  = () => this._toggleWatcher(cb.dataset.id, cb.checked); });
    }

    _showWatcherForm(w = null) {
        this._editingWatcherId = w ? w.id : null;
        document.getElementById('watcher-form-title').textContent = w ? 'Watcher bearbeiten' : 'Neuer Watcher';
        document.getElementById('watcher-label').value   = w ? w.label : '';
        document.getElementById('watcher-path').value    = w ? w.path  : '';
        document.getElementById('watcher-pattern').value = w ? (w.pattern || '*') : '*.pdf';
        document.getElementById('watcher-task').value    = w ? w.task  : '';
        document.getElementById('watcher-enabled').checked = w ? w.enabled : true;
        document.querySelectorAll('.watcher-event-cb').forEach(cb => {
            cb.checked = w ? (w.events || ['created']).includes(cb.value) : cb.value === 'created';
        });
        document.getElementById('watcher-form-error').style.display = 'none';
        document.getElementById('watcher-form-wrap').style.display  = '';
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

        if (!label || !path || !task) {
            errEl.textContent = 'Bitte Bezeichnung, Pfad und Aufgabe ausfüllen.';
            errEl.style.display = 'block';
            return;
        }
        if (!events.length) {
            errEl.textContent = 'Mindestens ein Ereignis auswählen.';
            errEl.style.display = 'block';
            return;
        }
        errEl.style.display = 'none';
        try {
            const method = this._editingWatcherId ? 'PUT' : 'POST';
            const url    = this._editingWatcherId ? `/api/watchers/${this._editingWatcherId}` : '/api/watchers';
            const r = await fetch(url, {
                method,
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ label, path, pattern, events, task, enabled })
            });
            if (!r.ok) {
                const e = await r.json().catch(() => ({}));
                errEl.textContent = e.detail || 'Fehler';
                errEl.style.display = 'block';
                return;
            }
            this._hideWatcherForm();
            this._loadWatchers();
            this._notify('✅ Watcher gespeichert');
        } catch (e) {
            errEl.textContent = 'Netzwerkfehler: ' + e.message;
            errEl.style.display = 'block';
        }
    }

    async _deleteWatcher(id) {
        if (!confirm('Watcher wirklich löschen?')) return;
        await fetch(`/api/watchers/${id}`, { method: 'DELETE', headers: _authHeaders() });
        this._loadWatchers();
        this._notify('🗑️ Watcher gelöscht', 'info');
    }

    async _toggleWatcher(id, enabled) {
        await fetch(`/api/watchers/${id}`, {
            method: 'PUT',
            headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled })
        });
        this._loadWatchers();
    }

    // ─── WebSocket-Events ─────────────────────────────────────────────────

    handleWsEvent(msg) {
        if      (msg.type === 'cron_event'    && msg.event === 'finished') this._loadJobs();
        else if (msg.type === 'watcher_event' && msg.event === 'finished') this._loadWatchers();
    }

    _esc(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
})();
