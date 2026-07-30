/* ═══════════════════════════════════════════════════════════════════
   Skill-Konfiguration in Settings-Reitern (generisch)
   ───────────────────────────────────────────────────────────────────
   Jeder Skill mit config_schema soll seine Einstellungen in einem
   eigenen Reiter haben – das Zahnrad unter "Installierte Skills"
   springt dorthin (skills.js: SKILL_TABS). Statt sechs handgeschriebene
   Panels rendert dieses Modul die Felder direkt aus dem Manifest
   (skill.json → config_schema), sodass neue Manifest-Felder ohne
   Frontend-Aenderung erscheinen.

   Reiter-Skills:  google, telegram, browser_control, claude_bridge,
                   agent_orchestrator, agent_autonomy_kit, avatar
   Ergaenzungen:   whatsapp (alles ausser debug_mode – das hat schon
                   einen Toggle im Logs-Abschnitt), knowledge
                   (max_file_size_mb; folders/search_mode haben
                   eigene Oberflaechen)

   API:  GET  /api/skills                  → Schema + installed/enabled
         GET  /api/skills/{name}/config    → aktuelle Werte
         POST /api/skills/{name}/config    → speichern (Server merged,
                                             also sind Teilmengen ok)
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // Skill → Zielcontainer im Reiter. only/exclude begrenzen die Felder,
    // wenn Teile der Config bereits eine eigene Oberflaeche haben.
    const TARGETS = {
        google:             { container: 'skcfg-google' },
        telegram:           { container: 'skcfg-telegram' },
        browser_control:    { container: 'skcfg-browser_control' },
        claude_bridge:      { container: 'skcfg-claude_bridge' },
        agent_orchestrator: { container: 'skcfg-agent_orchestrator' },
        agent_autonomy_kit: { container: 'skcfg-agent_autonomy_kit' },
        avatar:             { container: 'skcfg-avatar' },
        whatsapp:           { container: 'skcfg-whatsapp', exclude: ['debug_mode'] },
        knowledge:          { container: 'skcfg-knowledge', only: ['max_file_size_mb'] },
    };

    // Skills mit eigenem Reiter: Knopf-ID → nur sichtbar wenn Skill aktiv
    const TAB_BUTTONS = {
        google:             'settings-tab-btn-google',
        telegram:           'settings-tab-btn-telegram',
        browser_control:    'settings-tab-btn-browser',
        claude_bridge:      'settings-tab-btn-claude-bridge',
        agent_orchestrator: 'settings-tab-btn-orchestrator',
        agent_autonomy_kit: 'settings-tab-btn-autonomy',
        avatar:             'settings-tab-btn-avatar',
    };

    const SVG_EYE_OPEN   = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
    const SVG_EYE_CLOSED = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    }
    function tr(key, fallback) {
        const v = window.t ? window.t(key) : null;
        return (!v || v === key) ? fallback : v;
    }

    const Manager = {
        _skills: null,      // Cache der /api/skills-Antwort
        _pending: null,

        // ── Skill-Liste (einmal laden, danach aus dem Cache) ──────────
        async _loadSkills(force) {
            if (this._skills && !force) return this._skills;
            if (!this._pending || force) {
                this._pending = fetch('/api/skills', { headers: authHeaders() })
                    .then(r => r.json())
                    .then(d => { this._skills = (d && d.skills) || []; return this._skills; })
                    .catch(() => { this._skills = []; return this._skills; })
                    .finally(() => { this._pending = null; });
            }
            return this._pending;
        },

        _find(skills, name) {
            return skills.find(s => (s.dir_name || (s.path || '').split('/').pop()) === name);
        },

        // ── Reiter-Sichtbarkeit: Reiter nur bei aktivem Skill ─────────
        async updateTabs() {
            const skills = await this._loadSkills(true);
            Object.keys(TAB_BUTTONS).forEach(name => {
                const btn = document.getElementById(TAB_BUTTONS[name]);
                if (!btn) return;
                const sk = this._find(skills, name);
                btn.style.display = (sk && sk.enabled) ? '' : 'none';
            });
        },

        // ── Reiter geoeffnet ─────────────────────────────────────────
        onShow(name) { this.render(name); },

        // ── Formular aus dem Manifest-Schema bauen ───────────────────
        async render(name) {
            const target = TARGETS[name];
            if (!target) return;
            const box = document.getElementById(target.container);
            if (!box) return;

            box.innerHTML = '<div class="kb-hint">' + tr('common.loading', 'Lädt…') + '</div>';

            const [skills, cfgResp] = await Promise.all([
                this._loadSkills(),
                fetch('/api/skills/' + encodeURIComponent(name) + '/config', { headers: authHeaders() })
                    .then(r => r.json()).catch(() => ({})),
            ]);

            const skill  = this._find(skills, name) || {};
            const schema = skill.config_schema || {};
            const values = (cfgResp && cfgResp.config) || {};

            let keys = Object.keys(schema);
            if (target.only)    keys = keys.filter(k => target.only.includes(k));
            if (target.exclude) keys = keys.filter(k => !target.exclude.includes(k));

            if (!keys.length) {
                box.innerHTML = '<div class="kb-hint">'
                    + tr('skillcfg.no_options', 'Dieser Skill hat keine Einstellungen.') + '</div>';
                return;
            }

            let html = '';
            keys.forEach(key => {
                const f     = schema[key] || {};
                const label = esc(f.label || key);
                const hint  = f.description
                    ? '<div class="kb-hint" style="margin-top:4px;">' + esc(f.description) + '</div>' : '';
                const val   = values[key] !== undefined ? values[key] : f.default;
                const id    = 'skcfg-' + name + '-' + key;

                if (f.type === 'boolean') {
                    html += '<div class="form-group">'
                        + '<label style="display:flex;align-items:center;gap:8px;cursor:pointer;">'
                        + '<input type="checkbox" id="' + id + '" data-key="' + esc(key) + '" data-type="boolean"'
                        + (val ? ' checked' : '') + '>'
                        + '<span>' + label + '</span></label>' + hint + '</div>';
                } else if (f.type === 'number') {
                    // step="any": ein Default von 1.0 kommt aus JSON als 1 an, ist also
                    // nicht von einer echten Ganzzahl zu unterscheiden. Mit step="1"
                    // wuerde der Browser Dezimalwerte (z.B. send_delay 1.5) als
                    // ungueltig markieren – deshalb keine Schrittweite erzwingen.
                    html += '<div class="form-group"><label for="' + id + '">' + label + '</label>'
                        + '<input type="number" step="any" id="' + id + '" class="config-input"'
                        + ' data-key="' + esc(key) + '" data-type="number"'
                        + ' value="' + esc(val != null ? val : '') + '"'
                        + ' style="width:100%;box-sizing:border-box;">' + hint + '</div>';
                } else if (Array.isArray(f.enum) && f.enum.length) {
                    html += '<div class="form-group"><label for="' + id + '">' + label + '</label>'
                        + '<select id="' + id + '" class="config-input" data-key="' + esc(key) + '"'
                        + ' data-type="string" style="width:100%;box-sizing:border-box;">'
                        + f.enum.map(o => '<option value="' + esc(o) + '"'
                            + (String(val) === String(o) ? ' selected' : '') + '>' + esc(o) + '</option>').join('')
                        + '</select>' + hint + '</div>';
                } else if (f.type === 'text') {
                    // Mehrzeiliges Feld (z.B. Avatar: eigene Antworten "Frage ||| Antwort")
                    html += '<div class="form-group"><label for="' + id + '">' + label + '</label>'
                        + '<textarea id="' + id + '" class="config-input" rows="8"'
                        + ' data-key="' + esc(key) + '" data-type="string"'
                        + ' style="width:100%;box-sizing:border-box;resize:vertical;'
                        + 'font-family:inherit;line-height:1.45;">'
                        + esc(val != null ? val : '') + '</textarea>' + hint + '</div>';
                } else if (f.secret) {
                    html += '<div class="form-group"><label for="' + id + '">' + label + '</label>'
                        + '<div style="display:flex;align-items:center;gap:4px;">'
                        + '<input type="password" id="' + id + '" class="config-input" autocomplete="new-password"'
                        + ' data-key="' + esc(key) + '" data-type="string"'
                        + ' value="' + esc(val != null ? val : '') + '"'
                        + ' style="flex:1;min-width:0;box-sizing:border-box;">'
                        + '<button type="button" class="skcfg-eye" data-for="' + id + '"'
                        + ' data-i18n-title="profile.show_hide" title="Anzeigen/verbergen"'
                        + ' style="background:none;border:none;cursor:pointer;padding:0 6px;'
                        + 'color:var(--text-muted,#888);display:flex;align-items:center;flex-shrink:0;">'
                        + SVG_EYE_OPEN + '</button></div>' + hint + '</div>';
                } else {
                    html += '<div class="form-group"><label for="' + id + '">' + label + '</label>'
                        + '<input type="text" id="' + id + '" class="config-input"'
                        + ' data-key="' + esc(key) + '" data-type="string"'
                        + ' value="' + esc(val != null ? val : '') + '"'
                        + ' style="width:100%;box-sizing:border-box;">' + hint + '</div>';
                }
            });

            html += '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:6px;">'
                + '<button class="btn-primary skcfg-save" type="button" data-i18n="common.save">'
                + tr('common.save', 'Speichern') + '</button>'
                + '<span class="skcfg-status" style="font-size:0.9em;"></span></div>';

            box.innerHTML = html;

            box.querySelectorAll('.skcfg-eye').forEach(btn => {
                btn.addEventListener('click', () => {
                    const inp = document.getElementById(btn.dataset.for);
                    if (!inp) return;
                    const hidden = inp.type === 'password';
                    inp.type = hidden ? 'text' : 'password';
                    btn.innerHTML = hidden ? SVG_EYE_CLOSED : SVG_EYE_OPEN;
                });
            });
            const saveBtn = box.querySelector('.skcfg-save');
            if (saveBtn) saveBtn.addEventListener('click', () => this.save(name));
            if (window.applyLang) window.applyLang();
        },

        // ── Speichern (nur die gerenderten Felder) ───────────────────
        async save(name) {
            const target = TARGETS[name];
            const box    = target && document.getElementById(target.container);
            if (!box) return;
            const statusEl = box.querySelector('.skcfg-status');
            const setStatus = (msg, kind) => {
                if (!statusEl) return;
                statusEl.textContent = msg || '';
                statusEl.style.color = kind === 'error' ? 'var(--danger)'
                    : kind === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
            };

            const body = {};
            box.querySelectorAll('[data-key]').forEach(inp => {
                const key = inp.dataset.key;
                if (inp.dataset.type === 'boolean')     body[key] = inp.checked;
                else if (inp.dataset.type === 'number') body[key] = Number(inp.value);
                else                                    body[key] = inp.value;
            });

            setStatus(tr('skillcfg.saving', 'Speichere…'));
            try {
                const resp = await fetch('/api/skills/' + encodeURIComponent(name) + '/config', {
                    method: 'POST',
                    headers: authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify(body),
                });
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                setStatus('✓ ' + tr('skillcfg.saved', 'Gespeichert'), 'ok');
                // Google schreibt Client-ID/Secret zusaetzlich in die .env –
                // Statusanzeige des Google-Reiters danach neu laden.
                if (name === 'google' && window.googleManager) window.googleManager.init();
            } catch (e) {
                setStatus('✗ ' + tr('skillcfg.save_failed', 'Speichern fehlgeschlagen'), 'error');
            }
        },
    };

    window.SkillCfg = Manager;
})();
