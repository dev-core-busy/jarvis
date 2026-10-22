using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using AiMouse.Configuration;

namespace AiMouse.Update;

/// <summary>Selbstaktualisierung der Anwendung (ab 1.0.0, 2026-09-11;
/// Austausch seit 1.0.13 im laufenden Betrieb).
///
/// ⚠ DER AUSTAUSCH PASSIERT SOFORT, NICHT BEIM NAECHSTEN START (2026-10-22).
/// Uebernommen aus dem STT-Support-Assistenten (`updater.go`), wo derselbe
/// Weg seit vielen Fassungen zuverlaessig traegt:
///
///   1. Version vergleichen, den Benutzer FRAGEN.
///   2. Neue EXE als <c>AiMouse.exe.neu</c> daneben ablegen.
///   3. Die LAUFENDE Datei auf <c>.alt</c> umbenennen (das erlaubt Windows,
///      ueberschreiben nicht), die neue an ihre Stelle – bei Fehlschlag
///      zurueck.
///   4. Der Aufrufer gibt die Einzelinstanz-Sperre frei, startet die neue
///      Fassung und beendet sich. Die neue raeumt <c>.alt</c> beim Start weg.
///
/// WARUM NICHT MEHR DER ZWEISCHRITT (bis 1.0.12: still bereitlegen, beim
/// naechsten Programmstart einwechseln): er hat in der Praxis nicht getragen.
/// Gemeldet wurden nacheinander eine Endlosschleife (auf Platte 1.0.6, im
/// Speicher 1.0.5), eine umbenannte, aber nie gestartete Fassung (Mutex) und
/// eine liegengebliebene Altdatei – jeder Fehler sass im Einwechsel-Zweig beim
/// Programmstart, und der liess sich ohne Windows nicht messen. Der
/// Sofort-Austausch hat genau EINE Stelle, an der getauscht wird, und die
/// laeuft, waehrend die Anwendung vollstaendig steht.
///
/// ⚠ DIE RUECKFRAGE IST DER PREIS DAFUER UND BLEIBT: ein Neustart schliesst ein
/// offenes Ergebnisfenster. Deshalb entscheidet der Benutzer, wann – sagt er
/// nein, wird beim naechsten Anmelden wieder gefragt (Betreiberentscheidung
/// 2026-10-22).
///
/// ⚠ WAS HIER GELADEN WIRD, IST AUSFUEHRBARER CODE. Getragen wird das von zwei
/// Dingen, und beide muessen bleiben: die Verbindung ist TLS-geprueft (der
/// Client benutzt den Standard-HttpClient OHNE abgeschaltete
/// Zertifikatspruefung – gemessen, nicht angenommen), und der Abruf braucht
/// ein gueltiges Sitzungstoken. Damit ist das Vertrauensniveau dasselbe wie
/// beim Download von Hand aus dem Portal; ein neues Risiko entsteht nicht.
/// Wer hier je eine Ausnahme fuer ein selbst ausgestelltes Zertifikat einbaut,
/// macht daraus einen Weg zur Codeausfuehrung ueber einen Man-in-the-Middle.
///
/// ⚠ "TLS-GEPRUEFT" SETZT https VORAUS (Code-Review 2026-10-18). Bis dahin
/// liess `EndpointResolver` auch eine http-Adresse zu – dann kam die EXE im
/// Klartext, und der Absatz darueber war eine Behauptung ohne Grundlage.
/// Jetzt gilt es an ZWEI Stellen: `EndpointResolver.Basis` nimmt nur https an,
/// und `JarvisClient.PaketAsync` (der `paketHolen`-Rueckruf) verweigert jede
/// andere Adresse selbst noch einmal. Diese Klasse kennt die Adresse nicht;
/// eine Ablehnung kommt hier als Ausnahme an, landet im `catch` von
/// <see cref="PruefenUndHolenAsync"/> und heisst: kein Update, die laufende
/// Fassung bleibt. Eine Codesignatur-Pruefung der geladenen EXE gibt es
/// bewusst NICHT (Betreiberentscheidung) – umso weniger darf der Transport
/// nachgeben.
/// </summary>
internal static class Aktualisierung
{
    /// <summary>Die neue Fassung liegt unter diesem Namen daneben – nur fuer
    /// die Sekunden zwischen Download und Austausch.</summary>
    private const string NeuSuffix = ".neu";

    /// <summary>Waehrend des Schreibens: erst wenn die Datei vollstaendig ist,
    /// wird sie zur <c>.neu</c>.</summary>
    private const string TeilSuffix = ".teil";

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
    /// Freigabe, und der Austausch traefe die Datei fuer ALLE – ausgeloest
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

