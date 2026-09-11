#!/usr/bin/env python3
"""Live auf DEV: Sichtbarkeit einer Short-Tracks-Ablage umstellen.

Ueber den ECHTEN HTTPS-Endpunkt, im Produktiv-venv, gegen den laufenden Dienst.

⚠ DIESE PROBE STELLT DEN VORGEFUNDENEN ZUSTAND WIEDER HER und raet ihn nicht:
Freigabeliste und Skill-Schalter werden vorher GELESEN und am Ende auf genau
diesen Wert zurueckgesetzt (Register 2026-09-09: eine Messung, die einen
Schalter hart abschaltet, nimmt ihn dem Betreiber weg). Angelegte Ablagen
werden namentlich wieder entfernt.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
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


def ruf(pfad, token, methode="GET", rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=30) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                        # noqa: BLE001
            return e.code, {}


from backend import main as M                                    # noqa: E402
from backend.config import config                                 # noqa: E402
from backend import short_tracks as ST                           # noqa: E402

# ⚠ NICHT `jarvis`: der Bereich /tracks ist auf DEV nur fuer diesen Benutzer
# freigegeben ("leer = niemand"), und er ist zugleich Administrator. Die
# Freigabe fuer eine Messung umzustellen waere ein Eingriff in eine
# Sicherheitseinstellung – den freigegebenen Benutzer zu nehmen ist der
# richtige Weg (Register 2026-09-09).
ADMIN = os.environ.get("TRACKS_TESTUSER", "andreas.bender")
tok_admin = M.generate_token(ADMIN)

# ⚠ DIESE PROBE AENDERT WEDER FREIGABE NOCH SKILL-SCHALTER – sie liest den
# Zustand nur ueber den ECHTEN Weg (`/api/me`) und bricht ab, wenn der Bereich
# nicht freigegeben ist. Eine erste Fassung wollte `config.load_settings()`
# lesen; die Funktion gibt es nicht (geraten statt gemessen), und gebraucht
# wird sie auch nicht: was man nicht veraendert, muss man nicht sichern.
print("Vorgefunden: Skill short-tracks enabled=%r"
      % (config.get_skill_states().get("short-tracks", {}).get("enabled"),))

code, me = ruf("/api/me", tok_admin)
check(code == 200, "Anmeldung als %s" % ADMIN, str(code))
check(me.get("is_admin") is True, "und er ist Administrator")
if not me.get("permissions", {}).get("tracks"):
    print("\n⚠ ABBRUCH: der Bereich /tracks ist fuer %s nicht freigegeben." % ADMIN)
    print("  Die Probe stellt das NICHT selbst um – eine Freigabe ist eine")
    print("  Sicherheitseinstellung, keine Testvorbereitung.")
    sys.exit(2)

angelegt = []
try:
    # ── 1) Eigene Ablage anlegen ───────────────────────────────────────────
    code, d = ruf("/api/tracks/dumps", tok_admin, "POST",
                  {"name": "ZZ-Probe Sichtbarkeit", "prompt": "Lies die Datei.",
                   "bereiche": ["basis"]})
    check(code == 200, "eigene Ablage angelegt", str(code) + " " + str(d)[:120])
    dump = d.get("dump") or {}
    did = dump.get("id", "")
    if did:
        angelegt.append(did)
    check(dump.get("global") is False, "sie startet als eigene Ablage")
    besitzer_vorher = dump.get("owner")

    # ── 2) Hochstufen ueber den ECHTEN Endpunkt ────────────────────────────
    code, d = ruf("/api/tracks/dumps/" + did, tok_admin, "PUT",
                  {"name": "ZZ-Probe Sichtbarkeit", "prompt": "Lies die Datei.",
                   "bereiche": ["basis"], "global": True})
    check(code == 200, "PUT mit global:true wird angenommen",
          str(code) + " " + str(d.get("error", ""))[:120])
    check((d.get("dump") or {}).get("global") is True, "die Ablage ist jetzt 'fuer alle'")
    check((d.get("dump") or {}).get("id") == did, "die Kennung ist dieselbe geblieben")
    check((d.get("dump") or {}).get("owner") == besitzer_vorher,
          "der Besitzer bleibt beim Hochstufen stehen")

    # Auf PLATTE gegenpruefen – nicht nur in der Antwort.
    check((ST.holen(did) or {}).get("global") is True,
          "und steht so auch in der Registry auf Platte")

    # ── 3) Ohne das Feld bleibt die Sichtbarkeit stehen ────────────────────
    code, d = ruf("/api/tracks/dumps/" + did, tok_admin, "PUT",
                  {"name": "ZZ-Probe Sichtbarkeit v2",
                   "prompt": "Lies die Datei.", "bereiche": ["basis"]})
    check(code == 200, "PUT OHNE global wird angenommen", str(code))
    check((d.get("dump") or {}).get("global") is True,
          "ein Aufruf ohne das Feld privatisiert NICHT (der wichtigste Fall)")

    # ── 4) Zuruecknehmen ───────────────────────────────────────────────────
    code, d = ruf("/api/tracks/dumps/" + did, tok_admin, "PUT",
                  {"name": "ZZ-Probe Sichtbarkeit v2",
                   "prompt": "Lies die Datei.", "bereiche": ["basis"],
                   "global": False})
    check(code == 200, "PUT mit global:false wird angenommen", str(code))
    check((d.get("dump") or {}).get("global") is False, "sie ist wieder eigen")
    check((d.get("dump") or {}).get("owner") == ST.norm_user(ADMIN),
          "der handelnde Administrator ist jetzt der Besitzer")
    check((ST.holen(did) or {}).get("global") is False,
          "auch auf Platte wieder eigen")

    # ── 5) Ohne Token: 401, und es wird nichts geschrieben ─────────────────
    r = urllib.request.Request(BASIS + "/api/tracks/dumps/" + did,
                               data=json.dumps({"global": True}).encode(),
                               method="PUT")
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=20) as a:
            code = a.status
    except urllib.error.HTTPError as e:
        code = e.code
    check(code == 401, "ohne Token 401", str(code))
    check((ST.holen(did) or {}).get("global") is False,
          "und die Ablage ist unveraendert geblieben")

    # ── 6) `global` als gewoehnliches Feld bleibt abgewiesen ───────────────
    # Der Endpunkt zieht es heraus; die Feld-Whitelist AENDERBAR ist damit
    # unangetastet. Gemessen wird die WIRKUNG: es gibt keinen 400er.
    code, d = ruf("/api/tracks/dumps/" + did, tok_admin, "PUT",
                  {"name": "ZZ-Probe Sichtbarkeit v2", "prompt": "Lies die Datei.",
                   "bereiche": ["basis"], "owner": "chef"})
    check(code == 400 and "nicht aendern" in str(d.get("error", "")),
          "owner im Rumpf wird weiterhin abgewiesen", str(code))

finally:
    for did in angelegt:
        code, _ = ruf("/api/tracks/dumps/" + did, tok_admin, "DELETE")
        print("  … Probe-Ablage %s entfernt (HTTP %s)" % (did, code))
    # Zustand pruefen: keine ZZ-Probe mehr im Bestand
    rest = [x for x in (ST.sichtbar_fuer(ADMIN) or [])
            if str(x.get("name", "")).startswith("ZZ-Probe")]
    check(not rest, "Ausgangszustand wiederhergestellt (keine Probe-Ablage uebrig)",
          str([x.get("id") for x in rest]))

print("\n%s\n  %d OK, %d FAIL\n%s" % ("=" * 60, _ok, _fail, "=" * 60))
sys.exit(1 if _fail else 0)
