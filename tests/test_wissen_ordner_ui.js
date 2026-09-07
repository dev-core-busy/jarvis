/* Waechter: die Dateiliste in /wissen zeigt den Ordner SICHTBAR.
 *
 * Gemeldet 2026-09-07: "in der Dateiliste erscheint nur der Dateiname. Es ist
 * nicht moeglich zu erkennen, in welchem Unterverzeichnis die Datei liegt."
 *
 * Gemessen wird am ECHTEN DOM: die echte `wissen.html` wird mit der echten
 * `wissen.js` (plus `icons.js` und `i18n.js` – ein UI-Test, der weniger laedt
 * als die Seite, prueft eine Kette, die es nicht gibt) geladen, und die Liste
 * entsteht ueber den ECHTEN Weg `loadScope -> loadFiles -> renderFileList`
 * mit einer fetch-Attrappe. Ein Quelltext-Schnitt der Renderfunktion wuerde
 * die Sichtbarkeit gar nicht beantworten.
 *
 * Geprueft wird die REGEL, nicht ein Wortlaut:
 *   1. der Ordner steht als SICHTBARER Text in der Zeile (nicht nur im title)
 *   2. gleichnamige Dateien in verschiedenen Ordnern sind unterscheidbar
 *   3. RUECKFALL: fehlt `folder` (aelteres Backend / halber Deploy), steht der
 *      rohe Verzeichnispfad da – nie nichts
 *   4. die Loesch-Rueckfrage nennt Ordner UND Namen (Datenverlust-Risiko)
 *   5. Fremdtext wird maskiert (der Ordnername kommt aus einem Dateipfad)
 *   6. `.wi-fmeta` traegt flex:1 UND min-width:0 – ohne min-width schiebt ein
 *      langer Pfad Gruppen-Marken und Muelleimer aus der Zeile
 *   7. `.wi-item .nm { flex: 1 }` BLEIBT – die Entwurfsliste darunter benutzt
 *      `.nm` weiter als direktes Flex-Kind
 */
'use strict';
const fs = require('fs');
const path = require('path');

// jsdom liegt je Maschine anders (Projekt, /tmp, System) – ein Waechter, der
// nur auf einem Rechner laeuft, ist ein halber. Fehlt es: EXIT 2, nicht 0 –
// "konnte nicht laufen" darf nie wie "bestanden" aussehen.
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

// Ein abgebrochener Lauf darf nicht wie ein bestandener aussehen (Register):
// die ganze Datei ist eine async-IIFE, ein Wurf darin uebersprang sonst die
// Bilanz und Node beendete mit 0.
process.on('exit', function (code) {
    if (!bilanz && code === 0) {
        console.log('\x1b[31mABBRUCH: Lauf endete ohne Bilanzzeile\x1b[0m');
        process.exitCode = 1;
    }
});
process.on('unhandledRejection', function (e) {
    console.log('\x1b[31mABBRUCH: unbehandelte Zurueckweisung: ' + e + '\x1b[0m');
    bilanz = true;                       // Bilanz kommt unten, aber mit FAIL
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL\x1b[0m');
    process.exit(1);
});
// Die geladene Seite haelt eigene Poll-Timer (LLM-Status alle 30 s). Ohne
// diesen Wachhund laeuft ein gescheiterter Lauf ins Zeitlimit des Aufrufers
// und ist von "nicht gelaufen" nicht zu unterscheiden.
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

const GRUPPEN = [
    { id: 'allgemein', name: 'community', color: '#22c55e', folders: ['data/community'] },
    { id: 'erlernt', name: 'Erlernt', color: '#8b5cf6', folders: [] },
];

// Datensaetze wie der Server sie liefert (Pfade aus dem echten DEV-Bestand).
function standardDateien() {
    return [
        { path: 'data/community/Vertrieb/Preisliste.xlsx', name: 'Preisliste.xlsx',
          folder: 'community/Vertrieb', groups: [GRUPPEN[0]] },
        { path: 'mnt/jarvis-kb/share_1/Preisliste.xlsx', name: 'Preisliste.xlsx',
          folder: 'share_1', groups: [GRUPPEN[0]] },
        { path: 'data/knowledge/learned/2026-09/conv_1758.md', name: 'conv_1758.md',
          folder: 'knowledge/learned/2026-09', groups: [GRUPPEN[1]] },
    ];
}

// Baut die Seite auf und laesst die ECHTE Kette laufen.
async function seite(dateien) {
    const dom = new JSDOM(HTML, {
        url: 'https://localhost/wissen',          // ohne url ist localStorage unbenutzbar
        runScripts: 'outside-only',
        pretendToBeVisual: false,
    });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    win.localStorage.setItem('jarvis_theme', 'dark');
    win.requestAnimationFrame = function (cb) { return setTimeout(cb, 0); };
    win.matchMedia = win.matchMedia || function () {
        return { matches: false, addListener: function () {}, removeListener: function () {},
                 addEventListener: function () {}, removeEventListener: function () {} };
    };

    const gerufen = [];
    const bestaetigt = [];
    function antwort(körper) {
        return Promise.resolve({
            ok: true, status: 200,
            json: function () { return Promise.resolve(körper); },
        });
    }
    // Routing ueber den PFAD, nie ueber die volle URL (Register: ein spaeter
    // ergaenztes ?lang= verfehlt sonst jede Route).
    const attrappe = function (url, opt) {
        const p = String(url).split('?')[0];
        gerufen.push({ pfad: p, opt: opt || {} });
        if (p === '/api/wissen/scope') {
            return antwort({ ok: true, user: 'anna', is_editor: false, is_admin: false,
                             groups: GRUPPEN, folders: [
                                 { path: 'data/community', name: 'community',
                                   root: 'data/community', depth: 0 }] });
        }
        if (p === '/api/wissen/files') return antwort({ ok: true, files: dateien });
        if (p === '/api/wissen/file') return antwort({ ok: true });
        return antwort({ ok: true, pending: [], spaces: [], status: 'ok' });
    };
    win.fetch = attrappe;
    global.fetch = attrappe;                       // Node hat ein eigenes globales fetch
    win.confirm = function (text) { bestaetigt.push(text); return false; };
    win.alert = function () {};

    win.eval(JS_ICONS);
    win.eval(JS_I18N);
    win.eval(JS_WISSEN);
    win.document.dispatchEvent(new win.Event('DOMContentLoaded', { bubbles: true }));
    // Auf die gerenderte Liste warten (zwei fetch-Runden: scope -> files).
    for (let i = 0; i < 60; i++) {
        await new Promise(function (r) { setTimeout(r, 5); });
        if (win.document.querySelectorAll('#wi-files-list .wi-item').length) break;
    }
    return { win, doc: win.document, gerufen, bestaetigt };
}

// Sichtbarer Text einer Zeile: was ein Mensch dort liest. Attribute (title)
// zaehlen ausdruecklich NICHT – ein Tooltip ist unsichtbar.
function sichtbar(el) {
    return (el.textContent || '').replace(/\s+/g, ' ').trim();
}
function versteckterVorfahr(el) {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
        if (n.hasAttribute && n.hasAttribute('hidden')) return n;
        const st = (n.getAttribute && n.getAttribute('style')) || '';
        if (/display\s*:\s*none/.test(st)) return n;
        if (n.classList && n.classList.contains('hidden')) return n;
    }
    return null;
}

