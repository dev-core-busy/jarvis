namespace AiMouse.Vision;

/// <summary>
/// Macht aus dem, was jemand eingetippt hat, die BASISADRESSE des Servers.
///
/// ⚠ UMGEBAUT FUER JARVIS (2026-09-09). Vorher setzte diese Klasse eine
/// <c>/v1/chat/completions</c>-Route zusammen, weil die Anwendung direkt mit
/// einem OpenAI-kompatiblen Server sprach. Jarvis hat eigene Routen
/// (<c>/api/login</c>, <c>/api/ai-mouse/analyze</c>), die der Client selbst
/// anhaengt – gebraucht wird also nur noch der Rumpf.
///
/// Der Grund fuer die Klasse bleibt derselbe: ein Administrator tippt mal
/// <c>host</c>, mal <c>https://host/</c>, mal versehentlich eine vollstaendige
/// Route. Ohne Normalisierung entsteht daraus eine Adresse mit doppeltem
/// Schraegstrich oder doppeltem Pfad, und der Server antwortet mit einem
/// nackten 404, das wie ein Ausfall aussieht.
/// </summary>
internal static class EndpointResolver
{
    /// <summary>
    /// Basisadresse ohne abschliessenden Schraegstrich, oder leer.
    ///
    /// **Leer heisst "unbrauchbar"** und wird vom Aufrufer als Bedienfehler
    /// gemeldet – nie als Netzproblem. Ein geratener Rueckfall (etwa
    /// localhost) waere hier falsch: er erzeugt eine Fehlermeldung ueber einen
    /// Server, den der Benutzer nie gemeint hat.
    ///
    /// Idempotent: auf eine bereits saubere Adresse angewandt aendert sich
    /// nichts.
    /// </summary>
    public static string Basis(string endpoint)
    {
        string getrimmt = (endpoint ?? string.Empty).Trim();
        if (getrimmt.Length == 0)
        {
            return string.Empty;
        }

        // Ohne Schema ist es kein absoluter URI – https ergaenzen statt
        // abzulehnen. Ein Administrator, der "dp.example.de" eintippt, meint
        // keinen anderen Server, und http waere hier die falsche Vorgabe:
        // ueber die Leitung geht ein Kennwort.
        if (!getrimmt.Contains("://", StringComparison.Ordinal))
        {
            getrimmt = "https://" + getrimmt;
        }

        if (!Uri.TryCreate(getrimmt, UriKind.Absolute, out Uri? uri) ||
            (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps))
        {
            return string.Empty;
        }

        // Abfrageteil und Fragment haben hier keine Bedeutung und landeten
        // sonst mitten im Pfad, sobald eine Route angehaengt wird.
        string rumpf = uri.GetLeftPart(UriPartial.Path).TrimEnd('/');

        // Eine versehentlich mitgegebene Route abschneiden: wer die Adresse aus
        // der Anleitung kopiert, hat schnell "/api/..." mit dabei.
        int api = rumpf.IndexOf("/api/", StringComparison.OrdinalIgnoreCase);
        if (api > 0)
        {
            rumpf = rumpf[..api];
        }

        return rumpf;
    }
}
