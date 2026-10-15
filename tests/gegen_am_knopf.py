#!/usr/bin/env python3
"""Gegenproben zum Knopf-Waechter in tests/test_ai_mouse_ui.js.

Ein Waechter, der nicht beisst, ist ein Testmangel - kein Beweis. Jede Probe
dreht GENAU EINE Aenderung zurueck und zaehlt die FAIL.

⚠ Gesichert wird auf PLATTE (~/.gegen-am-knopf) und ueber atexit/SIGTERM
zurueckgestellt: ein per Timeout abgeschossener Lauf hinterliess sonst den
Arbeitsbaum sabotiert, und der naechste Testlauf meldete einen Fehler, den der
Code nicht hat (Register, mehrfach bezahlt).

    python3 tests/gegen_am_knopf.py
"""
import atexit
import hashlib
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ABLAGE = pathlib.Path.home() / ".gegen-am-knopf"
DATEIEN = ["frontend/ai_mouse.html", "frontend/js/ai_mouse.js"]
WAECHTER = "tests/test_ai_mouse_ui.js"


def md5(p: pathlib.Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern() -> None:
    """Bei JEDEM Lauf erneuern - eine alte Sicherung stellt sonst einen
    veralteten Stand her und macht fertige Arbeit zunichte (Register)."""
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)


def zurueck() -> None:
    for rel in DATEIEN:
        quelle = ABLAGE / rel.replace("/", "__")
        if quelle.exists():
            shutil.copy2(quelle, ROOT / rel)


def rueckstand_pruefen() -> None:
    """Ein Rueckstand eines abgeschossenen Laufs wird zuerst zurueckgenommen."""
    if not ABLAGE.exists():
        return
    for rel in DATEIEN:
        quelle = ABLAGE / rel.replace("/", "__")
        if quelle.exists() and md5(quelle) != md5(ROOT / rel):
            print(f"  (Rueckstand in {rel} zurueckgenommen)")
            shutil.copy2(quelle, ROOT / rel)


def lauf() -> tuple[int, int, bool]:
    """(OK, FAIL, Bilanzzeile vorhanden). Ein Lauf OHNE Bilanz ist von
    'nicht gelaufen' nicht zu unterscheiden und zaehlt als Fehlschlag."""
    p = subprocess.run(
        ["node", WAECHTER], cwd=ROOT, capture_output=True, text=True, timeout=120,
        env={**os.environ, "JSDOM_PATH": os.environ.get("JSDOM_PATH", "/tmp/node_modules/jsdom")},
    )
    m = re.search(r"(\d+) OK, (\d+) FAIL", p.stdout)
    if not m:
        return (0, 0, False)
    return (int(m.group(1)), int(m.group(2)), True)


def probe(name: str, rel: str, alt: str, neu: str) -> None:
    pfad = ROOT / rel
    txt = pfad.read_text(encoding="utf-8")
    assert alt in txt, f"SABOTAGE VERFEHLT ihr Ziel in {rel}: {alt[:60]!r}"
    pfad.write_text(txt.replace(alt, neu, 1), encoding="utf-8")
    try:
        ok, fail, bilanz = lauf()
        if not bilanz:
            print(f"  ⚠ {name}: ABGEBROCHEN ohne Bilanz")
        else:
            zeichen = "beisst" if fail else "⚠ BEISST NICHT"
            print(f"  {zeichen:14s} {name}: {fail} FAIL ({ok} OK)")
    finally:
        zurueck()


def main() -> int:
    rueckstand_pruefen()
    sichern()
    atexit.register(zurueck)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))

    ok, fail, bilanz = lauf()
    if not bilanz or fail:
        print(f"BASIS NICHT GRUEN ({ok} OK, {fail} FAIL) - Gegenproben waeren nicht deutbar")
        return 2
    print(f"Basis gruen: {ok} OK\n")

    probe("Neue Frage zurueck auf .btn-secondary", "frontend/ai_mouse.html",
          'class="ja-btn" id="am-frage-neu"', 'class="btn-secondary" id="am-frage-neu"')
    probe("Zeile zurueck auf .ja-actions (CSS-lose Klasse)", "frontend/ai_mouse.html",
          '<div class="ja-dl">\n                <button type="button" class="ja-btn" id="am-frage-neu"',
          '<div class="ja-actions">\n                <button type="button" class="ja-btn" id="am-frage-neu"')
    probe("Speichern zurueck auf .btn-primary", "frontend/js/ai_mouse.js",
          "class=\"ja-btn ja-btn-haupt\" id=\"am-f-save\"", "class=\"btn-primary\" id=\"am-f-save\"")
    probe("Abbrechen zurueck auf .btn-secondary", "frontend/js/ai_mouse.js",
          "class=\"ja-btn\" id=\"am-f-cancel\"", "class=\"btn-secondary\" id=\"am-f-cancel\"")
    probe("Speichern verliert die Hauptaktion", "frontend/js/ai_mouse.js",
          "class=\"ja-btn ja-btn-haupt\" id=\"am-f-save\"", "class=\"ja-btn\" id=\"am-f-save\"")

    zurueck()
    fehlt = [r for r in DATEIEN if md5(ROOT / r) != md5(ABLAGE / r.replace("/", "__"))]
    print("\nWiederhergestellt: " + ("byte-gleich" if not fehlt else "⚠ ABWEICHUNG " + str(fehlt)))
    return 1 if fehlt else 0


if __name__ == "__main__":
    sys.exit(main())
