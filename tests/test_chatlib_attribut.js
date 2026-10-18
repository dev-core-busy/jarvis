#!/usr/bin/env node
/* Waechter: Modelltext kann im Markdown-Renderer keine Attribute einschleusen
 * (Code-Review 2026-10-18).
 *
 * chatlib._E escaped nur & < > – ein Anfuehrungszeichen in der Adresse eines
 * Bildes oder Links beendete das Attribut: aus ![x](https://a" onerror="…)
 * wurde ein <img> mit onerror. Gemessen am ECHTEN renderMarkdown (echte
 * sitzung.js, dlkey.js, chatlib.js) am DOM, nicht am Quelltext.
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
require('./lib/bilanz')();   // Absturz -> Exit 2 statt 1

const W = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
let OK = 0, FAIL = 0, BILANZ = false;
function check(b, t, d) {
    if (b) { OK++; console.log('  ✓ ' + t); } else { FAIL++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
}
function bilanz() { BILANZ = true; console.log('\nErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL'); }
process.on('exit', (code) => { if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; } });

const dom = new JSDOM('<!doctype html><html><body></body></html>',
    { url: 'https://beispiel.test/chat', runScripts: 'outside-only' });
const win = dom.window;
win.localStorage.setItem('jarvis_chat_token', 'm.mustermann:1790000000:abcdef');
win.localStorage.setItem('jarvis_chat_user', 'm.mustermann');
win.fetch = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
for (const f of ['sitzung.js', 'dlkey.js', 'chatlib.js']) {
    win.eval(fs.readFileSync(path.join(W, 'frontend/js', f), 'utf8'));
}
const render = win.JarvisChatLib && win.JarvisChatLib.renderMarkdown;

function html(md) {
    const d = win.document.createElement('div');
    d.innerHTML = render(md);
    return d;
}
const ERLAUBT = {
    IMG: new Set(['src', 'alt', 'class', 'loading', 'style']),
    A: new Set(['href', 'target', 'rel', 'download', 'class', 'title']),
};
function fremdeAttribute(d) {
    const raus = [];
    for (const el of d.querySelectorAll('img, a')) {
        for (const at of el.getAttributeNames()) {
            if (!ERLAUBT[el.tagName].has(at)) raus.push(el.tagName + '[' + at + ']');
        }
        const st = el.getAttribute('style') || '';
        if (el.tagName === 'IMG' && st && !/^max-width:100%;border-radius:10px;margin:6px 0;display:block;$/.test(st)) {
            raus.push('IMG[style=' + st + ']');
        }
        if (el.tagName === 'A' && el.hasAttribute('style')) raus.push('A[style]');
    }
    return raus;
}

console.log('\n1) Positivkontrolle');
check(typeof render === 'function', 'renderMarkdown geladen');
const k = html('![Hund](https://beispiel.test/hund.png) und [Seite](https://beispiel.test/a?b=1&c=2)');
const kimg = k.querySelector('img'), ka = k.querySelector('a');
check(kimg && kimg.getAttribute('src') === 'https://beispiel.test/hund.png' && kimg.getAttribute('alt') === 'Hund',
      'normales Bild unveraendert');
check(ka && ka.getAttribute('href') === 'https://beispiel.test/a?b=1&c=2', 'normaler Link unveraendert (auch &)',
      ka && ka.getAttribute('href'));
check(fremdeAttribute(k).length === 0, 'Messmethode meldet bei Normalfall nichts', fremdeAttribute(k).join(','));
if (FAIL) { bilanz(); win.close(); process.exit(2); }

console.log('\n2) Angriffe');
const FAELLE = [
    ['Bild-Adresse mit "', '![x](https://a.test/x.png" onerror="alert(1))'],
    ['Bild-Adresse mit " und style', '![x](https://a.test/x.png" style="position:fixed;inset:0)'],
    ['Bild-Alt mit "', '![a" onerror="alert(1)](https://a.test/x.png)'],
    ['Link-Adresse mit "', '[klick](https://a.test/" style="position:fixed;inset:0;z-index:9)'],
    ['Link mit einfachem Anfuehrungszeichen', "[klick](https://a.test/' onmouseover='alert(1))"],
    ['Dokument-Link', '[Datei.pdf](/api/documents/abc__x.pdf)'],
];
for (const [name, md] of FAELLE) {
    const d = html(md);
    const fremd = fremdeAttribute(d);
    check(fremd.length === 0, name + ': keine fremden Attribute', fremd.join(', '));
}
const d = html('![x](https://a.test/x.png" onerror="alert(1))');
const img = d.querySelector('img');
check(img && /"/.test(img.getAttribute('src')) && !img.hasAttribute('onerror'),
      'das Anfuehrungszeichen bleibt TEIL der Adresse statt sie zu beenden', img && img.getAttribute('src'));

bilanz();
win.close();
process.exit(FAIL ? 1 : 0);
