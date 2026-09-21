#!/usr/bin/env node
/* Waechter: Benutzer-Pulldown in "Letzte Zugriffs-Verstoesse" (2026-09-21).
 *
 * GEMESSEN, NICHT GELESEN: der ECHTE Renderer laeuft gegen den ECHTEN Schnitt
 * aus settings.html, das Pulldown wird WIRKLICH umgestellt und der Abruf an
 * einer fetch-Attrappe abgegriffen. Ob der Filter beim SERVER landet oder still
 * im Client aussiebt, kann eine Quelltext-Suche nicht beantworten – und genau
 * daran haengt hier alles: der Endpunkt gibt die neuesten 150 ueber ALLE
 * Benutzer heraus, gespeichert sind bis zu 100 JE BENUTZER.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const WURZEL = path.resolve(__dirname, '..');
function ladeJsdom() {
  const orte = [process.env.JSDOM_PATH, path.join(WURZEL, 'node_modules'),
    '/tmp/node_modules', path.join(process.env.HOME || '', 'node_modules'),
    '/usr/lib/node_modules', '/usr/share/nodejs'].filter(Boolean);
  for (const o of orte) {
    try { return require(path.join(o, 'jsdom')); } catch (e) { /* weiter */ }
  }
  try { return require('jsdom'); } catch (e) { return null; }
}
const JSDOMMOD = ladeJsdom();
if (!JSDOMMOD) {
  // "Konnte nicht laufen" darf nie wie "bestanden" aussehen.
  console.log('ABBRUCH: jsdom nicht gefunden (JSDOM_PATH setzen)');
  process.exit(2);
}
const { JSDOM } = JSDOMMOD;

const JS = fs.readFileSync(path.join(WURZEL, 'frontend/js/security_incidents.js'), 'utf8');
const I18N = fs.readFileSync(path.join(WURZEL, 'frontend/js/i18n.js'), 'utf8');
const HTML = fs.readFileSync(path.join(WURZEL, 'frontend/settings.html'), 'utf8');
const CSS = fs.readFileSync(path.join(WURZEL, 'frontend/css/style.css'), 'utf8');

let ok = 0, fail = 0, bilanz = false;
function check(text, bed, zusatz) {
  if (typeof text !== 'string' || typeof bed === 'string') {
    console.log('ABBRUCH: check(text, bedingung) vertauscht'); process.exit(2);
  }
  if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + text); }
  else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + text + (zusatz ? '  [' + zusatz + ']' : '')); }
}
process.on('unhandledRejection', (e) => {
  fail++; console.log('  \x1b[31m✗\x1b[0m unbehandelte Zurueckweisung: ' + e);
});
// Ein Absturz in der async-IIFE beendet Node sonst mit Exit 0 und OHNE Bilanz.
process.on('exit', () => {
  if (!bilanz) { console.log('\x1b[31mABGEBROCHEN – keine Bilanz\x1b[0m'); process.exitCode = 1; }
});

/* Der Unter-Container wird aus der ECHTEN settings.html geschnitten. Ein
 * nachgebautes DOM prueft die Annahme seines Autors: faellt das Pulldown aus
 * dem Markup, waere der Test weiter gruen. */
function markup() {
  const i = HTML.indexOf('id="sec-sub-viol"');
  if (i < 0) return null;
  const a = HTML.lastIndexOf('<details', i);
  const b = HTML.indexOf('</details>', i);
  if (a < 0 || b < 0) return null;
  return HTML.slice(a, b + 10);
}
const MARKUP = markup();

let LETZTE_URL = null;
function welt(antwort, lang) {
  const dom = new JSDOM(
    '<!doctype html><html><body>'
    + (MARKUP || '<details id="x"></details>')
    + '<div id="sec-sect-incidents-hdr"></div></body></html>',
    { url: 'https://example.invalid/settings', runScripts: 'outside-only' });
  const w = dom.window;
  w.localStorage.setItem('jarvis_token', 'tok');
  LETZTE_URL = null;
  w.fetch = (url) => {
    LETZTE_URL = String(url);
    const d = typeof antwort === 'function' ? antwort(String(url)) : antwort;
    return Promise.resolve({ ok: true, json: () => Promise.resolve(d) });
  };
  w.eval(I18N);
  if (lang) { w._lang = lang; if (w.setLang) w.setLang(lang); }
  w.eval(JS);
  return w;
}

