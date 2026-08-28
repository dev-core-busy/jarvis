#!/usr/bin/env node
/* Waechter fuer die Anleitungsseite /jira-addon und den Jira-Reiter.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT: der Bezugsblock ("Paket holen") wird seit
 * 2026-08-28 vom Skript GEBAUT, nicht mehr ins Markup geschrieben. Geprueft
 * wurde das zuerst nur mit Regexen ueber den Quelltext – und ein Quelltext-Test
 * beantwortet die eine Frage nicht, auf die es ankommt: **steht am Ende ein
 * Knopf da?** Genau diese Frage hat der Betrieb gestellt ("JETZT GEHT GAR KEIN
 * DOWNLOAD MEHR").
 *
 * Hier wird die echte Seite mit dem echten Skript in jsdom ausgefuehrt und
 * anschliessend GEZAEHLT, was im DOM steht.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const WURZEL = path.resolve(__dirname, "..");
const HTML = fs.readFileSync(path.join(WURZEL, "frontend/jira_addon.html"), "utf8");
const JS = fs.readFileSync(path.join(WURZEL, "frontend/js/jira_addon.js"), "utf8");
const SETTINGS = fs.readFileSync(path.join(WURZEL, "frontend/settings.html"), "utf8");
const JIRA_JS = fs.readFileSync(path.join(WURZEL, "frontend/js/jira.js"), "utf8");
const I18N = fs.readFileSync(path.join(WURZEL, "frontend/js/i18n.js"), "utf8");

let ok = 0, fail = 0;
function check(bed, text, extra) {
  if (bed) { ok++; console.log("  OK   " + text); }
  else { fail++; console.log("  FAIL " + text + (extra ? " – " + extra : "")); }
}
function section(t) { console.log("\n═══ " + t); }

/** Laedt die Seite, laesst das Skript laufen und gibt das Ergebnis zurueck. */
async function seite({ pfade = null, istAdmin = false, healthOk = true,
                       healthWirft = false, zert = null } = {}) {
  const dom = new JSDOM(HTML, { url: "https://jarvis.test/jira-addon",
                                runScripts: "outside-only" });
  const w = dom.window;
  w.localStorage.setItem("jarvis_token", "T");
  const gerufen = [];
  w.fetch = async (url, opt) => {
    const p = String(url).split("?")[0];
    gerufen.push(String(url));
    if (p === "/api/me") {
      return { ok: true, json: async () => ({
        permissions: { jira_assist: true }, is_admin: istAdmin }) };
    }
    if (p === "/api/jira/assist/health") {
      if (healthWirft) throw new Error("Netz weg");
      if (!healthOk) return { ok: false, json: async () => ({}) };
      return { ok: true, json: async () => Object.assign({
        ok: true, jira_konfiguriert: true,
        paket_pfade: pfade || { chrome: "", firefox: "" } }, zert || {}) };
    }
    if (p === "/api/jira/assist/paket") {
      return { ok: true, blob: async () => new w.Blob(["x"]) };
    }
    return { ok: true, json: async () => ({}) };
  };
  const fehler = [];
  w.addEventListener("error", (e) => fehler.push(String(e.message)));
  try { w.eval(JS); } catch (e) { fehler.push("eval: " + e.message); }
  await new Promise((r) => setTimeout(r, 60));
  return { w, gerufen, fehler, box: w.document.getElementById("ja-paket") };
}

