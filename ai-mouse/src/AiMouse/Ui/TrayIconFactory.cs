using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using AiMouse.Interop;

namespace AiMouse.Ui;

/// <summary>
/// Draws the notification-area icon at runtime — a selection marquee with a pointer —
/// so the single-file exe needs no embedded resource and is distinguishable from the
/// generic application icon in the Windows 11 overflow flyout.
/// </summary>
internal static class TrayIconFactory
{
    private static readonly Color Accent = Color.FromArgb(90, 170, 255);

    public static Icon Create()
    {
        using var bitmap = new Bitmap(32, 32, PixelFormat.Format32bppArgb);

        using (Graphics g = Graphics.FromImage(bitmap))
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.Clear(Color.Transparent);

            // Dashed marquee, echoing the selection overlay.
            using var marquee = new Pen(Accent, 2.5f) { DashStyle = DashStyle.Dash };
            g.DrawRectangle(marquee, 3, 3, 24, 24);

            Point[] pointer =
            [
                new(13, 11), new(13, 27), new(17, 23),
                new(20, 29), new(23, 27), new(20, 21), new(25, 20),
            ];

            using var fill = new SolidBrush(Color.White);
            using var outline = new Pen(Color.FromArgb(25, 25, 25), 1.6f) { LineJoin = LineJoin.Round };
            g.FillPolygon(fill, pointer);
            g.DrawPolygon(outline, pointer);
        }

        IntPtr handle = bitmap.GetHicon();

        try
        {
            // Clone detaches the managed Icon from the GDI handle so it can be freed here.
            using var shared = Icon.FromHandle(handle);
            return (Icon)shared.Clone();
        }
        finally
        {
            NativeMethods.DestroyIcon(handle);
        }
    }
}
