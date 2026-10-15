#!/usr/bin/env python3
"""Live auf DEV: die gemeinsame Wissensgruppen-Normierung am ECHTEN Endpunkt.

Gemessen wird der GRUND, nicht nur der Status: ``["", "  "]`` wurde schon
vorher abgewiesen – aber mit "Keine Berechtigung fuer Gruppe(n):   ", und das
schickt an die falsche Stelle (es fehlt eine AUSWAHL, es fehlt kein Recht).

⚠ DIESE PROBE AENDERT NICHTS. Jeder Aufruf ist so gewaehlt, dass er vor jeder
Wirkung abgewiesen wird (erfundene Dokument-Kennung, ungueltiger Bereich); der
Bestand wird vorher und nachher verglichen und der Unterschied gemeldet.

Aufruf auf DEV:  /opt/jarvis/venv/bin/python /opt/jarvis/tests/live_gruppen_normierung_dev.py
"""
import json
import os
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
import backend.confluence_bindung as CFB                           # noqa: E402

BENUTZER = os.environ.get("GN_TESTUSER") or "jarvis"
TOKEN = M.generate_token(BENUTZER)
GRUPPEN = M._editable_groups_for(BENUTZER)
if not GRUPPEN:
    print("ABBRUCH: %r hat keinen Wissensbereich – jeder Endpunkt antwortet 403\n"
          "         und die Messung waere trivial wahr." % BENUTZER)
    sys.exit(2)
GID = GRUPPEN[0]["id"]
print("Benutzer: %s   Gruppen: %s" % (BENUTZER, ", ".join(g["id"] for g in GRUPPEN)))

ABLAGE = Path(CFB._pfad())
VOR_CFB = ABLAGE.read_bytes() if ABLAGE.is_file() else None


def ruf(pfad, methode="GET", rumpf=None, token=TOKEN):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


def grund(d):
    return str(d.get("error") or d.get("detail") or "")


AUSWAHL = "mindestens eine"        # "Bitte mindestens eine Wissensgruppe …"
RECHT = "Keine Berechtigung"

print("\n1. /api/wissen/pending/{id}/approve – an einem Wegwerf-Entwurf")
# ⚠ DER ENDPUNKT PRUEFT EXISTENZ UND EIGENTUEMER ZUERST (404) – die erste
# Fassung dieser Probe nahm das Gegenteil an und mass an einer erfundenen
# Kennung nur 404er. Es braucht also einen echten Entwurf.
# **Bewusst KEIN Aufruf mit gueltiger Gruppe**: der wuerde den Entwurf wirklich
# uebernehmen und eine Datei in der Wissensdatenbank anlegen. Dass der Code an
# der Existenzpruefung vorbei ist, belegt schon der 403 (statt 404).
from backend import web_extractor as WE                            # noqa: E402

VOR_PEND = {d.get("id") for d in WE.list_pending()}
DOC_ID = "gn-probe-%s" % os.getpid()
WE.save_pending({"id": DOC_ID, "title": "Wegwerf – Messung Gruppen-Normierung",
                 "content": "Wegwerf", "created_by": BENUTZER})
PFAD = "/api/wissen/pending/%s/approve" % DOC_ID

try:
    # PK und Gegenrichtung in einem: eine ECHTE, aber fremde Kennung muss
    # weiterhin die BERECHTIGUNG nennen. Der 403 belegt zugleich, dass wir an
    # der Existenzpruefung vorbei sind – sonst waere alles darunter trivial.
    s_, d_ = ruf(PFAD, "POST", {"groups": ["gibtesnicht"]})
    check("PK: eine fremde Kennung nennt die BERECHTIGUNG (und wir sind am 404 vorbei)",
          s_ == 403 and RECHT in grund(d_), "%s %s" % (s_, grund(d_)))

    for rumpf, text in [
        ({"groups": ["  "]}, "⚠ ['  '] nennt die fehlende AUSWAHL, nicht die Berechtigung"),
        ({"groups": [""]},   "[''] nennt die fehlende Auswahl"),
        ({"groups": [1]},    "⚠ [1] ergibt KEINEN 500 und nennt die fehlende Auswahl"),
        ({"groups": []},     "[] nennt die fehlende Auswahl"),
        ({},                 "ohne groups nennt er die fehlende Auswahl"),
    ]:
        s_, d_ = ruf(PFAD, "POST", rumpf)
        check(text, s_ == 403 and AUSWAHL in grund(d_) and RECHT not in grund(d_),
              "%s %s" % (s_, grund(d_)))
finally:
    WE.delete_pending(DOC_ID)

print("\n2. /api/wissen/confluence/bindung – dieselbe Regel")
for rumpf, text in [
    ({"key": "ZZZ", "groups": ["  "]}, "⚠ ['  '] nennt die fehlende Auswahl"),
    ({"key": "ZZZ", "groups": [1]},    "⚠ [1] wird VERWORFEN, nicht zu '1' geraten"),
]:
    s, d = ruf("/api/wissen/confluence/bindung", "POST", rumpf)
    check(text, s == 403 and AUSWAHL in grund(d), "%s %s" % (s, grund(d)))

print("\n3. Kein 500 an den Ordner-Endpunkten")
s, d = ruf("/api/knowledge/folders/groups", "POST",
           {"path": "data/rag/gibtesnicht-%s" % os.getpid(), "groups": [1]})
check("/api/knowledge/folders/groups: 404 statt 500", s == 404, "%s %s" % (s, grund(d)))

print("\n4. Anmeldung")
s, _ = ruf(PFAD, "POST", {"groups": [GID]}, token=None)
check("ohne Token 401", s == 401, str(s))
s, _ = ruf(PFAD, "POST", {"groups": [GID]}, token="muell")
check("mit Muell-Token 401", s == 401, str(s))

print("\n5. Zustand")
NACH_CFB = ABLAGE.read_bytes() if ABLAGE.is_file() else None
NACH_PEND = {d.get("id") for d in WE.list_pending()}
check("⚠ der Wegwerf-Entwurf ist restlos weg", NACH_PEND == VOR_PEND,
      "uebrig: %s" % sorted(NACH_PEND - VOR_PEND))
check("⚠ die Confluence-Ablage ist unveraendert", NACH_CFB == VOR_CFB,
      "vorher %s / nachher %s" % (
          len(VOR_CFB) if VOR_CFB is not None else "fehlt",
          len(NACH_CFB) if NACH_CFB is not None else "fehlt"))

print("\nErgebnis: %d/%d" % (_ok, _ok + _fail))
sys.exit(0 if _fail == 0 else 1)
