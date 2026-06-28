/* Support-Assistent – Konfigurationsreiter (Einstellungen)
   Prompt, KI-/Darstellungs-Parameter und Confluence-Eingrenzung (White-/Blacklist). */
(function () {
    'use strict';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function status(msg, kind) {
        var el = $('support-status'); if (!el) return;
        el.textContent = msg || '';
        el.style.color = kind === 'error' ? 'var(--danger)'
            : kind === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
    }

    var Manager = {
        _bound: false,
        _cfMode: 'off',
        _cfSel: null,        // Set gewählter Space-Keys
        _cfSpaces: null,     // gecachte Bereichsliste

        onShow: function () { this._bind(); this.loadConfig(); },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            this._cfSel = {};
            var save = $('support-save');
            if (save) save.addEventListener('click', this.save.bind(this));
            var self = this;
            // Modus-Buttons
            var btns = document.querySelectorAll('.sup-cf-mode');
            for (var i = 0; i < btns.length; i++) {
                btns[i].addEventListener('click', function () {
                    self._setMode(this.getAttribute('data-mode'), true);
                });
            }
            var srch = $('sup-cf-space-search');
            if (srch) srch.addEventListener('input', function () { self._renderSpaces(); });
            var pers = $('sup-cf-personal');
            if (pers) pers.addEventListener('change', function () { self._renderSpaces(); });
        },

        _setMode: function (mode, loadIfNeeded) {
            this._cfMode = mode;
            var btns = document.querySelectorAll('.sup-cf-mode');
            for (var i = 0; i < btns.length; i++) {
                var active = btns[i].getAttribute('data-mode') === mode;
                btns[i].classList.toggle('btn-primary', active);
                btns[i].classList.toggle('btn-secondary', !active);
            }
            var wrap = $('sup-cf-spaces-wrap');
            if (wrap) wrap.style.display = (mode === 'off') ? 'none' : '';
            if (mode !== 'off' && loadIfNeeded) this._loadSpaces();
        },

        loadConfig: function () {
            var self = this;
            fetch('/api/skills/support_assistant/config', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    if ($('support-prompt')) $('support-prompt').value = c.system_prompt || '';
                    if ($('support-lines')) $('support-lines').value = c.summary_lines || 5;
                    if ($('support-result-lines')) $('support-result-lines').value = c.result_lines || 2;
                    if ($('support-jira-limit')) $('support-jira-limit').value = c.jira_limit || 12;
                    self._cfSel = {};
                    (c.conf_spaces || []).forEach(function (k) { self._cfSel[k] = true; });
                    self._setMode(c.conf_filter_mode || 'off', false);
                    if (self._cfMode !== 'off') self._loadSpaces();
                })
                .catch(function () {});
        },

        _loadSpaces: function () {
            var self = this;
            if (this._cfSpaces) { this._renderSpaces(); return; }
            var box = $('sup-cf-space-list');
            if (box) box.innerHTML = '<div class="kb-hint">Lade Bereiche…</div>';
            fetch('/api/confluence/spaces', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        if (box) box.innerHTML = '<div class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || 'Bereiche nicht ladbar (Confluence aktiv?)') + '</div>';
                        return;
                    }
                    self._cfSpaces = d.spaces || [];
                    self._renderSpaces();
                })
                .catch(function () {
                    if (box) box.innerHTML = '<div class="kb-hint" style="color:var(--danger);">Bereiche nicht ladbar.</div>';
                });
        },

        _renderSpaces: function () {
            var box = $('sup-cf-space-list');
            if (!box || !this._cfSpaces) return;
            var self = this;
            var q = ($('sup-cf-space-search') ? $('sup-cf-space-search').value : '').trim().toLowerCase();
            var inclPers = $('sup-cf-personal') ? $('sup-cf-personal').checked : false;
            var list = this._cfSpaces.filter(function (s) {
                if (!inclPers && s.type === 'personal') return false;
                if (q) { return ((s.name || '') + ' ' + (s.key || '')).toLowerCase().indexOf(q) !== -1; }
                return true;
            });
            var CAP = 300;
            box.innerHTML = '';
            list.slice(0, CAP).forEach(function (s) {
                var sel = !!self._cfSel[s.key];
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 8px;'
                    + 'border-radius:6px;cursor:pointer;font-size:0.85rem;'
                    + (sel ? 'background:rgba(var(--accent-rgb),.18);' : '');
                row.innerHTML = '<span style="width:16px;text-align:center;color:var(--accent-hover);">'
                    + (sel ? '✓' : '') + '</span><span style="flex:1;min-width:0;">' + esc(s.name)
                    + ' <span class="kb-hint">(' + esc(s.key) + ')</span></span>';
                row.addEventListener('click', function () {
                    if (self._cfSel[s.key]) delete self._cfSel[s.key];
                    else self._cfSel[s.key] = true;
                    self._renderSpaces();
                });
                box.appendChild(row);
            });
            if (list.length > CAP) {
                var more = document.createElement('div');
                more.className = 'kb-hint';
                more.textContent = '… ' + (list.length - CAP) + ' weitere – Suche eingrenzen';
                box.appendChild(more);
            }
            var cnt = Object.keys(self._cfSel).length;
            var selEl = $('sup-cf-selected');
            if (selEl) selEl.textContent = cnt + ' Bereich(e) gewählt';
        },

        save: function () {
            var lines = parseInt(($('support-lines') ? $('support-lines').value : '5'), 10);
            if (!lines || lines < 1) lines = 5;
            if (lines > 50) lines = 50;
            var rlines = parseInt(($('support-result-lines') ? $('support-result-lines').value : '2'), 10);
            if (!rlines || rlines < 1) rlines = 2;
            if (rlines > 50) rlines = 50;
            var jlimit = parseInt(($('support-jira-limit') ? $('support-jira-limit').value : '12'), 10);
            if (!jlimit || jlimit < 1) jlimit = 12;
            if (jlimit > 1000) jlimit = 1000;
            var body = {
                system_prompt: ($('support-prompt') ? $('support-prompt').value : ''),
                summary_lines: lines,
                result_lines: rlines,
                jira_limit: jlimit,
                conf_filter_mode: this._cfMode || 'off',
                conf_spaces: Object.keys(this._cfSel || {})
            };
            status('Speichere…');
            fetch('/api/skills/support_assistant/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json(); })
              .then(function () { status('✓ Gespeichert', 'ok'); })
              .catch(function () { status('✗ Fehler beim Speichern', 'error'); });
        }
    };

    window.SupportAdminManager = Manager;
})();
