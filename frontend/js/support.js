/* Support-Assistent – Seitenlogik (/support)
   Login (Token-Fallback), Status (Jira-Checkbox), Suche + Ergebnis-Rendering. */
(function () {
    'use strict';

    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            var v = localStorage.getItem(TOKEN_KEYS[i]);
            if (v) return v;
        }
        return '';
    }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    function showApp() {
        $('sup-login').classList.add('hidden');
        $('sup-app').classList.remove('hidden');
        loadStatus();
        bind();
        if (window.refreshBranding) try { window.refreshBranding(); } catch (e) {}
    }

    function loadStatus() {
        fetch('/api/support/status', { headers: authHeaders() })
            .then(function (r) { if (r.status === 401) { logout(); return null; } return r.json(); })
            .then(function (d) {
                if (!d) return;
                if (d.jira_active) $('sup-opt-jira-wrap').classList.remove('hidden');
                else $('sup-opt-jira-wrap').classList.add('hidden');
            })
            .catch(function () {});
    }

    function logout() {
        TOKEN_KEYS.forEach(function (k) { localStorage.removeItem(k); });
        $('sup-app').classList.add('hidden');
        $('sup-login').classList.remove('hidden');
    }

    var _bound = false;
    function bind() {
        if (_bound) return; _bound = true;
        $('sup-search-btn').addEventListener('click', search);
        $('sup-input').addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); search(); }
        });
    }

    function search() {
        var text = ($('sup-input').value || '').trim();
        if (!text) { $('sup-input').focus(); return; }
        var jiraWrap = $('sup-opt-jira-wrap');
        var useJira = !jiraWrap.classList.contains('hidden') && $('sup-opt-jira').checked;
        var useRag = $('sup-opt-rag').checked;

        var btn = $('sup-search-btn'); btn.disabled = true;
        var meta = $('sup-meta'); meta.classList.remove('hidden');
        meta.innerHTML = '<span class="sup-spinner"></span>Suche läuft…';
        var box = $('sup-results');
        box.innerHTML = '<div class="sup-ai-card"><div class="sup-ai-label">KI-Zusammenfassung</div>'
            + '<div class="sup-ai-text"><span class="sup-spinner"></span>Quellen werden ausgewertet…</div></div>';

        fetch('/api/support/query', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ text: text, jira: useJira, rag: useRag })
        })
            .then(function (r) { if (r.status === 401) { logout(); return null; } return r.json(); })
            .then(function (d) {
                btn.disabled = false;
                if (!d) return;
                if (!d.ok) {
                    meta.textContent = '';
                    box.innerHTML = '<div class="sup-empty">' + esc(d.error || 'Suche fehlgeschlagen') + '</div>';
                    return;
                }
                render(d);
            })
            .catch(function () {
                btn.disabled = false;
                meta.textContent = '';
                box.innerHTML = '<div class="sup-empty">Suche fehlgeschlagen.</div>';
            });
    }

    function render(d) {
        var blocks = d.blocks || [];
        $('sup-meta').innerHTML = 'Ergebnis für <strong>"' + esc(d.query) + '"</strong> ('
            + blocks.length + ' Treffer in ' + (d.took_ms || 0) + ' ms)';
        var html = '';
        // KI-Zusammenfassung
        if (d.ai_summary) {
            html += '<div class="sup-ai-card"><div class="sup-ai-label">KI-Zusammenfassung</div>'
                + '<div class="sup-ai-text">' + esc(d.ai_summary) + '</div></div>';
        }
        if (!blocks.length) {
            html += '<div class="sup-empty">Keine passenden Quellen gefunden.</div>';
            $('sup-results').innerHTML = html;
            return;
        }
        blocks.forEach(function (b, i) {
            html += '<div class="sup-block">'
                + '<div class="sup-block-head">'
                + '<span class="sup-block-num">' + (i + 1) + '.</span>'
                + '<span class="sup-block-title">' + esc(b.title) + '</span>'
                + '<span class="sup-badge-src">' + esc(b.source) + '</span>'
                + '<span class="sup-badge-score" title="Zutreffend">' + b.score + '%</span>'
                + '</div>'
                + '<div class="sup-block-body">' + esc(b.summary) + '</div>'
                + (b.link ? '<a class="sup-block-link" href="' + esc(b.link)
                    + '" target="_blank" rel="noopener">Öffnen ↗</a>' : '')
                + '</div>';
        });
        $('sup-results').innerHTML = html;
    }

    // ── Login ──
    function bindLogin() {
        $('sup-login-form').addEventListener('submit', function (e) {
            e.preventDefault();
            var u = $('sup-login-user').value.trim();
            var p = $('sup-login-pass').value;
            $('sup-login-err').textContent = '';
            fetch('/api/login', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: u, password: p })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d && d.success && d.token) {
                      localStorage.setItem('jarvis_token', d.token);
                      showApp();
                  } else {
                      $('sup-login-err').textContent = (d && d.error) || 'Anmeldung fehlgeschlagen';
                  }
              })
              .catch(function () { $('sup-login-err').textContent = 'Netzwerkfehler'; });
        });
    }

    // ── Init ──
    bindLogin();
    if (token()) showApp();
    else $('sup-login').classList.remove('hidden');
})();
