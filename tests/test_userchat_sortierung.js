#!/usr/bin/env node
/**
 * Benutzerchat: Personenliste und Weiterleiten-Dialog stehen alphabetisch nach
 * dem ANGEZEIGTEN Namen (gemeldet 2026-11-09 im Zuge der Fehleranalyse-Liste).
 *
 * Der Login traegt mal einen Domaenen-Praefix ("firma\c.becker") und mal
 * nicht; angezeigt wird ohne. Sortiert wurde nach dem Login – der angezeigte
 * "c.becker" stand damit unter F, hinter "d.mai".
 *
 * Gemessen wird am ECHTEN Quelltext: `_displayName` und `_nameVergleich`
 * werden per acorn aus `userchat.js` geschnitten und ausgefuehrt; dazu eine
 * Regel am Syntaxbaum, dass beide Sortierstellen den Vergleicher benutzen und
 * kein `localeCompare` ausserhalb von ihm steht.
 *
 *   node tests/test_userchat_sortierung.js
 */
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const acorn = require('./lib/acorn_laden')();

let ok = 0, fail = 0;
const pruefe = (b, t, d) => { if (b) { ok++; console.log('  ✓ ' + t); }
                              else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); } };
let _bilanz = false;
process.on('exit', (c) => { if (!_bilanz && c === 0) {
    console.log('  ✗ ABBRUCH: keine Bilanzzeile – der Lauf ist vorzeitig beendet'); process.exitCode = 1; } });

const SRC = fs.readFileSync(path.join(ROOT, 'frontend/js/userchat.js'), 'utf8');
const AST = acorn.parse(SRC, { ecmaVersion: 'latest', sourceType: 'script' });

function alle(knoten, test, aus = [], eltern = []) {
    if (!knoten || typeof knoten.type !== 'string') return aus;
    if (test(knoten, eltern)) aus.push({ knoten, eltern: eltern.slice() });
    for (const k of Object.keys(knoten)) {
        const v = knoten[k];
        const kinder = Array.isArray(v) ? v : [v];
        for (const c of kinder) {
            if (c && typeof c.type === 'string') alle(c, test, aus, eltern.concat([knoten]));
        }
    }
    return aus;
}

const fn = (name) => alle(AST, n => n.type === 'FunctionDeclaration' && n.id && n.id.name === name);

// ── Positivkontrolle ─────────────────────────────────────────────────────
console.log('\n=== 0. Positivkontrolle ===');
const dn = fn('_displayName'), nv = fn('_nameVergleich');
if (dn.length !== 1 || nv.length !== 1) {
    console.log(`ABBRUCH: _displayName (${dn.length}) / _nameVergleich (${nv.length}) nicht genau einmal gefunden`);
    process.exit(2);
}
const code = SRC.slice(dn[0].knoten.start, dn[0].knoten.end) + '\n'
           + SRC.slice(nv[0].knoten.start, nv[0].knoten.end) + '\nreturn _nameVergleich;';
let vergleich;
try {
    vergleich = new Function('window', code)({ _lang: 'de' });
} catch (e) {
    console.log('ABBRUCH: geschnittene Funktionen nicht ausfuehrbar: ' + e.message);
    process.exit(2);
}
const LOGINS = ['zeta', 'firma\\e.wolf', 'd.mai', 'firma\\c.becker', 'b.schulz', 'Ärger'];
const ERWARTET = ['Ärger', 'b.schulz', 'firma\\c.becker', 'd.mai', 'firma\\e.wolf', 'zeta'];
// Die Probe muss den alten Fehler HERSTELLEN: nach dem Login sortiert kommt
// etwas anderes heraus – sonst waere jede Pruefung darunter trivial wahr.
const alt = LOGINS.slice().sort((a, b) => a.localeCompare(b));
if (JSON.stringify(alt) === JSON.stringify(ERWARTET)) {
    console.log('ABBRUCH: die Probe unterscheidet Login- und Anzeigesortierung nicht');
    process.exit(2);
}
pruefe(true, 'Probe trennt Login- von Anzeigesortierung');

// ── 1. Wirkung ───────────────────────────────────────────────────────────
console.log('\n=== 1. _nameVergleich ===');
const neu = LOGINS.slice().sort(vergleich);
pruefe(JSON.stringify(neu) === JSON.stringify(ERWARTET),
    'sortiert nach dem angezeigten Namen (Praefix zaehlt nicht)', JSON.stringify(neu));
pruefe(vergleich('user2', 'user10') < 0, 'Ziffern numerisch (user2 vor user10)');
pruefe(vergleich('B.Schulz', 'a.mueller') > 0, 'Gross/Klein entscheidet nicht');

// ── 2. Regel: beide Sortierstellen benutzen den Vergleicher ──────────────
console.log('\n=== 2. Sortierstellen ===');
const sortAufrufe = alle(AST, n => n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
    && !n.callee.computed && n.callee.property.name === 'sort' && n.arguments.length === 1);
const mitVergleicher = sortAufrufe.filter(({ knoten }) =>
    alle(knoten.arguments[0], n => n.type === 'CallExpression' && n.callee.type === 'Identifier'
        && n.callee.name === '_nameVergleich').length > 0);
pruefe(mitVergleicher.length >= 2,
    'Personenliste UND Weiterleiten-Dialog sortieren ueber _nameVergleich',
    `${mitVergleicher.length} von ${sortAufrufe.length} sort()-Aufrufen`);

const lc = alle(AST, n => n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
    && !n.callee.computed && n.callee.property.name === 'localeCompare');
const ausserhalb = lc.filter(({ eltern }) => !eltern.includes(nv[0].knoten));
pruefe(lc.length > 0 && ausserhalb.length === 0,
    'kein localeCompare ausserhalb von _nameVergleich (sonst sortiert dort wieder der Login)',
    ausserhalb.map(({ knoten }) => SRC.slice(knoten.start, knoten.end)).join(' | '));

console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
_bilanz = true;
process.exit(fail ? 1 : 0);
