/* Gemeinsame jsdom-Einbindung fuer alle JS-Waechter in tests/.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT: 54 Waechter hatten 19 verschiedene Gestalten,
 * um jsdom zu finden. Die haeufigste war
 *
 *     const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');
 *
 * Liegt jsdom nicht unter /tmp/node_modules (und /tmp wird geleert), stirbt das
 * Skript mit MODULE_NOT_FOUND, Stacktrace und Exit 1 – ununterscheidbar von
 * "der Waechter beisst". Gemessen am 2026-09-30: von 55 Dateien liefen nur 24.
 * 13 starben mit Exit 1, und 15 brachen mit Exit 2 und der Meldung "jsdom nicht
 * installiert" ab, OBWOHL jsdom im Repo liegt – sie sahen nur an einem Ort nach.
 * Die falsche Meldung ist der teurere Teil: sie sieht nach geklaertem Fall aus.
 *
 * Eine Liste von Suchorten, die 54-mal gepflegt werden muss, ist 54-mal
 * veraltet. Deshalb EINE Quelle. Die Waechter bleiben eigenstaendig (kein
 * Runner, kein Framework) – sie teilen nur das Auffinden des Werkzeugs.
 *
 * Aufruf (Regelfall, bricht bei fehlendem jsdom mit Exit 2 ab):
 *     const { JSDOM } = require('./lib/jsdom_laden')();
 *     const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
 *
 * Aufruf, wenn ein Abschnitt OHNE jsdom uebersprungen werden darf:
 *     const modul = require('./lib/jsdom_laden').versuchen();
 *     if (!modul) { ...Abschnitt ueberspringen...; }
 * Das ist die Ausnahme, nicht die Regel – sie gilt nur, wo das Fehlen von jsdom
 * ausdruecklich kein Fehlschlag sein soll (siehe tests/test_marke_i18n.js).
 */
"use strict";

const path = require("path");

const WURZEL = path.resolve(__dirname, "..", "..");

/** Alle Orte, an denen jsdom in diesem Projekt liegen kann – in dieser
 *  Reihenfolge. Ausdrueckliche Vorgabe zuerst, danach die normale Aufloesung
 *  von Node (die deckt Repo-node_modules und NODE_PATH mit ab), dann die
 *  Maschinen-spezifischen Orte. */
function orte() {
    const HOME = process.env.HOME || "";
    return [
        process.env.JSDOM_PATH,                           // ausdrueckliche Vorgabe
        "jsdom",                                          // normale Aufloesung / NODE_PATH
        "/tmp/node_modules/jsdom",                        // DEV legt es dorthin
        path.join(WURZEL, "node_modules/jsdom"),          // Repo
        path.join(WURZEL, "data/node_modules/jsdom"),     // Repo (Altbestand)
        HOME && path.join(HOME, "node_modules/jsdom"),    // Arbeitsplatz
        HOME && path.join(HOME, "sleek/node_modules/jsdom"),
        "/opt/jarvis/data/node_modules/jsdom",            // Server
        "/usr/share/nodejs/jsdom",                        // Debian-Paket
        "/usr/lib/node_modules/jsdom",
    ].filter(Boolean);
}

/** Einhaengepunkt der Prolog-Pruefung (tests/test_prolog_vollstaendig.js).
 *
 *  ⚠ WARUM HIER: diese Datei ist die EINE Stelle, durch die jeder JS-Waechter
 *  sein JSDOM holt – `test_jsdom_einbindung.js` haelt das als Regel fest. Wer
 *  `window.eval` beobachten will, erreicht hier rund 85 Pruefstaende auf
 *  einmal, ohne einen davon anzufassen.
 *
 *  ⚠ IM NORMALBETRIEB PASSIERT NICHTS: ohne `PROLOG_PRUEFUNG` wird das Modul
 *  unveraendert durchgereicht, und `prolog_pruefen` (mit acorn) wird nie
 *  geladen. Ein Defekt der Diagnose darf keinen Pruefstand kippen – aber
 *  STILL sein darf er auch nicht, sonst sieht "nicht eingehaengt" wie
 *  "nichts gefunden" aus. */
function umhuellen(modul) {
    if (!process.env.PROLOG_PRUEFUNG) return modul;
    try { return require("./prolog_pruefen").vielleichtUmhuellen(modul); }
    catch (e) {
        console.log("HINWEIS: Prolog-Pruefung NICHT eingehaengt: " + ((e && e.message) || e));
        return modul;
    }
}

/** Laedt jsdom und gibt das MODUL zurueck (nicht nur JSDOM – manche Waechter
 *  brauchen auch VirtualConsole). null, wenn es nirgends liegt.
 *
 *  ⚠ Nur "Modul nicht gefunden" wird uebergangen. Ein jsdom, das beim Laden
 *  SELBST wirft (kaputte Installation, unpassende Node-Fassung), muss laut
 *  werden – sonst sieht ein echter Defekt wie ein fehlendes Paket aus. */
function versuchen() {
    for (const ort of orte()) {
        try {
            return umhuellen(require(ort));
        } catch (e) {
            const fehltNur = e && e.code === "MODULE_NOT_FOUND"
                             && String(e.message).indexOf("'" + ort + "'") >= 0;
            if (!fehltNur) throw e;
        }
    }
    return null;
}

/** Regelfall: Modul oder Exit 2 mit lesbarer Meldung – kein Stacktrace.
 *  Exit 2 heisst "konnte nicht laufen" und ist ausdruecklich NICHT Exit 1
 *  ("Waechter beisst") und nicht Exit 0 ("bestanden"). */
function laden() {
    const modul = versuchen();
    if (modul) return modul;
    console.log("ABBRUCH: jsdom an keinem dieser Orte gefunden: " + orte().join(", "));
    console.log("Abhilfe: 'npm i jsdom' im Repo, oder JSDOM_PATH=<pfad zu jsdom> setzen.");
    console.log("Exit 2 = konnte nicht laufen (weder bestanden noch fehlgeschlagen).");
    process.exit(2);
}

module.exports = laden;
module.exports.laden = laden;
module.exports.versuchen = versuchen;
module.exports.orte = orte;
