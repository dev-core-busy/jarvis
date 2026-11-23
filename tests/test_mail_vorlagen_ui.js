/* Waechter: Auswertungs-Vorlagen – Oberflaeche (Kachel E-Mail + Outlook-Add-in),
 * 2026-11-23.
 *
 * jsdom gegen die ECHTEN Dateien:
 *  1. Add-in (taskpane.html + addin.js): das Pulldown waehlt den persoenlichen
 *     Standard vor; "Auswerten" schickt die KENNUNG der Vorlage und den aus
 *     Outlook gelesenen Inhalt (nie den Vorlagentext); das Ergebnis steht
 *     danach im Fenster samt Vorlagenname; "Schliessen" raeumt es ab; ohne
 *     Vorlagen steht der Hinweis auf die Kachel da.
 *  2. Kachel (email.html + email_portal.js): gemeinsame Vorlagen tragen
 *     Stift/Muelleimer NUR fuer Administratoren; der Stern ist fuer jeden da
 *     und setzt den Standard; geloescht wird mit dem MUELLEIMER (nicht ×).
 *  3. i18n: jeder benutzte Schluessel in DE und EN.
 *
 * ADDIN_JS / PORTAL_JS legen sabotierte KOPIEN vor (Gegenprobe).
 * Aufruf: node tests/test_mail_vorlagen_ui.js
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

const ROOT = path.resolve(__dirname, '..');
const lies = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const ADDINJS = fs.readFileSync(process.env.ADDIN_JS || path.join(ROOT, 'frontend/addin/addin.js'), 'utf8');
const PORTALJS = fs.readFileSync(process.env.PORTAL_JS || path.join(ROOT, 'frontend/js/email_portal.js'), 'utf8');
const TASKPANE = lies('frontend/addin/taskpane.html');
const MAIL_HTML = lies('frontend/email.html');
const I18N = lies('frontend/js/i18n.js');
const SITZUNG = lies('frontend/js/sitzung.js');
const ICONS = lies('frontend/js/icons.js');

let ok = 0, fail = 0;
function check(b, t, d) {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d ? ' – ' + d : '')); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const VORLAGEN = {
    ok: true, darf_global: false, standard: 'g2', text_max: 2000, name_max: 60,
    eigene: [{ id: 'e1', name: 'Meine', text: 'GEHEIMER VORLAGENTEXT eigene' }],
    global: [{ id: 'g1', name: 'Zusammenfassen', text: 'GEHEIMER VORLAGENTEXT g1' },
             { id: 'g2', name: 'Kurz (Team-Leitung)', text: 'GEHEIMER VORLAGENTEXT g2' }]
};

async function baueAddin(vorlagen) {
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
        if (pfad === '/api/email/vorlagen') return gib(vorlagen);
        if (pfad === '/api/email/auswerten') {
            const b = JSON.parse((o && o.body) || '{}');
            posts.push(b);
            const name = ((vorlagen.global || []).concat(vorlagen.eigene || [])
                .filter((v) => v.id === b.vorlage)[0] || {}).name || '';
            return gib({ ok: true, text: '- Lage: Lieferung verspaetet\n- Handlung: keine', vorlage: name });
        }
        return gib({ ok: true, eintraege: [], signaturen: [], regeln: [], bereiche: [] });
    };
    w.Office = { onReady: (cb) => cb({}), CoercionType: { Text: 'text' }, context: { mailbox: {
        userProfile: { emailAddress: 'a@beispiel.de' },
        item: { itemId: 'AAA', subject: 'Lieferung', from: { emailAddress: 'x@beispiel.de' },
                body: { getAsync: (a, cb) => cb({ status: 'succeeded', value: 'INHALT AUS OUTLOOK' }) },
                displayReplyForm: () => {}, displayReplyAllForm: () => {} } } } };
    w.eval(SITZUNG); w.eval(ICONS); w.eval(I18N); w.eval(ADDINJS);
    await sleep(300);
    return { w, posts };
}

function bauePortal(vorlagen, istAdmin) {
    const dom = new JSDOM(MAIL_HTML, { url: 'https://x/email', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {} }));
    const posts = [];
    w.confirm = () => true;
    w.fetch = (url, o) => {
        o = o || {};
        const pfad = String(url).split('?')[0];
        if ((o.method || 'GET') !== 'GET') posts.push({ pfad, methode: o.method, body: o.body ? JSON.parse(o.body) : null });
        const gib = (d) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null },
                                            json: () => Promise.resolve(d) });
        if (pfad === '/api/me') return gib({ username: 'm.mustermann', is_admin: !!istAdmin,
                                             permissions: { email: true } });
        if (pfad === '/api/email/status') return gib({ ok: true, skill_aktiv: true,
            konto: { vorhanden: true, adresse: 'a@b.c', aktiv: true, stile: [], signaturen: [] },
            bereiche: [], server: { kanal: 'auto', ews: true }, grenzen: {} });
        if (pfad === '/api/email/vorlagen' && (o.method || 'GET') === 'GET') return gib(vorlagen);
        if (pfad === '/api/email/vorlagen/standard') return gib({ ok: true, standard: posts[posts.length - 1].body.id });
        if (pfad === '/api/email/rules') return gib({ ok: true, regeln: [], bereiche: [] });
        if (pfad === '/api/email/log') return gib({ ok: true, eintraege: [] });
        return gib({ ok: true });
    };
    w.eval(SITZUNG); w.eval(I18N); w.eval(SITZUNG); w.eval(ICONS); w.eval(SITZUNG); w.eval(PORTALJS);
    return { w, posts };
}

(async () => {
    console.log('\n1. Add-in: Auswerten');
    {
        const { w, posts } = await baueAddin(VORLAGEN);
        // Messaufbau: der Nachrichten-Reiter ist gezeichnet (der Antwort-Knopf
        // daneben steht da). Fehlt NUR der Auswerten-Block, ist das ein BEFUND
        // (FAIL), kein "konnte nicht laufen".
        if (!w.document.getElementById('ad-reply-make')) {
            console.log('ABBRUCH: Nachrichten-Reiter nicht gezeichnet (Messaufbau)'); process.exit(2);
        }
        let sel = w.document.getElementById('ad-eval-vorl');
        check(!!sel && !!w.document.getElementById('ad-eval-run'), 'Auswerten-Block steht im Reiter');
        if (!sel) { console.log('\nErgebnis: ' + ok + ' OK, ' + (fail) + ' FAIL'); process.exit(1); }
        check(sel.options.length === 3, 'alle Vorlagen im Pulldown', String(sel.options.length));
        check(sel.value === 'g2', 'persoenlicher Standard ist vorausgewaehlt', sel.value);
        // Eine andere waehlen, dann den Reiter NEU ZEICHNEN lassen (Sprachwechsel)
        // – erst danach klicken: so misst die Probe das Merken der Wahl selbst.
        sel.value = 'g1';
        sel.dispatchEvent(new w.Event('change'));
        w.document.getElementById('ad-lang').click();
        await sleep(300);
        sel = w.document.getElementById('ad-eval-vorl');
        check(!!sel && sel.value === 'g1', 'Wahl ueberlebt ein Neuzeichnen vor dem Klick',
              sel ? sel.value : '(fehlt)');
        w.document.getElementById('ad-eval-run').click();
        await sleep(300);
        check(posts.length === 1, 'genau ein Aufruf an /api/email/auswerten', String(posts.length));
        const b = posts[0] || {};
        check(b.vorlage === 'g1', 'gewaehlte Kennung wird geschickt', String(b.vorlage));
        check(b.nachricht && b.nachricht.text === 'INHALT AUS OUTLOOK',
              'Inhalt kommt aus Outlook', JSON.stringify(b.nachricht || {}));
        check(JSON.stringify(b).indexOf('GEHEIMER VORLAGENTEXT') < 0,
              'der Vorlagentext geht NICHT mit (nur die Kennung)');
        check(Object.keys(b).sort().join(',') === 'lang,nachricht,postfach,vorlage',
              'Rumpf traegt genau Kennung, Nachricht, Postfach, Sprache', Object.keys(b).join(','));
        const ta = w.document.getElementById('ad-eval-text');
        check(!!ta && ta.value.indexOf('Lieferung verspaetet') >= 0 && ta.readOnly,
              'Ergebnis steht schreibgeschuetzt im Fenster', ta ? ta.value : '(fehlt)');
        check(/Zusammenfassen/.test(w.document.getElementById('ad-msg-box').textContent),
              'benutzte Vorlage wird genannt');
        check(w.document.getElementById('ad-eval-vorl').value === 'g1',
              'Wahl ueberlebt das Neuzeichnen');
        const zu = w.document.getElementById('ad-eval-close');
        if (zu) zu.click();
        await sleep(50);
        check(!w.document.getElementById('ad-eval-text'), 'Schliessen raeumt das Ergebnis ab');
        w.close();
    }
    {
        const { w } = await baueAddin({ ok: true, eigene: [], global: [], standard: '' });
        const box = w.document.getElementById('ad-msg-box');
        check(!w.document.getElementById('ad-eval-run') && /Kachel/.test(box ? box.textContent : ''),
              'ohne Vorlagen: kein Knopf, Hinweis auf die Kachel');
        w.close();
    }

    console.log('\n2. Kachel E-Mail: Verwaltung');
    for (const admin of [false, true]) {
        // Was ein Admin darf, sagt der SERVER (`darf_global`), nicht /api/me –
        // die Attrappe muss beides passend liefern.
        const { w, posts } = bauePortal(Object.assign({}, VORLAGEN, { darf_global: admin }), admin);
        await sleep(300);
        const karte = (id) => w.document.querySelector('#em-vorl-list [data-vorl="' + id + '"]');
        // Messaufbau: die Seite ist angemeldet aufgebaut (App sichtbar, Karte
        // im Markup). Eine LEERE Liste danach ist ein Befund, kein Abbruch.
        const app = w.document.getElementById('em-app');
        if (!app || app.classList.contains('hidden') || !w.document.getElementById('em-vorl-list')) {
            console.log('ABBRUCH: /email nicht aufgebaut (Messaufbau)'); process.exit(2);
        }
        check(!!karte('e1') && !!karte('g1'), (admin ? 'Admin' : 'Benutzer') + ': Vorlagenliste gezeichnet');
        if (!karte('e1') || !karte('g1')) { w.close(); continue; }
        const wer = admin ? 'Admin' : 'Benutzer';
        check(!!karte('e1').querySelector('[data-act="edit"]') && !!karte('e1').querySelector('[data-act="del"]'),
              wer + ': eigene Vorlage bearbeitbar und loeschbar');
        const gEdit = !!karte('g1').querySelector('[data-act="edit"]');
        const gDel = !!karte('g1').querySelector('[data-act="del"]');
        check(gEdit === admin && gDel === admin,
              wer + ': gemeinsame Vorlage ' + (admin ? 'MIT' : 'OHNE') + ' Stift/Muelleimer',
              'edit=' + gEdit + ' del=' + gDel);
        check(!!karte('g1').querySelector('[data-act="std"]'), wer + ': Stern auch an gemeinsamer Vorlage');
        check(!!karte('g2').querySelector('.jv-ico-star.is-gesetzt') && !karte('g1').querySelector('.jv-ico-star.is-gesetzt'),
              wer + ': Stern gefuellt genau beim Standard');
        const del = karte('e1').querySelector('[data-act="del"]');
        check(!!del && !!del.querySelector('.jv-ico-trash') && del.textContent.indexOf('✕') < 0,
              wer + ': Loeschen mit Muelleimer, nicht mit ×');
        check(!!w.document.getElementById('em-v-global') === false,
              wer + ': kein offenes Formular vor dem Klick');
        if (!admin) {
            karte('g1').querySelector('[data-act="std"]').click();
            await sleep(100);
            const p = posts.filter((x) => x.pfad === '/api/email/vorlagen/standard')[0];
            check(!!p && p.body && p.body.id === 'g1', 'Stern setzt den Standard', JSON.stringify(p || {}));
            check(!!karte('g1').querySelector('.jv-ico-star.is-gesetzt'), 'Stern danach gefuellt');
            w.document.getElementById('em-vorl-neu').click();
            check(!w.document.getElementById('em-v-global'), 'Benutzer: kein Haken „für alle“ im Formular');
        } else {
            w.document.getElementById('em-vorl-neu').click();
            check(!!w.document.getElementById('em-v-global'), 'Admin: Haken „für alle“ im Formular');
        }
        w.close();
    }

    console.log('\n3. Texte in beiden Sprachen');
    {
        const grenze = I18N.search(/\n\s*en\s*:\s*\{/);
        const bl = { de: I18N.slice(0, grenze), en: I18N.slice(grenze) };
        const quelle = ADDINJS + PORTALJS + MAIL_HTML;
        const schl = new Set();
        (quelle.match(/['"](mvorl\.[a-z_]+|addin\.eval_[a-z_]+)['"]/g) || [])
            .forEach((m) => schl.add(m.slice(1, -1)));
        (MAIL_HTML.match(/data-i18n(?:-html)?="(mvorl\.[a-z_]+)"/g) || [])
            .forEach((m) => schl.add(m.replace(/.*="|"$/g, '')));
        const fehlt = [];
        schl.forEach((k) => ['de', 'en'].forEach((lg) => {
            if (bl[lg].indexOf("'" + k + "':") < 0) fehlt.push(lg + ':' + k);
        }));
        check(grenze > 0 && schl.size >= 20, 'Positivkontrolle: Schluessel gefunden', String(schl.size));
        check(fehlt.length === 0, 'jeder Schluessel in DE und EN', fehlt.join(', '));
    }

    console.log('\n' + '='.repeat(46));
    console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
