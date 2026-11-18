#!/usr/bin/env python3
"""Gegenprobe zur Kennungs-Auskunft (cve_pruefung.kennung_auskunft,
syspackages.js kennungBlock): beissen test_cve_pruefung.py Abschnitt 11 und
test_cve_kennung_ui.js?

Jede Probe dreht EINE tragende Zeile zurueck, laesst den zustaendigen Waechter
laufen und erwartet Exit 1 mit mindestens einem FAIL. Vorher muss die Basis
gruen sein (ohne gruene Basis ist keine Probe deutbar). Die Sicherung liegt
im HOME; bleibt sie nach einem Abbruch liegen, nimmt der naechste Start den
Rueckstand selbst zurueck. Laeuft OHNE Bytecode (siehe Register).

    python3 tests/gegen_cve_kennung.py   Exit 0 alle beissen, 1 eine stumm, 2 nicht lauffaehig
NICHT in einem Sammellauf starten – die Probe patcht Dateien.
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
MARKE = Path.home() / ".jarvis_gegen_cve_kennung.json"
B = "backend/cve_pruefung.py"; F = "frontend/js/syspackages.js"
PROBEN = [
 ("Kernel: laufender Kernel zaehlt nicht", B, "                if cve_apt.vergleiche(kernel, fv) >= 0:\n                    z[\"zustand\"] = \"behoben\"", "                if False:\n                    z[\"zustand\"] = \"behoben\"", "py"),
 ("OSV auch bei lokalem Treffer", B, "        if not bef and not aus[\"lokal\"]:\n", "        if True:\n", "py"),
 ("Tracker: Teilstring statt Schluessel", B, "            if isinstance(wert, dict) and kennung in wert:\n                treffer[str(quelle)] = wert[kennung]", "            if isinstance(wert, dict) and any(kennung in x for x in wert):\n                treffer[str(quelle)] = next(v for x, v in wert.items() if kennung in x)", "py"),
 ("Online-Antwort nicht gemerkt", B, "    _online_cache[kennung] = (time.time(), aus)\n", "", "py"),
 ("fremdes Debian-Release mitgezaehlt", B, "                    if eco != f\"Debian:{nummer}\":\n                        continue\n", "", "py"),
 ("lokal_fehlt/unbekannt vertauscht", B, "    return \"lokal_fehlt\" if on.get(\"gefunden\") else \"unbekannt\"", "    return \"unbekannt\"", "py"),
 ("Fehler wird gemerkt", B, "        return {\"ok\": False, \"quelle\": \"OSV\", \"fehler\": f\"{type(e).__name__}: {e}\"[:300]}", "        aus = {\"ok\": False, \"quelle\": \"OSV\", \"fehler\": f\"{type(e).__name__}: {e}\"[:300]}\n        _online_cache[kennung] = (time.time(), aus)\n        return aus", "py"),
 ("JS: nie gesendete Anfrage bleibt haengen", F, "            if (alt && alt.laedt && !alt.gesendet) delete _kennung[_kennungTimer.k];\n", "", "js"),
 ("JS: Kasten trotz Paket-Treffer", F, "        var kennHtml = kennung && !Object.keys(ueberKennung).length\n", "        var kennHtml = kennung\n", "js"),
 ("JS: Zeilen unmaskiert", F, "                return '<li>' + esc(z) + '</li>';", "                return '<li>' + z + '</li>';", "js"),
 ("JS: Knopf immer", F, "        var knopf = (neu || u === 'lokal_fehlt') && !(_cve && _cve.laeuft)", "        var knopf = true", "js"),
 ("JS: keine Tipp-Pause", F, "        }, 500) };", "        }, 0) };", "js"),
]
DATEIEN = [B, F]
if {p[1] for p in PROBEN} - set(DATEIEN):
    print("ABBRUCH: eine Probe fasst eine Datei an, die nicht gesichert wird")
    sys.exit(2)
# Rueckstand eines abgebrochenen Laufs zuruecknehmen.
if MARKE.exists():
    for p, inhalt in json.loads(MARKE.read_text(encoding="utf-8")).items():
        (R / p).write_text(inhalt, encoding="utf-8")
    MARKE.unlink()
    print("Rueckstand eines frueheren Laufs zurueckgenommen")
md5 = lambda p: hashlib.md5((R / p).read_bytes()).hexdigest()
vor = {p: md5(p) for p in DATEIEN}
sich = {p: (R / p).read_bytes() for p in DATEIEN}
MARKE.write_text(json.dumps({p: b.decode("utf-8") for p, b in sich.items()}), encoding="utf-8")
MARKE.chmod(0o600)
stumm = 0
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
def lauf(art):
    cmd = ["python3", "tests/test_cve_pruefung.py"] if art == "py" else ["node", "tests/test_cve_kennung_ui.js"]
    r = subprocess.run(cmd, cwd=R, capture_output=True, text=True, timeout=300, env=env)
    return r.returncode, len(re.findall(r"^\s+FAIL ", r.stdout, re.M))
try:
    for art in ("py", "js"):
        rc, n = lauf(art)
        print(f"Basis {art}: Exit {rc}, {n} FAIL")
        if rc != 0:
            print("ABBRUCH: Basis nicht gruen")
            sys.exit(2)
    for name, datei, alt, neu, art in PROBEN:
        t = sich[datei].decode()
        if t.count(alt) != 1:
            print(f"ABBRUCH: Anker der Probe \"{name}\" {t.count(alt)}x gefunden")
            sys.exit(2)
        (R / datei).write_text(t.replace(alt, neu), encoding="utf-8")
        rc, n = lauf(art)
        (R / datei).write_bytes(sich[datei])
        biss = rc == 1 and n > 0
        stumm += 0 if biss else 1
        print(f"  {'BEISST' if biss else 'STUMM '} {name}: Exit {rc}, {n} FAIL")
finally:
    for p in DATEIEN: (R / p).write_bytes(sich[p])
    gleich = all(md5(p) == vor[p] for p in DATEIEN)
    print("Dateien byte-gleich wiederhergestellt:", gleich)
    if gleich:
        MARKE.unlink(missing_ok=True)
print(f"\nErgebnis: {len(PROBEN) - stumm} von {len(PROBEN)} Proben beissen")
sys.exit(0 if stumm == 0 else 1)
