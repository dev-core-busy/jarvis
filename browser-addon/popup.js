/* Popup: NUR Anmeldung und Einrichtung.
 *
 * Gearbeitet wird im Panel (`panel.js`), das der Klick auf das Symbol in die
 * Jira-Seite einsetzt. Der Grund steht im Kopf von panel.js: ein Popup
 * schliesst, sobald der Benutzer daneben klickt – also genau dann, wenn er in
 * den Jira-Tab wechselt, um das Kommentarfeld zu oeffnen ("Fenster und Ergebnis
 * verschwindet, wenn z. B. der Tab gewechselt wird").
 *
 * WARUM DIE ANMELDUNG TROTZDEM HIER BLEIBT: hier tippt jemand sein Kennwort.
 * Ein Anmeldeformular, das die Erweiterung in eine FREMDE Seite einsetzt, sieht
 * aus wie ein Formular dieser Seite – das ist genau die Form, vor der man
 * Benutzer warnt. Eine Extension-Seite hat eine eigene, erkennbare Herkunft.
 *
 * Es fetcht NICHTS selbst – jeder Netzaufruf geht ueber den Hintergrund
 * (Begruendung im Kopf von background.js).
 *
 * Welches der beiden Fenster ein Klick oeffnet, entscheidet der Hintergrund
 * ueber `action.setPopup()`: angemeldet = Panel, sonst dieses Fenster.
 */

const api = (typeof browser !== "undefined") ? browser : chrome;

const $ = (id) => document.getElementById(id);
const el = {
  login: $("bereich-login"), bereit: $("bereich-bereit"),
  basis: $("f-basis"), benutzer: $("f-benutzer"), kennwort: $("f-kennwort"),
  totp: $("f-totp"), meldung: $("meldung"), abmelden: $("btn-abmelden"),
};

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

// ── Start ───────────────────────────────────────────────────────────────────
function zeige(angemeldet) {
  el.login.hidden = !!angemeldet;
  el.bereit.hidden = !angemeldet;
  el.abmelden.hidden = !angemeldet;
}

async function start() {
  // ZUERST die Platzhalter belegen – sonst steht "{marke}" sichtbar da,
  // solange (oder falls) kein Branding geholt werden kann.
  markeAnwenden();
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
  /* Angemeldet und trotzdem hier? Dann konnte der Hintergrund das Fenster nicht
   * umschalten (alte Browserfassung). Kein Fehler – der Hinweis sagt, wo
   * gearbeitet wird, und Abmelden bleibt erreichbar. */
  zeige(z.angemeldet);
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
  } catch (e) {
    melde(e.message);
  } finally {
    sperre(false);
  }
});

el.abmelden.addEventListener("click", async () => {
  try { await frage({ art: "abmelden" }); } catch (e) { /* egal */ }
  zeige(false);
  melde("");
});

start();
