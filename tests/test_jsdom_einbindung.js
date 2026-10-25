#!/usr/bin/env node
/* Waechter: JEDER JS-Waechter, der jsdom braucht, bindet es ueber die
 * gemeinsame Quelle ein – und endet bei fehlendem jsdom mit Exit 2.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT (gemessen am 2026-09-30, vor dem Umbau):
 * von 55 Dateien in tests/*.js, die jsdom laden, liefen nur 24. 14 starben mit
 * MODULE_NOT_FOUND, Stacktrace und Exit 1 – und Exit 1 ist die Sprache, in der
 * ein Waechter "ich beisse" sagt. "Konnte nicht laufen" war damit von einem
 * echten Befund nicht zu unterscheiden. Die anderen 15 brachen mit Exit 2 und
 * der Meldung "jsdom nicht installiert" ab, OBWOHL jsdom im Repo liegt: sie
 * sahen nur unter /tmp/node_modules nach. Diese Sorte ist die teurere, weil sie
 * wie ein geklaerter Fall aussieht.
 *
 * ⚠ KEINE GEPFLEGTE LISTE. Der Waechter sucht die betroffenen Dateien selbst
 * (jede Datei in tests/, die jsdom laedt) – eine Liste waere an dem Tag
 * unvollstaendig, an dem jemand einen UI-Test hinzufuegt, und die fehlende
 * Zeile meldet sich nicht.
 *
 * ⚠ GEMESSEN, NICHT GERATEN. Abschnitt 2 liest nicht den Text, sondern STARTET
 * jede Datei in einer Umgebung ohne jsdom (tests/lib/ohne_jsdom.js faengt die
 * Modulaufloesung ab) und prueft den Exit-Code. Ein Waechter, der ein VORKOMMEN
 * prueft, wuerde hier nichts messen: `require('./lib/jsdom_laden')` im Quelltext
 * beweist nicht, dass der Lauf bei fehlendem jsdom sauber endet.
 *
 * ⚠ ER WAR SELBST BLIND – GEMESSEN AM 2026-10-10, UND ZWAR AN GENAU DER
 * FEHLERKLASSE, GEGEN DIE ER GEBAUT IST. Die Dateiauswahl entschied ueber den
 * QUELLTEXT des require-Arguments (`if (!/jsdom/i.test(text)) return;`). Bei
 * der zweithaeufigsten Gestalt im Repo –
 *
 *     for (const k of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom'])
 *         try { JSDOM = require(k).JSDOM; break; } catch (e) {}
 *
 * – ist dieser Text "k". Kein Treffer, kein Fund, und `if (!funde.length)
 * continue;` warf die Datei KOMPLETT aus der Messung: auch Abschnitt 3 ("endet
 * ohne jsdom mit Exit 2") lief fuer sie nie. 104 Dateien nannten jsdom, der
 * Waechter zaehlte 66 und meldete "keine Datei bindet jsdom direkt ein" –
 * 29 Dateien mit EIGENER Suchschleife waren unsichtbar, darunter solche, die
 * `<HOME>/node_modules/jsdom` nicht kennen und also "ABBRUCH: jsdom nicht
 * gefunden" gemeldet haetten, obwohl jsdom dort liegt. Ein Teilstring ist keine
 * Identitaet – und ein require-ARGUMENT ist kein Pfad, sondern ein Ausdruck.
 * Gemessen wird seitdem die EIGENSCHAFT (siehe `jsdomAufrufe`): wessen Ergebnis
 * als `.JSDOM` gelesen wird oder wessen Argument aus einer Kandidatenliste
 * stammt, der bindet jsdom ein – egal wie die Variable heisst.
 *
 * Lauf:  node tests/test_jsdom_einbindung.js
 */
"use strict";

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require("fs");
const path = require("path");
const { execFileSync, spawnSync } = require("child_process");

const WURZEL = path.resolve(__dirname, "..");
const TESTS = path.join(WURZEL, "tests");
const LADER_REL = "tests/lib/jsdom_laden.js";
const BLOCKER = path.join(TESTS, "lib", "ohne_jsdom.js");

