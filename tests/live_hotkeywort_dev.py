#!/usr/bin/env python3
"""Fuehrt die ECHTE Hotkey-Regel der AI-Maus auf DEV AUS.

⚠ WARUM DAS NOETIG IST: `HotkeyWort` entscheidet, welche Tastenkombination
zulaessig ist und welche ZAHL daraus wird. Ein Quelltext-Waechter kann nur
pruefen, DASS die Klasse existiert – nicht, WAS sie ausrechnet. Und ein
falsches Ergebnis waere hier besonders unangenehm: die Verknuepfung traege dann
eine andere Taste als die angezeigte.

Die Klasse ist deshalb frei von COM und WinForms (wie `ZiehbarRegel` und
`LinkZiel`) – sie laesst sich in eine gewoehnliche Konsolenanwendung heben und
auf einem Linux-Server ausfuehren.

Aufruf:  python3 tests/live_hotkeywort_dev.py
"""
import subprocess
import sys
from pathlib import Path

DEV = "root@191.100.144.1"
SSH = ["ssh", "-i", str(Path.home() / ".ssh" / "id_rsa"), "-o", "StrictHostKeyChecking=no"]
# ⚠ NICHT nach /tmp (1777): dort koennen Reste eines fremden Laufs liegen, die
#   sich nicht ueberschreiben lassen – im Register als eigener Vorfall vermerkt.
FERN = "/root/.hkprobe"
QUELLE = Path(__file__).resolve().parent.parent / "ai-mouse/src/AiMouse/Start/HotkeyWort.cs"

CSPROJ = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <AssemblyName>hkprobe</AssemblyName>
    <RootNamespace>hkprobe</RootNamespace>
  </PropertyGroup>
</Project>
"""

# Die Faelle. Jede Zeile: Beschreibung, Ausdruck, erwartetes Ergebnis.
# Gewaehlt nach FEHLERRICHTUNG, nicht nach Vollstaendigkeit.
PRUEFUNGEN = r"""
using AiMouse.Start;

internal static class Probe
{
    private static int _ok, _fail;

    private static void P(string was, object ist, object soll)
    {
        bool gut = ist?.ToString() == soll?.ToString();
        if (gut) { _ok++; } else { _fail++; }
        Console.WriteLine((gut ? "OK   " : "FAIL ") + was
            + "  ->  ist=" + ist + " soll=" + soll);
    }

