#!/usr/bin/env node
/**
 * REGEL: ein JS-Waechter darf nicht STUMM abbrechen.
 *
 * Bezahlt am 2026-10-05: `test_knowledge_sync_ui.js` und
 * `test_topbar_symbole_ui.js` starben an einem TypeError (`JarvisSitzung`
 * fehlte im geschnittenen Prolog, Folge von 8d082990) und endeten mit
 * **Exit 1 ohne Bilanzzeile**. Exit 1 ist hier die Sprache, in der ein
 * Waechter "ich beisse" sagt – ein Abbruch war davon nicht zu unterscheiden,
 * und beide Dateien lagen unbemerkt brach. Repoweit gemessen: **9 von 102**
 * Waechter brachen so ab, 7 aus derselben Ursache.
 *
 * Eine LISTE dieser neun waere morgen unvollstaendig – deshalb eine Regel.
 * Gemessen werden zwei EIGENSCHAFTEN am Syntaxbaum (acorn), nicht am Text:
 * ein Teilstring ist keine Identitaet, und ein Waechter, der ein VORKOMMEN
 * prueft, misst keine Wirkung.
 *
 *   Teil 1  Positivkontrolle: der Parser sieht die Dateien ueberhaupt.
 *   Teil 2  KEIN BLINDES NETZ. Wer ein `process.on('exit')`-Netz hat, muss
 *           den Code nur bei einem STILLEN Ende anheben (`code === 0`). Ein
 *           blindes `process.exitCode = 1` laeuft NACH `process.exit(2)` und
 *           macht aus "konnte nicht laufen" ein "Waechter beisst".
 *   Teil 3  ABSTURZ IST UNTERSCHEIDBAR. Die Datei hat einen Weg, der einen
 *           Absturz auf Exit 2 legt – entweder ueber `lib/bilanz` oder
 *           eigenhaendig (uncaughtException / unhandledRejection / catch).
 *
 * Teil 3 ist der Kern und heute fuer die Mehrheit der Dateien noch offen;
 * die Bilanz nennt die Zahl, damit die Luecke nicht als erledigt gilt.
 *
 *   node tests/test_waechter_bilanz.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const fertig = require('./lib/bilanz')({ stumm: true });   // eigenes Netz

let OK = 0, FAIL = 0;
const pruefe = (b, t, d) => {
    if (b) { OK++; console.log('  \x1b[32m✓\x1b[0m ' + t); }
    else { FAIL++; console.log('  \x1b[31m✗\x1b[0m ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

// Ohne Parser gibt es keine Aussage: Exit 2, nicht 0 – und die gesuchten
// Orte werden GENANNT (eine falsche Begruendung sieht wie ein geklaerter
// Fall aus und wird nicht nachgeprueft).
const ORTE = ['acorn', '/usr/share/nodejs/acorn',
              path.join(REPO, 'node_modules/acorn'),
              path.join(REPO, 'data/node_modules/acorn')];
let acorn = null;
for (const p of ORTE) { try { acorn = require(p); break; } catch (e) { /* weiter */ } }
if (!acorn) {
    console.log('ABBRUCH (Exit 2): acorn nicht gefunden – gesucht in:\n  ' + ORTE.join('\n  '));
    fertig();
    process.exit(2);
}

/* ── Baum-Werkzeug ──────────────────────────────────────────────────────── */

// Besucht jeden Knoten mit seiner Elternkette.
function alle(n, fn, eltern) {
    eltern = eltern || [];
    fn(n, eltern);
    const kette = eltern.concat([n]);
    for (const k in n) {
        if (k === 'loc' || k === 'start' || k === 'end') continue;
        const v = n[k];
        if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && alle(x, fn, kette));
        else if (v && typeof v.type === 'string') alle(v, fn, kette);
    }
}
const IST_FN = (t) => /^(FunctionExpression|ArrowFunctionExpression|FunctionDeclaration)$/.test(t);

/** `process.on('<ereignis>', fn)` -> die Handler-Funktion, sonst null. */
function prozessOn(n, ereignis) {
    if (!n || n.type !== 'CallExpression') return null;
    const c = n.callee;
    if (!c || c.type !== 'MemberExpression') return null;
    if (!(c.object.type === 'Identifier' && c.object.name === 'process')) return null;
    if (!(c.property.type === 'Identifier' && c.property.name === 'on')) return null;
    const a0 = n.arguments[0];
    if (!a0 || a0.type !== 'Literal' || a0.value !== ereignis) return null;
    const a1 = n.arguments[1];
    return a1 && IST_FN(a1.type) ? a1 : null;
}

/** Hebt dieser Knoten den Exitcode an? (`process.exitCode = …` / `process.exit(…)`) */
function istHebung(n) {
    if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression'
        && n.left.object.type === 'Identifier' && n.left.object.name === 'process'
        && n.left.property && n.left.property.name === 'exitCode') return true;
    if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
        && n.callee.object.type === 'Identifier' && n.callee.object.name === 'process'
        && n.callee.property && n.callee.property.name === 'exit') return true;
    return false;
}

