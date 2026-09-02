#!/usr/bin/env node
/* Waechter: die Vorfallsliste unterscheidet VERSTOSS und GRENZE (2026-09-02).
 *
 * WARUM ES DIESEN TEST GIBT: das Backend stuft seit dem 2026-08-05 ein
 * (`soft` + `soft_reason`), der Endpunkt reicht das Feld durch – und
 * `renderViolations` las es bis zum 2026-09-02 NIE. Gemessen auf DEV waren
 * allein 12 von 18 Eintraegen weich, also ausdruecklich KEIN Angriffsindiz,
 * und standen trotzdem unter derselben Ueberschrift wie ein echter Verstoss.
 * Dazu behauptete der Hinweistext darueber eine Auto-Sperre, die es fuer
 * genau diese Eintraege nicht gibt.
 *
 * GEMESSEN, NICHT GELESEN: der ECHTE Renderer laeuft gegen ein echtes DOM.
 * Eine Quelltext-Suche nach 'soft' bliebe gruen, sobald jemand das Feld liest
 * und dann doch nichts damit macht.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const WURZEL = path.resolve(__dirname, '..');
const JS = fs.readFileSync(path.join(WURZEL, 'frontend/js/security_incidents.js'), 'utf8');
const I18N = fs.readFileSync(path.join(WURZEL, 'frontend/js/i18n.js'), 'utf8');
const CSS = fs.readFileSync(path.join(WURZEL, 'frontend/css/style.css'), 'utf8');
const HTML = fs.readFileSync(path.join(WURZEL, 'frontend/settings.html'), 'utf8');

let ok = 0, fail = 0;
function check(text, bed, zusatz) {
  if (typeof text !== 'string' || typeof bed === 'string') {
    console.log('ABBRUCH: check(text, bedingung) vertauscht'); process.exit(2);
  }
  if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + text); }
  else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + text + (zusatz ? '  [' + zusatz + ']' : '')); }
}
// Ein Waechter, der beim Melden abbricht, verschluckt seine eigene Bilanz und
// ist von "nicht gelaufen" nicht zu unterscheiden.
process.on('unhandledRejection', (e) => { fail++; console.log('  \x1b[31m✗\x1b[0m unbehandelte Zurueckweisung: ' + e); });

/* Der Unter-Container wird aus der ECHTEN settings.html geschnitten, nicht
 * nachgebaut. Ein nachgebautes DOM prueft die Annahme seines Autors: faellt das
 * Filter-Kaestchen aus dem Markup, waere der Test weiter gruen. */
function markup() {
  const i = HTML.indexOf('id="sec-sub-viol"');
  if (i < 0) return null;
  const a = HTML.lastIndexOf('<details', i);
  const b = HTML.indexOf('</details>', i);
  if (a < 0 || b < 0) return null;
  return HTML.slice(a, b + 10);
}
const MARKUP = markup();

function welt(lang) {
  const dom = new JSDOM(
    '<!doctype html><html><body>'
    + (MARKUP || '<details id="sec-sub-viol"><summary><span id="sec-viol-count"></span></summary>'
                 + '<div id="sec-viol-list"></div></details>')
    + '<div id="sec-sect-incidents-hdr"></div></body></html>',
    // runScripts ist PFLICHT: ohne das ist `window.eval` NICHT die eval des
    // Fensters, sondern die von Node – i18n.js stirbt dann an 'window is not
    // defined' und der Lauf bricht ab, statt fehlzuschlagen. 'outside-only'
    // genuegt, weil dieses Minimal-DOM keine eigenen <script> mitbringt.
    { url: 'https://example.invalid/settings', runScripts: 'outside-only' });
  const w = dom.window;
  w.localStorage.setItem('jarvis_token', 'tok');
  w.eval(I18N);
  if (lang) { w._lang = lang; if (w.setLang) w.setLang(lang); }
  w.eval(JS);
  return w;
}

