/* Setzt die Ansichts-Klasse VOR dem ersten Zeichnen.
 *
 * WARUM EINE EIGENE DATEI UND KEIN INLINE-SKRIPT: Erweiterungsseiten laufen
 * unter `script-src 'self'` – ein <script> mit Rumpf im HTML wird von der
 * Content-Security-Policy geblockt, und zwar wortlos. Der im Projekt sonst
 * uebliche Anti-Flacker-Weg (Inline-Skript direkt hinter <body>, siehe die
 * Theme-Umschaltung der Portalseiten) scheidet hier also aus.
 *
 * WARUM UEBERHAUPT SO FRUEH: `popup.js` ist ein Modul und damit aufgeschoben.
 * Wer die Klasse erst dort setzt, laesst die Seitenleiste einen Wimpernschlag
 * lang in der 380 px breiten Popup-Form stehen. Diese Datei ist im <head>
 * synchron eingebunden und damit vor jedem Zeichnen durch.
 *
 * WARUM EIN ABFRAGETEIL UND KEINE ZWEITE HTML-DATEI: eine zweite Datei waere
 * eine Kopie derselben Oberflaeche – und Kopien laufen auseinander. Den Pfad
 * mit `?ansicht=leiste` setzt der Hintergrund beim Einrichten der Leiste
 * (background.js::ansichtAnwenden), NICHT das Manifest: `setOptions`/`setPanel`
 * nehmen einen Abfrageteil nachweislich an, fuer die Manifest-Schluessel
 * `side_panel.default_path` bzw. `sidebar_action.default_panel` ist das nicht
 * belegt. Faellt der Aufruf aus, laedt die Leiste ohne Abfrageteil – dann ist
 * sie 380 px schmal statt fliessend, aber sie funktioniert. Fail-safe in die
 * richtige Richtung.
 */
try {
  if (new URLSearchParams(location.search).get("ansicht") === "leiste") {
    document.documentElement.classList.add("leiste");
  }
} catch (e) {
  /* Ohne Klasse bleibt es bei der Popup-Breite – unschoen, nicht kaputt. */
}
