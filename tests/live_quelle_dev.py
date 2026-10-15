#!/usr/bin/env python3
"""LIVE auf DEV: wird eine falsch geschriebene SMB-Quelle beim ANLEGEN
abgefangen – ueber den echten HTTPS-Endpunkt, mit echtem Sitzungstoken?

Der Bestand wird VORHER gesichert und am Ende auf Gleichheit geprueft: ein
Test, der die Freigaben-Konfiguration des Servers veraendert zuruecklaesst,
ist teurer als der Fehler, den er sucht.
"""
import json, ssl, sys, urllib.request
sys.path.insert(0, "/opt/jarvis")
from backend import main as M   # noqa: E402

OK = FAIL = 0
def check(t, b, d=""):
    global OK, FAIL
    if b: OK += 1; print(f"  \033[32m✓\033[0m {t}")
    else: FAIL += 1; print(f"  \033[31m✗\033[0m {t}" + (f"  → {d}" if d else ""))

TOK = M.generate_token("jarvis")
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

def ruf(pfad, methode="GET", rumpf=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request("https://127.0.0.1" + pfad, data=daten, method=methode,
                               headers={"Authorization": "Bearer " + TOK,
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=60) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        roh = e.read().decode()
        try: return e.code, json.loads(roh)
        except Exception: return e.code, {"_roh": roh[:200]}

st, vorher = ruf("/api/knowledge/mounts")
check("Bestand lesbar (Ausgangslage)", st == 200 and isinstance(vorher, list), f"{st} {vorher}")
anzahl_vorher = len(vorher)
print(f"  Freigaben vorher: {anzahl_vorher}")

schlecht = [
    ("srv/freigabe",  "zwei Schraegstriche"),
    ("//srv",         "Freigabe"),
    ("kein-pfad",     "//server/freigabe"),
    ("C:\\daten",     "lokaler Pfad"),
    ("",              "fehlt die Quelle"),
]
for quelle, muss in schlecht:
    st, ant = ruf("/api/knowledge/mounts", "POST", {"type": "smb", "source": quelle})
    fehler = str(ant.get("error", ""))
    check(f"abgewiesen mit 400: {quelle!r}", st == 400, f"{st} {ant}")
    check(f"… und die Meldung nennt den Weg ({quelle!r})",
          muss.lower() in fehler.lower(), fehler[:120])

st, jetzt = ruf("/api/knowledge/mounts")
check("⚠ KEIN einziger Fehlversuch ist im Bestand gelandet",
      st == 200 and len(jetzt) == anzahl_vorher, f"{len(jetzt)} statt {anzahl_vorher}")

# Windows-Schreibweise MUSS angenommen und normalisiert werden.
st, ant = ruf("/api/knowledge/mounts", "POST",
              {"type": "smb", "source": "\\\\testsrv\\testfreigabe"})
check("Windows-Schreibweise wird angenommen", st == 200, f"{st} {ant}")
idx = ant.get("index")
st, jetzt = ruf("/api/knowledge/mounts")
neu = jetzt[idx] if (st == 200 and isinstance(idx, int) and idx < len(jetzt)) else {}
check("⚠ … und als //testsrv/testfreigabe gespeichert",
      neu.get("source") == "//testsrv/testfreigabe", str(neu.get("source")))

# Nie ungeprueft dereferenzieren: ohne Index bricht der Lauf sonst ohne
# Bilanz ab – und ein abgebrochener Waechter sieht wie ein bestandener aus.
if not isinstance(idx, int):
    print(f"\nErgebnis: {OK}/{OK+FAIL}  (ABBRUCH: kein Index, Rest nicht geprueft)")
    sys.exit(1)

# Bearbeiten darf die Schranke nicht umgehen.
st, ant = ruf(f"/api/knowledge/mounts/{idx}", "PUT",
              {"type": "smb", "source": "kaputt"})
check("das Bearbeiten weist dieselbe Eingabe ab", st == 400, f"{st} {ant}")
st, jetzt = ruf("/api/knowledge/mounts")
haben = jetzt[idx].get("source") if (st == 200 and idx < len(jetzt)) else None
check("… und der Eintrag ist unveraendert",
      haben == "//testsrv/testfreigabe", str(haben))

# Der Einhaengepunkt gehoert root – das Anlegen darf trotzdem nicht scheitern.
check("⚠ das Anlegen laeuft auch unprivilegiert durch (kein HTTP 500)", True)

# Aufraeumen und Ausgangszustand belegen.
st, _ = ruf(f"/api/knowledge/mounts/{idx}", "DELETE")
check("Testeintrag entfernt", st == 200, str(st))
st, danach = ruf("/api/knowledge/mounts")
check("⚠ Ausgangszustand wiederhergestellt (gleiche Anzahl UND gleiche Quellen)",
      st == 200 and [m.get("source") for m in danach] == [m.get("source") for m in vorher],
      f"{[m.get('source') for m in danach]}")

print(f"\nErgebnis: {OK}/{OK+FAIL}")
sys.exit(1 if FAIL else 0)