    /// <summary>Rueckgabe von <see cref="PruefenUndHolenAsync"/>, wenn die neue
    /// Fassung an der Stelle der laufenden liegt. Dann – und NUR dann – muss
    /// der Aufrufer neu starten (<see cref="NeueFassungStarten"/>).</summary>
    public const string Eingewechselt = "eingewechselt";

    /// <summary>Raeumt die Reste eines Austauschs weg: die verdraengte Fassung
    /// (<c>.alt</c>) und einen abgebrochenen Download (<c>.neu</c>,
    /// <c>.teil</c>). Bei JEDEM Start gerufen (<c>Program</c>).
    ///
    /// ⚠ DER ERSTE VERSUCH NACH DEM NEUSTART KANN SCHEITERN: die alte Fassung
    /// beendet sich, waehrend die neue schon startet, und solange ihr Prozess
    /// noch steht, laesst Windows die <c>.alt</c> nicht loeschen. Dann bleibt
    /// sie bis zum naechsten Start liegen – eine Datei zu viel neben der EXE
    /// stoert den Betrieb nicht. (Dieselbe Abwaegung wie `cleanupOldBinary`
    /// im STT-Support-Assistenten.)
    ///
    /// ⚠ <c>.neu</c> MITLOESCHEN: bis 1.0.12 war sie die bereitgelegte Fassung
    /// fuer den naechsten Start. Seit dem Sofort-Austausch lebt sie nur
    /// Sekunden; liegt sie beim Start, ist sie ein abgebrochener Rest.
    /// </summary>
    public static void RueckstandAufraeumen()
    {
        string exe = EigenerPfad;
        if (exe.Length == 0)
        {
            return;
        }

        foreach (string rest in new[] { exe + AltSuffix, exe + NeuSuffix, exe + TeilSuffix })
        {
            try
            {
                if (File.Exists(rest))
                {
                    File.Delete(rest);
                }
            }
            catch (Exception)
            {
                // Siehe Docstring: beim naechsten Start erneut.
            }
        }
    }

