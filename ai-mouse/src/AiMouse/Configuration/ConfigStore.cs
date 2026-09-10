using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Collections.Generic;
using Microsoft.Win32;

namespace AiMouse.Configuration;

/// <summary>Benutzereinstellungen in der Registry (HKCU\Software\AiMouse).
///
/// ⚠ ES GIBT KEINE settings.json UND KEINE prompts.json MEHR (Vorgabe des
/// Betreibers, 2026-09-09). Was frueher in zwei Dateien neben der Exe lag,
/// verteilt sich jetzt auf drei Orte – jeder mit einem Grund:
///
/// * **Serveradresse, Marke, Akzent** stehen im PROGRAMM (<see cref="Vorgaben"/>),
///   vom Server beim Uebersetzen eingesetzt. Sie gehoeren dem Haus, nicht dem
///   Arbeitsplatz, und die Anmeldemaske braucht die Marke, bevor es eine
///   Sitzung gibt.
/// * **Die Fragen** liegen auf dem SERVER und werden im Portal gepflegt. Sie
///   folgen dem Benutzer, nicht dem Rechner.
/// * **Was ein Benutzer selbst einstellt** (Sprache, Ziehschwelle,
///   Zwischenablage, zuletzt benutzter Anmeldename) liegt HIER, in der
///   Registry – dem unter Windows dafuer vorgesehenen Ort. Sie ueberlebt das
///   Verschieben der Exe, und niemand kann sie versehentlich mitkopieren.
///
/// EIN KENNWORT STEHT HIER NIE. Das Sitzungstoken lebt ausschliesslich im
/// Arbeitsspeicher.
///
/// Fehlertolerant an jeder Stelle: eine unlesbare Registry (Gruppenrichtlinie,
/// eingeschraenktes Profil) darf die Anwendung nicht am Starten hindern – dann
/// gelten die Vorgaben, und Einstellungen halten eben nur bis zum Beenden.
/// </summary>
internal static class ConfigStore
{
    private const string Schluessel = @"Software\AiMouse";

    /// <summary>Nur noch fuer den Datei-Dialog "Bild speichern unter…".</summary>
    public static string BaseDirectory
    {
        get
        {
            string? path = Environment.ProcessPath;
            string? directory = path is null ? null : Path.GetDirectoryName(path);
            return string.IsNullOrEmpty(directory) ? AppContext.BaseDirectory : directory;
        }
    }

    /// <summary>Wo die Einstellungen liegen – fuer die Anzeige im Dialog.</summary>
    public static string SettingsPath => @"HKCU\" + Schluessel;

    public static AppSettings LoadSettings(out string? error)
    {
        error = null;
        var s = new AppSettings
        {
            // Die Vorgaben des Hauses sind der Ausgangspunkt; die Registry
            // ueberschreibt nur, was ein Benutzer wirklich geaendert hat.
            Endpoint = Vorgaben.Endpoint,
            Marke = Vorgaben.Marke,
            Akzent = Vorgaben.Akzent,
            Sprache = Vorgaben.Sprache,
        };

        try
        {
            using RegistryKey? k = Registry.CurrentUser.OpenSubKey(Schluessel);
            if (k is null)
            {
                return s;   // Erststart – nichts gespeichert, Vorgaben gelten.
            }
            // ⚠ Eine LEERE gespeicherte Adresse darf die Hausvorgabe NICHT
            // ueberschreiben: sonst verliert ein Benutzer, der einmal auf
            // "Speichern" geklickt hat, die eingebaute Serveradresse.
            string end = Lies(k, "Endpoint");
            if (end.Length > 0) { s.Endpoint = end; }
            string spr = Lies(k, "Sprache");
            if (spr.Length > 0) { s.Sprache = spr; }
            s.Benutzer = Lies(k, "Benutzer");
            s.TimeoutSeconds = Zahl(k, "TimeoutSeconds", s.TimeoutSeconds, 5, 3600);
            s.DragThreshold = Zahl(k, "DragThreshold", s.DragThreshold, 1, 100);
            s.CopyResultToClipboard = Zahl(k, "CopyResultToClipboard", 0, 0, 1) == 1;
            // Leerer Wert = nichts gespeichert -> Vorgabe behalten (gleiche
            // Regel wie bei Endpoint und Sprache eine Zeile darueber).
            string rdk = Lies(k, "RightDragKey");
            if (rdk.Length > 0) { s.RightDragKey = rdk; }
            // ⚠ Hier gilt "leer = Vorgabe" NICHT wie oben: leer IST die
            //   Vorgabe (Geste ohne Zusatztaste). Ein fehlender Wert und ein
            //   ausdrueckliches "keine" fuehren also zum selben Verhalten.
            s.GestureKey = Lies(k, "GestureKey");
        }
        catch (Exception e)
        {
            // Gemeldet, nicht verschluckt – aber die Anwendung laeuft weiter.
            error = e.Message;
        }
        return s;
    }

