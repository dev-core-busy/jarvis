#!/usr/bin/env node
/* Waechter: Niederlaendisch ist eine vollwertige Oberflaechensprache.
 *
 * Seit 2026-11-25 liegt das niederlaendische Woerterbuch in
 * frontend/js/i18n_nl.js und haengt sich als _I18N.nl an das Literal aus
 * i18n.js (Muster: Franzoesisch, tests/test_i18n_fr.js – dort ist auch die
 * Bedienung des Klappmenues im Einzelnen geprueft). Damit NL nicht still
 * verwaist, misst dieser Waechter vier Zusagen:
 *
 *   1. VOLLSTAENDIG – jeder Schluessel aus dem DE-Block steht auch in NL,
 *      nicht leer, und NL kennt keinen Schluessel, den es in DE nicht gibt.
 *      Fehlt einer, saehe ein niederlaendischer Benutzer dort Englisch (t()
 *      faellt nl → en → de) – das ist kein Absturz, sondern eine Luecke,
 *      die niemand meldet.
 *   2. GLEICH GEBAUT – Platzhalter ({x}, %s), HTML-Tags und Zeilenumbrueche
 *      eines NL-Werts entsprechen dem EN-Wert. Ein verlorenes {marke} oder
 *      ein fehlendes </b> zerbricht die Anzeige, ohne dass ein Test es sieht.
 *   3. EINGEBUNDEN – jede HTML-Seite, die i18n.js laedt, laedt i18n_fr.js
 *      und DIREKT danach i18n_nl.js (vorher gibt es kein _I18N, spaeter
 *      haben Module beim Laden schon t() gerufen), und jede Sprachwahl mit
 *      FR-Knopf bietet auch NL an.
 *   4. WIRKSAM (jsdom, echte i18n.js + i18n_fr.js + i18n_nl.js) –
 *      setLang('nl') zeigt Niederlaendisch, die Rueckfallkette nl → en → de
 *      greift, und das Klappmenue fuehrt NL als vierte Sprache in fester
 *      Folge DE, EN, FR, NL.
 *      Die SICHTBARKEIT selbst (theme.css) misst jsdom nicht verlaesslich
 *      (Register: getComputedStyle ignoriert die Spezifitaet) – geprueft wird
 *      deshalb, dass die Regeln in theme.css stehen.
 *
 * Ausnahmen der Tag-Pruefung stehen einzeln mit Grund in AUSNAHMEN_TAGS.
 *
 *   node tests/test_i18n_nl.js     Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
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

/* Schluessel, deren "Tags" Platzhalter in spitzen Klammern sind und bewusst
 * uebersetzt werden – dort entfaellt nur der Tag-Vergleich. */
const AUSNAHMEN_TAGS = {
    'mail.style_text_suggest': '<Name>/<Department> sind Platzhalter im Vorschlagstext und duerfen uebersetzt werden',
};

// ── Woerterbuecher aus den ECHTEN Dateien ─────────────────────────────────
const SRC_I18N = fs.readFileSync(path.join(FRONT, 'js', 'i18n.js'), 'utf8');
const SRC_FR = fs.readFileSync(path.join(FRONT, 'js', 'i18n_fr.js'), 'utf8');
const SRC_NL = fs.readFileSync(path.join(FRONT, 'js', 'i18n_nl.js'), 'utf8');
let I;
try {
    const anf = SRC_I18N.indexOf('const _I18N = {');
    const ende = SRC_I18N.indexOf('\n};', anf);
    if (anf < 0 || ende < 0) abbruch('_I18N-Literal in i18n.js nicht gefunden');
    I = new Function(SRC_I18N.slice(anf, ende + 3) + ';\n' + SRC_FR + ';\n' + SRC_NL + ';\nreturn _I18N;')();
} catch (e) { abbruch('Woerterbuecher nicht auswertbar: ' + e.message); }
if (!I || !I.de || !I.en || !I.fr || !I.nl) abbruch('DE, EN, FR oder NL fehlt nach dem Laden');
const nDe = Object.keys(I.de).length;
if (nDe < 1000) abbruch('DE-Block unplausibel klein (' + nDe + ')');

console.log('\n\x1b[1m1. Vollstaendigkeit\x1b[0m');
const fehlend = Object.keys(I.de).filter(k => !(k in I.nl));
check(fehlend.length === 0, `jeder DE-Schluessel steht in NL (${nDe})`,
      fehlend.slice(0, 10).join(', ') + (fehlend.length > 10 ? ` … (+${fehlend.length - 10})` : ''));
