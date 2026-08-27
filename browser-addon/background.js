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
 * Aus demselben Grund sitzt die Arbeitsoberflaeche seit dem Panel-Umbau IN der
 * Jira-Seite (`panel.js`) und nicht mehr im Popup.
 */

const api = (typeof browser !== "undefined") ? browser : chrome;

/* `einfuegen.js` wird hier gebraucht, um `einfuegenUeberEditorApi` per
 * `executeScript({func})` in die SEITENWELT nachzuschieben.
 *
 * ⚠ ZWEI HINTERGRUENDE, ZWEI LADEWEGE: Chrome laeuft als Service Worker und
 * kennt `importScripts`; Firefox laeuft als Event Page (ein Fenster-Kontext,
 * KEIN Worker) und hat es nicht – dort steht die Datei als erster Eintrag in
 * `background.scripts` und ist beim Auswerten dieser Zeile schon geladen. Ein
 * bedingungsloses `importScripts` waere in Firefox ein ReferenceError beim
 * Start, und der Hintergrund liefe gar nicht an.
 */
if (typeof importScripts === "function") importScripts("einfuegen.js");

// Serveradresse steht NICHT im Manifest, sondern in den Einstellungen.
// Grund: eine Firefox-Erweiterung muss von Mozilla signiert sein, auch die
// selbst verteilte ("All add-ons must be submitted for signing, even if you
// distribute them outside AMO"). Eine signierte Datei laesst sich nicht pro
// Server umschreiben, ohne die Signatur zu brechen. Damit scheidet der Weg des
// Outlook-Add-ins aus, wo das Manifest je Server erzeugt wird – und die
// Drift-Falle "eine Kopie je Installation" gleich mit.
const EINST = "einstellungen";   // storage.local: { basis }
const SITZUNG = "sitzung";       // storage.local: { token, benutzer }
const ERGEBNIS = "ergebnis";     // storage.local: letzter Lauf (siehe unten)

async function basisLesen() {
  const d = await api.storage.local.get(EINST);
  return ((d[EINST] || {}).basis || "").replace(/\/+$/, "");
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
  await popupNachziehen();
}

/* ── Was ein Klick auf das Symbol tut, haengt an der Anmeldung ──────────────
 *
 * ANGEMELDET: kein Popup (`setPopup("")`) – dann feuert `action.onClicked`, und
 * der Klick injiziert das Panel in die Jira-Seite. Genau das ist der Umbau: das
 * Fenster ueberlebt den Tabwechsel, weil es zur Seite gehoert.
 *
 * NICHT ANGEMELDET: `popup.html` – Anmeldung und Einrichtung bleiben eine
 * Extension-Seite. Ein Anmeldeformular IN einer fremden Seite waere die
 * schlechtere Wahl: dort tippt der Benutzer sein Kennwort in ein Formular, das
 * optisch im Jira steht.
 *
 * ⚠ Das ist zugleich der EINZIGE Weg zurueck zum Anmeldefenster. Wer abmeldet
 * oder dessen Token mit 401 verfaellt, muss beim naechsten Klick wieder die
 * Maske sehen – deshalb haengt der Aufruf in `sitzungSchreiben()` und damit an
 * JEDER Aenderung der Sitzung, statt an den einzelnen Stellen.
 *
 * Der Aufruf steht ausserdem im Modulrumpf: ein Service Worker wird beendet und
 * neu gestartet, und nach einem Browser-Neustart gilt wieder der Wert aus dem
 * Manifest (`popup.html`). Ohne das Nachziehen bei jedem Start saehe ein
 * laengst angemeldeter Benutzer wieder die Anmeldemaske.
 */
async function popupNachziehen() {
  try {
    const t = await tokenLesen();
    await api.action.setPopup({ popup: t ? "" : "popup.html" });
  } catch (e) {
    // Kann eine alte Browserfassung nicht umschalten, bleibt es beim Popup –
    // das ist der funktionierende Zustand von vorher, nicht ein kaputter.
  }
}
popupNachziehen();

/* Der Klick auf das Symbol – nur erreichbar, wenn kein Popup gesetzt ist.
 *
 * `activeTab` gibt genau hier das Zugriffsrecht auf den offenen Tab, und nur
 * fuer diesen. Deshalb gibt es KEIN dauerhaftes Content-Script: das verlangte
 * bei der Installation "Alle deine Daten auf allen Websites lesen und aendern".
 *
 * `einfuegen.js` MUSS mitinjiziert werden – das Panel ruft `einfuegenInJira`
 * direkt auf, statt es aus der Ferne zu serialisieren.
 */
