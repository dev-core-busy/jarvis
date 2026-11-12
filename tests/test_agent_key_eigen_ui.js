/* UI-Waechter: Agent-API-Key-Zeile – ein Auge, breites Feld, editierbar.
 *
 * VORGABE DES BETREIBERS (2026-11-12), Einstellungen -> Agent API Key:
 *   a) Feld "Name" doppelt so breit (130 -> 260 px)
 *   b) Key-Feld doppelt so breit
 *   c) das Auge INNERHALB des Key-Feldes entfernen – gesteuert wird ueber das
 *      Auge daneben
 *   d) der Key ist editierbar (eigenen Wert hinterlegen)
 *
 * URSACHE von b) und c) war DIESELBE: pwreveal.js setzt an jedes Kennwortfeld
 * ein Auge, ausser es erkennt ein handverdrahtetes (eye|auge|toggle in id oder
 * Klasse eines Geschwister-Knopfs). Der Knopf hiess nur `ak-show` – also kam ein
 * zweites Auge ins Feld, und das Feld wanderte dabei in einen <span>-Wrapper.
 * Der Wrapper ist das Flex-Kind, nicht mehr das Feld: `flex:1` wirkte nicht
 * mehr, das Feld schrumpfte auf seine Vorgabebreite.
 *
 * jsdom rechnet KEIN Layout – die Breite wird deshalb als STRUKTUR geprueft
 * (das Feld ist direktes Flex-Kind der Zeile und traegt flex:1), nicht in px.
 *
 * Lauf:  timeout 90 node tests/test_agent_key_eigen_ui.js [pfad/zu/app.js]
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
 */
'use strict';

