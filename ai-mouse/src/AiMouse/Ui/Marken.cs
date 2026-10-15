using System.Drawing;
using System.Windows.Forms;

using AiMouse.Configuration;
using AiMouse.Localization;
using AiMouse.Update;

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
    /// <summary>Kopfzeile mit Marke in der Hausfarbe – und der Version daneben.
    ///
    /// ⚠ DIE VERSION STEHT HIER, WEIL SIE SONST NIRGENDS ZU SEHEN WAR (gemeldet
    /// 2026-09-11). Sie lag in der csproj, in den Windows-Dateieigenschaften und
    /// im health-Endpunkt – also an drei Orten, die der Benutzer am Arbeitsplatz
    /// nicht aufschlaegt. Damit war die Frage, die beim Melden eines Fehlers
    /// IMMER zuerst kommt ("habe ich ueberhaupt den neuen Stand?"), nur ueber
    /// einen Rechtsklick auf die EXE zu beantworten. Die Jira-Erweiterung nennt
    /// ihre Nummer aus genau diesem Grund in `chrome://extensions`.
    ///
    /// Sie steht im GETEILTEN Kopf und damit auch in der Anmeldemaske. Das ist
    /// Absicht: beim Einrichten ist die Frage dieselbe – und eine Ausnahme fuer
    /// ein Fenster waere gegen den Zweck dieser Klasse (eine Fassung fuer alle).
    /// </summary>
    public static Control Kopf(AppSettings s)
    {
        // ⚠ EIN Label mit ZWEI Schriftgraden geht nicht – deshalb ein
        //    FlowLayoutPanel. `Dock = Top` in einem AutoSize-Container waere der
        //    bekannte WinForms-Fallstrick (die Hoehe bleibt dann stehen); der
        //    Fluss waechst dagegen mit der Schrift, also auch bei 150 % Zoom.
        var kopf = new FlowLayoutPanel
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            AutoSizeMode = AutoSizeMode.GrowAndShrink,
            MinimumSize = new Size(0, 38),
            Padding = new Padding(12, 10, 12, 0),
            FlowDirection = FlowDirection.LeftToRight,
            // ⚠ `true`: passt die Version bei grosser Schrift nicht mehr neben
            //    die Marke, rutscht sie DARUNTER statt abgeschnitten zu werden.
            //    Fail-safe in die lesbare Richtung.
            WrapContents = true,
        };

        var marke = new Label
        {
            AutoSize = true,
            Margin = new Padding(0),
            Text = s.Marke,
            Font = new Font("Segoe UI", 12f, FontStyle.Bold),
            ForeColor = AkzentFarbe(s.Akzent),
        };

        var version = new Label
        {
            AutoSize = true,
            // Der linke Abstand trennt sie von der Marke, der obere setzt sie
            // auf deren Grundlinie – sie ist kleiner und staende sonst oben.
            Margin = new Padding(8, 6, 0, 0),
            Text = Texte.Version + " " + Aktualisierung.EigeneAnzeige,
            Font = new Font("Segoe UI", 8.25f),
            ForeColor = SystemColors.GrayText,
        };

        kopf.Controls.Add(marke);
        kopf.Controls.Add(version);
        return kopf;
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
