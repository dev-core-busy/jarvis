/* Waechter: VEMAS "Anmeldung ueber die Portal-Kachel" in der Oberflaeche
 * (2026-11-05, analog zu tests/test_sap_portal_ui.js Abschnitte 19–21).
 *
 * jsdom gegen die ECHTEN Dateien (frontend/vemas.html + js/vemas_portal.js,
 * frontend/settings.html + js/vemas.js) mit gemockter API:
 *   1. /vemas, Anmeldekarte: erscheint ohne Klick, Benutzer vorbelegt,
 *      autocomplete stimmt, genau EIN Speichern (nur das Kennwort), sofortiger
 *      Verbindungstest, Merken nur bei Erfolg
 *   2. /vemas, "Mein VEMAS-Zugang" im Kachel-Modus: Formular fuer den Browser,
 *      genau EIN Absenden; im Normalmodus speichert Enter/Absenden nichts
 *   3. Einstellungen → Vemas: Rueckfrage beim Einschalten, gesperrte
 *      Kennwortfelder, Liste sagt "kein Kennwort gespeichert"
 *
 * VEMAS_PORTAL_JS / VEMAS_JS legen sabotierte KOPIEN vor (Gegenprobe).
 * Aufruf: node tests/test_vemas_kachel_ui.js
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const PORTAL_JS = process.env.VEMAS_PORTAL_JS || path.join(ROOT, 'frontend', 'js', 'vemas_portal.js');
const VEMAS_JS = process.env.VEMAS_JS || path.join(ROOT, 'frontend', 'js', 'vemas.js');
const SITZUNG = fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const KONTO = { vorhanden: true, auth_kind: 'basic', aktiv: true, username: 'MUSTER',
                passwort_gesetzt: false, token_gesetzt: false, letzter_erfolg: 1730000000,
                letzter_fehler: '', anmeldefehler: 0, ausgesetzt: false,
                server: 'https://vemas.beispiel.de/api', server_konfiguriert: true,
                schreiben_frei: false };

/** /vemas mit gemockter API. `status` darf eine Funktion sein. */
async function portal(opts) {
    const html = fs.readFileSync(path.join(ROOT, 'frontend', 'vemas.html'), 'utf8');
    const posts = [], tests = [], merken = [];
    const vc = new VirtualConsole();
    const dom = new JSDOM(html, {
        url: 'https://localhost/vemas', runScripts: 'outside-only', virtualConsole: vc,
        beforeParse(win) {
            win.localStorage.setItem('jarvis_token', 'testtoken');
            win.PasswordCredential = function (d) { Object.assign(this, d); };
            Object.defineProperty(win.navigator, 'credentials', { configurable: true,
                value: { store: (c) => { merken.push(c); return Promise.resolve(); } } });
            win.fetch = (url, init) => {
                const u = String(url).split('?')[0];
                const body = (init && init.body) ? JSON.parse(init.body) : null;
                const json = (data) => Promise.resolve({ ok: true, status: 200,
                    json: () => Promise.resolve(data), text: () => Promise.resolve(JSON.stringify(data)) });
                if (u === '/api/me') return json({ username: 'anna', permissions: { vemas: true } });
                if (u === '/api/vemas/status') {
                    const st = typeof opts.status === 'function' ? opts.status(posts) : opts.status;
                    return json(Object.assign({ ok: true, configured: true, read_only: true, resources: 1 }, st));
                }
                if (u === '/api/vemas/account') {
                    if (init && init.method === 'POST') posts.push(body);
                    return json({ ok: true, account: opts.konto });
                }
                if (u === '/api/vemas/test') { tests.push(u); return json(opts.test || { ok: true }); }
                if (u === '/api/vemas/analyses') return json({ ok: true, categories: [], analyses: [] });
                return json({ ok: true });
            };
        },
    });
    dom.window.eval(SITZUNG);
    dom.window.eval(I18N);
    dom.window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8'));
    dom.window.eval(SITZUNG);
    dom.window.eval(fs.readFileSync(PORTAL_JS, 'utf8'));
    await sleep(200);
    return { dom, posts, tests, merken, $: (id) => dom.window.document.getElementById(id) };
}

