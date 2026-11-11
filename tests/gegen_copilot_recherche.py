#!/usr/bin/env python3
"""Gegenproben zu ``tests/test_copilot_recherche.py``.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der Waechter das
meldet. Ein Waechter, dessen Zusagen auch ohne den Fix gruen bleiben, ist kein
Beweis, sondern ein Testmangel (Register).

WARUM HIER DATEIEN GEPATCHT WERDEN
----------------------------------
``gegen_google_geheimnisse.py`` sabotiert im SPEICHER und laesst damit nach
einem ``kill -9`` keinen Rueckstand. Das geht hier nur fuer ``backend.sandbox``
– der Waechter prueft ausserdem den QUELLTEXT von ``agent.py`` und ``main.py``
am Syntaxbaum und laedt das Skill-Modul selbst aus dem Dateipfad. Beides ist im
Speicher nicht erreichbar.

Deshalb das aeltere Hausrezept, vollstaendig:

* **Sicherung auf Platte VOR der ersten Probe**, Wiederherstellung nach jeder,
  danach **md5-Vergleich** – nicht "angenommen, es hat geklappt".
* **Laufmarke**: bleibt sie nach einem Abbruch liegen, nimmt der naechste
  Start den Rueckstand zurueck. Ein Start-``zurueck()`` OHNE Marke waere
  gefaehrlich – es stellte den Stand eines frueheren Laufs her und machte
  Arbeit zwischen zwei Laeufen zunichte (Register).
* **Die Dateiliste wird als REGEL geprueft**, nicht gepflegt: eine Probe, deren
  Datei nicht gesichert wird, bricht den Harness mit Exit 2 ab. Genau diese
  Liste ist hier schon zweimal auseinandergelaufen.
* **``PYTHONDONTWRITEBYTECODE=1``**: Python haelt eine ``.pyc`` fuer gueltig,
  wenn mtime-SEKUNDE und GROESSE passen. Mehrere Sabotagen hier tauschen
  gleich lange Teile – ohne das laedt ein spaeterer Lauf die Sabotage bei
  byte-gleicher Quelle.

GEMESSEN WIRD Exit-Code UND die gemeinte FAIL-Zeile. Ein Exit 1 allein koennte
ein Absturz sein, und ein Lauf ohne Bilanzzeile ist von "bestanden" nicht zu
unterscheiden. Ein Abbruch mit Exit 2 ("konnte nicht laufen") zaehlt
ausdruecklich NICHT als Biss.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_copilot_recherche.py"
SICHERUNG = Path.home() / ".jarvis-gegen-copilot"
MARKE = SICHERUNG / "LAUF_AKTIV"

SKILL = "skills/copilot/main.py"
CLIENT = "backend/copilot_client.py"
AGENT = "backend/agent.py"
MAIN = "backend/main.py"
SANDBOX = "backend/sandbox.py"

DATEIEN = (SKILL, CLIENT, AGENT, MAIN, SANDBOX)

# (Name, Datei, alt, neu, erwartete FAIL-Zeile)
PROBEN: list[tuple[str, str, str, str, str]] = [
    ("Internet-Freigabe wird nicht mehr ausgewertet",
     SKILL,
     "        return bool(m._user_has_internet_access(benutzer))",
     "        return True",
     "kein einziger Graph-Aufruf"),

    ("Benutzer wird ein Werkzeug-Argument",
     SKILL,
     '                "nur_web": {',
     '                "benutzer": {\n'
     '                    "type": "STRING",\n'
     '                    "description": "Konto",\n'
     '                },\n'
     '                "nur_web": {',
     "keines der Konto-Felder im Schema"),

    ("Kuerzungshinweis wandert hinter den Text",
     SKILL,
     '        teile.append(f"[Gekuerzt: {MAX_ANTWORT} von {len(text)} Zeichen "\n'
     '                     f"gezeigt. Stelle eine engere Frage, wenn der Rest "\n'
     '                     f"gebraucht wird.]")\n'
     '        text = text[:MAX_ANTWORT]\n'
     '    teile.append(text)',
     '        text = text[:MAX_ANTWORT]\n'
     '        teile.append(text)\n'
     '        teile.append(f"[Gekuerzt: {MAX_ANTWORT} von {len(text)} Zeichen "\n'
     '                     f"gezeigt.]")\n'
     '    else:\n'
     '        teile.append(text)',
     "der Hinweis steht VOR dem gekuerzten Text"),

    ("fehlende Quellen werden nicht mehr gemeldet",
     SKILL,
     '        teile.append("Copilot hat zu dieser Antwort keine Quellen genannt - "\n'
     '                     "sie ist damit nicht nachpruefbar.")',
     "        pass",
     "nicht nachpruefbar"),

    ("isWebEnabled wird nicht gesendet",
     CLIENT,
     '                "contextualResources": {"webContext": {"isWebEnabled": bool(web)}},',
     "",
     "nur_web=False sendet isWebEnabled=false"),

    ("ein Pflicht-Scope faellt weg",
     CLIENT,
     '    "ChannelMessage.Read.All",\n',
     "",
     "genau die sieben Pflicht-Scopes"),

    ("trennen leert den Eintrag statt ihn zu entfernen",
     CLIENT,
     "        _sichere(benutzer, None)\n        return True",
     "        _sichere(benutzer, {})\n        return True",
     "der getrennte Eintrag ist ENTFERNT, nicht geleert"),

    ("_antwort_lesen nimmt die eigene Frage als Antwort",
     CLIENT,
     "        if eigene and t.strip() == eigene:\n"
     "            continue\n",
     "",
     "Antwort ohne Text: Meldung, nicht die Frage als Ergebnis"),

    ("_antwort_lesen greift die letzte Nachricht per Index",
     CLIENT,
     "    for m in nachrichten:\n"
     "        if not isinstance(m, dict):\n"
     "            continue",
     "    for m in [nachrichten[-1]]:\n"
     "        if not isinstance(m, dict):\n"
     "            continue",
     "ohne messages: Meldung statt Wurf"),

    ("die Dispatch-Bindung wird entfernt",
     AGENT,
     '                    _cp_token = _cpcv.set(_uname or "")',
     "                    pass",
     "und ruft darauf .set() auf"),

    ("ein Endpunkt nimmt den Benutzer aus dem Rumpf",
     MAIN,
     'async def copilot_trennen(user: str = Depends(require_auth)):',
     'async def copilot_trennen(user: str = Depends(require_auth), benutzer: str = ""):',
     "copilot_trennen: genau ein Parameter"),

    # ⚠ ZWEI PROBEN, NICHT EINE: der Pfad steht in ZWEI Listen, und der Anker
    # `"data/copilot_auth",` allein kommt damit zweimal vor – die erste
    # Fassung dieser Probe hat der Harness deshalb zu Recht als "nicht
    # deutbar" gemeldet statt sie als Biss zu zaehlen. Jeder Anker nimmt die
    # Zeile DAVOR mit und trifft damit genau eine Liste.
    ("data/copilot_auth faellt aus _APP_DENY_REL (Dateiwerkzeuge)",
     SANDBOX,
     '    # (genau daran ist die Google-Sperrliste 2026-11-06 gescheitert).\n'
     '    "data/copilot_auth",\n',
     "",
     "gesperrt: eine kuenftige, heute unbekannte Datei im Verzeichnis"),

    ("data/copilot_auth faellt aus PRIVATE_DIRS (Verzeichnis-Rechte)",
     SANDBOX,
     '                # Microsoft-Graph-Refresh-Token je Benutzer (siehe _APP_DENY_REL)\n'
     '                "data/copilot_auth",\n',
     "",
     "Verzeichnis data/copilot_auth auf 0750"),

    ("die Datei faellt aus PRIVATE_FILES_STRENG",
     SANDBOX,
     '                        "data/copilot_auth/tokens.json")',
     "                        )",
     "data/copilot_auth/tokens.json auf 0600"),

    ("die Shell-Sperre faellt weg",
     SANDBOX,
     "    r'/copilot_auth\\b|'",
     "    r''",
     "gesperrt: cd data/copilot_auth && cat tokens.json"),
]


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern() -> dict[str, str]:
    """Jede Datei, die eine Probe anfasst – IMMER neu, nicht nur wenn sie fehlt.

    Eine vorhandene Sicherung nicht zu erneuern stellt beim zweiten Lauf einen
    veralteten Stand her und macht fertige Arbeit zunichte (Register). Der
    Basislauf ist ohnehin gruen geprueft, also ist der heutige Stand der
    richtige Sicherungsstand.
    """
    SICHERUNG.mkdir(parents=True, exist_ok=True)
    SICHERUNG.chmod(0o700)
    summen = {}
    for rel in DATEIEN:
        quelle = ROOT / rel
        ziel = SICHERUNG / rel.replace("/", "__")
        shutil.copy2(quelle, ziel)
        summen[rel] = _md5(quelle)
    return summen


def zurueck(summen: dict[str, str]) -> list[str]:
    """Alles wiederherstellen und die Byte-Gleichheit NACHSEHEN."""
    schlecht = []
    for rel in DATEIEN:
        quelle = SICHERUNG / rel.replace("/", "__")
        ziel = ROOT / rel
        if not quelle.exists():
            schlecht.append(f"{rel}: keine Sicherung")
            continue
        shutil.copy2(quelle, ziel)
        if summen and _md5(ziel) != summen.get(rel):
            schlecht.append(f"{rel}: md5 weicht nach dem Zuruecklegen ab")
    return schlecht


def lauf() -> tuple[int, str]:
    umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([sys.executable, str(WAECHTER)],
                       capture_output=True, text=True, timeout=300,
                       cwd=str(ROOT), env=umgebung)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    # REGEL statt Pflege: jede Probe muss eine gesicherte Datei anfassen.
    fehlend = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlend:
        print(f"ABBRUCH (Exit 2): Proben fassen ungesicherte Dateien an: "
              f"{sorted(fehlend)}")
        return 2

    # Rueckstand eines abgeschossenen Laufs zuruecknehmen – nur mit Marke.
    if MARKE.exists():
        print("! Laufmarke gefunden – nehme den Rueckstand des letzten Laufs "
              "zurueck")
        schlecht = zurueck({})
        if schlecht:
            print(f"ABBRUCH (Exit 2): Rueckstand nicht ruecknehmbar: {schlecht}")
            return 2
        MARKE.unlink()

    print("0. Basislauf muss GRUEN sein – ohne ihn ist keine Gegenprobe "
          "deutbar")
    code, ausgabe = lauf()
    bilanz = re.search(r"(\d+) OK, (\d+) FAIL", ausgabe)
    if code != 0 or not bilanz or bilanz.group(2) != "0":
        print(f"ABBRUCH (Exit 2): Basislauf nicht gruen (Exit {code}, "
              f"Bilanz {bilanz.group(0) if bilanz else 'FEHLT'})")
        print(ausgabe[-1500:])
        return 2
    basis_ok = int(bilanz.group(1))
    print(f"   Basis: {basis_ok} OK, 0 FAIL, Exit 0")

    summen = sichern()
    MARKE.write_text("laeuft\n", encoding="utf-8")
    beissen = stumm = kaputt = 0
    try:
        for nr, (name, rel, alt, neu, erwartet) in enumerate(PROBEN, 1):
            ziel = ROOT / rel
            text = ziel.read_text("utf-8")
            if text.count(alt) != 1:
                print(f"{nr}. {name}\n   ABBRUCH-PROBE: der Anker kommt "
                      f"{text.count(alt)}x in {rel} vor (erwartet genau 1) – "
                      f"die Sabotage traefe die falsche Stelle")
                kaputt += 1
                continue
            ziel.write_text(text.replace(alt, neu), "utf-8")
            try:
                code, ausgabe = lauf()
            finally:
                schlecht = zurueck(summen)
                if schlecht:
                    print(f"ABBRUCH (Exit 2): Wiederherstellung misslungen: "
                          f"{schlecht}")
                    return 2
            bilanz = re.search(r"(\d+) OK, (\d+) FAIL", ausgabe)
            getroffen = erwartet in ausgabe
            if code == 2:
                # "Konnte nicht laufen" ist KEIN Biss – und wenn eine
                # erwartbare Produktaenderung hier landet, ist der Guard im
                # Waechter zu scharf (Register).
                print(f"{nr}. {name}\n   ABBRUCH im Waechter (Exit 2) – das "
                      f"ist kein Biss, sondern ein zu scharfer Guard")
                kaputt += 1
            elif code == 1 and bilanz and getroffen:
                print(f"{nr}. {name}\n   BEISST: Exit 1, {bilanz.group(2)} "
                      f"FAIL, gemeinte Zeile dabei")
                beissen += 1
            elif code == 1 and bilanz:
                print(f"{nr}. {name}\n   FAIL, aber die GEMEINTE Zeile fehlt "
                      f"({erwartet!r}) – die Probe trifft eine andere Stelle")
                stumm += 1
            elif not bilanz:
                print(f"{nr}. {name}\n   KEINE BILANZ (Exit {code}) – der "
                      f"Waechter ist abgebrochen, nicht fehlgeschlagen")
                kaputt += 1
            else:
                print(f"{nr}. {name}\n   STUMM: Exit {code}, der Waechter "
                      f"meldet nichts")
                stumm += 1
    finally:
        schlecht = zurueck(summen)
        if MARKE.exists():
            MARKE.unlink()
        if schlecht:
            print(f"ABBRUCH (Exit 2): Rueckstand im Arbeitsbaum: {schlecht}")
            return 2

    print(f"\n{beissen} von {len(PROBEN)} Proben beissen, {stumm} stumm, "
          f"{kaputt} nicht deutbar")
    return 0 if (beissen == len(PROBEN)) else 1


if __name__ == "__main__":
    sys.exit(main())
