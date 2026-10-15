#!/usr/bin/env node
/* Gegenprobe zu tests/test_prolog_vollstaendig.js – BEISST der Waechter?
 *
 * Eine Gegenprobe, die nicht beisst, ist ein Testmangel, kein Beweis. Gedreht
 * wird je Probe genau EINE Eigenschaft, und zwar so, dass klar ist, WELCHE
 * Pruefung sie treffen muss.
 *
 * ⚠ ZWEI SORTEN, SAUBER GETRENNT – dieselbe Trennung wie in
 * `gegen_keine_externen_einbindungen`:
 *   · PRODUKT-Sabotage (ein neuer Helfer in einer geschnittenen Funktion)
 *     -> Exit 1 mit einem Befund. Das ist die Fehlerklasse selbst.
 *   · WERKZEUG-Sabotage (der Analysator wird blind, zu breit, oder die
 *     Einteilung verrutscht) -> Exit 2 und Abbruch. Ein Waechter muss seine
 *     eigene Defektheit nach Exit 2 melden, nicht nach Exit 1 (Register).
 *
 * ⚠ DER WAECHTER LAEUFT JE PROBE RUND SIEBEN MINUTEN (er faehrt 85
 * Pruefstaende wirklich). Die Werkzeug-Proben brechen in Abschnitt 1 ab und
 * sind in Sekunden durch; nur die Produkt-Probe kostet den vollen Lauf.
 * Gesamtdauer deshalb rund 15 Minuten.
 *
 * ⚠ VERFAHREN (aus dem Register bezahlter Vorfaelle):
 * · Ohne gruenen Basislauf ist keine Gegenprobe deutbar -> Abbruch Exit 2.
 * · Jede Datei, die eine Probe anfasst, wird VORHER auf Platte gesichert –
 *   ins HOME (0700), nicht in ein festes /tmp/<name> (1777, stirbt am Tag nach
 *   einem Lauf unter fremdem Benutzer). Die Liste wird als REGEL geprueft.
 * · Eine Laufmarke ueberlebt ein `kill -9`; beim naechsten Start wird der
 *   Rueckstand zuerst zurueckgenommen. `kill` fuehrt kein atexit aus.
 * · Nach dem Zuruecknehmen wird Byte-Gleichheit per md5 NACHGESEHEN.
 *
 * Lauf:  node tests/gegen_prolog_vollstaendig.js
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const { spawnSync } = require("child_process");

const WURZEL = path.resolve(__dirname, "..");
const WAECHTER = path.join("tests", "test_prolog_vollstaendig.js");
const WERKZEUG = path.join("tests", "lib", "prolog_pruefen.js");
const SICHERUNG = path.join(os.homedir(), ".gegen_prolog_sicherung");
const MARKE = path.join(SICHERUNG, "LAUF_AKTIV");

const PROBEN = [
    {
        /* ⚠ DIE FEHLERKLASSE SELBST: ein neuer Helfer wird auf Modulebene
         * DEKLARIERT und in einer geschnittenen Funktion GERUFEN – genau das,
         * was am 2026-10-11 mit `_bildMimeAusBytes` und am 2026-09-29 mit
         * `_selMode`/`_selIds` passiert ist. Der Aufruf steht in einem Zweig,
         * den KEIN Testfall betritt (`file.name` endet nie auf `.zzz`): ein
         * Sammellauf bleibt deshalb gruen, dieser Waechter darf das nicht.
         *
         * ⚠ BEIDE HAELFTEN SIND NOETIG, und die erste Fassung hatte nur die
         * zweite – sie blieb STUMM, voellig zu Recht. Ein Aufruf auf einen
         * Namen, den der Produktivcode NIRGENDS deklariert, ist ein Fehler im
         * Produkt und kein verlorener Schnitt; die Einteilung schickt ihn
         * darum in die Umgebung. Eine Gegenprobe muss die Stelle treffen, die
         * sie MEINT (Register) – und der echte Vorgang bringt die Deklaration
         * immer mit. */
        name: "neuer Helfer in einer geschnittenen Funktion (die Fehlerklasse)",
        datei: "frontend/js/chat.js",
        um: (s) => s
            .replace("    function _bildMimeAusBytes(b64) {",
                     "    function _nochNichtImProlog(x) { return String(x).length; }\n"
                     + "    function _bildMimeAusBytes(b64) {")
            .replace("            const mimeEff = _bildMimeAusBytes(b64) || mime;",
                     "            if (file.name.endsWith('.zzz')) { _nochNichtImProlog(b64); }\n"
                     + "            const mimeEff = _bildMimeAusBytes(b64) || mime;"),
        erwartet: /kein Prolog verliert einen Namen/,
        art: "produkt",
    },
    {
        // Der Analysator findet nichts mehr -> 85-mal "keine Luecke" waere
        // Entwarnung. Treffen muss es die Probequelle, nicht die Bilanz.
        name: "der Analysator wird blind (keine Referenzen mehr)",
        datei: WERKZEUG,
        um: (s) => s.replace("        if (!treffer.has(k.name)) treffer.set(k.name, k.loc.start.line);",
                             "        return;"),
        erwartet: /Probequelle 1: die EINE echte Referenz wird gefunden/,
        art: "werkzeug",
    },
    {
        // Die andere Richtung, und die teurere: ein zu BREITES Werkzeug meldet
        // jede Erwaehnung und wird binnen einer Woche abgeschaltet.
        name: "der Analysator wird zu breit (nichts gilt als gebunden)",
        datei: WERKZEUG,
        um: (s) => s.replace("function gebundene(wurzel) {\n    const namen = new Set();",
                             "function gebundene(wurzel) {\n    const namen = new Set();\n    if (wurzel) return namen;"),
        erwartet: /Probequelle 2: sauberer Code meldet nichts/,
        art: "werkzeug",
    },
    {
        /* `arguments` war hier ein echter Fehlalarm. Wer die Zeile entfernt,
         * bekommt ihn zurueck – ueber voellig richtigem Code. */
        name: "`arguments` gilt wieder als ungebunden (alter Fehlalarm)",
        datei: WERKZEUG,
        um: (s) => s.replace('            namen.add("arguments");', "            ;"),
        erwartet: /Probequelle 4: `arguments` und der Name eines/,
        art: "werkzeug",
    },
    {
        /* Der zweite echte Fehlalarm: der Name eines Klassenausdrucks. Er traf
         * drei Pruefstaende, die gar nichts schneiden. */
        name: "der Name eines Klassenausdrucks gilt wieder als ungebunden",
        datei: WERKZEUG,
        um: (s) => s.replace(
            'if ((k.type === "FunctionExpression" || k.type === "ClassExpression") && k.id) {',
            'if ((k.type === "FunctionExpression") && k.id) {'),
        erwartet: /Probequelle 4: `arguments` und der Name eines/,
        art: "werkzeug",
    },
    {
        /* Die EINTEILUNG ist der Kern: ohne sie waere die Regel entweder blind
         * (alles Umgebung) oder unbrauchbar laut (36 Dateien, so gemessen).
         * Hier gilt jeder fehlende Name als Schnitt-Luecke. */
        name: "die Einteilung verrutscht (jeder Umgebungsname gilt als Schnitt)",
        datei: WERKZEUG,
        um: (s) => s.replace('    if (index.deklariert.has(name)) return "schnitt";\n    return "umgebung";',
                             '    return "schnitt";'),
        erwartet: /ein Browser-Name \(`fetch`\) gilt als Umgebung/,
        art: "werkzeug",
    },
    {
        /* Ohne Beobachtung am `window.eval` sieht der Waechter nichts – und
         * "nichts gesehen" muss von "nichts gefunden" unterscheidbar sein.
         * Sabotiert wird die EINHAENGUNG, nicht der Analysator. */
        name: "die Beobachtung haengt nicht mehr an window.eval",
        datei: WERKZEUG,
        um: (s) => s.replace("    const echtEval = window.eval;",
                             "    const echtEval = window.eval;\n    if (window) return;"),
        erwartet: /die Beobachtung haengt an window\.eval/,
        art: "werkzeug",
    },
];

