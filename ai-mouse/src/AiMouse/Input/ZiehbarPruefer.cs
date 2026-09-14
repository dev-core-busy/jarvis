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
///
/// ═══════════════════════════════════════════════════════════════════════════
/// ⚠ EIN DAUERHAFTER WORKER, NICHT EIN THREAD JE ABFRAGE – und das ist der
/// wichtigste Satz dieser Datei.
///
/// Bis Fassung 1.0.5 erzeugte jede Abfrage einen eigenen STA-Thread und gab
/// ihn nach der Zeitgrenze einfach auf („er stirbt spaetestens mit dem
/// Prozess" – das stimmte nicht). Antwortet die Zielanwendung nicht, bleibt
/// der Thread im Kernel-Wait stehen, mit initialisiertem COM-Apartment und
/// einem Proxy auf ein fremdes Objekt. Beim naechsten Halten entstand der
/// naechste. Sie haeuften sich unbegrenzt an – und beim Beenden lief die
/// Anwendung dann in einen Deadlock, aus dem sie ohne Systemneustart nicht
/// mehr herauskam (gemeldet 2026-09-14; die ganze Kette steht in
/// <see cref="Start.Prozessende"/>).
///
/// Jetzt gibt es GENAU EINEN Worker. Haengt er, ist er „beschaeftigt", und
/// jede weitere Abfrage wird sofort mit <c>false</c> beantwortet, OHNE einen
/// zweiten Thread zu erzeugen. Der Schaden ist damit auf einen einzigen
/// haengenden Thread begrenzt – egal, wie oft der Benutzer die Taste haelt.
/// Kommt die Zielanwendung wieder zu sich, wird der Worker von selbst wieder
/// frei und die Erkennung arbeitet weiter; es ist also keine Abschaltung auf
/// Dauer, sondern eine Pause fuer die Dauer der Stoerung.
/// ═══════════════════════════════════════════════════════════════════════════
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

    /// <summary>Weckt den Worker: es liegt ein Auftrag an.</summary>
    private static readonly AutoResetEvent _auftrag = new(false);

    /// <summary>Der Worker meldet: Auftrag erledigt.</summary>
    private static readonly AutoResetEvent _fertig = new(false);

    /// <summary>1, solange ein Auftrag laeuft. Wird vom WORKER
    /// zurueckgesetzt, nie vom Aufrufer – haengt der Worker, bleibt der Wert
    /// auf 1 und alle weiteren Abfragen werden uebersprungen. Genau das ist
    /// die Schranke gegen das Thread-Leck.</summary>
    private static int _beschaeftigt;

    /// <summary>Der Worker konnte nicht gestartet werden – dann gibt es die
    /// Erkennung auf diesem System nicht, und es bleibt beim Lasso.</summary>
    private static bool _ausgefallen;

    private static Thread? _worker;
    private static readonly object _startTor = new();

    private static Point _punkt;
    private static volatile bool _ergebnis;

    /// <summary>Liegt an <paramref name="p"/> ein ziehbares Objekt?
    ///
    /// ⚠ DER AUFRUF BLOCKIERT DEN AUFRUFER BIS ZU <paramref name="grenze"/>,
    /// und der Aufrufer ist der UI-Thread – derselbe, der den
    /// <c>WH_MOUSE_LL</c>-Hook bedient. Die Grenze muss deshalb deutlich
    /// unter `LowLevelHooksTimeout` (Vorgabe 300 ms) bleiben, sonst haengt
    /// Windows den Hook still aus und die ganze Geste ist tot.
    ///
    /// Jeder Fehler ergibt <c>false</c> – siehe die Begruendung in
    /// <see cref="ZiehbarRegel"/>: im Zweifel Lasso, nie Drag.
    /// </summary>
    public static bool LiegtObjektUnter(Point p, TimeSpan grenze)
    {
        if (_ausgefallen)
        {
            return false;
        }

        // ⚠ BESETZT HEISST UEBERSPRINGEN, NICHT ANSTELLEN. Ein zweiter Auftrag
        //    waere entweder ein zweiter Thread (das alte Leck) oder eine
        //    Warteschlange, die sich bei einer haengenden Zielanwendung endlos
        //    fuellt. Der Benutzer bekommt dann eben das Lasso – die harmlose
        //    Richtung.
        if (Interlocked.CompareExchange(ref _beschaeftigt, 1, 0) != 0)
        {
            return false;
        }

        if (!WorkerSicherstellen())
        {
            Interlocked.Exchange(ref _beschaeftigt, 0);
            return false;
        }

        _punkt = p;
        _ergebnis = false;

        // ⚠ ALT-SIGNAL VERWERFEN: lief ein frueherer Auftrag in die Grenze,
        //    hat der Worker sein `_fertig` gesetzt, ohne dass noch jemand
        //    wartete. Ein AutoResetEvent bleibt dann signalisiert – der
        //    naechste Wait kaeme sofort durch und lieferte das Ergebnis des
        //    VORIGEN Punktes.
        _fertig.Reset();
        _auftrag.Set();

        // Laeuft die Grenze ab, bleibt `_beschaeftigt` auf 1 stehen: der
        // Worker arbeitet ja noch. Er gibt sich selbst wieder frei.
        return _fertig.WaitOne(grenze) && _ergebnis;
    }

    /// <summary>Startet den Worker beim ersten Bedarf.</summary>
    /// <returns><c>false</c>, wenn kein Worker zur Verfuegung steht.</returns>
    private static bool WorkerSicherstellen()
    {
        lock (_startTor)
        {
            if (_ausgefallen)
            {
                return false;
            }

            if (_worker is not null)
            {
                return true;
            }

            try
            {
                var t = new Thread(WorkerSchleife)
                {
                    // ⚠ HINTERGRUND: ein Vordergrund-Thread in einer
                    //    Endlosschleife wuerde das Beenden der Anwendung
                    //    verhindern.
                    IsBackground = true,
                    Name = "AiMouse.UIA-Worker",
                };

                // COM verlangt STA; das setzt der Laufzeit, nicht wir von Hand.
                t.SetApartmentState(ApartmentState.STA);
                t.Start();
                _worker = t;
                return true;
            }
            catch (Exception)
            {
                // Kein Thread, kein STA – die Erkennung gibt es hier nicht.
                // Nicht erneut versuchen: waere der Versuch teuer und
                // aussichtslos, kostete er bei jedem Halten Zeit.
                _ausgefallen = true;
                _worker = null;
                return false;
            }
        }
    }

    /// <summary>Der eine Worker: wartet auf Auftraege und beantwortet sie.
    ///
    /// ⚠ DAS AUTOMATION-OBJEKT WIRD EINMAL ERZEUGT UND BEHALTEN. Es gehoert
    /// dem STA dieses Threads und darf ihn nicht verlassen; es je Abfrage neu
    /// anzulegen kostete jedes Mal eine COM-Aktivierung.
    /// </summary>
    private static void WorkerSchleife()
    {
        IUIAutomation? automation = null;

        while (true)
        {
            _auftrag.WaitOne();

            Point p = _punkt;
            bool ergebnis = false;

            try
            {
                automation ??= (IUIAutomation)new CUIAutomation();

                IUIAutomationElement? el = automation.ElementFromPoint(
                    new POINT { x = p.X, y = p.Y });

                if (el is not null)
                {
                    ergebnis = ZiehbarRegel.IstZiehbar(
                        ZahlAus(el, UIA_ControlTypePropertyId),
                        WahrheitAus(el, UIA_IsDragPatternAvailablePropertyId),
                        WahrheitAus(el, UIA_IsSelectionItemPatternAvailablePropertyId));
                }
            }
            catch (Exception)
            {
                // UIA nicht verfuegbar, Zugriff verweigert, Element
                // verschwunden – alles derselbe Ausgang: kein Drag.
                //
                // ⚠ DAS OBJEKT WIRD VERWORFEN: ist der Proxy einmal kaputt
                //    (die Zielanwendung ist weg, RPC abgebrochen), bliebe er
                //    es fuer alle weiteren Abfragen. Beim naechsten Auftrag
                //    wird er neu geholt.
                ergebnis = false;
                automation = null;
            }

            _ergebnis = ergebnis;

            // ⚠ REIHENFOLGE: erst melden, DANN freigeben. Andersherum koennte
            //    ein neuer Auftrag hereinkommen und `_fertig` zuruecksetzen,
            //    bevor der Wartende sein Signal gesehen hat.
            _fertig.Set();
            Interlocked.Exchange(ref _beschaeftigt, 0);
        }
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
