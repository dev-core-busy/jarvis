using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using AiMouse.Configuration;
using AiMouse.Localization;

using AiMouse;

namespace AiMouse.Vision;

/// <summary>Spricht mit dem Jarvis-Server: Anmeldung und Auswertung.
///
/// ⚠ ERSETZT DEN FRUEHEREN <c>VisionClient</c>, der direkt einen
/// OpenAI-kompatiblen Server ansprach. Der Unterschied ist nicht nur die
/// Adresse:
///
/// * **Kein Modell, kein System-Prompt, keine Temperatur mehr im Client.** Das
///   entscheidet der Server. Stuende es hier, waere der System-Prompt an jedem
///   Arbeitsplatz frei veraenderbar – und damit kein Schutz.
/// * **Anmeldung mit Benutzer und Kennwort statt eines geteilten API-Keys.**
///   Die Berechtigung haengt an der Person, greift auf die vorhandenen
///   Freigabelisten zurueck und steht im Anwesenheits- und Audit-Log.
/// * **Das Token liegt NUR im Arbeitsspeicher.** Es landet nicht in der
///   settings.json: die Datei wird per Netzfreigabe verteilt und liegt im
///   Klartext neben der Exe. Preis ist eine Anmeldung je Programmstart.
/// </summary>
internal sealed class JarvisClient : IDisposable
{
    private readonly HttpClient _http;
    private readonly AppSettings _settings;
    private string _token = string.Empty;

