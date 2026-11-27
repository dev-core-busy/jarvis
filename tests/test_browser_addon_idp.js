#!/usr/bin/env node
/* Waechter: Anmeldung ueber das Firmenkonto (IdP) in der Browser-Erweiterung.
 *
 * Gemessen wird der ABLAUF, nicht der Quelltext:
 *   A) Regeln: Permission `identity` in beiden Manifesten, STAND/Version gleich,
 *      Knoepfe im Markup an der richtigen Stelle, neue Merk-Felder bekannt.
 *   B) Der ECHTE background.js laeuft in einer VM gegen gestellte Browser-
 *      Wurzeln (chrome-, browser-, gemischt) und eine fetch-Attrappe, die ueber
 *      den PFAD routet. Nachrichten gehen ueber den echten onMessage-Zuhoerer.
 *      PKCE wird nachgerechnet (SHA-256 des verifiers == challenge).
 *   C) Die echten Fensterteile (idpZeigen, idpPruefen, die Klick-Rumpfe,
 *      start) laufen in jsdom gegen die echte popup.html.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen (Positivkontrolle). */
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const nodeCrypto = require("crypto");
const { JSDOM } = require("./lib/jsdom_laden")();
const wachhund = require("./lib/wachhund");

const WURZEL = path.resolve(__dirname, "..");
const ADDON = process.env.ADDON_DIR || path.join(WURZEL, "browser-addon");
const lies = (p) => fs.readFileSync(path.join(ADDON, p), "utf8");

let ok = 0, fail = 0, bilanz = false;
function check(bed, text, extra) {
  if (bed) { ok++; console.log("  OK   " + text); }
  else { fail++; console.log("  FAIL " + text + (extra !== undefined ? " – " + extra : "")); }
}
function section(t) { console.log("\n═══ " + t); }
function abbruch(grund) {
  console.log("ABBRUCH (konnte nicht laufen): " + grund);
  process.exit(2);
}
process.on("unhandledRejection", (e) => {
  fail++;
  process.exitCode = 1;
  console.log("  FAIL unbehandelte Zurueckweisung: " + ((e && e.stack) || e));
});
process.on("exit", (code) => {
  if (!bilanz && code === 0) process.exitCode = 1;
});
const hund = wachhund(() => { console.log("ABBRUCH: Stillstand (Wachhund)"); process.exit(2); }, 60000);

const BG = lies("background.js");
const POPUP_JS = lies("popup.js");
const POPUP_HTML = lies("popup.html");
const M_CHROME = JSON.parse(lies("manifest.json"));
const M_FF = JSON.parse(lies("manifest.firefox.json"));

const b64url = (buf) => Buffer.from(buf).toString("base64")
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const sha256b64url = (s) => b64url(nodeCrypto.createHash("sha256").update(s, "ascii").digest());

