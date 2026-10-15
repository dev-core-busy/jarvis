/* Waechter: /wissen laedt nach einer Sitzung neu, statt die Inhalte des
 * Vorgaengers stehen zu lassen (Code-Review 2026-10-07).
 *
 * Befund: "Abmelden" zeigte nur die Anmeldemaske. Destillat-Ergebnis,
 * einmal gezeichnete Gruppen-Kaestchen, Confluence-Baum und Listen blieben im
 * Speicher; meldete sich danach jemand anderes im selben Tab an, sah er das
 * alles, und das Destillat bot die Gruppen des Vorgaengers als Ziel an.
 *
 * Gemessen an der ECHTEN wissen.html mit der ECHTEN wissen.js. jsdom kann
 * nicht neu laden – es MELDET den Versuch als jsdomError ("navigation").
 * Genau das wird gezaehlt:
 *   1. ohne geladene Sitzung: Abmelden zeigt die Maske, KEIN Neuladen
 *      (Positivkontrolle: die Zaehlung sieht nicht jedes Abmelden als Neuladen)
 *   2. nach geladener Sitzung: Abmelden -> Neuladen, Token weg
 *   3. Sitzung abgelaufen (Maske), neue Anmeldung -> Neuladen statt
 *      loadScope in die alte Seite
 *
 *   node tests/test_wissen_abmelden_ui.js
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
let ok = 0, fail = 0, BILANZ = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function section(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
const schlaf = (ms) => new Promise(r => setTimeout(r, ms));
const WACH = setTimeout(() => { console.log('ABBRUCH: Lauf haengt'); process.exit(2); }, 30000);
process.on('exit', (c) => { if (!BILANZ && c === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 2; } });

const HTML = lies('frontend/wissen.html');

async function seite(opt) {
    const neuladen = [];
    const vc = new VirtualConsole();
    vc.on('jsdomError', (e) => {
        if (/navigation/i.test(String(e && e.message))) neuladen.push(String(e.message));
    });
    const dom = new JSDOM(HTML, { url: 'https://localhost/wissen', runScripts: 'outside-only',
                                  virtualConsole: vc });
    const win = dom.window;
    if (opt.token) win.localStorage.setItem('jarvis_token', opt.token);
    const zustand = { scope401: !!opt.scope401 };
    win.fetch = function (url, init) {
        const p = String(url).split('?')[0];
        const j = (d, st) => Promise.resolve({ ok: (st || 200) < 300, status: st || 200,
                                               json: () => Promise.resolve(d) });
        if (p === '/api/wissen/scope') {
            if (zustand.scope401) return j({ error: 'abgelaufen' }, 401);
            return j({ ok: true, user: 'anna', is_editor: false,
                       groups: [{ id: 'g1', name: 'Vertrieb', color: '#888', folders: ['data/rag/x'] }],
                       folders: [{ path: 'data/rag/x', name: 'x', root: 'data/rag/x', depth: 0 }] });
        }
        if (p === '/api/login') return j({ success: true, token: 'NEU', username: 'bert' });
        if (p === '/api/wissen/files') return j({ ok: true, files: [] });
        return j({ ok: true, pending: [], spaces: [], bereiche: [] });
    };
    win.alert = () => {};
    win.eval(lies('frontend/js/sitzung.js'));
    win.eval(lies('frontend/js/icons.js'));
    win.eval(lies('frontend/js/i18n.js'));
    win.eval(lies('frontend/js/wissen.js'));
    if (win.document.readyState === 'loading') {
        await new Promise(r => win.document.addEventListener('DOMContentLoaded', r, { once: true }));
    } else {
        win.document.dispatchEvent(new win.Event('DOMContentLoaded', { bubbles: true }));
    }
    await schlaf(80);
    return { win, doc: win.document, neuladen, zustand };
}
const sichtbar = (el) => !!el && !el.classList.contains('hidden');

(async () => {
section('1. Ohne geladene Sitzung: Abmelden zeigt die Maske, kein Neuladen');
{
    const s = await seite({ token: '', scope401: true });
    check('Positivkontrolle: die Anmeldemaske steht', sichtbar(s.doc.getElementById('wi-login')));
    s.doc.getElementById('wi-logout').click();
    await schlaf(20);
    check('Positivkontrolle: KEIN Neuladen ohne vorherige Sitzung', s.neuladen.length === 0,
          s.neuladen.join(' | '));
    s.win.close();
}

section('2. Nach einer Sitzung: Abmelden laedt die Seite neu');
{
    const s = await seite({ token: 'ALT' });
    check('Positivkontrolle: die Sitzung ist geladen (App sichtbar)', sichtbar(s.doc.getElementById('wi-app')));
    s.doc.getElementById('wi-logout').click();
    await schlaf(20);
    check('⚠ Abmelden -> Neuladen (Inhalte des Vorgaengers weg)', s.neuladen.length === 1,
          String(s.neuladen.length));
    check('… und das Token ist weg', !s.win.localStorage.getItem('jarvis_token'));
    s.win.close();
}

section('3. Sitzung abgelaufen, neue Anmeldung im selben Tab: Neuladen');
{
    const s = await seite({ token: 'ALT' });
    check('Positivkontrolle: Sitzung geladen', sichtbar(s.doc.getElementById('wi-app')));
    // Ablauf: der naechste Scope-Abruf antwortet 401 -> Maske
    s.zustand.scope401 = true;
    s.doc.getElementById('wi-user').value = 'bert';
    s.doc.getElementById('wi-pass').value = 'pw';
    s.doc.getElementById('wi-login-btn').click();
    await schlaf(40);
    check('⚠ neue Anmeldung nach einer Sitzung -> Neuladen', s.neuladen.length === 1,
          String(s.neuladen.length));
    check('… mit dem NEUEN Token im Speicher', s.win.localStorage.getItem('jarvis_token') === 'NEU');
    s.win.close();
}

clearTimeout(WACH);
BILANZ = true;
console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
