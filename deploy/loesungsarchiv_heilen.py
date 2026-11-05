#!/usr/bin/env python3
"""Loesungsarchiv: Altbestand von Python-Text auf Zeilen umstellen.

Bis 2026-11-05 landete eine Loesung, die das Modell als Liste lieferte, als
``['1. …', '2. …']`` im Stand und von dort in der Wissensdatenbank. Neue Antworten
sind seitdem richtig (``loesungsarchiv._als_text``); dieses Skript holt den Bestand
nach. Die Umwandlung selbst steht in ``loesungsarchiv.bestand_heilen`` und wird hier
nicht nachgebaut.

Auf dem Server, als Dienstbenutzer mit dem Hauptschluessel:

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python deploy/loesungsarchiv_heilen.py
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python deploy/loesungsarchiv_heilen.py --anwenden

Der Trockenlauf ist die Vorgabe. ``--anwenden`` legt neben dem Stand eine Sicherung
an. Die Dateien in der Wissensdatenbank und der Index folgen im naechsten Lauf.

⚠ KEIN ROOT OHNE ``als_dienst.sh``: die Sperrdatei gehoerte sonst root, und der
Dienst kaeme nicht mehr an sie heran.

Ob ein Lauf aktiv ist, entscheidet die Dateisperre in ``bestand_heilen``. Das Skript
fragt den Dienst nicht: auf einem Server mit Zwei-Faktor-Pflicht wuerde ein selbst
ausgestelltes Token an der Admin-Schnittstelle abgewiesen (ECHT 2026-11-05).

Exit: 0 fertig · 2 konnte nicht laufen · 3 ein Lauf ist aktiv (nichts geschrieben).
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("JARVIS_DIR", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True


def main() -> int:
    arg = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    arg.add_argument("--anwenden", action="store_true",
                     help="wirklich schreiben (sonst nur zaehlen)")
    anwenden = arg.parse_args().anwenden

    from backend import loesungsarchiv as la
    try:
        erg = la.bestand_heilen(anwenden=anwenden)
    except la.LaufAktiv as e:
        print(f"ABBRUCH: {e}")
        return 3
    except la.ArchivFehler as e:
        print(f"ABBRUCH: {e}")
        return 2

    print(("Geheilt: " if anwenden else "Wuerde heilen: ") + f"{len(erg['geheilt'])} Eintraege, "
          f"davon {erg['veroeffentlicht']} in der Wissensdatenbank")
    print(f"Nicht lesbar (bleiben stehen): {len(erg['unlesbar'])}"
          + (" – " + ", ".join(erg["unlesbar"][:10]) if erg["unlesbar"] else ""))
    if not anwenden:
        print("Trockenlauf: nichts geschrieben. Zum Schreiben: --anwenden")
        try:
            if la.sperre_belegt():
                print("Hinweis: gerade ist ein Lauf aktiv, --anwenden wuerde abbrechen.")
        except OSError as e:
            print(f"Hinweis: Sperrdatei nicht nutzbar ({e}), --anwenden wuerde abbrechen.")
        return 0
    if erg["sicherung"]:
        print(f"Sicherung: {la._wurzel() / erg['sicherung']}")
        print("Die Dateien in der Wissensdatenbank und der Index folgen im naechsten Lauf.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
