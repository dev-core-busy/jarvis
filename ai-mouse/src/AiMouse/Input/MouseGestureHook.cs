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

    /// <summary>Taste, die den Rechtsklick DURCHREICHT statt ihn zu nehmen.
    ///
    /// ⚠ WOZU DAS DA IST: der Hook verschluckt sonst JEDEN Rechtsklick bis zum
    /// Loslassen – damit ist Windows' eigenes Right-Drag („Datei mit rechter
    /// Maustaste ziehen" → Hierher kopieren/verschieben/Verknuepfung) tot,
    /// solange die Anwendung laeuft. Die Zielanwendung sieht nie einen
    /// gedrueckten Knopf und kann deshalb gar keinen Drag beginnen.
    ///
    /// ⚠ WARUM EINE TASTE UND KEINE ERKENNUNG: „liegt hier etwas Ziehbares?"
    /// laesst sich unter Windows nicht zuverlaessig beantworten. Ziehbarkeit
    /// ist kein Zustand, den man abfragen kann – sie entsteht erst dadurch,
    /// dass die Anwendung auf gedrueckte Taste + Bewegung mit `DoDragDrop`
    /// reagiert. UIA kennt zwar `IsDraggable`, aber Explorer, Office und
    /// Browser implementieren es nicht (die Abfrage saegt fast ueberall
    /// „nein"), und `LVM_HITTEST` hilft nur beim klassischen ListView – der
    /// Explorer in Windows 10/11 rendert per DirectUI.
    ///
    /// ⚠ UND DER AUSSCHLAGGEBENDE GRUND IST DIE ZEIT: dieser Callback muss
    /// innerhalb `LowLevelHooksTimeout` (Vorgabe 300 ms) zurueck, sonst haengt
    /// Windows den Hook STILLSCHWEIGEND aus – die Geste waere dann tot, ohne
    /// jede Meldung. Eine UIA-Abfrage ist ein Cross-Process-COM-Aufruf und
    /// kann bei einer beschaeftigten Zielanwendung zig Millisekunden dauern.
    /// `GetAsyncKeyState` kostet dagegen nichts.
    /// </summary>
    public GestenTaste Durchreichen { get; set; } = GestenTaste.Keine;

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

                // Haelt der Benutzer die Durchreich-Taste, gehoert der Klick der
                // Zielanwendung – wir fassen ihn gar nicht erst an, damit ihr
                // Drag&Drop funktioniert. `_pressWithheld = false` ist dabei
                // Pflicht: sonst haelte sich der spaetere BUTTONUP fuer einen,
                // der zurueckgehalten wurde, und verschluckte ihn.
                if (TasteGehalten(Durchreichen))
                {
                    _pressWithheld = false;
                    break;
                }

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

    /// <summary>Ist die gewaehlte Modifikatortaste gerade physisch gedrueckt?
    ///
    /// Das hohe Bit von `GetAsyncKeyState` heisst „gerade unten". Das NIEDRIGE
    /// Bit bedeutet etwas voellig anderes (seit dem letzten Aufruf einmal
    /// gedrueckt gewesen) und darf hier NICHT mitgelesen werden – sonst wuerde
    /// ein laengst losgelassenes Strg den naechsten Rechtsklick durchreichen.
    /// </summary>
    private static bool TasteGehalten(GestenTaste taste)
    {
        int vk = taste switch
        {
            GestenTaste.Strg => NativeMethods.VK_CONTROL,
            GestenTaste.Alt => NativeMethods.VK_MENU,
            GestenTaste.Umschalt => NativeMethods.VK_SHIFT,
            _ => 0,
        };
        return vk != 0 && (NativeMethods.GetAsyncKeyState(vk) & 0x8000) != 0;
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