/** `process.exit(<wert>)` mit festem Wert. */
function exitMit(n, wert) {
    return n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
        && n.callee.object.type === 'Identifier' && n.callee.object.name === 'process'
        && n.callee.property && n.callee.property.name === 'exit'
        && n.arguments[0] && n.arguments[0].type === 'Literal'
        && n.arguments[0].value === wert;
}

/** Der Name der Bilanz-Marke aus `if (!bilanz …)` im Netz, sonst null. */
function markeAus(handler) {
    let name = null;
    alle(handler.body, (n) => {
        if (!name && n.type === 'UnaryExpression' && n.operator === '!'
            && n.argument.type === 'Identifier') name = n.argument.name;
    });
    return name;
}

/** Setzt eine Anweisung die Marke auf true? (`marke = true`) */
function setztMarke(knoten, marke) {
    let ja = false;
    alle(knoten, (n) => {
        if (n.type === 'AssignmentExpression' && n.operator === '='
            && n.left.type === 'Identifier' && n.left.name === marke
            && n.right.type === 'Literal' && n.right.value === true) ja = true;
    });
    return ja;
}

/** Vergleicht dieser Ausdruck `name` gegen die 0? (beide Richtungen) */
function gegenNull(n, name) {
    if (!name || n.type !== 'BinaryExpression' || !/^===?$/.test(n.operator)) return false;
    const [a, b] = [n.left, n.right];
    return (a.type === 'Identifier' && a.name === name && b.type === 'Literal' && b.value === 0)
        || (b.type === 'Identifier' && b.name === name && a.type === 'Literal' && a.value === 0);
}