    public static int Main()
    {
        int STRG = HotkeyWort.ModStrg, ALT = HotkeyWort.ModAlt, SHIFT = HotkeyWort.ModUmschalt;
        int A = 'A', F5 = 0x74, F12 = 0x7B;

        // ── Die Rechnung: VK im niederwertigen, Modifier im hoeherwertigen Byte
        P("Strg+Alt+A ergibt 0x0641", "0x" + HotkeyWort.Bauen(STRG | ALT, A).ToString("X4"), "0x0641");
        P("Strg+Alt+Umschalt+A ergibt 0x0741", "0x" + HotkeyWort.Bauen(STRG | ALT | SHIFT, A).ToString("X4"), "0x0741");
        P("Strg+Alt+F5 ergibt 0x0674", "0x" + HotkeyWort.Bauen(STRG | ALT, F5).ToString("X4"), "0x0674");
        P("Strg+Alt+F12 ergibt 0x067B", "0x" + HotkeyWort.Bauen(STRG | ALT, F12).ToString("X4"), "0x067B");

        // ── Was NICHT durchgehen darf (Windows wirkt sonst nicht zuverlaessig)
        P("nur Strg  -> keiner", HotkeyWort.Bauen(STRG, A), 0);
        P("nur Alt   -> keiner", HotkeyWort.Bauen(ALT, A), 0);
        P("nur Shift -> keiner", HotkeyWort.Bauen(SHIFT, A), 0);
        P("ohne Modifier -> keiner", HotkeyWort.Bauen(0, A), 0);
        P("Strg+Umschalt (ohne Alt) -> keiner", HotkeyWort.Bauen(STRG | SHIFT, A), 0);
        P("Leertaste ist keine erlaubte Taste", HotkeyWort.Bauen(STRG | ALT, 0x20), 0);
        P("Escape ist keine erlaubte Taste", HotkeyWort.Bauen(STRG | ALT, 0x1B), 0);
        P("Ziffernblock-1 ist keine erlaubte Taste", HotkeyWort.Bauen(STRG | ALT, 0x61), 0);
        P("F13 ist keine erlaubte Taste", HotkeyWort.Bauen(STRG | ALT, 0x7C), 0);

        // ── Positivkontrolle: es wird ueberhaupt etwas durchgelassen.
        //    Ohne sie waere eine Regel, die ALLES ablehnt, „sicher" und wertlos.
        P("Positivkontrolle: 0-9 erlaubt", HotkeyWort.Bauen(STRG | ALT, '7') != 0, true);
        P("Positivkontrolle: Z erlaubt", HotkeyWort.Bauen(STRG | ALT, 'Z') != 0, true);

        // ── Wortform
        P("AlsText Strg+Alt+A", HotkeyWort.AlsText(STRG | ALT, A), "CTRL+ALT+A");
        P("AlsText mit Umschalt", HotkeyWort.AlsText(STRG | ALT | SHIFT, A), "CTRL+ALT+SHIFT+A");
        P("AlsText F5", HotkeyWort.AlsText(STRG | ALT, F5), "CTRL+ALT+F5");
        P("AlsText unzulaessig -> leer", HotkeyWort.AlsText(ALT, A), "");

        // ── Einlesen, auch von Hand getippt
        P("AusText CTRL+ALT+A", HotkeyWort.AusText("CTRL+ALT+A"), "(" + (STRG | ALT) + ", " + A + ")");
        P("AusText klein geschrieben", HotkeyWort.AusText("ctrl+alt+a"), "(" + (STRG | ALT) + ", " + A + ")");
        P("AusText deutsch (STRG/UMSCHALT)", HotkeyWort.AusText("Strg+Alt+Umschalt+A"),
          "(" + (STRG | ALT | SHIFT) + ", " + A + ")");
        P("AusText mit Leerraum", HotkeyWort.AusText(" CTRL + ALT + A "), "(" + (STRG | ALT) + ", " + A + ")");
        P("AusText leer -> (0,0)", HotkeyWort.AusText(""), "(0, 0)");
        P("AusText null -> (0,0)", HotkeyWort.AusText(null), "(0, 0)");
        P("AusText ohne Alt -> (0,0)", HotkeyWort.AusText("CTRL+A"), "(0, 0)");
        P("AusText zwei Tasten -> (0,0)", HotkeyWort.AusText("CTRL+ALT+A+B"), "(0, 0)");
        P("AusText unbekannte Taste -> (0,0)", HotkeyWort.AusText("CTRL+ALT+POS1"), "(0, 0)");
        P("AusText Muell -> (0,0)", HotkeyWort.AusText("///"), "(0, 0)");

        // ── Rundlauf: was geschrieben wurde, muss wieder herauskommen.
        //    Das ist die Eigenschaft, an der die Registry haengt.
        string t = HotkeyWort.AlsText(STRG | ALT | SHIFT, F12);
        P("Rundlauf Text->Werte->Text", HotkeyWort.AlsText(
            HotkeyWort.AusText(t).Modifier, HotkeyWort.AusText(t).Vk), t);
        ushort w = HotkeyWort.Bauen(STRG | ALT, F5);
        P("Rundlauf Wort->Zerlegen->Wort", HotkeyWort.Bauen(
            HotkeyWort.Zerlegen(w).Modifier, HotkeyWort.Zerlegen(w).Vk), w);
        P("Zerlegen(0) -> (0,0)", HotkeyWort.Zerlegen(0), "(0, 0)");

        // ── Tastennamen
        P("TastenName F1", HotkeyWort.TastenName(0x70), "F1");
        P("TastenName F12", HotkeyWort.TastenName(F12), "F12");
        P("TastenCode F12", HotkeyWort.TastenCode("F12"), F12);
        P("TastenCode unbekannt -> 0", HotkeyWort.TastenCode("F99"), 0);

        Console.WriteLine();
        Console.WriteLine("Ergebnis: " + _ok + " OK, " + _fail + " FAIL");
        return _fail == 0 ? 0 : 1;
    }
}
"""


def fern(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(SSH + [DEV, cmd], capture_output=True, text=True)


def main() -> int:
    if not QUELLE.exists():
        print(f"FEHLT: {QUELLE}")
        return 2

    lokal = Path("/tmp") / f"hkprobe-{os_pid()}"
    lokal.mkdir(parents=True, exist_ok=True)
    (lokal / "hkprobe.csproj").write_text(CSPROJ, encoding="utf-8")
    (lokal / "Probe.cs").write_text(PRUEFUNGEN, encoding="utf-8")
    (lokal / "HotkeyWort.cs").write_text(QUELLE.read_text(encoding="utf-8"), encoding="utf-8")

    fern(f"rm -rf {FERN} && mkdir -p {FERN} && chmod 700 {FERN}")
    scp = subprocess.run(
        ["scp", "-i", str(Path.home() / ".ssh" / "id_rsa"), "-q",
         str(lokal / "hkprobe.csproj"), str(lokal / "Probe.cs"), str(lokal / "HotkeyWort.cs"),
         f"{DEV}:{FERN}/"],
        capture_output=True, text=True)
    if scp.returncode != 0:
        print("scp fehlgeschlagen:", scp.stderr)
        return 2

    r = fern(f"cd {FERN} && DOTNET_CLI_TELEMETRY_OPTOUT=1 "
             f"/opt/jarvis/vendor/dotnet/dotnet run -c Release 2>&1")
    print(r.stdout)
    if r.stderr.strip():
        print("stderr:", r.stderr.strip()[:2000])

    # ⚠ EXIT 2, wenn der Lauf gar nicht stattgefunden hat: „konnte nicht
    #   laufen" darf nie wie „bestanden" aussehen.
    if "Ergebnis:" not in r.stdout:
        print("\n⚠ KEINE BILANZZEILE – der Lauf hat nicht stattgefunden.")
        fern(f"rm -rf {FERN}")
        return 2

    fern(f"rm -rf {FERN}")
    return 0 if "0 FAIL" in r.stdout else 1


def os_pid() -> int:
    import os
    return os.getpid()


if __name__ == "__main__":
    sys.exit(main())
