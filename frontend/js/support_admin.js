/* Support-Assistent – Konfigurationsreiter (Einstellungen)
   Lädt/speichert das vorangestellte LLM-Prompt in der Skill-Config. */
(function () {
    'use strict';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    function status(msg, kind) {
        var el = $('support-status'); if (!el) return;
        el.textContent = msg || '';
        el.style.color = kind === 'error' ? 'var(--danger)'
            : kind === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
    }

    var Manager = {
        _bound: false,
        onShow: function () { this._bind(); this.loadConfig(); },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            var save = $('support-save');
            if (save) save.addEventListener('click', this.save.bind(this));
        },

        loadConfig: function () {
            fetch('/api/skills/support_assistant/config', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    if ($('support-prompt')) $('support-prompt').value = c.system_prompt || '';
                    if ($('support-lines')) $('support-lines').value = c.summary_lines || 5;
                    if ($('support-result-lines')) $('support-result-lines').value = c.result_lines || 2;
                })
                .catch(function () {});
        },

        save: function () {
            var lines = parseInt(($('support-lines') ? $('support-lines').value : '5'), 10);
            if (!lines || lines < 1) lines = 5;
            if (lines > 20) lines = 20;
            var rlines = parseInt(($('support-result-lines') ? $('support-result-lines').value : '2'), 10);
            if (!rlines || rlines < 1) rlines = 2;
            if (rlines > 20) rlines = 20;
            var body = {
                system_prompt: ($('support-prompt') ? $('support-prompt').value : ''),
                summary_lines: lines,
                result_lines: rlines
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
