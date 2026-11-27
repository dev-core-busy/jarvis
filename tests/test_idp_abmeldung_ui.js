#!/usr/bin/env node
/**
 * Waechter: Abmelden nach einer Anmeldung ueber den IdP fuehrt den Browser zur
 * Abmeldung am IdP (2026-11-27, frontend/js/sessions.js).
 *
 * WARUM: Der Abmelde-Knopf beendete nur die Jarvis-Sitzung; die Sitzung am IdP
 * blieb offen, und "Mit Firmenkonto anmelden" meldete danach ohne Kennwort
 * wieder an. /api/logout nennt jetzt in "idp_abmeldung" die Abmeldeadresse des
 * IdP; JarvisSession.logout geht dorthin und laesst sein Promise OFFEN – die
 * Abmelde-Knoepfe warten darauf und fuehren sonst selbst auf "/", das wuerde
 * die Abmeldung am IdP ueberholen (test_abmelden_ziel.js).
 *
 * Gemessen wird die WIRKUNG: sessions.js wird mit einer fetch-Attrappe in der
 * echten Antwortform ausgefuehrt, gezaehlt werden location.replace-Aufrufe und
 * ob das Promise aufgeloest wird.
 *
 * Positivkontrolle: ohne "idp_abmeldung" loest das Promise mit true auf und
 * es wird NICHT navigiert – sonst Exit 2.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs'), path = require('path'), vm = require('vm');

const QUELLE = fs.readFileSync(path.resolve(__dirname, '../frontend/js/sessions.js'), 'utf8');
let ok = 0, fail = 0;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (detail ? ' – ' + detail : '')); }
}

// Fuehrt sessions.js mit der gegebenen Server-Antwort aus und ruft logout().
async function lauf(antwort, status) {
    const ziele = [], anfragen = [];
    const speicher = { jarvis_token: 'CSRF' };
    const fenster = {
        JarvisSitzung: { tokenSchluessel: () => ['jarvis_token'] },
        location: { replace: (u) => ziele.push(u) },
    };
    const kontext = {
        window: fenster,
        document: { addEventListener() {}, getElementById: () => null },
        localStorage: { getItem: (k) => (k in speicher ? speicher[k] : null) },
        fetch: (url, opt) => {
            anfragen.push({ url, opt });
            const text = typeof antwort === 'string' ? antwort : JSON.stringify(antwort);
            return Promise.resolve({ ok: (status || 200) < 400, status: status || 200,
                                     json: () => Promise.resolve().then(() => JSON.parse(text)) });
        },
        setTimeout, clearTimeout, console,
    };
    vm.runInNewContext(QUELLE, kontext, { filename: 'sessions.js' });
    let erledigt = false, wert;
    fenster.JarvisSession.logout().then((w) => { erledigt = true; wert = w; });
    // Genug Mikrotasks/Runden, dass eine Aufloesung sicher eingetreten waere.
    for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r));
    return { ziele, anfragen, erledigt, wert };
}

(async () => {
    // Positivkontrolle
    let r = await lauf({ ok: true });
    if (!(r.erledigt && r.wert === true && r.ziele.length === 0 && r.anfragen.length === 1)) {
        console.log('ABBRUCH: Positivkontrolle – ohne idp_abmeldung kein sauberes Ende ('
                    + JSON.stringify(r) + ')');
        process.exit(2);
    }
    check('Positivkontrolle: ohne idp_abmeldung -> true, keine Navigation', true);
    check('Abmeldung geht an /api/logout mit keepalive',
          r.anfragen[0].url === '/api/logout' && r.anfragen[0].opt.keepalive === true
          && r.anfragen[0].opt.headers.Authorization === 'Bearer CSRF');

    const IDP = 'https://idp.beispiel.de/logout?client_id=c&post_logout_redirect_uri=https%3A%2F%2Fj%2F';
    r = await lauf({ ok: true, idp_abmeldung: IDP });
    check('mit idp_abmeldung: Browser geht zur Abmeldung am IdP', r.ziele.length === 1 && r.ziele[0] === IDP,
          JSON.stringify(r.ziele));
    check('mit idp_abmeldung: Promise bleibt offen (Aufrufer navigiert nicht auf "/")', !r.erledigt);

    for (const [schlecht, text] of [['javascript:alert(1)', 'javascript:'],
                                    ['http://idp.beispiel.de/logout', 'http ohne TLS'],
                                    ['/lokal', 'relative Adresse'],
                                    ['https://idp.beispiel.de/a b', 'Leerraum'],
                                    [['https://x'], 'kein Text']]) {
        r = await lauf({ ok: true, idp_abmeldung: schlecht });
        check('unbrauchbares Ziel (' + text + '): keine Navigation, Promise loest auf',
              r.ziele.length === 0 && r.erledigt && r.wert === true);
    }
    r = await lauf('kein json', 200);
    check('Antwort ohne JSON: keine Navigation, true', r.ziele.length === 0 && r.erledigt && r.wert === true);
    r = await lauf({ detail: 'Nicht autorisiert' }, 401);
    check('abgelaufenes Token (401): keine Navigation', r.ziele.length === 0 && r.erledigt);

    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
