using System.Runtime.InteropServices;
using AiMouse.Interop;

namespace AiMouse.Input;

/// <summary>
/// Decides whether it is safe to withhold a right-click for later replay.
///
/// UIPI refuses <c>SendInput</c> when the foreground window belongs to a process of
/// higher integrity than ours, so swallowing the press there would destroy the user's
/// click outright. In that situation the gesture stands down and every mouse event is
/// passed through untouched — a right-click keeps working, only the capture gesture is
/// unavailable over that window.
/// </summary>
internal static class InjectionGuard
{
    // A window's integrity level cannot change, so the answer is cached per window.
    // The pid is part of the key because window handles can be recycled.
    private static IntPtr _cachedWindow;
    private static uint _cachedProcessId;
    private static bool _cachedResult;

    /// <summary>True when the current foreground window is out of reach for injection.</summary>
    public static bool BlocksInjection()
    {
        IntPtr window = NativeMethods.GetForegroundWindow();

        if (window == IntPtr.Zero)
        {
            return false;
        }

        NativeMethods.GetWindowThreadProcessId(window, out uint processId);

        if (processId == 0)
        {
            return false;
        }

        if (window == _cachedWindow && processId == _cachedProcessId)
        {
            return _cachedResult;
        }

        bool blocked = IsHigherIntegrity(processId);

        _cachedWindow = window;
        _cachedProcessId = processId;
        _cachedResult = blocked;

        return blocked;
    }

    /// <summary>
    /// Probes the process token. A medium-integrity process may open a *handle* to an
    /// elevated process with <c>PROCESS_QUERY_LIMITED_INFORMATION</c>, but opening its
    /// token is denied — that denial is the signal we are looking for.
    /// </summary>
    private static bool IsHigherIntegrity(uint processId)
    {
        IntPtr process = NativeMethods.OpenProcess(NativeMethods.PROCESS_QUERY_LIMITED_INFORMATION, false, processId);

        if (process == IntPtr.Zero)
        {
            return Marshal.GetLastWin32Error() == NativeMethods.ERROR_ACCESS_DENIED;
        }

        try
        {
            if (NativeMethods.OpenProcessToken(process, NativeMethods.TOKEN_QUERY, out IntPtr token))
            {
                NativeMethods.CloseHandle(token);
                return false;
            }

            return Marshal.GetLastWin32Error() == NativeMethods.ERROR_ACCESS_DENIED;
        }
        finally
        {
            NativeMethods.CloseHandle(process);
        }
    }
}
