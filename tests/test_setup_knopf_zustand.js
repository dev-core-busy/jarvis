#!/usr/bin/env node
/* Waechter: Einrichtungs-Knoepfe sagen, was der Klick im JETZIGEN Zustand tut
 * (2026-11-25).
 *
 * DER FEHLER: "Einschalten / Reparieren" stand auch dann auf dem Knopf, wenn
 * die automatischen Sicherheitsupdates laengst eingeschaltet waren – der
 * Betreiber las daraus "ist aus". Dasselbe bei der Egress-Sperre
 * ("Einrichten / Reparieren") und der Sandbox ("Aktivieren / Reparieren").
 *
 * GEMESSEN am ECHTEN security_incidents.js + i18n.js in jsdom:
 * 1. aus  -> "Einschalten" / "Einrichten" / "Aktivieren"
 * 2. an   -> "Reparieren"
 * 3. der data-i18n-Schluessel wandert mit (ein Sprachwechsel setzt sonst den
 *    alten Doppeltext zurueck) – geprueft ueber applyTranslations auf EN.
 * 4. nach einer Aktion steht die Beschriftung des NEUEN Zustands auf dem
 *    Knopf, nicht der Text vom Klickzeitpunkt.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const WURZEL = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const lies = (p) => fs.readFileSync(path.join(WURZEL, p), 'utf8');
const JS = lies('frontend/js/security_incidents.js');
const I18N = lies('frontend/js/i18n.js');
const SITZUNG = lies('frontend/js/sitzung.js');
const ICONS = lies('frontend/js/icons.js');

// Absturz -> Exit 2, stilles Ende -> Exit 1 (EINE Quelle, test_waechter_bilanz.js)
const fertig = require('./lib/bilanz')({ stumm: true });

let ok = 0, fail = 0;
function check(text, bed, zusatz) {
  if (typeof text !== 'string' || typeof bed === 'string') {
    console.log('ABBRUCH: check(text, bedingung) vertauscht'); process.exit(2);
  }
  if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + text); }
  else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + text + (zusatz ? '  [' + zusatz + ']' : '')); }
}

// Knoepfe wie in settings.html (Ausgangstext = der kombinierte Platzhalter)
const KNOEPFE = [
  ['sec-unatt-setup', 'security.unattended_setup', 'sec-unatt-status', 'sec-unatt-result'],
  ['sec-egress-setup', 'security.egress_setup', 'sec-egress-status', 'sec-egress-result'],
  ['sec-sandbox-setup', 'security.sandbox_setup', 'sec-sandbox-status', 'sec-sandbox-result'],
];
const HTML_SETTINGS = lies('frontend/settings.html');

let SETUP_ANTWORT = null;
function welt() {
  const body = KNOEPFE.map(k => '<button id="' + k[0] + '" data-i18n="' + k[1] + '">x / y</button>'
    + '<div id="' + k[2] + '"></div><div id="' + k[3] + '"></div>').join('');
  const dom = new JSDOM('<!doctype html><html><body>' + body + '</body></html>',
    { url: 'https://example.invalid/settings', runScripts: 'outside-only' });
  const w = dom.window;
  w.localStorage.setItem('jarvis_token', 'tok');
  const f = (url) => {
    const u = String(url).split('?')[0];
    if (u === '/api/security/unattended/setup') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(SETUP_ANTWORT) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
  };
  w.fetch = f; global.fetch = f;
  w.eval(SITZUNG); w.eval(ICONS); w.eval(I18N); w.eval(JS);
  return w;
}
const txt = (w, id) => (w.document.getElementById(id).textContent || '').trim();
const warte = (ms) => new Promise(r => setTimeout(r, ms || 0));

(async function () {
  console.log('\x1b[1m0. Positivkontrolle\x1b[0m');
  const w = welt();
  const M = w.SecurityIncidents;
  check('SecurityIncidents geladen, Renderer vorhanden',
    !!(M && M.renderUnattended && M.renderEgress && M.renderSandbox));
  check('die drei Knoepfe stehen so in settings.html',
    KNOEPFE.every(k => HTML_SETTINGS.indexOf('id="' + k[0] + '" data-i18n="' + k[1] + '"') >= 0));
  if (fail) { console.log('ABBRUCH: Positivkontrolle fehlgeschlagen'); process.exit(2); }

  console.log('\x1b[1m1. Ausgeschaltet\x1b[0m');
  M.renderUnattended({ ok: false, enabled: false, timers: {} });
  M.renderEgress({ ok: false, configured: false, nft_active: false });
  M.renderSandbox({ ok: false, active: false, h10: {} });
  check('Sicherheitsupdates aus -> "Einschalten"', txt(w, 'sec-unatt-setup') === 'Einschalten', txt(w, 'sec-unatt-setup'));
  check('Egress-Sperre aus -> "Einrichten"', txt(w, 'sec-egress-setup') === 'Einrichten', txt(w, 'sec-egress-setup'));
  check('Sandbox aus -> "Aktivieren"', txt(w, 'sec-sandbox-setup') === 'Aktivieren', txt(w, 'sec-sandbox-setup'));

  console.log('\x1b[1m2. Eingeschaltet\x1b[0m');
  M.renderUnattended({ ok: true, enabled: true, timers: {} });
  M.renderEgress({ ok: true, configured: true, nft_active: true });
  M.renderSandbox({ ok: true, active: true, user_exists: true, secrets_locked: true, h10: {} });
  KNOEPFE.forEach(k => check(k[0] + ' an -> "Reparieren"', txt(w, k[0]) === 'Reparieren', txt(w, k[0])));
  M.renderUnattended({ ok: false, enabled: true, timers: {} });
  check('eingeschaltet, aber unvollstaendig -> ebenfalls "Reparieren"', txt(w, 'sec-unatt-setup') === 'Reparieren');

  console.log('\x1b[1m3. Sprachwechsel behaelt den Zustand\x1b[0m');
  if (typeof w.setLang === 'function') {
    w.setLang('en');
    if (typeof w.applyTranslations === 'function') w.applyTranslations();
    check('EN, eingeschaltet -> "Repair"', txt(w, 'sec-unatt-setup') === 'Repair', txt(w, 'sec-unatt-setup'));
    M.renderEgress({ ok: false, configured: false });
    if (typeof w.applyTranslations === 'function') w.applyTranslations();
    check('EN, Egress aus -> "Set up"', txt(w, 'sec-egress-setup') === 'Set up', txt(w, 'sec-egress-setup'));
    w.setLang('de');
    if (typeof w.applyTranslations === 'function') w.applyTranslations();
  } else {
    check('setLang vorhanden', false);
  }

  console.log('\x1b[1m4. Nach der Aktion gilt der NEUE Zustand\x1b[0m');
  M.renderUnattended({ ok: false, enabled: false, timers: {} });
  check('vorher "Einschalten"', txt(w, 'sec-unatt-setup') === 'Einschalten');
  SETUP_ANTWORT = { ok: true, steps: [], status: { ok: true, enabled: true, timers: {} } };
  M.setupUnattended();
  await warte(20);
  check('nach erfolgreichem Einschalten -> "Reparieren"', txt(w, 'sec-unatt-setup') === 'Reparieren', txt(w, 'sec-unatt-setup'));
  check('und der Knopf ist wieder bedienbar', !w.document.getElementById('sec-unatt-setup').disabled);

  fertig();
  console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
  process.exit(fail ? 1 : 0);
})();
