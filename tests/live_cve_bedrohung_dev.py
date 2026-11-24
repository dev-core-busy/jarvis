"""Live-Probe auf DEV: Bedrohungslage (CISA KEV, EPSS) der CVE-Pruefung.

NUR PRUEFEN, NICHT BEHEBEN. Die Probe startet eine Pruefung ohne Behebung,
wartet sie ab und liest das Ergebnis. Neu geschrieben werden dabei nur
data/cve/ergebnis.json und die Caches der Quellen – das ist der Zweck der
Funktion, kein Fremdzustand. Quittungen, Einstellungen und Auftraege fasst
sie nicht an.

    python3 tests/live_mit_brokercode.py tests/live_cve_bedrohung_dev.py   (root, auf DEV)
"""
import gzip
import json
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
from backend import cve_pruefung as cp  # noqa: E402
from backend import main as m          # noqa: E402

CTX = ssl._create_unverified_context()
BASIS = "https://127.0.0.1"
ok = fail = 0


def check(n, c, d=""):
    global ok, fail
    if c:
        ok += 1
        print("  OK   %s" % n)
    else:
        fail += 1
        print("  FAIL %s%s" % (n, (" – %s" % d) if d else ""))


def hol(pfad, token=None, methode="GET", daten=None):
    r = urllib.request.Request(BASIS + pfad, method=methode,
                               data=None if daten is None else json.dumps(daten).encode())
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=120) as a:
            return a.status, json.loads(a.read() or b"{}")
    except urllib.error.HTTPError as e:
        roh = e.read()
        try:
            return e.code, json.loads(roh or b"{}")
        except ValueError:
            return e.code, {"roh": roh[:200].decode(errors="replace")}


BENUTZER = sys.argv[1] if len(sys.argv) > 1 else "jarvis"
tok = m.generate_token(BENUTZER)

# Admin-Rechte gibt es nur ueber das Zahnrad mit eigenem 2FA-Code (BSI M3) –
# der echte Weg, kein im Token nachgebautes Merkmal. Die Codes liefert
# tests/live_mit_brokercode.py (Geheimnis im Root-Broker).
sys.path.insert(0, "/opt/jarvis/tests/lib")
from zweifaktor_code import code_quelle  # noqa: E402
_auth = m._get_user_auth_state(BENUTZER)
if not _auth.get("totp_enabled"):
    print("NICHT PRUEFBAR: Konto %s hat keine 2FA – ohne Code gibt es keine Admin-Sitzung" % BENUTZER)
    sys.exit(2)
_s, _r = hol("/api/admin/erhoehen", tok, "POST", {"code": code_quelle(_auth.get("totp_secret"))()})
if _s != 200 or not _r.get("erhoeht"):
    print("NICHT PRUEFBAR: Erhoehung am Zahnrad gelang nicht -> %s %s" % (_s, str(_r)[:200]))
    sys.exit(2)

print("\n0) Positivkontrolle: der Dienst antwortet einem Administrator")
s, me = hol("/api/me", tok)
if s != 200 or not me.get("is_admin"):
    print("ABBRUCH: /api/me liefert keinen Administrator (%s, is_admin=%s) – Probe nicht deutbar"
          % (s, me.get("is_admin")))
    sys.exit(2)
s, z = hol("/api/system/cve", tok)
if s != 200:
    print("ABBRUCH: /api/system/cve antwortet %s" % s)
    sys.exit(2)
if z.get("laeuft"):
    print("ABBRUCH: es laeuft bereits eine Pruefung – fremder Lauf, nicht deutbar")
    sys.exit(2)

print("\n1) Pruefung OHNE Behebung starten und abwarten")
t0 = time.time()
s, d = hol("/api/system/cve/pruefen", tok, "POST", {"beheben": False})
check("Start 202", s == 202, (s, d))
while time.time() - t0 < 900:
    s, z = hol("/api/system/cve", tok)
    if s == 200 and not z.get("laeuft"):
        break
    time.sleep(5)
erg = z.get("ergebnis") or {}
print("     -> Dauer %.0f s, Zaehler %s" % (time.time() - t0, erg.get("zaehler")))
if not (erg.get("ts", 0) >= t0 - 5 and erg.get("ok")):
    print("ABBRUCH: kein frisches Ergebnis (%s)" % erg.get("fehler"))
    sys.exit(2)
check("es wurde NICHT behoben", erg.get("beheben") is False and erg.get("behebung") is None)

print("\n2) Bedrohungslage im Ergebnis")
bed = erg.get("bedrohung") or {}
kev, epss = bed.get("kev") or {}, bed.get("epss") or {}
print("     -> KEV:  %s" % json.dumps(kev, ensure_ascii=False))
print("     -> EPSS: %s" % json.dumps(epss, ensure_ascii=False))
check("KEV geladen, ohne Hinweis", kev.get("ok") is True and not kev.get("hinweis"), kev)
check("KEV-Katalog plausibel gross (> 1000 Eintraege)", (kev.get("eintraege") or 0) > 1000, kev)
heute = time.strftime("%Y-%m-%d")
check("KEV-Stand hoechstens 14 Tage alt", bool(kev.get("stand"))
      and (time.mktime(time.strptime(heute, "%Y-%m-%d"))
           - time.mktime(time.strptime(kev["stand"], "%Y-%m-%d"))) <= 14 * 86400, kev.get("stand"))
