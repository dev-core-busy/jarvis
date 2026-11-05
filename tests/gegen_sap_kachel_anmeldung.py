#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_sap_kachel_anmeldung.py?

Legt sabotierte KOPIEN von ``backend/sap_accounts.py`` bzw. ``backend/main.py``
in ein Wegwerf-Verzeichnis und gibt sie dem Waechter ueber
``SAP_KACHEL_MODUL`` / ``SAP_KACHEL_MAIN`` mit – die echten Dateien werden nie
angefasst, ein abgebrochener Lauf hinterlaesst also keinen Rueckstand.

Vorher ein Basislauf gegen die unveraenderten Dateien: ohne gruene Basis ist
keine Probe deutbar. Eine Probe "beisst", wenn der Waechter mit Exit 1 und
mindestens einem FAIL endet – Exit 2 ("konnte nicht laufen") zaehlt NICHT.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = HIER / "test_sap_kachel_anmeldung.py"
DATEIEN = {
    "modul": (ROOT / "backend" / "sap_accounts.py", "SAP_KACHEL_MODUL"),
    "main": (ROOT / "backend" / "main.py", "SAP_KACHEL_MAIN"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("Kennwort wird trotz Schalter verschluesselt gespeichert", "modul",
     "                if pflicht:\n                    sitzung_neu[f] = wert\n",
     "                if False:\n                    sitzung_neu[f] = wert\n"),
    ("Kennwort-Rest von vorher bleibt beim Speichern liegen", "modul",
     "        for f in GEHEIMFELDER:\n            k.pop(f + \"_enc\", None)\n",
     "        pass\n"),
    ("Aufloesung ignoriert den Schalter (Rueckfall auf Sammelzugang)", "modul",
     "    if kachel_pflicht():\n        return _aufloesen_kachel(un, trotz_aussetzer)\n",
     ""),
    ("ohne Anmeldung wird trotzdem verbunden", "modul",
     "    if not _sitzung_holen(un):\n        return _kein_zugang(un, \"Fuer SAP ist eine Anmeldung noetig. \" + ANMELDEN_TEXT)\n",
     ""),
    ("Client liest das Kennwort von der Platte statt aus der Anmeldung", "modul",
     "    if kachel_pflicht(c):\n        # Nur die Anmeldung aus der Kachel",
     "    if False:\n        # Nur die Anmeldung aus der Kachel"),
    ("Einschalten entfernt keine Kennwoerter", "modul",
     "        for f in weg:\n            del k[f]\n",
     "        for f in weg:\n            pass\n"),
    ("Anmeldung laeuft nie ab", "modul",
     "    if float(s.get(\"bis\") or 0) < time.time():\n",
     "    if False:\n"),
    ("Anmeldefehler beendet die Anmeldung nicht", "modul",
     "        if anmeldefehler and kachel_pflicht() and sitzung_beenden(un):\n",
     "        if False:\n"),
    ("Abgelehntes Speichern meldet trotzdem an", "modul",
     "    if pflicht:\n        # Kein Kennwort auf der Platte",
     "    if pflicht:\n        _sitzung_setzen(un, {g: felder[g] for g in GEHEIMFELDER if felder.get(g)})\n"
     "        # Kein Kennwort auf der Platte"),
    ("Geheimfelder werden nur VOR dem Behalten geleert", "main",
     "    if sap_kachel:\n        # NACH dem Behalten: das setzt leere Geheimfelder wieder ein.\n"
     "        for _f in _sapacc.GEHEIMFELDER:\n            body[_f] = \"\"\n",
     ""),
    ("Einschalten ruft kennwoerter_entfernen nicht", "main",
     "            _n = _sapacc.kennwoerter_entfernen()\n",
     "            _n = 0\n"),
    ("Kennwort-Abfrage auch fuer nie erfolgreich verbundene Zugaenge", "modul",
     "    if not int(k.get(\"letzter_erfolg\", 0) or 0):\n        return {}\n", ""),
    ("Kennwort-Abfrage trotz laufender Anmeldung", "modul",
     "    if not un or \":\" in un or _sitzung_holen(un):\n",
     "    if not un or \":\" in un:\n"),
    ("Status-Endpunkt liefert keine Anmeldekarte", "main",
     "        anmeldung = sap_accounts.anmeldung_anbieten(user) if kachel else {}\n",
     "        anmeldung = {}\n"),
    ("kennwort_gespeichert meldet immer 'nein'", "modul",
     "    return any((k.get(f + \"_enc\") or \"\").strip() for f in GEHEIMFELDER)\n",
     "    return False\n"),
    ("Admin-Liste ohne Angabe 'Kennwort gespeichert'", "main",
     "                \"kennwort_gespeichert\": sap_accounts.kennwort_gespeichert(un),\n", ""),
    ("Jarvis-Abmeldung laesst die SAP-Anmeldung stehen", "main",
     "        _sapacc.sitzung_beenden(user)\n",
     "        pass\n"),
]


def lauf(umgebung: dict) -> tuple:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **umgebung)
    r = subprocess.run([sys.executable, str(WAECHTER)], cwd=str(ROOT), env=env,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None), r.stdout + r.stderr


def main() -> int:
    nicht_gedeckt = {p[1] for p in PROBEN} - set(DATEIEN)
    if nicht_gedeckt:
        print(f"ABBRUCH: Proben auf unbekannte Dateien: {nicht_gedeckt}")
        return 2
    code, fails, aus = lauf({})
    if code != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, FAIL {fails})")
        print(aus[-2000:])
        return 2
    print(f"Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_sapkachel_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??  {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
                stumm += 1
                continue
            ziel = Path(tmp) / f"probe{i}_{quelle.name}"
            ziel.write_text(text.replace(alt, neu), encoding="utf-8")
            code, fails, aus = lauf({var: str(ziel)})
            if code == 1 and fails:
                print(f"  BEISST {i:2d} {name} ({fails} FAIL)")
            else:
                stumm += 1
                print(f"  STUMM  {i:2d} {name} (Exit {code}, FAIL {fails})")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
