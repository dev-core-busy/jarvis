#!/usr/bin/env node
/**
 * Waechter: kein Frontend-Modul ruft einen Bezeichner, den es an dieser Stelle
 * gar nicht sehen kann.
 *
 * ⚠ ZWEIMAL BEZAHLT, beide Male mit demselben Muster:
 *   - 2026-09-03: `_dlk()` stand in vier Modulen MITTEN in einer anderen
 *     Funktion. Syntaktisch einwandfrei, `node --check` schweigt - und jeder
 *     Aufruf ausserhalb lief in einen ReferenceError, den ein `catch`
 *     verschluckte (Panel behauptete "6 Dateien" und zeigte nichts).
 *   - 2026-08-19: bei der Symbol-Umstellung kam `title="${T('common.delete')}"`
 *     in `toggleLearnedList()`, das kein `T` deklariert. Drei Wochen lang
 *     brach damit "Einstellungen -> Wissen -> gelerntes Wissen -> anzeigen"
 *     mit "Fehler: T is not defined" ab.
 *
 * Der Vorgaenger `test_dlkey_reichweite.js` prueft NUR `_dlk` - eine gepflegte
 * Liste, die den zweiten Fall nicht sehen konnte. Dieser hier prueft die
 * EIGENSCHAFT fuer JEDEN lokal deklarierten Helfer: wird er dort gerufen, wo er
 * sichtbar ist?
 *
 * Ohne Parser gibt es keine Aussage: Exit 2, nicht 0.
 */
const fs = require('fs'), path = require('path');
const REPO = path.resolve(__dirname, '..');
let acorn = null;
for (const p of ['acorn', '/usr/share/nodejs/acorn',
                 path.join(REPO, 'node_modules/acorn'),
                 path.join(REPO, 'data/node_modules/acorn'),
                 '/tmp/node_modules/acorn']) {
    try { acorn = require(p); break; } catch (e) { /* weiter */ }
}
if (!acorn) {
    console.log('\x1b[31mABBRUCH: acorn nicht gefunden - ohne Parser keine Aussage.\x1b[0m');
    process.exit(2);
}
let OK = 0, FAIL = 0;
const check = (n, b) => { console.log((b ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + n); b ? OK++ : FAIL++; };

function kinder(n, fn) {
    for (const k in n) {
        if (k === 'loc' || k === 'start' || k === 'end') continue;
        const v = n[k];
        if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && fn(x));
        else if (v && typeof v.type === 'string') fn(v);
    }
}
const IST_FN = t => /^(FunctionDeclaration|FunctionExpression|ArrowFunctionExpression)$/.test(t);

/** Alle lokal deklarierten Namen (const/let/var/function) mit ihrem Gueltigkeitsbereich. */
function pruefeDatei(datei) {
    const src = fs.readFileSync(datei, 'utf8');
    let ast;
    try {
        ast = acorn.parse(src, { ecmaVersion: 2022, locations: true, sourceType: 'script' });
    } catch (e) {
        return { fehler: `nicht parsebar: ${e.message}` };
    }
    const dekl = [];   // {name, node}  - Deklarationen INNERHALB einer Funktion
    const rufe = [];   // {name, node, kette}
    (function geh(n, kette) {
        const neu = IST_FN(n.type) ? kette.concat([n]) : kette;
        if (n.type === 'VariableDeclarator' && n.id && n.id.type === 'Identifier' && neu.length)
            dekl.push({ name: n.id.name, node: n });
        if (n.type === 'FunctionDeclaration' && n.id && neu.length > 1)
            dekl.push({ name: n.id.name, node: n });
        if (n.type === 'CallExpression' && n.callee && n.callee.type === 'Identifier')
            rufe.push({ name: n.callee.name, node: n, kette: neu });
        kinder(n, x => geh(x, neu));
    })(ast, []);
    const nachName = {};
    for (const d of dekl) (nachName[d.name] = nachName[d.name] || []).push(d);
    const kaputt = [];
    for (const r of rufe) {
        const kandidaten = nachName[r.name];
        if (!kandidaten) continue;            // global/importiert - nicht unsere Frage
        const sichtbar = kandidaten.some(d =>
            r.kette.some(f => d.node.start >= f.start && d.node.end <= f.end));
        if (!sichtbar) kaputt.push({ name: r.name, zeile: r.node.loc.start.line });
    }
    return { kaputt, anzahlRufe: rufe.length };
}

console.log('\n\x1b[1mReichweite lokaler Helfer in allen Frontend-Modulen\x1b[0m');
const dir = path.join(REPO, 'frontend/js');
const dateien = fs.readdirSync(dir).filter(f => f.endsWith('.js')).sort();
check(`Positivkontrolle: Module gefunden (${dateien.length})`, dateien.length > 10);
let gesamtRufe = 0, betroffen = [];
for (const f of dateien) {
    const r = pruefeDatei(path.join(dir, f));
    if (r.fehler) { check(`${f}: ${r.fehler}`, false); continue; }
    gesamtRufe += r.anzahlRufe;
    if (r.kaputt.length) betroffen.push({ f, k: r.kaputt });
}
check(`Positivkontrolle: Aufrufe wirklich untersucht (${gesamtRufe})`, gesamtRufe > 500);
for (const b of betroffen)
    for (const k of b.k)
        console.log(`      \x1b[31m${b.f}:${k.zeile}  ${k.name}() ist hier nicht sichtbar\x1b[0m`);
check('⚠ kein Aufruf eines lokal deklarierten Helfers ausserhalb seiner Reichweite',
      betroffen.length === 0);

// Die beiden bezahlten Faelle namentlich - damit sie nicht zurueckkommen.
const KJS = fs.readFileSync(path.join(dir, 'knowledge.js'), 'utf8');
check('⚠ der gemeldete Fall (T in toggleLearnedList) ist weg',
      !/title="\$\{T\('common\.delete'/.test(KJS));
check('und die Stelle benutzt window.t (immer sichtbar)',
      /title="\$\{window\.t\('common\.delete'\)\}"/.test(KJS));

console.log(`\n\x1b[1mErgebnis: ${OK} OK, ${FAIL} FAIL\x1b[0m`);
process.exit(FAIL ? 1 : 0);
