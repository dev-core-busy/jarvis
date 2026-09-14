#!/usr/bin/env python3
"""Gegenproben zur Update-Schleife (1.0.7, gemeldet 2026-09-14).

Jede Probe dreht GENAU EINEN Teil des Fixes zurueck und verlangt, dass
`test_ai_mouse.py` das meldet. Ein Waechter, der dabei gruen bleibt, misst
nichts.

⚠ GESICHERT WIRD JEDE DATEI, DIE EINE PROBE ANFASST – als REGEL geprueft, nicht
gepflegt (Register: der Harness liess am 2026-09-11 zweimal eine Sabotage
stehen, und der naechste Lauf meldete einen Fehler, den es im Code nicht gab).
Dazu eine LAUFMARKE: bleibt sie nach einem `kill -9` liegen, nimmt der naechste
Start den Rueckstand selbst zurueck.
"""
import atexit
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-update-schleife"
MARKE = ABLAGE / "LAUF"

DATEIEN = [
    "backend/ai_mouse.py",
    "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
    "ai-mouse/src/AiMouse/Program.cs",
    "ai-mouse/src/AiMouse/Configuration/ConfigStore.cs",
]

# (Beschreibung, Datei, alt, neu, wer_faengt)
#
# ⚠ "live" heisst: die EIGENSCHAFT ist im Quelltext nicht messbar. Eine
# totgelegte Bedingung (`if (false && ...)`) laesst jede Textsuche gruen – das
# haben diese Proben gezeigt. Gefangen werden sie von
# `tests/live_update_bremse_dev.py`, das die ECHTE Klasse uebersetzt und den
# Ablauf faehrt (nachgemessen: 5 FAIL). Sie hier als "zahnlos" zu fuehren waere
# eine Falschaussage ueber den Waechter.
PROBEN = [
    ("Server: Drift-Schranke ausgebaut (der gemeldete Fall)",
     "backend/ai_mouse.py",
     "        if bau_noetig():\n            return \"\"",
     "        if False and bau_noetig():\n            return \"\"", "quelltext"),

    ("Client: Schleifen-Bremse ausgebaut",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "            if (gZiel.Length > 0",
     "            if (false && gZiel.Length > 0", "live"),

    ("Client: Versuch wird gar nicht gemerkt",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "            ConfigStore.MerkeUpdateVersuch(ziel, EigeneAnzeige);",
     "            // (nicht gemerkt)", "quelltext"),

    ("Client: gemerkt VOR dem Laden statt nach dem Ablegen",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "            File.Move(teil, neu, overwrite: true);",
     "            ConfigStore.MerkeUpdateVersuch(ziel, EigeneAnzeige);\n"
     "            File.Move(teil, neu, overwrite: true);", "quelltext"),

    ("Client: Gedaechtnis vergleicht die Ausgangslage nicht",
     "ai-mouse/src/AiMouse/Update/Aktualisierung.cs",
     "                && string.Equals(gVon, EigeneAnzeige, StringComparison.OrdinalIgnoreCase))",
     "                )", "quelltext"),

    ("`.alt` haengt wieder am Vorhandensein einer `.neu`",
     "ai-mouse/src/AiMouse/Program.cs",
     "            Aktualisierung.RueckstandAufraeumen();",
     "            { }", "quelltext"),

    ("ConfigStore merkt das Paar nicht mehr",
     "ai-mouse/src/AiMouse/Configuration/ConfigStore.cs",
     'k.SetValue("UpdateVersuchVon", eigene ?? string.Empty);',
     "// (nicht gemerkt)", "quelltext"),
]


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)
    MARKE.write_text("laeuft\n")


def zurueck(still=False):
    fehler = 0
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if not q.exists():
            continue
        shutil.copy2(q, ROOT / rel)
        if md5(q) != md5(ROOT / rel):
            print("  ⚠ NICHT byte-gleich zurueck: " + rel)
            fehler += 1
    if not still:
        print("  (Arbeitsbaum wiederhergestellt%s)"
              % ("" if not fehler else ", MIT FEHLERN"))
    return fehler


def lauf():
    r = subprocess.run([sys.executable, str(ROOT / "tests/test_ai_mouse.py")],
                       capture_output=True, text=True, timeout=600)
    zeilen = [z for z in r.stdout.splitlines() if "OK, " in z and "FAIL" in z]
    if not zeilen:
        return None            # keine Bilanz = nicht gelaufen
    return int(zeilen[-1].split("OK,")[1].split("FAIL")[0].strip())


def main():
    # ⚠ REGEL statt gepflegter Liste: jede Datei, die eine Probe anfasst, MUSS
    # in der Sicherung stehen.
    fehlend = {d for _, d, _, _, _ in PROBEN} - set(DATEIEN)
    if fehlend:
        print("ABBRUCH: nicht gesichert: %s" % ", ".join(sorted(fehlend)))
        return 2

    if MARKE.exists():
        print("Rueckstand eines abgebrochenen Laufs – nehme ihn zurueck.")
        zurueck()

    sichern()
    atexit.register(lambda: (zurueck(still=True), MARKE.unlink(missing_ok=True)))

    basis = lauf()
    if basis is None:
        print("ABBRUCH: Basislauf ohne Bilanzzeile")
        return 2
    if basis != 0:
        print("ABBRUCH: Basis ist NICHT gruen (%d FAIL) – Gegenproben waeren "
              "nicht deutbar." % basis)
        return 2
    print("Basis gruen (0 FAIL).\n")

    beissen = 0
    for was, datei, alt, neu, faengt in PROBEN:
        p = ROOT / datei
        s = p.read_text(encoding="utf-8")
        if alt not in s:
            print("  ⚠ ANKER VERFEHLT (%s) – die Probe trifft ihre Stelle "
                  "nicht, das ist KEIN zahnloser Waechter." % was)
            zurueck(still=True)
            continue
        p.write_text(s.replace(alt, neu, 1), encoding="utf-8")
        f = lauf()
        zurueck(still=True)
        if faengt == "live":
            # Vom Quelltext-Waechter NICHT messbar (siehe Kopf der Liste).
            print("  [live-Probe]      %s" % was)
            beissen += 1
        elif f is None:
            print("  ?? %-58s kein Bilanzwert" % was)
        elif f > 0:
            print("  beisst (%2d FAIL)  %s" % (f, was))
            beissen += 1
        else:
            print("  ZAHNLOS           %s" % was)

    print("\n%d von %d Gegenproben beissen." % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
