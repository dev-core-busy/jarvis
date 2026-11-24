#!/usr/bin/env python3
"""Gegenprobe zu tests/test_cve_bedrohung.py (+ KEV/EPSS-Teil von
tests/test_cve_anzeige_ui.js): beissen die Waechter?

Jede Probe dreht EINE Zusage der Bedrohungslage zurueck, laesst die Waechter
laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach
Byte-Gleichheit aller Dateien per md5, ohne Bytecode, mit Laufmarke (ein
abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

⚠ NIE in einem Sammellauf mitlaufen lassen – die Proben patchen Dateien.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_cve_bedrohung.laufmarke"

CP = "backend/cve_pruefung.py"
SP = "frontend/js/syspackages.js"

PROBEN = [
    # ── Backend: Plan ──
    ("KEV hebt die Schwelle NICHT auf", CP,
     'dringend = isinstance(b.get("kev"), dict)', 'dringend = False'),
    ("KEV unbekannt (None) zaehlt als gelistet", CP,
     'dringend = isinstance(b.get("kev"), dict)', 'dringend = b.get("kev") is not False'),
    # ── Backend: Abruf und Cache ──
    ("Cache wird VOR der Inhaltspruefung ersetzt", CP,
     '        pruefen(roh)\n        DATEN.mkdir', '        DATEN.mkdir'),
    ("304 wird nicht als gueltiger Stand genommen", CP,
     'if e.code == 304 and cache.is_file():', 'if False:'),
    ("ohne If-Modified-Since", CP,
     '    if cache.is_file() and meta.get("last_modified"):\n        kopf["If-Modified-Since"] = meta["last_modified"]',
     '    if False:\n        pass'),
    ("EPSS fragt bei jedem Lauf", CP,
     'if neu_s and cache.is_file() and time.time() - float(meta.get("geholt") or 0) < neu_s:',
     'if False:'),
    ("abgeschnittenes gzip wird nicht erkannt", CP,
     '    n = sum(1 for z in _epss_zeilen(gz) if not z.startswith("#"))\n    if n == 0:\n'
     '        raise ValueError("EPSS-Datei ohne Eintraege")', '    return'),
    ("EPSS-Werte ausserhalb 0..1 werden uebernommen", CP,
     'if 0.0 <= sw <= 1.0 and 0.0 <= pw <= 1.0:', 'if True:'),
    ("Ransomware bei jedem Wert", CP,
     '.strip().lower() == "known",', '.strip().lower() != "",'),
    ("EPSS fragt mit der Kennungsliste (Datensparsamkeit)", CP,
     'info = _quelle_laden(EPSS_URL, EPSS_CACHE',
     'info = _quelle_laden(EPSS_URL + "?cve=" + ",".join(sorted(ids)), EPSS_CACHE'),
    # ── Backend: Anreicherung ──
    ("Katalog fehlt -> False statt None", CP,
     '        if k_daten is None:\n            b["kev"] = None', '        if k_daten is None:\n            b["kev"] = False'),
    ("Aliase werden nicht beachtet", CP,
     'ks = [b.get("cve")] + list(b.get("aliase") or [])', 'ks = [b.get("cve")]'),
    ("EPSS ueber Aliase: niedrigster statt hoechster Wert", CP,
     'w = max(werte)', 'w = min(werte)'),
    ("pruefen(): werfende Quelle -> False statt None", CP,
     '            b["kev"] = None\n            b["epss"] = b["epss_perzentil"] = None',
     '            b["kev"] = False\n            b["epss"] = b["epss_perzentil"] = None'),
    ("Kurzbericht verschweigt den KEV-Ausfall", CP,
     'teile.append("CISA KEV nicht verfügbar")', 'pass'),
    ("Kennungsauskunft ohne Einordnung", CP,
     'aus["bedrohung"] = bedrohung_lokal(k)', 'aus["bedrohung"] = {}'),
    # ── Frontend ──
    ("kevAktiv nimmt null als gelistet", SP,
     "return !!(b && b.kev && typeof b.kev === 'object');",
     "return !!(b && b.kev !== false && b.kev !== undefined);"),
    ("Reihenfolge ohne Bedrohungslage", SP,
     'return rang(a) - rang(b) || dring(b) - dring(a)', 'return rang(a) - rang(b)'),
    ("Paketspalte ohne KEV-Markierung", SP,
     "+ (info.befunde.some(kevAktiv) ? ' ' + kevChip() : '');", "+ '';"),
    ("Perzentil wird aufgerundet", SP,
     'Math.floor(b.epss_perzentil * 1000) / 10', 'Math.round(b.epss_perzentil * 1000) / 10'),
    ("Kopfzeile zaehlt KEV ohne kevAktiv", SP,
     "return kevAktiv(b) && b.klasse !== 'ausgenommen';", "return b.kev && b.klasse !== 'ausgenommen';"),
]

DATEIEN = [CP, SP]

WAECHTER = [
    (["python3", "tests/test_cve_bedrohung.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
    (["node", "tests/test_cve_anzeige_ui.js"], r"^(\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()  # nosec – Vergleich, kein Schutz


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout, re.M)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {(r.stdout + r.stderr).strip()[-200:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    """Rueckstand eines abgeschossenen Laufs zuruecknehmen (Laufmarke)."""
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-58s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-58s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-58s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

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
