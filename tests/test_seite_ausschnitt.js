#!/usr/bin/env node
/* Waechter: tests/lib/seite_ausschnitt.js liefert einen Ausschnitt, auf dem
 * eine Probe DASSELBE sieht wie auf der vollen Seite - nur weniger davon.
 *
 * Gemessen wird am geparsten DOM (jsdom), nicht am Text: jsdom normiert beim
 * Parsen, und eine Probe sieht nur den Baum. Zusagen (siehe Kopf des Helfers):
 *   A  das Ziel samt Teilbaum ist knotengleich (outerHTML), der <head> ebenso
 *   B  die Vorfahren tragen dieselben Attribute, closest() trifft sie
 *   C  alles andere faellt weg (Geschwister, Text daneben, Body-Skripte)
 *   D  skripte: true behaelt jedes <script> an seinem Ort
 *   E  eine fehlende id steht in `fehlend` (Positivkontrolle der Aufrufer)
 *   F  ein Ziel IN einem Ziel: das aeussere bleibt ganz
 *   G  an der echten settings.html: je Reiter knotengleich und klein
 *   H  ohneReiter: nur fremde Reiter-Inhalte fallen weg, alles andere bleibt
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const { ausschnitt } = require('./lib/seite_ausschnitt');

let ok = 0, fail = 0, _bilanz = false;
function pruefe(name, cond, detail) {
    if (cond) { ok++; console.log('  OK   ' + name); }
    else { fail++; console.log('  FAIL ' + name + (detail !== undefined ? '  → ' + JSON.stringify(detail) : '')); }
}
function bilanz() {
    _bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
}
process.on('exit', (code) => {
    if (!_bilanz) {
        console.log('\nABBRUCH ohne Bilanz – ' + ok + ' OK, ' + fail + ' FAIL bis dahin');
        if (code === 0) process.exitCode = 1;
    }
});

const PROBE = '<!doctype html><html><head><title>T</title><style>.ka{color:red}</style>'
    + '<script src="/kopf.js"></script></head><body>'
    + '<div id="a" class="ka" hidden data-x="1">Text-A<span id="ax">nachbar</span>'
    + '<section id="b" class="kb" style="display:none"><p>innen <b>fett</b></p><input id="i" value="v"></section></div>'
    + '<div id="c">weg</div><script>var s = 1;</script>'
    + '<div id="d"><script src="/tief.js"></script><span id="dx">weg</span></div></body></html>';
const doc = (h) => new JSDOM(h).window.document;
const ORIG = doc(PROBE);

// Positivkontrolle: die Probeseite traegt alles, was die Pruefungen erwarten.
if (!(ORIG.getElementById('b') && ORIG.getElementById('ax') && ORIG.getElementById('c')
      && ORIG.querySelectorAll('body script').length === 2 && ORIG.head.querySelector('style'))) {
    console.log('ABBRUCH: Probeseite unvollstaendig geparst – Pruefungen waeren trivial');
    process.exit(2);
}

console.log('── A/B/C: Ausschnitt auf #b');
const A1 = ausschnitt(PROBE, ['b']);
const D1 = doc(A1.html);
pruefe('A: nichts fehlend', A1.fehlend.length === 0, A1.fehlend);
pruefe('A: das Ziel ist knotengleich (outerHTML)',
       !!D1.getElementById('b') && D1.getElementById('b').outerHTML === ORIG.getElementById('b').outerHTML,
       D1.getElementById('b') && D1.getElementById('b').outerHTML);
pruefe('A: der <head> ist knotengleich', D1.head.outerHTML === ORIG.head.outerHTML, D1.head.outerHTML);
const a = D1.getElementById('a');
pruefe('B: der Vorfahre ist da, mit denselben Attributen',
       !!a && ['class', 'hidden', 'data-x'].every((n) => a.getAttribute(n) === ORIG.getElementById('a').getAttribute(n)),
       a && a.outerHTML.slice(0, 80));
pruefe('B: closest() vom Ziel trifft den Vorfahren',
       !!D1.getElementById('i') && D1.getElementById('i').closest('.ka') === a);
pruefe('C: Geschwister des Pfads fallen weg (#ax, #c, #d)',
       !D1.getElementById('ax') && !D1.getElementById('c') && !D1.getElementById('d'));
pruefe('C: Text neben dem Pfad faellt weg', D1.body.textContent.indexOf('Text-A') < 0, D1.body.textContent);
pruefe('C: Body-Skripte fallen ohne skripte:true weg', D1.querySelectorAll('body script').length === 0);
pruefe('C: der Ausschnitt ist kuerzer', A1.nachher < A1.vorher, [A1.vorher, A1.nachher]);

console.log('── D: skripte: true');
const D2 = doc(ausschnitt(PROBE, ['b'], { skripte: true }).html);
const quellen = [...D2.querySelectorAll('body script')].map((s) => s.getAttribute('src') || s.textContent);
pruefe('D: jedes Body-Skript bleibt, auch ein tief verschachteltes',
       quellen.length === 2 && quellen.includes('/tief.js') && quellen.includes('var s = 1;'), quellen);
pruefe('D: …an seinem Ort (der Elternteil bleibt als Pfad)',
       !!D2.getElementById('d') && D2.getElementById('d').querySelector('script') !== null
       && !D2.getElementById('dx'));

console.log('── E: fehlende id');
const A3 = ausschnitt(PROBE, ['gibt-es-nicht', 'b']);
pruefe('E: die fehlende id steht in fehlend (und nur sie)',
       A3.fehlend.length === 1 && A3.fehlend[0] === 'gibt-es-nicht', A3.fehlend);

console.log('── F: Ziel in einem Ziel');
const D4 = doc(ausschnitt(PROBE, ['a', 'b']).html);
pruefe('F: das aeussere Ziel bleibt ganz (samt Geschwister des inneren)',
       !!D4.getElementById('a') && D4.getElementById('a').outerHTML === ORIG.getElementById('a').outerHTML);

console.log('── G: echte settings.html');
const HTML = fs.readFileSync(path.join(ROOT, 'frontend', 'settings.html'), 'utf8');
const VOLL = doc(HTML);
// Die FUENF GROESSTEN Reiter (berechnet, keine feste Liste): die Eigenschaft ist
// allgemein, und die groessten sind die am tiefsten verschachtelten. Alle 33
// kosteten 7,5 s - in einem Waechter, der Laufzeit sparen soll.
const REITER = [...VOLL.querySelectorAll('.settings-tab-content[id]')]
    .sort((x, y) => y.outerHTML.length - x.outerHTML.length).slice(0, 5).map((e) => e.id);
if (REITER.length < 5) {
    console.log('ABBRUCH: settings.html ohne erkennbare Reiter (' + REITER.length + ') – Messung waere leer');
    process.exit(2);
}
const ungleich = [], gross = [];
for (const id of REITER) {
    const A = ausschnitt(HTML, [id]);
    const d = doc(A.html);
    const e = d.getElementById(id);
    if (!e || e.outerHTML !== VOLL.getElementById(id).outerHTML || A.fehlend.length) ungleich.push(id);
    if (d.querySelectorAll('*').length * 4 > VOLL.querySelectorAll('*').length) gross.push(id);
}
pruefe(`G: jeder der ${REITER.length} Reiter ist im Ausschnitt knotengleich`, ungleich.length === 0, ungleich);
pruefe('G: jeder Reiter-Ausschnitt hat weniger als ein Viertel der Elemente', gross.length === 0, gross);
pruefe('G: der Kopf von settings.html bleibt knotengleich',
       doc(ausschnitt(HTML, [REITER[0]]).html).head.outerHTML === VOLL.head.outerHTML);

// ── H: ohneReiter - die Gegenrichtung fuer Proben, die app.js ganz laufen lassen
console.log('── H: ohneReiter an einer Probeseite');
const RAHMEN = '<!doctype html><html><head><title>R</title></head><body>'
    + '<div id="maske">Anmeldung</div>'
    + '<div id="modal" class="modal"><div class="kopf"><button class="settings-tab-btn" data-settings-tab="p">P</button>'
    + '<button class="settings-tab-btn" data-settings-tab="q">Q</button></div>'
    + '<div class="modal-body"><div id="tab-p" class="settings-tab-content active"><input id="pi" value="1"></div>'
    + '<div id="tab-q" class="settings-tab-content"><span id="qi">fremd</span></div>'
    + '<div id="neben" class="vis-modal">bleibt</div><script>var r = 1;</script>'
    + '<section><div id="tab-tief" class="settings-tab-content gross">tief</div></section></div></div></body></html>';
const RORIG = doc(RAHMEN);
const { ohneReiter } = require('./lib/seite_ausschnitt');
const H1 = ohneReiter(RAHMEN, ['tab-p']);
const HD = doc(H1.html);
pruefe('H: nichts fehlend', H1.fehlend.length === 0, H1.fehlend);
pruefe('H: der behaltene Reiter ist knotengleich',
       !!HD.getElementById('tab-p') && HD.getElementById('tab-p').outerHTML === RORIG.getElementById('tab-p').outerHTML);
pruefe('H: fremde Reiter fallen weg, auch ein tief verschachtelter',
       !HD.getElementById('tab-q') && !HD.getElementById('qi') && !HD.getElementById('tab-tief'));
pruefe('H: entfernt nennt genau die fremden Reiter',
       H1.entfernt.slice().sort().join(',') === 'tab-q,tab-tief', H1.entfernt);
pruefe('H: alles ausserhalb der Reiter bleibt (Maske, Reiterleiste, Nachbar, Skript, Kopf)',
       !!HD.getElementById('maske') && HD.querySelectorAll('.settings-tab-btn').length === 2
       && !!HD.getElementById('neben') && HD.querySelectorAll('body script').length === 1
       && HD.head.outerHTML === RORIG.head.outerHTML);
pruefe('H: der Rahmen um die Reiter traegt seine Attribute',
       !!HD.getElementById('modal') && HD.getElementById('modal').className === 'modal');
const H2 = ohneReiter(RAHMEN, ['tab-p', 'gibt-es-nicht']);
pruefe('H: die fehlende id steht in fehlend (und nur sie)',
       H2.fehlend.length === 1 && H2.fehlend[0] === 'gibt-es-nicht', H2.fehlend);

console.log('── H: ohneReiter an der echten settings.html');
const HS = ohneReiter(HTML, [REITER[0]]);
const HSD = doc(HS.html);
const inFremdemReiter = (e) => { const r = e.closest('.settings-tab-content'); return !!r && r.id !== REITER[0]; };
const vermisst = [...VOLL.querySelectorAll('[id]')]
    .filter((e) => !inFremdemReiter(e) && !HSD.getElementById(e.id)).map((e) => e.id);
pruefe('H: jedes Element mit id ausserhalb fremder Reiter ist noch da', vermisst.length === 0, vermisst.slice(0, 5));
pruefe('H: der behaltene Reiter ist knotengleich',
       !!HSD.getElementById(REITER[0])
       && HSD.getElementById(REITER[0]).outerHTML === VOLL.getElementById(REITER[0]).outerHTML);
pruefe('H: kein fremder Reiter bleibt stehen',
       HSD.querySelectorAll('.settings-tab-content').length === 1
       && HS.entfernt.length === VOLL.querySelectorAll('.settings-tab-content').length - 1,
       [HSD.querySelectorAll('.settings-tab-content').length, HS.entfernt.length]);
pruefe('H: die Seite hat weniger als die Haelfte der Elemente',
       HSD.querySelectorAll('*').length * 2 < VOLL.querySelectorAll('*').length,
       [HSD.querySelectorAll('*').length, VOLL.querySelectorAll('*').length]);

console.log('── H: ohneReiter mit huelle: true');
const HH = ohneReiter(RAHMEN, ['tab-p'], { huelle: true });
const HHD = doc(HH.html);
const q = HHD.getElementById('tab-q');
pruefe('H/huelle: der fremde Reiter steht noch da, mit seinen Attributen',
       !!q && q.className === 'settings-tab-content' && !!HHD.getElementById('tab-tief')
       && HHD.getElementById('tab-tief').className === 'settings-tab-content gross');
pruefe('H/huelle: ...aber leer (kein Kind, kein Text)',
       !!q && q.childNodes.length === 0 && !HHD.getElementById('qi')
       && HHD.getElementById('tab-tief').childNodes.length === 0);
pruefe('H/huelle: der behaltene Reiter bleibt knotengleich',
       !!HHD.getElementById('tab-p') && HHD.getElementById('tab-p').outerHTML === RORIG.getElementById('tab-p').outerHTML);
pruefe('H/huelle: entfernt nennt die geleerten Reiter',
       HH.entfernt.slice().sort().join(',') === 'tab-q,tab-tief', HH.entfernt);
const HSH = doc(ohneReiter(HTML, [], { huelle: true }).html);
const alleReiter = [...VOLL.querySelectorAll('.settings-tab-content[id]')].map((e) => e.id);
const huellenFehlen = alleReiter.filter((id) => !HSH.getElementById(id));
pruefe('H/huelle: an der echten settings.html steht JEDER Reiter als Element', huellenFehlen.length === 0
       && alleReiter.length >= 5, huellenFehlen.slice(0, 5));
pruefe('H/huelle: ...und jeder ist leer',
       [...HSH.querySelectorAll('.settings-tab-content')].every((e) => e.childNodes.length === 0));

console.log('── I: mitReitern (JSDOM-Huelle)');
const { mitReitern } = require('./lib/seite_ausschnitt');
const M = mitReitern(require('./lib/jsdom_laden')(), ['tab-p']);
// Ein Abbruch der Huelle (Exit 2 bei fehlendem Reiter) wird HIER zur FAIL-Zeile:
// ist ohneReiter kaputt, soll das als Befund mit Bilanz enden, nicht als Abbruch
// des ganzen Waechters (Register: ein Absturz ist kein Biss).
let MD = null;
{
    const _exit = process.exit;
    process.exit = (c) => { throw new Error('Exit ' + c); };
    try { MD = new M.JSDOM(RAHMEN).window.document; }
    catch (e) { pruefe('I: die Huelle baut die Probeseite auf', false, String(e.message)); }
    finally { process.exit = _exit; }
}
if (!MD) MD = doc('<!doctype html><html><body></body></html>');
pruefe('I: eine Seite mit Reitern wird gekuerzt (fremder Reiter weg, eigener da)',
       !MD.getElementById('tab-q') && !MD.getElementById('tab-tief') && !!MD.getElementById('tab-p')
       && MD.getElementById('tab-p').outerHTML === RORIG.getElementById('tab-p').outerHTML);
pruefe('I: ...alles ausserhalb bleibt (Maske, Knoepfe, Nachbar)',
       !!MD.getElementById('maske') && MD.querySelectorAll('.settings-tab-btn').length === 2 && !!MD.getElementById('neben'));
const OHNE = '<!doctype html><html><head></head><body><div id="x" class="y">z</div></body></html>';
pruefe('I: eine Seite ohne Reiter geht unveraendert durch',
       new M.JSDOM(OHNE).window.document.documentElement.outerHTML === doc(OHNE).documentElement.outerHTML);
pruefe('I: der Zaehler nennt Aufbauten und Kuerzungen', M.ausschnittZaehler.aufbauten === 2
       && M.ausschnittZaehler.gekuerzt === 1, JSON.stringify(M.ausschnittZaehler));
pruefe('I: die Klasse bleibt ein JSDOM (instanceof, statische Methoden)',
       new M.JSDOM(OHNE) instanceof JSDOM && typeof M.JSDOM.fragment === 'function');
const kind = require('child_process').spawnSync(process.execPath, ['-e',
    "const {mitReitern}=require('./tests/lib/seite_ausschnitt');"
    + "const M=mitReitern(require('./tests/lib/jsdom_laden')(),['gibt-es-nicht']);"
    + "new M.JSDOM('<div class=\"settings-tab-content\" id=\"a\"></div>');console.log('weiter')"],
    { cwd: ROOT, encoding: 'utf8' });
pruefe('I: fehlt ein behaltener Reiter, endet der Lauf mit Exit 2 (nicht leer gruen)',
       kind.status === 2 && /ABBRUCH/.test(kind.stdout) && !/weiter/.test(kind.stdout), [kind.status, kind.stdout.slice(0, 120)]);

bilanz();
process.exit(fail === 0 ? 0 : 1);
