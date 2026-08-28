/* Popup: die ganze Oberflaeche.
 *
 * Es fetcht NICHTS selbst – jeder Netzaufruf geht ueber den Hintergrund
 * (Begruendung im Kopf von background.js). Das Popup schliesst sich, sobald der
 * Benutzer daneben klickt; ein Aufruf von hier waere damit mitten in einer
 * 13-Sekunden-Auswertung weg.
 */
import {
  einfuegenInJira, einfuegenUeberEditorApi, leseAusJira, lesenUeberEditorApi,
} from "./einfuegen.js";

const api = (typeof browser !== "undefined") ? browser : chrome;

const $ = (id) => document.getElementById(id);
const el = {
  login: $("bereich-login"), arbeit: $("bereich-arbeit"),
  basis: $("f-basis"), benutzer: $("f-benutzer"), kennwort: $("f-kennwort"),
  totp: $("f-totp"), hinweis: $("f-hinweis"), ergebnisFeld: $("f-ergebnis"),
  ergebnis: $("ergebnis"), ergebnisFuss: $("ergebnis-fuss"),
  meldung: $("meldung"), ticket: $("ticket-anzeige"),
  abmelden: $("btn-abmelden"),
};

let _key = "";        // Ticketnummer des offenen Tabs
let _tabId = null;
// Gehört der angezeigte Text zu einem ANDEREN Ticket als dem offenen?
let _fremdesErgebnis = false;
// Das zuletzt angezeigte Ergebnis (für das Mitmerken bearbeiteter Texte).
let _letztes = null;

// ── Meldungen ───────────────────────────────────────────────────────────────
function melde(text, arbeitet = false) {
  if (!text) { el.meldung.hidden = true; return; }
  // Meldungen tragen {marke} – auch die aus dem Hintergrund (der kennt das
  // DOM nicht und kann selbst nicht ersetzen).
  el.meldung.textContent = String(text).split("{marke}").join(_marke);
  /* WARTEMELDUNGEN BEKOMMEN EINEN DREHENDEN KREIS. "Formuliere einen
   * Antwortvorschlag … (dauert einige Sekunden)" steht sonst reglos da, und
   * ein stehender Satz ist von einem haengenden Fenster nicht zu
   * unterscheiden – erst recht nicht in einem Popup, das keine Titelleiste und
   * keinen Ladebalken hat.
   *
   * Der Kreis wird VORANGESTELLT statt in den Text geschrieben: der Text kommt
   * teils aus dem Hintergrund und ginge sonst durch innerHTML. `insertBefore`
   * laesst `textContent` oben die einzige Stelle, die Fremdtext setzt. */
  if (arbeitet) {
    const kreis = document.createElement("span");
    kreis.className = "dreher";
    // Vorlesesoftware soll den Kreis nicht als Inhalt ansagen - die Meldung
    // daneben sagt bereits, was laeuft.
    kreis.setAttribute("aria-hidden", "true");
    el.meldung.insertBefore(kreis, el.meldung.firstChild);
  }
  el.meldung.classList.toggle("arbeitet", !!arbeitet);
  el.meldung.hidden = false;
}

function sperre(an) {
  for (const b of document.querySelectorAll("button")) b.disabled = an;
}

/** Rückfrage – EIGENER Dialog, nie `confirm`.
 *
 * `window.confirm` blockiert in einem Extension-Popup den Renderer und sieht
 * aus wie ein Dialog der Seite; im Projekt ist es aus demselben Grund auch im
 * Outlook-Aufgabenfenster verboten. Fehlt das Markup, wird mit `true`
 * aufgelöst (fail-open) – der Benutzer hat den Knopf schon gedrückt.
 */
function frageJaNein(text) {
  const box = $("ja-nein");
  if (!box) return Promise.resolve(true);
  if (text) $("jn-text").textContent = text;
  else $("jn-text").innerHTML =
    'Der Text gehört zu einem <b>anderen Ticket</b>. Trotzdem einfügen?';
  box.hidden = false;
  return new Promise((fertig) => {
    const schluss = (wert) => {
      box.hidden = true;
      $("jn-ja").removeEventListener("click", ja);
      $("jn-nein").removeEventListener("click", nein);
      fertig(wert);
    };
    const ja = () => schluss(true);
    const nein = () => schluss(false);
    $("jn-ja").addEventListener("click", ja);
    $("jn-nein").addEventListener("click", nein);
    // Der Fokus liegt auf ABBRECHEN – die gefährlichere Wahl darf nicht die
    // sein, die ein Tastendruck auslöst.
    $("jn-nein").focus();
  });
}

/** Eine Anfrage an den Hintergrund – Fehler kommen als Text zurueck, nie als
 * Ausnahme mitten in einem Klick-Handler. */
async function frage(nachricht) {
  const a = await api.runtime.sendMessage(nachricht);
  if (!a) throw new Error("Keine Antwort von der Erweiterung.");
  if (!a.ok) throw new Error(a.fehler || "Unbekannter Fehler.");
  return a;
}

