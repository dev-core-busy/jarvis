/**
 * Jarvis Trigger-UI  (Cron-Jobs + Datei-Watcher)
 * Design: kb-container / kb-section System  (wie Wissen- und Skills-Tab)
 */
// Datumsformat nach Oberflaechensprache (Code-Review 2026-10-07: fest 'de-DE',
// die englische Oberflaeche zeigte deutsches Format). window.t() kennt keine
// Platzhalter – {e} wird an der Aufrufstelle ersetzt.
function _cronOrt() { return window._lang === 'en' ? 'en-GB' : 'de-DE'; }

function _authHeaders() {
    return { 'Authorization': 'Bearer ' + (window.authToken || window.JarvisSitzung.token()) };
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
        // Auftraege, deren Protokoll aufgeklappt ist. ⚠ Die Liste wird nach
        // JEDEM Lauf neu gezeichnet (cron_event 'finished' -> _loadJobs) - der
        // Wissensabgleich allein alle fuenf Minuten. Ohne diesen Merker klappte
        // ein offenes Protokoll unter der Hand wieder zu.
        this._logOffen = new Set();
        this._logDaten = {};   // job_id -> {eintraege, mehr}
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
                    <h3>${window.t('cron.section_jobs')}</h3>
                    <span class="sk-openclaw-toggle" id="cron-sect-jobs-tog">▶</span>
                </div>
                <div id="cron-sect-jobs-body" style="display:none;">
                    <p class="kb-hint" style="margin-top:6px;">${window.t('cron.jobs_hint')}</p>
                    <div style="display:flex;gap:6px;margin:8px 0 10px;">
                        <button id="cron-add-btn"     class="kb-btn-action">${window.t('cron.add_job_btn')}</button>
                        <button id="cron-refresh-btn" class="kb-btn-secondary" title="Aktualisieren">🔄</button>
                    </div>

                    <!-- Formular -->
                    <div id="cron-form-wrap" style="display:none;margin:10px 0;padding:14px 16px;background:rgba(var(--fg-rgb),0.03);border:1px solid var(--border);border-radius:8px;">
                        <h3 id="cron-form-title" style="margin:0 0 12px;font-size:.9rem;">${window.t('cron.form_title_new')}</h3>

                        <div class="kb-form-grid-2">
                            <div class="kb-form-field">
                                <label class="kb-label" for="cron-label">${window.t('cron.label_label')}</label>
                                <input id="cron-label" type="text" placeholder="z.B. Täglicher Server-Report" class="kb-input">
                            </div>
                            <div class="kb-form-field">
                                <label class="kb-label" for="cron-schedule">
                                    ${window.t('cron.schedule_label')} &ensp;<a href="https://crontab.guru" target="_blank" style="color:var(--accent);">Hilfe ↗</a>
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

                        <!-- Art des Auftrags (seit 2026-10-29). Die Sicherheitslücken-
                             Prüfung läuft OHNE Agent (backend/cve_pruefung.py); die Art
                             ist nach dem Anlegen nicht mehr änderbar. -->
                        <div class="kb-form-row">
                            <label class="kb-label" for="cron-kind">${window.t('cron.kind_label')}</label>
                            <select id="cron-kind" class="kb-input">
                                <option value="agent">${window.t('cron.kind_agent')}</option>
                                <option value="cve_pruefung">${window.t('cron.kind_cve')}</option>
                            </select>
                        </div>

                        <div class="kb-form-row" id="cron-cve-opts" hidden>
                            <label class="kb-form-checkbox-label">
                                <input id="cron-cve-beheben" type="checkbox"> ${window.t('cron.cve_beheben')}
                            </label>
                            <p class="kb-hint" style="margin:2px 0 6px 24px;">${window.t('cron.cve_beheben_hint')}</p>
                            <p class="kb-hint" id="cron-cve-unatt" style="margin:0 0 6px 24px;" hidden>${window.t('cron.cve_unatt_hint')}</p>
                            <label class="kb-label" for="cron-cve-schwelle">${window.t('cron.cve_schwelle')}</label>
                            <select id="cron-cve-schwelle" class="kb-input">
                                <option value="">${window.t('cron.cve_schwelle_vorgabe')}</option>
                                <option value="alle">${window.t('cve.schwelle_alle')}</option>
                                <option value="ab_niedrig">${window.t('cve.schwelle_ab_niedrig')}</option>
                                <option value="ab_mittel">${window.t('cve.schwelle_ab_mittel')}</option>
                            </select>
                        </div>

                        <div class="kb-form-row" id="cron-task-row">
                            <label class="kb-label" for="cron-task">Aufgabe für Jarvis</label>
                            <textarea id="cron-task" rows="3" class="kb-input"
                                placeholder="Was soll Jarvis tun? z.B.: Prüfe Server-Auslastung und sende Zusammenfassung per WhatsApp."></textarea>
                            <label class="kb-form-checkbox-label" style="margin-top:6px;">
                                <input id="cron-aussenwirkung" type="checkbox"> ${window.t('cron.aussenwirkung')}
                            </label>
                            <p class="kb-hint" style="margin:2px 0 0 24px;">${window.t('cron.aussenwirkung_hint')}</p>
                        </div>

                        <div class="kb-form-footer">
                            <div class="kb-form-footer-left">
                                <label class="kb-form-checkbox-label">
                                    <input id="cron-enabled" type="checkbox" checked> ${window.t('common.active')}
                                </label>
                            </div>
                            <div class="kb-form-footer-right">
                                <button id="cron-cancel-btn" class="kb-btn-secondary">${window.t('cron.cancel_btn')}</button>
                                <button id="cron-save-btn"   class="kb-btn-action">${window.t('cron.save_btn')}</button>
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
                    <h3>${window.t('cron.section_watcher')}</h3>
                    <span class="sk-openclaw-toggle" id="cron-sect-watch-tog">▶</span>
                </div>
                <div id="cron-sect-watch-body" style="display:none;">
                    <p class="kb-hint" style="margin-top:6px;">${window.t('cron.watcher_hint')}</p>
                    <div style="display:flex;gap:6px;margin:8px 0 10px;">
                        <button id="watcher-add-btn"     class="kb-btn-action">${window.t('cron.add_watcher_btn')}</button>
                        <button id="watcher-refresh-btn" class="kb-btn-secondary" title="Aktualisieren">🔄</button>
                    </div>

                    <!-- Watcher-Formular -->
                    <div id="watcher-form-wrap" style="display:none;margin:10px 0;padding:14px 16px;background:rgba(var(--fg-rgb),0.03);border:1px solid var(--border);border-radius:8px;">
                        <h3 id="watcher-form-title" style="margin:0 0 12px;font-size:.9rem;">${window.t('cron.form_title_new_watcher')}</h3>

                        <div class="kb-form-grid-2">
                            <div class="kb-form-field">
                                <label class="kb-label" for="watcher-label">${window.t('cron.label_label')}</label>
                                <input id="watcher-label" type="text" placeholder="z.B. PDF Inbox" class="kb-input">
                            </div>
                            <div class="kb-form-field">
                                <label class="kb-label" for="watcher-trigger-type">Trigger (Ereignis)</label>
                                <select id="watcher-trigger-type" class="kb-input">
                                    <option value="file">Datei-Ereignis</option>
                                    <option value="llm_down">LLM nicht erreichbar</option>
                                    <option value="issue_created">Neuer Issue-Eintrag</option>
                                </select>
                            </div>
                        </div>

                        <!-- Datei-spezifische Felder (nur bei Trigger = Datei) -->
                        <div id="watcher-file-fields">
                            <div class="kb-form-grid-2">
                                <div class="kb-form-field">
                                    <label class="kb-label" for="watcher-path">${window.t('cron.watcher_path')}</label>
                                    <input id="watcher-path" type="text" placeholder="/home/jarvis/inbox" class="kb-input">
                                </div>
                                <div class="kb-form-field">
                                    <label class="kb-label" for="watcher-pattern">${window.t('cron.watcher_pattern')}</label>
                                    <input id="watcher-pattern" type="text" placeholder="*.pdf" class="kb-input">
                                </div>
                            </div>
                            <div class="kb-form-field">
                                <label class="kb-label">${window.t('cron.watcher_events')}</label>
                                <div style="display:flex;gap:12px;padding-top:4px;">
                                    ${['created','modified','deleted','moved'].map(ev =>
                                        `<label class="kb-form-checkbox-label">
                                            <input type="checkbox" class="watcher-event-cb" value="${ev}" ${ev==='created'?'checked':''}> ${ev}
                                        </label>`
                                    ).join('')}
                                </div>
                            </div>
                        </div>

                        <!-- Aktion auswählen -->
                        <div class="kb-form-field">
                            <label class="kb-label" for="watcher-action-type">Aktion bei Auslösung</label>
                            <select id="watcher-action-type" class="kb-input">
                                <option value="agent_task">Jarvis-Aufgabe ausführen</option>
                                <option value="whatsapp">WhatsApp senden</option>
                                <option value="email">E-Mail senden</option>
                                <option value="webhook">Webhook (HTTP POST)</option>
                            </select>
                            <p class="kb-hint" style="margin-top:4px;">Platzhalter: <code>{filename}</code> <code>{filepath}</code> <code>{event}</code> · Issue: <code>{issue_title}</code> <code>{issue_author}</code> <code>{issue_type}</code></p>
                        </div>

                        <!-- Aktion: Jarvis-Aufgabe -->
                        <div id="watcher-action-agent" class="kb-form-row">
                            <label class="kb-label" for="watcher-task">Aufgabe für Jarvis</label>
                            <textarea id="watcher-task" rows="3" class="kb-input"
                                placeholder="Fasse die neu eingetroffene Datei {filename} zusammen."></textarea>
                            <label class="kb-form-checkbox-label" style="margin-top:6px;">
                                <input id="watcher-aussenwirkung" type="checkbox"> ${window.t('cron.aussenwirkung')}
                            </label>
                            <p class="kb-hint" style="margin:2px 0 0 24px;">${window.t('cron.aussenwirkung_hint')}</p>
                        </div>

                        <!-- Aktion: WhatsApp -->
                        <div id="watcher-action-whatsapp" style="display:none;">
                            <div class="kb-form-field">
                                <label class="kb-label" for="watcher-wa-to">WhatsApp-Empfänger (z.B. +49170…)</label>
                                <input id="watcher-wa-to" type="text" placeholder="+491701234567" class="kb-input">
                            </div>
                            <div class="kb-form-row">
                                <label class="kb-label" for="watcher-wa-message">Nachricht</label>
                                <textarea id="watcher-wa-message" rows="2" class="kb-input"
                                    placeholder="⚠️ Jarvis: Das aktive LLM ist nicht erreichbar!"></textarea>
                            </div>
                        </div>

                        <!-- Aktion: Webhook -->
                        <div id="watcher-action-webhook" style="display:none;">
                            <div class="kb-form-field">
                                <label class="kb-label" for="watcher-webhook-url">Webhook-URL</label>
                                <input id="watcher-webhook-url" type="text" placeholder="https://hooks.example.com/…" class="kb-input">
                            </div>
                            <div class="kb-form-row">
                                <label class="kb-label" for="watcher-webhook-body">Nachricht/Body (als JSON-Feld &quot;text&quot;)</label>
                                <textarea id="watcher-webhook-body" rows="2" class="kb-input"
                                    placeholder="LLM down: {event}"></textarea>
                            </div>
                            <label class="kb-form-checkbox-label" style="margin-top:6px;">
                                <input id="watcher-webhook-tls-aus" type="checkbox"> ${window.t('cron.webhook_tls_aus')}
                            </label>
                            <p class="kb-hint" style="margin:2px 0 0 24px;">${window.t('cron.webhook_tls_aus_hint')}</p>
                        </div>

                        <!-- Aktion: E-Mail -->
                        <div id="watcher-action-email" style="display:none;">
                            <div class="kb-form-grid-2">
                                <div class="kb-form-field">
                                    <label class="kb-label" for="watcher-email-to">Empfänger (E-Mail)</label>
                                    <input id="watcher-email-to" type="text" placeholder="empfaenger@example.com" class="kb-input">
                                </div>
                                <div class="kb-form-field">
                                    <label class="kb-label" for="watcher-email-subject">Betreff</label>
                                    <input id="watcher-email-subject" type="text" placeholder="Jarvis: LLM nicht erreichbar" class="kb-input">
                                </div>
                            </div>
                            <div class="kb-form-row">
                                <label class="kb-label" for="watcher-email-body">Nachricht</label>
                                <textarea id="watcher-email-body" rows="2" class="kb-input"
                                    placeholder="Das aktive LLM ist nicht erreichbar ({event})."></textarea>
                            </div>
                            <p class="kb-hint" style="margin-top:4px;">Versand über das verbundene Google-Konto (Einstellungen → Google).</p>
                        </div>

                        <div class="kb-form-footer">
                            <div class="kb-form-footer-left">
                                <label class="kb-form-checkbox-label">
                                    <input id="watcher-enabled" type="checkbox" checked> ${window.t('common.active')}
                                </label>
                            </div>
                            <div class="kb-form-footer-right">
                                <button id="watcher-cancel-btn" class="kb-btn-secondary">${window.t('cron.cancel_btn')}</button>
                                <button id="watcher-save-btn"   class="kb-btn-action">${window.t('cron.save_btn')}</button>
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

        // Trigger-/Aktions-Typ: passende Felder ein-/ausblenden
        document.getElementById('watcher-trigger-type').addEventListener('change', () => this._updateWatcherFormVisibility());
        document.getElementById('watcher-action-type').addEventListener('change', () => this._updateWatcherFormVisibility());

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
        const body = document.getElementById(bodyId);
        const tog  = document.getElementById(togId);
        // Gemerkten Auf-/Zu-Zustand (pro Container) anwenden; ohne gespeicherten
        // Wert gilt der HTML-Default. Key-Schema identisch zu app.js.
        const key = 'jarvis_sect_collapse_' + hdrId;
        let saved = null;
        try { saved = localStorage.getItem(key); } catch (e) {}
        const collapsed0 = (saved === '1') ? true
            : (saved === '0') ? false
            : (body && body.style.display === 'none');
        if (body) body.style.display = collapsed0 ? 'none' : '';
        if (tog) tog.textContent = collapsed0 ? '▶' : '▼';
        hdr.classList.toggle('is-collapsed', collapsed0);
        hdr.addEventListener('click', e => {
            if (e.target.closest('button, input, label')) return;
            const nowCollapsed = body.style.display !== 'none';
            body.style.display = nowCollapsed ? 'none' : '';
            if (tog) tog.textContent = nowCollapsed ? '▶' : '▼';
            hdr.classList.toggle('is-collapsed', nowCollapsed);
            try { localStorage.setItem(key, nowCollapsed ? '1' : '0'); } catch (e) {}
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
            try { localStorage.setItem('jarvis_sect_collapse_' + hdrId, '0'); } catch (e) {}
        }
    }

    // ─── Formular-Platzierung ────────────────────────────────────────────
    // Beim Bearbeiten steht das Formular IN der Box des Eintrags, nicht ueber
    // der ganzen Liste - sonst ist nicht zu sehen, welcher Eintrag gerade
    // bearbeitet wird. Die Neuanlage bleibt oberhalb der Liste. Das Formular
    // wird VERSCHOBEN, nicht neu gebaut: Eingaben und Zuhoerer bleiben erhalten.
    // Vor jedem Neuzeichnen der Liste wird es zurueckgeholt (innerHTML wuerde es
    // sonst mitloeschen) und danach wieder in die Box gesetzt.
    _parkForm(formId, listId) {
        const form = document.getElementById(formId);
        const list = document.getElementById(listId);
        if (!form || !list) return null;
        const act = document.activeElement;
        const focus = (act && form.contains(act)) ? act : null;
        if (form.nextElementSibling !== list) list.parentNode.insertBefore(form, list);
        return focus;
    }

    // Liefert false, wenn der bearbeitete Eintrag nicht mehr in der Liste steht.
    _placeForm(formId, listId, editingId, focus = null) {
        const form = document.getElementById(formId);
        const list = document.getElementById(listId);
        if (!form || !list) return true;
        if (editingId === null || editingId === undefined) {
            this._parkForm(formId, listId);
        } else {
            const item = [...list.querySelectorAll('.cron-item')]
                .find(el => el.dataset.id === String(editingId));
            if (!item) return false;
            if (form.parentNode !== item) item.appendChild(form);
        }
        if (focus && focus.isConnected && document.activeElement !== focus) {
            try { focus.focus({ preventScroll: true }); } catch (e) {}
        }
        return true;
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
        const focus = this._parkForm('cron-form-wrap', 'cron-list');
        this._renderJobItems(el);
        if (!this._placeForm('cron-form-wrap', 'cron-list', this._editingJobId, focus)) this._hideJobForm();
    }

    _renderJobItems(el) {
        // Aufgeklappte Protokoll-Eintraege VOR dem Ueberschreiben merken - das
        // neue Markup kennt sie nicht, und _renderLog liest sonst eine leere Box.
        this._logAufVorher = {};
        el.querySelectorAll('.cron-log').forEach(b => {
            this._logAufVorher[b.dataset.id] = new Set(Array.prototype.map.call(
                b.querySelectorAll('.cron-log-eintrag[open]'), x => x.dataset.ts));
        });
        if (!this._jobs.length) {
            el.innerHTML = `<p class="kb-empty" style="text-align:center;padding:16px 0;">${window.t('cron.no_jobs')}</p>`;
            return;
        }
        el.innerHTML = `<div class="kb-folder-list">${this._jobs.map(job => {
            const lastRun  = job.last_run ? new Date(job.last_run * 1000).toLocaleString(_cronOrt()) : '—';
            const dotCls   = job.enabled ? 'active' : 'inactive';
            const onceBadge = (job.once ? `<span style="font-size:.7rem;background:var(--accent-muted,rgba(99,102,241,.2));color:var(--accent);border-radius:4px;padding:1px 6px;margin-left:4px;">einmalig</span>` : '')
                + ((job.kind || 'agent') === 'agent' && job.aussenwirkung === true
                    ? `<span class="cron-owner-badge cron-badge-none" style="margin-left:4px;" title="${this._esc(window.t('cron.aussenwirkung_hint'))}">${window.t('cron.aussenwirkung_badge')}</span>` : '');
            // Auftraggeber-Bindung sichtbar machen: mit WESSEN Rechten laeuft der
            // Auftrag? Ohne Besitzer laeuft er unprivilegiert und scheitert an
            // System-Befehlen – deshalb der Uebernehmen-Knopf (nur Admins).
            const owner    = job.owner || '';
            const rightsCls = job.owner_privileged ? 'cron-badge-sys' : 'cron-badge-user';
            const rightsTxt = !owner ? window.t('cron.owner_none')
                            : job.owner_privileged ? window.t('cron.rights_system')
                            : window.t('cron.rights_user');
            const ownerBadge = `<span class="cron-owner-badge ${owner ? rightsCls : 'cron-badge-none'}" `
                + `title="${this._esc(window.t('cron.owner_hint'))}">${this._esc(rightsTxt)}`
                + `${owner ? ` · ${this._esc(owner)}` : ''}</span>`;
            // Übernehmen nur anbieten, wenn der Auftrag noch keine Systemrechte hat.
            // Ob der Benutzer übernehmen DARF, entscheidet der Server
            // (/api/cron/{id}/claim hängt an require_local_auth) – /settings ist
            // ohnehin nur für Admins erreichbar.
            // Erinnerungen (kind='reminder') sind reine Sendeauftraege: zur
            // Faelligkeit geht nur eine Nachricht raus, es laeuft KEIN Agent.
            // Das muss man sehen koennen – sonst haelt ein Admin den Eintrag fuer
            // einen Auftrag, den ein Netzwerk-Benutzer angelegt hat.
            const isRem = job.kind === 'reminder';
            // Wartungsauftrag (kind='wissensabgleich', seit 2026-09-21): sieht
            // nach, ob sich in den Wissensordnern etwas geaendert hat, und
            // indiziert nur dann nach. Ebenfalls OHNE Agent - auch das muss man
            // sehen koennen, sonst haelt ein Admin den Auftragstext fuer etwas,
            // das ein Modell ausfuehrt.
            const isWiss = job.kind === 'wissensabgleich';
            // Sicherheitsluecken-Pruefung (kind='cve_pruefung'): ebenfalls ohne
            // Agent. Ob sie automatisch BEHEBT, muss man in der Liste sehen –
            // das ist der Unterschied zwischen Bericht und Eingriff.
            const isCve = job.kind === 'cve_pruefung';
            const cveBadge = isCve
                ? `<span class="cron-owner-badge cron-badge-user" title="${this._esc(window.t('cron.kind_cve_hint'))}">`
                  + `${this._esc(window.t('cron.kind_cve'))}</span> `
                  + ((job.payload || {}).beheben === true
                      ? `<span class="cron-owner-badge cron-badge-none" title="${this._esc(window.t('cron.cve_beheben_hint'))}">`
                        + `${this._esc(window.t('cron.cve_badge_beheben'))}</span> ` : '')
                : '';
            const kindBadge = isCve ? cveBadge : isRem
                ? `<span class="cron-owner-badge cron-badge-user" title="${this._esc(window.t('cron.kind_reminder_hint'))}">`
                  + `${this._esc(window.t('cron.kind_reminder'))}</span> `
                : (isWiss
                ? `<span class="cron-owner-badge cron-badge-user" title="${this._esc(window.t('cron.kind_wissen_hint'))}">`
                  + `${this._esc(window.t('cron.kind_wissen'))}</span> ` : '');
            // Übernehmen (= Systemrechte) ist bei einer Erinnerung sinnlos: sie
            // fuehrt nichts aus. Dasselbe gilt fuer den Wissensabgleich - er
            // ruft eine Funktion im Dienst, keine Rechte im Spiel.
            const claimBtn = (!job.owner_privileged && !isRem && !isWiss && !isCve)
                ? `<button class="kb-btn-icon cron-claim-btn" data-id="${job.id}" `
                  + `title="${this._esc(window.t('cron.claim_title'))}">🔑</button>` : '';
            return `
            <div class="cron-item" data-id="${job.id}">
                <div class="cron-item-row">
                    <span class="cron-item-dot ${dotCls}"></span>
                    <span class="cron-item-label">${this._esc(job.label)}${onceBadge}</span>
                    <code  class="cron-item-code" data-tip="${this._esc(this._cronToText(job.cron))}">${this._esc(job.cron)}</code>
                    <div   class="cron-item-actions">
                        <button class="kb-btn-run  cron-run-btn"  data-id="${job.id}" title="Jetzt ausführen">▶</button>
                        <button class="kb-btn-icon cron-log-btn" data-id="${job.id}" aria-expanded="${this._logOffen.has(job.id) ? 'true' : 'false'}" title="${this._esc(window.t('cron.log_hint'))}">${this._esc(window.t('cron.log_btn'))}</button>
                        ${claimBtn}
                        <button class="kb-btn-icon cron-edit-btn" data-id="${job.id}" title="Bearbeiten">${JarvisIcons.pencil()}</button>
                        <button class="kb-btn-danger cron-del-btn" data-id="${job.id}" title="Löschen">${JarvisIcons.trash()}</button>
                        <label class="kb-form-checkbox-label" style="margin-left:4px;" title="${job.enabled ? 'Aktiv' : 'Inaktiv'}">
                            <input type="checkbox" class="cron-toggle" data-id="${job.id}" ${job.enabled ? 'checked' : ''}>
                        </label>
                    </div>
                </div>
                <div class="cron-item-task">${this._esc(job.task)}</div>
                <div class="cron-item-meta">${kindBadge}${ownerBadge} ${window.t('cron.last_run')}: ${lastRun}${job.last_result ? ` · ${this._esc(job.last_result.substring(0,80))}${job.last_result.length>80?'…':''}` : ''}</div>
                <div class="cron-log" data-id="${job.id}"${this._logOffen.has(job.id) ? '' : ' hidden'}></div>
            </div>`;
        }).join('')}</div>`;

        el.querySelectorAll('.cron-claim-btn').forEach(btn => { btn.onclick = () => this._claimJob(btn.dataset.id); });
        el.querySelectorAll('.cron-del-btn').forEach(btn => { btn.onclick = () => this._deleteJob(btn.dataset.id); });
        el.querySelectorAll('.cron-edit-btn').forEach(btn => { btn.onclick = () => this._editJob(btn.dataset.id); });
        el.querySelectorAll('.cron-run-btn').forEach(btn  => { btn.onclick = () => this._runJobNow(btn.dataset.id, btn); });
        el.querySelectorAll('.cron-toggle').forEach(cb    => { cb.onchange  = () => this._toggleJob(cb.dataset.id, cb.checked); });
        el.querySelectorAll('.cron-log-btn').forEach(btn  => { btn.onclick = () => this._toggleLog(btn.dataset.id); });
        // Offene Protokolle nach dem Neuzeichnen wieder fuellen: erst aus dem
        // Merker (sofort, ohne Flackern), dann frisch vom Server - ein Lauf
        // hat die Liste ja gerade verlaengert.
        this._logOffen.forEach(id => {
            if (!this._jobs.some(j => j.id === id)) { this._logOffen.delete(id); return; }
            this._renderLog(id);
            this._loadLog(id);
        });
    }

    // ─── Protokoll je Auftrag (Vorgabe 2026-09-28) ─────────────────────────
    // Ein Eintrag je Lauf (backend/cron_log.py) - last_result oben kennt nur
    // den LETZTEN, der naechste Lauf ueberschreibt ihn.

    _logBox(id) {
        return Array.prototype.find.call(document.querySelectorAll('#cron-list .cron-log'),
                                         b => b.dataset.id === id) || null;
    }

    _toggleLog(id) {
        const auf = !this._logOffen.has(id);
        if (auf) this._logOffen.add(id); else this._logOffen.delete(id);
        const box = this._logBox(id);
        if (box) box.hidden = !auf;
        const btn = Array.prototype.find.call(document.querySelectorAll('#cron-list .cron-log-btn'),
                                              b => b.dataset.id === id);
        if (btn) btn.setAttribute('aria-expanded', auf ? 'true' : 'false');
        if (auf) { this._renderLog(id); this._loadLog(id); }
    }

    async _loadLog(id, aelter = false) {
        const alt = this._logDaten[id];
        let url = `/api/cron/${encodeURIComponent(id)}/log?limit=50`;
        const letzter = aelter && alt && alt.eintraege.length ? alt.eintraege[alt.eintraege.length - 1] : null;
        if (letzter) url += `&vor=${encodeURIComponent(letzter.ts)}`;
        try {
            const r = await fetch(url, { headers: _authHeaders() });
            const d = await r.json().catch(() => ({}));
            if (!r.ok || !d.ok) throw new Error(d.error || d.detail || ('HTTP ' + r.status));
            const neu = d.eintraege || [];
            this._logDaten[id] = {
                eintraege: letzter ? alt.eintraege.concat(neu) : neu,
                mehr: !!d.mehr, fehler: '',
            };
        } catch (e) {
            // ⚠ Kein "noch keine Laeufe" bei einem Fehler: das waere eine
            // Falschaussage ueber einen Auftrag, der vielleicht taeglich laeuft.
            this._logDaten[id] = Object.assign({ eintraege: [], mehr: false }, alt || {},
                                               { fehler: e.message || String(e) });
        }
        if (this._logOffen.has(id)) this._renderLog(id);
    }

    _renderLog(id) {
        const box = this._logBox(id);
        if (!box) return;
        const d = this._logDaten[id];
        if (!d) { box.innerHTML = `<div class="cron-log-leer">${this._esc(window.t('common.loading'))}</div>`; return; }
        const offen = new Set(Array.prototype.map.call(box.querySelectorAll('.cron-log-eintrag[open]'),
                                                       x => x.dataset.ts));
        // Einmalig nach einem Neuzeichnen der Liste (siehe _renderJobItems);
        // danach ist das DOM wieder die Wahrheit - sonst oeffnete sich ein
        // Eintrag, den jemand inzwischen zugeklappt hat, beim naechsten Mal neu.
        const merk = (this._logAufVorher || {})[id];
        if (merk) { merk.forEach(ts => offen.add(ts)); delete this._logAufVorher[id]; }
        const zeilen = d.eintraege.map(e => {
            const zeit = e.ts ? new Date(e.ts * 1000).toLocaleString(_cronOrt()) : '—';
            const wer = e.ausloeser === 'manuell'
                ? window.t('cron.log_manual') + (e.von ? ' · ' + e.von : '')
                : window.t('cron.log_schedule');
            const erg = String(e.ergebnis || '');
            const kurz = erg.split('\n')[0].slice(0, 140) + (erg.length > 140 || erg.indexOf('\n') !== -1 ? '…' : '');
            return `<details class="cron-log-eintrag ${e.ok ? 'ok' : 'fehler'}" data-ts="${this._esc(String(e.ts))}"${offen.has(String(e.ts)) ? ' open' : ''}>`
                + `<summary><span class="cron-log-status">${this._esc(window.t(e.ok ? 'cron.log_ok' : 'cron.log_err'))}</span>`
                + `<span class="cron-log-zeit">${this._esc(zeit)}</span>`
                + `<span class="cron-log-wer">${this._esc(wer)}</span>`
                + `<span class="cron-log-dauer">${this._esc(this._logDauer(e.dauer_s))}</span>`
                + `<span class="cron-log-kurz">${this._esc(kurz || window.t('cron.log_no_result'))}</span></summary>`
                + `<pre class="cron-log-voll">${this._esc(erg || window.t('cron.log_no_result'))}</pre>`
                + (e.gekuerzt ? `<div class="cron-log-hinweis">${this._esc(window.t('cron.log_truncated'))}</div>` : '')
                + `</details>`;
        }).join('');
        box.innerHTML = (d.fehler ? `<div class="cron-log-fehlermeldung">${this._esc(window.t('cron.log_load_err').replace('{e}', d.fehler))}</div>` : '')
            + (zeilen || (d.fehler ? '' : `<div class="cron-log-leer">${this._esc(window.t('cron.log_none'))}</div>`))
            + (d.mehr ? `<button class="kb-btn-icon cron-log-mehr" type="button">${this._esc(window.t('cron.log_more'))}</button>` : '');
        const mehr = box.querySelector('.cron-log-mehr');
        if (mehr) mehr.onclick = () => { mehr.disabled = true; this._loadLog(id, true); };
    }

    _logDauer(s) {
        const n = Number(s);
        if (!isFinite(n)) return '';
        if (n >= 60) return (n / 60).toFixed(1).replace('.', ',') + ' min';
        return n.toFixed(1).replace('.', ',') + ' s';
    }

    _showJobForm(job = null) {
        this._expandSection('cron-sect-jobs-body', 'cron-sect-jobs-tog', 'cron-sect-jobs-hdr');
        this._editingJobId = job ? job.id : null;
        document.getElementById('cron-form-title').textContent  = job ? window.t('cron.form_title_edit') : window.t('cron.form_title_new');
        document.getElementById('cron-label').value    = job ? job.label : '';
        document.getElementById('cron-schedule').value = job ? job.cron  : '';
        document.getElementById('cron-task').value     = job ? job.task  : '';
        document.getElementById('cron-enabled').checked = job ? job.enabled : true;
        // BSI H8/H9-Rest: nur ein echtes true ist eine Freigabe; neu = aus.
        document.getElementById('cron-aussenwirkung').checked = !!job && job.aussenwirkung === true;
        const kindSel = document.getElementById('cron-kind');
        kindSel.value = job && job.kind === 'cve_pruefung' ? 'cve_pruefung' : 'agent';
        // Die Art ist nach dem Anlegen fest (der Server aendert `kind` nie).
        kindSel.disabled = !!job;
        const pl = (job && job.payload) || {};
        document.getElementById('cron-cve-beheben').checked = pl.beheben === true;
        document.getElementById('cron-cve-schwelle').value = pl.schwelle || '';
        kindSel.onchange = () => this._artUmschalten();
        this._artUmschalten();
        document.getElementById('cron-form-error').style.display = 'none';
        document.getElementById('cron-form-wrap').style.display  = '';
        this._placeForm('cron-form-wrap', 'cron-list', this._editingJobId);
        // Live-Preview aktualisieren
        const prev = document.getElementById('cron-schedule-preview');
        if (prev) prev.textContent = job ? this._cronToText(job.cron) : '';
        document.getElementById('cron-label').focus();
    }

    /* Blendet je nach Art das Auftragsfeld oder die Pruefoptionen ein. Ein
     * Erinnerungs- oder Wissensauftrag wird hier nicht bearbeitet, er
     * erscheint als "Agent" nur, wenn man ihn neu anlegt. */
    _artUmschalten() {
        const cve = document.getElementById('cron-kind').value === 'cve_pruefung';
        document.getElementById('cron-cve-opts').hidden = !cve;
        document.getElementById('cron-task-row').hidden = cve;
        const lab = document.getElementById('cron-label');
        if (cve && !lab.value.trim()) lab.value = window.t('cron.cve_label_vorgabe');
        if (!cve) return;
        // Hinweis, wenn unattended-upgrades schon laeuft: dann behebt diese
        // Option vor allem Luecken, deren Behebung nur im regulaeren Release liegt.
        const hint = document.getElementById('cron-cve-unatt');
        fetch('/api/security/unattended', { headers: _authHeaders() })
            .then(r => r.ok ? r.json() : null)
            .then(d => { hint.hidden = !(d && d.enabled); })
            .catch(() => { hint.hidden = true; });
    }

    _hideJobForm() {
        this._editingJobId = null;
        this._parkForm('cron-form-wrap', 'cron-list');
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
        const aussenwirkung = document.getElementById('cron-aussenwirkung').checked;
        const errEl   = document.getElementById('cron-form-error');
        const istCve  = document.getElementById('cron-kind').value === 'cve_pruefung';
        const cveOpt  = { beheben: document.getElementById('cron-cve-beheben').checked,
                          schwelle: document.getElementById('cron-cve-schwelle').value };
        if (!label || !cron || (!task && !istCve)) {
            errEl.textContent  = window.t('cron.error_fill_all');
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
                body: JSON.stringify(istCve
                    ? Object.assign({ label, cron, enabled, cve: cveOpt },
                                    this._editingJobId ? {} : { kind: 'cve_pruefung' })
                    : { label, cron, task, enabled, aussenwirkung })
            });
            if (!r.ok) {
                const e = await r.json().catch(() => ({}));
                errEl.textContent = e.detail || 'Fehler';
                errEl.style.display = 'block';
                return;
            }
            this._hideJobForm();
            this._loadJobs();
            this._notify(window.t('cron.job_saved'));
        } catch (e) {
            errEl.textContent = 'Netzwerkfehler: ' + e.message;
            errEl.style.display = 'block';
        }
    }

    async _claimJob(id) {
        // Übernahme ist die AUSDRÜCKLICHE Entscheidung, diesem Auftrag
        // Systemrechte zu geben – deshalb eine eigene Bestätigung und kein
        // Nebeneffekt des Bearbeiten-Formulars.
        if (!confirm(window.t('cron.claim_confirm'))) return;
        const r = await fetch(`/api/cron/${id}/claim`, { method: 'POST', headers: _authHeaders() });
        if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            this._notify(d.detail || window.t('cron.claim_failed'), 'error');
            return;
        }
        this._loadJobs();
        this._notify(window.t('cron.claim_done'));
    }

    async _deleteJob(id) {
        if (!confirm(window.t('cron.delete_job_confirm'))) return;
        await fetch(`/api/cron/${id}`, { method: 'DELETE', headers: _authHeaders() });
        this._loadJobs();
        this._notify(window.t('cron.job_deleted'), 'info');
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
        const focus = this._parkForm('watcher-form-wrap', 'watcher-list');
        this._renderWatcherItems(el);
        if (!this._placeForm('watcher-form-wrap', 'watcher-list', this._editingWatcherId, focus)) this._hideWatcherForm();
    }

    _renderWatcherItems(el) {
        if (!this._watchers.length) {
            el.innerHTML = `<p class="kb-empty" style="text-align:center;padding:16px 0;">${window.t('cron.no_watchers')}</p>`;
            return;
        }
        el.innerHTML = `<div class="kb-folder-list">${this._watchers.map(w => {
            const lastTrig  = w.last_triggered ? new Date(w.last_triggered * 1000).toLocaleString(_cronOrt()) : '—';
            const dotCls    = w.enabled ? 'active' : 'inactive';
            const trig      = w.trigger_type || 'file';
            const act       = w.action_type || 'agent_task';
            const trigLabel = trig === 'llm_down' ? '⚡ LLM nicht erreichbar' : (trig === 'issue_created' ? '🐞 Neuer Issue' : '📂 Datei');
            const actLabel  = act === 'whatsapp' ? '📱 WhatsApp' : (act === 'webhook' ? '🔗 Webhook' : (act === 'email' ? '✉️ E-Mail' : '🤖 Jarvis-Aufgabe'));
            const evBadges  = (trig === 'file') ? (w.events || []).map(ev => `<span class="cron-event-badge">${ev}</span>`).join('') : '';
            const trigDetail = (trig === 'file')
                ? `<div class="cron-item-path">📂 ${this._esc(w.path || '')} <code class="cron-item-code">${this._esc(w.pattern || '*')}</code></div>` : '';
            let detail = '';
            if (act === 'agent_task')      detail = this._esc(w.task || '');
            else if (act === 'whatsapp')   detail = `→ ${this._esc(w.wa_to || '')}: ${this._esc(w.wa_message || '')}`;
            else if (act === 'webhook')    detail = this._esc(w.webhook_url || '');
            else if (act === 'email')      detail = `→ ${this._esc(w.email_to || '')}: ${this._esc(w.email_subject || '')}`;
            return `
            <div class="cron-item" data-id="${w.id}">
                <div class="cron-item-row">
                    <span class="cron-item-dot ${dotCls}"></span>
                    <span class="cron-item-label">${this._esc(w.label)}${(w.action_type || 'agent_task') === 'agent_task' && w.aussenwirkung === true
                        ? `<span class="cron-owner-badge cron-badge-none" style="margin-left:4px;" title="${this._esc(window.t('cron.aussenwirkung_hint'))}">${window.t('cron.aussenwirkung_badge')}</span>` : ''}</span>
                    <span class="cron-event-badge">${trigLabel}</span>
                    <span style="display:flex;gap:3px;">${evBadges}</span>
                    <span class="cron-event-badge">${actLabel}</span>
                    <div   class="cron-item-actions">
                        <button class="kb-btn-icon   watcher-edit-btn" data-id="${w.id}" title="Bearbeiten">${JarvisIcons.pencil()}</button>
                        <button class="kb-btn-danger watcher-del-btn"  data-id="${w.id}" title="Löschen">${JarvisIcons.trash()}</button>
                        <label class="kb-form-checkbox-label" style="margin-left:4px;" title="${w.enabled ? 'Aktiv' : 'Inaktiv'}">
                            <input type="checkbox" class="watcher-toggle" data-id="${w.id}" ${w.enabled ? 'checked' : ''}>
                        </label>
                    </div>
                </div>
                ${trigDetail}
                <div class="cron-item-task">${detail}</div>
                <div class="cron-item-meta">${window.t('cron.last_trigger')}: ${lastTrig}${w.last_result ? ` · ${this._esc(w.last_result.substring(0,80))}${w.last_result.length>80?'…':''}` : ''}</div>
            </div>`;
        }).join('')}</div>`;

        el.querySelectorAll('.watcher-del-btn').forEach(btn  => { btn.onclick  = () => this._deleteWatcher(btn.dataset.id); });
        el.querySelectorAll('.watcher-edit-btn').forEach(btn => { btn.onclick  = () => this._editWatcher(btn.dataset.id); });
        el.querySelectorAll('.watcher-toggle').forEach(cb    => { cb.onchange  = () => this._toggleWatcher(cb.dataset.id, cb.checked); });
    }

    _showWatcherForm(w = null) {
        this._expandSection('cron-sect-watch-body', 'cron-sect-watch-tog', 'cron-sect-watch-hdr');
        this._editingWatcherId = w ? w.id : null;
        document.getElementById('watcher-form-title').textContent = w ? window.t('cron.form_title_edit_watcher') : window.t('cron.form_title_new_watcher');
        document.getElementById('watcher-label').value   = w ? w.label : '';
        document.getElementById('watcher-path').value    = w ? w.path  : '';
        document.getElementById('watcher-pattern').value = w ? (w.pattern || '*') : '*.pdf';
        document.getElementById('watcher-task').value    = w ? w.task  : '';
        document.getElementById('watcher-enabled').checked = w ? w.enabled : true;
        document.getElementById('watcher-aussenwirkung').checked = !!w && w.aussenwirkung === true;
        document.querySelectorAll('.watcher-event-cb').forEach(cb => {
            cb.checked = w ? (w.events || ['created']).includes(cb.value) : cb.value === 'created';
        });
        document.getElementById('watcher-trigger-type').value = w ? (w.trigger_type || 'file') : 'file';
        document.getElementById('watcher-action-type').value  = w ? (w.action_type || 'agent_task') : 'agent_task';
        document.getElementById('watcher-wa-to').value        = w ? (w.wa_to || '') : '';
        document.getElementById('watcher-wa-message').value   = w ? (w.wa_message || '') : '';
        document.getElementById('watcher-webhook-url').value  = w ? (w.webhook_url || '') : '';
        document.getElementById('watcher-webhook-body').value = w ? (w.webhook_body || '') : '';
        // BSI M12: angehakt heisst "Pruefung AUS" – nur ein gespeichertes false hakt an.
        document.getElementById('watcher-webhook-tls-aus').checked = !!w && w.webhook_tls_pruefen === false;
        document.getElementById('watcher-email-to').value      = w ? (w.email_to || '') : '';
        document.getElementById('watcher-email-subject').value = w ? (w.email_subject || '') : '';
        document.getElementById('watcher-email-body').value    = w ? (w.email_body || '') : '';
        this._updateWatcherFormVisibility();
        document.getElementById('watcher-form-error').style.display = 'none';
        document.getElementById('watcher-form-wrap').style.display  = '';
        this._placeForm('watcher-form-wrap', 'watcher-list', this._editingWatcherId);
        document.getElementById('watcher-label').focus();
    }

    _updateWatcherFormVisibility() {
        const trig = document.getElementById('watcher-trigger-type').value;
        const act  = document.getElementById('watcher-action-type').value;
        document.getElementById('watcher-file-fields').style.display     = (trig === 'file') ? '' : 'none';
        document.getElementById('watcher-action-agent').style.display    = (act === 'agent_task') ? '' : 'none';
        document.getElementById('watcher-action-whatsapp').style.display = (act === 'whatsapp') ? '' : 'none';
        document.getElementById('watcher-action-webhook').style.display  = (act === 'webhook') ? '' : 'none';
        document.getElementById('watcher-action-email').style.display    = (act === 'email') ? '' : 'none';
    }

    _hideWatcherForm() {
        this._editingWatcherId = null;
        this._parkForm('watcher-form-wrap', 'watcher-list');
        document.getElementById('watcher-form-wrap').style.display = 'none';
    }

    _editWatcher(id) {
        const w = this._watchers.find(x => x.id === id);
        if (w) this._showWatcherForm(w);
    }

    async _saveWatcher() {
        const label        = document.getElementById('watcher-label').value.trim();
        const trigger_type = document.getElementById('watcher-trigger-type').value;
        const action_type  = document.getElementById('watcher-action-type').value;
        const path         = document.getElementById('watcher-path').value.trim();
        const pattern      = document.getElementById('watcher-pattern').value.trim() || '*';
        const task         = document.getElementById('watcher-task').value.trim();
        const wa_to        = document.getElementById('watcher-wa-to').value.trim();
        const wa_message   = document.getElementById('watcher-wa-message').value.trim();
        const webhook_url  = document.getElementById('watcher-webhook-url').value.trim();
        const webhook_body = document.getElementById('watcher-webhook-body').value.trim();
        const webhook_tls_pruefen = !document.getElementById('watcher-webhook-tls-aus').checked;
        const email_to      = document.getElementById('watcher-email-to').value.trim();
        const email_subject = document.getElementById('watcher-email-subject').value.trim();
        const email_body    = document.getElementById('watcher-email-body').value.trim();
        const enabled      = document.getElementById('watcher-enabled').checked;
        const aussenwirkung = document.getElementById('watcher-aussenwirkung').checked;
        const events       = [...document.querySelectorAll('.watcher-event-cb:checked')].map(cb => cb.value);
        const errEl        = document.getElementById('watcher-form-error');
        const fail = (msg) => { errEl.textContent = msg; errEl.style.display = 'block'; };

        if (!label) return fail('Bitte einen Namen angeben.');
        if (trigger_type === 'file') {
            if (!path) return fail('Bitte den zu überwachenden Pfad angeben.');
            if (!events.length) return fail(window.t('cron.watcher_error_events'));
        }
        if (action_type === 'agent_task' && !task) return fail('Bitte eine Aufgabe für Jarvis angeben.');
        if (action_type === 'whatsapp' && (!wa_to || !wa_message)) return fail('Bitte WhatsApp-Empfänger und Nachricht angeben.');
        if (action_type === 'webhook' && !webhook_url) return fail('Bitte eine Webhook-URL angeben.');
        if (action_type === 'email' && !email_to) return fail('Bitte einen E-Mail-Empfänger angeben.');
        errEl.style.display = 'none';
        try {
            const method = this._editingWatcherId ? 'PUT' : 'POST';
            const url    = this._editingWatcherId ? `/api/watchers/${this._editingWatcherId}` : '/api/watchers';
            const r = await fetch(url, {
                method,
                headers: { ..._authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ label, trigger_type, action_type, path, pattern, events, task,
                                       wa_to, wa_message, webhook_url, webhook_body, webhook_tls_pruefen,
                                       email_to, email_subject, email_body, enabled, aussenwirkung })
            });
            if (!r.ok) {
                const e = await r.json().catch(() => ({}));
                errEl.textContent = e.detail || 'Fehler';
                errEl.style.display = 'block';
                return;
            }
            this._hideWatcherForm();
            this._loadWatchers();
            this._notify(window.t('cron.watcher_saved'));
        } catch (e) {
            errEl.textContent = 'Netzwerkfehler: ' + e.message;
            errEl.style.display = 'block';
        }
    }

    async _deleteWatcher(id) {
        if (!confirm(window.t('cron.delete_watcher_confirm'))) return;
        await fetch(`/api/watchers/${id}`, { method: 'DELETE', headers: _authHeaders() });
        this._loadWatchers();
        this._notify(window.t('cron.watcher_deleted'), 'info');
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
