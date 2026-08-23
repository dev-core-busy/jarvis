/* ═══════════════════════════════════════════════════════════════════════
   /portal: Kachelgroesse umschalten – gross (Vorgabe) oder klein.

   GEMELDET: "die Zahl der moeglichen Kacheln in /portal ist gestiegen, so dass
   dort gescrollt werden muss." Mit allen freigeschalteten Bereichen passt die
   Kachelwand nicht mehr auf einen Bildschirm.

   KLEIN heisst: Symbol + Kurzbeschreibung (der Titel), und der laengere
   Beschreibungstext wandert in den Tooltip. Er wird also NICHT weggeworfen,
   sondern wechselt den Platz – wer wissen will, was ein Bereich tut, kommt
   weiterhin daran.

   DAS VIDEO WIRD NIE VERKLEINERT (Vorgabe). Es belegt im engeren Raster zwei
   Spalten und behaelt damit seine Breite (Regel in portal.html).

   ── DIE AUTOMATIK UND WARUM SIE NUR IN EINE RICHTUNG SCHALTET ────────────
   Gefragt war: "Ist eine automatische Umschaltung moeglich? z.B. dann, wenn ein
   Scrollbalken erscheint automatisch auf klein umschalten?" – Ja, aber nur
   einseitig. Wer bei "kein Scrollbalken" auch wieder vergroessert, baut eine
   Endlosschleife: gross -> Scrollbalken -> klein -> kein Scrollbalken -> gross
   -> ... Die Seite flackerte dann bei jeder Fenstergroesse, die genau auf der
   Kippe liegt. Deshalb:

     * Die Automatik schaltet ausschliesslich AUF KLEIN, nie zurueck.
     * Sie greift nur, solange der Benutzer nicht selbst gewaehlt hat. Ein Klick
       auf den Umschalter ist eine Entscheidung und wird gespeichert; danach
       schweigt die Automatik dauerhaft (auch fuer "gross", obwohl dann
       gescrollt werden muss – eine Anzeige, die die Wahl des Benutzers
       ueberstimmt, ist ein Fehler, keine Hilfe).
     * Gemessen wird mit einem Schwellwert (`SCHWELLE`), nicht auf das letzte
       Pixel: ein Ueberstand von wenigen Pixeln (Rundung, Rollbalkenbreite) ist
       kein Grund, die Ansicht umzubauen.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var KEY = 'jarvis_portal_kompakt';   // '1' | '0' – nur bei EIGENER Wahl gesetzt
    var KLASSE = 'pt-kompakt';
    // Ueberstand in Pixeln, ab dem die Automatik greift. Klein genug, um echtes
    // Scrollen zu erkennen, gross genug gegen Rundungen und Rollbalkenbreite.
    var SCHWELLE = 24;

    function $(id) { return document.getElementById(id); }

    function gewaehlt() {
        try { return localStorage.getItem(KEY); } catch (e) { return null; }
    }

    function istKompakt() {
        return document.body.classList.contains(KLASSE);
    }

    /* Die Beschreibungstexte in den Tooltip heben – und beim Zurueckschalten
       wieder entfernen. Der Titel bleibt in BEIDEN Zustaenden sichtbar; er IST
       die Kurzbeschreibung.

       Warum der Text nicht dauerhaft im title stehen darf: in der grossen
       Ansicht steht er sichtbar in der Kachel, ein Tooltip mit demselben Wortlaut
       ist dort nur Rauschen ueber dem Text, den man gerade liest. */
    function tooltips(an) {
        var karten = document.querySelectorAll('.pt-cards .pt-card');
        Array.prototype.forEach.call(karten, function (k) {
            // Die Video-Karte hat keinen Text und wird nicht verkleinert.
            if (k.classList.contains('pt-card-video')) return;
            var desc = k.querySelector('.pt-card-desc');
            if (!desc) return;
            if (an) {
                var txt = (desc.textContent || '').trim();
                // Den EIGENEN Tooltip nicht ueberschreiben: eine Karte kann
                // schon einen tragen (dann bleibt er). Gemerkt wird, dass wir
                // ihn gesetzt haben, damit nur der eigene wieder verschwindet.
                if (txt && !k.getAttribute('title')) {
                    k.setAttribute('title', txt);
                    k.dataset.ptTip = '1';
                }
            } else if (k.dataset.ptTip === '1') {
                k.removeAttribute('title');
                delete k.dataset.ptTip;
            }
        });
    }

    function knopfAktualisieren() {
        var b = $('pt-size-btn');
        if (!b) return;
        var k = istKompakt();
        var klein = $('pt-size-ico-small'), gross = $('pt-size-ico-large');
        if (klein) klein.style.display = k ? 'none' : '';
        if (gross) gross.style.display = k ? '' : 'none';
        // Beschriftung ueber i18n, mit deutschem Rueckfall (wie im uebrigen
        // Portal): sie nennt die AKTION, nicht den Zustand.
        var key = k ? 'portal.tiles_large' : 'portal.tiles_small';
        var txt = (window.t ? window.t(key) : '') || (k ? 'Kacheln vergrößern' : 'Kacheln verkleinern');
        b.setAttribute('title', txt);
        b.setAttribute('data-i18n-title', key);
        b.setAttribute('aria-pressed', k ? 'true' : 'false');
    }

    function setzen(kompakt) {
        document.body.classList.toggle(KLASSE, !!kompakt);
        tooltips(!!kompakt);
        knopfAktualisieren();
    }

    /* Automatik: greift NUR ohne eigene Wahl und NUR in Richtung klein. */
    function pruefeUeberlauf() {
        if (gewaehlt() !== null) return;      // der Benutzer hat entschieden
        if (istKompakt()) return;             // einseitig – nie zurueck
        var d = document.documentElement;
        var ueber = Math.max(d.scrollHeight, document.body.scrollHeight)
                    - window.innerHeight;
        if (ueber > SCHWELLE) setzen(true);
    }

    var _gestartet = false;

    function start() {
        /* Idempotent – Projektmuster (`_gebunden` in den uebrigen Modulen).
           Ein zweiter Durchlauf haengte einen ZWEITEN Klick-Handler an, der Klick
           schaltete dann zweimal und damit sichtbar gar nicht. Auf der echten
           Seite feuert DOMContentLoaded nur einmal; gefunden hat es der Test,
           der es zusaetzlich von Hand ausloeste – und genau dieser Fall tritt
           auch ein, wenn die Seite das Skript spaeter noch einmal einbindet. */
        if (_gestartet) return;
        _gestartet = true;
        var w = gewaehlt();
        // Ohne eigene Wahl beginnt es GROSS (wie bisher) – die Automatik
        // entscheidet gleich danach anhand der wirklichen Hoehe.
        setzen(w === '1');

        var b = $('pt-size-btn');
        if (b) b.addEventListener('click', function () {
            var neu = !istKompakt();
            try { localStorage.setItem(KEY, neu ? '1' : '0'); } catch (e) { /* egal */ }
            setzen(neu);
        });

        // Erst messen, wenn die Kacheln stehen: mehrere werden nachtraeglich
        // eingeblendet (Freigaben aus /api/me), und vorher ist die Hoehe
        // bedeutungslos. Zwei Zeitpunkte, weil die Abrufe nebenlaeufig sind.
        setTimeout(pruefeUeberlauf, 700);
        setTimeout(pruefeUeberlauf, 2200);

        var t = null;
        window.addEventListener('resize', function () {
            clearTimeout(t);
            t = setTimeout(pruefeUeberlauf, 250);
        });
        // Der Sprachwechsel baut die Beschreibungstexte neu auf – die Tooltips
        // muessen dann mitgezogen werden, sonst steht dort der alte Wortlaut.
        window.addEventListener('jarvis-lang-changed', function () {
            if (istKompakt()) { tooltips(false); tooltips(true); }
            knopfAktualisieren();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    window.JarvisPortalTiles = {
        setzen: setzen, pruefeUeberlauf: pruefeUeberlauf, istKompakt: istKompakt
    };
})();
