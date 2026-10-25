/* Die Werkzeuge der Waechter muessen auf dem Arbeitsplatz und in der CI
 * DIESELBE Fassung haben.
 *
 * ⚠ WARUM ES DIESEN WAECHTER GIBT. Die CI holte jsdom und acorn mit
 *   npm install --no-save jsdom acorn
 * also bei JEDEM Lauf die jeweils aktuelle Fassung, waehrend der Arbeitsplatz
 * seine installierte behielt. Am 2026-10-11 war genau dieser Unterschied
 * ZWEIMAL die Ursache fuer "lokal gruen, CI rot", und beide Male sah es wie
 * ein Produktfehler aus:
 *   · test_excel_addin_ui.js - die Untersuchung begann mit dem Verdacht auf
 *     jsdom 25 gegen 30 (es war dann doch ein festes Prueffenster).
 *   · test_review_niedrig_ui.js - DREI rote Laeufe. jsdom 30 expandiert
 *     `border:1px solid` spec-treu zu `border-color: currentcolor`, jsdom 25
 *     liess das Feld leer. Die Pruefung `!el.style.borderColor` kippte
 *     dadurch, obwohl das Markup unveraendert und richtig war.
 * Eine Fassungsdifferenz, die sich als Produktbefund tarnt, kostet jedes Mal
 * eine Fehlersuche am falschen Ende. Deshalb steht die Fassung jetzt in
 * package.json (ohne ^-Spanne), und dieser Waechter vergleicht sie mit dem,
 * was wirklich geladen wird.
 *
 * ⚠ GEMESSEN WIRD DAS GELADENE, NICHT DAS DEKLARIERTE. Gesucht wird ueber
 * dieselben Orte, die auch die Waechter benutzen (tests/lib/*_laden.js
 * exportieren ihre Suchliste als `orte`) - sonst prueft dieser Waechter eine
 * andere Installation als die, mit der gemessen wird.
 *
 * ⚠ DIE FASSUNG IST BEWUSST jsdom 25, NICHT 30. jsdom 30 verlangt
 * node >= 22.22.2; der Arbeitsplatz faehrt node 20, dort wuerde JEDER
 * JS-Waechter mit "webidl.util.markAsUncloneable is not a function" abbrechen
 * (am 2026-10-11 gemessen). Wer auf 30 hoch will, hebt zuerst node am
 * Arbeitsplatz und aendert dann package.json - dieser Waechter meldet die
 * Abweichung, bis beides zusammenpasst.
 *
 * Exit 0 = Fassungen stimmen · 1 = Abweichung · 2 = konnte nicht laufen
 */
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require("fs");
const path = require("path");

const WURZEL = path.resolve(__dirname, "..");
let ok = 0, fail = 0;

function check(name, bedingung, detail) {
    if (bedingung) { ok++; console.log("  OK   " + name); }
    else { fail++; console.log("  FAIL " + name + (detail ? " – " + detail : "")); }
}
function abbruch(grund) {
    console.log("ABBRUCH (konnte nicht laufen): " + grund);
    process.exit(2);
}

/* ── Der Pin ──────────────────────────────────────────────────────────────── */
let pin;
try {
    pin = JSON.parse(fs.readFileSync(path.join(WURZEL, "package.json"), "utf8"));
} catch (e) {
    abbruch("package.json im Wurzelverzeichnis nicht lesbar: " + e.message);
}
const erwartet = (pin && pin.devDependencies) || {};
if (!Object.keys(erwartet).length) {
    abbruch("package.json nennt keine devDependencies - ohne Pin ist hier nichts zu messen");
}

/* Positivkontrolle VOR den inhaltlichen Pruefungen: ein Pin mit Spanne ist
 * kein Pin. "^25.0.1" wuerde jede 25.x zulassen und die Differenz wieder
 * zufaellig machen. */
const mitSpanne = Object.entries(erwartet).filter(([, v]) => /[\^~*x><|| ]/.test(v));
if (mitSpanne.length) {
    abbruch("Pin mit Spanne statt fester Fassung: "
            + mitSpanne.map(([n, v]) => n + "@" + v).join(", ")
            + " - eine Spanne macht Arbeitsplatz und CI wieder verschieden.");
}
console.log("Pin aus package.json: "
            + Object.entries(erwartet).map(([n, v]) => n + "@" + v).join(", "));

/* ── Das Installierte, gefunden wie die Waechter es finden ───────────────── */
function fassungVon(paket, lader) {
    let orte = [];
    try { orte = require(lader).orte() || []; } catch (e) { /* unten gemeldet */ }
    for (const ort of orte.filter(Boolean)) {
        for (const p of [path.join(ort, "package.json"),
                         path.join(ort, "..", paket, "package.json")]) {
            try {
                const v = JSON.parse(fs.readFileSync(p, "utf8"));
                if (v && v.name === paket && v.version) return { fassung: v.version, ort: p };
            } catch (e) { /* naechster Ort */ }
        }
    }
    // Rueckfall: die gewoehnliche Modulaufloesung von Node.
    try {
        const p = require.resolve(paket + "/package.json", { paths: [WURZEL] });
        return { fassung: JSON.parse(fs.readFileSync(p, "utf8")).version, ort: p };
    } catch (e) { return null; }
}

const LADER = { jsdom: "./lib/jsdom_laden", acorn: "./lib/acorn_laden" };
const gefunden = {};
for (const paket of Object.keys(erwartet)) {
    const t = fassungVon(paket, LADER[paket] || "./lib/jsdom_laden");
    if (!t) {
        abbruch("Paket " + paket + " ist nirgends installiert. Nachholen mit:\n"
                + "         npm install --no-save --no-audit --no-fund   (im Repo-Wurzelverzeichnis)");
    }
    gefunden[paket] = t;
}

/* ── Der Vergleich ───────────────────────────────────────────────────────── */
for (const [paket, soll] of Object.entries(erwartet)) {
    const ist = gefunden[paket];
    check(paket + ": installiert " + ist.fassung + " == Pin " + soll,
          ist.fassung === soll,
          "installiert " + ist.fassung + " aus " + ist.ort.replace(WURZEL + "/", "")
          + "\n       Abgleichen mit: npm install --no-save --no-audit --no-fund"
          + "\n       (oder package.json bewusst aendern - dann sagt diese Zeile, worauf)");
}

/* Die CI darf die Fassungen NICHT mehr auf der Kommandozeile nennen, sonst
 * ueberstimmt sie den Pin still. Das ist eine REGEL, keine Messung. */
const WF = path.join(WURZEL, ".github", "workflows", "sicherheit.yml");
let wf = "";
try { wf = fs.readFileSync(WF, "utf8"); } catch (e) {
    abbruch("sicherheit.yml nicht lesbar: " + e.message);
}
const npmZeilen = wf.split("\n").filter(z => /npm install/.test(z) && !/^\s*#/.test(z));
check("Positivkontrolle: npm-install-Zeile(n) in sicherheit.yml gefunden",
      npmZeilen.length > 0, "gefunden: " + npmZeilen.length);
if (!npmZeilen.length) abbruch("keine npm-install-Zeile gefunden - die Regel waere trivial wahr.");
for (const z of npmZeilen) {
    const nennt = Object.keys(erwartet).filter(p => new RegExp("\\b" + p + "\\b").test(z));
    check("sicherheit.yml nennt keine Paketfassung auf der Kommandozeile",
          nennt.length === 0,
          "nennt " + nennt.join(", ") + " in: " + z.trim());
}

console.log("\nErgebnis: " + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
