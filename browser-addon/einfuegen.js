/* „Als Kommentar uebernehmen" – schreibt in das Jira-Kommentarfeld, per
 * scripting.executeScript in die Seite injiziert, NUR auf Klick (activeTab).
 *
 * ⚠ ES WIRD UEBERSCHRIEBEN, NICHT ANGEHAENGT (Vorgabe 2026-08-31). Der Knopf
 * hiess bis dahin „Ins Kommentarfeld einfuegen" und haengte an – aber nur bei
 * den EDITOR-Wegen; die textarea-Wege ersetzten schon immer. Dieselbe
 * Beschriftung hatte damit je Jira-Betriebsart eine andere Wirkung.
 * Und der Regelablauf verlangt das Ersetzen: „Antwort ueberarbeiten" LIEST den
 * Entwurf aus genau diesem Feld, der uebernommene Text ist dessen korrigierte
 * Fassung – angehaengt stuende beides hintereinander im Kommentar beim Kunden.
 *
 * GEMELDET AUS DEM BETRIEB: "'in Kommentarfeld uebernehmen' fuegt NICHT in das
 * Feld ein" – bei einem Jira mit WYSIWYG-Editor (Formatierleiste). Die erste
 * Fassung suchte zuerst `#comment` als <textarea>; in dieser Betriebsart ist
 * die zwar vorhanden, aber unsichtbar, und der eigentliche Editor lag nicht in
 * den geprueften Selektoren.
 *
 * DREI LEHREN, die die Reihenfolge unten bestimmen:
 *
 * 1. DAS ZULETZT FOKUSSIERTE FELD SCHLAEGT JEDE SELEKTORLISTE. Wer einfuegen
 *    will, hat vorher ins Kommentarfeld geklickt. `document.activeElement`
 *    ueberlebt das Oeffnen des Popups (das Dokument verliert den Fokus, die
 *    Auswahl bleibt). Damit funktioniert es auch in einem Editor, den niemand
 *    vorhergesehen hat – und der Benutzer hat die Kontrolle darueber, WOHIN
 *    geschrieben wird.
 * 2. EIN FEHLSCHLAG MUSS SAGEN, WAS ER GESEHEN HAT. Ohne Diagnose ist der
 *    naechste Anlauf wieder Raten. Der Rueckgabewert nennt deshalb die
 *    gefundenen Kandidaten.
 * 3. DIESE FUNKTION LAEUFT IN DER ISOLIERTEN WELT und sieht `window.tinymce`
 *    der Seite NICHT. Der Editor-API-Weg steht deshalb in einer zweiten
 *    Funktion (`einfuegenUeberEditorApi`), die der Aufrufer bei Bedarf mit
 *    `world: "MAIN"` nachschiebt.
 *
 * ⚠ SERIALISIERUNG: beide Funktionen werden per toString uebertragen und in der
 * Seite neu ausgewertet. Sie duerfen NICHTS aus ihrem Modul benutzen – keine
 * Importe, keine Konstanten von aussen. Alle Helfer stehen innen.
 */

