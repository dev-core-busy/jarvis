namespace AiMouse.Start;

/// <summary>Rechnet eine Tastenkombination in das Hotkey-Wort einer Verknuepfung
/// um – und zurueck.
///
/// ⚠ DIESE KLASSE IST BEWUSST FREI VON COM UND WINFORMS. Sie traegt die ganze
/// ENTSCHEIDUNG (was ist eine zulaessige Kombination, welche Zahl ergibt sie),
/// waehrend <see cref="Verknuepfung"/> nur noch schreibt. Der Grund ist
/// derselbe wie bei <c>ZiehbarRegel</c> und <c>LinkZiel</c>: auf dem Bauserver
/// laeuft kein Windows – eine Regel, die an COM haengt, laesst sich dort weder
/// ausfuehren noch messen. So wird sie es.
///
/// ⚠ DIE ZAHLENWERTE DER MODIFIER STAMMEN AUS `commctrl.h` (HOTKEYF_*), NICHT
/// aus der Learn-Doku: die nennt an beiden Stellen (IShellLink::GetHotkey,
/// HKM_SETHOTKEY) nur die NAMEN der Flags und keine Werte. Sie sind seit
/// Windows 95 unveraendert.
///
/// **Wie sich ein falscher Wert zeigen wuerde:** die Verknuepfung traegt dann
/// eine andere Modifikatortaste als die angezeigte – der Explorer zeigt die
/// Kombination in den Eigenschaften der Verknuepfung an, es ist also in einem
/// Blick sichtbar und nicht still. Das ist der Grund, warum dieses Restrisiko
/// vertretbar ist; siehe Abschlussvermerk „nicht geprueft".
/// </summary>
internal static class HotkeyWort
{
    // commctrl.h
    public const int ModUmschalt = 0x01;    // HOTKEYF_SHIFT
    public const int ModStrg = 0x02;        // HOTKEYF_CONTROL
    public const int ModAlt = 0x04;         // HOTKEYF_ALT

    /// <summary>„Kein Hotkey" – auch der Wert, den SetHotkey zum Loeschen nimmt.</summary>
    public const ushort Keiner = 0;

    /// <summary>Virtuelle Tastencodes, die wir zulassen.
    ///
    /// Bewusst eng: A–Z, 0–9 und F1–F12. Alles andere (Tote Tasten, Ziffernblock,
    /// Sondertasten einer Herstellertastatur) ist entweder nicht auf jeder
    /// Tastatur vorhanden oder vom System belegt.
    /// </summary>
    public static bool TasteErlaubt(int vk)
        => (vk >= 0x41 && vk <= 0x5A)       // A–Z
        || (vk >= 0x30 && vk <= 0x39)       // 0–9
        || (vk >= 0x70 && vk <= 0x7B);      // F1–F12

    /// <summary>Ist die Kombination als Verknuepfungs-Hotkey brauchbar?
    ///
    /// ⚠ STRG UND ALT SIND BEIDE PFLICHT, und das ist keine Willkuer: der
    /// Explorer-Dialog („Eigenschaften → Tastenkombination") erzeugt
    /// ausschliesslich `Strg+Alt+&lt;Taste&gt;` und ergaenzt fehlende Modifier
    /// selbsttaetig. Andere Kombinationen laesst die Shell zwar SPEICHERN, sie
    /// wirken aber nicht zuverlaessig – und ein Hotkey, der sich einstellen
    /// laesst und nichts tut, ist schlimmer als einer, den man gar nicht erst
    /// anbieten kann.
    ///
    /// Umschalt ist ZUSAETZLICH erlaubt (Strg+Alt+Umschalt+X), aber nie allein.
    /// </summary>
    public static bool IstZulaessig(int modifier, int vk)
        => TasteErlaubt(vk)
        && (modifier & ModStrg) != 0
        && (modifier & ModAlt) != 0;

    /// <summary>Baut das Wort: VK im niederwertigen, Modifier im hoeherwertigen
    /// Byte (so verlangt es <c>IShellLink::SetHotkey</c>).
    ///
    /// Unzulaessige Kombinationen ergeben <see cref="Keiner"/> – fail-closed:
    /// lieber kein Hotkey als einer, der auf eine unerwartete Taste zeigt.
    /// </summary>
    public static ushort Bauen(int modifier, int vk)
        => IstZulaessig(modifier, vk)
            ? (ushort)((vk & 0xFF) | ((modifier & 0xFF) << 8))
            : Keiner;

