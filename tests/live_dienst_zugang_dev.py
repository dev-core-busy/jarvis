#!/usr/bin/env python3
"""Live-Probe auf DEV: eigener Zugang (PAT) fuer Loesungsarchiv und
Confluence-Einbindung ueber den ECHTEN Dienst (backend/dienst_zugang.py).

Gemessen ueber HTTPS gegen den laufenden Dienst und gegen das echte
Jira/Confluence:
  * ohne/mit Muell-Token 401, unbekannter Dienst 404
  * Positivkontrolle: der Verbindungstest mit dem GEMEINSAMEN Zugang gelingt
    (sonst waere "der Dienst-Token wird abgelehnt" kein Beleg)
  * ein Probe-Token wird gespeichert: Zustand "dienst", in settings.json
    VERPACKT (JGS1:), nicht im Klartext, GET der Skill-Config maskiert
  * ⚠ der Verbindungstest laeuft jetzt mit dem Probe-Token – der echte Server
    lehnt ihn ab. Das belegt, dass GENAU er gesendet wird und nicht still der
    gemeinsame
  * Entfernen stellt den gemeinsamen Zugang wieder her

⚠ SCHREIBT IN DIE SKILL-CONFIG – und raeumt ueber ``atexit`` wieder ab. Liegt
schon ein eigener Token, bricht die Probe ab (Exit 2): sie koennte ihn nicht
wiederherstellen, ohne ihn zu kennen, und ein geratener Leerwert waere eine
Aenderung, keine Wiederherstellung.

Aufruf (als root auf DEV):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_dienst_zugang_dev.py
"""
from __future__ import annotations

import atexit
import json
import secrets
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import main as M                                      # noqa: E402

TOKEN = M.generate_token("jarvis")
SETTINGS = Path("/opt/jarvis/data/settings.json")
DIENSTE = {"loesungsarchiv": ("jira", "loesungsarchiv_api_token"),
           "confluence_einbindung": ("confluence", "einbindung_api_token")}


def ruf(pfad, methode="GET", rumpf=None, token=TOKEN):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=120) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


def roh(skill, feld):
    d = json.loads(SETTINGS.read_text(encoding="utf-8"))
    return ((((d.get("skills") or {}).get(skill) or {}).get("config")) or {}).get(feld)


_gesetzt: list[str] = []


def _aufraeumen():
    for dienst in list(_gesetzt):
        st, _ = ruf("/api/dienstzugang/" + dienst, "DELETE")
        print("  [aufgeraeumt] %s → %s" % (dienst, st))


atexit.register(_aufraeumen)

print("\n0. Zugang zur Messung")
st, z = ruf("/api/dienstzugang/loesungsarchiv")
if st != 200:
    print("ABBRUCH: Admin-Token wird nicht angenommen (%s %s)" % (st, z))
    sys.exit(2)
check("ohne Token 401", ruf("/api/dienstzugang/loesungsarchiv", token=None)[0] == 401)
check("Muell-Token 401", ruf("/api/dienstzugang/loesungsarchiv", token="x.y.z")[0] == 401)
check("unbekannter Dienst 404", ruf("/api/dienstzugang/fremd")[0] == 404)

for dienst, (skill, feld) in DIENSTE.items():
    print("\n%s (%s)" % (dienst, skill))
    st, z = ruf("/api/dienstzugang/" + dienst)
    if z.get("token_gesetzt"):
        print("ABBRUCH: auf DEV liegt bereits ein eigener Token – die Probe faesst ihn nicht an")
        sys.exit(2)
    if not z.get("adresse_gesetzt") or z.get("quelle") != "sammel":
        print("  NICHT GEPRUEFT: %s hat keine Adresse oder keinen gemeinsamen Zugang (%s)" % (skill, z))
        continue
    vorher_roh = roh(skill, feld)
    st, t = ruf("/api/dienstzugang/%s/test" % dienst, "POST")
    check("Positivkontrolle: Verbindungstest mit dem gemeinsamen Zugang gelingt",
          st == 200 and t.get("ok") is True and t.get("quelle") == "sammel", t)
    st, f = ruf("/api/dienstzugang/" + dienst, "POST", {"token": "mit leerzeichen"})
    check("ungueltiger Token 400, nichts geschrieben", st == 400 and roh(skill, feld) == vorher_roh, (st, f))
    probe = "Probe" + secrets.token_hex(12)
    st, z = ruf("/api/dienstzugang/" + dienst, "POST", {"token": probe})
    if st == 200:
        _gesetzt.append(dienst)
    check("Probe-Token gespeichert, Zustand 'dienst'", st == 200 and z.get("quelle") == "dienst", (st, z))
    check("⚠ Antwort enthaelt den Token nicht", probe not in json.dumps(z))
    wert = roh(skill, feld)
    check("⚠ settings.json: verpackt (JGS1:), kein Klartext",
          isinstance(wert, str) and wert.startswith("JGS1:") and probe not in SETTINGS.read_text(encoding="utf-8"),
          (wert or "")[:12])
    st, k = ruf("/api/skills/%s/config" % skill)
    check("⚠ Skill-Config maskiert und meldet das Feld als gesetzt",
          st == 200 and probe not in json.dumps(k) and feld in (k.get("geheim_gesetzt") or []),
          k.get("geheim_gesetzt"))
    st, t = ruf("/api/dienstzugang/%s/test" % dienst, "POST")
    check("⚠ Verbindungstest laeuft MIT dem Probe-Token und der echte Server lehnt ihn ab",
          st == 200 and t.get("ok") is False and t.get("quelle") == "dienst", t)
    st, z = ruf("/api/dienstzugang/" + dienst, "DELETE")
    if st == 200:
        _gesetzt.remove(dienst)
    check("Entfernen: zurueck auf den gemeinsamen Zugang", st == 200 and z.get("quelle") == "sammel", (st, z))
    check("settings.json: Feld wieder leer", not roh(skill, feld), roh(skill, feld))
    st, t = ruf("/api/dienstzugang/%s/test" % dienst, "POST")
    check("danach gelingt der Test wieder mit dem gemeinsamen Zugang",
          t.get("ok") is True and t.get("quelle") == "sammel", t)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
