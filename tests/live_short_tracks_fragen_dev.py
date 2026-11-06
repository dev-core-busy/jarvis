#!/usr/bin/env python3
"""Live auf DEV: Referenzdateien und Fragefeld einer Short-Tracks-Ablage.

Ueber den ECHTEN HTTPS-Endpunkt, gegen den laufenden Dienst, mit ECHTEM Modell.
Aufruf auf dem Server (Token-Ausstellung braucht den Hauptschluessel, BSI M5):

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_short_tracks_fragen_dev.py

POSITIVKONTROLLE STATT VERMUTUNG: das Schema traegt frei erfundene Namen
(``zz_lieferant_q7``, ``lfr_ort_k9``), die kein Modell kennen kann. Steht einer
davon in der Antwort, ist die Referenz WIRKLICH im Lauf angekommen – eine
plausible Antwort allein belegt das nicht. Gefragt wird ZWEIMAL: eine
Modellantwort ist erst nach Wiederholung eine Messung (Register).

DIESE PROBE AENDERT WEDER FREIGABE NOCH SKILL-SCHALTER. Sie legt eine eigene
Ablage an und entfernt sie im ``finally`` wieder – samt Referenzverzeichnis, das
am Ende auf Platte nachgeprueft wird.
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

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
          "stehen. Schreibe SQL, wenn danach gefragt wird.")

angelegt = []
ref_ordner = None
try:
    # ── 1) Ablage mit Fragefeld ────────────────────────────────────────────
    code, d = ruf("/api/tracks/dumps", TOK, "POST",
                  {"name": "ZZ-Probe Schema-Fragen", "prompt": PROMPT,
                   "bereiche": ["basis"], "fragen": True})
    dump = d.get("dump") or {}
    did = dump.get("id", "")
    if did:
        angelegt.append(did)
    check(code == 200 and dump.get("fragen") is True,
          "Ablage mit eingeschaltetem Fragefeld angelegt", "%s %s" % (code, str(d)[:120]))
    code, d = ruf("/api/tracks/dumps", TOK, "POST",
                  {"name": "ZZ-Probe ohne Fragen", "prompt": "Lies die Datei.",
                   "bereiche": ["basis"]})
    did_ohne = (d.get("dump") or {}).get("id", "")
    if did_ohne:
        angelegt.append(did_ohne)
    check(code == 200 and (d.get("dump") or {}).get("fragen") is False,
          "zweite Ablage ohne Fragefeld (Vorgabe AUS)")

    # ── 2) Referenz hochladen ──────────────────────────────────────────────
    code, d = hochladen("/api/tracks/dumps/%s/refs" % did, TOK,
                        [("schema.sql", SCHEMA, "application/sql")])
    check(code == 200 and [r.get("name") for r in d.get("referenzen", [])] == ["schema.sql"],
          "Referenz hochgeladen und gelistet", "%s %s" % (code, str(d)[:160]))
    ref_ordner = ST.ref_wurzel() / did
    datei = ref_ordner / "schema.sql"
    check(datei.is_file() and datei.read_bytes() == SCHEMA, "liegt byte-gleich auf Platte")
    check(oct(datei.stat().st_mode & 0o777) == "0o640" if datei.exists() else False,
          "Datei 0640", oct(datei.stat().st_mode & 0o777) if datei.exists() else "fehlt")
    check(oct(ref_ordner.stat().st_mode & 0o777) == "0o750" if ref_ordner.exists() else False,
          "Verzeichnis 0750")
    check(oct(ST.ref_wurzel().stat().st_mode & 0o777) == "0o750",
          "Wurzelverzeichnis 0750")

    code, d = hochladen("/api/tracks/dumps/%s/refs" % did, TOK,
                        [("harmlos.sql", b"\x7fELF\x02\x01\x01" + b"\0" * 64,
                          "application/sql")])
    check(code == 400 and any("ausfuehrbar" in (a.get("grund") or "")
                              for a in d.get("abgewiesen", [])),
          "ein Programm mit .sql-Endung wird abgewiesen", "%s %s" % (code, str(d)[:160]))
    check(not (ref_ordner / "harmlos.sql").exists(), "und landet nicht im Verzeichnis")

    code, st_ = ruf("/api/tracks/status", TOK)
    eintrag = [x for x in st_.get("dumps", []) if x.get("id") == did]
    check(eintrag and [r.get("name") for r in eintrag[0].get("referenzen", [])] == ["schema.sql"],
          "der Status nennt die Referenz an der Ablage")
    check((st_.get("grenzen") or {}).get("frage_max") == ST.FRAGE_MAX,
          "und die Grenze der Frage")

    # ── 3) Abweisungen am Frage-Endpunkt ───────────────────────────────────
    code, d = ruf("/api/tracks/ask", TOK, "POST", {"dump_id": did_ohne, "frage": "x?"})
    check(code == 400 and "keine Fragen" in str(d.get("error")),
          "Ablage ohne Fragefeld weist die Frage ab", "%s %s" % (code, d))
    code, d = ruf("/api/tracks/ask", TOK, "POST",
                  {"dump_id": did, "frage": "x" * (ST.FRAGE_MAX + 1)})
    check(code == 400 and "zu lang" in str(d.get("error")), "zu lange Frage abgewiesen")
    code, d = ruf("/api/tracks/ask", TOK, "POST", {"dump_id": "ffffffffffff", "frage": "x?"})
    check(code == 404, "unbekannte Ablage → 404", str(code))

    # ── 4) Zwei echte Fragen, je ein Lauf mit dem Modell ───────────────────
    FRAGEN = [("Welche Spalten hat die Tabelle zz_lieferant_q7?", "lfr_ort_k9"),
              ("Schreibe eine SQL-Abfrage: Summe der Bestellbetraege je Lieferantenname.",
               "bst_betrag_x4")]
    for frage, merkmal in FRAGEN:
        code, d = ruf("/api/tracks/ask", TOK, "POST", {"dump_id": did, "frage": frage})
        jobs = d.get("jobs") or [{}]
        jid = jobs[0].get("id", "")
        check(code == 200 and jobs[0].get("art") == "frage",
              "Frage eingereiht: %s" % frage[:40], "%s %s" % (code, str(d)[:120]))
        t0, job = time.time(), {}
        while time.time() - t0 < LAUF_MAX_S:
            _, j = ruf("/api/tracks/jobs", TOK)
            job = next((x for x in j.get("jobs", []) if x.get("id") == jid), {})
            if job.get("status") in ("fertig", "fehler"):
                break
            time.sleep(3)
        dauer = time.time() - t0
        erg = job.get("ergebnis") or ""
        check(job.get("status") == "fertig", "Lauf fertig nach %.0f s" % dauer,
              "%s %s" % (job.get("status"), (job.get("fehler") or "")[:200]))
        check(merkmal in erg,
              "die Antwort nennt den erfundenen Namen %s (Referenz ist angekommen)" % merkmal,
              erg[:300])
        check(not any("schema" in (f.get("name") or "").lower() for f in job.get("dateien") or []),
              "das Schema wird NICHT als Ergebnis-Download angeboten",
              str(job.get("dateien")))
        print("     Antwort: %s" % " ".join(erg.split())[:220])

    # ── 5) Referenz loeschen ───────────────────────────────────────────────
    code, d = ruf("/api/tracks/dumps/%s/refs/schema.sql" % did, TOK, "DELETE")
    check(code == 200 and d.get("referenzen") == [], "Referenz geloescht", str(code))
    check(not (ref_ordner / "schema.sql").exists(), "und auf Platte weg")
    code, _ = ruf("/api/tracks/dumps/%s/refs/schema.sql" % did, TOK, "DELETE")
    check(code == 404, "ein zweites Loeschen → 404", str(code))
finally:
    for x in angelegt:
        code, _ = ruf("/api/tracks/dumps/" + x, TOK, "DELETE")
        print("  … Probe-Ablage %s entfernt (HTTP %s)" % (x, code))
    if ref_ordner is not None:
        check(not ref_ordner.exists(), "das Referenzverzeichnis der Ablage ist mit entfernt")
    rest = [x for x in (ST.sichtbar_fuer(BENUTZER) or [])
            if str(x.get("name", "")).startswith("ZZ-Probe")]
    check(not rest, "Ausgangszustand wiederhergestellt (keine Probe-Ablage uebrig)",
          str([x.get("id") for x in rest]))

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 60, _ok, _fail, "=" * 60))
sys.exit(1 if _fail else 0)
