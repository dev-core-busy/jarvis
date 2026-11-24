#!/usr/bin/env node
/* Waechter: Franzoesisch ist eine vollwertige Oberflaechensprache.
 *
 * Seit 2026-11-24 liegt das franzoesische Woerterbuch in
 * frontend/js/i18n_fr.js und haengt sich als _I18N.fr an das Literal aus
 * i18n.js. Damit es nicht still verwaist, misst dieser Waechter vier Zusagen:
 *
 *   1. VOLLSTAENDIG – jeder Schluessel aus dem DE-Block steht auch in FR,
 *      nicht leer, und FR kennt keinen Schluessel, den es in DE nicht gibt.
 *      Fehlt einer, saehe ein franzoesischer Benutzer dort Englisch (t()
 *      faellt fr → en → de) – das ist kein Absturz, sondern eine Luecke,
 *      die niemand meldet.
 *   2. GLEICH GEBAUT – Platzhalter ({x}, %s), HTML-Tags und Zeilenumbrueche
 *      eines FR-Werts entsprechen dem EN-Wert. Ein verlorenes {marke} oder
 *      ein fehlendes </b> zerbricht die Anzeige, ohne dass ein Test es sieht.
 *   3. EINGEBUNDEN – jede HTML-Seite, die i18n.js laedt, laedt i18n_fr.js
 *      DIREKT danach (vorher gibt es kein _I18N, spaeter haben Module beim
 *      Laden schon t() gerufen).
 *   4. WIRKSAM (jsdom, echte i18n.js + i18n_fr.js) – setLang('fr') zeigt
 *      Franzoesisch, die Rueckfallkette fr → en → de greift, und die
 *      Sprachauswahl ist ein Klappmenue: die aktive Sprache steht vorn, ein
 *      Klick auf sie oeffnet/schliesst die Auswahl ohne Sprachwechsel, ein
 *      Klick auf eine andere setzt sie und schliesst, Esc und ein Klick
 *      daneben schliessen; bei unbekannter Sprache gilt DE als aktiv.
 *      Die SICHTBARKEIT selbst (theme.css) misst jsdom nicht verlaesslich
 *      (Register: getComputedStyle ignoriert die Spezifitaet) – geprueft wird
 *      deshalb, dass die Regeln in theme.css stehen.
 *
 * Ausnahmen der Tag-Pruefung stehen einzeln mit Grund in AUSNAHMEN_TAGS.
 *
 *   node tests/test_i18n_fr.js     Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
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
    'mail.style_text_suggest': '<Name>/<Department> sind Platzhalter im Vorschlagstext, FR: <Nom>/<Service>',
};

// ── Woerterbuecher aus den ECHTEN Dateien ─────────────────────────────────
const SRC_I18N = fs.readFileSync(path.join(FRONT, 'js', 'i18n.js'), 'utf8');
const SRC_FR = fs.readFileSync(path.join(FRONT, 'js', 'i18n_fr.js'), 'utf8');
let I;
try {
    const anf = SRC_I18N.indexOf('const _I18N = {');
    const ende = SRC_I18N.indexOf('\n};', anf);
    if (anf < 0 || ende < 0) abbruch('_I18N-Literal in i18n.js nicht gefunden');
    I = new Function(SRC_I18N.slice(anf, ende + 3) + ';\n' + SRC_FR + ';\nreturn _I18N;')();
} catch (e) { abbruch('Woerterbuecher nicht auswertbar: ' + e.message); }
if (!I || !I.de || !I.en || !I.fr) abbruch('DE, EN oder FR fehlt nach dem Laden');
const nDe = Object.keys(I.de).length;
if (nDe < 1000) abbruch('DE-Block unplausibel klein (' + nDe + ')');

console.log('\n\x1b[1m1. Vollstaendigkeit\x1b[0m');
const fehlend = Object.keys(I.de).filter(k => !(k in I.fr));
check(fehlend.length === 0, `jeder DE-Schluessel steht in FR (${nDe})`,
      fehlend.slice(0, 10).join(', ') + (fehlend.length > 10 ? ` … (+${fehlend.length - 10})` : ''));
const leer = Object.keys(I.fr).filter(k => typeof I.fr[k] !== 'string' || (!I.fr[k].trim() && (I.de[k] || '').trim()));
check(leer.length === 0, 'kein FR-Wert ist leer oder kein Text', leer.slice(0, 10).join(', '));
const fremd = Object.keys(I.fr).filter(k => !(k in I.de));
check(fremd.length === 0, 'FR kennt keinen Schluessel, den es in DE nicht gibt', fremd.slice(0, 10).join(', '));

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
const abweich = { ph: [], tag: [], nl: [], ent: [] };
for (const k of Object.keys(I.fr)) {
    const en = I.en[k], fr = I.fr[k];
    if (typeof en !== 'string' || typeof fr !== 'string') continue;
    if (sortiert(en, PH) !== sortiert(fr, PH)) abweich.ph.push(k);
    if (!(k in AUSNAHMEN_TAGS) && sortiert(en, TAG) !== sortiert(fr, TAG)) abweich.tag.push(k);
    if (umbr(en) !== umbr(fr)) abweich.nl.push(k);
    if (sortiert(en, ENT) !== sortiert(fr, ENT)) abweich.ent.push(k);
}
check(abweich.ph.length === 0, 'Platzhalter wie in EN', abweich.ph.slice(0, 10).join(', '));
check(abweich.tag.length === 0, 'HTML-Tags wie in EN', abweich.tag.slice(0, 10).join(', '));
check(abweich.nl.length === 0, 'Zeilenumbrueche wie in EN', abweich.nl.slice(0, 10).join(', '));
check(abweich.ent.length === 0, 'HTML-Entitaeten wie in EN', abweich.ent.slice(0, 10).join(', '));
for (const k of Object.keys(AUSNAHMEN_TAGS)) {
    check(k in I.fr, `Ausnahme ${k} ist noch ein echter Schluessel`);
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
    check(srcs[i + 1] === '/static/js/i18n_fr.js', `${path.relative(ROOT, p)}: i18n_fr.js direkt nach i18n.js`,
          'danach: ' + (srcs[i + 1] || '–'));
}
check(mitI18n >= 20, `Positivkontrolle: Seiten mit i18n.js gefunden (${mitI18n})`);

console.log('\n\x1b[1m4. Wirkung (jsdom)\x1b[0m');
const { JSDOM } = require('./lib/jsdom_laden')();
const THEME = fs.readFileSync(path.join(FRONT, 'css', 'theme.css'), 'utf8');
check(/\.lang-toggle:not\(\.offen\)\s*>\s*\.lang-toggle-btn:not\(\.active\)\s*\{\s*display:\s*none/.test(THEME),
      'theme.css blendet bei geschlossenem Menue die nicht aktiven Sprachen aus');
check(/\.lang-toggle\.offen\s*>\s*\.lang-toggle-btn:not\(\.active\)\s*\{[^}]*position:\s*absolute/.test(THEME),
      'theme.css legt die angebotenen Sprachen als Menue unter den Knopf');
check(/html\[data-lang="fr"\]\s*\.i18n-de/.test(THEME), 'theme.css: FR zeigt die englischen Fliesstextbloecke');

function seite(lang) {
    const dom = new JSDOM(`<!doctype html><html><body>
        <div class="lang-toggle" id="g1">
          <button class="lang-toggle-btn" data-lang="de" data-setlang="de">DE</button>
          <button class="lang-toggle-btn" data-lang="en" data-setlang="en">EN</button>
          <button class="lang-toggle-btn" data-lang="fr" data-setlang="fr">FR</button>
        </div>
        <div class="lang-toggle" id="g2">
          <button class="lang-toggle-btn" data-lang="de" data-setlang="de">DE</button>
          <button class="lang-toggle-btn" data-lang="en" data-setlang="en">EN</button>
          <button class="lang-toggle-btn" data-lang="fr" data-setlang="fr">FR</button>
        </div>
        <span id="w" data-i18n="portal.welcome"></span><p id="draussen">x</p>
      </body></html>`, { runScripts: 'outside-only', url: 'https://beispiel.de/' });
    if (lang !== undefined) dom.window.localStorage.setItem('jarvis_lang', lang);
    // EIN eval: ein `const` aus einem eval ist nur dort sichtbar – im Browser
    // teilen sich klassische Skripte den globalen Geltungsbereich, hier nicht.
    dom.window.eval(SRC_I18N + '\n' + SRC_FR + '\nwindow.__I18N = _I18N;');
    dom.window.applyLang();
    return dom;
}
const klick = (w, el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
const reihe = g => [...g.children].map(b => b.dataset.lang).join(',');
const aktiv = g => [...g.querySelectorAll('.lang-toggle-btn.active')].map(b => b.dataset.lang).join(',');

{
    const dom = seite('de'), w = dom.window, d = w.document;
    const g1 = d.getElementById('g1'), g2 = d.getElementById('g2');
    check(w.t('portal.welcome') === I.de['portal.welcome'], 'Positivkontrolle: DE liefert den DE-Text');
    check(aktiv(g1) === 'de' && reihe(g1).startsWith('de,'), 'DE aktiv und vorn', reihe(g1));
    // Klick auf die aktive Sprache: Menue auf, KEIN Sprachwechsel
    klick(w, g1.querySelector('[data-lang="de"]'));
    check(g1.classList.contains('offen') && w._lang === 'de', 'Klick auf DE oeffnet das Menue ohne Sprachwechsel');
    check(g1.firstElementChild.getAttribute('aria-expanded') === 'true', 'aktiver Knopf meldet aria-expanded=true');
    check(!g2.classList.contains('offen'), 'die zweite Gruppe bleibt zu');
    const angeboten = [...g1.querySelectorAll('.lang-toggle-btn:not(.active)')].map(b => b.dataset.lang).sort().join(',');
    check(angeboten === 'en,fr', 'angeboten werden die beiden anderen Sprachen', angeboten);
    // Klick auf FR: Sprache gesetzt, Menue zu, FR vorn – auch in der anderen Gruppe
    klick(w, g1.querySelector('[data-lang="fr"]'));
    check(w._lang === 'fr' && w.localStorage.getItem('jarvis_lang') === 'fr', 'Klick auf FR setzt die Sprache');
    check(!g1.classList.contains('offen'), 'danach ist das Menue zu');
    check(reihe(g1) === 'fr,de,en' && reihe(g2) === 'fr,de,en', 'FR steht in allen Gruppen vorn, danach DE, EN', reihe(g1) + ' / ' + reihe(g2));
    // Feste Folge der Angebote auch nach mehreren Wechseln (nicht die Wechselfolge)
    w.setLang('de');
    check(reihe(g1) === 'de,en,fr', 'nach FR → DE stehen die Angebote fest als EN, FR (nicht FR, EN)', reihe(g1));
    w.setLang('fr');
    check(d.getElementById('w').textContent === I.fr['portal.welcome'], 'data-i18n zeigt den FR-Text',
          d.getElementById('w').textContent);
    check(d.documentElement.getAttribute('data-lang') === 'fr' && d.documentElement.getAttribute('lang') === 'fr',
          'html traegt data-lang und lang = fr');
    // Zweimal auf die aktive: auf und wieder zu
    klick(w, g1.firstElementChild);
    klick(w, g1.firstElementChild);
    check(!g1.classList.contains('offen') && w._lang === 'fr', 'zweiter Klick auf die aktive Sprache schliesst');
    // Esc und Klick daneben schliessen
    klick(w, g1.firstElementChild);
    d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    check(!g1.classList.contains('offen'), 'Esc schliesst das Menue');
    klick(w, g1.firstElementChild);
    klick(w, d.getElementById('draussen'));
    check(!g1.classList.contains('offen'), 'Klick daneben schliesst das Menue');
    // Oeffnen der einen Gruppe schliesst die andere – vom Ausgangszustand
    // unabhaengig: beide erst zu, dann g1 auf, dann g2.
    g1.classList.remove('offen'); g2.classList.remove('offen');
    klick(w, g1.firstElementChild);
    check(g1.classList.contains('offen'), 'Positivkontrolle: g1 ist offen');
    klick(w, g2.firstElementChild);
    check(g2.classList.contains('offen') && !g1.classList.contains('offen'), 'nur eine Gruppe ist gleichzeitig offen');
    // Rueckfallkette fr → en → de
    const k = 'portal.welcome';
    const frWert = I.fr[k];
    w.__I18N.fr[k] = undefined;
    check(w.t(k) === I.en[k], 'fehlt FR, zeigt t() Englisch', w.t(k));
    w.__I18N.en[k] = undefined;
    check(w.t(k) === I.de[k], 'fehlt auch EN, zeigt t() Deutsch', w.t(k));
    check(frWert !== I.en[k] && I.en[k] !== I.de[k], 'Positivkontrolle: Probeschluessel unterscheidet sich je Sprache');
    dom.window.close();
}
{
    const dom = seite('xx'), d = dom.window.document;
    const g1 = d.getElementById('g1');
    check(aktiv(g1) === 'de' && reihe(g1).startsWith('de,'), 'unbekannte Sprache: DE gilt als aktiv (Gruppe nicht unsichtbar)',
          aktiv(g1) + ' / ' + reihe(g1));
    dom.window.close();
}

console.log(`\n${ok} OK, ${fail} FAIL`);
process.exit(fail ? 1 : 0);
