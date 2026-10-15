#!/usr/bin/env node
/**
 * Waechter: Hinweiskarte "deine 2FA wurde zurueckgesetzt" (frontend/js/konto_hinweise.js).
 *
 *  A  EINBINDUNG als REGEL: jede Webseite mit sitzung.js (ausser den Office-
 *     Aufgabenfenstern) laedt konto_hinweise.js, und zwar NACH sitzung.js.
 *  B  VERHALTEN in jsdom (fetch nach PFAD geroutet, echte Sitzungsquelle als
 *     Attrappe): einmal je Sitzung, Warten auf ein spaeteres Token, Karte mit
 *     Name als TEXT, Quittieren, Fehler beim Quittieren laesst die Karte stehen,
 *     "Jetzt neu einrichten" (Portal-Knopf bzw. Weiterleitung), Portal-Ziel.
 *  C  TEXTE: alle konto.*-Schluessel des Moduls in DE und EN.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs'), path = require('path');
const REPO = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

let ok = 0, fail = 0, bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });
const MODUL = fs.readFileSync(path.join(REPO, 'frontend/js/konto_hinweise.js'), 'utf8');
const I18N = fs.readFileSync(path.join(REPO, 'frontend/js/i18n.js'), 'utf8');

// ── A ──
console.log('A  Einbindung (Regel ueber alle Seiten)');
const seiten = [];
(function sammle(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) sammle(p); else if (e.name.endsWith('.html')) seiten.push(p);
    }
})(path.join(REPO, 'frontend'));
const pos = (h, n) => { const m = h.match(new RegExp('<script src="/static/js/' + n.replace('.', '\\.') + '\\?v=\\d+"></script>')); return m ? m.index : -1; };
let mitSitzung = 0;
const fehlt = [], vorher = [], office = [];
for (const s of seiten) {
    const h = fs.readFileSync(s, 'utf8'), rel = path.relative(REPO, s);
    const si = pos(h, 'sitzung.js'), kh = pos(h, 'konto_hinweise.js');
    if (/frontend\/(addin|excel-addin)\//.test(rel)) { if (kh >= 0) office.push(rel); continue; }
    if (si < 0) continue;
    mitSitzung++;
    if (kh < 0) fehlt.push(rel); else if (kh < si) vorher.push(rel);
}
check('Webseiten mit sitzung.js gefunden (> 10)', mitSitzung > 10, String(mitSitzung));
check('jede laedt konto_hinweise.js', !fehlt.length, fehlt.join(', '));
check('jeweils NACH sitzung.js', !vorher.length, vorher.join(', '));
check('nicht in den Office-Aufgabenfenstern', !office.length, office.join(', '));

// ── C ──
console.log('\nC  Texte');
const keys = new Set([...MODUL.matchAll(/T\('(konto\.[a-z_]+)'/g)].map(m => m[1]));
check('Schluessel gefunden (>= 5)', keys.size >= 5, String(keys.size));
const ohne = [...keys].filter(k => (I18N.match(new RegExp("\\n\\s*'" + k.replace('.', '\\.') + "':", 'g')) || []).length !== 2);
check('jeder in DE und EN', !ohne.length, ohne.join(', '));
check('Text traegt {von} und {am} in beiden Sprachen',
      (I18N.match(/'konto\.totp_reset_text':[^\n]*\{von\}[^\n]*\{am\}/g) || []).length === 2);

// ── B ──
function umgebung(o) {
    o = o || {};
    const dom = new JSDOM('<!doctype html><head></head><body>' + (o.portal ? '<button id="btn-totp-setup"></button>' : '') + '</body>',
                          { runScripts: 'outside-only', url: 'https://jarvis.test' + (o.pfad || '/chat') });
    const w = dom.window;
    const z = { aufrufe: [], tok: o.tok === undefined ? 'TOKEN-ABCDEFGHIJKLMNOPQRS' : o.tok,
                hinweise: o.hinweise || [], gelesenStatus: o.gelesenStatus || 200, weiter: [], setupKlicks: 0 };
    /* Das ECHTE sitzung.js statt `{ token: () => … }`. Eine Attrappe bietet
       WENIGER als das Original und prueft damit die eigene Annahme - genau
       daran sind am 2026-10-05 acht Waechter still gestorben (Begruendung in
       lib/sitzung_laden.js). Der Helfer WIRFT, wenn danach kein benutzbares
       window.JarvisSitzung steht. */
    sitzungLaden(w, { token: z.tok });
    w.fetch = (url, init) => {
        const p = String(url).split('?')[0];
        z.aufrufe.push({ p, init: init || {} });
        const a = p === '/api/auth/hinweise' ? { status: 200, body: { hinweise: z.hinweise } }
                : p === '/api/auth/hinweise/gelesen' ? { status: z.gelesenStatus, body: { ok: z.gelesenStatus === 200 } }
                : { status: 404, body: {} };
        return Promise.resolve({ ok: a.status < 400, status: a.status, json: () => Promise.resolve(a.body) });
    };
    if (o.portal) w.document.getElementById('btn-totp-setup').addEventListener('click', () => { z.setupKlicks++; });
    if (o.merker) w.sessionStorage.setItem('jarvis_konto_hinweise_geprueft', o.merker);
    w.eval(MODUL);
    w.KontoHinweise._weiter = (u) => z.weiter.push(u);
    return { w, z, d: w.document };
}
const warte = (ms) => new Promise(r => setTimeout(r, ms || 30));
const HINWEIS = { art: 'totp_zurueckgesetzt', von: '<b onmouseover="window.__x=1">Admin</b>', am: 1790000000 };
const nHinweise = (z) => z.aufrufe.filter(a => a.p === '/api/auth/hinweise').length;

