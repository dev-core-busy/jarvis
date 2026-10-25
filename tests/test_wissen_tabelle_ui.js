/* Waechter: "Mein Wissen" als sortierbare Tabelle + Seitenbreite per Knopf.
 *
 * Vorgabe 2026-09-27: "/wissen mit einem '[]' button vergroesserbar und unter
 * 'Mein Wissen' eine sortierbare dreispalten Ausgabe … fuege 'Groesse' noch
 * dazu" – also vier Spalten: Name · Ordner · Wissensgruppen · Groesse.
 *
 * Gemessen wird am ECHTEN DOM: die echte `wissen.html` mit der echten
 * `wissen.js`, `icons.js` und `i18n.js`; die Liste entsteht ueber den ECHTEN
 * Weg `loadScope -> loadFiles -> renderFileList` an einer fetch-Attrappe, und
 * sortiert wird per KLICK auf den Spaltenkopf. Ob eine Reihenfolge ENTSTEHT,
 * kann eine Quelltext-Suche nicht beantworten.
 *
 * Geprueft wird die EIGENSCHAFT:
 *   1. vier Spalten in der verlangten Reihenfolge, jede per Kopf sortierbar
 *   2. Vorgabe Name aufsteigend – deutsch (Umlaut, Zahl im Namen)
 *   3. Klick: gleiche Spalte kehrt um, neue Spalte beginnt aufsteigend;
 *      Zustand in aria-sort UND als Pfeil
 *   4. Groesse: numerisch, UNBEKANNT steht in beiden Richtungen am Ende,
 *      0 Byte ist "0 B" und kein Strich
 *   5. die Sortierung ueberlebt das Tippen in der Suche
 *   6. eine Tabellenzeile ist eine Tabellenzeile (nicht `.wi-item` = flex)
 *   7. Maximieren sitzt hinter "Angemeldet als" ganz oben (weder in der
 *      Titelleiste noch in "Mein Wissen", Vorgabe 2026-09-27), hebt die
 *      900-px-Deckelung fuer ALLE Abschnitte auf, je Browser gemerkt
 *   8. alle neuen Texte in DE und EN
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');

const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0;
let bilanz = false;

function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function check(name, cond, detail) {
    if (typeof name !== 'string') {
        console.log('\x1b[31mABBRUCH: check() falsch herum aufgerufen\x1b[0m');
        process.exit(2);
    }
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function abbruch(t) { console.log('\x1b[31mABBRUCH: ' + t + '\x1b[0m'); process.exit(2); }

process.on('exit', function (code) {
    if (!bilanz && code === 0) {
        console.log('\x1b[31mABBRUCH: Lauf endete ohne Bilanzzeile\x1b[0m');
        process.exitCode = 1;
    }
});
process.on('unhandledRejection', function (e) {
    console.log('\x1b[31mABBRUCH: unbehandelte Zurueckweisung: ' + (e && e.stack || e) + '\x1b[0m');
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
WACHHUND.unref && WACHHUND.unref();

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8');
const JS_WISSEN = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen.js'), 'utf8');
const JS_ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');
const JS_I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const JS_SEITE_BREIT = fs.readFileSync(path.join(ROOT, 'frontend/js/seite_breit.js'), 'utf8');

const G_A = { id: 'a', name: 'Allgemein', color: '#22c55e', folders: ['data/rag/a'] };
const G_Z = { id: 'z', name: 'Zentrale', color: '#8b5cf6', folders: [] };

// Absichtlich NICHT vorsortiert – sonst waere jede Reihenfolge-Pruefung
// trivial wahr (Register: der Testbestand stand zufaellig schon richtig).
function bestand() {
    return [
        { path: 'data/rag/z/Datei 10.md', name: 'Datei 10.md', folder: 'z',
          groups: [G_Z], size: 5000 },
        { path: 'data/rag/a/Birne.pdf', name: 'Birne.pdf', folder: 'a/Obst',
          groups: [G_A], size: 1536 },
        { path: 'data/rag/a/Äpfel.docx', name: 'Äpfel.docx', folder: 'a',
          groups: [G_A, G_Z], size: null },
        { path: 'data/rag/a/Datei 2.md', name: 'Datei 2.md', folder: 'm',
          groups: [G_Z], size: 0 },
        { path: 'data/rag/a/Cola.txt', name: 'Cola.txt', folder: 'b',
          groups: [G_A], size: 3 * 1024 * 1024 },
    ];
}

async function seite(dateien, vorher) {
    const dom = new JSDOM(HTML, { url: 'https://localhost/wissen', runScripts: 'outside-only' });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    win.localStorage.setItem('jarvis_lang', 'de');
    Object.keys(vorher || {}).forEach(function (k) { win.localStorage.setItem(k, vorher[k]); });
    win.requestAnimationFrame = function (cb) { return setTimeout(cb, 0); };
    win.matchMedia = win.matchMedia || function () {
        return { matches: false, addListener: function () {}, removeListener: function () {},
                 addEventListener: function () {}, removeEventListener: function () {} };
    };
    const bestaetigt = [];
    function antwort(k) {
        return Promise.resolve({ ok: true, status: 200, json: function () { return Promise.resolve(k); } });
    }
    const attrappe = function (url) {
        const p = String(url).split('?')[0];
        if (p === '/api/wissen/scope') {
            return antwort({ ok: true, user: 'anna', is_editor: false, is_admin: false,
                             groups: [G_A, G_Z], folders: [] });
        }
        if (p === '/api/wissen/files') return antwort({ ok: true, files: dateien });
        return antwort({ ok: true, pending: [], spaces: [], status: 'ok', files: [] });
    };
    win.fetch = attrappe;
    global.fetch = attrappe;
    win.confirm = function (text) { bestaetigt.push(text); return false; };
    win.alert = function () {};
    // sitzung.js vor jedem Modul-Eval: die Module lesen den Sitzungstoken
    // seit dem 2026-10-01 aus der gemeinsamen Quelle und rufen sie beim
    // LADEN auf. Jede echte Seite laedt sie davor.
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(JS_ICONS);
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(JS_I18N);
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(JS_SEITE_BREIT);   // wie wissen.html: nach i18n.js, vor wissen.js
    win.eval(require('fs').readFileSync(require('path').join(__dirname, '..', 'frontend/js/sitzung.js'), 'utf8'));
    win.eval(JS_WISSEN);
    // ⚠ KEIN eigener DOMContentLoaded-Dispatch: jsdom feuert ihn selbst
    // (readyState steht direkt nach `new JSDOM` auf 'loading', gemessen: 2
    // Ereignisse mit Dispatch). Doppelt initialisiert haengt jeder Handler
    // zweimal – ein Klick auf die Klapp-Kopfzeile hob sich dann selbst auf.
    for (let i = 0; i < 80; i++) {
        await new Promise(function (r) { setTimeout(r, 5); });
        if (win.document.querySelectorAll('#wi-files-list .wi-frow').length) break;
    }
    return { win: win, doc: win.document, bestaetigt: bestaetigt };
}

function namen(doc) {
    return Array.prototype.map.call(doc.querySelectorAll('#wi-files-list .wi-frow .wi-fname'),
        function (z) { return z.textContent.trim(); });
}
function kopf(doc, key) {
    return doc.querySelector('#wi-files-list th[data-sort="' + key + '"]');
}
function klick(doc, key) {
    const th = kopf(doc, key);
    const b = th && th.querySelector('.wi-sortbtn');
    if (!b) return false;
    b.click();
    return true;
}
function i18nZahl(key) {
    return (JS_I18N.match(new RegExp("'" + key.replace('.', '\\.') + "':", 'g')) || []).length;
}

(async function () {
    const s = await seite(bestand());
    const doc = s.doc;
    const zeilen = doc.querySelectorAll('#wi-files-list .wi-frow');
    // Positivkontrolle VOR allen inhaltlichen Pruefungen – ohne gezeichnete
    // Tabelle waere jede Aussage darunter trivial.
    check('Positivkontrolle: fuenf Zeilen gezeichnet', zeilen.length === 5, String(zeilen.length));
    if (zeilen.length !== 5) abbruch('ohne gezeichnete Tabelle ist jede weitere Aussage trivial');

    abschnitt('1 – vier Spalten, jede sortierbar');
    const koepfe = Array.prototype.map.call(doc.querySelectorAll('#wi-files-list th[data-sort]'),
        function (th) { return th.getAttribute('data-sort'); });
    check('Spalten in der verlangten Reihenfolge',
          JSON.stringify(koepfe) === '["name","folder","groups","size"]', JSON.stringify(koepfe));
    const texte = Array.prototype.map.call(doc.querySelectorAll('#wi-files-list th[data-sort] .wi-sortbtn'),
        function (b) { return b.textContent.replace(/[▲▼]/g, '').trim(); });
    check('Kopfzeilen tragen die deutschen Beschriftungen',
          JSON.stringify(texte) === '["Name","Ordner","Wissensgruppen","Größe"]', JSON.stringify(texte));
    check('jeder Kopf ist ein KNOPF (per Tastatur erreichbar)',
          koepfe.every(function (k) { return !!kopf(doc, k).querySelector('button.wi-sortbtn'); }));
    check('Loeschen bleibt je Zeile erreichbar (Muelleimer)',
          doc.querySelectorAll('#wi-files-list .wi-frow .wi-file-del').length === 5);

    abschnitt('2 – Vorgabe: Name aufsteigend, deutsch sortiert');
    check('Name traegt aria-sort=ascending', kopf(doc, 'name').getAttribute('aria-sort') === 'ascending');
    check('die anderen Spalten aria-sort=none',
          ['folder', 'groups', 'size'].every(function (k) { return kopf(doc, k).getAttribute('aria-sort') === 'none'; }));
    check('Reihenfolge: Umlaut bei A, "Datei 2" vor "Datei 10"',
          JSON.stringify(namen(doc)) === '["Äpfel.docx","Birne.pdf","Cola.txt","Datei 2.md","Datei 10.md"]',
          JSON.stringify(namen(doc)));

    abschnitt('3 – Klick auf den Kopf');
    klick(doc, 'name');
    check('gleiche Spalte erneut: absteigend',
          namen(doc)[0] === 'Datei 10.md' && namen(doc)[4] === 'Äpfel.docx', JSON.stringify(namen(doc)));
    check('… aria-sort=descending', kopf(doc, 'name').getAttribute('aria-sort') === 'descending');
    check('… Pfeil ▼ sichtbar', kopf(doc, 'name').textContent.indexOf('▼') >= 0);

    klick(doc, 'folder');
    check('neue Spalte "Ordner" beginnt aufsteigend',
          JSON.stringify(namen(doc)) === '["Äpfel.docx","Birne.pdf","Cola.txt","Datei 2.md","Datei 10.md"]',
          JSON.stringify(namen(doc)));
    check('… und nur SIE traegt jetzt den Zustand',
          kopf(doc, 'folder').getAttribute('aria-sort') === 'ascending'
          && kopf(doc, 'name').getAttribute('aria-sort') === 'none');

    klick(doc, 'groups');
    // "Allgemein" < "Allgemein, Zentrale" < "Zentrale"; Gleichstand nach Name.
    check('"Wissensgruppen" sortiert nach den Gruppennamen',
          JSON.stringify(namen(doc)) === '["Birne.pdf","Cola.txt","Äpfel.docx","Datei 2.md","Datei 10.md"]',
          JSON.stringify(namen(doc)));

    abschnitt('4 – Groesse');
    klick(doc, 'size');
    check('aufsteigend numerisch, UNBEKANNT am Ende',
          JSON.stringify(namen(doc)) === '["Datei 2.md","Birne.pdf","Datei 10.md","Cola.txt","Äpfel.docx"]',
          JSON.stringify(namen(doc)));
    klick(doc, 'size');
    check('absteigend – UNBEKANNT bleibt am Ende (ist keine kleine Datei)',
          JSON.stringify(namen(doc)) === '["Cola.txt","Datei 10.md","Birne.pdf","Datei 2.md","Äpfel.docx"]',
          JSON.stringify(namen(doc)));
    const groesse = {};
    Array.prototype.forEach.call(doc.querySelectorAll('#wi-files-list .wi-frow'), function (z) {
        groesse[z.querySelector('.wi-fname').textContent.trim()] = z.querySelector('td.wi-fsize');
    });
    check('0 Byte wird "0 B" – kein Strich', groesse['Datei 2.md'] && groesse['Datei 2.md'].textContent === '0 B',
          groesse['Datei 2.md'] && groesse['Datei 2.md'].textContent);
    check('1536 Byte → "1,5 KB" (deutsches Komma)',
          groesse['Birne.pdf'] && groesse['Birne.pdf'].textContent === '1,5 KB',
          groesse['Birne.pdf'] && groesse['Birne.pdf'].textContent);
    check('3 MiB → "3 MB"', groesse['Cola.txt'] && groesse['Cola.txt'].textContent === '3 MB',
          groesse['Cola.txt'] && groesse['Cola.txt'].textContent);
    const unb = groesse['Äpfel.docx'];
    check('unbekannte Groesse: Strich …', !!unb && unb.textContent === '–', unb && unb.textContent);
    check('… MIT Grund im title', !!unb && (unb.getAttribute('title') || '').length > 10,
          unb && unb.getAttribute('title'));

    abschnitt('5 – Sortierung ueberlebt die Suche');
    const q = doc.getElementById('wi-files-q');
    if (!q) abbruch('Suchfeld fehlt');
    q.value = 'datei';
    q.dispatchEvent(new s.win.Event('input'));
    check('gefiltert UND weiter nach Groesse absteigend',
          JSON.stringify(namen(doc)) === '["Datei 10.md","Datei 2.md"]', JSON.stringify(namen(doc)));
    check('… Kopf zeigt weiter den Zustand', kopf(doc, 'size').getAttribute('aria-sort') === 'descending');
    q.value = '';
    q.dispatchEvent(new s.win.Event('input'));

    abschnitt('6 – Tabellenzeile bleibt Tabellenzeile');
    const tr = doc.querySelector('#wi-files-list .wi-frow');
    check('Zeile ist ein <tr>', !!tr && tr.tagName === 'TR');
    // `.wi-item` traegt `display: flex` (Entwurfsliste) – an einem <tr> zerlegte
    // das die Tabelle, und jsdom rechnet kein Layout: gemessen wird die Regel.
    check('Zeile traegt NICHT `.wi-item` (display: flex)', !!tr && !tr.classList.contains('wi-item'));
    check('berechnetes display ist table-row',
          !!tr && s.win.getComputedStyle(tr).display === 'table-row', tr && s.win.getComputedStyle(tr).display);
    // Loeschen ueber die neue Zeile: die Rueckfrage nennt Ordner UND Namen.
    const del = tr && tr.querySelector('.wi-file-del');
    if (del) del.dispatchEvent(new s.win.Event('click', { bubbles: true }));
    await new Promise(function (r) { setTimeout(r, 5); });
    check('Loeschen fragt nach – mit Ordner und Namen',
          s.bestaetigt.length === 1 && /\//.test(s.bestaetigt[0]), JSON.stringify(s.bestaetigt));

    abschnitt('7 – Maximieren: hinter "Angemeldet als", ganze Seite breit');
    // Vorgabe 2026-09-27 (zweite Fassung): Knopf hinter "Angemeldet als ..."
    // ganz oben auf der Seite; maximiert passen sich ALLE Abschnitte an die
    // Fensterbreite an. Seit 2026-09-28 der gemeinsame Baustein (seite_breit.js).
    // ⚠ DIE BREITE SELBST misst hier niemand mehr: die Regel steht in theme.css,
    // und jsdom ignoriert die Spezifitaet (Register) – das tun
    // live_wissen_tabelle_ui.py und live_seite_breit_ui.py im echten Chrome.
    check('KEIN Maximieren-Knopf in der Titelleiste',
          !doc.querySelector('.wi-topbar [data-i18n-title="common.maximize"], .wi-topbar .jv-max-btn'));
    check('KEIN Maximieren-Knopf mehr in "Mein Wissen"',
          !doc.querySelector('#wi-sec-files .jv-max-btn, #wi-files-max'));
    const b = doc.getElementById('jv-max');
    const banner = doc.getElementById('wi-scope-banner');
    const wrap = doc.getElementById('wi-app');
    check('Knopf steht direkt hinter dem Banner "Angemeldet als"',
          !!b && !!banner && banner.nextElementSibling === b);
    check('… und ist KEIN Kind des Banners (renderScope schreibt es per innerHTML neu)',
          !!b && !!banner && !banner.contains(b));
    check('Positivkontrolle: Banner zeigt "Angemeldet als"',
          !!banner && /Angemeldet als/.test(banner.textContent), banner && banner.textContent);
    check('… Zeile mit Banner und Knopf ist das erste Element der Seite',
          !!b && !!wrap && wrap.firstElementChild === b.parentElement);
    if (!b || !wrap) { check('Maximieren: abhaengige Pruefungen NICHT PRUEFBAR (Knopf fehlt)', false); }
    else {
        const mw = function () { return s.win.getComputedStyle(wrap).maxWidth; };
        check('vorher: aria-pressed=false, Beschriftung "Maximieren"',
              b.getAttribute('aria-pressed') === 'false' && b.getAttribute('aria-label') === 'Maximieren');
        check('Positivkontrolle: vorher ist die Seite auf 900px gedeckelt', mw() === '900px', mw());
        check('der Bereich ist als "wird breit" markiert', wrap.hasAttribute('data-jv-breit'));
        const zeichenVor = b.textContent;
        b.click();
        check('nach Klick: Seite breit (body.jv-breit)', doc.body.classList.contains('jv-breit'));
        check('… kein einzelner Abschnitt ist fixiert',
              ![].some.call(doc.querySelectorAll('.wi-section'),
                  function (x) { return s.win.getComputedStyle(x).position === 'fixed'; }));
        check('… aria-pressed=true, Beschriftung "Verkleinern", Zeichen 🗗',
              b.getAttribute('aria-pressed') === 'true' && b.getAttribute('aria-label') === 'Verkleinern'
              && b.textContent === '\u{1F5D7}' && b.textContent !== zeichenVor, JSON.stringify(b.textContent));
        check('… die i18n-Attribute wandern mit',
              b.getAttribute('data-i18n-title') === 'common.minimize');
        check('… die Tabelle bleibt bedienbar (Sortierkopf-Klick sortiert weiter)',
              klick(doc, 'name') && kopf(doc, 'name').getAttribute('aria-sort') !== 'none');
        b.click();
        check('zweiter Klick verkleinert wieder', !doc.body.classList.contains('jv-breit')
              && b.getAttribute('aria-label') === 'Maximieren');
        // Der Zustand wird JE BROWSER GEMERKT (Vorgabe 2026-09-27, dritte
        // Fassung). ⚠ Jede jsdom-Seite hat ihren EIGENEN localStorage – ein
        // "neue Seite startet nicht maximiert" war darum immer wahr, gleich was
        // der Code tat. Gemessen wird deshalb (a) was der Klick SCHREIBT und
        // (b) wie eine Seite MIT diesem Wert startet.
        check('Verkleinern merkt "0"', s.win.localStorage.getItem('jarvis_wissen_breit') === '0',
              s.win.localStorage.getItem('jarvis_wissen_breit'));
        b.click();
        check('Maximieren merkt "1"', s.win.localStorage.getItem('jarvis_wissen_breit') === '1',
              s.win.localStorage.getItem('jarvis_wissen_breit'));
        const gemerkt = s.win.localStorage.getItem('jarvis_wissen_breit');
        const s2 = await seite(bestand(), { jarvis_wissen_breit: gemerkt });
        const b2 = s2.doc.getElementById('jv-max');
        check('neue Seite mit gemerktem "1" startet MAXIMIERT',
              s2.doc.body.classList.contains('jv-breit'));
        check('… und der Knopf zeigt "Verkleinern" (Zustand und Knopf stimmen ueberein)',
              !!b2 && b2.getAttribute('aria-pressed') === 'true'
              && b2.getAttribute('aria-label') === 'Verkleinern');
        try { s2.win.close(); } catch (e) {}
        const s3 = await seite(bestand(), { jarvis_wissen_breit: '0' });
        check('neue Seite mit gemerktem "0" startet normal',
              !s3.doc.body.classList.contains('jv-breit'));
        try { s3.win.close(); } catch (e) {}
        const s4 = await seite(bestand());
        check('ohne gemerkten Wert: normal (Vorgabe bleibt 900 px)',
              !s4.doc.body.classList.contains('jv-breit'));
        try { s4.win.close(); } catch (e) {}
    }

    abschnitt('8 – Texte in DE und EN');
    const fehlt = ['wissen.col_name', 'wissen.col_folder', 'wissen.col_groups', 'wissen.col_size',
                   'wissen.sort_by', 'wissen.size_unknown', 'common.maximize', 'common.minimize']
        .filter(function (k) { return i18nZahl(k) !== 2; });
    check('alle neuen Schluessel genau zweimal (DE + EN)', fehlt.length === 0, fehlt.join(', '));

    try { s.win.close(); } catch (e) {}
    clearTimeout(WACHHUND);
    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
    process.exit(fail === 0 ? 0 : 1);
})();
