/* Waechter BSI H4 (Frontend) – sitzung.js stellt auf Cookie + CSRF-Token um.
 *
 * Gemessen am ECHTEN frontend/js/sitzung.js in jsdom:
 *   [1] Umstellung: ein echtes Token (`benutzer:zeit:sig`) im Speicher wird
 *       per POST /api/sitzung/cookie getauscht und danach NICHT mehr gehalten;
 *       ein zweites, anderes echtes Token wird entfernt; ein schon
 *       umgestelltes (CSRF) loest nichts aus; ein Fehlschlag aendert nichts.
 *   [2] Ausnahmen: Add-in-Seiten, http und ein fremder Rahmen stellen NICHT um
 *       und schicken keinen Anmelde-Kopf (dort kommt das Cookie nicht an).
 *   [3] anmeldeKopf(): setzt den Kopf nur, wo das Cookie ankommt, und behaelt
 *       die Felder des Aufrufers.
 *   [4] REGEL (acorn): jeder fetch('/api/login') unter frontend/js/ schickt
 *       `headers: window.JarvisSitzung.anmeldeKopf(...)`. Die Add-in-Seiten
 *       (frontend/addin/, frontend/excel-addin/) liegen bewusst ausserhalb:
 *       sie bleiben beim Bearer-Token (Office-WebView, fremder Rahmen).
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const acorn = require('./lib/acorn_laden')();

const WURZEL = path.resolve(__dirname, '..');
const QUELLE = fs.readFileSync(path.join(WURZEL, 'frontend/js/sitzung.js'), 'utf8');

let ok = 0, fail = 0;
function check(name, bed, info) {
    if (bed) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (info !== undefined ? '  [' + JSON.stringify(info).slice(0, 300) + ']' : '')); }
}
function abbruch(grund) { console.log('ABBRUCH: ' + grund); process.exit(2); }

const ECHT_A = 'anna:1790000000:' + 'a'.repeat(64);
const ECHT_B = 'bert:1790000000:' + 'b'.repeat(64);
const CSRF_A = 'JCS1.' + 'c'.repeat(64);

/* Seite laden: Speicher VOR dem Modul fuellen (so findet es ein Browser nach
 * dem Neuladen vor), fetch-Attrappe mit der echten Antwortform des Endpunkts. */
async function seite(url, speicher, antwort, rahmen) {
    const dom = new JSDOM('<!doctype html><html><body></body></html>',
                          { url: url, runScripts: 'outside-only' });
    const w = dom.window;
    for (const k of Object.keys(speicher || {})) w.localStorage.setItem(k, speicher[k]);
    const aufrufe = [];
    w.fetch = function (u, opt) {
        aufrufe.push({ url: String(u).split('?')[0], opt: opt || {} });
        const a = antwort || { status: 200, json: { ok: true, sitzung: 'cookie', umgestellt: true, token: CSRF_A } };
        return Promise.resolve({ ok: a.status >= 200 && a.status < 300, status: a.status,
                                 json: function () { return Promise.resolve(a.json); } });
    };
    if (rahmen) {
        /* Fremder Rahmen: NUR window.top weicht ab, die Adresse bleibt https.
         * Ein jsdom-iframe taugt dafuer nicht – es steht auf about:blank und
         * wuerde schon am Protokoll scheitern (so gemessen: die Pruefung war
         * damit aus dem falschen Grund gruen). `top` ist in jsdom nicht
         * umdefinierbar, also bekommt das Modul ein Fenster-Proxy. */
        w.__rahmenFenster = new w.Proxy(w, {
            get: function (t, k) {
                if (k === 'top') return {};
                if (k === 'self') return w.__rahmenFenster;
                const v = Reflect.get(t, k);
                return typeof v === 'function' && k !== 'fetch' ? v.bind(t) : v;
            }
        });
        w.eval('(function (window) {\n' + QUELLE + '\n})(window.__rahmenFenster);');
        w.__rahmenPruefung = w.eval('(function (window) { return [window.top !== window.self, location.protocol]; })(window.__rahmenFenster)');
    } else {
        w.eval(QUELLE);
    }
    if (!w.JarvisSitzung || typeof w.JarvisSitzung.anmeldeKopf !== 'function') {
        abbruch('sitzung.js hat kein JarvisSitzung.anmeldeKopf gesetzt');
    }
    await new Promise(function (r) { setTimeout(r, 30); });
    const lies = function (k) { return w.localStorage.getItem(k); };
    return { w: w, aufrufe: aufrufe, lies: lies, dom: dom };
}

