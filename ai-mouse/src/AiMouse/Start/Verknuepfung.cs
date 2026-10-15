using System.Runtime.InteropServices;

namespace AiMouse.Start;

/// <summary>Schreibt und entfernt Windows-Verknuepfungen (<c>.lnk</c>).
///
/// ⚠ WARUM ES DIESE KLASSE UEBERHAUPT GIBT – und warum der naheliegende Weg
/// NICHT funktioniert: eine Tastenkombination, die ein NICHT LAUFENDES Programm
/// startet, laesst sich nicht aus dem Programm heraus registrieren.
/// `RegisterHotKey` braucht einen laufenden Prozess mit Fenster. Was das kann,
/// ist die Windows-Shell: eine Verknuepfung traegt ein Hotkey-Feld, und Windows
/// startet daraufhin ihr Ziel. Also legt die Anwendung eine solche Verknuepfung
/// an, statt selbst auf Tasten zu lauschen.
///
/// ⚠ DIE TRAGENDE BEDINGUNG STEHT IN KEINER API-DOKU: der Hotkey wirkt NUR,
/// wenn die .lnk im STARTMENUE oder auf dem DESKTOP liegt. Anderswo laesst sie
/// sich speichern und tut nichts. Deshalb <see cref="StartmenuePfad"/> – ein
/// frei waehlbarer Ablageort waere eine Einstellung, die stillschweigend
/// wirkungslos bleibt.
///
/// ⚠ DIE GUIDS UND DIE VTABLE-REIHENFOLGE SIND VERIFIZIERT (shobjidl_core.idl),
/// NICHT aus der Learn-Seite abgeschrieben: DIE LISTET ALPHABETISCH
/// (`GetArguments` zuerst) und ist als vtable-Quelle wertlos. Dieselbe Falle wie
/// in <c>ZiehbarPruefer</c>, und sie ist hier groesser, weil die gebrauchte
/// Methode `SetPath` an 18. Stelle steht:
///
///   ShellLink (coclass)  00021401-0000-0000-C000-000000000046
///   IShellLinkW          000214F9-0000-0000-C000-000000000046
///     SetDescription        =  5.   SetHotkey = 11.   SetPath = 18.
///     SetWorkingDirectory   =  7.
///   IPersistFile         0000010B-0000-0000-C000-000000000046
///     Save                  =  4.  (1 = GetClassID, geerbt von IPersist)
///
/// Ein falsch nummeriertes Interface UEBERSETZT FEHLERFREI und ruft zur Laufzeit
/// die falsche Funktion – der Fehler kaeme erst am Arbeitsplatz.
/// </summary>
internal static class Verknuepfung
{
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellLinkW
    {
        // 1–4: nicht benutzt. Ihre ANZAHL haelt die vtable-Positionen darunter
        // richtig – die Signaturen duerfen vereinfacht sein, solange niemand
        // sie aufruft.
        void GetPath();
        void GetIDList();
        void SetIDList();
        void GetDescription();

        // 5.
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);

        // 6.
        void GetWorkingDirectory();

