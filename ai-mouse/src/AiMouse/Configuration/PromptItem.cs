using AiMouse.Localization;

namespace AiMouse.Configuration;

/// <summary>One entry of <c>prompts.json</c> / one row of the gesture context menu.</summary>
internal sealed class PromptItem
{
    public string Title { get; set; } = string.Empty;

    public string Prompt { get; set; } = string.Empty;

    /// <summary>Rueckfall, wenn der Server keine Fragen geliefert hat.
    ///
    /// ⚠ AUSDRUECKSKOERPER (`=>`) UND KEIN INITIALISIERER: mit `{ get; } = […]`
    /// entstuende die Liste EINMALIG beim ersten Zugriff, und die Titel trugen
    /// dann fuer immer die Sprache, die in genau diesem Moment galt. Beim
    /// Start ist das die Vorgabe – ein Sprachwechsel im Einstellungsdialog
    /// erreichte sie also nie, und beim naechsten Zugriff frueher im Ablauf
    /// waere sogar die einkompilierte Sprache verloren.
    ///
    /// Der PROMPT bleibt englisch: er geht an das Modell, dort ist die Sprache
    /// eine Eigenschaft des Auftrags und keine der Anzeige.
    /// </summary>
    public static IReadOnlyList<PromptItem> Defaults =>
    [
        new PromptItem
        {
            Title = Texte.FrageOcr,
            Prompt = "Act as an OCR system. Extract all visible text from this image precisely without added commentary.",
        },
        new PromptItem
        {
            Title = Texte.FrageBeschreiben,
            Prompt = "Describe the contents and key visual elements of this image in detail.",
        },
        new PromptItem
        {
            Title = Texte.FrageFehler,
            Prompt = "Analyze the error message or code shown in this snippet and propose a solution.",
        },
    ];
}
