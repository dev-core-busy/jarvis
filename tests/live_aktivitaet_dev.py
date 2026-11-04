#!/usr/bin/env python3
"""Live auf DEV: das Aktivitaetsprotokoll ueber die ECHTEN Endpunkte.

Durchstich: ein Probe-Unterordner wird angelegt und entfernt, eine
Probe-Wissensgruppe angelegt, ihr Editor gesetzt (Rechte-Pfad: zusaetzlich
ins Sicherheitsprotokoll) und geloescht. Gemessen wird ueber
``GET /api/logs/aktivitaet`` bzw. ``GET /api/security/log`` des laufenden
Dienstes – nicht ueber ein zweites Objekt im Probeprozess (Register).

⚠ DIESE PROBE AENDERT DEN BESTAND und stellt ihn wieder her: Probeordner und
Probegruppe werden entfernt, das Gruppen-Manifest am Ende byte-genau
zurueckgeschrieben. Die PROTOKOLLZEILEN bleiben stehen – sie sind der Beleg
(Aktivitaetsprotokoll und Sicherheitsprotokoll, je mit Kennung ``probeakt``).

Aufruf auf DEV (Tokens brauchen den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python \
      tests/live_aktivitaet_dev.py <admin-und-globaler-wissens-editor>
"""
import atexit
import json
import shutil
import ssl
import sys
import urllib.error
import urllib.parse
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
        print("  FAIL %s%s" % (text, ("  [%s]" % (info,)) if info else ""))


from backend import main as M                                      # noqa: E402
from backend import knowledge_groups as KG                         # noqa: E402

if len(sys.argv) < 2:
    print("ABBRUCH – Aufruf: … live_aktivitaet_dev.py <admin-und-wissens-editor>")
    sys.exit(2)
ADMIN = sys.argv[1]
if not M._may_edit_knowledge(ADMIN):
    print("ABBRUCH – '%s' ist kein globaler Wissens-Editor" % ADMIN)
    sys.exit(2)
ANZEIGE = M._display_name(ADMIN)
TOKEN = M.generate_token(ANZEIGE)

WURZEL = next((f for f in M._kb_current_folder_list() if f.startswith("data/rag/")), None)
if WURZEL is None:
    print("ABBRUCH – kein Wissensordner unter data/rag konfiguriert")
    sys.exit(2)
PROJ = Path("/opt/jarvis")
# Kein fuehrender Unterstrich: die Ordnernamen-Pruefung weist ihn ab (live gesehen)
KENNUNG = "probeakt" + uuid.uuid4().hex[:8]
UNTER = "%s/%s" % (WURZEL, KENNUNG)
MANIFEST_VOR = KG.MANIFEST_PATH.read_bytes()
GID = None


def aufraeumen():
    shutil.rmtree(PROJ / UNTER, ignore_errors=True)
    if KG.MANIFEST_PATH.read_bytes() != MANIFEST_VOR:
        KG.MANIFEST_PATH.write_bytes(MANIFEST_VOR)


atexit.register(aufraeumen)


def ruf(pfad, methode="GET", rumpf=None):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + TOKEN)
    if rumpf is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=120) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


def eintraege(suche):
    s, d = ruf("/api/logs/aktivitaet?" + urllib.parse.urlencode({"suche": suche, "limit": 50}))
    return s, d.get("eintraege") or []


def finde(liste, aktion):
    return next((e for e in liste if e.get("aktion") == aktion), None)


print("0. Positivkontrolle")
s, d = ruf("/api/logs/aktivitaet?limit=1")
check("Lese-Endpunkt ist ausgerollt und gilt fuer das Token (200)", s == 200, s)
if s != 200:
    sys.exit(2)

print("1. Unterordner anlegen")
s, d = ruf("/api/knowledge/subfolders", "POST", {"parent": WURZEL, "name": KENNUNG})
check("Unterordner angelegt (200)", s == 200, (s, d))
s, liste = eintraege(KENNUNG)
e = finde(liste, "unterordner_angelegt") or {}
check("Eintrag 'unterordner_angelegt' mit dem Pfad als Gegenstand",
      e.get("objekt") == UNTER, e)
check("Benutzer ist das angemeldete Konto", e.get("benutzer") == ANZEIGE, e.get("benutzer"))
check("Herkunft (IP) steht im Eintrag", bool((e.get("details") or {}).get("ip")), e.get("details"))
check("Anzeigename wird mitgeliefert", bool(e.get("benutzer_anzeige")), e)

print("2. Probegruppe: anlegen, Editor setzen (Rechte), loeschen")
s, d = ruf("/api/knowledge/groups", "POST", {"name": KENNUNG, "color": "#64748b"})
GID = ((d or {}).get("group") or {}).get("id")
check("Probegruppe angelegt", s == 200 and bool(GID), (s, d))
if GID:
    s, d = ruf("/api/knowledge/groups/" + urllib.parse.quote(GID), "PATCH",
               {"editors_users": ANZEIGE})
    check("Editor gesetzt (200)", s == 200, (s, d))
    # Gesucht ueber die Gruppen-ID: sie wird aus dem Namen ABGELEITET und muss
    # die Kennung nicht woertlich enthalten (live gesehen)
    s, liste = eintraege(GID)
    g = next((x for x in liste if x.get("aktion") == "gruppe_geaendert"
              and x.get("objekt") == GID), {})
    check("Eintrag 'gruppe_geaendert' traegt die Rechte-Markierung",
          (g.get("details") or {}).get("rechte") is True, g)
    check("… und den neuen Editor im Wortlaut",
          (g.get("details") or {}).get("editors_users") == ANZEIGE, g.get("details"))
    s, d = ruf("/api/security/log?" + urllib.parse.urlencode({"art": "rechte_aenderung",
                                                               "limit": 50}))
    sl = [x for x in (d.get("eintraege") or [])
          if (x.get("details") or {}).get("objekt") == GID]
    check("Sicherheitsprotokoll: 'rechte_aenderung' fuer die Probegruppe",
          s == 200 and any((x.get("details") or {}).get("aktion") == "gruppe_geaendert"
                           for x in sl), (s, sl))
    check("Kette des Sicherheitsprotokolls bleibt intakt",
          bool((d.get("kette") or {}).get("ok")), d.get("kette"))
    s, d = ruf("/api/knowledge/groups/" + urllib.parse.quote(GID), "DELETE")
    check("Probegruppe geloescht", s == 200, (s, d))
    s, liste = eintraege(KENNUNG)
    g = next((x for x in liste if x.get("aktion") == "gruppe_geloescht"), {})
    check("Eintrag 'gruppe_geloescht' mit Rechte-Markierung",
          (g.get("details") or {}).get("rechte") is True and g.get("objekt") == GID, g)

print("3. Unterordner entfernen")
s, d = ruf("/api/knowledge/subfolders", "DELETE", {"path": UNTER, "delete_files": True})
check("Unterordner entfernt (200)", s == 200, (s, d))
s, liste = eintraege(KENNUNG)
e = finde(liste, "unterordner_entfernt") or {}
check("Eintrag 'unterordner_entfernt', Dateien geloescht",
      e.get("objekt") == UNTER and (e.get("details") or {}).get("dateien_geloescht") is True, e)
check("Suche liefert NUR Probe-Eintraege",
      bool(liste) and all(KENNUNG in json.dumps(x, ensure_ascii=False) for x in liste),
      [x.get("aktion") for x in liste])

aufraeumen()
check("Probeordner weg", not (PROJ / UNTER).exists())
check("Manifest byte-gleich wiederhergestellt", KG.MANIFEST_PATH.read_bytes() == MANIFEST_VOR)
print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
