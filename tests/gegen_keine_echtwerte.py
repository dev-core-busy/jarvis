#!/usr/bin/env python3
"""Gegenprobe zu ``test_keine_echtwerte.py``: beisst der Waechter wirklich?

Ein gruener Waechter beweist nichts, solange niemand gemessen hat, dass er bei
einem echten Rueckfall ROT wird. Diese Probe schleust nacheinander je einen
Echtwert in eine unverdaechtige Datei ein, laesst den Waechter laufen und
verlangt Exit 1 samt Fundstelle.

Vorgehen je Probe:
  1. Basislauf muss GRUEN sein - ohne gruene Basis ist kein Ergebnis deutbar.
  2. Datei auf Platte sichern, Probe einbauen, Waechter laufen lassen.
  3. Zuruecknehmen und die Byte-Gleichheit per md5 NACHSEHEN, nicht annehmen.

Eine Laufmarke faengt den Abbruch mitten in einer Probe ab: beim naechsten Start
wird der Rueckstand zuerst zurueckgenommen.

NICHT in einem Sammellauf ueber ``tests/*.py`` mitlaufen lassen - diese Datei
patcht den Arbeitsbaum (Register).

Exit 0 = der Waechter beisst, 1 = er beisst nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WAECHTER = WURZEL / "tests" / "test_keine_echtwerte.py"
MARKE = Path.home() / ".gegen_keine_echtwerte.laeuft"

# Unverdaechtige Zieldatei: wird vom Waechter gelesen und ist nicht ausgenommen.
ZIEL = WURZEL / "tests" / "test_keine_echtwerte_ziel.tmp.md"

# Die Echtwerte stehen NICHT im Repo (seit 2026-10-15): vorher standen sie
# hier, aus Teilen zusammengesetzt - in einem lesbaren Repo ist das kein Schutz.
# Sie kommen aus einer gitignorierten Datei; fehlt sie, kann die Gegenprobe
# nicht messen (Exit 2), und das ist etwas anderes als "beisst nicht".
PROBEN_DATEI = WURZEL / "tests" / "echtwerte_proben.local.txt"


def proben_laden():
    """(PROBEN, ORTS_ZEILE) aus der Probendatei, oder Abbruch mit Exit 2."""
    if not PROBEN_DATEI.is_file():
        print("ABBRUCH (Exit 2): Probendatei fehlt: %s" % PROBEN_DATEI)
        print("  Sie ist gitignoriert und liegt nur auf dem Rechner des Betreibers.")
        sys.exit(2)
    proben, ort = [], None
    for zeile in PROBEN_DATEI.read_text(encoding="utf-8").splitlines():
        if not zeile.strip() or zeile.startswith("#") or "\t" not in zeile:
            continue
        name, wert = zeile.split("\t", 1)
        if name == "ORT":
            ort = wert
        else:
            proben.append((name, wert))
    if not proben or not ort:
        print("ABBRUCH (Exit 2): Probendatei ohne Proben oder ohne ORT-Zeile.")
        sys.exit(2)
    return proben, ort


PROBEN, ORTS_ZEILE = proben_laden()

# Dieselbe Adresse an Orten, die BIS 2026-10-01 pauschal ausgenommen waren.
# Ohne diese Proben bliebe unbemerkt, wenn eine Ausnahme zurueckkehrt.
ORTSPROBEN = [
    ("live_-Probe",     WURZEL / "tests" / "live_zz_gegenprobe.tmp.py"),
    ("Windows-Client",  WURZEL / "windows-app-go" / "zz_gegenprobe.tmp.go"),
    ("Deploy-Werkzeug", WURZEL / "deploy" / "zz_gegenprobe.tmp.sh"),
    ("Browser-Erweiterung", WURZEL / "browser-addon" / "zz_gegenprobe.tmp.json"),
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


def md5(pfad: Path) -> str:
    return hashlib.md5(pfad.read_bytes()).hexdigest()


def waechter_lauf():
    """(exit, ausgabe). Ohne Bytecode, damit eine .pyc aus einer frueheren Probe
    nicht den naechsten Lauf bestimmt (Register)."""
    umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    erg = subprocess.run([sys.executable, str(WAECHTER)], cwd=WURZEL,
                         capture_output=True, text=True, timeout=600,
                         env=umgebung)
    return erg.returncode, erg.stdout + erg.stderr


def aufraeumen():
    ZIEL.unlink(missing_ok=True)
    for _n, pfad in ORTSPROBEN:
        pfad.unlink(missing_ok=True)


# ── Rueckstand eines abgeschossenen Laufs zuerst wegraeumen ─────────────────
if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden - wird zurueckgenommen.")
    aufraeumen()
    MARKE.unlink(missing_ok=True)

if not WAECHTER.is_file():
    print("ABBRUCH (Exit 2): Waechter nicht gefunden: %s" % WAECHTER)
    sys.exit(2)

# ── Basislauf ───────────────────────────────────────────────────────────────
aufraeumen()
rc, ausgabe = waechter_lauf()
if rc == 2:
    print("ABBRUCH (Exit 2): der Waechter konnte selbst nicht laufen.")
    print(ausgabe[-1500:])
    sys.exit(2)
if rc != 0:
    print("ABBRUCH (Exit 2): Basislauf ist NICHT gruen (Exit %d)." % rc)
    print("Ohne gruene Basis zaehlt jede Probe eine Fehlschlagsmeldung zu viel.")
    print(ausgabe[-2000:])
    sys.exit(2)
print("Basislauf gruen - der Waechter meldet auf dem sauberen Baum nichts.\n")

MARKE.write_text("laeuft", encoding="utf-8")
try:
    for name, zeile in PROBEN:
        ZIEL.write_text("# Wegwerfdatei der Gegenprobe\n\n%s\n" % zeile,
                        encoding="utf-8")
        vorher = md5(ZIEL)
        rc, ausgabe = waechter_lauf()

        pruefe(rc == 1, "%s -> der Waechter meldet den Fund (Exit 1)" % name,
               "Exit %d" % rc)
        pruefe(ZIEL.name in ausgabe,
               "%s -> und nennt die Fundstelle" % name,
               "Dateiname fehlt in der Ausgabe")
        # Die Probe darf die Datei nicht selbst veraendert haben
        pruefe(md5(ZIEL) == vorher, "%s -> die Probe blieb unveraendert" % name)
        aufraeumen()

    for name, pfad in ORTSPROBEN:
        pfad.write_text("# Wegwerfdatei der Gegenprobe\n%s\n" % ORTS_ZEILE,
                        encoding="utf-8")
        rc, ausgabe = waechter_lauf()
        pruefe(rc == 1, "Adresse in %s -> gemeldet (keine Ausnahme mehr)" % name,
               "Exit %d" % rc)
        pruefe(pfad.name in ausgabe, "%s -> Fundstelle genannt" % name)
        aufraeumen()

    # ── Gegenrichtung: ein Platzhalter darf NICHT melden ────────────────────
    # Ohne diese Messung waere "beisst" auch dann erfuellt, wenn der Waechter
    # wahllos jede Datei meldet - und damit wertlos.
    ZIEL.write_text("# Wegwerfdatei der Gegenprobe\n\n"
                    "\\\\10.0.0.10\\Freigabe, Mail m.mustermann@beispiel.de, "
                    "DN CN=X,DC=firma,DC=local, Login FIRMA\\m.mustermann\n"
                    # Versionsnummer und Dokumentationsadresse (RFC 5737)
                    "Version 1.0.2.0, DNS 192.0.2.53, root@<dev-host>\n",
                    encoding="utf-8")
    rc, ausgabe = waechter_lauf()
    pruefe(rc == 0, "Platzhalter loesen KEINEN Fund aus (sonst meldet er alles)",
           "Exit %d" % rc)
    aufraeumen()
finally:
    aufraeumen()
    MARKE.unlink(missing_ok=True)

# ── Nach allen Proben: der Baum ist wieder sauber ───────────────────────────
pruefe(not ZIEL.exists(), "die Wegwerfdatei ist entfernt")
rc, _ = waechter_lauf()
pruefe(rc == 0, "Abschlusslauf wieder gruen - kein Rueckstand im Arbeitsbaum",
       "Exit %d" % rc)

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
