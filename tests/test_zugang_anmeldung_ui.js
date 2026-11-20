/* Waechter: weitere Anmeldungen nach der Jarvis-Anmeldung und Anmeldung fuer
 * die Sitzung in den Bereichen Jira/Confluence (2026-11-15).
 *
 * jsdom gegen die ECHTEN Dateien mit gestellter API:
 *   1. settings.html + zugang_anmeldung.js: der zweite Schritt erscheint NUR mit
 *      Eintraegen, blockiert nie (leere Liste, Netzfehler), meldet ueber die
 *      vorhandenen Wege an (SAP: Konto + Test, Jira/Confluence: Sitzung), laesst
 *      leere Felder aus, behaelt den Schritt bei einem Fehler, leert jedes
 *      Geheimfeld, "Ueberspringen" geht weiter, danach Grundzustand.
 *   2. app.js: der Schritt liegt VOR dem Weiterleiten.
 *   3. jira_addon.html/confluence_addon.html + zugang_sitzung.js: Abschnitt nur
 *      im Sitzungsbetrieb, Anmelden/Abmelden ueber /api/<system>/account/sitzung.
 *
 * ZA_JS / ZS_JS / ZA_APP legen sabotierte KOPIEN vor (Gegenprobe).
 * Aufruf: node tests/test_zugang_anmeldung_ui.js
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const ZA_JS = process.env.ZA_JS || path.join(ROOT, 'frontend/js/zugang_anmeldung.js');
const ZS_JS = process.env.ZS_JS || path.join(ROOT, 'frontend/js/zugang_sitzung.js');
const APP_JS = process.env.ZA_APP || path.join(ROOT, 'frontend/js/app.js');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
function section(t) { console.log('\n═══ ' + t); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Seite laden; `api(pfad, methode, rumpf)` liefert {status, data} oder wirft. */
function seite(datei, api) {
    const html = fs.readFileSync(path.join(ROOT, 'frontend', datei), 'utf8');
    const rufe = [];
    const dom = new JSDOM(html, {
        url: 'https://localhost/', runScripts: 'outside-only', virtualConsole: new VirtualConsole(),
        beforeParse(win) {
            win.fetch = (url, init) => {
                const u = String(url).split('?')[0];
                const m = (init && init.method) || 'GET';
                const body = (init && init.body) ? JSON.parse(init.body) : null;
                rufe.push({ u, m, body, auth: init && init.headers && init.headers.Authorization });
                let r;
                try { r = api(u, m, body); } catch (e) { return Promise.reject(e); }
                const st = r.status || 200;
                return Promise.resolve({ ok: st < 400, status: st,
                    json: () => Promise.resolve(r.data) });
            };
        },
    });
    // sitzung.js zuerst, wie auf jeder Seite (tests/lib/sitzung_laden.js):
    // der Pruefstand fuehrt Module ueber eine Pfadvariable aus.
    require('./lib/sitzung_laden')(dom.window);
    dom.window.eval(I18N);
    return { dom, rufe, $: (id) => dom.window.document.getElementById(id) };
}

function klick(s, id) { s.$(id).dispatchEvent(new s.dom.window.Event('click')); }

