#!/usr/bin/env python3
"""Die ECHTE Versionsvergleichs-Regel des Clients – AUSGEFUEHRT.

⚠ WARUM DAS NICHT IN DEN PYTHON-WAECHTER PASST: `Aktualisierung.IstNeuer` ist
C#, und ein Quelltext-Waechter kann nur pruefen, DASS `Version.TryParse`
vorkommt – nicht, WAS die Regel entscheidet. Genau dort sitzt aber die
teuerste Falle: `Version` setzt fehlende Teile auf **-1**, damit ist "1.0.0"
KLEINER als "1.0.0.0". Ohne Normierung loest also jeder Start ein Update aus,
das nichts aendert – eine Endlosschleife, die niemand sieht, weil sie still
laeuft. Dieselbe Aufteilung wie bei `LinkZiel` und `ZiehbarRegel`.

⚠ VERAENDERT NICHTS: uebersetzt eine Wegwerf-Konsolenanwendung in /tmp, fuehrt
sie aus, raeumt ab. Die Klasse wird im ORIGINAL uebernommen (nur die
WinForms-freien Teile), nicht nachgebaut – ein Nachbau prueft sich selbst.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/opt/jarvis")
QUELLE = ROOT / "ai-mouse" / "src" / "AiMouse" / "Update" / "Aktualisierung.cs"
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


roh = QUELLE.read_text(encoding="utf-8")

# Nur die reinen Rechenteile herausziehen – `BeimStartEinwechseln` und
# `PruefenUndHolenAsync` fassen Dateien an und gehoeren nicht in eine Probe.
def block(signatur: str) -> str:
    i = roh.find(signatur)
    if i < 0:
        return ""

    # ⚠ AUSDRUCKSKOERPER ZUERST: `Normiert` ist `=> new(...);` und hat GAR
    # KEINE geschweifte Klammer. Die Klammersuche darunter fand deshalb die
    # naechste METHODE und zog sie mit – der Uebersetzer meldete dann
    # `EigenerPfad`/`File`/`NeuSuffix` als unbekannt, also Fehler in einer
    # Funktion, die im Original voellig richtig ist. Zweiter Fall dieser
    # Klasse nach `GestenTasteAus` (2026-09-10).
    kl = roh.find("{", i)
    sk = roh.find(";", i)
    if sk >= 0 and (kl < 0 or sk < kl):
        return roh[i:sk + 1]

    j = kl
    tiefe, k = 0, j
    while k < len(roh):
        if roh[k] == "{":
            tiefe += 1
        elif roh[k] == "}":
            tiefe -= 1
            if tiefe == 0:
                # Ein Ausdruckskoerper endet mit `;` – das MUSS mit, sonst
                # meldet der Uebersetzer "; erwartet" in einer Zeile, die im
                # Original voellig richtig ist (Register, 2026-09-10).
                ende = k + 1
                if ende < len(roh) and roh[ende] == ";":
                    ende += 1
                return roh[i:ende]
        k += 1
    return ""


istneuer = block("public static bool IstNeuer")
normiert = block("private static Version Normiert")
if not istneuer or not normiert:
    print("ABBRUCH: Regel nicht geschnitten (umbenannt?).")
    sys.exit(2)

# Positivkontrolle des Schnitts: ohne sie prueft die Probe womoeglich einen
# leeren oder halben Rumpf und ist trivial gruen.
check("der Schnitt enthaelt die Normierung",
      "Math.Max" in normiert and "TryParse" in istneuer)
# ⚠ UND NICHTS SONST: ein zu weiter Schnitt prueft fremden Code (Register).
check("der Schnitt zieht keine fremde Methode mit",
      "EigenerPfad" not in normiert and "File.Exists" not in normiert
      and "File.Exists" not in istneuer,
      normiert[-80:])

FAELLE = [
    # (server, eigene, soll_neuer, warum)
    ("1.0.1", "1.0.0.0", True, "echte neue Fassung"),
    ("1.0.0", "1.0.0.0", False, "⚠ DIE FALLE: gleich, nur anders geschrieben"),
    ("1.0.0.0", "1.0.0.0", False, "identisch"),
    ("0.10.0", "0.9.0.0", True, "⚠ ZAHLEN, nicht Text: 10 > 9"),
    ("0.9.0", "0.10.0.0", False, "Gegenrichtung dazu"),
    ("2.0", "1.9.9.9", True, "zweiteilig, hoeher"),
    ("1.0.0", "1.0.1.0", False, "Server ist AELTER – kein Rueckschritt"),
    ("", "1.0.0.0", False, "unbekannt = nichts tun"),
    ("   ", "1.0.0.0", False, "Leerraum = nichts tun"),
    ("kaputt", "1.0.0.0", False, "unlesbar = nichts tun"),
    ("1.0.0-beta", "1.0.0.0", False, "nicht parsebar = nichts tun"),
    (" 1.0.2 ", "1.0.0.0", True, "Leerraum drumherum wird getrimmt"),
]

arbeit = Path(tempfile.mkdtemp(prefix="aimouse_ver_"))
try:
    (arbeit / "p.csproj").write_text(
        "<Project Sdk=\"Microsoft.NET.Sdk\"><PropertyGroup>"
        "<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>"
        "<Nullable>enable</Nullable><AssemblyName>ver</AssemblyName>"
        "</PropertyGroup></Project>", encoding="utf-8")

    faelle_cs = "\n".join(
        '        Pruefe(%s, "%s", "%s", %s);'
        % ("null" if s is None else '"%s"' % s, e, w.replace('"', "'"),
           "true" if soll else "false")
        for s, e, soll, w in FAELLE)

    (arbeit / "Program.cs").write_text(
        "using System;\n\n"
        "internal static class Regel\n{\n"
        + istneuer + "\n\n" + normiert + "\n}\n\n"
        # ⚠ OHNE INTERPOLATION UND OHNE VERSCHACHTELTE ANFUEHRUNGSZEICHEN:
        # der erste Anlauf schrieb `$"… {server ?? \"(null)\"} …"` und der
        # Uebersetzer brach mit fuenf Syntaxfehlern ab. Python-Escapes, die in
        # C#-Escapes muenden, sind hier die falsche Ebene – schlichte
        # Konkatenation ist lesbar und geht nicht schief.
        "internal static class P\n{\n"
        "    static int Fehler = 0;\n"
        "    static void Pruefe(string? server, string eigene, string warum, bool soll)\n"
        "    {\n"
        "        bool ist = Regel.IstNeuer(server, Version.Parse(eigene));\n"
        "        string s = server == null ? \"(null)\" : \"[\" + server + \"]\";\n"
        "        Console.WriteLine((ist == soll ? \"OK   \" : \"FAIL \")\n"
        "            + \"server=\" + s + \" eigene=\" + eigene\n"
        "            + \" -> \" + ist + \" (soll \" + soll + \")  \" + warum);\n"
        "        if (ist != soll) { Fehler++; }\n"
        "    }\n"
        "    static int Main()\n    {\n"
        + faelle_cs + "\n"
        "        Console.WriteLine($\"__FEHLER__={Fehler}\");\n"
        "        return 0;\n    }\n}\n", encoding="utf-8")

    # ⚠ DEN SDK-PFAD NICHT RATEN: `dotnet` liegt auf DEV NICHT im PATH (es gibt
    # kein apt-Paket auf Debian 13), sondern unter `vendor/dotnet` – genau so
    # sucht es auch `deploy/ai_mouse_build.sh`. Ein geratenes `dotnet` bricht
    # ab, und ein Aufruf, der nicht stattgefunden hat, ist kein Messwert.
    eigen = ROOT / "vendor" / "dotnet"
    exe = eigen / "dotnet"
    if not exe.is_file():
        exe = Path(shutil.which("dotnet") or "")
    if not exe or not exe.is_file():
        print("ABBRUCH: kein .NET-SDK gefunden (vendor/dotnet, PATH).")
        sys.exit(2)

    p = subprocess.run(
        [str(exe), "run", "--project", str(arbeit / "p.csproj"), "-c", "Release",
         "--nologo", "-v", "q"],
        capture_output=True, text=True, timeout=540,
        cwd=str(arbeit), env={"HOME": str(arbeit),
                              "PATH": "%s:/usr/bin:/bin" % exe.parent,
                              "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                              "DOTNET_NOLOGO": "1",
                              "DOTNET_ROOT": str(exe.parent)})
    aus = (p.stdout or "") + (p.stderr or "")
    for zeile in aus.splitlines():
        if zeile.startswith(("OK   ", "FAIL ")):
            print("  " + zeile)
    m = re.search(r"__FEHLER__=(\d+)", aus)
    if not m:
        print("ABBRUCH: die Probe lief nicht (kein Ergebnis).")
        print(aus[-1500:])
        sys.exit(2)
    check("alle %d Versionsfaelle wie erwartet" % len(FAELLE),
          m.group(1) == "0", "%s Abweichungen" % m.group(1))
finally:
    shutil.rmtree(arbeit, ignore_errors=True)

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 62, _ok, _fail, "=" * 62))
sys.exit(1 if _fail else 0)
