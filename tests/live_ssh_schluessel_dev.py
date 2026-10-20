#!/usr/bin/env python3
"""Live-Probe: SSH-Schluessel per Oberflaeche hinterlegen und entfernen – ECHTER Weg.

Backend-Endpunkt -> Broker (root) -> authorized_keys. Laeuft AUF dem Server im
Dienst-Kontext (Tokens brauchen den Hauptschluessel):

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_ssh_schluessel_dev.py

Die Freigabe-Codes kann der Dienstbenutzer NICHT selbst rechnen (das Geheimnis
liegt root-eigen im Broker – genau das ist die Schranke). root legt sie vorher
in die Datei ``JARVIS_PROBE_CODES`` (Vorgabe /run/jv_probe/codes, zwei Codes
fuer aufeinanderfolgende Zeitschritte; Verzeichnis und Datei gehoeren dem
Dienstbenutzer, 0700/0600 – sonst darf die Probe sie nicht loeschen).
Die Probe loescht die Datei nach dem Lesen.

Was sich aendert: ein frisch erzeugter Testschluessel wird beim Konto
``JARVIS_PROBE_KONTO`` (Vorgabe root) hinterlegt und wieder entfernt; am Ende
muss die Schluesselliste wieder GENAU dem Vorzustand entsprechen. Die zwei
Codes sind danach verbraucht (gemeinsamer Wiederholschutz mit der Anmeldung).
Den Aussperr-Schutz prueft diese Probe bewusst NICHT – er wuerde hier am
echten Zugangsschluessel gemessen; das tut tests/test_fernzugang.py im
Sandkasten.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
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


def schluessel_von(st, konto):
    for k in st.get("konten") or []:
        if k.get("name") == konto:
            return sorted(s.get("fingerabdruck", "") for s in k.get("schluessel") or [])
    return None


# Codes zuerst lesen und die Datei sofort entfernen – auch bei einem Abbruch danach
pfad_codes = os.environ.get("JARVIS_PROBE_CODES") or "/run/jv_probe/codes"
try:
    with open(pfad_codes, encoding="ascii") as f:
        CODES = f.read().split()
except OSError as e:
    print("ABBRUCH: keine Freigabe-Codes (%s) – root muss sie vorher ablegen" % e)
    sys.exit(2)
try:
    os.unlink(pfad_codes)
except OSError as e:
    print("  (Codedatei nicht loeschbar: %s – root raeumt sie ab)" % e)
if len(CODES) != 2 or not all(c.isdigit() and len(c) == 6 for c in CODES):
    print("ABBRUCH: Codedatei hat nicht zwei 6-stellige Codes")
    sys.exit(2)

from backend import main as M  # noqa: E402

ADMIN = os.environ.get("JARVIS_DEV_ADMIN") or "jarvis"
KONTO = os.environ.get("JARVIS_PROBE_KONTO") or "root"
TA = M.generate_token(ADMIN)
code, me = ruf("/api/me", TA)
if code != 200 or not me.get("is_admin"):
    print("ABBRUCH: %s ist hier kein Admin (/api/me %s) – JARVIS_DEV_ADMIN setzen" % (ADMIN, code))
    sys.exit(2)
code, st = ruf("/api/broker/ssh/status", TA)
VORHER = schluessel_von(st, KONTO) if code == 200 else None
if VORHER is None:
    print("ABBRUCH: Konto %s nicht in der Kontenliste (Status %s)" % (KONTO, code))
    sys.exit(2)
print("Vorzustand %s: %d Schluessel" % (KONTO, len(VORHER)))

# Testschluessel: echt erzeugt, Fingerabdruck vom echten ssh-keygen
tmp = tempfile.mkdtemp(prefix="jv_probe_ssh_")
try:
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "jarvis-probe",
                    "-f", os.path.join(tmp, "k")], check=True)
    PUB = open(os.path.join(tmp, "k.pub"), encoding="ascii").read().strip()
    FP = subprocess.run(["ssh-keygen", "-lf", os.path.join(tmp, "k.pub")], capture_output=True,
                        text=True, check=True).stdout.split()[1]
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("── Rechte und Abweisungen (ohne Code)")
check(ruf("/api/broker/ssh/schluessel", None, {"aktion": "hinzufuegen"})[0] == 401, "ohne Anmeldung 401")
nutzer = os.environ.get("TRACKS_TESTUSER") or ziele.wert("JARVIS_DEV_TESTUSER")
tn = M.generate_token(nutzer)
c, me2 = ruf("/api/me", tn)
if c == 200 and not me2.get("is_admin"):
    c, r = ruf("/api/broker/ssh/schluessel", tn,
               {"aktion": "hinzufuegen", "konto": KONTO, "schluessel": PUB, "nachweis": CODES[0]})
    check(c == 403, "Nicht-Admin -> 403 (Code wird dabei nicht verbraucht)", (c, r))
else:
    print("  (Nicht-Admin-Probe uebersprungen: %s ist Admin oder unbekannt)" % nutzer)
c, r = ruf("/api/broker/ssh/schluessel", TA, {"aktion": "hinzufuegen", "konto": KONTO, "schluessel": PUB})
check(c == 403 and r.get("grund") == "nachweis_fehlt", "ohne Code -> 403 nachweis_fehlt", (c, r))
c, r = ruf("/api/broker/ssh/schluessel", TA, {"aktion": "irgendwas"})
check(c == 400, "unbekannte Aktion -> 400", c)
check(schluessel_von(ruf("/api/broker/ssh/status", TA)[1], KONTO) == VORHER,
      "nach den Abweisungen unveraendert")

print("── Hinterlegen und Entfernen (mit Code)")
c, r = ruf("/api/broker/ssh/schluessel", TA,
           {"aktion": "hinzufuegen", "konto": KONTO, "schluessel": PUB, "nachweis": CODES[0]})
check(c == 200 and r.get("ok") is True and r.get("neu") is True and r.get("fingerabdruck") == FP,
      "hinzufuegen: 200, neu, Fingerabdruck = ssh-keygen", (c, r))
DANACH = schluessel_von(ruf("/api/broker/ssh/status", TA)[1], KONTO)
check(DANACH == sorted(VORHER + [FP]), "Status zeigt genau den neuen Schluessel zusaetzlich", DANACH)
c, r = ruf("/api/broker/ssh/schluessel", TA,
           {"aktion": "entfernen", "konto": KONTO, "fingerabdruck": FP, "nachweis": CODES[1]})
check(c == 200 and r.get("ok") is True, "entfernen: 200", (c, r))
ZUM_SCHLUSS = schluessel_von(ruf("/api/broker/ssh/status", TA)[1], KONTO)
check(ZUM_SCHLUSS == VORHER, "Schluesselliste wieder GENAU wie vorher", ZUM_SCHLUSS)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
