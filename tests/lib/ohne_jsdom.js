/* Messwerkzeug: laesst jsdom fuer einen Node-Prozess VERSCHWINDEN.
 *
 * Aufruf:  node -r ./tests/lib/ohne_jsdom.js tests/test_irgendwas.js
 *
 * ⚠ WARUM NICHT EINFACH JSDOM_PATH AUF EINEN UNGUELTIGEN PFAD:
 * weil ein Waechter, der richtig baut, MEHRERE Orte absucht – er faende jsdom
 * dann im Repo und liefe durch. Gemessen werden soll aber der Fall "jsdom liegt
 * NIRGENDS". Umbenennen im Dateisystem scheidet aus (nicht rueckbaubar, wenn der
 * Lauf abbricht, und es traefe parallele Laeufe mit).
 *
 * Deshalb wird die Modulaufloesung von Node abgefangen: jede Anfrage nach dem
 * Modul `jsdom` wird mit genau dem Fehler abgewiesen, den Node auch sonst wirft
 * (MODULE_NOT_FOUND, Meldung "Cannot find module '<name>'"). Die Umgebung ist
 * also nicht nachgeahmt, sondern echt – nur eben ohne jsdom.
 *
 * `tests/lib/jsdom_laden.js` selbst bleibt ladbar: der Ausdruck trifft `jsdom`
 * nur als vollstaendigen Pfadbestandteil, nicht `jsdom_laden`.
 */
"use strict";

const Module = require("module");

const JSDOM_ANFRAGE = /(^|[/\\])jsdom([/\\]|$)/;
const echtAufloesen = Module._resolveFilename;

Module._resolveFilename = function (anfrage, ...rest) {
    if (typeof anfrage === "string" && JSDOM_ANFRAGE.test(anfrage)) {
        const fehler = new Error("Cannot find module '" + anfrage + "'");
        fehler.code = "MODULE_NOT_FOUND";
        fehler.requireStack = [];
        throw fehler;
    }
    return echtAufloesen.call(this, anfrage, ...rest);
};
