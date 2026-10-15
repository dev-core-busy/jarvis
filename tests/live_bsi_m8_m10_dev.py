"""Live auf DEV: BSI M8 (Journal) und M10 (Deny-by-default) am laufenden Dienst.

  M8  A. Der laufende Backend-Prozess traegt weder adm noch systemd-journal.
      B. Als Dienstbenutzer ist das Journal einer FREMDEN Einheit leer …
      C. … das der eigenen Dienste kommt ueber die Broker-Op journal_lesen
         (Positivkontrolle: Zeilen von jarvis.service), eine fremde Einheit
         weist der Broker ab.
  M10 D. /api/security/zugangsregeln: keine Route ohne Regel, keine verwaiste
         Ausnahme; Stichproben: Ausnahme offen, Dependency-Route 401.
      E. /ws: eine NICHT angemeldete Verbindung bekommt keine Rundsendung
         (CPU-Last), nach "hello" mit Sitzung schon (Positivkontrolle).
      F. /api/vision/stream nimmt den alten Vorgabeschluessel nicht mehr.

Aufruf (Token brauchen den Hauptschluessel, BSI M5):
  bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python tests/live_bsi_m8_m10_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import asyncio
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402

try:
    from websockets.sync.client import connect
except ImportError:
    print("NICHT PRUEFBAR: websockets fehlt (venv/bin/python verwenden)")
    sys.exit(2)

BASIS, WSS = "https://127.0.0.1", "wss://127.0.0.1"
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


def ruf(pfad, token=None):
    r = urllib.request.Request(BASIS + pfad)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            return a.status, a.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


if os.geteuid() == 0:
    print("NICHT PRUEFBAR: als root gestartet – die Probe misst den DIENSTBENUTZER (als_dienst.sh)")
    sys.exit(2)

# ── M8 ──
print("Live DEV: BSI M8 / M10")
pid = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value", "jarvis.service"],
                     capture_output=True, text=True).stdout.strip()
gruppen = ""
try:
    gruppen = next(z for z in open("/proc/%s/status" % pid) if z.startswith("Groups:"))
except Exception as e:  # noqa: BLE001
    print("NICHT PRUEFBAR: Prozess des Dienstes nicht lesbar (%s)" % e)
    sys.exit(2)
import grp  # noqa: E402
gids = {grp.getgrnam(g).gr_gid for g in ("adm", "systemd-journal")}
check(not (set(gruppen.split()[1:]) & {str(g) for g in gids}),
      "A: laufendes Backend ohne adm/systemd-journal", gruppen.strip())
check(not (set(os.getgroups()) & gids), "A: Probe (Dienstkontext) ohne die Gruppen", os.getgroups())

fremd = subprocess.run(["journalctl", "-u", "ssh", "-u", "cron", "-n", "20", "--no-pager", "-o", "cat"],
                       capture_output=True, text=True)
check(not fremd.stdout.strip(), "B: fremdes Journal als Dienstbenutzer leer", fremd.stdout[:120])

from backend import broker_client  # noqa: E402


async def _op(args):
    return await broker_client.call("journal_lesen", args, user="live-probe", timeout=60)

r = asyncio.run(_op({"einheit": "jarvis", "zeilen": 20}))
zeilen = [z for z in str(r.get("stdout") or "").splitlines() if z.strip()]
check(r.get("ok") is True and len(zeilen) >= 1,
      "C: journal_lesen liefert Zeilen von jarvis.service (Positivkontrolle)",
      (r.get("decision"), r.get("rc"), r.get("stderr", "")[:120], len(zeilen)))
r2 = asyncio.run(_op({"einheit": "ssh"}))
check(r2.get("rc") == 2 and "nicht erlaubt" in str(r2.get("stderr")), "C: fremde Einheit abgewiesen", r2)

# ── M10 ──
from backend import main as M  # noqa: E402
ADMIN = ziele.wert("JARVIS_DEV_TESTUSER")
TOK = M.generate_token(ADMIN, mit_2fa=True)
M._sitzung.flush()
try:
    st, roh = ruf("/api/security/zugangsregeln", TOK)
    z = json.loads(roh) if st == 200 else {}
    check(st == 200 and z.get("routen", 0) > 300, "D: Ueberblick abrufbar (%s Routen)" % z.get("routen"), st)
    check(z.get("ohne_regel") == [], "D: keine Route ohne Regel", z.get("ohne_regel"))
    check(z.get("verwaiste_ausnahmen") == [], "D: keine verwaiste Ausnahme", z.get("verwaiste_ausnahmen"))
    check(ruf("/api/health")[0] == 200, "D: Ausnahme /api/health ohne Anmeldung 200")
    check(ruf("/")[0] == 200, "D: Startseite ohne Anmeldung 200")
    check(ruf("/api/me")[0] == 401, "D: Dependency-Route ohne Anmeldung 401")
    check(ruf("/api/security/zugangsregeln")[0] == 401, "D: Ueberblick ohne Anmeldung 401")

    def _cpu_in(ws, sek):
        ende = time.time() + sek
        while time.time() < ende:
            try:
                m = json.loads(ws.recv(timeout=max(0.1, ende - time.time())))
            except TimeoutError:
                return False
            except Exception:  # noqa: BLE001
                return False
            if m.get("type") == "cpu":
                return True
        return False

    with connect(WSS + "/ws", ssl=CTX, open_timeout=30) as ws:
        check(not _cpu_in(ws, 5), "E: /ws ohne Anmeldung: keine Rundsendung in 5 s")
        ws.send(json.dumps({"type": "hello", "token": TOK}))
        check(_cpu_in(ws, 6), "E: nach hello mit Sitzung: Rundsendung kommt (Positivkontrolle)")

    st, _ = ruf("/api/vision/stream?key=jarvis-stream")
    check(st == 401, "F: alter Vorgabeschluessel am Vision-Stream abgewiesen", st)
finally:
    try:
        u, ts, sig = TOK.split(":", 2)
        M._sitzung.widerrufe(sig, int(ts))
    except Exception as e:  # noqa: BLE001
        print("  !!   Probe-Sitzung nicht widerrufen: %s" % e)
    M._sitzung.flush()

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
