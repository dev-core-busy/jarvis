#!/usr/bin/env python3
"""Live auf DEV: Endpunkte mit eigener Token-Pruefung weisen ein GESPERRTES Konto ab
(BSI-Abgleich Abschnitt 5, Skill "avatar", 2026-10-13).

Gemessen gegen den LAUFENDEN Dienst mit dem AD-Testkonto:
  1. Positivkontrolle: mit gueltiger Sitzung antwortet ``/api/avatar/config`` 200.
  2. Konto sperren (wie ein Administrator) -> Avatar, Sprache und Support
     antworten 403; ``/api/avatar/config`` als Beleg, dass die Sperre im Dienst
     ankommt, und die uebrigen als Wirkung.
  3. Sperre aufheben -> wieder 200.

⚠ Die Probe sperrt das Testkonto fuer wenige Sekunden. War es vorher schon
gesperrt, bricht sie ab (Exit 2) und fasst nichts an. Am Ende wird der
VORGEFUNDENE Zustand hergestellt (entsperrt) und nachgeprueft; die
Probe-Sitzung wird widerrufen.

Aufruf (root): bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python tests/live_bsi_sitzung_sperre_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import http.client
import json
import os
import ssl
import sys

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))

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
        print("  FAIL %s%s" % (label, (" – %s" % str(detail)[:300]) if detail else ""))


def abbruch(text):
    print("NICHT PRUEFBAR: %s" % text)
    sys.exit(2)


def https(pfad, token, methode="GET", body=None):
    c = http.client.HTTPSConnection("127.0.0.1", 443, context=CTX, timeout=60)
    h = {"Authorization": "Bearer " + token}
    daten = None
    if body is not None:
        daten = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    c.request(methode, pfad, body=daten, headers=h)
    a = c.getresponse()
    a.read()
    c.close()
    return a.status


import ziele  # noqa: E402
from backend import main as M  # noqa: E402
from backend import security_guard as SG  # noqa: E402

# Die Form, die eine echte Anmeldung ins Token schreibt (Register: Backslash)
KONTO = M._display_name(ziele.wert("JARVIS_DEV_TESTUSER"))
if SG.is_blocked(KONTO):
    abbruch("Testkonto ist bereits gesperrt – Probe fasst nichts an")

TOK = M.generate_token(KONTO)
M._sitzung.flush()
gesperrt_durch_probe = False
try:
    try:
        st = https("/api/avatar/config", TOK)
    except OSError as e:
        abbruch("Dienst auf 443 nicht erreichbar: %s" % e)
    if st != 200:
        abbruch("Positivkontrolle: /api/avatar/config mit gueltiger Sitzung -> %s "
                "(ueber deploy/als_dienst.sh gestartet?)" % st)
    print("Gesperrtes Konto")
    gesperrt_durch_probe = SG.block(KONTO, reason="BSI-Probe Sitzungssperre", by="live_probe")
    if not gesperrt_durch_probe:
        abbruch("Sperre liess sich nicht setzen")
    for methode, pfad, body in [
        ("GET", "/api/avatar/config", None),
        ("GET", "/api/avatar/graphics", None),
        ("POST", "/api/avatar/ask", {"text": "Probe"}),
        ("POST", "/api/avatar/stop", {}),
        ("POST", "/api/tts", {"text": "Probe"}),
        ("GET", "/api/tts/voices", None),
        ("POST", "/api/support/query", {"query": "Probe"}),
        ("POST", "/api/support/summarize", {"text": "Probe"}),
    ]:
        st = https(pfad, TOK, methode, body)
        check(st == 403, "%s %s -> %s (erwartet 403)" % (methode, pfad, st))
finally:
    if gesperrt_durch_probe:
        SG.unblock(KONTO)
    try:
        u, ts, sig = TOK.rsplit(":", 2)
        st_nach = https("/api/avatar/config", TOK)
        M._sitzung.widerrufe(sig, int(ts))
        M._sitzung.flush()
    except Exception as e:  # noqa: BLE001
        st_nach = "Fehler %s" % e

print("Nach dem Entsperren")
check(not SG.is_blocked(KONTO), "Testkonto wieder frei (vorgefundener Zustand)")
check(st_nach == 200, "/api/avatar/config wieder 200", st_nach)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
