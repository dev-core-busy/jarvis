#!/usr/bin/env python3
"""Gegenprobe zu tests/test_pillow_brotli.py: beisst der Waechter?

Jede Probe dreht EINEN Teil der Bewertung vom 2026-10-26 zurueck (gebuendelter
Brotli-Decoder in Pillow, CVE-2026-111497), laesst den Waechter laufen und
erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach
Byte-Gleichheit aller Dateien per md5; Sicherung AUF PLATTE mit Laufmarke
(siehe tests/gegen_sicherheits_log_kette.py).

Die Frist-Probe beisst nur, solange der Interpreter dieses Laufs ein Pillow mit
Brotli < 1.2.1 hat – danach ist sie gegenstandslos und gehoert mit der
Ausnahme gestrichen.

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
WAECHTER = ROOT / "tests" / "test_pillow_brotli.py"
MARKE = ROOT / "tests" / ".gegen_pillow_brotli.laufmarke"
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() \
    else sys.executable
AI = "backend/addon_icons.py"
BT = "backend/tools/bild_text.py"
BS = "backend/branding_schriften.py"
TW = "tests/test_pillow_brotli.py"

PROBEN = [
    ("Wiedervorlage abgelaufen", TW,
     "FRIST = datetime.date(2026, 12, 1)\n", "FRIST = datetime.date(2020, 1, 1)\n"),
    ("addon_icons: Schrift aus fremder Quelle", AI,
     "    for pfad in _SCHRIFTEN:\n",
     "    for pfad in _SCHRIFTEN + (os.environ.get(\"JARVIS_SCHRIFT\", \"\"),):\n"),
    ("bild_text: Schrift aus dem Text des Benutzers", BT,
     "    pfad = _SCHRIFT_FETT if fett else _SCHRIFT\n",
     "    pfad = _SCHRIFT_FETT if fett else text\n"),
    ("bild_text: Schrift-Konstante ausserhalb /usr/share/fonts", BT,
     '_SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"\n',
     '_SCHRIFT = "/tmp/hochgeladen.woff2"\n'),
    ("Branding nimmt die Endung woff2 an", BS,
     'ENDUNGEN = {"ttf", "otf", "ttc", "otc"}\n',
     'ENDUNGEN = {"ttf", "otf", "ttc", "otc", "woff2", "woff"}\n'),
    ("Branding nimmt WOFF2-Inhalt an", BS,
     '    b"OTTO": "OpenType",\n',
     '    b"OTTO": "OpenType",\n    b"wOF2": "WOFF2",\n    b"wOFF": "WOFF",\n'),
]

DATEIEN = [AI, BT, BS, TW]


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
    r = subprocess.run([PY, str(WAECHTER)], capture_output=True, text=True,
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
