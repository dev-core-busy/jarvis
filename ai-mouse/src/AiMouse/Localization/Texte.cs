using AiMouse.Configuration;

namespace AiMouse.Localization;

/// <summary>Oberflaechentexte in Deutsch und Englisch.
///
/// WARUM EINE EIGENE TABELLE UND NICHT .resx: die Anwendung ist EINE portable
/// Exe ohne Installation – Satellitenassemblies waeren zusaetzliche Dateien
/// neben der Exe, die beim Kopieren verlorengehen. Die Tabelle liegt im
/// Programm und kann nicht fehlen.
///
/// WARUM NICHT DIE SYSTEMSPRACHE: die Sprache kommt vom Server – sie wird beim
/// Paketbau EINKOMPILIERT (`Vorgaben.Sprache`) – so bekommt ein Haus mit englischer
/// Oberflaeche das Paket auf Englisch, unabhaengig davon, wie der einzelne
/// Arbeitsplatz eingestellt ist. Der Benutzer kann sie im Einstellungsdialog
/// umstellen.
///
/// ⚠ FEHLT EIN SCHLUESSEL, GILT DEUTSCH – nie ein leerer Text. Eine leere
/// Beschriftung ist von einem kaputten Fenster nicht zu unterscheiden.
/// </summary>
internal static class Texte
{
    private static bool _englisch;

    /// <summary>Aus den Einstellungen uebernehmen. Alles ausser "en" ist Deutsch.</summary>
    public static void Anwenden(AppSettings settings)
    {
        _englisch = (settings.Sprache ?? string.Empty)
            .Trim().StartsWith("en", StringComparison.OrdinalIgnoreCase);
    }

    public static bool IstEnglisch => _englisch;

    /// <summary>Der eine Zugriff. <paramref name="de"/> ist zugleich der Rueckfall.</summary>
    public static string T(string de, string en) => _englisch ? en : de;

    // ── Anmeldung ───────────────────────────────────────────────────────────
    public static string AnmeldenTitel => T("Anmelden", "Sign in");
    public static string Benutzername => T("Benutzername", "User name");
    public static string Kennwort => T("Kennwort", "Password");
    public static string Gespeichert => T("Einstellungen gespeichert.", "Settings saved.");
    public static string Angemeldet => T("Angemeldet. Deine Fragen sind geladen.",
                                         "Signed in. Your questions have been loaded.");
    public static string EinmalCode => T("Einmal-Code (2FA)", "One-time code (2FA)");
    public static string Anmelden => T("Anmelden", "Sign in");
    public static string Abbrechen => T("Abbrechen", "Cancel");
    public static string AnmeldungLaeuft => T("Anmeldung läuft…", "Signing in…");
    public static string KeinServer => T(
        "Es ist keine Serveradresse hinterlegt. Trage sie unter „Einstellungen“ ein.",
        "No server address configured. Enter it under “Settings”.");
    public static string AnmeldungFehlt => T(
        "Bitte zuerst anmelden.", "Please sign in first.");

    // ── Geste und Auswertung ────────────────────────────────────────────────
    public static string Auswerten => T("Wird ausgewertet…", "Analysing…");
    public static string Ergebnis => T("Ergebnis", "Result");
    public static string Kopieren => T("Kopieren", "Copy");
    public static string Schliessen => T("Schließen", "Close");
    public static string EigeneFrage => T("Eigene Frage…", "Custom question…");
    public static string EigeneFrageTitel => T(
        "Was soll mit dem Ausschnitt geschehen?",
        "What should happen with this region?");
    public static string Nachgeschlagen => T(
        "Für diese Antwort wurde zusätzlich nachgeschlagen: ",
        "Additional sources were consulted for this answer: ");

    // ── Tray ────────────────────────────────────────────────────────────────
    public static string Einstellungen => T("Einstellungen…", "Settings…");
    public static string FragenBearbeiten => T("Fragen bearbeiten…", "Edit questions…");
    public static string Abmelden => T("Abmelden", "Sign out");
    public static string Beenden => T("Beenden", "Exit");
    public static string TrayHinweis => T(
        "Rechte Maustaste halten und einen Rahmen aufziehen.",
        "Hold the right mouse button and drag a frame.");

    // ── Einstellungen ───────────────────────────────────────────────────────
    public static string Serveradresse => T("Serveradresse", "Server address");
    public static string Sprache => T("Sprache", "Language");
    public static string Ziehschwelle => T("Ziehschwelle (Pixel)", "Drag threshold (pixels)");
    public static string Zeitlimit => T("Zeitlimit (Sekunden)", "Timeout (seconds)");
    public static string ErgebnisKopieren => T(
        "Ergebnis sofort in die Zwischenablage", "Copy result to clipboard immediately");
    public static string Speichern => T("Speichern", "Save");
    public static string VerbindungTesten => T("Verbindung testen", "Test connection");
    public static string VerbindungOk => T("Verbindung steht.", "Connection works.");

    /// <summary>Der Test ohne Kennwort bei fremder Adresse bzw. ohne Sitzung.
    ///
    /// Sie sagt, WAS zu tun ist – „nicht angemeldet" allein waere richtig und
    /// nutzlos (Projektregel).</summary>
    public static string KennwortFehlt => T(
        "Trage dein Kennwort ein, dann kann die Verbindung geprüft werden.",
        "Enter your password so the connection can be checked.");

    // ── Fehler ──────────────────────────────────────────────────────────────
    public static string FehlerTitel => T("Fehler", "Error");
    public static string KeineAntwort => T(
        "Der Server hat keine Antwort geliefert.", "The server returned no answer.");
    public static string NichtErreichbar => T(
        "Der Server ist nicht erreichbar: ", "The server cannot be reached: ");
    public static string Abgelaufen => T(
        "Die Anmeldung ist abgelaufen. Bitte erneut anmelden.",
        "Your session has expired. Please sign in again.");
    public static string KeineFreigabe => T(
        "Dein Konto ist für AI Mouse nicht freigeschaltet. Ein Administrator "
            + "trägt es unter Sicherheit → Berechtigungen ein.",
        "Your account is not enabled for AI Mouse. An administrator can add it "
            + "under Security → Permissions.");
}
