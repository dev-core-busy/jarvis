#!/usr/bin/env python3
"""Gegenproben zu tests/test_ocr_last.py – beisst der Waechter einzeln?

Jede Probe dreht GENAU EINE Zusage zurueck und erwartet, dass der Waechter das
meldet. Beisst eine nicht, ist das ein Waechter- oder Proben-Mangel – KEIN
Beweis, dass die Zusage haelt.

⚠ SICHERUNG: jede Datei, die eine Probe anfasst, MUSS in DATEIEN stehen. Das
wird als REGEL geprueft (Exit 2), nicht gepflegt – ein abgeschossener Lauf
liesse den Arbeitsbaum sonst sabotiert zurueck, und der naechste Lauf meldete
Fehler, die es im Code nicht gibt (im Projekt zweimal bezahlt).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-ocr-last"          # NICHT /tmp (1777, fremde Reste)
MARKE = ABLAGE / ".laeuft"

KNOW = "backend/tools/knowledge.py"
WAECHTER = "tests/test_ocr_last.py"
DATEIEN = [KNOW, WAECHTER]


def sichern():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    os.chmod(ABLAGE, 0o700)
    for rel in DATEIEN:
        ziel = ABLAGE / rel.replace("/", "__")     # relativer Pfad, nicht basename
        shutil.copy2(WURZEL / rel, ziel)


def zurueck():
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, WURZEL / rel)


def lauf():
    """Waechter fahren -> (FAIL-Zahl, hat_bilanz)."""
    r = subprocess.run([sys.executable, str(WURZEL / WAECHTER)],
                       capture_output=True, text=True, timeout=600, cwd=WURZEL)
    letzte = [z for z in r.stdout.splitlines() if z.startswith("ERGEBNIS:")]
    if not letzte:
        return -1, False                           # ohne Bilanz = nicht gelaufen
    try:
        return int(letzte[-1].split(",")[1].strip().split()[0]), True
    except (IndexError, ValueError):
        return -1, False


def patch(rel, alt, neu, anzahl=1):
    """Ersetzen MIT Trefferkontrolle – eine Probe, die nicht greift, sieht wie
    ein zahnloser Waechter aus."""
    p = WURZEL / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"ANKER TRIFFT NICHT ({s.count(alt)}x): {alt[:70]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


PROBEN = [
    ("OMP_THREAD_LIMIT aus der Umgebung entfernt", lambda: patch(
        KNOW, '_OCR_UMGEBUNG = {"OMP_THREAD_LIMIT": "1"}',
        '_OCR_UMGEBUNG = {"LC_ALL": "C"}')),

    ("kein timeout am tesseract-Aufruf", lambda: patch(
        KNOW, "timeout=_ocr_zeitdeckel(), env=umgebung, check=False",
        "env=umgebung, check=False")),

    ("Umgebung wird NICHT kopiert (minimal statt dict(os.environ))", lambda: patch(
        KNOW, "umgebung = dict(os.environ)", "umgebung = {}")),

    ("zurueck auf pytesseract.image_to_string", lambda: patch(
        KNOW, "    text = _ocr_datei(str(filepath), lang)",
        "    import pytesseract\n    from PIL import Image as _I\n"
        "    text = pytesseract.image_to_string(_I.open(str(filepath)), lang=lang)")),

    ("os.environ wird global gesetzt", lambda: patch(
        KNOW, "    umgebung = dict(os.environ)",
        '    os.environ["OMP_THREAD_LIMIT"] = "1"\n    umgebung = dict(os.environ)')),

    ("Zeitdeckel als Konstante statt Funktion", lambda: patch(
        KNOW, "def _ocr_zeitdeckel() -> int:", "_OCR_DECKEL = 120\ndef _ocr_zeitdeckel_alt() -> int:")),

    ("Plakette verlangt wieder pytesseract", lambda: patch(
        KNOW, 'else "Bilder/OCR ⚠️ (System-Paket tesseract-ocr nötig)")',
        'else "Bilder/OCR ⚠️ (tesseract-ocr + pytesseract nötig)")')),

    ("Verfuegbarkeit haengt wieder am Python-Paket", lambda: patch(
        KNOW, '        if shutil.which("tesseract"): has_image = True',
        '        try:\n            import pytesseract  # noqa: F401\n'
        '            has_image = True\n        except ImportError: pass')),

    ("leeres Bild liefert '' statt None", lambda: patch(
        KNOW, "        text = _ocr_datei(ziel, lang)\n        return text or None",
        "        text = _ocr_datei(ziel, lang)\n        return text")),

    ("ENV-Wert wird ungeprueft uebernommen (0 moeglich)", lambda: patch(
        KNOW, 'return v if 5 <= v <= 3600 else 120', 'return v')),

    # ⚠ GEGEN DEN WAECHTER SELBST: genau dieser Mangel war die erste Fassung –
    # ohne Variablen-Verfolgung findet er nur die harmlose --list-langs-Abfrage
    # und laesst die teure Erkennung aus.
    ("WAECHTER: Variablen-Verfolgung ausgebaut", lambda: patch(
        WAECHTER, "if _liste_mit_tesseract(erst) or (isinstance(erst, ast.Name) and erst.id in namen):",
        "if _liste_mit_tesseract(erst):")),

    ("WAECHTER: Kommentar-/Docstring-Filter ausgebaut", lambda: patch(
        WAECHTER, "OHNE = ohne_worte(QUELL)", "OHNE = QUELL")),
]


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs – stelle wieder her")
        zurueck()
        MARKE.unlink(missing_ok=True)

    # REGEL statt gepflegter Liste
    fehlend = set()
    for _name, fn in PROBEN:
        import inspect
        for rel in (KNOW, WAECHTER):
            if rel in inspect.getsource(fn) and rel not in DATEIEN:
                fehlend.add(rel)
    if fehlend:
        print(f"ABBRUCH: angefasst, aber nicht gesichert: {fehlend}")
        sys.exit(2)

    sichern()
    MARKE.write_text("x")
    try:
        basis, bilanz = lauf()
        if not bilanz:
            print("ABBRUCH: Basislauf ohne Bilanzzeile")
            sys.exit(2)
        if basis != 0:
            print(f"ABBRUCH: Basislauf ist NICHT gruen ({basis} FAIL) – "
                  f"ohne gruene Basis ist keine Gegenprobe deutbar")
            sys.exit(2)
        print(f"Basislauf gruen (0 FAIL) – {len(PROBEN)} Proben\n")

        beissen = 0
        for name, fn in PROBEN:
            zurueck()
            try:
                fn()
            except AssertionError as e:
                print(f"  ⚠ PROBEN-MANGEL  {name}: {e}")
                continue
            n, hat = lauf()
            if not hat:
                print(f"  ⚠ OHNE BILANZ    {name}  (Lauf abgebrochen)")
            elif n > 0:
                beissen += 1
                print(f"  beisst ({n:2} FAIL)  {name}")
            else:
                print(f"  ⚠ STUMM          {name}  – Waechter- oder Proben-Mangel")
        print(f"\nERGEBNIS: {beissen} von {len(PROBEN)} Proben beissen")
        return 0 if beissen == len(PROBEN) else 1
    finally:
        zurueck()
        MARKE.unlink(missing_ok=True)
        for rel in DATEIEN:                        # Byte-Gleichheit nachsehen
            q = ABLAGE / rel.replace("/", "__")
            if q.exists() and q.read_bytes() != (WURZEL / rel).read_bytes():
                print(f"⚠ NICHT wiederhergestellt: {rel}")
                return 2


if __name__ == "__main__":
    sys.exit(main())
