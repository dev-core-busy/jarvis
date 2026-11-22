/* Auswahllisten: stabile Breite fuer die gestaltbare Auswahl (base-select).
 *
 * WARUM: theme.css stellt alle einfachen Auswahlfelder auf
 * `appearance: base-select` um (Begruendung dort, Abschnitt "Auswahllisten":
 * das Betriebssystem-Menue legte sich bei langen Listen ueber das Feld und
 * waehlte beim Loslassen der Maustaste einen Eintrag). Die gestaltbare Auswahl
 * richtet ihre Breite aber nach dem GEWAEHLTEN Eintrag, die alte nach dem
 * LAENGSTEN (gemessen: 59 gegen 242 px). Ein Feld ohne feste Breite sprang
 * damit bei jeder Auswahl und schob die Zeile daneben weg. Per CSS laesst sich
 * das nicht beheben – deshalb dieses Modul.
 *
 * WIE: jeder Eintrag wird einmal kurz gewaehlt und die Breite des Feldes
 * gemessen; die groesste wird Mindestbreite. Das misst die ECHTE Breite samt
 * Klassenregeln, Innenabstand und Pfeil, statt sie nachzurechnen. Ein Feld mit
 * fester Breite (`width: 100%`, `90px`) misst dabei jedes Mal gleich – es
 * bekommt keine Mindestbreite und bleibt unveraendert. Das Umschalten ist
 * synchron und loest kein `change`/`input` aus; die Auswahl steht danach
 * wieder wie vorher.
 *
 * WANN: (1) bevor die Liste aufgeht (`pointerdown`/`focusin`) – das ist der
 * verlaessliche Weg, denn gewaehlt wird erst danach; (2) wenn ein Feld
 * sichtbar wird oder seine Groesse aendert (ResizeObserver) – damit es schon
 * vor dem ersten Klick die richtige Breite hat; (3) wenn sich Eintraege oder
 * ihre Texte aendern (MutationObserver, Sprachwechsel).
 *
 * Eine Mindestbreite, die der Autor selbst inline gesetzt hat, bleibt
 * unangetastet. Ohne base-select (Firefox, aeltere Chrome) tut das Modul
 * nichts.
 */
(function () {
    'use strict';

    var CSSO = window.CSS;
    if (!CSSO || !CSSO.supports || !CSSO.supports('appearance', 'base-select')) return;

    // Marke: die Mindestbreite stammt von hier und darf neu berechnet werden.
    var MARKE = 'data-auswahl-breite';

    function betroffen(s) {
        if (!s || s.tagName !== 'SELECT' || s.multiple || s.hasAttribute('size')) return false;
        if (s.style.minWidth && !s.hasAttribute(MARKE)) return false;   // vom Autor gesetzt
        return getComputedStyle(s).appearance === 'base-select';
    }

    function messen(s) {
        if (!betroffen(s)) return;
        if (s.hasAttribute(MARKE)) {
            // Eigene Vorgabe zuruecknehmen – sonst misst die Schleife nur sie selbst,
            // und ein kuerzer gewordener Inhalt behielte die alte Breite.
            s.style.minWidth = '';
            s.removeAttribute(MARKE);
        }
        var n = s.options.length;
        if (n < 2 || !s.offsetWidth) return;   // unsichtbar: beim Sichtbarwerden erneut
        var vorher = s.selectedIndex;
        var groesste = 0, kleinste = Infinity;
        for (var i = 0; i < n; i++) {
            s.selectedIndex = i;
            var b = s.getBoundingClientRect().width;
            if (b > groesste) groesste = b;
            if (b < kleinste) kleinste = b;
        }
        s.selectedIndex = vorher;
        // "Breiten unterscheiden sich" – NICHT "die aktuelle ist schmaler": steht
        // gerade der laengste Eintrag, waere sonst keine Untergrenze gesetzt, und
        // das Feld schrumpfte bei der naechsten Auswahl (vom Waechter gefunden).
        // Feste Breite: alle Messungen gleich, nichts zu tun.
        if (groesste - kleinste > 0.5) {
            s.style.minWidth = Math.ceil(groesste) + 'px';
            s.setAttribute(MARKE, '');
        }
    }

    // ── Sichtbarwerden und Groessenaenderung ─────────────────────────────────
    var beobachtet = new WeakSet();
    var ro = window.ResizeObserver ? new ResizeObserver(function (eintraege) {
        eintraege.forEach(function (e) { messen(e.target); });
    }) : null;

    function aufnehmen(s) {
        if (!s || s.tagName !== 'SELECT' || beobachtet.has(s)) return;
        beobachtet.add(s);
        if (ro) ro.observe(s);
    }

    // ── Geaenderte Eintraege: gesammelt, einmal je Feld und Takt ─────────────
    var offen = new Set();
    var geplant = false;
    function vormerken(s) {
        if (!s) return;
        offen.add(s);
        if (geplant) return;
        geplant = true;
        Promise.resolve().then(function () {
            geplant = false;
            var liste = Array.from(offen);
            offen.clear();
            liste.forEach(function (x) { aufnehmen(x); messen(x); });
        });
    }

    function feldZu(knoten) {
        var el = knoten && (knoten.nodeType === 1 ? knoten : knoten.parentNode);
        return el && el.closest ? el.closest('select') : null;
    }

    function hinzugekommen(knoten) {
        if (!knoten || knoten.nodeType !== 1) return;
        if (knoten.tagName === 'SELECT') { vormerken(knoten); return; }
        var innen = knoten.getElementsByTagName('select');
        for (var i = 0; i < innen.length; i++) vormerken(innen[i]);
    }

    new MutationObserver(function (aenderungen) {
        aenderungen.forEach(function (m) {
            var s = feldZu(m.target);
            if (s) vormerken(s);
            if (m.type === 'childList') m.addedNodes.forEach(hinzugekommen);
        });
    }).observe(document.documentElement, { childList: true, subtree: true, characterData: true });

    // ── Bevor die Liste aufgeht ──────────────────────────────────────────────
    function vorDemOeffnen(e) {
        var s = e.target && e.target.closest ? e.target.closest('select') : null;
        if (s) { aufnehmen(s); messen(s); }
    }
    document.addEventListener('pointerdown', vorDemOeffnen, true);
    document.addEventListener('focusin', vorDemOeffnen, true);

    // Sprachwechsel aendert die Texte aller Eintraege
    function alle() {
        var felder = document.getElementsByTagName('select');
        for (var i = 0; i < felder.length; i++) { aufnehmen(felder[i]); messen(felder[i]); }
    }
    window.addEventListener('jarvis-lang-changed', alle);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', alle);
    else alle();

    window.JarvisAuswahlliste = { messen: messen, alle: alle };
})();