(async () => {
    // ═════════════════════════════════════════════════════════════════════
    section('1a) Markup: zweiter Schritt in der Anmeldemaske');
    {
        const s = seite('settings.html', () => ({ data: { ok: true, anmeldungen: [] } }));
        const box = s.$('zg-schritt');
        check(!!box, 'Container #zg-schritt vorhanden');
        check(!!box && box.hidden === true, '… im Grundzustand verborgen');
        check(!!box && !!box.closest('#login-screen'), '… liegt in der Anmeldemaske');
        check(!!s.$('zg-weiter') && !!s.$('zg-ueberspringen') && !!s.$('zg-liste'),
              'Knoepfe und Liste vorhanden');
        const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
        const iZa = html.indexOf('/static/js/zugang_anmeldung.js?v=');
        const iApp = html.indexOf('/static/js/app.js?v=');
        check(iZa > 0 && iApp > 0 && iZa < iApp, 'zugang_anmeldung.js wird VOR app.js eingebunden',
              iZa + ' / ' + iApp);
        s.dom.window.close();
    }

    // ═════════════════════════════════════════════════════════════════════
    section('1b) nichts anzumelden / Fehler: es geht ohne Schritt weiter');
    for (const [name, api] of [
        ['leere Liste', () => ({ data: { ok: true, anmeldungen: [] } })],
        ['Netzfehler', () => { throw new Error('netz'); }],
        ['403', () => ({ status: 403, data: { detail: 'nein' } })],
        ['unbekanntes System', () => ({ data: { ok: true, anmeldungen: [{ system: 'xyz', art: 'token', feld: 'api_token' }] } })],
    ]) {
        const s = seite('settings.html', api);
        s.dom.window.eval(fs.readFileSync(ZA_JS, 'utf8'));
        let fertig = false;
        // Eine Ablehnung zaehlt als "nicht aufgeloest" – sie darf den Waechter
        // nicht abstuerzen lassen (sonst keine Bilanzzeile).
        s.dom.window.ZugangAnmeldung.schritt('tok').then(() => { fertig = true; }, () => {});
        await sleep(50);
        check(fertig, name + ': loest sofort auf');
        check(s.$('zg-schritt').hidden === true && s.$('login-form').hidden === false,
              name + ': kein zweiter Schritt, Formular unveraendert');
        s.dom.window.close();
    }

    // ═════════════════════════════════════════════════════════════════════
    section('1c) Anmelden: vorhandene Wege, leere Felder ausgelassen, Fehler halten den Schritt');
    {
        const EINTRAEGE = [
            { system: 'sap', art: 'kennwort', feld: 'password', benutzer: 'MUSTER', benutzer_feld: 'username' },
            { system: 'jira', art: 'token', feld: 'api_token', benutzer: '', benutzer_feld: '' },
            { system: 'confluence', art: 'token', feld: 'api_token', benutzer: '', benutzer_feld: '' },
        ];
        const s = seite('settings.html', (u, m, b) => {
            if (u === '/api/zugaenge/anmeldung') return { data: { ok: true, anmeldungen: EINTRAEGE } };
            if (u === '/api/sap/account') return { data: { ok: true, account: {} } };
            if (u === '/api/sap/test') return { data: { ok: true } };
            if (u === '/api/confluence/account/sitzung') {
                return (b && b.api_token === 'GUT') ? { data: { ok: true, account: { angemeldet: true } } }
                    : { status: 400, data: { ok: false, error: 'Confluence lehnt den Token ab: 401' } };
            }
            return { status: 404, data: { ok: false, error: 'unerwartet ' + u } };
        });
        s.dom.window.eval(fs.readFileSync(ZA_JS, 'utf8'));
        let fertig = false;
        s.dom.window.ZugangAnmeldung.schritt('tok').then(() => { fertig = true; }, () => {});
        await sleep(50);
        const box = s.$('zg-schritt');
        check(box.hidden === false, 'Schritt sichtbar');
        check(s.$('login-form').hidden === true, 'Anmeldeformular dabei verborgen');
        const zeilen = s.dom.window.document.querySelectorAll('#zg-liste .zg-zeile');
        check(zeilen.length === 3, 'eine Zeile je System', String(zeilen.length));
        const ZEILE = {};
        ['sap', 'jira', 'confluence'].forEach((k) => {
            ZEILE[k] = s.dom.window.document.querySelector('.zg-zeile[data-system="' + k + '"]');
        });
        if (!ZEILE.sap || !ZEILE.jira || !ZEILE.confluence) {
            console.log('ABBRUCH: Zeilen nicht gezeichnet – Messaufbau unbrauchbar');
            process.exit(2);
        }
        const z = (sys) => ZEILE[sys];
        const sapU = z('sap') && z('sap').querySelector('.zg-benutzer');
        check(!!sapU && sapU.value === 'MUSTER', 'SAP: Benutzer vorbelegt');
        check(!z('jira').querySelector('.zg-benutzer'), 'Jira: kein Benutzerfeld (nur Token)');
        const geheim = s.dom.window.document.querySelectorAll('#zg-liste .zg-geheim');
        check(Array.from(geheim).every((g) => g.type === 'password' && g.autocomplete === 'off'),
              'alle Geheimfelder: type=password, autocomplete=off (Merken ist offen, docs/todo.md)');

        z('sap').querySelector('.zg-geheim').value = 'pw1';
        z('confluence').querySelector('.zg-geheim').value = 'FALSCH';
        s.rufe.length = 0;
        klick(s, 'zg-weiter');
        await sleep(80);
        const wege = s.rufe.map((r) => r.m + ' ' + r.u);
        check(JSON.stringify(wege) === JSON.stringify(
            ['POST /api/sap/account', 'GET /api/sap/test', 'POST /api/confluence/account/sitzung']),
            'Reihenfolge der Aufrufe; Jira (leer) ausgelassen', JSON.stringify(wege));
        const sapPost = s.rufe.find((r) => r.u === '/api/sap/account');
        check(!!sapPost && JSON.stringify(sapPost.body) === JSON.stringify({ password: 'pw1' }),
              'SAP: nur das Kennwort, unveraenderter Benutzer wird nicht gesendet',
              sapPost && JSON.stringify(sapPost.body));
        check(s.rufe.every((r) => r.auth === 'Bearer tok'), 'jeder Aufruf mit dem frischen Token');
        check(!fertig, 'bei einem Fehler bleibt der Schritt stehen');
        check(s.$('zg-meldung').hidden === false, '… mit sichtbarer Meldung');
        check(/lehnt den Token ab/.test(z('confluence').querySelector('.zg-status').textContent),
              '… der Grund steht an der Zeile');
        check(z('sap').querySelector('.zg-status').classList.contains('is-ok')
              && z('sap').querySelector('.zg-geheim').disabled, 'SAP: angemeldet und gesperrt');
        check(Array.from(geheim).every((g) => g.value === ''), 'kein Geheimnis bleibt im Formular stehen');

        z('confluence').querySelector('.zg-geheim').value = 'GUT';
        s.rufe.length = 0;
        klick(s, 'zg-weiter');
        await sleep(80);
        check(s.rufe.length === 1 && s.rufe[0].u === '/api/confluence/account/sitzung',
              'zweiter Durchgang: nur das noch offene System', JSON.stringify(s.rufe.map((r) => r.u)));
        check(fertig, 'alle gelungen: geht weiter');
        check(box.hidden === true && s.$('login-form').hidden === false
              && s.$('zg-liste').children.length === 0, 'danach Grundzustand (fuer eine spaetere Abmeldung)');
        s.dom.window.close();
    }

    // ═════════════════════════════════════════════════════════════════════
    section('1d) geaenderter SAP-Benutzer, SAP-Test scheitert, Ueberspringen');
    {
        const s = seite('settings.html', (u) => {
            if (u === '/api/zugaenge/anmeldung') return { data: { ok: true, anmeldungen: [
                { system: 'vemas', art: 'kennwort', feld: 'password', benutzer: 'ALT', benutzer_feld: 'username' }] } };
            if (u === '/api/vemas/account') return { data: { ok: true, account: {} } };
            if (u === '/api/vemas/test') return { data: { ok: false, error: 'Anmeldung abgelehnt' } };
            return { status: 404, data: {} };
        });
        s.dom.window.eval(fs.readFileSync(ZA_JS, 'utf8'));
        let fertig = false;
        s.dom.window.ZugangAnmeldung.schritt('tok').then(() => { fertig = true; }, () => {});
        await sleep(50);
        const zeile = s.dom.window.document.querySelector('.zg-zeile[data-system="vemas"]');
        zeile.querySelector('.zg-benutzer').value = 'NEU';
        zeile.querySelector('.zg-geheim').value = 'pw';
        klick(s, 'zg-weiter');
        await sleep(80);
        const post = s.rufe.find((r) => r.u === '/api/vemas/account');
        check(!!post && post.body.username === 'NEU' && post.body.password === 'pw',
              'geaenderter Benutzer wird mitgesendet', post && JSON.stringify(post.body));
        check(!fertig && /abgelehnt/.test(zeile.querySelector('.zg-status').textContent),
              'gescheiterter Test = nicht angemeldet, Grund an der Zeile');
        s.rufe.length = 0;
        klick(s, 'zg-ueberspringen');
        await sleep(30);
        check(fertig && s.rufe.length === 0, 'Ueberspringen geht weiter, ohne etwas zu senden');
        s.dom.window.close();
    }

    // ═════════════════════════════════════════════════════════════════════
    section('2) app.js: der Schritt liegt VOR dem Weiterleiten');
    {
        const app = fs.readFileSync(APP_JS, 'utf8');
        const iErfolg = app.indexOf('} else if (data.must_change_password) {');
        // Endmarke ist der naechste Zweig nach dem Erfolg. Bis 2026-11-20 war
        // das die Admin-Einrichtung (requires_totp_setup); die gibt es an der
        // Anmeldemaske nicht mehr (Zahnrad), seitdem folgt requires_totp.
        const iTotp = app.indexOf('} else if (data.requires_totp) {');
        check(iErfolg > 0 && iTotp > iErfolg, 'Positivkontrolle: Erfolgszweig gefunden');
        const zweig = (iErfolg > 0 && iTotp > iErfolg) ? app.slice(iErfolg, iTotp) : '';
        const iSchritt = zweig.indexOf('await window.ZugangAnmeldung.schritt(token)');
        const iPortal = zweig.indexOf("window.location.replace('/portal')");
        const iSettings = zweig.indexOf('_enterSettingsPage()');
        check(iSchritt > 0, 'Erfolgszweig wartet auf den zweiten Schritt');
        check(iSchritt > 0 && iPortal > iSchritt && iSettings > iSchritt,
              '… VOR Portal-Weiterleitung und Einstellungsseite', [iSchritt, iPortal, iSettings].join('/'));
    }

    // ═════════════════════════════════════════════════════════════════════
    for (const [datei, pre, sys] of [['jira_addon.html', 'ja', 'jira'],
                                     ['confluence_addon.html', 'ca', 'confluence']]) {
        section('3) ' + datei + ': Anmeldung fuer die Sitzung');
        const pfad = '/api/' + sys + '/account/sitzung';
        let antwortAn = { angemeldet: true, sitzungs_modus: true, server_konfiguriert: true,
                          sitzung_bis: 1900000000, sitzung_anzeigename: 'Anna Beispiel' };
        const s = seite(datei, (u, m, b) => {
            if (u === pfad && m === 'POST') {
                return (b && b.api_token === 'GUT') ? { data: { ok: true, account: antwortAn } }
                    : { status: 400, data: { ok: false, error: 'lehnt den Token ab' } };
            }
            if (u === pfad && m === 'DELETE') {
                return { data: { ok: true, account: { sitzungs_modus: true, angemeldet: false,
                                                      server_konfiguriert: true } } };
            }
            return { status: 404, data: {} };
        });
        const html = fs.readFileSync(path.join(ROOT, 'frontend', datei), 'utf8');
        const iZs = html.indexOf('/static/js/zugang_sitzung.js?v=');
        const iAddon = html.indexOf('/static/js/' + datei.replace('.html', '.js') + '?v=');
        check(iZs > 0 && iAddon > iZs, 'zugang_sitzung.js wird VOR dem Seitenmodul eingebunden');
        const addon = fs.readFileSync(path.join(ROOT, 'frontend/js', datei.replace('.html', '.js')), 'utf8');
        check(addon.includes('window.ZugangSitzung.einrichten(') && addon.includes("pfad: '" + pfad + "'")
              && addon.includes('if (_sz) _sz.zeichnen(a);'),
              'Seitenmodul richtet den Abschnitt ein und zeichnet ihn aus dem Kontostand');

        s.dom.window.eval(fs.readFileSync(ZS_JS, 'utf8'));
        const nachher = [];
        const sz = s.dom.window.ZugangSitzung.einrichten({ praefix: pre, name: sys, pfad: pfad,
            token: () => 'tok', nachher: (a) => nachher.push(a) });
        const sect = s.$(pre + '-sz-sect');
        check(!!sect, 'Abschnitt vorhanden');
        check(sect.style.display === 'none', 'Grundzustand: verborgen');
        sz.zeichnen({ sitzungs_modus: false, persoenlich_erlaubt: true });
        check(sect.style.display === 'none', 'persoenliche Zugaenge erlaubt: verborgen');
        sz.zeichnen({ sitzungs_modus: true, angemeldet: false, server_konfiguriert: true });
        check(sect.style.display === '', 'Sitzungsbetrieb: sichtbar');
        check(s.$(pre + '-sz-logout').disabled === true && s.$(pre + '-sz-login').disabled === false,
              'nicht angemeldet: Abmelden gesperrt, Anmelden frei');

        s.rufe.length = 0;
        klick(s, pre + '-sz-login');
        await sleep(30);
        check(s.rufe.length === 0 && s.$(pre + '-sz-msg').hidden === false,
              'leerer Token: kein Aufruf, Meldung');
        s.$(pre + '-sz-token').value = 'FALSCH';
        klick(s, pre + '-sz-login');
        await sleep(50);
        check(/lehnt/.test(s.$(pre + '-sz-msg').textContent) && s.$(pre + '-sz-token').value === '',
              'abgelehnt: Grund sichtbar, Feld geleert');
        check(s.$(pre + '-sz-login').disabled === false, '… und erneut anmeldbar');
        s.$(pre + '-sz-token').value = 'GUT';
        s.rufe.length = 0;
        klick(s, pre + '-sz-login');
        await sleep(50);
        check(s.rufe.length === 1 && s.rufe[0].m === 'POST' && s.rufe[0].u === pfad
              && s.rufe[0].body.api_token === 'GUT', 'Anmelden: POST ' + pfad);
        check(s.$(pre + '-sz-logout').disabled === false && s.$(pre + '-sz-token').disabled === true,
              'angemeldet: Abmelden frei, Tokenfeld gesperrt');
        check(/Anna Beispiel/.test(s.$(pre + '-sz-note').textContent), 'zeigt, als wer angemeldet');
        check(nachher.length === 1, 'Seitenmodul erfaehrt den neuen Stand');
        s.rufe.length = 0;
        klick(s, pre + '-sz-logout');
        await sleep(50);
        check(s.rufe.length === 1 && s.rufe[0].m === 'DELETE' && s.rufe[0].u === pfad,
              'Abmelden: DELETE ' + pfad);
        check(s.$(pre + '-sz-logout').disabled === true, 'abgemeldet: Abmelden wieder gesperrt');
        s.dom.window.close();
    }

    console.log('\n' + '═'.repeat(70) + '\nERGEBNIS: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
