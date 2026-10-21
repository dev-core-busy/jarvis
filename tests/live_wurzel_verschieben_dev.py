#!/usr/bin/env python3
"""Live auf DEV: einen Wurzelordner unter data/rag in einen anderen Wissensordner
verschieben (2026-10-21).

Durchstich ueber die ECHTEN Endpunkte: eine Probe-Wurzel mit einer Datei wird
angelegt, einer Probegruppe als Speicherordner gegeben und indiziert, dann in
den ersten anderen Wissensordner unter data/rag verschoben und danach zurueck
nach data/rag (Gegenrichtung: wieder eigener Wissensordner). Gemessen:
Ordnerliste (Wurzel weg), Gruppen-Speicherordner (zieht mit, wird
Unterordner-Speicherordner), Datei-Zuordnung (zieht mit), Verzeichnis.

⚠ DIESE PROBE AENDERT DEN BESTAND und stellt ihn wieder her: der verschobene
Probeordner wird samt Index-Eintraegen ueber den Loesch-Endpunkt entfernt, das
Gruppen-Manifest wird byte-genau zurueckgeschrieben, und die Ordnerliste muss
am Ende der vorgefundenen gleichen (sonst FAIL – dann steht dort ein Rest).

Aufruf auf DEV (Tokens brauchen den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python \\
      tests/live_wurzel_verschieben_dev.py <globaler-wissens-editor>
"""
import atexit
import json
import shutil
import ssl
import sys
import urllib.error
import urllib.request
import uuid
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
        # (info,) statt info: ein Tupel als Info wuerde sonst als Argumentliste
        # gelesen, und die Fehlermeldung selbst WARF (live auf DEV gesehen).
        print("  FAIL %s%s" % (text, ("  [%s]" % (info,)) if info else ""))


from backend import main as M                                      # noqa: E402
from backend import knowledge_groups as KG                         # noqa: E402

if len(sys.argv) < 2:
    print("ABBRUCH – Aufruf: … live_wurzel_verschieben_dev.py <globaler-wissens-editor>")
    sys.exit(2)
ADMIN = sys.argv[1]
if not M._may_edit_knowledge(ADMIN):
    print("ABBRUCH – '%s' ist kein globaler Wissens-Editor" % ADMIN)
    sys.exit(2)
TOKEN = M.generate_token(M._display_name(ADMIN))
PROJ = Path("/opt/jarvis")
NAME = "probewv" + uuid.uuid4().hex[:6]   # Ordnernamen muessen mit Buchstabe/Zahl beginnen
QUELLE = "data/rag/" + NAME
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


def liste():
    s, d = ruf("/api/knowledge/stats")
    return [f["path"] for f in d.get("folders", [])] if s == 200 else None


LISTE_VOR = liste()
ZIEL = next((f for f in (LISTE_VOR or []) if f.startswith("data/rag/")), None)
if LISTE_VOR is None or ZIEL is None:
    print("ABBRUCH – Ordnerliste nicht lesbar oder kein Ziel unter data/rag")
    sys.exit(2)
NEU = ZIEL + "/" + NAME
REST = []          # was am Ende noch weggeraeumt werden muss


def aufraeumen():
    for rel in REST:
        if rel == QUELLE:
            ruf("/api/knowledge/folders", "DELETE", {"path": rel, "delete_files": True})
        else:
            ruf("/api/knowledge/subfolders", "DELETE", {"path": rel, "delete_files": True})
        shutil.rmtree(PROJ / rel, ignore_errors=True)
    if KG.MANIFEST_PATH.read_bytes() != MANIFEST_VOR:
        KG.MANIFEST_PATH.write_bytes(MANIFEST_VOR)


atexit.register(aufraeumen)

print("0. Positivkontrolle: Probe-Wurzel anlegen")
s, g = ruf("/api/knowledge/groups", "POST", {"name": "_probe_wv"})
GID = g.get("group", {}).get("id") if s == 200 else None
s, d = ruf("/api/knowledge/folders", "POST", {"name": NAME, "groups": [GID] if GID else []})
check("Wurzel angelegt (200)", s == 200, (s, d))
if s != 200 or not GID:
    sys.exit(2)
REST.append(QUELLE)
datei = PROJ / QUELLE / "probe.md"
datei.write_text("# Probe\nWurzel verschieben\n", encoding="utf-8")
KG.set_assignment(str(datei.relative_to(PROJ)), [GID])
check("Wurzel steht in der Ordnerliste", QUELLE in (liste() or []))
check("Gruppe fuehrt die Wurzel als Speicherordner",
      (KG.get_group(GID) or {}).get("folders") == [QUELLE], KG.get_group(GID))

print("\n1. Verschieben ueber die Verwaltung")
s, d = ruf("/api/knowledge/subfolders/move", "POST", {"path": QUELLE, "target": ZIEL})
check("200, was_root", s == 200 and d.get("was_root") is True and d.get("path") == NEU, (s, d))
if s == 200:
    REST[:] = [NEU]
check("Verzeichnis liegt unter dem Ziel",
      (PROJ / NEU / "probe.md").is_file() and not (PROJ / QUELLE).exists())
nachher = liste() or []
check("Wurzel aus der Ordnerliste ausgetragen", QUELLE not in nachher, nachher)
check("Ordnerliste sonst unveraendert", nachher == LISTE_VOR, (nachher, LISTE_VOR))
check("Gruppen-Speicherordner zog mit (jetzt Unterordner)",
      (KG.get_group(GID) or {}).get("folders") == [NEU], KG.get_group(GID))
check("Datei-Zuordnung zog mit", KG.get_assignment(NEU + "/probe.md") == [GID],
      KG.get_assignment(NEU + "/probe.md"))

print("\n2. Rueckweg: wieder eigener Wissensordner (Ziel data/rag)")
s, d = ruf("/api/knowledge/subfolders/move", "POST", {"path": NEU, "target": "data/rag"})
check("200, now_root", s == 200 and d.get("now_root") is True and d.get("path") == QUELLE, (s, d))
if s == 200:
    REST[:] = [QUELLE]
zurueck = liste() or []
check("wieder in der Ordnerliste", QUELLE in zurueck, zurueck)
check("Ordnerliste sonst unveraendert",
      [f for f in zurueck if f != QUELLE] == LISTE_VOR, (zurueck, LISTE_VOR))
check("Verzeichnis wieder direkt unter data/rag",
      (PROJ / QUELLE / "probe.md").is_file() and not (PROJ / NEU).exists())
check("Gruppen-Speicherordner wieder die Wurzel",
      (KG.get_group(GID) or {}).get("folders") == [QUELLE], KG.get_group(GID))
check("Datei-Zuordnung zog zurueck", KG.get_assignment(QUELLE + "/probe.md") == [GID],
      KG.get_assignment(QUELLE + "/probe.md"))

# Bewusst KEIN /wissen-Fall hier: jeder Wurzelordner auf DEV enthaelt
# Speicherordner und scheiterte schon an deren Sperre – die Probe traefe auf
# zwei Wegen und maesse keinen. Dass /wissen den Schalter nicht setzt, prueft
# tests/test_wurzel_verschieben.py am Syntaxbaum.

aufraeumen()
REST.clear()
check("Probeordner entfernt", not (PROJ / NEU).exists() and not (PROJ / QUELLE).exists())
check("Ordnerliste wie vorgefunden", liste() == LISTE_VOR)
check("Manifest byte-gleich wiederhergestellt", KG.MANIFEST_PATH.read_bytes() == MANIFEST_VOR)
print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
