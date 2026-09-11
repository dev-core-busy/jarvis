using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;

namespace AiMouse.Update;

/// <summary>Stille Selbstaktualisierung der Anwendung (ab 1.0.0, 2026-09-11).
///
/// ⚠ ZWEI SCHRITTE, UND DIE TRENNUNG IST DER GANZE ENTWURF:
///
///   1. <see cref="PruefenUndHolenAsync"/> – im Hintergrund, nach der
///      Anmeldung. Vergleicht die Version und legt bei Bedarf die neue EXE als
///      <c>AiMouse.exe.neu</c> DANEBEN. Kein Neustart, kein Dialog, kein
///      Flackern; der Benutzer merkt nichts.
///   2. <see cref="BeimStartEinwechseln"/> – beim naechsten Programmstart, als
///      ERSTES. Benennt um und startet neu.
///
/// WARUM NICHT SOFORT ERSETZEN UND NEU STARTEN: eine laufende Windows-EXE kann
/// sich nicht selbst ueberschreiben, also muesste sie sich beenden. Genau das
/// ist nicht still – ein offenes Ergebnisfenster waere weg, eine laufende
/// Auswertung abgebrochen, und das Tray-Symbol verschwindet fuer einen Moment
/// ohne erkennbaren Grund. Beim Programmstart ist dagegen nichts zu verlieren:
/// dort dauert der Wechsel Millisekunden, und die Anwendung erscheint einfach
/// einmal im Tray. Der Preis ist, dass eine neue Fassung erst beim naechsten
/// Start gilt – bei einem Autostart-Programm also am naechsten Arbeitstag.
///
/// ⚠ WAS HIER GELADEN WIRD, IST AUSFUEHRBARER CODE. Getragen wird das von zwei
/// Dingen, und beide muessen bleiben: die Verbindung ist TLS-geprueft (der
/// Client benutzt den Standard-HttpClient OHNE abgeschaltete
/// Zertifikatspruefung – gemessen, nicht angenommen), und der Abruf braucht
/// ein gueltiges Sitzungstoken. Damit ist das Vertrauensniveau dasselbe wie
/// beim Download von Hand aus dem Portal; ein neues Risiko entsteht nicht.
/// Wer hier je eine Ausnahme fuer ein selbst ausgestelltes Zertifikat einbaut,
/// macht daraus einen Weg zur Codeausfuehrung ueber einen Man-in-the-Middle.
/// </summary>
internal static class Aktualisierung
{
    /// <summary>Die neue Fassung liegt unter diesem Namen daneben.</summary>
    private const string NeuSuffix = ".neu";

    /// <summary>Die verdraengte Fassung – eine laufende EXE laesst sich
    /// UMBENENNEN, aber nicht loeschen. Aufgeraeumt wird beim naechsten Start.
    /// </summary>
    private const string AltSuffix = ".alt";

    /// <summary>Version dieser laufenden Anwendung (aus der Assembly).</summary>
    public static Version Eigene =>
        Assembly.GetExecutingAssembly().GetName().Version ?? new Version(0, 0);

    /// <summary>Dieselbe Version ZUM ANZEIGEN – dreiteilig, wie die csproj.
    ///
    /// ⚠ NICHT <c>Eigene.ToString()</c>: die Assembly traegt vier Teile
    /// ("1.0.2.0"), der Server nennt in <c>/api/ai-mouse/health</c> drei
    /// ("1.0.2"). Wer beides nebeneinander liest, haelt zwei Schreibweisen
    /// derselben Zahl fuer zwei verschiedene Staende – und genau diese Frage
    /// soll die Anzeige ja beantworten.
    ///
    /// ⚠ <c>Build</c> IST -1, WENN NICHT GESETZT (<c>new Version(0, 0)</c> –
    /// der Rueckfall oben). Ungeprueft stuende dort "0.0.-1".
    /// </summary>
    public static string EigeneAnzeige
    {
        get
        {
            Version v = Eigene;
            return v.Build >= 0
                ? $"{v.Major}.{v.Minor}.{v.Build}"
                : $"{v.Major}.{v.Minor}";
        }
    }

