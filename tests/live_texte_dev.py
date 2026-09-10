#!/usr/bin/env python3
"""Live auf DEV: die Texttabelle wird WIRKLICH AUSGEFUEHRT.

Der Waechter in `test_ai_mouse.py` prueft am Quelltext, dass jeder Eintrag
`T(de, en)` benutzt. Das belegt "zweisprachig DEKLARIERT" – nicht, dass beim
Umschalten auch etwas anderes herauskommt, und schon gar nicht, dass die Marke
richtig aufgeloest wird. Beides entscheidet die Laufzeit.

⚠ GEPRUEFT WIRD DIE EIGENSCHAFT, NICHT DER WORTLAUT: kein Eintrag ist leer,
   Deutsch und Englisch unterscheiden sich, und die Marke folgt den
   Einstellungen statt einer Konstante.

`Texte`, `AppSettings` und `Vorgaben` sind UI-frei – deshalb laesst sich das
hier ueberhaupt ausfuehren (WinForms liefe auf dem Bauserver nicht).

Aufruf auf DEV: python3 tests/live_texte_dev.py
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/ai-mouse").is_dir() else \
    Path(__file__).resolve().parent.parent
DOTNET = Path("/opt/jarvis/vendor/dotnet/dotnet")
SRC = ROOT / "ai-mouse" / "src" / "AiMouse"

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

# Alle Texteintraege aus der ECHTEN Datei – keine abgetippte Liste, sonst
# faellt genau der naechste neue Eintrag heraus.
texte_cs = (SRC / "Localization" / "Texte.cs").read_text(encoding="utf-8")
NAMEN = [n for n in re.findall(r"public static string (\w+) =>", texte_cs)]
check(f"Eintraege gefunden ({len(NAMEN)})", len(NAMEN) > 30)

with tempfile.TemporaryDirectory(prefix="txtprobe-") as tmp:
    tmp = Path(tmp)
    (tmp / "probe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>"
        "<Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings>"
        "<AssemblyName>probe</AssemblyName><InvariantGlobalization>true</InvariantGlobalization>"
        "</PropertyGroup></Project>", encoding="utf-8")

    # Die ECHTEN Dateien, unveraendert.
    for rel in ("Localization/Texte.cs", "Configuration/AppSettings.cs",
                "Configuration/Vorgaben.cs"):
        ziel = tmp / Path(rel).name
        shutil.copy2(SRC / rel, ziel)

    zugriffe = "\n".join(
        f'        raus["{n}"] = Texte.{n};' for n in NAMEN)
    (tmp / "Program.cs").write_text(f'''
using System.Text.Json;
using AiMouse.Configuration;
using AiMouse.Localization;

static Dictionary<string, string> Alle(string sprache, string marke)
{{
    Texte.Anwenden(new AppSettings {{ Sprache = sprache, Marke = marke }});
    var raus = new Dictionary<string, string>();
{zugriffe}
    raus["__Marke"] = Texte.Marke;
    raus["__Zeichen"] = Texte.Zeichen(7);
    return raus;
}}

var alles = new Dictionary<string, Dictionary<string, string>>
{{
    ["de"] = Alle("de", "Nexus DP"),
    ["en"] = Alle("en", "Nexus DP"),
    ["leer"] = Alle("de", ""),
    ["fremd"] = Alle("fr", "Nexus DP"),
}};
Console.Write(JsonSerializer.Serialize(alles));
''', encoding="utf-8")

    umg = {"DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",
           "HOME": str(tmp), "PATH": "/usr/bin:/bin"}
    bau = subprocess.run([str(DOTNET), "build", "-v", "q", "--nologo", str(tmp / "probe.csproj")],
                         capture_output=True, text=True, cwd=tmp, env=umg)
    if bau.returncode != 0:
        print("ABBRUCH: die Probe uebersetzt nicht\n" + (bau.stdout or "") + (bau.stderr or ""))
        sys.exit(2)

    dll = next(tmp.glob("bin/**/probe.dll"), None)
    if dll is None:
        print("ABBRUCH: probe.dll nicht gefunden")
        sys.exit(2)

    lauf = subprocess.run([str(DOTNET), str(dll)], capture_output=True, text=True, env=umg)
    if lauf.returncode != 0:
        print("ABBRUCH: die Probe laeuft nicht\n" + (lauf.stderr or ""))
        sys.exit(2)
    d = json.loads(lauf.stdout)

print("\n── Die Texttabelle, wirklich ausgefuehrt ──")

leer = [n for n, v in d["de"].items() if not v.strip()]
check("kein Eintrag ist leer (eine leere Beschriftung sieht kaputt aus)",
      not leer, repr(leer[:5]))
leer_en = [n for n, v in d["en"].items() if not v.strip()]
check("auch nicht auf Englisch", not leer_en, repr(leer_en[:5]))

gleich = [n for n in d["de"] if d["de"][n] == d["en"][n]]
# Eintraege, die in beiden Sprachen gleich lauten DUERFEN – begruendet:
ERLAUBT_GLEICH = {
    "__Marke",       # ein Eigenname wird nicht uebersetzt
    "Marke",
    "PngFilter",     # "PNG-Bild|*.png" vs "PNG image|*.png" – s.u. gepruefte Ausnahme
}
unerwartet = [n for n in gleich if n not in ERLAUBT_GLEICH]
check(f"Deutsch und Englisch unterscheiden sich ({len(gleich)} gleich)",
      not unerwartet, repr(unerwartet[:6]))

check("die Umschaltung wirkt ueberhaupt (Stichprobe)",
      d["de"]["BildKopieren"] == "Bild in die Zwischenablage"
      and d["en"]["BildKopieren"] == "Copy image to clipboard",
      f'de={d["de"]["BildKopieren"]!r} en={d["en"]["BildKopieren"]!r}')
check("der gemeldete zweite Eintrag ebenso",
      d["de"]["BildSpeichern"].startswith("Bild speichern")
      and d["en"]["BildSpeichern"].startswith("Save image"))

# ⚠ Alles ausser "en" ist Deutsch – fail-safe in die haeufigere Richtung.
check("eine unbekannte Sprache ergibt Deutsch, nicht Kauderwelsch",
      d["fremd"]["BildKopieren"] == d["de"]["BildKopieren"])

# ── Die Marke ──────────────────────────────────────────────────────────────
check("die Marke kommt aus den Einstellungen", d["de"]["__Marke"] == "Nexus DP")
check("und faellt bei leerem Wert auf den einkompilierten zurueck – nie auf leer",
      d["leer"]["__Marke"].strip() != "",
      repr(d["leer"]["__Marke"]))
check("die Freigabe-Meldung nennt die Marke, nicht 'AI Mouse'",
      "Nexus DP" in d["de"]["KeineFreigabe"] and "AI Mouse" not in d["de"]["KeineFreigabe"],
      d["de"]["KeineFreigabe"][:70])
check("auch auf Englisch",
      "Nexus DP" in d["en"]["KeineFreigabe"] and "AI Mouse" not in d["en"]["KeineFreigabe"])
check("und der Admin-Hinweis zum Rechtsklick ebenso",
      "Nexus DP" in d["de"]["KlickNichtWeitergereichtAdmin"])

# ── Die Zeichenzahl ist ein FORMAT, kein fester Text ───────────────────────
check("die Zeichenzahl setzt die Zahl ein",
      d["de"]["__Zeichen"] == "7 Zeichen" and d["en"]["__Zeichen"] == "7 characters",
      f'de={d["de"]["__Zeichen"]!r} en={d["en"]["__Zeichen"]!r}')

# Positivkontrolle: die Probe kann ueberhaupt einen Unterschied sehen.
check("Positivkontrolle: die beiden Saetze sind nicht identisch",
      d["de"] != d["en"])

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
