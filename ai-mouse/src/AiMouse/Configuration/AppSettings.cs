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
}