check("EPSS geladen, ohne Hinweis, mit Stand", epss.get("ok") is True and not epss.get("hinweis")
      and bool(epss.get("stand")), epss)
bef = erg.get("befunde") or []
mit_cve = [b for b in bef if cp.cve_kennungen(b)]
check("jeder Befund traegt kev als dict oder False (nie None bei geladenem Katalog)",
      bool(bef) and all(b.get("kev") is False or isinstance(b.get("kev"), dict) for b in bef),
      [b.get("cve") for b in bef if not (b.get("kev") is False or isinstance(b.get("kev"), dict))][:5])
mit_epss = [b for b in mit_cve if isinstance(b.get("epss"), (int, float))]
print("     -> %d Befunde, %d mit CVE-Kennung, %d mit EPSS-Wert, %d aktiv ausgenutzt"
      % (len(bef), len(mit_cve), len(mit_epss), sum(1 for b in bef if isinstance(b.get("kev"), dict))))
check("die meisten CVE-Befunde haben einen EPSS-Wert (>= 80 %)",
      bool(mit_cve) and len(mit_epss) >= 0.8 * len(mit_cve), (len(mit_epss), len(mit_cve)))
check("Zaehler im Ergebnis == Zaehlung an den Befunden",
      kev.get("treffer") == sum(1 for b in bef if isinstance(b.get("kev"), dict))
      and epss.get("mit_wert") == sum(1 for b in bef if b.get("epss") is not None), (kev, epss))
for b in sorted((b for b in bef if isinstance(b.get("kev"), dict)), key=lambda b: b["cve"])[:10]:
    print("     KEV %-18s %-8s %-14s %-12s seit %s" % (b["cve"], b["bereich"], b["quelle"][:14],
                                                     b["klasse"], b["kev"].get("seit")))

print("\n3) Caches und Gegenpruefung an der Quelle")
check("KEV-Cache liegt (gzip)", cp.KEV_CACHE.is_file() and cp.KEV_CACHE.read_bytes()[:2] == b"\x1f\x8b")
check("EPSS-Cache liegt (gzip)", cp.EPSS_CACHE.is_file() and cp.EPSS_CACHE.read_bytes()[:2] == b"\x1f\x8b")
katalog = json.loads(gzip.decompress(cp.KEV_CACHE.read_bytes()))
ids = {str(v.get("cveID") or "").upper() for v in katalog.get("vulnerabilities") or []}
falsch = [b["cve"] for b in bef if isinstance(b.get("kev"), dict) and b["kev"]["kennung"] not in ids]
fehlt = [b["cve"] for b in bef if b.get("kev") is False and set(cp.cve_kennungen(b)) & ids]
check("KEV-Treffer stimmen mit dem Katalog ueberein (beide Richtungen)", not falsch and not fehlt,
      (falsch[:5], fehlt[:5]))

print("\n4) Plan: KEV-Befunde unter der Schwelle sind eingeplant")
pl = z.get("plan") or {}
unter = [b for b in bef if b["bereich"] == "debian" and b["klasse"] == "behebbar"
         and isinstance(b.get("kev"), dict) and b.get("aus_sicherheitsquelle")
         and not cp.erreicht_schwelle(b.get("einstufung", ""), (z.get("einstellungen") or {}).get("schwelle"))]
if unter:
    check("KEV-Befund unter der Schwelle steht im Plan",
          all(set(b.get("beheben_mit") or []) <= set(pl.get("debian") or []) for b in unter), unter[:2])
else:
    print("  --   auf DEV gerade kein behebbarer KEV-Befund unter der Schwelle – Fall hier nicht messbar"
          " (tests/test_cve_bedrohung.py Abschnitt 5 misst ihn)")

print("\n5) Kennungsauskunft (nur gespeicherte Dateien)")
probe = sorted(ids)[-1]
s, a = hol("/api/system/cve/kennung?k=" + probe, tok)
check("Auskunft zu einer KEV-Kennung nennt sie als ausgenutzt", s == 200
      and isinstance((a.get("bedrohung") or {}).get("kev"), dict), (probe, s, a.get("bedrohung")))
t1 = time.time()
s, a = hol("/api/system/cve/kennung?k=CVE-1999-0001", tok)
print("     -> CVE-1999-0001: %s (%.2f s)" % (a.get("bedrohung"), time.time() - t1))
check("Auskunft zu einer alten Kennung: nicht gelistet, EPSS-Wert vorhanden",
      s == 200 and (a.get("bedrohung") or {}).get("kev") is False
      and isinstance((a.get("bedrohung") or {}).get("epss"), (int, float)), a.get("bedrohung"))

print("\nKurzbericht: " + cp.kurzbericht(erg))
print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
