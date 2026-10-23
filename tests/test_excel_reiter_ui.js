#!/usr/bin/env node
/* Waechter: Einstellungen und Protokoll als zwei REITER, plus der Schalter
 * "ausfuehrliche Diagnose" (debug).
 *
 * VORHER LAGEN SIE INEINANDER: das Protokoll war ein <details> INNERHALB des
 * <details> "Einstellungen". Wer bei einem Fehler das Protokoll brauchte,
 * musste erst die Einstellungen aufklappen – und die Zeile, die einen Lauf
 * erklaert, ist genau dann wichtig, wenn jemand unter Druck sucht.
 *
 * ⚠ GEMESSEN WIRD AUSGEFUEHRT, NICHT GELESEN. Am 2026-10-23 blieben zwei
 * Gegenproben stumm, weil ein Waechter `"d.grund === 'modell_stumm'" in JS`
 * prueste – eine Sabotage `if (false && …)` laesst den Text stehen. Die
 * echten Funktionen (`reiterZeigen`, `reiterUmschalten`, `debugAn`,
 * `debugSetzen`, `protokollDebug`) laufen deshalb hier gegen ein jsdom-DOM,
 * das aus dem ECHTEN Markup gebaut wird.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/excel.js'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/taskpane.html'), 'utf8');

let ok = 0, fail = 0, bilanz = false;

function pruefe(bed, text) {
    if (bed) ok++; else { fail++; console.log('  FAIL: ' + text); }
}

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

const code = {};
for (const t of ['reiterZeigen', 'reiterUmschalten', 'debugAn', 'debugSetzen',
                 'protokoll', 'protokollDebug', 'logZeichnen']) {
    code[t] = schneide(t);
    if (!code[t]) abbruch('Funktion ' + t + ' nicht schneidbar');
}

/* Baut das ECHTE Markup und gibt die geschnittenen Funktionen darauf los.
   `runScripts: 'outside-only'` laedt die <script src> der Seite NICHT – die
   Module werden bewusst nicht ausgefuehrt, sonst miede man die Isolation, die
   diesen Pruefstand schnell und deterministisch macht. */
function bau() {
    const dom = new JSDOM(HTML, { runScripts: 'outside-only' });
    const doc = dom.window.document;
    const protokolle = [];
    const speicher = {};
    const sandbox = {
        document: doc,
        localStorage: {
            getItem: (k) => (k in speicher ? speicher[k] : null),
            setItem: (k, v) => { speicher[k] = String(v); },
            removeItem: (k) => { delete speicher[k]; }
        },
        T: (k, f) => f,
        Date: dom.window.Date
    };
    const namen = Object.keys(sandbox);
    // `_log`, `_speicherGeht` und `_debugRam` sind Modulvariablen, die der
    // Code SETZT – als Parameter uebergeben traefe die Zuweisung nur die
    // lokale Kopie (am 2026-10-23 bei `_verlauf` genau so bezahlt).
    // eslint-disable-next-line no-new-func
    const fn = new Function(...namen,
        'var _log = []; var _speicherGeht = true; var _debugRam = "0";' +
        'var LOG_MAX = 60; var DEBUG_KEY = "jarvis_xl_debug";' +
        'function $(id) { return document.getElementById(id); }' +
        'function zeitstempel() { return "00:00:00.000"; }' +
        'function logText() { return _log.length ? _log.join("\\n") : "leer"; }' +
        Object.keys(code).map((k) => code[k]).join('\n') +
        '\nreturn { reiterZeigen: reiterZeigen, reiterUmschalten: reiterUmschalten,' +
        ' debugAn: debugAn, debugSetzen: debugSetzen, protokoll: protokoll,' +
        ' protokollDebug: protokollDebug, log: function () { return _log; } };');
    const api = fn(...namen.map((n) => sandbox[n]));
    return { dom, doc, api, speicher, protokolle };
}

function zu(doc, id) {
    const el = doc.getElementById(id);
    return !el || el.classList.contains('hidden');
}
function gewaehlt(doc, name) {
    const el = doc.querySelector('.xl-tab[data-xl-tab="' + name + '"]');
    return !!el && el.getAttribute('aria-selected') === 'true';
}

