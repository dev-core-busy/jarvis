#!/usr/bin/env python3
"""Gegenprobe zu tests/test_token_verbrauch.py: beisst der Waechter?

Jede Probe dreht EINE Zusage der Token-Erfassung zurueck, laesst den Waechter
laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach
Byte-Gleichheit aller Dateien per md5. Ohne Bytecode (Register: eine .pyc aus
derselben Sekunde laedt sonst die Sabotage nach).

NIE in einem Sammellauf mitlaufen lassen – sie patcht Produktdateien.

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
WAECHTER = ROOT / "tests" / "test_token_verbrauch.py"
TV = "backend/token_verbrauch.py"
LLM = "backend/llm.py"
AGENT = "backend/agent.py"
MAIN = "backend/main.py"
LR = "backend/log_retention.py"

PROBEN = [
    ("Provider werden nicht umhuellt", LLM,
     "        cls.generate_response = token_verbrauch.umhuellen(eigen)\n",
     "        pass\n"),
    ("auch Test-Attrappen werden umhuellt", LLM,
     "        if cls.__module__ != __name__:\n            return\n", ""),
    ("Herkunft erst in der Koroutine (Task-Grenze)", TV,
     '            "dienst": _herkunft(2),\n',
     '            "dienst": None,\n'),
    ("Cache-Tokens fehlen in der Eingabe", TV,
     '        zeile["ein"] = _zahl(usage.get("input_tokens")) + cl + cs\n',
     '        zeile["ein"] = _zahl(usage.get("input_tokens"))\n'),
    ("fehlende Zaehlung wird als 0 geschaetzt", TV,
     '        zeile["ein"] = None\n        zeile["aus"] = None\n',
     '        zeile["ein"] = 0\n        zeile["aus"] = 0\n'),
    ("Doppelzaehlung bei verschachtelter Huelle", TV,
     "        if _in_erfassung.get():\n",
     "        if False:\n"),
    ("Fehlschlag wird nicht erfasst", TV,
     "    if fehler:\n        zeile[\"f\"] = 1\n", ""),
    ("laufendes Werkzeug wird ignoriert", TV,
     '                    werkzeuge = ([kontext["werkzeug"]] if kontext["werkzeug"]\n'
     '                                 else _angeforderte_werkzeuge(resp))\n',
     '                    werkzeuge = _angeforderte_werkzeuge(resp)\n'),
    ("Benutzer nicht aus dem Lauf", TV,
     '    cv = getattr(ag, "_actor_cv", None) if ag else None\n',
     '    cv = None\n'),
    ("Kanal aus der Auftragsquelle ungekuerzt", TV,
     '                for trenner in (" ", "(", ":", "\'"):\n',
     '                for trenner in ():\n'),
    ("Benutzerfilter ohne Normierung", TV,
     '            filt[k] = _norm_user(v) if k == "benutzer" else str(v)\n',
     '            filt[k] = str(v)\n'),
    ("leerer Filterwert gilt als 'alle'", TV,
     '        if k in DIMENSIONEN and v is not None and v != "*":\n',
     '        if k in DIMENSIONEN and v:\n'),
    ("mehrere Werkzeuge doppelt gezaehlt (erster Wert)", TV,
     '        return ", ".join(sorted(w for w in werte if w))\n',
     '        return werte[0]\n'),
    ("Uebrige-Reihe faellt weg", TV,
     "    if rest:\n        n = len(achse)\n",
     "    if False:\n        n = len(achse)\n"),
    ("Optionen aus dem gefilterten Bestand", TV,
     "        for d in DIMENSIONEN:\n            for w in _schluessel(z, d):\n"
     "                optionen[d][w] = optionen[d].get(w, 0) + 1\n"
     "        if any(f not in _schluessel(z, d) for d, f in filt.items()):\n            continue\n",
     "        if any(f not in _schluessel(z, d) for d, f in filt.items()):\n            continue\n"
     "        for d in DIMENSIONEN:\n            for w in _schluessel(z, d):\n"
     "                optionen[d][w] = optionen[d].get(w, 0) + 1\n"),
    ("Schnitt-Datei wird nicht gefiltert", TV,
     "            if p.name > schnitt_datei:\n",
     "            if p.name >= schnitt_datei:\n"),
    ("Endpunkt fuer jeden Angemeldeten", MAIN,
     "async def api_logs_token_verbrauch(request: Request, user: str = Depends(require_local_auth)):\n",
     "async def api_logs_token_verbrauch(request: Request, user: str = Depends(require_auth)):\n"),
    ("Alterung nicht im Tageslauf", LR,
     '                     ("token_verbrauch", _prune_token_verbrauch)):\n',
     '                     ):\n'),
    ("Werkzeug bleibt nach dem Aufruf gesetzt", AGENT,
     "                    try:\n                        _tvw.werkzeug_cv.reset(_w_token)\n"
     "                    except Exception:  # noqa: BLE001\n                        pass\n", ""),
    ("Kanal wird nicht gesetzt", AGENT,
     '                           else _tv.kanal_cv.set(str(client_type or "browser")))\n',
     '                           else None)\n'),
]

DATEIEN = [TV, LLM, AGENT, MAIN, LR, "tests/test_token_verbrauch.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    py = ROOT / "venv" / "bin" / "python"
    r = subprocess.run([str(py if py.exists() else sys.executable), str(WAECHTER)],
                       capture_output=True, text=True, timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


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
