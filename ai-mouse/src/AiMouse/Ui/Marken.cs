using System.Drawing;
using System.Windows.Forms;

using AiMouse.Configuration;

namespace AiMouse.Ui;

/// <summary>Der Marken-Kopf der Fenster.
///
/// ⚠ EINE FASSUNG FUER ALLE FENSTER (2026-09-09 gemeldet: „Einstellungen ist
/// immer noch nicht gebrandet"). Die Anmeldemaske hatte ihren Kopf selbst
/// gebaut, der Einstellungsdialog trug die Marke nur im Fenstertitel – also
/// dort, wo sie unter Umstaenden gar nicht zu sehen ist.
///
/// Zwei Fassungen waeren beim naechsten Feinschliff auseinandergelaufen: der
/// eine Dialog haette die Hausfarbe getragen, der andere nicht, und niemand
/// haette erklaeren koennen warum.
/// </summary>
internal static class Marken
{
    /// <summary>Kopfzeile mit Marke in der Hausfarbe.</summary>
    public static Label Kopf(AppSettings s)
    {
        return new Label
        {
            Dock = DockStyle.Top,
            // ⚠ `AutoSize` statt fester Hoehe: die Marke steht in 12 pt fett –
            //    bei 150%% Zoom ist sie hoeher als 38 px und wuerde unten
            //    abgeschnitten. Die Mindesthoehe haelt das Aussehen bei 100%%.
            AutoSize = true,
            MinimumSize = new Size(0, 38),
            Padding = new Padding(12, 10, 12, 0),
            Text = s.Marke,
            Font = new Font("Segoe UI", 12f, FontStyle.Bold),
            ForeColor = AkzentFarbe(s.Akzent),
        };
    }

    /// <summary>Hausfarbe aus dem einkompilierten Wert.
    ///
    /// Fail-safe: eine kaputte Farbe darf das Fenster nicht am Oeffnen
    /// hindern – der Benutzer koennte sich dann gar nicht mehr anmelden.
    /// </summary>
    public static Color AkzentFarbe(string hex)
    {
        try
        {
            if (!string.IsNullOrWhiteSpace(hex) && hex.TrimStart().StartsWith('#'))
            {
                return ColorTranslator.FromHtml(hex.Trim());
            }
        }
        catch (Exception)
        {
            // Absichtlich verschluckt - siehe Docstring.
        }
        return SystemColors.ControlText;
    }
}
