/* Einfuegen in das Jira-Kommentarfeld.
 *
 * ⚠ DIESE DATEI IST BEWUSST EIN KLASSISCHES SKRIPT, KEIN ES-MODUL. Sie wird an
 * ZWEI Orten geladen, und keiner davon kann `import`:
 *   1. zusammen mit `panel.js` per `scripting.executeScript({files:[...]})` in
 *      die Jira-Seite – dort injizierte Dateien sind immer klassische Skripte,
 *      ein `export` stirbt mit "Unexpected token 'export'";
 *   2. im Hintergrund (Chrome per `importScripts`, Firefox als zweiter Eintrag
 *      in `background.scripts`) – von dort wird `einfuegenUeberEditorApi` per
 *      `executeScript({func})` in die SEITENWELT nachgeschoben.
 * Registriert wird deshalb in `globalThis.__jvEinfuegen`.
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
 *    will, hat vorher ins Kommentarfeld geklickt. Damit funktioniert es auch in
 *    einem Editor, den niemand vorhergesehen hat – und der Benutzer hat die
 *    Kontrolle darueber, WOHIN geschrieben wird.
 *    ⚠ SEIT DEM PANEL MUSS DAS FELD UEBERGEBEN WERDEN (`zielVorgabe`):
 *    das Panel sitzt IN der Seite, also ist `document.activeElement` beim Klick
 *    auf "Einfuegen" der Panel-Wirt und nicht mehr das Kommentarfeld. Ohne den
 *    Parameter waere ausgerechnet die verlaesslichste Regel tot – und zwar
 *    still: es faellt einfach auf die Selektorliste zurueck.
 * 2. EIN FEHLSCHLAG MUSS SAGEN, WAS ER GESEHEN HAT. Ohne Diagnose ist der
 *    naechste Anlauf wieder Raten. Der Rueckgabewert nennt deshalb die
 *    gefundenen Kandidaten.
 * 3. `einfuegenUeberEditorApi` SIEHT `window.tinymce` DER SEITE NICHT, solange
 *    sie in der isolierten Welt laeuft. Sie steht deshalb getrennt und wird vom
 *    Hintergrund mit `world: "MAIN"` nachgeschoben.
 *
 * ⚠ SERIALISIERUNG: `einfuegenUeberEditorApi` wird per toString uebertragen und
 * in der Seite neu ausgewertet. Sie darf NICHTS aus dieser Datei benutzen –
 * keine Helfer von aussen, keine Konstanten. Alles steht innen.
 */
(function (raum) {
  "use strict";

  function einfuegenInJira(text, zielVorgabe) {
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
      // BEIDES pruefen: `isContentEditable` ist die richtige Frage, aber nicht
      // ueberall vorhanden (jsdom kennt es gar nicht, und ein Editor kann das
      // Attribut dynamisch setzen, bevor der Browser die Eigenschaft nachzieht).
      // Das Attribut allein waere zu schwach – deshalb die Oder-Verknuepfung.
      return el.isContentEditable === true
        || (el.getAttribute && el.getAttribute("contenteditable") === "true");
    }

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
      try {
        const aus = el.ownerDocument || document;
        // Ans Ende stellen, damit ein bereits getippter Text nicht ersetzt wird.
        const sel = (aus.defaultView || window).getSelection();
        if (sel && el.contains(sel.anchorNode) === false) {
          const r = aus.createRange();
          r.selectNodeContents(el);
          r.collapse(false);
          sel.removeAllRanges();
          sel.addRange(r);
        }
        if (aus.execCommand && aus.execCommand("insertText", false, txt)) {
          return "insertText";
        }
      } catch (e) { /* weiter mit dem direkten Weg */ }

      const aus = el.ownerDocument || document;
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

    // ── 1. Das zuletzt fokussierte Feld ─────────────────────────────────────
    /* `zielVorgabe` schlaegt `document.activeElement`: das Panel merkt sich das
     * Feld, in dem der Benutzer ZULETZT IN DER SEITE war – nach einem Klick auf
     * einen Knopf des Panels ist `activeElement` der Panel-Wirt.
     * `isConnected` ist Pflicht: eine Jira-Oberflaeche baut ihr DOM neu auf,
     * und in ein herausgeloestes Element zu schreiben waere ein Erfolg, den
     * niemand sieht. */
    let ziel = (zielVorgabe && zielVorgabe.isConnected !== false)
      ? zielVorgabe : document.activeElement;
    // Auch in einem iframe: activeElement des Hauptdokuments ist dann der iframe.
    if (ziel && ziel.tagName === "IFRAME") {
      try { ziel = ziel.contentDocument.activeElement; } catch (e) { ziel = null; }
    }
    if (istTextfeld(ziel) && sichtbar(ziel)) {
      setzeWert(ziel, text);
      ziel.focus();
      return { ok: true, weg: "fokussiertes Textfeld" };
    }
    if (istEditierbar(ziel)) {
      const weg = schreibeEditierbar(ziel, text);
      return { ok: true, weg: "fokussierter Editor (" + weg + ")" };
    }

    // ── 2. Bekannte Kommentarfelder ─────────────────────────────────────────
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
      try {
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
          setzeWert(el, text);
          el.focus();
          try { el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) {}
          return { ok: true, weg: "textarea " + sel };
        }
      }
    }

    // ── 3. Nichts gefunden: sagen, was da war ───────────────────────────────
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


  /* Zweiter Versuch – laeuft mit `world: "MAIN"` IM SEITENKONTEXT.
   *
   * Nur so ist die Editor-API der Seite erreichbar (`window.tinymce`, das Jira
   * fuer den Rich-Text-Editor benutzt, bzw. AJS). Aus der isolierten Welt sind
   * diese Objekte nicht sichtbar – das ist keine Einstellung, sondern die
   * Trennung, auf der Content-Scripts beruhen. Auch das Panel sitzt in der
   * isolierten Welt; es laesst diesen Weg deshalb ueber den Hintergrund
   * nachschieben.
   *
   * ⚠ Dieser Weg wird NUR benutzt, wenn der erste scheitert: Code im
   * Seitenkontext kann von der Seite beobachtet werden und teilt sich ihren
   * globalen Namensraum. Er schreibt ausschliesslich Text, den der Benutzer
   * gerade freigegeben hat, und liest nichts.
   */
  function einfuegenUeberEditorApi(text) {
    "use strict";
    try {
      const tm = window.tinymce || (window.tinyMCE);
      if (tm && tm.activeEditor) {
        // setContent ersetzt, insertContent haengt an der Cursorposition an.
        const html = text.split(/\n{2,}/).map(function (p) {
          const d = document.createElement("p");
          d.textContent = p.replace(/\n/g, " ");
          return d.outerHTML;
        }).join("");
        tm.activeEditor.insertContent(html);
        return { ok: true, weg: "tinymce.insertContent" };
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

  raum.einfuegenInJira = einfuegenInJira;
  raum.einfuegenUeberEditorApi = einfuegenUeberEditorApi;
})(globalThis.__jvEinfuegen = globalThis.__jvEinfuegen || {});