// ── Branding ────────────────────────────────────────────────────────────────
/* Die Erweiterung laeuft ausserhalb von Jarvis und kann weder theme.css noch
 * branding.js laden – sie holt die Marke deshalb selbst und setzt sie hier.
 *
 * WARUM DAS SEIN MUSS: dies ist ein White-Label-Produkt. Ein Fenster, das im
 * Browser jedes Sachbearbeiters "Jarvis" schreibt, verraet das Produkt hinter
 * der Hausmarke – dieselbe Begruendung, aus der die Mail-Kategorie und der
 * Name des Outlook-Add-ins dem Branding folgen.
 *
 * Ohne Branding bleibt alles wie eingebaut; ein Fehlschlag aendert nichts.
 */
/* DIE VORGABE AUS DEM PAKET ist der erste Anlauf, der Rueckfall der zweite.
 *
 * Gemeldet: "das Branding beim Login ist noch falsch". Zu Recht – die Marke kam
 * bis dahin AUSSCHLIESSLICH aus `/api/branding`, und der Abruf braucht eine
 * Adresse. Beim allerersten Oeffnen ist keine hinterlegt: die Anmeldemaske, das
 * erste, was jemand sieht, zeigte den eingebauten Namen.
 * Der Server traegt die Marke deshalb beim Bauen des ZIP ins Fenster ein
 * (jira_assist._popup_gebrandet). Ist das Feld leer – Paket aus bauen.sh, oder
 * gar kein Branding eingerichtet –, bleibt alles wie vorher.
 */
function _vorgabeMarke() {
    const m = document.querySelector('meta[name="marke"]');
    return ((m && m.content) || "").trim();
}

// Der Rueckfall, solange keine Marke bekannt ist.
let _marke = _vorgabeMarke() || "Jarvis";

/* ── Hausfarbe ──────────────────────────────────────────────────────────────
 * DIESELBE LUECKE WIE BEI DER MARKE, gemeldet 2026-08-28: der Anmelden-Knopf
 * war nie gebrandet. Die Farbe kam ausschliesslich aus `/api/branding`, und
 * der Abruf haengt am `change` des Adressfeldes - auf der Anmeldemaske steht
 * dort noch nichts. Genau dort sieht jemand das Fenster zum ersten Mal.
 *
 * ⚠ DIE FARBE WIRD ALS CSS GESETZT und kommt aus dem Branding-Formular, ist
 * also Fremdeingabe. Zugelassen ist deshalb NUR eine Hex-Notation: ein Wert
 * wie `red;background:url(...)` waere sonst eine Einschleusung in die
 * Formatvorlage. Alles andere wird verworfen, nicht repariert - dann bleibt
 * der neutrale Knopf, und das ist der richtige Ausgang.
 */
function _istHexFarbe(wert) {
    return /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(String(wert || "").trim());
}

/** Setzt die Hausfarbe und beendet damit den Neutralzustand.
 *
 * EINE Stelle fuer beide Wege (Vorgabe aus dem Paket und Antwort des Servers):
 * zwei Fassungen wuerden beim naechsten Farbfeld auseinanderlaufen, und der
 * Unterschied faellt nur auf, wenn jemand die Anmeldemaske ansieht.
 */
function akzentSetzen(akzent, hover) {
    if (!_istHexFarbe(akzent)) return false;
    const s = document.documentElement.style;
    s.setProperty("--akzent", akzent.trim());
    // Ohne eigenen Hover-Ton einen aus der Hausfarbe ableiten - sonst bliebe
    // der Knopf beim Ueberfahren auf dem neutralen Wert stehen und saehe wie
    // ein Fehler aus.
    s.setProperty("--akzent-hover", _istHexFarbe(hover) ? hover.trim()
        : "color-mix(in srgb, " + akzent.trim() + " 82%, #000)");
    document.documentElement.classList.remove("neutral");
    return true;
}

/* Die Vorgabe aus dem Paket gilt SOFORT - vor jedem Netzaufruf. Ist das Feld
 * leer (Paket aus bauen.sh oder kein Branding eingerichtet), bleibt der
 * Knopf neutral. */
akzentSetzen((document.querySelector('meta[name="akzent"]') || {}).content);

/** Ersetzt {marke} ueberall im Fenster – und MUSS auch ohne Branding laufen.
 *
 * Sonst steht der rohe Platzhalter im Text ("Bitte die {marke}-Adresse
 * eintragen"). Dieselbe Mechanik wie in branding.js, nur ohne dessen
 * Infrastruktur: die Erweiterung laeuft ausserhalb von Jarvis.
 *
 * Ersetzt wird ausschliesslich in TEXTKNOTEN und in `placeholder`/`title` –
 * nicht per innerHTML: der Markenname kommt aus einem Formular und darf kein
 * Markup einschleusen.
 */
/* Die ORIGINALE mit Platzhalter, damit ein zweiter Lauf (Branding kommt
 * nachtraeglich) wieder von vorn ersetzen kann. Ohne das waere nach dem ersten
 * Lauf ueberall "Jarvis" eingebrannt und die Marke traefe ins Leere. */
