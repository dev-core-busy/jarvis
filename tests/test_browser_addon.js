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

/* ⚠ EINE UNBEHANDELTE ZURUECKWEISUNG IST EIN FEHLSCHLAG, KEIN ZUFALL.
 *
 * Gefunden 2026-08-31 bei den Gegenproben zur Ticket-Automatik: eine
 * geschnittene Funktion, die NICHT abgewartet wird (`autoAktionPruefen`), warf
 * in einem Harness einen ReferenceError. Der landete als unbehandelte
 * Zurueckweisung – und ob der Lauf daran abbrach oder sie gar nicht meldete,
 * haengte allein daran, ob `process.exit()` schneller war. Zwei Gegenproben
 * brachen deshalb ab, statt fehlzuschlagen: kein FAIL, keine Zaehlzeile, der
 * Waechter sah aus, als waere er nicht gelaufen (Register).
 * Jetzt wird sie gezaehlt, und vor der Zusammenfassung wird der Mikrotask-
 * Puffer geleert, damit sie sicher vorher ankommt. */
const zurueckweisungen = [];
process.on("unhandledRejection", (e) => {
  zurueckweisungen.push((e && e.stack) || String(e));
  /* ⚠ EXIT-CODE SOFORT SETZEN. Ohne diese Zeile war der Wachhund schlimmer als
   * gar keiner: die ganze Datei ist EINE async-IIFE – wirft etwas darin, wird
   * alles bis zum Ende uebersprungen, auch die Zusammenfassung und
   * `process.exit(fail ? 1 : 0)`. Der Zuhoerer verhinderte dann den Absturz,
   * und der Lauf endete mit "0" und ohne jede Zaehlzeile: ein abgebrochener
   * Test, der wie ein bestandener aussieht. Genau am 2026-08-31 passiert. */
  process.exitCode = 1;
  console.log("  FAIL Lauf abgebrochen: " + ((e && e.message) || e));
});

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

/* Modul-Konstanten, die die geschnittenen Funktionen brauchen. Sie stehen
 * nicht in einem Funktionsrumpf und fallen deshalb aus jedem Schnitt heraus –
 * fehlen sie, WIRFT der Lauf statt fehlzuschlagen (siehe LEISTE_PFAD). */
const STAND_ZEILE = (POPUP_JS.match(/const STAND = \d+;/) || [""])[0];
/* Dieselbe Falle, am 2026-08-31 erneut zugeschnappt: `_FETT_RE` und
 * `_BLOCK_RE` stehen in keinem Funktionsrumpf. Ohne sie warf der Lauf mitten
 * in `felderLeeren` – und weil die ganze Datei EINE async-IIFE ist, endete er
 * ohne Zaehlzeile. */
const FELD_KONST = [
  (POPUP_JS.match(/const _FETT_RE = .*;/) || [""])[0],
  (POPUP_JS.match(/const _BLOCK_RE = .*;/) || [""])[0],
].join("\n");

/* ── Schnitt-Helfer fuer die funktionalen Laeufe ──────────────────────────
 *
 * Schneidet eine Funktion aus popup.js und zieht TRANSITIV alles mit, was sie
 * aufruft und was popup.js selbst als Funktion definiert. Eine gepflegte Liste
 * gab es hier bis 2026-08-30 – sie liess beim naechsten neuen Aufruf in
 * `start()` genau eine Funktion fehlen, und der Lauf brach mit einem nackten
 * ReferenceError ab: kein FAIL, keine Zaehlzeile, der Waechter sah aus, als
 * waere er gar nicht gelaufen (Register).
 */
