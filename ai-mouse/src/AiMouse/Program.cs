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
        using var instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out bool isOnlyInstance);

        // ⚠ DER EINWECHSEL STEHT HIER: HINTER DER EINZELINSTANZ-SPERRE UND VOR
        // ALLEM ANDEREN. Hinter der Sperre, weil sonst zwei gleichzeitig
        // gestartete Instanzen dieselbe Datei umbenennen wollen. Vor allem
        // anderen, weil ab dem ersten Fenster etwas zu verlieren waere – hier
        // ist noch nichts da, der Wechsel dauert Millisekunden, und der
        // Benutzer sieht nur, dass das Tray-Symbol einmal erscheint.
        //
        // ⚠ DIE SPERRE MUSS VOR DEM NEUSTART FREIGEGEBEN WERDEN: die neu
        // gestartete Instanz liefe sonst in die "laeuft bereits"-Meldung – und
        // zwar genau dann, wenn ein Update eingewechselt wurde.
        if (isOnlyInstance && Aktualisierung.NeueFassungLiegtBereit())
        {
            try
            {
                instanceLock.ReleaseMutex();
            }
            catch (Exception)
            {
                // Schon freigegeben oder fremder Besitzer – der Start darunter
                // entscheidet ohnehin selbst, ob er gelingt.
            }

            if (Aktualisierung.BeimStartEinwechseln())
            {
                return;     // die neue Fassung laeuft jetzt
            }

            // Nicht gelungen (kein Schreibrecht, Ruecknahme) – weiterlaufen wie
            // bisher. Die Sperre ist dabei freigegeben; vertretbar, weil ein
            // zweiter Start in genau diesem Moment der seltenste Fall ist und
            // hoechstens eine zweite Instanz kostet.
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

    private static void ReportFatal(Exception? exception) => MessageBox.Show(
        $"{Texte.UnerwarteterFehler}\r\n\r\n{exception?.ToString() ?? Texte.Unbekannt}",
        Texte.Marke,
        MessageBoxButtons.OK,
        MessageBoxIcon.Error);
}