const _originale = new Map();

function markeAnwenden() {
    if (!_originale.size) {
        const lauf = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let n = lauf.nextNode(); n; n = lauf.nextNode()) {
            if (n.nodeValue && n.nodeValue.indexOf("{marke}") >= 0) {
                _originale.set(n, n.nodeValue);
            }
        }
        for (const e of document.querySelectorAll("[placeholder], [title]")) {
            for (const attr of ["placeholder", "title"]) {
                const v = e.getAttribute(attr);
                if (v && v.indexOf("{marke}") >= 0) _originale.set([e, attr], v);
            }
        }
        _originale.set("titel", document.title);
    }
    for (const [ziel, roh] of _originale) {
        const wert = roh.split("{marke}").join(_marke);
        if (ziel === "titel") document.title = wert;
        else if (Array.isArray(ziel)) ziel[0].setAttribute(ziel[1], wert);
        else ziel.nodeValue = wert;
    }
}

function setzeBranding(b) {
    if (!b) return;
    const name = (b.assistant_name || b.company_name || "").trim();
    if (name) {
        _marke = name;
        const m = $("marke");
        // textContent, nie innerHTML: der Name kommt aus einem Formular.
        if (m) m.textContent = name;
        // Alle Platzhalter neu belegen – aus den gemerkten Originalen, nicht
        // aus dem bereits ersetzten Text.
        markeAnwenden();
    }
    /* ⚠ DIE FARBEN STEHEN IN `colors`, NICHT FLACH IN DER ANTWORT.
     * Ein Zugriff auf `b.accent` liefert `undefined` – und zwar STILL: das
     * Fenster behielte einfach den Standardton, ohne dass irgendwo etwas
     * fehlschlaegt. Erst die Live-Messung gegen ein eingeschaltetes Branding
     * hat das gezeigt.
     * Der Akzent gilt markenweit aus `colors` (nicht `colors_light`) – so
     * macht es branding.js::effectiveColors() auch. */
    const farben = b.colors || {};
    // Ueber dieselbe Funktion wie die Vorgabe aus dem Paket - sie prueft die
    // Farbe und beendet den Neutralzustand.
    akzentSetzen(farben.accent, farben.accent_hover);
    const logo = b.logo_url_light || b.logo_url;
    if (logo) {
        const bild = $("marke-logo");
        if (bild) {
            // Relative URLs des Servers absolut machen – das Popup laeuft unter
            // chrome-extension://, dort zeigt "/api/..." ins Leere.
            const basis = (el.basis && el.basis.value || "").replace(/\/+$/, "");
            bild.src = /^https?:/i.test(logo) ? logo : (basis + logo);
            bild.hidden = false;
        }
    }
}

async function brandingHolen(basis) {
    try {
        const a = await frage({ art: "branding", basis: basis || "" });
        setzeBranding(a.daten);
    } catch (e) { /* ohne Branding bleibt das eingebaute Aussehen */ }
}

/* Farbe und Logo kennt nur der Server – die stehen also erst, wenn eine Adresse
 * da ist. Sobald sie eingetippt IST, gibt es keinen Grund, damit bis nach dem
 * Anmelden zu warten: `/api/branding` haengt an keiner Anmeldung.
 * Bewusst am `change` (also nach dem Verlassen des Feldes) und nur bei einer
 * plausiblen https-Adresse – jeder Tastendruck waere ein Netzaufruf, und ein
 * halb getippter Name wuerde als Adresse gespeichert.
 */
el.basis.addEventListener("change", () => {
    const b = (el.basis.value || "").trim();
    if (/^https:\/\/[^\s/]+\.[^\s/]+/i.test(b)) brandingHolen(b);
});

// ── Ticketnummer aus dem offenen Tab ────────────────────────────────────────
/** Liest die Ticketnummer aus der URL – NICHT aus dem Seiteninhalt.
 *
 * Die URL ist die verlässliche Quelle: `/browse/ABC-123` ist bei Jira
 * Server/DC wie Cloud stabil, während sich das DOM mit jeder Jira-Version
 * ändert. Den INHALT holt ohnehin der Server über die Jira-API – die
 * Erweiterung muss die Seite dafür gar nicht lesen.
 */
function keyAusUrl(url) {
  if (!url) return "";
  try {
    const u = new URL(url);
    const m = u.pathname.match(/\/browse\/([A-Z][A-Z0-9]{0,15}-\d{1,10})/i);
    if (m) return m[1].toUpperCase();
    // Board-/Backlog-Ansicht: das Ticket steht im Abfrageteil.
    for (const p of ["selectedIssue", "issueKey", "issue"]) {
      const w = u.searchParams.get(p);
      if (w && /^[A-Z][A-Z0-9]{0,15}-\d{1,10}$/i.test(w)) return w.toUpperCase();
    }
  } catch (e) { /* keine gueltige URL */ }
  return "";
}

