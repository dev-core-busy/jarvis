#!/usr/bin/env python3
"""Live auf DEV: BSI H3 am laufenden Dienst (Laufzeit, Leerlauf, Abmelden).

Gefahren wird ueber den ECHTEN HTTPS-Endpunkt; die Tokens stellt
``main.generate_token`` aus (wie in den uebrigen live_*_dev.py). Der Dienst
kennt diese Tokens nicht – genau der Fall "unbekannt = zuletzt gesehen bei
Ausstellung".

Veraendert: ein Probe-Token wird widerrufen (nur dieses; andere Sitzungen des
Benutzers bleiben unberuehrt), und die Anwesenheit vermerkt eine Abmeldung,
bis die naechste echte Anfrage des Benutzers sie wieder aufhebt.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
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


def ruf(pfad, token, methode="GET"):
    r = urllib.request.Request(BASIS + pfad, data=b"{}" if methode == "POST" else None,
                               method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if methode == "POST":
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=30) as a:
            return a.status
    except urllib.error.HTTPError as e:
        return e.code


from backend import main as M                                    # noqa: E402

BENUTZER = os.environ.get("TRACKS_TESTUSER") or ziele.wert("JARVIS_DEV_TESTUSER")
jetzt = int(time.time())

t1 = M.generate_token(BENUTZER)
if ruf("/api/me", t1) != 200:
    print("ABBRUCH: Positivkontrolle – frisches Token wird abgelehnt")
    sys.exit(2)
check(True, "frisches Token: /api/me 200 (Positivkontrolle)")

check(ruf("/api/me", M.generate_token(BENUTZER, ts=jetzt - 13 * 3600)) == 401,
      "13 h altes Token -> 401 (vorher 30 Tage gueltig)")
check(ruf("/api/me", M.generate_token(BENUTZER, ts=jetzt - 3 * 3600)) == 401,
      "3 h ohne Anfrage -> 401 (Leerlauf)")
check(ruf("/api/me", M.generate_token(BENUTZER, ts=jetzt - 90 * 60)) == 200,
      "90 min alt, Leerlauf nicht erreicht -> 200")

time.sleep(1.1)                         # zweites Token mit anderem Zeitstempel
t2 = M.generate_token(BENUTZER)
check(ruf("/api/logout", t1, "POST") == 200, "Abmelden -> 200")
check(ruf("/api/me", t1) == 401, "abgemeldetes Token -> 401 (vorher weiter gueltig)")
check(ruf("/api/me", t2) == 200, "zweites Token desselben Benutzers -> weiter 200")

ablage = "/opt/jarvis/data/auth_sitzungen.json"
if os.path.exists(ablage):
    modus = os.stat(ablage).st_mode & 0o777
    check(modus & 0o007 == 0, "Ablage nicht weltlesbar (%o)" % modus)
    roh = open(ablage, encoding="utf-8").read()
    check(t1.rsplit(":", 1)[-1] not in roh, "Ablage enthaelt die Signatur nicht")
else:
    check(False, "Ablage nach dem Abmelden vorhanden")

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
