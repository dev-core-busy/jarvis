/* Startet viele kurze Node-Laeufe mit begrenzter Gleichzeitigkeit - fuer Waechter,
 * die je Datei einen eigenen Prozess messen.
 *
 * WARUM (2026-11-22): `test_jsdom_einbindung.js` startet in Abschnitt 3 jede
 * der rund 160 jsdom-Dateien ohne jsdom und prueft Exit-Code und Ausgabe.
 * Nacheinander per spawnSync war das 28 von 31 s CPU-Profil - reines Warten.
 * Und seine Gegenprobe zahlt es je Probe: 14 Laeufe, 20 Minuten.
 *
 * Gleiches Muster wie `prolog_fanout.js`: eine EIGENE Datei (ein eingebettetes
 * Node-Skript ist nicht diagnostizierbar, Register 2026-10-11), gestartet vom
 * Waechter per spawnSync, Ergebnis als JSON-Datei IN DER REIHENFOLGE DES
 * AUFTRAGS - die Auswertung bleibt im Waechter seriell, eine Bilanz, die sich
 * bei gleichem Code anders sortiert, ist keine Messung.
 *
 * Aufruf:  node tests/lib/parallel_laeufe.js <auftrag.json>
 * Auftrag: { "laeufe": [{"argv": [...], "cwd": "...", "timeout_ms": 120000}],
 *            "grenze": 8, "ergebnis": "<pfad.json>" }
 * Ergebnis: { "ergebnisse": [{"argv", "status", "signal", "stdout", "stderr"}] }
 *           (argv je Ergebnis: der Waechter prueft damit, dass Ergebnis i zu Lauf i gehoert)
 * Exit 0 = alle beendet und geschrieben · 2 = Auftrag unbrauchbar
 */
"use strict";

const fs = require("fs");
const { spawn } = require("child_process");

let A;
try {
    A = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
} catch (e) {
    console.error("ABBRUCH: Auftrag nicht lesbar: " + e.message);
    process.exit(2);
}
if (!Array.isArray(A.laeufe) || !A.ergebnis) {
    console.error("ABBRUCH: Auftrag ohne laeufe/ergebnis");
    process.exit(2);
}
const GRENZE = Math.max(1, Number(A.grenze) || 1);

function einer(lauf) {
    return new Promise((fertig) => {
        const kind = spawn(process.execPath, lauf.argv, { cwd: lauf.cwd, env: process.env });
        const aus = [], err = [];
        kind.stdout.on("data", (d) => aus.push(d));
        kind.stderr.on("data", (d) => err.push(d));
        let erledigt = false;
        const uhr = setTimeout(() => { try { kind.kill("SIGKILL"); } catch (e) { /* schon weg */ } },
                               lauf.timeout_ms || 120000);
        const ende = (status, signal) => {
            if (erledigt) return;
            erledigt = true;
            clearTimeout(uhr);
            fertig({ argv: lauf.argv, status, signal: signal || null,
                     stdout: Buffer.concat(aus).toString("utf8"), stderr: Buffer.concat(err).toString("utf8") });
        };
        // "close" statt "exit": erst dann sind stdout/stderr vollstaendig gelesen
        kind.on("close", ende);
        // Startet der Prozess gar nicht, kommt kein "close" - ohne diesen Zweig
        // wartete der Starter bis zum Deckel.
        kind.on("error", (e) => ende(null, "start:" + e.code));
    });
}

(async () => {
    const ergebnisse = new Array(A.laeufe.length);
    let naechster = 0;
    const arbeiter = Array.from({ length: Math.min(GRENZE, A.laeufe.length) }, async () => {
        for (;;) {
            const i = naechster++;
            if (i >= A.laeufe.length) return;
            ergebnisse[i] = await einer(A.laeufe[i]);
        }
    });
    await Promise.all(arbeiter);
    fs.writeFileSync(A.ergebnis, JSON.stringify({ ergebnisse }));
    process.exit(0);
})();
