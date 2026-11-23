/* Waechter: Zertifikathinweis auf der Anmeldemaske nur bei UNSICHERER Verbindung
 * (gemeldet 2026-11-18, erneut 2026-11-20: „entferne ENDLICH den ueberfluessigen
 * 'SSL Zertifikat & Verbindung Hilfe' button, wenn eine sichere HTTPS Verbindung
 * hergestellt ist").
 *
 * ⚠ WARUM DIE ZUSAGE SICH GEAENDERT HAT: bis 2026-11-20 entschied eine
 * Server-Auskunft (`GET /api/cert/status` – „ist mein Zertifikat von einer
 * Zertifizierungsstelle ausgestellt?"). Die beantwortet eine ANDERE Frage als
 * die gestellte: auf DEV (selbst ausgestelltes Zertifikat, `ca_ausgestellt:
 * false`) blieb der Knopf stehen, obwohl der Browser das Zertifikat importiert
 * hat und die Verbindung gruen ist. Massgeblich ist jetzt allein die
 * VERBINDUNG, und der Endpunkt ist ersatzlos entfallen.
 *
 * Gemessen wird die WIRKUNG am ECHTEN Markup (settings.html = die Seite unter
 * "/") mit der ECHTEN `checkSecurity` aus app.js, geschnitten und im Fenster
 * ausgefuehrt.
 *
 * Die Faelle:
 *   HTTPS                 → Hinweis WEG (der gemeldete Fall)
 *   HTTP auf localhost    → Hinweis WEG (verschluesselt nicht noetig, lokal)
 *   HTTP, fremder Host    → Hinweis SICHTBAR (dort hilft die Anleitung wirklich)
 *
 * ⚠ GEPRUEFT WIRD DIE BERECHNETE SICHTBARKEIT, NICHT DAS `hidden`-ATTRIBUT:
 * `.btn-link` und `.login-extras` setzen `display:flex` und ueberstimmen
 * `hidden` (Register: CSS und DOM). Deshalb wird style.css eingebunden und
 * `getComputedStyle` gelesen.
 *
 * ⚠ Und es wird gemessen, dass GAR KEIN Server abgefragt wird – ein
 * wiederauferstandener `/api/cert/status`-Abruf waere genau der alte Fehler.
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
const wachhund = require('./lib/wachhund')(() => {
    console.log('  FAIL Wachhund: Lauf haengt (20 s)'); fail++; bilanz(); process.exit(1);
}, 20000);

const HTML  = fs.readFileSync(path.join(ROOT, 'frontend', 'settings.html'), 'utf8');
// Ausschnitt statt der VOLLEN settings.html: checkSecurity fasst nur die
// Anmeldemaske, das Sicherheitsband und den Zertifikatsdialog an (2026-11-23,
// die vollen Aufbauten waren der groesste Teil der Laufzeit). Die einzige
// .login-extras der Seite liegt in der Anmeldemaske. Regeln:
// tests/lib/seite_ausschnitt.js.
const { ausschnitt } = require('./lib/seite_ausschnitt');
const AUSSCHNITT = ausschnitt(HTML, ['login-screen', 'security-banner', 'cert-modal'], { skripte: true });
const APPJS = fs.readFileSync(path.join(ROOT, 'frontend', 'js', 'app.js'), 'utf8');
// ⚠ NUR DIE BEIDEN MASSGEBLICHEN REGELN aus style.css, nicht die ganze Datei:
// jsdoms Selektor-Bibliothek (nwsapi) wirft an einem `:has()` weiter unten, und
// zwar erst in getComputedStyle. Gelesen, nicht abgetippt – und die
// Positivkontrolle unten verlangt, dass beide `display:flex` tragen (sonst
// waere „der Inline-Style ist noetig" eine Behauptung ohne Messung).
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
const F_ZEIG  = schneide(APPJS, 'zertHinweisZeigen');
if (!F_CHECK || !F_ZEIG) {
    console.log('ABBRUCH: checkSecurity / zertHinweisZeigen nicht in app.js gefunden');
    _bilanz = true; process.exit(2);
}

function warte(n) {
    return new Promise(r => { let i = 0; (function t() { if (++i >= n) r(); else setTimeout(t, 0); })(); });
}

async function lauf(url) {
    const dom = new JSDOM(AUSSCHNITT.html, { url, runScripts: 'outside-only', pretendToBeVisual: true });
    const w = dom.window;
    const st = w.document.createElement('style');
    st.textContent = CSS;
    w.document.head.appendChild(st);
    w.t = (k) => k;
    // Jeder Abruf wird festgehalten UND scheitert: wer hier wieder einen Server
    // fragt, darf davon nicht abhaengen.
    const abrufe = [];
    w.fetch = (u) => { abrufe.push(String(u).split('?')[0]); return Promise.reject(new Error('netz')); };
    w.eval(F_ZEIG + '\n' + F_CHECK + '\ncheckSecurity();');
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
    pruefe('Ausschnitt der Proben: Anmeldemaske, Band und Dialog gefunden (Positivkontrolle)',
           AUSSCHNITT.fehlend.length === 0, AUSSCHNITT.fehlend.join(', '));
    if (fail) { bilanz(); process.exit(2); }

    // Die Messung muss Sichtbarkeit ueberhaupt feststellen koennen – sonst waere
    // jedes „WEG" trivial wahr. Das belegt der unsichere Fall: dort blendet
    // checkSecurity den Knopf ein, und zwar samt Container.
    const unsicher = await lauf('http://pruef.local/');
    pruefe('Knopf #btn-cert-help existiert im Markup', !!unsicher.btn);
    pruefe('… und wird bei unsicherer Verbindung SICHTBAR (Messung sieht Sichtbarkeit)',
           unsicher.sichtbar);
    pruefe('… samt seinem Container', unsicher.boxSichtbar);
    // ⚠ ZWEI URSACHEN, ZWEI SIGNALE (Register): fehlt der Knopf im Markup, kann
    // hier nichts gemessen werden (Exit 2). Ist er da und bleibt unsichtbar,
    // ist das ein PRODUKTBEFUND – die Hilfe fehlt genau dort, wo sie gebraucht
    // wird – und jede folgende „WEG"-Pruefung waere trivial wahr (Exit 1).
    if (!unsicher.btn) { bilanz(); process.exit(2); }
    if (!unsicher.sichtbar) { bilanz(); process.exit(1); }

    console.log('── HTTPS (der gemeldete Fall)');
    const https = await lauf('https://pruef.local/');
    pruefe('ueber HTTPS → Hinweis WEG', !https.sichtbar);
    pruefe('… samt seinem Container (kein leerer Abstand)', !https.boxSichtbar);
    pruefe('… und es wird dafuer KEIN Server gefragt',
           https.abrufe.length === 0, https.abrufe.join(','));

    console.log('── lokal');
    const lokal = await lauf('http://localhost:8000/');
    pruefe('localhost ohne HTTPS → Hinweis WEG', !lokal.sichtbar);
    const lokal2 = await lauf('http://127.0.0.1:8000/');
    pruefe('127.0.0.1 ohne HTTPS → Hinweis WEG', !lokal2.sichtbar);

    console.log('── Markup-Vorgabe');
    // Faellt app.js aus, muss der Knopf WEG bleiben statt faelschlich zu
    // erscheinen: die Vorgabe im Markup ist `display:none`, nicht `hidden`.
    const roh = new JSDOM(AUSSCHNITT.html, { url: 'https://pruef.local/' });
    const rohBox = roh.window.document.querySelector('.login-extras');
    pruefe('Container traegt im Markup display:none (kein Aufblitzen, kein hidden)',
           !!rohBox && /display:\s*none/.test(rohBox.getAttribute('style') || ''),
           rohBox && rohBox.getAttribute('style'));
    roh.window.close();

    console.log('── keine Rueckkehr der alten Auskunft');
    // Gesucht wird der AUFRUF, nicht das Wort: die Begruendung oben in app.js
    // nennt den alten Endpunkt absichtlich (Register: ein Waechter, der seine
    // eigene Begruendung liest, prueft nichts).
    pruefe('app.js ruft nirgends mehr /api/cert/status ab',
           !/fetch\s*\(\s*['"`][^'"`]*\/api\/cert\/status/.test(APPJS));

    clearTimeout(wachhund);
    bilanz();
    process.exit(fail === 0 ? 0 : 1);
})();
