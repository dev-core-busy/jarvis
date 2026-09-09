using System.ComponentModel;
using System.Runtime.InteropServices;
using AiMouse.Interop;

namespace AiMouse.Input;

/// <summary>
/// Re-injects the right-click that the gesture hook swallowed. Every synthetic event
/// carries <see cref="Marker"/> in its <c>dwExtraInfo</c> so the hook recognises its
/// own input and lets it straight through instead of eating it a second time.
/// </summary>
internal static class InputReplay
{
    /// <summary>ASCII "AIMS" — arbitrary, just has to be unlikely to collide.</summary>
    public static readonly IntPtr Marker = (IntPtr)0x41494D53;

    /// <summary>
    /// Sends a right button press + release at the current cursor position. No move is
    /// injected: the pointer is already where the user released, and that is within the
    /// drag threshold of where they pressed.
    /// </summary>
    /// <returns><c>null</c> on success, otherwise a human-readable reason.</returns>
    public static string? SendRightClick()
    {
        NativeMethods.INPUT[] inputs =
        [
            Mouse(NativeMethods.MOUSEEVENTF_RIGHTDOWN),
            Mouse(NativeMethods.MOUSEEVENTF_RIGHTUP),
        ];

        uint sent = NativeMethods.SendInput((uint)inputs.Length, inputs, Marshal.SizeOf<NativeMethods.INPUT>());

        if (sent == inputs.Length)
        {
            return null;
        }

        int error = Marshal.GetLastWin32Error();

        // UIPI refused the injection: the foreground window belongs to a higher-integrity
        // process. InjectionGuard normally prevents this from ever being reached, but the
        // foreground window can still change between the press and the release.
        return error == NativeMethods.ERROR_ACCESS_DENIED
            ? "The right-click could not be forwarded: the focused window runs elevated. Start AI Mouse as administrator."
            : $"The right-click could not be forwarded ({new Win32Exception(error).Message}).";
    }

    /// <summary>True if this event is one we injected ourselves.</summary>
    public static bool IsOwnInput(in NativeMethods.MSLLHOOKSTRUCT data) => data.dwExtraInfo == Marker;

    private static NativeMethods.INPUT Mouse(uint flags) => new()
    {
        type = NativeMethods.INPUT_MOUSE,
        mi = new NativeMethods.MOUSEINPUT
        {
            dwFlags = flags,
            dwExtraInfo = Marker,
        },
    };
}
