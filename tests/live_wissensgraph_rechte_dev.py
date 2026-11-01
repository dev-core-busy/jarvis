#!/usr/bin/env python3
"""Live-Probe (DEV): Wissensgraph nach Wissensrollen, ueber den echten HTTPS-Dienst.

Nur lesend. Benutzer kommen als Argumente (keine Echtnamen im Repo):

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_wissensgraph_rechte_dev.py \\
        <gruppen-editor> <seine-gruppe> [<fremde-gruppe>]

* globaler Wissenseditor (``jarvis`` – lokaler Admin, auf DEV als Editor
  eingetragen): Zugang ``global``, Export erlaubt;
* Gruppen-Editor: Zugang ``gruppen``, JEDE Quelle in Graph, Detail und
  Widerspruechen liegt in seiner Gruppe, fremde Gruppe im Filter → 403,
  Pflege/Export/Steuerung → 403;
* ein Name ohne jede Rolle: ueberall 403, Zugang ``keine``.
"""
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, "/opt/jarvis")
if len(sys.argv) < 3:
    print("ABBRUCH – Aufruf: live_wissensgraph_rechte_dev.py <gruppen-editor> <gruppe> [<fremde-gruppe>]")
    sys.exit(2)
EDITOR, GRUPPE = sys.argv[1], sys.argv[2]
FREMD_GRUPPE = sys.argv[3] if len(sys.argv) > 3 else ""
sys.argv = ["x"]
from backend import knowledge_groups as KG                         # noqa: E402
from backend import main as M                                      # noqa: E402
from backend import wissensgraph as WG                             # noqa: E402

BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, cond, info=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % str(info)[:300]) if info else ""))


TOK = {"global": M.generate_token("jarvis"), "gruppe": M.generate_token(EDITOR),
       "keine": M.generate_token("probe.ohne.wissensrolle")}


def ruf(pfad, wer, methode="GET", rumpf=None):
    r = urllib.request.Request(BASIS + pfad, method=methode,
                               data=None if rumpf is None else json.dumps(rumpf).encode())
    r.add_header("Authorization", "Bearer " + TOK[wer])
    if rumpf is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=300) as a:
            roh = a.read()
            try:
                return a.status, json.loads(roh.decode() or "{}")
            except Exception:                                      # noqa: BLE001
                return a.status, {"_roh": len(roh)}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}


print("1. Positivkontrolle")
s, zg = ruf("/api/wissensgraph/zugang", "global")
check("globaler Wissenseditor: Zugang global", s == 200 and zg.get("stufe") == "global", (s, zg))
s, ze = ruf("/api/wissensgraph/zugang", "gruppe")
check("Gruppen-Editor: Zugang gruppen mit seiner Gruppe",
      s == 200 and ze.get("stufe") == "gruppen" and GRUPPE in [g["id"] for g in ze.get("gruppen", [])], (s, ze))
if ze.get("stufe") != "gruppen":
    print("ABBRUCH – der angegebene Benutzer ist hier kein Gruppen-Editor; die Folgepruefungen waeren nicht deutbar")
    sys.exit(2)
erlaubt = set(KG.filter_paths_by_groups(sorted(WG.quellen_index()), [g["id"] for g in ze["gruppen"]]))
check("Positivkontrolle: seine Gruppen enthalten Graph-Quellen", len(erlaubt) > 0, len(erlaubt))
s, gg = ruf("/api/wissensgraph/graph?limit=20000&dokumente=true", "global")
check("global: Graph lesbar", s == 200 and gg.get("knoten"), s)

print("2. Gruppen-Editor sieht nur seine Dokumente")
s, ge = ruf("/api/wissensgraph/graph?limit=20000&dokumente=true", "gruppe")
check("Graph lesbar", s == 200, s)
quellen = {q for k in ge.get("knoten", []) for q in k.get("sources", [])}
check("Positivkontrolle: Ausschnitt enthaelt Begriffe", len(ge.get("knoten", [])) > 0, len(ge.get("knoten", [])))
check("jede Quelle der Knoten liegt in seinen Gruppen", quellen <= erlaubt, sorted(quellen - erlaubt)[:5])
kq = {q for e in ge.get("kanten", []) for q in e.get("sources", [])}
check("jede Kante ist durch ein eigenes Dokument belegt", kq <= erlaubt, sorted(kq - erlaubt)[:5])
check("weniger Begriffe als global (Ausschnitt greift)", len(ge.get("knoten", [])) < len(gg.get("knoten", [])),
      (len(ge.get("knoten", [])), len(gg.get("knoten", []))))
