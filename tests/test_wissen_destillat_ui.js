/* Waechter: Wissens-Destillat unter /wissen (Import aus knowledge-distiller).
 *
 * Gemessen wird am ECHTEN DOM: die echte `wissen.html` mit dem echten
 * `wissen_destillat.js`, `icons.js` und `i18n.js` – ein UI-Test, der weniger
 * laedt als die Seite, prueft eine Kette, die es nicht gibt. Geklickt und
 * getippt wird wirklich; ob ein Container ERSCHEINT und wohin ein Klick
 * fuehrt, kann eine Quelltext-Suche nicht beantworten.
 *
 * Geprueft wird die EIGENSCHAFT, nicht ein Wortlaut:
 *   1. der Container liegt ZWISCHEN Informationsextraktor und Confluence –
 *      gemessen an der DOM-Reihenfolge, nicht an der Zeile im Markup
 *   2. Sichtbarkeit GENAU WIE DER EXTRAKTOR: ohne Wissensgruppe versteckt
 *   3. der Markdown-Renderer laesst KEIN fremdes Markup durch (der Text kommt
 *      vom Modell, das hochgeladene Fremddokumente verarbeitet hat)
 *   4. Bilder: Download bettet ein, die Wissensdatenbank bekommt den Hinweis
 *   5. der Destillieren-Knopf ist ohne Text GESPERRT MIT GRUND
 *   6. die Uebernahme sendet die gewaehlten Gruppen und weist eine leere
 *      Auswahl ab, BEVOR sie den Server fragt
 *   7. kein Lookbehind-LITERAL in der Datei (wuerde auf Safari < 16.4 schon
 *      beim Parsen werfen – dann waere der ganze Container tot)
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');

const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0;
let bilanz = false;

// ⚠ FRUEH REGISTRIEREN. Stuende das erst am Dateiende, gaebe es kein Fenster,
// in dem es mit bilanz===false laeuft – der Wachhund koennte nie feuern
// (Register: genau so gebaut und gemessen worden).
process.on('exit', function (code) {
    if (!bilanz) {
        console.log('\n\x1b[31mABGEBROCHEN – keine Bilanz\x1b[0m');
        if (code === 0) process.exitCode = 1;
    }
});

function abschnitt(t) { console.log('\n\x1b[1m' + t + '\x1b[0m'); }
function check(name, cond, detail) {
    if (typeof name !== 'string') {
        console.log('\x1b[31mABBRUCH: check() falsch herum aufgerufen\x1b[0m');
        process.exit(2);
    }
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen_destillat.js'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

/* Baut die echte Seite und fuehrt das echte Modul aus.
 * `gruppen`: Wissensgruppen des Scope (leer = kein Bereich).
 * `antworten`: Routen der fetch-Attrappe, ueber den PFAD (nicht die volle URL:
 * ein spaeter ergaenztes ?x= verfehlt sonst jede Route).            */
