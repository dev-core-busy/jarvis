"""Live auf DEV: BSI M9 (Loeschfristen, Gedaechtnis, Lernnotizen) und M11 (Fingerabdruck).

  A. /api/settings/loeschfristen: vier Fristen mit Quelle; Setzen wirkt und
     wird danach auf den VORGEFUNDENEN Stand zurueckgestellt; ungueltige Werte
     400; ohne Anmeldung 401.
  B. /api/memory: eigenes Gedaechtnis lesbar (200), ohne Anmeldung 401.
  C. /api/knowledge/learned: Liste traegt "herkunft"; DELETE mit Pfad aus dem
     Notizordner heraus -> 403 (die Datei bleibt).
  D. /api/settings/ssl: Fingerabdruck = openssl auf dem ausgelieferten Zertifikat.

Aufruf: bash /opt/jarvis/deploy/als_dienst.sh /opt/jarvis/venv/bin/python tests/live_bsi_m9_m11_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402

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
        print("  FAIL %s%s" % (label, (" – %s" % str(detail)[:300]) if detail else ""))


def ruf(pfad, token=None, methode="GET", body=None):
    daten = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASIS + pfad, method=methode, data=daten)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=120) as a:
            return a.status, json.loads(a.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:  # noqa: BLE001
            return e.code, None


from backend import main as M  # noqa: E402
ADMIN = ziele.wert("JARVIS_DEV_TESTUSER")
TOK = M.generate_token(ADMIN, mit_2fa=True)
M._sitzung.flush()
print("Live DEV: BSI M9 / M11")
vorher = None
try:
    st, d = ruf("/api/settings/loeschfristen", TOK)
    if st != 200 or not isinstance(d, dict):
        print("NICHT PRUEFBAR: Fristen nicht abrufbar (%s)" % st)
        sys.exit(2)
    vorher = d["fristen"]
    check(set(vorher) == {"chats", "prompts", "protokoll", "sicherheit"}, "A: vier Fristen", list(vorher))
    check(all("quelle" in v and "tage" in v for v in vorher.values()), "A: je Frist Wert + Quelle")
    neu_chats = 179 if vorher["chats"]["tage"] != 179 else 178
    st, d = ruf("/api/settings/loeschfristen", TOK, "POST", {"fristen": {"chats": neu_chats}})
    check(st == 200 and d["fristen"]["chats"]["tage"] == neu_chats
          and d["fristen"]["chats"]["quelle"] == "einstellung", "A: Setzen wirkt", (st, d))
    st, d = ruf("/api/settings/loeschfristen", TOK, "POST", {"fristen": {"chats": -3}})
    check(st == 400, "A: negative Frist 400", st)
    check(ruf("/api/settings/loeschfristen")[0] == 401, "A: ohne Anmeldung 401")

    st, d = ruf("/api/memory", TOK)
    check(st == 200 and isinstance((d or {}).get("eintraege"), list), "B: eigenes Gedaechtnis lesbar", st)
    check(ruf("/api/memory")[0] == 401, "B: ohne Anmeldung 401")

    st, d = ruf("/api/knowledge/learned", TOK)
    check(st == 200 and isinstance(d, list), "C: Lernnotizen-Liste abrufbar", st)
    if d:
        check(all("herkunft" in x for x in d), "C: jede Zeile traegt herkunft")
    st, _ = ruf("/api/knowledge/learned", TOK, "DELETE", {"path": "data/erfahrung/../settings.json"})
    check(st == 403 and os.path.exists("/opt/jarvis/data/settings.json"), "C: Ausbruch aus dem Notizordner 403", st)

    st, d = ruf("/api/settings/ssl", TOK)
    fp = (d or {}).get("fingerabdruck", "")
    pfad = (d or {}).get("cert_path", "")
    soll = subprocess.run(["openssl", "x509", "-in", pfad, "-noout", "-fingerprint", "-sha256"],
                          capture_output=True, text=True).stdout.strip().split("=", 1)[-1]
    check(bool(fp) and fp == soll, "D: Fingerabdruck = openssl (%s…)" % fp[:11], (fp, soll))
finally:
    if vorher is not None:
        # Vorgefundenen Zustand herstellen: nur was "hier eingestellt" war, bleibt gesetzt
        zurueck = {a: (v["tage"] if v["quelle"] == "einstellung" else None) for a, v in vorher.items()}
        st, d = ruf("/api/settings/loeschfristen", TOK, "POST", {"fristen": zurueck})
        gleich = st == 200 and all(d["fristen"][a]["tage"] == vorher[a]["tage"]
                                   and d["fristen"][a]["quelle"] == vorher[a]["quelle"] for a in vorher)
        check(gleich, "Zustand: Fristen wie vorgefunden", (st, d))
    try:
        u, ts, sig = TOK.split(":", 2)
        M._sitzung.widerrufe(sig, int(ts))
    except Exception as e:  # noqa: BLE001
        print("  !!   Probe-Sitzung nicht widerrufen: %s" % e)
    M._sitzung.flush()

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
