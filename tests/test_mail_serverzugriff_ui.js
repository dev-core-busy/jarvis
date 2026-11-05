/* Waechter: Outlook-Umbau, Punkt e (2026-11-05) – Oberflaeche.
 *
 * jsdom gegen die ECHTEN Dateien:
 *   1. Outlook-Add-in (taskpane.html + addin/addin.js): ohne Serverzugriff steht
 *      der Hinweis in Regeln/Postfach/Protokoll und im Nachricht-Reiter, der
 *      Antwortvorschlag bleibt trotzdem bedienbar; mit Serverzugriff kein Hinweis.
 *   2. Einstellungen → E-Mail (settings.html + js/email.js): die Auswahl zeigt die
 *      Kandidaten samt Markierungen, speichert genau die angehakten, zeigt eine
 *      Ablehnung mit Namen an.
 *
 * ADDIN_JS / EMAIL_JS legen sabotierte KOPIEN vor (gegen_mail_serverzugriff.py).
 * Aufruf: node tests/test_mail_serverzugriff_ui.js
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

const ROOT = path.resolve(__dirname, '..');
const ADDINJS = fs.readFileSync(process.env.ADDIN_JS || path.join(ROOT, 'frontend/addin/addin.js'), 'utf8');
const EMAILJS = fs.readFileSync(process.env.EMAIL_JS || path.join(ROOT, 'frontend/js/email.js'), 'utf8');
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

async function addin(serverZugriff) {
    const dom = new JSDOM(TASKPANE, { url: 'https://x/addin/taskpane.html', runScripts: 'outside-only' });
    const w = dom.window;
    sitzungLaden(w);
    w.localStorage.setItem('jarvis_token', 'T');
    const KONTO = { vorhanden: true, adresse: 'a@b.de', aktiv: true, kanal: 'ews', passwort_gesetzt: true,
                    antwort_format: 'html', stile: [], signaturen: [], server_zugriff: serverZugriff };
    w.fetch = (u) => {
        const pfad = String(u).split('?')[0];
        const gib = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(d) });
        if (pfad === '/api/me') return gib({ username: 'a', is_admin: false, permissions: { email: true } });
        if (pfad === '/api/email/status') return gib({ ok: true, regeln: 1, bereiche: [], server: { ews: true },
            grenzen: {}, konto: KONTO });
        if (pfad === '/api/email/account') return gib({ ok: true, konto: KONTO });
        if (pfad === '/api/email/rules') return gib({ ok: true, regeln: [{ id: 'r1', name: 'Eins', enabled: true }], bereiche: [] });
        return gib({ ok: true, eintraege: [], signaturen: [] });
    };
    w.Office = { onReady: (cb) => cb({}), CoercionType: { Text: 'text' }, context: { mailbox: {
        userProfile: { emailAddress: 'a@b.de' },
        item: { itemId: 'AAA', subject: 'S', from: { emailAddress: 'x@y.de' },
                body: { getAsync: (a, cb) => cb({ status: 'succeeded', value: 'Text' }) },
                displayReplyForm: () => {}, displayReplyAllForm: () => {} } } } };
    w.eval(SITZUNG); w.eval(ICONS); w.eval(I18N); w.eval(ADDINJS);
    await sleep(250);
    return w;
}

(async () => {
    console.log('\n1. Outlook-Add-in');
    {
        const w = await addin(false);
        const d = w.document;
        const hinweise = Array.from(d.querySelectorAll('.ad-noserver'));
        if (hinweise.length < 3 || !d.getElementById('ad-msg-box')) {
            console.log('ABBRUCH: Markup fehlt (ad-noserver/ad-msg-box)'); process.exit(2);
        }
        check(hinweise.every((h) => !h.classList.contains('hidden')),
              'ohne Serverzugriff: Hinweis in Regeln, Postfach und Protokoll sichtbar',
              hinweise.map((h) => h.className).join(' | '));
        const box = d.getElementById('ad-msg-box').textContent;
        check(/Der Server greift für dich nicht/.test(box), 'Nachricht-Reiter: Regel-Abschnitt nennt den Grund');
        check(!d.getElementById('ad-run-msg'), 'kein "Jetzt verarbeiten" ohne Serverzugriff');
        check(!!d.getElementById('ad-reply-make'), 'Antwort vorschlagen bleibt bedienbar');
        w.close();
    }
    {
        const w = await addin(true);
        const d = w.document;
        check(Array.from(d.querySelectorAll('.ad-noserver')).every((h) => h.classList.contains('hidden')),
              'mit Serverzugriff: kein Hinweis');
        check(!!d.getElementById('ad-run-msg'), 'mit Serverzugriff: "Jetzt verarbeiten" da');
        w.close();
    }

    console.log('\n2. Einstellungen → E-Mail: Auswahl');
    const KAND = [
        { benutzer: 'm.mustermann', anzeige: 'Max Mustermann', gewaehlt: true, postfach: true, berechtigt: true },
        { benutzer: 'e.beispiel', anzeige: 'Erika Beispiel', gewaehlt: false, postfach: false, berechtigt: true },
        { benutzer: 'x.alt', anzeige: 'X Alt', gewaehlt: true, postfach: true, berechtigt: false },
    ];
    async function reiter(postAntwort) {
        const html = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
        const posts = [];
        const s = new JSDOM(html, { url: 'https://localhost/settings', runScripts: 'outside-only',
            beforeParse(win) {
                win.localStorage.setItem('jarvis_token', 'T');
                win.fetch = (u, o) => {
                    const pfad = String(u).split('?')[0];
                    const gib = (d, st) => Promise.resolve({ ok: (st || 200) < 400, status: st || 200,
                        json: () => Promise.resolve(d) });
                    if (pfad === '/api/email/admin/serverzugriff') {
                        if (o && o.method === 'POST') { posts.push(JSON.parse(o.body)); return gib(postAntwort[0], postAntwort[1]); }
                        return gib({ ok: true, kandidaten: KAND });
                    }
                    if (pfad === '/api/email/admin/overview') return gib({ ok: true, bereiche: [], konten: [] });
                    return gib({ ok: true, config: {} });
                };
            } });
        s.window.eval(SITZUNG); s.window.eval(I18N); s.window.eval(SITZUNG);
        s.window.eval(EMAILJS);
        s.window.EmailAdmin.onShow();
        await sleep(150);
        return { s, posts, $: (id) => s.window.document.getElementById(id) };
    }
    {
        const e = await reiter([{ ok: true, gewaehlt: ['e.beispiel'] }, 200]);
        const cbs = Array.from(e.s.window.document.querySelectorAll('#em-server-liste .em-server-cb'));
        if (!cbs.length) { console.log('ABBRUCH: Auswahl nicht gerendert'); process.exit(2); }
        check(cbs.length === 3, 'drei Kandidaten', String(cbs.length));
        check(cbs[0].checked && !cbs[1].checked && cbs[2].checked, 'Haken entsprechen der Auswahl');
        const txt = e.$('em-server-liste').textContent;
        check(/kein Postfach hinterlegt/.test(txt) && /keine E-Mail-Berechtigung mehr/.test(txt),
              'Markierungen: ohne Postfach / ohne Berechtigung', txt);
        cbs[0].checked = false; cbs[1].checked = true; cbs[2].checked = false;
        e.$('em-server-save').click();
        await sleep(100);
        check(e.posts.length === 1 && JSON.stringify(e.posts[0].benutzer) === '["e.beispiel"]',
              'Speichern sendet genau die angehakten', JSON.stringify(e.posts));
        check(/✓/.test(e.$('em-server-status').textContent), 'Erfolg wird gemeldet', e.$('em-server-status').textContent);
        e.s.window.close();
    }
    {
        const e = await reiter([{ ok: false, error: 'Ohne E-Mail-Berechtigung (…): x.alt' }, 400]);
        e.$('em-server-save').click();
        await sleep(100);
        check(/x\.alt/.test(e.$('em-server-status').textContent),
              'Ablehnung nennt den Namen', e.$('em-server-status').textContent);
        e.s.window.close();
    }

    console.log('\n3. Texte in beiden Sprachen');
    {
        const grenze = I18N.search(/\n\s*en\s*:\s*\{/);
        const bl = { de: I18N.slice(0, grenze), en: I18N.slice(grenze) };
        const keys = ['addin.no_server', 'addin.no_body', 'addin.reply_outlook', 'addin.reply_outlook_all',
            'addin.reply_opened', 'addin.reply_no_form', 'mailadm.sect_server', 'mailadm.server_hint',
            'mailadm.server_none', 'mailadm.server_no_box', 'mailadm.server_no_right', 'mail.no_server_access'];
        const fehlt = [];
        keys.forEach((k) => ['de', 'en'].forEach((lg) => { if (bl[lg].indexOf("'" + k + "':") < 0) fehlt.push(lg + ':' + k); }));
        check(grenze > 0 && fehlt.length === 0, 'Schluessel in DE und EN', fehlt.join(', '));
    }

    console.log('\n' + '='.repeat(46));
    console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
