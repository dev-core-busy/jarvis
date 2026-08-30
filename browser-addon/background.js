/* Hintergrund: HIER laufen ALLE Netzaufrufe – und das ist keine Stilfrage.
 *
 * Unter Manifest V3 unterliegen Content-Scripts derselben CORS-Regel wie die
 * Seite, in der sie laufen; host_permissions wirken dort NICHT (MDN: "Only
 * backend scripts have elevated cross-domain privileges"). Der Jarvis-Server
 * traegt eine enge CORS-Liste – live gemessen antwortet er einem Preflight von
 * `chrome-extension://…` mit **400 Disallowed CORS origin**. Aus dem
 * Hintergrund entsteht dieser Preflight gar nicht erst.
 *
 * Wer einen dieser fetch-Aufrufe ins Content-Script oder in das Popup
 * verschiebt, bricht die Erweiterung also – und zwar mit einer Meldung, die
 * nach einem Serverfehler aussieht.
 *
 * Das Popup waere als Extension-Page zwar ebenfalls privilegiert, ist aber der
 * falsche Ort: es schliesst sich, sobald der Benutzer daneben klickt, und
 * nimmt einen laufenden Aufruf mit. Eine Auswertung dauert rund 13 Sekunden.
 */

const api = (typeof browser !== "undefined") ? browser : chrome;

// Serveradresse steht NICHT im Manifest, sondern in den Einstellungen.
// Grund: eine Firefox-Erweiterung muss von Mozilla signiert sein, auch die
// selbst verteilte ("All add-ons must be submitted for signing, even if you
// distribute them outside AMO"). Eine signierte Datei laesst sich nicht pro
// Server umschreiben, ohne die Signatur zu brechen. Damit scheidet der Weg des
// Outlook-Add-ins aus, wo das Manifest je Server erzeugt wird – und die
// Drift-Falle "eine Kopie je Installation" gleich mit.
/* STAND DES HINTERGRUND-CODES – muss mit `STAND` in popup.js uebereinstimmen.
 *
 * ⚠ WOFUER DAS DA IST: Chrome liest die Popup-SEITE bei jedem Oeffnen frisch
 * von der Platte, behaelt den **Service-Worker** aber im Speicher. Wer die
 * Erweiterung aktualisiert, ohne sie in `chrome://extensions` neu zu laden,
 * bekommt damit ein NEUES Fenster und einen ALTEN Hintergrund. Gemeldet
 * 2026-08-30: Klick auf den Ansichts-Schalter antwortete „Unbekannte
 * Anfrage." – das ist der `default`-Zweig unten, und er sagte nicht, was zu
 * tun ist.
 * Bei jeder Aenderung an den Nachrichtenfaellen HOCHZAEHLEN. Ein Test
 * vergleicht beide Zahlen. */
const STAND = 4;

const EINST = "einstellungen";   // storage.local: { basis }
const SITZUNG = "sitzung";       // storage.local: { token, benutzer }
const ERGEBNIS = "ergebnis";     // storage.local: letzter Lauf (siehe unten)

async function einstLesen() {
  const d = await api.storage.local.get(EINST);
  return d[EINST] || {};
}

async function basisLesen() {
  return ((await einstLesen()).basis || "").replace(/\/+$/, "");
}

/* Adresse und Benutzername ueberleben das Schliessen des Fensters – und das
 * ist keine Bequemlichkeit, sondern die zweite Haelfte des Fixes zur Meldung
 * "man muss sich 2x anmelden".
 *
 * Fehlt das Host-Zugriffsrecht, muss das Fenster es erfragen, und **Chrome
 * schliesst dabei das Popup**. Ohne Gedaechtnis stuende danach eine leere
 * Maske da: der Benutzer haette getippt, nichts waere passiert, und er
 * muesste alles noch einmal eingeben. Gemerkt wird VOR der Nachfrage.
 *
 * ⚠ DAS KENNWORT WIRD NIE GEMERKT. Der Benutzername ist eine Bequemlichkeit,
 * das Kennwort waere eine gespeicherte Zugangsberechtigung ohne Ablauf – und
 * es wird ohnehin nur einmal gebraucht, danach traegt das Token.
 */
