"""Live auf DEV: der Abruf-Schluessel ersetzt das Sitzungstoken – und ist als
Sitzungstoken WERTLOS.

Das ist die Probe, die der gemeldete Fall verlangt. Am 2026-09-02 wurde
nachgewiesen, dass das Token aus einem Dokument-Link als ``Bearer`` jeden
Endpunkt oeffnet. Hier wird gemessen, dass der Schluessel, der jetzt in solchen
Adressen steht, genau das NICHT mehr tut – und dass der Download trotzdem geht.

Seit Pentest "Hardening" F-20 (2026-11-17) zusaetzlich DER Befund selbst: ein
Schluessel fuer Datei A oeffnet Datei B NICHT mehr. Positivkontrolle ist immer
derselbe Abruf mit dem Schluessel der eigenen Adresse (200).
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


def hol(pfad, header=None, daten=None):
    req = urllib.request.Request(BASIS + pfad, headers=header or {},
                                 data=json.dumps(daten).encode() if daten is not None else None,
                                 method="POST" if daten is not None else "GET")
    if daten is not None:
        req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req, context=ctx, timeout=20)
        return r.status, r.read(2000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(400)
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode()


AUTH = {"Authorization": "Bearer " + TOK}
import os  # noqa: E402
DOCS = "/opt/jarvis/data/documents"
kand = [f for f in sorted(os.listdir(DOCS))
        if "__" in f and not f.startswith(".") and os.path.isfile(os.path.join(DOCS, f))] \
    if os.path.isdir(DOCS) else []
if len(kand) < 2:
    print("ABBRUCH (Exit 2): zwei Dateien in data/documents noetig – keine Aussage moeglich")
    sys.exit(2)
A = "/api/documents/" + urllib.parse.quote(kand[-1])
B = "/api/documents/" + urllib.parse.quote(kand[-2])


def schluessel_fuer(adresse):
    st, b = hol("/api/download-key?ziel=" + urllib.parse.quote(adresse, safe=""), AUTH)
    return st, (json.loads(b).get("key", "") if st == 200 else "")


def mit(adresse, key):
    return adresse + ("&" if "?" in adresse else "?") + "token=" + urllib.parse.quote(key)


print("\n\033[1m1. Ausgabe: nur noch MIT Ziel\033[0m")
s, b = hol("/api/download-key", AUTH)
check("GET /api/download-key OHNE Ziel -> 400 (kein ungebundener Schluessel mehr)", s == 400, s)
s, KEY = schluessel_fuer(A)
check("GET /api/download-key?ziel=<Datei A> -> 200", s == 200, s)
check("er hat die 7-teilige Form (mit Zielbindung)", KEY.startswith("JDL1.") and len(KEY.split(".")) == 7,
      KEY[:40])
s2, _ = hol("/api/download-key?ziel=" + urllib.parse.quote(A, safe=""))
check("ohne Anmeldung gibt es keinen Schluessel", s2 == 401, s2)
s3, b3 = hol("/api/download-key", AUTH, {"ziele": [A, B, "/etc/passwd"]})
d3 = json.loads(b3) if s3 == 200 else {}
check("Sammelabruf (POST) -> 200", s3 == 200, s3)
check("… liefert je Adresse einen EIGENEN Schluessel",
      set((d3.get("keys") or {}).keys()) == {A, B}
      and d3["keys"][A]["key"] != d3["keys"][B]["key"], list((d3.get("keys") or {}).keys()))
check("… und weist eine Adresse ausserhalb der Abruf-Pfade mit Grund ab",
      "/etc/passwd" in (d3.get("abgewiesen") or {}), d3.get("abgewiesen"))

print("\n\033[1m2. Als Sitzungstoken wertlos\033[0m")
for pfad in ("/api/me", "/api/chat/sessions", "/api/knowledge/groups", "/api/sessions"):
    st, _ = hol(pfad, {"Authorization": "Bearer " + KEY})
    check("Bearer <Abruf-Schluessel> auf %-22s -> 401" % pfad, st == 401, st)
st, _ = hol("/api/me", AUTH)
check("… mit dem Sitzungstoken weiterhin 200 (Positivkontrolle)", st == 200, st)

print("\n\033[1m3. F-20: der Schluessel gilt NUR fuer seine Adresse\033[0m")
st, _ = hol(mit(A, KEY))
check("Positivkontrolle: Datei A mit dem Schluessel von A -> 200", st == 200, st)
st, _ = hol(mit(B, KEY))
check("⚠ Datei B mit dem Schluessel von A -> 401 (der Befund)", st == 401, st)
_, KB = schluessel_fuer(B)
st, _ = hol(mit(B, KB))
check("Positivkontrolle: Datei B mit dem Schluessel von B -> 200", st == 200, st)
st, _ = hol(mit(A + "?disp=inline", KEY))
check("⚠ gleiche Datei, zusaetzlicher Parameter -> 401", st == 401, st)
st, _ = hol(mit(A + "?t=12345", KEY))
check("der Cache-Buster t aendert das Ziel nicht -> 200", st == 200, st)
st2, _ = hol(A)
check("ohne Schluessel -> 401", st2 == 401, st2)
kaputt = KEY[:-1] + ("a" if KEY[-1] != "a" else "b")
st3, _ = hol(mit(A, kaputt))
check("mit verfaelschtem Schluessel -> 401", st3 == 401, st3)
exp_alt = int(time.time()) - 10
zh = dk.ziel_hash(dk.ziel_aus_adresse(A))
abgelaufen = f"{dk.PRAEFIX}.{dk._b64('jarvis')}.{exp_alt}.v.0.{zh}.{dk._sig('jarvis', exp_alt, 'v', '0', zh)}"
st4, _ = hol(mit(A, abgelaufen))
check("mit abgelaufenem (korrekt signiertem) Schluessel -> 401", st4 == 401, st4)
# Die ALTE, ungebundene Form – gueltig signiert, wie bis 2026-11-17 ausgestellt.
import hashlib as _hl  # noqa: E402
import hmac as _hm  # noqa: E402
from backend.config import config as _cfg  # noqa: E402
exp_neu = int(time.time()) + 600
_alt_sig = _hm.new(_cfg.SECRET_KEY.encode(), f"jdl1:jarvis:{exp_neu}:v:0".encode(), _hl.sha256).hexdigest()
alt6 = f"{dk.PRAEFIX}.{dk._b64('jarvis')}.{exp_neu}.v.0.{_alt_sig}"
st5, _ = hol(mit(A, alt6))
check("⚠ alte, ungebundene Form (gueltig signiert) -> 401", st5 == 401, st5)

print("\n\033[1m4. Alt-Weg zu, Grund im Journal\033[0m")
check("download_key_strict ist an", dk.streng() is True)
st6, _ = hol(mit(A, TOK))
check("Sitzungstoken in ?token= wird abgewiesen", st6 == 401, st6)
import subprocess  # noqa: E402
time.sleep(1)
j = subprocess.run(["journalctl", "-u", "jarvis.service", "--since", "-3min", "--no-pager", "-o", "cat"],
                   capture_output=True, text=True).stdout
check("das Journal nennt den Grund 'andere Adresse'", "gilt fuer eine andere Adresse" in j,
      "journalctl leer? (Dienstkontext noetig)" if not j else "")
check("das Journal nennt den Grund 'ohne Zielbindung'", "ohne Zielbindung" in j)
check("der Schluessel selbst steht NICHT im Journal", KEY not in j and KEY.split(".")[-1] not in j)

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