    /// <summary>Speichert. Rueckgabe: Fehlertext oder <c>null</c>.
    ///
    /// Marke und Akzent werden NICHT geschrieben: sie gehoeren dem Haus und
    /// kommen bei jedem Start frisch aus <see cref="Vorgaben"/>. Stuenden sie
    /// in der Registry, truege ein Arbeitsplatz nach einem Rebranding noch
    /// monatelang die alte Marke.
    /// </summary>
    public static string? SaveSettings(AppSettings settings)
    {
        try
        {
            using RegistryKey k = Registry.CurrentUser.CreateSubKey(Schluessel);
            k.SetValue("Endpoint", settings.Endpoint ?? string.Empty);
            k.SetValue("Sprache", settings.Sprache ?? "de");
            k.SetValue("Benutzer", settings.Benutzer ?? string.Empty);
            k.SetValue("TimeoutSeconds", settings.TimeoutSeconds);
            k.SetValue("DragThreshold", settings.DragThreshold);
            k.SetValue("RightDragKey", settings.RightDragKey ?? "ctrl");
            k.SetValue("GestureKey", settings.GestureKey ?? string.Empty);
            k.SetValue("CopyResultToClipboard", settings.CopyResultToClipboard ? 1 : 0);
            return null;
        }
        catch (Exception e)
        {
            return e.Message;
        }
    }

    // ── Sitzung und Fragen ──────────────────────────────────────────────────
    //
    // ⚠ HIER STEHT NIE EIN KENNWORT – auch nicht verschluesselt. Gespeichert
    // wird das SITZUNGSTOKEN, das die Anmeldung zurueckgibt: es laeuft ab, und
    // ein Administrator kann es serverseitig entwerten (Zwangsabmeldung). Ein
    // Kennwort koennte beides nicht.
    //
    // DPAPI (`ProtectedData`, CurrentUser) bindet den Wert an das
    // Windows-Konto: ein anderer Benutzer desselben Rechners kann ihn nicht
    // lesen, und eine kopierte Registry-Datei ist woanders wertlos. Ohne diesen
    // Schutz laege ein Token im Klartext, das laut Projektregel die VOLLE
    // Sitzung traegt.

    /// <summary>Sitzungstoken ablegen. Leer = loeschen.</summary>
    public static void SaveToken(string? token)
    {
        try
        {
            using RegistryKey k = Registry.CurrentUser.CreateSubKey(Schluessel);
            if (string.IsNullOrWhiteSpace(token))
            {
                // Beim Abmelden MUSS der Wert weg sein, nicht nur leer –
                // sonst haelt ein Rest die naechste Anmeldung fuer erledigt.
                try { k.DeleteValue("Sitzung", false); } catch (Exception) { }
                return;
            }
            byte[] roh = Encoding.UTF8.GetBytes(token);
            byte[] zu = ProtectedData.Protect(roh, null, DataProtectionScope.CurrentUser);
            k.SetValue("Sitzung", Convert.ToBase64String(zu));
        }
        catch (Exception)
        {
            // Fail-safe in die harmlose Richtung: ohne gespeicherte Sitzung
            // fragt der naechste Start nach den Zugangsdaten. Ein Fehlerfenster
            // waere hier Stoerung ohne Handlungsmoeglichkeit.
        }
    }

