#!/usr/bin/env python3
"""Live auf DEV: `Markdown.ZuZeilen` wird WIRKLICH AUSGEFUEHRT.

Der Waechter in `test_ai_mouse.py` prueft, dass die Regel ZEICHENGLEICH zu der
im Browser-Plugin ist. Das ist die halbe Zusage – die andere Haelfte ist, dass
.NET diese Regel genauso ANWENDET wie JavaScript. Lookbehind, Gierigkeit und
die Schleife ueber den Rest sind in beiden Sprachen zu vergleichen, nicht zu
vermuten: deshalb laeuft hier die ECHTE Klasse gegen dieselben Faelle, mit
denen der Plugin-Parser belegt ist.

⚠ Der Text ist FREMDTEXT (Modellantwort ueber einen Bildschirmausschnitt).
   Die Faelle sind entsprechend gewaehlt: nicht "was sieht huebsch aus",
   sondern "was darf NICHT als Auszeichnung gelesen werden".

Aufruf auf DEV: python3 tests/live_markdown_dev.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/opt/jarvis") if Path("/opt/jarvis/ai-mouse").is_dir() else \
    Path(__file__).resolve().parent.parent
# ⚠ MEHRERE ORTE, nicht einer: auf DEV liegt das SDK unter `vendor/`, auf der
#   Arbeitsmaschine im PATH. Ein Waechter, der nur auf einem Rechner laeuft,
#   ist ein halber (Register, dieselbe Lehre wie bei der jsdom-Suche).
def _dotnet() -> Path | None:
    import shutil as _sh
    for kandidat in (Path("/opt/jarvis/vendor/dotnet/dotnet"),
                     ROOT / "vendor" / "dotnet" / "dotnet"):
        if kandidat.exists():
            return kandidat
    gefunden = _sh.which("dotnet")
    return Path(gefunden) if gefunden else None


DOTNET = _dotnet()
QUELLE = ROOT / "ai-mouse" / "src" / "AiMouse" / "Ui" / "Markdown.cs"
PLUGIN = ROOT / "browser-addon" / "popup.js"

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


if DOTNET is None:
    # Exit 2: "konnte nicht laufen" darf nie wie "bestanden" aussehen.
    print("ABBRUCH: kein dotnet gefunden (vendor/dotnet oder PATH)")
    sys.exit(2)
if not QUELLE.exists():
    print(f"ABBRUCH: {QUELLE} fehlt")
    sys.exit(2)

# ── Die Faelle ──────────────────────────────────────────────────────────────
# Erwartung als Liste von Zeilen, jede Zeile eine Liste von [Text, fett].
FAELLE = [
    # (1) Der Regelfall.
    ("**Fehler:** Datei fehlt.",
     [[["Fehler:", True], [" Datei fehlt.", False]]]),

    # (2) Mehrere Stellen in einer Zeile – die Schleife ueber den Rest.
    ("a **eins** b **zwei** c",
     [[["a ", False], ["eins", True], [" b ", False], ["zwei", True], [" c", False]]]),

    # (3) ⚠ DIE WICHTIGSTEN: das darf KEINE Auszeichnung sein. Ohne die
    #     `\S`-Waechter wuerde hier fremder Text verstuemmelt.
    ("2 * 3 * 4 = 24", [[["2 * 3 * 4 = 24", False]]]),
    ("Muster *.txt und *.log", [[["Muster *.txt und *.log", False]]]),
    ("** allein **", [[["** allein **", False]]]),
    ("ein * Sternchen", [[["ein * Sternchen", False]]]),

    # (4) Nicht geschlossen – bleibt stehen, statt den Rest zu schlucken.
    ("**offen ohne Ende", [[["**offen ohne Ende", False]]]),

    # (5) Zeilen bleiben Zeilen, auch leere (Absaetze der Antwort).
    ("eins\n\n**zwei**",
     [[["eins", False]], [], [["zwei", True]]]),

    # (6) Windows-Zeilenenden ergeben keinen Lauf mit nacktem \r.
    ("a\r\n**b**", [[["a", False]], [["b", True]]]),

    # (7) Nicht gierig: die erste schliessende Klammer gewinnt.
    ("**a** und **b**",
     [[["a", True], [" und ", False], ["b", True]]]),

    # (8) Leer und nur Umbruch.
    ("", [[]]),
    ("\n", [[], []]),

    # (9) Sternchen INNERHALB der Auszeichnung.
    ("**a*b**", [[["a*b", True]]]),

    # (10) ⚠ MEINE ERWARTUNG WAR HIER FALSCH, nicht der Code: `***x***` ergibt
    #      fett `*x` und ein uebriges `*` – die Gruppe ist non-greedy, das
    #      erste schliessende `**` steht hinter dem `x`. Das PLUGIN liefert
    #      exakt dasselbe (unten gemessen, nicht angenommen). Der Fall bleibt
    #      drin, weil er das Verhalten festhaelt, das beide Seiten teilen.
    ("***x***", [[["*x", True], ["*", False]]]),
]

with tempfile.TemporaryDirectory(prefix="mdprobe-") as tmp:
    tmp = Path(tmp)
    (tmp / "probe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        "<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>"
        "<Nullable>enable</Nullable><ImplicitUsings>enable</ImplicitUsings>"
        "<AssemblyName>probe</AssemblyName><RootNamespace>probe</RootNamespace>"
        "<InvariantGlobalization>true</InvariantGlobalization>"
        "</PropertyGroup></Project>", encoding="utf-8")

    # ⚠ DIE ECHTE DATEI, unveraendert kopiert. Ein Nachbau wuerde die eigene
    #    Annahme pruefen, nicht den ausgelieferten Code.
    shutil.copy2(QUELLE, tmp / "Markdown.cs")

    (tmp / "Program.cs").write_text('''
using System.Text.Json;
using AiMouse.Ui;

string roh = Console.In.ReadToEnd();
var faelle = JsonSerializer.Deserialize<List<string>>(roh)!;
var raus = new List<List<List<object>>>();
foreach (string f in faelle)
{
    var zeilen = new List<List<object>>();
    foreach (var zeile in Markdown.ZuZeilen(f))
    {
        var l = new List<object>();
        foreach (var lauf in zeile) { l.Add(new object[] { lauf.Text, lauf.Fett }); }
        zeilen.Add(l);
    }
    raus.Add(zeilen);
}
Console.Write(JsonSerializer.Serialize(raus));
''', encoding="utf-8")

    bau = subprocess.run([str(DOTNET), "build", "-v", "q", "--nologo", str(tmp / "probe.csproj")],
                         capture_output=True, text=True, cwd=tmp,
                         env={"DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                              "DOTNET_NOLOGO": "1", "HOME": str(tmp),
                              "PATH": "/usr/bin:/bin"})
    if bau.returncode != 0:
        print("ABBRUCH: die Probe uebersetzt nicht\n" + (bau.stdout or "") + (bau.stderr or ""))
        sys.exit(2)

    dll = next(tmp.glob("bin/**/probe.dll"), None)
    if dll is None:
        print("ABBRUCH: probe.dll nicht gefunden")
        sys.exit(2)

    lauf = subprocess.run([str(DOTNET), str(dll)],
                          input=json.dumps([f for f, _ in FAELLE]),
                          capture_output=True, text=True,
                          env={"DOTNET_CLI_TELEMETRY_OPTOUT": "1", "HOME": str(tmp),
                               "PATH": "/usr/bin:/bin"})
    if lauf.returncode != 0:
        print("ABBRUCH: die Probe laeuft nicht\n" + (lauf.stdout or "") + (lauf.stderr or ""))
        sys.exit(2)

    ergebnis = json.loads(lauf.stdout)

print("── Der Parser, wirklich ausgefuehrt ──")
for (text, erwartet), ist in zip(FAELLE, ergebnis):
    check(f"{text!r}", ist == erwartet, f"ist={ist}")

# ── Positivkontrolle: die Probe kann ueberhaupt einen Unterschied sehen ─────
# Ohne sie waere ein Parser, der IMMER dasselbe liefert, unauffaellig.
check("Positivkontrolle: nicht alle Ergebnisse sind gleich",
      len({json.dumps(e) for e in ergebnis}) > 5)

# ── DIE EIGENTLICHE DRIFT-SCHRANKE: .NET gegen den ECHTEN Plugin-Parser ────
#
# ⚠ „ZEICHENGLEICHE REGEL" IST NUR DIE HALBE ZUSAGE. Ob .NET und JavaScript
#    dieselbe Regel auch gleich ANWENDEN (Lookbehind, Gierigkeit, Schleife
#    ueber den Rest), entscheidet die jeweilige Laufzeit – das gehoert
#    gemessen. Diese Probe hat damit sofort geliefert, wofuer sie gebaut ist:
#    meine abgetippte Erwartung fuer `***x***` war falsch, und der Vergleich
#    hat gezeigt, dass BEIDE Seiten dasselbe tun.
if PLUGIN.exists() and shutil.which("node"):
    import re as _re
    _m = _re.search(r"const _FETT_RE = /(.+?)/;", PLUGIN.read_text(encoding="utf-8"))
    _cs = _re.search(r'new\(@"(.+?)",', QUELLE.read_text(encoding="utf-8"))
    check("die Regel ist zeichengleich zum Browser-Plugin",
          bool(_m and _cs and _m.group(1) == _cs.group(1)),
          f"js={_m.group(1) if _m else None} cs={_cs.group(1) if _cs else None}")

    # Der ECHTE `zuBloecken`-Rumpf aus popup.js, geschnitten statt nachgebaut.
    _quelle = PLUGIN.read_text(encoding="utf-8")
    _i = _quelle.find("function zuBloecken(")
    _j = _quelle.find("\n}", _i)
    _rumpf = _quelle[_i:_j + 2] if 0 <= _i < _j else ""
    check("der Plugin-Parser ist schneidbar", bool(_rumpf) and "bloecke" in _rumpf)

    _js = f"""