(async () => {

// ═══════════════════════════════════════════════════════════════════════════
section("1) OHNE Netzwerkpfad steht ein DOWNLOAD-Knopf da – in jeder Lage");
// ═══════════════════════════════════════════════════════════════════════════
/* Das ist die Regressionsprobe zum gemeldeten Fehler. Der Block wird gebaut;
 * faellt irgendetwas davor aus, bliebe er LEER – und die Seite saehe aus, als
 * gaebe es das Paket nicht mehr. Deshalb werden auch die Fehlerlagen geprueft:
 * ein 403 oder ein Netzausfall darf den Bezugsweg nicht mitnehmen. */
for (const [name, lage] of [
  ["Normalfall", {}],
  ["health antwortet 403", { healthOk: false }],
  ["health faellt aus", { healthWirft: true }],
]) {
  const { box, fehler } = await seite(lage);
  check(!!box, name + ": der Platz fuer das Paket existiert");
  const knoepfe = box ? box.querySelectorAll("button") : [];
  check(knoepfe.length === 2, name + ": ZWEI Download-Knoepfe",
        "gezaehlt: " + knoepfe.length);
  check(!!(box && box.querySelector("#ja-dl-chrome")
           && box.querySelector("#ja-dl-firefox")),
        name + ": beide Varianten sind dabei");
  check(fehler.length === 0, name + ": kein Skriptfehler", fehler.join("; "));
}

// Der Klick muss den Endpunkt wirklich rufen – ein Knopf, der nichts tut, ist
// dasselbe wie kein Knopf.
{
  const { w, box, gerufen } = await seite({});
  box.querySelector("#ja-dl-chrome").click();
  await new Promise((r) => setTimeout(r, 30));
  check(gerufen.some((u) => u.indexOf("/api/jira/assist/paket") === 0),
        "der Klick ruft den Paket-Endpunkt", gerufen.join(" | "));
  check(gerufen.some((u) => u.indexOf("variante=chrome") > 0),
        "und nennt die Variante");
  w.close();
}

// ═══════════════════════════════════════════════════════════════════════════
section("2) MIT Netzwerkpfad: der Pfad ersetzt den Download");
// ═══════════════════════════════════════════════════════════════════════════
const PFADE = { chrome: "\\\\srv\\freigabe\\jira-chrome",
                firefox: "\\\\srv\\freigabe\\jira-firefox.zip" };
{
  const { w, box } = await seite({ pfade: PFADE });
  const zeilen = box.querySelectorAll(".ja-pfad");
  check(zeilen.length === 2, "beide Pfade stehen da", "gezaehlt: " + zeilen.length);
  check(box.querySelectorAll("#ja-dl-chrome, #ja-dl-firefox").length === 0,
        "und KEIN Download-Knopf mehr (der Benutzer laedt nichts herunter)");
  const wert = box.querySelector(".ja-pfad-wert");
  check(wert && wert.textContent === PFADE.chrome,
        "der Pfad steht unveraendert im Text", wert && wert.textContent);
  w.close();
}

// Nur EINE Variante konfiguriert: die andere behaelt ihren Download.
{
  const { w, box } = await seite({ pfade: { chrome: PFADE.chrome, firefox: "" } });
  check(box.querySelectorAll(".ja-pfad").length === 1
        && !!box.querySelector("#ja-dl-firefox"),
        "je Variante entschieden: Pfad hier, Knopf dort");
  w.close();
}

// Der Pfad ist Fremdeingabe aus einem Formular – er darf kein Markup werden.
{
  const boese = '\\\\srv\\<img src=x onerror=alert(1)>';
  const { w, box } = await seite({ pfade: { chrome: boese, firefox: "" } });
  check(box.querySelectorAll("img").length === 0,
        "eingeschleustes Markup wird NICHT als HTML uebernommen");
  check(box.querySelector(".ja-pfad-wert").textContent === boese,
        "sondern als Text angezeigt");
  w.close();
}

// ═══════════════════════════════════════════════════════════════════════════
section("3) Die Anleitung verweist auf den ORDNER, sie laesst nichts kopieren");
// ═══════════════════════════════════════════════════════════════════════════
/* Gemeldet: "DU SOLLST AUF DEN ORDNER VERWEISEN, DER VOM ADMIN KONFIGURIERT
 * WURDE. Der Benutzer muss nichts mehr downloaden." Zutreffend – eine erste
 * Fassung liess den Benutzer den Ordner erst lokal kopieren. */
/* ⚠ GEPRUEFT WERDEN DIE BETROFFENEN SCHLUESSEL, nicht die ganze Datei: "local
 * folder" steht auch in `kbsync.hint` und hat dort nichts mit dieser Anleitung
 * zu tun. Ein Suchlauf ueber i18n.js meldete deshalb beim ersten Mal einen
 * Fehler, den es nicht gab. */
const ANLEITUNG = (I18N.match(/'jaddon\.inst_[a-z0-9_]+':\s*'[^']*'/g) || []).join("\n");
check(ANLEITUNG.length > 200, "die Anleitungs-Schluessel wurden gefunden",
      "nur " + ANLEITUNG.length + " Zeichen");
for (const wort of ["lokalen Ordner", "dorthin <b>kopieren</b>", "local folder"]) {
  check(ANLEITUNG.indexOf(wort) < 0,
        "die Anleitung sagt NICHT mehr '" + wort + "'");
}
const CH1 = /'jaddon\.inst_chrome_1':\s*'([^']*)'/.exec(I18N);
check(!!CH1 && /nichts vorzubereiten/.test(CH1[1]),
      "Schritt 1 sagt: bei Netzwerkpfad ist nichts vorzubereiten",
      CH1 && CH1[1].slice(0, 70));
const CH4 = /'jaddon\.inst_chrome_4':\s*'([^']*)'/.exec(I18N);
check(!!CH4 && /Schritt&nbsp;1/.test(CH4[1]),
      "und 'Entpackt laden' verweist auf genau diesen Ordner");

