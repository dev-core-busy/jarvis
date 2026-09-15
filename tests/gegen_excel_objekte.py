#!/usr/bin/env python3
"""Gegenproben zu den Excel-Objekten: beisst jeder Waechter EINZELN?

Eine Gegenprobe, die nicht beisst, ist ein TESTMANGEL – kein Beweis. Gemessen
wird am **Exit-Code UND an der Bilanzzeile**, nie am Zaehlen von FAIL-Zeilen:
ein Lauf, der ohne Bilanz abbricht, ist von „bestanden" nicht zu unterscheiden.

⚠ DIE SICHERUNGSLISTE WIRD ALS REGEL GEPRUEFT. Faehrt eine Probe eine Datei an,
die nicht gesichert ist, bleibt die Sabotage liegen – und der naechste Lauf
meldet einen Fehler, den es im Code nicht gibt. Das ist im Projekt zweimal
passiert (Register).
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-excel-objekte"
MARKE = ABLAGE / "laeuft"

DATEIEN = [
    "backend/excel_objekte.py",
    "backend/excel_ask.py",
    "backend/excel_addin.py",
    "backend/tools/excel_vorschlag.py",
    "frontend/excel-addin/excel.js",
]

WAECHTER = [
    ("py", "tests/test_excel_objekte.py"),
    ("js", "tests/test_excel_objekte_ui.js"),
]


def sichern() -> None:
    """Sichert bei JEDEM Lauf neu – eine alte Sicherung stellte sonst beim
    zweiten Durchgang einen VERALTETEN Stand her und machte fertige Arbeit
    zunichte (Register, 2026-09-05)."""
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)
    MARKE.write_text("1")


def zurueck() -> None:
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)


def aufraeumen() -> None:
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


def lauf(art: str, pfad: str) -> tuple[int, str]:
    cmd = ([sys.executable, pfad] if art == "py" else ["node", pfad])
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
    return (p.returncode, p.stdout + p.stderr)


def bilanz_fails(ausgabe: str) -> int | None:
    """Liest die FAIL-Zahl aus der Bilanzzeile. ``None`` = keine Bilanz."""
    for zeile in reversed(ausgabe.strip().splitlines()):
        if zeile.startswith("Ergebnis:"):
            if "ABGEBROCHEN" in zeile:
                return None
            try:
                return int(zeile.split(",")[1].strip().split()[0])
            except Exception:  # noqa: BLE001
                return None
    return None


def patch(rel: str, alt: str, neu: str) -> None:
    p = ROOT / rel
    s = p.read_text()
    # TREFFERKONTROLLE: eine Ersetzung ohne assert ist kein Messwert – die
    # Probe saehe wie ein zahnloser Waechter aus, waehrend sie gar nicht griff.
    assert alt in s, "Anker nicht gefunden in %s: %r" % (rel, alt[:70])
    p.write_text(s.replace(alt, neu, 1))


# ── Proben ────────────────────────────────────────────────────────────────
# (Name, Dateien die sie anfasst, Funktion)
PROBEN = []


def probe(name: str, *dateien):
    def deko(fn):
        PROBEN.append((name, list(dateien), fn))
        return fn
    return deko


@probe("Objekt-Zweig aus excel_ask entfernt", "backend/excel_ask.py")
def _p1():
    patch("backend/excel_ask.py",
          "        if _objekte.ist_objekt(eintrag):",
          "        if False and _objekte.ist_objekt(eintrag):")


@probe("Blatt-Anlage nur ueber die Zellen", "frontend/excel-addin/excel.js")
def _p2():
    patch("frontend/excel-addin/excel.js",
          "            var angelegt = [];\n            alle.forEach(function (a) {",
          "            var angelegt = [];\n            aenderungen.forEach(function (a) {")


@probe("Objekte VOR den Zellen", "frontend/excel-addin/excel.js")
def _p3():
    # Den Objekt-Schritt vor die Kosmetik ziehen heisst hier: vor das
    # Zellschreiben, weil der Kosmetik-Schritt erst nach dem Schreiben laeuft.
    patch("frontend/excel-addin/excel.js",
          "        var objekte = alle.filter(istObjekt);",
          "        var objekte = [];  // sabotiert: keine Objekte mehr")


@probe("Tabelle wird GELOESCHT statt zurueckverwandelt",
       "frontend/excel-addin/excel.js")
def _p4():
    patch("frontend/excel-addin/excel.js",
          "s.tables.getItem(a._objName || a.name).convertToRange();",
          "s.tables.getItem(a._objName || a.name).delete();")


@probe("bedingtes Format per clearAll entfernt", "frontend/excel-addin/excel.js")
def _p5():
    patch("frontend/excel-addin/excel.js",
          "s.getRange(a.adresse).conditionalFormats.getItemAt(0).delete();",
          "s.getRange(a.adresse).conditionalFormats.clearAll();")


@probe("1.8-Pruefung entfernt (Wurf statt Absage)",
       "frontend/excel-addin/excel.js")
def _p6():
    patch("frontend/excel-addin/excel.js",
          "        if (a.typ === 'pivot' && !_kann18) {",
          "        if (a.typ === 'pivot' && false) {")


@probe("summarizeBy wird nicht gesetzt", "frontend/excel-addin/excel.js")
def _p7():
    patch("frontend/excel-addin/excel.js",
          "                    try { dh.summarizeBy = w.funktion; } catch (e) { }",
          "                    try { dh._x = w.funktion; } catch (e) { }")


@probe("Vergleichswert ohne fuehrendes =", "frontend/excel-addin/excel.js")
def _p8():
    patch("frontend/excel-addin/excel.js",
          "var regel = { formula1: '=' + String(a.wert), operator:",
          "var regel = { formula1: String(a.wert), operator:")


@probe("Name wird nicht zurueckgelesen (kein Rueckweg)",
       "frontend/excel-addin/excel.js")
def _p9():
    patch("frontend/excel-addin/excel.js",
          "            try { erzeugt.load('name'); } catch (e) { }",
          "            /* sabotiert: kein load */")


@probe("_angelegt wird nicht gesetzt", "frontend/excel-addin/excel.js")
def _p10():
    patch("frontend/excel-addin/excel.js",
          "                a._angelegt = true;\n                return { a: a, ok: true };",
          "                return { a: a, ok: true };")


@probe("Fehlermeldung nennt Werte, die selbst abgelehnt wuerden",
       "backend/excel_objekte.py")
def _p11():
    # ⚠ NICHT bei den Operatoren ansetzen: dort sind die Office-Namen seit
    # 2026-09-15 ZUSAETZLICH gueltige Eingaben, die Sabotage waere also
    # harmlos und die Probe ein falscher Alarm. Bei den Diagrammarten ist
    # `"ColumnClustered".lower()` dagegen KEIN Schluessel – die Meldung
    # schickte den Leser dann im Kreis.
    patch("backend/excel_objekte.py",
          '% (art[:30], ", ".join(HAUPT_ARTEN)))',
          '% (art[:30], ", ".join(sorted(set(DIAGRAMM_ARTEN.values())))))')


@probe("api_min fuer pivot faelschlich auf 1.7", "backend/excel_objekte.py")
def _p12():
    patch("backend/excel_objekte.py", '"pivot": "1.8",', '"pivot": "1.7",')


@probe("Manifest wird auf 1.8 hochgezogen", "backend/excel_addin.py")
def _p13():
    patch("backend/excel_addin.py", 'EXCEL_API_MIN = "1.7"', 'EXCEL_API_MIN = "1.8"')


@probe("kopfzeile per Falsyness statt is False", "backend/excel_objekte.py")
def _p14():
    patch("backend/excel_objekte.py",
          'ziel["kopfzeile"] = e.get("kopfzeile") is not False',
          'ziel["kopfzeile"] = bool(e.get("kopfzeile"))')


@probe("Tabellenname wird nicht geprueft", "backend/excel_objekte.py")
def _p15():
    patch("backend/excel_objekte.py",
          '    if typ == "tabelle":\n        if _WIE_ZELLE_RE.match(name):',
          '    if False:\n        if _WIE_ZELLE_RE.match(name):')


@probe("Pivot ohne Wertfeld wird durchgelassen", "backend/excel_objekte.py")
def _p16():
    patch("backend/excel_objekte.py",
          "    if not werte_roh:\n        return (\"Eine Pivot-Tabelle braucht mindestens ein Wertfeld \"",
          "    if False:\n        return (\"Eine Pivot-Tabelle braucht mindestens ein Wertfeld \"")


@probe("Objekt-Fehler nur ins Protokoll, nicht in den Verlauf",
       "frontend/excel-addin/excel.js")
def _p17():
    patch("frontend/excel-addin/excel.js",
          "            if (erg.objFehler && erg.objFehler.length) {",
          "            if (false && erg.objFehler && erg.objFehler.length) {")


def main() -> int:
    # Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
    if MARKE.exists():
        print("Rueckstand eines frueheren Laufs gefunden – nehme ihn zurueck.")
        zurueck()
        MARKE.unlink()

    # REGEL: jede angefasste Datei muss gesichert werden.
    fehlend = {d for _, ds, _ in PROBEN for d in ds} - set(DATEIEN)
    if fehlend:
        print("ABBRUCH: nicht gesicherte Dateien in Proben: %s" % sorted(fehlend))
        return 2

    sichern()
    atexit.register(aufraeumen)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    # ── Basislauf: ohne gruene Basis ist keine Gegenprobe deutbar ──────────
    print("Basislauf …")
    basis = {}
    for art, pfad in WAECHTER:
        rc, aus = lauf(art, pfad)
        f = bilanz_fails(aus)
        basis[pfad] = f
        if f is None:
            print("ABBRUCH: %s liefert keine Bilanz" % pfad)
            print(aus[-2000:])
            return 2
        if f != 0:
            print("ABBRUCH: %s ist schon ohne Sabotage rot (%d FAIL)" % (pfad, f))
            print(aus[-2000:])
            return 2
    print("  Basis gruen.\n")

    beissen = 0
    for name, dateien, fn in PROBEN:
        zurueck()
        try:
            fn()
        except AssertionError as e:
            print("  ⚠ %-52s ANKER VERFEHLT (%s)" % (name, e))
            continue
        summe = 0
        abbruch = False
        for art, pfad in WAECHTER:
            rc, aus = lauf(art, pfad)
            f = bilanz_fails(aus)
            if f is None:
                abbruch = True
            else:
                summe += f
        if abbruch:
            print("  ⚠ %-52s BRICHT AB (keine Bilanz)" % name)
        elif summe > 0:
            print("  ✓ %-52s %d FAIL" % (name, summe))
            beissen += 1
        else:
            print("  ✗ %-52s BEISST NICHT" % name)

    zurueck()
    print("\n%d von %d Proben beissen." % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
