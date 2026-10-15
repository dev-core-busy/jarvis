/* Prueft, ob Code, der in ein jsdom-Fenster evaluiert wird, einen Namen
 * referenziert, den NIEMAND stellt.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT. Rund 85 Pruefstaende schneiden Funktionen aus
 * `frontend/js/*.js` heraus und bauen sich dafuer je einen eigenen Prolog, den
 * sie per `window.eval()` ausfuehren. Kommt im Produktivcode ein Helfer oder
 * eine Modulkonstante dazu, stirbt jeder dieser Prologe mit einem nackten
 * `ReferenceError` – je nach Ort unbehandelt (Exit 1 ohne Bilanz, in diesem
 * Projekt die Sprache fuer "der Waechter beisst") oder in einem `catch`
 * verschluckt (dann trivial gruene Pruefungen). Belegte Faelle:
 *   · 2026-09-29  `_selMode`/`_selIds` in `_renderSidebar` – zwei FREMDE Proben
 *                 starben, waehrend der eigene Waechter gruen war.
 *   · 2026-10-11  `_bildMimeAusBytes` in `addFiles` – `lies_chat_vorschau.js`
 *                 starb mitten in seiner Tabelle.
 * Das Register ermahnt dazu zweimal. Eine Ermahnung muss jemand lesen; eine
 * Regel beisst von selbst.
 *
 * ⚠ GEMESSEN WIRD AM ORT DES GESCHEHENS, nicht statisch nachgebaut. Die
 * Prologe entstehen zur LAUFZEIT (Template-Literal aus mehreren Schnitten) –
 * ein Waechter, der sie aus dem Quelltext der Pruefstaende rekonstruiert,
 * misst seine eigene Nachbildung. Stattdessen wird `window.eval`
 * instrumentiert: dort liegt der fertige Prolog als Zeichenkette vor.
 * Eingehaengt wird ueber `tests/lib/jsdom_laden.js` – die EINE Quelle, durch
 * die jeder Pruefstand sein JSDOM holt (`test_jsdom_einbindung.js` haelt das
 * als Regel fest). Kein Pruefstand muss dafuer angefasst werden.
 *
 * ⚠ KEINE GEPFLEGTE LISTE VON GLOBALEN. Ob ein Name von der Umgebung gestellt
 * wird, entscheidet `name in window` am ECHTEN Fenster – gemessen, nicht
 * aufgezaehlt. Eine Liste waere an dem Tag unvollstaendig, an dem jsdom etwas
 * ergaenzt oder ein Pruefstand ein `w.fetch = …` setzt. (Gemessen: `document`,
 * `atob`, `File`, `Promise`, `Set`, `localStorage` sind im Fenster, `fetch`
 * NICHT – das stellen die Pruefstaende selbst.)
 *
 * ⚠ LEXIKALISCHE BINDUNGEN UEBERLEBEN DEN eval NICHT – und das war ein
 * Irrtum, den erst der Lauf aufgedeckt hat. Gemessen: nach
 * `window.eval("function f(){} var v; const c=1")` gilt `'f' in window` und
 * `'v' in window`, aber `'c' in window` ist FALSCH. Ich hatte daraus
 * geschlossen, `c` sei fuer einen SPAETEREN eval trotzdem da, und fuehrte
 * dafuer je Fenster eine Menge frueher gebundener Namen mit. Falsch:
 * `window.eval("const c = 2")` gefolgt von `window.eval("c + 1")` wirft
 * `ReferenceError: c is not defined`. Die mitgefuehrte Menge haette also eine
 * ECHTE Luecke verdeckt. Sie ist weg; `var`/`function` deckt `name in window`
 * ohnehin ab, und `const`/`let` sind beim naechsten eval wirklich nicht mehr
 * da. Dass ein Pruefstand seinen Prolog in EINEM Stueck evaluiert, ist kein
 * Zufall, sondern Notwendigkeit.
 *
 * ⚠ DIE BINDUNGEN WERDEN FLACH GESAMMELT, nicht je Geltungsbereich. Das ist
 * ABSICHT und die sichere Richtung: ein Name, der in einer verschachtelten
 * Funktion deklariert ist, gilt hier ueberall als gebunden. Dadurch kann der
 * Waechter einen Gueltigkeitsfehler UEBERSEHEN (dafuer gibt es
 * `test_js_reichweite.js`), aber er kann keinen ERFINDEN – und ein Fehlalarm
 * ueber 85 Dateien waere schlimmer als eine Luecke: er wuerde den Waechter
 * innerhalb einer Woche abgeschaltet. Der gesuchte Fall ist ein Helfer, der
 * NIRGENDS deklariert ist; flach oder verschachtelt macht dafuer keinen
 * Unterschied.
 *
 * Benutzung (setzt `jarvis_laden`; nichts davon laeuft im Normalbetrieb):
 *     PROLOG_PRUEFUNG=<datei> node tests/test_irgendwas.js
 * Jede Fundstelle wird als JSON-Zeile an <datei> angehaengt – NICHT nach
 * stdout: die Ausgabe eines Pruefstands ist sein Messergebnis und wird nicht
 * mit Diagnose vermischt.
 */
