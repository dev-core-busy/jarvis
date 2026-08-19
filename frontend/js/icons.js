/**
 * Zentrale Symbole fuer Bedienelemente – EINE Quelle der Wahrheit.
 *
 * ═══ DIE DESIGN-ENTSCHEIDUNG (2026-08-19, Vorgabe des Nutzers) ═══
 *
 *   MUELLEIMER  =  LOESCHEN.  Etwas Gespeichertes wird dauerhaft entfernt:
 *                  Datei, Eintrag, Regel, Profil, Sitzung, Protokoll, Freigabe.
 *   ×           =  SCHLIESSEN / ABBRECHEN.  Ein Fenster, ein Panel, ein
 *                  Formular geht zu. Es geht nichts verloren.
 *
 * Vorher stand fuer BEIDES ein × – in derselben Oberflaeche, teils in
 * derselben Zeile. Wer ein Panel schliessen wollte, konnte damit einen
 * Eintrag loeschen. Genau das ist der Grund fuer diese Datei.
 *
 * ═══ WARUM SVG UND KEIN EMOJI ═══
 *
 * 🗑️ ist ein Emoji: es wird je nach System FARBIG gerendert, folgt keiner
 * Theme-Variablen und fehlt auf manchen Systemen ganz (dann steht dort ein
 * grauer Kasten – im Projekt schon zweimal passiert). Das Inline-SVG erbt
 * `currentColor`, folgt also Hell/Dunkel und der Markenfarbe, und ist auf
 * jedem System gleich. Dieselbe Begruendung wie bei `.kb-hdr-btn`.
 *
 * ═══ BENUTZUNG ═══
 *
 *   In Template-Strings:   `<button …>${JarvisIcons.trash()}</button>`
 *   Bei textContent:       JarvisIcons.setTrash(knopf)   // statt .textContent = '×'
 *   Als Symbol-Angabe:     icon: JarvisIcons.trash()      // z.B. Kontextmenue
 *
 * Die Datei wird auf JEDER Seite als ERSTES Skript eingebunden (vor i18n.js) –
 * andere Module rufen sie beim Rendern auf, und ein fehlendes `JarvisIcons`
 * waere dort ein harter Fehler mitten in einem Template-String. Ein Test haelt
 * die Einbindung auf allen Seiten fest.
 *
 * KEIN Text im Symbol: die Bedeutung steht im `title`/`aria-label` des Knopfes,
 * und die kommt aus i18n. Ein Symbol traegt keine Sprache.
 */
(function () {
    'use strict';

    // Strichzeichnungen im Stil der uebrigen Symbole des Projekts (feather).
    // `aria-hidden` + `focusable="false"`: das Symbol ist Dekoration, die
    // Bedeutung liefert der Knopf ueber title/aria-label. Ohne das liest ein
    // Screenreader an manchen Stellen nichts und an anderen doppelt vor.
    var GEMEINSAM = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
                    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
                    'aria-hidden="true" focusable="false"';

    var MUELL = '<svg class="jv-ico jv-ico-trash" ' + GEMEINSAM + '>' +
        '<polyline points="3 6 5 6 21 6"/>' +
        '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>' +
        '<line x1="10" y1="11" x2="10" y2="17"/>' +
        '<line x1="14" y1="11" x2="14" y2="17"/></svg>';

    var KREUZ = '<svg class="jv-ico jv-ico-close" ' + GEMEINSAM + '>' +
        '<line x1="18" y1="6" x2="6" y2="18"/>' +
        '<line x1="6" y1="6" x2="18" y2="18"/></svg>';

    function setzen(el, markup) {
        if (!el) return el;
        // innerHTML mit KONSTANTEM Markup – hier kommt nichts von aussen hinein.
        el.innerHTML = markup;
        return el;
    }

    window.JarvisIcons = {
        /** Muelleimer – NUR fuer dauerhaftes Loeschen/Entfernen. */
        trash: function () { return MUELL; },
        /** Kreuz – NUR fuer Schliessen/Abbrechen. */
        close: function () { return KREUZ; },
        /** Ersetzt den Inhalt eines Elements durch den Muelleimer. */
        setTrash: function (el) { return setzen(el, MUELL); },
        /** Ersetzt den Inhalt eines Elements durch das Kreuz. */
        setClose: function (el) { return setzen(el, KREUZ); }
    };
})();
