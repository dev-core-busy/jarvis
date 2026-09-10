using System.Diagnostics;
using System.Runtime.InteropServices;

using AiMouse.Interop;
using AiMouse.Localization;

namespace AiMouse.Ui;

/// <summary>Small top-most window showing the model's answer next to the selection.</summary>
internal sealed class ResultWindow : Form
{
    private readonly Label _header;
    private readonly RichTextBox _output;
    private readonly Button _copyButton;
    private readonly CancellationTokenSource _cts;

    public ResultWindow(string title, CancellationTokenSource cts)
    {
        _cts = cts;

        Text = $"{Texte.Marke} — {title}";
        StartPosition = FormStartPosition.Manual;
        MinimizeBox = false;
        MaximizeBox = true;
        ShowInTaskbar = true;
        TopMost = true;
        Size = new Size(560, 420);
        MinimumSize = new Size(360, 220);
        KeyPreview = true;
        Font = new Font("Segoe UI", 9f);

        _header = new Label
        {
            Dock = DockStyle.Top,
            Height = 28,
            Padding = new Padding(10, 6, 10, 0),
            Text = Texte.WarteAufModell,
            ForeColor = SystemColors.GrayText,
            AutoEllipsis = true,
        };

        // RichTextBox statt TextBox aus ZWEI Gruenden: `DetectUrls` macht eine
        // Adresse in der Antwort anklickbar, und `SelectionFont` erlaubt die
        // Fettschrift fuer `**…**` (Vorgabe 2026-09-10: „der MD-Parser wie im
        // Browser-Plugin"). Gedeutet wird ausschliesslich Fett – Begruendung
        // in `Ui/Markdown.cs`.
        _output = new RichTextBox
        {
            Dock = DockStyle.Fill,
            ReadOnly = true,
            DetectUrls = true,
            ScrollBars = RichTextBoxScrollBars.Vertical,
            BorderStyle = BorderStyle.None,
            BackColor = SystemColors.Window,
            Margin = new Padding(10),
            WordWrap = true,
        };
        // ⚠ Die RichTextBox oeffnet von allein NICHTS – ohne diesen Zuhoerer
        // ist der Link blau und tot. Was geoeffnet werden darf, entscheidet
        // `LinkZiel` (Begruendung dort).
        _output.LinkClicked += (_, e) => LinkOeffnen(e.LinkText);

        var body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(10, 4, 10, 4) };
        body.Controls.Add(_output);

        _copyButton = new Button
        {
            Text = Texte.Kopieren,
            Width = 90,
            Height = 28,
            Enabled = false,
            Anchor = AnchorStyles.Right,
        };
        _copyButton.Click += (_, _) => CopyToClipboard();

