#!/usr/bin/env python3
"""Sammellauf der Waechter fuer die CI (BSI M6: "CI mit Tests").

Die Waechter bleiben eigenstaendige Skripte (kein pytest, kein Framework) –
dieses Skript startet nur jedes `tests/test_*.py` und `tests/test_*.js` als
eigenen Prozess und wertet den Exit-Code nach der Hauskonvention aus:

    0  bestanden
    2  konnte nicht laufen (Werkzeug/Dienst fehlt)
    sonst  Fehlschlag (Exit 1, Absturz, Zeitdeckel)

Der EIGENE Exit-Code dieses Skripts folgt derselben Konvention:
    0  alles gelaufen und gruen
    1  mindestens ein Waechter rot (Befunde sind die staerkere Aussage)
    2  nichts rot, aber mindestens einer konnte nicht laufen

⚠ Exit 2 war bis zum 2026-10-11 KEIN Fehlschlag – "nicht gelaufen" stand nur
in der Bilanz. Das hat nicht getragen: `test_chat_bild_verlauf.py` brach seit
dem 2026-10-06 ab (chat.js rief ein neues Symbol, das im Pruefstand fehlte),
und seine Gegenprobe war sogar seit dem 2026-09-28 unbrauchbar. Beides stand
in JEDER Bilanzzeile als "1 nicht gelaufen" und wurde fuenf Tage lang nicht
gehandelt – gemeldet ist nicht bemerkt. Ein Waechter, der nicht laeuft,
verdeckt echte Befunde (Register: eine vergleichbare Reparatur brachte 470
Pruefungen und vier Produktbefunde zurueck), deshalb ist er jetzt
fail-closed. Wer einen Waechter in der CI nicht laufen lassen KANN, nimmt ihn
mit GRUND in tests/ci_ausnahmen.txt auf – das ist der vorgesehene Weg und
bleibt sichtbar, statt im Rauschen einer Bilanzzeile zu verschwinden.

`gegen_*` laufen hier NIE mit: sie patchen Dateien im Arbeitsbaum, und ein
Sammellauf mit Zeitdeckel kann sie mitten in einer Probe abschiessen – der
Rueckstand verfaelscht dann jeden folgenden Waechter (Register, 2026-09-30).
`live_*` brauchen einen laufenden Dienst und gehoeren nicht in die CI.

Ausnahmen stehen in tests/ci_ausnahmen.txt – je Zeile ein Dateiname und, nach
`#`, der GRUND. Eine Zeile ohne Grund ist ein Fehler (Exit 2): ein Geltungs-
bereich, der etwas auslaesst, braucht die Begruendung im Waechter.

Mit --ausnahmen-pruefen laufen die ausgenommenen Waechter zusaetzlich; wer davon
gruen ist, wird als "aus der Liste streichen" gemeldet (kein Fehlschlag) – sonst
wird die Liste nur laenger und nie kuerzer.

REIHENFOLGE (2026-11-22): die LAENGSTEN Waechter starten zuerst, nach den
zuletzt gemessenen Laufzeiten (``JARVIS_CI_DAUERN``, sonst
``~/.cache/jarvis/ci_dauern.json``; unbekannte zuerst, sonst nach Namen).
Alphabetisch konnte der laengste Waechter (test_prolog_vollstaendig.js, im
Sammellauf 225 s) als einer der letzten starten - dann wartete der ganze
Lauf auf ihn, waehrend die anderen Plaetze leer standen. Die Datei steuert
NUR die Startreihenfolge, nie ein Ergebnis; fehlt oder ist sie kaputt, laeuft
alles wie vorher alphabetisch. Die Ausgabe bleibt nach Namen sortiert.

Aufruf:  python3 tests/ci_lauf.py [--parallel N] [--zeitdeckel SEK]
                                  [--ausnahmen-pruefen] [muster ...]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
TESTS = WURZEL / "tests"
AUSNAHMEN = TESTS / "ci_ausnahmen.txt"
# Laufen NACH dem parallelen Block, einzeln: sie pruefen, dass der echte
# data/-Baum waehrend ihres Laufs unveraendert bleibt (Sandkasten-Waechter) –
# parallel dazu aendert ihn ein anderer Waechter, und sie brechen mit Exit 2
# ab, obwohl sie allein gruen sind (gemessen 2026-10-06).
ALLEIN = {"test_bsi_m5.py"}
# Waechter mit EIGENEM Zeitdeckel, als VIELFACHES des globalen (nicht als
# feste Sekundenzahl - sonst wandert er nicht mit, wenn jemand --zeitdeckel
# aendert, und eine feste Zahl in einem Test ist eine Zeitbombe).
#
# test_prolog_vollstaendig.js ist ein SAMMELLAUF IM SAMMELLAUF: es startet
# jeden der ~86 betroffenen Pruefstaende als eigenen Prozess. Es bleibt damit
# strukturell langsamer als ein einzelner Waechter, auch nachdem das Starten
# nebenlaeufig geworden ist (tests/lib/prolog_fanout.js).
#
# Verlauf, alles gemessen: seriell in der CI 286,6 s (durch), 300,1 s und
# 305,3 s (gerissen bzw. nur durch diesen Faktor gerettet) bei 300 s Deckel;
# lokal seriell 365-409 s, nebenlaeufig 116 s - Faktor 3,1.
#
# Der Faktor steht deshalb auf 2, nicht mehr auf 4: 4 waere nach der
# Parallelisierung keine Schranke mehr, sondern ein Versteck - ein kuenftiger
# dreifacher Rueckschritt (116 s -> 350 s) bliebe darunter unbemerkt. 2 laesst
# dem Sammellauf seine Sonderstellung und meldet eine Verdreifachung.
ZEITDECKEL_FAKTOR = {"test_prolog_vollstaendig.js": 2}


def dauern_datei() -> Path:
    """Ablage der zuletzt gemessenen Laufzeiten (ausserhalb des Arbeitsbaums)."""
    eigen = os.environ.get("JARVIS_CI_DAUERN")
    if eigen:
        return Path(eigen)
    basis = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(basis) / "jarvis" / "ci_dauern.json"


def dauern_laden() -> dict[str, float]:
    """Name -> Sekunden. Fehlt oder taugt die Datei nicht: leer (alphabetisch)."""
    try:
        roh = json.loads(dauern_datei().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(roh, dict):
        return {}
    return {k: float(v) for k, v in roh.items()
            if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)}


def dauern_speichern(neu: dict[str, float]) -> None:
    """Gemessene Zeiten in die Ablage MISCHEN (ein Teillauf loescht nichts)."""
    ziel = dauern_datei()
    alle = dauern_laden()
    alle.update({k: round(v, 1) for k, v in neu.items()})
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        tmp = ziel.with_name(ziel.name + ".%d.tmp" % os.getpid())
        tmp.write_text(json.dumps(alle, indent=0, sort_keys=True), encoding="utf-8")
        os.replace(tmp, ziel)
    except OSError as e:
        # Nur die Reihenfolge des NAECHSTEN Laufs leidet - kein Grund, diesen
        # Lauf zu kippen. Gesagt wird es trotzdem.
        print(f"   Laufzeiten nicht gespeichert ({e}) - naechster Lauf startet alphabetisch")


def reihenfolge(dateien: list[Path], dauern: dict[str, float]) -> list[Path]:
    """Laengste zuerst; unbekannte (keine Messung) noch davor; Gleichstand nach Namen."""
    return sorted(dateien, key=lambda d: (-dauern.get(d.name, float("inf")), d.name))


def ausnahmen_laden() -> dict[str, str]:
    """Dateiname -> Grund. Fehlender Grund oder unbekannte Datei: Exit 2."""
    erg: dict[str, str] = {}
    if not AUSNAHMEN.is_file():
        return erg
    for nr, zeile in enumerate(AUSNAHMEN.read_text(encoding="utf-8").splitlines(), 1):
        roh = zeile.strip()
        if not roh or roh.startswith("#"):
            continue
        name, _, grund = roh.partition("#")
        name, grund = name.strip(), grund.strip()
        if not grund:
            print(f"ABBRUCH: {AUSNAHMEN.name}:{nr} '{name}' ohne Grund")
            sys.exit(2)
        if not (TESTS / name).is_file():
            # Eine veraltete Ausnahme waere ein stilles Loch, sobald eine
            # gleichnamige Datei wiederkommt – und sie verschleiert den Bestand.
            print(f"ABBRUCH: {AUSNAHMEN.name}:{nr} '{name}' gibt es nicht (mehr)")
            sys.exit(2)
        erg[name] = grund
    return erg


def kandidaten(muster: list[str]) -> list[Path]:
    dateien = sorted(TESTS.glob("test_*.py")) + sorted(TESTS.glob("test_*.js"))
    if muster:
        dateien = [d for d in dateien if any(fnmatch.fnmatch(d.name, m) for m in muster)]
    return dateien


def deckel_fuer(name: str, global_deckel: int) -> int:
    """Zeitdeckel dieses Waechters - fuer die meisten der globale."""
    return global_deckel * ZEITDECKEL_FAKTOR.get(name, 1)


def lauf(datei: Path, zeitdeckel: int) -> tuple[str, int | None, float, str]:
    if datei.suffix == ".py":
        befehl = [sys.executable, str(datei)]
    else:
        befehl = [shutil.which("node") or "node", str(datei)]
    umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    zeitdeckel = deckel_fuer(datei.name, zeitdeckel)
    t0 = time.monotonic()
    try:
        p = subprocess.run(befehl, cwd=WURZEL, env=umgebung, capture_output=True,
                           text=True, timeout=zeitdeckel, start_new_session=True)
        rc: int | None = p.returncode
        ausgabe = (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        rc = None
        ausgabe = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes)
                   else (e.stdout or ""))
    return datei.name, rc, time.monotonic() - t0, ausgabe


# ⚠ "Error" ist ENGLISCH - die Meldungen dieses Projekts sind deutsch. Am
# 2026-11-19 hat deshalb der Auszug zu test_system_haertung.py die einzige
# Zeile verschluckt, die den Abbruch erklaert ("FEHLER: sudoers-Pruefung
# (visudo -cf) fehlgeschlagen"): sie traf kein Muster und lag ausserhalb der
# letzten 15 Zeilen. Zurueck blieb ein Exit 3 ohne Grund, und die Fehlersuche
# begann bei der Frage, welcher Zweig ueberhaupt abgebrochen hat.
_FEHLZEILE = re.compile(r"(\u2717|\u274c|\bFAIL\b|ABBRUCH|FEHLER|Traceback|Error)")

# ⚠ EINE BENANNTE LUECKE MUSS SICHTBAR SEIN, SONST IST SIE KEINE. Ein Waechter
# darf eine Zusage als "NICHT GEPRUEFT" zuruecklegen, wenn er sie auf DIESEM
# Rechner nicht messen KANN (test_system_haertung: ohne ein visudo, das die
# sudoers-Syntax des Zielsystems beurteilt; test_excel_objekte: ohne
# importierbares Modul; test_onenote_import, test_sicherheits_log_kette).
# Bis 2026-11-20 hat diese Schicht die Ausgabe GRUENER Waechter restlos
# verworfen: die Zeile entstand und kam nie an. Genau der Fehler, den der Kopf
# dieser Datei fuer Exit 2 beschreibt - gemeldet ist nicht bemerkt. Im Lauf
# 00a0e81f war deshalb nicht zu sagen, ob der Laeufer ein taugliches visudo
# fand oder zwei Zusagen stillschweigend ungemessen blieben; beides ergibt
# Exit 0.
# Gross geschrieben als Marker: "nicht geprueft" kommt auch in Pruefnamen und
# Begruendungen vor, "NICHT GEPRUEFT" ist die AUSGABEFORM aller vier Waechter.
# Der Marker darf mitten in der Zeile stehen (test_onenote_import: "– <zusage>
# (NICHT GEPRUEFT: <grund>)").
_NICHT_GEMESSEN = re.compile(r"NICHT GEPRUEFT")
_ANSI = re.compile(r"\033\[[0-9;]*m")


def _luecken(name: str, ausgabe: str) -> list[tuple[str, str]]:
    """Zusagen, die ein Waechter ausdruecklich NICHT gemessen hat (je Zeile eine).

    Eigene Funktion, damit sie pruefbar ist: in main() verborgen waere sie es
    nicht (Waechter test_bsi_m6_m7.py ruft sie direkt auf, wie _auszug)."""
    aus = []
    for z in ausgabe.splitlines():
        sauber = _ANSI.sub("", z).strip()
        if _NICHT_GEMESSEN.search(sauber):
            aus.append((name, sauber[:200]))
    return aus


def _auszug(ausgabe: str) -> str:
    """ALLE Fehlzeilen (sonst schnitt ein langer Waechter sie ab – erster
    CI-Lauf 2026-10-06: nur die Bilanz war zu sehen) plus das Ende."""
    zeilen = ausgabe.splitlines()
    fehl = [z for z in zeilen if _FEHLZEILE.search(z)][:60]
    return "\n".join(fehl + ["…"] + zeilen[-15:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parallel", type=int, default=max(2, (os.cpu_count() or 2)))
    ap.add_argument("--zeitdeckel", type=int, default=300)
    ap.add_argument("--ausnahmen-pruefen", action="store_true")
    ap.add_argument("muster", nargs="*")
    a = ap.parse_args()

    ausn = ausnahmen_laden()
    dateien = kandidaten(a.muster)
    # Positivkontrolle: ein leerer Lauf ist "konnte nicht laufen", nicht gruen
    if not dateien:
        print("ABBRUCH: keine Waechter gefunden")
        return 2
    laufen = [d for d in dateien if d.name not in ausn]
    ausgenommen = [d for d in dateien if d.name in ausn] if a.ausnahmen_pruefen else []
    print(f"{len(dateien)} Waechter, davon {len(dateien) - len(laufen)} ausgenommen; "
          f"{a.parallel} parallel, Zeitdeckel {a.zeitdeckel} s")
    # Einen eigenen Deckel SICHTBAR machen: eine stille Ausnahme sieht wie eine
    # Messung aus. Nur die nennen, die im Lauf wirklich vorkommen.
    eigen = [(d.name, deckel_fuer(d.name, a.zeitdeckel))
             for d in dateien if d.name in ZEITDECKEL_FAKTOR]
    for name, sek in eigen:
        print(f"   eigener Zeitdeckel: {name} = {sek} s "
              f"({ZEITDECKEL_FAKTOR[name]}x – Sammellauf im Sammellauf)")

    gruen: list[str] = []
    nicht_gelaufen: list[tuple[str, str]] = []
    rot: list[tuple[str, str, str]] = []
    streichen: list[str] = []
    luecken: list[tuple[str, str]] = []
    dauern = dauern_laden()
    gemessen: dict[str, float] = {}
    with cf.ThreadPoolExecutor(max_workers=a.parallel) as pool:
        # Ausgenommene und regulaere in EINER Warteschlange, laengste zuerst:
        # vorher liefen die ausgenommenen als eigener Block davor, und jeder
        # Langlaeufer darin hielt den Start aller anderen auf.
        parallel = [d for d in laufen if d.name not in ALLEIN]
        einzeln = [d for d in laufen if d.name in ALLEIN]
        zukunft = {pool.submit(lauf, d, a.zeitdeckel): d.name in ausn
                   for d in reihenfolge(parallel + ausgenommen, dauern)}
        ergebnisse = []
        for f in cf.as_completed(zukunft):
            name, rc, dauer, ausgabe = f.result()
            gemessen[name] = dauer
            if zukunft[f]:
                if rc == 0:
                    streichen.append(name)
            else:
                ergebnisse.append((name, rc, dauer, ausgabe))
        ergebnisse.sort(key=lambda e: e[0])
        streichen.sort()
        for d in einzeln:
            ergebnisse.append(lauf(d, a.zeitdeckel))
            gemessen[d.name] = ergebnisse[-1][2]
        dauern_speichern(gemessen)
        for name, rc, dauer, ausgabe in ergebnisse:
            letzte = [z for z in ausgabe.strip().splitlines() if z.strip()][-1:] or [""]
            if rc == 0:
                gruen.append(name)
                # Nur bei GRUENEN: bei rot und Exit 2 traegt der Auszug die
                # Zeile ohnehin (ABBRUCH/FAIL), und doppelt gemeldet wandert
                # dasselbe in zwei Abschnitte.
                luecken += _luecken(name, ausgabe)
            elif rc == 2:
                nicht_gelaufen.append((name, letzte[0][:160], _auszug(ausgabe)))
            else:
                grund = "Zeitdeckel" if rc is None else f"Exit {rc}"
                rot.append((name, grund, _auszug(ausgabe)))
            print(f"  {'OK  ' if rc == 0 else ('N/L ' if rc == 2 else 'FAIL')} "
                  f"{name}  ({dauer:.1f} s)", flush=True)

    print()
    if nicht_gelaufen:
        print(f"── konnte nicht laufen (Exit 2): {len(nicht_gelaufen)}")
        for name, z, _ in nicht_gelaufen:
            print(f"   {name}: {z}")
        # ⚠ UND DER AUSZUG DAZU, nicht nur die letzte Zeile. Seit Exit 2 den
        # Lauf faellt, ist "konnte nicht laufen" ein Befund - dann muss sein
        # Grund genauso lesbar sein wie bei einem roten Waechter. Am 2026-10-12
        # hat test_bsi_m5 seine Sandkasten-Diagnose samt Pfaden ausgegeben, und
        # DIESE Schicht hat sie verworfen: gemeldet wurde nur die letzte Zeile
        # ("... 1 geaendert - Pfade siehe oben"), waehrend das "oben" nie
        # ankam. Eine Diagnose, die erzeugt und dann weggeworfen wird, ist
        # dasselbe wie keine.
        for name, _, auszug in nicht_gelaufen:
            print(f"\n══ N/L {name} (Exit 2) – Ende der Ausgabe:\n{auszug}")
    if ausn:
        print(f"── ausgenommen: {len(ausn)} (Gruende in {AUSNAHMEN.name})")
    if streichen:
        print(f"── ausgenommen, aber GRUEN – aus {AUSNAHMEN.name} streichen: {len(streichen)}")
        for name in streichen:
            print(f"   {name}")
    if luecken:
        # Name UND Zeile, wie bei "ausgenommen, aber GRUEN" - damit es handelbar
        # ist. Bewusst NICHT fail-closed: der Waechter LIEF, und den Grund hat er
        # selbst geprueft (dort eine Positivkontrolle ueber das Werkzeug). Ein
        # roter Lauf auf jedem Laeufer, dem ein Werkzeug fehlt, wuerde die Bilanz
        # entwerten - und eine entwertete Bilanz liest am Ende niemand.
        print(f"── gelaufen, aber Zusagen NICHT GEMESSEN: {len(luecken)}")
        for name, z in luecken:
            print(f"   {name}: {z}")
    for name, grund, ausgabe in rot:
        print(f"\n══ FAIL {name} ({grund}) – Ende der Ausgabe:\n{ausgabe}")
    print(f"\nBILANZ: {len(gruen)} gruen, {len(rot)} rot, {len(nicht_gelaufen)} nicht gelaufen, "
          f"{len(ausn)} ausgenommen"
          # Nur wenn es etwas zu tun gibt: eine Zahl, die in JEDER Zeile steht,
          # wird zur Tapete (so geschehen mit "nicht gelaufen", Kopf dieser Datei).
          + (", %d %s nicht gemessen" % (len(luecken),
                                         "Zusage" if len(luecken) == 1 else "Zusagen")
             if luecken else ""))
    if rot:
        # Befunde sind die staerkere Aussage als "nicht gemessen".
        return 1
    if nicht_gelaufen:
        print("ABBRUCH: Waechter, die nicht laufen konnten, sind KEIN gruener Lauf.\n"
              "         Entweder reparieren oder mit GRUND in "
              f"{AUSNAHMEN.name} aufnehmen.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
