#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_persoenlich_schalter.py?

Kopiert ``backend/`` in ein Wegwerf-Verzeichnis, sabotiert dort je Probe EINE
Stelle und laesst den Waechter ueber ``PERS_ROOT`` gegen die Kopie laufen –
die echten Dateien werden nie angefasst, ein abgebrochener Lauf hinterlaesst
keinen Rueckstand. Vorher ein Basislauf gegen die unveraenderte Kopie: ohne
gruene Basis ist keine Probe deutbar.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = HIER / "test_persoenlich_schalter.py"

# (Name, Datei relativ zu backend/, alt, neu, Anzahl Treffer)
PROBEN = [
    ("Confluence: speichern ohne Sperre", "confluence_accounts.py",
     "    if not persoenlich_erlaubt():\n        raise ConfluenceKontoFehler(ABGESCHALTET_TEXT)\n\n    unbekannt",
     "\n    unbekannt", 1),
    ("Confluence: aufloesen ohne Schalter", "confluence_accounts.py",
     "    if not persoenlich_erlaubt():\n        # Ein Rest in der Datei",
     "    if False:\n        # Ein Rest in der Datei", 1),
    ("Confluence: testen ohne Sperre", "confluence_accounts.py",
     '    gruenfaerben."""\n    if not persoenlich_erlaubt():',
     '    gruenfaerben."""\n    if False:', 1),
    ("Confluence: alle_entfernen loescht nicht", "confluence_accounts.py",
     "        n = len(alle)\n        if n:\n            _speichern({})",
     "        n = len(alle)", 1),
    ("Confluence: zugang_info ohne Schalter", "confluence_accounts.py",
     '        "persoenlich_erlaubt": persoenlich_erlaubt(),', "", 1),
    ("Vorgabe kippt: Feld fehlt = verboten", "confluence_accounts.py",
     "return cfg.get(PERSOENLICH_SCHALTER) is not False",
     "return cfg.get(PERSOENLICH_SCHALTER) is True", 1),
    # SAP/VEMAS: ein zweiter Schalter darf sich nicht wieder einschleichen.
    ("SAP: speichern beachtet persoenliche_zugaenge wieder", "sap_accounts.py",
     "werden.\")\n\n    alle = _laden()\n    k = alle.get(un) or _leer(un)",
     "werden.\")\n    if skill_config().get(\"persoenliche_zugaenge\") is False:\n"
     "        raise SapKontoFehler(\"abgeschaltet\")\n"
     "    alle = _laden()\n    k = alle.get(un) or _leer(un)", 1),
    ("SAP: aufloesen faellt bei persoenliche_zugaenge auf den Sammelzugang", "sap_accounts.py",
     "        return _aufloesen_kachel(un, trotz_aussetzer)\n",
     "        return _aufloesen_kachel(un, trotz_aussetzer)\n"
     "    if skill_config().get(\"persoenliche_zugaenge\") is False:\n"
     "        return {\"client\": SapClient(), \"quelle\": QUELLE_SAMMEL, \"hinweis\": \"\",\n"
     "                \"benutzer\": un, \"ausgesetzt\": False}\n", 1),
    ("VEMAS: zugang_info meldet wieder einen Schalter", "vemas_accounts.py",
     '        "kachel_pflicht": pflicht,\n',
     '        "kachel_pflicht": pflicht,\n        "persoenlich_erlaubt": False,\n', 1),
    ("VEMAS: Kachelpflicht faellt auf den Sammelzugang zurueck", "vemas_accounts.py",
     "        return _aufloesen_kachel(un, trotz_aussetzer)\n",
     "        return {\"client\": sammel_client(), \"quelle\": QUELLE_SAMMEL, \"hinweis\": \"\",\n"
     "                \"benutzer\": un, \"ausgesetzt\": False}\n", 1),
    ("SAP: alle_entfernen loescht die Zugaenge nicht", "sap_accounts.py",
     "    if n or KONTEN_DATEI.exists():\n        _speichern({})\n    _SITZUNG.clear()\n",
     "    _SITZUNG.clear()\n", 1),
    ("VEMAS: alle_entfernen laesst Anmeldungen im Speicher", "vemas_accounts.py",
     "        _speichern({})\n    _SITZUNG.clear()\n    return n\n",
     "        _speichern({})\n    return n\n", 1),
]


def kopie() -> Path:
    ziel = Path(tempfile.mkdtemp(prefix="gegen-persoenlich-"))
    shutil.copytree(ROOT / "backend", ziel / "backend",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return ziel


def lauf(wurzel: Path):
    env = dict(os.environ, PERS_ROOT=str(wurzel), PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                       text=True, env=env, timeout=180)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


def main():
    basis = kopie()
    try:
        rc, fails = lauf(basis)
    finally:
        shutil.rmtree(basis, ignore_errors=True)
    if rc != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {rc}, FAIL {fails})")
        sys.exit(2)
    print("Basislauf gruen.\n")
    stumm = 0
    for i, (name, datei, alt, neu, anzahl) in enumerate(PROBEN, 1):
        w = kopie()
        try:
            p = w / "backend" / datei
            t = p.read_text(encoding="utf-8")
            if t.count(alt) != anzahl:
                print(f"  ANKER  {i:2} {name} – Anker {t.count(alt)}x statt {anzahl}x")
                stumm += 1
                continue
            p.write_text(t.replace(alt, neu), encoding="utf-8")
            rc, fails = lauf(w)
        finally:
            shutil.rmtree(w, ignore_errors=True)
        if rc == 1 and fails:
            print(f"  BEISST {i:2} {name} ({fails} FAIL)")
        else:
            stumm += 1
            print(f"  STUMM  {i:2} {name} (Exit {rc}, FAIL {fails})")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    sys.exit(1 if stumm else 0)


if __name__ == "__main__":
    main()
