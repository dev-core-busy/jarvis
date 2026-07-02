/* Support-Assistent – Seitenlogik (/support)
   Login (Token-Fallback), Status (Jira-Checkbox), Suche + Ergebnis-Rendering. */
(function () {
    'use strict';

    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            var v = localStorage.getItem(TOKEN_KEYS[i]);
            if (v) return v;
        }
        return '';
    }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    // Übersetzung mit Fallback (deutscher Text), falls i18n nicht geladen
    function T(key, def) { return (window.t && window.t(key)) || def; }
    // CPU-Auslastung: /api/cpu pollen und Topbar-Bar aktualisieren
    var _cpuTimer = null;
    function _updateCpu(pct) {
        var fill = $('cpu-bar-fill'), label = $('cpu-bar-label');
        if (!fill || !label) return;
        var p = Math.max(0, Math.min(100, Number(pct) || 0));
        fill.style.width = p + '%';
        fill.style.backgroundPosition = p + '% 0';
        label.textContent = 'CPU: ' + Math.round(p) + '%';
    }
    function _pollCpu() {
        fetch('/api/cpu', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d) _updateCpu(d.cpu); })
            .catch(function () {});
    }
    function _startCpu() {
        if (_cpuTimer) return;
        _pollCpu();
        _cpuTimer = setInterval(_pollCpu, 3000);
    }
    // KI-Zusammenfassung ab >10 Zeilen einklappen + 'mehr'/'weniger'-Umschalter
    function _applyAiClamp() {
        var el = document.querySelector('.sup-ai-text.sup-ai-md');
        if (!el) return;
        var cs = window.getComputedStyle(el);
        var lh = parseFloat(cs.lineHeight);
        if (!lh || isNaN(lh)) lh = (parseFloat(cs.fontSize) || 15) * 1.55;
        var maxH = Math.round(lh * 10);   // 10 Zeilen
        if (el.scrollHeight <= maxH + 8) return;   // ≤10 Zeilen → nichts tun
        el.classList.add('sup-ai-collapsed');
        el.style.maxHeight = maxH + 'px';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'sup-ai-more';
        btn.textContent = T('sup.more', 'mehr');
        btn.addEventListener('click', function () {
            if (el.classList.contains('sup-ai-collapsed')) {
                el.classList.remove('sup-ai-collapsed');
                el.style.maxHeight = 'none';
                btn.textContent = T('sup.less', 'weniger');
            } else {
                el.classList.add('sup-ai-collapsed');
                el.style.maxHeight = maxH + 'px';
                btn.textContent = T('sup.more', 'mehr');
                var card = el.closest('.sup-ai-card'); if (card) card.scrollIntoView({ block: 'nearest' });
            }
        });
        el.parentNode.insertBefore(btn, el.nextSibling);
    }
    // Basis-URL der Jira-Instanz (vom Backend) – fuer Ticket-Key-Links
    var _jiraBase = '';
    // Escapen + http(s)-URLs UND Jira-Ticket-Keys (z.B. NXDISPATHO-19706) verlinken
    function escLink(s) {
        var html = esc(s);
        // 1) http(s)-URLs sichern (Platzhalter), damit die Ticket-Erkennung sie
        //    nicht im href/Text zerreisst.
        var urls = [];
        html = html.replace(/(https?:\/\/[^\s<]+)/g, function (u) {
            var tail = '';
            var m = u.match(/[)\].,;:!?]+$/);
            if (m) { tail = m[0]; u = u.slice(0, -tail.length); }
            urls.push('<a href="' + u + '" target="_blank" rel="noopener" '
                + 'style="color:var(--accent-hover);word-break:break-all;">' + u + '</a>' + tail);
            return '@@URL' + (urls.length - 1) + '@@';
        });
        // 2) Ticket-Keys (PROJEKT-NUMMER) als Links, wenn Jira-Basis bekannt
        if (_jiraBase) {
            html = html.replace(/\b([A-Z][A-Z0-9]+-\d+)\b/g, function (key) {
                return '<a href="' + _jiraBase + '/browse/' + key + '" target="_blank" '
                    + 'rel="noopener" style="color:var(--accent-hover);">' + key + '</a>';
            });
        }
        // 3) gesicherte URLs wiederherstellen
        return html.replace(/@@URL(\d+)@@/g, function (_, i) { return urls[+i]; });
    }

    function showApp() {
        $('sup-login').classList.add('hidden');
        $('sup-app').classList.remove('hidden');
        loadStatus();
        bind();
        startLlmStatus();
        if (window.refreshBranding) try { window.refreshBranding(); } catch (e) {}
    }

    // ── LLM-Verbindungsanzeige (wie jarvis/chat): Punkt gruen/rot, alle 30s ──
    var _llmStatusTimer = null;
    function checkLlmStatus() {
        var dot = $('sup-status-dot');
        if (!dot) return;
        fetch('/api/llm/active-status', { headers: authHeaders() })
            .then(function (r) { if (!r.ok) throw new Error('http'); return r.json(); })
            .then(function (d) {
                var reachable = (d.status === 'ok' || d.status === 'degraded');
                dot.className = 'sup-status-dot ' + (reachable ? 'connected' : 'disconnected');
                var name = d.profile_name ? ' – ' + d.profile_name : '';
                dot.title = (d.status === 'ok' ? T('sup.llm_ok', 'LLM erreichbar')
                    : d.status === 'degraded' ? T('sup.llm_degraded', 'LLM erreichbar (Modell fehlt)')
                    : T('sup.llm_down', 'LLM nicht erreichbar')) + name;
            })
            .catch(function () {
                dot.className = 'sup-status-dot disconnected';
                dot.title = T('sup.llm_down', 'LLM nicht erreichbar');
            });
    }
    function startLlmStatus() {
        checkLlmStatus();
        if (!_llmStatusTimer) _llmStatusTimer = setInterval(checkLlmStatus, 30000);
    }

    // ── Checkbox-Vorbelegung pro Browser/Session merken ──
    function getPref(key) {
        var v = localStorage.getItem('jarvis_support_' + key);
        return v === null ? true : v === '1';  // Default: an
    }
    function setPref(key, on) {
        localStorage.setItem('jarvis_support_' + key, on ? '1' : '0');
    }
    function clampNum(v, lo, hi) { v = parseInt(v, 10); if (isNaN(v)) v = hi; return Math.max(lo, Math.min(v, hi)); }
    function getNumPref(key) { var v = localStorage.getItem('jarvis_support_' + key); return v === null ? null : parseInt(v, 10); }
    function setNumPref(key, n) { localStorage.setItem('jarvis_support_' + key, String(n)); }
    var _supMax = { sum: 5, res: 2, tickets: 50 };
    var _supDefault = { tickets: 12 };
    var _me = null;  // angemeldeter Benutzer (fuer benutzerbasierte Prefs)

    function loadStatus() {
        fetch('/api/support/status', { headers: authHeaders() })
            .then(function (r) { if (r.status === 401) { logout(); return null; } return r.json(); })
            .then(function (d) {
                if (!d) return;
                // Sichtbarkeit je nach aktivem Skill
                $('sup-opt-jira-wrap').classList.toggle('hidden', !d.jira_active);
                $('sup-opt-open-wrap').classList.toggle('hidden', !d.jira_active);
                $('sup-opt-conf-wrap').classList.toggle('hidden', !d.confluence_active);
                // Gespeicherte Vorbelegung anwenden (Default: an)
                $('sup-opt-jira').checked = getPref('jira');
                $('sup-opt-conf').checked = getPref('conf');
                $('sup-opt-rag').checked = getPref('rag');
                $('sup-opt-ai').checked = getPref('ai');
                $('sup-opt-open').checked = getPref('open');
                // Exklusiv: nie 'alle' UND 'offene' zugleich → Standard 'offene'
                if ($('sup-opt-jira').checked && $('sup-opt-open').checked) {
                    $('sup-opt-jira').checked = false; setPref('jira', false);
                }
                // Darstellungs-Parameter: Maxima vom Server, Nutzerwert aus localStorage
                _supMax.sum = parseInt(d.summary_lines_max, 10) || 5;
                _supMax.res = parseInt(d.result_lines_max, 10) || 2;
                _supMax.tickets = parseInt(d.ticket_count_max, 10) || 50;
                _supDefault.tickets = parseInt(d.ticket_count_default, 10) || 12;
                var sEl = $('sup-u-sumlines'), rEl = $('sup-u-reslines'), tEl = $('sup-u-tickets');
                if (sEl) {
                    sEl.max = _supMax.sum;
                    var sp = getNumPref('sumlines'); sEl.value = clampNum(sp === null ? _supMax.sum : sp, 2, _supMax.sum);
                }
                if (rEl) {
                    rEl.max = _supMax.res;
                    var rp = getNumPref('reslines'); rEl.value = clampNum(rp === null ? _supMax.res : rp, 2, _supMax.res);
                }
                if (tEl) {
                    tEl.max = _supMax.tickets;
                    var tp = getNumPref('tickets'); tEl.value = clampNum(tp === null ? _supDefault.tickets : tp, 1, _supMax.tickets);
                }
                var hint = $('sup-u-hint');
                if (hint) hint.textContent = '(max. ' + _supMax.sum + ' / ' + _supMax.res + ' Zeilen)';
                var thint = $('sup-u-thint');
                if (thint && tEl) thint.textContent = '(' + tEl.value + '/' + _supMax.tickets + ')';
            })
            .catch(function () {});
    }

    function logout() {
        TOKEN_KEYS.forEach(function (k) { localStorage.removeItem(k); });
        $('sup-app').classList.add('hidden');
        $('sup-login').classList.remove('hidden');
    }

    var _bound = false;
    function bind() {
        if (_bound) return; _bound = true;
        $('sup-search-btn').addEventListener('click', search);
        $('sup-input').addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); search(); }
        });
        // Checkbox-Werte als Vorbelegung fuer die naechste Session merken
        // 'alle Jira' und 'offene Jira' schliessen sich gegenseitig aus
        $('sup-opt-jira').addEventListener('change', function () {
            if (this.checked && $('sup-opt-open').checked) { $('sup-opt-open').checked = false; setPref('open', false); }
            setPref('jira', this.checked);
        });
        $('sup-opt-open').addEventListener('change', function () {
            if (this.checked && $('sup-opt-jira').checked) { $('sup-opt-jira').checked = false; setPref('jira', false); }
            setPref('open', this.checked);
        });
        $('sup-opt-conf').addEventListener('change', function () { setPref('conf', this.checked); });
        $('sup-opt-rag').addEventListener('change', function () { setPref('rag', this.checked); });
        $('sup-opt-ai').addEventListener('change', function () { setPref('ai', this.checked); });
        // Abmelden (global: alle Token-Keys) -> zurueck zum Portal
        var _lo = $('sup-logout-btn');
        if (_lo) _lo.addEventListener('click', function () {
            TOKEN_KEYS.forEach(function (k) { localStorage.removeItem(k); });
            ['jarvis_user', 'jarvis_chat_user', 'jarvis_uc_user'].forEach(function (k) { localStorage.removeItem(k); });
            window.location.href = '/portal';
        });
        // LLM-Status-Pill: nur fuer Admins klickbar -> Einstellungen (LLM-Profile)
        fetch('/api/me', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                // Angemeldeten Benutzer merken -> erweiterte Einstellungen benutzerbasiert
                if (d.username) { _me = d.username; applyAdvState(); }
                // Angemeldeten Benutzer als Tooltip am Logout-Button ('<user> abmelden')
                var lo = $('sup-logout-btn');
                if (lo && d.username) lo.title = d.username + ' abmelden';
                if (d.is_admin) {
                    var dot = $('sup-status-dot');
                    if (dot) {
                        dot.style.cursor = 'pointer';
                        dot.title = T('chat.llm_settings', 'LLM-Profile öffnen');
                        dot.addEventListener('click', function () { try{sessionStorage.setItem('jarvis_settings_return','/support');}catch(e){} window.location.href = '/settings'; });
                    }
                    // Setup-Button (direkt vor Logout) fuer Admins einblenden
                    var sb = $('sup-settings-btn');
                    if (sb) {
                        sb.style.display = '';
                        sb.addEventListener('click', function () { try{sessionStorage.setItem('jarvis_settings_return','/support');}catch(e){} window.location.href = '/settings'; });
                    }
                }
            }).catch(function () {});
        // CPU-Auslastung (fuer alle): /api/cpu pollen und Bar aktualisieren
        _startCpu();
        // Sprachwechsel: statische Labels via applyLang (i18n.js), dynamische Treffer neu rendern
        if (window.setLang && !window._supLangWrapped) {
            window._supLangWrapped = true;
            var _origSetLang = window.setLang;
            window.setLang = function (l) {
                _origSetLang(l);
                try { if (_lastData) render(_lastData); } catch (e) {}
            };
        }
        // Darstellungs-Parameter (Nutzerwert 2 … Maximum, sitzungsüberdauernd)
        var sEl = $('sup-u-sumlines'), rEl = $('sup-u-reslines');
        if (sEl) sEl.addEventListener('change', function () {
            var v = clampNum(this.value, 2, _supMax.sum); this.value = v; setNumPref('sumlines', v);
        });
        if (rEl) rEl.addEventListener('change', function () {
            var v = clampNum(this.value, 2, _supMax.res); this.value = v; setNumPref('reslines', v);
            try { document.documentElement.style.setProperty('--sup-rl', String(v)); } catch (e) {}  // sofort anwenden
        });
        var tEl = $('sup-u-tickets');
        if (tEl) tEl.addEventListener('change', function () {
            var v = clampNum(this.value, 1, _supMax.tickets); this.value = v; setNumPref('tickets', v);
            var th = $('sup-u-thint'); if (th) th.textContent = '(' + v + '/' + _supMax.tickets + ')';
        });
        // Eingrenzungs-Pulldowns → Ergebnis live neu filtern (clientseitig)
        ['sup-f-source', 'sup-f-rel', 'sup-f-sort', 'sup-f-limit'].forEach(function (id) {
            var el = $(id);
            if (el) el.addEventListener('change', renderBlocks);
        });
        // Verlauf (benutzerabhaengig)
        $('sup-hist-btn').addEventListener('click', function (e) {
            e.stopPropagation();
            var panel = $('sup-hist-panel');
            if (panel.classList.contains('hidden')) { loadHistory(); panel.classList.remove('hidden'); }
            else panel.classList.add('hidden');
        });
        $('sup-hist-clear').addEventListener('click', clearHistory);
        document.addEventListener('click', function (e) {
            var w = document.querySelector('.sup-hist-wrap');
            if (w && !w.contains(e.target)) $('sup-hist-panel').classList.add('hidden');
        });
        // Dokument-Viewer (lokale Wissensquellen)
        $('sup-results').addEventListener('click', function (e) {
            var a = e.target.closest ? e.target.closest('.sup-doc-link') : null;
            if (a) { e.preventDefault(); openDoc(a.getAttribute('data-doc'), a.getAttribute('data-label')); return; }
            var btn = e.target.closest ? e.target.closest('.sup-ai-btn') : null;
            if (btn) { e.preventDefault(); summarizeTicket(btn); }
        });
        $('sup-doc-close').addEventListener('click', closeDoc);
        $('sup-doc-modal').addEventListener('click', function (e) { if (e.target === this) closeDoc(); });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { closeDoc(); $('sup-help-modal').classList.add('hidden'); }
        });
        // Hilfe-Popup (Score & Trefferzahl)
        $('sup-help-btn').addEventListener('click', function () { $('sup-help-modal').classList.remove('hidden'); });
        $('sup-help-close').addEventListener('click', function () { $('sup-help-modal').classList.add('hidden'); });
        $('sup-help-modal').addEventListener('click', function (e) { if (e.target === this) this.classList.add('hidden'); });

        // ── Eigene Anweisungen (userspezifisch, dauerhaft) ──
        if ($('sup-instr-btn')) $('sup-instr-btn').addEventListener('click', openInstructions);
        if ($('sup-instr-close')) $('sup-instr-close').addEventListener('click', function () { $('sup-instr-overlay').classList.add('hidden'); });
        if ($('sup-instr-overlay')) $('sup-instr-overlay').addEventListener('click', function (e) { if (e.target === this) this.classList.add('hidden'); });
        if ($('sup-instr-save')) $('sup-instr-save').addEventListener('click', saveInstructions);

        // ── Erweiterte Einstellungen ein-/ausklappen (benutzerbasiert gespeichert) ──
        var advBtn = $('sup-adv-toggle');
        if (advBtn) advBtn.addEventListener('click', function () { setAdvOpen(!_advOpen); });
        applyAdvState();
    }

    // Zustand der erweiterten Einstellungen: benutzerbasiert (Key enthaelt Benutzername)
    var _advOpen = false;
    function _advKey() { return 'jarvis_support_adv_open_' + (_me || 'anon'); }
    function applyAdvState() {
        var v = localStorage.getItem(_advKey());
        setAdvOpen(v === '1', true);  // Default: eingeklappt
    }
    function setAdvOpen(open, silent) {
        _advOpen = !!open;
        var panel = $('sup-adv'), btn = $('sup-adv-toggle');
        if (panel) panel.classList.toggle('hidden', !_advOpen);
        if (btn) btn.setAttribute('aria-expanded', _advOpen ? 'true' : 'false');
        if (!silent) localStorage.setItem(_advKey(), _advOpen ? '1' : '0');
    }

    function openInstructions() {
        var st = $('sup-instr-status'); if (st) st.textContent = T('common.loading', 'Lädt…');
        $('sup-instr-overlay').classList.remove('hidden');
        fetch('/api/support/instructions', { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                $('sup-instr-text').value = (d && d.instructions) || '';
                var wrap = $('sup-instr-admin'), box = $('sup-instr-admin-box');
                var adm = (d && d.admin_prompt) || '';
                if (wrap && box) {
                    if (adm) { box.textContent = adm; wrap.classList.remove('hidden'); }
                    else { box.textContent = ''; wrap.classList.add('hidden'); }
                }
                if (st) st.textContent = '';
            })
            .catch(function () { if (st) st.textContent = '✗ ' + T('sup.instr_load_fail', 'Laden fehlgeschlagen'); });
    }

    function saveInstructions() {
        var st = $('sup-instr-status'); if (st) st.textContent = T('common.saving', 'Speichert…');
        fetch('/api/support/instructions', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ instructions: $('sup-instr-text').value })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.ok) {
                    if (st) { st.textContent = '✓ ' + T('sup.instr_saved', 'Gespeichert'); st.style.color = 'var(--success)'; }
                    setTimeout(function () { if (st) { st.textContent = ''; st.style.color = ''; } $('sup-instr-overlay').classList.add('hidden'); }, 1200);
                } else {
                    if (st) { st.textContent = '✗ ' + ((d && d.error) || T('sup.instr_save_fail', 'Speichern fehlgeschlagen')); st.style.color = 'var(--danger)'; }
                }
            })
            .catch(function (e) { if (st) { st.textContent = '✗ ' + e.message; st.style.color = 'var(--danger)'; } });
    }

    function closeDoc() { $('sup-doc-modal').classList.add('hidden'); }

    function openDoc(path, label) {
        var modal = $('sup-doc-modal');
        $('sup-doc-title').textContent = label || 'Dokument';
        $('sup-doc-body').innerHTML = '<span class="sup-spinner"></span> Lade…';
        modal.classList.remove('hidden');
        fetch('/api/knowledge/file_read?path=' + encodeURIComponent(path), { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) {
                    $('sup-doc-body').textContent = (d && d.error) || 'Dokument konnte nicht geladen werden.';
                    return;
                }
                var content = d.content || '';
                // JSON hübsch formatieren, falls parsebar
                try { content = JSON.stringify(JSON.parse(content), null, 2); } catch (e) {}
                $('sup-doc-body').innerHTML = escLink(content);
            })
            .catch(function () { $('sup-doc-body').textContent = 'Dokument konnte nicht geladen werden.'; });
    }

    function relTime(ts) {
        var diff = Math.floor(Date.now() / 1000) - (ts || 0);
        var en = (localStorage.getItem('jarvis_lang') || 'de') === 'en';
        var pre = en ? '' : 'vor ', post = en ? ' ago' : '';
        if (diff < 60) return T('sup.now', 'gerade eben');
        if (diff < 3600) return pre + Math.floor(diff / 60) + ' ' + T('sup.min', 'Min') + post;
        if (diff < 86400) return pre + Math.floor(diff / 3600) + ' ' + T('sup.hours', 'Std') + post;
        if (diff < 604800) return pre + Math.floor(diff / 86400) + ' ' + T('sup.days', 'Tg') + post;
        try { return new Date(ts * 1000).toLocaleDateString(); } catch (e) { return ''; }
    }

    function loadHistory() {
        var list = $('sup-hist-list');
        list.innerHTML = '<div class="sup-hist-empty"><span class="sup-spinner"></span></div>';
        fetch('/api/support/history', { headers: authHeaders() })
            .then(function (r) { if (r.status === 401) { logout(); return null; } return r.json(); })
            .then(function (d) {
                if (!d) return;
                var entries = (d && d.entries) || [];
                if (!entries.length) { list.innerHTML = '<div class="sup-hist-empty">' + esc(T('sup.hist_empty', 'Noch keine Anfragen.')) + '</div>'; return; }
                list.innerHTML = '';
                entries.forEach(function (e) {
                    var item = document.createElement('div');
                    item.className = 'sup-hist-item';
                    item.innerHTML = '<div class="sup-hist-q">' + esc(e.query) + '</div>'
                        + '<div class="sup-hist-meta">' + relTime(e.ts)
                        + (typeof e.total === 'number' ? ' · ' + e.total + ' ' + T('sup.hits', 'Treffer') : '') + '</div>';
                    item.addEventListener('click', function () {
                        $('sup-hist-panel').classList.add('hidden');
                        $('sup-input').value = e.query;
                        search();
                    });
                    list.appendChild(item);
                });
            })
            .catch(function () { list.innerHTML = '<div class="sup-hist-empty">' + esc(T('sup.hist_err', 'Fehler beim Laden.')) + '</div>'; });
    }

    function clearHistory() {
        fetch('/api/support/history', { method: 'DELETE', headers: authHeaders() })
            .then(function () { loadHistory(); })
            .catch(function () {});
    }

    function search() {
        var text = ($('sup-input').value || '').trim();
        if (!text) { $('sup-input').focus(); return; }
        var jiraWrap = $('sup-opt-jira-wrap');
        var confWrap = $('sup-opt-conf-wrap');
        var jiraHidden = jiraWrap.classList.contains('hidden');
        // Zwei exklusive Modi: alle Jira-Tickets ODER nur offene (oder keins)
        var allJira = !jiraHidden && $('sup-opt-jira').checked;
        var openJira = !jiraHidden && $('sup-opt-open').checked;
        var useConf = !confWrap.classList.contains('hidden') && $('sup-opt-conf').checked;
        var useRag = $('sup-opt-rag').checked;
        var useAi = $('sup-opt-ai').checked;

        var btn = $('sup-search-btn'); btn.disabled = true;
        var meta = $('sup-meta'); meta.classList.remove('hidden');
        meta.innerHTML = '<span class="sup-spinner"></span>' + esc(T('sup.searching', 'Suche läuft…'));
        var box = $('sup-results');
        box.innerHTML = useAi
            ? '<div class="sup-ai-card"><div class="sup-ai-label">' + esc(T('sup.ai_label', 'KI-Gesamtzusammenfassung')) + '</div>'
              + '<div class="sup-ai-text"><span class="sup-spinner"></span>' + esc(T('sup.evaluating', 'Quellen werden ausgewertet…')) + '</div></div>'
            : '<div class="sup-empty"><span class="sup-spinner"></span>' + esc(T('sup.searching', 'Suche läuft…')) + '</div>';

        fetch('/api/support/query', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ text: text, jira_all: allJira, jira_open: openJira,
                                   confluence: useConf, rag: useRag, ai: useAi,
                                   lang: (localStorage.getItem('jarvis_lang') || 'de'),
                                   jira_limit: clampNum(getNumPref('tickets') === null ? _supDefault.tickets : getNumPref('tickets'), 1, _supMax.tickets),
                                   summary_lines: clampNum(getNumPref('sumlines') === null ? _supMax.sum : getNumPref('sumlines'), 2, _supMax.sum) })
        })
            .then(function (r) { if (r.status === 401) { logout(); return null; } return r.json(); })
            .then(function (d) {
                btn.disabled = false;
                if (!d) return;
                if (!d.ok) {
                    meta.textContent = '';
                    box.innerHTML = '<div class="sup-empty">' + esc(d.error || T('sup.search_failed', 'Suche fehlgeschlagen.')) + '</div>';
                    return;
                }
                render(d);
            })
            .catch(function () {
                btn.disabled = false;
                meta.textContent = '';
                box.innerHTML = '<div class="sup-empty">' + esc(T('sup.search_failed', 'Suche fehlgeschlagen.')) + '</div>';
            });
    }

    var _lastData = null;

    function render(d) {
        _lastData = d;
        if (d.jira_base) _jiraBase = d.jira_base;   // fuer Ticket-Key-Links in Texten
        // Antwortzeilen: Nutzerwert, begrenzt auf das Admin-Maximum (Anzeige-Kappung)
        var rMax = parseInt(d.result_lines_max || d.result_lines, 10) || 2;
        var rUser = clampNum(getNumPref('reslines') === null ? rMax : getNumPref('reslines'), 2, rMax);
        try { document.documentElement.style.setProperty('--sup-rl', String(rUser)); } catch (e) {}
        var html = '';
        if (d.ai_summary) {
            // Volles Markdown rendern (Tabellen/Überschriften/Listen/**fett**/Links);
            // Fallback: nur **fett**, falls der Renderer nicht geladen ist.
            var _sum = (window.JarvisChatLib && window.JarvisChatLib.renderMarkdown)
                ? window.JarvisChatLib.renderMarkdown(d.ai_summary)
                : escLink(d.ai_summary).replace(/\*\*([^\n*][^*]*?)\*\*/g, '<strong>$1</strong>');
            html += '<div class="sup-ai-card"><div class="sup-ai-label">' + esc(T('sup.ai_label', 'KI-Gesamtzusammenfassung')) + '</div>'
                + '<div class="sup-ai-text sup-ai-md">' + _sum + '</div></div>';
        }
        html += '<div id="sup-blocks"></div>';
        $('sup-results').innerHTML = html;
        renderBlocks();
        _applyAiClamp();
    }

    function blockHtml(b, i) {
        var label = b.source_label || b.title || 'Quelle';
        var inner;
        if (b.link) {
            inner = '<a href="' + esc(b.link) + '" target="_blank" rel="noopener">' + esc(label) + ' ↗</a>';
        } else if (b.doc) {
            // lokales Wissensdokument → im Viewer öffnen
            var dl = label + (b.doc_name ? ' (' + b.doc_name + ')' : '');
            inner = '<a href="#" class="sup-doc-link" data-doc="' + esc(b.doc)
                + '" data-label="' + esc(dl) + '">' + esc(dl) + '</a>';
        } else {
            inner = esc(label);
        }
        var srcHtml = '<div class="sup-block-src">' + esc(T('sup.source_prefix', 'Quelle:')) + ' ' + inner + '</div>';
        // Jira-Tickets: On-Demand-Button "KI-Zusammenfassung" rechts in der Kopfzeile
        var aiBtn = '';
        if (b.source === 'JIRA' && (b.key || b.title)) {
            aiBtn = '<button type="button" class="sup-ai-btn" data-key="' + esc(b.key || b.title) + '">'
                + esc(T('sup.ai_btn', 'KI-Zusammenfassung')) + '</button>';
        }
        return '<div class="sup-block">'
            + '<div class="sup-block-head">'
            + '<span class="sup-block-num">' + (i + 1) + '.</span>'
            + '<span class="sup-block-title">' + esc(b.title) + '</span>'
            + '<span class="sup-badge-src">' + esc(b.source) + '</span>'
            + '<span class="sup-badge-score" title="Zutreffend">' + b.score + '%</span>'
            + aiBtn
            + '</div>'
            + '<div class="sup-block-body">' + escLink(b.summary) + '</div>'
            + srcHtml
            + '</div>';
    }

    // Eine Liste, nach Relevanz (%) sortiert; Pulldown-Filter
    // (Quelle, Relevanz, Sortierung, Anzahl) wirken auf die gesamte Liste.
    function renderBlocks() {
        if (!_lastData) return;
        var all = (_lastData.blocks || []).slice();
        var src = $('sup-f-source') ? $('sup-f-source').value : '';
        var minRel = parseInt(($('sup-f-rel') ? $('sup-f-rel').value : '0'), 10) || 0;
        var sort = $('sup-f-sort') ? $('sup-f-sort').value : 'score';
        var limit = parseInt(($('sup-f-limit') ? $('sup-f-limit').value : '0'), 10) || 0;

        var list = all.filter(function (b) {
            if (src && b.source !== src) return false;
            if (minRel && b.score < minRel) return false;
            return true;
        });
        if (sort === 'source') list.sort(function (a, b) {
            return a.source === b.source ? b.score - a.score : a.source.localeCompare(b.source);
        });
        else if (sort === 'title') list.sort(function (a, b) {
            return String(a.title).localeCompare(String(b.title), 'de');
        });
        else list.sort(function (a, b) { return b.score - a.score; });
        if (limit) list = list.slice(0, limit);

        var metaStr = T('sup.result_for', 'Ergebnis für') + ' <strong>"' + esc(_lastData.query) + '"</strong> ('
            + list.length + ' ' + T('sup.of', 'von') + ' ' + all.length + ' ' + T('sup.hits', 'Treffer')
            + (_lastData.took_ms ? ' · ' + _lastData.took_ms + ' ms' : '') + ')';
        // Jira-Gesamtzahl (vor 12er-Deckelung) anzeigen, wenn mehr gefunden als angezeigt
        if (_lastData.jira_total != null) {
            var jiraShown = list.filter(function (b) { return b.source === 'JIRA'; }).length;
            if (jiraShown && _lastData.jira_total > jiraShown) {
                var word = _lastData.open_only ? T('sup.open_word', 'offenen') : T('sup.found_word', 'gefunden');
                metaStr += ' · Jira: ' + jiraShown + ' ' + T('sup.of', 'von') + ' ' + _lastData.jira_total + ' ' + word;
            }
        }
        $('sup-meta').innerHTML = metaStr;

        var box = $('sup-blocks');
        if (!box) return;
        if (!list.length) {
            box.innerHTML = '<div class="sup-empty">'
                + esc(all.length ? T('sup.no_filter', 'Keine Treffer mit diesen Filtern.')
                                 : T('sup.no_results', 'Keine passenden Quellen gefunden.'))
                + '</div>';
            return;
        }
        box.innerHTML = list.map(blockHtml).join('');
    }

    // On-Demand-KI-Zusammenfassung eines Jira-Tickets (Button je Ergebnisbox)
    function summarizeTicket(btn) {
        var key = btn.getAttribute('data-key');
        if (!key || btn.disabled) return;
        var block = btn.closest ? btn.closest('.sup-block') : null;
        var bodyEl = block ? block.querySelector('.sup-block-body') : null;
        if (!bodyEl) return;
        var orig = btn.textContent;
        btn.disabled = true;
        btn.innerHTML = '<span class="sup-spinner"></span>' + esc(T('sup.analyzing', 'Analysiere…'));
        var lines = clampNum(getNumPref('reslines') === null ? _supMax.res : getNumPref('reslines'), 2, _supMax.res);
        fetch('/api/support/summarize', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ key: key, source: 'JIRA',
                lang: (localStorage.getItem('jarvis_lang') || 'de'), lines: lines })
        })
            .then(function (r) { if (r.status === 401) { logout(); return null; } return r.json(); })
            .then(function (d) {
                btn.disabled = false;
                if (!d) return;
                if (!d.ok) {
                    btn.textContent = orig;
                    bodyEl.classList.add('expanded');
                    bodyEl.innerHTML = '<span style="color:var(--danger);">'
                        + esc(d.error || T('sup.search_failed', 'Suche fehlgeschlagen.')) + '</span>';
                    return;
                }
                if (d.jira_base) _jiraBase = d.jira_base;
                bodyEl.classList.add('expanded');
                bodyEl.innerHTML = escLink(d.summary);
                btn.textContent = T('sup.ai_btn_again', 'Neu zusammenfassen');
                btn.classList.add('done');   // farblich abgesetzter Zustand
            })
            .catch(function () { btn.disabled = false; btn.textContent = orig; });
    }

    // ── Login ──
    function bindLogin() {
        $('sup-login-form').addEventListener('submit', function (e) {
            e.preventDefault();
            var u = $('sup-login-user').value.trim();
            var p = $('sup-login-pass').value;
            $('sup-login-err').textContent = '';
            fetch('/api/login', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: u, password: p })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                  if (d && d.success && d.token) {
                      localStorage.setItem('jarvis_token', d.token);
                      showApp();
                  } else {
                      $('sup-login-err').textContent = (d && d.error) || 'Anmeldung fehlgeschlagen';
                  }
              })
              .catch(function () { $('sup-login-err').textContent = 'Netzwerkfehler'; });
        });
    }

    // ── Init ──
    bindLogin();
    if (token()) showApp();
    else $('sup-login').classList.remove('hidden');
})();