async function einstSchreiben(teil) {
  const alt = await einstLesen();
  const neu = Object.assign({}, alt);
  if (teil.basis !== undefined) neu.basis = String(teil.basis).replace(/\/+$/, "");
  if (teil.benutzer !== undefined) neu.benutzer = String(teil.benutzer);
  if (teil.zugriff_erfragt !== undefined) neu.zugriff_erfragt = !!teil.zugriff_erfragt;
  /* NUR ZWEI WERTE, und alles Unbekannte wird zu "popup".
   * Der Wert steuert, ob der Klick auf das Symbol ein Popup oeffnet oder die
   * Seitenleiste. Ein Tippfehler in der Ablage (oder ein aelterer Stand, der
   * das Feld gar nicht kennt) darf nicht in einem dritten, undefinierten
   * Zustand enden - dann oeffnet gar nichts mehr, und niemand sieht warum. */
  if (teil.ansicht !== undefined) neu.ansicht = (teil.ansicht === "leiste") ? "leiste" : "popup";
  await api.storage.local.set({ [EINST]: neu });
  return neu;
}

/* ── Popup oder Seitenleiste ────────────────────────────────────────────────
 *
 * DIE LEISTE IST KEIN ZWEITES FENSTER, sondern dieselbe `popup.html` – nur mit
 * `?ansicht=leiste` davor (ansicht.js macht daraus eine Klasse am <html>). Eine
 * zweite Oberflaeche waere eine Kopie, und Kopien laufen auseinander.
 *
 * ZWEI APIS, EIN VERHALTEN: Chrome kennt `sidePanel` (ab 114), Firefox kennt
 * `sidebarAction` – und keiner der beiden kennt den jeweils anderen. Deshalb
 * wird hier auf VORHANDENSEIN geprueft, nicht auf den Browsernamen: eine
 * Abfrage des User-Agent waere beim naechsten Fork falsch.
 *
 * DER UMSCHALTER IST `action.setPopup`. Solange ein Popup gesetzt ist, gewinnt
 * es – `openPanelOnActionClick` bleibt dann wirkungslos und `onClicked` feuert
 * nicht. Erst ein LEERER Popup-Pfad gibt den Klick frei.
 */
/* ── Herstellereigene APIs: NICHT ueber `api` ansprechen ───────────────────
 *
 * ⚠ HIER LAG DER FEHLER, DER DREI RUNDEN GEKOSTET HAT (gemeldet 2026-08-30).
 *
 * `api` ist `browser ?? chrome`. Chrome (152) definiert inzwischen selbst ein
 * `browser`-Objekt – aber `sidePanel` ist eine **Chrome-eigene** API und steht
 * dort NICHT drin. `api.sidePanel` war damit `undefined`, obwohl
 * `chrome.sidePanel` existiert und die Leiste nachweislich funktioniert.
 * Folge: `setPanelBehavior` und `setOptions` liefen ins Leere (der Klick aufs
 * Symbol oeffnete nie die Leiste), und die Faehigkeitspruefung meldete „dieser
 * Browser stellt keine Seitenleiste bereit" – auf einem Browser, der sie
 * bereitstellt.
 *
 * Merkregel: `browser ?? chrome` taugt nur fuer STANDARDISIERTE APIs. Was nur
 * ein Hersteller kennt (`sidePanel` in Chrome, `sidebarAction` in Firefox),
 * wird an BEIDEN Wurzeln gesucht.
 */
function _wurzeln() {
  const w = [];
  if (typeof chrome !== "undefined" && chrome) w.push(chrome);
  if (typeof browser !== "undefined" && browser && w.indexOf(browser) === -1) {
    w.push(browser);
  }
  return w;
}

/** Sucht einen API-Zweig an beiden Wurzeln. `null`, wenn es ihn nirgends gibt. */
function zweig(name, methode) {
  for (const w of _wurzeln()) {
    const z = w[name];
    if (z && (!methode || typeof z[methode] === "function")) return z;
  }
  return null;
}

const LEISTE_PFAD = "popup.html?ansicht=leiste";

