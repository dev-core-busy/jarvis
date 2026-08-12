/* UI-Test: Agent-API-Keys bleiben nicht auf „Laedt…" stehen
 * (jsdom, echte settings.html / app.js / i18n.js).
 *
 * DER GEMELDETE FALL (ECHT, 2026-08-12): Unter *Einstellungen -> KI & System ->
 * Agent-API-Keys* stand dauerhaft „Laedt…", obwohl ein Key 'kundenverwaltung'
 * hinterlegt war.
 *
 * Ursache: die Liste wurde AUSSCHLIESSLICH im Klick-Handler der Abschnitts-
 * Kopfzeile geladen (`hdr.addEventListener('click', ...)`). `_collapseInit`
 * stellt aber den gemerkten Auf/Zu-Zustand aus localStorage wieder her – wer den
 * Abschnitt einmal aufgeklappt hat, findet ihn beim naechsten Oeffnen BEREITS
 * offen und klickt die Kopfzeile nie an. Der Abruf lief also nie.
 * Dieselbe Falle wie bei den Update-Knoepfen (2026-07-28) und der Rollen-Liste
 * (2026-08-10); beide Male stand danach eine Warnung in app.js.
 *
 * DESHALB TREIBT DIESER TEST NICHT DAS MODUL, SONDERN DIE SEITE: geprueft wird
 * ueber das echte `_openSettingsModal()` bei gemerkt AUFGEKLAPPTEM Abschnitt.
 * Ein Test, der `loadOnce()` direkt aufruft oder die Kopfzeile anklickt, ist
 * gruen – und faende den Fehler nicht.
 *
 * WICHTIG (Fallstrick 2026-07-30): am Ende window.close() + process.exit(),
 * sonst halten die Poll-Timer aus app.js den Node-Prozess fuer immer offen.
 *
 * Lauf:  timeout 90 node tests/test_agent_keys_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + name
        + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
const read = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');

// Der Bestand wie auf ECHT: genau ein benannter Key.
const KEYS = [{ id: 'k1', name: 'kundenverwaltung', key: 'geheim-abc-123' }];

let calls = [];

function j(obj, ok = true, status = 200) {
    return Promise.resolve({
        ok, status,
        json: () => Promise.resolve(obj),
        text: () => Promise.resolve(JSON.stringify(obj)),
    });
}

function appFetch(url, opts) {
    const u = String(url);
    const method = (opts && opts.method) || 'GET';
    let body = null;
    try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) {}
    calls.push({ url: u, method, body });

    if (u.startsWith('/api/agent/keys')) {
        if (method === 'GET') return j({ keys: KEYS, legacy: false });
        return j({ ok: true, keys: KEYS });
    }
    if (u.startsWith('/api/settings/ldap')) return j({ access_mode: 'none' });
    if (u.startsWith('/api/settings')) return j({ docs_retention_days: 30 });
    if (u.startsWith('/api/me')) return j({ username: 'jarvis', is_admin: true, permissions: {} });
    if (u.startsWith('/api/skills')) return j({ skills: [] });
    if (u.startsWith('/api/branding')) return j({ enabled: false });
    if (u.startsWith('/api/version')) return j({ version: '0.9' });
    return j({ ok: true, items: [], skills: [], groups: [], profiles: [] });
}

function makeDom({ apiOffen }) {
    const dom = new JSDOM(HTML, { runScripts: 'outside-only', url: 'https://localhost/settings' });
    const { window } = dom;
    window.localStorage.setItem('jarvis_token', 'tok');
    window.localStorage.setItem('jarvis_user', 'jarvis');
    // GENAU DAS ist der gemeldete Zustand: der Abschnitt ist gemerkt AUFGEKLAPPT
    // ('0' = nicht eingeklappt), es fallt also kein Klick auf die Kopfzeile.
    if (apiOffen !== null) {
        window.localStorage.setItem('jarvis_sect_collapse_prof-sect-api-hdr',
            apiOffen ? '0' : '1');
    }
    window.confirm = () => true;
    window.alert = () => {};
    window.scrollTo = () => {};
    window.WebSocket = class { constructor() { this.readyState = 0; } send() {} close() {} addEventListener() {} };
    return dom;
}

async function ladeApp(dom) {
    const w = dom.window;
    // FALLSTRICK: fetch MUSS vor dem eval stehen – app.js laeuft als IIFE sofort
    // und ruft fetch; ist es undefined, bricht die Funktion ab, bevor sie
    // window._openSettingsModal setzt.
    w.fetch = appFetch;
    for (const f of ['frontend/js/i18n.js', 'frontend/js/theme.js', 'frontend/js/app.js']) {
        try { w.eval(read(f)); } catch (e) { console.log('    (Modul ' + f + ': ' + e.message + ')'); }
    }
    if (!w.t) w.t = (k) => k;
    await sleep(30);
    return w;
}

(async () => {
    section('1) Markup und Verdrahtung');
    const dom0 = makeDom({ apiOffen: null });
    const d0 = dom0.window.document;
    check('Liste #agent-keys-list vorhanden', !!d0.getElementById('agent-keys-list'));
    check('Kopfzeile #prof-sect-api-hdr vorhanden', !!d0.getElementById('prof-sect-api-hdr'));
    check('Platzhalter „Laedt…" steht im HTML',
        /Lädt…/.test(d0.getElementById('agent-keys-list').innerHTML));
    check('app.js stellt window.agentKeysOnShow bereit',
        /window\.agentKeysOnShow\s*=/.test(APP));
    check('onShow wird im Modal-Oeffner gerufen',
        (APP.match(/if \(window\.agentKeysOnShow\) window\.agentKeysOnShow\(\);/g) || []).length >= 2,
        'erwartet: Modal-Oeffner UND Reiter-Klick');
    check('Klick-Hook auf der Kopfzeile bleibt erhalten',
        /hdr\.addEventListener\('click', \(\) => setTimeout\(loadOnce, 50\)\)/.test(APP));
    dom0.window.close();

    // ══════════════════════════════════════════════════════════════════════
    section('2) DER GEMELDETE FALL: Abschnitt gemerkt AUFGEKLAPPT, kein Klick');
    // ══════════════════════════════════════════════════════════════════════
    const dom1 = makeDom({ apiOffen: true });
    const w1 = await ladeApp(dom1);
    const d1 = w1.document;
    check('Modal-Oeffner erreichbar', typeof w1._openSettingsModal === 'function');

    calls = [];
    await w1._openSettingsModal();
    await sleep(120);

    const body1 = d1.getElementById('prof-sect-api-body');
    check('Abschnitt ist tatsaechlich offen', body1 && body1.style.display !== 'none',
        body1 ? `display=[${body1.style.display}]` : '—');
    const abrufe = calls.filter(c => c.url.startsWith('/api/agent/keys') && c.method === 'GET');
    check('GET /api/agent/keys wurde OHNE Klick ausgefuehrt', abrufe.length === 1,
        `${abrufe.length} Abrufe`);

    const liste1 = d1.getElementById('agent-keys-list');
    check('„Laedt…" ist verschwunden', !/Lädt…/.test(liste1.innerHTML), liste1.textContent.trim());
    check('der Key „kundenverwaltung" wird angezeigt',
        liste1.innerHTML.includes('kundenverwaltung'));
    check('Key-Feld ist zunaechst verdeckt (type=password)',
        !!liste1.querySelector('.ak-key[type=password]'));
    check('Zeile traegt die Kennung', !!liste1.querySelector('[data-id="k1"]'));
    check('Knoepfe Anzeigen/Kopieren/Neu/Loeschen vorhanden',
        !!(liste1.querySelector('.ak-show') && liste1.querySelector('.ak-copy')
           && liste1.querySelector('.ak-regen') && liste1.querySelector('.ak-del')));

    section('3) Kein doppelter Abruf beim zweiten Oeffnen');
    calls = [];
    await w1._openSettingsModal();
    await sleep(80);
    check('kein zweiter GET (loadOnce ist idempotent)',
        calls.filter(c => c.url.startsWith('/api/agent/keys') && c.method === 'GET').length === 0);
    w1.window ? null : null;
    dom1.window.close();

    // ══════════════════════════════════════════════════════════════════════
    section('4) Zugeklappter Abschnitt: kein Abruf, aber der Klick laedt');
    // ══════════════════════════════════════════════════════════════════════
    const dom2 = makeDom({ apiOffen: false });
    const w2 = await ladeApp(dom2);
    const d2 = w2.document;
    calls = [];
    await w2._openSettingsModal();
    await sleep(120);
    const body2 = d2.getElementById('prof-sect-api-body');
    check('Abschnitt ist zu', body2 && body2.style.display === 'none',
        body2 ? `display=[${body2.style.display}]` : '—');
    check('kein Abruf fuer einen unsichtbaren Abschnitt',
        calls.filter(c => c.url.startsWith('/api/agent/keys')).length === 0);

    // Aufklappen per Klick – der alte Weg muss weiter funktionieren
    d2.getElementById('prof-sect-api-hdr')
        .dispatchEvent(new w2.MouseEvent('click', { bubbles: true }));
    await sleep(150);
    check('nach dem Klick ist der Abschnitt offen',
        d2.getElementById('prof-sect-api-body').style.display !== 'none');
    check('Klick loest den Abruf aus',
        calls.filter(c => c.url.startsWith('/api/agent/keys') && c.method === 'GET').length === 1);
    check('der Key erscheint auch auf diesem Weg',
        d2.getElementById('agent-keys-list').innerHTML.includes('kundenverwaltung'));
    dom2.window.close();

    // ══════════════════════════════════════════════════════════════════════
    section('5) Leerer Bestand und Ladefehler sagen es AUSDRUECKLICH');
    // ══════════════════════════════════════════════════════════════════════
    // Ein Abschnitt, der bei 0 Keys oder bei einem Fehler weiter „Laedt…" zeigt,
    // ist von „haengt" nicht zu unterscheiden – genau das war das Problem.
    const dom3 = makeDom({ apiOffen: true });
    const w3 = dom3.window;
    w3.fetch = (url, opts) => {
        if (String(url).startsWith('/api/agent/keys')) return j({ keys: [] });
        return appFetch(url, opts);
    };
    for (const f of ['frontend/js/i18n.js', 'frontend/js/theme.js', 'frontend/js/app.js']) {
        try { w3.eval(read(f)); } catch (e) {}
    }
    if (!w3.t) w3.t = (k) => k;
    await sleep(30);
    await w3._openSettingsModal();
    await sleep(120);
    const l3 = w3.document.getElementById('agent-keys-list');
    check('leerer Bestand: „Laedt…" weg', !/Lädt…/.test(l3.innerHTML), l3.textContent.trim());
    check('leerer Bestand: Hinweistext steht da', l3.textContent.trim().length > 0);
    dom3.window.close();

    const dom4 = makeDom({ apiOffen: true });
    const w4 = dom4.window;
    w4.fetch = (url, opts) => {
        if (String(url).startsWith('/api/agent/keys')) return Promise.reject(new Error('Netz weg'));
        return appFetch(url, opts);
    };
    for (const f of ['frontend/js/i18n.js', 'frontend/js/theme.js', 'frontend/js/app.js']) {
        try { w4.eval(read(f)); } catch (e) {}
    }
    if (!w4.t) w4.t = (k) => k;
    await sleep(30);
    await w4._openSettingsModal();
    await sleep(120);
    const l4 = w4.document.getElementById('agent-keys-list');
    check('Ladefehler: „Laedt…" weg', !/Lädt…/.test(l4.innerHTML), l4.textContent.trim());
    check('Ladefehler: Fehlerfarbe gesetzt', /--danger/.test(l4.innerHTML));
    dom4.window.close();

    // ── Ergebnis ────────────────────────────────────────────────────────────
    const ok = results.filter(r => r.ok).length;
    const bad = results.length - ok;
    console.log(`\n${ok} ok, ${bad} Fehler (${results.length} Pruefungen)`);
    process.exit(bad === 0 ? 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });
