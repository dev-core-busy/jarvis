#!/usr/bin/env python3
"""Gegenprobe zu tests/test_sicherheits_log_kette.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der Behebung vom 2026-10-26 zurueck, laesst den
Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf,
danach Byte-Gleichheit aller Dateien per md5. Laeuft ohne Bytecode.

Gesichert wird AUF PLATTE (Laufmarke neben dieser Datei): ein abgeschossener
Lauf laesst sonst eine Sabotage im Arbeitsbaum liegen – am 2026-10-26 mit
gegen_bsi_m3.py genau so passiert (Sicherung nur im Speicher). Liegt beim Start
eine Laufmarke, wird zuerst zurueckgenommen.

Nicht geprobt: die Sperre ueber Prozessgrenzen (flock). Ein Wettlauf zweier
Prozesse ist im Waechter nicht deterministisch herstellbar – die Zeile ist
benannt statt mit einer stummen Probe belegt.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_sicherheits_log_kette.py"
MARKE = ROOT / "tests" / ".gegen_sicherheits_log_kette.laufmarke"
SL = "backend/sicherheits_log.py"
SK = "backend/secret_key.py"

PROBEN = [
    ("Nebenprozess ohne Schluessel schreibt wieder in die Kette", SL,
     "                if not schluessel and _letzter_eintrag().get(\"mac\"):\n",
     "                if False:\n"),
    ("Nebenprozess laedt den Schluessel nicht selbst", SL,
     "    if _mac_schluessel or _selbst_geladen:\n",
     "    if True:\n"),
    (".env wird nicht gelesen", SL,
     "        if not env.strip():\n",
     "        if False:\n"),
    ("fremder Anhang wird nicht erkannt (Groesse nicht verglichen)", SL,
     "            and groesse == _letzte_groesse):\n",
     "            and True):\n"),
    ("pruefen-Befehl meldet ohne Schluessel wieder Scheinbrueche", SL,
     "            sys.exit(2)\n        r = pruefen()\n",
     "            pass\n        r = pruefen()\n"),
    ("nur_lesen liefert ohne Hauptschluessel einen fluechtigen Ersatz", SK,
     "        if haupt is None:\n            return None\n",
     "        if haupt is None:\n            return secrets.token_hex(32)\n"),
    ("nur_lesen nimmt einen Platzhalter aus der Datei", SK,
     "    return None if ist_platzhalter(wert) else wert\n",
     "    return wert or None\n"),
    ("nur_lesen ignoriert den Umgebungswert", SK,
     "    if not ist_platzhalter(env_wert):\n        return env_wert.strip()\n    try:\n        wert = datei.read_text().strip()\n    except OSError:\n        return None\n",
     "    try:\n        wert = datei.read_text().strip()\n    except OSError:\n        return None\n"),
]

DATEIEN = [SL, SK, "tests/test_sicherheits_log_kette.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def zurueck() -> None:
    """Rueckstand eines abgebrochenen Laufs zuruecknehmen (Laufmarke)."""
    if not MARKE.exists():
        return
    daten = json.loads(MARKE.read_text())
    for d, b64 in daten.items():
        (ROOT / d).write_bytes(base64.b64decode(b64))
    MARKE.unlink()
    print("Rueckstand eines frueheren Laufs zurueckgenommen: " + ", ".join(daten))


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       timeout=600, cwd=str(ROOT), env=env)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    zurueck()
    vorher = {d: md5(d) for d in DATEIEN}
    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")
    MARKE.write_text(json.dumps({d: base64.b64encode((ROOT / d).read_bytes()).decode()
                                 for d in DATEIEN}))
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}

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
                f, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if f > 0:
                beissen += 1
                print("  BISS %-62s %d FAIL" % (name, f))
            else:
                print("  ZAHN %-62s %s – beisst NICHT" % (name, "Abbruch" if f < 0 else "0 FAIL"))
    finally:
        for d, b in sicherung.items():
            (ROOT / d).write_bytes(b)
    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("ABBRUCH: Dateien nicht byte-gleich wiederhergestellt – Laufmarke bleibt")
        return 2
    MARKE.unlink()
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
