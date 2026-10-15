#!/usr/bin/env node
/* Waechter fuer die Seite /confluence-addon – AUSGEFUEHRT, nicht gelesen.
 *
 * ⚠ WARUM ES DIESE DATEI GIBT: der ganze Zustandsblock (Pille am Titel,
 * Hinweiskasten, Serverfeld) wird vom Skript GEBAUT. Ein Quelltext-Test
 * beantwortet die eine Frage nicht, auf die es ankommt: **steht am Ende das
 * Richtige da?** Und die Pille ist der einzige Hinweis darauf, WELCHER Zugang
 * gerade gilt – ein stiller Rueckfall auf den Sammelzugang liesse den Benutzer
 * Seiten sehen, die mit FREMDEN Rechten geholt wurden.
 *
 * Geprueft wird ausserdem, was nur ein Lauf zeigen kann: dass ein LEERES
 * Token-Feld gar nicht erst gesendet wird ("leer = unveraendert" bleibt EINE
 * Regel des Servers), und dass die Seite Unberechtigte wirklich wegleitet.
 *
 * Lauf:  JSDOM_PATH=<pfad> node tests/test_confluence_addon_ui.js
 */
"use strict";

// Abbruchnetz aus EINER Quelle: ein Absturz endet mit Exit 2 statt mit
// Exit 1. Am 2026-10-05 lag diese Datei stumm brach, weil ein TypeError
// wie ein Befund aussah. Begruendung in tests/lib/bilanz.js.
require('./lib/bilanz')();

const fs = require("fs");
const path = require("path");

const WURZEL = path.resolve(__dirname, "..");
// jsdom an allen ueblichen Orten suchen – und mit Exit 2 abbrechen, wenn es
// fehlt. "konnte nicht laufen" darf nicht wie "bestanden" aussehen.
// Die Suchorte stehen gemeinsam in tests/lib/jsdom_laden.js.
const { JSDOM } = require("./lib/jsdom_laden")();
const sitzungLaden = require("./lib/sitzung_laden");

const HTML = fs.readFileSync(path.join(WURZEL, "frontend/confluence_addon.html"), "utf8");
const JS = fs.readFileSync(path.join(WURZEL, "frontend/js/confluence_addon.js"), "utf8");
// Sitzungstoken: seit 8d082990 liegt die Schluesselkette an EINER Stelle
// (`window.JarvisSitzung`), und confluence_addon.js liest sie in `token()`.
// Das ECHTE Modul, keine Attrappe - keine Abhaengigkeiten, kein DOM, nur
// localStorage. Im Browser ist es das erste <script> der Seite.
const SITZUNG = fs.readFileSync(path.join(WURZEL, "frontend/js/sitzung.js"), "utf8");

let ok = 0, fail = 0;
function check(bed, text, extra) {
  if (bed) { ok++; console.log("  OK   " + text); }
  else { fail++; console.log("  FAIL " + text + (extra ? " – " + extra : "")); }
}
function section(t) { console.log("\n═══ " + t); }

