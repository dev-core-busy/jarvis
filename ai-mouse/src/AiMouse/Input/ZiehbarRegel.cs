namespace AiMouse.Input;

/// <summary>Entscheidet aus den UIA-Merkmalen eines Elements, ob es ziehbar ist.
///
/// ⚠ WARUM DAS EINE EIGENE, COM-FREIE KLASSE IST: die UIA-Abfrage
/// (<see cref="ZiehbarPruefer"/>) laesst sich hier nicht ausfuehren – sie
/// braucht Windows. Die ENTSCHEIDUNG dagegen ist reine Rechnerei und wird
/// deshalb getrennt gehalten und gegen echte Faelle gemessen. Dieselbe
/// Aufteilung wie bei <c>LinkZiel</c> und <c>Markdown</c>.
///
/// ⚠ DAS IST EINE HEURISTIK, KEINE GARANTIE – und das ist keine Nachlaessigkeit,
/// sondern die Eigenschaft der Sache: „ziehbar" ist unter Windows KEIN Zustand,
/// den man abfragen kann. Er entsteht erst dadurch, dass die Anwendung auf
/// gedrueckte Taste + Bewegung mit <c>DoDragDrop</c> reagiert. UIA kennt zwar
/// <c>IsDragPatternAvailable</c>, aber Explorer, Office und die Browser
/// implementieren es nicht – die Abfrage sagt dort „nein", obwohl man ziehen
/// kann. Deshalb entscheidet zusaetzlich der Elementtyp.
///
/// ⚠ FAIL-SAFE IST „NICHT ZIEHBAR". Die beiden Fehlerlagen sind NICHT gleich
/// schwer: wer faelschlich kein Drag bekommt, zieht ein Lasso – laestig, aber
/// harmlos und sofort erkennbar. Wer faelschlich ein Drag bekommt, VERSCHIEBT
/// womoeglich eine Datei, ohne es zu wollen. Im Zweifel also nein.
/// </summary>
internal static class ZiehbarRegel
{
    // ── Elementtypen (UIA_*ControlTypeId, aus UIAutomationClient.idl) ───────
    public const int Button = 50000;
    public const int Hyperlink = 50005;
    public const int Image = 50006;
    public const int ListItem = 50007;
    public const int List = 50008;
    public const int Edit = 50004;
    public const int Text = 50020;
    public const int TreeItem = 50024;
    public const int Custom = 50025;
    public const int Group = 50026;
    public const int DataItem = 50029;
    public const int Document = 50030;
    public const int Pane = 50033;
    public const int Window = 50032;

    /// <summary>Typen, die in der Praxis ein ziehbares Objekt DARSTELLEN.
    ///
    /// Bewusst kurz und bewusst ohne <c>Text</c>, <c>Image</c> im Dokument,
    /// <c>Edit</c> und <c>Button</c>:
    ///   * <c>Text</c>/<c>Document</c>/<c>Edit</c> – dort zieht man eine
    ///     Auswahl, kein Objekt; ein durchgereichter Rechtsklick oeffnet
    ///     stattdessen das Kontextmenue mitten in der Geste.
    ///   * <c>Button</c>, <c>Pane</c>, <c>Group</c>, <c>Window</c> – Flaechen
    ///     und Bedienelemente, keine Objekte.
    ///   * <c>List</c>/<c>Tree</c> ohne <c>Item</c> ist der LEERE Bereich der
    ///     Liste. Genau dort will man das Lasso behalten.
    /// </summary>
    private static readonly int[] Objekttypen =
    [
        ListItem,     // Datei/Ordner im Explorer, Mail in Outlook, Zeile in Listen
        TreeItem,     // Ordner im Navigationsbaum
        DataItem,     // Zeile in Detailansichten und Tabellen
        Hyperlink,    // Link im Browser – wird als Verknuepfung gezogen
        Image,        // Bild im Browser oder in einer Galerie
    ];

    /// <summary>Ist an dieser Stelle ein Objekt, das man ziehen kann?</summary>
    /// <param name="controlType">UIA ControlType des Elements unter dem Zeiger.</param>
    /// <param name="dragPattern">Meldet das Element <c>IsDragPatternAvailable</c>?</param>
    /// <param name="auswaehlbar">Meldet es <c>IsSelectionItemPatternAvailable</c>?</param>
    public static bool IstZiehbar(int controlType, bool dragPattern, bool auswaehlbar = false)
    {
        // (1) Sagt die Anwendung es selbst, gilt das – unabhaengig vom Typ.
        //     Das ist die einzige Auskunft, die keine Vermutung ist.
        if (dragPattern)
        {
            return true;
        }

        // (2) Sonst entscheidet der Typ.
        foreach (int t in Objekttypen)
        {
            if (t == controlType)
            {
                return true;
            }
        }

        // (3) ⚠ EIN „CUSTOM"-ELEMENT ZAEHLT NUR MIT ZUSAETZLICHEM BELEG.
        //     Der moderne Explorer (DirectUI) und viele Anwendungen melden
        //     `Custom` fuer so gut wie alles – als Freibrief waere das die
        //     Aufhebung der ganzen Regel. Erst zusammen mit
        //     `IsSelectionItemPatternAvailable` ist es ein EINTRAG in einer
        //     Auswahl, also ein Objekt.
        return controlType == Custom && auswaehlbar;
    }
}
