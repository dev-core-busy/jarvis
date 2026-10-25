#!/usr/bin/env node
/* Waechter: Zellkommentare des Excel-Aufgabenfensters (`kosmetik`).
 *
 * DER BEZAHLTE VORFALL (2026-10-23, aus dem Add-in gemeldet): ein Vorschlag
 * trug DREIMAL denselben Bereich `2026!B12:AN12`. `comments.add` haengt an der
 * oberen linken Zelle; der zweite Aufruf auf B12 wirft `InvalidOperation`, und
 * weil alle Aufrufe in EINEM `ctx.sync()` liegen, faellt der ganze Lauf:
 *
 *     [markierung] nicht gesetzt (die Aenderung selbst steht)
 *         code=InvalidOperation  errorLocation=CommentCollection.add
 *
 * Das Nachsehen per `getItemByCell` konnte das nicht verhindern – es laeuft
 * fuer ALLE Ziele, BEVOR der erste `add` passiert ist.
 *
 * ⚠ DIE ATTRAPPE BILDET GENAU DIESES WERFEN NACH. Eine, die einen zweiten
 * Kommentar klaglos annimmt, koennte die zu pruefende Lage gar nicht
 * herstellen und waere dauerhaft gruen (Register). Abschnitt 0 belegt
 * deshalb ZUERST, dass sie wirft – sonst Exit 2.
 *
 * Die echte `kosmetik` wird geschnitten und WIRKLICH AUSGEFUEHRT. Eine
 * Quelltext-Pruefung koennte „wie viele `add` kommen am Ende an?" nicht
 * beantworten.
 */
'use strict';

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/excel.js'), 'utf8');

let ok = 0, fail = 0, bilanz = false;

function pruefe(bed, text) {
    if (bed) ok++; else { fail++; console.log('  FAIL: ' + text); }
}

/* Netz gegen den stillen Abbruch: ohne Bilanzzeile ist ein abgestuerzter Lauf
 * von einem bestandenen nicht zu unterscheiden. Nur einen STILLEN Abbruch
 * anheben – ein ausdrueckliches `process.exit(2)` darf nicht zu 1 werden. */
process.on('exit', (code) => {
    if (!bilanz && code === 0) {
        console.log('\nErgebnis: ABGEBROCHEN – keine Bilanz erreicht');
        process.exitCode = 1;
    }
});

function abbruch(grund) {
    console.log('ABBRUCH: ' + grund);
    bilanz = true;
    process.exit(2);
}

/* ── Funktionen schneiden ──────────────────────────────────────────────── */
function schneide(name) {
    const anker = 'function ' + name + '(';
    const i = JS.indexOf(anker);
    if (i < 0) return null;
    const auf = JS.indexOf('{', i);
    if (auf < 0) return null;
    let tiefe = 0;
    for (let j = auf; j < JS.length; j++) {
        const c = JS[j];
        if (c === '{') tiefe++;
        else if (c === '}') { tiefe--; if (tiefe === 0) return JS.slice(i, j + 1); }
    }
    return null;
}

const TEILE = ['ankerSchluessel', 'kosmetik'];
const code = {};
for (const t of TEILE) {
    code[t] = schneide(t);
    if (!code[t]) abbruch('Funktion ' + t + ' nicht schneidbar');
}
// Positivkontrolle des Schnitts – sonst prueft der Waechter eine leere
// Zeichenkette gegen sich selbst.
if (!code.kosmetik.includes('comments.add')) {
    abbruch('Schnitt kosmetik enthaelt keinen comments.add');
}
// ⚠ DER GUARD PRUEFT, DASS DER SCHNITT LAEUFT – NICHT WIE ER ES TUT. Hier
// stand `includes('split(')`, also genau die Zeichenkette, die eine
// Gegenprobe zur Ankerzelle entfernt: die Probe brach mit Exit 2 ab
// ("konnte nicht laufen") statt zu beissen, und ein abgebrochener Lauf ist
// von einem bestandenen nicht zu unterscheiden. Ein Guard, der eine
// Implementierung festschreibt, macht jede Gegenprobe darauf unmessbar.
try {
    // eslint-disable-next-line no-new-func
    const _ank = new Function(code.ankerSchluessel + '\nreturn ankerSchluessel;')();
    const _probe = _ank({ blatt: 'X', adresse: 'B12:AN12' });
    if (typeof _probe !== 'string' || _probe.indexOf('!') < 0) {
        abbruch('ankerSchluessel liefert keinen Blatt!Zelle-Schluessel: ' + _probe);
    }
} catch (e) {
    abbruch('ankerSchluessel nicht ausfuehrbar: ' + e.message);
}

