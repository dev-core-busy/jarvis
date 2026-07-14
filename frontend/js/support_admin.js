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
            // API-Hilfe-Modal (REST-Zugriffe)
            var helpBtn = $('support-api-help-btn');
            if (helpBtn) helpBtn.addEventListener('click', function () { self._apiHelp(true); });
            var helpClose = $('support-api-close');
            if (helpClose) helpClose.addEventListener('click', function () { self._apiHelp(false); });
            // "PDF"-Button: Doku via Druckdialog als PDF speichern (an PDF-Drucker drucken).
            // body.printing-apidoc blendet per @media print alles ausser dem Modal aus.
            var pdfBtn = $('support-api-pdf');
            if (pdfBtn) pdfBtn.addEventListener('click', function () {
                document.body.classList.add('printing-apidoc');
                var cleanup = function () {
                    document.body.classList.remove('printing-apidoc');
                    window.removeEventListener('afterprint', cleanup);
                };
                window.addEventListener('afterprint', cleanup);
                try { window.print(); } catch (e) { cleanup(); }
            });
            var helpModal = $('support-api-modal');
            if (helpModal) helpModal.addEventListener('click', function (e) {
                if (e.target === helpModal) self._apiHelp(false);
            });
            document.addEventListener('keydown', function (e) {
                if (e.key === 'Escape' && helpModal && helpModal.classList.contains('open')) self._apiHelp(false);
            });
        },

        _apiHelp: function (show) {
            var m = $('support-api-modal');
            if (m) m.classList.toggle('open', !!show);
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
                    if ($('support-jira-limit')) $('support-jira-limit').value = c.jira_limit || 12;
                    if ($('support-rag-results')) $('support-rag-results').value = c.rag_results || 8;
                    if ($('support-confluence-results')) $('support-confluence-results').value = c.confluence_results || 6;
                    if ($('support-summary-sources')) $('support-summary-sources').value = c.summary_sources || 10;
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
                            + esc((d && d.error) || window.t('support_admin.areas_unloadable_hint')) + '</div>';
                        return;
                    }
                    self._cfSpaces = d.spaces || [];
                    self._renderSpaces();
                })
                .catch(function () {
                    if (box) box.innerHTML = '<div class="kb-hint" style="color:var(--danger);">' + window.t('support_admin.areas_unloadable') + '</div>';
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
            var jlimit = parseInt(($('support-jira-limit') ? $('support-jira-limit').value : '12'), 10);
            if (!jlimit || jlimit < 1) jlimit = 12;
            if (jlimit > 1000) jlimit = 1000;
            function _cnt(id, def) {
                var v = parseInt(($(id) ? $(id).value : '') || String(def), 10);
                if (!v || v < 1) v = def;
                if (v > 50) v = 50;
                return v;
            }
            var rag = _cnt('support-rag-results', 8);
            var conf = _cnt('support-confluence-results', 6);
            var ssrc = _cnt('support-summary-sources', 10);
            var body = {
                system_prompt: ($('support-prompt') ? $('support-prompt').value : ''),
                summary_lines: lines,
                jira_limit: jlimit,
                rag_results: rag,
                confluence_results: conf,
                summary_sources: ssrc,
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
