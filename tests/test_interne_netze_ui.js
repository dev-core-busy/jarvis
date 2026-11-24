/* Interne Netze: Vorschlaege und Vorschau in den System-Einstellungen
 * (app.js _netzeHilfeVerdrahten/_netzeHilfeLaden/_netzeVorschlaegeZeigen/
 * _netzeVorschau, Markup in settings.html).
 *
 * Anlass (2026-11-24): die Liste "Interne Netze" liess sich nur als Freitext
 * pflegen, und ob ein Eintrag wirkt, sah man erst nach dem Speichern an den
 * Plaketten der Profile. Jetzt schlaegt der Server Bereiche vor (eigene
 * Schnittstellen, oeffentliche Profiladressen), ein Klick fuegt sie ins Feld,
 * und eine Vorschau nennt vor dem Speichern, welches Profil seine Einstufung
 * wechselt.
 *
 * Geprueft wird die WIRKUNG: die echten Funktionen werden am Syntaxbaum aus
 * app.js geschnitten und im jsdom-Fenster mit dem echten Markup-Ausschnitt und
 * der echten i18n.js ausgefuehrt; fetch ist eine Attrappe mit der Antwortform
 * der Endpunkte in main.py (Routing ueber den Pfad).
 *
 *     node tests/test_interne_netze_ui.js   Exit 0 gruen, 1 rot, 2 nicht lauffaehig
 */
'use strict';
const fs = require('fs');
const path = require('path');
const fertig = require('./lib/bilanz')({ stumm: true });
const acorn = require('./lib/acorn_laden')();
const { JSDOM } = require('./lib/jsdom_laden')();
const { ausschnitt } = require('./lib/seite_ausschnitt');

const ROOT = path.resolve(__dirname, '..');
const lies = (f) => fs.readFileSync(path.join(ROOT, f), 'utf8');
let ok = 0, fail = 0;
function check(cond, label, detail) {
    if (cond) { ok++; console.log('  OK   ' + label); }
    else { fail++; console.log('  FAIL ' + label + (detail ? ' - ' + detail : '')); }
}
const warte = (ms) => new Promise((r) => setTimeout(r, ms));

// ── Funktionen aus app.js schneiden ──
const APP = lies('frontend/js/app.js');
const NAMEN = ['escapeHtml', '_netzeEintraege', '_netzeHilfeVerdrahten', '_netzeHilfeLaden',
    '_netzeVorschlaegeZeigen', '_netzeVorschau'];
const fn = {};
(function lauf(k) {
    if (!k || typeof k.type !== 'string') return;
    if (k.type === 'FunctionDeclaration' && k.id && NAMEN.includes(k.id.name) && !fn[k.id.name]) {
        fn[k.id.name] = APP.slice(k.start, k.end);
    }
    for (const w of Object.values(k)) {
        if (Array.isArray(w)) w.forEach(lauf);
        else if (w && typeof w.type === 'string') lauf(w);
    }
})(acorn.parse(APP, { ecmaVersion: 'latest', sourceType: 'script' }));
const fehltFn = NAMEN.filter((n) => !fn[n]);
if (fehltFn.length) {
    console.log('ABBRUCH: in app.js nicht gefunden: ' + fehltFn.join(', '));
    process.exit(2);
}

// ── Markup ──
const HTML = lies('frontend/settings.html');
const A = ausschnitt(HTML, ['prof-sect-list-body', 'prof-sect-tuning-body']);
if (A.fehlend.length) {
    console.log('ABBRUCH: Markup fehlt: ' + A.fehlend.join(', '));
    process.exit(2);
}

// ── Attrappe der Endpunkte (Antwortform wie main.py) ──
const PROFILE = [{ id: 'qwen', name: 'Qwen' }, { id: 'gem', name: 'Gemini' }];
const GESPEICHERT = { qwen: { standort: 'extern', quelle: 'auto', grund: 'öffentliche IP-Adresse', auto: 'extern' },
    gem: { standort: 'extern', quelle: 'auto', grund: 'fester Cloud-Endpunkt des Anbieters', auto: 'extern' } };
