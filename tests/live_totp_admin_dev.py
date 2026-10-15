#!/usr/bin/env python3
"""Live auf DEV: Admin-Ruecksetzung der Zwei-Faktor-Anmeldung (/api/admin/totp/*).

Gefahren wird ueber den ECHTEN HTTPS-Endpunkt des laufenden Dienstes.

Grenze dieser Probe: den ERFOLGSWEG kann sie nicht gehen – er verlangt das
Kennwort des Administrators, und das hat eine Probe nicht (und soll es nicht
haben). Der ist im Waechter test_totp_admin_reset.py ausgefuehrt; hier wird
gemessen, was ohne Kennwort messbar ist: Liste, Abweisungen, und dass bei jeder
Abweisung NICHTS am Zustand geschieht.

Zustand: ein PROBEKONTO (eindeutiger Name je Lauf, Secret ohne Wert) wird in
auth_state.json eingetragen und im finally wieder ENTFERNT – nur dieser eine
Schluessel, die Datei wird nicht als Ganzes zurueckgeschrieben (der Dienst
schreibt sie bei Anmeldungen selbst).

Aufruf: cd /opt/jarvis && runuser -u jarvis -- env PYTHONDONTWRITEBYTECODE=1 \
            HOME=/home/jarvis venv/bin/python tests/live_totp_admin_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import ssl
import sys
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


def ruf(pfad, token, rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method="POST" if daten is not None else "GET")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            roh = a.read()
            return a.status, roh
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def js(roh):
    try:
        return json.loads(roh.decode() or "{}")
    except Exception:  # noqa: BLE001
        return {}


from backend import main as M  # noqa: E402

ADMIN = ziele.wert("JARVIS_DEV_TESTUSER")
TOK = M.generate_token(ADMIN)
PROBE = "zz-probe-2fa-%d" % os.getpid()
SECRET = "PROBESECRET%dXYZ" % os.getpid()

print("Live DEV: 2FA-Ruecksetzung durch Administratoren (Probekonto %s)" % PROBE)
st, roh = ruf("/api/admin/totp/users", TOK)
if st != 200:
    print("NICHT PRUEFBAR: /api/admin/totp/users -> %s (Testkonto %s kein Administrator?)" % (st, ADMIN))
    sys.exit(2)
check(True, "(Positivkontrolle) Testkonto ist Administrator, Liste erreichbar")

vorher_users = set((M._load_auth_state().get("users") or {}).keys())
if PROBE in vorher_users:
    print("NICHT PRUEFBAR: Probekonto existiert schon")
    sys.exit(2)


def probe_zustand():
    return (M._load_auth_state().get("users") or {}).get(PROBE)


try:
    M._set_user_auth_state(PROBE, {"must_change_password": False, "totp_enabled": True,
                                   "totp_secret": SECRET, "totp_pending_secret": None})
    soll = probe_zustand()
    check(bool(soll and soll.get("totp_enabled")), "(Positivkontrolle) Probekonto mit 2FA angelegt")

    st, roh = ruf("/api/admin/totp/users", TOK)
    d = js(roh)
    namen = [u.get("user") for u in d.get("users", [])]
    check(st == 200 and PROBE in namen, "Probekonto erscheint in der Liste", str(namen)[:200])
    check(SECRET.encode() not in roh, "kein Secret in der Antwort")
    check(all(set(u) == {"user", "display", "self"} for u in d.get("users", [])), "nur Namen und Markierung")

    # ⚠ KEIN Fall mit FALSCHEM Kennwort: das Testkonto ist ein AD-Konto, und
    # jeder Fehlversuch zaehlt gegen die Sperrschwelle der Domaene (3 Versuche,
    # 30 Minuten, gilt auch fuer Windows). Alle Faelle hier werden VOR der
    # Kennwortpruefung abgewiesen; "falsches Kennwort" misst der Waechter mit
    # Attrappe (test_totp_admin_reset.py).
    FAELLE = [
        ("ohne Anmeldung", None, {"user": PROBE, "password": "x"}, 401),
        ("ohne Kennwort", TOK, {"user": PROBE}, 400),
        ("eigenes Konto", TOK, {"user": ADMIN, "password": "egal"}, 400),
        ("Rumpf keine Zuordnung", TOK, ["x"], 400),
    ]
    for name, tok, rumpf, code in FAELLE:
        st, roh = ruf("/api/admin/totp/reset", tok, rumpf)
        check(st == code and probe_zustand() == soll, "%s -> %d, Probekonto unveraendert" % (name, code),
              "%s %s" % (st, roh[:160]))
finally:
    st_ = M._load_auth_state()
    if PROBE in (st_.get("users") or {}):
        del st_["users"][PROBE]
        M._save_auth_state(st_)
    nachher = set((M._load_auth_state().get("users") or {}).keys())
    check(PROBE not in nachher, "Probekonto wieder entfernt")
    check(nachher == vorher_users, "Kontenliste wie vorgefunden")

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