const _FETT_RE = /{_m.group(1) if _m else ''}/;
{_rumpf}
const faelle = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(faelle.map(f =>
  zuBloecken(f).map(z => z.map(l => [l.t, l.fett])))));
"""
    with tempfile.TemporaryDirectory(prefix="mdjs-") as _t:
        _d = Path(_t) / "p.js"
        _d.write_text(_js, encoding="utf-8")
        _r = subprocess.run(["node", str(_d)], input=json.dumps([f for f, _ in FAELLE]),
                            capture_output=True, text=True)
    if _r.returncode != 0:
        check("der Plugin-Parser laeuft", False, (_r.stderr or "")[:120])
    else:
        _jsergebnis = json.loads(_r.stdout)
        # ⚠ VERGLICHEN WIRD OHNE `\r` – UND DAS IST EIN BEFUND, KEIN KNIFF.
        #    Der Plugin-Parser splittet nur an `\n`; ein `\r` bleibt als Text
        #    im Lauf stehen. In HTML ist das unsichtbar, in einer RichTextBox
        #    NICHT: dort ist `\r` selbst ein Umbruch, aus einer Windows-Zeile
        #    wuerde also eine LEERZEILE. Deshalb normiert die .NET-Fassung
        #    zusaetzlich – eine bewusste Anpassung an das Zielmedium, die der
        #    Vergleich hier ausdruecklich ausnimmt statt sie zu verdecken.
        _ohne_cr = [i for i, (f, _) in enumerate(FAELLE) if "\r" not in f]
        _abw = [FAELLE[i][0] for i in _ohne_cr
                if json.dumps(_jsergebnis[i]) != json.dumps(ergebnis[i])]
        check("⚠ .NET und das Plugin deuten JEDEN Fall ohne \\r gleich (%d Faelle)"
              % len(_ohne_cr), not _abw, "abweichend: " + repr(_abw[:4]))
        check("Positivkontrolle: der Vergleich laesst Faelle uebrig",
              len(_ohne_cr) >= len(FAELLE) - 1)

        # Und die Ausnahme wird BENANNT, nicht uebergangen: genau hier
        # unterscheiden sich die beiden – nachgewiesen, nicht behauptet.
        _cr = [i for i, (f, _) in enumerate(FAELLE) if "\r" in f]
        check("bei `\\r\\n` weichen sie nachweislich ab (das Plugin traegt das \\r mit)",
              bool(_cr) and any(json.dumps(_jsergebnis[i]) != json.dumps(ergebnis[i])
                                for i in _cr),
              "js=%s cs=%s" % (_jsergebnis[_cr[0]] if _cr else None,
                               ergebnis[_cr[0]] if _cr else None))
        check("Positivkontrolle: der Plugin-Lauf hat wirklich gearbeitet",
              len({json.dumps(e) for e in _jsergebnis}) > 5)

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
