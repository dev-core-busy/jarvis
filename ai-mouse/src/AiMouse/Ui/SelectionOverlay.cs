using AiMouse.Interop;

namespace AiMouse.Ui;

/// <summary>
/// Frameless, click-through, top-most window spanning the whole virtual desktop.
/// It dims everything except the current selection, which is punched out with the
/// layered-window colour key so the user sees the untouched screen underneath.
/// </summary>
internal sealed class SelectionOverlay : Form
{
    /// <summary>Colour key: rendered fully transparent by the layered window.</summary>
    private static readonly Color ChromaKey = Color.FromArgb(255, 0, 254);

    private static readonly Color BorderColor = Color.FromArgb(90, 170, 255);

    private Point _anchor;
    private Point _current;

    public SelectionOverlay()
    {
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        AutoScaleMode = AutoScaleMode.None;
        ShowInTaskbar = false;
        TopMost = true;
        DoubleBuffered = true;
        BackColor = Color.Black;
        TransparencyKey = ChromaKey;
        Opacity = 0.45d;
    }

    /// <summary>Never steal focus from the window the user is dragging over.</summary>
    protected override bool ShowWithoutActivation => true;

    protected override CreateParams CreateParams
    {
        get
        {
            CreateParams cp = base.CreateParams;
            cp.ExStyle |= NativeMethods.WS_EX_TOPMOST
                        | NativeMethods.WS_EX_TOOLWINDOW
                        | NativeMethods.WS_EX_NOACTIVATE
                        | NativeMethods.WS_EX_TRANSPARENT;
            return cp;
        }
    }

    /// <summary>Selection in screen coordinates (physical pixels).</summary>
    public Rectangle SelectionBounds => Rectangle.FromLTRB(
        Math.Min(_anchor.X, _current.X),
        Math.Min(_anchor.Y, _current.Y),
        Math.Max(_anchor.X, _current.X),
        Math.Max(_anchor.Y, _current.Y));

    public void BeginSelection(Point anchor)
    {
        _anchor = anchor;
        _current = anchor;

        // SystemInformation.VirtualScreen is already in physical pixels because the
        // process is Per-Monitor-V2 aware, so this covers every attached monitor.
        Bounds = SystemInformation.VirtualScreen;

        if (!Visible)
        {
            Show();
        }

        Invalidate();
        Update();
    }

    public void UpdateSelection(Point current)
    {
        if (!Visible || current == _current)
        {
            return;
        }

        Rectangle previous = SelectionBounds;
        _current = current;
        Rectangle updated = SelectionBounds;

        // Repaint the old and the new rectangle only — a full invalidate would be
        // expensive across a large multi-monitor desktop.
        Rectangle dirty = Rectangle.Union(previous, updated);
        dirty.Inflate(4, 4);
        dirty.Offset(-Left, -Top);

        Invalidate(dirty);
        Update();
    }

    public void EndSelection()
    {
        if (Visible)
        {
            Hide();
        }
    }

    protected override void OnPaintBackground(PaintEventArgs e)
    {
        // Painted entirely in OnPaint to avoid flicker.
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        Graphics g = e.Graphics;

        using (var dim = new SolidBrush(BackColor))
        {
            g.FillRectangle(dim, e.ClipRectangle);
        }

        Rectangle selection = SelectionBounds;
        selection.Offset(-Left, -Top);

        if (selection.Width <= 0 || selection.Height <= 0)
        {
            return;
        }

        using (var hole = new SolidBrush(ChromaKey))
        {
            g.FillRectangle(hole, selection);
        }

        using var pen = new Pen(BorderColor, 2f);
        g.DrawRectangle(pen, selection);

        DrawSizeHint(g, selection);
    }

    private void DrawSizeHint(Graphics g, Rectangle selection)
    {
        string label = $"{selection.Width} × {selection.Height}";
        using var font = new Font("Segoe UI", 9f, FontStyle.Regular, GraphicsUnit.Point);

        SizeF size = g.MeasureString(label, font);
        float x = selection.Left;
        float y = selection.Top - size.Height - 4f;

        if (y < ClientRectangle.Top)
        {
            y = selection.Bottom + 4f;
        }

        using var background = new SolidBrush(Color.FromArgb(20, 20, 20));
        using var text = new SolidBrush(Color.White);

        var box = new RectangleF(x, y, size.Width + 8f, size.Height + 2f);
        g.FillRectangle(background, box);
        g.DrawString(label, font, text, x + 4f, y + 1f);
    }
}
