namespace AiMouse.Configuration;

/// <summary>One entry of <c>prompts.json</c> / one row of the gesture context menu.</summary>
internal sealed class PromptItem
{
    public string Title { get; set; } = string.Empty;

    public string Prompt { get; set; } = string.Empty;

    public static IReadOnlyList<PromptItem> Defaults { get; } =
    [
        new PromptItem
        {
            Title = "Extract Text (OCR)",
            Prompt = "Act as an OCR system. Extract all visible text from this image precisely without added commentary.",
        },
        new PromptItem
        {
            Title = "Describe Image",
            Prompt = "Describe the contents and key visual elements of this image in detail.",
        },
        new PromptItem
        {
            Title = "Analyze Error / Code",
            Prompt = "Analyze the error message or code shown in this snippet and propose a solution.",
        },
    ];
}
