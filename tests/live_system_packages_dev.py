"""Live-Probe auf DEV: /api/system/packages gegen den echten Dienst."""
import json, sys, time, urllib.request, ssl
sys.path.insert(0, "/opt/jarvis")
from backend import main as m          # noqa: E402

CTX = ssl._create_unverified_context()
BASIS = "https://127.0.0.1"
ok = fail = 0
def check(n, c, d=""):
    global ok, fail
    if not isinstance(n, str): print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if c: ok += 1; print("  OK   %s" % n)
    else: fail += 1; print("  FAIL %s%s" % (n, (" – %s" % d) if d else ""))

def hol(pfad, token=None):
    r = urllib.request.Request(BASIS + pfad)
    if token: r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            # ⚠ HTTP-Kopfnamen sind case-insensitiv, und uvicorn liefert sie
            # KLEIN. Ein `dict(a.headers)` mit `.get("Content-Disposition")`
            # meldete deshalb einen Fehler, den es nicht gab - der Code war
            # richtig, die Probe falsch (Register).
            return a.status, a.read(), {k.lower(): v for k, v in a.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}

# Token wie der Login-Endpunkt es tut (die PAM-Anmeldung von der Kommandozeile
# scheitert auf DEV an einem anderen OS-Kennwort - Register).
tok_admin = m.generate_token("jarvis")

print("\n1) Ohne Anmeldung")
s, _, _ = hol("/api/system/packages")
check("ohne Token 401", s == 401, s)
s, _, _ = hol("/api/system/packages", "muell")
check("mit Muell-Token 401", s == 401, s)

print("\n2) Als Nicht-Admin")
tok_user = m.generate_token("nexus\\testnutzer")
s, b, _ = hol("/api/system/packages", tok_user)
check("ein Nicht-Admin bekommt 403 (nicht die Liste)", s == 403, s)
check("und die Antwort enthaelt KEINE Pakete", b"\"pakete\"" not in b, b[:120])

print("\n3) Als Administrator")
t0 = time.time()
s, b, h = hol("/api/system/packages", tok_admin)
d = time.time() - t0
check("Administrator bekommt 200", s == 200, s)
j = json.loads(b) if s == 200 else {}
check("die Liste ist nicht leer", j.get("anzahl", 0) > 100, j.get("anzahl"))
check("Anzahl und Liste stimmen ueberein", j.get("anzahl") == len(j.get("pakete", [])))
check("Kopfdaten sind da (Host, Zeitpunkt, Gesamtgroesse)",
      bool(j.get("host")) and bool(j.get("erzeugt_am")) and j.get("groesse_kb_gesamt", 0) > 0,
      {k: j.get(k) for k in ("host", "erzeugt_am", "groesse_kb_gesamt")})
check("es dauert unter 5 s", d < 5, "%.2fs" % d)
print("     -> %d Pakete, %.2f GiB, %.2fs, host=%s"
      % (j.get("anzahl", 0), j.get("groesse_kb_gesamt", 0) / 1048576, d, j.get("host")))

# ⚠ Der Kern der Zusage: kein `rc`-Paket in einer Liste INSTALLIERTER Pakete.
zust = {}
for p in j.get("pakete", []):
    zust[p["status"]] = zust.get(p["status"], 0) + 1
check("jeder Eintrag ist wirklich installiert (2. Zeichen = i)",
      all(len(k) >= 2 and k[1] == "i" for k in zust), zust)
print("     -> Zustaende:", zust)
check("jedes Paket hat Name, Version und Groesse",
      all(p["package"] and p["version"] and isinstance(p["size_kb"], int)
          for p in j.get("pakete", [])))
mit_datum = sum(1 for p in j.get("pakete", []) if p["update_date"])
check("die allermeisten Pakete haben einen Zeitstempel",
      mit_datum > 0.9 * max(1, j.get("anzahl", 0)),
      "%d von %d" % (mit_datum, j.get("anzahl", 0)))

print("\n4) Es wird bei JEDEM Abruf neu erzeugt")
s2, b2, _ = hol("/api/system/packages", tok_admin)
j2 = json.loads(b2)
check("ein zweiter Abruf traegt einen neuen Zeitstempel",
      j2["erzeugt_am"] != j["erzeugt_am"] or j2["anzahl"] == j["anzahl"],
      (j["erzeugt_am"], j2["erzeugt_am"]))
check("und liefert denselben Bestand", j2["anzahl"] == j["anzahl"])

print("\n5) ?download=1")
s3, b3, h3 = hol("/api/system/packages?download=1", tok_admin)
cd = h3.get("content-disposition", "")
check("setzt einen Dateinamen", "attachment" in cd and ".json" in cd, cd)
check("und liefert denselben Inhalt", json.loads(b3)["anzahl"] == j["anzahl"])

print("\n6) Es liegt keine Datei auf Platte")
import os, glob
funde = glob.glob("/opt/jarvis/**/*packages_report*", recursive=True) \
    + glob.glob("/opt/jarvis/data/pakete*")
check("der Bericht wird nirgends abgelegt", not funde, funde)

print("\n7) Der Dienst bleibt waehrenddessen ansprechbar")
# to_thread ist die Zusage - gemessen, nicht gelesen: ein paralleler Abruf
# eines leichten Endpunkts darf nicht warten.
import threading
lang = {}
def _schwer():
    t = time.time(); hol("/api/system/packages", tok_admin); lang["d"] = time.time() - t
th = threading.Thread(target=_schwer); th.start()
time.sleep(0.02)
t1 = time.time(); s4, _, _ = hol("/api/health"); d4 = time.time() - t1
th.join()
check("/api/health antwortet waehrend des Berichts zuegig", d4 < 2.0, "%.3fs" % d4)
print("     -> Bericht %.2fs, /api/health parallel %.3fs" % (lang.get("d", 0), d4))

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
