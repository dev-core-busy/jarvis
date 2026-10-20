#!/usr/bin/env node
/**
 * Newsfeed-Laufband (frontend/js/newsfeed.js) – das VERHALTEN, nicht der Text.
 *
 * Das echte Modul laeuft in jsdom unter einer EIGENEN Uhr (setTimeout,
 * clearTimeout und Date.now des Fensters sind ersetzt). Damit sind die
 * Zeitzusagen messbar, ohne echte Sekunden zu warten:
 *
 *   1. Drei Meldungen: Meldung bleibt GENAU `verweil_s` stehen, rollt dann in
 *      `scroll_s` nach oben; nach der letzten rollt das Band auf die Kopie der
 *      ersten und springt OHNE Uebergang auf den Anfang zurueck.
 *   2. Maus ueber der Kachel haelt an – mit RESTZEIT, nicht von vorn.
 *   3. Eine einzige Meldung: kein Zeitgeber, keine Kopie, kein Balken.
 *   4. Fremdtext wird als Text gesetzt, nie als Markup.
 *   5. „Bewegung reduzieren": keine Kopie, Wechsel per Ueberblendung.
 *   6. stoppen() haelt alles an.
 *   7. Portal: portalStart zeigt nur mit Meldungen, setzt ein unveraendertes
 *      Band nicht zurueck, und ein Fehlschlag nimmt nichts weg.
 *   8. Verdrahtung (acorn): portal_seite.js ruft portalStart NUR im Zweig
 *      `permissions.newsfeed`; portal.html und settings.html binden ein.
 *
 *   node tests/test_newsfeed_ui.js
 */