/** Das Bedienelement in der Symbolleiste – in MV3 `action`, sonst `browserAction`. */
function aktion() {
  return api.action || api.browserAction || null;
}

/** Gibt es ueberhaupt eine Leiste? Firefox < 115 und aeltere Chrome kennen keine. */
function leisteMoeglich() {
  /* DAS MANIFEST IST DIE VERLAESSLICHSTE AUSKUNFT: hat der Browser die
   * Erweiterung MIT dem Leisten-Schluessel geladen, gibt es die Leiste – ganz
   * unabhaengig davon, unter welchem Namen die API im JS erreichbar ist. Die
   * API-Abfrage bleibt als zweiter Weg daneben stehen. */
  try {
    const m = api.runtime.getManifest() || {};
    if (m.side_panel || m.sidebar_action) return true;
  } catch (e) { /* dann entscheidet die API-Abfrage */ }
  return !!(zweig("sidePanel", "setOptions") || zweig("sidebarAction", "setPanel"));
}

/** Stellt den gewuenschten Modus im Browser her.
 *
 * JEDER Teilschritt ist einzeln abgesichert: schlaegt einer fehl, sollen die
 * uebrigen trotzdem wirken. Ein `sidePanel`, das sich nicht konfigurieren
 * laesst, darf nicht dazu fuehren, dass auch der Popup-Pfad ungesetzt bleibt –
 * dann oeffnet der Klick GAR NICHTS, und das ist der schlechteste Ausgang.
 */
async function ansichtAnwenden(modus) {
  const leiste = (modus === "leiste");
  const a = aktion();
  if (a && a.setPopup) {
    // Leer = der Klick faellt an `onClicked` bzw. an das Panel-Verhalten.
    try { await a.setPopup({ popup: leiste ? "" : "popup.html" }); } catch (e) {}
  }
  const panel = zweig("sidePanel", "setOptions");
  const leisteFf = zweig("sidebarAction", "setPanel");
  if (panel) {
    /* DER ABFRAGETEIL WIRD HIER GESETZT, NICHT IM MANIFEST. Fuer `setOptions`
     * ist ein Pfad mit `?…` belegt, fuer `side_panel.default_path` nicht – und
     * ein Manifest, das der Browser ablehnt, macht die ganze Erweiterung
     * uninstallierbar. Faellt der Aufruf aus, laedt die Leiste ohne
     * Abfrageteil: schmal, aber benutzbar. */
    try {
      await panel.setOptions({ path: LEISTE_PFAD, enabled: true });
    } catch (e) {
      /* Nimmt dieser Chrome keinen Abfrageteil im Pfad, wenigstens den nackten
       * Pfad setzen - sonst bliebe die Leiste ganz abgeschaltet. Die Erkennung
       * haengt ohnehin nicht mehr daran (kontextArt). */
      try {
        await panel.setOptions({ path: "popup.html", enabled: true });
      } catch (e2) {}
    }
    try {
      await panel.setPanelBehavior({ openPanelOnActionClick: leiste });
    } catch (e) {}
  } else if (leisteFf) {
    // Firefox verlangt eine vollstaendige Adresse, keinen relativen Pfad.
    try {
      await leisteFf.setPanel({ panel: api.runtime.getURL(LEISTE_PFAD) });
    } catch (e) {}
  }
}

/** Was ist der Absender dieser Nachricht – Popup oder Seitenleiste?
 *
 * ⚠ DAS IST DIE EIGENTLICHE ERKENNUNG. Bis hierher haing sie am Abfrageteil
 * `?ansicht=leiste`, den `setOptions`/`setPanel` in den Pfad schreiben. Der
 * kommt aber NUR mit, wenn die Leiste ueber unseren Weg geoeffnet wird –
 * oeffnet der Benutzer sie ueber **Chromes eigene Seitenleisten-Auswahl**,
 * laedt Chrome `side_panel.default_path`, also `popup.html` ohne Abfrageteil.
 * Das Fenster hielt sich dann fuer ein Popup: keine Tab-Zuhoerer, feste
 * Breite. Genau so gemeldet (2026-08-30, Chrome 152).
 *
 * `runtime.getContexts` beantwortet die Frage am Absender selbst und ist von
 * jedem Oeffnungsweg unabhaengig. Faellt es aus (aeltere Browser, Firefox),
 * bleibt der Abfrageteil als Rueckfall – deshalb wird er weiterhin gesetzt.
 */
