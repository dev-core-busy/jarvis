#!/usr/bin/env node
/* Waechter: jeder im Frontend LITERAL benutzte i18n-Schluessel existiert in DE UND EN.
 *
 * Code-Review 2026-10-07: `445127d6` entfernte alle ext.*-Schluessel, ein
 * paralleler Zweig benutzte zwei davon weiter. Der Merge holte nur zwei von
 * vier zurueck – der Loesch-Dialog der Bearbeitungsmaske zeigte danach woertlich
 * `ext.delete_approved_confirm` statt der Frage, und der Benutzer bestaetigte
 * ein Loeschen, das er nicht lesen konnte. Kein Waechter sah das, weil jeder nur
 * die Schluessel SEINES Bereichs kannte. Hier gilt die REGEL fuer alle Dateien.
 *
 * Erfasst: t('…') / T('…') / window.t('…') mit literalem Schluessel und
 * data-i18n, -html, -title, -placeholder, -aria-label. Ein Schluessel mit
 * Unterstrich am Ende ist ein PRAEFIX einer Verkettung ('fbadm.typ_' + art)
 * und wird nicht gemessen – dafuer gibt es keinen statischen Namen.
 * Das Woerterbuch kommt aus der ECHTEN i18n.js (Objekt-Literal ausgewertet).
 *
 *   node tests/test_i18n_schluessel.js
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const FRONT = path.join(ROOT, 'frontend');
let ok = 0, fail = 0;
function check(cond, label, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + label); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + label + (detail ? ' – ' + detail : '')); }
}
function abbruch(grund) { console.log('\n\x1b[31mABBRUCH\x1b[0m: ' + grund); process.exit(2); }

// ── Woerterbuch ──────────────────────────────────────────────────────────
let I;
try {
    const src = fs.readFileSync(path.join(FRONT, 'js', 'i18n.js'), 'utf8');
    const anf = src.indexOf('const _I18N = {');
    const ende = src.indexOf('\n};', anf);
    if (anf < 0 || ende < 0) abbruch('_I18N-Literal in i18n.js nicht gefunden');
    I = new Function(src.slice(anf, ende + 3) + '; return _I18N;')();
} catch (e) { abbruch('i18n.js nicht auswertbar: ' + e.message); }
if (!I || !I.de || !I.en || Object.keys(I.de).length < 1000) abbruch('Woerterbuch unvollstaendig geladen');

// ── Sammeln ──────────────────────────────────────────────────────────────
const MUSTER = [
    /(?:^|[^\w.$])(?:window\.)?[tT]\(\s*'([a-z][\w-]*(?:\.[\w-]+)+)'/g,
    /(?:^|[^\w.$])(?:window\.)?[tT]\(\s*"([a-z][\w-]*(?:\.[\w-]+)+)"/g,
    /data-i18n(?:-html|-title|-placeholder|-aria-label)?="([a-z][\w-]*(?:\.[\w-]+)+)"/g,
];
function schluessel(text) {
    const raus = [];
    for (const re of MUSTER) {
        re.lastIndex = 0;
        let m;
        while ((m = re.exec(text))) if (!m[1].endsWith('_')) raus.push(m[1]);
    }
    return raus;
}

// Positivkontrolle der Erkennung an einer Probe mit bekannter Antwort
const probe = `x = t('a.b'); y = window.t("c.d"); z = T('e.f', 'Rueckfall');
<span data-i18n-title="g.h"></span> obj.t('nicht.gemeint'); fmt('kein.t');
w = T('praefix.typ_' + art);`;
const gef = schluessel(probe).sort().join(',');
check(gef === 'a.b,c.d,e.f,g.h', 'Erkennung findet genau die vier gemeinten Aufrufe', gef);
if (fail) abbruch('Erkennung fehlerhaft – jede Aussage darunter waere wertlos');

const dateien = [];
(function walk(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) { if (!/^(vendor|node_modules)$/.test(e.name)) walk(p); }
        else if (/\.(js|html)$/.test(e.name) && p !== path.join(FRONT, 'js', 'i18n.js')) dateien.push(p);
    }
})(FRONT);
check(dateien.length >= 50, 'Positivkontrolle: Frontend-Dateien gefunden (' + dateien.length + ')');

let gesamt = 0;
const fehlend = {};
for (const f of dateien) {
    for (const k of schluessel(fs.readFileSync(f, 'utf8'))) {
        gesamt++;
        for (const l of ['de', 'en']) {
            if (!Object.prototype.hasOwnProperty.call(I[l], k)) {
                (fehlend[k + ' [' + l + ']'] = fehlend[k + ' [' + l + ']'] || new Set()).add(path.relative(ROOT, f));
            }
        }
    }
}
check(gesamt >= 1000, 'Positivkontrolle: Schluessel-Verwendungen gefunden (' + gesamt + ')');
const bekannt = schluessel(fs.readFileSync(path.join(FRONT, 'api.html'), 'utf8'));
check(bekannt.includes('chat.logout'), 'Positivkontrolle: chat.logout in api.html erkannt');

console.log('');
const liste = Object.entries(fehlend);
check(liste.length === 0, 'jeder benutzte Schluessel existiert in DE und EN',
      liste.length + ' fehlen');
for (const [k, v] of liste) console.log('      ' + k + '  <-  ' + [...v].join(', '));

console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
process.exit(fail ? 1 : 0);