function seite(gruppen, antworten) {
    const dom = new JSDOM(HTML, { runScripts: 'outside-only', url: 'https://x/wissen' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'tok');
    const gesendet = [];
    w.fetch = function (url, opt) {
        const pfad = String(url).split('?')[0];
        gesendet.push({ pfad: pfad, voll: String(url), opt: opt || {} });
        const a = (antworten || {})[pfad];
        const d = typeof a === 'function' ? a(url, opt) : (a || { ok: true });
        // Eine ECHTE Response hat json() UND text() (Register: Attrappen bilden
        // die echte Antwortform nach). `__zeilen` = NDJSON-Strom wie ihn
        // /extract?stream=1 liefert; `__body` = selbst gesteuerter Strom.
        if (d && d.__antwort) return Promise.resolve(d.__antwort);
        const roh = d && d.__zeilen
            ? d.__zeilen.map(function (z) { return JSON.stringify(z); }).join('\n') + '\n'
            : JSON.stringify(d);
        return Promise.resolve({
            status: d.__status || 200,
            json: function () { return Promise.resolve(JSON.parse(roh)); },
            text: function () { return Promise.resolve(roh); }
        });
    };
    w.eval(ICONS);
    w.eval(I18N);
    w.eval(JS);
    w.WissenDestillat.init({
        scope: { groups: gruppen || [], folders: [], user: 'tester' },
        token: 'tok'
    });
    return { w: w, doc: w.document, gesendet: gesendet };
}

const GRUPPEN = [{ id: 'technik', name: 'Technik', color: '#4f6ef7' },
                 { id: 'vertrieb', name: 'Vertrieb', color: '#22c55e' }];

// ════════════════════════════════════════════════════════════════════════════
abschnitt('1. Der Container liegt ZWISCHEN Extraktor und Confluence');
{
    const { doc } = seite(GRUPPEN, {});
    const alle = Array.prototype.map.call(
        doc.querySelectorAll('.wi-section'), function (s) { return s.id; });
    const iUp = alle.indexOf('wi-sec-upload');
    const iDe = alle.indexOf('wi-sec-destillat');
    const iCf = alle.indexOf('wi-sec-cfbind');
    check('alle drei Container existieren',
          iUp >= 0 && iDe >= 0 && iCf >= 0, alle.join(', '));
    // ⚠ GEMESSEN AN DER DOM-REIHENFOLGE. Eine Suche nach der Zeilennummer im
    // Markup waere eine Aussage ueber die Datei, nicht ueber die Seite.
    check('Destillat steht NACH dem Informationsextraktor', iUp >= 0 && iDe > iUp,
          iUp + ' / ' + iDe);
    check('Destillat steht VOR der Confluence-Einbindung', iCf >= 0 && iDe < iCf,
          iDe + ' / ' + iCf);

    const sec = doc.getElementById('wi-sec-destillat');
    check('hat eine Kopfzeile mit Klapp-Pfeil (wie die Nachbarn)',
          !!(sec && sec.querySelector('h2 .wi-sec-tog')));
    check('die Kopfzeile ist uebersetzbar',
          !!(sec && sec.querySelector('h2 [data-i18n="wissen.sec_dest"]')));
}

// ════════════════════════════════════════════════════════════════════════════
abschnitt('2. Sichtbarkeit wie der Informationsextraktor');
{
    const mit = seite(GRUPPEN, {});
    const secMit = mit.doc.getElementById('wi-sec-destillat');
    check('MIT Wissensgruppe: sichtbar', !secMit.classList.contains('hidden'));

    const ohne = seite([], {});
    const secOhne = ohne.doc.getElementById('wi-sec-destillat');
    check('OHNE Wissensgruppe: versteckt', secOhne.classList.contains('hidden'));
    // Gegenprobe der Messung: der Extraktor verhaelt sich genauso. Ohne diese
    // Zeile koennte die Zusage "wie der Extraktor" auseinanderlaufen, ohne dass
    // es auffaellt.
    check('… und das Modul sendet dann NICHTS', ohne.gesendet.length === 0,
          JSON.stringify(ohne.gesendet.map(function (g) { return g.pfad; })));
}

// ════════════════════════════════════════════════════════════════════════════
abschnitt('3. Markdown-Renderer: Fremdtext kann kein Markup einschleusen');
{
    const { w } = seite(GRUPPEN, {});
    const md = w.WissenDestillat._md;

    const boese = md('<img src=x onerror=alert(1)> <script>alert(2)</script>');
    check('kein <img> aus dem Inhalt', boese.indexOf('<img') === -1, boese.slice(0, 60));
    check('kein <script> aus dem Inhalt', boese.toLowerCase().indexOf('<script') === -1);

    // Die Regeln selbst muessen aber arbeiten – sonst waere "sicher" trivial.
    check('Ueberschrift wird gerendert', md('# Titel').indexOf('<h1>Titel</h1>') >= 0);
    check('Fettschrift wird gerendert',
          md('ein **wichtiges** Wort').indexOf('<strong>wichtiges</strong>') >= 0);
    check('Liste wird gerendert', /<ul><li>a<\/li><li>b<\/li><\/ul>/.test(md('- a\n- b')));
    check('Codeblock bleibt Code',
          md('```\n**nicht fett**\n```').indexOf('<strong>') === -1);

    // ⚠ NUR http(s) und unsere data:-Bilder. Ein `javascript:`-Link liefe im
    // Origin von /wissen – dort liegt das Sitzungstoken im localStorage.
    check('javascript:-Link wird NICHT verlinkt',
          md('[klick](javascript:alert(1))').indexOf('<a ') === -1);
    check('http-Link wird verlinkt',
          md('[x](https://example.com)').indexOf('href="https://example.com"') >= 0);
    check('fremdes Bild-Schema wird verworfen (nur Alt-Text bleibt)',
          md('![alt](javascript:x)').indexOf('<img') === -1);
    check('unser data:-Bild wird gezeigt',
          md('![b](data:image/png;base64,AAAA)').indexOf('<img src="data:image/png') >= 0);

    // ⚠ Code-Review 2026-10-07: die Linkregel griff IN das alt-Attribut eines
    // schon erzeugten <img> und schloss es – daraus wurde ein eigenes onerror.
    // Gemessen am geparsten DOM, nicht am Text: KEIN Element traegt ein
    // on*-Attribut, und ein <img> traegt nur src und alt.
    const dom = function (html) { const d = w.document.createElement('div'); d.innerHTML = html; return d; };
    const ANGRIFFE = [
        '![[t](https://q)](https://a/onerror=alert.call``//)',
        '![[t](https://q) x](https://a/" onerror="alert(1))',
        '![a](https://x/"onload="alert(1))',
        '[![[i](https://q)](https://b/onerror=alert``)](https://c)',
        '![![x](https://q)](https://a/onerror=alert``)',
    ];
    for (const eingabe of ANGRIFFE) {
        const d = dom(md(eingabe));
        const handler = [];
        d.querySelectorAll('*').forEach(function (el) {
            for (const at of el.attributes) if (/^on/i.test(at.name)) handler.push(el.tagName + '[' + at.name + ']');
        });
        check('kein Ereignis-Attribut aus ' + JSON.stringify(eingabe.slice(0, 40)), handler.length === 0,
              handler.join(','));
        let fremd = [];
        d.querySelectorAll('img').forEach(function (el) {
            for (const at of el.attributes) if (at.name !== 'src' && at.name !== 'alt') fremd.push(at.name);
        });
        check('… und kein <img> mit fremden Attributen', fremd.length === 0, fremd.join(','));
    }
    // Positivkontrolle: Bild und Link nebeneinander werden BEIDE gerendert
    const beide = dom(md('![b](https://example.com/b.png) und [x](https://example.com)'));
    check('Bild UND Link nebeneinander werden gerendert',
          beide.querySelectorAll('img').length === 1 && beide.querySelectorAll('a').length === 1,
          beide.innerHTML.slice(0, 120));
    check('ein Bild allein bleibt ohne <p>-Huelle (wie vorher)',
          md('![b](https://example.com/b.png)').indexOf('<img') === 0);
}

// ════════════════════════════════════════════════════════════════════════════
abschnitt('4. Bild-Marker');
{
    const { w } = seite(GRUPPEN, {});
    check('_mitBildern ersetzt nur bekannte Marker',
          w.WissenDestillat._mitBildern('[BILD-1] [BILD-7]').indexOf('[BILD-7]') >= 0);
}

// ════════════════════════════════════════════════════════════════════════════
abschnitt('5. Destillieren-Knopf: gesperrt MIT Grund');
{
    const { w, doc, gesendet } = seite(GRUPPEN, {});
    const run = doc.getElementById('wi-dest-run');
    const ta = doc.getElementById('wi-dest-text');
    check('ohne Text gesperrt', run.disabled === true);
    check('… und der Grund steht im title', (run.title || '').length > 0, run.title);

    ta.value = 'Ein Text zum Destillieren';
    ta.dispatchEvent(new w.Event('input'));
    check('mit Text frei', run.disabled === false);
    check('… und ohne title (kein unerklaertes Zeichen)', !run.title);

    const vorher = gesendet.length;
    run.click();
    check('Klick loest genau EINEN Lauf aus',
          gesendet.length - vorher === 1,
          JSON.stringify(gesendet.map(function (g) { return g.pfad; })));
    check('… und zwar an den Destillat-Endpunkt',
          gesendet[gesendet.length - 1].pfad === '/api/wissen/destillat/lauf');
    // Vorgabe 2026-09-28: waehrend des Laufs derselbe Drehkreis wie beim
    // Upload und beim Lesen der Dateien – keine Sanduhr im Text.
    const st = doc.getElementById('wi-dest-status');
    check('waehrend des Laufs: Drehkreis in der Statuszeile',
          !!st.querySelector('.wi-dest-busy .wi-busy-spin'), st.innerHTML);
    check('… Text "Das Modell arbeitet" OHNE Sanduhr',
          /Das Modell arbeitet/.test(st.textContent) && st.textContent.indexOf('\u23f3') < 0,
          st.textContent);
}

// ════════════════════════════════════════════════════════════════════════════
abschnitt('6. Uebernahme in die Wissensdatenbank');
{
    const { w, doc, gesendet } = seite(GRUPPEN, {
        '/api/wissen/destillat/lauf': { ok: true, markdown: '# Destillat\n\nInhalt.', bloecke: 1 },
        '/api/wissen/destillat/uebernehmen': { ok: true, __status: 201, id: 'abc', title: 'Destillat' }
    });
    const ta = doc.getElementById('wi-dest-text');
    ta.value = 'Text';
    ta.dispatchEvent(new w.Event('input'));
    doc.getElementById('wi-dest-run').click();

    return new Promise(function (fertig) {
        setTimeout(function () {
            const out = doc.getElementById('wi-dest-out');
            check('nach dem Lauf ist das Ergebnis sichtbar', out.hidden === false);
            check('das Destillat ist gerendert',
                  doc.getElementById('wi-dest-md').innerHTML.indexOf('<h1>Destillat</h1>') >= 0);

            const box = doc.getElementById('wi-dest-takebox');
            check('die Gruppen-Auswahl ist zunaechst ZU', box.hidden === true);
            doc.getElementById('wi-dest-take').click();
            check('Klick auf "In die Wissensdatenbank" oeffnet sie', box.hidden === false);
            check('die Wissensgruppen sind gezeichnet',
                  doc.querySelectorAll('.wi-grp-dest').length === 2);

            // ⚠ LEERE AUSWAHL: abweisen, OHNE den Server zu fragen.
            const vor = gesendet.length;
            doc.getElementById('wi-dest-takego').click();
            check('ohne Gruppe wird NICHT gesendet', gesendet.length === vor);
            check('… und der Grund steht da',
                  (doc.getElementById('wi-dest-takestatus').textContent || '').length > 0);

            doc.querySelector('.wi-grp-dest').checked = true;

            // ⚠ DIE HAKEN MUESSEN EIN ERNEUTES OEFFNEN UEBERLEBEN. Wer die
            // Gruppen bei jedem Zeichnen neu baut, verwirft die Auswahl – der
            // Benutzer hakt an, klappt zu, klappt auf und sendet ins Leere.
            // Gemessen am DOM; im Quelltext waere das nicht zu sehen.
            doc.getElementById('wi-dest-takecancel').click();
            doc.getElementById('wi-dest-take').click();
            check('die gesetzten Haken ueberleben ein erneutes Oeffnen',
                  doc.querySelector('.wi-grp-dest').checked === true);

            doc.getElementById('wi-dest-takego').click();
            const tst = doc.getElementById('wi-dest-takestatus');
            check('Uebernahme laeuft: Drehkreis statt Sanduhr',
                  !!tst.querySelector('.wi-dest-busy .wi-busy-spin')
                  && tst.textContent.indexOf('\u23f3') < 0, tst.innerHTML);
            check('nach dem Lauf: kein Drehkreis mehr in der Destillat-Statuszeile',
                  !doc.querySelector('#wi-dest-status .wi-busy-spin'),
                  doc.getElementById('wi-dest-status').innerHTML);
            setTimeout(function () {
                const letzte = gesendet[gesendet.length - 1];
                check('nach der Uebernahme: kein Drehkreis mehr',
                      !tst.querySelector('.wi-busy-spin'), tst.innerHTML);
                check('mit Gruppe wird gesendet',
                      letzte.pfad === '/api/wissen/destillat/uebernehmen', letzte.pfad);
                const rumpf = JSON.parse(letzte.opt.body || '{}');
                check('der Rumpf traegt die gewaehlte Gruppe',
                      JSON.stringify(rumpf.groups) === '["technik"]',
                      JSON.stringify(rumpf.groups));
                check('der Rumpf traegt das Markdown',
                      (rumpf.markdown || '').indexOf('# Destillat') >= 0);
                // ⚠ KEIN Benutzername im Rumpf – der kommt aus der Anmeldung.
                check('KEIN Benutzername im Rumpf',
                      !('user' in rumpf) && !('username' in rumpf));
                fertig();
            }, 30);
        }, 30);
    }).then(weiter);
}

function weiter() {
// ════════════════════════════════════════════════════════════════════════════
abschnitt('7. Kein Lookbehind-LITERAL (sonst stirbt die Datei beim Parsen)');
{
    // ⚠ Ein `(?<=…)` im Regex-LITERAL wirft auf Safari < 16.4 schon beim
    // PARSEN – dann waere nicht die Fettschrift weg, sondern der GANZE
    // Container. Als String im try verschiebt es sich auf die Laufzeit.
    const ohneKommentar = JS.replace(/^\s*(\/\/|\*|\/\*).*$/gm, '');
    check('kein Lookbehind im Regex-Literal',
          !/\/[^\/\n]*\(\?<[=!]/.test(ohneKommentar));
    // ⚠ NICHT `new RegExp\([^)]*\(\?<=` – `[^)]*` kann die inneren Klammern
    // von `(?=\S)` nicht ueberspringen; die Pruefung meldete einen Fehler, den
    // es nicht gibt (Register: "ein Regex ueber den Aufruf scheiterte an
    // inneren Klammern"). Gemessen wird die EIGENSCHAFT ueber das Muster.
    const mDe = JS.match(/_FETT\s*=\s*new RegExp\('((?:[^'\\]|\\.)*)'/);
    check('… sondern ueber new RegExp im try',
          !!mDe && mDe[1].indexOf('(?<=') >= 0 && /catch\s*\([^)]*\)\s*\{[^}]*_FETT\s*=\s*null/.test(JS),
          mDe ? mDe[1] : 'kein new RegExp gefunden');

    // Positivkontrolle: das Muster ist ZEICHENGLEICH zur Fassung in avatar.js
    // (und im Jira-Plugin) – die `\S`-Waechter sind der Unterschied zwischen
    // brauchbar und gefaehrlich (ohne sie werden `2 * 3 * 4` und `*.txt`
    // ausgezeichnet). avatar.js kapselt es in eine IIFE, deshalb wird das
    // MUSTER verglichen und nicht die Schreibweise der Zuweisung.
    const AV = fs.readFileSync(path.join(ROOT, 'frontend/js/avatar.js'), 'utf8');
    const mAv = AV.match(/_FETT_RE[\s\S]{0,120}?new RegExp\('((?:[^'\\]|\\.)*)'/);
    check('Fett-Regel deckungsgleich mit avatar.js',
          !!(mAv && mDe) && mAv[1] === mDe[1],
          mAv && mDe ? (mAv[1] + '  vs  ' + mDe[1]) : 'nicht gefunden');
}

