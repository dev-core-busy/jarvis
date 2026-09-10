using AiMouse.Localization;

namespace AiMouse;

internal static class Program
{
    private const string SingleInstanceName = @"Local\AiMouse.SingleInstance";

    [STAThread]
    private static void Main()
    {
        using var instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out bool isOnlyInstance);

        if (!isOnlyInstance)
        {
            MessageBox.Show(
                "AI Mouse is already running — look for its icon in the notification area.",
                "AI Mouse",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return;
        }

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
