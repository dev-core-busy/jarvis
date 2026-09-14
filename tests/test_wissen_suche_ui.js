/* Waechter: die Dateiliste in /wissen ("Mein Wissen") hat eine SUCHE.
 *
 * Gemeldet 2026-09-14: "unter der Kachel /portal -> Wissen fehlt eine Suche
 * wie unter Massenzuordnung". Zutreffend: es gab dort nur den Wissensgruppen-
 * Filter (Kaestchen), kein Textfeld – bei vielen Dateien war eine bestimmte
 * nur durch Scrollen zu finden.
 *
 * Gemessen wird am ECHTEN DOM: die echte `wissen.html` mit der echten
 * `wissen.js` (plus `icons.js` und `i18n.js` – ein UI-Test, der weniger laedt
 * als die Seite, prueft eine Kette, die es nicht gibt). Getippt wird ueber das
 * echte `input`-Ereignis, die Liste entsteht ueber den ECHTEN Renderer. Ein
 * Quelltext-Schnitt koennte "wird die Zeile ausgeblendet?" gar nicht
 * beantworten.
 *
 * Geprueft wird die EIGENSCHAFT, nicht ein Wortlaut:
 *   1. das Feld ist da und SICHTBAR (kein versteckter Vorfahr)
 *   2. Name, Ordner und Gruppenname filtern sofort, ohne Serveraufruf
 *   3. der Dateiinhalt wird zusaetzlich (verzoegert) ueber den Server gesucht
 *   4. ⚠ DIE PFADFORMEN DER BEIDEN ENDPUNKTE SIND NICHT GLEICH (gemessen):
 *      /api/wissen/files liefert `mnt/rag/share_1/x.pdf`, content_search
 *      `/mnt/rag/share_1/x.pdf`. Ohne Angleichung traefe die Inhaltssuche bei
 *      JEDER Datei aus einer Netzwerk-Freigabe daneben – im Betrieb die
 *      meisten. Das ist der Kern dieses Waechters.
 *   5. eine veraltete Antwort (weitergetippt) darf nicht zaehlen
 *   6. Zaehler und Leermeldung nennen den WIRKLICHEN Grund – "keine Dateien in
 *      den gewaehlten Wissensgruppen" waere bei erfolgloser Suche eine
 *      Falschaussage
 *   7. Suche und Gruppenfilter wirken UND-verknuepft
 *   8. die Suchzeile liegt NICHT in der Gruppen-Filterzeile (die wird ohne
 *      Wissensgruppen ausgeblendet – die Suche waere dann unerreichbar)
 */
'use strict';
const fs = require('fs');
const path = require('path');

// jsdom liegt je Maschine anders. Fehlt es: EXIT 2, nicht 0 – "konnte nicht
// laufen" darf nie wie "bestanden" aussehen.
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
    console.log('\x1b[31m✗ Wachhund: der Lauf haengt (>40 s)\x1b[0m');
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + (fail + 1) + ' FAIL\x1b[0m');
    process.exit(1);
}, 40000);
WACHHUND.unref && WACHHUND.unref();

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/wissen.html'), 'utf8');
const JS_WISSEN = fs.readFileSync(path.join(ROOT, 'frontend/js/wissen.js'), 'utf8');
const JS_ICONS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');
const JS_I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

const GRUPPEN = [
    { id: 'allgemein', name: 'community', color: '#22c55e', folders: ['data/rag/community'] },
    { id: 'technik', name: 'Handbuecher', color: '#8b5cf6', folders: [] },
];

// Datensaetze in den ECHTEN Pfadformen des Servers: relativ fuer Dateien unter
// PROJECT_ROOT, OHNE fuehrenden Schraegstrich fuer Netz-Freigaben (so
// normalisiert knowledge_groups._rel – gemessen, nicht angenommen).
function dateien() {
    return [
        { path: 'data/rag/community/Vertrieb/Preisliste.xlsx', name: 'Preisliste.xlsx',
          folder: 'community/Vertrieb', groups: [GRUPPEN[0]] },
        { path: 'mnt/rag/share_1/OneNote/Anleitung SAP.one', name: 'Anleitung SAP.one',
          folder: 'share_1/OneNote', groups: [GRUPPEN[1]] },
        { path: 'data/rag/community/Notizen/urlaub.md', name: 'urlaub.md',
          folder: 'community/Notizen', groups: [GRUPPEN[0]] },
    ];
}