/* ⚠ ERST LADEN, DANN WAEHLEN. Vor dem ersten Abruf traegt das Pulldown nur
 * die eine statische Option aus dem Markup – ein `sel.value = 'x'` verpufft
 * dann wortlos (HTMLSelectElement setzt auf '', wenn es die Option nicht gibt),
 * und der Test misst einen Filter, den es nie gab. Genau so waren acht
 * Pruefungen dieses Waechters zuerst rot, ohne dass am Code etwas fehlte. */
async function mitFilter(w, user) {
  await w.SecurityIncidents.loadViolations();     // fuellt das Pulldown
  const sel = w.document.getElementById('sec-viol-user');
  sel.value = user;
  if (sel.value !== user) throw new Error('Option fehlt im Pulldown: ' + user);
  sel.dispatchEvent(new w.Event('change'));       // loest den zweiten Abruf aus
  await new Promise(r => setTimeout(r, 0));
  return sel;
}

function eintrag(user, ts, soft) {
  return { ts: ts, user: user, channel: 'chat', pattern: soft ? 'fs-deny' : 'shell-illegal',
    detail: 'd' + ts, soft: !!soft };
}
// Bestand: 4 Eintraege gesamt, davon 2 von a.b (einer hart, einer weich).
const ALLE = [eintrag('nexus\\a.b', 400), eintrag('nexus\\c.d', 300),
  eintrag('nexus\\a.b', 200, true), eintrag('wa:+49', 100, true)];
const NUR_AB = [ALLE[0], ALLE[2]];
const USERS = ['nexus\\a.b', 'nexus\\c.d', 'wa:+49'];
const GESAMT = { hart: 2, weich: 2, anzahl: 4 };

