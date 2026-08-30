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
    check(ohneTicket.zeilenGesperrt === true,
          'ohne Ticket sind auch die frisch gezeichneten Zeilen-Knoepfe gesperrt');
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
     'zeige', 'start', 'markeAnwenden'],
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
  const laufMit = async (tabKey, gemerkt, klickLeeren) => {
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
      const f = new w.Function('tabKey', 'gemerkt', 'klickLeeren', `
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
          const _originale = new Map();
          let _jiraBasis = "";
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
              text: el.ergebnisFeld.value,
              sichtbar: !el.ergebnis.hidden,
              fuss: el.ergebnisFuss.textContent,
              hinweis: el.hinweis.value,
              meldung: el.meldung.hidden ? "" : el.meldung.textContent,
              geloescht: gesendet.some(n => n && n.art === "ergebnis_merken"
                                            && n.wert === null),
            });
          })();`);
      return JSON.parse(await f(tabKey, gemerkt, klickLeeren));
    } finally { w.close(); }
  };

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
  const anwenden = bgTeil("ansichtAnwenden");
  check(!!anwenden && !!bgTeil("aktion"),
        "background.js hat ansichtAnwenden() und aktion()");
  /* Der Pfad ist eine Modul-Konstante und gehoert in den Schnitt. Fehlte er,
   * warf `ansichtAnwenden` - und weil dort JEDER Schritt einzeln abgesichert
   * ist, verschwand der Fehler im leeren catch: der Lauf meldete FAIL und es
   * sah nach einem Codefehler aus, war aber ein Testmangel. */
  const PFAD_ZEILE = (BG.match(/const LEISTE_PFAD = "[^"]+";/) || [""])[0];
  check(/\?ansicht=leiste/.test(PFAD_ZEILE),
        "background.js kennt den Leisten-Pfad", PFAD_ZEILE);

  const laufAnsicht = async (modus, welt) => {
    const spur = [];
    const a = {
      action: { setPopup: async (o) => { spur.push(["popup", o.popup]); } },
    };
    if (welt === "chrome") {
      a.sidePanel = {
        setOptions: async (o) => { spur.push(["optionen", o.path, o.enabled]); },
        setPanelBehavior: async (o) => {
          spur.push(["verhalten", o.openPanelOnActionClick]); },
      };
    } else {
      a.sidebarAction = {
        setPanel: async (o) => { spur.push(["panel", o.panel]); },
      };
      a.runtime = { getURL: (p) => "moz-extension://x/" + p };
    }
    await new Function("api", PFAD_ZEILE + "\n" + anwenden + "\n" + bgTeil("aktion")
                       + "\nreturn ansichtAnwenden(" + JSON.stringify(modus) + ");")(a);
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
      ["tabWechsel"], ["tabErmitteln", "frage"]);
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
            let _jiraBasis = "", _leiste_unbenutzt = 0;
            const _leiste = true;
            let _tabUrl = "https://jira.test/browse/" + (nachKey || "X-1");
            let _windowId = 7, _tabId = 1;
            const api = { permissions: { contains: async () => true } };
            async function frage(n) { gesendet.push(n); return { ok: true }; }
            async function tabErmitteln() {
              _key = nachKey; el.ticket.textContent = _key || "";
            }
` + t2.join("\n") + `
            return (async () => {
              el.ergebnisFeld.value = (gemerkt && gemerkt.text) || "";
              el.ergebnis.hidden = !(gemerkt && gemerkt.text);
              await tabWechsel();
              return JSON.stringify({
                text: el.ergebnisFeld.value,
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
    check(!!az && /kasten\.disabled = !moeglich/.test(az),
          "kann der Browser keine Leiste, ist sie gesperrt statt verborgen");
    check(!!az && /Chrome\/Edge ab 114|ab 114/.test(az),
          "und der Hinweis nennt den Grund");
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
    const lo = schneidePopup("leisteOeffnen");
    /* ⚠ JEDER Zweig muss warten, nicht irgendeiner. Die erste Fassung dieser
     * Pruefung suchte `await api.(sidePanel|sidebarAction)` - mit zwei Zweigen
     * blieb sie gruen, obwohl in einem das `await` fehlte, und die Gegenprobe
     * biss nicht. Geprueft wird jetzt die Eigenschaft: KEIN `open(` ohne
     * unmittelbar davorstehendes `await`. */
    const offeneAufrufe = (lo || "").match(/(\w+\s+)?api\.\w+\.open\(/g) || [];
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
   * auseinander. Geprueft wird die REGEL. */
  const AUSNAHMEN = [...POPUP_HTML.matchAll(
    /<button[^>]*\bid="([^"]+)"[^>]*data-ohne-ticket/g)].map((m) => m[1])
    .concat([...POPUP_HTML.matchAll(
      /<button[^>]*data-ohne-ticket[^>]*\bid="([^"]+)"/g)].map((m) => m[1]));
  const ausnahme = new Set(AUSNAHMEN);
  check(ausnahme.size >= 6,
        "im Markup sind die Ausnahmen gekennzeichnet", [...ausnahme].join(", "));

  /* DIE VIER, DIE DRINSTEHEN MUESSEN - und jede aus einem eigenen Grund.
   * Sie sind hier namentlich genannt, weil ihr Fehlen ein Einbahnstrassen-
   * Zustand waere: nicht hineinkommen, nicht hinaus, Dialog nicht schliessbar. */
  for (const [id, grund] of [
    ["btn-anmelden", "sonst kaeme man von einem fremden Tab aus nie hinein"],
    ["btn-abmelden", "sonst nie hinaus"],
    ["btn-vorlagen-zu", "ein Dialog, den man nicht wegbekommt, ist eine Falle"],
    ["jn-nein", "dito fuer die Rueckfrage beim Einfuegen"],
  ]) {
    check(ausnahme.has(id), id + " bleibt bedienbar - " + grund);
  }

  {
    const r = lageBei("", false, false);
    const gesperrt = Object.entries(r.zustand).filter(([, d]) => d).map(([i]) => i);
    const offen = Object.entries(r.zustand).filter(([, d]) => !d).map(([i]) => i);
    check(offen.every((id) => ausnahme.has(id)),
          "ohne Ticket ist NUR noch offen, was ausdruecklich ausgenommen ist",
          offen.join(", "));
    check(gesperrt.every((id) => !ausnahme.has(id)) && gesperrt.length >= 8,
          "alles uebrige ist gesperrt", gesperrt.length + ": " + gesperrt.join(", "));
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

console.log("\n" + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
})();
