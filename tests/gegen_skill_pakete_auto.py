#!/usr/bin/env python3
"""Gegenprobe zu tests/test_skill_pakete_auto.py: beisst der Waechter?

Jede Probe dreht EINE Zusage zurueck und erwartet mindestens einen FAIL.
Gruener Basislauf vorher, Byte-Gleichheit danach, ohne Bytecode.
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_skill_pakete_auto.py"
A = "backend/abhaengigkeiten.py"
S = "backend/skills/manager.py"
N = "backend/anonymisieren.py"
H = "backend/main.py"

PROBEN = [
    ("vorhandene Pakete nicht festgenagelt (keine Constraints-Zeilen)", A,
     '    return "".join(f"{n}=={v}\\n" for n, v in sorted(inst.items()))\n',
     '    return ""\n'),
    ("Untergrenze statt Ist-Stand (Kern darf steigen)", A,
     '    return "".join(f"{n}=={v}\\n" for n, v in sorted(inst.items()))\n',
     '    return "".join(f"{n}>={v}\\n" for n, v in sorted(inst.items()))\n'),
    ("Schalter JARVIS_ABH_AUTO wirkungslos", A,
     '    if not fehlend or not installieren:\n', '    if not fehlend:\n'),
    ("gescheiterter Satz wird bei jedem Start wiederholt", A,
     '            if gescheitert.get(skill, {}).get("specs") == specs:\n',
     '            if False:\n'),
    ("Gedaechtnis nach Erfolg nicht geleert", A,
     '                                                 if vorher.get(n) != v)\n'
     '                gescheitert.pop(skill, None)\n',
     '                                                 if vorher.get(n) != v)\n'
     '                pass\n'),
    ("keine Ruecknahme bei rotem Import-Test", A,
     '                    erg.setdefault("zurueckgesetzt", {})[skill] = _zuruecksetzen(vorher, nachher)\n',
     '                    erg.setdefault("zurueckgesetzt", {})[skill] = []\n'),
    ("schon vorher roter pip check zaehlt als Fehlschlag", A,
     '                pc_ok = _pip("check", timeout=120).returncode == 0 or not pc_vorher\n',
     '                pc_ok = _pip("check", timeout=120).returncode == 0\n'),
    ("Import-Test wird ignoriert", A,
     '                elif not imp_ok:\n', '                elif False:\n'),
    ("Sperre wird nicht beachtet", A,
     '    if not _sperre.acquire(blocking=False):\n        erg["fehler"]["*"] = "laeuft bereits"\n',
     '    if not (_sperre.acquire(blocking=False) or True):\n        erg["fehler"]["*"] = "laeuft bereits"\n'),
    ("vor jedem Skill nicht neu nachgesehen (Liste von vorhin)", A,
     '                     if not s.startswith("lock:") and _spec_name(s) not in vorher]\n',
     '                     if not s.startswith("lock:")]\n'),
    ("Spec-Name aus 'name @ url' falsch gelesen", A,
     '        return _norm(Requirement(spec).name)\n', '        return spec\n'),
    ("Skill-Lock ohne --require-hashes", A,
     '    return ["install", "--no-deps", "--require-hashes", "-r", tf.name], tf.name\n',
     '    return ["install", "--no-deps", "-r", tf.name], tf.name\n'),
    ("Skill-Lock mit Aufloesung (ohne --no-deps)", A,
     '    return ["install", "--no-deps", "--require-hashes", "-r", tf.name], tf.name\n',
     '    return ["install", "--require-hashes", "-r", tf.name], tf.name\n'),
    ("Skill-Lock installiert ALLES statt nur Fehlendes", A,
     '            if n not in inst]\n', '            ]\n'),
    ("Hash-Zeilen gehen beim Lesen verloren", A,
     '        elif aktuell and zeile.strip().startswith("--hash="):\n',
     '        elif False:\n'),
    ("Skill-Lock wird ignoriert", A,
     '    return p if p.is_file() else None\n', '    return None\n'),
    ("auch ausgeschaltete Skills", S,
     '            if not (zustaende.get(name) or {}).get("enabled", info.get("enabled", True)):\n',
     '            if False:\n'),
    ("Manifest-Vorgabe ignoriert (nur gespeicherter Zustand)", S,
     '            if not (zustaende.get(name) or {}).get("enabled", info.get("enabled", True)):\n',
     '            if not (zustaende.get(name) or {}).get("enabled"):\n'),
    ("Hilfsprozess startet nach Nachinstallation NICHT neu", N,
     '                    and _pakete_stand() != self._pakete):\n',
     '                    and False):\n'),
    ("Hilfsprozess startet bei JEDER Anfrage neu", N,
     '                    and _pakete_stand() != self._pakete):\n',
     '                    ):\n'),
    ("Skill-Pakete auch bei angesetztem Neustart (vor dem if)", H,
     '                if neu and neu != vorher and not erg.get("zurueckgesetzt"):\n'
     '                    from backend.update_manager import restart_service_delayed\n',
     '                await _skill_pakete()\n'
     '                if neu and neu != vorher and not erg.get("zurueckgesetzt"):\n'
     '                    from backend.update_manager import restart_service_delayed\n'),
]
DATEIEN = [A, S, N, H, "tests/test_skill_pakete_auto.py"]


def md5(p):
    return hashlib.md5((ROOT / p).read_bytes()).hexdigest()


def lauf():
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True, timeout=300,
                       cwd=str(ROOT), env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return (int(m.group(2)) if m and r.returncode != 2 else -1), r.returncode


def main():
    # Jede angefasste Datei muss gesichert sein – als REGEL, nicht gepflegt.
    fehlt = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlt:
        print("ABBRUCH: Proben fassen ungesicherte Dateien an: %s" % sorted(fehlt))
        return 2
    sich = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}
    f, rc = lauf()
    if f != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (f, rc))
        return 2
    print("Basislauf gruen.\n")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            p = ROOT / datei
            t = p.read_text(encoding="utf-8")
            if t.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, t.count(alt)))
                continue
            p.write_text(t.replace(alt, neu), encoding="utf-8")
            try:
                f, rc = lauf()
            finally:
                p.write_bytes(sich[datei])
            if f > 0:
                beissen += 1
                print("  BISS %-62s %d FAIL" % (name, f))
            elif f < 0:
                print("  ABBR %-62s rc=%s" % (name, rc))
            else:
                print("  ZAHN %-62s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, b in sich.items():
            (ROOT / d).write_bytes(b)
    if {d: md5(d) for d in DATEIEN} != vorher:
        print("ABBRUCH: Dateien nicht byte-gleich")
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)" % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
