#!/usr/bin/env python3
"""Live auf DEV: die Wissens-Endpunkte antworten nach dem Umzug in Threads
unveraendert, und ``/api/health`` bleibt waehrenddessen frei.

Anlass: ECHT 2026-11-16, Event-Loop hing alle 2-5 s fuer 0,5-4 s (104-MB-
``faiss_meta.json`` je Abruf geparst, Wiki-Index je Seite geschrieben).
Waechter ``test_eventloop_wissen.py``; diese Probe belegt, dass der echte Dienst
dieselben Felder liefert. Veraendert NICHTS (nur GET).

Aufruf auf dem Server (seit BSI M5 nur mit Hauptschluessel):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_eventloop_wissen_dev.py
"""
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def ruf(pfad, token=None):
    r = urllib.request.Request(BASIS + pfad)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}"), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, {}, time.time() - t0


from backend import main as M  # noqa: E402

BENUTZER = ziele.wert("JARVIS_DEV_TESTUSER")
if not BENUTZER:
    print("ABBRUCH (Exit 2): JARVIS_DEV_TESTUSER fehlt")
    sys.exit(2)
TOK = M.generate_token(M._display_name(BENUTZER) if hasattr(M, "_display_name") else BENUTZER)

st, _d, _t = ruf("/api/me", TOK)
if st != 200:
    print(f"ABBRUCH (Exit 2): Token gilt im Dienst nicht ({st}) – ueber als_dienst.sh starten?")
    sys.exit(2)

# Health-Abtastung parallel zu den Endpunkt-Abrufen
_latenz = []
_stop = threading.Event()


def _abtasten():
    while not _stop.is_set():
        _s, _x, t = ruf("/api/health")
        _latenz.append(t)
        time.sleep(0.05)


th = threading.Thread(target=_abtasten, daemon=True)
th.start()
ergebnisse = {}
for _runde in range(3):
    for pfad in ("/api/wissen/scope", "/api/knowledge/groups", "/api/knowledge/groups/ungrouped",
                 "/api/knowledge/stats"):
        ergebnisse[pfad] = ruf(pfad, TOK)
_stop.set()
th.join(5)

s, d, t = ergebnisse["/api/wissen/scope"]
check(s == 200 and d.get("ok") is True, "/api/wissen/scope 200 + ok", (s, d.get("error")))
check({"user", "is_editor", "is_admin", "groups", "folders"} <= set(d), "scope traegt alle Felder",
      sorted(d))
check(all("display" in f for f in d.get("folders", [])), "jeder Ordner traegt `display`")
s, d, t = ergebnisse["/api/knowledge/groups"]
check(s == 200 and d.get("ok") is True and isinstance(d.get("groups"), list),
      "/api/knowledge/groups 200 + Gruppenliste", (s, list(d)[:5]))
s, d, t = ergebnisse["/api/knowledge/groups/ungrouped"]
check(s == 200 and isinstance(d.get("files"), list), "/api/knowledge/groups/ungrouped 200 + Dateiliste",
      (s, list(d)[:5]))
s, d, t = ergebnisse["/api/knowledge/stats"]
check(s == 200 and {"vector_chunks", "vector_files", "indexed_files"} <= set(d),
      "/api/knowledge/stats 200 + Zaehler", (s, list(d)[:8]))
check(ruf("/api/wissen/scope")[0] == 401, "ohne Token 401")
check(len(_latenz) >= 5, "Positivkontrolle: Health wurde abgetastet", len(_latenz))
check(max(_latenz or [9]) < 1.0, "Health blieb waehrend der Abrufe unter 1 s",
      "max %.2f s" % max(_latenz or [9]))
print("  (Health: %d Proben, max %.3f s)" % (len(_latenz), max(_latenz or [0])))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