        var closeButton = new Button
        {
            Text = Texte.Schliessen,
            Width = 90,
            Height = 28,
            Anchor = AnchorStyles.Right,
        };
        closeButton.Click += (_, _) => Close();

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            FlowDirection = FlowDirection.RightToLeft,
            Height = 44,
            Padding = new Padding(10, 8, 10, 8),
        };
        buttons.Controls.Add(closeButton);
        buttons.Controls.Add(_copyButton);

        Controls.Add(body);
        Controls.Add(buttons);
        Controls.Add(_header);

        CancelButton = closeButton;
    }

    /// <summary>Places the window near the pointer without letting it leave the screen.</summary>
    public void PositionNear(Point anchor)
    {
        Rectangle working = Screen.FromPoint(anchor).WorkingArea;

        int x = Math.Clamp(anchor.X + 12, working.Left, Math.Max(working.Left, working.Right - Width));
        int y = Math.Clamp(anchor.Y + 12, working.Top, Math.Max(working.Top, working.Bottom - Height));

        Location = new Point(x, y);
    }

    public void ShowAnswer(string answer, bool copyToClipboard)
    {
        TextSetzen(answer, markdown: true);
        _header.Text = Texte.Zeichen(_output.TextLength);
        _header.ForeColor = SystemColors.GrayText;
        _copyButton.Enabled = true;

        if (copyToClipboard)
        {
            CopyToClipboard();
        }
    }

    public void ShowError(string message)
    {
        // ⚠ EINE FEHLERMELDUNG WIRD NICHT GEDEUTET. Sie stammt vom Server oder
        // aus einer Ausnahme und ist kein Markdown; ein `**` darin waere ein
        // Zufall, und ihn als Auszeichnung zu lesen wuerde die Meldung
        // verstuemmeln – gerade dort, wo man sie genau lesen muss.
        TextSetzen(message, markdown: false);
        _header.Text = Texte.AnfrageFehlgeschlagen;
        _header.ForeColor = Color.Firebrick;
        _copyButton.Enabled = true;
    }

    /// <summary>Setzt den Inhalt – wahlweise mit gedeuteter Fettschrift.
    ///
    /// ⚠ AUFGEBAUT WIRD UEBER `AppendText` + `SelectionFont`, NICHT ueber
    /// selbst gebautes RTF. Der Text ist FREMDTEXT (Modellantwort zu einem
    /// Bildschirmausschnitt); in RTF muessten `\`, `{` und `}` maskiert werden,
    /// und ein vergessener Fall zerlegt die Anzeige oder schmuggelt
    /// Steuerworte ein. Ueber `AppendText` gibt es nichts zu maskieren.
    ///
    /// Das Neuzeichnen wird waehrenddessen abgeschaltet: sonst flackert das
    /// Fenster bei jeder Fettstelle sichtbar.
    /// </summary>
    private void TextSetzen(string text, bool markdown)
    {
        _output.Clear();

        Font normal = _output.Font;
        using var fett = new Font(normal, FontStyle.Bold);

        // ⚠ `IsHandleCreated` UND NICHT einfach `.Handle`: der Zugriff auf
        // `Handle` ERZWINGT die Erzeugung des Fensterhandles. Beim ersten
        // Fuellen kann das Steuerelement noch keines haben, und ein erzwungener
        // Aufbau an dieser Stelle ist eine Nebenwirkung ohne Gegenwert – ohne
        // Handle gibt es ohnehin nichts, was flackern koennte.
        bool redraw = _output.IsHandleCreated;
        if (redraw)
        {
            NativeMethods.SendMessageW(_output.Handle, NativeMethods.WM_SETREDRAW, IntPtr.Zero, IntPtr.Zero);
        }

        try
        {
            if (!markdown)
            {
                _output.SelectionFont = normal;
                _output.AppendText(text.ReplaceLineEndings("\r\n"));
            }
            else
            {
                IReadOnlyList<IReadOnlyList<Lauf>> zeilen = Markdown.ZuZeilen(text);
                for (int i = 0; i < zeilen.Count; i++)
                {
                    if (i > 0)
                    {
                        _output.SelectionFont = normal;
                        _output.AppendText("\r\n");
                    }

                    foreach (Lauf lauf in zeilen[i])
                    {
                        _output.SelectionFont = lauf.Fett ? fett : normal;
                        _output.AppendText(lauf.Text);
                    }
                }
            }
        }
        finally
        {
            if (redraw)
            {
                NativeMethods.SendMessageW(_output.Handle, NativeMethods.WM_SETREDRAW, (IntPtr)1, IntPtr.Zero);
                _output.Invalidate();
            }
        }

        _output.Select(0, 0);
        _output.SelectionFont = normal;
    }

    /// <summary>Oeffnet einen angeklickten Link – ausschliesslich http/https.</summary>
    private void LinkOeffnen(string? ziel)
    {
        if (!LinkZiel.IstWeb(ziel, out Uri? adresse) || adresse is null)
        {
            // ⚠ NICHT STILL ABLEHNEN. Ein Link, der blau aussieht und beim
            // Klick nichts tut, ist von einem kaputten Fenster nicht zu
            // unterscheiden – der Kopf sagt deshalb, dass und warum nicht.
            _header.Text = Texte.LinkNichtGeoeffnet;
            _header.ForeColor = Color.Firebrick;
            return;
        }

        try
        {
            // `AbsoluteUri` und nicht der Rohtext: so geht genau die Adresse
            // hinaus, die geprueft wurde.
            Process.Start(new ProcessStartInfo(adresse.AbsoluteUri) { UseShellExecute = true })
                ?.Dispose();
            _header.Text = Texte.LinkGeoeffnet;
            _header.ForeColor = SystemColors.GrayText;
        }
        catch (Exception ex)
        {
            _header.Text = Texte.LinkFehler + " " + ex.Message;
            _header.ForeColor = Color.Firebrick;
        }
    }

    private void CopyToClipboard()
    {
        if (_output.TextLength == 0)
        {
            return;
        }

        try
        {
            // `_output.Text` ist bereits der Text OHNE `**` – gedeutet wurde
            // beim Anzeigen. Kopiert wird damit genau das, was im Fenster
            // steht; die Auszeichnung geht dabei verloren, und das ist richtig:
            // in Mail, Ticket oder Word waere `**` reines Rauschen.
            Clipboard.SetText(_output.Text);
            _header.Text = Texte.InZwischenablage;
        }
        catch (ExternalException)
        {
            // Another process is holding the clipboard open; not worth interrupting for.
        }
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        // Stop an in-flight request when the user closes the window early.
        if (!_cts.IsCancellationRequested)
        {
            _cts.Cancel();
        }

        _cts.Dispose();
        base.OnFormClosed(e);
    }
}
