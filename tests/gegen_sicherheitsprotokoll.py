#!/usr/bin/env python3
"""Gegenproben zur Ansicht des Sicherheitsprotokolls
(test_sicherheitsprotokoll.py / test_sicherheitsprotokoll_ui.js).

Dreht je EINE Zusage im Produktcode zurueck und erwartet FAILs MIT Bilanz;
stellt danach byte-gleich wieder her (md5). Sicherung auf PLATTE mit
Laufmarke (``~/.cache/jarvis_gegen_sprot``) – ein abgeschossener Lauf wird beim
naechsten Start zurueckgenommen.

Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
SL = W / "backend/sicherheits_log.py"
MA = W / "backend/main.py"
JS = W / "frontend/js/sicherheitsprotokoll.js"
BE = W / "frontend/js/settings_bedienung.js"
I18 = W / "frontend/js/i18n.js"
DATEIEN = [SL, MA, JS, BE, I18]
SICH = Path.home() / ".cache" / "jarvis_gegen_sprot"
MARKE = SICH / "LAUF"
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()  # noqa: E731
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
PY, UI = "test_sicherheitsprotokoll.py", "test_sicherheitsprotokoll_ui.js"

NEUE_DELETE_ROUTE = '''@app.delete("/api/security/log")
async def sicherheitsprotokoll_loeschen(_u: str = Depends(require_local_auth)):
    return JSONResponse({"ok": True})


@app.delete("/api/audit_log")'''

PROBEN = [
    ("Benutzerfilter achtet auf Gross/Klein", SL,
     'if benutzer and benutzer not in str(e.get("benutzer") or "").lower():',
     'if benutzer and benutzer not in str(e.get("benutzer") or ""):', PY),
    ("Pruefmaterial geht hinaus", MA,
     'z = {k: v for k, v in e.items() if k not in ("prev", "hash", "mac")}',
     "z = dict(e)", PY),
    ("Kette immer als intakt gemeldet", MA,
     '"kette": {"ok": bool(kette.get("ok")),', '"kette": {"ok": True,', PY),
    ("Deckel entfernt", MA,
     "    limit = max(1, min(int(limit or 200), 1000))\n", "    limit = int(limit or 200)\n", PY),
    ("Loeschweg ergaenzt", MA, '@app.delete("/api/audit_log")', NEUE_DELETE_ROUTE, PY),
    ("Details per innerHTML", JS,
     "b.textContent = v.length > 160 ? v.slice(0, 160) + '…' : v;",
     "b.innerHTML = v.length > 160 ? v.slice(0, 160) + '…' : v;", UI),
    ("Fehler verschwindet von selbst", JS,
     "el.style.display = text ? 'block' : 'none';\n",
     "el.style.display = text ? 'block' : 'none';\n"
     "        setTimeout(function () { el.style.display = 'none'; }, 3000);\n", UI),
    ("Art markiert nicht mehr", JS,
     "if (WARN[e.art] || /^[45]\\d\\d$/.test(erg)", "if (false && WARN[e.art] || /^[45]\\d\\d$/.test(erg)", UI),
    ("Statuscode markiert nicht mehr", JS,
     "|| /^[45]\\d\\d$/.test(erg) ||", "|| false ||", UI),
    ("Bruch wird als intakt angezeigt", JS,
     "} else if (k.ok) {", "} else if (true) {", UI),
    ("Sprachwechsel zeichnet nicht neu", JS,
     "            if (letzte) zeichnen(letzte);\n", "", UI),
    ("Klappkopf nicht verdrahtet", BE,
     "        'sprot-klappen': function () {", "        'sprot-klappen-alt': function () {", UI),
    ("EN-Name einer Ereignisart fehlt", I18,
     "        'sprot.art.konto_gesperrt':  'Account locked',\n", "", UI),
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
