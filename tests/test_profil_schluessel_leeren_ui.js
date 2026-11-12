#!/usr/bin/env node
/* Waechter (2026-11-12): der Schluessel eines LLM-Profils laesst sich LEEREN.
 *
 * Gemeldet: unter KI & System -> LLM-Profile liess sich der API-Key nicht mit
 * einem leeren Wert ueberschreiben – ein leeres Feld hiess immer
 * "unveraendert" (BSI M5: das Formular laedt den Schluessel nicht mehr).
 * Derselbe Fehler wie am Morgen beim STT-Token.
 *
 * Gemessen am ECHTEN settings.html + app.js in jsdom, fetch als Attrappe:
 *   1. nie angefasst, leer gespeichert   -> KEIN api_key_entfernen (unveraendert)
 *   2. getippt und wieder geleert        -> api_key_entfernen: true
 *   3. per Auge geholt, dann geleert     -> api_key_entfernen: true
 *   4. neuer Wert                        -> der Wert, kein Entfernen
 *   5. Profil OHNE gespeicherten Schluessel, getippt+geleert -> kein Entfernen
 *   6. "Verbindung testen" nach dem Leeren nimmt NICHT den gespeicherten
 *      (profile_id leer); unangefasst schon (profile_id gesetzt)
 *
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 * Lauf:  timeout 60 node tests/test_profil_schluessel_leeren_ui.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const HTML = lies('frontend/settings.html');
const SITZUNG = lies('frontend/js/sitzung.js');
const MODULE = ['frontend/js/icons.js', 'frontend/js/i18n.js', 'frontend/js/theme.js', 'frontend/js/app.js'];

let OK = 0, FAIL = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) OK++; else FAIL++;
    console.log((cond ? '  ✓ ' : '  ✗ ') + name + (!cond && detail !== undefined ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }
function bilanz() { BILANZ = true; console.log('\nErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL'); }
process.on('exit', (code) => {
    if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; }
});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Antwortform wie GET /api/settings: Schluessel maskiert (_mask_key)
const PROFILE = [
    { id: 'p1', name: 'Mit Key', provider: 'openai', model: 'm1', api_url: 'https://api.beispiel.de/v1',
      api_key: 'sk-…***', auth_method: 'api_key', session_key: '' },
    { id: 'p2', name: 'Ohne Key', provider: 'openai', model: 'm2', api_url: 'http://192.0.2.7:11434/v1',
      api_key: '', auth_method: 'api_key', session_key: '' },
];

let calls = [];
function j(obj) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(obj), text: () => Promise.resolve(JSON.stringify(obj)) });
}
function appFetch(url, opts) {
    const u = String(url).split('?')[0];
    const method = (opts && opts.method) || 'GET';
    calls.push({ url: u, method, body: opts && opts.body });
    if (u === '/api/settings') return j({ profiles: PROFILE, active_profile_id: 'p1', defaults: {} });
    if (/^\/api\/profiles\/p\d$/.test(u) && method === 'PUT') return j({ success: true, profile: {} });
    if (u === '/api/profiles/test') return j({ success: true, message: 'ok' });
    if (u.startsWith('/api/settings/ldap')) return j({ access_mode: 'none' });
    if (u.startsWith('/api/settings')) return j({});
    if (u.startsWith('/api/me')) return j({ username: 'jarvis', is_admin: true, permissions: {} });
    if (u.startsWith('/api/skills')) return j({ skills: [] });
    if (u.startsWith('/api/branding')) return j({ enabled: false });
    return j({ ok: true, items: [], skills: [], groups: [], profiles: [] });
}

async function main() {
    const dom = new JSDOM(HTML, { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    w.localStorage.setItem('jarvis_user', 'jarvis');
    w.confirm = () => true;
    w.alert = () => {};
    w.scrollTo = () => {};
    w.WebSocket = class { constructor() { this.readyState = 0; } send() {} close() {} addEventListener() {} };
    w.fetch = appFetch;
    for (const f of MODULE) {
        w.eval(SITZUNG);
        try { w.eval(lies(f)); } catch (e) { console.log('    (Modul ' + f + ': ' + e.message + ')'); }
    }
    // Auge: Attrappe in der Antwortform von JarvisPwEye.abruf ({ok, d})
    w.JarvisPwEye = { abruf: () => Promise.resolve({ ok: true, d: { api_key: 'sk-alt-klartext' } }) };
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    await sleep(30);
    const d = w.document;

    section('0) Positivkontrolle: Messaufbau');
    check('Modal-Oeffner erreichbar', typeof w._openSettingsModal === 'function');
    if (FAIL) { bilanz(); w.close(); process.exit(2); }
    await w._openSettingsModal();
    await sleep(150);
    const editBtn = (id) => d.querySelector('#profiles-container .btn-edit-profile[data-id="' + id + '"]');
    check('Bearbeiten-Knopf fuer beide Profile gezeichnet', !!editBtn('p1') && !!editBtn('p2'));
    const key = d.getElementById('profile-api-key');
    const save = d.getElementById('btn-save-profile');
    const auge = d.getElementById('btn-toggle-profile-apikey');
    const testBtn = d.getElementById('btn-test-profile');
    check('Schluesselfeld, Speichern, Auge und Test vorhanden', !!key && !!save && !!auge && !!testBtn);
    if (FAIL) { bilanz(); w.close(); process.exit(2); }

    const klick = (el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    const tippe = (wert) => { key.value = wert; key.dispatchEvent(new w.Event('input', { bubbles: true })); };
    async function oeffnen(id) { klick(editBtn(id)); await sleep(40); }
    async function speichern(id) {
        calls = [];
        klick(save);
        await sleep(60);
        const put = calls.find((c) => c.method === 'PUT' && c.url === '/api/profiles/' + id);
        try { return put ? JSON.parse(put.body) : null; } catch (e) { return null; }
    }
    async function testen() {
        calls = [];
        klick(testBtn);
        await sleep(60);
        const t = calls.find((c) => c.url === '/api/profiles/test');
        try { return t ? JSON.parse(t.body) : null; } catch (e) { return null; }
    }

    await oeffnen('p1');
    check('Positivkontrolle: gespeicherter Schluessel zeigt Sterne, Feld leer',
        key.value === '' && /•/.test(key.placeholder), JSON.stringify([key.value, key.placeholder]));
    let b = await speichern('p1');
    check('Positivkontrolle: Speichern schickt ein PUT', !!b, 'kein PUT');
    if (!b) { bilanz(); w.close(); process.exit(2); }

    section('1) nie angefasst = unveraendert');
    check('kein api_key_entfernen', !('api_key_entfernen' in b), JSON.stringify(b));
    check('api_key leer (Server behaelt den gespeicherten)', b.api_key === '', JSON.stringify(b.api_key));

    section('2) getippt und wieder geleert = loeschen');
    await oeffnen('p1');
    tippe('x'); tippe('');
    b = await speichern('p1');
    check('api_key_entfernen: true', !!b && b.api_key_entfernen === true, JSON.stringify(b));
    check('api_key leer', !!b && b.api_key === '', b && JSON.stringify(b.api_key));

    section('3) per Auge geholt, dann geleert = loeschen');
    await oeffnen('p1');
    b = await speichern('p1');
    check('… Oeffnen setzt den Zustand zurueck (kein Entfernen)', !!b && !('api_key_entfernen' in b), JSON.stringify(b));
    await oeffnen('p1');
    klick(auge);
    await sleep(40);
    check('Positivkontrolle: das Auge hat den Klartext geholt', key.value === 'sk-alt-klartext', key.value);
    key.value = '';   // Leeren per Tastatur erzeugt auch ein input – hier bewusst ohne
    b = await speichern('p1');
    check('api_key_entfernen: true', !!b && b.api_key_entfernen === true, JSON.stringify(b));

    section('4) neuer Wert = neuer Wert');
    await oeffnen('p1');
    tippe('sk-neu');
    b = await speichern('p1');
    check('api_key = sk-neu', !!b && b.api_key === 'sk-neu', b && b.api_key);
    check('kein api_key_entfernen', !!b && !('api_key_entfernen' in b), JSON.stringify(b));

    section('5) Profil ohne gespeicherten Schluessel');
    await oeffnen('p2');
    tippe('x'); tippe('');
    b = await speichern('p2');
    check('kein api_key_entfernen (nichts zu loeschen)', !!b && !('api_key_entfernen' in b), JSON.stringify(b));

    section('6) Verbindung testen');
    await oeffnen('p1');
    let t = await testen();
    check('unangefasst: profile_id gesetzt (gespeicherter Schluessel springt ein)',
        !!t && t.profile_id === 'p1', JSON.stringify(t));
    tippe('x'); tippe('');
    t = await testen();
    check('geleert: profile_id leer (kein gespeicherter Schluessel)',
        !!t && t.profile_id === '' && t.api_key === '', JSON.stringify(t));

    bilanz();
    w.close();
    process.exit(FAIL ? 1 : 0);
}

main().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); BILANZ = true; process.exit(2); });
