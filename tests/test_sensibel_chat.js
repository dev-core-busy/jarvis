#!/usr/bin/env node
/* Waechter: sensibler Chat in chat.js (Schalter "sensible Daten", 2026-11-24).
 *
 * Zusage: ein sensibler Chat lebt NUR im offenen Tab – nie localStorage, nie
 * Server-Sitzung/Transkript, und jeder Auftrag traegt `sensibel: true`.
 *
 * Gemessen am SYNTAXBAUM (acorn), nicht am Text: die Funktionen liegen in
 * einer Closure von chat.js und lassen sich ohne die ganze Seite nicht
 * ausfuehren. Geprueft wird je Speicherweg, dass VOR dem ersten Schreibzugriff
 * (localStorage / fetch / JarvisChatLib.saveHistory) ein `if (_istSensibel(..))`
 * steht, dessen Zweig mit `return` endet.
 *
 * Exit 0 = bestanden, 1 = Befund, 2 = konnte nicht laufen. Aufgerufen von
 * tests/test_sensibel.py, laeuft aber auch allein:  node tests/test_sensibel_chat.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const acorn = require('./lib/acorn_laden')();
const walk = (n, f) => {
    if (!n || typeof n.type !== 'string') return;
    f(n);
    for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && walk(x, f));
        else if (v && typeof v.type === 'string') walk(v, f);
    }
};

let ok = 0, fail = 0;
const check = (c, l, d) => { if (c) { ok++; console.log('  OK   ' + l); } else { fail++; console.log('  FAIL ' + l + (d ? ' – ' + d : '')); } };

const QUELLE = path.join(__dirname, '..', 'frontend', 'js', 'chat.js');
let src;
try { src = fs.readFileSync(QUELLE, 'utf8'); } catch (e) { console.log('ABBRUCH: chat.js nicht lesbar'); process.exit(2); }
let baum;
try { baum = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script' }); }
catch (e) { console.log('ABBRUCH: chat.js nicht parsebar: ' + e.message); process.exit(2); }

const funks = {};
walk(baum, n => { if (n.type === 'FunctionDeclaration' && n.id) funks[n.id.name] = n; });
// Positivkontrolle: die Funktionen, um die es geht, gibt es
const NOETIG = ['_saveHistory', '_persistSession', '_appendToSessionTranscript', '_auswahlMitgeben',
                '_restoreHistory', '_sidMerken', '_istSensibel', '_mitSensiblen', '_newSensibelSession'];
const fehlt = NOETIG.filter(n => !funks[n]);
if (fehlt.length) { console.log('ABBRUCH: Funktionen fehlen in chat.js: ' + fehlt.join(', ')); process.exit(2); }

const txt = n => src.slice(n.start, n.end);
const istSensTest = t => { let j = false; walk(t, n => { if (n.type === 'CallExpression' && n.callee.type === 'Identifier' && n.callee.name === '_istSensibel') j = true; }); return j; };
const endetMitReturn = b => b && (b.type === 'ReturnStatement'
    || (b.type === 'BlockStatement' && b.body.length && b.body[b.body.length - 1].type === 'ReturnStatement'));
const schreibt = n => {
    let j = false;
    walk(n, k => {
        if (k.type === 'CallExpression') {
            const c = txt(k.callee);
            if (/^(localStorage\.setItem|fetch|window\.JarvisChatLib\.saveHistory)$/.test(c) || c === '_csGet') j = true;
        }
    });
    return j;
};

// 1) Waechter-Zweig VOR dem ersten Schreibzugriff
for (const name of ['_saveHistory', '_persistSession', '_appendToSessionTranscript']) {
    const body = funks[name].body.body;
    let waechter = -1, erster = -1;
    body.forEach((st, i) => {
        if (waechter < 0 && st.type === 'IfStatement' && istSensTest(st.test) && endetMitReturn(st.consequent)) waechter = i;
        if (erster < 0 && schreibt(st)) erster = i;
    });
    check(waechter >= 0 && (erster < 0 || waechter < erster) && (erster >= 0),
        name + ': sensibler Chat kehrt VOR dem Speichern zurueck', 'Waechter@' + waechter + ' Schreiben@' + erster);
}

// 2) localStorage mit der Sitzungskennung nur in _sidMerken (und dort hinter dem Waechter)
const sidSchreiber = [];
walk(baum, n => {
    if (n.type === 'CallExpression' && txt(n.callee) === 'localStorage.setItem'
        && n.arguments[0] && txt(n.arguments[0]) === '_sidKey()') sidSchreiber.push(n);
});
const inMerken = sidSchreiber.filter(n => n.start >= funks._sidMerken.start && n.end <= funks._sidMerken.end);
check(sidSchreiber.length === 1 && inMerken.length === 1,
    'Sitzungskennung wird nur in _sidMerken nach localStorage geschrieben', sidSchreiber.length + ' Stellen');
const smBody = funks._sidMerken.body.body;
check(smBody.length && smBody[0].type === 'IfStatement' && istSensTest(smBody[0].test) && endetMitReturn(smBody[0].consequent),
    '_sidMerken: sensible Kennung wird nie gemerkt');

// 3) Auftrag traegt sensibel: true
let setztFlag = false;
walk(funks._auswahlMitgeben, n => {
    if (n.type === 'IfStatement' && istSensTest(n.test)) {
        walk(n.consequent, k => {
            if (k.type === 'AssignmentExpression' && txt(k.left) === 'msg.sensibel' && txt(k.right) === 'true') setztFlag = true;
        });
    }
});
check(setztFlag, '_auswahlMitgeben setzt msg.sensibel = true im sensiblen Chat');

// 4) _restoreHistory fragt den Server nur fuer NICHT sensible Chats
let csGetGeschuetzt = false, csGetAufrufe = 0;
walk(funks._restoreHistory, n => {
    if (n.type === 'CallExpression' && txt(n.callee) === '_csGet') csGetAufrufe++;
    if (n.type === 'IfStatement' && istSensTest(n.test) && n.alternate) {
        walk(n.alternate, k => { if (k.type === 'CallExpression' && txt(k.callee) === '_csGet') csGetGeschuetzt = true; });
    }
});
check(csGetAufrufe === 1 && csGetGeschuetzt, '_restoreHistory: Serverabruf nur im else-Zweig des sensiblen Tests');

// 5) Jede Zuweisung einer Server-Liste an _sessions laeuft ueber _mitSensiblen
const zuw = [];
walk(baum, n => {
    if (n.type === 'AssignmentExpression' && txt(n.left) === '_sessions') {
        const r = txt(n.right);
        const vomServer = /_csList\(|\blist\b/.test(r);
        if (vomServer) zuw.push({ r, gut: n.right.type === 'CallExpression' && txt(n.right.callee) === '_mitSensiblen' });
    }
});
check(zuw.length >= 3 && zuw.every(z => z.gut), 'Server-Listen gehen durch _mitSensiblen (' + zuw.length + ')',
    zuw.filter(z => !z.gut).map(z => z.r).join(' | '));

// 6) Sensible Kennung entsteht nur im Browser (kein _csCreate im Anlegen)
let legtAn = false;
walk(funks._newSensibelSession, n => { if (n.type === 'CallExpression' && /^(_csCreate|fetch)$/.test(txt(n.callee))) legtAn = true; });
check(!legtAn, '_newSensibelSession legt nichts auf dem Server an');

// 7) Markup: Knopf und Hinweisband existieren, Band ist vorbelegt verborgen
let html = '';
try { html = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'chat.html'), 'utf8'); } catch (e) { /* unten */ }
check(/<button[^>]*id="cs-new-sens"/.test(html), 'chat.html: Knopf cs-new-sens vorhanden');
check(/<div[^>]*id="sens-banner"[^>]*\bhidden\b/.test(html), 'chat.html: Hinweisband vorbelegt verborgen');

console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