"use strict";

const fs = require("fs");

/* ── Syntaxbaum ───────────────────────────────────────────────────────────── */

function parser() {
    // Lazy: ein Normallauf laedt acorn nie.
    return require("./acorn_laden")();
}

function baum(quelle) {
    return parser().parse(quelle, {
        ecmaVersion: 2023, locations: true,
        allowReturnOutsideFunction: true,   // mehrere Prologe nutzen CJS-Verhalten
        allowAwaitOutsideFunction: true,
        allowSuperOutsideMethod: true,
    });
}

function gehe(knoten, fn, eltern = []) {
    if (!knoten || typeof knoten !== "object") return;
    if (Array.isArray(knoten)) { knoten.forEach(k => gehe(k, fn, eltern)); return; }
    if (typeof knoten.type === "string") { fn(knoten, eltern); eltern = eltern.concat([knoten]); }
    for (const feld in knoten) {
        if (feld === "type" || feld === "loc" || feld === "start" || feld === "end") continue;
        gehe(knoten[feld], fn, eltern);
    }
}

/** Jeden Namen eines Bindungsmusters einsammeln – auch aus Destrukturierung,
 *  Vorgabewerten und Rest-Elementen. Wer hier ein Muster vergisst, erzeugt
 *  Fehlalarme fuer voellig richtigen Code. */
function musterNamen(knoten, hinein) {
    if (!knoten) return;
    switch (knoten.type) {
        case "Identifier": hinein.add(knoten.name); break;
        case "ObjectPattern":
            knoten.properties.forEach(p =>
                musterNamen(p.type === "RestElement" ? p.argument : p.value, hinein));
            break;
        case "ArrayPattern": knoten.elements.forEach(e => musterNamen(e, hinein)); break;
        case "AssignmentPattern": musterNamen(knoten.left, hinein); break;
        case "RestElement": musterNamen(knoten.argument, hinein); break;
        default: break;
    }
}

/** Alles, was dieses Stueck Code SELBST bindet.
 *
 *  ⚠ `arguments` STEHT IN JEDER NICHT-PFEIL-FUNKTION IMPLIZIT ZUR VERFUEGUNG –
 *  es wird nirgends deklariert und ist trotzdem gebunden. Die erste Fassung
 *  hat es als fehlenden Namen gemeldet und damit zwei Pruefstaende
 *  (`test_stt_lokal`, `test_chat_release_ui`) als Befund ausgegeben, in denen
 *  voellig richtiger Code steht. Ein Fehlalarm ueber 85 Dateien ist schlimmer
 *  als eine Luecke: er schaltet den Waechter ab. */
