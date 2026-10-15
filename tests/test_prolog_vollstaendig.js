#!/usr/bin/env node
/* Waechter: KEIN Prolog eines Pruefstands referenziert einen Namen, den
 * niemand stellt.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT. Rund 85 Pruefstaende schneiden Funktionen aus
 * `frontend/js/*.js` heraus und bauen sich dafuer je einen eigenen Prolog, den
 * sie per `window.eval()` ausfuehren. Kommt im Produktivcode ein Helfer oder
 * eine Modulkonstante dazu, stirbt jeder dieser Prologe mit einem nackten
 * `ReferenceError` – unbehandelt als Exit 1 OHNE Bilanz (in diesem Projekt die
 * Sprache fuer "der Waechter beisst") oder in einem `catch` verschluckt, dann
 * als trivial gruene Pruefung. Zwei bezahlte Faelle:
 *   · 2026-09-29  `_selMode`/`_selIds` kamen in `_renderSidebar` dazu – ZWEI
 *                 fremde Proben starben, waehrend der eigene Waechter gruen war.
 *   · 2026-10-11  `_bildMimeAusBytes` kam in `addFiles` dazu –
 *                 `lies_chat_vorschau.js` starb mitten in seiner Tabelle.
 * Das Register ermahnt zweimal dazu, den Prolog mitzuziehen. Eine Ermahnung
 * muss jemand lesen; eine Regel beisst von selbst.
 *
 * ⚠ DIE LUECKE IST VOR DEM ERSTEN TESTFALL DA, NICHT ERST BEIM ABSTURZ. Ein
 * Sammellauf findet nur, was der ausgefuehrte Zweig beruehrt: in
 * `test_chat_bild_einfuegen.js` lagen bei der ersten Messung 42 Referenzen auf
 * drei Modulvariablen (`_lbAtts`, `_lbIdx`, `_ctxAtt`), waehrend der Waechter
 * 43 OK / 0 FAIL meldete – die Lightbox- und Kontextmenue-Zweige werden dort
 * nie betreten. Deshalb wird nicht der LAUF beurteilt, sondern jede Referenz
 * im evaluierten Code.
 *
 * ⚠ GEMESSEN WIRD AM ORT DES GESCHEHENS. Die Prologe entstehen zur LAUFZEIT
 * (Template-Literal aus mehreren Schnitten) – ein Waechter, der sie aus dem
 * Quelltext der Pruefstaende rekonstruiert, misst seine eigene Nachbildung.
 * Stattdessen instrumentiert `tests/lib/prolog_pruefen.js` das `window.eval`,
 * eingehaengt in `tests/lib/jsdom_laden.js`: die EINE Quelle, durch die jeder
 * Pruefstand sein JSDOM holt (`test_jsdom_einbindung.js` haelt das als Regel
 * fest). Kein Pruefstand musste dafuer angefasst werden.
 *
 * ⚠ KEINE GEPFLEGTE LISTE – weder der Pruefstaende noch der Globalen. Die
 * Dateien ermittelt dieser Waechter selbst (Eigenschaft: liest etwas unter
 * `frontend/` UND ruft `.eval(`), und ob ein Name von der Umgebung kommt,
 * entscheidet `name in window` am ECHTEN Fenster.
 *
 * ⚠ DAUER: rund 6 Minuten – jeder Pruefstand laeuft wirklich. Ein billigerer
 * Weg existiert nicht: ohne Lauf gibt es den Prolog nicht.
 *
 * Lauf:  node tests/test_prolog_vollstaendig.js
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const WURZEL = path.resolve(__dirname, "..");
const TESTS = path.join(WURZEL, "tests");
const pruefer = require("./lib/prolog_pruefen");

/* Absturznetz: ein Wurf endet mit Exit 2, nicht mit Node-Vorgabe 1. Exit 1 ist
 * hier die Sprache fuer "der Waechter beisst" – und ein Waechter, der sieben
 * Minuten laeuft, ist genau der, bei dem niemand nachsieht, ob die Zahl ein
 * Befund oder ein Absturz war. `test_waechter_bilanz.js` haelt das als Regel
 * fest und hat diese Datei beim ersten Lauf zu Recht gemeldet. */