async function tabErmitteln() {
  const tabs = await api.tabs.query({ active: true, currentWindow: true });
  const t = tabs && tabs[0];
  _tabId = t ? t.id : null;
  _key = keyAusUrl(t && t.url);
  el.ticket.textContent = _key || "";
}

// ── Start ───────────────────────────────────────────────────────────────────
async function start() {
  // ZUERST die Platzhalter belegen – sonst steht "{marke}" sichtbar da,
  // solange (oder falls) kein Branding geholt werden kann.
  markeAnwenden();
  await tabErmitteln();
  let z;
  try {
    z = await frage({ art: "zustand" });
  } catch (e) {
    melde(e.message);
    return;
  }
  el.basis.value = z.basis || "";
  // Marke setzen, sobald eine Adresse bekannt ist – das geht ohne Anmeldung
  // und damit schon beim allerersten Öffnen nach dem Einrichten.
  if (z.basis) brandingHolen(z.basis);
  zeige(z.angemeldet);
  if (z.angemeldet) {
    el.abmelden.hidden = false;
    // Das Pulldown gleich füllen – nicht erst beim Öffnen des Zahnrads:
    // sonst steht dort „Standard“, obwohl Vorlagen hinterlegt sind.
    vorlagenLaden();
    /* GEMERKTES GILT NUR FÜR DAS TICKET, ZU DEM ES GEHÖRT.
     *
     * Vorgabe des Nutzers 2026-08-28: passt der gemerkte Text nicht zum
     * offenen Tab, werden die Felder GELEERT. Vorher stand er weiter da – mit
     * Warnung, aber eben sichtbar und einfügbar. Ein Text im Feld ist eine
     * Einladung, ihn zu benutzen; die stärkere Antwort ist, ihn wegzuräumen.
     * Der Ticketbezug ist hier keine Bequemlichkeit, sondern eine
     * Sicherheitsfrage: das Ergebnis geht am Ende an einen echten Kunden. */
    const gemerkt = z.ergebnis;
    const passt = gemerkt && gemerkt.key && _key && gemerkt.key === _key;
    if (passt) {
      zeigeGemerktes(gemerkt);
    } else if (gemerkt && gemerkt.text) {
      await felderLeeren(_key
        ? "Der gemerkte Text gehörte zu " + gemerkt.key + ", offen ist "
          + _key + " – die Felder wurden geleert."
        : "Kein Jira-Ticket in diesem Tab. Der gemerkte Text zu "
          + gemerkt.key + " wurde entfernt. Öffne ein Ticket "
          + "(…/browse/ABC-123).");
    } else if (!_key) {
      // Kein Fehler, sondern eine Auskunft: die Erweiterung ist bereit, dieser
      // Tab ist nur kein Ticket.
      melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
    }
  }
}

/** Alles wegräumen, was zu einem Ticket gehört – Anzeige UND Gedächtnis.
 *
 * ⚠ DAS GEDÄCHTNIS MUSS MIT. Der gemerkte Text liegt im Speicher der
 * Erweiterung (background.js::ergebnisSchreiben); nur das Feld zu leeren,
 * hätte ihn beim nächsten Öffnen zurückgebracht – das Leeren sähe dann aus wie
 * ein Fehler, und der fremde Text stünde wieder da.
 *
 * ⚠ UND DER LAUFENDE MERK-TIMER MUSS GESTOPPT WERDEN. Wer den Vorschlag
 * bearbeitet hat, hat einen Timer offen, der `_letztes` eine halbe Sekunde
 * später zurückschreibt. Ohne `clearTimeout` löscht man das Gedächtnis und der
 * Timer legt es unmittelbar danach wieder an.
 *
 * Die VORLAGE bleibt bewusst stehen: sie ist eine Voreinstellung für den
 * nächsten Lauf, kein Inhalt dieses Tickets.
 */
async function felderLeeren(meldungstext) {
  clearTimeout(_merkTimer);
  _letztes = null;
  _fremdesErgebnis = false;
  el.ergebnisFeld.value = "";
  el.ergebnis.hidden = true;
  el.ergebnisFuss.textContent = "";
  el.hinweis.value = "";
  // Fehlschlag ist hier nicht schlimm: die Anzeige ist bereits leer, und beim
  // nächsten Öffnen greift dieselbe Prüfung erneut.
  try { await frage({ art: "ergebnis_merken", wert: null }); } catch (e) {}
  melde(meldungstext || "");
}

/* Ein gemerktes Ergebnis wieder anzeigen.
 *
 * ⚠ DER TICKETBEZUG IST HIER EINE SICHERHEITSFRAGE, KEINE BEQUEMLICHKEIT.
 * Das Fenster schliesst beim Wechsel in den Jira-Tab; beim naechsten Oeffnen
 * kann laengst ein ANDERES Ticket offen sein. Ein wiederhergestellter Text
 * ohne sichtbaren Bezug waere die Einladung, die Antwort auf Vorgang A in
 * Vorgang B einzufuegen – und der geht danach an einen echten Kunden.
 * Seit 2026-08-28 wird bei Abweichung GELEERT (siehe start()); die Warnung
 * hier bleibt als zweite Schranke für den Fall, dass diese Funktion künftig
 * von anderer Stelle gerufen wird.
 */
