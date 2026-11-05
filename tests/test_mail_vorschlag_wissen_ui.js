/* Waechter: Wissensdatenbank beim Antwortvorschlag – Anzeige im Outlook-Add-in
 * (2026-11-05).
 *
 * jsdom gegen die ECHTEN Dateien (taskpane.html + addin/addin.js): nach einem
 * Klick auf "Antwort vorschlagen" sagt das Fenster, ob die Wissensdatenbank
 * befragt wurde – mit der Zahl vom Server, "nicht nachgeschlagen" als Auskunft,
 * und GAR NICHTS, wenn sie nicht zur Verfuegung stand (eine Anzeige darf keinen
 * Zustand behaupten, den sie nicht kennt).
 *
 * ADDIN_JS legt eine sabotierte KOPIE vor (gegen_mail_vorschlag_wissen.py).
 * Aufruf: node tests/test_mail_vorschlag_wissen_ui.js
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

const ROOT = path.resolve(__dirname, '..');
const ADDINJS = fs.readFileSync(process.env.ADDIN_JS || path.join(ROOT, 'frontend/addin/addin.js'), 'utf8');
const TASKPANE = fs.readFileSync(path.join(ROOT, 'frontend/addin/taskpane.html'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const SITZUNG = fs.readFileSync(path.join(ROOT, 'frontend/js/sitzung.js'), 'utf8');
const ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');
let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function vorschlagMit(antwort) {
    const dom = new JSDOM(TASKPANE, { url: 'https://x/addin/taskpane.html', runScripts: 'outside-only' });
    const w = dom.window;
    sitzungLaden(w);
    w.localStorage.setItem('jarvis_token', 'T');
    const KONTO = { vorhanden: true, adresse: 'a@beispiel.de', aktiv: true, kanal: 'ews',
                    passwort_gesetzt: true, antwort_format: 'html', stile: [], signaturen: [],
                    server_zugriff: false };
    const posts = [];
    w.fetch = (u, o) => {
        const pfad = String(u).split('?')[0];
        const gib = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(d) });
        if (pfad === '/api/me') return gib({ username: 'a', is_admin: false, permissions: { email: true } });
        if (pfad === '/api/email/status') return gib({ ok: true, regeln: 0, bereiche: [], server: { ews: true },
            grenzen: {}, konto: KONTO });
        if (pfad === '/api/email/account') return gib({ ok: true, konto: KONTO });
        if (pfad === '/api/email/reply/preview') {
            posts.push(JSON.parse((o && o.body) || '{}'));
            return gib(Object.assign({ ok: true, text: 'Hallo,\nDanke.', an: 'x@beispiel.de',
                                       betreff: 'Frage', stil: '', stil_id: '', stil_quelle: '',
                                       stil_hinweis: '' }, antwort));
        }
        return gib({ ok: true, eintraege: [], signaturen: [], regeln: [], bereiche: [] });
    };
    w.Office = { onReady: (cb) => cb({}), CoercionType: { Text: 'text' }, context: { mailbox: {
        userProfile: { emailAddress: 'a@beispiel.de' },
        item: { itemId: 'AAA', subject: 'Frage', from: { emailAddress: 'x@beispiel.de' },
                body: { getAsync: (a, cb) => cb({ status: 'succeeded', value: 'Wie geht das?' }) },
                displayReplyForm: () => {}, displayReplyAllForm: () => {} } } } };
    w.eval(SITZUNG); w.eval(ICONS); w.eval(I18N); w.eval(ADDINJS);
    await sleep(250);
    const knopf = w.document.getElementById('ad-reply-make');
    if (!knopf) { console.log('ABBRUCH: Knopf "Antwort vorschlagen" fehlt'); process.exit(2); }
    knopf.click();
    await sleep(250);
    if (!posts.length || !w.document.getElementById('ad-reply-text')) {
        console.log('ABBRUCH: Vorschlag kam nicht an (Messaufbau)'); process.exit(2);
    }
    return w;
}

(async () => {
    console.log('\n1. Anzeige der Wissensdatenbank im Vorschlag');
    {
        const w = await vorschlagMit({ wissen: true, wissen_suchen: 2 });
        const el = w.document.getElementById('ad-reply-wissen');
        check(!!el && /2×/.test(el.textContent) && /nachgeschlagen/.test(el.textContent),
              'befragt: Zahl vom Server steht da', el ? el.textContent : '(fehlt)');
        w.close();
    }
    {
        const w = await vorschlagMit({ wissen: true, wissen_suchen: 0 });
        const el = w.document.getElementById('ad-reply-wissen');
        check(!!el && /nicht nachgeschlagen/.test(el.textContent),
              'verfuegbar, nicht befragt: sagt das ausdruecklich', el ? el.textContent : '(fehlt)');
        w.close();
    }
    {
        const w = await vorschlagMit({ wissen: false, wissen_suchen: 0 });
        check(!w.document.getElementById('ad-reply-wissen'),
              'nicht freigegeben: keine Zeile (nichts behaupten)');
        w.close();
    }
    {
        // Aelteres Backend ohne Feld: ebenfalls keine Zeile.
        const w = await vorschlagMit({});
        check(!w.document.getElementById('ad-reply-wissen'), 'ohne Feld: keine Zeile');
        w.close();
    }

    console.log('\n2. Texte in beiden Sprachen');
    {
        const grenze = I18N.search(/\n\s*en\s*:\s*\{/);
        const bl = { de: I18N.slice(0, grenze), en: I18N.slice(grenze) };
        const fehlt = [];
        ['addin.reply_wissen_n', 'addin.reply_wissen_0'].forEach((k) => ['de', 'en'].forEach((lg) => {
            if (bl[lg].indexOf("'" + k + "':") < 0) fehlt.push(lg + ':' + k);
        }));
        check(grenze > 0 && fehlt.length === 0, 'Schluessel in DE und EN', fehlt.join(', '));
    }

    console.log('\n' + '='.repeat(46));
    console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