eigen_ids = {k["id"] for k in ge.get("knoten", [])}
fremd = next((k for k in gg.get("knoten", []) if k["typ"] != "quelle" and not set(k["sources"]) & erlaubt), None)
if fremd:
    s, _d = ruf("/api/wissensgraph/knoten/" + urllib.parse.quote(fremd["id"]), "gruppe")
    check("Detail eines Begriffs nur aus fremden Gruppen → 404", s == 404, s)
    s, _d = ruf("/api/wissensgraph/wiki/" + urllib.parse.quote(fremd["id"]), "gruppe")
    check("Wiki-Seite eines fremden Begriffs → 404", s == 404, s)
gemischt = next((k for k in gg.get("knoten", []) if k["typ"] != "quelle" and set(k["sources"]) & erlaubt
                 and set(k["sources"]) - erlaubt), None)
if gemischt:
    s, d = ruf("/api/wissensgraph/knoten/" + urllib.parse.quote(gemischt["id"]), "gruppe")
    roh = json.dumps(d, ensure_ascii=False)
    fremde_pfade = [q for q in set(gemischt["sources"]) - erlaubt if q in roh]
    check("Detail eines gemischten Begriffs: keine fremde Quelle darin", s == 200 and not fremde_pfade, (s, fremde_pfade[:3]))
    s, _w = ruf("/api/wissensgraph/wiki/" + urllib.parse.quote(gemischt["id"]), "gruppe")
    check("Wiki-Seite eines gemischten Begriffs: gesperrt (403) oder keine (404)", s in (403, 404), s)
else:
    print("     (kein gemischter Begriff im Bestand – Fall nicht pruefbar)")
s, w = ruf("/api/wissensgraph/widersprueche", "gruppe")
check("Widersprueche: nur Paare aus eigenen Dokumenten", s == 200 and all(
    b["a"] in erlaubt and b["b"] in erlaubt for b in w.get("befunde", [])), s)
if FREMD_GRUPPE:
    s, _x = ruf("/api/wissensgraph/graph?gruppe=" + urllib.parse.quote(FREMD_GRUPPE), "gruppe")
    check("fremde Gruppe im Filter → 403", s == 403, s)
for m, pfad, rumpf in (("GET", "/api/wissensgraph/pruefliste", None), ("GET", "/api/wissensgraph/export", None),
                       ("POST", "/api/wissensgraph/zusammenfuehren", {"quelle": "e:x", "ziel": "e:y"}),
                       ("GET", "/api/wissensgraph/status", None), ("GET", "/api/wissensgraph/einstellungen", None),
                       ("POST", "/api/wissensgraph/neuaufbau", {"umfang": "eingestellt"})):
    s, _x = ruf(pfad, "gruppe", m, rumpf)
    check("Gruppen-Editor: %s %s → 403" % (m, pfad), s == 403, s)

print("3. Ohne Wissensrolle")
s, zk = ruf("/api/wissensgraph/zugang", "keine")
check("Zugang keine", s == 200 and zk.get("stufe") == "keine" and not zk.get("steuern"), zk)
for pfad in ("/api/wissensgraph/graph", "/api/wissensgraph/widersprueche", "/api/wissensgraph/rueckmeldung",
             "/api/wissensgraph/export", "/api/wissensgraph/status"):
    s, _x = ruf(pfad, "keine")
    check("ohne Rolle: GET %s → 403" % pfad, s == 403, s)

print("4. Globaler Wissenseditor")
s, x = ruf("/api/wissensgraph/export", "global")
check("Export erlaubt", s == 200, s)

print("\nErgebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
