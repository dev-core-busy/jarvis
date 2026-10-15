#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m3_ui.js: beisst der Waechter?

Jede Probe dreht EINEN Teil des M3-Fixes zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne Bytecode.

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
WAECHTER = ROOT / "tests" / "test_bsi_m3_ui.js"
APP = "frontend/js/app.js"
MOD = "frontend/js/totp_admin.js"

PROBEN = [
    ("Login ignoriert requires_totp_setup", APP,
     "            } else if (data.requires_totp_setup) {\n",
     "            } else if (false) {\n"),
    ("Einrichtung zeigt den QR nicht", APP,
     "                    totpSetup.hidden = false;\n", ""),
    ("Einrichtung zeigt den Server-Hinweis als Fehler", APP,
     "                    totpSetup.hidden = false;\n                    loginError.hidden = true;\n",
     "                    totpSetup.hidden = false;\n                    loginError.textContent = data.error; loginError.hidden = false;\n"),
    ("Erfolg laesst die Einrichtung stehen", APP,
     "                if (totpSetup) totpSetup.hidden = true;\n", ""),
    ("Sperrliste: Name als HTML", MOD,
     "            row.appendChild(el('strong', { 'style': 'color:var(--text-primary);' }, s.display || s.konto));\n",
     "            var _s = el('strong', {}); _s.innerHTML = s.display || s.konto; row.appendChild(_s);\n"),
    ("Aufheben laedt nicht neu", MOD,
     "                    if ((res.status === 200 && res.d.ok) || res.status === 404) { schutzLaden(); return; }\n",
     "                    if ((res.status === 200 && res.d.ok) || res.status === 404) { return; }\n"),
    ("Schalter: Fehlschlag wird nicht zurueckgenommen", MOD,
     "                cb.checked = !soll;\n                if (msg) msg.textContent = res.d.detail",
     "                if (msg) msg.textContent = res.d.detail"),
    ("Schalter doppelt verdrahtet", MOD,
     "        if (!cb || cb.dataset.verdrahtet) return;\n", "        if (!cb) return;\n"),
    ("onShow laedt den Anmeldeschutz nicht", MOD,
     "        pflichtVerdrahten();\n        schutzLaden();\n", "        pflichtVerdrahten();\n"),
]

DATEIEN = [APP, MOD, "tests/test_bsi_m3_ui.js"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(["node", str(WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"Ergebnis: (\d+)/(\d+)", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)) - int(m.group(1)), r.returncode


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
                print("  BISS %-56s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-56s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-56s 0 FAIL – beisst NICHT" % name)
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