api.action.onClicked.addListener(async (tab) => {
  if (!tab || tab.id === undefined || tab.id === null) return;
  try {
    await api.scripting.executeScript({
      target: { tabId: tab.id },
      files: ["einfuegen.js", "panel.js"],
    });
    await api.action.setBadgeText({ tabId: tab.id, text: "" });
    await api.action.setTitle({ tabId: tab.id, title: "" });   // zurueck zur Vorgabe
  } catch (e) {
    /* Haeufigster Fall: eine Seite, in die der Browser nicht injizieren laesst
     * (Browser-interne Seiten, PDF-Ansicht, der Web Store). Es gibt von hier
     * aus keinen Weg, dem Benutzer ein Fenster zu zeigen – ein Klick, der
     * WORTLOS nichts tut, waere aber das Schlimmste. Also Abzeichen plus
     * Beschriftung, die den Grund nennt. */
    const grund = (e && e.message) || String(e);
    try {
      await api.action.setBadgeText({ tabId: tab.id, text: "!" });
      await api.action.setTitle({
        tabId: tab.id,
        title: "Auf dieser Seite kann der Assistent nicht geöffnet werden "
             + "(" + grund + "). Öffne ein Jira-Ticket.",
      });
    } catch (e2) { /* dann bleibt es beim stillen Fehlschlag */ }
  }
});

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
  await api.storage.local.set({ [EINST]: { basis: (basis || "").replace(/\/+$/, "") } });
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

/** Zweiter Einfuege-Versuch – IM SEITENKONTEXT (`world: "MAIN"`).
 *
 * Das Panel kann das nicht selbst: es laeuft in der isolierten Welt und sieht
 * `window.tinymce` der Seite nicht. Nur der Hintergrund darf `executeScript`
 * rufen, also faehrt der Weg hier durch.
 *
 * ⚠ DIE TAB-KENNUNG KOMMT AUS DEM ABSENDER, NIE AUS DER NACHRICHT. Sonst waere
 * die Nachricht ein Weg, in einen BELIEBIGEN offenen Tab zu schreiben – und
 * eine Nachricht kann aus jeder Seite kommen, in der das Panel steckt.
 */
async function editorApi(nachricht, absender) {
  const tabId = absender && absender.tab && absender.tab.id;
  if (tabId === undefined || tabId === null) {
    throw new Error("Kein Tab zur Anfrage bekannt.");
  }
  const fn = (globalThis.__jvEinfuegen || {}).einfuegenUeberEditorApi;
  if (!fn) throw new Error("Das Einfüge-Modul wurde nicht geladen.");
  const treffer = await api.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: fn,
    args: [String(nachricht.text || "")],
  });
  return (treffer && treffer[0] && treffer[0].result) || { ok: false };
}

// ── Nachrichten aus dem Popup und aus dem Panel ─────────────────────────────
api.runtime.onMessage.addListener((nachricht, absender, antworten) => {
  (async () => {
    try {
      switch (nachricht && nachricht.art) {
        case "zustand": {
          const basis = await basisLesen();
          const d = await api.storage.local.get(SITZUNG);
          const s = d[SITZUNG] || {};
          antworten({ ok: true, basis, angemeldet: !!s.token,
                      benutzer: s.benutzer || "",
                      ergebnis: await ergebnisLesen() });
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
        case "editor_api":
          antworten({ ok: true, daten: await editorApi(nachricht, absender) });
          break;
        case "branding": {
          // Die Adresse kann aus dem Formular kommen (noch nicht gespeichert),
          // damit das Fenster schon beim Eintippen die Marke zeigen kann.
          if (nachricht.basis) {
            await api.storage.local.set({
              [EINST]: { basis: String(nachricht.basis).replace(/\/+$/, "") }
            });
          }
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
            },
          });
          // Sofort merken – der Benutzer wechselt als Naechstes typischerweise
          // in den Jira-Tab, und damit ist das Fenster zu.
          await ergebnisSchreiben({
            key: d.key, modus: d.modus, text: d.text || "",
            titel: d.titel || "", kommentare: d.kommentare || 0,
            modell: d.modell || "", zeit: Date.now(),
          });
          antworten({ ok: true, daten: d });
          break;
        }
        default:
          antworten({ ok: false, fehler: "Unbekannte Anfrage." });
      }
    } catch (e) {
      antworten({ ok: false, fehler: (e && e.message) || String(e) });
    }
  })();
  // true = die Antwort kommt asynchron. Ohne das bekommt das Popup `undefined`
  // und zeigt "Unbekannter Fehler", waehrend der Aufruf in Wahrheit laeuft.
  return true;
});
