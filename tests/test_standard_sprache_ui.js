#!/usr/bin/env node
/* Waechter: i18n.js nimmt ohne eigene Wahl die Standardsprache der
 * Installation aus dem Cookie, das der Server mitgibt (2026-11-26).
 *
 * Vorher: `localStorage … || 'de'` – eine in Franzoesisch installierte
 * Oberflaeche stand beim ersten Aufruf auf Deutsch.
 *
 * Gemessen am ECHTEN i18n.js in jsdom, je Fall ein frisches Fenster:
 *   Cookie fr, keine Wahl          -> fr
 *   gespeicherte Wahl en + Cookie fr -> en (eigene Wahl gewinnt)
 *   Cookie mit unbekannter Sprache -> de
 *   kein Cookie                    -> de
 * Pruefling umlenkbar: JARVIS_PRUEFLING_I18N.
 *
 *   node tests/test_standard_sprache_ui.js
 */
'use strict';

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const DATEI = process.env.JARVIS_PRUEFLING_I18N
    || path.resolve(__dirname, '..', 'frontend', 'js', 'i18n.js');
const QUELLE = fs.readFileSync(DATEI, 'utf8');

let ok = 0, fail = 0;
const pruefe = (bed, text, detail) => {
    if (bed) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (detail !== undefined ? ' – ' + detail : '')); }
};

function sprache(cookie, gespeichert) {
    const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>',
        { url: 'https://jarvis.beispiel.de/', runScripts: 'outside-only' });
    const w = dom.window;
    if (cookie) w.document.cookie = cookie + '; path=/';
    if (gespeichert) w.localStorage.setItem('jarvis_lang', gespeichert);
    w.eval(QUELLE);
    const erg = { lang: w._lang, cookie: w.document.cookie };
    w.close();
    return erg;
}

// Positivkontrolle: der Pruefling laeuft und legt die Sprache fest
const basis = sprache(null, null);
if (typeof basis.lang !== 'string' || !basis.lang) {
    console.log('ABBRUCH: i18n.js setzt window._lang nicht (' + basis.lang + ')');
    process.exit(2);
}

let r = sprache('jarvis_lang=fr', null);
pruefe(r.lang === 'fr', 'Cookie fr ohne eigene Wahl -> fr', r.lang);
pruefe(/jarvis_lang=fr/.test(r.cookie), '… und das Cookie bleibt fr (kein Zurueckschreiben auf de)', r.cookie);
r = sprache('jarvis_lang=nl', null);
pruefe(r.lang === 'nl', 'Cookie nl ohne eigene Wahl -> nl', r.lang);
r = sprache('jarvis_lang=fr', 'en');
pruefe(r.lang === 'en', 'gespeicherte Wahl gewinnt gegen das Cookie', r.lang);
r = sprache('jarvis_lang=xx', null);
pruefe(r.lang === 'de', 'unbekannte Sprache im Cookie -> de', r.lang);
r = sprache('anderes=fr', null);
pruefe(r.lang === 'de', 'fremdes Cookie mit Sprachwert zaehlt nicht -> de', r.lang);
pruefe(basis.lang === 'de', 'kein Cookie, keine Wahl -> de', basis.lang);

console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
