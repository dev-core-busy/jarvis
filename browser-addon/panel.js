/* Das Arbeitsfenster – es sitzt IN der Jira-Seite, nicht im Browser-Popup.
 *
 * WARUM: ein Action-Popup schliesst, sobald der Benutzer daneben klickt – also
 * genau dann, wenn er in den Jira-Tab wechselt, um das Kommentarfeld zu
 * oeffnen. Gemeldet als "Fenster und Ergebnis verschwindet, wenn z. B. der Tab
 * gewechselt wird". Das Ergebnis wird zwar in `storage.local` gemerkt, aber das
 * FENSTER war trotzdem weg. Ein Panel in der Seite bleibt stehen.
 *
 * ZWEITER GEWINN, und der ist der groessere: das Panel SIEHT das Kommentarfeld.
 * Es merkt sich, in welchem Feld der Benutzer zuletzt war, und uebergibt es an
 * `einfuegenInJira` – aus einem Popup heraus war das nicht moeglich, dort war
 * `document.activeElement` bereits verloren.
 *
 * ⚠ DREI RANDBEDINGUNGEN, DIE HIER NICHT VERHANDELBAR SIND:
 *
 * 1. KEIN `fetch`. Unter Manifest V3 unterliegt dieser Code der CORS-Regel der
 *    Jira-Seite; `host_permissions` wirken hier NICHT. Der Jarvis-Server
 *    beantwortet einen Preflight von `chrome-extension://…` mit 400. Alles
 *    Netz laeuft ueber `runtime.sendMessage` in den Hintergrund.
 * 2. DAS MARKUP DARF DIE SEITE NICHT STOEREN. Deshalb Shadow DOM: die Seite
 *    sieht genau EIN Element (den Wirt), unsere Klassennamen koennen mit
 *    nichts kollidieren, und Jiras CSS erreicht unsere Knoepfe nicht.
 * 3. DER TICKETBEZUG MUSS SICHTBAR BLEIBEN – und zwar staerker als im Popup.
 *    Ein Panel ueberlebt die Navigation innerhalb der Anwendung: der Benutzer
 *    kann laengst bei Ticket B stehen, waehrend der Text zu Ticket A gehoert.
 *    Deshalb wird die Adresse UEBERWACHT (`URL_TAKT`), und die Warnung ist eine
 *    stehende Zeile, keine Meldung, die die naechste Aktion ueberschreibt.
 *
 * Was das Panel NICHT loest: ein echter Seitenwechsel (Neuladen, Jira
 * Server/DC laedt `/browse/…` oft voll neu) raeumt es ab. Das Ergebnis liegt
 * dann weiter in `storage.local` und ist nach einem Klick auf das Symbol
 * wieder da – genau dafuer gibt es das Gedaechtnis.
 */
