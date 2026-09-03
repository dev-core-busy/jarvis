#!/usr/bin/env node
/**
 * Waechter: der Abruf-Schluessel muss an JEDER Aufrufstelle in REICHWEITE sein.
 *
 * DER VORFALL (2026-09-02, gemeldet 2026-09-03 als "unter /portal -> Dokumente
 * sind die 6 Dokumente nicht sichtbar"): bei der Umstellung von `?token=` auf
 * den Abruf-Schluessel wurde der Helfer `_dlk()` in VIER Dateien mitten in eine
 * andere Funktion hineingeschrieben – `info_files.js` und `tracks.js` in
 * `token()`, `issues.js` in `_token()`, `vision.js` in `_feedTick()`. Das ist
 * syntaktisch einwandfrei (eine verschachtelte Funktionsdeklaration), aber der
 * Helfer ist damit nur INNERHALB jener Funktion sichtbar. Jede Aufrufstelle
 * ausserhalb lief in einen `ReferenceError` – und der wurde vom `catch` der
 * Ladefunktion verschluckt: das Panel blieb leer, ohne Fehlermeldung, ohne
 * 500er, ohne Konsolenausgabe an einer Stelle, die jemand ansieht.
 * Betroffen waren 10 Aufrufstellen: Dokumente-Panel, Short-Tracks-Downloads,
 * Meldungs-Anhaenge und fuenf der sechs Vision-Medienstellen.
 *
 * ⚠ WARUM DER BESTEHENDE WAECHTER DAS NICHT FAND – das ist die eigentliche
 * Lehre: `tests/test_download_key.py` prueft die REGEL "jede `?token=`-Stelle
 * muss aus dem Abruf-Schluessel gespeist sein" am QUELLTEXT. Der Aufruf
 * `_dlk()` steht dort ja – er ist nur nicht erreichbar. Ein Waechter, der ein
 * VORKOMMEN prueft, kann eine Sichtbarkeitsfrage nicht beantworten. Dieser
 * Test messt sie deshalb am ECHTEN SYNTAXBAUM (acorn), nicht an der
 * Einrueckung und nicht am Text.
 *
 * Aufruf:  node tests/test_dlkey_reichweite.js
 * Exit 0 = alles in Reichweite · 1 = Fehlschlag · 2 = konnte nicht laufen
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let ok = 0, fail = 0;

function abschnitt(t) { console.log(`\n\x1b[1m${t}\x1b[0m`); }
function pruefe(name, bedingung, detail) {
    if (bedingung) { ok++; console.log(`  \x1b[32m✓\x1b[0m ${name}`); }
    else { fail++; console.log(`  \x1b[31m✗\x1b[0m ${name}${detail ? '  →  ' + detail : ''}`); }
}

// Ohne Parser gibt es keine Aussage – und "konnte nicht laufen" darf NIE wie
// "bestanden" aussehen (deshalb Exit 2, nicht 0). acorn kommt mit jsdom, das
// die uebrigen UI-Tests ohnehin brauchen.
/* Beide Module werden an zwei Orten gesucht: im Projekt (node_modules) und
 * unter /tmp/node_modules – das ist die historische Ablage, auf die die
 * uebrigen UI-Tests dieses Projekts ueber JSDOM_PATH zeigen. Ohne den zweiten
 * Ort laeuft der Test auf einem Rechner nicht, auf dem die anderen laufen. */
function hole(name) {
    // Reihenfolge: ausdrueckliche Vorgabe · normale Aufloesung · die drei Orte,
    // an denen die Module in diesem Projekt tatsaechlich liegen (lokal
    // node_modules, auf DEV data/node_modules bzw. /usr/share/nodejs).
    const orte = [process.env[name.toUpperCase() + '_PATH'], name,
                  path.join(ROOT, 'data/node_modules', name),
                  '/tmp/node_modules/' + name,
                  '/usr/share/nodejs/' + name];
    for (const kandidat of orte) {
        if (!kandidat) continue;
        try { return require(kandidat); } catch (e) { /* naechster Ort */ }
    }
    return null;
}

