/* ═══════════════════════════════════════════════════════════════════
   VEMAS-Bereich (/vemas)
   ───────────────────────────────────────────────────────────────────
   Vorgefertigte Auswertungen, freie Frage, persoenliche Zugangsdaten und
   eine Abfrage-Konsole ohne KI. Aufbau bewusst 1:1 wie js/sap_portal.js –
   wer zwischen den Bereichen wechselt, soll dieselben Knoepfe an
   derselben Stelle finden.

   Praefix `vm-` fuer alle Elemente dieser Seite; `vemas-` gehoert dem
   Einstellungs-Reiter (js/vemas.js).
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // Dieselben Token-Schluessel wie in den uebrigen Bereichen: wer sich in
    // /chat angemeldet hat, soll hier nicht erneut anmelden muessen.
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    var HIST_KEY = 'jarvis_vemas_history';
    var HIST_MAX = 25;
    var PREF_TOOL = 'jarvis_vemas_tool';
    var PREF_ANALYSIS = 'jarvis_vemas_analysis';

    function $(id) { return document.getElementById(id); }
    function T(key, fallback) {
        return (window.t ? window.t(key) : null) || fallback;
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
        return (localStorage.getItem('jarvis_lang') === 'en') ? 'en' : 'de';
    }
    function toPortal() { window.location.replace('/portal'); }

    var _catalog = null;     // {categories, analyses, tools}
    var _status = null;      // /api/vemas/status
    var _account = null;     // /api/vemas/account
    var _abort = null;       // laufende Auswertung (fetch-Abbruch)

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
                // freigegeben" – lieber zurueck aufs Portal als eine Seite, auf
                // der jeder Knopf 403 liefert.
                if (!(me.permissions && me.permissions.vemas)) { toPortal(); return; }
                showApp();
            })
            .catch(function () { toPortal(); });
    }

    function showApp() {
        $('vm-app').classList.remove('hidden');
        bind();
        loadStatus();
        loadCatalog();
        loadAccount();
        loadResources();
        loadEndpoints();
        renderHistory();
        startLlmStatus();
        if (window.refreshBranding) { try { window.refreshBranding(); } catch (e) {} }
    }

    // ── LLM-Punkt (gleiches Muster wie /sap, alle 30 s) ─────────────
    var _llmTimer = null;
    function checkLlm() {
        var dot = $('vm-status-dot'); if (!dot) return;
        fetch('/api/llm/active-status', { headers: authHeaders() })
            .then(function (r) { if (!r.ok) throw new Error('http'); return r.json(); })
            .then(function (d) {
                var ok = (d.status === 'ok' || d.status === 'degraded');
                dot.className = 'vm-status-dot ' + (ok ? 'connected' : 'disconnected');
                dot.title = (d.status === 'ok' ? T('sup.llm_ok', 'LLM erreichbar')
                    : d.status === 'degraded' ? T('sup.llm_degraded', 'LLM erreichbar (Modell fehlt)')
                    : T('sup.llm_down', 'LLM nicht erreichbar')) + (d.profile_name ? ' – ' + d.profile_name : '');
            })
            .catch(function () {
                dot.className = 'vm-status-dot disconnected';
                dot.title = T('sup.llm_down', 'LLM nicht erreichbar');
            });
    }
    function startLlmStatus() { checkLlm(); if (!_llmTimer) _llmTimer = setInterval(checkLlm, 30000); }

    // ── Verbindungszustand ──────────────────────────────────────────
    function loadStatus() {
        fetch('/api/vemas/status', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _status = d;
                var el = $('vm-conn'); if (!el) return;
                if (!d) { el.textContent = ''; return; }
                accRenderState();
                if (!d.configured) {
                    el.className = 'vm-conn is-off';
                    el.textContent = T('vemas.not_configured', 'VEMAS nicht konfiguriert');
                    el.title = T('vemas.not_configured_hint',
                        'Ein Administrator hinterlegt Serveradresse und Zugang unter Einstellungen → Vemas.');
                    note(T('vemas.not_configured_hint',
                        'Ein Administrator hinterlegt Serveradresse und Zugang unter Einstellungen → Vemas.'), 'error');
                    return;
                }
                el.className = 'vm-conn';
                // Nur-Lesen gehoert in die Pille: es ist der Unterschied
                // zwischen "der Agent darf etwas anlegen" und "er darf es
                // nicht", und niemand kann das sonst irgendwo ablesen.
                el.textContent = (d.product ? d.product + ' · ' : '')
                    + (d.read_only ? T('vemas.pill_ro', 'nur lesend')
                                   : T('vemas.pill_rw', 'lesen und schreiben'));
                el.title = (d.server || '') + ' · '
                    + T('vemas.resources_n', 'hinterlegte Ressourcen:') + ' ' + (d.resources || 0);
                if (!d.resources) {
                    // Ohne Ressourcen-Zuordnung muss der Agent Pfade raten –
                    // das ist der haeufigste Grund fuer leere Ergebnisse und
                    // von aussen nicht erkennbar.
                    note(T('vemas.no_resources',
                        'Es sind keine Ressourcen hinterlegt – Auswertungen finden dann möglicherweise nichts. '
                        + 'Ein Administrator trägt sie unter Einstellungen → Vemas ein.'), 'warn');
                }
            })
            .catch(function () {});
    }

    // ── Katalog: Abfragen + Zielwerkzeuge ───────────────────────────
    function loadCatalog() {
        fetch('/api/vemas/analyses?lang=' + encodeURIComponent(lang()), { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                _catalog = d;
                fillAnalyses();
                fillTools();
                applyDesc();
            })
            .catch(function () {});
    }

    function fillAnalyses() {
        var sel = $('vm-analysis'); if (!sel || !_catalog) return;
        var vorher = localStorage.getItem(PREF_ANALYSIS) || '';
        sel.innerHTML = '';
        var leer = document.createElement('option');
        leer.value = '';
        leer.textContent = T('vemas.free_question', '— Freie Frage (keine Vorlage) —');
        sel.appendChild(leer);
        (_catalog.categories || []).forEach(function (c) {
            var g = document.createElement('optgroup');
            g.label = c.title;
            (_catalog.analyses || []).forEach(function (a) {
                if (a.cat !== c.id) return;
                var o = document.createElement('option');
                o.value = a.id; o.textContent = a.title;
                g.appendChild(o);
            });
            if (g.children.length) sel.appendChild(g);
        });
        if (vorher) sel.value = vorher;
    }

    function fillTools() {
        var sel = $('vm-tool'); if (!sel || !_catalog) return;
        var vorher = localStorage.getItem(PREF_TOOL) || 'inline';
        sel.innerHTML = '';
        (_catalog.tools || []).forEach(function (b) {
            var o = document.createElement('option');
            o.value = b.id;
            o.textContent = b.name + (b.iface ? ' (' + b.iface + ')' : '');
            sel.appendChild(o);
        });
        if (vorher) sel.value = vorher;
    }

    function currentAnalysis() {
        var id = $('vm-analysis') ? $('vm-analysis').value : '';
        if (!id || !_catalog) return null;
        var hit = null;
        (_catalog.analyses || []).forEach(function (a) { if (a.id === id) hit = a; });
        return hit;
    }

    function applyDesc() {
        var box = $('vm-desc'); if (!box) return;
        var a = currentAnalysis();
        if (!a) { box.classList.add('hidden'); return; }
        box.classList.remove('hidden');
        $('vm-desc-title').textContent = a.title;
        $('vm-desc-text').textContent = a.desc;
        var chips = $('vm-desc-kpis');
        chips.innerHTML = '';
        (a.kpis || []).forEach(function (k) {
            var s = document.createElement('span');
            s.className = 'vm-chip'; s.textContent = k;
            chips.appendChild(s);
        });
        // Die Quellen sind ein HINWEIS, keine Zusicherung – der Text sagt das,
        // sonst haelt der Benutzer eine leere Auswertung fuer einen Fehler.
        $('vm-desc-src').textContent =
            T('vemas.sources', 'Übliche VEMAS-Quellen (Hinweis, nicht garantiert)') + ': ' + a.sources;
    }

    // ── Anbindungs-Hinweise ─────────────────────────────────────────
    function loadEndpoints() {
        fetch('/api/vemas/reporting-endpoints', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                var box = $('vm-bi-list'); if (!box || !d || !d.ok) return;
                box.innerHTML = '';
                (d.endpoints || []).forEach(function (e) {
                    var div = document.createElement('div');
                    div.className = 'vm-ep';
                    var n = document.createElement('div');
                    n.className = 'vm-ep-name'; n.textContent = e.name;
                    var u = document.createElement('div');
                    u.className = 'vm-ep-url'; u.textContent = e.hinweis;
                    div.appendChild(n); div.appendChild(u);
                    box.appendChild(div);
                });
            })
            .catch(function () {});
    }

    // ── Ressourcen (fuer die Konsole als Vorschlagsliste) ───────────
    function loadResources() {
        fetch('/api/vemas/resources', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                var dl = $('vm-res-list'); if (!dl || !d || !d.ok) return;
                dl.innerHTML = '';
                (d.resources || []).forEach(function (r2) {
                    var o = document.createElement('option');
                    o.value = r2.name;
                    o.label = r2.pfad;
                    dl.appendChild(o);
                });
            })
            .catch(function () {});
    }

    // ── Auswertung starten ──────────────────────────────────────────
    function note(msg, kind) {
        var el = $('vm-note'); if (!el) return;
        el.textContent = msg || '';
        el.className = 'vm-note' + (kind === 'error' ? ' is-error'
            : kind === 'warn' ? ' is-warn' : kind === 'ok' ? ' is-ok' : '');
    }

    function busy(on) {
        var run = $('vm-run'), cancel = $('vm-cancel');
        if (run) run.disabled = !!on;
        if (cancel) cancel.classList.toggle('hidden', !on);
    }

    function run() {
        var a = currentAnalysis();
        var q = ($('vm-question') ? $('vm-question').value : '').trim();
        if (!a && !q) {
            note(T('vemas.need_input', 'Bitte eine Abfrage wählen oder eine Frage eingeben.'), 'error');
            return;
        }
        if (_status && _status.configured === false) {
            note(T('vemas.not_configured_hint',
                'Ein Administrator hinterlegt Serveradresse und Zugang unter Einstellungen → Vemas.'), 'error');
            return;
        }
        var tool = $('vm-tool') ? $('vm-tool').value : '';
        localStorage.setItem(PREF_TOOL, tool);
        localStorage.setItem(PREF_ANALYSIS, a ? a.id : '');

        busy(true);
        showResult('<div class="vm-busy"><span class="vm-spin"></span><span>'
            + esc(T('vemas.running_long',
                'Der Assistent liest die Daten aus VEMAS und verdichtet sie. Das kann einige Minuten dauern.'))
            + '</span></div>', a ? a.title : T('vemas.free_question_short', 'Freie Frage'));

        _abort = new AbortController();
        fetch('/api/vemas/ask', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                analysis_id: a ? a.id : '', question: q,
                tool: tool, lang: lang()
            }),
            signal: _abort.signal
        })
            .then(function (r) {
                if (r.status === 423) {
                    // Konto wegen Sicherheitsverstoss gesperrt – dieselbe
                    // Behandlung wie im Chat und in /sap.
                    return r.json().catch(function () { return {}; }).then(function (e) {
                        throw new Error(e.message || T('vemas.blocked', 'Konto gesperrt.'));
                    });
                }
                return r.json().catch(function () { return null; });
            })
            .then(function (d) {
                if (!d) throw new Error(T('vemas.failed', 'Auswertung fehlgeschlagen.'));
                if (!d.ok) throw new Error(d.error || T('vemas.failed', 'Auswertung fehlgeschlagen.'));
                renderAnswer(d.answer || '',
                    a ? a.title : T('vemas.free_question_short', 'Freie Frage'), d);
                pushHistory(a, q, tool);
                note('');
            })
            .catch(function (e) {
                if (e && e.name === 'AbortError') {
                    showResult('<div class="vm-empty">'
                        + esc(T('vemas.cancelled', 'Auswertung abgebrochen.')) + '</div>', '');
                    note('');
                    return;
                }
                showResult('<div class="vm-empty" style="color:var(--danger);">'
                    + esc((e && e.message) || T('vemas.failed', 'Auswertung fehlgeschlagen.'))
                    + '</div>', '');
                note('');
            })
            .then(function () { busy(false); _abort = null; });
    }

    function cancel() {
        // Beide Seiten beenden: der Abbruch im Browser stoppt nur das Warten,
        // der Agent liefe sonst im Hintergrund weiter und blockierte die
        // Sperre fuer die naechste Auswertung.
        if (_abort) { try { _abort.abort(); } catch (e) {} }
        fetch('/api/vemas/stop', { method: 'POST', headers: authHeaders() }).catch(function () {});
    }

    function showResult(html, title) {
        var box = $('vm-result'); if (!box) return;
        box.classList.remove('hidden');
        if (title) $('vm-result-title').textContent = title;
        $('vm-result-body').innerHTML = html;
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
        // den Sammelzugang zurueck, sind die Daten mit fremden, in der Regel
        // weiteren Berechtigungen geholt; das darf nicht unbemerkt bleiben.
        if (meta && meta.quelle) {
            var eigen = (meta.quelle === 'persoenlich');
            var kopf = eigen ? T('vemas.res_own', 'Gelesen mit deinem persönlichen VEMAS-Zugang.')
                             : T('vemas.res_shared', 'Gelesen mit dem gemeinsamen Zugang.');
            html = '<div class="vm-acc-note' + (meta.hinweis ? ' is-on' : '')
                + '" style="' + (meta.hinweis ? '' : 'display:block;border-color:var(--border);') + '">'
                + esc(kopf) + (meta.hinweis ? ' ' + esc(meta.hinweis) : '') + '</div>' + html;
        }
        showResult(html, title);
        // ```chartjs-Bloecke zu echten Diagrammen machen. charts.js beobachtet
        // das DOM zwar selbst, der ausdrueckliche Aufruf spart die 250 ms
        // Debounce und wirkt auch, wenn der Beobachter nicht greift.
        if (window.JarvisCharts && window.JarvisCharts.hydrate) {
            try { window.JarvisCharts.hydrate($('vm-result-body')); } catch (e) {}
        }
    }

    // ── Verlauf (rein lokal im Browser) ─────────────────────────────
    // Bewusst localStorage und nicht serverseitig: der Verlauf ist eine
    // Bequemlichkeit fuer den einzelnen Arbeitsplatz. Gespeichert wird nur,
    // WAS gefragt wurde – nie das Ergebnis, damit keine Geschaeftsdaten im
    // Browser-Speicher liegen bleiben.
    function readHistory() {
        try { return JSON.parse(localStorage.getItem(HIST_KEY) || '[]') || []; }
        catch (e) { return []; }
    }
    function pushHistory(a, q, tool) {
        var list = readHistory();
        list.unshift({ id: a ? a.id : '', title: a ? a.title : '', q: q, tool: tool, ts: Date.now() });
        try { localStorage.setItem(HIST_KEY, JSON.stringify(list.slice(0, HIST_MAX))); }
        catch (e) {}
        renderHistory();
    }
    // Loescht GENAU EINEN Eintrag, gefunden ueber den Zeitstempel: ein zweiter
    // Tab kann den Verlauf inzwischen verschoben haben, ein Listenindex traefe
    // dann den falschen Eintrag.
    function deleteHistory(ts) {
        var list = readHistory();
        var i = -1;
        for (var k = 0; k < list.length; k++) { if (list[k].ts === ts) { i = k; break; } }
        if (i < 0) { renderHistory(); return; }
        list.splice(i, 1);
        try { localStorage.setItem(HIST_KEY, JSON.stringify(list)); } catch (e) {}
        renderHistory();
    }
    function renderHistory() {
        var box = $('vm-hist-list'); if (!box) return;
        var list = readHistory();
        box.innerHTML = '';
        if (!list.length) {
            var e0 = document.createElement('div');
            e0.className = 'vm-hist-empty';
            e0.textContent = T('vemas.hist_empty', 'Noch keine Auswertungen.');
            box.appendChild(e0);
            return;
        }
        list.forEach(function (h) {
            var d = document.createElement('div');
            d.className = 'vm-hist-item';
            var q = document.createElement('div');
            q.className = 'vm-hist-q';
            q.textContent = h.title || h.q || '—';
            var m = document.createElement('div');
            m.className = 'vm-hist-meta';
            m.textContent = new Date(h.ts || 0).toLocaleString()
                + (h.q && h.title ? ' · ' + h.q : '');
            // Text in einem eigenen Kind (min-width:0), sonst greift das
            // Ellipsis der langen Zeile im Flex-Container nicht mehr.
            var txt = document.createElement('div');
            txt.className = 'vm-hist-text';
            txt.appendChild(q); txt.appendChild(m);
            d.appendChild(txt);
            // MUELLEIMER, kein x: der gespeicherte Eintrag wird dauerhaft
            // entfernt (Symbol-Semantik 2026-08-19).
            var del = document.createElement('button');
            del.type = 'button';
            del.className = 'vm-hist-del';
            del.innerHTML = window.JarvisIcons.trash();
            var lbl = T('sup.hist_del', 'Eintrag löschen');
            del.title = lbl;
            del.setAttribute('aria-label', lbl);
            del.addEventListener('click', function (e) {
                // stopPropagation ist hier PFLICHT, und zwar doppelt: ohne sie
                // uebernaehme der Eintrag darunter die Auswertung ins Formular,
                // UND der Dokument-Listener schloesse das Verlaufsfeld – die
                // geloeschte Zeile haengt beim Weiterlaufen des Klicks nicht
                // mehr im Panel, `panel.contains(target)` ist dann falsch.
                e.stopPropagation();
                e.preventDefault();
                deleteHistory(h.ts);
            });
            d.appendChild(del);
            // Ein Klick UEBERNIMMT nur, er startet nicht: eine Auswertung
            // kostet Minuten und Last (gleiche Entscheidung wie in /sap).
            d.addEventListener('click', function () {
                if ($('vm-analysis')) $('vm-analysis').value = h.id || '';
                if ($('vm-question')) $('vm-question').value = h.q || '';
                if (h.tool && $('vm-tool')) $('vm-tool').value = h.tool;
                applyDesc();
                $('vm-hist-panel').classList.add('hidden');
            });
            box.appendChild(d);
        });
    }

    // ── Persoenliche Anweisungen ────────────────────────────────────
    function openInstructions() {
        $('vm-instr-overlay').classList.remove('hidden');
        $('vm-instr-status').textContent = '';
        fetch('/api/vemas/instructions', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (d && d.ok && $('vm-instr-text')) $('vm-instr-text').value = d.instructions || '';
            })
            .catch(function () {});
    }

    function saveInstructions() {
        var txt = $('vm-instr-text') ? $('vm-instr-text').value : '';
        $('vm-instr-status').textContent = T('vemas.acc_saving', 'Speichere…');
        fetch('/api/vemas/instructions', {
            method: 'POST',
            headers: authHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ instructions: txt })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                $('vm-instr-status').textContent = (d && d.ok)
                    ? '✓ ' + T('vemas.acc_saved', 'Gespeichert.')
                    : T('vemas.acc_save_failed', 'Speichern fehlgeschlagen.');
            })
            .catch(function () {
                $('vm-instr-status').textContent = T('vemas.acc_save_failed', 'Speichern fehlgeschlagen.');
            });
    }

    // ── Abfrage-Konsole (ohne KI) ───────────────────────────────────
    function renderTable(box, columns, rows) {
        if (!box) return;
        if (!rows || !rows.length) {
            box.innerHTML = '<span class="vm-empty">'
                + esc(T('vemas.no_rows', 'Keine Datensätze.')) + '</span>';
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

    function consoleNote(msg, kind) {
        var el = $('vm-q-note'); if (!el) return;
        el.textContent = msg || '';
        el.className = 'vm-note' + (kind === 'error' ? ' is-error' : kind === 'ok' ? ' is-ok' : '');
    }

    function runQuery() {
        var box = $('vm-console-out'); if (!box) return;
        var res = ($('vm-q-resource') ? $('vm-q-resource').value : '').trim();
        if (!res) {
            consoleNote(T('vemas.need_resource', 'Bitte eine Ressource angeben.'), 'error');
            return;
        }
        consoleNote('');
        box.innerHTML = '<span class="vm-empty">' + esc(T('vemas.loading', 'Lade…')) + '</span>';
        var url = '/api/vemas/query?resource=' + encodeURIComponent(res)
            + '&params=' + encodeURIComponent(($('vm-q-params') ? $('vm-q-params').value : '').trim())
            + '&top=' + encodeURIComponent(($('vm-q-top') ? $('vm-q-top').value : '') || '20');
        fetch(url, { headers: authHeaders() })
            .then(function (r) { return r.json().catch(function () { return null; }); })
            .then(function (d) {
                if (!d || !d.ok) {
                    box.innerHTML = '';
                    consoleNote((d && d.error) || T('vemas.failed', 'Abfrage fehlgeschlagen.'), 'error');
                    return;
                }
                renderTable(box, d.columns, d.rows);
                consoleNote((d.rows || []).length + ' ' + T('vemas.rows_found', 'Datensätze'), 'ok');
            })
            .catch(function () {
                box.innerHTML = '';
                consoleNote(T('vemas.failed', 'Abfrage fehlgeschlagen.'), 'error');
            });
    }

    // ── Mein VEMAS-Zugang ───────────────────────────────────────────
    function accNote(msg, kind) {
        var el = $('vm-acc-status'); if (!el) return;
        el.textContent = msg || '';
        el.className = 'vm-note' + (kind === 'error' ? ' is-error' : kind === 'ok' ? ' is-ok' : '');
    }

    // Benutzer/Kennwort ODER Token – nie beides. Sonst fuellt jemand das Feld,
    // das seine Anmeldeart gar nicht benutzt, und sucht den Fehler beim Server.
    // 'login' braucht ebenfalls Benutzer und Kennwort (damit holt der Server
    // das Token), deshalb teilt es sich die Gruppe mit 'basic'.
    function accApplyAuth() {
        var art = $('vm-acc-auth') ? $('vm-acc-auth').value : '';
        var u = $('vm-acc-g-user'), t = $('vm-acc-g-token');
        if (u) u.hidden = !(art === 'basic' || art === 'login');
        if (t) t.hidden = (art !== 'bearer');
    }

    // Pille + Hinweiskasten. Die Aussage steckt in Farbe UND Text – Farbe
    // allein ist keine Information.
    function accRenderState() {
        var pill = $('vm-acc-pill');
        var box = $('vm-acc-note');
        var quelle = (_status && _status.quelle) || 'sammel';
        var hinweis = (_status && _status.hinweis) || '';
        if (pill) {
            if (quelle === 'persoenlich') {
                pill.className = 'vm-acc-pill is-own';
                pill.textContent = T('vemas.acc_pill_own', 'eigener Zugang');
            } else if (hinweis) {
                pill.className = 'vm-acc-pill is-warn';
                pill.textContent = T('vemas.acc_pill_fallback', 'gemeinsamer Zugang (Rückfall)');
            } else {
                pill.className = 'vm-acc-pill';
                pill.textContent = T('vemas.acc_pill_shared', 'gemeinsamer Zugang');
            }
        }
        if (box) {
            box.textContent = hinweis;
            box.classList.toggle('is-on', !!hinweis);
        }
    }

    // Der Satz zum Schreiben gehoert an die Kachel, nicht in eine Fussnote:
    // "Schreiben ist freigegeben" gilt NUR mit eigenem Zugang, und genau das
    // erklaert sonst niemand.
    function accRenderWrite() {
        var el = $('vm-acc-write'); if (!el || !_account) return;
        if (!_account.server_konfiguriert) {
            el.textContent = T('vemas.acc_no_server',
                'Es ist noch kein VEMAS-Server hinterlegt – ein eigener Zugang ist derzeit wirkungslos. '
                + 'Ein Administrator trägt ihn unter Einstellungen → Vemas ein.');
            return;
        }
        el.textContent = _account.schreiben_frei
            ? T('vemas.acc_write_on',
                'Schreibzugriffe sind freigegeben – sie laufen ausschließlich über einen eigenen Zugang, '
                + 'damit jeder Vorgang in VEMAS deinem Konto zuzuordnen ist. Über den gemeinsamen Zugang bleibt es beim Lesen.')
            : T('vemas.acc_write_off', 'Es wird ausschließlich gelesen. Schreibzugriffe kann ein Administrator freigeben.');
    }

    function loadAccount() {
        fetch('/api/vemas/account', { headers: authHeaders() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok || !d.account) return;
                var a = _account = d.account;
                if ($('vm-acc-server')) $('vm-acc-server').value = a.server || '';
                if ($('vm-acc-auth')) $('vm-acc-auth').value = a.auth_kind || '';
                if ($('vm-acc-aktiv')) $('vm-acc-aktiv').checked = a.aktiv !== false;
                if ($('vm-acc-user')) $('vm-acc-user').value = a.username || '';
                // Kennwort-/Token-Felder bleiben LEER (der Server gibt sie nie
                // heraus); der Platzhalter sagt, dass leer "unveraendert" heisst.
                accApplyAuth();
                accRenderWrite();
                accRenderState();
                if (a.ausgesetzt) {
                    // Der GRUND gehoert dazu: ohne ihn stuende hier nur
                    // "Zugangsdaten pruefen", waehrend der Zugang womoeglich an
                    // einer fehlenden BERECHTIGUNG gescheitert ist – der Satz
                    // schickte den Benutzer an die falsche Stelle.
                    var grund = a.ausgesetzt_grund || a.letzter_fehler || '';
                    accNote(T('vemas.acc_suspended',
                        'Ausgesetzt nach fehlgeschlagenen Anmeldungen – Zugangsdaten prüfen und „Verbindung testen" drücken.')
                        + (grund ? ' ' + T('vemas.acc_last_error', 'Letzter Fehler:') + ' ' + grund : ''),
                        'error');
                } else if (a.letzter_fehler) {
                    accNote(a.letzter_fehler, 'error');
                }
            })
            .catch(function () {});
    }

    function accCollect() {
        var v = function (id) { var e = $(id); return e ? e.value.trim() : ''; };
        var raw = function (id) { var e = $(id); return e ? e.value : ''; };
        // Es werden immer alle Felder gesendet: der Server hat die Whitelist,
        // und ein Wechsel der Anmeldeart soll die alten Werte nicht heimlich
        // stehen lassen. Die Serveradresse ist NICHT dabei – sie gehoert dem
        // Administrator (der Server wuerde sie ohnehin mit 400 abweisen).
        return {
            auth_kind: v('vm-acc-auth'),
            aktiv: $('vm-acc-aktiv') ? $('vm-acc-aktiv').checked : true,
            username: v('vm-acc-user'),
            password: raw('vm-acc-pass'),
            api_token: raw('vm-acc-token')
        };
    }

    function accClearSecrets() {
        ['vm-acc-pass', 'vm-acc-token'].forEach(function (id) {
            var e = $(id); if (e) e.value = '';
        });
    }

    function saveAccount() {
        var art = $('vm-acc-auth') ? $('vm-acc-auth').value : '';
        if (!art) {
            // Kein leerer Datensatz: sonst laegen Zugangsdaten gespeichert da,
            // die nie benutzt werden. Wer keinen eigenen Zugang will, entfernt ihn.
            accNote(T('vemas.acc_need_type',
                'Bitte eine Anmeldeart wählen – oder „Eigenen Zugang entfernen" drücken.'), 'error');
            return;
        }
        accNote(T('vemas.acc_saving', 'Speichere…'));
        fetch('/api/vemas/account', {
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
                    accNote((res.d && res.d.error)
                        || T('vemas.acc_save_failed', 'Speichern fehlgeschlagen.'), 'error');
                    return;
                }
                accClearSecrets();
                accNote('✓ ' + T('vemas.acc_saved', 'Gespeichert.'), 'ok');
                loadAccount();
                loadStatus();      // Pille und Verbindungsanzeige folgen sofort
            })
            .catch(function () {
                accNote(T('vemas.acc_save_failed', 'Speichern fehlgeschlagen.'), 'error');
            });
    }

    function testAccount() {
        accNote(T('vemas.acc_testing', 'Teste Verbindung…'));
        fetch('/api/vemas/test', { headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.ok) {
                    var q = (d.quelle === 'persoenlich')
                        ? T('vemas.acc_pill_own', 'eigener Zugang')
                        : T('vemas.acc_pill_shared', 'gemeinsamer Zugang');
                    accNote('✅ ' + q + ' – ' + (d.detail || 'OK'), 'ok');
                } else if (d && d.configured === false) {
                    accNote(T('vemas.acc_not_configured', 'Kein Zugang konfiguriert.'), 'error');
                } else {
                    accNote('❌ ' + ((d && d.error) || T('vemas.failed', 'Fehlgeschlagen.')), 'error');
                }
                loadAccount();
                loadStatus();
            })
            .catch(function () { accNote('❌ ' + T('vemas.failed', 'Fehlgeschlagen.'), 'error'); });
    }

    function delAccount() {
        if (!window.confirm(T('vemas.acc_del_confirm',
            'Eigenen VEMAS-Zugang entfernen? Danach laufen Auswertungen wieder über den gemeinsamen Zugang.'))) return;
        fetch('/api/vemas/account', { method: 'DELETE', headers: authHeaders() })
            .then(function (r) { return r.json(); })
            .then(function () {
                accClearSecrets();
                if ($('vm-acc-auth')) $('vm-acc-auth').value = '';
                if ($('vm-acc-user')) $('vm-acc-user').value = '';
                accApplyAuth();
                accNote(T('vemas.acc_removed', 'Eigener Zugang entfernt.'), 'ok');
                loadAccount();
                loadStatus();
            })
            .catch(function () { accNote('❌ ' + T('vemas.failed', 'Fehlgeschlagen.'), 'error'); });
    }

    // ── Verdrahtung ─────────────────────────────────────────────────
    var _bound = false;
    function bind() {
        if (_bound) return; _bound = true;

        // Muelleimer aus icons.js in den Slot – NIE als Emoji und nie als
        // Text: das SVG erbt currentColor und folgt damit Theme und Marke.
        var ico = $('vm-acc-del-ico');
        if (ico && window.JarvisIcons) ico.innerHTML = window.JarvisIcons.trash();

        $('vm-analysis').addEventListener('change', function () { applyDesc(); note(''); });
        $('vm-run').addEventListener('click', run);
        $('vm-cancel').addEventListener('click', cancel);
        $('vm-question').addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
        });

        $('vm-copy').addEventListener('click', function () {
            var done = function () { note(T('vemas.copied', 'In die Zwischenablage kopiert.'), 'ok'); };
            if (window.JarvisChatLib && window.JarvisChatLib.copyTextToClipboard) {
                window.JarvisChatLib.copyTextToClipboard(_lastAnswer).then(done);
            } else if (navigator.clipboard) {
                navigator.clipboard.writeText(_lastAnswer).then(done);
            }
        });

        var accA = $('vm-acc-auth');
        if (accA) accA.addEventListener('change', function () { accApplyAuth(); accNote(''); });
        var accS = $('vm-acc-save'); if (accS) accS.addEventListener('click', saveAccount);
        var accP = $('vm-acc-test'); if (accP) accP.addEventListener('click', testAccount);
        var accD = $('vm-acc-del'); if (accD) accD.addEventListener('click', delAccount);

        var qr = $('vm-q-run'); if (qr) qr.addEventListener('click', runQuery);

        $('vm-instr-btn').addEventListener('click', openInstructions);
        $('vm-instr-close').addEventListener('click', function () {
            $('vm-instr-overlay').classList.add('hidden');
        });
        $('vm-instr-overlay').addEventListener('click', function (e) {
            if (e.target === this) this.classList.add('hidden');
        });
        $('vm-instr-save').addEventListener('click', saveInstructions);

        $('vm-hist-btn').addEventListener('click', function (e) {
            e.stopPropagation();
            $('vm-hist-panel').classList.toggle('hidden');
        });
        $('vm-hist-clear').addEventListener('click', function (e) {
            e.stopPropagation();
            try { localStorage.removeItem(HIST_KEY); } catch (err) {}
            renderHistory();
        });
        // Klick daneben schliesst das Verlaufsfeld – sonst bleibt es beim
        // Weiterarbeiten ueber der Seite stehen.
        document.addEventListener('click', function (e) {
            var p = $('vm-hist-panel');
            if (p && !p.classList.contains('hidden') && !p.contains(e.target)) p.classList.add('hidden');
        });
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            // Reihenfolge: erst das obenauf liegende Fenster, sonst schliesst
            // Escape das Verlaufsfeld unter einem offenen Anweisungs-Dialog.
            var ov = $('vm-instr-overlay');
            if (ov && !ov.classList.contains('hidden')) { ov.classList.add('hidden'); return; }
            var p = $('vm-hist-panel');
            if (p && !p.classList.contains('hidden')) p.classList.add('hidden');
        });

        $('vm-logout-btn').addEventListener('click', function () {
            var p = (window.JarvisSession ? window.JarvisSession.logout() : Promise.resolve());
            TOKEN_KEYS.forEach(function (k) { localStorage.removeItem(k); });
            p.catch(function () {}).then(function () { window.location.replace('/'); });
        });

        // Sprachwechsel: der Katalog kommt uebersetzt vom Server, also neu
        // holen. Der Vergleich mit `_catalog.lang` ist noetig, weil applyLang()
        // das Ereignis auch beim Seitenaufbau feuert – ohne ihn holte die Seite
        // den Katalog jedes Mal zweimal.
        window.addEventListener('jarvis-lang-changed', function (e) {
            var lg = (e && e.detail && e.detail.lang) || lang();
            if (_catalog && _catalog.lang === (lg === 'en' ? 'en' : 'de')) return;
            localStorage.setItem(PREF_ANALYSIS, $('vm-analysis') ? $('vm-analysis').value : '');
            loadCatalog();
            renderHistory();
            accRenderWrite();
            accRenderState();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
