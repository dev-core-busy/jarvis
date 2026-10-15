#!/usr/bin/env python3
"""Fuehrt `JarvisClient.BildAdressePruefen` WIRKLICH aus (2026-09-15).

⚠ WARUM AUSGEFUEHRT UND NICHT IM QUELLTEXT GEMESSEN: der Waechter kann nur
sagen, DASS eine Erlaubnisliste dasteht – nicht, WAS sie durchlaesst. Genau das
ist hier die Frage: die Methode entscheidet, an welche Adresse der Client
greift, nachdem der Server sie genannt hat. Dieselbe Aufteilung wie bei
`LinkZiel` und `ZiehbarRegel`; WinForms laesst sich auf dem Bauserver
uebersetzen, aber nicht ausfuehren – diese Methode ist deshalb bewusst UI-frei
und `static`.

Die ECHTE Datei wird kopiert und die Methode herausgeschnitten, nicht
nachgebaut: ein Nachbau prueft die Annahme des Testautors.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/ai-mouse").is_dir() else \
    Path(__file__).resolve().parent.parent


def _dotnet():
    for kandidat in (Path("/opt/jarvis/vendor/dotnet/dotnet"),
                     ROOT / "vendor" / "dotnet" / "dotnet"):
        if kandidat.exists():
            return kandidat
    gefunden = shutil.which("dotnet")
    return Path(gefunden) if gefunden else None


DOTNET = _dotnet()
QUELLE = ROOT / "ai-mouse" / "src" / "AiMouse" / "Vision" / "JarvisClient.cs"

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


if DOTNET is None:
    # Exit 2: "konnte nicht laufen" darf nie wie "bestanden" aussehen.
    print("ABBRUCH: kein dotnet gefunden (vendor/dotnet oder PATH)")
    sys.exit(2)
if not QUELLE.exists():
    print("ABBRUCH: %s fehlt" % QUELLE)
    sys.exit(2)

# ── MUSS-DURCHLASSEN / DARF-NICHT ──────────────────────────────────────────
# ⚠ EINE MUSS-FREI-LISTE GEHOERT DAZU. Eine Pruefung, die alles ablehnt, waere
# "sicher" und voellig wertlos – dann gaebe es die Anzeige gar nicht mehr.
ERLAUBT = [
    "/api/generated/" + "a" * 32 + ".png",
    "/api/generated/" + "0123456789abcdef" * 2 + ".jpg",
    "/api/generated/" + "f" * 32 + ".jpeg",
    "/api/generated/" + "0" * 32 + ".gif",
    "/api/generated/" + "c" * 32 + ".webp",
    "  /api/generated/" + "b" * 32 + ".PNG  ",   # Leerraum + Endung gross
]
VERBOTEN = [
    "",
    "   ",
    # Absolute Adressen: der Client haengt selbst seine Serveradresse davor –
    # eine absolute hier waere ein Abruf an einen FREMDEN Host.
    "https://fremd.example/api/generated/" + "a" * 32 + ".png",
    "http://169.254.169.254/latest/meta-data/",
    "//fremd.example/api/generated/" + "a" * 32 + ".png",
    # Pfadwechsel: alles, was nicht GENAU der Ausliefer-Endpunkt ist.
    "/api/documents/" + "a" * 32 + ".png",
    "/api/generated/../../etc/passwd",
    "/api/generated/" + "a" * 32 + ".png/../../etc/passwd",
    "/api/settings",
    # Form: der Ausliefer-Endpunkt selbst laesst nur 32 Hex + Endung durch –
    # was er mit 400 abweist, wird gar nicht erst abgerufen.
    "/api/generated/kurz.png",
    "/api/generated/" + "a" * 31 + ".png",
    "/api/generated/" + "a" * 33 + ".png",
    "/api/generated/" + "A" * 32 + ".png",       # Grossbuchstaben: nicht die Form
    "/api/generated/" + "g" * 32 + ".png",       # 'g' ist nicht hex
    "/api/generated/" + "a" * 32 + ".exe",
    "/api/generated/" + "a" * 32 + ".svg",       # SVG kann Skripte tragen
    "/api/generated/" + "a" * 32,                # ohne Endung
    "/api/generated/" + "a" * 32 + ".",
    "file:///etc/passwd",
]

ARB = Path(tempfile.mkdtemp(prefix="bildadresse-", dir="/tmp"))
try:
    (ARB / "P.csproj").write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings>
    <AssemblyName>P</AssemblyName><RootNamespace>P</RootNamespace>
  </PropertyGroup>
</Project>""", encoding="utf-8")

    roh = QUELLE.read_text(encoding="utf-8")
    kopf = "private static string BildAdressePruefen(string? roh)"
    if kopf not in roh:
        print("ABBRUCH: BildAdressePruefen sieht anders aus als erwartet (umbenannt?).")
        sys.exit(2)

    # Methodenrumpf ueber die Klammerbilanz schneiden – ein Schnitt "bis zum
    # ersten }" endete mitten in der Schleife.
    i = roh.index(kopf)
    j = roh.index("{", i)
    tiefe, k = 0, j
    while k < len(roh):
        if roh[k] == "{":
            tiefe += 1
        elif roh[k] == "}":
            tiefe -= 1
            if tiefe == 0:
                break
        k += 1
    rumpf = roh[i:k + 1].replace("private static", "public static", 1)
    if "StartsWith" not in rumpf or len(rumpf) < 200:
        print("ABBRUCH: der Schnitt hat die Methode nicht vollstaendig erfasst.")
        sys.exit(2)

    (ARB / "Pruef.cs").write_text(
        "namespace AiMouse.Vision;\n\npublic static class Pruef\n{\n" + rumpf + "\n}\n",
        encoding="utf-8")

    (ARB / "Main.cs").write_text("""
using AiMouse.Vision;
using System.Text.Json;

var faelle = JsonSerializer.Deserialize<string[]>(Console.In.ReadToEnd())!;
var raus = new List<object>();
foreach (var f in faelle)
{
    raus.Add(new { text = f, ergebnis = Pruef.BildAdressePruefen(f) });
}
Console.WriteLine(JsonSerializer.Serialize(raus));
""", encoding="utf-8")

    umg = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1",
               HOME="/tmp/dotnethome")
    Path("/tmp/dotnethome").mkdir(exist_ok=True)
    b = subprocess.run([str(DOTNET), "build", "-c", "Release", "--nologo"],
                       cwd=ARB, capture_output=True, text=True, timeout=420, env=umg)
    if b.returncode != 0:
        print("ABBRUCH: Testprogramm liess sich nicht uebersetzen:")
        print((b.stdout + b.stderr)[-1500:])
        sys.exit(2)

    exe = next(ARB.glob("bin/Release/net8.0/P.dll"), None)
    if exe is None:
        print("ABBRUCH: gebautes Programm nicht gefunden.")
        sys.exit(2)

    alle = ERLAUBT + VERBOTEN
    lauf = subprocess.run([str(DOTNET), str(exe)], input=json.dumps(alle),
                          capture_output=True, text=True, timeout=120, env=umg)
    if lauf.returncode != 0:
        print("ABBRUCH: Testprogramm gescheitert:\n" + (lauf.stdout + lauf.stderr)[-1200:])
        sys.exit(2)

    erg = {e["text"]: e["ergebnis"] for e in json.loads(lauf.stdout)}

    print("=== Adressen, die DURCHGELASSEN werden muessen ===")
    for f in ERLAUBT:
        check("durchgelassen: %r" % f, erg.get(f, "") != "", "ergebnis=%r" % erg.get(f))
    # Und der Rueckgabewert ist GETRIMMT – der Client haengt ihn an die
    # Serveradresse; Leerraum darin ergaebe eine kaputte URL.
    _mit_raum = "  /api/generated/" + "b" * 32 + ".PNG  "
    check("der Rueckgabewert ist getrimmt", erg.get(_mit_raum, " ").strip() == erg.get(_mit_raum),
          "ergebnis=%r" % erg.get(_mit_raum))

    print("\n=== Adressen, die NICHT abgerufen werden duerfen ===")
    for f in VERBOTEN:
        check("abgewiesen: %r" % f, erg.get(f, "x") == "", "ergebnis=%r" % erg.get(f))

    # ⚠ POSITIVKONTROLLE DES MASSSTABS: haette der Lauf gar nichts gemessen,
    # waere jede "abgewiesen"-Zeile trivial wahr.
    print("\n=== Positivkontrolle ===")
    check("es wurde ueberhaupt etwas durchgelassen (%d von %d)"
          % (sum(1 for f in ERLAUBT if erg.get(f)), len(ERLAUBT)),
          any(erg.get(f) for f in ERLAUBT))
    check("alle Faelle sind wirklich gelaufen", len(erg) == len(set(alle)),
          "%d von %d" % (len(erg), len(set(alle))))
finally:
    shutil.rmtree(ARB, ignore_errors=True)

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
