#!/usr/bin/env python3
"""Live auf DEV: Wissensgraph-API – Rechte, Antwortform, Isolation im Bestand.

Gemessen ueber den laufenden Dienst (nicht ueber ein zweites Objekt derselben
Klasse – Register):
  1. Positivkontrolle: Status als Admin 200 mit der erwarteten Form.
  2. Jede /api/wissensgraph/*-Route verweigert einem Nicht-Admin (401/403).
  3. Abweisungen ohne Wirkung: unbekanntes Einstellungsfeld → 400, Ordner
     ausserhalb von data/rag → 400; die Einstellungen sind danach UNVERAENDERT.
  4. Ist der Graph gebaut: jede Quelle auf der Platte liegt unter data/rag/
     bzw. /mnt/rag/ und im eingestellten Umfang (Wissensgruppen).

⚠ AENDERT NICHTS: alle schreibenden Aufrufe sind absichtlich ungueltig und
werden abgewiesen; am Ende wird der Einstellungsstand mit dem vorgefundenen
verglichen.

Aufruf auf DEV (Tokens brauchen den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_wissensgraph_dev.py [nicht-admin]
"""
import json
import ssl
import sys
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
from backend import wissensgraph as WG                             # noqa: E402

ADMIN = M.generate_token("jarvis")
FREMD = M.generate_token(sys.argv[1] if len(sys.argv) > 1 else "probe.kein.admin")


def ruf(pfad, methode="GET", rumpf=None, token=ADMIN):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if daten:
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


print("1. Positivkontrolle")
s, st = ruf("/api/wissensgraph/status")
check("Status als Admin: 200", s == 200, s)
if s != 200:
    print("ABBRUCH – ohne erreichbaren Status sind die Folgepruefungen nicht deutbar")
    sys.exit(2)
check("Form: aktiv, arbeiter, warteschlange, graph, einstellungen",
      {"aktiv", "arbeiter", "warteschlange", "graph", "einstellungen"} <= set(st), sorted(st))
s, e_vor = ruf("/api/wissensgraph/einstellungen")
check("Einstellungen lesbar, mit Vorgaben", s == 200 and "vorgaben" in e_vor, s)

print("2. Kein Zugriff ohne Admin")
ROUTEN = [("GET", "/api/wissensgraph/status", None),
          ("GET", "/api/wissensgraph/einstellungen", None),
          ("POST", "/api/wissensgraph/einstellungen", {"gibt_es_nicht": 1}),
          ("POST", "/api/wissensgraph/neuaufbau", {"umfang": "ordner", "ordner": "/etc"}),
          ("POST", "/api/wissensgraph/abbrechen", None),
          # Phase 6
          ("GET", "/api/wissensgraph/widersprueche", None),
          ("GET", "/api/wissensgraph/wiki/e:x", None),
          ("POST", "/api/wissensgraph/wiki/e:x", None),
          ("GET", "/api/wissensgraph/export", None),
          ("GET", "/api/wissensgraph/rueckmeldung", None),
          ("POST", "/api/wissensgraph/rueckmeldung", {"schluessel": "v:x", "art": "v"}),
          ("DELETE", "/api/wissensgraph/rueckmeldung", None)]
# abbrechen IST wirksam (leert die Schlange) – es wird nur als Nicht-Admin
# gerufen, nie als Admin.
for m, pfad, rumpf in ROUTEN:
    s, _ = ruf(pfad, m, rumpf if rumpf is not None else ({} if m == "POST" else None), token=FREMD)
    check("%s %s → %s" % (m, pfad, s), s in (401, 403), s)

print("3. Abweisungen ohne Wirkung")
s, r = ruf("/api/wissensgraph/einstellungen", "POST", {"gibt_es_nicht": True})
check("unbekanntes Feld → 400", s == 400, (s, r))
s, r = ruf("/api/wissensgraph/einstellungen", "POST", {"block_woerter": "viel"})
check("falscher Typ → 400", s == 400, (s, r))
s, r = ruf("/api/wissensgraph/neuaufbau", "POST", {"umfang": "ordner", "ordner": "data/erfahrung"})
check("Neuaufbau fuer data/erfahrung → 400", s == 400, (s, r))
s, r = ruf("/api/wissensgraph/neuaufbau", "POST", {"umfang": "unbekannt"})
check("unbekannter Umfang → 400", s == 400, (s, r))
s, e_nach = ruf("/api/wissensgraph/einstellungen")
check("Einstellungen danach unveraendert", e_nach.get("einstellungen") == e_vor.get("einstellungen"),
      (e_vor.get("einstellungen"), e_nach.get("einstellungen")))