/** Laedt und parst eine Waechterdatei. */
function baum(datei) {
    // Shebang unschaedlich machen, ohne Zeilen zu verschieben – acorn kennt
    // ihn nicht, und 55 von 102 Dateien tragen einen. Wer ihn WEGSCHNEIDET,
    // verschiebt jede Zeilennummer im Befund.
    const src = fs.readFileSync(datei, 'utf8').replace(/^#!/, '//');
    return acorn.parse(src, {
        ecmaVersion: 2022, sourceType: 'script',
        allowReturnOutsideFunction: true,   // mehrere Waechter nutzen das
        allowAwaitOutsideFunction: true,
    });
}

/* ── Erhebung ───────────────────────────────────────────────────────────── */

const DATEIEN = fs.readdirSync(path.join(REPO, 'tests'))
    .filter(f => /^test_.*\.js$/.test(f)).sort();

const befund = [];   // { datei, netze, blind[], absturz2, helfer }
for (const f of DATEIEN) {
    const voll = path.join(REPO, 'tests', f);
    let ast;
    try { ast = baum(voll); }
    catch (e) { befund.push({ datei: f, parsefehler: e.message }); continue; }

    const netze = [];
    let absturz2 = false, helfer = false;
    let netzPos = null, marke = null;
    const exit2 = [];       // alle process.exit(2)-Stellen mit Elternkette

    alle(ast, (n, eltern) => {
        // (a) `exit`-Netze einsammeln und auf Blindheit pruefen
        const h = prozessOn(n, 'exit');
        if (h) {
            if (netzPos === null) { netzPos = n.start; marke = markeAus(h); }
            const p = h.params[0] && h.params[0].name;
            let vergleich = false, hebungen = 0, bewacht = 0;
            alle(h.body, (m, el) => {
                if (gegenNull(m, p)) vergleich = true;
                if (istHebung(m)) {
                    hebungen++;
                    // Die Hebung muss unter einer Bedingung stehen.
                    if (el.some(x => x.type === 'IfStatement'
                                  || x.type === 'ConditionalExpression'
                                  || x.type === 'LogicalExpression')) bewacht++;
                }
            });
            netze.push({ blind: !(vergleich && hebungen > 0 && hebungen === bewacht) });
        }

        // (b) Absturzweg nach Exit 2: in catch / .catch() / den Prozess-Haken
        if (exitMit(n, 2)) {
            exit2.push({ pos: n.start, eltern: eltern.slice() });
            const drin = eltern.some(x =>
                x.type === 'CatchClause'
                || (x.type === 'CallExpression' && x.callee
                    && x.callee.type === 'MemberExpression' && x.callee.property
                    && x.callee.property.name === 'catch')
                || prozessOn(x, 'uncaughtException')
                || prozessOn(x, 'unhandledRejection'));
            if (drin) absturz2 = true;
        }

        // (c) benutzt die Datei die EINE Quelle? (require('./lib/bilanz'))
        if (n.type === 'CallExpression' && n.callee.type === 'Identifier'
            && n.callee.name === 'require' && n.arguments[0]
            && n.arguments[0].type === 'Literal'
            && /(^|\/)lib\/bilanz$/.test(String(n.arguments[0].value))) helfer = true;
    });

    /* Ein BLINDES Netz ist fuer sich noch kein Schaden – es braucht einen
     * Exit-2-Weg, den es zerstoeren KANN. Geschuetzt ist ein `process.exit(2)`
     * auf zwei Wegen, und beide zaehlen:
     *   - er liegt VOR der Anmeldung des Netzes (das Netz gibt es da noch
     *     nicht; so retten sich die jsdom-Abbrueche am Dateianfang),
     *   - oder die Marke wird im selben Block vorher auf true gesetzt
     *     (`bilanz = true; process.exit(2);`).
     * Am 2026-10-05 gemessen: alle 12 blinden Netze waren auf einem dieser
     * zwei Wege gedeckt – 12 blinde Netze sind also NICHT 12 Fehler. Gemeldet
     * wird deshalb nur der UNGEDECKTE Fall; das ist der, den das Register
     * schon einmal bezahlt hat. */
    const blindesNetz = netze.some(n => n.blind);
    const ungedeckt = !blindesNetz ? [] : exit2.filter(e => {
        if (netzPos !== null && e.pos < netzPos) return false;      // vor dem Netz
        if (!marke) return true;                                     // keine Marke = ungedeckt
        /* NUR der INNERSTE Block zaehlt als Deckung, nicht `Program`.
         * Zuerst hatte ich jeden umgebenden Block samt Program durchsucht –
         * damit galt ein `bilanz = true`, das IRGENDWO weiter oben in der
         * Datei steht, als Deckung fuer ein exit(2) am Dateiende. Die eigene
         * Gegenprobe hat das als STUMPF gemeldet (die Sabotage wurde nicht
         * erkannt). Gedeckt ist nur das Muster, das die echten Faelle zeigen:
         * `… bilanz = true; process.exit(2);` als Geschwister im selben
         * innersten Block. */
        const bloecke = e.eltern.filter(x => x.type === 'BlockStatement');
        const innerster = bloecke[bloecke.length - 1];
        if (!innerster) return true;                // z. B. direkt unter Program
        for (const st of innerster.body) {
            if (st.start > e.pos) break;            // nur was davor steht
            if (setztMarke(st, marke)) return false;
        }
        return true;
    });

    befund.push({ datei: f, netze, absturz2, helfer, blindesNetz,
                  ungedeckt: ungedeckt.length, exit2: exit2.length });
}

/* ── Teil 1: Positivkontrolle ───────────────────────────────────────────── */
abschnitt('1. Positivkontrolle – der Parser sieht die Dateien');

const kaputt = befund.filter(b => b.parsefehler);
pruefe(DATEIEN.length >= 90, 'genug Waechter gefunden', `${DATEIEN.length} Dateien`);
pruefe(kaputt.length === 0, 'jede Datei ist geparst',
       kaputt.map(b => `${b.datei}: ${b.parsefehler}`).join('; '));
// Ohne diese Kontrolle waeren Teil 2 und 3 trivial wahr: eine nicht geparste
// Datei hat weder ein blindes Netz noch einen fehlenden Absturzweg.
if (kaputt.length) {
    console.log('ABBRUCH (Exit 2): ungeparste Dateien machen die Regel blind.');
    fertig();
    process.exit(2);
}
// Und der Baum muss die gesuchten Formen ueberhaupt finden koennen.
const mitNetz = befund.filter(b => b.netze && b.netze.length);
pruefe(mitNetz.length > 0, 'die Suche findet exit-Netze (sonst misst Teil 2 nichts)',
       `${mitNetz.length} Dateien mit Netz`);
const mitA2 = befund.filter(b => b.absturz2);
pruefe(mitA2.length > 0, 'die Suche findet Absturzwege (sonst misst Teil 3 nichts)',
       `${mitA2.length} Dateien`);

/* ── Teil 2: kein blindes Netz ──────────────────────────────────────────── */
abschnitt('2. Kein BLINDES Netz (es wuerde das Exit-2-Signal zerstoeren)');

const blind = befund.filter(b => b.blindesNetz);
const echt = befund.filter(b => b.ungedeckt > 0);
for (const b of echt) {
    pruefe(false, `${b.datei}: blindes Netz UND ${b.ungedeckt} ungedeckter Exit-2-Weg `
                + `– der Abbruch kommt als Exit 1 heraus`);
}
if (!echt.length) {
    pruefe(true, `kein ungedeckter Exit-2-Weg unter einem blinden Netz `
               + `(${blind.length} blinde Netze, alle durch Reihenfolge oder Marke gedeckt)`);
}

/* ── Teil 3: Absturz ist von einem Befund unterscheidbar ────────────────── */
abschnitt('3. Ein Absturz endet mit Exit 2, nicht mit Exit 1');

const ohne = befund.filter(b => !b.absturz2 && !b.helfer);
for (const b of ohne) {
    pruefe(false, `${b.datei}: kein Absturzweg nach Exit 2 (require('./lib/bilanz')() genuegt)`);
}
if (!ohne.length) pruefe(true, 'jeder Waechter trennt Abbruch von Befund');

/* ── Bilanz ─────────────────────────────────────────────────────────────── */
console.log('\n' + '='.repeat(70));
console.log(`Waechter: ${DATEIEN.length}   mit Netz: ${mitNetz.length}   `
          + `blind: ${blind.length}   ohne Absturzweg: ${ohne.length}`);
console.log(`\x1b[1m${OK} OK, ${FAIL} FAIL\x1b[0m`);
fertig();
process.exit(FAIL ? 1 : 0);