async function kontextArt(absender) {
  try {
    if (!api.runtime.getContexts || !absender || !absender.documentId) return "";
    const k = await api.runtime.getContexts(
      { documentIds: [absender.documentId] });
    return (k && k[0] && k[0].contextType) || "";
  } catch (e) {
    return "";
  }
}

async function ansichtLesen() {
  return ((await einstLesen()).ansicht === "leiste") ? "leiste" : "popup";
}

/* WIRD BEI JEDEM START DES HINTERGRUNDS GERUFEN – und das ist noetig, nicht
 * vorsichtshalber: unter MV3 wird der Service-Worker beendet, sobald er nichts
 * zu tun hat. `setPopup` gilt nur fuer die laufende Browsersitzung; ohne
 * Wiederherstellung stuende nach dem naechsten Browserstart wieder das Popup
 * da, obwohl der Benutzer die Leiste gewaehlt hat. */
async function ansichtHerstellen() {
  try { await ansichtAnwenden(await ansichtLesen()); } catch (e) {}
}

api.runtime.onInstalled.addListener(() => { ansichtHerstellen(); });
api.runtime.onStartup.addListener(() => { ansichtHerstellen(); });
ansichtHerstellen();

/* Der Klick auf das Symbol, wenn KEIN Popup gesetzt ist.
 *
 * ⚠ HIER DARF VOR DEM OEFFNEN KEIN `await` STEHEN. Sowohl `sidePanel.open()`
 * als auch `sidebarAction.toggle()` verlangen eine Benutzergeste, und die ist
 * nach dem ersten `await` verbraucht – der Aufruf scheitert dann mit "may only
 * be called in response to a user gesture", also mit einer Meldung, die kein
 * Benutzer je zu sehen bekommt, weil einfach nichts passiert.
 * Den Modus nachzulesen ist auch unnoetig: steht ein Popup, feuert `onClicked`
 * gar nicht erst.
 */
const _aktion = aktion();
if (_aktion && _aktion.onClicked) {
  _aktion.onClicked.addListener((tab) => {
    const ff = zweig("sidebarAction", "toggle");
    if (ff) { ff.toggle().catch(() => {}); return; }
    const cp = zweig("sidePanel", "open");
    if (cp && tab) cp.open({ windowId: tab.windowId }).catch(() => {});
  });
}

/* DAS TOKEN LIEGT IN storage.LOCAL – geaendert auf Meldung aus dem Betrieb
 * ("Anmeldung verschwindet generell bei Chrome Neustart").
 *
 * Vorher stand es in `storage.session` mit der Begruendung, es solle den
 * Browser nicht ueberleben. Das war eine Sicherheitsentscheidung ohne
 * Gegenwert: das Portal legt sein Token seit jeher in den `localStorage`,
 * derselbe Rechner, dieselbe Person, dasselbe Token. Wer die Platte lesen kann,
 * findet es dort ohnehin – die Erweiterung war also strenger als die Anwendung,
 * fuer die sie arbeitet, und der Preis war eine Anmeldung bei jedem
 * Browserstart.
 *
 * Was die Grenze weiterhin haelt: das Token laeuft serverseitig ab, `401`
 * verwirft es hier sofort (siehe `ruf`), und Abmelden loescht es.
 */
async function tokenLesen() {
  const d = await api.storage.local.get(SITZUNG);
  return (d[SITZUNG] || {}).token || "";
}

async function sitzungSchreiben(wert) {
  await api.storage.local.set({ [SITZUNG]: wert || {} });
}

