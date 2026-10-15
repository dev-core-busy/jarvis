#!/usr/bin/env node
/* Gegenprobe zu tests/test_jsdom_einbindung.js – BEISST der Waechter?
 *
 * Eine Gegenprobe, die nicht beisst, ist ein Testmangel, kein Beweis. Gedreht
 * wird deshalb je Probe genau EINE Eigenschaft zurueck, und zwar so, dass klar
 * ist, WELCHE Pruefung sie treffen muss.
 *
 * ⚠ VERFAHREN (aus dem Register bezahlter Vorfaelle):
 * · Ohne gruenen Basislauf ist keine Gegenprobe deutbar → Abbruch mit Exit 2.
 * · Jede Datei, die eine Probe anfasst, wird VORHER auf Platte gesichert – auch
 *   die Waechterdatei selbst, falls eine Probe sie betrifft. Die Liste wird als
 *   REGEL geprueft, nicht gepflegt.
 * · Eine Laufmarke ueberlebt ein `kill -9`: beim naechsten Start wird der
 *   Rueckstand zuerst zurueckgenommen.
 * · Nach jedem Zuruecknehmen wird Byte-Gleichheit per md5 NACHGESEHEN, nicht
 *   angenommen.
 * · Gesichert wird ins HOME (0700), nicht in ein festes /tmp/<name> – das ist
 *   1777 und stirbt am Tag nach einem Lauf unter fremdem Benutzer.
 *
 * Lauf:  node tests/gegen_jsdom_einbindung.js
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const { spawnSync } = require("child_process");

const WURZEL = path.resolve(__dirname, "..");
const WAECHTER = path.join("tests", "test_jsdom_einbindung.js");
const SICHERUNG = path.join(os.homedir(), ".gegen_jsdom_sicherung");
const MARKE = path.join(SICHERUNG, "LAUF_AKTIV");

/* ── Proben: [Name, Datei, Umbau, welche Pruefung treffen muss] ────────────── */
const PROBEN = [
    {
        name: "hartes require zurueck (die Fehlerklasse selbst)",
        datei: "tests/test_activity_ui.js",
        um: (s) => s.replace("const { JSDOM } = require('./lib/jsdom_laden')();",
                             "const { JSDOM } = require(process.env.JSDOM_PATH "
                             + "|| '/tmp/node_modules/jsdom');"),
        erwartet: /keine Datei bindet jsdom direkt ein/,
    },
    {
        name: "nacktes require('jsdom') statt der gemeinsamen Quelle",
        datei: "tests/test_theme_default.js",
        um: (s) => s.replace("const { JSDOM } = require('./lib/jsdom_laden')();",
                             "const { JSDOM } = require('jsdom');"),
        erwartet: /keine Datei bindet jsdom direkt ein/,
    },
    {
        name: "Abbruch mit Exit 0 statt 2 ('konnte nicht laufen' sieht aus wie bestanden)",
        datei: "tests/lib/jsdom_laden.js",
        um: (s) => s.replace("process.exit(2);\n}", "process.exit(0);\n}"),
        erwartet: /jede Datei endet ohne jsdom mit Exit 2/,
    },
    {
        name: "Abbruch mit Exit 1 statt 2 (sieht aus wie 'Waechter beisst')",
        datei: "tests/lib/jsdom_laden.js",
        um: (s) => s.replace("process.exit(2);\n}", "process.exit(1);\n}"),
        erwartet: /jede Datei endet ohne jsdom mit Exit 2/,
    },
    {
        name: "Stacktrace statt lesbarer Meldung (der Lader wirft durch)",
        datei: "tests/lib/jsdom_laden.js",
        um: (s) => s.replace("            if (!fehltNur) throw e;", "            throw e;"),
        erwartet: /keine Datei wirft dabei einen Stacktrace/,
    },
    {
        name: "ein Suchort fehlt (<HOME>/sleek)",
        datei: "tests/lib/jsdom_laden.js",
        um: (s) => s.replace('        HOME && path.join(HOME, "sleek/node_modules/jsdom"),\n', ""),
        erwartet: /gesucht wird <HOME>\/sleek\/node_modules\/jsdom/,
    },
    {
        name: "JSDOM_PATH verliert den Vorrang",
        datei: "tests/lib/jsdom_laden.js",
        um: (s) => s.replace('        process.env.JSDOM_PATH,                           '
                             + '// ausdrueckliche Vorgabe\n        "jsdom",',
                             '        "jsdom",\n        process.env.JSDOM_PATH,'),
        erwartet: /JSDOM_PATH hat Vorrang/,
    },
    {
        name: "der Exit-Code wird von einem exit-Handler ueberschrieben",
        datei: "tests/test_lic_panel_ui.js",
        um: (s) => s.replace("process.on('exit', (code) => {", "process.on('exit', () => {")
                    .replace("if (!bilanz && code === 0) {", "if (!bilanz) {"),
        erwartet: /jede Datei endet ohne jsdom mit Exit 2/,
    },
    {
        // Positivkontrolle der Positivkontrolle: nimmt man dem Messwerkzeug die
        // Wirkung, muss Abschnitt 1 das MELDEN – sonst waeren 3 und 4 trivial gruen.
        name: "das Messwerkzeug nimmt jsdom NICHT mehr weg",
        datei: "tests/lib/ohne_jsdom.js",
        um: (s) => s.replace("    if (typeof anfrage === \"string\" && JSDOM_ANFRAGE.test(anfrage)) {",
                             "    if (false) {"),
        erwartet: /das Messwerkzeug nimmt jsdom wirklich weg/,
    },
    {
        /* ⚠ DIE GESTALT, FUER DIE DER WAECHTER AM 2026-10-10 BLIND WAR.
         * Die Probe darueber ("hartes require zurueck") setzt ein LITERAL ein –
         * die alte Textpruefung auf das require-Argument hat die gefunden. Hier
         * ist das Argument eine VARIABLE (`require(kandidat)`), der Argumenttext
         * also "kandidat": kein Treffer, kein Fund, und die Datei fiel komplett
         * aus Abschnitt 2 UND 3. 29 Dateien standen so da. Diese Probe wuerde
         * vor der Umstellung STUMM bleiben – sie ist der Beleg, dass die neuen
         * Wege (.JSDOM / Kandidatenliste) tragen. Die Gestalt ist die echte aus
         * tests/test_alpha_sort_ui.js, nicht erfunden. */
        name: "eigene Suchschleife mit VARIABLEM require-Argument (die blinde Gestalt)",
        datei: "tests/test_alpha_sort_ui.js",
        um: (s) => s.replace("const { JSDOM } = require('./lib/jsdom_laden')();",
            "let JSDOM = null;\n"
            + "for (const kandidat of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom']) {\n"
            + "    if (!kandidat) continue;\n"
            + "    try { JSDOM = require(kandidat).JSDOM; break; } catch (e) { /* naechster */ }\n"
            + "}\n"
            + "if (!JSDOM) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }"),
        erwartet: /keine Datei bindet jsdom direkt ein/,
    },
    {
        /* Die drei folgenden Proben zielen auf das MESSWERKZEUG des Waechters,
         * nicht auf das Produkt – deshalb ist Exit 2 die erwartete Antwort und
         * nicht ein FAIL (Register: ein Waechter muss seine eigene Defektheit
         * nach Exit 2 melden, sonst sieht "ich kann nicht messen" aus wie "ich
         * beisse"). Ohne sie waere die Positivkontrolle in Abschnitt 1a
         * Dekoration. */
        name: "dem Werkzeug den Weg 'Kandidatenliste' nehmen",
        datei: WAECHTER,
        um: (s) => s.replace('    if (arg.type !== "Identifier") return false;\n'
                             + "    for (let k = eltern.get(aufruf); k; k = eltern.get(k)) {",
                             "    return false;\n"
                             + "    for (let k = eltern.get(aufruf); k; k = eltern.get(k)) {"),
        erwartet: /Probequelle 1: die Schleife ueber Kandidatenpfade wird gefunden/,
    },
    {
        name: "dem Werkzeug den Weg '.JSDOM' nehmen",
        datei: WAECHTER,
        um: (s) => s.replace("    const p = eltern.get(aufruf);\n    if (!p) return false;",
                             "    const p = eltern.get(aufruf);\n    if (p) return false;"),
        erwartet: /Probequelle 2: ein require\(\) mit variablem Argument/,
    },
    {
        /* ⚠ DIE ANDERE RICHTUNG, und die teurere: ein zu BREITES Werkzeug ist
         * dauerhaft gruen. Mit `return true` gilt jede Erwaehnung als Einbindung
         * – genau der Mangel, der test_js_einbindung.py beinahe zahnlos gemacht
         * hat und den eine Pruefung mit einem erfundenen Namen NICHT sehen kann. */
        name: "das Werkzeug trivial wahr machen (jede Erwaehnung zaehlt)",
        datei: WAECHTER,
        um: (s) => s.replace("    return /jsdom/i.test(t) || /JSDOM_PATH/.test(t);",
                             "    return true;"),
        erwartet: /Probequelle 3: blosse Erwaehnungen zaehlen NICHT/,
    },
];

