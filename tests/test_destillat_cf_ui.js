/* Waechter: "Als neue Confluence-Seite" im Wissens-Destillat (Vorgabe 2026-09-29).
 *
 * Gemessen wird am ECHTEN DOM: die echte `wissen.html` mit dem echten
 * `wissen_destillat.js`, `icons.js` und `i18n.js`. Geklickt und getippt wird
 * wirklich – ob ein Knopf ERSCHEINT, ob ein Kasten aufgeht, was am Ende im
 * Rumpf der Anfrage steht und ob eine Elternseite nach einem Bereichswechsel
 * noch mitgeschickt wird, kann eine Quelltext-Suche nicht beantworten.
 *
 * Geprueft wird die EIGENSCHAFT, nicht ein Wortlaut:
 *   1. der Knopf erscheint NUR, wenn Confluence aktiv und konfiguriert ist –
 *      und verschwindet wieder, wenn der Skill abgeschaltet wird
 *   2. der Titel wird vorbelegt, bearbeiteter Text wird NICHT ueberschrieben
 *   3. "Seite anlegen" ist ohne Bereich/Titel GESPERRT MIT DEM RICHTIGEN GRUND
 *   4. der Rumpf traegt Bereich, Elternseite, Titel und die Bilder
 *   5. ⚠ nach einem Bereichswechsel geht KEINE fremde Elternseite mit
 *   6. der Seitenbaum wird eingerueckt angeboten (Hierarchie sichtbar)
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');

const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0, bilanz = false;

// Frueh registrieren: ein Lauf ohne Bilanz ist von "nicht gelaufen" nicht zu
// unterscheiden (Register).
process.on('exit', function (code) {
    if (!bilanz) {
        console.log('\n\x1b[31mABGEBROCHEN – keine Bilanz\x1b[0m');
        if (code === 0) process.exitCode = 1;
    }
});
// Wachhund: haengt eine Attrappe, bricht der Lauf MIT Bilanz ab statt ins
// Zeitlimit zu laufen (die geladene Seite haelt eigene Timer).
const WACHHUND = setTimeout(function () {
    console.log('\n\x1b[31m✗ Wachhund: der Lauf haengt\x1b[0m');
    fail++;
    ende();
}, 25000);

function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function check(name, cond, detail) {
    if (typeof name !== 'string') {
        console.log('\x1b[31mABBRUCH: check() falsch herum aufgerufen\x1b[0m');
        process.exit(2);
    }
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function ende() {
    clearTimeout(WACHHUND);
    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    process.exit(fail ? 1 : 0);
}

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen_destillat.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

const GRUPPEN = [{ id: 'technik', name: 'Technik', color: '#4f6ef7' }];
const SPACES = [{ key: 'CTDP', name: 'Produkt' }, { key: 'CTDE', name: 'Entwicklung' }];
// Seitenbaum: B haengt unter A, C ist eine zweite Wurzel.
const SEITEN_CTDP = [{ id: '1', title: 'A', parent: '' },
                     { id: '2', title: 'B', parent: '1' },
                     { id: '3', title: 'C', parent: '' }];
const SEITEN_CTDE = [{ id: '9', title: 'Z', parent: '' }];

function seite(antworten) {
    const dom = new JSDOM(HTML, { runScripts: 'outside-only', url: 'https://x/wissen' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    const gesendet = [];
    // ⚠ Route ueber den PFAD, nie ueber die volle URL: ein spaeter ergaenztes
    // `?space=` verfehlt sonst jede Route (Register).
    w.fetch = function (url, opt) {
        const pfad = String(url).split('?')[0];
        gesendet.push({ pfad: pfad, voll: String(url), opt: opt || {} });
        const a = (antworten || {})[pfad];
        const d = typeof a === 'function' ? a(String(url), opt) : (a || { ok: true });
        const roh = JSON.stringify(d);
        return Promise.resolve({
            status: d.__status || 200,
            json: function () { return Promise.resolve(JSON.parse(roh)); },
            text: function () { return Promise.resolve(roh); }
        });
    };
    // ⚠ `WissenPortal.cfBaum` stellt die ECHTE Semantik, kein No-op: der
    // Container baut seine Hierarchie damit, und eine Attrappe, die alles zu
    // Wurzeln macht, prueft eine Kette, die es nicht gibt.
    w.WissenPortal = {
        reloadPending: function () {},
        cfBaum: function (pages) {
            const byId = {}, roots = [];
            pages.forEach(function (p) {
                byId[String(p.id)] = { id: String(p.id), title: p.title || '', kids: [] };
            });
            pages.forEach(function (p) {
                const n = byId[String(p.id)], par = p.parent ? String(p.parent) : '';
                if (par && byId[par]) byId[par].kids.push(n); else roots.push(n);
            });
            return roots;
        }
    };
    w.eval(ICONS);
    w.eval(I18N);
    w.eval(JS);
    w.WissenDestillat.init({
        scope: { groups: GRUPPEN, folders: [], user: 'tester' }, token: 'tok'
    });
    return { w: w, doc: w.document, gesendet: gesendet };
}

/* Bringt den Container in den Zustand "Destillat liegt vor" – ueber den
 * ECHTEN Bedienweg (tippen, Knopf druecken), nicht durch Setzen von `hidden`:
 * ein Kasten, der von Hand aufgeklappt wird, stellt den Regelfall nicht her
 * (Register, beim Bau des Destillats bezahlt). */
