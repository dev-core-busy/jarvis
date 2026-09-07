/* Waechter: der Neustart-Knopf wird GEKLICKT, nicht gelesen.
 *
 * `tests/test_dienst_neustart.py` prueft den Quelltext – das beantwortet nicht,
 * ob der Klick funktioniert und ob die MELDUNG zur Lage passt. Genau daran
 * haengt aber der Wert des Knopfes: eine Anzeige, die einen Neustart behauptet,
 * der nicht stattgefunden hat, ist schlimmer als keine.
 *
 * Der Verdrahtungsblock wird aus der ECHTEN `app.js` geklammert geschnitten
 * (nicht am ersten "\n}" – das taugt nur fuer mehrzeilige Funktionen) und gegen
 * das ECHTE Markup aus `settings.html` sowie die ECHTEN Texte aus `i18n.js`
 * ausgefuehrt. Die Uhr ist virtualisiert: sonst wartet der Lauf echte 25–90 s.
 *
 * Vier Ausgaenge, jeder eine eigene Pruefung:
 *   1. Neustart klappt (started_at aendert sich) -> Erfolg, mit Sekunden
 *   2. Dienst antwortet DURCHGEHEND mit derselben Startzeit -> "unveraendert
 *      weiter", und zwar ohne 90 s zu warten
 *   3. Dienst kommt nicht zurueck -> "antwortet noch nicht" (NICHT "unveraendert")
 *   4. Rueckfrage abgelehnt -> KEIN Aufruf
 */
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM;
for (const kandidat of [process.env.JSDOM_PATH, 'jsdom',
                        path.resolve(__dirname, '../node_modules/jsdom'),
                        path.resolve(__dirname, '../data/node_modules/jsdom'),
                        '/tmp/node_modules/jsdom',
                        '/usr/share/nodejs/jsdom'].filter(Boolean)) {
    try { JSDOM = require(kandidat).JSDOM; break; } catch (e) { /* naechster */ }
}
if (!JSDOM) {
    console.log('\x1b[31mABBRUCH: jsdom nicht installiert (JSDOM_PATH setzen)\x1b[0m');
    process.exit(2);
}

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0, bilanz = false;

