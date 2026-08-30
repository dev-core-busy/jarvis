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

/* LAEUFT GERADE EINE AUSWERTUNG? Gesetzt von `sperre`.
 *
 * Nur in der Seitenleiste von Belang: dort kann der Benutzer den Tab wechseln,
 * WAEHREND eine Auswertung laeuft. Die Felder dann zu leeren wuerde das
 * Ergebnis wegwerfen, fuer das er gerade wartet. */
let _laeuft = false;

/* SEITENLEISTE ODER POPUP.
 *
 * ⚠ DER ABFRAGETEIL ALLEIN GENUEGT NICHT – gemeldet 2026-08-30 (Chrome 152):
 * „ich kann die Seitenleiste nur ueber die plugin Steuerung oeffnen. Dann wird
 * aber ein TAB Wechsel nicht erkannt." Zutreffend. `?ansicht=leiste` kommt nur
 * mit, wenn die Leiste ueber UNSEREN Weg aufgeht; oeffnet der Benutzer sie
 * ueber **Chromes eigene Seitenleisten-Auswahl**, laedt Chrome
 * `side_panel.default_path`, also `popup.html` ohne Abfrageteil. Das Fenster
 * hielt sich dann fuer ein Popup und registrierte KEINEN einzigen Tab-Zuhoerer.
 *
 * Der Anfangswert bleibt die Klasse (ansicht.js setzt sie vor dem ersten
 * Zeichnen, das ist fuer die Breite noetig); die verbindliche Antwort kommt
 * gleich darauf vom Hintergrund (`kontextArt` ueber runtime.getContexts) und
 * wird hier nachgetragen. */
let _leiste = document.documentElement.classList.contains("leiste");
let _windowId = null;
let _tabUrl = "";
// Adresse des Jira-Servers, einmal vom Server geholt (siehe zugriffZeile).
let _jiraBasis = "";

/** Traegt die verbindliche Antwort des Hintergrunds nach. */
function leisteFeststellen(kontext) {
  // Nur EINSCHALTEN, nie ausschalten: sagt der Hintergrund nichts (aeltere
  // Browser, Firefox ohne getContexts), bleibt es beim Abfrageteil - der ist
  // dann die einzige Auskunft, die es gibt.
  if (kontext !== "SIDE_PANEL" && kontext !== "SIDEBAR") return;
  _leiste = true;
  document.documentElement.classList.add("leiste");
}

// ── Meldungen ───────────────────────────────────────────────────────────────
function melde(text, arbeitet = false) {
  if (!text) {
    /* ⚠ AUCH INHALT UND KLASSE RAEUMEN, nicht nur verstecken.
     *
     * Bis 2026-08-30 stand hier nur `hidden = true`. Der alte Text blieb im
     * DOM, der drehende Kreis blieb Kind, und die Klasse `arbeitet` blieb
     * gesetzt - deren `display: flex` ueberstimmt das `hidden`-Attribut, also
     * blieb die Wartemeldung sichtbar STEHEN. Die CSS-Regel `.meldung[hidden]`
     * faengt das jetzt strukturell ab; hier wird zusaetzlich der Zustand
     * beseitigt, damit gar nichts Altes mehr herumliegt. */
    el.meldung.hidden = true;
    el.meldung.textContent = "";
    el.meldung.classList.remove("arbeitet");
    return;
  }
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
  _laeuft = !!an;
  if (an) {
    for (const b of document.querySelectorAll("button")) b.disabled = true;
    return;
  }
  /* ⚠ NICHT blind alles freigeben. Bis 2026-08-30 stand hier
   * `b.disabled = an` fuer JEDEN Knopf – damit haette das Ende eines Laufs die
   * Ticket-Sperre wieder aufgehoben, und zwar genau dann, wenn der Benutzer
   * waehrenddessen auf einen fremden Tab gewechselt ist. */
  knoepfeAktualisieren();
}

/** Sperrt alles, was ein Ticket braucht – und gibt es wieder frei.
 *
 * ⚠ DIE RICHTUNG IST FAIL-CLOSED, und das ist der ganze Entwurf: gesperrt wird
 * pauschal JEDER Knopf, ausgenommen sind nur die wenigen mit
 * `data-ohne-ticket` im Markup. Andersherum – eine Liste der zu sperrenden
 * Knoepfe – waere ein kuenftig ergaenzter Knopf ohne Eintrag **bedienbar**,
 * obwohl er ohne Ticket nichts tun kann; so ist er hoechstens einmal zu viel
 * gesperrt. Das ist die harmlosere Halbfehlerstellung.
 *
 * Bedienbar bleiben: Anmelden (sonst kaeme man von einem fremden Tab aus nie
 * hinein), Abmelden (sonst nie hinaus), die Schliessen-Knoepfe der beiden
 * Dialoge (ein Dialog, den man nicht wegbekommt, ist eine Falle) und die
 * Zugriffsabfrage der Seitenleiste.
 */
