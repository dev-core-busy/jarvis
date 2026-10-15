#!/usr/bin/env python3
"""Fuehrt die Worker-Mechanik von `ZiehbarPruefer` WIRKLICH aus (2026-09-14).

⚠ WOZU DAS NOETIG IST: der Waechter in `test_ai_mouse.py` kann nur pruefen,
DASS eine Besetzt-Schranke im Quelltext steht – nicht, WAS sie bewirkt. Die
Zusage, um die es nach dem Vorfall vom 2026-09-14 geht, lautet aber:

    Haengt die Zielanwendung, entsteht KEIN zweiter Thread –
    egal, wie oft der Benutzer die Taste haelt.

Genau das hat die Anwendung vorher unbeendbar gemacht (jede Abfrage einen
eigenen STA-Thread, der nach der Zeitgrenze stehenblieb). Also wird es hier
gemessen: die ECHTEN Methoden werden aus der Datei geschnitten, in eine
Wegwerf-Konsolenanwendung gehoben und ausgefuehrt.

⚠ WAS DIESE PROBE NICHT KANN: den COM-Teil. `ElementFromPoint` braucht
Windows, den Bauserver gibt es nur mit Linux. Ersetzt ist deshalb GENAU dieser
eine Aufruf durch eine steuerbare Attrappe – die Nebenlaeufigkeit drumherum
(Interlocked, die beiden Signale, die Reihenfolge) ist Zeichen fuer Zeichen
der echte Code. Ebenso entfaellt `SetApartmentState`: STA gibt es unter Linux
nicht, der Aufruf wuerde werfen und die Mechanik in den Ausfall-Zweig treiben.
Beides wird unten als Positivkontrolle ausgewiesen.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUELLE = ROOT / "ai-mouse/src/AiMouse/Input/ZiehbarPruefer.cs"

ok = fail = 0


def check(text, bedingung):
    global ok, fail
    if not isinstance(text, str) or isinstance(bedingung, str):
        print("ABBRUCH: check() mit vertauschten Argumenten")
        sys.exit(2)
    if bedingung:
        ok += 1
        print("  OK   %s" % text)
    else:
        fail += 1
        print("  FAIL %s" % text)


def rumpf(quelle, signatur):
    """Schneidet eine Methode samt Signatur ueber Klammerzaehlung heraus."""
    i = quelle.find(signatur)
    if i < 0:
        return ""
    a = quelle.find("{", i)
    if a < 0:
        return ""
    tiefe = 0
    for j in range(a, len(quelle)):
        if quelle[j] == "{":
            tiefe += 1
        elif quelle[j] == "}":
            tiefe -= 1
            if tiefe == 0:
                return quelle[i:j + 1]
    return ""


def main():
    if not QUELLE.exists():
        print("ABBRUCH: %s fehlt" % QUELLE)
        sys.exit(2)

    src = QUELLE.read_text(encoding="utf-8")

    abfrage = rumpf(src, "public static bool LiegtObjektUnter")
    start = rumpf(src, "private static bool WorkerSicherstellen")
    schleife = rumpf(src, "private static void WorkerSchleife")

    # ⚠ POSITIVKONTROLLE DES SCHNITTS. Ein leerer Schnitt wuerde unten eine
    #    Konsolenanwendung erzeugen, die gar nichts von der echten Mechanik
    #    enthaelt – und jede Messung daran waere wertlos.
    check("die drei echten Methoden wurden geschnitten",
          bool(abfrage) and bool(start) and bool(schleife))
    # ⚠ DIE POSITIVKONTROLLE DARF NICHT AN DEM TEXT HAENGEN, DER GEMESSEN WIRD.
    #   Die erste Fassung prueste hier `Interlocked.CompareExchange` – also
    #   genau die Besetzt-Schranke. Eine Gegenprobe, die sie entfernt, liess
    #   den Lauf damit an DIESER Stelle aussteigen, bevor ueberhaupt ein Thread
    #   gezaehlt wurde: die Probe „beiss" scheinbar, belegte aber nicht, dass
    #   die Messung den Fehler SIEHT. Belegt werden soll hier nur, dass der
    #   Schnitt ueberhaupt gegriffen hat.
    check("und sie tragen die Mechanik (Positivkontrolle)",
          "_fertig" in abfrage
          and "new Thread" in start
          and "_fertig.Set()" in schleife)
    if fail:
        print("\n%d OK, %d FAIL" % (ok, fail))
        sys.exit(2)

    # ── Nur der COM-Aufruf wird ersetzt ────────────────────────────────────
    com = re.search(r"automation \?\?=.*?\n\s*\}\n", schleife, re.S)
    check("der COM-Block ist eindeutig auffindbar", com is not None)
    if com is None:
        print("\n%d OK, %d FAIL" % (ok, fail))
        sys.exit(2)

    schleife_test = schleife.replace(
        com.group(0),
        "                ergebnis = Attrappe.Messen(p);\n",
        1)
    # Die lokale COM-Variable steht VOR der Schleife und faellt nicht unter den
    # Block oben. Sie bleibt erhalten (der catch setzt sie zurueck), nur ihr
    # Typ wird neutral – so bleibt auch das Verwerfen des kaputten Proxys Teil
    # des gemessenen Codes.
    schleife_test = schleife_test.replace(
        "IUIAutomation? automation = null;", "object? automation = null;", 1)
    check("und ist ersetzt (Positivkontrolle)",
          "ElementFromPoint" not in schleife_test
          and "Attrappe.Messen" in schleife_test
          and "IUIAutomation" not in schleife_test)

    # STA gibt es unter Linux nicht – der Aufruf wuerde werfen.
    start_test = start.replace("t.SetApartmentState(ApartmentState.STA);",
                               "/* STA: unter Linux nicht moeglich */")
    check("die STA-Zeile ist fuer den Linux-Lauf neutralisiert",
          "SetApartmentState" not in start_test)

    programm = """