require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const APP_PFAD = process.argv[2] || path.join(ROOT, 'frontend/js/app.js');
const read = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let okN = 0, failN = 0;
function check(name, cond, detail) {
    if (cond) okN++; else failN++;
    console.log((cond ? '  OK   ' : '  FAIL ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function abbruch(grund) { console.log('ABBRUCH: ' + grund); process.exit(2); }

const GESPEICHERT = 'gespeicherter-key-abcdef123456';
let calls = [];
let putAntwort = { status: 200, body: { ok: true } };

function j(obj, status = 200) {
    return Promise.resolve({ ok: status < 400, status,
        json: () => Promise.resolve(obj), text: () => Promise.resolve(JSON.stringify(obj)) });
}
function appFetch(url, opts) {
    const u = String(url).split('?')[0];
    const method = (opts && opts.method) || 'GET';
    let body = null;
    try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) {}
    calls.push({ url: u, method, body });
    if (u.startsWith('/api/agent/keys')) {
        if (method === 'GET') return j({ keys: [{ id: 'k1', name: 'probe', key: '', key_gesetzt: true, key_ende: '3456' }], legacy: false });
        if (method === 'PUT') return j(putAntwort.body, putAntwort.status);
        return j({ ok: true });
    }
    if (u === '/api/secret/reveal') return j({ wert: GESPEICHERT });
    if (u.startsWith('/api/settings/ldap')) return j({ access_mode: 'none' });
    if (u.startsWith('/api/settings')) return j({ docs_retention_days: 30 });
    if (u.startsWith('/api/me')) return j({ username: 'jarvis', is_admin: true, permissions: {} });
    if (u.startsWith('/api/skills')) return j({ skills: [] });
    if (u.startsWith('/api/branding')) return j({ enabled: false });
    if (u.startsWith('/api/version')) return j({ version: '0.9' });
    return j({ ok: true, items: [], skills: [], groups: [], profiles: [] });
}

(async () => {
    const dom = new JSDOM(read('frontend/settings.html'), { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    w.localStorage.setItem('jarvis_user', 'jarvis');
    w.localStorage.setItem('jarvis_sect_collapse_prof-sect-api-hdr', '0');
    w.confirm = () => true; w.alert = () => {}; w.scrollTo = () => {};
    w.WebSocket = class { constructor() { this.readyState = 0; } send() {} close() {} addEventListener() {} };
    w.fetch = appFetch;
    const sitzung = read('frontend/js/sitzung.js');
    const module = [['icons.js', read('frontend/js/icons.js')], ['i18n.js', read('frontend/js/i18n.js')],
        ['theme.js', read('frontend/js/theme.js')], ['pwreveal.js', read('frontend/js/pwreveal.js')],
        ['app.js', fs.readFileSync(APP_PFAD, 'utf8')]];
    for (const [n, code] of module) {
        w.eval(sitzung);
        try { w.eval(code); } catch (e) { console.log('    (Modul ' + n + ': ' + e.message + ')'); }
    }
    if (!w.t) w.t = (k) => k;
    // readyState steht direkt nach new JSDOM auf 'loading' – pwreveal startet
    // dann erst mit DOMContentLoaded.
    if (w.document.readyState === 'loading') {
        await new Promise((r) => w.document.addEventListener('DOMContentLoaded', r));
    }
    await sleep(30);
    const d = w.document;

    // ── Positivkontrollen: pwreveal ist aktiv, die Liste ist gerendert ───────
    console.log('\n0) Positivkontrollen');
    if (!w.JarvisPwEye) abbruch('pwreveal.js nicht geladen');
    const probe = d.createElement('div');
    probe.innerHTML = '<input type="password" class="pk-probe"><span>x</span>';
    d.body.appendChild(probe);
    await sleep(30);
    if (!probe.querySelector('.jv-pw-eye')) abbruch('pwreveal versorgt ein gewoehnliches Kennwortfeld nicht – Messung waere trivial wahr');
    check('pwreveal setzt an ein gewoehnliches Kennwortfeld ein Auge', true);
    if (typeof w._openSettingsModal !== 'function') abbruch('_openSettingsModal fehlt');
    await w._openSettingsModal();
    await sleep(150);
    const zeile = d.querySelector('#agent-keys-list [data-id="k1"]');
    if (!zeile) abbruch('Key-Zeile nicht gerendert');
    check('Key-Zeile gerendert', true);
    const key = zeile.querySelector('.ak-key');
    const name = zeile.querySelector('.ak-name');
    if (!key || !name) abbruch('Felder .ak-key/.ak-name fehlen');

    // ── a) Name doppelt so breit ────────────────────────────────────────────
    console.log('\na) Feld "Name"');
    check('Name-Feld 260 px breit', name.style.width === '260px', name.style.width);

    // ── b) + c) kein Auge im Feld, Feld bleibt Flex-Kind ────────────────────
    console.log('\nb/c) Key-Feld: ein Auge, volle Breite');
    check('kein pwreveal-Auge in der Zeile', zeile.querySelectorAll('.jv-pw-eye').length === 0,
        zeile.querySelectorAll('.jv-pw-eye').length + ' gefunden');
    check('Key-Feld nicht in einen Wrapper gepackt', key.parentElement === zeile,
        'Eltern: ' + (key.parentElement && key.parentElement.className));
    check('Key-Feld traegt flex:1 (fuellt den Rest der Zeile)', /^1/.test(key.style.flex || ''), key.style.flex);
    check('genau EIN Augen-Knopf in der Zeile', zeile.querySelectorAll('.ak-show').length === 1);

    // ── d) editierbar ───────────────────────────────────────────────────────
    console.log('\nd) Key editierbar');
    check('Key-Feld nicht schreibgeschuetzt', !key.readOnly && !key.hasAttribute('readonly'));
    check('Browser fuellt kein gespeichertes Kennwort ein', key.getAttribute('autocomplete') === 'new-password',
        key.getAttribute('autocomplete'));
    check('Hinweis zum Speichern am Feld', !!key.title && key.title !== 'app.key_edit_hint', key.title);

    const puts = () => calls.filter((c) => c.url === '/api/agent/keys/k1' && c.method === 'PUT');
    const aendern = async (wert) => {
        key.value = wert;
        key.dispatchEvent(new w.Event('change', { bubbles: true }));
        await sleep(60);
    };

    calls = [];
    await aendern('Mein-eigener_Key.2026!');
    const p1 = puts();
    check('Eingabe -> PUT mit dem Key', p1.length === 1 && p1[0].body && p1[0].body.key === 'Mein-eigener_Key.2026!',
        JSON.stringify(p1));
    check('nach dem Speichern wird die Liste neu geladen',
        calls.some((c) => c.url === '/api/agent/keys' && c.method === 'GET'));

    // Auge holt den gespeicherten Key – unveraendert verlassen speichert NICHT.
    const z2 = d.querySelector('#agent-keys-list [data-id="k1"]');
    const k2 = z2.querySelector('.ak-key');
    z2.querySelector('.ak-show').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(80);
    check('Auge zeigt den gespeicherten Key', k2.value === GESPEICHERT && k2.type === 'text',
        `value=${k2.value} type=${k2.type}`);
    calls = [];
    k2.dispatchEvent(new w.Event('change', { bubbles: true }));
    await sleep(60);
    check('unveraenderter Key wird NICHT gespeichert', puts().length === 0, puts().length + ' PUT');
    calls = [];
    k2.value = '   ';
    k2.dispatchEvent(new w.Event('change', { bubbles: true }));
    await sleep(60);
    check('leeres Feld wird NICHT gespeichert (Key bleibt)', puts().length === 0, puts().length + ' PUT');

    // Ablehnung: Grund steht an der Zeile und bleibt stehen.
    putAntwort = { status: 400, body: { ok: false, error: 'Der Key muss mindestens 16 Zeichen lang sein.' } };
    calls = [];
    k2.value = 'kurz';
    k2.dispatchEvent(new w.Event('change', { bubbles: true }));
    await sleep(80);
    const fe = z2.querySelector('.ak-fehler');
    check('Ablehnung: Grund des Servers an der Zeile', !!fe && /16 Zeichen/.test(fe.textContent),
        fe ? fe.textContent : 'kein .ak-fehler');
    check('Ablehnung: Liste wird NICHT neu geladen (Eingabe bleibt sichtbar)',
        !calls.some((c) => c.url === '/api/agent/keys' && c.method === 'GET') && k2.value === 'kurz');
    await sleep(300);
    check('Fehler verschwindet nicht von selbst', !!fe && fe.textContent.length > 0);

    // Kopieren nach abgelehnter Eingabe liefert den GESPEICHERTEN Key.
    let kopiert = null;
    Object.defineProperty(w.navigator, 'clipboard', { value: { writeText: (s) => { kopiert = s; return Promise.resolve(); } }, configurable: true });
    z2.querySelector('.ak-copy').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    await sleep(60);
    check('Kopieren liefert den gespeicherten Key, nicht die Eingabe', kopiert === GESPEICHERT, String(kopiert));

    // i18n: neue Schluessel in DE und EN
    console.log('\ni18n');
    const I18N = read('frontend/js/i18n.js');
    for (const k of ['app.key_edit_hint', 'app.key_save_error']) {
        const n = (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length;
        check(`${k} in DE und EN`, n === 2, n + 'x');
    }

    console.log(`\nErgebnis: ${okN} OK, ${failN} FAIL`);
    w.close();
    process.exit(failN === 0 ? 0 : 1);
})().catch((e) => { console.error(e); process.exit(2); });
