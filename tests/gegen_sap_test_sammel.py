#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_sap_test_sammel.py?

Legt sabotierte KOPIEN von ``backend/main.py`` bzw. ``frontend/js/sap.js`` in
ein Wegwerf-Verzeichnis und gibt sie dem Waechter ueber ``--main`` /
``--sapjs`` mit – die echten Dateien werden nie angefasst.

Vorher ein Basislauf gegen die unveraenderten Dateien: ohne gruene Basis ist
keine Probe deutbar. Eine Probe "beisst", wenn der Waechter mit Exit 1 und
mindestens einem FAIL endet – Exit 2 ("konnte nicht laufen") zaehlt NICHT.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = HIER / "test_sap_test_sammel.py"
DATEIEN = {
    "main": (ROOT / "backend" / "main.py", "--main"),
    "sapjs": (ROOT / "frontend" / "js" / "sap.js", "--sapjs"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("Admin-Knopf ruft wieder /api/sap/test (Stand vor dem Fix)", "sapjs",
     "            fetch('/api/sap/test/sammel', { headers: authHeaders() })\n",
     "            fetch('/api/sap/test', { headers: authHeaders() })\n"),
    ("Sammel-Test loest den Zugang auf (persoenlich mit Vorrang)", "main",
     "    return await _sap_test_antwort(SapClient(), \"sammel\", \"\", user)\n",
     "    z = _sap_zugang(user, trotz_aussetzer=True)\n"
     "    return await _sap_test_antwort(z[\"client\"], \"sammel\", \"\", user)\n"),
    ("Sammel-Test ohne Admin-Recht", "main",
     "async def sap_test_sammel(user: str = Depends(require_local_auth)):\n",
     "async def sap_test_sammel(user: str = Depends(require_sap_access)):\n"),
    ("Anmeldefehler zaehlt immer beim persoenlichen Zugang", "main",
     "    except SapError as e:\n"
     "        # Ein Anmeldefehler zaehlt gegen den Aussetzer – aber nur, wenn wirklich\n"
     "        # der persoenliche Zugang getestet wurde (sonst rechnete man dem\n"
     "        # Benutzer einen Fehler des Sammelzugangs an).\n"
     "        if quelle == \"persoenlich\":\n",
     "    except SapError as e:\n"
     "        if True:\n"),
    ("Sammel-Test meldet sich als persoenlich", "main",
     "    return await _sap_test_antwort(SapClient(), \"sammel\", \"\", user)\n",
     "    return await _sap_test_antwort(SapClient(), \"persoenlich\", \"\", user)\n"),
]


def lauf(argumente: list) -> tuple:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER), *argumente], cwd=str(ROOT),
                       env=env, capture_output=True, text=True, timeout=300)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None), r.stdout + r.stderr


def main() -> int:
    nicht_gedeckt = {p[1] for p in PROBEN} - set(DATEIEN)
    if nicht_gedeckt:
        print(f"ABBRUCH: Proben auf unbekannte Dateien: {nicht_gedeckt}")
        return 2
    code, fails, aus = lauf([])
    if code != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, FAIL {fails})")
        print(aus[-2000:])
        return 2
    print("Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_saptestsammel_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, schalter = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??  {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
                stumm += 1
                continue
            ziel = Path(tmp) / f"probe{i}_{quelle.name}"
            ziel.write_text(text.replace(alt, neu), encoding="utf-8")
            code, fails, aus = lauf([schalter, str(ziel)])
            if code == 1 and fails:
                print(f"  BEISST {i:2d} {name} ({fails} FAIL)")
            else:
                stumm += 1
                print(f"  STUMM  {i:2d} {name} (Exit {code}, FAIL {fails})")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
