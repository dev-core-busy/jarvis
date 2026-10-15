#!/usr/bin/env node
/* Gegenprobe zu tests/test_waechter_bilanz.js – BEISST der Waechter?
 *
 * Eine Gegenprobe, die nicht beisst, ist ein Testmangel, kein Beweis. Besonders
 * hier: Teil 2 der Regel ist heute GRUEN ("kein ungedeckter Exit-2-Weg"), und
 * eine gruene Pruefung ohne Gegenprobe ist nur eine Behauptung. Gedreht wird je
 * Probe genau EINE Eigenschaft.
 *
 * ⚠ VERFAHREN (aus dem Register bezahlter Vorfaelle):
 * · Ohne gruenen Basislauf ist keine Gegenprobe deutbar. Dieser Waechter ist
 *   heute ABSICHTLICH rot (82 Dateien ohne Absturzweg), also wird nicht der
 *   Exitcode als Basis genommen, sondern die ZAHLEN der Bilanzzeile – und die
 *   muessen vor jeder Probe reproduzierbar sein.
 * · Jede Datei, die eine Probe anfasst, wird VORHER auf Platte gesichert. Die
 *   Liste wird als REGEL geprueft, nicht gepflegt.
 * · Eine Laufmarke ueberlebt ein `kill -9`: beim naechsten Start wird der
 *   Rueckstand zuerst zurueckgenommen.
 * · Nach jedem Zuruecknehmen wird Byte-Gleichheit per md5 NACHGESEHEN.
 * · Gesichert wird ins HOME (0700), nicht nach /tmp (1777).
 * · ⚠ DIESE DATEI DARF NIE IN EINEM SAMMELLAUF UEBER tests/*.js MITLAUFEN –
 *   sie patcht Dateien; ein `timeout`, das sie mitten in einer Probe
 *   abschiesst, laesst den Rueckstand im Arbeitsbaum stehen.
 *
 * Lauf:  node tests/gegen_waechter_bilanz.js
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');

const WURZEL = path.resolve(__dirname, '..');
const WAECHTER = path.join('tests', 'test_waechter_bilanz.js');
const SICHERUNG = path.join(os.homedir(), '.gegen_waechter_bilanz');
const MARKE = path.join(SICHERUNG, 'LAUF_AKTIV');

const md5 = (p) => crypto.createHash('md5')
    .update(fs.readFileSync(path.join(WURZEL, p))).digest('hex');

/* ── Proben ───────────────────────────────────────────────────────────────── */
const PROBEN = [
    {
        // Teil 2: die Fehlerklasse des Registers selbst. `test_viol_filter_ui`
        // hat ein BLINDES Netz; sein einziger Exit-2-Weg liegt VOR dem Netz und
        // ist damit gedeckt. Hier kommt ein ungedeckter Weg DAHINTER.
        name: 'ungedeckter Exit-2-Weg unter einem blinden Netz',
        datei: 'tests/test_viol_filter_ui.js',
        um: (s) => s + '\nif (process.env.NIE_GESETZT) process.exit(2);\n',
        erwartet: /test_viol_filter_ui\.js: blindes Netz UND 1 ungedeckter Exit-2-Weg/,
    },
    {
        // Gegenstueck dazu: derselbe Weg, aber mit der Marke gedeckt – er darf
        // NICHT gemeldet werden. Ohne diese Probe wuesste man nicht, ob Teil 2
        // die Deckung ueberhaupt bemerkt oder einfach jedes exit(2) meldet.
        name: 'derselbe Weg MIT Marke gedeckt (darf nicht melden)',
        datei: 'tests/test_viol_filter_ui.js',
        um: (s) => s + '\nif (process.env.NIE_GESETZT) { bilanz = true; process.exit(2); }\n',
        erwartet: null,          // null = dieser Text darf NICHT auftauchen
        nicht: /test_viol_filter_ui\.js: blindes Netz UND/,
    },
    {
        // Teil 3 misst wirklich die EIGENSCHAFT und nicht eine Namensliste:
        // wer die eine Quelle einbindet, verschwindet aus der Mangelliste.
        name: 'lib/bilanz eingebunden -> Teil 3 meldet die Datei nicht mehr',
        datei: 'tests/test_activity_ui.js',
        um: (s) => "require('./lib/bilanz')();\n" + s,
        erwartet: null,
        nicht: /test_activity_ui\.js: kein Absturzweg nach Exit 2/,
    },
];

/* REGEL statt gepflegter Liste: jede angefasste Datei muss gesichert werden. */
const DATEIEN = [...new Set(PROBEN.map(p => p.datei))];

/* ── Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen ───────────── */
function zurueck(wortreich) {
    let geholt = 0;
    for (const d of DATEIEN) {
        const sich = path.join(SICHERUNG, d.replace(/\//g, '__'));
        if (!fs.existsSync(sich)) continue;
        const ziel = path.join(WURZEL, d);
        if (fs.readFileSync(sich, 'utf8') !== fs.readFileSync(ziel, 'utf8')) {
            fs.copyFileSync(sich, ziel);
            geholt++;
            if (wortreich) console.log(`  zurueckgenommen: ${d}`);
        }
    }
    return geholt;
}

if (fs.existsSync(MARKE)) {
    console.log('⚠ Rueckstand eines abgebrochenen Laufs gefunden – nehme zurueck:');
    zurueck(true);
    fs.rmSync(MARKE, { force: true });
}

fs.mkdirSync(SICHERUNG, { recursive: true, mode: 0o700 });

/** Laeuft der Waechter und liefert Ausgabe + Kennzahlen. */
function lauf() {
    const r = spawnSync(process.execPath, [WAECHTER],
                        { cwd: WURZEL, encoding: 'utf8', timeout: 180000 });
    const aus = (r.stdout || '') + (r.stderr || '');
    const m = /(\d+) OK, (\d+) FAIL/.exec(aus.replace(/\x1b\[[0-9;]*m/g, ''));
    return { aus, ok: m ? +m[1] : null, fail: m ? +m[2] : null, code: r.status };
}

/* ── Basislauf: ohne reproduzierbare Zahlen ist keine Probe deutbar ───────── */
console.log('=== Basislauf ===');
const basis = lauf();
if (basis.ok === null) {
    console.log('ABBRUCH (Exit 2): der Waechter liefert keine Bilanzzeile.');
    console.log(basis.aus.slice(-800));
    process.exit(2);
}
console.log(`  Basis: ${basis.ok} OK, ${basis.fail} FAIL (Exit ${basis.code})`);
// Positivkontrolle: Teil 2 muss im Basislauf GRUEN sein, sonst misst Probe 1
// nichts (sie soll einen Uebergang gruen -> rot zeigen).
if (/ungedeckter Exit-2-Weg/.test(basis.aus.replace(/\x1b\[[0-9;]*m/g, '')) &&
    !/kein ungedeckter Exit-2-Weg/.test(basis.aus.replace(/\x1b\[[0-9;]*m/g, ''))) {
    console.log('ABBRUCH (Exit 2): Teil 2 ist schon im Basislauf rot – Probe 1 waere nicht deutbar.');
    process.exit(2);
}

/* ── Proben fahren ────────────────────────────────────────────────────────── */
let beissen = 0, stumpf = 0;
for (const d of DATEIEN) {
    fs.copyFileSync(path.join(WURZEL, d), path.join(SICHERUNG, d.replace(/\//g, '__')));
}
const VORHER = Object.fromEntries(DATEIEN.map(d => [d, md5(d)]));
fs.writeFileSync(MARKE, String(process.pid));

for (const p of PROBEN) {
    console.log(`\n=== Probe: ${p.name} ===`);
    const ziel = path.join(WURZEL, p.datei);
    const orig = fs.readFileSync(ziel, 'utf8');
    const neu = p.um(orig);
    if (neu === orig) {
        console.log('  ✗ SABOTAGE TRAF NICHT – die Probe sagt nichts aus.');
        stumpf++;
        continue;
    }
    fs.writeFileSync(ziel, neu);
    const r = lauf();
    const rein = r.aus.replace(/\x1b\[[0-9;]*m/g, '');

    if (p.erwartet) {
        const traf = p.erwartet.test(rein);
        console.log(traf ? `  ✓ BEISST – ${r.ok} OK, ${r.fail} FAIL`
                         : `  ✗ STUMPF – erwarteter Befund fehlt (${r.ok} OK, ${r.fail} FAIL)`);
        traf ? beissen++ : stumpf++;
    } else {
        const schlecht = p.nicht.test(rein);
        console.log(!schlecht ? `  ✓ richtig STILL – ${r.ok} OK, ${r.fail} FAIL`
                              : `  ✗ meldet trotzdem (${r.ok} OK, ${r.fail} FAIL)`);
        !schlecht ? beissen++ : stumpf++;
    }

    fs.writeFileSync(ziel, orig);
}

/* ── Zuruecknehmen und Byte-Gleichheit NACHSEHEN ──────────────────────────── */
console.log('\n=== Zuruecknehmen ===');
zurueck(false);
let abweichung = 0;
for (const d of DATEIEN) {
    const jetzt = md5(d);
    const gut = jetzt === VORHER[d];
    console.log(`  ${gut ? '✓' : '✗'} ${d} ${gut ? 'byte-gleich' : 'ABWEICHUNG: ' + jetzt}`);
    if (!gut) abweichung++;
}
fs.rmSync(MARKE, { force: true });

console.log('\n' + '='.repeat(70));
console.log(`Proben: ${PROBEN.length}   beissen/korrekt: ${beissen}   stumpf: ${stumpf}`);
if (abweichung) {
    console.log(`\x1b[31mRUECKSTAND: ${abweichung} Datei(en) nicht zurueckgesetzt\x1b[0m`);
    process.exit(1);
}
console.log(stumpf === 0 ? '\x1b[32mAlle Proben wie erwartet.\x1b[0m'
                         : `\x1b[31m${stumpf} Probe(n) stumpf – der Waechter ist unfertig.\x1b[0m`);
process.exit(stumpf === 0 ? 0 : 1);
