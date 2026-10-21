#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_h7.py: beisst der Waechter?

Jede Probe dreht EINEN Teil des H7-Fixes zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Laeuft ohne
Bytecode (PYTHONDONTWRITEBYTECODE=1).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bsi_h7.py"
SK = "backend/sicherheits_kopf.py"
CSP = "backend/csp.py"
MAIN = "backend/main.py"

PROBEN = [
    ("HSTS auch bei selbst signiertem Zertifikat", SK,
     "    return zertifikat_selbst_signiert() is False\n", "    return True\n"),
    ("HSTS bei unlesbarem Zertifikat", SK,
     "    return zertifikat_selbst_signiert() is False\n",
     "    return zertifikat_selbst_signiert() is not True\n"),
    ("HSTS auch ueber HTTP", SK,
     "    if https and hsts_aktiv():\n", "    if hsts_aktiv():\n"),
    ("Add-in-Seiten mit X-Frame-Options", SK,
     "    if not any(pfad.startswith(p) for p in ADDIN_PRAEFIXE):\n", "    if True:\n"),
    ("Referrer-Policy zu offen", SK,
     'REFERRER = "same-origin"\n', 'REFERRER = "unsafe-url"\n'),
    ("nosniff fehlt", SK,
     '    k = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": REFERRER}\n',
     '    k = {"Referrer-Policy": REFERRER}\n'),
    ("HSTS mit includeSubDomains/preload", SK,
     'HSTS_WERT = "max-age=31536000"\n', 'HSTS_WERT = "max-age=31536000; includeSubDomains; preload"\n'),
    ("HSTS nur 1 Tag", SK,
     'HSTS_WERT = "max-age=31536000"\n', 'HSTS_WERT = "max-age=86400"\n'),
    ("unbekannter Modus gilt als 'an'", SK,
     "    return wert if wert in HSTS_MODI else HSTS_VORGABE\n",
     '    return wert if wert in HSTS_MODI else "an"\n'),
    ("Zertifikats-Cache ohne mtime", SK,
     "        if _zert_cache and _zert_cache[0] == mtime:\n", "        if _zert_cache:\n"),
    ("Office-Hosts auf allen Seiten", CSP,
     "        \"frame-ancestors 'self'\" + (\" \" + FRAME_ANCESTORS_OFFICE if addin else \"\"),\n",
     "        \"frame-ancestors 'self' \" + FRAME_ANCESTORS_OFFICE,\n"),
    ("frame-ancestors fehlt", CSP,
     "        \"frame-ancestors 'self'\" + (\" \" + FRAME_ANCESTORS_OFFICE if addin else \"\"),\n", ""),
    ("Middleware ueberschreibt Routen-Vorgaben", MAIN,
     "        response.headers.setdefault(name, wert)\n", "        response.headers[name] = wert\n"),
    ("Middleware nicht registriert", MAIN,
     "@app.middleware(\"http\")\nasync def _sicherheits_kopfzeilen(", "async def _sicherheits_kopfzeilen("),
    ("Kopfzeilen-Endpunkt ohne Admin-Schranke", MAIN,
     "async def security_kopfzeilen_setzen(request: Request, user: str = Depends(require_local_auth)):\n",
     "async def security_kopfzeilen_setzen(request: Request, user: str = Depends(require_auth)):\n"),
]

DATEIEN = [SK, CSP, MAIN, "tests/test_bsi_h7.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-52s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-52s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-52s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

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
