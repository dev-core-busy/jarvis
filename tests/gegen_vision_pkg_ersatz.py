#!/usr/bin/env python3
"""Gegenprobe zu tests/test_vision_pkg_ersatz.py: beisst der Waechter?

Jede Probe dreht EINE Zusage des pkg_resources-Ersatzes in vision_engine.py
zurueck, laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit per md5, ohne Bytecode, mit
Laufmarke (ein abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

⚠ NIE in einem Sammellauf mitlaufen lassen – die Proben patchen Dateien.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_vision_pkg_ersatz.laufmarke"

VE = "skills/vision/vision_engine.py"

PROBEN = [
    ("Import ohne Ersatz", VE,
     "    with _pkg_resources_ersatz():\n        import face_recognition\n",
     "    if True:\n        import face_recognition\n"),
    ("SystemExit nicht abgefangen", VE,
     "except (ImportError, SystemExit):\n    face_recognition = None",
     "except ImportError:\n    face_recognition = None"),
    ("Ersatz bleibt nach dem Import stehen", VE,
     '            del sys.modules["pkg_resources"]', "            pass"),
    ("Ersatz auch neben echtem pkg_resources", VE,
     "    if not _pkg_resources_fehlt():", "    if False:"),
    ("geworfene Suche gilt als vorhanden", VE,
     "    except (ImportError, ValueError):\n        return True",
     "    except (ImportError, ValueError):\n        return False"),
    ("schon geladenes Modul wird ueberdeckt", VE,
     '    if "pkg_resources" in sys.modules:\n        return False',
     '    if False:\n        return False'),
    ("Unterverzeichnis der Ressource verloren", VE,
     'joinpath(*ressource.split("/"))', 'joinpath(ressource.split("/")[-1])'),
]

DATEIEN = [VE, "tests/test_vision_pkg_ersatz.py"]

WAECHTER = [
    (["python3", "tests/test_vision_pkg_ersatz.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout, re.M)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {(r.stdout + r.stderr).strip()[-200:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    """Rueckstand eines abgeschossenen Laufs zuruecknehmen (Laufmarke)."""
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-58s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