const leer = Object.keys(I.nl).filter(k => typeof I.nl[k] !== 'string' || (!I.nl[k].trim() && (I.de[k] || '').trim()));
check(leer.length === 0, 'kein NL-Wert ist leer oder kein Text', leer.slice(0, 10).join(', '));
const fremd = Object.keys(I.nl).filter(k => !(k in I.de));
check(fremd.length === 0, 'NL kennt keinen Schluessel, den es in DE nicht gibt', fremd.slice(0, 10).join(', '));

console.log('\n\x1b[1m2. Gleicher Aufbau wie EN\x1b[0m');
const PH = /\{[A-Za-z_][\w.]*\}|%[a-zA-Z](?![a-zA-Z])|%\d/g;
const TAG = /<\/?([a-zA-Z][a-zA-Z0-9]*)/g;
const ENT = /&[a-z]+;|&#\d+;/g;
const sortiert = (s, re) => (s.match(re) || []).map(x => x.replace(/^<\/?/, '')).sort().join('|');
const umbr = s => (s.match(/\n/g) || []).length;
// Positivkontrolle der Merkmalsfunktionen an bekannter Antwort
if (sortiert('a {x} %s <b>c</b> %LOCAL%', PH) !== '%s|{x}' || sortiert('<b>x</b><br>', TAG) !== 'b|b|br') {
    abbruch('Merkmalserkennung fehlerhaft – jede Aussage darunter waere wertlos');
}
const abweich = { ph: [], tag: [], zeilen: [], ent: [] };
for (const k of Object.keys(I.nl)) {
    const en = I.en[k], nl = I.nl[k];
    if (typeof en !== 'string' || typeof nl !== 'string') continue;
    if (sortiert(en, PH) !== sortiert(nl, PH)) abweich.ph.push(k);
    if (!(k in AUSNAHMEN_TAGS) && sortiert(en, TAG) !== sortiert(nl, TAG)) abweich.tag.push(k);
    if (umbr(en) !== umbr(nl)) abweich.zeilen.push(k);
    if (sortiert(en, ENT) !== sortiert(nl, ENT)) abweich.ent.push(k);
}
check(abweich.ph.length === 0, 'Platzhalter wie in EN', abweich.ph.slice(0, 10).join(', '));
check(abweich.tag.length === 0, 'HTML-Tags wie in EN', abweich.tag.slice(0, 10).join(', '));
check(abweich.zeilen.length === 0, 'Zeilenumbrueche wie in EN', abweich.zeilen.slice(0, 10).join(', '));
check(abweich.ent.length === 0, 'HTML-Entitaeten wie in EN', abweich.ent.slice(0, 10).join(', '));
for (const k of Object.keys(AUSNAHMEN_TAGS)) {
    check(k in I.nl, `Ausnahme ${k} ist noch ein echter Schluessel`);
}

console.log('\n\x1b[1m3. Einbindung in den Seiten\x1b[0m');
const seiten = [];
(function walk(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) { if (!/^(vendor|node_modules)$/.test(e.name)) walk(p); }
        else if (e.name.endsWith('.html')) seiten.push(p);
    }
})(FRONT);
const RE_TAG = /<script\b[^>]*\bsrc="([^"]+)"[^>]*>\s*<\/script>/g;
let mitI18n = 0;
for (const p of seiten) {
    const roh = fs.readFileSync(p, 'utf8').replace(/<!--[\s\S]*?-->/g, '');
    const srcs = [...roh.matchAll(RE_TAG)].map(m => m[1].split('?')[0]);
    const i = srcs.indexOf('/static/js/i18n.js');
    if (i < 0) continue;
    mitI18n++;
    check(srcs[i + 1] === '/static/js/i18n_fr.js' && srcs[i + 2] === '/static/js/i18n_nl.js',
          `${path.relative(ROOT, p)}: i18n_fr.js und i18n_nl.js direkt nach i18n.js`,
          'danach: ' + (srcs.slice(i + 1, i + 3).join(', ') || '–'));
    const nFr = (roh.match(/data-setlang="fr"/g) || []).length, nNl = (roh.match(/data-setlang="nl"/g) || []).length;
    check(nFr === nNl, `${path.relative(ROOT, p)}: jede Sprachwahl mit FR bietet auch NL (${nFr}/${nNl})`);
}
const KOPF = fs.readFileSync(path.join(FRONT, 'js', 'kopfzeile.js'), 'utf8');
check(/data-setlang="nl"/.test(KOPF), 'kopfzeile.js: die Sprachwahl der Kopfzeile bietet NL');
check(mitI18n >= 20, `Positivkontrolle: Seiten mit i18n.js gefunden (${mitI18n})`);

