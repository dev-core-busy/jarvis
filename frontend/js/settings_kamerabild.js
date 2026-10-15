/* BSI H4, CSP ohne Inline-Skript (2026-10-04): Live-Bild der Kamera im Vision-Reiter
   (alle 500 ms neu laden, nur solange der Reiter offen ist).
   Bis hierher stand dieser Code als Inline-<script> in settings.html.
   Eine Content-Security-Policy mit script-src 'self' ohne 'unsafe-inline'
   fuehrt kein Inline-Skript aus – deshalb ausgelagert, Inhalt unveraendert.
   Eingebunden SYNCHRON an DERSELBEN Stelle der Seite wie vorher (kein
   defer/async): Zeitpunkt und Reihenfolge bleiben gleich, inklusive dessen,
   was das Skript zu diesem Zeitpunkt vom Dokument schon sieht. */
(function(){
    setInterval(function(){
        // Hintergrund-Tab: kein Bild holen (Code-Review 2026-10-07)
        if (document.hidden) return;
        var tab = document.getElementById('settings-tab-vision');
        if (!tab || tab.style.display === 'none' || !tab.classList.contains('active')) return;
        var img = document.getElementById('vis-feed-img');
        var tok = window.JarvisSitzung.token();
        if (img && tok) {
            img.src = '/api/vision/snapshot?t=' + Date.now() + '&token=' + encodeURIComponent(
                (window.JarvisDL && window.JarvisDL.schluessel()) || tok);
        }
    }, 500);
})();
