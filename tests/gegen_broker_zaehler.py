#!/usr/bin/env python3
"""Gegenprobe: beissen ``test_broker_zaehler.py`` (Trennung Zaehler/Policy) und
``test_broker_policy_zaehler.py`` (Buendelung) ueberhaupt?

Baut je Probe einen Wegwerf-Baum (``backend/broker/*``, die beiden Waechter und
die Oberflaechen-Datei, die der Waechter liest), sabotiert darin EINE Stelle von
``policy.py`` und verlangt den erwarteten Exit des zustaendigen Waechters
(1 = Biss mit Bilanz, 2 = Sandkasten-Abbruch). Der Arbeitsbaum wird nie
angefasst – kein Rueckstand nach einem Abbruch moeglich. Ohne Bytecode.

Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
TRENN = "test_broker_zaehler.py"
BUENDEL = "test_broker_policy_zaehler.py"
KOPIEREN = ["backend/__init__.py", "backend/broker", "frontend/js/security_incidents.js",
            "tests/" + TRENN, "tests/" + BUENDEL]

# (Name, alt, neu, Waechter, erwarteter Exit)
PROBEN = [
    ("Zaehler-Flush schreibt die Policy-Datei mit",
     "            elif time.monotonic() - _letzter_flush >= ZAEHLER_FLUSH_S:\n"
     "                _zaehler_flushen(data)\n",
     "            elif time.monotonic() - _letzter_flush >= ZAEHLER_FLUSH_S:\n"
     "                _zaehler_flushen(data)\n"
     "                _atomar_schreiben(POLICY_FILE, data)\n", TRENN, 1),
    ("flush() schreibt die Policy (Migration nur ueber Neuschreiben)",
     "        except PolicyUnlesbar:\n            return\n        _zaehler_flushen(data)\n",
     "        except PolicyUnlesbar:\n            return\n        _save(data)\n        _zaehler_flushen(data)\n",
     TRENN, 1),
    ("Altbestand in der Policy wird nicht uebernommen",
     "        basis = {\"count\": _zahl(entry.get(\"count\")), \"last_used\": _zahl(entry.get(\"last_used\"))}\n",
     "        basis = {\"count\": 0, \"last_used\": 0}\n", TRENN, 1),
    ("Policy wird bereinigt, ohne die Zaehler vorher zu retten",
     "        if _zaehler_flushen(data):\n", "        if True:\n", TRENN, 1),
    ("list_ops liefert die Zaehler nicht mehr (Admin, Oberflaeche)",
     "        entries = [_mit_zaehler(k, e, bestand) for k, e in data[\"ops\"].items()]\n",
     "        entries = list(data[\"ops\"].values())\n", TRENN, 1),
    ("decide gibt den Eintrag ohne Zaehler zurueck",
     "        return _mit_zaehler(key, entry, _zaehler_lesen())\n",
     "        return dict(entry)\n", TRENN, 1),
    ("Dateien mit 0644 statt 0600",
     "    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)\n"
     "    try:\n        os.fchmod(fd, 0o600)",
     "    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)\n"
     "    try:\n        os.fchmod(fd, 0o644)", TRENN, 1),
    ("Entfernen laesst den Zaehler stehen",
     "            _zaehler_flushen(data)   # sonst erbte ein neu auftauchender Eintrag den alten Stand\n",
     "", TRENN, 1),
    ("Schreibfehler der Zaehlerdatei sperrt die Op",
     "        print(f\"[Broker-Policy] Zaehler nicht geschrieben: {str(e)[:160]}\", flush=True)\n"
     "        return False\n",
     "        raise\n", TRENN, 1),
    ("Buendelung weg: Zaehlerdatei bei jeder Op",
     "            elif time.monotonic() - _letzter_flush >= ZAEHLER_FLUSH_S:\n",
     "            elif True:\n", BUENDEL, 1),
    ("Zaehlerdatei folgt der umgelenkten Policy nicht (Sandkasten)",
     "if os.environ.get(\"JARVIS_BROKER_POLICY\")\n", "if False\n", TRENN, 2),
]


def baum(ziel: Path) -> None:
    for rel in KOPIEREN:
        q, z = WURZEL / rel, ziel / rel
        z.parent.mkdir(parents=True, exist_ok=True)
        if q.is_dir():
            shutil.copytree(q, z, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(q, z)


def lauf(ziel: Path, waechter: str) -> tuple[int, str]:
    umg = {k: v for k, v in os.environ.items() if not k.startswith("JARVIS_")}
    umg["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run([sys.executable, str(ziel / "tests" / waechter)], capture_output=True,
                       text=True, env=umg, cwd=str(ziel), timeout=180)
    bilanz = [z for z in p.stdout.splitlines() if z.startswith("Ergebnis:")]
    return p.returncode, (bilanz[-1] if bilanz else "KEINE BILANZ")


def main() -> int:
    text = (WURZEL / "backend" / "broker" / "policy.py").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="gegen_broker_zaehler_") as tmp:
        basis = Path(tmp) / "basis"
        baum(basis)
        for w in (TRENN, BUENDEL):
            rc, bilanz = lauf(basis, w)
            if rc != 0:
                print("ABBRUCH: Basislauf %s nicht gruen (Exit %d, %s)" % (w, rc, bilanz))
                return 2
        print("Basislauf gruen (beide Waechter).\n")
        treffer = 0
        for i, (name, alt, neu, waechter, erwartet) in enumerate(PROBEN):
            if text.count(alt) != 1:
                print("  ???  %-62s Anker %dx gefunden" % (name, text.count(alt)))
                continue
            ziel = Path(tmp) / ("p%02d" % i)
            baum(ziel)
            (ziel / "backend" / "broker" / "policy.py").write_text(text.replace(alt, neu),
                                                                   encoding="utf-8")
            rc, bilanz = lauf(ziel, waechter)
            # Exit 1 zaehlt nur MIT Bilanzzeile – ein Absturz ist kein Biss
            gut = rc == erwartet and (erwartet != 1 or bilanz != "KEINE BILANZ")
            treffer += gut
            print("  %s %-62s Exit %d (erwartet %d)  %s"
                  % ("OK  " if gut else "ZAHN", name, rc, erwartet, bilanz))
    print("\n%d/%d Proben wie erwartet" % (treffer, len(PROBEN)))
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
