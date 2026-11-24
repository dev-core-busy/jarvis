#!/usr/bin/env python3
"""Live-Probe: offene Paket-Updates, Einspielen, AIDE-Abgleich und Neustart
ueber den LAUFENDEN Dienst (Endpunkt -> Broker -> apt/AIDE/systemd).

SCHREIBEND und nur fuer DEV: "einspielen" hebt alle offenen Pakete, die
Uebernahme setzt einen neuen AIDE-Vergleichsstand, "neustart" startet einen
Dienst neu. Ein eingespieltes Update laesst sich nicht zuruecknehmen – das
ist der Zweck der Messung, nicht ihr Nebeneffekt.

Phasen (die AIDE-Pruefung dauert Minuten):
  lesen       GET /api/security/updates: Liste, needrestart, AIDE-Zustand
  einspielen  POST einspielen: Pakete gehoben, Broker-Audit fuehrt die Op,
              danach weniger offen, AIDE-Pruefung laeuft
  aide        wartet auf das Ende der Pruefung (bis 45 min) und prueft den
              Zustand; bei "offen": falsche Kennung -> 409, richtige -> ok
  aide-neu    stoesst die Pruefung selbst an (POST aide/pruefen), dann wie "aide"
  neustart    gesperrter Dienst -> 409; ein erlaubter -> ok und danach nicht
              mehr gelistet

Aufruf AUF dem Server (Token braucht den Hauptschluessel, siehe CLAUDE.md):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_paket_updates_dev.py <phase> [admin]
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
BASIS = "https://127.0.0.1"
AUDIT = Path("/var/log/jarvis-broker-audit.jsonl")
_KTX = ssl.create_default_context()
_KTX.check_hostname = False
_KTX.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


PHASE = sys.argv[1] if len(sys.argv) > 1 else ""
if PHASE not in ("lesen", "einspielen", "aide", "aide-neu", "neustart"):
    print(__doc__)
    sys.exit(2)

from backend import main as M                                      # noqa: E402

BENUTZER = sys.argv[2] if len(sys.argv) > 2 else "jarvis"
TOKEN = M.generate_token(BENUTZER)
M._sitzung.flush()


def ruf(pfad, methode="GET", rumpf=None, timeout=240):
    daten = json.dumps(rumpf).encode() if rumpf is not None else (b"" if methode == "POST" else None)
    r = urllib.request.Request(BASIS + pfad, method=methode, data=daten)
    r.add_header("Authorization", "Bearer " + TOKEN)
    if rumpf is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=timeout) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


def apt_bloecke_seit(t0):
    """Commandline-Zeilen der apt/history.log-Bloecke, die nach t0 begannen."""
    try:
        text = Path("/var/log/apt/history.log").read_text(errors="replace")
    except OSError:
        return None
    erg = []
    for block in text.split("\n\n"):
        s = next((z[12:].strip() for z in block.splitlines() if z.startswith("Start-Date: ")), "")
        c = next((z[13:].strip() for z in block.splitlines() if z.startswith("Commandline: ")), "")
        try:
            t = time.mktime(time.strptime(" ".join(s.split()), "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if t >= t0 - 2:
            erg.append(c)
    return erg


def gestartet_seit(dienst):
    import subprocess
    r = subprocess.run(["systemctl", "show", "--timestamp=unix", "-p", "ActiveEnterTimestamp", "--value", dienst],
                       capture_output=True, text=True, timeout=20)
    v = (r.stdout or "").strip()
    return float(v[1:]) if v.startswith("@") else 0.0


def audit_seit(t0, op):
    try:
        zeilen = AUDIT.read_text(errors="replace").splitlines()[-400:]
    except OSError:
        return None
    treffer = []
    for z in zeilen:
        try:
            e = json.loads(z)
        except ValueError:
            continue
        if e.get("op") == op and float(e.get("ts") or 0) >= t0 - 2:
            treffer.append(e)
    return treffer


# Admin-Rechte gibt es nur ueber das Zahnrad mit eigenem 2FA-Code (BSI M3) –
# der echte Weg, kein im Token nachgebautes Merkmal. Liegt das Geheimnis im
# Root-Broker, liefert tests/live_mit_brokercode.py die Codes.
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from zweifaktor_code import code_quelle  # noqa: E402
_auth = M._get_user_auth_state(BENUTZER)
if not _auth.get("totp_enabled"):
    print("NICHT PRUEFBAR: Konto %s hat keine 2FA – ohne Code gibt es keine Admin-Sitzung" % BENUTZER)
    sys.exit(2)
st, r = ruf("/api/admin/erhoehen", "POST", {"code": code_quelle(_auth.get("totp_secret"))()})
if st != 200 or not r.get("erhoeht"):
    print("NICHT PRUEFBAR: Erhoehung am Zahnrad gelang nicht -> %s %s" % (st, str(r)[:200]))
    sys.exit(2)

st, d = ruf("/api/security/updates")
check("Positivkontrolle: GET /api/security/updates antwortet 200", st == 200, "%s %s" % (st, str(d)[:200]))
if st != 200:
    print("ERGEBNIS: %d OK, %d FAIL" % (_ok, _fail))
    sys.exit(2)

if PHASE == "lesen":
    check("Liste der offenen Pakete vorhanden", isinstance(d.get("pakete"), list), str(d)[:200])
    check("Trockenlauf ohne Fehler", d.get("ok") is True and not d.get("fehler"), d.get("fehler", ""))
    check("needrestart-Auskunft vorhanden", isinstance((d.get("neustart") or {}).get("dienste"), list))
    a = d.get("aide") or {}
    check("AIDE-Abgleich eingerichtet", a.get("eingerichtet") is True, str(a)[:200])
    print("  offen: %d, davon Sicherheit %d, zurueckgehalten %d, Dienste mit altem Stand %d, AIDE %s"
          % (len(d.get("pakete") or []), sum(1 for p in d.get("pakete") or [] if p.get("sicherheit")),
             len(d.get("zurueckgehalten") or []), len((d.get("neustart") or {}).get("dienste") or []),
             (a.get("zustand") or {}).get("zustand")))

elif PHASE == "einspielen":
    vorher = len(d.get("pakete") or [])
    check("Vorbedingung: es ist etwas offen (%d)" % vorher, vorher > 0)
    t0 = time.time()
    st, r = ruf("/api/security/updates/einspielen", "POST", timeout=3000)
    dauer = time.time() - t0
    check("POST einspielen: 200 und ok (%.0f s)" % dauer, st == 200 and r.get("ok") is True,
          "%s %s" % (st, json.dumps(r.get("steps"), ensure_ascii=False)[:600]))
    for s in r.get("steps") or []:
        print("    %s %s%s" % ("✓" if s.get("ok") else "✗", s.get("name"), (" – " + s.get("detail")) if s.get("detail") and not s.get("ok") else ""))
    check("eingespielte Pakete benannt (%d)" % len(r.get("eingespielt") or []), len(r.get("eingespielt") or []) > 0)
    # Unabhaengige Quelle: das Broker-Audit ist fuer den Dienstbenutzer nicht
    # lesbar (root 0600) – apt/history.log schon (0644, schreibt nur dpkg selbst).
    bl = apt_bloecke_seit(t0)
    check("unabhaengige Quelle: apt/history.log fuehrt einen upgrade-Lauf mit --no-remove seit dem Aufruf",
          bl is not None and any("upgrade" in b and "--no-remove" in b for b in bl),
          "history.log nicht lesbar" if bl is None else "%d Bloecke" % len(bl))
    st, d2 = ruf("/api/security/updates")
    nachher = len(d2.get("pakete") or [])
    check("danach weniger offen (%d -> %d)" % (vorher, nachher), nachher < vorher)
    if r.get("hinweise"):
        print("  Hinweise der Pakete (apt-listchanges):\n    " + r["hinweise"][:600].replace("\n", "\n    "))
    a2 = d2.get("aide") or {}
    check("AIDE-Pruefung laeuft oder wurde angestossen", bool(a2.get("laeuft")) or any(
        "AIDE" in (s.get("name") or "") and s.get("ok") for s in r.get("steps") or []), str(a2)[:200])

elif PHASE in ("aide", "aide-neu"):
    t0 = time.time()
    if PHASE == "aide-neu":
        st, r = ruf("/api/security/aide/pruefen", "POST")
        check("POST aide/pruefen: Pruefung gestartet", st == 200 and r.get("ok"), "%s %s" % (st, str(r)[:200]))
        time.sleep(20)
        st, d = ruf("/api/security/updates")
    while time.time() - t0 < 45 * 60:
        a = d.get("aide") or {}
        if not a.get("laeuft"):
            break
        time.sleep(30)
        st, d = ruf("/api/security/updates")
    a = d.get("aide") or {}
    z = a.get("zustand") or {}
    check("Pruefung beendet", not a.get("laeuft"), str(a)[:200])
    check("Abgleich hat einen Zustand (%s)" % z.get("zustand"), z.get("zustand") in ("uebernommen", "offen", "unveraendert"),
          z.get("grund", ""))
    check("Abgleich frisch (juenger als 1 h)", time.time() - (z.get("zeit") or 0) < 3600, str(z.get("zeit")))
    if PHASE == "aide-neu":
        check("Abgleich stammt aus DIESER Pruefung", (z.get("zeit") or 0) >= t0, "%s < %s" % (z.get("zeit"), t0))
    print("  erklaert: %s" % json.dumps(z.get("erklaert"), ensure_ascii=False))
    print("  nicht erklaert: %s%s" % (z.get("offen_anzahl"), (" – " + z.get("grund")) if z.get("grund") else ""))
    for e in (z.get("offen") or [])[:15]:
        print("    %-9s %s  (%s)" % (e.get("art"), e.get("pfad"), e.get("warum")))
    if z.get("zustand") == "offen":
        st, r = ruf("/api/security/aide/uebernehmen", "POST", {"kennung": "0" * 16})
        check("fremde Kennung: abgelehnt (409)", st == 409 and not r.get("ok"), "%s %s" % (st, str(r)[:200]))
        st, d3 = ruf("/api/security/updates")
        check("danach weiter offen", ((d3.get("aide") or {}).get("zustand") or {}).get("zustand") == "offen")
        st, r = ruf("/api/security/aide/uebernehmen", "POST", {"kennung": z.get("kennung")})
        check("gesehene Kennung: uebernommen", st == 200 and r.get("ok"), "%s %s" % (st, str(r)[:200]))
        st, d4 = ruf("/api/security/updates")
        z4 = (d4.get("aide") or {}).get("zustand") or {}
        check("Zustand nennt den Uebernehmenden", z4.get("zustand") == "uebernommen" and bool(z4.get("uebernommen_von"))
              and z4.get("uebernommen_von") != "automatisch", str(z4.get("uebernommen_von")))

elif PHASE == "neustart":
    st, r = ruf("/api/security/updates/neustart", "POST", {"dienst": "dbus.service"})
    check("dbus.service: abgelehnt (409)", st == 409 and not r.get("ok"), "%s %s" % (st, str(r)[:200]))
    dienste = [x["name"] for x in (d.get("neustart") or {}).get("dienste") or [] if x.get("neustartbar")]
    kandidat = next((x for x in ("cron.service", "chrony.service", "colord.service") if x in dienste), None)
    if not kandidat:
        print("  NICHT GEPRUEFT: kein harmloser neustartbarer Dienst gelistet (%s)" % dienste)
    else:
        t0 = time.time()
        st, r = ruf("/api/security/updates/neustart", "POST", {"dienst": kandidat})
        check("%s: neu gestartet" % kandidat, st == 200 and r.get("ok"), "%s %s" % (st, str(r)[:200]))
        time.sleep(2)
        check("unabhaengige Quelle: systemd fuehrt einen Start von %s seit dem Aufruf" % kandidat,
              gestartet_seit(kandidat) >= t0 - 1, str(gestartet_seit(kandidat)))
        st, d2 = ruf("/api/security/updates")
        noch = [x["name"] for x in (d2.get("neustart") or {}).get("dienste") or []]
        check("%s danach nicht mehr mit altem Stand gelistet" % kandidat, kandidat not in noch, str(noch)[:200])

print("ERGEBNIS: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