function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function check(name, cond, detail) {
    if (typeof name !== 'string') {
        console.log('\x1b[31mABBRUCH: check() falsch herum\x1b[0m'); process.exit(2);
    }
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function abbruch(t) { console.log('\x1b[31mABBRUCH: ' + t + '\x1b[0m'); process.exit(2); }

// Ein abgebrochener oder haengender Lauf darf nicht wie ein bestandener
// aussehen (Register): die Datei ist eine async-IIFE.
process.on('exit', function (code) {
    if (!bilanz && code === 0) {
        console.log('\x1b[31mABBRUCH: Lauf endete ohne Bilanzzeile\x1b[0m');
        process.exitCode = 1;
    }
});
process.on('unhandledRejection', function (e) {
    console.log('\x1b[31mABBRUCH: unbehandelte Zurueckweisung: ' + e + '\x1b[0m');
    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL\x1b[0m');
    process.exit(1);
});
const WACHHUND = setTimeout(function () {
    bilanz = true;
    console.log('\x1b[31m✗ Wachhund: der Lauf haengt (>25 s)\x1b[0m');
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL\x1b[0m');
    process.exit(1);
}, 25000);

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

// ── Verdrahtungsblock geklammert schneiden ────────────────────────────────
const START = APP.indexOf("const _btnRs = document.getElementById('btn-service-restart');");
if (START < 0) abbruch('Verdrahtung von #btn-service-restart nicht in app.js gefunden');
let tiefe = 0, ENDE = -1;
for (let i = START; i < APP.length; i++) {
    if (APP[i] === '{') tiefe++;
    else if (APP[i] === '}') { tiefe--; if (tiefe === 0) { ENDE = i + 1; break; } }
}
if (ENDE < 0) abbruch('Blockende nicht gefunden');
const BLOCK = APP.slice(START, ENDE);

// Der Schnitt muss den ganzen Handler enthalten und nicht mehr – ohne diese
// Kontrolle prueft der Waechter womoeglich fremden Code (Register).
if (!/addEventListener\('click'/.test(BLOCK) || !/restart_back/.test(BLOCK)
    || /btn-save-llm-max-tokens/.test(BLOCK)) {
    abbruch('Schnitt unplausibel (' + BLOCK.length + ' Zeichen)');
}

// ── Ein Lauf: Seite, Uhr, fetch-Attrappe, Klick ───────────────────────────
async function lauf(opt) {
    const dom = new JSDOM(HTML, {
        url: 'https://localhost/settings',
        runScripts: 'outside-only',
        pretendToBeVisual: false,
    });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    win.eval(I18N);                       // ECHTE Texte, keine t()-Attrappe:
    if (typeof win.t !== 'function') abbruch('window.t fehlt – i18n.js nicht geladen');
    //  eine Attrappe verschluckt die {s}-Platzhalter, und genau die tragen die
    //  Aussage "nach N Sekunden" (Register).

    // Virtuelle Uhr: `schlaf()` springt, statt zu warten. Ohne sie laeuft der
    // Fall "unveraendert" echte 25 s und der Fall "kommt nicht zurueck" 90 s.
    let uhr = 1700000000000;
    const echteImmediate = setImmediate;
    const fakeTimeout = function (cb, ms) { uhr += (ms || 0); return echteImmediate(cb); };
    const fakeDate = function () {};
    fakeDate.now = function () { return uhr; };

    const gerufen = [];
    const gefragt = [];
    let healthAufrufe = 0;
    function antwort(körper, status) {
        return Promise.resolve({
            ok: (status || 200) < 400, status: status || 200,
            json: function () { return Promise.resolve(körper); },
        });
    }
    const attrappe = function (url, o) {
        const p = String(url).split('?')[0];
        gerufen.push({ pfad: p, opt: o || {} });
        if (p === '/api/health') {
            healthAufrufe++;
            const s = opt.health(healthAufrufe);
            if (s === 'weg') return Promise.reject(new Error('ECONNREFUSED'));
            return antwort({ status: 'ok', started_at: s });
        }
        if (p === '/api/system/restart') {
            return opt.restartFehler ? antwort({}, 500) : antwort({ ok: true });
        }
        return antwort({});
    };
    win.confirm = function (t) { gefragt.push(t); return opt.bestaetigen !== false; };

    const btn = win.document.getElementById('btn-service-restart');
    if (!btn) abbruch('#btn-service-restart nicht im echten Markup von settings.html');

    // Block im gestellten Scope ausfuehren.
    const fn = new Function('document', 'window', 'token', 'fetch', 'setTimeout', 'Date',
                            BLOCK + '\nreturn null;');
    fn(win.document, win, 'test-token', attrappe, fakeTimeout, fakeDate);

    btn.dispatchEvent(new win.Event('click', { bubbles: true }));
    // Auf das Ende des Handlers warten (echte Microtasks, virtuelle Uhr).
    for (let i = 0; i < 4000; i++) {
        await new Promise(r => echteImmediate(r));
        if (!btn.disabled && gerufen.some(g => g.pfad === '/api/system/restart')) break;
        if (opt.bestaetigen === false && gefragt.length) break;
    }
    const st = win.document.getElementById('service-restart-status');
    const aus = {
        text: st ? st.textContent : null,
        klassen: st ? st.className : null,
        gerufen, gefragt, btn, healthAufrufe,
        virtuelleSekunden: Math.round((uhr - 1700000000000) / 1000),
    };
    try { win.close(); } catch (e) {}
    return aus;
}

(async function () {
    // ══ 1. Der Regelfall ══════════════════════════════════════════════════
    abschnitt('1 – Neustart klappt: der Erfolg ist GEMESSEN');

    const a = await lauf({
        // Erst der alte Prozess, dann weg, dann ein NEUER (andere Startzeit).
        health: (n) => (n === 1 ? 1000 : n <= 3 ? 'weg' : 2000),
    });
    check('es wurde gefragt, bevor etwas passierte', a.gefragt.length === 1, a.gefragt);
    check('POST /api/system/restart gerufen',
          a.gerufen.some(g => g.pfad === '/api/system/restart' && g.opt.method === 'POST'));
    check('der Vergleichswert wurde VOR dem Neustart geholt',
          a.gerufen.findIndex(g => g.pfad === '/api/health')
          < a.gerufen.findIndex(g => g.pfad === '/api/system/restart'),
          a.gerufen.map(g => g.pfad).join(' → '));
    check('Erfolgsmeldung erscheint', /✓/.test(a.text || ''), a.text);
    check('Erfolgs-Klasse gesetzt, keine Warn-Klasse daneben',
          /svc-ok/.test(a.klassen || '') && !/svc-warn/.test(a.klassen || ''), a.klassen);
    check('sie nennt die Wartezeit als ZAHL (Platzhalter aufgelöst)',
          /\d/.test(a.text || '') && !/\{s\}/.test(a.text || ''), a.text);
    check('Knopf ist danach wieder bedienbar', a.btn.disabled === false);
    check('der Dienst wurde als abwesend erlebt und kam zurueck',
          a.healthAufrufe >= 3, a.healthAufrufe);

    // ══ 2. Der gefaehrliche Fall ══════════════════════════════════════════
    abschnitt('2 – Dienst laeuft unveraendert weiter: KEIN Erfolg melden');

    const b = await lauf({ health: () => 1000 });   // immer derselbe Prozess
    check('meldet NICHT "wieder erreichbar"', !/✓/.test(b.text || ''), b.text);
    check('meldet ausdruecklich "unveraendert"',
          /unver|still the same/i.test(b.text || ''), b.text);
    check('Warn-Klasse, nicht Erfolgs-Klasse',
          /svc-warn/.test(b.klassen || '') && !/svc-ok/.test(b.klassen || ''), b.klassen);
    check('wartet dafuer NICHT den ganzen Rueckkehr-Deckel ab (<= 30 virt. s)',
          b.virtuelleSekunden <= 30, b.virtuelleSekunden + ' s');

    // ══ 3. Dienst kommt nicht zurueck ═════════════════════════════════════
    abschnitt('3 – Dienst kommt nicht zurueck: andere Aussage');

    const c = await lauf({ health: (n) => (n === 1 ? 1000 : 'weg') });
    check('meldet NICHT "unveraendert weiter"',
          !/unver|still the same/i.test(c.text || ''), c.text);
    check('meldet "antwortet noch nicht"',
          /antwortet|not responding/i.test(c.text || ''), c.text);
    check('Warn-Klasse', /svc-warn/.test(c.klassen || '')
          && !/svc-ok/.test(c.klassen || ''), c.klassen);
    check('Knopf wieder bedienbar (sonst waere die Seite gesperrt)',
          c.btn.disabled === false);

    // ══ 3b. Der erste Poll trifft noch den ALTEN Prozess ══════════════════
    abschnitt('3b – Langsames systemd: erst der alte Prozess, dann der neue');

    // Realistischer Fall: das Backend wartet 1 s, systemd braucht laenger als
    // unsere 2,5 s Vorlauf. Wer beim ERSTEN erfolgreichen Poll aufhoert, sieht
    // die alte Startzeit und meldete "laeuft unveraendert weiter" – mitten in
    // einem gelingenden Neustart.
    const f = await lauf({ health: (n) => (n <= 2 ? 1000 : n <= 4 ? 'weg' : 2000) });
    check('meldet Erfolg, nicht "unveraendert"',
          /✓/.test(f.text || '') && !/unver|still the same/i.test(f.text || ''), f.text);

    // ══ 3c. Erst Antwort, dann stirbt der Dienst ══════════════════════════
    abschnitt('3c – Dienst antwortet erst, stirbt dann: keine Erfolgs-/Gleichheits-Luege');

    // Hier zaehlt, dass `jetzt` im Fehlerzweig auf null zurueckgesetzt wird:
    // sonst steht dort der Wert von VOR dem Herunterfahren, und ein toter
    // Dienst wuerde als "laeuft unveraendert weiter" gemeldet.
    const g = await lauf({ health: (n) => (n <= 2 ? 1000 : 'weg') });
    check('meldet NICHT "unveraendert weiter"',
          !/unver|still the same/i.test(g.text || ''), g.text);
    check('meldet "antwortet noch nicht"',
          /antwortet|not responding/i.test(g.text || ''), g.text);

    // ══ 4. Abgelehnte Rueckfrage ══════════════════════════════════════════
    abschnitt('4 – Rueckfrage abgelehnt: nichts passiert');

    const d = await lauf({ bestaetigen: false, health: () => 1000 });
    check('gefragt wurde', d.gefragt.length === 1);
    check('KEIN Neustart-Aufruf',
          !d.gerufen.some(g => g.pfad === '/api/system/restart'),
          d.gerufen.map(g => g.pfad).join(','));
    check('kein Health-Abruf noetig', d.healthAufrufe <= 1, d.healthAufrufe);
    check('kein Statustext', !(d.text || '').trim(), d.text);

    // ══ 5. Fehlgeschlagener Auslöser ══════════════════════════════════════
    abschnitt('5 – Der Endpunkt antwortet mit Fehler');

    const e = await lauf({ restartFehler: true, health: () => 1000 });
    check('meldet den Fehlschlag', /✗/.test(e.text || ''), e.text);
    check('und wartet nicht auf einen Dienst, der nie neu startet',
          e.virtuelleSekunden <= 1, e.virtuelleSekunden + ' s');
    check('Knopf wieder bedienbar', e.btn.disabled === false);

    clearTimeout(WACHHUND);
    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
    process.exit(fail === 0 ? 0 : 1);
})();
