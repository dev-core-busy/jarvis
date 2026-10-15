#!/usr/bin/env python3
"""Gegenprobe zu tests/test_x11vnc_shm.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der Behebung zurueck; gruener Basislauf vorher,
Byte-Gleichheit nachher, ohne Bytecode, mit Laufmarke.
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
MARKE = ROOT / "tests" / ".gegen_x11vnc_shm.laufmarke"
DC = "backend/desktop_control.py"
SJ = "start_jarvis_root.sh"

PROBEN = [
    ("restart_vnc wieder mit pkill -9", DC,
     "    \"\"\"x11vnc fuer Display :0 robust neu starten.\"\"\"\n    x11vnc_beenden()\n",
     "    \"\"\"x11vnc fuer Display :0 robust neu starten.\"\"\"\n"
     "    subprocess.run([\"pkill\", \"-9\", \"x11vnc\"], capture_output=True, timeout=5)\n"),
    ("Session-Wechsel wieder mit pkill -9", DC,
     "        # 3. x11vnc stoppen (TERM – SIGKILL liesse 42 SHM-Segmente liegen)\n        x11vnc_beenden()\n",
     "        # 3. x11vnc stoppen\n        subprocess.run([\"pkill\", \"-9\", \"x11vnc\"], capture_output=True, timeout=5)\n"),
    ("sofort KILL statt TERM", DC,
     '    subprocess.run(["pkill", "-TERM", "-x", "x11vnc"], capture_output=True, timeout=5)\n',
     '    subprocess.run(["pkill", "-KILL", "-x", "x11vnc"], capture_output=True, timeout=5)\n'),
    ("kein Warten auf TERM", DC,
     "    while time.monotonic() < frist and _x11vnc_laeuft():\n",
     "    while False:\n"),
    ("nach KILL kein Aufraeumen", DC,
     "        n = shm_verwaiste_aufraeumen()\n", "        n = 0\n"),
    ("Aufraeumen trotz lebendem Erzeuger", DC,
     '        if os.path.exists("/proc/%s" % t[2]):\n            continue\n', ""),
    ("Aufraeumen trotz Anhang", DC,
     ' and t[2] in ("root", VNC_BENUTZER) and t[5] == "0":\n', ' and t[2] in ("root", VNC_BENUTZER):\n'),
    ("Aufraeumen fremder Eigentuemer", DC,
     ' and t[2] in ("root", VNC_BENUTZER) and t[5] == "0":\n', ' and t[5] == "0":\n'),
    ("Broker-Start raeumt nicht auf", SJ,
     "(cd \"$CODE_DIR\" && python3 -m backend.desktop_control shm-aufraeumen) \\\n",
     "(cd \"$CODE_DIR\" && true backend.desktop_control) \\\n"),
]

DATEIEN = [DC, SJ, "tests/test_x11vnc_shm.py"]

WAECHTER = [
    (["python3", "tests/test_x11vnc_shm.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
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
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {r.stdout.strip()[-160:]}"
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
