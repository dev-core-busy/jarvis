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

    // Inhalt der "neuen Fassung" – ueber der 1-MB-Schranke.
    private static readonly byte[] NeueExe = Zufall(1_200_000, 42);

    private static byte[] Zufall(int n, int saat)
    {
        var buf = new byte[n];
        new Random(saat).NextBytes(buf);
        return buf;
    }

    // Ein ZIP mit dieser EXE.
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
            s.Write(NeueExe);
        }
        return ms.ToArray();
    }

    private static bool Gleich(string pfad, byte[] soll) =>
        File.Exists(pfad) && File.ReadAllBytes(pfad).AsSpan().SequenceEqual(soll);

    private static async Task<int> Main()
    {
        string exe = Aktualisierung.EigenerPfad;
        string alt = exe + ".alt", neu = exe + ".neu", teil = exe + ".teil";
        int geholt = 0, gefragt = 0;
        bool antwort = true;
        Task<byte[]> Holen(CancellationToken _) { geholt++; return Task.FromResult(Paket()); }
        Task<bool> Fragen(string _) { gefragt++; return Task.FromResult(antwort); }

        // ⚠ DIE LAUFENDE DATEI WIRD WIRKLICH AUSGETAUSCHT – unter Linux laesst
        // sich ein laufendes Programm genauso umbenennen wie unter Windows. Der
        // Prozess laeuft aus dem Speicher weiter, und das ist genau der Fall
        // des Sofort-Austauschs.
        byte[] original = File.ReadAllBytes(exe);

        Console.WriteLine($"Eigene Fassung: {Aktualisierung.EigeneAnzeige}  (simuliert die alte)");
        Check("Ausgangslage: Anwendung meldet 1.0.5", Aktualisierung.EigeneAnzeige == "1.0.5");
        Check("Positivkontrolle: Original und neue Fassung unterscheiden sich",
              !original.AsSpan().SequenceEqual(NeueExe));

        // ── Runde 0: der Benutzer sagt NEIN ──
        antwort = false;
        string r0 = await Aktualisierung.PruefenUndHolenAsync("1.0.6", Fragen, Holen, default);
        Check($"Nein: nichts geladen (r='{r0}')", r0 == "abgelehnt" && geholt == 0 && gefragt == 1);
        Check("Nein: die laufende Datei ist unveraendert", Gleich(exe, original));
        Check("Nein: nicht gemerkt – beim naechsten Mal wird wieder gefragt",
              ConfigStore.Schreibzaehler == 0);
        antwort = true;

        // ── Runde 1: der Server fuehrt 1.0.6, der Benutzer sagt JA ──
        string r1 = await Aktualisierung.PruefenUndHolenAsync("1.0.6", Fragen, Holen, default);
        Check($"Runde 1 tauscht aus (r='{r1}')", r1 == Aktualisierung.Eingewechselt);
        Check("Runde 1 hat erst gefragt, dann geladen", gefragt == 2 && geholt == 1);
        Check("an der Stelle der laufenden liegt jetzt die NEUE Fassung", Gleich(exe, NeueExe));
        Check("die alte Fassung liegt als `.alt` daneben", Gleich(alt, original));
        Check("keine `.neu` und keine `.teil` uebrig", !File.Exists(neu) && !File.Exists(teil));
        Check("Versuch wurde gemerkt", ConfigStore.Schreibzaehler == 1);

        // ── Die LAUFENDE Fassung bleibt dabei 1.0.5 – genau der gemeldete
        //    Zustand, wenn das Paket nicht die Version traegt, die der Server
        //    nennt (auf Platte 1.0.6, im Speicher 1.0.5).

        // ── Runde 2: derselbe Server, dieselbe Ausgangslage ──
        string r2 = await Aktualisierung.PruefenUndHolenAsync("1.0.6", Fragen, Holen, default);
        Check($"Runde 2 bremst (r='{r2}')", r2 == "schon versucht");
        Check("Runde 2 hat NICHT geladen  <<< der gemeldete Fehler", geholt == 1);
        Check("Runde 2 hat NICHT gefragt (keine Dauer-Rueckfrage)", gefragt == 2);

        // ── Runde 3 und 4: es bleibt dabei, beliebig oft ──
        await Aktualisierung.PruefenUndHolenAsync("1.0.6", Fragen, Holen, default);
        await Aktualisierung.PruefenUndHolenAsync("1.0.6", Fragen, Holen, default);
        Check("auch nach vier Runden nur EIN Download", geholt == 1);

        // ── Positivkontrolle A: ein WIRKLICH neueres Ziel darf wieder ──
        string r5 = await Aktualisierung.PruefenUndHolenAsync("1.0.8", Fragen, Holen, default);
        Check($"neueres Ziel wird geholt (r='{r5}')",
              r5 == Aktualisierung.Eingewechselt && geholt == 2);

        // ── Positivkontrolle B: gleiches Ziel, aber die Anwendung ist
        //    inzwischen gewechselt → die Bremse darf NICHT dauerhaft sperren.
        ConfigStore.MerkeUpdateVersuch("1.0.9", "0.9.9");   // fremde Ausgangslage
        string r6 = await Aktualisierung.PruefenUndHolenAsync("1.0.9", Fragen, Holen, default);
        Check($"nach Fassungswechsel wieder erlaubt (r='{r6}')",
              r6 == Aktualisierung.Eingewechselt && geholt == 3);

        // ── Positivkontrolle C: gleiche Version = gar keine Frage ──
        ConfigStore.Vergessen();
        int vorher = gefragt;
        string r7 = await Aktualisierung.PruefenUndHolenAsync("1.0.5", Fragen, Holen, default);
        Check($"gleiche Version laedt nie und fragt nie (r='{r7}')",
              r7 == "" && geholt == 3 && gefragt == vorher);

        // ── Das Aufraeumen beim naechsten Start ──
        File.WriteAllBytes(neu, new byte[] { 1 });
        File.WriteAllBytes(teil, new byte[] { 1 });
        Aktualisierung.RueckstandAufraeumen();
        Check("Start raeumt `.alt`, `.neu` und `.teil` weg",
              !File.Exists(alt) && !File.Exists(neu) && !File.Exists(teil));
        Check("  … und laesst die EXE selbst stehen", Gleich(exe, NeueExe));

        // ── Die Ruecknahme: der zweite Schritt scheitert ──
        //    (eigene Wegwerf-Dateien, nicht die laufende EXE)
        string d = Path.Combine(Path.GetTempPath(), "brems-" + Environment.ProcessId);
        Directory.CreateDirectory(d);
        string x = Path.Combine(d, "x.exe");
        byte[] xInhalt = Zufall(1000, 7);
        File.WriteAllBytes(x, xInhalt);
        bool getauscht = Aktualisierung.Austauschen(x, Path.Combine(d, "fehlt.neu"));
        Check("fehlende neue Datei: Austausch meldet false", !getauscht);
        Check("  … und die alte Fassung steht WIEDER an ihrem Platz  <<< Ruecknahme",
              Gleich(x, xInhalt) && !File.Exists(x + ".alt"));
        Directory.Delete(d, true);

        Console.WriteLine($"\nErgebnis: {_ok} OK, {_fail} FAIL");
        return _fail == 0 ? 0 : 1;
    }
}
