/* Jarvis – mausbedienbarer AD-User-/Gruppen-Picker + Token-Listen.
 *
 * - Hängt an alle AD-Felder einen "Durchsuchen"-Button mit Live-Verzeichnis-Suche
 *   (POST /api/ldap/users|groups). Service-Konto oder On-Demand-Passwort (nur Sitzung).
 * - Felder mit list:true (Erlaubte Benutzer / Erlaubte Gruppe) werden als
 *   Chip-Liste dargestellt: Einträge untereinander, je × zum Herausnehmen, plus
 *   manuelles Hinzufügen. Das zugrunde liegende (versteckte) Feld bleibt die
 *   Quelle der Wahrheit (Benutzer: kommagetrennt; Gruppen: zeilengetrennt, da
 *   DNs Kommas enthalten).
 */
(function () {
    'use strict';

    var FIELDS = {
        'ad-allowed-users':           { kind: 'users',  multi: true, sep: ',',  list: true },
        'ad-allowed-group':           { kind: 'groups', multi: true, sep: '\n', list: true },
        'ad-internet-users':          { kind: 'users',  multi: true, sep: ',',  list: true },
        'ad-internet-group':          { kind: 'groups', multi: true, sep: '\n', list: true },
        'ad-admins':                  { kind: 'users',  multi: true, sep: ',',  list: true },
        'ad-admins-group':            { kind: 'groups', multi: true, sep: '\n', list: true },
        'ad-knowledge-editors':       { kind: 'users',  multi: true, sep: ',',  list: true },
        'ad-knowledge-editors-group': { kind: 'groups', multi: true, sep: '\n', list: true },
        'sap-allowed-users':          { kind: 'users',  multi: true, sep: ',',  list: true },
        'sap-allowed-group':          { kind: 'groups', multi: true, sep: '\n', list: true },
        'email-allowed-users':        { kind: 'users',  multi: true, sep: ',',  list: true },
        'email-allowed-group':        { kind: 'groups', multi: true, sep: '\n', list: true },
        'tracks-allowed-users':       { kind: 'users',  multi: true, sep: ',',  list: true },
        'tracks-allowed-group':       { kind: 'groups', multi: true, sep: '\n', list: true }
    };

    var _cred = { user: '', password: '' };
    var _state = null;
    var _searchTimer = null;

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function el(id) { return document.getElementById(id); }
    function joinSep(sep) { return sep === '\n' ? '\n' : ', '; }
    function splitVals(val, sep) {
        return (val || '').split(sep).map(function (s) { return s.trim(); }).filter(Boolean);
    }
    function shortDn(dn) {
        var m = /^CN=([^,]+)/i.exec(dn || '');
        return m ? m[1] : dn;
    }
    function setTarget(inp, value) {
        inp.value = value;
        inp.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // ── Such-Popup ────────────────────────────────────────────────────────
    function ensureModal() {
        if (el('ldap-picker-modal')) return;
        var m = document.createElement('div');
        m.id = 'ldap-picker-modal';
        m.className = 'modal';
        m.style.zIndex = '10002';
        m.innerHTML =
            '<div class="modal-content glass" style="max-width:640px;">' +
              '<div class="modal-header">' +
                '<h2 id="ldap-picker-title">' + window.t('ldap.title_browse') + '</h2>' +
                '<button class="btn-icon" id="ldap-picker-close" aria-label="' + window.t('common.close') + '">' +
                  '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>' +
                '</button>' +
              '</div>' +
              '<div class="modal-body" style="overflow-y:auto;">' +
                '<div id="ldap-picker-cred" style="display:none;margin-bottom:12px;padding:10px 12px;border:1px solid var(--border);border-radius:10px;background:rgba(var(--fg-rgb),0.03);">' +
                  '<div style="font-size:0.84rem;margin-bottom:8px;">' + window.t('ldap.cred_hint') + '</div>' +
                  '<input type="text" id="ldap-picker-user" placeholder="' + window.t('ldap.ph_user') + '" style="width:100%;box-sizing:border-box;margin-bottom:6px;">' +
                  '<input type="password" id="ldap-picker-pass" placeholder="' + window.t('ldap.ph_pass') + '" style="width:100%;box-sizing:border-box;margin-bottom:8px;">' +
                  '<button type="button" id="ldap-picker-connect" style="padding:6px 14px;border-radius:8px;border:1px solid rgba(var(--accent-rgb),0.5);background:rgba(var(--accent-rgb),0.15);color:var(--text-primary,#e2e8f0);cursor:pointer;font-size:0.84rem;">' + window.t('ldap.connect_search') + '</button>' +
                '</div>' +
                '<input type="text" id="ldap-picker-search" placeholder="' + window.t('ldap.ph_search') + '" autocomplete="off" style="width:100%;box-sizing:border-box;margin-bottom:6px;">' +
                '<div id="ldap-picker-info" style="font-size:0.78rem;color:var(--text-muted);min-height:1.2em;margin-bottom:6px;"></div>' +
                '<div id="ldap-picker-list" style="max-height:46vh;overflow-y:auto;border:1px solid var(--border);border-radius:10px;"></div>' +
                '<div id="ldap-picker-actions" style="display:none;justify-content:flex-end;gap:8px;margin-top:12px;">' +
                  '<button type="button" id="ldap-picker-apply" style="padding:7px 16px;border-radius:8px;border:1px solid rgba(var(--accent-rgb),0.5);background:rgba(var(--accent-rgb),0.2);color:var(--text-primary,#e2e8f0);cursor:pointer;font-weight:600;font-size:0.85rem;">' + window.t('ldap.apply') + '</button>' +
                '</div>' +
              '</div>' +
            '</div>';
        document.body.appendChild(m);

        el('ldap-picker-close').addEventListener('click', close);
        m.addEventListener('click', function (e) { if (e.target === m) close(); });
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            // Zuerst das obere Popup: sonst schliesst Escape den Picker UNTER der
            // noch offenen Mitgliederliste, und die bliebe ohne Bezug stehen.
            if (membersOpen()) { closeMembers(); return; }
            if (m.classList.contains('open')) close();
        });
        el('ldap-picker-search').addEventListener('input', function () {
            clearTimeout(_searchTimer);
            _searchTimer = setTimeout(runSearch, 300);
        });
        el('ldap-picker-connect').addEventListener('click', function () {
            _cred.user = el('ldap-picker-user').value.trim();
            _cred.password = el('ldap-picker-pass').value;
            if (!_cred.password) { info(window.t('ldap.enter_pass'), true); return; }
            runSearch();
        });
        el('ldap-picker-apply').addEventListener('click', applyMulti);
    }

    function close() {
        closeMembers();   // kein verwaistes Unter-Popup zuruecklassen
        var m = el('ldap-picker-modal');
        if (m) m.classList.remove('open');
        _state = null;
    }
    function info(msg, isErr) {
        var i = el('ldap-picker-info');
        if (i) { i.textContent = msg || ''; i.style.color = isErr ? 'var(--danger)' : 'var(--text-muted)'; }
    }

    function open(cfg, targetInput) {
        ensureModal();
        _state = { kind: cfg.kind, multi: !!cfg.multi, sep: cfg.sep || ',', target: targetInput, selected: {} };
        if (_state.multi) {
            splitVals(targetInput.value, _state.sep).forEach(function (v) {
                _state.selected[v.toLowerCase()] = v;
            });
        }
        el('ldap-picker-title').textContent = cfg.kind === 'users' ? window.t('ldap.pick_user') : window.t('ldap.pick_groups');
        el('ldap-picker-search').value = '';
        el('ldap-picker-list').innerHTML = '';
        el('ldap-picker-cred').style.display = 'none';
        el('ldap-picker-actions').style.display = _state.multi ? 'flex' : 'none';
        if (!el('ldap-picker-user').value) {
            el('ldap-picker-user').value = _cred.user || localStorage.getItem('jarvis_user') || '';
        }
        info('');
        el('ldap-picker-modal').classList.add('open');
        el('ldap-picker-search').focus();
        runSearch();
    }

    function runSearch() {
        if (!_state) return;
        var q = el('ldap-picker-search').value.trim();
        info(window.t('ldap.searching'));
        var payload = { q: q };
        if (_cred.password) { payload.password = _cred.password; payload.bind_user = _cred.user; }
        fetch('/api/ldap/' + _state.kind, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token() },
            body: JSON.stringify(payload)
        }).then(function (r) {
            return r.json().then(function (j) { return { status: r.status, j: j }; });
        }).then(function (res) {
            if (res.status === 428) { showCred(''); return; }
            if (res.status === 401) { showCred(window.t('ldap.auth_failed')); return; }
            if (res.status !== 200) { info((res.j && res.j.error) || (window.t('common.error') + ' ' + res.status), true); return; }
            el('ldap-picker-cred').style.display = 'none';
            renderList(res.j[_state.kind] || []);
        }).catch(function () { info(window.t('ldap.network_error'), true); });
    }

    function showCred(errMsg) {
        el('ldap-picker-cred').style.display = 'block';
        el('ldap-picker-list').innerHTML = '';
        info(errMsg || '', !!errMsg);
        var u = el('ldap-picker-user'); if (u && !u.value) u.focus(); else el('ldap-picker-pass').focus();
    }

    function renderList(rows) {
        var box = el('ldap-picker-list');
        if (!rows.length) { box.innerHTML = '<div style="padding:14px;color:var(--text-muted);font-size:0.85rem;">' + window.t('ldap.no_hits') + '</div>'; info(''); return; }
        info(rows.length + ' ' + window.t('ldap.hits') + (rows.length >= 100 ? ' (' + window.t('ldap.narrow') + ')' : ''));
        var users = _state.kind === 'users';
        var html = '';
        rows.forEach(function (r) {
            var key = (users ? r.sam : r.dn) || '';
            var main = users ? r.display : r.cn;
            var sub = users ? (r.sam + (r.mail ? ' · ' + r.mail : '')) : (r.dn + (r.desc ? ' · ' + r.desc : ''));
            // Bei Gruppen ist der NAME zusaetzlich ein Knopf: er oeffnet die
            // Mitgliederliste. Der restliche Eintrag schaltet die Auswahl um.
            var mainHtml = users
                ? '<span class="ldap-row-main">' + esc(main) + '</span>'
                : '<button type="button" class="ldap-row-main ldap-members-btn" data-group="' + esc(key) +
                  '" title="' + esc(window.t('ldap.show_members_title')) + '">' + esc(main) + ' 👥</button>';
            if (_state.multi) {
                var checked = _state.selected[key.toLowerCase()] ? ' checked' : '';
                html += '<label class="ldap-row" data-key="' + esc(key) + '" title="' + esc(key) + '">' +
                    '<input type="checkbox"' + checked + ' style="flex-shrink:0;">' +
                    mainHtml +
                    '<span class="ldap-row-sub">' + esc(sub) + '</span></label>';
            } else {
                html += '<div class="ldap-row" data-key="' + esc(key) + '" role="button" tabindex="0" title="' + esc(key) + '">' +
                    mainHtml +
                    '<span class="ldap-row-sub">' + esc(sub) + '</span></div>';
            }
        });
        box.innerHTML = html;
        box.querySelectorAll('.ldap-row').forEach(function (row) {
            var key = row.getAttribute('data-key');
            if (_state.multi) {
                // Der Eintrag IST ein <label> um die Checkbox – ein Klick irgendwo
                // darin schaltet sie also schon vom Browser aus um. Frueher hat der
                // Klick-Handler zusaetzlich selbst umgeschaltet ("if (e.target !== cb)
                // cb.checked = !cb.checked"), und weil das <label> den Klick danach an
                // die Checkbox weiterreicht, kippte sie ZWEIMAL – unterm Strich also
                // gar nicht. Nur ein Klick genau auf das Kaestchen wirkte. Deshalb
                // jetzt ausschliesslich auf 'change' hoeren und NICHT selbst schalten.
                var cb = row.querySelector('input');
                cb.addEventListener('change', function () {
                    if (cb.checked) _state.selected[key.toLowerCase()] = key;
                    else delete _state.selected[key.toLowerCase()];
                });
            } else {
                row.addEventListener('click', function () { setTarget(_state.target, key); close(); });
            }
        });
        // Mitglieder-Knopf: darf die Auswahl NICHT umschalten und das <label>
        // nicht aktivieren -> preventDefault + stopPropagation.
        box.querySelectorAll('.ldap-members-btn').forEach(function (b) {
            b.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                openMembers(b.getAttribute('data-group'));
            });
        });
    }

    // ── Mitglieder einer Gruppe (Unter-Popup ueber dem Picker) ────────────
    function ensureMembersModal() {
        if (el('ldap-members-modal')) return;
        var m = document.createElement('div');
        m.id = 'ldap-members-modal';
        m.className = 'modal';
        m.style.zIndex = '10003';   // ueber dem Picker (10002)
        m.innerHTML =
            '<div class="modal-content glass" style="max-width:560px;">' +
              '<div class="modal-header">' +
                '<h2 id="ldap-members-title">' + window.t('ldap.members_title') + '</h2>' +
                '<button class="btn-icon" id="ldap-members-close" aria-label="' + window.t('common.close') + '">' +
                  '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>' +
                '</button>' +
              '</div>' +
              '<div class="modal-body" style="overflow-y:auto;">' +
                '<div id="ldap-members-dn" style="font-size:0.74rem;color:var(--text-muted);word-break:break-all;margin-bottom:6px;"></div>' +
                '<div id="ldap-members-info" style="font-size:0.78rem;color:var(--text-muted);min-height:1.2em;margin-bottom:6px;"></div>' +
                '<div id="ldap-members-list" style="max-height:46vh;overflow-y:auto;border:1px solid var(--border);border-radius:10px;"></div>' +
                '<div style="font-size:0.72rem;color:var(--text-muted);margin-top:8px;" data-i18n="ldap.members_hint">' +
                  window.t('ldap.members_hint') +
                '</div>' +
              '</div>' +
            '</div>';
        document.body.appendChild(m);
        el('ldap-members-close').addEventListener('click', closeMembers);
        m.addEventListener('click', function (e) { if (e.target === m) closeMembers(); });
    }

    function closeMembers() {
        var m = el('ldap-members-modal');
        if (m) m.classList.remove('open');
    }

    function membersOpen() {
        var m = el('ldap-members-modal');
        return !!(m && m.classList.contains('open'));
    }

    function openMembers(group) {
        if (!group) return;
        ensureMembersModal();
        el('ldap-members-title').textContent = shortDn(group);
        el('ldap-members-dn').textContent = group;
        el('ldap-members-list').innerHTML = '';
        var inf = el('ldap-members-info');
        inf.style.color = 'var(--text-muted)';
        inf.textContent = window.t('ldap.members_loading');
        el('ldap-members-modal').classList.add('open');

        var payload = { group: group };
        // Dasselbe On-Demand-Passwort wie die Suche – sonst muesste der Admin es
        // fuer die Mitgliederliste ein zweites Mal eingeben.
        if (_cred.password) { payload.password = _cred.password; payload.bind_user = _cred.user; }
        fetch('/api/ldap/group_members', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token() },
            body: JSON.stringify(payload)
        }).then(function (r) {
            return r.json().then(function (j) { return { status: r.status, j: j }; });
        }).then(function (res) {
            if (res.status !== 200) {
                inf.style.color = 'var(--danger)';
                inf.textContent = (res.j && (res.j.error === 'NO_CREDENTIALS'
                    ? window.t('ldap.cred_hint')
                    : res.j.error)) || (window.t('common.error') + ' ' + res.status);
                return;
            }
            renderMembers(res.j);
        }).catch(function () {
            inf.style.color = 'var(--danger)';
            inf.textContent = window.t('ldap.network_error');
        });
    }

    function renderMembers(d) {
        var list = el('ldap-members-list');
        var rows = (d && d.members) || [];
        var nUsers = rows.filter(function (r) { return r.kind !== 'group'; }).length;
        var nGroups = rows.length - nUsers;
        var inf = el('ldap-members-info');
        inf.style.color = 'var(--text-muted)';
        inf.textContent = nUsers + ' ' + window.t('ldap.members_users') +
            (nGroups ? ' · ' + nGroups + ' ' + window.t('ldap.members_groups') : '');
        if (!rows.length) {
            list.innerHTML = '<div style="padding:14px;color:var(--text-muted);font-size:0.85rem;">' +
                window.t('ldap.members_empty') + '</div>';
            return;
        }
        list.innerHTML = rows.map(function (r) {
            var isGrp = r.kind === 'group';
            var sub = (r.sam || '') + (r.mail ? ' · ' + r.mail : '');
            return '<div class="ldap-row" style="cursor:default;">' +
                '<span style="flex-shrink:0;">' + (isGrp ? '🗂️' : '👤') + '</span>' +
                '<span class="ldap-row-main">' + esc(r.display) + '</span>' +
                '<span class="ldap-row-sub">' + esc(sub) +
                (isGrp ? ' · ' + esc(window.t('ldap.members_nested')) : '') + '</span></div>';
        }).join('');
    }

    function applyMulti() {
        if (!_state) return;
        var vals = Object.keys(_state.selected).map(function (k) { return _state.selected[k]; });
        setTarget(_state.target, vals.join(joinSep(_state.sep)));
        close();
    }

    // ── Token-Liste (Chips mit ✕) für list:true-Felder ────────────────────
    function initTokenList(inp, cfg) {
        if (inp.dataset.tokenList) return;
        inp.dataset.tokenList = '1';
        inp.style.display = 'none';
        var wrap = document.createElement('div');
        wrap.className = 'token-list';
        var items = document.createElement('div');
        items.className = 'token-items';
        var addRow = document.createElement('div');
        addRow.className = 'token-add';
        var addInp = document.createElement('input');
        addInp.type = 'text';
        addInp.className = 'token-add-input';
        addInp.placeholder = cfg.kind === 'groups' ? window.t('ldap.ph_group_dn') : window.t('ldap.ph_login_manual');
        var addBtn = document.createElement('button');
        addBtn.type = 'button';
        addBtn.className = 'token-add-btn';
        addBtn.textContent = window.t('ldap.add_btn');
        addRow.appendChild(addInp);
        addRow.appendChild(addBtn);
        wrap.appendChild(items);
        wrap.appendChild(addRow);
        inp.parentNode.insertBefore(wrap, inp);

        function render() {
            var toks = splitVals(inp.value, cfg.sep);
            if (!toks.length) {
                items.innerHTML = '<span class="token-empty">' + window.t('ldap.no_entries') + '</span>';
            } else {
                items.innerHTML = toks.map(function (t, i) {
                    var label = cfg.kind === 'groups' ? shortDn(t) : t;
                    return '<span class="token" title="' + esc(t) + '"><span class="token-label">' + esc(label) +
                           '</span><button type="button" class="token-x" data-i="' + i + '" aria-label="' + window.t('ldap.remove') + '">×</button></span>';
                }).join('');
            }
            items.querySelectorAll('.token-x').forEach(function (b) {
                b.addEventListener('click', function () {
                    var toks2 = splitVals(inp.value, cfg.sep);
                    toks2.splice(parseInt(b.getAttribute('data-i'), 10), 1);
                    inp.value = toks2.join(joinSep(cfg.sep));
                    render();
                });
            });
        }
        function add() {
            var v = addInp.value.trim();
            if (!v) return;
            var toks = splitVals(inp.value, cfg.sep);
            if (toks.some(function (t) { return t.toLowerCase() === v.toLowerCase(); })) { addInp.value = ''; return; }
            toks.push(v);
            inp.value = toks.join(joinSep(cfg.sep));
            addInp.value = '';
            render();
        }
        addBtn.addEventListener('click', add);
        addInp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add(); } });
        inp.addEventListener('change', render);
        render();
    }

    // ── Buttons + Token-Listen an EIN Feld hängen ─────────────────────────
    function attachOne(inp, cfg) {
        if (!inp || inp.dataset.ldapAttached) return;
        inp.dataset.ldapAttached = '1';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ldap-pick-btn';
        btn.innerHTML = (cfg.kind === 'users' ? '👥' : '🗂️') + ' ' + window.t('ldap.browse');
        btn.addEventListener('click', function () { open(cfg, inp); });
        if (inp.nextSibling) inp.parentNode.insertBefore(btn, inp.nextSibling);
        else inp.parentNode.appendChild(btn);
        if (cfg.list) initTokenList(inp, cfg);
    }

    // ── Buttons + Token-Listen an die statischen Felder hängen ────────────
    function attachButtons() {
        Object.keys(FIELDS).forEach(function (id) {
            attachOne(el(id), FIELDS[id]);
        });
    }

    // attachField: für dynamisch erzeugte Felder (z.B. Wissensgruppen-Editoren).
    // cfg optional – Default = mehrfach-Token-Liste, kind ableitbar oder 'users'.
    function attachField(inp, cfg) {
        cfg = cfg || {};
        attachOne(inp, {
            kind: cfg.kind === 'groups' ? 'groups' : 'users',
            multi: cfg.multi !== false,
            sep: cfg.sep || (cfg.kind === 'groups' ? '\n' : ','),
            list: cfg.list !== false
        });
    }

    window.LdapPicker = { open: open, attachButtons: attachButtons, attachField: attachField };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attachButtons);
    } else {
        attachButtons();
    }
})();
