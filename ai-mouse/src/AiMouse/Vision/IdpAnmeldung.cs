using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using AiMouse.Localization;

namespace AiMouse.Vision;

/// <summary>Anmeldung ueber das Firmenkonto (IdP) per Systembrowser und
/// Ruecksprung auf diesen Rechner (RFC 8252, "Loopback").
///
/// ABLAUF: Prueffolge (verifier) und Zustand erzeugen → auf
/// <c>127.0.0.1:&lt;freier Port&gt;/jarvis-anmeldung/&lt;zufall&gt;/</c> lauschen →
/// Systembrowser auf <c>/api/login/oidc/start?app=ai-maus&amp;…</c> →
/// der Server meldet beim IdP an und leitet mit einem Einmal-Code hierher zurueck
/// → der Code wird zusammen mit der Prueffolge an
/// <c>/api/login/oidc/app-einloesen</c> geschickt (das macht
/// <see cref="JarvisClient.FirmenkontoAnmeldenAsync"/>).
///
/// WARUM SO UND NICHT ANDERS:
/// * **Jarvis bleibt der einzige Client beim IdP** – an der Registrierung dort
///   aendert sich nichts. Der Einmal-Code ist ein Code von JARVIS, nicht vom IdP.
/// * **PKCE (S256):** der Code allein ist wertlos. Wer ihn mitliest (Verlauf des
///   Browsers, ein anderes Programm auf dem Rechner), kann ihn ohne die
///   Prueffolge nicht einloesen – die verlaesst diesen Prozess nie.
/// * **Zustand:** ein fremder Aufruf auf den Lauschport (eine Webseite, die
///   <c>127.0.0.1</c> anspricht) wird am Zustand erkannt und verworfen.
/// * **NUR die Loopback-Adresse, nie <c>0.0.0.0</c>:** sonst waere der Port aus
///   dem Netz erreichbar. <c>TcpListener</c> statt <c>HttpListener</c>, weil
///   http.sys je nach Windows-Fassung fuer eine Adresse eine URL-Reservierung
///   verlangt, die ein gewoehnlicher Benutzer nicht hat.
/// </summary>
internal static class IdpAnmeldung
{
    /// <summary>So lange wartet die AI-Maus auf die Rueckkehr aus dem Browser.</summary>
    public static readonly TimeSpan Zeitgrenze = TimeSpan.FromMinutes(5);

    /// <summary>Pfad-Praefix des Ruecksprungs; dahinter steht ein Zufallsteil.</summary>
    public const string PfadPraefix = "/jarvis-anmeldung/";

    /// <summary>Fehlerkennungen des Servers, fuer die es einen eigenen Text gibt.</summary>
    public static readonly string[] Fehlerkennungen =
    [
        "nicht_eingerichtet", "zu_viele", "abgelaufen", "abgebrochen",
        "nicht_erreichbar", "konfiguration", "idp", "token", "schluessel", "name",
        "lokal", "gesperrt", "keine_freigabe", "pruefung", "lizenz",
    ];

    // ── reine Hilfsfunktionen (ohne Netz, im Waechter nachgerechnet) ──────────

    /// <summary>base64url ohne Auffuellung (RFC 7636, Anhang A).</summary>
    public static string B64Url(byte[] daten) =>
        Convert.ToBase64String(daten).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    /// <summary>Prueffolge: 32 Zufallsbytes → 43 Zeichen.</summary>
    public static string NeuerVerifier() => B64Url(RandomNumberGenerator.GetBytes(32));

    /// <summary>Zustand: 16 Zufallsbytes → 22 Zeichen.</summary>
    public static string NeuerZustand() => B64Url(RandomNumberGenerator.GetBytes(16));

    /// <summary>S256: base64url(SHA-256(ASCII(verifier))).</summary>
    public static string Challenge(string verifier) =>
        B64Url(SHA256.HashData(Encoding.ASCII.GetBytes(verifier)));

    /// <summary>Adresse, mit der der Systembrowser die Anmeldung beginnt.</summary>
    public static string StartAdresse(string basis, string challenge, string zustand, string rueck) =>
        basis.TrimEnd('/') + "/api/login/oidc/start?app=ai-maus"
        + "&challenge=" + Uri.EscapeDataString(challenge)
        + "&zustand=" + Uri.EscapeDataString(zustand)
        + "&rueck=" + Uri.EscapeDataString(rueck);

    /// <summary>Zerlegt einen Abfrageteil (<c>a=1&amp;b=2</c>, ohne <c>?</c>).
    /// Doppelte Schluessel: der erste gilt.</summary>
    public static Dictionary<string, string> Abfrage(string abfrage)
    {
        var d = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (string teil in (abfrage ?? string.Empty).Split('&'))
        {
            if (teil.Length == 0) { continue; }
            int gl = teil.IndexOf('=');
            string k = Uri.UnescapeDataString((gl < 0 ? teil : teil[..gl]).Replace('+', ' '));
            string v = gl < 0 ? string.Empty : Uri.UnescapeDataString(teil[(gl + 1)..].Replace('+', ' '));
            d.TryAdd(k, v);
        }
        return d;
    }

