/* Wachhund fuer die JS-Waechter: schlaegt bei STILLSTAND an, nicht nach fester Gesamtdauer.
 *
 * ⚠ WARUM (2026-11-22): rund sechzig Waechter trugen einen festen Wecker
 * ueber den GANZEN Lauf (`setTimeout(abbruch, 25000)`). Allein ist das
 * reichlich, im Sammellauf unter Volllast nicht: `test_dienst_neustart_ui.js`
 * brauchte allein 8 s, unter Last 28 s - und meldete "der Lauf haengt",
 * obwohl jede Pruefung bestanden hatte. Gemessen hat der Wecker die Maschine,
 * nicht den Code.
 *
 * Ein Haenger heisst: es kommt nichts mehr. Dieser Wachhund wartet deshalb
 * auf eine Pause OHNE AUSGABE (jede Zeile auf stdout/stderr - jede Pruefung
 * schreibt eine - startet die Frist neu), und die Frist waechst mit der
 * Systemlast: Grundfrist x max(1, Lastmittel einer Minute / Kerne). Auf einer
 * ruhigen Maschine bleibt es bei der Grundfrist. Die Gesamtdauer begrenzt
 * weiter der Zeitdeckel des Sammellaufs (tests/ci_lauf.py).
 *
 * Grenze: eine Seite, die im Haenger fortlaufend auf die Konsole schreibt,
 * haelt den Hund wach - dann greift erst der Zeitdeckel des Sammellaufs.
 *
 * Gleiche Aufrufform wie setTimeout, und der Rueckgabewert IST der Timer:
 * `clearTimeout(hund)`, `hund.unref()` und `.unref()` am Aufruf wirken wie
 * bisher. (Ein abgeschalteter Timer bleibt abgeschaltet: Node ignoriert
 * refresh() nach clearTimeout - gemessen in test_wachhund.js.)
 * Umstellung eines Waechters = nur der Aufrufname:
 *
 *     const WACHHUND = require('./lib/wachhund')(() => { ...; process.exit(1); }, 25000);
 *
 * Waechter: tests/test_wachhund.js (Wirkung je Fall in eigenem Prozess +
 * Regel am Syntaxbaum: kein fester Wecker >= 10 s mehr auf oberster Ebene).
 */
'use strict';

const os = require('os');

// Eigene Uhr: ein Waechter, der spaeter Date.now ersetzt (virtuelle Zeit),
// darf den Hund nicht mitreissen. (setTimeout ruft der Hund nach dem Anlegen
// nie wieder auf - er stellt sich per refresh() neu.)
const _jetztMs = () => Number(process.hrtime.bigint() / 1000000n);

const aktiv = new Set();
let eingehaengt = false;

function lastfaktor() {
    const kerne = (os.cpus() || []).length || 1;
    const last = (os.loadavg() || [0])[0] || 0;
    // Nie unter 1: ruhige Maschine = Grundfrist. (Kuerzer ginge ohnehin
    // nicht - der Timer feuert fruehestens nach der Grundfrist.)
    return Math.max(1, last / kerne);
}

function einhaengen() {
    eingehaengt = true;
    // Jede Ausgabe ist Fortschritt: Frist aller Hunde neu starten.
    for (const strom of [process.stdout, process.stderr]) {
        const echt = strom.write;
        strom.write = function () {
            if (aktiv.size) {
                const t = _jetztMs();
                for (const h of aktiv) { h.letzte = t; h.timer.refresh(); }
            }
            return echt.apply(this, arguments);
        };
    }
}

module.exports = function wachhund(anschlag, grundMs) {
    if (typeof anschlag !== 'function' || !(grundMs > 0)) {
        throw new TypeError('wachhund(anschlag, grundMs): Funktion und Frist > 0 erwartet');
    }
    if (!eingehaengt) einhaengen();
    const h = { letzte: _jetztMs(), timer: null };
    h.timer = setTimeout(function pruefen() {
        const still = _jetztMs() - h.letzte;
        const faktor = lastfaktor();
        if (still < grundMs * faktor) {
            // Unter Last: weiter warten (in Schritten der Grundfrist).
            h.timer.refresh();
            return;
        }
        aktiv.delete(h);
        console.log('Wachhund: ' + Math.round(still / 1000) + ' s ohne neue Ausgabe (Grundfrist '
                    + Math.round(grundMs / 1000) + ' s, Lastfaktor ' + faktor.toFixed(1) + ')');
        return anschlag.apply(this, arguments);
    }, grundMs);
    aktiv.add(h);
    return h.timer;
};

// Fuer den Waechter: Faktor sichtbar machen, ohne die Formel zu kopieren.
module.exports.lastfaktor = lastfaktor;