const VORSCHLAEGE = [
    { netz: '198.51.100.0/24', art: 'schnittstelle', name: '' },
    { netz: '203.0.113.7/32', art: 'profil', name: 'Qwen' },
];
let rufe = [];
function attrappe(url, opt) {
    const pfad = String(url).split('?')[0];
    const methode = (opt && opt.method) || 'GET';
    rufe.push({ pfad, methode, rumpf: opt && opt.body ? JSON.parse(opt.body) : null });
    const antwort = (o) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(o) });
    if (pfad === '/api/settings/interne-netze/vorschlaege' && methode === 'GET') {
        return antwort({ vorschlaege: VORSCHLAEGE });
    }
    if (pfad === '/api/settings/interne-netze/vorschau' && methode === 'POST') {
        const text = JSON.parse(opt.body).interne_netze || '';
        const teile = text.split(/[\s,]+/).filter(Boolean);
        const ungueltig = teile.filter((t) => !/^[0-9.]+\/\d+$/.test(t));
        const st = JSON.parse(JSON.stringify(GESPEICHERT));
        if (teile.includes('203.0.113.7/32')) st.qwen = { standort: 'intern', quelle: 'auto', grund: 'im internen Netz 203.0.113.7/32', auto: 'intern' };
        return antwort({ standorte: st, ungueltig });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
}

