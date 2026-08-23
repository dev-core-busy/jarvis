/* ═══════════════════════════════════════════════════════════════════
   SAP-Reiter (Einstellungen) – Read-Only
   ───────────────────────────────────────────────────────────────────
   Verbindungskonfiguration (OData / HANA-SQL / RFC), Verbindungstest,
   OData-Leseabfragen, direkte SELECT-Abfragen gegen HANA sowie fertige
   Anbindungshinweise fuer die gaengigen Reporting-Tools. Schreibzugriffe
   sind serverseitig hart gesperrt.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    function val(id) { var e = $(id); return e ? e.value.trim() : ''; }
    function checked(id) { var e = $(id); return !!(e && e.checked); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function status(msg, kind) {
        var el = $('sap-status'); if (!el) return;
        el.textContent = msg || '';
        el.style.color = kind === 'error' ? 'var(--danger)'
            : kind === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
    }

    var SVG_EYE_CLOSED = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
    var SVG_EYE_OPEN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';

    // Ergebnis-Tabelle aus {columns, rows}
    function renderTable(box, columns, rows) {
        if (!box) return;
        if (!rows || !rows.length) { box.innerHTML = '<span class="kb-hint">Keine Zeilen.</span>'; return; }
        var cols = (columns && columns.length) ? columns : Object.keys(rows[0]);
        var html = '<table style="border-collapse:collapse;width:100%;font-size:0.82rem;">';
        html += '<thead><tr>' + cols.map(function (c) {
            return '<th style="text-align:left;padding:4px 8px;border-bottom:1px solid var(--border);'
                + 'white-space:nowrap;color:var(--text-secondary);">' + esc(c) + '</th>';
        }).join('') + '</tr></thead><tbody>';
        rows.forEach(function (r) {
            html += '<tr>' + cols.map(function (c) {
                return '<td style="padding:4px 8px;border-bottom:1px solid rgba(var(--fg-rgb),.06);'
                    + 'vertical-align:top;">' + esc(r[c]) + '</td>';
            }).join('') + '</tr>';
        });
        html += '</tbody></table>';
        box.innerHTML = html;
    }

    var Manager = {
        _bound: false,

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
            var ct = $('sap-conn-type');
            if (ct) ct.addEventListener('change', function () { self._applyType(ct.value); });
            var save = $('sap-save'); if (save) save.addEventListener('click', this.save.bind(this));
            var test = $('sap-test'); if (test) test.addEventListener('click', this.test.bind(this));
            var oq = $('sap-odata-run'); if (oq) oq.addEventListener('click', this.runOData.bind(this));
            var sq = $('sap-sql-run'); if (sq) sq.addEventListener('click', this.runSql.bind(this));
            var rp = $('sap-reporting-btn'); if (rp) rp.addEventListener('click', this.loadReporting.bind(this));
            // Sichtbarkeit der Analysen im Bereich /sap
            var va = $('sap-vis-all'); if (va) va.addEventListener('click', function () { self._visSetAll(true); });
            var vn = $('sap-vis-none'); if (vn) vn.addEventListener('click', function () { self._visSetAll(false); });
            var vs = $('sap-vis-save'); if (vs) vs.addEventListener('click', this.saveVisibility.bind(this));
            // Passwort-Augen (delegiert)
            document.querySelectorAll('#settings-tab-sap .sap-eye').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var inp = $(btn.dataset.target); if (!inp) return;
                    var hidden = inp.type === 'password';
                    inp.type = hidden ? 'text' : 'password';
                    btn.innerHTML = hidden ? SVG_EYE_CLOSED : SVG_EYE_OPEN;
                });
            });
        },

        _applyType: function (type) {
            ['odata', 'hana', 'rfc'].forEach(function (t) {
                var g = $('sap-group-' + t);
                if (g) g.style.display = (t === type) ? '' : 'none';
                var d = $('sap-data-' + t);
                if (d) d.style.display = (t === type) ? '' : 'none';
            });
            var res = $('sap-results'); if (res) res.innerHTML = '';
        },

        loadConfig: function () {
            var self = this;
            fetch('/api/skills/sap/config', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    if ($('sap-conn-type')) $('sap-conn-type').value = c.connection_type || 'odata';
                    if ($('sap-product')) $('sap-product').value = c.sap_product || '';
                    // OData
                    if ($('sap-odata-url')) $('sap-odata-url').value = c.odata_base_url || '';
                    if ($('sap-odata-service')) $('sap-odata-service').value = c.odata_service || '';
                    if ($('sap-auth-kind')) $('sap-auth-kind').value = c.auth_kind || 'basic';
                    if ($('sap-odata-client')) $('sap-odata-client').value = c.sap_client || '';
                    if ($('sap-odata-user')) $('sap-odata-user').value = c.username || '';
                    if ($('sap-odata-pass')) $('sap-odata-pass').value = c.password || '';
                    if ($('sap-odata-token')) $('sap-odata-token').value = c.bearer_token || '';
                    if ($('sap-verify-ssl')) $('sap-verify-ssl').checked = c.verify_ssl !== false;
                    // HANA
                    if ($('sap-hana-host')) $('sap-hana-host').value = c.hana_host || '';
                    if ($('sap-hana-port')) $('sap-hana-port').value = c.hana_port || '';
                    if ($('sap-hana-user')) $('sap-hana-user').value = c.hana_user || '';
                    if ($('sap-hana-pass')) $('sap-hana-pass').value = c.hana_password || '';
                    if ($('sap-hana-schema')) $('sap-hana-schema').value = c.hana_schema || '';
                    if ($('sap-hana-encrypt')) $('sap-hana-encrypt').checked = c.hana_encrypt !== false;
                    if ($('sap-hana-validate')) $('sap-hana-validate').checked = c.hana_ssl_validate !== false;
                    // RFC
                    if ($('sap-rfc-ashost')) $('sap-rfc-ashost').value = c.rfc_ashost || '';
                    if ($('sap-rfc-sysnr')) $('sap-rfc-sysnr').value = c.rfc_sysnr || '';
                    if ($('sap-rfc-client')) $('sap-rfc-client').value = c.rfc_client || '';
                    if ($('sap-rfc-user')) $('sap-rfc-user').value = c.rfc_user || '';
                    if ($('sap-rfc-pass')) $('sap-rfc-pass').value = c.rfc_password || '';
                    if ($('sap-rfc-lang')) $('sap-rfc-lang').value = c.rfc_lang || 'EN';
                    // Freigegebene Server fuer persoenliche Zugaenge (leer = niemand)
                    if ($('sap-allowed-hosts')) $('sap-allowed-hosts').value = c.allowed_hosts || '';
                    self._cfg = c;
                    self._mountCert();
                    self._applyType(c.connection_type || 'odata');
                })
                .catch(function () {});
        },

        // ── Serverzertifikat pruefen/verankern ──────────────────────────
        // Der Baustein liegt in js/sapcert.js und wird von BEIDEN Oberflaechen
        // benutzt (hier und in /sap). `_mountCert` ist idempotent – onShow()
        // laeuft bei jedem Oeffnen des Reiters.
        _cfg: {},
        _cert: {},

        _mountCert: function () {
            var self = this;
            if (!window.SapCert) return;
            [['odata', 'sapcert-odata'], ['hana', 'sapcert-hana']].forEach(function (p) {
                var kanal = p[0], box = $(p[1]);
                if (!box) return;
                if (!self._cert[kanal]) {
                    self._cert[kanal] = window.SapCert.mount(box, {
                        basis: '/api/sap/admin/cert',
                        kanal: kanal,
                        ziel: function () {
                            return kanal === 'hana'
                                ? { host: val('sap-hana-host'), port: val('sap-hana-port') || 443 }
                                : { url: val('sap-odata-url') };
                        },
                        gebunden: function () { return self._cfg['cert_' + kanal] || {}; },
                        nachAenderung: function () { self.loadConfig(); }
                    });
                } else {
                    // Nach dem Neuladen der Konfiguration muss die Zustandszeile
                    // folgen – sonst stuende dort noch der alte Anker.
                    self._cert[kanal].refresh();
                }
            });
        },

        _collect: function () {
            // ACHTUNG: hier stehen bewusst KEINE `cert_*`-Felder. Der Server
            // merged (`update_skill_config`), ein Speichern der Verbindung darf
            // den Anker also nicht mitschreiben – sonst loescht der eine Knopf,
            // was der andere gesetzt hat (Muster „zwei Knoepfe, zwei Teilmengen").
            return {
                connection_type: val('sap-conn-type') || 'odata',
                sap_product: val('sap-product'),
                read_only: true,
                // OData
                odata_base_url: val('sap-odata-url'),
                odata_service: val('sap-odata-service'),
                auth_kind: val('sap-auth-kind') || 'basic',
                sap_client: val('sap-odata-client'),
                username: val('sap-odata-user'),
                password: ($('sap-odata-pass') ? $('sap-odata-pass').value : ''),
                bearer_token: ($('sap-odata-token') ? $('sap-odata-token').value : ''),
                verify_ssl: checked('sap-verify-ssl'),
                // HANA
                hana_host: val('sap-hana-host'),
                hana_port: Number(val('sap-hana-port') || 443),
                hana_user: val('sap-hana-user'),
                hana_password: ($('sap-hana-pass') ? $('sap-hana-pass').value : ''),
                hana_schema: val('sap-hana-schema'),
                hana_encrypt: checked('sap-hana-encrypt'),
                hana_ssl_validate: checked('sap-hana-validate'),
                // RFC
                rfc_ashost: val('sap-rfc-ashost'),
                rfc_sysnr: val('sap-rfc-sysnr'),
                rfc_client: val('sap-rfc-client'),
                rfc_user: val('sap-rfc-user'),
                rfc_password: ($('sap-rfc-pass') ? $('sap-rfc-pass').value : ''),
                rfc_lang: val('sap-rfc-lang') || 'EN',
                // Gehoert zum Verbindungs-Knopf (Serverkonfiguration). Der
                // Sichtbarkeits-Knopf sendet es NICHT mit – sonst ueberschriebe
                // ein Klick dort den jeweils anderen Teil (gleiche Trennung wie
                // bei hidden_analyses).
                allowed_hosts: ($('sap-allowed-hosts') ? $('sap-allowed-hosts').value.trim() : '')
            };
        },

        save: function () {
            status(window.t ? window.t('confluence.saving') : 'Speichere…');
            fetch('/api/skills/sap/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(this._collect())
            }).then(function (r) { return r.json(); })
              .then(function () {
                  status('✓ ' + (window.t ? window.t('confluence.saved') : 'Gespeichert'), 'ok');
                  // Die Freigabeliste entscheidet, ob vorhandene persoenliche
                  // Zugaenge noch gelten – deshalb die Liste neu zeichnen.
                  Manager.loadAccounts();
              })
              .catch(function () { status('✗ Fehler beim Speichern', 'error'); });
        },

        // ── Persoenliche SAP-Zugaenge (nur Anzeige) ─────────────────────
        loadAccounts: function () {
            var box = $('sap-accounts-list'); if (!box) return;
            fetch('/api/sap/admin/accounts', { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d || !d.ok) { box.textContent = 'Nicht abrufbar.'; return; }
                    var hosts = (d.erlaubte_hosts || []);
                    var kopf = hosts.length
                        ? 'Freigegebene Server: ' + hosts.map(esc).join(', ')
                        : '⚠ Kein Server freigegeben – niemand kann einen eigenen Zugang hinterlegen.';
                    var list = (d.accounts || []);
                    // kopf ist bereits sicher: die Hostnamen wurden oben durch esc()
                    // geschickt, der Rest ist statischer Text. Ein zweites esc()
                    // wuerde die Entities doppelt maskieren.
                    if (!list.length) {
                        box.innerHTML = kopf
                            + '<br>Kein Benutzer hat einen eigenen SAP-Zugang hinterlegt – alle Auswertungen '
                            + 'laufen über den gemeinsamen Lesezugang.';
                        return;
                    }
                    var html = kopf + '<br>' + list.length + ' Benutzer mit eigenem Zugang:<ul style="margin:6px 0 0 18px;">';
                    list.forEach(function (a) {
                        var mark = a.ausgesetzt ? ' – <span style="color:var(--danger);">ausgesetzt nach '
                                + a.anmeldefehler + ' Anmeldefehlern</span>'
                            : (!a.aktiv ? ' – inaktiv'
                            : (!a.host_ok ? ' – <span style="color:var(--danger);">Server nicht mehr freigegeben</span>' : ''));
                        html += '<li>' + esc(a.user) + ' (' + esc(a.connection_type || '?') + ')' + mark + '</li>';
                    });
                    box.innerHTML = html + '</ul>';
                })
                .catch(function () { box.textContent = 'Nicht abrufbar.'; });
        },

        test: function () {
            status('Teste Verbindung…');
            fetch('/api/sap/test', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d && d.ok) {
                        status('✅ Verbindung OK [' + esc(d.type) + ']'
                            + (d.detail ? ' – ' + esc(d.detail) : ''), 'ok');
                    } else if (d && d.configured === false) {
                        status('Nicht konfiguriert – bitte zuerst speichern.', 'error');
                    } else {
                        status('❌ ' + ((d && d.error) || 'Verbindung fehlgeschlagen'), 'error');
                    }
                })
                .catch(function () { status('❌ Verbindungstest fehlgeschlagen', 'error'); });
        },

        runOData: function () {
            var box = $('sap-results'); if (!box) return;
            var entity = val('sap-odata-entity');
            if (!entity) { box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">EntitySet fehlt.</span>'; return; }
            box.innerHTML = '<span class="kb-hint">Lade…</span>';
            var url = '/api/sap/odata/query?entity_set=' + encodeURIComponent(entity)
                + '&service=' + encodeURIComponent(val('sap-odata-qservice'))
                + '&top=' + encodeURIComponent(val('sap-odata-top') || '20');
            fetch(url, { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || 'Abfrage fehlgeschlagen') + '</span>';
                        return;
                    }
                    renderTable(box, d.columns, d.rows);
                })
                .catch(function () { box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">Abfrage fehlgeschlagen</span>'; });
        },

        runSql: function () {
            var box = $('sap-results'); if (!box) return;
            var sql = $('sap-sql') ? $('sap-sql').value.trim() : '';
            if (!sql) { box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">SQL fehlt.</span>'; return; }
            box.innerHTML = '<span class="kb-hint">Führe aus…</span>';
            fetch('/api/sap/sql', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ sql: sql, max_rows: Number(val('sap-sql-max') || 200) })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || 'Abfrage fehlgeschlagen') + '</span>';
                        return;
                    }
                    renderTable(box, d.columns, d.rows);
                    if (d.truncated) {
                        box.insertAdjacentHTML('afterbegin',
                            '<div class="kb-hint" style="color:var(--danger);margin-bottom:6px;">⚠️ Ergebnis abgeschnitten.</div>');
                    }
              })
              .catch(function () { box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">Abfrage fehlgeschlagen</span>'; });
        },

        // ── Sichtbare Analysen im Bereich /sap ──────────────────────────
        // Gespeichert wird die Liste der AUSGEBLENDETEN Ids (`hidden_analyses`),
        // nicht der sichtbaren: so erscheint eine spaeter ergaenzte Analyse von
        // selbst, statt still zu fehlen. Die Kaesten zeigen deshalb "sichtbar",
        // gespeichert wird das Gegenteil.
        _visStatus: function (msg, kind) {
            var el = $('sap-vis-status'); if (!el) return;
            el.textContent = msg || '';
            el.style.color = kind === 'error' ? 'var(--danger)'
                : kind === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
        },

        _visCount: function () {
            var el = $('sap-vis-count'); if (!el) return;
            var boxes = document.querySelectorAll('#sap-vis-list .sap-vis-cb');
            var on = document.querySelectorAll('#sap-vis-list .sap-vis-cb:checked').length;
            var tpl = (window.t ? window.t('sap.vis_count') : '');
            if (!tpl || tpl === 'sap.vis_count') tpl = '{n} von {total} sichtbar';
            el.textContent = tpl.replace('{n}', on).replace('{total}', boxes.length);
            // Alles abgewaehlt ist erlaubt (die freie Frage bleibt), aber der
            // Anwender saehe ein leeres Pulldown – das gehoert angesagt.
            el.style.color = (boxes.length && !on) ? 'var(--warning)' : '';
        },

        _visSetAll: function (on) {
            document.querySelectorAll('#sap-vis-list .sap-vis-cb').forEach(function (cb) {
                cb.checked = !!on;
            });
            this._visCount();
        },

        loadVisibility: function () {
            var self = this;
            var box = $('sap-vis-list'); if (!box) return;
            var lg = (function () {
                try { return localStorage.getItem('jarvis_lang') || 'de'; } catch (e) { return 'de'; }
            })();
            box.innerHTML = '<span class="kb-hint">' + esc(window.t ? window.t('common.loading') : 'Lädt…') + '</span>';
            fetch('/api/sap/analyses/catalog?lang=' + encodeURIComponent(lg), { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc(window.t ? window.t('sap.vis_load_fail') : 'Analysen konnten nicht geladen werden')
                            + '</span>';
                        return;
                    }
                    box.innerHTML = d.categories.map(function (c) {
                        var items = d.analyses.filter(function (a) { return a.cat === c.id; });
                        if (!items.length) return '';
                        return '<div style="margin-bottom:14px;">'
                            + '<div style="font-weight:600;font-size:0.88rem;margin-bottom:5px;'
                            + 'color:var(--text-secondary);">' + esc(c.title) + '</div>'
                            + items.map(function (a) {
                                return '<label class="checkbox-group" style="align-items:flex-start;'
                                    + 'gap:8px;margin-bottom:4px;" title="' + esc(a.desc) + '">'
                                    + '<input type="checkbox" class="sap-vis-cb" data-id="' + esc(a.id) + '"'
                                    + (a.visible ? ' checked' : '') + '>'
                                    + '<span>' + esc(a.title) + '</span></label>';
                            }).join('')
                            + '</div>';
                    }).join('');
                    // Delegiert statt je Kasten: die Liste wird bei jedem
                    // Sprachwechsel neu gebaut, Einzel-Listener haetten sich
                    // dabei angesammelt.
                    box.addEventListener('change', function (e) {
                        if (e.target && e.target.classList.contains('sap-vis-cb')) self._visCount();
                    });
                    self._visCount();
                })
                .catch(function () {
                    box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                        + esc(window.t ? window.t('sap.vis_load_fail') : 'Analysen konnten nicht geladen werden')
                        + '</span>';
                });
        },

        saveVisibility: function () {
            var self = this;
            var boxes = document.querySelectorAll('#sap-vis-list .sap-vis-cb');
            if (!boxes.length) return;
            var hidden = [];
            boxes.forEach(function (cb) { if (!cb.checked) hidden.push(cb.dataset.id); });
            this._visStatus(window.t ? window.t('confluence.saving') : 'Speichere…');
            // NUR dieses eine Feld senden – der Server merged (update_skill_config),
            // die Zugangsdaten bleiben also unberuehrt. Wuerde hier die ganze
            // Konfiguration mitgehen, ueberschriebe ein Klick hier die
            // Verbindungsfelder mit dem Formularstand.
            fetch('/api/skills/sap/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ hidden_analyses: hidden })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d && d.success === false) throw new Error('save');
                  self._visStatus('✓ ' + (window.t ? window.t('confluence.saved') : 'Gespeichert'), 'ok');
                  setTimeout(function () { self._visStatus(''); }, 2500);
              })
              .catch(function () {
                  self._visStatus('✗ ' + (window.t ? window.t('sap.vis_save_fail') : 'Speichern fehlgeschlagen'), 'error');
              });
        },

        loadReporting: function () {
            var box = $('sap-reporting'); if (!box) return;
            box.innerHTML = '<span class="kb-hint">Lade…</span>';
            fetch('/api/sap/reporting-endpoints', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var eps = (d && d.endpoints) || [];
                    if (!eps.length) {
                        box.innerHTML = '<span class="kb-hint">Keine Schnittstelle konfiguriert – bitte oben Zugangsdaten speichern.</span>';
                        return;
                    }
                    box.innerHTML = eps.map(function (e) {
                        var tools = Object.keys(e.tools || {}).map(function (k) {
                            return '<li><strong>' + esc(k) + ':</strong> ' + esc(e.tools[k]) + '</li>';
                        }).join('');
                        return '<div style="border:1px solid var(--border);border-radius:8px;padding:10px 12px;'
                            + 'margin-bottom:8px;background:var(--bg-glass);">'
                            + '<div style="font-weight:600;">' + esc(e.interface) + '</div>'
                            + '<div class="kb-hint" style="margin:2px 0 6px;word-break:break-all;">' + esc(e.url) + '</div>'
                            + '<ul style="margin:0;padding-left:18px;font-size:0.85rem;">' + tools + '</ul></div>';
                    }).join('');
                })
                .catch(function () { box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">Konnte nicht laden</span>'; });
        }
    };

    window.SapManager = Manager;
})();
