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
 *
 * SEIT PENTEST F-20 (2026-11-17) gilt jeder Schluessel nur fuer GENAU EINE
 * Adresse. Die drei Netze (Nachziehen, Klick, Takt) gelten deshalb je ADRESSE,
 * und die Attrappe des Servers beantwortet den Sammelabruf in der ECHTEN
 * Antwortform von POST /api/download-key ({ok, keys: {<adresse>: {key, exp}}})
 * – mit einem anderen Schluessel fuer jede Adresse. Ein Client, der einen
 * Schluessel fuer alle Adressen benutzte, fiele hier durch.
 */
'use strict';
const fs = require('fs');
const path = require('path');

let JSDOM;
({ JSDOM } = require('./lib/jsdom_laden')());
if (!JSDOM) { console.error('ABBRUCH: jsdom nicht gefunden – der Waechter konnte NICHT laufen.'); process.exit(2); }

const WURZEL = path.resolve(__dirname, '..');
const QUELLE = fs.readFileSync(path.join(WURZEL, 'frontend/js/dlkey.js'), 'utf8');
/* ⚠ sitzung.js GEHOERT IN DEN AUFBAU – dlkey.js liest den Sitzungstoken seit
   dem 2026-10-01 ueber die gemeinsame Quelle (es gab drei Schluesselnamen, und
   dlkey.js kannte nur einen; im Chat trug damit kein Download-Link ein Token).
   Ohne diese Zeile ist `tok()` leer und der Waechter misst einen Aufbau, den
   keine echte Seite hat – jede Seite laedt sitzung.js davor (als REGEL geprueft
   in tests/test_sitzung_eine_quelle.js, Abschnitt 3). */
const SITZUNG = fs.readFileSync(path.join(WURZEL, 'frontend/js/sitzung.js'), 'utf8');

let ok = 0, fail = 0;
function check(text, bed) {
    if (typeof text !== 'string' || typeof bed !== 'boolean') {
        console.error('ABBRUCH: check(Beschreibung, Bedingung) – Argumente vertauscht: ' + text);
        process.exit(2);
    }
    if (bed) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text); }
}

const JETZT = () => Math.floor(Date.now() / 1000);
/* Schluessel in der Form, die der Server ausstellt (7 Teile). Die Zielmarke ist
   hier eine Ableitung der ADRESSE – so ist am Wert ablesbar, fuer welche Adresse
   er ausgestellt wurde (der echte Server bildet einen Hash, den der Client nie
   nachrechnet). */
function zmarke(adr) {
    const u = new URL(adr, 'https://beispiel.test');
    u.searchParams.delete('token'); u.searchParams.delete('t'); u.searchParams.sort();
    return Buffer.from(u.pathname + u.search, 'utf8').toString('base64')
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function schluessel(user, expSek, adr) {
    const b64 = Buffer.from(user, 'utf8').toString('base64')
        .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return 'JDL1.' + b64 + '.' + expSek + '.v.0.' + zmarke(adr || '/api/x') + '.' + 'a'.repeat(64);
}
const traegtZiel = (adresse, adr) => adresse.indexOf(encodeURIComponent('.' + zmarke(adr) + '.')) >= 0
    || adresse.indexOf('.' + zmarke(adr) + '.') >= 0;

/* Baut eine frische Umgebung: echter dlkey.js, gestellter Server, DOM. */
function umgebung(html, lebensdauer) {
    const dom = new JSDOM('<!doctype html><html><body>' + (html || '') + '</body></html>',
        { url: 'https://beispiel.test/chat', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'benutzer:123:abc');
    w.localStorage.setItem('jarvis_user', 'm.mustermann');
    const zustand = { abrufe: [], dauer: lebensdauer || 900 };
    w.fetch = function (url, opt) {
        opt = opt || {};
        // Nur der Abruf-Schluessel-Endpunkt zaehlt. sitzung.js meldet beim Laden
        // seine Sitzung an (POST /api/sitzung/cookie) – das ist kein Abruf.
        if (String(url).indexOf('/api/download-key') !== 0) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
        }
        let ziele = null;
        try { ziele = JSON.parse(opt.body || 'null').ziele; } catch (e) { ziele = null; }
        zustand.abrufe.push({ url: String(url), methode: opt.method || 'GET', ziele: ziele });
        if (String(url) !== '/api/download-key' || opt.method !== 'POST' || !Array.isArray(ziele)) {
            return Promise.resolve({ ok: false, status: 400, json: () => Promise.resolve({ ok: false }) });
        }
        const keys = {};
        ziele.forEach(function (adr) {
            keys[adr] = { key: schluessel('m.mustermann', JETZT() + zustand.dauer, adr),
                          exp: JETZT() + zustand.dauer };
        });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, keys: keys }) });
    };
    w.eval(SITZUNG);
    w.eval(QUELLE);
    return { dom, w, z: zustand };
}
const warte = () => new Promise(r => setTimeout(r, 30));