function mitErgebnis(extra) {
    const routen = Object.assign({
        '/api/wissen/destillat/lauf': {
            ok: true, markdown: '# Mein Titel\n\nInhalt mit [BILD-1].', bloecke: 1
        },
        '/api/wissen/confluence/pages': function (url) {
            return { ok: true, pages: url.indexOf('CTDE') >= 0 ? SEITEN_CTDE : SEITEN_CTDP };
        }
    }, extra || {});
    const s = seite(routen);
    const ta = s.doc.getElementById('wi-dest-text');
    ta.value = 'Text';
    ta.dispatchEvent(new s.w.Event('input'));
    s.doc.getElementById('wi-dest-run').click();
    return s;
}

function warte(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

(async function () {
    // ════════════════════════════════════════════════════════════════════
    abschnitt('1. Der Knopf haengt am Confluence-Zustand');
    {
        const s = mitErgebnis();
        await warte(30);
        const knopf = s.doc.getElementById('wi-dest-cf');
        check('ohne Meldung von wissen.js ist der Knopf versteckt',
              knopf.hidden === true);

        s.w.WissenDestillat.confluence(true, SPACES);
        check('Confluence aktiv -> der Knopf erscheint', knopf.hidden === false);

        // ⚠ UND ER VERSCHWINDET WIEDER. Wird der Skill abgeschaltet, bliebe er
        // sonst stehen und fuehrte in einen Endpunkt, der 400 antwortet.
        s.w.WissenDestillat.confluence(false, null);
        check('Skill abgeschaltet -> der Knopf verschwindet wieder',
              knopf.hidden === true);
        check('… und der Zielkasten wird dabei geschlossen',
              s.doc.getElementById('wi-dest-cfbox').hidden === true);

        // Der Container darf die Bereichsliste NICHT selbst holen.
        check('kein eigener Abruf von /api/wissen/confluence/spaces',
              s.gesendet.every(function (g) {
                  return g.pfad !== '/api/wissen/confluence/spaces';
              }), s.gesendet.map(function (g) { return g.pfad; }).join(', '));
    }

    // ════════════════════════════════════════════════════════════════════
    abschnitt('2. Titelvorschlag – und die Arbeit des Benutzers bleibt stehen');
    {
        const s = mitErgebnis();
        await warte(30);
        s.w.WissenDestillat.confluence(true, SPACES);
        const kasten = s.doc.getElementById('wi-dest-cfbox');
        check('der Zielkasten ist zunaechst ZU', kasten.hidden === true);
        s.doc.getElementById('wi-dest-cf').click();
        check('Klick oeffnet ihn', kasten.hidden === false);

        const titel = s.doc.getElementById('wi-dest-cftitel');
        check('der Titel ist aus der ersten Ueberschrift vorbelegt',
              titel.value === 'Mein Titel', titel.value);

        // ⚠ EIN BEARBEITETER TITEL DARF NICHT UEBERSCHRIEBEN WERDEN.
        titel.value = 'Eigener Name';
        titel.dispatchEvent(new s.w.Event('input'));
        s.doc.getElementById('wi-dest-cfcancel').click();
        s.doc.getElementById('wi-dest-cf').click();
        check('erneutes Oeffnen behaelt den bearbeiteten Titel',
              titel.value === 'Eigener Name', titel.value);
    }

    // ════════════════════════════════════════════════════════════════════
    abschnitt('3. Gesperrt MIT dem RICHTIGEN Grund');
    {
        const s = mitErgebnis();
        await warte(30);
        s.w.WissenDestillat.confluence(true, SPACES);
        s.doc.getElementById('wi-dest-cf').click();
        const btn = s.doc.getElementById('wi-dest-cfgo');
        const sel = s.doc.getElementById('wi-dest-cfspace');
        const titel = s.doc.getElementById('wi-dest-cftitel');

        check('ohne Bereich gesperrt', btn.disabled === true);
        // Der Grund muss der RICHTIGE sein – ein Knopf, der nach dem Titel
        // fragt, obwohl der Titel steht, schickt an die falsche Stelle.
        check('… und der Grund nennt den BEREICH',
              /Bereich/i.test(btn.title), btn.title);

        // ⚠ ERST die Optionen, DANN der Wert: an einem leeren <select> verpufft
        // die Zuweisung still (Register).
        check('das Pulldown traegt die echten Bereiche',
              sel.querySelectorAll('option[value="CTDP"]').length === 1,
              sel.innerHTML.slice(0, 120));
        sel.value = 'CTDP';
        sel.dispatchEvent(new s.w.Event('change'));
        titel.value = '';
        titel.dispatchEvent(new s.w.Event('input'));
        check('mit Bereich, ohne Titel: weiterhin gesperrt', btn.disabled === true);
        check('… und der Grund nennt jetzt den TITEL',
              /Titel/i.test(btn.title), btn.title);

        titel.value = 'Neue Seite';
        titel.dispatchEvent(new s.w.Event('input'));
        check('mit Bereich UND Titel: frei', btn.disabled === false);
        check('… ohne Tooltip (ein leerer Grund bei freiem Knopf waere ein Raetsel)',
              !btn.title);
    }

    // ════════════════════════════════════════════════════════════════════
    abschnitt('4. Der Seitenbaum wird eingerueckt angeboten');
    {
        const s = mitErgebnis();
        await warte(30);
        s.w.WissenDestillat.confluence(true, SPACES);
        s.doc.getElementById('wi-dest-cf').click();
        const sel = s.doc.getElementById('wi-dest-cfspace');
        sel.value = 'CTDP';
        sel.dispatchEvent(new s.w.Event('change'));
        await warte(30);

        const eltern = s.doc.getElementById('wi-dest-cfparent');
        const opts = Array.prototype.map.call(eltern.options, function (o) {
            return { v: o.value, t: o.textContent };
        });
        check('die Startseite steht als erste Wahl da',
              opts.length > 0 && opts[0].v === '', JSON.stringify(opts[0] || {}));
        check('alle drei Seiten sind waehlbar', opts.length === 4,
              JSON.stringify(opts));
        // Tiefensuche-Reihenfolge: A, dann sein Kind B, dann C.
        check('Reihenfolge ist die des Baums (A, B, C)',
              opts[1].v === '1' && opts[2].v === '2' && opts[3].v === '3',
              JSON.stringify(opts));
        // ⚠ DIE EINRUECKUNG MUSS SICHTBAR SEIN: ein <option> faltet gewoehnliche
        // Leerzeichen zusammen, dann saehe der Baum wie eine flache Liste aus.
        check('das Kind ist mit U+00A0 eingerueckt',
              opts[2].t.charCodeAt(0) === 0x00a0, JSON.stringify(opts[2].t));
        check('die Wurzel ist NICHT eingerueckt',
              opts[1].t.charCodeAt(0) !== 0x00a0, JSON.stringify(opts[1].t));
    }

    // ════════════════════════════════════════════════════════════════════
    abschnitt('5. Was wirklich gesendet wird');
    {
        const s = mitErgebnis({
            '/api/wissen/destillat/confluence': {
                ok: true, __status: 201, id: '42', title: 'Neue Seite',
                link: 'https://cf/x/42', bilder: 1, bilder_fehler: []
            }
        });
        await warte(30);
        s.w.WissenDestillat.confluence(true, SPACES);
        s.doc.getElementById('wi-dest-cf').click();
        const sel = s.doc.getElementById('wi-dest-cfspace');
        sel.value = 'CTDP';
        sel.dispatchEvent(new s.w.Event('change'));
        await warte(30);
        s.doc.getElementById('wi-dest-cfparent').value = '2';
        const titel = s.doc.getElementById('wi-dest-cftitel');
        titel.value = 'Neue Seite';
        titel.dispatchEvent(new s.w.Event('input'));

        s.doc.getElementById('wi-dest-cfgo').click();
        await warte(40);

        const letzte = s.gesendet[s.gesendet.length - 1];
        check('der Endpunkt wird gerufen',
              letzte.pfad === '/api/wissen/destillat/confluence', letzte.pfad);
        const rumpf = JSON.parse(letzte.opt.body || '{}');
        check('Bereich im Rumpf', rumpf.space === 'CTDP', String(rumpf.space));
        check('Elternseite im Rumpf', rumpf.parent === '2', String(rumpf.parent));
        check('Titel im Rumpf', rumpf.titel === 'Neue Seite', String(rumpf.titel));
        check('das Markdown im Rumpf ist das Destillat',
              /Mein Titel/.test(rumpf.markdown || ''), String(rumpf.markdown));
        check('die Bilder gehen mit (sie werden Anhaenge)',
              Array.isArray(rumpf.bilder), JSON.stringify(rumpf.bilder));

        const st = s.doc.getElementById('wi-dest-cfstatus');
        check('die neue Seite steht als LINK da (nicht als Kennung)',
              !!st.querySelector('a[href="https://cf/x/42"]'), st.innerHTML);
        check('… und oeffnet in einem neuen Tab mit noopener',
              /noopener/.test((st.querySelector('a') || {}).rel || ''), st.innerHTML);
    }

    // ════════════════════════════════════════════════════════════════════
    abschnitt('6. ⚠ Ein Bereichswechsel setzt die Elternseite zurueck');
    {
        const s = mitErgebnis({ '/api/wissen/destillat/confluence': { ok: true, __status: 201, id: '1', title: 'T' } });
        await warte(30);
        s.w.WissenDestillat.confluence(true, SPACES);
        s.doc.getElementById('wi-dest-cf').click();
        const sel = s.doc.getElementById('wi-dest-cfspace');
        const eltern = s.doc.getElementById('wi-dest-cfparent');
        sel.value = 'CTDP';
        sel.dispatchEvent(new s.w.Event('change'));
        await warte(30);
        eltern.value = '2';                       // Seite aus CTDP
        check('Positivkontrolle: die Elternseite ist wirklich gesetzt',
              eltern.value === '2', eltern.value);

        // ⚠ DAS IST DIE TRAGENDE ZUSAGE. Bleibt die alte Auswahl stehen,
        // waehrend die neue Seitenliste noch unterwegs ist, schickt der naechste
        // Klick eine Seiten-ID aus einem FREMDEN Bereich mit.
        sel.value = 'CTDE';
        sel.dispatchEvent(new s.w.Event('change'));
        check('sofort nach dem Wechsel ist die Elternseite leer',
              eltern.value === '', eltern.value);
        check('… und die Seite des alten Bereichs wird gar nicht mehr angeboten',
              eltern.querySelectorAll('option[value="2"]').length === 0,
              eltern.innerHTML.slice(0, 120));

        const titel = s.doc.getElementById('wi-dest-cftitel');
        titel.value = 'T';
        titel.dispatchEvent(new s.w.Event('input'));
        s.doc.getElementById('wi-dest-cfgo').click();
        await warte(40);

        const rumpf = JSON.parse(s.gesendet[s.gesendet.length - 1].opt.body || '{}');
        check('der neue Bereich geht raus', rumpf.space === 'CTDE', String(rumpf.space));
        check('⚠ die Elternseite des ALTEN Bereichs geht NICHT mit',
              !rumpf.parent, String(rumpf.parent));

        // Nach dem Laden bietet das Pulldown die Seiten des NEUEN Bereichs an.
        await warte(30);
        check('danach steht die Seite des neuen Bereichs zur Wahl',
              eltern.querySelectorAll('option[value="9"]').length === 1,
              eltern.innerHTML.slice(0, 120));
    }

    // ════════════════════════════════════════════════════════════════════
    abschnitt('7. Ein neues Destillat setzt das Ziel zurueck');
    {
        const s = mitErgebnis();
        await warte(30);
        s.w.WissenDestillat.confluence(true, SPACES);
        s.doc.getElementById('wi-dest-cf').click();
        const titel = s.doc.getElementById('wi-dest-cftitel');
        titel.value = 'Alter Name';
        titel.dispatchEvent(new s.w.Event('input'));

        // Zweiter Lauf mit anderem Inhalt – ueber den echten Bedienweg.
        const ta = s.doc.getElementById('wi-dest-text');
        ta.value = 'Anderer Text';
        ta.dispatchEvent(new s.w.Event('input'));
        s.doc.getElementById('wi-dest-run').click();
        await warte(40);

        check('der Zielkasten ist wieder zu',
              s.doc.getElementById('wi-dest-cfbox').hidden === true);
        s.doc.getElementById('wi-dest-cf').click();
        check('⚠ der Titel des VORIGEN Laufs steht nicht mehr da',
              titel.value !== 'Alter Name', titel.value);
    }

    ende();
})().catch(function (e) {
    console.log('\x1b[31m✗ Ausnahme: ' + (e && e.stack || e) + '\x1b[0m');
    fail++;
    ende();
});