(async function () {
    // ══ 1. Der Ordner steht sichtbar in der Zeile ═════════════════════════
    abschnitt('1 – Der Ordner ist SICHTBAR, nicht nur im title');

    const a = await seite(standardDateien());
    const zeilen = Array.prototype.slice.call(
        a.doc.querySelectorAll('#wi-files-list .wi-item'));
    check('drei Dateizeilen gezeichnet', zeilen.length === 3, 'gezeichnet: ' + zeilen.length);
    if (zeilen.length !== 3) abbruch('ohne gezeichnete Liste ist jede weitere Aussage trivial');

    const pfadEl = zeilen.map(function (r) { return r.querySelector('.wi-fpath'); });
    check('jede Zeile hat ein Ordner-Element', pfadEl.every(Boolean));
    check('der Ordner steht als TEXT in der Zeile (nicht nur als Attribut)',
          zeilen.every(function (r, i) {
              return sichtbar(r).indexOf(standardDateien()[i].folder) !== -1;
          }),
          zeilen.map(sichtbar).join(' | '));
    check('das Ordner-Element liegt in keinem versteckten Vorfahren',
          pfadEl.every(function (e) { return !versteckterVorfahr(e); }));
    check('der Dateiname bleibt der Link (.nm)',
          zeilen.every(function (r) {
              const nm = r.querySelector('a.nm');
              return nm && nm.textContent.indexOf('/') === -1;
          }));
    function attr(el, name) { return (el && el.getAttribute(name)) || ''; }
    check('der volle technische Pfad steht im title (Zusatz, nicht Ersatz)',
          attr(pfadEl[0], 'title')
              .indexOf('data/community/Vertrieb/Preisliste.xlsx') !== -1,
          attr(pfadEl[0], 'title'));

    // ══ 2. Der gemeldete Kern ═════════════════════════════════════════════
    abschnitt('2 – Gleichnamige Dateien sind unterscheidbar');

    const gleich = zeilen.filter(function (r) {
        return (r.querySelector('a.nm') || {}).textContent === 'Preisliste.xlsx';
    });
    check('zwei Zeilen tragen denselben Dateinamen', gleich.length === 2);
    check('ihr sichtbarer Text unterscheidet sich',
          gleich.length === 2 && sichtbar(gleich[0]) !== sichtbar(gleich[1]),
          gleich.map(sichtbar).join(' || '));

    // ══ 3. Rueckfall bei aelterem Backend ═════════════════════════════════
    abschnitt('3 – Ohne Feld "folder": roher Verzeichnispfad statt Leere');

    const b = await seite([
        { path: 'data/community/Vertrieb/Preisliste.xlsx', name: 'Preisliste.xlsx',
          groups: [GRUPPEN[0]] },
        { path: 'ganz-oben.md', name: 'ganz-oben.md', groups: [GRUPPEN[0]] },
    ]);
    const bz = Array.prototype.slice.call(
        b.doc.querySelectorAll('#wi-files-list .wi-item'));
    check('beide Zeilen gezeichnet', bz.length === 2, 'gezeichnet: ' + bz.length);
    check('der Verzeichnisteil des Pfads erscheint sichtbar',
          bz.length === 2 && sichtbar(bz[0]).indexOf('data/community/Vertrieb') !== -1,
          bz.length === 2 ? sichtbar(bz[0]) : '');
    check('eine Datei ohne Verzeichnis bekommt KEINE leere Ordnerzeile',
          bz.length === 2 && !bz[1].querySelector('.wi-fpath'));

    // ══ 4. Die Loesch-Rueckfrage ══════════════════════════════════════════
    abschnitt('4 – Die Rueckfrage nennt Ordner UND Namen');

    const del = gleich[0].querySelector('.wi-file-del');
    check('Loeschknopf vorhanden', !!del);
    if (del) {
        del.dispatchEvent(new a.win.Event('click', { bubbles: true }));
        await new Promise(function (r) { setTimeout(r, 5); });
    }
    check('genau eine Rueckfrage', a.bestaetigt.length === 1, a.bestaetigt.join(' | '));
    const frage = a.bestaetigt[0] || '';
    check('die Rueckfrage nennt den Dateinamen', frage.indexOf('Preisliste.xlsx') !== -1, frage);
    check('die Rueckfrage nennt den Ordner', frage.indexOf('community/Vertrieb') !== -1, frage);
    check('abgelehnte Rueckfrage loescht nichts',
          !a.gerufen.some(function (g) {
              return g.pfad === '/api/wissen/file' && (g.opt.method === 'DELETE');
          }));

    // ══ 5. Fremdtext bleibt Text ══════════════════════════════════════════
    abschnitt('5 – Der Ordnername wird maskiert');

    const c = await seite([
        { path: 'data/community/<img src=x onerror=alert(1)>/x.md', name: 'x.md',
          folder: 'community/<img src=x onerror=alert(1)>', groups: [GRUPPEN[0]] },
    ]);
    const cz = c.doc.querySelector('#wi-files-list .wi-item');
    check('Zeile gezeichnet', !!cz);
    check('kein <img> aus dem Ordnernamen im DOM',
          !!cz && cz.querySelectorAll('img').length === 0);
    check('der Text erscheint woertlich',
          !!cz && sichtbar(cz).indexOf('onerror=alert(1)') !== -1, cz ? sichtbar(cz) : '');

    // ══ 6+7. Die CSS-Zusagen ══════════════════════════════════════════════
    abschnitt('6 – .wi-fmeta: flex:1 UND min-width:0');

    // Gemessen an der WIRKUNG (getComputedStyle gegen das echte Inline-CSS der
    // Seite), nicht per Textsuche in der Datei.
    const fmeta = a.doc.querySelector('#wi-files-list .wi-fmeta');
    const stil = fmeta ? a.win.getComputedStyle(fmeta) : null;
    check('.wi-fmeta existiert in der gerenderten Zeile', !!fmeta);
    check('flex-grow ist 1 (der Textblock nimmt den Platz)',
          !!stil && parseFloat(stil.flexGrow) === 1, stil ? stil.flexGrow : '');
    check('min-width ist 0 (sonst fliegen Marken und Muelleimer aus der Zeile)',
          !!stil && (stil.minWidth === '0px' || stil.minWidth === '0'),
          stil ? stil.minWidth : '');
    const fp = pfadEl[0] ? a.win.getComputedStyle(pfadEl[0]) : null;
    check('der Ordner bricht um statt zu ueberlaufen',
          !!fp && fp.wordBreak === 'break-all', fp ? fp.wordBreak : 'kein Element');

    abschnitt('7 – Die Entwurfsliste bleibt unangetastet');
    // `.nm` ist dort ein direktes Flex-Kind von .wi-item und braucht flex:1.
    const entwurf = a.doc.createElement('div');
    entwurf.className = 'wi-item';
    const nm = a.doc.createElement('span');
    nm.className = 'nm';
    entwurf.appendChild(nm);
    a.doc.body.appendChild(entwurf);
    check('.wi-item > .nm behaelt flex-grow: 1',
          parseFloat(a.win.getComputedStyle(nm).flexGrow) === 1,
          a.win.getComputedStyle(nm).flexGrow);

    [a, b, c].forEach(function (s) { try { s.win.close(); } catch (e) {} });
    clearTimeout(WACHHUND);
    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
    process.exit(fail === 0 ? 0 : 1);
})();
