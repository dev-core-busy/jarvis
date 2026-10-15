#!/usr/bin/env node
/* Waechter: zweite Extraktion im Wissens-Destillat haengt Bilder und Quellen
 * an und verschiebt ihre Marken (Review 2026-09-28 #12).
 *
 * ⚠ DER BEFUND: `extraktUebernehmen` ERSETZTE `bilder`/`quellen` je
 * Extraktion, haengte den Text aber AN. Der Server nummeriert `[BILD-n]` je
 * Anfrage ab 1 – ab der zweiten Datei zeigten die Marken auf falsche Bilder,
 * und die Uebernahme schickte nur die letzte Quelle.
 *
 * AUSGEFUEHRT: `extraktUebernehmen` und `mitBildern` werden aus dem echten
 * Modul geschnitten und hintereinander aufgerufen – gemessen wird, welches
 * Bild am Ende hinter welcher Marke steht, nicht ob ein Wort im Quelltext
 * vorkommt.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen_destillat.js'), 'utf8');

let ok = 0, fail = 0, bilanz = false;
process.on('exit', () => {
    if (!bilanz) { console.log('\nErgebnis: ABGEBROCHEN – keine Bilanz'); process.exitCode = 1; }
});
function check(text, bed, detail) {
    if (bed) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (detail ? '  [' + detail + ']' : '')); }
}

function schneide(name) {
    const i = JS.indexOf('function ' + name + '(');
    if (i < 0) return null;
    const auf = JS.indexOf('{', i);
    let tiefe = 0, inStr = null, inCom = null, inRe = false;
    for (let j = auf; j < JS.length; j++) {
        const c = JS[j], n = JS[j + 1];
        if (inCom === '/*') { if (c === '*' && n === '/') { inCom = null; j++; } continue; }
        if (inCom === '//') { if (c === '\n') inCom = null; continue; }
        if (inStr) { if (c === '\\') { j++; continue; } if (c === inStr) inStr = null; continue; }
        if (inRe) { if (c === '\\') { j++; continue; } if (c === '/') inRe = false; continue; }
        if (c === '/' && n === '*') { inCom = '/*'; j++; continue; }
        if (c === '/' && n === '/') { inCom = '//'; j++; continue; }
        // Regex-Literal nach ( , = : ersetzen – sonst zaehlt `\s*$/, '')` falsch.
        if (c === '/' && /[(,=:]\s*$/.test(JS.slice(Math.max(0, j - 3), j))) { inRe = true; continue; }
        if (c === '"' || c === "'" || c === '`') { inStr = c; continue; }
        if (c === '{') tiefe++;
        else if (c === '}') { tiefe--; if (tiefe === 0) return JS.slice(i, j + 1); }
    }
    return null;
}

const teile = ['extraktUebernehmen', 'mitBildern'].map(schneide);
if (teile.some((x) => !x)) {
    console.log('ABBRUCH: Funktion nicht schneidbar');
    bilanz = true; process.exit(2);
}
check('Positivkontrolle: Schnitt enthaelt das Textfeld',
      teile[0].indexOf("'wi-dest-text'") >= 0 && teile[0].indexOf('protokollSetzen') >= 0);

function modul() {
    const ta = { value: '' };
    const f = new Function('ta', `
        var bilder = [], quellen = [], dateien = [];
        function $(id) { return id === 'wi-dest-text' ? ta : null; }
        function t(k) { return k; }
        function status() {}
        function protokollSetzen() {}
        function dateilisteZeichnen() {}
        function zaehlerZeichnen() {}
        ${teile.join('\n')}
        return { rein: extraktUebernehmen, zeige: mitBildern,
                 stand: function () { return { bilder: bilder, quellen: quellen }; } };
    `);
    return { ta, m: f(ta) };
}

console.log('\n=== 1. Zwei Extraktionen hintereinander ===');
{
    const { ta, m } = modul();
    m.rein({ ok: ['a.docx'], text: '--- a.docx ---\nA1 [BILD-1] A2 [BILD-2]',
             bilder: ['data:a1', 'data:a2'] }, 0, []);
    check('Positivkontrolle: erste Extraktion steht im Feld', ta.value.indexOf('A1') >= 0);
    m.rein({ ok: ['b.docx'], text: '--- b.docx ---\nB1 [BILD-1]', bilder: ['data:b1'] }, 0, []);
    const st = m.stand();
    check('Bilder angehaengt (3 statt 1)', st.bilder.length === 3, JSON.stringify(st.bilder));
    check('Quellen angehaengt (a.docx UND b.docx)',
          st.quellen.indexOf('a.docx') >= 0 && st.quellen.indexOf('b.docx') >= 0,
          JSON.stringify(st.quellen));
    const html = m.zeige(ta.value);
    const reihe = (html.match(/data:[ab]\d/g) || []).join(',');
    check('⚠ jede Marke zeigt auf IHR Bild (a1,a2,b1)', reihe === 'data:a1,data:a2,data:b1', reihe);
    check('zweite Marke im Text verschoben auf [BILD-3]', ta.value.indexOf('B1 [BILD-3]') >= 0, ta.value);
}

console.log('\n=== 2. Leeres Feld = neuer Anfang ===');
{
    const { ta, m } = modul();
    m.rein({ ok: ['a.docx'], text: 'A [BILD-1]', bilder: ['data:a1'] }, 0, []);
    ta.value = '   ';
    m.rein({ ok: ['b.docx'], text: 'B [BILD-1]', bilder: ['data:b1'] }, 0, []);
    const st = m.stand();
    check('alte Bilder verworfen', st.bilder.length === 1 && st.bilder[0] === 'data:b1',
          JSON.stringify(st.bilder));
    check('nur die neue Quelle', st.quellen.join() === 'b.docx', JSON.stringify(st.quellen));
    check('Marke unverschoben', ta.value === 'B [BILD-1]', ta.value);
}

console.log('\n=== 3. Gleiche Datei zweimal: Quelle nur einmal ===');
{
    const { m } = modul();
    m.rein({ ok: ['a.docx'], text: 'A', bilder: [] }, 0, []);
    m.rein({ ok: ['a.docx'], text: 'A', bilder: [] }, 0, []);
    check('Quelle nicht doppelt', m.stand().quellen.join() === 'a.docx', m.stand().quellen.join());
}

console.log('\n=== 4. Extraktion ohne Text laesst den Bestand stehen ===');
{
    const { m } = modul();
    m.rein({ ok: ['a.docx'], text: 'A [BILD-1]', bilder: ['data:a1'] }, 0, []);
    m.rein({ ok: [], text: '', bilder: [], fehler: { 'x.pdf': 'kaputt' } }, 0, []);
    check('Bilder der ersten Extraktion bleiben', m.stand().bilder.length === 1,
          JSON.stringify(m.stand().bilder));
    check('Quelle der ersten Extraktion bleibt', m.stand().quellen.join() === 'a.docx');
}

bilanz = true;
console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
