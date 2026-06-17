/* ═══════════════════════════════════════════════════════════════════
   Dark/Light-Theme – eigenstaendiger Umschalter
   ───────────────────────────────────────────────────────────────────
   Schaltet zwischen Dunkel (Default) und Hell um, indem die Klasse
   `light` auf <body> gesetzt wird. Die CSS-Dateien definieren das helle
   Farbschema unter `body.light`. Persistenz im localStorage-Schluessel
   `jarvis_theme` (seitenuebergreifend).

   Eingebunden in index.html und userchat.html. chat.html hat einen
   eigenen, kompatiblen Umschalter (chat.js) mit demselben Schluessel.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';
    var KEY = 'jarvis_theme';

    function setIcons(light) {
        document.querySelectorAll('.theme-icon-moon').forEach(function (e) {
            e.style.display = light ? 'none' : '';
        });
        document.querySelectorAll('.theme-icon-sun').forEach(function (e) {
            e.style.display = light ? '' : 'none';
        });
    }

    function apply(light) {
        if (document.body) document.body.classList.toggle('light', light);
        setIcons(light);
        // Branding (und andere) ueber den Theme-Wechsel informieren
        try { document.dispatchEvent(new CustomEvent('jarvis:themechange', { detail: { light: light } })); } catch (e) {}
    }

    function isLight() {
        return !!(document.body && document.body.classList.contains('light'));
    }

    var saved = localStorage.getItem(KEY);
    var light = saved ? (saved === 'light') : false; // Default: Dunkel

    function init() {
        apply(light);
        document.querySelectorAll('#btn-theme-toggle, .btn-theme-toggle').forEach(function (b) {
            if (b._themeBound) return;
            b._themeBound = true;
            b.addEventListener('click', function () {
                var l = !isLight();
                apply(l);
                try { localStorage.setItem(KEY, l ? 'light' : 'dark'); } catch (e) {}
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.applyTheme = apply;
})();
