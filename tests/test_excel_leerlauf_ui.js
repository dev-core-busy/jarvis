#!/usr/bin/env node
/* Waechter: das Fenster erklaert einen Lauf ohne Ergebnis – GEMESSEN, nicht gelesen.
 *
 * `tests/test_excel_leerlauf.py` prueft die Backend-Seite und am Fenster nur
 * VORKOMMEN. Genau das hat zwei Gegenproben stumm bleiben lassen: eine
 * Sabotage `if (false) protokoll('lauf', …)` laesst den gesuchten Text stehen,
 * und `if (false && d.grund === 'modell_stumm')` ebenso. Beide Zusagen werden
 * deshalb HIER ausgefuehrt:
 *
 *   1. `laufProtokollieren` schreibt je Runde eine Zeile, die den Lauf erklaert.
 *   2. `fertig` unterscheidet die Gruende und beschuldigt nicht den Benutzer.
 *
 * Die echten Funktionen werden geschnitten und wirklich aufgerufen.
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const JS = fs.readFileSync(path.join(ROOT, 'frontend/excel-addin/excel.js'), 'utf8');

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
for (const t of ['laufProtokollieren', 'fertig']) {
    code[t] = schneide(t);
    if (!code[t]) abbruch('Funktion ' + t + ' nicht schneidbar');
}

/* ── Prolog ────────────────────────────────────────────────────────────────
   `fertig` ruft Nachbarn, die hier nicht zur Sache gehoeren (Diff-Aufbau,
   Auto-Uebernahme). Sie werden als leere Attrappen gestellt – NICHT
   weggelassen: ein fehlender Name wirft, und der Wurf landete in einem
   `catch`, womit die Messung "0 Meldungen" ergaebe und wie ein Befund
   aussaehe (Register: eine Attrappe mit weniger als dem Original stirbt beim
   naechsten Symbol). */
function laufen(fnName, arg1, arg2) {
    const protokolle = [];
    const sandbox = {
        protokoll: function (bereich, text) {
            protokolle.push(bereich + ': ' + text);
        },
        T: function (k, f) { return f; },
        zeichneVerlauf: function () { },
        alteWerteLesen: function () { return Promise.resolve(); },
        uebernehmenJetzt: function () { },
        Promise: Promise,
        Object: Object,
        String: String
    };
    const namen = Object.keys(sandbox);
    // ⚠ `_verlauf` UND `_vorschlag` SIND CLOSURE-VARIABLEN, KEINE PARAMETER.
    // `fertig` beginnt mit `_verlauf = _verlauf.filter(…)` – es ERSETZT das
    // Array. Als Parameter uebergeben traf die Zuweisung nur die lokale Kopie,
    // mein aeusseres Array blieb leer, und ZEHN Pruefungen meldeten einen
    // Fehler, den es im Produkt nicht gab (darunter die Positivkontrolle –
    // daran war es zu erkennen). Dieselbe Klasse wie die ContextVar-Lehre im
    // Register: wer einen Wert ersetzt statt die Liste zu fuellen, muss ueber
    // die Variable gelesen werden, nicht ueber die alte Referenz.
    // eslint-disable-next-line no-new-func
    const fn = new Function(...namen,
        'var _verlauf = []; var _vorschlag = null;' +
        'function autoAn() { return false; }' +
        code.laufProtokollieren + '\n' + code.fertig +
        '\nreturn { laufProtokollieren: laufProtokollieren, fertig: fertig,' +
        ' verlauf: function () { return _verlauf; } };');
    const api = fn(...namen.map((n) => sandbox[n]));
    api[fnName](arg1, arg2);
    return { protokolle, verlauf: api.verlauf() };
}

