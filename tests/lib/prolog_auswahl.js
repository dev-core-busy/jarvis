/* Welche Pruefstaende bauen einen Prolog? - die EINE Regel fuer
 * `test_prolog_vollstaendig.js` UND den Sammellauf (`tests/ci_lauf.py`).
 *
 * WARUM EINE EIGENE DATEI (2026-11-22): der Sammellauf schaltet die
 * Prolog-Beobachtung jetzt schon in den REGULAEREN Laeufen dieser
 * Pruefstaende ein, damit der Waechter sie nicht ein zweites Mal startet
 * (er war mit 225-400 s der laengste Pfad des ganzen Sammellaufs). Dafuer
 * muessen beide dieselben Dateien meinen - eine zweite Fassung der Regel in
 * Python liefe beim naechsten neuen Muster still auseinander.
 *
 * Eigenschaft, keine Liste: wer Code aus `frontend/` liest UND ihn per
 * `.eval(` in ein Fenster gibt, baut einen Prolog - egal wie seine
 * Schneidefunktion heisst. `gegen_*` bleibt ausdruecklich draussen: eine
 * Gegenprobe patcht Dateien und darf NIE in einem Sammellauf mitlaufen.
 *
 * Aufruf als Modul:   require('./lib/prolog_auswahl').pruefstaende(TESTS, ausser)
 * Aufruf von aussen:  node tests/lib/prolog_auswahl.js [verzeichnis]  -> JSON-Liste auf stdout
 */
"use strict";

const fs = require("fs");
const path = require("path");

const LIEST_FRONTEND = /readFileSync\([^)]*frontend|join\([^)]*['"]frontend/;
const EVAL = /\.eval\(/;
const WAECHTER = "test_prolog_vollstaendig.js";

/** Dateinamen (sortiert) der Pruefstaende in `verzeichnis`; `ausser` = ein
 *  absoluter Pfad, der nicht mitzaehlt (der Waechter selbst). */
function pruefstaende(verzeichnis, ausser) {
    return fs.readdirSync(verzeichnis)
        .filter((n) => n.endsWith(".js"))
        .filter((n) => !n.startsWith("gegen_"))
        .sort()
        .filter((n) => {
            const p = path.join(verzeichnis, n);
            if (ausser && p === ausser) return false;
            const q = fs.readFileSync(p, "utf8");
            return LIEST_FRONTEND.test(q) && EVAL.test(q);
        });
}

module.exports = { pruefstaende, WAECHTER };

if (require.main === module) {
    // Wahlweise ein anderes Testverzeichnis (der Sammellauf uebergibt seines).
    const tests = path.resolve(process.argv[2] || path.join(__dirname, ".."));
    process.stdout.write(JSON.stringify(pruefstaende(tests, path.join(tests, WAECHTER))) + "\n");
}
