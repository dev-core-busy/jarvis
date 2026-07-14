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
        $('wi-login').classList.remove('hidden');
        var u = $('wi-user'); if (u) u.focus();
    }
    function showApp() {
        $('wi-login').classList.add('hidden');
        $('wi-app').classList.remove('hidden');
        $('wi-logout').classList.remove('hidden');
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
            $('wi-sec-ext').classList.add('hidden');
            return;
        }
        banner.className = 'wi-banner';
        banner.innerHTML = t('wissen.scope_as') + ' <b>' + esc(SCOPE.user) + '</b>'
            + (SCOPE.is_editor ? ' ' + t('wissen.global_editor') : '')
            + ' · ' + t('wissen.scope_area') + ' ' + SCOPE.groups.map(function (g) {
                return '<span class="wi-chip" style="border-color:' + esc(g.color) + ';color:' + esc(g.color) + ';">' + esc(g.name) + '</span>';
            }).join(' ');

        var sel = $('wi-folder');
        sel.innerHTML = SCOPE.folders.map(function (f) {
            return '<option value="' + esc(f.path) + '">' + esc(f.name) + ' (' + esc(f.path) + ')</option>';
        }).join('');

        $('wi-upload-groups').innerHTML = groupBoxes('up');
    }

    function groupBoxes(prefix) {
        return SCOPE.groups.map(function (g) {
            return '<label class="wi-grpbox" style="border-color:' + esc(g.color) + '55;">'
                + '<input type="checkbox" class="wi-grp-' + prefix + '" value="' + esc(g.id) + '"'
                + (SCOPE.groups.length === 1 ? ' checked' : '') + '>'
                + '<span style="color:' + esc(g.color) + ';font-weight:600;">' + esc(g.name) + '</span></label>';
        }).join('');
    }
    function checkedGroups(prefix) {
        return Array.prototype.slice.call(document.querySelectorAll('.wi-grp-' + prefix + ':checked'))
            .map(function (c) { return c.value; });
    }

    // ── Upload ──────────────────────────────────────────────────────────
    function uploadFiles(fileList) {
        var st = $('wi-upload-status');
        var groups = checkedGroups('up');
        if (!groups.length) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.pick_group'); return; }
        if (!fileList || !fileList.length) return;
        var fd = new FormData();
        for (var i = 0; i < fileList.length; i++) fd.append('files', fileList[i]);
        fd.append('folder', $('wi-folder').value);
        fd.append('groups', groups.join(','));
        st.style.color = 'var(--text-secondary)'; st.textContent = t('wissen.uploading', { n: fileList.length });
        fetch('/api/wissen/upload', { method: 'POST', headers: authH(), body: fd })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                d = d || {};
                if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
                st.style.color = 'var(--success)';
                st.textContent = t('wissen.saved_n', { n: d.total_saved || 0 })
                    + (d.total_rejected ? t('wissen.rejected_n', { n: d.total_rejected }) : '') + '.';
                loadFiles();
            })
            .catch(function () { st.style.color = 'var(--danger)'; st.textContent = t('wissen.upload_failed'); });
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
                        return '<span class="wi-chip" style="border-color:' + esc(g.color) + ';color:' + esc(g.color) + ';font-size:0.7rem;">' + esc(g.name) + '</span>';
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

    // ── Extraktor ───────────────────────────────────────────────────────
    function extractUrl() {
        var url = $('wi-ext-url').value.trim();
        if (!url) return;
        var st = $('wi-ext-status');
        st.style.color = 'var(--text-secondary)'; st.textContent = t('wissen.extracting');
        fetch('/api/wissen/extract', { method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify({ url: url }) })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
                st.textContent = ''; $('wi-ext-url').value = '';
                showReview(d); loadPending();
            })
            .catch(function () { st.style.color = 'var(--danger)'; st.textContent = t('wissen.extract_failed'); });
    }
    function extractFile(file) {
        if (!file) return;
        var st = $('wi-ext-status');
        st.style.color = 'var(--text-secondary)'; st.textContent = t('wissen.extracting_file', { f: file.name });
        var fd = new FormData(); fd.append('file', file);
        fetch('/api/wissen/extract/upload', { method: 'POST', headers: authH(), body: fd })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
                st.textContent = ''; showReview(d); loadPending();
            })
            .catch(function () { st.style.color = 'var(--danger)'; st.textContent = t('wissen.extract_failed'); });
    }

    function docPreview(d) {
        var parts = [];
        if (d.summary) parts.push(d.summary);
        if (d.facts && d.facts.length) parts.push('\n' + t('wissen.facts_label') + '\n- ' + d.facts.join('\n- '));
        if (d.qa_pairs && d.qa_pairs.length) parts.push('\n' + t('wissen.qa_label') + '\n' + d.qa_pairs.map(function (p) { return 'F: ' + p.q + '\nA: ' + p.a; }).join('\n'));
        return parts.join('\n');
    }

    function showReview(d) {
        var box = $('wi-ext-review');
        box.innerHTML = '<div class="wi-review">'
            + '<div style="font-weight:600;margin-bottom:6px;">' + t('wissen.review_title') + '</div>'
            + '<label style="font-size:0.78rem;color:var(--text-secondary);">' + t('wissen.title_label') + '</label>'
            + '<input class="wi-input" id="wi-rev-title" value="' + esc(d.title || '') + '">'
            + '<pre>' + esc(docPreview(d)) + '</pre>'
            + '<label style="font-size:0.78rem;color:var(--text-secondary);">' + t('wissen.target_groups') + '</label>'
            + '<div class="wi-groups" id="wi-rev-groups" style="margin:6px 0 10px;">' + groupBoxes('rev') + '</div>'
            + '<button class="sec-btn primary" id="wi-rev-approve" type="button">' + t('wissen.approve') + '</button> '
            + '<button class="sec-btn danger" id="wi-rev-discard" type="button">' + t('wissen.discard') + '</button>'
            + '</div>';
        $('wi-rev-approve').addEventListener('click', function () { approvePending(d.id); });
        $('wi-rev-discard').addEventListener('click', function () { deletePending(d.id, true); });
    }

    function approvePending(id) {
        var groups = checkedGroups('rev');
        var st = $('wi-ext-status');
        if (!groups.length) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.pick_target'); return; }
        var title = ($('wi-rev-title') || {}).value;
        var chain = Promise.resolve();
        if (title != null) {
            chain = fetch('/api/wissen/pending/' + encodeURIComponent(id), {
                method: 'PATCH', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify({ title: title })
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
        drop.addEventListener('click', function () { fin.click(); });
        fin.addEventListener('change', function () { uploadFiles(fin.files); fin.value = ''; });
        ['dragover', 'dragleave', 'drop'].forEach(function (ev) {
            drop.addEventListener(ev, function (e) {
                e.preventDefault();
                drop.classList.toggle('drag', ev === 'dragover');
                if (ev === 'drop' && e.dataTransfer) uploadFiles(e.dataTransfer.files);
            });
        });

        $('wi-ext-url-btn').addEventListener('click', extractUrl);
        $('wi-ext-url').addEventListener('keydown', function (e) { if (e.key === 'Enter') extractUrl(); });
        $('wi-ext-tab-url').addEventListener('click', function () {
            $('wi-ext-url-panel').classList.remove('hidden'); $('wi-ext-file-panel').classList.add('hidden');
        });
        $('wi-ext-tab-file').addEventListener('click', function () {
            $('wi-ext-file-panel').classList.remove('hidden'); $('wi-ext-url-panel').classList.add('hidden');
        });
        var edrop = $('wi-ext-drop'), efin = $('wi-ext-file-input');
        edrop.addEventListener('click', function () { efin.click(); });
        efin.addEventListener('change', function () { if (efin.files[0]) extractFile(efin.files[0]); efin.value = ''; });
        ['dragover', 'dragleave', 'drop'].forEach(function (ev) {
            edrop.addEventListener(ev, function (e) {
                e.preventDefault();
                edrop.classList.toggle('drag', ev === 'dragover');
                if (ev === 'drop' && e.dataTransfer && e.dataTransfer.files[0]) extractFile(e.dataTransfer.files[0]);
            });
        });

        if (window.applyLang) window.applyLang();
        loadScope();
    });
})();
