#!/usr/bin/env python3
"""Live auf DEV: Nachfragen mit Verlauf im Fragefeld einer Short-Tracks-Ablage.

Ueber den ECHTEN HTTPS-Endpunkt, gegen den laufenden Dienst, mit ECHTEM Modell.
Aufruf auf dem Server (Token-Ausstellung braucht den Hauptschluessel, BSI M5):

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_short_tracks_verlauf_dev.py

ABLAUF: Frage und Nachfrage werden SOFORT hintereinander gestellt – gemessen
wird also auch, dass die Nachfrage auf die Antwort davor wartet (im Betrieb
tippt niemand so schnell, aber genau dann zeigte sich ein paralleler Start).
Die Nachfrage („und die andere Tabelle?") nennt ihr Ziel NICHT; die erfundenen
Spaltennamen der zweiten Tabelle in der Antwort sind das Merkmal. Zwei Runden,
dazwischen Zuruecksetzen: eine Modellantwort ist erst nach Wiederholung eine
Messung (Register). Danach die Gegenkontrolle: nach dem Zuruecksetzen hat
dieselbe Nachfrage KEINEN Verlauf.

DIESE PROBE AENDERT WEDER FREIGABE NOCH SKILL-SCHALTER. Sie legt eine eigene
Ablage an und entfernt sie im ``finally`` wieder.
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
LAUF_MAX_S = 420

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def _antwort(r):
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                        # noqa: BLE001
            return e.code, {}


def ruf(pfad, token, methode="GET", rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    return _antwort(r)


def hochladen(pfad, token, dateien):
    """Multipart von Hand (urllib kennt keins) – Feldname `files` wie im Browser."""
    rand = "----probe" + uuid.uuid4().hex
    teile = []
    for name, inhalt, typ in dateien:
        teile.append(("--%s\r\nContent-Disposition: form-data; name=\"files\"; "
                      "filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                      % (rand, name, typ)).encode() + inhalt + b"\r\n")
    rumpf = b"".join(teile) + ("--%s--\r\n" % rand).encode()
    r = urllib.request.Request(BASIS + pfad, data=rumpf, method="POST")
    r.add_header("Authorization", "Bearer " + token)
    r.add_header("Content-Type", "multipart/form-data; boundary=" + rand)
    return _antwort(r)


def job_von(jid):
    _, j = ruf("/api/tracks/jobs", TOK)
    return next((x for x in j.get("jobs", []) if x.get("id") == jid), {})


def warte_fertig(jid):
    t0, job = time.time(), {}
    while time.time() - t0 < LAUF_MAX_S:
        job = job_von(jid)
        if job.get("status") in ("fertig", "fehler"):
            break
        time.sleep(2)
    return job, time.time() - t0


def frage_stellen(did, frage):
    code, d = ruf("/api/tracks/ask", TOK, "POST", {"dump_id": did, "frage": frage})
    jobs = d.get("jobs") or [{}]
    return code, jobs[0].get("id", "")


from backend import main as M                                    # noqa: E402
from backend import short_tracks as ST                           # noqa: E402

BENUTZER = os.environ.get("TRACKS_TESTUSER") or ziele.wert("JARVIS_DEV_TESTUSER")
TOK = M.generate_token(BENUTZER)

code, me = ruf("/api/me", TOK)
if code != 200 or not (me.get("permissions") or {}).get("tracks"):
    print("ABBRUCH: /tracks ist fuer den Testbenutzer nicht freigegeben oder die "
          "Anmeldung scheitert (HTTP %s). Die Probe stellt das NICHT selbst um." % code)
    sys.exit(2)
check(True, "Anmeldung und Bereichs-Freigabe (Positivkontrolle)")

SCHEMA = b"""-- Probe-Schema (erfundene Namen)
CREATE TABLE zz_lieferant_q7 (
    lfr_kennung   INTEGER PRIMARY KEY,
    lfr_name      VARCHAR(80) NOT NULL,
    lfr_ort_k9    VARCHAR(60)
);
CREATE TABLE zz_bestellung_q7 (
    bst_nr        INTEGER PRIMARY KEY,
    lfr_kennung   INTEGER REFERENCES zz_lieferant_q7(lfr_kennung),
    bst_betrag_x4 NUMERIC(10,2)
);
"""
PROMPT = ("Beantworte Fragen zum Datenbankschema in den Referenzdateien. Antworte "
          "knapp und nenne Tabellen- und Spaltennamen genau so, wie sie im Schema "
          "stehen.")
FRAGE = "Welche Spalten hat die Tabelle zz_lieferant_q7?"
NACHFRAGE = "Und welche Spalten hat die andere Tabelle?"

angelegt = []
try:
    code, d = ruf("/api/tracks/dumps", TOK, "POST",
                  {"name": "ZZ-Probe Nachfragen", "prompt": PROMPT,
                   "bereiche": ["basis"], "fragen": True})
    did = (d.get("dump") or {}).get("id", "")
    if did:
        angelegt.append(did)
    check(code == 200 and did, "Ablage mit Fragefeld angelegt", "%s %s" % (code, str(d)[:120]))
    code, d = hochladen("/api/tracks/dumps/%s/refs" % did, TOK,
                        [("schema.sql", SCHEMA, "application/sql")])
    check(code == 200, "Referenz hochgeladen", str(code))

    for runde in (1, 2):
        print("\n  Runde %d" % runde)
        c1, j1 = frage_stellen(did, FRAGE)
        c2, j2 = frage_stellen(did, NACHFRAGE)          # sofort, ohne zu warten
        check(c1 == 200 and c2 == 200 and j1 and j2, "Frage und Nachfrage eingereiht")
        stand2 = job_von(j2).get("status")
        stand1 = job_von(j1).get("status")
        check(not (stand2 == "laeuft" and stand1 in ("wartet", "laeuft")),
              "die Nachfrage laeuft NICHT, solange die Frage davor offen ist",
              "frage=%s nachfrage=%s" % (stand1, stand2))
        job1, s1 = warte_fertig(j1)
        job2, s2 = warte_fertig(j2)
        check(job1.get("status") == "fertig", "Frage fertig nach %.0f s" % s1,
              (job1.get("fehler") or "")[:200])
        check(job2.get("status") == "fertig", "Nachfrage fertig nach %.0f s" % s2,
              (job2.get("fehler") or "")[:200])
        check(job1.get("verlauf") == 0, "die erste Frage hat keinen Verlauf",
              repr(job1.get("verlauf")))
        check(job2.get("verlauf") == 1, "die Nachfrage baut auf EINER Frage auf",
              repr(job2.get("verlauf")))
        erg2 = job2.get("ergebnis") or ""
        check("bst_betrag_x4" in erg2,
              "die Nachfrage hat „die andere Tabelle“ richtig aufgeloest (bst_betrag_x4)",
              erg2[:300])
        check("lfr_ort_k9" not in erg2,
              "und beantwortet nicht noch einmal die erste Frage", erg2[:300])
        print("     Nachfrage-Antwort: %s" % " ".join(erg2.split())[:220])
        code, d = ruf("/api/tracks/dumps/%s/reset" % did, TOK, "POST")
        check(code == 200 and d.get("entfernt") == 2, "Zuruecksetzen entfernt beide",
              "%s %s" % (code, d))

    print("\n  Gegenkontrolle")
    code, j3 = frage_stellen(did, NACHFRAGE)
    job3, s3 = warte_fertig(j3)
    check(job3.get("status") == "fertig", "Nachfrage allein fertig nach %.0f s" % s3)
    check(job3.get("verlauf") == 0, "nach dem Zuruecksetzen KEIN Verlauf",
          repr(job3.get("verlauf")))
    print("     Antwort ohne Verlauf: %s" % " ".join((job3.get("ergebnis") or "").split())[:220])
finally:
    for x in angelegt:
        code, _ = ruf("/api/tracks/dumps/" + x, TOK, "DELETE")
        print("  … Probe-Ablage %s entfernt (HTTP %s)" % (x, code))
    rest = [x for x in (ST.sichtbar_fuer(BENUTZER) or [])
            if str(x.get("name", "")).startswith("ZZ-Probe")]
    check(not rest, "Ausgangszustand wiederhergestellt (keine Probe-Ablage uebrig)",
          str([x.get("id") for x in rest]))

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 60, _ok, _fail, "=" * 60))
sys.exit(1 if _fail else 0)
