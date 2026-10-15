"""Live gegen den ECHTEN Endpunkt auf DEV. REIN LESEND – kein Zustand wird
veraendert (kein Schalter, keine Freigabe, keine Datei)."""
import json, ssl, sys, urllib.request, urllib.parse
sys.path.insert(0, '/opt/jarvis')
from backend.main import generate_token   # derselbe Weg wie nach dem Login

ok = fail = 0
def check(t, b, z=""):
    global ok, fail
    if b: ok += 1; print("  \033[32m✓\033[0m " + t)
    else: fail += 1; print("  \033[31m✗\033[0m " + t + (("  [" + str(z) + "]") if z else ""))

TOK = generate_token("jarvis")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
BASIS = "https://127.0.0.1/api/security/violations"

def hole(user=None, token=TOK):
    u = BASIS + ("?user=" + urllib.parse.quote(user) if user else "")
    r = urllib.request.Request(u)
    if token: r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=25) as a:
            return a.status, json.loads(a.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None

print("\n\033[1m1. Ohne Filter – Positivkontrolle\033[0m")
st, d = hole()
check("Endpunkt antwortet 200", st == 200, st)
check("Positivkontrolle: es gibt ueberhaupt Eintraege", bool(d) and len(d.get("violations") or []) > 0,
      len(d.get("violations") or []) if d else "-")
check("die Benutzerliste kommt mit", bool(d) and isinstance(d.get("users"), list) and d["users"],
      d.get("users") if d else "-")
check("'gesamt' kommt mit", bool(d) and isinstance(d.get("gesamt"), dict), d.get("gesamt") if d else "-")
alle = d["violations"]; users = d["users"]; ges = d["gesamt"]
print("     Bestand: %d Eintraege, %d hart / %d weich, Benutzer: %s"
      % (ges["anzahl"], ges["hart"], ges["weich"], users))
check("gesamt.anzahl passt zur ungefilterten Liste", ges["anzahl"] == len(alle), (ges, len(alle)))

print("\n\033[1m2. Jeder angebotene Benutzer findet auch wirklich Eintraege\033[0m")
summe = 0
for u in users:
    st2, d2 = hole(u)
    n = len(d2.get("violations") or []) if d2 else -1
    summe += n
    check("Filter '%s' liefert %d Eintraege – und nur seine" % (u, n),
          st2 == 200 and n > 0 and all(e.get("user") == u for e in d2["violations"]), n)
    check("  und der Zaehler nennt weiter den GESAMTbestand (%d)" % ges["anzahl"],
          d2 and d2.get("gesamt", {}).get("anzahl") == ges["anzahl"], d2.get("gesamt") if d2 else "-")
    check("  und das Pulldown bleibt vollstaendig (%d Namen)" % len(users),
          d2 and d2.get("users") == users, d2.get("users") if d2 else "-")
check("die Summe der gefilterten Listen deckt den Bestand", summe <= ges["anzahl"] and summe > 0,
      "%d von %d (Rest: Eintraege ohne Benutzer)" % (summe, ges["anzahl"]))

print("\n\033[1m3. Die Namensformen\033[0m")
u0 = users[0]
n_voll = len(hole(u0)[1]["violations"])
kurz = u0.split("\\")[-1]
if kurz != u0:
    check("ohne Domaenen-Praefix ('%s') dieselbe Zahl" % kurz,
          len(hole(kurz)[1]["violations"]) == n_voll, len(hole(kurz)[1]["violations"]))
check("GROSS geschrieben dieselbe Zahl", len(hole(u0.upper())[1]["violations"]) == n_voll)
check("unbekannter Benutzer -> leere Liste, kein Fehler",
      hole("gibtsnicht")[0] == 200 and hole("gibtsnicht")[1]["violations"] == [])
check("  und der Zaehler nennt trotzdem den Bestand",
      hole("gibtsnicht")[1]["gesamt"]["anzahl"] == ges["anzahl"])

print("\n\033[1m4. Rechte\033[0m")
check("ohne Token: 401", hole(None, token=None)[0] == 401, hole(None, token=None)[0])
check("mit Muell-Token: 401", hole(None, token="muell")[0] == 401, hole(None, token="muell")[0])

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
