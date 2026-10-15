using AiMouse.Configuration;

namespace AiMouse.Start;

/// <summary>Bildet die zwei Start-Einstellungen auf Verknuepfungen ab:
/// Tastenkombination (Startmenue) und „mit Windows starten" (Autostart).
///
/// ⚠ HIER LIEGT DIE VERDRAHTUNG, NICHT DIE ENTSCHEIDUNG. Ob eine Kombination
/// zulaessig ist, sagt <see cref="HotkeyWort"/>; wie man eine .lnk schreibt,
/// sagt <see cref="Verknuepfung"/>. Diese Klasse beantwortet nur: welche Datei
/// muss es geben, welche nicht.
///
/// ⚠ IMMER BEIDE WEGE ANFASSEN, AUCH DEN ABGESCHALTETEN. Wer nur anlegt, was
/// eingeschaltet ist, laesst beim Ausschalten die alte Verknuepfung liegen –
/// und die startet weiter. Eine Einstellung, die sich nicht zuruecknehmen
/// laesst, ist schlimmer als eine, die es nie gab.
/// </summary>
internal static class Startwege
{
    /// <summary>Pfad der laufenden Anwendung; leer, wenn er nicht zu
    /// ermitteln ist (dann kann keine Verknuepfung entstehen).</summary>
    public static string ExePfad => Environment.ProcessPath ?? string.Empty;

    /// <summary>Setzt beide Verknuepfungen auf den Stand der Einstellungen.
    ///
    /// ⚠ ES WIRD BEI JEDEM AUFRUF NEU GESCHRIEBEN, nicht nur bei Aenderung.
    /// Das ist Absicht: der Pfad in der .lnk zeigt auf die Exe, und die kann
    /// verschoben oder (beim Update) ersetzt worden sein. Neu schreiben heilt
    /// das; pruefen muesste dafuer `GetPath` lesen und waere teurer als die
    /// Heilung selbst.
    /// </summary>
    /// <returns>Fehlertext oder <c>null</c>. Beide Wege werden versucht, auch
    /// wenn der erste scheitert – sonst haengt der Autostart daran, dass die
    /// Tastenkombination gelingt.</returns>
    public static string? Anwenden(AppSettings s)
    {
        string exe = ExePfad;
        if (exe.Length == 0)
        {
            return "Der Pfad der Anwendung ist nicht zu ermitteln.";
        }

        string marke = string.IsNullOrWhiteSpace(s.Marke) ? "AI Mouse" : s.Marke;
        string? f1 = HotkeyAnwenden(s, exe, marke);
        string? f2 = AutostartAnwenden(s, exe, marke);

        // Beide Meldungen behalten: „der Autostart ging nicht" und „die
        // Tastenkombination ging nicht" sind verschiedene Befunde, und wer nur
        // den ersten sieht, sucht am falschen Ende.
        if (f1 is not null && f2 is not null) { return f1 + " / " + f2; }
        return f1 ?? f2;
    }

    private static string? HotkeyAnwenden(AppSettings s, string exe, string marke)
    {
        string pfad = Verknuepfung.StartmenuePfad(marke);
        (int mod, int vk) = HotkeyWort.AusText(s.StartHotkey);
        ushort wort = HotkeyWort.Bauen(mod, vk);

        if (wort == HotkeyWort.Keiner)
        {
            // Kein Hotkey eingestellt (oder ein unbrauchbarer Wert in der
            // Registry) – dann darf auch keine Verknuepfung stehenbleiben, die
            // noch einen alten traegt.
            return Verknuepfung.Entfernen(pfad);
        }

        return Verknuepfung.Schreiben(pfad, exe, wort, Beschreibung(marke));
    }

    private static string? AutostartAnwenden(AppSettings s, string exe, string marke)
    {
        string pfad = Verknuepfung.AutostartPfad(marke);

        // ⚠ OHNE HOTKEY: die Autostart-Verknuepfung traegt bewusst KEINEN –
        //   zwei Verknuepfungen mit derselben Kombination waeren ein Konflikt,
        //   den Windows nicht aufloest, und welche gewinnt, waere Zufall.
        return s.MitWindowsStarten
            ? Verknuepfung.Schreiben(pfad, exe, HotkeyWort.Keiner, Beschreibung(marke))
            : Verknuepfung.Entfernen(pfad);
    }

    private static string Beschreibung(string marke)
        => marke + " – von der Anwendung angelegt (Einstellungen → Start).";
}
