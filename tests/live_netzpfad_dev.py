#!/usr/bin/env python3
"""Live auf DEV: `Aktualisierung.IstNetzpfad` wird WIRKLICH AUSGEFUEHRT.

Ein Quelltext-Grep beantwortet nicht, was bei `\\\\?\\UNC\\srv\\x` oder bei
`\\\\?\\C:\\x` herauskommt – das entscheidet die .NET-Laufzeit. Diese Probe
uebersetzt die ECHTE Klasse (unveraendert aus dem Repo, bis auf `internal` →
`public`) und laesst sie ueber echte Pfade laufen.

⚠ WOZU DIE REGEL DA IST: wer die EXE DIREKT von der Freigabe startet, liesse
   die Selbstaktualisierung neben der GEMEINSAMEN Datei arbeiten – ein
   beliebiger Arbeitsplatz tauschte sie fuer alle aus. Eine Muss-frei-Liste
   gehoert dazu: eine Regel, die alles als Netzpfad meldet, waere „sicher" und
   naehme jeder normalen Installation die Aktualisierung.

⚠ WAS HIER NICHT MESSBAR IST: das verbundene Netzlaufwerk (`Z:\\…`). Es haengt
   an `DriveInfo.DriveType`, und unter Linux gibt es keine Windows-Laufwerke.
   Belegt ist der UNC-Teil (die haeufige Lage) und dass die Funktion bei einem
   Laufwerkspfad NICHT wirft und „lokal" meldet.

Aufruf auf DEV: python3 tests/live_netzpfad_dev.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/ai-mouse").is_dir() else \
    Path(__file__).resolve().parent.parent


def _dotnet():
    for k in (Path("/opt/jarvis/vendor/dotnet/dotnet"), ROOT / "vendor" / "dotnet" / "dotnet"):
        if k.exists():
            return k
    g = shutil.which("dotnet")
    return Path(g) if g else None


DOTNET = _dotnet()
QUELLE = ROOT / "ai-mouse" / "src" / "AiMouse" / "Update" / "Aktualisierung.cs"

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
    print("ABBRUCH: kein dotnet gefunden (Exit 2 – nicht gelaufen, nicht bestanden)")
    sys.exit(2)
if not QUELLE.exists():
    print("ABBRUCH: %s fehlt (Exit 2)" % QUELLE)
    sys.exit(2)

# ── NETZ (Selbstaktualisierung MUSS aus sein) ───────────────────────────────
NETZ = [
    r"\\fileserver\Software\AI-Maus\AiMouse.exe",
    r"\\fileserver.nexus-ag.intern\Software\Werkzeuge\AiMouse.exe",
    r"\\192.168.1.10\tools\AiMouse.exe",
    r"\\?\UNC\fileserver\Software\AiMouse.exe",
    r"\\?\unc\fileserver\Software\AiMouse.exe",   # Gross/Klein egal
]
# ── LOKAL (Selbstaktualisierung MUSS laufen) ────────────────────────────────
# ⚠ Ohne diese Haelfte waere eine Regel, die alles blockiert, gruen - und
#   naehme JEDER normalen Installation die Aktualisierung.
LOKAL = [
    r"C:\Program Files\AI-Maus\AiMouse.exe",
    r"C:\Users\mueller\AppData\Local\AiMouse\AiMouse.exe",
    r"D:\tools\AiMouse.exe",
    r"\\?\C:\Program Files\AI-Maus\AiMouse.exe",   # lange Form, ABER lokal
    "",                                            # nicht ermittelbar
]

ARB = Path(tempfile.mkdtemp(prefix="netzpfad-", dir="/tmp"))
try:
    (ARB / "P.csproj").write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings>
    <AssemblyName>P</AssemblyName><RootNamespace>P</RootNamespace>
  </PropertyGroup>
</Project>""", encoding="utf-8")

    # ⚠ DIE ECHTE DATEI, NICHT NACHGEBAUT. Nur die Sichtbarkeit wird geoeffnet
    #   und der Rest der Klasse (HttpClient, ConfigStore, …) weggeschnitten –
    #   gemessen wird ausschliesslich `IstNetzpfad`.
    roh = QUELLE.read_text(encoding="utf-8")
    i = roh.find("internal static bool IstNetzpfad(string exe)")
    if i < 0:
        print("ABBRUCH: IstNetzpfad nicht gefunden (umbenannt?) – Exit 2")
        sys.exit(2)
    tief, j = 0, roh.find("{", i)
    k = j
    while k < len(roh):
        if roh[k] == "{":
            tief += 1
        elif roh[k] == "}":
            tief -= 1
            if tief == 0:
                break
        k += 1
    rumpf = roh[i:k + 1].replace("internal static bool", "public static bool", 1)
    # Positivkontrolle des Schnitts: der Rumpf muss vollstaendig sein.
    if rumpf.count("{") != rumpf.count("}") or "DriveType.Network" not in rumpf:
        print("ABBRUCH: Schnitt unvollstaendig – Exit 2")
        sys.exit(2)

    (ARB / "R.cs").write_text(
        "namespace AiMouse.Update;\npublic static class Regel\n{\n"
        + rumpf + "\n}\n", encoding="utf-8")

    (ARB / "Main.cs").write_text("""
using AiMouse.Update;
using System.Text.Json;

var faelle = JsonSerializer.Deserialize<string[]>(Console.In.ReadToEnd())!;
var raus = new List<object>();
foreach (var f in faelle)
{
    bool netz;
    string fehler = "";
    try { netz = Regel.IstNetzpfad(f); }
    catch (Exception e) { netz = false; fehler = e.GetType().Name; }
    raus.Add(new { pfad = f, netz, fehler });
}
Console.WriteLine(JsonSerializer.Serialize(raus));
""", encoding="utf-8")

    print("=" * 70)
    print("IstNetzpfad – AUSGEFUEHRT gegen echte Pfade")
    print("=" * 70)
    b = subprocess.run([str(DOTNET), "build", "-v", "q", "--nologo",
                        "-p:EnableWindowsTargeting=true"],
                       cwd=ARB, capture_output=True, text=True, timeout=300)
    if b.returncode != 0:
        print("ABBRUCH: Bau fehlgeschlagen\n" + (b.stdout or "")[-1500:])
        sys.exit(2)

    r = subprocess.run([str(DOTNET), "run", "--no-build", "-v", "q", "--nologo"],
                       cwd=ARB, input=json.dumps(NETZ + LOKAL),
                       capture_output=True, text=True, timeout=180)
    zeile = [z for z in (r.stdout or "").splitlines() if z.startswith("[")]
    if not zeile:
        print("ABBRUCH: keine Ausgabe\n" + (r.stdout or "") + (r.stderr or "")[-800:])
        sys.exit(2)
    erg = {e["pfad"]: e for e in json.loads(zeile[-1])}

    print("\n── MUSS als Netzfreigabe gelten (kein Selbst-Update) ──")
    for pf in NETZ:
        e = erg.get(pf, {})
        check("%-58s -> Netz" % (pf[:58]), e.get("netz") is True,
              "netz=%s fehler=%s" % (e.get("netz"), e.get("fehler")))

    print("\n── MUSS lokal bleiben (Selbst-Update laeuft weiter) ──")
    for pf in LOKAL:
        e = erg.get(pf, {})
        check("%-58s -> lokal" % ((pf or "(leer)")[:58]), e.get("netz") is False,
              "netz=%s fehler=%s" % (e.get("netz"), e.get("fehler")))

    print("\n── Die Funktion wirft NIE ──")
    wirft = [p for p, e in erg.items() if e.get("fehler")]
    check("kein Wurf ueber alle %d Faelle" % len(erg), not wirft, wirft)

    # ⚠ POSITIVKONTROLLE: eine Regel, die alles ablehnt, waere „sicher" und
    #   wertlos – und eine, die alles meldet, naehme jedem die Aktualisierung.
    check("Positivkontrolle: es wird ueberhaupt unterschieden",
          any(e.get("netz") for e in erg.values())
          and any(not e.get("netz") for e in erg.values()))
finally:
    shutil.rmtree(ARB, ignore_errors=True)

print("\n" + "=" * 70)
print("%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
