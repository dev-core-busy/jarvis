#!/usr/bin/env python3
"""Gegenprobe zu tests/test_server_sprache.py.

Jede Probe sabotiert eine KOPIE (backend/ + Waechter + tests/lib in einem
Wegwerf-Verzeichnis) und laesst den Waechter dort laufen. Die Repo-Dateien
werden nie angefasst. Erwartet je Probe: Exit 1 mit FAIL, nie Exit 2.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WAECHTER = REPO / "tests" / "test_server_sprache.py"
SP = "backend/sprache.py"
MAIN = "backend/main.py"
UPD = "backend/update_manager.py"
PY = str(REPO / "venv/bin/python") if (REPO / "venv/bin/python").exists() else sys.executable

PROBEN = [
    ("Middleware uebersetzt nie", MAIN,
     '        if sp == "de" or not response.headers.get("content-type", "").startswith("application/json"):',
     '        if True:', 1),
    ("Cookie wird ignoriert", SP, '        return normieren(request.cookies.get(COOKIE)) or vorgabe() or "de"',
     '        return "de"', 1),
    ("?lang= gewinnt nicht", SP, '        if q:\n            return q\n', '', 1),
    ("Muster nicht erkannt", SP, '    for rx, e, namen in idx.get("muster", []):', '    for rx, e, namen in []:', 1),
    ("alle Felder statt Textfelder", SP, '    for feld in FELDER:\n        neu = satz_uebersetzen(daten.get(feld), sprache)',
     '    for feld in list(daten):\n        neu = satz_uebersetzen(daten.get(feld) if isinstance(daten.get(feld), str) else (daten.get(feld) or [None])[0] if isinstance(daten.get(feld), list) else None, sprache)', 1),
    ("alte Content-Length bleibt", MAIN,
     '        kopf = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}',
     '        kopf = dict(response.headers.items())', 1),
    ("Groessengrenze fehlt", SP, '    if not roh or len(roh) > ANTWORT_MAX:', '    if not roh:', 1),
    ("unbekannte Sprache durchgelassen", SP, '    return w if w in SPRACHEN else ""', '    return w', 1),
    # 2026-11-26: Lizenz-Banner und Update-Pill
    ("license_banner nicht uebersetzt", SP, '"msg",\n          # Lizenz-Warnung im Portal (/api/me, nur Admins)\n          "license_banner")',
     '"msg")', 1),
    ("git ohne Sprachumgebung", UPD, '            env=_git_umgebung(),\n', '', 1),
    ("Sprachumgebung immer geerbt", UPD, '    return {**os.environ, "LANGUAGE": "en"}', '    return None', 1),
]
# Proben auf die Textdatei: ein Satz fehlt -> die Regel ueber main.py bzw. die
# Regeln fuer Lizenz-Banner und Update-Pill muessen beissen
TEXT_PROBEN = [
    "Nicht authentifiziert",
    "Kein Lizenzschlüssel eingetragen – die Lizenzgrenzen greifen in {w1} Tagen.",
    "Lizenz wurde widerrufen",
    "git fetch fehlgeschlagen: {w1}",
    "git log fehlgeschlagen",
]


def lauf(wurzel: Path) -> tuple[int, int, str]:
    p = subprocess.run([PY, str(wurzel / "tests" / WAECHTER.name)], capture_output=True, text=True,
                       timeout=300, cwd=str(wurzel), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return p.returncode, len(re.findall(r"^\s*FAIL ", p.stdout, re.M)), p.stdout + p.stderr


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="gegen_sprache_"))
    try:
        (tmp / "tests").mkdir()
        shutil.copy2(WAECHTER, tmp / "tests" / WAECHTER.name)
        shutil.copytree(REPO / "tests" / "lib", tmp / "tests" / "lib",
                        ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(REPO / "backend", tmp / "backend", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        original = {}
        for _, datei, alt, _, soll in PROBEN:
            text = original.setdefault(datei, (REPO / datei).read_text(encoding="utf-8"))
            if text.count(alt) != soll:
                print("ABBRUCH: Anker in %s %dx (erwartet %d): %r" % (datei, text.count(alt), soll, alt[:70]))
                return 2
        rc, fails, aus = lauf(tmp)
        if rc != 0 or fails:
            print("ABBRUCH: Basislauf nicht gruen (Exit %d, %d FAIL)\n%s" % (rc, fails, aus[-1200:]))
            return 2
        print("Basislauf gruen")
        stumm = 0
        for name, datei, alt, neu, _ in PROBEN:
            ziel = tmp / datei
            ziel.write_text(original[datei].replace(alt, neu), encoding="utf-8")
            try:
                rc, fails, aus = lauf(tmp)
            finally:
                ziel.write_text(original[datei], encoding="utf-8")
            if rc == 1 and fails:
                print("  BEISST  %-34s %d FAIL" % (name, fails))
            else:
                stumm += 1
                print("  STUMM   %-34s Exit %d, %d FAIL" % (name, rc, fails))
        # Textdatei: je Probe fehlt ein Satz
        tdatei = tmp / "backend" / "server_texte.json"
        t_orig = tdatei.read_text(encoding="utf-8")
        for satz in TEXT_PROBEN:
            d = json.loads(t_orig)
            vorher = len(d["saetze"])
            d["saetze"] = [e for e in d["saetze"] if e["de"] != satz]
            if len(d["saetze"]) != vorher - 1:
                print("ABBRUCH: Probesatz nicht genau einmal in server_texte.json: %r" % satz[:60])
                return 2
            tdatei.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            try:
                rc, fails, _ = lauf(tmp)
            finally:
                tdatei.write_text(t_orig, encoding="utf-8")
            name = "fehlt: " + satz[:26]
            if rc == 1 and fails:
                print("  BEISST  %-34s %d FAIL" % (name, fails))
            else:
                stumm += 1
                print("  STUMM   %-34s Exit %d, %d FAIL" % (name, rc, fails))
        gesamt = len(PROBEN) + len(TEXT_PROBEN)
        print("\nERGEBNIS: %d/%d Proben beissen" % (gesamt - stumm, gesamt))
        return 1 if stumm else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
