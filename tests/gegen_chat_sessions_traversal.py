#!/usr/bin/env python3
"""Gegenprobe zu ``test_chat_sessions_traversal.py``: beisst er?

Je Probe wird EINE Schranke in ``backend/chat_sessions.py`` zurueckgedreht und
das erwartete Urteil verlangt. Die beiden Schranken (Punktname in ``_safe``,
Elternpruefung in ``_valid``) decken sich bei ``..``/``.`` GEGENSEITIG – das ist
gewollt und wird hier als eigene Probe BENANNT statt als "blinder Waechter"
gezaehlt: nimmt man nur die Punktregel weg, faengt die Elternpruefung es auf
und der Waechter MUSS gruen bleiben.

Ablauf wie gegen_konto_hinweise.py (gruene Basis, Sicherung im HOME, Laufmarke,
md5). Zusaetzlich: SIGTERM/SIGINT laufen ueber ``finally`` – ein ``timeout``
um diesen Harness hinterlaesst keinen sabotierten Baum.
NICHT in einem Sammellauf ueber ``tests/*`` mitlaufen lassen – patcht den Baum.

Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WAECHTER = [sys.executable, str(WURZEL / "tests" / "test_chat_sessions_traversal.py")]
SICHERUNG = Path.home() / ".gegen_chat_sessions_traversal"
MARKE = SICHERUNG / "laeuft"
MODUL = "backend/chat_sessions.py"

PUNKT = ("    if not out.strip(\".\"):\n        return fallback\n    return out\n",
         "    return out or fallback\n")
ELTERN = ("        if sd.resolve().parent != _user_dir(user).resolve():\n            return False\n",
          "        pass\n")

# (Name, [(datei, alt, neu), ...], erwarteter Exit des Waechters)
PROBEN = [
    ("Elternpruefung weg (Symlink-Sitzung gilt)", [(MODUL,) + ELTERN], 1),
    ("beide Schranken weg (Altstand: '..' loescht alles)", [(MODUL,) + PUNKT, (MODUL,) + ELTERN], 1),
    ("nur Punktregel weg – Elternpruefung faengt es (Waechter bleibt gruen)", [(MODUL,) + PUNKT], 0),
]
DATEIEN = sorted({s[0] for _n, schritte, _e in PROBEN for s in schritte})
ERFASST = [MODUL]

_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf(cmd):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    e = subprocess.run(cmd, cwd=WURZEL, capture_output=True, text=True, timeout=300, env=env)
    return e.returncode, e.stdout + e.stderr


def zurueck():
    for rel in DATEIEN:
        s = SICHERUNG / rel.replace("/", "__")
        if s.is_file():
            shutil.copyfile(s, WURZEL / rel)


def _signal(signum, _frame):
    raise SystemExit(128 + signum)


# Die Liste der gesicherten Dateien ist eine REGEL, keine Pflege.
if set(DATEIEN) - set(ERFASST):
    print("ABBRUCH (Exit 2): Proben fassen ungesicherte Dateien an: %s" % sorted(set(DATEIEN) - set(ERFASST)))
    sys.exit(2)

if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

rc, aus = lauf(WAECHTER)
if rc != 0:
    print("ABBRUCH (Exit 2): Basislauf nicht gruen (Exit %d)." % rc)
    print(aus[-1500:])
    sys.exit(2)
print("Basislauf gruen.\n")

SICHERUNG.mkdir(mode=0o700, exist_ok=True)
for rel in DATEIEN:
    shutil.copyfile(WURZEL / rel, SICHERUNG / rel.replace("/", "__"))
soll = {rel: md5(WURZEL / rel) for rel in DATEIEN}
MARKE.write_text("laeuft", encoding="utf-8")
signal.signal(signal.SIGTERM, _signal)
signal.signal(signal.SIGINT, _signal)
try:
    for name, schritte, erwartet in PROBEN:
        angewandt = True
        for rel, alt, neu in schritte:
            pfad = WURZEL / rel
            quelle = pfad.read_text(encoding="utf-8")
            n = quelle.count(alt)
            if n != 1:
                pruefe(False, "%s -> Anker eindeutig" % name, "%d Treffer" % n)
                angewandt = False
                break
            pfad.write_text(quelle.replace(alt, neu), encoding="utf-8")
        if angewandt:
            rc, _aus = lauf(WAECHTER)
            pruefe(rc == erwartet, "%s -> Waechter Exit %d" % (name, erwartet), "Exit %d" % rc)
        zurueck()
        for rel in DATEIEN:
            pruefe(md5(WURZEL / rel) == soll[rel], "%s -> %s byte-gleich zurueck" % (name, rel))
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

rc, _ = lauf(WAECHTER)
pruefe(rc == 0, "Abschlusslauf gruen", "Exit %d" % rc)
shutil.rmtree(SICHERUNG, ignore_errors=True)

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