const acorn = hole('acorn');
if (!acorn) {
    console.log('\x1b[31mABBRUCH\x1b[0m: acorn nicht verfuegbar – ohne Parser ist die '
        + 'Reichweite nicht messbar (npm i acorn, oder jsdom installieren).');
    process.exit(2);
}

/* ── Werkzeug: Baum durchlaufen mit Elternkette ───────────────────────────── */
const FUNKTIONEN = ['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'];
const THIS_BINDER = ['FunctionDeclaration', 'FunctionExpression'];  // Arrow bindet `this` NICHT neu

function lauf(knoten, eltern, cb) {
    if (!knoten || typeof knoten.type !== 'string') return;
    cb(knoten, eltern);
    const k = eltern.concat([knoten]);
    for (const feld of Object.keys(knoten)) {
        if (feld === 'type' || feld === 'start' || feld === 'end' || feld === 'loc') continue;
        const v = knoten[feld];
        if (Array.isArray(v)) {
            for (const x of v) if (x && typeof x.type === 'string') lauf(x, k, cb);
        } else if (v && typeof v.type === 'string') lauf(v, k, cb);
    }
}

/* Bindet zwischen Aufrufstelle und Methodenrumpf etwas `this` NEU?
 *
 * Eine Arrow-Funktion ist fuer `this` durchsichtig, eine `function`-Expression
 * bzw. -Deklaration nicht: darin waere `this._dlk` `undefined` – derselbe
 * Ausfall wie ein ReferenceError, nur einen Schritt spaeter.
 *
 * ⚠ DER METHODENRUMPF SELBST IST IM BAUM EINE `FunctionExpression` (das `value`
 * der MethodDefinition). Wer ihn mitzaehlt, meldet JEDE Aufrufstelle als
 * Fehler – genau das tat die erste Fassung dieses Waechters. Deshalb wird die
 * Kette von innen nach aussen gelesen und beim eigenen Rumpf ABGEBROCHEN. */
function thisUmgebunden(kette) {
    for (let i = kette.length - 1; i >= 0; i--) {
        const n = kette[i], eltern = kette[i - 1];
        if (n.type === 'ArrowFunctionExpression') continue;
        if (n.type === 'FunctionExpression') {
            const istRumpf = eltern && (eltern.type === 'MethodDefinition'
                || eltern.type === 'PropertyDefinition' || eltern.type === 'Property')
                && eltern.value === n;
            if (istRumpf) return null;            // Methode erreicht, alles gut
            return { zeile: n.loc.start.line };
        }
        if (n.type === 'FunctionDeclaration') return { zeile: n.loc.start.line };
        if (n.type === 'ClassBody') return null;
    }
    return null;
}

/* Alle .js unter frontend/ – die Regel gilt auch fuer eine Datei, die es heute
 * noch nicht gibt; eine gepflegte Liste waere beim naechsten Feature blind. */
function jsDateien() {
    const out = [];
    (function ab(d) {
        for (const e of fs.readdirSync(d, { withFileTypes: true })) {
            const p = path.join(d, e.name);
            if (e.isDirectory()) { if (e.name !== 'node_modules' && e.name !== 'vendor') ab(p); }
            else if (e.name.endsWith('.js')) out.push(p);
        }
    })(path.join(ROOT, 'frontend'));
    return out.sort();
}

const rel = (p) => path.relative(ROOT, p);

