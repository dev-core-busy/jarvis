#!/usr/bin/env node
/**
 * Waechter: Einstellungen -> Sicherheit -> Zwei-Faktor-Anmeldung zuruecksetzen.
 *
 *  A  EINBINDUNG: settings.html traegt #sec-totp-list und laedt totp_admin.js,
 *     app.js ruft TotpAdmin.onShow() im Zweig des Sicherheits-Reiters (am
 *     Syntaxbaum: der Aufruf steht im Block, dessen Bedingung 'security' prueft).
 *     Register: ein Modul, das in keinem <script> steht, faellt still aus.
 *  B  VERHALTEN in jsdom mit fetch-Attrappe (nach PFAD geroutet):
 *     Liste, Kontonamen als TEXT (kein Markup), eigenes Konto ohne Knopf,
 *     Bestaetigung mit Kennwortfeld, leeres Kennwort schickt nichts, Erfolg
 *     laedt neu, Fehler BLEIBT stehen, Kennwort wird nach jedem Versuch geleert.
 *  C  TEXTE: jeder im Modul benutzte security.totp_*-Schluessel in DE und EN.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs'), path = require('path');
const REPO = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');
let acorn = null;
for (const p of ['acorn', '/usr/share/nodejs/acorn', path.join(REPO, 'node_modules/acorn'),
                 path.join(REPO, 'data/node_modules/acorn'), '/tmp/node_modules/acorn']) {
    try { acorn = require(p); break; } catch (e) { /* weiter */ }
}
if (!acorn) { console.log('ABBRUCH (Exit 2): acorn nicht gefunden'); process.exit(2); }

let ok = 0, fail = 0, bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });

const MODUL = fs.readFileSync(path.join(REPO, 'frontend/js/totp_admin.js'), 'utf8');
const SETTINGS = fs.readFileSync(path.join(REPO, 'frontend/settings.html'), 'utf8');
const APP = fs.readFileSync(path.join(REPO, 'frontend/js/app.js'), 'utf8');
const I18N = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');

// ── A: Einbindung ───────────────────────────────────────────────────────────
console.log('A  Einbindung');
check('settings.html hat #sec-totp-list', /id="sec-totp-list"/.test(SETTINGS));
check('settings.html laedt totp_admin.js', /<script src="\/static\/js\/totp_admin\.js\?v=\d+"><\/script>/.test(SETTINGS));

function aufrufImSicherheitsZweig(quelle) {
    const ast = acorn.parse(quelle, { ecmaVersion: 'latest', sourceType: 'script' });
    let gefunden = 0;
    const istSecurityTest = (t) => t && t.type === 'LogicalExpression'
        ? istSecurityTest(t.left) || istSecurityTest(t.right)
        : !!(t && t.type === 'BinaryExpression' && /===?/.test(t.operator)
             && [t.left, t.right].some(x => x.type === 'Literal' && x.value === 'security'));
    const ruftOnShow = (n) => {
        let ja = false;
        (function lauf(k) {
            if (!k || typeof k.type !== 'string') return;
            if (k.type === 'CallExpression' && k.callee.type === 'MemberExpression'
                && k.callee.property.name === 'onShow' && k.callee.object.type === 'MemberExpression'
                && k.callee.object.property.name === 'TotpAdmin') ja = true;
            for (const key of Object.keys(k)) {
                const v = k[key];
                if (Array.isArray(v)) v.forEach(lauf); else if (v && typeof v.type === 'string') lauf(v);
            }
        })(n);
        return ja;
    };
    (function lauf(n) {
        if (!n || typeof n.type !== 'string') return;
        if (n.type === 'IfStatement' && istSecurityTest(n.test) && ruftOnShow(n.consequent)) gefunden++;
        for (const k of Object.keys(n)) {
            const v = n[k];
            if (Array.isArray(v)) v.forEach(lauf); else if (v && typeof v.type === 'string') lauf(v);
        }
    })(ast);
    return gefunden;
}
// Positivkontrolle der Sonde: erkennt den Fall, uebersieht einen falschen Zweig
const sondeJa = aufrufImSicherheitsZweig("if (target === 'security' && x) { if (window.TotpAdmin) window.TotpAdmin.onShow(); }");
const sondeNein = aufrufImSicherheitsZweig("if (target === 'cron') { window.TotpAdmin.onShow(); }");
check('(Sonde) erkennt Aufruf im security-Zweig, nicht im cron-Zweig', sondeJa === 1 && sondeNein === 0, sondeJa + '/' + sondeNein);
check('app.js ruft TotpAdmin.onShow() im Sicherheits-Reiter', aufrufImSicherheitsZweig(APP) >= 1);