(async () => {

console.log('\n\x1b[1m0. Der Schnitt aus der echten settings.html\x1b[0m');
check('der Unter-Container ist auffindbar (Positivkontrolle)', !!MARKUP);
check('er enthaelt das Benutzer-Pulldown',
  !!MARKUP && MARKUP.indexOf('id="sec-viol-user"') !== -1);
check('und weiterhin Liste, Zaehler und Kaestchen "Nur Verstoesse"',
  !!MARKUP && MARKUP.indexOf('sec-viol-list') !== -1
  && MARKUP.indexOf('sec-viol-count') !== -1
  && MARKUP.indexOf('sec-viol-onlyhard') !== -1);

console.log('\n\x1b[1m1. ⚠ Das Pulldown steht im KOERPER, nicht im <summary>\x1b[0m');
/* GEMESSEN: ein <select> im <summary> klappt das <details> um – auch MIT
 * onclick="event.stopPropagation()". Die Aktivierung des <summary> ist kein
 * Zuhoerer, sondern das Default-Verhalten des Elements; stopPropagation greift
 * daran nicht. Ein Klick ins Pulldown wuerde den Abschnitt zuklappen. */
{
  const d = new JSDOM('<details id="d" open><summary>T <select id="in"><option>a</option></select></summary>'
    + '<div><select id="out"><option>a</option></select></div></details>');
  const w = d.window, det = w.document.getElementById('d');
  w.document.getElementById('in').dispatchEvent(
    new w.MouseEvent('click', { bubbles: true, cancelable: true }));
  const zu = det.open === false;
  det.open = true;
  w.document.getElementById('out').dispatchEvent(
    new w.MouseEvent('click', { bubbles: true, cancelable: true }));
  check('Positivkontrolle: ein <select> IM <summary> klappt den Abschnitt zu', zu,
    'open=' + det.open);
  check('ein <select> im KOERPER laesst ihn offen', det.open === true, 'open=' + det.open);
}
{
  const i = MARKUP ? MARKUP.indexOf('</summary>') : -1;
  const j = MARKUP ? MARKUP.indexOf('id="sec-viol-user"') : -1;
  check('das Pulldown steht deshalb HINTER dem </summary>', i > 0 && j > i,
    'summary@' + i + ' select@' + j);
}

console.log('\n\x1b[1m2. Der Filter geht an den SERVER, nicht in den Client\x1b[0m');
let w = welt({ violations: ALLE, users: USERS, gesamt: GESAMT }, 'de');
await w.SecurityIncidents.loadViolations();
check('ohne Auswahl wird OHNE Parameter geholt',
  LETZTE_URL === '/api/security/violations', LETZTE_URL);
const sel = w.document.getElementById('sec-viol-user');
check('das Pulldown ist gefuellt (Alle + 3 Benutzer)', !!sel && sel.options.length === 4,
  sel ? sel.options.length : '-');
check('der erste Eintrag ist "Alle Benutzer" mit leerem Wert',
  !!sel && sel.options[0].value === '' && /Alle Benutzer/.test(sel.options[0].textContent),
  sel ? sel.options[0].textContent : '-');

// Jetzt WIRKLICH umstellen und das change-Ereignis ausloesen.
w.fetch = (url) => {
  LETZTE_URL = String(url);
  return Promise.resolve({ ok: true, json: () => Promise.resolve(
    { violations: NUR_AB, users: USERS, gesamt: GESAMT }) });
};
sel.value = 'nexus\\a.b';
sel.dispatchEvent(new w.Event('change'));
await new Promise(r => setTimeout(r, 0));
check('⚠ ein Wechsel loest einen neuen ABRUF aus (Server-Filter)',
  LETZTE_URL && LETZTE_URL.indexOf('?user=') !== -1, LETZTE_URL);
check('der Name ist dabei kodiert',
  LETZTE_URL === '/api/security/violations?user=' + encodeURIComponent('nexus\\a.b'), LETZTE_URL);
check('die Liste zeigt danach nur die zwei Eintraege dieses Benutzers',
  w.document.querySelectorAll('.sec-viol-row').length === 2,
  'n=' + w.document.querySelectorAll('.sec-viol-row').length);

console.log('\n\x1b[1m3. Der Zaehler nennt den GESAMTbestand, auch gefiltert\x1b[0m');
const cnt = () => w.document.getElementById('sec-viol-count').textContent;
check('er nennt 2 Verstoesse und 2 Grenzen – nicht die gefilterten Zahlen',
  /2\s+Verstöße/.test(cnt()) && /2\s+Grenzen/.test(cnt()), cnt());
check('die Liste sagt ausdruecklich, dass gefiltert ist',
  /Gefiltert nach/.test(w.document.getElementById('sec-viol-list').textContent),
  w.document.getElementById('sec-viol-list').textContent.slice(0, 90));
check('und nennt dabei beide Zahlen (2 von 4)',
  /2 von 4/.test(w.document.getElementById('sec-viol-list').textContent),
  w.document.getElementById('sec-viol-list').textContent.slice(0, 90));
check('sowie den Benutzer',
  w.document.getElementById('sec-viol-list').textContent.indexOf('nexus\\a.b') !== -1);

console.log('\n\x1b[1m4. Die Leermeldung luegt nicht\x1b[0m');
{
  const w2 = welt(url => ({
    violations: url.indexOf('user=') === -1 ? ALLE : [],
    users: USERS, gesamt: GESAMT }), 'de');
  await mitFilter(w2, 'nexus\\c.d');
  const t = w2.document.getElementById('sec-viol-list').textContent;
  check('⚠ sie behauptet NICHT "Keine Verstoesse protokolliert"',
    t.indexOf('Keine Verstöße protokolliert') === -1, t);
  check('sie nennt den Benutzer und den Gesamtbestand',
    t.indexOf('nexus\\c.d') !== -1 && /4/.test(t), t);
}
{
  // Ohne Filter bleibt die alte Meldung unveraendert.
  const w3 = welt({ violations: [], users: [], gesamt: { hart: 0, weich: 0, anzahl: 0 } }, 'de');
  await w3.SecurityIncidents.loadViolations();
  check('ohne Filter und ohne Bestand bleibt "Keine Verstoeße protokolliert."',
    /Keine Verstöße protokolliert/.test(w3.document.getElementById('sec-viol-list').textContent),
    w3.document.getElementById('sec-viol-list').textContent);
  check('und das Filter-Kaestchen ist verborgen (nichts zu filtern)',
    w3.document.getElementById('sec-viol-onlyhard-box').hidden === true);
}
{
  // Benutzer gewaehlt, "Nur Verstoesse" an, er hat nur weiche: beides nennen.
  const w4 = welt(url => ({
    violations: url.indexOf('user=') === -1 ? ALLE : [eintrag('nexus\\a.b', 1, true)],
    users: USERS, gesamt: GESAMT }), 'de');
  w4.localStorage.setItem('jarvis_sec_viol_nur_hart', '1');
  await mitFilter(w4, 'nexus\\a.b');
  const t = w4.document.getElementById('sec-viol-list').textContent;
  check('"nur harte" + Benutzer: beide Filter werden benannt',
    t.indexOf('nexus\\a.b') !== -1 && /1 Grenze/.test(t), t);
}

console.log('\n\x1b[1m5. Das Kaestchen "Nur Verstoesse" bleibt bedienbar\x1b[0m');
{
  // Benutzer ohne Treffer gewaehlt: die Liste ist leer, das Kaestchen aber
  // NICHT – sonst verschwaende ein Bedienelement mit gemerktem Zustand.
  const w5 = welt(url => ({
    violations: url.indexOf('user=') === -1 ? ALLE : [],
    users: USERS, gesamt: GESAMT }), 'de');
  await mitFilter(w5, 'nexus\\c.d');
  check('bei leerer gefilterter Liste bleibt es sichtbar (Bestand > 0)',
    w5.document.getElementById('sec-viol-onlyhard-box').hidden === false);
}

console.log('\n\x1b[1m6. Fremdtext im Namen wird nicht ausgefuehrt\x1b[0m');
{
  const boes = '<img src=x onerror=alert(1)>';
  const w6 = welt({ violations: [eintrag(boes, 1)], users: [boes],
    gesamt: { hart: 1, weich: 0, anzahl: 1 } }, 'de');
  await w6.SecurityIncidents.loadViolations();
  const s6 = w6.document.getElementById('sec-viol-user');
  check('das Pulldown baut kein Markup aus dem Namen',
    s6.querySelectorAll('img').length === 0 && s6.options[1].textContent === boes,
    s6.innerHTML.slice(0, 80));
  s6.value = boes;
  s6.dispatchEvent(new w6.Event('change'));
  await new Promise(r => setTimeout(r, 0));
  const t6 = w6.document.getElementById('sec-viol-list');
  check('und die Hinweiszeile ebenfalls nicht',
    t6.querySelectorAll('img').length === 0
    && t6.textContent.indexOf(boes) !== -1, t6.innerHTML.slice(0, 120));
}

console.log('\n\x1b[1m7. Die getroffene Wahl ueberlebt den Neuaufbau\x1b[0m');
{
  const w7 = welt({ violations: NUR_AB, users: USERS, gesamt: GESAMT }, 'de');
  const s7 = await mitFilter(w7, 'nexus\\a.b');
  check('die Auswahl steht nach dem Neufuellen weiter', s7.value === 'nexus\\a.b', s7.value);
  // Ein Benutzer, der inzwischen aus dem Speicher gefallen ist, bleibt
  // ausdruecklich stehen – sonst spraenge die Auswahl wortlos auf "Alle" und
  // die Liste zeigte etwas anderes, als das Pulldown behauptet.
  w7.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { violations: NUR_AB, users: ['nexus\\c.d'], gesamt: GESAMT }) });
  await w7.SecurityIncidents.loadViolations();
  check('⚠ ein nicht mehr gelisteter Benutzer bleibt waehlbar, statt stumm zurueckzuspringen',
    s7.value === 'nexus\\a.b', s7.value);
  check('genau einmal, nicht doppelt',
    Array.from(s7.options).filter(o => o.value === 'nexus\\a.b').length === 1);
}

