/* Wird per scripting.executeScript in die Jira-Seite injiziert – NUR auf Klick.
 *
 * Deshalb `activeTab` statt eines Content-Scripts mit `https://*​/*`: ein
 * dauerhaft injiziertes Skript verlangt bei der Installation "Alle deine Daten
 * auf allen Websites lesen und ändern". Für einen Knopf, den jemand bewusst
 * drückt, ist das eine Berechtigung zu viel.
 *
 * ⚠ DIESER TEIL IST GEGEN EIN ECHTES JIRA UNGEPRÜFT. Jira Server/DC liefert je
 * nach Version und Konfiguration ein <textarea> (Wiki-Editor), einen TinyMCE in
 * einem iframe oder ein contenteditable. Deshalb mehrere Wege UND ein
 * Rückfall, der nichts kaputtmacht: findet sich kein Feld, landet der Text in
 * der Zwischenablage und der Benutzer bekommt das gesagt. Ein Einfügen, das
 * still ins Leere greift, wäre der schlechtere Ausgang.
 */

/* WICHTIG: Diese Funktion wird von `scripting.executeScript({func, args})`
 * SERIALISIERT (per toString) und in der Seite neu ausgewertet. Sie darf
 * deshalb NICHTS aus ihrem Modul benutzen – keine Importe, keine Konstanten von
 * ausserhalb, keine Closure-Variablen. Alle Helfer stehen absichtlich INNEN.
 * Wer hier etwas herauszieht, bekommt in der Seite ein `ReferenceError`, das
 * im Popup als "Einfügen fehlgeschlagen" ankommt.
 */
export function einfuegenInJira(text) {
  "use strict";

  /** Setzt einen Wert so, dass auch React/Angular ihn mitbekommen.
   *
   * Ein blosses `el.value = x` aktualisiert das DOM, aber nicht den Zustand
   * eines Frameworks – beim Absenden waere das Feld dann wieder leer. Der
   * native Setter plus ein gebubbeltes `input` ist der Weg, der in beiden
   * Welten funktioniert.
   */
  function setzeWert(el, wert) {
    const proto = (el.tagName === "TEXTAREA")
      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value");
    if (setter && setter.set) { setter.set.call(el, wert); } else { el.value = wert; }
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function sichtbar(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  // Reihenfolge = Wahrscheinlichkeit. `#comment` ist das Kommentarfeld von Jira
  // Server/DC im klassischen Editor und damit der häufigste Fall im Haus.
  const kandidaten = [
    "#comment",
    "textarea[name='comment']",
    "#jira-issue-comment textarea",
    ".issue-comment textarea",
    "textarea.wiki-editor",
  ];

  for (const sel of kandidaten) {
    const el = document.querySelector(sel);
    if (el && sichtbar(el)) {
      setzeWert(el, text);
      el.focus();
      try { el.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (e) {}
      return { ok: true, weg: "textarea " + sel };
    }
  }

  // TinyMCE (Rich-Text-Editor von Jira Server) lebt in einem iframe.
  for (const rahmen of document.querySelectorAll("iframe.mce-edit-area, iframe[id$='_ifr']")) {
    try {
      const doc = rahmen.contentDocument;
      const koerper = doc && doc.body;
      if (koerper && koerper.isContentEditable && sichtbar(rahmen)) {
        // Absätze statt \n: in einem HTML-Editor wäre der Text sonst ein Block.
        koerper.innerHTML = text.split(/\n{2,}/)
          .map(function (p) {
            const d = doc.createElement("p");
            // textContent, nicht innerHTML – der Vorschlagstext ist Modelltext
            // und darf kein Markup einschleusen.
            d.textContent = p.replace(/\n/g, " ");
            return d.outerHTML;
          }).join("");
        koerper.dispatchEvent(new Event("input", { bubbles: true }));
        return { ok: true, weg: "TinyMCE" };
      }
    } catch (e) { /* fremdes iframe – weitersuchen */ }
  }

  // Letzter Versuch: ein sichtbares contenteditable (Jira Cloud, ProseMirror).
  for (const el of document.querySelectorAll("[contenteditable='true']")) {
    if (sichtbar(el)) {
      el.focus();
      const ok = document.execCommand && document.execCommand("insertText", false, text);
      if (ok) return { ok: true, weg: "contenteditable" };
      el.textContent = text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return { ok: true, weg: "contenteditable (ohne execCommand)" };
    }
  }

  return {
    ok: false,
    fehler: "Auf dieser Seite wurde kein Kommentarfeld gefunden. Öffne das " +
            "Kommentarfeld in Jira und versuche es erneut – oder benutze " +
            "„Kopieren“.",
  };
}
