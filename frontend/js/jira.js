/* ═══════════════════════════════════════════════════════════════════
   Jira-Reiter (Einstellungen) – Schwerpunkt Ticketsuche
   ───────────────────────────────────────────────────────────────────
   Verbindungskonfiguration (URL/Token), Verbindungstest und eine
   Such-/Leseoberflaeche fuer Tickets (Volltext + optionale Filter / JQL).
   Schreiboperationen (Kommentar, Ticket anlegen) laufen ueber die
   Agent-Tools des Skills.
   ═══════════════════════════════════════════════════════════════════ */
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
    // Jira liefert ISO-8601-Strings (z.B. "2024-03-15T10:30:00.000+0100").
    // Festes Format tt.mm.jjjj HH:MM (24h, null-gepolstert); leer/ungueltig -> ''.
    function fmtDate(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        function p(n) { return (n < 10 ? '0' : '') + n; }
        return p(d.getDate()) + '.' + p(d.getMonth() + 1) + '.' + d.getFullYear()
            + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    }
    function status(msg, kind) {
        var el = $('jira-status'); if (!el) return;
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
            var save = $('jira-save'); if (save) save.addEventListener('click', this.save.bind(this));
            var test = $('jira-test'); if (test) test.addEventListener('click', this.test.bind(this));
            var sb = $('jira-search-btn'); if (sb) sb.addEventListener('click', this.search.bind(this));
            ['jira-search-q', 'jira-search-project', 'jira-search-jql'].forEach(function (id) {
                var el = $(id);
                if (el) el.addEventListener('keydown', function (e) { if (e.key === 'Enter') Manager.search(); });
            });
        },

        loadConfig: function () {
            fetch('/api/skills/jira/config', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    if ($('jira-url')) $('jira-url').value = c.base_url || '';
                    if ($('jira-token')) $('jira-token').value = c.api_token || '';
                    if ($('ibs-api-url')) $('ibs-api-url').value = c.ibs_api_url || '';
                    if ($('ibs-api-key')) $('ibs-api-key').value = c.ibs_api_key || '';
                    if ($('jira-max-results')) $('jira-max-results').value = c.max_results || 50;
                })
                .catch(function () {});
        },

        save: function () {
            var mr = parseInt(($('jira-max-results') ? $('jira-max-results').value : '') || '50', 10);
            if (isNaN(mr) || mr < 1) mr = 50;
            if (mr > 1000) mr = 1000;
            var body = {
                base_url: ($('jira-url') ? $('jira-url').value : '').trim(),
                api_token: ($('jira-token') ? $('jira-token').value : '').trim(),
                ibs_api_url: ($('ibs-api-url') ? $('ibs-api-url').value : '').trim(),
                ibs_api_key: ($('ibs-api-key') ? $('ibs-api-key').value : '').trim(),
                max_results: mr
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

        test: function () {
            status('Teste Verbindung…');
            fetch('/api/jira/test', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d && d.ok) {
                        status('✅ Verbunden als ' + (d.user || '?'), 'ok');
                    } else if (d && d.configured === false) {
                        status('Nicht konfiguriert – bitte zuerst speichern.', 'error');
                    } else {
                        status('❌ ' + ((d && d.error) || 'Verbindung fehlgeschlagen'), 'error');
                    }
                })
                .catch(function () { status('❌ Verbindungstest fehlgeschlagen', 'error'); });
        },

        search: function () {
            var q = ($('jira-search-q') ? $('jira-search-q').value : '').trim();
            var project = ($('jira-search-project') ? $('jira-search-project').value : '').trim();
            var jql = ($('jira-search-jql') ? $('jira-search-jql').value : '').trim();
            var box = $('jira-results');
            if (!box) return;
            box.innerHTML = '<span class="kb-hint">Suche…</span>';
            if ($('jira-issue-view')) $('jira-issue-view').style.display = 'none';
            var url = '/api/jira/search?limit=25'
                + '&q=' + encodeURIComponent(q)
                + '&project=' + encodeURIComponent(project)
                + '&jql=' + encodeURIComponent(jql);
            fetch(url, { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || 'Suche fehlgeschlagen') + '</span>';
                        return;
                    }
                    var res = d.results || [];
                    var head = '<div class="kb-hint" style="margin-bottom:8px;">' + (d.total || res.length)
                        + ' Treffer · <code>' + esc(d.jql || '') + '</code></div>';
                    if (!res.length) { box.innerHTML = head + '<span class="kb-hint">Keine Tickets.</span>'; return; }
                    box.innerHTML = head;
                    res.forEach(function (r) {
                        var row = document.createElement('div');
                        row.className = 'jira-result-row';
                        row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;'
                            + 'gap:10px;padding:8px 10px;margin-bottom:6px;border:1px solid var(--border);'
                            + 'border-radius:8px;cursor:pointer;background:var(--bg-glass);';
                        var rC = fmtDate(r.created), rU = fmtDate(r.updated);
                        var meta = [r.status, r.type, r.priority ? ('Prio ' + r.priority) : '',
                                    r.assignee ? ('→ ' + r.assignee) : '',
                                    rC ? ('Erstellt ' + rC) : '',
                                    rU ? ('Geändert ' + rU) : ''].filter(Boolean).join(' · ');
                        row.innerHTML = '<span style="min-width:0;"><span style="font-weight:600;">'
                            + esc(r.key) + '</span> ' + esc(r.summary || '')
                            + '<br><span class="kb-hint">' + esc(meta) + '</span></span>'
                            + (r.link ? '<a href="' + esc(r.link) + '" target="_blank" rel="noopener" '
                                + 'class="kb-hint" onclick="event.stopPropagation()" '
                                + 'style="white-space:nowrap;">↗</a>' : '');
                        row.addEventListener('click', function () { Manager.viewIssue(r.key); });
                        box.appendChild(row);
                    });
                })
                .catch(function () { box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">Suche fehlgeschlagen</span>'; });
        },

        viewIssue: function (key) {
            var view = $('jira-issue-view'); if (!view) return;
            view.style.display = '';
            if ($('jira-issue-title')) $('jira-issue-title').textContent = 'Lade…';
            if ($('jira-issue-text')) $('jira-issue-text').textContent = '';
            if ($('jira-issue-comments')) $('jira-issue-comments').innerHTML = '';
            fetch('/api/jira/issue?key=' + encodeURIComponent(key), { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        if ($('jira-issue-title')) $('jira-issue-title').textContent = 'Fehler';
                        if ($('jira-issue-text')) $('jira-issue-text').textContent = (d && d.error) || 'Ticket konnte nicht geladen werden.';
                        return;
                    }
                    var dC = fmtDate(d.created), dU = fmtDate(d.updated);
                    var meta = [d.status, d.type, d.priority ? ('Prio ' + d.priority) : '',
                                d.assignee ? ('Bearbeiter: ' + d.assignee) : '',
                                dC ? ('Erstellt: ' + dC) : '',
                                dU ? ('Geändert: ' + dU) : ''].filter(Boolean).join(' · ');
                    if ($('jira-issue-title')) $('jira-issue-title').textContent = d.key + ' — ' + (d.summary || '');
                    if ($('jira-issue-meta')) $('jira-issue-meta').textContent = meta;
                    var link = $('jira-issue-link');
                    if (link) { if (d.link) { link.href = d.link; link.style.display = ''; } else { link.style.display = 'none'; } }
                    if ($('jira-issue-text')) $('jira-issue-text').textContent = d.description || '(keine Beschreibung)';
                    var cbox = $('jira-issue-comments');
                    if (cbox) {
                        var cs = d.comments || [];
                        cbox.innerHTML = cs.length ? ('<div class="kb-hint" style="margin:10px 0 4px;">💬 '
                            + cs.length + ' Kommentar(e):</div>') : '';
                        cs.forEach(function (cm) {
                            var el = document.createElement('div');
                            el.style.cssText = 'border-left:3px solid var(--accent);padding:4px 10px;margin:6px 0;'
                                + 'background:rgba(var(--accent-rgb),.06);border-radius:0 6px 6px 0;';
                            el.innerHTML = '<div style="font-weight:600;font-size:.82rem;">' + esc(cm.author || '?')
                                + '</div><div style="white-space:pre-wrap;font-size:.85rem;">' + esc(cm.body || '') + '</div>';
                            cbox.appendChild(el);
                        });
                    }
                })
                .catch(function () {
                    if ($('jira-issue-title')) $('jira-issue-title').textContent = 'Fehler';
                });
        }
    };

    window.JiraManager = Manager;
})();