let ok = 0, fail = 0;
function check(bed, text, extra) {
    if (bed) { ok++; console.log("  OK   " + text); }
    else { fail++; console.log("  FAIL " + text + (extra ? " – " + extra : "")); }
}
/** Eine Fundliste lesbar kuerzen – 55 Dateinamen in einer Zeile liest niemand,
 *  und die Zahl ist die eigentliche Aussage. */
function kurz(liste, zeige = 6) {
    if (!liste.length) return "";
    const rest = liste.length - zeige;
    return liste.length + " Stueck: " + liste.slice(0, zeige).join(", ")
           + (rest > 0 ? ", … (" + rest + " weitere)" : "");
}
function abschnitt(t) { console.log("\n═══ " + t); }

/* ── acorn: ohne Parser keine Aussage ueber den Syntaxbaum ─────────────────── */
let acorn = null;
for (const ort of ["acorn", "/usr/share/nodejs/acorn",
                   path.join(WURZEL, "node_modules/acorn")]) {
    try { acorn = require(ort); break; } catch (e) { /* naechster Ort */ }
}
if (!acorn) {
    console.log("ABBRUCH: acorn nicht gefunden – ohne Parser ist die Einbindung nicht "
                + "am Syntaxbaum messbar. Exit 2 = konnte nicht laufen.");
    process.exit(2);
}

function baum(quelle) {
    // allowReturnOutsideFunction: mehrere Waechter nutzen das CJS-Modulverhalten
    // (top-level `return`) – ohne das Flag wirft der Parser bei gueltigen Dateien.
    return acorn.parse(quelle, { ecmaVersion: 2023, locations: true,
                                 allowReturnOutsideFunction: true,
                                 allowAwaitOutsideFunction: true });
}
function durchlaufen(knoten, fn) {
    if (!knoten || typeof knoten !== "object") return;
    if (Array.isArray(knoten)) { knoten.forEach(k => durchlaufen(k, fn)); return; }
    if (typeof knoten.type === "string") fn(knoten);
    for (const feld in knoten) {
        if (feld === "type" || feld === "loc" || feld === "start" || feld === "end") continue;
        durchlaufen(knoten[feld], fn);
    }
}

/** Eltern-Verweise. Ohne sie ist nicht entscheidbar, wie das ERGEBNIS eines
 *  require() benutzt wird – und genau daran war dieser Waechter blind. */
function elternkarte(wurzel) {
    const karte = new Map();
    (function gehe(knoten, eltern) {
        if (!knoten || typeof knoten !== "object") return;
        if (Array.isArray(knoten)) { knoten.forEach(k => gehe(k, eltern)); return; }
        if (typeof knoten.type === "string") { karte.set(knoten, eltern); eltern = knoten; }
        for (const feld in knoten) {
            if (feld === "type" || feld === "loc" || feld === "start" || feld === "end") continue;
            gehe(knoten[feld], eltern);
        }
    })(wurzel, null);
    return karte;
}

/** Nennt dieser Teilausdruck jsdom? Bewusst ueber den Quelltext GENAU DIESES
 *  Knotens – ein Listenelement ist `'jsdom'`, `path.join(ROOT,
 *  'node_modules/jsdom')`, `W + '/node_modules/jsdom'` oder
 *  `process.env.JSDOM_PATH`; alle vier Gestalten kommen im Repo vor, und keine
 *  davon ist ein Literal, das man vergleichen koennte. */
function nenntJsdom(quelle, knoten) {
    if (!knoten) return false;
    const t = quelle.slice(knoten.start, knoten.end);
    return /jsdom/i.test(t) || /JSDOM_PATH/.test(t);
}

/** Der erste Array-Ausdruck in (oder an) einem Knoten – `[...]` steht im Repo
 *  auch als `[...].filter(Boolean)` hinter dem `of`. */
function arrayDarin(knoten) {
    let gefunden = null;
    durchlaufen(knoten, k => { if (!gefunden && k.type === "ArrayExpression") gefunden = k; });
    return gefunden;
}

