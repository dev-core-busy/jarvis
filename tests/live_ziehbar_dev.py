#!/usr/bin/env python3
"""Live auf DEV: `ZiehbarRegel.IstZiehbar` wird WIRKLICH AUSGEFUEHRT.

⚠ WAS DIESE PROBE NICHT KANN: die UIA-Abfrage selbst (`ZiehbarPruefer`) laeuft
   hier nicht – sie braucht Windows und eine echte Oberflaeche. Gemessen wird
   die ENTSCHEIDUNG: was folgt aus ControlType + Pattern-Merkmalen. Genau
   deshalb ist die Regel von der COM-Schicht getrennt.

⚠ DIE FAELLE SIND NACH DER FEHLERRICHTUNG GEWAEHLT. Ein falsches JA verschiebt
   womoeglich eine Datei, die niemand anfassen wollte; ein falsches NEIN kostet
   nur ein Lasso. Die "darf-nicht"-Liste ist deshalb laenger als die "muss".

Aufruf auf DEV: python3 tests/live_ziehbar_dev.py
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
QUELLE = ROOT / "ai-mouse" / "src" / "AiMouse" / "Input" / "ZiehbarRegel.cs"

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

# ControlType-Ids aus UIAutomationClient.idl (im Waechter gegen die Quelle
# abgeglichen – hier stehen sie fuer die Lesbarkeit der Faelle).
T = {
    "Button": 50000, "Hyperlink": 50005, "Image": 50006, "ListItem": 50007,
    "List": 50008, "Edit": 50004, "Text": 50020, "TreeItem": 50024,
    "Custom": 50025, "Group": 50026, "DataItem": 50029, "Document": 50030,
    "Window": 50032, "Pane": 50033, "Tree": 50023, "MenuItem": 50011,
}

# (Name, controlType, dragPattern, auswaehlbar, erwartet)
FAELLE = [
    # ── MUSS ziehbar sein ──────────────────────────────────────────────────
    ("Datei im Explorer (ListItem)",       T["ListItem"], False, True,  True),
    ("Ordner im Navigationsbaum",          T["TreeItem"], False, True,  True),
    ("Zeile in einer Detailansicht",       T["DataItem"], False, True,  True),
    ("Link im Browser",                    T["Hyperlink"], False, False, True),
    ("Bild im Browser",                    T["Image"],    False, False, True),
    # Sagt die Anwendung es selbst, gilt das – unabhaengig vom Typ.
    ("beliebiges Element MIT DragPattern", T["Group"],    True,  False, True),
    ("sogar ein Text mit DragPattern",     T["Text"],     True,  False, True),

    # ── DARF NICHT ziehbar sein ────────────────────────────────────────────
    # ⚠ Der leere Bereich einer Liste – genau dort will man das Lasso.
    ("leerer Bereich einer Liste",         T["List"],     False, False, False),
    ("leerer Bereich eines Baums",         T["Tree"],     False, False, False),
    ("Fensterflaeche",                     T["Pane"],     False, False, False),
    ("Fenster selbst",                     T["Window"],   False, False, False),
    ("Gruppe / Rahmen",                    T["Group"],    False, False, False),
    # ⚠ In Text/Dokument/Eingabefeld zieht man eine AUSWAHL, kein Objekt –
    #   ein durchgereichter Rechtsklick oeffnet dort das Kontextmenue.
    ("Fliesstext",                         T["Text"],     False, False, False),
    ("Dokument",                           T["Document"], False, False, False),
    ("Eingabefeld",                        T["Edit"],     False, False, False),
    ("Schaltflaeche",                      T["Button"],   False, False, False),
    ("Menueeintrag",                       T["MenuItem"], False, False, False),
    # ⚠ DER WICHTIGSTE NEIN-FALL: `Custom` meldet der moderne Explorer fuer
    #   fast alles. Als Freibrief waere das die Aufhebung der ganzen Regel.
    ("Custom OHNE weiteren Beleg",         T["Custom"],   False, False, False),
    ("Custom MIT Auswahl-Merkmal",         T["Custom"],   False, True,  True),
    # Unbekannter Typ (kuenftige Windows-Fassung) → im Zweifel nein.
    ("unbekannter Elementtyp",             59999,         False, False, False),
    ("gar kein Element (0)",               0,             False, False, False),
    ("gar kein Element, aber auswaehlbar", 0,             False, True,  False),
]

with tempfile.TemporaryDirectory(prefix="ziehprobe-") as tmp:
    tmp = Path(tmp)
    (tmp / "probe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>"
        "<Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings>"
        "<AssemblyName>probe</AssemblyName>"
        "<InvariantGlobalization>true</InvariantGlobalization>"
        "</PropertyGroup></Project>", encoding="utf-8")

    # ⚠ DIE ECHTE DATEI, unveraendert kopiert.
    shutil.copy2(QUELLE, tmp / "ZiehbarRegel.cs")

    (tmp / "Program.cs").write_text('''
using System.Text.Json;
using AiMouse.Input;

string roh = Console.In.ReadToEnd();
var faelle = JsonSerializer.Deserialize<List<List<int>>>(roh)!;
var raus = new List<bool>();
foreach (var f in faelle)
{
    raus.Add(ZiehbarRegel.IstZiehbar(f[0], f[1] != 0, f[2] != 0));
}
Console.Write(JsonSerializer.Serialize(raus));
''', encoding="utf-8")

    umg = {"DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",
           "HOME": str(tmp), "PATH": "/usr/bin:/bin"}
    bau = subprocess.run([str(DOTNET), "build", "-v", "q", "--nologo",
                          str(tmp / "probe.csproj")],
                         capture_output=True, text=True, cwd=tmp, env=umg)
    if bau.returncode != 0:
        print("ABBRUCH: die Probe uebersetzt nicht\n"
              + (bau.stdout or "") + (bau.stderr or ""))
        sys.exit(2)

    dll = next(tmp.glob("bin/**/probe.dll"), None)
    if dll is None:
        print("ABBRUCH: probe.dll nicht gefunden")
        sys.exit(2)

    eingabe = json.dumps([[c, 1 if d else 0, 1 if a else 0]
                          for _, c, d, a, _ in FAELLE])
    lauf = subprocess.run([str(DOTNET), str(dll)], input=eingabe,
                          capture_output=True, text=True, env=umg)
    if lauf.returncode != 0:
        print("ABBRUCH: die Probe laeuft nicht\n" + (lauf.stderr or ""))
        sys.exit(2)
    ist = json.loads(lauf.stdout)

print("── Die Regel, wirklich ausgefuehrt ──")
for (name, ct, dp, sel, erwartet), gemessen in zip(FAELLE, ist):
    check(f"{'ziehbar ' if erwartet else 'KEIN Zug'}: {name}",
          gemessen == erwartet,
          f"controlType={ct} drag={dp} auswaehlbar={sel} -> {gemessen}")

# ── Positivkontrollen: die Probe kann ueberhaupt beides sehen ──────────────
# Ohne sie waere eine Regel, die IMMER nein sagt, "sicher" und wertlos –
# und eine, die immer ja sagt, faellt sonst nur bei den Nein-Faellen auf.
check("Positivkontrolle: es gibt gemessene JA-Faelle", any(ist))
check("Positivkontrolle: es gibt gemessene NEIN-Faelle", not all(ist))

# ── Die ControlType-Ids stimmen mit der Quelle ueberein ────────────────────
# ⚠ Eine abgetippte Id waere still falsch: 50007 statt 50008 macht aus dem
#   LEEREN Listenbereich ein ziehbares Objekt.
import re
q = QUELLE.read_text(encoding="utf-8")
for name, wert in (("ListItem", 50007), ("List", 50008), ("TreeItem", 50024),
                   ("DataItem", 50029), ("Hyperlink", 50005), ("Image", 50006),
                   ("Custom", 50025), ("Text", 50020), ("Edit", 50004)):
    m = re.search(r"public const int %s = (\d+);" % name, q)
    check(f"Id {name} = {wert} wie in der SDK-IDL",
          m is not None and int(m.group(1)) == wert,
          m.group(1) if m else "fehlt")

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
