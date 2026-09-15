#!/usr/bin/env node
/**
 * Die Versionszeile der AI-Maus-Kachel sagt, wenn gerade gebaut wird.
 *
 * ⚠ AUSGEFUEHRT, NICHT IM QUELLTEXT GEMESSEN. Die Frage lautet "was STEHT
 * danach in der Zeile" – und das kann eine Textsuche nicht beantworten. Der
 * ECHTE Renderer laeuft gegen die ECHTE `ai_mouse.html` mit dem ECHTEN
 * `i18n.js`; gestellt wird nur die health-Antwort, ueber die Schnittstelle
 * `window.__amHealth`, die genau dafuer existiert.
 *
 * Gemeldet am 2026-09-15 fuer ECHT: „ich habe das update gemacht, dort ist
 * aber IMMER noch 1.0.7" – der Bau lief zu dem Zeitpunkt seit 90 Sekunden,
 * und die Kachel verschwieg das.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = fs.existsSync('/opt/jarvis/frontend') ? '/opt/jarvis'
  : path.resolve(__dirname, '..');

// jsdom an allen ueblichen Orten suchen – ein Waechter, der nur auf einem
// Rechner laeuft, ist ein halber.
let JSDOM = null;
for (const p of [process.env.JSDOM_PATH, ROOT + '/node_modules/jsdom',
                 ROOT + '/data/node_modules/jsdom', '/tmp/node_modules/jsdom',
                 '/usr/share/nodejs/jsdom', 'jsdom']) {
  if (!p) { continue; }
  try { JSDOM = require(p).JSDOM; break; } catch (e) { /* weiter */ }
}
if (!JSDOM) {
  // Exit 2: "konnte nicht laufen" darf nie wie "bestanden" aussehen.
  console.log('ABBRUCH: jsdom nicht gefunden (JSDOM_PATH setzen)');
  process.exit(2);
}

let ok = 0, fail = 0, bilanz = false;
function check(text, bed, info) {
  if (bed) { ok++; console.log('  OK   ' + text); }
  else { fail++; console.log('  FAIL ' + text + (info ? '  [' + info + ']' : '')); }
}

// Ein abgebrochener Lauf darf nicht wie ein bestandener aussehen.
process.on('exit', () => {
  if (!bilanz) { console.log('\n⚠ ABGEBROCHEN – keine Bilanz'); process.exitCode = 1; }
});

const wach = setTimeout(() => {
  console.log('\n⚠ TIMEOUT'); process.exit(1);
}, 40000);

(async () => {
  const html = fs.readFileSync(ROOT + '/frontend/ai_mouse.html', 'utf8');
  const dom = new JSDOM(html, { url: 'https://x/ai-mouse', runScripts: 'outside-only' });
  const w = dom.window;

  w.localStorage.setItem('jarvis_token', 'tok');
  w.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
  w.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });

  for (const f of ['frontend/js/i18n.js', 'frontend/js/ai_mouse.js']) {
    w.eval(fs.readFileSync(ROOT + '/' + f, 'utf8'));
  }

  const zeile = () => (w.document.getElementById('am-version') || {}).textContent || '';

  check('Positivkontrolle: die Schnittstelle existiert',
        typeof w.__amHealth === 'function');
  if (typeof w.__amHealth !== 'function') {
    bilanz = true; clearTimeout(wach);
    console.log('\n' + ok + ' OK, ' + fail + ' FAIL'); process.exit(1);
  }

  const basis = { paket_bereit: true, bereiche: [], aktive_bereiche: [] };

  console.log('=== 1) Ruhezustand: beide Versionen gleich ===');
  w.__amHealth(Object.assign({}, basis,
    { klient_version: '1.0.8', quelltext_version: '1.0.8', paket_baut: false }));
  check('die Version steht da', zeile().indexOf('1.0.8') >= 0, zeile());
  check('…und KEIN Bau-Hinweis (es gibt nichts Neues)',
        zeile().indexOf('·') < 0, zeile());

  console.log('\n=== 2) DER GEMELDETE FALL: Rollout durch, Bau steht aus ===');
  w.__amHealth(Object.assign({}, basis,
    { klient_version: '1.0.7', quelltext_version: '1.0.8', paket_baut: false }));
  check('die AUSGELIEFERTE Version steht weiter vorn', zeile().indexOf('1.0.7') >= 0, zeile());
  check('…und die neue wird BENANNT', zeile().indexOf('1.0.8') >= 0, zeile());
  check('…als "in Kürze"', /Kürze|shortly/.test(zeile()), zeile());
  console.log('  Zeile: ' + zeile());

  console.log('\n=== 3) Der Bau laeuft gerade ===');
  w.__amHealth(Object.assign({}, basis,
    { klient_version: '1.0.7', quelltext_version: '1.0.8', paket_baut: true }));
  check('…das wird anders gesagt als "kommt gleich"',
        /gerade gebaut|being built/.test(zeile()), zeile());
  check('…und nennt ebenfalls die Zielversion', zeile().indexOf('1.0.8') >= 0, zeile());
  console.log('  Zeile: ' + zeile());

  console.log('\n=== 4) Keine Behauptung ohne Angabe ===');
  w.__amHealth(Object.assign({}, basis,
    { klient_version: '1.0.7', paket_baut: false }));   // aelteres Backend
  check('fehlt quelltext_version, steht NUR die Version da',
        zeile().indexOf('1.0.7') >= 0 && zeile().indexOf('·') < 0, zeile());
  w.__amHealth(Object.assign({}, basis,
    { klient_version: '', quelltext_version: '1.0.8', paket_baut: true }));
  check('fehlt die EXE-Version, bleibt die Zeile ganz leer', zeile() === '', zeile());

  console.log('\n=== 5) Der Hinweis folgt dem Sprachwechsel ===');
  if (typeof w.setLang === 'function') {
    w.setLang('en');
    w.__amHealth(Object.assign({}, basis,
      { klient_version: '1.0.7', quelltext_version: '1.0.8', paket_baut: true }));
    check('englisch: der Hinweis ist uebersetzt',
          /being built/.test(zeile()) && !/gebaut/.test(zeile()), zeile());
    console.log('  Zeile: ' + zeile());
    w.setLang('de');
  } else {
    check('setLang vorhanden (sonst ist der Sprachwechsel ungeprueft)', false);
  }

  w.close();
  bilanz = true;
  clearTimeout(wach);
  console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  console.log('\n⚠ ABBRUCH: ' + (e && e.stack || e));
  bilanz = true;
  console.log('\n' + ok + ' OK, ' + (fail + 1) + ' FAIL (ABGEBROCHEN)');
  process.exit(1);
});