require("./lib/bilanz")();

let ok = 0, fail = 0;
function check(bed, text, extra) {
    if (bed) { ok++; console.log("  OK   " + text); }
    else { fail++; console.log("  FAIL " + text + (extra ? " – " + extra : "")); }
}
function kurz(liste, zeige = 6) {
    if (!liste.length) return "";
    const rest = liste.length - zeige;
    return liste.length + " Stueck: " + liste.slice(0, zeige).join(", ")
           + (rest > 0 ? ", … (" + rest + " weitere)" : "");
}
function abschnitt(t) { console.log("\n═══ " + t); }
function abbruch(grund) {
    console.log("\nABBRUCH: " + grund + " Exit 2 = konnte nicht laufen.");
    process.exit(2);
}

/* ═══ 1 · Positivkontrolle des Messwerkzeugs ═══════════════════════════════
 *
 * ⚠ OHNE DIESEN ABSCHNITT IST ALLES WEITERE TRIVIAL. Ein Analysator, der nie
 * etwas findet, meldet 85-mal "keine Luecke" und sieht wie Entwarnung aus; ein
 * zu breiter meldet 85-mal Unsinn und wird binnen einer Woche abgeschaltet.
 * Ein ERFUNDENER Name taugt dafuer nicht (er kommt nirgends vor, also kann ein
 * zu breites Muster damit nicht auffallen) – gemessen wird an Quellen, in
 * denen der Name auch HARMLOS vorkommt: als Kommentar, als Zeichenkette, als
 * Eigenschaft und als Objektschluessel. */
abschnitt("1 · Positivkontrolle des Messwerkzeugs");

const P_LUECKE = [
    "// _fehlenderHelfer steht hier nur im Kommentar.",
    "const text = '_fehlenderHelfer';",            // Zeichenkette
    "const obj = { _fehlenderHelfer: 1 };",        // Objektschluessel
    "let gefunden = null;",
    "function lauf(eingabe) {",
    "    gefunden = obj._fehlenderHelfer;",        // Eigenschaft
    "    return _fehlenderHelfer(eingabe) + gefunden;",   // Z. 7 – die ECHTE Referenz
    "}",
].join("\n");
const P_SAUBER = [
    "function a(x) { const y = x + 1; return b(y); }",
    "function b(z) { return z * 2; }",
    "const { p, q } = a(1);",
    "const [r, ...rest] = [p, q];",
    "try { a(r); } catch (e) { b(rest.length); }",
].join("\n");
// Kurzschreibweise IST eine Referenz – wer sie wie einen Schluessel behandelt,
// uebersieht `{ _fehlenderKurz }` und damit eine ganze Schreibweise.
const P_KURZ = "const o = { _fehlenderKurz };";
/* ⚠ ZWEI FEHLALARME, DIE DIESES WERKZEUG BEIM BAU SELBST PRODUZIERT HAT –
 * beide ueber voellig richtigem Code, und jeder haette den Waechter unbrauchbar
 * gemacht:
 *   · `arguments` steht in jeder Nicht-Pfeil-Funktion implizit zur Verfuegung
 *     und wird nirgends deklariert (traf test_stt_lokal, test_chat_release_ui).
 *   · der Name eines KLASSENAUSDRUCKS bindet nach innen. `window.x = new (class
 *     Name { … })` ist die Hausform von cron.js und audit.js – gemeldet wurden
 *     DREI Pruefstaende, die diese Dateien sogar GANZ evaluieren, also gar
 *     nichts geschnitten haben.
 * Sie stehen hier, damit der Waechter seine eigenen Fehlalarme bewacht. */
