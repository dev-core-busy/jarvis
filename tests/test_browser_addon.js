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
check(!/ergebnisFeld\.value\s*=[^;]*hinweis/.test(popupOhne),
      "er wird NICHT in das bearbeitbare Feld geschrieben");
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
check(/_fremdesErgebnis && !\(await frageJaNein\(\)\)/.test(POPUP_JS),
      "und beim Einfuegen zurueckgefragt");
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

console.log("\n" + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
