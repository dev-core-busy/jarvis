#!/usr/bin/env python3
"""Live auf DEV: `LinkZiel.IstWeb` wird WIRKLICH AUSGEFUEHRT.

Ein Quelltext-Grep beantwortet nicht, was `Uri.TryCreate` mit `ms-msdt:`,
`file:///C:/…` oder `\\\\server\\freigabe` macht – das entscheidet die
.NET-Laufzeit. Diese Probe uebersetzt die ECHTE Klasse (unveraendert aus dem
Repo) in ein winziges Konsolenprogramm und laesst sie ueber echte Faelle laufen.

⚠ Die Faelle sind ANGRIFFSFAELLE, keine Stichprobe: der Linktext stammt aus
   einer Modellantwort ueber einen Bildschirmausschnitt – also aus Fremdtext.

Aufruf auf DEV: python3 tests/live_linkziel_dev.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/ai-mouse").is_dir() else \
    Path(__file__).resolve().parent.parent
DOTNET = Path("/opt/jarvis/vendor/dotnet/dotnet")
QUELLE = ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "LinkZiel.cs"

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


if not DOTNET.exists():
    print(f"ABBRUCH: kein dotnet unter {DOTNET}")
    sys.exit(2)
if not QUELLE.exists():
    print(f"ABBRUCH: {QUELLE} fehlt")
    sys.exit(2)

# ── MUSS-OEFFNEN / DARF-NICHT-OEFFNEN ───────────────────────────────────────
# Eine Muss-frei-Liste gehoert dazu: eine Pruefung, die alles ablehnt, waere
# "sicher" und wertlos (Register).
ERLAUBT = [
    "https://jarvis-ai.info/hilfe",
    "http://intranet/seite?a=1&b=2",
    "https://dp.nexerius.nexus-ag.de/portal#abschnitt",
    "www.beispiel.de",                       # DetectUrls meldet auch schemenlos
    "WWW.Beispiel.de/Pfad",
    "https://192.168.1.10:8443/x",
    "  https://mit-leerraum.de  ",
    # ⚠ DIESER Fall misst das `Trim()`, der darueber NICHT: `Uri.TryCreate`
    # trimmt selbst (gemessen) – nur beim schemenlosen `www.` mit Leerraum
    # greift sonst das `StartsWith` nicht und die Adresse faellt durch.
    "  www.mit-leerraum.de  ",
]
VERBOTEN = [
    "file:///C:/Windows/System32/calc.exe",  # ShellExecute wuerde starten
    "file://server/freigabe/x.exe",
    "\\\\server\\freigabe\\daten",           # UNC -> NTLM-Leak an fremden Host
    "\\\\1.2.3.4\\c$",
    "ms-msdt:/id PCWDiagnostic",             # bekannter Missbrauchspfad
    "search-ms:query=x&crumb=location:\\\\1.2.3.4\\x",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "mailto:jemand@example.com",             # kein Web – bewusst nicht geoeffnet
    "ftp://server/datei",
    "shell:startup",
    "",
    "   ",
    "kein link",
    "C:\\Users\\Public\\evil.exe",
]

ARB = Path(tempfile.mkdtemp(prefix="linkziel-", dir="/tmp"))
try:
    (ARB / "P.csproj").write_text("""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings>
    <AssemblyName>P</AssemblyName><RootNamespace>P</RootNamespace>
  </PropertyGroup>
</Project>""", encoding="utf-8")

    # ⚠ Die ECHTE Datei wird KOPIERT, nicht nachgebaut – ein Nachbau prueft die
    # Annahme des Testautors (Register). `internal` -> `public` ist die einzige
    # Aenderung, damit das Testprogramm sie sieht.
    roh = QUELLE.read_text(encoding="utf-8")
    if "internal static class LinkZiel" not in roh:
        print("ABBRUCH: LinkZiel sieht anders aus als erwartet (umbenannt?).")
        sys.exit(2)
    (ARB / "LinkZiel.cs").write_text(
        roh.replace("internal static class LinkZiel", "public static class LinkZiel"),
        encoding="utf-8")

    (ARB / "Main.cs").write_text("""
using AiMouse.Ui;
using System.Text.Json;

var faelle = JsonSerializer.Deserialize<string[]>(Console.In.ReadToEnd())!;
var raus = new List<object>();
foreach (var f in faelle)
{
    bool ok = LinkZiel.IstWeb(f, out Uri? a);
    raus.Add(new { text = f, ok, adresse = a?.AbsoluteUri ?? "" });
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
        print("ABBRUCH: P.dll nicht gefunden")
        sys.exit(2)

    print("=" * 74)
    print("LIVE: LinkZiel.IstWeb – ausgefuehrt, nicht gelesen")
    print("=" * 74)

    r = subprocess.run([str(DOTNET), str(exe)], input=json.dumps(ERLAUBT + VERBOTEN),
                       capture_output=True, text=True, timeout=120, env=umg)
    if r.returncode != 0:
        print("ABBRUCH: Lauf gescheitert:", (r.stdout + r.stderr)[-800:])
        sys.exit(2)
    erg = {e["text"]: e for e in json.loads(r.stdout)}

    print("\n── MUSS geoeffnet werden ──")
    for f in ERLAUBT:
        e = erg[f]
        check(f"{f!r} -> {e['adresse'] or '(keine)'}", e["ok"] and e["adresse"], json.dumps(e))

    print("\n── DARF NICHT geoeffnet werden ──")
    for f in VERBOTEN:
        e = erg[f]
        check(f"abgewiesen: {f!r}", not e["ok"], json.dumps(e))

    print("\n── Eigenschaften ──")
    check("schemenlose Adressen werden zu HTTPS (nicht http)",
          erg["www.beispiel.de"]["adresse"].startswith("https://"),
          erg["www.beispiel.de"]["adresse"])
    check("Leerraum wird abgeschnitten (auch bei schemenloser Adresse)",
          erg["  www.mit-leerraum.de  "]["adresse"] == "https://www.mit-leerraum.de/",
          erg["  www.mit-leerraum.de  "]["adresse"])
    check("die zurueckgegebene Adresse traegt IMMER ein Web-Schema",
          all(e["adresse"].startswith(("http://", "https://"))
              for e in erg.values() if e["ok"]))
    # Positivkontrolle: eine Pruefung, die ALLES ablehnt, waere trivial "sicher".
    check("Positivkontrolle: es wird ueberhaupt etwas durchgelassen",
          sum(1 for e in erg.values() if e["ok"]) == len(ERLAUBT),
          str(sum(1 for e in erg.values() if e["ok"])))

finally:
    shutil.rmtree(ARB, ignore_errors=True)

print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(1 if _fail else 0)