// ═══════════════════════════════════════════════════════════════════════════
section("4) Der Administrator kommt an die ZIPs – im Jira-Reiter, IMMER");
// ═══════════════════════════════════════════════════════════════════════════
/* Gemeldet: "es existiert keine Möglichkeit, die beiden ZIPs durch den admin
 * herunterzuladen". Der Knopf hing vorher in der Anleitung hinter ZWEI
 * Bedingungen (Pfad gesetzt UND Admin) – faktisch war er nicht vorhanden.
 * Jetzt steht er dort, wo der Administrator die Freigabe pflegt, und haengt an
 * gar keiner Bedingung. */
check(SETTINGS.indexOf('id="jshare-dl-chrome"') > 0
      && SETTINGS.indexOf('id="jshare-dl-firefox"') > 0,
      "beide Knoepfe stehen im Jira-Reiter");
const iShare = SETTINGS.indexOf('id="ji-sect-share"');
const iChrome = SETTINGS.indexOf('id="jshare-dl-chrome"');
check(iShare > 0 && iChrome > iShare,
      "und zwar im Abschnitt 'Browser Plugin Bereitstellung'");
// Sie duerfen NICHT an den Pfad gekoppelt sein – sonst ist die Datei genau
// dann unerreichbar, wenn man sie zum Einrichten braucht.
check(!/jshare-dl-chrome[\s\S]{0,400}(hidden|display:\s*none)/.test(SETTINGS),
      "sie starten nicht versteckt");
check(/ladePaket:\s*function/.test(JIRA_JS), "jira.js kann das Paket holen");
check(/\/api\/jira\/assist\/paket/.test(JIRA_JS), "und ruft den richtigen Endpunkt");
check(/jshare-dl-\.?\s*\+?\s*v|jshare-dl-' \+ v/.test(JIRA_JS)
      || /jshare-dl-/.test(JIRA_JS), "die Knoepfe sind verdrahtet");
