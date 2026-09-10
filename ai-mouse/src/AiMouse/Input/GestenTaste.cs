namespace AiMouse.Input;

/// <summary>Modifikatortaste, die den Rechtsklick an die Anwendung DURCHREICHT,
/// statt ihn fuer die Lasso-Geste zu nehmen.
///
/// ⚠ DIE VORGABE IST `Strg` UND NICHT `Keine` – begruendet:
/// ohne eine solche Taste ist Windows' Right-Drag („Datei mit rechter Maustaste
/// ziehen" → Hierher kopieren / verschieben / Verknuepfung erstellen)
/// vollstaendig blockiert, solange AI Mouse laeuft. Das ist eine Funktion des
/// Betriebssystems, die wir nicht stillschweigend abschalten wollen.
///
/// Warum Strg und nicht Alt/Umschalt (alle drei waeren technisch gleich):
///   * `Alt` haelt in vielen Anwendungen die Menueleiste an sich und wird von
///     Fensterverwaltungen zum Verschieben benutzt.
///   * `Umschalt`+Rechtsklick oeffnet im Explorer das ERWEITERTE Kontextmenue
///     („Als Pfad kopieren") – eine benutzte Funktion, die man nicht mit einer
///     zweiten Bedeutung belegen sollte.
///   * `Strg`+Rechtsklick ist dagegen kaum belegt.
/// `Keine` bleibt waehlbar: dann verhaelt sich alles wie vor 2026-09-10.
/// </summary>
internal enum GestenTaste
{
    /// <summary>Kein Durchreichen – jeder Rechtsklick gehoert der Geste.</summary>
    Keine = 0,
    Strg,
    Alt,
    Umschalt,
}