export function einfuegenInJira(text, bloecke) {
  "use strict";

  /* `bloecke` ist der bereits geparste Text: `[[{t,fett}, …], …]`, eine Zeile
   * je Eintrag. Er kommt als JSON ueber `executeScript({args})`, weil DIESE
   * Funktion keinen eigenen Parser haben darf – sie wird per toString
   * uebertragen und sieht ihr Modul nicht (siehe Dateikopf). Zwei Parser waeren
   * zwei Fassungen: der Mitarbeiter saehe etwas anderes als der Kunde.
   *
   * FEHLT er (aelteres Fenster), verhaelt sich alles wie vor dem Umbau. */
  const _bl = Array.isArray(bloecke) ? bloecke : null;

  function hatFett() {
    return !!_bl && _bl.some(function (laeufe) {
      return laeufe.some(function (l) { return l && l.fett; });
    });
  }

  /* Text OHNE die Sternchen – fuer alles, was kein Fett kann.
   * Ein `**` in einer textarea ist genau das, was der Kunde am Ende liest;
   * lieber ohne Fett als mit Sternchen. Ohne `bloecke` bleibt es beim
   * Originaltext (fail-safe: nichts wegwerfen, was man nicht deuten kann). */
  function klartext() {
    if (!_bl) return text;
    return _bl.map(function (laeufe) {
      return laeufe.map(function (l) { return l.t; }).join("");
    }).join("\n");
  }

  /* Absaetze wie bisher: leere Zeile trennt, einfacher Umbruch wird zum
   * Leerzeichen. Genau das machte der bisherige Rueckfall mit
   * `txt.split(/\n{2,}/)` und `replace(/\n/g, " ")` – nur eben auf Text
   * statt auf Laeufen. */
  function absaetze() {
    const raus = [];
    let aktuell = [];
    for (const laeufe of (_bl || [])) {
      const leer = !laeufe.length
        || laeufe.every(function (l) { return !String(l.t).trim(); });
      if (leer) {
        if (aktuell.length) { raus.push(aktuell); aktuell = []; }
        continue;
      }
      if (aktuell.length) aktuell.push({ t: " ", fett: false });
      for (const l of laeufe) aktuell.push(l);
    }
    if (aktuell.length) raus.push(aktuell);
    return raus;
  }

  /* Baut einen Absatz als KNOTEN – nie ueber innerHTML.
   * Damit ist ausgeschlossen, dass Modelltext im Kommentarfeld zu Markup wird;
   * die Fett-Auszeichnung entsteht aus der geparsten Struktur, nicht aus
   * Zeichen im Text. */
  function absatzKnoten(aus, laeufe) {
    const p = aus.createElement("p");
    for (const l of laeufe) {
      if (l.fett) {
        const stark = aus.createElement("strong");
        stark.appendChild(aus.createTextNode(l.t));
        p.appendChild(stark);
      } else {
        p.appendChild(aus.createTextNode(l.t));
      }
    }
    return p;
  }

  function sichtbar(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function istTextfeld(el) {
    return !!el && (el.tagName === "TEXTAREA"
      || (el.tagName === "INPUT" && /^(text|search)$/i.test(el.type || "")));
  }

  function istEditierbar(el) {
    if (!el) return false;
    // BEIDES pruefen: `isContentEditable` ist die richtige Frage, aber nicht
    // ueberall vorhanden (jsdom kennt es gar nicht, und ein Editor kann das
    // Attribut dynamisch setzen, bevor der Browser die Eigenschaft nachzieht).
    // Das Attribut allein waere zu schwach – deshalb die Oder-Verknuepfung.
    return el.isContentEditable === true
      || (el.getAttribute && el.getAttribute("contenteditable") === "true");
  }

  /* MARKIERT DEN GANZEN INHALT, damit `insertText`/`insertHTML` ihn ERSETZT.
   *
   * ⚠ HIER STAND DAS GEGENTEIL: der Cursor wurde ans ENDE gestellt, "damit ein
   * bereits getippter Text nicht ersetzt wird". Seit der Knopf „Als Kommentar
   * uebernehmen" heisst, ist das Ersetzen die Zusage – und sie ist auch die
   * einzige, die zum Ablauf passt: der uebernommene Text IST in der Regel die
   * ueberarbeitete Fassung genau des Entwurfs, der im Feld steht („Antwort
   * ueberarbeiten" liest ihn von dort). Angehaengt stuende er zweimal im
   * Kommentar beim Kunden.
   *
   * Ueber die AUSWAHL zu ersetzen und nicht per `innerHTML` ist Absicht: es
   * geht durch die Ereignisbehandlung des Editors und bleibt ruecknehmbar
   * (Strg+Z) – wer versehentlich uebernommen hat, kommt zurueck. */
  function alleMarkieren(el) {
    try {
      const aus = el.ownerDocument || document;
      const sel = (aus.defaultView || window).getSelection();
      if (!sel) return false;
      const r = aus.createRange();
      r.selectNodeContents(el);
      sel.removeAllRanges();
      sel.addRange(r);
      return true;
    } catch (e) { return false; }
  }

  /* Inhalt restlos entfernen – fuer die Wege OHNE execCommand.
   * Ueber Knoten, nicht `innerHTML = ""`: diese Datei fasst nie innerHTML an. */
  function leeren(el) { while (el.firstChild) el.removeChild(el.firstChild); }

  /** Setzt einen Wert so, dass auch React/Angular ihn mitbekommen.
   *
   * Ein blosses `el.value = x` aktualisiert das DOM, aber nicht den Zustand
   * eines Frameworks – beim Absenden waere das Feld dann wieder leer.
   */
  function setzeWert(el, wert) {
    const proto = (el.tagName === "TEXTAREA")
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value");
    if (setter && setter.set) { setter.set.call(el, wert); } else { el.value = wert; }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /** Schreibt in ein contenteditable – bevorzugt so, dass der Editor es merkt.
   *
   * `insertText` ist der beste Weg: es loest die Ereignisse aus, auf die ein
   * Editor hoert, und bleibt rueckgaengig machbar. Erst wenn das nicht geht,
   * wird der Inhalt gesetzt – dann aber als ABSAETZE, nicht als eine Zeile.
   */
  function schreibeEditierbar(el, txt) {
    el.focus();
    /* ⚠ MIT FETT WIRD `insertText` UEBERSPRUNGEN – und das ist ein bewusster
     * Tausch, kein Versehen. `insertText` traegt nur Klartext ein; die
     * Auszeichnung ginge dabei verloren. Der Knotenweg darunter kann Fett,
     * wird aber von manchen Editoren nicht bemerkt.
     * OHNE Fett bleibt alles exakt wie vor dem Umbau – und das ist der
     * Normalfall: in 14 gemessenen Laeufen lieferte das Modell kein einziges
     * Mal Fett. Der riskantere Weg wird also nur beschritten, wenn es dafuer
     * einen Grund gibt. */
    if (hatFett()) return schreibeMitFett(el);
    try {
      const aus = el.ownerDocument || document;
      // Ganzen Inhalt markieren: `insertText` ERSETZT die Auswahl.
      alleMarkieren(el);
      if (aus.execCommand && aus.execCommand("insertText", false, txt)) {
        return "insertText";
      }
    } catch (e) { /* weiter mit dem direkten Weg */ }

    const aus = el.ownerDocument || document;
    // Ohne execCommand bleibt nur der harte Weg – dann aber ebenfalls
    // ersetzend, sonst haette derselbe Knopf je Editor eine andere Wirkung.
    leeren(el);
    for (const absatz of txt.split(/\n{2,}/)) {
      const p = aus.createElement("p");
      // textContent, nicht innerHTML – der Vorschlag ist Modelltext und darf
      // kein Markup einschleusen.
      p.textContent = absatz.replace(/\n/g, " ");
      el.appendChild(p);
    }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return "appendChild";
  }

  /** Fett einfuegen – in absteigender Verlaesslichkeit, MIT Rueckleseprobe.
   *
   * ⚠ DIE HALBFEHLERSTELLUNGEN SIND NICHT GLEICH SCHWER, und daraus folgt die
   * Reihenfolge: „Text kommt an, Fett fehlt" ist harmlos – der Mitarbeiter
   * sieht es und kann es von Hand setzen. „Text kommt gar nicht an, es meldet
   * aber Erfolg" ist teuer: er wechselt in den Jira-Tab und findet ein leeres
   * Kommentarfeld, oder schlimmer, er merkt es nicht.
   *
   * 1. `insertHTML` – geht durch die Ereignisbehandlung des Editors, bleibt
   *    ruecknehmbar. Das HTML wird SELBST gebaut, jeder Text ueber
   *    `textContent` (dieselbe Technik wie im TinyMCE-Weg unten): Modelltext
   *    beruehrt nie einen HTML-Parser.
   * 2. Knoten anhaengen – kann Fett, wird aber von Editoren mit eigenem
   *    Dokumentmodell (ak-editor/ProseMirror in Jira Cloud) womoeglich
   *    ignoriert.
   * 3. RUECKLESEN. Steht der Text danach nicht im Feld, war Weg 1 und 2
   *    wirkungslos: dann lieber `insertText` mit Klartext – Fett verloren,
   *    Text da. Ohne diese Probe waere ein ignoriertes `appendChild` ein
   *    STILLER Fehlschlag mit Erfolgsmeldung.
   */
  function schreibeMitFett(el) {
    const aus = el.ownerDocument || document;
    const vorher = (el.textContent || "").replace(/\s+/g, " ").trim();
    const probe = klartext().replace(/\s+/g, " ").trim().slice(0, 24);
    const alteProbe = vorher.slice(0, 24);

    /* ⚠ DIE RUECKLESEPROBE MUSSTE MIT DEM UEBERSCHREIBEN UMGEBAUT WERDEN.
     * Vorher hiess "angekommen" `jetzt.length > vorher.length` – das war fuer
     * ANHAENGEN richtig und ist fuer ERSETZEN falsch: die ueberarbeitete
     * Fassung darf kuerzer sein als der Entwurf, den sie ersetzt, und der Weg
     * haette sich dann selbst fuer wirkungslos erklaert und waere auf den
     * Rueckfall ohne Fett gefallen.
     * Zwei Haelften, beide noetig:
     *   – der NEUE Text ist da (Probetext gefunden),
     *   – der ALTE ist weg. Ohne die zweite gilt ein wirkungsloses insertHTML
     *     als Erfolg. Sie wird uebersprungen, wenn beide Texte gleich
     *     ANFANGEN – das ist der haeufige Fall (die Korrektur beginnt wie der
     *     Entwurf), und dort waere sie ein Fehlalarm. */
    function angekommen() {
      const jetzt = (el.textContent || "").replace(/\s+/g, " ");
      if (probe && jetzt.indexOf(probe) < 0) return false;
      if (alteProbe && alteProbe !== probe && jetzt.indexOf(alteProbe) >= 0) return false;
      return jetzt.trim().length > 0;
    }

    // 1) insertHTML – ersetzt die Auswahl, also den ganzen alten Inhalt.
    try {
      if (aus.execCommand) {
        const html = absaetze().map(function (laeufe) {
          return absatzKnoten(aus, laeufe).outerHTML;
        }).join("");
        alleMarkieren(el);
        if (aus.execCommand("insertHTML", false, html) && angekommen()) {
          return "insertHTML+fett";
        }
      }
    } catch (e) { /* weiter mit Knoten */ }

    // 2) Alten Inhalt entfernen und Knoten setzen
    leeren(el);
    for (const laeufe of absaetze()) el.appendChild(absatzKnoten(aus, laeufe));
    el.dispatchEvent(new Event("input", { bubbles: true }));
    if (angekommen()) return "appendChild+fett";

    /* 3) Beides wirkungslos – der Editor fuehrt sein eigenes Modell. Jetzt
     * zaehlt nur noch, dass der TEXT ankommt. */
    try {
      alleMarkieren(el);
      if (aus.execCommand && aus.execCommand("insertText", false, klartext())) {
        return "insertText ohne Fett";
      }
    } catch (e) { /* nichts mehr uebrig */ }
    return "appendChild+fett (ungeprueft)";
  }

  // ── 1. Das zuletzt fokussierte Feld ───────────────────────────────────────
  // Auch in einem iframe: activeElement des Hauptdokuments ist dann der iframe.
  let ziel = document.activeElement;
  if (ziel && ziel.tagName === "IFRAME") {
    try { ziel = ziel.contentDocument.activeElement; } catch (e) { ziel = null; }
  }
  if (istTextfeld(ziel) && sichtbar(ziel)) {
    // Eine textarea kann kein Fett – dort geht der bereinigte Text hinein.
    // `setzeWert` ERSETZT den Inhalt; dieser Weg hat also immer schon
    // ueberschrieben, waehrend die Editor-Wege anhaengten. Genau diese
    // Ungleichheit loest „Als Kommentar uebernehmen" auf.
    setzeWert(ziel, klartext());
    ziel.focus();
    return { ok: true, weg: "fokussiertes Textfeld" };
  }
  if (istEditierbar(ziel)) {
    const weg = schreibeEditierbar(ziel, text);
    return { ok: true, weg: "fokussierter Editor (" + weg + ")" };
  }

  // ── 2. Bekannte Kommentarfelder ───────────────────────────────────────────
  // Reihenfolge = Wahrscheinlichkeit. Der WYSIWYG-Fall steht VOR der textarea:
  // bei aktivem Rich-Text-Editor existiert `#comment` zwar, ist aber versteckt
  // und traegt beim Absenden nicht den sichtbaren Inhalt.
  const diagnose = [];

  const editorSelektoren = [
    "#comment-wiki-edit [contenteditable='true']",
    ".jira-editor-container [contenteditable='true']",
    ".ak-editor-content-area [contenteditable='true']",   // Jira Cloud
    "[data-testid='comment'] [contenteditable='true']",
    "form [contenteditable='true']",
    "[contenteditable='true']",
  ];
  for (const sel of editorSelektoren) {
    for (const el of document.querySelectorAll(sel)) {
      diagnose.push(sel + (sichtbar(el) ? " (sichtbar)" : " (unsichtbar)"));
      if (sichtbar(el)) {
        const weg = schreibeEditierbar(el, text);
        return { ok: true, weg: sel + " – " + weg };
      }
    }
  }

  // TinyMCE und andere iframe-Editoren (Jira Server mit Rich-Text).
  for (const rahmen of document.querySelectorAll("iframe")) {
    let koerper = null;
    try { koerper = rahmen.contentDocument && rahmen.contentDocument.body; }
    catch (e) { continue; }                      // fremde Herkunft
    if (!koerper) continue;
    const editierbar = koerper.isContentEditable
      || koerper.getAttribute("contenteditable") === "true"
      || (rahmen.contentDocument.designMode || "").toLowerCase() === "on";
    if (!editierbar) continue;
    diagnose.push("iframe#" + (rahmen.id || "?")
      + (sichtbar(rahmen) ? " (sichtbar)" : " (unsichtbar)"));
    if (!sichtbar(rahmen)) continue;
    const aus = rahmen.contentDocument;
    koerper.focus();
    let weg = "innerHTML";
    if (hatFett()) {
      leeren(koerper);                       // ersetzen, nicht anhaengen
      for (const laeufe of absaetze()) koerper.appendChild(absatzKnoten(aus, laeufe));
      koerper.dispatchEvent(new Event("input", { bubbles: true }));
      return { ok: true, weg: "iframe-Editor (appendChild+fett)" };
    }
    try {
      alleMarkieren(koerper);                // insertText ersetzt die Auswahl
      if (aus.execCommand && aus.execCommand("insertText", false, text)) weg = "insertText";
      else throw new Error("kein insertText");
    } catch (e) {
      koerper.innerHTML = text.split(/\n{2,}/).map(function (p) {
        const d = aus.createElement("p");
        d.textContent = p.replace(/\n/g, " ");
        return d.outerHTML;
      }).join("");
    }
    koerper.dispatchEvent(new Event("input", { bubbles: true }));
    return { ok: true, weg: "iframe-Editor (" + weg + ")" };
  }

  // Einfache Textfelder zuletzt.
  for (const sel of ["#comment", "textarea[name='comment']",
                     "#jira-issue-comment textarea", ".issue-comment textarea",
                     "textarea.wiki-editor", "form textarea"]) {
    for (const el of document.querySelectorAll(sel)) {
      diagnose.push(sel + (sichtbar(el) ? " (sichtbar)" : " (unsichtbar)"));
      if (sichtbar(el)) {
        setzeWert(el, klartext());     // textarea kann kein Fett
        el.focus();
        try { el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) {}
        return { ok: true, weg: "textarea " + sel };
      }
    }
  }

  // ── 3. Nichts gefunden: sagen, was da war ─────────────────────────────────
  return {
    ok: false,
    // `tinymce_moeglich` sagt dem Aufrufer, ob ein zweiter Versuch ueber die
    // Editor-API der Seite lohnt (die ist von hier aus unsichtbar).
    tinymce_moeglich: document.querySelectorAll("iframe").length > 0
      || !!document.querySelector(".wiki-edit, .jira-editor-container, #comment"),
    gesehen: diagnose.slice(0, 8),
    fehler: diagnose.length
      ? "Ein Kommentarfeld ist vorhanden, war aber nicht beschreibbar. "
        + "Klicke zuerst IN das Kommentarfeld und versuche es erneut."
      : "Auf dieser Seite wurde kein Kommentarfeld gefunden. Öffne das "
        + "Kommentarfeld in Jira und versuche es erneut – oder benutze „Kopieren“.",
  };
}


/* LESEN statt schreiben – fuer "Überarbeiten".
 *
 * Der Benutzer hat seine Antwort schon getippt; hier wird sie geholt, damit der
 * Server sie gegen den Ticketverlauf abgleichen kann. Dieselbe Kaskade und
 * dieselben drei Lehren wie beim Einfuegen – vor allem die erste: DAS ZULETZT
 * FOKUSSIERTE FELD SCHLAEGT JEDE SELEKTORLISTE. Wer ueberarbeiten laesst, hat
 * gerade in das Feld getippt; `document.activeElement` ueberlebt das Oeffnen des
 * Popups.
 *
 * ⚠ DER UNTERSCHIED ZUM EINFUEGEN: hier gewinnt das erste Feld MIT TEXT, nicht
 * das erste ueberhaupt. Grund ist ein Jira-Detail – manche Editoren halten den
 * Fokus auf einer versteckten Spiegel-`textarea`, waehrend der sichtbare Editor
 * den Inhalt traegt. Wuerde das fokussierte, leere Feld sofort gewinnen, meldete
 * die Erweiterung "leer", obwohl der Text sichtbar auf dem Schirm steht. Ein
 * leerer Fund wird deshalb nur GEMERKT und die Suche laeuft weiter; die
 * Reihenfolge bleibt dieselbe.
 *
 * Was NICHT passiert: es wird nichts anderes von der Seite gelesen. Nur der
 * Inhalt des Kommentarfeldes verlaesst den Tab.
 */
export function leseAusJira() {
  "use strict";

  function sichtbar(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function istTextfeld(el) {
    return !!el && (el.tagName === "TEXTAREA"
      || (el.tagName === "INPUT" && /^(text|search)$/i.test(el.type || "")));
  }

  function istEditierbar(el) {
    if (!el) return false;
    return el.isContentEditable === true
      || (el.getAttribute && el.getAttribute("contenteditable") === "true");
  }

  /** Zeilenumbrueche erhalten, Leerlauf entfernen.
   *
   * Ein Absatzwechsel ist im Ergebnis eine Information: der Server bekommt den
   * Entwurf als Text, und "Guten TagIhr Anliegen" waere eine andere Vorlage als
   * die getippte.
   */
  function aufraeumen(t) {
    return String(t || "")
      .replace(/\r/g, "")
      .replace(/ /g, " ")          // geschuetzte Leerzeichen der Editoren
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  /** Text aus einem Editor – mit Absaetzen, nicht als eine Zeile.
   *
   * `innerText` ist der richtige Weg (er liefert den SICHTBAREN Text samt
   * Umbruechen), existiert aber nicht ueberall. `textContent` allein waere
   * falsch: es klebt alle Absaetze aneinander. Deshalb der Rueckfall, der die
   * Blockgrenzen selbst setzt.
   */
  function textAus(el) {
    const roh = el.innerText;
    if (typeof roh === "string" && roh.trim()) return roh;
    const BLOCK = /^(P|DIV|LI|UL|OL|H[1-6]|BLOCKQUOTE|PRE|TR|SECTION|ARTICLE)$/;
    const teile = [];
    (function lauf(k) {
      for (let n = k.firstChild; n; n = n.nextSibling) {
        if (n.nodeType === 3) { teile.push(n.nodeValue || ""); continue; }
        if (n.nodeType !== 1) continue;
        if (n.tagName === "BR") { teile.push("\n"); continue; }
        const block = BLOCK.test(n.tagName);
        if (block) teile.push("\n");
        lauf(n);
        if (block) teile.push("\n");
      }
    })(el);
    return teile.join("");
  }

  const diagnose = [];
  let leerGesehen = false;

  /** Liefert den Text – oder merkt sich, dass das Feld leer war. */
  function hole(el, weg) {
    const t = aufraeumen(istTextfeld(el) ? (el.value || "") : textAus(el));
    if (!t) { leerGesehen = true; diagnose.push(weg + " (leer)"); return null; }
    return { ok: true, weg: weg, text: t };
  }

  // ── 1. Das zuletzt fokussierte Feld ───────────────────────────────────────
  let ziel = document.activeElement;
  if (ziel && ziel.tagName === "IFRAME") {
    try { ziel = ziel.contentDocument.activeElement; } catch (e) { ziel = null; }
  }
  if (istTextfeld(ziel) && sichtbar(ziel)) {
    const r = hole(ziel, "fokussiertes Textfeld");
    if (r) return r;
  } else if (istEditierbar(ziel)) {
    const r = hole(ziel, "fokussierter Editor");
    if (r) return r;
  }

  // ── 2. Bekannte Kommentarfelder – gleiche Reihenfolge wie beim Einfuegen ──
  const editorSelektoren = [
    "#comment-wiki-edit [contenteditable='true']",
    ".jira-editor-container [contenteditable='true']",
    ".ak-editor-content-area [contenteditable='true']",   // Jira Cloud
    "[data-testid='comment'] [contenteditable='true']",
    "form [contenteditable='true']",
    "[contenteditable='true']",
  ];
  for (const sel of editorSelektoren) {
    for (const el of document.querySelectorAll(sel)) {
      if (!sichtbar(el)) { diagnose.push(sel + " (unsichtbar)"); continue; }
      const r = hole(el, sel);
      if (r) return r;
    }
  }

  for (const rahmen of document.querySelectorAll("iframe")) {
    let koerper = null;
    try { koerper = rahmen.contentDocument && rahmen.contentDocument.body; }
    catch (e) { continue; }                      // fremde Herkunft
    if (!koerper) continue;
    const editierbar = koerper.isContentEditable
      || koerper.getAttribute("contenteditable") === "true"
      || (rahmen.contentDocument.designMode || "").toLowerCase() === "on";
    if (!editierbar || !sichtbar(rahmen)) continue;
    const r = hole(koerper, "iframe#" + (rahmen.id || "?"));
    if (r) return r;
  }

  for (const sel of ["#comment", "textarea[name='comment']",
                     "#jira-issue-comment textarea", ".issue-comment textarea",
                     "textarea.wiki-editor", "form textarea"]) {
    for (const el of document.querySelectorAll(sel)) {
      if (!sichtbar(el)) { diagnose.push(sel + " (unsichtbar)"); continue; }
      const r = hole(el, "textarea " + sel);
      if (r) return r;
    }
  }

  // ── 3. Nichts gefunden: sagen, WAS der Fall war ───────────────────────────
  // Die beiden Faelle brauchen verschiedene Antworten: "leer" ist ein
  // Bedienfehler mit klarem Weg, "nicht gefunden" ein Fund fuer die Fehlersuche.
  return {
    ok: false,
    leer: leerGesehen,
    tinymce_moeglich: document.querySelectorAll("iframe").length > 0
      || !!document.querySelector(".wiki-edit, .jira-editor-container, #comment"),
    gesehen: diagnose.slice(0, 8),
    fehler: leerGesehen
      ? "Das Kommentarfeld ist leer. Schreibe deinen Entwurf hinein und "
        + "versuche es erneut."
      : "Auf dieser Seite wurde kein Kommentarfeld gefunden. Klicke IN das "
        + "Kommentarfeld in Jira und versuche es erneut.",
  };
}


/* Zweiter Versuch – laeuft mit `world: "MAIN"` IM SEITENKONTEXT.
 *
 * Nur so ist die Editor-API der Seite erreichbar (`window.tinymce`, das Jira
 * fuer den Rich-Text-Editor benutzt, bzw. AJS). Aus der isolierten Welt sind
 * diese Objekte nicht sichtbar – das ist keine Einstellung, sondern die
 * Trennung, auf der Content-Scripts beruhen.
 *
 * ⚠ Dieser Weg wird NUR benutzt, wenn der erste scheitert: Code im
 * Seitenkontext kann von der Seite beobachtet werden und teilt sich ihren
 * globalen Namensraum. Er schreibt ausschliesslich Text, den der Benutzer
 * gerade freigegeben hat, und liest nichts.
 */
export function einfuegenUeberEditorApi(text) {
  "use strict";
  try {
    const tm = window.tinymce || (window.tinyMCE);
    if (tm && tm.activeEditor) {
      /* `setContent` ERSETZT, `insertContent` haengt an der Cursorposition an.
       * Genommen wird setContent: „Als Kommentar uebernehmen" ersetzt den
       * vorhandenen Inhalt, und dieser Weg muss dasselbe tun wie die uebrigen –
       * ein Knopf mit editorabhaengiger Wirkung ist nicht erklaerbar. */
      const html = text.split(/\n{2,}/).map(function (p) {
        const d = document.createElement("p");
        d.textContent = p.replace(/\n/g, " ");
        return d.outerHTML;
      }).join("");
      tm.activeEditor.setContent(html);
      return { ok: true, weg: "tinymce.setContent" };
    }
    if (tm && tm.editors && tm.editors.length) {
      tm.editors[0].setContent(text.replace(/\n/g, "<br>"));
      return { ok: true, weg: "tinymce.editors[0]" };
    }
  } catch (e) {
    return { ok: false, fehler: "Editor-API meldet: " + (e && e.message || e) };
  }
  return { ok: false, fehler: "Die Seite hat keinen erreichbaren Editor." };
}


/* Der Lese-Weg ueber die Editor-API – ebenfalls `world: "MAIN"`.
 *
 * Gleiche Begruendung wie beim Schreiben: bei einem TinyMCE-Editor haengt der
 * Inhalt nicht am DOM-Knoten, den die isolierte Welt sieht. `format: "text"`
 * liefert den Text mit Absaetzen statt HTML – der Server soll den Entwurf
 * ueberarbeiten, nicht Markup.
 */
export function lesenUeberEditorApi() {
  "use strict";
  try {
    const tm = window.tinymce || (window.tinyMCE);
    const ed = tm && (tm.activeEditor || (tm.editors && tm.editors[0]));
    if (ed) {
      const t = String(ed.getContent({ format: "text" }) || "")
        .replace(/\r/g, "").replace(/\n{3,}/g, "\n\n").trim();
      if (!t) {
        return { ok: false, leer: true,
                 fehler: "Das Kommentarfeld ist leer. Schreibe deinen Entwurf "
                       + "hinein und versuche es erneut." };
      }
      return { ok: true, weg: "tinymce.getContent", text: t };
    }
  } catch (e) {
    return { ok: false, fehler: "Editor-API meldet: " + (e && e.message || e) };
  }
  return { ok: false, fehler: "Die Seite hat keinen erreichbaren Editor." };
}
