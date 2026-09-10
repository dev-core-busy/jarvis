#!/usr/bin/env python3
"""Live auf DEV: `TrayApplicationContext.TastenAus` wird WIRKLICH AUSGEFUEHRT.

⚠ WARUM DAS EINE EIGENE PROBE BRAUCHT: die zwei Tastenfelder sind
   ENTGEGENGESETZT und koennen sich widersprechen.

     RightDragKey  "die Geste nimmt jeden Rechtsklick – ausser mit dieser Taste"
     GestureKey    "der Rechtsklick gehoert der Anwendung – ausser mit dieser Taste"

   Beides gleichzeitig ergibt keinen Sinn; dieselbe Taste koennte zweierlei
   heissen. `TastenAus` ist die EINE Stelle, die das aufloest – waere sie
   falsch, zeigte die Oberflaeche etwas anderes an, als tatsaechlich gilt.

⚠ UND DIE VORGABEN SIND JE FELD VERSCHIEDEN: Unbekanntes ergibt bei der
   Gestentaste `Keine`, bei der Durchreich-Taste `Strg`. Beide Male ist das
   das BISHERIGE Verhalten – das ist die Eigenschaft, die hier zaehlt.

Aufruf auf DEV: python3 tests/live_tastenaus_dev.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/ai-mouse").is_dir() else \
    Path(__file__).resolve().parent.parent
DOTNET = Path("/opt/jarvis/vendor/dotnet/dotnet")
SRC = ROOT / "ai-mouse" / "src" / "AiMouse"
TRAY = SRC / "TrayApplicationContext.cs"

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


def schnitt(quelle, kopf):
    """Die Funktion samt Rumpf – Block oder Ausdruckskoerper.

    ⚠ Ein Klammer-Schnitt taugt nur fuer Methoden MIT Block-Rumpf; bei einem
    `=>` landet er im naechsten Rumpf und zieht fremden Code mit (am
    2026-09-10 genau so bezahlt).
    """
    i = quelle.find(kopf)
    if i < 0:
        return ""
    j, semi = quelle.find("{", i), quelle.find(";", i)
    if j < 0 or (0 <= semi < j):
        return quelle[i:semi + 1]
    tiefe, k = 1, j + 1
    while k < len(quelle) and tiefe:
        if quelle[k] == "{":
            tiefe += 1
        elif quelle[k] == "}":
            tiefe -= 1
        k += 1
    # ⚠ EIN AUSDRUCKSKOERPER MIT switch-BLOCK IST BEIDES ZUGLEICH:
    #   `=> wert switch { … };` – die schliessende Klammer ist NICHT das Ende,
    #   das `;` dahinter gehoert dazu. Ohne es fehlt im Ergebnis genau ein
    #   Zeichen, und der Uebersetzer meldet „; erwartet" in einer Zeile, die
    #   im Original voellig richtig ist (am 2026-09-10 genau so passiert).
    while k < len(quelle) and quelle[k] in " \t\r\n":
        k += 1
    if k < len(quelle) and quelle[k] == ";":
        k += 1
    return quelle[i:k]


tray = TRAY.read_text(encoding="utf-8")
ta = schnitt(tray, "internal static (GestenTaste Geste, GestenTaste Durchreichen) TastenAus")
ga = schnitt(tray, "private static GestenTaste GestenTasteAus")
check("TastenAus ist schneidbar", bool(ta) and "GestureKey" in ta)
check("GestenTasteAus ist schneidbar", bool(ga) and "switch" in ga)
# ⚠ Positivkontrolle des SCHNITTS selbst: ein Ausdruckskoerper muss auf `;`
#   enden. Ohne sie faellt ein halber Schnitt erst beim Uebersetzen auf – und
#   sieht dann wie ein Fehler im Produktivcode aus.
check("beide Schnitte sind vollstaendig (enden auf } oder ;)",
      ta.rstrip().endswith("}") and ga.rstrip().endswith(";"),
      repr(ga[-40:]))
if not (ta and ga):
    print(f"\n{_ok} OK, {_fail} FAIL")
    sys.exit(1)

# (GestureKey, RightDragKey) -> (Geste, Durchreichen)
FAELLE = [
    # ── Vorgabe: alles wie vor dem 2026-09-10 ──────────────────────────────
    (("", "ctrl"), ("Keine", "Strg")),
    (("none", "ctrl"), ("Keine", "Strg")),
    (("", "none"), ("Keine", "Keine")),
    (("", "alt"), ("Keine", "Alt")),

    # ── Gestentaste gesetzt: sie gewinnt, Durchreichen faellt weg ──────────
    # ⚠ DAS IST DIE ZUSAGE: mit Gestentaste geht der Rechtsklick ohnehin an
    #   die Anwendung – "durchreichen mit Taste" haette dann keine Bedeutung,
    #   und dieselbe Taste koennte zweierlei heissen.
    (("ctrl", "ctrl"), ("Strg", "Keine")),
    (("alt", "ctrl"), ("Alt", "Keine")),
    (("shift", "alt"), ("Umschalt", "Keine")),
    (("ctrl", "none"), ("Strg", "Keine")),

    # ── Unbrauchbare Werte: JE FELD in die harmlose Richtung ───────────────
    # Ein Tippfehler in der Registry darf weder das Lasso abschalten (links)
    # noch Windows' Right-Drag (rechts).
    (("quatsch", "ctrl"), ("Keine", "Strg")),
    (("", "quatsch"), ("Keine", "Strg")),
    (("quatsch", "quatsch"), ("Keine", "Strg")),
    # ⚠ LEER IST JE FELD ETWAS ANDERES: bei der Gestentaste heisst es „keine"
    #   (der Normalfall), bei der Durchreich-Taste die Vorgabe Strg. Der Fall
    #   haelt fest, dass die entfernte `"" => Keine`-Zeile wirklich weg bleibt.
    (("", ""), ("Keine", "Strg")),

    # ── Schreibweise ───────────────────────────────────────────────────────
    (("CTRL", "none"), ("Strg", "Keine")),
    ((" alt ", "none"), ("Alt", "Keine")),
    (("Shift", "none"), ("Umschalt", "Keine")),
]

PROGRAMM = """
using System.Text.Json;
using AiMouse.Input;