/* ── Analyse EINER Datei ──────────────────────────────────────────────────── */
function analysiere(datei) {
    const quelle = fs.readFileSync(datei, 'utf8');
    if (!/\b_dlk\b/.test(quelle)) return null;      // Datei ohne Schluessel-Helfer
    let baum;
    try { baum = acorn.parse(quelle, { ecmaVersion: 2022, locations: true }); }
    catch (e) { return { parseFehler: e.message }; }

    const frei = [];      // Deklarationen, die einen Scope aufspannen: function _dlk(){} / var _dlk = ...
    const methoden = [];  // this._dlk: Methode bzw. Klassenfeld
    const refFrei = [];   // Aufrufe als nackter Name
    const refThis = [];   // Aufrufe als this._dlk

    lauf(baum, [], (n, eltern) => {
        // ── Deklarationen ──
        if (n.type === 'FunctionDeclaration' && n.id && n.id.name === '_dlk') {
            // Eine Funktionsdeklaration wird in den naechsten Funktions- bzw.
            // Programm-Scope gehoben – ein Block dazwischen ist unerheblich.
            const scope = eltern.slice().reverse()
                .find((x) => FUNKTIONEN.includes(x.type) || x.type === 'Program');
            frei.push({ zeile: n.loc.start.line, scope });
        }
        if (n.type === 'VariableDeclarator' && n.id.type === 'Identifier' && n.id.name === '_dlk') {
            const scope = eltern.slice().reverse()
                .find((x) => FUNKTIONEN.includes(x.type) || x.type === 'Program');
            frei.push({ zeile: n.loc.start.line, scope });
        }
        if ((n.type === 'MethodDefinition' || n.type === 'PropertyDefinition' || n.type === 'Property')
            && n.key && (n.key.name === '_dlk' || n.key.value === '_dlk')) {
            const klasse = eltern.slice().reverse()
                .find((x) => x.type === 'ClassDeclaration' || x.type === 'ClassExpression'
                          || x.type === 'ObjectExpression');
            methoden.push({ zeile: n.loc.start.line, traeger: klasse });
        }
        // ── Aufrufstellen ──
        if (n.type === 'Identifier' && n.name === '_dlk') {
            const p = eltern[eltern.length - 1];
            if (!p) return;
            if (p.type === 'FunctionDeclaration' && p.id === n) return;          // der Name selbst
            if (p.type === 'VariableDeclarator' && p.id === n) return;
            if (p.type === 'MethodDefinition' || p.type === 'PropertyDefinition'
                || p.type === 'Property') return;                                 // Schluessel selbst
            if (p.type === 'MemberExpression' && p.property === n) {
                // this._dlk(...) bzw. irgendwas._dlk(...)
                const istThis = p.object && p.object.type === 'ThisExpression';
                refThis.push({ zeile: n.loc.start.line, start: n.start, istThis, kette: eltern.slice() });
                return;
            }
            refFrei.push({ zeile: n.loc.start.line, start: n.start });
        }
    });

    return { frei, methoden, refFrei, refThis, baum, quelle };
}

/* ── Teil 1: Reichweite je Aufrufstelle ───────────────────────────────────── */
abschnitt('1. Der Abruf-Schluessel ist an jeder Aufrufstelle erreichbar');

const betroffen = [];
for (const datei of jsDateien()) {
    const a = analysiere(datei);
    if (!a) continue;
    const name = rel(datei);
    if (a.parseFehler) { pruefe(`${name}: parsebar`, false, a.parseFehler); continue; }
    betroffen.push({ name, a });

    // (a) nackter Aufruf `_dlk()` – braucht eine Deklaration im umgebenden Scope
    for (const r of a.refFrei) {
        const sichtbar = a.frei.some((d) => d.scope && r.start >= d.scope.start && r.start < d.scope.end);
        pruefe(`${name}:${r.zeile}  _dlk() ist in Reichweite`, sichtbar,
            a.frei.length
                ? 'Definition liegt in Zeile ' + a.frei.map((d) => d.zeile).join('/')
                  + ' und spannt diese Stelle nicht ein → ReferenceError'
                : 'keine Deklaration von _dlk in dieser Datei → ReferenceError');
    }

    // (b) `this._dlk()` – Traeger muss die Methode haben, und zwischen Aufruf
    //     und Methode darf keine `function`-Expression liegen: die bindet `this`
    //     neu, und dann ist `this._dlk` `undefined` (derselbe Ausfall, nur ein
    //     Schritt spaeter).
    for (const r of a.refThis) {
        if (!r.istThis) continue;                 // fremdes Objekt – nicht unsere Regel
        pruefe(`${name}:${r.zeile}  this._dlk() – der Traeger fuehrt die Methode`,
            a.methoden.length > 0, 'keine Methode/kein Feld _dlk gefunden');
        pruefe(`${name}:${r.zeile}  this ist noch das Objekt (kein function-Rumpf dazwischen)`,
            !thisUmgebunden(r.kette), 'Zeile ' + (thisUmgebunden(r.kette) || {zeile: '?'}).zeile);
    }
}