console.log('\n\x1b[1m4. Wirkung (jsdom)\x1b[0m');
const { JSDOM } = require('./lib/jsdom_laden')();
const THEME = fs.readFileSync(path.join(FRONT, 'css', 'theme.css'), 'utf8');
check(/html\[data-lang="nl"\]\s*\.i18n-de/.test(THEME), 'theme.css: NL blendet die deutschen Fliesstextbloecke aus');
check(/:not\(\[data-lang="nl"\]\)\s*\.i18n-en/.test(THEME), 'theme.css: NL zeigt die englischen Fliesstextbloecke');

function seite(lang) {
    const knoepfe = ['de', 'en', 'fr', 'nl'].map(l =>
        `<button class="lang-toggle-btn" data-lang="${l}" data-setlang="${l}">${l.toUpperCase()}</button>`).join('');
    const dom = new JSDOM(`<!doctype html><html><body>
        <div class="lang-toggle" id="g1">${knoepfe}</div>
        <span id="w" data-i18n="portal.welcome"></span>
      </body></html>`, { runScripts: 'outside-only', url: 'https://beispiel.de/' });
    if (lang !== undefined) dom.window.localStorage.setItem('jarvis_lang', lang);
    // EIN eval: ein `const` aus einem eval ist nur dort sichtbar – im Browser
    // teilen sich klassische Skripte den globalen Geltungsbereich, hier nicht.
    dom.window.eval(SRC_I18N + '\n' + SRC_FR + '\n' + SRC_NL + '\nwindow.__I18N = _I18N;');
    dom.window.applyLang();
    return dom;
}
const klick = (w, el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
const reihe = g => [...g.children].map(b => b.dataset.lang).join(',');

{
    const dom = seite('de'), w = dom.window, d = w.document;
    const g1 = d.getElementById('g1');
    check(w.t('portal.welcome') === I.de['portal.welcome'], 'Positivkontrolle: DE liefert den DE-Text');
    klick(w, g1.querySelector('[data-lang="de"]'));
    const angeboten = [...g1.querySelectorAll('.lang-toggle-btn:not(.active)')].map(b => b.dataset.lang).sort().join(',');
    check(angeboten === 'en,fr,nl', 'angeboten werden EN, FR und NL', angeboten);
    klick(w, g1.querySelector('[data-lang="nl"]'));
    check(w._lang === 'nl' && w.localStorage.getItem('jarvis_lang') === 'nl', 'Klick auf NL setzt die Sprache');
    check(reihe(g1) === 'nl,de,en,fr', 'NL steht vorn, danach fest DE, EN, FR', reihe(g1));
    check(d.getElementById('w').textContent === I.nl['portal.welcome'], 'data-i18n zeigt den NL-Text',
          d.getElementById('w').textContent);
    check(d.documentElement.getAttribute('data-lang') === 'nl' && d.documentElement.getAttribute('lang') === 'nl',
          'html traegt data-lang und lang = nl');
    w.setLang('fr');
    check(reihe(g1) === 'fr,de,en,nl', 'nach NL → FR stehen die Angebote fest als DE, EN, NL', reihe(g1));
    w.setLang('nl');
    // Rueckfallkette nl → en → de
    const k = 'portal.welcome';
    const nlWert = I.nl[k];
    w.__I18N.nl[k] = undefined;
    check(w.t(k) === I.en[k], 'fehlt NL, zeigt t() Englisch', w.t(k));
    w.__I18N.en[k] = undefined;
    check(w.t(k) === I.de[k], 'fehlt auch EN, zeigt t() Deutsch', w.t(k));
    check(nlWert !== I.en[k] && I.en[k] !== I.de[k], 'Positivkontrolle: Probeschluessel unterscheidet sich je Sprache');
    dom.window.close();
}

console.log(`\n${ok} OK, ${fail} FAIL`);
process.exit(fail ? 1 : 0);
