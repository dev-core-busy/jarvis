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
        Mutex? instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out bool isOnlyInstance);
        try
        {
        // ⚠ DER EINWECHSEL STEHT HIER: HINTER DER EINZELINSTANZ-SPERRE UND VOR
        // ALLEM ANDEREN. Hinter der Sperre, weil sonst zwei gleichzeitig
        // gestartete Instanzen dieselbe Datei umbenennen wollen. Vor allem
        // anderen, weil ab dem ersten Fenster etwas zu verlieren waere – hier
        // ist noch nichts da, der Wechsel dauert Millisekunden, und der
        // Benutzer sieht nur, dass das Tray-Symbol einmal erscheint.
        if (isOnlyInstance && Aktualisierung.NeueFassungLiegtBereit())
        {
            /* ⚠ GESCHLOSSEN, NICHT NUR FREIGEGEBEN – UND GENAU DAS WAR DER
             * FEHLER (gemeldet 2026-09-14: „wird umbenannt ... aber nicht
             * automatisch gestartet").
             *
             * `ReleaseMutex()` gibt die BESITZERSCHAFT frei, nicht den NAMEN.
             * Solange dieser Prozess das Handle haelt, existiert das
             * Kernel-Objekt weiter – und `new Mutex(..., out createdNew)`
             * meldet jedem weiteren Prozess `createdNew = false`. Die frisch
             * gestartete neue Fassung hielt sich damit fuer einen ZWEITSTART,
             * suchte das Wecksignal der „laufenden" Instanz (das es nicht gibt,
             * weil `AlsErsteInstanz()` im Update-Zweig nie erreicht wird) und
             * beendete sich wortlos. Ergebnis genau wie gemeldet: die Dateien
             * sind umbenannt, und es laeuft nichts.
             *
             * Erst `Dispose()` schliesst das Handle und gibt den Namen frei.
             * Danach ist der Start deterministisch, kein Wettlauf mehr. */
            try
            {
                instanceLock.ReleaseMutex();
            }
            catch (Exception)
            {
                // Schon freigegeben oder fremder Besitzer – das Schliessen
                // darunter ist ohnehin das, worauf es ankommt.
            }

            instanceLock.Dispose();
            instanceLock = null;

            if (Aktualisierung.BeimStartEinwechseln())
            {
                return;     // die neue Fassung laeuft jetzt
            }

            /* Nicht gelungen (kein Schreibrecht, Ruecknahme): die Sperre
             * ZURUECKHOLEN. Ohne das liefe diese Instanz ungeschuetzt weiter –
             * und ein zweiter Start wuerde eine zweite Instanz erzeugen,
             * obwohl gar kein Update stattgefunden hat. */
            instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out isOnlyInstance);
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

        using (context)
        {
            Application.Run(context);
        }
        }
        finally
        {
            // Ersetzt das fruehere `using var`: der Mutex wird beim Einwechseln
            // ZWISCHENDURCH geschlossen und danach ggf. neu erworben – ein
            // `using` auf die Variable koennte das nicht abbilden.
            instanceLock?.Dispose();
        }
    }

    private static void ReportFatal(Exception? exception) => MessageBox.Show(
        $"{Texte.UnerwarteterFehler}\r\n\r\n{exception?.ToString() ?? Texte.Unbekannt}",
        Texte.Marke,
        MessageBoxButtons.OK,
        MessageBoxIcon.Error);
}
