#!/usr/bin/env node
/* Waechter fuer die Browser-Erweiterung (browser-addon/).
 *
 * Zwei Teile:
 *  1. Struktur und Regeln – Manifeste, Rechte-Zuschnitt, Feldnamen, und die
 *     Frage, wo gefetcht werden darf (das ist unter MV3 keine Stilfrage).
 *  2. Das Einfuegen wird gegen ein nachgebautes Jira-DOM WIRKLICH AUSGEFUEHRT.
 *     Ein Quelltext-Test wuerde hier nichts belegen: die Funktion wird von
 *     scripting.executeScript serialisiert und in fremdem Kontext neu
 *     ausgewertet – ob sie das ueberlebt, sieht man nur, wenn man es tut.
 *
 * jsdom rechnet KEIN Layout: `getBoundingClientRect` liefert ueberall Nullen.
 * Die Sichtbarkeitspruefung wird deshalb im Test gezielt versorgt, statt sie
 * auszubauen – sonst pruefte der Test eine andere Funktion als die echte.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const WURZEL = path.resolve(__dirname, "..");
const ADDON = path.join(WURZEL, "browser-addon");

let ok = 0, fail = 0;
function check(bed, text, extra) {
  if (bed) { ok++; console.log("  OK   " + text); }
  else { fail++; console.log("  FAIL " + text + (extra ? " – " + extra : "")); }
}
function section(t) { console.log("\n═══ " + t); }

const lies = (p) => fs.readFileSync(path.join(ADDON, p), "utf8");

/* Kommentare weg – ein Waechter darf nicht seine eigene Begruendung lesen.
 * Im Projekt neun belegte Faelle; in dieser Datei waere es besonders leicht,
 * weil die Begruendungen die gesuchten Bezeichner woertlich nennen. */