const P_IMPLIZIT = [
    "function f() { return arguments.length; }",
    "const h = new (class Nachbar { lauf() { return Nachbar.name; } })();",
    "const g = function rekursiv(n) { return n ? rekursiv(n - 1) : 0; };",
].join("\n");

const nurName = (e) => (e.fehlend || []).map(x => x.name).sort();
const eL = pruefer.luecken(P_LUECKE, null, null);
const eS = pruefer.luecken(P_SAUBER, null, null);
const eK = pruefer.luecken(P_KURZ, null, null);
const eI = pruefer.luecken(P_IMPLIZIT, null, null);

const kontrollen = [
    [!eL.parsefehler && eL.fehlend.length === 1 && eL.fehlend[0].name === "_fehlenderHelfer"
     && eL.fehlend[0].zeile === 7,
     "Probequelle 1: die EINE echte Referenz wird gefunden – und nur sie "
     + "(Kommentar, Zeichenkette, Eigenschaft und Objektschluessel zaehlen nicht)",
     JSON.stringify(eL.fehlend || eL)],
    [!eS.parsefehler && eS.fehlend.length === 0,
     "Probequelle 2: sauberer Code meldet nichts (Destrukturierung, Rest, catch)",
     JSON.stringify(eS.fehlend || eS)],
    [!eK.parsefehler && nurName(eK).join() === "_fehlenderKurz",
     "Probequelle 3: die Kurzschreibweise `{ x }` zaehlt als Referenz",
     JSON.stringify(eK.fehlend || eK)],
    [!eI.parsefehler && eI.fehlend.length === 0,
     "Probequelle 4: `arguments` und der Name eines Klassen-/Funktionsausdrucks "
     + "gelten als gebunden (beide waren hier schon Fehlalarme)",
     JSON.stringify(eI.fehlend || eI)],
];
for (const [bed, text, extra] of kontrollen) check(bed, text, extra);

/* 1b · Dieselbe Pruefung durch die ECHTE Instrumentierung, an einem echten
 * Fenster. Abschnitt 1a misst den Analysator; hier wird gemessen, dass die
 * Beobachtung an `window.eval` haengt und dass `name in window` wirkt.
 *
 * ⚠ DIE LETZTE KONTROLLE HAELT EINE UMGEBUNGS-EIGENSCHAFT FEST, die beim Bau
 * dieses Waechters eine falsche Annahme war: ein `const` aus einem FRUEHEREN
 * `window.eval` ist im naechsten NICHT mehr da (`ReferenceError`), waehrend
 * `var` und `function` am Fenster liegen und bleiben. Wer das verwechselt,
 * fuehrt eine Menge "frueher gebundener Namen" mit und verdeckt damit genau
 * die Luecken, die dieser Waechter finden soll. Deshalb wird die Eigenschaft
 * hier gemessen und nicht angenommen. */
const { JSDOM } = require("./lib/jsdom_laden")();
const dom = new JSDOM("<!doctype html><body></body>", { url: "https://h/", runScripts: "outside-only" });
const w = dom.window;
const saetze = [];
pruefer.fensterAusstatten(w, (s) => saetze.push(s));
const fehlendBeim = (i) => (saetze[i] && saetze[i].fehlend || []).map(x => x.name);

w._amFenster = 7;
w.eval("var _ausEval = _amFenster + 1;");   // 0 · am Fenster gesetzt
w.eval("_ausEval + 1;");                    // 1 · `var` aus eval 0 liegt am Fenster
w.eval("const _nurLexikalisch = 2;");       // 2 · bindet selbst
let lexikalischWirft = false;               // 3 · und ist danach WEG
try { w.eval("_nurLexikalisch + 1;"); } catch (e) { lexikalischWirft = /ReferenceError/.test(String(e)); }
try { w.eval("_garNichtDa(1);"); } catch (e) { /* 4 · die echte Luecke, wirft natuerlich */ }

