using System.Text.Json.Serialization;
using AiMouse.Configuration;

namespace AiMouse;

/// <summary>
/// Source-generated serializer metadata. Reflection-based serialization is switched
/// off in the csproj (<c>JsonSerializerIsReflectionEnabledByDefault=false</c>), so
/// every type crossing the JSON boundary MUST be listed here.
///
/// ⚠ EIN FEHLENDER TYP FAELLT ERST ZUR LAUFZEIT AUF – und dann mit einer
/// Ausnahme mitten in der Anfrage, nicht beim Uebersetzen. Wer hier eine
/// Nutzlast ergaenzt, traegt ihren Typ mit ein.
///
/// Die frueheren OpenAI-Typen (<c>ChatRequest</c>, <c>ChatResponse</c>,
/// <c>ContentPart</c>) sind mit <c>VisionClient</c> entfallen: die Anwendung
/// spricht seit dem 2026-09-09 mit Jarvis, nicht mehr mit einem
/// OpenAI-kompatiblen Server. Die Anfragen sind flache Zeichenketten-Paare,
/// die Antworten werden mit <c>JsonDocument</c> gelesen – das braucht keine
/// Metadaten.
/// </summary>
[JsonSourceGenerationOptions(
    DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    WriteIndented = false)]
[JsonSerializable(typeof(AppSettings))]
[JsonSerializable(typeof(List<PromptItem>))]
[JsonSerializable(typeof(Dictionary<string, string>))]
[JsonSerializable(typeof(string))]
internal partial class AppJsonContext : JsonSerializerContext;
