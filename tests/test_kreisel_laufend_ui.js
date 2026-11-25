#!/usr/bin/env node
/* Waechter (2026-11-25): laufender Vorgang = drehender Kreis.
 *
 * Vereinbarung, zuletzt eingefordert 2026-11-25 ("wir hatten vereinbart, dass bei
 * sowas 'Die Prüfung läuft gerade …' der überall verwendete drehende Kreis ist"):
 * jede Laufmeldung traegt `.jv-pkg-spin` (theme.css) davor – kein Statuspunkt,
 * kein Sanduhr-Emoji, nicht nur Text. Die Stellen im Container "Paket-Updates und
 * Integritaet" misst tests/test_paket_updates_ui.js (4c); hier die vier weiteren:
 *
 *   A  LLM-Profil "Verbindung testen" (app.js): Knopf UND Ergebniskasten
 *   B  Anmeldedienst "Verbindung testen" (settings_idp.js)
 *   C  Wissens-Verdichtung (knowledge.js): Knopf UND Statuszeile, auch der Knopf,
 *      den die Ansicht bei bereits laufender Verdichtung zeichnet
 *   D  Wissens-Synchronisation (knowledge_sync.js): Pille "läuft" – und NUR dort
 *   E  Texte: kein Sanduhr-Emoji mehr in diesen Schluesseln (DE/EN/FR)
 *
 * Gemessen WAEHREND des Vorgangs: der Abruf antwortet nie.
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/seite_ausschnitt')
    .mitReitern(require('./lib/jsdom_laden')(), ['settings-tab-profiles']);

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
// Gegenprobe (tests/gegen_kreisel_laufend.py) schiebt sabotierte KOPIEN unter
const quelle = (name, p) => process.env['JARVIS_PRUEFLING_' + name]
    ? fs.readFileSync(process.env['JARVIS_PRUEFLING_' + name], 'utf8') : lies(p);
const APP = quelle('APP', 'frontend/js/app.js');
const IDP = quelle('IDP', 'frontend/js/settings_idp.js');
const KNOW = quelle('KNOW', 'frontend/js/knowledge.js');
const SYNC = quelle('SYNC', 'frontend/js/knowledge_sync.js');
const I18N = quelle('I18N', 'frontend/js/i18n.js');
const I18N_FR = quelle('I18N_FR', 'frontend/js/i18n_fr.js');
const SITZUNG = lies('frontend/js/sitzung.js');
const ICONS = lies('frontend/js/icons.js');

let OK = 0, FAIL = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) OK++; else FAIL++;
    console.log((cond ? '  ✓ ' : '  ✗ ') + name + (!cond && detail !== undefined ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }
function bilanz() { BILANZ = true; console.log('\nErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL'); }
function abbruch(t) { console.log('ABBRUCH: ' + t); bilanz(); process.exit(2); }
process.on('exit', (code) => {
    if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; }
});
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hatKreis = (el) => !!(el && el.querySelector('.jv-pkg-spin'));
const kurz = (el) => (el ? el.innerHTML : '(fehlt)').slice(0, 140);

function j(obj) {
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(obj), text: () => Promise.resolve(JSON.stringify(obj)) });
}

async function teilA() {
    section('A) LLM-Profil: Verbindung testen (app.js)');
    const PROFILE = [{ id: 'p1', name: 'P', provider: 'openai', model: 'm1', api_url: 'https://api.beispiel.de/v1',
                       api_key: 'sk-…***', auth_method: 'api_key', session_key: '' }];
    const dom = new JSDOM(lies('frontend/settings.html'), { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    w.localStorage.setItem('jarvis_user', 'jarvis');
    w.confirm = () => true; w.alert = () => {}; w.scrollTo = () => {};
    w.WebSocket = class { constructor() { this.readyState = 0; } send() {} close() {} addEventListener() {} };
    w.fetch = (url) => {
        const u = String(url).split('?')[0];
        if (u === '/api/profiles/test') return new Promise(() => {});   // haengt: Zustand WAEHREND des Tests
        if (u === '/api/settings') return j({ profiles: PROFILE, active_profile_id: 'p1', defaults: {} });
        if (u.startsWith('/api/settings/ldap')) return j({ access_mode: 'none' });
        if (u.startsWith('/api/me')) return j({ username: 'jarvis', is_admin: true, permissions: {} });
        if (u.startsWith('/api/skills')) return j({ skills: [] });
        if (u.startsWith('/api/branding')) return j({ enabled: false });
        return j({ ok: true, items: [], skills: [], groups: [], profiles: [] });
    };
    for (const src of [ICONS, I18N, lies('frontend/js/theme.js'), APP]) {
        w.eval(SITZUNG);
        try { w.eval(src); } catch (e) { console.log('    (Modul: ' + e.message + ')'); }
    }
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    await sleep(30);
    if (typeof w._openSettingsModal !== 'function') abbruch('A: Einstellungen nicht zu oeffnen');
    await w._openSettingsModal();
    await sleep(150);
    const d = w.document;
    const edit = d.querySelector('#profiles-container .btn-edit-profile[data-id="p1"]');
    const btn = d.getElementById('btn-test-profile'), erg = d.getElementById('profile-test-result');
    if (!edit || !btn || !erg) abbruch('A: Profil-Formular nicht gezeichnet (Positivkontrolle)');
    edit.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(40);
    btn.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(40);
    check('A: Test laeuft (Knopf gesperrt) – Positivkontrolle', btn.disabled === true);
    check('A: Knopf zeigt den drehenden Kreis vor "Teste…"', hatKreis(btn) && /Teste/.test(btn.textContent), kurz(btn));
    check('A: Ergebniskasten zeigt den Kreis vor "Verbindung wird geprüft"',
          hatKreis(erg) && /Verbindung wird geprüft/.test(erg.textContent), kurz(erg));
    check('A: kein Sanduhr-Emoji im Ergebniskasten', !/⏳/.test(erg.textContent), erg.textContent);
    w.close();
}

async function teilB() {
    section('B) Anmeldedienst: Verbindung testen (settings_idp.js)');
    const dom = new JSDOM('<!doctype html><body><button id="idp-testen"></button><div id="idp-msg"></div></body>',
                          { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    let gerufen = false;
    w.fetch = (url) => { if (String(url).indexOf('/api/admin/oidc/test') === 0) gerufen = true; return new Promise(() => {}); };
    w.eval(SITZUNG); w.eval(I18N); w.eval(IDP);
    // readyState steht in jsdom auf 'loading' – das Modul verdrahtet erst hier
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    w.document.getElementById('idp-testen').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(30);
    const m = w.document.getElementById('idp-msg');
    if (!gerufen) abbruch('B: der Klick hat den Test nicht ausgeloest (Positivkontrolle)');
    check('B: Meldung zeigt den drehenden Kreis vor "Verbindung wird geprüft"',
          hatKreis(m) && /Verbindung wird geprüft/.test(m.textContent), kurz(m));
    check('B: der Text bleibt Text (kein Markup aus der Uebersetzung)', m.children.length === 1, kurz(m));
    w.close();
}

async function teilC() {
    section('C) Wissens-Verdichtung (knowledge.js)');
    const dom = new JSDOM(`<!doctype html><body><div id="kb-stats-container"></div><div id="kb-folder-list"></div>
        <div id="kb-mount-list"></div><div id="kb-cleanup-body"></div>
        <button id="kb-compact-btn">Verdichten</button><div id="kb-compact-status" style="display:none"></div></body>`,
                          { runScripts: 'outside-only', url: 'https://host/settings' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    w.fetch = () => new Promise(() => {});
    w.JarvisDL = { url: (u) => u };
    w.eval(SITZUNG); w.eval(I18N); w.eval(ICONS); w.eval(KNOW);
    const km = w.knowledgeManager;
    if (!km || typeof km.compactLearned !== 'function') abbruch('C: knowledgeManager.compactLearned fehlt');
    const btn = w.document.getElementById('kb-compact-btn'), st = w.document.getElementById('kb-compact-status');
    km.compactLearned(btn);
    await sleep(20);
    check('C: Verdichtung laeuft (Knopf gesperrt) – Positivkontrolle', btn.disabled === true);
    check('C: Knopf zeigt den Kreis vor "Verdichtung läuft"', hatKreis(btn) && /Verdichtung läuft/.test(btn.textContent), kurz(btn));
    check('C: Statuszeile zeigt den Kreis vor dem Hinweis', hatKreis(st) && /verdichtet/.test(st.textContent), kurz(st));
    check('C: kein Sanduhr-Emoji', !/⏳/.test(btn.textContent + st.textContent));
    // Fehler danach: der Kreis muss weg sein (er sagt "laeuft")
    km._compactStatusLine('Fehler', 'var(--danger)');
    check('C: eine spaetere Meldung ohne laeuft traegt KEINEN Kreis', !hatKreis(st), kurz(st));
    // Die Ansicht zeichnet den Knopf bei bereits laufender Verdichtung selbst
    const quelleKnopf = /\$\{cs\.running \? '<span class="jv-pkg-spin" aria-hidden="true"><\/span>' \+ window\.t\('knowledge\.compact\.running'\)/;
    check('C: gezeichneter Knopf bei laufender Verdichtung traegt den Kreis (Quelle)', quelleKnopf.test(KNOW));
    w.close();
}

function teilD() {
    section('D) Wissens-Synchronisation: Pille (knowledge_sync.js)');
    const dom = new JSDOM('<!doctype html><body></body>', { runScripts: 'outside-only', url: 'https://host/settings' });
    const w = dom.window;
    w.fetch = () => new Promise(() => {});
    w.eval(SITZUNG); w.eval(I18N); w.eval(ICONS);
    try { w.eval(lies('frontend/js/tabfill.js')); } catch (e) { /* nicht noetig fuer _zeile */ }
    w.eval(SYNC);
    const KS = w.KnowledgeSync;
    if (!KS || typeof KS._zeile !== 'function') abbruch('D: KnowledgeSync._zeile fehlt');
    const pille = (p) => {
        const box = w.document.createElement('div');
        box.innerHTML = KS._zeile(p);
        return box.querySelector('.kbsync-pill');
    };
    const basis = { id: 'x', name: 'Standort', url: 'https://beispiel.de', state: 'active', auto: false, last_sync: {} };
    const lauf = pille(Object.assign({}, basis, { running: true, progress: { phase: 'download', done: 1, total: 3 } }));
    const ruhe = pille(Object.assign({}, basis, { running: false }));
    if (!lauf || !ruhe) abbruch('D: Pille nicht gezeichnet (Positivkontrolle)');
    check('D: Pille "läuft" mit drehendem Kreis', hatKreis(lauf) && /läuft/.test(lauf.textContent), kurz(lauf));
    check('D: Pille "aktiv" (nichts laeuft) OHNE Kreis', !hatKreis(ruhe), kurz(ruhe));
    const css = lies('frontend/css/style.css');
    check('D: Kreis in der Pille hat eine eigene, kleinere Groesse', /\.kbsync-pill \.jv-pkg-spin\s*\{[^}]*width:\s*10px/.test(css));
    w.close();
}

