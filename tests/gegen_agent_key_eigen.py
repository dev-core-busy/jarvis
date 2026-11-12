#!/usr/bin/env python3
"""Gegenprobe: beissen test_agent_key_eigen.py und test_agent_key_eigen_ui.js?

Legt den Waechtern sabotierte KOPIEN von backend/main.py bzw.
frontend/js/app.js vor (Argument, Wegwerf-Verzeichnis) – die echten Dateien
werden nie angefasst.
Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
PY_WAECHTER = HIER / "test_agent_key_eigen.py"
JS_WAECHTER = HIER / "test_agent_key_eigen_ui.js"
MAIN = ROOT / "backend" / "main.py"
APP = ROOT / "frontend" / "js" / "app.js"

# (Name, Datei, alt, neu, erwarteter Exit)
PROBEN = [
    ("Backend: Mindestlaenge weg", MAIN,
     "    if len(wert) < AGENT_KEY_MIN_LAENGE:\n",
     "    if False:\n", 1),
    ("Backend: Zeichenpruefung weg", MAIN,
     "    if not all(33 <= ord(c) <= 126 for c in wert):\n",
     "    if False:\n", 1),
    ("Backend: Duplikatpruefung weg", MAIN,
     "    andere.append(str(config.AGENT_API_KEY or \"\"))\n    roh = wert.encode(\"ascii\")\n",
     "    andere = []\n    roh = wert.encode(\"ascii\")\n", 1),
    ("Backend: Endpunkt speichert trotz Fehler", MAIN,
     "                if fehler:\n                    return JSONResponse({\"ok\": False, \"error\": fehler}, status_code=400)\n",
     "                pass\n", 1),
    ("Backend: Pruefung umbenannt -> konnte nicht laufen", MAIN,
     "def _agent_key_eigener_fehler(wert, keys: list, kid: str) -> str:\n",
     "def _agent_key_pruefen(wert, keys: list, kid: str) -> str:\n", 2),
    ("Frontend: Name wieder 130 px", APP,
     "esc(_tt('app.key_name', 'Name')) + '\" style=\"width:260px;\">'",
     "esc(_tt('app.key_name', 'Name')) + '\" style=\"width:130px;\">'", 1),
    ("Frontend: Auge-Klasse weg (pwreveal setzt zweites Auge)", APP,
     "'<button class=\"btn-icon btn-small ak-show ak-eye\"",
     "'<button class=\"btn-icon btn-small ak-show\"", 1),
    ("Frontend: Feld wieder readonly", APP,
     "'<input class=\"ak-key\" type=\"password\" value=\"\" autocomplete",
     "'<input class=\"ak-key\" type=\"password\" value=\"\" readonly autocomplete", 1),
    ("Frontend: unveraendert wird trotzdem gespeichert", APP,
     "                    if (!wert || wert === klar.get(id)) return;\n",
     "                    if (!wert) return;\n", 1),
    ("Frontend: Fehler wird nicht angezeigt", APP,
     "                                if (fehlerEl) fehlerEl.textContent = d.error || ",
     "                                if (false) fehlerEl.textContent = d.error || ", 1),
    ("Frontend: Kopieren nimmt den Feldinhalt", APP,
     "                const holen = () => klar.has(id) ? Promise.resolve(klar.get(id))\n",
     "                const holen = () => keyInput.value ? Promise.resolve(keyInput.value) : klar.has(id) ? Promise.resolve(klar.get(id))\n", 1),
]


def lauf(datei: Path, kopie: Path) -> int:
    if datei == MAIN:
        cmd = [sys.executable, str(PY_WAECHTER), str(kopie)]
    else:
        cmd = ["node", str(JS_WAECHTER), str(kopie)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT),
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                          timeout=180).returncode


def main() -> int:
    texte = {MAIN: MAIN.read_text(encoding="utf-8"), APP: APP.read_text(encoding="utf-8")}
    with tempfile.TemporaryDirectory() as tmp:
        kopien = {MAIN: Path(tmp) / "main.py", APP: Path(tmp) / "app.js"}
        for d, k in kopien.items():
            k.write_text(texte[d], encoding="utf-8")
            if lauf(d, k) != 0:
                print("ABBRUCH: Basislauf nicht gruen (%s)" % d.name)
                return 2
        print("Basislauf gruen.\n")
        treffer = 0
        for name, datei, alt, neu, erwartet in PROBEN:
            text = texte[datei]
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            kopien[datei].write_text(text.replace(alt, neu), encoding="utf-8")
            rc = lauf(datei, kopien[datei])
            kopien[datei].write_text(text, encoding="utf-8")
            treffer += rc == erwartet
            print("  %s %-62s Exit %d (erwartet %d)"
                  % ("OK  " if rc == erwartet else "ZAHN", name, rc, erwartet))
    print("\n%d/%d Proben wie erwartet" % (treffer, len(PROBEN)))
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
