#!/usr/bin/env python3
"""Live auf DEV: steht in "Angemeldete Benutzer" die GENAUE Handlung?

Gemeldet 2026-09-27: bei Short-Tracks-Nutzung nur "Aktion". Gefahren wird
ueber den ECHTEN HTTPS-Endpunkt gegen den laufenden Dienst; gelesen wird die
Liste ueber /api/sessions (wie das Portal).

Veraendert NICHTS: geloescht wird ein Lauf, den es nicht gibt (die Handlung
wird in require_auth verbucht, bevor der Endpunkt 404 antwortet), und
/api/activity schreibt nur die Anwesenheit.
"""
import json
import os
import ssl
import sys
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


def ruf(pfad, token, methode="GET", rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=30) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                        # noqa: BLE001
            return e.code, {}


from backend import main as M                                    # noqa: E402

BENUTZER = os.environ.get("TRACKS_TESTUSER") or ziele.wert("JARVIS_DEV_TESTUSER")
tok = M.generate_token(BENUTZER)


def label():
    st, d = ruf("/api/sessions", tok)
    if st != 200:
        return st, None
    for u in d.get("users", []):
        if u.get("username") == BENUTZER:
            return st, u.get("last_action_label")
    return st, None


print("Live DEV: Beschriftung der letzten Handlung")
st, _ = label()
if st != 200:
    print(f"NICHT PRUEFBAR: /api/sessions -> {st} (Benutzer {BENUTZER} kein Admin?)")
    sys.exit(2)

st, _ = ruf("/api/tracks/jobs/__gibt_es_nicht__", tok, "DELETE")
check(st in (200, 403, 404), f"(Positivkontrolle) DELETE auf Short Tracks beantwortet ({st})")
time.sleep(0.3)
_, lb = label()
check(lb == "Short Tracks · Lauf entfernt",
      "⚠ Short Tracks: 'Short Tracks · Lauf entfernt' statt 'Aktion'", repr(lb))

st, _ = ruf("/api/activity", tok, "POST", {"page": "tracks"})
time.sleep(0.3)
_, lb = label()
check(st == 200 and lb == "Short Tracks", "Seite /tracks meldet 'Short Tracks'", f"{st} {lb!r}")

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
