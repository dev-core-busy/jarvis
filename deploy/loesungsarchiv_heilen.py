#!/usr/bin/env python3
"""Loesungsarchiv: Altbestand von Python-Text auf Zeilen umstellen.

Bis 2026-11-05 landete eine Loesung, die das Modell als Liste lieferte, als
``['1. …', '2. …']`` im Stand und von dort in der Wissensdatenbank. Neue Antworten
sind seitdem richtig (``loesungsarchiv._als_text``); dieses Skript holt den Bestand
nach. Die Umwandlung selbst steht in ``loesungsarchiv.bestand_heilen`` und wird hier
nicht nachgebaut.

Auf dem Server, mit dem Hauptschluessel (das Token muss im Dienst gelten):

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python deploy/loesungsarchiv_heilen.py
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python deploy/loesungsarchiv_heilen.py --anwenden

Der Trockenlauf ist die Vorgabe. ``--anwenden`` legt neben dem Stand eine Sicherung
an. Die Dateien in der Wissensdatenbank und der Index folgen im naechsten Lauf.

Exit: 0 fertig · 2 konnte nicht laufen · 3 ein Lauf ist aktiv (nichts geschrieben,
bzw. nach dem Schreiben gestartet: dann Sicherung und Stand pruefen).
"""
import argparse
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("JARVIS_DIR", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

BASIS = os.environ.get("JARVIS_LOKAL_URL", "https://127.0.0.1")


def lauf_aktiv() -> bool:
    """Den LAUFENDEN Dienst fragen: ``_lauf_aktiv`` in diesem Prozess weiss nichts
    von dessen Lauf. Nicht feststellbar wirft – dann wird nicht geschrieben."""
    from backend import main as M
    token = M.generate_token(os.environ.get("CRON_TESTUSER") or "jarvis")
    anfrage = urllib.request.Request(BASIS + "/api/jira/admin/loesungsarchiv",
                                     headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(anfrage, context=ssl._create_unverified_context(),
                                timeout=60) as antwort:
        return bool(json.loads(antwort.read().decode()).get("laeuft"))


def main() -> int:
    arg = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    arg.add_argument("--anwenden", action="store_true",
                     help="wirklich schreiben (sonst nur zaehlen)")
    anwenden = arg.parse_args().anwenden

    from backend import loesungsarchiv as la
    if anwenden:
        try:
            if lauf_aktiv():
                print("ABBRUCH: ein Lauf ist aktiv, es wurde nichts geschrieben.")
                return 3
        except Exception as e:  # noqa: BLE001
            print(f"ABBRUCH: Zustand des Dienstes nicht feststellbar ({type(e).__name__}: {e}).")
            return 2
    try:
        erg = la.bestand_heilen(anwenden=anwenden)
    except la.ArchivFehler as e:
        print(f"ABBRUCH: {e}")
        return 2

    print(("Geheilt: " if anwenden else "Wuerde heilen: ") + f"{len(erg['geheilt'])} Eintraege, "
          f"davon {erg['veroeffentlicht']} in der Wissensdatenbank")
    print(f"Nicht lesbar (bleiben stehen): {len(erg['unlesbar'])}"
          + (" – " + ", ".join(erg["unlesbar"][:10]) if erg["unlesbar"] else ""))
    if not anwenden:
        print("Trockenlauf: nichts geschrieben. Zum Schreiben: --anwenden")
        return 0
    if erg["sicherung"]:
        print(f"Sicherung: {la._wurzel() / erg['sicherung']}")
        print("Die Dateien in der Wissensdatenbank und der Index folgen im naechsten Lauf.")
        try:
            if lauf_aktiv():
                print("WARNUNG: inzwischen laeuft ein Lauf – er kann den alten Stand "
                      "zurueckschreiben. Nach seinem Ende den Trockenlauf wiederholen.")
                return 3
        except Exception as e:  # noqa: BLE001
            print(f"WARNUNG: Zustand danach nicht feststellbar ({type(e).__name__}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
