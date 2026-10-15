/* Gemeinsame acorn-Einbindung fuer die JS-Waechter in tests/.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT: genau dieselbe Lehre wie bei
 * `jsdom_laden.js` – nur eine Datei spaeter bezahlt. Fuenf Waechter trugen
 * je eine EIGENE Suchschleife fuer acorn (`test_js_reichweite.js`,
 * `test_dlkey_reichweite.js`, `test_jsdom_einbindung.js`,
 * `test_settings_suche_ui.js`, `test_stt_lokal.js`). Eine Ortsliste, die
 * fuenfmal gepflegt werden muss, ist fuenfmal veraltet – und ein Waechter, der
 * seinen Parser nicht findet, sagt "ABBRUCH" und misst NICHTS, waehrend der
 * Sammellauf gruen aussieht.
 *
 * Fuer die bestehenden fuenf bleibt ihre eigene Schleife bis zu einer eigenen
 * Umstellung stehen (sie funktioniert); NEUE Waechter nehmen diese Quelle.
 *
 * Aufruf (Regelfall, Exit 2 wenn acorn fehlt):
 *     const acorn = require('./lib/acorn_laden')();
 *
 * Aufruf, wenn ein Abschnitt ohne Parser uebersprungen werden darf:
 *     const acorn = require('./lib/acorn_laden').versuchen();
 */
"use strict";

const path = require("path");

const WURZEL = path.resolve(__dirname, "..", "..");

/** Suchorte in dieser Reihenfolge: ausdrueckliche Vorgabe, normale
 *  Node-Aufloesung (deckt Repo-node_modules und NODE_PATH mit ab), dann die
 *  maschinenspezifischen Orte. Gleiche Liste wie bei jsdom – acorn kommt in
 *  diesem Projekt aus demselben Debian-Paketbaum (/usr/share/nodejs). */
function orte() {
    const HOME = process.env.HOME || "";
    return [
        process.env.ACORN_PATH,                           // ausdrueckliche Vorgabe
        "acorn",                                          // normale Aufloesung / NODE_PATH
        "/usr/share/nodejs/acorn",                        // Debian-Paket
        path.join(WURZEL, "node_modules/acorn"),          // Repo
        path.join(WURZEL, "data/node_modules/acorn"),     // Repo (Altbestand)
        "/tmp/node_modules/acorn",
        HOME && path.join(HOME, "node_modules/acorn"),
        "/opt/jarvis/data/node_modules/acorn",            // Server
        "/usr/lib/node_modules/acorn",
    ].filter(Boolean);
}

/** acorn oder null. Nur "Modul nicht gefunden" wird uebergangen – ein acorn,
 *  das beim Laden SELBST wirft, muss laut werden, sonst sieht ein echter Defekt
 *  wie ein fehlendes Paket aus. */
function versuchen() {
    for (const ort of orte()) {
        try {
            return require(ort);
        } catch (e) {
            const fehltNur = e && e.code === "MODULE_NOT_FOUND"
                             && String(e.message).indexOf("'" + ort + "'") >= 0;
            if (!fehltNur) throw e;
        }
    }
    return null;
}

/** Regelfall: Modul oder Exit 2 ("konnte nicht laufen") mit lesbarer Meldung. */
function laden() {
    const modul = versuchen();
    if (modul) return modul;
    console.log("ABBRUCH: acorn an keinem dieser Orte gefunden: " + orte().join(", "));
    console.log("Abhilfe: 'npm i acorn' im Repo, oder ACORN_PATH=<pfad> setzen.");
    console.log("Exit 2 = konnte nicht laufen (weder bestanden noch fehlgeschlagen).");
    process.exit(2);
}

module.exports = laden;
module.exports.laden = laden;
module.exports.versuchen = versuchen;
module.exports.orte = orte;
