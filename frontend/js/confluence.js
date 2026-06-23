/* ═══════════════════════════════════════════════════════════════════
   Confluence-Reiter (Einstellungen)
   ───────────────────────────────────────────────────────────────────
   Verbindungskonfiguration (URL/Benutzer/Token), Verbindungstest und
   eine einfache Such-/Lese-Oberflaeche. Schreiboperationen (Seiten anlegen
   /aendern/kommentieren, Anhaenge) laufen ueber die Agent-Tools des Skills.
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
    function status(msg, kind) {
        var el = $('cf-status'); if (!el) return;
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
            var save = $('cf-save'); if (save) save.addEventListener('click', this.save.bind(this));
            var test = $('cf-test'); if (test) test.addEventListener('click', this.test.bind(this));
            var sb = $('cf-search-btn'); if (sb) sb.addEventListener('click', this.search.bind(this));
            var q = $('cf-search-q');
            if (q) q.addEventListener('keydown', function (e) { if (e.key === 'Enter') Manager.search(); });
        },

        loadConfig: function () {
            fetch('/api/skills/confluence/config', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    if ($('cf-url')) $('cf-url').value = c.base_url || '';
                    if ($('cf-token')) $('cf-token').value = c.api_token || '';
                })
                .catch(function () {});
        },

        save: function () {
            var body = {
                base_url: ($('cf-url') ? $('cf-url').value : '').trim(),
                user: '',  // Server/DC: PAT als Bearer -> kein Benutzer noetig
                api_token: ($('cf-token') ? $('cf-token').value : '').trim()
            };
            status('Speichere…');
            fetch('/api/skills/confluence/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json(); })
              .then(function () { status('✓ Gespeichert', 'ok'); })
              .catch(function () { status('✗ Fehler beim Speichern', 'error'); });
        },

        test: function () {
            status('Teste Verbindung…');
            fetch('/api/confluence/test', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d && d.ok) {
                        status('✅ Verbunden (' + d.count + ' Space(s))', 'ok');
                    } else if (d && d.configured === false) {
                        status('Nicht konfiguriert – bitte zuerst speichern.', 'error');
                    } else {
                        status('❌ ' + ((d && d.error) || 'Verbindung fehlgeschlagen'), 'error');
                    }
                })
                .catch(function () { status('❌ Verbindungstest fehlgeschlagen', 'error'); });
        },

        search: function () {
            var q = ($('cf-search-q') ? $('cf-search-q').value : '').trim();
            var space = ($('cf-search-space') ? $('cf-search-space').value : '').trim();
            var box = $('cf-results');
            if (!box) return;
            box.innerHTML = '<span class="kb-hint">Suche…</span>';
            if ($('cf-page-view')) $('cf-page-view').style.display = 'none';
            var url = '/api/confluence/search?limit=20&q=' + encodeURIComponent(q)
                + '&space=' + encodeURIComponent(space);
            fetch(url, { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || 'Suche fehlgeschlagen') + '</span>';
                        return;
                    }
                    var res = d.results || [];
                    if (!res.length) { box.innerHTML = '<span class="kb-hint">Keine Treffer.</span>'; return; }
                    box.innerHTML = '';
                    res.forEach(function (r) {
                        var row = document.createElement('div');
                        row.className = 'cf-result-row';
                        row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;'
                            + 'gap:10px;padding:8px 10px;border:1px solid var(--border);border-radius:8px;'
                            + 'cursor:pointer;background:var(--bg-glass);';
                        row.innerHTML = '<span>' + esc(r.title) + ' <span class="kb-hint">(ID '
                            + esc(r.id) + ')</span></span>'
                            + (r.link ? '<a href="' + esc(r.link) + '" target="_blank" rel="noopener" '
                                + 'class="kb-hint" onclick="event.stopPropagation()" '
                                + 'style="white-space:nowrap;">↗</a>' : '');
                        row.addEventListener('click', function () { Manager.viewPage(r.id); });
                        box.appendChild(row);
                    });
                })
                .catch(function () { box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">Suche fehlgeschlagen</span>'; });
        },

        viewPage: function (id) {
            var view = $('cf-page-view'); if (!view) return;
            view.style.display = '';
            if ($('cf-page-title')) $('cf-page-title').textContent = 'Lade…';
            if ($('cf-page-text')) $('cf-page-text').textContent = '';
            fetch('/api/confluence/page?id=' + encodeURIComponent(id), { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        if ($('cf-page-title')) $('cf-page-title').textContent = 'Fehler';
                        if ($('cf-page-text')) $('cf-page-text').textContent = (d && d.error) || 'Seite konnte nicht geladen werden.';
                        return;
                    }
                    if ($('cf-page-title')) $('cf-page-title').textContent = d.title + ' (Space ' + (d.space || '?') + ')';
                    var link = $('cf-page-link');
                    if (link) { if (d.link) { link.href = d.link; link.style.display = ''; } else { link.style.display = 'none'; } }
                    if ($('cf-page-text')) $('cf-page-text').textContent = d.text || '(kein Textinhalt)';
                })
                .catch(function () {
                    if ($('cf-page-title')) $('cf-page-title').textContent = 'Fehler';
                });
        }
    };

    window.ConfluenceManager = Manager;
})();
