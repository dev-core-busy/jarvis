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
        loadAccount();
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
                accRenderState();
                if (!d.configured) {
                    el.className = 'sp-conn is-off';
                    el.textContent = T('sap.not_configured', 'SAP nicht konfiguriert');
                    el.title = T('sap.not_configured_hint2',
                        'Entweder hinterlegt ein Administrator einen gemeinsamen Lesezugang, '
                        + 'oder du trägst unter „Mein SAP-Zugang" deine eigenen Zugangsdaten ein.');
                    note(T('sap.not_configured_hint2',
                        'Entweder hinterlegt ein Administrator einen gemeinsamen Lesezugang, '
                        + 'oder du trägst unter „Mein SAP-Zugang" deine eigenen Zugangsdaten ein.'), 'error');
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

    function currentAnalysisById(id) {
        if (!_catalog || !id) return null;
        for (var i = 0; i < _catalog.analyses.length; i++) {
            if (_catalog.analyses[i].id === id) return _catalog.analyses[i];
        }
        return null;
    }

    function currentAnalysis() {
        return currentAnalysisById($('sp-analysis') ? $('sp-analysis').value : '');
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
                renderAnswer(d.answer || '', a ? a.title : T('sap.free_question_short', 'Freie Frage'), d);
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
    function renderAnswer(text, title, meta) {
        _lastAnswer = text;
        var html;
        if (window.JarvisChatLib && window.JarvisChatLib.renderMarkdown) {
            html = window.JarvisChatLib.renderMarkdown(text);
        } else {
            html = '<pre>' + esc(text) + '</pre>';
        }
        // MIT WELCHEM ZUGANG gelesen wurde, steht ueber dem Ergebnis – nicht im
        // Antworttext (der wird kopiert und weitergegeben). Faellt der Lauf auf
        // den Sammelzugang zurueck, sind die Zahlen mit fremden, in der Regel
        // weiteren SAP-Berechtigungen geholt; das darf nicht unbemerkt bleiben.
        if (meta && meta.quelle) {
            var eigen = (meta.quelle === 'persoenlich');
            var kopf = eigen ? T('sap.res_own', 'Gelesen mit deinem persönlichen SAP-Zugang.')
                             : T('sap.res_shared', 'Gelesen mit dem gemeinsamen Lesezugang.');
            html = '<div class="sp-acc-note' + (meta.hinweis ? ' is-on' : '')
                + '" style="' + (meta.hinweis ? '' : 'display:block;border-color:var(--border);') + '">'
                + esc(kopf) + (meta.hinweis ? ' ' + esc(meta.hinweis) : '') + '</div>' + html;
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
                // Der Verlauf liegt im Browser und ueberlebt das Ausblenden
                // einer Vorlage durch den Administrator. Ohne diese Pruefung
                // faende `value = id` keine Option, das Feld spraenge
                // wortlos auf "freie Frage" und der Anwender saehe nur, dass
                // "nichts passiert".
                var gone = !!it.id && !currentAnalysisById(it.id);
                if ($('sp-analysis')) $('sp-analysis').value = gone ? '' : (it.id || '');
                if ($('sp-question')) $('sp-question').value = it.q || '';
                if (it.tool && $('sp-bitool')) $('sp-bitool').value = it.tool;
                applyDesc();
                markMatchingEndpoint();
                $('sp-hist-panel').classList.add('hidden');
                if (gone) {
                    note(T('sap.hidden_by_admin',
                        'Diese Analyse wurde vom Administrator ausgeblendet.'), 'error');
                    return;
                }
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

    // ── Mein SAP-Zugang (persoenliche Zugangsdaten) ─────────────────
    // Seit 2026-08-17: ein hinterlegter eigener Zugang hat VORRANG, der in den
    // Einstellungen gepflegte Zugang ist der gemeinsame Lesezugang (Rueckfall).
    // Kennwoerter kommen nie zurueck – der Server liefert nur `*_gesetzt`, und
    // ein leeres Feld heisst beim Speichern "unveraendert".
    var _account = null;

    function accNote(msg, kind) {
        var el = $('sp-acc-status'); if (!el) return;
        el.textContent = msg || '';
        el.className = 'sp-note' + (kind === 'error' ? ' is-error' : kind === 'ok' ? ' is-ok' : '');
    }

    function accApplyType(t) {
        ['odata', 'hana', 'rfc'].forEach(function (k) {
            var g = $('sp-acc-g-' + k);
            if (!g) return;
            var an = (k === t);
            g.classList.toggle('is-on', an);
            g.hidden = !an;
        });
        accApplyAuth();
    }

    // Benutzer/Kennwort ODER Token – nie beides. Sonst fuellt jemand das Feld,
    // das seine Anmeldeart gar nicht benutzt, und sucht den Fehler beim Server.
    function accApplyAuth() {
        var art = $('sp-acc-od-auth') ? $('sp-acc-od-auth').value : 'basic';
        var b = $('sp-acc-od-basic'), t = $('sp-acc-od-bearer');
        if (b) b.hidden = (art === 'bearer');
        if (t) t.hidden = (art !== 'bearer');
    }

    // Pille + Hinweiskasten. Die Aussage steckt in Farbe UND Text – Farbe allein
    // ist keine Information.
    function accRenderState() {
        var pill = $('sp-acc-pill');
        var note = $('sp-acc-note');
        var quelle = (_status && _status.quelle) || 'sammel';
        var hinweis = (_status && _status.hinweis) || '';
        if (pill) {
            if (quelle === 'persoenlich') {
                pill.className = 'sp-acc-pill is-own';
                pill.textContent = T('sap.acc_pill_own', 'eigener Zugang');
            } else if (hinweis) {
                pill.className = 'sp-acc-pill is-warn';
                pill.textContent = T('sap.acc_pill_fallback', 'gemeinsamer Lesezugang (Rückfall)');
            } else {
                pill.className = 'sp-acc-pill';
                pill.textContent = T('sap.acc_pill_shared', 'gemeinsamer Lesezugang');
            }
        }
        if (note) {
            note.textContent = hinweis;
            note.classList.toggle('is-on', !!hinweis);
        }
    }

    function accRenderHosts() {
        var el = $('sp-acc-hosts'); if (!el || !_account) return;
        var hosts = _account.erlaubte_hosts || [];
        if (!hosts.length) {
            el.textContent = T('sap.acc_hosts_none',
                'Es ist kein Server freigegeben – ein eigener Zugang ist derzeit nicht möglich. '
                + 'Ein Administrator gibt Server unter Einstellungen → SAP frei.');
            return;
        }
        el.textContent = T('sap.acc_hosts', 'Freigegebene Server:') + ' ' + hosts.join(', ');
    }

    // ── Serverzertifikat pruefen/verankern ──────────────────────────────
    // Derselbe Baustein wie im Einstellungs-Reiter (js/sapcert.js), nur gegen
    // die Benutzer-Endpunkte. Warum der Benutzer das darf, obwohl er die
    // Pruefung nicht ABschalten darf: Verankern ist strenger, nicht schwaecher –
    // und ohne diesen Weg haette ein eigener Server mit selbst ausgestelltem
    // Zertifikat ueberhaupt keine Loesung.
    var _certBoxen = {};

    function accMountCert() {
        if (!window.SapCert) return;
        [['odata', 'sp-cert-odata'], ['hana', 'sp-cert-hana']].forEach(function (p) {
            var kanal = p[0], box = $(p[1]);
            if (!box) return;
            if (!_certBoxen[kanal]) {
                _certBoxen[kanal] = window.SapCert.mount(box, {
                    basis: '/api/sap/cert',
                    kanal: kanal,
                    ziel: function () {
                        var v = function (id) { var e = $(id); return e ? e.value.trim() : ''; };
                        return kanal === 'hana'
                            ? { host: v('sp-acc-hana-host'), port: v('sp-acc-hana-port') || 443 }
                            : { url: v('sp-acc-od-url') };
                    },
                    gebunden: function () {
                        return ((_account && _account.cert && _account.cert[kanal]) || {}).eigen || {};
                    },
                    fremd: function () {
                        return ((_account && _account.cert && _account.cert[kanal]) || {}).admin || {};
                    },
                    nachAenderung: function (d) {
                        if (d && d.account) _account = d.account;
                        loadStatus();   // die Pille folgt der geaenderten Lage
                    }
                });
            } else {
                _certBoxen[kanal].refresh();
            }
        });
    }

    function loadAccount() {
        fetch('/api/sap/account', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok || !d.account) return;
                var a = _account = d.account;
                if ($('sp-acc-type')) $('sp-acc-type').value = a.connection_type || '';
                if ($('sp-acc-aktiv')) $('sp-acc-aktiv').checked = a.aktiv !== false;
                // OData
                if ($('sp-acc-od-url')) $('sp-acc-od-url').value = a.odata_base_url || '';
                if ($('sp-acc-od-service')) $('sp-acc-od-service').value = a.odata_service || '';
                if ($('sp-acc-od-auth')) $('sp-acc-od-auth').value = a.auth_kind || 'basic';
                if ($('sp-acc-od-client')) $('sp-acc-od-client').value = a.sap_client || '';
                if ($('sp-acc-od-user')) $('sp-acc-od-user').value = a.username || '';
                // HANA
                if ($('sp-acc-hana-host')) $('sp-acc-hana-host').value = a.hana_host || '';
                if ($('sp-acc-hana-port')) $('sp-acc-hana-port').value = a.hana_port || 443;
                if ($('sp-acc-hana-user')) $('sp-acc-hana-user').value = a.hana_user || '';
                if ($('sp-acc-hana-schema')) $('sp-acc-hana-schema').value = a.hana_schema || '';
                // RFC
                if ($('sp-acc-rfc-host')) $('sp-acc-rfc-host').value = a.rfc_ashost || '';
                if ($('sp-acc-rfc-sysnr')) $('sp-acc-rfc-sysnr').value = a.rfc_sysnr || '';
                if ($('sp-acc-rfc-client')) $('sp-acc-rfc-client').value = a.rfc_client || '';
                if ($('sp-acc-rfc-lang')) $('sp-acc-rfc-lang').value = a.rfc_lang || '';
                if ($('sp-acc-rfc-user')) $('sp-acc-rfc-user').value = a.rfc_user || '';
                // Kennwortfelder bleiben LEER (der Server gibt sie nie heraus);
                // der Platzhalter sagt, dass leer "unveraendert" bedeutet.
                accApplyType(a.connection_type || '');
                accRenderHosts();
                accRenderState();
                accMountCert();
                if (a.ausgesetzt) {
                    accNote(T('sap.acc_suspended', 'Ausgesetzt nach fehlgeschlagenen Anmeldungen – '
                        + 'Kennwort prüfen und „Verbindung testen" drücken.'), 'error');
                } else if (a.letzter_fehler) {
                    accNote(a.letzter_fehler, 'error');
                }
            })
            .catch(function () {});
    }

    function accCollect() {
        var t = $('sp-acc-type') ? $('sp-acc-type').value : '';
        var v = function (id) { var e = $(id); return e ? e.value.trim() : ''; };
        var raw = function (id) { var e = $(id); return e ? e.value : ''; };
        // Es werden immer alle Felder gesendet: der Server hat die Whitelist, und
        // ein Kanalwechsel soll die alten Werte nicht heimlich stehen lassen.
        return {
            connection_type: t,
            aktiv: $('sp-acc-aktiv') ? $('sp-acc-aktiv').checked : true,
            odata_base_url: v('sp-acc-od-url'),
            odata_service: v('sp-acc-od-service'),
            auth_kind: ($('sp-acc-od-auth') ? $('sp-acc-od-auth').value : 'basic'),
            sap_client: v('sp-acc-od-client'),
            username: v('sp-acc-od-user'),
            password: raw('sp-acc-od-pass'),
            bearer_token: raw('sp-acc-od-token'),
            hana_host: v('sp-acc-hana-host'),
            hana_port: Number(v('sp-acc-hana-port') || 443),
            hana_user: v('sp-acc-hana-user'),
            hana_password: raw('sp-acc-hana-pass'),
            hana_schema: v('sp-acc-hana-schema'),
            rfc_ashost: v('sp-acc-rfc-host'),
            rfc_sysnr: v('sp-acc-rfc-sysnr'),
            rfc_client: v('sp-acc-rfc-client'),
            rfc_user: v('sp-acc-rfc-user'),
            rfc_password: raw('sp-acc-rfc-pass'),
            rfc_lang: v('sp-acc-rfc-lang')
        };
    }

    function accClearSecrets() {
        ['sp-acc-od-pass', 'sp-acc-od-token', 'sp-acc-hana-pass', 'sp-acc-rfc-pass']
            .forEach(function (id) { var e = $(id); if (e) e.value = ''; });
    }

    function saveAccount() {
        var t = $('sp-acc-type') ? $('sp-acc-type').value : '';
        if (!t) {
            // Kein leerer Datensatz: sonst laegen Kennwoerter gespeichert da, die
            // nie benutzt werden. Wer keinen eigenen Zugang will, entfernt ihn.
            accNote(T('sap.acc_need_type',
                'Bitte eine Zugangsart wählen – oder „Eigenen Zugang entfernen" drücken.'), 'error');
            return;
        }
        accNote(T('sap.acc_saving', 'Speichere…'));
        fetch('/api/sap/account', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(accCollect())
        })
            .then(function (r) {
                return r.json().catch(function () { return null; }).then(function (d) {
                    return { ok: r.ok, d: d };
                });
            })
            .then(function (res) {
                if (!res.ok || !res.d || !res.d.ok) {
                    accNote((res.d && res.d.error) || T('sap.acc_save_failed', 'Speichern fehlgeschlagen.'), 'error');
                    return;
                }
                accClearSecrets();
                accNote('✓ ' + T('sap.acc_saved', 'Gespeichert.'), 'ok');
                loadAccount();
                loadStatus();      // Pille und Verbindungsanzeige folgen sofort
            })
            .catch(function () {
                accNote(T('sap.acc_save_failed', 'Speichern fehlgeschlagen.'), 'error');
            });
    }

    function testAccount() {
        accNote(T('sap.acc_testing', 'Teste Verbindung…'));
        fetch('/api/sap/test', { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.ok) {
                    var q = (d.quelle === 'persoenlich')
                        ? T('sap.acc_pill_own', 'eigener Zugang')
                        : T('sap.acc_pill_shared', 'gemeinsamer Lesezugang');
                    accNote('✅ ' + q + ' – ' + (d.detail || 'OK'), 'ok');
                } else if (d && d.configured === false) {
                    accNote(T('sap.acc_not_configured', 'Kein Zugang konfiguriert.'), 'error');
                } else {
                    accNote('❌ ' + ((d && d.error) || T('sap.failed', 'Fehlgeschlagen.')), 'error');
                }
                loadAccount();
                loadStatus();
            })
            .catch(function () { accNote('❌ ' + T('sap.failed', 'Fehlgeschlagen.'), 'error'); });
    }

    function delAccount() {
        if (!window.confirm(T('sap.acc_del_confirm',
            'Eigenen SAP-Zugang entfernen? Danach laufen Auswertungen wieder über den '
            + 'gemeinsamen Lesezugang.'))) return;
        fetch('/api/sap/account', { method: 'DELETE', headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function () {
                accClearSecrets();
                if ($('sp-acc-type')) $('sp-acc-type').value = '';
                accApplyType('');
                accNote(T('sap.acc_removed', 'Eigener Zugang entfernt.'), 'ok');
                loadAccount();
                loadStatus();
            })
            .catch(function () { accNote('❌ ' + T('sap.failed', 'Fehlgeschlagen.'), 'error'); });
    }

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

        var accT = $('sp-acc-type');
        if (accT) accT.addEventListener('change', function () { accApplyType(accT.value); accNote(''); });
        var accA = $('sp-acc-od-auth');
        if (accA) accA.addEventListener('change', accApplyAuth);
        var accS = $('sp-acc-save'); if (accS) accS.addEventListener('click', saveAccount);
        var accP = $('sp-acc-test'); if (accP) accP.addEventListener('click', testAccount);
        var accD = $('sp-acc-del'); if (accD) accD.addEventListener('click', delAccount);

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