/* ── Teil 2: Positivkontrolle – der Waechter darf nicht ins Leere pruefen ── */
abschnitt('2. Positivkontrolle');
pruefe('es wurden Dateien mit Abruf-Schluessel gefunden', betroffen.length > 0,
    'keine einzige – dann prueft Teil 1 nichts');
const summe = betroffen.reduce((s, b) => s + b.a.refFrei.length + b.a.refThis.length, 0);
pruefe('es wurden Aufrufstellen gefunden', summe > 0, 'gefunden: ' + summe);
for (const b of betroffen) {
    pruefe(`${b.name}: mindestens eine Aufrufstelle erkannt`,
        (b.a.refFrei.length + b.a.refThis.length) > 0);
}

/* ── Teil 3: Regel – wer `?token=` baut, braucht eine Schluessel-Quelle ──── */
abschnitt('3. Regel: jede ?token=-Adresse wird aus dem Abruf-Schluessel gespeist');
// Umgekehrt formuliert, wie der Python-Waechter: nicht "welche Namen sind
// verboten", sondern "diese Stelle MUSS aus JarvisDL kommen". Hier zusaetzlich
// mit der Reichweite-Frage aus Teil 1 verbunden.
for (const datei of jsDateien()) {
    const quelle = fs.readFileSync(datei, 'utf8');
    const name = rel(datei);
    // Zeilen, die eine Adresse mit ?token=/&token= zusammensetzen (keine
    // Kommentare – sonst liest der Waechter seine eigene Begruendung).
    const zeilen = quelle.split('\n').filter((z) => {
        const t = z.trim();
        if (t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) return false;
        return /[?&]token=/.test(z);
    });
    if (!zeilen.length) continue;
    // vnc.js ist ausgenommen und begruendet: ein WebSocket hat einen eigenen
    // Auth-Weg, und seine Adresse kopiert niemand in eine Mail.
    if (name.endsWith('js/vnc.js')) continue;
    const hatQuelle = /\b_dlk\s*\(|JarvisDL/.test(quelle);
    pruefe(`${name}: hat eine Schluessel-Quelle (${zeilen.length} Adress-Stelle(n))`, hatQuelle,
        'weder _dlk() noch JarvisDL in der Datei');
}

/* ── Teil 4: der gemeldete Fall, funktional gemessen ─────────────────────────
 *
 * Nicht die Schreibweise, sondern das ERGEBNIS: der ECHTE `info_files.js` laeuft
 * gegen die ECHTE `portal.html` und muss aus sechs gemeldeten Dateien sechs
 * Eintraege zeichnen. Der Altstand zeichnet null – und zwar STILL, weil der
 * ReferenceError im `catch` der Ladefunktion landet. Genau deshalb genuegt hier
 * keine Quelltext-Pruefung. */
abschnitt('4. Der gemeldete Fall: das Dokumente-Panel zeichnet seine Eintraege');

const jsdomModul = hole('jsdom');
const JSDOM = jsdomModul && jsdomModul.JSDOM;
if (!JSDOM) {
    console.log('\x1b[31mABBRUCH\x1b[0m: jsdom nicht verfuegbar – Teil 4 kann nicht messen.');
    process.exit(2);
}

const DATEIEN = [
    { name: 'Benutzerhandbuch.20260811.pdf', kind: 'pdf', size: 20346908 },
    { name: 'ChatTutorial.pdf', kind: 'pdf', size: 997007 },
    { name: 'KI-Systeme_Ueberblick_v1_29072026.pdf', kind: 'pdf', size: 1608279 },
    { name: 'llm-monitor.url', kind: 'link', size: 54, url: 'https://example.invalid/monitor', label: 'llm-monitor' },
    { name: 'Pull-Sync-Leitfaden.pdf', kind: 'pdf', size: 209238 },
    { name: 'Übersicht der KIM Komponenten.pdf', kind: 'pdf', size: 93415 }
];

(async function () {
    const html = fs.readFileSync(path.join(ROOT, 'frontend/portal.html'), 'utf8');
    const dom = new JSDOM(html, { url: 'https://localhost/portal', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'benutzer:1:abc');
    // Der Schluessel kommt aus dlkey.js; hier als Attrappe, damit die Adresse
    // nachweislich den ABRUF-Schluessel traegt und nicht das Sitzungstoken.
    w.JarvisDL = { schluessel: () => 'JDL1.probe', url: (u) => u + '?token=JDL1.probe' };
    let abrufe = 0;
    w.fetch = function (u) {
        abrufe++;
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ files: DATEIEN }) });
    };
    w.eval(fs.readFileSync(path.join(ROOT, 'frontend/js/info_files.js'), 'utf8'));
    await new Promise((r) => setTimeout(r, 30));

    const d = w.document;
    const wrap = d.getElementById('pt-info-wrap');
    const eintraege = d.querySelectorAll('#pt-info-list .pt-info-item');
    pruefe('der Abruf ist gelaufen', abrufe > 0, 'Abrufe: ' + abrufe);
    pruefe('das Ordnersymbol ist sichtbar', wrap && wrap.style.display !== 'none',
        wrap ? 'display=' + wrap.style.display : 'kein #pt-info-wrap');
    pruefe(`alle ${DATEIEN.length} Dokumente sind gezeichnet`,
        eintraege.length === DATEIEN.length, 'gezeichnet: ' + eintraege.length);
    pruefe('der Zaehler nennt die Anzahl',
        (d.getElementById('pt-info-count').textContent || '').indexOf(String(DATEIEN.length)) === 0,
        'Zaehler: ' + d.getElementById('pt-info-count').textContent);

    // Die Adresse muss den ABRUF-Schluessel tragen, nicht das Sitzungstoken –
    // das ist die Zusage vom 2026-09-02, und sie war mit dem ReferenceError
    // ebenfalls nicht eingeloest (es kam gar keine Adresse zustande).
    const datei = Array.from(eintraege).find((a) => /\.pdf(\?|$)/.test(a.getAttribute('href')));
    pruefe('eine Datei-Adresse traegt den Abruf-Schluessel',
        !!datei && /token=JDL1\.probe/.test(datei.getAttribute('href')),
        datei ? datei.getAttribute('href') : 'keine Datei-Adresse');
    // ⚠ MIT `eintraege.length` – ohne diese Haelfte ist die Aussage im
    // Fehlerfall TRIVIAL WAHR: zeichnet nichts, traegt auch nichts.
    pruefe('keine Datei-Adresse traegt das Sitzungstoken',
        eintraege.length > 0
        && !Array.from(eintraege).some((a) => /token=benutzer%3A1/.test(a.getAttribute('href') || '')));
    // Die Verknuepfung zeigt auf ihr Ziel, nicht auf den Abruf-Endpunkt.
    const link = Array.from(eintraege).find((a) => (a.getAttribute('href') || '').startsWith('https://example.invalid'));
    pruefe('die Verknuepfung zeigt auf ihr Ziel', !!link,
        Array.from(eintraege).map((a) => a.getAttribute('href')).join(' | '));

    w.close();
    console.log(`\n\x1b[1mErgebnis: ${ok}/${ok + fail}\x1b[0m`);
    process.exit(fail === 0 ? 0 : 1);
})();
