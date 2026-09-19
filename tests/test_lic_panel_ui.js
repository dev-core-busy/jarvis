/**
 * Die Lizenz-Anzeige: Beschriftung und Hinweis folgen der BINDUNGSART.
 *
 * Gemessen wird die WIRKUNG am echten Markup mit dem echten i18n – eine
 * Quelltext-Suche koennte nicht beantworten, ob am Ende das richtige Label
 * dasteht. Der Codeblock wird aus der ECHTEN app.js geschnitten.
 */
const fs = require('fs'), path = require('path');
const ROOT = '/home/bender/ai/projekte/jarvis';
let ok = 0, fail = 0, bilanz = false;
const p = (b, t, i = '') => { b ? ok++ : fail++;
  console.log((b ? '  OK   ' : '  FAIL ') + t + (i ? `  (${i})` : '')); };

process.on('exit', () => {
  if (!bilanz) { console.log('\n(ABGEBROCHEN – keine Bilanz)'); process.exitCode = 1; }
});
const wachhund = setTimeout(() => {
  console.log('\nFAIL: Wachhund – der Lauf haengt'); process.exit(1);
}, 25000);

const { JSDOM } = require(path.join(ROOT, 'node_modules/jsdom'));

// Markup-Ausschnitt aus der ECHTEN settings.html schneiden (nicht nachbauen –
// ein Test, der sein Markup selbst schreibt, prueft seine eigene Annahme).
const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const i = html.indexOf('data-i18n="license.hwid_label"');
const j = html.indexOf('data-i18n="license.key_label"');
if (i < 0 || j < 0 || j < i) { console.log('FAIL: Schnitt verfehlt'); bilanz = true;
  console.log('\n0 OK, 1 FAIL'); process.exit(1); }
const block = html.slice(html.lastIndexOf('<label', i), j);
p(block.includes('lic-bind-hint'), 'Positivkontrolle: der Schnitt enthält die Hinweiszeile');

// ⚠ `runScripts: 'outside-only'` ist Pflicht: ohne das ist `window.eval` das
// eval von NODE – dort gibt es kein localStorage, und i18n.js stirbt beim Laden.
const dom = new JSDOM(`<!DOCTYPE html><body>${block}</body>`,
                      { url: 'https://x/settings', runScripts: 'outside-only' });
const { document } = dom.window;
global.document = document; global.window = dom.window;

// Echte i18n-Texte laden
const i18n = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
dom.window.eval(i18n);
const T = (k, f) => (dom.window.t ? dom.window.t(k) : null) || f;

// Den Anzeigeblock aus der echten app.js schneiden
const app = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
const a = app.indexOf("(function () {\n                const instanz = z.bindungsart");
const e = app.indexOf('})();', a);
if (a < 0 || e < 0) { console.log('FAIL: app.js-Schnitt verfehlt'); bilanz = true;
  console.log(`\n${ok} OK, ${fail + 1} FAIL`); process.exit(1); }
const code = app.slice(a, e + 5);
p(code.includes('setAttribute') && code.includes('lic-bind-hint'),
  'Positivkontrolle: der app.js-Schnitt enthält beide Zweige');

const zeigen = (art) => dom.window.eval(`(function(z, T){ ${code} })`)({ bindungsart: art }, T);
// ⚠ Nie ungeprueft dereferenzieren: fehlt das Element, wirft `.hidden`, und
// der Lauf endet OHNE Bilanzzeile – von "nicht gelaufen" nicht zu
// unterscheiden. Das Leer-Objekt macht daraus ein FAIL mit Bilanz.
const LEER = { textContent: '(FEHLT)', hidden: false, getAttribute: () => '(FEHLT)' };
const lbl  = () => document.querySelector('[data-i18n^="license."]') || LEER;
const hint = () => document.getElementById('lic-bind-hint') || LEER;

zeigen('hardware');
p(/Hardware/i.test(lbl().textContent), 'hardware: Beschriftung nennt Hardware', lbl().textContent);
p(hint().hidden, 'hardware: kein Container-Hinweis');

zeigen('instanz');
p(/Instanz|Container/i.test(lbl().textContent) && !/^Hardware-Kennung/.test(lbl().textContent),
  'instanz: Beschriftung behauptet KEINE Hardware', lbl().textContent);
p(!hint().hidden, 'instanz: der Hinweis erscheint');
p(/Datenverzeichnis|kopiert/i.test(hint().textContent),
  'instanz: der Hinweis nennt die Folge (Kopie überträgt die Bindung)');

// ⚠ Das data-i18n-ATTRIBUT muss mitwandern – sonst holt der naechste
// Sprachwechsel das falsche Label zurueck.
p(lbl().getAttribute('data-i18n') === 'license.instanz_label',
  'das data-i18n-Attribut folgt (Sprachwechsel bleibt richtig)',
  lbl().getAttribute('data-i18n'));
dom.window.setLang ? dom.window.setLang('en') : dom.window.applyLang && dom.window.applyLang();
p(/container/i.test(lbl().textContent) && !/Hardware ID/i.test(lbl().textContent),
  'nach dem Sprachwechsel steht der ENGLISCHE Container-Text', lbl().textContent);

// Beide neuen Schluessel muessen in BEIDEN Sprachen liegen – ein fehlender
// faellt sonst nur auf, wenn jemand die Oberflaeche umstellt.
const i18nQ = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
for (const k of ['license.instanz_label', 'license.instanz_hint']) {
  const n = (i18nQ.match(new RegExp(`'${k.replace('.', '\\.')}'`, 'g')) || []).length;
  p(n >= 2, `i18n-Schlüssel ${k} in DE und EN`, `${n}x gefunden`);
}

// und wieder zurueck
zeigen('hardware');
p(/Hardware/i.test(lbl().textContent) && hint().hidden,
  'Rückweg: hardware stellt Beschriftung und Hinweis zurück');

clearTimeout(wachhund);
bilanz = true;
console.log(`\n${ok} OK, ${fail} FAIL`);
process.exit(fail ? 1 : 0);
