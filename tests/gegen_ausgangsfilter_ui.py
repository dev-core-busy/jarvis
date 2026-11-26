#!/usr/bin/env python3
"""Gegenprobe zu test_ausgangsfilter_ui.js: beisst der Waechter?

Jede Verfaelschung trifft eine KOPIE von frontend/js/ausgangsfilter.js; der
Waechter laeuft gegen die Kopie (JARVIS_AUSGANGSFILTER_PRUEFLING) und muss mit
Exit 1 rot werden. Die Repo-Datei wird nie angefasst.
Vorher muss der Basislauf gruen sein – sonst ist keine Gegenprobe deutbar.
Exit 0 = jede Verfaelschung erkannt, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
# Schreibschutz: kein Zurueckschreiben ueber fremde Aenderungen (Pflicht fuer
# jeden Harness). Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORIGINAL = REPO / "frontend" / "js" / "ausgangsfilter.js"
WAECHTER = REPO / "tests" / "test_ausgangsfilter_ui.js"

VERFAELSCHUNGEN = {
    "Notiz geht verloren": ("            if (r.notiz) aus.push('# ' + String(r.notiz).replace(/\\s*\\n\\s*/g, ' '));\n", ""),
    "Kopf geht verloren": ("        (stand.kopf || []).forEach(function (z) { aus.push(z); });\n", ""),
    "unbekannte Zeile faellt weg": ("            if (r.roh != null) { aus.push(r.roh); return; }", "            if (r.roh != null) { return; }"),
    "Pruefen fragt nach dem Code": ("            if (aktion !== 'pruefen') {\n", "            if (true) {\n"),
    "keine Rueckfrage": ("                if (!window.confirm(frage)) return;\n", ""),
    "Code wird nicht mitgeschickt": ("                body.nachweis = String(c).replace(/\\D/g, '');", "                body.nachweis = '';"),
    "leeres Feld wird gesendet": ("                if (leer) {\n", "                if (false) {\n"),
    "Loeschen verwirft Eingaben": ("                self._ausTabelle();\n                self._stand.zeilen.splice(i, 1);", "                self._stand.zeilen.splice(i, 1);"),
    "Vorschlag in Grossschrift": ("        var proto = String(tr.proto || '').toLowerCase();", "        var proto = String(tr.proto || '');"),
    "kein drehender Kreis": ("            if (art === 'laeuft') el.innerHTML = '<span class=\"jv-pkg-spin\"></span> ' + esc(text);\n            else el.textContent = text || '';",
                             "            el.textContent = text || '';"),
    "Sprachwechsel verwirft Bearbeitung": ("            Af._ausTabelle();\n            var st = $('af-status');", "            Af.zeigen(Af._daten);\n            var st = $('af-status');"),
    "Startzustand verkehrt": ("            teile.push(d.unit === 'enabled'", "            teile.push(d.unit !== 'enabled'"),
    "Entfernen immer sichtbar": ("            if (weg) weg.style.display = d && d.geladen ? '' : 'none';", "            if (weg) weg.style.display = '';"),
    "kein Neuladen nach Speichern": ("                  if (aktion !== 'pruefen' && d && d.ok) return self.laden();\n", ""),
}


def lauf(pruefling):
    env = dict(os.environ, JARVIS_AUSGANGSFILTER_PRUEFLING=str(pruefling))
    p = subprocess.run(["node", str(WAECHTER)], capture_output=True, text=True, timeout=300, env=env)
    return p.returncode, p.stdout


def main():
    if not ORIGINAL.is_file() or not WAECHTER.is_file():
        print("ABBRUCH: Original oder Waechter fehlt")
        return 2
    rc, aus = lauf(ORIGINAL)
    if rc != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (rc={rc})\n{aus[-800:]}")
        return 2
    print("Basislauf gruen.")
    text = ORIGINAL.read_text()
    nicht = 0
    with tempfile.TemporaryDirectory() as d:
        for name, (alt, neu) in VERFAELSCHUNGEN.items():
            if text.count(alt) != 1:
                print(f"  ABBRUCH: Stelle fuer '{name}' nicht eindeutig ({text.count(alt)}x)")
                return 2
            kopie = Path(d) / "ausgangsfilter.js"
            kopie.write_text(text.replace(alt, neu))
            rc, aus = lauf(kopie)
            if rc == 1:
                print(f"  ✓ {name}: erkannt ({aus.count('  FAIL ')} FAIL)")
            else:
                nicht += 1
                print(f"  ✗ {name}: NICHT erkannt (rc={rc})")
    print(f"\n{len(VERFAELSCHUNGEN) - nicht}/{len(VERFAELSCHUNGEN)} erkannt")
    return 1 if nicht else 0


if __name__ == "__main__":
    sys.exit(main())