/* Das letzte Ergebnis ueberlebt das Schliessen des Fensters.
 *
 * Ein Browser-Popup schliesst, sobald der Benutzer daneben klickt – auch beim
 * Wechsel in den Jira-Tab, um das Kommentarfeld zu oeffnen. Ohne Gedaechtnis
 * ist eine 13 Sekunden lange Auswertung dann weg, und der einzige Weg zurueck
 * ist, sie erneut zu bezahlen.
 *
 * Gespeichert wird der BEARBEITETE Text: der Benutzer soll seine Aenderungen
 * nicht verlieren. Dazu die Ticketnummer – ohne sie waere beim naechsten
 * Oeffnen nicht erkennbar, zu welchem Vorgang der Text gehoert, und das ist
 * gefaehrlicher als kein Text.
 */
async function ergebnisLesen() {
  const d = await api.storage.local.get(ERGEBNIS);
  return d[ERGEBNIS] || null;
}

async function ergebnisSchreiben(wert) {
  if (wert) await api.storage.local.set({ [ERGEBNIS]: wert });
  else await api.storage.local.remove(ERGEBNIS);
}

/** Ein Aufruf an Jarvis. Wirft mit KLARTEXT – der Text geht 1:1 ins Popup. */
async function ruf(pfad, { methode = "GET", rumpf = null, mitToken = true } = {}) {
  const basis = await basisLesen();
  if (!basis) throw new Error("Es ist keine {marke}-Adresse hinterlegt.");

  const kopf = { "Content-Type": "application/json" };
  if (mitToken) {
    const t = await tokenLesen();
    if (!t) throw new Error("Nicht angemeldet.");
    kopf["Authorization"] = "Bearer " + t;
  }

  let antwort;
  try {
    antwort = await fetch(basis + pfad, {
      method: methode,
      headers: kopf,
      body: rumpf ? JSON.stringify(rumpf) : undefined,
      // KEINE Cookies. Jarvis authentifiziert ueber den Bearer-Header; ein
      // "include" wuerde nur die CORS-Regeln verschaerfen, ohne etwas zu
      // gewinnen.
      credentials: "omit",
    });
  } catch (e) {
    // Der haeufigste Fall dahinter ist KEIN Netzausfall, sondern ein
    // Zertifikat, das nicht zur aufgerufenen Adresse passt. Im Hintergrund gibt
    // es dafuer kein "trotzdem fortfahren" – der Aufruf bricht wortlos ab.
    // Genau dieser Fehler hat beim Outlook-Add-in Tage gekostet.
    throw new Error(
      "Der Server ist nicht erreichbar (" + (e && e.message ? e.message : "?") + ").\n" +
      "Häufigste Ursache: die Adresse passt nicht zum Serverzertifikat. Rufe " +
      "{marke} unter genau dem Namen auf, auf den das Zertifikat lautet – nicht " +
      "über die IP-Adresse.");
  }

  if (antwort.status === 401) {
    await sitzungSchreiben({});
    throw new Error("Die Anmeldung ist abgelaufen. Bitte neu anmelden.");
  }

  let daten = null;
  try { daten = await antwort.json(); } catch (e) { daten = null; }

  if (!antwort.ok) {
    // Jarvis antwortet bei fachlichem Fehlschlag mit 400 und Klartext in
    // `error` bzw. `detail` (403 der Freigabe). Ein "HTTP 400" allein waere
    // fuer den Benutzer wertlos.
    const txt = (daten && (daten.error || daten.detail))
      || ("Der Server meldet HTTP " + antwort.status + ".");
    throw new Error(String(txt));
  }
  return daten || {};
}

/** Marke, Farbe und Logo des Servers – OHNE Anmeldung abrufbar.
 *
 * `/api/branding` haengt bewusst an keiner Anmeldung (es wird schon auf der
 * Loginseite gebraucht). Deshalb kann das Fenster sein Aussehen setzen, sobald
 * eine Adresse eingetragen ist – also VOR dem ersten Anmelden, genau dann,
 * wenn jemand zum ersten Mal hinsieht.
 *
 * Fehlschlag ist KEIN Fehler: ohne Branding bleibt das eingebaute Aussehen.
 */
async function branding() {
    try {
        const b = await ruf("/api/branding", { mitToken: false });
        return (b && b.active) ? b : null;
    } catch (e) {
        return null;
    }
}

