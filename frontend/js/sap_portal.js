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
    var TOKEN_KEYS = window.JarvisSitzung.tokenSchluessel();
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
    // Loescht GENAU EINEN Eintrag. Der Index stammt aus dem GEZEICHNETEN Stand;
    // ein zweiter Tab kann den Verlauf inzwischen verschoben haben, deshalb
    // entscheidet der Zeitstempel und der Index ist nur der schnelle Weg.
    // Ohne diese Pruefung loeschte ein Klick den falschen Eintrag.
    function deleteHistory(i, ts) {
        var list = readHistory();
        if (!(list[i] && list[i].ts === ts)) {
            i = -1;
            for (var k = 0; k < list.length; k++) { if (list[k].ts === ts) { i = k; break; } }
        }
        if (i < 0) { renderHistory(); return; }
        list.splice(i, 1);
        try { localStorage.setItem(HIST_KEY, JSON.stringify(list)); } catch (e) {}
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
        var delLbl = esc(T('sup.hist_del', 'Eintrag löschen'));
        box.innerHTML = list.map(function (it, i) {
            var label = it.title || it.q || T('sap.free_question_short', 'Freie Frage');
            var when = new Date(it.ts).toLocaleString();
            var sub = (it.title && it.q) ? (it.q + ' · ' + when) : when;
            // Text in einem eigenen Kind (min-width:0), sonst greift das
            // Ellipsis der langen Zeile im Flex-Container nicht mehr.
            // MUELLEIMER, kein x: der Eintrag wird dauerhaft entfernt.
            return '<div class="sp-hist-item" data-i="' + i + '">'
                + '<div class="sp-hist-text">'
                + '<div class="sp-hist-q">' + esc(label) + '</div>'
                + '<div class="sp-hist-meta">' + esc(sub) + '</div></div>'
                + '<button type="button" class="sp-hist-del" data-i="' + i + '"'
                + ' data-ts="' + (it.ts || 0) + '" title="' + delLbl + '"'
                + ' aria-label="' + delLbl + '">' + window.JarvisIcons.trash() + '</button>'
                + '</div>';
        }).join('');
        Array.prototype.forEach.call(box.querySelectorAll('.sp-hist-del'), function (b) {
            b.addEventListener('click', function (e) {
                // stopPropagation ist hier PFLICHT, und zwar doppelt: ohne sie
                // uebernaehme der Eintrag darunter die Analyse ins Formular,
                // UND der Dokument-Listener schloesse das Verlaufsfeld – die
                // geloeschte Zeile haengt beim Weiterlaufen des Klicks nicht
                // mehr im Panel, `panel.contains(target)` ist dann falsch.
                e.stopPropagation();
                e.preventDefault();
                deleteHistory(parseInt(b.dataset.i, 10), parseInt(b.dataset.ts, 10));
            });
        });
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
    // ── Auswahllisten der OData-Konsole ─────────────────────────────
    // Service-Feld: Katalog des Gateway (einmal je Seite). EntitySet-Feld:
    // EntitySets des eingetragenen Service bzw. des Standard-Service, je
    // Eingabe gemerkt. Geladen wird erst, wenn die OData-Konsole sichtbar ist –
    // die Seite fragt nicht bei jedem Aufruf den Katalog ab. Die Felder bleiben
    // frei beschreibbar (<datalist>), die Liste ist ein Angebot, keine Schranke.
    var _odSvc = null;        // laufende/erledigte Katalog-Abfrage (Promise)
    var _odSets = {};         // Service-Eingabe -> erfolgreiche Antwort
    var _odSetsFuer = null;   // fuer welche Eingabe die EntitySet-Liste gilt

    function odHint(id, msg, kind) {
        var el = $(id); if (!el) return;
        el.textContent = msg || '';
        el.className = 'sp-note sp-od-hint' + (kind === 'error' ? ' is-error' : '');
    }
    function odFill(listId, items) {
        var dl = $(listId); if (!dl) return;
        while (dl.firstChild) dl.removeChild(dl.firstChild);
        items.forEach(function (it) {
            var o = document.createElement('option');
            o.value = it.value;
            if (it.label) o.setAttribute('label', it.label);
            dl.appendChild(o);
        });
    }
    function odSichtbar() {
        var sect = $('sp-sect-console'), pane = $('sp-pane-odata');
        return !!(sect && sect.open && pane && !pane.classList.contains('hidden'));
    }
    function odServiceKey() {
        return (($('sp-od-service') || {}).value || '').trim().replace(/^\/+|\/+$/g, '');
    }

    function odLadeServices() {
        if (_odSvc) return _odSvc;
        odHint('sp-od-svc-hint', T('sap.od_svc_loading', 'Lade Service-Liste…'));
        _odSvc = fetch('/api/sap/odata/services', { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) {
                    // Kein Katalog ist ein Dauerzustand – sonst beim naechsten
                    // Klick ins Feld neu versuchen (ein Klick = eine Anfrage).
                    if (!(d && d.kein_katalog)) _odSvc = null;
                    odHint('sp-od-svc-hint', (d && d.kein_katalog)
                        ? T('sap.od_svc_nocatalog', 'Dieser Server hat keinen Gateway-Katalog – den Service bitte von Hand eintragen.')
                        : T('sap.od_svc_failed', 'Service-Liste nicht abrufbar:') + ' ' + ((d && d.error) || ''), 'error');
                    return;
                }
                var liste = Array.isArray(d.services) ? d.services : [];
                odFill('sp-od-service-list', liste.map(function (x) {
                    return { value: x.service, label: x.title };
                }));
                var msg = (d.genau ? T('sap.od_svc_count', '{n} Services im Katalog – zur Auswahl ins Feld klicken oder tippen.')
                                   : T('sap.od_svc_count_min', 'Mindestens {n} Services im Katalog – zur Auswahl ins Feld klicken oder tippen.'))
                    .replace('{n}', liste.length);
                if (d.ausgelassen) {
                    msg += ' ' + T('sap.od_svc_skipped', '({n} weitere liegen nicht unter der Basis-URL und fehlen in der Liste.)')
                        .replace('{n}', d.ausgelassen);
                }
                odHint('sp-od-svc-hint', msg);
            })
            .catch(function () {
                _odSvc = null;
                odHint('sp-od-svc-hint', T('sap.od_svc_failed', 'Service-Liste nicht abrufbar:'), 'error');
            });
        return _odSvc;
    }

    function odZeigeSets(d) {
        if (!d.ok) {
            _odSetsFuer = null;   // beim naechsten Klick ins Feld neu fragen
            odFill('sp-od-entity-list', []);
            if (d.kein_service) {
                odHint('sp-od-entity-hint', T('sap.od_sets_noservice',
                    'Für die Liste zuerst einen Service eintragen – oder unter „Mein SAP-Zugang“ einen Standard-Service hinterlegen.'));
            } else {
                odHint('sp-od-entity-hint', T('sap.od_sets_failed', 'EntitySet-Liste nicht abrufbar:') + ' '
                    + (d.error || ''), 'error');
            }
            return;
        }
        var sets = Array.isArray(d.entity_sets) ? d.entity_sets : [];
        odFill('sp-od-entity-list', sets.map(function (n) { return { value: n }; }));
        odHint('sp-od-entity-hint', T('sap.od_sets_count', '{n} EntitySets in „{s}“ – zur Auswahl ins Feld klicken oder tippen.')
            .replace('{n}', sets.length).replace('{s}', d.service || ''));
    }

    function odLadeSets() {
        var key = odServiceKey();
        if (_odSetsFuer === key) return;            // gilt schon bzw. wird gerade geladen
        _odSetsFuer = key;
        if (_odSets[key]) { odZeigeSets(_odSets[key]); return; }
        odFill('sp-od-entity-list', []);
        odHint('sp-od-entity-hint', T('sap.od_sets_loading', 'Lade EntitySets…'));
        fetch('/api/sap/odata/entity-sets?service=' + encodeURIComponent(key), { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                d = d || {};
                if (d.ok) _odSets[key] = d;          // nur Erfolge merken
                // Inzwischen ein anderer Service eingetragen: diese Antwort
                // ist veraltet und darf die neue Liste nicht ueberschreiben.
                if (_odSetsFuer !== key) return;
                odZeigeSets(d);
            })
            .catch(function () {
                if (_odSetsFuer !== key) return;
                _odSetsFuer = null;
                odHint('sp-od-entity-hint', T('sap.od_sets_failed', 'EntitySet-Liste nicht abrufbar:'), 'error');
            });
    }

    function odListenLaden() {
        if (!odSichtbar()) return;
        odLadeServices();
        odLadeSets();
    }

    function switchPane(name) {
        ['odata', 'sql'].forEach(function (p) {
            var tab = $('sp-tab-' + p), pane = $('sp-pane-' + p);
            if (tab) tab.classList.toggle('active', p === name);
            if (pane) pane.classList.toggle('hidden', p !== name);
        });
        var out = $('sp-console-out'); if (out) out.innerHTML = '';
        if (name === 'odata') odListenLaden();
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
                    // Der GRUND gehoert dazu (Vorfall 2026-08-25): ohne ihn stand
                    // hier nur "Kennwort pruefen", waehrend der Zugang in Wahrheit
                    // an einer fehlenden BERECHTIGUNG gescheitert war – der Satz
                    // schickte den Benutzer an die falsche Stelle, und den
                    // tatsaechlichen Fehler bekam er nirgends zu sehen.
                    var grund = a.ausgesetzt_grund || a.letzter_fehler || '';
                    accNote(T('sap.acc_suspended', 'Ausgesetzt nach fehlgeschlagenen Anmeldungen – '
                        + 'Kennwort prüfen und „Verbindung testen" drücken.')
                        + (grund ? ' ' + T('sap.acc_last_error', 'Letzter Fehler:') + ' ' + grund : ''),
                        'error');
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
                accResetTestInfo();
                accNote('✓ ' + T('sap.acc_saved', 'Gespeichert.'), 'ok');
                loadAccount();
                loadStatus();      // Pille und Verbindungsanzeige folgen sofort
            })
            .catch(function () {
                accNote(T('sap.acc_save_failed', 'Speichern fehlgeschlagen.'), 'error');
            });
    }

    // ── Bericht zum Verbindungstest ─────────────────────────────────
    // Fuer den SAP-Administrator: WAS geprueft wurde (Gateway-Katalog oder
    // Metadaten eines Service), gegen welche Adresse, mit welchem Benutzer und
    // Mandanten, mit welchem HTTP-Status. Steht auch im FEHLERFALL da – genau
    // dann wird nachgefragt. Kennwort und Token liefert der Server nie mit.
    var _letzterTest = null;   // {d, zeit}

    function tiVariante(v) {
        switch (v) {
            case 'service':
                return T('sap.ti_v_service', 'Abgerufen wurde die Beschreibung ($metadata) des Standard-Service. '
                    + 'Gezählt sind die darin definierten EntitySets (Datenmengen) – keine Datensätze, '
                    + 'und keine Aussage darüber, welche davon dieser Benutzer lesen darf.');
            case 'katalog':
                return T('sap.ti_v_catalog', 'Kein Standard-Service eingetragen – abgerufen wurde deshalb der '
                    + 'Service-Katalog des SAP Gateway (/IWFND/CATALOGSERVICE). Das belegt Erreichbarkeit, '
                    + 'Anmeldung und das Recht, den Katalog aufzurufen. Für einen Test gegen einen bestimmten '
                    + 'Service dessen Namen unter „Standard-Service“ eintragen.');
            case 'katalog_fehlt':
                return T('sap.ti_v_nocatalog', 'Der Server antwortet, hat aber keinen Gateway-Katalog (HTTP 404, '
                    + 'z. B. bei S/4HANA Cloud). Bitte unter „Standard-Service“ einen Service eintragen.');
            case 'hana':
                return T('sap.ti_v_hana', 'Angemeldet an der HANA-Datenbank und Benutzer sowie Datenbankname abgefragt.');
            case 'rfc':
                return T('sap.ti_v_rfc', 'Erreichbarkeit und Anmeldung per RFCPING geprüft.');
        }
        return '';
    }

    function tiAnmeldeart(a) {
        if (a === 'basic') return T('sap.ti_auth_basic', 'Benutzer und Kennwort (Basic)');
        if (a === 'bearer') return T('sap.ti_auth_bearer', 'Token (Bearer)');
        return T('sap.ti_auth_none', 'keine – es wurden keine Anmeldedaten gesendet');
    }

    // [Beschriftung, Wert] – EINE Quelle fuer Anzeige UND kopierten Bericht,
    // sonst steht im Bericht etwas anderes als auf dem Bildschirm.
    function tiZeilen(d) {
        var i = (d && d.info) || {}, z = [];
        var odata = (i.variante === 'service' || i.variante === 'katalog' || i.variante === 'katalog_fehlt');
        function add(k, fb, v) {
            if (v === undefined || v === null || v === '') return;
            z.push([T(k, fb), String(v)]);
        }
        add('sap.ti_address', 'Aufgerufene Adresse', i.adresse);
        if (odata && i.basis && !i.adresse) add('sap.ti_base', 'Basis-URL', i.basis);
        if (odata) add('sap.ti_service', 'Standard-Service', i.service || T('sap.ti_none', '— keiner —'));
        if (odata || i.variante === 'rfc') {
            add('sap.ti_mandant', 'Mandant', i.mandant
                || T('sap.ti_mandant_default', '— nicht angegeben, es gilt der Standardmandant des Servers —'));
        }
        if (i.variante === 'rfc') add('sap.ti_sysnr', 'Systemnummer', i.systemnummer);
        add('sap.ti_user', 'SAP-Benutzer', i.benutzer);
        if (odata) add('sap.ti_auth', 'Anmeldeart', tiAnmeldeart(i.anmeldeart));
        if (i.variante === 'hana') {
            add('sap.ti_schema', 'Schema', i.schema);
            add('sap.ti_encrypt', 'Verschlüsselt', i.verschluesselt ? T('sap.ti_yes', 'ja') : T('sap.ti_no', 'nein'));
        }
        if (i.http_status !== undefined && i.http_status !== null) {
            add('sap.ti_http', 'HTTP-Status', i.http_status === 0
                ? T('sap.ti_http_none', 'keine Antwort (Netzwerk, Zertifikat oder Zeitüberschreitung)')
                : i.http_status);
        }
        if (typeof i.dauer_ms === 'number') add('sap.ti_time', 'Antwortzeit', i.dauer_ms + ' ms');
        if (typeof i.anzahl_services === 'number') {
            add('sap.ti_services', 'Services im Katalog', i.anzahl_genau
                ? i.anzahl_services
                : T('sap.ti_at_least', 'mindestens') + ' ' + i.anzahl_services);
        }
        if (Array.isArray(i.entity_sets)) add('sap.ti_sets', 'EntitySets im Service', i.entity_sets.length);
        return z;
    }

    function tiFuss() {
        return T('sap.ti_foot', 'Es wurden keine Geschäftsdaten gelesen. Ob die Berechtigungen für die '
            + 'Daten selbst ausreichen, zeigt erst eine Auswertung.');
    }

    function tiErgebnis(d) {
        var q = (d.quelle === 'persoenlich')
            ? T('sap.acc_pill_own', 'eigener Zugang')
            : T('sap.acc_pill_shared', 'gemeinsamer Lesezugang');
        return (d.ok ? T('sap.ti_ok', 'erfolgreich') : T('sap.ti_failed', 'fehlgeschlagen'))
            + ' (' + q + ') – ' + (d.ok ? (d.detail || 'OK') : (d.error || ''));
    }

    function tiText() {
        if (!_letzterTest) return '';
        var d = _letzterTest.d, i = d.info || {};
        var zeilen = [T('sap.ti_title', 'SAP-Verbindungstest') + ' – ' + _letzterTest.zeit,
            T('sap.ti_result', 'Ergebnis') + ': ' + tiErgebnis(d), '', tiVariante(i.variante), ''];
        tiZeilen(d).forEach(function (z) { zeilen.push(z[0] + ': ' + z[1]); });
        if (Array.isArray(i.entity_sets) && i.entity_sets.length) {
            zeilen.push('', T('sap.ti_sets', 'EntitySets im Service') + ':');
            i.entity_sets.forEach(function (n) { zeilen.push('  ' + n); });
        }
        zeilen.push('', tiFuss());
        return zeilen.join('\n');
    }

    function accRenderTestInfo() {
        var box = $('sp-acc-testinfo'); if (!box) return;
        var d = _letzterTest && _letzterTest.d;
        if (!d || !d.info) { box.hidden = true; box.innerHTML = ''; return; }
        var i = d.info, html = '';
        var v = tiVariante(i.variante);
        if (v) html += '<p class="sp-ti-head">' + esc(v) + '</p>';
        html += '<dl class="sp-ti-grid">';
        tiZeilen(d).forEach(function (z) {
            html += '<dt>' + esc(z[0]) + '</dt><dd>' + esc(z[1]) + '</dd>';
        });
        html += '</dl>';
        if (Array.isArray(i.entity_sets) && i.entity_sets.length) {
            html += '<details class="sp-ti-sets"><summary>'
                + esc(T('sap.ti_sets_show', 'EntitySets anzeigen') + ' (' + i.entity_sets.length + ')')
                + '</summary><ul>' + i.entity_sets.map(function (n) {
                    return '<li>' + esc(n) + '</li>';
                }).join('') + '</ul></details>';
        }
        html += '<p class="sp-ti-foot">' + esc(tiFuss()) + '</p>'
            + '<div class="sp-actions"><button class="sp-hist-btn" id="sp-acc-ti-copy" type="button">'
            + esc(T('sap.ti_copy', 'Bericht für den SAP-Administrator kopieren')) + '</button>'
            + '<span class="sp-note" id="sp-acc-ti-note"></span></div>';
        box.innerHTML = html;
        box.classList.toggle('is-error', !d.ok);
        box.hidden = false;
        var btn = $('sp-acc-ti-copy');
        if (btn) btn.addEventListener('click', function () {
            var txt = tiText();
            var fertig = function () {
                var n = $('sp-acc-ti-note');
                if (n) { n.textContent = T('sap.copied', 'In die Zwischenablage kopiert.'); n.className = 'sp-note is-ok'; }
            };
            if (window.JarvisChatLib && window.JarvisChatLib.copyTextToClipboard) {
                window.JarvisChatLib.copyTextToClipboard(txt).then(fertig);
            } else if (navigator.clipboard) {
                navigator.clipboard.writeText(txt).then(fertig);
            }
        });
    }

    function accResetTestInfo() {
        _letzterTest = null;
        accRenderTestInfo();
    }

    function testAccount() {
        accNote(T('sap.acc_testing', 'Teste Verbindung…'));
        accResetTestInfo();
        fetch('/api/sap/test', { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.info) {
                    _letzterTest = { d: d, zeit: new Date().toLocaleString(lang() === 'en' ? 'en-GB' : 'de-DE') };
                    accRenderTestInfo();
                }
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
                accResetTestInfo();
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
        // Der Bericht wird aus T() gebaut – nach einem Sprachwechsel neu zeichnen.
        // accRenderTestInfo ruft kein applyLang(), loest also kein Ereignis aus.
        window.addEventListener('jarvis-lang-changed', function () {
            if (_letzterTest) accRenderTestInfo();
        });
        var accD = $('sp-acc-del'); if (accD) accD.addEventListener('click', delAccount);

        $('sp-instr-btn').addEventListener('click', openInstructions);
        $('sp-instr-close').addEventListener('click', function () { $('sp-instr-overlay').classList.add('hidden'); });
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
        var con = $('sp-sect-console');
        if (con) con.addEventListener('toggle', odListenLaden);
        $('sp-od-service').addEventListener('focus', odLadeServices);
        $('sp-od-service').addEventListener('change', odLadeSets);
        $('sp-od-entity').addEventListener('focus', odLadeSets);
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