        // 7.
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);

        void GetArguments();     //  8.
        void SetArguments();     //  9.
        void GetHotkey();        // 10.

        // 11.
        void SetHotkey(ushort wHotkey);

        void GetShowCmd();       // 12.
        void SetShowCmd();       // 13.
        void GetIconLocation();  // 14.
        void SetIconLocation();  // 15.
        void SetRelativePath();  // 16.
        void Resolve();          // 17.

        // 18.
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
    }

    [ComImport, Guid("0000010B-0000-0000-C000-000000000046"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPersistFile
    {
        void GetClassID();   // 1. (geerbt von IPersist)
        void IsDirty();      // 2.
        void Load();         // 3.

        // 4.
        void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName,
                  [MarshalAs(UnmanagedType.Bool)] bool fRemember);
    }

    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    private class ShellLink
    {
    }

    /// <summary>Ordner, in dem ein Hotkey ueberhaupt wirkt (Startmenue des
    /// angemeldeten Benutzers – kein Administratorrecht noetig).</summary>
    public static string StartmenuePfad(string name)
        => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Programs),
            Dateiname(name));

    /// <summary>Autostart-Ordner des angemeldeten Benutzers.
    ///
    /// Bewusst der ORDNER und nicht der Registry-Schluessel `…\CurrentVersion\Run`:
    /// der Ordner ist fuer den Benutzer sichtbar und ohne Werkzeug wieder
    /// auszuraeumen – ein Autostart, den man nur mit `regedit` findet, ist eine
    /// Zumutung. Ausserdem ist es derselbe Mechanismus wie beim Hotkey, also
    /// eine Technik statt zweier.
    /// </summary>
    public static string AutostartPfad(string name)
        => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Startup),
            Dateiname(name));

    /// <summary>Legt die Verknuepfung an bzw. schreibt sie neu.
    ///
    /// ⚠ SIE WIRD IMMER VOLLSTAENDIG NEU GESCHRIEBEN, nie gelesen und geaendert.
    /// Damit ist der Aufruf idempotent und heilt nebenbei den Fall, dass die
    /// Exe verschoben wurde und die alte Verknuepfung ins Leere zeigt – ohne
    /// dass dafuer `GetPath` (1.) und sein `StringBuilder`-Marshalling noetig
    /// waeren.
    /// </summary>
    /// <param name="hotkey">Hotkey-Wort, <see cref="HotkeyWort.Keiner"/> = keiner.</param>
    /// <returns>Fehlertext oder <c>null</c> bei Erfolg.</returns>
    public static string? Schreiben(string pfad, string ziel, ushort hotkey, string beschreibung)
    {
        try
        {
            string? ordner = Path.GetDirectoryName(pfad);
            if (!string.IsNullOrEmpty(ordner))
            {
                Directory.CreateDirectory(ordner);
            }

            var link = (IShellLinkW)new ShellLink();
            link.SetPath(ziel);

            string? arbeitsverzeichnis = Path.GetDirectoryName(ziel);
            if (!string.IsNullOrEmpty(arbeitsverzeichnis))
            {
                link.SetWorkingDirectory(arbeitsverzeichnis);
            }

            if (!string.IsNullOrWhiteSpace(beschreibung))
            {
                // Der Explorer zeigt das als Kommentar der Verknuepfung – die
                // einzige Stelle, an der jemand erfaehrt, woher sie kommt.
                link.SetDescription(Kuerzen(beschreibung, 260));
            }

            link.SetHotkey(hotkey);

            ((IPersistFile)link).Save(pfad, true);
            return null;
        }
        catch (Exception e)
        {
            return e.Message;
        }
    }

    /// <summary>Entfernt die Verknuepfung. Eine nicht vorhandene Datei ist kein
    /// Fehler – „soll weg" und „ist schon weg" sind derselbe Wunsch.</summary>
    public static string? Entfernen(string pfad)
    {
        try
        {
            if (File.Exists(pfad))
            {
                File.Delete(pfad);
            }
            return null;
        }
        catch (Exception e)
        {
            return e.Message;
        }
    }

    public static bool Existiert(string pfad)
    {
        try
        {
            return File.Exists(pfad);
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>Macht aus der Hausmarke einen brauchbaren Dateinamen.
    ///
    /// Die Marke ist frei konfigurierbar und kann alles enthalten – ein
    /// `\` oder `:` darin ergaebe einen Pfad statt eines Namens.
    /// </summary>
    private static string Dateiname(string name)
    {
        string roh = string.IsNullOrWhiteSpace(name) ? "AI Mouse" : name.Trim();
        foreach (char c in Path.GetInvalidFileNameChars())
        {
            roh = roh.Replace(c, '_');
        }
        roh = roh.Trim().TrimEnd('.');
        return (roh.Length == 0 ? "AI Mouse" : Kuerzen(roh, 80)) + ".lnk";
    }

    private static string Kuerzen(string s, int max)
        => s.Length <= max ? s : s[..max];
}