(async () => {
// ═══════════════════════════════════════════════════════════════════════════
section("A) Regeln: Manifeste, STAND, Markup");
// ═══════════════════════════════════════════════════════════════════════════
check((M_CHROME.permissions || []).includes("identity"), "Chrome-Manifest traegt identity");
check((M_FF.permissions || []).includes("identity"), "Firefox-Manifest traegt identity");
check(M_CHROME.version === M_FF.version, "beide Manifeste dieselbe Version",
      M_CHROME.version + " / " + M_FF.version);
{
  const sp = (POPUP_JS.match(/const STAND = (\d+);/) || [0, ""])[1];
  const sb = (BG.match(/const STAND = (\d+);/) || [0, ""])[1];
  check(sp !== "" && sp === sb, "STAND gleich in popup.js und background.js", sp + "/" + sb);
  check(parseInt(sb, 10) >= 10, "STAND hochgezaehlt (neue Faelle idp_status/idp_anmelden)", sb);
}
{
  const dom = new JSDOM(POPUP_HTML);
  const d = dom.window.document;
  const block = d.getElementById("idp-block"), kw = d.getElementById("kennwort-block");
  const knopf = d.getElementById("btn-idp"), link = d.getElementById("btn-kennwort-zeigen");
  if (!block || !kw || !knopf || !link || !d.getElementById("f-basis")) {
    abbruch("idp-block/kennwort-block/btn-idp/btn-kennwort-zeigen/f-basis fehlt im Markup");
  }
  check(block.hidden, "der IdP-Block ist im Markup verborgen (Vorgabe: Maske wie bisher)");
  check(!kw.hidden, "die Kennwortmaske ist im Markup sichtbar");
  check(knopf.textContent.trim() === "Mit Firmenkonto anmelden (SSO)",
        "Knopfbeschriftung", knopf.textContent.trim());
  check(!!(block.compareDocumentPosition(kw) & dom.window.Node.DOCUMENT_POSITION_FOLLOWING),
        "der Firmenkonto-Knopf steht VOR der Kennwortmaske");
  check(kw.contains(d.getElementById("f-kennwort")) && kw.contains(d.getElementById("btn-anmelden")),
        "Kennwortfeld und Anmelden-Knopf liegen in der Kennwortmaske");
  check(!kw.contains(d.getElementById("f-basis")),
        "die Adresse liegt NICHT in der eingeklappten Maske (wird fuer beide Wege gebraucht)");
  check(knopf.hasAttribute("data-ohne-ticket") && link.hasAttribute("data-ohne-ticket"),
        "beide neuen Knoepfe sind von der Ticket-Sperre ausgenommen");
}
{
  // Jedes per `merken` geschickte Feld muss einstSchreiben kennen, sonst wird
  // es wortlos verworfen (Regel aus test_browser_addon.js, hier fuer die neuen).
  const es = (BG.match(/async function einstSchreiben\([\s\S]*?\n\}/) || [""])[0];
  for (const f of ["idp_meldung", "idp_kennwort"]) {
    check(new RegExp("teil\\." + f + " !== undefined").test(es),
          "einstSchreiben kennt " + f);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
section("B) Hintergrund: der echte background.js in einer VM");
// ═══════════════════════════════════════════════════════════════════════════
const RUECK_CHROME = "https://abcdefghijklmnopabcdefghijklmnop.chromiumapp.org/";
const RUECK_FF = "https://0123456789abcdef0123456789abcdef01234567.extensions.allizom.org/";

/** Baut eine Umgebung. `wurzel`: "chrome" | "browser" | "gemischt" | "ohne_identity".
 *  `flow(url)`: was launchWebAuthFlow liefert (oder wirft). `server`: Pfad -> Antwort. */
function umgebung({ wurzel = "chrome", flow, server = {} } = {}) {
  const ablage = {};
  const spur = { fetch: [], flow: [] };
  let zuhoerer = null;
  const lautlos = () => new Proxy(function () {}, {
    get: (_t, k) => (k === "then" ? undefined : lautlos()),
    apply: () => Promise.resolve(undefined),
  });
  const storage = { local: {
    async get(k) { return k in ablage ? { [k]: JSON.parse(JSON.stringify(ablage[k])) } : {}; },
    async set(o) { for (const k of Object.keys(o)) ablage[k] = JSON.parse(JSON.stringify(o[k])); },
    async remove(k) { delete ablage[k]; },
  } };
  const runtime = {
    onMessage: { addListener(f) { zuhoerer = f; } },
    onInstalled: { addListener() {} }, onStartup: { addListener() {} },
    getManifest: () => ({}), getContexts: async () => [],
  };
  const rueck = wurzel === "browser" ? RUECK_FF : RUECK_CHROME;
  const identity = {
    getRedirectURL: () => rueck,
    async launchWebAuthFlow(opt) {
      spur.flow.push(opt);
      return flow ? flow(opt.url, rueck) : "";
    },
  };
  const voll = { storage, runtime, identity, action: lautlos(), tabs: lautlos(),
                 permissions: lautlos(), sidePanel: lautlos(), scripting: lautlos() };
  let chromeW, browserW;
  if (wurzel === "chrome") chromeW = voll;
  else if (wurzel === "browser") { browserW = voll; chromeW = { runtime }; }
  else if (wurzel === "gemischt") {
    // browser als TEIL-Alias ohne identity (Edge-Fall), identity nur an chrome.
    browserW = { storage, runtime };
    chromeW = Object.assign({}, voll);
  } else { chromeW = Object.assign({}, voll); delete chromeW.identity; }

  async function fetchAttrappe(url, opt) {
    const u = new URL(url);
    const eintrag = { pfad: u.pathname, opt, rumpf: opt && opt.body ? JSON.parse(opt.body) : null,
                      basis: u.origin };
    spur.fetch.push(eintrag);
    const h = server[u.pathname];
    if (!h) return { status: 404, ok: false, json: async () => ({ error: "nicht da" }) };
    const r = await h(eintrag);
    if (r instanceof Error) throw r;
    return { status: r.status || 200, ok: (r.status || 200) < 400,
             json: async () => r.body };
  }
  const ctx = {
    console, setTimeout, clearTimeout, URL, URLSearchParams, TextEncoder,
    btoa: (s) => Buffer.from(s, "binary").toString("base64"),
    crypto: nodeCrypto.webcrypto, fetch: fetchAttrappe,
  };
  if (chromeW) ctx.chrome = chromeW;
  if (browserW) ctx.browser = browserW;
  vm.createContext(ctx);
  vm.runInContext(BG, ctx, { filename: "background.js" });
  if (!zuhoerer) abbruch("background.js hat keinen onMessage-Zuhoerer angemeldet");
  const senden = (n) => new Promise((fertig) => {
    const r = zuhoerer(n, { documentId: "d1" }, fertig);
    if (r !== true) fertig(undefined);
  });
  return { senden, ablage, spur, rueck };
}

const BASIS = "https://jarvis.beispiel.de";
const meOk = async () => ({ body: { permissions: { jira_assist: true } } });
const statusAn = (modus) => async () => ({ body: { aktiv: true, ad_modus: modus } });

// ── Positivkontrolle: die VM laeuft und der Zustand antwortet ─────────────
{
  const u = umgebung();
  const z = await u.senden({ art: "zustand" });
  if (!z || z.ok !== true || z.stand === undefined) {
    abbruch("Positivkontrolle: 'zustand' antwortet nicht aus der VM (" + JSON.stringify(z) + ")");
  }
  check(true, "Positivkontrolle: der echte Hintergrund antwortet aus der VM");
}

// ── B1) Status ────────────────────────────────────────────────────────────
{
  let u = umgebung({ server: { "/api/login/oidc/status": statusAn("fallback") } });
  let r = await u.senden({ art: "idp_status", basis: BASIS });
  check(r && r.ok && r.aktiv === true && r.ad_modus === "fallback",
        "Status aktiv/fallback wird durchgereicht", JSON.stringify(r));
  const f = u.spur.fetch[0] || {};
  check(f.basis === BASIS && !(f.opt.headers || {}).Authorization,
        "der Status geht an die Adresse aus dem FELD und ohne Token");
  check(f.opt && f.opt.credentials === "omit", "und ohne Cookies (wie ruf() immer)");

  u = umgebung({ server: { "/api/login/oidc/status": statusAn("zusaetzlich") } });
  r = await u.senden({ art: "idp_status", basis: BASIS });
  check(r.aktiv === true && r.ad_modus === "zusaetzlich", "Status zusaetzlich");

  u = umgebung({ server: { "/api/login/oidc/status": async () => ({ body: { aktiv: true, ad_modus: "quatsch" } }) } });
  r = await u.senden({ art: "idp_status", basis: BASIS });
  check(r.ad_modus === "fallback", "unbekannter ad_modus -> Vorgabe fallback", r.ad_modus);

  u = umgebung({ server: { "/api/login/oidc/status": async () => ({ body: { aktiv: false } }) } });
  r = await u.senden({ art: "idp_status", basis: BASIS });
  check(r.ok && r.aktiv === false, "Server ohne IdP -> aktiv false");

  u = umgebung({ server: { "/api/login/oidc/status": async () => new Error("Netz") } });
  r = await u.senden({ art: "idp_status", basis: BASIS });
  check(r.ok && r.aktiv === false, "Netzfehler -> aktiv false, kein Fehler");

  u = umgebung({ server: {} });
  r = await u.senden({ art: "idp_status", basis: BASIS });
  check(r.ok && r.aktiv === false, "alter Server (404) -> aktiv false");

  u = umgebung({ wurzel: "ohne_identity", server: { "/api/login/oidc/status": statusAn("fallback") } });
  r = await u.senden({ art: "idp_status", basis: BASIS });
  check(r.aktiv === false && u.spur.fetch.length === 0,
        "Browser ohne identity -> aktiv false, ohne Serveraufruf");

  u = umgebung({ server: { "/api/login/oidc/status": statusAn("fallback") } });
  r = await u.senden({ art: "idp_status", basis: "http://jarvis.beispiel.de" });
  check(r.aktiv === false && u.spur.fetch.length === 0, "http-Adresse -> kein Angebot");
}

// ── B2) Gelungene Anmeldung, je Wurzel ────────────────────────────────────
for (const wurzel of ["chrome", "browser", "gemischt"]) {
  const u = umgebung({
    wurzel,
    flow: (url, rueck) => {
      const q = new URL(url).searchParams;
      return rueck + "?code=C-123&zustand=" + encodeURIComponent(q.get("zustand"));
    },
    server: {
      "/api/login/oidc/app-einloesen": async () => ({ body: { success: true, token: "TOK-1",
                                                               username: "alice", is_admin: false } }),
      "/api/me": meOk,
    },
  });
  const r = await u.senden({ art: "idp_anmelden", basis: BASIS + "/" });
  check(r && r.ok && r.angemeldet === true && r.erlaubt === true && r.benutzer === "alice",
        "[" + wurzel + "] Anmeldung gelingt", JSON.stringify(r));
  const opt = u.spur.flow[0] || {};
  const su = opt.url ? new URL(opt.url) : null;
  const q = su ? su.searchParams : new URLSearchParams();
  check(!!su && su.origin === BASIS && su.pathname === "/api/login/oidc/start",
        "[" + wurzel + "] Start-Adresse auf dem Server", opt.url);
  check(q.get("app") === "browser", "[" + wurzel + "] app=browser");
  check(q.get("rueck") === u.rueck, "[" + wurzel + "] rueck = identity.getRedirectURL()", q.get("rueck"));
  check(/^[A-Za-z0-9_-]{43}$/.test(q.get("challenge") || ""), "[" + wurzel + "] challenge 43 Zeichen base64url");
  check(/^[A-Za-z0-9_-]{16,}$/.test(q.get("zustand") || ""), "[" + wurzel + "] zustand gesetzt");
  check(opt.interactive === true, "[" + wurzel + "] interactive: true");
  const e = u.spur.fetch.find((f) => f.pfad === "/api/login/oidc/app-einloesen");
  check(!!e && e.rumpf && e.rumpf.code === "C-123" && /^[A-Za-z0-9_-]{43}$/.test(e.rumpf.verifier || ""),
        "[" + wurzel + "] app-einloesen mit {code, verifier}", e && JSON.stringify(e.rumpf));
  check(!!e && !!e.rumpf && typeof e.rumpf.verifier === "string"
        && sha256b64url(e.rumpf.verifier) === q.get("challenge"),
        "[" + wurzel + "] challenge == base64url(SHA-256(verifier)) – nachgerechnet");
  check(!!e && !(e.opt.headers || {}).Authorization && e.opt.method === "POST",
        "[" + wurzel + "] Einloesen per POST ohne Token");
  check(u.ablage.sitzung && u.ablage.sitzung.token === "TOK-1" && u.ablage.sitzung.benutzer === "alice",
        "[" + wurzel + "] Sitzung geschrieben", JSON.stringify(u.ablage.sitzung));
  const me = u.spur.fetch.find((f) => f.pfad === "/api/me");
  check(!!me && (me.opt.headers || {}).Authorization === "Bearer TOK-1",
        "[" + wurzel + "] Freigabe mit dem neuen Token geprueft");
  check((u.ablage.einstellungen || {}).basis === BASIS, "[" + wurzel + "] Adresse gemerkt (ohne Schraegstrich)");
  check(!(u.ablage.einstellungen || {}).idp_meldung, "[" + wurzel + "] keine Meldung liegengelassen");
}

// ── B3) Zwei Anmeldungen haben verschiedene Geheimnisse ───────────────────
{
  const seen = [];
  const u = umgebung({ flow: (url) => { seen.push(new URL(url).searchParams); throw new Error("The user did not approve access."); } });
  await u.senden({ art: "idp_anmelden", basis: BASIS });
  await u.senden({ art: "idp_anmelden", basis: BASIS });
  check(seen.length === 2 && seen[0].get("challenge") !== seen[1].get("challenge")
        && seen[0].get("zustand") !== seen[1].get("zustand"),
        "jede Anmeldung erzeugt neuen verifier und zustand");
}

// ── B4) Falscher zustand -> verworfen, Code geht nirgends hin ─────────────
{
  const u = umgebung({
    flow: (url, rueck) => rueck + "?code=FREMD&zustand=untergeschoben",
    server: { "/api/login/oidc/app-einloesen": async () => ({ body: { success: true, token: "BOESE", username: "mallory" } }),
              "/api/me": meOk },
  });
  const r = await u.senden({ art: "idp_anmelden", basis: BASIS });
  check(r.ok && r.angemeldet === false, "falscher zustand -> nicht angemeldet");
  check(!u.spur.fetch.some((f) => f.pfad === "/api/login/oidc/app-einloesen"),
        "der fremde Code wird NICHT eingeloest");
  check(!(u.ablage.sitzung && u.ablage.sitzung.token), "keine Sitzung geschrieben");
  check(r.abgebrochen === false && /gehört nicht zu diesem Vorgang/.test(r.text || ""),
        "Klartext statt stiller Verwurf", r.text);
  check((u.ablage.einstellungen || {}).idp_kennwort === true && !!(u.ablage.einstellungen || {}).idp_meldung,
        "fuer ein geschlossenes Fenster gemerkt: Meldung + Kennwortmaske auf");
}

// ── B5) Rueckkehr an eine fremde Adresse ─────────────────────────────────
{
  const u = umgebung({ flow: (url) => "https://boese.beispiel/?code=X&zustand=" + new URL(url).searchParams.get("zustand"),
                       server: { "/api/login/oidc/app-einloesen": async () => ({ body: { success: true, token: "X", username: "x" } }) } });
  const r = await u.senden({ art: "idp_anmelden", basis: BASIS });
  check(r.angemeldet === false && !u.spur.fetch.some((f) => f.pfad === "/api/login/oidc/app-einloesen"),
        "Rueckkehr an eine fremde Adresse wird nicht eingeloest");
}

// ── B6) Fehlerkennung vom Server ─────────────────────────────────────────
{
  const u = umgebung({ flow: (url, rueck) => rueck + "?fehler=keine_freigabe&zustand="
                         + new URL(url).searchParams.get("zustand") });
  const r = await u.senden({ art: "idp_anmelden", basis: BASIS });
  check(r.ok && r.angemeldet === false && r.text === "Keine Anmeldeberechtigung.",
        "fehler=keine_freigabe -> deutscher Klartext", r.text);
  check(r.abgebrochen === false, "ein Fehler ist kein Abbruch (Kennwortmaske geht auf)");
  check(u.spur.fetch.length === 0, "bei Fehlerkennung kein Einloesen");
  const u2 = umgebung({ flow: (url, rueck) => rueck + "?fehler=unbekannt_neu&zustand="
                          + new URL(url).searchParams.get("zustand") });
  const r2 = await u2.senden({ art: "idp_anmelden", basis: BASIS });
  check(/fehlgeschlagen/.test(r2.text || ""), "unbekannte Kennung -> allgemeiner Satz", r2.text);
  // Alle vom Server vereinbarten Kennungen haben einen eigenen Text.
  const kennungen = ["nicht_eingerichtet", "zu_viele", "abgelaufen", "abgebrochen", "nicht_erreichbar",
                     "konfiguration", "idp", "token", "schluessel", "name", "lokal", "gesperrt",
                     "keine_freigabe", "pruefung", "lizenz"];
  const fehlend = [];
  for (const k of kennungen) {
    const ux = umgebung({ flow: (url, rueck) => rueck + "?fehler=" + k + "&zustand="
                            + new URL(url).searchParams.get("zustand") });
    const rx = await ux.senden({ art: "idp_anmelden", basis: BASIS });
    if (/fehlgeschlagen\. Bitte mit Kennwort/.test(rx.text || "")) fehlend.push(k);
  }
  check(fehlend.length === 0, "jede vereinbarte Kennung hat einen eigenen Text", fehlend.join(","));
}

// ── B7) Abbruch durch den Benutzer ───────────────────────────────────────
{
  const u = umgebung({ flow: () => { throw new Error("The user did not approve access."); } });
  const r = await u.senden({ art: "idp_anmelden", basis: BASIS });
  check(r.ok === true, "Abbruch ist KEIN Fehler fuer das Fenster (ok:true, keine Ausnahme)");
  check(r.angemeldet === false && r.abgebrochen === true, "abgebrochen: true");
  check(/abgebrochen/.test(r.text || "") && (r.text || "").split(/[.!]\s/).length <= 2,
        "EIN ruhiger Satz", r.text);
  check((u.ablage.einstellungen || {}).idp_kennwort === false, "Abbruch klappt die Kennwortmaske NICHT auf");
  const u2 = umgebung({ flow: () => { throw new Error("Authorization page could not be loaded."); } });
  const r2 = await u2.senden({ art: "idp_anmelden", basis: BASIS });
  check(r2.abgebrochen === false && /ließ sich nicht öffnen/.test(r2.text || ""),
        "anderer Fehler beim Oeffnen wird benannt", r2.text);
}

// ── B8) Einloesen scheitert ──────────────────────────────────────────────
{
  const u = umgebung({
    flow: (url, rueck) => rueck + "?code=C&zustand=" + new URL(url).searchParams.get("zustand"),
    server: { "/api/login/oidc/app-einloesen": async () => ({ status: 400, body: { success: false,
                                                       error: "Der Code ist abgelaufen." } }) },
  });
  const r = await u.senden({ art: "idp_anmelden", basis: BASIS });
  check(r.angemeldet === false && r.text === "Der Code ist abgelaufen.", "Serverfehler beim Einloesen im Klartext", r.text);
  check(!(u.ablage.sitzung && u.ablage.sitzung.token), "keine Sitzung bei gescheitertem Einloesen");
}

// ── B9) Ohne identity: kein Ablauf ───────────────────────────────────────
{
  const u = umgebung({ wurzel: "ohne_identity" });
  const r = await u.senden({ art: "idp_anmelden", basis: BASIS });
  check(r.ok && r.angemeldet === false && u.spur.fetch.length === 0,
        "ohne identity -> Klartext, kein Aufruf", r.text);
}

// ── B10) Zustand liefert die gemerkte Meldung ────────────────────────────
{
  const u = umgebung({ flow: (url, rueck) => rueck + "?fehler=lizenz&zustand=" + new URL(url).searchParams.get("zustand") });
  await u.senden({ art: "idp_anmelden", basis: BASIS });
  const z = await u.senden({ art: "zustand" });
  check(z.idp_meldung === "Die Zahl der Benutzer für diese Lizenz ist erreicht." && z.idp_kennwort === true,
        "zustand meldet ein verpasstes Ergebnis samt Maske-auf", JSON.stringify([z.idp_meldung, z.idp_kennwort]));
  await u.senden({ art: "merken", idp_meldung: "", idp_kennwort: false });
  const z2 = await u.senden({ art: "zustand" });
  check(z2.idp_meldung === "" && z2.idp_kennwort === false, "nach dem Zeigen geleert");
}

// ═══════════════════════════════════════════════════════════════════════════
section("C) Fenster: echte popup.js-Teile gegen die echte popup.html");
// ═══════════════════════════════════════════════════════════════════════════
function schneide(name) {
  const kopf = new RegExp("(?:async )?function " + name + "\\([^)]*\\)\\s*\\{");
  const m = kopf.exec(POPUP_JS);
  if (!m) return null;
  let tiefe = 0;
  for (let i = m.index + m[0].length - 1; i < POPUP_JS.length; i++) {
    const c = POPUP_JS[i];
    if (c === "{") tiefe++;
    else if (c === "}") { tiefe--; if (tiefe === 0) return POPUP_JS.slice(m.index, i + 1); }
  }
  return null;
}
function teile(start, gestellt) {
  const G = new Set(gestellt), drin = new Set(), aus = [], offen = start.slice();
  while (offen.length) {
    const n = offen.shift();
    if (drin.has(n) || G.has(n)) continue;
    const k = schneide(n);
    if (!k) continue;
    drin.add(n); aus.push(k);
    for (const t of k.match(/\b[A-Za-z_$][\w$]*(?=\s*\()/g) || []) {
      if (!drin.has(t) && !G.has(t) && schneide(t)) offen.push(t);
    }
  }
  return { aus, drin };
}
function rumpf(id) {
  const re = new RegExp('\\$\\("' + id + '"\\)\\.addEventListener\\("click", (?:async )?\\(\\) => \\{([\\s\\S]*?)\\n\\}\\);');
  return (POPUP_JS.match(re) || [])[1] || null;
}
const MODUL_LETS = ["_idpStatus", "_kennwortOffen", "_idpMeldung"].map((n) =>
  (POPUP_JS.match(new RegExp("let " + n + " = .*;")) || [""])[0]);
if (MODUL_LETS.some((z) => !z)) abbruch("Modulvariablen der IdP-Anzeige nicht gefunden");
const R_IDP = rumpf("btn-idp"), R_LINK = rumpf("btn-kennwort-zeigen");
if (!R_IDP || !R_LINK) abbruch("Klick-Rumpfe von btn-idp / btn-kennwort-zeigen nicht schneidbar");

const STUBS = ["frage", "brandingHolen", "angemeldetEinrichten", "leisteBeobachten",
               "zugriffSichern", "zugriffAnzeigen", "markeAnwenden", "tabErmitteln",
               "leisteFeststellen", "ansichtZeigen", "autoZeigen", "wechselZeigen",
               "einstAbschnittZeigen", "hatZugriff", "ticketLageAnwenden", "_vorgabeBasis",
               "knoepfeAktualisieren", "meldungPlatzieren"];
const { aus: T, drin: D } = teile(["idpZeigen", "idpPruefen", "nachAnmeldung", "melde", "sperre",
                                   "zeige", "start"], STUBS);
for (const n of ["idpZeigen", "idpPruefen", "nachAnmeldung", "start"]) {
  if (!D.has(n)) abbruch("popup.js hat " + n + "() nicht");
}

/** Ein Fenster mit gestelltem Hintergrund. `antwort(n)` beantwortet frage(). */
function fenster(antwort) {
  const dom = new JSDOM(POPUP_HTML, { url: "https://x.test/", runScripts: "outside-only" });
  const w = dom.window;
  const code = `
    const spur = [];
    const $ = (id) => document.getElementById(id);
    const el = {
      login: $("bereich-login"), arbeit: $("bereich-arbeit"),
      basis: $("f-basis"), benutzer: $("f-benutzer"), kennwort: $("f-kennwort"),
      totp: $("f-totp"), meldung: $("meldung"), abmelden: $("btn-abmelden"),
      reset: $("btn-reset"), ergebnis: $("ergebnis"),
    };
    const STAND = 10; let _standAlt = false, _standGesehen;
    let _key = "ABC-1", _laeuft = false, _marke = "Marke";
    ${MODUL_LETS.join("\n")}
    async function frage(n) { spur.push(n.art + (n.art === "merken" ? ":" + JSON.stringify(n) : ""));
                              const r = await antwort(n); if (!r || !r.ok) throw new Error((r && r.fehler) || "x"); return r; }
    function brandingHolen() {} function angemeldetEinrichten(w) { spur.push("einrichten:" + w); }
    function leisteBeobachten() {} async function zugriffSichern() { spur.push("zugriff"); return true; }
    async function zugriffAnzeigen() {} function markeAnwenden() {} async function tabErmitteln() {}
    function leisteFeststellen() {} function ansichtZeigen() {} function autoZeigen() {}
    function wechselZeigen() {} function einstAbschnittZeigen() {} async function hatZugriff() { return true; }
    async function ticketLageAnwenden() {} function _vorgabeBasis() { return ""; }
    function knoepfeAktualisieren() {} function meldungPlatzieren() {}
    ${T.join("\n")}
    return {
      spur, el, $,
      klickIdp: async () => { ${R_IDP} },
      klickLink: () => { ${R_LINK} },
      idpZeigen, idpPruefen, start,
      offen: () => _kennwortOffen,
    };`;
  const f = new w.Function("antwort", code);
  return Object.assign(f.call(w, antwort), { w });
}
const sichtbar = (e) => !!e && !e.hidden;

// ── C1) Anzeige je Lage ──────────────────────────────────────────────────
{
  const F = fenster(async () => ({ ok: true }));
  const blk = F.$("idp-block"), kw = F.$("kennwort-block"), link = F.$("btn-kennwort-zeigen");
  F.idpZeigen({ aktiv: false });
  check(!sichtbar(blk) && sichtbar(kw), "ohne IdP: kein Knopf, Kennwortmaske wie bisher");
  F.idpZeigen({ aktiv: true, ad_modus: "fallback" });
  check(sichtbar(blk) && !sichtbar(kw) && sichtbar(link),
        "fallback: Knopf da, Kennwortmaske eingeklappt, Link da");
  F.idpZeigen({ aktiv: true, ad_modus: "zusaetzlich" });
  check(sichtbar(blk) && sichtbar(kw) && !sichtbar(link),
        "zusaetzlich: Knopf UND Kennwortmaske, kein Link");
  F.idpZeigen({ aktiv: true, ad_modus: "fallback" });
  F.klickLink();
  check(sichtbar(kw) && !sichtbar(link) && sichtbar(blk), "Link klappt die Kennwortmaske auf, Knopf bleibt");
  F.w.close();
}

// ── C2) idpPruefen fragt mit der Adresse aus dem Feld ────────────────────
{
  let gesehen = null;
  const F = fenster(async (n) => { if (n.art === "idp_status") { gesehen = n.basis; return { ok: true, aktiv: true, ad_modus: "fallback" }; } return { ok: true }; });
  F.el.basis.value = "https://s.test";
  await F.idpPruefen();
  check(gesehen === "https://s.test" && sichtbar(F.$("idp-block")), "idpPruefen fragt mit dem Feldwert und zeigt den Knopf");
  const G = fenster(async () => ({ ok: false, fehler: "Unbekannte Anfrage" }));
  G.el.basis.value = "https://s.test";
  await G.idpPruefen();
  check(!sichtbar(G.$("idp-block")) && sichtbar(G.$("kennwort-block")),
        "alter Hintergrund (Fehler) -> Maske wie bisher");
  F.w.close(); G.w.close();
}

// ── C3) Klick auf den Knopf ──────────────────────────────────────────────
async function klickMit(ergebnis) {
  const F = fenster(async (n) => {
    if (n.art === "idp_anmelden") return Object.assign({ ok: true }, ergebnis);
    return { ok: true };
  });
  F.idpZeigen({ aktiv: true, ad_modus: "fallback" });
  F.el.basis.value = "https://s.test";
  await F.klickIdp();
  return F;
}
{
  const F = await klickMit({ angemeldet: true, erlaubt: true, hinweis: "", benutzer: "alice" });
  check(F.spur.indexOf("zugriff") >= 0 && F.spur.indexOf("zugriff") < F.spur.indexOf("idp_anmelden"),
        "ERST das Zugriffsrecht, DANN die Anmeldung", JSON.stringify(F.spur));
  check(sichtbar(F.el.arbeit) && !sichtbar(F.el.login), "Erfolg: Arbeitsbereich offen");
  check(F.spur.includes("einrichten:alice"), "Erfolg: Arbeitsbereich fuer den Benutzer aus der Antwort eingerichtet");
  check(F.spur.some((s) => /merken:.*"idp_meldung":""/.test(s)), "die gemerkte Meldung wird geleert");
  F.w.close();
}
{
  const F = await klickMit({ angemeldet: false, abgebrochen: false, text: "Keine Anmeldeberechtigung." });
  check(F.el.meldung.textContent.includes("Keine Anmeldeberechtigung."), "Fehler: Klartext steht da", F.el.meldung.textContent);
  check(sichtbar(F.$("kennwort-block")), "Fehler: der Notweg geht von selbst auf");
  check(!sichtbar(F.el.arbeit), "Fehler: kein Arbeitsbereich");
  F.w.close();
}
{
  const F = await klickMit({ angemeldet: false, abgebrochen: true, text: "Anmeldung über das Firmenkonto abgebrochen." });
  check(!sichtbar(F.$("kennwort-block")), "Abbruch: Kennwortmaske bleibt eingeklappt");
  check(F.el.meldung.textContent === "Anmeldung über das Firmenkonto abgebrochen.",
        "Abbruch: genau ein ruhiger Satz", F.el.meldung.textContent);
  F.w.close();
}
{
  const F = fenster(async () => ({ ok: true }));
  F.idpZeigen({ aktiv: true, ad_modus: "fallback" });
  F.el.basis.value = "http://s.test";
  await F.klickIdp();
  check(!F.spur.includes("idp_anmelden") && /https:\/\//.test(F.el.meldung.textContent),
        "http-Adresse: keine Anmeldung, Hinweis");
  F.w.close();
}

// ── C4) start(): verpasstes Ergebnis wird einmal gezeigt ─────────────────
{
  const z = { ok: true, angemeldet: false, basis: "https://s.test", stand: 10,
              idp_meldung: "Keine Anmeldeberechtigung.", idp_kennwort: true };
  const F = fenster(async (n) => {
    if (n.art === "zustand") return z;
    if (n.art === "idp_status") return { ok: true, aktiv: true, ad_modus: "fallback" };
    return { ok: true };
  });
  await F.start();
  check(F.el.meldung.textContent.includes("Keine Anmeldeberechtigung."), "start zeigt die verpasste Meldung",
        F.el.meldung.textContent);
  check(sichtbar(F.$("kennwort-block")) && sichtbar(F.$("idp-block")),
        "nach gescheitertem Versuch: Kennwortmaske offen, Knopf da");
  check(F.spur.some((s) => /merken:.*"idp_meldung":""/.test(s)), "und raeumt die Meldung ab (einmalig)");

  const z2 = Object.assign({}, z, { idp_meldung: "", idp_kennwort: false });
  const G = fenster(async (n) => n.art === "zustand" ? z2
    : n.art === "idp_status" ? { ok: true, aktiv: true, ad_modus: "fallback" } : { ok: true });
  await G.start();
  check(sichtbar(G.$("idp-block")) && !sichtbar(G.$("kennwort-block")),
        "regulaerer Start mit IdP (fallback): Knopf, Kennwortmaske eingeklappt");
  F.w.close(); G.w.close();
}

bilanz = true;
clearTimeout(hund);
await new Promise((r) => setImmediate(r));
console.log("\n" + ok + " OK, " + fail + " FAIL");
process.exit(fail ? 1 : 0);
})().catch((e) => { console.log("ABBRUCH: " + ((e && e.stack) || e)); process.exit(2); });
