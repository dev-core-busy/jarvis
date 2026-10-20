#!/usr/bin/env python3
"""Waechter: Shell-Skripte im Repo sind ausfuehrbar (Modus 100755 im INDEX).

WARUM
-----
Am 2026-10-20 scheiterte auf DEV der letzte Schritt des `c+p`-Ablaufs:

    $ deploy/dev_reset.sh --pruefen
    bash: deploy/dev_reset.sh: Keine Berechtigung        (Exit 126)

Im Arbeitsbaum des Betreibers hatte die Datei das Ausfuehrbit, im INDEX nicht -
und ein Server bekommt seinen Stand aus dem Index (`git reset --hard`, frischer
Klon, Docker-Build). Betroffen waren alle 15 `deploy/*.sh` und zehn weitere,
darunter BEIDE `gradlew`: wer `./gradlew assembleDebug` tippt, wie es
`GalaxyWatch8App/README.md` ansagt, bekommt dieselbe Meldung.

Das ist die unangenehme Sorte Fehler: auf dem Rechner, der ihn verursacht,
funktioniert alles, denn dort ist das Bit im Dateisystem gesetzt. `git status`
zeigt nichts, weil der Arbeitsbaum zum Index passt - der Modus wird nur
sichtbar, wenn man ausdruecklich `git ls-files -s` fragt. Und `chmod` behebt es
NICHT: das aendert den Arbeitsbaum, nicht den Index. Dafuer braucht es

    git update-index --chmod=+x <datei>

WARUM NUR SHELL-SHEBANGS
------------------------
Gemessen am Bestand: 586 verzeichnete Dateien beginnen mit `#!`, 578 davon ohne
Ausfuehrbit. Eine Regel "Shebang, also ausfuehrbar" haette damit 578 Befunde
gemeldet - und ein Waechter mit dieser Trefferquote wird beim ersten Lauf
abgeschaltet (Register: "Eine falsche Sonde ist schlimmer als keine"; derselbe
Fehler hat `test_keine_echtwerte` einmal 1508 Fehlalarme gekostet).

Die 551 Python- und Node-Dateien sind keine Fehler. Die Hauskonvention ruft sie
ueber den Interpreter auf (`python3 tests/test_<name>.py`, `node tests/x.js`);
ihr Shebang sagt, WOMIT die Datei zu lesen ist, nicht dass sie ein Kommando
waere. Gemessen, nicht angenommen: im ganzen Repo gibt es keine Stelle, die eine
`.py` ohne vorangestellten Interpreter startet (gesucht in .sh/.md/.yml/
Dockerfile/.service - die Treffer waren ausnahmslos Erwaehnungen in Backticks).

Ein SHELL-Skript dagegen ist genau dann brauchbar, wenn es startbar ist. Die
Regel haengt deshalb an der Shebang-KLASSE, nicht an der Dateiendung - eine
Endung kann fehlen (`gradlew`) und eine `.conf` kann einen Shebang tragen, ohne
ein Kommando zu sein: `deploy/security/nftables-jarvis-egress.conf` beginnt mit
`#!/usr/sbin/nft -f` und wird per `nft -f <datei>` GELADEN (README.md:249). Sie
fehlt hier nicht als Ausnahme, sondern faellt durch die Klasse heraus - eine
Ausnahmeliste, die man pflegen muss, waere der schlechtere Bau.

Exit 0 = alle ausfuehrbar, 1 = Fund, 2 = konnte nicht laufen.
"""
import re
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent

# Shebangs, die ein Kommando ankuendigen. Bewusst eine Positivliste: eine
# Negativliste muesste jeden Interpreter kennen, der je dazukommt.
RE_SHELL = re.compile(r"^#!\s*(?:/usr/bin/env\s+)?/?(?:[\w/]*/)?(sh|bash|dash|zsh|ksh)\b")

# Ausnahmen: Pfadmuster -> Grund. Ein Eintrag ohne passende Datei ist selbst ein
# Fund, sonst verrottet die Liste still (gleiche Bauform wie in
# test_keine_echtwerte.py). Derzeit leer - die Shebang-Klasse genuegt.
AUSNAHMEN = {}

AUSFUEHRBAR = "100755"

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def index_dateien():
    """[(modus, pfad)] aller verzeichneten Dateien, oder Abbruch mit Exit 2."""
    try:
        roh = subprocess.run(["git", "ls-files", "-s"], cwd=WURZEL,
                             capture_output=True, text=True, check=True,
                             timeout=120).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        print("ABBRUCH (Exit 2): 'git ls-files -s' nicht ausfuehrbar -> %s" % exc)
        sys.exit(2)
    eintraege = []
    for zeile in roh.splitlines():
        # "<modus> <hash> <stufe>\t<pfad>" - der Pfad kann Leerzeichen tragen,
        # deshalb am Tabulator trennen und nicht per split().
        if "\t" not in zeile:
            continue
        kopf, pfad = zeile.split("\t", 1)
        teile = kopf.split()
        if len(teile) == 3:
            eintraege.append((teile[0], pfad))
    return eintraege


