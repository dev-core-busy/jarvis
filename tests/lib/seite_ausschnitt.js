/* Ausschnitt einer grossen HTML-Seite fuer jsdom-Waechter.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT (2026-11-22, gemessen ueber alle JS-Waechter):
 * 35 % der gesamten JS-Waechterzeit (496 von 1423 s) waren 342 Aufbauten der
 * VOLLEN frontend/settings.html (690 KB, 5743 Elemente) in 65 Waechtern - je
 * Aufbau ~0,8 s (unter Last ~1,5 s), dazu ~0,2 s applyLang ueber 1091
 * i18n-Marken. Die meisten Proben brauchen davon EINEN Reiter (15-65 KB) oder
 * die Anmeldemaske. Fast die ganze Zeit steckt im Baumaufbau von jsdom selbst
 * (SymbolTree, Node-impl, CSSStyleDeclaration), nicht im Tokenisieren - einen
 * Cache "gleiche Zeichenkette, gleicher Baum" kann es deshalb nicht geben, und
 * jede Probe braucht ohnehin ein FRISCHES DOM (Register).
 *
 * Was der Ausschnitt behaelt:
 *   * den ganzen <head> (Styles, Metadaten, Skript-Tags)
 *   * jedes Element mit einer der genannten ids MIT seinem ganzen Teilbaum,
 *     Zeichen fuer Zeichen so, wie parse5 (der Parser von jsdom) es liest
 *   * die Vorfahren dieser Elemente bis <body> - mit allen Attributen (id,
 *     class, hidden, style: closest(), Sichtbarkeit und CSS-Selektoren sehen
 *     dieselbe Kette), aber ohne ihre UEBRIGEN Kinder
 *   * auf Wunsch (skripte: true) jedes <script> der Seite an seinem Ort
 * Alles andere faellt weg - auch Textknoten zwischen den Geschwistern.
 *
 * ⚠ GRENZE, die der Aufrufer kennen muss: eine Probe, die die GANZE Seite
 * misst (Anzahl aller Knoepfe, Einbindung jedes Skripts, Reihenfolge der
 * Stylesheets), gehoert NICHT auf einen Ausschnitt - sie liest den vollen
 * Text oder baut das volle DOM. Und braucht der Produktcode spaeter ein
 * Element ausserhalb des Ausschnitts, faellt die Probe rot aus statt still
 * gruen: das fehlende Element ist dann weg wie in einer kaputten Seite.
 *
 * ⚠ FEHLENDE ids MELDEN, NICHT WERFEN: `fehlend` nennt jede id, die nicht
 * vorkommt. Der Aufrufer macht daraus eine Pruefung (Positivkontrolle) - ein
 * Wurf an dieser Stelle waere Exit 1 OHNE Bilanz, also von "nicht gelaufen"
 * nicht zu unterscheiden (Register), und eine stille Luecke liesse die
 * Proben auf einem leeren DOM trivial gruen werden.
 *
 * Aufruf:
 *     const { ausschnitt } = require('./lib/seite_ausschnitt');
 *     const A = ausschnitt(HTML, ['login-screen', 'settings-tab-security']);
 *     check('Ausschnitt: alle Bereiche gefunden', A.fehlend.length === 0, A.fehlend);
 *     ... new JSDOM(A.html, {...}) ...
 *
 * Fuer Proben, die app.js ganz laufen lassen, gibt es die Gegenrichtung
 * ohneReiter() (unten): alles bleibt, nur fremde Reiter-Inhalte fallen weg.
 *
 * Waechter: tests/test_seite_ausschnitt.js, Gegenprobe tests/gegen_seite_ausschnitt.py.
 */
"use strict";

const path = require("path");
const { orte } = require("./jsdom_laden");

let _p5 = null;

/** parse5 ist eine Abhaengigkeit von jsdom, keine eigene des Repos - es wird
 *  deshalb NEBEN dem jsdom gesucht, das jsdom_laden.js findet (dieselbe
 *  Suchliste, keine zweite). Fehlt es, Exit 2 mit lesbarer Meldung. */
function parse5() {
    if (_p5) return _p5;
    for (const ort of orte()) {
        let haupt;
        try { haupt = require.resolve(ort); } catch (e) { continue; }
        try {
            _p5 = require(require.resolve("parse5", { paths: [path.dirname(haupt)] }));
            return _p5;
        } catch (e) { /* naechster Ort */ }
    }
    console.log("ABBRUCH: parse5 (Abhaengigkeit von jsdom) neben keinem jsdom gefunden: " + orte().join(", "));
    console.log("Exit 2 = konnte nicht laufen (weder bestanden noch fehlgeschlagen).");
    process.exit(2);
}

