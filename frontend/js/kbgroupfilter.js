/* Jarvis – aufklappbarer Wissensgruppen-Filter für /chat und /support.
 *
 * Zeigt eine Checkbox-Liste aller Wissensgruppen (+ „ungruppiert"). Die Auswahl
 * bestimmt, aus welchen Gruppen Wissen genutzt wird. Default: ALLE ausgewählt.
 *
 * Persistiert werden die ABGEWÄHLTEN Gruppen pro Benutzer/Seite in localStorage
 * (nicht die ausgewählten) – so sind neu angelegte Gruppen automatisch aktiv.
 *
 * getSelection(): null = alle (kein Filter) · [] = keine · [ids] = nur diese.
 * Wird mit der Chat-/Support-Anfrage als `kb_groups` mitgeschickt.
 */
window.KbGroupFilter = (function () {
    'use strict';
    var UNGROUPED = 'ungrouped';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function who() { return localStorage.getItem('jarvis_user') || 'anon'; }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function t(k, d) { return (window.t && window.t(k)) || d; }

    var _styled = false;
    function injectStyle() {
        if (_styled) return; _styled = true;
        var css =
        '.kbgf-wrap{position:relative;display:inline-flex;flex:0 0 auto;}' +
        '.kbgf-btn{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:10px;' +
            'border:1px solid var(--border,rgba(255,255,255,.14));background:var(--bg-glass,rgba(255,255,255,.05));' +
            'color:var(--text-secondary,#94a3b8);font-size:.82rem;cursor:pointer;line-height:1;white-space:nowrap;}' +
        '.kbgf-btn:hover{color:var(--text-primary,#e2e8f0);border-color:rgba(var(--accent-rgb,155,89,182),.5);}' +
        '.kbgf-btn .kbgf-badge{font-size:.72rem;font-weight:700;padding:1px 7px;border-radius:999px;' +
            'background:rgba(var(--accent-rgb,155,89,182),.22);color:var(--text-primary,#e2e8f0);}' +
        '.kbgf-btn.kbgf-partial .kbgf-badge{background:rgba(245,158,11,.28);}' +
        '.kbgf-caret{transition:transform .15s ease;font-size:.7rem;}' +
        '.kbgf-btn[aria-expanded="true"] .kbgf-caret{transform:rotate(180deg);}' +
        '.kbgf-panel{position:absolute;z-index:10050;min-width:240px;max-width:320px;' +
            'background:var(--bg-elevated,var(--bg-glass,rgba(23,32,50,.98)));backdrop-filter:blur(12px);' +
            'border:1px solid var(--border,rgba(255,255,255,.14));border-radius:12px;padding:10px;' +
            'box-shadow:0 12px 40px rgba(0,0,0,.45);}' +
        '.kbgf-panel.kbgf-up{bottom:calc(100% + 8px);left:0;}' +
        '.kbgf-panel.kbgf-down{top:calc(100% + 8px);left:0;}' +
        '.kbgf-head{font-size:.76rem;color:var(--text-secondary,#94a3b8);margin:0 2px 8px;}' +
        '.kbgf-actions{display:flex;gap:6px;margin-bottom:8px;}' +
        '.kbgf-a{flex:1;padding:5px 8px;border-radius:8px;border:1px solid var(--border,rgba(255,255,255,.14));' +
            'background:transparent;color:var(--text-secondary,#94a3b8);font-size:.76rem;cursor:pointer;}' +
        '.kbgf-a:hover{color:var(--text-primary,#e2e8f0);border-color:rgba(var(--accent-rgb,155,89,182),.5);}' +
        '.kbgf-list{max-height:44vh;overflow-y:auto;display:flex;flex-direction:column;gap:2px;}' +
        '.kbgf-row{display:flex;align-items:center;gap:8px;padding:5px 6px;border-radius:8px;cursor:pointer;' +
            'font-size:.85rem;color:var(--text-primary,#e2e8f0);}' +
        '.kbgf-row:hover{background:rgba(255,255,255,.06);}' +
        '.kbgf-row input{flex:0 0 auto;cursor:pointer;}' +
        '.kbgf-dot{width:10px;height:10px;border-radius:50%;flex:0 0 auto;}' +
        '.kbgf-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
        '.kbgf-empty{padding:8px 6px;color:var(--text-secondary,#94a3b8);font-size:.82rem;}';
        var s = document.createElement('style');
        s.textContent = css;
        document.head.appendChild(s);
    }

    async function loadGroups() {
        if (window.KbGroups) {
            try {
                await window.KbGroups.load();
                return (window.KbGroups.all() || []).map(function (g) {
                    return { id: g.id, name: g.name, color: g.color };
                });
            } catch (e) { /* fällt unten auf Direkt-Fetch */ }
        }
        try {
            var r = await fetch('/api/knowledge/groups', { headers: { 'Authorization': 'Bearer ' + token() } });
            var d = await r.json();
            return ((d && d.groups) || []).map(function (g) { return { id: g.id, name: g.name, color: g.color }; });
        } catch (e) { return []; }
    }

    function mount(opts) {
        opts = opts || {};
        injectStyle();
        var anchor = opts.anchor;
        var place = opts.place || 'append';
        var direction = opts.direction || 'down';
        var storageKey = 'jarvis_kbfilter_off_' + (opts.key || 'default') + '_' + who();

        var _groups = [];
        var _off = loadOff();
        var _desired;          // programmatisch gesetzte Auswahl (null/[]/[ids]) o. undefined
        var _onChange = null;  // Callback bei Nutzer-Aenderung (fuer Sitzungs-Persistenz)

        function loadOff() {
            try { return new Set(JSON.parse(localStorage.getItem(storageKey) || '[]')); }
            catch (e) { return new Set(); }
        }
        function saveOff() {
            localStorage.setItem(storageKey, JSON.stringify(Array.from(_off)));
        }
        function entries() {
            return _groups.concat([{ id: UNGROUPED, name: t('kbfilter.ungrouped', 'ungruppiert'), color: '#94a3b8' }]);
        }
        // Programmatisch gesetzte Auswahl (aus einer Sitzung) auf _off anwenden.
        function applyDesired() {
            if (_desired === undefined) return;
            var all = entries();
            if (_desired === null) { _off = new Set(); }
            else if (Array.isArray(_desired) && _desired.length === 0) { _off = new Set(all.map(function (e) { return e.id; })); }
            else { var want = new Set(_desired); _off = new Set(all.filter(function (e) { return !want.has(e.id); }).map(function (e) { return e.id; })); }
            saveOff(); renderBadge(); if (!panel.hidden) renderPanel();
        }
        function fireChange() { _desired = undefined; if (_onChange) { try { _onChange(pub.getSelection()); } catch (e) {} } }

        var wrap = document.createElement('div');
        wrap.className = 'kbgf-wrap';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'kbgf-btn';
        btn.title = t('kbfilter.btn', 'Wissensgruppen');
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = '<span class="kbgf-label">' + esc(t('kbfilter.btn', 'Wissensgruppen')) +
            '</span><span class="kbgf-badge"></span><span class="kbgf-caret">▾</span>';
        var panel = document.createElement('div');
        panel.className = 'kbgf-panel ' + (direction === 'up' ? 'kbgf-up' : 'kbgf-down');
        panel.hidden = true;
        wrap.appendChild(btn);
        wrap.appendChild(panel);

        if (place === 'before' && anchor && anchor.parentNode) anchor.parentNode.insertBefore(wrap, anchor);
        else if (anchor) anchor.appendChild(wrap);

        function renderBadge() {
            var all = entries();
            var on = all.filter(function (e) { return !_off.has(e.id); }).length;
            var badge = btn.querySelector('.kbgf-badge');
            if (on >= all.length) { badge.textContent = t('kbfilter.all', 'alle'); btn.classList.remove('kbgf-partial'); }
            else { badge.textContent = on + '/' + all.length; btn.classList.add('kbgf-partial'); }
        }
        function renderPanel() {
            var all = entries();
            var rows = all.map(function (e) {
                var checked = _off.has(e.id) ? '' : ' checked';
                return '<label class="kbgf-row"><input type="checkbox" value="' + esc(e.id) + '"' + checked + '>' +
                    '<span class="kbgf-dot" style="background:' + esc(e.color) + '"></span>' +
                    '<span class="kbgf-name">' + esc(e.name) + '</span></label>';
            }).join('');
            panel.innerHTML =
                '<div class="kbgf-head">' + esc(t('kbfilter.title', 'Wissen nur aus diesen Gruppen verwenden')) + '</div>' +
                '<div class="kbgf-actions">' +
                    '<button type="button" class="kbgf-a" data-a="all">' + esc(t('kbfilter.select_all', 'Alle')) + '</button>' +
                    '<button type="button" class="kbgf-a" data-a="none">' + esc(t('kbfilter.select_none', 'Keine')) + '</button>' +
                '</div>' +
                '<div class="kbgf-list">' + (all.length ? rows : '<div class="kbgf-empty">' + esc(t('kbfilter.empty', 'Keine Gruppen angelegt.')) + '</div>') + '</div>';
            panel.querySelectorAll('input[type=checkbox]').forEach(function (cb) {
                cb.addEventListener('change', function () {
                    if (cb.checked) _off.delete(cb.value); else _off.add(cb.value);
                    saveOff(); renderBadge(); fireChange();
                });
            });
            panel.querySelectorAll('.kbgf-a').forEach(function (b) {
                b.addEventListener('click', function () {
                    if (b.dataset.a === 'all') _off = new Set();
                    else _off = new Set(all.map(function (e) { return e.id; }));
                    saveOff(); renderPanel(); renderBadge(); fireChange();
                });
            });
        }
        function openP() { panel.hidden = false; btn.setAttribute('aria-expanded', 'true'); renderPanel(); }
        function closeP() { panel.hidden = true; btn.setAttribute('aria-expanded', 'false'); }
        btn.addEventListener('click', function (e) { e.stopPropagation(); if (panel.hidden) openP(); else closeP(); });
        document.addEventListener('click', function (e) { if (!wrap.contains(e.target)) closeP(); });

        (async function () { _groups = await loadGroups(); applyDesired(); renderBadge(); if (!panel.hidden) renderPanel(); })();

        var pub = {
            el: wrap,
            getSelection: function () {
                var all = entries();
                var on = all.filter(function (e) { return !_off.has(e.id); });
                if (on.length >= all.length) return null;   // alle -> kein Filter
                if (on.length === 0) return [];              // keine -> kein Wissen
                return on.map(function (e) { return e.id; });
            },
            // Auswahl aus einer Sitzung setzen (null=alle, []=keine, [ids]=nur diese).
            setSelection: function (sel) { _desired = sel; applyDesired(); },
            // Callback bei Nutzer-Aenderung registrieren (fuer Sitzungs-Persistenz).
            onChange: function (cb) { _onChange = cb; },
            refresh: async function () {
                _groups = await loadGroups(); applyDesired(); renderBadge(); if (!panel.hidden) renderPanel();
            }
        };
        return pub;
    }

    return { mount: mount };
})();
