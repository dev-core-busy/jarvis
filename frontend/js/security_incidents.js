/* Sicherheitsschicht – Einstellungen (Sicherheitsvorfälle) + Sperr-Bildschirm
   - Verwaltung im Tab Einstellungen → Sicherheit: Schicht/Heuristik/LLM schalten,
     gesperrte Konten anzeigen, Protokoll einsehen, freischalten (nur lokal).
   - Sperr-Bildschirm für betroffene Nutzer nach dem Login (Hinweis + Protokoll).
   i18n via window.t(), Branding über CSS-Variablen (keine harten Farben). */
(function () {
    'use strict';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) { return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {}); }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function T(key, def) { return (window.t && window.t(key) !== key ? window.t(key) : null) || def; }
    function fmtTs(ts) {
        try { return new Date((ts || 0) * 1000).toLocaleString((window._lang === 'en') ? 'en-GB' : 'de-DE'); }
        catch (e) { return '' + ts; }
    }
    function chanLabel(ch) {
        return T('security.ch_' + ch, ch === 'chat' ? 'Chat' : ch === 'support' ? 'Support'
            : ch === 'whatsapp' ? 'WhatsApp' : (ch || '–'));
    }

    var Mgr = {
        _bound: false,

        // ── Einstellungen ───────────────────────────────────────────────
        onShow: function () { this._bind(); this.load(); },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            ['sec-guard-enabled', 'sec-guard-heuristic', 'sec-guard-llm'].forEach(function (id) {
                var el = $(id);
                if (el) el.addEventListener('change', function () { Mgr.saveConfig(); });
            });
            // Funktionsbeschreibungs-Popup (❓) + PDF-Druck
            var docBtn = $('sec-secdoc-btn');
            if (docBtn) docBtn.addEventListener('click', function () { Mgr._showDoc(true); });
            var docClose = $('sec-secdoc-close');
            if (docClose) docClose.addEventListener('click', function () { Mgr._showDoc(false); });
            var docModal = $('sec-secdoc-modal');
            if (docModal) docModal.addEventListener('click', function (e) { if (e.target === docModal) Mgr._showDoc(false); });
            var docPdf = $('sec-secdoc-pdf');
            if (docPdf) docPdf.addEventListener('click', function () {
                document.body.classList.add('printing-secdoc');
                var cleanup = function () {
                    document.body.classList.remove('printing-secdoc');
                    window.removeEventListener('afterprint', cleanup);
                };
                window.addEventListener('afterprint', cleanup);
                try { window.print(); } catch (e) { cleanup(); }
            });
            document.addEventListener('keydown', function (e) {
                if (e.key === 'Escape' && docModal && docModal.classList.contains('open')) Mgr._showDoc(false);
            });
            // Internet-Egress-Sperre: Einrichten / Live-Prüfung
            var egSetup = $('sec-egress-setup');
            if (egSetup) egSetup.addEventListener('click', function () { Mgr.setupEgress(); });
            var egVerify = $('sec-egress-verify');
            if (egVerify) egVerify.addEventListener('click', function () { Mgr.loadEgress(true); });
        },

        _showDoc: function (show) {
            var m = $('sec-secdoc-modal');
            if (m) m.classList.toggle('open', !!show);
        },

        load: function () {
            fetch('/api/security/incidents', { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d || !d.ok) return;
                    if ($('sec-guard-enabled')) $('sec-guard-enabled').checked = !!d.enabled;
                    if ($('sec-guard-heuristic')) $('sec-guard-heuristic').checked = !!d.heuristic;
                    if ($('sec-guard-llm')) $('sec-guard-llm').checked = !!d.llm;
                    Mgr.renderBlocked(d.blocked || []);
                })
                .catch(function () {});
            // OS-Sandbox-Status
            fetch('/api/security/sandbox', { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { Mgr.renderSandbox(d); })
                .catch(function () {});
            // Letzte Zugriffs-Verstöße
            fetch('/api/security/violations', { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { Mgr.renderViolations((d && d.violations) || []); })
                .catch(function () {});
            // Internet-Egress-Sperre (Status ohne Live-Test = schnell)
            Mgr.loadEgress(false);
        },

        loadEgress: function (live) {
            var box = $('sec-egress-status');
            if (box && live) box.innerHTML = '⏳ Live-Test läuft…';
            fetch('/api/security/egress' + (live ? '?live=1' : ''), { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { Mgr.renderEgress(d); })
                .catch(function () {});
        },

        renderEgress: function (d) {
            var box = $('sec-egress-status');
            if (!box) return;
            if (!d) { box.innerHTML = '<span style="color:var(--text-muted);">Status nicht verfügbar.</span>'; return; }
            function row(ok, label) {
                var mark = ok === true ? '✅' : (ok === false ? '❌' : '❔');
                return '<div>' + mark + ' ' + esc(label) + '</div>';
            }
            var head = d.ok
                ? (d.egress_blocked === false
                    ? '🟠 <b>Eingerichtet – aber Live-Test: Internet noch erreichbar!</b>'
                    : '🟢 <b>Aktiv' + (d.egress_blocked === true ? ' &amp; live verifiziert' : '') + '</b>')
                : '🔴 <b>Nicht (vollständig) eingerichtet</b>';
            var rows = ''
                + row(d.configured, 'Einstellung gesetzt (No-Internet-Sandbox-Benutzer)')
                + row(d.user_exists, 'Gesperrter OS-Benutzer: ' + (d.user || '') + (d.uid != null ? ' (uid ' + d.uid + ')' : ' — fehlt'))
                + row(d.nft_active, 'Firewall-Regel aktiv (nftables)')
                + row(d.service_enabled, 'Autostart nach Reboot (systemd)');
            if (d.egress_blocked === true || d.egress_blocked === false) {
                rows += row(d.egress_blocked, 'Live-Test: öffentliches Internet ' + (d.egress_blocked ? 'geblockt' : 'ERREICHBAR ⚠'));
            }
            var res = (d.resolvers && d.resolvers.length)
                ? '<div style="color:var(--text-muted);font-size:0.75rem;margin-top:4px;">Erlaubte DNS-Resolver: ' + esc(d.resolvers.join(', ')) + '</div>' : '';
            box.innerHTML = '<div style="margin-bottom:6px;">' + head + '</div>' + rows + res;
        },

        setupEgress: function () {
            var btn = $('sec-egress-setup');
            var out = $('sec-egress-result');
            var orig = btn ? btn.textContent : '';
            if (btn) { btn.disabled = true; btn.textContent = 'Wird eingerichtet…'; }
            fetch('/api/security/egress/setup', { method: 'POST', headers: authHeaders() })
                .then(function (r) { return r.json().then(function (j) { return j; }); })
                .then(function (d) {
                    d = d || {};
                    if (out) {
                        out.style.display = 'block';
                        var good = !!d.ok;
                        out.style.borderColor = good ? 'rgba(34,197,94,0.5)' : 'rgba(239,68,68,0.5)';
                        out.style.background = good ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)';
                        var lines = (d.steps || []).map(function (s) {
                            return (s.ok ? '✅' : '❌') + ' ' + esc(s.name) + (s.detail && !s.ok ? ' – ' + esc(s.detail) : '');
                        }).join('<br>');
                        out.innerHTML = '<div style="font-weight:600;margin-bottom:4px;">'
                            + (good ? 'Einrichtung erfolgreich &amp; verifiziert.' : 'Einrichtung unvollständig – Details:')
                            + '</div>' + lines;
                    }
                    Mgr.renderEgress(d.status);
                })
                .catch(function () {
                    if (out) { out.style.display = 'block'; out.innerHTML = 'Fehler bei der Einrichtung.'; }
                })
                .then(function () {
                    if (btn) { btn.disabled = false; btn.textContent = orig || 'Einrichten / Reparieren'; }
                });
        },

        renderSandbox: function (d) {
            var box = $('sec-sandbox-status');
            if (!box) return;
            if (!d) { box.innerHTML = ''; return; }
            var active = !!d.active, exists = !!d.user_exists;
            var dot = (active && exists) ? '🟢' : (active ? '🟠' : '⚪');
            var txt;
            if (active && exists) {
                txt = T('security.sandbox_on', 'OS-Sandbox aktiv') + ' — '
                    + T('security.sandbox_user', 'Sandbox-Benutzer') + ': ' + esc(d.user);
            } else if (active && !exists) {
                txt = '⚠️ ' + T('security.sandbox_missing', 'Sandbox konfiguriert, aber OS-Benutzer fehlt')
                    + ': ' + esc(d.user);
            } else {
                txt = T('security.sandbox_off', 'OS-Sandbox inaktiv – nur Code-Härtung aktiv');
            }
            box.innerHTML = '<span style="font-size:0.9rem;">' + dot + ' ' + txt + '</span>';
        },

        renderViolations: function (list) {
            var box = $('sec-viol-list');
            if (!box) return;
            if (!list.length) {
                box.innerHTML = '<p class="kb-hint">' + esc(T('security.no_violations', 'Keine Verstöße protokolliert.')) + '</p>';
                return;
            }
            box.innerHTML = list.map(function (v) {
                var meta = esc(fmtTs(v.ts)) + ' · <strong style="color:var(--text-primary);">' + esc(v.user) + '</strong> · '
                    + esc(chanLabel(v.channel)) + ' · ' + esc(v.pattern || '');
                if (v.tool) meta += ' · ' + esc(v.tool);
                if (v.ip) meta += ' · IP ' + esc(v.ip);
                var html = '<div style="padding:6px 0;border-bottom:1px solid rgba(var(--fg-rgb),.08);">'
                    + '<div style="font-size:0.78rem;color:var(--text-muted);">' + meta + '</div>';
                if (v.detail) html += '<div style="font-size:0.82rem;color:var(--text-primary);">' + esc(v.detail) + '</div>';
                if (v.task) html += '<div style="font-size:0.78rem;color:var(--text-secondary);">'
                    + esc(T('security.f_request', 'Anfrage')) + ': ' + esc(v.task) + '</div>';
                return html + '</div>';
            }).join('');
        },

        saveConfig: function () {
            var body = {
                enabled: $('sec-guard-enabled') ? $('sec-guard-enabled').checked : true,
                heuristic: $('sec-guard-heuristic') ? $('sec-guard-heuristic').checked : true,
                llm: $('sec-guard-llm') ? $('sec-guard-llm').checked : true
            };
            var st = $('sec-guard-status');
            if (st) st.textContent = T('common.saving', 'Speichere…');
            fetch('/api/security/incidents/config', {
                method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json(); })
              .then(function () {
                  if (st) { st.textContent = '✓ ' + T('common.saved', 'Gespeichert'); setTimeout(function () { st.textContent = ''; }, 2000); }
              }).catch(function () { if (st) st.textContent = '✗'; });
        },

        renderBlocked: function (list) {
            var box = $('sec-blocked-list');
            if (!box) return;
            if (!list.length) {
                box.innerHTML = '<p class="kb-hint">' + esc(T('security.no_blocked', 'Keine gesperrten Konten.')) + '</p>';
                return;
            }
            box.innerHTML = list.map(function (b) {
                return '<div class="sec-blk-row" data-user="' + esc(b.user) + '" '
                    + 'style="border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px;">'
                    + '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'
                    + '<strong style="color:var(--text-primary);">' + esc(b.user) + '</strong>'
                    + '<span style="font-size:0.78rem;color:var(--text-muted);">' + esc(fmtTs(b.at)) + '</span>'
                    + '<span style="font-size:0.78rem;color:var(--danger);">' + esc(b.reason || '') + '</span>'
                    + '<span style="font-size:0.74rem;color:var(--text-muted);">[' + esc(chanLabel(b.channel)) + ' · ' + esc(b.method || '') + ' · ' + (b.incident_count || 0) + ']</span>'
                    + '<span style="flex:1;"></span>'
                    + '<button type="button" class="kb-btn-action sec-blk-log" style="font-size:0.76rem;padding:3px 10px;">' + esc(T('security.view_log', 'Log ansehen')) + '</button>'
                    + '<button type="button" class="kb-btn-action sec-blk-unblock" style="font-size:0.76rem;padding:3px 10px;">' + esc(T('security.unblock', 'Freischalten')) + '</button>'
                    + '</div>'
                    + '<div class="sec-blk-detail" style="display:none;margin-top:10px;"></div>'
                    + '</div>';
            }).join('');
            box.querySelectorAll('.sec-blk-log').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var row = btn.closest('.sec-blk-row');
                    Mgr.toggleLog(row.getAttribute('data-user'), row.querySelector('.sec-blk-detail'));
                });
            });
            box.querySelectorAll('.sec-blk-unblock').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var row = btn.closest('.sec-blk-row');
                    Mgr.unblock(row.getAttribute('data-user'));
                });
            });
        },

        toggleLog: function (user, detailEl) {
            if (!detailEl) return;
            if (detailEl.style.display !== 'none') { detailEl.style.display = 'none'; return; }
            detailEl.style.display = '';
            detailEl.innerHTML = '<p class="kb-hint">' + esc(T('common.loading', 'Lade…')) + '</p>';
            fetch('/api/security/incidents/log?target=' + encodeURIComponent(user), { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) { Mgr.renderIncidents(detailEl, (d && d.incidents) || []); })
                .catch(function () { detailEl.innerHTML = '<p class="kb-hint">✗</p>'; });
        },

        unblock: function (user) {
            if (!window.confirm(T('security.unblock_confirm', 'Konto „%s" wirklich freischalten?').replace('%s', user))) return;
            fetch('/api/security/incidents/unblock', {
                method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ user: user })
            }).then(function (r) {
                if (r.status === 403) { window.alert(T('security.only_local', 'Nur ein lokaler Benutzer darf Konten freischalten.')); return null; }
                return r.json();
            }).then(function (d) { if (d && d.ok) Mgr.load(); })
              .catch(function () {});
        },

        // Rendert eine Vorfallsliste (Settings-Detail ODER Sperr-Bildschirm)
        renderIncidents: function (el, incidents) {
            if (!el) return;
            if (!incidents.length) {
                el.innerHTML = '<p class="kb-hint">' + esc(T('security.no_incidents', 'Keine Vorfälle protokolliert.')) + '</p>';
                return;
            }
            el.innerHTML = incidents.slice().reverse().map(function (it) {
                var meta = esc(fmtTs(it.ts)) + ' · ' + esc(chanLabel(it.channel))
                    + ' · ' + esc(it.method || '') + ' · ' + esc(it.pattern || '');
                if (it.tool) meta += ' · ' + esc(T('security.f_tool', 'Tool')) + ': ' + esc(it.tool);
                if (it.ip) meta += ' · IP ' + esc(it.ip);
                var html = '<div style="padding:8px 0;border-bottom:1px solid rgba(var(--fg-rgb),.08);">'
                    + '<div style="font-size:0.78rem;color:var(--text-muted);">' + meta + '</div>';
                if (it.detail) html += '<div style="font-size:0.85rem;color:var(--text-primary);margin-top:2px;">' + esc(it.detail) + '</div>';
                if (it.task) html += '<div style="font-size:0.8rem;color:var(--text-secondary);margin-top:2px;">'
                    + esc(T('security.f_request', 'Anfrage')) + ': ' + esc(it.task) + '</div>';
                if (it.snippet && it.snippet !== it.task) html += '<div style="font-size:0.76rem;color:var(--text-muted);'
                    + 'white-space:pre-wrap;word-break:break-word;margin-top:2px;font-family:monospace;">' + esc(it.snippet) + '</div>';
                return html + '</div>';
            }).join('');
        },

        // ── Sperr-Bildschirm für betroffene Nutzer ───────────────────────
        showBlockedScreen: function (reason, incidents) {
            var m = $('blocked-screen');
            if (!m) return;
            var rEl = $('blocked-reason');
            if (rEl) rEl.textContent = reason ? (T('security.blocked_reason_label', 'Grund: ') + reason) : '';
            Mgr.renderIncidents($('blocked-incidents'), incidents || []);
            // CSS-unabhaengig anzeigen (funktioniert auf allen Seiten, auch ohne
            // .modal-Styles wie portal.html).
            m.style.display = 'flex';
            m.classList.add('open');
            if (window.applyLang) window.applyLang();
        },

        // Holt die eigene Sperr-Info (z.B. nach WS-Event) und zeigt den Bildschirm
        fetchAndShowBlocked: function () {
            fetch('/api/security/my-block', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) { if (d && d.blocked) Mgr.showBlockedScreen(d.reason, d.incidents); })
                .catch(function () {});
        }
    };

    document.addEventListener('DOMContentLoaded', function () {
        var lo = $('blocked-logout');
        if (lo) lo.addEventListener('click', function () {
            localStorage.removeItem('jarvis_token');
            localStorage.removeItem('jarvis_user');
            window.location.reload();
        });
    });

    window.SecurityIncidents = Mgr;
})();