const _element = (k) => k && typeof k.tagName === "string";
const _attr = (k, name) => {
    const a = (k.attrs || []).find((x) => x.name === name);
    return a ? a.value : null;
};

function _kind(knoten, tag) {
    return (knoten.childNodes || []).find((k) => _element(k) && k.tagName === tag) || null;
}

/** Liefert { html, fehlend, vorher, nachher } - html ist ein vollstaendiges
 *  Dokument (mit Doctype), vorher/nachher die Laengen zur Auskunft. */
function ausschnitt(html, ids, opt) {
    opt = opt || {};
    const p5 = parse5();
    const doc = p5.parse(String(html));
    const wurzel = _kind(doc, "html");
    const body = wurzel && _kind(wurzel, "body");
    const gesucht = new Set(ids || []);
    if (!body) return { html: String(html), fehlend: [...gesucht], vorher: String(html).length, nachher: String(html).length };

    const ziele = new Set(), pfad = new Set(), gefunden = new Set();
    const markieren = (k) => {
        ziele.add(k);
        for (let e = k.parentNode; e && e !== body; e = e.parentNode) pfad.add(e);
    };
    // Tiefensuche ueber den Body (iterativ: settings.html ist tief verschachtelt)
    const stapel = [body];
    while (stapel.length) {
        const k = stapel.pop();
        for (const c of k.childNodes || []) {
            if (!_element(c)) continue;
            const id = _attr(c, "id");
            if (id !== null && gesucht.has(id)) { gefunden.add(id); markieren(c); continue; }
            if (opt.skripte && c.tagName === "script") markieren(c);
            stapel.push(c);
        }
    }
    const beschneiden = (k) => {
        k.childNodes = (k.childNodes || []).filter((c) => ziele.has(c) || pfad.has(c));
        for (const c of k.childNodes) if (pfad.has(c) && !ziele.has(c)) beschneiden(c);
    };
    beschneiden(body);
    const aus = p5.serialize(doc);
    return { html: aus, fehlend: [...gesucht].filter((x) => !gefunden.has(x)),
             vorher: String(html).length, nachher: aus.length };
}

/** Die Gegenrichtung fuer Proben, die app.js GANZ laufen lassen: alles bleibt
 *  stehen (Kopf, Anmeldemaske, Dialoge, Rahmen und Reiterleiste der
 *  Einstellungen), nur die Inhalte der Einstellungs-Reiter
 *  (.settings-tab-content), deren id NICHT in `behalten` steht, fallen samt
 *  Teilbaum weg.
 *
 *  ⚠ WARUM NICHT ausschnitt() MIT EINER LISTE (2026-11-23 gemessen): app.js
 *  greift beim Laden und in seinen Ablaeufen auf Dutzende Elemente ausserhalb
 *  der Reiter zu, viele ohne Null-Pruefung (Anmeldemaske, Sicherheitsband,
 *  main-screen ...). Eine Liste "was app.js braucht" waere ein Ratespiel, das
 *  jede neue Stelle in app.js bricht. Die Reiter dagegen fasst app.js nur ueber
 *  null-gepruefte Verweise an - und sie sind 486 von 690 KB der Seite.
 *  Ein Aufbau sinkt damit von ~0,9 auf ~0,3 s.
 *
 *  Liefert { html, fehlend, entfernt, vorher, nachher } - `fehlend` nennt jede
 *  id aus `behalten`, die kein Reiter traegt (Positivkontrolle der Aufrufer,
 *  wie bei ausschnitt), `entfernt` die ids der weggefallenen Reiter. */
function ohneReiter(html, behalten) {
    const p5 = parse5();
    const doc = p5.parse(String(html));
    const bleibt = new Set(behalten || []);
    const gefunden = new Set(), entfernt = [];
    const istReiter = (k) => _element(k) && /(^|\s)settings-tab-content(\s|$)/.test(_attr(k, "class") || "");
    const stapel = [doc];
    while (stapel.length) {
        const k = stapel.pop();
        if (!k.childNodes) continue;
        k.childNodes = k.childNodes.filter((c) => {
            if (!istReiter(c)) return true;
            const id = _attr(c, "id");
            if (id !== null && bleibt.has(id)) { gefunden.add(id); return true; }
            entfernt.push(id);
            return false;
        });
        for (const c of k.childNodes) stapel.push(c);
    }
    const aus = p5.serialize(doc);
    return { html: aus, fehlend: [...bleibt].filter((x) => !gefunden.has(x)), entfernt,
             vorher: String(html).length, nachher: aus.length };
}

module.exports = { ausschnitt, ohneReiter, parse5 };
