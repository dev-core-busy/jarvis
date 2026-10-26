#!/usr/bin/env python3
"""Live auf DEV: BSI N1, N2, N3, N5 gegen den LAUFENDEN Dienst.

  N1  ``/api/health`` anonym genau ``{"status": "ok"}``; mit Administrator-
      Sitzung die Details samt ``started_at``.
  N2  Port 80 mit fremdem Host-Kopf leitet auf einen Namen aus dem
      Serverzertifikat um, nicht auf den fremden Namen.
  N3  Derselbe 2FA-Code wird an ``/api/auth/bestaetigen`` nur EINMAL
      angenommen.
  N5  Weder HTTPS (443) noch die Umleitung (80) senden einen ``server``-Kopf.

N4 wird hier bewusst NICHT gemessen: ein falsches Kennwort an einem echten
Konto zaehlt beim Anmeldeschutz des Dienstes (und beim AD-Konto am
Domain-Controller) – der Waechter test_bsi_n.py misst es an den echten
Endpunkten im Sandkasten.

⚠ KONTO fuer N1/N3: das lokale Konto ``jarvis`` (2FA eingerichtet), nie das
AD-Testkonto. N3 verbraucht den gerade gueltigen Code dieses Kontos – wer sich
in derselben halben Minute mit genau diesem Code anmelden wollte, nimmt den
naechsten. Die Probe-Sitzung wird am Ende widerrufen; sonst wird nichts
geschrieben.

Aufruf (root): bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_bsi_n_dev.py
  Liegt das 2FA-Geheimnis des Kontos im Root-Broker (Marke "broker", seit
  2026-10-20): python3 tests/live_mit_brokercode.py tests/live_bsi_n_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import http.client
import json
import ssl
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
KONTO = "jarvis"
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % str(detail)[:300]) if detail else ""))


def abbruch(text):
    print("NICHT PRUEFBAR: %s" % text)
    sys.exit(2)


def https(pfad, token=None, methode="GET", body=None):
    c = http.client.HTTPSConnection("127.0.0.1", 443, context=CTX, timeout=60)
    h = {}
    if token:
        h["Authorization"] = "Bearer " + token
    daten = None
    if body is not None:
        daten = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    c.request(methode, pfad, body=daten, headers=h)
    a = c.getresponse()
    roh = a.read()
    kopf = {k.lower(): v for k, v in a.getheaders()}
    c.close()
    try:
        return a.status, json.loads(roh or b"{}"), kopf
    except ValueError:
        return a.status, {"_roh": roh[:200]}, kopf


def http80(pfad, host):
    c = http.client.HTTPConnection("127.0.0.1", 80, timeout=20)
    c.request("GET", pfad, headers={"Host": host})
    a = c.getresponse()
    a.read()
    kopf = {k.lower(): v for k, v in a.getheaders()}
    c.close()
    return a.status, kopf


# ── N1 + N5 (443) ────────────────────────────────────────────────────────────
print("N1 / N5: /api/health")
try:
    st, d, kopf = https("/api/health")
except OSError as e:
    abbruch("Dienst auf 443 nicht erreichbar: %s" % e)
if st != 200:
    abbruch("Positivkontrolle: /api/health antwortet %s" % st)
check(d == {"status": "ok"}, "anonym: genau {'status': 'ok'}", d)
check("server" not in kopf, "443: kein server-Kopf", kopf.get("server"))

from backend import main as M  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from zweifaktor_code import code_quelle  # noqa: E402

st_auth = M._get_user_auth_state(KONTO)
if not (st_auth.get("totp_enabled") and st_auth.get("totp_secret")):
    abbruch("Konto %s hat keine 2FA" % KONTO)
TOK = M.generate_token(KONTO, mit_2fa=True)
M._sitzung.flush()
try:
    st, d, _ = https("/api/health", TOK)
    if st != 200 or "started_at" not in d:
        abbruch("Positivkontrolle: Admin-Sitzung bekommt keine Details (%s %s) – "
                "ueber deploy/als_dienst.sh gestartet?" % (st, d))
    check(all(k in d for k in ("services", "cpu_percent", "errors")),
          "Admin: Details mit started_at, Diensten, Auslastung", sorted(d))

    # ── N3 ──────────────────────────────────────────────────────────────────
    print("N3: 2FA-Code nur einmal")
    code = code_quelle(st_auth["totp_secret"])()
    st, d, _ = https("/api/auth/bestaetigen", TOK, "POST", {"code": code})
    if st != 200:
        # der aktuelle Code war womoeglich gerade schon verbraucht (Anmeldung
        # oder ein Lauf dieser Probe in derselben halben Minute)
        abbruch("Positivkontrolle: frischer Code nicht angenommen (%s %s) – in 30 s erneut"
                % (st, d))
    st, d, _ = https("/api/auth/bestaetigen", TOK, "POST", {"code": code})
    check(st == 403 and not d.get("ok"), "⚠ derselbe Code ein zweites Mal: abgewiesen", (st, d))
finally:
    try:
        u, ts, sig = TOK.split(":", 2)
        M._sitzung.widerrufe(sig, int(ts))
        M._sitzung.flush()
    except Exception as e:  # noqa: BLE001
        print("  (Widerruf: %s)" % e)

# ── N2 + N5 (80) ─────────────────────────────────────────────────────────────
print("N2 / N5: Umleitung Port 80")
from backend import http_umleitung as HU  # noqa: E402
from backend.security import CERT_FILE  # noqa: E402

namen = HU.zertifikat_namen(CERT_FILE)
if not namen:
    abbruch("Serverzertifikat ohne lesbare Namen")
try:
    st, kopf = http80("/portal?x=1", "boese.example")
except OSError as e:
    abbruch("Port 80 nicht erreichbar: %s" % e)
ziel = urllib.parse.urlsplit(kopf.get("location", ""))
check(st == 301, "fremder Host: 301", st)
check(ziel.scheme == "https" and ziel.hostname in [n.lower() for n in namen],
      "⚠ Ziel ist ein Name aus dem Zertifikat, nicht der fremde Host", kopf.get("location"))
check(ziel.path == "/portal" and ziel.query == "x=1", "Pfad und Query bleiben erhalten",
      kopf.get("location"))
check("server" not in kopf, "80: kein server-Kopf", kopf.get("server"))
st, kopf = http80("/", namen[0])
check(urllib.parse.urlsplit(kopf.get("location", "")).hostname == namen[0].lower(),
      "Zertifikatsname im Host-Kopf bleibt erhalten", kopf.get("location"))

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
