/* Seite maximieren – der Knopf ⛶ oben rechts UEBER den Kacheln.
 *
 * Vorbild /wissen (Vorgabe 2026-09-27/28, seit 2026-09-28 nutzt /wissen
 * selbst diesen Baustein): der Knopf sitzt AUSSERHALB der
 * Container ganz oben in der Seite; maximiert faellt die Breiten-Deckelung
 * des Inhaltsbereichs weg und ALLE Kacheln nutzen die volle Fensterbreite.
 * Kein Vollbild einer einzelnen Kachel mehr (das war die Bauform bis
 * 2026-09-27 in /feedback und /tracks).
 *
 * Einbindung je Seite:
 *   - der gedeckelte Inhaltsbereich traegt `data-jv-breit` (die Regel
 *     `body.jv-breit [data-jv-breit]` steht in theme.css),
 *   - der Knopf `#jv-max` mit `data-seite="<name>"` steht davor bzw. als
 *     erstes Kind – NIE in einem Element, das per innerHTML neu geschrieben
 *     wird (Lehre aus /wissen: renderScope() loeschte ihn).
 *
 * Der Zustand wird JE BROWSER UND SEITE gemerkt (wie /wissen, dritte
 * Fassung). Jeder Speicherzugriff im try: privates Fenster / gesperrter
 * Speicher = einfach nicht gemerkt, kein Fehler.
 *
 * Wer beim Umschalten nachmessen muss (/feedback: Antwortfelder mit fester
 * px-Hoehe), hoert auf das Ereignis `jarvis-breit` am window.
 *
 * KEIN Escape-Kuerzel: die Seite ist kein Overlay, und Escape schliesst auf
 * diesen Seiten Dialoge – das verkleinerte sonst nebenbei die Seite.
 */
(function () {
    'use strict';

    function T(k, rueckfall) {
        var v = window.t ? window.t(k) : k;
        return (v && v !== k) ? v : rueckfall;
    }

    // `data-speicher` nur fuer BESTEHENDE Schluessel: /wissen merkte seinen
    // Zustand schon vor diesem Baustein unter `jarvis_wissen_breit` – ein
    // neuer Name haette jedem Benutzer die gemerkte Breite genommen.
    function schluessel(b) {
        return b.getAttribute('data-speicher')
            || 'jarvis_breit_' + (b.getAttribute('data-seite') || 'seite');
    }

    function setzen(an) {
        document.body.classList.toggle('jv-breit', !!an);
        var b = document.getElementById('jv-max');
        if (b) {
            // DIESELBEN ZEICHEN wie /wissen und der Einstellungs-Dialog:
            // ⛶ maximieren, 🗗 verkleinern (ausdrueckliche Ausnahme von der
            // Emoji-Regel, Vorgabe 2026-08-18).
            b.innerHTML = an ? '&#128471;' : '&#9974;';
            b.classList.toggle('active', !!an);
            b.setAttribute('aria-pressed', an ? 'true' : 'false');
            var k = an ? 'common.minimize' : 'common.maximize';
            // Die data-i18n-*-Attribute wandern mit, sonst holt der naechste
            // Sprachwechsel den Text des ANDEREN Zustands zurueck.
            b.setAttribute('data-i18n-title', k);
            b.setAttribute('data-i18n-aria', k);
            var txt = T(k, an ? 'Verkleinern' : 'Maximieren');
            b.title = txt;
            b.setAttribute('aria-label', txt);
        }
        try {
            window.dispatchEvent(new CustomEvent('jarvis-breit', { detail: { an: !!an } }));
        } catch (e) { /* sehr alter Browser: niemand hoert zu */ }
    }

    function init() {
        var b = document.getElementById('jv-max');
        if (!b || b._jvGebunden) return;
        b._jvGebunden = true;
        var gemerkt = null;
        try { gemerkt = localStorage.getItem(schluessel(b)); } catch (e) { }
        if (gemerkt === '1') setzen(true);
        b.addEventListener('click', function (ev) {
            ev.preventDefault();
            var an = !document.body.classList.contains('jv-breit');
            setzen(an);
            try { localStorage.setItem(schluessel(b), an ? '1' : '0'); } catch (e) { }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.jarvisSeiteBreit = { init: init, setzen: setzen };
})();
