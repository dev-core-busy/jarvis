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
 *   9. Ausblenden im Portal: × schickt den GEZEIGTEN Stand, verbirgt erst nach
 *      Bestaetigung, ein Fehlschlag bleibt sichtbar am Knopf; eine neue
 *      Neuigkeit zeigt wieder. Ohne `schliessen` (Vorschau) gibt es kein ×.
 *  10. Admin-Reiter (echtes settings.html-Markup): deaktivierte Meldung ist
 *      gekennzeichnet, ohne Deaktivieren-Knopf, fehlt in der Vorschau und
 *      zaehlt nicht zu „im Portal sichtbar"; Deaktivieren ruft den Endpunkt.
 *  11. Vor/Zurueck/Pause (echte Klicks): zurueck von der ersten ueber die
 *      Kopie zur letzten, vor ab dem Ziel eines halben Rollschritts, Pause
 *      haelt ueber das Verlassen der Maus hinweg, Weiter mit Restzeit; bei
 *      einer Meldung keine Knoepfe; mit reduzierter Bewegung blaettern.
 *  12. Anzahl im Admin-Reiter: das Feld zeigt den gespeicherten Wert, die
 *      Vorschau folgt dem FELD (1 → eine Meldung, „alle" → alle aktiven,
 *      Feld dann gesperrt), „im Portal sichtbar" folgt dem GESPEICHERTEN Wert;
 *      Speichern schickt `anzahl` mit; gespeichertes „alle" hakt das Kaestchen.
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

    abschnitt('9. Ausblenden im Portal');
    {
        const { w } = fenster();
        // Ohne schliessen: kein × (Vorschau im Reiter).
        w.JarvisNewsfeed.ticker(w.document.getElementById('w'), DREI, {});
        pruefe(!w.document.querySelector('#w .nf-zu'), 'ohne schliessen kein ×-Knopf');
    }
    {
        const { w } = fenster();
        w.eval(lies('frontend/js/icons.js'));
        const STAND = '2026-10-20T09:00:00';
        let antwort = { ok: true, eintraege: DREI, verweil_s: 3, scroll_s: 0.8, stand: STAND, ausgeblendet: false };
        let postOk = false, gesendet = null, intervall = null;
        w.setInterval = (fn) => { intervall = fn; return 1; };
        w.fetch = (url, o) => {
            const pfad = url.split('?')[0];
            if (pfad === '/api/newsfeed/ausblenden') {
                gesendet = { methode: o && o.method, rumpf: JSON.parse((o && o.body) || 'null'),
                             auth: o && o.headers && o.headers.Authorization };
                return Promise.resolve({ ok: postOk, status: postOk ? 200 : 500, json: () => Promise.resolve({ ok: postOk }) });
            }
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(antwort) });
        };
        const kachel = w.document.getElementById('pt-newsfeed');
        await w.JarvisNewsfeed.portalStart();
        const zu = kachel.querySelector('.nf-zu');
        pruefe(!!zu && zu.querySelector('svg'), '×-Knopf mit Symbol aus icons.js');
        pruefe(zu && /Ausblenden/.test(zu.title), 'Tooltip nennt die Wirkung', zu && zu.title);
        const tick = () => new Promise((r) => setImmediate(r));
        // Fehlschlag: Kachel bleibt, Knopf sagt es.
        zu.click(); await tick(); await tick();
        pruefe(gesendet && gesendet.methode === 'POST' && gesendet.rumpf && gesendet.rumpf.stand === STAND,
               'POST mit dem GEZEIGTEN Stand', JSON.stringify(gesendet));
        pruefe(gesendet && gesendet.auth === 'Bearer testtoken', 'mit Sitzungstoken');
        pruefe(!kachel.hidden, 'Fehlschlag: Kachel bleibt sichtbar');
        pruefe(zu.classList.contains('nf-zu-fehler') && /fehlgeschlagen/.test(zu.title) && !zu.disabled,
               'Fehlschlag: am Knopf sichtbar, erneut klickbar', zu.title);
        // Erfolg: Kachel weg.
        postOk = true;
        zu.click(); await tick(); await tick();
        pruefe(kachel.hidden, 'nach Bestaetigung ausgeblendet');
        // Nachladen: Server sagt ausgeblendet -> bleibt weg.
        antwort = Object.assign({}, antwort, { ausgeblendet: true });
        await intervall();
        pruefe(kachel.hidden, 'Server meldet ausgeblendet: bleibt verborgen');
        // Neue Meldung: Server sagt nicht mehr ausgeblendet -> kommt wieder.
        antwort = { ok: true, eintraege: [{ titel: 'Neu', text: 'Ganz neu.', erstellt: '2026-10-21T08:00:00' }].concat(DREI.slice(0, 2)),
                    verweil_s: 3, scroll_s: 0.8, stand: '2026-10-21T08:00:00', ausgeblendet: false };
        await intervall();
        pruefe(!kachel.hidden && kachel.querySelector('.nf-titel').textContent === 'Neu', 'neue Meldung: Kachel wieder da');
    }
    {
        const { w } = fenster();
        w.JarvisNewsfeed.ticker(w.document.getElementById('w'),
            [{ titel: 'A', text: 'a.', erstellt: '2026-10-01T09:00:00', geaendert: '2026-10-20T09:00:00' },
             { titel: 'B', text: 'b.', erstellt: '2026-10-02T09:00:00', geaendert: '2026-10-02T17:00:00' }], {});
        const d = w.document.querySelectorAll('#w .nf-datum');
        pruefe(d[0] && /01\.10\.2026.*aktualisiert 20\.10\.2026/.test(d[0].textContent), 'bearbeitet an anderem Tag: Zusatz „aktualisiert"', d[0] && d[0].textContent);
        pruefe(d[1] && !/aktualisiert/.test(d[1].textContent), 'am selben Tag bearbeitet: kein Zusatz', d[1] && d[1].textContent);
    }

    abschnitt('11. Vor/Zurueck/Pause');
    {
        const { w, vor } = fenster();
        w.eval(lies('frontend/js/icons.js'));
        const wurzel = w.document.getElementById('w');
        const t = w.JarvisNewsfeed.ticker(wurzel, DREI, { verweil_s: 3, scroll_s: 0.8 });
        const k = (cls) => wurzel.querySelector('.nf-kopf .' + cls);
        // Positivkontrolle: die drei Knoepfe sind da.
        if (!k('nf-zurueck') || !k('nf-pause-knopf') || !k('nf-vor')) {
            console.log('ABBRUCH: Knoepfe fehlen'); process.exit(2);
        }
        pruefe(['nf-zurueck', 'nf-pause-knopf', 'nf-vor'].every((c) => k(c).type === 'button' && k(c).querySelector('svg')),
               'drei Knoepfe mit Symbol aus icons.js');
        pruefe(k('nf-zurueck').title === 'Vorherige Meldung' && k('nf-vor').title === 'Nächste Meldung'
               && k('nf-pause-knopf').title === 'Anhalten' && k('nf-pause-knopf').getAttribute('aria-pressed') === 'false',
               'Tooltips nennen die Wirkung', k('nf-pause-knopf').title);
        // Zurueck von der ersten: ueber die Kopie zur letzten, nicht rueckwaerts durchs Band.
        vor(1000);
        k('nf-zurueck').click();
        pruefe(band(w).style.transform === 'translateY(-50%)' && /transform 0\.8s/.test(band(w).style.transition),
               'zurueck von 1: rollt zur letzten (Index 2)', band(w).style.transform);
        pruefe(zaehler(w) === '3/3' && t.index() === 2, 'Zaehler 3/3', zaehler(w));
        vor(800 + 2999);
        pruefe(band(w).style.transform === 'translateY(-50%)', 'danach volle Verweilzeit (nicht der Rest der alten)');
        vor(1);
        pruefe(band(w).style.transform === 'translateY(-75%)', 'Ablauf geht von dort weiter (auf die Kopie)', band(w).style.transform);
        // Vor mitten im Rollen auf die Kopie: Schritt abschliessen, dann weiter zu 2.
        vor(400);
        k('nf-vor').click();
        pruefe(band(w).style.transform === 'translateY(-25%)' && zaehler(w) === '2/3',
               'vor mitten im Rollen: von der ersten weiter zur zweiten', band(w).style.transform + ' ' + zaehler(w));
        vor(800);
        // Pause: haelt auch, wenn die Maus die Kachel verlaesst.
        vor(1000);
        k('nf-pause-knopf').click();
        pruefe(wurzel.classList.contains('nf-pause') && k('nf-pause-knopf').getAttribute('aria-pressed') === 'true'
               && k('nf-pause-knopf').title === 'Weiterlaufen lassen', 'Pause gedrueckt: angehalten, Knopf zeigt Weiter');
        wurzel.dispatchEvent(new w.Event('mouseenter'));
        wurzel.dispatchEvent(new w.Event('mouseleave'));
        vor(20000);
        pruefe(band(w).style.transform === 'translateY(-25%)' && wurzel.classList.contains('nf-pause'),
               'Maus weg: bleibt trotzdem stehen', band(w).style.transform);
        // Blaettern waehrend Pause: wechselt, bleibt aber stehen.
        k('nf-vor').click();
        vor(800 + 20000);
        pruefe(band(w).style.transform === 'translateY(-50%)', 'vor waehrend Pause: Meldung 3, kein Weiterlaufen', band(w).style.transform);
        // Weiter: volle Verweilzeit (nach dem Blaettern), dann Ablauf.
        k('nf-pause-knopf').click();
        pruefe(!wurzel.classList.contains('nf-pause') && k('nf-pause-knopf').getAttribute('aria-pressed') === 'false',
               'Weiter gedrueckt: laeuft wieder');
        vor(2999);
        pruefe(band(w).style.transform === 'translateY(-50%)', 'Weiter: Verweilzeit laeuft');
        vor(1);
        pruefe(band(w).style.transform === 'translateY(-75%)', 'dann naechster Schritt', band(w).style.transform);
        t.stoppen();
    }
    {
        // Pause mit Restzeit: 1 s verweilt, Pause, Weiter -> noch 2 s.
        const { w, vor } = fenster();
        const wurzel = w.document.getElementById('w');
        const t = w.JarvisNewsfeed.ticker(wurzel, DREI, { verweil_s: 3, scroll_s: 0.8 });
        vor(1000);
        t.pause(); vor(10000); t.pause();
        vor(1999);
        pruefe(band(w).style.transform === '', 'Pause/Weiter: Rest 2 s noch nicht um');
        vor(1);
        pruefe(band(w).style.transform === 'translateY(-25%)', 'Pause/Weiter: Wechsel nach Restzeit', band(w).style.transform);
        t.stoppen();
    }
    {
        const { w } = fenster();
        w.JarvisNewsfeed.ticker(w.document.getElementById('w'), DREI.slice(0, 1), {});
        pruefe(!w.document.querySelector('#w .nf-knopf'), 'eine Meldung: keine Ablauf-Knoepfe');
    }
    {
        const { w, vor } = fenster({ ruhig: true });
        const wurzel = w.document.getElementById('w');
        w.JarvisNewsfeed.ticker(wurzel, DREI, { verweil_s: 3, scroll_s: 0.8 });
        wurzel.querySelector('.nf-zurueck').click();
        vor(400);
        pruefe(band(w).style.opacity === '1' && band(w).style.transform === 'translateY(-66.66666666666667%)' && zaehler(w) === '3/3',
               'reduzierte Bewegung: zurueck blendet die letzte ein', band(w).style.transform);
    }

    abschnitt('10. Admin-Reiter');
    {
        const dom = new JSDOM(lies('frontend/settings.html'), { url: 'https://localhost/settings', runScripts: 'outside-only' });
        const w = dom.window;
        w.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
        w.setInterval = () => 0;
        w.confirm = () => true;
        sitzungLaden(w, { token: 'testtoken' });
        w.eval(lies('frontend/js/icons.js'));
        w.eval(lies('frontend/js/newsfeed.js'));
        w.eval(lies('frontend/js/newsfeed_admin.js'));
        if (!w.NewsfeedAdmin || !w.document.getElementById('nfadm-liste')) {
            console.log('ABBRUCH: NewsfeedAdmin oder #nfadm-liste fehlt'); process.exit(2);
        }
        const E = (id, aktiv, stand) => ({ id, titel: 'T-' + id, text: 'x.', erstellt: stand, aktiv });
        let daten = { ok: true, skill_aktiv: true, einstellungen: { verweil_s: 3, scroll_s: 0.8, anzahl: 3 },
            grenzen: { anzahl_min: 1, anzahl_max: 100, anzahl_alle: 'alle', titel_max: 80, text_max: 400 },
            eintraege: [E('a', true, '2026-10-20T10:00:00'), E('b', false, '2026-10-19T10:00:00'),
                        E('c', true, '2026-10-18T10:00:00'), E('d', true, '2026-10-17T10:00:00'),
                        E('e', true, '2026-10-16T10:00:00')] };
        const aufrufe = [];
        w.fetch = (url, o) => {
            aufrufe.push([(o && o.method) || 'GET', url.split('?')[0]]);
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(url.indexOf('/deaktivieren') > -1 ? { ok: true } : daten) });
        };
        await w.NewsfeedAdmin.onShow();
        const karte = (id) => w.document.querySelector('#nfadm-liste .am-vorg-card[data-nid="' + id + '"]');
        // Positivkontrolle: die Liste ist gezeichnet.
        if (!karte('a')) { console.log('ABBRUCH: Liste nicht gezeichnet'); process.exit(2); }
        pruefe(karte('b').classList.contains('nf-adm-inaktiv') && /deaktiviert/.test(karte('b').textContent),
               'deaktivierte Meldung als Text gekennzeichnet');
        pruefe(!karte('b').querySelector('[data-akt="deakt"]'), 'deaktivierte ohne Deaktivieren-Knopf');
        pruefe(!!karte('b').querySelector('[data-akt="edit"]'), 'deaktivierte bleibt bearbeitbar');
        pruefe(!!karte('a').querySelector('[data-akt="deakt"]'), 'aktive mit Deaktivieren-Knopf');
        const sichtbar = ['a', 'b', 'c', 'd', 'e'].filter((id) => /im Portal sichtbar/.test(karte(id).textContent));
        pruefe(JSON.stringify(sichtbar) === '["a","c","d"]', '„im Portal sichtbar" = die ersten drei AKTIVEN', JSON.stringify(sichtbar));
        const titel = [...w.document.querySelectorAll('#nfadm-vorschau .nf-block:not([aria-hidden]) .nf-titel')].map((x) => x.textContent);
        pruefe(JSON.stringify(titel) === '["T-a","T-c","T-d"]', 'Vorschau ohne die deaktivierte', JSON.stringify(titel));
        aufrufe.length = 0;
        karte('c').querySelector('[data-akt="deakt"]').click();
        await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r));
        pruefe(aufrufe.some(([m, u]) => m === 'POST' && u === '/api/newsfeed/admin/eintraege/c/deaktivieren'),
               'Deaktivieren ruft POST …/c/deaktivieren', JSON.stringify(aufrufe));
        pruefe(aufrufe.some(([m, u]) => m === 'GET' && u === '/api/newsfeed/admin'), 'danach aus der Server-Antwort neu geladen');
        w.close();
    }

    {
        console.log('\n12. Anzahl im Admin-Reiter');
        const dom = new JSDOM(lies('frontend/settings.html'), { url: 'https://localhost/settings', runScripts: 'outside-only' });
        const w = dom.window;
        w.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
        w.setInterval = () => 0;
        sitzungLaden(w, { token: 'testtoken' });
        w.eval(lies('frontend/js/icons.js'));
        w.eval(lies('frontend/js/newsfeed.js'));
        w.eval(lies('frontend/js/newsfeed_admin.js'));
        const $ = (id) => w.document.getElementById(id);
        if (!w.NewsfeedAdmin || !$('nfadm-anzahl') || !$('nfadm-anzahl-alle')) {
            console.log('ABBRUCH: NewsfeedAdmin oder Anzahl-Felder fehlen im Markup'); process.exit(2);
        }
        const E = (id, aktiv, stand) => ({ id, titel: 'T-' + id, text: 'x.', erstellt: stand, aktiv });
        const daten = { ok: true, skill_aktiv: true, einstellungen: { verweil_s: 3, scroll_s: 0.8, anzahl: 3 },
            grenzen: { anzahl_min: 1, anzahl_max: 100, anzahl_alle: 'alle', titel_max: 80, text_max: 400 },
            eintraege: [E('a', true, '2026-10-20T10:00:00'), E('b', false, '2026-10-19T10:00:00'),
                        E('c', true, '2026-10-18T10:00:00'), E('d', true, '2026-10-17T10:00:00'),
                        E('e', true, '2026-10-16T10:00:00')] };
        let gesendet = null;
        w.fetch = (url, o) => {
            const pfad = url.split('?')[0];
            if (pfad === '/api/newsfeed/admin/einstellungen') {
                gesendet = JSON.parse(o.body);
                const neu = Object.assign({}, gesendet);
                return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, einstellungen: neu }) });
            }
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(daten) });
        };
        await w.NewsfeedAdmin.onShow();
        const karte = (id) => w.document.querySelector('#nfadm-liste .am-vorg-card[data-nid="' + id + '"]');
        if (!karte('a')) { console.log('ABBRUCH: Liste nicht gezeichnet'); process.exit(2); }
        const sichtbar = () => ['a', 'b', 'c', 'd', 'e'].filter((id) => /im Portal sichtbar/.test(karte(id).textContent));
        const vorschau = () => [...w.document.querySelectorAll('#nfadm-vorschau .nf-block:not([aria-hidden]) .nf-titel')].map((x) => x.textContent);
        pruefe($('nfadm-anzahl').value === '3' && !$('nfadm-anzahl-alle').checked, 'Feld zeigt gespeicherte Anzahl 3', $('nfadm-anzahl').value);
        pruefe($('nfadm-anzahl').min === '1', 'Untergrenze des Feldes = 1', $('nfadm-anzahl').min);
        // Feld auf 1: Vorschau folgt sofort, die Liste (gespeichert) nicht.
        $('nfadm-anzahl').value = '1';
        $('nfadm-anzahl').dispatchEvent(new w.Event('input'));
        pruefe(JSON.stringify(vorschau()) === '["T-a"]', 'Feld 1 -> Vorschau zeigt eine Meldung', JSON.stringify(vorschau()));
        pruefe(JSON.stringify(sichtbar()) === '["a","c","d"]', 'Liste folgt dem GESPEICHERTEN Wert, nicht dem Feld', JSON.stringify(sichtbar()));
        // „alle": Feld gesperrt, Vorschau mit allen aktiven.
        $('nfadm-anzahl-alle').checked = true;
        $('nfadm-anzahl-alle').dispatchEvent(new w.Event('change'));
        pruefe($('nfadm-anzahl').disabled, '„alle" sperrt das Zahlenfeld');
        pruefe(JSON.stringify(vorschau()) === '["T-a","T-c","T-d","T-e"]', '„alle" -> Vorschau mit allen aktiven', JSON.stringify(vorschau()));
        $('nfadm-anz-save').click();
        await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r));
        pruefe(gesendet && gesendet.anzahl === 'alle', 'Speichern schickt anzahl: "alle"', JSON.stringify(gesendet));
        pruefe(JSON.stringify(sichtbar()) === '["a","c","d","e"]', 'nach dem Speichern: alle aktiven als sichtbar markiert', JSON.stringify(sichtbar()));
        // Zurueck auf eine Zahl.
        $('nfadm-anzahl-alle').checked = false;
        $('nfadm-anzahl-alle').dispatchEvent(new w.Event('change'));
        pruefe(!$('nfadm-anzahl').disabled && $('nfadm-anzahl').value !== '', 'Abwaehlen gibt das Feld mit einer Zahl frei', $('nfadm-anzahl').value);
        $('nfadm-anzahl').value = '2';
        $('nfadm-anz-save').click();
        await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r));
        pruefe(gesendet && gesendet.anzahl === 2, 'Speichern schickt die Zahl als Zahl', JSON.stringify(gesendet));
        pruefe(JSON.stringify(sichtbar()) === '["a","c"]', 'nach dem Speichern: zwei als sichtbar markiert', JSON.stringify(sichtbar()));
        // Gespeichertes „alle" beim Laden.
        daten.einstellungen.anzahl = 'alle';
        await w.NewsfeedAdmin.laden();
        pruefe($('nfadm-anzahl-alle').checked && $('nfadm-anzahl').disabled, 'gespeichertes „alle" hakt das Kaestchen und sperrt das Feld');
        w.close();
    }

    console.log(`\n${ok} OK, ${fail} FAIL`);
    process.exit(fail ? 1 : 0);
})();