function zeigeGemerktes(g) {
  if (!g || !g.text) return;
  _letztes = g;
  el.ergebnisFeld.value = g.text;
  el.ergebnis.hidden = false;
  const alter = Math.round((Date.now() - (g.zeit || 0)) / 60000);
  el.ergebnisFuss.textContent =
    g.key + " · " + (g.kommentare || 0) + " Kommentar(e) · "
    + (alter < 1 ? "gerade eben" : "vor " + alter + " Min.")
    + (g.modell ? " · " + g.modell : "");

  if (_key && g.key && _key !== g.key) {
    _fremdesErgebnis = true;
    melde("⚠ Dieser Text gehört zu " + g.key + ", offen ist aber " + _key
          + ". Nicht einfügen, ohne ihn zu prüfen.");
  } else if (g.modus === "ueberarbeiten") {
    melde(mitAbgleich("Gemerkte Überarbeitung – bitte vor dem Absenden lesen.",
                      g.hinweis));
  } else {
    melde(g.modus === "antwort"
      ? "Gemerkter Vorschlag – bitte vor dem Absenden lesen."
      : "Gemerkte Zusammenfassung.");
  }
}

/** Haengt den Abgleich-Hinweis an eine Meldung – oder eben nicht.
 *
 * Der Hinweis kommt vom Server bereits ABGETRENNT (jira_assist._abgleich_teilen)
 * und darf hier nicht in das bearbeitbare Feld geraten: er ist eine Anmerkung
 * FUER den Mitarbeiter, kein Teil der Antwort an den Kunden.
 */
function mitAbgleich(text, hinweis) {
  const h = (hinweis || "").trim();
  return h ? (text + "\n\n⚠ Abgleich mit dem Ticket:\n" + h) : text;
}

function zeige(angemeldet) {
  el.login.hidden = !!angemeldet;
  el.arbeit.hidden = !angemeldet;
  el.abmelden.hidden = !angemeldet;
}

// ── Anmelden ────────────────────────────────────────────────────────────────
$("btn-anmelden").addEventListener("click", async () => {
  const basis = (el.basis.value || "").trim();
  if (!basis) { melde("Bitte die {marke}-Adresse eintragen."); return; }
  if (!/^https:\/\//i.test(basis)) {
    // http scheidet aus: der Token ginge im Klartext über die Leitung.
    melde("Die Adresse muss mit https:// beginnen.");
    return;
  }

  // Die Host-Berechtigung wird ERST HIER erfragt, für genau diesen Server.
  // Deshalb steht die Adresse nicht im Manifest: eine bei der Installation
  // erzwungene Berechtigung für „alle Websites“ wäre für einen einzigen Server
  // unverhältnismäßig – und in Firefox ließe sich die Adresse ohnehin nicht ins
  // signierte Manifest schreiben.
  let muster;
  try { muster = new URL(basis).origin + "/*"; }
  catch (e) { melde("Die Adresse ist keine gültige URL."); return; }

  sperre(true);
  melde("Melde an …", true);
  try {
    const hat = await api.permissions.contains({ origins: [muster] });
    if (!hat) {
      const ok = await api.permissions.request({ origins: [muster] });
      if (!ok) {
        melde("Ohne Zugriffsrecht auf " + muster + " kann die Erweiterung den " +
              "Server nicht erreichen.");
        return;
      }
    }
    const a = await frage({
      art: "anmelden", basis,
      benutzer: (el.benutzer.value || "").trim(),
      kennwort: el.kennwort.value,
      totp: (el.totp.value || "").trim(),
    });
    // Das Kennwort verlässt das Feld, sobald es nicht mehr gebraucht wird.
    el.kennwort.value = "";
    el.totp.value = "";
    brandingHolen(basis);
    zeige(true);
    melde(a.erlaubt ? "" : a.hinweis);
    if (a.erlaubt && !_key) {
      melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
    }
  } catch (e) {
    melde(e.message);
  } finally {
    sperre(false);
  }
});

el.abmelden.addEventListener("click", async () => {
  try { await frage({ art: "abmelden" }); } catch (e) { /* egal */ }
  zeige(false);
  el.ergebnis.hidden = true;
  melde("");
});

// ── Auswerten ───────────────────────────────────────────────────────────────
const ARBEITSTEXT = {
  zusammenfassung: "Fasse das Ticket zusammen … (dauert einige Sekunden)",
  antwort: "Formuliere einen Antwortvorschlag … (dauert einige Sekunden)",
  ueberarbeiten: "Gleiche deinen Entwurf mit dem Ticket ab … "
                 + "(dauert einige Sekunden)",
};
const FERTIGTEXT = {
  zusammenfassung: "",
  antwort: "Vorschlag – bitte vor dem Absenden lesen und anpassen.",
  ueberarbeiten: "Überarbeitete Fassung deines Entwurfs – bitte vor dem "
                 + "Absenden lesen.",
};