/** Name der Laufvariablen einer for-of-Schleife (`for (const k of …)`). */
function schleifenname(fuer) {
    const l = fuer.left;
    if (l.type === "VariableDeclaration" && l.declarations.length
        && l.declarations[0].id.type === "Identifier") return l.declarations[0].id.name;
    if (l.type === "Identifier") return l.name;
    return null;
}

/** Wird das Ergebnis dieses Aufrufs als `.JSDOM` gelesen? Deckt
 *  `require(k).JSDOM`, `const { JSDOM } = require(k)` und die Zuweisung ohne
 *  Deklaration ab – also jede Gestalt, in der ein Aufrufer sagt, dass er jsdom
 *  gemeint hat. */
function alsJsdomGelesen(aufruf, eltern) {
    const p = eltern.get(aufruf);
    if (!p) return false;
    const heisstJSDOM = (k) => !!k && ((k.type === "Identifier" && k.name === "JSDOM")
                                       || (k.type === "Literal" && k.value === "JSDOM"));
    if (p.type === "MemberExpression" && p.object === aufruf && heisstJSDOM(p.property)) return true;
    const muster = (p.type === "VariableDeclarator" && p.init === aufruf) ? p.id
                 : (p.type === "AssignmentExpression" && p.right === aufruf) ? p.left
                 : null;
    if (muster && muster.type === "ObjectPattern") {
        return muster.properties.some(pr => heisstJSDOM(pr.key));
    }
    return false;
}

/** Stammt das Argument aus einer Kandidatenliste, die jsdom nennt? Gemessen
 *  ueber die ELTERNKETTE: die Variable muss die Laufvariable einer umgebenden
 *  for-of-Schleife sein. Keine Namensliste – `k`, `o`, `p`, `kand` und
 *  `kandidat` kommen im Repo alle vor, und der naechste heisst anders. */
function ausKandidatenliste(aufruf, arg, eltern, arrays, quelle) {
    if (arg.type !== "Identifier") return false;
    for (let k = eltern.get(aufruf); k; k = eltern.get(k)) {
        if (k.type !== "ForOfStatement" || schleifenname(k) !== arg.name) continue;
        let liste = arrayDarin(k.right);
        if (!liste && k.right.type === "Identifier") liste = arrays.get(k.right.name) || null;
        if (liste && liste.elements.some(e => nenntJsdom(quelle, e))) return true;
    }
    return false;
}

/** Alle require()-Aufrufe einer Datei, die jsdom betreffen – am Syntaxbaum,
 *  nicht am Text (ein Teilstring ist keine Identitaet: "jsdom_laden" enthaelt
 *  "jsdom", ist aber genau der richtige Weg).
 *
 *  ⚠ DREI UNABHAENGIGE EIGENSCHAFTEN, keine davon ein Name:
 *   (a) das ARGUMENT nennt jsdom (`require('jsdom')`,
 *       `require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom')`),
 *   (b) das ERGEBNIS wird als `.JSDOM` gelesen – dann ist die Absicht erklaert,
 *       auch wenn das Argument `k` heisst,
 *   (c) das Argument ist die Laufvariable einer Schleife ueber eine Liste, die
 *       jsdom nennt – dann ist die Absicht an der Liste erklaert.
 *  (b) und (c) sind der Grund, dass dieser Waechter die eigene Fehlerklasse
 *  sieht; (a) allein hat 29 Dateien uebersehen. */
