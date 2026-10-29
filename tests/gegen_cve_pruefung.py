#!/usr/bin/env python3
"""Gegenprobe zu tests/test_cve_pruefung.py: beisst der Waechter?

Jede Probe dreht EINE Zusage der CVE-Pruefung zurueck, laesst den Waechter
laufen und erwartet mindestens einen FAIL. Vorher gruener Basislauf, danach
Byte-Gleichheit aller Dateien per md5, ohne Bytecode, mit Laufmarke (ein
abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

⚠ NIE in einem Sammellauf mitlaufen lassen – die Proben patchen Dateien.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_cve_pruefung.laufmarke"

CP = "backend/cve_pruefung.py"
MA = "backend/main.py"
CA = "backend/cve_apt.py"
SC = "backend/scheduler.py"
DA = "backend/broker/daemon.py"
OP = "backend/broker/ops.py"

PROBEN = [
    ("/api/me ohne cve_badge", MA, '        "cve_badge": cve_badge,\n', ''),
    ("Fremdquelle (NodeSource) gilt als Debian", CP,
     '        return not passt(eigene)', '        return False'),
    ("Zuordnung ueber das Binaerpaket statt die Quelle", CP,
     'gruppen.setdefault(p["quelle"], []).append(p)', 'gruppen.setdefault(p["paket"], []).append(p)'),
    ("Kernel ohne Sonderfall (laufender Kernel egal)", CP,
     'ist_kernel = quelle == "linux" and bool(kernel)', 'ist_kernel = False'),
    # KEINE Probe "fixed_version 0": dafuer gibt es keinen eigenen Zweig – der
    # Versionsvergleich verwirft es (jede Version >= 0). Die Probe blieb stumm,
    # weil die Zusage nicht separat existiert; der Waechter prueft die WIRKUNG.
    ("Vergleich behoben/installiert umgedreht", CP,
     'alt = [p for p in bins if cve_apt.vergleiche(p["quell_version"], fv) < 0]',
     'alt = [p for p in bins if cve_apt.vergleiche(p["quell_version"], fv) >= 0]'),
    ("nicht Eingestuftes faellt unter jede Schwelle", CP,
     '    if einstufung not in RANG:\n        return True', '    if einstufung not in RANG:\n        return False'),
    ("regulaere Quelle ohne Schalter", CP,
     'if b.get("aus_sicherheitsquelle") or einst["regulaere_quelle"]:', 'if True:'),
    ("Python im Lock-Modus wird gehoben", CP,
     '.get("lock_modus"):\n        python = False', '.get("lock_modus"):\n        pass'),
    ("Badge zaehlt Quittiertes mit", CP,
     'if b["klasse"] == "ausgenommen" or b["id"] in q:', 'if b["klasse"] == "ausgenommen":'),
    ("behebbar quittierbar", CP,
     'erlaubt = {b["id"] for b in erg.get("befunde") or [] if b.get("quittierbar")}',
     'erlaubt = {b["id"] for b in erg.get("befunde") or []}'),
    ("beheben auch bei Wahrheitswert statt True", CP,
     'return {"beheben": d.get("beheben") is True, "schwelle": sw}',
     'return {"beheben": bool(d.get("beheben")), "schwelle": sw}'),
    ("Tilde sortiert hinter statt vor", CA,
     '    if c == "~":\n        return -1', '    if c == "~":\n        return 1'),
    ("hold wird angefasst", CA, 'if st == "hi":', 'if False:'),
    ("Sicherheitsquelle nicht erzwungen", CA,
     'if nur_sicherheit and not info.get("sicherheit"):', 'if False:'),
    ("geplante Entfernung wird ignoriert", CA,
     'if sim.returncode != 0 or re.search(r"^Remv ", sim.stdout or "", re.M):',
     'if sim.returncode != 0:'),
    ("--no-remove fehlt", CA,
     '"--only-upgrade", "--no-remove",', '"--only-upgrade",'),
    ("Auftragsart fehlt in der Whitelist", SC,
     '"cve_pruefung") else "agent",', ') else "agent",'),
    ("Optionen auch fuer fremde Auftragsart", SC,
     'if job.get("kind") != "cve_pruefung":', 'if False:'),
    ("Op nicht als lange Op", DA, '"cve_beheben"})', '})'),
    ("nur_sicherheit nicht fail-closed", OP,
     'nur_sicherheit=args.get("nur_sicherheit") is not False,',
     'nur_sicherheit=bool(args.get("nur_sicherheit")),'),
]

DATEIEN = [CP, CA, SC, DA, OP, MA, "tests/test_cve_pruefung.py"]

WAECHTER = [
    (["python3", "tests/test_cve_pruefung.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


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
        m = re.search(muster, r.stdout)
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
