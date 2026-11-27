#!/usr/bin/env node
/**
 * Office-Add-ins (Outlook, Excel): Anmeldung ueber das Firmenkonto (IdP).
 *
 * Gemessen wird der ABLAUF, nicht der Quelltext: die ECHTE taskpane.html, die
 * ECHTEN Module (sitzung.js, i18n.js, office_idp.js, addin.js bzw. excel.js)
 * laufen in jsdom gegen eine Office-Attrappe mit Dialog-API und eine
 * fetch-Attrappe, die ueber den PFAD routet.
 *
 * Zusagen:
 *   - Knopf nur bei {aktiv:true} UND Dialog-API; sonst Maske exakt wie bisher.
 *   - ad_modus "fallback": Kennwortmaske eingeklappt, Link klappt auf;
 *     "zusaetzlich": Maske offen, kein Link.
 *   - Klick oeffnet den Dialog auf /api/login/oidc/start mit app, challenge,
 *     zustand; challenge == SHA-256(verifier) (nachgerechnet beim Einloesen).
 *   - Eine Nachricht mit fremdem zustand wird verworfen (kein Einloesen).
 *   - fehler -> uebersetzter Text, Kennwortmaske offen.
 *   - Erfolg -> app-einloesen {code, verifier} -> Token gespeichert -> derselbe
 *     Folgeweg wie nach der Kennwortanmeldung (/api/me -> Anwendung).
 *   - Einloesen scheitert -> Text, Maske offen, Knopf wieder frei.
 *   - Fenster selbst geschlossen (12006) -> kein Fehlertext, Knopf frei.
 *
 *   node tests/test_office_idp_ui.js        Exit 0 gruen, 1 Befund, 2 konnte nicht laufen
 *
 * Fuer die Gegenprobe lassen sich die Quellen umlenken (OFFICE_IDP_JS,
 * ADDIN_JS, EXCEL_JS, ADDIN_HTML, EXCEL_HTML) – sabotiert werden KOPIEN.
 */
require('./lib/bilanz')();

const fs = require('fs');
const path = require('path');
const nodeCrypto = require('crypto');
const { TextEncoder } = require('util');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d !== undefined ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');
const abbruch = (t) => { console.log('ABBRUCH (konnte nicht laufen): ' + t); process.exit(2); };

const ROOT = path.resolve(__dirname, '..');
const lies = (umg, rel) => fs.readFileSync(process.env[umg] || path.join(ROOT, rel), 'utf8');
const { JSDOM } = require('./lib/jsdom_laden')();

const QUELLEN = {
    sitzung: lies('SITZUNG_JS', 'frontend/js/sitzung.js'),
    icons: lies('ICONS_JS', 'frontend/js/icons.js'),
    i18n: lies('I18N_JS', 'frontend/js/i18n.js'),
    idp: lies('OFFICE_IDP_JS', 'frontend/js/office_idp.js'),
};
const ADDINS = {
    outlook: { p: 'ad', html: lies('ADDIN_HTML', 'frontend/addin/taskpane.html'),
               js: lies('ADDIN_JS', 'frontend/addin/addin.js'),
               url: 'https://jarvis.test/addin/taskpane.html', app: 'ad-app',
               recht: 'email', host: {} },
    excel: { p: 'xl', html: lies('EXCEL_HTML', 'frontend/excel-addin/taskpane.html'),
             js: lies('EXCEL_JS', 'frontend/excel-addin/excel.js'),
             url: 'https://jarvis.test/excel-addin/taskpane.html', app: 'xl-app',
             recht: 'excel', host: { host: 'Excel' } },
};

const warte = (ms) => new Promise(r => setTimeout(r, ms));
const b64url = (buf) => Buffer.from(buf).toString('base64')
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const sha = (s) => b64url(nodeCrypto.createHash('sha256').update(s, 'ascii').digest());

/* opt: status ({aktiv, ad_modus} | 'fehler'), ui (Dialog-API da), dialogFehlt
   (displayDialogAsync meldet Fehlschlag), einloesen ({st, d}) */