// ── C: Texte ────────────────────────────────────────────────────────────────
console.log('\nC  Texte DE/EN');
const schluessel = new Set();
for (const m of MODUL.matchAll(/T\('(security\.totp_[a-z_]+)'/g)) schluessel.add(m[1]);
for (const m of SETTINGS.matchAll(/data-i18n="(security\.totp_[a-z_]+)"/g)) schluessel.add(m[1]);
check('Schluessel gefunden (> 8)', schluessel.size > 8, String(schluessel.size));
const fehlt = [...schluessel].filter(k => (I18N.match(new RegExp("\\n\\s*'" + k.replace('.', '\\.') + "':", 'g')) || []).length !== 2);
check('jeder Schluessel in DE und EN', fehlt.length === 0, fehlt.join(', '));

// ── B: Verhalten ────────────────────────────────────────────────────────────
function umgebung(antwortReset) {
    const dom = new JSDOM('<!doctype html><body><div id="sec-totp-list"></div></body>',
                          { runScripts: 'outside-only', url: 'https://jarvis.test/settings' });
    const w = dom.window;
    const z = { aufrufe: [], users: [
        { user: 'jarvis', display: 'jarvis', self: true },
        { user: 'FIRMA\\m.muster', display: 'FIRMA\\m.muster', self: false },
        { user: '<img src=x onerror="window.__xss=1">', display: '<img src=x onerror="window.__xss=1">', self: false },
    ], reset: antwortReset || { status: 200, body: { ok: true } } };
    /* Das ECHTE sitzung.js statt `{ token: () => … }`. Eine Attrappe bietet
       WENIGER als das Original und prueft damit die eigene Annahme - genau
       daran sind am 2026-10-05 acht Waechter still gestorben (Begruendung in
       lib/sitzung_laden.js). Der Helfer WIRFT, wenn danach kein benutzbares
       window.JarvisSitzung steht. */
    sitzungLaden(w, { token: 'TOK' });
    w.fetch = (url, init) => {
        const pfad = String(url).split('?')[0];
        z.aufrufe.push({ pfad, init: init || {} });
        let a;
        if (pfad === '/api/admin/totp/users') a = { status: 200, body: { ok: true, users: z.users } };
        else if (pfad === '/api/admin/totp/reset') a = z.reset;
        else a = { status: 404, body: {} };
        return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
    };
    w.eval(MODUL);
    return { w, z, d: w.document };
}
const warte = (ms) => new Promise(r => setTimeout(r, ms || 20));

(async () => {
    console.log('\nB  Verhalten');
    let { w, z, d } = umgebung();
    check('window.TotpAdmin.onShow vorhanden', typeof (w.TotpAdmin && w.TotpAdmin.onShow) === 'function');
    w.TotpAdmin.onShow();
    await warte();
    const zeilen = d.querySelectorAll('.sec-totp-row');
    check('drei Zeilen', zeilen.length === 3, String(zeilen.length));
    check('Liste mit Sitzungstoken geholt', (z.aufrufe[0] && z.aufrufe[0].init.headers || {}).Authorization === 'Bearer TOK');
    check('Kontoname mit Markup bleibt TEXT', !d.querySelector('#sec-totp-list img') && w.__xss === undefined
          && d.getElementById('sec-totp-list').textContent.includes('<img src=x'));
    const eigen = d.querySelector('.sec-totp-row[data-user="jarvis"]');
    check('eigenes Konto: kein Zuruecksetzen-Knopf', eigen && !eigen.querySelector('.sec-totp-start'));
    const row = d.querySelector('.sec-totp-row[data-user="FIRMA\\\\m.muster"]');
    check('(Positivkontrolle) Zeile des Zielkontos gefunden', !!row);
    if (!row) { bilanz = true; console.log('ABBRUCH (Exit 2)'); process.exit(2); }
    const form = row.querySelector('.sec-totp-confirm');
    check('Bestaetigung ist zunaechst verborgen', form.hasAttribute('hidden') && form.style.display === 'none');
    row.querySelector('.sec-totp-start').click();
    check('Klick oeffnet die Bestaetigung', !form.hasAttribute('hidden') && form.style.display !== 'none');
    check('Kennwortfeld ist type=password', row.querySelector('.sec-totp-pw').type === 'password');

    const vorher = z.aufrufe.length;
    row.querySelector('.sec-totp-ok').click();
    await warte();
    check('leeres Kennwort: kein Aufruf', z.aufrufe.length === vorher);
    check('leeres Kennwort: Hinweis am Knopf', row.querySelector('.sec-totp-msg').textContent.length > 0);

    row.querySelector('.sec-totp-pw').value = 'admin-geheim';
    row.querySelector('.sec-totp-ok').click();
    await warte(50);
    const post = z.aufrufe.find(a => a.pfad === '/api/admin/totp/reset');
    check('POST an /api/admin/totp/reset', !!post);
    const rumpf = post ? JSON.parse(post.init.body) : {};
    check('Rumpf {user, password} mit dem echten Kontonamen',
          rumpf.user === 'FIRMA\\m.muster' && rumpf.password === 'admin-geheim', JSON.stringify(rumpf));
    check('mit Sitzungstoken', post && post.init.headers.Authorization === 'Bearer TOK');
    check('Erfolg laedt die Liste neu', z.aufrufe.filter(a => a.pfad === '/api/admin/totp/users').length === 2);
    w.close();

    // Falsches Kennwort: Meldung bleibt, Kennwort ist geleert, Knopf wieder frei
    ({ w, z, d } = umgebung({ status: 403, body: { ok: false, error: 'Falsches Kennwort.' } }));
    w.TotpAdmin.onShow(); await warte();
    let r2 = d.querySelector('.sec-totp-row[data-user="FIRMA\\\\m.muster"]');
    r2.querySelector('.sec-totp-start').click();
    r2.querySelector('.sec-totp-pw').value = 'falsch';
    r2.querySelector('.sec-totp-ok').click();
    await warte(50);
    const msg = r2.querySelector('.sec-totp-msg').textContent;
    check('403: Meldung "Falsches Kennwort"', /Falsches Kennwort/.test(msg), msg);
    check('403: Kennwortfeld geleert', r2.querySelector('.sec-totp-pw').value === '');
    check('403: Bestaetigen wieder bedienbar', r2.querySelector('.sec-totp-ok').disabled === false);
    check('403: Liste NICHT neu geladen', z.aufrufe.filter(a => a.pfad === '/api/admin/totp/users').length === 1);
    await warte(4500);
    check('Fehlermeldung steht auch nach 4,5 s noch da', r2.querySelector('.sec-totp-msg').textContent === msg);
    r2.querySelector('.sec-totp-cancel').click();
    check('Abbrechen schliesst die Bestaetigung', r2.querySelector('.sec-totp-confirm').hasAttribute('hidden'));
    w.close();

    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (Exit 2): ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