def shebang(pfad: Path):
    """Erste Zeile, falls die Datei mit '#!' beginnt - sonst None.

    Liest nur den Anfang: eine 65-MB-Datei (tika-app.jar) gehoert nicht in den
    Speicher, nur weil sie im Index steht. Binaer -> None.
    """
    try:
        with pfad.open("rb") as f:
            kopf = f.read(200)
    except OSError:
        return None
    if not kopf.startswith(b"#!"):
        return None
    try:
        return kopf.split(b"\n", 1)[0].decode("utf-8")
    except UnicodeDecodeError:
        return None


def ausgenommen(rel: str):
    for muster, grund in AUSNAHMEN.items():
        if re.search(muster, rel):
            return muster, grund
    return None, None


# ════════════════════════════════════════════════════════════════════════════
# POSITIVKONTROLLE - vor den inhaltlichen Pruefungen.
# Ohne sie waere ein gruener Lauf bedeutungslos: ein Waechter, dessen
# Shebang-Erkennung nichts findet, meldet auf jedem Bestand "alles sauber".
# ════════════════════════════════════════════════════════════════════════════
_TRIFFT = ["#!/bin/bash", "#!/bin/sh", "#!/usr/bin/env bash",
           "#!/usr/bin/env sh", "#!/bin/bash -eu", "#! /bin/bash",
           "#!/usr/local/bin/bash", "#!/bin/zsh"]
_TRIFFT_NICHT = ["#!/usr/bin/env python3", "#!/usr/bin/env node",
                 "#!/usr/sbin/nft -f", "#!/opt/jarvis/venv/bin/python",
                 "#!/usr/bin/perl", "# kein Shebang, nur ein Kommentar",
                 "#!/usr/bin/env pwsh"]

_falsch_negativ = [s for s in _TRIFFT if not RE_SHELL.match(s)]
_falsch_positiv = [s for s in _TRIFFT_NICHT if RE_SHELL.match(s)]
if _falsch_negativ or _falsch_positiv:
    print("ABBRUCH (Exit 2): die Shebang-Erkennung ist unbrauchbar.")
    if _falsch_negativ:
        print("  nicht erkannt, muesste aber: %r" % _falsch_negativ)
    if _falsch_positiv:
        print("  erkannt, darf aber nicht: %r" % _falsch_positiv)
    print("  Ohne funktionierende Erkennung ist jeder gruene Lauf bedeutungslos.")
    sys.exit(2)

dateien = index_dateien()
if len(dateien) < 100:
    print("ABBRUCH (Exit 2): nur %d verzeichnete Dateien - kein vollstaendiger Baum."
          % len(dateien))
    sys.exit(2)

# Zweite Kontrolle: der Lauf muss ueberhaupt Shell-Skripte GEFUNDEN haben.
# Ein Tippfehler im Suchweg oder eine kaputte Shebang-Lesung macht den Waechter
# sonst dauerhaft gruen, ohne eine Zeile Ausgabe (Register: ein Waechter, der
# nicht laeuft, verdeckt echte Befunde).
skripte = []
for modus, rel in dateien:
    pfad = WURZEL / rel
    if not pfad.is_file():
        continue
    zeile = shebang(pfad)
    if zeile and RE_SHELL.match(zeile):
        skripte.append((modus, rel))

if len(skripte) < 20:
    print("ABBRUCH (Exit 2): nur %d Shell-Skripte gefunden - erwartet sind"
          " dutzende." % len(skripte))
    print("  Entweder ist die Shebang-Lesung kaputt oder der Baum unvollstaendig.")
    sys.exit(2)

print("Positivkontrolle: Erkennung trennt %d Shell- von %d Fremd-Shebangs, und"
      "\nder Lauf hat %d Shell-Skripte in %d verzeichneten Dateien gefunden.\n"
      % (len(_TRIFFT), len(_TRIFFT_NICHT), len(skripte), len(dateien)))

# ── Die Regel ───────────────────────────────────────────────────────────────
benutzte_ausnahmen = set()
funde = []
for modus, rel in skripte:
    muster, _grund = ausgenommen(rel)
    if muster:
        benutzte_ausnahmen.add(muster)
        continue
    if modus != AUSFUEHRBAR:
        funde.append((rel, modus))

pruefe(not funde,
       "jedes Shell-Skript im Index ist ausfuehrbar (%s)" % AUSFUEHRBAR,
       "%d von %d nicht" % (len(funde), len(skripte)) if funde else "")

verwaist = sorted(set(AUSNAHMEN) - benutzte_ausnahmen)
pruefe(not verwaist, "jede Ausnahme deckt noch mindestens eine Datei",
       "verwaist: %s" % verwaist if verwaist else "")

if funde:
    print("\nNicht ausfuehrbar im Index:")
    for rel, modus in sorted(funde):
        print("  %s  %s" % (modus, rel))
    print("\nBeheben (chmod allein genuegt NICHT - es aendert nur den Arbeitsbaum):")
    print("  git update-index --chmod=+x \\")
    for rel, _m in sorted(funde):
        print("      %s \\" % rel)
    print("")

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
