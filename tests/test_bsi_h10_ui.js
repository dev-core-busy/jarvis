#!/usr/bin/env node
/* Waechter BSI H10 – Sandbox-Panel in Einstellungen → Sicherheit (2026-10-05).
 *
 * GEMESSEN, NICHT GELESEN: der ECHTE Schnitt aus settings.html, das ECHTE
 * security_incidents.js, eine fetch-Attrappe, die jeden Abruf festhaelt.
 *
 * 0. Das Panel hat Schalter + drei Grenzfelder + Speichern, KEIN "Deaktivieren"
 *    mehr (die Sandbox ist Pflicht) – weder Knopf noch Funktion.
 * 1. Jeder data-i18n-Schluessel des Panels hat DE und EN.
 * 2. Laden: Schalter und Felder zeigen die Werte des Servers.
 * 3. Schalter umlegen -> POST mit booleschem auch_admins.
 * 4. Speichern -> POST mit Zahlen; die Felder zeigen danach die GEKLEMMTEN
 *    Werte der Antwort, nicht die Eingabe.
 * 5. Ein Fehler bleibt stehen (verschwindet nicht von selbst).
 * 6. Statuszeilen: "nicht eingerichtet" heisst "keine Shell", ein unbekannter
 *    Zustand ist "unbekannt" (nicht "nein"), {marke} ist eingesetzt.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const WURZEL = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();

const JS = fs.readFileSync(path.join(WURZEL, 'frontend/js/security_incidents.js'), 'utf8');
const I18N = fs.readFileSync(path.join(WURZEL, 'frontend/js/i18n.js'), 'utf8');
const SITZUNG = fs.readFileSync(path.join(WURZEL, 'frontend/js/sitzung.js'), 'utf8');
const HTML = fs.readFileSync(path.join(WURZEL, 'frontend/settings.html'), 'utf8');

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
process.on('exit', (code) => {
  if (!bilanz && code === 0) { console.log('\x1b[31mABGEBROCHEN – keine Bilanz\x1b[0m'); process.exitCode = 1; }
});

// Panel = von der Zwischenueberschrift bis zum naechsten Unter-Container.
function schnitt() {
  const a = HTML.indexOf('data-i18n="security.section_sandbox"');
  const b = HTML.indexOf('id="sec-sub-viol"', a);
  if (a < 0 || b < 0) return null;
  const von = HTML.lastIndexOf('<h4', a);
  const bis = HTML.lastIndexOf('<details', b);
  return (von >= 0 && bis > von) ? HTML.slice(von, bis) : null;
}
const PANEL = schnitt();

const ABRUFE = [];
let ANTWORT_CFG = null;
const STATUS = {
  ok: true, active: true, user: 'jarvis_sandbox', uid: 997, user_exists: true, secrets_locked: true,
  h10: { pflicht: true, auch_admins: true, systemd_run: true, bwrap: true, isolation_gewuenscht: true,
         lo_sperre: true, grenzen: { speicher_mb: 3072, prozesse: 300, cpu_prozent: 150 } },
  isolation: { secret_readable: false, tmp_writable: true, loopback_offen: false, grenzen_anwendbar: true }
};

function welt(lang) {
  const dom = new JSDOM('<!doctype html><html><body>' + (PANEL || '') + '</body></html>',
    { url: 'https://example.invalid/settings', runScripts: 'outside-only' });
  const w = dom.window;
  w.localStorage.setItem('jarvis_token', 'tok');
  ABRUFE.length = 0;
  const f = (url, opt) => {
    const u = String(url).split('?')[0];
    ABRUFE.push({ url: u, opt: opt || {} });
    if (u === '/api/security/sandbox') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(STATUS) });
    }
    if (u === '/api/security/sandbox/config') {
      const a = typeof ANTWORT_CFG === 'function' ? ANTWORT_CFG(opt) : ANTWORT_CFG;
      return Promise.resolve({ ok: a.status === 200, json: () => Promise.resolve(a.body) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  };
  w.fetch = f;
  global.fetch = f;
  w.eval(SITZUNG);
  /* ⚠ DAS ECHTE icons.js, keine Attrappe - und VOR dem Modul, wie das fruehe
   * <script> jeder Seite. Register 2026-10-06: fuenf Pruefstaende stellten
   * `JarvisIcons = { trash: ... }` von Hand; als `pencil()` dazukam, brachen
   * alle fuenf auf einmal, drei davon OHNE Bilanzzeile - und die Messung
   * meldete "0 gerendert", was wie ein Produktfehler aussieht. Hier fehlte es
   * GANZ: gemeldet von tests/test_prolog_vollstaendig.js (5 Referenzen auf
   * JarvisIcons in einem Fenster, das keines hat). Gruen war der Lauf nur,
   * weil kein Testfall ein Symbol zeichnet. */
  w.eval(fs.readFileSync(path.join(WURZEL, 'frontend/js/icons.js'), 'utf8'));
  w.eval(I18N);
  if (lang && w.setLang) w.setLang(lang);
  w.eval(JS);
  return w;
}
const warte = (ms) => new Promise(r => setTimeout(r, ms || 0));