/* ── Office.js-Attrappe ────────────────────────────────────────────────────
   Sie zeichnet auf UND bildet das echte Werfen nach. `getItemByCell` wirft
   bei einer Zelle ohne Kommentar erst beim `sync()` – genau wie das Original;
   wuerde sie sofort werfen, liefe der Code in einen anderen Zweig als im
   Betrieb. */
function bauOffice() {
    // ⚠ ZWEI ZAEHLER, UND DAS IST KEINE FEINHEIT: `getItemByCell` auf eine
    // Zelle OHNE Kommentar wirft REGULAER (der Code schluckt das bewusst).
    // Wer jeden sync-Fehler zaehlt, meldet genau diesen Regelfall als Befund –
    // beim ersten Lauf dieses Waechters 3 FAIL, die es im Produkt nicht gab.
    // Gemessen wird deshalb der Fehler, um den es geht: CommentCollection.add.
    const log = { add: [], inhalt: [], fuellung: [], syncFehler: 0, addFehler: 0 };
    const kommentare = {};          // "BLATT!ZELLE" -> text

    function zelle(blatt, adr) {
        return { _blatt: blatt, _adr: String(adr).split(':')[0].replace(/\$/g, '').toUpperCase() };
    }
    function schluessel(z) { return z._blatt.toUpperCase() + '!' + z._adr; }

    const ctx = { _offen: [] };

    function bereich(blatt, adr) {
        return {
            format: { fill: { set color(v) { log.fuellung.push(blatt + '!' + adr + '=' + v); } } },
            getCell: function () { return zelle(blatt, adr); }
        };
    }
    function blattObj(name) {
        return { getRange: function (adr) { return bereich(name, adr); } };
    }

    ctx.workbook = {
        worksheets: {
            getItem: function (n) { return blattObj(n); },
            getActiveWorksheet: function () { return blattObj('Tabelle1'); }
        },
        comments: {
            add: function (z, text) {
                const k = schluessel(z);
                // ⚠ DAS ECHTE VERHALTEN: ein zweiter Kommentar auf dieselbe
                // Zelle wirft. Der Fehler faellt beim sync() an.
                ctx._offen.push(function () {
                    if (kommentare[k] !== undefined) {
                        const e = new Error('Dieser Vorgang ist für das aktuelle Objekt nicht zulässig.');
                        e.code = 'InvalidOperation';
                        e.errorLocation = 'CommentCollection.add';
                        throw e;
                    }
                    kommentare[k] = text;
                    log.add.push(k + ' :: ' + text);
                });
            },
            getItemByCell: function (adr) {
                const teile = String(adr).split('!');
                const k = (teile.length > 1 ? teile[0] : 'Tabelle1').toUpperCase() +
                    '!' + String(teile[teile.length - 1]).replace(/\$/g, '').toUpperCase();
                const obj = {
                    _k: k, _geladen: false,
                    // ⚠ `load` wirkt wie im Original ERST beim sync() – und
                    // faellt mit dem Batch aus, wenn davor etwas wirft
                    // (Code-Review 2026-10-25). Die erste Fassung setzte
                    // `_geladen` sofort: der Abbruch des Batches war damit
                    // nicht darstellbar, und der Waechter konnte den Fehler
                    // "Zelle ohne Kommentar VOR Zelle mit Kommentar" nie sehen.
                    load: function () { ctx._offen.push(function () { obj._geladen = true; }); },
                    set content(v) { log.inhalt.push(k + ' :: ' + v); kommentare[k] = v; },
                    get id() {
                        if (!obj._geladen) throw new Error('PropertyNotLoaded');
                        return kommentare[k] !== undefined ? 'id-' + k : undefined;
                    }
                };
                // Wie im Original: fehlt der Kommentar, faellt der Fehler
                // erst beim sync() an.
                ctx._offen.push(function () {
                    if (kommentare[k] === undefined) throw new Error('ItemNotFound');
                });
                return obj;
            }
        }
    };

    ctx.sync = function () {
        const auf = ctx._offen;
        ctx._offen = [];
        try {
            for (const f of auf) f();
        } catch (e) {
            log.syncFehler++;
            if (e && e.code === 'InvalidOperation') log.addFehler++;
            return Promise.reject(e);
        }
        return Promise.resolve();
    };

    const Excel = {
        run: function (cb) {
            try { return Promise.resolve(cb(ctx)); }
            catch (e) { return Promise.reject(e); }
        }
    };
    return { Excel: Excel, log: log, kommentare: kommentare, ctx: ctx };
}

