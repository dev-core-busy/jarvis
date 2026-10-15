#!/usr/bin/env python3
"""Live-Probe: Fernzugang (SSH) ueber den ECHTEN Weg Backend -> Broker -> Skripte.

Laeuft AUF dem Server, im Dienst-Kontext (Tokens brauchen den Hauptschluessel):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_fernzugang_dev.py

Aendert NICHTS am Zugang: geprueft werden nur der Status, die Rechte der drei
Endpunkte und die Abweisungen (kein Code -> 403, kein Test -> 409). Es entstehen
nur Audit-Eintraege der abgewiesenen Versuche.

Admin-Konto: JARVIS_DEV_ADMIN (Vorgabe "jarvis"), Nicht-Admin: JARVIS_DEV_TESTUSER.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
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


def ruf(pfad, token=None, body=None):
    r = urllib.request.Request(BASIS + pfad, method="POST" if body is not None else "GET",
                               data=json.dumps(body).encode() if body is not None else None)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=120) as a:
            return a.status, json.loads(a.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


from backend import main as M  # noqa: E402

ADMIN = os.environ.get("JARVIS_DEV_ADMIN") or "jarvis"
TA = M.generate_token(ADMIN)
code, me = ruf("/api/me", TA)
if code != 200 or not me.get("is_admin"):
    print("ABBRUCH: %s ist hier kein Admin (/api/me %s) – JARVIS_DEV_ADMIN setzen" % (ADMIN, code))
    sys.exit(2)

print("── Status")
code, st = ruf("/api/broker/ssh/status", TA)
check(code == 200 and st.get("ok") is True, "Status 200 ueber den echten Broker", (code, st.get("error")))
check(bool(st.get("konten")), "Konten geliefert", st.get("konten"))
check(all(s.get("fingerabdruck", "").startswith("SHA256:")
          for k in st.get("konten") or [] for s in k.get("schluessel") or []),
      "Fingerabdruecke im SHA256-Format")
check(st.get("sshd", {}).get("passwordauthentication") in ("yes", "no"),
      "sshd -T gelesen", st.get("sshd"))
check(isinstance(st.get("firewall_eingerichtet"), bool), "Paketfilter-Zustand bekannt")
vs = st.get("vorschlaege") or {}
check(isinstance(vs.get("lokal"), list) and isinstance(vs.get("anmeldungen"), list)
      and isinstance(vs.get("tailscale"), bool), "Vorschlaege fuer den Netze-Helfer geliefert", vs)
check(all(not str(l.get("netz", "")).startswith("127.") for l in vs.get("lokal") or []),
      "kein Loopback unter den Vorschlaegen", vs.get("lokal"))
check(st.get("deine_adresse") == "127.0.0.1", "Adresse der Web-Sitzung (Probe laeuft lokal)",
      st.get("deine_adresse"))
vorher = (st.get("sshd"), st.get("haertung"), st.get("netze"))

print("── Rechte")
check(ruf("/api/broker/ssh/status")[0] == 401, "ohne Anmeldung 401")
nutzer = os.environ.get("TRACKS_TESTUSER") or ziele.wert("JARVIS_DEV_TESTUSER")
tn = M.generate_token(nutzer)
c, me2 = ruf("/api/me", tn)
if c == 200 and not me2.get("is_admin"):
    for pfad, body in (("/api/broker/ssh/status", None),
                       ("/api/broker/ssh/haertung", {"aktion": "aus"}),
                       ("/api/broker/ssh/netze", {"aktion": "verwerfen"})):
        check(ruf(pfad, tn, body)[0] == 403, "Nicht-Admin an %s -> 403" % pfad)
else:
    print("  (Nicht-Admin-Probe uebersprungen: %s ist Admin oder unbekannt)" % nutzer)

print("── Abweisungen")
c, r = ruf("/api/broker/ssh/haertung", TA, {"aktion": "aus"})
check(c == 403 and r.get("grund") in ("nachweis_fehlt", "nicht_eingerichtet"),
      "Haertung abschalten ohne Code -> 403", (c, r))
c, r = ruf("/api/broker/ssh/netze", TA, {"aktion": "test", "netze": "192.0.2.0/24"})
check(c == 403 and r.get("grund"), "Netze ohne Code -> 403", (c, r))
c, r = ruf("/api/broker/ssh/netze", TA, {"aktion": "verwerfen"})
check(c == 409 and "Kein laufender Test" in (r.get("meldung") or ""),
      "Verwerfen ohne laufenden Test -> 409", (c, r))
c, r = ruf("/api/broker/ssh/haertung", TA, {"aktion": "irgendwas"})
check(c == 400, "unbekannte Aktion -> 400", c)
code, st2 = ruf("/api/broker/ssh/status", TA)
check((st2.get("sshd"), st2.get("haertung"), st2.get("netze")) == vorher,
      "Zustand unveraendert nach den Abweisungen")

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
