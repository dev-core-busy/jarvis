#!/usr/bin/env node
/* Waechter fuer die Browser-Erweiterung (browser-addon/).
 *
 * Zwei Teile:
 *  1. Struktur und Regeln – Manifeste, Rechte-Zuschnitt, Feldnamen, und die
 *     Frage, wo gefetcht werden darf (das ist unter MV3 keine Stilfrage).
 *  2. Das PANEL und das Einfuegen werden gegen ein nachgebautes Jira-DOM
 *     WIRKLICH AUSGEFUEHRT.
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
const { JSDOM, VirtualConsole } = require("jsdom");

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
const PANEL = lies("panel.js");
const BAUEN = lies("bauen.sh");

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
// Das Panel sitzt IN der Jira-Seite – fuer es gilt dieselbe CORS-Regel. Und es
// darf sich seine Gestaltung auch nicht per fetch(runtime.getURL(...)) holen.
check(!/\bfetch\s*\(/.test(ohneKommentare(PANEL)),
      "panel.js fetcht NICHT (es laeuft im Ursprung der Jira-Seite)");
check(/runtime\.sendMessage/.test(ohneKommentare(PANEL)),
      "panel.js spricht ueber runtime.sendMessage mit dem Hintergrund");
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
section("5) einfuegen.js: klassisches Skript, selbststaendige Funktionen");
// ═══════════════════════════════════════════════════════════════════════════
/* Die Datei wird an ZWEI Orten geladen, und keiner davon kann ES-Module:
 * per `executeScript({files})` in die Jira-Seite (injizierte Dateien sind immer
 * klassische Skripte) und im Hintergrund (Chrome `importScripts`, Firefox als
 * Eintrag in `background.scripts`). Ein `export` stirbt dort mit
 * "Unexpected token 'export'" – und zwar BEVOR das Panel entsteht. */
const einfOhne = ohneKommentare(EINFUEGEN);
check(!/\bexport\s/.test(einfOhne),
      "kein export (injizierte Dateien sind klassische Skripte)");
check(!/\bimport\b/.test(einfOhne), "kein import");
check(/globalThis\.__jvEinfuegen/.test(einfOhne),
      "registriert sich in globalThis.__jvEinfuegen");

/* `einfuegenUeberEditorApi` wird weiterhin per toString serialisiert und in der
 * SEITENWELT neu ausgewertet. Jede Referenz nach draussen – auch auf den eigenen
 * Namensraum – wird dort zu einem ReferenceError. */
const zweitKoerper = einfOhne.slice(einfOhne.indexOf("function einfuegenUeberEditorApi"),
                                    einfOhne.indexOf("raum.einfuegenInJira"));
check(zweitKoerper.length > 200, "die serialisierte Funktion wurde gefunden",
      "Laenge " + zweitKoerper.length);
for (const fremd of ["api.", "chrome.", "browser.", "__jvEinfuegen", "raum.", "$("]) {
  check(!zweitKoerper.includes(fremd),
        "einfuegenUeberEditorApi ohne Referenz auf '" + fremd + "'");
}

/* Und die DOM-Suche darf keine Erweiterungs-API benutzen: sie laeuft in der
 * Jira-Seite, dort gibt es weder Netzrecht noch Speicher der Erweiterung. */
const ersterKoerper = einfOhne.slice(einfOhne.indexOf("function einfuegenInJira"),
                                     einfOhne.indexOf("function einfuegenUeberEditorApi"));
for (const fremd of ["api.", "chrome.", "browser.", "sendMessage"]) {
  check(!ersterKoerper.includes(fremd),
        "einfuegenInJira ohne Referenz auf '" + fremd + "'");
}

// ═══════════════════════════════════════════════════════════════════════════
section("6) Einfuegen gegen ein nachgebautes Jira – WIRKLICH ausgefuehrt");
// ═══════════════════════════════════════════════════════════════════════════
/* Die Funktion wird so geladen, wie der Browser sie sieht: als Quelltext, neu
 * ausgewertet. Damit wird zugleich belegt, dass die Serialisierung traegt. */
