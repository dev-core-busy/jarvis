#!/usr/bin/env python3
"""Gegenproben zu Abschnitt 24 (Version sichtbar, 2026-09-11).

⚠ SICHERUNG AUF PLATTE + atexit + SIGTERM: ein per Timeout GEKILLTER Lauf laesst
   den Arbeitsbaum sonst sabotiert zurueck, und der naechste Testlauf meldet
   einen Fehler, den es nicht gibt (Register, mehrfach bezahlt).
⚠ Gemessen wird EXIT-CODE UND BILANZZEILE, nie das Zaehlen von FAIL-Zeilen:
   ein Lauf, der abbricht, hat keine Bilanz und ist von "bestanden" sonst nicht
   zu unterscheiden.
⚠ `Vorgaben.cs` gehoert in die Sicherung, obwohl keine Probe sie anfasst: der
   GEPRUEFTE Lauf schreibt sie selbst (er ruft `paket_bauen`).
"""
import atexit
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SICHER = pathlib.Path.home() / ".gegen-am-version"

DATEIEN = [
    "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
    "ai-mouse/src/AiMouse/Ui/Marken.cs",
    "ai-mouse/src/AiMouse/Localization/Texte.cs",
    "ai-mouse/src/AiMouse/AiMouse.csproj",
    "ai-mouse/src/AiMouse/Configuration/Vorgaben.cs",
    "frontend/ai_mouse.html",
    "frontend/js/ai_mouse.js",
    "frontend/js/i18n.js",
    "frontend/css/jira_addon.css",
    "tests/live_texte_dev.py",
    # ⚠ DIE TESTDATEI SELBST – eine Probe saboteirt sie ("Waechter prueft wieder
    #   die Schreibweise"). Sie fehlte hier, also blieb genau diese Sabotage
    #   liegen: der naechste Lauf meldete 1 FAIL, den es im Code nicht gab.
    #   Die Regel unten faengt das kuenftig ab, damit es nicht an dieser Liste
    #   haengt.
    "tests/test_ai_mouse.py",
]


def sichern():
    SICHER.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = SICHER / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)   # IMMER erneuern, nie "nur wenn fehlt"


def zurueck():
    if not SICHER.is_dir():
        return
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


MARKE = SICHER / "LAEUFT"


def abraeumen():
    """⚠ DIE SICHERUNG WIRD BEIM GEORDNETEN ENDE ENTFERNT.

    Ohne das stellt der NAECHSTE Lauf beim Start einen veralteten Stand her und
    macht Arbeit zunichte, die zwischendurch an diesen Dateien passiert ist –
    hier am 2026-09-11 bezahlt: der zweite Lauf hat die gerade gehaertete
    Fassung von `test_ai_mouse.py` ueberschrieben, und die Basis war danach rot
    aus einem Grund, der nicht im Code lag. Nach einem `kill -9` bleibt die
    Marke liegen, und dann soll das Zuruecknehmen genau greifen.
    """
    zurueck()
    if MARKE.is_file():
        MARKE.unlink()
    shutil.rmtree(SICHER, ignore_errors=True)


atexit.register(abraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(2))

# Rueckstand eines ABGESCHOSSENEN Laufs zuruecknehmen – erkennbar an der Marke.
if MARKE.is_file():
    print("⚠ Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck.")
    zurueck()
sichern()
MARKE.write_text("laeuft\n", encoding="utf-8")


def lauf():
    """(exit, hat_bilanz, fails)"""
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "test_ai_mouse.py")],
                       capture_output=True, text=True, timeout=600)
    aus = p.stdout + p.stderr
    m = re.search(r"(\d+) OK, (\d+) FAIL", aus)
    return p.returncode, m is not None, (int(m.group(2)) if m else -1)


def probe(name, rel, alt, neu, nr=1):
    """`nr` = das wievielte Vorkommen getroffen wird (1-basiert).

    ⚠ Ein Anker, der mehrfach vorkommt, ist ohne diese Angabe eine Probe, die
      ihr Ziel verfehlen KANN – dieselbe Falle wie eine Sabotage, die den
      Kommentar statt des Aufrufs trifft.
    """
    d = ROOT / rel
    s = d.read_text(encoding="utf-8")
    n = s.count(alt)
    if n < nr:
        print(f"  ⚠ {name}: ANKER NICHT GEFUNDEN ({n}x, gesucht #{nr})")
        return False
    if nr == 1 and n != 1:
        print(f"  ⚠ {name}: ANKER NICHT EINDEUTIG ({n}x) – Probe verfehlt ihr Ziel")
        return False
    vor, _, rest = s.partition(alt) if nr == 1 else (
        alt.join(s.split(alt)[:nr]), alt, alt.join(s.split(alt)[nr:]))
    d.write_text(vor + neu + rest, encoding="utf-8")
    try:
        code, bilanz, fails = lauf()
    finally:
        zurueck()
    if not bilanz:
        print(f"  ⚠ {name}: KEINE BILANZ (Abbruch) – nicht deutbar")
        return False
    ok = code != 0 and fails > 0
    print(f"  {'✓' if ok else '✗'} {name}: {fails} FAIL")
    return ok


