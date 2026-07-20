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

    var SVG_EYE_OPEN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
    var SVG_EYE_CLOSED = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';

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
            var test = $('kv-test'); if (test) test.addEventListener('click', this.test.bind(this));
            var sb = $('kv-search-btn'); if (sb) sb.addEventListener('click', this.search.bind(this));
            var inp = $('kv-search-buzzwords');
            if (inp) inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') Manager.search(); });
            // Auge: API-Key anzeigen/verbergen (analog Confluence-Reiter)
            var tt = $('kv-key-toggle');
            if (tt) tt.addEventListener('click', function () {
                var el = $('ibs-api-key'); if (!el) return;
                var hidden = el.type === 'password';
                el.type = hidden ? 'text' : 'password';
                tt.innerHTML = hidden ? SVG_EYE_CLOSED : SVG_EYE_OPEN;
            });
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

        // Erreichbarkeits-Test der IBS-API (jede HTTP-Antwort = erreichbar)
        test: function () {
            status('Teste Verbindung…');
            fetch('/api/kundenverwaltung/test', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || (!d.ok && d.configured === false)) {
                        status('Nicht konfiguriert – bitte zuerst URL speichern.', 'error');
                    } else if (!d.ok) {
                        status('❌ ' + (d.error || 'Nicht erreichbar'), 'error');
                    } else {
                        var msg = '✅ Erreichbar (HTTP ' + d.status + ')';
                        if (!d.key_set) msg += ' – API-Key fehlt noch';
                        else if (d.status === 401 || d.status === 403) msg = '⚠️ Erreichbar, aber HTTP ' + d.status + ' – API-Key prüfen';
                        status(msg, (d.status === 401 || d.status === 403 || !d.key_set) ? '' : 'ok');
                    }
                })
                .catch(function () { status('❌ Verbindungstest fehlgeschlagen', 'error'); });
        },

        // Ticketsuche ueber /api/kundenverwaltung/tickets-by-buzzwords
        // (serverseitig API-Funktion 'getMatchingEvents')
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
            var addr = ($('kv-search-address') ? $('kv-search-address').value : '').trim();
            box.innerHTML = '<span class="kb-hint">Suche…</span>';
            fetch('/api/kundenverwaltung/tickets-by-buzzwords?buzzwords=' + encodeURIComponent(buzz)
                    + '&limit=' + limit
                    + (addr ? '&address_id=' + encodeURIComponent(addr) : ''),
                    { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || 'Suche fehlgeschlagen') + '</span>';
                        return;
                    }
                    var res = d.tickets || [];
                    box.innerHTML = '<div class="kb-hint" style="margin:8px 0 4px;">' + res.length
                        + ' Treffer für Schlagworte: ' + esc((d.terms || []).join(', '))
                        + (d.address_id ? ' · Adress-ID: ' + esc(d.address_id) : '') + '</div>';
                    res.forEach(function (t) {
                        var row = document.createElement('div');
                        row.style.cssText = 'display:flex;flex-direction:column;gap:4px;'
                            + 'padding:10px 12px;border:1px solid var(--border);'
                            + 'border-radius:8px;background:var(--bg-glass);';
                        // Kopfzeile: ID · Status · geaendert am
                        var meta = [];
                        if (t.status) meta.push(esc(t.status));
                        if (t.updated) meta.push(esc(t.updated));
                        if (t.dispatch_user) meta.push(esc(t.dispatch_user));
                        var head = '<div style="display:flex;justify-content:space-between;'
                            + 'gap:10px;align-items:baseline;">'
                            + '<span style="font-weight:600;">#' + esc(t.key || '—') + '</span>'
                            + '<span class="kb-hint" style="white-space:nowrap;">' + meta.join(' · ') + '</span>'
                            + '</div>';
                        // Volltext (mehrzeilige Verlaufshistorie) lesbar mit Umbruechen
                        var full = (t.text || t.title || '');
                        var bodyHtml = '<div style="white-space:pre-wrap;word-break:break-word;'
                            + 'font-size:0.88rem;line-height:1.45;">' + esc(full) + '</div>';
                        row.innerHTML = head + bodyHtml;
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
