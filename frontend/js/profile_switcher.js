// ─────────────────────────────────────────────────────────────────────────
//  Profil-Umschalter (LLM-Status-Pill)
//  Gemeinsames Modul fuer alle vier Frontends (/, /chat, /support, /userchat).
//  Klick auf die Status-Pill oeffnet ein Menue mit allen fuer den Benutzer
//  nutzbaren KI-Profilen; ein rot/gruen-Punkt zeigt die Erreichbarkeit.
//  Selbst-enthaltend (eigenes CSS wird injiziert) – keine Abhaengigkeit zu
//  chat.css o.ae., damit es ueberall gleich aussieht.
// ─────────────────────────────────────────────────────────────────────────
(function () {
    'use strict';

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    // i18n mit Fallback: nutzt window.t, wenn ein echter Treffer vorliegt.
    function tt(key, fallback) {
        if (window.t) { var v = window.t(key); if (v && v !== key) return v; }
        return fallback;
    }

    var _stylesInjected = false;
    function injectStyles() {
        if (_stylesInjected) return;
        _stylesInjected = true;
        var css = ''
            + '.llm-pop{position:fixed;z-index:100000;min-width:220px;max-width:340px;'
            + 'background:var(--bg-glass,rgba(30,32,40,.98));border:1px solid var(--border,rgba(255,255,255,.14));'
            + 'border-radius:12px;box-shadow:0 12px 34px rgba(0,0,0,.45);padding:6px;'
            + 'backdrop-filter:blur(12px);font-size:.9rem;}'
            + '.llm-pop-head{padding:6px 10px 8px;font-size:.72rem;letter-spacing:.04em;text-transform:uppercase;'
            + 'color:var(--text-secondary,#9aa0ad);}'
            + '.llm-pop-item{display:flex;align-items:center;gap:9px;width:100%;text-align:left;'
            + 'background:transparent;border:0;color:var(--text-primary,#f0f1f4);padding:8px 10px;'
            + 'border-radius:8px;cursor:pointer;font:inherit;line-height:1.2;}'
            + '.llm-pop-item:hover{background:rgba(var(--fg-rgb,255,255,255),.08);}'
            + '.llm-pop-item.active{background:rgba(var(--accent-rgb,155,89,182),.16);}'
            + '.llm-pop-check{width:14px;flex:0 0 14px;color:var(--accent,#9B59B6);font-weight:700;}'
            + '.llm-pop-name{flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}'
            + '.llm-pop-reach{width:9px;height:9px;flex:0 0 9px;border-radius:50%;background:#7b7f88;}'
            + '.llm-pop-reach.ps-ok{background:var(--success,#2ecc71);box-shadow:0 0 6px rgba(var(--success-rgb,46,204,113),.7);}'
            + '.llm-pop-reach.ps-degraded{background:var(--warning,#e0a92e);box-shadow:0 0 6px rgba(var(--warning-rgb,224,169,46),.6);}'
            + '.llm-pop-reach.ps-down{background:var(--danger,#e05b5b);box-shadow:0 0 6px rgba(var(--danger-rgb,224,91,91),.6);}'
            + '.llm-pop-reach.ps-loading{background:#7b7f88;animation:llmPopPulse 1s ease-in-out infinite;}'
            + '@keyframes llmPopPulse{0%,100%{opacity:.35}50%{opacity:1}}';
        var st = document.createElement('style');
        st.textContent = css;
        document.head.appendChild(st);
    }

    window.ProfileSwitcher = {
        // opts: { dotId, headers:()=>({}), onSwitched:(name)=>{} }
        attach: function (opts) {
            injectStyles();
            var dot = document.getElementById(opts.dotId);
            if (!dot) return;
            var headers = function () { return (opts.headers && opts.headers()) || {}; };
            var st = { profiles: [], activeId: '', pop: null, reach: {} };

            function closePop() {
                if (st.pop) { st.pop.remove(); st.pop = null; document.removeEventListener('click', closePop); }
            }
            function reachClass(r) {
                if (!r) return 'ps-loading';
                if (r.status === 'ok') return 'ps-ok';
                if (r.status === 'degraded') return 'ps-degraded';
                return 'ps-down';
            }
            function reachTitle(r) {
                if (!r) return tt('profile.reach_checking', 'Erreichbarkeit wird geprüft …');
                if (r.status === 'ok') return tt('profile.reach_ok', 'Erreichbar');
                if (r.status === 'degraded') return tt('profile.reach_degraded', 'Erreichbar (Modell fehlt)');
                return tt('profile.reach_down', 'Nicht erreichbar');
            }
            function renderReachDots() {
                if (!st.pop) return;
                st.pop.querySelectorAll('.llm-pop-item').forEach(function (btn) {
                    var d = btn.querySelector('.llm-pop-reach');
                    var r = st.reach[btn.dataset.id];
                    d.className = 'llm-pop-reach ' + reachClass(r);
                    d.title = reachTitle(r);
                });
            }
            function loadReach() {
                // graue Ladepunkte -> dann echter Zustand
                renderReachDots();
                fetch('/api/llm/profiles/reachability', { headers: headers() })
                    .then(function (r) { return r.json(); })
                    .then(function (d) { if (d && d.ok) { st.reach = d.reachability || {}; renderReachDots(); } })
                    .catch(function () { /* Punkte bleiben grau */ });
            }
            function openPop() {
                if (st.pop) { closePop(); return; }
                var pop = document.createElement('div');
                pop.className = 'llm-pop';
                pop.innerHTML = '<div class="llm-pop-head">' + esc(tt('chat.switch_profile', 'KI-Profil wechseln')) + '</div>'
                    + st.profiles.map(function (p) {
                        return '<button type="button" class="llm-pop-item' + (p.id === st.activeId ? ' active' : '') + '" data-id="' + esc(p.id) + '">'
                            + '<span class="llm-pop-reach ps-loading"></span>'
                            + '<span class="llm-pop-check">' + (p.id === st.activeId ? '✓' : '') + '</span>'
                            + '<span class="llm-pop-name">' + esc(p.name) + '</span></button>';
                    }).join('');
                document.body.appendChild(pop);
                var rect = dot.getBoundingClientRect();
                pop.style.top = (rect.bottom + 6) + 'px';
                pop.style.left = Math.max(8, Math.min(rect.left - 4, window.innerWidth - pop.offsetWidth - 8)) + 'px';
                st.pop = pop;
                pop.querySelectorAll('.llm-pop-item').forEach(function (btn) {
                    btn.addEventListener('click', function (e) { e.stopPropagation(); doSwitch(btn.dataset.id); });
                });
                setTimeout(function () { document.addEventListener('click', closePop); }, 0);
                loadReach();
            }
            function doSwitch(id) {
                if (id === st.activeId) { closePop(); return; }
                fetch('/api/llm/profiles/' + encodeURIComponent(id) + '/activate',
                    { method: 'POST', headers: headers() })
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d && d.ok) {
                            st.activeId = d.active_id || id;
                            var p = st.profiles.find(function (x) { return x.id === st.activeId; });
                            if (opts.onSwitched) opts.onSwitched(p ? p.name : '');
                        } else {
                            window.alert((d && d.error) || tt('chat.switch_failed', 'Profilwechsel fehlgeschlagen'));
                        }
                    })
                    .catch(function () { window.alert(tt('chat.switch_failed', 'Profilwechsel fehlgeschlagen')); })
                    .then(function () { closePop(); });
            }

            fetch('/api/llm/profiles', { headers: headers() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    st.profiles = (d && d.profiles) || [];
                    st.activeId = (d && d.active_id) || '';
                    if (st.profiles.length < 2) return;   // nichts zu wechseln
                    dot.style.cursor = 'pointer';
                    if (!dot.title) dot.title = tt('chat.switch_profile', 'KI-Profil wechseln');
                    if (!dot._psWired) {
                        dot._psWired = true;
                        dot.addEventListener('click', function (e) { e.stopPropagation(); openPop(); });
                    }
                })
                .catch(function () { /* Pill bleibt reiner Status */ });
        }
    };
})();