print("Basis …", end=" ", flush=True)
c, b, f = lauf()
if not (c == 0 and b and f == 0):
    print(f"NICHT GRUEN (exit={c}, bilanz={b}, fails={f}) – ohne gruene Basis "
          f"ist keine Gegenprobe deutbar.")
    sys.exit(2)
print("gruen\n")

PROBEN = [
    ("Anzeige vierteilig (Eigene.ToString)",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     """            Version v = Eigene;
            return v.Build >= 0
                ? $"{v.Major}.{v.Minor}.{v.Build}"
                : $"{v.Major}.{v.Minor}";""",
     "            return Eigene.ToString();"),
    ("Build -1 ungeprueft",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "v.Build >= 0", "v.Build >= -99"),
    ("Kopf nennt die Version nicht",
     "ai-mouse/src/AiMouse/Ui/Marken.cs",
     "Text = Texte.Version + \" \" + Aktualisierung.EigeneAnzeige,",
     "Text = string.Empty,"),
    ("Kopf waechst nicht mit der Schrift",
     "ai-mouse/src/AiMouse/Ui/Marken.cs",
     "AutoSizeMode = AutoSizeMode.GrowAndShrink,", ""),
    ("Version bricht nicht um (Zoom)",
     "ai-mouse/src/AiMouse/Ui/Marken.cs",
     "WrapContents = true,", "WrapContents = false,"),
    ("hartes Literal statt Texte",
     "ai-mouse/src/AiMouse/Ui/Marken.cs",
     "Texte.Version", "\"Version\""),
    ("DE=EN-Ausnahme nicht eingetragen",
     "tests/live_texte_dev.py",
     '    "Version",       # dasselbe Wort in beiden Sprachen\n', ""),
    ("Version nicht hochgezaehlt",
     "ai-mouse/src/AiMouse/AiMouse.csproj",
     "<Version>1.0.2</Version>", "<Version>1.0.1</Version>"),
    ("Kachel ohne Platz fuer die Version",
     "frontend/ai_mouse.html",
     '<span id="am-version" class="ja-note"></span>', ""),
    ("Zahl abgetippt statt aus health",
     "frontend/ai_mouse.html",
     '<span id="am-version" class="ja-note"></span>',
     '<span id="am-version" class="ja-note">klient_version 1.0.2</span>'),
    ("Kachel fuellt sie nicht",
     "frontend/js/ai_mouse.js",
     "vs.textContent = v ? (t('aimouse.version', 'Version') + ' ' + v) : '';",
     "vs.title = v;"),
    ("ohne Angabe wird geraten",
     "frontend/js/ai_mouse.js",
     "var v = (_health.klient_version || '').trim();",
     "var v = (_health.klient_version || '1.0.0').trim();"),
    ("innerHTML statt textContent",
     "frontend/js/ai_mouse.js",
     "vs.textContent = v ?", "vs.innerHTML = v ?"),
    ("i18n nur deutsch (EN-Eintrag weg)",
     "frontend/js/i18n.js",
     "        'aimouse.version':       'Version',\n", "", 2),
    ("Hinweisklasse wieder undefiniert",
     "frontend/css/jira_addon.css",
     ".ja-note { color: var(--text-secondary); font-size: 13px; }", ""),
    ("Hinweis im zu blassen Ton",
     "frontend/css/jira_addon.css",
     ".ja-note { color: var(--text-secondary);", ".ja-note { color: var(--text-muted);"),
    ("Version steht oben statt mittig",
     "frontend/css/jira_addon.css",
     "#am-version { align-self: center; }", ""),
    ("Waechter prueft wieder die Schreibweise",
     "tests/test_ai_mouse.py",
     r'''          re.search(r"public\s+static\s+\w+\s+Kopf\s*\(", mk) is not None)''',
     '''          "public static Label Kopf" in mk)'''),
]

_fehlt = sorted({p[1] for p in PROBEN} - set(DATEIEN))
if _fehlt:
    print("⚠ ABBRUCH: diese Dateien werden saboteirt, aber nicht gesichert –\n"
          "  ein Lauf wuerde sie veraendert zuruecklassen:\n   " + "\n   ".join(_fehlt))
    sys.exit(2)

gut = 0
for p in PROBEN:
    if probe(*p):
        gut += 1

print(f"\n{gut}/{len(PROBEN)} Gegenproben beissen")
sys.exit(0 if gut == len(PROBEN) else 1)
