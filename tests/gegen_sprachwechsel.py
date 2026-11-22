#!/usr/bin/env python3
"""Gegenprobe zum Sprachwechsel-Fix (2026-11-22).

Waechter: tests/test_sprachwechsel_zuhoerer.js (Regel ueber alle Module) und
die vier UI-Waechter, die seitdem ueber den ECHTEN Weg umschalten
(`setLang` -> `applyLang` -> Ereignis am window).

Jede Probe dreht EINE Zusage im PRODUKT zurueck und nennt die Waechter, die
darauf anschlagen MUESSEN (jeder einzelne mit Exit 1). Exit 2 zaehlt NICHT
als Biss – dann hat eine Positivkontrolle der Messvorrichtung abgebrochen.
Vorher gruener Basislauf aller Waechter, danach Byte-Gleichheit.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SICHERUNG = Path.home() / ".gegen_sprachwechsel_sicherung"

REGEL = "tests/test_sprachwechsel_zuhoerer.js"
W_SPROT = "tests/test_sicherheitsprotokoll_ui.js"
W_PROT = "tests/test_protokolle_ui.js"
W_TV = "tests/test_token_verbrauch_ui.js"
W_FA = "tests/test_fehleranalyse_ui.js"
WAECHTER = [REGEL, W_SPROT, W_PROT, W_TV, W_FA]

SPROT = "frontend/js/sicherheitsprotokoll.js"
PROT = "frontend/js/protokolle.js"
TV = "frontend/js/token_verbrauch.js"
FA = "frontend/js/fehleranalyse.js"
I18N = "frontend/js/i18n.js"

ZUH = "window.addEventListener('jarvis-lang-changed', function () {\n"
ZUH_DOC = "document.addEventListener('jarvis-lang-changed', function () {\n"
SCHRANKE = "if (sprache === window._lang) return;\n"

PROBEN = [
    # (Name, Datei, alt, neu, Waechter, die beissen muessen)
    ("Sicherheitsprotokoll hoert wieder am document (der Vorfall)", SPROT,
     "        " + ZUH, "        " + ZUH_DOC, [REGEL, W_SPROT]),
    ("Sicherheitsprotokoll zeichnet bei jedem applyLang() neu", SPROT,
     "            " + SCHRANKE, "", [W_SPROT]),
    ("Protokolle hoeren wieder am document", PROT,
     "    " + ZUH, "    " + ZUH_DOC, [REGEL, W_PROT]),
    ("Protokolle zeichnen bei jedem applyLang() neu", PROT,
     "        " + SCHRANKE, "", [W_PROT]),
    ("Token-Verbrauch hoert wieder am document", TV,
     "        " + ZUH, "        " + ZUH_DOC, [REGEL, W_TV]),
    ("Token-Verbrauch baut bei jedem applyLang() die Listen neu", TV,
     "            " + SCHRANKE, "", [W_TV]),
    ("Fehleranalyse hoert wieder am document", FA,
     "        " + ZUH, "        " + ZUH_DOC, [REGEL, W_FA]),
    ("Fehleranalyse zeichnet bei jedem applyLang() neu", FA,
     "            if (lang === window._lang) return;\n", "", [W_FA]),
    ("Fehleranalyse verwirft beim Neuzeichnen den gewaehlten Lauf", FA,
     "                sel.value = gewaehlt;\n", "", [W_FA]),
    ("i18n.js sendet am document statt am window", I18N,
     "        window.dispatchEvent(new CustomEvent('jarvis-lang-changed',\n",
     "        document.dispatchEvent(new CustomEvent('jarvis-lang-changed',\n", [REGEL, W_SPROT]),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(waechter: str) -> tuple[int, str]:
    r = subprocess.run(["node", str(ROOT / waechter)], cwd=ROOT, capture_output=True,
                       text=True, timeout=300)
    zeile = next((z for z in reversed(r.stdout.splitlines())
                  if "FAIL" in z or "ABBRUCH" in z or "✗" in z), "")
    return r.returncode, zeile.strip()[:90]


def zurueck() -> None:
    if not SICHERUNG.exists():
        return
    for rel in DATEIEN:
        quelle = SICHERUNG / rel
        if quelle.exists():
            shutil.copy2(quelle, ROOT / rel)
    shutil.rmtree(SICHERUNG)


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Dateiliste unvollstaendig.")
        return 2
    zurueck()  # Rueckstand eines abgebrochenen Laufs
    for name, rel, alt, _neu, _w in PROBEN:
        n = (ROOT / rel).read_text(encoding="utf-8").count(alt)
        if n != 1:
            print("ABBRUCH: Anker %dx gefunden – %s" % (n, name))
            return 2
    for w in WAECHTER:
        code, zeile = lauf(w)
        if code != 0:
            print("ABBRUCH: Basislauf %s nicht gruen (%s, Exit %d)" % (w, zeile, code))
            return 2
    print("Basislauf gruen: %d Waechter" % len(WAECHTER))
    vorher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    SICHERUNG.mkdir(mode=0o700)
    for rel in DATEIEN:
        (SICHERUNG / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, SICHERUNG / rel)
    stumm = []
    try:
        for name, rel, alt, neu, waechter in PROBEN:
            pfad = ROOT / rel
            original = pfad.read_text(encoding="utf-8")
            pfad.write_text(original.replace(alt, neu), encoding="utf-8")
            try:
                ergebnisse = [(w, *lauf(w)) for w in waechter]
            finally:
                pfad.write_text(original, encoding="utf-8")
            biss = all(code == 1 for _w, code, _z in ergebnisse)
            print("%s  %s" % ("BEISST" if biss else "STUMM ", name))
            for w, code, zeile in ergebnisse:
                print("          %-40s Exit %d  %s" % (Path(w).name, code, zeile))
            if not biss:
                stumm.append(name)
    finally:
        zurueck()
    nachher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    if nachher != vorher:
        print("FEHLER: Dateien nach der Gegenprobe nicht byte-gleich!")
        return 2
    print("\nDateien byte-gleich wiederhergestellt.")
    print("Bilanz: %d von %d Proben beissen" % (len(PROBEN) - len(stumm), len(PROBEN)))
    return 0 if not stumm else 1


if __name__ == "__main__":
    sys.exit(main())