async function anmelden({ basis, benutzer, kennwort, totp }) {
  // Der Merker der Berechtigungsabfrage faellt hier weg: sie ist erledigt,
  // sonst waeren wir nicht bis zur Anmeldung gekommen.
  await einstSchreiben({ basis, benutzer, zugriff_erfragt: false });
  const d = await ruf("/api/login", {
    methode: "POST", mitToken: false,
    rumpf: {
      username: benutzer,
      password: kennwort,
      // ⚠ DAS FELD HEISST `totp_code`. Im Outlook-Add-in stand hier einmal
      // `totp`, und das Ergebnis war eine Anmeldeschleife OHNE Fehlermeldung –
      // der Server sah schlicht keinen Code. Ein Test vergleicht den Namen
      // gegen app.js.
      totp_code: totp || "",
    },
  });
  if (!d || d.success === false || !d.token) {
    throw new Error((d && d.error) || "Anmeldung fehlgeschlagen.");
  }
  await sitzungSchreiben({ token: d.token, benutzer: benutzer });

  // Darf dieser Benutzer den Assistenten ueberhaupt? Wird sofort geklaert, statt
  // den Knopf anzubieten und beim Druecken 403 zu liefern.
  let erlaubt = false, hinweis = "";
  try {
    const me = await ruf("/api/me");
    erlaubt = !!(me && me.permissions && me.permissions.jira_assist);
    if (!erlaubt) {
      hinweis = "Dein Konto ist für den Jira-Assistenten nicht freigeschaltet " +
                "(Einstellungen → Sicherheit → Berechtigungen → Jira-Assistent).";
    }
  } catch (e) {
    hinweis = e.message;
  }
  return { ok: true, benutzer, erlaubt, hinweis };
}

