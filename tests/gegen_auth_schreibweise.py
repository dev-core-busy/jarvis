#!/usr/bin/env python3
"""Gegenprobe zu ``test_auth_schreibweise.py``.

Je Probe wird EINE tragende Stelle zurueckgedreht; der Waechter muss mit
Exit 1 antworten. Basislauf gruen, Sicherung auf Platte, Laufmarke,
md5-Kontrolle danach, ohne Bytecode (Register). NICHT in einem Sammellauf.
Exit 0 = jede Probe beisst, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MARKE = Path.home() / ".gegen_auth_schreibweise.laeuft"
SICHER = Path.home() / ".gegen_auth_schreibweise.sicherung"
MAIN = "backend/main.py"

PROBEN = [
    ("Lesen ohne Normalisierung", MAIN,
     "    return users.get(_auth_schluessel(username), {",
     "    return users.get(username, {"),
    ("Schreiben ohne Normalisierung", MAIN,
     "    username = _auth_schluessel(username)\n    state = _load_auth_state()",
     "    state = _load_auth_state()"),
    ("Altbestand wird nicht zusammengefuehrt", MAIN,
     "        users, geaendert = _auth_eintraege_zusammenfuehren(state[\"users\"])",
     "        users, geaendert = state[\"users\"], False"),
    ("Migration bevorzugt NICHT die aktive 2FA", MAIN,
     "            return (0 if aktiv else 1, 0 if k == norm else 1, k)",
     "            return (0 if k == norm else 1, k)"),
    ("Lesefehler wieder fail-open", MAIN,
     "            raise AuthStateUnlesbar(str(e)) from e",
     "            return {}"),
    ("keine Sicherung beim Schreiben", MAIN,
     "                os.replace(_AUTH_STATE_FILE, bak)",
     "                pass"),
    ("login faengt die Ausnahme nicht", MAIN,
     "    except AuthStateUnlesbar:\n        # Fail-closed",
     "    except ZeroDivisionError:\n        # Fail-closed"),
]
DATEIEN = sorted({p[1] for p in PROBEN})
_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  ok   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (("  -> " + detail) if detail else ""))


def md5(p):
    return hashlib.md5((WURZEL / p).read_bytes()).hexdigest()


def lauf():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "tests/test_auth_schreibweise.py"], cwd=WURZEL,
                       capture_output=True, text=True, timeout=300, env=env)
    aus = r.stdout + r.stderr
    return r.returncode, aus.count("  FAIL "), aus


def zurueck():
    for d in DATEIEN:
        q = SICHER / d.replace("/", "__")
        if q.exists():
            shutil.copy2(q, WURZEL / d)


if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

rc, f, aus = lauf()
if rc != 0:
    print("ABBRUCH (Exit 2): Basislauf nicht gruen (%d)" % rc)
    print(aus[-1500:])
    sys.exit(2)
print("Basislauf gruen.\n")

SICHER.mkdir(exist_ok=True)
vorher = {}
for d in DATEIEN:
    shutil.copy2(WURZEL / d, SICHER / d.replace("/", "__"))
    vorher[d] = md5(d)
MARKE.write_text("laeuft")
try:
    for name, datei, alt, neu in PROBEN:
        p = WURZEL / datei
        t = p.read_text(encoding="utf-8")
        if t.count(alt) != 1:
            pruefe(False, "%s: Anker nicht eindeutig (%d)" % (name, t.count(alt)))
            continue
        p.write_text(t.replace(alt, neu), encoding="utf-8")
        rc, f, aus = lauf()
        pruefe(rc == 1 and f >= 1, "%s -> beisst (%d FAIL)" % (name, f), "Exit %d" % rc)
        zurueck()
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for d in DATEIEN:
    pruefe(md5(d) == vorher[d], "%s byte-gleich zurueck" % d)
rc, _, _ = lauf()
pruefe(rc == 0, "Abschlusslauf wieder gruen")
shutil.rmtree(SICHER, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