    /// <summary>Pfad der laufenden EXE – leer, wenn nicht ermittelbar.
    ///
    /// ⚠ NICHT <c>Assembly.Location</c>: bei <c>PublishSingleFile</c> ist das
    /// ein LEERER String (die Assembly liegt im Bundle, nicht auf Platte). Der
    /// Weg, der hier traegt, ist der Prozesspfad.
    /// </summary>
    public static string EigenerPfad
    {
        get
        {
            try
            {
                return Environment.ProcessPath ?? string.Empty;
            }
            catch (Exception)
            {
                return string.Empty;
            }
        }
    }

    /// <summary>Vergleicht zwei Versionsangaben. <c>true</c> = Ziel ist neuer.
    ///
    /// ⚠ ZAHLEN, KEINE ZEICHENKETTEN: "0.10.0" ist neuer als "0.9.0", als Text
    /// aber kleiner – der Hinweis blieb dann genau dann aus, wenn er am
    /// dringendsten waere (im Projekt bei der Jira-Erweiterung schon einmal
    /// bezahlt).
    ///
    /// ⚠ UND AUF VIER TEILE NORMIERT: der Server liest "1.0.0" aus der
    /// csproj, die Assembly meldet "1.0.0.0". <see cref="Version"/> setzt
    /// fehlende Teile auf -1, damit waere 1.0.0 KLEINER als 1.0.0.0 und jeder
    /// Start wuerde ein Update ausloesen, das nichts aendert – eine
    /// Endlosschleife, die niemand sieht.
    ///
    /// Eine unlesbare oder fehlende Angabe ergibt <c>false</c>: ohne
    /// verlaessliche Nummer wird NICHT aktualisiert.
    /// </summary>
    public static bool IstNeuer(string? ziel, Version eigene)
    {
        if (string.IsNullOrWhiteSpace(ziel))
        {
            return false;
        }

        if (!Version.TryParse(ziel.Trim(), out Version? z) || z is null)
        {
            return false;
        }

        return Normiert(z) > Normiert(eigene);
    }

    private static Version Normiert(Version v) => new(
        Math.Max(v.Major, 0), Math.Max(v.Minor, 0),
        Math.Max(v.Build, 0), Math.Max(v.Revision, 0));

