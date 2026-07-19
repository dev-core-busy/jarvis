/* ═══════════════════════════════════════════════════════════════════
   Kundenverwaltungs-Reiter (Einstellungen)
   ───────────────────────────────────────────────────────────────────
   Konfiguration der Kundenverwaltungs-(IBS-)API. Die CRM-Auswertungs-
   Tools des Skills nutzen die Jira-Verbindung aus dem Jira-Reiter;
   die IBS-Felder liegen (rueckwaerts-kompatibel) im Config-Store des
   Jira-Skills unter ibs_api_url/ibs_api_key – der Speichern-Button
   schreibt NUR diese Teilschluessel (Config-Merge im Backend).
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    function status(msg, kind) {
        var el = $('kv-status'); if (!el) return;
        el.textContent = msg || '';
        el.style.color = kind === 'error' ? 'var(--danger)'
            : kind === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
    }

    var Manager = {
        _bound: false,

        onShow: function () {
            this._bind();
            this.loadConfig();
        },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            var save = $('kv-save'); if (save) save.addEventListener('click', this.save.bind(this));
        },

        loadConfig: function () {
            fetch('/api/skills/jira/config', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    if ($('ibs-api-url')) $('ibs-api-url').value = c.ibs_api_url || '';
                    if ($('ibs-api-key')) $('ibs-api-key').value = c.ibs_api_key || '';
                })
                .catch(function () {});
        },

        save: function () {
            var body = {
                ibs_api_url: ($('ibs-api-url') ? $('ibs-api-url').value : '').trim(),
                ibs_api_key: ($('ibs-api-key') ? $('ibs-api-key').value : '').trim()
            };
            status('Speichere…');
            fetch('/api/skills/jira/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json(); })
              .then(function () { status('✓ Gespeichert', 'ok'); })
              .catch(function () { status('✗ Fehler beim Speichern', 'error'); });
        }
    };

    window.KundenverwaltungManager = Manager;
})();