const kontrollen2 = [
    [saetze.length === 5, "die Beobachtung haengt an window.eval (5 evals gesehen)",
     "gesehen: " + saetze.length],
    [fehlendBeim(0).length === 0, "ein am Fenster gesetzter Name gilt als gestellt "
     + "(`name in window`, keine gepflegte Globalen-Liste)", JSON.stringify(fehlendBeim(0))],
    [fehlendBeim(1).length === 0, "ein `var` aus einem frueheren eval gilt als gestellt",
     JSON.stringify(fehlendBeim(1))],
    [fehlendBeim(2).length === 0, "ein `const` im selben eval gilt als gestellt",
     JSON.stringify(fehlendBeim(2))],
    [lexikalischWirft && fehlendBeim(3).join() === "_nurLexikalisch",
     "ein `const` aus einem FRUEHEREN eval ist weg – und wird gemeldet "
     + "(gemessen: der Lauf wirft dort wirklich ReferenceError)",
     "wirft=" + lexikalischWirft + " " + JSON.stringify(fehlendBeim(3))],
    [fehlendBeim(4).join() === "_garNichtDa", "ein nirgends gestellter Name wird gemeldet",
     JSON.stringify(fehlendBeim(4))],
];
for (const [bed, text, extra] of kontrollen2) check(bed, text, extra);
w.close();

/* 1c · Die EINTEILUNG. Ein fehlender Name hat drei moegliche Herkuenfte, und
 * nur eine ist Sache dieser Regel. Gemessen am ausgelieferten Code, nicht ueber
 * eine gepflegte Liste:
 *   · im Frontend deklariert und NICHT ans Fenster exportiert -> der SCHNITT
 *     hat ihn verloren. Das ist der Befund.
 *   · als `window.X = …` exportiert -> ein NACHBARMODUL ist nicht geladen.
 *   · nirgends deklariert -> die UMGEBUNG soll ihn stellen (`fetch`,
 *     `TextEncoder`, `requestAnimationFrame`; jsdom hat sie nicht).
 * Ohne diese Kontrolle waere die Regel entweder blind (alles Umgebung) oder
 * unbrauchbar laut (36 Dateien beim ersten Lauf – so gemessen). */
function frontendDateien(verzeichnis, raus = []) {
    for (const e of fs.readdirSync(verzeichnis, { withFileTypes: true })) {
        const v = path.join(verzeichnis, e.name);
        // `vendor/` ist Fremdcode und wird nie geschnitten.
        if (e.isDirectory()) {
            if (e.name !== "vendor" && e.name !== "node_modules") frontendDateien(v, raus);
        } else if (e.name.endsWith(".js")) raus.push(v);
    }
    return raus;
}
const FE = frontendDateien(path.join(WURZEL, "frontend"));
const index = pruefer.frontendIndex(FE);

const kontrollen3 = [
    [FE.length >= 50 && index.deklariert.size >= 500,
     FE.length + " Frontend-Dateien gelesen, " + index.deklariert.size
     + " deklarierte Namen, " + index.amFenster.size + " Fenster-Exporte",
     "zu wenig – die Einteilung waere wertlos"],
    [index.parsefehler.length === 0,
     "jede Frontend-Datei ist parsebar (ein lueckenhafter Index verschiebt eine "
     + "Schnitt-Luecke stillschweigend in die Umgebung)", kurz(index.parsefehler, 3)],
    // Drei bekannte Faelle, je einer pro Herkunft – an ECHTEN Namen gemessen,
    // nicht an erfundenen: ein erfundener Name landet immer in "umgebung" und
    // kann eine falsche Einteilung nicht zeigen.
    [pruefer.einteilen("_selSetze", index) === "schnitt",
     "eine Modulfunktion (`_selSetze`, chat.js) gilt als Schnitt-Luecke"],
    [pruefer.einteilen("JarvisIcons", index) === "nachbarmodul",
     "ein Fenster-Export (`JarvisIcons`, icons.js) gilt als fehlendes Nachbarmodul"],
    [pruefer.einteilen("fetch", index) === "umgebung",
     "ein Browser-Name (`fetch`) gilt als Umgebung, nicht als Befund"],
];
for (const [bed, text, extra] of kontrollen3) check(bed, text, extra);