// ════════════════════════════════════════════════════════════════════════════
abschnitt('8. i18n: jeder benutzte Schluessel in BEIDEN Sprachen');
{
    const keys = new Set();
    let m;
    const reJs = /\bt\(['"](wissen\.[a-z_0-9]+)['"]/g;
    while ((m = reJs.exec(JS))) keys.add(m[1]);
    const reHtml = /data-i18n(?:-placeholder)?="(wissen\.dest[a-z_0-9]*|wissen\.sec_dest[a-z_0-9]*)"/g;
    while ((m = reHtml.exec(HTML))) keys.add(m[1]);

    check('es werden ueberhaupt Schluessel benutzt', keys.size > 20, String(keys.size));
    const fehlt = [];
    keys.forEach(function (k) {
        // Zweimal = DE und EN. Einmal = eine Sprachfassung fehlt.
        const n = (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "':", 'g')) || []).length;
        if (n < 2) fehlt.push(k + '(' + n + ')');
    });
    check('alle in DE und EN vorhanden', fehlt.length === 0, fehlt.join(', '));

    // Die Vorgabe-Auftraege gehen an das MODELL und muessen die Bild-Marker in
    // DERSELBEN Schreibweise nennen wie der Extraktor – sonst gehen sie
    // verloren.
    check('der Vorgabe-Auftrag nennt den Bild-Marker [BILD-N]',
          I18N.indexOf('[BILD-N]') >= 0);
}

