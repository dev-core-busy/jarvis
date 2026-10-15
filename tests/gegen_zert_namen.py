#!/usr/bin/env python3
"""Gegenprobe zu Abschnitt 13 von tests/test_outlook_addin.py: beisst er?

Geprueft wird die Zusage "liegt ein SAN vor, zaehlt der CN NICHT" samt der
Deutung von ``zert_deckt_basis`` (None = nicht feststellbar, nicht False).

ZWEI GETRENNTE ERWARTUNGEN, und die Trennung ist der Punkt (Register, Fall
``test_keine_externen_einbindungen``):

* **BISS-Proben** drehen eine Zusage im PRODUKT zurueck. Erwartet wird mindestens
  ein FAIL – der Waechter laeuft und widerspricht.
* **ABBRUCH-Proben** nehmen dem Waechter die Messgrundlage (openssl liefert
  nichts). Erwartet wird **Exit 2**: "konnte nicht laufen" muss von "bestanden"
  UND von "beisst" unterscheidbar bleiben. Zaehlte man das als Biss, waere ein
  blinder Waechter von einem scharfen nicht zu trennen.

Der Waechter hat auf diesem Stand zwei ALTE FAILs, die nicht zu dieser Aenderung
gehoeren (Hell-Modus, Marke in den addin.js-Texten; gegen origin/master
nachgemessen). Deshalb zaehlt hier nicht "FAIL > 0", sondern ob die Zahl der
FAILs GEGENUEBER DEM BASISLAUF steigt – ein Basislauf, der nicht gruen ist, waere
sonst gar nicht deutbar.

Vorher Basislauf, danach Byte-Gleichheit per md5. Ohne Bytecode.

Lauf:  python3 tests/gegen_zert_namen.py
Exit 0 = alle Proben verhalten sich wie erwartet, 1 = mindestens eine nicht,
         2 = konnte nicht laufen
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_outlook_addin.py"
AD = "backend/addin.py"

# (Name, Datei, alt, neu) – ganze Zeilen, damit der Anker eindeutig ist.
BISS_PROBEN = [
    # Der Fehler, der auf ECHT gemessen wurde: CN immer mitgezaehlt.
    ("CN wird immer mitgezaehlt (Zustand vor dem 2026-10-13)", AD,
     "    if not namen:\n",
     "    namen += [t.strip().lower()\n"
     "              for t in re.findall(r\"CN\\s*=\\s*([^,/\\n]+)\", roh)]\n"
     "    if False:\n"),
    # Fail-open in der Deutung: ohne lesbares Zertifikat "deckt nicht ab"
    # statt "nicht feststellbar".
    ("ohne Namen wird False statt None gemeldet", AD,
     "    if not host or not namen:\n", "    if not host:\n"),
    # SAN gar nicht gelesen -> der CN traegt wieder alles.
    ("SAN wird nicht gelesen", AD,
     "    namen = [t.strip().lower()\n"
     "             for t in re.findall(r\"(?:DNS|IP Address):\\s*([^,\\s]+)\", roh)]\n",
     "    namen = []\n"),
]

ABBRUCH_PROBEN = [
    # Nimmt die Messgrundlage weg: zert_namen() liefert fuer BEIDE Zertifikate
    # eine leere Liste. Dann sind alle inhaltlichen Pruefungen trivial wahr –
    # der Waechter MUSS mit Exit 2 abbrechen statt gruen zu melden.
    ("openssl liefert nichts (Messgrundlage weg)", AD,
     "        roh = (res.stdout or \"\") + (res.stderr or \"\")\n",
     "        roh = \"\"\n"),
]

PROBEN = BISS_PROBEN + ABBRUCH_PROBEN
# Register: JEDE Datei, die eine Probe anfasst, gehoert gesichert - auch die
# Waechterdatei selbst, falls je eine Probe sie anfasst.
DATEIEN = [AD, "tests/test_outlook_addin.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    """(FAIL-Anzahl, Returncode). FAIL = -1, wenn die Bilanzzeile fehlt."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                       text=True, timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"(\d+) bestanden, (\d+) fehlgeschlagen", r.stdout)
    if not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    fehlend = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlend:
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an: %s" % sorted(fehlend))
        return 2

    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    basis_fails, rc = lauf()
    if basis_fails < 0:
        print("ABBRUCH: Basislauf ohne Bilanzzeile (rc=%s)" % rc)
        return 2
    print("Basislauf: %d FAIL (Altbestand, nicht aus dieser Aenderung) – "
          "gemessen wird die STEIGERUNG.\n" % basis_fails)

    gut = 0
    try:
        for name, datei, alt, neu in PROBEN:
            erwartet_abbruch = (name, datei, alt, neu) in ABBRUCH_PROBEN
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %-58s Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])

            if erwartet_abbruch:
                if rc == 2:
                    gut += 1
                    print("  ABBR %-58s Exit 2 wie erwartet" % name)
                else:
                    print("  ZAHN %-58s Exit %s statt 2 (FAIL=%s)" % (name, rc, fails))
            elif fails > basis_fails:
                gut += 1
                print("  BISS %-58s %d FAIL (+%d)"
                      % (name, fails, fails - basis_fails))
            elif rc == 2:
                print("  ZAHN %-58s Exit 2 – Waechter konnte nicht messen, "
                      "das ist KEIN Biss" % name)
            else:
                print("  ZAHN %-58s %d FAIL – beisst NICHT" % (name, fails))
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben verhalten sich wie erwartet "
          "(Dateien byte-gleich wiederhergestellt)" % (gut, len(PROBEN)))
    return 0 if gut == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