function gebundene(wurzel) {
    const namen = new Set();
    gehe(wurzel, (k) => {
        if (k.type === "FunctionDeclaration" || k.type === "FunctionExpression") {
            namen.add("arguments");
        }
        if ((k.type === "FunctionDeclaration" || k.type === "ClassDeclaration") && k.id) {
            namen.add(k.id.name);
        }
        /* ⚠ EIN BENANNTER AUSDRUCK BINDET SEINEN NAMEN – NACH INNEN.
         * `window.cronManager = new (class JarvisCronManager { … })` ist die
         * Hausform von cron.js und audit.js. Die erste Fassung kannte nur
         * `ClassDeclaration` und meldete `JarvisCronManager` /
         * `JarvisAuditManager` als fehlend – in DREI Pruefstaenden, die die
         * Datei sogar GANZ evaluieren, also gar nichts geschnitten haben.
         * Dasselbe gilt fuer `const f = function g() { … }`. */
        if ((k.type === "FunctionExpression" || k.type === "ClassExpression") && k.id) {
            namen.add(k.id.name);
        }
        if (k.type === "VariableDeclarator") musterNamen(k.id, namen);
        if (k.type === "FunctionDeclaration" || k.type === "FunctionExpression"
            || k.type === "ArrowFunctionExpression") {
            k.params.forEach(p => musterNamen(p, namen));
        }
        if (k.type === "CatchClause" && k.param) musterNamen(k.param, namen);
        if (k.type === "ImportDeclaration") {
            k.specifiers.forEach(s => s.local && namen.add(s.local.name));
        }
    });
    return namen;
}

/** Jeder Name, der als WERT gelesen oder geschrieben wird. Eigenschaftsnamen
 *  gehoeren nicht dazu – `a.foo` sagt nichts ueber einen Namen `foo`. */
function referenzen(wurzel) {
    const treffer = new Map();   // name -> erste Zeile
    gehe(wurzel, (k, eltern) => {
        if (k.type !== "Identifier") return;
        const p = eltern[eltern.length - 1];
        if (!p) return;
        // a.foo / a?.foo – aber a[foo] IST eine Referenz auf foo
        if (p.type === "MemberExpression" && p.property === k && !p.computed) return;
        // { foo: 1 } – aber { foo } (shorthand) IST eine Referenz
        if (p.type === "Property" && p.key === k && !p.computed && !p.shorthand) return;
        if (p.type === "MethodDefinition" && p.key === k && !p.computed) return;
        if (p.type === "PropertyDefinition" && p.key === k && !p.computed) return;
        // Deklarationsstellen sind Bindungen, keine Referenzen
        // Der NAME einer Deklaration oder eines benannten Ausdrucks ist eine
        // Bindung, keine Referenz – `ClassExpression` eingeschlossen.
        if ((p.type === "FunctionDeclaration" || p.type === "ClassDeclaration"
             || p.type === "FunctionExpression" || p.type === "ClassExpression")
            && p.id === k) return;
        if (p.type === "VariableDeclarator" && p.id === k) return;
        if (p.type === "LabeledStatement" && p.label === k) return;
        if ((p.type === "BreakStatement" || p.type === "ContinueStatement")
            && p.label === k) return;
        if (p.type === "ImportSpecifier" || p.type === "ImportDefaultSpecifier"
            || p.type === "ImportNamespaceSpecifier") return;
        if (!treffer.has(k.name)) treffer.set(k.name, k.loc.start.line);
    });
    return treffer;
}

/** Namen, die dieses Stueck Code braucht und die niemand stellt.
 *
 *  `window` entscheidet ueber die Umgebung, `bekannt` ueber frueheres eval
 *  im selben Fenster. Gibt `{ fehlend, gebunden }` oder `{ parsefehler }`. */
function luecken(quelle, window, bekannt) {
    let wurzel;
    try { wurzel = baum(quelle); }
    catch (e) {
        // Kein Urteil: ein nicht parsebarer Schnitt ist eine eigene Aussage,
        // aber kein fehlender Name. Gemeldet wird er trotzdem.
        return { parsefehler: e.message };
    }
    const gebunden = gebundene(wurzel);
    const fehlend = [];
    for (const [name, zeile] of referenzen(wurzel)) {
        if (gebunden.has(name)) continue;
        if (bekannt && bekannt.has(name)) continue;
        let imFenster = false;
        try { imFenster = window ? (name in window) : false; } catch (e) { imFenster = false; }
        if (imFenster) continue;
        fehlend.push({ name, zeile });
    }
    return { fehlend, gebunden };
}

