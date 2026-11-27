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

/* ⚠ JE ZWEIG, NICHT JE WURZEL – und darin lag der gemeldete Fehler
 * ("in edge wird kein Ticket erkannt", 2026-09-02).
 *
 * Hier stand `(typeof browser !== "undefined") ? browser : chrome`. Das waehlt
 * EINE Wurzel und benutzt sie fuer ALLES. Existiert `browser` aber nur als
 * TEIL-Alias (ein Objekt mit `runtime`, ohne `tabs`), dann ist `api.tabs`
 * undefined – und `api.tabs.query` wirft "Cannot read properties of
 * undefined". Gemessen an einer gestellten Umgebung: Anzeige LEER, kein
 * Ticket, kein Hinweis. Dass Anmeldung und Vorlagen weiter gingen, passt genau
 * dazu: `runtime` war ja da.
 *
 * Dieselbe Klasse wie `api.sidePanel` (2026-08-30, drei Runden gekostet), nur
 * eine Ebene tiefer: dort fehlte ein Zweig in `browser`, hier auch – und das
 * Muster `browser ?? chrome` kann darauf nicht reagieren.
 *
 * ⚠ DIE REIHENFOLGE IST PFLICHT: `browser` ZUERST. In Firefox gibt es BEIDE
 * Wurzeln, aber nur `browser.*` liefert Promises; `chrome.*` ist dort die
 * Callback-Variante. Wer hier `chrome` vorzieht, macht Firefox kaputt – und
 * zwar vollstaendig, nicht nur an einer Stelle.
 */
const api = new Proxy({}, {
  get(_ziel, name) {
    if (typeof browser !== "undefined" && browser && browser[name]) {
      return browser[name];
    }
    if (typeof chrome !== "undefined" && chrome && chrome[name]) {
      return chrome[name];
    }
    return undefined;
  },
});

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
const STAND = 10;

const EINST = "einstellungen";   // storage.local: { basis }
const SITZUNG = "sitzung";       // storage.local: { token, benutzer }
const ERGEBNIS = "ergebnis";     // ALT: EIN Lauf. Wird migriert, s.u.
const ERGEBNISSE = "ergebnisse"; // storage.local: { <ticket>: lauf } (s.u.)

/* Wie viele Ticket-Ergebnisse gleichzeitig vorgehalten werden.
 *
 * ⚠ FUENF, NICHT UNBEGRENZT – und das ist eine Abwaegung, keine runde Zahl.
 * In jedem Eintrag steht Kundentext aus einem Ticket. Er liegt in
 * `storage.local`, also auf der Platte des Arbeitsplatzes, bis der Benutzer
 * sich abmeldet oder zuruecksetzt. Ohne Deckel wuechse dieser Bestand mit
 * jedem angesehenen Vorgang weiter, unbemerkt.
 * Fuenf deckt ab, wofuer der Speicher da ist: zwischen ein paar Vorgaengen
 * hin- und herwechseln, ohne eine bezahlte Auswertung zu verlieren. */
const ERGEBNIS_MAX = 5;

