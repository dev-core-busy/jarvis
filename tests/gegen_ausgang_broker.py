#!/usr/bin/env python3
"""Gegenprobe zu test_ausgang_broker.py: beisst der Waechter?

Jede Verfaelschung trifft eine KOPIE von backend/broker/ausgang.py bzw.
backend/broker/meta.py; der Waechter laeuft gegen die Kopie
(JARVIS_AUSGANG_BROKER_PRUEFLING / JARVIS_AUSGANG_META_PRUEFLING) und muss mit
Exit 1 rot werden. Die Repo-Dateien werden nie angefasst.
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
AUSGANG = REPO / "backend" / "broker" / "ausgang.py"
META = REPO / "backend" / "broker" / "meta.py"
WAECHTER = REPO / "tests" / "test_ausgang_broker.py"

# (Datei, Name, alt, neu)
VERFAELSCHUNGEN = [
    (AUSGANG, "Speichern ohne Pruefung",
     '    probe = pruefen(text)\n    if not probe.get("ok"):\n        return probe\n',
     '    probe = {"ok": True, "text": _normieren(text) or ""}\n'),
    (AUSGANG, "kein Zurueckschreiben nach Fehlschlag", '            _schreiben(KONF, alt)\n', '            pass\n'),
    (AUSGANG, "neue Datei bleibt nach Fehlschlag", '                KONF.unlink()\n', '                pass\n'),
    (AUSGANG, "Datei 0644 statt 0600", 'os.O_TRUNC, 0o600)', 'os.O_TRUNC, 0o644)'),
    (AUSGANG, "keine Groessengrenze",
     'if len(text) > MAX_ZEICHEN or text.count("\\n") > MAX_ZEILEN or "\\x00" in text:', 'if False:'),
    (AUSGANG, "verworfen und aufgezeichnet vermischt",
     'art = "drop" if "nft-aus-drop:" in z else ("frei" if "nft-aus-frei:" in z else "")',
     'art = "frei" if "nft-aus-" in z else ""'),
    (AUSGANG, "seltenste zuerst", 'key=lambda e: (-e["anzahl"], -e["zuletzt"])', 'key=lambda e: (e["anzahl"], -e["zuletzt"])'),
    (AUSGANG, "unlesbares Protokoll gilt als leer",
     '    if r.returncode not in (0, 1):\n        return [], False\n', '    if r.returncode not in (0, 1):\n        return [], True\n'),
    (AUSGANG, "Zeitraum ungedeckelt", 'max(1, min(MAX_STUNDEN, int(stunden)))', 'max(1, int(stunden))'),
    (AUSGANG, "Protokoll nur des laufenden Starts", '["journalctl", "_TRANSPORT=kernel",', '["journalctl", "-k",'),
    (AUSGANG, "Kontoname fehlt", '"benutzer": _name(uid) if uid else "",', '"benutzer": "",'),
    (META, "Speichern ohne Code",
     '        fehler = _nachweis(args, by, op, audit_key, peer)\n        if fehler:\n            return fehler\n        erg = ausgang.speichern',
     '        erg = ausgang.speichern'),
    (META, "Entfernen ohne Code",
     '        fehler = _nachweis(args, by, op, audit_key, peer)\n        if fehler:\n            return fehler\n        erg = ausgang.speichern',
     '        fehler = _nachweis(args, by, op, audit_key, peer) if aktion == "speichern" else None\n        if fehler:\n            return fehler\n        erg = ausgang.speichern'),
    (META, "kein Audit",
     '        policy.audit(by, op, audit_key, "executed" if erg.get("ok") else "fehler",\n                     rc=erg.get("rc"), detail=str(erg.get("meldung", ""))[:200], peer=peer)\n        return erg\n    # Schluessel',
     '        return erg\n    # Schluessel'),
]


def lauf(env_extra):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **env_extra)
    p = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True, timeout=600, env=env)
    return p.returncode, p.stdout


def main():
    for f in (AUSGANG, META, WAECHTER):
        if not f.is_file():
            print(f"ABBRUCH: {f} fehlt")
            return 2
    rc, aus = lauf({})
    if rc != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (rc={rc})\n{aus[-800:]}")
        return 2
    print("Basislauf gruen.")
    nicht = 0
    with tempfile.TemporaryDirectory() as d:
        for datei, name, alt, neu in VERFAELSCHUNGEN:
            text = datei.read_text()
            if text.count(alt) != 1:
                print(f"  ABBRUCH: Stelle fuer '{name}' nicht eindeutig ({text.count(alt)}x)")
                return 2
            kopie = Path(d) / datei.name
            kopie.write_text(text.replace(alt, neu))
            var = "JARVIS_AUSGANG_BROKER_PRUEFLING" if datei == AUSGANG else "JARVIS_AUSGANG_META_PRUEFLING"
            rc, aus = lauf({var: str(kopie)})
            if rc == 1:
                print(f"  ✓ {name}: erkannt ({aus.count('  FAIL ')} FAIL)")
            else:
                nicht += 1
                print(f"  ✗ {name}: NICHT erkannt (rc={rc})")
    print(f"\n{len(VERFAELSCHUNGEN) - nicht}/{len(VERFAELSCHUNGEN)} erkannt")
    return 1 if nicht else 0


if __name__ == "__main__":
    sys.exit(main())
