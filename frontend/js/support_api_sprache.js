/* BSI H4 (CSP ohne Inline-Skript, 2026-10-04): bisher Inline-<script> am Ende
   von frontend/support-api.html (oeffentliche Doku-Seite /support-api).
   An DERSELBEN Stelle synchron eingebunden, Verhalten unveraendert. */
(function () {
    function apply(l) {
        document.documentElement.setAttribute('data-lang', l);
        document.title = (l === 'en') ? 'Jarvis Support API – REST Documentation'
                                      : 'Jarvis Support-API – REST-Dokumentation';
        document.querySelectorAll('.lang-sw button').forEach(function (b) {
            b.classList.toggle('active', b.getAttribute('data-lang') === l);
        });
    }
    window.__setDocLang = function (l) {
        try { localStorage.setItem('jarvis_lang', l); } catch (e) {}
        apply(l);
    };
    /* BSI H4 (CSP ohne Inline-Skript, 2026-10-04): die Knoepfe DE/EN riefen
       __setDocLang frueher per onclick-Attribut. Jetzt Listener; die Sprache
       steht schon im data-lang des Knopfs. Die Knoepfe liegen OBERHALB dieses
       Skripts (Seitenanfang) - beim synchronen Laden hier sind sie also da. */
    document.querySelectorAll('.lang-sw button[data-lang]').forEach(function (b) {
        b.addEventListener('click', function () {
            window.__setDocLang(b.getAttribute('data-lang'));
        });
    });
    var cur = 'de';
    try { cur = localStorage.getItem('jarvis_lang') || 'de'; } catch (e) {}
    apply(cur);
})();
