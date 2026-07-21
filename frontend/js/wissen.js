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
                loadCfSpaces();
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
        // Nur "Angemeldet als <user>" – die Wissensgruppen-Chips entfallen hier,
        // da die Gruppen weiter unten in der Auswahl ohnehin gezeigt werden.
        banner.innerHTML = '<div>' + t('wissen.scope_as') + ' <b>' + esc(SCOPE.user) + '</b>'
            + (SCOPE.is_editor ? ' ' + t('wissen.global_editor') : '') + '</div>';

        $('wi-upload-groups').innerHTML = groupBoxes('up');
        updateFolderOptions();
        updateDropState();   // Ablage-Sperre initial setzen (keine Gruppe = gesperrt + Hinweis)

        // Massenzuordnung + Wissensgruppen-Verwaltung nur fuer globale Wissens-Editoren
        var mSec = $('wi-sec-matrix');
        if (mSec) mSec.style.display = SCOPE.is_editor ? '' : 'none';
        var gSec = $('wi-sec-groups');
        if (gSec) {
            gSec.style.display = SCOPE.is_editor ? '' : 'none';
            // Gruppen-Verwaltung (aus Einstellungen verschoben) via knowledge.js rendern
            if (SCOPE.is_editor && window.knowledgeManager && window.knowledgeManager.initGroups) {
                window.knowledgeManager.initGroups();
            }
        }
    }

    // Speicherordner-Auswahl auf die gewaehlten Gruppen eingrenzen: angeboten
    // wird die Union der Speicherordner der angehakten Gruppen (Server liefert
    // pro Gruppe g.folders; data/knowledge wird unter /wissen nie angeboten).
    // Gruppen ohne Zuordnung haben KEIN Speicherziel -> Ablage bleibt gesperrt.
    // Globale Editoren sehen immer alle Ordner ihres Scopes.
    function updateFolderOptions() {
        var sel = $('wi-folder');
        if (!sel) return;
        var offer = SCOPE.folders || [];
        var checked = checkedGroups('up');
        if (!SCOPE.is_editor && checked.length) {
            var want = {};
            checked.forEach(function (gid) {
                var g = null;
                SCOPE.groups.forEach(function (x) { if (x.id === gid) g = x; });
                ((g && g.folders) || []).forEach(function (p) { want[p] = true; });
            });
            offer = offer.filter(function (f) { return want[f.path]; });
        }
        var cur = sel.value;
        sel.innerHTML = offer.map(function (f) {
            return '<option value="' + esc(f.path) + '">' + esc(f.name) + ' (' + esc(f.path) + ')</option>';
        }).join('');
        // Bisherige Auswahl erhalten, wenn sie weiterhin angeboten wird
        for (var i = 0; i < offer.length; i++) {
            if (offer[i].path === cur) { sel.value = cur; break; }
        }
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
    function hasFolder() { var s = $('wi-folder'); return !!(s && s.value); }
    function canUpload() { return !_busy && checkedGroups('up').length > 0 && hasFolder(); }
    function updateDropState() {
        var drop = $('wi-drop'), hint = $('wi-drop-hint');
        if (!drop) return;
        var ok = canUpload();
        drop.classList.toggle('disabled', !ok);
        if (hint) {
            if (_busy) { hint.style.display = 'none'; }                       // Busy-Banner uebernimmt
            else if (!checkedGroups('up').length) { hint.style.display = 'block'; hint.textContent = t('wissen.drop_need_group'); }
            else if (!hasFolder()) { hint.style.display = 'block'; hint.textContent = t('wissen.no_folder'); }
            else { hint.style.display = 'none'; }
        }
    }
    function setBusy(on, genQ) {
        _busy = !!on;
        var b = $('wi-busy'), bt = $('wi-busy-text');
        if (b) b.classList.toggle('hidden', !_busy);
        if (_busy && bt) bt.textContent = genQ ? t('wissen.busy_genq') : t('wissen.busy_upload');
        var ub = $('wi-extract-btn'); if (ub) ub.disabled = _busy;   // Aktion mitsperren
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
        if (!hasFolder()) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.no_folder'); updateDropState(); return; }
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
                var bulk = $('wi-drafts-bulk');
                if (bulk) bulk.style.display = items.length ? 'flex' : 'none';
                if (!items.length) { box.innerHTML = '<div class="wi-empty">' + t('wissen.no_drafts') + '</div>'; return; }
                box.innerHTML = '';
                items.forEach(function (it) {
                    var row = document.createElement('div');
                    row.className = 'wi-item';
                    var cb = document.createElement('input');
                    cb.type = 'checkbox'; cb.className = 'wi-draft-cb'; cb.value = it.id;
                    cb.title = t('wissen.mark_delete');
                    cb.style.cssText = 'flex-shrink:0;width:16px;height:16px;margin:0 2px 0 0;cursor:pointer;';
                    var nm = document.createElement('span'); nm.className = 'nm'; nm.textContent = it.title || t('wissen.untitled');
                    var rev = document.createElement('button'); rev.className = 'sec-btn small'; rev.textContent = t('wissen.review_btn');
                    rev.addEventListener('click', function () { showReview(it); window.scrollTo(0, document.body.scrollHeight); });
                    var del = document.createElement('button'); del.className = 'sec-btn small danger'; del.textContent = '×';
                    del.addEventListener('click', function () { deletePending(it.id, false); });
                    row.appendChild(cb); row.appendChild(nm); row.appendChild(rev); row.appendChild(del);
                    box.appendChild(row);
                });
                bindDraftsBulk(box);
            })
            .catch(function () {});
    }

    // Mehrfachauswahl zum Verwerfen mehrerer Entwuerfe (analog Einstellungen-Extraktor).
    function bindDraftsBulk(box) {
        var boxes = Array.prototype.slice.call(box.querySelectorAll('.wi-draft-cb'));
        var selAll = $('wi-drafts-selall'), delSel = $('wi-drafts-delsel');
        function sync() {
            var checked = boxes.filter(function (b) { return b.checked; }).length;
            if (delSel) {
                delSel.disabled = checked === 0;
                delSel.textContent = checked ? t('wissen.delete_selected') + ' (' + checked + ')' : t('wissen.delete_selected');
            }
            if (selAll) selAll.textContent = (checked && checked === boxes.length) ? t('wissen.unselect_all') : t('wissen.select_all');
        }
        boxes.forEach(function (b) { b.onchange = sync; });
        if (selAll) selAll.onclick = function () {
            var all = boxes.length && boxes.every(function (b) { return b.checked; });
            boxes.forEach(function (b) { b.checked = !all; });
            sync();
        };
        if (delSel) delSel.onclick = function () {
            var ids = boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
            if (ids.length) bulkDeleteDrafts(ids);
        };
        sync();
    }

    function bulkDeleteDrafts(ids) {
        if (!window.confirm(t('wissen.delete_selected_confirm', { n: ids.length }))) return;
        var chain = Promise.resolve();
        ids.forEach(function (id) {
            chain = chain.then(function () {
                return fetch('/api/wissen/pending/' + encodeURIComponent(id), { method: 'DELETE', headers: authH() }).catch(function () {});
            });
        });
        chain.then(function () { $('wi-ext-review').innerHTML = ''; loadPending(); });
    }

    // ── Eingabe-Tabs: URL / Datei / Confluence ──────────────────────────
    var _extTab = 'url';
    function switchExtTab(tab) {
        _extTab = tab;
        [['url', 'wi-tab-url', 'wi-panel-url'], ['file', 'wi-tab-file', 'wi-panel-file'],
         ['cf', 'wi-tab-cf', 'wi-panel-cf']].forEach(function (x) {
            var btn = $(x[1]), pan = $(x[2]);
            if (btn) btn.classList.toggle('active', tab === x[0]);
            if (pan) pan.style.display = (tab === x[0]) ? '' : 'none';
        });
        // Der Abbrechen-Button gehoert zum Confluence-Bulk – bei Tab-Wechsel weg,
        // sofern kein Job laeuft.
        if (!_cfJobId) { var xc = $('wi-extract-cancel'); if (xc) xc.style.display = 'none'; }
        if (tab === 'file') updateDropState();
    }

    // Universeller "Extrahieren"-Button: löst je nach aktivem Tab die passende Aktion aus.
    function doExtract() {
        if (_extTab === 'cf') { importCf(); return; }
        if (_extTab === 'file') {
            if (canUpload()) $('wi-file-input').click(); else updateDropState();
            return;
        }
        extractUrl();
    }

    // ── Confluence-Import (nur persönliche Bereiche) ────────────────────
    // Suchbare Bereichsauswahl (analog Einstellungen → Wissen → Confluence):
    // Freitext-Suche mit Dropdown, danach Seiten-Mehrfachauswahl.
    var _cfJobId = null, _cfPoll = null;
    var _cfSpaces = null, _selectedSpaceKey = '', _ddOpen = false, _ddIndex = -1, _ddList = [];

    function loadCfSpaces(force) {
        var tabBtn = $('wi-tab-cf'), input = $('wi-cf-space-search');
        if (_cfSpaces && !force) { if (_ddOpen) renderCfSpaceDropdown(); return; }
        if (input) input.placeholder = t('common.loading');
        fetch('/api/wissen/confluence/spaces', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var spaces = (d && d.ok && d.configured) ? (d.spaces || []) : [];
                if (!spaces.length) {
                    _cfSpaces = [];
                    if (tabBtn) tabBtn.style.display = 'none';
                    if (_extTab === 'cf') switchExtTab('url');   // Tab entfaellt -> zurueck auf URL
                    return;
                }
                _cfSpaces = spaces;
                if (tabBtn) tabBtn.style.display = '';
                if (input) input.placeholder = t('wissen.cf_space_search') + ' (' + spaces.length + ')';
                if (_ddOpen) renderCfSpaceDropdown();
            })
            .catch(function () {
                if (tabBtn) tabBtn.style.display = 'none';
                if (_extTab === 'cf') switchExtTab('url');
            });
    }

    function filteredSpaces() {
        if (!_cfSpaces) return [];
        var q = (($('wi-cf-space-search') || {}).value || '').trim().toLowerCase();
        if (!q) return _cfSpaces;
        return _cfSpaces.filter(function (s) {
            return (((s.name || '') + ' ' + (s.key || '')).toLowerCase().indexOf(q) !== -1);
        });
    }

    function onSpaceSearchInput() {
        _selectedSpaceKey = '';
        var wrap = $('wi-cf-page-wrap'), hint = $('wi-cf-hint');
        if (wrap) wrap.style.display = 'none';
        if (hint) hint.style.display = 'none';
        _ddIndex = -1;
        openSpaceDropdown();
    }

    function openSpaceDropdown() {
        _ddOpen = true;
        if (!_cfSpaces) { loadCfSpaces(false); return; }
        renderCfSpaceDropdown();
    }
    function closeSpaceDropdown() {
        _ddOpen = false;
        var dd = $('wi-cf-space-dd');
        if (dd) dd.style.display = 'none';
    }

    function renderCfSpaceDropdown() {
        var dd = $('wi-cf-space-dd');
        if (!dd) return;
        var list = filteredSpaces();
        var CAP = 200;
        var shown = list.slice(0, CAP);
        _ddList = shown;
        if (_ddIndex >= shown.length) _ddIndex = -1;
        if (!shown.length) {
            dd.innerHTML = '<div style="padding:8px 10px;color:var(--text-secondary);font-size:0.85rem;">' + esc(t('wissen.cf_no_hits')) + '</div>';
            dd.style.display = '';
            return;
        }
        dd.innerHTML = shown.map(function (s, i) {
            return '<div class="wi-cf-opt" data-key="' + esc(s.key) + '" data-i="' + i + '" '
                + 'style="padding:7px 10px;cursor:pointer;font-size:0.86rem;'
                + (i === _ddIndex ? 'background:rgba(var(--accent-rgb),0.18);' : '') + '">'
                + esc(s.name) + ' <span style="color:var(--text-secondary);">(' + esc(s.key) + ')</span></div>';
        }).join('')
        + (list.length > CAP ? '<div style="padding:6px 10px;color:var(--text-secondary);font-size:0.78rem;">… '
            + (list.length - CAP) + '</div>' : '');
        dd.style.display = '';
        dd.querySelectorAll('.wi-cf-opt').forEach(function (el) {
            el.addEventListener('mousedown', function (ev) {
                ev.preventDefault();   // verhindert blur vor der Auswahl
                selectSpace(el.getAttribute('data-key'));
            });
            el.addEventListener('mouseover', function () {
                _ddIndex = parseInt(el.getAttribute('data-i'), 10);
                highlightDd();
            });
        });
    }

    function highlightDd() {
        var dd = $('wi-cf-space-dd');
        if (!dd) return;
        dd.querySelectorAll('.wi-cf-opt').forEach(function (el) {
            var i = parseInt(el.getAttribute('data-i'), 10);
            el.style.background = (i === _ddIndex) ? 'rgba(var(--accent-rgb),0.18)' : '';
        });
    }

    function spaceSearchKey(e) {
        if (!_ddOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { openSpaceDropdown(); return; }
        var n = (_ddList || []).length;
        if (e.key === 'ArrowDown') { e.preventDefault(); _ddIndex = Math.min(_ddIndex + 1, n - 1); highlightDd(); scrollDdIntoView(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); _ddIndex = Math.max(_ddIndex - 1, 0); highlightDd(); scrollDdIntoView(); }
        else if (e.key === 'Enter') { e.preventDefault(); var pick = (_ddList || [])[_ddIndex] || (_ddList || [])[0]; if (pick) selectSpace(pick.key); }
        else if (e.key === 'Escape') { closeSpaceDropdown(); }
    }
    function scrollDdIntoView() {
        var dd = $('wi-cf-space-dd');
        var el = dd && dd.querySelector('.wi-cf-opt[data-i="' + _ddIndex + '"]');
        if (el) el.scrollIntoView({ block: 'nearest' });
    }

    function selectSpace(key) {
        var sp = (_cfSpaces || []).filter(function (s) { return s.key === key; })[0];
        if (!sp) return;
        _selectedSpaceKey = key;
        var input = $('wi-cf-space-search');
        if (input) input.value = sp.name + ' (' + sp.key + ')';
        closeSpaceDropdown();
        loadCfPages(key);
    }

    function loadCfPages(space) {
        var wrap = $('wi-cf-page-wrap'), hint = $('wi-cf-hint'), pageSel = $('wi-cf-page'), st = $('wi-cf-status');
        if (st) st.textContent = '';
        if (wrap) wrap.style.display = 'flex';
        if (hint) hint.style.display = 'none';
        if (pageSel) { pageSel.disabled = true; pageSel.innerHTML = '<option>' + esc(t('common.loading')) + '</option>'; }
        fetch('/api/wissen/confluence/pages?space=' + encodeURIComponent(space), { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!pageSel) return;
                if (!d || !d.ok) { pageSel.innerHTML = '<option value="">' + esc((d && d.error) || t('common.error')) + '</option>'; return; }
                var pages = d.pages || [];
                pageSel.disabled = false;
                pageSel.innerHTML = '<option value="__ALL__">' + esc(t('wissen.cf_all', { n: pages.length })) + '</option>'
                    + pages.map(function (p) { return '<option value="' + esc(p.id) + '">' + esc(p.title) + '</option>'; }).join('');
                if (hint) hint.style.display = pages.length ? 'block' : 'none';
            })
            .catch(function () { if (pageSel) pageSel.innerHTML = '<option value="">' + esc(t('common.error')) + '</option>'; });
    }

    function importCf() {
        var sel = $('wi-cf-page');
        var picked = sel ? Array.prototype.slice.call(sel.selectedOptions).map(function (o) { return o.value; }).filter(Boolean) : [];
        var st = $('wi-cf-status');
        if (!picked.length) { if (st) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.cf_pick'); } return; }
        var space = _selectedSpaceKey || '';
        var body, bulk;
        if (picked.indexOf('__ALL__') !== -1) { body = { space: space }; bulk = true; }
        else if (picked.length > 1) { body = { page_ids: picked }; bulk = true; }
        else { body = { page_id: picked[0] }; bulk = false; }
        var jobId = _cfJobId = 'wcf_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
        body.job_id = jobId;
        var btn = $('wi-extract-btn'), cancel = $('wi-extract-cancel');
        if (btn) btn.disabled = true;
        if (st) { st.style.color = 'var(--text-secondary)'; st.textContent = t('wissen.cf_starting'); }
        fetch('/api/wissen/extract/confluence', { method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) })
            .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); })
            .then(function (res) {
                var j = res.j || {};
                if (res.status === 499) { if (st) st.textContent = t('wissen.cf_cancelled'); if (btn) btn.disabled = false; _cfJobId = null; return; }
                if (res.status >= 400) {
                    if (st) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + (j.error || t('common.error')); }
                    if (btn) btn.disabled = false; _cfJobId = null; return;
                }
                if (bulk) {
                    if (cancel) cancel.style.display = '';
                    watchCf(jobId, j.total || 0);
                } else {
                    if (btn) btn.disabled = false;
                    _cfJobId = null;
                    if (st) st.textContent = '';
                    showReview(j); loadPending();
                    $('wi-ext-review').scrollIntoView({ behavior: 'smooth' });
                }
            })
            .catch(function () { if (st) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.cf_failed'); } if (btn) btn.disabled = false; _cfJobId = null; });
    }

    // Bulk-Fortschritt pollen und Statuszeile mit Countdown stehen lassen.
    function watchCf(jobId, total) {
        if (!jobId) return;
        clearInterval(_cfPoll);
        var started = Date.now();
        var st = $('wi-cf-status'), btn = $('wi-extract-btn'), cancel = $('wi-extract-cancel');
        function tick() {
            fetch('/api/wissen/extract/progress?job_id=' + encodeURIComponent(jobId), { headers: authH() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    d = d || {};
                    var done = d.done || 0, running = !!d.running;
                    if (d.total) total = d.total;
                    if (_cfJobId !== jobId) { clearInterval(_cfPoll); _cfPoll = null; return; }
                    if (running) {
                        var remaining = Math.max(0, total - done);
                        var secs = Math.round((Date.now() - started) / 1000);
                        if (st) { st.style.color = 'var(--text-secondary)'; st.textContent = t('wissen.cf_progress', { r: remaining, n: total, s: secs }); }
                        loadPending();
                        return;
                    }
                    clearInterval(_cfPoll); _cfPoll = null; _cfJobId = null;
                    if (btn) btn.disabled = false;
                    if (cancel) cancel.style.display = 'none';
                    loadPending();
                    if (st) {
                        if (done < total) { st.style.color = 'var(--warning)'; st.textContent = t('wissen.cf_stopped', { done: done, n: total }); }
                        else { st.style.color = 'var(--success)'; st.textContent = t('wissen.cf_done', { n: total }); }
                    }
                })
                .catch(function () { /* Netzfehler -> naechster Tick */ });
        }
        tick();
        _cfPoll = setInterval(tick, 2000);
    }

    function abortCf() {
        var jid = _cfJobId; _cfJobId = null;
        clearInterval(_cfPoll); _cfPoll = null;
        var cancel = $('wi-extract-cancel'), btn = $('wi-extract-btn');
        if (cancel) cancel.style.display = 'none';
        if (btn) btn.disabled = false;
        if (!jid) return;
        fetch('/api/wissen/extract/cancel', { method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify({ job_id: jid }) })
            .then(function () { var st = $('wi-cf-status'); if (st) st.textContent = t('wissen.cf_cancelled'); })
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
        $('wi-upload-groups').addEventListener('change', function () {
            updateFolderOptions();   // Ordner-Angebot an die gewaehlten Gruppen anpassen
            updateDropState();
        });

        // Einklappbare Container (Zustand pro Browser gemerkt, analog Einstellungen).
        // Der Pfeil steht fest im Markup (eigener Span, damit applyLang ihn nicht wegwischt).
        ['wi-sec-matrix', 'wi-sec-groups', 'wi-sec-upload', 'wi-sec-files'].forEach(function (id) {
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

        var exBtn = $('wi-extract-btn'); if (exBtn) exBtn.addEventListener('click', doExtract);
        var exCancel = $('wi-extract-cancel'); if (exCancel) exCancel.addEventListener('click', abortCf);
        $('wi-ext-url').addEventListener('keydown', function (e) { if (e.key === 'Enter') doExtract(); });

        // Eingabe-Tabs (URL / Datei / Confluence)
        var tU = $('wi-tab-url'); if (tU) tU.addEventListener('click', function () { switchExtTab('url'); });
        var tF = $('wi-tab-file'); if (tF) tF.addEventListener('click', function () { switchExtTab('file'); });
        var tC = $('wi-tab-cf'); if (tC) tC.addEventListener('click', function () { switchExtTab('cf'); });

        // Confluence-Import (nur persönliche Bereiche) – suchbare Bereichsauswahl
        var cfSearch = $('wi-cf-space-search');
        if (cfSearch) {
            cfSearch.addEventListener('input', onSpaceSearchInput);
            cfSearch.addEventListener('focus', openSpaceDropdown);
            cfSearch.addEventListener('keydown', spaceSearchKey);
            cfSearch.addEventListener('blur', function () { setTimeout(closeSpaceDropdown, 150); });
        }
        var cfRefresh = $('wi-cf-refresh'); if (cfRefresh) cfRefresh.addEventListener('click', function () { loadCfSpaces(true); });

        // Massenzuordnung: Tabellen-Overlay öffnen (nur für globale Wissens-Editoren sichtbar)
        var mBtn = $('wi-matrix-btn');
        if (mBtn) mBtn.addEventListener('click', function () { if (window.KbMatrix) window.KbMatrix.open(); });

        if (window.applyLang) window.applyLang();
        loadScope();
    });
})();
