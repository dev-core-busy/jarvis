/* ═══════════════════════════════════════════════════════════════════
   Jira-Reiter (Einstellungen) – Schwerpunkt Ticketsuche
   ───────────────────────────────────────────────────────────────────
   Verbindungskonfiguration (URL/Token), Verbindungstest und eine
   Such-/Leseoberflaeche fuer Tickets (Volltext + optionale Filter / JQL).
   Schreiboperationen (Kommentar, Ticket anlegen) laufen ueber die
   Agent-Tools des Skills.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    // Jira liefert ISO-8601-Strings (z.B. "2024-03-15T10:30:00.000+0100").
    // Festes Format tt.mm.jjjj HH:MM (24h, null-gepolstert); leer/ungueltig -> ''.
    function fmtDate(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        function p(n) { return (n < 10 ? '0' : '') + n; }
        return p(d.getDate()) + '.' + p(d.getMonth() + 1) + '.' + d.getFullYear()
            + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    }
    function status(msg, kind) {
        setStatus('jira-status', msg, kind);
    }
    function setStatus(id, msg, kind) {
        var el = $(id); if (!el) return;
        el.textContent = msg || '';
        el.style.color = kind === 'error' ? 'var(--danger)'
            : kind === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
    }
    // Uebersetzung mit Rueckfall: der Reiter wird auch gerendert, wenn i18n.js
    // (noch) nicht da ist – dann steht der deutsche Text statt eines leeren
    // Feldes. Platzhalter werden hier ersetzt, window.t kennt keine.
    function t(key, fallback, werte) {
        var s = (window.t && window.t(key)) || '';
        if (!s || s === key) s = fallback;
        for (var k in (werte || {})) s = s.split('{' + k + '}').join(werte[k]);
        return s;
    }

    var SVG_EYE_OPEN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
    var SVG_EYE_CLOSED = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';

    var Manager = {
        _bound: false,

        onShow: function () {
            this._bind();
            this.loadConfig();
            this.loadVorlagen();
        },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            var save = $('jira-save'); if (save) save.addEventListener('click', this.save.bind(this));
            var test = $('jira-test'); if (test) test.addEventListener('click', this.test.bind(this));
            var sb = $('jira-search-btn'); if (sb) sb.addEventListener('click', this.search.bind(this));
            ['jira-search-q', 'jira-search-project', 'jira-search-jql'].forEach(function (id) {
                var el = $(id);
                if (el) el.addEventListener('keydown', function (e) { if (e.key === 'Enter') Manager.search(); });
            });
            var sh = $('jshare-save'); if (sh) sh.addEventListener('click', this.saveShare.bind(this));
            var vs = $('jvorl-save'); if (vs) vs.addEventListener('click', this.saveVorlage.bind(this));
            var vn = $('jvorl-new');
            if (vn) vn.addEventListener('click', function () { Manager.editVorlage(null, false); });
            // Auge: PAT anzeigen/verbergen (analog Confluence-Reiter)
            var tt = $('jira-token-toggle');
            if (tt) tt.addEventListener('click', function () {
                var inp = $('jira-token'); if (!inp) return;
                var hidden = inp.type === 'password';
                inp.type = hidden ? 'text' : 'password';
                tt.innerHTML = hidden ? SVG_EYE_CLOSED : SVG_EYE_OPEN;
            });
        },

        loadConfig: function () {
            fetch('/api/skills/jira/config', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var c = (d && d.config) || {};
                    if ($('jira-url')) $('jira-url').value = c.base_url || '';
                    if ($('jira-token')) $('jira-token').value = c.api_token || '';
                    if ($('jira-max-results')) $('jira-max-results').value = c.max_results || 50;
                    if ($('jshare-chrome')) $('jshare-chrome').value = c.addon_pfad_chrome || '';
                    if ($('jshare-firefox')) $('jshare-firefox').value = c.addon_pfad_firefox || '';
                })
                .catch(function () {});
        },

        save: function () {
            var mr = parseInt(($('jira-max-results') ? $('jira-max-results').value : '') || '50', 10);
            if (isNaN(mr) || mr < 1) mr = 50;
            if (mr > 1000) mr = 1000;
            // IBS-/Kundenverwaltungs-Felder pflegt der Kundenverwaltungs-Reiter
            // (kundenverwaltung.js) – gleicher Config-Store, getrennte Teilschluessel.
            var body = {
                base_url: ($('jira-url') ? $('jira-url').value : '').trim(),
                api_token: ($('jira-token') ? $('jira-token').value : '').trim(),
                max_results: mr
            };
            status('Speichere…');
            fetch('/api/skills/jira/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json(); })
              .then(function () { status('✓ Gespeichert', 'ok'); })
              .catch(function () { status('✗ Fehler beim Speichern', 'error'); });
        },

        /* Eigener Knopf, eigene TEILMENGE.
         *
         * `POST /api/skills/jira/config` merged serverseitig – ein Knopf darf
         * deshalb nur seine eigenen Felder senden. Schickte er den ganzen
         * Formularstand mit, ueberschriebe er den Stand des anderen Knopfes
         * (im Projekt bezahlt, siehe Register „Zwei Knoepfe im selben Reiter"):
         * ein leeres Token-Feld waere dann ein geloeschter Zugang.
         */
        saveShare: function () {
            var s = $('jshare-status');
            var setz = function (t, art) {
                if (!s) return;
                s.textContent = t || '';
                s.style.color = art === 'ok' ? 'var(--success, #2ecc71)'
                              : art === 'error' ? 'var(--danger, #e74c3c)' : '';
            };
            var body = {
                addon_pfad_chrome: ($('jshare-chrome') ? $('jshare-chrome').value : '').trim(),
                addon_pfad_firefox: ($('jshare-firefox') ? $('jshare-firefox').value : '').trim()
            };
            setz('Speichere…');
            fetch('/api/skills/jira/config', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json(); })
              .then(function () { setz('✓ Gespeichert', 'ok'); })
              .catch(function () { setz('✗ Fehler beim Speichern', 'error'); });
        },

        test: function () {
            status('Teste Verbindung…');
            fetch('/api/jira/test', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (d && d.ok) {
                        status('✅ Verbunden als ' + (d.user || '?'), 'ok');
                    } else if (d && d.configured === false) {
                        status('Nicht konfiguriert – bitte zuerst speichern.', 'error');
                    } else {
                        status('❌ ' + ((d && d.error) || 'Verbindung fehlgeschlagen'), 'error');
                    }
                })
                .catch(function () { status('❌ Verbindungstest fehlgeschlagen', 'error'); });
        },

        /* ── Vorlagen des Jira-Assistenten ──────────────────────────────────
           Dieselben Endpunkte wie im Fenster der Erweiterung; die Schranke
           „gemeinsame Vorlagen nur fuer Admins" sitzt im Backend
           (jira_vorlagen.speichern). Hier wird sie nur ANGEZEIGT – eine
           Oberflaeche, die das Haekchen versteckt, ist keine Schranke. */
        _vorlagen: { global: [], eigene: [], darf_global: false },
        _vorlBearbeitet: '',

        loadVorlagen: function () {
            var box = $('jvorl-liste'); if (!box) return;
            box.innerHTML = '<span class="kb-hint">' + esc(t('jvorl.loading', 'Lade Vorlagen …')) + '</span>';
            fetch('/api/jira/assist/vorlagen', { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || d.ok === false) throw new Error((d && d.error) || 'Fehler');
                    Manager._vorlagen = {
                        global: d.global || [], eigene: d.eigene || [],
                        darf_global: !!d.darf_global
                    };
                    Manager.renderVorlagen();
                })
                .catch(function (e) {
                    box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                        + esc(e.message || 'Vorlagen konnten nicht geladen werden.') + '</span>';
                });
        },

        renderVorlagen: function () {
            var box = $('jvorl-liste'); if (!box) return;
            var v = this._vorlagen;
            var zeile = $('jvorl-global-zeile');
            // Wer keine gemeinsamen Vorlagen anlegen darf, sieht das Haekchen
            // gar nicht erst – der Server wuerde ihn ohnehin abweisen.
            if (zeile) zeile.style.display = v.darf_global ? '' : 'none';
            box.innerHTML = '';
            var alle = v.global.map(function (x) { return { v: x, global: true }; })
                .concat(v.eigene.map(function (x) { return { v: x, global: false }; }));
            if (!alle.length) {
                box.innerHTML = '<span class="kb-hint">' + esc(t('jvorl.empty', 'Noch keine Vorlagen.')) + '</span>';
                return;
            }
            alle.forEach(function (e) {
                // Aendern darf man Eigenes immer, Gemeinsames nur als Admin.
                var darf = !e.global || v.darf_global;
                var row = document.createElement('div');
                row.style.cssText = 'display:flex;justify-content:space-between;align-items:flex-start;'
                    + 'gap:10px;padding:8px 10px;border:1px solid var(--border);border-radius:8px;'
                    + 'background:var(--bg-glass);';
                var links = document.createElement('span');
                links.style.cssText = 'min-width:0;';
                // textContent: Name und Text sind Freitext aus einem Formular.
                var titel = document.createElement('span');
                titel.style.fontWeight = '600';
                titel.textContent = e.v.name || '';
                var art = document.createElement('span');
                art.className = 'kb-hint';
                art.style.marginLeft = '8px';
                art.textContent = e.global ? t('jvorl.shared', 'Gemeinsam') : t('jvorl.mine', 'Nur für mich');
                var text = document.createElement('div');
                text.className = 'kb-hint';
                text.style.cssText = 'white-space:pre-wrap;word-break:break-word;';
                text.textContent = e.v.text || '';
                links.appendChild(titel); links.appendChild(art); links.appendChild(text);
                row.appendChild(links);

                if (darf) {
                    var knoepfe = document.createElement('span');
                    knoepfe.style.cssText = 'display:flex;gap:4px;flex:0 0 auto;';
                    var b = document.createElement('button');
                    b.type = 'button';
                    b.className = 'kb-hdr-btn';
                    b.title = t('jvorl.edit', 'Bearbeiten');
                    b.textContent = '✎';
                    b.addEventListener('click', function () { Manager.editVorlage(e.v, e.global); });
                    knoepfe.appendChild(b);
                    var w = document.createElement('button');
                    w.type = 'button';
                    w.className = 'kb-hdr-btn';
                    w.title = t('jvorl.del', 'Löschen');
                    // Muelleimer = loeschen (Projektregel), als Inline-SVG aus
                    // icons.js – nie ein Emoji, nie ein ×.
                    w.innerHTML = (window.JarvisIcons && window.JarvisIcons.trash()) || '';
                    w.addEventListener('click', function () { Manager.deleteVorlage(e.v); });
                    knoepfe.appendChild(w);
                    row.appendChild(knoepfe);
                }
                box.appendChild(row);
            });
        },

        editVorlage: function (v, global_) {
            this._vorlBearbeitet = v ? (v.id || '') : '';
            if ($('jvorl-name')) $('jvorl-name').value = v ? (v.name || '') : '';
            if ($('jvorl-text')) $('jvorl-text').value = v ? (v.text || '') : '';
            if ($('jvorl-global')) $('jvorl-global').checked = !!global_;
            setStatus('jvorl-status',
                v ? t('jvorl.editing', 'Ändert „{name}“.', { name: v.name || '' }) : '');
        },

        saveVorlage: function () {
            var name = ($('jvorl-name') ? $('jvorl-name').value : '').trim();
            var text = ($('jvorl-text') ? $('jvorl-text').value : '').trim();
            if (!name || !text) {
                setStatus('jvorl-status', t('jvorl.need', 'Name und Anweisung sind nötig.'), 'error');
                return;
            }
            fetch('/api/jira/assist/vorlagen', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({
                    id: this._vorlBearbeitet, name: name, text: text,
                    global: !!($('jvorl-global') && $('jvorl-global').checked)
                })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                    if (!d || d.ok === false) throw new Error((d && (d.error || d.detail)) || 'Fehler');
                    Manager.editVorlage(null, false);
                    Manager.loadVorlagen();
                    setStatus('jvorl-status', t('jvorl.saved', '✓ Gespeichert'), 'ok');
              })
              .catch(function (e) { setStatus('jvorl-status', e.message, 'error'); });
        },

        deleteVorlage: function (v) {
            if (!confirm(t('jvorl.del_ask', 'Vorlage „{name}“ wirklich löschen?',
                           { name: v.name || '' }))) return;
            fetch('/api/jira/assist/vorlagen/' + encodeURIComponent(v.id || ''), {
                method: 'DELETE', headers: authHeaders()
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                    if (!d || d.ok === false) throw new Error((d && (d.error || d.detail)) || 'Fehler');
                    if (Manager._vorlBearbeitet === v.id) Manager.editVorlage(null, false);
                    Manager.loadVorlagen();
                    setStatus('jvorl-status', t('jvorl.deleted', '✓ Gelöscht'), 'ok');
              })
              .catch(function (e) { setStatus('jvorl-status', e.message, 'error'); });
        },

        search: function () {
            var q = ($('jira-search-q') ? $('jira-search-q').value : '').trim();
            var project = ($('jira-search-project') ? $('jira-search-project').value : '').trim();
            var jql = ($('jira-search-jql') ? $('jira-search-jql').value : '').trim();
            var box = $('jira-results');
            if (!box) return;
            box.innerHTML = '<span class="kb-hint">Suche…</span>';
            if ($('jira-issue-view')) $('jira-issue-view').style.display = 'none';
            var url = '/api/jira/search?limit=25'
                + '&q=' + encodeURIComponent(q)
                + '&project=' + encodeURIComponent(project)
                + '&jql=' + encodeURIComponent(jql);
            fetch(url, { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">'
                            + esc((d && d.error) || 'Suche fehlgeschlagen') + '</span>';
                        return;
                    }
                    var res = d.results || [];
                    var head = '<div class="kb-hint" style="margin-bottom:8px;">' + (d.total || res.length)
                        + ' Treffer · <code>' + esc(d.jql || '') + '</code></div>';
                    if (!res.length) { box.innerHTML = head + '<span class="kb-hint">Keine Tickets.</span>'; return; }
                    box.innerHTML = head;
                    res.forEach(function (r) {
                        var row = document.createElement('div');
                        row.className = 'jira-result-row';
                        row.style.cssText = 'display:flex;justify-content:space-between;align-items:center;'
                            + 'gap:10px;padding:8px 10px;margin-bottom:6px;border:1px solid var(--border);'
                            + 'border-radius:8px;cursor:pointer;background:var(--bg-glass);';
                        var rC = fmtDate(r.created), rU = fmtDate(r.updated);
                        var meta = [r.status, r.type, r.priority ? ('Prio ' + r.priority) : '',
                                    r.assignee ? ('→ ' + r.assignee) : '',
                                    rC ? ('Erstellt ' + rC) : '',
                                    rU ? ('Geändert ' + rU) : ''].filter(Boolean).join(' · ');
                        row.innerHTML = '<span style="min-width:0;"><span style="font-weight:600;">'
                            + esc(r.key) + '</span> ' + esc(r.summary || '')
                            + '<br><span class="kb-hint">' + esc(meta) + '</span></span>'
                            + (r.link ? '<a href="' + esc(r.link) + '" target="_blank" rel="noopener" '
                                + 'class="kb-hint" onclick="event.stopPropagation()" '
                                + 'style="white-space:nowrap;">↗</a>' : '');
                        row.addEventListener('click', function () { Manager.viewIssue(r.key); });
                        box.appendChild(row);
                    });
                })
                .catch(function () { box.innerHTML = '<span class="kb-hint" style="color:var(--danger);">Suche fehlgeschlagen</span>'; });
        },

        viewIssue: function (key) {
            var view = $('jira-issue-view'); if (!view) return;
            view.style.display = '';
            if ($('jira-issue-title')) $('jira-issue-title').textContent = 'Lade…';
            if ($('jira-issue-text')) $('jira-issue-text').textContent = '';
            if ($('jira-issue-comments')) $('jira-issue-comments').innerHTML = '';
            fetch('/api/jira/issue?key=' + encodeURIComponent(key), { headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) {
                        if ($('jira-issue-title')) $('jira-issue-title').textContent = 'Fehler';
                        if ($('jira-issue-text')) $('jira-issue-text').textContent = (d && d.error) || 'Ticket konnte nicht geladen werden.';
                        return;
                    }
                    var dC = fmtDate(d.created), dU = fmtDate(d.updated);
                    var meta = [d.status, d.type, d.priority ? ('Prio ' + d.priority) : '',
                                d.assignee ? ('Bearbeiter: ' + d.assignee) : '',
                                dC ? ('Erstellt: ' + dC) : '',
                                dU ? ('Geändert: ' + dU) : ''].filter(Boolean).join(' · ');
                    if ($('jira-issue-title')) $('jira-issue-title').textContent = d.key + ' — ' + (d.summary || '');
                    if ($('jira-issue-meta')) $('jira-issue-meta').textContent = meta;
                    var link = $('jira-issue-link');
                    if (link) { if (d.link) { link.href = d.link; link.style.display = ''; } else { link.style.display = 'none'; } }
                    if ($('jira-issue-text')) $('jira-issue-text').textContent = d.description || '(keine Beschreibung)';
                    var cbox = $('jira-issue-comments');
                    if (cbox) {
                        var cs = d.comments || [];
                        cbox.innerHTML = cs.length ? ('<div class="kb-hint" style="margin:10px 0 4px;">💬 '
                            + cs.length + ' Kommentar(e):</div>') : '';
                        cs.forEach(function (cm) {
                            var el = document.createElement('div');
                            el.style.cssText = 'border-left:3px solid var(--accent);padding:4px 10px;margin:6px 0;'
                                + 'background:rgba(var(--accent-rgb),.06);border-radius:0 6px 6px 0;';
                            el.innerHTML = '<div style="font-weight:600;font-size:.82rem;">' + esc(cm.author || '?')
                                + '</div><div style="white-space:pre-wrap;font-size:.85rem;">' + esc(cm.body || '') + '</div>';
                            cbox.appendChild(el);
                        });
                    }
                })
                .catch(function () {
                    if ($('jira-issue-title')) $('jira-issue-title').textContent = 'Fehler';
                });
        }
    };

    window.JiraManager = Manager;
})();