(async () => {
    console.log('\nB  Verhalten');
    // Kein Hinweis -> nichts zu sehen, Sitzung gemerkt, zweiter Aufruf fragt nicht
    let u = umgebung();
    await warte();
    check('mit Token: genau eine Abfrage', nHinweise(u.z) === 1, String(nHinweise(u.z)));
    check('mit Sitzungstoken', (u.z.aufrufe[0].init.headers || {}).Authorization === 'Bearer TOKEN-ABCDEFGHIJKLMNOPQRS');
    check('kein Hinweis: keine Karte', !u.d.querySelector('.jkh-karte'));
    const merker = u.w.sessionStorage.getItem('jarvis_konto_hinweise_geprueft');
    check('kein Hinweis: Sitzung gemerkt', !!merker);
    u.w.close();
    u = umgebung({ merker });
    await warte();
    check('gleiche Sitzung, naechste Seite: KEINE Abfrage', nHinweise(u.z) === 0);
    u.w.close();
    u = umgebung({ merker: 'anderes-token-xx' });
    await warte();
    check('neues Token (neue Anmeldung): wieder eine Abfrage', nHinweise(u.z) === 1);
    u.w.close();

    // Hinweis offen
    u = umgebung({ hinweise: [HINWEIS] });
    await warte();
    let karte = u.d.querySelector('.jkh-karte');
    check('Hinweis: Karte erscheint', !!karte);
    check('Name als TEXT, nicht als Markup', karte && !karte.querySelector('b') && u.w.__x === undefined
          && karte.textContent.includes('<b onmouseover'));
    check('Datum steht im Text', karte && /\d{2}\.\d{2}\.\d{4}/.test(karte.textContent), karte && karte.textContent);
    check('offener Hinweis: Sitzung NICHT gemerkt (Karte kommt auf der naechsten Seite wieder)',
          !u.w.sessionStorage.getItem('jarvis_konto_hinweise_geprueft'));
    check('eigenes Styling vorhanden (keine fremde Knopfklasse)', !!u.d.getElementById('jkh-stil'));
    const css = (u.d.getElementById('jkh-stil') || {}).textContent || '';
    check('Karte mit deckender Flaeche aus Theme-Variable', /\.jkh-karte\{[^}]*background:var\(--bg-secondary/.test(css));
    karte.querySelector('.jkh-gelesen').click();
    await warte();
    const post = u.z.aufrufe.find(a => a.p === '/api/auth/hinweise/gelesen');
    check('Verstanden: POST gelesen mit {art}', post && JSON.parse(post.init.body).art === 'totp_zurueckgesetzt');
    check('Verstanden: Karte weg, Sitzung gemerkt', !u.d.querySelector('.jkh-karte')
          && !!u.w.sessionStorage.getItem('jarvis_konto_hinweise_geprueft'));
    u.w.close();

    // Quittieren scheitert -> Karte bleibt
    u = umgebung({ hinweise: [HINWEIS], gelesenStatus: 500 });
    await warte();
    u.d.querySelector('.jkh-gelesen').click();
    await warte();
    check('Quittieren scheitert: Karte bleibt, Knopf wieder bedienbar',
          !!u.d.querySelector('.jkh-karte') && u.d.querySelector('.jkh-gelesen').disabled === false);
    u.w.close();

    // Jetzt neu einrichten – ausserhalb des Portals: Weiterleitung, NICHT quittiert
    u = umgebung({ hinweise: [HINWEIS] });
    await warte();
    u.d.querySelector('.jkh-einrichten').click();
    await warte();
    check('Einrichten (Chat): Weiterleitung ins Portal', u.z.weiter[0] === '/portal?zwei_faktor=einrichten', JSON.stringify(u.z.weiter));
    check('Einrichten quittiert NICHT', !u.z.aufrufe.some(a => a.p === '/api/auth/hinweise/gelesen'));
    u.w.close();

    // Jetzt neu einrichten – im Portal: 2FA-Dialog direkt
    u = umgebung({ hinweise: [HINWEIS], portal: true, pfad: '/portal' });
    await warte();
    u.d.querySelector('.jkh-einrichten').click();
    check('Einrichten (Portal): oeffnet den 2FA-Dialog, keine Weiterleitung', u.z.setupKlicks === 1 && !u.z.weiter.length);
    u.w.close();

    // Portal als Ziel der Weiterleitung: Dialog oeffnet sich, Karte bleibt weg
    u = umgebung({ hinweise: [HINWEIS], portal: true, pfad: '/portal?zwei_faktor=einrichten' });
    await warte(450);
    check('Portal-Ziel: 2FA-Dialog oeffnet sich von selbst', u.z.setupKlicks === 1, String(u.z.setupKlicks));
    check('Portal-Ziel: Parameter aus der Adresse entfernt', !/zwei_faktor/.test(u.w.location.href), u.w.location.href);
    check('Portal-Ziel: keine Karte ueber dem Dialog', !u.d.querySelector('.jkh-karte'));
    u.w.close();

    // Anmeldung auf derselben Seite: erst kein Token, dann eines
    u = umgebung({ tok: '', hinweise: [HINWEIS] });
    await warte();
    check('ohne Token: keine Abfrage', nHinweise(u.z) === 0);
    // Nicht mehr `z.tok` setzen: das echte sitzung.js liest localStorage.
    u.w.localStorage.setItem('jarvis_token', 'TOKEN-NACH-DER-ANMELDUNG-123');
    await warte(2300);
    check('Token erscheint spaeter: Abfrage folgt, Karte erscheint', nHinweise(u.z) === 1 && !!u.d.querySelector('.jkh-karte'));
    u.w.close();

    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH (Exit 2): ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