(async function () {
    // ── Positivkontrolle + API-Vertrag ────────────────────────────────────
    {
        const { w, dom } = umgebung('');
        if (!w.JarvisDL || typeof w.JarvisDL.url !== 'function') {
            console.error('ABBRUCH: JarvisDL wurde nicht bereitgestellt – jede weitere Aussage waere wertlos.');
            process.exit(2);
        }
        check('Positivkontrolle: JarvisDL steht bereit', true);
        /* Fehlt eine Funktion, wuerden die Pruefungen darunter WERFEN – also
         * FAIL mit Bilanzzeile, nicht Abbruch. */
        var noetig = ['url', 'fuer', 'veraltet', 'ersetzen', 'aktualisiere'];
        var fehlt = noetig.filter(function (k) { return typeof w.JarvisDL[k] !== 'function'; });
        check('API-Vertrag vollstaendig (' + noetig.join(', ') + ')', fehlt.length === 0);
        check('F-20: es gibt KEINEN Schluessel ohne Adresse mehr (schluessel/bereit entfernt)',
            typeof w.JarvisDL.schluessel === 'undefined' && typeof w.JarvisDL.bereit === 'undefined');
        dom.window.close();
        if (fehlt.length) {
            console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
            process.exit(1);
        }
    }

    // ── 1. veraltet(): erkennt der Client einen toten Schluessel? ─────────
    {
        const { w, dom } = umgebung('');
        const D = w.JarvisDL;
        const A = '/api/documents/abc__x.xlsx';
        check('abgelaufener Schluessel gilt als veraltet', D.veraltet(A + '?token=' + schluessel('a', JETZT() - 60, A)) === true);
        check('frischer Schluessel gilt NICHT als veraltet', D.veraltet(A + '?token=' + schluessel('a', JETZT() + 900, A)) === false);
        check('Ablauf in 30 s gilt als veraltet (Vorlauf 60 s)', D.veraltet(A + '?token=' + schluessel('a', JETZT() + 30, A)) === true);
        check('der Platzhalter gilt als veraltet', D.veraltet(A + '?token=JDL1.warten.0.0') === true);
        check('Adresse ohne Token ist nicht "veraltet"', D.veraltet(A) === false);
        check('Sitzungstoken in ?token= wird nicht angefasst', D.veraltet(A + '?token=nutzer%3A1%3Aab') === false);
        dom.window.close();
    }

    // ── 2. ersetzen(): nur der eigene Schluessel, nichts sonst ────────────
    {
        const { w, dom } = umgebung('');
        const D = w.JarvisDL;
        const alt = schluessel('a', JETZT() - 60), neu = schluessel('a', JETZT() + 900);
        check('Schluessel wird ersetzt', D.ersetzen('/api/x?token=' + alt, neu) === '/api/x?token=' + neu);
        check('weitere Parameter bleiben stehen',
            D.ersetzen('/api/x?a=1&token=' + alt + '&b=2', neu) === '/api/x?a=1&token=' + neu + '&b=2');
        check('Sitzungstoken bleibt unveraendert', D.ersetzen('/api/x?token=nutzer:1:ab', neu) === '/api/x?token=nutzer:1:ab');
        dom.window.close();
    }

    /* ── 3. F-20: url() beim Rendern – Platzhalter, EIN Sammelabruf, je Adresse
     *    ihr eigener Schluessel, Nachziehen ins DOM ─────────────────────── */
    {
        const { w, z, dom } = umgebung('');
        const A = '/api/documents/1111__bericht.pdf', B = '/api/wissen/file?path=a%2Fb.xlsx';
        const ua = w.JarvisDL.url(A), ub = w.JarvisDL.url(B);
        check('3: beim Rendern steht der Platzhalter in der Adresse (nie das Sitzungstoken)',
            ua.indexOf('token=JDL1.warten') > 0 && ub.indexOf('token=JDL1.warten') > 0
            && ua.indexOf('benutzer') < 0);
        w.document.body.innerHTML = '<a id="a" download href="' + ua + '">A</a><img id="b" src="' + ub + '">';
        await warte();
        check('3: GENAU EIN Abruf fuer beide Adressen (Sammelabruf)', z.abrufe.length === 1);
        const ab = z.abrufe[0] || {};
        check('3: als POST mit beiden Adressen als Ziel (ohne token)',
            ab.methode === 'POST' && Array.isArray(ab.ziele) && ab.ziele.length === 2
            && ab.ziele.indexOf(A) >= 0 && ab.ziele.indexOf(B) >= 0);
        const ha = w.document.getElementById('a').getAttribute('href');
        const hb = w.document.getElementById('b').getAttribute('src');
        check('3: der Link traegt danach SEINEN Schluessel', traegtZiel(ha, A));
        check('3: das Bild traegt danach SEINEN Schluessel (nicht den des Links)',
            traegtZiel(hb, B) && !traegtZiel(hb, A));
        check('3: es sind dieselben Dateien', ha.indexOf(A) === 0 && hb.indexOf(B) === 0);
        // Wiederholtes Rendern derselben Adresse: synchron aus dem Zwischenspeicher.
        const vorher = z.abrufe.length;
        const wieder = w.JarvisDL.url(A);
        check('3: dieselbe Adresse erneut: sofort mit Schluessel, ohne Serveraufruf',
            traegtZiel(wieder, A) && wieder.indexOf('warten') < 0);
        // Kamerabild: wechselnder Cache-Buster t ist DIESELBE Adresse.
        const k1 = w.JarvisDL.url('/api/vision/snapshot?t=1');
        await warte();
        const k2 = w.JarvisDL.url('/api/vision/snapshot?t=2');
        check('3: ein anderer Cache-Buster t braucht keinen neuen Schluessel',
            k1.indexOf('warten') > 0 && k2.indexOf('warten') < 0);
        check('3: … und kostete genau einen weiteren Abruf', z.abrufe.length === vorher + 1);
        check('3: nie ein Abruf ohne Ziel (GET /api/download-key ohne ?ziel=)',
            z.abrufe.every(function (a) { return a.methode === 'POST' && Array.isArray(a.ziele) && a.ziele.length > 0; }));
        dom.window.close();
    }

    /* ── 3a. DER GEMELDETE FALL – Netz 2 (Nachziehen) ALLEIN ──────────────
     * Ein Chip mit ABGELAUFENEM Schluessel steht im DOM; takt/Sichtbarkeit
     * holen fuer GENAU diese Adresse einen neuen und ziehen ihn nach. */
    {
        const ADR = '/api/documents/a316546546f04426883907714bb43ed7__kalender_2027.xlsx';
        const alt = schluessel('m.mustermann', JETZT() - 60, ADR);
        const { w, z, dom } = umgebung('<a id="chip" download class="chat-doc-dl" href="' + ADR + '?token=' + alt + '">K</a>');
        w.JarvisDL.aktualisiere();
        await warte();
        const h = w.document.getElementById('chip').getAttribute('href') || '';
        check('3a: der Chip traegt danach einen frischen Schluessel FUER SEINE ADRESSE',
            traegtZiel(h, ADR) && !w.JarvisDL.veraltet(h));
        check('3a: der abgelaufene Schluessel ist verschwunden', h.indexOf(alt) < 0);
        check('3a: angefragt wurde genau diese Adresse',
            z.abrufe.length === 1 && JSON.stringify(z.abrufe[0].ziele) === JSON.stringify([ADR]));
        dom.window.close();
    }

    /* ── 3b. DER GEMELDETE FALL – Netz 3 (Klick) ALLEIN ─────────────────── */
    {
        const ADR = '/api/documents/a316546546f04426883907714bb43ed7__kalender_2027.xlsx';
        const alt = schluessel('m.mustermann', JETZT() - 60, ADR);
        const { w, z, dom } = umgebung('');
        w.document.body.innerHTML =
            '<a id="chip" download class="chat-doc-dl" href="' + ADR + '?token=' + alt + '">K</a>';
        const chip = w.document.getElementById('chip');
        const durchgelassen = [];
        w.document.addEventListener('click', function (ev) {
            durchgelassen.push(chip.getAttribute('href'));
            ev.preventDefault();             // jsdom kann nicht navigieren
        });
        chip.click();
        await warte();
        check('3b: der veraltete Klick wird angehalten und genau EINMAL wiederholt', durchgelassen.length === 1);
        const h = durchgelassen[0] || '';
        check('3b: der durchgelassene Klick traegt den frischen Schluessel FUER SEINE ADRESSE',
            traegtZiel(h, ADR) && !w.JarvisDL.veraltet(h));
        check('3b: der abgelaufene Schluessel steht nicht mehr in der Adresse', h.indexOf(alt) < 0);
        check('3b: das DOM wurde mitgezogen, nicht nur der Klick',
            traegtZiel(chip.getAttribute('href') || '', ADR) && !w.JarvisDL.veraltet(chip.getAttribute('href')));
        check('3b: genau ein Abruf, genau fuer diese Adresse',
            z.abrufe.length === 1 && JSON.stringify(z.abrufe[0].ziele) === JSON.stringify([ADR]));
        dom.window.close();
    }

    // ── 4. ein FRISCHER Chip wird nicht angefasst (keine Bremse im Alltag) ─
    {
        const A = '/api/documents/x__y.xlsx';
        const gut = schluessel('m.mustermann', JETZT() + 900, A);
        const { w, z, dom } = umgebung('<a id="chip" download href="' + A + '?token=' + gut + '">Y</a>');
        await warte();
        const chip = w.document.getElementById('chip');
        let angehalten = null;
        w.document.addEventListener('click', function (ev) { angehalten = ev.defaultPrevented; ev.preventDefault(); });
        chip.click();
        await warte();
        check('frischer Chip: der Klick wird NICHT angehalten', angehalten === false);
        check('frischer Chip: die Adresse bleibt unveraendert', (chip.getAttribute('href') || '').indexOf(gut) >= 0);
        check('frischer Chip: kein Serveraufruf', z.abrufe.length === 0);
        dom.window.close();
    }

    // ── 5. Nachziehen im DOM: nur Veraltetes, je Adresse ──────────────────
    {
        const A1 = '/api/documents/1__a.xlsx', A2 = '/api/documents/2__b.xlsx', A4 = '/api/documents/4__d.png';
        const { w, z, dom } = umgebung(
            '<a id="a1" href="' + A1 + '?token=' + schluessel('m.mustermann', JETZT() - 60, A1) + '">alt</a>' +
            '<a id="a2" href="' + A2 + '?token=' + schluessel('m.mustermann', JETZT() + 900, A2) + '">frisch</a>' +
            '<a id="a3" href="/api/documents/3__c.xlsx?token=nutzer:1:ab">sitzung</a>' +
            '<img id="i1" src="' + A4 + '?token=JDL1.warten.0.0">');
        w.JarvisDL.aktualisiere();
        await warte();
        const g = (id, at) => w.document.getElementById(id).getAttribute(at);
        check('veralteter Link wird mit SEINEM Schluessel nachgezogen', traegtZiel(g('a1', 'href'), A1) && !w.JarvisDL.veraltet(g('a1', 'href')));
        check('frischer Link bleibt unberuehrt', g('a2', 'href').indexOf(schluessel('m.mustermann', 0, A2).split('.')[5]) >= 0
            && !w.JarvisDL.veraltet(g('a2', 'href')));
        check('Sitzungstoken-Link bleibt unberuehrt', g('a3', 'href').indexOf('nutzer:1:ab') >= 0);
        check('Bild mit Platzhalter bekommt SEINEN Schluessel', traegtZiel(g('i1', 'src'), A4) && g('i1', 'src').indexOf('warten') < 0);
        check('angefragt wurden genau die beiden veralteten Adressen, in EINEM Abruf',
            z.abrufe.length === 1 && (z.abrufe[0].ziele || []).length === 2
            && z.abrufe[0].ziele.indexOf(A1) >= 0 && z.abrufe[0].ziele.indexOf(A4) >= 0);
        dom.window.close();
    }

    // ── 6. Takt: beim Zurueckholen des Tabs wird erneuert ─────────────────
    {
        const A = '/api/documents/x__z.xlsx';
        const knapp = schluessel('m.mustermann', JETZT() + 10, A);
        const { w, z, dom } = umgebung('<a id="c" href="' + A + '?token=' + knapp + '">Z</a>');
        await warte();
        // FALLSTRICK jsdom: dort ist `document.hidden` true – ein sichtbarer Tab wird gestellt.
        Object.defineProperty(w.document, 'hidden', { get: function () { return false; } });
        const vorher = z.abrufe.length;
        w.document.dispatchEvent(new w.Event('visibilitychange'));
        await warte();
        check('Sichtbarkeitswechsel erneuert einen fast abgelaufenen Schluessel', z.abrufe.length === vorher + 1);
        check('… und der Link traegt danach einen frischen',
            !w.JarvisDL.veraltet(w.document.getElementById('c').getAttribute('href')));
        dom.window.close();
    }

    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})().catch(e => { console.error('ABBRUCH: ' + (e && e.stack || e)); process.exit(2); });
