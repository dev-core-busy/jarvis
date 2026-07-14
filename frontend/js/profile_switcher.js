// ─────────────────────────────────────────────────────────────────────────
//  KI-Profil-Pulldown
//  Loest das fruehere Popup-Menue auf der Status-Pill ab. Rendert ein <select>
//  mit den fuer den Benutzer nutzbaren LLM-Profilen + einen dezenten
//  Erreichbarkeits-Punkt (gruen/gelb/rot) fuer das gewaehlte Profil.
//
//  mount(opts) -> { el, getSelected(), setSelected(id,{activate}), refresh() }
//    opts.anchor    Zielcontainer
//    opts.place     'append' (Default) | 'before'
//    opts.headers   ()=>({...})  Auth-Header
//    opts.onChange  (id)=>{}     nach erfolgreicher Aktivierung durch den Nutzer
// ─────────────────────────────────────────────────────────────────────────
(function () {
    'use strict';

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function tt(key, fallback) {
        if (window.t) { var v = window.t(key); if (v && v !== key) return v; }
        return fallback;
    }

    var _styled = false;
    function injectStyles() {
        if (_styled) return; _styled = true;
        var css = ''
            + '.llmps-wrap{display:inline-flex;align-items:center;gap:6px;flex:0 0 auto;}'
            + '.llmps-label{font-size:.82rem;color:var(--text-secondary,#94a3b8);white-space:nowrap;}'
            + '.llmps-select{max-width:220px;padding:6px 10px;border-radius:10px;font:inherit;font-size:.82rem;'
            + 'cursor:pointer;line-height:1;color:var(--text-primary,#e2e8f0);'
            + 'border:1px solid var(--border,rgba(255,255,255,.14));background:var(--bg-glass,rgba(255,255,255,.05));}'
            + '.llmps-select:hover{border-color:rgba(var(--accent-rgb,155,89,182),.5);}'
            + '.llmps-select:disabled{opacity:.55;cursor:default;}';
        var s = document.createElement('style');
        s.textContent = css;
        document.head.appendChild(s);
    }

    function mount(opts) {
        opts = opts || {};
        injectStyles();
        var headers = function () { return (opts.headers && opts.headers()) || {}; };
        var st = { profiles: [], activeId: '' };

        var wrap = document.createElement('div');
        wrap.className = 'llmps-wrap';
        var label = document.createElement('span');
        label.className = 'llmps-label';
        label.textContent = tt('profile.pulldown_label', 'KI-Profil');
        label.setAttribute('data-i18n', 'profile.pulldown_label');
        var sel = document.createElement('select');
        sel.className = 'llmps-select';
        sel.title = tt('profile.pulldown_label', 'KI-Profil');
        wrap.appendChild(label);
        wrap.appendChild(sel);

        var anchor = opts.anchor;
        if (opts.place === 'before' && anchor && anchor.parentNode) anchor.parentNode.insertBefore(wrap, anchor);
        else if (anchor) anchor.appendChild(wrap);

        function renderOptions() {
            sel.innerHTML = st.profiles.map(function (p) {
                return '<option value="' + esc(p.id) + '"' + (p.id === st.activeId ? ' selected' : '') + '>' + esc(p.name) + '</option>';
            }).join('');
            sel.value = st.activeId;
            // Nur ein Profil -> keine Auswahl noetig
            sel.disabled = st.profiles.length < 2;
            wrap.style.display = st.profiles.length ? '' : 'none';
        }
        function activate(id) {
            return fetch('/api/llm/profiles/' + encodeURIComponent(id) + '/activate',
                { method: 'POST', headers: headers() })
                .then(function (r) { return r.json(); })
                .then(function (d) { return !!(d && d.ok); })
                .catch(function () { return false; });
        }

        sel.addEventListener('change', function () {
            var id = sel.value;
            activate(id).then(function (ok) {
                if (ok) { st.activeId = id; if (opts.onChange) opts.onChange(id); }
                else { sel.value = st.activeId; window.alert(tt('chat.switch_failed', 'Profilwechsel fehlgeschlagen')); }
            });
        });

        function load() {
            return fetch('/api/llm/profiles', { headers: headers() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    st.profiles = (d && d.profiles) || [];
                    st.activeId = (d && d.active_id) || (st.profiles[0] && st.profiles[0].id) || '';
                    renderOptions();
                })
                .catch(function () { wrap.style.display = 'none'; });
        }
        load();

        return {
            el: wrap,
            getSelected: function () { return sel.value; },
            // Auswahl setzen; mit {activate:true} auch serverseitig aktivieren.
            setSelected: function (id, o) {
                o = o || {};
                if (!id || !st.profiles.some(function (p) { return p.id === id; })) return;
                sel.value = id; st.activeId = id;
                if (o.activate) activate(id);
            },
            refresh: load
        };
    }

    window.ProfileSwitcher = { mount: mount };
})();
