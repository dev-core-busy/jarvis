using AiMouse.Interop;

namespace AiMouse.Input;

/// <summary>Die Masse, nach denen Windows „stillhalten" und „ziehen" bemisst.
///
/// ⚠ AUSDRUECKLICHE VORGABE (2026-09-10): „an das entsprechende Windows
/// timeout anpassen". Eigene Zahlen waeren hier falsch: wer seine
/// Eingabehilfen angepasst hat (zittrige Hand, Touchpad), bekommt sonst ein
/// Verhalten, das zu keiner anderen Anwendung auf seinem Rechner passt.
/// </summary>
internal static class SystemWerte
{
    /// <summary>Untergrenzen gegen unbrauchbare Systemwerte.
    ///
    /// ⚠ FAIL-SAFE IN DIE LANGSAME RICHTUNG: eine Verweilzeit von 0 waere
    /// „sofort durchreichen" – dann gaebe es das Lasso praktisch nicht mehr,
    /// und niemand koennte sich erklaeren warum. Eine zu grosse Zeit kostet
    /// dagegen nur Geduld.
    /// </summary>
    private const int VerweilMin = 150;
    private const int VerweilMax = 2000;
    private const int VerweilVorgabe = 400;   // Windows-Vorgabe

    /// <summary>Wie lange muss die Maus stillstehen? (<c>SPI_GETMOUSEHOVERTIME</c>)</summary>
    public static int Verweilzeit()
    {
        try
        {
            uint wert = 0;
            if (NativeMethods.SystemParametersInfoW(
                    NativeMethods.SPI_GETMOUSEHOVERTIME, 0, ref wert, 0)
                && wert > 0)
            {
                return (int)Math.Clamp(wert, VerweilMin, VerweilMax);
            }
        }
        catch
        {
            // Faellt die Abfrage aus, gilt die Windows-Vorgabe.
        }

        return VerweilVorgabe;
    }

    /// <summary>Zieh-Toleranz in Pixeln (<c>SM_CXDRAG</c> / <c>SM_CYDRAG</c>).
    ///
    /// „Ohne Bewegung" kann nicht null Pixel heissen – eine Hand zittert, und
    /// jede andere Anwendung misst an genau diesem Wert, ob eine Bewegung ein
    /// Ziehen ist.</summary>
    public static (int X, int Y) Ziehtoleranz()
    {
        int x = 0, y = 0;
        try
        {
            x = NativeMethods.GetSystemMetrics(NativeMethods.SM_CXDRAG);
            y = NativeMethods.GetSystemMetrics(NativeMethods.SM_CYDRAG);
        }
        catch
        {
            // s.u. – die Vorgabe greift.
        }

        // 0 kaeme bei jedem Pixel Zittern als "Bewegung" durch und wuerde die
        // Halte-Erkennung praktisch abschalten.
        return (x > 0 ? x : 4, y > 0 ? y : 4);
    }

    /// <summary>Hat sich der Zeiger weiter bewegt als die Toleranz erlaubt?</summary>
    public static bool UeberToleranz(Point start, Point jetzt)
    {
        (int tx, int ty) = Ziehtoleranz();
        return Math.Abs(jetzt.X - start.X) > tx || Math.Abs(jetzt.Y - start.Y) > ty;
    }
}