    public JarvisClient(AppSettings settings)
    {
        _settings = settings;
        _http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(Math.Clamp(settings.TimeoutSeconds, 5, 3600)),
        };
    }

    /// <summary>Ist eine Sitzung vorhanden? Sagt NICHT, ob sie noch gilt.</summary>
    public bool Angemeldet => _token.Length > 0;

    /// <summary>Meldet ab – nur lokal. Der Server kennt keine Sitzungstabelle.</summary>
    public void Abmelden() => _token = string.Empty;

    /// <summary>Das aktuelle Sitzungstoken – zum Ablegen in der Registry.
    ///
    /// ⚠ NUR LESEN, und nur fuer diesen einen Zweck. Es traegt laut
    /// Projektregel die VOLLE Sitzung; wer es weitergibt, gibt die Anmeldung
    /// weiter. `ConfigStore.SaveToken` verschluesselt es deshalb per DPAPI.
    /// </summary>
    public string Token => _token;

    /// <summary>Ein gespeichertes Token uebernehmen (Programmstart).
    ///
    /// Es wird NICHT geprueft – das kostete einen Serveraufruf beim Start und
    /// beantwortete doch nur die Frage, die der erste echte Aufruf ohnehin
    /// stellt. Ist es abgelaufen, antwortet der Server mit 401, und der
    /// vorhandene Weg fragt neu (`AnmeldungNoetigException`).
    /// </summary>
    public void TokenSetzen(string? token)
    {
        _token = string.IsNullOrWhiteSpace(token) ? string.Empty : token.Trim();
    }

    /// <summary>Uebernimmt die Sitzung eines anderen Clients.
    ///
    /// ⚠ NOETIG, WEIL DER CLIENT BEI JEDER EINSTELLUNGSAENDERUNG NEU ENTSTEHT:
    /// das Zeitlimit steckt im <see cref="HttpClient"/> und laesst sich nach
    /// dem ersten Request nicht mehr aendern. Ohne diese Uebergabe verlor jedes
    /// Speichern im Einstellungsdialog die Anmeldung – und der Benutzer wurde
    /// beim naechsten Rahmen erneut gefragt (gemeldet am 2026-09-09).
    ///
    /// **NUR bei gleicher Serveradresse aufrufen.** Ein Token gilt fuer den
    /// Server, an dem es entstanden ist; anderswo waere es ein 401, der wie ein
    /// Serverfehler aussieht. Der Aufrufer prueft das.
    /// </summary>
    public void SitzungUebernehmen(JarvisClient anderer)
    {
        if (anderer is not null && anderer._token.Length > 0)
        {
            _token = anderer._token;
        }
    }

    /// <summary>Anmeldung. Wirft <see cref="VisionException"/> mit Klartext.
    ///
    /// <paramref name="totp"/> bleibt leer, solange der Server keinen Code
    /// verlangt; verlangt er einen, wirft der erste Versuch
    /// <see cref="TotpNoetigException"/> und der Aufrufer fragt nach.
    /// </summary>
    public async Task AnmeldenAsync(string benutzer, string kennwort, string totp,
                                    CancellationToken ct)
    {
        string basis = EndpointResolver.Basis(_settings.Endpoint);
        if (basis.Length == 0)
        {
            throw new VisionException(Texte.KeinServer);
        }

        var rumpf = new Dictionary<string, string>
        {
            ["username"] = benutzer,
            ["password"] = kennwort,
        };
        if (!string.IsNullOrWhiteSpace(totp))
        {
            rumpf["totp_code"] = totp.Trim();
        }

        using var inhalt = new StringContent(
            JsonSerializer.Serialize(rumpf, AppJsonContext.Default.DictionaryStringString),
            Encoding.UTF8, "application/json");

        JsonElement wurzel;
        try
        {
            using HttpResponseMessage antwort =
                await _http.PostAsync(basis + "/api/login", inhalt, ct).ConfigureAwait(false);
            string roh = await antwort.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            using JsonDocument doc = JsonDocument.Parse(roh);
            wurzel = doc.RootElement.Clone();
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or JsonException)
        {
            // Der Rohtext bleibt in der Meldung: "nicht erreichbar" allein
            // unterscheidet nicht zwischen falschem Namen, Zertifikat und
            // fehlendem Netzweg – und genau das muss der Benutzer wissen.
            throw new VisionException(Texte.NichtErreichbar + e.Message, e);
        }

        if (wurzel.TryGetProperty("success", out JsonElement erf) &&
            erf.ValueKind == JsonValueKind.True)
        {
            _token = wurzel.TryGetProperty("token", out JsonElement t)
                ? (t.GetString() ?? string.Empty) : string.Empty;
            if (_token.Length == 0)
            {
                throw new VisionException(Texte.KeineAntwort);
            }
            return;
        }

        // Zweistufige Anmeldung: der Server sagt es ausdruecklich, statt einen
        // falschen Fehler ("Kennwort falsch") zurueckzugeben.
        if (wurzel.TryGetProperty("requires_totp", out JsonElement r) &&
            r.ValueKind == JsonValueKind.True)
        {
            throw new TotpNoetigException(Fehlertext(wurzel, Texte.EinmalCode));
        }

        throw new VisionException(Fehlertext(wurzel, Texte.KeineAntwort));
    }

    /// <summary>Bildausschnitt und Frage auswerten. Rueckgabe: die Antwort.
    ///
    /// <paramref name="bereiche"/> nimmt auf, was der Lauf zusaetzlich
    /// nachschlagen durfte – der Server liefert das mit, und das Fenster sagt
    /// es dem Benutzer. Ohne diese Angabe ist eine Antwort mit nachgeschlagenem
    /// Hintergrund von einer ohne nicht zu unterscheiden.
    /// </summary>
    public async Task<string> AnalysierenAsync(string frage, string bildDataUri,
                                               List<string> bereiche,
                                               CancellationToken ct)
    {
        if (!Angemeldet)
        {
            throw new AnmeldungNoetigException(Texte.AnmeldungFehlt);
        }
        string basis = EndpointResolver.Basis(_settings.Endpoint);
        if (basis.Length == 0)
        {
            throw new VisionException(Texte.KeinServer);
        }

        var rumpf = new Dictionary<string, string>
        {
            ["image"] = bildDataUri,
            ["prompt"] = frage,
            ["lang"] = Texte.IstEnglisch ? "en" : "de",
        };

        using var nachricht = new HttpRequestMessage(
            HttpMethod.Post, basis + "/api/ai-mouse/analyze")
        {
            Content = new StringContent(
                JsonSerializer.Serialize(rumpf, AppJsonContext.Default.DictionaryStringString),
                Encoding.UTF8, "application/json"),
        };
        nachricht.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);

        HttpResponseMessage antwort;
        string roh;
        try
        {
            antwort = await _http.SendAsync(nachricht, ct).ConfigureAwait(false);
            roh = await antwort.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
        {
            throw new VisionException(Texte.NichtErreichbar + e.Message, e);
        }

        // 401 heisst: das Token gilt nicht mehr. Der Aufrufer soll die
        // Anmeldemaske zeigen, nicht eine Fehlermeldung – deshalb ein eigener
        // Ausnahmetyp und nicht der allgemeine.
        if (antwort.StatusCode == HttpStatusCode.Unauthorized)
        {
            _token = string.Empty;
            antwort.Dispose();
            throw new AnmeldungNoetigException(Texte.Abgelaufen);
        }

        JsonElement wurzel;
        try
        {
            using JsonDocument doc = JsonDocument.Parse(roh);
            wurzel = doc.RootElement.Clone();
        }
        catch (JsonException)
        {
            // Keine JSON-Antwort: ein Proxy oder eine Fehlerseite. Der Rohtext
            // ist dann die einzige Spur – gekuerzt, damit kein HTML-Dokument
            // im Meldungsfenster landet.
            antwort.Dispose();
            throw new VisionException(Texte.KeineAntwort + " (HTTP "
                + (int)antwort.StatusCode + ") " + Kurz(roh));
        }
        antwort.Dispose();

        if (wurzel.TryGetProperty("ok", out JsonElement okE) &&
            okE.ValueKind == JsonValueKind.True)
        {
            if (wurzel.TryGetProperty("bereiche", out JsonElement b) &&
                b.ValueKind == JsonValueKind.Array)
            {
                foreach (JsonElement e in b.EnumerateArray())
                {
                    string? s = e.GetString();
                    if (!string.IsNullOrWhiteSpace(s)) { bereiche.Add(s); }
                }
            }
            string text = wurzel.TryGetProperty("text", out JsonElement t)
                ? (t.GetString() ?? string.Empty) : string.Empty;
            return text.Length > 0 ? text : throw new VisionException(Texte.KeineAntwort);
        }

        // 403 vom Freigabe-Gate: eigener Text mit dem Weg zur Abhilfe. Die
        // Meldung des Servers steht dahinter, damit der Grund nicht verloren
        // geht (er unterscheidet Freigabe von abgeschaltetem Skill).
        string fehler = Fehlertext(wurzel, Texte.KeineAntwort);
        if (antwort.StatusCode == HttpStatusCode.Forbidden)
        {
            throw new VisionException(Texte.KeineFreigabe + "\n\n" + fehler);
        }
        throw new VisionException(fehler);
    }

    /// <summary>Holt die Fragen des angemeldeten Benutzers vom Server.
    ///
    /// ⚠ SIE LAGEN BIS 2026-09-09 IN EINER prompts.json NEBEN DER EXE. Jetzt
    /// kommen sie vom Server: sie folgen dem BENUTZER und nicht dem Rechner,
    /// und ein Administrator kann gemeinsame Fragen fuer alle setzen. Gepflegt
    /// werden sie im Portal (Kachel "AI Mouse").
    ///
    /// Ein Fehlschlag ist NICHT toedlich: der Aufrufer behaelt die zuletzt
    /// geholte Liste. Ohne Fragen waere die Geste nutzlos – eine leere Liste
    /// nach einem Netzhaenger waere der schlechtere Ausgang.
    /// </summary>
    public async Task<List<PromptItem>> FragenAsync(CancellationToken ct)
    {
        if (!Angemeldet)
        {
            throw new AnmeldungNoetigException(Texte.AnmeldungFehlt);
        }
        string basis = EndpointResolver.Basis(_settings.Endpoint);
        if (basis.Length == 0)
        {
            throw new VisionException(Texte.KeinServer);
        }

        using var nachricht = new HttpRequestMessage(
            HttpMethod.Get, basis + "/api/ai-mouse/fragen");
        nachricht.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _token);

        using HttpResponseMessage antwort =
            await _http.SendAsync(nachricht, ct).ConfigureAwait(false);
        if (antwort.StatusCode == HttpStatusCode.Unauthorized)
        {
            _token = string.Empty;
            throw new AnmeldungNoetigException(Texte.Abgelaufen);
        }
        string roh = await antwort.Content.ReadAsStringAsync(ct).ConfigureAwait(false);

        var raus = new List<PromptItem>();
        using JsonDocument doc = JsonDocument.Parse(roh);
        if (doc.RootElement.TryGetProperty("fragen", out JsonElement arr)
            && arr.ValueKind == JsonValueKind.Array)
        {
            foreach (JsonElement e in arr.EnumerateArray())
            {
                string titel = e.TryGetProperty("titel", out JsonElement tt)
                    ? (tt.GetString() ?? string.Empty) : string.Empty;
                string prompt = e.TryGetProperty("prompt", out JsonElement pp)
                    ? (pp.GetString() ?? string.Empty) : string.Empty;
                // Beides muss da sein: ein Menueeintrag ohne Anweisung waere
                // ein Knopf, der eine leere Frage stellt.
                if (titel.Length > 0 && prompt.Length > 0)
                {
                    raus.Add(new PromptItem { Title = titel, Prompt = prompt });
                }
            }
        }
        return raus;
    }

    /// <summary>Zieht die Fehlermeldung aus einer Serverantwort.
    ///
    /// Jarvis benutzt <c>error</c> (eigene Endpunkte) und <c>detail</c>
    /// (FastAPI bei 401/403/422) – beide werden gelesen. Nur eines zu kennen
    /// hat im Projekt schon einmal dazu gefuehrt, dass eine vorhandene
    /// Begruendung nicht angezeigt wurde.
    /// </summary>
    private static string Fehlertext(JsonElement wurzel, string rueckfall)
    {
        foreach (string feld in new[] { "error", "detail", "message" })
        {
            if (wurzel.TryGetProperty(feld, out JsonElement e) &&
                e.ValueKind == JsonValueKind.String)
            {
                string? s = e.GetString();
                if (!string.IsNullOrWhiteSpace(s)) { return s!; }
            }
        }
        return rueckfall;
    }

    private static string Kurz(string s) =>
        s.Length <= 300 ? s : s[..300] + "…";

    public void Dispose() => _http.Dispose();
}

/// <summary>Die Sitzung fehlt oder gilt nicht mehr – Anmeldemaske zeigen.</summary>
internal sealed class AnmeldungNoetigException : VisionException
{
    public AnmeldungNoetigException(string message) : base(message) { }
}

/// <summary>Der Server verlangt zusaetzlich einen Einmal-Code.</summary>
internal sealed class TotpNoetigException : VisionException
{
    public TotpNoetigException(string message) : base(message) { }
}

/// <summary>Fachlicher Fehlschlag mit einem Text fuer die Oberflaeche.
///
/// Lag bis 2026-09-09 in <c>VisionClient.cs</c> und ist mit dem Umbau
/// hierher gewandert – der Name bleibt, damit die Aufrufer (Tray, Fenster)
/// unveraendert fangen koennen.
/// </summary>
internal class VisionException : Exception
{
    public VisionException(string message) : base(message) { }

    public VisionException(string message, Exception inner) : base(message, inner) { }
}
