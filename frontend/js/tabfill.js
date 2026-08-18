/* ═══════════════════════════════════════════════════════════════════════
   Vorschlag per TAB uebernehmen
   ───────────────────────────────────────────────────────────────────────
   Mehrere Freitextfelder zeigen im Platzhalter einen BRAUCHBAREN Vorschlag
   ("z. B. Antworte knapp in Stichpunkten …"). Bis 2026-08-18 liess er sich
   nur abtippen. Jetzt: TAB in einem LEEREN, ausdruecklich markierten Feld
   uebernimmt den Vorschlag in das Feld.

   OPT-IN ueber `data-tabfill`, nie global:
     <textarea data-tabfill>                  → nimmt den `placeholder`
     <textarea data-tabfill="Fertiger Text">  → nimmt genau diesen Text

   Der zweite Weg ist noetig, wo der Platzhalter eine AUFZAEHLUNG dessen ist,
   was hineingehoert ("z. B. Signatur, Anrede-Form, …") – als Feldinhalt waere
   das Unsinn. Und deshalb ist es Opt-in: Formvorgaben wie
   "vorname.nachname@firma.de" oder ein Beispiel-DN duerfen NIE uebernommen
   werden, sonst speichert jemand versehentlich das Beispiel.

   TAB IST DIE FOKUS-WEITERSCHALTUNG – dieser Eingriff ist deshalb eng:
   * nur bei LEEREM Feld (danach schaltet TAB wieder normal weiter),
   * nie bei Shift+TAB (rueckwaerts navigieren muss immer gehen),
   * der uebernommene Text wird MARKIERT: Tippen ersetzt ihn, Entf loescht ihn,
     ein weiteres TAB springt weiter. Wer nur durchtabben wollte, verliert
     dadurch nichts als einen Tastendruck.

   Ein Feld, das niemand als uebernehmbar erkennt, nuetzt nichts – deshalb
   erscheint bei Fokus auf einem leeren Feld ein dezenter Hinweis darunter.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var HINWEIS_KLASSE = 'jv-tabfill-hint';

    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }

    function vorschlag(el) {
        if (!el || !el.getAttribute) return '';
        var eigen = el.getAttribute('data-tabfill');
        // Ein gesetztes Attribut mit Text gewinnt; leeres Attribut = Platzhalter.
        if (eigen && eigen.trim()) return eigen.trim();
        return (el.getAttribute('placeholder') || '').trim();
    }

    function passt(el) {
        if (!el || !el.hasAttribute || !el.hasAttribute('data-tabfill')) return false;
        if (el.disabled || el.readOnly) return false;
        var tag = (el.tagName || '').toLowerCase();
        if (tag !== 'textarea' && tag !== 'input') return false;
        return !(el.value || '').length && !!vorschlag(el);
    }

    function hinweisWeg() {
        var alt = document.querySelectorAll('.' + HINWEIS_KLASSE);
        for (var i = 0; i < alt.length; i++) {
            if (alt[i].parentNode) alt[i].parentNode.removeChild(alt[i]);
        }
    }

    function hinweisZeigen(el) {
        hinweisWeg();
        if (!passt(el)) return;
        var s = document.createElement('span');
        s.className = HINWEIS_KLASSE;
        // Textzeichen statt Emoji: ⇥ ist monochrom und folgt dem Theme.
        s.textContent = '⇥ ' + T('common.tabfill_hint',
            'Tab übernimmt den Vorschlag');
        if (el.parentNode) el.parentNode.insertBefore(s, el.nextSibling);
    }

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Tab' || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey) return;
        var el = e.target;
        if (!passt(el)) return;          // nicht markiert oder nicht leer → normales TAB
        e.preventDefault();
        el.value = vorschlag(el);
        try { el.select(); } catch (x) { /* select() gibt es nicht ueberall */ }
        // Andere Module haengen an `input` (Zeichenzaehler, Formular-Spiegel) –
        // ohne dieses Ereignis wuesste keines von der Uebernahme.
        el.dispatchEvent(new Event('input', { bubbles: true }));
        hinweisWeg();
    }, true);

    document.addEventListener('focusin', function (e) { hinweisZeigen(e.target); });
    document.addEventListener('focusout', function () { hinweisWeg(); });
    // Nach einer Uebernahme (oder beim Tippen) ist der Hinweis erledigt.
    document.addEventListener('input', function (e) {
        if (e.target && e.target.hasAttribute &&
            e.target.hasAttribute('data-tabfill') && (e.target.value || '').length) {
            hinweisWeg();
        }
    });
})();