function jsdomAufrufe(quelle) {
    const wurzel = baum(quelle);
    const eltern = elternkarte(wurzel);
    // `const orte = [...]` plus `for (const o of orte)` ist eine der Gestalten.
    const arrays = new Map();
    durchlaufen(wurzel, k => {
        if (k.type !== "VariableDeclarator" || k.id.type !== "Identifier" || !k.init) return;
        const a = arrayDarin(k.init);
        if (a) arrays.set(k.id.name, a);
    });

    const funde = [];
    durchlaufen(wurzel, knoten => {
        if (knoten.type !== "CallExpression") return;
        if (knoten.callee.type !== "Identifier" || knoten.callee.name !== "require") return;
        if (!knoten.arguments.length) return;
        const arg = knoten.arguments[0];
        const text = quelle.slice(arg.start, arg.end);
        const wörtlich = (arg.type === "Literal" && typeof arg.value === "string")
                         ? arg.value : null;
        const wege = [];
        if (nenntJsdom(quelle, arg)) wege.push("Argument");
        if (alsJsdomGelesen(knoten, eltern)) wege.push(".JSDOM");
        if (ausKandidatenliste(knoten, arg, eltern, arrays, quelle)) wege.push("Kandidatenliste");
        if (!wege.length) return;
        funde.push({
            zeile: arg.loc.start.line,
            text: text.replace(/\s+/g, " "),
            wege: wege.join("+"),
            // Der gemeinsame Weg: ein WOERTLICHER Pfad auf den Lader.
            ueberLader: wörtlich !== null && /(^|\/)lib\/jsdom_laden$/.test(wörtlich),
        });
    });
    return funde;
}

/** Baut die Datei ein DOM? `new JSDOM(...)` ist der unabhaengige Gegenbeleg zur
 *  Fundliste: wer ein DOM baut, MUSS eine erkannte Einbindung haben. Ohne diese
 *  Gegenrichtung ist "nennt jsdom nur im Kommentar" von "der Waechter sieht die
 *  Einbindung nicht" nicht zu unterscheiden – exakt der Zustand vom 2026-10-10. */
function baut_dom(quelle) {
    let gefunden = false;
    durchlaufen(baum(quelle), k => {
        if (k.type !== "NewExpression") return;
        const c = k.callee;
        if (c.type === "Identifier" && c.name === "JSDOM") gefunden = true;
        if (c.type === "MemberExpression" && c.property.type === "Identifier"
            && c.property.name === "JSDOM") gefunden = true;
    });
    return gefunden;
}

/* ═══ 1 · Positivkontrolle: ohne sie sind alle weiteren Pruefungen trivial ══ */
abschnitt("1 · Positivkontrolle des Messaufbaus");

check(fs.existsSync(path.join(WURZEL, LADER_REL)), "die gemeinsame Quelle existiert: " + LADER_REL);
check(fs.existsSync(BLOCKER), "das Messwerkzeug existiert: tests/lib/ohne_jsdom.js");

/* ── 1a · Das MESSWERKZEUG gegen Probequellen ──────────────────────────────
 *
 * ⚠ EIN ERFUNDENER NAME TAUGT ALS KONTROLLE NICHT (Register, Lehre zu
 * test_js_einbindung.py): er kommt nirgends vor, also kann ein zu BREITES
 * Muster damit nicht auffallen – und ein zu ENGES erst recht nicht. Gemessen
 * wird deshalb an Quellen, in denen jsdom mehrfach HARMLOS vorkommt
 * (Kommentar, Zeichenkette, fremdes Modul) und genau einmal als Einbindung:
 * das Werkzeug muss die eine finden und NUR sie.
 *
 * Die Quellen stehen inline, nicht als Datei in tests/ – dort geriete eine
 * Probedatei in die eigene Messung (und in die der uebrigen Waechter). */
const PROBE_SCHLEIFE = [
    "const fs = require('fs');",                              // 1 fremdes Modul
    "// jsdom liegt je Maschine anders – dies ist nur ein Kommentar.",
    "const hinweis = 'ABBRUCH: jsdom nicht gefunden';",        // 3 Zeichenkette
    "const sitzung = require('./lib/sitzung_laden');",         // 4 fremdes Modul
    "let modul = null;",
    "for (const k of [process.env.JSDOM_PATH, 'jsdom', '/tmp/node_modules/jsdom']) {",
    "    if (!k) continue;",
    "    try { modul = require(k); break; } catch (e) { /* naechster */ }",  // 8 ECHT
    "}",
].join("\n");
// Dieselbe Absicht, anders erklaert: das Argument kommt NICHT aus einer Liste,
// aber das Ergebnis wird als `.JSDOM` gelesen.
const PROBE_PUNKT = [
    "const ort = process.argv[2];",
    "const JSDOM = require(ort).JSDOM;",                       // 2 ECHT
].join("\n");
// Und die Gegenrichtung: nur Erwaehnungen, keine Einbindung.
const PROBE_HARMLOS = [
    "// jsdom rechnet kein Layout (Register).",
    "const text = 'jsdom';",
    "const fs = require('fs');",
    "const path = require('path');",
].join("\n");
const PROBE_LADER = "const { JSDOM } = require('./lib/jsdom_laden')();";

