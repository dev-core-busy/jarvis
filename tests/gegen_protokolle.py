#!/usr/bin/env python3
"""Gegenproben zu den weiteren Protokollen (test_protokolle.py / test_protokolle_ui.js).

Dreht je EINE Zusage im Produktcode zurueck und erwartet FAILs MIT Bilanz;
stellt danach byte-gleich wieder her (md5). Sicherung auf PLATTE mit
Laufmarke (``~/.cache/jarvis_gegen_plog``).

BEWUSST OHNE PROBE: die Einheiten-Pruefung des Journal-Endpunkts. Ohne sie
wirft der Zugriff auf EINHEITEN[...] – das waere ein Absturz des Waechters,
kein beobachtbares FAIL (Register: eine Sabotage, die den Waechter abstuerzen
laesst, hat nicht gebissen). Die Pruefung selbst misst der Waechter trotzdem
("fremde Einheit: 400, der Broker wird nicht gefragt").

Exit 0 = alle beissen, 1 = mindestens eine zahnlos, 2 = Basis nicht gruen.
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

W = Path(__file__).resolve().parent.parent
FZ = W / "backend/broker/fernzugang.py"
ME = W / "backend/broker/meta.py"
UP = W / "backend/update_protokoll.py"
PQ = W / "backend/protokoll_quellen.py"
MA = W / "backend/main.py"
LR = W / "backend/log_retention.py"
JS = W / "frontend/js/protokolle.js"
BE = W / "frontend/js/settings_bedienung.js"
I18 = W / "frontend/js/i18n.js"
DATEIEN = [FZ, ME, UP, PQ, MA, LR, JS, BE, I18]
SICH = Path.home() / ".cache" / "jarvis_gegen_plog"
MARKE = SICH / "LAUF"
md5 = lambda p: hashlib.md5(p.read_bytes()).hexdigest()  # noqa: E731
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
PY, UI = "test_protokolle.py", "test_protokolle_ui.js"

PROBEN = [
    ("SSH-Filter erst nach dem Deckel", FZ,
     '    treffer = [e for e in alle if not art or e["art"] == art]\n', "    treffer = list(alle)\n", PY),
    ("'invalid user' wird zum Kontonamen", FZ,
     r'r"^(\S+)\s.*?: Failed (\S+) for (?:invalid user )?(\S+) from (\S+) port \d+")',
     r'r"^(\S+)\s.*?: Failed (\S+) for (\S+) from (\S+) port \d+")', PY),
    ("SSH-Abfrage ohne Broker-Audit", ME,
     "        policy.audit(by, op, f\"{op}:{art or 'alle'}\", \"executed\" if erg.get(\"ok\") else \"fehler\",\n"
     "                     info=f\"tage={erg.get('tage', '')}\", peer=peer)\n", "", PY),
    ("Update-Verlauf schreibt bei jedem Start", UP,
     '    if vorher == jetzt["voll"]:\n        return None\n', '    if False:\n        return None\n', PY),
    ("Update-Knopf protokolliert nicht", MA,
     "        await asyncio.to_thread(update_protokoll.knopf, user, _vorher, result)\n",
     "        pass\n", PY),
    ("Update-Verlauf ohne Aufbewahrungsfrist", LR,
     '                     ("update_verlauf", _prune_update_verlauf)):', '                     ):', PY),
    ("Traceback-Zeilen werden eigene Eintraege", PQ,
     '        elif aus:\n            aus[-1]["text"] += "\\n" + z\n',
     '        elif False:\n            aus[-1]["text"] += "\\n" + z\n', PY),
    ("Journal nicht mehr neueste zuerst", MA,
     '"seit": pq.ZEITRAEUME[zeitraum], "umgekehrt": True,', '"seit": pq.ZEITRAEUME[zeitraum], "umgekehrt": False,', PY),
    ("Tabelleninhalt per innerHTML", JS,
     "else td.textContent = (inhalt === undefined", "else td.innerHTML = (inhalt === undefined", UI),
    ("SSH-Fehlschlag nicht markiert", JS,
     "var warn = e.art !== 'angenommen';", "var warn = false;", UI),
    ("Update-Fehlschlag nicht markiert", JS,
     "var fehl = e.art === 'update_knopf' && !e.ok;", "var fehl = false;", UI),
    ("veraltete Abhaengigkeitspruefung verschwiegen", JS,
     "if (d.alter_s > 2 * 86400) {", "if (false) {", UI),
    ("Broker-Fehler wird zur leeren Tabelle", JS,
     "if (d && d.ok === false) {", "if (false) {", UI),
    ("SSH-Filter nicht an den Server", JS,
     "if (a) p.set('art', a);", "", UI),
    ("Klappkopf nicht verdrahtet", BE,
     "        'plog-klappen': function () {", "        'plog-klappen-alt': function () {", UI),
    ("EN-Text fehlt", I18,
     "        'plog.ssh.fehlgeschlagen': 'Failed',\n", "", UI),
    ("Reiter heisst wieder Telemetry", I18,
     "        'settings.tab.telemetry':   'Protokolle',", "        'settings.tab.telemetry':   'Telemetry',", UI),
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
