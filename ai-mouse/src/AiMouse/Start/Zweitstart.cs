namespace AiMouse.Start;

/// <summary>Verbindet einen zweiten Programmstart mit der bereits laufenden
/// Instanz.
///
/// ⚠ WOZU DAS NOETIG IST – sonst waere die Tastenkombination im Regelfall
/// nutzlos: sie startet die Exe. Laeuft die Anwendung schon (der Normalzustand,
/// sie sitzt im Infobereich), lief der zweite Start bis 2026-09-12 in einen
/// MODALEN DIALOG „is already running". Der Hotkey haette also meistens nicht
/// gestartet, sondern eine Fehlermeldung erzeugt – schlechter als kein Hotkey.
///
/// Jetzt: die zweite Instanz SETZT EIN SIGNAL und beendet sich wortlos, die
/// laufende meldet sich. Damit tut dieselbe Kombination beides – starten, wenn
/// nichts laeuft, und sich melden, wenn doch.
///
/// ⚠ `Local\` UND NICHT `Global\`: bei mehreren angemeldeten Benutzern
/// (Terminalserver, schneller Benutzerwechsel) gehoert jeder Sitzung ihre
/// eigene Instanz – ein globales Signal wuerde die Instanz eines FREMDEN
/// Benutzers wecken. Dieselbe Wahl wie bei der Einzelinstanz-Sperre daneben.
/// </summary>
internal static class Zweitstart
{
    private const string SignalName = @"Local\AiMouse.Zeigen";

    private static EventWaitHandle? _signal;
    private static RegisteredWaitHandle? _beobachter;

    /// <summary>Legt das Signal an – von der ERSTEN Instanz zu rufen.
    ///
    /// ⚠ SO FRUEH WIE MOEGLICH, unmittelbar nach der Einzelinstanz-Sperre:
    /// zwischen „ich bin die erste Instanz" und „mein Signal steht" gibt es ein
    /// Zeitfenster, in dem ein zweiter Start das Signal nicht faende und doch
    /// wieder den Dialog zeigte. Das Fenster laesst sich nicht ganz schliessen,
    /// aber auf Millisekunden verkuerzen.
    ///
    /// Scheitert es (Rechte, Namenskollision), laeuft die Anwendung normal
    /// weiter – nur der Zweitstart meldet dann wieder wie frueher.
    /// </summary>
    public static void AlsErsteInstanz()
    {
        try
        {
            _signal = new EventWaitHandle(false, EventResetMode.AutoReset, SignalName);
        }
        catch (Exception)
        {
            _signal = null;
        }
    }

    /// <summary>Weckt eine laufende Instanz – von der ZWEITEN zu rufen.</summary>
    /// <returns><c>true</c>, wenn das Signal wirklich abgesetzt wurde. Nur dann
    /// darf der Aufrufer sich wortlos beenden; sonst haette der Benutzer eine
    /// Taste gedrueckt und BEKAEME GAR KEINE Rueckmeldung.</returns>
    public static bool LaufendeInstanzWecken()
    {
        try
        {
            if (!EventWaitHandle.TryOpenExisting(SignalName, out EventWaitHandle? h))
            {
                return false;
            }

            using (h)
            {
                return h.Set();
            }
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>Ruft <paramref name="beiSignal"/>, sooft ein zweiter Start
    /// stattfindet.
    ///
    /// ⚠ DER RUECKRUF KOMMT AUS EINEM POOL-THREAD, nicht aus dem UI-Thread –
    /// wer darin ein Fenster anfasst, bekommt einen Fehler, den nur ein echter
    /// Windows-Lauf zeigt. Das Marshalling gehoert in den Aufrufer (er kennt
    /// sein Fenster); hier wird es bewusst nicht erraten.
    ///
    /// <c>executeOnlyOnce: false</c>: die Registrierung bleibt fuer JEDEN
    /// weiteren Zweitstart bestehen – sonst wirkte der Hotkey genau einmal.
    /// </summary>
    public static void Beobachten(Action beiSignal)
    {
        if (_signal is null || _beobachter is not null)
        {
            return;
        }

        try
        {
            _beobachter = ThreadPool.RegisterWaitForSingleObject(
                _signal,
                (_, _) =>
                {
                    try
                    {
                        beiSignal();
                    }
                    catch (Exception)
                    {
                        // Ein Fehler in der Reaktion darf die Beobachtung nicht
                        // beenden – sonst waere der Hotkey ab dem ersten
                        // Stolperer dauerhaft tot.
                    }
                },
                state: null,
                millisecondsTimeOutInterval: Timeout.Infinite,
                executeOnlyOnce: false);
        }
        catch (Exception)
        {
            _beobachter = null;
        }
    }

    /// <summary>Gibt Beobachter und Signal frei.</summary>
    public static void Aufraeumen()
    {
        try
        {
            _beobachter?.Unregister(null);
        }
        catch (Exception) { }
        _beobachter = null;

        try
        {
            _signal?.Dispose();
        }
        catch (Exception) { }
        _signal = null;
    }
}