    /// <summary>Gespeichertes Sitzungstoken, sonst leer.</summary>
    public static string LoadToken()
    {
        try
        {
            using RegistryKey? k = Registry.CurrentUser.OpenSubKey(Schluessel);
            string b64 = k is null ? string.Empty : Lies(k, "Sitzung");
            if (b64.Length == 0) { return string.Empty; }
            byte[] zu = Convert.FromBase64String(b64);
            byte[] roh = ProtectedData.Unprotect(zu, null, DataProtectionScope.CurrentUser);
            return Encoding.UTF8.GetString(roh);
        }
        catch (Exception)
        {
            // Ein auf einem anderen Konto verschluesselter oder beschaedigter
            // Wert ist hier nicht zu retten – dann gilt "nicht angemeldet".
            return string.Empty;
        }
    }

    /// <summary>Die zuletzt geholten Fragen ablegen.
    ///
    /// Damit steht das Menue schon beim naechsten Start, BEVOR der Server
    /// geantwortet hat – und auch dann, wenn er gerade nicht erreichbar ist.
    /// Es sind Anweisungstexte des Benutzers, kein Geheimnis: sie liegen im
    /// Klartext.
    /// </summary>
    public static void SavePrompts(IReadOnlyList<PromptItem> prompts)
    {
        try
        {
            using RegistryKey k = Registry.CurrentUser.CreateSubKey(Schluessel);
            k.SetValue("Fragen", JsonSerializer.Serialize(prompts,
                AppJsonContext.Default.ListPromptItem));
        }
        catch (Exception) { /* der naechste Abruf holt sie ohnehin */ }
    }

    /// <summary>Gemerkte Fragen, sonst eine leere Liste.</summary>
    public static List<PromptItem> LoadPrompts()
    {
        try
        {
            using RegistryKey? k = Registry.CurrentUser.OpenSubKey(Schluessel);
            string j = k is null ? string.Empty : Lies(k, "Fragen");
            if (j.Length == 0) { return []; }
            List<PromptItem>? l = JsonSerializer.Deserialize(j,
                AppJsonContext.Default.ListPromptItem);
            // Ein Eintrag ohne Text waere eine leere Menuezeile.
            return (l ?? []).Where(x => !string.IsNullOrWhiteSpace(x.Title)
                                     && !string.IsNullOrWhiteSpace(x.Prompt)).ToList();
        }
        catch (Exception)
        {
            return [];
        }
    }

    /// <summary>Ist die Anwendung schon eingerichtet?
    ///
    /// ⚠ ENTSCHEIDEND IST DIE SERVERADRESSE, nicht das Vorhandensein des
    /// Schluessels: den legt schon das erste Speichern irgendeiner Einstellung
    /// an. Ohne Adresse kann die Anwendung nichts – dann ist es der erste
    /// Start, und der fragt.
    /// </summary>
    public static bool Eingerichtet()
    {
        try
        {
            using RegistryKey? k = Registry.CurrentUser.OpenSubKey(Schluessel);
            if (k is null) { return false; }
            // ⚠ ADRESSE **UND** BENUTZER. Die Adresse allein genuegt nicht: sie
            // ist einkompiliert und wird beim ersten Speichern mitgeschrieben –
            // die Anwendung galt damit als eingerichtet, obwohl noch keine
            // Zugangsdaten hinterlegt waren, und der Einstellungsdialog blieb
            // beim Start aus (2026-09-09 gemeldet).
            //
            // Eingerichtet heisst: man kann damit ARBEITEN. Dazu gehoert ein
            // Benutzername – ohne ihn fuehrt jeder Weg in eine Anmeldung.
            return Lies(k, "Endpoint").Length > 0 && Lies(k, "Benutzer").Length > 0;
        }
        catch (Exception)
        {
            return false;
        }
    }

    private static string Lies(RegistryKey k, string name)
        => (k.GetValue(name) as string ?? string.Empty).Trim();

    /// <summary>Zahl aus der Registry, hart begrenzt.
    ///
    /// Die Werte sind von Hand editierbar (regedit); ein unsinniger Wert darf
    /// nicht zu einer Ausnahme beim Zuweisen an ein NumericUpDown fuehren.
    /// </summary>
    private static int Zahl(RegistryKey k, string name, int vorgabe, int min, int max)
    {
        try
        {
            object? v = k.GetValue(name);
            if (v is null) { return vorgabe; }
            int i = v is int n ? n : int.Parse(v.ToString() ?? string.Empty);
            return Math.Clamp(i, min, max);
        }
        catch (Exception)
        {
            return vorgabe;
        }
    }
}