/* ── REGEL statt Liste: jede angefasste Datei muss gesichert werden ────────── */
const DATEIEN = [...new Set(PROBEN.map(p => p.datei))];
const fehltInSicherung = [...new Set(PROBEN.map(p => p.datei))].filter(d => !DATEIEN.includes(d));
if (fehltInSicherung.length) {
    console.log("ABBRUCH: Probe fasst ungesicherte Datei an: " + fehltInSicherung.join(", "));
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

/* ── Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen ────────────── */
if (fs.existsSync(MARKE)) {
    console.log("HINWEIS: Laufmarke gefunden – ein frueherer Lauf wurde abgeschossen. "
                + "Rueckstand wird zurueckgenommen.");
    zurueck();
    fs.unlinkSync(MARKE);
}

/** Laesst den Waechter laufen. */
function waechter() {
    const lauf = spawnSync(process.execPath, [WAECHTER],
                           { cwd: WURZEL, encoding: "utf8", timeout: 900000 });
    const aus = (lauf.stdout || "") + (lauf.stderr || "");
    return {
        code: lauf.status,
        aus,
        fails: (aus.match(/^  FAIL /gm) || []).length,
        fehlzeilen: (aus.match(/^  FAIL .*$/gm) || []),
    };
}

/* ═══ Basislauf: ohne gruene Basis ist keine Probe deutbar ═════════════════ */
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

        console.log("\n═══ Probe: " + probe.name);
        console.log("    (" + probe.datei + ")");
        if (nachher === vorher) {
            // Eine Sabotage, die nichts aendert, belegt nichts – das ist ein
            // Mangel der PROBE und muss auffallen, nicht durchlaufen.
            console.log("  ✗ PROBE GREIFT NICHT: der Umbau hat die Datei nicht veraendert "
                        + "(Anker veraltet?)");
            stumm++; ergebnisse.push([probe.name, "PROBE DEFEKT"]);
            continue;
        }
        fs.writeFileSync(ziel, nachher);
        const lauf = waechter();
        fs.writeFileSync(ziel, vorher);

        const traf = probe.erwartet.test(lauf.aus.split("\n")
                         .filter(z => z.startsWith("  FAIL")).join("\n"))
                     || (lauf.code === 2 && probe.erwartet.test(lauf.aus));
        if (lauf.fails > 0 && traf) {
            console.log("  ✓ gebissen: Exit " + lauf.code + ", " + lauf.fails + " FAIL");
            lauf.fehlzeilen.slice(0, 3).forEach(z => console.log("      " + z.trim()));
            gebissen++; ergebnisse.push([probe.name, "gebissen (" + lauf.fails + " FAIL)"]);
        } else if (lauf.code === 2 && probe.erwartet.test(lauf.aus)) {
            console.log("  ✓ gebissen: Exit 2 (Positivkontrolle verweigert die Messung)");
            gebissen++; ergebnisse.push([probe.name, "gebissen (Exit 2)"]);
        } else {
            console.log("  ✗ STUMM: Exit " + lauf.code + ", " + lauf.fails + " FAIL – "
                        + "die erwartete Pruefung hat nicht angeschlagen");
            if (lauf.fehlzeilen.length) lauf.fehlzeilen.forEach(z => console.log("      " + z.trim()));
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

/* ── Bilanz ──────────────────────────────────────────────────────────────── */
console.log("\n" + "═".repeat(70));
ergebnisse.forEach(([n, e]) => console.log("  " + (e.startsWith("gebissen") ? "✓" : "✗")
                                          + " " + e.padEnd(22) + n));
console.log("\nErgebnis: " + gebissen + " von " + PROBEN.length + " Proben haben gebissen"
            + (stumm ? ", " + stumm + " STUMM" : ""));
if (stumm) {
    console.log("Eine stumme Probe ist ein TESTMANGEL des Waechters – kein Beweis.");
    process.exit(1);
}
process.exit(process.exitCode || 0);