// Das Muster, das die Meldung ausgeloest hat: viel Rauschen, wenig Substanz.
const LISTE = [
  { ts: 1756800000, user: 'nexus\\a.b', channel: 'chat', pattern: 'shell-illegal',
    detail: 'cat /etc/shadow', tool: 'shell_execute' },                               // hart
  { ts: 1756800100, user: 'nexus\\a.b', channel: 'chat', pattern: 'blocked-tool',
    detail: 'spawn_agent', tool: 'spawn_agent', soft: true },                          // weich
  { ts: 1756800200, user: 'nexus\\c.d', channel: 'chat', pattern: 'fs-deny',
    detail: 'read /opt', tool: 'filesystem', soft: true },                             // weich
  { ts: 1756800300, user: 'nexus\\c.d', channel: 'chat', pattern: 'shell-write',
    detail: 'grep x 2>/dev/null', tool: 'shell_execute', soft: true },                 // weich
  { ts: 1756800400, user: 'wa:+49', channel: 'email', kind: 'injektion-erkannt',
    pattern: 'ignoriere-anweisungen', detail: 'IGNORIERE ALLE …', soft: true,
    soft_reason: 'nur protokolliert – der Text stammt von einem Fremden' },            // weich
  { ts: 1756800500, user: 'nexus\\e.f', channel: 'chat', pattern: 'kuenftige-art',
    detail: 'etwas Neues', soft: true, soft_reason: 'gespeicherter Grund aus dem Altbestand' }
];

console.log('\n\x1b[1m0. Der Schnitt aus der echten settings.html\x1b[0m');
check('der Unter-Container ist auffindbar (Positivkontrolle)', !!MARKUP);
check('er enthaelt Liste, Zaehler und Filter-Kaestchen',
  !!MARKUP && MARKUP.indexOf('sec-viol-list') !== -1
  && MARKUP.indexOf('sec-viol-count') !== -1
  && MARKUP.indexOf('sec-viol-onlyhard') !== -1,
  MARKUP ? MARKUP.length + ' Zeichen' : '-');

console.log('\n\x1b[1m1. Zaehler nennt BEIDE Zahlen, nicht eine Summe\x1b[0m');
let w = welt('de');
w.SecurityIncidents.renderViolations(LISTE);
const cnt = w.document.getElementById('sec-viol-count').textContent;
check('der Zaehler nennt Verstoesse UND Grenzen getrennt',
  /1\s+Verstoß/.test(cnt) && /5\s+Grenzen/.test(cnt), cnt);
check('er nennt NICHT nur die Gesamtzahl 6', cnt.indexOf('(6)') === -1, cnt);
check('Singular/Plural stimmen', cnt.indexOf('1 Verstoß ') !== -1 || /1 Verstoß\b/.test(cnt), cnt);

console.log('\n\x1b[1m2. Jede Zeile traegt ihre Einstufung als WORT\x1b[0m');
const zeilen = w.document.querySelectorAll('.sec-viol-row');
check('alle sechs Eintraege sind gerendert', zeilen.length === 6, 'n=' + zeilen.length);
const badges = w.document.querySelectorAll('.sec-viol-badge');
check('jede Zeile hat genau ein Abzeichen', badges.length === 6, 'n=' + badges.length);
// NIE ungeprueft dereferenzieren: fehlt das Abzeichen, WIRFT der Zugriff, der
// Lauf bricht ohne Bilanz ab und ist von "nicht gelaufen" nicht zu
// unterscheiden – genau das hat die erste Gegenprobe gezeigt (1 statt 12 FAIL).
function abz(z) { const b = z && z.querySelector('.sec-viol-badge'); return b ? b.textContent.trim() : '(KEIN ABZEICHEN)'; }
check('die harte Zeile ist als "Verstoß" bezeichnet', abz(zeilen[0]) === 'Verstoß', abz(zeilen[0]));
check('die harte Zeile traegt die Klasse is-hard', !!zeilen[0] && zeilen[0].classList.contains('is-hard'));
for (let i = 1; i < 6; i++) {
  check('weiche Zeile ' + i + ' ist als "Grenze" bezeichnet', abz(zeilen[i]) === 'Grenze', abz(zeilen[i]));
  check('weiche Zeile ' + i + ' traegt die Klasse is-soft',
    !!zeilen[i] && zeilen[i].classList.contains('is-soft'));
}
check('die Farbe ist NICHT die einzige Information (Wort im Abzeichen)',
  badges.length > 0 && Array.from(badges).every(b => b.textContent.trim().length > 0));

console.log('\n\x1b[1m3. Die Begruendung steht dabei – sonst ist das Abzeichen ein unerklaertes Zeichen\x1b[0m');
check('die harte Zeile hat KEINE Grenz-Begruendung',
  zeilen[0].querySelector('.sec-viol-reason') === null);
