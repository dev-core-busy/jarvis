/* ═══════════════════════════════════════════════════════════════════
   VEMAS-Reiter (Einstellungen) – Serverkonfiguration
   ───────────────────────────────────────────────────────────────────
   Hier stehen Serveradresse, Anmeldeart und die Ressourcen-Zuordnung des
   gemeinsamen Zugangs; die persoenlichen Zugangsdaten pflegen die Anwender
   im Bereich /vemas. Aufbau bewusst wie js/sap.js.

   Praefix `vemas-` fuer alles hier; `vm-` gehoert der Bereichsseite
   (js/vemas_portal.js) – eine Kollision waere beim Debuggen kaum zu sehen.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    function val(id) { var e = $(id); return e ? e.value.trim() : ''; }
    function raw(id) { var e = $(id); return e ? e.value : ''; }
    function checked(id) { var e = $(id); return !!(e && e.checked); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function T(key, fallback) { return (window.t ? window.t(key) : null) || fallback; }

    function status(msg, kind) {
        var el = $('vemas-status'); if (!el) return;
        el.textContent = msg || '';
        el.style.color = kind === 'error' ? 'var(--danger)'
            : kind === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
    }

    var SVG_EYE_CLOSED = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
    var SVG_EYE_OPEN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';

    // Ergebnis-Tabelle aus {columns, rows}
    function renderTable(box, columns, rows) {
        if (!box) return;
        if (!rows || !rows.length) {
            box.innerHTML = '<span class="kb-hint">' + esc(T('vemas.no_rows', 'Keine Datensätze.')) + '</span>';
            return;
        }
        var cols = (columns && columns.length) ? columns : Object.keys(rows[0] || {});
        var html = '<table style="border-collapse:collapse;width:100%;font-size:0.82rem;">';
        html += '<thead><tr>' + cols.map(function (c) {
            return '<th style="text-align:left;padding:4px 8px;border-bottom:1px solid var(--border);'
                + 'white-space:nowrap;color:var(--text-secondary);">' + esc(c) + '</th>';
        }).join('') + '</tr></thead><tbody>';
        rows.forEach(function (r) {
            html += '<tr>' + cols.map(function (c) {
                var v = r ? r[c] : '';
                if (v && typeof v === 'object') { try { v = JSON.stringify(v); } catch (e) { v = ''; } }
                return '<td style="padding:4px 8px;border-bottom:1px solid rgba(var(--fg-rgb),.06);'
                    + 'vertical-align:top;">' + esc(v) + '</td>';
            }).join('') + '</tr>';
        });
        box.innerHTML = html + '</tbody></table>';
    }

    var Manager = {
        _bound: false,
        _visible: null,   // Set der sichtbaren Abfrage-Ids

        onShow: function () {
            this._bind();
            this.loadConfig();
            this.loadVisibility();
            this.loadAccounts();
        },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            var self = this;
            var ak = $('vemas-auth-kind');
            if (ak) ak.addEventListener('change', function () { self._applyAuth(ak.value); });
            var save = $('vemas-save'); if (save) save.addEventListener('click', this.save.bind(this));
            var test = $('vemas-test'); if (test) test.addEventListener('click', this.test.bind(this));
            var disc = $('vemas-discover'); if (disc) disc.addEventListener('click', this.discover.bind(this));
            var q = $('vemas-q-run'); if (q) q.addEventListener('click', this.runQuery.bind(this));
            var va = $('vemas-vis-all'); if (va) va.addEventListener('click', function () { self._visSetAll(true); });
            var vn = $('vemas-vis-none'); if (vn) vn.addEventListener('click', function () { self._visSetAll(false); });
            var vs = $('vemas-vis-save'); if (vs) vs.addEventListener('click', this.saveVisibility.bind(this));
            // Kennwort-Augen
            document.querySelectorAll('#settings-tab-vemas .vemas-eye').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var inp = $(btn.dataset.target); if (!inp) return;
                    var hidden = inp.type === 'password';
                    inp.type = hidden ? 'text' : 'password';
                    btn.innerHTML = hidden ? SVG_EYE_CLOSED : SVG_EYE_OPEN;
                });
            });
        },

        // Nur die Felder zeigen, die zur gewaehlten Anmeldeart gehoeren.
        // 'login' braucht Benutzer/Kennwort ZUSAETZLICH zum Anmelde-Endpunkt –
        // damit holt der Server das Token; deshalb bleibt die basic-Gruppe an.
        _applyAuth: function (art) {
            var zeig = {
                basic:  { basic: true,  bearer: false, login: false },
                bearer: { basic: false, bearer: true,  login: false },
                login:  { basic: true,  bearer: false, login: true }
            }[art] || { basic: true, bearer: false, login: false };
            ['basic', 'bearer', 'login'].forEach(function (k) {
                var g = $('vemas-g-' + k);
                if (g) g.style.display = zeig[k] ? '' : 'none';
            });
        },

        loadConfig: function () {
            var self = this;
            fetch('/api/skills/vemas/config', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    if ($('vemas-base-url')) $('vemas-base-url').value = c.base_url || '';
                    if ($('vemas-product')) $('vemas-product').value = c.vemas_product || '';
                    if ($('vemas-auth-kind')) $('vemas-auth-kind').value = c.auth_kind || 'basic';
                    if ($('vemas-username')) $('vemas-username').value = c.username || '';
                    if ($('vemas-password')) $('vemas-password').value = c.password || '';
                    if ($('vemas-token')) $('vemas-token').value = c.api_token || '';
                    if ($('vemas-login-path')) $('vemas-login-path').value = c.login_path || '';
                    if ($('vemas-login-user-field')) $('vemas-login-user-field').value = c.login_user_field || '';
                    if ($('vemas-login-pass-field')) $('vemas-login-pass-field').value = c.login_pass_field || '';
                    if ($('vemas-token-json-path')) $('vemas-token-json-path').value = c.token_json_path || '';
                    if ($('vemas-token-header')) $('vemas-token-header').value = c.token_header || '';
                    // Praefix darf ein reines Leerzeichen enthalten ("Bearer ") –
                    // deshalb NICHT trimmen und nicht auf Falsyness pruefen.
                    if ($('vemas-token-prefix')) {
                        $('vemas-token-prefix').value =
                            (c.token_prefix === undefined || c.token_prefix === null) ? 'Bearer ' : c.token_prefix;
                    }
                    if ($('vemas-mandant')) $('vemas-mandant').value = c.mandant || '';
                    if ($('vemas-mandant-param')) $('vemas-mandant-param').value = c.mandant_param || '';
                    if ($('vemas-test-path')) $('vemas-test-path').value = c.test_path || '';
                    if ($('vemas-resources')) $('vemas-resources').value = c.resources || '';
                    // Beide Haken auf `!== false` pruefen: fehlt das Feld (frisch
                    // aktivierter Skill), gilt die SICHERE Vorgabe – Prüfung an,
                    // nur lesend.
                    if ($('vemas-verify-ssl')) $('vemas-verify-ssl').checked = c.verify_ssl !== false;
                    if ($('vemas-read-only')) $('vemas-read-only').checked = c.read_only !== false;
                    self._applyAuth(c.auth_kind || 'basic');
                })
                .catch(function () { status('✗ Konfiguration nicht abrufbar', 'error'); });
        },

        // Der Verbindungs-Knopf sendet NUR die Verbindungsfelder. Der
        // Sichtbarkeits-Knopf sendet NUR `hidden_analyses`. Beide Teilmengen
        // sind getrennt, weil der Server serverseitig merged – sendete einer
        // den ganzen Formularstand, überschriebe ein Klick den Stand des
        // anderen (dieselbe Trennung wie im SAP- und Jira-Reiter).
        _collect: function () {
            return {
                base_url: val('vemas-base-url'),
                vemas_product: val('vemas-product'),
                auth_kind: val('vemas-auth-kind') || 'basic',
                username: val('vemas-username'),
                password: raw('vemas-password'),
                api_token: raw('vemas-token'),
                login_path: val('vemas-login-path'),
                login_user_field: val('vemas-login-user-field') || 'username',
                login_pass_field: val('vemas-login-pass-field') || 'password',
                token_json_path: val('vemas-token-json-path') || 'token',
                token_header: val('vemas-token-header') || 'Authorization',
                // NICHT trimmen: "Bearer " endet auf einem bedeutsamen Leerzeichen.
                token_prefix: raw('vemas-token-prefix'),
                mandant: val('vemas-mandant'),
                mandant_param: val('vemas-mandant-param'),
                verify_ssl: checked('vemas-verify-ssl'),
                read_only: checked('vemas-read-only'),
                test_path: val('vemas-test-path'),
                resources: ($('vemas-resources') ? $('vemas-resources').value : '')
            };
        },

        save: function () {
            var self = this;
            status(T('confluence.saving', 'Speichere…'));
            fetch('/api/skills/vemas/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(this._collect())
            }).then(function (r) { return r.json(); })
              .then(function () {
                  status('✓ ' + T('confluence.saved', 'Gespeichert'), 'ok');
                  // Ohne Serveradresse ist kein persoenlicher Zugang moeglich –
                  // die Liste kann sich also durch das Speichern aendern.
                  self.loadAccounts();
              })
              .catch(function () { status('✗ Fehler beim Speichern', 'error'); });
        },

        test: function () {
            status(T('vemas.acc_testing', 'Teste Verbindung…'));
            fetch('/api/vemas/test', { headers: authHeaders() })
                .then(function (r) {
                    // 403 heisst hier NICHT "kaputt": der Endpunkt haengt an der
                    // VEMAS-Freigabe, und die kennt bewusst keinen Admin-Bypass.
                    // Ohne diesen Zweig suchte ein Administrator den Fehler in
                    // seiner Serverkonfiguration.
                    if (r.status === 403) {
                        status(T('vemas.test_no_access',
                            'Der Verbindungstest läuft über den VEMAS-Bereich – dafür musst du dich '
                            + 'unter Sicherheit → Berechtigungen → VEMAS-Zugriff selbst freischalten.'), 'error');
                        return null;
                    }
                    return r.json();
                })
                .then(function (d) {
                    if (!d) return;
                    if (d.ok) {
                        status('✅ ' + T('vemas.test_ok', 'Verbindung OK')
                            + (d.detail ? ' – ' + d.detail : ''), 'ok');
                    } else if (d.configured === false) {
                        status(T('vemas.test_unconfigured', 'Nicht konfiguriert – bitte zuerst speichern.'), 'error');
                    } else {
                        status('❌ ' + (d.error || T('vemas.failed', 'Verbindung fehlgeschlagen')), 'error');
                    }
                })
                .catch(function () { status('❌ Verbindungstest fehlgeschlagen', 'error'); });
        },

        // Selbstauskunft des Servers lesen und als fertige Zeilen für das
        // Ressourcen-Feld anbieten. Der Knopf SCHREIBT NICHT selbst ins Feld:
        // was VEMAS als Endpunkt fuehrt, ist nicht zwingend das, was hier
        // stehen soll (Unterpfade, Schreiboperationen, Verwaltungsrouten).
        discover: function () {
            var box = $('vemas-discover-out'); if (!box) return;
            box.innerHTML = '<span class="kb-hint">' + esc(T('vemas.loading', 'Lade…')) + '</span>';
            fetch('/api/vemas/query?resource=' + encodeURIComponent('swagger/v1/swagger.json') + '&top=1',
                  { headers: authHeaders() })
                .then(function (r) { return r.json().catch(function () { return null; }); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint">'
                            + esc(T('vemas.discover_none',
                                'Dieses VEMAS-System liefert keine maschinenlesbare Schnittstellenbeschreibung. '
                                + 'Tragen Sie die Ressourcen von Hand ein – die Pfade nennt Ihnen der Hersteller.'))
                            + '</span>';
                        return;
                    }
                    var roh = (d.rows && d.rows[0]) || {};
                    var pfade = roh.paths ? Object.keys(roh.paths) : [];
                    if (!pfade.length) {
                        box.innerHTML = '<span class="kb-hint">'
                            + esc(T('vemas.discover_none',
                                'Dieses VEMAS-System liefert keine maschinenlesbare Schnittstellenbeschreibung. '
                                + 'Tragen Sie die Ressourcen von Hand ein – die Pfade nennt Ihnen der Hersteller.'))
                            + '</span>';
                        return;
                    }
                    var vorschlag = pfade.filter(function (p) { return p.indexOf('{') < 0; })
                        .map(function (p) {
                            var t = p.replace(/^\/+/, '');
                            var name = t.split('/').filter(Boolean).pop() || t;
                            return name + ' = ' + t;
                        });
                    box.innerHTML = '<p class="kb-hint">' + esc(pfade.length + ' ')
                        + esc(T('vemas.discover_found', 'Endpunkt(e) gefunden. Vorschlag zum Übernehmen:'))
                        + '</p><textarea class="config-input" rows="8" readonly '
                        + 'style="width:100%;box-sizing:border-box;font-family:var(--font-mono);font-size:0.82rem;">'
                        + esc(vorschlag.join('\n')) + '</textarea>';
                })
                .catch(function () {
                    box.innerHTML = '<span class="kb-hint">'
                        + esc(T('vemas.failed', 'Fehlgeschlagen.')) + '</span>';
                });
        },

        runQuery: function () {
            var box = $('vemas-results'); if (!box) return;
            var res = val('vemas-q-resource');
            if (!res) {
                box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                    + esc(T('vemas.need_resource', 'Bitte eine Ressource angeben.')) + '</span>';
                return;
            }
            box.innerHTML = '<span class="kb-hint">' + esc(T('vemas.loading', 'Lade…')) + '</span>';
            var url = '/api/vemas/query?resource=' + encodeURIComponent(res)
                + '&params=' + encodeURIComponent(val('vemas-q-params'))
                + '&top=' + encodeURIComponent(val('vemas-q-top') || '20');
            fetch(url, { headers: authHeaders() })
                .then(function (r) { return r.json().catch(function () { return null; }); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || T('vemas.failed', 'Abfrage fehlgeschlagen')) + '</span>';
                        return;
                    }
                    renderTable(box, d.columns, d.rows);
                })
                .catch(function () {
                    box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                        + esc(T('vemas.failed', 'Abfrage fehlgeschlagen')) + '</span>';
                });
        },

        // ── Persoenliche Zugaenge (nur Anzeige) ─────────────────────
        loadAccounts: function () {
            var box = $('vemas-accounts-list'); if (!box) return;
            fetch('/api/vemas/admin/accounts', { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d || !d.ok) { box.textContent = 'Nicht abrufbar.'; return; }
                    var list = d.accounts || [];
                    if (!list.length) {
                        box.textContent = T('vemas.acc_none_admin',
                            'Kein Benutzer hat einen eigenen VEMAS-Zugang hinterlegt – alle Abfragen laufen '
                            + 'über den gemeinsamen Zugang.');
                        return;
                    }
                    var html = esc(list.length + ' ')
                        + esc(T('vemas.acc_n_admin', 'Benutzer mit eigenem Zugang:'))
                        + '<ul style="margin:6px 0 0 18px;">';
                    list.forEach(function (a) {
                        var mark = a.ausgesetzt
                            ? ' – <span style="color:var(--danger);">'
                              + esc(T('vemas.acc_suspended_short', 'ausgesetzt nach ')) + a.anmeldefehler
                              + esc(T('vemas.acc_authfails', ' Anmeldefehlern')) + '</span>'
                            : (!a.aktiv ? ' – ' + esc(T('vemas.acc_inactive', 'inaktiv')) : '');
                        html += '<li>' + esc(a.user) + ' (' + esc(a.auth_kind || '?') + ')' + mark + '</li>';
                    });
                    box.innerHTML = html + '</ul>';
                })
                .catch(function () { box.textContent = 'Nicht abrufbar.'; });
        },

        // ── Sichtbarkeit der Abfragen im Bereich /vemas ─────────────
        loadVisibility: function () {
            var self = this;
            var box = $('vemas-vis-list'); if (!box) return;
            var lg = (localStorage.getItem('jarvis_lang') === 'en') ? 'en' : 'de';
            fetch('/api/vemas/analyses/catalog?lang=' + lg, { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d) {
                        box.innerHTML = '<span class="kb-hint">'
                            + esc(T('sap.vis_load_fail', 'Abfragen konnten nicht geladen werden')) + '</span>';
                        return;
                    }
                    box.innerHTML = '';
                    (d.categories || []).forEach(function (c) {
                        var eintraege = (d.analyses || []).filter(function (a) { return a.cat === c.id; });
                        if (!eintraege.length) return;
                        var h = document.createElement('h5');
                        h.style.cssText = 'margin:12px 0 4px;color:var(--text-secondary);font-size:.85rem;';
                        h.textContent = c.title;
                        box.appendChild(h);
                        eintraege.forEach(function (a) {
                            var lab = document.createElement('label');
                            lab.className = 'checkbox-group';
                            lab.style.cssText = 'display:flex;align-items:flex-start;gap:8px;margin:3px 0;';
                            var cb = document.createElement('input');
                            cb.type = 'checkbox';
                            cb.checked = a.visible !== false;
                            cb.dataset.aid = a.id;
                            // NUR auf 'change' hoeren und NIE selbst umschalten:
                            // ein Klick im <label> schaltet die Checkbox schon
                            // vom Browser aus um (Register-Eintrag 2026-07-29).
                            cb.addEventListener('change', function () { self._visCount(); });
                            var sp = document.createElement('span');
                            sp.innerHTML = '<b>' + esc(a.title) + '</b><br>'
                                + '<span class="kb-hint">' + esc(a.desc) + '</span>';
                            lab.appendChild(cb); lab.appendChild(sp);
                            box.appendChild(lab);
                        });
                    });
                    self._visCount();
                })
                .catch(function () {
                    box.innerHTML = '<span class="kb-hint">'
                        + esc(T('sap.vis_load_fail', 'Abfragen konnten nicht geladen werden')) + '</span>';
                });
        },

        _visBoxes: function () {
            return Array.prototype.slice.call(
                document.querySelectorAll('#vemas-vis-list input[type=checkbox][data-aid]'));
        },

        _visCount: function () {
            var el = $('vemas-vis-count'); if (!el) return;
            var alle = this._visBoxes();
            var an = alle.filter(function (c) { return c.checked; }).length;
            el.textContent = an + ' / ' + alle.length;
        },

        _visSetAll: function (an) {
            this._visBoxes().forEach(function (c) { c.checked = !!an; });
            this._visCount();
        },

        saveVisibility: function () {
            var el = $('vemas-vis-status');
            var aus = this._visBoxes().filter(function (c) { return !c.checked; })
                .map(function (c) { return c.dataset.aid; });
            if (el) { el.textContent = T('confluence.saving', 'Speichere…'); el.style.color = ''; }
            fetch('/api/skills/vemas/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                // NUR dieses eine Feld – siehe Begruendung bei _collect().
                body: JSON.stringify({ hidden_analyses: aus })
            })
                .then(function (r) { return r.json(); })
                .then(function () {
                    if (el) { el.textContent = '✓ ' + T('confluence.saved', 'Gespeichert'); el.style.color = 'var(--success)'; }
                })
                .catch(function () {
                    if (el) { el.textContent = T('sap.vis_save_fail', 'Speichern fehlgeschlagen'); el.style.color = 'var(--danger)'; }
                });
        }
    };

    window.VemasManager = Manager;
})();