    /// <summary>Wertet die Rueckkehr aus. Rueckgabe: (Code, Fehlerkennung).
    ///
    /// ⚠ DER ZUSTAND WIRD ZUERST GEPRUEFT – passt er nicht, zaehlt weder ein
    /// Code noch eine Fehlerkennung: beides koennte von einer fremden Seite
    /// stammen. Verglichen wird in fester Zeit.</summary>
    public static (string Code, string Fehler) Auswerten(Dictionary<string, string> q, string zustand)
    {
        q.TryGetValue("zustand", out string? z);
        if (string.IsNullOrEmpty(z) || string.IsNullOrEmpty(zustand) ||
            !CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(z),
                                                     Encoding.UTF8.GetBytes(zustand)))
        {
            return (string.Empty, "zustand");
        }
        if (q.TryGetValue("fehler", out string? f) && !string.IsNullOrWhiteSpace(f))
        {
            return (string.Empty, f.Trim());
        }
        if (q.TryGetValue("code", out string? c) && !string.IsNullOrWhiteSpace(c))
        {
            return (c.Trim(), string.Empty);
        }
        return (string.Empty, "abgebrochen");
    }

    /// <summary>Text zu einer Fehlerkennung; Unbekanntes nennt die Kennung.</summary>
    public static string FehlerText(string kennung) => kennung switch
    {
        "nicht_eingerichtet" => Texte.IdpNichtEingerichtet,
        "zu_viele" => Texte.IdpZuViele,
        "abgelaufen" => Texte.IdpAbgelaufen,
        "abgebrochen" => Texte.IdpAbgebrochen,
        "nicht_erreichbar" => Texte.IdpNichtErreichbar,
        "konfiguration" => Texte.IdpKonfiguration,
        "idp" => Texte.IdpAbgelehnt,
        "token" or "schluessel" => Texte.IdpUngueltig,
        "name" => Texte.IdpName,
        "lokal" => Texte.IdpLokal,
        "gesperrt" => Texte.IdpGesperrt,
        "keine_freigabe" => Texte.IdpKeineFreigabe,
        "pruefung" => Texte.IdpPruefung,
        "lizenz" => Texte.IdpLizenz,
        "zustand" => Texte.IdpZustand,
        "zeit" => Texte.IdpZeit,
        _ => Texte.IdpUnbekannt(kennung),
    };

    // ── der Ruecksprung auf diesen Rechner ────────────────────────────────────

    /// <summary>Wartet auf die Rueckkehr aus dem Browser und liefert den
    /// Einmal-Code. Wirft <see cref="VisionException"/> mit Klartext.
    ///
    /// <paramref name="oeffnen"/> bekommt die Startadresse (Systembrowser);
    /// im Normalfall <see cref="BrowserOeffnen"/>.</summary>
    public static async Task<string> CodeHolenAsync(string basis, string challenge,
                                                    string zustand, Action<string> oeffnen,
                                                    CancellationToken ct)
    {
        // Port 0: das System waehlt einen freien. NUR Loopback.
        var lauscher = new TcpListener(IPAddress.Loopback, 0);
        lauscher.Start();
        try
        {
            int port = ((IPEndPoint)lauscher.LocalEndpoint).Port;
            string pfad = PfadPraefix + NeuerZustand() + "/";
            string rueck = "http://127.0.0.1:" + port + pfad;

            oeffnen(StartAdresse(basis, challenge, zustand, rueck));

            using var zeit = CancellationTokenSource.CreateLinkedTokenSource(ct);
            zeit.CancelAfter(Zeitgrenze);
            while (true)
            {
                TcpClient verbindung;
                try
                {
                    verbindung = await lauscher.AcceptTcpClientAsync(zeit.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException) when (!ct.IsCancellationRequested)
                {
                    throw new VisionException(FehlerText("zeit"));
                }
                using (verbindung)
                {
                    (bool fertig, string code) = await AnfrageBearbeitenAsync(
                        verbindung, pfad, zustand, zeit.Token).ConfigureAwait(false);
                    if (fertig)
                    {
                        return code;
                    }
                }
            }
        }
        finally
        {
            lauscher.Stop();
        }
    }

    /// <summary>Eine Anfrage auf dem Lauschport. (true, Code) = erledigt;
    /// (false, "") = nicht unsere (z. B. favicon), weiter warten.
    /// Fehler der Anmeldung werfen eine <see cref="VisionException"/>.</summary>
    private static async Task<(bool, string)> AnfrageBearbeitenAsync(
        TcpClient verbindung, string pfad, string zustand, CancellationToken ct)
    {
        NetworkStream strom = verbindung.GetStream();
        strom.ReadTimeout = 10000;
        string zeile = await KopfLesenAsync(strom, ct).ConfigureAwait(false);

        // "GET /pfad?abfrage HTTP/1.1"
        string[] teile = zeile.Split(' ');
        if (teile.Length < 2 || teile[0] != "GET")
        {
            await AntwortenAsync(strom, 405, Texte.IdpSeiteFehler, ct).ConfigureAwait(false);
            return (false, string.Empty);
        }
        string ziel = teile[1];
        int frage = ziel.IndexOf('?');
        string weg = frage < 0 ? ziel : ziel[..frage];
        if (!string.Equals(weg, pfad, StringComparison.Ordinal))
        {
            await AntwortenAsync(strom, 404, string.Empty, ct).ConfigureAwait(false);
            return (false, string.Empty);
        }

        var q = Abfrage(frage < 0 ? string.Empty : ziel[(frage + 1)..]);
        (string code, string fehler) = Auswerten(q, zustand);
        if (fehler == "zustand")
        {
            // Fremder Aufruf mit unserem Pfad: abweisen, weiter auf den
            // echten warten. Der Pfad ist zufaellig – das passiert nur, wenn
            // jemand ihn kennt.
            await AntwortenAsync(strom, 400, Texte.IdpZustand, ct).ConfigureAwait(false);
            return (false, string.Empty);
        }
        if (fehler.Length > 0)
        {
            string text = FehlerText(fehler);
            await AntwortenAsync(strom, 200, text, ct).ConfigureAwait(false);
            throw new IdpFehlerException(fehler, text);
        }
        await AntwortenAsync(strom, 200, Texte.IdpSeiteFertig, ct).ConfigureAwait(false);
        return (true, code);
    }

    /// <summary>Liest bis zum Ende des Kopfes (hoechstens 16 KB) und gibt die
    /// erste Zeile zurueck.</summary>
    private static async Task<string> KopfLesenAsync(NetworkStream strom, CancellationToken ct)
    {
        var puffer = new byte[16384];
        int gelesen = 0;
        while (gelesen < puffer.Length)
        {
            int n = await strom.ReadAsync(puffer.AsMemory(gelesen), ct).ConfigureAwait(false);
            if (n <= 0) { break; }
            gelesen += n;
            if (Encoding.ASCII.GetString(puffer, 0, gelesen).Contains("\r\n\r\n", StringComparison.Ordinal))
            {
                break;
            }
        }
        string kopf = Encoding.ASCII.GetString(puffer, 0, gelesen);
        int ende = kopf.IndexOf("\r\n", StringComparison.Ordinal);
        return ende < 0 ? kopf : kopf[..ende];
    }

    /// <summary>Kleine HTML-Seite fuer den Browser. Der Text wird maskiert.</summary>
    private static async Task AntwortenAsync(NetworkStream strom, int status, string text,
                                             CancellationToken ct)
    {
        string grund = status switch { 200 => "OK", 400 => "Bad Request", 404 => "Not Found", _ => "Error" };
        string html = "<!doctype html><html><head><meta charset=\"utf-8\"><title>"
                      + WebUtility.HtmlEncode(Texte.Marke)
                      + "</title></head><body style=\"font-family:Segoe UI,sans-serif;margin:3em\"><p>"
                      + WebUtility.HtmlEncode(text) + "</p></body></html>";
        byte[] rumpf = Encoding.UTF8.GetBytes(html);
        string kopf = "HTTP/1.1 " + status + " " + grund + "\r\n"
                      + "Content-Type: text/html; charset=utf-8\r\n"
                      + "Content-Length: " + rumpf.Length + "\r\n"
                      + "Cache-Control: no-store\r\n"
                      + "Connection: close\r\n\r\n";
        byte[] k = Encoding.ASCII.GetBytes(kopf);
        await strom.WriteAsync(k, ct).ConfigureAwait(false);
        await strom.WriteAsync(rumpf, ct).ConfigureAwait(false);
        await strom.FlushAsync(ct).ConfigureAwait(false);
    }

    /// <summary>Oeffnet die Adresse im Standardbrowser.</summary>
    public static void BrowserOeffnen(string adresse)
    {
        try
        {
            Process.Start(new ProcessStartInfo(adresse) { UseShellExecute = true });
        }
        catch (Exception e)
        {
            throw new VisionException(Texte.IdpBrowser + e.Message, e);
        }
    }
}

/// <summary>Der Server oder IdP hat die Anmeldung abgelehnt; <see cref="Kennung"/>
/// ist die Fehlerkennung (z. B. <c>keine_freigabe</c>).</summary>
internal sealed class IdpFehlerException(string kennung, string text) : VisionException(text)
{
    public string Kennung { get; } = kennung;
}
