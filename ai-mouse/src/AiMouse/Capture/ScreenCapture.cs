using System.Drawing.Imaging;

namespace AiMouse.Capture;

/// <summary>Grabs a region of the virtual desktop and encodes it as PNG / Base64.</summary>
internal static class ScreenCapture
{
    /// <summary>Anything smaller than this in either axis is treated as a mis-drag.</summary>
    public const int MinimumEdge = 4;

    /// <summary>
    /// Copies <paramref name="bounds"/> (screen coordinates, physical pixels) into a
    /// bitmap. Returns <c>null</c> if the region is degenerate or off-screen.
    /// </summary>
    public static Bitmap? Capture(Rectangle bounds)
    {
        Rectangle clipped = Rectangle.Intersect(bounds, SystemInformation.VirtualScreen);

        if (clipped.Width < MinimumEdge || clipped.Height < MinimumEdge)
        {
            return null;
        }

        var bitmap = new Bitmap(clipped.Width, clipped.Height, PixelFormat.Format32bppArgb);

        try
        {
            using Graphics g = Graphics.FromImage(bitmap);
            g.CopyFromScreen(clipped.Location, Point.Empty, clipped.Size, CopyPixelOperation.SourceCopy);
            return bitmap;
        }
        catch
        {
            bitmap.Dispose();
            throw;
        }
    }

    public static byte[] ToPng(Image image)
    {
        using var buffer = new MemoryStream();
        image.Save(buffer, ImageFormat.Png);
        return buffer.ToArray();
    }

    /// <summary>PNG bytes as a data URI, ready for an OpenAI-style <c>image_url</c>.</summary>
    public static string ToDataUri(Image image) => "data:image/png;base64," + Convert.ToBase64String(ToPng(image));
}