internal sealed class AppSettings
{
    public string RightDragKey { get; set; } = "ctrl";
    public string GestureKey { get; set; } = string.Empty;
}

internal static class P
{
__TA__

__GA__

    public static void Main()
    {
        var faelle = JsonSerializer.Deserialize<List<List<string>>>(
            Console.In.ReadToEnd())!;
        var raus = new List<string[]>();
        foreach (var f in faelle)
        {
            var t = TastenAus(new AppSettings { GestureKey = f[0], RightDragKey = f[1] });
            raus.Add(new[] { t.Geste.ToString(), t.Durchreichen.ToString() });
        }
        Console.Write(JsonSerializer.Serialize(raus));
    }
}
"""

with tempfile.TemporaryDirectory(prefix="tastenprobe-") as tmp:
    tmp = Path(tmp)
    (tmp / "p.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>"
        "<Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings>"
        "<AssemblyName>p</AssemblyName>"
        "<InvariantGlobalization>true</InvariantGlobalization>"
        "</PropertyGroup></Project>", encoding="utf-8")
    shutil.copy2(SRC / "Input" / "GestenTaste.cs", tmp / "GestenTaste.cs")
    (tmp / "P.cs").write_text(
        PROGRAMM.replace("__TA__", ta).replace("__GA__", ga), encoding="utf-8")

    umg = {"DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",
           "HOME": str(tmp), "PATH": "/usr/bin:/bin"}
    bau = subprocess.run([str(DOTNET), "build", "-v", "q", "--nologo",
                          str(tmp / "p.csproj")],
                         capture_output=True, text=True, cwd=tmp, env=umg)
    if bau.returncode != 0:
        print("ABBRUCH: uebersetzt nicht\n" + (bau.stdout or "")[-1500:])
        sys.exit(2)
    dll = next(tmp.glob("bin/**/p.dll"), None)
    if dll is None:
        print("ABBRUCH: p.dll fehlt")
        sys.exit(2)
    lauf = subprocess.run([str(DOTNET), str(dll)],
                          input=json.dumps([[a, b] for (a, b), _ in FAELLE]),
                          capture_output=True, text=True, env=umg)
    if lauf.returncode != 0:
        print("ABBRUCH: laeuft nicht\n" + (lauf.stderr or "")[-600:])
        sys.exit(2)
    ist = json.loads(lauf.stdout)

print("\n── Die Aufloesung, wirklich ausgefuehrt ──")
for ((gk, rd), soll), g in zip(FAELLE, ist):
    check(f"GestureKey={gk!r:12} RightDragKey={rd!r:10} -> {soll}",
          tuple(g) == soll, str(g))

# ⚠ Ohne diese Kontrolle waere eine Aufloesung, die IMMER dasselbe liefert,
#   unauffaellig – alle Nein-Faelle waeren dann trivial erfuellt.
check("Positivkontrolle: es kommen verschiedene Ergebnisse heraus",
      len({tuple(x) for x in ist}) >= 5)
# Und die tragende Eigenschaft noch einmal als Ganzes:
check("REGEL: mit Gestentaste ist Durchreichen IMMER abgeschaltet",
      all(g[1] == "Keine" for ((gk, _), _), g in zip(FAELLE, ist)
          if gk.strip().lower() in ("ctrl", "alt", "shift")))

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
