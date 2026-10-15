#!/usr/bin/env node
/* Waechter: im Browser traegt jedes erzeugte Bild einen Abruf-Schluessel.
 *
 * Seit 2026-10-15 verlangt /api/generated/<32 Hex> eine Anmeldung. Ein <img>
 * kann keinen Authorization-Kopfsatz setzen – deshalb haengt
 * chatlib._withToken den Abruf-Schluessel als ?token=JDL1.… an (dlkey.js zieht
 * ihn in bereits gerenderten Bildern nach). Ohne das waere JEDES erzeugte Bild
 * im Chat ein 401.
 *
 * Gemessen am echten renderMarkdown mit echter sitzung.js, dlkey.js und
 * chatlib.js – am DOM, nicht am Quelltext.
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const W = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const SITZUNG = fs.readFileSync(W + '/frontend/js/sitzung.js', 'utf8');
const DLKEY = fs.readFileSync(W + '/frontend/js/dlkey.js', 'utf8');
const CHATLIB = fs.readFileSync(W + '/frontend/js/chatlib.js', 'utf8');
const HEX = '0123456789abcdef0123456789abcdef';

let OK = 0, FAIL = 0, BILANZ = false;
function check(b, t) {
    if (b) { OK++; console.log('  ✓ ' + t); } else { FAIL++; console.log('  ✗ ' + t); }
}
function bilanz() {
    BILANZ = true;
    console.log('\nErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL');
}
process.on('exit', (code) => {
    if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; }
});

const dom = new JSDOM('<!doctype html><html><body></body></html>',
    { url: 'https://beispiel.test/chat', runScripts: 'outside-only' });
const win = dom.window;
win.localStorage.setItem('jarvis_chat_token', 'm.mustermann:1790000000:abcdef');
win.localStorage.setItem('jarvis_chat_user', 'm.mustermann');
win.fetch = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
win.eval(SITZUNG);
win.eval(DLKEY);
win.eval(CHATLIB);
const render = win.JarvisChatLib && win.JarvisChatLib.renderMarkdown;

function html(md) {
    const d = win.document.createElement('div');
    d.innerHTML = render(md);
    return d;
}

console.log('\n1) Positivkontrolle');
check(typeof render === 'function', 'renderMarkdown ist geladen');
const kontrolle = html('![Bild.png](/api/documents/' + HEX + '__Bild.png)');
const kSrc = (kontrolle.querySelector('img') || { getAttribute: () => '' }).getAttribute('src') || '';
check(/[?&]token=JDL1\./.test(kSrc), 'ein Dokument-Bild traegt den Abruf-Schluessel (Messaufbau tut)');
if (FAIL) { bilanz(); win.close(); process.exit(2); }

console.log('\n2) Erzeugtes Bild');
const d = html('Hier ist es:\n\n![Ein Hund](/api/generated/' + HEX + '.png)');
const img = d.querySelector('img');
const src = img ? (img.getAttribute('src') || '') : '';
check(!!img, 'das erzeugte Bild wird ein <img>');
check(src.indexOf('/api/generated/' + HEX + '.png') === 0, 'auf die richtige Adresse');
check(/[?&]token=JDL1\./.test(src), 'mit Abruf-Schluessel in ?token= (sonst 401)');
check(!/token=m\.mustermann/.test(d.innerHTML), 'NIE das Sitzungstoken in der Adresse');
const chips = d.querySelectorAll('a.chat-doc-dl');
check(chips.length === 0 || [...chips].every(a => /[?&]token=JDL1\./.test(a.getAttribute('href') || '')),
      'ein Download-Chip zum Bild traegt ebenfalls den Schluessel');

console.log('\n3) Fremde Adressen bleiben unberuehrt');
const ext = html('![x](https://beispiel.test/bild.png)');
const eSrc = (ext.querySelector('img') || { getAttribute: () => '' }).getAttribute('src') || '';
check(eSrc.indexOf('token=') < 0, 'keine Anmeldung an eine fremde Adresse');

bilanz();
win.close();
process.exit(FAIL ? 1 : 0);