using System.Diagnostics;

// Die Attrappe an der Stelle des COM-Aufrufs: steuerbar haengend.
internal static class Attrappe
{
    public static volatile bool Haengt;
    public static readonly ManualResetEventSlim Loesen = new(false);
    public static int Aufrufe;
    public static readonly HashSet<int> ThreadIds = new();

    public static bool Messen(Point p)
    {
        Interlocked.Increment(ref Aufrufe);
        lock (ThreadIds) { ThreadIds.Add(Environment.CurrentManagedThreadId); }
        if (Haengt)
        {
            // Wie eine Zielanwendung, die nicht antwortet.
            Loesen.Wait();
        }
        return p.X == 42;
    }
}

internal struct Point
{
    public int X;
    public int Y;
    public Point(int x, int y) { X = x; Y = y; }
}

internal static class ZiehbarRegel
{
    public static bool IstZiehbar(int a, bool b, bool c) => true;
}

internal static class Pruefer
{
__FELDER__

__ABFRAGE__

__START__

__SCHLEIFE__
}

internal static class P
{
    private static int Threads() => Process.GetCurrentProcess().Threads.Count;

    private static void Main()
    {
        var g = TimeSpan.FromMilliseconds(200);

        // ── A) Regelfall: der Worker antwortet ────────────────────────────
        bool a1 = Pruefer.LiegtObjektUnter(new Point(42, 0), g);
        bool a2 = Pruefer.LiegtObjektUnter(new Point(7, 0), g);
        Console.WriteLine($"A|{a1}|{a2}|{Attrappe.Aufrufe}|{Attrappe.ThreadIds.Count}");

        // 50 weitere Abfragen im Regelfall: der Worker wird wiederverwendet.
        for (int i = 0; i < 50; i++) { Pruefer.LiegtObjektUnter(new Point(42, 0), g); }
        Console.WriteLine($"A2|{Attrappe.ThreadIds.Count}");

        // ── B) Die Zielanwendung haengt ───────────────────────────────────
        int vorher = Threads();
        Attrappe.Haengt = true;

        var uhr = Stopwatch.StartNew();
        bool b1 = Pruefer.LiegtObjektUnter(new Point(42, 0), g);   // laeuft in die Grenze
        long ersteMs = uhr.ElapsedMilliseconds;

        uhr.Restart();
        int treffer = 0;
        for (int i = 0; i < 50; i++)
        {
            if (Pruefer.LiegtObjektUnter(new Point(42, 0), g)) { treffer++; }
        }
        long weitereMs = uhr.ElapsedMilliseconds;
        Thread.Sleep(150);
        int nachher = Threads();

        Console.WriteLine($"B|{b1}|{treffer}|{ersteMs}|{weitereMs}|{vorher}|{nachher}|{Attrappe.ThreadIds.Count}");

        // ── C) Die Zielanwendung kommt zu sich ────────────────────────────
        Attrappe.Haengt = false;
        Attrappe.Loesen.Set();
        Thread.Sleep(200);
        bool c1 = Pruefer.LiegtObjektUnter(new Point(42, 0), g);
        Console.WriteLine($"C|{c1}|{Attrappe.ThreadIds.Count}");
    }
}
"""

    # Die Felder stehen AUSSERHALB der Methoden und fallen aus jedem
    # Funktions-Schnitt heraus (Register: Modul-Konstanten mitnehmen).
    felder = []
    for m in re.finditer(
            r"^\s*private static (?:readonly )?[\w<>?.]+ (_auftrag|_fertig|"
            r"_beschaeftigt|_ausgefallen|_worker|_startTor|_punkt|_ergebnis)\b[^;]*;",
            src, re.M):
        felder.append(m.group(0))
    # `volatile` steht vor dem Typ und wird vom Muster oben nicht erfasst.
    for m in re.finditer(r"^\s*private static volatile [\w<>?.]+ _ergebnis\b[^;]*;", src, re.M):
        felder.append(m.group(0))

    check("die Felder der Mechanik wurden mitgenommen", len(felder) >= 7)
    check("darunter die Besetzt-Marke und beide Signale",
          any("_beschaeftigt" in f for f in felder)
          and any("_auftrag" in f for f in felder)
          and any("_fertig" in f for f in felder))

    programm = (programm
                .replace("__FELDER__", "\n".join(felder))
                .replace("__ABFRAGE__", abfrage)
                .replace("__START__", start_test)
                .replace("__SCHLEIFE__", schleife_test))

    arbeit = Path(tempfile.mkdtemp(prefix="uia-worker-"))
    try:
        (arbeit / "P.cs").write_text(programm, encoding="utf-8")
        (arbeit / "P.csproj").write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <LangVersion>latest</LangVersion>
    <AssemblyName>P</AssemblyName>
    <NoWarn>$(NoWarn);CS0414;CS0649</NoWarn>
  </PropertyGroup>
</Project>
""", encoding="utf-8")

        # ⚠ `dotnet` LIEGT NICHT ZWINGEND IM PATH. Auf DEV gibt es kein
        #   apt-Paket dafuer, das SDK liegt unter `vendor/dotnet` – genau wie
        #   `deploy/ai_mouse_build.sh` es ablegt. Ohne diesen Griff meldet die
        #   Probe dort „FileNotFoundError: dotnet" und man sucht den Fehler im
        #   Code, statt in der Umgebung.
        dn = shutil.which("dotnet")
        if dn is None:
            eigen = ROOT / "vendor/dotnet/dotnet"
            dn = str(eigen) if eigen.exists() else None
        if dn is None:
            print("  FAIL kein dotnet-SDK gefunden (weder im PATH noch unter "
                  "vendor/dotnet) – die Messung kann nicht laufen.")
            print("\n%d OK, %d FAIL" % (ok, fail + 1))
            sys.exit(2)

        b = subprocess.run([dn, "run", "--project", str(arbeit / "P.csproj"), "-c", "Release"],
                           capture_output=True, text=True, timeout=600, cwd=str(arbeit))
        if b.returncode != 0:
            print("  FAIL der Lauf ist gescheitert:")
            print((b.stdout + b.stderr)[-2500:])
            print("\n%d OK, %d FAIL" % (ok, fail + 1))
            sys.exit(1)

        zeilen = {z.split("|")[0]: z.split("|")
                  for z in b.stdout.splitlines() if "|" in z}

        check("der Lauf hat alle vier Messpunkte geliefert",
              all(k in zeilen for k in ("A", "A2", "B", "C")))
        if not all(k in zeilen for k in ("A", "A2", "B", "C")):
            print(b.stdout[-1500:])
            print("\n%d OK, %d FAIL" % (ok, fail))
            sys.exit(1)

        # ── A) Regelfall ──────────────────────────────────────────────────
        a = zeilen["A"]
        check("A: eine Abfrage liefert das Ergebnis des Workers (true)",
              a[1] == "True")
        check("A: und eine andere Stelle liefert false",
              a[2] == "False")
        check("A: der Worker wurde wirklich gerufen (Positivkontrolle)",
              int(a[3]) == 2)
        check("A: und zwar auf genau EINEM Thread", int(a[4]) == 1)
        check("A2: auch nach 52 Abfragen ist es derselbe EINE Thread",
              int(zeilen["A2"][1]) == 1)

        # ── B) Die entscheidende Messung ──────────────────────────────────
        bz = zeilen["B"]
        erste, weitere = int(bz[3]), int(bz[4])
        vorher, nachher = int(bz[5]), int(bz[6])

        check("B: die erste Abfrage gegen eine haengende Anwendung gibt false",
              bz[1] == "False")
        check("B: und die 50 weiteren ebenfalls (kein Drag im Zweifel)",
              int(bz[2]) == 0)
        check("B: die erste Abfrage laeuft in die Zeitgrenze (>= 150 ms)",
              erste >= 150)
        # ⚠ DAS IST DER KERN: die weiteren Abfragen kosten NICHTS. Der alte
        #   Code haette jede einzelne 200 ms warten lassen UND einen Thread
        #   erzeugt – 50 Abfragen also 10 Sekunden und 50 Leichen.
        check("B: die 50 weiteren kosten zusammen unter 100 ms (%d ms)" % weitere,
              weitere < 100)
        check("B: WAEHREND DER WORKER HAENGT ENTSTEHT KEIN WEITERER THREAD "
              "(%d -> %d)" % (vorher, nachher),
              nachher <= vorher)
        check("B: der haengende Worker wurde nicht erneut beauftragt",
              int(bz[7]) == 1)

        # ── C) Erholung ───────────────────────────────────────────────────
        c = zeilen["C"]
        check("C: kommt die Anwendung zu sich, arbeitet die Erkennung weiter",
              c[1] == "True")
        check("C: und immer noch auf demselben EINEN Thread",
              int(c[2]) == 1)

    finally:
        shutil.rmtree(arbeit, ignore_errors=True)

    print("\n%d OK, %d FAIL" % (ok, fail))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
