#!/usr/bin/env python3
"""Gegenprobe zu ``test_anmelde_spruehen.py``: beisst der Waechter wirklich?

Je Probe wird EINE Schutzzusage im Produktcode zurueckgedreht; der Waechter muss
mit Exit 1 antworten. Vorgehen wie im Register:
  1. Basislauf GRUEN – ohne gruene Basis ist keine Probe deutbar.
  2. Dateien auf Platte sichern, Probe einbauen, Waechter ohne Bytecode laufen.
  3. Zuruecknehmen und die Byte-Gleichheit per md5 NACHSEHEN.
Eine Laufmarke nimmt den Rueckstand eines abgebrochenen Laufs beim naechsten
Start zurueck. NICHT in einem Sammellauf mitlaufen lassen (patcht den Baum).

Exit 0 = jede Probe beisst, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WAECHTER = WURZEL / "tests" / "test_anmelde_spruehen.py"
MARKE = Path.home() / ".gegen_anmelde_spruehen.laeuft"
SICHER = Path.home() / ".gegen_anmelde_spruehen.sicherung"
AS = "backend/anmelde_schutz.py"
MAIN = "backend/main.py"

# (Name, Datei, alt, neu) – alt muss GENAU EINMAL vorkommen.
PROBEN = [
    ("Vorabpruefung im Login entfernt", MAIN,
     'if _ad_vorab_freigabe(username) == "nein":', 'if False:'),
    ("Orakel zurueck: 403 fuer nicht freigegeben", MAIN,
     '        _record_login_attempt(client_ip, username)\n        return JSONResponse(\n'
     '            {"success": False, "error": "Benutzername oder Passwort falsch"},\n'
     '            status_code=401,\n        )\n\n    # Standard-Kennwort',
     '        if _auth_details.get("reason") == "nicht_freigegeben":\n'
     '            return JSONResponse({"success": False, "error": "Keine Anmeldeberechtigung"}, status_code=403)\n'
     '        _record_login_attempt(client_ip, username)\n        return JSONResponse(\n'
     '            {"success": False, "error": "Benutzername oder Passwort falsch"},\n'
     '            status_code=401,\n        )\n\n    # Standard-Kennwort'),
    ("IPv6 wieder je Adresse", AS,
     'return str(ipaddress.ip_network(f"{a}/64", strict=False))', 'return str(a)'),
    ("Jarvis-Schwelle = Domaenen-Schwelle", AS,
     'return max(1, schwelle - 1), max(KONTO_FENSTER_VORGABE_S, fenster), "domaene"',
     'return max(1, schwelle), max(KONTO_FENSTER_VORGABE_S, fenster), "domaene"'),
    ("Spruehen nie erkannt", AS,
     'if len(konten) >= SPRUEH_KONTEN:', 'if False and len(konten) >= SPRUEH_KONTEN:'),
    ("Meldung bei jedem Fehlversuch", AS,
     '        _sprueh["gemeldet"] = True\n', '        _sprueh["gemeldet"] = False\n'),
    ("Bremse wirkungslos", AS,
     '    if not spruehlage()["aktiv"]:\n        return\n    loop', '    if True:\n        return\n    loop'),
    ("Mindestdauer nicht verdrahtet", MAIN,
     '        await _anmelde_schutz.angleichen(_start)\n', '        pass\n'),
    ("Suchfehler wird zu 'nein'", MAIN,
     '        print(f"[AUTH] Vorabpruefung \'{plain}\': Suche gescheitert ({e}) – "\n'
     '              f"pruefe wie bisher nach dem Bind", flush=True)\n        return "unbekannt"',
     '        print(f"[AUTH] Vorabpruefung \'{plain}\': Suche gescheitert ({e}) – "\n'
     '              f"pruefe wie bisher nach dem Bind", flush=True)\n        return "nein"'),
    ("Kein Gedaechtnis fuer den Dienst-Bind", MAIN,
     '    if time.time() < _vorab_dienst_pause["bis"]:\n        return "unbekannt"',
     '    if False:\n        return "unbekannt"'),
]
DATEIEN = sorted({p[1] for p in PROBEN})
if {p[1] for p in PROBEN} - set(DATEIEN):
    print("ABBRUCH (Exit 2): Probe zielt auf eine nicht gesicherte Datei")
    sys.exit(2)

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
    r = subprocess.run([sys.executable, str(WAECHTER)], cwd=WURZEL, capture_output=True,
                       text=True, timeout=600, env=env)
    return r.returncode, r.stdout + r.stderr


def zurueck():
    for d in DATEIEN:
        quelle = SICHER / d.replace("/", "__")
        if quelle.exists():
            shutil.copy2(quelle, WURZEL / d)


if MARKE.exists():
    print("Rueckstand eines abgebrochenen Laufs – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()

rc, aus = lauf()
if rc != 0:
    print("ABBRUCH (Exit 2): Basislauf nicht gruen (Exit %d)" % rc)
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
        rc, aus = lauf()
        fails = aus.count("  FAIL ")
        pruefe(rc == 1 and fails >= 1, "%s -> beisst (%d FAIL)" % (name, fails),
               "Exit %d" % rc)
        zurueck()
finally:
    zurueck()
    MARKE.unlink(missing_ok=True)

for d in DATEIEN:
    pruefe(md5(d) == vorher[d], "%s byte-gleich zurueck" % d)
rc, _ = lauf()
pruefe(rc == 0, "Abschlusslauf wieder gruen")
shutil.rmtree(SICHER, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
