using System.ComponentModel;
using System.Runtime.InteropServices;
using AiMouse.Interop;

namespace AiMouse.Input;

/// <summary>
/// Low-level (<c>WH_MOUSE_LL</c>) hook that recognises a "right-click + drag" gesture.
///
/// Both <c>WM_RBUTTONDOWN</c> and <c>WM_RBUTTONUP</c> are swallowed, so no application
/// ever sees half a click and the system context menu never appears on its own. The
/// decision is deferred to the release:
///
/// <list type="bullet">
///   <item>moved past <see cref="_threshold"/> px — the gesture keeps the click and
///     <see cref="DragCompleted"/> fires;</item>
///   <item>otherwise it was a plain right-click, and <see cref="InputReplay"/> injects a
///     genuine press + release so the target application behaves exactly as usual.</item>
/// </list>
///
/// The cost is that a right-click now reaches its target on button-up rather than
/// button-down, and that injection is subject to UIPI (see <see cref="ReplayFailed"/>).
/// </summary>
internal sealed class MouseGestureHook : IDisposable
{
    private readonly NativeMethods.LowLevelMouseProc _callback;
    private readonly ISynchronizeInvoke _marshaller;

    private int _threshold;

    private IntPtr _hookHandle;

    /// <summary>True while a swallowed press is owed either to a gesture or to a replay.</summary>
    private bool _pressWithheld;

    private bool _isDragging;
    private Point _start;

    /// <summary>Raised once the drag threshold is crossed. Argument: anchor point.</summary>
    public event Action<Point>? DragStarted;

    /// <summary>Raised on every move while dragging. Argument: current point.</summary>
    public event Action<Point>? DragMoved;

    /// <summary>Raised on release. Argument: the normalised selection rectangle.</summary>
    public event Action<Rectangle>? DragCompleted;

    /// <summary>
    /// Raised when a swallowed right-click could not be re-injected — the user's click
    /// is lost in that case, so it must not stay silent.
    /// </summary>
    public event Action<string>? ReplayFailed;

    /// <summary>Pixels the pointer must travel before the gesture engages.</summary>
    public int Threshold
    {
        get => _threshold;
        set => _threshold = Math.Max(1, value);
    }

    public MouseGestureHook(ISynchronizeInvoke marshaller, int threshold)
    {
        _marshaller = marshaller;
        Threshold = threshold;

        // Held in a field so the GC cannot collect the delegate while Windows owns it.
        _callback = HookProc;
    }

    public void Install()
    {
        if (_hookHandle != IntPtr.Zero)
        {
            return;
        }

        IntPtr module = NativeMethods.GetModuleHandleW(null);
        _hookHandle = NativeMethods.SetWindowsHookExW(NativeMethods.WH_MOUSE_LL, _callback, module, 0);

        if (_hookHandle == IntPtr.Zero)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "SetWindowsHookEx(WH_MOUSE_LL) failed.");
        }
    }

    private IntPtr HookProc(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode < 0)
        {
            return NativeMethods.CallNextHookEx(_hookHandle, nCode, wParam, lParam);
        }

        NativeMethods.MSLLHOOKSTRUCT data = Marshal.PtrToStructure<NativeMethods.MSLLHOOKSTRUCT>(lParam);
        var point = new Point(data.pt.x, data.pt.y);

        switch ((int)wParam)
        {
            case NativeMethods.WM_RBUTTONDOWN:
                if (InputReplay.IsOwnInput(data))
                {
                    break;
                }

                _isDragging = false;

                if (InjectionGuard.BlocksInjection())
                {
                    // We could not replay this click afterwards, so we must not take it.
                    _pressWithheld = false;
                    break;
                }

                _pressWithheld = true;
                _start = point;

                // Withhold the press until the release tells us what the user meant.
                return (IntPtr)1;

            case NativeMethods.WM_MOUSEMOVE:
                if (!_pressWithheld)
                {
                    break;
                }

                if (!_isDragging)
                {
                    if (Math.Abs(point.X - _start.X) <= _threshold && Math.Abs(point.Y - _start.Y) <= _threshold)
                    {
                        break;
                    }

                    _isDragging = true;

                    // Snapshot the anchor: the field may move on before the post runs.
                    Point anchor = _start;
                    Post(() => DragStarted?.Invoke(anchor));
                }

                Post(() => DragMoved?.Invoke(point));
                break;

            case NativeMethods.WM_RBUTTONUP:
                if (InputReplay.IsOwnInput(data))
                {
                    break;
                }

                if (!_pressWithheld)
                {
                    // Nothing was taken from the target application — either the press
                    // predates the hook, or the guard let it through.
                    break;
                }

                _pressWithheld = false;

                if (_isDragging)
                {
                    _isDragging = false;
                    Rectangle selection = Normalise(_start, point);
                    Post(() => DragCompleted?.Invoke(selection));
                }
                else if (InputReplay.SendRightClick() is { } failure)
                {
                    Post(() => ReplayFailed?.Invoke(failure));
                }

                // The press was withheld, so the release must go too — either the
                // gesture consumed the click or InputReplay has already replayed it.
                return (IntPtr)1;
        }

        return NativeMethods.CallNextHookEx(_hookHandle, nCode, wParam, lParam);
    }

    /// <summary>
    /// Queues work on the UI thread. The hook callback must return well within the
    /// system's <c>LowLevelHooksTimeout</c>, so nothing is executed inline here.
    /// </summary>
    private void Post(Action action)
    {
        try
        {
            _marshaller.BeginInvoke(action, null);
        }
        catch (InvalidOperationException)
        {
            // Handle already destroyed during shutdown. Covers ObjectDisposedException,
            // which derives from it.
        }
    }

    private static Rectangle Normalise(Point a, Point b) => Rectangle.FromLTRB(
        Math.Min(a.X, b.X),
        Math.Min(a.Y, b.Y),
        Math.Max(a.X, b.X),
        Math.Max(a.Y, b.Y));

    public void Dispose()
    {
        if (_hookHandle != IntPtr.Zero)
        {
            NativeMethods.UnhookWindowsHookEx(_hookHandle);
            _hookHandle = IntPtr.Zero;
        }
    }
}