require('./lib/bilanz')();

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const acorn = require('./lib/acorn_laden')();
const sitzungLaden = require('./lib/sitzung_laden');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  OK   ' + t); }
    else { fail++; console.log('  FAIL ' + t + (d !== undefined ? ' - ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');
const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');

/** Fenster mit eigener Uhr und echtem newsfeed.js. */
function fenster(opt) {
    opt = opt || {};
    const dom = new JSDOM('<!DOCTYPE html><body><section id="w" hidden></section>'
        + '<section id="pt-newsfeed" class="nf-kachel" hidden></section></body>',
        { url: 'https://localhost/portal', runScripts: 'outside-only' });
    const w = dom.window;
    let jetzt = 1000000, nr = 0;
    const plan = new Map();
    w.setTimeout = (fn, ms) => { const id = ++nr; plan.set(id, { at: jetzt + (ms || 0), fn }); return id; };
    w.clearTimeout = (id) => { plan.delete(id); };
    w.setInterval = () => 0;
    w.Date.now = () => jetzt;
    w.matchMedia = () => ({ matches: !!opt.ruhig, addListener() {}, removeListener() {} });
    sitzungLaden(w, { token: 'testtoken' });
    w.eval(lies('frontend/js/newsfeed.js'));
    if (!w.JarvisNewsfeed || typeof w.JarvisNewsfeed.ticker !== 'function') {
        console.log('ABBRUCH: newsfeed.js setzt kein window.JarvisNewsfeed');
        process.exit(2);
    }
    /** Uhr um ms vorstellen und faellige Zeitgeber in Reihenfolge ausfuehren. */
    function vor(ms) {
        const ziel = jetzt + ms;
        for (;;) {
            let naechst = null;
            for (const [id, e] of plan) if (e.at <= ziel && (!naechst || e.at < naechst[1].at)) naechst = [id, e];
            if (!naechst) break;
            plan.delete(naechst[0]);
            jetzt = naechst[1].at;
            naechst[1].fn();
        }
        jetzt = ziel;
    }
    return { dom, w, vor, offen: () => plan.size };
}

const DREI = [
    { titel: 'Erste', text: 'Satz eins.', erstellt: '2026-10-20T09:00:00' },
    { titel: 'Zweite', text: 'Satz zwei.', erstellt: '2026-10-19T09:00:00' },
    { titel: 'Dritte', text: 'Satz drei.', erstellt: '2026-10-18T09:00:00' },
];
const band = (w) => w.document.querySelector('#w .nf-band');
const zaehler = (w) => (w.document.querySelector('#w .nf-zaehler') || {}).textContent;

(async () => {
    abschnitt('1. Ablauf mit drei Meldungen (3 s / 0,8 s)');
    {
        const { w, vor } = fenster();
        const wurzel = w.document.getElementById('w');
        const t = w.JarvisNewsfeed.ticker(wurzel, DREI, { verweil_s: 3, scroll_s: 0.8 });
        // Positivkontrolle: das Band ist ueberhaupt gezeichnet.
        if (!band(w)) { console.log('ABBRUCH: kein Band gezeichnet'); process.exit(2); }
        const bloecke = band(w).querySelectorAll('.nf-block');
        pruefe(!wurzel.hidden, 'Kachel sichtbar');
        pruefe(bloecke.length === 4, '3 Meldungen + 1 Kopie', bloecke.length);
        pruefe(bloecke[3] && bloecke[3].getAttribute('aria-hidden') === 'true', 'Kopie ist fuer Vorleser verborgen');
        pruefe(bloecke[3] && bloecke[3].querySelector('.nf-titel').textContent === 'Erste', 'Kopie zeigt die erste Meldung');
        pruefe(zaehler(w) === '1/3', 'Zaehler 1/3', zaehler(w));
        pruefe(band(w).style.transform === '', 'Start ohne Verschiebung', band(w).style.transform);
        pruefe(/20\.10\.2026/.test(bloecke[0].querySelector('.nf-datum').textContent), 'Datum deutsch formatiert',
               bloecke[0].querySelector('.nf-datum').textContent);
        vor(2999);
        pruefe(band(w).style.transform === '', 'nach 2,999 s steht Meldung 1 noch');
        vor(1);
        pruefe(band(w).style.transform === 'translateY(-25%)', 'nach 3 s rollt zu Meldung 2', band(w).style.transform);
        pruefe(/transform 0\.8s/.test(band(w).style.transition), 'Rolldauer 0,8 s', band(w).style.transition);
        pruefe(zaehler(w) === '2/3', 'Zaehler 2/3', zaehler(w));
        vor(800 + 2999);
        pruefe(band(w).style.transform === 'translateY(-25%)', 'Meldung 2 bleibt volle Verweilzeit NACH dem Rollen');
        vor(1);
        pruefe(band(w).style.transform === 'translateY(-50%)', 'dann Meldung 3', band(w).style.transform);
        vor(3800);
        pruefe(band(w).style.transform === 'translateY(-75%)', 'nach der letzten: rollt auf die Kopie', band(w).style.transform);
        pruefe(zaehler(w) === '1/3', 'Zaehler zeigt dabei 1/3', zaehler(w));
        vor(800);
        pruefe(band(w).style.transform === '' && band(w).style.transition === 'none',
               'danach Sprung OHNE Uebergang an den Anfang', band(w).style.transform + ' | ' + band(w).style.transition);
        pruefe(t.index() === 0, 'Index wieder 0');
        vor(3000);
        pruefe(band(w).style.transform === 'translateY(-25%)', 'zweite Runde laeuft weiter');
        t.stoppen();
    }

    abschnitt('2. Anhalten mit Restzeit');
    {
        const { w, vor } = fenster();
        const wurzel = w.document.getElementById('w');
        const t = w.JarvisNewsfeed.ticker(wurzel, DREI, { verweil_s: 3, scroll_s: 0.8 });
        vor(1000);
        wurzel.dispatchEvent(new w.Event('mouseenter'));
        pruefe(wurzel.classList.contains('nf-pause'), 'Klasse nf-pause gesetzt (haelt den Balken an)');
        vor(20000);
        pruefe(band(w).style.transform === '', 'waehrend Maus darueber: kein Wechsel');
        wurzel.dispatchEvent(new w.Event('mouseleave'));
        vor(1999);
        pruefe(band(w).style.transform === '', 'nach Fortsetzen: Rest 2 s noch nicht um');
        vor(1);
        pruefe(band(w).style.transform === 'translateY(-25%)', 'nach Rest 2 s Wechsel (nicht von vorn)', band(w).style.transform);
        // Anhalten waehrend des ROLLENS bricht den Schritt nicht ab.
        vor(400);
        wurzel.dispatchEvent(new w.Event('mouseenter'));
        vor(10000);
        pruefe(band(w).style.transform === 'translateY(-25%)', 'Rollschritt laeuft zu Ende, dann Halt');
        wurzel.dispatchEvent(new w.Event('mouseleave'));
        vor(2999);
        pruefe(band(w).style.transform === 'translateY(-25%)', 'nach Halt im Rollen: volle Verweilzeit');
        vor(1);
        pruefe(band(w).style.transform === 'translateY(-50%)', 'dann weiter zu Meldung 3');
        t.stoppen();
    }

    abschnitt('3. Eine einzige Meldung');
    {
        const { w, vor, offen } = fenster();
        const wurzel = w.document.getElementById('w');
        w.JarvisNewsfeed.ticker(wurzel, DREI.slice(0, 1), { verweil_s: 3, scroll_s: 0.8 });
        pruefe(!wurzel.hidden, 'sichtbar');
        pruefe(band(w).querySelectorAll('.nf-block').length === 1, 'keine Kopie');
        pruefe(offen() === 0, 'kein Zeitgeber geplant', offen());
        pruefe(w.document.querySelector('#w .nf-fortschritt').hidden, 'Fortschrittsbalken verborgen');
        vor(10000);
        pruefe(band(w).style.transform === '', 'nichts bewegt sich');
    }

    abschnitt('4. Fremdtext als Text');
    {
        const { w } = fenster();
        const wurzel = w.document.getElementById('w');
        w.JarvisNewsfeed.ticker(wurzel, [{ titel: '<img src=x onerror="alert(1)">', text: '<b>fett</b>', erstellt: 'kaputt' }], {});
        pruefe(!wurzel.querySelector('img') && !wurzel.querySelector('.nf-text b'), 'kein Markup aus Titel/Text');
        pruefe(wurzel.querySelector('.nf-titel').textContent.indexOf('<img') === 0, 'Titel woertlich');
        pruefe(wurzel.querySelector('.nf-datum').textContent === '', 'kaputtes Datum -> leer statt "Invalid Date"');
    }

    abschnitt('5. Bewegung reduzieren');
    {
        const { w, vor } = fenster({ ruhig: true });
        const wurzel = w.document.getElementById('w');
        w.JarvisNewsfeed.ticker(wurzel, DREI, { verweil_s: 3, scroll_s: 0.8 });
        pruefe(band(w).querySelectorAll('.nf-block').length === 3, 'keine Kopie (kein Rollen)');
        vor(3000);
        pruefe(band(w).style.opacity === '0' && /opacity/.test(band(w).style.transition), 'blendet aus statt zu rollen');
        vor(400);
        pruefe(band(w).style.opacity === '1' && band(w).style.transform === 'translateY(-33.333333333333336%)',
               'blendet Meldung 2 ein', band(w).style.transform);
        vor(400 + 3000 + 800);
        vor(3000 + 800);
        pruefe(band(w).style.transform === '', 'nach Meldung 3 wieder Meldung 1 (ohne Kopie)', band(w).style.transform);
    }

    abschnitt('6. stoppen()');
    {
        const { w, vor, offen } = fenster();
        const wurzel = w.document.getElementById('w');
        const t = w.JarvisNewsfeed.ticker(wurzel, DREI, { verweil_s: 3, scroll_s: 0.8 });
        t.stoppen();
        pruefe(offen() === 0, 'kein Zeitgeber mehr geplant', offen());
        vor(20000);
        pruefe(band(w).style.transform === '', 'nichts bewegt sich nach stoppen()');
    }

    abschnitt('7. Portal: portalStart');
    {
        const { w, vor } = fenster();
        let antwort = { ok: true, eintraege: [], verweil_s: 3, scroll_s: 0.8 }, status = 200, aufrufe = 0, kopf = '';
        w.fetch = (url, o) => {
            aufrufe++;
            kopf = (o && o.headers && o.headers.Authorization) || '';
            if (url.split('?')[0] !== '/api/newsfeed') return Promise.reject(new Error('falsche Adresse ' + url));
            return Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(antwort) });
        };
        const kachel = w.document.getElementById('pt-newsfeed');
        await w.JarvisNewsfeed.portalStart();
        pruefe(aufrufe === 1 && kopf === 'Bearer testtoken', 'ein Abruf mit Sitzungstoken', aufrufe + ' ' + kopf);
        pruefe(kachel.hidden, 'ohne Meldungen bleibt die Kachel verborgen');
        // Zweiter Start ist wirkungslos (kein zweites Intervall).
        await w.JarvisNewsfeed.portalStart();
        pruefe(aufrufe === 1, 'zweiter portalStart ruft nicht erneut ab', aufrufe);
    }
    {
        // Frisches Fenster: Nachladen gleicher Daten setzt das Band nicht zurueck.
        const { w, vor } = fenster();
        let intervall = null;
        w.setInterval = (fn) => { intervall = fn; return 1; };
        let antwort = { ok: true, eintraege: DREI, verweil_s: 3, scroll_s: 0.8 }, status = 200;
        w.fetch = () => Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(antwort) });
        const kachel = w.document.getElementById('pt-newsfeed');
        await w.JarvisNewsfeed.portalStart();
        const b = () => kachel.querySelector('.nf-band');
        pruefe(!kachel.hidden && kachel.querySelectorAll('.nf-block').length === 4, 'mit Meldungen sichtbar');
        pruefe(typeof intervall === 'function', 'Nachladen ist eingeplant');
        vor(3000);
        const vorher = b();
        await intervall();
        pruefe(b() === vorher && b().style.transform === 'translateY(-25%)', 'gleiche Daten: Band laeuft weiter');
        status = 500;
        await intervall();
        pruefe(!kachel.hidden && b() === vorher, 'Serverfehler: sichtbare Meldungen bleiben');
        status = 200;
        antwort = { ok: true, eintraege: DREI.slice(1), verweil_s: 3, scroll_s: 0.8 };
        await intervall();
        pruefe(kachel.querySelector('.nf-titel').textContent === 'Zweite', 'neue Daten: neu gezeichnet');
        antwort = { ok: true, eintraege: [], verweil_s: 3, scroll_s: 0.8 };
        await intervall();
        pruefe(kachel.hidden, 'alle Meldungen geloescht: Kachel verschwindet');
    }

    abschnitt('8. Verdrahtung');
    {
        const quelle = lies('frontend/js/portal_seite.js');
        const baum = acorn.parse(quelle, { ecmaVersion: 2020 });
        // Jeder Aufruf von *.portalStart() muss in einem if stehen, dessen
        // Bedingung `permissions.newsfeed` liest.
        const treffer = [];
        (function lauf(k, ifs) {
            if (!k || typeof k.type !== 'string') return;
            if (k.type === 'CallExpression' && k.callee.type === 'MemberExpression'
                && k.callee.property.name === 'portalStart') treffer.push(ifs.slice());
            const naechste = k.type === 'IfStatement' ? ifs.concat([quelle.slice(k.test.start, k.test.end)]) : ifs;
            for (const s of Object.keys(k)) {
                const v = k[s];
                if (Array.isArray(v)) v.forEach((x) => lauf(x, s === 'consequent' ? naechste : ifs));
                else if (v && typeof v.type === 'string') lauf(v, s === 'consequent' ? naechste : ifs);
            }
        })(baum, []);
        pruefe(treffer.length === 1, 'portal_seite.js ruft portalStart genau einmal', treffer.length);
        pruefe(treffer.length > 0 && treffer.every((ifs) => ifs.some((b) => /permissions\.newsfeed\b/.test(b))),
               'nur im Zweig permissions.newsfeed', JSON.stringify(treffer));
        const portal = lies('frontend/portal.html');
        const iNf = portal.indexOf('/static/js/newsfeed.js?v='), iPs = portal.indexOf('/static/js/portal_seite.js?v=');
        pruefe(iNf > -1 && iNf < iPs, 'portal.html: newsfeed.js vor portal_seite.js eingebunden', iNf + ' ' + iPs);
        pruefe(/<section id="pt-newsfeed"[^>]*\bhidden\b/.test(portal), 'portal.html: Kachel vorbelegt verborgen');
        pruefe(portal.indexOf('/static/css/newsfeed.css?v=') > -1, 'portal.html: newsfeed.css eingebunden');
        const pc = portal.indexOf('<div class="pt-cards">'), pn = portal.indexOf('id="pt-newsfeed"');
        pruefe(pn > -1 && pn < pc, 'Kachel steht VOR (ausserhalb) dem Kartenraster');
        const st = lies('frontend/settings.html');
        pruefe(st.indexOf('/static/js/newsfeed.js?v=') > -1 && st.indexOf('/static/js/newsfeed_admin.js?v=') > -1,
               'settings.html: newsfeed.js + newsfeed_admin.js eingebunden');
        pruefe(/id="settings-tab-btn-newsfeed"/.test(st) && /id="settings-tab-newsfeed"/.test(st), 'settings.html: Reiter-Knopf + Inhalt');
        pruefe(/newsfeed:\s*'settings-tab-btn-newsfeed'/.test(lies('frontend/js/skillcfg.js')),
               'skillcfg.js: Reiter nur bei aktivem Skill');
    }

    console.log(`\n${ok} OK, ${fail} FAIL`);
    process.exit(fail ? 1 : 0);
})();
