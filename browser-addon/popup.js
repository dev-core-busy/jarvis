/* Popup: die ganze Oberflaeche.
 *
 * Es fetcht NICHTS selbst – jeder Netzaufruf geht ueber den Hintergrund
 * (Begruendung im Kopf von background.js). Das Popup schliesst sich, sobald der
 * Benutzer daneben klickt; ein Aufruf von hier waere damit mitten in einer
 * 13-Sekunden-Auswertung weg.
 */
import {
  einfuegenInJira, einfuegenUeberEditorApi, leseAusJira, lesenUeberEditorApi,
  oeffneKommentarfeld,
} from "./einfuegen.js";

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

/** Wie `zweig`, wirft aber mit KLARTEXT, statt `null` zurueckzugeben.
 *
 * ⚠ GEMELDET 2026-09-02: "in edge wird kein Ticket erkannt". Gemessen an
 * gestellten Umgebungen: existiert `browser` OHNE `tabs` (ein Alias-Objekt, das
 * nur einen Teil der Zweige traegt), dann ist `api.tabs` undefined und
 * `api.tabs.query` wirft "Cannot read properties of undefined". Die Anzeige
 * blieb dabei LEER – nicht einmal "Kein Ticket gefunden" stand da, und aus dem
 * Fenster war nicht zu erkennen, dass ueberhaupt etwas schiefging.
 *
 * Genau dieselbe Falle wie bei `sidePanel` (2026-08-30, drei Runden): `api` ist
 * `browser ?? chrome`, und ein Alias-Objekt eines Herstellers muss nicht
 * vollstaendig sein. Deshalb JEDER Zweig ueber beide Wurzeln – und wenn es ihn
 * wirklich nirgends gibt, eine Meldung, die den Zweig NENNT.
 */
function brauche(name, methode) {
  const z = zweig(name, methode);
  if (z) return z;
  throw new Error("Dieser Browser stellt " + name + "." + methode
                  + " nicht bereit. Die Erweiterung braucht sie, um den "
                  + "offenen Tab zu lesen.");
}

/* STAND DES FENSTER-CODES – muss mit `STAND` in background.js uebereinstimmen.
 * Begruendung dort; kurz: Chrome laedt diese Seite bei jedem Oeffnen frisch,
 * behaelt den Service-Worker aber im Speicher. Ohne diesen Abgleich sieht ein
 * halb aktualisierter Zustand wie ein Programmierfehler aus. */
const STAND = 6;

