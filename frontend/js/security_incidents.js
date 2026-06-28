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
                return '<div style="padding:8px 0;border-bottom:1px solid rgba(var(--fg-rgb),.08);">'
                    + '<div style="font-size:0.78rem;color:var(--text-muted);">'
                    + esc(fmtTs(it.ts)) + ' · ' + esc(chanLabel(it.channel)) + ' · ' + esc(it.method || '') + ' · ' + esc(it.pattern || '')
                    + '</div>'
                    + '<div style="font-size:0.84rem;color:var(--text-primary);white-space:pre-wrap;word-break:break-word;margin-top:2px;">'
                    + esc(it.snippet || '') + '</div>'
                    + '</div>';
            }).join('');
        },

        // ── Sperr-Bildschirm für betroffene Nutzer ───────────────────────
        showBlockedScreen: function (reason, incidents) {
            var m = $('blocked-screen');
            if (!m) return;
            var rEl = $('blocked-reason');
            if (rEl) rEl.textContent = reason ? (T('security.blocked_reason_label', 'Grund: ') + reason) : '';
            Mgr.renderIncidents($('blocked-incidents'), incidents || []);
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