/* ── Prolog: alles, was die geschnittene Funktion aussenherum braucht ───── */
function laufen(aenderungen, opt) {
    opt = opt || {};
    const o = bauOffice();
    const protokolle = [];
    const sandbox = {
        Promise: Promise,
        Excel: o.Excel,
        window: { Excel: o.Excel },
        _office: true,
        _kann110: opt.kann110 === false ? false : true,
        MARK_FARBE: '#FFF2CC',
        markAn: function () { return opt.markAn === false ? false : true; },
        T: function (k, f) { return f; },
        protokoll: function (b, t) { protokolle.push(b + ': ' + t); },
        fehlerDetails: function (e) { return 'code=' + (e && e.code); }
    };
    const namen = Object.keys(sandbox);
    const werte = namen.map((n) => sandbox[n]);
    // eslint-disable-next-line no-new-func
    const fn = new Function(...namen,
        code.ankerSchluessel + '\n' + code.kosmetik + '\nreturn kosmetik;');
    return fn(...werte)(aenderungen).then(function () {
        return { log: o.log, kommentare: o.kommentare, protokolle: protokolle };
    });
}

const E = (blatt, adresse, begruendung) => ({ blatt, adresse, begruendung, werte: [[1]] });

(async function () {
    console.log('── 0. Positivkontrolle: kann die Attrappe den Fehler ueberhaupt? ──');
    // Ohne diesen Beleg waere jede folgende Pruefung trivial wahr.
    {
        const o = bauOffice();
        const z = { _blatt: 'X', _adr: 'B12' };
        o.ctx.workbook.comments.add(z, 'eins');
        o.ctx.workbook.comments.add(z, 'zwei');
        let geworfen = null;
        try { await o.ctx.sync(); } catch (e) { geworfen = e; }
        if (!geworfen || geworfen.code !== 'InvalidOperation') {
            abbruch('die Attrappe wirft bei doppeltem comments.add NICHT – ' +
                    'jede weitere Pruefung waere trivial wahr');
        }
        pruefe(geworfen.errorLocation === 'CommentCollection.add',
               'die Attrappe meldet errorLocation wie das Original');
    }

    console.log('── 1. DER GEMELDETE FALL: dreimal derselbe Bereich ─────────────────');
    {
        const r = await laufen([
            E('2026', 'B12:AN12', 'erste Begruendung'),
            E('2026', 'B12:AN12', 'zweite Begruendung'),
            E('2026', 'B12:AN12', 'dritte Begruendung')
        ]);
        pruefe(r.log.add.length === 1,
               'genau EIN comments.add (gezaehlt: ' + r.log.add.length + ')');
        pruefe(r.log.addFehler === 0,
               'kein comments.add ist gescheitert (gezaehlt: ' + r.log.addFehler + ')');
        pruefe(!r.protokolle.some((p) => p.indexOf('nicht gesetzt') >= 0),
               'das Protokoll meldet KEIN "nicht gesetzt"');
        // Es gewinnt der LETZTE – wie beim Zellinhalt auch.
        pruefe(r.log.add[0] && r.log.add[0].indexOf('dritte Begruendung') >= 0,
               'der LETZTE Eintrag stellt den Kommentar (gefunden: ' + r.log.add[0] + ')');
        // Die Markierung darf NICHT dedupliziert werden – sie ist idempotent,
        // und ein ausgefallener Zweig faellt hier sonst nicht auf.
        pruefe(r.log.fuellung.length === 3,
               'alle drei Bereiche wurden eingefaerbt (gezaehlt: ' + r.log.fuellung.length + ')');
    }

    console.log('── 2. Verschiedene Zellen bekommen JEDE ihren Kommentar ────────────');
    {
        const r = await laufen([
            E('2026', 'B12:AN12', 'eins'),
            E('2026', 'B13:AN13', 'zwei'),
            E('2026', 'B14:AN14', 'drei')
        ]);
        pruefe(r.log.add.length === 3,
               'drei verschiedene Anker = drei Kommentare (gezaehlt: ' + r.log.add.length + ')');
        pruefe(r.log.addFehler === 0, 'kein comments.add ist gescheitert');
    }

    console.log('── 3. Gleicher ANKER bei verschiedener Adresse ─────────────────────');
    {
        // ⚠ DIE EIGENTLICHE FALLE: `comments.add` haengt am oberen linken
        // Feld. B12:AN12 und B12:B20 sind verschiedene Bereiche mit DERSELBEN
        // Ankerzelle – eine Deduplizierung ueber die Adresse wuerde hier
        // wieder zweimal adden.
        const r = await laufen([
            E('2026', 'B12:AN12', 'waagerecht'),
            E('2026', 'B12:B20', 'senkrecht')
        ]);
        pruefe(r.log.add.length === 1,
               'gleicher Anker = EIN Kommentar (gezaehlt: ' + r.log.add.length + ')');
        pruefe(r.log.addFehler === 0, 'kein comments.add ist gescheitert');
    }

    console.log('── 4. Absolute Adressen zaehlen als dieselbe Zelle ─────────────────');
    {
        const r = await laufen([
            E('2026', '$B$12:$AN$12', 'absolut'),
            E('2026', 'B12:AN12', 'relativ')
        ]);
        pruefe(r.log.add.length === 1,
               '$B$12 und B12 sind derselbe Anker (gezaehlt: ' + r.log.add.length + ')');
    }

    console.log('── 5. Dasselbe Feld auf VERSCHIEDENEN Blaettern ────────────────────');
    {
        const r = await laufen([
            E('2026', 'B12:AN12', 'eins'),
            E('2025', 'B12:AN12', 'zwei')
        ]);
        pruefe(r.log.add.length === 2,
               'der Blattname gehoert zum Schluessel (gezaehlt: ' + r.log.add.length + ')');
    }

    console.log('── 6. Ein VORHANDENER Kommentar wird ersetzt, nicht angelegt ───────');
    {
        const o = bauOffice();
        // Vorzustand: B12 traegt schon einen Kommentar aus einem frueheren Lauf.
        o.ctx.workbook.comments.add({ _blatt: '2026', _adr: 'B12' }, 'alt');
        await o.ctx.sync();
        const vorher = o.log.add.length;
        // Denselben Office-Zustand weiterbenutzen: ein frischer waere ein
        // anderer Fall (Abschnitt 1) und wuerde die Ersetzung nicht messen.
        const protokolle = [];
        const sandbox = {
            Promise, Excel: o.Excel, window: { Excel: o.Excel },
            _office: true, _kann110: true, MARK_FARBE: '#FFF2CC',
            markAn: () => true, T: (k, f) => f,
            protokoll: (b, t) => protokolle.push(b + ': ' + t),
            fehlerDetails: (e) => 'code=' + (e && e.code)
        };
        const namen = Object.keys(sandbox);
        // eslint-disable-next-line no-new-func
        const fn = new Function(...namen,
            code.ankerSchluessel + '\n' + code.kosmetik + '\nreturn kosmetik;');
        await fn(...namen.map((n) => sandbox[n]))([
            E('2026', 'B12:AN12', 'neu'), E('2026', 'B12:AN12', 'neuer')
        ]);
        pruefe(o.log.add.length === vorher,
               'kein zusaetzliches add auf die belegte Zelle (gezaehlt: ' +
               (o.log.add.length - vorher) + ')');
        pruefe(o.log.inhalt.length === 1,
               'der Inhalt wurde EINMAL ersetzt (gezaehlt: ' + o.log.inhalt.length + ')');
        pruefe(o.kommentare['2026!B12'] === 'Jarvis: neuer',
               'es gilt der LETZTE Text (gefunden: ' + o.kommentare['2026!B12'] + ')');
    }

    console.log('── 6b. Zelle OHNE Kommentar VOR einer Zelle MIT Kommentar ─────────');
    {
        // Code-Review 2026-10-25: alle getItemByCell lagen in EINEM Batch. Das
        // erwartete ItemNotFound der ersten Zelle brach ihn ab – die `load`
        // der folgenden Zellen liefen nie, ihre vorhandenen Kommentare galten
        // als "nicht da", und comments.add warf InvalidOperation.
        const o = bauOffice();
        o.ctx.workbook.comments.add({ _blatt: '2026', _adr: 'B12' }, 'alt');
        await o.ctx.sync();
        const vorher = o.log.add.length;
        const protokolle = [];
        const sandbox = {
            Promise, Excel: o.Excel, window: { Excel: o.Excel },
            _office: true, _kann110: true, MARK_FARBE: '#FFF2CC',
            markAn: () => true, T: (k, f) => f,
            protokoll: (b, t) => protokolle.push(b + ': ' + t),
            fehlerDetails: (e) => 'code=' + (e && e.code)
        };
        const namen = Object.keys(sandbox);
        // eslint-disable-next-line no-new-func
        const fn = new Function(...namen,
            code.ankerSchluessel + '\n' + code.kosmetik + '\nreturn kosmetik;');
        await fn(...namen.map((n) => sandbox[n]))([
            E('2026', 'C5', 'neu an C5'), E('2026', 'B12:AN12', 'neu an B12')
        ]);
        pruefe(o.log.addFehler === 0,
               'kein comments.add ist gescheitert (gezaehlt: ' + o.log.addFehler + ')');
        pruefe(o.log.add.length - vorher === 1 && o.kommentare['2026!C5'] === 'Jarvis: neu an C5',
               'C5 bekommt einen NEUEN Kommentar (adds: ' + (o.log.add.length - vorher) + ')');
        pruefe(o.kommentare['2026!B12'] === 'Jarvis: neu an B12',
               'der VORHANDENE Kommentar an B12 wird ersetzt (gefunden: ' +
               o.kommentare['2026!B12'] + ')');
        pruefe(!protokolle.some((p) => p.indexOf('nicht gesetzt') >= 0),
               'das Protokoll meldet KEIN "nicht gesetzt"');
    }

    console.log('── 7. Ohne Begruendung kein Kommentar ──────────────────────────────');
    {
        const r = await laufen([
            { blatt: '2026', adresse: 'B12:AN12', werte: [[1]] },
            { blatt: '2026', adresse: 'B13:AN13', werte: [[1]] }
        ]);
        pruefe(r.log.add.length === 0,
               'kein Kommentar ohne Begruendung (gezaehlt: ' + r.log.add.length + ')');
        pruefe(r.log.fuellung.length === 2,
               'markiert wird trotzdem (gezaehlt: ' + r.log.fuellung.length + ')');
    }

    console.log('── 8. Ohne ExcelApi 1.10 bleibt es bei der Markierung ──────────────');
    {
        const r = await laufen([E('2026', 'B12:AN12', 'x')], { kann110: false });
        pruefe(r.log.add.length === 0, 'kein Kommentar ohne 1.10');
        pruefe(r.log.fuellung.length === 1, 'die Markierung laeuft trotzdem');
    }

    console.log('── 9. Markieren ausgeschaltet = gar kein Eingriff ──────────────────');
    {
        const r = await laufen([E('2026', 'B12:AN12', 'x')], { markAn: false });
        pruefe(r.log.add.length === 0 && r.log.fuellung.length === 0,
               'weder Kommentar noch Markierung');
    }

    console.log('── 10. Die Fassung steht im Titel, aus EINER Quelle ───────────────');
    {
        const HTML = fs.readFileSync(
            path.join(ROOT, 'frontend/excel-addin/taskpane.html'), 'utf8');
        // ⚠ DIE ZAHL DARF NUR AN EINER STELLE STEHEN. Der Titel kommt zweimal
        // im Markup vor und zweimal in i18n.js (DE/EN) – vier Pflegestellen
        // fuer eine Zahl sind die Zeitbombe, vor der das Register warnt.
        const treffer = JS.match(/var XL_VERSION = '([^']+)'/);
        pruefe(!!treffer, 'XL_VERSION ist in excel.js definiert');
        const ver = treffer ? treffer[1] : null;
        // ⚠ DREI GRUPPEN: Haupt.Neben.BAUNUMMER (Festlegung 2026-10-23).
        // Die dritte steigt bei jedem Neubau um eins – geprueft wird die FORM,
        // nicht der Wert: eine feste Zahl in einem Waechter ist die Zeitbombe,
        // die das Register beschreibt (sie wird beim naechsten Bau falsch).
        pruefe(/^\d+\.\d{2}\.\d{2,}$/.test(ver || ''),
               'die Fassung hat die Form N.NN.BB (gefunden: ' + ver + ')');
        const bau = ver ? parseInt(ver.split('.')[2], 10) : 0;
        pruefe(bau >= 1, 'die Baunummer ist mindestens 1 (gefunden: ' + bau + ')');
        // Jeder Titel im Markup traegt den Platz dafuer – sonst ist die
        // Version auf der Anmeldemaske unsichtbar und erscheint erst nach
        // dem Anmelden.
        const titel = (HTML.match(/data-i18n="xl\.title"/g) || []).length;
        const plaetze = (HTML.match(/class="xl-ver"/g) || []).length;
        pruefe(titel > 0 && plaetze === titel,
               'jeder Titel hat seinen Versions-Platz (' + plaetze + ' zu ' + titel + ')');
        // Die Zahl steht NICHT im i18n-Wert: dort wuerde sie je Sprache
        // gepflegt und beim naechsten Mal auseinanderlaufen.
        const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
        const werte = I18N.match(/'xl\.title':\s*'([^']*)'/g) || [];
        pruefe(werte.length >= 2, 'xl.title ist in beiden Sprachen gesetzt');
        pruefe(!werte.some((w) => w.indexOf('(v') >= 0),
               'kein i18n-Wert traegt die Fassung selbst');
        // Und der Platz ist leer – ein Markup-Fallback waere eine zweite
        // Quelle, die still von XL_VERSION abweichen kann.
        // ⚠ NICHT ueber `>\s*\S` pruefen: das `<` von `</span>` IST ein
        // Nicht-Leerzeichen, der leere Platz haette die Pruefung also immer
        // verletzt (beim ersten Lauf genau so passiert – ein FAIL, den es im
        // Markup nicht gab). Gezaehlt wird die leere Form gegen alle Plaetze.
        const leer = (HTML.match(/class="xl-ver"><\/span>/g) || []).length;
        pruefe(leer === plaetze,
               'jeder Versions-Platz ist leer (' + leer + ' von ' + plaetze + ')');
    }

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
