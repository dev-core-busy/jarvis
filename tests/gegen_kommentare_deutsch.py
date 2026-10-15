#!/usr/bin/env python3
"""Gegenprobe zu ``test_kommentare_deutsch.py``: beisst der Waechter wirklich?

Je Probe wird eine Wegwerfdatei mit EINEM englischen Kommentar in der
jeweiligen Sprache angelegt; der Waechter muss mit Exit 1 antworten und die
Datei nennen. Die Gegenrichtung (deutscher Kommentar, englisches Zitat,
englisch in einer Zeichenkette) darf NICHT melden - sonst waere "beisst" auch
erfuellt, wenn der Waechter wahllos jede Datei meldet.

Vorgehen:
  1. Basislauf muss GRUEN sein - ohne gruene Basis ist kein Ergebnis deutbar.
  2. Probe anlegen, Waechter laufen lassen, Probe entfernen.
  3. Abschlusslauf wieder gruen.

Die Proben sind NEUE Dateien (der Waechter liest auch unverfolgte, nicht
ignorierte Dateien); am Bestand wird nichts veraendert. Eine Laufmarke faengt
den Abbruch mitten in einer Probe ab.

NICHT in einem Sammellauf ueber ``tests/*.py`` mitlaufen lassen - diese Datei
legt Dateien im Arbeitsbaum an (Register).

Exit 0 = der Waechter beisst, 1 = er beisst nicht, 2 = konnte nicht laufen.
"""
import os
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WAECHTER = WURZEL / "tests" / "test_kommentare_deutsch.py"
MARKE = Path.home() / ".gegen_kommentare_deutsch.laeuft"

# (Name, Pfad, Inhalt) - je ein englischer Kommentar in der Syntax der Sprache.
PROBEN = [
    ("Python #-Kommentar", "tests/zz_kommentar_probe.tmp.py",
     "x = 1\n# Check if the value is larger than the limit\n"),
    ("Python-Docstring", "tests/zz_kommentar_probe.tmp.py",
     'def f():\n    """Returns the number of items in the list."""\n'
     "    return 0\n"),
    ("JS //-Kommentar", "frontend/js/zz_kommentar_probe.tmp.js",
     "// Load the settings from the server when the page opens\nvar a = 1;\n"),
    ("JS-Blockkommentar", "frontend/js/zz_kommentar_probe.tmp.js",
     "/**\n * This module renders the list of users.\n */\nvar a = 1;\n"),
    ("Go-Kommentar", "windows-app-go/zz_kommentar_probe.tmp.go",
     "package main\n\n// sameDay returns true if both are on the same day.\n"
     "func x() {}\n"),
    ("Shell-Kommentar", "deploy/zz_kommentar_probe.tmp.sh",
     "#!/bin/bash\n# Stop the service before the files are copied\necho ok\n"),
    ("CSS-Kommentar", "frontend/css/zz_kommentar_probe.tmp.css",
     "/* Buttons in the header should not wrap */\n.x { color: var(--a); }\n"),
    ("Kotlin-Kommentar", "android/zz_kommentar_probe.tmp.kt",
     "// Show the dialog only if the user is logged in\nval a = 1\n"),
    # Ein englischer Satz neben einem Zitat - das Zitat darf ihn nicht
    # "entschuldigen".
    ("Englisch neben Zitat", "tests/zz_kommentar_probe.tmp.py",
     "# The server answers \"Fehler\" when the token is missing\nx = 1\n"),
]

GEGENRICHTUNG = [
    ("deutscher Kommentar", "tests/zz_kommentar_probe.tmp.py",
     "# Prueft, ob der Wert die Grenze ueberschreitet\nx = 1\n"),
    ("englisches Zitat in deutschem Satz", "tests/zz_kommentar_probe.tmp.py",
     "# EWS lehnt das ab (\"EWS does not support filtering on field 'id'\")\n"
     "x = 1\n"),
    ("mehrzeiliges Zitat", "frontend/js/zz_kommentar_probe.tmp.js",
     "// Quelle: Microsoft Learn, \"Sideload Office Add-ins on Windows from a\n"
     "// network share\" und das Gegenstueck fuer das Web.\nvar a = 1;\n"),
    ("Englisch in Zeichenkette", "frontend/js/zz_kommentar_probe.tmp.js",
     "var t = '// Check if the value is in the list of all items';\n"),
    ("Fachbegriff im deutschen Satz", "deploy/zz_kommentar_probe.tmp.sh",
     "#!/bin/bash\n# Fallback: Default-Queue anlegen, wenn keine da ist\n"),
]

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def waechter_lauf():
    umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    erg = subprocess.run([sys.executable, str(WAECHTER)], cwd=WURZEL,
                         capture_output=True, text=True, timeout=600,
                         env=umgebung)
    return erg.returncode, erg.stdout + erg.stderr


def aufraeumen():
    for _n, rel, _i in PROBEN + GEGENRICHTUNG:
        (WURZEL / rel).unlink(missing_ok=True)


if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden - wird entfernt.")
    aufraeumen()
    MARKE.unlink(missing_ok=True)

if not WAECHTER.is_file():
    print("ABBRUCH (Exit 2): Waechter nicht gefunden: %s" % WAECHTER)
    sys.exit(2)

aufraeumen()
rc, ausgabe = waechter_lauf()
if rc != 0:
    print("ABBRUCH (Exit 2): Basislauf ist NICHT gruen (Exit %d)." % rc)
    print(ausgabe[-2000:])
    sys.exit(2)
print("Basislauf gruen.\n")

MARKE.write_text("laeuft", encoding="utf-8")
try:
    for name, rel, inhalt in PROBEN:
        pfad = WURZEL / rel
        if not pfad.parent.is_dir():
            print("ABBRUCH (Exit 2): Zielverzeichnis fehlt: %s" % pfad.parent)
            sys.exit(2)
        pfad.write_text(inhalt, encoding="utf-8")
        rc, ausgabe = waechter_lauf()
        pruefe(rc == 1, "%s -> gemeldet (Exit 1)" % name, "Exit %d" % rc)
        pruefe(Path(rel).name in ausgabe, "%s -> Fundstelle genannt" % name)
        aufraeumen()

    for name, rel, inhalt in GEGENRICHTUNG:
        (WURZEL / rel).write_text(inhalt, encoding="utf-8")
        rc, ausgabe = waechter_lauf()
        pruefe(rc == 0, "%s -> KEIN Fund" % name,
               "Exit %d: %s" % (rc, ausgabe[-400:]))
        aufraeumen()
finally:
    aufraeumen()
    MARKE.unlink(missing_ok=True)

rc, _ = waechter_lauf()
pruefe(rc == 0, "Abschlusslauf wieder gruen - kein Rueckstand", "Exit %d" % rc)
pruefe(not any((WURZEL / r).exists() for _n, r, _i in PROBEN + GEGENRICHTUNG),
       "alle Wegwerfdateien entfernt")

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
