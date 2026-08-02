/* ═══════════════════════════════════════════════════════════════════
   SAP-Analysebereich (/sap)
   ───────────────────────────────────────────────────────────────────
   Drei Dinge auf einer Seite:
     1. Management-Analysen  – Vorlage waehlen, Agent wertet lesend aus.
     2. BI-Anbindung         – fertige Verbindungsangaben je Werkzeug.
     3. Abfrage-Konsole      – OData/SQL direkt, ohne KI.

   Nicht zu verwechseln mit `sap.js`: das ist der Einstellungs-Reiter, in
   dem ein Administrator die ZUGANGSDATEN pflegt. Hier wird nur
   ausgewertet – die Seite zeigt keine Zugangsdaten und kann keine
   speichern.

   Berechtigung: jeder Endpunkt haengt serverseitig an `require_sap_access`.
   Die Pruefung hier ist reine Benutzerfuehrung – wer nicht freigegeben ist,
   soll aufs Portal zurueck statt auf einer Seite voller 403-Meldungen zu
   landen.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // Gleiche Schluesselkette wie support.js/portal.html – ein Benutzer, der
    // ueber /chat angemeldet ist, soll hier nicht erneut anmelden muessen.
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    var HIST_KEY = 'jarvis_sap_history';
    var HIST_MAX = 25;
    var PREF_TOOL = 'jarvis_sap_bitool';
    var PREF_ANALYSIS = 'jarvis_sap_analysis';

    function $(id) { return document.getElementById(id); }
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
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
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function lang() {
        try { return (localStorage.getItem('jarvis_lang') || 'de'); } catch (e) { return 'de'; }
    }
    function toPortal() { window.location.replace('/portal'); }

    var _catalog = null;     // {categories, analyses, bi_tools}
    var _status = null;      // /api/sap/status
    var _endpoints = [];     // /api/sap/reporting-endpoints
    var _abort = null;       // laufende Analyse (fetch-Abbruch)
    var _timer = null;       // Sekundenzaehler des Wartehinweises

    // ── Start ───────────────────────────────────────────────────────
    function init() {
        if (!token()) { window.location.replace('/'); return; }
        fetch('/api/me', { headers: authHeaders() })
            .then(function (r) {
                if (r.status === 401) { window.location.replace('/'); return null; }
                return r.ok ? r.json() : null;
            })
            .then(function (me) {
                if (!me) { toPortal(); return; }
                // Fail-closed: fehlt das Feld (aelteres Backend), gilt "nicht
                // freigegeben" – lieber zurueck aufs Portal als eine Seite,
                // auf der jeder Knopf 403 liefert.
                var may = !!(me.permissions && me.permissions.sap);
                if (!may) { toPortal(); return; }
                if (me.is_admin) {
                    var sb = $('sp-settings-btn');
                    if (sb) {
                        sb.style.display = '';
                        sb.addEventListener('click', function () {
                            try { sessionStorage.setItem('jarvis_settings_return', '/sap'); } catch (e) {}
                            window.location.href = '/settings';
                        });
                    }
                }
                showApp();
            })
            .catch(function () { toPortal(); });
    }

    function showApp() {
        $('sp-app').classList.remove('hidden');
        bind();
        loadStatus();
        loadCatalog();
        loadEndpoints();
        renderHistory();
        startLlmStatus();
        if (window.refreshBranding) { try { window.refreshBranding(); } catch (e) {} }
    }

    // ── LLM-Punkt (gleiches Muster wie /support, alle 30 s) ─────────
    var _llmTimer = null;
    function checkLlm() {
        var dot = $('sp-status-dot'); if (!dot) return;
        fetch('/api/llm/active-status', { headers: authHeaders() })
            .then(function (r) { if (!r.ok) throw new Error('http'); return r.json(); })
            .then(function (d) {
                var ok = (d.status === 'ok' || d.status === 'degraded');
                dot.className = 'sp-status-dot ' + (ok ? 'connected' : 'disconnected');
                dot.title = (d.status === 'ok' ? T('sup.llm_ok', 'LLM erreichbar')
                    : d.status === 'degraded' ? T('sup.llm_degraded', 'LLM erreichbar (Modell fehlt)')
                    : T('sup.llm_down', 'LLM nicht erreichbar')) + (d.profile_name ? ' – ' + d.profile_name : '');
            })
            .catch(function () {
                dot.className = 'sp-status-dot disconnected';
                dot.title = T('sup.llm_down', 'LLM nicht erreichbar');
            });
    }
    function startLlmStatus() { checkLlm(); if (!_llmTimer) _llmTimer = setInterval(checkLlm, 30000); }

    // ── Verbindungszustand ──────────────────────────────────────────
    function loadStatus() {
        fetch('/api/sap/status', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _status = d;
                var el = $('sp-conn'); if (!el) return;
                if (!d) { el.textContent = ''; return; }
                if (!d.configured) {
                    el.className = 'sp-conn is-off';
                    el.textContent = T('sap.not_configured', 'SAP nicht konfiguriert');
                    el.title = T('sap.not_configured_hint',
                        'Zugangsdaten hinterlegt ein Administrator unter Einstellungen → SAP.');
                    note(T('sap.not_configured_hint',
                        'Zugangsdaten hinterlegt ein Administrator unter Einstellungen → SAP.'), 'error');
                    return;
                }
                var names = { odata: 'OData', hana: 'HANA SQL', rfc: 'RFC' };
                el.className = 'sp-conn';
                el.textContent = (names[d.connection_type] || d.connection_type)
                    + (d.product ? ' · ' + d.product : '');
                el.title = T('sap.conn_hint', 'Aktive SAP-Schnittstelle');
            })
            .catch(function () {});
    }

    // ── Katalog: Analysen + BI-Werkzeuge ────────────────────────────
    function loadCatalog() {
        fetch('/api/sap/analyses?lang=' + encodeURIComponent(lang()), { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                _catalog = d;
                fillAnalyses();
                fillTools();
                applyDesc();
                markMatchingEndpoint();
            })
            .catch(function () {});
    }

    function fillAnalyses() {
        var sel = $('sp-analysis'); if (!sel || !_catalog) return;
        var html = '<option value="">' + esc(T('sap.free_question', '— Freie Frage (keine Vorlage) —')) + '</option>';
        _catalog.categories.forEach(function (c) {
            var items = _catalog.analyses.filter(function (a) { return a.cat === c.id; });
            if (!items.length) return;
            html += '<optgroup label="' + esc(c.title) + '">';
            items.forEach(function (a) {
                html += '<option value="' + esc(a.id) + '">' + esc(a.title) + '</option>';
            });
            html += '</optgroup>';
        });
        sel.innerHTML = html;
        var saved = localStorage.getItem(PREF_ANALYSIS);
        if (saved && sel.querySelector('option[value="' + saved.replace(/"/g, '') + '"]')) sel.value = saved;
    }

    function fillTools() {
        var sel = $('sp-bitool'); if (!sel || !_catalog) return;
        sel.innerHTML = _catalog.bi_tools.map(function (b) {
            return '<option value="' + esc(b.id) + '">' + esc(b.name) + '</option>';
        }).join('');
        var saved = localStorage.getItem(PREF_TOOL);
        if (saved && sel.querySelector('option[value="' + saved.replace(/"/g, '') + '"]')) sel.value = saved;
    }

    function currentAnalysis() {
        if (!_catalog) return null;
        var id = $('sp-analysis') ? $('sp-analysis').value : '';
        if (!id) return null;
        for (var i = 0; i < _catalog.analyses.length; i++) {
            if (_catalog.analyses[i].id === id) return _catalog.analyses[i];
        }
        return null;
    }

    function applyDesc() {
        var box = $('sp-desc'); if (!box) return;
        var a = currentAnalysis();
        if (!a) { box.classList.add('hidden'); return; }
        box.classList.remove('hidden');
        $('sp-desc-title').textContent = a.title;
        $('sp-desc-text').textContent = a.desc;
        $('sp-desc-kpis').innerHTML = (a.kpis || []).map(function (k) {
            return '<span class="sp-chip">' + esc(k) + '</span>';
        }).join('');
        $('sp-desc-src').textContent = T('sap.sources', 'Übliche SAP-Quellen') + ': ' + a.sources;
    }

    // ── BI-Anbindung ────────────────────────────────────────────────
    function loadEndpoints() {
        fetch('/api/sap/reporting-endpoints', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _endpoints = (d && d.endpoints) || [];
                renderEndpoints();
            })
            .catch(function () {});
    }

    function renderEndpoints() {
        var box = $('sp-bi-list'); if (!box) return;
        if (!_endpoints.length) {
            box.innerHTML = '<div class="sp-empty">'
                + esc(T('sap.no_endpoints',
                    'Keine Schnittstelle konfiguriert. Sobald ein Administrator unter Einstellungen → SAP Zugangsdaten hinterlegt, stehen hier die Verbindungsangaben.'))
                + '</div>';
            return;
        }
        box.innerHTML = _endpoints.map(function (e) {
            var tools = Object.keys(e.tools || {}).map(function (k) {
                return '<li><strong>' + esc(k) + ':</strong> ' + esc(e.tools[k]) + '</li>';
            }).join('');
            return '<div class="sp-ep" data-iface="' + esc(e.interface) + '">'
                + '<div class="sp-ep-name">' + esc(e.interface) + '</div>'
                + '<div class="sp-ep-url">' + esc(e.url) + '</div>'
                + '<ul class="sp-ep-list">' + tools + '</ul></div>';
        }).join('');
        markMatchingEndpoint();
    }

    // Hebt die Schnittstelle hervor, ueber die das oben gewaehlte Werkzeug
    // liest. Ohne das muss der Benutzer selbst wissen, dass Power BI ueber
    // OData und Grafana ueber HANA-SQL geht.
    function markMatchingEndpoint() {
        if (!_catalog) return;
        var id = $('sp-bitool') ? $('sp-bitool').value : '';
        var iface = null;
        _catalog.bi_tools.forEach(function (b) { if (b.id === id) iface = b.iface; });
        var nodes = document.querySelectorAll('#sp-bi-list .sp-ep');
        for (var i = 0; i < nodes.length; i++) {
            nodes[i].classList.toggle('is-match', !!iface && nodes[i].dataset.iface === iface);
        }
    }

    // ── Analyse ausfuehren ──────────────────────────────────────────
    function note(msg, kind) {
        var el = $('sp-note'); if (!el) return;
        el.className = 'sp-note' + (kind === 'error' ? ' is-error' : kind === 'ok' ? ' is-ok' : '');
        el.textContent = msg || '';
    }

    function busy(on) {
        var run = $('sp-run'), cancel = $('sp-cancel');
        if (run) run.disabled = !!on;
        if (cancel) cancel.classList.toggle('hidden', !on);
        clearInterval(_timer); _timer = null;
        if (!on) return;
        // Mitlaufende Sekunden: eine Analyse dauert je nach Datenmenge
        // Minuten – ohne sichtbaren Fortschritt wirkt die Seite tot.
        var t0 = Date.now();
        function tick() {
            var s = Math.round((Date.now() - t0) / 1000);
            note(T('sap.running', 'Analyse läuft …') + ' (' + s + ' s)');
        }
        tick();
        _timer = setInterval(tick, 1000);
    }

    function run() {
        var a = currentAnalysis();
        var q = ($('sp-question') ? $('sp-question').value : '').trim();
        if (!a && !q) {
            note(T('sap.need_input', 'Bitte eine Analyse wählen oder eine Frage eingeben.'), 'error');
            return;
        }
        if (_status && _status.configured === false) {
            note(T('sap.not_configured_hint',
                'Zugangsdaten hinterlegt ein Administrator unter Einstellungen → SAP.'), 'error');
            return;
        }
        var tool = $('sp-bitool') ? $('sp-bitool').value : '';
        localStorage.setItem(PREF_TOOL, tool);
        localStorage.setItem(PREF_ANALYSIS, a ? a.id : '');

        busy(true);
        showResult('<div class="sp-busy"><span class="sp-spin"></span><span>'
            + esc(T('sap.running_long',
                'Der Assistent liest die Daten aus SAP und verdichtet sie. Das kann einige Minuten dauern.'))
            + '</span></div>', a ? a.title : T('sap.free_question_short', 'Freie Frage'));

        _abort = new AbortController();
        fetch('/api/sap/ask', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                analysis_id: a ? a.id : '', question: q,
                bi_tool: tool, lang: lang()
            }),
            signal: _abort.signal
        })
            .then(function (r) {
                if (r.status === 423) {
                    // Konto wegen Sicherheitsverstoss gesperrt – dieselbe
                    // Behandlung wie im Chat.
                    return r.json().catch(function () { return {}; }).then(function (e) {
                        throw new Error(e.message || T('sap.blocked', 'Konto gesperrt.'));
                    });
                }
                return r.json().catch(function () { return null; });
            })
            .then(function (d) {
                if (!d) throw new Error(T('sap.failed', 'Analyse fehlgeschlagen.'));
                if (!d.ok) throw new Error(d.error || T('sap.failed', 'Analyse fehlgeschlagen.'));
                renderAnswer(d.answer || '', a ? a.title : T('sap.free_question_short', 'Freie Frage'));
                pushHistory(a, q, tool);
                note('');
            })
            .catch(function (e) {
                if (e && e.name === 'AbortError') {
                    showResult('<div class="sp-empty">'
                        + esc(T('sap.cancelled', 'Analyse abgebrochen.')) + '</div>', '');
                    note('');
                    return;
                }
                showResult('<div class="sp-empty" style="color:var(--danger);">'
                    + esc((e && e.message) || T('sap.failed', 'Analyse fehlgeschlagen.'))
                    + '</div>', '');
                note('');
            })
            .then(function () { busy(false); _abort = null; });
    }

    function cancel() {
        // Beide Seiten beenden: der Abbruch im Browser stoppt nur das Warten,
        // der Agent liefe sonst im Hintergrund weiter und blockierte die
        // Sperre fuer die naechste Analyse.
        if (_abort) { try { _abort.abort(); } catch (e) {} }
        fetch('/api/sap/stop', { method: 'POST', headers: authHeaders() }).catch(function () {});
    }

    function showResult(html, title) {
        var box = $('sp-result'); if (!box) return;
        box.classList.remove('hidden');
        if (title) $('sp-result-title').textContent = title;
        $('sp-result-body').innerHTML = html;
    }

    var _lastAnswer = '';
    function renderAnswer(text, title) {
        _lastAnswer = text;
        var html;
        if (window.JarvisChatLib && window.JarvisChatLib.renderMarkdown) {
            html = window.JarvisChatLib.renderMarkdown(text);
        } else {
            html = '<pre>' + esc(text) + '</pre>';
        }
        showResult(html, title);
        // ```chartjs-Bloecke zu echten Diagrammen machen. charts.js beobachtet
        // das DOM zwar selbst, der ausdrueckliche Aufruf spart die 250 ms
        // Debounce und wirkt auch, wenn der Beobachter nicht greift.
        if (window.JarvisCharts && window.JarvisCharts.hydrate) {
            try { window.JarvisCharts.hydrate($('sp-result-body')); } catch (e) {}
        }
    }

    // ── Verlauf (rein lokal im Browser) ─────────────────────────────
    // Bewusst localStorage und nicht serverseitig: der Verlauf ist eine
    // Bequemlichkeit fuer den einzelnen Arbeitsplatz. Gespeichert wird nur,
    // WAS gefragt wurde – nie das Ergebnis, damit keine Geschaeftszahlen im
    // Browser-Speicher liegen bleiben.
    function readHistory() {
        try { return JSON.parse(localStorage.getItem(HIST_KEY) || '[]') || []; }
        catch (e) { return []; }
    }
    function pushHistory(a, q, tool) {
        var list = readHistory();
        list.unshift({
            id: a ? a.id : '', title: a ? a.title : '',
            q: q, tool: tool, ts: Date.now()
        });
        try { localStorage.setItem(HIST_KEY, JSON.stringify(list.slice(0, HIST_MAX))); } catch (e) {}
        renderHistory();
    }
    function renderHistory() {
        var box = $('sp-hist-list'); if (!box) return;
        var list = readHistory();
        if (!list.length) {
            box.innerHTML = '<div class="sp-hist-empty">'
                + esc(T('sap.hist_empty', 'Noch keine Analysen ausgeführt.')) + '</div>';
            return;
        }
        box.innerHTML = list.map(function (it, i) {
            var label = it.title || it.q || T('sap.free_question_short', 'Freie Frage');
            var when = new Date(it.ts).toLocaleString();
            var sub = (it.title && it.q) ? (it.q + ' · ' + when) : when;
            return '<div class="sp-hist-item" data-i="' + i + '">'
                + '<div class="sp-hist-q">' + esc(label) + '</div>'
                + '<div class="sp-hist-meta">' + esc(sub) + '</div></div>';
        }).join('');
        Array.prototype.forEach.call(box.querySelectorAll('.sp-hist-item'), function (el) {
            el.addEventListener('click', function () {
                var it = readHistory()[parseInt(el.dataset.i, 10)];
                if (!it) return;
                if ($('sp-analysis')) $('sp-analysis').value = it.id || '';
                if ($('sp-question')) $('sp-question').value = it.q || '';
                if (it.tool && $('sp-bitool')) $('sp-bitool').value = it.tool;
                applyDesc();
                markMatchingEndpoint();
                $('sp-hist-panel').classList.add('hidden');
                // Nur eintragen, nicht starten: eine Analyse kostet Zeit und
                // Last – ein versehentlicher Klick im Verlauf darf sie nicht
                // ausloesen.
                note(T('sap.hist_loaded', 'Aus dem Verlauf übernommen – zum Starten „Analyse starten“ drücken.'));
            });
        });
    }

    // ── Anweisungen ─────────────────────────────────────────────────
    function openInstructions() {
        var st = $('sp-instr-status'); if (st) st.textContent = T('common.loading', 'Lädt…');
        $('sp-instr-overlay').classList.remove('hidden');
        fetch('/api/sap/instructions', { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                $('sp-instr-text').value = (d && d.instructions) || '';
                if (st) st.textContent = '';
            })
            .catch(function () { if (st) st.textContent = '✗ ' + T('sap.instr_load_fail', 'Laden fehlgeschlagen'); });
    }
    function saveInstructions() {
        var st = $('sp-instr-status'); if (st) st.textContent = T('common.saving', 'Speichert…');
        fetch('/api/sap/instructions', {
            method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ instructions: $('sp-instr-text').value })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.ok) {
                    if (st) { st.textContent = '✓ ' + T('common.saved', 'Gespeichert'); st.style.color = 'var(--success)'; }
                    setTimeout(function () {
                        if (st) { st.textContent = ''; st.style.color = ''; }
                        $('sp-instr-overlay').classList.add('hidden');
                    }, 1200);
                } else if (st) {
                    st.textContent = '✗ ' + ((d && d.error) || T('sap.instr_save_fail', 'Speichern fehlgeschlagen'));
                    st.style.color = 'var(--danger)';
                }
            })
            .catch(function () {
                if (st) { st.textContent = '✗ ' + T('sap.instr_save_fail', 'Speichern fehlgeschlagen'); st.style.color = 'var(--danger)'; }
            });
    }

    // ── Abfrage-Konsole ─────────────────────────────────────────────
    function renderTable(box, columns, rows) {
        if (!box) return;
        if (!rows || !rows.length) {
            box.innerHTML = '<div class="sp-empty">' + esc(T('sap.no_rows', 'Keine Zeilen.')) + '</div>';
            return;
        }
        var cols = (columns && columns.length) ? columns : Object.keys(rows[0]);
        var html = '<table><thead><tr>' + cols.map(function (c) {
            return '<th>' + esc(c) + '</th>';
        }).join('') + '</tr></thead><tbody>';
        rows.forEach(function (r) {
            html += '<tr>' + cols.map(function (c) { return '<td>' + esc(r[c]) + '</td>'; }).join('') + '</tr>';
        });
        box.innerHTML = html + '</tbody></table>';
    }
    function consoleError(msg) {
        var box = $('sp-console-out');
        if (box) box.innerHTML = '<div class="sp-empty" style="color:var(--danger);">' + esc(msg) + '</div>';
    }
    function runOData() {
        var box = $('sp-console-out');
        var entity = ($('sp-od-entity').value || '').trim();
        if (!entity) { consoleError(T('sap.need_entityset', 'Bitte ein EntitySet angeben.')); return; }
        box.innerHTML = '<div class="sp-empty">' + esc(T('common.loading', 'Lädt…')) + '</div>';
        var url = '/api/sap/odata/query?entity_set=' + encodeURIComponent(entity)
            + '&service=' + encodeURIComponent(($('sp-od-service').value || '').trim())
            + '&top=' + encodeURIComponent($('sp-od-top').value || '20');
        fetch(url, { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) { consoleError((d && d.error) || T('sap.query_failed', 'Abfrage fehlgeschlagen.')); return; }
                renderTable(box, d.columns, d.rows);
            })
            .catch(function () { consoleError(T('sap.query_failed', 'Abfrage fehlgeschlagen.')); });
    }
    function runSql() {
        var box = $('sp-console-out');
        var sql = ($('sp-sql').value || '').trim();
        if (!sql) { consoleError(T('sap.need_sql', 'Bitte eine SELECT-Abfrage eingeben.')); return; }
        box.innerHTML = '<div class="sp-empty">' + esc(T('common.loading', 'Lädt…')) + '</div>';
        fetch('/api/sap/sql', {
            method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ sql: sql, max_rows: Number($('sp-sql-max').value || 200) })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) { consoleError((d && d.error) || T('sap.query_failed', 'Abfrage fehlgeschlagen.')); return; }
                renderTable(box, d.columns, d.rows);
                if (d.truncated) {
                    box.insertAdjacentHTML('afterbegin', '<div class="sp-note is-error" style="margin-bottom:6px;">⚠️ '
                        + esc(T('sap.truncated', 'Ergebnis abgeschnitten.')) + '</div>');
                }
            })
            .catch(function () { consoleError(T('sap.query_failed', 'Abfrage fehlgeschlagen.')); });
    }
    function switchPane(name) {
        ['odata', 'sql'].forEach(function (p) {
            var tab = $('sp-tab-' + p), pane = $('sp-pane-' + p);
            if (tab) tab.classList.toggle('active', p === name);
            if (pane) pane.classList.toggle('hidden', p !== name);
        });
        var out = $('sp-console-out'); if (out) out.innerHTML = '';
    }

    // ── Verdrahtung ─────────────────────────────────────────────────
    var _bound = false;
    function bind() {
        if (_bound) return; _bound = true;

        $('sp-analysis').addEventListener('change', function () { applyDesc(); note(''); });
        $('sp-bitool').addEventListener('change', markMatchingEndpoint);
        $('sp-run').addEventListener('click', run);
        $('sp-cancel').addEventListener('click', cancel);
        $('sp-question').addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
        });

        $('sp-copy').addEventListener('click', function () {
            var done = function () { note(T('sap.copied', 'In die Zwischenablage kopiert.'), 'ok'); };
            if (window.JarvisChatLib && window.JarvisChatLib.copyTextToClipboard) {
                window.JarvisChatLib.copyTextToClipboard(_lastAnswer).then(done);
            } else if (navigator.clipboard) {
                navigator.clipboard.writeText(_lastAnswer).then(done);
            }
        });

        $('sp-instr-btn').addEventListener('click', openInstructions);
        $('sp-instr-close').addEventListener('click', function () { $('sp-instr-overlay').classList.add('hidden'); });
        $('sp-instr-overlay').addEventListener('click', function (e) {
            if (e.target === this) this.classList.add('hidden');
        });
        $('sp-instr-save').addEventListener('click', saveInstructions);

        $('sp-hist-btn').addEventListener('click', function (e) {
            e.stopPropagation();
            $('sp-hist-panel').classList.toggle('hidden');
        });
        $('sp-hist-clear').addEventListener('click', function (e) {
            e.stopPropagation();
            try { localStorage.removeItem(HIST_KEY); } catch (err) {}
            renderHistory();
        });
        // Klick daneben schliesst das Verlaufsfeld – sonst bleibt es beim
        // Weiterarbeiten ueber der Seite stehen.
        document.addEventListener('click', function (e) {
            var p = $('sp-hist-panel');
            if (p && !p.classList.contains('hidden') && !p.contains(e.target)) p.classList.add('hidden');
        });
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            // Reihenfolge: erst das obenauf liegende Fenster, sonst schliesst
            // Escape das Verlaufsfeld unter einem offenen Anweisungs-Dialog.
            var ov = $('sp-instr-overlay');
            if (ov && !ov.classList.contains('hidden')) { ov.classList.add('hidden'); return; }
            var p = $('sp-hist-panel');
            if (p && !p.classList.contains('hidden')) p.classList.add('hidden');
        });

        $('sp-tab-odata').addEventListener('click', function () { switchPane('odata'); });
        $('sp-tab-sql').addEventListener('click', function () { switchPane('sql'); });
        $('sp-od-run').addEventListener('click', runOData);
        $('sp-sql-run').addEventListener('click', runSql);

        $('sp-logout-btn').addEventListener('click', function () {
            var p = (window.JarvisSession ? window.JarvisSession.logout() : Promise.resolve());
            TOKEN_KEYS.forEach(function (k) { localStorage.removeItem(k); });
            p.catch(function () {}).then(function () { window.location.replace('/'); });
        });

        // Sprachwechsel: der Katalog kommt uebersetzt vom Server, also neu
        // holen. Die aktuelle Auswahl bleibt ueber die gespeicherte Vorgabe
        // erhalten.
        // Der Vergleich mit `_catalog.lang` ist noetig, weil applyLang() das
        // Ereignis auch beim Seitenaufbau feuert – ohne ihn holte die Seite
        // den Katalog jedes Mal zweimal.
        window.addEventListener('jarvis-lang-changed', function (e) {
            var lg = (e && e.detail && e.detail.lang) || lang();
            if (_catalog && _catalog.lang === (lg === 'en' ? 'en' : 'de')) return;
            localStorage.setItem(PREF_ANALYSIS, $('sp-analysis') ? $('sp-analysis').value : '');
            loadCatalog();
            renderHistory();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
