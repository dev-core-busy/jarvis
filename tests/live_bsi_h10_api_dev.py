#!/usr/bin/env python3
"""LIVE auf DEV: die H10-Endpunkte im LAUFENDEN Dienst.

    sudo -u jarvis /opt/jarvis/venv/bin/python tests/live_bsi_h10_api_dev.py

* GET /api/security/sandbox?live=1 – Status mit H10-Teil und Live-Test.
* POST /api/security/sandbox/config – kein Text als Schalter, Grenzen werden
  geklemmt, die Antwort nennt die WIRKSAMEN Werte.
* POST /api/security/sandbox/teardown – gibt es nicht mehr.
Der vorgefundene Zustand (Schalter + Grenzen) wird am Ende WIEDERHERGESTELLT –
gelesen, nicht geraten (Register).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
from backend import main as M  # noqa: E402

TOKEN = M.generate_token("jarvis")      # lokaler Administrator (require_local_auth)
BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


def rufe(methode, pfad, rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    req = urllib.request.Request(BASIS + pfad, data=daten, method=methode, headers={
        "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=_KTX, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


code, st = rufe("GET", "/api/security/sandbox?live=1")
if code != 200 or not isinstance(st.get("h10"), dict):
    print(f"ABBRUCH: Status nicht lesbar ({code}) – Positivkontrolle fehlt: {str(st)[:200]}")
    sys.exit(2)
vorher = {"auch_admins": st["h10"].get("auch_admins") is True, **(st["h10"].get("grenzen") or {})}
print("vorgefunden:", vorher)
try:
    check("Status: Pflicht-Sandbox gemeldet", st.get("pflicht") is True and st.get("active") is True)
    iso = st.get("isolation") or {}
    check("Live: Loopback aus der Sandbox zu", iso.get("loopback_offen") is False, str(iso))
    check("Live: Grenzen anwendbar", iso.get("grenzen_anwendbar") is True, str(iso))
    check("Live: Secrets nicht lesbar", iso.get("secret_readable") is False, str(iso))
    check("Gesamtstatus ok", st.get("ok") is True)

    code, r = rufe("POST", "/api/security/sandbox/config", {"auch_admins": "true"})
    check("Schalter als Text -> 400", code == 400, f"{code} {r}")
    code, r = rufe("POST", "/api/security/sandbox/config",
                   {"speicher_mb": 0, "prozesse": 99999, "cpu_prozent": "x"})
    g = r.get("grenzen") or {}
    check("Grenzen geklemmt (0 -> 128, 99999 -> 4096, Text -> Vorgabe 200)",
          code == 200 and g == {"speicher_mb": 128, "prozesse": 4096, "cpu_prozent": 200}, f"{code} {g}")
    code, st2 = rufe("GET", "/api/security/sandbox")
    check("Status zeigt dieselben wirksamen Werte", (st2.get("h10") or {}).get("grenzen") == g,
          str((st2.get("h10") or {}).get("grenzen")))
    code, r = rufe("POST", "/api/security/sandbox/config", {"auch_admins": not vorher["auch_admins"]})
    check("Schalter umlegbar", code == 200 and r.get("auch_admins") is (not vorher["auch_admins"]), str(r))

    code, _ = rufe("POST", "/api/security/sandbox/teardown")
    check(f"'Sandbox deaktivieren' gibt es nicht mehr ({code})", code in (404, 405))
finally:
    code, r = rufe("POST", "/api/security/sandbox/config", vorher)
    wieder = {"auch_admins": r.get("auch_admins"), **(r.get("grenzen") or {})}
    check("vorgefundener Zustand wiederhergestellt", code == 200 and wieder == vorher, f"{wieder} != {vorher}")

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 and _ok > 0 else 1)
