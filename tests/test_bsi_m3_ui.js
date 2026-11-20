#!/usr/bin/env node
/**
 * Waechter: BSI M3 – Oberflaeche (Admin-Rechte am Zahnrad, Betreiberentscheid 2026-11-20).
 *
 *   A  Anmeldemaske (settings.html + app.js, wie ausgeliefert): ein Admin wird
 *      NICHT mehr nach der 2FA gefragt und richtet sie dort auch nicht ein –
 *      der Einrichtungsblock ist samt Zweig entfernt. Nicht-Admins mit eigener
 *      2FA geben den Code weiterhin an der Maske ein.
 *   B  Einstellungen -> Sicherheit (totp_admin.js): kein Pflicht-Schalter mehr;
 *      gesperrte Konten werden gelistet (Namen als TEXT), "Sperre aufheben"
 *      schickt das Konto und laedt neu.
 *   C  Zahnrad (settings_btn.js im echten portal.html bzw. settings.html):
 *      sichtbar fuer ein Admin-KONTO ohne Rechte; Klick fragt den Server; Code-
 *      Dialog (sechs Ziffern schicken ab, Fehler bleibt stehen, QR bleibt bei
 *      falschem Code); Einrichtungs-Dialog mit Kennwort (ohne Kennwort kein
 *      Absenden); IdP-MFA ohne Dialog; mit Rechten Markierung + Menue
 *      (Einstellungen / Administration beenden), auf /settings nur Beenden.
 *   D  i18n: jeder Schluessel in DE und EN; entfernte Schluessel sind weg.
 *
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const SETTINGS = lies('frontend/settings.html');
const PORTAL = lies('frontend/portal.html');
const I18N = lies('frontend/js/i18n.js');
const MODUL = lies('frontend/js/totp_admin.js');
const SBTN = lies('frontend/js/settings_btn.js');
const ICONS = lies('frontend/js/icons.js');
const APPJS = lies('frontend/js/app.js');
// Kommentare weg – ein Waechter, der seine eigene Begruendung liest, prueft nichts.
const nurCode = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

let ok = 0, fail = 0, bilanz = false;
function check(name, bed, info) {
    if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (info ? ' – ' + info : '')); }
}
function abbruch(grund) {
    console.log('ABBRUCH (Exit 2): ' + grund); bilanz = true; process.exit(2);
}
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });
const warte = (ms) => new Promise(r => setTimeout(r, ms || 30));

// jsdom navigiert nicht; `location.href = ...` meldet einen jsdomError. Der ist
// hier ERWARTET – mitgezaehlt wird er als Navigationsversuch.
function konsole(z) {
    const vc = new VirtualConsole();
    vc.on('jsdomError', (err) => {
        if (/Not implemented: navigation/.test(String(err && err.message))) z.nav++;
        else z.fehler.push(String(err && err.message));
    });
    return vc;
}

// ── A: Anmeldemaske ─────────────────────────────────────────────────────────
function anmeldeSeite(antworten) {
    const html = SETTINGS.replace(/<script[\s\S]*?<\/script>/g, '');
    const z = { posts: [], fehler: [], nav: 0 };
    const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'https://jarvis.test/',
                                  virtualConsole: konsole(z) });
    const w = dom.window;
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

// ── C: Zahnrad ──────────────────────────────────────────────────────────────
/* Echte Seite (portal.html bzw. settings.html), echte Module (sitzung.js,
 * icons.js, settings_btn.js). `me` ist die Antwort von /api/me, `erh` eine
 * Liste von Antworten auf POST /api/admin/erhoehen. */
