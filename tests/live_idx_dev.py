#!/usr/bin/env python3
"""LIVE auf DEV: verschiebt das Loeschen einer Freigabe die Einhaengepunkte?

Die ZWEI ECHTEN Freigaben werden nicht angefasst – geprueft wird mit zwei
Testeintraegen dahinter, und ihr Zustand wird vorher und nachher verglichen.
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
def ruf(p, m="GET", b=None, z=120):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request("https://127.0.0.1"+p, data=d, method=m,
                               headers={"Authorization": "Bearer "+TOK,
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=z) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except Exception: return e.code, {}

def liste():
    st, m = ruf("/api/knowledge/mounts")
    return m if st == 200 else []

def mounts_auf_platte():
    with open("/proc/mounts") as f:
        return sorted(z.split(" ")[1] for z in f if len(z.split(" ")) > 1
                      and z.split(" ")[1].startswith("/mnt/jarvis-kb"))

vorher = liste()
print("  Bestand:", json.dumps([{"s": x["source"], "mp": x["mountpoint"],
                                 "aktiv": x["active"]} for x in vorher],
                               ensure_ascii=False))
echt = len(vorher)
check("Bestand lesbar", echt >= 1, str(echt))
check("⚠ MIGRATION: jede Bestandsfreigabe hat jetzt einen festen Einhaengepunkt",
      all(x.get("mountpoint") for x in vorher), str([x.get("mountpoint") for x in vorher]))
gemountet_vorher = mounts_auf_platte()
print("  gemountet:", gemountet_vorher)
check("⚠ und die laufenden Mounts sind noch da (Migration hat nichts verschoben)",
      len(gemountet_vorher) >= 1 and all(
          x["mountpoint"] in gemountet_vorher for x in vorher if x["active"]),
      f"{gemountet_vorher} / {[x['mountpoint'] for x in vorher if x['active']]}")

# Zwei Testeintraege dahinter anlegen.
st, a1 = ruf("/api/knowledge/mounts", "POST", {"type": "smb", "source": "//testsrv/eins"})
st2, a2 = ruf("/api/knowledge/mounts", "POST", {"type": "smb", "source": "//testsrv/zwei"})
check("zwei Testfreigaben angelegt", st == 200 and st2 == 200, f"{st}/{st2}")
i1, i2 = a1.get("index"), a2.get("index")
if not isinstance(i1, int) or not isinstance(i2, int):
    print(f"\nErgebnis: {OK}/{OK+FAIL}  (ABBRUCH: keine Indizes)"); sys.exit(1)

nach_anlegen = liste()
mp1 = nach_anlegen[i1]["mountpoint"]; mp2 = nach_anlegen[i2]["mountpoint"]
print(f"  Testpunkte: {mp1} / {mp2}")
check("die neuen Punkte kollidieren mit keinem vorhandenen",
      mp1 != mp2 and mp1 not in gemountet_vorher and mp2 not in gemountet_vorher,
      f"{mp1} / {mp2}")

# Die ERSTE Testfreigabe loeschen -> die zweite rutscht im Index nach vorn.
st, _ = ruf(f"/api/knowledge/mounts/{i1}", "DELETE")
check("erste Testfreigabe geloescht", st == 200, str(st))
danach = liste()
check("die Liste ist um eins kuerzer", len(danach) == echt + 1, str(len(danach)))
verschoben = danach[i1] if i1 < len(danach) else {}
check("⚠ DER KERN: die nachgerutschte Freigabe behaelt ihren Einhaengepunkt",
      verschoben.get("source") == "//testsrv/zwei"
      and verschoben.get("mountpoint") == mp2,
      f"{verschoben.get('source')} -> {verschoben.get('mountpoint')} (erwartet {mp2})")

# Und die echten Freigaben sind unberuehrt.
jetzt_echt = danach[:echt]
check("⚠ die echten Freigaben sind unveraendert (Quelle, Punkt, Zustand)",
      [(x["source"], x["mountpoint"], x["active"]) for x in jetzt_echt]
      == [(x["source"], x["mountpoint"], x["active"]) for x in vorher],
      json.dumps([{"s": x["source"], "mp": x["mountpoint"], "a": x["active"]}
                  for x in jetzt_echt], ensure_ascii=False))

# Aufraeumen.
st, _ = ruf(f"/api/knowledge/mounts/{i1}", "DELETE")
check("Testeintrag entfernt", st == 200, str(st))
ende = liste()
check("⚠ Ausgangszustand wiederhergestellt",
      [(x["source"], x["mountpoint"], x["active"]) for x in ende]
      == [(x["source"], x["mountpoint"], x["active"]) for x in vorher],
      json.dumps([{"s": x["source"], "mp": x["mountpoint"]} for x in ende],
                 ensure_ascii=False))
check("… und die laufenden Mounts stehen weiter",
      mounts_auf_platte() == gemountet_vorher,
      f"{mounts_auf_platte()} statt {gemountet_vorher}")

print(f"\nErgebnis: {OK}/{OK+FAIL}")
sys.exit(1 if FAIL else 0)