/* ── AUTOMATIK BEI NEUEM TICKET ─────────────────────────────────────────────
 *
 * Zwei Werte in `einstellungen`:
 *   auto_vorlage  "" | <Kennung einer Vorlage>  – Vorgabe LEER (aus).
 *   auto_gelaufen [key, ...]                    – Ringspeicher, s.u.
 *
 * ⚠ BIS 2026-09-02 HIESS DAS FELD `auto_modus` und trug einen Modus
 * ("zusammenfassung"/"antwort"). Seit die Automatik VORLAGEN anbietet, steht
 * dort eine Vorlagen-Kennung – und deshalb ein NEUER Feldname statt einer
 * Umdeutung: ein alter Wert wird schlicht nicht mehr gelesen, die Automatik
 * ist nach dem Update also aus, bis jemand eine Vorlage waehlt.
 *
 * Das ist die fail-closed Richtung und Absicht: der alte Wert liesse sich
 * nicht verlaesslich auf eine Vorlage abbilden (welche der fuenf
 * Zusammenfassungs-Vorlagen waere gemeint?), und eine Automatik, die nach
 * einem Update etwas ANDERES tut als bestellt, waere schlimmer als eine, die
 * einmal neu eingestellt werden muss. Ein hoeherer `STAND` macht den
 * Unterschied fuer ein halb aktualisiertes Fenster sichtbar.
 *
 * WARUM DER RING SEIN MUSS: ohne ihn feuert jeder Tab-Wechsel zurueck auf ein
 * schon gesehenes Ticket einen weiteren LLM-Lauf. In der Seitenleiste wechselt
 * man zwischen zwei Vorgaengen hin und her – das waeren dann zwei Laeufe je
 * Runde, unbemerkt und auf Kosten des Servers. Der Ring macht die Zusage
 * "hoechstens EIN automatischer Lauf je Ticket" haltbar.
 *
 * ⚠ ER LIEGT IN DER ABLAGE, NICHT IM SPEICHER. Im Popup wird das Fenster bei
 * jedem Klick daneben zerstoert, und unter MV3 beendet der Browser auch den
 * Service-Worker, sobald er nichts zu tun hat – ein Merker im Arbeitsspeicher
 * waere in beiden Faellen sofort wieder weg und der Ring wirkungslos.
 *
 * DIE DRITTE ENTSCHEIDUNG: vermerkt wird VOR dem Lauf, nicht nach einem
 * Erfolg. Ein Server, der gerade nicht antwortet, wuerde sonst bei jedem
 * Tab-Wechsel erneut angefragt. Preis: schlaegt der eine automatische Lauf
 * fehl, gibt es keinen zweiten von selbst – der Knopf daneben steht bereit.
 */
const AUTO_MERK_MAX = 20;

/* Wie eine Vorlagen-Kennung aussieht: `uuid4().hex[:12]` am Server
 * (jira_vorlagen.speichern). Geprueft wird die FORM, nicht die Existenz – ob
 * es die Vorlage noch gibt, weiss nur der Server, und der Hintergrund fragt
 * ihn dafuer nicht. Das Fenster raeumt eine verschwundene Vorlage auf, sobald
 * es die Liste geladen hat (popup.js::autoOptionenZeichnen). */
const AUTO_ID_RE = /^[0-9a-f]{1,32}$/;

/** Nimmt nur eine wohlgeformte Vorlagen-Kennung an – alles andere heisst "aus".
 *
 * Fail-closed wie bei `ansicht`: ein Tippfehler in der Ablage, ein Wert aus
 * einer kuenftigen Fassung und ausdruecklich auch der ALTE Modus-Wert
 * ("zusammenfassung"/"antwort") fallen hier heraus. "aus" ist die Lage, die
 * niemanden ueberrascht.
 */