(async () => {
  console.log('\n\x1b[1m0. Markup\x1b[0m');
  check('Panel aus settings.html geschnitten (Positivkontrolle)', !!PANEL && PANEL.indexOf('sec-sandbox-setup') !== -1);
  for (const id of ['sec-sandbox-admins', 'sec-sandbox-mem', 'sec-sandbox-tasks', 'sec-sandbox-cpu', 'sec-sandbox-save', 'sec-sandbox-cfg-status']) {
    check('Element #' + id + ' vorhanden', !!PANEL && PANEL.indexOf('id="' + id + '"') !== -1);
  }
  check('KEIN Knopf "Deaktivieren" mehr (ganze settings.html)', HTML.indexOf('sec-sandbox-teardown') === -1);
  check('kein Aufruf des entfernten Endpunkts im Skript', JS.indexOf('/api/security/sandbox/teardown') === -1);

  console.log('\n\x1b[1m1. i18n DE/EN\x1b[0m');
  const keys = PANEL ? Array.from(PANEL.matchAll(/data-i18n(?:-html)?="([^"]+)"/g)).map(m => m[1]) : [];
  check('Positivkontrolle: Schluessel gefunden (' + keys.length + ')', keys.length >= 8);
  for (const lang of ['de', 'en']) {
    const w = welt(lang);
    const fehlt = keys.filter(k => !w.t || w.t(k) === k);
    check(lang.toUpperCase() + ': alle Schluessel uebersetzt', fehlt.length === 0, fehlt.join(', '));
    w.close();
  }
  {
    const wd = welt('de'), we = welt('en');
    check('Schalter-Text unterscheidet sich DE/EN (EN ist wirklich Englisch)',
      wd.t('security.sandbox_admins') !== we.t('security.sandbox_admins'));
    wd.close(); we.close();
  }

  console.log('\n\x1b[1m2. Laden\x1b[0m');
  const w = welt('de');
  const M = w.SecurityIncidents;
  check('Modul geladen', !!M && typeof M.renderSandbox === 'function');
  check('Funktion zum Abschalten gibt es nicht mehr', !!M && typeof M.teardownSandbox === 'undefined');
  M._bind();
  M.loadSandbox(false);
  await warte(5);
  const $ = (id) => w.document.getElementById(id);
  check('Schalter zeigt Serverwert (an)', $('sec-sandbox-admins').checked === true);
  check('Felder zeigen Serverwerte', $('sec-sandbox-mem').value === '3072' && $('sec-sandbox-tasks').value === '300'
    && $('sec-sandbox-cpu').value === '150', [$('sec-sandbox-mem').value, $('sec-sandbox-tasks').value, $('sec-sandbox-cpu').value].join('/'));

  console.log('\n\x1b[1m3. Schalter umlegen\x1b[0m');
  ANTWORT_CFG = { status: 200, body: { ok: true, auch_admins: false, grenzen: STATUS.h10.grenzen } };
  ABRUFE.length = 0;
  $('sec-sandbox-admins').checked = false;
  $('sec-sandbox-admins').dispatchEvent(new w.Event('change'));
  await warte(5);
  const post = ABRUFE.find(a => a.url === '/api/security/sandbox/config');
  let body = {};
  try { body = JSON.parse((post && post.opt.body) || '{}'); } catch (e) { body = {}; }
  check('POST an /api/security/sandbox/config', !!post && post.opt.method === 'POST');
  check('Rumpf traegt boolesches auch_admins=false', body.auch_admins === false, JSON.stringify(body));
  check('Bestaetigung "Gespeichert"', /Gespeichert/.test($('sec-sandbox-cfg-status').textContent), $('sec-sandbox-cfg-status').textContent);

  console.log('\n\x1b[1m4. Grenzen speichern\x1b[0m');
  ANTWORT_CFG = { status: 200, body: { ok: true, auch_admins: false,
    grenzen: { speicher_mb: 128, prozesse: 64, cpu_prozent: 100 } } };
  ABRUFE.length = 0;
  $('sec-sandbox-mem').value = '5';
  $('sec-sandbox-tasks').value = '64';
  $('sec-sandbox-cpu').value = '100';
  $('sec-sandbox-save').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  await warte(5);
  const post2 = ABRUFE.find(a => a.url === '/api/security/sandbox/config');
  let body2 = {};
  try { body2 = JSON.parse((post2 && post2.opt.body) || '{}'); } catch (e) { body2 = {}; }
  check('Rumpf traegt Zahlen (nicht Text)', body2.speicher_mb === 5 && body2.prozesse === 64 && body2.cpu_prozent === 100,
    JSON.stringify(body2));
  check('Feld zeigt danach den GEKLEMMTEN Wert des Servers (128, nicht 5)', $('sec-sandbox-mem').value === '128',
    $('sec-sandbox-mem').value);

  console.log('\n\x1b[1m5. Fehler bleibt stehen\x1b[0m');
  ANTWORT_CFG = { status: 400, body: { ok: false, error: 'auch_admins muss true/false sein' } };
  $('sec-sandbox-save').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
  await warte(5);
  check('Fehlermeldung mit Grund', /✗/.test($('sec-sandbox-cfg-status').textContent)
    && /true\/false/.test($('sec-sandbox-cfg-status').textContent), $('sec-sandbox-cfg-status').textContent);
  await warte(2700);
  check('nach 2,7 s noch sichtbar (ein Erfolg verschwindet nach 2,5 s, ein Fehler nicht)',
    /✗/.test($('sec-sandbox-cfg-status').textContent));

  console.log('\n\x1b[1m6. Statuszeilen\x1b[0m');
  M.renderSandbox(STATUS);
  const box = $('sec-sandbox-status').textContent;
  check('Live-Test-Zeile Loopback vorhanden und {marke} eingesetzt', /Jarvis selbst aus der Sandbox/.test(box)
    && box.indexOf('{marke}') === -1, box.slice(0, 300));
  check('Zeile Obergrenzen vorhanden', /Obergrenzen für Speicher/.test(box));
  M.renderSandbox(Object.assign({}, STATUS, { ok: false, active: false }));
  check('kein Sandbox-Benutzer -> "keine Shell-Befehle" (nicht mehr "nur Code-Härtung")',
    /keine Shell-Befehle/.test($('sec-sandbox-status').textContent)
    && !/nur Code-Härtung/.test($('sec-sandbox-status').textContent), $('sec-sandbox-status').textContent.slice(0, 160));
  M.renderSandbox(Object.assign({}, STATUS, { h10: Object.assign({}, STATUS.h10, { lo_sperre: null }) }));
  // Nur BLATT-Zeilen (ohne eigene <div>-Kinder) – der Container enthaelt alle Zeilen.
  const zeilen = Array.from($('sec-sandbox-status').querySelectorAll('div'))
    .filter(d => !d.querySelector('div'))
    .map(d => d.textContent).filter(t => /Lokale Dienste/.test(t));
  // Seit Code-Review 2026-10-07 ohne Emoji: ✓ / ✗ / ? (Textzeichen)
  check('Loopback-Sperre nicht messbar -> "unbekannt" (?), nicht "nein"',
    zeilen.length >= 1 && zeilen.every(t => t.indexOf('?') === 0), zeilen.join(' | '));
  w.close();

  bilanz = true;
  console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
  process.exit(fail === 0 && ok > 0 ? 0 : 1);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
