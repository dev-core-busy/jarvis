/* Popup: die ganze Oberflaeche.
 *
 * Es fetcht NICHTS selbst – jeder Netzaufruf geht ueber den Hintergrund
 * (Begruendung im Kopf von background.js). Das Popup schliesst sich, sobald der
 * Benutzer daneben klickt; ein Aufruf von hier waere damit mitten in einer
 * 13-Sekunden-Auswertung weg.
 */
import { einfuegenInJira } from "./einfuegen.js";

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

// ── Meldungen ───────────────────────────────────────────────────────────────
function melde(text, arbeitet = false) {
  if (!text) { el.meldung.hidden = true; return; }
  // Meldungen tragen {marke} – auch die aus dem Hintergrund (der kennt das
  // DOM nicht und kann selbst nicht ersetzen).
  el.meldung.textContent = String(text).split("{marke}").join(_marke);
  el.meldung.classList.toggle("arbeitet", !!arbeitet);
  el.meldung.hidden = false;
}

function sperre(an) {
  for (const b of document.querySelectorAll("button")) b.disabled = an;
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
// Der Rueckfall, solange keine Marke bekannt ist.
let _marke = "Jarvis";

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
    if (farben.accent) {
        document.documentElement.style.setProperty("--akzent", farben.accent);
    }
    if (farben.accent_hover) {
        document.documentElement.style.setProperty("--akzent-hover", farben.accent_hover);
    }
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
    if (!_key) {
      // Kein Fehler, sondern eine Auskunft: die Erweiterung ist bereit, dieser
      // Tab ist nur kein Ticket.
      melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
    }
  }
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
async function auswerten(modus) {
  if (!_key) {
    melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
    return;
  }
  sperre(true);
  el.ergebnis.hidden = true;
  melde(modus === "antwort"
    ? "Formuliere einen Antwortvorschlag … (dauert einige Sekunden)"
    : "Fasse das Ticket zusammen … (dauert einige Sekunden)", true);
  try {
    const a = await frage({
      art: "auswerten", key: _key, modus,
      lang: (navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en",
      hinweis: (el.hinweis.value || "").trim(),
    });
    const d = a.daten || {};
    el.ergebnisFeld.value = d.text || "";
    el.ergebnis.hidden = false;
    // Was das Ergebnis TRÄGT, gehört sichtbar dazu: aus wie vielen Kommentaren
    // es stammt und mit welchem Modell. Ohne das ist eine dünne Antwort nicht
    // von einem dünnen Ticket zu unterscheiden.
    el.ergebnisFuss.textContent =
      d.key + " · " + (d.kommentare || 0) + " Kommentar(e) ausgewertet · " + (d.modell || "");
    melde(modus === "antwort"
      ? "Vorschlag – bitte vor dem Absenden lesen und anpassen."
      : "");
  } catch (e) {
    melde(e.message);
  } finally {
    sperre(false);
  }
}

$("btn-zusammenfassung").addEventListener("click", () => auswerten("zusammenfassung"));
$("btn-antwort").addEventListener("click", () => auswerten("antwort"));

// ── Einfügen und Kopieren ───────────────────────────────────────────────────
$("btn-einfuegen").addEventListener("click", async () => {
  const text = el.ergebnisFeld.value || "";
  if (!text.trim() || _tabId === null) return;
  sperre(true);
  try {
    const treffer = await api.scripting.executeScript({
      target: { tabId: _tabId },
      func: einfuegenInJira,
      args: [text],
    });
    const r = (treffer && treffer[0] && treffer[0].result) || {};
    if (r.ok) {
      melde("Eingefügt. Bitte in Jira prüfen und selbst abschicken.");
    } else {
      melde(r.fehler || "Einfügen fehlgeschlagen.");
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

start();