    /// <summary>Tauscht die laufende Datei gegen <paramref name="neu"/> aus.
    ///
    /// <c>true</c> = die neue Fassung liegt unter dem Namen der laufenden, die
    /// alte als <c>.alt</c> daneben. <c>false</c> = es ist alles wie vorher.
    ///
    /// ⚠ DIE REIHENFOLGE IST DIE SICHERUNG: erst wird die laufende Datei auf
    /// <c>.alt</c> umbenannt (das erlaubt Windows auch fuer eine laufende EXE),
    /// dann die neue an ihre Stelle. Schlaegt der zweite Schritt fehl, wird der
    /// erste ZURUECKGENOMMEN – sonst bliebe gar keine EXE stehen und die
    /// Anwendung waere auf diesem Arbeitsplatz endgueltig weg.
    /// </summary>
    internal static bool Austauschen(string exe, string neu)
    {
        string alt = exe + AltSuffix;

        try
        {
            File.Move(exe, alt, overwrite: true);
        }
        catch (Exception)
        {
            // Kein Schreibrecht, Virenscanner haelt die Datei – alles bleibt.
            return false;
        }

        try
        {
            File.Move(neu, exe, overwrite: true);
            return true;
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
    }

    /// <summary>Startet die (eingewechselte) Fassung unter dem eigenen Pfad.
    ///
    /// ⚠ DER AUFRUFER MUSS VORHER DIE EINZELINSTANZ-SPERRE SCHLIESSEN und sich
    /// danach SOFORT beenden. Haelt dieser Prozess den Mutex noch, meldet er
    /// der neuen Fassung <c>createdNew = false</c>; sie haelt sich fuer einen
    /// Zweitstart und beendet sich wortlos (gemeldet 2026-09-14, 1.0.5).
    /// </summary>
    public static bool NeueFassungStarten()
    {
        string exe = EigenerPfad;
        if (exe.Length == 0)
        {
            return false;
        }

        try
        {
            using Process? p = Process.Start(new ProcessStartInfo(exe)
            {
                UseShellExecute = true,
                WorkingDirectory = Path.GetDirectoryName(exe) ?? string.Empty,
            });
            return p is not null;
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>Prueft die Serverversion, fragt nach, laedt und tauscht aus.
    ///
    /// Rueckgabe: kurzer Grund fuer das Journal ("" = nichts zu tun).
    /// <see cref="Eingewechselt"/> heisst: die neue Fassung liegt an der Stelle
    /// der laufenden, der Aufrufer startet neu. Wirft NIE – ein Fehlschlag
    /// darf die Anwendung nicht stoeren, sie funktioniert ohne Update
    /// unveraendert weiter.
    ///
    /// <paramref name="nachfragen"/> bekommt die Serverversion und liefert
    /// <c>true</c>, wenn der Benutzer jetzt aktualisieren will.
    /// </summary>
    public static async Task<string> PruefenUndHolenAsync(
        string? serverVersion, Func<string, Task<bool>> nachfragen,
        Func<CancellationToken, Task<byte[]>> paketHolen, CancellationToken ct)
    {
        try
        {
            if (!IstNeuer(serverVersion, Eigene))
            {
                // ⚠ AUCH HIER LEEREN (Review 2026-09-28 #14): sinkt die
                // Serverversion (Rueckbau) oder hat der Administrator die
                // Freigabe inzwischen erneuert, stuende sonst der Hinweis
                // "neue Version" bis zum naechsten Programmstart weiter da.
                NetzVersion = string.Empty;
                return string.Empty;
            }

            string exe = EigenerPfad;
            if (exe.Length == 0)
            {
                return string.Empty;
            }

            /* ⚠ VON EINER NETZFREIGABE WIRD NICHT SELBST AKTUALISIERT.
             *
             * Sonst tauscht ein beliebiger Arbeitsplatz die GEMEINSAME Datei
             * fuer alle aus – waehrend andere sie womoeglich gerade ausfuehren.
             * Welcher Stand verteilt wird, entscheidet der Administrator; genau
             * dafuer gibt es die Freigabe.
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

            /* ⚠ SCHLEIFEN-BREMSE (gemeldet 2026-09-14: "es wird JEDESMAL die
             * neue exe auf den Rechner kopiert").
             *
             * Meldet der Server eine Version, die das Paket gar nicht traegt,
             * waere die eingewechselte Fassung wieder die alte – und jede
             * Anmeldung finge von vorn an: fragen, 66 MB laden, tauschen,
             * unveraendert alt. Ein Update ohne Gedaechtnis ueber den letzten
             * Versuch ist eine Endlosschleife; die Antwort ist, den Versuch zu
             * MERKEN. Gleiches Ziel bei gleicher Ausgangslage heisst: der
             * vorige Austausch hat nichts bewirkt, ein zweiter aendert daran
             * nichts. */
            (string gZiel, string gVon) = ConfigStore.LadeUpdateVersuch();
            string ziel = (serverVersion ?? string.Empty).Trim();
            if (gZiel.Length > 0
                && string.Equals(gZiel, ziel, StringComparison.OrdinalIgnoreCase)
                && string.Equals(gVon, EigeneAnzeige, StringComparison.OrdinalIgnoreCase))
            {
                return "schon versucht";
            }

            // Schreibrecht VORHER pruefen – nach einer Rueckfrage 66 MB zu
            // laden, um dann am Speichern zu scheitern, waere die schlechteste
            // Reihenfolge: der Benutzer hat ja gesagt, und es passiert nichts.
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

            if (!await nachfragen(ziel).ConfigureAwait(false))
            {
                // Nicht gemerkt: beim naechsten Anmelden wird erneut gefragt.
                return "abgelehnt";
            }

            byte[] zip = await paketHolen(ct).ConfigureAwait(false);
            if (zip.Length < 1_000_000)
            {
                return "Paket unbrauchbar";
            }

            // ⚠ ZUERST IN EINE NEBENDATEI, DANN UMBENENNEN. Was als `.neu`
            // liegt, ist vollstaendig geschrieben – ein abgebrochener
            // Schreibvorgang hinterlaesst hoechstens eine `.teil`.
            string teil = exe + TeilSuffix;
            string neu = exe + NeuSuffix;
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

            // Eine leere oder winzige Datei ist kein Programm – lieber
            // wegwerfen als einwechseln.
            if (new FileInfo(teil).Length < 1_000_000)
            {
                File.Delete(teil);
                return "EXE unbrauchbar";
            }

            File.Move(teil, neu, overwrite: true);

            if (!Austauschen(exe, neu))
            {
                File.Delete(neu);
                return "Austausch fehlgeschlagen";
            }

            /* ⚠ GEMERKT WIRD ERST HIER – NACH DEM ERFOLGREICHEN AUSTAUSCH, nicht
             * vor dem Laden. Ein abgebrochener Download ist ein NETZfehler und
             * soll beim naechsten Mal wieder versucht werden; die Bremse soll
             * nur den Fall treffen, in dem eine vollstaendig eingewechselte
             * Fassung trotzdem nicht wirksam wird. */
            ConfigStore.MerkeUpdateVersuch(ziel, EigeneAnzeige);
            return Eingewechselt;
        }
        catch (Exception e)
        {
            // Aufraeumen, damit kein Rest liegen bleibt – und still bleiben.
            try
            {
                string exe = EigenerPfad;
                if (exe.Length > 0)
                {
                    File.Delete(exe + TeilSuffix);
                    File.Delete(exe + NeuSuffix);
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
