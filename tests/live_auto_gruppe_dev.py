#!/usr/bin/env python3
"""Live auf DEV: neue Dateien eines Speicherordners bekommen dessen Wissensgruppe.

Durchstich ueber den ECHTEN Produktivweg: Datei in einen Wissensordner legen,
den Cron-Auftrag 'Wissensabgleich' ausloesen (rag_autoindex → force_reindex
incremental → _vector_index_lauf), dann die Zuordnung am Endpunkt lesen.
Dazu die zweite Zusage: eine von Hand ausgetragene Datei kommt beim naechsten
Lauf NICHT zurueck.

⚠ DIESE PROBE AENDERT DEN BESTAND und stellt ihn wieder her: die Probedateien
werden geloescht, ein weiterer Abgleich raeumt den Index, und das
Gruppen-Manifest wird am Ende mit dem vorgefundenen Stand verglichen (bei
Abweichung byte-genau zurueckgeschrieben – knowledge_groups liest es bei jedem
Aufruf von der Platte, es gibt keinen Zwischenspeicher im Dienst).
NICHT zurueckstellbar und deshalb benannt: der Cron-Auftrag traegt danach
diesen Lauf als letzten Lauf.

Aufruf auf DEV (Tokens brauchen den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_auto_gruppe_dev.py <benutzer>
"""
import atexit
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import main as M                                      # noqa: E402
from backend import knowledge_groups as KG                         # noqa: E402

BENUTZER = sys.argv[1] if len(sys.argv) > 1 else "jarvis"
TOKEN = M.generate_token(BENUTZER)
ORDNER_REL = "data/rag/community"
ORDNER = Path("/opt/jarvis") / ORDNER_REL
GRUPPE = "allgemein"
PROBEN = [ORDNER / ("_probe_autogruppe_%s.md" % x) for x in ("a", "b", "c")]
MANIFEST_VOR = KG.MANIFEST_PATH.read_bytes()


def ruf(pfad, methode="GET", rumpf=None):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + TOKEN)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=300) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


def gruppen_von(datei):
    s, d = ruf("/api/knowledge/assignments?path=%s" % urllib.request.quote(
        str(datei.relative_to("/opt/jarvis"))))
    return d.get("groups") if s == 200 else ("HTTP %s" % s)


def abgleich():
    return ruf("/api/cron/wissensabgleich/run", "POST")


def aufraeumen():
    for p in PROBEN:
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    s, d = abgleich()
    print("  (Aufraeumen: Abgleich %s – %s)" % (s, str(d.get("result", ""))[:80]))
    if json.loads(KG.MANIFEST_PATH.read_bytes()) != json.loads(MANIFEST_VOR):
        KG.MANIFEST_PATH.write_bytes(MANIFEST_VOR)
        print("  (Manifest auf den vorgefundenen Stand zurueckgeschrieben)")
    print("  Manifest danach wie vorgefunden: %s"
          % (json.loads(KG.MANIFEST_PATH.read_bytes()) == json.loads(MANIFEST_VOR)))


# ── Positivkontrollen VOR jeder Wirkung ─────────────────────────────────────
print("Benutzer: %s" % BENUTZER)
s, _ = ruf("/api/knowledge/stats")
if s != 200:
    print("ABBRUCH: Token gilt nicht (HTTP %s)" % s)
    sys.exit(2)
s, d = ruf("/api/cron/wissensabgleich/log?limit=1")
if s != 200:
    print("ABBRUCH: Auftrag 'wissensabgleich' nicht erreichbar (HTTP %s)" % s)
    sys.exit(2)
m = json.loads(MANIFEST_VOR)
if not any(g["id"] == GRUPPE and ORDNER_REL in g.get("folders", []) for g in m["groups"]):
    print("ABBRUCH: %s ist auf DEV nicht Speicherordner von %s – Lage nicht herstellbar"
          % (ORDNER_REL, GRUPPE))
    sys.exit(2)
if any(p.exists() for p in PROBEN):
    print("ABBRUCH: Probedateien liegen schon (Rueckstand?)")
    sys.exit(2)

atexit.register(aufraeumen)

print("\n1. Neue Dateien → Wissensabgleich → Gruppe")
for p in PROBEN[:2]:
    p.write_text("# Probe Autogruppe\n\nKundenliste Musterstadt, Schnittstelle %s.\n" % p.name,
                 encoding="utf-8")
t0 = time.time()
s, d = abgleich()
check("Abgleich laeuft durch (Admin, 200)", s == 200, "%s %s" % (s, d))
print("     Ergebnis: %s (%.1f s)" % (str(d.get("result", ""))[:100], time.time() - t0))
check("Datei a hat die Gruppe des Speicherordners", gruppen_von(PROBEN[0]) == [GRUPPE],
      gruppen_von(PROBEN[0]))
check("Datei b ebenso", gruppen_von(PROBEN[1]) == [GRUPPE], gruppen_von(PROBEN[1]))

print("\n2. Von Hand ausgetragen bleibt ausgetragen")
s, d = ruf("/api/knowledge/assignments", "POST",
           {"path": str(PROBEN[0].relative_to("/opt/jarvis")), "groups": []})
check("Austragen ueber den echten Endpunkt", s == 200, "%s %s" % (s, d))
check("Positivkontrolle: a ist jetzt ohne Gruppe", gruppen_von(PROBEN[0]) == [], gruppen_von(PROBEN[0]))
PROBEN[2].write_text("# Probe c\n\nNoch eine neue Liste.\n", encoding="utf-8")
time.sleep(1.1)
PROBEN[1].write_text(PROBEN[1].read_text(encoding="utf-8") + "\nGeaendert.\n", encoding="utf-8")
s, d = abgleich()
print("     Ergebnis: %s" % str(d.get("result", ""))[:100])
check("Positivkontrolle: der zweite Lauf hat gearbeitet (neue Datei c zugeordnet)",
      gruppen_von(PROBEN[2]) == [GRUPPE], gruppen_von(PROBEN[2]))
check("⚠ a ist NICHT zurueckgekommen", gruppen_von(PROBEN[0]) == [], gruppen_von(PROBEN[0]))
check("b behaelt die Gruppe nach einer Aenderung", gruppen_von(PROBEN[1]) == [GRUPPE],
      gruppen_von(PROBEN[1]))

print("\n3. Verknuepfungs-Endpunkt")
s, d = ruf("/api/knowledge/folders/groups", "POST", {"path": ORDNER_REL, "groups": [GRUPPE]})
check("Speichern der (unveraenderten) Verknuepfung: 200", s == 200, "%s %s" % (s, d))
check("… meldet 0 neue Zuordnungen (alles schon gesehen)", d.get("zugeordnet") == 0, d)
check("… und a bleibt ausgetragen", gruppen_von(PROBEN[0]) == [], gruppen_von(PROBEN[0]))

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