// Baut die Seite auf und laesst die ECHTE Kette laufen.
// `inhalt` beantwortet /api/knowledge/content_search: (q) -> [pfade]
// `cfg.verzug`     – Antwortzeit des Servers in ms. OHNE diesen Schalter laesst
//                    sich ein Wettlauf gar nicht herstellen: das Entprellen
//                    loescht eine Anfrage, zu der noch keine Antwort unterwegs
//                    war (eine Attrappe, die die Eigenschaft nicht erzeugen
//                    kann, macht den Waechter gruen – Register).
// `cfg.scopeGruppen` – Wissensgruppen im Lese-Scope; [] versteckt die
//                    Gruppen-Filterzeile, dann muss die Suche trotzdem da sein.
async function seite(liste, inhalt, cfg) {
    cfg = cfg || {};
    const dom = new JSDOM(HTML, {
        url: 'https://localhost/wissen',
        runScripts: 'outside-only',
        pretendToBeVisual: false,
    });
    const win = dom.window;
    win.localStorage.setItem('jarvis_token', 'test-token');
    win.localStorage.setItem('jarvis_theme', 'dark');
    // Vorgabe: alle Gruppen sichtbar (der Filter merkt die ABGEWAEHLTEN)
    win.document.cookie = 'jarvis_wissen_gfilter_off=;path=/';
    win.requestAnimationFrame = function (cb) { return setTimeout(cb, 0); };
    win.matchMedia = win.matchMedia || function () {
        return { matches: false, addListener: function () {}, removeListener: function () {},
                 addEventListener: function () {}, removeEventListener: function () {} };
    };

    const gerufen = [];
    // ⚠ Der fetch-Parameter heisst absichtlich NICHT `opt`: er wuerde die
    // Optionen dieser Funktion ueberschatten, und `cfg.verzug` /
    // `cfg.scopeGruppen` waeren still wirkungslos – zwei Faelle waeren dann
    // gruen, ohne ihre Lage herzustellen.
    function antwort(körper) {
        return Promise.resolve({
            ok: true, status: 200,
            json: function () { return Promise.resolve(körper); },
        });
    }
    // Routing ueber den PFAD, nie ueber die volle URL (Register).
    const attrappe = function (url, opt) {
        const voll = String(url);
        const p = voll.split('?')[0];
        gerufen.push({ pfad: p, url: voll, opt: opt || {} });
        if (p === '/api/wissen/scope') {
            return antwort({ ok: true, user: 'anna', is_editor: false, is_admin: false,
                             groups: (cfg.scopeGruppen || GRUPPEN), folders: [
                                 { path: 'data/rag/community', name: 'community',
                                   root: 'data/rag/community', depth: 0 }] });
        }
        if (p === '/api/wissen/files') return antwort({ ok: true, files: liste });
        if (p === '/api/knowledge/content_search') {
            const q = decodeURIComponent((voll.split('q=')[1] || ''));
            const körper = { ok: true, files: (inhalt ? inhalt(q) : []) };
            if (cfg.verzug) {
                return new Promise(function (r) {
                    setTimeout(function () { r(antwort(körper)); }, cfg.verzug(q));
                });
            }
            return antwort(körper);
        }
        return antwort({ ok: true, pending: [], spaces: [], status: 'ok' });
    };
    win.fetch = attrappe;
    global.fetch = attrappe;
    win.confirm = function () { return false; };
    win.alert = function () {};

    win.eval(JS_ICONS);
    win.eval(JS_I18N);
    win.eval(JS_WISSEN);
    win.document.dispatchEvent(new win.Event('DOMContentLoaded', { bubbles: true }));
    for (let i = 0; i < 80; i++) {
        await new Promise(function (r) { setTimeout(r, 5); });
        if (win.document.querySelectorAll('#wi-files-list .wi-item').length) break;
    }
    return { win, doc: win.document, gerufen };
}