console.log('\n\x1b[1m8. Der Filter wird NICHT gemerkt\x1b[0m');
/* Anders als "Nur Verstoesse": ein gemerkter Benutzer-Filter verbirgt HARTE
 * Verstoesse ANDERER – ein Administrator oeffnet den Reiter, liest "nichts
 * Neues" und sieht in Wahrheit einen drei Wochen alten Filter. */
{
  const w8 = welt({ violations: ALLE, users: USERS, gesamt: GESAMT }, 'de');
  await mitFilter(w8, 'nexus\\a.b');
  let gespeichert = 0;
  for (let i = 0; i < w8.localStorage.length; i++) {
    const k = w8.localStorage.key(i);
    if (String(w8.localStorage.getItem(k)).indexOf('a.b') !== -1) gespeichert++;
  }
  check('kein localStorage-Eintrag traegt den gewaehlten Benutzer', gespeichert === 0,
    'n=' + gespeichert);
  check('Positivkontrolle: das harte Kaestchen wird sehr wohl gemerkt',
    (() => { const c = w8.document.getElementById('sec-viol-onlyhard');
      c.checked = true; c.dispatchEvent(new w8.Event('change'));
      return w8.localStorage.getItem('jarvis_sec_viol_nur_hart') === '1'; })());
}

console.log('\n\x1b[1m9. Aelteres Backend: ohne "gesamt" gilt die Liste selbst\x1b[0m');
{
  const w9 = welt({ violations: ALLE }, 'de');
  await w9.SecurityIncidents.loadViolations();
  const c9 = w9.document.getElementById('sec-viol-count').textContent;
  check('der Zaehler faellt auf die Zahlen der Liste zurueck',
    /2\s+Verstöße/.test(c9) && /2\s+Grenzen/.test(c9), c9);
  check('und es steht keine Filterzeile da', 
    !/Gefiltert nach/.test(w9.document.getElementById('sec-viol-list').textContent));
}