(async () => {
    const dom = new JSDOM(A.html, { runScripts: 'outside-only', url: 'https://jarvis.test/settings' });
    const w = dom.window;
    w.eval(lies('frontend/js/i18n.js'));
    w.eval(lies('frontend/js/settings_bedienung.js'));
    w.fetch = attrappe;
    // Die geschnittenen Funktionen teilen ihre Variablen als Closure (wie in
    // app.js); gelesen und gesetzt wird ueber den Zugriff __netze.
    w.eval(`(function () {
        const token = 't';
        let profiles = ${JSON.stringify(PROFILE)};
        let standorte = ${JSON.stringify(GESPEICHERT)};
        let _netzeGespeichert = '';
        let _netzeVorschlaege = [];
        let _netzeVorschauTimer = null;
        ${NAMEN.map((n) => fn[n]).join('\n')}
        window.__netze = { _netzeHilfeVerdrahten, _netzeHilfeLaden, _netzeVorschau,
            setzeGespeichert: (v) => { _netzeGespeichert = v; } };
    })();`);
    if (typeof w.t !== 'function' || !w.__netze) {
        console.log('ABBRUCH: i18n oder Funktionen im Fenster nicht verfuegbar');
        process.exit(2);
    }
    const N = w.__netze;
    const feld = w.document.getElementById('setting-interne-netze');
    const vbox = w.document.getElementById('interne-netze-vorschlaege');
    const pbox = w.document.getElementById('interne-netze-vorschau');

    console.log('\n── Markup');
    const block = w.document.getElementById('interne-netze-block');
    const neu = w.document.getElementById('btn-add-profile');
    const liste = w.document.getElementById('prof-sect-list-body');
    check(block && neu && liste && liste.contains(block),
        'Block "Interne Netze" steht im Container LLM-Profile');
    check(block && neu && (block.compareDocumentPosition(neu) & w.Node.DOCUMENT_POSITION_FOLLOWING),
        'Block steht VOR "+ Neues Profil"');
    check(!w.document.getElementById('prof-sect-tuning-body').querySelector('#setting-interne-netze'),
        'nicht mehr unter System-Einstellungen');
    check(block && block.contains(feld) && block.contains(vbox) && block.contains(pbox)
        && block.contains(w.document.getElementById('btn-save-interne-netze')),
        'Feld, Speichern, Vorschlaege und Vorschau gehoeren zum Block');
    check(!vbox.closest('[hidden]') && !pbox.closest('[hidden]'),
        'Vorschlaege und Vorschau stehen nicht hinter "Details"');
    const hinweis = w.document.getElementById('interne-netze-hinweis');
    const details = block && block.querySelector('[aria-controls="interne-netze-hinweis"]');
    check(hinweis && hinweis.hidden, 'Erlaeuterung ist zunaechst zu');
    if (details) details.click();
    check(hinweis && !hinweis.hidden && details.getAttribute('aria-expanded') === 'true',
        '"Details" klappt die Erlaeuterung auf');
    if (details) details.click();
    check(hinweis && hinweis.hidden, '"Details" klappt sie wieder zu');
    check(pbox.getAttribute('aria-live') === 'polite', 'Vorschau wird Bildschirmlesern angesagt');

    console.log('\n── Vorschlaege');
    N._netzeHilfeVerdrahten();
    N._netzeHilfeVerdrahten();   // zweiter Aufruf darf nicht doppelt verdrahten
    await N._netzeHilfeLaden();
    const knoepfe = () => [...vbox.querySelectorAll('button[data-netz]')];
    check(knoepfe().length === 2, 'Positivkontrolle: beide Vorschlaege als Knopf', vbox.innerHTML);
    check(rufe.some((r) => r.pfad === '/api/settings/interne-netze/vorschlaege'),
        'Vorschlaege kommen vom Server');
    const kProfil = knoepfe().find((b) => b.getAttribute('data-netz') === '203.0.113.7/32');
    check(kProfil && kProfil.textContent.includes('Qwen') && /eigenen Netz/.test(kProfil.textContent),
        'Profilvorschlag nennt das Profil und die Bedingung', kProfil && kProfil.textContent);
    const kSchnitt = knoepfe().find((b) => b.getAttribute('data-netz') === '198.51.100.0/24');
    check(kSchnitt && /Server/.test(kSchnitt.textContent), 'Schnittstellenvorschlag sagt, woher er kommt',
        kSchnitt && kSchnitt.textContent);
    check(pbox.innerHTML === '', 'unveraendertes Feld: keine Vorschau', pbox.innerHTML);

    console.log('\n── Klick fuegt ein, Vorschau folgt');
    rufe = [];
    kProfil.click();
    check(feld.value === '203.0.113.7/32', 'Klick traegt den Bereich ins Feld ein', feld.value);
    const kProfil2 = knoepfe().find((b) => b.getAttribute('data-netz') === '203.0.113.7/32');
    check(kProfil2 && kProfil2.disabled, 'eingetragener Vorschlag ist danach gesperrt (kein Doppeleintrag)');
    knoepfe().find((b) => b.getAttribute('data-netz') === '198.51.100.0/24').click();
    check(feld.value === '203.0.113.7/32, 198.51.100.0/24', 'zweiter Klick haengt mit Komma an', feld.value);
    await warte(700);
    const vRufe = rufe.filter((r) => r.pfad === '/api/settings/interne-netze/vorschau');
    check(vRufe.length === 1, 'Vorschau gebuendelt: ein Abruf nach mehreren Eingaben', String(vRufe.length));
    check(vRufe.length && vRufe[vRufe.length - 1].rumpf.interne_netze === feld.value,
        'Vorschau fragt mit dem UNGESPEICHERTEN Feldinhalt');
    check(/Qwen/.test(pbox.textContent) && /extern/i.test(pbox.textContent) && /intern/i.test(pbox.textContent),
        'Vorschau nennt den Wechsel des Profils', pbox.textContent);
    check(!/Gemini/.test(pbox.textContent), 'unveraendertes Profil steht nicht in der Vorschau', pbox.textContent);
    check(/Speichern/.test(pbox.textContent), 'Vorschau sagt, dass erst Speichern wirkt', pbox.textContent);

    console.log('\n── Ungueltiges und Rueckkehr');
    feld.value = '198.51.100.0/24, quatsch';
    await N._netzeVorschau();
    check(/quatsch/.test(pbox.textContent) && pbox.querySelector('.netze-vorschau-fehler'),
        'ungueltiger Eintrag wird vor dem Speichern genannt', pbox.innerHTML);
    feld.value = '198.51.100.0/24';
    await N._netzeVorschau();
    check(/ändert sich dadurch nichts/.test(pbox.textContent) && !pbox.querySelector('.netze-vorschau-fehler'),
        'gueltig, aber ohne Wechsel: die Vorschau sagt das ausdruecklich', pbox.textContent);
    N.setzeGespeichert('198.51.100.0/24');
    feld.value = '198.51.100.0/24';
    await N._netzeVorschau();
    check(pbox.innerHTML === '', 'Feld wieder wie gespeichert: Vorschau verschwindet', pbox.innerHTML);

    w.close();
    fertig();
    console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
    process.exit(fail ? 1 : 0);
})();
