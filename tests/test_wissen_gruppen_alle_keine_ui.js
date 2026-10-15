/* Waechter: jede Wissensgruppen-Auswahl unter /wissen hat "Alle" und "Keine".
 *
 * Vorgabe 2026-09-28: "wir benoetigen eine 'keiner'/'alle' markieren Option
 * fuer Wissensgruppen unter /wissen (ueberall da, wo Wissensgruppen per
 * Checkbox ausgewaehlt werden koennen)".
 *
 * Gemessen am ECHTEN DOM: die echte `wissen.html` mit `icons.js`, `i18n.js`,
 * `wissen_destillat.js` und `wissen.js` (in der Reihenfolge der Seite). Geklickt
 * wird der echte Knopf; geprueft wird die WIRKUNG, nicht das Vorkommen:
 *   1. an jeder Auswahl (Extraktor, Dateifilter, Confluence, Destillat) steht
 *      genau EINE Leiste mit zwei Knoepfen - NICHT im <label> (sonst schaltet
 *      der Browser zusaetzlich ein Kaestchen um)
 *   2. "Alle"/"Keine" setzen die Kaestchen UND die Hoerer laufen mit:
 *      Extraktor -> "Extrahieren" frei/gesperrt, Dateifilter -> Liste + Cookie
 *   3. eine Leiste schaltet NUR ihre eigene Reihe
 *   4. bei genau EINER Gruppe gibt es keine Leiste (nichts zu waehlen)
 *   5. die Texte gibt es in DE und EN
 */
'use strict';
const fs = require('fs');
const path = require('path');

const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0;
let bilanz = false;

function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function abbruch(t) { console.log('\x1b[31mABBRUCH: ' + t + '\x1b[0m'); bilanz = true; process.exit(2); }

process.on('exit', function (code) {
    if (!bilanz && code === 0) {
        console.log('\x1b[31mABBRUCH: Lauf endete ohne Bilanzzeile\x1b[0m');
        process.exitCode = 1;
    }
});
process.on('unhandledRejection', function (e) {
    console.log('\x1b[31mABBRUCH: unbehandelte Zurueckweisung: ' + (e && e.stack || e) + '\x1b[0m');
    bilanz = true;
    process.exit(1);
});
const WACHHUND = setTimeout(function () {
    bilanz = true;
    console.log('\x1b[31m✗ Wachhund: der Lauf haengt (>40 s)\x1b[0m');
    process.exit(1);
}, 40000);
WACHHUND.unref && WACHHUND.unref();

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8');
const JS = ['icons.js', 'i18n.js', 'wissen_destillat.js', 'wissen.js'].map(function (n) {
    return fs.readFileSync(path.join(ROOT, 'frontend/js', n), 'utf8');
});

const GRUPPEN = [
    { id: 'allgemein', name: 'community', color: '#22c55e', folders: ['data/rag/community'] },
    { id: 'technik', name: 'Handbuecher', color: '#8b5cf6', folders: ['data/rag/community'] },
    { id: 'vertrieb', name: 'Vertrieb', color: '#4f6ef7', folders: ['data/rag/community'] },
];
function dateien(gruppen) {
    return gruppen.map(function (g, i) {
        return { path: 'data/rag/community/d' + i + '.md', name: 'd' + i + '.md',
                 folder: 'community', groups: [g] };
    });
}

