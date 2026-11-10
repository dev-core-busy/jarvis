/* Waechter: "Eigenen Zugang entfernen" in /sap und /vemas (2026-11-10).
 *
 * GEMELDET: der Knopf stand unter "Mein SAP-Zugang" immer da – auch ohne
 * hinterlegten Zugang –, und ein Klick meldete dann "Eigener Zugang entfernt.".
 *
 * jsdom gegen die ECHTEN Dateien (frontend/sap.html + js/sap_portal.js,
 * frontend/vemas.html + js/vemas_portal.js) mit gemockter API. Gemessen wird
 * das VERHALTEN:
 *   - der Knopf ist im Markup verborgen vorbelegt und folgt danach dem Feld
 *     `gespeichert` der Kontoauskunft (nicht `vorhanden`); fehlt das Feld
 *     (aelterer Dienst), bleibt er sichtbar
 *   - "entfernt" steht nur da, wenn der Server etwas entfernt hat; `removed:
 *     false` und ein Fehler haben je eine eigene Meldung, und bei einem Fehler
 *     bleiben die Felder stehen
 *   - /sap: ein verankertes Zertifikat legt den Datensatz an – der Knopf folgt
 *
 * NICHT hier messbar: ob `hidden` im Browser den Knopf wirklich verbirgt (die
 * Knopfklasse setzt `display: flex`, jsdom rechnet die Kaskade nicht) – das
 * misst tests/test_zugang_knopf_chrome.py.
 *
 * SAP_PORTAL_JS / VEMAS_PORTAL_JS / ZUGANG_SAP_HTML / ZUGANG_VEMAS_HTML /
 * ZUGANG_I18N legen sabotierte KOPIEN vor (Gegenprobe tests/gegen_zugang_entfernen.py).
 * Aufruf: node tests/test_zugang_entfernen_ui.js
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const lies = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const SITZUNG = lies('frontend/js/sitzung.js');
const I18N = process.env.ZUGANG_I18N ? fs.readFileSync(process.env.ZUGANG_I18N, 'utf8')
                                     : lies('frontend/js/i18n.js');
const ICONS = lies('frontend/js/icons.js');
const SAPCERT = lies('frontend/js/sapcert.js');

let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
function abbruch(t) { console.log('ABBRUCH: ' + t); process.exit(2); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PORTALE = {
    sap: {
        titel: '/sap',
        html: process.env.ZUGANG_SAP_HTML || path.join(ROOT, 'frontend', 'sap.html'),
        js: process.env.SAP_PORTAL_JS || path.join(ROOT, 'frontend', 'js', 'sap_portal.js'),
        api: '/api/sap', pre: 'sp', feld: 'sp-acc-od-user', zert: true,
        konto: { vorhanden: true, connection_type: 'odata', aktiv: true, username: 'MUSTER',
                 odata_base_url: 'https://s4.firma.local/sap/opu/odata', auth_kind: 'basic',
                 passwort_gesetzt: true, hana_port: 443, erlaubte_hosts: ['firma.local'],
                 host_ok: true, cert: {}, letzter_fehler: '', ausgesetzt: false },
        leer: { vorhanden: false, connection_type: '', aktiv: true, username: '',
                hana_port: 443, erlaubte_hosts: ['firma.local'], host_ok: true, cert: {},
                letzter_fehler: '', ausgesetzt: false },
    },
    vemas: {
        titel: '/vemas',
        html: process.env.ZUGANG_VEMAS_HTML || path.join(ROOT, 'frontend', 'vemas.html'),
        js: process.env.VEMAS_PORTAL_JS || path.join(ROOT, 'frontend', 'js', 'vemas_portal.js'),
        api: '/api/vemas', pre: 'vm', feld: 'vm-acc-user', zert: false,
        konto: { vorhanden: true, auth_kind: 'basic', aktiv: true, username: 'MUSTER',
                 passwort_gesetzt: true, letzter_fehler: '', ausgesetzt: false,
                 server: 'https://vemas.beispiel.de/api', server_konfiguriert: true },
        leer: { vorhanden: false, auth_kind: '', aktiv: true, username: '',
                letzter_fehler: '', ausgesetzt: false,
                server: 'https://vemas.beispiel.de/api', server_konfiguriert: true },
    },
};

/** Portalseite mit gemockter API.
 *  opts.konto     – Kontoauskunft beim Laden
 *  opts.loeschen  – { status, body } der DELETE-Antwort
 *  opts.kontoNach – Kontoauskunft NACH einem gelungenen DELETE */