function baue(name, opt) {
    const A = ADDINS[name];
    const dom = new JSDOM(A.html, { url: A.url, runScripts: 'outside-only' });
    const w = dom.window;
    const rufe = [];
    const dialoge = [];
    // WebCrypto + TextEncoder wie im Browser (jsdom bringt subtle nicht mit).
    Object.defineProperty(w, 'crypto', { value: nodeCrypto.webcrypto, configurable: true });
    w.TextEncoder = TextEncoder;
    w.fetch = (u, o) => {
        o = o || {};
        const pfad = String(u).split('?')[0];
        let rumpf = null;
        try { rumpf = o.body ? JSON.parse(o.body) : null; } catch (e) { rumpf = o.body; }
        rufe.push({ pfad, methode: o.method || 'GET', rumpf, kopf: o.headers || {} });
        const gib = (d, st) => Promise.resolve({
            ok: (st || 200) < 400, status: st || 200, json: () => Promise.resolve(d)
        });
        if (pfad === '/api/login/oidc/status') {
            if (opt.status === 'fehler') return Promise.reject(new Error('offline'));
            return gib(opt.status || { aktiv: false });
        }
        if (pfad === '/api/login/oidc/app-einloesen') {
            const e = opt.einloesen || { st: 200, d: { success: true, token: 'TOK-IDP',
                                                       username: 'm.mustermann', is_admin: false } };
            return gib(e.d, e.st);
        }
        if (pfad === '/api/me') {
            const perm = {}; perm[A.recht] = true;
            return gib({ username: 'm.mustermann', is_admin: false, permissions: perm });
        }
        if (pfad === '/api/addin/version' || pfad === '/api/excel-addin/version') {
            return gib({ ok: true, version: '1.0.0.0' });
        }
        if (pfad === '/api/email/status') {
            return gib({ ok: true, konto: { vorhanden: false }, bereiche: [], server: {},
                         regeln: 0, grenzen: {} });
        }
        if (pfad === '/api/email/rules') return gib({ ok: true, regeln: [], bereiche: [] });
        if (pfad === '/api/email/log') return gib({ ok: true, eintraege: [] });
        if (pfad === '/api/email/vorlagen') return gib({ ok: true, eigene: [], global: [] });
        return gib({ ok: true });
    };
    const ui = {
        displayDialogAsync: (url, o, cb) => {
            if (opt.dialogFehlt) { cb({ status: 'failed', error: { code: 12007 } }); return; }
            const d = { url, o, handler: {}, zu: 0,
                        addEventHandler: (t, f) => { d.handler[t] = f; },
                        close: () => { d.zu++; } };
            dialoge.push(d);
            cb({ status: 'succeeded', value: d });
        }
    };
    const ctx = { requirements: { isSetSupported: () => false } };
    if (name === 'outlook') ctx.mailbox = {};
    if (opt.ui !== false) ctx.ui = ui;
    w.Office = {
        onReady: (cb) => cb(A.host),
        context: ctx,
        HostType: { Excel: 'Excel' },
        EventType: { DialogMessageReceived: 'dialogMessageReceived',
                     DialogEventReceived: 'dialogEventReceived' },
        AsyncResultStatus: { Succeeded: 'succeeded', Failed: 'failed' },
    };
    w.eval(QUELLEN.sitzung);
    w.eval(QUELLEN.icons);
    w.eval(QUELLEN.i18n);
    w.eval(QUELLEN.idp);
    w.eval(A.js);
    const $ = (id) => w.document.getElementById(id);
    const sicht = (id) => { const e = $(id); return !!e && !e.classList.contains('hidden'); };
    // Sichtbar heisst: weder das Element noch ein Vorfahr traegt "hidden".
    const wirklich = (id) => {
        let e = $(id);
        if (!e) return false;
        for (; e && e.classList; e = e.parentElement) if (e.classList.contains('hidden')) return false;
        return true;
    };
    const tokens = () => {
        const v = [];
        for (let i = 0; i < w.localStorage.length; i++) v.push(w.localStorage.getItem(w.localStorage.key(i)));
        return v;
    };
    return { w, A, rufe, dialoge, $, sicht, wirklich, tokens, p: A.p };
}

function nachricht(d, m) {
    d.handler.dialogMessageReceived({ message: typeof m === 'string' ? m : JSON.stringify(m) });
}
function startParam(d) {
    const u = new URL(d.url);
    return { pfad: u.pathname, app: u.searchParams.get('app'),
             challenge: u.searchParams.get('challenge'), zustand: u.searchParams.get('zustand'),
             rueck: u.searchParams.get('rueck'), origin: u.origin };
}

