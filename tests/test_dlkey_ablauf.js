/* Waechter: ueberlebt ein Download-Link den Ablauf seines Abruf-Schluessels?
 *
 * GEMELDET 2026-09-04 (ECHT, /chat): Chrome meldete beim Klick auf einen
 * Excel-Chip „Versuch, dich auf der Website anzumelden. Lade die Datei dann
 * noch einmal herunter." – das ist Chromes Text fuer HTTP 401. Ursache: die
 * Adresse wird beim RENDERN gebaut und friert im DOM ein, der Schluessel darin
 * gilt 15 Minuten, geklickt wird Stunden spaeter. Auf DEV end-to-end gemessen:
 * derselbe Link 200 → nach Ablauf 401 → mit frischem Schluessel wieder 200.
 *
 * GEMESSEN WIRD DIE EIGENSCHAFT, nicht das Vorkommen einer Zeile: der ECHTE
 * dlkey.js laeuft in jsdom, ein veralteter Chip wird WIRKLICH geklickt, und
 * verlangt ist, dass die Adresse beim tatsaechlich durchgelassenen Klick einen
 * FRISCHEN Schluessel traegt. Eine Suche nach „addEventListener('click'" waere
 * gruen, sobald jemand den Zweig spaeter ueberspringt.
 */
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch (e) {
    for (const p of ['node_modules', 'data/node_modules', '/tmp/node_modules', '/usr/share/nodejs']) {
        try { ({ JSDOM } = require(path.resolve(p, 'jsdom'))); break; } catch (_) { }
    }
}
if (!JSDOM) { console.error('ABBRUCH: jsdom nicht gefunden – der Waechter konnte NICHT laufen.'); process.exit(2); }

const WURZEL = path.resolve(__dirname, '..');
const QUELLE = fs.readFileSync(path.join(WURZEL, 'frontend/js/dlkey.js'), 'utf8');

let ok = 0, fail = 0;
function check(text, bed) {
    if (typeof text !== 'string' || typeof bed !== 'boolean') {
        console.error('ABBRUCH: check(Beschreibung, Bedingung) – Argumente vertauscht: ' + text);
        process.exit(2);
    }
    if (bed) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text); }
}

function schluessel(user, expSek) {
    const b64 = Buffer.from(user, 'utf8').toString('base64')
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return 'JDL1.' + b64 + '.' + expSek + '.' + 'a'.repeat(64);
}
const JETZT = () => Math.floor(Date.now() / 1000);

/* Baut eine frische Umgebung: echter dlkey.js, gestellter fetch, leeres DOM. */
function umgebung(html) {
    const dom = new JSDOM('<!doctype html><html><body>' + (html || '') + '</body></html>',
        // runScripts:'outside-only' – ohne das ist window.eval Nodes eval und
        // `window` im Skript nicht definiert; der Waechter wuerde am eigenen
        // Aufbau scheitern, nicht am Code.
        { url: 'https://beispiel.test/chat', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'benutzer:123:abc');
    w.localStorage.setItem('jarvis_user', 'andreas.bender');
    const zustand = { abrufe: 0, neuerKey: schluessel('andreas.bender', JETZT() + 900) };
    w.fetch = function () {
        zustand.abrufe++;
        return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ ok: true, key: zustand.neuerKey, exp: JETZT() + 900 })
        });
    };
    w.eval(QUELLE);
    return { dom, w, z: zustand };
}
const warte = () => new Promise(r => setTimeout(r, 30));

