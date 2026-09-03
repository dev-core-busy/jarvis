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

/* ── REGEL: `data-i18n` setzt den textContent ────────────────────────────
 * Traegt der uebersetzte Text Markup (<b>, <code>, <ul> …), gehoert
 * `data-i18n-html` an das Element. Sonst steht das Tag WOERTLICH auf der
 * Seite – genau so stand am 2026-08-31 "<b>deinen</b>" im Kasten
 * "Mein Jira-Zugang" auf dem Produktivsystem.
 *
 * ⚠ AUFGEFALLEN IST DAS NUR AM SCHREENSHOT. Im Quelltext sieht ein
 * `data-i18n` genauso richtig aus wie ein `data-i18n-html`; der Fehler
 * entsteht erst aus dem Zusammenspiel mit dem TEXT in i18n.js. Deshalb
 * prueft dieser Waechter die REGEL ueber alle Schluessel der Seite und
 * nicht eine gepflegte Liste – ein kuenftiger Text, dem jemand ein <b>
 * hinzufuegt, faellt damit von selbst auf.
 */
{
  const deVon = I18N.search(/^\s{0,4}de\s*:\s*\{/m);
  const enVon = I18N.search(/^\s{0,4}en\s*:\s*\{/m);
  const de = I18N.slice(deVon, enVon);
  const wert = (k) => {
    const m = de.match(new RegExp("'" + k.replace(".", "\\.") + "'\\s*:\\s*'((?:[^'\\\\]|\\\\.)*)'"));
    return m ? m[1] : "";
  };
  const mitMarkup = /<(b|i|code|strong|em|ul|ol|li|br)\b/;
  const schuldige = [];
  for (const m of HTML.matchAll(/data-i18n="([a-z]+\.[a-z_0-9]+)"/g)) {
    if (mitMarkup.test(wert(m[1]))) schuldige.push(m[1]);
  }
  check(schuldige.length === 0,
        "kein data-i18n auf einem Text mit Markup (sonst steht das Tag da)",
        schuldige.join(", "));
  // Positivkontrolle: die Pruefung findet ueberhaupt Texte mit Markup –
  // sonst waere die Null oben aus dem falschen Grund gruen.
  const mitHtml = [...HTML.matchAll(/data-i18n-html="([a-z]+\.[a-z_0-9]+)"/g)]
      .map((m) => m[1]).filter((k) => mitMarkup.test(wert(k)));
  check(mitHtml.length >= 3,
        "und die Regel greift wirklich (Texte mit Markup gefunden)",
        String(mitHtml.length));
}

// ═══════════════════════════════════════════════════════════════════════════
section("9) Die Anleitung nennt den ersten Pulldown-Eintrag richtig");
// ═══════════════════════════════════════════════════════════════════════════
/* Vorgabe 2026-09-02: der Eintrag heisst "Zusammenfassen" statt "Ohne
 * Vorlage". Eine Anleitung, die ein Bedienelement bei einem Namen nennt, den
 * es nicht mehr gibt, schickt den Benutzer suchen - diese Fehlerklasse hat das
 * Projekt schon mehrfach bezahlt (jaddon.limit_3, use_5, view_3).
 *
 * ⚠ GEPRUEFT WIRD ALS REGEL UEBER ALLE `jaddon.*`-SCHLUESSEL, nicht nur ueber
 * use_3: sonst faellt der naechste Text auf, der den alten Namen wieder
 * einfuehrt - und genau so ist die Luecke jedes Mal entstanden. */
{
  const deVon = I18N.search(/^\s{0,4}de\s*:\s*\{/m);
  const enVon = I18N.search(/^\s{0,4}en\s*:\s*\{/m);
  check(deVon >= 0 && enVon > deVon, "beide Sprachbloecke gefunden");

  const sammle = (block) =>
    (block.match(/'jaddon\.[a-z0-9_]+':\s*'(?:[^'\\]|\\.)*'/g) || []).join("\n");
  const jdDe = sammle(I18N.slice(deVon, enVon));
  const jdEn = sammle(I18N.slice(enVon));
  // Positivkontrolle: ohne sie waere jede Abwesenheits-Pruefung unten aus dem
  // falschen Grund gruen (Register).
  check(jdDe.length > 2000 && jdEn.length > 2000,
        "die jaddon-Schluessel wurden in beiden Sprachen gefunden",
        jdDe.length + " / " + jdEn.length);

  for (const [name, block] of [["DE", jdDe], ["EN", jdEn]]) {
    for (const wort of ["Ohne Vorlage", "ohne Vorlage",
                        "Without a template", "without a template"]) {
      check(block.indexOf(wort) < 0,
            name + ": keine Anleitung sagt mehr '" + wort + "'");
    }
  }

  const wert = (block, k) => {
    const m = block.match(new RegExp("'" + k.replace(/\./g, "\\.")
                                     + "':\\s*'((?:[^'\\\\]|\\\\.)*)'"));
    return m ? m[1] : "";
  };
  const u3de = wert(jdDe, "jaddon.use_3");
  const u3en = wert(jdEn, "jaddon.use_3");
  check(/Zusammenfassen/.test(u3de),
        "DE: use_3 nennt den Eintrag 'Zusammenfassen'", u3de.slice(0, 80));
  /* ⚠ AUCH IM ENGLISCHEN STEHT DER DEUTSCHE NAME: das Fenster der Erweiterung
   * ist einsprachig. Wer hier "Summarise" schreibt, laesst den Leser nach
   * einem Eintrag suchen, den es nicht gibt - die Anleitung muss das
   * Bedienelement bei SEINEM Namen nennen (Gloss in Klammern). */
  check(/Zusammenfassen/.test(u3en),
        "EN: use_3 nennt denselben deutschen Eintragstext",
        u3en.slice(0, 80));

  /* Das Rueckfall-Markup ist, was ein Leser SIEHT, bevor i18n laeuft. Weicht
   * es ab, wechselt der Text vor seinen Augen. */
  const fb = (HTML.match(/data-i18n-html="jaddon\.use_3">([\s\S]*?)<\/li>/)
              || ["", ""])[1].trim();
  check(fb === u3de.replace(/\\'/g, "'"),
        "das Rueckfall-Markup in jira_addon.html ist deckungsgleich mit DE",
        fb.slice(0, 80));
}

// ═══════════════════════════════════════════════════════════════════════════
section("10) Die Anleitung nennt die Seitenleiste als Vorgabe (2026-09-03)");
// ═══════════════════════════════════════════════════════════════════════════
/* Vorgabe des Nutzers: die Leiste ist die Vorgabe, sofern der Browser sie
 * kann. Bis 0.8.5 stand hier "oeffnet ein kleines Fenster - so ist es
 * voreingestellt". Eine Anleitung, die eine andere Vorgabe behauptet als die
 * wirksame, schickt den Benutzer suchen. */
{
  const deVon = I18N.search(/^\s{0,4}de\s*:\s*\{/m);
  const enVon = I18N.search(/^\s{0,4}en\s*:\s*\{/m);
  const holen = (block) => {
    const o = {};
    const rx = /'(jaddon\.[a-z0-9_]+)':\s*'((?:[^'\\]|\\.)*)'/g;
    let m;
    while ((m = rx.exec(block))) o[m[1]] = m[2].replace(/\\'/g, "'");
    return o;
  };
  const DE = holen(I18N.slice(deVon, enVon));
  const EN = holen(I18N.slice(enVon));
  check(Object.keys(DE).length > 30 && Object.keys(EN).length > 30,
        "Positivkontrolle: die jaddon-Schluessel wurden gelesen",
        Object.keys(DE).length + " / " + Object.keys(EN).length);

  for (const [name, T] of [["DE", DE], ["EN", EN]]) {
    const p = T["jaddon.view_p"] || "";
    check(/Seitenleiste|side panel/i.test(p.split(/–|-/)[0] || p),
          name + ": view_p nennt zuerst die Seitenleiste", p.slice(0, 90));
    check(/voreingestellt|the default/i.test(p),
          name + ": und sagt ausdruecklich, dass sie die Vorgabe ist");
    /* Die Vorgabe gilt NUR, wenn der Browser eine Leiste kennt - das gehoert
     * in den Text, sonst sucht ein Benutzer ohne Leiste den Fehler bei sich. */
    check(/sofern|provided/i.test(p),
          name + ": und dass das am Browser haengt");
    check(!/kleines Fenster – so ist es voreingestellt/.test(p)
          && !/opens a small window – that is the default/.test(p),
          name + ": die alte Vorgabe-Aussage ist weg");
  }
  /* ⚠ AUCH IM ENGLISCHEN STEHT DER DEUTSCHE SCHALTERTEXT: das Fenster der
   * Erweiterung ist einsprachig. Wer hier "Open as side panel" schreibt,
   * laesst den Leser nach einem Bedienelement suchen, das es nicht gibt -
   * dieselbe Regel wie bei use_3 (Gloss in Klammern). */
  check(/Als Seitenleiste öffnen/.test(EN["jaddon.view_p"] || ""),
        "EN: view_p nennt den Schalter bei SEINEM (deutschen) Namen",
        (EN["jaddon.view_p"] || "").slice(-90));

  /* ⚠ DAS RUECKFALL-MARKUP IST EINE REGEL UEBER ALLE SCHLUESSEL, nicht nur
   * ueber use_3. Genau die Luecke hat dieser Lauf am 2026-09-03 gefunden:
   * `setup_note` ("das Zugangstoken wird bewusst nicht dauerhaft
   * gespeichert"), `use_note` und `limit_2` ("Sie kann nichts nachschlagen")
   * standen im Markup noch in ihrer ALTEN, inzwischen falschen Fassung - drei
   * Aussagen, die ein Leser sieht, bevor i18n laeuft, und von denen zwei das
   * Gegenteil des heutigen Verhaltens behaupten. */
  {
    const rx = new RegExp(
      '<(\\w+)[^>]*?data-i18n(?:-html)?="(jaddon\\.[a-z0-9_]+)"[^>]*>'
      + '([\\s\\S]*?)</\\1>', "g");
    let m, gezaehlt = 0, schief = [];
    while ((m = rx.exec(HTML))) {
      const k = m[2], fb = m[3].trim();
      gezaehlt++;
      if (!(k in DE)) { schief.push(k + " (kein DE-Text)"); continue; }
      if (fb !== DE[k]) schief.push(k);
    }
    check(gezaehlt > 40, "Positivkontrolle: Rueckfall-Texte gefunden",
          String(gezaehlt));
    check(schief.length === 0,
          "jeder Rueckfall-Text in jira_addon.html ist deckungsgleich mit DE",
          schief.join(", "));
  }
}

console.log("\n" + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
})();