function teilE() {
    section('E) Texte ohne Sanduhr-Emoji');
    const dom = new JSDOM('<!doctype html><body></body>', { runScripts: 'outside-only', url: 'https://host/' });
    const w = dom.window;
    // EIN eval: das const _I18N aus i18n.js ist sonst fuer i18n_fr.js nicht sichtbar
    w.eval(I18N + '\n;' + I18N_FR + '\n;window.__I18N = _I18N;');
    const SCHL = ['knowledge.compact.running', 'knowledge.compact.status_running', 'profile.testing',
                  'common.testing', 'security.idp_test_laeuft'];
    const funde = [];
    for (const sp of ['de', 'en', 'fr']) {
        const tab = (w.__I18N || {})[sp] || {};
        if (!Object.keys(tab).length) abbruch('E: Woerterbuch ' + sp + ' nicht geladen');
        for (const k of SCHL) if (/⏳/.test(tab[k] || '')) funde.push(sp + ':' + k);
    }
    check('E: keiner der Laufmeldungs-Texte traegt ⏳ (der Kreis steht davor)', !funde.length, funde.join(', '));
    w.close();
}

(async () => {
    const theme = lies('frontend/css/theme.css');
    if (!/\.jv-pkg-spin\s*\{[^}]*animation:\s*jv-pkg-spin/.test(theme)) abbruch('.jv-pkg-spin fehlt in theme.css');
    check('Positivkontrolle: .jv-pkg-spin dreht und steht in theme.css (jede Seite)', true);
    await teilA();
    await teilB();
    await teilC();
    teilD();
    teilE();
    bilanz();
    process.exit(FAIL ? 1 : 0);
})().catch((e) => abbruch('Absturz: ' + (e && e.stack || e)));