(async function () {
    // ── Positivkontrolle: Messaufbau traegt ueberhaupt ──────────────────
    abschnitt('0. Positivkontrolle');
    for (const name of Object.keys(ADDINS)) {
        const f = baue(name, { status: { aktiv: true, ad_modus: 'fallback' } });
        await warte(80);
        // Nur der MESSAUFBAU bricht ab (Modul nicht ausgewertet, Maske nie
        // gezeigt). Fehlendes Markup oder eine fehlende Statusabfrage sind
        // PRODUKTAENDERUNGEN und werden als FAIL gemeldet – ein Guard, der sie
        // zu Exit 2 macht, verwandelt einen Befund in "konnte nicht laufen"
        // (Register, dreimal an einem Tag).
        if (!f.w.OfficeIdp) abbruch(name + ': office_idp.js nicht ausgewertet');
        if (!f.sicht(f.p + '-login')) abbruch(name + ': Anmeldemaske nicht gezeigt');
        pruefe(true, name + ': Modul geladen, Anmeldemaske steht');
        pruefe(!!(f.$(f.p + '-idp') && f.$(f.p + '-idp-btn') && f.$(f.p + '-idp-status') &&
                  f.$(f.p + '-idp-kennwort') && f.$(f.p + '-kennwort')),
               name + ': IdP-Markup vollstaendig in taskpane.html');
        pruefe(f.rufe.some(r => r.pfad === '/api/login/oidc/status'),
               name + ': Anmeldemaske fragt den IdP-Status ab');
    }

    for (const name of Object.keys(ADDINS)) {
        const P = (id) => ADDINS[name].p + id;

        abschnitt(name + ': ohne IdP / ohne Dialog – Maske wie bisher');
        for (const [titel, opt] of [['aktiv:false', { status: { aktiv: false } }],
                                    ['Status nicht erreichbar', { status: 'fehler' }],
                                    ['ohne Dialog-API', { status: { aktiv: true, ad_modus: 'fallback' }, ui: false }]]) {
            const f = baue(name, opt);
            await warte(80);
            pruefe(!f.wirklich(P('-idp-btn')), titel + ': kein Firmenkonto-Knopf');
            pruefe(f.wirklich(P('-user')) && f.wirklich(P('-pass')) && f.wirklich(P('-do-login')),
                   titel + ': Kennwortmaske sichtbar');
            pruefe(!f.wirklich(P('-idp-kennwort')), titel + ': kein Aufklapp-Link');
        }

        abschnitt(name + ': ad_modus');
        {
            const f = baue(name, { status: { aktiv: true, ad_modus: 'fallback' } });
            await warte(80);
            pruefe(f.wirklich(P('-idp-btn')), 'fallback: Knopf sichtbar');
            pruefe(!f.wirklich(P('-user')) && !f.wirklich(P('-do-login')), 'fallback: Kennwortmaske eingeklappt');
            pruefe(f.wirklich(P('-idp-kennwort')), 'fallback: Link sichtbar');
            // Knopf steht OBEN: vor dem Benutzerfeld im Dokument.
            const pos = f.$(P('-idp-btn')).compareDocumentPosition(f.$(P('-user')));
            pruefe(!!(pos & f.w.Node.DOCUMENT_POSITION_FOLLOWING), 'Knopf steht vor der Kennwortmaske');
            f.$(P('-idp-kennwort')).click();
            pruefe(f.wirklich(P('-user')) && f.wirklich(P('-do-login')), 'Link klappt die Kennwortmaske auf');
            pruefe(!f.wirklich(P('-idp-kennwort')), 'Link danach weg');
        }
        {
            const f = baue(name, { status: { aktiv: true, ad_modus: 'zusaetzlich' } });
            await warte(80);
            pruefe(f.wirklich(P('-idp-btn')) && f.wirklich(P('-user')), 'zusaetzlich: Knopf UND Maske sichtbar');
            pruefe(!f.wirklich(P('-idp-kennwort')), 'zusaetzlich: kein Link');
        }

        abschnitt(name + ': Dialog oeffnen, Erfolg');
        {
            const f = baue(name, { status: { aktiv: true, ad_modus: 'fallback' } });
            await warte(80);
            f.$(P('-idp-btn')).click();
            await warte(50);
            pruefe(f.dialoge.length === 1, 'Klick oeffnet genau einen Dialog', f.dialoge.length);
            const d = f.dialoge[0];
            if (!d) { pruefe(false, 'ohne Dialog keine Folgepruefungen moeglich'); continue; }
            const sp = startParam(d);
            pruefe(sp.origin === 'https://jarvis.test' && sp.pfad === '/api/login/oidc/start',
                   'Dialog auf eigenem Ursprung /api/login/oidc/start', d.url);
            pruefe(sp.app === name, 'app=' + name, sp.app);
            pruefe(/^[A-Za-z0-9_-]{43}$/.test(sp.challenge || ''), 'challenge: 43 Zeichen base64url', sp.challenge);
            pruefe(/^[A-Za-z0-9_-]{22}$/.test(sp.zustand || ''), 'zustand: 16 Bytes base64url', sp.zustand);
            pruefe(sp.rueck === null, 'kein rueck-Parameter (Server setzt ihn)');
            pruefe(f.$(P('-idp-btn')).disabled, 'Knopf waehrend des Laufs gesperrt');
            pruefe(!!f.$(P('-idp-status')).querySelector('.jv-pkg-spin'), 'laufender Vorgang: drehender Kreis');
            pruefe(f.rufe.filter(r => r.pfad === '/api/login/oidc/app-einloesen').length === 0,
                   'vor der Nachricht kein Einloesen');
            nachricht(d, { code: 'CODE-1', fehler: '', zustand: sp.zustand });
            await warte(120);
            const e = f.rufe.filter(r => r.pfad === '/api/login/oidc/app-einloesen');
            pruefe(e.length === 1 && e[0].methode === 'POST', 'app-einloesen genau einmal per POST', e.length);
            const r = (e[0] && e[0].rumpf) || {};
            pruefe(r.code === 'CODE-1', 'Code geht mit', r.code);
            pruefe(typeof r.verifier === 'string' && /^[A-Za-z0-9_-]{43}$/.test(r.verifier),
                   'verifier: 43 Zeichen base64url', r.verifier);
            pruefe(sha(r.verifier || '') === sp.challenge, 'challenge == SHA-256(verifier) nachgerechnet');
            pruefe(d.zu >= 1, 'Dialog geschlossen');
            pruefe(f.tokens().indexOf('TOK-IDP') !== -1, 'Token gespeichert');
            const meNach = f.rufe.findIndex((x, i) => x.pfad === '/api/me' &&
                i > f.rufe.indexOf(e[0]));
            pruefe(meNach !== -1, 'danach derselbe Folgeweg: /api/me');
            pruefe(f.sicht(ADDINS[name].app) && !f.sicht(P('-login')), 'Anwendung sichtbar, Anmeldung weg');
        }

        abschnitt(name + ': fremder zustand wird verworfen');
        {
            const f = baue(name, { status: { aktiv: true, ad_modus: 'fallback' } });
            await warte(80);
            f.$(P('-idp-btn')).click();
            await warte(50);
            const d = f.dialoge[0];
            nachricht(d, { code: 'CODE-X', fehler: '', zustand: 'fremd-fremd-fremd-fremd' });
            await warte(80);
            pruefe(f.rufe.filter(r => r.pfad === '/api/login/oidc/app-einloesen').length === 0,
                   'kein Einloesen mit fremdem zustand');
            pruefe(/gehört nicht zu dieser Anmeldung/.test(f.$(P('-idp-status')).textContent),
                   'Fehlertext genannt', f.$(P('-idp-status')).textContent);
            pruefe(f.wirklich(P('-user')), 'Kennwortmaske aufgeklappt');
            pruefe(!f.$(P('-idp-btn')).disabled, 'Knopf wieder frei');
            pruefe(f.tokens().indexOf('TOK-IDP') === -1, 'kein Token');
            // Unlesbare Nachricht ebenso.
            const g = baue(name, { status: { aktiv: true, ad_modus: 'fallback' } });
            await warte(80);
            g.$(P('-idp-btn')).click();
            await warte(50);
            nachricht(g.dialoge[0], 'kein json');
            await warte(50);
            pruefe(g.rufe.filter(r => r.pfad === '/api/login/oidc/app-einloesen').length === 0,
                   'unlesbare Nachricht: kein Einloesen');
        }

        abschnitt(name + ': fehler aus dem Dialog');
        {
            const f = baue(name, { status: { aktiv: true, ad_modus: 'fallback' } });
            await warte(80);
            f.$(P('-idp-btn')).click();
            await warte(50);
            const sp = startParam(f.dialoge[0]);
            nachricht(f.dialoge[0], { code: '', fehler: 'keine_freigabe', zustand: sp.zustand });
            await warte(80);
            pruefe(f.$(P('-idp-status')).textContent.trim() === 'Keine Anmeldeberechtigung.',
                   'Kennung uebersetzt (login.idp_err.keine_freigabe)', f.$(P('-idp-status')).textContent);
            pruefe(f.wirklich(P('-user')), 'Kennwortmaske aufgeklappt');
            pruefe(f.rufe.filter(r => r.pfad === '/api/login/oidc/app-einloesen').length === 0,
                   'kein Einloesen');
            pruefe(f.dialoge[0].zu >= 1, 'Dialog geschlossen');
        }

        abschnitt(name + ': Einloesen scheitert');
        {
            const f = baue(name, { status: { aktiv: true, ad_modus: 'fallback' },
                                   einloesen: { st: 401, d: { success: false, abgelaufen: true,
                                                              error: 'Schein abgelaufen XYZ' } } });
            await warte(80);
            f.$(P('-idp-btn')).click();
            await warte(50);
            const sp = startParam(f.dialoge[0]);
            nachricht(f.dialoge[0], { code: 'C', fehler: '', zustand: sp.zustand });
            await warte(120);
            pruefe(/Schein abgelaufen XYZ/.test(f.$(P('-idp-status')).textContent),
                   'Fehlertext des Servers steht da', f.$(P('-idp-status')).textContent);
            pruefe(f.wirklich(P('-user')), 'Kennwortmaske aufgeklappt');
            pruefe(!f.$(P('-idp-btn')).disabled, 'Knopf wieder frei');
            pruefe(f.tokens().indexOf('TOK-IDP') === -1, 'kein Token');
        }

        abschnitt(name + ': Fenster selbst geschlossen / Dialog nicht oeffenbar');
        {
            const f = baue(name, { status: { aktiv: true, ad_modus: 'fallback' } });
            await warte(80);
            f.$(P('-idp-btn')).click();
            await warte(50);
            f.dialoge[0].handler.dialogEventReceived({ error: 12006 });
            await warte(30);
            pruefe(!f.$(P('-idp-btn')).disabled, '12006: Knopf wieder frei');
            pruefe(f.$(P('-idp-status')).textContent.trim() === '', '12006: kein Fehlertext');
            pruefe(!f.wirklich(P('-user')), '12006: Maske bleibt eingeklappt');
            // Ein spaeter noch eintreffendes Ergebnis wird nicht mehr verarbeitet.
            nachricht(f.dialoge[0], { code: 'SPAET', fehler: '', zustand: startParam(f.dialoge[0]).zustand });
            await warte(80);
            pruefe(f.rufe.filter(r => r.pfad === '/api/login/oidc/app-einloesen').length === 0,
                   'nach dem Schliessen kein Einloesen mehr');

            const g = baue(name, { status: { aktiv: true, ad_modus: 'fallback' }, dialogFehlt: true });
            await warte(80);
            g.$(P('-idp-btn')).click();
            await warte(50);
            pruefe(/Anmeldefenster ließ sich nicht öffnen/.test(g.$(P('-idp-status')).textContent),
                   'Dialog scheitert: Text genannt', g.$(P('-idp-status')).textContent);
            pruefe(g.wirklich(P('-user')) && !g.$(P('-idp-btn')).disabled,
                   'Dialog scheitert: Maske offen, Knopf frei');
        }
    }

    // ── Regeln: Einbindung und Sprachen ─────────────────────────────────
    abschnitt('Einbindung und Uebersetzungen');
    for (const name of Object.keys(ADDINS)) {
        const h = ADDINS[name].html;
        const iI = h.indexOf('/static/js/office_idp.js?v=');
        const iA = h.indexOf(name === 'outlook' ? '/static/addin/addin.js?v=' : '/static/excel-addin/excel.js?v=');
        pruefe(iI !== -1 && iA !== -1 && iI < iA, name + ': office_idp.js vor dem Add-in-Modul eingebunden');
    }
    const I18N_FR = lies('I18N_FR_JS', 'frontend/js/i18n_fr.js');
    const I18N_NL = lies('I18N_NL_JS', 'frontend/js/i18n_nl.js');
    for (const k of ['login.idp_laeuft', 'login.idp_err.allgemein', 'login.idp_err.dialog',
                     'login.idp_err.zustand', 'addin.idp_fertig_laeuft', 'addin.idp_fertig_ohne_office']) {
        const n = QUELLEN.i18n.split("'" + k + "'").length - 1;
        pruefe(n === 2, k + ': DE und EN in i18n.js', n);
        pruefe(I18N_FR.indexOf('"' + k + '"') !== -1 && I18N_NL.indexOf('"' + k + '"') !== -1,
               k + ': FR und NL');
    }

    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
