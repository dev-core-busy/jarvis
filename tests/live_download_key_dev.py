"""Live auf DEV: der Abruf-Schluessel ersetzt das Sitzungstoken – und ist als
Sitzungstoken WERTLOS.

Das ist die Probe, die der gemeldete Fall verlangt. Am 2026-09-02 wurde
nachgewiesen, dass das Token aus einem Dokument-Link als ``Bearer`` jeden
Endpunkt oeffnet. Hier wird gemessen, dass der Schluessel, der jetzt in solchen
Adressen steht, genau das NICHT mehr tut – und dass der Download trotzdem geht.
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402
from backend import download_key as dk  # noqa: E402

TOK = generate_token("jarvis")
BASIS = "https://127.0.0.1"
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


def hol(pfad, header=None):
    req = urllib.request.Request(BASIS + pfad, headers=header or {})
    try:
        r = urllib.request.urlopen(req, context=ctx, timeout=20)
        return r.status, r.read(2000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(400)
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode()


print("\n\033[1m1. Der Schluessel wird ausgegeben\033[0m")
s, b = hol("/api/download-key", {"Authorization": "Bearer " + TOK})
check("GET /api/download-key -> 200", s == 200, s)
d = json.loads(b) if s == 200 else {}
KEY = d.get("key", "")
check("er hat die erwartete Form", KEY.startswith("JDL1."), KEY[:30])
check("er traegt eine Restlaufzeit", d.get("exp", 0) > int(time.time()), d)
check("die Lebensdauer ist kurz (<= 120 min)", 1 <= d.get("ttl_min", 0) <= 120, d.get("ttl_min"))
s2, _ = hol("/api/download-key")
check("ohne Anmeldung gibt es keinen Schluessel", s2 == 401, s2)

print("\n\033[1m2. DAS IST DER PUNKT: als Sitzungstoken wertlos\033[0m")
for pfad in ("/api/me", "/api/chat/sessions", "/api/knowledge/groups", "/api/sessions"):
    st, _ = hol(pfad, {"Authorization": "Bearer " + KEY})
    check("Bearer <Abruf-Schluessel> auf %-22s -> 401" % pfad, st == 401, st)
# Positivkontrolle: dieselben Endpunkte mit dem SITZUNGStoken -> 200.
# Ohne sie waere die Zeile darueber auch dann gruen, wenn der Dienst gar nicht laeuft.
st, _ = hol("/api/me", {"Authorization": "Bearer " + TOK})
check("… mit dem Sitzungstoken weiterhin 200 (Positivkontrolle)", st == 200, st)

print("\n\033[1m3. Als Datei-Schluessel funktioniert er\033[0m")
# Eine echte Datei aus data/documents suchen.
import os  # noqa: E402
DOCS = "/opt/jarvis/data/documents"
kand = [f for f in sorted(os.listdir(DOCS))
        if "__" in f and not f.startswith(".")] if os.path.isdir(DOCS) else []
if not kand:
    check("eine Datei zum Pruefen vorhanden (Positivkontrolle)", False, "data/documents leer")
else:
    name = kand[-1]
    q = urllib.parse.quote(name)
    st, _ = hol(f"/api/documents/{q}?token={urllib.parse.quote(KEY)}")
    check("GET /api/documents/<datei>?token=<Abruf-Schluessel> -> 200/403/404",
          st in (200, 403, 404), st)
    check("… und NICHT 401 (der Schluessel wird angenommen)", st != 401, st)
    st2, _ = hol(f"/api/documents/{q}")
    check("ohne Schluessel -> 401 (Gegenprobe)", st2 == 401, st2)
    kaputt = KEY[:-1] + ("a" if KEY[-1] != "a" else "b")
    st3, _ = hol(f"/api/documents/{q}?token={urllib.parse.quote(kaputt)}")
    check("mit verfaelschtem Schluessel -> 401", st3 == 401, st3)
    exp_alt = int(time.time()) - 10
    abgelaufen = f"{dk.PRAEFIX}.{dk._b64('jarvis')}.{exp_alt}.{dk._sig('jarvis', exp_alt)}"
    st4, _ = hol(f"/api/documents/{q}?token={urllib.parse.quote(abgelaufen)}")
    check("mit abgelaufenem (korrekt signiertem) Schluessel -> 401", st4 == 401, st4)

print("\n\033[1m4. Der Alt-Weg lebt noch (Vorgabe) und wird gemeldet\033[0m")
check("download_key_strict ist aus", dk.streng() is False)
if kand:
    st5, _ = hol(f"/api/documents/{urllib.parse.quote(kand[-1])}?token={urllib.parse.quote(TOK)}")
    check("Sitzungstoken in ?token= wird noch angenommen (Android/-docs)",
          st5 != 401, st5)

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