// Kein Token in der URL – es landet sonst im Verlauf und in Proxy-Logs.
check(!/paket\?[^'"]*token=/.test(JIRA_JS), "kein Token in der Adresse");
check(/authHeaders\(\)/.test(JIRA_JS), "sondern im Authorization-Kopf");
// Rueckmeldung ist Pflicht: ein Download, der scheitert, ist sonst unsichtbar.
check(/jshare-dl-status/.test(JIRA_JS) && /catch/.test(JIRA_JS),
      "Erfolg UND Fehlschlag werden gemeldet");
// Der alte, versteckte Weg ist raus – zwei Orte fuer dieselbe Datei waeren die
// naechste Verwirrung.
check(JS.indexOf("adminBlock") < 0,
      "der versteckte Admin-Kasten in der Anleitung ist entfernt");
for (const k of ["jshare.dl_h", "jshare.dl_p", "jshare.dl_chrome", "jshare.dl_firefox"]) {
  const n = (I18N.match(new RegExp("'" + k.replace(".", "\\.") + "':", "g")) || []).length;
  check(n >= 2, k + " hat DE und EN", "gefunden: " + n);
}

// ═══════════════════════════════════════════════════════════════════════════
section("4) Die Serveradresse steht in Schritt 3 – GEMESSEN am DOM");
// ═══════════════════════════════════════════════════════════════════════════
/* Die Karte „Einsatzbereit?" ist entfallen (Vorgabe 2026-08-28); ihre einzige
 * handlungsrelevante Zeile - die Adresse - steht jetzt dort, wo sie
 * eingetragen wird. Ein Quelltext-Test beantwortet die Frage nicht, auf die es
 * ankommt: STEHT AM ENDE EINE ADRESSE DA? */
for (const [name, zert, erwartet] of [
  ["Zertifikat deckt die Adresse", { zert_deckt_adresse: true }, false],
  ["nicht feststellbar (Rueckwaertsproxy)", {}, false],
  ["Zertifikat deckt sie NICHT",
   { zert_deckt_adresse: false, zert_namen: ["dp.firma.de", "alt.firma.de"] }, true],
]) {
  const { w, fehler } = await seite({ zert });
  const box = w.document.getElementById("ja-adresse");
  check(!!box, name + ": der Adress-Kasten existiert");
  const wert = box && box.querySelector(".ja-pfad-wert");
  check(!!wert && wert.textContent.indexOf("https://") === 0,
        name + ": eine Adresse steht da", wert && wert.textContent);
  check(!!(box && box.querySelector("button")), name + ": mit Kopier-Knopf");
  const warn = box && box.querySelector(".ja-warn");
  check(!!warn === erwartet,
        name + ": Warnung " + (erwartet ? "vorhanden" : "NICHT vorhanden"),
        warn ? warn.textContent.slice(0, 60) : "keine");
  /* ⚠ "nicht feststellbar" ist NICHT dasselbe wie "passt nicht" (TLS-Abbruch
   * in einem Rueckwaertsproxy). Daraus eine Warnung zu machen, wuerde eine
   * funktionierende Einrichtung als kaputt darstellen. */
  /* ⚠ KEIN `wert.textContent` OHNE NULL-SCHUTZ. Fehlt der Kasten, WIRFT das -
   * der Lauf bricht ab, statt fehlzuschlagen, und die Gegenprobe sieht aus wie
   * ein Absturz statt wie ein Befund. Genau so ist die Gegenprobe zu diesem
   * Abschnitt beim ersten Mal ausgegangen (Register). */
  const wtext = wert ? wert.textContent : "";
  const wntext = warn ? warn.textContent : "";
  if (zert.zert_deckt_adresse === false) {
    check(wtext === "https://dp.firma.de",
          name + ": eingetragen wird der Name aus dem ZERTIFIKAT", wtext);
    check(wntext.indexOf("alt.firma.de") > 0,
          name + ": weitere gueltige Namen werden genannt", wntext);
  } else {
    check(wtext === "https://jarvis.test",
          name + ": eingetragen wird die aufgerufene Adresse", wtext);
  }
  check(fehler.length === 0, name + ": kein Skriptfehler", fehler.join("; "));
  w.close();
}

/* `location.origin` ist nicht immer brauchbar (file://, "null" im
 * abgeschotteten iframe). Ein Kopierfeld mit "file://" waere eine Falle: der
 * Benutzer traegt es ein und wundert sich, dass nichts antwortet. Gefunden am
 * SCREENSHOT, nicht im Test - die Messung war gruen. */
/* ⚠ NICHT ueber eine echte file://-URL in jsdom: dort ist der Origin opak und
 * `localStorage` wirft eine DOMException - der Lauf braeche ab, statt
 * fehlzuschlagen (im ersten Anlauf genau so passiert, Register). Die Funktion
 * haengt allein an `window.location`, also wird sie mit gefaelschten Werten
 * ausgefuehrt. */
{
  const m = JS.match(/function eigeneAdresse\(\)\s*\{[\s\S]*?\n    \}/);
  check(!!m, "eigeneAdresse() ist schneidbar");
  const f = m ? new Function("window", m[0] + "\nreturn eigeneAdresse();") : null;
  const fall = (loc) => (f ? f({ location: loc }) : "?");
  check(fall({ origin: "https://dp.firma.de", hostname: "dp.firma.de" })
        === "https://dp.firma.de", "normale Adresse bleibt unveraendert");
  check(fall({ origin: "file://", hostname: "" }) === "",
        "file:// ergibt KEINE Adresse", fall({ origin: "file://", hostname: "" }));
  check(fall({ origin: "null", hostname: "" }) === "",
        "ein opaker Origin ebenfalls nicht");
  check(fall({ origin: "", hostname: "dp.firma.de" }) === "https://dp.firma.de",
        "ohne origin wird der Hostname genommen");
  // Und ohne Adresse entsteht KEIN Kopierfeld - ein Feld mit Unsinn waere
  // schlimmer als keines: der Benutzer traegt ihn ein und wundert sich.
  check(/if \(!eintragen\) return;/.test(JS),
        "ohne brauchbare Adresse wird kein Kopierfeld gebaut");
}

// Der Markenname muss aufgeloest sein: branding.js sammelt seine Fundstellen
// beim Laden ein, diese Zeile entsteht erst nach der Antwort von /health.
{
  const { w } = await seite({});
  const lab = w.document.querySelector("#ja-adresse .ja-pfad-lab");
  check(!!lab && lab.textContent.indexOf("{marke}") < 0,
        "kein roher {marke}-Platzhalter im Kasten", lab && lab.textContent);
  check(!!lab && /Adresse/.test(lab.textContent),
        "das Feld wird beim Namen genannt", lab && lab.textContent);
  check(!w.document.getElementById("ja-status"),
        "die Zustandsliste existiert nicht mehr im DOM");
  check(!w.document.getElementById("ja-status-card"),
        "und ihre Karte ebenfalls nicht");
  w.close();
}

console.log("\n" + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
})();
