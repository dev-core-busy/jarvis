/* Waechter: i18n.js gibt die gewaehlte Sprache als Cookie `jarvis_lang` an
 * den Server weiter (backend/sprache.py uebersetzt damit seine Antworten).
 *
 * Gemeldet 2026-11-24: bei FR kamen Fehler des Servers deutsch. Gemessen an
 * der ECHTEN i18n.js (+ i18n_fr.js) in jsdom:
 *   1. beim Laden: Cookie = gespeicherte Sprache (localStorage), sonst de;
 *   2. setLang('fr'|'en'|'de') setzt das Cookie mit um;
 *   3. das Cookie gilt fuer die ganze Seite (path=/), damit jede API-Anfrage
 *      es mitschickt.
 *
 * Lauf: timeout 60 node tests/test_sprach_cookie.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
require('./lib/bilanz')();

const ROOT = path.resolve(__dirname, '..');
const lies = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');
let ok = 0, fail = 0;
function pruefe(bed, text, detail) {
    if (bed) { ok++; console.log('  ✓ ' + text); }
    else { fail++; console.log('  ✗ ' + text + (detail ? ' – ' + detail : '')); }
}
function bilanz(code) {
    console.log('\n  ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(code === undefined ? (fail ? 1 : 0) : code);
}

const SRC = lies('frontend/js/i18n.js') + '\n' + lies('frontend/js/i18n_fr.js');

function seite(gespeichert, url) {
    const dom = new JSDOM('<!doctype html><html><body></body></html>',
                          // tiefer Pfad: ohne path=/ gaelte das Cookie nur unter /static/addin/
                          { url: url || 'https://beispiel.de/static/addin/taskpane.html', runScripts: 'outside-only' });
    if (gespeichert) dom.window.localStorage.setItem('jarvis_lang', gespeichert);
    dom.window.eval(SRC);
    return dom;
}
function cookie(dom) {
    const m = /(?:^|;\s*)jarvis_lang=([^;]*)/.exec(dom.window.document.cookie);
    return m ? m[1] : null;
}

let d = seite(null);
pruefe(typeof d.window.setLang === 'function', 'Positivkontrolle: i18n.js geladen (setLang vorhanden)');
if (typeof d.window.setLang !== 'function') bilanz(2);
pruefe(cookie(d) === 'de', 'ohne gespeicherte Sprache: Cookie de', String(cookie(d)));
d.window.setLang('fr');
pruefe(cookie(d) === 'fr', 'setLang(fr) setzt das Cookie auf fr', String(cookie(d)));
d.window.setLang('en');
pruefe(cookie(d) === 'en', 'setLang(en) setzt das Cookie auf en', String(cookie(d)));
d.window.close();

d = seite('fr');
pruefe(cookie(d) === 'fr', 'gespeicherte Sprache fr: Cookie schon beim Laden fr', String(cookie(d)));
// Gilt fuer die ganze Seite: von einem anderen Pfad derselben Herkunft sichtbar
const anderer = new JSDOM('<!doctype html><html><body></body></html>',
                          { url: 'https://beispiel.de/api/irgendwas', cookieJar: d.cookieJar });
pruefe(/jarvis_lang=fr/.test(anderer.window.document.cookie), 'Cookie gilt fuer die ganze Seite (path=/)');
d.window.close();
anderer.window.close();
bilanz();
