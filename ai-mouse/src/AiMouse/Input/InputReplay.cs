using System.ComponentModel;
using System.Runtime.InteropServices;
using AiMouse.Interop;
using AiMouse.Localization;

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
    /// <summary>Injiziert NUR das Druecken – fuer das Durchreichen an eine
    /// Anwendung, waehrend der Benutzer die Taste noch physisch haelt.
    ///
    /// ⚠ WARUM KEIN LOSLASSEN DAZU: der Benutzer haelt die Taste weiter, und
    /// das echte Loslassen kommt spaeter von ihm selbst. Wer hier ein `UP`
    /// mitschickt, beendet das Ziehen, bevor es angefangen hat – die
    /// Zielanwendung saehe einen vollstaendigen Klick und oeffnete ihr
    /// Kontextmenue statt Drag&amp;Drop zu starten.
    ///
    /// Der Hook laesst das Ereignis an seinem <see cref="Marker"/> durch.
    /// </summary>
    /// <returns><c>null</c> bei Erfolg, sonst ein lesbarer Grund.</returns>
    public static string? SendRightDown()
    {
        NativeMethods.INPUT[] inputs = [Mouse(NativeMethods.MOUSEEVENTF_RIGHTDOWN)];
        uint sent = NativeMethods.SendInput((uint)inputs.Length, inputs,
                                            Marshal.SizeOf<NativeMethods.INPUT>());
        return sent == inputs.Length ? null : Grund();
    }

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

        return Grund();
    }

    private static string? Grund()
    {
        int error = Marshal.GetLastWin32Error();

        // UIPI refused the injection: the foreground window belongs to a higher-integrity
        // process. InjectionGuard normally prevents this from ever being reached, but the
        // foreground window can still change between the press and the release.
        return error == NativeMethods.ERROR_ACCESS_DENIED
            ? Texte.KlickNichtWeitergereichtAdmin
            : $"{Texte.KlickNichtWeitergereicht} ({new Win32Exception(error).Message}).";
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