/* ── Einteilung: woher sollte ein fehlender Name kommen? ──────────────────── */

/** Namen, die eine Datei DEKLARIERT – ohne Funktionsparameter und ohne
 *  catch-Parameter.
 *
 *  ⚠ PARAMETER GEHOEREN NICHT HINEIN, und das ist nicht Feinschliff: haette
 *  irgendwo im Frontend eine Funktion einen Parameter `fetch`, `localStorage`
 *  oder `TextEncoder`, dann gaelte dieser Umgebungs-Name als "vom Frontend
 *  deklariert" und wuerde als Schnitt-Luecke gemeldet. Ein Parameter ist von
 *  seiner eigenen Funktion gebunden und kann durch einen Schnitt nicht
 *  verloren gehen. */
function deklarierteNamen(wurzel) {
    const namen = new Set();
    gehe(wurzel, (k) => {
        if ((k.type === "FunctionDeclaration" || k.type === "ClassDeclaration") && k.id) {
            namen.add(k.id.name);
        }
        // `window.x = new (class Name {...})` – der Klassenname ist NUR im
        // Ausdruck gebunden und geht bei einem Methoden-Schnitt verloren.
        if (k.type === "ClassExpression" && k.id) namen.add(k.id.name);
        if (k.type === "VariableDeclarator") musterNamen(k.id, namen);
    });
    return namen;
}

/** Namen, die eine Datei ans Fenster EXPORTIERT (`window.X = …`). */
function fensterExporte(wurzel) {
    const namen = new Set();
    gehe(wurzel, (k) => {
        if (k.type !== "AssignmentExpression") return;
        const l = k.left;
        if (l.type !== "MemberExpression" || l.computed) return;
        if (l.object.type !== "Identifier") return;
        if (l.object.name !== "window" && l.object.name !== "globalThis") return;
        if (l.property.type === "Identifier") namen.add(l.property.name);
    });
    return namen;
}

/** Index ueber den ausgelieferten Frontend-Code.
 *
 *  Damit wird ein fehlender Name EINGETEILT, und zwar als Eigenschaft statt
 *  ueber eine gepflegte Liste:
 *    · deklariert, nicht ans Fenster exportiert -> der SCHNITT hat ihn
 *      verloren (`_lbAtts`, `_selSetze`, ein Klassenname). Das ist die Regel.
 *    · ans Fenster exportiert -> ein NACHBARMODUL ist nicht geladen
 *      (`JarvisIcons`). Andere Frage, eigene Zeile.
 *    · nirgends deklariert -> die UMGEBUNG soll ihn stellen (`fetch`,
 *      `TextEncoder`, `requestAnimationFrame`). Nicht Sache dieses Waechters.
 *
 *  Ein Parsefehler wird GEMELDET, nicht uebergangen: ein unvollstaendiger
 *  Index verschiebt eine Schnitt-Luecke stillschweigend in die Umgebung. */
function frontendIndex(dateien) {
    const deklariert = new Set(), amFenster = new Set(), parsefehler = [];
    for (const datei of dateien) {
        let wurzel;
        try { wurzel = baum(fs.readFileSync(datei, "utf8")); }
        catch (e) { parsefehler.push(datei + ": " + e.message); continue; }
        deklarierteNamen(wurzel).forEach(n => deklariert.add(n));
        fensterExporte(wurzel).forEach(n => amFenster.add(n));
    }
    return { deklariert, amFenster, parsefehler };
}

/** Einteilung eines fehlenden Namens. */
function einteilen(name, index) {
    if (index.amFenster.has(name)) return "nachbarmodul";
    if (index.deklariert.has(name)) return "schnitt";
    return "umgebung";
}

/* ── Instrumentierung ─────────────────────────────────────────────────────── */

