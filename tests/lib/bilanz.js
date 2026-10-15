/* EINE Quelle fuer das Abbruchnetz der JS-Waechter.
 *
 * WARUM ES DAS GIBT (bezahlt am 2026-10-05): `test_knowledge_sync_ui.js` und
 * `test_topbar_symbole_ui.js` brachen mit einem TypeError ab
 * (`window.JarvisSitzung` fehlte im Prolog, Folge von 8d082990) und lieferten
 * dabei **Exit 1 ohne Bilanzzeile**. Exit 1 ist in diesem Projekt die Sprache,
 * in der ein Waechter "ich beisse" sagt – der Abbruch war von einem Befund
 * nicht zu unterscheiden, und beide Dateien lagen unbemerkt brach. Repoweit
 * gemessen traf das **9 von 102** Waechter, 7 davon aus derselben Ursache.
 *
 * Dieselbe Klasse wie der jsdom-Vorfall vom 2026-09-30 ("ein Werkzeug, das an
 * einem festen Ort erwartet wird, macht den Waechter stumm"): dort war die
 * Loesung EINE Quelle (`tests/lib/jsdom_laden.js`) statt 19 Gestalten. Hier
 * ebenso.
 *
 * ZWEI NETZE, FUER ZWEI VERSCHIEDENE ENDEN – sie sind nicht austauschbar:
 *
 *   1. ABSTURZ (uncaughtException / unhandledRejection) -> Exit 2.
 *      Node beendet einen Absturz von sich aus mit Code 1. Genau das ist die
 *      Verwechslung: Exit 2 heisst "konnte nicht laufen", Exit 1 heisst
 *      "Waechter beisst". Dieses Netz ist der Kern und braucht vom Aufrufer
 *      NICHTS – eine Zeile `require('./lib/bilanz')();` genuegt.
 *
 *   2. STILLES ENDE (Code 0, aber nie eine Bilanz gedruckt) -> Exit 1.
 *      Nur per `{ stumm: true }`, denn es verlangt eine Gegenleistung: der
 *      Aufrufer MUSS `fertig()` neben seine Bilanzzeile setzen. Waere es
 *      vorgabeweise an, wuerde jeder gruene Waechter, der `fertig()` nicht
 *      kennt, faelschlich als "ohne Bilanz" gemeldet.
 *
 * ⚠ DER CODE WIRD NUR BEI EINEM STILLEN ENDE ANGEHOBEN (`code === 0`). Ein
 * blindes `process.exitCode = 1` im `exit`-Netz zerstoert das Exit-2-Signal:
 * es laeuft NACH `process.exit(2)` und macht daraus Exit 1 – der Abbruch
 * "Werkzeug fehlt" sieht damit aus wie "Waechter beisst". Das ist im Register
 * bezahlt, und am 2026-10-05 standen trotzdem **12 von 42** vorhandenen
 * Netzen genau so blind da. `tests/test_waechter_bilanz.js` haelt beides fest.
 *
 * Benutzung:
 *     require('./lib/bilanz')();                       // nur Absturznetz
 *     const fertig = require('./lib/bilanz')({ stumm: true });
 *     ... fertig(); console.log(`${ok} OK, ${fail} FAIL`);
 */
'use strict';

module.exports = function netz(opt) {
    opt = opt || {};
    let bilanz = false;

    const grund = (e) => (e && e.stack) || String(e);

    // Absturz: Grund NENNEN und mit Exit 2 enden. Ein richtiger Grund, der
    // den naechsten Schritt nicht sagt, ist nutzlos - deshalb der Stack.
    const abbruch = (was) => (e) => {
        console.log(`\nABBRUCH (Exit 2) – ${was}: ` + grund(e));
        bilanz = true;          // das Stumm-Netz darf nicht nachtreten
        process.exit(2);
    };
    process.on('uncaughtException', abbruch('Ausnahme'));
    process.on('unhandledRejection', abbruch('offene Zusage'));

    if (opt.stumm) {
        process.on('exit', (code) => {
            // NUR das stille Ende anheben - siehe Warnung im Kopf.
            if (!bilanz && code === 0) {
                console.log('\nABGEBROCHEN – keine Bilanzzeile (siehe Ausgabe oben)');
                process.exitCode = 1;
            }
        });
    }

    return function fertig() { bilanz = true; };
};
