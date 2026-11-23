/* Waechter: Einstellungen → Branding ist in Klapp-Container aufgeteilt
 * (Vorgabe des Betreibers 2026-11-15), gemessen am DOM der ECHTEN settings.html.
 *
 *   1. Positivkontrolle: Reiter und Bedienelemente sind ueberhaupt da (sonst
 *      waeren die Regeln unten trivial wahr) → sonst Exit 2.
 *   2. REGEL: jede .kb-section des Reiters ist in app.js::_initBrandingCollapse
 *      gebunden, und die Bindung laeuft beim Oeffnen des Reiters – eine
 *      gepflegte Liste vergaesse genau den neuen Container.
 *   3. REGEL: jede Kopfzeile hat Titel (h3 mit data-i18n), Pfeil und Koerper
 *      mit den Kennungen, die die Bindung erwartet.
 *   4. REGEL: jedes Eingabefeld des Reiters liegt in GENAU einem
 *      Container-Koerper – ausser "Speichern & anwenden" samt Statuszeile, die
 *      ausdruecklich AUSSERHALB stehen (sie speichern alle Container zugleich).
 *   5. Klappen wirkt: die ECHTE _collapseInit aus app.js geschnitten und
 *      ausgefuehrt – Klick auf die Kopfzeile schliesst und oeffnet den Koerper.
 *
 * Aufruf: node tests/test_branding_container_ui.js
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
// settings.html in jsdom ohne die Inhalte fremder Reiter (2026-11-23, Laufzeit;
// tests/lib/seite_ausschnitt.js, mitReitern). Textpruefungen lesen weiter die volle Seite.
const { JSDOM } = require('./lib/seite_ausschnitt')
    .mitReitern(require('./lib/jsdom_laden')(), ['settings-tab-branding']);

// Eine Gegenprobe kann eine sabotierte KOPIE von frontend/ ueber BR_ROOT geben.
const ROOT = process.env.BR_ROOT || path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
function abbruch(t) { console.log('ABBRUCH: ' + t); process.exit(2); }

const HTML = lies('frontend/settings.html');
const APP = lies('frontend/js/app.js');
const dom = new JSDOM(HTML, { url: 'https://localhost/settings' });
const d = dom.window.document;

console.log('\n1. Positivkontrolle');
const tab = d.getElementById('settings-tab-branding');
if (!tab) abbruch('Reiter #settings-tab-branding fehlt');
const felder = [...tab.querySelectorAll('input, select, textarea, button')];
if (felder.length < 20) abbruch('nur ' + felder.length + ' Bedienelemente im Reiter – falscher Schnitt?');
if (!d.getElementById('br-save')) abbruch('#br-save fehlt');
console.log('  ' + felder.length + ' Bedienelemente im Reiter');

console.log('\n2. Jede .kb-section ist gebunden');
const sects = [...tab.querySelectorAll('.kb-section')];
check(sects.length >= 2, 'der Reiter hat mehrere Container', String(sects.length));
const i = APP.indexOf('function _initBrandingCollapse(');
const fn = i >= 0 ? APP.slice(i, APP.indexOf('\n        }', i)) : '';
check(!!fn, '_initBrandingCollapse ist definiert');
const ungebunden = sects.map((s) => s.id).filter((id) => !id || !fn.includes("'" + id + "-hdr'"));
check(!!fn && ungebunden.length === 0, 'JEDE .kb-section ist klappbar gebunden', ungebunden.join(', '));
const j = APP.indexOf("target === 'branding'");
const zweig = j >= 0 ? APP.slice(j, APP.indexOf('} else if', j + 10)) : '';
check(/_initBrandingCollapse\(\);/.test(zweig), 'die Bindung laeuft beim Oeffnen des Reiters');

console.log('\n3. Aufbau je Container');
for (const s of sects) {
    const hdr = d.getElementById(s.id + '-hdr');
    const body = d.getElementById(s.id + '-body');
    const tog = d.getElementById(s.id + '-tog');
    const h3 = hdr && hdr.querySelector('h3');
    check(!!hdr && s.contains(hdr) && hdr.classList.contains('kb-collapse-header')
          && !!body && s.contains(body) && body.classList.contains('kb-collapse-body')
          && !!tog && hdr.contains(tog),
          s.id + ': Kopfzeile, Pfeil und Koerper vorhanden');
    check(!!h3 && !!h3.getAttribute('data-i18n') && h3.textContent.trim().length > 0,
          s.id + ': Titel mit i18n-Schluessel', h3 ? h3.outerHTML : 'kein h3');
}

console.log('\n4. Jedes Feld liegt in genau einem Container');
const AUSSEN = new Set(['br-save']);
const lose = [], doppelt = [];
for (const el of felder) {
    const n = sects.filter((s) => d.getElementById(s.id + '-body')
                                  && d.getElementById(s.id + '-body').contains(el)).length;
    const name = el.id || el.name || el.tagName;
    if (AUSSEN.has(el.id)) {
        if (n !== 0) doppelt.push(name + ' (gehoert ausserhalb)');
    } else if (n === 0) lose.push(name);
    else if (n > 1) doppelt.push(name);
}
check(lose.length === 0, 'kein Feld steht ausserhalb der Container', lose.join(', '));
check(doppelt.length === 0, 'kein Feld in mehreren Containern, Speichern steht aussen', doppelt.join(', '));

console.log('\n5. Klappen wirkt (echte _collapseInit)');
{
    const k = APP.indexOf('function _collapseInit(');
    if (k < 0) abbruch('_collapseInit nicht gefunden');
    const ende = APP.indexOf('\n        }\n', k);
    const quelle = APP.slice(k, ende + 10);
    const w = new JSDOM(HTML, { url: 'https://localhost/settings' }).window;
    const make = new w.Function('document', 'localStorage', 'sections',
        quelle + '\n_collapseInit(sections);');
    const liste = sects.map((s) => ({ hdr: s.id + '-hdr', body: s.id + '-body', tog: s.id + '-tog' }));
    make(w.document, w.localStorage, liste);
    const s0 = sects[0] && sects[0].id;
    const hdr = w.document.getElementById(s0 + '-hdr');
    const body = w.document.getElementById(s0 + '-body');
    if (!hdr || !body) abbruch('erster Container im zweiten DOM fehlt');
    const vorher = body.style.display;
    hdr.querySelector('h3').click();
    const nachEins = body.style.display;
    hdr.querySelector('h3').click();
    check(vorher !== 'none' && nachEins === 'none' && body.style.display !== 'none',
          s0 + ': Klick schliesst, zweiter Klick oeffnet',
          [vorher, nachEins, body.style.display].join(' → '));
    w.close();
}

dom.window.close();
console.log('\n' + '='.repeat(60));
console.log('Ergebnis: ' + ok + '/' + (ok + fail) + ' Pruefungen bestanden');
process.exit(fail ? 1 : 0);