print("4. Isolation im gebauten Bestand")
quellen = WG.quellen_alle()
roh = sorted((WG.ORDNER / "quellen").glob("*.json")) if (WG.ORDNER / "quellen").is_dir() else []
print("     (%d Quelldateien auf der Platte, %d gelesen)" % (len(roh), len(quellen)))
if not roh:
    print("     – Graph noch nicht gebaut, Abschnitt uebersprungen")
else:
    pfade = [json.loads(p.read_text(encoding="utf-8")).get("pfad", "") for p in roh]
    check("jede Quelldatei liegt unter data/rag/ oder mnt/rag/",
          all(p.startswith(("data/rag/", "mnt/rag/")) for p in pfade),
          [p for p in pfade if not p.startswith(("data/rag/", "mnt/rag/"))][:5])
    gruppen = (e_vor.get("einstellungen") or {}).get("gruppen") or []
    if gruppen:
        im = KG.filter_paths_by_groups(pfade, gruppen)
        check("jede Quelle gehoert zum eingestellten Umfang %s" % gruppen, len(im) == len(pfade),
              sorted(set(pfade) - set(im))[:5])
    g = st.get("graph") or {}
    check("Kennzahlen passen zur Platte (Quellen)", g.get("quellen") == len(quellen), (g, len(quellen)))
    modus = oct(WG.ORDNER.stat().st_mode & 0o777)
    check("Ablage ist fuer andere Konten zu (0750)", modus == "0o750", modus)

print("5. Phase 6 (nur lesend bzw. mit Wiederherstellung)")
s, w = ruf("/api/wissensgraph/widersprueche")
check("Widersprueche lesbar", s == 200 and isinstance(w.get("befunde"), list), s)
befunde = w.get("befunde") or []
check("jeder Befund nennt Begriff, zwei Dokumente und zwei Aussagen",
      all(b.get("kid") and b.get("a") and b.get("b") and b["a"] != b["b"] and b.get("aussage_a") and b.get("aussage_b")
          for b in befunde), befunde[:1])
s, r = ruf("/api/wissensgraph/wiki/e:gibt%20es%20sicher%20nicht")
check("Wiki-Seite eines unbekannten Begriffs → 404", s == 404, s)
s, r = ruf("/api/wissensgraph/wiki/e:gibt%20es%20sicher%20nicht", "POST", {})
check("Erzeugen fuer unbekannten Begriff → 404 (kein Modellaufruf)", s == 404, (s, r))
s, r = ruf("/api/wissensgraph/rueckmeldung", "POST", {"schluessel": "v:x", "art": "z"})
check("Rueckmeldung mit fremder Art → 400", s == 400, (s, r))
s, vorher = ruf("/api/wissensgraph/rueckmeldung")
check("Rueckmeldungen lesbar", s == 200 and isinstance(vorher.get("verworfen"), list), s)
# Export: als Rohdaten holen (kein JSON)
r = urllib.request.Request(BASIS + "/api/wissensgraph/export")
r.add_header("Authorization", "Bearer " + ADMIN)
try:
    with urllib.request.urlopen(r, context=_KTX, timeout=300) as a:
        daten, art, cd = a.read(), a.headers.get("Content-Type", ""), a.headers.get("Content-Disposition", "")
except Exception as e:                                             # noqa: BLE001
    daten, art, cd = b"", str(e), ""
import io
import zipfile
check("Export: ZIP mit Dateinamen", daten[:2] == b"PK" and "zip" in art and "filename=" in cd, (art, cd, daten[:4]))
if daten[:2] == b"PK":
    z = zipfile.ZipFile(io.BytesIO(daten))
    namen = z.namelist()
    n_begriffe = sum(1 for n in namen if n.startswith("Wissensgraph/Begriffe/"))
    n_quellen = sum(1 for n in namen if n.startswith("Wissensgraph/Quellen/"))
    g = st.get("graph") or {}
    check("Export: je Begriff und je Quelle eine Notiz", n_begriffe == g.get("entitaeten") and n_quellen == g.get("quellen"),
          (n_begriffe, n_quellen, g))

print("\nErgebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