function schneidePopup(name) {
  const m = POPUP_JS.match(new RegExp('(?:async )?function ' + name
                                      + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  return m ? m[0] : null;
}

function popupTeile(start, gestellt) {
  const GESTELLT = new Set((gestellt || []).concat(['Function', 'JSON']));
  const teile = [], drin = new Set(), offen = start.slice();
  while (offen.length) {
    const name = offen.shift();
    if (drin.has(name) || GESTELLT.has(name)) continue;
    const koerper = schneidePopup(name);
    if (!koerper) continue;
    drin.add(name);
    teile.push(koerper);
    // Jeder Bezeichner vor einer Klammer ist ein Aufruf-Kandidat; mitgenommen
    // wird nur, was popup.js wirklich als Funktion definiert.
    for (const t of koerper.match(/\b[A-Za-z_$][\w$]*(?=\s*\()/g) || []) {
      if (!drin.has(t) && !GESTELLT.has(t) && schneidePopup(t)) offen.push(t);
    }
  }
  return { teile, drin };
}


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
  // IM REPO keine festen host_permissions – die traegt erst der Server beim
  // Bauen ein, und zwar SEINE Adresse (jira_assist._manifest_gebrandet).
  // Stuende hier eine, waere sie auf jedem anderen Server falsch.
  check(!m.host_permissions,
        name + ": im Repo keine festen host_permissions");
  check(Array.isArray(m.optional_host_permissions)
        && m.optional_host_permissions.length > 0,
        name + ": Host-Rechte sind sonst zur Laufzeit erfragbar");
  check((m.permissions || []).includes("activeTab"),
        name + ": activeTab");
  check(!(m.permissions || []).includes("tabs"),
        name + ": KEINE weitreichende tabs-Berechtigung");
}

/* KEINE SERVERADRESSE IM REPO-MANIFEST – aber sehr wohl im gebauten Paket.
 *
 * ⚠ HIER STAND EINE BEGRUENDUNG, DIE NICHT MEHR STIMMTE: "eine signierte Datei
 * laesst sich nicht pro Server umschreiben". Das Paket ist laengst pro
 * Installation verschieden – `_manifest_gebrandet` schreibt seit Langem den
 * Markennamen hinein. Die Adresse herauszuhalten war damit eine Regel ohne
 * Grund, und sie hat Geld gekostet: ohne Host-Recht musste das Fenster beim
 * ersten Anmelden nachfragen, Chrome schloss dabei das Popup, und **die
 * Anmeldung ging beim ersten Mal verloren** ("man muss sich 2x anmelden").
 *
 * Was bleibt und hier geprueft wird: im REPO steht keine Adresse. Sie entsteht
 * beim Bauen aus `addin.basis_url(request)` – die Drift-Falle "eine Kopie je
 * Installation im Repo" ist damit weiterhin zu. */
const beideManifeste = JSON.stringify(M_CHROME) + JSON.stringify(M_FF);
check(!/https:\/\/(?!\*)[a-z0-9.-]+\.[a-z]{2,}/i.test(beideManifeste),
      "keine feste Serveradresse im Repo-Manifest");

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
section("4) Anmeldung und Ergebnis ueberleben den Neustart");
// ═══════════════════════════════════════════════════════════════════════════
/* GEAENDERT auf Meldung aus dem Betrieb ("Anmeldung verschwindet generell bei
 * Chrome Neustart"). Vorher lag das Token in `storage.session` – eine
 * Strenge ohne Gegenwert: das Portal legt sein Token seit jeher in den
 * localStorage, gleicher Rechner, gleiche Person. Die Erweiterung war also
 * strenger als die Anwendung, fuer die sie arbeitet. */
check(/storage\.local/.test(bgOhne), "Token und Adresse liegen in storage.local");
check(!/storage\.session/.test(bgOhne),
      "storage.session wird nicht mehr benutzt (ueberlebt den Neustart nicht)");

// Was die Grenze weiterhin haelt – und das ist der Punkt, an dem die
// Lockerung vertretbar wird:
check(/status === 401/.test(bgOhne) && /sitzungSchreiben\(\{\}\)/.test(bgOhne),
      "ein abgelaufenes Token (401) wird sofort verworfen");
check(/case "abmelden"[\s\S]{0,220}sitzungSchreiben\(\{\}\)/.test(bgOhne),
      "Abmelden loescht es");

// Das Ergebnis ueberlebt das Schliessen des Fensters – ein Popup schliesst
// beim Wechsel in den Jira-Tab, und eine Auswertung dauert ~13 Sekunden.
check(/ergebnisSchreiben/.test(bgOhne), "das Ergebnis wird gemerkt");
check(/case "abmelden"[\s\S]{0,320}ergebnisSchreiben\(null\)/.test(bgOhne),
      "beim Abmelden geht es mit (es enthaelt Ticketinhalte)");

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
function ladeEinfuegen(fenster, name) {
  // /g – die Datei exportiert seit dem Editor-API-Weg MEHRERE Funktionen. Ohne
  // das globale Flag bleibt das zweite `export` stehen und der ganze Abschnitt
  // stirbt mit "Unexpected token 'export'".
  const quelle = EINFUEGEN.replace(/export function/g, "function");
  const f = new fenster.Function(
    quelle + "\nreturn " + (name || "einfuegenInJira") + ";")();
  return f;
}

function mitDom(html, arbeit, name) {
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
    return arbeit(w, ladeEinfuegen(w, name));
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
  // Geprueft wird der INHALT, nicht die Zeichenkette: der Text wird bewusst in
  // ABSAETZE zerlegt (ein HTML-Editor macht aus \n sonst nichts). Ein Vergleich
  // auf Gleichheit haette hier eine Verbesserung als Fehler gemeldet.
  const drin = w.document.querySelector("[contenteditable]").textContent;
  check(TEXT.split(/\s+/).every((wort) => drin.includes(wort)),
        "auch dort steht der Text", drin);
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
section("6b) Branding: keine Marke und keine Farbe fest verdrahtet");
// ═══════════════════════════════════════════════════════════════════════════
/* Dies ist ein White-Label-Produkt. Ein Fenster, das im Browser jedes
 * Sachbearbeiters "Jarvis" schreibt, verraet das Produkt hinter der Hausmarke –
 * dieselbe Begruendung, aus der die Mail-Kategorie und der Name des
 * Outlook-Add-ins dem Branding folgen. */
const POPUP_CSS = lies("popup.css");
const cssOhne = ohneKommentare(POPUP_CSS);

// Die Kundenfarbe stand hier hart verdrahtet (#b80f2e) – sie gehoert zum
// Server, nicht ins ausgelieferte Paket.
const festeFarben = (cssOhne.match(/#[0-9a-fA-F]{3,8}\b/g) || [])
    .filter(f => !['#fff', '#ffffff'].includes(f.toLowerCase()));
check(!festeFarben.includes('#b80f2e'),
      'keine Kundenfarbe im Paket', festeFarben.join(', '));
// OHNE BRANDING GIBT ES GAR KEINE PRODUKTFARBE MEHR (Vorgabe 2026-08-28).
// Erst stand hier eine Kundenfarbe, dann das Jarvis-Violett - beides ist in
// einem ausgelieferten White-Label-Paket eine Aussage ueber das Produkt.
check(!/--akzent:\s*#9b59b6/.test(cssOhne),
      'der Jarvis-Ton ist als Rueckfall raus');
check(/--akzent:\s*CanvasText/.test(cssOhne),
      'der Rueckfall folgt dem Systemthema (hell = schwarz auf weiss)');
check(/html\.neutral\s+button\.haupt\s*\{/.test(cssOhne),
      'es gibt einen neutralen Knopf-Zustand');
{
  // Der Nutzer hat den Neutralknopf woertlich beschrieben: schwarze Schrift,
  // schwarzer Rand, weisser Hintergrund. Geprueft wird die REGEL, nicht die
  // Existenz der Klasse.
  const m = cssOhne.match(/html\.neutral\s+button\.haupt\s*\{([^}]*)\}/);
  const r = m ? m[1] : '';
  check(/background:\s*Canvas\b/.test(r), 'neutral: heller Hintergrund', r);
  check(/color:\s*CanvasText\b/.test(r), 'neutral: dunkle Schrift', r);
  check(/border-color:\s*CanvasText\b/.test(r), 'neutral: dunkler Rand', r);
}
check(/setProperty\("--akzent"/.test(POPUP_JS),
      'popup.js setzt die Akzentfarbe aus dem Branding');
// Die Farben stehen in `colors`, nicht flach in der Antwort. Ein Zugriff auf
// b.accent liefert undefined – und zwar STILL (das Fenster behaelt den
// Standardton). Live gegen ein eingeschaltetes Branding gemessen.
check(/b\.colors/.test(POPUP_JS),
      'die Farben werden aus b.colors gelesen');
check(!/\bb\.accent\b/.test(ohneKommentare(POPUP_JS)),
      'NICHT flach aus b.accent (dort steht nichts)');
// Gegenprobe an der Wahrheit: der Endpunkt liefert genau dieses Feld.
const MAIN_SRC = fs.readFileSync(path.join(WURZEL, 'backend', 'main.py'), 'utf8');
check(/"colors":\s*cfg\.get\("colors"/.test(MAIN_SRC),
      '/api/branding liefert colors – die Namen passen zusammen');

// ── Der Platzhalter {marke} wird WIRKLICH ersetzt ─────────────────────────
// Kein Quelltext-Test: ein roher "{marke}"-Text im Fenster waere schlimmer als
// der falsche Markenname. Geprueft wird in BEIDEN Faellen – ohne Branding
// (Rueckfall) und mit.
{
  // markeAnwenden + setzeBranding aus popup.js schneiden und ausfuehren.
  const teile = ['const _originale = new Map();'];
  for (const name of ['_istHexFarbe', 'akzentSetzen', 'markeAnwenden', 'setzeBranding']) {
    const m = POPUP_JS.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
    if (m) teile.push(m[0]);
  }

  /* JE FALL EIN FRISCHES DOM. Der erste Lauf ersetzt die Platzhalter durch den
   * Rueckfall; ein zweiter Lauf auf demselben DOM faende keine mehr und waere
   * gruen aus dem falschen Grund – genau so ist dieser Test beim ersten Mal
   * fehlgeschlagen und hat einen Fehler im PRODUKTIONSCODE behauptet, den es
   * nicht gab. (Register: ein neuer Testblock braucht ein frisches DOM.) */
  const lauf = (branding) => {
    const dom = new JSDOM(POPUP_HTML, { url: 'https://x.test/', runScripts: 'outside-only' });
    const w = dom.window;
    try {
      const f = new w.Function('marke', 'branding', `
          let _marke = marke;
          const $ = (id) => document.getElementById(id);
          const el = { basis: { value: '' } };
          ${teile.join('\n')}
          markeAnwenden();
          if (branding) setzeBranding(branding);
          return JSON.stringify({
            text: document.body.textContent,
            titel: document.title,
            marke: document.getElementById('marke').textContent
          });`);
      return JSON.parse(f('Jarvis', branding));
    } finally {
      w.close();
    }
  };

  const ohne = lauf(null);
  check(!ohne.text.includes('{marke}'),
        'ohne Branding: kein roher Platzhalter im Fenster');
  check(ohne.text.includes('Jarvis-Adresse'),
        'ohne Branding: Rueckfall auf Jarvis');
  check(!ohne.titel.includes('{marke}'), 'ohne Branding: auch der Titel');

  const mit = lauf({ assistant_name: 'Nexerius', colors: { accent: '#b80f2e' } });

  /* Der Test oben ruft markeAnwenden() SELBST auf – er belegt damit die
   * Funktion, nicht ihren Aufruf. Eine Gegenprobe, die den Aufruf aus start()
   * entfernte, blieb deshalb gruen. Also zusaetzlich: wird er ueberhaupt
   * gerufen, und zwar VOR dem ersten await? Danach blitzt der rohe Platzhalter
   * sichtbar auf, weil das Fenster schon gerendert ist. */
  const startFn = (POPUP_JS.match(/async function start\(\)\s*\{[\s\S]*?\n\}/) || [''])[0];
  check(/markeAnwenden\(\)/.test(startFn), 'start() ruft markeAnwenden()');
  const vorAwait = startFn.slice(0, startFn.search(/\bawait\b/));
  check(/markeAnwenden\(\)/.test(vorAwait),
        'und zwar VOR dem ersten await (sonst blitzt {marke} auf)');
  check(!mit.text.includes('{marke}'), 'mit Branding: kein roher Platzhalter');
  check(mit.text.includes('Nexerius-Adresse'),
        'mit Branding: der Platzhalter traegt die Marke');
  check(!mit.text.includes('Jarvis-Adresse'),
        'mit Branding: kein "Jarvis" mehr im Text');
  check(mit.marke === 'Nexerius', 'die Kopfzeile traegt die Marke');
  check(mit.titel === 'Nexerius für Jira', 'der Fenstertitel ebenfalls');
}

/* ── DER GEMELDETE FALL: die ANMELDEMASKE ─────────────────────────────────
 * "das Branding beim Login ist noch falsch". Zu Recht: die Marke kam
 * ausschliesslich aus /api/branding, und der Abruf braucht eine Adresse. Beim
 * allerersten Oeffnen ist keine hinterlegt – ausgerechnet auf der Maske, die
 * jemand als Erstes sieht, stand deshalb der eingebaute Name.
 * Der Server traegt die Marke jetzt beim Bauen des ZIP ein. Hier wird das
 * OHNE jeden Abruf gemessen: ein gebrandetes Paket, kein Branding-Objekt. */
{
  const vorgabe  = POPUP_JS.match(/function _vorgabeMarke\(\)\s*\{[\s\S]*?\n\}/);
  const anwenden = POPUP_JS.match(/function markeAnwenden\(\)\s*\{[\s\S]*?\n\}/);
  check(!!vorgabe, 'popup.js liest eine Marken-Vorgabe aus dem Paket');
  check(/<meta name="marke" content="">/.test(POPUP_HTML),
        'im Repo ist das Feld LEER (keine zweite Wahrheit neben dem Branding)');
  check(/_vorgabeMarke\(\)\s*\|\|\s*"Jarvis"/.test(POPUP_JS),
        'ohne Vorgabe gilt weiterhin der eingebaute Rueckfall');

  const html = POPUP_HTML.replace('<meta name="marke" content="">',
                                  '<meta name="marke" content="Nexerius">');
  const dom = new JSDOM(html, { url: 'https://x.test/', runScripts: 'outside-only' });
  const w = dom.window;
  try {
    const f = new w.Function(`
        const _originale = new Map();
        ${vorgabe ? vorgabe[0] : ''}
        ${anwenden ? anwenden[0] : ''}
        let _marke = _vorgabeMarke() || "Jarvis";
        markeAnwenden();
        return JSON.stringify({ text: document.body.textContent,
                                titel: document.title });`);
    const r = JSON.parse(f());
    check(r.text.includes('Nexerius-Adresse'),
          'die Anmeldemaske traegt die Marke OHNE jeden Serverabruf');
    check(!/Jarvis/.test(r.text),
          'und nirgends mehr den eingebauten Namen', r.text.slice(0, 80));
    check(r.titel === 'Nexerius für Jira', 'der Fenstertitel ebenfalls');
  } finally { w.close(); }

  // Farbe und Logo kennt nur der Server – die sollen stehen, sobald eine
  // Adresse eingetippt IST, nicht erst nach dem Anmelden.
  check(/el\.basis\.addEventListener\("change"/.test(POPUP_JS),
        'die eingetippte Adresse loest den Branding-Abruf schon vor dem Login aus');
}

/* ── DIE HAUSFARBE AUF DER ANMELDEMASKE ───────────────────────────────────
 * Gemeldet 2026-08-28: "der Anmelden-Knopf ist weiterhin NICHT in der
 * Branding-Farbe". Dieselbe Luecke wie bei der Marke, eine Ebene tiefer: die
 * Farbe kam nur aus /api/branding, und der Abruf haengt am `change` des
 * Adressfeldes – auf der Anmeldemaske steht dort noch nichts.
 * GEMESSEN, nicht gelesen: die Funktionen werden wirklich ausgefuehrt. */
{
  const teile = [];
  for (const name of ['_istHexFarbe', 'akzentSetzen']) {
    const m = POPUP_JS.match(new RegExp('function ' + name + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
    check(!!m, 'popup.js hat ' + name + '()');
    if (m) teile.push(m[0]);
  }
  check(/<meta name="akzent" content="">/.test(POPUP_HTML),
        'im Repo ist das Farbfeld LEER (keine Produktfarbe im Paket)');
  check(/class="neutral"/.test(POPUP_HTML),
        'das Fenster startet im Neutralzustand');
  // Die Richtung ist der Kern: die Klasse wird ENTFERNT, nie gesetzt. Sonst
  // blitzt bei jedem Oeffnen kurz die falsche Farbe auf, und ohne JS waere der
  // Knopf gefaerbt, obwohl niemand eine Farbe kennt.
  check(/classList\.remove\("neutral"\)/.test(POPUP_JS),
        'und verlaesst ihn nur, wenn eine Farbe da ist');
  check(!/classList\.add\("neutral"\)/.test(POPUP_JS),
        'die Klasse wird nie per JS gesetzt (fail-safe Richtung)');
  /* ⚠ DER TEST UNTEN RUFT akzentSetzen() SELBST – er belegt damit die Funktion,
   * nicht ihren AUFRUF. Eine Gegenprobe, die den Aufruf aus popup.js entfernte,
   * blieb deshalb gruen (dieselbe Falle wie bei markeAnwenden weiter oben).
   * Also zusaetzlich: steht er auf MODULEBENE, also vor jedem Rendern und vor
   * jedem Netzaufruf? Ein Aufruf in einer Funktion waere zu spaet - dann
   * blitzt der neutrale Knopf auf und faerbt sich nachtraeglich. */
  check(/^akzentSetzen\(/m.test(ohneKommentare(POPUP_JS)),
        'popup.js wendet die Vorgabe beim Laden an, nicht erst spaeter');
  check(/^akzentSetzen\([^\n]*meta\[name="akzent"\]/m.test(ohneKommentare(POPUP_JS)),
        'und zwar die Vorgabe aus dem Paket');

  const lauf = (farbe) => {
    const html = POPUP_HTML.replace('<meta name="akzent" content="">',
                                    '<meta name="akzent" content="' + farbe + '">');
    const dom = new JSDOM(html, { url: 'https://x.test/', runScripts: 'outside-only' });
    const w = dom.window;
    try {
      const f = new w.Function(`
          ${teile.join('\n')}
          akzentSetzen((document.querySelector('meta[name="akzent"]') || {}).content);
          return JSON.stringify({
            neutral: document.documentElement.classList.contains('neutral'),
            akzent: document.documentElement.style.getPropertyValue('--akzent'),
            hover: document.documentElement.style.getPropertyValue('--akzent-hover')
          });`);
      return JSON.parse(f());
    } finally { w.close(); }
  };

  const mit = lauf('#b80f2e');
  check(mit.akzent === '#b80f2e',
        'die Hausfarbe steht OHNE jeden Serverabruf im Fenster', mit.akzent);
  check(mit.neutral === false, 'und der Neutralzustand ist beendet');
  check(mit.hover.includes('#b80f2e'),
        'ein Hover-Ton wird abgeleitet (sonst springt der Knopf zurueck)',
        mit.hover);

  const ohne = lauf('');
  check(ohne.neutral === true && !ohne.akzent,
        'ohne Vorgabe bleibt es neutral – keine Produktfarbe');

  /* ⚠ DIE FARBE LANDET IN EINER CSS-EIGENSCHAFT. Maskieren nuetzt dort nichts,
   * deshalb wird GEPRUEFT statt entschaerft: alles ausser #rgb/#rrggbb wird
   * verworfen, und dann bleibt der neutrale Knopf. */
  for (const boese of ['red;background:url(http://x/a.png)', 'url(javascript:1)',
                       'expression(alert(1))', 'var(--x)', '#12', 'rot']) {
    const r = lauf(boese);
    check(r.neutral === true && !r.akzent,
          'unbrauchbare/gefaehrliche Farbe wird verworfen: ' + boese,
          r.akzent);
  }

  /* Und der Server fuellt die Felder auch wirklich – sonst ist alles obige tot.
   *
   * Geprueft wird, dass der NAME des Feldes belegt wird, nicht die Schreibweise
   * des Regex: seit alle drei Felder ueber denselben Helfer laufen
   * (`feld_setzen`), steht `name="akzent"` nirgends mehr woertlich da. Ein
   * Waechter, der auf die Schreibweise zielt, meldet dann einen Fehler, den es
   * nicht gibt – genau das ist hier beim Umbau passiert. Das VERHALTEN prueft
   * `tests/test_jira_assist.py`, indem es das Paket wirklich baut. */
  const JA_SRC = fs.readFileSync(path.join(WURZEL, 'backend', 'jira_assist.py'), 'utf8');
  const fn = (JA_SRC.match(/def _popup_gebrandet\([\s\S]*?\n\n\n/) || [''])[0];
  for (const feld of ['marke', 'akzent', 'basis']) {
    check(new RegExp('"' + feld + '"').test(fn),
          'jira_assist._popup_gebrandet belegt das Feld ' + feld);
  }
  check(/_HEXFARBE/.test(fn),
        'und prueft die Farbe serverseitig ebenfalls');
}

/* ── DREHENDER KREIS BEI WARTEMELDUNGEN ───────────────────────────────────
 * Vorgabe des Nutzers 2026-08-28: "Formuliere einen Antwortvorschlag …
 * (dauert einige Sekunden)" stand reglos da. Ein stehender Satz ist von einem
 * haengenden Fenster nicht zu unterscheiden – das Popup hat weder Titelleiste
 * noch Ladebalken.
 * GEMESSEN am echten DOM: melde() wird wirklich ausgefuehrt. */
{
  const m = POPUP_JS.match(/function melde\([^)]*\)\s*\{[\s\S]*?\n\}/);
  check(!!m, 'melde() ist schneidbar');

  const lauf = (rufe) => {
    const dom = new JSDOM(POPUP_HTML, { url: 'https://x.test/', runScripts: 'outside-only' });
    const w = dom.window;
    try {
      const f = new w.Function('rufe', `
          const _marke = "Marke";
          const el = { meldung: document.getElementById("meldung") };
          ${m ? m[0] : ''}
          for (const r of rufe) melde(r[0], r[1]);
          return JSON.stringify({
            kreise: el.meldung.querySelectorAll(".dreher").length,
            text: el.meldung.textContent,
            arbeitet: el.meldung.classList.contains("arbeitet"),
            ariaVersteckt: (el.meldung.querySelector(".dreher") || {})
                .getAttribute ? el.meldung.querySelector(".dreher").getAttribute("aria-hidden") : null,
            erstesKind: el.meldung.firstChild && el.meldung.firstChild.className || ''
          });`);
      return JSON.parse(f(rufe));
    } finally { w.close(); }
  };

  const wartet = lauf([['Formuliere einen Antwortvorschlag … (dauert einige Sekunden)', true]]);
  check(wartet.kreise === 1, 'Wartemeldung: genau ein drehender Kreis', wartet.kreise);
  check(wartet.erstesKind === 'dreher',
        'und er steht VOR dem Text', wartet.erstesKind);
  check(wartet.text.includes('Antwortvorschlag'),
        'der Text bleibt vollstaendig erhalten', wartet.text);
  check(wartet.arbeitet === true, 'die Meldung ist als arbeitend markiert');
  check(wartet.ariaVersteckt === 'true',
        'der Kreis wird Vorlesesoftware nicht als Inhalt angesagt');

  const fertig = lauf([['Fertig.', false]]);
  check(fertig.kreise === 0, 'normale Meldung: kein Kreis', fertig.kreise);

  /* Der Wechsel ist der interessante Fall: bleibt ein Kreis stehen, dreht sich
   * das Fenster nach dem Ergebnis weiter und behauptet Arbeit, die laengst
   * fertig ist. */
  const danach = lauf([['Lade …', true], ['Vorschlag – bitte lesen.', false]]);
  check(danach.kreise === 0,
        'nach dem Ergebnis ist der Kreis weg', danach.kreise);
  check(danach.arbeitet === false, 'und die Markierung ebenfalls');
  const zweimal = lauf([['Lade …', true], ['Lese …', true]]);
  check(zweimal.kreise === 1,
        'zwei Wartemeldungen hintereinander haeufen keine Kreise an', zweimal.kreise);

  /* Der Text kommt teils aus dem Hintergrund - er darf nicht durch innerHTML.
   * ⚠ OHNE ohneKommentare() liest der Waechter die eigene Begruendung im Code
   * mit ("ginge sonst durch innerHTML") und meldet einen Fehler, den es nicht
   * gibt - genau so ist diese Pruefung beim ersten Lauf fehlgeschlagen. */
  check(!/innerHTML/.test(ohneKommentare(m ? m[0] : 'innerHTML')),
        'melde() setzt den Text nie per innerHTML');

  // Und die Wartetexte melden sich auch wirklich als solche an.
  for (const stelle of [/melde\(ARBEITSTEXT\[modus\][^)]*,\s*true\)/,
                        /melde\("Melde an …",\s*true\)/,
                        /melde\("Lese das Kommentarfeld …",\s*true\)/]) {
    check(stelle.test(POPUP_JS),
          'Wartetext ' + stelle.source.slice(0, 32) + '… ist als arbeitend gemeldet');
  }

  // CSS: Bauform wie .chat-activity-spinner im Hauptprojekt.
  const dreher = (cssOhne.match(/\.dreher\s*\{([^}]*)\}/) || ['', ''])[1];
  check(/animation:\s*[\w-]+\s/.test(dreher), 'der Kreis dreht sich wirklich', dreher);
  check(/border-radius:\s*50%/.test(dreher), 'und ist rund', dreher);
  check(/border-top-color:\s*var\(--akzent\)/.test(dreher),
        'die drehende Kante folgt der Hausfarbe', dreher);
  check(/@keyframes\s+dreher-drehen/.test(cssOhne), 'die Animation ist definiert');
  check(/prefers-reduced-motion[\s\S]{0,120}\.dreher\s*\{\s*animation:\s*none/
        .test(cssOhne),
        'wer Bewegung abgestellt hat, bekommt keine');
  check(/\.meldung\.arbeitet\s*\{[^}]*display:\s*flex/.test(cssOhne),
        'Kreis und Text stehen nebeneinander, nicht uebereinander');
}

// Kein sichtbarer Text im Paket darf "Jarvis" fest verdrahtet haben – der
// Rueckfall gehoert in EINE Variable, nicht in zwanzig Zeichenketten.
for (const [datei, inhalt] of [['popup.html', POPUP_HTML],
                               ['background.js', BG],
                               ['popup.js', POPUP_JS]]) {
  const sichtbar = ohneKommentare(inhalt)
      // Der Rueckfall selbst ist erlaubt – aber nur EINMAL und nur hier.
      .replace(/_vorgabeMarke\(\) \|\| "Jarvis";/, '')
      .replace(/JarvisIcons|JarvisIssues/g, '');
  check(!/Jarvis/.test(sichtbar),
        datei + ': kein fest verdrahtetes "Jarvis" im Anzeigetext',
        (sichtbar.match(/.{0,40}Jarvis.{0,40}/) || [''])[0].trim());
}

// Der Markenname wird gesetzt – und zwar per textContent (er kommt aus einem
// Formular, also Fremdeingabe).
check(/getElementById\("marke"\)|\$\("marke"\)/.test(POPUP_JS),
      'popup.js setzt den Markennamen');
check(!/marke[^\n]*innerHTML/.test(POPUP_JS),
      'der Markenname geht NICHT durch innerHTML');
check(/textContent = name/.test(POPUP_JS),
      'sondern durch textContent');

// /api/branding haengt an KEINER Anmeldung – deshalb kann die Marke schon vor
// dem ersten Login stehen. Wuerde hier ein Token verlangt, saehe der Benutzer
// beim allerersten Oeffnen die fremde Marke.
check(/mitToken:\s*false/.test(bgOhne.slice(bgOhne.indexOf('/api/branding') - 200,
                                            bgOhne.indexOf('/api/branding') + 200)),
      '/api/branding wird OHNE Token geholt');

// Serverseitig: das Manifest im ZIP traegt den Markennamen.
const MAIN_PY = fs.readFileSync(path.join(WURZEL, 'backend', 'jira_assist.py'), 'utf8');
const pyOhne = MAIN_PY.replace(/"""[\s\S]*?"""/g, '')
                      .split('\n').map(z => z.split('#')[0]).join('\n');
check(/def markenname/.test(pyOhne), 'der Server kennt einen Markennamen');
check(/kategorie_name/.test(pyOhne),
      'er kommt aus kategorie_name() – keine dritte Fassung derselben Frage');
check(/json\.dumps/.test(pyOhne),
      'das Manifest wird JSON-sicher gebaut (der Name ist Fremdeingabe)');
check(!/\.replace\([^)]*"name"/.test(pyOhne),
      'kein Zeichenketten-Ersatz am Manifest');


// ═══════════════════════════════════════════════════════════════════════════
section("6c) Einfuegen: fokussiertes Feld, Editor-API, Diagnose");
// ═══════════════════════════════════════════════════════════════════════════
/* GEMELDET: "'in Kommentarfeld uebernehmen' fuegt NICHT in das Feld ein" –
 * bei einem Jira mit WYSIWYG-Editor. */
{
  const TXT = "Guten Tag,\n\nerledigt.";

  // a) Das ZULETZT FOKUSSIERTE Feld schlaegt jede Selektorliste. Wer einfuegen
  //    will, hat vorher hineingeklickt – das funktioniert auch in einem Editor,
  //    den niemand vorhergesehen hat.
  mitDom('<div id="fremd" contenteditable="true"></div>'
         + '<textarea id="comment"></textarea>', (w, f) => {
    const ziel = w.document.getElementById("fremd");
    // activeElement ist in jsdom nur ueber focus() setzbar.
    ziel.focus();
    Object.defineProperty(w.document, "activeElement", { value: ziel, configurable: true });
    w.document.execCommand = () => false;
    const r = f(TXT);
    check(r.ok === true && /fokussiert/.test(r.weg || ""),
          "das fokussierte Feld wird bevorzugt", JSON.stringify(r));
    check(ziel.textContent.includes("erledigt"),
          "und der Text landet dort – nicht in der textarea");
    check(w.document.getElementById("comment").value === "",
          "die textarea bleibt unberuehrt");
  });

  // b) WYSIWYG ohne Fokus: der contenteditable-Weg vor der versteckten textarea.
  //    Genau das war der gemeldete Fall – `#comment` existiert, ist aber
  //    unsichtbar und traegt beim Absenden nicht den sichtbaren Inhalt.
  mitDom('<textarea id="comment" data-unsichtbar></textarea>'
         + '<div id="comment-wiki-edit"><div contenteditable="true"></div></div>',
         (w, f) => {
    w.document.execCommand = () => false;
    const r = f(TXT);
    check(r.ok === true, "WYSIWYG wird gefunden, obwohl #comment existiert",
          JSON.stringify(r));
    check(w.document.querySelector("#comment-wiki-edit [contenteditable]")
            .textContent.includes("erledigt"),
          "der Text steht im sichtbaren Editor");
    check(w.document.getElementById("comment").value === "",
          "die unsichtbare textarea bleibt leer");
  });

  // c) Ein Fehlschlag muss sagen, WAS er gesehen hat – sonst ist der naechste
  //    Anlauf wieder Raten.
  mitDom('<textarea id="comment" data-unsichtbar></textarea>', (w, f) => {
    const r = f(TXT);
    check(r.ok === false, "unsichtbares Feld allein: kein falscher Erfolg");
    check(Array.isArray(r.gesehen) && r.gesehen.length > 0,
          "die Diagnose nennt die gefundenen Kandidaten", JSON.stringify(r.gesehen));
    check(/unsichtbar/.test((r.gesehen || []).join(" ")),
          "und sagt dazu, dass sie unsichtbar waren");
    check(/Klicke zuerst/.test(r.fehler || ""),
          "die Meldung nennt den Ausweg (erst hineinklicken)");
  });

  // d) Der zweite Weg laeuft in der SEITENWELT – von der isolierten Welt aus
  //    ist `window.tinymce` unsichtbar, das ist keine Einstellung.
  const zweitQuelle = EINFUEGEN.slice(EINFUEGEN.indexOf("export function einfuegenUeberEditorApi"));
  check(!/document\.querySelectorAll\(/.test(zweitQuelle) || /tinymce/.test(zweitQuelle),
        "die zweite Funktion benutzt die Editor-API");
  check(/world:\s*["']MAIN["']/.test(POPUP_JS),
        'popup.js ruft sie mit world: "MAIN"');
  check(/tinymce_moeglich/.test(POPUP_JS) && /tinymce_moeglich/.test(EINFUEGEN),
        "und nur, wenn der erste Weg das nahelegt");
  // Die Diagnose muss beim Benutzer ankommen, nicht nur im Rueckgabewert.
  check(/r\.gesehen/.test(POPUP_JS), "die Diagnose wird angezeigt");
}

// ═══════════════════════════════════════════════════════════════════════════
section("6e) Ueberarbeiten: das Kommentarfeld LESEN – ausgefuehrt");
// ═══════════════════════════════════════════════════════════════════════════
/* Der dritte Knopf holt den bereits getippten Entwurf aus dem Kommentarfeld.
 * Gleiche Kaskade wie beim Einfuegen, ein Unterschied: es gewinnt das erste
 * Feld MIT TEXT. */
{
  const lies = (html, arbeit) => mitDom(html, arbeit, "leseAusJira");

  // a) Der einfache Fall – und die Absaetze muessen erhalten bleiben.
  lies('<textarea id="comment">Hallo Herr Meier,\n\nerledigt.</textarea>',
       (w, f) => {
    const r = f();
    check(r.ok === true, "textarea wird gelesen", JSON.stringify(r));
    check(r.text === "Hallo Herr Meier,\n\nerledigt.",
          "der Text kommt unveraendert – mit Absatz", JSON.stringify(r.text));
  });

  // b) Das FOKUSSIERTE Feld schlaegt die Selektorliste – wie beim Einfuegen.
  lies('<div id="fremd" contenteditable="true"><p>Mein Entwurf.</p></div>'
       + '<textarea id="comment">Etwas ganz anderes.</textarea>', (w, f) => {
    const ziel = w.document.getElementById("fremd");
    Object.defineProperty(w.document, "activeElement",
                          { value: ziel, configurable: true });
    const r = f();
    check(r.ok === true && r.text === "Mein Entwurf.",
          "der Text kommt aus dem fokussierten Feld", JSON.stringify(r));
  });

  /* c) ⚠ DER FALL, DER DIE REGEL BEGRUENDET: manche Jira-Editoren halten den
   *    Fokus auf einer versteckten Spiegel-textarea, waehrend der sichtbare
   *    Editor den Inhalt traegt. Wuerde das fokussierte, LEERE Feld sofort
   *    gewinnen, meldete die Erweiterung "leer" – waehrend der Text sichtbar
   *    auf dem Schirm steht. */
  /*    ⚠ DAS FELD MUSS HIER SICHTBAR SEIN. Ein unsichtbares wird schon von der
   *    Sichtbarkeitspruefung uebergangen – der Test liefe dann durch einen
   *    ANDEREN Zweig und waere auch mit der naiven Fassung gruen (genau so beim
   *    ersten Anlauf passiert: die Gegenprobe biss nicht). */
  lies('<textarea id="comment"></textarea>'
       + '<div id="comment-wiki-edit"><div contenteditable="true">'
       + '<p>Der sichtbare Entwurf.</p></div></div>', (w, f) => {
    const leer = w.document.getElementById("comment");
    Object.defineProperty(w.document, "activeElement",
                          { value: leer, configurable: true });
    const r = f();
    check(r.ok === true && r.text === "Der sichtbare Entwurf.",
          "ein leeres fokussiertes Feld laesst die Suche WEITERLAUFEN",
          JSON.stringify(r));
    check((r.gesehen || []).length === 0 || r.ok === true,
          "und der leere Fund fuehrt zu keiner Absage");
  });

  // d) Absaetze aus einem Editor: <p> und <br> sind Umbrueche, kein Leerzeichen.
  //    textContent allein klebte "Guten Tag" und "erledigt" aneinander.
  lies('<div contenteditable="true"><p>Guten Tag,</p><p>erledigt.<br>MfG</p></div>',
       (w, f) => {
    const r = f();
    check(r.ok === true, "contenteditable wird gelesen", JSON.stringify(r));
    check(/Guten Tag,\n+erledigt\.\nMfG/.test(r.text || ""),
          "Absaetze und <br> werden zu Zeilenumbruechen",
          JSON.stringify(r.text));
  });

  // e) `innerText` ist der bevorzugte Weg – jsdom kennt ihn nicht, deshalb
  //    wird er gestellt. Ohne diese Pruefung waere im Browser ein anderer
  //    Zweig aktiv als im Test.
  lies('<div contenteditable="true"><p>x</p></div>', (w, f) => {
    const el = w.document.querySelector("[contenteditable]");
    Object.defineProperty(el, "innerText",
                          { value: "Zeile 1\nZeile 2", configurable: true });
    const r = f();
    check(r.text === "Zeile 1\nZeile 2", "innerText wird bevorzugt",
          JSON.stringify(r.text));
  });

  // f) LEER ist ein eigener Zustand – nicht "nicht gefunden". Die beiden
  //    brauchen verschiedene Antworten: ein Bedienfehler mit klarem Weg gegen
  //    einen Fund fuer die Fehlersuche.
  lies('<textarea id="comment"></textarea>', (w, f) => {
    const r = f();
    check(r.ok === false && r.leer === true, "ein leeres Feld meldet 'leer'",
          JSON.stringify(r));
    check(/leer/i.test(r.fehler || "") && /Entwurf/.test(r.fehler || ""),
          "und sagt, was zu tun ist");
  });
  lies("<p>Kein Formular hier.</p>", (w, f) => {
    const r = f();
    check(r.ok === false && !r.leer, "ohne Feld: NICHT 'leer', sondern nicht gefunden");
    check(/Kommentarfeld/.test(r.fehler || ""), "die Meldung nennt das Feld");
  });

  // g) Unsichtbare Felder werden uebergangen – in Jira liegt oft ein
  //    verstecktes Formular im DOM.
  lies('<textarea id="comment" data-unsichtbar>Alter Entwurf</textarea>',
       (w, f) => {
    const r = f();
    check(r.ok === false, "ein unsichtbares Feld wird NICHT gelesen",
          JSON.stringify(r));
  });

  // h) Es wird TEXT gelesen, kein Markup: was der Server bekommt, soll der
  //    getippte Entwurf sein und nicht der HTML-Rumpf des Editors.
  lies('<div contenteditable="true"><p>Hallo <b>Welt</b></p>'
       + '<script>var x = 1;<\/script></div>', (w, f) => {
    const r = f();
    check(!/[<>]/.test(r.text || ""), "kein Markup im Ergebnis",
          JSON.stringify(r.text));
    check(/Hallo Welt/.test(r.text || ""), "der sichtbare Text bleibt");
  });

  // i) Gelesen wird NUR das Kommentarfeld. Die Funktion laeuft in der Seite –
  //    sie darf dort nichts anderes einsammeln und nichts nach draussen geben.
  const leseQuelle = EINFUEGEN.slice(EINFUEGEN.indexOf("export function leseAusJira"),
                                     EINFUEGEN.indexOf("export function lesenUeberEditorApi"));
  for (const verboten of ["fetch(", "XMLHttpRequest", "localStorage", "cookie",
                          "sendMessage", "document.forms"]) {
    check(!leseQuelle.includes(verboten),
          "die Lesefunktion benutzt kein '" + verboten + "'");
  }
}

// ═══════════════════════════════════════════════════════════════════════════
section("6f) Ueberarbeiten: Verdrahtung Knopf → Server");
// ═══════════════════════════════════════════════════════════════════════════
const popupOhne = ohneKommentare(POPUP_JS);
check(/id="btn-ueberarbeiten"/.test(POPUP_HTML), "der Knopf steht im Fenster");
check(/\$\("btn-ueberarbeiten"\)\.addEventListener/.test(popupOhne),
      "und ist verdrahtet");
// Die Voraussetzung (Cursor im Feld) ist unsichtbar – ohne den Hinweis drueckt
// jemand den Knopf und weiss nach der Absage nicht, was er anders machen soll.
check(/Cursor/.test(POPUP_HTML) && /Kommentarfeld/.test(POPUP_HTML),
      "das Fenster nennt die Voraussetzung");
check(/leseAusJira/.test(popupOhne) && /lesenUeberEditorApi/.test(popupOhne),
      "beide Lesewege werden eingebunden");
check(/world:\s*["']MAIN["'][\s\S]{0,120}lesenUeberEditorApi/.test(popupOhne),
      "der Editor-API-Weg laeuft im Seitenkontext");
check(/entwurf:\s*entwurf/.test(popupOhne), "der Entwurf geht an den Hintergrund");
check(/entwurf:\s*nachricht\.entwurf/.test(bgOhne),
      "und von dort an den Server");
// DRIFT-SCHRANKE: der Modusname steht in zwei Welten. Passt er nicht, antwortet
// der Server "Unbekannter Modus" – und die Ursache steht in einer anderen Datei.
check(/MODI = \([^)]*"ueberarbeiten"/.test(MAIN_PY),
      "der Server kennt genau diesen Modusnamen");
check(/auswerten\("ueberarbeiten"/.test(popupOhne),
      "das Fenster schickt ihn");

/* DER ABGLEICH-HINWEIS DARF NICHT INS KOMMENTARFELD.
 * Er ist eine Anmerkung an den Mitarbeiter ("das steht so nicht im Ticket").
 * Landete er im bearbeitbaren Feld, ginge er mit dem naechsten Klick auf
 * "Einfuegen" an einen Kunden. Getrennt wird am Server; hier wird geprueft,
 * dass die Oberflaeche ihn NUR als Meldung anfasst. */
check(/mitAbgleich/.test(popupOhne), "der Hinweis wird eigens behandelt");
/* ⚠ DIESE PRUEFUNG HING AN DER SCHREIBWEISE `ergebnisFeld.value = …` – und
 * wurde mit dem Rich-Text-Umbau zur TAUTOLOGIE: den Ausdruck gibt es nirgends
 * mehr, der Regex war fuer immer wahr und prueste nichts. Gemessen wird jetzt
 * die EIGENSCHAFT (Abschnitt 15e fuehrt sie aus); hier bleibt nur die billige
 * Struktur-Aussage, entkoppelt vom Zuweisungs-Operator. */
check(!/ergebnisFeld[^;\n]*\bhinweis\b/.test(popupOhne),
      "der Hinweis wird nirgends an das Ergebnisfeld gegeben");
/* Und die Gegenrichtung, damit der Umbau nicht heimlich zurueckrutscht: ein
 * <div> nimmt `.value` klaglos als eigene Eigenschaft an – ohne Wurf, ohne
 * Warnung, ohne roten Test. */
check(!/ergebnisFeld\s*\.\s*value/.test(popupOhne),
      "und niemand fasst das Feld ueber .value an (am <div> ein stiller No-op)");
check(/melde\(mitAbgleich/.test(popupOhne), "sondern als Meldung angezeigt");
check(/hinweis:\s*d\.hinweis/.test(bgOhne),
      "und mitgemerkt (sonst fehlt er beim naechsten Oeffnen)");

// Ein Fehlschlag beim Lesen muss sagen, WAS er gesehen hat – gleiche Lehre wie
// beim Einfuegen.
check(/r\.gesehen/.test(popupOhne), "die Diagnose des Lesens wird angezeigt");
// Und er darf keinen Modellaufruf ausloesen: ohne Entwurf gibt es nichts zu
// ueberarbeiten, ein Lauf waere bezahlte Zeit fuer eine erfundene Antwort.
check(/if \(!r \|\| !r\.ok\)[\s\S]{0,300}return;/.test(popupOhne),
      "ohne Entwurf wird gar nicht erst ausgewertet");

// ═══════════════════════════════════════════════════════════════════════════
section("6d) Vorlagen und Ticketbezug");
// ═══════════════════════════════════════════════════════════════════════════
// Ein gemerkter Text zu Ticket A darf nicht unbemerkt in Ticket B landen –
// er geht am Ende an einen Kunden.
check(/_fremdesErgebnis/.test(POPUP_JS), "ein fremder Ticketbezug wird erkannt");

/* ⚠ GEPRUEFT WIRD DIE EIGENSCHAFT, NICHT DIE SCHREIBWEISE.
 *
 * Hier stand bis 2026-08-30 ein Vergleich auf den Wortlaut
 * `_fremdesErgebnis && !(await frageJaNein())`. Als die Schranke von einem
 * Merker auf eine abgeleitete Pruefung umgestellt wurde – noetig, weil in der
 * Seitenleiste der Tab waehrend der Anzeige wechseln kann und ein Merker dabei
 * stehenbleibt –, meldete dieser Waechter einen Fehler, den es nicht gab.
 * Dieselbe Lehre wie bei `test_kontext_schnitt` im Hauptprojekt (Register). */
{
  const m = POPUP_JS.match(/function fremd\(\)\s*\{[\s\S]*?\n\}/);
  check(!!m, "popup.js hat fremd()");
  if (m) {
    // WIRKLICH AUSGEFUEHRT, nicht gelesen: nur so faellt auf, wenn die
    // Ableitung eines Tages wieder nur den Merker liest.
    const bau = (letztes, key, flag) => new Function(
      "_letztes", "_key", "_fremdesErgebnis", m[0] + "; return fremd();"
    )(letztes, key, flag);
    check(bau(null, "A-1", true) === true,
          "der gesetzte Merker allein genuegt weiterhin");
    check(bau({ key: "A-1", text: "x" }, "B-2", false) === true,
          "ein Text zu A-1 gilt bei offenem B-2 als fremd – OHNE Merker");
    check(bau({ key: "A-1", text: "x" }, "A-1", false) === false,
          "derselbe Vorgang gilt nicht als fremd");
    check(bau(null, "A-1", false) === false, "ohne Text gibt es nichts Fremdes");
    check(bau({ key: "A-1", text: "x" }, "", false) === false,
          "ohne erkanntes Ticket im Tab wird nicht geraten");
  }
}
// Und die Einfuege-Schranke muss diese Ableitung wirklich benutzen.
{
  const h = POPUP_JS.match(
    /\$\("btn-einfuegen"\)\.addEventListener\([\s\S]*?\n\}\);/);
  check(!!h, "der Einfuegen-Knopf ist verdrahtet");
  check(!!h && /fremd\(\)\s*&&\s*!\(await frageJaNein\(\)\)/.test(h[0]),
        "und fragt bei fremdem Ticketbezug zurueck");
}
check(!/\b(confirm|alert|prompt)\s*\(/.test(ohneKommentare(POPUP_JS)),
      "die Rueckfrage ist ein eigener Dialog, kein confirm");
check(/jn-nein"\)\.focus\(\)/.test(POPUP_JS),
      "der Fokus liegt auf Abbrechen (die gefaehrlichere Wahl loest kein Tastendruck aus)");

// Die Vorlage gilt nur fuer die Zusammenfassung – bei einem Antwortvorschlag
// waere sie eine zweite, widersprechende Aufgabe.
check(/modus === "zusammenfassung"\) \? \(\$\("f-vorlage"\)/.test(POPUP_JS),
      "die Vorlage geht nur bei der Zusammenfassung mit");
// Namen sind Freitext aus einem Formular.
check(!/innerHTML\s*=\s*[^;]*\bv\.name\b/.test(POPUP_JS),
      "Vorlagennamen gehen nicht durch innerHTML");
check(/o\.textContent = v\.name/.test(POPUP_JS), "sondern durch textContent");

/* ── DIE PERSOENLICHE STANDARD-VORLAGE (gemeldet 2026-08-28) ──────────────
 * "der user muss die Moeglichkeit haben eine Vorlage als seine 'Standard'
 * Vorlage zu markieren". Das Fenster wird bei jedem Klick neu aufgebaut, die
 * Auswahl stand also bei JEDEM Oeffnen wieder auf "ohne Vorlage".
 *
 * AUSGEFUEHRT, nicht gelesen: die haeufigste Ursache fuer eine wirkungslose
 * Vorauswahl ist, dass sie beim naechsten Neuzeichnen wieder ueberschrieben
 * wird – im Quelltext sieht man das nicht. */
{
  /* Transitiv geschnitten, nicht handverlesen: `vorlagenZeichnen` zieht die
   * Knopf-Sperre nach (die Zeilen-Knoepfe entstehen erst hier), und eine feste
   * Liste haette genau diese Funktion fehlen lassen – der Lauf waere mit einem
   * nackten ReferenceError abgebrochen statt fehlzuschlagen. */
  const { teile: t3, drin: d3 } = popupTeile(
    ['vorlagenZeichnen'],
    ['standardSetzen', 'vorlageInsFormular', 'vorlageLoeschen', 'frageJaNein']);
  const zeichnen = t3.join('\n');
  check(d3.has('vorlagenZeichnen'), 'popup.js hat vorlagenZeichnen()');
  check(d3.has('knoepfeAktualisieren'),
        'und zieht die Knopf-Sperre nach', [...d3].join(','));

  const lauf = (standard, eigeneWahl, key) => {
    const dom = new JSDOM(POPUP_HTML, { url: 'https://x.test/',
                                        runScripts: 'outside-only' });
    const w = dom.window;
    try {
      const f = new w.Function('standard', 'eigeneWahl', 'key', `
        const $ = (id) => document.getElementById(id);
        let _vorlBeruehrt = false;
        let _vorlagen = {
          global: [{ id: "g1", name: "Kurz" }, { id: "g2", name: "Technisch" }],
          eigene: [{ id: "e1", name: "Meine" }],
          darf_global: true, standard,
        };
        function standardSetzen() {}
        function vorlageInsFormular() {}
        function vorlageLoeschen() {}
        function frageJaNein() { return Promise.resolve(true); }
        let _key = (key === undefined) ? "ABC-1" : key, _laeuft = false;
` + zeichnen + `
        vorlagenZeichnen();
        if (eigeneWahl) {
          $("f-vorlage").value = eigeneWahl;
          _vorlBeruehrt = true;
          vorlagenZeichnen();            // z. B. nach dem Speichern
        }
        const sterne = Array.from(
          document.querySelectorAll("#vorl-liste button"))
          .filter((b) => /^[★☆]$/u.test(b.textContent))
          .map((b) => b.textContent);
        const zeilenKnoepfe = Array.from(
          document.querySelectorAll("#vorl-liste button"));
        return JSON.stringify({
          gewaehlt: $("f-vorlage").value,
          erste: $("f-vorlage").options[0].textContent,
          sterne,
          zeilenAnzahl: zeilenKnoepfe.length,
          zeilenGesperrt: zeilenKnoepfe.every((b) => b.disabled),
        });`);
      return JSON.parse(f(standard, eigeneWahl, key));
    } finally { w.close(); }
  };

  /* ⚠ DIE ZEILEN-KNOEPFE ENTSTEHEN ERST HIER - Stern, Bearbeiten, Loeschen.
   * Ein einmaliger Durchlauf ueber `button` beim Tab-Wechsel erwischt sie
   * nicht, und beim naechsten Neuzeichnen waeren sie wieder bedienbar.
   * GEMESSEN, nicht am Schnitt abgelesen: die Pruefung "knoepfeAktualisieren
   * steckt im geschnittenen Code" bleibt wahr, auch wenn ein `return` davor
   * steht - die Gegenprobe biss damit nicht. */
  {
    const mit = lauf('', '', 'ABC-1');
    const ohneTicket = lauf('', '', '');
    check(mit.zeilenAnzahl > 0, 'die Vorlagenliste hat Zeilen-Knoepfe',
          String(mit.zeilenAnzahl));
    check(mit.zeilenGesperrt === false, 'mit Ticket sind sie bedienbar');
    /* ⚠ SEIT 2026-08-31 UMGEKEHRT, auf Meldung: Vorlagen pflegt man
     * unabhaengig von einem Ticket. Vorher waren Stern, Bearbeiten und
     * Loeschen ohne Ticket gesperrt - zusammen mit dem Zahnrad, das die Box
     * ueberhaupt erst oeffnet, war die Verwaltung damit unerreichbar.
     * GEMESSEN am frisch gezeichneten DOM: die Knoepfe entstehen erst hier,
     * die Ausnahme kommt vom Container - eine Quelltext-Pruefung saehe das
     * nicht. */
    check(ohneTicket.zeilenAnzahl === mit.zeilenAnzahl,
          'ohne Ticket wird die Liste genauso gezeichnet',
          String(ohneTicket.zeilenAnzahl));
    check(ohneTicket.zeilenGesperrt === false,
          'und die frisch gezeichneten Zeilen-Knoepfe sind bedienbar');
  }

  const ohne = lauf('', '');
  check(ohne.gewaehlt === '',
        'ohne Standard bleibt "ohne Vorlage" vorausgewaehlt', ohne.gewaehlt);
  /* "Standard" hiesse jetzt zweierlei: der eingebaute Ablauf UND die Vorlage
   * mit dem Stern. Deshalb wurde die erste Option umbenannt. */
  check(!/^Standard$/.test(ohne.erste),
        'die leere Option heisst nicht mehr "Standard"', ohne.erste);
  check(ohne.sterne.length === 3 && ohne.sterne.every((s) => s === '☆'),
        'jede Zeile traegt einen Stern, keiner ist gefuellt',
        JSON.stringify(ohne.sterne));

  const mit = lauf('g2', '');
  check(mit.gewaehlt === 'g2',
        'mit Standard ist er vorausgewaehlt – DAS ist der Sinn', mit.gewaehlt);
  check(mit.sterne.join('') === '☆★☆',
        'und genau seine Zeile traegt den gefuellten Stern',
        JSON.stringify(mit.sterne));

  /* ⚠ EINE EIGENE WAHL MUSS DEN STANDARD SCHLAGEN. Ohne den Merker holte
   * jedes Neuzeichnen (Speichern, Loeschen, Stern) den Standard zurueck und
   * verstellte die gerade getroffene Auswahl – ein Pulldown, das sich selbst
   * zuruecksetzt, sieht wie ein Fehler aus. */
  const gewaehlt = lauf('g2', 'e1');
  check(gewaehlt.gewaehlt === 'e1',
        'eine eigene Wahl ueberlebt das Neuzeichnen', gewaehlt.gewaehlt);
}

/* Drei Layout-Regeln, die NUR der Screenshot gezeigt hat. jsdom rechnet kein
 * Layout – geprüft wird deshalb die Regel, nicht das Ergebnis. Alle drei
 * ließen im 380 px breiten Fenster etwas herausragen, während die erste
 * Messung „kein Überlauf“ meldete: sie verglich Kinder mit ihren Eltern statt
 * das Dokument mit dem Viewport. */
const cssRegel = (sel) => {
  const m = new RegExp('(?:^|\\})\\s*' + sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
                       + '\\s*\\{([^}]*)\\}', 'm').exec(cssOhne);
  return m ? m[1] : '';
};
check(/width:\s*auto/.test(cssRegel('input[type="checkbox"], input[type="radio"]')),
      'Kontrollkästchen sind nicht 100 % breit (sonst rutscht die Beschriftung um)');
check(/flex-wrap:\s*wrap/.test(cssRegel('.knopfreihe')),
      'Knopfreihen brechen um (zwei lange Beschriftungen passen nicht nebeneinander)');
check(/min-width:\s*0/.test(cssRegel('.marke')),
      'die Marke darf schrumpfen');
check(/flex:\s*0 0 auto/.test(cssRegel('.kopf > button')),
      'der Abmelden-Knopf nicht (sonst schiebt ihn eine lange Ticketnummer hinaus)');
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

(async () => {

/* ── FELDER LEEREN, WENN DER TEXT NICHT ZUM TAB GEHÖRT ────────────────────
 * Vorgabe des Nutzers 2026-08-28. Vorher blieb ein gemerkter Text stehen -
 * mit Warnung, aber sichtbar und einfügbar. Ein Text im Feld ist eine
 * Einladung, ihn zu benutzen; er geht am Ende an einen echten Kunden.
 * GEMESSEN: start() wird mit echtem DOM ausgefuehrt. */
{
  /* ⚠ DIE FUNKTIONSLISTE WIRD TRANSITIV AUFGEBAUT, NICHT GEPFLEGT.
   *
   * Bis 2026-08-30 stand hier eine feste Aufzaehlung. Als `start()` um den
   * Aufruf von `ansichtZeigen()` wuchs, brach dieser Lauf mit einem nackten
   * ReferenceError ab – kein FAIL, keine Zaehlzeile, der Waechter sah aus, als
   * waere er gar nicht gelaufen. Dieselbe Falle steht im Register
   * (`live_bildrahmen_dev.py`): eine gepflegte Liste laesst genau die eine
   * Funktion fehlen, die gerade dazugekommen ist.
   *
   * Gesammelt wird deshalb ab einem Startpunkt ueber die AUFRUFE: alles, was
   * aus dem geschnittenen Code heraus gerufen wird und in popup.js als
   * Funktion existiert, kommt dazu – ausser dem, was die Attrappe selbst
   * stellt. */
  const { teile, drin } = popupTeile(
    ['melde', 'felderLeeren', 'zeigeGemerktes', 'mitAbgleich',
     'zeige', 'start', 'markeAnwenden',
     // Die Attrappe LIEST damit den Feldinhalt; aus dem geschnittenen Code
     // heraus wird es nicht gerufen und faellt sonst aus dem Schnitt.
     'feldZuText'],
    ['frage', 'tabErmitteln', 'vorlagenLaden', 'brandingHolen']);
  for (const n of ['melde', 'felderLeeren', 'zeigeGemerktes', 'mitAbgleich',
                   'zeige', 'start', 'markeAnwenden']) {
    check(drin.has(n), 'popup.js hat ' + n + '()');
  }
  check(drin.has('ticketLageAnwenden'),
        'der Schnitt zieht ticketLageAnwenden mit', [...drin].join(','));

  /* Der Lauf gibt zurueck, was NACH start() im Fenster steht - und was an den
   * Hintergrund gemeldet wurde. Letzteres ist der eigentliche Punkt: nur das
   * Feld zu leeren wuerde den Text beim naechsten Oeffnen zurueckbringen. */
  // Die Attrappe muss `zustand` beantworten - sonst laeuft start() ins Leere.
  const laufMit = async (tabKey, gemerkt, klickLeeren, bgStand) => {
    const dom = new JSDOM(POPUP_HTML, { url: 'https://x.test/',
                                        runScripts: 'outside-only' });
    const w = dom.window;
    try {
      /* ⚠ DER CODE WIRD ANGEHAENGT, NICHT INTERPOLIERT.
       *
       * Bis 2026-08-30 stand hier eine Interpolation mitten in einem
       * Template-Literal. Das ging zweimal schief, sobald der Schnitt groesser
       * wurde: ein Backtick in einem Kommentar der geschnittenen Funktion
       * beendet das Literal vorzeitig (harter SyntaxError, kein FAIL) – und,
       * viel stiller, ein Regex-Backslash verliert im Template-Literal seine
       * Bedeutung (\\d wird zu d). Der Waechter pruefte dann eine Funktion,
       * die es so im Code gar nicht gibt.
       * Zusammengehaengt kommt der Code Zeichen fuer Zeichen an. */
      const f = new w.Function('tabKey', 'gemerkt', 'klickLeeren', 'bgStand', `
          const gesendet = [];
          const $ = (id) => document.getElementById(id);
          const el = {
            login: $("bereich-login"), arbeit: $("bereich-arbeit"),
            basis: $("f-basis"), hinweis: $("f-hinweis"),
            ergebnisFeld: $("f-ergebnis"), ergebnis: $("ergebnis"),
            ergebnisFuss: $("ergebnis-fuss"), meldung: $("meldung"),
            ticket: $("ticket-anzeige"), abmelden: $("btn-abmelden"),
          };
          let _marke = "Marke", _key = tabKey, _tabId = 1;
          let _letztes = null, _fremdesErgebnis = false, _merkTimer = null;
          // Siehe Abschnitt 10: ticketLageAnwenden stoesst die Automatik an.
          let _autoModus = "";
          const _originale = new Map();
          let _jiraBasis = "", _standAlt = false, _standGesehen;
          /* ⚠ EIN value-ZUGRIFF AM <div> IST EIN STILLER ERFOLG: JS legt
           * einfach eine Eigenschaft an, die mit dem Sichtbaren nichts zu tun
           * hat. Eine zurueckgerutschte Zuweisung waere damit unsichtbar - und
           * der schlimmste Ausgang ist der Antworttext zu Vorgang A im
           * Kommentarfeld von Vorgang B, ohne Rueckfrage (die Fremd-Pruefung
           * merkt nichts, weil das Gedaechtnis stimmt). Deshalb wirft es hier.
           * KEINE BACKTICKS in diesem Vorspann - er steht selbst in einem
           * Template-Literal und wuerde es beenden. */
          Object.defineProperty(el.ergebnisFeld, "value", {
            get() { throw new Error("value am Ergebnisfeld GELESEN"); },
            set() { throw new Error("value am Ergebnisfeld GESETZT"); },
          });
` + STAND_ZEILE + `
` + FELD_KONST + `
          /* Die Leisten-Umgebung. Hier gilt der Popup-Fall (_leiste = false);
           * den Leisten-Fall prueft Abschnitt 10.
           * KEINE Backticks in diesem Vorspann - er steht selbst in einem
           * Template-Literal und wuerde es beenden. */
          let _leiste = false, _windowId = 7, _tabUrl = "https://jira.test/browse/" + (tabKey || "X-1");
          let _laeuft = false;
          const api = {
            permissions: { contains: async () => true, request: async () => true },
            tabs: { onActivated: { addListener() {} },
                    onUpdated: { addListener() {} } },
          };
          async function frage(n) {
            gesendet.push(n);
            if (n && n.art === "zustand") {
              return { ok: true, basis: "https://s.test", angemeldet: true,
                       stand: (bgStand === undefined) ? STAND : bgStand,
                       ergebnis: gemerkt };
            }
            return { ok: true };
          }
          async function tabErmitteln() { el.ticket.textContent = _key || ""; }
          function vorlagenLaden() {}
          function brandingHolen() {}
` + teile.join('\n') + `
          return (async () => {
            el.hinweis.value = "bitte kurz halten";
            await start();
            if (klickLeeren) await felderLeeren("Geleert.");
            return JSON.stringify({
              text: feldZuText(el.ergebnisFeld),
              sichtbar: !el.ergebnis.hidden,
              fuss: el.ergebnisFuss.textContent,
              hinweis: el.hinweis.value,
              meldung: el.meldung.hidden ? "" : el.meldung.textContent,
              geloescht: gesendet.some(n => n && n.art === "ergebnis_merken"
                                            && n.wert === null),
            });
          })();`);
      return JSON.parse(await f(tabKey, gemerkt, klickLeeren, bgStand));
    } finally { w.close(); }
  };

  /* ── HALB AKTUALISIERT: neues Fenster, alter Hintergrund ────────────────
   * Gemeldet 2026-08-30 („Unbekannte Anfrage" beim Ansichts-Schalter). Chrome
   * liest die Popup-SEITE bei jedem Oeffnen frisch, behaelt den
   * Service-Worker aber im Speicher - wer aktualisiert, ohne in
   * chrome://extensions neu zu laden, hat genau diesen Zustand. */
  {
    // AUSGEFUEHRT: passender Stand -> keine Warnung, abweichender -> Warnung.
    const G = { key: "ABC-1", text: "Text", modus: "antwort",
                zeit: Date.now(), kommentare: 1 };
    {
      const r = await laufMit("ABC-1", G, false);        // Stand passt
      check(!/halb aktualisiert/.test(r.meldung),
            "passender Stand: keine Warnung", r.meldung);
    }
    {
      const r = await laufMit("ABC-1", G, false, 1);     // Hintergrund aelter
      check(/halb aktualisiert/.test(r.meldung),
            "alter Hintergrund: die Warnung steht da", r.meldung);
      check(/chrome:\/\/extensions/.test(r.meldung),
            "und nennt den Weg");
      /* ⚠ SIE MUSS GEWINNEN. Die Warnung wird ganz am Ende von start()
       * gesetzt - sonst ueberschreibt sie die naechste Routine-Meldung, und
       * die wichtigste Auskunft des Fensters waere die einzige, die niemand
       * sieht. Hier steht sonst „Gemerkter Vorschlag …". */
      check(!/Gemerkter Vorschlag/.test(r.meldung),
            "und ueberschreibt die Routine-Meldung, nicht umgekehrt", r.meldung);
    }
    {
      // Eine Fassung OHNE das Feld ist per Definition aelter.
      const r = await laufMit("ABC-1", G, false, null);
      check(/halb aktualisiert/.test(r.meldung),
            "fehlt das Feld ganz, gilt der Hintergrund als aelter", r.meldung);
    }
  }

  const GEMERKT = { key: 'ABC-1', text: 'Sehr geehrte Damen und Herren …',
                    modus: 'antwort', zeit: Date.now(), kommentare: 3 };

  // 1) Passt zusammen -> der Text bleibt stehen (sonst waere das Gedaechtnis
  //    wertlos: genau dafuer gibt es es).
  {
    const r = await laufMit('ABC-1', GEMERKT, false);
    check(r.text === GEMERKT.text, 'gleiches Ticket: der Text bleibt', r.text);
    check(r.sichtbar === true, 'und das Feld ist sichtbar');
    check(r.geloescht === false, 'das Gedaechtnis wird NICHT geloescht');
  }

  // 2) ANDERES Ticket -> leeren.
  {
    const r = await laufMit('XYZ-9', GEMERKT, false);
    check(r.text === '', 'anderes Ticket: der Text ist weg', r.text);
    check(r.sichtbar === false, 'das Feld ist ausgeblendet');
    check(r.fuss === '', 'die Fusszeile ebenfalls', r.fuss);
    check(r.hinweis === '', 'auch der Zusatzwunsch', r.hinweis);
    check(r.geloescht === true,
          'und das GEDAECHTNIS ist geloescht (sonst kommt der Text zurueck)');
    check(/ABC-1/.test(r.meldung) && /XYZ-9/.test(r.meldung),
          'die Meldung nennt beide Ticketnummern', r.meldung);
  }

  // 3) KEIN Ticket im Tab -> ebenfalls leeren.
  {
    const r = await laufMit('', GEMERKT, false);
    check(r.text === '', 'kein Ticket: der Text ist weg', r.text);
    check(r.geloescht === true, 'und das Gedaechtnis ebenfalls');
    check(/browse/.test(r.meldung),
          'die Meldung sagt weiterhin, was zu tun ist', r.meldung);
  }

  // 4) Kein Ticket UND nichts gemerkt -> nur die Auskunft, kein Loeschbefehl
  //    (ein Loeschen ohne Anlass waere ein Aufruf ins Leere).
  {
    const r = await laufMit('', null, false);
    check(r.geloescht === false, 'ohne gemerkten Text wird nichts geloescht');
    check(/browse/.test(r.meldung), 'die Auskunft steht trotzdem da', r.meldung);
  }

  // 5) Der Knopf leert von Hand - auch wenn alles zusammenpasst.
  {
    const r = await laufMit('ABC-1', GEMERKT, true);
    check(r.text === '' && r.sichtbar === false,
          'der Leeren-Knopf raeumt das Feld');
    check(r.hinweis === '', 'und den Zusatzwunsch');
    check(r.geloescht === true, 'und das Gedaechtnis');
    check(r.meldung === 'Geleert.', 'mit Rueckmeldung', r.meldung);
  }

  check(/id="btn-leeren"/.test(POPUP_HTML), 'der Knopf steht im Fenster');
  check(/btn-leeren[\s\S]{0,200}addEventListener/.test(POPUP_JS),
        'und ist verdrahtet');
  /* ⚠ DER LAUFENDE MERK-TIMER MUSS GESTOPPT WERDEN: wer den Vorschlag
   * bearbeitet hat, hat einen Timer offen, der `_letztes` eine halbe Sekunde
   * spaeter zurueckschreibt - das Gedaechtnis waere sofort wieder da. */
  const fl = (POPUP_JS.match(/async function felderLeeren\([\s\S]*?\n\}/) || [''])[0];
  check(/clearTimeout\(_merkTimer\)/.test(fl),
        'felderLeeren stoppt den laufenden Merk-Timer');
  check(/wert:\s*null/.test(fl), 'und loescht das Gedaechtnis wirklich');
  check(/_letztes = null/.test(fl), 'der lokale Merker faellt mit');
}

/* ── 9) ZUGRIFFSRECHT VOR ANMELDUNG – der Fix zu "man muss sich 2x anmelden"
 *
 * GEMELDET 2026-08-28. Die Ursache lag nicht in der Anmeldung: fehlte das
 * Host-Recht, erfragte das Fenster es MITTEN im Anmelde-Ablauf – und Chrome
 * schliesst dabei das Popup. Der Klick auf "Anmelden" endete im Nichts, die
 * Zugangsdaten wurden nie abgeschickt. Beim zweiten Anlauf war das Recht da.
 *
 * GEMESSEN WIRD DIE REIHENFOLGE, nicht der Quelltext: erst merken, dann
 * fragen, dann anmelden. Ein Test, der nur nach `permissions.request` sucht,
 * bliebe gruen, wenn der Aufruf wieder hinter die Anmeldung rutscht – also
 * genau bei dem Fehler, um den es hier geht. */
section("9) Zugriffsrecht: erst merken, dann fragen, dann anmelden");
{
  /* Der Klick-Handler haengt an `addEventListener` auf Modulebene und laesst
   * sich nicht als Funktion herausschneiden. Deshalb wird sein RUMPF
   * geschnitten und als eigene Funktion ausgefuehrt – zusammen mit den
   * Helfern, die er benutzt. */
  const handler = (POPUP_JS.match(
    /\$\("btn-anmelden"\)\.addEventListener\("click", async \(\) => \{([\s\S]*?)\n\}\);/) || [])[1];
  check(!!handler, 'der Anmelden-Handler laesst sich schneiden');

  /* Transitiv geschnitten. `sperre` zieht seit 2026-08-30 die Ticket-Sperre
   * nach – mit der frueheren festen Liste fehlte `knoepfeAktualisieren`, und
   * der Lauf brach mit einem nackten ReferenceError ab statt fehlzuschlagen.
   * Vierter Harness in dieser Datei, in dem dieselbe Falle stand. */
  const { teile: t4, drin: d4 } = popupTeile(
    ['melde', 'sperre', 'zeige', 'hostMuster', 'hatZugriff',
     'zugriffAnzeigen', 'zugriffSichern'],
    ['frage', 'brandingHolen']);
  for (const name of ['melde', 'sperre', 'zeige', 'hostMuster', 'hatZugriff',
                      'zugriffAnzeigen', 'zugriffSichern']) {
    check(d4.has(name), 'popup.js hat ' + name + '()');
  }
  const teile = t4;

  /** Ein Anmelde-Klick mit gestellter Berechtigungslage.
   *  `hat`: liegt das Recht schon vor? `erteilt`: sagt der Benutzer im
   *  Browser-Dialog ja? */
  const anmeldeKlick = async (hat, erteilt) => {
    const dom = new JSDOM(POPUP_HTML, { url: 'https://x.test/',
                                        runScripts: 'outside-only' });
    const w = dom.window;
    try {
      const f = new w.Function('hat', 'erteilt', `
        const spur = [];            // die REIHENFOLGE aller Ereignisse
        let erlaubt = hat;
        const api = { permissions: {
          async contains() { return erlaubt; },
          async request() {
            spur.push("request");
            if (erteilt) erlaubt = true;
            return erteilt;
          },
        } };
        const $ = (id) => document.getElementById(id);
        const el = {
          login: $("bereich-login"), arbeit: $("bereich-arbeit"),
          basis: $("f-basis"), benutzer: $("f-benutzer"),
          kennwort: $("f-kennwort"), totp: $("f-totp"),
          meldung: $("meldung"), abmelden: $("btn-abmelden"),
        };
        let _marke = "Marke", _key = "ABC-1";
        async function frage(n) {
          spur.push(n.art);
          if (n.art === "merken") return { ok: true };
          if (n.art === "anmelden") return { ok: true, erlaubt: true, hinweis: "" };
          return { ok: true };
        }
        function brandingHolen() {}
        let _laeuft = false;
` + teile.join('\n') + `
        return (async () => {
          el.basis.value = "https://s.test";
          el.benutzer.value = "alice";
          el.kennwort.value = "geheim";
          await (async () => {${handler}})();
          return JSON.stringify({
            spur,
            meldung: el.meldung.hidden ? "" : el.meldung.textContent,
            kennwortFeld: el.kennwort.value,
            angemeldet: !el.arbeit.hidden,
          });
        })();`);
      return JSON.parse(await f(hat, erteilt));
    } finally { w.close(); }
  };

  // a) Recht liegt vor (der Normalfall mit gebrandetem Paket): gar keine
  //    Nachfrage, EINE Anmeldung.
  {
    const r = await anmeldeKlick(true, false);
    check(!r.spur.includes('request'),
          'mit vorhandenem Recht wird NICHT nachgefragt', JSON.stringify(r.spur));
    check(r.spur.includes('anmelden'), 'und die Anmeldung laeuft durch');
    check(r.angemeldet === true, 'der Arbeitsbereich ist danach offen');
    check(r.kennwortFeld === '', 'das Kennwort verlaesst das Feld');
  }

  // b) Recht fehlt und wird erteilt: merken → fragen → anmelden, in DIESER
  //    Reihenfolge. Das Merken MUSS vor der Nachfrage stehen – danach kann
  //    das Fenster weg sein.
  {
    const r = await anmeldeKlick(false, true);
    const iM = r.spur.indexOf('merken');
    const iR = r.spur.indexOf('request');
    const iA = r.spur.indexOf('anmelden');
    check(iM >= 0, 'Adresse und Benutzer werden gemerkt', JSON.stringify(r.spur));
    check(iM < iR, 'und zwar VOR der Berechtigungsabfrage', JSON.stringify(r.spur));
    check(iR >= 0 && iR < iA,
          'die Abfrage steht VOR der Anmeldung – nicht mittendrin',
          JSON.stringify(r.spur));
    check(iA >= 0, 'nach dem Erteilen wird angemeldet – ohne zweiten Klick');
  }

  // c) Recht fehlt und wird VERWEIGERT: es darf keine Anmeldung geben, und
  //    der Grund muss dastehen. Ein stiller Abbruch ist genau das gemeldete
  //    Symptom.
  {
    const r = await anmeldeKlick(false, false);
    check(!r.spur.includes('anmelden'),
          'ohne Recht wird gar nicht erst angemeldet', JSON.stringify(r.spur));
    check(/Zugriffsrecht/.test(r.meldung),
          'und der Grund steht im Fenster', r.meldung);
    check(/Anmelden/.test(r.meldung),
          'samt dem Weg zurueck (erneut druecken)', r.meldung);
  }

  /* Der Hinweis ueber dem Knopf: er muss VOR dem Klick dastehen, sonst liest
   * ihn niemand rechtzeitig. */
  check(/id="zugriff-hinweis"/.test(POPUP_HTML),
        'das Fenster hat einen Platz fuer die Erklaerung');

  /* WANN der Hinweis erscheint, wird AUSGEFUEHRT statt im Quelltext gelesen.
   * Die erste Fassung dieses Waechters suchte nach "=== false" und meldete
   * einen Fehler, obwohl dort "!== false" stand – dieselbe Aussage, andere
   * Schreibweise. Ein Waechter, der die Schreibweise prueft, prueft nicht die
   * Eigenschaft. */
  const hinweisBei = async (lage) => {
    const dom = new JSDOM(POPUP_HTML, { url: 'https://x.test/',
                                        runScripts: 'outside-only' });
    const w = dom.window;
    try {
      const f = new w.Function('lage', `
        const api = { permissions: { async contains() {
          if (lage === 'kaputt') throw new Error('geht nicht');
          return lage === 'da';
        } } };
        const $ = (id) => document.getElementById(id);
        const el = { basis: $("f-basis") };
        ${teile.join('\n')}
        return (async () => {
          el.basis.value = "https://s.test";
          await zugriffAnzeigen();
          const p = $("zugriff-hinweis");
          return JSON.stringify({ sichtbar: !p.hidden, text: p.textContent });
        })();`);
      return JSON.parse(await f(lage));
    } finally { w.close(); }
  };
  check((await hinweisBei('fehlt')).sichtbar === true,
        'fehlt das Recht, steht die Erklaerung ueber dem Knopf');
  check(/schließt/.test((await hinweisBei('fehlt')).text),
        'und sie kuendigt an, dass das Fenster dabei zugehen kann');
  check((await hinweisBei('da')).sichtbar === false,
        'mit vorhandenem Recht steht dort nichts');
  /* "Nicht feststellbar" ist NICHT "fehlt" – eine Warnung auf Verdacht
   * verunsichert bei einer funktionierenden Einrichtung. Meldet sich der
   * Aufruf spaeter doch, steht der Grund im Meldungsfeld. */
  check((await hinweisBei('kaputt')).sichtbar === false,
        '"nicht feststellbar" erzeugt KEINE Warnung');

  /* Die Adresse aus dem Paket – ohne sie tippt jemand eine abweichende
   * Schreibweise ein, fuer die das vorbelegte Recht nicht gilt. */
  check(/meta\[name="basis"\]/.test(POPUP_JS),
        'popup.js liest die Adress-Vorgabe aus dem Paket');
  const vb = (POPUP_JS.match(/function _vorgabeBasis\([\s\S]*?\n\}/) || [''])[0];
  check(/https/.test(vb), 'und nimmt nur https-Adressen an');
  check(/z\.basis \|\| _vorgabeBasis\(\)/.test(POPUP_JS),
        'eine hinterlegte Adresse schlaegt die Vorgabe aus dem Paket');

  /* Das Kennwort darf NIE gemerkt werden – der Benutzername schon. */
  const BG_OHNE = ohneKommentare(BG);
  check(/benutzer/.test(BG_OHNE) && !/kennwort:/.test(
          (BG_OHNE.match(/async function einstSchreiben\([\s\S]*?\n\}/) || [''])[0]),
        'der Hintergrund merkt den Benutzernamen, nie das Kennwort');
}

// ═══════════════════════════════════════════════════════════════════════════
section("10) Seitenleiste statt Popup (2026-08-30)");
// ═══════════════════════════════════════════════════════════════════════════
/* Zwei Meldungen aus dem Betrieb, eine Ursache: das Popup laesst sich nicht
 * in der Groesse ziehen (der Browser zeichnet es um den Inhalt und klemmt es
 * auf 800x600 - es gibt dafuer keine API), und wer neben dem Ticket arbeitet,
 * will es ohnehin offen behalten. Die Leiste loest beides.
 *
 * DIE OBERFLAECHE BLEIBT DIESELBE DATEI. Eine zweite waere eine Kopie, und
 * Kopien laufen auseinander - dieselbe Begruendung, aus der es nur zwei
 * Manifeste und nicht zwei Codebasen gibt. */
{
  const ANS = lies("ansicht.js");

  // ── a) Manifeste ────────────────────────────────────────────────────────
  check(M_CHROME.permissions.includes("sidePanel"),
        "Chrome deklariert die sidePanel-Berechtigung");
  check(!!(M_CHROME.side_panel && M_CHROME.side_panel.default_path),
        "Chrome traegt einen side_panel-Pfad");
  check(!!(M_FF.sidebar_action && M_FF.sidebar_action.default_panel),
        "Firefox traegt einen sidebar_action-Pfad");

  /* `sidePanel` gibt es in Firefox NICHT. Eine unbekannte Berechtigung
   * quittiert Firefox beim Installieren mit einer Warnung - auf einem Paket,
   * das ohnehin einzeln signiert werden muss, ist das der falsche Auftakt. */
  check(!(M_FF.permissions || []).includes("sidePanel"),
        "Firefox deklariert sie NICHT - dort gibt es sie nicht");

  /* ⚠ AB HIER NUR NOCH ABGESICHERT ZUGREIFEN. Ein fehlender Schluessel liess
   * die Pruefungen darunter mit einem TypeError ABBRECHEN statt fehlzuschlagen
   * - der ganze Lauf endete dann ohne Zaehlzeile und sah aus, als waere er gar
   * nicht gelaufen (Register: nie ungeprueft dereferenzieren). */
  const cPfad = (M_CHROME.side_panel || {}).default_path || "";
  const fPfad = (M_FF.sidebar_action || {}).default_panel || "";

  /* EINE Oberflaeche fuer beide Ansichten. */
  check(cPfad === "popup.html" && fPfad === "popup.html",
        "beide Leisten zeigen dieselbe popup.html", cPfad + " / " + fPfad);

  /* ⚠ IM MANIFEST STEHT KEIN ABFRAGETEIL. Fuer `setOptions`/`setPanel` ist ein
   * Pfad mit `?…` belegt, fuer die Manifest-Schluessel nicht - und ein
   * Manifest, das der Browser ablehnt, macht die ganze Erweiterung
   * uninstallierbar. Gesetzt wird er deshalb zur Laufzeit. */
  check(!!cPfad && !!fPfad && !/\?/.test(cPfad) && !/\?/.test(fPfad),
        "und zwar OHNE Abfrageteil - den setzt erst der Hintergrund");

  /* Firefox klappt die Leiste sonst beim Installieren von selbst auf, obwohl
   * die Vorgabe das Popup ist. */
  check((M_FF.sidebar_action || {}).open_at_install === false,
        "Firefox oeffnet die Leiste NICHT beim Installieren");

  /* DIE VORGABE BLEIBT DAS POPUP - fuer Bestandsnutzer aendert sich nichts,
   * bis sie den Schalter umlegen. */
  check((M_CHROME.action || {}).default_popup === "popup.html",
        "die Vorgabe bleibt das Popup (Chrome)");
  check((M_FF.action || {}).default_popup === "popup.html",
        "die Vorgabe bleibt das Popup (Firefox)");

  // ── b) Drift-Schranke: jede eingebundene Datei muss in BEIDE Paketlisten ─
  /* Die Dateiliste steht an DREI Orten: popup.html bindet ein, bauen.sh packt
   * lokal, jira_assist.PAKET_DATEIEN packt der Server beim Abruf ueber die
   * Kachel. Laufen sie auseinander, installiert sich das Paket klaglos und
   * bricht erst beim Benutzen - hier waere die Leiste dann still 380 px
   * schmal. Geprueft wird die REGEL, nicht eine Aufzaehlung: was popup.html
   * einbindet, muss in beiden Listen stehen. */
  const BAUEN = fs.readFileSync(path.join(ADDON, "bauen.sh"), "utf8");
  const ASSIST = fs.readFileSync(
    path.join(WURZEL, "backend", "jira_assist.py"), "utf8");
  const paketListe = (ASSIST.match(/PAKET_DATEIEN\s*=\s*\(([\s\S]*?)\)/) || ["", ""])[1];
  const bauenListe = (BAUEN.match(/DATEIEN\s*=\s*\[([\s\S]*?)\]/) || ["", ""])[1];
  const eingebunden = [
    ...POPUP_HTML.matchAll(/<script[^>]+src="([^"]+)"/g),
    ...POPUP_HTML.matchAll(/<link[^>]+href="([^"]+)"/g),
  ].map((m) => m[1].split("?")[0]).filter((d) => !/^https?:/.test(d));
  check(eingebunden.length >= 3,
        "popup.html bindet mehrere eigene Dateien ein", eingebunden.join(", "));
  for (const d of eingebunden) {
    check(paketListe.includes('"' + d + '"'),
          "PAKET_DATEIEN enthaelt " + d);
    check(bauenListe.includes('"' + d + '"'),
          "bauen.sh enthaelt " + d);
  }

  // ── c) ansicht.js setzt die Klasse - wirklich ausgefuehrt ───────────────
  /* Eigene Datei statt Inline-Skript: Erweiterungsseiten laufen unter
   * `script-src 'self'`, ein Skriptrumpf im HTML wird wortlos geblockt. */
  check(/<script src="ansicht\.js">/.test(POPUP_HTML),
        "popup.html laedt ansicht.js");
  check(POPUP_HTML.indexOf('src="ansicht.js"') < POPUP_HTML.indexOf("popup.css"),
        "und zwar VOR dem Stylesheet - sonst blitzt die falsche Breite auf");
  check(!/<script>[\s\S]*?ansicht/.test(POPUP_HTML),
        "kein Inline-Skript - die CSP der Erweiterungsseite verbietet es");

  const klasseBei = (suche) => {
    const dom = new JSDOM("<html><head></head><body></body></html>",
                          { url: "https://x.test/popup.html" + suche });
    try {
      new dom.window.Function("location", "document", ANS)(
        { search: suche }, dom.window.document);
      return dom.window.document.documentElement.classList.contains("leiste");
    } finally { dom.window.close(); }
  };
  check(klasseBei("?ansicht=leiste") === true,
        "mit ?ansicht=leiste entsteht die Klasse `leiste`");
  check(klasseBei("") === false, "ohne Abfrageteil bleibt es beim Popup");
  check(klasseBei("?ansicht=popup") === false, "und bei ?ansicht=popup ebenso");

  // ── d) Der Umschalter im Hintergrund - wirklich ausgefuehrt ─────────────
  /* `action.setPopup` IST der Umschalter: solange ein Popup gesetzt ist,
   * gewinnt es, `openPanelOnActionClick` bleibt wirkungslos und `onClicked`
   * feuert nicht. Erst ein LEERER Pfad gibt den Klick frei. */
  const bgTeil = (name) => (BG.match(new RegExp(
    "(?:async )?function " + name + "\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}")) || [null])[0];
  /* Transitiv, wie in popup.js: `ansichtAnwenden` ruft seit 2026-08-30
   * `zweig()`, und mit der frueheren festen Liste brach der Lauf mit einem
   * nackten ReferenceError ab statt fehlzuschlagen. Fuenfter Harness in dieser
   * Datei mit derselben Falle. */
  const bgTeile = (start, gestellt) => {
    const G = new Set(gestellt || []);
    const teile = [], drin = new Set(), offen = start.slice();
    while (offen.length) {
      const n = offen.shift();
      if (drin.has(n) || G.has(n)) continue;
      const k = bgTeil(n);
      if (!k) continue;
      drin.add(n); teile.push(k);
      for (const t of k.match(/\b[A-Za-z_$][\w$]*(?=\s*\()/g) || []) {
        if (!drin.has(t) && !G.has(t) && bgTeil(t)) offen.push(t);
      }
    }
    return { teile, drin };
  };
  const { teile: bgT, drin: bgD } = bgTeile(["ansichtAnwenden", "aktion"], []);
  const anwenden = bgT.join("\n");
  check(bgD.has("ansichtAnwenden") && bgD.has("aktion"),
        "background.js hat ansichtAnwenden() und aktion()");
  check(bgD.has("zweig") && bgD.has("_wurzeln"),
        "der Schnitt zieht die API-Wurzelsuche mit", [...bgD].join(","));
  /* Der Pfad ist eine Modul-Konstante und gehoert in den Schnitt. Fehlte er,
   * warf `ansichtAnwenden` - und weil dort JEDER Schritt einzeln abgesichert
   * ist, verschwand der Fehler im leeren catch: der Lauf meldete FAIL und es
   * sah nach einem Codefehler aus, war aber ein Testmangel. */
  const PFAD_ZEILE = (BG.match(/const LEISTE_PFAD = "[^"]+";/) || [""])[0];
  check(/\?ansicht=leiste/.test(PFAD_ZEILE),
        "background.js kennt den Leisten-Pfad", PFAD_ZEILE);

  /* ⚠ DIE WELTEN WERDEN ALS ECHTE GLOBALE `chrome`/`browser` GESTELLT.
   *
   * Vorher stellte der Lauf nur ein `api`-Objekt - damit war der gemeldete
   * Fehler gar nicht nachstellbar: `api` ist `browser ?? chrome`, und genau
   * DIESE Aufloesung war das Problem. Chrome 152 definiert selbst ein
   * `browser`-Objekt, in dem `sidePanel` NICHT vorkommt (Chrome-eigene API) -
   * `api.sidePanel` war undefined, obwohl `chrome.sidePanel` da ist. */
  const laufAnsicht = async (modus, welt) => {
    const spur = [];
    const panelStub = () => ({
      setOptions: async (o) => { spur.push(["optionen", o.path, o.enabled]); },
      setPanelBehavior: async (o) => {
        spur.push(["verhalten", o.openPanelOnActionClick]); },
    });
    const aktionStub = () => ({
      setPopup: async (o) => { spur.push(["popup", o.popup]); },
    });
    const runtimeStub = () => ({
      getURL: (p) => "ext://x/" + p,
      getManifest: () => ({ side_panel: { default_path: "popup.html" } }),
    });
    let C, B;
    if (welt === "chrome") {
      C = { action: aktionStub(), sidePanel: panelStub(), runtime: runtimeStub() };
      B = undefined;
    } else if (welt === "chrome152") {
      // DER GEMELDETE FALL: `browser` ist da, kennt aber kein sidePanel.
      C = { action: aktionStub(), sidePanel: panelStub(), runtime: runtimeStub() };
      B = { action: aktionStub(), runtime: runtimeStub() };
    } else {
      C = undefined;
      B = { action: aktionStub(), runtime: runtimeStub(),
            sidebarAction: { setPanel: async (o) => { spur.push(["panel", o.panel]); } } };
    }
    const a = B || C;
    await new Function("api", "chrome", "browser",
                       PFAD_ZEILE + "\n" + anwenden
                       + "\nreturn ansichtAnwenden(" + JSON.stringify(modus) + ");")(a, C, B);
    return spur;
  };

  {
    const s = await laufAnsicht("leiste", "chrome");
    check(s.some((z) => z[0] === "popup" && z[1] === ""),
          "Chrome/Leiste: der Popup-Pfad wird GELEERT", JSON.stringify(s));
    check(s.some((z) => z[0] === "verhalten" && z[1] === true),
          "und der Klick oeffnet das Panel");
    check(s.some((z) => z[0] === "optionen" && /\?ansicht=leiste/.test(z[1])),
          "der Panel-Pfad traegt den Abfrageteil");
  }
  {
    const s = await laufAnsicht("popup", "chrome");
    check(s.some((z) => z[0] === "popup" && z[1] === "popup.html"),
          "Chrome/Popup: der Popup-Pfad wird wieder gesetzt", JSON.stringify(s));
    check(s.some((z) => z[0] === "verhalten" && z[1] === false),
          "und der Klick oeffnet kein Panel mehr");
    /* ⚠ DER PFAD WIRD IN BEIDEN MODI GESETZT. Nur so ist er schon richtig,
     * wenn der Benutzer den Schalter umlegt und die Leiste im selben Klick
     * aufgeht - `setOptions` kaeme sonst zu spaet und die Leiste stuende in
     * der Popup-Breite da. */
    check(s.some((z) => z[0] === "optionen" && /\?ansicht=leiste/.test(z[1])),
          "der Panel-Pfad wird AUCH im Popup-Modus gesetzt");
  }
  /* ⚠ DER GEMELDETE FALL (Chrome 152, 2026-08-30): `browser` ist definiert,
   * kennt aber kein `sidePanel`. Ueber `api = browser ?? chrome` war die
   * ganze Panel-Steuerung damit ein stiller No-op - der Klick aufs Symbol
   * oeffnete nie die Leiste, und die Faehigkeitspruefung meldete "dieser
   * Browser kann das nicht" auf einem Browser, der es kann. */
  {
    const s = await laufAnsicht("leiste", "chrome152");
    check(s.some((z) => z[0] === "verhalten" && z[1] === true),
          "browser OHNE sidePanel: die Panel-Steuerung wird trotzdem erreicht",
          JSON.stringify(s));
    check(s.some((z) => z[0] === "optionen" && /\?ansicht=leiste/.test(z[1])),
          "und der Panel-Pfad wird gesetzt");
    check(s.some((z) => z[0] === "popup" && z[1] === ""),
          "der Popup-Pfad wird geleert");
  }
  {
    const s = await laufAnsicht("leiste", "firefox");
    check(s.some((z) => z[0] === "popup" && z[1] === ""),
          "Firefox/Leiste: der Popup-Pfad wird geleert", JSON.stringify(s));
    check(s.some((z) => z[0] === "panel" && /\?ansicht=leiste/.test(z[1])),
          "und die Sidebar bekommt den Pfad mit Abfrageteil");
    check(s.every((z) => z[0] !== "verhalten"),
          "ohne sidePanel wird dort nichts davon gerufen");
  }

  /* Ein unbekannter Wert in der Ablage darf nicht in einem dritten Zustand
   * enden - dann oeffnet gar nichts mehr und niemand sieht warum. */
  {
    const es = bgTeil("einstSchreiben");
    check(!!es && /ansicht\s*=\s*\(teil\.ansicht === "leiste"\)/.test(es),
          "einstSchreiben normalisiert die Ansicht auf zwei Werte");
  }

  /* Nach einem Browserstart (und unter MV3 nach jedem Ende des
   * Service-Workers) muss der Modus wiederhergestellt werden - `setPopup` gilt
   * nur fuer die laufende Sitzung. */
  const bgOhneK = ohneKommentare(BG);
  for (const wo of ["onInstalled", "onStartup"]) {
    check(new RegExp("runtime\\." + wo + "[\\s\\S]{0,120}ansichtHerstellen").test(bgOhneK),
          "die Ansicht wird bei " + wo + " wiederhergestellt");
  }
  check(/\nansichtHerstellen\(\);/.test(bgOhneK),
        "und bei jedem Start des Hintergrunds");

  /* ⚠ IM KLICK-ZUWEIGER DARF VOR DEM OEFFNEN KEIN `await` STEHEN. Beide APIs
   * verlangen eine Benutzergeste, und die ist nach dem ersten `await` weg -
   * der Aufruf wird dann abgelehnt und es passiert sichtbar gar nichts. */
  {
    const h = (bgOhneK.match(/onClicked\.addListener\(([\s\S]*?)\n  \}\);/) || [null])[0];
    check(!!h, "der Klick auf das Symbol ist verdrahtet");
    if (h) {
      check(!/await/.test(h),
            "und oeffnet OHNE vorheriges await - sonst ist die Benutzergeste weg");
      check(/sidebarAction[\s\S]*toggle/.test(h) && /sidePanel[\s\S]*open/.test(h),
            "er bedient beide Welten");
    }
  }

  // ── e) popup.js: Beobachtung, Ableitung, Reihenfolge ────────────────────
  /* ⚠ DIE KLASSE IST NUR DER ANFANGSWERT, NICHT DIE ANTWORT.
   *
   * Hier stand bis zur Meldung vom 2026-08-30 `const _leiste = …classList…`.
   * Der Abfrageteil `?ansicht=leiste` kommt aber NUR mit, wenn die Leiste ueber
   * unseren Weg aufgeht - ueber Chromes eigene Seitenleisten-Auswahl laedt sie
   * `side_panel.default_path`, also popup.html ohne Abfrageteil. Das Fenster
   * hielt sich dann fuer ein Popup und registrierte keinen Tab-Zuhoerer.
   * Verbindlich antwortet jetzt der Hintergrund ueber runtime.getContexts. */
  check(/let _leiste = document\.documentElement\.classList\.contains\("leiste"\)/
        .test(POPUP_JS),
        "die Klasse ist der Anfangswert der Ansicht");
  const lf = schneidePopup("leisteFeststellen");
  check(!!lf, "popup.js hat leisteFeststellen()");
  check(!!lf && /SIDE_PANEL/.test(lf) && /_leiste = true/.test(lf),
        "und macht aus der Kontextauskunft des Hintergrunds die Leiste");
  /* NUR EINSCHALTEN, nie ausschalten: sagt der Hintergrund nichts (aeltere
   * Browser, Firefox ohne getContexts), bleibt der Abfrageteil die einzige
   * Auskunft, die es gibt. */
  check(!!lf && !/_leiste = false/.test(lf),
        "sie schaltet die Leiste nie AB - sonst faellt der Rueckfall aus");
  check(/leisteFeststellen\(z\.kontext\)/.test(POPUP_JS),
        "start() traegt die Auskunft nach");
  {
    const bg = ohneKommentare(BG);
    check(/getContexts/.test(bg) && /contextType/.test(bg),
          "der Hintergrund ermittelt die Kontextart ueber runtime.getContexts");
    check(/kontext: await kontextArt\(absender\)/.test(bg),
          "und schickt sie mit dem Zustand mit");
  }

  {
    const lb = schneidePopup("leisteBeobachten");
    check(!!lb, "popup.js hat leisteBeobachten()");
    /* Im Popup wird NICHT beobachtet: dort gibt es keinen Tab-Wechsel zu
     * sehen, und ein Zuhoerer, der nie feuert, ist nur eine Fehlerquelle. */
    check(!!lb && /if \(!_leiste[\s\S]{0,60}return;/.test(lb),
          "sie tut im Popup-Modus nichts");
    check(!!lb && /onActivated/.test(lb) && /onUpdated/.test(lb),
          "und haengt sich an Tab-Wechsel UND Adressaenderung");
    /* Jira wechselt das Ticket ohne Neuladen - das meldet sich als info.url.
     * Ein Filter auf `status: complete` verpasst genau diesen Fall. */
    /* ⚠ OHNE KOMMENTARE PRUEFEN. Die Begruendungen im Code nennen die
     * gesuchten Bezeichner woertlich - der Waechter fand seinen eigenen Text
     * und meldete einen Fehler, den es nicht gab (belegter Fall im Projekt). */
    const lbO = ohneKommentare(lb || "");
    /* ⚠ HIER STAND EIN FILTER AUF `info.url` - UND DAS WAR DER FEHLER.
     * `changeInfo.url` liefert der Browser nur mit der `tabs`-Berechtigung
     * oder einem Host-Recht fuer genau diese Seite; die Erweiterung hat beides
     * von Haus aus nicht. Der Zuhoerer war damit so gut wie tot (gemeldet
     * 2026-08-30). Entschieden wird jetzt ueber den VERGLEICH in tabWechsel. */
    check(!/info\.url/.test(lbO) && !/status/.test(lbO),
          "der Zuhoerer filtert NICHT auf info.url - das braeuchte ein Host-Recht");
    check(/tab\.active/.test(lbO),
          "er beschraenkt sich aber auf den sichtbaren Tab");
  }

  /* ⚠ DER TAB-WECHSEL IST EINE SICHERHEITSFRAGE. Gemessen, nicht gelesen:
   * `tabWechsel` wird mit echtem DOM ausgefuehrt. Ohne diese Pruefung stuende
   * in der offenen Leiste ein fertiger Antwortentwurf zu TICKET-A neben dem
   * geoeffneten TICKET-B - und der Text geht an einen echten Kunden. */
  {
    const { teile: t2, drin: d2 } = popupTeile(
      // textZuFeld/feldZuText: die Attrappe baut und liest den Feldinhalt damit.
      ["tabWechsel", "textZuFeld", "feldZuText"], ["tabErmitteln", "frage"]);
    check(d2.has("ticketLageAnwenden") && d2.has("felderLeeren"),
          "der Schnitt um tabWechsel zieht die Leer-Logik mit",
          [...d2].join(","));

    const wechselLauf = async (vonKey, nachKey, gemerkt, laeuft) => {
      const dom = new JSDOM(POPUP_HTML, { url: "https://x.test/",
                                          runScripts: "outside-only" });
      const w = dom.window;
      try {
        const f = new w.Function("vonKey", "nachKey", "gemerkt", "laeuft", `
            const gesendet = [];
            const $ = (id) => document.getElementById(id);
            const el = {
              ergebnisFeld: $("f-ergebnis"), ergebnis: $("ergebnis"),
              ergebnisFuss: $("ergebnis-fuss"), meldung: $("meldung"),
              ticket: $("ticket-anzeige"), hinweis: $("f-hinweis"),
            };
            let _key = vonKey, _letztes = gemerkt, _fremdesErgebnis = false;
            let _merkTimer = null, _laeuft = laeuft, _marke = "Marke";
            /* ticketLageAnwenden stoesst die Automatik an; ohne diese Variable
             * wirft die geschnittene Funktion einen ReferenceError - und weil
             * sie NICHT abgewartet wird, kaeme der als unbehandelte
             * Zurueckweisung zurueck, die je nach Zeitpunkt den Lauf abbricht
             * oder gar nicht auffaellt. Hier bedeutet "" = Automatik aus, also
             * genau das Verhalten, das dieser Abschnitt messen will.
             * Abschnitt 14 prueft die Automatik selbst. */
            let _autoModus = "";
            Object.defineProperty(el.ergebnisFeld, "value", {
              get() { throw new Error("value am Ergebnisfeld GELESEN"); },
              set() { throw new Error("value am Ergebnisfeld GESETZT"); },
            });
            let _jiraBasis = "", _leiste_unbenutzt = 0;
            const _leiste = true;
            let _tabUrl = "https://jira.test/browse/" + (nachKey || "X-1");
            let _windowId = 7, _tabId = 1;
            const api = { permissions: { contains: async () => true } };
            async function frage(n) { gesendet.push(n); return { ok: true }; }
            async function tabErmitteln() {
              _key = nachKey; el.ticket.textContent = _key || "";
            }
` + FELD_KONST + "\n" + t2.join("\n") + `
            return (async () => {
              textZuFeld(el.ergebnisFeld, (gemerkt && gemerkt.text) || "");
              el.ergebnis.hidden = !(gemerkt && gemerkt.text);
              await tabWechsel();
              return JSON.stringify({
                text: feldZuText(el.ergebnisFeld),
                sichtbar: !el.ergebnis.hidden,
                meldung: el.meldung.hidden ? "" : el.meldung.textContent,
                geloescht: gesendet.some(n => n && n.art === "ergebnis_merken"
                                              && n.wert === null),
              });
            })();`);
        return JSON.parse(await f(vonKey, nachKey, gemerkt, laeuft));
      } finally { w.close(); }
    };

    const G = { key: "ABC-1", text: "Sehr geehrte Damen und Herren …",
                modus: "antwort", zeit: Date.now(), kommentare: 3 };

    // 1) Wechsel auf ein ANDERES Ticket -> leeren, auch im Gedaechtnis.
    {
      const r = await wechselLauf("ABC-1", "XYZ-9", G, false);
      check(r.text === "", "Tab-Wechsel auf ein anderes Ticket leert das Feld",
            r.text);
      check(r.sichtbar === false, "und blendet es aus");
      check(r.geloescht === true, "das Gedaechtnis wird mit geleert");
      check(/XYZ-9/.test(r.meldung) && /ABC-1/.test(r.meldung),
            "die Meldung nennt beide Vorgaenge", r.meldung);
    }
    // 2) Derselbe Vorgang bleibt derselbe - kein Wechsel, nichts passiert.
    {
      const r = await wechselLauf("ABC-1", "ABC-1", G, false);
      check(r.text === G.text, "gleiches Ticket: der Text bleibt", r.text);
      check(r.geloescht === false, "und das Gedaechtnis bleibt");
    }
    // 3) Tab ohne Ticket -> ebenfalls leeren (der Text gehoert nirgendwohin).
    {
      const r = await wechselLauf("ABC-1", "", G, false);
      check(r.text === "", "Tab ohne Ticket: der Text ist weg");
      check(r.geloescht === true, "auch hier faellt das Gedaechtnis");
    }
    /* 4) WAEHREND EINER LAUFENDEN AUSWERTUNG WIRD NICHT GELEERT. Der Benutzer
     *    wartet auf genau dieses Ergebnis; es wegzuwerfen, weil er nebenbei
     *    nachgesehen hat, waere die teuerste Reaktion. Gewarnt wird trotzdem -
     *    und die Einfuege-Schranke greift ohnehin ueber `fremd()`. */
    {
      const r = await wechselLauf("ABC-1", "XYZ-9", G, true);
      check(r.text === G.text, "waehrend einer Auswertung bleibt der Text",
            r.text);
      check(r.geloescht === false, "und das Gedaechtnis unangetastet");
      check(/⚠/.test(r.meldung), "gewarnt wird trotzdem", r.meldung);
    }
  }

  // ── f) Zugriffsrecht: nur in der Leiste, nur https ──────────────────────
  /* Das Popup kommt mit `activeTab` aus - der Klick erteilt das Recht fuer den
   * Tab, in dem gearbeitet wird, und laenger lebt das Popup nicht. Die Leiste
   * ueberlebt den Tab-Wechsel; fuer den naechsten Tab gilt `activeTab` nicht
   * mehr. */
  {
    // Transitiv: `tabHerkunft` reicht seit 2026-08-30 an `herkunftAus` weiter,
    // damit auch die Jira-Adresse aus dem Server durch dieselbe Pruefung geht.
    const { teile: t5, drin: d5 } = popupTeile(["tabHerkunft"], []);
    check(d5.has("tabHerkunft"), "popup.js hat tabHerkunft()");
    check(d5.has("herkunftAus"),
          "und die Herkunftspruefung liegt in EINER Funktion", [...d5].join(","));
    const herkunft = (url) =>
      new Function("_tabUrl", t5.join("\n") + "; return tabHerkunft();")(url);
    check(herkunft("https://jira.test/browse/A-1") === "https://jira.test",
          "https liefert die Herkunft");
    check(herkunft("http://jira.test/browse/A-1") === "",
          "http NICHT - optional_host_permissions deckt nur https");
    check(herkunft("about:blank") === "", "und eine interne Seite ebenso wenig");
    check(herkunft("") === "", "eine leere Adresse wirft nicht");

    const zz = schneidePopup("zugriffZeileAktualisieren");
    check(!!zz, "popup.js hat zugriffZeileAktualisieren()");
    check(!!zz && /if \(!_leiste/.test(zz),
          "die Zeile bleibt im Popup-Modus aus");
    /* "Nicht feststellbar" wird wie "vorhanden" behandelt - dieselbe Regel wie
     * bei zugriffAnzeigen: eine Aufforderung auf Verdacht verunsichert bei
     * einer funktionierenden Einrichtung. */
    check(!!zz && /da !== false/.test(zz),
          '"nicht feststellbar" erzeugt keine Aufforderung');
  }
  /* ⚠ DIE ZEILE LIEF IM KREIS - gemeldet am 2026-08-30 als "Tab-Wechsel wird
   * nicht erkannt". Ohne Host-Recht liefert `tabs.query` fuer einen fremden
   * Tab GAR KEINE Adresse; damit gibt es keine Ticketnummer, und die Zeile
   * haing an einer Ticketnummer: sie war ausgerechnet dann verborgen, wenn sie
   * gebraucht wurde. AUSGEFUEHRT geprueft, nicht gelesen. */
  {
    const { teile: t6 } = popupTeile(
      ["zugriffZeileAktualisieren"], ["frage"]);
    const zeigeBei = async (leiste, tabUrl, key, hatRecht, basis) => {
      const dom = new JSDOM(POPUP_HTML, { url: "https://x.test/",
                                          runScripts: "outside-only" });
      const w = dom.window;
      try {
        const f = new w.Function("leiste", "tabUrl", "key", "hatRecht", "basis", `
          const $ = (id) => document.getElementById(id);
          const gefragt = [];
          let _leiste = leiste, _tabUrl = tabUrl, _key = key, _jiraBasis = "";
          const api = { permissions: {
            async contains(o) { gefragt.push(o.origins[0]); return hatRecht; },
          } };
          async function frage(n) {
            if (n.art === "health") return { ok: true, daten: { jira_basis: basis } };
            return { ok: true };
          }
` + t6.join("\n") + `
          return (async () => {
            await zugriffZeileAktualisieren();
            const p = $("leiste-zugriff");
            return JSON.stringify({
              sichtbar: !p.hidden,
              text: $("leiste-zugriff-text").textContent,
              gefragt,
            });
          })();`);
        return JSON.parse(await f(leiste, tabUrl, key, hatRecht, basis));
      } finally { w.close(); }
    };

    const JIRA = "https://jira.test";
    // 1) DER GEMELDETE FALL: Leiste offen, Tab-Adresse NICHT lesbar.
    {
      const r = await zeigeBei(true, "", "", false, JIRA);
      check(r.sichtbar === true,
            "ohne lesbare Tab-Adresse ist die Zugriffszeile SICHTBAR");
      check(r.gefragt[0] === JIRA + "/*",
            "und fragt nach dem Jira-Server, nicht nach irgendetwas",
            r.gefragt.join(","));
      check(/nicht lesen/.test(r.text) && /kein Ticket/.test(r.text),
            "der Text sagt, dass deshalb kein Ticket erkannt wird", r.text);
    }
    // 2) Recht schon da -> keine Aufforderung.
    {
      const r = await zeigeBei(true, "", "", true, JIRA);
      check(r.sichtbar === false, "mit vorhandenem Recht bleibt sie aus");
    }
    // 3) Ticket erkannt -> die Herkunft des TABS, nicht die aus health.
    {
      const r = await zeigeBei(true, "https://jira-echt.test/browse/A-1", "A-1",
                               false, JIRA);
      check(r.gefragt[0] === "https://jira-echt.test/*",
            "bei erkanntem Ticket gilt die Herkunft des Tabs", r.gefragt.join(","));
    }
    /* 4) KEIN erkanntes Ticket, aber eine lesbare fremde Adresse: es wird
     *    NICHT nach dem fremden Host gefragt. Sonst bekaeme jemand, der die
     *    Leiste im Intranet oeffnet, eine Abfrage fuer das Intranet - die ihm
     *    nichts nuetzt und die er zu Recht ablehnt. */
    {
      const r = await zeigeBei(true, "https://intranet.test/start", "", false, JIRA);
      check(r.gefragt[0] === JIRA + "/*",
            "auf einem fremden Tab wird trotzdem nach Jira gefragt",
            r.gefragt.join(","));
    }
    // 5) Im Popup ist die Zeile immer aus - dort traegt `activeTab`.
    {
      const r = await zeigeBei(false, "", "", false, JIRA);
      check(r.sichtbar === false, "im Popup bleibt sie aus");
      check(r.gefragt.length === 0, "und es wird gar nicht erst gefragt");
    }
    // 6) Ohne Auskunft vom Server wird NICHTS geraten.
    {
      const r = await zeigeBei(true, "", "", false, "");
      check(r.sichtbar === false,
            "ohne bekannte Jira-Adresse bleibt sie aus statt zu raten");
    }
  }

  /* Nach dem Erteilen muss die Lage NEU ERMITTELT werden - der Tab ist jetzt
   * lesbar und traegt womoeglich zum ersten Mal eine Ticketnummer. */
  {
    const h = (POPUP_JS.match(
      /\$\("btn-leiste-zugriff"\)\.addEventListener\([\s\S]*?\n\}\);/) || [""])[0];
    check(/tabErmitteln\(\)/.test(h) && /ticketLageAnwenden/.test(h),
          "nach dem Erteilen wird der Tab neu ermittelt, nicht nur neu gezeichnet");
  }

  // Der Server muss die Jira-Adresse ueberhaupt herausgeben.
  {
    const m = MAIN.match(/def _jira_basis_url[\s\S]*?\n\n\n/);
    check(!!m, "main.py hat _jira_basis_url()");
    check(!!m && /https:\/\//.test(m[0]) && /return ""/.test(m[0]),
          "sie nimmt nur https und gibt sonst nichts heraus");
    check(/"jira_basis": _jira_basis_url\(user\)/.test(MAIN),
          "und health liefert sie mit");
  }

  check(/id="btn-leiste-zugriff"/.test(POPUP_HTML),
        "es gibt einen eigenen Knopf fuer die Abfrage");
  {
    /* Der Knopf ist Absicht: `permissions.request` verlangt eine
     * Benutzergeste, und aus einem Fehlerzweig heraus (nach await) lehnt
     * Chrome die Abfrage ab. */
    const h = (POPUP_JS.match(
      /\$\("btn-leiste-zugriff"\)\.addEventListener\([\s\S]*?\n\}\);/) || [null])[0];
    check(!!h && /permissions\.request/.test(h),
          "und er erfragt das Recht wirklich");
  }

  // ── g) Der Umschalter im Fenster ────────────────────────────────────────
  check(/id="f-ansicht"/.test(POPUP_HTML), "das Fenster hat den Umschalter");
  /* Er steht AUSSERHALB von Anmeldung und Arbeitsbereich: wer in der Leiste
   * steht und zurueck will, muss das auch ohne Konto koennen. */
  {
    const login = POPUP_HTML.indexOf('id="bereich-login"');
    const arbeitEnde = POPUP_HTML.indexOf('id="meldung"');
    const schalter = POPUP_HTML.indexOf('id="ansicht-zeile"');
    check(schalter > arbeitEnde && schalter > login,
          "und zwar ausserhalb beider Bereiche");
  }
  check(/ansichtZeigen\(z\.ansicht, z\.leiste_moeglich\)/.test(POPUP_JS),
        "start() belegt ihn aus dem Zustand des Hintergrunds");
  {
    /* ⚠ UMGEDREHT AM 2026-08-30. Hier stand „kennt der Browser keine Leiste,
     * bleibt der Schalter verborgen". Die Meldung „keine Moeglichkeit die
     * Seitenleiste auszuwaehlen" liess sich damit von aussen nicht deuten:
     * fehlt der Schalter, wurde er ausgeblendet, oder liegt er nur ausserhalb
     * des Sichtfensters? Ein unsichtbares Bedienelement ist unerklaerbar. */
    const az = schneidePopup("ansichtZeigen");
    check(!!az && /zeile\.hidden = false;/.test(az) && !/hidden = true/.test(az),
          "die Ansichts-Zeile bleibt IMMER sichtbar");
    /* ⚠ UND SIE WIRD NICHT GESPERRT. Die Faehigkeitspruefung war eine
     * Vermutung und lag falsch (sie fragte `api.sidePanel`, das es in Chrome
     * nicht gibt) - sie hat eine funktionierende Funktion blockiert. Ein
     * faelschlich gesperrter Schalter macht das Feature unerreichbar, ein
     * faelschlich freigegebener kostet einen Klick, der nichts tut. */
    check(!!az && /kasten\.disabled = false/.test(az),
          "und wird NIE gesperrt - die Faehigkeitspruefung ist keine Schranke");
    check(!!az && /ab 114/.test(az),
          "der Hinweis nennt die Voraussetzung trotzdem");
  }
  /* ⚠ REIHENFOLGE: erst absenden, dann oeffnen. Nach einem `await` fehlt die
   * Benutzergeste fuer `sidePanel.open`; und ein Oeffnen VOR dem Absenden
   * koennte das Popup toeten, bevor die Einstellung ueberhaupt unterwegs ist.
   * Gemessen an den Positionen, nicht am Vorkommen. */
  {
    const h = (POPUP_JS.match(
      /\$\("f-ansicht"\)\.addEventListener\([\s\S]*?\n\}\);/) || [null])[0];
    check(!!h, "der Umschalter ist verdrahtet");
    if (h) {
      const senden = h.indexOf('frage({ art: "ansicht"');
      const oeffnen = h.indexOf("leisteOeffnen()");
      check(senden > -1 && oeffnen > -1 && senden < oeffnen,
            "erst absenden, dann oeffnen", senden + " / " + oeffnen);
      /* ⚠ UND ZWAR ABGEWARTET. Hier stand die Gegenregel ("OHNE await, sonst
       * ist die Benutzergeste verbraucht") - sie war die Ursache der Meldung
       * "ich kann die Seitenleiste nur ueber die plugin Steuerung oeffnen":
       * Chrome zerstoert das Popup, sobald die Leiste aufgeht, die Nachricht
       * war da noch unterwegs und die Einstellung wurde nie gespeichert. Der
       * naechste Klick auf das Symbol oeffnete wieder das Popup.
       * Eine nicht gespeicherte Einstellung macht den Schalter kaputt, eine
       * verlorene Benutzergeste kostet einen Klick - und die Meldung sagt
       * dann, welchen. */
      check(/await frage\(\{ art: "ansicht"/.test(h),
            "die Einstellung wird ABGEWARTET, bevor die Leiste aufgeht");
      check(/Symbol/.test(h),
            "und misslingt das Oeffnen, nennt die Meldung den Weg");
    }
    /* ── DAS POPUP SCHLIESST SICH NICHT VON SELBST ────────────────────────
     * Gemeldet 2026-08-30: „nach dem Aktivieren der Seitenleiste bleibt das
     * popup noch sichtbar" - man sieht beide nebeneinander. Ich hatte bis
     * dahin das GEGENTEIL angenommen und sogar die Reihenfolge des Speicherns
     * damit begruendet. Gemessen im Betrieb: es bleibt stehen.
     * AUSGEFUEHRT geprueft, mit `window` als Attrappe. */
    {
      const rumpf = (POPUP_JS.match(
        /\$\("f-ansicht"\)\.addEventListener\("change", async \(ereignis\) => \{([\s\S]*?)\n\}\);/)
        || [])[1];
      check(!!rumpf, "der Umschalter-Rumpf laesst sich schneiden");
      const lauf = async (imLeiste, gehtAuf, anhaken) => {
        const spur = [];
        const fn = new Function(
          "ereignis", "window", "frage", "ansichtZeigen", "melde",
          "leisteOeffnen", "_leiste", "_standAlt",
          "return (async () => {" + rumpf + "\n})();");
        await fn(
          { target: { checked: anhaken } },
          { close: () => spur.push("zu") },
          async (n) => { spur.push("gespeichert:" + n.wert);
                         return { ok: true, wert: n.wert, leiste_moeglich: true }; },
          () => {},
          (t) => { if (t) spur.push("meldung"); },
          async () => { spur.push("geoeffnet"); return gehtAuf; },
          imLeiste, false);
        return spur;
      };

      // 1) Aus dem POPUP heraus einschalten: speichern, oeffnen, schliessen.
      {
        const r = await lauf(false, true, true);
        check(r.join(",") === "gespeichert:leiste,geoeffnet,zu",
              "aus dem Popup: erst speichern, dann oeffnen, dann schliessen",
              r.join(","));
      }
      /* 2) ⚠ GEHT DIE LEISTE NICHT AUF, DARF DAS POPUP NICHT ZUGEHEN - sonst
       *    verschwindet die Meldung, die gerade erklaert, was zu tun ist. */
      {
        const r = await lauf(false, false, true);
        check(r.indexOf("zu") === -1,
              "misslingt das Oeffnen, bleibt das Popup stehen", r.join(","));
        check(r.indexOf("meldung") > -1, "und sagt, was zu tun ist");
      }
      /* 3) ⚠ IN DER LEISTE NIEMALS SCHLIESSEN - `window.close()` wuerde genau
       *    die Leiste schliessen, die der Benutzer eingeschaltet hat. */
      {
        const r = await lauf(true, true, true);
        check(r.indexOf("zu") === -1,
              "in der Leiste wird NICHT geschlossen", r.join(","));
      }
      // 4) Zurueck auf Popup: nur speichern, nichts oeffnen, nichts schliessen.
      {
        const r = await lauf(true, true, false);
        check(r.join(",") === "gespeichert:popup,meldung",
              "Zurueckstellen speichert und meldet, mehr nicht", r.join(","));
      }
    }
    /* Und `window.close()` steht sonst NIRGENDS - eine zweite Stelle koennte
     * die Leiste treffen. Ohne Kommentare, sonst zaehlt die Begruendung mit. */
    check((ohneKommentare(POPUP_JS).match(/window\.close\(\)/g) || []).length === 1,
          "window.close() steht genau EINMAL in popup.js");

    const lo = ohneKommentare(schneidePopup("leisteOeffnen") || "");
    /* ⚠ JEDER Zweig muss warten, nicht irgendeiner. Die erste Fassung dieser
     * Pruefung suchte `await api.(sidePanel|sidebarAction)` - mit zwei Zweigen
     * blieb sie gruen, obwohl in einem das `await` fehlte, und die Gegenprobe
     * biss nicht. Geprueft wird jetzt die Eigenschaft: KEIN `open(` ohne
     * unmittelbar davorstehendes `await`.
     * Ohne Kommentare, sonst zaehlen die Begruendungen mit. */
    check(/zweig\("sidebarAction"/.test(lo) && /zweig\("sidePanel"/.test(lo),
          "leisteOeffnen sucht beide APIs an BEIDEN Wurzeln");
    const offeneAufrufe = lo.match(/(\w+\s+)?\w+\.open\(/g) || [];
    check(offeneAufrufe.length >= 2,
          "leisteOeffnen() bedient beide Welten", String(offeneAufrufe.length));
    check(offeneAufrufe.every((a) => /^await\s/.test(a)),
          "und wartet in JEDEM Zweig das Ergebnis ab - sonst waere die Meldung geraten",
          offeneAufrufe.join(" | "));
    check(!!lo && /return false;/.test(lo),
          "und meldet einen Fehlschlag zurueck, statt ihn zu verschlucken");

  }

  /* ── i) DIE WARTEMELDUNG MUSS WIEDER VERSCHWINDEN ──────────────────────
   *
   * Gemeldet 2026-08-30: „'Fasse das Ticket zusammen...' wird dauerhaft
   * angezeigt". Ursache war NICHT ein haengender Lauf: `melde("")` setzte nur
   * `hidden`, und `.meldung.arbeitet { display: flex }` UEBERSTIMMT das
   * `hidden`-Attribut. Im echten Chrome gemessen: hidden=true, display=flex,
   * offsetHeight>0, drehender Kreis noch da.
   * Die Folge war schlimmer als der Schoenheitsfehler: der Kasten machte das
   * Fenster hoeher und schob den Ansichts-Umschalter aus dem 600 px hohen
   * Popup - „keine Moeglichkeit die Seitenleiste auszuwaehlen". */
  {
    const regel = /\.meldung\[hidden\]\s*\{([^}]*)\}/.exec(POPUP_CSS);
    check(!!regel && /display:\s*none/.test(regel[1]),
          "`.meldung[hidden]` setzt display:none - das Attribut muss gewinnen");
    /* Die Regel muss NACH der Klasse stehen: gleiche Spezifitaet (0,2,0 gegen
     * 0,2,0), da entscheidet die Reihenfolge. */
    check(POPUP_CSS.indexOf(".meldung[hidden]")
          > POPUP_CSS.lastIndexOf(".meldung.arbeitet"),
          "und steht NACH .meldung.arbeitet - sonst verliert sie");

    // Und der Zustand wird geraeumt, nicht nur versteckt.
    const m = schneidePopup("melde");
    check(!!m && /textContent = ""/.test(m) && /classList\.remove\("arbeitet"\)/.test(m),
          "melde(\"\") raeumt Text und Klasse mit ab");

    // AUSGEFUEHRT: erst eine Wartemeldung, dann leeren.
    {
      const dom = new JSDOM(POPUP_HTML, { url: "https://x.test/",
                                          runScripts: "outside-only" });
      const w = dom.window;
      try {
        const r = JSON.parse(new w.Function(`
          const $ = (id) => document.getElementById(id);
          const el = { meldung: $("meldung") };
          let _marke = "Marke";
` + m + `
          melde("Fasse das Ticket zusammen …", true);
          const waehrend = { sichtbar: !el.meldung.hidden,
                             dreher: !!el.meldung.querySelector(".dreher") };
          melde("");
          return JSON.stringify({ waehrend, danach: {
            hidden: el.meldung.hidden,
            text: el.meldung.textContent,
            arbeitet: el.meldung.classList.contains("arbeitet"),
            dreher: !!el.meldung.querySelector(".dreher"),
          }});`)());
        check(r.waehrend.sichtbar && r.waehrend.dreher,
              "waehrend des Laufs steht die Meldung mit drehendem Kreis da");
        check(r.danach.hidden === true, "danach ist sie versteckt");
        check(r.danach.text === "", "der Text ist weg", r.danach.text);
        check(r.danach.arbeitet === false, "die Klasse `arbeitet` ist weg");
        check(r.danach.dreher === false, "und der Kreis ist weg");
      } finally { w.close(); }
    }
  }

  /* ── j) DER UMSCHALTER DARF NICHT AUS DEM BILD WANDERN ─────────────────
   * Ein Popup ist auf 600 px geklemmt; bei langem Ergebnis lag die Oberkante
   * der Zeile gemessen bei y=703. Sie ist dann da und trotzdem unauffindbar. */
  {
    const r = /\.ansicht-fuss\s*\{([^}]*)\}/.exec(POPUP_CSS);
    check(!!r && /position:\s*sticky/.test(r[1]),
          "der Ansichts-Fuss klebt am unteren Rand", (r || ["", ""])[1].trim());
    /* DECKENDE Flaeche ist Pflicht - halbtransparent schiene der Text
     * darunter durch (Projektregel). */
    check(!!r && /background:\s*var\(--grund\)/.test(r[1]),
          "und traegt eine deckende Flaeche");
  }

  /* ── k) HERSTELLEREIGENE APIs AN BEIDEN WURZELN ────────────────────────
   *
   * ⚠ DER FEHLER, DER DREI RUNDEN GEKOSTET HAT. `api` ist `browser ?? chrome`.
   * Chrome 152 definiert selbst ein `browser`-Objekt - `sidePanel` steht dort
   * NICHT drin, weil es eine Chrome-eigene API ist. `api.sidePanel` war damit
   * undefined, obwohl `chrome.sidePanel` existiert: die ganze Panel-Steuerung
   * war ein stiller No-op, und die Faehigkeitspruefung meldete "dieser Browser
   * kann das nicht" auf einem Browser, der es kann.
   * AUSGEFUEHRT geprueft - eine Quelltext-Pruefung haette denselben Denkfehler
   * nur wiederholt. */
  {
    const schneideAus = (quelle, name) => (quelle.match(new RegExp(
      "(?:async )?function " + name + "\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}")) || [null])[0];
    /* ⚠ DER HELFER STEHT IN BEIDEN DATEIEN - und beide muessen geprueft
     * werden. Eine Gegenprobe, die nur background.js verbog, blieb sonst
     * gruen, weil der Lauf die Fassung aus popup.js ausfuehrte.
     * Dazu eine DRIFT-SCHRANKE: zwei Fassungen derselben Funktion laufen
     * auseinander (Register; im Projekt zuletzt bei `kanonisch()` der Lizenz).
     * Geteilt werden kann der Code nicht: popup.js ist ein Modul, background.js
     * laeuft in Firefox als klassisches Skript. */
    const fassungen = [["popup.js", POPUP_JS], ["background.js", BG]];
    const geschnitten = fassungen.map(([n, q]) =>
      [n, schneideAus(q, "_wurzeln"), schneideAus(q, "zweig")]);
    for (const [n, w_, z_] of geschnitten) {
      check(!!w_ && !!z_, n + " hat zweig() und _wurzeln()");
    }
    check(geschnitten[0][1] === geschnitten[1][1]
          && geschnitten[0][2] === geschnitten[1][2],
          "beide Fassungen sind ZEICHENGLEICH - sonst laufen sie auseinander");

    const sucheIn = (w, z) => (C, B, name, methode) => new Function(
      "chrome", "browser", "name", "methode",
      w + "\n" + z + "\nreturn zweig(name, methode) ? 'gefunden' : 'fehlt';"
    )(C, B, name, methode);
    // Gemessen wird gegen BEIDE Fassungen; `suche` prueft sie gemeinsam und
    // meldet nur "gefunden", wenn beide es sagen.
    const suche = (C, B, name, methode) => {
      const e = geschnitten.map(([, w_, z_]) => sucheIn(w_, z_)(C, B, name, methode));
      return (e[0] === e[1]) ? e[0] : ("uneinig: " + e.join("/"));
    };

    const MIT = { sidePanel: { setOptions() {}, open() {} } };
    const OHNE = { runtime: {} };

    check(suche(MIT, undefined, "sidePanel", "setOptions") === "gefunden",
          "klassisches Chrome: sidePanel wird gefunden");
    /* DER GEMELDETE FALL. */
    check(suche(MIT, OHNE, "sidePanel", "setOptions") === "gefunden",
          "Chrome 152 mit `browser` OHNE sidePanel: wird trotzdem gefunden");
    check(suche(undefined, { sidebarAction: { setPanel() {} } },
                "sidebarAction", "setPanel") === "gefunden",
          "Firefox: sidebarAction wird gefunden");
    check(suche(OHNE, OHNE, "sidePanel", "setOptions") === "fehlt",
          "gibt es sie nirgends, wird nichts erfunden");
    /* Ein Zweig OHNE die gesuchte Methode zaehlt nicht - sonst laeuft der
     * Aufruf gleich darauf in einen TypeError. */
    check(suche({ sidePanel: {} }, undefined, "sidePanel", "setOptions") === "fehlt",
          "ein Zweig ohne die Methode zaehlt nicht");
    check(suche(undefined, undefined, "sidePanel", "setOptions") === "fehlt",
          "ganz ohne Wurzeln wirft es nicht");
  }

  /* Und die Faehigkeit wird aus dem MANIFEST gelesen, nicht nur aus der API -
   * das ist die verlaesslichste Auskunft: hat der Browser die Erweiterung mit
   * dem Leisten-Schluessel geladen, gibt es die Leiste. */
  {
    const lm = ohneKommentare((BG.match(
      /function leisteMoeglich\(\)[\s\S]*?\n\}/) || [""])[0]);
    check(/getManifest/.test(lm) && /side_panel/.test(lm),
          "leisteMoeglich fragt zuerst das Manifest");
    check(/zweig\(/.test(lm),
          "und sucht die API an beiden Wurzeln");
    check(!/api\.sidePanel/.test(lm),
          "aber NICHT mehr ueber `api` - das ist browser ?? chrome");
  }
  /* Keine Stelle im Code darf noch ueber `api` an die herstellereigenen APIs
   * gehen - GEPRUEFT ALS REGEL, damit auch eine kuenftige auffaellt. */
  for (const [name, quelle] of [["background.js", BG], ["popup.js", POPUP_JS]]) {
    const o = ohneKommentare(quelle);
    check(!/api\.sidePanel/.test(o) && !/api\.sidebarAction/.test(o),
          name + " greift nirgends ueber `api` auf sidePanel/sidebarAction zu");
  }

  /* ── l) HALB AKTUALISIERT: neues Fenster, alter Hintergrund ────────────
   *
   * Gemeldet 2026-08-30: Klick auf den Ansichts-Schalter antwortete
   * „Unbekannte Anfrage." – der `default`-Zweig des Hintergrunds. Der Code war
   * in Ordnung; es antwortete eine AELTERE Fassung.
   * URSACHE (Chrome-Bauart, nicht Fehler): die Popup-SEITE liest Chrome bei
   * jedem Oeffnen frisch von der Platte, den **Service-Worker** behaelt es im
   * Speicher. Wer aktualisiert, ohne in chrome://extensions neu zu laden, hat
   * genau diesen Zustand – und alle Symptome sehen aus wie Programmierfehler.
   * Der Abgleich macht daraus eine Anweisung. */
  {
    const inPopup = (POPUP_JS.match(/const STAND = (\d+);/) || [])[1];
    const inBg = (BG.match(/const STAND = (\d+);/) || [])[1];
    check(!!inPopup && !!inBg, "beide Dateien tragen einen STAND",
          inPopup + " / " + inBg);
    check(inPopup === inBg, "und er ist derselbe - sonst warnt es dauernd",
          inPopup + " / " + inBg);
    check(/stand: STAND/.test(BG), "der Hintergrund schickt ihn im Zustand mit");

    /* Der `default`-Zweig muss den WEG nennen. „Unbekannte Anfrage." war
     * richtig und trotzdem wertlos. */
    const dflt = (BG.match(/default:[\s\S]*?\}\);/) || [""])[0];
    check(/chrome:\/\/extensions/.test(dflt) && /aeltere Fassung/.test(dflt),
          "und der default-Zweig nennt den Weg statt nur 'unbekannt'",
          dflt.slice(0, 60));

  }

  // ── h) CSS ──────────────────────────────────────────────────────────────
  /* Im Popup bestimmt der Inhalt die Breite, in der Leiste der Browser. Eine
   * feste Breite laeuft dort waagerecht ueber. */
  {
    const r = (POPUP_CSS.match(/html\.leiste body \{([\s\S]*?)\}/) || ["", ""])[1];
    check(/width:\s*auto/.test(r),
          "html.leiste body loest die feste Breite auf", r.trim());
    check(/body \{[\s\S]*?width:\s*380px/.test(POPUP_CSS),
          "das Popup behaelt seine 380 px");
  }
}

// ═══════════════════════════════════════════════════════════════════════════
section("11) Ohne Ticket ist alles gesperrt (Vorgabe 2026-08-30)");
// ═══════════════════════════════════════════════════════════════════════════
/* "alle buttons des jira browser plugins muessen deaktiviert sein, wenn kein
 * Jira Ticket gefunden wird". Vorher waren nur die drei Auswertungsknoepfe
 * abgesichert - und zwar erst IM Handler, mit einer Meldung nach dem Klick.
 * Ein Knopf, der sich druecken laesst und dann sagt, dass er nicht kann, ist
 * eine schlechtere Auskunft als ein grauer Knopf. */
{
  check(/id="ticket-anzeige"/.test(POPUP_HTML), "es gibt das Ticket-Infofeld");

  const ta = schneidePopup("ticketAnzeigen");
  const ka = schneidePopup("knoepfeAktualisieren");
  check(!!ta, "popup.js hat ticketAnzeigen()");
  check(!!ka, "popup.js hat knoepfeAktualisieren()");

  /* Anzeige und Sperre haben dieselbe Ursache und werden deshalb in EINER
   * Funktion gesetzt - sonst waere der Zustand denkbar, in dem die Knoepfe
   * grau sind und im Kopf trotzdem eine Ticketnummer steht. */
  check(!!ta && /knoepfeAktualisieren\(\)/.test(ta),
        "die Anzeige zieht die Sperre nach");
  check(/ticketAnzeigen\(\)/.test(
          schneidePopup("tabErmitteln") || ""),
        "und tabErmitteln setzt sie bei jeder Tab-Ermittlung");

  /* AUSGEFUEHRT gegen die ECHTE popup.html: nur so faellt auf, wenn ein Knopf
   * im Markup dazukommt und keiner daran denkt. */
  const lageBei = (key, laeuft, vorherSperren) => {
    const dom = new JSDOM(POPUP_HTML, { url: "https://x.test/",
                                        runScripts: "outside-only" });
    const w = dom.window;
    try {
      const f = new w.Function("key", "laeuft", "vorherSperren", `
        const $ = (id) => document.getElementById(id);
        const el = { ticket: $("ticket-anzeige") };
        let _key = key, _laeuft = false;
` + [schneidePopup("sperre"), ka, ta].join("\n") + `
        if (vorherSperren) sperre(true);
        _laeuft = laeuft;
        ticketAnzeigen();
        if (vorherSperren && !laeuft) sperre(false);
        const zustand = {};
        for (const b of document.querySelectorAll("button")) {
          zustand[b.id || b.className] = !!b.disabled;
        }
        return JSON.stringify({
          text: el.ticket.textContent,
          leer: el.ticket.classList.contains("leer"),
          zustand,
        });`);
      return JSON.parse(f(key, laeuft, vorherSperren));
    } finally { w.close(); }
  };

  // ── a) Das Infofeld sagt es im Klartext ────────────────────────────────
  {
    const r = lageBei("", false, false);
    check(r.text === "Kein Ticket gefunden",
          'ohne Ticket steht "Kein Ticket gefunden" im Feld', r.text);
    check(r.leer === true, "und es ist als Zustandsmeldung gekennzeichnet");
    /* ⚠ NICHT UEBER DIE FARBE: `.ticket` ist ohnehin schon gedaempft, eine
     * Faerbung waere ein No-op - so stand es im ersten Anlauf da. Getrennt
     * wird ueber die Schrift: Kennung in Monospace, Satz in Textschrift. */
    const regelLeer = (POPUP_CSS.match(/\.ticket\.leer \{([^}]*)\}/) || ["", ""])[1];
    const regelTicket = (POPUP_CSS.match(/\.ticket \{[^}]*monospace[^}]*\}/) || [""])[0];
    check(/monospace/.test(regelTicket),
          "eine Ticketnummer steht in Monospace");
    check(/font-family/.test(regelLeer) && !/color/.test(regelLeer),
          "der Leer-Zustand hebt das auf und faerbt NICHT nur um",
          regelLeer.trim());
  }
  {
    const r = lageBei("NXKS-17559", false, false);
    check(r.text === "NXKS-17559", "mit Ticket steht die Nummer da", r.text);
    check(r.leer === false, "ohne die Zustands-Kennzeichnung");
  }

  // ── b) Ohne Ticket ist JEDER Knopf gesperrt - bis auf die Ausnahmen ────
  /* Die Ausnahmen sind im Markup markiert (`data-ohne-ticket`), nicht hier
   * aufgezaehlt: eine zweite Liste im Test liefe beim naechsten Knopf
   * auseinander. Geprueft wird die REGEL.
   * ⚠ UEBER DEN DOM, NICHT PER REGEX (2026-08-31): das Attribut darf an einem
   * CONTAINER stehen und gilt dann fuer alles darin. Eine Regex auf
   * `<button ... data-ohne-ticket>` haette die Knoepfe der Vorlagen-Box
   * uebersehen und faelschlich Alarm geschlagen. */
  const ausnahme = (() => {
    const dom = new JSDOM(POPUP_HTML, { url: "https://x.test/" });
    try {
      return new Set(Array.from(dom.window.document.querySelectorAll("button"))
        .filter((b) => b.closest("[data-ohne-ticket]"))
        .map((b) => b.id).filter(Boolean));
    } finally { dom.window.close(); }
  })();
  check(ausnahme.size >= 6,
        "im Markup sind die Ausnahmen gekennzeichnet", [...ausnahme].join(", "));

  /* DIE SECHS, DIE DRINSTEHEN MUESSEN - und jede aus einem eigenen Grund.
   * Sie sind hier namentlich genannt, weil ihr Fehlen ein Einbahnstrassen-
   * Zustand waere: nicht hineinkommen, nicht hinaus, Dialog nicht schliessbar
   * - oder eine Verwaltung, die ein Ticket verlangt, das sie nie benutzt. */
  for (const [id, grund] of [
    ["btn-anmelden", "sonst kaeme man von einem fremden Tab aus nie hinein"],
    ["btn-abmelden", "sonst nie hinaus"],
    ["btn-vorlagen-zu", "ein Dialog, den man nicht wegbekommt, ist eine Falle"],
    ["jn-nein", "dito fuer die Rueckfrage beim Einfuegen"],
    ["btn-vorlagen", "Vorlagen verwalten braucht kein Ticket (gemeldet 2026-08-31)"],
    ["btn-vorl-speichern", "sonst laesst sich die geoeffnete Box nicht benutzen"],
  ]) {
    check(ausnahme.has(id), id + " bleibt bedienbar - " + grund);
  }

  /* Und die Ausnahme haengt am CONTAINER, nicht an jedem Knopf: nur so sind
   * die erst beim Zeichnen entstehenden Zeilen-Knoepfe erfasst. */
  check(/<div id="vorlagen-box" data-ohne-ticket/.test(POPUP_HTML),
        "die Vorlagen-Box traegt die Ausnahme als ganzer Bereich");
  check(/b\.closest\("\[data-ohne-ticket\]"\)/.test(ka || ""),
        "und knoepfeAktualisieren sucht sie ueber die Vorfahren");

  {
    const r = lageBei("", false, false);
    const gesperrt = Object.entries(r.zustand).filter(([, d]) => d).map(([i]) => i);
    const offen = Object.entries(r.zustand).filter(([, d]) => !d).map(([i]) => i);
    check(offen.every((id) => ausnahme.has(id)),
          "ohne Ticket ist NUR noch offen, was ausdruecklich ausgenommen ist",
          offen.join(", "));
    /* ⚠ KEINE FESTE ZAHL mehr (kostete beim Ausnehmen der Vorlagen-Box einen
     * Fehlalarm): geprueft wird die EIGENSCHAFT - jeder nicht ausgenommene
     * Knopf ist gesperrt, und es ist ueberhaupt einer dabei. Eine Untergrenze
     * meldet sonst einen Fehler, sobald eine Ausnahme dazukommt. */
    check(gesperrt.every((id) => !ausnahme.has(id)) && gesperrt.length > 0,
          "alles uebrige ist gesperrt", gesperrt.length + ": " + gesperrt.join(", "));
    check([...ausnahme].every((id) => r.zustand[id] !== true),
          "und keine einzige Ausnahme ist gesperrt",
          [...ausnahme].filter((id) => r.zustand[id] === true).join(", "));
    check(r.zustand["btn-zusammenfassung"] === true &&
          r.zustand["btn-antwort"] === true &&
          r.zustand["btn-ueberarbeiten"] === true,
          "die drei Auswertungsknoepfe sind gesperrt");
    check(r.zustand["btn-einfuegen"] === true,
          "und Einfuegen ebenfalls - ohne Ticket gibt es kein Kommentarfeld");
    check(r.zustand["btn-anmelden"] === false,
          "Anmelden bleibt bedienbar");
    check(r.zustand["btn-abmelden"] === false,
          "Abmelden bleibt bedienbar");
  }

  // ── c) Mit Ticket ist alles wieder frei ────────────────────────────────
  {
    const r = lageBei("ABC-1", false, false);
    check(Object.values(r.zustand).every((d) => d === false),
          "mit Ticket ist kein Knopf gesperrt",
          Object.entries(r.zustand).filter(([, d]) => d).map(([i]) => i).join(", "));
  }

  // ── d) Zusammenspiel mit der Lauf-Sperre ───────────────────────────────
  /* ⚠ `sperre(false)` DARF NICHT BLIND ALLES FREIGEBEN. Bis 2026-08-30 stand
   * dort `b.disabled = an` fuer jeden Knopf - das Ende eines Laufs haette die
   * Ticket-Sperre wieder aufgehoben, und zwar genau dann, wenn der Benutzer
   * waehrenddessen auf einen fremden Tab gewechselt ist. */
  {
    const r = lageBei("", false, true);   // sperre(true) ... sperre(false)
    check(r.zustand["btn-zusammenfassung"] === true,
          "nach einem Lauf bleibt die Ticket-Sperre bestehen");
    check(r.zustand["btn-abmelden"] === false,
          "und die Ausnahme ist wieder frei");
  }
  {
    // Waehrend eines Laufs entscheidet `sperre` allein - ein Tab-Wechsel
    // mitten in der Auswertung darf die Knoepfe nicht freigeben.
    const r = lageBei("ABC-1", true, true);
    check(Object.values(r.zustand).every((d) => d === true),
          "waehrend eines Laufs bleibt ALLES gesperrt, auch die Ausnahmen",
          Object.entries(r.zustand).filter(([, d]) => !d).map(([i]) => i).join(", "));
  }
  check(!!ka && /if \(_laeuft\) return;/.test(ka),
        "knoepfeAktualisieren haelt sich waehrend eines Laufs heraus");

  // ── e) Die Schranke im Handler BLEIBT ──────────────────────────────────
  /* Ein gesperrter Knopf ist Oberflaeche, keine Garantie: `_key` kann sich
   * zwischen Zeichnen und Klick aendern (Tab-Wechsel in der Leiste), und ein
   * `disabled` laesst sich aus den Entwicklerwerkzeugen entfernen. Die
   * Pruefung im Handler ist die eigentliche Schranke. */
  for (const id of ["btn-zusammenfassung", "btn-antwort", "btn-ueberarbeiten"]) {
    const h = (POPUP_JS.match(new RegExp(
      '\\$\\("' + id + '"\\)\\.addEventListener\\([\\s\\S]*?\\n\\}\\);')) || [""])[0];
    const auswerten = /auswerten\("(zusammenfassung|antwort)"\)/.test(h);
    check(auswerten || /if \(!_key\)/.test(h),
          id + " prueft weiterhin selbst auf ein Ticket");
  }
  check(/async function auswerten[\s\S]{0,200}if \(!_key\)/.test(POPUP_JS),
        "auswerten() bricht ohne Ticket ab - die Schranke hinter der Oberflaeche");
}

/* ── 14) AUTOMATIK BEI NEUEM TICKET ────────────────────────────────────────
 *
 * Vorgabe des Nutzers 2026-08-31: eine der beiden Auswertungen soll bei einem
 * NEUEN Ticket von selbst starten koennen.
 *
 * DIE ZUSAGE, DIE HIER HAENGT, IST "HOECHSTENS EINMAL JE TICKET" – und sie ist
 * keine Sparmassnahme, sondern zwei verschiedene Schaeden:
 *   a) ein automatischer Lauf ueber ein bereits BEARBEITETES Ergebnis wirft die
 *      Arbeit des Benutzers weg, ohne dass er etwas gedrueckt hat;
 *   b) ohne Ringspeicher feuert jeder Tab-Wechsel zurueck auf ein schon
 *      gesehenes Ticket einen weiteren Modellaufruf.
 * Beide Schranken werden deshalb AUSGEFUEHRT geprueft, nicht am Quelltext
 * abgelesen.
 */
section("14) Automatik bei neuem Ticket");

/* Schnitt aus dem HINTERGRUND. Bis hierher gab es nur `schneidePopup`; die
 * Entscheidung "darf dieses Ticket automatisch laufen" liegt aber bewusst
 * dort, weil Pruefen und Vermerken EIN Schritt sein muessen. */
function schneideBg(name) {
  const m = BG.match(new RegExp('(?:async )?function ' + name
                                + '\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}'));
  return m ? m[0] : null;
}

// ── a) Die Umbenennung ───────────────────────────────────────────────────
{
  const knopf = (POPUP_HTML.match(
    /<button[^>]*id="btn-ueberarbeiten"[^>]*>([^<]*)<\/button>/) || ["", ""])[1];
  check(knopf.trim() === "Antwort überarbeiten",
        'der Knopf heisst "Antwort überarbeiten"', knopf);
  check(!/>\s*Überarbeiten\s*</.test(POPUP_HTML),
        "der alte Name steht nirgends mehr im Fenster");
  // Der Hinweis darunter erklaert GENAU diesen Knopf - laeuft er auf den alten
  // Namen, sucht der Benutzer ein Bedienelement, das es nicht mehr gibt.
  const hinweis = (POPUP_HTML.match(
    /id="ueberarb-hinweis"[^>]*>([\s\S]*?)<\/p>/) || ["", ""])[1];
  check(/<b>Antwort überarbeiten<\/b>/.test(hinweis),
        "und der Hinweis darunter nennt ihn beim neuen Namen", hinweis.trim());
}

// ── b) Das Pulldown steht im Arbeitsbereich ──────────────────────────────
{
  const arbeit = (POPUP_HTML.match(
    /<section id="bereich-arbeit"[\s\S]*?<\/section>/) || [""])[0];
  check(/id="f-auto"/.test(arbeit),
        "das Pulldown liegt im Arbeitsbereich (nur nach Anmeldung sichtbar)");

  const sel = (arbeit.match(/<select id="f-auto"[\s\S]*?<\/select>/) || [""])[0];
  const werte = [...sel.matchAll(/value="([^"]*)"/g)].map((m) => m[1]);
  check(werte.length === 3, "es stehen genau drei Moeglichkeiten zur Wahl",
        werte.join("|"));
  check(werte[0] === "",
        "die erste ist AUS - Vorgabe ist, dass nichts von selbst laeuft");

  /* DRIFT-SCHRANKE ueber drei Dateien. Ein Wert im Markup, den der Hintergrund
   * nicht kennt, wird dort still zu "aus" (autoModus ist fail-closed): der
   * Benutzer stellt etwas ein, es wird gespeichert, und es passiert nie etwas -
   * ohne jede Fehlermeldung. */
  const AUTO_MODI = JSON.parse(
    (BG.match(/const AUTO_MODI = (\[[^\]]*\]);/) || ["", "[]"])[1]
      .replace(/'/g, '"'));
  check(AUTO_MODI.length === 2, "der Hintergrund kennt zwei Modi",
        AUTO_MODI.join("|"));
  check(werte.filter((w) => w).every((w) => AUTO_MODI.indexOf(w) >= 0),
        "jeder Wert im Markup ist einer, den der Hintergrund annimmt",
        werte.join("|") + " gegen " + AUTO_MODI.join("|"));

  /* "Antwort ueberarbeiten" darf NICHT zur Wahl stehen: es braucht einen
   * Entwurf, den der Bearbeiter selbst ins Kommentarfeld geschrieben hat - bei
   * einem gerade geoeffneten Ticket gibt es den per Definition nicht. Der Lauf
   * endete zwangslaeufig mit "kein Text gefunden". */
  check(werte.indexOf("ueberarbeiten") < 0 && AUTO_MODI.indexOf("ueberarbeiten") < 0,
        "'ueberarbeiten' steht NICHT zur Wahl (es braucht einen eigenen Entwurf)");

  /* Bewusst KEIN `data-ohne-ticket` noetig: die Ticket-Sperre greift nur auf
   * <button>. Genau richtig - wer auf einem fremden Tab steht, muss die
   * Automatik trotzdem AUSschalten koennen. Der Test haelt fest, dass es ein
   * <select> bleibt und kein Knopf daraus wird. */
  const ka = schneidePopup("knoepfeAktualisieren") || "";
  check(/querySelectorAll\("button"\)/.test(ka),
        "die Ticket-Sperre fasst nur Knoepfe an - das Pulldown bleibt bedienbar");
}

// ── c) Der Hintergrund entscheidet - AUSGEFUEHRT ─────────────────────────
{
  const teile = ["autoModus", "einstLesen", "einstSchreiben", "autoStart"]
    .map(schneideBg);
  for (let i = 0; i < teile.length; i++) {
    check(!!teile[i],
          "background.js hat " + ["autoModus", "einstLesen", "einstSchreiben",
                                  "autoStart"][i] + "()");
  }
  // Modul-Konstanten: sie stehen in keinem Funktionsrumpf und fallen aus jedem
  // Schnitt heraus - fehlen sie, WIRFT der Lauf statt fehlzuschlagen.
  const konst = [
    (BG.match(/const EINST = "[^"]*";/) || [""])[0],
    (BG.match(/const AUTO_MODI = \[[^\]]*\];/) || [""])[0],
    (BG.match(/const AUTO_MERK_MAX = \d+;/) || [""])[0],
  ];
  check(konst.every((k) => k), "und die drei Modul-Konstanten dazu",
        konst.join(" / "));

  const bgLauf = new Function("start", "rufe", ""
    + konst.join("\n") + "\n"
    + "const ablage = Object.assign({}, start);\n"
    + "const api = { storage: { local: {\n"
    + "  get: async (k) => (ablage[k] === undefined ? {} : { [k]: ablage[k] }),\n"
    + "  set: async (o) => { Object.assign(ablage, o); },\n"
    + "} } };\n"
    + teile.join("\n") + "\n"
    + "return (async () => {\n"
    + "  const spur = [];\n"
    + "  for (const k of rufe) spur.push(await autoStart(k));\n"
    + "  return JSON.stringify({ spur, ablage });\n"
    + "})();");

  const einst = (o) => ({ einstellungen: o });

  // 1) Automatik AUS -> es startet nichts, und es wird nichts vermerkt.
  {
    const r = JSON.parse(await bgLauf(einst({}), ["ABC-1", "ABC-2"]));
    check(r.spur.every((s) => s.starten === false),
          "Vorgabe (kein auto_modus): es startet nichts");
    check(r.spur.every((s) => s.modus === ""), "und der Modus ist leer");
    check(!r.ablage.einstellungen.auto_gelaufen,
          "es wird auch nichts vermerkt - der Ring bleibt unangetastet",
          JSON.stringify(r.ablage.einstellungen));
  }

  // 2) DER KERN: je Ticket genau einmal.
  {
    const r = JSON.parse(await bgLauf(
      einst({ auto_modus: "zusammenfassung" }),
      ["ABC-1", "ABC-1", "ABC-2", "ABC-1"]));
    check(r.spur[0].starten === true, "erstes Ticket: es startet");
    check(r.spur[0].modus === "zusammenfassung", "mit dem eingestellten Modus",
          r.spur[0].modus);
    check(r.spur[1].starten === false,
          "DASSELBE Ticket ein zweites Mal: es startet NICHT mehr");
    check(r.spur[2].starten === true, "ein anderes Ticket startet wieder");
    check(r.spur[3].starten === false,
          "und der Rueckwechsel auf das erste startet nicht erneut "
          + "(genau das waere der Tab-Wechsel-Kreisel)");
    check(r.spur[1].modus === "zusammenfassung",
          "der Modus steht auch dann drin, wenn nicht gestartet wird - "
          + "'aus' und 'schon gelaufen' sind zweierlei");
    check(JSON.stringify(r.ablage.einstellungen.auto_gelaufen)
            === JSON.stringify(["ABC-1", "ABC-2"]),
          "im Ring stehen beide Ticketnummern, jede einmal",
          JSON.stringify(r.ablage.einstellungen.auto_gelaufen));
  }

  // 3) Ohne Ticketnummer passiert nichts (und es landet kein Leerwert im Ring).
  {
    const r = JSON.parse(await bgLauf(einst({ auto_modus: "antwort" }), [""]));
    check(r.spur[0].starten === false, "ohne Ticketnummer startet nichts");
    check(!r.ablage.einstellungen.auto_gelaufen,
          "und der Ring bekommt keinen Leerwert");
  }

  // 4) Ein unbekannter Modus ist AUS, nicht ein dritter Zustand.
  {
    const r = JSON.parse(await bgLauf(
      einst({ auto_modus: "ueberarbeiten" }), ["ABC-1"]));
    check(r.spur[0].modus === "" && r.spur[0].starten === false,
          "ein unbekannter Modus gilt als AUS (fail-closed)",
          JSON.stringify(r.spur[0]));
  }

  // 5) DER RING WAECHST NICHT UNBEGRENZT. Ohne Deckel steht die Ablage nach
  //    einem Jahr voller Ticketnummern - und niemand sieht es.
  {
    const MAX = parseInt((BG.match(/const AUTO_MERK_MAX = (\d+);/) || [])[1], 10);
    const viele = [];
    for (let i = 0; i < MAX + 5; i++) viele.push("T-" + i);
    const r = JSON.parse(await bgLauf(einst({ auto_modus: "antwort" }), viele));
    /* Kein `ring.length` auf einem moeglicherweise fehlenden Wert: eine
     * Pruefung, die WIRFT statt fehlzuschlagen, bricht die Gegenprobe ab und
     * sieht aus wie ein nicht gelaufener Test (Register). */
    const ring = r.ablage.einstellungen.auto_gelaufen || [];
    check(ring.length === MAX, "der Ring ist bei " + MAX + " gedeckelt",
          String(ring.length));
    check(ring[ring.length - 1] === "T-" + (MAX + 4),
          "und behaelt die JUENGSTEN Eintraege", String(ring[ring.length - 1]));
    check(ring.length > 0 && ring.indexOf("T-0") < 0,
          "der aelteste ist herausgefallen");
  }
}

// ── d) Das Fenster: wann es NICHT startet - AUSGEFUEHRT ──────────────────
{
  const { teile, drin } = popupTeile(
    ["autoAktionPruefen", "autoZeigen"],
    ["frage", "auswerten", "melde"]);
  check(drin.has("autoAktionPruefen") && drin.has("autoZeigen"),
        "popup.js hat autoAktionPruefen() und autoZeigen()");

  /* Der Lauf gibt zurueck, WAS an den Hintergrund ging und OB ausgewertet
   * wurde. Beides ist noetig: bei ausgeschalteter Automatik darf nicht einmal
   * gefragt werden (sonst kostet der Normalfall eine Nachricht je
   * Tab-Wechsel). */
  const lauf = async (o) => {
    const dom = new JSDOM(POPUP_HTML, { url: "https://x.test/",
                                        runScripts: "outside-only" });
    const w = dom.window;
    try {
      const f = new w.Function("o", ""
        + "const gesendet = [], gelaufen = [];\n"
        + "const $ = (id) => document.getElementById(id);\n"
        + "const el = { arbeit: $('bereich-arbeit'), meldung: $('meldung') };\n"
        + "el.arbeit.hidden = !!o.abgemeldet;\n"
        + "let _autoModus = '', _key = o.key, _laeuft = !!o.laeuft;\n"
        + "function melde() {}\n"
        + "async function frage(n) {\n"
        + "  gesendet.push(n);\n"
        + "  if (o.wechseltTab) _key = 'ANDERS-9';\n"
        + "  if (o.hintergrundAlt) throw new Error('Diese Anfrage kennt der Hintergrund nicht');\n"
        + "  return { ok: true, modus: o.modus || '', starten: !!o.starten };\n"
        + "}\n"
        + "async function auswerten(m) { gelaufen.push(m); }\n"
        + teile.join("\n") + "\n"
        + "return (async () => {\n"
        + "  autoZeigen(o.modus);\n"
        + "  await autoAktionPruefen(!!o.passt);\n"
        + "  return JSON.stringify({\n"
        + "    gefragt: gesendet.filter((n) => n && n.art === 'auto_start').length,\n"
        + "    gelaufen, pulldown: $('f-auto').value,\n"
        + "  });\n"
        + "})();");
      return JSON.parse(await f(o));
    } finally { w.close(); }
  };

  // 1) Automatik aus -> es wird NICHT EINMAL GEFRAGT.
  {
    const r = await lauf({ key: "ABC-1", modus: "", starten: true });
    check(r.gefragt === 0,
          "Automatik aus: der Hintergrund wird gar nicht erst gefragt");
    check(r.gelaufen.length === 0, "und es laeuft nichts");
    check(r.pulldown === "", "das Pulldown steht auf AUS", r.pulldown);
  }

  // 2) Der Regelfall.
  {
    const r = await lauf({ key: "ABC-1", modus: "antwort", starten: true });
    check(r.gefragt === 1, "neues Ticket: der Hintergrund wird gefragt");
    check(JSON.stringify(r.gelaufen) === JSON.stringify(["antwort"]),
          "und es laeuft GENAU die eingestellte Aktion",
          JSON.stringify(r.gelaufen));
    check(r.pulldown === "antwort", "das Pulldown zeigt sie an", r.pulldown);
  }

  /* 3) ⚠ DIE WICHTIGSTE SCHRANKE. Liegt fuer dieses Ticket schon ein Ergebnis
   *    vor, kann es der Benutzer BEARBEITET haben (der Text wird gedrosselt
   *    mitgemerkt). Ein automatischer Lauf wuerde es ueberschreiben - seine
   *    Arbeit waere weg, ohne dass er etwas gedrueckt hat. */
  {
    const r = await lauf({ key: "ABC-1", modus: "antwort", starten: true,
                           passt: true });
    check(r.gefragt === 0 && r.gelaufen.length === 0,
          "liegt schon ein Ergebnis zu diesem Ticket vor, laeuft NICHTS "
          + "(der Text kann bearbeitet sein)");
  }

  // 4) Waehrend einer Auswertung wird nichts angestossen.
  {
    const r = await lauf({ key: "ABC-1", modus: "antwort", starten: true,
                           laeuft: true });
    check(r.gefragt === 0 && r.gelaufen.length === 0,
          "waehrend eines laufenden Auftrags startet nichts zusaetzlich");
  }

  // 5) Kein Ticket im Tab.
  {
    const r = await lauf({ key: "", modus: "antwort", starten: true });
    check(r.gefragt === 0 && r.gelaufen.length === 0,
          "ohne erkanntes Ticket startet nichts");
  }

  /* 6) Abgemeldet. Kann in der Seitenleiste vorkommen: ihre Tab-Zuhoerer
   *    ueberleben eine Abmeldung, der Arbeitsbereich ist dann verborgen. */
  {
    const r = await lauf({ key: "ABC-1", modus: "antwort", starten: true,
                           abgemeldet: true });
    check(r.gefragt === 0 && r.gelaufen.length === 0,
          "abgemeldet startet nichts");
  }

  /* 7) DER TAB WECHSELT WAEHREND DER RUECKFRAGE. `auswerten` liest `_key`
   *    selbst - ohne die zweite Pruefung wuerde fuer das NEUE Ticket
   *    ausgewertet, waehrend im Ring das alte vermerkt ist. */
  {
    const r = await lauf({ key: "ABC-1", modus: "antwort", starten: true,
                           wechseltTab: true });
    check(r.gefragt === 1, "gefragt wurde");
    check(r.gelaufen.length === 0,
          "aber nach einem Tab-Wechsel waehrend der Rueckfrage laeuft nichts");
  }

  /* 8) Aelterer Hintergrund: die Anfrage kennt er nicht. Still bleiben - es
   *    hat niemand etwas gedrueckt, und die Stand-Warnung sagt es ohnehin. */
  {
    const r = await lauf({ key: "ABC-1", modus: "antwort", starten: true,
                           hintergrundAlt: true });
    check(r.gelaufen.length === 0,
          "ein aelterer Hintergrund laesst die Automatik still aus");
  }
}

// ── e) Verdrahtung ───────────────────────────────────────────────────────
{
  const tla = schneidePopup("ticketLageAnwenden") || "";
  check(/autoAktionPruefen\(/.test(tla),
        "ticketLageAnwenden stoesst die Automatik an - die EINE Stelle, an der "
        + "Anzeige und Ticketbezug zusammenlaufen (start() UND tabWechsel)");
  /* ⚠ OHNE `await`: `start()` registriert unmittelbar danach die Tab-Zuhoerer
   * der Leiste, und die sind eine Sicherheitsschranke. Ein abgewarteter Lauf
   * liesse die Leiste zehn Sekunden ohne Beobachtung des Tab-Wechsels. */
  check(!/await\s+autoAktionPruefen\(/.test(tla),
        "und wartet NICHT darauf (sonst haengen die Tab-Zuhoerer hinterher)");
  check(/autoAktionPruefen\([\s\S]*?_key !== key/.test(POPUP_JS),
        "dafuer prueft autoAktionPruefen die Ticketnummer nach der Rueckfrage "
        + "ein zweites Mal");

  const st = schneidePopup("start") || "";
  check(/autoZeigen\(z\.auto_modus\)/.test(st),
        "start() belegt das Pulldown aus dem gespeicherten Zustand");
  check(st.indexOf("autoZeigen(") < st.indexOf("ticketLageAnwenden("),
        "und zwar BEVOR die Ticketlage angewandt wird - sonst liest die "
        + "Automatik einen leeren Modus");

  check(/case "auto_start":/.test(BG),
        "der Hintergrund kennt den Nachrichtenfall");
  check(/auto_modus: autoModus\(e\.auto_modus\)/.test(BG),
        "und gibt den Modus im Zustand heraus (sonst stuende das Pulldown "
        + "nach jedem Oeffnen wieder auf AUS)");

  /* ⚠ ABMELDEN RAEUMT DEN RING. Es sind die Ticketnummern des vorigen
   * Benutzers; der naechste am selben Rechner bekaeme fuer sie keine
   * Automatik. Die EINSTELLUNG bleibt - die gehoert zum Browser. */
  /* ⚠ OHNE KOMMENTARE. Der erste Anlauf schlug hier fehl, und der Code war in
   * Ordnung: die Begruendung IM Quelltext nennt `auto_modus` woertlich ("der
   * Einstellung passiert nichts"). Der Waechter las seine eigene Begruendung -
   * die Falle steht im Register und ist hier trotzdem zugeschnappt. */
  const ab = (ohneKommentare(BG).match(/case "abmelden":[\s\S]*?break;/) || [""])[0];
  check(/auto_gelaufen: \[\]/.test(ab), "Abmelden leert den Ring", ab.trim());
  check(!/auto_modus/.test(ab),
        "laesst die Einstellung aber stehen (sie gehoert zum Browser, "
        + "nicht zu einer Anmeldung)", ab.trim());

  /* DRIFT-SCHRANKE, und zwar als REGEL: jedes Feld, das das Fenster per
   * `merken` schickt, muss `einstSchreiben` auch kennen. Sonst wird es dort
   * WORTLOS verworfen - der Benutzer stellt etwas ein, es steht beim naechsten
   * Oeffnen wieder auf der Vorgabe, und es gibt keine Fehlermeldung. Genau
   * dieser Fall ist der Grund fuer STAND. */
  const felder = new Set();
  for (const m of POPUP_JS.matchAll(/\{\s*art:\s*"merken",([\s\S]*?)\}\)/g)) {
    for (const f of m[1].matchAll(/(\w+)\s*[:,]/g)) felder.add(f[1]);
  }
  const es = schneideBg("einstSchreiben") || "";
  check(felder.size >= 3, "das Fenster schickt Felder per merken",
        [...felder].join(", "));
  for (const f of felder) {
    check(new RegExp("teil\\." + f + " !== undefined").test(es),
          "einstSchreiben kennt das Feld " + f
          + " (sonst wird es wortlos verworfen)");
  }
  check(felder.has("auto_modus"), "darunter auto_modus");
}

/* ── 15) DAS ERGEBNISFELD IST RICH-TEXT ────────────────────────────────────
 *
 * Vorgabe des Nutzers 2026-08-31: `**Loesung:**` soll FETT dastehen, und beim
 * Einfuegen sollen echte `<strong>`-Knoten in den Jira-Editor.
 *
 * DIE KETTE ENDET BEIM KUNDEN – deshalb wird hier nichts am Quelltext
 * abgelesen, sondern ausgefuehrt. Zwei Dinge muessen zugleich halten:
 * was der Mitarbeiter SIEHT und was der Kunde BEKOMMT.
 */
section("15) Ergebnisfeld als Rich-Text");

/* Baut die Feld-Funktionen aus der echten popup.js in ein jsdom-Fenster. */
function feldWelt() {
  const { teile, drin } = popupTeile(
    ["zuBloecken", "hatFett", "ohneFett", "textZuFeld", "feldZuText"], []);
  const dom = new JSDOM("<div id=e></div>", { runScripts: "outside-only" });
  const w = dom.window;
  const F = new w.Function(FELD_KONST + "\n" + teile.join("\n")
    + "\nreturn { zuBloecken, hatFett, ohneFett, textZuFeld, feldZuText };")();
  return { w, F, el: w.document.getElementById("e"), drin };
}

// ── a) Der Rundlauf Text -> Feld -> Text ─────────────────────────────────
{
  const { w, F, el, drin } = feldWelt();
  for (const n of ["zuBloecken", "textZuFeld", "feldZuText", "ohneFett"]) {
    check(drin.has(n), "popup.js hat " + n + "()");
  }
  /* ⚠ EIN PARSER FUER BEIDES. Liefe die Anzeige nach anderen Regeln als das
   * Einfuegen, saehe der Mitarbeiter etwas anderes, als der Kunde bekommt. */
  check(/zuBloecken\(/.test(schneidePopup("textZuFeld") || ""),
        "textZuFeld baut aus demselben Parser wie das Einfuegen");

  const RUND = [
    "**Lösung:** Der Dienst wurde neu gestartet.",
    "1. Worum es geht\n2. Was passiert ist\n\n- Punkt A\n- Punkt B",
    "Sehr geehrte Damen und Herren,\n\nwir haben geprüft.\n\nMit freundlichen Grüßen",
    "**Lösung:**\nDetails darunter.",
    // Die drei Fallen, an denen ein naives Muster den Kundentext verstuemmelt.
    "Preis 2 * 3 * 4 und Datei *.txt bleiben unangetastet",
    "Sternchen ** allein ** mit Leerzeichen",
    "***fett und kursiv***",
    "**A** und **B** in einer Zeile",
    "Ein <script>alert(1)</script> aus dem Ticket",
    "",
  ];
  for (const t of RUND) {
    F.textZuFeld(el, t);
    const zurueck = F.feldZuText(el);
    check(zurueck === t, "verlustfrei: " + JSON.stringify(t.slice(0, 42)),
          "zurueck " + JSON.stringify(zurueck.slice(0, 60)));
  }
  w.close();
}

// ── b) Was ECHTE Browser beim Bearbeiten bauen ───────────────────────────
/* ⚠ DIESE TABELLE IST GEMESSEN, NICHT AUSGEDACHT. Die Chrome-Formen stammen
 * aus einem Lauf in echtem Chrome (contenteditable, execCommand-Operationen,
 * innerHTML abgegriffen). Sie hat einen Fehler im ersten Entwurf gefunden: der
 * Rueckweg verwarf `<br>` und zog damit zwei Zeilen stillschweigend zusammen.
 *
 * Die Firefox-Formen sind der zweite Grund fuer diese Tabelle: Firefox erzeugt
 * beim Enter GAR KEIN `<div>`, sondern ein `<br>` auf oberster Ebene. Wer nur
 * "div = Zeile" kennt, verliert dort JEDEN vom Benutzer gesetzten Umbruch -
 * und beide Browser werden ausgeliefert. */
{
  const { w, F, el } = feldWelt();
  const FORMEN = [
    ["Chrome: Enter am Zeilenende",
     "<div><strong>L:</strong> eins</div><div>neu</div><div>zwei</div>",
     "**L:** eins\nneu\nzwei"],
    ["Chrome: Shift+Enter -> br IN der Zeile",
     "<div><strong>L:</strong> eins<br>neu</div><div>zwei</div>",
     "**L:** eins\nneu\nzwei"],
    ["Chrome: alles markiert und geloescht", "<br>", ""],
    ["Chrome: leere Zeile", "<div>a</div><div><br></div><div>b</div>", "a\n\nb"],
    ["Chrome: Fuellwerk-br am Blockende", "<div>a<br></div><div>b</div>", "a\nb"],
    ["Chrome: Strg+B erzeugt <b>",
     "<div><strong>L:</strong> <b>Der</b> Dienst</div>", "**L:** **Der** Dienst"],
    ["Strg+B als span font-weight",
     '<div><span style="font-weight:700">Fett</span> normal</div>',
     "**Fett** normal"],
    ["Fremdformat eingefuegt wird flachgeklopft",
     '<div>a<i>kursiv</i> und <span style="color:red">rot</span></div>',
     "akursiv und rot"],
    ["FIREFOX: Enter erzeugt br, keine div", "eins<br>zwei<br>drei",
     "eins\nzwei\ndrei"],
    ["FIREFOX: mit Fett", "<strong>L:</strong> eins<br>zwei", "**L:** eins\nzwei"],
    ["FIREFOX: alles geloescht", "<br>", ""],
    /* Der HAEUFIGSTE Bearbeitungsfall: ein Leerzeichen hinter das fette Wort
     * getippt. Naiv emittiert waere das `**Loesung: **`, und das erfuellt die
     * Bedingung beim naechsten Aufbau nicht - das Fett waere nach dem
     * naechsten Wiederherstellen spurlos weg. */
    ["Leerzeichen im Fettlauf", "<div><strong>Lösung: </strong>Text</div>",
     "**Lösung:** Text"],
    /* Beim Loeschen an einer Fettgrenze entstehen zwei benachbarte Laeufe.
     * `**A****B**` ist im Feld unsichtbar, im Text an den Server und in der
     * textarea aber sichtbarer Muell. */
    ["zwei Fettlaeufe nebeneinander",
     "<div><strong>A</strong><strong>B</strong> c</div>", "**AB** c"],
    ["geschuetztes Leerzeichen wird normal", "<div>a  b</div>", "a  b"],
  ];
  for (const [name, html, erwartet] of FORMEN) {
    el.innerHTML = html;          // NUR im Test: stellt das Browser-Ergebnis nach
    const t = F.feldZuText(el);
    check(t === erwartet, name, "bekommen " + JSON.stringify(t)
          + " statt " + JSON.stringify(erwartet));
  }
  w.close();
}

// ── c) Modelltext kann kein Element werden ───────────────────────────────
/* Der Text stammt aus einem Modell, das Kundentext verarbeitet hat. Mit
 * `innerHTML` waere ein `<img src=x onerror=…>` aus einem Ticket im Origin der
 * Erweiterung ausfuehrbar - und dort liegt das Sitzungstoken. */
{
  const { w, F, el } = feldWelt();
  const boese = 'Ein <img src=x onerror=alert(1)> und <script>alert(2)</script>'
    + ' und <b>fett</b> aus dem Ticket';
  F.textZuFeld(el, boese);
  const fremd = [...el.querySelectorAll("*")]
    .map((n) => n.nodeName).filter((n) => n !== "DIV" && n !== "STRONG");
  check(fremd.length === 0,
        "aus Modelltext entsteht KEIN fremdes Element", fremd.join(","));
  check(el.textContent === boese,
        "und der Text bleibt woertlich erhalten", el.textContent.slice(0, 50));
  check(!/innerHTML/.test(schneidePopup("textZuFeld") || ""),
        "textZuFeld benutzt kein innerHTML");
  w.close();
}

// ── d) Eingefuegt und fallengelassen wird nur Klartext ───────────────────
/* In echtem Chrome gemessen: ein Einfuegen aus der Zwischenablage traegt
 * `<i>`, `<span style>` und beliebiges weiteres Markup in das Feld. */
{
  const ohne = ohneKommentare(POPUP_JS);
  const einsetzen = schneidePopup("klartextEinsetzen") || "";
  check(!!einsetzen, "popup.js hat klartextEinsetzen()");
  check(/addEventListener\("paste"/.test(ohne), "ein paste-Zuhoerer ist da");
  check(/addEventListener\("drop"/.test(ohne),
        "und ein drop-Zuhoerer - Hineinziehen ist derselbe Fall");
  check(/addEventListener\("dragover"/.test(ohne),
        "mit dragover, sonst navigiert Chrome das Fenster weg");

  const pasteRumpf = (ohne.match(
    /addEventListener\("paste"[\s\S]*?\n\}\);/) || [""])[0];
  check(/preventDefault\(\)/.test(pasteRumpf), "paste wird abgefangen");
  check(/getData\("text\/plain"\)/.test(pasteRumpf),
        "und NUR text/plain gelesen - nie text/html");
  check(!/text\/html/.test(pasteRumpf), "text/html wird nirgends angefasst");
  /* Ohne das Ereignis laeuft die Merk-Drossel nicht an, und das Eingesetzte
   * waere beim naechsten Oeffnen weg - genau das Szenario, fuer das der Timer
   * gebaut wurde. */
  check(/dispatchEvent\(new Event\("input"/.test(einsetzen),
        "der Range-Rueckfall feuert selbst ein input-Ereignis");
}

// ── e) Der Abgleich-Hinweis gehoert NICHT in den Kundentext ──────────────
/* ⚠ AUSGEFUEHRT, nicht gelesen. Die alte Pruefung hing an der Schreibweise
 * `ergebnisFeld.value = …` und wurde durch den Umbau zur Tautologie. Der
 * Hinweis ist eine Anmerkung FUER den Mitarbeiter; landete er im Feld, ginge
 * er mit dem naechsten Klick auf "Einfuegen" an einen Kunden. */
{
  const { teile } = popupTeile(["auswerten", "mitAbgleich", "textZuFeld",
                                "feldZuText", "melde"],
                               ["frage", "sperre"]);
  const dom = new JSDOM(POPUP_HTML, { url: "https://x.test/",
                                      runScripts: "outside-only" });
  const w = dom.window;
  try {
    const f = new w.Function(""
      + "const $ = (id) => document.getElementById(id);\n"
      + "const el = { ergebnisFeld: $('f-ergebnis'), ergebnis: $('ergebnis'),\n"
      + "             ergebnisFuss: $('ergebnis-fuss'), meldung: $('meldung'),\n"
      + "             hinweis: $('f-hinweis') };\n"
      + "let _key = 'ABC-1', _letztes = null, _fremdesErgebnis = false;\n"
      + "let _marke = 'Marke', _laeuft = false, _leiste = false;\n"
      + "let _merkTimer = null, _autoModus = '';\n"
      + "const _originale = new Map();\n"
      + "function sperre() {}\n"
      + "async function frage() {\n"
      + "  return { ok: true, daten: { key: 'ABC-1', modus: 'ueberarbeiten',\n"
      + "    text: 'ANTWORTTEXT', hinweis: 'GEHEIMER-ABGLEICH', kommentare: 3,\n"
      + "    modell: 'M' } };\n"
      + "}\n"
      /* Auch ARBEITSTEXT/FERTIGTEXT stehen in keinem Funktionsrumpf und
       * fallen aus dem Schnitt - dieselbe Falle wie bei _FETT_RE. */
      + (POPUP_JS.match(/const ARBEITSTEXT = \{[\s\S]*?\n\};/) || [""])[0] + "\n"
      + (POPUP_JS.match(/const FERTIGTEXT = \{[\s\S]*?\n\};/) || [""])[0] + "\n"
      + FELD_KONST + "\n" + teile.join("\n") + "\n"
      + "return (async () => {\n"
      + "  await auswerten('ueberarbeiten', 'entwurf');\n"
      + "  return JSON.stringify({\n"
      + "    sichtbar: el.ergebnisFeld.textContent,\n"
      + "    kanonisch: feldZuText(el.ergebnisFeld),\n"
      + "    meldung: el.meldung.textContent,\n"
      + "  });\n"
      + "})();");
    const r = JSON.parse(await f());
    check(r.sichtbar.indexOf("GEHEIMER-ABGLEICH") < 0,
          "der Abgleich-Hinweis steht NICHT sichtbar im Feld", r.sichtbar);
    check(r.kanonisch.indexOf("GEHEIMER-ABGLEICH") < 0,
          "und auch nicht in dem, was gespeichert und eingefuegt wird",
          r.kanonisch);
    check(r.sichtbar.indexOf("ANTWORTTEXT") >= 0,
          "der Antworttext dagegen schon (sonst waere gar nichts gelaufen)");
    check(r.meldung.indexOf("GEHEIMER-ABGLEICH") >= 0,
          "der Hinweis erscheint als MELDUNG", r.meldung);
  } finally { w.close(); }
}

// ── f) Einfuegen: mit Fett, ohne Fett, in eine textarea ──────────────────
/* ⚠ execCommand wird als AUFZEICHNER gestellt, nicht als `() => false`. Nur so
 * ist messbar, welcher Weg wirklich genommen wurde - ohne die Attrappe misst
 * man immer nur den Rueckfall, und die Zusage "ohne Fett aendert sich nichts"
 * waere unpruefbar. */
{
  const bloeckeAus = (text) => {
    const { w, F } = feldWelt();
    const b = F.zuBloecken(text);
    w.close();
    return JSON.parse(JSON.stringify(b));   // wie ueber executeScript: JSON
  };

  const einfuegeLauf = (html, text, mitBloecken, execAntwort) => {
    const dom = new JSDOM("<body>" + html + "</body>",
      { url: "https://jira.test/browse/A-1", runScripts: "outside-only" });
    const w = dom.window, doc = w.document;
    w.Element.prototype.getBoundingClientRect = function () {
      return this.hasAttribute("data-unsichtbar")
        ? { width: 0, height: 0 } : { width: 300, height: 80 };
    };
    w.Element.prototype.scrollIntoView = function () {};
    const ruf = [];
    if (execAntwort !== null) {
      doc.execCommand = (befehl, u, wert) => {
        ruf.push(befehl);
        if (!execAntwort) return false;
        // Wie der Browser: an der Auswahl einsetzen.
        const ziel = doc.querySelector("[contenteditable]")
          || doc.activeElement;
        if (ziel && befehl === "insertText") {
          ziel.appendChild(doc.createTextNode(wert));
        } else if (ziel && befehl === "insertHTML") {
          const h = doc.createElement("div");
          h.innerHTML = wert;
          while (h.firstChild) ziel.appendChild(h.firstChild);
        }
        return true;
      };
    }
    const f = ladeEinfuegen(w);
    const r = mitBloecken ? f(text, bloeckeAus(text)) : f(text);
    const ziel = doc.querySelector("[contenteditable]")
      || doc.querySelector("textarea");
    const erg = {
      ok: r.ok, weg: r.weg, ruf,
      inhalt: ziel ? (ziel.value !== undefined && ziel.tagName === "TEXTAREA"
        ? ziel.value : ziel.textContent) : "",
      fett: ziel ? ziel.querySelectorAll
        ? ziel.querySelectorAll("strong").length : 0 : 0,
    };
    w.close();
    return erg;
  };

  const MIT = "**Lösung:** Der Dienst laeuft.";
  const OHNE = "Guten Tag,\n\nerledigt.";

  // 1) OHNE Fett bleibt der bevorzugte Weg unangetastet.
  {
    const r = einfuegeLauf('<div contenteditable="true"></div>', OHNE, true, true);
    check(r.ruf.indexOf("insertText") >= 0,
          "ohne Fett wird weiterhin insertText benutzt", r.ruf.join(","));
    check(r.ruf.indexOf("insertHTML") < 0, "und NICHT insertHTML");
    check(r.inhalt.indexOf("erledigt.") >= 0, "der Text kommt an", r.inhalt);
  }

  // 2) MIT Fett: echte <strong> im Ziel.
  {
    const r = einfuegeLauf('<div contenteditable="true"></div>', MIT, true, true);
    check(r.fett === 1, "mit Fett steht ein <strong> im Ziel", String(r.fett));
    check(r.inhalt.indexOf("Lösung:") >= 0, "mit dem richtigen Wort", r.inhalt);
    check(r.inhalt.indexOf("**") < 0,
          "und OHNE Sternchen - die liest sonst der Kunde", r.inhalt);
    check(/fett/i.test(String(r.weg)), "der Weg wird als Fett-Weg gemeldet", r.weg);
  }

  // 3) MIT Fett, aber der Editor nimmt execCommand nicht an -> Knoten.
  {
    const r = einfuegeLauf('<div contenteditable="true"></div>', MIT, true, false);
    check(r.fett === 1, "auch ueber den Knotenweg kommt Fett an", String(r.fett));
    check(r.inhalt.indexOf("**") < 0, "weiterhin ohne Sternchen", r.inhalt);
  }

  /* 4) EINE TEXTAREA KANN KEIN FETT. Dort geht der bereinigte Text hinein -
   * ein `**` waere genau das, was der Kunde am Ende liest. */
  {
    const r = einfuegeLauf('<textarea id="comment"></textarea>', MIT, true, null);
    check(r.inhalt.indexOf("**") < 0,
          "textarea bekommt den Text OHNE Sternchen", r.inhalt);
    check(r.inhalt.indexOf("Lösung:") >= 0, "aber vollstaendig", r.inhalt);
  }

  /* 5) ALTES FENSTER, NEUE einfuegen.js: ohne zweites Argument muss sich alles
   * verhalten wie vor dem Umbau - sonst braeche jeder Bestandstest. */
  {
    const r = einfuegeLauf('<textarea id="comment"></textarea>', MIT, false, null);
    check(r.ok === true && r.inhalt === MIT,
          "ohne bloecke bleibt der Originaltext unangetastet", r.inhalt);
  }
}

// ── g) Kopieren legt bereinigten Text ab ─────────────────────────────────
{
  const ohne = ohneKommentare(POPUP_JS);
  const kop = (ohne.match(/btn-kopieren"\)\.addEventListener\([\s\S]*?\n\}\);/) || [""])[0];
  check(/ohneFett\(/.test(kop),
        "Kopieren legt den Text OHNE Sternchen ab - er wird von Hand eingefuegt");
  const zweit = (ohne.match(/func: einfuegenUeberEditorApi,[\s\S]{0,120}/) || [""])[0];
  check(/ohneFett\(/.test(zweit),
        "und der Editor-API-Weg ebenfalls (er kann kein Fett tragen)", zweit.trim());
}

// ── h) Das Feld sieht aus wie ein Eingabefeld und waechst nicht davon ────
{
  const regel = (POPUP_CSS.match(/#f-ergebnis \{([^}]*)\}/) || ["", ""])[1];
  check(!!regel.trim(), "es gibt eine eigene #f-ergebnis-Regel");
  for (const [eig, grund] of [
    ["white-space: pre-wrap", "Umbrueche und Einrueckungen des Modells"],
    ["min-height", "sonst ist das Feld beim ersten Zeichen huefthoch"],
    ["overflow", "Voraussetzung dafuer, dass resize ueberhaupt wirkt"],
  ]) {
    check(regel.indexOf(eig) >= 0, "#f-ergebnis setzt " + eig + " - " + grund);
  }
  /* ⚠ DER DECKEL IST DER WICHTIGE TEIL. Die abgeloeste textarea hatte
   * rows="12", also eine FESTE Hoehe. Ein <div> waechst unbegrenzt und schoebe
   * bei einer langen Antwort den Einfuegen-Knopf aus dem 600-px-Fenster. */
  check(/max-height/.test(regel),
        "und einen max-height-Deckel (sonst waechst es aus dem Fenster)");
  const leiste = (POPUP_CSS.match(/html\.leiste #f-ergebnis \{([^}]*)\}/) || ["", ""])[1];
  check(/min-height:\s*40vh/.test(leiste),
        "in der Leiste bleibt der Hoehengewinn erhalten", leiste.trim());
  check(/max-height/.test(leiste), "auch dort gedeckelt");
  check(/#f-ergebnis:empty::before/.test(POPUP_CSS),
        "ein leeres Feld zeigt einen Platzhalter (ein div kennt kein placeholder)");
  // Das Markup selbst.
  check(/id="f-ergebnis"[^>]*contenteditable="true"/.test(POPUP_HTML),
        "das Feld ist contenteditable");
  check(/id="f-ergebnis"[^>]*role="textbox"/.test(POPUP_HTML),
        'und traegt role="textbox" - ein div hat keine implizite Rolle');
  check(/id="f-ergebnis"[^>]*aria-multiline="true"/.test(POPUP_HTML),
        "sowie aria-multiline");
  check(/id="f-ergebnis"[^>]*spellcheck="true"/.test(POPUP_HTML),
        "die Rechtschreibpruefung bleibt erhalten");
  check(!/<textarea id="f-ergebnis"/.test(POPUP_HTML),
        "und es ist keine textarea mehr");
}

// ═══════════════════════════════════════════════════════════════════════════
section('16) „Als Kommentar uebernehmen" ERSETZT, statt anzuhaengen');
// ═══════════════════════════════════════════════════════════════════════════
/* VORGABE 2026-08-31: der Knopf hiess „Ins Kommentarfeld einfuegen" und haengte
 * an – aber nur bei den EDITOR-Wegen; die textarea-Wege ersetzten schon immer.
 * Dieselbe Beschriftung hatte also je Jira-Betriebsart eine andere Wirkung.
 *
 * ⚠ DIE ATTRAPPE FUER `execCommand` MUSS DIE AUSWAHL BEACHTEN. Die Attrappe in
 * Abschnitt 6f haengt bedingungslos an – gegen sie waere „ersetzt" gar nicht
 * messbar, und der Waechter waere mit der ANHAENGENDEN Fassung gruen. Hier wird
 * deshalb der Browser nachgebaut: `insertText`/`insertHTML` LOESCHEN zuerst die
 * markierte Auswahl (jsdom kann `Range.deleteContents`). */
{
  const bloeckeAus = (text) => {
    const { w, F } = feldWelt();
    const b = F.zuBloecken(text);
    w.close();
    return JSON.parse(JSON.stringify(b));   // wie ueber executeScript: JSON
  };

  /** @param execAntwort true = Editor nimmt execCommand an, false = nicht,
   *                     null = es gibt kein execCommand (reine textarea). */
  function uebernahme(html, text, execAntwort) {
    const dom = new JSDOM("<body>" + html + "</body>",
      { url: "https://jira.test/browse/A-1", runScripts: "outside-only" });
    const w = dom.window, doc = w.document;
    w.Element.prototype.getBoundingClientRect = () => ({ width: 300, height: 80 });
    w.Element.prototype.scrollIntoView = function () {};
    const ruf = [];
    if (execAntwort !== null) {
      doc.execCommand = (befehl, u, wert) => {
        ruf.push(befehl);
        if (!execAntwort) return false;
        const ziel = doc.querySelector("[contenteditable]") || doc.activeElement;
        if (!ziel) return false;
        // WIE DER BROWSER: erst die Auswahl weg, dann einsetzen.
        const sel = w.getSelection();
        if (sel && sel.rangeCount) { try { sel.getRangeAt(0).deleteContents(); } catch (e) {} }
        if (befehl === "insertText") {
          ziel.appendChild(doc.createTextNode(wert));
        } else if (befehl === "insertHTML") {
          const h = doc.createElement("div");
          h.innerHTML = wert;
          while (h.firstChild) ziel.appendChild(h.firstChild);
        } else { return false; }
        return true;
      };
    }
    const r = ladeEinfuegen(w)(text, bloeckeAus(text));
    const ziel = doc.querySelector("[contenteditable]") || doc.querySelector("textarea");
    const erg = {
      ok: r.ok, weg: String(r.weg || ""), ruf,
      inhalt: ziel
        ? (ziel.tagName === "TEXTAREA" ? ziel.value : ziel.textContent)
        : "",
      fett: (ziel && ziel.querySelectorAll) ? ziel.querySelectorAll("strong").length : 0,
    };
    w.close();
    return erg;
  }

  const ALT  = "Guten Tag Herr Mueller, das schauen wir uns an. MfG";
  const NEU  = "Sehr geehrter Herr Mueller,\n\ndas Problem ist behoben.";
  const NEUF = "**Loesung:** Das Problem ist behoben.";

  // 1) contenteditable mit Entwurf, ohne Fett – der Regelweg.
  {
    const r = uebernahme('<div contenteditable="true">' + ALT + '</div>', NEU, true);
    check(r.inhalt.indexOf("behoben.") >= 0, "der neue Text kommt an", r.inhalt);
    check(r.inhalt.indexOf("Guten Tag Herr Mueller") < 0,
          "und der alte Entwurf ist WEG (ersetzt, nicht angehaengt)", r.inhalt);
    check(r.ruf.indexOf("insertText") >= 0,
          "ueber insertText – geht durch den Editor und bleibt ruecknehmbar",
          r.ruf.join(","));
  }

  // 2) Derselbe Fall ohne execCommand: der harte Weg muss ebenso ersetzen,
  //    sonst haette EIN Knopf je Editor zwei verschiedene Wirkungen.
  {
    const r = uebernahme('<div contenteditable="true">' + ALT + '</div>', NEU, false);
    check(r.inhalt.indexOf("behoben.") >= 0, "Knotenweg: der neue Text kommt an", r.inhalt);
    check(r.inhalt.indexOf("Guten Tag Herr Mueller") < 0,
          "Knotenweg: der alte Entwurf ist ebenfalls weg", r.inhalt);
  }

  // 3) Mit Fett ueber insertHTML.
  {
    const r = uebernahme('<div contenteditable="true">' + ALT + '</div>', NEUF, true);
    check(r.fett === 1, "mit Fett steht ein <strong> im Ziel", String(r.fett));
    check(r.inhalt.indexOf("Guten Tag Herr Mueller") < 0,
          "und der alte Entwurf ist weg", r.inhalt);
    check(/insertHTML\+fett/.test(r.weg), "gemeldet wird der insertHTML-Weg", r.weg);
  }

  // 4) Mit Fett, aber der Editor nimmt execCommand nicht an.
  {
    const r = uebernahme('<div contenteditable="true">' + ALT + '</div>', NEUF, false);
    check(r.fett === 1, "Knotenweg: Fett kommt an", String(r.fett));
    check(r.inhalt.indexOf("Guten Tag Herr Mueller") < 0,
          "Knotenweg: der alte Entwurf ist weg", r.inhalt);
  }

  /* 5) ⚠ DER FALL, DER DIE RUECKLESEPROBE UMBAUEN MUSSTE: die uebernommene
   * Fassung ist KUERZER als der Entwurf, den sie ersetzt. Die alte Probe hiess
   * `jetzt.length > vorher.length` – damit haette sich der insertHTML-Weg
   * selbst fuer wirkungslos erklaert und waere auf `insertText` OHNE Fett
   * gefallen: Fett verloren, ohne dass etwas kaputt war. */
  {
    const lang = "Sehr geehrter Herr Mueller, ".repeat(12);
    const r = uebernahme('<div contenteditable="true">' + lang + '</div>', NEUF, true);
    check(/insertHTML\+fett/.test(r.weg),
          "eine KUERZERE Ersetzung gilt trotzdem als angekommen", r.weg);
    check(!/ohne Fett/.test(r.weg),
          "und NICHT als Rueckfall ohne Fett – das war der alte length-Fehler", r.weg);
    check(r.fett === 1, "das Fett bleibt dabei erhalten", String(r.fett));
    check(r.inhalt.length < lang.length, "und der lange Entwurf ist ersetzt",
          String(r.inhalt.length) + " vs " + lang.length);
  }

  // 6) textarea: verhielt sich schon immer ersetzend – das bleibt so.
  {
    const r = uebernahme('<textarea id="comment">' + ALT + '</textarea>', NEUF, null);
    check(r.inhalt.indexOf("Guten Tag") < 0, "textarea: alter Inhalt ersetzt", r.inhalt);
    check(r.inhalt.indexOf("Loesung:") >= 0 && r.inhalt.indexOf("**") < 0,
          "textarea: neuer Text ohne Sternchen", r.inhalt);
  }

  // 7) Gegenrichtung: ein LEERES Feld verhaelt sich unveraendert.
  {
    const r = uebernahme('<div contenteditable="true"></div>', NEU, true);
    check(r.ok === true && r.inhalt.indexOf("behoben.") >= 0,
          "in ein leeres Feld wird wie bisher geschrieben", r.inhalt);
  }
}

// ── b) Der iframe-Editor (Jira Server mit Rich-Text) ersetzt ebenfalls ───
{
  const dom = new JSDOM('<body><iframe id="ed"></iframe></body>',
    { url: "https://jira.test/browse/A-1", runScripts: "outside-only" });
  const w = dom.window, doc = w.document;
  w.Element.prototype.getBoundingClientRect = () => ({ width: 300, height: 80 });
  w.Element.prototype.scrollIntoView = function () {};
  const rahmen = doc.getElementById("ed");
  const idoc = rahmen.contentDocument;
  idoc.body.setAttribute("contenteditable", "true");
  idoc.body.textContent = "alter Entwurf im Rahmen";
  const ruf = [];
  idoc.execCommand = (befehl, u, wert) => {
    ruf.push(befehl);
    const sel = idoc.defaultView.getSelection();
    if (sel && sel.rangeCount) { try { sel.getRangeAt(0).deleteContents(); } catch (e) {} }
    if (befehl !== "insertText") return false;
    idoc.body.appendChild(idoc.createTextNode(wert));
    return true;
  };
  const r = ladeEinfuegen(w)("Neuer Text.", null);
  check(r.ok === true && /iframe/.test(String(r.weg)),
        "der iframe-Editor wird gefunden", JSON.stringify(r));
  check(idoc.body.textContent.indexOf("alter Entwurf") < 0,
        "und sein Inhalt wird ERSETZT, nicht ergaenzt", idoc.body.textContent);
  check(idoc.body.textContent.indexOf("Neuer Text.") >= 0,
        "der neue Text steht darin", idoc.body.textContent);
  w.close();
}

// ── c) Der Editor-API-Weg benutzt setContent, nicht insertContent ────────
/* `insertContent` haengt an der Cursorposition an – dieser Weg haette dann als
 * einziger noch angehaengt, und ein Knopf mit editorabhaengiger Wirkung ist
 * nicht erklaerbar. */
{
  const { w } = mitDom("<body></body>", (w) => w, "einfuegenUeberEditorApi");
  const dom = new JSDOM("<body></body>", { runScripts: "outside-only" });
  const fw = dom.window;
  const ruf = [];
  fw.tinymce = {
    activeEditor: {
      setContent: (h) => ruf.push("setContent:" + h),
      insertContent: (h) => ruf.push("insertContent:" + h),
    },
  };
  const f = ladeEinfuegen(fw, "einfuegenUeberEditorApi");
  const r = f("Neuer Text.");
  check(r.ok === true, "der Editor-API-Weg meldet Erfolg", JSON.stringify(r));
  check(ruf.some((x) => x.indexOf("setContent:") === 0),
        "es wird setContent gerufen (ersetzt)", ruf.join(" | "));
  check(!ruf.some((x) => x.indexOf("insertContent:") === 0),
        "und NICHT insertContent (das wuerde anhaengen)", ruf.join(" | "));
  check(/setContent/.test(String(r.weg)), "der gemeldete Weg nennt setContent", r.weg);
  fw.close();
  if (w && w.close) w.close();
}

// ── d) Beschriftung und Rueckmeldung sagen, was passiert ─────────────────
{
  check(/id="btn-einfuegen">Als Kommentar übernehmen</.test(POPUP_HTML),
        'der Knopf heisst „Als Kommentar übernehmen"');
  // Der alte Wortlaut darf nirgends stehenbleiben – sonst beschreibt die
  // Anleitung einen Knopf, den es nicht mehr gibt.
  for (const [name, inhalt] of [["popup.html", POPUP_HTML], ["popup.js", POPUP_JS],
                                ["popup.css", POPUP_CSS], ["einfuegen.js", EINFUEGEN]]) {
    check(!/Ins Kommentarfeld einfügen/.test(inhalt),
          name + ": der alte Wortlaut kommt nicht mehr vor");
  }
  check(/id="uebernehmen-hinweis"/.test(POPUP_HTML),
        "im Fenster steht, dass der bisherige Inhalt ersetzt wird");
  check(/uebernehmen-hinweis[\s\S]{0,240}ersetzt/.test(POPUP_HTML),
        'und zwar mit dem Wort „ersetzt“');
  const pj = ohneKommentare(POPUP_JS);
  check(/melde\("Als Kommentar übernommen"/.test(pj),
        'die Erfolgsmeldung heisst „übernommen“, nicht „eingefügt“');
  check(/wurde ersetzt/.test(pj),
        "und sie nennt das Ersetzen – sonst haelt es der Benutzer fuer einen Fehler");
}

// ── e) Version hochgezaehlt (Verhaltensaenderung, nicht nur Beschriftung) ─
{
  const vC = JSON.parse(lies("manifest.json")).version;
  const vF = JSON.parse(lies("manifest.firefox.json")).version;
  check(vC === vF, "beide Manifeste tragen dieselbe Version", vC + " / " + vF);
  const zahl = (v) => v.split(".").map(Number);
  const [a, b] = zahl(vC);
  check(a > 0 || b >= 6,
        "die Version ist ueber 0.5.0 hinaus – das Verhalten hat sich geaendert", vC);
}

// ── f) Die Anleitung im Portal nennt denselben Knopf ─────────────────────
/* Der Waechter greift ueber `browser-addon/` hinaus, weil die Anleitung im
 * Portal liegt: ein Text, der ein Bedienelement bei einem Namen nennt, den es
 * nicht mehr gibt, schickt den Benutzer suchen (Register). */
{
  const FE = path.join(WURZEL, "frontend");
  const i18n = fs.readFileSync(path.join(FE, "js/i18n.js"), "utf8");
  const seite = fs.readFileSync(path.join(FE, "jira_addon.html"), "utf8");
  check(!/Ins Kommentarfeld einfügen/.test(i18n),
        "i18n.js kennt den alten Wortlaut nicht mehr");
  check(!/Ins Kommentarfeld einfügen/.test(seite),
        "das Rueckfall-Markup ebenfalls nicht");
  check(!/Insert into comment field/.test(i18n),
        "auch nicht in Englisch");
  // Beide Sprachen muessen das Ersetzen nennen – es ist die Aenderung, die
  // jemanden ueberraschen kann.
  const de = (i18n.match(/'jaddon\.use_5':\s*'([^']*)'/) || ["", ""])[1];
  const alleUse5 = [...i18n.matchAll(/'jaddon\.use_5':\s*'([^']*)'/g)].map((m) => m[1]);
  check(alleUse5.length === 2, "es gibt jaddon.use_5 in DE und EN", String(alleUse5.length));
  check(alleUse5.every((t) => /ersetzt|replaces/.test(t)),
        "beide Fassungen nennen das Ersetzen", alleUse5.join(" ||| ").slice(0, 200));
  check(de && seite.indexOf("Als Kommentar übernehmen") >= 0,
        "das Rueckfall-Markup nennt den neuen Namen");
}

// ═══════════════════════════════════════════════════════════════════════════
section("17) Zeilenumbrueche ueberleben das Einfuegen");
// ═══════════════════════════════════════════════════════════════════════════
/* Gemeldet 2026-09-01 mit einem Screenshot: rechts im Fenster stand eine
 * Timeline mit einem Eintrag je Zeile, links im Jira-Kommentarfeld war daraus
 * EIN Fliesstextblock geworden.
 *
 * Ursache war `absaetze()`: ein einfacher Umbruch wurde zum Leerzeichen, nur
 * eine LEERZEILE trennte. Das stammte aus der Zeit vor dem Rich-Text-Feld
 * (`replace(/\n/g, " ")`) und widerspricht seither der Zusage des Umbaus – das
 * Feld zeigt `white-space: pre-wrap`, also die Umbrueche.
 *
 * ⚠ GEMESSEN WIRD DIE EIGENSCHAFT, nicht das Markup: `gesehen()` rekonstruiert
 * aus dem Ziel-DOM, was ein Mensch dort SIEHT. Ein Editor, der statt <br> ein
 * <div> je Zeile baut, waere ebenso richtig – eine Suche nach "<br>" haette
 * das faelschlich als Fehler gemeldet. */
{
  const bloeckeAus = (text) => {
    const { w, F } = feldWelt();
    const b = F.zuBloecken(text);
    w.close();
    return JSON.parse(JSON.stringify(b));   // wie ueber executeScript: JSON
  };

  function gesehen(el) {
    if (!el) return "";
    if (el.tagName === "TEXTAREA") return el.value;
    let out = "";
    (function lauf(k) {
      for (const n of k.childNodes) {
        if (n.nodeType === 3) { out += n.nodeValue; continue; }
        if (n.nodeType !== 1) continue;
        if (n.tagName === "BR") { out += "\n"; continue; }
        const block = /^(P|DIV)$/.test(n.tagName);
        if (block && out && !/\n\n$/.test(out)) out += "\n\n";
        lauf(n);
        if (block) out += "\n\n";
      }
    })(el);
    return out.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
  }

  /* Wie in Abschnitt 16: die execCommand-Attrappe LOESCHT erst die Auswahl.
   * Eine bedingungslos anhaengende Attrappe koennte "ersetzt" nicht messen. */
  function einfuegen17(html, text, execAntwort) {
    const dom = new JSDOM("<body>" + html + "</body>",
      { url: "https://jira.test/browse/A-1", runScripts: "outside-only" });
    const w = dom.window, doc = w.document;
    w.Element.prototype.getBoundingClientRect = () => ({ width: 300, height: 80 });
    w.Element.prototype.scrollIntoView = function () {};
    if (execAntwort !== null) {
      doc.execCommand = (befehl, u, wert) => {
        if (!execAntwort) return false;
        const ziel = doc.querySelector("[contenteditable]") || doc.activeElement;
        if (!ziel) return false;
        const sel = w.getSelection();
        if (sel && sel.rangeCount) { try { sel.getRangeAt(0).deleteContents(); } catch (e) {} }
        if (befehl === "insertText") {
          ziel.appendChild(doc.createTextNode(wert));
        } else if (befehl === "insertHTML") {
          const h = doc.createElement("div");
          h.innerHTML = wert;
          while (h.firstChild) ziel.appendChild(h.firstChild);
        } else { return false; }
        return true;
      };
    }
    const r = ladeEinfuegen(w)(text, bloeckeAus(text));
    const ziel = doc.querySelector("[contenteditable]") || doc.querySelector("textarea");
    const erg = { weg: String(r.weg || ""), text: gesehen(ziel),
                  fett: (ziel && ziel.querySelectorAll) ? ziel.querySelectorAll("strong").length : 0 };
    w.close();
    return erg;
  }

  // Der gemeldete Fall: Fett UND ein Eintrag je Zeile.
  const TIMELINE = "**Timeline**\n07.07. Weiterleitung an A. Liman\n"
                 + "08.07. Koordinierung aller Beteiligten\n\n"
                 + "**Bewertung**\nReaktive Kommunikation.";
  const T_SOLL   = "Timeline\n07.07. Weiterleitung an A. Liman\n"
                 + "08.07. Koordinierung aller Beteiligten\n\n"
                 + "Bewertung\nReaktive Kommunikation.";
  const OHNE     = "Zeile eins\nZeile zwei\n\nNeuer Absatz";

  const EDIT = '<div contenteditable="true">Alter Entwurf</div>';

  // a) Mit Fett ueber insertHTML – der Weg des gemeldeten Falls.
  {
    const r = einfuegen17(EDIT, TIMELINE, true);
    check(r.text === T_SOLL,
          "insertHTML+fett: jede Zeile bleibt eine Zeile", JSON.stringify(r.text));
    const zeilen = r.text.split("\n").filter((z) => z.trim());
    check(zeilen.length === 5,
          "es sind wirklich 5 Zeilen, kein Fliesstextblock", String(zeilen.length));
    check(r.fett === 2, "und die zwei Fettstellen sind erhalten", String(r.fett));
    check(/insertHTML\+fett/.test(r.weg),
          "der Umbruch kostet die Rueckleseprobe NICHT ihren Weg", r.weg);
  }

  // b) Derselbe Text, aber der Editor nimmt execCommand nicht an (Knotenweg).
  {
    const r = einfuegen17(EDIT, TIMELINE, false);
    check(r.text === T_SOLL, "Knotenweg: dieselben Zeilen", JSON.stringify(r.text));
    check(r.fett === 2, "Knotenweg: Fett erhalten", String(r.fett));
  }

  /* c) ⚠ DIE RUECKLESEPROBE WAR DER ZWEITE HALBE FEHLER. `<p>a<br>b</p>` gibt
   * als textContent "ab", die Probe kommt aber aus `klartext()` ("a\nb").
   * Mit der alten Normierung (\s+ -> " ") fand sie sich nie wieder: der Weg
   * haette sich fuer wirkungslos erklaert und waere auf insertText OHNE Fett
   * gefallen – Auszeichnung verloren, obwohl alles angekommen war. */
  {
    const r = einfuegen17(EDIT, TIMELINE, true);
    check(!/ohne Fett/.test(r.weg),
          "kein Rueckfall auf 'insertText ohne Fett' wegen der <br>", r.weg);
  }

  // d) Ohne Fett, ohne execCommand – der Klartext-Rueckfall.
  {
    const r = einfuegen17(EDIT, OHNE, false);
    check(r.text === OHNE, "Klartext-Rueckfall: Umbrueche erhalten",
          JSON.stringify(r.text));
    check(r.fett === 0, "und kein Fett, wo keines war", String(r.fett));
  }

  // e) Gegenrichtung: die LEERZEILE trennt weiterhin Absaetze.
  {
    const r = einfuegen17(EDIT, OHNE, false);
    check(/\n\n/.test(r.text), "die Leerzeile bleibt eine Absatzgrenze",
          JSON.stringify(r.text));
    check(r.text.indexOf("Zeile eins Zeile zwei") < 0,
          "und nichts wird zu einem Leerzeichen zusammengezogen", r.text);
  }

  // f) textarea: schrieb schon immer `\n` – das darf sich nicht aendern.
  {
    const r = einfuegen17('<textarea id="comment">alt</textarea>', TIMELINE, null);
    check(r.text === T_SOLL, "textarea: unveraendert mit Umbruechen",
          JSON.stringify(r.text));
  }

  // g) Der iframe-Editor (Jira Server mit Rich-Text) – beide Zweige.
  for (const mitFett of [true, false]) {
    const quelle = mitFett ? TIMELINE : OHNE;
    const soll   = mitFett ? T_SOLL   : OHNE;
    const dom = new JSDOM('<body><iframe id="ed"></iframe></body>',
      { url: "https://jira.test/browse/A-1", runScripts: "outside-only" });
    const w = dom.window, doc = w.document;
    w.Element.prototype.getBoundingClientRect = () => ({ width: 300, height: 80 });
    w.Element.prototype.scrollIntoView = function () {};
    const idoc = doc.getElementById("ed").contentDocument;
    idoc.body.setAttribute("contenteditable", "true");
    idoc.body.textContent = "alter Entwurf";
    idoc.execCommand = () => false;          // erzwingt den Knoten-/Rueckfallweg
    ladeEinfuegen(w)(quelle, bloeckeAus(quelle));
    check(gesehen(idoc.body) === soll,
          "iframe-Editor" + (mitFett ? " mit" : " ohne") + " Fett: Umbrueche erhalten",
          JSON.stringify(gesehen(idoc.body)));
    w.close();
  }

  /* h) Der Editor-API-Weg (world: "MAIN"). Seine beiden Zweige lagen
   * auseinander: `tm.editors[0]` machte seit jeher `\n` -> <br>, der
   * `activeEditor`-Zweig darueber machte ein Leerzeichen daraus. Derselbe
   * Knopf hatte damit je Editor-Variante eine andere Wirkung. */
  {
    const dom = new JSDOM("<body></body>", { runScripts: "outside-only" });
    const w = dom.window;
    let gesetzt = "";
    w.tinymce = { activeEditor: { setContent: (h) => { gesetzt = h; } } };
    ladeEinfuegen(w, "einfuegenUeberEditorApi")(OHNE);
    const box = w.document.createElement("div");
    box.innerHTML = gesetzt;
    check(gesehen(box) === OHNE, "tinymce.setContent: Umbrueche erhalten",
          JSON.stringify(gesehen(box)));
    check(gesetzt.indexOf("Zeile eins Zeile zwei") < 0,
          "und kein Leerzeichen an der Umbruchstelle", gesetzt);
    w.close();
  }

  /* i) DIE REGEL, nicht eine Liste von Stellen: nirgends in `einfuegen.js`
   * darf ein einfacher Umbruch zu einem Leerzeichen werden. Kommentare werden
   * vorher entfernt – sonst liest der Waechter seine eigene Begruendung
   * (die erklaert genau dieses Muster) und meldet einen Fehler, den es nicht
   * gibt. `\n` -> "<br>" bleibt ausdruecklich erlaubt. */
  {
    const nackt = ohneKommentare(EINFUEGEN);
    const treffer = nackt.match(/replace\(\s*\/\\n\/g\s*,\s*" "\s*\)/g) || [];
    check(treffer.length === 0,
          "kein `replace(/\\n/g, \" \")` mehr in einfuegen.js",
          treffer.join(" | "));
    check(/replace\(\s*\/\\n\/g\s*,\s*"<br>"\s*\)/.test(nackt),
          "der <br>-Weg von tm.editors[0] steht weiterhin da");
  }
}

/* Erst den Puffer leeren: eine Zurueckweisung aus einem nicht abgewarteten
 * Aufruf wird sonst womoeglich erst nach der Zusammenfassung gemeldet. */
await new Promise((r) => setTimeout(r, 20));
for (const z of zurueckweisungen) {
  check(false, "unbehandelte Zurueckweisung im Lauf", z.split("\n")[0]);
}

console.log("\n" + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
})();