async function seite(p, opts) {
    const st = { konto: opts.konto, dels: 0, fragen: 0, zert: [] };
    const dom = new JSDOM(fs.readFileSync(p.html, 'utf8'), {
        url: 'https://localhost' + p.titel, runScripts: 'outside-only',
        virtualConsole: new VirtualConsole(),
        beforeParse(win) {
            win.localStorage.setItem('jarvis_token', 'testtoken');
            win.HTMLCanvasElement.prototype.getContext = () => null;
            win.confirm = () => { st.fragen++; return true; };
            win.fetch = (url, init) => {
                const u = String(url).split('?')[0];
                const json = (data, status) => Promise.resolve({
                    ok: (status || 200) < 400, status: status || 200,
                    json: () => Promise.resolve(data), text: () => Promise.resolve(JSON.stringify(data)) });
                if (u === '/api/me') return json({ username: 'anna', permissions: { sap: true, vemas: true } });
                if (u === p.api + '/status') return json({ ok: true, configured: true, quelle: 'persoenlich' });
                if (u === p.api + '/account') {
                    if (init && init.method === 'DELETE') {
                        st.dels++;
                        const a = opts.loeschen || { status: 200, body: { ok: true, removed: true } };
                        if (a.body && a.body.ok && opts.kontoNach) st.konto = opts.kontoNach;
                        return json(a.body, a.status);
                    }
                    return json({ ok: true, account: st.konto });
                }
                if (u === p.api + '/analyses') {
                    return json({ ok: true, lang: 'de', categories: [], analyses: [], bi_tools: [] });
                }
                if (u === p.api + '/reporting-endpoints') return json({ ok: true, endpoints: [] });
                return json({ ok: true });
            };
        },
    });
    const win = dom.window;
    win.eval(SITZUNG);
    win.eval(I18N);
    win.eval(ICONS);
    if (p.zert) {
        // Das ECHTE Modul, nur mit einem Mithoerer davor: so ist die Signatur
        // von mount() die wirkliche, und der Test bekommt die Rueckrufe.
        win.eval(SAPCERT);
        if (!win.SapCert || typeof win.SapCert.mount !== 'function') abbruch('SapCert.mount fehlt');
        const echt = win.SapCert.mount;
        win.SapCert.mount = function (box, o) { st.zert.push(o); return echt.apply(this, arguments); };
    }
    win.eval(fs.readFileSync(p.js, 'utf8'));
    await sleep(200);
    const $ = (id) => win.document.getElementById(id);
    return { win, $, st, knopf: $(p.pre + '-acc-del'), note: $(p.pre + '-acc-status'), feld: $(p.feld) };
}

