using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using AiMouse.Configuration;

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

    /// <summary>Die Fassung, die auf dem Server liegt – gesetzt NUR, wenn sie
    /// neuer ist und diese Anwendung sie nicht selbst holen darf (Start von
    /// einer Netzfreigabe). Sonst leer.
    ///
    /// ⚠ ABSCHALTEN OHNE ES ZU SAGEN WAERE DER SCHLECHTERE AUSGANG: der
    /// Benutzer arbeitete sonst monatelang mit einer alten Fassung, und die
    /// einzige Spur waere ein Rueckgabewert, den niemand liest – dieselbe
    /// Lehre wie beim still verschluckten Fragen-Fehlschlag (1.0.9). Den SATZ
    /// baut das Tray-Menue; diese Klasse bleibt textfrei, genau wie
    /// <c>Ui/LinkZiel</c>. Sonst haengt eine Infrastruktur-Klasse an der
    /// Lokalisierung, und die Regel waere nicht mehr ohne UI pruefbar.</summary>
    public static string NetzVersion { get; private set; } = string.Empty;

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

    /// <summary>Laeuft die Anwendung von einer NETZFREIGABE? (2026-09-22)
    ///
    /// ⚠ WARUM DAS DIE SELBSTAKTUALISIERUNG ABSCHALTEN MUSS – und warum es der
    /// gefaehrlichste Fall dieser Klasse ist:
    ///
    /// Seit der Bereitstellung im Netz liegt die EXE auf einer Freigabe, und
    /// die Anleitung sagt ausdruecklich „auf den eigenen Rechner kopieren".
    /// Wer sie trotzdem DIREKT von dort startet, laesst
    /// <see cref="PruefenUndHolenAsync"/> neben der GEMEINSAMEN Datei
    /// arbeiten: die neue Fassung landet als <c>AiMouse.exe.neu</c> auf der
    /// Freigabe, und der naechste Start tauscht sie fuer ALLE aus – ausgeloest
    /// von einem beliebigen Arbeitsplatz, waehrend andere die Datei womoeglich
    /// gerade ausfuehren. Der Administrator verliert damit die Kontrolle
    /// darueber, welcher Stand verteilt wird; genau dafuer hat er die Freigabe.
    ///
    /// ⚠ BEI EINER SCHREIBGESCHUETZTEN FREIGABE WAERE ES NUR STILL: die
    /// Schreibprobe scheitert, es passiert nichts – und der Benutzer arbeitet
    /// monatelang mit einer alten Fassung, ohne es zu erfahren. Deshalb wird
    /// hier nicht nur abgeschaltet, sondern GESAGT (siehe
    /// <see cref="NetzHinweis"/>).
    ///
    /// ⚠ FAIL-SAFE IN RICHTUNG „LOKAL", und das ist eine Abwaegung: ein
    /// faelschlich als Freigabe erkannter Pfad nimmt einer normalen
    /// Installation dauerhaft die Aktualisierung – teurer als der umgekehrte
    /// Fall, weil er jeden Arbeitsplatz trifft statt der wenigen, die von der
    /// Freigabe starten. Der haeufige Fall (UNC, <c>\\server\...</c>) ist
    /// ohnehin an einer Zeichenkette erkennbar und kann nicht fehlschlagen;
    /// nur die Laufwerksabfrage kann werfen, und die faellt dann auf „lokal".
    /// </summary>
    public static bool VonNetzfreigabe() => IstNetzpfad(EigenerPfad);

    /// <summary>Die reine Regel – ohne <see cref="EigenerPfad"/>, damit sie
    /// AUSGEFUEHRT geprueft werden kann.
    ///
    /// ⚠ DIESELBE TRENNUNG WIE BEI <c>ZiehbarRegel</c> GEGEN
    /// <c>ZiehbarPruefer</c>: was an <c>Environment.ProcessPath</c> haengt,
    /// laesst sich nur auf einem Windows-Arbeitsplatz messen – die Entscheidung
    /// selbst dagegen ueberall. Ein Waechter, der nur den Quelltext lesen kann,
    /// beantwortet nicht, was bei <c>\\?\UNC\srv\x</c> herauskommt.
    /// </summary>
    internal static bool IstNetzpfad(string exe)
    {
        if (string.IsNullOrEmpty(exe))
        {
            return false;
        }
        // UNC – der haeufige Fall, reine Zeichenkette, kann nicht scheitern.
        // `\\?\UNC\server\...` ist die lange Form desselben.
        if (exe.StartsWith(@"\\", StringComparison.Ordinal)
            && !exe.StartsWith(@"\\?\", StringComparison.Ordinal))
        {
            return true;
        }
        if (exe.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }
        // Verbundenes Netzlaufwerk (Z:\...). Nur das kann werfen.
        try
        {
            string? wurzel = Path.GetPathRoot(exe);
            if (string.IsNullOrEmpty(wurzel))
            {
                return false;
            }
            return new DriveInfo(wurzel).DriveType == DriveType.Network;
        }
        catch (Exception)
        {
            return false;   // siehe Docstring: fail-safe in Richtung "lokal"
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

    /// <summary>Raeumt die verdraengte Fassung (<c>.alt</c>) weg.
    ///
    /// ⚠ EIGENE METHODE UND BEI JEDEM START GERUFEN – vorher stand das
    /// Loeschen IN <see cref="BeimStartEinwechseln"/>, und das laeuft nur, wenn
    /// eine <c>.neu</c> danebenliegt. Folge: nach dem letzten Update blieb die
    /// alte Fassung fuer immer liegen (im gemeldeten Fall vom 2026-09-14 mit
    /// 64 MB). Der Rueckstand entsteht beim Einwechseln, also gehoert das
    /// Aufraeumen an den Start – nicht an die Bedingung, die zufaellig
    /// daneben stand.
    ///
    /// Schlaegt es fehl (die Datei laeuft noch, Virenscanner haelt sie),
    /// passiert nichts weiter: eine Datei zu viel neben der EXE stoert den
    /// Betrieb nicht, und beim naechsten Start wird es erneut versucht.
    /// </summary>
    public static void RueckstandAufraeumen()
    {
        try
        {
            string exe = EigenerPfad;
            if (exe.Length == 0)
            {
                return;
            }

            string alt = exe + AltSuffix;
            if (File.Exists(alt))
            {
                File.Delete(alt);
            }
        }
        catch (Exception)
        {
            // Siehe Docstring: kein Grund, irgendetwas abzubrechen.
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

        RueckstandAufraeumen();

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

            /* ⚠ VON EINER NETZFREIGABE WIRD NICHT SELBST AKTUALISIERT.
             *
             * Sonst legt ein beliebiger Arbeitsplatz `AiMouse.exe.neu` auf die
             * GEMEINSAME Datei und tauscht sie beim naechsten Start fuer alle
             * aus – waehrend andere sie womoeglich gerade ausfuehren. Welcher
             * Stand verteilt wird, entscheidet der Administrator; genau dafuer
             * gibt es die Freigabe.
             *
             * ⚠ DIE PRUEFUNG STEHT HINTER `IstNeuer`: ohne eine neuere Fassung
             * gibt es nichts zu melden, und ein Hinweis, der bei jedem Start
             * erscheint, wird nach zwei Tagen nicht mehr gelesen. */
            if (VonNetzfreigabe())
            {
                NetzVersion = (serverVersion ?? string.Empty).Trim();
                return "Netzfreigabe";
            }
            NetzVersion = string.Empty;

            string neu = exe + NeuSuffix;

            // ⚠ LIEGT SIE SCHON DA, WIRD NICHT ERNEUT GELADEN. Sonst holt jede
            // Anmeldung 66 MB, solange der Benutzer nicht neu startet.
            if (File.Exists(neu))
            {
                return "liegt bereit";
            }

            /* ⚠ SCHLEIFEN-BREMSE – UND SIE IST DER EIGENTLICHE SCHUTZ HIER
             * (gemeldet 2026-09-14: "es wird JEDESMAL die neue exe auf den
             * Rechner kopiert").
             *
             * Die Pruefung darueber greift nur, SOLANGE `.neu` liegt. Nach dem
             * Einwechseln ist sie weg – und wenn die Anwendung danach trotzdem
             * die alte Fassung ist, faengt alles von vorn an: holen,
             * einwechseln, unveraendert alt, holen. Gemessen wurde genau das:
             * auf Platte lag bereits 1.0.6, im Speicher lief weiter 1.0.5, und
             * zwischen zwei Screenshots im Abstand einer Minute lagen zwei
             * volle Zyklen zu je 66 MB.
             *
             * Ein Update ohne Gedaechtnis ueber den letzten Versuch ist eine
             * Endlosschleife – dieselbe Klasse wie "ein Zeitdeckel ohne
             * Gedaechtnis ist eine wiederkehrende Rechnung" (OneNote, 06.09.),
             * und die Antwort ist dieselbe: den Fehlschlag MERKEN.
             *
             * ⚠ WARUM NICHT AM SYMPTOM GEFLICKT: WARUM die alte Fassung
             * weiterlief, laesst sich von hier aus nicht messen (es gibt kein
             * Windows auf dem Bauserver). Diese Bremse wirkt unabhaengig davon.
             * Sie kostet hoechstens ein verzoegertes Update, verhindert aber
             * die Leitung im Kreis – die Halbfehlerstellungen sind nicht gleich
             * schwer. */
            (string gZiel, string gVon) = ConfigStore.LadeUpdateVersuch();
            string ziel = (serverVersion ?? string.Empty).Trim();
            if (gZiel.Length > 0
                && string.Equals(gZiel, ziel, StringComparison.OrdinalIgnoreCase)
                && string.Equals(gVon, EigeneAnzeige, StringComparison.OrdinalIgnoreCase))
            {
                // Gleiches Ziel, gleiche Ausgangslage: der vorige Versuch hat
                // nichts bewirkt. Ein zweiter aendert daran nichts.
                return "schon versucht";
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

            /* ⚠ GEMERKT WIRD ERST HIER – NACH DEM ERFOLGREICHEN ABLEGEN, nicht
             * vor dem Laden. Der Unterschied ist die Fehlerrichtung: ein
             * abgebrochener Download ist ein NETZfehler und soll beim naechsten
             * Mal wieder versucht werden. Was die Bremse treffen soll, ist der
             * andere Fall – eine Fassung, die vollstaendig bereitliegt und
             * trotzdem nicht wirksam wird. Vor dem Laden gemerkt wuerde ein
             * einziger Verbindungsabbruch das Update bis zum naechsten
             * Versionswechsel blockieren. */
            ConfigStore.MerkeUpdateVersuch(ziel, EigeneAnzeige);
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