const pSchleife = jsdomAufrufe(PROBE_SCHLEIFE);
const pPunkt = jsdomAufrufe(PROBE_PUNKT);
const pHarmlos = jsdomAufrufe(PROBE_HARMLOS);
const pLader = jsdomAufrufe(PROBE_LADER);
const zeigen = (f) => JSON.stringify(f.map(x => x.zeile + ":" + x.text + " [" + x.wege + "]"));

const kontrollen = [
    [pSchleife.length === 1 && pSchleife[0].zeile === 8,
     "Probequelle 1: die Schleife ueber Kandidatenpfade wird gefunden – und NUR sie "
     + "(Kommentar, Zeichenkette und zwei fremde require() zaehlen nicht)", zeigen(pSchleife)],
    [pSchleife.length === 1 && !pSchleife[0].ueberLader,
     "Probequelle 1: sie gilt als DIREKTE Einbindung, nicht als Weg ueber den Lader",
     zeigen(pSchleife)],
    [pPunkt.length === 1 && !pPunkt[0].ueberLader,
     "Probequelle 2: ein require() mit variablem Argument, dessen Ergebnis als "
     + ".JSDOM gelesen wird, zaehlt ebenfalls", zeigen(pPunkt)],
    [pHarmlos.length === 0,
     "Probequelle 3: blosse Erwaehnungen zaehlen NICHT (das Werkzeug ist nicht "
     + "trivial wahr)", zeigen(pHarmlos)],
    [pLader.length === 1 && pLader[0].ueberLader,
     "Probequelle 4: der gemeinsame Weg wird als solcher erkannt", zeigen(pLader)],
];
let kontrolleRot = false;
for (const [bed, text, extra] of kontrollen) {
    check(bed, text, extra);
    if (!bed) kontrolleRot = true;
}
if (kontrolleRot) {
    // Exit 2, nicht 1: ein defektes Messwerkzeug macht JEDE Folgepruefung
    // wertlos, und "ich beisse" waere dafuer die falsche Sprache (Register).
    console.log("\nABBRUCH: das Messwerkzeug erkennt eine Einbindung nicht oder haelt "
                + "eine Erwaehnung fuer eine. Alles Folgende waere wertlos. "
                + "Exit 2 = konnte nicht laufen.");
    process.exit(2);
}

/* ── 1b · Die betroffenen Dateien selbst ermitteln ─────────────────────────── */
const dateien = [];
const parseFehler = [];
const blindUebersehen = [];
let nurErwaehnt = 0;
for (const name of fs.readdirSync(TESTS).filter(n => n.endsWith(".js")).sort()) {
    const p = path.join(TESTS, name);
    // Dieser Waechter selbst prueft die Regel, er unterliegt ihr nicht: er redet
    // ueber jsdom, baut aber kein DOM. Ausschluss ueber __filename statt ueber
    // einen Namen – so kann er beim Umbenennen nicht stillschweigend wieder
    // in die eigene Messung geraten.
    if (p === __filename) continue;
    const quelle = fs.readFileSync(p, "utf8");
    if (!/jsdom/i.test(quelle)) continue;
    let funde, baut;
    try { funde = jsdomAufrufe(quelle); baut = baut_dom(quelle); }
    catch (e) { parseFehler.push(name + ": " + e.message); continue; }
    if (!funde.length) {
        // ⚠ HIER lag die Blindheit: ein `continue` ohne Gegenbeleg. Wer ein DOM
        // BAUT, muss eine erkannte Einbindung haben – sonst ist nicht der Code
        // harmlos, sondern das Messwerkzeug blind.
        if (baut) blindUebersehen.push(name);
        else nurErwaehnt++;
        continue;
    }
    dateien.push({ name, pfad: p, quelle, funde });
}