if (fail) {
    abbruch("das Messwerkzeug erkennt eine Luecke nicht, haelt eine Erwaehnung fuer "
            + "eine, oder teilt die Herkunft falsch ein. Jede Folgepruefung waere wertlos.");
}

/* ═══ 2 · Die Pruefstaende selbst ermitteln ════════════════════════════════ */
abschnitt("2 · Die betroffenen Pruefstaende");

/* Eigenschaft, keine Liste: wer Code aus `frontend/` liest UND ihn per
 * `.eval(` in ein Fenster gibt, baut einen Prolog – egal wie seine
 * Schneidefunktion heisst. (Eine Liste waere an dem Tag unvollstaendig, an
 * dem jemand einen UI-Test hinzufuegt, und die fehlende Zeile meldet sich
 * nicht.) `gegen_*` bleibt ausdruecklich draussen: eine Gegenprobe patcht
 * Dateien und darf NIE in einem Sammellauf mitlaufen – der Rueckstand stand
 * danach schon einmal im Arbeitsbaum. */
const LIEST_FRONTEND = /readFileSync\([^)]*frontend|join\([^)]*['"]frontend/;
const EVAL = /\.eval\(/;
const dateien = fs.readdirSync(TESTS)
    .filter(n => n.endsWith(".js"))
    .filter(n => !n.startsWith("gegen_"))
    .sort()
    .filter(n => {
        if (path.join(TESTS, n) === __filename) return false;
        const q = fs.readFileSync(path.join(TESTS, n), "utf8");
        return LIEST_FRONTEND.test(q) && EVAL.test(q);
    });

if (dateien.length < 20) {
    abbruch("nur " + dateien.length + " Pruefstaende mit Prolog gefunden (erwartet: "
            + "Dutzende). Der Waechter misst so nichts.");
}
check(true, dateien.length + " Pruefstaende geben Frontend-Code in ein Fenster");

/* ═══ 3 · Je Pruefstand: jede Referenz im evaluierten Code ════════════════ */
abschnitt("3 · Kein evaluierter Prolog referenziert einen ungestellten Namen");

const ablage = fs.mkdtempSync(path.join(os.homedir(), ".prolog_pruefung_"));
const ohneEval = [], ohneFenster = [], werkzeugfehler = [], parsefehler = [], luecken = [];
/* Die beiden anderen Herkuenfte sind KEIN Befund dieser Regel – aber sie
 * werden GEZAEHLT und benannt. Ein Geltungsbereich, der etwas auslaesst,
 * braucht den Grund im Waechter (Register); eine stille Auslassung sieht wie
 * eine Messung aus und ist eine Luecke. */
const nebenbefunde = { nachbarmodul: new Set(), umgebung: new Set() };
const nebenbefundeDateien = { nachbarmodul: new Set(), umgebung: new Set() };
let evalsGesamt = 0;

/* ═══ 3a · Alle Pruefstaende STARTEN (nebenlaeufig) ═══════════════════════
 * Seriell war die Laufzeit dieses Waechters die SUMME der ~86 anderen und
 * wuchs mit jedem neuen Pruefstand: in der CI 286,6 s / 300,1 s / 305,3 s bei
 * 300 s Deckel, zweimal gerissen (2026-10-11).
 *
 * Gestartet wird mit derselben Grenze, die ci_lauf.py aussen fuer genau diese
 * Dateien schon benutzt (--parallel 4) - sie laufen dort heute bereits
 * nebenlaeufig, es kommt also KEINE neue Konfliktklasse dazu. Und
 * `test_bsi_m5.py`, das ci_lauf bewusst ALLEIN faehrt, ist hier nicht dabei:
 * gesammelt werden ausschliesslich .js-Dateien.
 *
 * Die AUSWERTUNG bleibt unten seriell in DATEIREIHENFOLGE - eine Bilanz, die
 * sich bei gleichem Code von Lauf zu Lauf anders sortiert, ist keine Messung.
 *
 * Der Starter liegt als EIGENE Datei in tests/lib/, nicht als Zeichenkette im
 * Waechter: ein eingebettetes Node-Skript ist nicht diagnostizierbar - am
 * 2026-10-11 lautete ein Abbruchgrund woertlich "node lieferte nichts
 * Lesbares:  s/loader:1613:10)". */
const GRENZE = Math.max(1, Number(process.env.PROLOG_PARALLEL || 4) || 4);
{
    const auftrag = path.join(ablage, "_auftrag.json");
    fs.writeFileSync(auftrag, JSON.stringify({
        wurzel: WURZEL, ablage, namen: dateien, grenze: GRENZE, zeitdeckel_ms: 300000,
    }));
    const r = spawnSync(process.execPath,
                        [path.join("tests", "lib", "prolog_fanout.js"), auftrag],
                        { cwd: WURZEL, encoding: "utf8", timeout: 300000 * 4 });
    // Ein Starter, der selbst scheitert, darf nicht als "keine Luecke"
    // durchgehen: ohne .jsonl-Dateien waere jede Pruefung unten trivial wahr.
    if (r.status !== 0) {
        abbruch("der Starter (tests/lib/prolog_fanout.js) endete mit "
                + (r.status === null ? "Zeitdeckel" : "Exit " + r.status) + ": "
                + String(r.stderr || "").trim().split("\n").slice(0, 2).join(" | "));
    }
    const gestartet = String(r.stdout || "").split("\n").filter(Boolean).length;
    check(gestartet === dateien.length,
          "alle " + dateien.length + " Pruefstaende gestartet (" + GRENZE + " gleichzeitig)",
          "gemeldet: " + gestartet);
    if (gestartet !== dateien.length) {
        abbruch("der Starter meldet " + gestartet + " von " + dateien.length
                + " - fuer die uebrigen ist \"keine Luecke\" keine Aussage.");
    }
}

try {
    for (const name of dateien) {
        const ziel = path.join(ablage, name + ".jsonl");
        let saetze = [];
        try {
            saetze = fs.readFileSync(ziel, "utf8").split("\n").filter(Boolean)
                       .map(z => JSON.parse(z));
        } catch (e) { /* keine Datei = kein eval beobachtet */ }

        const evals = saetze.filter(s => s.art === "eval");
        const fenster = saetze.filter(s => s.art === "fenster").length;
        evalsGesamt += evals.length;
        /* ⚠ POSITIVKONTROLLE JE DATEI, und sie muss am GEBAUTEN FENSTER
         * haengen, nicht an der statischen Vorauswahl. Wer kein Fenster baut,
         * hat keinen Prolog – `test_sitzung_pruefstand.js` liest fremde
         * Pruefstaende nur als Text und traegt deshalb `.eval(` und einen
         * frontend-Pfad im Quelltext, ohne je etwas auszufuehren. Das ist kein
         * Mangel, aber es muss BENANNT werden statt stillschweigend als
         * "keine Luecke" durchzugehen. Ein Fenster OHNE eval dagegen heisst:
         * die Beobachtung lief nicht – dann ist "keine Luecke" eine
         * Falschaussage. */
        if (!fenster) { ohneFenster.push(name); continue; }
        if (!evals.length) { ohneEval.push(name); continue; }
        saetze.filter(s => s.art === "werkzeugfehler")
              .forEach(s => werkzeugfehler.push(name + ": " + String(s.grund).split("\n")[0]));
        saetze.filter(s => s.art === "parsefehler")
              .forEach(s => parsefehler.push(name + ": " + s.grund));

        const nachHerkunft = { schnitt: new Map(), nachbarmodul: new Map(), umgebung: new Map() };
        for (const s of evals) for (const f of s.fehlend || []) {
            const topf = nachHerkunft[pruefer.einteilen(f.name, index)];
            topf.set(f.name, (topf.get(f.name) || 0) + 1);
        }
        if (nachHerkunft.schnitt.size) {
            luecken.push(name + " → " + [...nachHerkunft.schnitt]
                .map(([n, c]) => n + " (" + c + "×)").join(", "));
        }
        for (const art of ["nachbarmodul", "umgebung"]) {
            for (const [n] of nachHerkunft[art]) nebenbefunde[art].add(n);
            if (nachHerkunft[art].size) nebenbefundeDateien[art].add(name);
        }
    }
} finally {
    fs.rmSync(ablage, { recursive: true, force: true });
}

check(werkzeugfehler.length === 0,
      "die Beobachtung lief ohne eigenen Defekt", kurz(werkzeugfehler, 3));
if (werkzeugfehler.length) abbruch("das Messwerkzeug hat selbst geworfen.");

check(ohneEval.length === 0,
      "jeder Pruefstand, der ein Fenster BAUT, hat darin auch evaluiert ("
      + evalsGesamt + " evals insgesamt)", kurz(ohneEval, 8));
if (ohneEval.length) {
    abbruch(ohneEval.length + " Pruefstand(e) haben ein Fenster gebaut und nichts darin "
            + "evaluiert – fuer sie ist \"keine Luecke\" keine Aussage.");
}
if (ohneFenster.length) {
    console.log("  ·    " + ohneFenster.length + " Datei(en) bauen gar kein Fenster und "
                + "haben damit keinen Prolog: " + ohneFenster.join(", "));
    console.log("       (sie lesen Frontend-Code nur als TEXT – kein Mangel, aber auch "
                + "keine Messung)");
}

check(parsefehler.length === 0,
      "jeder evaluierte Prolog ist parsebar", kurz(parsefehler, 3));

check(luecken.length === 0,
      "kein Prolog verliert einen Namen, den der geschnittene Code deklariert",
      kurz(luecken, 10));

/* ── Die zwei anderen Herkuenfte: gezaehlt und benannt, nicht gewertet ───── */
abschnitt("4 · Nebenbefunde (andere Herkunft, nicht Befund DIESER Regel)");
const sortiert = (s) => [...s].sort();
console.log("  · Nachbarmodul nicht geladen (als `window.X =` exportiert): "
            + nebenbefundeDateien.nachbarmodul.size + " Pruefstaende, Namen: "
            + (sortiert(nebenbefunde.nachbarmodul).join(", ") || "keine"));
console.log("    Der Register-Eintrag dazu ist bezahlt (JarvisIcons.pencil, 2026-10-06:");
console.log("    fuenf Pruefstaende mit Teil-Attrappe brachen auf einmal). Die Abhilfe ist");
console.log("    dort das ECHTE Modul zu laden - ein eigener Vorgang, eigene Messung.");
console.log("  · Umgebung (jsdom stellt sie nicht): "
            + nebenbefundeDateien.umgebung.size + " Pruefstaende, Namen: "
            + (sortiert(nebenbefunde.umgebung).join(", ") || "keine"));
console.log("    `fetch`, `TextEncoder`, `requestAnimationFrame`, `ResizeObserver` & Co.");
console.log("    fehlen im jsdom-Fenster; betroffen sind Zweige, die kein Testfall");
console.log("    betritt. Das ist eine Frage der Abdeckung, nicht des Prologs.");

/* ── Bilanz ───────────────────────────────────────────────────────────────── */
console.log("\n" + "═".repeat(70));
console.log("Ergebnis: " + ok + " OK, " + fail + " FAIL  ("
            + dateien.length + " Pruefstaende, " + evalsGesamt + " evals geprueft)");
process.exit(fail ? 1 : 0);
