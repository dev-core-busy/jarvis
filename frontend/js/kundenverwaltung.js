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
            var sb = $('kv-search-btn'); if (sb) sb.addEventListener('click', this.search.bind(this));
            var inp = $('kv-search-buzzwords');
            if (inp) inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') Manager.search(); });
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
        },

        // Dummy-Ticketsuche ueber /api/kundenverwaltung/tickets-by-buzzwords
        search: function () {
            var box = $('kv-search-results');
            if (!box) return;
            var esc = function (s) {
                return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
                    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
                });
            };
            var buzz = ($('kv-search-buzzwords') ? $('kv-search-buzzwords').value : '').trim();
            if (!buzz) {
                box.innerHTML = '<span class="kb-hint">Bitte Schlagworte eingeben (kommagetrennt).</span>';
                return;
            }
            var limit = parseInt(($('kv-search-limit') ? $('kv-search-limit').value : '') || '25', 10);
            if (isNaN(limit) || limit < 1) limit = 25;
            if (limit > 100) limit = 100;
            box.innerHTML = '<span class="kb-hint">Suche…</span>';
            fetch('/api/kundenverwaltung/tickets-by-buzzwords?buzzwords=' + encodeURIComponent(buzz)
                    + '&limit=' + limit, { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || 'Suche fehlgeschlagen') + '</span>';
                        return;
                    }
                    var head = '';
                    if (d.dummy) {
                        head += '<div class="kb-hint" style="border:1px solid var(--border);'
                            + 'border-radius:8px;padding:8px 10px;background:var(--bg-glass);">'
                            + '⚠️ <strong>Dummy-Antwort</strong> – die API-Funktion „tickets-by-buzzwords" '
                            + 'ist noch nicht verfügbar. Geplanter Aufruf:<br>'
                            + '<code style="word-break:break-all;">GET ' + esc(d.planned || '') + '</code></div>';
                    }
                    var res = d.tickets || [];
                    head += '<div class="kb-hint" style="margin:8px 0 4px;">' + res.length
                        + ' Beispieldaten für Schlagworte: ' + esc((d.terms || []).join(', ')) + '</div>';
                    box.innerHTML = head;
                    res.forEach(function (t) {
                        var row = document.createElement('div');
                        row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;'
                            + 'gap:10px;padding:8px 10px;border:1px solid var(--border);'
                            + 'border-radius:8px;background:var(--bg-glass);';
                        row.innerHTML = '<span style="min-width:0;"><span style="font-weight:600;">'
                            + esc(t.key) + '</span> ' + esc(t.title || '')
                            + '</span><span class="kb-hint" style="white-space:nowrap;">' + esc(t.status || '') + '</span>';
                        box.appendChild(row);
                    });
                })
                .catch(function () {
                    box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">Suche fehlgeschlagen</span>';
                });
        }
    };

    window.KundenverwaltungManager = Manager;
})();