(async () => {
    console.log('\n1. /vemas: Anmeldekarte');
    const ANM = { feld: 'password', benutzer: 'MUSTER', kanal: 'basic' };
    {
        const k = await portal({
            konto: Object.assign({ kachel_pflicht: true, angemeldet: false }, KONTO),
            test: { ok: true, detail: 'OK', quelle: 'persoenlich' },
            status: (posts) => posts.length
                ? { configured: true, kachel_pflicht: true, quelle: 'persoenlich', anmeldung: {} }
                : { configured: false, kachel_pflicht: true, quelle: 'keine',
                    hinweis: 'Fuer VEMAS ist eine Anmeldung noetig.', anmeldung: ANM },
        });
        const $ = k.$;
        const box = $('vm-login');
        if (!box || box.tagName !== 'FORM' || !box.contains($('vm-login-pass'))) {
            console.log('ABBRUCH: Anmeldekarte fehlt oder ist kein Formular');
            process.exit(2);
        }
        check(box.hidden === false, 'Karte erscheint ohne Klick');
        check($('vm-login-user').value === 'MUSTER', 'VEMAS-Benutzer vorbelegt', $('vm-login-user').value);
        check($('vm-login-user').getAttribute('autocomplete') === 'username'
              && $('vm-login-pass').getAttribute('autocomplete') === 'current-password',
              'autocomplete=username / current-password');
        check(!/Anmeldung noetig/.test($('vm-note') ? $('vm-note').textContent : ''),
              'kein Hinweistext statt der Karte');
        $('vm-login-pass').value = 'Richtig-123';
        $('vm-login-btn').click();
        await sleep(160);
        check(k.posts.length === 1 && JSON.stringify(Object.keys(k.posts[0] || {})) === '["password"]',
              'genau EIN Speichern, nur das Kennwort', JSON.stringify(k.posts));
        check(k.tests.length === 1, 'danach sofort ein Verbindungstest', String(k.tests.length));
        check(k.merken.length === 1 && k.merken[0].id === 'MUSTER', 'Erfolg: Browser darf sich das Kennwort merken',
              JSON.stringify(k.merken));
        check($('vm-login').hidden === true && $('vm-login-pass').value === '', 'Erfolg: Karte weg, Feld leer');
        k.dom.window.close();
    }
    {
        const k = await portal({
            konto: Object.assign({ kachel_pflicht: true, angemeldet: false }, KONTO),
            test: { ok: false, error: '401 Unauthorized' },
            status: { configured: false, kachel_pflicht: true, quelle: 'keine', anmeldung: ANM },
        });
        k.$('vm-login-pass').value = 'Falsch';
        k.$('vm-login-btn').click();
        await sleep(160);
        check(k.$('vm-login').hidden === false && /401/.test(k.$('vm-login-status').textContent),
              'Fehlschlag: Karte bleibt, Grund steht daran', k.$('vm-login-status').textContent);
        check(k.merken.length === 0, 'Fehlschlag: KEIN Angebot zum Merken');
        k.dom.window.close();
    }

    console.log('\n2. /vemas: "Mein VEMAS-Zugang"');
    {
        const k = await portal({
            konto: Object.assign({ kachel_pflicht: true, angemeldet: false }, KONTO),
            status: { configured: false, kachel_pflicht: true, quelle: 'keine', anmeldung: {},
                      hinweis: 'Es ist noch kein eigener VEMAS-Zugang eingerichtet.' },
        });
        const $ = k.$;
        check(!!$('vm-acc-form') && $('vm-acc-form').contains($('vm-acc-pass')) && $('vm-acc-form').contains($('vm-acc-save')),
              'Positivkontrolle: Formular umschliesst Kennwort und Knopf');
        check($('vm-login').hidden === true, 'ohne erfolgreichen Vorlauf: keine Anmeldekarte');
        check($('vm-acc-user').getAttribute('autocomplete') === 'username'
              && $('vm-acc-pass').getAttribute('autocomplete') === 'current-password',
              'Kachel-Modus: Felder fuer die Browser-Anmeldung');
        check($('vm-acc-save').type === 'submit' && /Anmelden/.test($('vm-acc-save').textContent),
              'Knopf "Anmelden" (submit)', $('vm-acc-save').type + ' / ' + $('vm-acc-save').textContent);
        check(/nicht angemeldet/.test($('vm-acc-pill').textContent), 'Pille: nicht angemeldet', $('vm-acc-pill').textContent);
        $('vm-acc-pass').value = 'Kachel-1';
        $('vm-acc-save').click();
        await sleep(100);
        check(k.posts.length === 1 && k.posts[0].password === 'Kachel-1', 'genau EIN Absenden mit Kennwort',
              JSON.stringify(k.posts));
        k.dom.window.close();
    }
    {
        const k = await portal({
            konto: Object.assign({ kachel_pflicht: false }, KONTO),
            status: { configured: true, quelle: 'persoenlich' },
        });
        const $ = k.$;
        check($('vm-acc-pass').getAttribute('autocomplete') === 'new-password'
              && $('vm-acc-save').type === 'button', 'Normalmodus unveraendert');
        $('vm-acc-form').dispatchEvent(new k.dom.window.Event('submit', { cancelable: true, bubbles: true }));
        await sleep(40);
        check(k.posts.length === 0, 'Normalmodus: Absenden speichert nichts', String(k.posts.length));
        k.dom.window.close();
    }

    console.log('\n3. Einstellungen → Vemas');
    async function reiter(cfg, konten, antwort) {
        const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
        const posts = [], fragen = [];
        const s = new JSDOM(html, {
            url: 'https://localhost/settings', runScripts: 'outside-only',
            beforeParse(win) {
                win.localStorage.setItem('jarvis_token', 'testtoken');
                win.confirm = (t) => { fragen.push(t); return antwort; };
                win.fetch = (url, init) => {
                    const u = String(url).split('?')[0];
                    const json = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(d) });
                    if (u === '/api/skills/vemas/config') {
                        if (init && init.method === 'POST') { posts.push(JSON.parse(init.body)); return json({ success: true }); }
                        return json({ config: cfg, geheim_gesetzt: ['password'] });
                    }
                    if (u === '/api/vemas/admin/accounts') return json(konten);
                    return json({ ok: true });
                };
            },
        });
        s.window.eval(SITZUNG); s.window.eval(I18N); s.window.eval(SITZUNG);
        // Das ECHTE skillcfg.js, keine Attrappe: die Zugangsliste nimmt den
        // Kennwort-/Anmeldezustand aus SkillCfg.kennwortZustand (seit 2026-11-10
        // EINE Fassung fuer SAP und VEMAS) – in settings.html steht es vor vemas.js.
        s.window.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/skillcfg.js'), 'utf8'));
        s.window.eval(fs.readFileSync(VEMAS_JS, 'utf8'));
        s.window.VemasManager.onShow();
        await sleep(150);
        return { s, posts, fragen, $: (id) => s.window.document.getElementById(id) };
    }
    if (!fs.readFileSync(VEMAS_JS, 'utf8').includes('window.VemasManager')) {
        console.log('ABBRUCH: VemasManager nicht exportiert'); process.exit(2);
    }
    {
        const e = await reiter({ base_url: 'https://vemas.beispiel.de/api', auth_kind: 'basic' },
            { ok: true, kachel_pflicht: false, accounts: [{ user: 'm.mustermann', auth_kind: 'basic', aktiv: true,
              ausgesetzt: false, kennwort_gespeichert: true }] }, false);
        const txt = e.$('vemas-accounts-list').textContent;
        check(/– Kennwort gespeichert/.test(txt), 'ohne Schalter: "Kennwort gespeichert"', txt);
        check(e.$('vemas-password').disabled === false, 'ohne Schalter: Kennwortfeld frei');
        e.$('vemas-kachel-pflicht').checked = true;
        e.$('vemas-kachel-pflicht').dispatchEvent(new e.s.window.Event('change'));
        check(e.$('vemas-password').disabled && e.$('vemas-token').disabled, 'Haken sperrt Kennwort und Token');
        e.$('vemas-save').click();
        await sleep(60);
        check(e.fragen.length === 1 && /gelöscht/.test(e.fragen[0] || ''), 'Einschalten fragt nach', String(e.fragen[0]));
        check(e.posts.length === 0, 'Abbrechen speichert nichts', String(e.posts.length));
        e.s.window.close();
    }
    {
        const e = await reiter({ base_url: 'https://vemas.beispiel.de/api', kachel_anmeldung: true },
            { ok: true, kachel_pflicht: true, accounts: [{ user: 'm.mustermann', auth_kind: 'basic', aktiv: true,
              ausgesetzt: false, kennwort_gespeichert: false, angemeldet: false }] }, true);
        const txt = e.$('vemas-accounts-list').textContent;
        check(/kein VEMAS-Kennwort gespeichert/.test(txt) && /kein Kennwort gespeichert · nicht angemeldet/.test(txt),
              'Liste: kein Kennwort gespeichert, nicht angemeldet', txt);
        e.$('vemas-save').click();
        await sleep(60);
        check(e.fragen.length === 0 && e.posts.length === 1 && e.posts[0].kachel_anmeldung === true,
              'schon an: speichert ohne erneute Rueckfrage', e.fragen.length + '/' + JSON.stringify(e.posts.map((p) => p.kachel_anmeldung)));
        e.s.window.close();
    }

    console.log('\n4. Texte in beiden Sprachen');
    {
        const grenze = I18N.search(/\n\s*en\s*:\s*\{/);
        const bl = { de: I18N.slice(0, grenze), en: I18N.slice(grenze) };
        const keys = [...new Set([...(fs.readFileSync(PORTAL_JS, 'utf8') + fs.readFileSync(VEMAS_JS, 'utf8')
            + fs.readFileSync(path.join(ROOT, 'frontend/vemas.html'), 'utf8'))
            .matchAll(/['"](vemas\.(?:login_[a-z_]+|acc_(?:pass_kachel_ph|hint_kachel|pill_none|login|logout|logging_in|logged_in|logged_out|none_kachel)|not_logged_in|kachel_pflicht(?:_hint|_confirm)?|adm_kachel_kopf))['"]/g)].map((m) => m[1]))];
        check(keys.length >= 15, 'Positivkontrolle: Kachel-Schluessel gefunden', String(keys.length));
        const fehlt = [];
        keys.forEach((k) => ['de', 'en'].forEach((lg) => { if (bl[lg].indexOf("'" + k + "':") < 0) fehlt.push(lg + ':' + k); }));
        check(grenze > 0 && fehlt.length === 0, 'alle in DE und EN', fehlt.join(', '));
    }

    console.log('\n' + '='.repeat(46));
    console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