(function () {
  "use strict";

  const api = (typeof browser !== "undefined") ? browser : chrome;
  const WIRT_ID = "jv-assist-panel";
  // Wie oft die Adresse geprueft wird. `popstate` genuegt NICHT: eine
  // Einzelseiten-Anwendung wechselt das Ticket per `pushState`, und das feuert
  // kein Ereignis. Eine Sekunde ist unauffaellig und schnell genug – die
  // Warnung muss stehen, bevor jemand auf "Einfuegen" drueckt.
  const URL_TAKT = 1000;

  /* Zweiter Klick auf das Symbol blendet das Panel wieder aus.
   * Das Ergebnis geht dabei NICHT verloren (es liegt im Hintergrund), und der
   * Benutzer braucht einen Weg, die Jira-Oberflaeche wieder ganz zu sehen. */
  const alt = document.getElementById(WIRT_ID);
  if (alt) {
    if (typeof alt.__jvAufraeumen === "function") alt.__jvAufraeumen();
    alt.remove();
    return;
  }

  // ── Oberflaeche ───────────────────────────────────────────────────────────
  /* Die Gestaltung steht als Zeichenkette hier drin und nicht in einer
   * CSS-Datei: eine Datei muesste geholt werden (`fetch` – siehe oben) oder per
   * `insertCSS` in die SEITE gelegt werden, und dort erreicht sie den Shadow
   * DOM gar nicht, verschmutzt aber Jiras Stilraum.
   *
   * Farben folgen dem Systemthema (`Canvas`/`CanvasText`) wie im Popup. Der
   * Akzent ist der neutrale Jarvis-Ton; ist am Server ein Branding hinterlegt,
   * ueberschreibt `setzeBranding()` die Variable AM WIRT – eine Custom Property
   * wird auf dem Element berechnet, auf dem sie deklariert ist. */
  const STIL = `
  :host {
    /* "all: initial" schneidet Jiras Vererbung ab (Schriftgroesse, Farbe,
       line-height). Es setzt auch "position" zurueck – die eigenen Angaben
       muessen deshalb DANACH stehen. Custom Properties bleiben unberuehrt. */
    all: initial;
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    width: 380px;
    max-width: 100vw;
    /* Ueber Jiras eigenen Dialogen – darunter waere das Panel je nach Ansicht
       unerreichbar. */
    z-index: 2147483647;
    color-scheme: light dark;
    --grund: Canvas;
    --schrift: CanvasText;
    --rand: color-mix(in srgb, CanvasText 22%, transparent);
    --gedaempft: color-mix(in srgb, CanvasText 62%, transparent);
    --akzent: #9b59b6;
    --akzent-hover: #8e44ad;
    --akzent-schrift: #fff;
    --warn: color-mix(in srgb, var(--akzent) 12%, Canvas);
  }
  *, *::before, *::after { box-sizing: border-box; }

  /* ⚠ EINE AUTOREN-REGEL SCHLAEGT DAS "hidden"-ATTRIBUT. ".feld { display: block }"
     ueberstimmt das "display: none" des Browsers – gemessen im echten Chrome: die
     Zeile "Fuer alle Benutzer (Administrator)" stand trotz "hidden" da, obwohl
     der Benutzer kein Administrator ist. Dieselbe Falle wie ".sp-row[hidden]" im
     Hauptprojekt (Register). Die Regel gilt fuer ALLES, nicht nur fuer den einen
     Fall, damit der naechste versteckte Kasten nicht wieder auffaellt. */
  [hidden] { display: none !important; }

  .rahmen {
    display: flex;
    flex-direction: column;
    height: 100%;
    /* DECKEND. Darunter liegt die Jira-Seite mit Text – halbtransparent waere
       beides unlesbar (Projektregel). */
    background: var(--grund);
    color: var(--schrift);
    font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
    border-left: 1px solid var(--rand);
    box-shadow: -2px 0 12px rgba(0, 0, 0, .18);
  }

  .kopf {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 10px;
    border-bottom: 1px solid var(--rand);
    flex: 0 0 auto;
  }
  /* Die Marke darf schrumpfen, die Knoepfe nicht: sonst schiebt eine lange
     Ticketnummer den Schliessen-Knopf aus dem Panel. */
  .marke { font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .kopf > button { flex: 0 0 auto; }
  .logo { height: 20px; max-width: 110px; object-fit: contain; flex-shrink: 0; }
  .ticket {
    margin-left: auto;
    flex: 0 1 auto;
    overflow: hidden;
    text-overflow: ellipsis;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    color: var(--gedaempft);
  }

  /* "min-height: 0" ist Pflicht, nicht Kosmetik: ohne das schrumpft ein
     Flex-Kind nicht unter seine Inhaltshoehe, "overflow-y" bleibt wirkungslos
     und der Fuss wird aus dem Panel gedrueckt (Register). */
  .koerper {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
    padding: 10px;
    /* Spalte, damit das Ergebnis den freien Platz bekommt: das Panel ist so
       hoch wie das Fenster, ein Textfeld fester Hoehe liesse darunter ein
       leeres Drittel stehen – gemessen im echten Browser. */
    display: flex;
    flex-direction: column;
  }
  /* Nur das Ergebnis waechst; alles andere behaelt seine Hoehe, sonst
     quetscht die Spalte die Formularzeilen zusammen. */
  .koerper > * { flex: 0 0 auto; }
  .koerper > #ergebnis { flex: 1 1 auto; display: flex; flex-direction: column; min-height: 0; }
  #ergebnis > textarea { flex: 1 1 auto; }
  .fuss {
    flex: 0 0 auto;
    display: flex;
    justify-content: flex-end;
    padding: 6px 10px;
    border-top: 1px solid var(--rand);
  }

  .feld { display: block; margin-bottom: 8px; }
  .feld > span { display: block; margin-bottom: 3px; font-size: 12px; color: var(--gedaempft); }
  .feld em { font-style: normal; opacity: .75; }

  input, textarea, select {
    width: 100%;
    padding: 6px 8px;
    border: 1px solid var(--rand);
    border-radius: 5px;
    background: var(--grund);
    color: var(--schrift);
    font: inherit;
  }
  /* ⚠ "width: 100%" traefe sonst auch das Kaestchen: ein 100 % breites
     Kontrollkaestchen schiebt seine Beschriftung in die naechste Zeile und
     sieht aus wie ein Eingabefeld (Register). */
  input[type="checkbox"], input[type="radio"] { width: auto; margin-right: 6px; vertical-align: middle; }
  textarea { resize: vertical; min-height: 160px; font-size: 12.5px; }
  input:focus-visible, textarea:focus-visible, select:focus-visible {
    outline: 2px solid var(--akzent);
    outline-offset: 1px;
  }

  button {
    padding: 6px 10px;
    border: 1px solid var(--rand);
    border-radius: 5px;
    background: transparent;
    color: var(--schrift);
    font: inherit;
    cursor: pointer;
  }
  button:hover:not(:disabled) { border-color: var(--akzent); }
  button:disabled { opacity: .5; cursor: default; }
  button.haupt { background: var(--akzent); border-color: var(--akzent); color: var(--akzent-schrift); }
  button.haupt:hover:not(:disabled) { background: var(--akzent-hover); border-color: var(--akzent-hover); }
  button.leise { color: var(--gedaempft); }
  button.ico { flex: 0 0 auto; padding: 4px 7px; line-height: 1; }

  /* "wrap": "Ins Kommentarfeld einfuegen" neben "Kopieren" passt bei 380 px
     nicht in eine Zeile – ohne Umbruch ragt der zweite Knopf hinaus. */
  .knopfreihe { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
  .knopfreihe > button { flex: 1 1 auto; }
  .knopfreihe > button.leise { flex: 0 0 auto; }

  .feld-zeile { display: flex; align-items: center; gap: 6px; }
  .feld-zeile select { flex: 1 1 auto; min-width: 0; }

  .hinweis, .fussnote { margin: -2px 0 8px; font-size: 11.5px; color: var(--gedaempft); }
  .fussnote { margin: 4px 0 0; }

  /* Meldungen tragen ihre Aussage doppelt – Farbe UND Text. */
  .meldung {
    margin: 10px 0 0;
    padding: 8px 10px;
    border: 1px solid var(--rand);
    border-radius: 5px;
    background: var(--warn);
    white-space: pre-wrap;
  }
  .meldung.arbeitet { background: transparent; color: var(--gedaempft); }

  /* Die Bezugswarnung ist KEINE Meldung: sie steht, solange der Text zu einem
     anderen Vorgang gehoert, und wird von der naechsten Aktion nicht
     ueberschrieben. */
  .warnung {
    margin: 0 0 8px;
    padding: 8px 10px;
    border: 1px solid var(--akzent);
    border-radius: 5px;
    background: var(--warn);
    font-weight: 600;
  }

  .ja-nein { margin-top: 10px; padding: 10px; border: 1px solid var(--akzent); border-radius: 6px; background: var(--warn); }
  .ja-nein p { margin: 0 0 8px; }
  .ja-nein .knopfreihe { margin: 0; }

  #vorlagen-box { margin: 10px 0 0; padding: 10px; border: 1px solid var(--rand); border-radius: 6px; }
  .vorl-kopf { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .vorl-liste { list-style: none; margin: 0 0 10px; padding: 0; }
  .vorl-liste li { display: flex; align-items: center; gap: 6px; padding: 4px 0; border-bottom: 1px solid var(--rand); }
  .vorl-liste li:last-child { border-bottom: 0; }
  .vorl-liste li > span { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
  `;

  /* Der Rueckfalltext traegt `{marke}` – ersetzt wird er von `markeAnwenden()`,
   * auch OHNE Branding (sonst stuende der rohe Platzhalter im Fenster). */
  const MARKUP = `
  <div class="rahmen" part="rahmen">
    <header class="kopf">
      <img class="logo" id="logo" alt="" hidden>
      <span class="marke" id="marke">{marke}</span>
      <span class="ticket" id="ticket"></span>
      <button type="button" id="btn-zu" class="leise ico" title="Assistent schließen"
              aria-label="Assistent schließen">&times;</button>
    </header>

    <div class="koerper">
      <p class="warnung" id="bezug-warnung" hidden></p>

      <div class="knopfreihe">
        <button type="button" id="btn-zus" class="haupt">Zusammenfassen</button>
        <button type="button" id="btn-ant" class="haupt">Antwort vorschlagen</button>
      </div>

      <label class="feld">
        <span>Vorlage für die Zusammenfassung</span>
        <div class="feld-zeile">
          <select id="f-vorlage"><option value="">Standard</option></select>
          <button type="button" id="btn-vorlagen" class="leise ico"
                  title="Vorlagen verwalten" aria-label="Vorlagen verwalten">⚙</button>
        </div>
      </label>

      <label class="feld">
        <span>Zusatzwunsch <em>(optional)</em></span>
        <input type="text" id="f-hinweis" placeholder="z. B. kurz halten, auf Englisch">
      </label>

      <div id="vorlagen-box" hidden>
        <div class="vorl-kopf">
          <b>Vorlagen</b>
          <button type="button" id="btn-vorlagen-zu" class="leise ico" title="Schließen"
                  aria-label="Schließen">&times;</button>
        </div>
        <ul class="vorl-liste" id="vorl-liste"></ul>
        <label class="feld">
          <span>Name</span>
          <input type="text" id="f-vorl-name" maxlength="60" placeholder="z. B. Kurz für die Leitung">
        </label>
        <label class="feld">
          <span>Anweisung</span>
          <textarea id="f-vorl-text" rows="4"
                    placeholder="Worauf soll die Zusammenfassung hinauslaufen?"></textarea>
        </label>
        <label class="feld" id="vorl-global-zeile" hidden>
          <span><input type="checkbox" id="f-vorl-global"> Für alle Benutzer (Administrator)</span>
        </label>
        <div class="knopfreihe">
          <button type="button" id="btn-vorl-speichern" class="haupt">Speichern</button>
          <button type="button" id="btn-vorl-neu" class="leise">Neu</button>
        </div>
        <p class="hinweis" id="vorl-hinweis"></p>
      </div>

      <div id="ergebnis" hidden>
        <textarea id="f-ergebnis" spellcheck="true"></textarea>
        <div class="knopfreihe">
          <button type="button" id="btn-einfuegen">Ins Kommentarfeld einfügen</button>
          <button type="button" id="btn-kopieren" class="leise">Kopieren</button>
        </div>
        <p class="fussnote" id="ergebnis-fuss"></p>
      </div>

      <div class="ja-nein" id="ja-nein" hidden>
        <p id="jn-text"></p>
        <div class="knopfreihe">
          <button type="button" id="jn-nein" class="leise">Abbrechen</button>
          <button type="button" id="jn-ja">Trotzdem einfügen</button>
        </div>
      </div>

      <p class="meldung" id="meldung" hidden></p>
    </div>

    <footer class="fuss">
      <button type="button" id="btn-abmelden" class="leise">Abmelden</button>
    </footer>
  </div>`;

  const wirt = document.createElement("div");
  wirt.id = WIRT_ID;
  const wurzel = wirt.attachShadow({ mode: "open" });
  const stil = document.createElement("style");
  stil.textContent = STIL;
  wurzel.appendChild(stil);
  const huelle = document.createElement("div");
  // Eigenes Markup, keine Fremdeingabe – Fremdtext geht ausschliesslich ueber
  // `textContent` hinein (Vorlagennamen, Modelltext, Serverfehler).
  huelle.innerHTML = MARKUP;
  while (huelle.firstChild) wurzel.appendChild(huelle.firstChild);
  document.body.appendChild(wirt);

  const $ = (id) => wurzel.getElementById(id);

  // ── Zustand ───────────────────────────────────────────────────────────────
  let _marke = "Jarvis";           // Rueckfall, solange keine Marke bekannt ist
  let _basis = "";
  let _key = "";                   // Ticketnummer der aktuellen Adresse
  let _letztes = null;             // zuletzt angezeigtes Ergebnis
  let _fremdesErgebnis = false;
  let _letztesFeld = null;         // das Feld, in dem der Benutzer zuletzt war
  let _vorlagen = { global: [], eigene: [], darf_global: false };
  let _vorlBearbeitet = "";
  let _merkTimer = null;

  // ── Marke ─────────────────────────────────────────────────────────────────
  /* Wie im Popup: die Erweiterung laeuft ausserhalb von Jarvis und kann weder
   * theme.css noch branding.js laden. Dies ist ein White-Label-Produkt – ein
   * Panel, das in der Jira-Oberflaeche jedes Sachbearbeiters "Jarvis" schreibt,
   * verraet das Produkt hinter der Hausmarke.
   * Die ORIGINALE mit Platzhalter werden gemerkt, damit ein zweiter Lauf
   * (Branding kommt nachtraeglich) wieder von vorn ersetzen kann. */
  const _originale = new Map();

  function markeAnwenden() {
    if (!_originale.size) {
      const lauf = document.createTreeWalker(wurzel, NodeFilter.SHOW_TEXT);
      for (let n = lauf.nextNode(); n; n = lauf.nextNode()) {
        if (n.nodeValue && n.nodeValue.indexOf("{marke}") >= 0) _originale.set(n, n.nodeValue);
      }
      for (const e of wurzel.querySelectorAll("[placeholder], [title]")) {
        for (const attr of ["placeholder", "title"]) {
          const v = e.getAttribute(attr);
          if (v && v.indexOf("{marke}") >= 0) _originale.set([e, attr], v);
        }
      }
    }
    for (const [ziel, roh] of _originale) {
      const wert = roh.split("{marke}").join(_marke);
      if (Array.isArray(ziel)) ziel[0].setAttribute(ziel[1], wert);
      else ziel.nodeValue = wert;
    }
  }

  function setzeBranding(b) {
    if (!b) return;
    const name = (b.assistant_name || b.company_name || "").trim();
    if (name) {
      _marke = name;
      markeAnwenden();
    }
    /* ⚠ DIE FARBEN STEHEN IN `colors`, NICHT FLACH IN DER ANTWORT – ein Zugriff
     * auf `b.accent` liefert `undefined`, und zwar STILL. */
    const farben = b.colors || {};
    // AM WIRT setzen, nicht am Dokument: die Variablen sind auf `:host`
    // deklariert, und nur dort gewinnt der Inline-Wert (Register).
    if (farben.accent) wirt.style.setProperty("--akzent", farben.accent);
    if (farben.accent_hover) wirt.style.setProperty("--akzent-hover", farben.accent_hover);
    const logo = b.logo_url_light || b.logo_url;
    if (logo) {
      const bild = $("logo");
      // Relative Adressen des Servers absolut machen – die Jira-Seite hat einen
      // anderen Ursprung, dort zeigt "/api/..." ins Leere.
      bild.src = /^https?:/i.test(logo) ? logo : ((_basis || "").replace(/\/+$/, "") + logo);
      bild.hidden = false;
    }
  }

  // ── Meldungen ─────────────────────────────────────────────────────────────
  function melde(text, arbeitet) {
    const m = $("meldung");
    if (!text) { m.hidden = true; return; }
    // Meldungen tragen `{marke}` – auch die aus dem Hintergrund, der das DOM
    // nicht kennt und selbst nicht ersetzen kann.
    m.textContent = String(text).split("{marke}").join(_marke);
    m.classList.toggle("arbeitet", !!arbeitet);
    m.hidden = false;
  }

  function sperre(an) {
    for (const b of wurzel.querySelectorAll("button")) b.disabled = an;
  }

  /** Rueckfrage – EIGENER Dialog, nie `confirm`.
   *
   * `window.confirm` blockiert den Renderer der FREMDEN Seite und sieht aus wie
   * ein Dialog von Jira. Der Fokus liegt auf ABBRECHEN: die gefaehrlichere Wahl
   * darf nicht die sein, die ein Tastendruck ausloest. */
  function frageJaNein(text) {
    const box = $("ja-nein");
    $("jn-text").textContent = text;
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
      $("jn-nein").focus();
    });
  }

  /** Eine Anfrage an den Hintergrund – Fehler kommen als Text, nie als Ausnahme
   * mitten in einem Klick-Handler. HIER LAEUFT KEIN `fetch` (siehe Kopf). */
  async function frage(nachricht) {
    const a = await api.runtime.sendMessage(nachricht);
    if (!a) throw new Error("Keine Antwort von der Erweiterung.");
    if (!a.ok) throw new Error(a.fehler || "Unbekannter Fehler.");
    return a;
  }

  // ── Ticketnummer und Ticketbezug ──────────────────────────────────────────
  /** Liest die Ticketnummer aus der Adresse – NICHT aus dem Seiteninhalt.
   *
   * Die Adresse ist die verlaessliche Quelle: `/browse/ABC-123` ist bei Jira
   * Server/DC wie Cloud stabil, waehrend sich das DOM mit jeder Jira-Version
   * aendert. Den INHALT holt ohnehin der Server ueber die Jira-API.
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

  /* ⚠ DER TICKETBEZUG IST EINE SICHERHEITSFRAGE, KEINE BEQUEMLICHKEIT.
   * Das Panel bleibt stehen, waehrend der Benutzer weiterarbeitet – bei einem
   * Wechsel innerhalb der Anwendung gehoert der angezeigte Text ploetzlich zu
   * einem anderen Vorgang. Ein Text ohne sichtbaren Bezug waere die Einladung,
   * die Antwort auf Vorgang A in Vorgang B einzufuegen, und die geht danach an
   * einen echten Kunden. */
  function bezugPruefen() {
    const w = $("bezug-warnung");
    _fremdesErgebnis = !!(_letztes && _letztes.key && _key && _letztes.key !== _key);
    if (_fremdesErgebnis) {
      w.textContent = "⚠ Dieser Text gehört zu " + _letztes.key + ", offen ist aber "
        + _key + ". Nicht einfügen, ohne ihn zu prüfen.";
      w.hidden = false;
    } else {
      w.hidden = true;
    }
  }

  function urlUebernehmen() {
    _key = keyAusUrl(location.href);
    $("ticket").textContent = _key || "";
    bezugPruefen();
  }

  // ── Das Feld merken, in dem der Benutzer zuletzt war ──────────────────────
  /* Ohne das ist die verlaesslichste Regel des Einfuegens tot: sobald jemand im
   * Panel klickt, ist `document.activeElement` der Panel-Wirt. Gemerkt wird nur,
   * was ueberhaupt ein Schreibziel sein kann – sonst wuerde ein Klick auf Jiras
   * Formatierleiste das Kommentarfeld verdraengen. */
  function istSchreibziel(el) {
    if (!el || el === wirt) return false;
    if (el.tagName === "TEXTAREA" || el.tagName === "IFRAME") return true;
    if (el.tagName === "INPUT") return /^(text|search)$/i.test(el.type || "");
    return el.isContentEditable === true
      || (el.getAttribute && el.getAttribute("contenteditable") === "true");
  }

  // Der Klick im Panel wird am Dokument auf den WIRT umgeschrieben (Shadow DOM),
  // deshalb genuegt der Vergleich in `istSchreibziel`.
  const merkeFokus = (ev) => {
    if (istSchreibziel(ev.target)) _letztesFeld = ev.target;
  };
  document.addEventListener("focusin", merkeFokus, true);
  if (istSchreibziel(document.activeElement)) _letztesFeld = document.activeElement;

  const takt = setInterval(() => {
    if (keyAusUrl(location.href) !== _key) urlUebernehmen();
  }, URL_TAKT);

  wirt.__jvAufraeumen = () => {
    clearInterval(takt);
    clearTimeout(_merkTimer);
    document.removeEventListener("focusin", merkeFokus, true);
  };

  // ── Auswerten ─────────────────────────────────────────────────────────────
  function zeigeErgebnis(d, frisch) {
    _letztes = d;
    $("f-ergebnis").value = d.text || "";
    $("ergebnis").hidden = false;
    const alter = Math.round((Date.now() - (d.zeit || 0)) / 60000);
    $("ergebnis-fuss").textContent =
      d.key + " · " + (d.kommentare || 0) + " Kommentar(e)"
      + (frisch ? " ausgewertet" : "")
      + (frisch ? "" : " · " + (alter < 1 ? "gerade eben" : "vor " + alter + " Min."))
      + (d.modell ? " · " + d.modell : "");
    bezugPruefen();
  }

  async function auswerten(modus) {
    if (!_key) {
      melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
      return;
    }
    sperre(true);
    $("ergebnis").hidden = true;
    melde(modus === "antwort"
      ? "Formuliere einen Antwortvorschlag … (dauert einige Sekunden)"
      : "Fasse das Ticket zusammen … (dauert einige Sekunden)", true);
    try {
      const a = await frage({
        art: "auswerten", key: _key, modus,
        lang: (navigator.language || "de").toLowerCase().startsWith("de") ? "de" : "en",
        hinweis: ($("f-hinweis").value || "").trim(),
        // Die Vorlage gilt nur fuer die Zusammenfassung – ein Antwortvorschlag
        // hat seine eigene Aufgabe, dort waere sie eine zweite Anweisung.
        vorlage: (modus === "zusammenfassung") ? ($("f-vorlage").value || "") : "",
      });
      const d = a.daten || {};
      zeigeErgebnis({ key: d.key, modus: d.modus, text: d.text || "",
                      titel: d.titel || "", kommentare: d.kommentare || 0,
                      modell: d.modell || "", zeit: Date.now() }, true);
      melde(modus === "antwort"
        ? "Vorschlag – bitte vor dem Absenden lesen und anpassen."
        : "");
    } catch (e) {
      melde(e.message);
    } finally {
      sperre(false);
    }
  }

  // ── Vorlagen ──────────────────────────────────────────────────────────────
  /* Gemeinsame Vorlagen pflegt ein Administrator, eigene darf jeder anlegen –
   * die Trennung ist am Server durchgesetzt, hier wird sie nur ANGEZEIGT. */
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
    sel.value = gewaehlt;                        // Auswahl ueberlebt das Neuzeichnen
    if (sel.value !== gewaehlt) sel.value = "";  // ...ausser sie wurde geloescht

    const liste = $("vorl-liste");
    liste.innerHTML = "";
    for (const [art, vs] of [["global", _vorlagen.global], ["eigen", _vorlagen.eigene]]) {
      for (const v of vs) {
        // Aenderbar ist nur, was einem gehoert – oder alles, wenn man Admin ist.
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
          // Muelleimer = loeschen (Projektregel). Als Inline-SVG, nicht als
          // Emoji: ein Emoji-Muelleimer wird je System anders gerendert.
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
      // Ohne Vorlagen bleibt "Standard" – kein Grund, den Rest zu sperren.
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

  // ── Einfuegen und Kopieren ────────────────────────────────────────────────
  async function einfuegen() {
    const text = $("f-ergebnis").value || "";
    if (!text.trim()) return;
    /* Ein Text zu einem anderen Vorgang wird nicht ohne Rueckfrage eingefuegt –
     * das Ergebnis geht am Ende an einen Kunden. */
    if (_fremdesErgebnis) {
      const ok = await frageJaNein("Der Text gehört zu " + (_letztes && _letztes.key)
        + ", offen ist " + _key + ". Trotzdem einfügen?");
      if (!ok) return;
    }
    sperre(true);
    try {
      /* HIER liegt der zweite Gewinn des Panels: die Suche laeuft in derselben
       * Seite, und das zuletzt benutzte Feld ist bekannt. Aus dem Popup heraus
       * war beides nur ueber einen serialisierten Fremdaufruf zu haben. */
      const werkzeug = (globalThis.__jvEinfuegen || {});
      let r = werkzeug.einfuegenInJira
        ? werkzeug.einfuegenInJira(text, _letztesFeld)
        : { ok: false, fehler: "Das Einfüge-Modul wurde nicht geladen." };

      /* ZWEITER VERSUCH UEBER DIE EDITOR-API DER SEITE.
       * Von hier aus ist `window.tinymce` unsichtbar – das Panel laeuft in der
       * isolierten Welt. Der Hintergrund schiebt die Funktion mit
       * `world: "MAIN"` nach; nur wenn der erste Weg scheitert, denn Code im
       * Seitenkontext teilt sich deren globalen Namensraum. */
      if (!r.ok && r.tinymce_moeglich) {
        try {
          const a = await frage({ art: "editor_api", text });
          if (a.daten && a.daten.ok) r = a.daten;
        } catch (e) {
          // `world: "MAIN"` gibt es in Firefox erst ab 128 – dort bleibt es beim
          // Ergebnis des ersten Versuchs. Die Meldung unten ist die
          // aussagekraeftigere.
        }
      }

      if (r.ok) {
        melde("Eingefügt. Bitte in Jira prüfen und selbst abschicken.");
      } else {
        // DIE DIAGNOSE GEHOERT IN DIE MELDUNG. Ohne sie ist der naechste Anlauf
        // wieder Raten – fuer den Benutzer wie fuer die Fehlersuche.
        const gesehen = (r.gesehen && r.gesehen.length)
          ? "\nGefunden: " + r.gesehen.join(", ") : "";
        melde((r.fehler || "Einfügen fehlgeschlagen.") + gesehen);
      }
    } catch (e) {
      melde("Einfügen nicht möglich: " + ((e && e.message) || e)
            + "\nBenutze „Kopieren“ und füge den Text von Hand ein.");
    } finally {
      sperre(false);
    }
  }

  // ── Verdrahtung ───────────────────────────────────────────────────────────
  $("btn-zu").addEventListener("click", () => {
    wirt.__jvAufraeumen();
    wirt.remove();
  });
  $("btn-zus").addEventListener("click", () => auswerten("zusammenfassung"));
  $("btn-ant").addEventListener("click", () => auswerten("antwort"));
  $("btn-einfuegen").addEventListener("click", einfuegen);

  $("btn-kopieren").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("f-ergebnis").value || "");
      melde("In die Zwischenablage kopiert.");
    } catch (e) {
      // Rueckmeldung ist Pflicht: in der Zwischenablage sieht man nichts, ein
      // stiller Fehlschlag waere unsichtbar.
      melde("Kopieren fehlgeschlagen. Markiere den Text und kopiere ihn von Hand.");
    }
  });

  $("btn-abmelden").addEventListener("click", async () => {
    try { await frage({ art: "abmelden" }); } catch (e) { /* egal */ }
    _letztes = null;
    $("ergebnis").hidden = true;
    $("bezug-warnung").hidden = true;
    melde("Abgemeldet. Klicke auf das Symbol, um dich neu anzumelden.");
  });

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
      // Die frisch gespeicherte Vorlage gleich auswaehlen – sonst muss der
      // Benutzer sie im Pulldown suchen, das er gerade gefuellt hat.
      const neu = a.daten && a.daten.vorlage;
      if (neu && neu.id) $("f-vorlage").value = neu.id;
      vorlageInsFormular(null, false);
      $("vorl-hinweis").textContent = "Gespeichert.";
    } catch (e) {
      $("vorl-hinweis").textContent = e.message;
    }
  });

  /* Der BEARBEITETE Text wird mitgemerkt – gedrosselt.
   * Das Panel ueberlebt zwar den Tabwechsel, aber nicht das Neuladen der Seite;
   * wer einen Vorschlag umschreibt, soll seine Aenderungen nicht verlieren.
   * Bei jedem Tastendruck zu speichern waere unnoetig. */
  $("f-ergebnis").addEventListener("input", () => {
    clearTimeout(_merkTimer);
    _merkTimer = setTimeout(async () => {
      if (!_letztes) return;
      _letztes.text = $("f-ergebnis").value || "";
      try { await frage({ art: "ergebnis_merken", wert: _letztes }); } catch (e) {}
    }, 500);
  });

  // Escape schliesst zuerst die Rueckfrage, dann das Panel – sonst stuende eine
  // Warnung ohne Bezug ueber einer geschlossenen Oberflaeche.
  wurzel.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    if (!$("ja-nein").hidden) { $("jn-nein").click(); return; }
    $("btn-zu").click();
  });

  // ── Start ─────────────────────────────────────────────────────────────────
  (async function start() {
    // ZUERST die Platzhalter belegen – sonst steht "{marke}" sichtbar da,
    // solange (oder falls) kein Branding geholt werden kann.
    markeAnwenden();
    urlUebernehmen();
    let z;
    try {
      z = await frage({ art: "zustand" });
    } catch (e) {
      melde(e.message);
      return;
    }
    _basis = z.basis || "";
    if (!z.angemeldet) {
      // Der Hintergrund stellt in diesem Fall das Anmeldefenster wieder her –
      // ein Anmeldeformular im Panel waere eine zweite Fassung derselben Maske.
      melde("Nicht angemeldet. Klicke auf das Symbol, um dich anzumelden.");
      sperre(true);
      $("btn-zu").disabled = false;
      return;
    }
    try { setzeBranding((await frage({ art: "branding" })).daten); }
    catch (e) { /* ohne Branding bleibt das eingebaute Aussehen */ }
    vorlagenLaden();
    if (z.ergebnis && z.ergebnis.text) {
      zeigeErgebnis(z.ergebnis, false);
      if (!_fremdesErgebnis) {
        melde(z.ergebnis.modus === "antwort"
          ? "Gemerkter Vorschlag – bitte vor dem Absenden lesen."
          : "Gemerkte Zusammenfassung.");
      }
    }
    if (!_key) {
      // Kein Fehler, sondern eine Auskunft: die Erweiterung ist bereit, dieser
      // Tab ist nur kein Ticket.
      melde("Kein Jira-Ticket in diesem Tab. Öffne ein Ticket (…/browse/ABC-123).");
    }
  })();
})();
