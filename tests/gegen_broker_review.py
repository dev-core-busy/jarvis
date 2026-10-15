#!/usr/bin/env python3
"""Gegenprobe zu ``test_lauf_tmp_symlink.py`` und ``test_broker_certbot_benutzer.py``.

Code-Review 2026-10-07, zwei Wege vom Dienstbenutzer zu root ueber automatisch
erlaubte Broker-Ops. Je Probe wird EINE Schranke zurueckgedreht und Exit 1 des
zustaendigen Waechters verlangt. Die Quotierung im Renewal-Hook ist Guertel zur
Namenspruefung (ein gueltiger Systemname enthaelt nichts, was zu quoten waere)
und hat deshalb KEINE eigene Probe – ihre Sabotage waere wirkungslos.

Ablauf wie gegen_konto_hinweise.py (gruene Basis, Sicherung im HOME, Laufmarke,
md5, ohne Bytecode). SIGTERM/SIGINT laufen ueber ``finally``.
NICHT in einem Sammellauf ueber ``tests/*`` mitlaufen lassen – patcht den Baum.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
PY = Path(WURZEL / "venv" / "bin" / "python")
PY = str(PY) if PY.is_file() else sys.executable
W_LINK = [PY, str(WURZEL / "tests" / "test_lauf_tmp_symlink.py")]
W_CERT = [PY, str(WURZEL / "tests" / "test_broker_certbot_benutzer.py")]
SICHERUNG = Path.home() / ".gegen_broker_review"
MARKE = SICHERUNG / "laeuft"
LT = "backend/lauf_tmp.py"
OPS = "backend/broker/ops.py"
ERFASST = [LT, OPS]

MUSTER = "    if not re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', service_user):\n"
EXISTENZ = ("    except KeyError:\n"
            "        return {\"ok\": False, \"rc\": -1, \"stdout\": \"\", \"stderr\": \"Dienst-Benutzer existiert nicht\"}\n")
EXISTENZ_ALT = ("    except KeyError:\n"
                "        _pw_dienst = pwd.struct_passwd((service_user, 'x', 4711, 4711, '', '/', '/bin/sh'))\n")

# (Name, Datei, [(alt, neu), ...] oder alt, neu, Waechter[, erwarteter Exit])
PROBEN = [
    ("Kennung wieder ueber den Pfad (mkdir/chown/chmod folgen dem Link)", LT,
     "        fd = _verzeichnis_fd(ziel, 0o700)\n"
     "        try:\n"
     "            _, gid = _dienst_ids()\n"
     "            os.fchown(fd, pw.pw_uid, gid)\n"
     "            # chmod NACH chown: ein chown loescht setgid/setuid wieder.\n"
     "            os.fchmod(fd, ARBEIT_MODUS)\n"
     "        finally:\n"
     "            os.close(fd)\n",
     "        ziel.mkdir(parents=True, exist_ok=True)\n"
     "        _, gid = _dienst_ids()\n"
     "        os.chown(ziel, pw.pw_uid, gid)\n"
     "        os.chmod(ziel, ARBEIT_MODUS)\n", W_LINK),
    ("Einhaengepunkte wieder ueber den Pfad", LT,
     "                fd = _verzeichnis_fd(teil, 0o700)\n"
     "                try:\n"
     "                    os.fchown(fd, uid, gid)\n"
     "                    os.fchmod(fd, ARBEIT_MODUS)\n"
     "                finally:\n"
     "                    os.close(fd)\n",
     "                teil.mkdir(exist_ok=True)\n"
     "                os.chown(teil, uid, gid)\n"
     "                os.chmod(teil, ARBEIT_MODUS)\n", W_LINK),
    ("Wurzel als root wieder ueber den Pfad", LT,
     "        fd = _verzeichnis_fd(pfad, modus)\n"
     "        try:\n"
     "            os.fchmod(fd, modus)\n"
     "            uid, gid = _dienst_ids()\n"
     "            os.fchown(fd, uid, gid)\n"
     "        finally:\n"
     "            os.close(fd)\n",
     "        pfad.mkdir(parents=True, exist_ok=True)\n"
     "        os.chmod(pfad, modus)\n"
     "        uid, gid = _dienst_ids()\n"
     "        os.chown(pfad, uid, gid)\n", W_LINK),
    ("_verzeichnis_fd ohne O_NOFOLLOW", LT,
     "            neu = os.open(teil, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)\n",
     "            neu = os.open(teil, os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)\n", W_LINK),
    ("_verzeichnis_fd laesst '..' durch", LT,
     "            if teil in (\".\", \"..\") or \"/\" in teil:\n",
     "            if \"/\" in teil:\n", W_LINK),
    # Die drei certbot-Schranken (Muster, Existenz, nicht root) decken sich
    # gegenseitig: jede EINZELN wegzunehmen laesst den Waechter zu Recht gruen.
    # Benannt statt als "blinder Waechter" gezaehlt; der ALTSTAND (Muster weg
    # UND unbekannter Name geht als normaler Benutzer durch) muss beissen.
    ("certbot: nur Namensmuster weg – Existenzpruefung faengt es", OPS,
     [(MUSTER, "    if False:\n")], W_CERT, 0),
    ("certbot: Altstand (Muster weg, unbekannter Name geht durch)", OPS,
     [(MUSTER, "    if False:\n"), (EXISTENZ, EXISTENZ_ALT)], W_CERT, 1),
    ("certbot: root als Dienst-Benutzer erlaubt", OPS,
     [("    if _pw_dienst.pw_uid == 0:\n", "    if False:\n")], W_CERT, 1),
]
DATEIEN = sorted({p[1] for p in PROBEN})

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


if set(DATEIEN) - set(ERFASST):
    print("ABBRUCH (Exit 2): Proben fassen ungesicherte Dateien an: %s"
          % sorted(set(DATEIEN) - set(ERFASST)))
    sys.exit(2)

if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

for cmd in (W_LINK, W_CERT):
    rc, aus = lauf(cmd)
    if rc != 0:
        print("ABBRUCH (Exit 2): Basislauf %s nicht gruen (Exit %d)." % (Path(cmd[-1]).name, rc))
        print(aus[-1500:])
        sys.exit(2)
print("Basislauf beider Waechter gruen.\n")

SICHERUNG.mkdir(mode=0o700, exist_ok=True)
for rel in DATEIEN:
    shutil.copyfile(WURZEL / rel, SICHERUNG / rel.replace("/", "__"))
soll = {rel: md5(WURZEL / rel) for rel in DATEIEN}
MARKE.write_text("laeuft", encoding="utf-8")
signal.signal(signal.SIGTERM, _signal)
signal.signal(signal.SIGINT, _signal)
try:
    for probe in PROBEN:
        if isinstance(probe[2], list):
            name, rel, schritte, waechter, erwartet = probe
        else:
            name, rel, alt, neu, waechter = probe
            schritte, erwartet = [(alt, neu)], 1
        pfad = WURZEL / rel
        quelle = pfad.read_text(encoding="utf-8")
        treffer = [quelle.count(a) for a, _n in schritte]
        if treffer != [1] * len(schritte):
            pruefe(False, "%s -> Anker eindeutig" % name, "Treffer %s" % treffer)
            continue
        for a, n in schritte:
            quelle = quelle.replace(a, n)
        pfad.write_text(quelle, encoding="utf-8")
        rc, _aus = lauf(waechter)
        pruefe(rc == erwartet, "%s -> %s Exit %d" % (name, Path(waechter[-1]).name, erwartet),
               "Exit %d" % rc)
        zurueck()
        pruefe(md5(pfad) == soll[rel], "%s -> Datei byte-gleich zurueck" % name)
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for rel in DATEIEN:
    pruefe(md5(WURZEL / rel) == soll[rel], "%s unveraendert" % rel)
for cmd in (W_LINK, W_CERT):
    rc, _ = lauf(cmd)
    pruefe(rc == 0, "Abschlusslauf %s gruen" % Path(cmd[-1]).name, "Exit %d" % rc)
shutil.rmtree(SICHERUNG, ignore_errors=True)

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
