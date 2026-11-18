/* Waechter: Zertifikathinweis auf der Anmeldemaske nur, wenn er gebraucht wird
 * (gemeldet 2026-11-18: „bei korrekter HTTPS-Anmeldung muss im Loginscreen
 * kein Zertifikathinweis mehr angezeigt werden").
 *
 * Gemessen wird die WIRKUNG am ECHTEN Markup (settings.html = die Seite unter
 * "/") mit den ECHTEN Funktionen aus app.js (`checkSecurity`,
 * `zertHinweisAnpassen`), geschnitten und im Fenster ausgefuehrt. Die
 * Server-Auskunft (`GET /api/cert/status`) liefert eine fetch-Attrappe in der
 * Form des echten Endpunkts: `{ca_ausgestellt: true|false|null}`.
 *
 * Die Faelle:
 *   HTTPS + CA-ausgestellt           → Hinweis WEG
 *   HTTPS + selbstsigniert           → Hinweis bleibt
 *   HTTPS + unbekannt (null)         → Hinweis bleibt (nichts behaupten)
 *   HTTPS + Abruf scheitert / 404    → Hinweis bleibt (alter Server)
 *   HTTP                             → Hinweis bleibt, und es wird gar nicht
 *                                      erst gefragt
 *
 * ⚠ GEPRUEFT WIRD DIE BERECHNETE SICHTBARKEIT, NICHT DAS `hidden`-ATTRIBUT:
 * `.btn-link` und `.login-extras` setzen `display:flex` und ueberstimmen
 * `hidden` (Register: CSS und DOM). Deshalb wird style.css eingebunden und
 * `getComputedStyle` gelesen.
 *
 *   node tests/test_cert_hinweis_ui.js
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
if (!JSDOM) {
    console.log('ABBRUCH: jsdom nicht gefunden');
    process.exit(2);
}

let ok = 0, fail = 0, _bilanz = false;
function pruefe(name, cond, detail) {
    if (cond) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (detail !== undefined ? '  → ' + detail : '')); }
}
function bilanz() {
    _bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
}
process.on('exit', (code) => {
    if (!_bilanz) {
        console.log('\nABBRUCH ohne Bilanz – ' + ok + ' OK, ' + fail + ' FAIL bis dahin');
        if (code === 0) process.exitCode = 1;
    }
});
const wachhund = setTimeout(() => {
    console.log('  FAIL Wachhund: Lauf haengt (20 s)'); fail++; bilanz(); process.exit(1);
}, 20000);

const HTML  = fs.readFileSync(path.join(ROOT, 'frontend', 'settings.html'), 'utf8');
const APPJS = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'app.js'), 'utf8');
// ⚠ NUR DIE BEIDEN MASSGEBLICHEN REGELN aus style.css, nicht die ganze Datei:
// jsdoms Selektor-Bibliothek (nwsapi) wirft an einem `:has()` weiter unten, und
// zwar erst in getComputedStyle. Gelesen, nicht abgetippt – und die
// Positivkontrolle unten verlangt, dass beide `display:flex` tragen (sonst
// waere „hidden wuerde nicht reichen" eine Behauptung ohne Messung).
const STYLE = fs.readFileSync(path.join(ROOT, 'frontend', 'css', 'style.css'), 'utf8');
function regel(sel) {
    const m = STYLE.match(new RegExp('(^|\\n)' + sel.replace('.', '\\.') + ' \\{[^}]*\\}'));
    return m ? m[0].trim() : '';
}
const CSS = regel('.btn-link') + '\n' + regel('.login-extras');

function schneide(quelle, name) {
    for (const kopf of ['async function ' + name + '(', 'function ' + name + '(']) {
        const i = quelle.indexOf(kopf);
        if (i < 0) continue;
        const auf = quelle.indexOf('{', i);
        let tief = 0;
        for (let j = auf; j < quelle.length; j++) {
            const c = quelle[j];
            if (c === '{') tief++;
            else if (c === '}') { tief--; if (tief === 0) return quelle.slice(i, j + 1); }
        }
    }
    return null;
}

const F_CHECK = schneide(APPJS, 'checkSecurity');
const F_HINW  = schneide(APPJS, 'zertHinweisAnpassen');
if (!F_CHECK || !F_HINW) {
    console.log('ABBRUCH: checkSecurity / zertHinweisAnpassen nicht in app.js gefunden');
    _bilanz = true; process.exit(2);
}

function warte(n) {
    return new Promise(r => { let i = 0; (function t() { if (++i >= n) r(); else setTimeout(t, 0); })(); });
}

// antwort: Objekt = JSON-Antwort 200; 'fehler' = Netzfehler; 404 = alter Server
async function lauf(url, antwort) {
    const dom = new JSDOM(HTML, { url, runScripts: 'outside-only', pretendToBeVisual: true });
    const w = dom.window;
    const st = w.document.createElement('style');
    st.textContent = CSS;
    w.document.head.appendChild(st);
    w.t = (k) => k;
    const abrufe = [];
    w.fetch = (u) => {
        abrufe.push(String(u).split('?')[0]);
        if (antwort === 'fehler') return Promise.reject(new Error('netz'));
        if (antwort === 404) return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(antwort) });
    };
    w.eval(F_HINW + '\n' + F_CHECK + '\ncheckSecurity();');
    await warte(10);
    const btn = w.document.getElementById('btn-cert-help');
    const box = btn && btn.closest('.login-extras');
    const sichtbar = (el) => {
        for (let p = el; p && p.nodeType === 1; p = p.parentElement) {
            if (w.getComputedStyle(p).display === 'none') return false;
        }
        return true;
    };
    const erg = { abrufe, btn, sichtbar: !!btn && sichtbar(btn), boxSichtbar: !!box && sichtbar(box) };
    w.close();
    return erg;
}

(async function () {
    console.log('── Positivkontrolle');
    pruefe('beide Regeln aus style.css gelesen und mit display:flex',
           /display:\s*flex/.test(regel('.btn-link')) && /display:\s*flex/.test(regel('.login-extras')),
           CSS.slice(0, 80));
    if (fail) { bilanz(); process.exit(2); }
    const basis = await lauf('https://pruef.local/', { ca_ausgestellt: false });
    pruefe('Knopf #btn-cert-help existiert im Markup', !!basis.btn);
    pruefe('… und ist ohne Anlass SICHTBAR (sonst waere „weg" trivial wahr)', basis.sichtbar);
    if (!basis.btn || !basis.sichtbar) { bilanz(); process.exit(2); }

    console.log('── HTTPS');
    const ca = await lauf('https://pruef.local/', { ca_ausgestellt: true });
    pruefe('fragt den Server (/api/cert/status)', ca.abrufe.indexOf('/api/cert/status') >= 0,
           ca.abrufe.join(','));
    pruefe('CA-ausgestellt → Hinweis WEG (der gemeldete Fall)', !ca.sichtbar);
    pruefe('… samt seinem Container (kein leerer Abstand)', !ca.boxSichtbar);

    pruefe('selbstsigniert → Hinweis bleibt', basis.sichtbar);
    const unb = await lauf('https://pruef.local/', { ca_ausgestellt: null });
    pruefe('unbekannt (null) → Hinweis bleibt', unb.sichtbar);
    const truthy = await lauf('https://pruef.local/', { ca_ausgestellt: 'ja' });
    pruefe('nur ein echtes true nimmt ihn weg (kein truthy-Wert)', truthy.sichtbar);
    const netz = await lauf('https://pruef.local/', 'fehler');
    pruefe('Abruf scheitert → Hinweis bleibt', netz.sichtbar);
    const alt = await lauf('https://pruef.local/', 404);
    pruefe('alter Server (404) → Hinweis bleibt', alt.sichtbar);

    console.log('── HTTP');
    const http = await lauf('http://pruef.local/', { ca_ausgestellt: true });
    pruefe('ueber HTTP bleibt der Hinweis, auch wenn der Server „CA" sagt', http.sichtbar);
    pruefe('… und es wird gar nicht erst gefragt',
           http.abrufe.indexOf('/api/cert/status') < 0, http.abrufe.join(','));

    clearTimeout(wachhund);
    bilanz();
    process.exit(fail === 0 ? 0 : 1);
})();