function ladeEinfuegen(fenster) {
  // Genau wie der Browser sie laedt: als klassisches Skript, das sich selbst in
  // `globalThis` registriert. Ein Nachbau der Funktion (Quelltext ausschneiden)
  // wuerde beweisen, dass der AUSSCHNITT laeuft – nicht die Datei.
  new fenster.Function(EINFUEGEN)();
  return fenster.__jvEinfuegen.einfuegenInJira;
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
check(/--akzent:\s*#9b59b6/.test(cssOhne),
      'der Rueckfall ist der neutrale Jarvis-Ton');
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
  for (const name of ['markeAnwenden', 'setzeBranding']) {
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

// Kein sichtbarer Text im Paket darf "Jarvis" fest verdrahtet haben – der
// Rueckfall gehoert in EINE Variable, nicht in zwanzig Zeichenketten.
for (const [datei, inhalt] of [['popup.html', POPUP_HTML],
                               ['background.js', BG],
                               ['popup.js', POPUP_JS],
                               ['panel.js', PANEL]]) {
  const sichtbar = ohneKommentare(inhalt)
      // Der Rueckfall selbst und der Elementinhalt der Kopfzeile sind erlaubt.
      .replace(/let _marke = "Jarvis";/, '')
      .replace(/<span class="marke" id="marke">Jarvis<\/span>/, '')
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
  /* Rufen kann `executeScript` nur der Hintergrund – das Panel sitzt in der
   * isolierten Welt und laesst den Weg deshalb dort nachschieben. */
  check(/world:\s*["']MAIN["']/.test(BG),
        'background.js schiebt sie mit world: "MAIN" nach');
  check(/tinymce_moeglich/.test(PANEL) && /tinymce_moeglich/.test(EINFUEGEN),
        "und nur, wenn der erste Weg das nahelegt");
  // Die Diagnose muss beim Benutzer ankommen, nicht nur im Rueckgabewert.
  check(/r\.gesehen/.test(PANEL), "die Diagnose wird angezeigt");

  /* ⚠ DIE TAB-KENNUNG KOMMT AUS DEM ABSENDER, NIE AUS DER NACHRICHT. Eine
   * Nachricht kann aus jeder Seite kommen, in der das Panel steckt – stuende
   * die Kennung im Rumpf, waere sie ein Weg, in einen BELIEBIGEN offenen Tab zu
   * schreiben. */
  const editorFn = (bgOhne.match(/async function editorApi[\s\S]*?\n\}/) || [''])[0];
  check(/absender[\s\S]{0,40}\.tab[\s\S]{0,20}\.id/.test(editorFn),
        "die Tab-Kennung kommt aus dem Absender");
  check(!/nachricht\.tab/.test(editorFn) && !/nachricht\.tabId/.test(editorFn),
        "und NICHT aus der Nachricht");
}

// ═══════════════════════════════════════════════════════════════════════════
section("6d) Vorlagen und Ticketbezug (jetzt im Panel)");
// ═══════════════════════════════════════════════════════════════════════════
// Ein gemerkter Text zu Ticket A darf nicht unbemerkt in Ticket B landen –
// er geht am Ende an einen Kunden.
const panelOhne = ohneKommentare(PANEL);
check(/_fremdesErgebnis/.test(PANEL), "ein fremder Ticketbezug wird erkannt");
check(/if \(_fremdesErgebnis\)[\s\S]{0,240}await frageJaNein/.test(PANEL),
      "und beim Einfuegen zurueckgefragt");
check(!/\b(confirm|alert|prompt)\s*\(/.test(panelOhne),
      "die Rueckfrage ist ein eigener Dialog, kein confirm");
check(/jn-nein"\)\.focus\(\)/.test(PANEL),
      "der Fokus liegt auf Abbrechen (die gefaehrlichere Wahl loest kein Tastendruck aus)");

/* NEU MIT DEM PANEL: es ueberlebt einen Wechsel innerhalb der Anwendung. Der
 * Benutzer kann laengst bei Ticket B stehen, waehrend der Text zu A gehoert –
 * deshalb wird die Adresse ueberwacht, und die Warnung ist eine STEHENDE Zeile
 * und keine Meldung, die die naechste Aktion ueberschreibt. */
check(/setInterval/.test(panelOhne), "die Adresse wird ueberwacht");
check(/bezug-warnung/.test(PANEL) && /class="warnung"/.test(PANEL),
      "die Bezugswarnung ist ein eigenes, stehendes Element");
// `popstate` allein GENUEGT NICHT: eine Einzelseiten-Anwendung wechselt das
// Ticket per pushState, und das feuert kein Ereignis.
check(!/addEventListener\("popstate"/.test(panelOhne)
      || /setInterval/.test(panelOhne),
      "und nicht nur ueber popstate (pushState feuert keines)");

// Die Vorlage gilt nur fuer die Zusammenfassung – bei einem Antwortvorschlag
// waere sie eine zweite, widersprechende Aufgabe.
check(/modus === "zusammenfassung"\) \? \(\$\("f-vorlage"\)/.test(PANEL),
      "die Vorlage geht nur bei der Zusammenfassung mit");
// Namen sind Freitext aus einem Formular.
check(!/innerHTML\s*=\s*[^;]*\bv\.name\b/.test(PANEL),
      "Vorlagennamen gehen nicht durch innerHTML");
check(/o\.textContent = v\.name/.test(PANEL), "sondern durch textContent");

/* Drei Layout-Regeln, die NUR der Screenshot gezeigt hat. jsdom rechnet kein
 * Layout – geprüft wird deshalb die Regel, nicht das Ergebnis. Alle drei
 * ließen im 380 px breiten Fenster etwas herausragen, während die erste
 * Messung „kein Überlauf“ meldete: sie verglich Kinder mit ihren Eltern statt
 * das Dokument mit dem Viewport. */
const cssRegel = (quelle, sel) => {
  const m = new RegExp('(?:^|\\})\\s*' + sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
                       + '\\s*\\{([^}]*)\\}', 'm').exec(quelle);
  return m ? m[1] : '';
};
/* Die Arbeitsflaeche ist umgezogen, die Fallen sind mitgezogen: das Panel ist
 * ebenfalls 380 px breit und traegt jetzt die Knopfreihen und das
 * Kontrollkaestchen. Geprueft wird deshalb DORT, wo die Regel heute gilt. */
const panelCss = ohneKommentare((PANEL.match(/const STIL = `([\s\S]*?)`;/) || ['', ''])[1]);
check(panelCss.length > 500, 'die Gestaltung des Panels wurde gefunden',
      'Laenge ' + panelCss.length);
/* ⚠ ZWEIMAL PASSIERT: ein Rueckwaerts-Hochkomma in einem CSS-Kommentar beendet
 * das Template-Literal, und die Datei stirbt beim Laden mit einem
 * SyntaxError – also BEVOR das Panel entsteht. Der Waechter prueft das an der
 * geladenen Datei, nicht am Ausschnitt: `new Function` faellt darauf herein
 * wie der Browser. */
try {
  new Function(PANEL);
  check(true, 'panel.js ist syntaktisch gueltig (Template-Literale unversehrt)');
} catch (e) {
  check(false, 'panel.js ist syntaktisch gueltig (Template-Literale unversehrt)',
        String(e && e.message));
}
check(/width:\s*auto/.test(cssRegel(panelCss, 'input[type="checkbox"], input[type="radio"]')),
      'Kontrollkästchen sind nicht 100 % breit (sonst rutscht die Beschriftung um)');
check(/flex-wrap:\s*wrap/.test(cssRegel(panelCss, '.knopfreihe')),
      'Knopfreihen brechen um (zwei lange Beschriftungen passen nicht nebeneinander)');
check(/min-width:\s*0/.test(cssRegel(panelCss, '.marke')),
      'die Marke darf schrumpfen (Panel)');
check(/flex:\s*0 0 auto/.test(cssRegel(panelCss, '.kopf > button')),
      'der Schliessen-Knopf nicht (sonst schiebt ihn eine lange Ticketnummer hinaus)');
/* ⚠ `min-height: 0` ist Pflicht, nicht Kosmetik: ohne das schrumpft ein
 * Flex-Kind nicht unter seine Inhaltshoehe, `overflow-y` bleibt wirkungslos und
 * der Fuss wird aus dem Panel gedrueckt (Register). */
check(/min-height:\s*0/.test(cssRegel(panelCss, '.koerper'))
      && /overflow-y:\s*auto/.test(cssRegel(panelCss, '.koerper')),
      'der scrollende Bereich darf schrumpfen (min-height: 0)');
/* Was ueber Inhalt liegt, braucht eine DECKENDE Flaeche – darunter liegt die
 * Jira-Seite mit Text. */
check(/background:\s*var\(--grund\)/.test(cssRegel(panelCss, '.rahmen')),
      'das Panel ist deckend');
/* ⚠ EINE AUTOREN-REGEL SCHLAEGT DAS `hidden`-ATTRIBUT – im echten Chrome
 * gemessen: `.feld { display: block }` liess die Zeile "Fuer alle Benutzer
 * (Administrator)" trotz `hidden` stehen, obwohl der Benutzer kein Admin ist.
 * Dieselbe Falle wie `.sp-row[hidden]` im Hauptprojekt. jsdom rechnet kein
 * Layout und haette das NIE gemeldet – geprueft wird deshalb die Regel. */
for (const [wo, quelle] of [['Panel', panelCss], ['Popup', cssOhne]]) {
  check(/display:\s*none\s*!important/.test(cssRegel(quelle, '[hidden]')),
        wo + ': [hidden] wird gegen eigene display-Regeln durchgesetzt');
}
// Im Popup ist von den Layout-Fallen nur die Kopfzeile geblieben.
check(/min-width:\s*0/.test(cssRegel(cssOhne, '.marke')),
      'die Marke darf schrumpfen (Popup)');
check(/flex:\s*0 0 auto/.test(cssRegel(cssOhne, '.kopf > button')),
      'der Abmelden-Knopf nicht');
// ═══════════════════════════════════════════════════════════════════════════
/* Das Popup ist NUR noch Anmeldung und Einrichtung – die Arbeitsflaeche sitzt
 * im Panel. Zwei Fassungen derselben Oberflaeche waeren die Drift-Falle des
 * Projekts; ein Waechter haelt deshalb fest, dass die Arbeit dort NICHT mehr
 * steht. */
check(!/einfuegen\.js/.test(POPUP_HTML) && !/\bimport\b/.test(ohneKommentare(POPUP_JS)),
      "popup.js bindet einfuegen.js nicht mehr ein");
for (const [was, muster] of [["Auswerten", /art: "auswerten"/],
                             ["Einfuegen", /einfuegenInJira/],
                             ["Vorlagen", /art: "vorlagen"/]]) {
  check(!muster.test(POPUP_JS), "das Popup macht kein " + was + " mehr");
  check(muster.test(PANEL), "das Panel macht " + was);
}
// Aber der WEG dorthin muss im Popup stehen: nach dem Anmelden bietet es nichts
// mehr an, und niemand kaeme von selbst darauf, dass derselbe Knopf beim
// naechsten Klick etwas anderes tut.
check(/bereich-bereit/.test(POPUP_HTML) && /Symbol/.test(POPUP_HTML),
      "das Popup sagt nach der Anmeldung, wo gearbeitet wird");

// window.confirm/alert sind in Aufgabenfenstern unterdrueckt; in einem
// Extension-Popup funktionieren sie zwar, sehen aber wie ein Browserdialog der
// Seite aus. Eigene Meldungen statt Systemdialoge – wie im Rest des Projekts.
check(!/\b(confirm|alert|prompt)\s*\(/.test(ohneKommentare(POPUP_JS)),
      "keine Systemdialoge (confirm/alert/prompt)");
check(/https:\\?\/\\?\//.test(POPUP_JS) && /muss mit https/.test(POPUP_JS),
      "http wird abgelehnt – der Token darf nicht im Klartext reisen");
// Rueckmeldung ist Pflicht: in der Zwischenablage sieht man nichts.
check(/Kopieren fehlgeschlagen/.test(PANEL),
      "ein fehlgeschlagenes Kopieren wird gemeldet");
check(/Zwischenablage kopiert/.test(PANEL),
      "ein erfolgreiches Kopieren ebenfalls");

// Die Ticketnummer kommt aus der URL, nicht aus dem DOM (stabil ueber
// Jira-Versionen hinweg – und den Inhalt holt ohnehin der Server).
check(/\/browse\//.test(PANEL), "die Ticketnummer wird aus /browse/ gelesen");
check(!/document\.querySelector[^\n]*issue/i.test(PANEL),
      "die Ticketnummer wird NICHT aus dem Seiten-DOM geraten");

// ═══════════════════════════════════════════════════════════════════════════
section("7) Der Klick: Panel statt Popup – und der Weg zurueck");
// ═══════════════════════════════════════════════════════════════════════════
/* Ein Klick auf das Symbol soll das Panel in die Jira-Seite setzen. `onClicked`
 * feuert aber NUR, wenn kein Popup gesetzt ist – deshalb schaltet der
 * Hintergrund um. */
check(/action\.onClicked\.addListener/.test(bgOhne),
      "der Hintergrund reagiert auf den Klick");
check(/executeScript\(\{[\s\S]{0,200}files:/.test(bgOhne),
      "und injiziert Dateien in den Tab");
check(/setPopup\(\{\s*popup:[^}]*popup\.html/.test(bgOhne),
      "nicht angemeldet: das Anmeldefenster");

/* ⚠ DER AUFRUF MUSS IM MODULRUMPF STEHEN. Ein Service Worker wird beendet und
 * neu gestartet, und nach einem Browser-Neustart gilt wieder der Wert aus dem
 * Manifest. Haenge das Umschalten nur an einem Ereignis, saehe ein laengst
 * angemeldeter Benutzer irgendwann wieder die Anmeldemaske. */
check(/^popupNachziehen\(\);\s*$/m.test(bgOhne),
      "das Fenster wird bei JEDEM Start des Hintergrunds nachgezogen");

/* Und es muss an JEDER Aenderung der Sitzung haengen, nicht an den einzelnen
 * Stellen: sonst bleibt nach einem 401 das Panel eingestellt, und der Benutzer
 * hat keinen Weg zurueck zur Anmeldung. */
const sitzFn = (bgOhne.match(/async function sitzungSchreiben[\s\S]*?\n\}/) || [''])[0];
check(/popupNachziehen\(\)/.test(sitzFn),
      "jede Aenderung der Sitzung zieht das Fenster nach (auch der 401-Fall)");

// Fail-safe: eine frische Installation zeigt die Anmeldung, nicht ins Leere.
for (const [name, m] of [["Chrome", M_CHROME], ["Firefox", M_FF]]) {
  check((m.action || {}).default_popup === "popup.html",
        name + ": die Vorgabe im Manifest ist das Anmeldefenster");
}

/* Ein Klick, der WORTLOS nichts tut, ist das Schlimmste. Auf einer Seite ohne
 * Injektionsrecht (Browser-interne Seiten, PDF-Ansicht) gibt es von hier aus
 * kein Fenster – also Abzeichen und Beschriftung mit dem Grund. */
check(/setBadgeText/.test(bgOhne) && /setTitle/.test(bgOhne),
      "eine gescheiterte Injektion wird sichtbar gemeldet");

// ── Das Panel lebt in der Seite, nicht als dauerhaftes Content-Script ──────
check(/attachShadow\(\{\s*mode:\s*["']open["']\s*\}\)/.test(panelOhne),
      "das Markup liegt im Shadow DOM (kein Eingriff in Jiras Stilraum)");
// Genau EIN Element in der fremden Seite – der Rest haengt darunter.
const anhaenge = (panelOhne.match(/document\.body\.appendChild/g) || []).length;
check(anhaenge === 1, "genau ein Element wird an die Seite gehaengt",
      "gefunden: " + anhaenge);

/* ⚠ DRIFT-SCHRANKE. Die Dateiliste des Pakets steht an ZWEI Orten (bauen.sh
 * fuer die Kommandozeile, jira_assist.py fuer den Download aus der Oberflaeche).
 * Fehlt eine injizierte Datei im Paket, installiert sich die Erweiterung
 * klaglos und der Klick scheitert erst beim Benutzen – mit einer Meldung, die
 * niemand deutet. Geprueft wird die REGEL: was `executeScript` injiziert, MUSS
 * in beiden Listen stehen. */
const strings = (s) => (s.match(/"[^"]+\.(?:js|html|css)"/g) || [])
    .map((x) => x.slice(1, -1));
const injiziert = strings((bgOhne.match(/files:\s*\[[^\]]*\]/) || [''])[0]);
check(injiziert.length >= 2, "die injizierten Dateien wurden gefunden",
      injiziert.join(", "));
const listeBauen = strings((BAUEN.match(/DATEIEN = \[[^\]]*\]/) || [''])[0]);
const JIRA_PY = fs.readFileSync(path.join(WURZEL, "backend", "jira_assist.py"), "utf8");
const listeServer = strings((JIRA_PY.match(/PAKET_DATEIEN = \([^)]*\)/) || [''])[0]);
check(listeBauen.length > 0 && listeServer.length > 0, "beide Paketlisten gefunden");
check(JSON.stringify(listeBauen.slice().sort()) === JSON.stringify(listeServer.slice().sort()),
      "bauen.sh und jira_assist.py packen dieselben Dateien",
      listeBauen.join(",") + "  ≠  " + listeServer.join(","));
for (const d of injiziert) {
  check(listeBauen.includes(d), "injizierte Datei '" + d + "' liegt im Paket");
  check(fs.existsSync(path.join(ADDON, d)), "und existiert auf der Platte");
}

/* Der Hintergrund braucht `einfuegen.js` selbst – fuer den MAIN-Welt-Weg.
 * Chrome laeuft als Service Worker (`importScripts`), Firefox als Event Page
 * (KEIN Worker, dort steht die Datei im Manifest). Ein bedingungsloses
 * `importScripts` waere in Firefox ein ReferenceError beim Start. */
check(/typeof importScripts === "function"/.test(bgOhne),
      "importScripts wird nur benutzt, wo es das gibt (Chrome)");
check((M_FF.background.scripts || []).includes("einfuegen.js"),
      "Firefox laedt einfuegen.js ueber background.scripts");
check(M_FF.background.scripts.indexOf("einfuegen.js")
      < M_FF.background.scripts.indexOf("background.js"),
      "und zwar VOR background.js (sonst ist der Namensraum beim Start leer)");

// ═══════════════════════════════════════════════════════════════════════════
section("8) Die Ticketnummer-Erkennung – ausgefuehrt");
// ═══════════════════════════════════════════════════════════════════════════
{
  // keyAusUrl ist modulintern; sie wird wie im Browser neu ausgewertet.
  const m = PANEL.match(/function keyAusUrl\(url\)\s*\{[\s\S]*?\n  \}/);
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

// ═══════════════════════════════════════════════════════════════════════════
section("8b) Die Anleitung beschreibt das PANEL, nicht mehr das Popup");
// ═══════════════════════════════════════════════════════════════════════════
/* Eine Anleitung, die das alte Verhalten verspricht, ist schlimmer als keine:
 * der Benutzer sucht dann einen Fehler, den es nicht gibt. Geprueft werden
 * deshalb die INHALTE – dieselbe Lehre wie bei der Excel-Add-in-Anleitung. */
const ANLEITUNG = fs.readFileSync(path.join(WURZEL, "frontend", "jira_addon.html"), "utf8");
const I18N = fs.readFileSync(path.join(WURZEL, "frontend", "js", "i18n.js"), "utf8");
const DOKU = ANLEITUNG + I18N + fs.readFileSync(path.join(ADDON, "README.md"), "utf8");

/* Die vier Zusagen, die der Umbau UMGEDREHT hat. Jede stand woertlich in der
 * Anleitung und ist heute falsch. */
for (const [was, muster] of [
  ["ein Klick daneben beende die Auswertung", /Klick daneben schließt es/],
  ["das Fenster muesse offen bleiben", /Solange muss das Fenster offen bleiben/],
  ["clicking elsewhere aborts", /clicking elsewhere closes it/],
  ["the window has to stay open", /The window has to stay open/],
]) {
  check(!muster.test(DOKU), "die Anleitung behauptet nicht mehr, " + was);
}

/* Und die Anmeldung ueberlebt den Browser seit dem Wechsel auf storage.local –
 * die Anleitung behauptete jahrelang das Gegenteil. Der Test bindet beides
 * aneinander: solange der Hintergrund storage.local benutzt, darf dort nicht
 * "bis zum Schliessen des Browsers" stehen. */
if (/storage\.local/.test(bgOhne)) {
  check(!/gilt bis zum Schließen des Browsers/.test(DOKU)
        && !/lasts until you close the browser/.test(DOKU),
        "die Anleitung behauptet keine Anmeldung, die mit dem Browser endet");
}

// Umgekehrt MUSS der neue Weg beschrieben sein – in beiden Sprachen.
for (const [was, muster] of [
  ["dass der Assistent in der Jira-Seite erscheint", /rechts in der Jira-Seite/],
  ["dasselbe auf Englisch", /right-hand side of the Jira page/],
  ["was beim Ticketwechsel passiert", /jaddon\.use_warn/],
  ["dass ein Neuladen das Fenster abraeumt", /jaddon\.tr5_q/],
]) {
  check(muster.test(DOKU), "die Anleitung sagt, " + was);
}
check(/panel\.js/.test(fs.readFileSync(path.join(ADDON, "README.md"), "utf8")),
      "die Entwickler-Anleitung fuehrt panel.js im Aufbau");

// ═══════════════════════════════════════════════════════════════════════════
// 9) DAS PANEL GEGEN EIN NACHGEBAUTES JIRA – WIRKLICH AUSGEFUEHRT
// ═══════════════════════════════════════════════════════════════════════════
/* Ein Quelltext-Test belegt hier nichts. Das Panel baut sich in einer FREMDEN
 * Seite auf, redet ueber `runtime.sendMessage` mit dem Hintergrund und schreibt
 * am Ende in ein Feld, das jemand anderes gerendert hat – ob das traegt, sieht
 * man nur, wenn man es tut.
 *
 * Die Erweiterungs-API wird gestellt, alles andere ist der echte Code. */

// CSS-Meldungen von jsdom sind Rauschen (es kennt `color-mix` nicht) – echte
// Skriptfehler sollen aber sichtbar bleiben.
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => {
  const m = String((e && e.message) || e);
  if (!/Could not parse CSS|Error: Not implemented/i.test(m)) console.log("  [jsdom] " + m);
});

const warte = (ms) => new Promise((r) => setTimeout(r, ms));
const ERG_TEXT = "Guten Tag,\n\ndas Problem ist behoben.\n\nViele Grüße";

function panelBau(seite, opts) {
  const o = opts || {};
  const dom = new JSDOM("<!DOCTYPE html><html><head></head><body>" + seite + "</body></html>", {
    url: o.url || "https://jira.test/browse/ABC-1",
    runScripts: "outside-only",
    virtualConsole: vc,
  });
  const w = dom.window;
  // jsdom rechnet kein Layout – ohne das haelt die Suche JEDES Feld fuer
  // unsichtbar. Gemessen wird die echte Logik, nur die Geometrie wird gestellt.
  w.Element.prototype.getBoundingClientRect = function () {
    return this.hasAttribute("data-unsichtbar")
      ? { width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 }
      : { width: 300, height: 80, top: 0, left: 0, right: 300, bottom: 80 };
  };
  w.Element.prototype.scrollIntoView = function () {};
  w.document.execCommand = () => false;

  const gesendet = [];
  const antw = Object.assign({
    zustand: { ok: true, basis: "https://dp.test", angemeldet: true, ergebnis: null },
    branding: { ok: true, daten: null },
    vorlagen: { ok: true, daten: { global: [], eigene: [], darf_global: false } },
    auswerten: (m) => ({ ok: true, daten: { key: m.key, modus: m.modus,
                                            text: ERG_TEXT, kommentare: 7,
                                            modell: "qwen3.6-35b" } }),
  }, o.antworten || {});
  w.chrome = {
    runtime: {
      sendMessage: (m) => {
        gesendet.push(m);
        const f = antw[m && m.art];
        const a = (typeof f === "function") ? f(m) : f;
        return Promise.resolve(a === undefined ? { ok: true } : a);
      },
    },
  };

  // Ein vergessener Taktgeber laeuft im Jira-Tab des Benutzers weiter – das
  // wird gezaehlt, nicht geglaubt.
  const takt = { auf: 0, zu: 0 };
  const si = w.setInterval.bind(w), ci = w.clearInterval.bind(w);
  w.setInterval = function (fn, ms) { takt.auf++; return si(fn, ms); };
  w.clearInterval = function (id) { takt.zu++; return ci(id); };

  const laden = () => new w.Function(EINFUEGEN + "\n;\n" + PANEL)();
  const wirt = () => w.document.getElementById("jv-assist-panel");
  const s = (id) => { const h = wirt(); return h && h.shadowRoot.getElementById(id); };
  return { dom, w, gesendet, takt, laden, wirt, s };
}

/** Ein Lauf – ein Wurf darf ihn nicht ABBRECHEN, sonst sieht ein Fehler aus wie
 * "nicht gelaufen" und eine Gegenprobe waere gruen aus dem falschen Grund. */
async function mitPanel(titel, seite, opts, arbeit) {
  const u = panelBau(seite, opts);
  try {
    u.laden();
    await warte(5);
    await arbeit(u);
  } catch (e) {
    check(false, titel, String((e && e.stack) || e));
  } finally {
    u.w.close();
  }
}

(async () => {
  section("9) Das Panel gegen ein nachgebautes Jira – ausgefuehrt");

  // a) Es haengt GENAU EIN Element in die fremde Seite, alles andere darunter.
  await mitPanel("Aufbau", '<div id="jira"><textarea id="comment"></textarea></div>',
                 null, async (u) => {
    const koerper = u.w.document.body;
    check(koerper.children.length === 2,
          "genau ein Element kommt zur Seite hinzu", "Kinder: " + koerper.children.length);
    check(!!u.wirt() && !!u.wirt().shadowRoot, "und es traegt einen Shadow DOM");
    check(u.w.document.head.querySelectorAll("style, link").length === 0,
          "die Gestaltung landet NICHT im Kopf der Jira-Seite");
    check(u.w.document.getElementById("comment").value === "",
          "die Seite selbst bleibt unberuehrt");
    // Der Ticketbezug steht sichtbar in der Kopfzeile.
    check(u.s("ticket").textContent === "ABC-1",
          "die Ticketnummer aus der Adresse steht im Kopf", u.s("ticket").textContent);
  });

  // b) Auswerten fragt den HINTERGRUND – mit der Nummer aus der Adresse.
  await mitPanel("Auswerten", '<textarea id="comment"></textarea>', null, async (u) => {
    u.s("btn-zus").click();
    await warte(5);
    const auf = u.gesendet.filter((m) => m.art === "auswerten");
    check(auf.length === 1 && auf[0].key === "ABC-1"
          && auf[0].modus === "zusammenfassung",
          "der Auftrag geht mit der richtigen Ticketnummer an den Hintergrund",
          JSON.stringify(auf));
    check(u.s("f-ergebnis").value === ERG_TEXT, "das Ergebnis steht im Feld");
    check(!u.s("ergebnis").hidden, "und der Bereich ist sichtbar");
    // Was das Ergebnis TRAEGT, gehoert sichtbar dazu.
    const fuss = u.s("ergebnis-fuss").textContent;
    check(/ABC-1/.test(fuss) && /7 Kommentar/.test(fuss) && /qwen/.test(fuss),
          "die Fussnote nennt Ticket, Kommentarzahl und Modell", fuss);
  });

  // c) ENDE ZU ENDE: der Text landet im Kommentarfeld DERSELBEN Seite.
  await mitPanel("Einfuegen", '<form><textarea id="comment"></textarea></form>',
                 null, async (u) => {
    u.s("btn-zus").click();
    await warte(5);
    u.s("btn-einfuegen").click();
    await warte(5);
    check(u.w.document.getElementById("comment").value === ERG_TEXT,
          "der Vorschlag steht im Kommentarfeld der Jira-Seite");
    check(/Eingefügt/.test(u.s("meldung").textContent),
          "und der Erfolg wird gemeldet", u.s("meldung").textContent);
  });

  /* d) DER EIGENTLICHE GEWINN DES UMBAUS – und die Falle, die er mitbringt.
   *
   * Das zuletzt fokussierte Feld schlaegt jede Selektorliste. Sobald der
   * Benutzer aber im Panel klickt, ist `document.activeElement` der Panel-Wirt.
   * Ohne das gemerkte Feld faellt die Suche auf die Selektorliste zurueck und
   * schreibt in den ERSTBESTEN Editor – hier also in den WYSIWYG-Kasten statt
   * in das Feld, in dem der Benutzer wirklich stand. */
  await mitPanel("Gemerktes Feld",
                 '<div class="jira-editor-container">'
                 + '<div contenteditable="true" id="wysiwyg"></div></div>'
                 + '<textarea id="notiz"></textarea>', null, async (u) => {
    const notiz = u.w.document.getElementById("notiz");
    notiz.dispatchEvent(new u.w.FocusEvent("focusin", { bubbles: true }));
    // Klick ins Panel: der Fokus liegt danach auf dem Wirt.
    Object.defineProperty(u.w.document, "activeElement",
                          { value: u.wirt(), configurable: true });
    u.s("btn-zus").click();
    await warte(5);
    u.s("btn-einfuegen").click();
    await warte(5);
    check(notiz.value === ERG_TEXT,
          "der Text landet in dem Feld, in dem der Benutzer zuletzt war");
    check(u.w.document.getElementById("wysiwyg").textContent === "",
          "und NICHT im erstbesten Editor der Selektorliste");
  });

  /* e) Ein Klick auf die Formatierleiste darf das gemerkte Feld nicht
   *    verdraengen – sonst waere die Regel nach dem ersten Fettdruck tot. */
  await mitPanel("Fremder Fokus",
                 '<textarea id="comment"></textarea><button id="fett">B</button>',
                 null, async (u) => {
    const feld = u.w.document.getElementById("comment");
    feld.dispatchEvent(new u.w.FocusEvent("focusin", { bubbles: true }));
    u.w.document.getElementById("fett")
      .dispatchEvent(new u.w.FocusEvent("focusin", { bubbles: true }));
    Object.defineProperty(u.w.document, "activeElement",
                          { value: u.wirt(), configurable: true });
    u.s("btn-zus").click();
    await warte(5);
    u.s("btn-einfuegen").click();
    await warte(5);
    check(feld.value === ERG_TEXT,
          "ein Knopf der Seite verdraengt das gemerkte Kommentarfeld nicht");
  });

  /* f) DER TICKETBEZUG BEIM WECHSEL – das ist neu, weil das Panel stehen
   *    bleibt. `popstate` feuert bei pushState NICHT; die Adresse wird deshalb
   *    ueberwacht. Der Test wartet die echte Taktzeit ab, statt einen Aufruf
   *    nachzubauen. */
  await mitPanel("Adresswechsel", '<textarea id="comment"></textarea>', null, async (u) => {
    u.s("btn-zus").click();
    await warte(5);
    check(u.s("bezug-warnung").hidden, "beim eigenen Ticket steht keine Warnung");

    u.w.history.pushState({}, "", "/browse/DEF-2");
    await warte(1300);
    check(u.s("ticket").textContent === "DEF-2",
          "nach dem Wechsel steht die neue Nummer im Kopf", u.s("ticket").textContent);
    const w = u.s("bezug-warnung");
    check(!w.hidden && /ABC-1/.test(w.textContent) && /DEF-2/.test(w.textContent),
          "und eine stehende Warnung nennt BEIDE Nummern", w.textContent);

    // Einfuegen fragt jetzt zurueck – und ABBRECHEN fuegt nichts ein.
    u.s("btn-einfuegen").click();
    await warte(5);
    check(!u.s("ja-nein").hidden, "Einfuegen fragt zurueck");
    check(u.w.document.getElementById("comment").value === "",
          "und hat bis dahin nichts geschrieben");
    u.s("jn-nein").click();
    await warte(5);
    check(u.w.document.getElementById("comment").value === "",
          "nach Abbrechen bleibt das Kommentarfeld leer");

    u.s("btn-einfuegen").click();
    await warte(5);
    u.s("jn-ja").click();
    await warte(5);
    check(u.w.document.getElementById("comment").value === ERG_TEXT,
          "erst die ausdrueckliche Bestaetigung fuegt ein");
  });

  // g) Ein GEMERKTES Ergebnis zu einem anderen Ticket warnt schon beim Oeffnen.
  await mitPanel("Gemerktes fremdes Ergebnis", '<textarea id="comment"></textarea>',
                 { antworten: { zustand: { ok: true, basis: "https://dp.test",
                     angemeldet: true,
                     ergebnis: { key: "DEF-2", modus: "antwort", text: ERG_TEXT,
                                 kommentare: 3, zeit: Date.now() } } } },
                 async (u) => {
    check(u.s("f-ergebnis").value === ERG_TEXT, "das gemerkte Ergebnis ist wieder da");
    const w = u.s("bezug-warnung");
    check(!w.hidden && /DEF-2/.test(w.textContent) && /ABC-1/.test(w.textContent),
          "und der fremde Bezug steht sofort sichtbar da", w.textContent);
  });

  // h) Kein Ticket im Tab: Auskunft statt Fehlversuch.
  await mitPanel("Kein Ticket", '<div>Dashboard</div>',
                 { url: "https://jira.test/secure/Dashboard.jspa" }, async (u) => {
    check(/Kein Jira-Ticket/.test(u.s("meldung").textContent),
          "das Panel sagt, dass dieser Tab kein Ticket ist");
    u.s("btn-zus").click();
    await warte(5);
    check(u.gesendet.filter((m) => m.art === "auswerten").length === 0,
          "und schickt keinen Auftrag ohne Ticketnummer los");
  });

  // i) Nicht angemeldet: keine Arbeitsknoepfe, aber ein Weg hinaus.
  await mitPanel("Nicht angemeldet", '<textarea id="comment"></textarea>',
                 { antworten: { zustand: { ok: true, basis: "", angemeldet: false,
                                           ergebnis: null } } }, async (u) => {
    check(/Nicht angemeldet/.test(u.s("meldung").textContent),
          "das Panel sagt, dass keine Anmeldung vorliegt");
    check(u.s("btn-zus").disabled && u.s("btn-einfuegen").disabled,
          "die Arbeitsknoepfe sind gesperrt");
    check(!u.s("btn-zu").disabled, "der Schliessen-Knopf bleibt bedienbar");
  });

  // j) Vorlagennamen sind Freitext aus einem Formular – kein Markup.
  await mitPanel("Vorlagennamen", '<textarea id="comment"></textarea>',
                 { antworten: { vorlagen: { ok: true, daten: {
                     global: [], darf_global: false,
                     eigene: [{ id: "1", name: '<img src=x onerror=alert(1)>Kurz',
                                text: "kurz" }] } } } }, async (u) => {
    u.s("btn-vorlagen").click();
    await warte(5);
    /* Gezaehlt wird IN DER LISTE, nicht im ganzen Panel: der Kopf traegt ein
     * eigenes <img> fuer das Logo – eine Zaehlung ueber alles haette hier einen
     * Fehler gemeldet, den es nicht gibt. */
    check(u.s("vorl-liste").querySelectorAll("img, script").length === 0
          && u.s("f-vorlage").querySelectorAll("img, script").length === 0,
          "eingeschleustes Markup wird NICHT als HTML uebernommen");
    check(/onerror/.test(u.s("vorl-liste").textContent),
          "der Name steht als Text da", u.s("vorl-liste").textContent);
  });

  // k) Der zweite Klick schliesst – und laesst nichts zurueck.
  await mitPanel("Schliessen", '<textarea id="comment"></textarea>', null, async (u) => {
    check(u.takt.auf === 1, "das Panel setzt genau einen Taktgeber",
          "auf: " + u.takt.auf);
    u.laden();                       // zweiter Klick auf das Symbol
    await warte(5);
    check(u.wirt() === null, "der zweite Klick blendet das Panel wieder aus");
    check(u.w.document.body.children.length === 1,
          "und laesst die Seite so zurueck, wie sie war");
    check(u.takt.zu === 1, "der Taktgeber wird abgeraeumt (kein Nachlauf im Tab)",
          "zu: " + u.takt.zu);
  });

  console.log("\n" + ok + " OK, " + fail + " FAIL");
  process.exit(fail ? 1 : 0);
})();
