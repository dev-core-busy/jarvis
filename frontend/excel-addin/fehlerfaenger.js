/* BSI H4 (CSP ohne Inline-Skript, 2026-10-04): bisher Inline-<script> in
   frontend/excel-addin/taskpane.html. Eine CSP mit script-src 'self' blockiert Inline-Skripte -
   deshalb hier als Datei, an DERSELBEN Stelle synchron eingebunden
   (kein defer/async): Zeitpunkt und Reihenfolge bleiben gleich. */
/* Faengt Fehler, die VOR oder WAEHREND des Startens auftreten – auch einen
   Syntaxfehler in excel.js, der sonst spurlos bliebe. Bewusst ganz oben (vor
   allen anderen Skripten der Seite). Frueher zusaetzlich inline, weil eine
   externe Datei selbst diejenige sein koennte, die nicht laedt - diesen einen
   Fall deckt die Datei nicht mehr ab (Preis der CSP ohne 'unsafe-inline',
   BSI H4). Das statische Hinweis-Markup in #xl-boot bleibt dann sichtbar. */
(function () {
    function aufklappen() {
        var d = document.getElementById('xl-boot-detail');
        if (d) d.classList.remove('hidden');
    }
    /* Ein bereits gemeldeter Grund wird NIE ueberschrieben – der erste ist der
       ursaechliche, spaetere Fehler sind meist seine Folge. Und der Wachhund
       unten darf ihn schon gar nicht mit Leere ersetzen; genau das hat er in
       der ersten Fassung getan, sodass die konkrete Zeile wieder verschwand. */
    function zeige(text) {
        try {
            aufklappen();
            var e = document.getElementById('xl-boot-err');
            if (e && !e.textContent) e.textContent = String(text || '').slice(0, 300);
        } catch (x) { }
    }
    /* `true` = Erfassungsphase, und das ist hier KEIN Detail: ein Skript oder
       Stylesheet, das gar nicht erst laedt, feuert sein `error` am ELEMENT und
       steigt NICHT bis zum Fenster auf. Ohne die Erfassungsphase bliebe genau
       der wahrscheinlichste Fall in einem abgeschotteten Netz unsichtbar –
       eine Datei, die der Arbeitsplatz nicht abrufen kann. */
    window.addEventListener('error', function (ev) {
        var z = ev && ev.target;
        if (z && (z.src || z.href)) {
            zeige('Nicht ladbar: ' + (z.src || z.href));
        } else {
            zeige((ev && ev.message) || 'Fehler beim Laden');
        }
    }, true);
    window.addEventListener('unhandledrejection', function (ev) {
        zeige((ev && ev.reason && ev.reason.message) || 'Fehler beim Laden');
    });
    /* Wachhund: kein Fehler, aber auch kein Fortschritt (haeufigster Fall –
       eine Ressource, die gar nicht erst antwortet). */
    setTimeout(function () {
        var b = document.getElementById('xl-boot');
        if (b && !b.classList.contains('hidden')) aufklappen();
    }, 9000);
})();