(async function () {
    console.log('\n[1] Umstellung');
    let s = await seite('https://jarvis.beispiel.de/settings',
                        { jarvis_token: ECHT_A, jarvis_chat_token: ECHT_A });
    const um = s.aufrufe.filter(function (a) { return a.url === '/api/sitzung/cookie'; });
    check('Positivkontrolle: Umstellung wird aufgerufen', um.length === 1, s.aufrufe);
    const kopf = (um[0] && um[0].opt.headers) || {};
    check('Umstellung schickt das echte Token als Bearer', kopf.Authorization === 'Bearer ' + ECHT_A, kopf);
    check('Umstellung per POST', um[0] && um[0].opt.method === 'POST');
    check('danach kein echtes Token mehr im Speicher (alle Schluessel)',
          ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'].every(function (k) {
              const v = s.lies(k); return !v || v.indexOf(':') < 0;
          }), [s.lies('jarvis_token'), s.lies('jarvis_chat_token')]);
    check('beide Schluessel tragen das CSRF-Token',
          s.lies('jarvis_token') === CSRF_A && s.lies('jarvis_chat_token') === CSRF_A);
    check('token() liefert danach das CSRF-Token', s.w.JarvisSitzung.token() === CSRF_A);

    s = await seite('https://jarvis.beispiel.de/chat', { jarvis_token: ECHT_A, jarvis_uc_token: ECHT_B });
    check('zweites, anderes echtes Token wird entfernt (ein Cookie je Browser)',
          s.lies('jarvis_uc_token') === null && s.lies('jarvis_token') === CSRF_A,
          [s.lies('jarvis_token'), s.lies('jarvis_uc_token')]);

    s = await seite('https://jarvis.beispiel.de/settings', { jarvis_token: CSRF_A });
    check('schon umgestellt -> kein Aufruf', s.aufrufe.length === 0, s.aufrufe);

    s = await seite('https://jarvis.beispiel.de/settings', { jarvis_token: ECHT_A },
                    { status: 409, json: { ok: false, error: 'Nur ueber HTTPS moeglich.' } });
    check('Fehlschlag -> Speicher unveraendert (Seite bleibt angemeldet)', s.lies('jarvis_token') === ECHT_A);
    s = await seite('https://jarvis.beispiel.de/settings', { jarvis_token: ECHT_A },
                    { status: 200, json: { ok: true, token: ECHT_B } });
    check('Antwort mit echtem Token wird NICHT abgelegt', s.lies('jarvis_token') === ECHT_A);

    s = await seite('https://jarvis.beispiel.de/settings', {});
    check('nicht angemeldet -> kein Aufruf', s.aufrufe.length === 0);

    console.log('\n[2] Ausnahmen');
    for (const p of ['/addin/taskpane.html', '/excel-addin/taskpane.html', '/jira-addon', '/confluence-addon']) {
        s = await seite('https://jarvis.beispiel.de' + p, { jarvis_token: ECHT_A });
        check('Add-in ' + p + ' -> keine Umstellung', s.aufrufe.length === 0 && s.lies('jarvis_token') === ECHT_A);
        check('Add-in ' + p + ' -> kein Anmelde-Kopf', !('X-Jarvis-Sitzung' in s.w.JarvisSitzung.anmeldeKopf()));
    }
    s = await seite('http://jarvis.beispiel.de/settings', { jarvis_token: ECHT_A });
    check('http -> keine Umstellung', s.aufrufe.length === 0 && s.lies('jarvis_token') === ECHT_A);
    check('http -> kein Anmelde-Kopf', !('X-Jarvis-Sitzung' in s.w.JarvisSitzung.anmeldeKopf()));
    s = await seite('https://jarvis.beispiel.de/settings', { jarvis_token: ECHT_A }, null, true);
    check('Positivkontrolle: Rahmen ist eingebettet UND die Adresse ist https',
          s.w.__rahmenPruefung && s.w.__rahmenPruefung[0] === true && s.w.__rahmenPruefung[1] === 'https:',
          s.w.__rahmenPruefung);
    check('Rahmen -> keine Umstellung', s.aufrufe.length === 0);
    check('Rahmen -> kein Anmelde-Kopf', !('X-Jarvis-Sitzung' in s.w.JarvisSitzung.anmeldeKopf()));

    console.log('\n[3] anmeldeKopf');
    s = await seite('https://jarvis.beispiel.de/settings', {});
    const h = s.w.JarvisSitzung.anmeldeKopf({ 'Content-Type': 'application/json' });
    check('https/oben -> Kopf X-Jarvis-Sitzung: cookie', h['X-Jarvis-Sitzung'] === 'cookie', h);
    check('Felder des Aufrufers bleiben', h['Content-Type'] === 'application/json', h);
    check('ohne Argument kein Wurf', typeof s.w.JarvisSitzung.anmeldeKopf() === 'object');

    console.log('\n[4] Regel: jeder fetch(\'/api/login\') schickt anmeldeKopf');
    const dir = path.join(WURZEL, 'frontend/js');
    const dateien = fs.readdirSync(dir).filter(function (f) { return f.endsWith('.js'); });
    let gefunden = 0; const ohne = [];
    function istAnmeldeKopf(n) {
        return n && n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
            && n.callee.property && n.callee.property.name === 'anmeldeKopf';
    }
    function lauf(n, datei) {
        if (!n || typeof n.type !== 'string') return;
        if (n.type === 'CallExpression' && n.callee.type === 'Identifier' && n.callee.name === 'fetch'
            && n.arguments[0] && n.arguments[0].type === 'Literal' && n.arguments[0].value === '/api/login') {
            gefunden++;
            const o = n.arguments[1];
            const hp = o && o.type === 'ObjectExpression' && o.properties.find(function (p) {
                return p.key && (p.key.name === 'headers' || p.key.value === 'headers');
            });
            if (!hp || !istAnmeldeKopf(hp.value)) ohne.push(datei + ':' + n.loc.start.line);
        }
        for (const k of Object.keys(n)) {
            const v = n[k];
            if (Array.isArray(v)) v.forEach(function (x) { lauf(x, datei); });
            else if (v && typeof v.type === 'string') lauf(v, datei);
        }
    }
    for (const f of dateien) {
        const src = fs.readFileSync(path.join(dir, f), 'utf8');
        let ast;
        try { ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', locations: true, allowHashBang: true }); }
        catch (e) { abbruch('acorn kann ' + f + ' nicht parsen: ' + e.message); }
        lauf(ast, f);
    }
    check('Positivkontrolle: Anmeldestellen gefunden (app, chat, userchat, wissen, support)', gefunden >= 5, gefunden);
    check('jede Anmeldung verlangt das Cookie-Verfahren', ohne.length === 0, ohne);

    console.log('\n' + '='.repeat(60));
    console.log('Ergebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
