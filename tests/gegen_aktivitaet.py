#!/usr/bin/env python3
"""Gegenproben zum Aktivitaetsprotokoll (test_aktivitaet.py).

Dreht je EINE Zusage im Produktcode zurueck und erwartet FAILs MIT Bilanz;
stellt danach byte-gleich wieder her (md5). Sicherung auf PLATTE mit
Laufmarke (``~/.cache/jarvis_gegen_akt``), Lauf ohne Bytecode (Register).

BEWUSST OHNE PROBE: "ein Endpunkt mit ZWEI Aufrufen verliert einen". Die Regel
prueft, DASS ein Endpunkt protokolliert, nicht jeden Rueckgabeweg – der
Ordner-Endpunkt hat zwei (mit und ohne gelungene Gruppenzuordnung), und das
Entfernen des einen bliebe stumm. Gemessen wird deshalb an einem Endpunkt mit
genau einem Aufruf (Datei loeschen).

Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
MA = W / "backend/main.py"
AK = W / "backend/aktivitaet.py"
LR = W / "backend/log_retention.py"
I18 = W / "frontend/js/i18n.js"
DATEIEN = [MA, AK, LR, I18]
SICH = Path.home() / ".cache" / "jarvis_gegen_akt"
MARKE = SICH / "LAUF"
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()  # noqa: E731
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
PY = "test_aktivitaet.py"

PROBEN = [
    ("Datei loeschen ohne Protokoll", MA,
     '    _aktivitaet(user, "wissen", "datei_geloescht", file_path)\n', "", PY),
    ("Gruppen-Editoren ohne Rechte-Markierung", MA,
     '    _aktivitaet(user, "wissen", "gruppe_geaendert", gid, rechte=bool(editoren),\n',
     '    _aktivitaet(user, "wissen", "gruppe_geaendert", gid,\n', PY),
    ("Kennwort in den Details", MA,
     '                kennwort_neu=bool("password" in data and data["password"]))\n',
     '                kennwort=data.get("password"))\n', PY),
    ("ganzer Anfragekoerper als Detail", MA,
     '"Automatische Verdichtung", an=auto)', '"Automatische Verdichtung", an=auto, roh=body)', PY),
    ("Middleware ohne IP", MA,
     '    halter: dict = {"ip": request.client.host if request.client else ""}\n',
     '    halter: dict = {}\n', PY),
    ("rechte=True erreicht das Sicherheitsprotokoll nicht", MA,
     '    if rechte:\n        try:\n            _sicherheits_log.ereignis(',
     '    if False:\n        try:\n            _sicherheits_log.ereignis(', PY),
    ("Protokollfehler kippt den Endpunkt", MA,
     '        print(f"[Aktivitaet] {bereich}/{aktion} nicht protokollierbar: {e}", flush=True)\n',
     '        raise\n', PY),
    ("Lesen ohne Admin-Recht", MA,
     '                               suche: str = "", _u: str = Depends(require_local_auth)):',
     '                               suche: str = "", _u: str = Depends(require_auth)):', PY),
    ("Suche nur im Gegenstand", AK,
     'for k in ("objekt", "aktion", "details")}', 'for k in ("objekt", "aktion")}', PY),
    ("Deckel vor dem Filter", AK,
     "            if not _passt(e, bereich, benutzer, suche):\n",
     "            if len(aus) >= limit:\n                break\n"
     "            if not _passt(e, bereich, benutzer, suche):\n", PY),
    ("Frist loescht Zeilen ohne Zeitstempel", AK,
     "if isinstance(ts, (int, float)) and ts < cutoff_ts:",
     "if not isinstance(ts, (int, float)) or ts < cutoff_ts:", PY),
    ("Falsyness verwirft 0 und False", AK,
     'if v is not None and v != ""}', "if v}", PY),
    ("Kappung fehlt", AK,
     'return s if len(s) <= WERT_MAX else s[:WERT_MAX] + "…"', "return s", PY),
    ("ohne Aufbewahrungsfrist", LR,
     '                     ("aktivitaet", _prune_aktivitaet)):', '                     ):', PY),
    ("EN-Text einer Aktion fehlt", I18,
     "        'plog.akt.a_ordner_angelegt': 'Knowledge folder created',\n", "", PY),
]

_fehlt = {str(p[1]) for p in PROBEN} - {str(d) for d in DATEIEN}
if _fehlt:
    print("ABBRUCH: Probe(n) auf ungesicherte Datei(en): %s" % _fehlt)
    sys.exit(2)


def zurueck():
    if not MARKE.is_file():
        return
    for p in DATEIEN:
        s = SICH / p.name
        if s.is_file():
            p.write_bytes(s.read_bytes())
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def lauf(test):
    r = subprocess.run([sys.executable, str(W / "tests" / test)], capture_output=True,
                       text=True, env=env, timeout=300)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None)


zurueck()
SICH.mkdir(parents=True, exist_ok=True)
for p in DATEIEN:
    (SICH / p.name).write_bytes(p.read_bytes())
vorher = {p: md5(p) for p in DATEIEN}
MARKE.write_text(str(os.getpid()))

rc_ende = 1
try:
    rc, f = lauf(PY)
    if rc != 0 or f != 0:
        print("ABBRUCH: Basis %s nicht gruen (rc=%s, FAIL=%s)" % (PY, rc, f))
        sys.exit(2)
    print("Basis gruen.\n")
    gut = 0
    for name, datei, a, n, t in PROBEN:
        txt = (SICH / datei.name).read_text(encoding="utf-8")
        if txt.count(a) != 1:
            print("  VERFEHLT %s: Anker %dx" % (name, txt.count(a)))
            continue
        datei.write_text(txt.replace(a, n, 1), encoding="utf-8")
        try:
            rc, f = lauf(t)
        finally:
            datei.write_bytes((SICH / datei.name).read_bytes())
        biss = rc == 1 and (f or 0) > 0
        gut += biss
        print("  %s %s: rc=%s FAIL=%s%s" % ("OK     " if biss else "ZAHNLOS", name, rc, f,
                                          "" if f is not None else " (OHNE BILANZ!)"))
    print("\n%d von %d beissen einzeln." % (gut, len(PROBEN)))
    rc_ende = 0 if gut == len(PROBEN) else 1
finally:
    for p in DATEIEN:
        p.write_bytes((SICH / p.name).read_bytes())
    gleich = all(md5(p) == vorher[p] for p in DATEIEN)
    print("byte-gleich:", gleich)
    if gleich and MARKE.is_file():
        MARKE.unlink()
sys.exit(rc_ende)
