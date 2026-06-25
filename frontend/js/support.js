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
    // Escapen + http(s)-URLs als klickbare Links umwandeln
    function escLink(s) {
        return esc(s).replace(/(https?:\/\/[^\s<]+)/g, function (u) {
            var tail = '';
            var m = u.match(/[)\].,;:!?]+$/);
            if (m) { tail = m[0]; u = u.slice(0, -tail.length); }
            return '<a href="' + u + '" target="_blank" rel="noopener" '
                + 'style="color:var(--accent-hover);word-break:break-all;">' + u + '</a>' + tail;
        });
    }

    function showApp() {
        $('sup-login').classList.add('hidden');
        $('sup-app').classList.remove('hidden');
        loadStatus();
        bind();
        if (window.refreshBranding) try { window.refreshBranding(); } catch (e) {}
    }

    // ── Checkbox-Vorbelegung pro Browser/Session merken ──
    function getPref(key) {
        var v = localStorage.getItem('jarvis_support_' + key);
        return v === null ? true : v === '1';  // Default: an
    }
    function setPref(key, on) {
        localStorage.setItem('jarvis_support_' + key, on ? '1' : '0');
    }

    function loadStatus() {
        fetch('/api/support/status', { headers: authHeaders() })
            .then(function (r) { if (r.status === 401) { logout(); return null; } return r.json(); })
            .then(function (d) {
                if (!d) return;
                // Sichtbarkeit je nach aktivem Skill
                $('sup-opt-jira-wrap').classList.toggle('hidden', !d.jira_active);
                $('sup-opt-conf-wrap').classList.toggle('hidden', !d.confluence_active);
                // Gespeicherte Vorbelegung anwenden (Default: an)
                $('sup-opt-jira').checked = getPref('jira');
                $('sup-opt-conf').checked = getPref('conf');
                $('sup-opt-rag').checked = getPref('rag');
                $('sup-opt-ai').checked = getPref('ai');
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
        // Checkbox-Werte als Vorbelegung fuer die naechste Session merken
        $('sup-opt-jira').addEventListener('change', function () { setPref('jira', this.checked); });
        $('sup-opt-conf').addEventListener('change', function () { setPref('conf', this.checked); });
        $('sup-opt-rag').addEventListener('change', function () { setPref('rag', this.checked); });
        $('sup-opt-ai').addEventListener('change', function () { setPref('ai', this.checked); });
        // Eingrenzungs-Pulldowns → Ergebnis live neu filtern (clientseitig)
        ['sup-f-source', 'sup-f-rel', 'sup-f-sort', 'sup-f-limit'].forEach(function (id) {
            var el = $(id);
            if (el) el.addEventListener('change', renderBlocks);
        });
        // Verlauf (benutzerabhaengig)
        $('sup-hist-btn').addEventListener('click', function (e) {
            e.stopPropagation();
            var panel = $('sup-hist-panel');
            if (panel.classList.contains('hidden')) { loadHistory(); panel.classList.remove('hidden'); }
            else panel.classList.add('hidden');
        });
        $('sup-hist-clear').addEventListener('click', clearHistory);
        document.addEventListener('click', function (e) {
            var w = document.querySelector('.sup-hist-wrap');
            if (w && !w.contains(e.target)) $('sup-hist-panel').classList.add('hidden');
        });
        // Dokument-Viewer (lokale Wissensquellen)
        $('sup-results').addEventListener('click', function (e) {
            var a = e.target.closest ? e.target.closest('.sup-doc-link') : null;
            if (a) { e.preventDefault(); openDoc(a.getAttribute('data-doc'), a.getAttribute('data-label')); }
        });
        $('sup-doc-close').addEventListener('click', closeDoc);
        $('sup-doc-modal').addEventListener('click', function (e) { if (e.target === this) closeDoc(); });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeDoc(); });
    }

    function closeDoc() { $('sup-doc-modal').classList.add('hidden'); }

    function openDoc(path, label) {
        var modal = $('sup-doc-modal');
        $('sup-doc-title').textContent = label || 'Dokument';
        $('sup-doc-body').innerHTML = '<span class="sup-spinner"></span> Lade…';
        modal.classList.remove('hidden');
        fetch('/api/knowledge/file_read?path=' + encodeURIComponent(path), { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) {
                    $('sup-doc-body').textContent = (d && d.error) || 'Dokument konnte nicht geladen werden.';
                    return;
                }
                var content = d.content || '';
                // JSON hübsch formatieren, falls parsebar
                try { content = JSON.stringify(JSON.parse(content), null, 2); } catch (e) {}
                $('sup-doc-body').innerHTML = escLink(content);
            })
            .catch(function () { $('sup-doc-body').textContent = 'Dokument konnte nicht geladen werden.'; });
    }

    function relTime(ts) {
        var diff = Math.floor(Date.now() / 1000) - (ts || 0);
        if (diff < 60) return 'gerade eben';
        if (diff < 3600) return 'vor ' + Math.floor(diff / 60) + ' Min';
        if (diff < 86400) return 'vor ' + Math.floor(diff / 3600) + ' Std';
        if (diff < 604800) return 'vor ' + Math.floor(diff / 86400) + ' Tg';
        try { return new Date(ts * 1000).toLocaleDateString(); } catch (e) { return ''; }
    }

    function loadHistory() {
        var list = $('sup-hist-list');
        list.innerHTML = '<div class="sup-hist-empty"><span class="sup-spinner"></span></div>';
        fetch('/api/support/history', { headers: authHeaders() })
            .then(function (r) { if (r.status === 401) { logout(); return null; } return r.json(); })
            .then(function (d) {
                if (!d) return;
                var entries = (d && d.entries) || [];
                if (!entries.length) { list.innerHTML = '<div class="sup-hist-empty">Noch keine Anfragen.</div>'; return; }
                list.innerHTML = '';
                entries.forEach(function (e) {
                    var item = document.createElement('div');
                    item.className = 'sup-hist-item';
                    item.innerHTML = '<div class="sup-hist-q">' + esc(e.query) + '</div>'
                        + '<div class="sup-hist-meta">' + relTime(e.ts)
                        + (typeof e.total === 'number' ? ' · ' + e.total + ' Treffer' : '') + '</div>';
                    item.addEventListener('click', function () {
                        $('sup-hist-panel').classList.add('hidden');
                        $('sup-input').value = e.query;
                        search();
                    });
                    list.appendChild(item);
                });
            })
            .catch(function () { list.innerHTML = '<div class="sup-hist-empty">Fehler beim Laden.</div>'; });
    }

    function clearHistory() {
        fetch('/api/support/history', { method: 'DELETE', headers: authHeaders() })
            .then(function () { loadHistory(); })
            .catch(function () {});
    }

    function search() {
        var text = ($('sup-input').value || '').trim();
        if (!text) { $('sup-input').focus(); return; }
        var jiraWrap = $('sup-opt-jira-wrap');
        var confWrap = $('sup-opt-conf-wrap');
        var useJira = !jiraWrap.classList.contains('hidden') && $('sup-opt-jira').checked;
        var useConf = !confWrap.classList.contains('hidden') && $('sup-opt-conf').checked;
        var useRag = $('sup-opt-rag').checked;
        var useAi = $('sup-opt-ai').checked;

        var btn = $('sup-search-btn'); btn.disabled = true;
        var meta = $('sup-meta'); meta.classList.remove('hidden');
        meta.innerHTML = '<span class="sup-spinner"></span>Suche läuft…';
        var box = $('sup-results');
        box.innerHTML = useAi
            ? '<div class="sup-ai-card"><div class="sup-ai-label">KI-Zusammenfassung</div>'
              + '<div class="sup-ai-text"><span class="sup-spinner"></span>Quellen werden ausgewertet…</div></div>'
            : '<div class="sup-empty"><span class="sup-spinner"></span>Suche läuft…</div>';

        fetch('/api/support/query', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ text: text, jira: useJira, confluence: useConf, rag: useRag, ai: useAi })
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

    var _lastData = null;

    function render(d) {
        _lastData = d;
        // Zeilen-Begrenzung pro Treffer aus der Skill-Config anwenden
        try { document.documentElement.style.setProperty('--sup-rl', String(d.result_lines || 2)); } catch (e) {}
        var html = '';
        if (d.ai_summary) {
            html += '<div class="sup-ai-card"><div class="sup-ai-label">KI-Zusammenfassung</div>'
                + '<div class="sup-ai-text">' + escLink(d.ai_summary) + '</div></div>';
        }
        html += '<div id="sup-blocks"></div>';
        $('sup-results').innerHTML = html;
        renderBlocks();
    }

    function blockHtml(b, i) {
        var label = b.source_label || b.title || 'Quelle';
        var inner;
        if (b.link) {
            inner = '<a href="' + esc(b.link) + '" target="_blank" rel="noopener">' + esc(label) + ' ↗</a>';
        } else if (b.doc) {
            // lokales Wissensdokument → im Viewer öffnen
            var dl = label + (b.doc_name ? ' (' + b.doc_name + ')' : '');
            inner = '<a href="#" class="sup-doc-link" data-doc="' + esc(b.doc)
                + '" data-label="' + esc(dl) + '">' + esc(dl) + '</a>';
        } else {
            inner = esc(label);
        }
        var srcHtml = '<div class="sup-block-src">Quelle: ' + inner + '</div>';
        return '<div class="sup-block">'
            + '<div class="sup-block-head">'
            + '<span class="sup-block-num">' + (i + 1) + '.</span>'
            + '<span class="sup-block-title">' + esc(b.title) + '</span>'
            + '<span class="sup-badge-src">' + esc(b.source) + '</span>'
            + '<span class="sup-badge-score" title="Zutreffend">' + b.score + '%</span>'
            + '</div>'
            + '<div class="sup-block-body">' + escLink(b.summary) + '</div>'
            + srcHtml
            + '</div>';
    }

    // Eine Liste, nach Relevanz (%) sortiert; Pulldown-Filter
    // (Quelle, Relevanz, Sortierung, Anzahl) wirken auf die gesamte Liste.
    function renderBlocks() {
        if (!_lastData) return;
        var all = (_lastData.blocks || []).slice();
        var src = $('sup-f-source') ? $('sup-f-source').value : '';
        var minRel = parseInt(($('sup-f-rel') ? $('sup-f-rel').value : '0'), 10) || 0;
        var sort = $('sup-f-sort') ? $('sup-f-sort').value : 'score';
        var limit = parseInt(($('sup-f-limit') ? $('sup-f-limit').value : '0'), 10) || 0;

        var list = all.filter(function (b) {
            if (src && b.source !== src) return false;
            if (minRel && b.score < minRel) return false;
            return true;
        });
        if (sort === 'source') list.sort(function (a, b) {
            return a.source === b.source ? b.score - a.score : a.source.localeCompare(b.source);
        });
        else if (sort === 'title') list.sort(function (a, b) {
            return String(a.title).localeCompare(String(b.title), 'de');
        });
        else list.sort(function (a, b) { return b.score - a.score; });
        if (limit) list = list.slice(0, limit);

        $('sup-meta').innerHTML = 'Ergebnis für <strong>"' + esc(_lastData.query) + '"</strong> ('
            + list.length + ' von ' + all.length + ' Treffer'
            + (_lastData.took_ms ? ' · ' + _lastData.took_ms + ' ms' : '') + ')';

        var box = $('sup-blocks');
        if (!box) return;
        if (!list.length) {
            box.innerHTML = '<div class="sup-empty">'
                + (all.length ? 'Keine Treffer mit diesen Filtern.' : 'Keine passenden Quellen gefunden.')
                + '</div>';
            return;
        }
        box.innerHTML = list.map(blockHtml).join('');
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