async function auswerten(modus, entwurf) {
  if (!_key) {
    melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
    return;
  }
  sperre(true);
  el.ergebnis.hidden = true;
  melde(ARBEITSTEXT[modus] || ARBEITSTEXT.zusammenfassung, true);
  try {
    const a = await frage({
      art: "auswerten", key: _key, modus,
      lang: (navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en",
      hinweis: (el.hinweis.value || "").trim(),
      // Die Vorlage gilt nur für die Zusammenfassung – ein Antwortvorschlag
      // hat seine eigene Aufgabe, dort wäre sie eine zweite Anweisung.
      vorlage: (modus === "zusammenfassung") ? ($("f-vorlage").value || "") : "",
      entwurf: entwurf || "",
    });
    const d = a.daten || {};
    _letztes = { key: d.key, modus: d.modus, text: d.text || "",
                 titel: d.titel || "", kommentare: d.kommentare || 0,
                 hinweis: d.hinweis || "",
                 modell: d.modell || "", zeit: Date.now() };
    _fremdesErgebnis = false;      // frisch geholt = passt zum offenen Ticket
    el.ergebnisFeld.value = d.text || "";
    el.ergebnis.hidden = false;
    // Was das Ergebnis TRÄGT, gehört sichtbar dazu: aus wie vielen Kommentaren
    // es stammt und mit welchem Modell. Ohne das ist eine dünne Antwort nicht
    // von einem dünnen Ticket zu unterscheiden.
    el.ergebnisFuss.textContent =
      d.key + " · " + (d.kommentare || 0) + " Kommentar(e) ausgewertet · " + (d.modell || "");
    melde(mitAbgleich(FERTIGTEXT[modus] || "", d.hinweis));
  } catch (e) {
    melde(e.message);
  } finally {
    sperre(false);
  }
}

$("btn-zusammenfassung").addEventListener("click", () => auswerten("zusammenfassung"));
$("btn-antwort").addEventListener("click", () => auswerten("antwort"));

/* ── Überarbeiten: erst das Kommentarfeld LESEN, dann auswerten ────────────
 *
 * Der Entwurf wird hier geholt und mitgeschickt; der Server liest die Seite
 * nicht (er kennt nur die Ticketnummer). Das ist dieselbe Trennung wie beim
 * Einfügen, nur in die andere Richtung – und derselbe zweistufige Weg: die
 * isolierte Welt zuerst, die Editor-API der Seite nur, wenn das nicht reicht.
 */
async function entwurfHolen() {
  const treffer = await api.scripting.executeScript({
    target: { tabId: _tabId }, func: leseAusJira,
  });
  let r = (treffer && treffer[0] && treffer[0].result) || {};
  // Auch bei „leer“ nachfassen: genau dann trägt oft der TinyMCE-Editor den
  // Text, während die sichtbare textarea daneben leer ist.
  if (!r.ok && r.tinymce_moeglich) {
    try {
      const zweit = await api.scripting.executeScript({
        target: { tabId: _tabId }, world: "MAIN", func: lesenUeberEditorApi,
      });
      const r2 = (zweit && zweit[0] && zweit[0].result) || {};
      // Nur ein ERFOLG zählt: die Meldung des ersten Laufs ist die
      // aussagekräftigere („leer“ statt „kein Editor erreichbar“).
      if (r2.ok) r = r2;
    } catch (e) {
      // `world: "MAIN"` gibt es in Firefox erst ab 128.
    }
  }
  return r;
}

$("btn-ueberarbeiten").addEventListener("click", async () => {
  if (!_key) {
    melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
    return;
  }
  if (_tabId === null) return;
  sperre(true);
  melde("Lese das Kommentarfeld …", true);
  let r;
  try {
    r = await entwurfHolen();
  } catch (e) {
    melde("Das Kommentarfeld ist nicht lesbar: " + ((e && e.message) || e)
          + "\nKopiere deinen Entwurf notfalls von Hand in das Textfeld unten.");
    return;
  } finally {
    sperre(false);
  }
  if (!r || !r.ok) {
    // DIE DIAGNOSE GEHÖRT IN DIE MELDUNG – ohne sie ist der nächste Anlauf
    // wieder Raten (gleiche Lehre wie beim Einfügen).
    const gesehen = (r && r.gesehen && r.gesehen.length)
      ? "\nGefunden: " + r.gesehen.join(", ") : "";
    melde(((r && r.fehler) || "Kein Text im Kommentarfeld gefunden.") + gesehen);
    return;
  }
  await auswerten("ueberarbeiten", r.text);
});

/* Der BEARBEITETE Text wird mitgemerkt – gedrosselt.
 *
 * Wer einen Vorschlag umschreibt und dann in den Jira-Tab wechselt, um das
 * Kommentarfeld zu öffnen, hätte sonst seine Änderungen verloren: das Popup
 * schließt dabei. Bei jedem Tastendruck zu speichern wäre unnötig – eine
 * halbe Sekunde Ruhe genügt.
 */
let _merkTimer = null;
el.ergebnisFeld.addEventListener("input", () => {
  clearTimeout(_merkTimer);
  _merkTimer = setTimeout(async () => {
    if (!_letztes) return;
    _letztes.text = el.ergebnisFeld.value || "";
    try { await frage({ art: "ergebnis_merken", wert: _letztes }); } catch (e) {}
  }, 500);
});

// ── Vorlagen ────────────────────────────────────────────────────────────────
/* Benannte Vorlagen bestimmen, WORAUF eine Zusammenfassung hinausläuft.
 *
 * Gemeinsame Vorlagen pflegt ein Administrator, eigene darf jeder anlegen –
 * die Trennung ist am Server durchgesetzt (jira_vorlagen.speichern), hier wird
 * sie nur ANGEZEIGT. Eine Oberfläche, die das Häkchen versteckt, ist keine
 * Schranke; wer es sich zurückholt, bekommt trotzdem einen Fehler.
 */
let _vorlagen = { global: [], eigene: [], darf_global: false };
let _vorlBearbeitet = "";      // Kennung der gerade bearbeiteten Vorlage

function vorlagenZeichnen() {
  const sel = $("f-vorlage");
  const gewaehlt = sel.value;
  sel.innerHTML = "";
  const standard = document.createElement("option");
  standard.value = "";
  standard.textContent = "Standard";
  sel.appendChild(standard);

  const gruppe = (titel, liste) => {
    if (!liste.length) return;
    const g = document.createElement("optgroup");
    g.label = titel;
    for (const v of liste) {
      const o = document.createElement("option");
      o.value = v.id;
      // textContent: die Namen sind Freitext aus einem Formular.
      o.textContent = v.name;
      g.appendChild(o);
    }
    sel.appendChild(g);
  };
  gruppe("Gemeinsam", _vorlagen.global);
  gruppe("Meine", _vorlagen.eigene);
  sel.value = gewaehlt;                       // Auswahl überlebt das Neuzeichnen
  if (sel.value !== gewaehlt) sel.value = "";  // ...außer sie wurde gelöscht

  const liste = $("vorl-liste");
  liste.innerHTML = "";
  for (const [art, vs] of [["global", _vorlagen.global], ["eigen", _vorlagen.eigene]]) {
    for (const v of vs) {
      // Änderbar ist nur, was einem gehört – oder alles, wenn man Admin ist.
      const darf = (art === "eigen") || _vorlagen.darf_global;
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = v.name + (art === "global" ? " (gemeinsam)" : "");
      li.appendChild(name);
      if (darf) {
        const bearb = document.createElement("button");
        bearb.type = "button";
        bearb.className = "leise ico";
        bearb.title = "Bearbeiten";
        bearb.textContent = "✎";
        bearb.addEventListener("click", () => vorlageInsFormular(v, art === "global"));
        li.appendChild(bearb);

        const weg = document.createElement("button");
        weg.type = "button";
        weg.className = "leise ico";
        weg.title = "Löschen";
        // Mülleimer = löschen (Projektregel). Als Inline-SVG, nicht als Emoji:
        // ein Emoji-Mülleimer wird je System anders gerendert.
        weg.innerHTML = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none"'
          + ' stroke="currentColor" stroke-width="2" stroke-linecap="round"'
          + ' stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/>'
          + '<path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
          + '<line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>';
        weg.addEventListener("click", () => vorlageLoeschen(v));
        li.appendChild(weg);
      }
      liste.appendChild(li);
    }
  }
  $("vorl-global-zeile").hidden = !_vorlagen.darf_global;
}

function vorlageInsFormular(v, global_) {
  _vorlBearbeitet = v ? v.id : "";
  $("f-vorl-name").value = v ? v.name : "";
  $("f-vorl-text").value = v ? v.text : "";
  $("f-vorl-global").checked = !!global_;
  $("vorl-hinweis").textContent = v ? "Ändert „" + v.name + "“." : "";
}

async function vorlagenLaden() {
  try {
    const a = await frage({ art: "vorlagen" });
    _vorlagen = {
      global: (a.daten && a.daten.global) || [],
      eigene: (a.daten && a.daten.eigene) || [],
      darf_global: !!(a.daten && a.daten.darf_global),
    };
    vorlagenZeichnen();
  } catch (e) {
    // Ohne Vorlagen bleibt „Standard“ – das ist kein Grund, den Rest zu sperren.
    $("vorl-hinweis").textContent = e.message;
  }
}

async function vorlageLoeschen(v) {
  if (!(await frageJaNein("Vorlage „" + v.name + "“ löschen?"))) return;
  try {
    await frage({ art: "vorlage_loeschen", id: v.id });
    if (_vorlBearbeitet === v.id) vorlageInsFormular(null, false);
    await vorlagenLaden();
    $("vorl-hinweis").textContent = "Gelöscht.";
  } catch (e) {
    $("vorl-hinweis").textContent = e.message;
  }
}

$("btn-vorlagen").addEventListener("click", () => {
  const box = $("vorlagen-box");
  box.hidden = !box.hidden;
  if (!box.hidden) vorlagenLaden();
});
$("btn-vorlagen-zu").addEventListener("click", () => { $("vorlagen-box").hidden = true; });
$("btn-vorl-neu").addEventListener("click", () => vorlageInsFormular(null, false));

$("btn-vorl-speichern").addEventListener("click", async () => {
  const name = ($("f-vorl-name").value || "").trim();
  const text = ($("f-vorl-text").value || "").trim();
  if (!name || !text) {
    $("vorl-hinweis").textContent = "Name und Anweisung sind nötig.";
    return;
  }
  try {
    const a = await frage({
      art: "vorlage_speichern",
      wert: { id: _vorlBearbeitet, name, text, global: $("f-vorl-global").checked },
    });
    await vorlagenLaden();
    // Die frisch gespeicherte Vorlage gleich auswählen – sonst muss der
    // Benutzer sie im Pulldown suchen, das er gerade gefüllt hat.
    const neu = a.daten && a.daten.vorlage;
    if (neu && neu.id) $("f-vorlage").value = neu.id;
    vorlageInsFormular(null, false);
    $("vorl-hinweis").textContent = "Gespeichert.";
  } catch (e) {
    $("vorl-hinweis").textContent = e.message;
  }
});

// ── Einfügen und Kopieren ───────────────────────────────────────────────────
$("btn-einfuegen").addEventListener("click", async () => {
  const text = el.ergebnisFeld.value || "";
  if (!text.trim() || _tabId === null) return;
  // Ein Text zu einem anderen Vorgang wird nicht ohne Rückfrage eingefügt –
  // das Ergebnis geht am Ende an einen Kunden.
  if (_fremdesErgebnis && !(await frageJaNein())) return;
  sperre(true);
  try {
    const treffer = await api.scripting.executeScript({
      target: { tabId: _tabId },
      func: einfuegenInJira,
      args: [text],
    });
    let r = (treffer && treffer[0] && treffer[0].result) || {};

    /* ZWEITER VERSUCH ÜBER DIE EDITOR-API DER SEITE.
     * Der erste Lauf sieht `window.tinymce` nicht – Content-Scripts leben in
     * einer isolierten Welt. Bei einem WYSIWYG-Editor ist die API aber oft der
     * einzige Weg, der wirklich ankommt (der sichtbare Inhalt hängt dann nicht
     * am DOM-Knoten, den wir beschreiben würden).
     * Nur wenn der erste Weg scheitert: Code im Seitenkontext teilt sich deren
     * globalen Namensraum, das ist kein Standardweg. */
    if (!r.ok && r.tinymce_moeglich) {
      try {
        const zweit = await api.scripting.executeScript({
          target: { tabId: _tabId },
          world: "MAIN",
          func: einfuegenUeberEditorApi,
          args: [text],
        });
        const r2 = (zweit && zweit[0] && zweit[0].result) || {};
        if (r2.ok) r = r2;
      } catch (e) {
        // `world: "MAIN"` gibt es in Firefox erst ab 128 – dort bleibt es beim
        // Ergebnis des ersten Versuchs. Kein eigener Fehler für den Benutzer:
        // die Meldung unten ist die aussagekräftigere.
      }
    }

    if (r.ok) {
      melde("Eingefügt. Bitte in Jira prüfen und selbst abschicken.");
    } else {
      // DIE DIAGNOSE GEHÖRT IN DIE MELDUNG. Ohne sie ist der nächste Anlauf
      // wieder Raten – und zwar für den Benutzer wie für die Fehlersuche.
      const gesehen = (r.gesehen && r.gesehen.length)
        ? "\nGefunden: " + r.gesehen.join(", ")
        : "";
      melde((r.fehler || "Einfügen fehlgeschlagen.") + gesehen);
    }
  } catch (e) {
    // Häufigster Fall: die Seite verbietet die Injektion (z. B. eine
    // Browser-interne Seite) oder activeTab gilt nicht mehr.
    melde("Einfügen nicht möglich: " + ((e && e.message) || e) +
          "\nBenutze „Kopieren“ und füge den Text von Hand ein.");
  } finally {
    sperre(false);
  }
});

$("btn-kopieren").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(el.ergebnisFeld.value || "");
    melde("In die Zwischenablage kopiert.");
  } catch (e) {
    // Rückmeldung ist Pflicht: in der Zwischenablage sieht man nichts, ein
    // stiller Fehlschlag wäre unsichtbar.
    melde("Kopieren fehlgeschlagen. Markiere den Text und kopiere ihn von Hand.");
  }
});

/* Von Hand leeren – bewusst OHNE Rückfrage.
 *
 * `window.confirm` ist in einem Extension-Popup ohnehin keine Option (siehe
 * frageJaNein), und ein eigener Dialog wäre hier zu viel: der Text lässt sich
 * mit einem Klick neu erzeugen, verloren geht höchstens eine Bearbeitung. Der
 * Knopf ist als `leise` gezeichnet und steht hinter dem Kopieren.
 */
$("btn-leeren").addEventListener("click", async () => {
  await felderLeeren("Geleert.");
});

start();
