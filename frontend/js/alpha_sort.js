/* ═══════════════════════════════════════════════════════════════════════
   Alphabetische Reihenfolge: Einstellungs-Reiter und Portal-Kacheln
   ───────────────────────────────────────────────────────────────────────
   VORGABE: die Reiter unter /settings und die Kacheln unter /portal stehen
   alphabetisch; die Marken-Animation (Video) bleibt IMMER am Ende.

   ⚠ WARUM ZUR LAUFZEIT UND NICHT IM MARKUP SORTIERT WIRD
   Die alphabetische Reihenfolge haengt an der ANGEZEIGTEN Beschriftung, und
   die ist sprachabhaengig. Gemessen an den echten Texten:
       Anweisungen (DE) ↔ Instructions (EN)
       KI & System      ↔ AI & System
       Wissen           ↔ Knowledge
       Sicherheit       ↔ Security
       Kundenverwaltung ↔ Customer Mgmt
   Eine feste Reihenfolge im HTML waere damit in genau einer der beiden
   Sprachen falsch – und niemand wuerde es merken, weil sie in der anderen
   stimmt. Deshalb wird nach `textContent` sortiert, und zwar bei JEDEM
   `jarvis-lang-changed`: dieses Ereignis feuert `applyLang()` auch beim
   ersten Aufbau, es gibt also keinen zweiten Einstiegspunkt zu pflegen.

   ── DIE REGEL STEHT IM MARKUP, NICHT IN EINER LISTE HIER ────────────────
   Was am Ende bleiben soll, traegt `data-sort-last`. Eine Namensliste in
   diesem Modul waere die zweite Wahrheit neben dem Markup und liefe beim
   naechsten Element auseinander; so bekommt ein kuenftiges Element seine
   Sonderstellung dort, wo es selbst steht.

   ── ES WIRD SO WENIG BEWEGT WIE MOEGLICH ────────────────────────────────
   Nicht "alles neu anhaengen": ein `<video>`, das aus dem Dokument genommen
   und wieder eingesetzt wird, faengt von vorn an zu laden. Steht die
   Reihenfolge schon, passiert gar nichts (der haeufige Fall – ein zweiter
   `applyLang()`-Lauf in derselben Sprache aendert keine Beschriftung).

   Die HTML-Kommentare an den Kacheln wandern dabei NICHT mit; sie bleiben in
   der Quelldatei bei ihrer Kachel stehen (nur der gerenderte Baum wird
   umgestellt) und rendern ohnehin nichts.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    /**
     * Vergleichsfunktion fuer die AKTUELLE Sprache.
     * `numeric` – "Agent 2" vor "Agent 10".
     * `sensitivity: 'base'` – Gross/Klein und Akzente entscheiden nicht.
     * `ignorePunctuation` – "E-Mail" zaehlt wie "EMail", "Claude-Bridge" wie
     *   "ClaudeBridge"; sonst entscheidet das Trennzeichen darueber, wo ein
     *   Eintrag landet, und das ist fuer den Leser nicht nachvollziehbar.
     */
    function vergleicher() {
        var lang = window._lang || 'de';
        try {
            return new Intl.Collator(lang, {
                numeric: true, sensitivity: 'base', ignorePunctuation: true
            }).compare;
        } catch (e) {
            // Ohne Intl lieber grob sortiert als gar nicht.
            return function (a, b) { return a < b ? -1 : (a > b ? 1 : 0); };
        }
    }

    /** Naechstes Geschwister, das selbst zur sortierten Menge gehoert. */
    function naechstes(el, menge) {
        var n = el.nextSibling;
        while (n) {
            if (n.nodeType === 1 && menge.indexOf(n) >= 0) return n;
            n = n.nextSibling;
        }
        return null;
    }

    /**
     * Sortiert die direkten Kinder von `behaelter`, die auf `auswahl` passen.
     * @param behaelter    Element mit den Kindern
     * @param auswahl      CSS-Selektor der zu sortierenden Kinder
     * @param beschriftung Funktion Element -> anzuzeigender Text
     * @returns Anzahl der wirklich bewegten Elemente
     */
    function sortiere(behaelter, auswahl, beschriftung) {
        if (!behaelter) return 0;
        var alle = [].slice.call(behaelter.querySelectorAll(auswahl))
            // Nur direkte Kinder: ein Treffer in einer verschachtelten Kachel
            // liesse sich nicht umhaengen, ohne sie aus ihrem Wirt zu reissen.
            .filter(function (el) { return el.parentNode === behaelter; });
        if (alle.length < 2) return 0;

        function text(el) {
            try { return (beschriftung(el) || '').trim(); } catch (e) { return ''; }
        }
        // Ans Ende gehoeren die ausdruecklich markierten – und Elemente OHNE
        // Beschriftung. Letzteres ist ein Fehlerfall (eine Kachel ohne Titel);
        // vorn stehend saehe er wie Absicht aus, hinten stoert er niemanden.
        function hinten(el) {
            return el.hasAttribute('data-sort-last') || !text(el);
        }

        var cmp = vergleicher();
        var frei = alle.filter(function (el) { return !hinten(el); });
        var ende = alle.filter(hinten);
        frei.sort(function (a, b) { return cmp(text(a), text(b)); });
        var soll = frei.concat(ende);

        // Von hinten nach vorn: hinter `el` steht dann bereits die endgueltige
        // Reihenfolge, `anker` ist das Element, VOR das `el` gehoert.
        var bewegt = 0, anker = null;
        for (var i = soll.length - 1; i >= 0; i--) {
            var el = soll[i];
            if (naechstes(el, alle) !== anker) {
                behaelter.insertBefore(el, anker);
                bewegt++;
            }
            anker = el;
        }
        return bewegt;
    }

    /** Einstellungs-Reiter (/settings). */
    function reiter() {
        return sortiere(document.querySelector('.settings-tabs'), '.settings-tab-btn',
            function (el) { return el.textContent; });
    }

    /** Portal-Kacheln (/portal) – die Video-Karte traegt `data-sort-last`. */
    function kacheln() {
        return sortiere(document.querySelector('.pt-cards'), '.pt-card', function (el) {
            var t = el.querySelector('.pt-card-title');
            return t ? t.textContent : '';
        });
    }

    function alles() { return { reiter: reiter(), kacheln: kacheln() }; }

    // `applyLang()` feuert das Ereignis auch beim ersten Aufbau – ein
    // zusaetzlicher Aufruf hier ist nur das Netz fuer den Fall, dass dieses
    // Modul erst NACH dem ersten `applyLang()` geladen wird (Testaufbauten,
    // spaeter eingefuegtes Skript). Sortieren ist idempotent.
    window.addEventListener('jarvis-lang-changed', alles);
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', alles);
    } else {
        alles();
    }

    window.JarvisAlphaSort = { sortiere: sortiere, jetzt: alles, reiter: reiter, kacheln: kacheln };
})();
