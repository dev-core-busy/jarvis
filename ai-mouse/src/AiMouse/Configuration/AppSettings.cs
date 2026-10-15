namespace AiMouse.Configuration;

/// <summary>Contents of <c>settings.json</c>, sitting next to the executable.
///
/// ⚠ ANGEPASST FUER JARVIS (2026-09-09). Vorher sprach die Anwendung direkt mit
/// einem OpenAI-kompatiblen Server (Ollama/LM Studio) und trug dessen Modell,
/// Temperatur und System-Prompt hier. **Das ist bewusst entfallen:** all diese
/// Entscheidungen trifft jetzt der Server – er kennt das aktive LLM-Profil, den
/// System-Prompt und die freigeschalteten Werkzeug-Bereiche. Stuenden sie hier,
/// waeren sie an jedem Arbeitsplatz frei veraenderbar, und der System-Prompt
/// waere kein Schutz mehr, sondern eine Empfehlung.
///
/// Was BLEIBT, sind reine Client-Einstellungen: wo der Server steht, wie die
/// Anwendung heisst und aussieht, und wie sich die Geste verhaelt.
/// </summary>
internal sealed class AppSettings
{
    /// <summary>
    /// Basisadresse des Jarvis-Servers, z. B. <c>https://dp.example.de</c>.
    /// Wird beim Herunterladen des Pakets serverseitig eingesetzt – also auf
    /// die Adresse, unter der der Administrator den Server selbst erreicht.
    /// </summary>
    public string Endpoint { get; set; } = string.Empty;

    /// <summary>Anzeigename des Hauses (Fenstertitel, Tray, Anmeldemaske).
    ///
    /// ⚠ SIE STEHT HIER UND NICHT NUR IM SERVERABRUF, und das ist der Kern des
    /// Brandings dieser Anwendung: die ANMELDEMASKE erscheint, bevor es eine
    /// Sitzung gibt – ein Abruf erreicht sie nicht. Dieselbe Loesung wie die
    /// <c>&lt;meta name="marke"&gt;</c> im Fenster der Jira-Erweiterung.
    /// </summary>
    public string Marke { get; set; } = "Jarvis";

    /// <summary>Akzentfarbe als <c>#RRGGBB</c>. Leer/unbrauchbar = Vorgabe.</summary>
    public string Akzent { get; set; } = "#9B59B6";

    /// <summary>Zuletzt benutzter Benutzername – reine Bequemlichkeit.
    ///
    /// Ein KENNWORT steht hier bewusst nie: die Datei wird per Netzfreigabe
    /// verteilt und liegt im Klartext neben der Exe.
    /// </summary>
    public string Benutzer { get; set; } = string.Empty;

    /// <summary>Oberflaechensprache: <c>de</c> oder <c>en</c>.</summary>
    public string Sprache { get; set; } = "de";

    /// <summary>Zeitlimit einer Anfrage. Der Server deckelt zusaetzlich selbst.</summary>
    public int TimeoutSeconds { get; set; } = 120;

    /// <summary>Pixels the pointer must travel before the gesture takes over.</summary>
    public int DragThreshold { get; set; } = 8;

    /// <summary>Put the model's answer on the clipboard as soon as it arrives.</summary>
    public bool CopyResultToClipboard { get; set; }

    /// <summary>Taste, die den Rechtsklick an die Anwendung durchreicht statt
    /// ihn fuer die Lasso-Geste zu nehmen: <c>none</c>, <c>ctrl</c>,
    /// <c>alt</c> oder <c>shift</c>.
    ///
    /// ⚠ VORGABE `ctrl`: ohne sie ist Windows' Right-Drag („Datei mit rechter
    /// Maustaste ziehen") blockiert, solange AI Mouse laeuft. Begruendung der
    /// Tastenwahl in <c>Input/GestenTaste.cs</c>.
    /// </summary>
    public string RightDragKey { get; set; } = "ctrl";

    /// <summary>Taste, die die GESTE ausloest – die Umkehrung von
    /// <see cref="RightDragKey"/>.
    ///
    /// ⚠ DIE BEIDEN SIND ENTGEGENGESETZT, UND DAS IST DER GANZE PUNKT:
    ///   * <c>RightDragKey</c> (Vorgabe Strg): die Geste nimmt JEDEN
    ///     Rechtsklick, die Taste reicht ihn ausnahmsweise durch.
    ///   * <c>GestureKey</c> (Vorgabe leer): der Rechtsklick gehoert normal
    ///     der Anwendung, und nur MIT der Taste greift die Geste.
    ///
    /// Vorgabe ist "" = wie bisher. Wer eine Gestentaste setzt, dreht das
    /// Verhalten um: die rechte Maustaste funktioniert dann ueberall so, wie
    /// Windows es vorsieht, und AI Mouse meldet sich nur auf Anforderung.
    ///
    /// ⚠ IST DIESES FELD GESETZT, IST <c>RightDragKey</c> BEDEUTUNGSLOS –
    /// der Klick geht dann ohnehin an die Anwendung. Aufgeloest wird das an
    /// EINER Stelle (<c>TrayApplicationContext.TastenAus</c>), damit
    /// Oberflaeche und Verhalten nicht auseinanderlaufen koennen.
    /// </summary>
    public string GestureKey { get; set; } = string.Empty;

    /// <summary>Tastenkombination, die die Anwendung STARTET, z. B.
    /// <c>CTRL+ALT+A</c>. Leer = keine.
    ///
    /// ⚠ SIE WIRD NICHT VON DER ANWENDUNG REGISTRIERT, sondern von Windows:
    /// ein laufendes Programm kann `RegisterHotKey` rufen, ein NICHT laufendes
    /// nicht – und genau das soll die Kombination starten. Getragen wird sie
    /// deshalb von einer Verknuepfung im Startmenue (<see cref="AiMouse.Start.Startwege"/>).
    ///
    /// Gespeichert in der lesbaren Wortform, nicht als Zahl – Begruendung in
    /// <c>HotkeyWort.AlsText</c>.
    /// </summary>
    public string StartHotkey { get; set; } = string.Empty;

    /// <summary>Verknuepfung im Autostart-Ordner anlegen.
    ///
    /// ⚠ VORGABE AUS. Ein Programm, das sich ungefragt in den Autostart
    /// eintraegt, ist ein Eingriff in den Rechner des Benutzers – und es waere
    /// bei einem Update eine abschaltende Aenderung in die falsche Richtung
    /// (ploetzlich startet etwas mit, das vorher nicht mitstartete).
    /// </summary>
    public bool MitWindowsStarten { get; set; }
}