const grund = i => (zeilen[i].querySelector('.sec-viol-reason') || {}).textContent || '';
check('blocked-tool: nennt die Werkzeugwahl des Modells', /Werkzeugwahl des Modells/.test(grund(1)), grund(1));
check('fs-deny: nennt den geratenen Pfad', /geratener Pfad/.test(grund(2)), grund(2));
check('shell-write: nennt das Ziel ausserhalb /tmp', /außerhalb \/tmp/.test(grund(3)), grund(3));
check('Fremdtext-Vorfall: nennt den fremden Absender', /Fremden/.test(grund(4)), grund(4));
check('unbekannte Art faellt auf den GESPEICHERTEN Grund zurueck',
  /Altbestand/.test(grund(5)), grund(5));
check('jede weiche Zeile hat eine nicht-leere Begruendung',
  [1, 2, 3, 4, 5].every(i => grund(i).trim().length > 0));

console.log('\n\x1b[1m4. Fremdtext wird maskiert\x1b[0m');
const w2 = welt('de');
w2.SecurityIncidents.renderViolations([{
  ts: 1, user: '<img src=x onerror=alert(1)>', channel: 'chat', pattern: 'fs-deny',
  detail: '<script>boese()</script>', soft: true, soft_reason: '<b>roh</b>'
}]);
const box2 = w2.document.getElementById('sec-viol-list');
check('kein eingeschleustes Element im DOM',
  box2.querySelectorAll('img, script, b').length === 0,
  'gefunden: ' + box2.querySelectorAll('img, script, b').length);
check('der Text ist trotzdem lesbar', box2.textContent.indexOf('boese()') !== -1);

console.log('\n\x1b[1m5. Leere Liste unveraendert\x1b[0m');
const w3 = welt('de');
w3.SecurityIncidents.renderViolations([]);
check('leere Liste zeigt den Hinweis',
  w3.document.getElementById('sec-viol-list').textContent.indexOf('Keine Verstöße') !== -1);
check('und der Zaehler bleibt leer',
  w3.document.getElementById('sec-viol-count').textContent === '');

console.log('\n\x1b[1m6. Sprachwechsel\x1b[0m');
const w4 = welt('en');
w4.SecurityIncidents.renderViolations(LISTE);
const cntEn = w4.document.getElementById('sec-viol-count').textContent;
const zeilenEn = w4.document.querySelectorAll('.sec-viol-row');
check('englischer Zaehler nennt beide Zahlen',
  /1\s+Violation/i.test(cntEn) && /5\s+limits/i.test(cntEn), cntEn);
check('englische Abzeichen sind uebersetzt',
  abz(zeilenEn[0]) === 'Violation' && abz(zeilenEn[1]) === 'Limit',
  abz(zeilenEn[0]) + '/' + abz(zeilenEn[1]));
const grundEn = ((zeilenEn[1] || { querySelector: () => null })
  .querySelector('.sec-viol-reason') || {}).textContent || '';
check('die abgeleitete Begruendung ist ebenfalls uebersetzt',
  /model chose this tool/.test(grundEn), grundEn);

console.log('\n\x1b[1m7. Der Hinweistext behauptet keine Sperre mehr fuer alles\x1b[0m');
// Kommentare raus – sonst liest der Waechter seine eigene Begruendung mit.
const i18nOhneKommentar = I18N.replace(/\/\*[\s\S]*?\*\//g, '');
const mDe = i18nOhneKommentar.match(/'security\.violations_desc':\s*'((?:[^'\\]|\\.)*)'/);
check('der DE-Hinweistext ist auffindbar (Positivkontrolle)', !!mDe);
const desc = mDe ? mDe[1] : '';
check('er nennt beide Sorten beim Namen', /VERSTOSS/.test(desc) && /GRENZE/.test(desc), desc.slice(0, 60));
check('er sagt ausdruecklich, dass eine Grenze nichts sperrt',
  /sperrt nichts/.test(desc) && /zählt auch später nicht mit/.test(desc), desc);