function autoVorlage(wert) {
  const w = String(wert || "");
  return AUTO_ID_RE.test(w) ? w : "";
}

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
  // Siehe `autoVorlage`: unbekannt = aus.
  if (teil.auto_vorlage !== undefined) neu.auto_vorlage = autoVorlage(teil.auto_vorlage);
  /* Ist der Einstellungen-Abschnitt im Fenster aufgeklappt? Vorgabe ZU, und
   * `!!` macht aus jedem Muellwert einen der zwei erlaubten Zustaende. Ohne
   * diese Zeile wuerde das Feld hier WORTLOS verworfen – der Benutzer klappt
   * auf, und beim naechsten Oeffnen ist es wieder zu, ohne Fehlermeldung.
   * Genau dieser Fall ist der Grund fuer `STAND` (ein Test prueft die Regel
   * "jedes per `merken` geschickte Feld muss hier stehen"). */
  if (teil.einst_offen !== undefined) neu.einst_offen = !!teil.einst_offen;
  /* ⚠ STARTET EIN WECHSEL IM VORLAGEN-PULLDOWN DEN LAUF VON SELBST?
   * Vorgabe AN (Vorgabe des Betreibers 2026-09-14) – und deshalb wird hier
   * NUR der ausdrueckliche Wert gespeichert. Die Vorgabe selbst steht an der
   * LESE-Stelle (`auto_wechsel !== false` im Zustand): ein Altbestand ohne
   * das Feld muss AN ergeben, nicht AUS. `!!` macht aus jedem Muellwert einen
   * der zwei erlaubten Zustaende. */
  if (teil.auto_wechsel !== undefined) neu.auto_wechsel = !!teil.auto_wechsel;
  /* Ergebnis einer IdP-Anmeldung, das das Fenster nicht mehr erlebt hat
   * (siehe `idpAnmelden`). Einmalig: das Fenster zeigt es und leert es. */
  if (teil.idp_meldung !== undefined) {
    neu.idp_meldung = String(teil.idp_meldung || "").slice(0, 500);
  }
  // Gehoert dazu: soll die Kennwortmaske deshalb offen stehen (gescheitert,
  // nicht bloss abgebrochen)?
  if (teil.idp_kennwort !== undefined) neu.idp_kennwort = !!teil.idp_kennwort;
  /* Der Ring wird hier GEKAPPT, nicht beim Lesen: was einmal in der Ablage
   * steht, waechst sonst mit jedem Ticket weiter – und niemand sieht es. */
  if (teil.auto_gelaufen !== undefined) {
    neu.auto_gelaufen = (Array.isArray(teil.auto_gelaufen) ? teil.auto_gelaufen : [])
      .filter((k) => typeof k === "string" && k)
      .slice(-AUTO_MERK_MAX);
  }
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
 *
 * ⚠ DIE VORGABE IST SEIT 2026-09-03 DIE LEISTE (siehe `ansichtLesen`) – und
 * genau deshalb bleiben ZWEI Manifest-Schluessel, wie sie sind:
 *
 *   `action.default_popup: "popup.html"` BLEIBT STEHEN. Er gilt in den
 *   Millisekunden, bevor dieser Service-Worker das erste Mal laeuft, und er
 *   ist der Rueckfall, falls `setPopup` scheitert: dann oeffnet der Klick
 *   wenigstens das Popup. Ohne ihn waere der schlechteste Ausgang „es oeffnet
 *   gar nichts, und niemand sieht warum". Ein Popup zu viel ist ein
 *   Schoenheitsfehler, ein totes Symbol ist ein Ausfall.
 *
 *   `sidebar_action.open_at_install: false` BLEIBT EBENFALLS. Die Begruendung
 *   von 2026-08-30 („die Vorgabe ist ja das Popup") ist damit weggefallen, die
 *   Entscheidung nicht: Firefox klappte die Leiste sonst schon beim
 *   INSTALLIEREN auf – ohne Klick, ohne Anlass, mit der Anmeldemaske darin –,
 *   und Chrome kennt dafuer gar keine Entsprechung. Die Vorgabe greift in
 *   beiden Browsern beim ERSTEN Klick auf das Symbol; dass sie in einem davon
 *   zusaetzlich ungefragt aufgeht, waere kein Gewinn, sondern eine Abweichung.
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

/** Welche Ansicht gilt – und die VORGABE ist seit 2026-09-03 die Seitenleiste.
 *
 * ⚠ HIER STAND „alles ausser `leiste` heisst Popup" – und das war zugleich die
 * Vorgabe: wer nie umgeschaltet hat, bekam ein Popup. Auf Anweisung ist die
 * Leiste jetzt die Vorgabe, **sofern der Browser sie kann**. Sie bleibt beim
 * Arbeiten im Ticket offen, folgt dem Tab-Wechsel und laesst sich in der
 * Breite ziehen; ein Popup kann keines davon (der Browser zeichnet es um den
 * Inhalt und klemmt es auf 800x600).
 *
 * DREI ZUSTAENDE, NICHT ZWEI – darin liegt die ganze Aenderung:
 *   "leiste"  ausdruecklich gewaehlt
 *   "popup"   ausdruecklich gewaehlt – bleibt Popup, auch wenn eine Leiste da
 *             waere: eine Vorgabe darf eine Entscheidung nicht ueberstimmen
 *   fehlt     nichts gewaehlt → Leiste, wenn moeglich, sonst Popup
 * `einstSchreiben` speichert nur einen der beiden ausdruecklichen Werte; das
 * Fehlen entsteht also ausschliesslich durch „noch nie angefasst".
 *
 * ⚠ OHNE `leisteMoeglich()` WAERE DIE VORGABE EIN TOTALAUSFALL: auf einem
 * Browser ohne Leiste leert `ansichtAnwenden` den Popup-Pfad, `onClicked`
 * findet danach keine Leisten-API – und der Klick auf das Symbol oeffnet GAR
 * NICHTS. Fail-safe ist hier die schmalere Funktion, nicht die schoenere.
 */
async function ansichtLesen() {
  const wert = (await einstLesen()).ansicht;
  if (wert === "leiste" || wert === "popup") return wert;
  return leisteMoeglich() ? "leiste" : "popup";
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
/* ⚠ EIN EINTRAG JE TICKET (Vorgabe 2026-09-03), vorher genau EINER insgesamt.
 *
 * DER GEMELDETE FALL: "nach Reiterwechsel ist die Antwort leider wieder weg".
 * Zutreffend, und gemessen – der Text war wirklich fort, nicht nur verborgen:
 * bei einem Wechsel auf ein anderes Ticket wurde der eine Speicherplatz
 * GELEERT, und beim Zurueckwechseln stand das Feld leer da, ohne jede
 * Erklaerung. In der Seitenleiste (seit 0.9.0 die Vorgabe) passiert genau das
 * beim normalen Arbeiten staendig.
 *
 * ⚠ DIE SICHERHEITSZUSAGE BLEIBT UNANGETASTET, und sie wird sogar strenger:
 * angezeigt wird immer nur der Eintrag, dessen `key` dem OFFENEN Ticket
 * entspricht. Genau deshalb ist der Speicher eine ABBILDUNG Ticket → Lauf und
 * nicht eine Liste: es gibt keinen Zustand, in dem ein Text zu Vorgang A neben
 * Vorgang B stehen kann, und das Fenster bekommt einen fremden Entwurf gar
 * nicht mehr zu sehen (es fragt je Ticket, siehe Fall "ergebnis").
 */
async function ergebnisseLesen() {
  const d = await api.storage.local.get([ERGEBNISSE, ERGEBNIS]);
  const m = d[ERGEBNISSE];
  const karte = (m && typeof m === "object" && !Array.isArray(m)) ? m : {};
  /* MIGRATION, genau einmal: ein vor dem Update gemerkter Lauf soll nicht
   * verloren gehen – wer gerade eine Auswertung offen hatte, hat sie bezahlt.
   * Der alte Schluessel wird danach entfernt, damit hier keine zweite Wahrheit
   * stehenbleibt. */
  const alt = d[ERGEBNIS];
  if (alt && alt.key && !karte[alt.key]) {
    karte[alt.key] = alt;
    try {
      await api.storage.local.set({ [ERGEBNISSE]: karte });
      await api.storage.local.remove(ERGEBNIS);
    } catch (e) { /* dann eben beim naechsten Mal */ }
  }
  return karte;
}

/** Der gemerkte Lauf zu GENAU diesem Ticket – oder null. */
async function ergebnisLesen(key) {
  if (!key) return null;
  const e = (await ergebnisseLesen())[key];
  return (e && e.key === key && e.text) ? e : null;
}

async function ergebnisSchreiben(wert) {
  if (!wert || !wert.key) return;
  const karte = await ergebnisseLesen();
  karte[wert.key] = wert;
  /* GEKAPPT WIRD BEIM SCHREIBEN, nicht beim Lesen: was einmal in der Ablage
   * steht, waechst sonst weiter, und niemand sieht es. Verworfen wird der
   * AELTESTE (kleinstes `zeit`) – ein Eintrag ohne Zeitstempel gilt als
   * aeltester, sonst waere er unloeschbar. */
  const schluessel = Object.keys(karte);
  if (schluessel.length > ERGEBNIS_MAX) {
    schluessel
      .sort((a, b) => ((karte[b] && karte[b].zeit) || 0)
                      - ((karte[a] && karte[a].zeit) || 0))
      .slice(ERGEBNIS_MAX)
      .forEach((k) => { delete karte[k]; });
  }
  await api.storage.local.set({ [ERGEBNISSE]: karte });
}

/** Loescht EINEN Eintrag ("Leeren" im Ergebnisbereich). */
async function ergebnisLoeschen(key) {
  if (!key) return;
  const karte = await ergebnisseLesen();
  if (!(key in karte)) return;
  delete karte[key];
  await api.storage.local.set({ [ERGEBNISSE]: karte });
}

/** Loescht ALLES (Abmelden, Zuruecksetzen).
 *
 * Beides ist eine ausdrueckliche Handlung des Benutzers – und beim Abmelden
 * sind es die Ticketinhalte des VORIGEN Benutzers an diesem Rechner. Der alte
 * Einzelplatz wird mitgeraeumt: ein Altbestand, der die Migration noch nicht
 * gesehen hat, darf ein Abmelden nicht ueberleben. */
async function ergebnisseLoeschen() {
  await api.storage.local.remove([ERGEBNISSE, ERGEBNIS]);
}

/** Darf fuer dieses Ticket automatisch ausgewertet werden – und womit?
 *
 * DIE ENTSCHEIDUNG LIEGT HIER, NICHT IM FENSTER, und zwar aus einem Grund:
 * Pruefen und Vermerken muessen EIN Schritt sein. Traege das Fenster den Ring
 * selbst nach, laege zwischen "kenne ich noch nicht" und "ist jetzt vermerkt"
 * eine Lese-Schreib-Runde – zwei schnelle Tab-Wechsel wuerden dieselbe
 * Ticketnummer zweimal durchlassen, und die Zusage "hoechstens ein Lauf je
 * Ticket" waere keine.
 *
 * Gibt `{ vorlage, starten }` zurueck. `vorlage` steht auch dann drin, wenn
 * nicht gestartet wird – das Fenster kann so unterscheiden, ob die Automatik
 * aus ist oder ob dieses Ticket bereits gelaufen war.
 *
 * WAS die Vorlage tut (Zusammenfassung oder Antwortentwurf), steht hier
 * NICHT – das entscheidet der Server aus ihrer Art. Der Hintergrund kennt die
 * Vorlagen gar nicht, und er soll sie auch nicht kennen muessen: eine zweite
 * Stelle, die aus einer Kennung einen Modus macht, waere eine zweite Wahrheit.
 */
async function autoStart(key) {
  const e = await einstLesen();
  const vorlage = autoVorlage(e.auto_vorlage);
  if (!vorlage || !key) return { vorlage, starten: false };
  const gelaufen = Array.isArray(e.auto_gelaufen) ? e.auto_gelaufen : [];
  if (gelaufen.indexOf(key) >= 0) return { vorlage, starten: false };
  // Vermerken VOR dem Lauf – siehe AUTO_MERK_MAX.
  await einstSchreiben({ auto_gelaufen: gelaufen.concat([key]) });
  return { vorlage, starten: true };
}

/** Ein Aufruf an Jarvis. Wirft mit KLARTEXT – der Text geht 1:1 ins Popup. */
async function ruf(pfad, { methode = "GET", rumpf = null, mitToken = true,
                           basis: basisVorgabe = "" } = {}) {
  /* `basis` nur fuer Aufrufe VOR der Anmeldung (IdP-Status), bei denen die
   * Adresse im Feld steht, aber noch nicht gemerkt ist. */
  const basis = String(basisVorgabe || "").replace(/\/+$/, "") || await basisLesen();
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
  return freigabePruefen(benutzer);
}

/* Darf dieser Benutzer den Assistenten ueberhaupt? Wird sofort geklaert, statt
 * den Knopf anzubieten und beim Druecken 403 zu liefern. EINE Fassung fuer
 * beide Anmeldewege (Kennwort und Firmenkonto) – zwei liefen auseinander. */
async function freigabePruefen(benutzer) {
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

// ── Anmeldung ueber das Firmenkonto (IdP) ───────────────────────────────────
/* Ablauf (Server: /api/login/oidc/start?app=browser … -> IdP -> Rueckkehr an
 * die Umleitungsadresse DIESER Erweiterung mit einem Einmal-Code):
 *   1. verifier/challenge (PKCE, S256) und `zustand` erzeugen,
 *   2. identity.launchWebAuthFlow oeffnet die Anmeldung in einem eigenen
 *      Fenster des Browsers und liefert die Rueckkehradresse,
 *   3. `zustand` pruefen, den Code mit dem verifier einloesen -> Token.
 *
 * ⚠ DAS LAEUFT IM HINTERGRUND, NICHT IM FENSTER. launchWebAuthFlow oeffnet ein
 * eigenes Browserfenster; das Popup verliert dabei den Fokus und SCHLIESST
 * sich (dieselbe Bauart wie bei der Berechtigungsabfrage). Liefe der Ablauf im
 * Popup, stuerbe er mit ihm – der Code kaeme nie an. Der Hintergrund erlebt
 * das Ende; die Sitzung liegt danach in `storage.local`, und das Fenster
 * zeigt beim naechsten Oeffnen den angemeldeten Zustand. Ein Fehlschlag, den
 * kein Fenster mehr sieht, wird als `idp_meldung` gemerkt und beim naechsten
 * Oeffnen einmal angezeigt.
 * Annahme (nicht im echten Browser gemessen): der Service-Worker bleibt
 * waehrend der offenen Anmeldung am Leben, weil ein Erweiterungsaufruf
 * aussteht. Der Verifier liegt deshalb nur im Speicher – stirbt der Worker
 * doch, ist der Code wertlos und der Benutzer klickt erneut (fail-closed).
 *
 * Benutzergeste: launchWebAuthFlow verlangt in Chrome keine (anders als
 * permissions.request oder sidePanel.open); `interactive: true` erlaubt das
 * sichtbare Anmeldefenster.
 *
 * Die Rueckkehradresse ist `identity.getRedirectURL()` – Chrome/Edge
 * `https://<id>.chromiumapp.org/`, Firefox `https://<hash>.extensions.allizom.org/`.
 * Der Server nimmt NUR diese Formen an; der Browser faengt die Navigation
 * dorthin ab, die Adresse wird nie wirklich geladen. */
const IDP_FEHLER = {
  nicht_eingerichtet: "Die Anmeldung über das Firmenkonto ist auf diesem Server nicht eingerichtet.",
  zu_viele: "Zu viele Anmeldeversuche. Bitte warte 5 Minuten.",
  abgelaufen: "Die Anmeldung über das Firmenkonto ist abgelaufen. Bitte erneut versuchen.",
  abgebrochen: "Die Anmeldung beim Firmenkonto wurde abgebrochen.",
  nicht_erreichbar: "Der Anmeldedienst des Unternehmens ist gerade nicht erreichbar.",
  konfiguration: "Die Anmeldung über das Firmenkonto ist falsch eingerichtet. Bitte den Administrator informieren.",
  idp: "Der Anmeldedienst des Unternehmens hat die Anmeldung abgelehnt.",
  token: "Die Bestätigung des Anmeldedienstes war ungültig. Bitte den Administrator informieren.",
  schluessel: "Die Bestätigung des Anmeldedienstes war ungültig. Bitte den Administrator informieren.",
  name: "Das Firmenkonto passt zu keinem Benutzer dieses Servers.",
  lokal: "Dieses Konto lässt sich nur mit Kennwort anmelden.",
  gesperrt: "Das Konto ist nach zu vielen Fehlversuchen vorübergehend gesperrt.",
  keine_freigabe: "Keine Anmeldeberechtigung.",
  pruefung: "Die Anmeldeberechtigung ist gerade nicht prüfbar. Bitte mit Kennwort anmelden.",
  lizenz: "Die Zahl der Benutzer für diese Lizenz ist erreicht.",
};

function idpFehlerText(kennung) {
  return IDP_FEHLER[kennung]
    || "Die Anmeldung über das Firmenkonto ist fehlgeschlagen. Bitte mit Kennwort anmelden.";
}

function _b64url(bytes) {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** PKCE (S256) und Zustand: {verifier, challenge, zustand}. */
async function pkceErzeugen() {
  const verifier = _b64url(crypto.getRandomValues(new Uint8Array(32)));
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: _b64url(hash),
           zustand: _b64url(crypto.getRandomValues(new Uint8Array(16))) };
}

/** Gibt es die identity-Schnittstelle? Ohne sie bleibt nur das Kennwort. */
function idpApi() {
  const id = api.identity;
  return (id && typeof id.launchWebAuthFlow === "function"
          && typeof id.getRedirectURL === "function") ? id : null;
}

/** Fuer die Anmeldemaske: gibt es die Anmeldung ueber das Firmenkonto?
 * Jeder Fehler (alter Server, kein Zugriffsrecht, Netz) heisst „nein“ –
 * dann bleibt die Maske, wie sie war. */
async function idpStatus(basis) {
  if (!idpApi()) return { aktiv: false };
  basis = String(basis || "").trim();
  if (!/^https:\/\//i.test(basis)) return { aktiv: false };
  try {
    const d = await ruf("/api/login/oidc/status", { mitToken: false, basis });
    if (!d || d.aktiv !== true) return { aktiv: false };
    return { aktiv: true,
             ad_modus: d.ad_modus === "zusaetzlich" ? "zusaetzlich" : "fallback" };
  } catch (e) {
    return { aktiv: false };
  }
}

async function idpAnmelden({ basis }) {
  const id = idpApi();
  basis = String(basis || "").trim().replace(/\/+$/, "");
  if (!id) {
    return { ok: true, angemeldet: false,
             text: "Dieser Browser bietet die Anmeldung über das Firmenkonto nicht an." };
  }
  if (!/^https:\/\//i.test(basis)) {
    return { ok: true, angemeldet: false, text: "Die Adresse muss mit https:// beginnen." };
  }
  await einstSchreiben({ basis, zugriff_erfragt: false, idp_meldung: "", idp_kennwort: false });
  const ende = async (text, abgebrochen) => {
    // Fuer den Fall, dass das Fenster inzwischen zu ist (siehe oben).
    await einstSchreiben({ idp_meldung: text, idp_kennwort: !abgebrochen });
    return { ok: true, angemeldet: false, abgebrochen: !!abgebrochen, text };
  };

  const { verifier, challenge, zustand } = await pkceErzeugen();
  const rueck = id.getRedirectURL();
  const url = basis + "/api/login/oidc/start?app=browser"
    + "&challenge=" + encodeURIComponent(challenge)
    + "&zustand=" + encodeURIComponent(zustand)
    + "&rueck=" + encodeURIComponent(rueck);

  let zurueck;
  try {
    zurueck = await id.launchWebAuthFlow({ url, interactive: true });
  } catch (e) {
    /* Hierher kommt vor allem das Schliessen des Anmeldefensters durch den
     * Benutzer – eine Entscheidung, kein Fehler. EIN ruhiger Satz, keine
     * Kaskade; die Kennwortmaske bleibt, wie sie ist. */
    const m = (e && e.message) || "";
    if (/approve|cancel|denied|closed/i.test(m) || !m) {
      return ende("Anmeldung über das Firmenkonto abgebrochen.", true);
    }
    return ende("Das Anmeldefenster ließ sich nicht öffnen (" + m + ").", false);
  }

  let q;
  try {
    const u = new URL(String(zurueck || ""));
    // Nur die eigene Rueckkehradresse zaehlt.
    if (u.origin !== new URL(rueck).origin) throw new Error("fremde Adresse");
    q = u.searchParams;
  } catch (e) {
    return ende("Die Rückmeldung der Anmeldung war unbrauchbar.", false);
  }
  /* ⚠ DER ZUSTAND MUSS PASSEN – sonst gehoert die Rueckkehr nicht zu DIESER
   * Anmeldung (etwa ein untergeschobener Code). Verworfen wird VOR dem
   * Einloesen, der Code geht dann nirgends hin. */
  if (q.get("zustand") !== zustand) {
    return ende("Die Rückmeldung der Anmeldung gehört nicht zu diesem Vorgang. "
                + "Bitte erneut anmelden.", false);
  }
  if (q.get("fehler")) {
    return ende(idpFehlerText(q.get("fehler")), q.get("fehler") === "abgebrochen");
  }
  const code = q.get("code") || "";
  if (!code) return ende(idpFehlerText(""), false);

  let d;
  try {
    d = await ruf("/api/login/oidc/app-einloesen", {
      methode: "POST", mitToken: false, basis, rumpf: { code, verifier } });
  } catch (e) {
    return ende(e.message, false);
  }
  if (!d || d.success === false || !d.token) {
    return ende((d && d.error) || idpFehlerText(""), false);
  }
  const benutzer = String(d.username || "");
  await sitzungSchreiben({ token: d.token, benutzer });
  await einstSchreiben({ benutzer, idp_meldung: "", idp_kennwort: false });
  return Object.assign(await freigabePruefen(benutzer), { angemeldet: true });
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
                      // Ergebnis einer IdP-Anmeldung, die kein Fenster mehr
                      // erlebt hat (einmalig, das Fenster leert es).
                      idp_meldung: e.idp_meldung || "",
                      idp_kennwort: e.idp_kennwort === true,
                      /* Welche Ansicht gilt, und kann dieser Browser
                       * ueberhaupt eine Leiste?
                       * ⚠ UEBER `ansichtLesen()`, NICHT ueber `e.ansicht`.
                       * Hier stand der Vergleich ein zweites Mal – seit die
                       * Leiste die Vorgabe ist, haette der Schalter „Popup"
                       * angezeigt, waehrend der Klick auf das Symbol die
                       * Leiste oeffnet. Eine Anzeige, die einen anderen
                       * Zustand behauptet als den wirksamen, kostet in diesem
                       * Projekt regelmaessig Stunden. Eine Quelle, keine zwei. */
                      ansicht: await ansichtLesen(),
                      leiste_moeglich: leisteMoeglich(),
                      // Welche Aktion bei einem neuen Ticket von selbst
                      // startet ("" = keine, das ist die Vorgabe).
                      auto_vorlage: autoVorlage(e.auto_vorlage),
                      /* Ist der Einstellungen-Abschnitt aufgeklappt?
                       * `=== true` und nicht `!!`: ein Altbestand ohne das
                       * Feld muss "zu" ergeben, also die Vorgabe. */
                      einst_offen: e.einst_offen === true,
                      /* Startet ein Vorlagenwechsel den Lauf von selbst?
                       * ⚠ `!== false` UND NICHT `=== true`: die Vorgabe ist
                       * AN, also muss ein Altbestand OHNE das Feld AN ergeben.
                       * Mit `=== true` waere die Einstellung fuer jeden, der
                       * sie nie angefasst hat, still aus – und die Vorgabe
                       * eine Behauptung, die nur fuer frische Profile gilt. */
                      auto_wechsel: e.auto_wechsel !== false,
                      // Damit das Fenster merkt, wenn hier noch eine aeltere
                      // Fassung antwortet (siehe STAND).
                      stand: STAND,
                      // "SIDE_PANEL" | "POPUP" | "" (nicht feststellbar).
                      // Das Fenster entscheidet danach, ob es Tab-Wechsel
                      // beobachten muss - siehe kontextArt().
                      kontext: await kontextArt(absender) });
          /* ⚠ HIER STAND `ergebnis: await ergebnisLesen()`. Seit es EINEN
           * Eintrag JE TICKET gibt, kann diese Antwort ihn gar nicht mehr
           * liefern: welcher Vorgang offen ist, weiss zu diesem Zeitpunkt nur
           * das Fenster (es ermittelt den Tab erst danach). Den einen
           * "letzten" mitzuschicken waere genau der Zustand, gegen den die
           * ganze Schranke gebaut ist – ein Text zu Vorgang A neben Vorgang B.
           * Das Fenster fragt deshalb gezielt nach (Fall "ergebnis"), und
           * bekommt einen fremden Entwurf nie zu sehen. */
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
        case "idp_status":
          antworten(Object.assign({ ok: true }, await idpStatus(nachricht.basis)));
          break;
        case "idp_anmelden":
          antworten(await idpAnmelden(nachricht));
          break;
        case "abmelden":
          await sitzungSchreiben({});
          // Beim Abmelden geht auch das Ergebnis – es enthaelt Ticketinhalte,
          // und der naechste Benutzer an diesem Rechner hat damit nichts zu tun.
          await ergebnisseLoeschen();
          /* Aus demselben Grund faellt der Ring: es sind die Ticketnummern des
           * vorigen Benutzers. Der EINSTELLUNG (auto_vorlage) passiert nichts –
           * die gehoert zu diesem Browser, nicht zu einer Anmeldung. */
          await einstSchreiben({ auto_gelaufen: [] });
          antworten({ ok: true });
          break;
        case "auto_start":
          antworten(Object.assign({ ok: true }, await autoStart(nachricht.key || "")));
          break;
        /* Der gemerkte Lauf zu GENAU einem Ticket. Ohne `key` gibt es nichts
         * – geraten wird hier nicht, ein falscher Text ist gefaehrlicher als
         * keiner. */
        case "ergebnis":
          antworten({ ok: true, ergebnis: await ergebnisLesen(nachricht.key || "") });
          break;
        /* DREI FAELLE, und die Unterscheidung ist der Kern der Aenderung:
         *   wert            → anlegen/ersetzen (der Schluessel steckt darin)
         *   null + key      → NUR diesen Eintrag weg ("Leeren")
         *   null + alle     → alles weg (Zuruecksetzen)
         * Ein `null` OHNE beides raeumt bewusst NICHTS: bis 2026-09-03 loeschte
         * genau dieser Aufruf den einzigen Speicherplatz, und er kam auch beim
         * bloszen Reiterwechsel – das war der gemeldete Datenverlust. */
        case "ergebnis_merken":
          if (nachricht.wert) await ergebnisSchreiben(nachricht.wert);
          else if (nachricht.alle) await ergebnisseLoeschen();
          else if (nachricht.key) await ergebnisLoeschen(nachricht.key);
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
