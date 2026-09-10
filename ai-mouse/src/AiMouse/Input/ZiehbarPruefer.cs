using System.Runtime.InteropServices;

namespace AiMouse.Input;

/// <summary>Fragt per UI Automation, was unter dem Mauszeiger liegt.
///
/// ⚠ DIE GUIDS UND DIE VTABLE-REIHENFOLGE SIND AUS DER SDK-IDL VERIFIZIERT
/// (`UIAutomationClient.idl`, Windows SDK 10.0.14393), NICHT geraten. Das ist
/// hier der gefaehrlichste Punkt der ganzen Datei: ein `[ComImport]`-Interface
/// mit falscher Reihenfolge UEBERSETZT FEHLERFREI und ruft zur Laufzeit die
/// falsche Funktion – der Absturz kaeme erst am Arbeitsplatz.
///
///   CUIAutomation (coclass)  ff48dba4-60ef-4201-aa87-54103eef594e
///   IUIAutomation            30cbe57d-d9d0-452a-ab13-7ac5ac4825ee
///     ElementFromPoint       = 5. Methode nach IUnknown
///   IUIAutomationElement     d22108aa-8ac5-49a5-837b-37bbb3d7591e
///     GetCurrentPropertyValue = 8. Methode nach IUnknown
///
/// ⚠ ES WIRD BEWUSST `GetCurrentPropertyValue` (8) BENUTZT UND NICHT
/// `get_CurrentControlType` (19): je weiter hinten die Methode liegt, desto
/// mehr Platzhalter muessen exakt stimmen. Acht statt neunzehn ist weniger als
/// die halbe Angriffsflaeche fuer genau den Fehler, der nicht auffaellt.
///
/// ⚠ DIESE KLASSE LAESST SICH AUF DEM BAUSERVER NICHT AUSFUEHREN (kein
/// Windows). Die ENTSCHEIDUNG liegt deshalb in <see cref="ZiehbarRegel"/> und
/// wird dort gemessen; hier bleibt nur das Beschaffen der Merkmale.
/// </summary>
internal static class ZiehbarPruefer
{
    private const int UIA_ControlTypePropertyId = 30003;
    private const int UIA_IsDragPatternAvailablePropertyId = 30137;
    private const int UIA_IsSelectionItemPatternAvailablePropertyId = 30036;

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int x;
        public int y;
    }

    [ComImport, Guid("d22108aa-8ac5-49a5-837b-37bbb3d7591e"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IUIAutomationElement
    {
        // 1–7: nicht benutzt, aber ihre ANZAHL und Rueckgabeart muessen stimmen,
        // sonst zeigt der Aufruf unten auf die falsche vtable-Position.
        void SetFocus();
        void GetRuntimeId();
        void FindFirst();
        void FindAll();
        void FindFirstBuildCache();
        void FindAllBuildCache();
        void BuildUpdatedCache();

        // 8.
        [return: MarshalAs(UnmanagedType.Struct)]
        object GetCurrentPropertyValue(int propertyId);
    }

    [ComImport, Guid("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IUIAutomation
    {
        void CompareElements();
        void CompareRuntimeIds();
        void GetRootElement();
        void ElementFromHandle();

        // 5.
        IUIAutomationElement ElementFromPoint(POINT pt);
    }

    [ComImport, Guid("ff48dba4-60ef-4201-aa87-54103eef594e")]
    private class CUIAutomation
    {
    }

    /// <summary>Liegt an <paramref name="p"/> ein ziehbares Objekt?
    ///
    /// ⚠ LAEUFT IN EINEM EIGENEN STA-THREAD MIT ZEITGRENZE – und das ist
    /// Pflicht, keine Vorsicht: `ElementFromPoint` ist ein Aufruf ueber die
    /// Prozessgrenze in die ZIELANWENDUNG. Antwortet die gerade nicht (sie
    /// rechnet, sie haengt, sie zeigt einen modalen Dialog), blockiert der
    /// Aufruf – und liefe er auf dem UI-Thread, staende die ganze Anwendung
    /// samt Maus-Hook still. Der Thread ist ein Hintergrund-Thread: laeuft er
    /// in die Grenze, geben wir auf und er stirbt spaetestens mit dem Prozess.
    ///
    /// COM braucht STA; das setzt `SetApartmentState`, nicht wir von Hand.
    ///
    /// Jeder Fehler ergibt <c>false</c> – siehe die Begruendung in
    /// <see cref="ZiehbarRegel"/>: im Zweifel Lasso, nie Drag.
    /// </summary>
    public static bool LiegtObjektUnter(Point p, TimeSpan grenze)
    {
        bool ergebnis = false;

        var t = new Thread(() =>
        {
            try
            {
                var automation = (IUIAutomation)new CUIAutomation();
                IUIAutomationElement? el = automation.ElementFromPoint(
                    new POINT { x = p.X, y = p.Y });
                if (el is null)
                {
                    return;
                }

                ergebnis = ZiehbarRegel.IstZiehbar(
                    ZahlAus(el, UIA_ControlTypePropertyId),
                    WahrheitAus(el, UIA_IsDragPatternAvailablePropertyId),
                    WahrheitAus(el, UIA_IsSelectionItemPatternAvailablePropertyId));
            }
            catch
            {
                // UIA nicht verfuegbar, Zugriff verweigert, Element
                // verschwunden – alles derselbe Ausgang: kein Drag.
                ergebnis = false;
            }
        })
        {
            IsBackground = true,
        };

        t.SetApartmentState(ApartmentState.STA);
        t.Start();

        // ⚠ `Join` mit Grenze und KEIN `Abort` danach: einen Thread hart zu
        // beenden gibt es in .NET aus gutem Grund nicht mehr – er haelt
        // womoeglich eine COM-Sperre. Wir lassen ihn laufen und ignorieren
        // ihn; `ergebnis` bleibt dann auf `false`.
        return t.Join(grenze) && ergebnis;
    }

    private static int ZahlAus(IUIAutomationElement el, int propertyId)
    {
        try
        {
            object v = el.GetCurrentPropertyValue(propertyId);
            return v is null ? 0 : Convert.ToInt32(v);
        }
        catch
        {
            return 0;
        }
    }

    private static bool WahrheitAus(IUIAutomationElement el, int propertyId)
    {
        try
        {
            object v = el.GetCurrentPropertyValue(propertyId);
            return v is not null && Convert.ToBoolean(v);
        }
        catch
        {
            // ⚠ Ein Element, das die Eigenschaft nicht kennt, liefert den
            // "Not Supported"-Platzhalter – der laesst sich nicht wandeln.
            // Das ist ein NEIN, kein Fehler.
            return false;
        }
    }
}
