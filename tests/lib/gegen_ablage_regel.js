/* Regel am Syntaxbaum: jede JS-Gegenprobe mit Home-Ablage raeumt sie per Helfer ab.
 *
 * Gegenstueck zu Teil B von tests/test_gegen_ablage.py (dort fuer gegen_*.py),
 * hier fuer tests/gegen_*.js - als eigene Datei, nicht als Zeichenkette im
 * Python-Waechter (ein eingebettetes Node-Skript ist nicht diagnostizierbar,
 * Register 2026-10-11). Der Waechter ruft sie auf und prueft sie vorher an
 * synthetischen Quellen.
 *
 * Erfasst wird eine Ablage = `const X = path.join(os.homedir(), ...)` auf
 * oberster Ebene, die als VERZEICHNIS benutzt wird (`fs.mkdirSync(X ...)` oder
 * `path.join(X, ...)`). Fuer jede muss gelten:
 *   * ein Aufruf `<...>.abraeumenBeimEnde(X, ...)` auf oberster Ebene, NACH
 *     der Zuweisung (ein Aufruf in einer Funktion oder nur im Kommentar zaehlt
 *     nicht);
 *   * gibt es eine Laufmarke `const MARKE|LAUF... = path.join(X, ...)`, steht
 *     sie im Optionsobjekt (`{ marke: MARKE }`);
 *   * KEIN `process.on("exit", ...)` auf oberster Ebene HINTER dem Aufruf:
 *     Node fuehrt exit-Handler in Anmelde-Reihenfolge aus - ein Zuruecklegen,
 *     das danach angemeldet ist, liefe erst NACH dem Abraeumen, und der Helfer
 *     saehe den sabotierten Baum.
 *
 * Aufruf: node tests/lib/gegen_ablage_regel.js <datei> [...]
 * Ausgabe: JSON {datei: {ablagen: [...], befunde: [...]}} auf stdout.
 * Exit 0 = ausgewertet, 2 = Werkzeug fehlt / Datei unlesbar.
 */
"use strict";

const fs = require("fs");
const acorn = require("./acorn_laden")();

const OPT = { ecmaVersion: "latest", sourceType: "script", allowHashBang: true,
              allowReturnOutsideFunction: true, locations: true };

function gehe(n, f) {
    if (!n || typeof n.type !== "string") return;
    f(n);
    for (const k of Object.keys(n)) {
        const v = n[k];
        if (Array.isArray(v)) v.forEach((c) => gehe(c, f));
        else if (v && typeof v.type === "string") gehe(v, f);
    }
}
const istAufruf = (n, objekt, methode) => n && n.type === "CallExpression"
    && n.callee.type === "MemberExpression" && !n.callee.computed
    && n.callee.property.name === methode
    && (objekt === null || (n.callee.object.type === "Identifier" && n.callee.object.name === objekt));
const istHomedir = (n) => { let ja = false; gehe(n, (c) => { if (istAufruf(c, "os", "homedir")) ja = true; }); return ja; };
const ersterArgName = (c) => c.arguments[0] && c.arguments[0].type === "Identifier" ? c.arguments[0].name : null;

function oberste(baum) {
    // [{art, name, zeile, init, aufruf}] fuer Zuweisungen und Aufrufe auf oberster Ebene
    const aus = [];
    for (const st of baum.body) {
        if (st.type === "VariableDeclaration") {
            for (const d of st.declarations) {
                if (d.id.type === "Identifier" && d.init) {
                    aus.push({ art: "const", name: d.id.name, zeile: st.loc.start.line, init: d.init });
                }
            }
        } else if (st.type === "ExpressionStatement") {
            aus.push({ art: "ausdruck", zeile: st.loc.start.line, aufruf: st.expression });
        }
    }
    return aus;
}

function befunde(quelle) {
    const baum = acorn.parse(quelle, OPT);
    const top = oberste(baum);
    const alsVerzeichnis = (name) => {
        let ja = false;
        gehe(baum, (c) => {
            if ((istAufruf(c, "fs", "mkdirSync") || istAufruf(c, "path", "join")) && ersterArgName(c) === name) ja = true;
        });
        return ja;
    };
    const ablagen = top.filter((t) => t.art === "const" && istAufruf(t.init, "path", "join")
                                     && istHomedir(t.init) && alsVerzeichnis(t.name));
    const aus = [];
    for (const a of ablagen) {
        const marken = top.filter((t) => t.art === "const" && /^(MARKE|LAUF)/i.test(t.name)
                                         && istAufruf(t.init, "path", "join") && ersterArgName(t.init) === a.name);
        const aufrufe = top.filter((t) => t.art === "ausdruck" && istAufruf(t.aufruf, null, "abraeumenBeimEnde")
                                          && ersterArgName(t.aufruf) === a.name);
        if (!aufrufe.length) { aus.push(a.name + ": kein abraeumenBeimEnde(" + a.name + ") auf oberster Ebene"); continue; }
        const z = aufrufe[0];
        if (z.zeile < a.zeile) aus.push(a.name + ": Aufruf (Zeile " + z.zeile + ") vor der Zuweisung (Zeile " + a.zeile + ")");
        const spaet = top.filter((t) => t.art === "ausdruck" && istAufruf(t.aufruf, "process", "on")
                                        && t.aufruf.arguments[0] && t.aufruf.arguments[0].value === "exit"
                                        && t.zeile > z.zeile);
        if (spaet.length) aus.push(a.name + ": process.on(\"exit\") (Zeile " + spaet[0].zeile
                                   + ") steht HINTER dem Abraeumen - es liefe vor dem Zuruecklegen");
        if (marken.length) {
            const o = z.aufruf.arguments[1];
            const ok = o && o.type === "ObjectExpression" && o.properties.some((p) =>
                p.key && (p.key.name === "marke" || p.key.value === "marke")
                && p.value.type === "Identifier" && marken.some((m) => m.name === p.value.name));
            if (!ok) aus.push(a.name + ": Laufmarke " + marken[0].name + " nicht uebergeben");
        }
    }
    return { ablagen: ablagen.map((a) => a.name), befunde: aus };
}

module.exports = { befunde };

if (require.main === module) {
    const erg = {};
    for (const datei of process.argv.slice(2)) {
        try { erg[datei] = befunde(fs.readFileSync(datei, "utf8")); }
        catch (e) { process.stderr.write("ABBRUCH: " + datei + ": " + e.message + "\n"); process.exit(2); }
    }
    process.stdout.write(JSON.stringify(erg) + "\n");
}
