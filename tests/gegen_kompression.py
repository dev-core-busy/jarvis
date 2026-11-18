#!/usr/bin/env python3
"""Gegenprobe zu ``test_kompression.py``: jede Sabotage hebt EINE Zusage auf,
der Waechter muss jede einzeln mit Exit 1 melden.

Sichert die angefassten Dateien in ``~/.gegen-sicherung-gzip`` und nimmt einen
Rueckstand eines abgebrochenen Laufs beim Start zurueck. Braucht ein venv mit
starlette >= 1.3.1 (``venv/bin/python tests/gegen_kompression.py``).
Nie in einem Sammellauf mitlaufen lassen (patcht den Arbeitsbaum).
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SICHER = Path.home() / ".gegen-sicherung-gzip"
WAECHTER = ROOT / "tests" / "test_kompression.py"

PROBEN = [
    ("/api/ wird komprimiert", "backend/kompression.py",
     'AUSGENOMMEN = ("/api/", "/ws", "/webdav", "/openapi.json")',
     'AUSGENOMMEN = ("/ws", "/webdav", "/openapi.json")'),
    ("/webdav wird komprimiert", "backend/kompression.py",
     'AUSGENOMMEN = ("/api/", "/ws", "/webdav", "/openapi.json")',
     'AUSGENOMMEN = ("/api/", "/ws", "/openapi.json")'),
    ("/ws wird komprimiert", "backend/kompression.py",
     'AUSGENOMMEN = ("/api/", "/ws", "/webdav", "/openapi.json")',
     'AUSGENOMMEN = ("/api/", "/webdav", "/openapi.json")'),
    ("jede Methode wird komprimiert", "backend/kompression.py",
     '    if scope.get("method") not in ("GET", "HEAD"):\n        return False\n', ""),
    ("gar nichts wird komprimiert", "backend/kompression.py",
     "        if komprimierbar(scope):\n", "        if False:\n"),
    ("Doku-Seite /api faellt unter die Ausnahme", "backend/kompression.py",
     "    if pfad.startswith(AUSGENOMMEN):\n",
     "    if pfad == \"/api\" or pfad.startswith(AUSGENOMMEN):\n"),
    ("Rumpf wird nicht mehr zusammengefasst", "backend/kompression.py",
     "        self.gzip = GZipMiddleware(_Zusammenfassen(app), minimum_size=minimum_size,\n",
     "        self.gzip = GZipMiddleware(app, minimum_size=minimum_size,\n"),
    ("auch Stroeme ohne Laenge werden gepuffert", "backend/kompression.py",
     "                puffern = laenge.isdigit() and int(laenge) <= PUFFER_MAX\n",
     "                puffern = True\n"),
    ("keine Mindestgroesse", "backend/kompression.py",
     "MINDESTGROESSE = 1024\n", "MINDESTGROESSE = 1\n"),
    # VERSCHIEBEN, nicht verdoppeln: eine zusaetzliche Registrierung vorne liesse
    # die urspruengliche am Ende stehen – die Weiche waere weiter die letzte.
    ("Weiche nicht mehr aeusserste Schicht", "backend/main.py",
     "app.add_middleware(_AnfragePfadMiddleware)\n\n# GZip fuer statische",
     "from backend import kompression as _kompression\n"
     "app.add_middleware(_kompression.KompressionsWeiche)\n"
     "app.add_middleware(_AnfragePfadMiddleware)\n\n# GZip fuer statische",
     ("app.add_middleware(_kompression.KompressionsWeiche)\n\n",
      "_kompression.KompressionsWeiche  # verschoben\n\n")),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def zurueck() -> None:
    if not SICHER.exists():
        return
    for rel in DATEIEN:
        s = SICHER / rel
        if s.exists():
            shutil.copy2(s, ROOT / rel)
            if md5(s) != md5(ROOT / rel):
                print(f"ABBRUCH: {rel} nicht byte-gleich wiederhergestellt")
                sys.exit(2)


def lauf() -> int:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                          env=env, timeout=300).returncode


def main() -> int:
    zurueck()
    shutil.rmtree(SICHER, ignore_errors=True)
    for rel in DATEIEN:
        ziel = SICHER / rel
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, ziel)
    try:
        basis = lauf()
        if basis != 0:
            print(f"ABBRUCH: Basislauf nicht gruen (Exit {basis}) – keine Gegenprobe deutbar")
            return 2
        beisst = 0
        for name, rel, alt, neu, *zusatz in PROBEN:
            p = ROOT / rel
            t = p.read_text(encoding="utf-8")
            if t.count(alt) != 1:
                print(f"  ANKER  {name}: trifft {t.count(alt)}x (Proben-Mangel)")
                continue
            t = t.replace(alt, neu)
            # Zweite Ersetzung (Verschiebung): erst NACH der ersten zaehlen,
            # dann muss sie genau einmal treffen – sonst Proben-Mangel.
            fehlt = False
            for z_alt, z_neu in zusatz:
                if t.count(z_alt) != 1:
                    print(f"  ANKER  {name}: Zusatz trifft {t.count(z_alt)}x (Proben-Mangel)")
                    fehlt = True
                    break
                t = t.replace(z_alt, z_neu)
            if fehlt:
                continue
            p.write_text(t, encoding="utf-8")
            try:
                rc = lauf()
            finally:
                shutil.copy2(SICHER / rel, p)
            ok = rc == 1
            beisst += ok
            print(f"  {'BEISST' if ok else 'STUMM '} {name} (Exit {rc})")
        print(f"\nErgebnis: {beisst} von {len(PROBEN)} Proben beissen")
        return 0 if beisst == len(PROBEN) else 1
    finally:
        zurueck()
        shutil.rmtree(SICHER, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
