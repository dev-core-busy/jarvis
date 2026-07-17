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

    // Automatische/interne Wartungs- & Status-Ops (UI-Polls, Bildschirm-Entsperrung,
    // VNC-Neustart) – ohne forensischen Wert, aus Liste UND Audit-Anzeige ausblenden
    // (blendet auch bereits protokollierte Alt-Einträge aus).
    var HIDE_OPS = { 'sandbox_status': 1, 'egress_status': 1, 'unlock_screen': 1, 'vnc_restart': 1 };

    var Mgr = {
        _bound: false,
        _auditCache: null,   // zwischengespeicherte Audit-Einträge (pro loadBroker geleert)

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
            // Firewall-Funktionsanalyse-Popup (❓)
            var fwBtn = $('sec-fwdoc-btn');
            if (fwBtn) fwBtn.addEventListener('click', function () { Mgr._showFwDoc(true); });
            var fwClose = $('sec-fwdoc-close');
            if (fwClose) fwClose.addEventListener('click', function () { Mgr._showFwDoc(false); });
            var fwModal = $('sec-fwdoc-modal');
            if (fwModal) fwModal.addEventListener('click', function (e) { if (e.target === fwModal) Mgr._showFwDoc(false); });
            var fwPdf = $('sec-fwdoc-pdf');
            if (fwPdf) fwPdf.addEventListener('click', function () {
                document.body.classList.add('printing-fwdoc');
                var cleanup = function () {
                    document.body.classList.remove('printing-fwdoc');
                    window.removeEventListener('afterprint', cleanup);
                };
                window.addEventListener('afterprint', cleanup);
                try { window.print(); } catch (e) { cleanup(); }
            });
            document.addEventListener('keydown', function (e) {
                if (e.key === 'Escape' && fwModal && fwModal.classList.contains('open')) Mgr._showFwDoc(false);
            });

            // Internet-Egress-Sperre: Einrichten / Live-Prüfung
            var egSetup = $('sec-egress-setup');
            if (egSetup) egSetup.addEventListener('click', function () { Mgr.setupEgress(); });
            var egVerify = $('sec-egress-verify');
            if (egVerify) egVerify.addEventListener('click', function () { Mgr.loadEgress(true); });
            var egDown = $('sec-egress-teardown');
            if (egDown) egDown.addEventListener('click', function () { Mgr.teardownEgress(); });
            // OS-Sandbox: Aktivieren / Isolation testen / Deaktivieren
            var sbSetup = $('sec-sandbox-setup');
            if (sbSetup) sbSetup.addEventListener('click', function () { Mgr.setupSandbox(); });
            var sbVerify = $('sec-sandbox-verify');
            if (sbVerify) sbVerify.addEventListener('click', function () { Mgr.loadSandbox(true); });
            var sbDown = $('sec-sandbox-teardown');
            if (sbDown) sbDown.addEventListener('click', function () { Mgr.teardownSandbox(); });
            // Root-Broker: Freigabeliste aktualisieren / Audit-Log
            var brRefresh = $('sec-broker-refresh');
            if (brRefresh) brRefresh.addEventListener('click', function () { Mgr.loadBroker(); });
            // Root-Broker: Betriebsart per Klick umschalten (getrennt <-> Alt-Betrieb)
            var brSetup = $('sec-broker-setup');
            if (brSetup) brSetup.addEventListener('click', function () { Mgr.setupBrokerMode(); });
            var brDown = $('sec-broker-teardown');
            if (brDown) brDown.addEventListener('click', function () { Mgr.teardownBrokerMode(); });
            var brAudit = $('sec-broker-audit-btn');
            if (brAudit) brAudit.addEventListener('click', function () { Mgr.toggleBrokerAudit(); });
            // Root-Broker-Funktionsanalyse-Popup (❓) + PDF-Druck
            var brkBtn = $('sec-brkdoc-btn');
            if (brkBtn) brkBtn.addEventListener('click', function () { Mgr._showBrkDoc(true); });
            var brkClose = $('sec-brkdoc-close');
            if (brkClose) brkClose.addEventListener('click', function () { Mgr._showBrkDoc(false); });
            var brkModal = $('sec-brkdoc-modal');
            if (brkModal) brkModal.addEventListener('click', function (e) { if (e.target === brkModal) Mgr._showBrkDoc(false); });
            var brkPdf = $('sec-brkdoc-pdf');
            if (brkPdf) brkPdf.addEventListener('click', function () {
                document.body.classList.add('printing-brkdoc');
                var cleanup = function () {
                    document.body.classList.remove('printing-brkdoc');
                    window.removeEventListener('afterprint', cleanup);
                };
                window.addEventListener('afterprint', cleanup);
                try { window.print(); } catch (e) { cleanup(); }
            });
            document.addEventListener('keydown', function (e) {
                if (e.key === 'Escape' && brkModal && brkModal.classList.contains('open')) Mgr._showBrkDoc(false);
            });
        },

        _showBrkDoc: function (show) {
            var m = $('sec-brkdoc-modal');
            if (m) m.classList.toggle('open', !!show);
        },

        _showDoc: function (show) {
            var m = $('sec-secdoc-modal');
            if (m) m.classList.toggle('open', !!show);
        },

        _showFwDoc: function (show) {
            var m = $('sec-fwdoc-modal');
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
            Mgr.loadSandbox(false);
            // Letzte Zugriffs-Verstöße
            fetch('/api/security/violations', { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { Mgr.renderViolations((d && d.violations) || []); })
                .catch(function () {});
            // Internet-Egress-Sperre (Status ohne Live-Test = schnell)
            Mgr.loadEgress(false);
            // Root-Broker (Rechte-Trennung + Freigabeliste)
            Mgr.loadBroker();
        },

        // ── Root-Broker: Freigabeliste + Audit ──────────────────────────
        loadBroker: function () {
            this._auditCache = null;   // Audit neu laden, sobald wieder benötigt
            fetch('/api/broker/status', { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { Mgr.renderBrokerStatus(d); })
                .catch(function () {});
            fetch('/api/broker/ops', { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { Mgr.renderBrokerOps(d && d.ops ? d.ops : null); })
                .catch(function () { Mgr.renderBrokerOps(null); });
        },

        renderBrokerStatus: function (d) {
            var box = $('sec-broker-status');
            if (!box) return;
            if (!d || !d.ok) { box.innerHTML = ''; return; }
            var head;
            if (d.mode === 'broker' && d.separated) {
                head = '🟢 <b>' + esc(T('security.broker_separated', 'Getrennter Betrieb aktiv')) + '</b> – '
                    + esc(T('security.broker_separated_hint', 'Oberfläche läuft unprivilegiert als')) + ' <code>' + esc(d.backend_user || '') + '</code>, '
                    + esc(T('security.broker_via', 'Root-Operationen laufen über den Broker')) + '.';
            } else if (d.mode === 'local-root') {
                head = '🟠 <b>' + esc(T('security.broker_legacy', 'Alt-Betrieb (Backend läuft als root)')) + '</b> – '
                    + esc(T('security.broker_legacy_hint', 'Freigabeliste + Audit sind aktiv, aber ohne Prozess-Trennung. Empfehlung: getrennten Betrieb aktivieren (Button unten).'));
            } else if (d.mode === 'broker') {
                head = '🟠 <b>Broker erreichbar, Backend läuft aber noch als root.</b>';
            } else {
                head = '🔴 <b>' + esc(T('security.broker_none', 'Root-Broker nicht erreichbar')) + '</b> – '
                    + esc(T('security.broker_none_hint', 'Root-Operationen schlagen fehl (jarvis-broker.service prüfen).'));
            }
            box.innerHTML = '<div style="margin-bottom:4px;">' + head + '</div>';
            var badge = $('sec-broker-pending-badge');
            if (badge) {
                if (d.pending > 0) {
                    badge.style.display = '';
                    badge.textContent = d.pending + ' ' + T('security.broker_pending_badge', 'offen');
                } else {
                    badge.style.display = 'none';
                }
            }
            // Zahnrad-Badge (Header) synchron mitziehen
            if (window._setBrokerBadge) window._setBrokerBadge(d.pending || 0);
            // Umschalt-Buttons je Betriebsart: im getrennten Betrieb nur den
            // Rueckweg anbieten, sonst die Aktivierung/Reparatur.
            var isSep = (d.mode === 'broker' && d.separated);
            var bSetup = $('sec-broker-setup');
            if (bSetup) bSetup.style.display = isSep ? 'none' : '';
            var bDown = $('sec-broker-teardown');
            if (bDown) bDown.style.display = isSep ? '' : 'none';
        },

        // ── Betriebsart umschalten (Ein-Klick, analog Sandbox/Egress-Panel) ──
        setupBrokerMode: function () {
            if (!window.confirm(T('security.broker_setup_confirm',
                'Getrennten Betrieb jetzt aktivieren/reparieren?\n\n'
                + 'Das Backend wird auf einen unprivilegierten Dienst-Benutzer umgestellt, '
                + 'Root-Operationen laufen danach über den Root-Broker. '
                + 'jarvis.service und jarvis-broker.service starten dabei NEU – die '
                + 'Oberfläche ist für einige Sekunden nicht erreichbar.'))) return;
            Mgr._brokerModeAction('/api/broker/setup', 'sec-broker-setup', 'broker',
                T('security.broker_mode_ok_sep', 'Getrennter Betrieb aktiv – Oberfläche läuft unprivilegiert.'));
        },

        teardownBrokerMode: function () {
            if (!window.confirm(T('security.broker_teardown_confirm',
                'Wirklich in den Alt-Betrieb zurückschalten?\n\n'
                + 'Das Backend läuft danach wieder MIT root-Rechten (keine Prozess-Trennung); '
                + 'der Broker-Dienst wird deaktiviert. Freigabeliste + Audit bleiben aktiv. '
                + 'jarvis.service startet dabei NEU – die Oberfläche ist kurz nicht erreichbar.'))) return;
            Mgr._brokerModeAction('/api/broker/teardown', 'sec-broker-teardown', 'local-root',
                T('security.broker_mode_ok_legacy', 'Alt-Betrieb wiederhergestellt (Backend läuft als root).'));
        },

        // Startet die Umstellung und pollt den Status, bis der Ziel-Modus
        // erreicht ist (die Dienste starten waehrenddessen neu).
        _brokerModeAction: function (url, btnId, expectMode, okMsg) {
            var btn = $(btnId), out = $('sec-broker-mode-result');
            var orig = btn ? btn.textContent : '';
            var finish = function () { if (btn) { btn.disabled = false; btn.textContent = orig; } };
            var show = function (html, good) {
                if (!out) return;
                out.style.display = 'block';
                out.style.borderColor = good === false ? 'rgba(var(--danger-rgb),0.5)'
                    : (good ? 'rgba(var(--success-rgb),0.5)' : 'rgba(var(--fg-rgb),0.3)');
                out.style.background = good === false ? 'rgba(var(--danger-rgb),0.1)'
                    : (good ? 'rgba(var(--success-rgb),0.1)' : 'rgba(var(--fg-rgb),0.06)');
                out.innerHTML = html;
            };
            if (btn) { btn.disabled = true; btn.textContent = T('security.busy_setup', 'Wird eingerichtet…'); }
            fetch(url, { method: 'POST', headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    d = d || {};
                    if (!d.ok) {
                        show('❌ ' + esc(d.error || 'Start fehlgeschlagen'), false);
                        finish();
                        return;
                    }
                    show('⏳ ' + esc(T('security.broker_mode_started',
                        'Umstellung gestartet – Dienste starten neu, Status wird überwacht…'))
                        + (d.message ? '<br><span style="color:var(--text-muted);">' + esc(d.message) + '</span>' : ''), null);
                    var tries = 0;
                    var iv = setInterval(function () {
                        tries++;
                        fetch('/api/broker/status', { headers: authHeaders() })
                            .then(function (r) { return r.ok ? r.json() : null; })
                            .then(function (s) {
                                if (s && s.ok && s.mode === expectMode
                                    && (expectMode !== 'broker' || s.separated)) {
                                    clearInterval(iv); finish();
                                    show('✅ ' + esc(okMsg), true);
                                    Mgr.loadBroker();
                                } else if (tries >= 30) {   // ~2 Minuten
                                    clearInterval(iv); finish();
                                    show('⚠️ ' + esc(T('security.broker_mode_timeout',
                                        'Zeitüberschreitung – Status bitte über „Aktualisieren“ prüfen; Details: journalctl -u jarvis-broker-migrate bzw. -u jarvis-broker-restore.')), false);
                                    Mgr.loadBroker();
                                }
                            })
                            .catch(function () { /* Dienst startet gerade neu – weiter pollen */ });
                    }, 4000);
                })
                .catch(function () { show('❌ ' + esc(T('portal.conn_error', 'Verbindungsfehler')), false); finish(); });
        },

        renderBrokerOps: function (ops) {
            var box = $('sec-broker-list');
            if (!box) return;
            if (ops === null) {
                box.innerHTML = '<p class="kb-hint">' + esc(T('security.broker_unavailable', 'Freigabeliste nicht verfügbar (Broker nicht erreichbar).')) + '</p>';
                return;
            }
            ops = ops.filter(function (e) { return !HIDE_OPS[e.key]; });   // Status-Polls nicht listen
            if (!ops.length) {
                box.innerHTML = '<p class="kb-hint">' + esc(T('security.broker_empty', 'Noch keine Root-Operationen registriert – Einträge erscheinen hier automatisch beim ersten Auftauchen.')) + '</p>';
                return;
            }
            function badge(dec) {
                if (dec === 'pending') return '<span style="padding:1px 8px;border-radius:999px;font-size:0.72rem;font-weight:700;background:rgba(var(--warning-rgb),0.18);border:1px solid rgba(var(--warning-rgb),0.5);">⏳ ' + esc(T('security.broker_st_pending', 'wartet auf Freigabe')) + '</span>';
                if (dec === 'deny') return '<span style="padding:1px 8px;border-radius:999px;font-size:0.72rem;font-weight:700;background:rgba(var(--danger-rgb),0.15);border:1px solid rgba(var(--danger-rgb),0.5);">🚫 ' + esc(T('security.broker_st_deny', 'abgelehnt')) + '</span>';
                return '<span style="padding:1px 8px;border-radius:999px;font-size:0.72rem;font-weight:700;background:rgba(var(--success-rgb),0.15);border:1px solid rgba(var(--success-rgb),0.5);">✅ ' + esc(T('security.broker_st_allow', 'erlaubt')) + '</span>';
            }
            box.innerHTML = ops.map(function (e) {
                var meta = [];
                if (e.auto) meta.push(T('security.broker_auto', 'Systemoperation (automatisch erlaubt)'));
                if (e.requested_by) meta.push(T('security.broker_by', 'angefordert von') + ' ' + e.requested_by);
                if (e.count) meta.push(e.count + '×');
                if (e.last_used) meta.push(T('security.broker_last', 'zuletzt') + ' ' + fmtTs(e.last_used));
                if (e.decided_by && !e.auto) meta.push(T('security.broker_decided', 'entschieden von') + ' ' + e.decided_by);
                var isPending = e.decision === 'pending';
                var html = '<div class="sec-broker-row" data-key="' + esc(e.key) + '" '
                    + 'style="border:1px solid ' + (isPending ? 'rgba(var(--warning-rgb),0.5)' : 'var(--border)') + ';border-radius:8px;padding:8px 12px;margin-bottom:6px;'
                    + (isPending ? 'background:rgba(var(--warning-rgb),0.06);' : '') + '">'
                    + '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'
                    + badge(e.decision)
                    + '<code style="font-size:0.78rem;word-break:break-all;flex:1;min-width:180px;">' + esc(e.description || e.key) + '</code>'
                    + '</div>'
                    + '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:4px;">'
                    + '<span style="font-size:0.72rem;color:var(--text-muted);flex:1;">' + esc(meta.join(' · ')) + '</span>';
                html += '<button type="button" class="sec-btn small sec-brk-history" title="' + esc(T('security.broker_history_title', 'Letzte Ausführungen/Entscheidungen zu diesem Eintrag')) + '">📜 ' + esc(T('security.broker_history', 'Beispiele')) + '</button>';
                if (e.decision !== 'allow') html += '<button type="button" class="sec-btn small primary sec-brk-allow">' + esc(T('security.broker_allow', 'Erlauben')) + '</button>';
                if (e.decision !== 'deny') html += '<button type="button" class="sec-btn small sec-brk-deny">' + esc(T('security.broker_deny', 'Ablehnen')) + '</button>';
                html += '<button type="button" class="sec-btn small danger sec-brk-remove" title="' + esc(T('security.broker_remove_title', 'Eintrag löschen – erscheint beim nächsten Auftauchen erneut')) + '">×</button>'
                    + '</div>'
                    + '<div class="sec-brk-history-box" style="display:none;margin-top:6px;"></div>'
                    + '</div>';
                return html;
            }).join('');
            box.querySelectorAll('.sec-brk-history').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var row = btn.closest('.sec-broker-row');
                    Mgr.toggleOpHistory(row.getAttribute('data-key'), row.querySelector('.sec-brk-history-box'));
                });
            });
            box.querySelectorAll('.sec-brk-allow').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    Mgr.decideBroker(btn.closest('.sec-broker-row').getAttribute('data-key'), 'allow');
                });
            });
            box.querySelectorAll('.sec-brk-deny').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    Mgr.decideBroker(btn.closest('.sec-broker-row').getAttribute('data-key'), 'deny');
                });
            });
            box.querySelectorAll('.sec-brk-remove').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    Mgr.removeBrokerOp(btn.closest('.sec-broker-row').getAttribute('data-key'));
                });
            });
        },

        decideBroker: function (key, decision) {
            if (!key) return;
            if (decision === 'allow' && key.indexOf('shell_root:') === 0
                && !window.confirm(T('security.broker_allow_confirm',
                    'Diesen Befehl mit ROOT-Rechten erlauben?\n\n%s\n\nEr darf danach jederzeit erneut ausgeführt werden.')
                    .replace('%s', key.substring(11)))) return;
            fetch('/api/broker/ops/decide', {
                method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ key: key, decision: decision })
            }).then(function (r) { return r.json(); })
              .then(function () { Mgr.loadBroker(); })
              .catch(function () {});
        },

        removeBrokerOp: function (key) {
            if (!key) return;
            if (!window.confirm(T('security.broker_remove_confirm', 'Eintrag wirklich löschen?'))) return;
            fetch('/api/broker/ops/remove', {
                method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ key: key })
            }).then(function (r) { return r.json(); })
              .then(function () { Mgr.loadBroker(); })
              .catch(function () {});
        },

        // Rendert eine einzelne Audit-Zeile (wiederverwendet: Gesamt-Log + Pro-Eintrag-Beispiele).
        // showKey=true zeigt zusätzlich den Befehl/Key (Gesamt-Log); pro Eintrag ist er redundant.
        _auditLineHtml: function (a, showKey) {
            var mark = a.decision === 'executed' ? (a.rc === 0 || a.rc == null ? '✅' : '⚠️')
                : (a.decision === 'denied' ? '🚫' : (a.decision === 'pending' ? '⏳' : '•'));
            var head = mark + ' ' + esc(fmtTs(a.ts)) + ' · <b>' + esc(a.user || '–') + '</b> · ' + esc(a.decision);
            if (a.rc != null && a.decision === 'executed') head += ' (rc=' + a.rc + (a.duration_ms != null ? ', ' + a.duration_ms + ' ms' : '') + ')';
            var parts = ['<div>' + head + '</div>'];
            if (showKey && (a.key || a.op)) {
                parts.push('<div style="margin-top:2px;"><code style="font-size:0.74rem;word-break:break-all;">' + esc(a.key || a.op) + '</code></div>');
            }
            // Konkrete (maskierte) Argumente dieser Ausfuehrung (Audit-Feld 'info',
            // z.B. "action=restart unit=jarvis.service" oder "command=…") – erst
            // damit sagt eine 'executed'-Zeile aus, WAS genau ausgefuehrt wurde.
            if (a.info) {
                parts.push('<div style="margin-top:2px;"><code style="font-size:0.74rem;word-break:break-all;color:var(--text-secondary);">' + esc(a.info) + '</code></div>');
            }
            if (a.context) {
                parts.push('<div style="margin-top:2px;color:var(--text-secondary);font-size:0.74rem;">↳ '
                    + esc(T('security.broker_trigger', 'Auslöser')) + ': ' + esc(a.context) + '</div>');
            }
            if (a.detail) {
                parts.push('<div style="margin-top:2px;color:var(--text-muted);font-size:0.72rem;white-space:pre-wrap;word-break:break-word;font-family:monospace;">' + esc(a.detail) + '</div>');
            }
            return '<div style="padding:6px 0;border-bottom:1px solid rgba(var(--fg-rgb),.06);">' + parts.join('') + '</div>';
        },

        // Holt das Audit-Log (max. n) und legt es in _auditCache ab; force erzwingt Neuladen.
        _fetchAuditOnce: function (force) {
            if (this._auditCache && !force) return Promise.resolve(this._auditCache);
            var self = this;
            return fetch('/api/broker/audit?n=1000', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    self._auditCache = ((d && d.entries) || []).filter(function (a) {
                        return !HIDE_OPS[a.op] && !HIDE_OPS[a.key];   // reine Status-Polls ausblenden
                    });
                    return self._auditCache;
                });
        },

        toggleBrokerAudit: function () {
            var box = $('sec-broker-audit');
            if (!box) return;
            if (box.style.display !== 'none') { box.style.display = 'none'; return; }
            box.style.display = '';
            box.innerHTML = '<p class="kb-hint">' + esc(T('common.loading', 'Lade…')) + '</p>';
            this._fetchAuditOnce(true)
                .then(function (entries) {
                    if (!entries.length) {
                        box.innerHTML = '<p class="kb-hint">' + esc(T('security.broker_audit_empty', 'Noch keine Audit-Einträge.')) + '</p>';
                        return;
                    }
                    box.innerHTML = '<div style="max-height:260px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;padding:6px 10px;">'
                        + entries.slice().reverse().map(function (a) { return Mgr._auditLineHtml(a, true); }).join('')
                        + '</div>';
                })
                .catch(function () { box.innerHTML = '<p class="kb-hint">✗</p>'; });
        },

        // Zeigt die letzten Audit-Beispiele für genau einen Freigabe-Eintrag (nach key gefiltert)
        toggleOpHistory: function (key, el) {
            if (!el) return;
            if (el.style.display !== 'none') { el.style.display = 'none'; return; }
            el.style.display = '';
            el.innerHTML = '<p class="kb-hint">' + esc(T('common.loading', 'Lade…')) + '</p>';
            this._fetchAuditOnce()
                .then(function (entries) {
                    var mine = entries.filter(function (a) { return (a.key || a.op) === key; });
                    if (!mine.length) {
                        el.innerHTML = '<p class="kb-hint">' + esc(T('security.broker_history_empty', 'Noch keine Beispiele zu diesem Eintrag.')) + '</p>';
                        return;
                    }
                    el.innerHTML = '<div style="max-height:180px;overflow-y:auto;border:1px solid var(--border);border-radius:8px;padding:6px 10px;background:rgba(var(--fg-rgb),.03);">'
                        + mine.slice(-8).reverse().map(function (a) { return Mgr._auditLineHtml(a, false); }).join('')
                        + '</div>';
                })
                .catch(function () { el.innerHTML = '<p class="kb-hint">✗</p>'; });
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
            if (btn) { btn.disabled = true; btn.textContent = T('security.busy_setup', 'Wird eingerichtet…'); }
            fetch('/api/security/egress/setup', { method: 'POST', headers: authHeaders() })
                .then(function (r) { return r.json().then(function (j) { return j; }); })
                .then(function (d) {
                    d = d || {};
                    if (out) {
                        out.style.display = 'block';
                        var good = !!d.ok;
                        out.style.borderColor = good ? 'rgba(var(--success-rgb),0.5)' : 'rgba(var(--danger-rgb),0.5)';
                        out.style.background = good ? 'rgba(var(--success-rgb),0.1)' : 'rgba(var(--danger-rgb),0.1)';
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
                    if (btn) { btn.disabled = false; btn.textContent = orig || T('security.egress_setup', 'Einrichten / Reparieren'); }
                });
        },

        teardownEgress: function () {
            if (!window.confirm('Harte Egress-Sperre wirklich deaktivieren?\n\n'
                + 'Benutzer ohne Internet-Freigabe können danach per Shell (curl, rohe Sockets) '
                + 'wieder ins öffentliche Internet. Die Tool-Sperre (Bildersuche, Browser, Google) '
                + 'bleibt aktiv.')) return;
            var btn = $('sec-egress-teardown');
            var out = $('sec-egress-result');
            var orig = btn ? btn.textContent : '';
            if (btn) { btn.disabled = true; btn.textContent = T('security.busy_teardown', 'Wird deaktiviert…'); }
            fetch('/api/security/egress/teardown', { method: 'POST', headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    d = d || {};
                    if (out) {
                        out.style.display = 'block';
                        var good = !!d.ok;
                        out.style.borderColor = good ? 'rgba(var(--fg-rgb),0.3)' : 'rgba(var(--danger-rgb),0.5)';
                        out.style.background = good ? 'rgba(var(--fg-rgb),0.06)' : 'rgba(var(--danger-rgb),0.1)';
                        var lines = (d.steps || []).map(function (s) {
                            return (s.ok ? '✅' : '❌') + ' ' + esc(s.name) + (s.detail && !s.ok ? ' – ' + esc(s.detail) : '');
                        }).join('<br>');
                        out.innerHTML = '<div style="font-weight:600;margin-bottom:4px;">'
                            + (good ? 'Egress-Sperre deaktiviert.' : 'Deaktivierung unvollständig – Details:')
                            + '</div>' + lines;
                    }
                    Mgr.renderEgress(d.status);
                })
                .catch(function () {
                    if (out) { out.style.display = 'block'; out.innerHTML = 'Fehler bei der Deaktivierung.'; }
                })
                .then(function () {
                    if (btn) { btn.disabled = false; btn.textContent = orig || T('security.egress_teardown', 'Deaktivieren'); }
                });
        },

        loadSandbox: function (live) {
            var box = $('sec-sandbox-status');
            if (box && live) box.innerHTML = '⏳ Isolationstest läuft…';
            fetch('/api/security/sandbox' + (live ? '?live=1' : ''), { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { Mgr.renderSandbox(d); })
                .catch(function () {});
        },

        renderSandbox: function (d) {
            var box = $('sec-sandbox-status');
            if (!box) return;
            if (!d) { box.innerHTML = ''; return; }
            function row(ok, label) {
                var mark = ok === true ? '✅' : (ok === false ? '❌' : '❔');
                return '<div>' + mark + ' ' + esc(label) + '</div>';
            }
            var iso = d.isolation || null;
            var head;
            if (d.ok) {
                head = (iso && iso.secret_readable)
                    ? '🟠 <b>Aktiv – aber Secrets für den Sandbox-Benutzer noch lesbar!</b>'
                    : '🟢 <b>Aktiv' + (iso ? ' &amp; live verifiziert' : '') + '</b>';
            } else if (d.active && !d.user_exists) {
                head = '🟠 <b>Konfiguriert, aber OS-Benutzer fehlt</b>';
            } else if (d.active && !d.secrets_locked) {
                head = '🟠 <b>Aktiv, aber Secret-Dateirechte offen</b>';
            } else if (!d.active) {
                head = '⚪ <b>Inaktiv – nur Code-Härtung</b>';
            } else {
                head = '🔴 <b>Nicht vollständig eingerichtet</b>';
            }
            var rows = ''
                + row(d.active, 'OS-Sandbox aktiviert (Einstellung sandbox_shell_user)')
                + row(d.user_exists, 'Unprivilegierter OS-Benutzer: ' + (d.user || '') + (d.uid != null ? ' (uid ' + d.uid + ')' : ' — fehlt'))
                + row(d.secrets_locked, 'Secret-Dateien gesperrt (nur root lesbar)');
            if (iso) {
                rows += row(iso.secret_readable === false, 'Live-Test: Secrets für Sandbox-Benutzer ' + (iso.secret_readable ? 'LESBAR ⚠' : 'nicht lesbar'));
                rows += row(iso.tmp_writable === true, 'Live-Test: Arbeitsbereich /tmp schreibbar');
            }
            box.innerHTML = '<div style="margin-bottom:6px;">' + head + '</div>'
                + '<div style="line-height:1.75;">' + rows + '</div>';
        },

        // Generischer POST-Aktions-Helfer (Einrichten/Deaktivieren) mit Schritt-Ausgabe
        _runAction: function (o) {
            if (o.confirm && !window.confirm(o.confirm)) return;
            var btn = $(o.btn), out = $(o.result), orig = btn ? btn.textContent : '';
            if (btn) { btn.disabled = true; btn.textContent = o.busy; }
            fetch(o.url, { method: 'POST', headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    d = d || {};
                    if (out) {
                        out.style.display = 'block';
                        var good = !!d.ok;
                        out.style.borderColor = good ? 'rgba(var(--success-rgb),0.5)' : 'rgba(var(--danger-rgb),0.5)';
                        out.style.background = good ? 'rgba(var(--success-rgb),0.1)' : 'rgba(var(--danger-rgb),0.1)';
                        var lines = (d.steps || []).map(function (s) {
                            return (s.ok ? '✅' : '❌') + ' ' + esc(s.name) + (s.detail && !s.ok ? ' – ' + esc(s.detail) : '');
                        }).join('<br>');
                        out.innerHTML = '<div style="font-weight:600;margin-bottom:4px;">'
                            + esc(good ? o.okMsg : o.failMsg) + '</div>' + lines;
                    }
                    if (o.render) o.render(d.status);
                })
                .catch(function () { if (out) { out.style.display = 'block'; out.innerHTML = 'Fehler bei der Ausführung.'; } })
                .then(function () { if (btn) { btn.disabled = false; btn.textContent = orig || o.busy; } });
        },

        setupSandbox: function () {
            Mgr._runAction({
                url: '/api/security/sandbox/setup', btn: 'sec-sandbox-setup', result: 'sec-sandbox-result',
                busy: T('security.busy_setup', 'Wird eingerichtet…'), okMsg: 'OS-Sandbox aktiv & verifiziert.',
                failMsg: 'Einrichtung unvollständig – Details:',
                render: function (s) { Mgr.renderSandbox(s); }
            });
        },

        teardownSandbox: function () {
            Mgr._runAction({
                url: '/api/security/sandbox/teardown', btn: 'sec-sandbox-teardown', result: 'sec-sandbox-result',
                busy: T('security.busy_teardown', 'Wird deaktiviert…'), okMsg: 'OS-Sandbox deaktiviert.',
                failMsg: 'Deaktivierung unvollständig – Details:',
                render: function (s) { Mgr.renderSandbox(s); },
                confirm: 'OS-Sandbox wirklich deaktivieren?\n\n'
                    + 'Shell-Befehle von Netzwerk-Benutzern MIT Internet-Freigabe laufen danach '
                    + 'wieder als Dienst-Benutzer (nur Code-Härtung, keine harte OS-Grenze). '
                    + 'Benutzer OHNE Internet-Freigabe bleiben über die Egress-Sperre gekapselt.'
            });
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
                    + '<button type="button" class="sec-btn small sec-blk-log">' + esc(T('security.view_log', 'Log ansehen')) + '</button>'
                    + '<button type="button" class="sec-btn small primary sec-blk-unblock">' + esc(T('security.unblock', 'Freischalten')) + '</button>'
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
