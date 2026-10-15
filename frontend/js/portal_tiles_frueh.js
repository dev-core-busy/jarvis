/* /portal: gespeicherte Wahl "kleine Kacheln" VOR dem ersten Zeichnen setzen.
 *
 * GEMELDET: "beim Wechsel zu /portal werden zuerst die grossen Kacheln geladen
 * und erst dann die kleinen". portal_tiles.js setzt die Klasse erst bei
 * DOMContentLoaded – bis dahin hat der Browser die Kachelwand bereits gross
 * gezeichnet. Diese Datei wird deshalb (wie theme_frueh.js) SYNCHRON direkt
 * hinter <body> geladen; document.body existiert dort bereits.
 *
 * Vorgezogen wird die EIGENE Wahl ('1') und – ohne eigene Wahl – das
 * gemerkte Ergebnis der Automatik.
 *
 * GEMELDET (2026-10-13, nach dem ersten Fix): "immer noch zuerst die grossen
 * Symbole trotz Einstellung kleine Symbole". Auf DEV im Chrome gemessen: mit
 * eigener Wahl nie gross, OHNE eigene Wahl bei jedem Besuch ~750 ms gross –
 * die kleinen Kacheln stammten von der Automatik, und die merkte sich nichts.
 * Sie merkt sich jetzt die Fenstergroesse, bei der sie umgeschaltet hat
 * ('<breite>x<hoehe>'). Gilt nur in einem Fenster, das hoechstens so gross
 * ist – in einem groesseren passt die grosse Ansicht vielleicht, dann
 * entscheidet die Automatik in portal_tiles.js neu. portal_tiles.js uebernimmt
 * den hier gesetzten Zustand, die Entscheidung liegt also nur HIER. */
try {
    var _ptWahl = localStorage.getItem('jarvis_portal_kompakt');
    var _ptAuto = (localStorage.getItem('jarvis_portal_auto') || '').split('x');
    if (_ptWahl === '1'
        || (_ptWahl === null && _ptAuto.length === 2
            && window.innerWidth <= +_ptAuto[0] && window.innerHeight <= +_ptAuto[1])) {
        document.body.classList.add('pt-kompakt');
    }
} catch (e) {}