function schlaf(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

// Tippt einen Text ins Suchfeld und loest das ECHTE input-Ereignis aus.
function tippe(s, text) {
    const el = s.doc.getElementById('wi-files-q');
    if (!el) abbruch('Suchfeld #wi-files-q fehlt – ohne es ist jede Aussage trivial');
    el.value = text;
    el.dispatchEvent(new s.win.Event('input', { bubbles: true }));
}

function namen(s) {
    return Array.prototype.slice
        .call(s.doc.querySelectorAll('#wi-files-list .wi-item a.nm'))
        .map(function (a) { return a.textContent; });
}
function leerText(s) {
    const e = s.doc.querySelector('#wi-files-list .wi-empty');
    return e ? e.textContent.trim() : '';
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
function suchAufrufe(s) {
    return s.gerufen.filter(function (g) { return g.pfad === '/api/knowledge/content_search'; });
}

(async function () {
    // ══ 1. Das Feld ist da und sichtbar ═══════════════════════════════════
    abschnitt('1 – Das Suchfeld existiert und ist sichtbar');

    const a = await seite(dateien(), null);
    check('drei Dateizeilen gezeichnet', namen(a).length === 3, 'gezeichnet: ' + namen(a).length);
    if (namen(a).length !== 3) abbruch('ohne gezeichnete Liste ist jede weitere Aussage trivial');

    const feld = a.doc.getElementById('wi-files-q');
    check('das Suchfeld ist im Markup', !!feld);
    check('das Suchfeld liegt in keinem versteckten Vorfahren',
          !!feld && !versteckterVorfahr(feld),
          feld && versteckterVorfahr(feld) ? 'versteckt durch: ' + versteckterVorfahr(feld).id : '');
    check('das Suchfeld traegt autocomplete="off" (Chrome-Autofill fuellt sonst ohne input-Ereignis)',
          !!feld && feld.getAttribute('autocomplete') === 'off');
    check('das Suchfeld hat einen uebersetzten Platzhalter',
          !!feld && !!feld.getAttribute('data-i18n-placeholder')
              && (feld.getAttribute('placeholder') || '').length > 3,
          feld ? feld.getAttribute('placeholder') : '');

    // ⚠ GEMESSEN, NICHT AM MARKUP ABGELESEN: ohne Wissensgruppen versteckt
    // renderFileFilter die Filterzeile. Laege das Suchfeld darin, waere es
    // genau dann unerreichbar. Geprueft wird deshalb der ZUSTAND der Seite
    // ohne Gruppen im Lese-Scope, nicht die Verschachtelung im Quelltext.
    const ohneGrp = await seite(dateien(), null, { scopeGruppen: [] });
    const feldOG = ohneGrp.doc.getElementById('wi-files-q');
    const fltOG = ohneGrp.doc.getElementById('wi-files-filter');
    check('ohne Wissensgruppen ist die Gruppen-Filterzeile versteckt (Positivkontrolle)',
          !!fltOG && !!versteckterVorfahr(fltOG),
          'style=' + JSON.stringify(fltOG && fltOG.getAttribute('style'))
          + ' boxen=' + (ohneGrp.doc.querySelectorAll('.wi-grp-flt').length));
    check('das Suchfeld bleibt trotzdem erreichbar',
          !!feldOG && !versteckterVorfahr(feldOG),
          feldOG && versteckterVorfahr(feldOG)
              ? 'versteckt durch: ' + (versteckterVorfahr(feldOG).id || '?') : 'Feld fehlt');
    check('und es filtert dort auch wirklich',
          (function () {
              tippe(ohneGrp, 'urlaub');
              return namen(ohneGrp).length === 1 && namen(ohneGrp)[0] === 'urlaub.md';
          })(), namen(ohneGrp).join(', '));
    check('es gibt einen sichtbaren Hinweis, was durchsucht wird',
          (function () {
              const h = a.doc.getElementById('wi-files-search-hint');
              return !!h && !versteckterVorfahr(h) && h.textContent.trim().length > 10;
          })());

    // ══ 2. Sofort-Suche ueber Name, Ordner, Gruppe ════════════════════════
    abschnitt('2 – Name, Ordner und Gruppe filtern SOFORT (ohne Serveraufruf)');

    const vorher = suchAufrufe(a).length;
    tippe(a, 'urlaub');
    check('Name: nur die passende Datei bleibt',
          namen(a).length === 1 && namen(a)[0] === 'urlaub.md', namen(a).join(', '));
    check('dabei wurde der Server NICHT gefragt (Sofort-Teil)',
          suchAufrufe(a).length === vorher);

    tippe(a, 'OneNote');
    check('Ordner: der Unterordner filtert mit',
          namen(a).length === 1 && namen(a)[0] === 'Anleitung SAP.one', namen(a).join(', '));

    tippe(a, 'Handbuecher');
    check('Gruppenname filtert mit',
          namen(a).length === 1 && namen(a)[0] === 'Anleitung SAP.one', namen(a).join(', '));

    tippe(a, 'PREISLISTE');
    check('Gross-/Kleinschreibung ist egal',
          namen(a).length === 1 && namen(a)[0] === 'Preisliste.xlsx', namen(a).join(', '));

    tippe(a, '');
    check('leeres Feld zeigt wieder alles', namen(a).length === 3, namen(a).join(', '));

    // ══ 3. Inhaltssuche ueber den Server ══════════════════════════════════
    abschnitt('3 – Der Dateiinhalt wird zusaetzlich ueber den Server gesucht');

    const b = await seite(dateien(), function (q) {
        // Ein Wort, das in KEINEM Namen und in KEINEM Ordner steht - der
        // Treffer kann also nur aus dem Inhalt kommen.
        return q === 'quartalsbericht' ? ['data/rag/community/Notizen/urlaub.md'] : [];
    });
    tippe(b, 'quartalsbericht');
    check('vor der Antwort ist die Liste leer (Wort steht in keinem Namen)',
          namen(b).length === 0, namen(b).join(', '));
    await schlaf(500);
    check('der Server wurde gefragt', suchAufrufe(b).length >= 1);
    check('die Anfrage traegt den Suchbegriff',
          suchAufrufe(b).some(function (g) { return g.url.indexOf('quartalsbericht') !== -1; }));
    check('nach der Antwort erscheint die Datei mit dem Inhalts-Treffer',
          namen(b).length === 1 && namen(b)[0] === 'urlaub.md', namen(b).join(', '));

    const c = await seite(dateien(), null);
    tippe(c, 'a');
    await schlaf(500);
    check('bei einem einzelnen Zeichen wird der Server NICHT gefragt',
          suchAufrufe(c).length === 0, 'Aufrufe: ' + suchAufrufe(c).length);

    // ══ 4. DER KERN: die Pfadformen sind nicht gleich ═════════════════════
    abschnitt('4 – Netz-Freigaben: content_search liefert den fuehrenden "/" mit');

    const d = await seite(dateien(), function (q) {
        // GENAU die Form, die content_search_paths fuer eine Datei ausserhalb
        // von PROJECT_ROOT zurueckgibt: MIT fuehrendem Schraegstrich.
        return q === 'buchungskreis' ? ['/mnt/rag/share_1/OneNote/Anleitung SAP.one'] : [];
    });
    tippe(d, 'buchungskreis');
    await schlaf(500);
    check('ein Treffer aus einer Netz-Freigabe wird trotz abweichender Pfadform gefunden',
          namen(d).length === 1 && namen(d)[0] === 'Anleitung SAP.one',
          'gezeigt: [' + namen(d).join(', ') + '] – Pfadformen angeglichen?');

    // Gegenrichtung: ein Treffer, den es in der eigenen Liste nicht gibt,
    // darf keine fremde Zeile einblenden.
    const e = await seite(dateien(), function () { return ['/mnt/rag/share_9/fremd.pdf']; });
    tippe(e, 'fremdwort');
    await schlaf(500);
    check('ein Treffer ausserhalb der eigenen Liste blendet nichts ein',
          namen(e).length === 0, namen(e).join(', '));

    // ══ 5. Wettlauf: veraltete Antwort zaehlt nicht ═══════════════════════
    abschnitt('5 – Eine Antwort zum ALTEN Begriff darf nicht zaehlen');

    // ⚠ Der Wettlauf entsteht nur, wenn die erste Anfrage WIRKLICH rausgeht:
    // dazu laenger warten als das Entprellen (sonst loescht der zweite
    // Tastendruck den Timer, und es gibt gar keine alte Antwort).
    // Der Server antwortet auf 'alt' langsam, auf alles andere sofort.
    const f = await seite(dateien(), function (q) {
        return q === 'alt' ? ['data/rag/community/Notizen/urlaub.md'] : [];
    }, { verzug: function (q) { return q === 'alt' ? 900 : 10; } });

    tippe(f, 'alt');
    await schlaf(450);            // > Entprellung: die Anfrage ist unterwegs
    check('die alte Anfrage ist wirklich rausgegangen (sonst misst der Fall nichts)',
          suchAufrufe(f).length === 1, 'Aufrufe: ' + suchAufrufe(f).length);
    tippe(f, 'altwort');          // weitergetippt, bevor die Antwort da war
    await schlaf(1200);           // beide Antworten sind jetzt durch
    check('die Liste bleibt leer – der Treffer gehoerte zum alten Begriff',
          namen(f).length === 0, namen(f).join(', '));

    // Gegenrichtung: kehrt der Benutzer zum alten Begriff zurueck, MUSS der
    // Treffer wieder gelten – eine Schranke, die dauerhaft sperrt, waere falsch.
    const f2 = await seite(dateien(), function (q) {
        return q === 'alt' ? ['data/rag/community/Notizen/urlaub.md'] : [];
    });
    tippe(f2, 'alt');
    await schlaf(500);
    check('derselbe Begriff findet den Inhalts-Treffer sehr wohl',
          namen(f2).length === 1 && namen(f2)[0] === 'urlaub.md', namen(f2).join(', '));

    // ⚠ DER ALLTAGSFALL, und er traegt die Zuordnung `_inhaltFuer === q`:
    // nach einem Inhalts-Treffer tippt der Benutzer WEITER. Der neue Begriff
    // hat noch keine Antwort – die alten Treffer duerfen fuer ihn nicht gelten,
    // sonst bleibt eine Zeile stehen, die zum getippten Text nicht passt.
    const f3 = await seite(dateien(), function (q) {
        return q === 'quartal' ? ['data/rag/community/Notizen/urlaub.md'] : [];
    });
    tippe(f3, 'quartal');
    await schlaf(500);
    check('Ausgangslage: der Inhalts-Treffer steht da',
          namen(f3).length === 1, namen(f3).join(', '));
    tippe(f3, 'quartalsbericht');     // weitergetippt, noch keine neue Antwort
    check('nach dem Weitertippen gilt der alte Treffer NICHT mehr',
          namen(f3).length === 0, namen(f3).join(', '));

    // ⚠ UND DER FALL, den die Schranke beim SPEICHERN traegt: eine langsame
    // Antwort zum KURZEN Begriff darf die bereits eingetroffene Antwort zum
    // laengeren nicht ueberschreiben – sonst verliert der Benutzer einen
    // Treffer, den er schon gesehen hat.
    const f4 = await seite(dateien(), function (q) {
        if (q === 'lang') return [];
        if (q === 'langsam') return ['data/rag/community/Notizen/urlaub.md'];
        return [];
    }, { verzug: function (q) { return q === 'lang' ? 900 : 10; } });
    tippe(f4, 'lang');
    await schlaf(450);                // Anfrage fuer 'lang' ist unterwegs
    tippe(f4, 'langsam');             // schnelle Antwort kommt zuerst
    await schlaf(500);
    check('Zwischenstand: der Treffer zum laengeren Begriff ist da',
          namen(f4).length === 1 && namen(f4)[0] === 'urlaub.md', namen(f4).join(', '));
    await schlaf(800);                // jetzt trifft die alte, leere Antwort ein
    check('die spaete Antwort zum alten Begriff nimmt ihn nicht wieder weg',
          namen(f4).length === 1 && namen(f4)[0] === 'urlaub.md', namen(f4).join(', '));

    // ══ 6. Zaehler und Leermeldung ════════════════════════════════════════
    abschnitt('6 – Zaehler und Leermeldung nennen den wirklichen Grund');

    const g = await seite(dateien(), null);
    tippe(g, 'urlaub');
    const zahl = (g.doc.getElementById('wi-files-count') || {}).textContent || '';
    check('der Zaehler nennt die gefilterte Zahl', /\b1\b/.test(zahl) && /\b3\b/.test(zahl), zahl);

    tippe(g, 'gibtesnicht');
    const leer = leerText(g);
    check('die Leermeldung erscheint', leer.length > 0);
    check('sie nennt die SUCHE als Grund, nicht den Gruppenfilter',
          leer.indexOf('gibtesnicht') !== -1, leer);
    check('sie behauptet NICHT "keine Dateien in den gewaehlten Wissensgruppen"',
          leer.indexOf('Wissensgruppen') === -1, leer);

    // Gegenrichtung: ohne Suche bleibt die alte Meldung die richtige.
    const h = await seite([], null);
    check('leerer Bereich: die Suchzeile wird gar nicht erst gezeigt',
          (function () {
              const el = h.doc.getElementById('wi-files-search');
              return !!el && versteckterVorfahr(el);
          })());

    // ══ 7. Suche UND Gruppenfilter ════════════════════════════════════════
    abschnitt('7 – Suche und Gruppenfilter wirken zusammen');

    const i = await seite(dateien(), null);
    const box = Array.prototype.slice.call(i.doc.querySelectorAll('.wi-grp-flt'))
        .filter(function (cb) { return cb.value === 'technik'; })[0];
    check('der Gruppen-Filter ist gezeichnet', !!box);
    if (box) {
        box.checked = false;
        box.dispatchEvent(new i.win.Event('change', { bubbles: true }));
    }
    check('ohne Suche zeigt der Gruppenfilter zwei Dateien', namen(i).length === 2, namen(i).join(', '));
    tippe(i, 'anleitung');
    check('die ausgefilterte Gruppe bleibt auch bei passender Suche aussen vor',
          namen(i).length === 0, namen(i).join(', '));

    // ══ 8. Escape leert das Feld ══════════════════════════════════════════
    abschnitt('8 – Escape leert die Suche');

    const j = await seite(dateien(), null);
    tippe(j, 'urlaub');
    check('gefiltert', namen(j).length === 1);
    const fj = j.doc.getElementById('wi-files-q');
    fj.dispatchEvent(new j.win.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    check('Escape leert das Feld', fj.value === '', fj.value);
    check('Escape stellt die volle Liste her', namen(j).length === 3, namen(j).join(', '));

    // ══ 9. i18n in BEIDEN Sprachen ════════════════════════════════════════
    abschnitt('9 – Die Texte gibt es in DE und EN');

    const txt = JS_I18N;
    ['wissen.search_ph', 'wissen.search_hint', 'wissen.no_files_search'].forEach(function (k) {
        const n = (txt.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length;
        check('Schluessel ' + k + ' steht in beiden Sprachen', n === 2, 'gefunden: ' + n);
    });

    clearTimeout(WACHHUND);
    bilanz = true;
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
    process.exit(fail ? 1 : 0);
})();
