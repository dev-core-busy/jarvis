/* Das Marken-Logo oben links fuehrt aufs Portal – zusaetzlich zum Haus-Symbol.
 *
 * VORGABE DES NUTZERS (2026-08-26): "zusaetzlich zum Klick auf das Home Symbol
 * soll auch durch Klick auf das 'J' / 'nx' Symbol oben links auf die
 * Portalseite gewechselt werden."
 *
 * WARUM EIN GEMEINSAMES MODUL UND NICHT ZEHN `<a>`-HUELLEN: das Logo steht auf
 * dreizehn Seiten, und die Umhuellung waere zehnmal dieselbe Handarbeit. Genau
 * dieses Muster hat die CPU-Anzeige gekostet – sie lag in VIER Fassungen vor
 * und fehlte deshalb auf sechs Seiten. Hier kommt der naechste Bereich von
 * selbst dazu.
 *
 * DIE SCHRANKE IST DER VORHANDENE WEG, NICHT EINE LISTE: verlinkt wird nur,
 * wenn die Seite SELBST schon einen Weg zum Portal hat (das Haus-Symbol,
 * erkennbar an `data-i18n-title="nav.home"`). Damit bleiben ohne jede Pflege
 * aussen vor:
 *   - `/portal` selbst (ein Link auf sich ist kein Weg),
 *   - die beiden Office-Aufgabenfenster (`/addin`, `/excel-addin`) – dort waere
 *     eine Navigation aufs Portal ein Fehler: das Fenster laeuft IN Outlook
 *     bzw. Excel, und das Portal gehoert nicht in ein Aufgabenfenster.
 * Ein Bereich ohne Haus-Symbol bekommt also auch am Logo keins – fail-safe in
 * die richtige Richtung.
 *
 * GEKLICKT WIRD DAS VORHANDENE BEDIENELEMENT, nicht `location.href`. Das ist
 * kein Umweg, sondern der Punkt: `/tracks` benutzt bewusst
 * `location.replace()` (kein Eintrag in der Verlaufsliste), andere ein
 * gewoehnliches `href`. Wer hier selbst navigiert, verliert diesen Unterschied
 * und muss ihn beim naechsten Bereich erneut nachbauen.
 */
(function () {
    'use strict';

    /* Der vorhandene Weg zum Portal auf DIESER Seite – oder null. */
    function hausSymbol() {
        // EIN Selektor fuer alle Bauformen: `/chat`, `/sap`, `/wissen` & Co.
        // benutzen ein `<a href="/portal">`, `/claude`, `/tracks` und `/email`
        // einen `<button>` mit eigenem Handler. Beide tragen dieselbe
        // Beschriftung `nav.home` – die ist damit das verlaessliche Merkmal,
        // und eine Id-Liste (`cs-portal-btn`, `st-portal-btn`, …) muesste bei
        // jedem neuen Bereich nachgepflegt werden.
        //
        // ⚠ `:not(.topbar-avatar)` IST PFLICHT, und zwar wegen dieser Funktion
        // selbst: `verdrahten()` setzt `data-i18n-title="nav.home"` AUF DAS
        // LOGO (damit die Beschriftung dem Sprachwechsel folgt). Ohne den
        // Ausschluss findet der Selektor also sein eigenes Werk wieder – steht
        // das Logo im Markup vor dem Haus-Symbol, klickt der Handler auf das
        // Logo, und der Klick tut GAR NICHTS. Vom Test gefunden, nicht vom
        // Lesen.
        return document.querySelector('[data-i18n-title="nav.home"]:not(.topbar-avatar)');
    }

    function verdrahten() {
        var ziel = hausSymbol();
        if (!ziel) return;                       // kein Weg zum Portal: nichts tun
        var logos = document.querySelectorAll('.topbar-avatar');
        if (!logos.length) return;
        Array.prototype.forEach.call(logos, function (logo) {
            if (logo.dataset.jvLogoHome) return; // idempotent (Sprachwechsel, Neuaufbau)
            logo.dataset.jvLogoHome = '1';
            logo.classList.add('jv-logo-home');
            // Beschriftung ueber die VORHANDENEN i18n-Schluessel: ein eigener
            // Text waere eine zweite Fassung derselben Aussage und muesste bei
            // jeder Sprachpflege mitgezogen werden.
            logo.setAttribute('data-i18n-title', 'nav.home');
            logo.setAttribute('data-i18n-aria', 'nav.home');
            logo.setAttribute('title', ziel.getAttribute('title') || 'Startseite');
            logo.setAttribute('aria-label', logo.getAttribute('title'));
            // Bedienbar auch ohne Maus: ein `<div>` ist von sich aus weder
            // fokussierbar noch als Knopf erkennbar.
            logo.setAttribute('role', 'button');
            if (!logo.hasAttribute('tabindex')) logo.setAttribute('tabindex', '0');
            logo.addEventListener('click', function (ev) {
                ev.preventDefault();
                var z = hausSymbol();            // beim Klick neu suchen: die
                if (z) z.click();                // Leiste kann neu gebaut sein
            });
            logo.addEventListener('keydown', function (ev) {
                if (ev.key !== 'Enter' && ev.key !== ' ' && ev.key !== 'Spacebar') return;
                ev.preventDefault();
                var z = hausSymbol();
                if (z) z.click();
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', verdrahten);
    } else {
        verdrahten();
    }
    // Nach einem Sprachwechsel wird auf manchen Seiten die Leiste neu gebaut –
    // dann muss ein frisch erzeugtes Logo wieder verdrahtet werden. Der Merker
    // `jvLogoHome` haelt das idempotent.
    window.addEventListener('jarvis-lang-changed', verdrahten);
})();