/* ── REGEL statt Liste: jede angefasste Datei muss gesichert werden ────────── */
const DATEIEN = [...new Set(PROBEN.map(p => p.datei))];
const ungesichert = PROBEN.map(p => p.datei).filter(d => !DATEIEN.includes(d));
if (ungesichert.length) {
    console.log("ABBRUCH: Probe fasst ungesicherte Datei an: " + ungesichert.join(", "));
    process.exit(2);
}
for (const d of DATEIEN) {
    if (!fs.existsSync(path.join(WURZEL, d))) {
        console.log("ABBRUCH: Probe zeigt auf eine Datei, die es nicht gibt: " + d);
        process.exit(2);
    }
}

const md5 = (p) => crypto.createHash("md5").update(fs.readFileSync(p)).digest("hex");
const ablage = (d) => path.join(SICHERUNG, d.replace(/[/\\]/g, "__"));

function sichern() {
    fs.mkdirSync(SICHERUNG, { recursive: true, mode: 0o700 });
    for (const d of DATEIEN) fs.copyFileSync(path.join(WURZEL, d), ablage(d));
    fs.writeFileSync(MARKE, new Date().toISOString());
}
function zurueck() {
    const abweichend = [];
    for (const d of DATEIEN) {
        const ziel = path.join(WURZEL, d), quelle = ablage(d);
        if (!fs.existsSync(quelle)) continue;
        fs.copyFileSync(quelle, ziel);
        if (md5(ziel) !== md5(quelle)) abweichend.push(d);
    }
    return abweichend;
}

