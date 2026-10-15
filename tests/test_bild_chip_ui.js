#!/usr/bin/env node
/**
 * Waechter: ein ausgeliefertes BILD bekommt im Chat Vorschau UND Download-Chip.
 *
 * DER VORFALL (ECHT, 2026-10-12, /chat): ein Benutzer liess zweimal ein PDF
 * in ein 300-dpi-JPEG wandeln, "und mir zum download anbieten". Auf ECHT
 * gemessen: das JPEG lag in data/documents, Eigentuemer korrekt, das Backend
 * sendete `![Auftragsnummer_C128-1.jpg](/api/documents/…)` – und das war
 * ALLES. Ein Bild wurde nur eingebettet; die Chip-Regel in chatlib.js kannte
 * nur docx|xlsx|pptx|pdf. Gemeldet als "es wird keine jpg Datei geliefert".
 *
 * Seitdem sendet `_deliver_docs._emit` (backend/agent.py) zu einem Bild ZWEI
 * Zeilen: die Vorschau und den Chip mit derselben Adresse. Die FORM des
 * Markdowns prueft tests/test_doc_delivery.py am echten Erzeuger; hier wird
 * gemessen, was der Browser daraus macht – echte sitzung.js, dlkey.js und
 * chatlib.js, der echte `renderMarkdown`, geprueft am DOM.
 *
 * Aufruf: node tests/test_bild_chip_ui.js   (Exit 0 gruen, 1 FAIL, 2 Abbruch)
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

/** Genau die Form aus agent.py::_emit fuer ein Bild. */
function bildMd(name) {
    const url = '/api/documents/' + HEX + '__' + name;
    return { url, md: '![' + name + '](' + url + ')\n[📥 ' + name + ' herunterladen](' + url + ')' };
}

let OK = 0, FAIL = 0, BILANZ = false;
function check(b, t) {
    if (typeof b !== 'boolean') {
        console.log('ABBRUCH: check(Bedingung, Text) – Argumente vertauscht: ' + t);
        process.exit(2);
    }
    if (b) { OK++; console.log('  \x1b[32mOK\x1b[0m   ' + t); }
    else { FAIL++; console.log('  \x1b[31mFAIL\x1b[0m ' + t); }
}
function kopf(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function bilanz() {
    if (BILANZ) return;
    BILANZ = true;
    console.log('\n' + '='.repeat(62));
    console.log('\x1b[1mErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL\x1b[0m');
}
process.on('exit', (code) => {
    if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; }
});

/** Seite wie /chat (Aufbau aus test_dlkey_token_schluessel.js, dort begruendet). */
function seite() {
    const dom = new JSDOM('<!doctype html><html><body></body></html>',
        { url: 'https://beispiel.test/chat', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_chat_token', 'm.mustermann:1790000000:abcdef');
    win.localStorage.setItem('jarvis_chat_user', 'm.mustermann');
    win.fetch = () => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    win.eval(SITZUNG);
    win.eval(DLKEY);
    win.eval(CHATLIB);
    return { win, render: win.JarvisChatLib.renderMarkdown };
}

function dom(win, html) {
    const d = win.document.createElement('div');
    d.innerHTML = html;
    return d;
}

const { win, render } = seite();

kopf('1) Positivkontrolle: Messaufbau und bestehende Chip-Regel');
{
    check(typeof render === 'function', 'renderMarkdown ist geladen');
    const d = dom(win, render('[📥 Bericht.pdf herunterladen](/api/documents/' + HEX + '__Bericht.pdf)'));
    check(d.querySelectorAll('a.chat-doc-dl').length === 1, 'ein PDF wird wie bisher ein Chip');
    const d2 = dom(win, render('![Bild.png](/api/documents/' + HEX + '__Bild.png)'));
    check(d2.querySelectorAll('img.chat-img').length === 1, 'ein Bild-Verweis wird wie bisher ein <img>');
    if (FAIL) { bilanz(); process.exit(2); }   // Messaufbau kaputt = keine Aussage
}

kopf('2) Der gemeldete Fall: JPEG mit Seitennummer');
{
    const { url, md } = bildMd('Auftragsnummer_C128-1.jpg');
    const d = dom(win, render(md));
    const imgs = d.querySelectorAll('img.chat-img');
    const chips = d.querySelectorAll('a.chat-doc-dl');
    check(imgs.length === 1, 'genau EINE Vorschau (gemessen: ' + imgs.length + ')');
    check(chips.length === 1, 'genau EIN Download-Chip (gemessen: ' + chips.length + ')');
    const a = chips[0];
    check(!!a && a.hasAttribute('download'), 'der Chip LAEDT herunter (download-Attribut), statt einen Tab zu oeffnen');
    check(!!a && (a.getAttribute('href') || '').indexOf(url) === 0, 'der Chip zeigt auf die Datei der Vorschau');
    check(!!a && /[?&]token=/.test(a.getAttribute('href') || ''), 'der Chip traegt ein ?token= (sonst 401)');
    check(!!a && /Auftragsnummer_C128-1\.jpg/.test(a.textContent), 'der Chip nennt den Dateinamen');
    // `!!a &&` zuerst: ohne Chip WUERFE `a.contains`, und die Gegenprobe
    // endete ohne Bilanz statt mit einem FAIL (so geschehen beim Bau).
    check(!!imgs[0] && !!a && !a.contains(imgs[0]), 'die Vorschau steckt nicht im Chip');
    check(!/herunterladen\]\(/.test(d.innerHTML) && d.textContent.indexOf('](') < 0,
          'kein roher Markdown-Rest in der Anzeige');
}

kopf('3) Jede Bildendung, die das Backend inline zeigt');
for (const e of ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']) {
    const { md } = bildMd('bild.' + e);
    const d = dom(win, render(md));
    check(d.querySelectorAll('a.chat-doc-dl').length === 1, '.' + e + ': Download-Chip vorhanden');
}

kopf('4) Gespeicherte Altverlaeufe (nur Vorschau) bleiben unveraendert');
{
    const d = dom(win, render('![alt.jpg](/api/documents/' + HEX + '__alt.jpg)'));
    check(d.querySelectorAll('img.chat-img').length === 1 && d.querySelectorAll('a.chat-doc-dl').length === 0,
          'ein Verlauf von vorher zeigt weiter genau das Bild und keinen erfundenen Chip');
}

bilanz();
win.close();
process.exit(FAIL ? 1 : 0);
