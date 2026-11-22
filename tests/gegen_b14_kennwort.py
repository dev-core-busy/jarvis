#!/usr/bin/env python3
"""Gegenprobe zu tests/test_b14_kennwort.py: beisst der Waechter?

Jede Probe sabotiert EINE Stelle in einer KOPIE der fuenf geprueften Dateien
(Wegwerf-Verzeichnis, JARVIS_B14_WURZEL) und erwartet mindestens einen FAIL.
Der Arbeitsbaum wird nie beschrieben – zwei der Dateien (i18n.js,
settings.html) sind gemeinsame Dateien, an denen parallel gearbeitet wird.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_b14_kennwort.py"
MAIN, APP, I18N, SEITE, SKRIPT = ("backend/main.py", "frontend/js/app.js", "frontend/js/i18n.js",
                                  "frontend/settings.html", "deploy/security/system_haertung.sh")
DATEIEN = [MAIN, APP, I18N, SEITE, SKRIPT]

PROBEN = [
    ("fester Dienst login", MAIN,
     "local_ok = _pam.authenticate(username, password, service=_pam_dienst())",
     'local_ok = _pam.authenticate(username, password, service="login")'),
    ("fester Dienst jarvis-web (ohne Rueckfall)", MAIN,
     '    return PAM_DIENST_WEB if PAM_DIENST_DATEI.is_file() else "login"',
     "    return PAM_DIENST_WEB"),
    ("Rueckfall auf other statt login", MAIN,
     '    return PAM_DIENST_WEB if PAM_DIENST_DATEI.is_file() else "login"',
     '    return PAM_DIENST_WEB if PAM_DIENST_DATEI.is_file() else "other"'),
    ("Verzeichnis gilt als Datei", MAIN,
     "PAM_DIENST_DATEI.is_file()", "PAM_DIENST_DATEI.exists()"),
    ("Dienstname verschrieben", MAIN,
     'PAM_DIENST_WEB = "jarvis-web"', 'PAM_DIENST_WEB = "jarvis_web"'),
    ("Mindestlaenge 8", MAIN, "KENNWORT_MIN_LAENGE = 14", "KENNWORT_MIN_LAENGE = 8"),
    ("Pruefung mit fester 8", MAIN,
     "    if len(password) < KENNWORT_MIN_LAENGE:", "    if len(password) < 8:"),
    ("Meldung ohne Zahl", MAIN,
     'errors.append(f"Mindestens {KENNWORT_MIN_LAENGE} Zeichen erforderlich.")',
     'errors.append("Kennwort zu kurz.")'),
    ("Staerkeanzeige 1 mit 8", APP, "            pw.length >= 14,", "            pw.length >= 8,"),
    ("Staerkeanzeige 2 mit 8", APP, "const score = [pw.length >= 14,", "const score = [pw.length >= 8,"),
    ("Hinweis DE mit 8", I18N, "Es muss mindestens 14 Zeichen, einen", "Es muss mindestens 8 Zeichen, einen"),
    ("Hinweis EN mit 8", I18N, "It must be at least 14 characters", "It must be at least 8 characters"),
    ("Vorgabetext settings.html mit 8", SEITE,
     "Es muss mindestens 14 Zeichen, einen", "Es muss mindestens 8 Zeichen, einen"),
    ("pwquality minlen 12", SKRIPT, "minlen = 14'", "minlen = 12'"),
]


def lauf(wurzel: Path) -> tuple[int, int]:
    env = dict(os.environ, JARVIS_B14_WURZEL=str(wurzel), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=120, env=env)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine Datei an, die nicht kopiert wird")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="gegen_b14_"))
    try:
        original = {d: (ROOT / d).read_text(encoding="utf-8") for d in DATEIEN}

        def baum(ersatz: dict | None = None) -> Path:
            w = tmp / "baum"
            shutil.rmtree(w, ignore_errors=True)
            for d, t in original.items():
                (w / d).parent.mkdir(parents=True, exist_ok=True)
                (w / d).write_text((ersatz or {}).get(d, t), encoding="utf-8")
            return w

        fails, rc = lauf(baum())
        if fails != 0:
            print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
            return 2
        print("Basislauf gruen.\n")
        beissen = 0
        for name, datei, alt, neu in PROBEN:
            n = original[datei].count(alt)
            if n != 1:
                print("  ???  %-44s Anker %dx gefunden" % (name, n))
                continue
            fails, rc = lauf(baum({datei: original[datei].replace(alt, neu)}))
            if fails > 0:
                beissen += 1
                print("  BISS %-44s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-44s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-44s 0 FAIL – beisst NICHT" % name)
        print("\n%d/%d Proben beissen (Arbeitsbaum nie beschrieben)" % (beissen, len(PROBEN)))
        return 0 if beissen == len(PROBEN) else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