if (fs.existsSync(MARKE)) {
    console.log("HINWEIS: Laufmarke gefunden – ein frueherer Lauf wurde abgeschossen. "
                + "Rueckstand wird zuerst zurueckgenommen.");
    zurueck();
    fs.unlinkSync(MARKE);
}

function waechter() {
    const lauf = spawnSync(process.execPath, [WAECHTER],
                           { cwd: WURZEL, encoding: "utf8", timeout: 1800000 });
    const aus = (lauf.stdout || "") + (lauf.stderr || "");
    return {
        code: lauf.status, aus,
        fails: (aus.match(/^  FAIL /gm) || []).length,
        fehlzeilen: (aus.match(/^  FAIL .*$/gm) || []),
    };
}

/* ═══ Basislauf ═══════════════════════════════════════════════════════════ */
console.log("═══ Basislauf (muss gruen sein, sonst ist keine Probe deutbar)");
const basis = waechter();
console.log("  Exit " + basis.code + ", " + basis.fails + " FAIL");
if (basis.code !== 0 || basis.fails !== 0) {
    console.log("\nABBRUCH: Basislauf ist NICHT gruen – jede Probe zaehlte sonst eine FAIL "
                + "zu viel. Exit 2 = konnte nicht laufen.");
    console.log(basis.fehlzeilen.join("\n"));
    process.exit(2);
}

/* ═══ Die Proben ══════════════════════════════════════════════════════════ */
sichern();
let gebissen = 0, stumm = 0;
const ergebnisse = [];
try {
    for (const probe of PROBEN) {
        const ziel = path.join(WURZEL, probe.datei);
        const vorher = fs.readFileSync(ziel, "utf8");
        const nachher = probe.um(vorher);

        console.log("\n═══ Probe (" + probe.art + "): " + probe.name);
        console.log("    (" + probe.datei + ")");
        if (nachher === vorher) {
            console.log("  ✗ PROBE GREIFT NICHT: der Umbau hat die Datei nicht veraendert "
                        + "(Anker veraltet?)");
            stumm++; ergebnisse.push([probe.name, "PROBE DEFEKT"]);
            continue;
        }
        fs.writeFileSync(ziel, nachher);
        const lauf = waechter();
        fs.writeFileSync(ziel, vorher);

        const inFails = probe.erwartet.test(lauf.fehlzeilen.join("\n"));
        const erwarteterCode = probe.art === "werkzeug" ? 2 : 1;
        if (lauf.code === erwarteterCode && inFails) {
            console.log("  ✓ gebissen: Exit " + lauf.code + ", " + lauf.fails + " FAIL");
            lauf.fehlzeilen.slice(0, 2).forEach(z => console.log("      " + z.trim()));
            gebissen++;
            ergebnisse.push([probe.name, "gebissen (Exit " + lauf.code + ")"]);
        } else {
            console.log("  ✗ STUMM: Exit " + lauf.code + " (erwartet " + erwarteterCode + "), "
                        + lauf.fails + " FAIL – die erwartete Pruefung hat nicht angeschlagen");
            lauf.fehlzeilen.slice(0, 3).forEach(z => console.log("      " + z.trim()));
            stumm++; ergebnisse.push([probe.name, "STUMM"]);
        }
    }
} finally {
    const abweichend = zurueck();
    if (fs.existsSync(MARKE)) fs.unlinkSync(MARKE);
    console.log("\n═══ Zuruecknehmen");
    if (abweichend.length) {
        console.log("  ✗ ACHTUNG: nicht byte-gleich wiederhergestellt: " + abweichend.join(", "));
        process.exitCode = 1;
    } else {
        console.log("  ✓ alle " + DATEIEN.length + " Dateien byte-gleich wiederhergestellt (md5)");
    }
}

console.log("\n" + "═".repeat(70));
ergebnisse.forEach(([n, e]) => console.log("  " + (e.startsWith("gebissen") ? "✓" : "✗")
                                          + " " + e.padEnd(20) + n));
console.log("\nErgebnis: " + gebissen + " von " + PROBEN.length + " Proben haben gebissen"
            + (stumm ? ", " + stumm + " STUMM" : ""));
if (stumm) {
    console.log("Eine stumme Probe ist ein TESTMANGEL des Waechters – kein Beweis.");
    process.exit(1);
}
process.exit(process.exitCode || 0);