function zahnradSeite(seite, url, me, erh) {
    const z = { posts: [], fehler: [], nav: 0, me: 0 };
    const html = lies('frontend/' + seite).replace(/<script[\s\S]*?<\/script>/g, '');
    const dom = new JSDOM(html, { runScripts: 'outside-only', url, virtualConsole: konsole(z) });
    const w = dom.window;
    sitzungLaden(w, { token: 'tok-1' });
    w.addEventListener('error', (e) => z.fehler.push(String(e.message)));
    w.fetch = (u, init) => {
        const pfad = String(u).split('?')[0];
        let a = { status: 404, body: {} };
        if (pfad === '/api/me') { z.me++; a = { status: 200, body: me }; }
        else if (pfad === '/api/admin/erhoehen') {
            z.posts.push({ pfad, body: JSON.parse((init && init.body) || '{}'), init });
            a = erh.shift() || { status: 500, body: {} };
        } else if (pfad === '/api/admin/erhoehung/beenden') {
            z.posts.push({ pfad, body: JSON.parse((init && init.body) || '{}'), init });
            a = { status: 200, body: { ok: true, erhoeht: false } };
        }
        return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
    };
    w.eval(ICONS);
    w.eval(SBTN);
    w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
    return { w, z, d: w.document };
}
const knopf = (d) => d.querySelector('[data-jarvis-settings]');
const dialog = (d) => d.querySelector('.jv-erh-overlay');
function tippen(w, feld, wert) {
    feld.value = wert;
    feld.dispatchEvent(new w.Event('input'));
}

