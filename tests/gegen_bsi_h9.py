#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_h9.py (+ test_bsi_h9_ui.js): beisst der Waechter?

Jede Probe dreht EINEN Teil des H9-Fixes zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Laeuft ohne
Bytecode (PYTHONDONTWRITEBYTECODE=1) und mit dem venv-Python, weil der
Waechter einen echten Agentenlauf macht.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.

    venv/bin/python tests/gegen_bsi_h9.py
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_bsi_h9.py"
UI = ROOT / "tests" / "test_bsi_h9_ui.js"
WI = "backend/wirkung.py"
AG = "backend/agent.py"
MA = "backend/main.py"
CJ = "frontend/js/chat.js"
BJ = "frontend/js/bestaetigung.js"
PY = str(ROOT / "venv" / "bin" / "python") if (ROOT / "venv" / "bin" / "python").exists() \
    else sys.executable

PROBEN = [
    # (name, datei, alt, neu) – Proben an Frontend-Dateien pruefen den UI-Waechter
    ("Tor im Dispatch entfernt", AG,
     "                if _klasse:\n                    _nein = await _wirkung.freigabe(name, args, _klasse)\n",
     "                if False:\n                    _nein = await _wirkung.freigabe(name, args, _klasse)\n"),
    ("Sandbox-Angabe immer wahr", AG,
     "                    sandbox=bool(exec_args.get('_sandbox_user')),\n",
     "                    sandbox=True,\n"),
    ("Shell ohne Sandbox fragt nicht", WI,
     "        return None if sandbox else SHELL\n", "        return None\n"),
    ("email_senden nicht eingestuft", WI,
     "    \"email_senden\": AUSSEN,\n", ""),
    ("Papierkorb-Verschieben nicht erkannt", WI,
     "    return LOESCHEN if _PAPIERKORB.search(ziel) else None\n", "    return None\n"),
    ("MCP ohne Angabe gilt als harmlos", WI,
     "    elif fremd:\n        return AUSSEN\n", "    elif fremd:\n        return None\n"),
    ("scheiternde Einstufung fail-open", WI,
     "            # unbekannt heisst hier: fragen.\n            return AUSSEN\n",
     "            # unbekannt heisst hier: fragen.\n            return None\n"),
    ("Kanal wird nie gelesen", WI,
     "    kanal = kanal_cv.get()\n", "    kanal = None\n"),
    ("Client ohne Dialog darf trotzdem", WI,
     "    if not kanal.kann_bestaetigen or kanal.ws is None:\n", "    if kanal.ws is None:\n"),
    ("Frist gilt als Freigabe", WI,
     "            return hinweis_frist(name)\n", "            return None\n"),
    ("fremder Benutzer darf freigeben", WI,
     "        if username != soll:\n", "        if False:\n"),
    ("jeder wahre Wert gibt frei", WI,
     "    eintrag.zukunft.set_result(erlaubt is True)\n",
     "    eintrag.zukunft.set_result(bool(erlaubt))\n"),
    ("keine Quittung an die Karte", WI,
     "        if erledigt_grund != \"nicht_zustellbar\":\n", "        if False:\n"),
    ("Anfrage bleibt nach Ende offen", WI,
     "        _offen.pop(kennung, None)\n", "        pass\n"),
    ("App gilt als dialogfaehig", MA,
     "        _kann_bestaetigen = msg.get(\"bestaetigung\") is True\n",
     "        _kann_bestaetigen = True\n"),
    ("Antwort-Benutzer aus der Nachricht", MA,
     "        _wirkung.antwort(str(msg.get(\"id\") or \"\"), _ws_usernames.get(id(ws), \"\"),\n",
     "        _wirkung.antwort(str(msg.get(\"id\") or \"\"), str(msg.get(\"user\") or \"\"),\n"),
    ("Kanal je Lauf nicht gesetzt", AG,
     "        if bestaetigung is not None:\n            _kanal_token = _wirkung.kanal_cv.set(",
     "        if False:\n            _kanal_token = _wirkung.kanal_cv.set("),
    ("Browser-Chat sagt bestaetigung nicht", CJ,
     "        const msg = { type: 'task', text: finalText, lang: window._lang || 'de', bestaetigung: true };\n",
     "        const msg = { type: 'task', text: finalText, lang: window._lang || 'de' };\n"),
    ("Karte per innerHTML (XSS)", BJ,
     "                dl.appendChild(_el('dd', null, String(paar[1])));\n",
     "                var dd = _el('dd'); dd.innerHTML = String(paar[1]); dl.appendChild(dd);\n"),
    ("Knoepfe nach dem Klick nicht gesperrt (Doppelklick)", BJ,
     "            ja.disabled = true;\n            nein.disabled = true;\n            status.textContent = erlaubt\n",
     "            status.textContent = erlaubt\n"),
    ("Server-Quittung ueberschreibt den Status nicht", BJ,
     "        if (st) {\n            st.textContent = T('bestaetigung.status.' + grund,\n",
     "        if (st && !st.textContent) {\n            st.textContent = T('bestaetigung.status.' + grund,\n"),
    ("ohne Modul wird gewartet statt abgelehnt", CJ,
     "                    wsSend({ type: 'bestaetigung_antwort', id: msg.id, erlaubt: false });\n", ""),
]

DATEIEN = [WI, AG, MA, CJ, BJ, "tests/test_bsi_h9.py", "tests/test_bsi_h9_ui.js"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    """Beide Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in (([PY, str(WAECHTER)], r"Ergebnis: (\d+) bestanden, (\d+) fehlgeschlagen"),
                        (["node", str(UI)], r"Ergebnis: (\d+) OK, (\d+) FAIL")):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=600, cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            # Ein haengender Waechter ist "konnte nicht laufen" – das Harness
            # darf daran nicht selbst sterben (2026-10-04 so passiert).
            return -1, "timeout"
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, r.returncode
        summe += int(m.group(2))
    return summe, 0


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
                print("  BISS %-52s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-52s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
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
