#!/usr/bin/env node
/**
 * Waechter: Abmelden nach einer Anmeldung ueber den IdP fuehrt NICHT zur
 * Abmeldeseite des IdP, sondern wie jede Abmeldung auf die Jarvis-Anmeldemaske
 * (Festlegung 2026-11-27, frontend/js/sessions.js).
 *
 * WARUM: Die erste Fassung (selber Tag) leitete den Browser nach /api/logout
 * zur Abmeldeseite des IdP weiter; der Benutzer blieb dort auf der Seite des
 * IdP stehen. Gewuenscht ist die Anmeldemaske von Jarvis. Die Sitzung am IdP
 * zwingt trotzdem niemand still weiter: die naechste IdP-Anmeldung verlangt
 * dort eine neue Anmeldung (prompt=login, test_oidc_anmeldung.py).
 *
 * Gemessen wird die WIRKUNG: sessions.js wird mit einer fetch-Attrappe in der
 * echten Antwortform ausgefuehrt, gezaehlt werden location.replace-Aufrufe und
 * ob das Promise aufgeloest wird (die Abmelde-Knoepfe warten darauf und fuehren
 * danach selbst auf "/", test_abmelden_ziel.js).
 *
 * Positivkontrolle: bei normaler Antwort loest das Promise mit true auf und
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
        console.log('ABBRUCH: Positivkontrolle – Abmeldung endet nicht sauber ('
                    + JSON.stringify(r) + ')');
        process.exit(2);
    }
    check('Positivkontrolle: Abmeldung -> true, keine Navigation', true);
    check('Abmeldung geht an /api/logout mit keepalive',
          r.anfragen[0].url === '/api/logout' && r.anfragen[0].opt.keepalive === true
          && r.anfragen[0].opt.headers.Authorization === 'Bearer CSRF');

    // Auch wenn ein (alter) Server noch ein Ziel nennt: kein Sprung zum IdP.
    for (const [ziel, text] of [['https://idp.beispiel.de/logout?client_id=c', 'https-Adresse des IdP'],
                                ['javascript:alert(1)', 'javascript:'],
                                ['/lokal', 'relative Adresse']]) {
        r = await lauf({ ok: true, idp_abmeldung: ziel });
        check('Server nennt Ziel (' + text + '): keine Navigation, Promise loest mit true auf',
              r.ziele.length === 0 && r.erledigt && r.wert === true, JSON.stringify(r.ziele));
    }
    check('sessions.js kennt kein idp_abmeldung mehr', !/idp_abmeldung/.test(QUELLE));
    r = await lauf('kein json', 200);
    check('Antwort ohne JSON: keine Navigation, true', r.ziele.length === 0 && r.erledigt && r.wert === true);
    r = await lauf({ detail: 'Nicht autorisiert' }, 401);
    check('abgelaufenes Token (401): keine Navigation, Promise loest auf', r.ziele.length === 0 && r.erledigt);

    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
