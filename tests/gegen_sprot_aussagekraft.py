#!/usr/bin/env python3
"""Gegenproben zu den aussagekraeftigen Eintraegen im Sicherheitsprotokoll
(test_sprot_aussagekraft.py / test_sicherheitsprotokoll_ui.js).

Dreht je EINE Zusage im Produktcode zurueck und erwartet FAILs MIT Bilanz;
stellt danach byte-gleich wieder her (md5). Sicherung auf PLATTE mit
Laufmarke (``~/.cache/jarvis_gegen_sprot_aussage``) – ein abgeschossener Lauf
wird beim naechsten Start zurueckgenommen. Nie in einem Sammellauf starten.

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
JS = W / "frontend/js/sicherheitsprotokoll.js"
I18 = W / "frontend/js/i18n.js"
DATEIEN = [MA, JS, I18]
SICH = Path.home() / ".cache" / "jarvis_gegen_sprot_aussage"
MARKE = SICH / "LAUF"
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()  # noqa: E731
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
PY, UI = "test_sprot_aussagekraft.py", "test_sicherheitsprotokoll_ui.js"

PROBEN = [
    ("Kennzeichnung wirkungslos (Abfrage wieder als Aenderung)", MA,
     'if art == "admin_aenderung" and getattr(endpunkt, "_sprot_keine_aenderung", False):',
     'if False and getattr(endpunkt, "_sprot_keine_aenderung", False):', PY),
    ("Kennzeichnung verschluckt auch die Verweigerung", MA,
     'if art == "admin_aenderung" and getattr(endpunkt, "_sprot_keine_aenderung", False):',
     'if art and getattr(endpunkt, "_sprot_keine_aenderung", False):', PY),
    ("Aktion fehlt im Eintrag", MA,
     '        d["aktion"] = _sprot_aktion(endpunkt)\n', '        pass\n', PY),
    ("Objekt (Pfadparameter) fehlt", MA,
     '    if params:\n        d["objekt"]', '    if False:\n        d["objekt"]', PY),
    ("Route aus dem scope statt selbst ermittelt", MA,
     'endpunkt, params = _sprot_route(request.scope)',
     'endpunkt, params = request.scope.get("endpoint"), request.scope.get("path_params") or {}', PY),
    ("Angaben des Endpunkts verworfen", MA,
     '    for k, v in (halter.get("angaben") or {}).items():', '    for k, v in {}.items():', PY),
    ("Vorgang aus dem Aktivitaetsprotokoll fehlt", MA,
     '    if vorgaenge:\n', '    if False:\n', PY),
    ("Abkuerzung gilt als Satzende", MA,
     '        if _SPROT_ABKUERZUNG.search(kopf):\n            continue\n', '', PY),
    ("Rechtehinweis (Admin) bleibt stehen", MA,
     '    satz = re.sub(r"\\s*\\((?:nur\\s+)?(?:Admin|Administratoren)\\b[^)]*\\)", "", satz)\n', '', PY),
    ("Gedankenstrich-Zusatz bleibt stehen", MA,
     '    satz = satz.split(" – ", 1)[0]\n', '', PY),
    ("Leere Angaben landen im Eintrag", MA,
     '        if v is None or v == "" or v == [] or v == {}:\n            continue\n', '', PY),
    ("Gruppenmitglieder nicht mehr gekennzeichnet", MA,
     '@app.post("/api/ldap/group_members")\n@_sprot_keine_aenderung\n',
     '@app.post("/api/ldap/group_members")\n', PY),
    ("Token-Pruefung nicht mehr gekennzeichnet", MA,
     '@app.post("/api/verify-token")\n@_sprot_keine_aenderung\n',
     '@app.post("/api/verify-token")\n', PY),
    ("/api/settings protokolliert WERTE", MA,
     '_sprot_angaben(felder=sorted(str(k)[:60] for k in body)[:60]',
     '_sprot_angaben(felder=sorted(str(v)[:60] for v in body.values())[:60]', PY),
    ("Admin-Endpunkt beschreibt sich wieder mit 'Body …'", MA,
     '    """Zwei-Faktor-Pflicht fuer Administratoren ein- oder ausschalten.\n\n    Body', '    """Body', PY),
    ("Admin-Endpunkt ohne Beschreibung", MA,
     '    """Laufenden Aufbau des Wissensgraphen abbrechen."""\n', '', PY),
    ("Aktion per innerHTML", JS,
     "kopf.textContent = aktion;", "kopf.innerHTML = aktion;", UI),
    ("Beleg steht nicht mehr getrennt", JS,
     "var BELEG = { methode: 1, pfad: 1 };", "var BELEG = {};", UI),
    ("Feldname 'aktion' erscheint zusaetzlich", JS,
     "var rest = schl.filter(function (k) { return k !== 'aktion' || !aktion; });",
     "var rest = schl;", UI),
    ("Feldbeschriftung nicht uebersetzt", JS,
     "a.textContent = T('sprot.det.' + k, k);", "a.textContent = k;", UI),
    ("EN-Beschriftung 'Objekt' fehlt", I18,
     "        'sprot.det.objekt':          'Object',\n", "", UI),
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
    cmd = ["node", str(W / "tests" / test)] if test.endswith(".js") else [sys.executable, str(W / "tests" / test)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300)
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
    for t in (PY, UI):
        rc, f = lauf(t)
        if rc != 0 or f != 0:
            print("ABBRUCH: Basis %s nicht gruen (rc=%s, FAIL=%s)" % (t, rc, f))
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
        print("  %s %s: %s rc=%s FAIL=%s%s" % ("OK     " if biss else "ZAHNLOS", name, t, rc, f,
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