const $ = (id) => document.getElementById(id);
const el = {
  login: $("bereich-login"), arbeit: $("bereich-arbeit"),
  basis: $("f-basis"), benutzer: $("f-benutzer"), kennwort: $("f-kennwort"),
  totp: $("f-totp"), hinweis: $("f-hinweis"), ergebnisFeld: $("f-ergebnis"),
  ergebnis: $("ergebnis"), ergebnisFuss: $("ergebnis-fuss"),
  meldung: $("meldung"), ticket: $("ticket-anzeige"),
  abmelden: $("btn-abmelden"), reset: $("btn-reset"),
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
// Antwortet im Hintergrund eine aeltere Fassung? (siehe STAND)
let _standAlt = false;
let _standGesehen;       // was der Hintergrund gemeldet hat (fuer die Meldung)
let _windowId = null;
let _tabUrl = "";
// Adresse des Jira-Servers, einmal vom Server geholt (siehe zugriffZeile).
let _jiraBasis = "";
/* WARUM die Ticketnummer fehlt - "" heisst: kein Grund bekannt (die Seite ist
 * einfach kein Ticket). Alles andere ist eine Stoerung, und die gehoert in die
 * Anzeige: sonst heisst "kein Ticket gefunden" zweierlei (gemeldet fuer Edge). */
let _tabFehler = "";
/* Die Herkunft, die die Zugriffszeile NENNT – und die ihr Knopf erfragen muss.
 * Gesetzt von `zugriffZeileAktualisieren`; der Knopf liest sie SYNCHRON
 * (Begruendung dort). */
let _zugriffHerkunft = "";
/* Was bei einem NEUEN Ticket von selbst startet: die KENNUNG einer Vorlage
 * oder "" (aus).
 *
 * ⚠ BIS 2026-09-02 STAND HIER EIN MODUS ("zusammenfassung"/"antwort"). Seit die
 * Automatik Vorlagen anbietet, ist es eine Vorlagen-Kennung – deshalb ein
 * anderer Feldname in der Ablage (`auto_vorlage`) und ein hoeherer `STAND`:
 * ein alter Wert wird nicht umgedeutet, sondern ignoriert, die Automatik ist
 * nach dem Update also AUS, bis jemand eine Vorlage waehlt. Fail-closed – eine
 * Automatik, die nach einem Update etwas anderes tut als bestellt, waere
 * schlimmer als eine, die einmal neu eingestellt werden muss.
 *
 * Der massgebliche Wert liegt in der Ablage (background.js); dies hier ist die
 * Kopie fuer dieses Fenster, damit `autoAktionPruefen` bei ausgeschalteter
 * Automatik gar nicht erst den Hintergrund fragen muss. */
let _autoVorlage = "";

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
 * pauschal JEDER Knopf, ausgenommen ist nur, was `data-ohne-ticket` traegt.
 * Andersherum – eine Liste der zu sperrenden Knoepfe – waere ein kuenftig
 * ergaenzter Knopf ohne Eintrag **bedienbar**, obwohl er ohne Ticket nichts tun
 * kann; so ist er hoechstens einmal zu viel gesperrt. Das ist die harmlosere
 * Halbfehlerstellung.
 *
 * ⚠ GESUCHT WIRD MIT `closest`, NICHT MIT `hasAttribute` (2026-08-31): das
 * Attribut darf auch an einem CONTAINER stehen und gilt dann fuer alles darin.
 * Zwei Gruende, jeder allein hinreichend:
 *   - Die Zeilen-Knoepfe der Vorlagenliste (Stern, Bearbeiten, Loeschen)
 *     entstehen erst beim Zeichnen und koennen im Markup gar kein Attribut
 *     tragen. Sie im JS einzeln zu markieren waere genau die zweite Liste,
 *     gegen die der ganze Entwurf gebaut ist.
 *   - Ein zusammenhaengender Bereich hat EINE Begruendung. Sie einmal an den
 *     Container zu schreiben ist ehrlicher als sie an fuenf Knoepfen zu
 *     wiederholen – und ein sechster Knopf darin ist von selbst richtig.
 *
 * Bedienbar bleiben: Anmelden (sonst kaeme man von einem fremden Tab aus nie
 * hinein), Abmelden (sonst nie hinaus), die Schliessen-Knoepfe der beiden
 * Dialoge (ein Dialog, den man nicht wegbekommt, ist eine Falle), die
 * Zugriffsabfrage der Seitenleiste – und die Vorlagen-Verwaltung samt
 * Zahnrad: sie liest kein Ticket und schreibt keines (gemeldet 2026-08-31).
 */
function knoepfeAktualisieren() {
  // Waehrend eines Laufs entscheidet `sperre` allein – sonst gaebe ein
  // Tab-Wechsel mitten in einer Auswertung die Knoepfe wieder frei.
  if (_laeuft) return;
  const aus = !_key;
  for (const b of document.querySelectorAll("button")) {
    b.disabled = aus && !b.closest("[data-ohne-ticket]");
  }
}

/** Setzt die Ticketanzeige im Kopf – und zieht die Knopf-Sperre nach.
 *
 * Beides gehoert in EINE Funktion: die Anzeige ist die Begruendung fuer die
 * Sperre. Stuenden sie getrennt, waere der naechste Zustand denkbar, in dem
 * Knoepfe grau sind und im Kopf trotzdem eine Ticketnummer steht.
 */
function ticketAnzeigen() {
  el.ticket.textContent = _key
    || (_tabFehler ? "Tab nicht lesbar" : "Kein Ticket gefunden");
  // Der GRUND steht in der Meldung - im 380 px breiten Kopf ist kein Platz
  // dafuer, und er ist zu wichtig, um ihn abzuschneiden.
  if (_tabFehler) melde(_tabFehler);
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
    'Der Text gehört zu einem <b>anderen Ticket</b>. Trotzdem übernehmen?';
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

/** Fragt den aktiven Tab ab – in BEIDER Aufrufform.
 *
 * Chromium (MV3) und Firefox geben ein Promise zurueck. Ein Alias-Objekt
 * koennte aber die aeltere CALLBACK-Form haben; dann ist der Rueckgabewert kein
 * Promise, `await` liefert `undefined` und es gibt STILL kein Ticket.
 *
 * ⚠ DER ZWEITE AUFRUF IST HIER UNBEDENKLICH, WEIL DIE ABFRAGE NUR LIEST. Bei
 * einem schreibenden Aufruf waere ein solcher Rueckfall ein Fehler – er wuerde
 * die Wirkung verdoppeln. Deshalb steht er nur an dieser Stelle.
 */
async function tabsAbfragen() {
  const z = brauche("tabs", "query");
  const frage = { active: true, currentWindow: true };
  /* ⚠ DER ERSTE AUFRUF MUSS IM try STEHEN: eine reine Callback-API wirft
   * SOFORT ("cb is not a function"), wenn man sie ohne Callback ruft – der
   * Rueckgabewert kommt dann gar nicht mehr zum Vergleich. Gemessen. */
  try {
    const r = z.query(frage);
    if (r && typeof r.then === "function") return r;
  } catch (e) { /* dann die Callback-Form, s.u. */ }
  return new Promise((fertig, fehler) => {
    try { z.query(frage, (tabs) => fertig(tabs)); }
    catch (e) { fehler(e); }
  });
}

async function tabErmitteln() {
  let tabs = null;
  _tabFehler = "";
  try {
    tabs = await tabsAbfragen();
  } catch (e) {
    /* ⚠ DER FEHLER WIRD BENANNT, NICHT VERSCHLUCKT. Vorher warf `tabErmitteln`
     * durch und die Anzeige blieb leer: „kein Ticket erkannt" war von „die
     * Adresse ist nicht lesbar" nicht zu unterscheiden, und niemand konnte
     * ableiten, was zu tun ist (gemeldet fuer Edge). */
    _tabFehler = (e && e.message) || String(e);
  }
  const t = tabs && tabs[0];
  _tabId = t ? t.id : null;
  // Das Fenster braucht `sidePanel.open`, die Adresse die Zugriffszeile.
  _windowId = t && (t.windowId !== undefined) ? t.windowId : null;
  _tabUrl = (t && t.url) || "";
  _key = keyAusUrl(t && t.url);
  /* KEIN Tab, KEINE Adresse und KEIN Fehler: dann fehlt das Zugriffsrecht auf
   * diesen Tab. `tabs.query` liefert die Adresse nur mit `activeTab` (Klick auf
   * das Symbol) oder einem Host-Recht – ohne beides kommt ein Tab OHNE `url`
   * zurueck, und das sah wie "kein Jira-Ticket" aus. */
  if (!_tabFehler && !t) {
    // Kein aktiver Tab in der Antwort: auch das ist eine Stoerung, nicht
    // "die Seite ist kein Ticket".
    _tabFehler = "Der aktive Tab war nicht ermittelbar. Öffne das Ticket im "
                 + "Vordergrund und klicke erneut auf das Symbol.";
  }
  if (!_tabFehler && t && !t.url) {
    /* ⚠ ZWEI VERSCHIEDENE WEGE, und der falsche kostet Zeit. Im POPUP erteilt
     * der Klick auf das Symbol `activeTab` – dort ist "klick auf das Symbol"
     * die Loesung. In der LEISTE gilt `activeTab` nicht ueber den Tab hinaus,
     * in dem sie geoeffnet wurde: dort hilft nur das dauerhafte Host-Recht,
     * und dafuer gibt es den Knopf in der Zugriffszeile. Wer dort "klick auf
     * das Symbol" liest, klappt die Leiste zu und wieder auf – und wundert
     * sich. */
    _tabFehler = _leiste
      ? "Die Adresse dieses Tabs ist für die Seitenleiste nicht lesbar – "
        + "deshalb erkennt sie kein Ticket. Erlaube ihr unten dauerhaften "
        + "Zugriff auf den Jira-Server."
      : "Die Adresse dieses Tabs ist für die Erweiterung nicht lesbar. Klicke "
        + "auf das Symbol in der Symbolleiste, während das Ticket im "
        + "Vordergrund ist.";
  }
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
  /* ⚠ LAEUFT IM HINTERGRUND NOCH EINE AELTERE FASSUNG? Dann stimmt hier gar
   * nichts mehr zusammen, und die Symptome sehen aus wie Programmierfehler:
   * der Ansichts-Schalter antwortet „Unbekannte Anfrage", Felder im Zustand
   * fehlen. Der Abgleich sagt es SOFORT und nennt den Weg - statt dass jemand
   * (auch ich) tagelang an der falschen Stelle sucht.
   * `undefined` zaehlt als Abweichung: eine Fassung ohne das Feld ist per
   * Definition aelter als die, die es eingefuehrt hat. */
  _standGesehen = z.stand;
  if (z.stand !== STAND) _standAlt = true;
  // ZUERST klaeren, WAS dieses Fenster ist - davon haengen Breite, Beschriftung
  // des Umschalters und die Tab-Beobachtung ab.
  leisteFeststellen(z.kontext);
  // Der Umschalter gilt unabhaengig von der Anmeldung – wer in der Leiste
  // steht und zurueck will, muss das auch ohne Konto koennen.
  ansichtZeigen(z.ansicht, z.leiste_moeglich);
  zeige(z.angemeldet);
  /* VOR `ticketLageAnwenden` – dort faellt die Entscheidung, ob die Automatik
   * greift, und sie liest `_autoVorlage`. Ein aelterer Hintergrund schickt das
   * Feld nicht mit; `autoZeigen` macht daraus "aus" (fail-closed: eine
   * Automatik, die man nicht sieht, darf nicht laufen). */
  autoZeigen(z.auto_vorlage);
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
    if (el.reset) el.reset.hidden = false;
    /* „[Benutzer] abmelden" – dasselbe Muster wie im Portal
     * (portal.html::pt-logout). Der Knopf traegt nur ein Symbol; wer darauf
     * zeigt, soll sehen, WESSEN Anmeldung er beendet. Ohne bekannten Namen
     * bleibt es beim schlichten „Abmelden" – ein „undefined abmelden" waere
     * schlimmer als kein Name. */
    const titel = abmeldeTitel(z.benutzer);
    el.abmelden.title = titel;
    el.abmelden.setAttribute("aria-label", titel);
    /* OHNE `await`: der Hinweis ist eine Auskunft, kein Arbeitsschritt – er
     * darf `start()` nicht aufhalten (dort haengen gleich danach die
     * Tab-Zuhoerer der Leiste, und die sind eine Sicherheitsschranke). */
    updateHinweis();
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

  /* ⚠ ZULETZT, damit sie GEWINNT. Ein halb aktualisierter Zustand macht alles
   * andere unerklaerlich; diese Auskunft darf nicht von einer Routine-Meldung
   * ueberschrieben werden, die kurz danach gesetzt wird. */
  if (_standAlt) {
    melde("Die Erweiterung ist nur halb aktualisiert: dieses Fenster ist neuer "
          + "als ihr Hintergrund. Öffne chrome://extensions und drücke bei "
          + "dieser Erweiterung auf Neu laden (⟳) – danach funktioniert wieder "
          + "alles. (Fenster " + STAND + ", Hintergrund "
          + (_standGesehen === undefined ? "älter" : _standGesehen) + ".)");
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

  /* ⚠ BEWUSST OHNE `await`. Die Automatik ist der letzte Schritt und darf den
   * Aufrufer nicht aufhalten: `start()` registriert unmittelbar danach die
   * Tab-Zuhoerer der Seitenleiste (`leisteBeobachten`), und die sind eine
   * Sicherheitsschranke. Wuerde hier eine Auswertung abgewartet, liefe die
   * Leiste zehn Sekunden lang OHNE Beobachtung des Tab-Wechsels – genau in der
   * Zeit, in der jemand nebenbei ein anderes Ticket aufmacht.
   * Der Preis ist eine kurze Lücke zwischen Entscheidung und Start; sie ist in
   * `autoAktionPruefen` durch die zweite Prüfung von `_key` abgedeckt. */
  autoAktionPruefen(passt);
}

/** „[Benutzer] abmelden" – oder „Abmelden", wenn der Name unbekannt ist.
 *
 * Dasselbe Muster wie im Portal (portal.html::pt-logout). Der Knopf traegt nur
 * ein Symbol; wer darauf zeigt, soll sehen, WESSEN Anmeldung er beendet.
 *
 * EIGENE FUNKTION, damit sie messbar ist: als Zeile in `start()` liess sich nur
 * die Schreibweise pruefen – und ein Waechter, der auf `z.benutzer` sucht,
 * trifft dort auch `z.benutzer_vorschlag` und bleibt gruen, obwohl der Name
 * gar nicht mehr benutzt wird (genau so beim ersten Lauf passiert).
 */
function abmeldeTitel(wer) {
  const n = String(wer || "").trim();
  // Kein Name: das schlichte Wort. „undefined abmelden" waere schlimmer als
  // kein Name - und ein leerer Vorsatz („ abmelden") sieht wie ein Fehler aus.
  return n ? n + " abmelden" : "Abmelden";
}

/** Sagt es, wenn der Server eine NEUERE Fassung ausliefert.
 *
 * ⚠ DIE ERWEITERUNG AKTUALISIERT SICH NICHT VON SELBST. Sie ist von Hand
 * geladen, nicht aus einem Store – bisher erfuhr niemand von einer neuen
 * Fassung, und ein laengst behobener Fehler blieb wochenlang stehen. Die
 * Stand-Warnung deckt das NICHT ab: sie greift nur bei einem HALB
 * aktualisierten Paket (Fenster neu, Hintergrund alt).
 *
 * Verglichen werden die drei Zahlen der Version, nicht die Zeichenketten:
 * "0.10.0" ist neuer als "0.9.0", als Text waere es kleiner. Fehlt eine
 * Angabe oder ist sie unlesbar, wird NICHTS gezeigt – eine Warnung auf
 * Verdacht verunsichert bei einer aktuellen Installation.
 */
async function updateHinweis() {
  const p = $("update-hinweis");
  if (!p) return;
  const serverVersion = (await healthHolen()).paket_version || "";
  /* ⚠ DER ZWEIG KANN FEHLEN – und genau darum ging es beim Edge-Fall: `api`
   * liefert `undefined`, wenn keine Wurzel ihn hat. Wer hier ungeprueft
   * dereferenziert, wirft ("Cannot read properties of undefined") und reisst
   * `start()` mit – dann steht das ganze Fenster still, wegen einer blossen
   * Auskunft. Ohne Manifest gibt es eben keinen Hinweis. */
  const rt = api.runtime;
  const eigene = (rt && rt.getManifest && rt.getManifest().version) || "";
  const zahlen = (v) => String(v || "").trim().split(".").map((x) => parseInt(x, 10));
  const a = zahlen(eigene), b = zahlen(serverVersion);
  if (!a.length || !b.length || a.some(isNaN) || b.some(isNaN)) {
    p.hidden = true;
    return;
  }
  let neuer = false;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || 0, y = b[i] || 0;
    if (y > x) { neuer = true; break; }
    if (y < x) break;
  }
  if (!neuer) { p.hidden = true; return; }
  /* DER WEG GEHOERT IN DIE MELDUNG. „Es gibt eine neue Fassung" allein laesst
   * den Benutzer suchen: das Paket kommt aus dem Portal, und danach muss die
   * Erweiterung von Hand neu geladen werden – sonst antwortet der alte
   * Service-Worker weiter (siehe STAND). */
  p.textContent = "Neue Fassung " + serverVersion + " verfügbar (installiert: "
    + eigene + "). Hol das Paket im Portal unter „Jira“ neu und lade die "
    + "Erweiterung danach in der Erweiterungsverwaltung neu (⟳).";
  p.hidden = false;
}

/** Traegt die gespeicherte Vorlagen-Kennung ins Pulldown ein.
 *
 * Geprueft wird nur die FORM (Hexziffern, so entstehen die Kennungen in
 * `jira_vorlagen.speichern`) – ob es die Vorlage noch gibt, weiss erst
 * `autoOptionenZeichnen`, wenn die Liste geladen ist. Ein Wert aus einer
 * aelteren Fassung ("zusammenfassung", "antwort") faellt hier heraus und die
 * Automatik ist damit aus; das ist gewollt (siehe `_autoVorlage`).
 *
 * Steht die Kennung noch nicht im Pulldown (die Liste kommt erst), traegt
 * dieser Aufruf sie trotzdem in `_autoVorlage` ein – `autoAktionPruefen` muss
 * ohne die Liste entscheiden koennen.
 */
function autoZeigen(wert) {
  _autoVorlage = /^[0-9a-f]{1,32}$/.test(String(wert || "")) ? String(wert) : "";
  const f = $("f-auto");
  if (!f) return;
  f.value = _autoVorlage;
  // Die Kennung ist (noch) keine Option: dann zeigt das Pulldown "Nichts",
  // ohne dass die Einstellung geloescht wird.
  if (f.value !== _autoVorlage) f.value = "";
}

/** Fuellt das Automatik-Pulldown aus DENSELBEN Vorlagen wie das Startfeld.
 *
 * ⚠ EINE VERSCHWUNDENE VORLAGE RAEUMT DIE EINSTELLUNG AUF. Zeigt die
 * gespeicherte Kennung ins Leere (gelöscht, oder eine gemeinsame Vorlage, die
 * der Administrator zurueckgezogen hat), wird die Automatik ABGESCHALTET und
 * das gesagt – nicht stillschweigend auf etwas anderes umgebogen. Eine
 * Einstellung, die auf nichts zeigt, wuerde sonst beim naechsten Ticket eine
 * Aktion ausloesen, die niemand bestellt hat.
 *
 * Nur bei ERFOLGREICH geladener Liste (`geladen`): ein Netzfehler darf die
 * Einstellung nicht loeschen.
 */
function autoOptionenZeichnen(geladen) {
  const f = $("f-auto");
  if (!f) return;
  const alle = (_vorlagen.global || []).concat(_vorlagen.eigene || []);
  f.innerHTML = "";
  const nichts = document.createElement("option");
  nichts.value = "";
  nichts.textContent = "Nichts – nur auf Knopfdruck";
  f.appendChild(nichts);
  for (const v of alle) {
    const o = document.createElement("option");
    o.value = v.id;
    // textContent: Vorlagennamen sind Freitext aus einem Formular.
    o.textContent = v.name + (v.art === "antwort" ? " (Antwort)" : "");
    f.appendChild(o);
  }
  if (_autoVorlage && !alle.some((v) => v.id === _autoVorlage)) {
    if (!geladen) { f.value = ""; return; }   // Ladefehler: nichts anfassen
    _autoVorlage = "";
    f.value = "";
    frage({ art: "merken", auto_vorlage: "" }).catch(() => {});
    melde("Die Vorlage für die Automatik gibt es nicht mehr – es startet "
          + "nichts mehr von selbst.");
    return;
  }
  f.value = _autoVorlage;
  if (f.value !== _autoVorlage) f.value = "";
}

/** Startet bei einem NEUEN Ticket die eingestellte Aktion von selbst.
 *
 * ⚠ `passt` IST DIE WICHTIGSTE SCHRANKE, und sie ist keine Sparmassnahme:
 * liegt fuer dieses Ticket bereits ein Ergebnis vor, kann es der Benutzer
 * BEARBEITET haben (der Text wird gedrosselt mitgemerkt). Ein automatischer
 * Lauf wuerde das Feld ueberschreiben – also seine Arbeit wegwerfen, ohne dass
 * er etwas gedrueckt hat. „Neu" heisst deshalb: kein Ticket im Tab gewechselt
 * UND nichts Gemerktes dazu.
 *
 * Die zweite Haelfte der Entscheidung – „lief dieses Ticket schon einmal?" –
 * faellt im Hintergrund, weil Pruefen und Vermerken dort EIN Schritt sind
 * (background.js::autoStart).
 *
 * Fehler sind hier bewusst still: es hat niemand etwas gedrueckt, und eine
 * Meldung ueber eine Automatik, die man nicht angestossen hat, waere Laerm.
 * Der Knopf daneben tut es weiterhin und meldet dann im Klartext.
 */
async function autoAktionPruefen(passt) {
  // Alles, was OHNE Rueckfrage entscheidbar ist, zuerst - so kostet der
  // Normalfall (Automatik aus) keine einzige Nachricht an den Hintergrund.
  if (!_autoVorlage || !_key || _laeuft || passt) return;
  // Nicht angemeldet: der Arbeitsbereich ist verborgen. Kann in der Leiste
  // vorkommen, deren Tab-Zuhoerer eine Abmeldung ueberleben.
  if (el.arbeit && el.arbeit.hidden) return;

  const key = _key;
  let a;
  try {
    a = await frage({ art: "auto_start", key });
  } catch (e) {
    return;   // aelterer Hintergrund oder Ablagefehler - siehe Docstring
  }
  if (!a || !a.starten) return;
  /* Nach der Runde noch einmal hinsehen: in der Leiste kann der Tab inzwischen
   * gewechselt haben. `auswerten` liest `_key` selbst - ohne diese Pruefung
   * wuerde fuer das NEUE Ticket ausgewertet, waehrend im Ring das alte
   * vermerkt ist. Das neue Ticket loest ohnehin seine eigene Pruefung aus. */
  if (_key !== key || _laeuft) return;
  /* MIT DER VORLAGE DER AUTOMATIK, nicht mit der im Pulldown gewaehlten – und
   * das Pulldown wird dabei NICHT verstellt: es zeigt die Wahl des Benutzers,
   * und die gehoert ihm.
   *
   * Welcher Modus daraus wird, entscheidet der SERVER aus der Art der Vorlage
   * (`jira_assist.auswerten`). Deshalb muss dieses Fenster die Vorlagenliste
   * hier nicht kennen – sie wird in `start()` ohne `await` geladen und ist
   * womoeglich noch nicht da. */
  await auswerten("zusammenfassung", undefined, a.vorlage);
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
/* ── DAS ERGEBNISFELD IST EIN RICH-TEXT-FELD ───────────────────────────────
 *
 * Es ist KEINE Anzeige, sondern die Bearbeitungsflaeche, deren Inhalt danach im
 * Kommentar beim Kunden landet. Daraus folgt der ganze Entwurf:
 *
 * 1. KANONISCH BLEIBT DER TEXT mit `**…**`. Gespeichert (`ergebnis_merken`),
 *    im Hintergrund abgelegt und vom Server geliefert wird unveraendert dieser
 *    Text – das Speicherformat aendert sich durch den Umbau NICHT. Das Feld ist
 *    nur eine zweite Darstellung davon, so wie der Jira-Kommentar die dritte.
 *
 * 2. GEBAUT WIRD MIT KNOTEN, NIE MIT `innerHTML`. Der Text stammt aus einem
 *    Modell, das den Ticketinhalt verarbeitet hat – und in ein Ticket schreibt
 *    ein Kunde, was er will. Mit `innerHTML` waere ein
 *    `<img src=x onerror=…>` aus dem Ticket im Origin der Erweiterung
 *    ausfuehrbar, und dort liegt das Sitzungstoken. Ueber `createElement` +
 *    `createTextNode` kann Modelltext strukturell kein Element werden; gemessen
 *    (Waechter Abschnitt 15b): aus `<script>` entsteht Text, kein Knoten.
 *
 * 3. EIN PARSER FUER BEIDES. `zuBloecken()` ist die einzige Stelle, die
 *    `**…**` deutet; Anzeige UND Einfuegen bauen aus demselben Ergebnis. Zwei
 *    Parser wuerden beim naechsten Feinschliff auseinanderlaufen, und dann
 *    saehe der Mitarbeiter etwas anderes, als der Kunde bekommt.
 */

/* Die `\S`-Waechter sind der ganze Unterschied zwischen brauchbar und
 * gefaehrlich: ohne sie wuerden `2 * 3 * 4`, `*.txt` und `** allein **` als
 * Auszeichnung gelesen und der Text beim Kunden verstuemmelt. Nicht global –
 * `exec` laeuft in einer Schleife ueber den Rest, ein `lastIndex` waere hier
 * eine Fehlerquelle. */
const _FETT_RE = /\*\*(?=\S)([^\n]+?)(?<=\S)\*\*/;

/** Zerlegt Text in Zeilen aus Laeufen: `[[{t,fett}, …], …]`.
 *
 * Bewusst eine reine Funktion ohne DOM: so laesst sie sich messen, und dasselbe
 * Ergebnis geht per `executeScript({args})` als JSON an die injizierte
 * Einfuege-Funktion – die darf nichts aus ihrem Modul benutzen (sie wird per
 * toString uebertragen) und braucht deshalb KEINEN eigenen Parser.
 */
function zuBloecken(text) {
  const bloecke = [];
  for (const zeile of String(text == null ? "" : text).split("\n")) {
    const laeufe = [];
    let rest = zeile, m;
    while ((m = _FETT_RE.exec(rest))) {
      if (m.index) laeufe.push({ t: rest.slice(0, m.index), fett: false });
      laeufe.push({ t: m[1], fett: true });
      rest = rest.slice(m.index + m[0].length);
    }
    if (rest) laeufe.push({ t: rest, fett: false });
    bloecke.push(laeufe);
  }
  return bloecke;
}

/** Ist ueberhaupt etwas fett? Entscheidet beim Einfuegen ueber den Weg. */
function hatFett(bloecke) {
  return bloecke.some((laeufe) => laeufe.some((l) => l.fett));
}

/** Text ohne die Auszeichnung – fuer Ziele, die kein Fett koennen.
 *
 * Ein Kommentarfeld im Wiki-Quelltextmodus ist eine `textarea`; dort waere ein
 * `**` genau das, was der Kunde am Ende sieht. Lieber ohne Fett als mit
 * Sternchen.
 */
function ohneFett(text) {
  return zuBloecken(text).map((laeufe) => laeufe.map((l) => l.t).join(""))
    .join("\n");
}

/** Baut den Feldinhalt aus Knoten – ein `<div>` je Zeile, `<strong>` je Lauf. */
function textZuFeld(el, text) {
  el.textContent = "";
  const t = String(text == null ? "" : text);
  // WIRKLICH leer lassen: nur dann greift der `:empty`-Platzhalter. Ein
  // `<div><br></div>` saehe leer aus, waere es aber nicht.
  if (!t) return;
  for (const laeufe of zuBloecken(t)) {
    const z = document.createElement("div");
    if (!laeufe.length) z.appendChild(document.createElement("br"));
    for (const l of laeufe) {
      if (l.fett) {
        const stark = document.createElement("strong");
        stark.appendChild(document.createTextNode(l.t));
        z.appendChild(stark);
      } else {
        z.appendChild(document.createTextNode(l.t));
      }
    }
    el.appendChild(z);
  }
}

/* Blockelemente – sie beginnen eine neue Zeile. Dieselbe Liste wie in
 * `einfuegen.js::textAus`, das dieselbe Aufgabe in der Gegenrichtung loest. */
const _BLOCK_RE = /^(?:DIV|P|LI|UL|OL|H[1-6]|BLOCKQUOTE|PRE|SECTION|ARTICLE)$/;

/** Ist dieser Knoten fett?
 *
 * ⚠ NICHT NUR `<strong>`. Strg+B im Feld erzeugt je nach Browser und Pfad
 * `<b>` oder sogar `<span style="font-weight:700">`. Wer nur `<strong>` kennt,
 * wirft vom Benutzer gesetztes Fett STILL weg: er sieht es auf dem Schirm, der
 * Kunde bekommt es nicht, und nach dem naechsten Wiederherstellen ist es auch
 * auf dem Schirm verschwunden.
 */
function istFett(n) {
  if (n.nodeName === "STRONG" || n.nodeName === "B") return true;
  const g = (n.style && n.style.fontWeight) || "";
  return g === "bold" || g === "bolder" || parseInt(g, 10) >= 600;
}

/** Setzt die Sternchen – und zieht den Leerraum davor/dahinter heraus.
 *
 * ⚠ DAS IST DER HAEUFIGSTE BEARBEITUNGSFALL, nicht ein Randfall: wer hinter
 * ein fettes Wort ein Leerzeichen tippt, bekommt `<strong>Loesung: </strong>`.
 * Naiv emittiert waere das `**Loesung: **`, und das erfuellt die `\S`-Bedingung
 * beim naechsten Aufbau NICHT – das Fett waere nach dem naechsten Speichern
 * spurlos weg.
 */
function fettSetzen(t) {
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(t);
  return m && m[2] ? m[1] + "**" + m[2] + "**" + m[3] : t;
}

/** Der Inhalt EINER Zeile als Text. */
function zeileZuText(knoten) {
  let s = "";
  const kinder = knoten.childNodes;
  for (let i = 0; i < kinder.length; i++) {
    const n = kinder[i];
    if (n.nodeType === 3) { s += n.data; continue; }
    if (n.nodeName === "BR") {
      /* Ein `<br>` als LETZTES Kind ist Fuellwerk: Chrome schliesst damit jeden
       * leeren Block ab. Als Umbruch gezaehlt verdoppelte es jede Leerzeile. */
      if (i === kinder.length - 1) continue;
      s += "\n";
      continue;
    }
    if (n.nodeType !== 1) continue;
    s += istFett(n) ? fettSetzen(zeileZuText(n)) : zeileZuText(n);
  }
  return s;
}

/** Der Rueckweg: aus dem bearbeiteten Feld wieder die kanonische Textform.
 *
 * ⚠ WAS HIER STEHT, IST GEMESSEN – nicht angenommen. Und die beiden Browser
 * bauen VERSCHIEDENE Baeume, das ist der Kern dieser Funktion:
 *   Chrome  Enter -> ein weiteres `<div>` als Geschwister
 *   Firefox Enter -> ein `<br>` auf OBERSTER Ebene, gar kein `<div>`
 * Wer nur „div = Zeile" kennt, verliert in Firefox JEDEN vom Benutzer
 * gesetzten Umbruch. Deshalb sammelt die Schleife inline-Inhalt in einem
 * Puffer und schliesst eine Zeile ab, sobald ein `<br>` oder ein Block kommt.
 * Weiter gemessen:
 *   Shift+Enter    -> `<br>` INNERHALB der Zeile
 *   Strg+B         -> `<b>` (siehe istFett)
 *   alles loeschen -> ein nacktes `<br>` ohne jeden `<div>`
 *   Einfuegen      -> `<i>`, `<span style>` und was sonst in der Ablage lag
 * Alles Unbekannte wird FLACHGEKLOPFT (nur sein Text zaehlt). Ein Wurf ist
 * hier ausgeschlossen – der Rueckgabewert geht direkt an einen Kunden.
 */
function feldZuText(el) {
  const zeilen = [];
  let puffer = "", offen = false;
  const abschliessen = () => { zeilen.push(puffer); puffer = ""; offen = false; };
  for (const kind of el.childNodes) {
    if (kind.nodeType === 3) { puffer += kind.data; offen = true; continue; }
    if (kind.nodeName === "BR") { abschliessen(); continue; }
    if (kind.nodeType !== 1) continue;
    if (_BLOCK_RE.test(kind.nodeName)) {
      if (offen) abschliessen();
      for (const z of zeileZuText(kind).split("\n")) zeilen.push(z);
    } else {
      puffer += istFett(kind) ? fettSetzen(zeileZuText(kind)) : zeileZuText(kind);
      offen = true;
    }
  }
  if (offen) abschliessen();
  return zeilen.join("\n")
    // Chrome setzt bei Doppel-Leerzeichen und am Zeilenende ein geschuetztes
    // Leerzeichen. Unsichtbar im Feld, sichtbar beim Kunden.
    .replace(/\u00a0/g, " ")
    /* Zwei benachbarte Fettlaeufe (entstehen beim Loeschen an einer
     * Fettgrenze) ergaeben `**A****B**` – im Feld unsichtbar, im Text an den
     * Server und in der textarea aber sichtbarer Muell. */
    .replace(/\*\*\*\*/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/^\n+/, "").replace(/\n+$/, "");
}

async function felderLeeren(meldungstext) {
  clearTimeout(_merkTimer);
  _letztes = null;
  _fremdesErgebnis = false;
  textZuFeld(el.ergebnisFeld, "");
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
  textZuFeld(el.ergebnisFeld, g.text);
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
  // Reset setzt die ARBEITSFLAECHE zurueck - ohne Anmeldung gibt es keine.
  if (el.reset) el.reset.hidden = !angemeldet;
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

/* ── ZURUECKSETZEN ─────────────────────────────────────────────────────────
 *
 * Es gab „Leeren" schon – aber nur IM Ergebnisbereich, also genau dann nicht,
 * wenn kein Ergebnis angezeigt wird. Wer eine haengengebliebene Anzeige oder
 * einen alten Zusatzwunsch loswerden will, sucht den Knopf dort vergeblich.
 *
 * WAS ES ZURUECKSETZT: den angezeigten und den GEMERKTEN Text (`felderLeeren`
 * raeumt beides ab, auch im Hintergrund), den Zusatzwunsch, die Vorlagenwahl
 * (zurueck auf den persoenlichen Standard) und die geoeffnete Verwaltung.
 * Dazu den Ring der Automatik: das ist der Sinn eines Reset – ein
 * automatischer Lauf darf fuer dieses Ticket wieder moeglich sein.
 *
 * WAS ES NICHT ANFASST, und das ist Absicht: Anmeldung, Serveradresse,
 * Ansicht (Popup/Leiste) und die Automatik-EINSTELLUNG. Fuer die Anmeldung
 * gibt es den Knopf daneben; die uebrigen drei gehoeren zur Einrichtung
 * dieses Browsers und nicht zur Arbeit an einem Ticket. Ein Reset, der
 * ungefragt eine Einstellung verwirft, ist ein Datenverlust mit freundlichem
 * Namen.
 */
$("btn-reset").addEventListener("click", async () => {
  $("vorlagen-box").hidden = true;
  vorlageFormularZu();
  $("vorl-hinweis").textContent = "";
  // Zurueck auf den persoenlichen Standard: `_vorlBeruehrt` ist der Merker,
  // der die eigene Wahl gegen den Standard verteidigt - hier soll sie fallen.
  _vorlBeruehrt = false;
  vorlagenZeichnen();
  /* Der Ring liegt im Hintergrund. Ein Fehlschlag ist hier nicht schlimm –
   * die Anzeige ist trotzdem zurueckgesetzt, und die Meldung sagt es. */
  try {
    await frage({ art: "merken", auto_gelaufen: [] });
  } catch (e) { /* aelterer Hintergrund: dann bleibt der Ring stehen */ }
  await felderLeeren("Zurückgesetzt. Anmeldung, Adresse und Ansicht bleiben.");
});

el.abmelden.addEventListener("click", async () => {
  try { await frage({ art: "abmelden" }); } catch (e) { /* egal */ }
  zeige(false);
  el.ergebnis.hidden = true;
  melde("");
});

// ── Auswerten ───────────────────────────────────────────────────────────────
const ARBEITSTEXT = {
  vorlage: "Werte das Ticket nach der gewählten Vorlage aus … "
           + "(dauert einige Sekunden)",
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

/** Ein Lauf.
 *
 * ``modus`` ist nur der WUNSCH: traegt die uebergebene Vorlage eine Art, gilt
 * sie – entschieden wird am Server, damit es nur eine Quelle gibt
 * (`jira_assist.auswerten`). Angezeigt wird deshalb der Modus, den die ANTWORT
 * nennt, nicht der gesendete.
 *
 * ``vorlagenId`` ist der einzige Weg, eine ANDERE als die im Pulldown gewaehlte
 * Vorlage zu fahren – die Automatik braucht das. Ohne Angabe gilt das Feld.
 */
async function auswerten(modus, entwurf, vorlagenId) {
  if (!_key) {
    melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
    return;
  }
  sperre(true);
  el.ergebnis.hidden = true;
  /* Bei einer gewaehlten Vorlage steht der Modus erst nach der Antwort fest
   * (die Art der Vorlage entscheidet). Eine Wartemeldung, die "Fasse das
   * Ticket zusammen" behauptet, waehrend ein Antwortentwurf entsteht, ist eine
   * falsche Auskunft – dann lieber die neutrale. */
  const wartet = (vorlagenId === undefined ? ($("f-vorlage").value || "")
                                           : (vorlagenId || ""));
  melde((wartet && modus !== "ueberarbeiten")
        ? ARBEITSTEXT.vorlage
        : (ARBEITSTEXT[modus] || ARBEITSTEXT.zusammenfassung), true);
  try {
    const a = await frage({
      art: "auswerten", key: _key, modus,
      lang: (navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en",
      hinweis: (el.hinweis.value || "").trim(),
      /* IMMER die gewählte Vorlage – auch bei „Antwort vorschlagen".
       *
       * Bis 2026-09-01 wurde sie nur beim Zusammenfassen mitgeschickt, weil ihr
       * TEXT dort die Gliederung bestimmt und in einem Antwortvorschlag eine
       * zweite Anweisung wäre. Das gilt weiter, und durchgesetzt wird es am
       * SERVER: `_system_prompt` benutzt den Text ausschließlich im Modus
       * „zusammenfassung".
       *
       * Ihre WERKZEUG-BEREICHE gelten dagegen für alle drei Knöpfe – und gerade
       * bei einer Antwort ist das Nachschlagen in der Hausdokumentation der
       * Punkt. Würde die Kennung hier weggelassen, wäre die Freigabe für zwei
       * von drei Knöpfen wirkungslos, ohne dass es jemand erklären könnte. */
      vorlage: (vorlagenId === undefined ? ($("f-vorlage").value || "")
                                        : (vorlagenId || "")),
      entwurf: entwurf || "",
    });
    const d = a.daten || {};
    _letztes = { key: d.key, modus: d.modus, text: d.text || "",
                 titel: d.titel || "", kommentare: d.kommentare || 0,
                 hinweis: d.hinweis || "",
                 modell: d.modell || "", zeit: Date.now() };
    _fremdesErgebnis = false;      // frisch geholt = passt zum offenen Ticket
    textZuFeld(el.ergebnisFeld, d.text || "");
    el.ergebnis.hidden = false;
    // Was das Ergebnis TRÄGT, gehört sichtbar dazu: aus wie vielen Kommentaren
    // es stammt und mit welchem Modell. Ohne das ist eine dünne Antwort nicht
    // von einem dünnen Ticket zu unterscheiden.
    el.ergebnisFuss.textContent =
      d.key + " · " + (d.kommentare || 0) + " Kommentar(e) ausgewertet · " + (d.modell || "");
    /* NACH DEM MODUS DER ANTWORT, nicht nach dem gesendeten: die Art der
     * Vorlage kann ihn am Server umgebogen haben (Antwort-Vorlage). Sonst
     * stuende unter einem Antwortentwurf kein Wort davon, dass er vor dem
     * Absenden gelesen werden muss. */
    melde(mitAbgleich(FERTIGTEXT[d.modus] || "", d.hinweis));
  } catch (e) {
    melde(e.message);
  } finally {
    sperre(false);
  }
}

/* ── STARTEN: die gewaehlte Vorlage ausfuehren ──────────────────────────────
 *
 * Ein Knopf statt zweier (Vorgabe 2026-09-02). Der gesendete Modus ist nur ein
 * Wunsch – die Art der Vorlage entscheidet am Server. Hier wird sie trotzdem
 * mitgeschickt, soweit bekannt: so stimmt die Wartemeldung, und ein Server
 * einer aelteren Fassung tut wenigstens das Naheliegende.
 */
$("btn-start").addEventListener("click", () => auswerten(vorlagenArt($("f-vorlage").value)));

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
  /* ⚠ AUS EINEM NICHT ERKANNTEN FELD WIRD NUR NACH RUECKFRAGE ueberarbeitet.
   *
   * `unsicher` setzt `leseAusJira`, wenn der Text aus dem Auffangnetz stammt –
   * also aus irgendeinem editierbaren Element, nicht aus einem als
   * Kommentarfeld erkannten (unbekannte Jira-Variante). Gemessen 2026-09-02:
   * bei Jira ist unter anderem die BESCHREIBUNG inline bearbeitbar, und deren
   * Text sah wie ein Entwurf aus. Das Ergebnis geht am Ende an einen KUNDEN –
   * dieselbe Schranke wie beim fremden Ticket. */
  if (r.unsicher && !(await frageJaNein(
        "Der gelesene Text stammt aus einem Feld, das nicht als Kommentarfeld "
        + "erkannt wurde. Er beginnt mit: „"
        + String(r.text || "").slice(0, 60).replace(/\s+/g, " ")
        + "…“ Trotzdem überarbeiten?"))) {
    melde("Abgebrochen. Klicke IN das Kommentarfeld und versuche es erneut.");
    return;
  }
  await auswerten("ueberarbeiten", r.text);
});

/* ── Automatik bei neuem Ticket ────────────────────────────────────────────
 *
 * ⚠ SIE GILT AB DEM NAECHSTEN TICKET, NICHT SOFORT – und das muss dastehen.
 * Wer sie einschaltet, waehrend ein Ticket offen ist, sieht sonst: nichts
 * passiert. Ein sofortiger Lauf waere die andere Moeglichkeit, aber er wuerde
 * ein bereits angezeigtes (womoeglich bearbeitetes) Ergebnis ueberschreiben –
 * genau das, wogegen die `passt`-Schranke in `autoAktionPruefen` gebaut ist.
 * Die ehrliche Ansage ist billiger als beides.
 */
$("f-auto").addEventListener("change", async (ereignis) => {
  const wert = ereignis.target.value;
  try {
    await frage({ art: "merken", auto_vorlage: wert });
  } catch (e) {
    // Zurueckdrehen: ein Pulldown, das einen nicht gespeicherten Wert zeigt,
    // ist schlimmer als eine Fehlermeldung.
    autoZeigen(_autoVorlage);
    melde(e.message);
    return;
  }
  autoZeigen(wert);
  melde(_autoVorlage
    ? "Gespeichert. Beim nächsten Ticket läuft die Vorlage „"
      + vorlagenName(_autoVorlage)
      + "“ von selbst – für das gerade offene nicht mehr."
    : "Gespeichert. Es startet nichts mehr von selbst.");
});

/* Der BEARBEITETE Text wird mitgemerkt – gedrosselt.
 *
 * Wer einen Vorschlag umschreibt und dann in den Jira-Tab wechselt, um das
 * Kommentarfeld zu öffnen, hätte sonst seine Änderungen verloren: das Popup
 * schließt dabei. Bei jedem Tastendruck zu speichern wäre unnötig – eine
 * halbe Sekunde Ruhe genügt.
 */
/* ⚠ EINGEFUEGT WIRD NUR KLARTEXT.
 *
 * In echtem Chrome nachgemessen: ein Einfuegen aus der Zwischenablage traegt
 * `<i>`, `<span style=…>` und beliebiges weiteres Markup in das Feld. Das ist
 * doppelt schaedlich – es sammelt sich Formatierung an, die niemand gewollt
 * hat, und der Rueckweg muesste sie flachklopfen, statt sie gar nicht erst
 * hereinzulassen. Fremdes Markup gehoert hier nicht hin.
 */
/** Setzt Klartext an der Auswahl ein – der gemeinsame Weg von Einfuegen und
 * Fallenlassen.
 *
 * `insertText` zuerst: nur so bleibt die Rueckgaengig-Kette des Browsers
 * erhalten. Der Range-Weg darunter ist der Rueckfall (und das, was in jsdom
 * gemessen werden kann – dort gibt es kein execCommand).
 */
function klartextEinsetzen(txt) {
  try {
    if (document.execCommand && document.execCommand("insertText", false, txt)) return;
  } catch (e) { /* weiter mit dem Range-Weg */ }
  const auswahl = window.getSelection();
  if (!auswahl || !auswahl.rangeCount) return;
  const bereich = auswahl.getRangeAt(0);
  bereich.deleteContents();
  const knoten = document.createTextNode(txt);
  bereich.insertNode(knoten);
  bereich.setStartAfter(knoten);
  bereich.collapse(true);
  auswahl.removeAllRanges();
  auswahl.addRange(bereich);
  /* Ohne dieses Ereignis laeuft die Merk-Drossel nicht an, und das Eingesetzte
   * waere beim naechsten Oeffnen weg – genau das Szenario, fuer das der Timer
   * ueberhaupt gebaut wurde. */
  el.ergebnisFeld.dispatchEvent(new Event("input", { bubbles: true }));
}

/* ⚠ EINGEFUEGT WIRD NUR KLARTEXT.
 *
 * In echtem Chrome nachgemessen: ein Einfuegen aus der Zwischenablage traegt
 * `<i>`, `<span style=…>` und beliebiges weiteres Markup in das Feld. Das ist
 * doppelt schaedlich – es sammelt sich Formatierung an, die niemand gewollt
 * hat, und der Rueckweg muesste sie flachklopfen, statt sie gar nicht erst
 * hereinzulassen. Fremdes Markup gehoert hier nicht hin.
 */
el.ergebnisFeld.addEventListener("paste", (ereignis) => {
  const ablage = ereignis.clipboardData;
  if (!ablage) return;                       // ohne Zugriff lieber gar nichts
  ereignis.preventDefault();
  const txt = (ablage.getData("text/plain") || "").replace(/\r/g, "");
  if (!txt) return;
  klartextEinsetzen(txt);
});

/* Hineingezogener Text ist derselbe Fall wie das Einfuegen – und ohne
 * `dragover`-Behandlung NAVIGIERT Chrome das Fenster zu einer fallengelassenen
 * Adresse weg, samt allem, was im Feld stand. */
el.ergebnisFeld.addEventListener("dragover", (ereignis) => {
  ereignis.preventDefault();
});
el.ergebnisFeld.addEventListener("drop", (ereignis) => {
  const d = ereignis.dataTransfer;
  if (!d) return;
  ereignis.preventDefault();
  const txt = (d.getData("text/plain") || "").replace(/\r/g, "");
  if (!txt) return;
  klartextEinsetzen(txt);
});

let _merkTimer = null;
el.ergebnisFeld.addEventListener("input", () => {
  clearTimeout(_merkTimer);
  _merkTimer = setTimeout(async () => {
    if (!_letztes) return;
    _letztes.text = feldZuText(el.ergebnisFeld);
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
/* Der Katalog der WERKZEUG-BEREICHE, wie der Server ihn liefert:
 * [{id, name, hinweis, freigegeben, werkzeuge}]. Er kommt mit derselben
 * Antwort wie die Vorlagen – ein eigener Abruf waere ein zweiter Roundtrip fuer
 * dieselbe Auskunft. Name und Hinweis stammen vom SERVER, damit Text und
 * Wirkung nicht auseinanderlaufen (dort stehen sie neben der Werkzeugliste). */
let _bereiche = [];
let _vorlBearbeitet = "";      // Kennung der gerade bearbeiteten Vorlage
// Hat der Benutzer in DIESEM Fenster schon selbst gewählt? Dann gewinnt seine
// Wahl gegen den Standard – sonst überschriebe ein Neuzeichnen (nach dem
// Speichern einer Vorlage) die gerade getroffene Auswahl.
let _vorlBeruehrt = false;

/** Die Art der Vorlage zu einer Kennung – "zusammenfassung", wenn unbekannt.
 *
 * Dieselbe fail-safe Richtung wie `jira_vorlagen.art_von` am Server: eine
 * unbekannte Kennung (Liste noch nicht geladen, Vorlage inzwischen geloescht)
 * darf nicht als "antwort" gelten. Der Wert ist hier ohnehin nur ein Wunsch –
 * entschieden wird am Server.
 */
/* ── DAS BEARBEITEN-FORMULAR WANDERT ───────────────────────────────────────
 *
 * Vorgabe 2026-09-02: „Bearbeiten" zeigt die Bearbeitung DIREKT UNTERHALB des
 * gewaehlten Eintrags, nicht am Ende der Liste. Bei mehreren Vorlagen war
 * sonst nicht erkennbar, welche gerade bearbeitet wird – man las ein Formular
 * ohne Bezug.
 *
 * ES IST GENAU EIN CONTAINER, DER VERSCHOBEN WIRD (`#vorl-form`), kein zweites
 * Formular: zwei waeren zwei Wege zum Speichern, die beim naechsten Feld
 * auseinanderlaufen. Dieselbe Bauart wie beim Rollen-Formular in
 * /settings (`.role-card > .role-row + #role-edit`).
 *
 * ⚠ DER HEIMATPLATZ WIRD NUR BEIM ERSTEN VERSCHIEBEN GEMERKT. Wer ihn spaeter
 * neu ausliest, merkt sich die verschobene Position als "Heimat" – und das
 * Formular kommt nie mehr zurueck.
 *
 * ⚠ UND ES MUSS VOR JEDEM NEUAUFBAU DER LISTE HEIMGEHOLT WERDEN: haengt es in
 * einem `<li>`, wuerde `liste.innerHTML = ""` es MITLOESCHEN – danach gaebe es
 * kein Namensfeld, keinen Speichern-Knopf und keinen Fehler, der das erklaert.
 */
let _formHeimat = null;

function formPlatz(zeile) {
  const form = $("vorl-form");
  if (!form) return;
  if (!_formHeimat) {
    _formHeimat = { eltern: form.parentNode, davor: form.nextSibling };
  }
  if (zeile) {
    zeile.appendChild(form);
  } else if (_formHeimat.eltern) {
    _formHeimat.eltern.insertBefore(form, _formHeimat.davor);
  }
}

function vorlagenArt(id) {
  if (!id) return "zusammenfassung";
  const alle = (_vorlagen.global || []).concat(_vorlagen.eigene || []);
  const v = alle.find((x) => x.id === id);
  return (v && v.art === "antwort") ? "antwort" : "zusammenfassung";
}

/** Der Name einer Vorlage zu einer Kennung – oder die Kennung selbst. */
function vorlagenName(id) {
  const alle = (_vorlagen.global || []).concat(_vorlagen.eigene || []);
  const v = alle.find((x) => x.id === id);
  return (v && v.name) || id;
}

/** Beschriftet den Startknopf nach der gewaehlten Vorlage.
 *
 * ⚠ EIN KNOPF, DER ZWEI VERSCHIEDENE DINGE TUN KANN, MUSS SAGEN WELCHES.
 * Das Dreieck bleibt dasselbe (Starten ist Starten), aber Tooltip und
 * Hilfsmittel-Beschriftung nennen das Ergebnis – sonst ist von aussen nicht
 * erkennbar, ob eine Zusammenfassung fuer den Mitarbeiter oder ein Entwurf
 * fuer den KUNDEN entsteht. Und das ist ein Unterschied, der zaehlt.
 */
function startTitelSetzen() {
  const b = $("btn-start");
  if (!b) return;
  const id = $("f-vorlage").value || "";
  /* ⚠ „ANTWORT ERSTELLEN" IN BEIDEN FAELLEN – Vorgabe des Nutzers 2026-09-02.
   * „Antwort" ist hier die Antwort DER ERWEITERUNG auf den Klick, nicht die
   * Kundenantwort: der Knopf tut immer dasselbe (die Vorlage ausfuehren), und
   * WAS herauskommt, sagt die Vorlage daneben – ihr Name steht im Titel. */
  const t = !id ? "Antwort erstellen – Zusammenfassung des Vorgangs"
    : "Antwort erstellen – Vorlage „" + vorlagenName(id) + "“"
      + (vorlagenArt(id) === "antwort" ? " (Antwort an den Melder)"
                                       : " (Zusammenfassung)");
  b.title = t;
  b.setAttribute("aria-label", t);
}

function vorlagenZeichnen() {
  const sel = $("f-vorlage");
  const gewaehlt = sel.value;
  sel.innerHTML = "";
  const ohne = document.createElement("option");
  ohne.value = "";
  /* ⚠ DER EINTRAG NENNT DIE AKTION (Vorgabe 2026-09-02): „Ohne Vorlage“ sagte,
   * was NICHT gewaehlt ist, und brauchte darunter einen Satz, der das Ergebnis
   * erklaert. „Zusammenfassen“ sagt es selbst – der Satz ist deshalb weg.
   * Dahinter steckt weiter der eingebaute Prompt (Wert bleibt leer).
   * NICHT „Standard“: seit es eine markierbare Standard-Vorlage gibt, hiesse
   * dasselbe Wort zwei verschiedene Dinge – der eingebaute Ablauf und die
   * Vorlage mit dem Stern.
   * ⚠ DERSELBE TEXT STEHT IN popup.html – und DIESER hier gewinnt, weil die
   * Liste beim Laden neu aufgebaut wird. Laufen sie auseinander, wechselt die
   * Beschriftung nach dem ersten Laden vor den Augen des Benutzers; ein Test
   * vergleicht beide. */
  ohne.textContent = "Zusammenfassen";
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
  /* ⚠ ZUERST DAS FORMULAR HEIMHOLEN. Haengt es in einer Zeile, wuerde das
   * `innerHTML = ""` gleich darunter es mitloeschen – siehe `formPlatz`.
   * Nach dem Aufbau wird es unter seine Zeile zurueckgesetzt (`_vorlBearbeitet`),
   * damit ein Neuaufbau (Speichern, Stern, Loeschen) die Bearbeitung nicht
   * wegreisst. */
  formPlatz(null);
  liste.innerHTML = "";
  for (const [art, vs] of [["global", _vorlagen.global], ["eigen", _vorlagen.eigene]]) {
    for (const v of vs) {
      // Änderbar ist nur, was einem gehört – oder alles, wenn man Admin ist.
      const darf = (art === "eigen") || _vorlagen.darf_global;
      const li = document.createElement("li");
      li.dataset.vid = v.id;
      /* Die FLEX-Zeile liegt eine Ebene tiefer als das `<li>` – nur so kann das
       * Bearbeiten-Formular darunter stehen statt daneben (popup.css). */
      const zeile = document.createElement("div");
      zeile.className = "vorl-zeile";
      li.appendChild(zeile);
      const name = document.createElement("span");
      name.textContent = v.name + (art === "global" ? " (gemeinsam)" : "");
      zeile.appendChild(name);

      /* WAS DIE VORLAGE TUT, gehoert in die Zeile: eine Antwort-Vorlage
       * erzeugt einen Text fuer einen KUNDEN, eine Zusammenfassung einen fuer
       * den Mitarbeiter. Das ist der wichtigste Unterschied zwischen zwei
       * Zeilen, die sonst gleich aussehen. Die Zusammenfassung ist die Vorgabe
       * und bleibt unbeschriftet – eine Marke an jeder Zeile waere Rauschen. */
      if (v.art === "antwort") {
        const am = document.createElement("span");
        am.className = "vorl-art";
        am.textContent = "Antwort";
        am.title = "Erzeugt einen Antwortentwurf für den Melder";
        zeile.appendChild(am);
      }

      /* WAS DIE VORLAGE DARF, gehoert in die Zeile: eine Vorlage, die
       * nachschlaegt, ist von einer, die nur das Ticket liest, sonst nicht zu
       * unterscheiden. Genannt werden nur WIRKSAME Bereiche – ein Rest aus
       * einer zurueckgenommenen Freigabe wirkt nicht mehr, und eine Marke dafuer
       * behauptete eine Faehigkeit, die es nicht gibt. */
      const wirksam = bereichsNamen(v.bereiche);
      if (wirksam) {
        const bm = document.createElement("span");
        bm.className = "vorl-ber";
        bm.textContent = "🔎 " + wirksam;
        zeile.appendChild(bm);
      }

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
      zeile.appendChild(stern);

      if (darf) {
        const bearb = document.createElement("button");
        bearb.type = "button";
        bearb.className = "leise ico";
        bearb.title = "Bearbeiten";
        bearb.textContent = "✎";
        /* ⚠ UMSCHALTER (Vorgabe 2026-09-02): ein zweiter Klick auf DIESELBE
         * Zeile schliesst das Formular wieder. Ohne das war der Knopf eine
         * Einbahnstrasse – man konnte die Felder nur noch loswerden, indem man
         * die ganze Verwaltung zuklappte. Dieselbe Bauart wie „Pruefen" in
         * /wissen (Vergleich der Kennung + gefuellter Container). */
        bearb.addEventListener("click", () => {
          if (_vorlBearbeitet === v.id && !$("vorl-form").hidden) {
            vorlageFormularZu();
            $("vorl-hinweis").textContent = "";
            return;
          }
          vorlageInsFormular(v, art === "global", li);
        });
        zeile.appendChild(bearb);

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
        zeile.appendChild(weg);
      }
      liste.appendChild(li);
    }
  }
  /* Die Bearbeitung ueberlebt den Neuaufbau: das `<li>` ist ein anderes
   * Element als vorher, deshalb wird es ueber die Kennung wiedergefunden.
   * Ist die Vorlage inzwischen weg, bleibt das Formular am Heimatplatz. */
  if (_vorlBearbeitet && !$("vorl-form").hidden) {
    const li = liste.querySelector('li[data-vid="' + _vorlBearbeitet + '"]');
    if (li) formPlatz(li);
  }
  $("vorl-global-zeile").hidden = !_vorlagen.darf_global;
  // Das Automatik-Pulldown zeigt DIESELBEN Vorlagen – aus einer Quelle
  // gezeichnet, damit die beiden Listen nicht auseinanderlaufen.
  autoOptionenZeichnen(true);
  // Der Startknopf sagt, was er tut; das haengt an der gewaehlten Vorlage und
  // die kann sich hier gerade geaendert haben.
  startTitelSetzen();
  /* ⚠ DIE ZEILEN-KNOEPFE ENTSTEHEN HIER ERST – Stern, Bearbeiten, Loeschen.
   * Ein einmaliger Durchlauf ueber `button` beim Tab-Wechsel erwischt sie
   * nicht: sie existieren zu dem Zeitpunkt noch gar nicht, und beim naechsten
   * Neuzeichnen waeren sie wieder bedienbar. Deshalb wird die Sperre HIER
   * nachgezogen.
   * Seit die Vorlagen-Box `data-ohne-ticket` traegt, laesst dieser Aufruf sie
   * frei – der Aufruf bleibt trotzdem stehen: er ist die Stelle, die die
   * Sperre wieder durchsetzt, falls die Box ihre Ausnahme je verliert. */
  knoepfeAktualisieren();
}

/** Die Namen der WIRKSAMEN Bereiche einer Vorlage als Text – oder "".
 *
 * Wirksam heisst: in der Vorlage gewaehlt UND vom Administrator freigeschaltet.
 * Denselben Schnitt macht der Server beim Lauf (`wirksame_bereiche`) – hier
 * wird er nur ANGEZEIGT. Zwei verschiedene Antworten auf dieselbe Frage waeren
 * schlimmer als keine Anzeige.
 */
function bereichsNamen(ids) {
  const frei = new Map(_bereiche.filter((b) => b.freigegeben).map((b) => [b.id, b.name]));
  return (ids || []).map((id) => frei.get(id)).filter(Boolean).join(", ");
}

/** Die Kaestchen fuer die Bereiche EINER Vorlage.
 *
 * Gezeigt werden nur FREIGESCHALTETE: ein Haken, den der Server abweist, ist
 * eine Zusage, die nicht gilt. Ist nichts freigeschaltet, bleibt der ganze
 * Block versteckt – im 380 Pixel breiten Fenster ist ein leerer Kasten mit
 * Erklaerung nur Ballast, und der Benutzer kann daran ohnehin nichts aendern.
 */
function bereicheZeichnen(gewaehlt) {
  const box = $("vorl-bereiche");
  const zeile = $("vorl-ber-zeile");
  if (!box || !zeile) return;
  const frei = _bereiche.filter((b) => b.freigegeben);
  zeile.hidden = frei.length === 0;
  box.innerHTML = "";
  const an = new Set(gewaehlt || []);
  for (const b of frei) {
    const lab = document.createElement("label");
    // NICHT "vorl-ber-zeile": so heisst der CONTAINER im Markup. Zwei Dinge
    // mit demselben Namen sind beim Debuggen kaum zu unterscheiden.
    lab.className = "vorl-ber-opt";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.dataset.ber = b.id;
    cb.checked = an.has(b.id);
    lab.appendChild(cb);
    const txt = document.createElement("span");
    // textContent: der Hinweis kommt vom Server, aber er wird nie als Markup
    // gebraucht – und diese Datei fasst kein innerHTML mit Fremdtext an.
    const stark = document.createElement("b");
    stark.textContent = b.name;
    txt.appendChild(stark);
    if (b.hinweis) {
      const h = document.createElement("span");
      h.className = "hinweis";
      h.textContent = b.hinweis;
      txt.appendChild(h);
    }
    lab.appendChild(txt);
    box.appendChild(lab);
  }
}

function bereicheGewaehlt() {
  return Array.from(document.querySelectorAll("#vorl-bereiche input[data-ber]"))
    .filter((c) => c.checked)
    .map((c) => c.dataset.ber);
}

/** Fuellt das Bearbeiten-Formular und stellt es an seinen Platz.
 *
 * ``zeile`` ist das ``<li>``, unter dem es stehen soll; ohne Angabe (also bei
 * „Neu" und nach dem Speichern) geht es an seinen Heimatplatz hinter der Liste.
 */
/** Schliesst das Bearbeiten-Formular: Felder leeren, heimholen, verstecken.
 *
 * ⚠ HEIMHOLEN GEHOERT DAZU. Bleibt es in einer Zeile haengen, loescht der
 * naechste Neuaufbau der Liste es mit (`liste.innerHTML = ""`) – dann gibt es
 * kein Namensfeld mehr und keinen Fehler, der das erklaert.
 */
function vorlageFormularZu() {
  _vorlBearbeitet = "";
  $("f-vorl-name").value = "";
  $("f-vorl-text").value = "";
  $("f-vorl-art").value = "zusammenfassung";
  $("f-vorl-global").checked = false;
  bereicheZeichnen([]);
  formPlatz(null);
  $("vorl-form").hidden = true;
}

function vorlageInsFormular(v, global_, zeile) {
  _vorlBearbeitet = v ? v.id : "";
  $("vorl-form").hidden = false;
  $("f-vorl-name").value = (v && v.name) || "";
  $("f-vorl-text").value = (v && v.text) || "";
  // Ohne Angabe die Zusammenfassung – dieselbe Vorgabe wie am Server
  // (`jira_vorlagen.art_von`), damit ein leeres Feld nicht zur Antwort wird.
  $("f-vorl-art").value = (v && v.art === "antwort") ? "antwort" : "zusammenfassung";
  $("f-vorl-global").checked = !!global_;
  bereicheZeichnen(v ? v.bereiche : []);
  formPlatz(zeile || null);
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
    // Fehlt das Feld, antwortet ein aelterer Server: dann gibt es keine
    // Bereiche, der Block bleibt versteckt und alles laeuft wie vorher.
    _bereiche = (a.daten && a.daten.bereiche) || [];
    vorlagenZeichnen();
    // Der Block gehoert zum Formular und muss auch ohne Klick auf "Bearbeiten"
    // stimmen – sonst stuenden beim ersten "Neu" die Kaestchen eines fremden
    // Ladezustands da.
    // Die schon gesetzten Haken bleiben stehen: ein Neuladen (etwa nach dem
    // Stern) darf die gerade getroffene Auswahl nicht verstellen – gleiche
    // Haltung wie bei `_vorlBeruehrt` fuer das Pulldown.
    bereicheZeichnen(bereicheGewaehlt());
  } catch (e) {
    // Ohne Vorlagen bleibt „Zusammenfassen“ – kein Grund, den Rest zu sperren.
    $("vorl-hinweis").textContent = e.message;
    /* ⚠ MIT `false`: bei einem LADEFEHLER darf die Automatik-Einstellung nicht
     * geraeumt werden. Die Liste ist dann leer, weil der Server nicht
     * antwortete – nicht, weil die Vorlage geloescht wurde. Ein Netzfehler
     * darf keine Einstellung loeschen. */
    autoOptionenZeichnen(false);
  }
}

/** Standard setzen oder aufheben. `""` hebt auf.
 *
 * Die Liste wird danach NEU GELADEN statt nur der Stern umgemalt: der Server
 * ist die Wahrheit, und er weist eine Kennung ab, die er nicht kennt. Ein
 * lokal umgemalter Stern hätte sonst einen Standard behauptet, den es nicht
 * gibt – und beim nächsten Öffnen stünde wieder „Zusammenfassen“ da.
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
    if (_vorlBearbeitet === v.id) vorlageFormularZu();
    await vorlagenLaden();
    $("vorl-hinweis").textContent = "Gelöscht.";
  } catch (e) {
    $("vorl-hinweis").textContent = e.message;
  }
}

// Eine eigene Wahl gewinnt gegen den Standard, bis das Fenster wieder zugeht.
// Ohne diesen Merker holte jedes Neuzeichnen (Speichern, Löschen, Stern) den
// Standard zurück und verstellte die gerade getroffene Auswahl.
$("f-vorlage").addEventListener("change", () => {
  _vorlBeruehrt = true;
  startTitelSetzen();
});

$("btn-vorlagen").addEventListener("click", () => {
  const box = $("vorlagen-box");
  box.hidden = !box.hidden;
  if (!box.hidden) vorlagenLaden();
});
$("btn-vorlagen-zu").addEventListener("click", () => { $("vorlagen-box").hidden = true; });
// "Neu" oeffnet das Formular am Heimatplatz - es gehoert zu keiner Zeile.
$("btn-vorl-neu").addEventListener("click", () => vorlageInsFormular(null, false));
$("btn-vorl-abbrechen").addEventListener("click", () => {
  vorlageFormularZu();
  $("vorl-hinweis").textContent = "";
});

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
      wert: { id: _vorlBearbeitet, name, text, global: $("f-vorl-global").checked,
              /* IMMER mitsenden. Ein FEHLENDES Feld heisst am Server
               * "unveraendert" (damit eine aeltere Erweiterung nichts
               * umstellt) – dann liesse sich eine Antwort-Vorlage nie wieder
               * zur Zusammenfassung machen. */
              art: $("f-vorl-art").value,
              /* IMMER mitsenden – auch die leere Liste. Sie heisst "keine
               * Bereiche"; ein FEHLENDES Feld heisst "unveraendert" (damit eine
               * aeltere Erweiterung nichts loescht), und dann liesse sich ein
               * Haken nie wieder abwaehlen. */
              bereiche: bereicheGewaehlt() },
    });
    await vorlagenLaden();
    // Die frisch gespeicherte Vorlage gleich auswählen – sonst muss der
    // Benutzer sie im Pulldown suchen, das er gerade gefüllt hat.
    const neu = a.daten && a.daten.vorlage;
    // Gilt als eigene Wahl – sonst zöge das nächste Neuzeichnen den Standard
    // vor und die gerade gespeicherte Vorlage wäre wieder abgewählt.
    if (neu && neu.id) { $("f-vorlage").value = neu.id; _vorlBeruehrt = true; }
    vorlageFormularZu();
    $("vorl-hinweis").textContent = "Gespeichert.";
  } catch (e) {
    $("vorl-hinweis").textContent = e.message;
  }
});

// ── Einfügen und Kopieren ───────────────────────────────────────────────────
$("btn-einfuegen").addEventListener("click", async () => {
  const text = feldZuText(el.ergebnisFeld);
  if (!text.trim() || _tabId === null) return;
  /* Die GEPARSTE Struktur geht mit – nicht, weil der Text nicht reichte,
   * sondern weil die injizierte Funktion keinen eigenen Parser haben darf: sie
   * wird per toString uebertragen und sieht ihr Modul nicht (einfuegen.js,
   * Dateikopf). Zwei Parser waeren zwei Fassungen, die auseinanderlaufen. */
  const bloecke = zuBloecken(text);
  // Ein Text zu einem anderen Vorgang wird nicht ohne Rückfrage eingefügt –
  // das Ergebnis geht am Ende an einen Kunden.
  if (fremd() && !(await frageJaNein())) return;
  sperre(true);
  try {
    /* ⚠ ZUERST DEN KOMMENTARBEREICH AUFKLAPPEN (gemeldet 2026-09-02).
     *
     * In Jira Server ist er zu; das Feld existiert im DOM, ist aber unsichtbar.
     * Der Text landete darin, und der Klick, mit dem der Benutzer den Bereich
     * oeffnet, baute den Editor NEU auf – die Auswertung war weg.
     *
     * Eigener Aufruf, weil Warten `async` heisst und `einfuegenInJira`
     * synchron bleiben soll (dort haengt die ganze Kaskade). Ein Fehlschlag
     * ist KEIN Abbruch: war der Bereich schon offen oder gibt es keinen
     * Oeffner, versucht das Einfuegen es trotzdem – und seine Rueckleseprobe
     * merkt, wenn nichts ankam. */
    let geoeffnet = null;
    try {
      const auf = await api.scripting.executeScript({
        target: { tabId: _tabId }, func: oeffneKommentarfeld,
      });
      geoeffnet = (auf && auf[0] && auf[0].result) || null;
    } catch (e) {
      // Kein Recht auf diesen Tab o. Ae. - der Aufruf unten meldet es sauber.
    }
    const treffer = await api.scripting.executeScript({
      target: { tabId: _tabId },
      func: einfuegenInJira,
      args: [text, bloecke],
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
          /* BEREINIGT: dieser Weg baut sein HTML aus reinem Text und kann
           * kein Fett tragen. Mit `**` gingen die Sternchen woertlich in den
           * Kommentar – genau das, was der Kunde am Ende liest. */
          args: [ohneFett(text)],
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
      /* ⚠ DER WEG GEHOERT IN DIE MELDUNG. Er wird in `einfuegen.js` muehsam
       * aufgebaut und wurde im Erfolgsfall bisher weggeworfen. Ob beim Kunden
       * Fett ankommt, haengt am Editor der Seite – das laesst sich hier nicht
       * vorhersagen, wohl aber BERICHTEN. Damit ist jede Rueckmeldung aus dem
       * Betrieb ein Beleg statt einer Vermutung. */
      const mitFett = /fett/i.test(String(r.weg || ""));
      /* „übernommen", nicht „eingefügt": der Knopf ERSETZT den bisherigen
       * Inhalt des Kommentarfeldes (einfuegen.js, Dateikopf). Wer eben noch
       * einen Entwurf dort hatte, muss das in der Rückmeldung lesen – sonst
       * hält er die Ersetzung für einen Fehler. */
      melde("Als Kommentar übernommen"
            + (hatFett(bloecke)
               ? (mitFett ? " – mit Fettschrift." : " – ohne Fettschrift (der "
                  + "Editor dieser Seite nimmt keine Formatierung an).")
               : ".")
            /* WAR DER BEREICH ZU, GEHOERT DAS IN DIE MELDUNG: der Benutzer
             * sieht dann einen Editor, den er nicht selbst geoeffnet hat – und
             * er soll wissen, dass er ihn NICHT noch einmal anklicken muss
             * (genau dieser Klick hat den Text vorher geloescht). */
            + (geoeffnet && geoeffnet.geoeffnet
               ? " Der Kommentarbereich wurde dafür aufgeklappt."
               : "")
            + " Der bisherige Inhalt des Kommentarfeldes wurde ersetzt."
            + " Bitte in Jira prüfen und selbst abschicken.");
    } else {
      // DIE DIAGNOSE GEHÖRT IN DIE MELDUNG. Ohne sie ist der nächste Anlauf
      // wieder Raten – und zwar für den Benutzer wie für die Fehlersuche.
      const gesehen = (r.gesehen && r.gesehen.length)
        ? "\nGefunden: " + r.gesehen.join(", ")
        : "";
      /* Auch der Oeffnungsversuch gehoert in die Diagnose: „kein Kommentarfeld
       * gefunden" und „der Bereich liess sich nicht aufklappen" fuehren zum
       * selben Ergebnis, verlangen aber verschiedene Antworten. */
      const auf = (geoeffnet && geoeffnet.grund)
        ? "\nAufklappen: " + geoeffnet.grund : "";
      melde((r.fehler || "Übernehmen fehlgeschlagen.") + gesehen + auf);
    }
  } catch (e) {
    // Häufigster Fall: die Seite verbietet die Injektion (z. B. eine
    // Browser-interne Seite) oder activeTab gilt nicht mehr.
    melde("Übernehmen nicht möglich: " + ((e && e.message) || e) +
          "\nBenutze „Kopieren“ und füge den Text von Hand ein.");
  } finally {
    sperre(false);
  }
});

$("btn-kopieren").addEventListener("click", async () => {
  try {
    /* OHNE die Sternchen: der Knopf ist der Rueckfall fuer den Fall, dass das
     * Kommentarfeld nicht gefunden wurde – von Hand eingefuegt wuerde ein `**`
     * genau das, was der Kunde am Ende liest. */
    await navigator.clipboard.writeText(ohneFett(feldZuText(el.ergebnisFeld)));
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
/* Die Auskunft des Servers, EINMAL geholt.
 *
 * Zwei Dinge haengen daran: die Adresse des Jira-Servers (fuer die
 * Berechtigungsabfrage der Leiste) und die Version des Pakets, das dieser
 * Server ausliefert (fuer den Update-Hinweis). EIN Abruf fuer beides – zwei
 * waeren zwei Roundtrips fuer dieselbe Antwort, und der Aufruf braucht ohnehin
 * eine Anmeldung. Ein neuer Nachrichtenfall ist dafuer NICHT noetig, also
 * bleibt `STAND` unberuehrt. */
let _health = null;

async function healthHolen() {
  if (_health) return _health;
  try {
    const a = await frage({ art: "health" });
    _health = a.daten || {};
  } catch (e) {
    // Fehlschlag ist kein Fehler: dann gibt es keinen Update-Hinweis und die
    // Zugriffszeile faellt auf den Weg ueber die Tab-Adresse zurueck.
    _health = {};
  }
  return _health;
}

async function jiraBasisHolen() {
  if (_jiraBasis) return _jiraBasis;
  _jiraBasis = String((await healthHolen()).jira_basis || "").replace(/\/+$/, "");
  return _jiraBasis;
}

async function zugriffZeileAktualisieren() {
  const p = $("leiste-zugriff");
  if (!p) return;
  /* ⚠ SIE HING AN `_leiste` – UND DAS WAR IM EDGE-FALL EINE SACKGASSE.
   *
   * Die Begruendung war: "das Popup kommt mit `activeTab` aus, dort ist die
   * Zeile immer aus". Richtig ist sie nur, SOLANGE `activeTab` wirkt. Ist die
   * Tab-Adresse nicht lesbar (gemeldet fuer Edge 2026-09-02: "Tab nicht
   * lesbar"), hilft ausschliesslich das dauerhafte Host-Recht – und dann muss
   * der Weg dorthin sichtbar sein, ganz gleich ob Fenster oder Leiste. Wird
   * die Leiste von einem Browser nicht als solche gemeldet, waere die Zeile
   * sonst genau dort verborgen, wo sie gebraucht wird.
   *
   * Umgekehrt kostet das nichts: ist die Adresse lesbar (Normalfall im Popup),
   * bleibt die Zeile weiter aus. */
  const blind = !_tabUrl;
  if (!_leiste && !blind) { p.hidden = true; return; }

  /* WELCHE HERKUNFT WIRD ERFRAGT? Steht in diesem Tab ein erkanntes Ticket,
   * ist seine Herkunft der richtige und sicherste Ort. Sonst die Adresse des
   * Jira-Servers laut Jarvis – NIE die eines beliebigen fremden Tabs: sonst
   * bekaeme jemand, der die Leiste im Intranet oeffnet, eine
   * Berechtigungsabfrage fuer das Intranet, die ihm gar nichts nuetzt. */
  const herkunft = (_key && tabHerkunft()) || herkunftAus(await jiraBasisHolen());
  /* ⚠ GEMERKT FUER DEN KNOPF, und das ist keine Bequemlichkeit.
   *
   * `permissions.request` verlangt eine BENUTZERGESTE, und die ist nach dem
   * ersten `await` verbraucht (im Projekt bei `sidePanel.open` schon einmal
   * bezahlt). Der Knopf darf die Herkunft also nicht selbst asynchron holen –
   * er muss sie synchron vorliegen haben. Hier ist der Ort, an dem sie ohnehin
   * ermittelt wird. */
  _zugriffHerkunft = herkunft;
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
  /* ⚠ DREI TEXTE, WEIL ES DREI LAGEN SIND – und der falsche Text schickt den
   * Benutzer in die Irre. „Die Seitenleiste kann …" in einem POPUP zu lesen
   * (Edge-Fall, in dem die Adresse auch dort nicht lesbar ist) laesst ihn nach
   * einer Leiste suchen, die er nicht offen hat. */
  $("leiste-zugriff-text").textContent = !blind
    ? "Damit die Seitenleiste beim Tab-Wechsel mitkommt und „Überarbeiten“ "
      + "und „Einfügen“ weiter funktionieren, braucht sie dauerhaften Zugriff "
      + "auf " + herkunft + ". "
    : (_leiste
        ? "Die Seitenleiste kann die Adresse des offenen Tabs nicht lesen und "
          + "erkennt deshalb kein Ticket. Erlaube ihr dauerhaften Zugriff auf "
          + herkunft + " – das kurzfristige Recht aus dem Klick auf das Symbol "
          + "gilt nur für den Tab, aus dem sie geöffnet wurde. "
        : "Die Erweiterung kann die Adresse des offenen Tabs nicht lesen und "
          + "erkennt deshalb kein Ticket. Erlaube ihr dauerhaften Zugriff auf "
          + herkunft + " – dann ist sie davon unabhängig. ");
  p.hidden = false;
}

$("btn-leiste-zugriff").addEventListener("click", () => {
  /* ⚠ HIER STAND `tabHerkunft()` – UND DAS WAR DER GEMELDETE FEHLER
   * ("Klick auf 'Zugriff erlauben' ist ohne Funktion", 2026-09-02).
   *
   * `tabHerkunft()` liest `_tabUrl`. In genau der Lage, in der dieser Knopf
   * ueberhaupt erscheint, ist die Tab-Adresse aber NICHT LESBAR – also leer.
   * Damit lief die erste Zeile in `if (!herkunft) return;` und der Knopf tat
   * buchstaeblich nichts: kein Dialog, keine Meldung. Die Zeile daneben nannte
   * dabei `https://servicedesk.nexus-ag.de` – den Ort aus `jiraBasisHolen()`,
   * den der Knopf gar nicht kannte. Die Sackgasse, eine Ebene weiter.
   *
   * Jetzt nimmt er GENAU DEN ORT, DEN DIE ZEILE NENNT (`_zugriffHerkunft`) –
   * eine Quelle, keine zwei.
   *
   * ⚠ UND KEIN `await` VOR `permissions.request`: die Benutzergeste ist nach
   * dem ersten `await` verbraucht, der Browser lehnt die Abfrage dann ab –
   * wieder ein Knopf, der sichtbar nichts tut. Deshalb ist der Handler NICHT
   * async und die Herkunft liegt schon vor. */
  const herkunft = _zugriffHerkunft;
  if (!herkunft) {
    // Kein stilles Nichts: sagen, warum es nicht geht.
    /* `{marke}` statt „Jarvis": im Fliesstext steht immer der Platzhalter,
     * `melde()` setzt die Hausmarke ein (Projektregel - der Waechter hat den
     * fest verdrahteten Namen hier sofort gemeldet). */
    melde("Es ist keine Jira-Adresse bekannt, für die der Zugriff erfragt "
          + "werden könnte. Trage sie in {marke} unter Einstellungen → Jira "
          + "ein (als https-Adresse).");
    return;
  }
  let p;
  try {
    p = api.permissions.request({ origins: [herkunft + "/*"] });
  } catch (e) {
    melde("Die Berechtigungsabfrage ließ sich nicht öffnen: "
          + ((e && e.message) || e)
          + "\nÖffne die Erweiterung als Fenster (Schalter unten) und "
          + "versuche es dort.");
    return;
  }
  /* Erst NACH dem Aufruf ist `await` unschaedlich - die Geste hat gewirkt.
   * Manche Umgebungen geben kein Promise, sondern erwarten einen Callback;
   * dann wartet niemand, und das Ergebnis kommt ueber `tabErmitteln` unten
   * ohnehin an. */
  Promise.resolve(p).then(async (ok) => {
    melde(ok
      ? "Zugriff auf " + herkunft + " erteilt."
      : "Ohne das Zugriffsrecht bleiben „Überarbeiten“ und „Einfügen“ auf den "
        + "Tab beschränkt, aus dem die Leiste geöffnet wurde.");
    /* Neu ERMITTELN, nicht nur neu zeichnen: mit dem Recht ist die Adresse des
     * offenen Tabs jetzt lesbar - und damit womoeglich zum ersten Mal eine
     * Ticketnummer. Ohne das stuende weiter "Kein Ticket gefunden" da, obwohl
     * gerade alles dafuer erledigt wurde. */
    await tabErmitteln();
    await ticketLageAnwenden(_letztes);
  }).catch((e) => {
    melde("Die Berechtigungsabfrage schlug fehl: " + ((e && e.message) || e));
  });
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

  /* ⚠ DER SCHALTER WIRD NICHT MEHR GESPERRT – auch nicht bei `moeglich ===
   * false`. Die Faehigkeitspruefung war eine VERMUTUNG, und sie lag falsch:
   * sie fragte `api.sidePanel`, also `browser.sidePanel`, das es in Chrome
   * nicht gibt – und meldete „dieser Browser stellt keine Seitenleiste bereit"
   * auf einem Browser, der sie nachweislich bereitstellt. Damit blockierte sie
   * eine funktionierende Funktion.
   * Die Fehlerlagen sind nicht gleich schwer: ein faelschlich gesperrter
   * Schalter macht das Feature unerreichbar, ein faelschlich freigegebener
   * kostet einen Klick, der nichts tut – und der sagt es dann auch
   * (`leisteOeffnen` meldet den Fehlschlag).
   * `moeglich` bleibt als AUSKUNFT erhalten (Hinweistext), nicht als Schranke. */
  kasten.disabled = false;
  zeile.classList.remove("aus");
  if (!h) return;
  h.textContent = _leiste
    ? "Die Breite ziehst du an der Kante der Leiste."
    : (moeglich
      ? "Öffnet sich beim nächsten Klick auf das Symbol in der Symbolleiste."
      : "Öffnet sich beim nächsten Klick auf das Symbol. Sollte nichts "
        + "passieren, kennt dieser Browser keine Seitenleiste für "
        + "Erweiterungen (nötig: Chrome/Edge ab 114, Firefox ab 115).");
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
    const ff = zweig("sidebarAction", "open");
    if (ff) {
      await ff.open();
      return true;
    }
    const cp = zweig("sidePanel", "open");
    if (cp && _windowId !== null) {
      await cp.open({ windowId: _windowId });
      return true;
    }
  } catch (e) { /* Fehlschlag ist kein Fehler – siehe oben. */ }
  return false;
}

$("f-ansicht").addEventListener("change", async (ereignis) => {
  const wert = ereignis.target.checked ? "leiste" : "popup";

  /* ⚠ ERST SPEICHERN – UND ZWAR ABGEWARTET –, DANN OEFFNEN, DANN SCHLIESSEN.
   *
   * ⚠ HIER STAND EINE FALSCHE BEGRUENDUNG, und sie bleibt als Warnung stehen:
   * „Chrome zerstoert das Popup, wenn die Leiste aufgeht" – damit hatte ich
   * die Meldung „ich kann die Seitenleiste nur ueber die plugin Steuerung
   * oeffnen" erklaert. **Beides war falsch.** Die echte Ursache jener Meldung
   * war `api.sidePanel` (= `browser.sidePanel`, das es in Chrome nicht gibt),
   * und das Popup schliesst sich NICHT von selbst – im Betrieb gemessen:
   * „nach dem Aktivieren der Seitenleiste bleibt das popup noch sichtbar".
   *
   * Die Reihenfolge stimmt trotzdem, nur aus einem anderen Grund: dieses
   * Fenster schliesst sich gleich SELBST, also muss die Einstellung vorher
   * sicher gespeichert sein. Eine nicht gespeicherte Einstellung macht den
   * Schalter kaputt; eine verlorene Benutzergeste kostet einen Klick, und die
   * Meldung sagt dann, welchen. */
  let a;
  try {
    a = await frage({ art: "ansicht", wert });
  } catch (e) {
    // Zuruecksetzen, sonst behauptet das Haekchen einen Zustand, den es nicht
    // gibt.
    ereignis.target.checked = (wert !== "leiste");
    // Kennt der Hintergrund die Anfrage nicht, ist er aelter als dieses
    // Fenster - dann ist die Fehlermeldung des Hintergrunds zwar richtig, der
    // Weg steht aber hier (siehe STAND).
    melde(_standAlt
      ? "Der Hintergrund der Erweiterung ist älter als dieses Fenster. Öffne "
        + "chrome://extensions und drücke bei dieser Erweiterung auf Neu "
        + "laden (⟳)."
      : e.message);
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
  const geoeffnet = _leiste ? true : await leisteOeffnen();
  if (!geoeffnet) {
    melde("Gespeichert. Die Seitenleiste öffnet sich beim nächsten Klick auf "
          + "das Symbol in der Symbolleiste.");
    return;
  }

  /* ⚠ DAS POPUP SCHLIESST SICH NICHT VON SELBST – gemeldet 2026-08-30:
   * „nach dem Aktivieren der Seitenleiste bleibt das popup noch sichtbar".
   * Ich hatte bis hierher das Gegenteil angenommen und sogar die Reihenfolge
   * des Speicherns damit begruendet („Chrome zerstoert das Popup, sobald die
   * Leiste aufgeht"). Gemessen im Betrieb: es bleibt stehen. Zwei Fenster mit
   * derselben Oberflaeche nebeneinander sind schlimmer als eines – schon weil
   * der gemerkte Text dann an zwei Stellen steht und nur eine davon dem Tab
   * folgt.
   *
   * ⚠ NUR AUS DEM POPUP HERAUS. `window.close()` in der Leiste wuerde genau
   * die Leiste schliessen, die der Benutzer gerade eingeschaltet hat. Deshalb
   * die `_leiste`-Schranke – und `window.close()` steht sonst NIRGENDS in
   * dieser Datei (ein Test haelt das fest). */
  if (!_leiste) window.close();
});

start();