    /// <summary>Zerlegt das Wort wieder. Gibt <c>(0, 0)</c> bei
    /// <see cref="Keiner"/> oder unbrauchbarem Inhalt.</summary>
    public static (int Modifier, int Vk) Zerlegen(ushort wort)
    {
        int vk = wort & 0xFF;
        int mod = (wort >> 8) & 0xFF;
        return IstZulaessig(mod, vk) ? (mod, vk) : (0, 0);
    }

    /// <summary>Menschenlesbare Form fuer Registry und Anzeige, z. B.
    /// <c>CTRL+ALT+A</c>. Leer heisst „kein Hotkey".
    ///
    /// ⚠ GESPEICHERT WIRD DIESE FORM UND NICHT DIE ZAHL: eine Zahl in der
    /// Registry kann niemand lesen oder von Hand korrigieren, und sie waere bei
    /// einem Fehler in der Rechnung nicht von einem Tippfehler zu
    /// unterscheiden. Die Wortform ist ausserdem dieselbe, die der Windows
    /// Script Host benutzt – wer sie kennt, erkennt sie wieder.
    /// </summary>
    public static string AlsText(int modifier, int vk)
    {
        if (!IstZulaessig(modifier, vk))
        {
            return string.Empty;
        }

        string taste = TastenName(vk);
        // Reihenfolge fest: sonst ergaebe dieselbe Kombination zwei
        // Schreibweisen, und ein Vergleich „hat sich etwas geaendert?" schlaege
        // grundlos an.
        string s = "CTRL+ALT+";
        if ((modifier & ModUmschalt) != 0)
        {
            s = "CTRL+ALT+SHIFT+";
        }
        return s + taste;
    }

    /// <summary>Liest die Wortform wieder ein. Unbrauchbares ergibt
    /// <c>(0, 0)</c> – ein von Hand verdrehter Registry-Wert darf nicht in
    /// einer Ausnahme enden.</summary>
    public static (int Modifier, int Vk) AusText(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return (0, 0);
        }

        int mod = 0;
        int vk = 0;

        foreach (string roh in text.Split('+', StringSplitOptions.RemoveEmptyEntries))
        {
            string teil = roh.Trim().ToUpperInvariant();
            switch (teil)
            {
                case "CTRL":
                case "STRG":
                    mod |= ModStrg;
                    break;
                case "ALT":
                    mod |= ModAlt;
                    break;
                case "SHIFT":
                case "UMSCHALT":
                    mod |= ModUmschalt;
                    break;
                default:
                    // ⚠ Nur der LETZTE Nicht-Modifier zaehlt nicht – es darf
                    //   ueberhaupt nur EINEN geben. Zwei Tasten in einer
                    //   Kombination gibt es hier nicht, und stillschweigend die
                    //   letzte zu nehmen waere eine Deutung, die niemand
                    //   verlangt hat.
                    if (vk != 0)
                    {
                        return (0, 0);
                    }
                    vk = TastenCode(teil);
                    if (vk == 0)
                    {
                        return (0, 0);
                    }
                    break;
            }
        }

        return IstZulaessig(mod, vk) ? (mod, vk) : (0, 0);
    }

    /// <summary>Anzeigename einer erlaubten Taste.</summary>
    public static string TastenName(int vk)
    {
        if (vk >= 0x70 && vk <= 0x7B)
        {
            return "F" + (vk - 0x70 + 1).ToString();
        }
        if ((vk >= 0x41 && vk <= 0x5A) || (vk >= 0x30 && vk <= 0x39))
        {
            return ((char)vk).ToString();
        }
        return string.Empty;
    }

    /// <summary>Umkehrung von <see cref="TastenName"/>; 0 = unbekannt.</summary>
    public static int TastenCode(string name)
    {
        string n = (name ?? string.Empty).Trim().ToUpperInvariant();
        if (n.Length == 1)
        {
            char c = n[0];
            if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9'))
            {
                return c;
            }
            return 0;
        }
        if (n.Length >= 2 && n[0] == 'F' && int.TryParse(n[1..], out int nr)
            && nr >= 1 && nr <= 12)
        {
            return 0x70 + nr - 1;
        }
        return 0;
    }
}