// ════════════════════════════════════════════════════════════════════════════
abschnitt('9. Klapp-Registrierung und Einbindung');
{
    const WJS = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen.js'), 'utf8');
    check('wi-sec-destillat ist bei den Klapp-Containern registriert',
          WJS.indexOf("'wi-sec-destillat'") >= 0);
    check('wissen.js ruft WissenDestillat.init', WJS.indexOf('WissenDestillat.init') >= 0);
    check('… und uebergibt Scope UND Token',
          /WissenDestillat\.init\(\{\s*scope:\s*SCOPE,\s*token:\s*token\s*\}\)/.test(WJS));
    // ⚠ OHNE DEN SCRIPT-TAG WAERE DER CONTAINER STILL LEER: `wissen.js` prueft
    // `if (window.WissenDestillat)`, der Aufruf faellt dann wortlos aus. Genau
    // dieser Fall ist im Projekt schon einmal passiert (feedback_admin.js).
    check('wissen.html bindet wissen_destillat.js ein',
          /<script src="\/static\/js\/wissen_destillat\.js\?v=\d+">/.test(HTML));
    check('… VOR wissen.js (das ruft init beim Laden des Scope)',
          HTML.indexOf('wissen_destillat.js') < HTML.indexOf('js/wissen.js'));
    check('WissenPortal.reloadPending existiert (Entwurfsliste nachziehen)',
          WJS.indexOf('window.WissenPortal') >= 0 && WJS.indexOf('reloadPending') >= 0);
}

ordnerProbe().then(fortschrittProbe).then(filterProbe).then(abschluss, function (e) {
    check('Abschnitt 10/11 lief ohne Wurf', false, String(e && e.stack || e));
    abschluss();
});
}

