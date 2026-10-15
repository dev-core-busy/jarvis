/* BSI H4, CSP ohne Inline-Skript (2026-10-04): Auf-/Zuklapp-Zustand der Unter-Container
   (details.sec-sub) im Sicherheits-Reiter merken.
   Bis hierher stand dieser Code als Inline-<script> in settings.html.
   Eine Content-Security-Policy mit script-src 'self' ohne 'unsafe-inline'
   fuehrt kein Inline-Skript aus – deshalb ausgelagert, Inhalt unveraendert.
   Eingebunden SYNCHRON an DERSELBEN Stelle der Seite wie vorher (kein
   defer/async): Zeitpunkt und Reihenfolge bleiben gleich, inklusive dessen,
   was das Skript zu diesem Zeitpunkt vom Dokument schon sieht. */
// Auf-/Zuklapp-Zustand der Unter-Container merken (localStorage).
// Default: alle geschlossen; gespeicherter Zustand gewinnt.
//
// WICHTIG – erst wenn das Dokument fertig geparst ist: dieses
// Skript steht MITTEN in der Seite und sah bisher nur die
// Unter-Container OBERHALB von sich. Weiter unten stehende
// (z.B. "Letzte Zugriffs-Verstöße" im Vorfalls-Abschnitt) gingen
// leer aus – ohne Fehlermeldung, sie merkten sich einfach nichts.
(function () {
    var KEY = 'jarvis_sec_sub_open';
    function init() {
        var saved = {};
        try { saved = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) {}
        document.querySelectorAll('details.sec-sub[data-sub]').forEach(function (d) {
            if (d._subBound) return;
            d._subBound = true;
            var k = d.getAttribute('data-sub');
            if (saved[k]) d.open = true;
            d.addEventListener('toggle', function () {
                saved[k] = d.open;
                try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
            });
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