    /// <summary>Liegt eine neue Fassung bereit? Rein lesend, ohne Nebenwirkung.
    ///
    /// ⚠ EIGENE FUNKTION, weil `Program.Main` VOR dem Einwechseln die
    /// Einzelinstanz-Sperre freigeben muss – und das darf nur passieren, wenn
    /// wirklich etwas zu tun ist. Ohne diese Frage waere die Sperre bei JEDEM
    /// Start kurz offen, fuer nichts.
    /// </summary>
    public static bool NeueFassungLiegtBereit()
    {
        try
        {
            string exe = EigenerPfad;
            return exe.Length > 0 && File.Exists(exe + NeuSuffix);
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>Wechselt eine bereitliegende neue Fassung ein und startet neu.
    ///
    /// Rueckgabe <c>true</c> = es wurde neu gestartet, der Aufrufer MUSS sich
    /// beenden. <c>false</c> = nichts zu tun (der Regelfall).
    ///
    /// ⚠ DIE REIHENFOLGE IST DIE SICHERUNG: erst wird die laufende Datei auf
    /// <c>.alt</c> umbenannt (das erlaubt Windows), dann die neue an ihre
    /// Stelle. Schlaegt der zweite Schritt fehl, wird der erste
    /// ZURUECKGENOMMEN – sonst bliebe gar keine EXE stehen und die Anwendung
    /// waere auf diesem Arbeitsplatz endgueltig weg.
    /// </summary>
    public static bool BeimStartEinwechseln()
    {
        string exe = EigenerPfad;
        if (exe.Length == 0)
        {
            return false;
        }

        string neu = exe + NeuSuffix;
        string alt = exe + AltSuffix;

        // Rueckstand des vorigen Wechsels wegraeumen – jetzt laeuft er nicht
        // mehr und ist loeschbar. Schlaegt es fehl, ist das kein Grund,
        // irgendetwas abzubrechen.
        try
        {
            if (File.Exists(alt))
            {
                File.Delete(alt);
            }
        }
        catch (Exception)
        {
            // Egal: eine Datei zu viel neben der EXE stoert nichts.
        }

        if (!File.Exists(neu))
        {
            return false;
        }

        // Eine leere oder winzige Datei ist kein Programm – lieber wegwerfen
        // als einwechseln. Ohne diese Pruefung koennte ein abgebrochener
        // Download die Anwendung unbrauchbar machen.
        try
        {
            if (new FileInfo(neu).Length < 1_000_000)
            {
                File.Delete(neu);
                return false;
            }
        }
        catch (Exception)
        {
            return false;
        }

        try
        {
            File.Move(exe, alt, overwrite: true);
        }
        catch (Exception)
        {
            // Kein Schreibrecht im eigenen Verzeichnis (z. B. Programme-Ordner)
            // – dann bleibt alles, wie es ist.
            return false;
        }

        try
        {
            File.Move(neu, exe, overwrite: true);
        }
        catch (Exception)
        {
            try
            {
                File.Move(alt, exe, overwrite: true);   // ZURUECKNEHMEN
            }
            catch (Exception)
            {
                // Hier ist nichts mehr zu retten; die Meldung kommt vom
                // Betriebssystem beim naechsten Start.
            }

            return false;
        }

        try
        {
            Process.Start(new ProcessStartInfo(exe) { UseShellExecute = true });
            return true;
        }
        catch (Exception)
        {
            // Eingewechselt, aber nicht gestartet: die neue Fassung gilt dann
            // ab dem naechsten Start von Hand. Kein Grund, sich zu beenden.
            return false;
        }
    }

    /// <summary>Prueft die Serverversion und legt die neue Fassung daneben.
    ///
    /// Rueckgabe: kurzer Grund fuer das Journal/den Tray-Titel ("" = nichts
    /// getan). Wirft NIE – ein Fehlschlag darf die Anwendung nicht stoeren,
    /// sie funktioniert ohne Update unveraendert weiter.
    /// </summary>
    public static async Task<string> PruefenUndHolenAsync(
        string? serverVersion, Func<CancellationToken, Task<byte[]>> paketHolen,
        CancellationToken ct)
    {
        try
        {
            if (!IstNeuer(serverVersion, Eigene))
            {
                return string.Empty;
            }

            string exe = EigenerPfad;
            if (exe.Length == 0)
            {
                return string.Empty;
            }

            string neu = exe + NeuSuffix;

            // ⚠ LIEGT SIE SCHON DA, WIRD NICHT ERNEUT GELADEN. Sonst holt jede
            // Anmeldung 66 MB, solange der Benutzer nicht neu startet.
            if (File.Exists(neu))
            {
                return "liegt bereit";
            }

            // Schreibrecht VORHER pruefen – 66 MB zu laden, um dann am
            // Speichern zu scheitern, ist verschwendete Leitung.
            string probe = exe + ".schreibprobe";
            try
            {
                await File.WriteAllBytesAsync(probe, new byte[] { 0 }, ct)
                    .ConfigureAwait(false);
                File.Delete(probe);
            }
            catch (Exception)
            {
                return "kein Schreibrecht";
            }

            byte[] zip = await paketHolen(ct).ConfigureAwait(false);
            if (zip.Length < 1_000_000)
            {
                return "Paket unbrauchbar";
            }

            // ⚠ ZUERST IN EINE NEBENDATEI, DANN UMBENENNEN. Ein abgebrochener
            // Schreibvorgang darf keine halbe `.neu` hinterlassen, die der
            // naechste Start einwechselt.
            string teil = exe + ".teil";
            using (var quelle = new MemoryStream(zip, writable: false))
            using (var archiv = new ZipArchive(quelle, ZipArchiveMode.Read))
            {
                ZipArchiveEntry? eintrag = archiv.Entries.FirstOrDefault(
                    e => e.Name.Equals("AiMouse.exe", StringComparison.OrdinalIgnoreCase));
                if (eintrag is null)
                {
                    return "keine EXE im Paket";
                }

                using Stream drin = eintrag.Open();
                using FileStream raus = File.Create(teil);
                await drin.CopyToAsync(raus, ct).ConfigureAwait(false);
            }

            if (new FileInfo(teil).Length < 1_000_000)
            {
                File.Delete(teil);
                return "EXE unbrauchbar";
            }

            File.Move(teil, neu, overwrite: true);
            return "bereitgelegt";
        }
        catch (Exception e)
        {
            // Aufraeumen, damit kein Rest liegen bleibt – und still bleiben.
            try
            {
                string exe = EigenerPfad;
                if (exe.Length > 0 && File.Exists(exe + ".teil"))
                {
                    File.Delete(exe + ".teil");
                }
            }
            catch (Exception)
            {
                // nichts
            }

            return "Fehlschlag: " + e.GetType().Name;
        }
    }
}