/** Laedt die echte Seite, laesst das echte Skript laufen. */
async function seite({ konto = null, darf = true, istAdmin = false,
                       kontoWirft = false } = {}) {
  const dom = new JSDOM(HTML, { url: "https://jarvis.test/confluence-addon",
                                runScripts: "outside-only" });
  const w = dom.window;
    // sitzung.js VOR den Modulen der Seite - im Browser ist sie das ERSTE
    // Skript jeder Seite, und die Module lesen den Token ausschliesslich ueber
    // window.JarvisSitzung. Ohne diese Zeile wirft der erste Abruf und der
    // Lauf endet OHNE Bilanzzeile (Begruendung: tests/lib/sitzung_laden.js).
    sitzungLaden(w);
  w.localStorage.setItem("jarvis_token", "T");
  const gerufen = [];
  let umgeleitet = "";
  // ⚠ `location.replace` LAESST SICH IN JSDOM NICHT STELLEN – weder per
  // Zuweisung ("Cannot assign to read only property") noch per
  // `defineProperty` ("Cannot redefine property"). Beide Versuche brechen den
  // Lauf VOR der ersten Pruefung ab; ein Lauf ohne Bilanz ist von "nicht
  // gelaufen" nicht zu unterscheiden.
  //
  // Deshalb wird das Modul in einer Klammer ausgefuehrt, in der `window` ein
  // Proxy mit unserer `location` ist. Das Modul greift die Umleitung ueber
  // `window.location.replace` ab – alles andere geht unveraendert an das echte
  // Fenster (Funktionen gebunden, sonst "Illegal invocation").
  const stubLoc = { replace: (z) => { umgeleitet = String(z); },
                    href: w.location.href, origin: w.location.origin,
                    hostname: w.location.hostname, pathname: w.location.pathname };
  w.__stubWin = new Proxy(w, {
    get(t, k) {
      if (k === "location") return stubLoc;
      const v = t[k];
      return typeof v === "function" ? v.bind(t) : v;
    },
    set(t, k, v) { t[k] = v; return true; },
    has(t, k) { return k in t; },
  });
  w.confirm = () => true;
  w.fetch = async (url, opt) => {
    const p = String(url).split("?")[0];
    gerufen.push({ pfad: p, methode: (opt && opt.method) || "GET",
                   rumpf: opt && opt.body ? JSON.parse(opt.body) : null });
    if (p === "/api/me") {
      return { ok: true, json: async () => ({
        permissions: { confluence: darf }, is_admin: istAdmin }) };
    }
    if (p === "/api/confluence/account") {
      if (kontoWirft) throw new Error("Netz weg");
      return { ok: true, json: async () => ({ ok: true, account: konto || {} }) };
    }
    if (p === "/api/confluence/account/test") {
      return { ok: true, json: async () => ({
        ok: true, anzeigename: "Alice A.", konto: "alice",
        info: konto || {} }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
  };
  const fehler = [];
  w.addEventListener("error", (e) => fehler.push(String(e.message)));
  // ANGEHAENGT, NICHT interpoliert: ein Backtick im Quelltext beendet sonst das
  // Template-Literal, und ein `\d` in einem Regex verliert seinen Backslash –
  // der Waechter prueefte dann eine Datei, die es so nicht gibt (Register).
  try {
    // sitzung.js auf das ECHTE Fenster, nicht in den Stub-Rahmen: der Proxy
    // reicht Lesezugriffe an `w` durch, das Modul findet es also ueber beide.
    w.eval(SITZUNG);
    w.eval("(function(window){\n" + JS + "\n}).call(window.__stubWin, window.__stubWin);");
  } catch (e) { fehler.push("eval: " + e.message); }
  await new Promise((r) => setTimeout(r, 60));
  const $ = (id) => w.document.getElementById(id);
  return { w, $, gerufen, fehler, umgeleitet };
}

const SAMMEL = { vorhanden: false, aktiv: true, token_gesetzt: false,
                 basis_url: "https://wiki.firma.de", server_konfiguriert: true,
                 sammel_vorhanden: true, anzeigename: "", konto: "",
                 letzter_fehler: "", letzter_erfolg: 0 };
const EIGEN = Object.assign({}, SAMMEL, { vorhanden: true, token_gesetzt: true,
                                          anzeigename: "Alice A.", konto: "alice" });

(async () => {

// ═══════════════════════════════════════════════════════════════════════════
section("1) Die Seite ist eine leere Huelle – fail-closed");
// ═══════════════════════════════════════════════════════════════════════════
{
  const a = await seite({ darf: false, konto: SAMMEL });
  check(a.umgeleitet === "/portal", "ohne Freigabe geht es aufs Portal",
        a.umgeleitet);
  check(a.$("ca-app").classList.contains("hidden"),
        "… und der Inhalt bleibt verborgen");
  // Positivkontrolle: mit Freigabe wird die Seite WIRKLICH aufgedeckt – ohne
  // diese Gegenrichtung waere die Pruefung darueber trivial erfuellt.
  const b = await seite({ darf: true, konto: SAMMEL });
  check(b.umgeleitet === "", "Positivkontrolle: mit Freigabe keine Umleitung",
        b.umgeleitet);
  check(!b.$("ca-app").classList.contains("hidden"),
        "… und der Inhalt ist sichtbar");
  check(b.fehler.length === 0, "kein JS-Fehler beim Aufbau", b.fehler.join("|"));
  check(b.$("ca-settings-btn").style.display === "none",
        "das Zahnrad bleibt fuer Nicht-Admins aus");
  const c = await seite({ istAdmin: true, konto: SAMMEL });
  check(c.$("ca-settings-btn").style.display === "",
        "… und erscheint fuer Administratoren");
}

// ═══════════════════════════════════════════════════════════════════════════
section("2) Die Pille sagt, WELCHER Zugang gilt – Text UND Farbe");
// ═══════════════════════════════════════════════════════════════════════════
/* Farbe allein ist keine Information (Projektregel), deshalb wird BEIDES
 * gemessen: der sichtbare Text und die Klasse. */
for (const [name, konto, wort, klasse] of [
  ["ohne eigenen Token", SAMMEL, "gemeinsam", null],
  ["mit eigenem Token", EIGEN, "eigener", "is-own"],
  ["inaktiv", Object.assign({}, EIGEN, { aktiv: false }), "inaktiv", "is-warn"],
  ["Token abgelehnt", Object.assign({}, EIGEN, { letzter_fehler: "HTTP 401" }),
   "abgelehnt", "is-warn"],
]) {
  const a = await seite({ konto });
  const pill = a.$("ca-acc-pill");
  check(pill.textContent.toLowerCase().includes(wort),
        name + ": die Pille nennt den Zustand", pill.textContent);
  if (klasse) {
    check(pill.classList.contains(klasse),
          name + ": … und traegt die Farbe dazu", pill.className);
  } else {
    check(!pill.classList.contains("is-own") && !pill.classList.contains("is-warn"),
          name + ": … ohne Warnfarbe", pill.className);
  }
}
{
  // Die Pille wird bei JEDEM Laden gefuellt, auch wenn nichts eingerichtet ist –
  // sie ist der einzige Hinweis, bevor jemand etwas anfasst.
  const a = await seite({ konto: SAMMEL });
  check(a.$("ca-acc-pill").textContent.trim() !== "",
        "die Pille ist nie leer (sonst stuende dort ein nackter Rahmen)");
  // Und bei ausgefallenem Abruf behauptet sie den Normalfall, nicht mehr.
  const b = await seite({ kontoWirft: true });
  check(b.fehler.length === 0, "ein ausgefallener Abruf reisst die Seite nicht mit",
        b.fehler.join("|"));
  check(b.$("ca-acc-pill").textContent.trim() !== "",
        "… und die Pille steht trotzdem da");
}

// ═══════════════════════════════════════════════════════════════════════════
section("3) Der Hinweiskasten nennt WER der Token ist");
// ═══════════════════════════════════════════════════════════════════════════
{
  const a = await seite({ konto: EIGEN });
  const note = a.$("ca-acc-note");
  check(note.classList.contains("is-on"), "der Kasten ist sichtbar");
  check(note.textContent.includes("Alice A.") && note.textContent.includes("alice"),
        "… und nennt Namen und Konto", note.textContent);
  const b = await seite({ konto: SAMMEL });
  check(!b.$("ca-acc-note").classList.contains("is-on"),
        "ohne Aussage bleibt er zu (kein leerer Kasten)");
  // Ohne JEDEN Zugang darf die Oberflaeche den eigenen Token nicht als
  // "optional" darstellen.
  const c = await seite({ konto: Object.assign({}, SAMMEL,
                                               { sammel_vorhanden: false }) });
  check(c.$("ca-acc-note").textContent.includes("weder"),
        "ohne gemeinsamen UND ohne eigenen Zugang sagt er das",
        c.$("ca-acc-note").textContent);
}

// ═══════════════════════════════════════════════════════════════════════════
section("4) Das Serverfeld ist Anzeige, kein Eingabefeld");
// ═══════════════════════════════════════════════════════════════════════════
{
  const a = await seite({ konto: EIGEN });
  const srv = a.$("ca-acc-server");
  check(srv.value === "https://wiki.firma.de", "die Adresse steht drin", srv.value);
  check(srv.hasAttribute("readonly") && srv.hasAttribute("disabled"),
        "… und das Feld ist readonly UND disabled (sonst tippt jemand hinein)");
  const b = await seite({ konto: Object.assign({}, SAMMEL,
                          { basis_url: "", server_konfiguriert: false }) });
  check(b.$("ca-acc-server").placeholder.includes("keine Adresse"),
        "ohne Adresse sagt der Platzhalter das",
        b.$("ca-acc-server").placeholder);
}

// ═══════════════════════════════════════════════════════════════════════════
section("5) ⚠ Ein LEERES Token-Feld wird gar nicht erst gesendet");
// ═══════════════════════════════════════════════════════════════════════════
/* "leer = unveraendert" bleibt so EINE Regel (die des Servers) und nicht zwei.
 * Das kann eine Quelltext-Suche nicht beantworten – gemessen wird der RUMPF. */
{
  const a = await seite({ konto: EIGEN });
  a.$("ca-acc-aktiv").checked = false;
  a.gerufen.length = 0;
  a.$("ca-acc-save").click();
  await new Promise((r) => setTimeout(r, 40));
  const posts = a.gerufen.filter((g) => g.pfad === "/api/confluence/account"
                                        && g.methode === "POST");
  check(posts.length === 1, "ein Klick = genau ein POST", String(posts.length));
  check(posts.length === 1 && !("api_token" in posts[0].rumpf),
        "⚠ das leere Feld steht NICHT im Rumpf",
        JSON.stringify(posts.length ? posts[0].rumpf : null));
  check(posts.length === 1 && posts[0].rumpf.aktiv === false,
        "… der Haken geht mit", JSON.stringify(posts.length ? posts[0].rumpf : null));
}
{
  const a = await seite({ konto: EIGEN });
  a.$("ca-acc-token").value = "NEUER-PAT";
  a.gerufen.length = 0;
  a.$("ca-acc-save").click();
  await new Promise((r) => setTimeout(r, 40));
  const p = a.gerufen.find((g) => g.pfad === "/api/confluence/account"
                                  && g.methode === "POST");
  check(!!p && p.rumpf.api_token === "NEUER-PAT",
        "ein gefuelltes Feld geht mit", JSON.stringify(p && p.rumpf));
  check(a.$("ca-acc-token").value === "",
        "⚠ und das Feld wird danach GELEERT (kein Klartext im Formular)",
        a.$("ca-acc-token").value);
}
{
  // Ohne eigenen Token UND ohne Eingabe ist "Speichern" sinnlos – es wird
  // gemeldet, nicht gesendet.
  const a = await seite({ konto: SAMMEL });
  a.gerufen.length = 0;
  a.$("ca-acc-save").click();
  await new Promise((r) => setTimeout(r, 40));
  check(!a.gerufen.some((g) => g.methode === "POST"),
        "ohne Token und ohne Eingabe wird nichts gesendet",
        JSON.stringify(a.gerufen));
  check(!a.$("ca-acc-msg").hidden
        && a.$("ca-acc-msg").textContent.toLowerCase().includes("token"),
        "… und der Grund steht am Knopf", a.$("ca-acc-msg").textContent);
}

// ═══════════════════════════════════════════════════════════════════════════
section("6) Testen und Entfernen gehen an die richtigen Wege");
// ═══════════════════════════════════════════════════════════════════════════
{
  const a = await seite({ konto: EIGEN });
  a.gerufen.length = 0;
  a.$("ca-acc-test").click();
  await new Promise((r) => setTimeout(r, 40));
  const t = a.gerufen.find((g) => g.pfad === "/api/confluence/account/test");
  check(!!t && t.methode === "POST", "der Test ruft /account/test per POST",
        JSON.stringify(a.gerufen));
  check(a.$("ca-acc-msg").textContent.includes("Alice A."),
        "… und die Meldung nennt, WER der Token ist",
        a.$("ca-acc-msg").textContent);
}
{
  const a = await seite({ konto: EIGEN });
  a.gerufen.length = 0;
  a.$("ca-acc-del").click();
  await new Promise((r) => setTimeout(r, 40));
  const d = a.gerufen.find((g) => g.pfad === "/api/confluence/account"
                                  && g.methode === "DELETE");
  check(!!d, "Entfernen ruft DELETE", JSON.stringify(a.gerufen));
}
{
  // Eine abgelehnte Rueckfrage darf NICHTS tun.
  const a = await seite({ konto: EIGEN });
  a.w.confirm = () => false;
  a.gerufen.length = 0;
  a.$("ca-acc-del").click();
  await new Promise((r) => setTimeout(r, 40));
  check(!a.gerufen.some((g) => g.methode === "DELETE"),
        "⚠ bei 'nein' wird nicht geloescht", JSON.stringify(a.gerufen));
}

// ═══════════════════════════════════════════════════════════════════════════
section("7) Der Sprachwechsel zeichnet den Zustand neu");
// ═══════════════════════════════════════════════════════════════════════════
/* Pille und Hinweiskasten werden GERENDERT, nicht per data-i18n uebersetzt –
 * ohne den Zuhoerer blieben sie nach einem Wechsel deutsch. Gemessen wird, dass
 * er greift, ohne den Zustand NEU zu laden (der liegt schon vor). */
{
  const a = await seite({ konto: EIGEN });
  const vorher = a.gerufen.filter((g) => g.pfad === "/api/confluence/account").length;
  a.$("ca-acc-pill").textContent = "ZERSTOERT";
  a.w.dispatchEvent(new a.w.Event("jarvis-lang-changed"));
  await new Promise((r) => setTimeout(r, 20));
  check(a.$("ca-acc-pill").textContent !== "ZERSTOERT",
        "die Pille wird neu gezeichnet", a.$("ca-acc-pill").textContent);
  const nachher = a.gerufen.filter((g) => g.pfad === "/api/confluence/account").length;
  check(nachher === vorher, "… ohne einen weiteren Abruf",
        vorher + " → " + nachher);
}

console.log("\n" + "=".repeat(70));
console.log("ERGEBNIS: " + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
})().catch((e) => {
  // Ein Abbruch darf nicht wie ein bestandener Lauf aussehen: Bilanz UND
  // Exit-Code setzen (Register – ein Wachhund ohne Ausgang ist schlimmer als
  // keiner).
  console.log("  FAIL ABBRUCH: " + (e && e.stack || e));
  console.log("\nERGEBNIS: " + ok + " OK, " + (fail + 1) + " FAIL (ABGEBROCHEN)");
  process.exit(1);
});
