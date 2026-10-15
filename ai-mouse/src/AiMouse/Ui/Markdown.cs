namespace AiMouse.Ui;

/// <summary>Ein Stueck Text mit oder ohne Fettschrift.</summary>
internal readonly record struct Lauf(string Text, bool Fett);

/// <summary>Deutet `**fett**` in einer Modellantwort – dieselbe Regel wie im
/// Browser-Plugin (`zuBloecken` in `browser-addon/popup.js`).
///
/// ⚠ WARUM DIESE KLASSE UI-FREI IST: `ResultWindow` erbt von `Form`, und
/// WinForms laesst sich auf dem Bauserver zwar uebersetzen, aber NICHT
/// ausfuehren. Nur so laesst sich die Regel gegen echte Faelle LAUFEN lassen
/// statt sie zu lesen – dieselbe Begruendung wie bei <see cref="LinkZiel"/>.
///
/// ⚠ ES WIRD NUR FETT GEDEUTET, und das ist die Vorgabe („wie im browser
/// plugin"), keine Auslassung. Ueberschriften (`## …`), Listen (`- …`),
/// Kursiv (`*…*`) und Code (`` `…` ``) bleiben stehen, wie sie das Modell
/// geschrieben hat. Der Grund ist derselbe wie dort: jede zusaetzliche Regel
/// ist eine weitere Gelegenheit, fremden Text zu VERSTUEMMELN – und was der
/// Parser nicht deutet, ist hoechstens ungeschickt formatiert, waehrend eine
/// falsch greifende Regel Inhalt kostet.
/// </summary>
internal static class Markdown
{
    /// <summary>Die Regel ist zeichengleich zu `_FETT_RE` im Browser-Plugin.
    ///
    /// Die `\S`-Waechter sind der ganze Unterschied zwischen brauchbar und
    /// gefaehrlich: ohne sie wuerden `2 * 3 * 4`, `*.txt` und `** allein **`
    /// als Auszeichnung gelesen. Nicht global – gesucht wird in einer Schleife
    /// ueber den REST der Zeile, ein wandernder `lastIndex` waere hier eine
    /// Fehlerquelle.
    /// </summary>
    private static readonly System.Text.RegularExpressions.Regex Fett =
        new(@"\*\*(?=\S)([^\n]+?)(?<=\S)\*\*",
            System.Text.RegularExpressions.RegexOptions.Compiled);

    /// <summary>Zerlegt den Text in Zeilen und jede Zeile in Laeufe.
    ///
    /// Die Zeilenstruktur bleibt erhalten (eine Liste je Zeile, auch fuer
    /// leere Zeilen) – der Aufrufer setzt die Umbrueche. Genau wie im Plugin:
    /// dort baut die Anzeige daraus `<br>`, hier die RichTextBox `\n`.
    /// </summary>
    public static IReadOnlyList<IReadOnlyList<Lauf>> ZuZeilen(string? text)
    {
        var zeilen = new List<IReadOnlyList<Lauf>>();

        // `\r\n` und `\r` zuerst vereinheitlichen, sonst entstuende bei einer
        // Windows-Zeile ein leerer Lauf mit einem einzelnen `\r` darin.
        string roh = (text ?? string.Empty).Replace("\r\n", "\n").Replace('\r', '\n');

        foreach (string zeile in roh.Split('\n'))
        {
            var laeufe = new List<Lauf>();
            string rest = zeile;

            while (true)
            {
                System.Text.RegularExpressions.Match m = Fett.Match(rest);
                if (!m.Success)
                {
                    break;
                }

                if (m.Index > 0)
                {
                    laeufe.Add(new Lauf(rest[..m.Index], false));
                }

                laeufe.Add(new Lauf(m.Groups[1].Value, true));
                rest = rest[(m.Index + m.Length)..];
            }

            if (rest.Length > 0)
            {
                laeufe.Add(new Lauf(rest, false));
            }

            zeilen.Add(laeufe);
        }

        return zeilen;
    }

    /// <summary>Der Text ohne die Auszeichnung – das, was der Benutzer SIEHT.
    ///
    /// Wird fuer die Zwischenablage gebraucht: `**` dort mitzugeben waere
    /// Rauschen in jedem Ziel, das kein Markdown kann (Mail, Ticket, Word).
    /// </summary>
    public static string OhneAuszeichnung(string? text)
    {
        var sb = new System.Text.StringBuilder();
        IReadOnlyList<IReadOnlyList<Lauf>> zeilen = ZuZeilen(text);

        for (int i = 0; i < zeilen.Count; i++)
        {
            if (i > 0)
            {
                sb.Append('\n');
            }

            foreach (Lauf l in zeilen[i])
            {
                sb.Append(l.Text);
            }
        }

        return sb.ToString();
    }
}
