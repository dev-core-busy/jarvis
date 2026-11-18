#!/usr/bin/env node
/**
 * Waechter: Anmeldung ueber den IdP auf der Anmeldemaske (idp_anmeldung.js).
 *
 *  A  EINBINDUNG: settings.html laedt idp_anmeldung.js und settings_idp.js,
 *     der Knopf ist ein LINK auf /api/login/oidc/start (kein Formular – CSP
 *     form-action 'self'), Code-Block ausserhalb des Formulars.
 *  B  VERHALTEN in jsdom auf dem ECHTEN Markup von settings.html, mit den
 *     echten Modulen i18n.js, sitzung.js, idp_anmeldung.js:
 *     Knopf nur bei aktiv:true, Fehlerkennung -> uebersetzter Text und
 *     Adresse aufgeraeumt, anmeldung=idp -> POST einloesen mit Sitzungs-Kopf,
 *     requires_totp -> Code-Block statt Formular, 6 Ziffern -> zweiter POST
 *     mit Code, Erfolg -> Token gespeichert + Weiterleitung auf /portal.
 *  C  TEXTE: jeder login.idp_* / security.idp_* / security.sub_idp*-Schluessel
 *     aus Markup und Modulen steht in DE und EN.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs'), path = require('path');
const REPO = path.resolve(__dirname, '..');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const lies = (p) => fs.readFileSync(path.join(REPO, p), 'utf8');

let ok = 0, fail = 0, bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });
const ALLE_FEHLER = [];
const warte = (ms) => new Promise(r => setTimeout(r, ms || 30));

const SETTINGS = lies('frontend/settings.html');
const MODUL = lies('frontend/js/idp_anmeldung.js');
const MODUL_ADMIN = lies('frontend/js/settings_idp.js');
const I18N = lies('frontend/js/i18n.js');

// ── A: Einbindung ───────────────────────────────────────────────────────────
console.log('A  Einbindung');
check('settings.html laedt idp_anmeldung.js', /<script src="\/static\/js\/idp_anmeldung\.js\?v=\d+"><\/script>/.test(SETTINGS));
check('settings.html laedt settings_idp.js', /<script src="\/static\/js\/settings_idp\.js\?v=\d+"><\/script>/.test(SETTINGS));
const knopf = SETTINGS.match(/<a id="btn-idp-login"[^>]*>/);
check('Knopf ist ein Link auf /api/login/oidc/start', !!knopf && /href="\/api\/login\/oidc\/start"/.test(knopf[0]));
const formStart = SETTINGS.indexOf('<form id="login-form"');
const formEnde = SETTINGS.indexOf('</form>', formStart);
const totpPos = SETTINGS.indexOf('id="idp-totp"');
check('Code-Block steht AUSSERHALB des Anmeldeformulars', totpPos > 0 && (totpPos < formStart || totpPos > formEnde));
check('Knopf-Bereich ist anfangs verborgen', /<div id="idp-login" hidden>/.test(SETTINGS));

// ── B: Verhalten ────────────────────────────────────────────────────────────
function seite(url, antworten) {
    const html = SETTINGS.replace(/<script[\s\S]*?<\/script>/g, '');
    const vc = new VirtualConsole();
    const z = { posts: [], koepfe: [], nav: [], fehler: [] };
    vc.on('jsdomError', (e) => { if (/navigation/i.test(String(e && e.message))) z.nav.push(e.message); else z.fehler.push(String(e && e.message)); });
    const dom = new JSDOM(html, { runScripts: 'outside-only', url, virtualConsole: vc });
    const w = dom.window;
    w.addEventListener('error', (e) => z.fehler.push(String(e.message)));
    w.fetch = (u, init) => {
        const pfad = String(u).split('?')[0];
        let a = { status: 404, body: {} };
        if (pfad === '/api/login/oidc/status') a = { status: 200, body: { aktiv: antworten.aktiv } };
        if (pfad === '/api/login/oidc/einloesen') {
            z.posts.push(JSON.parse((init && init.body) || '{}'));
            z.koepfe.push((init && init.headers) || {});
            a = antworten.einloesen.shift() || { status: 500, body: {} };
        }
        return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
    };
    for (const f of ['i18n.js', 'sitzung.js']) w.eval(lies('frontend/js/' + f));
    w.eval(MODUL);
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    ALLE_FEHLER.push(z.fehler);
    return { w, z, d: w.document, dom };
}

(async () => {
    console.log('B  Verhalten');
    // Positivkontrolle: das Modul ist geladen
    let s = seite('https://jarvis.test/', { aktiv: true, einloesen: [] });
    await warte(60);
    if (!s.w.IdpAnmeldung) { console.log('ABBRUCH (Exit 2): idp_anmeldung.js nicht geladen'); bilanz = true; process.exit(2); }
    check('aktiv:true -> Knopf sichtbar', s.d.getElementById('idp-login').hidden === false);
    check('ohne Kennung kein Einloesen', s.z.posts.length === 0);
    s.w.close();

    s = seite('https://jarvis.test/', { aktiv: false, einloesen: [] });
    await warte(60);
    check('aktiv:false -> Knopf bleibt verborgen', s.d.getElementById('idp-login').hidden === true);
    s.w.close();

    s = seite('https://jarvis.test/?idp_fehler=keine_freigabe', { aktiv: true, einloesen: [] });
    await warte(60);
    const err = s.d.getElementById('login-error');
    check('Fehlerkennung -> Text in #login-error', !err.hidden && err.textContent === 'Keine Anmeldeberechtigung.', err.textContent);
    check('Adresse danach aufgeraeumt', s.w.location.search === '', s.w.location.href);
    s.w.close();

    s = seite('https://jarvis.test/?idp_fehler=%3Cimg%20src%3Dx%3E', { aktiv: true, einloesen: [] });
    await warte(60);
    check('unbekannte Kennung: allgemeiner Text, kein Markup', s.d.querySelector('#login-error img') === null
          && s.d.getElementById('login-error').textContent.length > 0);
    s.w.close();

    s = seite('https://jarvis.test/?anmeldung=idp', { aktiv: true, einloesen: [
        { status: 200, body: { success: false, requires_totp: true, error: '2FA-Code erforderlich' } },
        { status: 200, body: { success: true, token: 'CSRF', username: 'm.muster', is_admin: false } }] });
    await warte(80);
    check('anmeldung=idp -> POST einloesen ohne Code', s.z.posts.length === 1 && !('totp_code' in s.z.posts[0]));
    check('Einloesen mit Sitzungs-Kopf (Cookie-Verfahren)', (s.z.koepfe[0] || {})['X-Jarvis-Sitzung'] === 'cookie',
          JSON.stringify(s.z.koepfe[0]));
    check('requires_totp -> Code-Block sichtbar, Formular verborgen',
          s.d.getElementById('idp-totp').hidden === false && s.d.getElementById('login-form').hidden === true);
    const feld = s.d.getElementById('idp-totp-code');
    feld.value = '12 34 56';
    feld.dispatchEvent(new s.w.Event('input'));
    await warte(80);
    check('6 Ziffern -> zweiter POST mit Code', s.z.posts.length === 2 && s.z.posts[1].totp_code === '123456',
          JSON.stringify(s.z.posts));
    check('Erfolg -> Token gespeichert', s.w.localStorage.getItem('jarvis_token') === 'CSRF'
          && s.w.localStorage.getItem('jarvis_user') === 'm.muster');
    check('Erfolg -> Weiterleitung (Navigation) ausgeloest', s.z.nav.length >= 1);
    s.w.close();

    s = seite('https://jarvis.test/?anmeldung=idp', { aktiv: true, einloesen: [
        { status: 401, body: { success: false, abgelaufen: true, error: 'Die Anmeldung über das Firmenkonto ist abgelaufen.' } }] });
    await warte(80);
    check('abgelaufen -> Meldung im Formular, Formular sichtbar',
          s.d.getElementById('login-form').hidden === false
          && /abgelaufen/.test(s.d.getElementById('login-error').textContent));
    check('abgelaufen -> nichts gespeichert, keine Weiterleitung',
          !s.w.localStorage.getItem('jarvis_token') && s.z.nav.length === 0);
    s.w.close();
    const fehlerAlle = [].concat(...ALLE_FEHLER);
    check('keine Skriptfehler in allen Laeufen', fehlerAlle.length === 0, fehlerAlle.join(' | '));

    // ── C: Texte ─────────────────────────────────────────────────────────────
    console.log('C  Texte');
    const schluessel = new Set();
    const quellen = SETTINGS + MODUL + MODUL_ADMIN;
    for (const m of quellen.matchAll(/['"]((?:login\.idp|security\.idp|security\.sub_idp)[a-z_.]*)['"]/g)) {
        // Praefix eines zusammengesetzten Schluessels (T('login.idp_err.' + k)) ist keiner.
        if (!m[1].endsWith('.')) schluessel.add(m[1]);
    }
    for (const k of Object.keys(s.w.IdpAnmeldung ? s.w.IdpAnmeldung._FEHLER : {})) schluessel.add('login.idp_err.' + k);
    const vorkommen = (k) => (I18N.match(new RegExp("'" + k.replace(/\./g, '\\.') + "'\\s*:", 'g')) || []).length;
    check('Positivkontrolle: Schluessel gefunden (' + schluessel.size + ')', schluessel.size >= 40);
    const fehlt = [...schluessel].filter(k => vorkommen(k) !== 2);
    check('jeder Schluessel steht genau zweimal (DE + EN)', fehlt.length === 0, fehlt.join(', '));

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (Exit 2): ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