if (!parseFehler.length) check(true, "alle jsdom-Dateien sind parsebar");
else check(false, "alle jsdom-Dateien sind parsebar", parseFehler.join("; "));

check(blindUebersehen.length === 0,
      "keine Datei baut ein DOM (`new JSDOM`), ohne dass ihre Einbindung erkannt wird",
      kurz(blindUebersehen, 8));
if (blindUebersehen.length) {
    console.log("\nABBRUCH: " + blindUebersehen.length + " Datei(en) bauen ein DOM, deren "
                + "Einbindung dieses Werkzeug nicht sieht – sie fielen aus Abschnitt 2 UND 3 "
                + "heraus. Exit 2 = konnte nicht laufen.");
    process.exit(2);
}

// Ohne Fundstellen misst dieser Waechter nichts – das ist kein "bestanden".
if (dateien.length < 10) {
    console.log("\nABBRUCH: nur " + dateien.length + " jsdom-Dateien gefunden (erwartet: "
                + "Dutzende). Der Waechter misst so nichts. Exit 2 = konnte nicht laufen.");
    process.exit(2);
}
check(true, dateien.length + " Dateien in tests/*.js binden jsdom (" + nurErwaehnt
           + " weitere nennen es nur, ohne ein DOM zu bauen)");

// Der Blocker muss WIRKLICH blocken, sonst messen Abschnitt 3 und 4 die
// normale Umgebung und sind trivial gruen.
const lader = require("./lib/jsdom_laden");
const jsdomDa = lader.versuchen() !== null;
check(jsdomDa, "jsdom ist auf dieser Maschine ueber die gemeinsame Quelle auffindbar",
      jsdomDa ? "" : "gesucht in: " + lader.orte().join(", "));
if (!jsdomDa) {
    console.log("\nABBRUCH: ohne auffindbares jsdom ist nicht belegbar, dass das "
                + "Messwerkzeug etwas WEGNIMMT. Exit 2 = konnte nicht laufen.");
    process.exit(2);
}
const blockprobe = spawnSync(process.execPath,
    ["-r", BLOCKER, "-e", "try { require('jsdom'); console.log('DA'); } "
     + "catch (e) { console.log('WEG:' + e.code); }"],
    { cwd: WURZEL, encoding: "utf8" });
check(/WEG:MODULE_NOT_FOUND/.test(blockprobe.stdout || ""),
      "das Messwerkzeug nimmt jsdom wirklich weg (sonst waere alles Folgende trivial)",
      JSON.stringify((blockprobe.stdout || "").trim()));
const laderprobe = spawnSync(process.execPath,
    ["-r", BLOCKER, "-e", "require('./tests/lib/jsdom_laden').orte()"],
    { cwd: WURZEL, encoding: "utf8" });
check(laderprobe.status === 0,
      "der Lader selbst bleibt trotz Blocker ladbar (jsdom_laden ist nicht jsdom)",
      "Exit " + laderprobe.status);

/* ═══ 2 · Regel: die Einbindung laeuft ueber die gemeinsame Quelle ═════════ */
abschnitt("2 · Jede Datei bindet jsdom ueber " + LADER_REL + " ein");

const direkt = [];
for (const d of dateien) {
    const eigene = d.funde.filter(f => !f.ueberLader);
    if (eigene.length) direkt.push(d.name + " (Z. " + eigene.map(f => f.zeile).join(", ") + ")");
}
check(direkt.length === 0,
      "keine Datei bindet jsdom direkt ein (" + dateien.length + " geprueft)",
      kurz(direkt));

/* ═══ 3 · Regel: fehlendes jsdom endet mit Exit 2, ohne Stacktrace ════════ */
abschnitt("3 · Ohne jsdom: Exit 2 und eine lesbare Meldung (gemessen, je Datei)");

// Eine Datei darf das Fehlen ausdruecklich ueberleben, wenn sie das mit
// `versuchen()` SELBST erklaert (Regelfall ist `laden()`/Exit 2). Das ist
// keine gepflegte Liste: die Ausnahme steht in der Datei, nicht hier.
function darfUeberspringen(quelle) {
    let gefunden = false;
    durchlaufen(baum(quelle), knoten => {
        if (knoten.type !== "CallExpression") return;
        const c = knoten.callee;
        if (c.type === "MemberExpression" && c.property.type === "Identifier"
            && c.property.name === "versuchen") gefunden = true;
    });
    return gefunden;
}

