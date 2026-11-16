#!/usr/bin/env node
/* Waechter: Kopf-Pille "Nicht bei Jira/Confluence angemeldet" (2026-11-15).
 *
 * Vorbild ist die Pille "Nicht bei SAP angemeldet" in der Titelleiste von
 * /sap (und /vemas). Auf /jira-addon und /confluence-addon fuellt sie
 * zugang_sitzung.js – AUSGEFUEHRT, nicht gelesen:
 *   - im Sitzungsbetrieb OHNE Anmeldung steht sie rot da und nennt den Bereich,
 *   - nach der Anmeldung und ausserhalb des Sitzungsbetriebs ist sie LEER
 *     (`:empty` blendet sie aus) – eine Pille, die nach dem Anmelden stehen
 *     bliebe, waere eine falsche Aussage.
 * Dazu als Regel: der Platz liegt seit 2026-11-16 in der Box „Angemeldet als …“
 * oben im Inhalt (vorher Titelleiste), und
 * die Klasse ist im CSS DIESER Seiten definiert (eine Klasse ohne Regel faellt
 * niemandem auf).
 *
 * Lauf:  node tests/test_zugang_kopf_ui.js
 */
"use strict";

require('./lib/bilanz')();

const fs = require("fs");
const path = require("path");
const WURZEL = path.resolve(__dirname, "..");
const { JSDOM } = require("./lib/jsdom_laden")();

const MODUL = fs.readFileSync(path.join(WURZEL, "frontend/js/zugang_sitzung.js"), "utf8");
const I18N = fs.readFileSync(path.join(WURZEL, "frontend/js/i18n.js"), "utf8");
const CSS = fs.readFileSync(path.join(WURZEL, "frontend/css/jira_addon.css"), "utf8");

let ok = 0, fail = 0;
function check(bed, text, info) {
    if (bed) { ok++; console.log("  OK   " + text); }
    else { fail++; console.log("  FAIL " + text + (info !== undefined ? "  [" + info + "]" : "")); }
}

// Uebersetzungswerte aus i18n.js (DE und EN muessen beide den Platzhalter tragen).
const kopfWerte = [...I18N.matchAll(/'zs\.kopf_aus':\s*'([^']*)'/g)].map((m) => m[1]);
check(kopfWerte.length === 2, "zs.kopf_aus steht in DE und EN", kopfWerte.length);
check(kopfWerte.length > 0 && kopfWerte.every((w) => w.includes("{name}")),
      "beide Fassungen nennen den Bereich ueber {name}", kopfWerte.join(" | "));

// Die Klasse ist im CSS der Seite definiert – samt Ausblenden im leeren Zustand.
check(/^\.ja-conn\s*\{/m.test(CSS), ".ja-conn ist in jira_addon.css definiert");
check(/^\.ja-conn:empty\s*\{[^}]*display:\s*none/m.test(CSS), "eine leere Pille ist unsichtbar");
check(/^\.ja-conn\.is-off\s*\{[^}]*var\(--danger\)/m.test(CSS), "der Zustand 'nicht angemeldet' ist als Warnung gefaerbt");

const SEITEN = [
    { datei: "jira_addon.html", praefix: "ja", name: "Jira" },
    { datei: "confluence_addon.html", praefix: "ca", name: "Confluence" },
];

for (const s of SEITEN) {
    console.log("\n── " + s.datei);
    const html = fs.readFileSync(path.join(WURZEL, "frontend", s.datei), "utf8");
    const dom = new JSDOM(html, { runScripts: "outside-only" });
    const w = dom.window;
    const doc = w.document;

    // Positivkontrolle: die Seite ist geladen und das Modul laeuft.
    const kopf = doc.getElementById(s.praefix + "-sz-kopf");
    check(!!kopf, s.name + ": Kopf-Pille ist im Markup");
    if (!kopf) { w.close(); continue; }
    // Seit 2026-11-16 (Vorgabe): die Pille steht in der Box "Angemeldet als …"
    // ueber den Containern (wie /wissen), NICHT mehr in der Titelleiste.
    check(!!kopf.closest(".jv-max-row .jv-anmelde-box"),
          s.name + ": die Pille sitzt in der Box \"Angemeldet als …\"");
    check(!kopf.closest("header.topbar"),
          s.name + ": die Pille steht nicht mehr in der Titelleiste");
    // Die Box ist das erste Element des Inhalts, der oberste Container ist
    // "Mein …-Zugang" (Sitzungs-Anmeldung) – Vorgabe 2026-11-16.
    const main = doc.querySelector("main");
    const sects = main ? [...main.querySelectorAll(":scope > details.ja-sect")] : [];
    check(!!main && main.firstElementChild && main.firstElementChild.classList.contains("jv-max-row"),
          s.name + ": die Box steht ganz oben im Inhalt");
    check(sects.length > 0 && sects[0].id === s.praefix + "-sz-sect",
          s.name + ": oberster Container ist die Sitzungs-Anmeldung", sects[0] && sects[0].id);
    check(!!doc.getElementById(s.praefix + "-sect-token"),
          s.name + ": eigener Container \"Wo finde ich meinen Token?\"");
    check(kopf.classList.contains("ja-conn"), s.name + ": die Pille traegt die Klasse .ja-conn");
    check(kopf.textContent.trim() === "", s.name + ": vor dem ersten Zeichnen ist sie leer");

    w.t = (k) => k;            // kein Wert → Rueckfalltext des Moduls (DE)
    w.eval(MODUL);
    check(!!(w.ZugangSitzung && w.ZugangSitzung.einrichten), s.name + ": zugang_sitzung.js ist geladen");
    if (!(w.ZugangSitzung && w.ZugangSitzung.einrichten)) { w.close(); continue; }
    const sz = w.ZugangSitzung.einrichten({
        praefix: s.praefix, name: s.name, pfad: "/x", token: () => "t", nachher: () => {},
    });

    sz.zeichnen({ sitzungs_modus: true, angemeldet: false, server_konfiguriert: true });
    check(kopf.textContent === "Nicht bei " + s.name + " angemeldet",
          s.name + ": Sitzungsbetrieb ohne Anmeldung → 'Nicht bei " + s.name + " angemeldet'", kopf.textContent);
    check(kopf.classList.contains("is-off"), s.name + ": … und als Warnung markiert");
    check(kopf.title !== "", s.name + ": … mit Erklaerung im Tooltip");

    sz.zeichnen({ sitzungs_modus: true, angemeldet: true, server_konfiguriert: true,
                  sitzung_konto: "konto.beispiel" });
    check(kopf.textContent === "" && !kopf.classList.contains("is-off"),
          s.name + ": nach der Anmeldung verschwindet die Pille", kopf.textContent);

    sz.zeichnen({ sitzungs_modus: false, angemeldet: false });
    check(kopf.textContent === "", s.name + ": ausserhalb des Sitzungsbetriebs keine Pille", kopf.textContent);

    sz.zeichnen(null);
    check(kopf.textContent === "", s.name + ": ohne Kontoauskunft keine Pille", kopf.textContent);

    // Sprachwechsel: der Text kommt aus der Uebersetzung, der Bereich bleibt.
    w.t = (k) => (k === "zs.kopf_aus" ? "Not signed in to {name}" : k);
    sz.zeichnen({ sitzungs_modus: true, angemeldet: false, server_konfiguriert: true });
    check(kopf.textContent === "Not signed in to " + s.name,
          s.name + ": die Uebersetzung wird benutzt und der Bereich eingesetzt", kopf.textContent);
    w.close();
}

console.log("\nErgebnis: " + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
