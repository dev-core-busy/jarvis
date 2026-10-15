namespace AiMouse.Ui;

/// <summary>Entscheidet, ob ein angeklickter Link geoeffnet werden darf.
///
/// ⚠ WARUM DAS EINE EIGENE KLASSE IST – ZWEI GRUENDE, jeder allein reichend:
///
/// (1) SICHERHEIT. Der Text im Ergebnisfenster ist eine MODELLANTWORT ueber
///     einen BILDSCHIRMAUSSCHNITT – also Fremdtext, den jemand ueber den
///     Bildschirminhalt steuern kann (eine praeparierte Webseite, eine Mail,
///     ein PDF im Bild). Ein Klick landet in `Process.Start(...,
///     UseShellExecute = true)`, und das startet JEDES registrierte Schema,
///     nicht nur Webseiten: `file:///C:/…\evil.exe`, `ms-msdt:`, `search-ms:`.
///     Deshalb eine ERLAUBNISLISTE (http/https) und keine Sperrliste: was
///     morgen an Schemata dazukommt, ist damit von selbst draussen.
///
/// (2) MESSBARKEIT. `ResultWindow` erbt von `Form` – WinForms laesst sich auf
///     dem Bauserver uebersetzen, aber nicht AUSFUEHREN. Diese Klasse haengt an
///     keiner Oberflaeche und kann deshalb in einem echten Lauf gegen echte
///     Faelle geprueft werden, statt nur im Quelltext gelesen zu werden.
/// </summary>
internal static class LinkZiel
{
    /// <summary>True, wenn `text` eine Web-Adresse ist, die geoeffnet werden darf.</summary>
    /// <param name="text">Der Linktext, wie ihn die RichTextBox meldet.</param>
    /// <param name="adresse">Die gepruefte Adresse (nur bei true gesetzt).</param>
    public static bool IstWeb(string? text, out Uri? adresse)
    {
        adresse = null;

        if (string.IsNullOrWhiteSpace(text))
        {
            return false;
        }

        string roh = text.Trim();

        // `DetectUrls` erkennt auch schemenlose Adressen ("www.beispiel.de").
        // Sie werden als https gelesen – NICHT als http: wer eine Adresse ohne
        // Schema anklickt, soll nicht ungefragt im Klartext landen.
        //
        // Das `Trim()` oben ist NUR fuer diesen Zweig noetig: `Uri.TryCreate`
        // trimmt selbst (gemessen), aber mit fuehrendem Leerraum greift das
        // `StartsWith("www.")` nicht – und ohne Schema scheitert das Parsen.
        if (roh.StartsWith("www.", StringComparison.OrdinalIgnoreCase))
        {
            roh = "https://" + roh;
        }

        if (!Uri.TryCreate(roh, UriKind.Absolute, out Uri? u))
        {
            return false;
        }

        // ERLAUBNISLISTE, keine Sperrliste: was morgen an Schemata dazukommt,
        // ist damit von selbst draussen.
        //
        // ⚠ SIE DECKT UNC UND DATEIPFADE MIT AB – gemessen, nicht vermutet:
        // `\\server\freigabe` und `C:\…` ergeben in .NET das Schema `file`
        // (`IsUnc`/`IsFile` true). Eine zusaetzliche `IsFile || IsUnc`-Zeile
        // stand hier kurz und war nachweislich TOT: ihr Entfernen aenderte in
        // keinem der 23 Faelle von `tests/live_linkziel_dev.py` etwas, weil ein
        // http/https-Uri niemals `IsFile` sein kann. Toter Code ist hier keine
        // Tiefenverteidigung, sondern eine Zeile, die bei jeder kuenftigen
        // Durchsicht mitgeprueft werden muesste. Der UNC-Fall bleibt trotzdem
        // als Pruefung stehen – die EIGENSCHAFT zaehlt, nicht die Zeile.
        //
        // Warum UNC ueberhaupt gefaehrlich waere: ein Klick darauf schickt die
        // Windows-Anmeldung an einen fremden Rechner (NTLM-Leak) – ausgeloest
        // durch Text, der aus einem Bildschirmausschnitt stammt.
        if (u.Scheme != Uri.UriSchemeHttp && u.Scheme != Uri.UriSchemeHttps)
        {
            return false;
        }

        adresse = u;
        return true;
    }
}