(function () {
    console.log('── 0. Positivkontrolle: das Markup traegt zwei Reiter ──────────────');
    {
        const { doc } = bau();
        const reiter = doc.querySelectorAll('.xl-tab');
        if (reiter.length !== 2) {
            abbruch('erwartet 2 Reiter, gefunden ' + reiter.length +
                    ' – der Pruefstand misst nicht die gemeinte Oberflaeche');
        }
        const panels = doc.querySelectorAll('.xl-tabpanel');
        if (panels.length !== 2) {
            abbruch('erwartet 2 Panels, gefunden ' + panels.length);
        }
        pruefe(true, 'zwei Reiter und zwei Panels sind vorhanden');
        // ⚠ DIE ALTE VERSCHACHTELUNG MUSS WEG SEIN, nicht nur ergaenzt: lagen
        // beide Fassungen nebeneinander, wuerde dieser Waechter gruen und der
        // Benutzer saehe weiter die alte.
        pruefe(!doc.getElementById('xl-einst'),
               'das alte <details id="xl-einst"> ist weg');
        pruefe(!doc.getElementById('xl-log'),
               'das verschachtelte <details id="xl-log"> ist weg');
        // Beide Bereiche sind GLEICHRANGIG – keiner liegt im anderen.
        const pe = doc.getElementById('xl-panel-einst');
        const pp = doc.getElementById('xl-panel-proto');
        pruefe(!!pe && !!pp, 'beide Panels existieren');
        pruefe(pe && pp && !pe.contains(pp) && !pp.contains(pe),
               'kein Panel liegt im anderen');
        pruefe(pe && pp && pe.parentNode === pp.parentNode,
               'beide haengen am selben Elternteil (gleichrangig)');
    }

    console.log('── 1. Der Bereich startet GESCHLOSSEN ──────────────────────────────');
    {
        const { doc, api } = bau();
        api.reiterZeigen('');
        pruefe(zu(doc, 'xl-panel-einst'), 'Einstellungen sind zu');
        pruefe(zu(doc, 'xl-panel-proto'), 'Protokoll ist zu');
        pruefe(!gewaehlt(doc, 'einst') && !gewaehlt(doc, 'proto'),
               'kein Reiter ist als gewaehlt gemeldet');
        // Das Markup selbst muss schon zu sein – zwischen Laden und erstem
        // Skriptlauf saehe man sonst einen offenen Block aufblitzen.
        const { doc: d2 } = bau();
        pruefe(zu(d2, 'xl-panel-einst') && zu(d2, 'xl-panel-proto'),
               'schon im MARKUP sind beide Panels zu');
    }

    console.log('── 2. Ein Klick oeffnet GENAU EINEN Reiter ─────────────────────────');
    {
        const { doc, api } = bau();
        api.reiterUmschalten('proto');
        pruefe(!zu(doc, 'xl-panel-proto'), 'Protokoll ist offen');
        pruefe(zu(doc, 'xl-panel-einst'), 'Einstellungen bleiben zu');
        pruefe(gewaehlt(doc, 'proto'), 'der Protokoll-Reiter ist gewaehlt');
        pruefe(!gewaehlt(doc, 'einst'), 'der andere nicht');

        api.reiterUmschalten('einst');
        pruefe(!zu(doc, 'xl-panel-einst'), 'jetzt sind Einstellungen offen');
        pruefe(zu(doc, 'xl-panel-proto'), '...und das Protokoll zu');
        pruefe(gewaehlt(doc, 'einst') && !gewaehlt(doc, 'proto'),
               'aria-selected folgt mit');
    }

    console.log('── 3. Klick auf den OFFENEN Reiter schliesst ───────────────────────');
    {
        // Ohne diesen Weg gibt es keine Rueckkehr zur vollen Chat-Hoehe – der
        // Benutzer muesste das Fenster neu laden.
        const { doc, api } = bau();
        pruefe(api.reiterUmschalten('proto') === 'proto', 'erster Klick oeffnet');
        pruefe(api.reiterUmschalten('proto') === '', 'zweiter Klick schliesst');
        pruefe(zu(doc, 'xl-panel-proto'), 'das Panel ist wieder zu');
        pruefe(!gewaehlt(doc, 'proto'), 'der Reiter ist nicht mehr gewaehlt');
    }

    console.log('── 4. aria-selected und "hidden" bleiben EINIG ─────────────────────');
    {
        // ⚠ ZWEI QUELLEN FUER EINEN ZUSTAND LAUFEN AUSEINANDER, und dann luegt
        // die Anzeige gegenueber dem Screenreader (Register). Geprueft wird
        // die Kopplung ueber ALLE Zustaende, nicht nur den Startfall.
        const { doc, api } = bau();
        for (const z of ['', 'einst', 'proto', 'einst', '']) {
            api.reiterZeigen(z);
            const r = doc.querySelectorAll('.xl-tab');
            let stimmig = true;
            for (let i = 0; i < r.length; i++) {
                const name = r[i].getAttribute('data-xl-tab');
                const an = r[i].getAttribute('aria-selected') === 'true';
                const offen = !zu(doc, 'xl-panel-' + name);
                if (an !== offen) stimmig = false;
            }
            pruefe(stimmig, 'Zustand ' + (z || '(zu)') + ': Reiter und Panel stimmen');
        }
    }

    console.log('── 5. Der debug-Schalter merkt sich seinen Zustand ─────────────────');
    {
        const { api, speicher } = bau();
        pruefe(api.debugAn() === false, 'Vorgabe ist AUS');
        api.debugSetzen(true);
        pruefe(api.debugAn() === true, 'nach dem Einschalten AN');
        pruefe(speicher['jarvis_xl_debug'] === '1', 'der Zustand ist gespeichert');
        api.debugSetzen(false);
        pruefe(api.debugAn() === false, 'nach dem Ausschalten AUS');
        pruefe(speicher['jarvis_xl_debug'] === '0', '...und das steht auch so da');
    }

    console.log('── 6. debug schaltet ZU, nicht AB ──────────────────────────────────');
    {
        // ⚠ DIE TRAGENDE ZUSAGE. Ein Schalter, der im Normalfall Diagnose
        // WEGNIMMT, macht genau den Bericht unmoeglich, den man hinterher
        // braucht – am 2026-10-23 bestand ein Fenster-Protokoll aus EINER
        // Zeile und war von einem Totalausfall nicht zu unterscheiden.
        const { api } = bau();
        api.debugSetzen(false);
        api.protokoll('pruef', 'immer');
        pruefe(api.log().length === 1,
               'eine gewoehnliche Zeile kommt auch mit debug AUS (' +
               api.log().length + ')');
        api.protokollDebug('pruef', 'nur mit debug');
        pruefe(api.log().length === 1,
               'eine Debug-Zeile kommt mit debug AUS NICHT (' +
               api.log().length + ')');
        api.debugSetzen(true);
        api.protokollDebug('pruef', 'nur mit debug');
        pruefe(api.log().length === 2,
               'mit debug AN kommt sie (' + api.log().length + ')');
        api.protokoll('pruef', 'immer noch');
        pruefe(api.log().length === 3, 'und die gewoehnliche weiterhin');
    }

    console.log('── 7. Eine teure Debug-Zeile wird nur bei Bedarf gebaut ────────────');
    {
        // Sonst kostet die Diagnose auch die, die sie ausgeschaltet haben.
        const { api } = bau();
        api.debugSetzen(false);
        let gebaut = 0;
        api.protokollDebug('pruef', function () { gebaut++; return 'teuer'; });
        pruefe(gebaut === 0, 'mit debug AUS wird der Text nicht gebaut');
        api.debugSetzen(true);
        api.protokollDebug('pruef', function () { gebaut++; return 'teuer'; });
        pruefe(gebaut === 1, 'mit debug AN genau einmal');
        pruefe((api.log()[0] || '').indexOf('teuer') >= 0,
               'und der gebaute Text steht im Protokoll');
    }

    console.log('── 8. Eine werfende Debug-Zeile reisst nichts mit ──────────────────');
    {
        // `protokollDebug` steht in Fehlerzweigen. Wirft es selbst, verschluckt
        // es den Fall, den es erklaeren soll.
        const { api } = bau();
        api.debugSetzen(true);
        let geworfen = null;
        try {
            api.protokollDebug('pruef', function () { throw new Error('kaputt'); });
        } catch (e) { geworfen = e; }
        pruefe(!geworfen, 'ein Wurf im Textbauer wird gefangen');
        pruefe(api.log().length === 0, 'und es landet keine halbe Zeile im Protokoll');
    }

    console.log('── 9. Der Schalter steht IM Protokoll-Reiter ───────────────────────');
    {
        const { doc } = bau();
        const sch = doc.getElementById('xl-debug');
        pruefe(!!sch, 'der Schalter existiert');
        pruefe(sch && sch.type === 'checkbox', 'er ist ein Kaestchen');
        pruefe(sch && !sch.checked, 'er ist im Markup NICHT vorbelegt (Vorgabe aus)');
        const panel = doc.getElementById('xl-panel-proto');
        pruefe(panel && sch && panel.contains(sch),
               'er liegt im Protokoll-Reiter, nicht in den Einstellungen');
        // Beschriftung: der Benutzer muss die WIRKUNG lesen koennen.
        const lab = sch && sch.closest('label');
        const txt = lab ? String(lab.textContent || '') : '';
        pruefe(txt.length > 20, 'er traegt eine erklaerende Beschriftung');
        pruefe(lab && lab.querySelector('[data-i18n]'),
               'die Beschriftung ist uebersetzbar (data-i18n)');
    }

    console.log('── 10. Die Zahl am Reiter bleibt erreichbar ────────────────────────');
    {
        // Sie sagt, ob sich das Aufklappen lohnt – und sie lag vorher im
        // verschachtelten <summary>.
        const { doc, api } = bau();
        const n = doc.getElementById('xl-log-n');
        pruefe(!!n, 'die Zaehleranzeige existiert');
        const tab = doc.querySelector('.xl-tab[data-xl-tab="proto"]');
        pruefe(tab && n && tab.contains(n), 'sie sitzt AM Protokoll-Reiter');
        api.protokoll('pruef', 'eins');
        api.protokoll('pruef', 'zwei');
        pruefe(n.textContent === '2',
               'sie zeigt die Zahl der Zeilen (gefunden: ' + n.textContent + ')');
    }

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
