/* Eigenständige Wissens-Seite /wissen – Domänennutzer pflegen Wissen NUR aus
   ihren Wissensgruppen (Editor-Rechte). Upload, Ordnerwahl, Informationsextraktor.
   Berechtigungen werden serverseitig erzwungen (/api/wissen/*). i18n via window.t. */
(function () {
    'use strict';

    var $ = function (id) { return document.getElementById(id); };
    var token = localStorage.getItem('jarvis_token') || '';
    var SCOPE = { groups: [], folders: [], is_editor: false, user: '' };

    // i18n-Helfer: liefert Übersetzung oder (fallback) den Key; {slots} via .replace().
    function t(k, vars) {
        var s = (window.t ? window.t(k) : k) || k;
        if (vars) { for (var v in vars) s = s.split('{' + v + '}').join(vars[v]); }
        return s;
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function authH(extra) { return Object.assign({ 'Authorization': 'Bearer ' + token }, extra || {}); }

    // ── Screens ─────────────────────────────────────────────────────────
    function showLogin() {
        $('wi-app').classList.add('hidden');
        $('wi-logout').classList.add('hidden');
        var d = $('wi-status-dot'); if (d) d.classList.add('hidden');
        var c = $('cpu-bar'); if (c) c.classList.add('hidden');
        $('wi-login').classList.remove('hidden');
        var u = $('wi-user'); if (u) u.focus();
    }
    function showApp() {
        $('wi-login').classList.add('hidden');
        $('wi-app').classList.remove('hidden');
        $('wi-logout').classList.remove('hidden');
        var d = $('wi-status-dot'); if (d) d.classList.remove('hidden');
        var c = $('cpu-bar'); if (c) c.classList.remove('hidden');
        mountProfile();
        startLlmStatus();
        startCpu();
    }

    // KI-Profil-Pulldown neben "Fragen & Antworten generieren"
    // (per-User-Auswahl, wirkt auf die KI-Analyse)
    var _prof = null;
    function mountProfile() {
        var slot = $('wi-prof-slot');
        if (!slot || !window.ProfileSwitcher) return;
        if (_prof) { _prof.refresh(); return; }
        _prof = window.ProfileSwitcher.mount({
            anchor: slot,
            headers: function () { return authH(); },
            onChange: function () { checkLlmStatus(); }
        });
    }

    // ── LLM-Status-Punkt + CPU-Auslastung (wie /chat und /support) ─────
    var _llmStatusTimer = null, _cpuTimer = null;
    function checkLlmStatus() {
        var dot = $('wi-status-dot');
        if (!dot) return;
        fetch('/api/llm/active-status', { headers: authH() })
            .then(function (r) { if (!r.ok) throw new Error('http'); return r.json(); })
            .then(function (d) {
                var reachable = (d.status === 'ok' || d.status === 'degraded');
                // classList statt className: 'hidden' (Login-Screen) muss erhalten bleiben
                dot.classList.toggle('connected', reachable);
                dot.classList.toggle('disconnected', !reachable);
                var name = d.profile_name ? ' – ' + d.profile_name : '';
                dot.title = (d.status === 'ok' ? t('sup.llm_ok')
                    : d.status === 'degraded' ? t('sup.llm_degraded')
                    : t('sup.llm_down')) + name;
            })
            .catch(function () {
                dot.classList.remove('connected');
                dot.classList.add('disconnected');
                dot.title = t('sup.llm_down');
            });
    }
    function startLlmStatus() {
        checkLlmStatus();
        if (!_llmStatusTimer) _llmStatusTimer = setInterval(checkLlmStatus, 30000);
    }
    function startCpu() {
        function poll() {
            fetch('/api/cpu', { headers: authH() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d) return;
                    var fill = $('cpu-bar-fill'), label = $('cpu-bar-label');
                    if (!fill || !label) return;
                    var p = Math.max(0, Math.min(100, Number(d.cpu) || 0));
                    fill.style.width = p + '%';
                    fill.style.backgroundPosition = p + '% 0';
                    label.textContent = 'CPU: ' + Math.round(p) + '%';
                })
                .catch(function () {});
        }
        if (_cpuTimer) return;
        poll();
        _cpuTimer = setInterval(poll, 3000);
    }

    // ── Login ───────────────────────────────────────────────────────────
    function doLogin() {
        var btn = $('wi-login-btn'), err = $('wi-login-err');
        err.textContent = '';
        var payload = { username: $('wi-user').value.trim(), password: $('wi-pass').value };
        var totp = $('wi-totp').value.trim();
        if (!$('wi-totp-row').classList.contains('hidden') && totp) payload.totp_code = totp;
        if (!payload.username || !payload.password) { err.textContent = t('wissen.err_user_pass'); return; }
        btn.disabled = true; btn.textContent = t('wissen.logging_in');
        fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.success && d.token) {
                    token = d.token;
                    localStorage.setItem('jarvis_token', token);
                    localStorage.setItem('jarvis_user', d.username || payload.username);
                    $('wi-totp-row').classList.add('hidden');
                    loadScope();
                } else if (d.requires_totp) {
                    $('wi-totp-row').classList.remove('hidden'); $('wi-totp').focus();
                    err.textContent = t('wissen.totp_required');
                } else {
                    err.textContent = d.error || t('wissen.login_failed');
                }
            })
            .catch(function () { err.textContent = t('wissen.conn_error'); })
            .then(function () { btn.disabled = false; btn.textContent = t('wissen.login_title'); });
    }

    function logout() {
        localStorage.removeItem('jarvis_token');
        token = '';
        showLogin();
    }

    // ── Bereich laden ───────────────────────────────────────────────────
    function loadScope() {
        if (!token) { showLogin(); return; }
        fetch('/api/wissen/scope', { headers: authH() })
            .then(function (r) {
                if (r.status === 401 || r.status === 403) { showLogin(); return null; }
                return r.json();
            })
            .then(function (d) {
                if (!d || !d.ok) return;
                SCOPE = d;
                showApp();
                renderScope();
                loadFiles();
                loadPending();
            })
            .catch(function () { showLogin(); });
    }

    function renderScope() {
        var banner = $('wi-scope-banner');
        if (!SCOPE.groups.length) {
            banner.className = 'wi-banner warn';
            banner.innerHTML = t('wissen.no_area');
            $('wi-sec-upload').classList.add('hidden');
            return;
        }
        banner.className = 'wi-banner';
        // "Dein Bereich" + Wissensgruppen in eigener Zeile (bricht sonst unschoen um)
        banner.innerHTML = '<div>' + t('wissen.scope_as') + ' <b>' + esc(SCOPE.user) + '</b>'
            + (SCOPE.is_editor ? ' ' + t('wissen.global_editor') : '') + '</div>'
            + '<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;">'
            + t('wissen.scope_area') + ' ' + SCOPE.groups.map(function (g) {
                return '<span class="wi-chip" style="border-color:' + esc(g.color) + ';">' + esc(g.name) + '</span>';
            }).join(' ') + '</div>';

        var sel = $('wi-folder');
        sel.innerHTML = SCOPE.folders.map(function (f) {
            return '<option value="' + esc(f.path) + '">' + esc(f.name) + ' (' + esc(f.path) + ')</option>';
        }).join('');

        $('wi-upload-groups').innerHTML = groupBoxes('up');
        updateDropState();   // Ablage-Sperre initial setzen (keine Gruppe = gesperrt + Hinweis)
    }

    function groupBoxes(prefix) {
        return SCOPE.groups.map(function (g) {
            return '<label class="wi-grpbox" style="border-color:' + esc(g.color) + ';">'
                + '<input type="checkbox" class="wi-grp-' + prefix + '" value="' + esc(g.id) + '"'
                + (SCOPE.groups.length === 1 ? ' checked' : '') + '>'
                + '<span style="font-weight:600;">' + esc(g.name) + '</span></label>';
        }).join('');
    }
    function checkedGroups(prefix) {
        return Array.prototype.slice.call(document.querySelectorAll('.wi-grp-' + prefix + ':checked'))
            .map(function (c) { return c.value; });
    }

    // ── Upload ──────────────────────────────────────────────────────────
    // Ablage-Sperre: solange keine Wissensgruppe gewaehlt ist ODER eine
    // KI-Analyse/ein Upload laeuft, duerfen keine Dateien abgelegt werden.
    var _busy = false;
    function canUpload() { return !_busy && checkedGroups('up').length > 0; }
    function updateDropState() {
        var drop = $('wi-drop'), hint = $('wi-drop-hint');
        if (!drop) return;
        var ok = canUpload();
        drop.classList.toggle('disabled', !ok);
        if (hint) {
            if (_busy) { hint.style.display = 'none'; }                       // Busy-Banner uebernimmt
            else if (!checkedGroups('up').length) { hint.style.display = 'block'; hint.textContent = t('wissen.drop_need_group'); }
            else { hint.style.display = 'none'; }
        }
    }
    function setBusy(on, genQ) {
        _busy = !!on;
        var b = $('wi-busy'), bt = $('wi-busy-text');
        if (b) b.classList.toggle('hidden', !_busy);
        if (_busy && bt) bt.textContent = genQ ? t('wissen.busy_genq') : t('wissen.busy_upload');
        var ub = $('wi-ext-url-btn'); if (ub) ub.disabled = _busy;   // URL-Analyse mitsperren
        updateDropState();
    }

    // Gewuenschte Fragenanzahl aus dem Zahlenfeld (1..30, Fallback 20)
    function qaCount() {
        var n = parseInt(($('wi-genq-count') || {}).value, 10);
        if (isNaN(n) || n < 1) n = 20; if (n > 30) n = 30;
        return n;
    }
    function uploadFiles(fileList) {
        var st = $('wi-upload-status');
        var groups = checkedGroups('up');
        if (_busy) return;   // laufende Analyse: keine weitere Ablage
        if (!groups.length) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.pick_group'); updateDropState(); return; }
        if (!fileList || !fileList.length) return;
        var fd = new FormData();
        for (var i = 0; i < fileList.length; i++) fd.append('files', fileList[i]);
        fd.append('folder', $('wi-folder').value);
        fd.append('groups', groups.join(','));
        // Optional: Frage-Antwort-Paare generieren (Checkbox + gewuenschte Anzahl)
        var genQ = $('wi-genq') && $('wi-genq').checked;
        if (genQ) fd.append('gen_questions', String(qaCount()));
        st.textContent = '';
        setBusy(true, genQ);   // prominentes Warten-Banner + Ablage-Sperre
        fetch('/api/wissen/upload', { method: 'POST', headers: authH(), body: fd })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                d = d || {};
                if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
                st.style.color = 'var(--success)';
                var msg = t('wissen.saved_n', { n: d.total_saved || 0 })
                    + (d.total_rejected ? t('wissen.rejected_n', { n: d.total_rejected }) : '') + '.';
                if (d.qa_pending && d.qa_pending.length) msg += ' ' + t('wissen.genq_done', { n: d.qa_pending.length });
                if (d.qa_errors && d.qa_errors.length) {
                    st.style.color = 'var(--warning)';
                    msg += ' ⚠ ' + d.qa_errors.map(function (e) { return e.name + ': ' + e.error; }).join(' · ');
                }
                st.textContent = msg;
                loadFiles();
                // Generierte Entwuerfe: Liste aktualisieren + ersten direkt zum Audit oeffnen
                if (d.qa_pending && d.qa_pending.length) {
                    loadPending();
                    fetch('/api/wissen/pending', { headers: authH() })
                        .then(function (r) { return r.json(); })
                        .then(function (p) {
                            var doc = ((p && p.pending) || []).find(function (x) { return x.id === d.qa_pending[0].id; });
                            if (doc) { showReview(doc); $('wi-ext-review').scrollIntoView({ behavior: 'smooth' }); }
                        }).catch(function () {});
                }
            })
            .catch(function () { st.style.color = 'var(--danger)'; st.textContent = t('wissen.upload_failed'); })
            .then(function () { setBusy(false); });
    }

    // ── Mein Wissen ─────────────────────────────────────────────────────
    function loadFiles() {
        fetch('/api/wissen/files', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var box = $('wi-files-list');
                var files = (d && d.files) || [];
                if (!files.length) { box.innerHTML = '<div class="wi-empty">' + t('wissen.no_files') + '</div>'; return; }
                box.innerHTML = files.map(function (f) {
                    var chips = f.groups.map(function (g) {
                        return '<span class="wi-chip" style="border-color:' + esc(g.color) + ';font-size:0.7rem;">' + esc(g.name) + '</span>';
                    }).join(' ');
                    var url = '/api/wissen/file?path=' + encodeURIComponent(f.path) + '&token=' + encodeURIComponent(token);
                    return '<div class="wi-item" data-path="' + esc(f.path) + '">'
                        + '<a class="nm wi-flink" href="' + esc(url) + '" target="_blank" rel="noopener" title="' + esc(t('wissen.open_file')) + '">' + esc(f.name) + '</a>'
                        + chips
                        + '<button type="button" class="sec-btn small danger wi-file-del" title="' + esc(t('wissen.delete_file')) + '">×</button>'
                        + '</div>';
                }).join('');
                box.querySelectorAll('.wi-file-del').forEach(function (btn) {
                    btn.addEventListener('click', function () {
                        var row = btn.closest('.wi-item');
                        deleteFile(row.getAttribute('data-path'), (row.querySelector('.nm') || {}).textContent);
                    });
                });
            })
            .catch(function () {});
    }

    function deleteFile(path, name) {
        if (!path) return;
        if (!window.confirm(t('wissen.delete_confirm', { name: name || path }))) return;
        fetch('/api/wissen/file', {
            method: 'DELETE', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ path: path })
        }).then(function (r) { return r.json(); })
          .then(function (d) {
              if (d && d.ok) { loadFiles(); }
              else { window.alert((d && d.error) || t('wissen.delete_failed')); }
          })
          .catch(function () { window.alert(t('wissen.delete_failed')); });
    }

    // ── Extraktor (Webseite) ────────────────────────────────────────────
    // Fragen & Antworten werden bei der URL-Analyse IMMER generiert
    // (Anzahl aus dem Zahlenfeld); waehrend der Analyse ist die Ablage gesperrt.
    function extractUrl() {
        var url = $('wi-ext-url').value.trim();
        if (!url || _busy) return;
        var st = $('wi-ext-status');
        st.style.color = 'var(--text-secondary)'; st.textContent = t('wissen.extracting');
        setBusy(true, true);
        fetch('/api/wissen/extract', { method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify({ url: url, qa_count: qaCount() }) })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
                st.textContent = ''; $('wi-ext-url').value = '';
                showReview(d); loadPending();
            })
            .catch(function () { st.style.color = 'var(--danger)'; st.textContent = t('wissen.extract_failed'); })
            .then(function () { setBusy(false); });
    }

    function docPreview(d) {
        var parts = [];
        if (d.summary) parts.push(d.summary);
        if (d.facts && d.facts.length) parts.push('\n' + t('wissen.facts_label') + '\n- ' + d.facts.join('\n- '));
        return parts.join('\n');
    }

    // Q&A-Audit: eine editierbare Zeile pro Frage-Antwort-Paar
    // (Checkbox = freigeben, Textfelder = korrigieren, × = loeschen).
    function qaRowHtml(p, i) {
        return '<div class="wi-qa-row" data-qid="' + esc(p.id || String(i)) + '" style="display:flex;gap:8px;align-items:flex-start;margin-bottom:8px;">'
            + '<input type="checkbox" class="wi-qa-keep" ' + (p.approved !== false ? 'checked' : '') + ' title="' + esc(t('wissen.qa_keep')) + '" style="margin-top:8px;">'
            + '<div style="flex:1;min-width:0;">'
            + '<input class="wi-input wi-qa-q" value="' + esc(p.q || '') + '" placeholder="' + esc(t('wissen.qa_q_ph')) + '" style="margin-bottom:4px;font-weight:600;">'
            + '<textarea class="wi-input wi-qa-a" rows="2" placeholder="' + esc(t('wissen.qa_a_ph')) + '" style="resize:vertical;">' + esc(p.a || '') + '</textarea>'
            + '</div>'
            + '<button type="button" class="sec-btn small danger wi-qa-del" title="' + esc(t('wissen.qa_del')) + '" style="margin-top:6px;">×</button>'
            + '</div>';
    }

    function showReview(d) {
        var box = $('wi-ext-review');
        var qa = (d.qa_pairs || []);
        var qaHtml = qa.length
            ? '<label style="font-size:0.78rem;color:var(--text-secondary);display:block;margin-top:10px;">' + t('wissen.qa_audit_label', { n: qa.length }) + '</label>'
              + '<div id="wi-rev-qa" style="margin:6px 0 10px;">' + qa.map(qaRowHtml).join('') + '</div>'
            : '';
        box.innerHTML = '<div class="wi-review">'
            + '<div style="font-weight:600;margin-bottom:6px;">' + t('wissen.review_title') + '</div>'
            + '<label style="font-size:0.78rem;color:var(--text-secondary);">' + t('wissen.title_label') + '</label>'
            + '<input class="wi-input" id="wi-rev-title" value="' + esc(d.title || '') + '">'
            + '<pre>' + esc(docPreview(d)) + '</pre>'
            + qaHtml
            + '<label style="font-size:0.78rem;color:var(--text-secondary);">' + t('wissen.target_groups') + '</label>'
            + '<div class="wi-groups" id="wi-rev-groups" style="margin:6px 0 10px;">' + groupBoxes('rev') + '</div>'
            + '<button class="sec-btn primary" id="wi-rev-approve" type="button">' + t('wissen.approve') + '</button> '
            + '<button class="sec-btn danger" id="wi-rev-discard" type="button">' + t('wissen.discard') + '</button>'
            + '</div>';
        // Zeilen-Loeschen (Paar komplett entfernen)
        box.querySelectorAll('.wi-qa-del').forEach(function (btn) {
            btn.addEventListener('click', function () { btn.closest('.wi-qa-row').remove(); });
        });
        $('wi-rev-approve').addEventListener('click', function () { approvePending(d.id); });
        $('wi-rev-discard').addEventListener('click', function () { deletePending(d.id, true); });
    }

    // Auditierte Q&A-Paare aus dem Review-Formular einsammeln
    // (geloeschte Zeilen fehlen; Checkbox ab = nicht freigeben).
    function collectQa() {
        var rows = document.querySelectorAll('#wi-rev-qa .wi-qa-row');
        if (!rows.length) return null;   // kein Q&A-Audit im Formular
        var out = [];
        rows.forEach(function (row) {
            var q = (row.querySelector('.wi-qa-q') || {}).value || '';
            var a = (row.querySelector('.wi-qa-a') || {}).value || '';
            if (!q.trim()) return;
            out.push({
                id: row.getAttribute('data-qid') || '',
                q: q.trim(), a: a.trim(),
                approved: !!(row.querySelector('.wi-qa-keep') || {}).checked,
            });
        });
        return out;
    }

    function approvePending(id) {
        var groups = checkedGroups('rev');
        var st = $('wi-ext-status');
        if (!groups.length) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.pick_target'); return; }
        var title = ($('wi-rev-title') || {}).value;
        var patch = {};
        if (title != null) patch.title = title;
        var qa = collectQa();
        if (qa !== null) patch.qa_pairs = qa;
        var chain = Promise.resolve();
        if (Object.keys(patch).length) {
            chain = fetch('/api/wissen/pending/' + encodeURIComponent(id), {
                method: 'PATCH', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify(patch)
            }).catch(function () {});
        }
        chain.then(function () {
            return fetch('/api/wissen/pending/' + encodeURIComponent(id) + '/approve', {
                method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify({ groups: groups })
            });
        }).then(function (r) { return r.json(); })
          .then(function (d) {
              if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
              st.style.color = 'var(--success)'; st.textContent = t('wissen.approved_ok');
              $('wi-ext-review').innerHTML = ''; loadPending(); loadFiles();
          })
          .catch(function () { st.style.color = 'var(--danger)'; st.textContent = t('wissen.approve_failed'); });
    }

    function deletePending(id, clearReview) {
        fetch('/api/wissen/pending/' + encodeURIComponent(id), { method: 'DELETE', headers: authH() })
            .then(function () { if (clearReview) $('wi-ext-review').innerHTML = ''; loadPending(); })
            .catch(function () {});
    }

    function loadPending() {
        fetch('/api/wissen/pending', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var box = $('wi-pending-list');
                var items = (d && d.pending) || [];
                if (!items.length) { box.innerHTML = '<div class="wi-empty">' + t('wissen.no_drafts') + '</div>'; return; }
                box.innerHTML = '';
                items.forEach(function (it) {
                    var row = document.createElement('div');
                    row.className = 'wi-item';
                    row.innerHTML = '<span class="nm">' + esc(it.title || t('wissen.untitled')) + '</span>';
                    var rev = document.createElement('button'); rev.className = 'sec-btn small'; rev.textContent = t('wissen.review_btn');
                    rev.addEventListener('click', function () { showReview(it); window.scrollTo(0, document.body.scrollHeight); });
                    var del = document.createElement('button'); del.className = 'sec-btn small danger'; del.textContent = '×';
                    del.addEventListener('click', function () { deletePending(it.id, false); });
                    row.appendChild(rev); row.appendChild(del);
                    box.appendChild(row);
                });
            })
            .catch(function () {});
    }

    // ── Verdrahtung ─────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        $('wi-login-btn').addEventListener('click', doLogin);
        ['wi-user', 'wi-pass', 'wi-totp'].forEach(function (id) {
            $(id).addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });
        });
        $('wi-logout').addEventListener('click', logout);

        var drop = $('wi-drop'), fin = $('wi-file-input');
        drop.addEventListener('click', function () {
            if (!canUpload()) { updateDropState(); return; }   // gesperrt: Hinweis statt Dateidialog
            fin.click();
        });
        fin.addEventListener('change', function () { uploadFiles(fin.files); fin.value = ''; });
        ['dragover', 'dragleave', 'drop'].forEach(function (ev) {
            drop.addEventListener(ev, function (e) {
                e.preventDefault();
                drop.classList.toggle('drag', ev === 'dragover' && canUpload());
                if (ev === 'drop' && e.dataTransfer) {
                    if (!canUpload()) { updateDropState(); return; }
                    uploadFiles(e.dataTransfer.files);
                }
            });
        });
        // Gruppen-Auswahl schaltet die Ablage frei/gesperrt (Checkboxen kommen per JS)
        $('wi-upload-groups').addEventListener('change', updateDropState);

        // Einklappbare Container (Zustand pro Browser gemerkt, analog Einstellungen).
        // Der Pfeil steht fest im Markup (eigener Span, damit applyLang ihn nicht wegwischt).
        ['wi-sec-upload', 'wi-sec-files'].forEach(function (id) {
            var sec = $(id); if (!sec) return;
            var h = sec.querySelector('h2'); if (!h) return;
            var tog = h.querySelector('.wi-sec-tog'); if (!tog) return;
            var key = 'jarvis_wissen_sec_' + id;
            function apply(collapsed, silent) {
                sec.classList.toggle('collapsed', collapsed);
                tog.textContent = collapsed ? '▶' : '▼';
                if (!silent) { try { localStorage.setItem(key, collapsed ? '1' : '0'); } catch (e) {} }
            }
            var saved = null; try { saved = localStorage.getItem(key); } catch (e) {}
            apply(saved === '1', true);
            h.addEventListener('click', function () { apply(!sec.classList.contains('collapsed')); });
        });

        $('wi-ext-url-btn').addEventListener('click', extractUrl);
        $('wi-ext-url').addEventListener('keydown', function (e) { if (e.key === 'Enter') extractUrl(); });

        if (window.applyLang) window.applyLang();
        loadScope();
    });
})();
