/* Jarvis – Auswahl der SQL-Schemata (SQL-Assistent) fuer /chat.
 *
 * Steht in der Eingabeleiste NEBEN dem Wissensgruppen-Filter und bestimmt, auf
 * welche Datenbankschemata die SQL-Werkzeuge in diesem Chat zugreifen.
 *
 * Vorgabe ist KEIN Schema (Festlegung des Betreibers 2026-11-07): ohne Auswahl
 * bekommt der Lauf die SQL-Werkzeuge gar nicht erst angeboten. Darum wird hier
 * – anders als beim Wissensgruppen-Filter – die AUSWAHL gespeichert, nicht die
 * Abwahl: ein neu angelegtes Schema ist NICHT von selbst dabei.
 *
 * Sichtbar nur fuer Benutzer, die fuer den SQL-Assistenten freigegeben sind –
 * entschieden wird an /api/sql/status (dieselbe Schranke wie die Werkzeuge):
 * antwortet der Endpunkt nicht mit ok, bleibt das Bedienelement verborgen.
 *
 * getSelection(): immer eine Liste von Schema-Kennungen (leer = kein Schema).
 * Wird mit der Chat-Anfrage als `sql_schemata` mitgeschickt.
 */
window.SqlSchemaFilter = (function () {
    'use strict';

    function token() { return window.JarvisSitzung.token(); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function t(k, d) { return (window.t && window.t(k)) || d; }

    // Schemata, die der Benutzer waehlen darf. null = nicht freigegeben oder
    // keine Auskunft (dann bleibt das Bedienelement verborgen).
    async function laden() {
        try {
            var r = await fetch('/api/sql/status', { headers: { 'Authorization': 'Bearer ' + token() } });
            if (!r.ok) return null;
            var d = await r.json();
            if (!d || !d.ok) return null;
            return (d.schemata || []).map(function (s) {
                return { id: s.id, name: s.name, tabellen: s.tabellen || 0 };
            });
        } catch (e) { return null; }
    }

    var _neuzeichnen = [];
    try {
        window.addEventListener('jarvis-lang-changed', function () {
            _neuzeichnen.forEach(function (fn) { try { fn(); } catch (e) {} });
        });
    } catch (e) { /* aeltere Umgebung ohne Ereignis */ }

    function mount(opts) {
        opts = opts || {};
        var anchor = opts.anchor;
        var direction = opts.direction || 'down';

        var _schemata = [];
        var _an = new Set();     // gewaehlte Kennungen
        var _onChange = null;

        var wrap = document.createElement('div');
        wrap.className = 'sqsf-wrap';
        wrap.hidden = true;      // erst nach der Auskunft sichtbar
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'sqsf-btn';
        btn.setAttribute('aria-expanded', 'false');
        btn.setAttribute('data-i18n-title', 'sqlfilter.btn_title');
        btn.title = t('sqlfilter.btn_title', 'Datenbankschemata für SQL-Fragen in diesem Chat');
        btn.innerHTML = '<span class="sqsf-label" data-i18n="sqlfilter.btn">' + esc(t('sqlfilter.btn', 'SQL-Schema')) +
            '</span><span class="sqsf-badge"></span><span class="sqsf-caret">▾</span>';
        var panel = document.createElement('div');
        panel.className = 'sqsf-panel ' + (direction === 'up' ? 'sqsf-up' : 'sqsf-down');
        panel.hidden = true;
        wrap.appendChild(btn);
        wrap.appendChild(panel);
        if (anchor) anchor.appendChild(wrap);

        // Nur Kennungen, die es gibt – ein geloeschtes Schema in einer
        // gespeicherten Auswahl faellt still weg (das Backend schneidet ebenso).
        function bereinigen() {
            var ids = new Set(_schemata.map(function (s) { return s.id; }));
            _an = new Set(Array.from(_an).filter(function (x) { return ids.has(x); }));
        }
        function renderBadge() {
            var badge = btn.querySelector('.sqsf-badge');
            var n = _an.size;
            // Zustand als TEXT, nicht nur als Farbe ("aus" gegen Anzahl).
            if (!n) { badge.textContent = t('sqlfilter.off', 'aus'); btn.classList.remove('sqsf-aktiv'); }
            else { badge.textContent = n + '/' + _schemata.length; btn.classList.add('sqsf-aktiv'); }
        }
        function renderPanel() {
            var rows = _schemata.map(function (s) {
                return '<label class="sqsf-row"><input type="checkbox" value="' + esc(s.id) + '"' +
                    (_an.has(s.id) ? ' checked' : '') + '>' +
                    '<span class="sqsf-name">' + esc(s.name) + '</span>' +
                    '<span class="sqsf-zahl">' + esc(String(s.tabellen)) + ' ' + esc(t('sqlfilter.tables', 'Tabellen')) + '</span></label>';
            }).join('');
            panel.innerHTML =
                '<div class="sqsf-head">' + esc(t('sqlfilter.title', 'SQL-Fragen in diesem Chat beziehen sich auf diese Schemata')) + '</div>' +
                '<div class="sqsf-list">' + (_schemata.length ? rows :
                    '<div class="sqsf-empty">' + esc(t('sqlfilter.empty', 'Es ist noch kein Schema angelegt.')) + '</div>') + '</div>' +
                (_schemata.length ? '<button type="button" class="sqsf-a" data-a="none">' +
                    esc(t('sqlfilter.none', 'Kein Schema')) + '</button>' : '');
            panel.querySelectorAll('input[type=checkbox]').forEach(function (cb) {
                cb.addEventListener('change', function () {
                    if (cb.checked) _an.add(cb.value); else _an.delete(cb.value);
                    renderBadge(); fire();
                });
            });
            var keins = panel.querySelector('.sqsf-a');
            if (keins) keins.addEventListener('click', function () {
                _an = new Set(); renderPanel(); renderBadge(); fire();
            });
        }
        function fire() { if (_onChange) { try { _onChange(pub.getSelection()); } catch (e) {} } }
        function openP() { panel.hidden = false; btn.setAttribute('aria-expanded', 'true'); renderPanel(); }
        function closeP() { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); }
        btn.addEventListener('click', function (e) { e.stopPropagation(); if (panel.hidden) openP(); else closeP(); });
        document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) closeP(); });
        _neuzeichnen.push(function () { renderBadge(); if (!panel.hidden) renderPanel(); });

        var _gewuenscht = null;   // vor dem Laden gesetzte Auswahl
        async function neuLaden() {
            var liste = await laden();
            if (liste === null) { wrap.hidden = true; _schemata = []; _an = new Set(); return; }
            _schemata = liste;
            if (_gewuenscht) { _an = new Set(_gewuenscht); _gewuenscht = null; }
            bereinigen();
            wrap.hidden = false;
            renderBadge();
            if (!panel.hidden) renderPanel();
        }
        neuLaden();

        var pub = {
            el: wrap,
            getSelection: function () { return Array.from(_an); },
            // Auswahl einer Sitzung setzen ([] oder null = kein Schema).
            setSelection: function (sel) {
                var liste = Array.isArray(sel) ? sel.filter(function (x) { return typeof x === 'string'; }) : [];
                if (!_schemata.length && wrap.hidden) { _gewuenscht = liste; _an = new Set(liste); return; }
                _an = new Set(liste); bereinigen(); renderBadge(); if (!panel.hidden) renderPanel();
            },
            onChange: function (cb) { _onChange = cb; },
            refresh: neuLaden
        };
        return pub;
    }

    return { mount: mount };
})();