/** Haengt die Pruefung an `window.eval`. Der Aufruf wird DURCHGEREICHT – der
 *  Pruefstand laeuft unveraendert weiter, es kommt nur eine Beobachtung dazu.
 *  Geprueft wird VOR dem eval: wirft der eval (genau der Fall, um den es
 *  geht), ist die Meldung sonst weg. */
function fensterAusstatten(window, melden) {
    if (!window || typeof window.eval !== "function") return;
    if (window.__prologBeobachtet) return;
    try { window.__prologBeobachtet = true; } catch (e) { return; }
    const echtEval = window.eval;
    window.eval = function (quelle) {
        const text = String(quelle);
        try {
            // `bekannt` ist bewusst null: was ein frueherer eval mit `var` oder
            // `function` gebunden hat, steht am Fenster und wird von
            // `name in window` erfasst; `const`/`let` ueberleben den eval NICHT
            // (gemessen, siehe Kopf). Eine mitgefuehrte Menge wuerde eine echte
            // Luecke verdecken.
            const e = luecken(text, window, null);
            if (e.parsefehler) melden({ art: "parsefehler", grund: e.parsefehler });
            else melden({ art: "eval", zeichen: text.length, fehlend: e.fehlend });
        } catch (fehler) {
            // Ein stilles Werkzeug ist schlimmer als keines: ein Defekt der
            // Pruefung muss als solcher heraus, nicht als Entwarnung.
            melden({ art: "werkzeugfehler", grund: (fehler && fehler.stack) || String(fehler) });
        }
        return echtEval.call(window, quelle);
    };
}

/** Umhuellt das jsdom-MODUL, sodass jedes `new JSDOM(...)` ein beobachtetes
 *  Fenster liefert. Ein Proxy, keine Unterklasse: so bleiben Statik
 *  (`JSDOM.fromFile`) und `instanceof` unberuehrt. */
function modulUmhuellen(modul, melden) {
    if (!modul || typeof modul.JSDOM !== "function") return modul;
    const Umhuellt = new Proxy(modul.JSDOM, {
        construct(ziel, args, neuZiel) {
            const dom = Reflect.construct(ziel, args, neuZiel);
            /* ⚠ DEN FENSTERBAU MELDEN, nicht nur die evals. Sonst ist "nichts
             * beobachtet" zweideutig: entweder hat der Pruefstand gar kein
             * Fenster gebaut (dann gibt es keinen Prolog und nichts zu messen –
             * `test_sitzung_pruefstand.js` liest fremde Pruefstaende nur als
             * TEXT), oder die Beobachtung lief nicht (dann ist "keine Luecke"
             * eine Falschaussage). Beides sieht in der Ablage gleich aus, und
             * genau diese Verwechslung ist die Fehlerklasse dieses Waechters. */
            melden({ art: "fenster" });
            try { fensterAusstatten(dom.window, melden); }
            catch (e) { melden({ art: "werkzeugfehler", grund: String(e) }); }
            return dom;
        },
    });
    const kopie = Object.create(Object.getPrototypeOf(modul));
    for (const k of Object.keys(modul)) kopie[k] = modul[k];
    kopie.JSDOM = Umhuellt;
    return kopie;
}

/** Der Einhaengepunkt fuer `jsdom_laden`: ohne `PROLOG_PRUEFUNG` unveraendert
 *  durchreichen (ein Normallauf darf nichts davon merken). */
function vielleichtUmhuellen(modul) {
    const ziel = process.env.PROLOG_PRUEFUNG;
    if (!ziel) return modul;
    const quelle = process.argv[1] || "(unbekannt)";
    const melden = (satz) => {
        try {
            fs.appendFileSync(ziel, JSON.stringify(Object.assign({ datei: quelle }, satz)) + "\n");
        } catch (e) { /* ein unbeschreibbares Ziel darf den Lauf nicht kippen */ }
    };
    return modulUmhuellen(modul, melden);
}

module.exports = {
    luecken, gebundene, referenzen, fensterAusstatten, modulUmhuellen,
    vielleichtUmhuellen, deklarierteNamen, fensterExporte, frontendIndex, einteilen,
    baum,
};
