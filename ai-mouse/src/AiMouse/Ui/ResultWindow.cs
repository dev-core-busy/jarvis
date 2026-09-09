using System.Runtime.InteropServices;

namespace AiMouse.Ui;

/// <summary>Small top-most window showing the model's answer next to the selection.</summary>
internal sealed class ResultWindow : Form
{
    private readonly Label _header;
    private readonly TextBox _output;
    private readonly Button _copyButton;
    private readonly CancellationTokenSource _cts;

    public ResultWindow(string title, CancellationTokenSource cts)
    {
        _cts = cts;

        Text = $"AI Mouse — {title}";
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
            Text = "Waiting for the model…",
            ForeColor = SystemColors.GrayText,
            AutoEllipsis = true,
        };

        _output = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            BorderStyle = BorderStyle.None,
            BackColor = SystemColors.Window,
            Margin = new Padding(10),
            WordWrap = true,
        };

        var body = new Panel { Dock = DockStyle.Fill, Padding = new Padding(10, 4, 10, 4) };
        body.Controls.Add(_output);

        _copyButton = new Button
        {
            Text = "&Copy",
            Width = 90,
            Height = 28,
            Enabled = false,
            Anchor = AnchorStyles.Right,
        };
        _copyButton.Click += (_, _) => CopyToClipboard();

        var closeButton = new Button
        {
            Text = "&Close",
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
        _header.Text = $"{answer.Length} characters";
        _header.ForeColor = SystemColors.GrayText;
        _output.Text = answer.ReplaceLineEndings("\r\n");
        _output.Select(0, 0);
        _copyButton.Enabled = true;

        if (copyToClipboard)
        {
            CopyToClipboard();
        }
    }

    public void ShowError(string message)
    {
        _header.Text = "Request failed";
        _header.ForeColor = Color.Firebrick;
        _output.Text = message.ReplaceLineEndings("\r\n");
        _output.Select(0, 0);
        _copyButton.Enabled = true;
    }

    private void CopyToClipboard()
    {
        if (_output.TextLength == 0)
        {
            return;
        }

        try
        {
            Clipboard.SetText(_output.Text);
            _header.Text = "Copied to clipboard";
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
