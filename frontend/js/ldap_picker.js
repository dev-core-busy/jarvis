/* Jarvis – mausbedienbarer AD-User-/Gruppen-Picker.
 *
 * Hängt an alle AD-Eingabefelder (Benutzer-Listen, Gruppen-DNs) einen
 * "Durchsuchen"-Button und öffnet ein Such-Popup mit Live-Ergebnissen aus dem
 * Verzeichnis (POST /api/ldap/users|groups). Nutzt das Service-Konto; ist keines
 * gesetzt, fragt das Popup einmalig nach AD-Benutzer + Passwort (nur im Speicher
 * dieser Sitzung, nichts wird gespeichert).
 *
 * Benutzer-Felder: Mehrfachauswahl (Checkboxen) -> kommagetrennte sAMAccountNames.
 * Gruppen-Felder:  Einzelauswahl -> Distinguished Name (DN).
 */
(function () {
    'use strict';

    // Feld-Zuordnung: Eingabe-ID -> Verzeichnistyp
    var FIELDS = {
        'ad-allowed-users': 'users', 'ad-allowed-group': 'groups',
        'ad-internet-users': 'users', 'ad-internet-group': 'groups',
        'ad-admins': 'users', 'ad-admins-group': 'groups',
        'ad-knowledge-editors': 'users', 'ad-knowledge-editors-group': 'groups'
    };

    var _cred = { user: '', password: '' };  // On-Demand-Credentials (nur Sitzung)
    var _state = null;                        // aktueller Picker-Kontext
    var _searchTimer = null;

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function el(id) { return document.getElementById(id); }

    // ── Modal einmalig aufbauen ───────────────────────────────────────────
    function ensureModal() {
        if (el('ldap-picker-modal')) return;
        var m = document.createElement('div');
        m.id = 'ldap-picker-modal';
        m.className = 'modal';
        m.style.zIndex = '10002';
        m.innerHTML =
            '<div class="modal-content glass" style="max-width:640px;">' +
              '<div class="modal-header">' +
                '<h2 id="ldap-picker-title">Verzeichnis durchsuchen</h2>' +
                '<button class="btn-icon" id="ldap-picker-close" aria-label="Schließen">' +
                  '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>' +
                '</button>' +
              '</div>' +
              '<div class="modal-body" style="overflow-y:auto;">' +
                '<div id="ldap-picker-cred" style="display:none;margin-bottom:12px;padding:10px 12px;border:1px solid rgba(255,255,255,0.12);border-radius:10px;background:rgba(255,255,255,0.03);">' +
                  '<div style="font-size:0.84rem;margin-bottom:8px;">Kein Service-Konto hinterlegt – bitte einmalig AD-Zugangsdaten eingeben (werden nicht gespeichert):</div>' +
                  '<input type="text" id="ldap-picker-user" placeholder="AD-Benutzer (z.B. vorname.nachname)" style="width:100%;box-sizing:border-box;margin-bottom:6px;">' +
                  '<input type="password" id="ldap-picker-pass" placeholder="AD-Passwort" style="width:100%;box-sizing:border-box;margin-bottom:8px;">' +
                  '<button type="button" id="ldap-picker-connect" style="padding:6px 14px;border-radius:8px;border:1px solid rgba(139,92,246,0.5);background:rgba(139,92,246,0.15);color:var(--text-primary,#e2e8f0);cursor:pointer;font-size:0.84rem;">Verbinden &amp; suchen</button>' +
                '</div>' +
                '<input type="text" id="ldap-picker-search" placeholder="Suchen… (Name, Login, E-Mail)" autocomplete="off" style="width:100%;box-sizing:border-box;margin-bottom:6px;">' +
                '<div id="ldap-picker-info" style="font-size:0.78rem;color:var(--text-muted);min-height:1.2em;margin-bottom:6px;"></div>' +
                '<div id="ldap-picker-list" style="max-height:46vh;overflow-y:auto;border:1px solid rgba(255,255,255,0.08);border-radius:10px;"></div>' +
                '<div id="ldap-picker-actions" style="display:none;justify-content:flex-end;gap:8px;margin-top:12px;">' +
                  '<button type="button" id="ldap-picker-apply" style="padding:7px 16px;border-radius:8px;border:1px solid rgba(139,92,246,0.5);background:rgba(139,92,246,0.2);color:var(--text-primary,#e2e8f0);cursor:pointer;font-weight:600;font-size:0.85rem;">Übernehmen</button>' +
                '</div>' +
              '</div>' +
            '</div>';
        document.body.appendChild(m);

        el('ldap-picker-close').addEventListener('click', close);
        m.addEventListener('click', function (e) { if (e.target === m) close(); });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && m.classList.contains('open')) close();
        });
        el('ldap-picker-search').addEventListener('input', function () {
            clearTimeout(_searchTimer);
            _searchTimer = setTimeout(runSearch, 300);
        });
        el('ldap-picker-connect').addEventListener('click', function () {
            _cred.user = el('ldap-picker-user').value.trim();
            _cred.password = el('ldap-picker-pass').value;
            if (!_cred.password) { info('Bitte Passwort eingeben.', true); return; }
            runSearch();
        });
        el('ldap-picker-apply').addEventListener('click', applyMulti);
    }

    function close() {
        var m = el('ldap-picker-modal');
        if (m) m.classList.remove('open');
        _state = null;
    }

    function info(msg, isErr) {
        var i = el('ldap-picker-info');
        if (i) { i.textContent = msg || ''; i.style.color = isErr ? '#f0a0a0' : 'var(--text-muted)'; }
    }

    function open(kind, targetInput) {
        ensureModal();
        _state = {
            kind: kind,
            mode: kind === 'users' ? 'multi' : 'single',
            target: targetInput,
            selected: {}
        };
        // vorhandene Auswahl (nur User/Multi) vorbelegen
        if (_state.mode === 'multi') {
            (targetInput.value || '').split(',').forEach(function (v) {
                v = v.trim(); if (v) _state.selected[v.toLowerCase()] = v;
            });
        }
        el('ldap-picker-title').textContent = kind === 'users' ? 'Benutzer auswählen' : 'Gruppe auswählen';
        el('ldap-picker-search').value = '';
        el('ldap-picker-list').innerHTML = '';
        el('ldap-picker-cred').style.display = 'none';
        el('ldap-picker-actions').style.display = _state.mode === 'multi' ? 'flex' : 'none';
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
        info('Suche läuft…');
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
            if (res.status === 401) { showCred('Anmeldung fehlgeschlagen – bitte Zugangsdaten prüfen.'); return; }
            if (res.status !== 200) { info((res.j && res.j.error) || ('Fehler ' + res.status), true); return; }
            el('ldap-picker-cred').style.display = 'none';
            renderList(res.j[_state.kind] || []);
        }).catch(function () { info('Netzwerkfehler.', true); });
    }

    function showCred(errMsg) {
        el('ldap-picker-cred').style.display = 'block';
        el('ldap-picker-list').innerHTML = '';
        info(errMsg || '', !!errMsg);
        var u = el('ldap-picker-user'); if (u && !u.value) u.focus(); else el('ldap-picker-pass').focus();
    }

    function renderList(rows) {
        var box = el('ldap-picker-list');
        if (!rows.length) { box.innerHTML = '<div style="padding:14px;color:var(--text-muted);font-size:0.85rem;">Keine Treffer.</div>'; info(''); return; }
        info(rows.length + ' Treffer' + (rows.length >= 100 ? ' (ggf. eingegrenzt – bitte suchen)' : ''));
        var html = '';
        rows.forEach(function (r) {
            if (_state.kind === 'users') {
                var checked = _state.selected[(r.sam || '').toLowerCase()] ? ' checked' : '';
                html += '<label class="ldap-row" data-sam="' + esc(r.sam) + '">' +
                    '<input type="checkbox"' + checked + ' style="flex-shrink:0;">' +
                    '<span class="ldap-row-main">' + esc(r.display) + '</span>' +
                    '<span class="ldap-row-sub">' + esc(r.sam) + (r.mail ? ' · ' + esc(r.mail) : '') + '</span>' +
                    '</label>';
            } else {
                html += '<div class="ldap-row" data-dn="' + esc(r.dn) + '" role="button" tabindex="0">' +
                    '<span class="ldap-row-main">' + esc(r.cn) + '</span>' +
                    '<span class="ldap-row-sub">' + esc(r.dn) + (r.desc ? ' · ' + esc(r.desc) : '') + '</span>' +
                    '</div>';
            }
        });
        box.innerHTML = html;
        if (_state.kind === 'users') {
            box.querySelectorAll('.ldap-row').forEach(function (row) {
                var cb = row.querySelector('input');
                row.addEventListener('click', function (e) {
                    if (e.target !== cb) cb.checked = !cb.checked;
                    var sam = row.getAttribute('data-sam');
                    if (cb.checked) _state.selected[sam.toLowerCase()] = sam;
                    else delete _state.selected[sam.toLowerCase()];
                });
            });
        } else {
            box.querySelectorAll('.ldap-row').forEach(function (row) {
                row.addEventListener('click', function () {
                    _state.target.value = row.getAttribute('data-dn');
                    close();
                });
            });
        }
    }

    function applyMulti() {
        if (!_state) return;
        var vals = Object.keys(_state.selected).map(function (k) { return _state.selected[k]; });
        _state.target.value = vals.join(', ');
        close();
    }

    // ── "Durchsuchen"-Buttons an die Felder hängen ────────────────────────
    function attachButtons() {
        Object.keys(FIELDS).forEach(function (id) {
            var inp = el(id);
            if (!inp || inp.dataset.ldapAttached) return;
            inp.dataset.ldapAttached = '1';
            var kind = FIELDS[id];
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ldap-pick-btn';
            btn.innerHTML = (kind === 'users' ? '👥' : '🗂️') + ' Durchsuchen';
            btn.addEventListener('click', function () { open(kind, inp); });
            // hinter das Eingabefeld setzen
            if (inp.nextSibling) inp.parentNode.insertBefore(btn, inp.nextSibling);
            else inp.parentNode.appendChild(btn);
        });
    }

    window.LdapPicker = { open: open, attachButtons: attachButtons };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', attachButtons);
    } else {
        attachButtons();
    }
})();
