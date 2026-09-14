#!/usr/bin/env python3
"""Gegenproben zu 1.0.5: Update-Neustart und Dialog-Platzierung (2026-09-14).

Jede Probe dreht GENAU EINE Zusage zurueck. Eine Gegenprobe, die nicht beisst,
ist ein Testmangel - kein Beweis.

⚠ DER HARNESS SICHERT JEDE DATEI, DIE ANGEFASST WIRD - auch `Vorgaben.cs`, die
der WAECHTER selbst beschreibt (er ruft `paket_bauen`). Am 2026-09-11 hat genau
diese Auslassung eine Sabotage stehen lassen, und der naechste Lauf meldete
einen FAIL, den es im Code nicht gab.
"""
import atexit
import hashlib
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path("/home/bender/ai/projekte/jarvis")
ABL = pathlib.Path.home() / ".gegen-am-layout"
MARKE = ABL / "LAUF"

DATEIEN = [
    "ai-mouse/src/AiMouse/Program.cs",
    "ai-mouse/src/AiMouse/Ui/SettingsWindow.cs",
    "ai-mouse/src/AiMouse/Localization/Texte.cs",
    "ai-mouse/src/AiMouse/AiMouse.csproj",
    "ai-mouse/src/AiMouse/Configuration/Vorgaben.cs",
    "tests/test_ai_mouse.py",
]


def sichern():
    ABL.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck(still=False):
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)
    if not still:
        for rel in DATEIEN:
            a = hashlib.md5((ABL / rel.replace("/", "__")).read_bytes()).hexdigest()
            b = hashlib.md5((ROOT / rel).read_bytes()).hexdigest()
            if a != b:
                print("  ⚠ NICHT wiederhergestellt: " + rel)


def ende():
    zurueck(still=True)
    if MARKE.exists():
        MARKE.unlink()


