using AiMouse.Interop;

namespace AiMouse.Start;

/// <summary>Beendet den Prozess so, dass er WIRKLICH endet.
///
/// ⚠ DER VORFALL, DER DAS NOETIG MACHT (gemeldet 2026-09-14, Fassung 1.0.5):
/// „die AiMouse.exe haengt sich so auf, dass sie nicht ohne System-Neustart zu
/// entfernen ist." Zwei Prozesse liessen sich weder ueber das Tray-Menue noch
/// mit `taskkill /F` beenden – die Fenster standen leer (weiss) da, die
/// Tray-Symbole blieben, und selbst nach dem Loeschen der EXE liefen die
/// Prozesse weiter.
///
/// DIE KETTE, die dahin fuehrt:
///
///   1. <see cref="Input.ZiehbarPruefer"/> fragt per UI Automation, was unter
///      dem Zeiger liegt. Das ist ein COM-Aufruf ueber die Prozessgrenze in
///      eine FREMDE Anwendung.
///   2. Antwortet die nicht (sie rechnet, sie zeigt einen modalen Dialog, sie
///      haengt), laeuft unsere Zeitgrenze ab – der abfragende Thread aber
///      bleibt im Kernel-Wait stehen. Er hat ein STA-Apartment initialisiert
///      und haelt einen COM-Proxy.
///   3. Beim Beenden nimmt `ExitProcess` den Loader-Lock und ruft
///      `DLL_PROCESS_DETACH`. Der haengende Thread wird terminiert – die
///      OLE32-internen Sperren, die er haelt, gibt er dabei NICHT frei.
///      Was sie als naechstes braucht, wartet ewig.
///   4. Ergebnis: ein Prozess, der in seiner eigenen Beendigung feststeckt.
///      `TerminateProcess` von aussen greift dann nicht mehr zuverlaessig,
///      weil die Beendigung ja laengst laeuft.
///
/// Die Ursache ist an ihrer Wurzel behoben (ein einziger, wiederverwendeter
/// Worker statt eines Threads je Abfrage – siehe dort). DIESE KLASSE IST DAS
/// NETZ DARUNTER: sie sorgt dafuer, dass ein Beenden auch dann endet, wenn
/// doch einmal etwas haengt – gleich ob COM, ein Treiber oder eine blockierte
/// Shell.
/// </summary>
internal static class Prozessende
{
    /// <summary>Frist fuer das geordnete Aufraeumen. Danach wird hart beendet.
    ///
    /// ⚠ GROSSZUEGIG GEWAEHLT, UND ZWAR ABSICHTLICH: in dieser Zeit werden
    /// Einstellungen geschrieben, das Tray-Symbol entfernt und der Hook
    /// ausgehaengt. Das dauert normalerweise Millisekunden; wer hier zu knapp
    /// misst, zerschiesst im Zweifel eine Einstellung, die gerade gespeichert
    /// wird. Fuenf Sekunden merkt niemand – ein Prozess, der gar nicht mehr
    /// weggeht, schon.
    /// </summary>
    private static readonly TimeSpan Frist = TimeSpan.FromSeconds(5);

    private static int _wachhundLaeuft;

    /// <summary>Beendet den Prozess sofort und ohne Aufraeumen.
    ///
    /// ⚠ NICHT <see cref="Environment.Exit"/>: das laeuft durch Finalizer und
    /// muendet in `ExitProcess` – also genau in die Sequenz, die am haengenden
    /// COM-Thread festhaengen kann. Auch `Application.Exit` hilft nicht, es
    /// beendet nur die Nachrichtenschleife.
    ///
    /// ⚠ VORHER MUSS ALLES PERSISTENTE GESCHRIEBEN SEIN. Nach diesem Aufruf
    /// laeuft nichts mehr.
    ///
    /// Schlaegt der Aufruf wider Erwarten fehl (er kann eigentlich nicht),
    /// bleibt <see cref="Environment.Exit"/> als Rueckfall – lieber der Weg,
    /// der haengen KANN, als gar keiner.
    /// </summary>
    public static void Hart(int code = 0)
    {
        try
        {
            NativeMethods.TerminateProcess(NativeMethods.GetCurrentProcess(), (uint)code);
        }
        catch (Exception)
        {
            // DllImport konnte nicht aufgeloest werden – praktisch unmoeglich,
            // aber ein Fehler hier darf nicht das Beenden verhindern.
        }

        // Wird im Regelfall NIE erreicht: TerminateProcess kehrt nicht zurueck.
        Environment.Exit(code);
    }

    /// <summary>Startet den Wachhund: haengt das Aufraeumen laenger als
    /// <see cref="Frist"/>, wird hart beendet.
    ///
    /// ⚠ EIN EIGENER THREAD UND KEIN TIMER AUS DEM THREADPOOL. Sobald die
    /// Beendigung begonnen hat, werden Pool-Threads nicht mehr bedient – ein
    /// Timer feuerte dann genau im Ernstfall nicht. Ein Vordergrund-Thread
    /// wuerde umgekehrt das Beenden verhindern, wenn alles gut geht; deshalb
    /// <see cref="Thread.IsBackground"/>.
    ///
    /// ⚠ IDEMPOTENT: wird von mehreren Beenden-Wegen gerufen (Tray-Menue,
    /// Windows-Abmeldung, Fehlerzweig). Zwei Wachhunde waeren zwei Threads
    /// fuer dieselbe Aufgabe.
    /// </summary>
    public static void WachhundStarten()
    {
        if (Interlocked.Exchange(ref _wachhundLaeuft, 1) != 0)
        {
            return;
        }

        try
        {
            var t = new Thread(() =>
            {
                Thread.Sleep(Frist);

                // Wir sind noch da, obwohl das Aufraeumen laengst durch sein
                // muesste: etwas haengt. Der Benutzer hat „Beenden" gedrueckt –
                // die Anwendung geht jetzt, so oder so.
                Hart(0);
            })
            {
                IsBackground = true,
                Name = "AiMouse.Beenden-Wachhund",
            };
            t.Start();
        }
        catch (Exception)
        {
            // Kein Thread verfuegbar – dann bleibt es beim geordneten Weg.
            _wachhundLaeuft = 0;
        }
    }
}
