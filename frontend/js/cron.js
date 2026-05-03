/**
 * Jarvis Trigger-UI  (Cron-Jobs + Datei-Watcher)
 * Design: kb-container / kb-section System  (wie Wissen- und Skills-Tab)
 */
function _authHeaders() {
    return { 'Authorization': 'Bearer ' + (window.authToken || localStorage.getItem('jarvis_token') || '') };
}

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

    // ─── Render ──────────────────────────────────────────────────────────

    _render() {
        this._container.innerHTML = `
        <div class="kb-container">

            <!-- Benachrichtigung -->
            <div id="cron-notification" class="kb-notification" style="display:none;"></div>

            <!-- ═══ Sektion: Cron-Aufgaben ═══ -->
            <div class="kb-section">
                <div class="kb-section-header kb-collapse-header" id="cron-sect-jobs-hdr">
                    <h3>Cron-Aufgaben</h3>
                    <span class="sk-openclaw-toggle" id="cron-sect-jobs-tog">▶</span>
                </div>
                <div id="cron-sect-jobs-body" style="display:none;">
                    <p class="kb-hint" style="margin-top:6px;">Jarvis führt die angegebene Aufgabe automatisch zum geplanten Zeitpunkt aus.</p>
                    <div style="display:flex;gap:6px;margin:8px 0 10px;">
                        <button id="cron-add-btn"     class="kb-btn-action">+ Neue Aufgabe</button>
                        <button id="cron-refresh-btn" class="kb-btn-secondary" title="Aktualisieren">🔄</button>
                    </div>

                    <!-- Formular -->
                    <div id="cron-form-wrap" style="display:none;margin:10px 0;padding:14px 16px;background:rgba(255,255,255,0.03);border:1px solid var(--border-color);border-radius:8px;">
                        <h3 id="cron-form-title" style="margin:0 0 12px;font-size:.9rem;">Neue Aufgabe</h3>

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
                                <small id="cron-schedule-preview" style="display:block;margin-top:4px;font-size:.75rem;opacity:.6;min-height:1em;"></small>
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
                    <div id="cron-list">
                        <p class="kb-loading">Lade…</p>
                    </div>
                </div>
            </div>

            <!-- ═══ Sektion: Datei-Watcher ═══ -->
            <div class="kb-section">
                <div class="kb-section-header kb-collapse-header" id="cron-sect-watch-hdr">
                    <h3>Datei-Watcher</h3>
                    <span class="sk-openclaw-toggle" id="cron-sect-watch-tog">▶</span>
                </div>
                <div id="cron-sect-watch-body" style="display:none;">
                    <p class="kb-hint" style="margin-top:6px;">Jarvis reagiert automatisch, wenn Dateien in einem Ordner erstellt, geändert oder gelöscht werden.</p>
                    <div style="display:flex;gap:6px;margin:8px 0 10px;">
                        <button id="watcher-add-btn"     class="kb-btn-action">+ Neuer Watcher</button>
                        <button id="watcher-refresh-btn" class="kb-btn-secondary" title="Aktualisieren">🔄</button>
                    </div>

                    <!-- Watcher-Formular -->
                    <div id="watcher-form-wrap" style="display:none;margin:10px 0;padding:14px 16px;background:rgba(255,255,255,0.03);border:1px solid var(--border-color);border-radius:8px;">
                        <h3 id="watcher-form-title" style="margin:0 0 12px;font-size:.9rem;">Neuer Watcher</h3>

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
                    <div id="watcher-list">
                        <p class="kb-loading">Lade…</p>
                    </div>
                </div>
            </div>

        </div><!-- /kb-container -->
        `;

        // Collapse-Logik für beide Sektionen
        this._bindCollapse('cron-sect-jobs-hdr',   'cron-sect-jobs-body',   'cron-sect-jobs-tog');
        this._bindCollapse('cron-sect-watch-hdr',  'cron-sect-watch-body',  'cron-sect-watch-tog');

        // Cron Beispiel-Chips
        this._container.querySelectorAll('.cron-example-btn').forEach(btn => {
            btn.onclick = () => {
                const inp = document.getElementById('cron-schedule');
                inp.value = btn.dataset.cron;
                inp.dispatchEvent(new Event('input'));
            };
        });

        // Live-Preview im Formular
        document.getElementById('cron-schedule').addEventListener('input', e => {
            const prev = document.getElementById('cron-schedule-preview');
            if (prev) prev.textContent = this._cronToText(e.target.value);
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

    // ─── Collapse-Helper ─────────────────────────────────────────────────
    _bindCollapse(hdrId, bodyId, togId) {
        const hdr = document.getElementById(hdrId);
        if (!hdr || hdr._crBound) return;
        hdr._crBound = true;
        hdr.addEventListener('click', e => {
            if (e.target.closest('button, input, label')) return;
            const body = document.getElementById(bodyId);
            const tog  = document.getElementById(togId);
            const collapsed = body.style.display !== 'none';
            body.style.display = collapsed ? 'none' : '';
            if (tog) tog.textContent = collapsed ? '▶' : '▼';
            hdr.classList.toggle('is-collapsed', collapsed);
        });
    }

    // Sektion aufklappen (z.B. wenn "+ Neue Aufgabe" geklickt)
    _expandSection(bodyId, togId, hdrId) {
        const body = document.getElementById(bodyId);
        const tog  = document.getElementById(togId);
        const hdr  = document.getElementById(hdrId);
        if (body && body.style.display === 'none') {
            body.style.display = '';
            if (tog) tog.textContent = '▼';
            if (hdr) hdr.classList.remove('is-collapsed');
        }
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
        const el = document.getElementById('cron-list');
        try {
            const r = await fetch('/api/cron', { headers: _authHeaders() });
            if (!r.ok) {
                if (el) el.innerHTML = `<p class="kb-empty" style="color:var(--error,#f87171);">Fehler beim Laden (${r.status}). Bitte Seite neu laden.</p>`;
                return;
            }
            let data;
            try {
                data = await r.json();
            } catch (jsonErr) {
                if (el) el.innerHTML = `<p class="kb-empty" style="color:var(--error,#f87171);">JSON-Fehler: ${jsonErr.message}</p>`;
                return;
            }
            this._jobs = data;
            try {
                this._renderJobList();
            } catch (renderErr) {
                console.error('[Cron] Render-Fehler:', renderErr);
                if (el) el.innerHTML = `<p class="kb-empty" style="color:var(--error,#f87171);">Render-Fehler: ${renderErr.message}</p>`;
            }
        } catch (e) {
            console.error('[Cron] Ladefehler:', e);
            if (el) el.innerHTML = `<p class="kb-empty" style="color:var(--error,#f87171);">Fehler: ${e.message || e} (${e.name || 'unknown'})</p>`;
        }
    }

    _renderJobList() {
        const el = document.getElementById('cron-list');
        if (!el) return;
        if (!this._jobs.length) {
            el.innerHTML = `<p class="kb-empty" style="text-align:center;padding:16px 0;">Noch keine geplanten Aufgaben. Klicke <strong>+ Neue Aufgabe</strong> um loszulegen.</p>`;
            return;
        }
        el.innerHTML = `<div class="kb-folder-list">${this._jobs.map(job => {
            const lastRun  = job.last_run ? new Date(job.last_run * 1000).toLocaleString('de-DE') : '—';
            const dotCls   = job.enabled ? 'active' : 'inactive';
            const onceBadge = job.once ? `<span style="font-size:.7rem;background:var(--accent-muted,rgba(99,102,241,.2));color:var(--accent);border-radius:4px;padding:1px 6px;margin-left:4px;">einmalig</span>` : '';
            return `
            <div class="cron-item" data-id="${job.id}">
                <div class="cron-item-row">
                    <span class="cron-item-dot ${dotCls}"></span>
                    <span class="cron-item-label">${this._esc(job.label)}${onceBadge}</span>
                    <code  class="cron-item-code" data-tip="${this._esc(this._cronToText(job.cron))}">${this._esc(job.cron)}</code>
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
        this._expandSection('cron-sect-jobs-body', 'cron-sect-jobs-tog', 'cron-sect-jobs-hdr');
        this._editingJobId = job ? job.id : null;
        document.getElementById('cron-form-title').textContent  = job ? 'Aufgabe bearbeiten' : 'Neue Aufgabe';
        document.getElementById('cron-label').value    = job ? job.label : '';
        document.getElementById('cron-schedule').value = job ? job.cron  : '';
        document.getElementById('cron-task').value     = job ? job.task  : '';
        document.getElementById('cron-enabled').checked = job ? job.enabled : true;
        document.getElementById('cron-form-error').style.display = 'none';
        document.getElementById('cron-form-wrap').style.display  = '';
        // Live-Preview aktualisieren
        const prev = document.getElementById('cron-schedule-preview');
        if (prev) prev.textContent = job ? this._cronToText(job.cron) : '';
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
        this._expandSection('cron-sect-watch-body', 'cron-sect-watch-tog', 'cron-sect-watch-hdr');
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

    // ─── Cron → deutschen Satz ─────────────────────────────────────────────
    _cronToText(expr) {
        if (!expr) return '';
        const e = expr.trim();

        // Sonderfälle
        if (e === '@reboot')  return 'Beim Systemstart';
        if (e === '@yearly' || e === '@annually') return 'Einmal im Jahr (1. Januar, 00:00 Uhr)';
        if (e === '@monthly') return 'Einmal im Monat (1., 00:00 Uhr)';
        if (e === '@weekly')  return 'Einmal pro Woche (Sonntag, 00:00 Uhr)';
        if (e === '@daily' || e === '@midnight') return 'Täglich um 00:00 Uhr';
        if (e === '@hourly')  return 'Jede Stunde';

        const parts = e.split(/\s+/);
        if (parts.length !== 5) return '';
        const [minF, hourF, domF, monF, dowF] = parts;

        const DAYS   = ['Sonntag','Montag','Dienstag','Mittwoch','Donnerstag','Freitag','Samstag'];
        const MONTHS = ['Januar','Februar','März','April','Mai','Juni','Juli','August',
                        'September','Oktober','November','Dezember'];

        const pad2   = n => String(n).padStart(2, '0');
        const num    = f => parseInt(f, 10);
        const isAny  = f => f === '*';
        const isStep = f => /^\*\/\d+$/.test(f);
        const step   = f => parseInt(f.slice(2));
        const isList = f => f.includes(',') && !f.includes('/');
        const isRng  = f => /^\d+-\d+$/.test(f);
        const isNum  = f => /^\d+$/.test(f);

        // --- Frequenz-Schnellpfade ---
        if (isAny(minF) && isAny(hourF) && isAny(domF) && isAny(monF) && isAny(dowF))
            return 'Jede Minute';
        if (isStep(minF) && isAny(hourF) && isAny(domF) && isAny(monF) && isAny(dowF)) {
            const s = step(minF);
            return s === 1 ? 'Jede Minute' : `Alle ${s} Minuten`;
        }
        if (isNum(minF) && isAny(hourF) && isAny(domF) && isAny(monF) && isAny(dowF))
            return num(minF) === 0 ? 'Jede Stunde' : `Jede Stunde, Minute ${num(minF)}`;
        if (isStep(hourF) && isAny(domF) && isAny(monF) && isAny(dowF)) {
            const s = step(hourF);
            const t = isNum(minF) ? `, Minute ${num(minF)}` : '';
            return (s === 1 ? 'Jede Stunde' : `Alle ${s} Stunden`) + t;
        }
        if (isStep(minF) && isNum(hourF))
            return `Alle ${step(minF)} Minuten, ${pad2(num(hourF))}:00–${pad2(num(hourF))}:59 Uhr`;

        // --- Zeit ---
        let timeStr = '';
        if (isNum(hourF) && isNum(minF))
            timeStr = `um ${pad2(num(hourF))}:${pad2(num(minF))} Uhr`;
        else if (isNum(hourF) && isAny(minF))
            timeStr = `ab ${pad2(num(hourF))}:00 Uhr (jede Minute)`;

        // --- Wochentag ---
        let dowStr = '';
        if (!isAny(dowF)) {
            if (isNum(dowF)) {
                dowStr = `jeden ${DAYS[num(dowF) % 7]}`;
            } else if (isRng(dowF)) {
                const [a, b] = dowF.split('-').map(Number);
                dowStr = `${DAYS[a % 7]} bis ${DAYS[b % 7]}`;
            } else if (isList(dowF)) {
                const ds = dowF.split(',').map(v => DAYS[Number(v) % 7]);
                const last = ds.pop();
                dowStr = (ds.length ? ds.join(', ') + ' und ' : '') + last;
            }
        }

        // --- Tag / Monat ---
        let dateStr = '';
        if (isAny(dowF)) {
            const hasD = !isAny(domF) && isNum(domF);
            const hasM = !isAny(monF) && isNum(monF);
            if (hasD && hasM)       dateStr = `am ${num(domF)}. ${MONTHS[num(monF) - 1]}`;
            else if (hasD)          dateStr = `am ${num(domF)}. jeden Monats`;
            else if (hasM)          dateStr = `im ${MONTHS[num(monF) - 1]}`;
        }

        // --- Zusammensetzen ---
        const when = dowStr || dateStr;
        if (when && timeStr) {
            const w = when.charAt(0).toUpperCase() + when.slice(1);
            return `${w} ${timeStr}`;
        }
        if (when) return when.charAt(0).toUpperCase() + when.slice(1);
        if (timeStr && isAny(domF) && isAny(monF) && isAny(dowF))
            return `Täglich ${timeStr}`;
        if (timeStr) return timeStr.charAt(0).toUpperCase() + timeStr.slice(1);

        return ''; // kein passendes Muster
    }
})();
