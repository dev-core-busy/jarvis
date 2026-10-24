#!/usr/bin/env python3
"""Gegenprobe zu tests/test_adressbuch.py: beisst der Waechter?

Jede Probe dreht EINE Zusage von backend/adressbuch.py zurueck, laesst den
Waechter laufen und erwartet mindestens einen FAIL. Davor ein gruener
Basislauf (ohne ihn ist keine Gegenprobe deutbar), danach Byte-Gleichheit per
md5. Ohne Bytecode (PYTHONDONTWRITEBYTECODE=1): liegen Sabotage und
Wiederherstellung in derselben Sekunde und sind gleich gross, laedt ein
spaeterer Lauf sonst die SABOTAGE bei byte-gleicher Quelle.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

    python3 tests/gegen_adressbuch.py
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_adressbuch.py"
AB = "backend/adressbuch.py"
PY = sys.executable

PROBEN = [
    # (name, datei, alt, neu)
    ("ohne Benutzer wird trotzdem gesucht (fail-open)", AB,
     "    if not wer:\n", "    if False:\n"),
    ("Rueckfall auch bei LEEREM Ergebnis", AB,
     "        return {\"treffer\": treffer, \"quelle\": \"ews\", \"hinweis\": \"\"}\n",
     "        if treffer:\n"
     "            return {\"treffer\": treffer, \"quelle\": \"ews\", \"hinweis\": \"\"}\n"
     "        gruende.append(\"Exchange → leer\")\n"),
    ("Aussetzer wird uebergangen", AB,
     "    konto = mail_accounts.konto_fuer(benutzer)\n",
     "    konto = mail_accounts.konto_fuer(benutzer, trotz_aussetzer=True)\n"),
    ("Anmeldefehler wird nicht gemeldet", AB,
     "            mail_accounts.merke_ergebnis(benutzer, False, str(f), art=f.kategorie)\n",
     "            mail_accounts.merke_ergebnis(benutzer, False, str(f))\n"),
    ("Eintraege ohne Adresse gelten als Treffer", AB,
     "        if \"@\" not in adr:\n            continue\n", "        pass\n"),
    ("gleiche Adresse mehrfach", AB,
     "        if schluessel in gesehen:\n            continue\n", "        pass\n"),
    ("Limit wird nicht gedeckelt", AB,
     "    return max(1, min(n, MAX_LIMIT))\n", "    return n\n"),
    ("Mindestlaenge der Frage aufgehoben", AB,
     "    if len(f) < MIN_FRAGE:\n", "    if False:\n"),
    ("Drossel abgeschaltet", AB,
     "    if not ok:\n        raise AdressbuchFehler(grund)\n", "    pass\n"),
    ("Drossel zaehlt global statt je Benutzer", AB,
     "    liste = [t for t in _verlauf.get(str(benutzer), []) if jetzt - t < 60]\n",
     "    liste = [t for t in _verlauf.get(\"alle\", []) if jetzt - t < 60]\n"),
    ("der Hinweis nennt den ersten Fehlschlag nicht", AB,
     "            \"erreichbar war: %s\" % \"; \".join(gruende)}\n",
     "            \"erreichbar war.\"}\n"),
    ("beide Quellen weg: nur der LETZTE Grund", AB,
     "            \"Das Adressbuch konnte nicht durchsucht werden. Versucht: %s\"\n"
     "            % \"; \".join(gruende)) from e\n",
     "            \"Das Adressbuch konnte nicht durchsucht werden.\") from e\n"),
    ("Verbindung wird nicht geschlossen", AB,
     "            c.schliessen()\n", "            pass\n"),
    ("Verzeichnis wird ohne Reserve gefragt", AB,
     "    rohe = ldap_directory.search_users(frage, None, None, limit=limit * 5)\n",
     "    rohe = ldap_directory.search_users(frage, None, None, limit=limit)\n"),
]

DATEIEN = [AB, "tests/test_adressbuch.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    """FAIL-Anzahl des Waechters. -1 = konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run([PY, str(WAECHTER)], capture_output=True, text=True,
                           timeout=600, cwd=str(ROOT), env=env)
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    m = re.search(r"Ergebnis: (\d+) ok, (\d+) fehlgeschlagen", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), 0


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
                print("  ???  %-52s Anker %dx gefunden" % (name, text.count(alt)))
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
                print("  ABBR %-52s konnte nicht laufen (rc=%s)" % (name, rc))
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
