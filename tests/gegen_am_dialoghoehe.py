#!/usr/bin/env python3
"""Gegenproben zu Abschnitt 26 (kein Bedienelement faellt aus dem Fenster).

Gemeldet 2026-09-14: „ich kann keine Einstellung fuer die Tastenkombination
finden". Sie war seit 1.0.3 da – nur ausserhalb eines `FixedDialog` mit fester
Hoehe und ohne Rollbalken.

⚠ SICHERUNG AUF PLATTE + atexit + SIGTERM + Laufmarke: ein per Timeout
   GEKILLTER Lauf laesst den Arbeitsbaum sonst sabotiert zurueck, und der
   naechste Testlauf meldet einen Fehler, den es nicht gibt.
⚠ Gemessen wird EXIT-CODE UND BILANZZEILE, nie das Zaehlen von FAIL-Zeilen.
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
SICHER = pathlib.Path.home() / ".gegen-am-dialoghoehe"

DATEIEN = [
    "ai-mouse/src/AiMouse/Ui/SettingsWindow.cs",
    "ai-mouse/src/AiMouse/Ui/LoginWindow.cs",
    "ai-mouse/src/AiMouse/AiMouse.csproj",
    "ai-mouse/src/AiMouse/Configuration/Vorgaben.cs",
    "tests/test_ai_mouse.py",
]


def sichern():
    SICHER.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, SICHER / rel.replace("/", "__"))


def zurueck():
    if not SICHER.is_dir():
        return
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


MARKE = SICHER / "LAEUFT"


def abraeumen():
    zurueck()
    if MARKE.is_file():
        MARKE.unlink()
    shutil.rmtree(SICHER, ignore_errors=True)


atexit.register(abraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(2))

if MARKE.is_file():
    print("⚠ Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck.")
    zurueck()
sichern()
MARKE.write_text("laeuft\n", encoding="utf-8")


def lauf():
    p = subprocess.run([sys.executable, str(ROOT / "tests" / "test_ai_mouse.py")],
                       capture_output=True, text=True, timeout=600)
    aus = p.stdout + p.stderr
    m = re.search(r"(\d+) OK, (\d+) FAIL", aus)
    return p.returncode, m is not None, (int(m.group(2)) if m else -1)


def probe(name, rel, alt, neu):
    d = ROOT / rel
    s = d.read_text(encoding="utf-8")
    n = s.count(alt)
    if n != 1:
        print(f"  ⚠ {name}: ANKER {n}x – Probe verfehlt ihr Ziel")
        return False
    d.write_text(s.replace(alt, neu), encoding="utf-8")
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

SW = "ai-mouse/src/AiMouse/Ui/SettingsWindow.cs"
LW = "ai-mouse/src/AiMouse/Ui/LoginWindow.cs"
CS = "ai-mouse/src/AiMouse/AiMouse.csproj"

PROBEN = [
    # ── Netz 2: der Rollbalken ─────────────────────────────────────────────
    ("Einstellungen ohne Rollbalken (der gemeldete Zustand)",
     SW, "            AutoScroll = true,\n        };",
         "        };"),
    ("Anmeldemaske ohne Rollbalken",
     LW, "            AutoScroll = true,\n        };",
         "        };"),

    # ── Netz 1: die gerechnete Hoehe ───────────────────────────────────────
    ("Hoehe wird nicht mehr gebunden (Aufruf raus)",
     SW, "        HoeheAnInhaltBinden(layout, kopf, buttons);", ""),
    ("Hoehe wieder aus einer festen Zahl statt aus dem Inhalt",
     SW, "layout.GetPreferredSize(new Size(ClientSize.Width, 0)).Height",
         "420"),
    ("kein Deckel auf den Bildschirm",
     SW, "int platz = Screen.FromPoint(Cursor.Position).WorkingArea.Height - 80;",
         "int platz = 100000;"),
    ("eine gescheiterte Rechnung verhindert den Dialog",
     SW, "        catch\n        {", "        catch (Exception) when (false)\n        {"),

    # ── Netz 3: der Benutzer kann nachhelfen ───────────────────────────────
    ("Fenster wieder FixedDialog",
     SW, "FormBorderStyle = FormBorderStyle.Sizable;",
         "FormBorderStyle = FormBorderStyle.FixedDialog;"),
    ("keine Mindestgroesse (unbrauchbar klein ziehbar)",
     SW, "        MinimumSize = new Size(420, 320);", ""),

    # ── Die Versionsregel ──────────────────────────────────────────────────
    ("Version gesenkt, Chronik bleibt (Arbeitsplatz bekaeme kein Update)",
     CS, "<Version>1.0.4</Version>", "<Version>1.0.3</Version>"),
    ("Version geaendert ohne Chronik-Eintrag",
     CS, "<!-- 1.0.4 (2026-09-14):", "<!-- 1.0.9 (2026-09-14):"),

    # ── Der Waechter selbst ────────────────────────────────────────────────
    ("Waechter nimmt die feste Zahl zurueck (Zeitbombe)",
     "tests/test_ai_mouse.py",
     '''check("und sie ist die juengste – die Chronik hinkt nicht hinterher",
      bool(_chronik26) and _teile26(_ver26) == max(_teile26(v) for v in _chronik26))''',
     '''check("und sie ist die juengste – die Chronik hinkt nicht hinterher",
      _ver26 == "1.0.3")'''),
]

_fehlt = sorted({p[1] for p in PROBEN} - set(DATEIEN))
if _fehlt:
    print("⚠ ABBRUCH: diese Dateien werden sabotiert, aber nicht gesichert –\n"
          "  ein Lauf wuerde sie veraendert zuruecklassen:\n   " + "\n   ".join(_fehlt))
    sys.exit(2)

gut = 0
for p in PROBEN:
    if probe(*p):
        gut += 1

print(f"\n{gut}/{len(PROBEN)} Gegenproben beissen")
sys.exit(0 if gut == len(PROBEN) else 1)