// ── Nachrichten aus dem Popup ───────────────────────────────────────────────
api.runtime.onMessage.addListener((nachricht, absender, antworten) => {
  (async () => {
    try {
      switch (nachricht && nachricht.art) {
        case "zustand": {
          const e = await einstLesen();
          const d = await api.storage.local.get(SITZUNG);
          const s = d[SITZUNG] || {};
          antworten({ ok: true,
                      basis: (e.basis || "").replace(/\/+$/, ""),
                      angemeldet: !!s.token,
                      benutzer: s.benutzer || "",
                      // Fuer die Anmeldemaske nach einem Fensterabbruch: der
                      // zuletzt eingetippte Name und der Merker, dass die
                      // Berechtigungsabfrage lief.
                      benutzer_vorschlag: e.benutzer || "",
                      zugriff_erfragt: !!e.zugriff_erfragt,
                      // Welche Ansicht gilt, und kann dieser Browser ueberhaupt
                      // eine Leiste? Ein Schalter fuer etwas, das es nicht gibt,
                      // ist schlimmer als kein Schalter.
                      ansicht: (e.ansicht === "leiste") ? "leiste" : "popup",
                      leiste_moeglich: leisteMoeglich(),
                      // Damit das Fenster merkt, wenn hier noch eine aeltere
                      // Fassung antwortet (siehe STAND).
                      stand: STAND,
                      // "SIDE_PANEL" | "POPUP" | "" (nicht feststellbar).
                      // Das Fenster entscheidet danach, ob es Tab-Wechsel
                      // beobachten muss - siehe kontextArt().
                      kontext: await kontextArt(absender),
                      ergebnis: await ergebnisLesen() });
          break;
        }
        case "merken":
          // Wird VOR der Berechtigungsabfrage gerufen – danach kann das
          // Fenster weg sein.
          antworten({ ok: true, daten: await einstSchreiben(nachricht) });
          break;
        case "ansicht": {
          // Ohne `wert` ist es eine reine Abfrage.
          if (nachricht.wert !== undefined) {
            await einstSchreiben({ ansicht: nachricht.wert });
            await ansichtAnwenden(nachricht.wert);
          }
          antworten({ ok: true, wert: await ansichtLesen(),
                      leiste_moeglich: leisteMoeglich() });
          break;
        }
        case "anmelden":
          antworten(await anmelden(nachricht));
          break;
        case "abmelden":
          await sitzungSchreiben({});
          // Beim Abmelden geht auch das Ergebnis – es enthaelt Ticketinhalte,
          // und der naechste Benutzer an diesem Rechner hat damit nichts zu tun.
          await ergebnisSchreiben(null);
          antworten({ ok: true });
          break;
        case "ergebnis_merken":
          await ergebnisSchreiben(nachricht.wert || null);
          antworten({ ok: true });
          break;
        case "branding": {
          // Die Adresse kann aus dem Formular kommen (noch nicht gespeichert),
          // damit das Fenster schon beim Eintippen die Marke zeigen kann.
          // MERGE, kein Ersatz: ein `set` mit nur `basis` haette den gemerkten
          // Benutzernamen mitgeloescht – und der ist genau das, was nach einer
          // Berechtigungsabfrage noch da sein soll.
          if (nachricht.basis) await einstSchreiben({ basis: nachricht.basis });
          antworten({ ok: true, daten: await branding() });
          break;
        }
        case "health":
          antworten({ ok: true, daten: await ruf("/api/jira/assist/health") });
          break;
        case "vorlagen":
          antworten({ ok: true, daten: await ruf("/api/jira/assist/vorlagen") });
          break;
        case "vorlage_speichern":
          antworten({ ok: true, daten: await ruf("/api/jira/assist/vorlagen", {
            methode: "POST", rumpf: nachricht.wert || {} }) });
          break;
        case "vorlage_standard":
          antworten({ ok: true, daten: await ruf(
            "/api/jira/assist/vorlagen/standard",
            { methode: "POST", rumpf: { id: nachricht.id || "" } }) });
          break;
        case "vorlage_loeschen":
          antworten({ ok: true, daten: await ruf(
            "/api/jira/assist/vorlagen/" + encodeURIComponent(nachricht.id || ""),
            { methode: "DELETE" }) });
          break;
        case "auswerten": {
          const d = await ruf("/api/jira/assist", {
            methode: "POST",
            rumpf: {
              key: nachricht.key,
              modus: nachricht.modus,
              lang: nachricht.lang || "de",
              hinweis: nachricht.hinweis || "",
              vorlage: nachricht.vorlage || "",
              // Nur im Modus "ueberarbeiten" gefuellt: der bereits getippte
              // Text aus dem Jira-Kommentarfeld. Der Server prueft ihn.
              entwurf: nachricht.entwurf || "",
            },
          });
          // Sofort merken – der Benutzer wechselt als Naechstes typischerweise
          // in den Jira-Tab, und damit ist das Fenster zu.
          await ergebnisSchreiben({
            key: d.key, modus: d.modus, text: d.text || "",
            titel: d.titel || "", kommentare: d.kommentare || 0,
            // Der Abgleich-Hinweis gehoert zum Text: ohne ihn stuende beim
            // naechsten Oeffnen eine ueberarbeitete Fassung da, deren
            // ausgewiesener Widerspruch verschwunden ist.
            hinweis: d.hinweis || "",
            modell: d.modell || "", zeit: Date.now(),
          });
          antworten({ ok: true, daten: d });
          break;
        }
        default:
          /* ⚠ DIE MELDUNG MUSS DEN WEG NENNEN. „Unbekannte Anfrage." war
           * richtig und trotzdem wertlos: der haeufigste Grund ist nicht ein
           * Programmierfehler, sondern ein Hintergrund, der aelter ist als das
           * Fenster (siehe STAND). */
          antworten({ ok: false, fehler:
            "Diese Anfrage kennt der Hintergrund nicht (\"" +
            String((nachricht && nachricht.art) || "?") + "\"). " +
            "Vermutlich laeuft noch eine aeltere Fassung der Erweiterung: " +
            "oeffne chrome://extensions und druecke bei dieser Erweiterung " +
            "auf Neu laden (\u27F3)." });
      }
    } catch (e) {
      antworten({ ok: false, fehler: (e && e.message) || String(e) });
    }
  })();
  // true = die Antwort kommt asynchron. Ohne das bekommt das Popup `undefined`
  // und zeigt "Unbekannter Fehler", waehrend der Aufruf in Wahrheit laeuft.
  return true;
});