(async () => {
    console.log('\nA  Anmeldemaske');
    const ADMIN_OK = { status: 200, body: { success: true, token: 'u:1:s', username: 'andreas',
                                             is_admin: false, admin_konto: true } };
    let { w, z, d } = anmeldeSeite([ADMIN_OK]);
    await warte(100);
    if (!d.getElementById('login-form') || !d.getElementById('totp-row')) {
        abbruch('Anmeldemaske (login-form/totp-row) nicht im Markup');
    }
    check('kein Einrichtungsblock mehr im Markup (#totp-setup)', d.getElementById('totp-setup') === null);
    d.getElementById('login-username').value = 'andreas';
    d.getElementById('login-password').value = 'pw';
    absenden(d, w); await warte(100);
    if (z.posts.length !== 1) abbruch('Positivkontrolle – Absenden erreicht /api/login nicht');
    check('Admin: EIN Absenden genuegt, kein Codefeld eingeblendet',
          z.posts.length === 1 && d.getElementById('totp-row').style.display === 'none');
    check('Admin: Token gespeichert', w.localStorage.getItem('jarvis_token') === 'u:1:s');
    check('keine Skriptfehler', z.fehler.length === 0, z.fehler.join(' | '));
    w.close();

    const CODE = { status: 200, body: { success: false, requires_totp: true, error: '2FA-Code erforderlich' } };
    const FALSCH = { status: 401, body: { success: false, requires_totp: true, error: 'Ungültiger 2FA-Code' } };
    ({ w, z, d } = anmeldeSeite([CODE, FALSCH]));
    await warte(100);
    d.getElementById('login-username').value = 'bert';
    d.getElementById('login-password').value = 'pw';
    absenden(d, w); await warte(100);
    check('Nicht-Admin mit 2FA: Codefeld eingeblendet', d.getElementById('totp-row').style.display !== 'none');
    check('…die Aufforderung selbst steht NICHT als Fehler da', d.getElementById('login-error').hidden === true);
    d.getElementById('login-totp').value = '123456';
    absenden(d, w); await warte(100);
    check('zweites Absenden schickt den Code mit', z.posts[1] && z.posts[1].totp_code === '123456',
          JSON.stringify(z.posts[1]));
    check('falscher Code: Fehler sichtbar', d.getElementById('login-error').hidden === false
          && /Ungültig/.test(d.getElementById('login-error').textContent));
    w.close();
    check('REGEL: app.js kennt keinen Einrichtungszweig an der Maske mehr',
          !/requires_totp_setup|totp-setup/.test(nurCode(APPJS)));

    // ── B: Einstellungen -> Sicherheit ─────────────────────────────────────
    console.log('\nB  Anmeldeschutz im Sicherheits-Reiter');
    function sicherheit() {
        const dom = new JSDOM('<!doctype html><body><div id="sec-totp-list"></div>'
            + '<p id="sec-anm-hint"></p><div id="sec-anm-sperren"></div></body>',
            { runScripts: 'outside-only', url: 'https://jarvis.test/settings' });
        const w = dom.window;
        const z = { aufrufe: [], status: { ok: true, konto_max: 5,
            konto_fenster_min: 15, konto_sperre_min: 15,
            sperren: [{ konto: 'm.muster', display: 'FIRMA\\m.muster', bis: 2000000000 },
                      { konto: 'x', display: '<img src=x onerror="window.__xss=1">', bis: 2000000000 }] } };
        w.JarvisSitzung = { token: () => 'TOK' };
        w.fetch = (url, init) => {
            const pfad = String(url).split('?')[0];
            const m = (init && init.method) || 'GET';
            z.aufrufe.push({ pfad, m, init: init || {} });
            let a = { status: 404, body: {} };
            if (pfad === '/api/admin/totp/users') a = { status: 200, body: { ok: true, users: [] } };
            else if (pfad === '/api/admin/anmeldeschutz' && m === 'GET') a = { status: 200, body: z.status };
            else if (pfad === '/api/admin/anmeldeschutz/aufheben') a = { status: 200, body: { ok: true } };
            return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
        };
        w.eval(MODUL);
        return { w, z, d: w.document };
    }
    ({ w, z, d } = sicherheit());
    if (!w.TotpAdmin || typeof w.TotpAdmin.onShow !== 'function') {
        abbruch('totp_admin.js stellt TotpAdmin.onShow nicht bereit');
    }
    w.TotpAdmin.onShow(); await warte(60);
    const zeilen = d.querySelectorAll('.sec-anm-row');
    check('onShow laedt den Anmeldeschutz (Sperrzeilen gerendert)', zeilen.length > 0);
    if (!zeilen.length) {
        bilanz = true;
        console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
        process.exit(1);
    }
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
    check('kein POST auf den (entfernten) Pflicht-Schalter',
          !z.aufrufe.some(a => a.pfad === '/api/admin/anmeldeschutz' && a.m === 'POST'));
    w.close();
    check('REGEL: kein Pflicht-Schalter mehr (Markup und Modul)',
          !SETTINGS.includes('sec-admin-2fa-pflicht') && !/admin_2fa_pflicht/.test(nurCode(MODUL)));
    check('Sicherheits-Reiter erklaert das Zahnrad', /data-i18n="security\.admin_zahnrad_hint"/.test(SETTINGS));

    // ── C: Zahnrad ─────────────────────────────────────────────────────────
    console.log('\nC  Zahnrad');
    const KONTO = { is_admin: false, admin_konto: true, admin_erhoehung: { einrichten: false } };
    ({ w, z, d } = zahnradSeite('portal.html', 'https://jarvis.test/portal', KONTO, [
        { status: 200, body: { ok: false, requires_totp: true, error: 'Bitte den Zwei-Faktor-Code eingeben.' } },
        { status: 401, body: { ok: false, requires_totp: true, error: 'Ungültiger 2FA-Code' } },
        { status: 200, body: { ok: true, erhoeht: true } }]));
    await warte(60);
    const b = knopf(d);
    if (!b || z.me !== 1) abbruch('Positivkontrolle: Zahnrad nicht gefunden oder /api/me nicht abgefragt');
    check('Admin-KONTO ohne Rechte: Zahnrad sichtbar', b.style.display !== 'none' && !b.classList.contains('hidden'));
    check('…ohne Markierung, Beschriftung "Administration starten"',
          !b.classList.contains('jv-gear-erhoeht') && /starten/.test(b.getAttribute('title') || ''),
          b.getAttribute('title'));
    b.click(); await warte(60);
    check('Klick fragt den Server (POST /api/admin/erhoehen, ohne Code)',
          z.posts.length === 1 && !('code' in z.posts[0].body)
          && z.posts[0].init.method === 'POST' && z.posts[0].init.headers.Authorization === 'Bearer tok-1');
    let dlg = dialog(d);
    check('requires_totp -> Dialog mit Codefeld, ohne Kennwortfeld',
          !!dlg && !!dlg.querySelector('#jv-erh-code') && !dlg.querySelector('#jv-erh-pw'));
    // Ohne Dialog sind die Folgepruefungen gegenstandslos – sie wuerden an einer
    // null-Dereferenzierung ABSTUERZEN (Exit 2) statt als FAIL zu zaehlen
    // (Register: eine Sabotage, die den Waechter abstuerzen laesst, hat nicht gebissen).
    if (dlg && dlg.querySelector('#jv-erh-code')) {
        check('…die Aufforderung des Servers steht NICHT als Fehler da',
              dlg.querySelector('.jv-erh-fehler').textContent === '');
        check('…Schliessen-Knopf traegt das ×-Symbol aus icons.js', !!dlg.querySelector('.jv-erh-x svg'));
        tippen(w, dlg.querySelector('#jv-erh-code'), '12 34 5');
        await warte(40);
        check('fuenf Ziffern schicken NICHT ab', z.posts.length === 1);
        tippen(w, dlg.querySelector('#jv-erh-code'), '123456');
        await warte(60);
        check('sechs Ziffern schicken ab, mit dem Code', z.posts.length === 2 && z.posts[1].body.code === '123456',
              JSON.stringify(z.posts.map(p => p.body)));
        dlg = dialog(d);
        check('falscher Code: Dialog bleibt, Fehler steht da, Feld geleert',
              !!dlg && /Ungültig/.test(dlg.querySelector('.jv-erh-fehler').textContent)
              && dlg.querySelector('#jv-erh-code').value === '');
        if (dlg) {
            tippen(w, dlg.querySelector('#jv-erh-code'), '654321');
            await warte(60);
        }
        check('richtiger Code: Dialog zu, Wechsel nach /settings mit Rueckweg',
              !dialog(d) && z.nav >= 1 && w.sessionStorage.getItem('jarvis_settings_return') === '/portal',
              'nav=' + z.nav + ' ret=' + w.sessionStorage.getItem('jarvis_settings_return'));
    }
    check('keine Skriptfehler', z.fehler.length === 0, z.fehler.join(' | '));
    w.close();

    // Escape schliesst
    ({ w, z, d } = zahnradSeite('portal.html', 'https://jarvis.test/portal', KONTO, [
        { status: 200, body: { ok: false, requires_totp: true } }]));
    await warte(60);
    knopf(d).click(); await warte(60);
    const vorEsc = !!dialog(d);
    d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    check('Escape schliesst den Dialog', vorEsc && !dialog(d));
    w.close();

    // Einrichtung: QR, Code UND Kennwort
    ({ w, z, d } = zahnradSeite('portal.html', 'https://jarvis.test/portal',
        { is_admin: false, admin_konto: true, admin_erhoehung: { einrichten: true } }, [
        { status: 200, body: { ok: false, requires_totp_setup: true, qr_code: 'data:image/png;base64,QUFB',
                               secret: 'GEHEIM234', error: 'Für Administratoren ist die Zwei-Faktor-Anmeldung Pflicht.' } },
        { status: 401, body: { ok: false, requires_totp_setup: true, error: 'Falsches Kennwort' } },
        { status: 200, body: { ok: true, erhoeht: true } }]));
    await warte(60);
    knopf(d).click(); await warte(60);
    dlg = dialog(d);
    check('Einrichtung: QR aus der Antwort, Schluessel als TEXT',
          !!dlg && !!dlg.querySelector('.jv-erh-qr img')
          && dlg.querySelector('.jv-erh-qr img').getAttribute('src') === 'data:image/png;base64,QUFB'
          && dlg.querySelector('.jv-erh-schluessel').textContent === 'GEHEIM234');
    check('Einrichtung: Code- UND Kennwortfeld (type=password)',
          !!dlg && !!dlg.querySelector('#jv-erh-code') && !!dlg.querySelector('#jv-erh-pw')
          && dlg.querySelector('#jv-erh-pw').type === 'password');
    if (dlg && dlg.querySelector('#jv-erh-code') && dlg.querySelector('#jv-erh-pw')) {
        tippen(w, dlg.querySelector('#jv-erh-code'), '123456');
        await warte(40);
        check('Einrichtung: sechs Ziffern schicken OHNE Kennwort nicht ab', z.posts.length === 1);
        // Die Kennwortzeile kommt NACH dem Code – ein Hinweis "Kennwort fehlt",
        // waehrend der Benutzer noch gar nicht dort ist, waere ein Fehlalarm.
        check('Einrichtung: nach sechs Ziffern noch KEIN Hinweis auf das Kennwort',
              dlg.querySelector('.jv-erh-fehler').textContent === '',
              dlg.querySelector('.jv-erh-fehler').textContent);
        dlg.querySelector('.jv-erh-btn-haupt').click(); await warte(40);
        check('Einrichtung: Freischalten ohne Kennwort -> Hinweis, kein POST',
              z.posts.length === 1 && /Kennwort/.test(dlg.querySelector('.jv-erh-fehler').textContent),
              dlg.querySelector('.jv-erh-fehler').textContent);
        dlg.querySelector('#jv-erh-pw').value = 'geheim';
        dlg.querySelector('.jv-erh-btn-haupt').click(); await warte(60);
        check('Einrichtung: POST mit Code und Kennwort',
              z.posts.length === 2 && z.posts[1].body.code === '123456' && z.posts[1].body.password === 'geheim');
        dlg = dialog(d);
        check('falsches Kennwort: QR bleibt stehen, Meldung steht da',
              !!dlg && !!dlg.querySelector('.jv-erh-qr img')
              && /Falsches Kennwort/.test(dlg.querySelector('.jv-erh-fehler').textContent));
        if (dlg && dlg.querySelector('#jv-erh-pw')) {
            tippen(w, dlg.querySelector('#jv-erh-code'), '222222');
            dlg.querySelector('#jv-erh-pw').value = 'richtig';
            dlg.querySelector('.jv-erh-btn-haupt').click(); await warte(60);
        }
        check('Einrichtung erfolgreich: Dialog zu, Wechsel ausgeloest', !dialog(d) && z.nav >= 1);
    }
    w.close();

    // Meldet der Server schon beim ersten Klick "erhoeht" (die Sitzung hatte die
    // Rechte bereits, z. B. in einem anderen Tab geholt): kein Dialog, direkt weiter.
    ({ w, z, d } = zahnradSeite('portal.html', 'https://jarvis.test/portal',
        { is_admin: false, admin_konto: true, admin_erhoehung: { einrichten: false } }, [
        { status: 200, body: { ok: true, erhoeht: true } }]));
    await warte(60);
    knopf(d).click(); await warte(60);
    check('Server meldet schon erhoeht: kein Dialog, direkt nach /settings',
          !dialog(d) && z.posts.length === 1 && z.nav >= 1);
    w.close();

    // Mit Rechten: Markierung + Menue
    const AKTIV = { is_admin: true, admin_konto: true, admin_badge: { root_pending: 0, gesperrt: 0, gesamt: 0 } };
    ({ w, z, d } = zahnradSeite('portal.html', 'https://jarvis.test/portal', AKTIV, []));
    await warte(60);
    check('mit Rechten: Zahnrad markiert (jv-gear-erhoeht)', knopf(d).classList.contains('jv-gear-erhoeht'));
    knopf(d).click(); await warte(40);
    let menue = d.querySelector('.jv-erh-menue');
    const eintraege = menue ? [...menue.querySelectorAll('.jv-erh-menue-zeile')].map(e => e.textContent) : [];
    check('Klick oeffnet das Menue: Einstellungen + Administration beenden',
          eintraege.length === 2 && /Einstellungen/.test(eintraege[0]) && /beenden/.test(eintraege[1]),
          JSON.stringify(eintraege));
    check('…kein POST beim Oeffnen des Menues', z.posts.length === 0);
    if (menue && menue.querySelector('.is-ende')) {
        menue.querySelector('.is-ende').click(); await warte(60);
    }
    check('Administration beenden: POST /api/admin/erhoehung/beenden, Menue zu, Seite neu',
          z.posts.length === 1 && z.posts[0].pfad === '/api/admin/erhoehung/beenden'
          && !d.querySelector('.jv-erh-menue') && z.nav >= 1, 'nav=' + z.nav);
    w.close();

    // Auf /settings: nur Beenden, danach zurueck zum Rueckweg
    ({ w, z, d } = zahnradSeite('settings.html', 'https://jarvis.test/settings', AKTIV, []));
    await warte(60);
    // Fehlt das Zahnrad, ist das ein BEFUND (Markup-Aenderung), kein
    // "konnte nicht laufen" – Register: Guards trennen die beiden Ursachen.
    check('/settings traegt das Zahnrad', !!knopf(d));
    if (knopf(d)) {
        check('/settings: Zahnrad sichtbar und markiert',
              knopf(d).style.display !== 'none' && knopf(d).classList.contains('jv-gear-erhoeht'));
        knopf(d).click(); await warte(40);
        menue = d.querySelector('.jv-erh-menue');
        check('/settings: Menue nur mit "Administration beenden"',
              !!menue && menue.querySelectorAll('.jv-erh-menue-zeile').length === 1
              && !!menue.querySelector('.is-ende'));
    }
    w.close();

    // Nicht-Admin: kein Zahnrad
    ({ w, z, d } = zahnradSeite('portal.html', 'https://jarvis.test/portal',
        { is_admin: false, admin_konto: false }, []));
    await warte(60);
    check('Nicht-Admin: Zahnrad bleibt verborgen', knopf(d).style.display === 'none');
    w.close();

    // ── D: i18n ─────────────────────────────────────────────────────────────
    console.log('\nD  i18n und Markup');
    const schluessel = new Set();
    for (const m of MODUL.matchAll(/T\('(security\.(?:anmeldeschutz|sperr)[a-z_]*)'/g)) schluessel.add(m[1]);
    for (const m of SETTINGS.matchAll(/data-i18n="(security\.(?:anmeldeschutz|admin_zahnrad|sperr)[a-z_.]*)"/g)) schluessel.add(m[1]);
    for (const m of SBTN.matchAll(/T\('(gear\.[a-z_]+)'/g)) schluessel.add(m[1]);
    check('Schluessel gefunden (>= 20)', schluessel.size >= 20, String(schluessel.size));
    const anzahl = (k) => (I18N.match(new RegExp("\\n\\s*'" + k.replace(/\./g, '\\.') + "':", 'g')) || []).length;
    const fehlt = [...schluessel].filter(k => anzahl(k) !== 2);
    check('jeder Schluessel genau einmal in DE und EN', fehlt.length === 0, fehlt.join(', '));
    const tot = ['login.totp_setup.text', 'login.totp_setup.manual', 'login.totp_setup.qr_alt',
                 'security.admin_2fa_pflicht', 'security.admin_2fa_pflicht_h',
                 'security.admin_2fa_pflicht_hint', 'login.idp_totp_text']
        .filter(k => anzahl(k) !== 0);
    check('entfernte Schluessel sind aus i18n.js verschwunden', tot.length === 0, tot.join(', '));
    for (const id of ['sec-anm-sperren', 'sec-anm-hint', 'btn-settings-gear'])
        check('settings.html: #' + id, SETTINGS.includes('id="' + id + '"'));
    check('portal.html bindet settings_btn.js ein', /js\/settings_btn\.js\?v=\d+/.test(PORTAL));

    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (Exit 2): ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