console.log('\n\x1b[1m10. Sprachwechsel und CSS\x1b[0m');
{
  const w10 = welt({ violations: NUR_AB, users: USERS, gesamt: GESAMT }, 'en');
  await mitFilter(w10, 'nexus\\a.b');
  const t10 = w10.document.getElementById('sec-viol-list').textContent;
  check('englisch: die Filterzeile ist uebersetzt', /Filtered by/.test(t10), t10.slice(0, 70));
  check('englisch: "All users" im Pulldown',
    /All users/.test(w10.document.getElementById('sec-viol-user').options[0].textContent));
}
function regel(name) {
  // Ohne Kommentare: sonst liest der Waechter seine eigene Begruendung.
  const rein = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
  const i = rein.indexOf(name + ' {');
  if (i < 0) return '';
  return rein.slice(i, rein.indexOf('}', i) + 1);
}
check('Positivkontrolle: der Kommentar-Filter laesst Code stehen',
  regel('.sec-viol-filter').indexOf('display') !== -1);
check('.sec-viol-filter bricht um statt aus dem Abschnitt zu laufen',
  /flex-wrap\s*:\s*wrap/.test(regel('.sec-viol-filter')));
check('⚠ .sec-viol-user hat min-width: 0 (sonst schiebt ein langer Name das '
  + 'Kaestchen hinaus)', /min-width\s*:\s*0/.test(regel('.sec-viol-user')));
check('und eine Obergrenze', /max-width/.test(regel('.sec-viol-user')));
check('keine harte Farbe – nur Theme-Variablen',
  !/#[0-9a-fA-F]{3,6}\b/.test(regel('.sec-viol-user') + regel('.sec-viol-filter')));

console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
bilanz = true;
process.exit(fail ? 1 : 0);

})().catch(e => {
  fail++;
  console.log('  \x1b[31m✗\x1b[0m ABBRUCH: ' + (e && e.stack || e));
  console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + ' (ABGEBROCHEN)\x1b[0m');
  bilanz = true;
  process.exit(1);
});
