using System.IO.Compression;
using AiMouse.Update;
using AiMouse.Configuration;

namespace Brems;

internal static class Programm
{
    private static int _ok, _fail;
    private static void Check(string was, bool bed)
    { if (bed) { _ok++; Console.WriteLine("  OK   " + was); }
      else { _fail++; Console.WriteLine("  FAIL " + was); } }

    // Ein ZIP mit einer EXE ueber der 1-MB-Schranke.
    private static byte[] Paket()
    {
        using var ms = new MemoryStream();
        using (var z = new ZipArchive(ms, ZipArchiveMode.Create, true))
        {
            // ⚠ INKOMPRESSIBEL: 1,2 MB Nullen schrumpfen auf wenige KB und
            // fallen durch die 1-MB-Schranke – das Testmaterial waere dann
            // untauglich, und der Waechter meldete einen Fehler, den es nicht
            // gibt (genau so beim ersten Lauf passiert).
            var e = z.CreateEntry("AiMouse.exe", CompressionLevel.NoCompression);
            using var s = e.Open();
            var buf = new byte[1_200_000];
            new Random(42).NextBytes(buf);
            s.Write(buf);
        }
        return ms.ToArray();
    }

    private static async Task<int> Main()
    {
        string exe = Aktualisierung.EigenerPfad;
        string neu = exe + ".neu";
        int geholt = 0;
        Task<byte[]> Holen(CancellationToken _) { geholt++; return Task.FromResult(Paket()); }

        Console.WriteLine($"Eigene Fassung: {Aktualisierung.EigeneAnzeige}  (simuliert die alte)");
        Check("Ausgangslage: Anwendung meldet 1.0.5", Aktualisierung.EigeneAnzeige == "1.0.5");
        if (File.Exists(neu)) File.Delete(neu);

        // ── Runde 1: der Server fuehrt 1.0.6 → holen ist RICHTIG ──
        string r1 = await Aktualisierung.PruefenUndHolenAsync("1.0.6", Holen, default);
        Check($"Runde 1 legt bereit (r='{r1}')", r1 == "bereitgelegt");
        Check("Runde 1 hat wirklich geladen", geholt == 1);
        Check("`.neu` liegt daneben", File.Exists(neu));
        Check("Versuch wurde gemerkt", ConfigStore.Schreibzaehler == 1);

        // ── Einwechseln, wie es der Programmstart tut. Die LAUFENDE Fassung
        //    bleibt dabei 1.0.5 – genau der gemeldete Zustand (auf Platte lag
        //    1.0.6, im Speicher lief 1.0.5).
        File.Delete(neu);

        // ── Runde 2: derselbe Server, dieselbe Ausgangslage ──
        string r2 = await Aktualisierung.PruefenUndHolenAsync("1.0.6", Holen, default);
        Check($"Runde 2 bremst (r='{r2}')", r2 == "schon versucht");
        Check("Runde 2 hat NICHT geladen  <<< der gemeldete Fehler", geholt == 1);
        Check("keine neue `.neu` entstanden", !File.Exists(neu));

        // ── Runde 3 und 4: es bleibt dabei, beliebig oft ──
        await Aktualisierung.PruefenUndHolenAsync("1.0.6", Holen, default);
        await Aktualisierung.PruefenUndHolenAsync("1.0.6", Holen, default);
        Check("auch nach vier Runden nur EIN Download", geholt == 1);

        // ── Positivkontrolle A: ein WIRKLICH neueres Ziel darf wieder ──
        string r5 = await Aktualisierung.PruefenUndHolenAsync("1.0.8", Holen, default);
        Check($"neueres Ziel wird geholt (r='{r5}')", r5 == "bereitgelegt" && geholt == 2);
        if (File.Exists(neu)) File.Delete(neu);

        // ── Positivkontrolle B: gleiches Ziel, aber die Anwendung ist
        //    inzwischen gewechselt → die Bremse darf NICHT dauerhaft sperren.
        ConfigStore.MerkeUpdateVersuch("1.0.9", "0.9.9");   // fremde Ausgangslage
        string r6 = await Aktualisierung.PruefenUndHolenAsync("1.0.9", Holen, default);
        Check($"nach Fassungswechsel wieder erlaubt (r='{r6}')", r6 == "bereitgelegt" && geholt == 3);
        if (File.Exists(neu)) File.Delete(neu);

        // ── Positivkontrolle C: gleiche Version = gar keine Frage ──
        ConfigStore.Vergessen();
        string r7 = await Aktualisierung.PruefenUndHolenAsync("1.0.5", Holen, default);
        Check($"gleiche Version laedt nie (r='{r7}')", r7 == "" && geholt == 3);

        Console.WriteLine($"\nErgebnis: {_ok} OK, {_fail} FAIL");
        return _fail == 0 ? 0 : 1;
    }
}
