"""Gegenproben zu test_agent_schluessel: beisst der Waechter, wenn eine Schranke fehlt?

Je Probe GENAU EINE Stelle sabotiert; ein Abbruch (Exit 2) zaehlt nicht als Biss.

    venv/bin/python tests/gegen_agent_schluessel.py
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import hashlib  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

W = Path(__file__).resolve().parent.parent
TEST = W / "tests" / "test_agent_schluessel.py"
AK = "backend/agent_schluessel.py"
AG = "backend/agent.py"
MA = "backend/main.py"

PROBEN = [
    ("Hauptagent ohne Namen wieder privilegiert/erbend", AG,
     '    if not username and not getattr(agent, "is_sub_agent", False):\n        return "", False\n', ""),
    ("run_task leitet das Privileg wieder selbst her", AG,
     "        _lauf_privilegiert = _ag_priv\n",
     "        _lauf_privilegiert = (not self._current_username) or "
     "self._current_username in _LOCAL_PRIVILEGED_USERS\n"),
    ("WebSocket setzt keinen festen Auftraggeber", MA,
     "            _ws_usernames[id(ws)] = WS_SCHLUESSEL_AKTEUR\n", "            pass\n"),
    ("WebSocket prueft den falschen Bereich", MA,
     'is_api_key = _is_valid_agent_key(token, "chat")', 'is_api_key = _is_valid_agent_key(token, "agent")'),
    ("Bereich aus request.url (BadHost)", MA,
     "    pfad = _routing_pfad(request)\n    bereich = _aks.bereich_fuer_pfad(pfad)\n",
     "    pfad = request.url.path\n    bereich = _aks.bereich_fuer_pfad(pfad)\n"),
    ("Ablaufdatum wird ignoriert", AK,
     "        if abgelaufen(e, jetzt):\n            continue\n", ""),
    ("Bereichsfilter fehlt", AK,
     "        if bereich is not None and bereich not in bereiche_von(e):\n            continue\n", ""),
    ("Pfad-Praefix ohne Grenze", AK,
     "        elif p == muster or p.startswith(muster + \"/\"):\n", "        elif p.startswith(muster):\n"),
    ("unlesbares Datum gilt als unbefristet", AK,
     "    if ende is None:\n        return True\n", "    if ende is None:\n        return False\n"),
    ("Endpunkt fehlt in der Pfadtabelle", AK,
     '    ("/api/jira/passende-tickets", "jira"),\n', ""),
    ("neue Schluessel bekommen alle Bereiche", AK,
     'VORGABE = ("agent",)\n', "VORGABE = BEREICHE\n"),
    ("Bestand ohne Feld bekommt nichts", AK,
     "    if not isinstance(eintrag, dict) or \"bereiche\" not in eintrag:\n        return BESTAND\n",
     "    if not isinstance(eintrag, dict) or \"bereiche\" not in eintrag:\n        return ()\n"),
]
DATEIEN = sorted({p[1] for p in PROBEN})
ORIG = {f: (W / f).read_bytes() for f in DATEIEN}
UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
PY = str(W / "venv" / "bin" / "python") if (W / "venv" / "bin" / "python").exists() else sys.executable


def zurueck():
    for f, b in ORIG.items():
        if (W / f).read_bytes() != b:
            (W / f).write_bytes(b)


def lauf():
    r = subprocess.run([PY, str(TEST)], capture_output=True, text=True, timeout=300, env=UMG)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


rc, b, f = lauf()
if rc or not b or f:
    print(f"ABBRUCH: Basis nicht gruen (rc={rc} bilanz={b} fails={f})")
    sys.exit(2)
print("Basis gruen.\n")

gut = 0
try:
    for name, rel, a, n in PROBEN:
        zurueck()
        s = (W / rel).read_text(encoding="utf-8")
        if s.count(a) != 1:
            print(f"  ⚠ VERFEHLT  {name} (Anker {s.count(a)}x)")
            continue
        (W / rel).write_text(s.replace(a, n, 1), encoding="utf-8")
        rc, b, f = lauf()
        zurueck()
        ok = rc == 1 and b and f > 0
        gut += ok
        grund = "" if b else " (OHNE BILANZ – Abbruch, kein Biss)"
        print(f"  {'OK     ' if ok else 'ZAHNLOS'}  {name}: {f} FAIL, rc={rc}{grund}")
finally:
    zurueck()
    for fn, bts in ORIG.items():
        if hashlib.md5((W / fn).read_bytes()).digest() != hashlib.md5(bts).digest():
            print(f"  ⚠ RUECKSTAND in {fn}")
print(f"\n{gut} von {len(PROBEN)} beissen einzeln.")
sys.exit(0 if gut == len(PROBEN) else 1)