(function () {
    console.log('── 1. Jeder Lauf hinterlaesst eine erklaerende Zeile ───────────────');
    {
        const r = laufen('laufProtokollieren',
            { max_runden: 3, text: 'Hallo', aenderungen: [1, 2],
              abgelehnt: [], brauche: [], verworfen: [], grund: '', rohlaenge: 42 }, 2);
        pruefe(r.protokolle.length === 1,
               'genau eine Zeile (gezaehlt: ' + r.protokolle.length + ')');
        const z = r.protokolle[0] || '';
        pruefe(z.indexOf('lauf:') === 0, 'sie gehoert zum Bereich "lauf"');
        pruefe(/runde 2\/3/.test(z), 'sie nennt Runde und Deckel (' + z + ')');
        pruefe(/text=5 Zeichen/.test(z), 'sie nennt die Textlaenge');
        pruefe(/eintraege=2/.test(z), 'sie nennt die Zahl der Eintraege');
        pruefe(/roh=42/.test(z), 'sie nennt die Rohlaenge');
    }

    console.log('── 2. Der gemeldete Fall ist aus der Zeile ABLESBAR ────────────────');
    {
        // Genau die Lage vom 2026-10-23: nichts kam an, die Nachforderung
        // wurde verworfen. Ohne diese Zeile stand im Protokoll NUR
        // "Excel bereit".
        const r = laufen('laufProtokollieren',
            { max_runden: 3, text: '', aenderungen: [], abgelehnt: [],
              brauche: [], verworfen: ['2026!AO20:IH21'],
              grund: 'runden_erschoepft', rohlaenge: 33 }, 3);
        const z = r.protokolle[0] || '';
        pruefe(/runde 3\/3/.test(z), 'die erschoepfte Runde steht da');
        pruefe(/text=0 Zeichen/.test(z), 'die leere Antwort steht da');
        pruefe(z.indexOf('VERWORFEN=2026!AO20:IH21') >= 0,
               'die verworfene Nachforderung steht da (' + z + ')');
        pruefe(z.indexOf('grund=runden_erschoepft') >= 0, 'der Grund steht da');
        pruefe(/roh=33/.test(z),
               'die Rohlaenge zeigt, dass das Modell NICHT stumm war');
    }

    console.log('── 3. Eine Nachforderung im Normalfall ist sichtbar ────────────────');
    {
        const r = laufen('laufProtokollieren',
            { max_runden: 3, text: '', aenderungen: [],
              brauche: ['2026!AO20:IH21'], rohlaenge: 33 }, 1);
        const z = r.protokolle[0] || '';
        pruefe(z.indexOf('braucht=2026!AO20:IH21') >= 0,
               'die laufende Nachforderung steht da');
        pruefe(z.indexOf('VERWORFEN') < 0,
               'sie wird NICHT als verworfen gemeldet');
    }

    console.log('── 4. Ein leeres Argument bricht die Zeile nicht ───────────────────');
    {
        // ⚠ `fertig` wird auch aus Fehlerzweigen gerufen. Eine Protokollzeile,
        // die selbst wirft, verschluckt den Fall, den sie erklaeren soll.
        let geworfen = null;
        try { laufen('laufProtokollieren', undefined, 1); } catch (e) { geworfen = e; }
        pruefe(!geworfen, 'laufProtokollieren(undefined) wirft nicht' +
               (geworfen ? ' (' + geworfen.message + ')' : ''));
    }

    console.log('── 5. fertig() unterscheidet die Gruende WIRKLICH ──────────────────');
    {
        const fall = (grund) => {
            const r = laufen('fertig', { text: '', aenderungen: [], grund: grund });
            const m = r.verlauf.filter((x) => x.rolle === 'bot');
            return m.length ? String(m[m.length - 1].text || '') : '';
        };
        const stumm = fall('modell_stumm');
        const marker = fall('nur_marker');
        const unbekannt = fall('');
        pruefe(stumm.length > 0, 'bei modell_stumm kommt eine Meldung');
        pruefe(marker.length > 0, 'bei nur_marker kommt eine Meldung');
        pruefe(unbekannt.length > 0, 'ohne Grund kommt eine Meldung');
        // ⚠ DIE DREI MUESSEN VERSCHIEDEN SEIN. Genau das konnte die
        // Vorkommens-Pruefung nicht sehen: mit abgeschalteter Verzweigung
        // kommt dreimal derselbe Text, und der Quelltext sah unveraendert aus.
        pruefe(stumm !== unbekannt,
               'modell_stumm unterscheidet sich vom Standardfall');
        pruefe(marker !== unbekannt,
               'nur_marker unterscheidet sich vom Standardfall');
        pruefe(stumm !== marker, 'modell_stumm und nur_marker unterscheiden sich');
        // Und keiner davon schiebt die Schuld auf die Frage.
        for (const [name, txt] of [['modell_stumm', stumm],
                                   ['nur_marker', marker],
                                   ['Standardfall', unbekannt]]) {
            pruefe(txt.indexOf('Formuliere die Frage bitte anders') < 0,
                   name + ' enthaelt nicht die alte Schuldzuweisung');
        }
        pruefe(stumm.indexOf('liegt nicht an deiner Frage') >= 0,
               'modell_stumm weist die Schuld ausdruecklich ab');
        pruefe(marker.indexOf('auf unserer Seite') >= 0,
               'nur_marker benennt den Fehler als unseren');
        pruefe(unbekannt.indexOf('muss nicht an deiner Frage liegen') >= 0,
               'der Standardfall relativiert');
    }

    console.log('── 6. Mit Inhalt kommt KEINE Fehlermeldung ─────────────────────────');
    {
        const r1 = laufen('fertig', { text: 'Fertig.', aenderungen: [] });
        pruefe(!r1.verlauf.some((x) => x.fehler),
               'bei vorhandenem Text keine Fehlermeldung');
        const r2 = laufen('fertig', { text: '', aenderungen: [] });
        pruefe(r2.verlauf.some((x) => x.fehler),
               'bei gar nichts schon (Positivkontrolle der Messung)');
    }

    bilanz = true;
    console.log('\nErgebnis: ' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
