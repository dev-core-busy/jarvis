#!/usr/bin/env python3
"""Gegenproben zu tests/test_index_parallel.py.

⚠ SICHERUNG als REGEL (Exit 2), nicht gepflegt - ein abgeschossener Lauf liesse
den Arbeitsbaum sonst sabotiert zurueck.
"""
import inspect
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-index-parallel"
MARKE = ABLAGE / ".laeuft"

KNOW = "backend/tools/knowledge.py"
WAECHTER = "tests/test_index_parallel.py"
DATEIEN = [KNOW, WAECHTER]


def sichern():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    os.chmod(ABLAGE, 0o700)
    for rel in DATEIEN:
        shutil.copy2(WURZEL / rel, ABLAGE / rel.replace("/", "__"))


def zurueck():
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, WURZEL / rel)


def lauf():
    r = subprocess.run([sys.executable, str(WURZEL / WAECHTER)],
                       capture_output=True, text=True, timeout=300, cwd=WURZEL)
    z = [l for l in r.stdout.splitlines() if l.startswith("ERGEBNIS:")]
    if not z:
        return -1, False
    try:
        return int(z[-1].split(",")[1].strip().split()[0]), True
    except (IndexError, ValueError):
        return -1, False


def patch(rel, alt, neu, anzahl=1):
    p = WURZEL / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"ANKER TRIFFT NICHT ({s.count(alt)}x): {alt[:60]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


PROBEN = [
    # DER GEMELDETE ZUSTAND: gar keine Sperre im Suchpfad.
    # ⚠ DIE GANZE KONSTRUKTION MUSS WEG. Nur das acquire zu entschaerfen
    # (`if False:`) laesst das release im finally stehen -> RuntimeError
    # "release unlocked lock", der Waechter bricht ab statt fehlzuschlagen.
    # Eine Sabotage, die einen Zustand erzeugt, den es im Altstand nie gab,
    # misst nicht den Altstand.
    ("ALTSTAND: keine Sperre im Suchpfad", lambda: patch(
        KNOW,
        "        if not _inline_index_lock.acquire(blocking=False):\n"
        '            _log.debug("Inline-Indexlauf laeuft bereits – diese Suche nutzt den "\n'
        '                       "vorhandenen Index")\n'
        "            return vs.chunk_count() > 0\n"
        "        try:\n"
        "            return _inline_vector_index(vs, indexed, folders, max_bytes)\n"
        "        finally:\n"
        "            _inline_index_lock.release()",
        "        return _vector_index_lauf(vs, indexed, folders, max_bytes, force=False)")),

    ("blockierende Sperre statt ueberspringen", lambda: patch(
        KNOW, "_inline_index_lock.acquire(blocking=False)",
        "_inline_index_lock.acquire(blocking=True)")),

    ("uebersprungener Lauf meldet False statt des echten Standes", lambda: patch(
        KNOW,
        '                       "vorhandenen Index")\n            return vs.chunk_count() > 0',
        '                       "vorhandenen Index")\n            return False')),

    ("Freigabe nicht im finally (Sperre bleibt nach Ausnahme zu)", lambda: patch(
        KNOW,
        "        try:\n            return _inline_vector_index(vs, indexed, folders, max_bytes)\n"
        "        finally:\n            _inline_index_lock.release()",
        "        ergebnis = _inline_vector_index(vs, indexed, folders, max_bytes)\n"
        "        _inline_index_lock.release()\n        return ergebnis")),

    ("laufender Voll-Reindex wird ignoriert", lambda: patch(
        KNOW, "    if _reindex_lock.locked():", "    if False:")),

    ("Reindex-Zweig meldet False statt des echten Standes", lambda: patch(
        KNOW,
        '        _log.debug("Neu-Indizieren laeuft – Inline-Lauf entfaellt fuer diese Suche")\n'
        "        return vs.chunk_count() > 0",
        '        _log.debug("Neu-Indizieren laeuft – Inline-Lauf entfaellt fuer diese Suche")\n'
        "        return False")),

    ("auch force=True nimmt die Inline-Sperre", lambda: patch(
        KNOW, "    return _vector_index_lauf(vs, indexed, folders, max_bytes, force)",
        "    with _inline_index_lock:\n"
        "        return _vector_index_lauf(vs, indexed, folders, max_bytes, force)")),

    # GEGEN DEN WAECHTER: misst er die Gleichzeitigkeit wirklich?
    # ⚠ NICHT den Vorgabewert aendern - jeder Aufruf uebergibt ihn ausdruecklich,
    # die Sabotage traefe ihr Ziel gar nicht (erste Fassung war deshalb stumm).
    # Der Schlaf IM Lauf ist die Stelle: ohne ihn gibt es keine Ueberlappung,
    # und "nur EIN Lauf" waere trivial wahr.
    ("WAECHTER: Lauf-Attrappe dauert nicht (keine Gleichzeitigkeit messbar)",
     lambda: patch(WAECHTER, "        time.sleep(lauf_dauer)", "        pass")),
]


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs – stelle wieder her")
        zurueck()
        MARKE.unlink(missing_ok=True)

    fehlend = {rel for _n, fn in PROBEN for rel in (KNOW, WAECHTER)
               if rel in inspect.getsource(fn) and rel not in DATEIEN}
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
            print(f"ABBRUCH: Basislauf NICHT gruen ({basis} FAIL)")
            sys.exit(2)
        print(f"Basislauf gruen – {len(PROBEN)} Proben\n")

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
                print(f"  ⚠ OHNE BILANZ    {name}")
            elif n > 0:
                beissen += 1
                print(f"  beisst ({n:2} FAIL)  {name}")
            else:
                print(f"  ⚠ STUMM          {name}")
        print(f"\nERGEBNIS: {beissen} von {len(PROBEN)} Proben beissen")
        return 0 if beissen == len(PROBEN) else 1
    finally:
        zurueck()
        MARKE.unlink(missing_ok=True)
        for rel in DATEIEN:
            q = ABLAGE / rel.replace("/", "__")
            if q.exists() and q.read_bytes() != (WURZEL / rel).read_bytes():
                print(f"⚠ NICHT wiederhergestellt: {rel}")
                return 2


if __name__ == "__main__":
    sys.exit(main())
