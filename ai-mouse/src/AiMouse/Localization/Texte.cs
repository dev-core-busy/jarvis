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

        string marke = (settings.Marke ?? string.Empty).Trim();
        _marke = marke.Length > 0 ? marke : Vorgaben.Marke;
    }

    /// <summary>Der Name des Hauses – fuer Fenstertitel und Hinweisblasen.
    ///
    /// ⚠ HIER STAND AN SECHS STELLEN "AI Mouse" FEST IM CODE. Das ist nicht
    /// nur ein uebersehener Text, sondern ein Branding-Fehler: der Titel des
    /// Ergebnisfensters und jede Hinweisblase nannten den Vorgabenamen, waehrend
    /// der Kopf des Dialogs daneben die Hausmarke trug. Die Marke kommt beim
    /// Paketbau vom Server (`Vorgaben.Marke`) und liegt in den Einstellungen –
    /// sie darf an keiner Stelle abgeschrieben werden.
    ///
    /// Rueckfall ist der einkompilierte Wert, nie ein leerer Titel: ein Fenster
    /// ohne Namen ist von einem kaputten nicht zu unterscheiden.
    /// </summary>
    public static string Marke => _marke;

    private static string _marke = Vorgaben.Marke;

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

    /// <summary>Beschriftung der Versionsanzeige im Marken-Kopf.
    ///
    /// ⚠ IN BEIDEN SPRACHEN GLEICH – das ist kein vergessener Eintrag, sondern
    /// dasselbe Wort. Er steht deshalb ausdruecklich in `ERLAUBT_GLEICH` von
    /// `tests/live_texte_dev.py`; die Regel "DE ≠ EN" bleibt fuer alles andere
    /// scharf, weil die Ausnahme einzeln eingetragen und begruendet ist.
    /// </summary>
    public static string Version => T("Version", "Version");
    public static string KeinServer => T(
        "Es ist keine Serveradresse hinterlegt. Trage sie unter „Einstellungen“ ein.",
        "No server address configured. Enter it under “Settings”.");
    public static string AnmeldungFehlt => T(
        "Bitte zuerst anmelden.", "Please sign in first.");

    // ── Geste und Auswertung ────────────────────────────────────────────────
    public static string Auswerten => T("Wird ausgewertet…", "Analysing…");
    public static string Ergebnis => T("Ergebnis", "Result");
    // ⚠ ZWEI KOPIER-KNOEPFE NEBENEINANDER MUESSEN SAGEN, WAS SIE KOPIEREN.
    //   Bis 2026-09-10 hiess dieser schlicht „Kopieren" – das war eindeutig,
    //   solange er allein stand. Neben „Bild kopieren" ist es die Frage, was
    //   der andere denn kopiert.
    public static string Kopieren => T("Text kopieren", "Copy text");
    public static string BildKopierenKnopf => T("Bild kopieren", "Copy image");
    public static string Schliessen => T("Schließen", "Close");
    public static string EigeneFrage => T("Eigene Frage…", "Custom question…");
    public static string EigeneFrageTitel => T(
        "Was soll mit dem Ausschnitt geschehen?",
        "What should happen with this region?");
    public static string Nachgeschlagen => T(
        "Für diese Antwort wurde zusätzlich nachgeschlagen: ",
        "Additional sources were consulted for this answer: ");

    // Adressen in der Antwort sind anklickbar. Geoeffnet wird NUR http/https –
    // der Text stammt aus einem Bildschirmausschnitt, siehe `Ui/LinkZiel.cs`.
    // Die Absage nennt Grund UND Ausweg: ein blauer Link, der beim Klick nichts
    // tut, ist von einem kaputten Fenster nicht zu unterscheiden.
    public static string LinkGeoeffnet => T("Link im Browser geöffnet.",
                                            "Link opened in your browser.");
    public static string LinkNichtGeoeffnet => T(
        "Nur Web-Adressen (http/https) werden geöffnet – diese nicht. Text markieren und kopieren.",
        "Only web addresses (http/https) are opened – this one is not. Select the text and copy it.");
    public static string LinkFehler => T("Link ließ sich nicht öffnen:",
                                         "Could not open the link:");

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
    // Die Beschriftung nennt die WIRKUNG, nicht die Technik: „Rechtsklick
    // durchreichen mit" waere richtig und fuer niemanden verstaendlich.
    //
    // ⚠ „Ziehen nur mit Taste" (Vorgabe 2026-09-11), vorher „Ziehen & Ablegen
    // mit Taste". Der neue Wortlaut ist PARALLEL zu `GesteTaste` darunter
    // („Ausschnitt nur mit Taste") – zwei Felder, die im Dialog untereinander
    // stehen und Gegenstuecke sind, muessen auch gleich gebaut klingen. Die
    // alte Fassung las sich wie ein eigenes Feature („Drag & Ablegen"), nicht
    // wie die Bedingung, die sie beschreibt.
    public static string RechtsziehTaste => T("Ziehen nur mit Taste",
                                              "Drag only with key");
    public static string RdKeine => T("(aus – Rechtsziehen gesperrt)",
                                      "(off – right-drag blocked)");
    public static string RdUmschalt => T("Umschalt", "Shift");

    // ── Gestentaste (Vorgabe 2026-09-10) ───────────────────────────────────
    // Die Beschriftung nennt die WIRKUNG. „Gestentaste" waere richtig und fuer
    // niemanden verstaendlich.
    public static string GesteTaste => T("Ausschnitt nur mit Taste",
                                         "Capture only with key");
    public static string GkKeine => T("(ohne Zusatztaste)", "(no extra key)");
    public static string RdGesperrt => T(
        "Nicht nötig: der Rechtsklick geht ohnehin an die Anwendung.",
        "Not needed: the right-click already goes to the application.");
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
        $"Dein Konto ist für {Marke} nicht freigeschaltet. Ein Administrator "
            + "trägt es unter Sicherheit → Berechtigungen ein.",
        $"Your account is not enabled for {Marke}. An administrator can add it "
            + "under Security → Permissions.");

    // ── Auswahl-Menue ───────────────────────────────────────────────────────
    // Gemeldet 2026-09-10 („die Menüs sind immer noch nicht i18n"): diese zwei
    // Eintraege standen als einzige des Menues hart auf Englisch.
    public static string BildKopieren => T("Bild in die Zwischenablage",
                                           "Copy image to clipboard");
    public static string BildSpeichern => T("Bild speichern unter…", "Save image as…");
    public static string PngFilter => T("PNG-Bild|*.png", "PNG image|*.png");

    // ── Ergebnisfenster ─────────────────────────────────────────────────────
    public static string WarteAufModell => T("Warte auf das Modell…",
                                             "Waiting for the model…");
    public static string AnfrageFehlgeschlagen => T("Anfrage fehlgeschlagen",
                                                    "Request failed");
    // ⚠ DIE MELDUNG NENNT DEN GEGENSTAND: in der Zwischenablage sieht man
    //   nicht, was drin liegt – bei zwei Kopier-Knoepfen ist „kopiert" allein
    //   keine Auskunft.
    public static string InZwischenablage => T("Text in die Zwischenablage kopiert.",
                                               "Text copied to clipboard.");
    public static string BildInZwischenablage =>
        T("Bild in die Zwischenablage kopiert.", "Image copied to clipboard.");

    /// <summary>Zeichenzahl der ANGEZEIGTEN Antwort.
    ///
    /// Gezaehlt wird, was im Fenster steht – also ohne die `**` der
    /// Auszeichnung. Die Zahl soll zu dem passen, was der Benutzer sieht und
    /// beim Kopieren bekommt.</summary>
    public static string Zeichen(int n) => T($"{n} Zeichen", $"{n} characters");

    // ── Meldungen aus dem Tray ──────────────────────────────────────────────
    // Jede nennt den Grund; der technische Text des Systems haengt dahinter.
    public static string AufnahmeFehler => T("Bildschirmaufnahme fehlgeschlagen: ",
                                             "Screen capture failed: ");
    public static string ZwischenablageBelegt => T(
        "Die Zwischenablage ist gerade belegt: ", "The clipboard is busy: ");
    public static string SpeichernFehler => T("Das Bild ließ sich nicht speichern: ",
                                              "Could not save the image: ");
    public static string OeffnenFehler => T("Ließ sich nicht öffnen: ",
                                            "Could not open: ");
    public static string UnerwarteterFehler => T("Unerwarteter Fehler:",
                                                 "Unexpected error:");
    public static string Unbekannt => T("unbekannt", "unknown");

    /// <summary>UIPI hat die Weitergabe des Rechtsklicks abgelehnt.
    ///
    /// Der Klick des Benutzers ist in diesem Fall VERLOREN – die Meldung darf
    /// deshalb nicht still bleiben und muss den Ausweg nennen.</summary>
    public static string KlickNichtWeitergereichtAdmin => T(
        $"Der Rechtsklick ließ sich nicht weiterreichen: das Fenster im Vordergrund "
            + $"läuft mit erhöhten Rechten. Starte {Marke} als Administrator.",
        $"The right-click could not be forwarded: the focused window runs elevated. "
            + $"Start {Marke} as administrator.");
    public static string KlickNichtWeitergereicht => T(
        "Der Rechtsklick ließ sich nicht weiterreichen",
        "The right-click could not be forwarded");

    // ── Eingebaute Fragen (Rueckfall, wenn der Server keine liefert) ────────
    // Der TITEL ist Oberflaeche und wird uebersetzt; der PROMPT geht an das
    // Modell und bleibt englisch – dort ist die Sprache eine Eigenschaft des
    // Auftrags, keine der Anzeige.
    public static string FrageOcr => T("Text erkennen (OCR)", "Extract text (OCR)");
    public static string FrageBeschreiben => T("Bild beschreiben", "Describe image");
    public static string FrageFehler => T("Fehler / Code analysieren",
                                          "Analyse error / code");
}