function knoepfeAktualisieren() {
  // Waehrend eines Laufs entscheidet `sperre` allein – sonst gaebe ein
  // Tab-Wechsel mitten in einer Auswertung die Knoepfe wieder frei.
  if (_laeuft) return;
  const aus = !_key;
  for (const b of document.querySelectorAll("button")) {
    b.disabled = aus && !b.hasAttribute("data-ohne-ticket");
  }
}

/** Setzt die Ticketanzeige im Kopf – und zieht die Knopf-Sperre nach.
 *
 * Beides gehoert in EINE Funktion: die Anzeige ist die Begruendung fuer die
 * Sperre. Stuenden sie getrennt, waere der naechste Zustand denkbar, in dem
 * Knoepfe grau sind und im Kopf trotzdem eine Ticketnummer steht.
 */
function ticketAnzeigen() {
  el.ticket.textContent = _key || "Kein Ticket gefunden";
  // Die Aussage traegt der TEXT; die Faerbung sagt nur zusaetzlich, dass hier
  // keine Ticketnummer steht (Farbe allein ist im Projekt keine Information).
  el.ticket.classList.toggle("leer", !_key);
  knoepfeAktualisieren();
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

/* DIE SERVERADRESSE AUS DEM PAKET – dieselbe Bauart wie Marke und Farbe, und
 * derselbe Zweck: etwas, das beim ALLERERSTEN Oeffnen schon dastehen muss.
 *
 * Sie gehoert zum Fix "man muss sich 2x anmelden": das Manifest traegt genau
 * diese Adresse als Host-Recht, also muss auch das Feld sie tragen. Tippt
 * jemand eine abweichende Schreibweise (IP statt Name, Port dazu), gilt das
 * vorbelegte Recht nicht und die Nachfrage waere wieder da.
 *
 * Nur https wird uebernommen - ein anderer Wert im Paket waere ein Feld, das
 * der Anmelden-Knopf gleich darauf ablehnt.
 */
function _vorgabeBasis() {
    const m = document.querySelector('meta[name="basis"]');
    const wert = ((m && m.content) || "").trim().replace(/\/+$/, "");
    return /^https:\/\/[^\s"']+$/i.test(wert) ? wert : "";
}

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
    // Das Zugriffsrecht gilt je Adresse: wer eine andere eintraegt, braucht
    // moeglicherweise eine neue Nachfrage – und soll das VORHER lesen, nicht
    // erst, wenn sein Klick auf "Anmelden" im Nichts endet.
    zugriffAnzeigen();
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
  // Das Fenster braucht `sidePanel.open`, die Adresse die Zugriffszeile.
  _windowId = t && (t.windowId !== undefined) ? t.windowId : null;
  _tabUrl = (t && t.url) || "";
  _key = keyAusUrl(t && t.url);
  ticketAnzeigen();
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
  /* DIE ADRESSE: gemerkt schlägt Paket-Vorgabe. Wer seinen Server umgestellt
   * hat, soll seine Eingabe behalten – die Vorgabe aus dem ZIP ist nur die
   * Starthilfe für das allererste Öffnen (siehe <meta name="basis">). */
  el.basis.value = z.basis || _vorgabeBasis();
  // Der zuletzt eingetippte Benutzername steht wieder da, wenn die
  // Berechtigungsabfrage das Fenster geschlossen hat. Das Kennwort nie.
  if (!z.angemeldet && z.benutzer_vorschlag && !el.benutzer.value) {
    el.benutzer.value = z.benutzer_vorschlag;
  }
  // Marke setzen, sobald eine Adresse bekannt ist – das geht ohne Anmeldung
  // und damit schon beim allerersten Öffnen nach dem Einrichten.
  if (el.basis.value) brandingHolen(el.basis.value);
  // ZUERST klaeren, WAS dieses Fenster ist - davon haengen Breite, Beschriftung
  // des Umschalters und die Tab-Beobachtung ab.
  leisteFeststellen(z.kontext);
  // Der Umschalter gilt unabhaengig von der Anmeldung – wer in der Leiste
  // steht und zurueck will, muss das auch ohne Konto koennen.
  ansichtZeigen(z.ansicht, z.leiste_moeglich);
  zeige(z.angemeldet);
  if (!z.angemeldet) {
    await zugriffAnzeigen();
    /* Nach dem Wiederöffnen SAGEN, was passiert ist. Ohne diesen Satz sieht
     * die Maske aus wie beim ersten Mal, und der Benutzer weiß nicht, ob die
     * Erlaubnis angekommen ist – genau das war die Verwirrung hinter „man muss
     * sich 2x anmelden". Der Merker gilt einmalig und wird sofort verworfen. */
    if (z.zugriff_erfragt && (await hatZugriff(el.basis.value)) === true) {
      try { await frage({ art: "merken", zugriff_erfragt: false }); } catch (e) {}
      melde("Zugriff erteilt. Bitte jetzt anmelden.");
      el.kennwort.focus();
    }
  }
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
    await ticketLageAnwenden(z.ergebnis);
    leisteBeobachten();
  }
}