function ohneKommentare(t) {
  return t.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

const M_CHROME = JSON.parse(lies("manifest.json"));
const M_FF = JSON.parse(lies("manifest.firefox.json"));
const BG = lies("background.js");
const POPUP_JS = lies("popup.js");
const POPUP_HTML = lies("popup.html");
const EINFUEGEN = lies("einfuegen.js");

// ═══════════════════════════════════════════════════════════════════════════
section("1) Manifeste: eine Erweiterung, zwei Bauformen");
// ═══════════════════════════════════════════════════════════════════════════
check(M_CHROME.manifest_version === 3 && M_FF.manifest_version === 3,
      "beide sind Manifest V3");
check(M_CHROME.version === M_FF.version,
      "beide tragen dieselbe Version", M_CHROME.version + " / " + M_FF.version);

// Firefox kennt background.service_worker NICHT (MDN: Event Pages statt
// Service Worker). Ein Chrome-Manifest in Firefox laedt den Hintergrund gar
// nicht – und die Erweiterung sieht aus, als tue sie nichts.
check(!!(M_CHROME.background && M_CHROME.background.service_worker),
      "Chrome/Edge: background.service_worker");
check(!!(M_FF.background && Array.isArray(M_FF.background.scripts)),
      "Firefox: background.scripts (Event Page)");
check(!M_FF.background.service_worker,
      "Firefox-Manifest hat KEINEN service_worker");
check(!!(M_FF.browser_specific_settings
         && M_FF.browser_specific_settings.gecko
         && M_FF.browser_specific_settings.gecko.id),
      "Firefox: gecko.id gesetzt (Pflicht zum Signieren)");

// DER ZUSCHNITT DER RECHTE. Ein Content-Script auf https://*/* verlangt bei der
// Installation "Alle deine Daten auf allen Websites lesen und aendern".
for (const [name, m] of [["Chrome", M_CHROME], ["Firefox", M_FF]]) {
  check(!m.content_scripts,
        name + ": kein dauerhaftes Content-Script (activeTab statt Vollzugriff)");
  check(!m.host_permissions,
        name + ": keine festen host_permissions");
  check(Array.isArray(m.optional_host_permissions)
        && m.optional_host_permissions.length > 0,
        name + ": Host-Rechte werden ERST zur Laufzeit erfragt");
  check((m.permissions || []).includes("activeTab"),
        name + ": activeTab");
  check(!(m.permissions || []).includes("tabs"),
        name + ": KEINE weitreichende tabs-Berechtigung");
}

// DIE SERVERADRESSE DARF NICHT INS MANIFEST. Eine Firefox-Erweiterung muss von
// Mozilla signiert sein, auch die selbst verteilte – eine signierte Datei laesst
// sich nicht pro Server umschreiben, ohne die Signatur zu brechen. Stuende die
// Adresse hier, braeuchte jeder Kunde ein eigenes Paket (Drift-Muster).
const beideManifeste = JSON.stringify(M_CHROME) + JSON.stringify(M_FF);
check(!/https:\/\/(?!\*)[a-z0-9.-]+\.[a-z]{2,}/i.test(beideManifeste),
      "keine feste Serveradresse im Manifest");

// ═══════════════════════════════════════════════════════════════════════════
section("2) Netzaufrufe NUR im Hintergrund");
// ═══════════════════════════════════════════════════════════════════════════
// Unter MV3 unterliegen Content-Scripts der CORS-Regel der Seite; host_permissions
// wirken dort nicht (MDN: "Only backend scripts have elevated cross-domain
// privileges"). Live gemessen antwortet der Jarvis-Server einem Preflight von
// chrome-extension:// mit 400 – aus dem Hintergrund entsteht keiner.
check(/\bfetch\s*\(/.test(ohneKommentare(BG)),
      "background.js fetcht");
check(!/\bfetch\s*\(/.test(ohneKommentare(POPUP_JS)),
      "popup.js fetcht NICHT (sonst schliesst das Popup den Aufruf mit sich)");
check(!/\bfetch\s*\(/.test(ohneKommentare(EINFUEGEN)),
      "das injizierte Skript fetcht NICHT (dort gilt CORS der Jira-Seite)");
check(/credentials:\s*["']omit["']/.test(BG),
      "keine Cookies – Jarvis authentifiziert per Bearer-Header");

// ═══════════════════════════════════════════════════════════════════════════
section("3) Der Feldname des 2FA-Codes");
// ═══════════════════════════════════════════════════════════════════════════
// Im Outlook-Add-in stand hier einmal `totp` statt `totp_code`. Ergebnis: eine
// Anmeldeschleife OHNE Fehlermeldung – der Server sah schlicht keinen Code.
const bgOhne = ohneKommentare(BG);
check(/totp_code\s*:/.test(bgOhne), "der Login-Rumpf sendet totp_code");
check(!/[^_]totp\s*:\s*(?:totp|nachricht)/.test(bgOhne.replace(/totp_code/g, "X")),
      "es wird KEIN Feld namens 'totp' gesendet");

// Gegenprobe an der Wahrheit: main.py liest genau diesen Namen.
const MAIN = fs.readFileSync(path.join(WURZEL, "backend", "main.py"), "utf8");
check(/["']totp_code["']/.test(MAIN),
      "backend/main.py liest 'totp_code' – die Namen passen zusammen");

// ═══════════════════════════════════════════════════════════════════════════
section("4) Das Token ueberlebt den Browser nicht");
// ═══════════════════════════════════════════════════════════════════════════
check(/storage\.session/.test(bgOhne),
      "der Token liegt in storage.session");
check(!/storage\.local\.set\([^)]*token/i.test(bgOhne),
      "der Token wird NICHT in storage.local geschrieben");
check(/storage\.local/.test(bgOhne),
      "die Serveradresse dagegen schon (sie ist kein Geheimnis)");

// ═══════════════════════════════════════════════════════════════════════════
section("5) Die injizierte Funktion ist SELBSTSTAENDIG");
// ═══════════════════════════════════════════════════════════════════════════
// scripting.executeScript serialisiert sie per toString und wertet sie in der
// Seite neu aus. Jede Referenz nach draussen wird dort zu einem ReferenceError,
// der im Popup als "Einfuegen fehlgeschlagen" ankommt.
const koerper = EINFUEGEN.slice(EINFUEGEN.indexOf("export function einfuegenInJira"));
check(!/\bimport\b/.test(koerper), "kein import in der Funktion");
for (const fremd of ["api.", "chrome.", "browser.", "$(", "frage(", "melde("]) {
  check(!koerper.includes(fremd),
        "keine Referenz auf '" + fremd + "' (Modul-Scope)");
}

// ═══════════════════════════════════════════════════════════════════════════
section("6) Einfuegen gegen ein nachgebautes Jira – WIRKLICH ausgefuehrt");
// ═══════════════════════════════════════════════════════════════════════════
/* Die Funktion wird so geladen, wie der Browser sie sieht: als Quelltext, neu
 * ausgewertet. Damit wird zugleich belegt, dass die Serialisierung traegt. */
function ladeEinfuegen(fenster) {
  const quelle = EINFUEGEN.replace("export function", "function");
  const f = new fenster.Function(
    quelle + "\nreturn einfuegenInJira;")();
  return f;
}

function mitDom(html, arbeit) {
  // runScripts ist Pflicht, nicht Beiwerk: ohne das liefert `window.Function`
  // eine Funktion, deren globaler Scope NICHT das jsdom-Fenster ist – sie sieht
  // dann kein `document` und stirbt mit ReferenceError. "outside-only" genuegt
  // (die Seite selbst soll nichts ausfuehren).
  const dom = new JSDOM(html, { url: "https://jira.test/browse/ABC-1",
                                runScripts: "outside-only" });
  const w = dom.window;
  // jsdom rechnet kein Layout – ohne das haelt die Funktion JEDES Feld fuer
  // unsichtbar und faellt immer auf den Fehlerzweig. Gemessen wird die echte
  // Logik, nur die Geometrie wird gestellt.
  w.Element.prototype.getBoundingClientRect = function () {
    return this.hasAttribute("data-unsichtbar")
      ? { width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 }
      : { width: 300, height: 80, top: 0, left: 0, right: 300, bottom: 80 };
  };
  w.Element.prototype.scrollIntoView = function () {};
  // Ein Wurf darf den Lauf nicht ABBRECHEN – sonst sieht ein Fehler aus wie
  // "nicht gelaufen" und eine Gegenprobe waere gruen aus dem falschen Grund
  // (Register: eine Pruefung darf nicht werfen).
  try {
    return arbeit(w, ladeEinfuegen(w));
  } catch (e) {
    check(false, "Lauf gegen das nachgebaute DOM", String(e && e.message || e));
    return null;
  } finally {
    w.close();
  }
}

const TEXT = "Guten Tag,\n\ndas Problem ist behoben.\n\nViele Grüße";

// a) Jira Server/DC, klassischer Editor
mitDom('<form><textarea id="comment"></textarea></form>', (w, f) => {
  const r = f(TEXT);
  check(r.ok === true, "textarea #comment: Einfuegen meldet Erfolg", JSON.stringify(r));
  check(w.document.getElementById("comment").value === TEXT,
        "der Text steht wirklich im Feld");
});

// b) Der Wert muss als input-Ereignis ankommen – sonst merkt ein Framework
//    nichts davon und das Feld ist beim Absenden wieder leer.
mitDom('<textarea id="comment"></textarea>', (w, f) => {
  let gesehen = 0;
  w.document.getElementById("comment")
    .addEventListener("input", () => { gesehen++; });
  f(TEXT);
  check(gesehen === 1, "genau ein input-Ereignis wird ausgeloest", "gesehen: " + gesehen);
});

// c) Alternative Feldnamen
mitDom('<textarea name="comment"></textarea>', (w, f) => {
  check(f(TEXT).ok === true, "textarea[name=comment] wird gefunden");
});

// d) Ein UNSICHTBARES Feld darf NICHT genommen werden – in Jira liegt oft ein
//    verstecktes Formular im DOM, bevor der Benutzer "Kommentieren" klickt.
mitDom('<textarea id="comment" data-unsichtbar></textarea>', (w, f) => {
  const r = f(TEXT);
  check(r.ok === false, "ein unsichtbares Feld wird uebergangen");
  check(/Kommentarfeld/.test(r.fehler || ""),
        "und der Grund wird im Klartext genannt");
});

// e) Gar kein Feld → ehrlicher Fehlschlag statt stillem Nichtstun
mitDom("<p>Kein Formular hier.</p>", (w, f) => {
  const r = f(TEXT);
  check(r.ok === false, "ohne Kommentarfeld: kein falscher Erfolg");
  check(/Kopieren/.test(r.fehler || ""),
        "die Meldung nennt den Ausweg (Kopieren)");
});

// f) contenteditable (Jira Cloud / ProseMirror)
mitDom('<div contenteditable="true"></div>', (w, f) => {
  w.document.execCommand = () => false;   // jsdom kennt execCommand nicht
  const r = f(TEXT);
  check(r.ok === true, "contenteditable wird als letzter Weg genommen");
  check(w.document.querySelector("[contenteditable]").textContent === TEXT,
        "auch dort steht der Text");
});

// g) Der Vorschlagstext ist MODELLTEXT und darf kein Markup einschleusen.
mitDom('<iframe id="x_ifr"></iframe>', (w, f) => {
  const rahmen = w.document.getElementById("x_ifr");
  const doc = rahmen.contentDocument;
  doc.body.contentEditable = "true";
  Object.defineProperty(doc.body, "isContentEditable", { value: true });
  const r = f("Hallo <img src=x onerror=alert(1)>\n\nZweiter Absatz");
  check(r.ok === true, "TinyMCE-iframe wird bedient", JSON.stringify(r));
  check(doc.body.querySelectorAll("img").length === 0,
        "eingeschleustes Markup wird NICHT als HTML uebernommen");
  check(doc.body.querySelectorAll("p").length === 2,
        "Absaetze bleiben Absaetze");
});

// ═══════════════════════════════════════════════════════════════════════════
section("7) Oberflaeche");
// ═══════════════════════════════════════════════════════════════════════════
check(/type="module"/.test(POPUP_HTML),
      "popup.js wird als Modul geladen (der Import von einfuegen.js braucht das)");
// window.confirm/alert sind in Aufgabenfenstern unterdrueckt; in einem
// Extension-Popup funktionieren sie zwar, sehen aber wie ein Browserdialog der
// Seite aus. Eigene Meldungen statt Systemdialoge – wie im Rest des Projekts.
check(!/\b(confirm|alert|prompt)\s*\(/.test(ohneKommentare(POPUP_JS)),
      "keine Systemdialoge (confirm/alert/prompt)");
check(/https:\\?\/\\?\//.test(POPUP_JS) && /muss mit https/.test(POPUP_JS),
      "http wird abgelehnt – der Token darf nicht im Klartext reisen");
// Rueckmeldung ist Pflicht: in der Zwischenablage sieht man nichts.
check(/Kopieren fehlgeschlagen/.test(POPUP_JS),
      "ein fehlgeschlagenes Kopieren wird gemeldet");
check(/Zwischenablage kopiert/.test(POPUP_JS),
      "ein erfolgreiches Kopieren ebenfalls");

// Die Ticketnummer kommt aus der URL, nicht aus dem DOM (stabil ueber
// Jira-Versionen hinweg – und den Inhalt holt ohnehin der Server).
check(/\/browse\//.test(POPUP_JS), "die Ticketnummer wird aus /browse/ gelesen");
check(!/document\.querySelector[^\n]*issue/i.test(POPUP_JS),
      "die Ticketnummer wird NICHT aus dem Seiten-DOM geraten");

// ═══════════════════════════════════════════════════════════════════════════
section("8) Die Ticketnummer-Erkennung – ausgefuehrt");
// ═══════════════════════════════════════════════════════════════════════════
{
  // keyAusUrl ist modulintern; sie wird wie im Browser neu ausgewertet.
  const m = POPUP_JS.match(/function keyAusUrl\(url\)\s*\{[\s\S]*?\n\}/);
  check(!!m, "keyAusUrl gefunden");
  if (m) {
    const dom = new JSDOM("", { url: "https://jira.test/" });
    const keyAusUrl = new dom.window.Function(
      m[0] + "\nreturn keyAusUrl;")();
    const faelle = [
      ["https://jira.firma.de/browse/ABC-123", "ABC-123"],
      ["https://jira.firma.de/browse/abc-123", "ABC-123"],
      ["https://jira.firma.de/browse/NXCIS-4711?filter=x", "NXCIS-4711"],
      ["https://jira.firma.de/secure/RapidBoard.jspa?selectedIssue=DEF-9", "DEF-9"],
      ["https://jira.firma.de/secure/Dashboard.jspa", ""],
      ["https://www.google.de/", ""],
      ["", ""],
      ["nicht-mal-eine-url", ""],
    ];
    for (const [u, erw] of faelle) {
      const g = keyAusUrl(u);
      check(g === erw, "URL " + (u || "(leer)").slice(0, 52) + " -> " + (erw || "(nichts)"),
            "bekam: " + g);
    }
    dom.window.close();
  }
}

console.log("\n" + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
