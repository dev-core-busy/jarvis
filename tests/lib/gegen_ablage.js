/* Sicherungsablage der JS-Gegenproben (`tests/gegen_*.js`) nach geordnetem Ende abraeumen.
 *
 * WARUM (2026-11-22): die drei JS-Harnesse sichern wie die Python-Harnesse auf
 * PLATTE im Home (`~/.gegen_*`) und nehmen am Ende nur die LAUFMARKE weg - der
 * Ordner blieb liegen (gesehen: `~/.gegen_prolog_sicherung` mit einem
 * vollstaendigen Altstand von chat.js). Die Python-Harnesse raeumen seit
 * `tests/lib/gegen_ablage.py` selbst ab.
 *
 * EINE REGEL, EINE QUELLE: dieser Helfer entscheidet NICHTS selbst. Beim
 * Prozessende ruft er `tests/lib/gegen_ablage.py` als Kommandozeile - geloescht
 * wird also nach genau derselben Regel ("nur eine Ablage, die nichts mehr
 * weiss": Marke weg UND jede Datei byte-gleich mit dem Arbeitsbaum). Eine
 * zweite Fassung in JS liefe beim naechsten Sonderfall still auseinander.
 *
 * REIHENFOLGE: Node fuehrt `exit`-Handler in ANMELDE-Reihenfolge aus (nicht
 * rueckwaerts wie Pythons atexit). Die drei Harnesse legen synchron im
 * `finally` bzw. vor `process.exit` zurueck - danach laeuft dieser Handler.
 * Meldet ein Harness sein Zuruecklegen selbst als `exit`-Handler an, muss der
 * Aufruf hier DAHINTER stehen (sonst saehe er den sabotierten Baum und liesse
 * die Ablage liegen - sicher, aber nutzlos). Waechter:
 * tests/test_gegen_ablage.py (Wirkung + Regel am Syntaxbaum).
 *
 * Ein Abschuss per Signal fuehrt keine `exit`-Handler aus -> Ablage und Marke
 * bleiben, der naechste Start nimmt den Rueckstand zurueck (wie bisher).
 *
 *     const gegenAblage = require("./lib/gegen_ablage");
 *     gegenAblage.abraeumenBeimEnde(SICHERUNG, { marke: MARKE });
 */
"use strict";

const path = require("path");
const { spawnSync } = require("child_process");

const SKRIPT = path.join(__dirname, "gegen_ablage.py");

/** Sofort abraeumen (nach der Python-Regel); liefert true, wenn nichts mehr liegt. */
function abraeumen(ablage, optionen) {
    const o = optionen || {};
    const argv = [SKRIPT, String(ablage)];
    if (o.marke) argv.push("--marke", String(o.marke));
    if (o.wurzel) argv.push("--wurzel", String(o.wurzel));
    const r = spawnSync(process.env.PYTHON || "python3", argv, { encoding: "utf8", timeout: 60000 });
    if (r.error || r.status === null) {
        process.stderr.write("[gegen_ablage] Sicherung bleibt liegen: " + ablage
                             + " - Pruefung nicht startbar (" + (r.error ? r.error.code : "Zeitlimit") + ")\n");
        return false;
    }
    if (r.stderr) process.stderr.write(r.stderr);
    return r.status === 0;
}

/** Meldet das Abraeumen fuer das Prozessende an (siehe REIHENFOLGE). */
function abraeumenBeimEnde(ablage, optionen) {
    process.on("exit", () => {
        try { abraeumen(ablage, optionen); }
        catch (e) {  // Abraeumen darf das Ergebnis des Harness nie kippen
            process.stderr.write("[gegen_ablage] Sicherung bleibt liegen: " + ablage + " - " + e + "\n");
        }
    });
}

module.exports = { abraeumen, abraeumenBeimEnde };