/** Bringt Anzeige und Gedaechtnis mit dem offenen Tab in Einklang.
 *
 * Stand bis 2026-08-30 wortgleich in `start()`. Herausgezogen, weil die
 * Seitenleiste dieselbe Pruefung BEI JEDEM TAB-WECHSEL braucht – im Popup lief
 * sie genau einmal, weil das Fenster danach ohnehin zu war.
 */
async function ticketLageAnwenden(gemerkt) {
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
  } else {
    melde("");
  }
  await zugriffZeileAktualisieren();
}

/* ── Der Tab-Wechsel ist der PREIS der Seitenleiste ─────────────────────────
 *
 * ⚠ UND ER IST EINE SICHERHEITSFRAGE, KEINE BEQUEMLICHKEIT. Das Popup schloss
 * sich beim Wechsel in einen anderen Tab; `start()` lief danach neu und pruefte
 * den Ticketbezug erneut. Die Leiste bleibt offen – ohne diese Beobachtung
 * stuende ein fertiger Antwortentwurf zu TICKET-A neben dem geoeffneten
 * TICKET-B, und der Text geht am Ende an einen echten Kunden. Genau dagegen ist
 * `felderLeeren` gebaut (Vorgabe 2026-08-28: bei Abweichung wird GELEERT).
 *
 * Im Popup wird NICHT beobachtet: dort gibt es keinen Wechsel zu sehen, und ein
 * Zuhoerer, der nie feuert, ist nur eine Fehlerquelle mehr.
 */
function leisteBeobachten() {
  if (!_leiste || leisteBeobachten._an) return;
  leisteBeobachten._an = true;   // idempotent: `start()` kann erneut laufen
  try {
    api.tabs.onActivated.addListener(() => { tabWechsel(); });
    api.tabs.onUpdated.addListener((tabId, info, tab) => {
      /* ⚠ HIER DARF NICHT AUF `info.url` GEFILTERT WERDEN.
       *
       * Das war die zweite Haelfte des gemeldeten Fehlers: `changeInfo.url`
       * liefert der Browser NUR mit der `tabs`-Berechtigung oder mit einem
       * Host-Recht fuer genau diese Seite. Die Erweiterung hat beides von Haus
       * aus nicht (`activeTab` ist etwas anderes) – der Filter traf also nie
       * zu, und der Zuhoerer war so gut wie tot.
       * Jetzt entscheidet der VERGLEICH in `tabWechsel`: der ist ohnehin
       * noetig, kostet nur eine Abfrage und ist gegen jede Zustandsaenderung
       * unempfindlich (er kehrt sofort um, wenn sich die Ticketnummer nicht
       * geaendert hat). */
      if (tab && tab.active) tabWechsel();
    });
  } catch (e) {
    // Ohne Zuhoerer verhaelt sich die Leiste wie das Popup von frueher: der
    // Ticketbezug wird beim Oeffnen geprueft, danach nicht mehr. Die Warnung
    // in `fremd()` traegt dann allein.
  }
}