// ════════════════════════════════════════════════════════════════════════════
// 10. Ordner als Quelle (Meldung 2026-09-27: "im aufpoppenden Fenster ist nur
// Dateiangabe moeglich"). Der Datei-Dialog eines Browsers kann ENTWEDER
// Dateien ODER einen Ordner waehlen – deshalb ein zweiter Eingang. Gemessen
// wird, was beim Server ANKOMMT (Namen im FormData), nicht das Markup.
function warte(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function datei(w, pfad) {
    const f = new w.File(['x'], pfad.split('/').pop());
    Object.defineProperty(f, 'webkitRelativePath', { value: pfad });
    return f;
}
function gesendeteNamen(gesendet) {
    const ex = gesendet.filter(function (g) { return g.pfad === '/api/wissen/destillat/extract'; });
    if (!ex.length) return null;
    const body = ex[ex.length - 1].opt.body;
    return body && body.getAll ? body.getAll('files').map(function (f) { return f.name; }) : null;
}
async function ordnerProbe() {
    // ⚠ HIER, nicht auf Dateiebene: Abschnitt 6 verlaesst die umschliessende
    // Funktion per `return` – ein `const` dahinter wird nie initialisiert
    // (nur Funktionsdeklarationen sind gehoben).
    const EXTRAKT = { '/api/wissen/destillat/extract': { __zeilen: [
        { art: 'datei', i: 1, n: 1, name: 'a' },
        { art: 'fertig', ok: ['a'], text: 'Inhalt', fehler: {},
          protokoll: [{ name: 'a', art: 'ok', zeichen: 6 }] }] } };
    abschnitt('10. Ordner als Quelle');
    {
        const { doc } = seite(GRUPPEN, EXTRAKT);
        const dirIn = doc.getElementById('wi-dest-dir');
        const btn = doc.getElementById('wi-dest-dirbtn');
        check('Ordner-Eingang existiert und ist ein Verzeichnis-Dialog',
              !!(dirIn && dirIn.type === 'file' && dirIn.hasAttribute('webkitdirectory')));
        check('Knopf "Ordner wählen" ist übersetzbar',
              !!(btn && btn.getAttribute('data-i18n') === 'wissen.dest_pick_dir'));
        if (!dirIn || !btn) return;

        // Der Knopf liegt IN der Drop-Zone, deren Klick den DATEI-Dialog oeffnet.
        let dirAuf = 0, dateiAuf = 0;
        dirIn.click = function () { dirAuf++; };
        doc.getElementById('wi-dest-files').click = function () { dateiAuf++; };
        btn.click();
        check('Knopf öffnet den Ordner-Dialog', dirAuf === 1, String(dirAuf));
        check('… und NICHT zusätzlich den Datei-Dialog', dateiAuf === 0, String(dateiAuf));
    }
    {
        const { w, doc, gesendet } = seite(GRUPPEN, EXTRAKT);
        const dirIn = doc.getElementById('wi-dest-dir');
        Object.defineProperty(dirIn, 'files', { configurable: true, value: [
            datei(w, 'Projekt/z.md'), datei(w, 'Projekt/.DS_Store'),
            datei(w, 'Projekt/Unter/a.pdf'), datei(w, 'Projekt/.git/config')
        ] });
        dirIn.dispatchEvent(new w.Event('change'));
        await warte(30);
        const namen = gesendeteNamen(gesendet);
        check('Ordnerwahl sendet die Dateien', !!namen, JSON.stringify(namen));
        check('… mit RELATIVEM Pfad als Name, sortiert',
              JSON.stringify(namen) === '["Projekt/Unter/a.pdf","Projekt/z.md"]', JSON.stringify(namen));
        const liste = doc.getElementById('wi-dest-filelist').textContent || '';
        check('die Dateiliste zeigt den Pfad sichtbar', liste.indexOf('Projekt/Unter/a.pdf') >= 0, liste);
        const st = doc.getElementById('wi-dest-exstatus').textContent || '';
        check('übersprungene versteckte Dateien werden GENANNT (2)',
              // window.t kennt keine Platzhalter – ersetzt wird wie im Modul.
              st.indexOf(w.t('wissen.dest_dir_skipped').replace('{n}', '2')) >= 0, st);
    }
    {
        const { w, doc, gesendet } = seite(GRUPPEN, EXTRAKT);
        const dirIn = doc.getElementById('wi-dest-dir');
        Object.defineProperty(dirIn, 'files', { configurable: true,
            value: [datei(w, 'Leer/.DS_Store')] });
        dirIn.dispatchEvent(new w.Event('change'));
        await warte(30);
        check('Ordner nur mit versteckten Dateien: KEINE Anfrage', gesendeteNamen(gesendet) === null);
        const st = doc.getElementById('wi-dest-exstatus').textContent || '';
        check('… und der Grund steht da', st.indexOf(w.t('wissen.dest_dir_empty')) >= 0, st);
    }
    {
        // Gezogener Ordner. readEntries() liefert BLOCKWEISE (Chrome: <= 100);
        // die Attrappe liefert zwei volle Bloecke, bevor sie leer meldet – wer
        // nur einmal liest, verliert den zweiten.
        const { w, doc, gesendet } = seite(GRUPPEN, EXTRAKT);
        function fe(pfad) {
            return { isFile: true, isDirectory: false, fullPath: '/' + pfad,
                     file: function (ok) { ok(new w.File(['x'], pfad.split('/').pop())); } };
        }
        function de(pfad, bloecke) {
            return { isFile: false, isDirectory: true, fullPath: '/' + pfad,
                     createReader: function () {
                         let i = 0;
                         return { readEntries: function (ok) { ok(bloecke[i++] || []); } };
                     } };
        }
        const wurzel = de('Doku', [
            [fe('Doku/a.md'), de('Doku/Sub', [[fe('Doku/Sub/c.docx')]])],
            [fe('Doku/b.md'), fe('Doku/.hidden')]
        ]);
        const ev = new w.Event('drop', { bubbles: true, cancelable: true });
        Object.defineProperty(ev, 'dataTransfer', { value: {
            files: [new w.File([''], 'Doku')],
            items: [{ kind: 'file', webkitGetAsEntry: function () { return wurzel; } }],
            types: ['Files']
        } });
        doc.getElementById('wi-dest-drop').dispatchEvent(ev);
        await warte(40);
        const namen = gesendeteNamen(gesendet);
        check('gezogener Ordner wird rekursiv gelesen – auch der zweite Block',
              JSON.stringify(namen) === '["Doku/Sub/c.docx","Doku/a.md","Doku/b.md"]', JSON.stringify(namen));
    }
    {
        // Rueckwaerts: gezogene DATEIEN gehen wie bisher direkt durch.
        const { w, doc, gesendet } = seite(GRUPPEN, EXTRAKT);
        const f = new w.File(['x'], 'einzeln.pdf');
        const ev = new w.Event('drop', { bubbles: true, cancelable: true });
        Object.defineProperty(ev, 'dataTransfer', { value: {
            files: [f],
            items: [{ kind: 'file', webkitGetAsEntry: function () {
                return { isFile: true, isDirectory: false, fullPath: '/einzeln.pdf' }; } }],
            types: ['Files']
        } });
        doc.getElementById('wi-dest-drop').dispatchEvent(ev);
        await warte(30);
        check('gezogene Einzeldatei geht unverändert durch',
              JSON.stringify(gesendeteNamen(gesendet)) === '["einzeln.pdf"]',
              JSON.stringify(gesendeteNamen(gesendet)));
    }
}

// ════════════════════════════════════════════════════════════════════════════
// 11. Lesefortschritt (Wunsch 2026-09-27: Drehkreis, Balken, "x von y",
// Protokoll welcher Datei was fehlte). Der Strom wird STUECKWEISE geliefert –
// eine Attrappe, die alles auf einmal liefert, kann einen Zwischenstand gar
// nicht zeigen, und genau der ist die Zusage.
function stromAttrappe(w) {
    const enc = new TextEncoder();
    const warten = [];           // offene read()-Zusagen
    const vorrat = [];           // gelieferte, noch nicht gelesene Stuecke
    let zu = false;
    function bedienen() {
        while (warten.length && (vorrat.length || zu)) {
            const r = warten.shift();
            if (vorrat.length) r({ done: false, value: vorrat.shift() });
            else r({ done: true, value: undefined });
        }
    }
    return {
        antwort: { status: 200,
            body: { getReader: function () { return { read: function () {
                return new Promise(function (r) { warten.push(r); bedienen(); });
            } }; } },
            json: function () { throw new Error('json() auf einem Strom'); },
            text: function () { throw new Error('text() auf einem Strom'); } },
        schick: function (txt) { vorrat.push(enc.encode(txt)); bedienen(); },
        ende: function () { zu = true; bedienen(); }
    };
}
function ablegen(w, doc, namen) {
    const inp = doc.getElementById('wi-dest-files');
    Object.defineProperty(inp, 'files', { configurable: true,
        value: namen.map(function (n) { return new w.File(['x'], n); }) });
    inp.dispatchEvent(new w.Event('change'));
}
function tr(w, key, vars) {
    // window.t kennt keine Platzhalter – ersetzt wird wie im Modul.
    let s = w.t(key);
    Object.keys(vars || {}).forEach(function (k) { s = s.split('{' + k + '}').join(vars[k]); });
    return s;
}
async function fortschrittProbe() {
    abschnitt('11. Lesefortschritt: Drehkreis, Balken, "x von y", Protokoll');
    let strom = null;
    const R = { '/api/wissen/destillat/extract': function () { return { __antwort: strom.antwort }; } };
    {
        const { w, doc, gesendet } = seite(GRUPPEN, R);
        w.TextDecoder = TextDecoder;
        strom = stromAttrappe(w);
        const busy = doc.getElementById('wi-dest-exbusy');
        const btxt = doc.getElementById('wi-dest-exbusy-text');
        const bar = doc.getElementById('wi-dest-exbar');
        const fill = doc.getElementById('wi-dest-exfill');
        const drop = doc.getElementById('wi-dest-drop');
        const lb = doc.getElementById('wi-dest-logbtn');
        const log = doc.getElementById('wi-dest-log');
        // Positivkontrolle: ohne diese Elemente ist jede Pruefung darunter leer.
        if (!busy || !btxt || !bar || !fill || !lb || !log) {
            console.log('\x1b[31mABBRUCH: Fortschritts-Elemente fehlen im Markup\x1b[0m');
            process.exit(2);
        }
        check('vor dem Lesen: Fortschrittszeile und Protokoll-Knopf verborgen',
              busy.hidden && bar.hidden && lb.hidden);

        ablegen(w, doc, ['a.pdf', 'b.one', 'c.docx']);
        await warte(10);
        const ex = gesendet.filter(function (g) { return g.pfad === '/api/wissen/destillat/extract'; });
        check('die Anfrage bittet um den Strom (?stream=1)',
              ex.length === 1 && /[?&]stream=1(&|$)/.test(ex[0].voll),
              JSON.stringify(ex.map(function (g) { return g.voll; })));
        check('während der Übertragung: Drehkreis sichtbar',
              !busy.hidden && !!busy.querySelector('.wi-busy-spin'));
        check('… Text nennt die Übertragung mit Dateizahl (noch kein "0 von 3")',
              btxt.textContent === tr(w, 'wissen.dest_uploading', { n: 3 }), btxt.textContent);
        check('… Balken sichtbar', !bar.hidden);
        check('… Ablage gesperrt', drop.classList.contains('disabled'));

        // Zeile ueber ZWEI Stuecke verteilt – der Leser muss sie zusammensetzen.
        const z1 = JSON.stringify({ art: 'datei', i: 1, n: 3, name: 'a.pdf' }) + '\n';
        strom.schick(z1.slice(0, 11)); await warte(5);
        check('halbe Zeile: noch keine Datei-Anzeige',
              btxt.textContent === tr(w, 'wissen.dest_uploading', { n: 3 }), btxt.textContent);
        strom.schick(z1.slice(11)); await warte(5);
        check('ganze Zeile: "Lese Datei 1 von 3: a.pdf"',
              btxt.textContent === tr(w, 'wissen.dest_reading_n', { i: 1, n: 3, name: 'a.pdf' }), btxt.textContent);
        strom.schick(JSON.stringify({ art: 'datei', i: 2, n: 3, name: 'b.one' }) + '\n');
        await warte(5);
        check('"x von y" läuft mit: 2 von 3',
              btxt.textContent === tr(w, 'wissen.dest_reading_n', { i: 2, n: 3, name: 'b.one' }), btxt.textContent);
        // (i-1)/n: waehrend Datei 2 laeuft, ist EINE von drei fertig.
        check('Balken misst fertige Dateien: 33 % bei Datei 2 von 3',
              Math.abs(parseFloat(fill.style.width) - 100 / 3) < 0.5, fill.style.width);

        // Ein zweites Ablegen WAEHREND des Lesens schickt nichts.
        ablegen(w, doc, ['d.txt']);
        await warte(5);
        check('zweites Ablegen während des Lesens: KEINE zweite Anfrage',
              gesendet.filter(function (g) { return g.pfad === '/api/wissen/destillat/extract'; }).length === 1);
        check('… und der Grund steht da',
              (doc.getElementById('wi-dest-exstatus').textContent || '').indexOf(w.t('wissen.dest_busy_wait')) >= 0);

        strom.schick(JSON.stringify({ art: 'datei', i: 3, n: 3, name: 'c.docx' }) + '\n'
            + JSON.stringify({ art: 'fertig', ok: ['a.pdf', 'c.docx'], text: '--- a.pdf ---\nA',
                fehler: { 'b.one': 'OneNote braucht den Tika-Dienst.' }, gekappt: false,
                protokoll: [{ name: 'a.pdf', art: 'ok', zeichen: 1234 },
                            { name: 'b.one', art: 'fehler', grund: 'OneNote braucht den Tika-Dienst.' },
                            { name: 'c.docx', art: 'ok', zeichen: 50, bilder: 2 }] }) + '\n');
        strom.ende();
        await warte(10);
        check('nach dem Ende: Drehkreis weg', busy.hidden);
        check('… Balken auf 100 %', parseFloat(fill.style.width) === 100, fill.style.width);
        check('… Ablage wieder frei', !drop.classList.contains('disabled'));
        const st = doc.getElementById('wi-dest-exstatus').textContent || '';
        check('Status: "2 gelesen · 1 nicht lesbar"',
              st.indexOf(tr(w, 'wissen.dest_extracted', { n: 2 })) >= 0
              && st.indexOf(tr(w, 'wissen.dest_failed_n', { n: 1 })) >= 0, st);
        check('Protokoll-Knopf erscheint, Protokoll noch zu', !lb.hidden && log.hidden);
        check('… Knopf übersetzbar (data-i18n)', lb.getAttribute('data-i18n') === 'wissen.dest_log_show');

        lb.click();
        const zeilen = log.querySelectorAll('.wi-dest-logzeile');
        check('Klick öffnet das Protokoll mit JEDER Datei', !log.hidden && zeilen.length === 3,
              String(zeilen.length));
        const fz = log.querySelector('.wi-dest-logzeile.fehler');
        check('… die fehlerhafte Datei steht MIT Grund',
              !!fz && fz.textContent.indexOf('b.one') >= 0
              && fz.textContent.indexOf('OneNote braucht den Tika-Dienst.') >= 0, fz && fz.textContent);
        check('… erfolgreiche Dateien als Erfolg markiert',
              log.querySelectorAll('.wi-dest-logzeile.ok').length === 2);
        check('… mit Zeichen- und Bildzahl',
              log.textContent.indexOf(tr(w, 'wissen.dest_log_images', { n: 2 })) >= 0
              && log.textContent.indexOf(tr(w, 'wissen.dest_chars', { n: (1234).toLocaleString() })) >= 0,
              log.textContent);
        check('… Knopf heißt jetzt "ausblenden" (auch für den Sprachwechsel)',
              lb.getAttribute('data-i18n') === 'wissen.dest_log_hide'
              && lb.textContent === w.t('wissen.dest_log_hide')
              && lb.getAttribute('aria-expanded') === 'true');
        lb.click();
        check('zweiter Klick schließt es wieder', log.hidden
              && lb.getAttribute('data-i18n') === 'wissen.dest_log_show');
        check('der Text der gelesenen Datei steht im Textfeld',
              doc.getElementById('wi-dest-text').value.indexOf('--- a.pdf ---') >= 0);
        check('die Zeile der nicht lesbaren Datei ist markiert',
              (doc.getElementById('wi-dest-filelist').textContent || '').indexOf(w.t('wissen.dest_unreadable')) >= 0);

        // Protokoll-Inhalt kommt vom Server (Dateinamen des Benutzers) – kein Markup.
        const { w: w2, doc: d2 } = seite(GRUPPEN, { '/api/wissen/destillat/extract': { __zeilen: [
            { art: 'fertig', ok: [], text: '', fehler: { '<img src=x onerror=alert(1)>': 'x' },
              protokoll: [{ name: '<img src=x onerror=alert(1)>', art: 'fehler', grund: '<b>g</b>' }] }] } });
        ablegen(w2, d2, ['q.txt']);
        await warte(15);
        d2.getElementById('wi-dest-logbtn').click();
        check('Protokoll maskiert Namen und Grund (kein fremdes Markup)',
              !d2.getElementById('wi-dest-log').querySelector('img, b'));
    }
    {
        // Abgerissener Strom: Zeilen kamen, "fertig" nie. Das darf NICHT wie ein
        // Erfolg mit 0 Dateien aussehen.
        const { w, doc } = seite(GRUPPEN, R);
        w.TextDecoder = TextDecoder;
        strom = stromAttrappe(w);
        ablegen(w, doc, ['a.pdf', 'b.pdf']);
        await warte(5);
        strom.schick(JSON.stringify({ art: 'datei', i: 1, n: 2, name: 'a.pdf' }) + '\n');
        strom.ende();
        await warte(10);
        const st = doc.getElementById('wi-dest-exstatus');
        check('abgerissener Strom: Fehlermeldung statt Erfolg',
              st.textContent.indexOf(w.t('wissen.dest_stream_broken')) >= 0
              && !!st.querySelector('.wi-err'), st.textContent);
        check('… Drehkreis und Balken weg', doc.getElementById('wi-dest-exbusy').hidden
              && doc.getElementById('wi-dest-exbar').hidden);
        check('… kein Protokoll-Knopf (es gibt kein Protokoll)', doc.getElementById('wi-dest-logbtn').hidden);
    }
    {
        // Fehler-Zeile des Servers (z. B. zu viele Dateien) und Antwort VOR dem
        // Strom (403 als gewoehnliches JSON) – beide zeigen den Servertext.
        const a = seite(GRUPPEN, { '/api/wissen/destillat/extract': { __zeilen: [
            { art: 'fehler', error: 'Zu viele Dateien (300).' }] } });
        ablegen(a.w, a.doc, ['a.txt']);
        await warte(10);
        check('Fehler-Zeile: Servertext steht da',
              a.doc.getElementById('wi-dest-exstatus').textContent.indexOf('Zu viele Dateien (300).') >= 0);
        const b = seite(GRUPPEN, { '/api/wissen/destillat/extract': {
            __status: 403, error: 'Dir ist kein Wissensbereich zugewiesen.' } });
        ablegen(b.w, b.doc, ['a.txt']);
        await warte(10);
        check('403 vor dem Strom: Servertext steht da',
              b.doc.getElementById('wi-dest-exstatus').textContent.indexOf('kein Wissensbereich') >= 0);
        check('… und die Ablage ist wieder frei',
              !b.doc.getElementById('wi-dest-drop').classList.contains('disabled'));
    }
    {
        // i18n: jeder neue Schluessel in DE UND EN.
        const neu = ['dest_uploading', 'dest_reading_n', 'dest_busy_wait', 'dest_stream_broken',
                     'dest_skipped_n', 'dest_log_show', 'dest_log_hide', 'dest_log_images',
                     'dest_log_skipped'];
        const fehlt = neu.filter(function (k) {
            const n = I18N.split("'wissen." + k + "':").length - 1;
            return n !== 2;
        });
        check('neue Texte stehen in DE und EN', fehlt.length === 0, fehlt.join(', '));
        check('kein Sanduhr-Emoji mehr in "Lese Dateien" (der Drehkreis ersetzt es)',
              !/'wissen\.dest_extracting':\s*'⏳/.test(I18N));
        check('kein Sanduhr-Emoji mehr in "Das Modell arbeitet" / "Lege Entwurf an" (DE+EN)',
              !/'wissen\.dest_(running|taking)':\s*'⏳/.test(I18N));
        check('… und die Laufanzeige hat eine CSS-Regel auf der Seite',
              /\.wi-dest-busy\s*\{/.test(fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8')));
    }
}

// ════════════════════════════════════════════════════════════════════════════
// 12. Dateifilter (Black-/Whitelist, Vorgabe 2026-09-27). Angewandt wird er im
// BROWSER vor dem Hochladen – gemessen wird deshalb, was im FormData landet.
async function filterProbe() {
    abschnitt('12. Dateifilter: Whitelist / Blacklist');
    const EXTRAKT = function () {
        return { __zeilen: [{ art: 'fertig', ok: ['P/a.pdf'], text: 'Inhalt', fehler: {},
                              protokoll: [{ name: 'P/a.pdf', art: 'ok', zeichen: 7 }] }] };
    };
    function feld(doc, id, wert) {
        const el = doc.getElementById(id);
        el.value = wert;
        el.dispatchEvent(new el.ownerDocument.defaultView.Event('input'));
        return el;
    }
    function ordner(w, doc, pfade) {
        const dirIn = doc.getElementById('wi-dest-dir');
        Object.defineProperty(dirIn, 'files', { configurable: true,
            value: pfade.map(function (p) { return datei(w, p); }) });
        dirIn.dispatchEvent(new w.Event('change'));
    }
    {
        const { doc } = seite(GRUPPEN, {});
        const box = doc.getElementById('wi-dest-filterbox');
        const drop = doc.getElementById('wi-dest-drop');
        check('(Positivkontrolle) Filterkasten und Ablage sind da', !!box && !!drop);
        check('der Filter liegt IM Destillat', !!box && !!box.closest('#wi-sec-destillat'));
        check('⚠ und VOR der Ablage (er greift beim Ziehen)',
              !!box && !!drop && !!(box.compareDocumentPosition(drop) & 4));
        check('er ist eingeklappt (im Regelfall braucht man ihn nicht)', !!box && !box.open);
        ['wi-dest-weiss', 'wi-dest-schwarz'].forEach(function (id) {
            const lab = doc.querySelector('label[for="' + id + '"]');
            const ta = doc.getElementById(id);
            check(id + ': Beschriftung mit i18n', !!lab && /^wissen\.dest_(white|black)$/.test(lab.getAttribute('data-i18n') || ''));
            check(id + ': Platzhalter mit i18n', !!ta && /_ph$/.test(ta.getAttribute('data-i18n-placeholder') || ''));
        });
        check('die Überschrift ist übersetzbar',
              !!doc.querySelector('#wi-dest-filterbox summary [data-i18n="wissen.dest_filter"]'));
    }
    {
        // Gespeicherter Filter wird geladen – und die Zahl steht AUCH ZUGEKLAPPT da.
        const { w, doc, gesendet } = seite(GRUPPEN, { '/api/wissen/destillat/filter':
            { ok: true, weiss: ['*.pdf'], schwarz: ['*entwurf*', 'archiv/'] } });
        await warte(20);
        check('der gespeicherte Filter wird geholt',
              gesendet.some(function (g) { return g.pfad === '/api/wissen/destillat/filter'
                  && !(g.opt.method && g.opt.method !== 'GET'); }));
        check('⚠ Whitelist aus der Ablage eingetragen', doc.getElementById('wi-dest-weiss').value === '*.pdf');
        check('⚠ Blacklist aus der Ablage eingetragen (eine Zeile je Muster)',
              doc.getElementById('wi-dest-schwarz').value === '*entwurf*\narchiv/',
              JSON.stringify(doc.getElementById('wi-dest-schwarz').value));
        check('die Zahl der aktiven Muster steht im Titel',
              doc.getElementById('wi-dest-filterzahl').textContent === tr(w, 'wissen.dest_filter_active', { n: 3 }),
              doc.getElementById('wi-dest-filterzahl').textContent);

        const W = w.WissenDestillat;
        check('*.pdf trifft den Dateinamen', W._filterGrund('a.PDF') === '');
        check('⚠ Blacklist gewinnt gegen Whitelist', W._filterGrund('Entwurf_1.pdf')
              === tr(w, 'wissen.dest_filter_black', { m: '*entwurf*' }), W._filterGrund('Entwurf_1.pdf'));
        check('⚠ "archiv/" meint den Ordner – in jeder Tiefe',
              W._filterGrund('proj/archiv/x.pdf') !== '' && W._filterGrund('archivx/x.pdf') === '');
        check('nicht in der Whitelist -> ausgelassen, mit Grund',
              W._filterGrund('notiz.txt') === tr(w, 'wissen.dest_filter_notwhite'));
        check('Windows-Trenner zählen als Ordnergrenze', W._filterGrund('proj\\archiv\\x.pdf') !== '');
        check('? steht für genau ein Zeichen',
              W._musterTrifft('a?.pdf', 'ab.pdf') && !W._musterTrifft('a?.pdf', 'abc.pdf'));
        check('Regex-Zeichen im Muster sind wörtlich',
              W._musterTrifft('(1).pdf', 'x/(1).pdf') && !W._musterTrifft('a.b', 'axb'));
        check('das Muster muss den GANZEN Namen treffen (kein Teilstring)',
              !W._musterTrifft('pdf', 'a.pdf') && W._musterTrifft('*pdf', 'a.pdf'));

        ordner(w, doc, ['P/a.pdf', 'P/Entwurf_x.pdf', 'P/b.txt', 'P/archiv/c.pdf']);
        await warte(30);
        const namen = gesendeteNamen(gesendet);
        check('⚠ nur die erlaubte Datei wird ÜBERTRAGEN', JSON.stringify(namen) === '["P/a.pdf"]',
              JSON.stringify(namen));
    }
    {
        const { w, doc, gesendet } = seite(GRUPPEN, { '/api/wissen/destillat/extract': EXTRAKT });
        feld(doc, 'wi-dest-weiss', '*.pdf');
        feld(doc, 'wi-dest-schwarz', '*entwurf*');
        ordner(w, doc, ['P/a.pdf', 'P/Entwurf_x.pdf', 'P/b.txt']);
        await warte(30);
        check('(Positivkontrolle) die Extraktion lief', JSON.stringify(gesendeteNamen(gesendet)) === '["P/a.pdf"]');
        const st = doc.getElementById('wi-dest-exstatus').textContent || '';
        check('⚠ die Statuszeile nennt die ausgelassenen Dateien (2)',
              st.indexOf(tr(w, 'wissen.dest_filtered_n', { n: 2 })) >= 0, st);
        check('nur-Filter ist kein Fehler (Status grün)',
              !!doc.querySelector('#wi-dest-exstatus .wi-ok'), doc.getElementById('wi-dest-exstatus').innerHTML);
        check('das Protokoll ist verfügbar', !doc.getElementById('wi-dest-logbtn').hidden);
        doc.getElementById('wi-dest-logbtn').click();
        const zeilen = Array.prototype.map.call(doc.querySelectorAll('#wi-dest-log .wi-dest-logzeile'),
            function (z) { return { k: z.className, t: z.textContent }; });
        check('⚠ das Protokoll nennt JEDE Datei – auch die ausgelassenen', zeilen.length === 3, JSON.stringify(zeilen));
        const e = zeilen.filter(function (z) { return z.t.indexOf('P/Entwurf_x.pdf') >= 0; })[0];
        check('… mit Grund (welches Muster)', !!e && /gefiltert/.test(e.k)
              && e.t.indexOf(tr(w, 'wissen.dest_filter_black', { m: '*entwurf*' })) >= 0, JSON.stringify(e));
        const b = zeilen.filter(function (z) { return z.t.indexOf('P/b.txt') >= 0; })[0];
        check('… und für die Whitelist', !!b && b.t.indexOf(tr(w, 'wissen.dest_filter_notwhite')) >= 0, JSON.stringify(b));
        const liste = doc.getElementById('wi-dest-filelist').textContent || '';
        check('ausgelassene Dateien stehen NICHT in der Dateiliste (sie wurden nicht übertragen)',
              liste.indexOf('P/b.txt') < 0 && liste.indexOf('P/a.pdf') >= 0, liste);
    }
    {
        const { w, doc, gesendet } = seite(GRUPPEN, { '/api/wissen/destillat/extract': EXTRAKT });
        feld(doc, 'wi-dest-schwarz', '*');
        ablegen(w, doc, ['a.pdf', 'b.docx']);
        await warte(30);
        check('⚠ alles ausgelassen: KEINE Übertragung', gesendeteNamen(gesendet) === null);
        const st = doc.getElementById('wi-dest-exstatus').textContent || '';
        check('… und das wird gesagt (kein stummes Nichts)',
              st.indexOf(tr(w, 'wissen.dest_filtered_all', { n: 2 })) >= 0, st);
        check('… samt Protokoll', !doc.getElementById('wi-dest-logbtn').hidden
              && doc.querySelectorAll('#wi-dest-log .wi-dest-logzeile').length === 2);
        check('… und die Ablage ist nicht gesperrt', !doc.getElementById('wi-dest-drop').classList.contains('disabled'));
    }
    {
        // Leerer Filter: alles wie bisher.
        const { w, doc, gesendet } = seite(GRUPPEN, { '/api/wissen/destillat/extract': EXTRAKT });
        ablegen(w, doc, ['a.pdf', 'b.txt']);
        await warte(30);
        check('⚠ ohne Muster geht jede Datei durch', JSON.stringify(gesendeteNamen(gesendet)) === '["a.pdf","b.txt"]',
              JSON.stringify(gesendeteNamen(gesendet)));
        check('ohne Muster keine Zahl im Titel', doc.getElementById('wi-dest-filterzahl').textContent === '');
    }
    {
        // Speichern beim Verlassen des Feldes – mit den GEPRUEFTEN Zeilen.
        let put = null;
        const { w, doc } = seite(GRUPPEN, { '/api/wissen/destillat/filter': function (url, opt) {
            if (opt && opt.method === 'PUT') { put = JSON.parse(opt.body); return { ok: true, weiss: put.weiss, schwarz: put.schwarz }; }
            return { ok: true, weiss: ['*.alt'], schwarz: [] };
        } });
        // ⚠ Getippt wird, BEVOR der Ladeabruf zurueck ist: die Eingabe gewinnt.
        const ta = feld(doc, 'wi-dest-weiss', ' *.pdf \n\n*.docx');
        await warte(20);
        check('⚠ eine schon begonnene Eingabe wird vom Laden NICHT überschrieben',
              ta.value === ' *.pdf \n\n*.docx', JSON.stringify(ta.value));
        check('die Zahl folgt der Eingabe', doc.getElementById('wi-dest-filterzahl').textContent
              === tr(w, 'wissen.dest_filter_active', { n: 2 }));
        check('(Positivkontrolle) ohne change noch kein Speichern', put === null);
        ta.dispatchEvent(new w.Event('change'));
        await warte(20);
        check('⚠ change speichert – Zeilen getrimmt, Leerzeilen weg',
              !!put && JSON.stringify(put) === '{"weiss":["*.pdf","*.docx"],"schwarz":[]}', JSON.stringify(put));
        check('… und bestätigt es', (doc.getElementById('wi-dest-filterstatus').textContent || '')
              .indexOf(w.t('wissen.dest_filter_saved')) >= 0);
    }
    {
        const { w, doc } = seite(GRUPPEN, { '/api/wissen/destillat/filter': function (url, opt) {
            if (opt && opt.method === 'PUT') return { __status: 400, ok: false, error: 'Höchstens 100 Muster je Liste.' };
            return { ok: true, weiss: [], schwarz: [] };
        } });
        const ta = feld(doc, 'wi-dest-schwarz', '*.tmp');
        ta.dispatchEvent(new w.Event('change'));
        await warte(3000);
        const st = doc.getElementById('wi-dest-filterstatus');
        check('⚠ ein Speicherfehler steht da – mit dem Servertext – und verschwindet NICHT von selbst',
              st.textContent.indexOf('Höchstens 100 Muster') >= 0 && !!st.querySelector('.wi-err'), st.textContent);
        check('⚠ der Filter WIRKT trotzdem (es gilt, was im Feld steht)',
              w.WissenDestillat._filterGrund('x.tmp') !== '');
    }
    {
        const { w, doc } = seite(GRUPPEN, {});
        w.setLang ? w.setLang('en') : (w.applyLang && w.applyLang('en'));
        await warte(20);
        check('Sprachwechsel erreicht den Filterkasten',
              /Filter files/.test(doc.querySelector('#wi-dest-filterbox summary').textContent)
              && /Whitelist – process only/.test(doc.querySelector('label[for="wi-dest-weiss"]').textContent));
        const neu = ['dest_filter', 'dest_filter_active', 'dest_filter_hint', 'dest_white', 'dest_white_ph',
                     'dest_black', 'dest_black_ph', 'dest_filter_saved', 'dest_filter_save_err',
                     'dest_filter_black', 'dest_filter_notwhite', 'dest_filtered_n', 'dest_filtered_all'];
        const fehlt = neu.filter(function (k) { return I18N.split("'wissen." + k + "':").length - 1 !== 2; });
        check('jeder neue Filter-Text steht in DE und EN', fehlt.length === 0, fehlt.join(', '));
        const mm = HTML.match(/data-i18n="wissen\.dest_filter_hint">([^<]*)</);
        const mt = I18N.match(/'wissen\.dest_filter_hint':\s*'([^']*)'/);
        check('Rückfall-Markup des Hinweises = DE', !!mm && !!mt && mm[1] === mt[1]);
    }
}

function abschluss() {
    console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
    bilanz = true;
    process.exit(fail ? 1 : 0);
}
