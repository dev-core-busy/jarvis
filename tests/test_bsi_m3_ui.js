#!/usr/bin/env node
/**
 * Waechter: BSI M3 – Oberflaeche.
 *
 *   A  Anmeldemaske (settings.html + app.js, wie ausgeliefert): Antwort
 *      ``requires_totp_setup`` zeigt QR + Schluessel + Codefeld; ein falscher
 *      Code laesst den QR stehen und zeigt den Fehler; der Code geht beim
 *      naechsten Absenden mit; Erfolg blendet die Einrichtung aus.
 *   B  Einstellungen -> Sicherheit (totp_admin.js): Pflicht-Schalter spiegelt
 *      den Server, schreibt ein echtes bool, nimmt einen Fehlschlag zurueck
 *      und meldet ihn am Schalter; gesperrte Konten werden gelistet (Namen als
 *      TEXT), "Sperre aufheben" schickt das Konto und laedt neu.
 *   C  i18n: jeder neue Schluessel in DE und EN; Container im Markup.
 *
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const SETTINGS = lies('frontend/settings.html');
const I18N = lies('frontend/js/i18n.js');
const MODUL = lies('frontend/js/totp_admin.js');

let ok = 0, fail = 0, bilanz = false;
function check(name, bed, info) {
    if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (info ? ' – ' + info : '')); }
}
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });
const warte = (ms) => new Promise(r => setTimeout(r, ms || 30));

// ── A: Anmeldemaske ─────────────────────────────────────────────────────────
function anmeldeSeite(antworten) {
    const html = SETTINGS.replace(/<script[\s\S]*?<\/script>/g, '');
    const vc = new VirtualConsole();          // Navigation (/portal) ist in jsdom nicht umgesetzt
    const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'https://jarvis.test/', virtualConsole: vc });
    const w = dom.window;
    const z = { posts: [], fehler: [] };
    w.addEventListener('error', (e) => z.fehler.push(String(e.message)));
    w.fetch = (url, init) => {
        const pfad = String(url).split('?')[0];
        let a = { status: 404, body: {} };
        if (pfad === '/api/login') {
            z.posts.push(JSON.parse((init && init.body) || '{}'));
            a = antworten.shift() || { status: 500, body: {} };
        }
        return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
    };
    for (const f of ['i18n.js', 'sitzung.js', 'app.js']) w.eval(lies('frontend/js/' + f));
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    return { w, z, d: w.document };
}
function absenden(d, w) {
    d.getElementById('login-form').dispatchEvent(new w.Event('submit', { cancelable: true }));
}

(async () => {
    console.log('\nA  Anmeldemaske');
    const SETUP = { status: 200, body: { success: false, requires_totp_setup: true,
        qr_code: 'data:image/png;base64,QUFB', secret: 'GEHEIM234',
        error: 'Für Administratoren ist die Zwei-Faktor-Anmeldung Pflicht. Bitte einmal über die Anmeldeseite anmelden und sie einrichten.' } };
    const FALSCH = { status: 401, body: { success: false, requires_totp_setup: true, error: 'Ungültiger 2FA-Code' } };
    const ERFOLG = { status: 200, body: { success: true, token: 'u:1:s', username: 'andreas', is_admin: true } };
    let { w, z, d } = anmeldeSeite([SETUP, FALSCH, ERFOLG]);
    await warte(100);
    const setup = d.getElementById('totp-setup');
    if (!setup || !d.getElementById('login-form')) {
        console.log('ABBRUCH (Exit 2): Anmeldemaske/Einrichtungsblock nicht im Markup'); bilanz = true; process.exit(2);
    }
    check('Einrichtungsblock ist zunaechst verborgen', setup.hidden === true);
    d.getElementById('login-username').value = 'andreas';
    d.getElementById('login-password').value = 'pw';
    absenden(d, w); await warte(100);
    if (z.posts.length !== 1) {
        console.log('ABBRUCH (Exit 2): Positivkontrolle – Absenden erreicht /api/login nicht'); bilanz = true; process.exit(2);
    }
    check('Einrichtung: Block sichtbar', setup.hidden === false);
    check('Einrichtung: QR aus der Antwort', d.getElementById('totp-setup-qr').getAttribute('src') === SETUP.body.qr_code);
    check('Einrichtung: Schluessel als Text', d.getElementById('totp-setup-secret').textContent === 'GEHEIM234');
    check('Einrichtung: Codefeld sichtbar', d.getElementById('totp-row').style.display !== 'none');
    check('Einrichtung: der Hinweis fuer fremde Clients steht NICHT als Fehler da',
          d.getElementById('login-error').hidden === true);

    d.getElementById('login-totp').value = '123456';
    absenden(d, w); await warte(100);
    check('zweites Absenden schickt den Code mit', z.posts[1] && z.posts[1].totp_code === '123456',
          JSON.stringify(z.posts[1]));
    check('falscher Code: Fehler sichtbar', d.getElementById('login-error').hidden === false
          && /Ungültig/.test(d.getElementById('login-error').textContent));
    check('falscher Code: QR bleibt stehen', setup.hidden === false
          && d.getElementById('totp-setup-qr').getAttribute('src') === SETUP.body.qr_code);
    check('falscher Code: Codefeld geleert', d.getElementById('login-totp').value === '');

    d.getElementById('login-totp').value = '654321';
    absenden(d, w); await warte(100);
    check('Erfolg: Einrichtung ausgeblendet', setup.hidden === true);
    check('keine Skriptfehler', z.fehler.length === 0, z.fehler.join(' | '));
    w.close();

    // ── B: Einstellungen -> Sicherheit ─────────────────────────────────────
    console.log('\nB  Anmeldeschutz im Sicherheits-Reiter');
    function sicherheit(post) {
        const dom = new JSDOM('<!doctype html><body><div id="sec-totp-list"></div>'
            + '<p id="sec-anm-hint"></p><label><input type="checkbox" id="sec-admin-2fa-pflicht"></label>'
            + '<div id="sec-anm-pflicht-msg"></div><div id="sec-anm-sperren"></div></body>',
            { runScripts: 'outside-only', url: 'https://jarvis.test/settings' });
        const w = dom.window;
        const z = { aufrufe: [], status: { ok: true, admin_2fa_pflicht: true, konto_max: 5,
            konto_fenster_min: 15, konto_sperre_min: 15,
            sperren: [{ konto: 'm.muster', display: 'FIRMA\\m.muster', bis: 2000000000 },
                      { konto: 'x', display: '<img src=x onerror="window.__xss=1">', bis: 2000000000 }] },
            post: post || { status: 200, body: { ok: true, admin_2fa_pflicht: false } } };
        w.JarvisSitzung = { token: () => 'TOK' };
        w.fetch = (url, init) => {
            const pfad = String(url).split('?')[0];
            const m = (init && init.method) || 'GET';
            z.aufrufe.push({ pfad, m, init: init || {} });
            let a = { status: 404, body: {} };
            if (pfad === '/api/admin/totp/users') a = { status: 200, body: { ok: true, users: [] } };
            else if (pfad === '/api/admin/anmeldeschutz' && m === 'GET') a = { status: 200, body: z.status };
            else if (pfad === '/api/admin/anmeldeschutz' && m === 'POST') a = z.post;
            else if (pfad === '/api/admin/anmeldeschutz/aufheben') a = { status: 200, body: { ok: true } };
            return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
        };
        w.eval(MODUL);
        return { w, z, d: w.document };
    }
    ({ w, z, d } = sicherheit());
    if (!w.TotpAdmin || typeof w.TotpAdmin.onShow !== 'function') {
        console.log('ABBRUCH (Exit 2): totp_admin.js stellt TotpAdmin.onShow nicht bereit'); bilanz = true; process.exit(2);
    }
    w.TotpAdmin.onShow(); await warte(60);
    const cb = d.getElementById('sec-admin-2fa-pflicht');
    const zeilen = d.querySelectorAll('.sec-anm-row');
    // Keine Zeilen sind ein BEFUND (onShow laedt nicht), kein Abbruchgrund –
    // die Umgebung selbst ist oben schon belegt (Modul geladen, fetch-Attrappe).
    check('onShow laedt den Anmeldeschutz (Sperrzeilen gerendert)', zeilen.length > 0);
    if (!zeilen.length) {
        bilanz = true;
        console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
        process.exit(1);
    }
    check('Schalter spiegelt den Server (an)', cb.checked === true);
    check('Hinweis nennt die Zahlen des Servers', /5/.test(d.getElementById('sec-anm-hint').textContent)
          && /15/.test(d.getElementById('sec-anm-hint').textContent), d.getElementById('sec-anm-hint').textContent);
    check('zwei gesperrte Konten gelistet', zeilen.length === 2, String(zeilen.length));
    check('Kontoname mit Markup bleibt TEXT', !d.querySelector('#sec-anm-sperren img') && w.__xss === undefined);
    zeilen[0].querySelector('.sec-anm-aufheben').click(); await warte(60);
    const auf = z.aufrufe.find(a => a.pfad === '/api/admin/anmeldeschutz/aufheben');
    check('Aufheben: POST mit dem Konto', auf && JSON.parse(auf.init.body).konto === 'm.muster');
    check('Aufheben: mit Sitzungstoken', auf && auf.init.headers.Authorization === 'Bearer TOK');
    check('Aufheben: Liste neu geladen',
          z.aufrufe.filter(a => a.pfad === '/api/admin/anmeldeschutz' && a.m === 'GET').length === 2);

    cb.checked = false;
    cb.dispatchEvent(new w.Event('change')); await warte(60);
    const post = z.aufrufe.find(a => a.pfad === '/api/admin/anmeldeschutz' && a.m === 'POST');
    check('Schalter: POST mit echtem bool false', post && JSON.parse(post.init.body).admin_2fa_pflicht === false);
    check('Schalter: Zustand der Antwort uebernommen', cb.checked === false && cb.disabled === false);
    w.close();

    ({ w, z, d } = sicherheit({ status: 403, body: { detail: 'Administrator-Rechte gibt es nur nach einer Anmeldung mit Zwei-Faktor-Code.' } }));
    w.TotpAdmin.onShow(); await warte(60);
    const cb2 = d.getElementById('sec-admin-2fa-pflicht');
    cb2.checked = false;
    cb2.dispatchEvent(new w.Event('change')); await warte(60);
    check('Fehlschlag: Schalter zurueckgenommen', cb2.checked === true);
    check('Fehlschlag: Grund am Schalter', /Zwei-Faktor/.test(d.getElementById('sec-anm-pflicht-msg').textContent));
    // Zweimal onShow (Reiter erneut geoeffnet): EIN Zuhoerer, nicht zwei
    w.TotpAdmin.onShow(); await warte(60);
    const vorher = z.aufrufe.filter(a => a.m === 'POST').length;
    cb2.checked = false; cb2.dispatchEvent(new w.Event('change')); await warte(60);
    check('erneutes Oeffnen verdrahtet den Schalter nicht doppelt',
          z.aufrufe.filter(a => a.m === 'POST').length === vorher + 1);
    w.close();

    // ── C: i18n + Markup ────────────────────────────────────────────────────
    console.log('\nC  i18n und Markup');
    const schluessel = new Set();
    for (const m of MODUL.matchAll(/T\('(security\.(?:anmeldeschutz|admin_2fa|pflicht|sperr)[a-z_]*)'/g)) schluessel.add(m[1]);
    for (const m of SETTINGS.matchAll(/data-i18n="((?:security\.(?:anmeldeschutz|admin_2fa|pflicht|sperr)|login\.totp_setup\.)[a-z_.]*)"/g)) schluessel.add(m[1]);
    schluessel.add('login.totp_setup.qr_alt');
    check('Schluessel gefunden (>= 10)', schluessel.size >= 10, String(schluessel.size));
    const fehlt = [...schluessel].filter(k => (I18N.match(new RegExp("\\n\\s*'" + k.replace(/\./g, '\\.') + "':", 'g')) || []).length !== 2);
    check('jeder Schluessel genau einmal in DE und EN', fehlt.length === 0, fehlt.join(', '));
    for (const id of ['totp-setup', 'totp-setup-qr', 'totp-setup-secret', 'sec-admin-2fa-pflicht',
                      'sec-anm-sperren', 'sec-anm-hint', 'sec-anm-pflicht-msg'])
        check('settings.html: #' + id, SETTINGS.includes('id="' + id + '"'));

    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (Exit 2): ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