check('das Rueckfall-Markup in settings.html ist deckungsgleich',
  HTML.indexOf(desc.replace(/\\'/g, "'")) !== -1);

console.log('\n\x1b[1m8. Filter "nur Verstoesse"\x1b[0m');
/* Der Filter ist der eigentliche Zweck der ganzen Aenderung: drei harte
 * Eintraege unter 150 sind sonst nur durch Scrollen zu finden. Er darf aber
 * nie den Eindruck erwecken, es sei weniger passiert – deshalb wird hier
 * ausdruecklich BEIDES gemessen: was er ausblendet UND dass er es sagt. */
const wf = welt('de');
wf.SecurityIncidents.renderViolations(LISTE);
const cb = wf.document.getElementById('sec-viol-onlyhard');
check('das Kaestchen ist da (Positivkontrolle)', !!cb);
check('Vorgabe ist AUS – niemand bekommt eine gefilterte Liste, ohne es zu wollen',
  !!cb && cb.checked === false);
check('ungefiltert stehen alle sechs Zeilen da',
  wf.document.querySelectorAll('.sec-viol-row').length === 6);
check('und es steht KEIN Ausblende-Hinweis da',
  wf.document.querySelector('.sec-viol-hidden') === null);

// Nie ungeprueft dereferenzieren: fehlt das Kaestchen, WIRFT der Zugriff und
// der Lauf bricht ohne Bilanz ab (Register – in diesem Waechter schon einmal
// bezahlt, siehe abz()).
function schalte(w, an) {
  const c = w.document.getElementById('sec-viol-onlyhard');
  if (!c) return false;
  c.checked = an;
  c.dispatchEvent(new w.Event('change'));
  return true;
}
check('das Kaestchen laesst sich schalten', schalte(wf, true));
const nachFilter = wf.document.querySelectorAll('.sec-viol-row');
check('gefiltert bleibt nur der harte Eintrag',
  nachFilter.length === 1, 'n=' + nachFilter.length);
check('und der ist wirklich der harte',
  nachFilter.length === 1 && nachFilter[0].classList.contains('is-hard'));
const hinweis = wf.document.querySelector('.sec-viol-hidden');
check('die Liste SAGT, wie viele Eintraege sie ausblendet',
  !!hinweis && /5/.test(hinweis.textContent), hinweis && hinweis.textContent);
check('der Zaehler nennt weiter den GESAMTbestand (nicht die gefilterte Menge)',
  /1\s+Verstoß/.test(wf.document.getElementById('sec-viol-count').textContent)
  && /5\s+Grenzen/.test(wf.document.getElementById('sec-viol-count').textContent),
  wf.document.getElementById('sec-viol-count').textContent);
check('die Wahl ist gemerkt',
  wf.localStorage.getItem('jarvis_sec_viol_nur_hart') === '1');

// Der gefaehrliche Fall: der Filter blendet ALLES aus.
const wf2 = welt('de');
wf2.localStorage.setItem('jarvis_sec_viol_nur_hart', '1');
wf2.SecurityIncidents.renderViolations(LISTE.filter(v => v.soft));
const leerText = wf2.document.getElementById('sec-viol-list').textContent;
check('bei "alles ausgefiltert" wird NICHT "nichts protokolliert" behauptet',
  leerText.indexOf('Keine Verstöße protokolliert') === -1, leerText.trim());
check('sondern gesagt, dass der Filter die Grenzen ausblendet',
  /ausgeblendet/.test(leerText) && /5/.test(leerText), leerText.trim());

// Zurueckschalten muss aus dem VOLLBESTAND zeichnen, nicht aus dem DOM.
schalte(wf, false);
check('Zurueckschalten holt die ausgeblendeten Eintraege wieder',
  wf.document.querySelectorAll('.sec-viol-row').length === 6,
  'n=' + wf.document.querySelectorAll('.sec-viol-row').length);

const wf3 = welt('de');
wf3.SecurityIncidents.renderViolations([]);
const box3 = wf3.document.getElementById('sec-viol-onlyhard-box');
check('bei leerer Liste ist das Kaestchen verborgen', !!box3 && box3.hidden === true);

console.log('\n\x1b[1m9. CSS: die beiden Sorten sehen verschieden aus\x1b[0m');
const cssOhneKommentar = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
function regel(sel) {
  const m = cssOhneKommentar.match(new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}'));
  return m ? m[1] : '';
}
check('.sec-viol-badge.is-hard ist definiert (Positivkontrolle)', regel('.sec-viol-badge.is-hard').length > 0);
check('.sec-viol-badge.is-soft ist definiert', regel('.sec-viol-badge.is-soft').length > 0);
check('die harte Variante benutzt die Gefahrfarbe',
  /--danger-rgb/.test(regel('.sec-viol-badge.is-hard')));
check('die weiche Variante NICHT',
  !/--danger-rgb/.test(regel('.sec-viol-badge.is-soft')));
check('keine harte Farbe (nur Theme-Variablen)',
  !/#[0-9a-fA-F]{3,6}/.test(regel('.sec-viol-badge.is-hard') + regel('.sec-viol-badge.is-soft')));
check('.sec-viol-reason ist definiert', regel('.sec-viol-reason').length > 0);

console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
setTimeout(() => process.exit(fail ? 1 : 0), 0);