def lies(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def ersetze(rel, alt, neu, anzahl=1):
    s = lies(rel)
    assert s.count(alt) >= anzahl, "Anker fehlt in %s: %r" % (rel, alt[:60])
    (ROOT / rel).write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


def waechter():
    """(fails, bilanz_da) - gemessen wird die BILANZZEILE, nicht nur der Code.

    Ein Lauf, der ohne Bilanz abbricht, ist von 'nicht gelaufen' nicht zu
    unterscheiden.
    """
    p = subprocess.run([sys.executable, "tests/test_ai_mouse.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"^(\d+) OK, (\d+) FAIL$", p.stdout, re.M)
    return (int(m.group(2)), True) if m else (-1, False)


PROBEN = []


def probe(name):
    def deko(fn):
        PROBEN.append((name, fn))
        return fn
    return deko


PROG = "ai-mouse/src/AiMouse/Program.cs"
SET = "ai-mouse/src/AiMouse/Ui/SettingsWindow.cs"


# ── a) Der Update-Neustart ────────────────────────────────────────────────
@probe("DER GEMELDETE FALL: nur ReleaseMutex, kein Dispose")
def _():
    ersetze(PROG, "            instanceLock.Dispose();\n            instanceLock = null;\n", "")


@probe("Dispose erst NACH dem Einwechseln (wirkungslos)")
def _():
    s = lies(PROG)
    s = s.replace("            instanceLock.Dispose();\n            instanceLock = null;\n", "", 1)
    s = s.replace("            if (Aktualisierung.BeimStartEinwechseln())",
                  "            instanceLock.Dispose();\n"
                  "            if (Aktualisierung.BeimStartEinwechseln())", 1)
    (ROOT / PROG).write_text(s, encoding="utf-8")


@probe("die Sperre wird nach einem Fehlschlag nicht zurueckgeholt")
def _():
    ersetze(PROG,
            "            instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out isOnlyInstance);",
            "")


@probe("`using var` zurueck (kann die Neubelegung nicht abbilden)")
def _():
    ersetze(PROG,
            "        Mutex? instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out bool isOnlyInstance);",
            "        using var instanceLock = new Mutex(initiallyOwned: true, SingleInstanceName, out bool isOnlyInstance);")


@probe("kein Dispose im finally")
def _():
    ersetze(PROG, "            instanceLock?.Dispose();", "")


# ── b) Die Platzierung im Dialog ──────────────────────────────────────────
@probe("DER GEMELDETE FALL: automatische Platzierung zurueck")
def _():
    s = lies(SET)
    s = s.replace("        layout.Controls.Add(label, 0, zeile);\n"
                  "        layout.Controls.Add(editor, 1, zeile);",
                  "        layout.Controls.Add(label);\n"
                  "        layout.Controls.Add(editor);", 1)
    assert "layout.Controls.Add(label);" in s, "Sabotage verfehlt"
    (ROOT / SET).write_text(s, encoding="utf-8")


@probe("kein Spaltensprung fuer captionlose Zeilen")
def _():
    ersetze(SET, "            layout.SetColumnSpan(editor, 2);", "")


@probe("RowCount wird nicht mitgefuehrt")
def _():
    ersetze(SET, "        layout.RowCount = zeile + 1;", "")


@probe("die Zeilennummer wird geraten statt gezaehlt")
def _():
    ersetze(SET, "        int zeile = layout.RowStyles.Count;",
            "        int zeile = 0;")


@probe("die Trennlinie ist wieder zu breit (bricht die Zeile um)")
def _():
    ersetze(SET, "            Width = 220,", "            Width = 300,")


@probe("der Loeschknopf traegt wieder den Zustandstext")
def _():
    ersetze(SET, "_hotkeyLoeschen.Text = Texte.HotkeyLoeschen;",
            "_hotkeyLoeschen.Text = Texte.HotkeyKeine;")


@probe("Version nicht hochgezaehlt")
def _():
    ersetze("ai-mouse/src/AiMouse/AiMouse.csproj",
            "<Version>1.0.5</Version>", "<Version>1.0.4</Version>")


@probe("KOMPLETTER ALTSTAND (Program.cs + SettingsWindow.cs)")
def _():
    for rel in (PROG, SET):
        alt = subprocess.run(["git", "show", "HEAD:" + rel], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
        (ROOT / rel).write_text(alt, encoding="utf-8")


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs - nehme ihn zurueck.")
        zurueck(still=True)

    # REGEL: was eine Probe anfasst, muss gesichert sein.
    quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
    genannt = {d for d in re.findall(r'"([\w/.-]+\.(?:cs|csproj|py))"', quelle)
               if (ROOT / d).exists()}
    fehlend = genannt - set(DATEIEN)
    if fehlend:
        print("⚠ NICHT GESICHERT: " + ", ".join(sorted(fehlend)))
        sys.exit(2)

    sichern()
    atexit.register(ende)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))

    basis, da = waechter()
    if not da or basis != 0:
        print("⚠ BASIS NICHT GRUEN (%s FAIL) - ohne gruene Basis ist keine "
              "Gegenprobe deutbar." % basis)
        sys.exit(2)
    print("Basis gruen (%d Proben)\n" % len(PROBEN))

    stumm = []
    for name, fn in PROBEN:
        zurueck(still=True)
        try:
            fn()
        except AssertionError as e:
            print("  ⚠ SABOTAGE VERFEHLT: %s - %s" % (name, e))
            stumm.append(name + " (verfehlt)")
            continue
        fails, bilanz = waechter()
        if not bilanz:
            print("  ABBRUCH ohne Bilanz: " + name)
            stumm.append(name + " (ohne Bilanz)")
        elif fails == 0:
            print("  STUMM   " + name)
            stumm.append(name)
        else:
            print("  beisst  %3d FAIL  %s" % (fails, name))

    zurueck()
    print("\n%d von %d Proben beissen." % (len(PROBEN) - len(stumm), len(PROBEN)))
    if stumm:
        print("STUMM: " + "; ".join(stumm))
    sys.exit(1 if stumm else 0)


if __name__ == "__main__":
    main()
