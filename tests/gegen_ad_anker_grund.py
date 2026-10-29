#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_ad_anker_grund.py ueberhaupt?

Legt dem Waechter sabotierte KOPIEN von backend/ldap_tls.py vor (Argument,
Wegwerf-Verzeichnis) – die echte Datei wird nie angefasst.
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
WAECHTER = HIER / "test_ad_anker_grund.py"
MODUL = HIER.parent / "backend" / "ldap_tls.py"

PROBEN = [
    ("Schaerfung weg: Urgrund wird durchgereicht",
     "    verankert = str((eintrag or {}).get(\"fingerprint\") or \"\")\n",
     "    return str(fehler)\n    verankert = str((eintrag or {}).get(\"fingerprint\") or \"\")\n", 1),
    ("verbinden() ruft den Grund gar nicht mehr",
     "            raise TlsFehler(_anker_grund(host, port, ldaps, eintrag, e, timeout)) from None\n",
     "            raise\n", 1),
    ("Mess-Aufbau sendet Anmeldedaten mit",
     "        conn = _oeffnen(host, port, ldaps, _tls(host, port, None, pruefen=False),\n"
     "                        timeout=timeout)\n",
     "        conn = _oeffnen(host, port, ldaps, _tls(host, port, None, pruefen=False),\n"
     "                        \"wer\", \"geheim\", timeout=timeout)\n", 1),
    ("Mess-Aufbau wird GEPRUEFT (scheitert damit genauso)",
     "        conn = _oeffnen(host, port, ldaps, _tls(host, port, None, pruefen=False),\n"
     "                        timeout=timeout)\n",
     "        conn = _oeffnen(host, port, ldaps, _tls(host, port, None, pruefen=True),\n"
     "                        timeout=timeout)\n", 1),
    ("Vergleich weg: Erneuerung wird auch bei gleichem Zertifikat behauptet",
     "    if not vorgelegt or not verankert or vorgelegt == verankert:\n",
     "    if not vorgelegt or not verankert:\n", 1),
    ("passender Anker faellt wieder in die Uebergangsfrist",
     "        if sap_cert.passt(eintrag, host, port):\n",
     "        if False and sap_cert.passt(eintrag, host, port):\n", 1),
    ("Funktion umbenannt -> konnte nicht laufen",
     "def _anker_grund(host: str, port: int, ldaps: bool, eintrag: dict | None,\n",
     "def _anker_begruendung(host: str, port: int, ldaps: bool, eintrag: dict | None,\n", 2),
]


def lauf(pfad: Path) -> int:
    return subprocess.run([sys.executable, str(WAECHTER), str(pfad)], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=180).returncode


def main() -> int:
    text = MODUL.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        kopie = Path(tmp) / "ldap_tls.py"
        kopie.write_text(text, encoding="utf-8")
        if lauf(kopie) != 0:
            print("ABBRUCH: Basislauf nicht gruen")
            return 2
        print("Basislauf gruen.\n")
        treffer = 0
        for name, alt, neu, erwartet in PROBEN:
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            kopie.write_text(text.replace(alt, neu), encoding="utf-8")
            rc = lauf(kopie)
            treffer += rc == erwartet
            print("  %s %-62s Exit %d (erwartet %d)"
                  % ("OK  " if rc == erwartet else "ZAHN", name, rc, erwartet))
    print("\n%d/%d Proben wie erwartet" % (treffer, len(PROBEN)))
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