function schlaf(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

async function seite(gruppen) {
    const dom = new JSDOM(HTML, { url: 'https://localhost/wissen', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    win.document.cookie = 'jarvis_wissen_gfilter_off=;path=/';
    win.requestAnimationFrame = function (cb) { return setTimeout(cb, 0); };
    win.matchMedia = win.matchMedia || function () {
        return { matches: false, addListener: function () {}, removeListener: function () {},
                 addEventListener: function () {}, removeEventListener: function () {} };
    };
    function antwort(k) {
        const roh = JSON.stringify(k);
        return Promise.resolve({ ok: true, status: 200,
            json: function () { return Promise.resolve(JSON.parse(roh)); },
            text: function () { return Promise.resolve(roh); } });
    }
    // Routing ueber den PFAD, nie ueber die volle URL (Register).
    win.fetch = function (url) {
        const p = String(url).split('?')[0];
        if (p === '/api/wissen/scope') {
            return antwort({ ok: true, user: 'anna', is_editor: false, is_admin: false,
                             groups: gruppen, folders: [{ path: 'data/rag/community',
                             name: 'community', root: 'data/rag/community', depth: 0 }] });
        }
        if (p === '/api/wissen/files') return antwort({ ok: true, files: dateien(gruppen) });
        if (p === '/api/wissen/confluence/bindung') return antwort({ ok: true, aktiv: true, bereiche: [] });
        if (p === '/api/wissen/destillat/lauf') return antwort({ ok: true, markdown: '# D\n\nx', bloecke: 1 });
        return antwort({ ok: true, pending: [], spaces: [], status: 'ok' });
    };
    win.confirm = function () { return false; };
    win.alert = function () {};
    // sitzung.js vor jedem Modul-Eval: die Module lesen den Sitzungstoken
    // seit dem 2026-10-01 aus der gemeinsamen Quelle (frontend/js/sitzung.js)
    // und rufen sie beim LADEN auf. Jede echte Seite laedt sie als erstes
    // Skript. Ohne diese Zeile stirbt der Aufbau still: der Waechter endet mit
    // Exit 0 und MESSEN TUT ER NICHTS MEHR.
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    JS.forEach(function (j) { win.eval(j); });
    win.document.dispatchEvent(new win.Event('DOMContentLoaded', { bubbles: true }));
    for (let i = 0; i < 80; i++) {
        await schlaf(5);
        if (win.document.querySelectorAll('#wi-files-list .wi-frow').length
            && win.document.querySelector('.wi-grp-cfb')) break;
    }
    return { win: win, doc: win.document };
}

function kaestchen(doc, cls) {
    return Array.prototype.slice.call(doc.querySelectorAll('input.' + cls));
}
function an(doc, cls) { return kaestchen(doc, cls).filter(function (c) { return c.checked; }).length; }
// Die Leiste einer Reihe: die, deren Knoepfe diese Klasse schalten.
function leisten(doc, cls) {
    return Array.prototype.slice.call(doc.querySelectorAll('.wi-grp-bulk')).filter(function (b) {
        const k = b.querySelector('.wi-grp-bulkbtn');
        return k && k.getAttribute('data-grp-cls') === cls;
    });
}
function knopf(doc, cls, alle) {
    const l = leisten(doc, cls)[0];
    return l ? l.querySelector('.wi-grp-bulkbtn[data-grp-an="' + (alle ? '1' : '0') + '"]') : null;
}
function klick(doc, cls, alle) {
    const k = knopf(doc, cls, alle);
    if (!k) return false;
    k.click();
    return true;
}
function zeilen(doc) { return doc.querySelectorAll('#wi-files-list .wi-frow').length; }
function cookieAus(doc) {
    const m = /(?:^|;\s*)jarvis_wissen_gfilter_off=([^;]*)/.exec(doc.cookie);
    return m ? decodeURIComponent(m[1]).split(',').filter(Boolean) : [];
}

(async function () {
    const s = await seite(GRUPPEN);
    const doc = s.doc;

    abschnitt('0 – Positivkontrolle: die Reihen sind gezeichnet');
    const reihen = { up: 'wi-grp-up', flt: 'wi-grp-flt', cfb: 'wi-grp-cfb' };
    Object.keys(reihen).forEach(function (k) {
        const n = kaestchen(doc, reihen[k]).length;
        if (n !== 3) abbruch(reihen[k] + ': ' + n + ' Kaestchen statt 3 - ohne Reihe ist jede Aussage trivial');
    });
    check('Extraktor, Dateifilter und Confluence haben je 3 Kaestchen', true);

    abschnitt('1 – je Reihe genau EINE Leiste, Knoepfe ausserhalb des <label>');
    Object.keys(reihen).forEach(function (k) {
        const cls = reihen[k];
        const l = leisten(doc, cls);
        check(cls + ': genau eine Leiste', l.length === 1, 'gefunden: ' + l.length);
        const kn = l[0] ? l[0].querySelectorAll('button.wi-grp-bulkbtn') : [];
        check(cls + ': zwei Knoepfe, type=button',
              kn.length === 2 && Array.prototype.every.call(kn, function (b) { return b.type === 'button'; }));
        check(cls + ': kein Knopf steckt in einem <label>',
              Array.prototype.every.call(kn, function (b) { return !b.closest('label'); }));
    });
    check('Knopftexte sind uebersetzt (kein roher Schluessel)',
          (knopf(doc, 'wi-grp-up', true) || {}).textContent === 'Alle'
          && (knopf(doc, 'wi-grp-up', false) || {}).textContent === 'Keine');

    abschnitt('2a – Extraktor: Wirkung auf "Extrahieren"');
    const ext = doc.getElementById('wi-extract-btn');
    if (!ext) abbruch('#wi-extract-btn fehlt');
    check('Ausgang: nichts gewaehlt, "Extrahieren" gesperrt', an(doc, 'wi-grp-up') === 0 && ext.disabled === true);
    klick(doc, 'wi-grp-up', true);
    check('"Alle" hakt alle 3 an', an(doc, 'wi-grp-up') === 3, String(an(doc, 'wi-grp-up')));
    check('… und der Hoerer lief: "Extrahieren" frei', ext.disabled === false);
    klick(doc, 'wi-grp-up', false);
    check('"Keine" nimmt alle Haken', an(doc, 'wi-grp-up') === 0);
    check('… und "Extrahieren" ist wieder gesperrt', ext.disabled === true);

    abschnitt('2b – Dateifilter: Wirkung auf Liste und Cookie');
    check('Ausgang: 3 Zeilen, alle Filter an', zeilen(doc) === 3 && an(doc, 'wi-grp-flt') === 3);
    klick(doc, 'wi-grp-flt', false);
    check('"Keine": alle Filter aus', an(doc, 'wi-grp-flt') === 0);
    check('… Liste leer', zeilen(doc) === 0, String(zeilen(doc)));
    check('… Cookie merkt alle 3 als ausgeblendet', cookieAus(doc).length === 3, cookieAus(doc).join(','));
    klick(doc, 'wi-grp-flt', true);
    check('"Alle": wieder 3 Zeilen', zeilen(doc) === 3 && an(doc, 'wi-grp-flt') === 3);
    check('… Cookie leer', cookieAus(doc).length === 0, cookieAus(doc).join(','));

    abschnitt('3 – eine Leiste schaltet NUR ihre eigene Reihe');
    klick(doc, 'wi-grp-cfb', true);
    check('Confluence "Alle": alle 3 an', an(doc, 'wi-grp-cfb') === 3);
    check('… Extraktor unberuehrt (0) und Filter unberuehrt (3)',
          an(doc, 'wi-grp-up') === 0 && an(doc, 'wi-grp-flt') === 3);
    klick(doc, 'wi-grp-cfb', false);
    check('Confluence "Keine": alle aus', an(doc, 'wi-grp-cfb') === 0);

    abschnitt('2c – Destillat: Uebernahme-Auswahl');
    const ta = doc.getElementById('wi-dest-text');
    if (!ta) abbruch('#wi-dest-text fehlt');
    ta.value = 'Text';
    ta.dispatchEvent(new s.win.Event('input'));
    doc.getElementById('wi-dest-run').click();
    for (let i = 0; i < 60 && doc.getElementById('wi-dest-out').hidden; i++) await schlaf(5);
    doc.getElementById('wi-dest-take').click();
    if (kaestchen(doc, 'wi-grp-dest').length !== 3) abbruch('Destillat-Gruppen nicht gezeichnet');
    check('Destillat: genau eine Leiste', leisten(doc, 'wi-grp-dest').length === 1);
    klick(doc, 'wi-grp-dest', true);
    check('Destillat "Alle": alle 3 an', an(doc, 'wi-grp-dest') === 3);
    klick(doc, 'wi-grp-dest', false);
    check('Destillat "Keine": alle aus', an(doc, 'wi-grp-dest') === 0);

    abschnitt('4 – bei genau EINER Gruppe keine Leiste');
    const e = await seite([GRUPPEN[0]]);
    if (kaestchen(e.doc, 'wi-grp-up').length !== 1) abbruch('Einzelgruppe: Extraktor-Reihe fehlt');
    check('keine Leiste auf der ganzen Seite', e.doc.querySelectorAll('.wi-grp-bulk').length === 0,
          String(e.doc.querySelectorAll('.wi-grp-bulk').length));

    abschnitt('5 – Texte in DE und EN');
    ['wissen.grp_all', 'wissen.grp_none', 'wissen.grp_all_title', 'wissen.grp_none_title'].forEach(function (k) {
        s.win._lang = 'de'; const de = s.win.t(k);
        s.win._lang = 'en'; const en = s.win.t(k);
        check(k + ' in beiden Sprachen', de && en && de !== k && en !== k && de !== en, de + ' / ' + en);
    });

    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
    process.exit(fail ? 1 : 0);
})();
