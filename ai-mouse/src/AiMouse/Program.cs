using AiMouse.Localization;
using AiMouse.Start;
using AiMouse.Update;

namespace AiMouse;

internal static class Program
{
    private const string SingleInstanceName = @"Local\AiMouse.SingleInstance";

    [STAThread]
    private static void Main()
    {
        Starten();

        /* ⚠ HART BEENDEN – UND ZWAR AUF JEDEM WEG AUS `Starten()`. Deshalb
         * steht der Aufruf hier und nicht am Ende des Rumpfes: der springt an
         * mehreren Stellen mit `return` heraus und liefe sonst daran vorbei.
         *
         * Gemeldet 2026-09-14 (Fassung 1.0.5): „die AiMouse.exe haengt sich so
         * auf, dass sie nicht ohne System-Neustart zu entfernen ist." Der
         * normale Rueckweg aus `Main` muendet in `ExitProcess`, und das nimmt
         * den Loader-Lock und ruft `DLL_PROCESS_DETACH` in jeder geladenen
         * DLL. Haengt dabei ein Thread in einem ausgehenden COM-Aufruf, wird er
         * terminiert, ohne seine OLE32-Sperren freizugeben – und was sie als
         * naechstes braucht, wartet ewig. Der Prozess steckt dann in seiner
         * eigenen Beendigung fest: leeres Fenster, Tray-Symbol bleibt, und
         * `taskkill /F` greift nicht mehr, weil die Beendigung ja laeuft.
         *
         * Die URSACHE ist an der Wurzel behoben (ein einziger Worker statt
         * eines Threads je Abfrage – siehe `ZiehbarPruefer`). Das hier ist das
         * Netz darunter: der Kernel raeumt den Prozess ab, ohne Detach-Sequenz.
         *
         * ⚠ ES DARF NICHTS MEHR ZU SPEICHERN GEBEN. Einstellungen schreibt der
         * Dialog beim Speichern, nicht beim Beenden – nachgesehen, nicht
         * angenommen. */
        Prozessende.Hart(0);
    }

    /// <summary>Die Einzelinstanz-Sperre. Ein FELD, kein lokales `using`: der
    /// Neustart nach einem Update (`TrayApplicationContext`) muss sie
    /// schliessen, bevor er die neue Fassung startet.</summary>
    private static Mutex? _instanceLock;

    /// <summary>Schliesst die Einzelinstanz-Sperre – NUR vor dem Neustart nach
    /// einem Update, und nur vom UI-Thread (dem, der sie erworben hat).
    ///
    /// ⚠ GESCHLOSSEN, NICHT NUR FREIGEGEBEN (gemeldet 2026-09-14: „wird
    /// umbenannt ... aber nicht automatisch gestartet"). `ReleaseMutex()` gibt
    /// die BESITZERSCHAFT frei, nicht den NAMEN. Solange dieser Prozess das
    /// Handle haelt, existiert das Kernel-Objekt weiter – und
    /// `new Mutex(..., out createdNew)` meldet der frisch gestarteten neuen
    /// Fassung `createdNew = false`. Sie hielte sich fuer einen ZWEITSTART und
    /// beendete sich wortlos. Erst `Dispose()` schliesst das Handle und gibt
    /// den Namen frei.
    /// </summary>
    internal static void EinzelinstanzFreigeben()
    {
        Mutex? m = _instanceLock;
        _instanceLock = null;
        if (m is null)
        {
            return;
        }

        try
        {
            m.ReleaseMutex();
        }
        catch (Exception)
        {
            // Schon freigegeben oder fremder Besitzer – das Schliessen
            // darunter ist ohnehin das, worauf es ankommt.
        }

        m.Dispose();
    }

