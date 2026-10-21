#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_ldap_sperrrichtlinie.py ueberhaupt?

Legt dem Waechter sabotierte KOPIEN von backend/ldap_directory.py vor (Argument,
Wegwerf-Verzeichnis) – die echte Datei wird nie angefasst.
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
WAECHTER = HIER / "test_ldap_sperrrichtlinie.py"
MODUL = HIER.parent / "backend" / "ldap_directory.py"

PROBEN = [
    ("100-ns-Fenster nicht in Sekunden umgerechnet",
     "            fenster = abs(int(roh or 0)) / 1e7\n", "            fenster = abs(int(roh or 0))\n", 1),
    ("Verbindung wird nicht geschlossen",
     "    except Exception as e:  # noqa: BLE001\n        raise RuntimeError(f\"Suche gescheitert ({e})\")\n"
     "    finally:\n        try:\n            conn.unbind()\n",
     "    except Exception as e:  # noqa: BLE001\n        raise RuntimeError(f\"Suche gescheitert ({e})\")\n"
     "    finally:\n        try:\n            pass\n", 1),
    ("Suche im ganzen Baum statt am Domaenenobjekt",
     "                    search_scope=ldap3.BASE,\n", "                    search_scope=\"SUBTREE\",\n", 1),
    ("gescheiterte Suche verschluckt (None statt Fehler)",
     "        raise RuntimeError(f\"Suche gescheitert ({e})\")\n", "        return None\n", 1),
    ("Funktion umbenannt -> konnte nicht laufen",
     "def sperrrichtlinie():\n", "def sperr_richtlinie():\n", 2),
]


def lauf(pfad: Path) -> int:
    return subprocess.run([sys.executable, str(WAECHTER), str(pfad)], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=120).returncode


def main() -> int:
    text = MODUL.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        kopie = Path(tmp) / "ldap_directory.py"
        kopie.write_text(text, encoding="utf-8")
        if lauf(kopie) != 0:
            print("ABBRUCH: Basislauf nicht gruen")
            return 2
        print("Basislauf gruen.\n")
        treffer = 0
        for name, alt, neu, erwartet in PROBEN:
            if text.count(alt) != 1:
                print(f"  ???  {name} – Anker {text.count(alt)}x gefunden")
                continue
            kopie.write_text(text.replace(alt, neu), encoding="utf-8")
            rc = lauf(kopie)
            treffer += rc == erwartet
            print(f"  {'OK  ' if rc == erwartet else 'ZAHN'} {name:<58} Exit {rc} (erwartet {erwartet})")
    print(f"\n{treffer}/{len(PROBEN)} Proben wie erwartet")
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
