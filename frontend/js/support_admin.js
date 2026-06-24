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
                })
                .catch(function () {});
        },

        save: function () {
            var body = { system_prompt: ($('support-prompt') ? $('support-prompt').value : '') };
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