const falscherExit = [], mitStacktrace = [], ohneMeldung = [];
for (const d of dateien) {
    const lauf = spawnSync(process.execPath, ["-r", BLOCKER, path.join("tests", d.name)],
                           { cwd: WURZEL, encoding: "utf8", timeout: 120000 });
    const ausgabe = (lauf.stdout || "") + (lauf.stderr || "");

    // Ein Stacktrace ist in JEDEM Fall verboten – auch bei den Ausnahmen.
    if (/MODULE_NOT_FOUND/.test(ausgabe) || /^\s+at .*\(.*:\d+:\d+\)$/m.test(ausgabe)) {
        mitStacktrace.push(d.name);
    }
    if (darfUeberspringen(d.quelle)) {
        // Erklaerte Ausnahme: kein Urteil ueber den Exit-Code, aber die Datei
        // muss das Ueberspringen SAGEN (eine stille Luecke ist keine Aussage).
        if (!/uebersprung|ueberspring|skip/i.test(ausgabe)) ohneMeldung.push(d.name);
        continue;
    }
    if (lauf.status !== 2) {
        falscherExit.push(d.name + " → Exit " + lauf.status
                          + (lauf.status === 1 ? " (sieht aus wie 'Waechter beisst')" : ""));
    }
}
check(falscherExit.length === 0,
      "jede Datei endet ohne jsdom mit Exit 2, nicht mit 1 oder 0",
      kurz(falscherExit, 4));
check(mitStacktrace.length === 0,
      "keine Datei wirft dabei einen Stacktrace",
      kurz(mitStacktrace));
check(ohneMeldung.length === 0,
      "eine Datei, die das Fehlen ueberlebt, sagt es auch",
      kurz(ohneMeldung));

/* ═══ 4 · Regel: die Suchorte der gemeinsamen Quelle ══════════════════════ */
abschnitt("4 · Die gemeinsame Quelle sucht an den vereinbarten Orten");

// Gemessen wird die RUECKGABE von orte(), nicht der Quelltext – eine
// Textpruefung waere gruen, sobald der Pfad irgendwo im Kommentar steht.
const HEIM = "/heim/pruefling";
const gemessen = execFileSync(process.execPath,
    ["-e", "process.stdout.write(JSON.stringify(require('./tests/lib/jsdom_laden').orte()))"],
    { cwd: WURZEL, encoding: "utf8",
      env: Object.assign({}, process.env, { HOME: HEIM, JSDOM_PATH: "/vorgabe/jsdom" }) });
const orte = JSON.parse(gemessen);

const pflicht = [
    ["die ausdrueckliche Vorgabe JSDOM_PATH", "/vorgabe/jsdom"],
    ["/tmp/node_modules/jsdom", "/tmp/node_modules/jsdom"],
    ["<HOME>/node_modules/jsdom", HEIM + "/node_modules/jsdom"],
    ["<HOME>/sleek/node_modules/jsdom", HEIM + "/sleek/node_modules/jsdom"],
    ["das Repo selbst", path.join(WURZEL, "node_modules/jsdom")],
    ["ein nacktes require('jsdom') (NODE_PATH/lokale Installation)", "jsdom"],
];
for (const [was, wert] of pflicht) {
    check(orte.indexOf(wert) >= 0, "gesucht wird " + was, "orte(): " + orte.join(", "));
}
check(orte[0] === "/vorgabe/jsdom", "JSDOM_PATH hat Vorrang vor allen anderen Orten",
      "erster Ort: " + orte[0]);

/* ── Bilanz ───────────────────────────────────────────────────────────────── */
console.log("\n" + "═".repeat(70));
console.log("Ergebnis: " + ok + " OK, " + fail + " FAIL  (" + dateien.length + " Dateien geprueft)");
process.exit(fail ? 1 : 0);
