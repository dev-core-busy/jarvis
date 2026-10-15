#!/usr/bin/env python3
"""Live auf DEV: Protokoll der Cron-Aufgaben am ECHTEN Dienst (Vorgabe 2026-09-28).

Loest den Wissensabgleich EINMAL ueber "Jetzt ausfuehren" aus (derselbe Weg wie
der Knopf) und misst, dass genau dieser Lauf im Protokoll ankommt – als
manueller Lauf, mit Person, mit dem Ergebnis, das der Endpunkt zurueckgab.

⚠ WAS DIE PROBE VERAENDERT: ein echter Lauf des Wissensabgleichs (er indiziert
nur, wenn sich etwas geaendert hat) – damit auch ``last_run``/``last_result``
des Auftrags und EIN Protokolleintrag. Zeitplan, Schalter und Text des Auftrags
fasst sie NICHT an; sie werden am Ende gegen den vorgefundenen Stand geprueft.

Ohne den Auftrag ``wissensabgleich``: Exit 2.
"""
import json
import os
import ssl
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import main as M                                      # noqa: E402

BENUTZER = os.environ.get("CRON_TESTUSER") or "jarvis"
TOKEN = M.generate_token(BENUTZER)
JID = "wissensabgleich"


def ruf(pfad, methode="GET"):
    r = urllib.request.Request(BASIS + pfad, method=methode, data=b"" if methode == "POST" else None)
    r.add_header("Authorization", "Bearer " + TOKEN)
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=300) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}


st, jobs = ruf("/api/cron")
job = next((j for j in (jobs if isinstance(jobs, list) else []) if j.get("id") == JID), None)
if st != 200 or job is None:
    print("ABBRUCH: Auftrag %r nicht sichtbar (HTTP %s)" % (JID, st))
    sys.exit(2)
KONFIG = {k: job.get(k) for k in ("cron", "enabled", "task", "label", "once")}

print("\n1. Protokoll vor dem Lauf")
st, vor = ruf("/api/cron/%s/log?limit=500" % JID)
check("(Positivkontrolle) Endpunkt antwortet ok", st == 200 and vor.get("ok") is True, str(st))
n0 = len(vor.get("eintraege") or [])

print("\n2. 'Jetzt ausfuehren'")
st, lauf = ruf("/api/cron/%s/run" % JID, "POST")
check("(Positivkontrolle) Lauf ok", st == 200 and lauf.get("ok") is True, str(lauf)[:200])

print("\n3. Der Lauf steht im Protokoll")
st, nach = ruf("/api/cron/%s/log?limit=500" % JID)
es = nach.get("eintraege") or []
e = es[0] if es else {}
check("genau EIN Eintrag mehr", len(es) == n0 + 1, "%d -> %d" % (n0, len(es)))
check("⚠ als manueller Lauf mit Person", e.get("ausloeser") == "manuell" and e.get("von") == BENUTZER, str(e)[:200])
check("⚠ mit dem Ergebnis, das der Endpunkt meldete",
      (e.get("ergebnis") or "")[:500] == (lauf.get("result") or ""), "%r / %r" % (e.get("ergebnis"), lauf.get("result")))
check("Status erfolgreich, Dauer da", e.get("ok") is True and isinstance(e.get("dauer_s"), (int, float)), str(e)[:200])

print("\n4. Sichtbarkeit und Ablage")
st, _ = ruf("/api/cron/gibt-es-nicht/log")
check("unbekannter Auftrag: 404", st == 404, str(st))
p = Path("/opt/jarvis/data/logs/cron/%s.jsonl" % JID)
check("Datei liegt unter data/logs/cron", p.is_file())
if p.is_file():
    s = p.stat()
    check("Datei 0640", stat.S_IMODE(s.st_mode) == 0o640, oct(stat.S_IMODE(s.st_mode)))

print("\n5. Auftrag unveraendert")
st, jobs = ruf("/api/cron")
job2 = next((j for j in jobs if j.get("id") == JID), {})
check("Zeitplan, Schalter, Text wie vorgefunden",
      {k: job2.get(k) for k in KONFIG} == KONFIG, str({k: job2.get(k) for k in KONFIG}))

print("\nErgebnis: %d/%d" % (_ok, _ok + _fail))
sys.exit(1 if _fail else 0)