    /// <summary>Holt die Sperre zurueck, wenn der Neustart nach einem Update
    /// NICHT gelang. Ohne das liefe diese Instanz ungeschuetzt weiter – und
    /// ein zweiter Start erzeugte eine zweite Instanz.</summary>
    internal static void EinzelinstanzZurueckholen()
    {
        if (_instanceLock is not null)
        {
            return;
        }

        try
        {
            _instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out _);
        }
        catch (Exception)
        {
            _instanceLock = null;
        }
    }

    private static void Starten()
    {
        _instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out bool isOnlyInstance);
        try
        {
        /* ⚠ DIE RESTE EINES AUSTAUSCHS WEGRAEUMEN – bei JEDEM Start, hinter der
         * Einzelinstanz-Sperre. Die verdraengte Fassung (`.alt`) entsteht beim
         * Update im laufenden Betrieb und ist erst loeschbar, wenn ihr Prozess
         * weg ist (eine laufende EXE laesst Windows umbenennen, nicht loeschen).
         * Hinter der Sperre, weil ein Zweitstart sonst die Datei einer
         * laufenden Instanz anfassen wuerde.
         *
         * ⚠ HIER WIRD NICHTS MEHR EINGEWECHSELT (seit 1.0.13). Der Austausch
         * passiert im laufenden Betrieb (`Update/Aktualisierung.cs`); der
         * fruehere Einwechsel beim Programmstart hat in der Praxis nicht
         * getragen. */
        if (isOnlyInstance)
        {
            Aktualisierung.RueckstandAufraeumen();
        }

        if (!isOnlyInstance)
        {
            // ⚠ KEIN MODALER DIALOG MEHR IM REGELFALL (2026-09-12). Seit die
            // Anwendung ueber eine Tastenkombination gestartet werden kann, ist
            // der Zweitstart der NORMALFALL: sie laeuft ja schon im
            // Infobereich. Ein Dialog haette den Hotkey damit meistens zu einer
            // Fehlermeldung gemacht.
            //
            // Gelingt das Signal nicht (die laufende Instanz ist gerade am
            // Starten oder Beenden), bleibt der Dialog – eine gedrueckte Taste
            // ohne JEDE Rueckmeldung waere der schlechtere Ausgang.
            if (!Zweitstart.LaufendeInstanzWecken())
            {
                MessageBox.Show(
                    Texte.LaeuftBereits,
                    Texte.Marke,
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }
            return;
        }

        // Erst hier, nicht frueher: vorher war noch offen, ob dieser Prozess
        // ueberhaupt die laufende Instanz wird.
        Zweitstart.AlsErsteInstanz();

        // Deliberately not ApplicationConfiguration.Initialize(): DPI awareness comes
        // from the manifest, so the generated SetHighDpiMode call would be a silent no-op.
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        Application.ThreadException += (_, e) => ReportFatal(e.Exception);
        AppDomain.CurrentDomain.UnhandledException += (_, e) => ReportFatal(e.ExceptionObject as Exception);

        TrayApplicationContext context;
        try
        {
            context = new TrayApplicationContext();
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                $"AI Mouse could not start.\r\n\r\n{ex.Message}",
                "AI Mouse",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return;
        }

        try
        {
            Application.Run(context);
        }
        finally
        {
            /* ⚠ DER WACHHUND STARTET VOR DEM AUFRAEUMEN, NICHT DANACH – sonst
             * waere er genau dann zu spaet, wenn er gebraucht wird. Das
             * Aufraeumen selbst kann haengen: `UnhookWindowsHookEx`, das
             * Entfernen des Tray-Symbols (es geht an die Shell) oder ein
             * Fenster-Dispose, das auf eine blockierte Nachrichtenschleife
             * wartet. Laeuft es laenger als die Frist, wird hart beendet.
             *
             * Ersetzt das fruehere `using`: die Zusage „wird in jedem Fall
             * aufgeraeumt" bleibt, nur kommt der Wachhund davor. */
            Prozessende.WachhundStarten();
            context.Dispose();
        }
        }
        finally
        {
            // Kein `using var`: der Mutex wird beim Neustart nach einem Update
            // ZWISCHENDURCH geschlossen und ggf. neu erworben – ein `using`
            // auf die Variable koennte das nicht abbilden.
            _instanceLock?.Dispose();
            _instanceLock = null;
        }
    }

    private static void ReportFatal(Exception? exception) => MessageBox.Show(
        $"{Texte.UnerwarteterFehler}\r\n\r\n{exception?.ToString() ?? Texte.Unbekannt}",
        Texte.Marke,
        MessageBoxButtons.OK,
        MessageBoxIcon.Error);
}