async function portal(name) {
    const p = PORTALE[name];
    const mit = (x) => Object.assign({}, p.konto, x);
    const ohne = (x) => Object.assign({}, p.leer, x);

    console.log('\n' + p.titel + ' – 0. Positivkontrolle: Seite geladen, Zugang eingetragen');
    {
        const s = await seite(p, { konto: mit({ gespeichert: true }) });
        if (!s.knopf || s.knopf.tagName !== 'BUTTON') abbruch(p.titel + ': Knopf ' + p.pre + '-acc-del fehlt');
        if (!s.note || !s.feld) abbruch(p.titel + ': Statuszeile oder Benutzerfeld fehlt');
        if (s.feld.value !== 'MUSTER') {
            abbruch(p.titel + ': die Kontoauskunft kam im Formular nicht an (' + JSON.stringify(s.feld.value)
                    + ') – die Seite ist nicht geladen, alles Weitere waere trivial');
        }
        check(true, 'Formular traegt den Benutzer aus der Kontoauskunft');
        s.win.close();
    }

    console.log('\n' + p.titel + ' – 1. Sichtbarkeit folgt `gespeichert`');
    {
        const roh = new JSDOM(fs.readFileSync(p.html, 'utf8'));
        const k = roh.window.document.getElementById(p.pre + '-acc-del');
        check(!!k && k.hasAttribute('hidden'), 'im Markup verborgen vorbelegt (kein Aufblitzen vor der Auskunft)');
        roh.window.close();

        const faelle = [
            ['nichts hinterlegt -> verborgen', ohne({ gespeichert: false }), true],
            ['Zugang hinterlegt -> sichtbar', mit({ gespeichert: true }), false],
            ['halb ausgefuellt (vorhanden false, gespeichert true) -> sichtbar',
             mit({ vorhanden: false, gespeichert: true }), false],
            ['`vorhanden` allein macht ihn nicht sichtbar', mit({ vorhanden: true, gespeichert: false }), true],
            ['Feld fehlt (aelterer Dienst) -> sichtbar, nicht weggenommen', mit({}), false],
        ];
        for (const [text, konto, verborgen] of faelle) {
            const s = await seite(p, { konto });
            check(s.knopf.hidden === verborgen, text, 'hidden=' + s.knopf.hidden);
            s.win.close();
        }
    }

    console.log('\n' + p.titel + ' – 2. Entfernen: die Antwort entscheidet ueber die Meldung');
    const T = { weg: name + '.acc_removed', nichts: name + '.acc_none_stored' };
    {
        const s = await seite(p, { konto: mit({ gespeichert: true }), kontoNach: ohne({ gespeichert: false }) });
        const t = (k) => s.win.t(k);
        if (t(T.weg) === T.weg) abbruch(p.titel + ': i18n-Text ' + T.weg + ' fehlt – Vergleich waere leer');
        s.knopf.click();
        await sleep(160);
        check(s.st.fragen === 1 && s.st.dels === 1, 'eine Rueckfrage, genau ein DELETE',
              'fragen=' + s.st.fragen + ' dels=' + s.st.dels);
        check(s.note.textContent === t(T.weg) && /\bis-ok\b/.test(s.note.className),
              'entfernt -> "' + t(T.weg) + '" als Erfolg', JSON.stringify(s.note.textContent));
        check(s.knopf.hidden === true, 'danach ist der Knopf verborgen');
        check(s.feld.value === '', 'und das Formular leer', JSON.stringify(s.feld.value));
        s.win.close();
    }
    {
        const s = await seite(p, { konto: mit({ gespeichert: true }), kontoNach: ohne({ gespeichert: false }),
                                   loeschen: { status: 200, body: { ok: true, removed: false } } });
        const t = (k) => s.win.t(k);
        s.knopf.click();
        await sleep(160);
        check(s.st.dels === 1, 'Positivkontrolle: der DELETE ging hinaus', String(s.st.dels));
        check(t(T.nichts) !== T.nichts && s.note.textContent === t(T.nichts),
              'removed:false -> "es war nichts hinterlegt"', JSON.stringify(s.note.textContent));
        check(s.note.textContent !== t(T.weg) && !/\bis-ok\b/.test(s.note.className),
              'removed:false meldet NICHT "entfernt"', s.note.className);
        s.win.close();
    }
    for (const [text, antwort, erwartet] of [
        ['Serverfehler (500 mit Grund)', { status: 500, body: { ok: false, error: 'Datei gesperrt' } }, 'Datei gesperrt'],
        ['Abweisung (403 ohne ok-Feld)', { status: 403, body: { detail: 'Kein Zugriff' } }, ''],
    ]) {
        const s = await seite(p, { konto: mit({ gespeichert: true }), loeschen: antwort });
        const t = (k) => s.win.t(k);
        s.knopf.click();
        await sleep(160);
        check(s.st.dels === 1 && /\bis-error\b/.test(s.note.className)
              && s.note.textContent.indexOf(erwartet) >= 0 && s.note.textContent.trim() !== '',
              text + ' -> Fehlermeldung' + (erwartet ? ' mit Grund' : ''),
              JSON.stringify(s.note.textContent) + ' / ' + s.note.className);
        check(s.note.textContent !== t(T.weg) && s.note.textContent !== t(T.nichts),
              text + ' -> kein "entfernt"');
        check(s.feld.value === 'MUSTER' && s.knopf.hidden === false,
              text + ' -> Formular und Knopf bleiben stehen',
              JSON.stringify(s.feld.value) + ' hidden=' + s.knopf.hidden);
        s.win.close();
    }

    if (p.zert) {
        console.log('\n' + p.titel + ' – 3. Verankertes Zertifikat legt den Datensatz an');
        const s = await seite(p, { konto: ohne({ gespeichert: false, connection_type: 'odata' }) });
        const ruf = s.st.zert.find((o) => o && typeof o.nachAenderung === 'function');
        if (!ruf) abbruch(p.titel + ': SapCert.mount bekam keinen Rueckruf nachAenderung');
        check(s.knopf.hidden === true, 'Positivkontrolle: vorher verborgen');
        ruf.nachAenderung({ account: ohne({ gespeichert: true, connection_type: 'odata' }) });
        check(s.knopf.hidden === false, 'nach dem Verankern sichtbar – ohne Neuladen der Seite');
        s.win.close();
    }

    console.log('\n' + p.titel + ' – ' + (p.zert ? 4 : 3) + '. Texte in beiden Sprachen');
    {
        const s = await seite(p, { konto: mit({ gespeichert: true }) });
        const de = s.win.t(T.nichts);
        s.win._lang = 'en';
        const en = s.win.t(T.nichts);
        check(de !== T.nichts && en !== T.nichts && de !== en, T.nichts + ' in DE und EN', de + ' / ' + en);
        s.win.close();
    }
}

(async () => {
    await portal('sap');
    await portal('vemas');
    console.log('\n' + '='.repeat(46));
    console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