(async function () {
    // ── Positivkontrolle: laeuft das Modul ueberhaupt? ────────────────────
    {
        const { w, dom } = umgebung('');
        if (!w.JarvisDL || typeof w.JarvisDL.url !== 'function') {
            console.error('ABBRUCH: JarvisDL wurde nicht bereitgestellt – jede weitere Aussage waere wertlos.');
            process.exit(2);
        }
        check('Positivkontrolle: JarvisDL steht bereit', true);
        /* API-Vertrag ZUERST und mit eigener Bilanz: fehlt eine der Funktionen
         * (Altstand vor dem 2026-09-04), wuerden die Pruefungen darunter WERFEN
         * und der Lauf mit "konnte nicht laufen" enden – von "bestanden" nicht
         * zu unterscheiden. Also FAIL mit Bilanzzeile, nicht Abbruch. */
        var noetig = ['url', 'schluessel', 'bereit', 'veraltet', 'ersetzen', 'aktualisiere'];
        var fehlt = noetig.filter(function (k) { return typeof w.JarvisDL[k] !== 'function'; });
        check('API-Vertrag vollstaendig (' + noetig.join(', ') + ')', fehlt.length === 0);
        dom.window.close();
        if (fehlt.length) {
            console.log('  FAIL Altstand ohne Ablauf-Behandlung – fehlend: ' + fehlt.join(', '));
            console.log('\n' + ok + ' OK, ' + (fail + 1) + ' FAIL');
            process.exit(1);
        }
    }

    // ── 1. veraltet(): erkennt der Client einen toten Schluessel? ─────────
    {
        const { w, dom } = umgebung('');
        const D = w.JarvisDL;
        const alt = '/api/documents/abc__x.xlsx?token=' + schluessel('a', JETZT() - 60);
        const neu = '/api/documents/abc__x.xlsx?token=' + schluessel('a', JETZT() + 900);
        const knapp = '/api/documents/abc__x.xlsx?token=' + schluessel('a', JETZT() + 30);
        check('abgelaufener Schluessel gilt als veraltet', D.veraltet(alt) === true);
        check('frischer Schluessel gilt NICHT als veraltet', D.veraltet(neu) === false);
        check('Ablauf in 30 s gilt als veraltet (Vorlauf 60 s)', D.veraltet(knapp) === true);
        check('Adresse ohne Token ist nicht "veraltet"', D.veraltet('/api/documents/abc__x.xlsx') === false);
        check('Sitzungstoken in ?token= wird nicht angefasst',
            D.veraltet('/api/documents/abc__x.xlsx?token=nutzer%3A1%3Aab') === false);
        dom.window.close();
    }

    // ── 2. ersetzen(): nur der eigene Schluessel, nichts sonst ────────────
    {
        const { w, dom } = umgebung('');
        const D = w.JarvisDL;
        const alt = schluessel('a', JETZT() - 60), neu = schluessel('a', JETZT() + 900);
        check('Schluessel wird ersetzt',
            D.ersetzen('/api/x?token=' + alt, neu) === '/api/x?token=' + neu);
        check('weitere Parameter bleiben stehen',
            D.ersetzen('/api/x?a=1&token=' + alt + '&b=2', neu) === '/api/x?a=1&token=' + neu + '&b=2');
        check('Sitzungstoken bleibt unveraendert (Alt-Weg der Android-App)',
            D.ersetzen('/api/x?token=nutzer:1:ab', neu) === '/api/x?token=nutzer:1:ab');
        dom.window.close();
    }

    /* ── 3a. DER GEMELDETE FALL – Netz 2 (Nachziehen) ALLEIN ──────────────
     * Der Chip steht beim Laden im DOM. Verlangt ist, dass der Abruf des
     * Schluessels die Adresse NACHZIEHT – ohne jeden Klick. Bewusst getrennt
     * von 3b: mit beiden Netzen in EINER Pruefung deckt eines den Ausfall des
     * anderen, und die Gegenprobe biss nicht (genau so beim ersten Lauf
     * passiert). */
    {
        const alt = schluessel('andreas.bender', JETZT() - 60);
        const ADR = '/api/documents/a316546546f04426883907714bb43ed7__kalender_2027.xlsx';
        const { w, z, dom } = umgebung(
            '<a id="chip" download class="chat-doc-dl" href="' + ADR + '?token=' + alt + '">Kalender</a>');
        await warte();
        const h = w.document.getElementById('chip').getAttribute('href') || '';
        check('3a: der Chip im DOM traegt nach dem Abruf den frischen Schluessel',
            h.indexOf(z.neuerKey) >= 0);
        check('3a: der abgelaufene Schluessel ist verschwunden', h.indexOf(alt) < 0);
        check('3a: es ist dieselbe Datei', h.indexOf(ADR) === 0);
        dom.window.close();
    }

    /* ── 3b. DER GEMELDETE FALL – Netz 3 (Klick) ALLEIN ───────────────────
     * Der Chip entsteht ERST NACH dem Abruf (so wie eine Chat-Nachricht, die
     * spaeter gerendert wird) und traegt einen veralteten Schluessel. Netz 2
     * kann ihn nicht mehr erwischen – nur der Klick. */
    {
        const alt = schluessel('andreas.bender', JETZT() - 60);
        const ADR = '/api/documents/a316546546f04426883907714bb43ed7__kalender_2027.xlsx';
        const { w, z, dom } = umgebung('');
        await warte();                       // Abruf beim Laden ist durch
        const abrufeVorher = z.abrufe;
        w.document.body.innerHTML =
            '<a id="chip" download class="chat-doc-dl" href="' + ADR + '?token=' + alt + '">Kalender</a>';
        const chip = w.document.getElementById('chip');

        const durchgelassen = [];
        w.document.addEventListener('click', function (ev) {
            durchgelassen.push(chip.getAttribute('href'));
            ev.preventDefault();             // jsdom kann nicht navigieren
        });

        chip.click();
        await warte();

        check('3b: der veraltete Klick wird angehalten und genau EINMAL wiederholt',
            durchgelassen.length === 1);
        const h = durchgelassen[0] || '';
        check('3b: der durchgelassene Klick traegt den FRISCHEN Schluessel',
            h.indexOf(z.neuerKey) >= 0);
        check('3b: der abgelaufene Schluessel steht nicht mehr in der Adresse',
            h.indexOf(alt) < 0);
        check('3b: es ist dieselbe Datei', h.indexOf(ADR) === 0);
        check('3b: das DOM wurde mitgezogen, nicht nur der Klick',
            (chip.getAttribute('href') || '').indexOf(z.neuerKey) >= 0);
        check('3b: der gueltige Schluessel aus dem Zwischenspeicher genuegt (kein zweiter Serveraufruf)',
            z.abrufe === abrufeVorher);
        dom.window.close();
    }

    // ── 4. ein FRISCHER Chip wird nicht angefasst (keine Bremse im Alltag) ─
    {
        const gut = schluessel('andreas.bender', JETZT() + 900);
        const { w, dom } = umgebung('<a id="chip" download href="/api/documents/x__y.xlsx?token=' + gut + '">Y</a>');
        await warte();
        const chip = w.document.getElementById('chip');
        let angehalten = null;
        w.document.addEventListener('click', function (ev) { angehalten = ev.defaultPrevented; ev.preventDefault(); });
        chip.click();
        await warte();
        check('frischer Chip: der Klick wird NICHT angehalten', angehalten === false);
        check('frischer Chip: die Adresse bleibt unveraendert',
            (chip.getAttribute('href') || '').indexOf(gut) >= 0);
        dom.window.close();
    }

    // ── 5. Nachziehen im DOM ──────────────────────────────────────────────
    {
        const alt = schluessel('andreas.bender', JETZT() - 60);
        const gut = schluessel('andreas.bender', JETZT() + 900);
        const { w, z, dom } = umgebung(
            '<a id="a1" href="/api/documents/1__a.xlsx?token=' + alt + '">alt</a>' +
            '<a id="a2" href="/api/documents/2__b.xlsx?token=' + gut + '">frisch</a>' +
            '<a id="a3" href="/api/documents/3__c.xlsx?token=nutzer:1:ab">sitzung</a>' +
            '<img id="i1" src="/api/documents/4__d.png?token=' + alt + '">');
        const n = w.JarvisDL.aktualisiere(z.neuerKey);
        const g = (id, at) => w.document.getElementById(id).getAttribute(at);
        check('veralteter Link wird nachgezogen', g('a1', 'href').indexOf(z.neuerKey) >= 0);
        check('frischer Link bleibt unberuehrt', g('a2', 'href').indexOf(gut) >= 0);
        check('Sitzungstoken-Link bleibt unberuehrt', g('a3', 'href').indexOf('nutzer:1:ab') >= 0);
        check('noch nicht geladenes Bild wird nachgezogen', g('i1', 'src').indexOf(z.neuerKey) >= 0);
        check('die Zahl der geaenderten Adressen wird gemeldet', n === 2);
        dom.window.close();
    }

    // ── 6. Takt: beim Zurueckholen des Tabs wird erneuert ─────────────────
    {
        const { w, z, dom } = umgebung('');
        await warte();
        // FALLSTRICK jsdom: dort ist `document.hidden` true und
        // visibilityState 'prerender' – der Zweig `if (!document.hidden)` waere
        // also nie erreichbar und der Waechter meldete einen Fehler, den es im
        // Browser nicht gibt. Ein sichtbarer Tab wird deshalb gestellt.
        Object.defineProperty(w.document, 'hidden', { get: function () { return false; } });
        const vorher = z.abrufe;
        // Zwischenspeicher auf "laeuft gleich ab" setzen
        w.sessionStorage.setItem('jarvis_dlkey', JSON.stringify(
            { key: schluessel('andreas.bender', JETZT() + 10), exp: JETZT() + 10, user: 'andreas.bender' }));
        w.document.dispatchEvent(new w.Event('visibilitychange'));
        await warte();
        check('Sichtbarkeitswechsel erneuert einen fast abgelaufenen Schluessel', z.abrufe === vorher + 1);
        dom.window.close();
    }

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(e => { console.error('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