async function tabWechsel() {
  const vorher = _key;
  await tabErmitteln();
  if (_key === vorher) { await zugriffZeileAktualisieren(); return; }

  /* LAEUFT GERADE EINE AUSWERTUNG, WIRD NICHTS GELEERT. Der Benutzer wartet
   * auf genau dieses Ergebnis; es wegzuwerfen, weil er nebenbei nachgesehen
   * hat, waere die teuerste Reaktion. Gewarnt wird trotzdem – und die
   * Einfuege-Schranke greift ohnehin, sie leitet den Fremdbezug aus dem
   * Zustand ab (siehe `fremd()`). */
  if (_laeuft) {
    melde("⚠ Der Tab hat gewechselt, während eine Auswertung läuft. Das "
          + "Ergebnis gehört zum vorher offenen Ticket.");
    await zugriffZeileAktualisieren();
    return;
  }
  await ticketLageAnwenden(_letztes);
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

/** Gehoert der angezeigte Text zu einem ANDEREN Ticket als dem offenen Tab?
 *
 * ⚠ ABGELEITET, NICHT NUR GEMERKT. Bis 2026-08-30 entschied allein das Flag
 * `_fremdesErgebnis`, und das wird nur an zwei Stellen gesetzt – beim
 * Wiederherstellen eines gemerkten Textes und beim Auswerten. Im Popup genuegte
 * das, weil sich der offene Tab waehrend seiner Lebensdauer nicht aendern
 * konnte. In der Seitenleiste kann er das jederzeit; ein Flag, das dabei
 * stehenbleibt, waere genau die Luecke, gegen die die Schranke gebaut ist.
 * Der Vergleich hier fragt den ZUSTAND und kann nicht veralten.
 */
function fremd() {
  if (_fremdesErgebnis) return true;
  return !!(_letztes && _letztes.key && _key && _letztes.key !== _key);
}

function zeige(angemeldet) {
  el.login.hidden = !!angemeldet;
  el.arbeit.hidden = !angemeldet;
  el.abmelden.hidden = !angemeldet;
}

// ── Zugriffsrecht auf den Server ────────────────────────────────────────────
/* ⚠ HIER LAG DIE MELDUNG „man muss sich 2x anmelden".
 *
 * Fehlt das Host-Recht, muss es erfragt werden – und **Chrome schließt dabei
 * das Popup**. Bis 2026-08-28 stand die Abfrage MITTEN im Anmelde-Ablauf:
 * Klick auf „Anmelden" → Abfrage → Fenster weg → die Zugangsdaten wurden nie
 * abgeschickt. Beim zweiten Anlauf war das Recht da und es ging. Nach außen
 * eine Anmeldung, die beim ersten Mal nicht zählt.
 *
 * Drei Dinge zusammen lösen das:
 *  1. Der Server schreibt seine Adresse als Host-Recht ins Paket – in Chrome
 *     kommt die Abfrage dann gar nicht mehr (jira_assist._manifest_gebrandet).
 *  2. Bleibt sie doch nötig (Firefox, abweichende Adresse, Altpaket), wird
 *     sie ZUERST erledigt und ANGEKÜNDIGT, nicht mitten im Anmelden.
 *  3. Adresse und Benutzername werden vorher gemerkt – schließt das Fenster,
 *     steht beim nächsten Öffnen alles außer dem Kennwort wieder da.
 */
function hostMuster(basis) {
  try { return new URL(basis).origin + "/*"; }
  catch (e) { return ""; }
}

/** Ist das Zugriffsrecht für diese Adresse da? `null` = nicht feststellbar. */
async function hatZugriff(basis) {
  const muster = hostMuster(basis);
  if (!muster) return null;
  try { return await api.permissions.contains({ origins: [muster] }); }
  catch (e) { return null; }
}

/** Blendet die Erklärung über dem Anmelden-Knopf ein – oder aus.
 *
 * „Nicht feststellbar" wird wie „vorhanden" behandelt: eine Warnung, die auf
 * einer Vermutung beruht, verunsichert bei einer funktionierenden Einrichtung.
 * Fehlt das Recht wirklich, meldet sich der Aufruf ohnehin.
 */
async function zugriffAnzeigen() {
  const p = $("zugriff-hinweis");
  if (!p) return;
  const basis = (el.basis.value || "").trim();
  if (!basis || (await hatZugriff(basis)) !== false) { p.hidden = true; return; }
  p.textContent =
    "Beim ersten Anmelden fragt der Browser nach dem Zugriffsrecht für "
    + basis + ". Bestätige die Nachfrage – dieses Fenster schließt dabei "
    + "möglicherweise. Öffne es danach einfach erneut, Adresse und Benutzer "
    + "stehen dann noch da.";
  p.hidden = false;
}

/** Beschafft das Zugriffsrecht. `true` = vorhanden (ggf. gerade erteilt).
 *
 * ⚠ NACH DEM `request` KANN DAS FENSTER WEG SEIN – der Rückgabewert kommt
 * dann nie an, und das ist kein Fehler, sondern der Normalfall in Chrome.
 * Deshalb steht vorher alles im Speicher, was der nächste Anlauf braucht.
 */
async function zugriffSichern(basis) {
  const muster = hostMuster(basis);
  if (!muster) throw new Error("Die Adresse ist keine gültige URL.");
  if ((await hatZugriff(basis)) === true) return true;
  await frage({ art: "merken", basis,
                benutzer: (el.benutzer.value || "").trim(),
                zugriff_erfragt: true });
  let ok = false;
  try {
    ok = await api.permissions.request({ origins: [muster] });
  } catch (e) {
    // Chrome verlangt für `request` eine Benutzeraktion. Geht sie verloren,
    // ist die Meldung („must be called during a user gesture") für niemanden
    // deutbar – der Weg zurück ist ein erneuter Klick.
    throw new Error("Die Berechtigungsabfrage ließ sich nicht öffnen. Bitte "
                    + "drücke „Anmelden“ noch einmal.");
  }
  if (!ok) {
    throw new Error("Ohne Zugriffsrecht auf " + muster + " kann die "
                    + "Erweiterung den Server nicht erreichen. Drücke "
                    + "„Anmelden“ erneut und bestätige die Nachfrage.");
  }
  return true;
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

  sperre(true);
  try {
    // ZUERST das Zugriffsrecht, DANN die Anmeldung – nie umgekehrt und nie
    // vermischt (Begründung im Block darüber).
    melde("Prüfe das Zugriffsrecht …", true);
    await zugriffSichern(basis);

    melde("Melde an …", true);
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
    // Der Hinweis über dem Knopf wird nachgezogen: scheiterte es am
    // Zugriffsrecht, muss dort jetzt stehen, was zu tun ist.
    zugriffAnzeigen();
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
let _vorlagen = { global: [], eigene: [], darf_global: false, standard: "" };
let _vorlBearbeitet = "";      // Kennung der gerade bearbeiteten Vorlage
// Hat der Benutzer in DIESEM Fenster schon selbst gewählt? Dann gewinnt seine
// Wahl gegen den Standard – sonst überschriebe ein Neuzeichnen (nach dem
// Speichern einer Vorlage) die gerade getroffene Auswahl.
let _vorlBeruehrt = false;

function vorlagenZeichnen() {
  const sel = $("f-vorlage");
  const gewaehlt = sel.value;
  sel.innerHTML = "";
  const ohne = document.createElement("option");
  ohne.value = "";
  // NICHT „Standard“: seit es eine markierbare Standard-Vorlage gibt, hieße
  // dasselbe Wort zwei verschiedene Dinge – der eingebaute Ablauf und die
  // Vorlage mit dem Stern.
  ohne.textContent = "Ohne Vorlage";
  sel.appendChild(ohne);

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
  // Die Auswahl überlebt das Neuzeichnen; wurde sie gelöscht, bleibt „ohne“.
  // Hat der Benutzer noch gar nichts angefasst, gilt SEIN Standard – genau
  // dafür gibt es ihn. Der Server liefert nur eine Kennung, die es wirklich
  // gibt (jira_vorlagen._standard_aus), ein Fehlgriff ist hier also keiner.
  const wunsch = _vorlBeruehrt ? gewaehlt : (_vorlagen.standard || gewaehlt);
  sel.value = wunsch;
  if (sel.value !== wunsch) sel.value = "";

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

      /* DER STERN STEHT AN JEDER ZEILE, auch an fremden (gemeinsamen)
       * Vorlagen: markiert wird nicht die Vorlage, sondern die eigene Wahl.
       * Deshalb hängt er NICHT an `darf` – wer eine gemeinsame Vorlage nicht
       * ändern darf, darf sie sehr wohl zu seinem Standard machen. */
      const istStd = _vorlagen.standard === v.id;
      const stern = document.createElement("button");
      stern.type = "button";
      stern.className = "leise ico stern" + (istStd ? " an" : "");
      // Der Knopf sagt, was ein Klick TUT – nicht, was gerade gilt. Bei einem
      // gesetzten Standard ist das Aufheben die Wirkung.
      stern.title = istStd ? "Standard aufheben" : "Als Standard markieren";
      stern.setAttribute("aria-label", stern.title);
      stern.setAttribute("aria-pressed", istStd ? "true" : "false");
      stern.textContent = istStd ? "★" : "☆";
      stern.addEventListener("click", () => standardSetzen(istStd ? "" : v.id));
      li.appendChild(stern);

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
  /* ⚠ DIE ZEILEN-KNOEPFE ENTSTEHEN HIER ERST – Stern, Bearbeiten, Loeschen.
   * Ein einmaliger Durchlauf ueber `button` beim Tab-Wechsel erwischt sie
   * nicht: sie existieren zu dem Zeitpunkt noch gar nicht, und beim naechsten
   * Neuzeichnen waeren sie wieder bedienbar. Deshalb wird die Sperre HIER
   * nachgezogen. */
  knoepfeAktualisieren();
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
      standard: (a.daten && a.daten.standard) || "",
    };
    vorlagenZeichnen();
  } catch (e) {
    // Ohne Vorlagen bleibt „Ohne Vorlage“ – kein Grund, den Rest zu sperren.
    $("vorl-hinweis").textContent = e.message;
  }
}

/** Standard setzen oder aufheben. `""` hebt auf.
 *
 * Die Liste wird danach NEU GELADEN statt nur der Stern umgemalt: der Server
 * ist die Wahrheit, und er weist eine Kennung ab, die er nicht kennt. Ein
 * lokal umgemalter Stern hätte sonst einen Standard behauptet, den es nicht
 * gibt – und beim nächsten Öffnen stünde wieder „Ohne Vorlage“ da.
 */
async function standardSetzen(vid) {
  try {
    await frage({ art: "vorlage_standard", id: vid });
    // Ein frisch gesetzter Standard soll SOFORT im Pulldown stehen – sonst
    // markiert jemand seine Vorlage und muss sie trotzdem noch auswählen.
    _vorlBeruehrt = false;
    await vorlagenLaden();
    $("vorl-hinweis").textContent = vid
      ? "Als Standard markiert."
      : "Standard aufgehoben.";
  } catch (e) {
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

// Eine eigene Wahl gewinnt gegen den Standard, bis das Fenster wieder zugeht.
// Ohne diesen Merker holte jedes Neuzeichnen (Speichern, Löschen, Stern) den
// Standard zurück und verstellte die gerade getroffene Auswahl.
$("f-vorlage").addEventListener("change", () => { _vorlBeruehrt = true; });

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
    // Gilt als eigene Wahl – sonst zöge das nächste Neuzeichnen den Standard
    // vor und die gerade gespeicherte Vorlage wäre wieder abgewählt.
    if (neu && neu.id) { $("f-vorlage").value = neu.id; _vorlBeruehrt = true; }
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
  if (fremd() && !(await frageJaNein())) return;
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

/* ── Dauerhaftes Zugriffsrecht auf die Jira-Seite (nur Seitenleiste) ───────
 *
 * DAS POPUP BRAUCHT DAS NICHT, und deshalb wird hier auch nichts erfragt,
 * solange es eines ist: `activeTab` erteilt das Recht fuer genau den Tab, in
 * dem der Benutzer die Erweiterung angeklickt hat – und das Popup lebt nicht
 * laenger als dieser Klick.
 *
 * Die Leiste bleibt ueber den Tab-Wechsel hinaus offen. Fuer den NAECHSTEN Tab
 * gilt `activeTab` nicht mehr; „Überarbeiten" und „Einfügen" liefen dort in
 * genau die Meldung, die weiter unten schon steht („activeTab gilt nicht
 * mehr") – eine Meldung, aus der niemand ableiten kann, was zu tun ist.
 *
 * ⚠ ERFRAGT WIRD UEBER EINEN EIGENEN KNOPF, nicht nebenbei aus dem
 * Fehlerzweig. `permissions.request` verlangt eine Benutzergeste, und die ist
 * nach dem ersten `await` verbraucht – ein Nachfragen nach einem
 * fehlgeschlagenen `executeScript` wuerde mit "must be called during a user
 * gesture" abgelehnt, also wortlos nichts tun.
 */
function herkunftAus(adresse) {
  try {
    const u = new URL(adresse);
    // Nur https: `optional_host_permissions` deckt nur das ab, und ueber http
    // wuerde das Sitzungstoken der Seite ohnehin nichts gewinnen.
    return (u.protocol === "https:") ? u.origin : "";
  } catch (e) { return ""; }
}

function tabHerkunft() { return herkunftAus(_tabUrl); }

/** Die Adresse des Jira-Servers – einmal beim Server erfragt, dann gemerkt.
 *
 * ⚠ OHNE SIE WAERE DIE ZUGRIFFSZEILE UNERREICHBAR, GENAU WENN MAN SIE BRAUCHT.
 * Fehlt das Host-Recht, liefert `tabs.query` fuer einen fremden Tab GAR KEINE
 * Adresse – dann gibt es keine Ticketnummer, und die Zeile haette sich an
 * einer Ticketnummer festgemacht: ein Kreis, aus dem der Benutzer nicht
 * herauskommt. Die Berechtigungsabfrage muss aber einen Ort nennen koennen,
 * und den kennt die Erweiterung von sich aus nicht.
 * Fehlschlag ist kein Fehler: dann bleibt es beim Weg ueber die Tab-Adresse.
 */
async function jiraBasisHolen() {
  if (_jiraBasis) return _jiraBasis;
  try {
    const a = await frage({ art: "health" });
    _jiraBasis = ((a.daten || {}).jira_basis || "").replace(/\/+$/, "");
  } catch (e) {
    _jiraBasis = "";
  }
  return _jiraBasis;
}

async function zugriffZeileAktualisieren() {
  const p = $("leiste-zugriff");
  if (!p) return;
  // Das Popup kommt mit `activeTab` aus - dort ist die Zeile immer aus.
  if (!_leiste) { p.hidden = true; return; }

  /* WELCHE HERKUNFT WIRD ERFRAGT? Steht in diesem Tab ein erkanntes Ticket,
   * ist seine Herkunft der richtige und sicherste Ort. Sonst die Adresse des
   * Jira-Servers laut Jarvis – NIE die eines beliebigen fremden Tabs: sonst
   * bekaeme jemand, der die Leiste im Intranet oeffnet, eine
   * Berechtigungsabfrage fuer das Intranet, die ihm gar nichts nuetzt. */
  const blind = !_tabUrl;
  const herkunft = (_key && tabHerkunft()) || herkunftAus(await jiraBasisHolen());
  if (!herkunft) { p.hidden = true; return; }

  let da = null;
  try { da = await api.permissions.contains({ origins: [herkunft + "/*"] }); }
  catch (e) { da = null; }
  /* „Nicht feststellbar" wird wie „vorhanden" behandelt – dieselbe Regel wie
   * in `zugriffAnzeigen`: eine Aufforderung, die auf einer Vermutung beruht,
   * verunsichert bei einer funktionierenden Einrichtung. */
  if (da !== false) { p.hidden = true; return; }

  /* OHNE LESBARE TAB-ADRESSE IST DAS KEINE EMPFEHLUNG MEHR, SONDERN DIE
   * VORAUSSETZUNG - dann erkennt die Leiste ueberhaupt kein Ticket. Der Text
   * muss das unterscheiden, sonst sucht der Benutzer den Fehler bei sich. */
  $("leiste-zugriff-text").textContent = blind
    ? "Die Seitenleiste kann die Adresse des offenen Tabs nicht lesen und "
      + "erkennt deshalb kein Ticket. Erlaube ihr dauerhaften Zugriff auf "
      + herkunft + " – das kurzfristige Recht aus dem Klick auf das Symbol "
      + "gilt nur für den Tab, aus dem sie geöffnet wurde. "
    : "Damit die Seitenleiste beim Tab-Wechsel mitkommt und „Überarbeiten“ "
      + "und „Einfügen“ weiter funktionieren, braucht sie dauerhaften Zugriff "
      + "auf " + herkunft + ". ";
  p.hidden = false;
}

$("btn-leiste-zugriff").addEventListener("click", async () => {
  const herkunft = tabHerkunft();
  if (!herkunft) return;
  try {
    const ok = await api.permissions.request({ origins: [herkunft + "/*"] });
    melde(ok
      ? "Zugriff auf " + herkunft + " erteilt."
      : "Ohne das Zugriffsrecht bleiben „Überarbeiten“ und „Einfügen“ auf den "
        + "Tab beschränkt, aus dem die Leiste geöffnet wurde.");
  } catch (e) {
    melde("Die Berechtigungsabfrage ließ sich nicht öffnen: "
          + ((e && e.message) || e));
  }
  /* Neu ERMITTELN, nicht nur neu zeichnen: mit dem Recht ist die Adresse des
   * offenen Tabs jetzt lesbar - und damit womoeglich zum ersten Mal eine
   * Ticketnummer. Ohne das stuende weiter "Kein Ticket gefunden" da, obwohl
   * gerade alles dafuer erledigt wurde. */
  await tabErmitteln();
  await ticketLageAnwenden(_letztes);
});

/* ── Umschalter Popup ↔ Seitenleiste ───────────────────────────────────────
 *
 * Der Zustand liegt im Hintergrund (background.js::ansichtAnwenden), weil nur
 * dort `action.setPopup` und die Panel-Einstellungen gesetzt werden koennen –
 * und weil sie einen Browserstart ueberdauern muessen.
 */
function ansichtZeigen(wert, moeglich) {
  const zeile = $("ansicht-zeile");
  const kasten = $("f-ansicht");
  const h = $("ansicht-hinweis");
  if (!zeile || !kasten) return;

  /* ⚠ DIE ZEILE BLEIBT SICHTBAR, AUCH WENN DER BROWSER KEINE LEISTE KANN.
   *
   * Hier stand die Gegenregel („ein Schalter fuer etwas, das es nicht gibt,
   * ist schlimmer als kein Schalter"). Die Meldung vom 2026-08-30 hat sie
   * widerlegt: „keine Moeglichkeit die Seitenleiste auszuwaehlen" – und weder
   * der Benutzer noch ich konnten von aussen unterscheiden, ob der Schalter
   * FEHLT, ob er ausgeblendet WURDE oder ob er nur ausserhalb des
   * Sichtfensters lag. Ein unsichtbares Bedienelement ist unerklaerbar.
   * Ein gesperrtes MIT GRUND ist besser als beides: es sagt, dass es die
   * Funktion gibt, und warum sie hier nicht geht. */
  zeile.hidden = false;
  kasten.checked = (wert === "leiste");
  kasten.disabled = !moeglich;
  zeile.classList.toggle("aus", !moeglich);
  if (!h) return;
  h.textContent = !moeglich
    ? "Dieser Browser stellt keine Seitenleiste für Erweiterungen bereit "
      + "(nötig: Chrome/Edge ab 114 oder Firefox ab 115)."
    : (_leiste
      ? "Die Breite ziehst du an der Kante der Leiste."
      : "Öffnet sich beim nächsten Klick auf das Symbol in der Symbolleiste.");
  h.hidden = false;
}

/** Oeffnet die Leiste. Gibt zurueck, ob sie WIRKLICH aufgegangen ist.
 *
 * Beide APIs verlangen eine Benutzergeste. Schlaegt der Aufruf deshalb fehl,
 * ist das kein Fehler: die Einstellung ist zu diesem Zeitpunkt bereits
 * gespeichert, der naechste Klick auf das Symbol oeffnet die Leiste. Genau das
 * sagt die Meldung dann auch – ein stiller Fehlschlag waere die schlechtere
 * Auskunft.
 */
async function leisteOeffnen() {
  try {
    if (api.sidebarAction && api.sidebarAction.open) {
      await api.sidebarAction.open();
      return true;
    }
    if (api.sidePanel && api.sidePanel.open && _windowId !== null) {
      await api.sidePanel.open({ windowId: _windowId });
      return true;
    }
  } catch (e) { /* Fehlschlag ist kein Fehler – siehe oben. */ }
  return false;
}

$("f-ansicht").addEventListener("change", async (ereignis) => {
  const wert = ereignis.target.checked ? "leiste" : "popup";

  /* ⚠ ERST SPEICHERN – UND ZWAR ABGEWARTET –, DANN OEFFNEN.
   *
   * Die erste Fassung machte es umgekehrt: absenden ohne zu warten, sofort
   * oeffnen, damit die Benutzergeste fuer `sidePanel.open` erhalten bleibt.
   * Das war die Ursache der Meldung „ich kann die Seitenleiste nur ueber die
   * plugin Steuerung oeffnen" (2026-08-30): **Chrome zerstoert das Popup, wenn
   * die Leiste aufgeht** – die Nachricht war da noch unterwegs, die Einstellung
   * wurde nie gespeichert, und der naechste Klick auf das Symbol oeffnete
   * wieder das Popup. Der Umschalter war damit faktisch wirkungslos.
   *
   * Die Abwaegung ist eindeutig: eine nicht gespeicherte Einstellung macht den
   * Schalter kaputt, eine verlorene Benutzergeste kostet einen Klick – und die
   * Meldung sagt dann, welchen. */
  let a;
  try {
    a = await frage({ art: "ansicht", wert });
  } catch (e) {
    // Zuruecksetzen, sonst behauptet das Haekchen einen Zustand, den es nicht
    // gibt.
    ereignis.target.checked = (wert !== "leiste");
    melde(e.message);
    return;
  }
  ansichtZeigen(a.wert, a.leiste_moeglich);

  if (wert !== "leiste") {
    melde(_leiste
      ? "Umgestellt. Das Symbol öffnet ab jetzt wieder das kleine Fenster – "
        + "diese Leiste kannst du schließen."
      : "Umgestellt.");
    return;
  }
  // Gelingt das Oeffnen, ist dieses Fenster gleich weg und die Meldung wird
  // ohnehin niemand lesen. Gelingt es nicht, ist sie der Weg zum Ziel.
  const geoeffnet = _leiste ? true : await leisteOeffnen();
  if (!geoeffnet) {
    melde("Gespeichert. Die Seitenleiste öffnet sich beim nächsten Klick auf "
          + "das Symbol in der Symbolleiste.");
  }
});

start();
