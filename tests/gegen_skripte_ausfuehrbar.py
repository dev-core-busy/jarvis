#!/usr/bin/env python3
"""Gegenprobe zu ``test_skripte_ausfuehrbar.py``: beisst der Waechter wirklich?

Zwei Sorten Proben, sauber getrennt - die Unterscheidung ist der Punkt:

  PRODUKT   Das x-Bit einer Datei im Index zurueckdrehen. Erwartet: Exit 1
            (ein Fund) und der Dateiname in der Ausgabe.
  WAECHTER  Die Shebang-Erkennung blenden. Erwartet: Exit 2 und ABBRUCH -
            nicht Exit 1. "Ich kann nicht messen" darf nicht in derselben
            Sprache sprechen wie "ich habe etwas gefunden", sonst sieht ein
            kaputter Pruefstand wie ein Befund aus (Register).

Der Index wird dabei wirklich veraendert. Deshalb:
  1. Basislauf muss GRUEN sein - ohne gruene Basis ist kein Ergebnis deutbar.
  2. Der Vorzustand (Modus je Datei) wird VOR der Probe gelesen und im finally
     zurueckgeschrieben; eine Laufmarke faengt den Abbruch mitten in der Probe
     ab, damit der naechste Start den Rueckstand zuerst wegraeumt.
  3. Nach dem Zuruecknehmen wird der Modus NACHGESEHEN, nicht angenommen.

NICHT in einem Sammellauf ueber ``tests/*.py`` mitlaufen lassen - diese Datei
veraendert den Index (Register).

Exit 0 = der Waechter beisst, 1 = er beisst nicht, 2 = konnte nicht laufen.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WAECHTER = WURZEL / "tests" / "test_skripte_ausfuehrbar.py"
MARKE = Path.home() / ".gegen_skripte_ausfuehrbar.laeuft"

# Opfer der Produkt-Probe: das Skript, dessen fehlendes Bit den Vorfall
# ausgeloest hat (2026-10-20, letzter Schritt des c+p auf DEV).
OPFER = "deploy/dev_reset.sh"

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=WURZEL, capture_output=True,
                          text=True, timeout=120)


def modus(rel):
    """Modus einer Datei im Index, oder None."""
    erg = git("ls-files", "-s", "--", rel)
    for zeile in erg.stdout.splitlines():
        if "\t" in zeile:
            return zeile.split()[0]
    return None


def lauf(datei=None):
    """(exit, ausgabe) des Waechters. Ohne Bytecode, damit eine .pyc aus einer
    frueheren Probe nicht den naechsten Lauf bestimmt (Register)."""
    umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    erg = subprocess.run([sys.executable, str(datei or WAECHTER)], cwd=WURZEL,
                         capture_output=True, text=True, timeout=600,
                         env=umgebung)
    return erg.returncode, erg.stdout + erg.stderr


def bit_setzen(rel, an):
    git("update-index", "--chmod=+x" if an else "--chmod=-x", "--", rel)


# ── Rueckstand eines abgeschossenen Laufs zuerst wegraeumen ─────────────────
if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden - Bit wird gesetzt.")
    bit_setzen(OPFER, True)
    MARKE.unlink(missing_ok=True)

if not WAECHTER.is_file():
    print("ABBRUCH (Exit 2): Waechter nicht gefunden: %s" % WAECHTER)
    sys.exit(2)

vorzustand = modus(OPFER)
if vorzustand != "100755":
    print("ABBRUCH (Exit 2): %s steht im Index auf %r, erwartet 100755."
          % (OPFER, vorzustand))
    print("  Die Probe wuerde sonst einen Zustand herstellen, der schon da ist.")
    sys.exit(2)

# ── Basislauf ───────────────────────────────────────────────────────────────
rc, _ausgabe = lauf()
if rc == 2:
    print("ABBRUCH (Exit 2): der Waechter konnte selbst nicht laufen.")
    print(_ausgabe[-1200:])
    sys.exit(2)
if rc != 0:
    print("ABBRUCH (Exit 2): Basislauf ist NICHT gruen (Exit %d)." % rc)
    print("Ohne gruene Basis zaehlt jede Probe eine Fehlschlagsmeldung zu viel.")
    print(_ausgabe[-1500:])
    sys.exit(2)
print("Basislauf gruen - der Waechter meldet auf dem sauberen Index nichts.\n")

MARKE.write_text("laeuft", encoding="utf-8")
try:
    # ── PRODUKT: das Bit faellt weg ─────────────────────────────────────────
    bit_setzen(OPFER, False)
    jetzt = modus(OPFER)
    if jetzt != "100644":
        print("  FAIL Probe konnte das Bit nicht entfernen (Modus %r)" % jetzt)
        _fail += 1
    else:
        rc, ausgabe = lauf()
        pruefe(rc == 1, "Bit weg -> der Waechter meldet den Fund (Exit 1)",
               "Exit %d" % rc)
        pruefe(OPFER in ausgabe, "Bit weg -> und nennt die Datei namentlich")
        pruefe("update-index --chmod=+x" in ausgabe,
               "Bit weg -> der Grund nennt den WEG zur Behebung",
               "ohne den Hinweis sucht der Leser bei chmod")
    bit_setzen(OPFER, True)
    pruefe(modus(OPFER) == "100755", "Bit nachgesehen zurueckgesetzt")

    # ── PRODUKT, Gegenrichtung: ein Fremd-Shebang darf NICHT melden ─────────
    # Ohne diese Messung waere "beisst" auch dann erfuellt, wenn der Waechter
    # jede Datei ohne x-Bit meldet - also 578 Python- und Node-Dateien.
    #
    # Die Referenzdatei wird GESUCHT, nicht genannt: ein fester Name ist eine
    # Zeitbombe (die Datei kann umziehen, das Bit bekommen oder - wie beim
    # ersten Lauf dieser Probe - noch gar nicht im Index stehen und deshalb
    # ueberhaupt keinen Modus haben).
    opfer_py = None
    for zeile in git("ls-files", "-s").stdout.splitlines():
        if "\t" not in zeile:
            continue
        kopf, rel = zeile.split("\t", 1)
        if kopf.split()[0] != "100644" or not rel.endswith(".py"):
            continue
        try:
            if (WURZEL / rel).open("rb").read(64).startswith(b"#!"):
                opfer_py = rel
                break
        except OSError:
            continue
    if not opfer_py:
        print("  FAIL kein Python-Skript mit Shebang und 100644 im Index -")
        print("       die Gegenrichtung ist damit nicht messbar.")
        _fail += 1
    else:
        pruefe(True, "Referenz fuer die Gegenrichtung gefunden: %s" % opfer_py)
        rc, ausgabe = lauf()
        pruefe(rc == 0, "Python ohne x-Bit loest KEINEN Fund aus", "Exit %d" % rc)
        pruefe(opfer_py not in ausgabe,
               "und wird in der Ausgabe nicht genannt")

    # ── WAECHTER: die Shebang-Erkennung erblindet -> Exit 2, nicht 1 ────────
    quelle = WAECHTER.read_text(encoding="utf-8")
    anker = 'RE_SHELL = re.compile(r"^#!\\s*(?:/usr/bin/env\\s+)?/?(?:[\\w/]*/)?(sh|bash|dash|zsh|ksh)\\b")'
    if quelle.count(anker) != 1:
        print("  FAIL Anker der Waechter-Probe %dx gefunden, erwartet 1x"
              % quelle.count(anker))
        _fail += 1
    else:
        blind = 'RE_SHELL = re.compile(r"^#!NIEMALS")'
        kopie = WAECHTER.with_suffix(".tmp_blind.py")
        kopie.write_text(quelle.replace(anker, blind), encoding="utf-8")
        try:
            rc, ausgabe = lauf(kopie)
            pruefe(rc == 2, "blinde Erkennung -> ABBRUCH mit Exit 2 (nicht 1)",
                   "Exit %d - ein kaputter Pruefstand spricht die Sprache "
                   "eines Befundes" % rc)
            pruefe("ABBRUCH" in ausgabe,
                   "blinde Erkennung -> der Grund steht in der Ausgabe")
        finally:
            kopie.unlink(missing_ok=True)
finally:
    bit_setzen(OPFER, True)
    MARKE.unlink(missing_ok=True)

# ── Nach allen Proben ───────────────────────────────────────────────────────
pruefe(modus(OPFER) == "100755", "am Ende steht das Bit wieder (im Index)")
pruefe(not list(WURZEL.glob("tests/*.tmp_blind.py")),
       "keine Wegwerfkopie im Arbeitsbaum")
rc, _ = lauf()
pruefe(rc == 0, "Abschlusslauf wieder gruen - kein Rueckstand", "Exit %d" % rc)

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
